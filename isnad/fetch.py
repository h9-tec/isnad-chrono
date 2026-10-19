"""Fetch queue, enumeration, and fetchers. The only module that touches the network."""

import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx

from isnad import pageprops

BASE = "https://hdith.com"
USER_AGENT = "isnad-chrono/0.1 (+https://github.com/h9-tec/isnad-chrono)"
FIRECRAWL = "https://api.firecrawl.dev/v2/batch/scrape"
BATCH_SIZE = 100
ENV_PATH = Path("~/.config/isnad-chrono/.env").expanduser()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, kind TEXT, id INTEGER, book TEXT, status TEXT,
    path TEXT, fetched_at TEXT, http_status INTEGER, entry_kind TEXT
)
"""


class Queue:
    def __init__(self, db_path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(_SCHEMA)
        self._db.commit()

    def add(self, url, kind, id=None, book=None, entry_kind=None):
        self._db.execute(
            "INSERT OR IGNORE INTO pages (url, kind, id, book, status, entry_kind)"
            " VALUES (?, ?, ?, ?, 'pending', ?)",
            (url, kind, id, book, entry_kind),
        )
        self._db.commit()

    def pending(self, kind=None, book=None, limit=None, include_passages=False) -> list[str]:
        sql, args = "SELECT url FROM pages WHERE status = 'pending'", []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if book:
            sql += " AND book = ?"
            args.append(book)
        if not include_passages:
            sql += " AND (entry_kind IS NULL OR entry_kind != 'passage')"
        sql += " ORDER BY rowid"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [r[0] for r in self._db.execute(sql, args)]

    def mark(self, url, status, path=None, http_status=None):
        self._db.execute(
            "UPDATE pages SET status = ?, path = ?, http_status = ?, fetched_at = ? WHERE url = ?",
            (status, str(path) if path else None, http_status,
             datetime.now(timezone.utc).isoformat(), url),
        )
        self._db.commit()

    def info(self, url) -> tuple[str, int]:
        return self._db.execute("SELECT kind, id FROM pages WHERE url = ?", (url,)).fetchone()

    def counts(self) -> dict[str, int]:
        return dict(self._db.execute("SELECT status, COUNT(*) FROM pages GROUP BY status"))

    def counts_by(self, kind=None, book=None) -> dict[str, int]:
        sql, args = "SELECT status, COUNT(*) FROM pages WHERE 1=1", []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if book:
            sql += " AND book = ?"
            args.append(book)
        return dict(self._db.execute(sql + " GROUP BY status", args))


# ---------- fetchers ----------

def _forbidden(url: str) -> bool:
    return "/embed/" in url or re.search(r"/encyclopedia/[^?]*-preview/?", url) is not None


class LocalFetcher:
    """httpx fetcher: <= `rate` requests/s, 3 retries on 5xx and timeouts."""

    def __init__(self, client: httpx.Client, rate: float = 3.0, sleep: Callable = time.sleep,
                 retries: int = 3, backoff: float = 1.0):
        self.client = client
        self.interval = 1.0 / rate
        self._sleep = sleep
        self.retries = retries
        self.backoff = backoff
        self._next = 0.0
        self._headers = {"User-Agent": USER_AGENT}

    def _throttle(self):
        now = time.monotonic()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = max(now, self._next) + self.interval

    def request(self, method: str, url: str, **kw) -> httpx.Response | None:
        """Throttled request with retries; None if every attempt timed out."""
        if _forbidden(url):
            return None
        resp = None
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.backoff * 2 ** (attempt - 1))
            self._throttle()
            try:
                resp = self.client.request(method, url, headers=self._headers, **kw)
            except httpx.TimeoutException:
                resp = None
                continue
            if resp.status_code < 500:
                return resp
        return resp

    def get(self, url: str) -> httpx.Response | None:
        return self.request("GET", url)

    def head(self, url: str) -> httpx.Response | None:
        return self.request("HEAD", url)

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for url in urls:
            resp = self.get(url)
            if resp is not None:
                out[url] = (resp.status_code, resp.text)
        return out


class FirecrawlFetcher:
    def __init__(self, api_key: str, client: httpx.Client, sleep: Callable = time.sleep,
                 poll_interval: float = 5.0, max_polls: int = 1440):
        self.client = client
        self._sleep = sleep
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for i in range(0, len(urls), BATCH_SIZE):
            out.update(self._batch(urls[i:i + BATCH_SIZE]))
        return out

    def _batch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        resp = self.client.post(FIRECRAWL, headers=self._headers,
                                json={"urls": urls, "formats": ["rawHtml"]}, timeout=60)
        resp.raise_for_status()
        job = resp.json()["id"]
        poll_url = f"{FIRECRAWL}/{job}"
        for _ in range(self.max_polls):
            resp = self.client.get(poll_url, headers=self._headers, timeout=60)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") == "completed":
                break
            if body.get("status") in ("failed", "cancelled"):
                raise RuntimeError(f"firecrawl batch {job} {body['status']}")
            self._sleep(self.poll_interval)
        else:
            raise TimeoutError(f"firecrawl batch {job} did not complete")
        out = {}
        while True:
            for d in body.get("data") or []:
                meta = d.get("metadata") or {}
                src = meta.get("sourceURL") or meta.get("url")
                if src is not None:
                    out[src] = (meta.get("statusCode"), d.get("rawHtml") or "")
            nxt = body.get("next")
            if not nxt:
                return out
            resp = self.client.get(nxt, headers=self._headers, timeout=60)
            resp.raise_for_status()
            body = resp.json()


# ---------- enumeration ----------

def load_rawi_sitemap(fetcher: LocalFetcher) -> Iterator[tuple[str, int]]:
    resp = fetcher.get(f"{BASE}/sitemap-rawis.xml")
    resp.raise_for_status()
    for url in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text):
        m = re.search(r"/p-(\d+)", url)
        if m:
            yield url, int(m.group(1))


def list_books(fetcher: LocalFetcher) -> list[str]:
    resp = fetcher.get(f"{BASE}/encyclopedia/books.md")
    resp.raise_for_status()
    return [f"b-{n}" for n in dict.fromkeys(re.findall(r"book/b-(\d+)", resp.text))]


def _props(fetcher: LocalFetcher, url: str) -> dict:
    resp = fetcher.get(url)
    if resp is None:
        raise RuntimeError(f"timed out: {url}")
    resp.raise_for_status()
    return pageprops.extract(resp.text)


def hadith_url(book: str, id: int) -> str:
    return f"{BASE}/encyclopedia/book/{book}/h/{id}"


def enumerate_book(fetcher: LocalFetcher, queue: Queue, book: str) -> int:
    """Enqueue every hadith/passage of a book; returns the number of rows found."""
    root = f"{BASE}/encyclopedia/book/{book}"
    top = _props(fetcher, root)
    chapters, stats = top["chapters"], top["stats"]
    found: dict[int, str | None] = {}
    headings: set[int] = {c["id"] for c in chapters}

    def collect(p: dict):
        for h in p.get("hadiths") or []:
            found[h["id"]] = h.get("kind")
        for g in p.get("hadith_groups") or []:
            for h in g.get("hadiths") or []:
                found[h["id"]] = h.get("kind")

    for ch in chapters:
        page = _props(fetcher, f"{root}?chapter={ch['id']}")
        collect(page)
        for g in page.get("hadith_groups") or []:
            headings.add(g["id"])
            collect(_props(fetcher, f"{root}?chapter={g['id']}"))

    # stats["hadiths"] counts hadith and passage entries together (b-2: 7651 + 15 = 7666)
    if len(found) < stats["hadiths"]:
        bounds = [c["id"] for c in chapters] + [chapters[0]["id"] + stats["entries"]]
        for lo, hi in zip(bounds, bounds[1:]):
            for i in range(lo + 1, hi):
                if i in found or i in headings:
                    continue
                resp = fetcher.head(hadith_url(book, i))
                if resp is not None and resp.status_code == 200:
                    found[i] = None

    for i, kind in found.items():
        queue.add(hadith_url(book, i), "hadith", id=i, book=book, entry_kind=kind)
    return len(found)


# ---------- run ----------

def run_fetch(queue: Queue, fetcher, kind: str, book=None, limit=None,
              cache_root="data/raw/html", include_passages=False) -> None:
    root = Path(cache_root) / kind
    root.mkdir(parents=True, exist_ok=True)
    todo = []
    for url in queue.pending(kind=kind, book=book, limit=limit, include_passages=include_passages):
        path = root / f"{queue.info(url)[1]}.html"
        if path.exists():
            queue.mark(url, "ok", path=path)
        else:
            todo.append(url)
    if not todo:
        return
    for url, (status, html) in fetcher.fetch(todo).items():
        if url not in todo:
            continue
        path = root / f"{queue.info(url)[1]}.html"
        if status == 200:
            path.write_text(html, encoding="utf-8")
            queue.mark(url, "ok", path=path, http_status=status)
        elif status == 404:
            queue.mark(url, "404", http_status=status)
        else:
            queue.mark(url, "error", http_status=status)


def read_api_key(env_path=ENV_PATH) -> str:
    for line in Path(env_path).read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "FIRECRAWL_API_KEY":
            return value.strip().strip("'\"")
    raise KeyError("FIRECRAWL_API_KEY not found")
