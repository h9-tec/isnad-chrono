"""Fetch queue, enumeration, and fetchers. The only module that touches the network."""

import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from isnad import pageprops
from isnad.pageprops import _PAGE_RE

BASE = "https://hdith.com"
USER_AGENT = "isnad-chrono/0.1 (+https://github.com/h9-tec/isnad-chrono)"
FIRECRAWL = "https://api.firecrawl.dev/v2/batch/scrape"
BATCH_SIZE = 100
ENV_PATH = Path("~/.config/isnad-chrono/.env").expanduser()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, kind TEXT, id INTEGER, book TEXT, status TEXT,
    path TEXT, fetched_at TEXT, http_status INTEGER, entry_kind TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
)
"""
_BOOKS = """
CREATE TABLE IF NOT EXISTS books (
    book TEXT PRIMARY KEY, status TEXT, found INTEGER, expected INTEGER
)
"""
MAX_ATTEMPTS = 3


class Queue:
    def __init__(self, db_path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(_SCHEMA)
        self._db.execute(_BOOKS)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(pages)")}
        if "attempts" not in cols:  # migrate databases created before retries existed
            self._db.execute("ALTER TABLE pages ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        self._db.commit()

    def record_transient(self, url, http_status=None) -> str:
        """Count a failed attempt; stays pending until MAX_ATTEMPTS, then becomes error."""
        self._db.execute(
            "UPDATE pages SET attempts = attempts + 1, http_status = ? WHERE url = ?",
            (http_status, url),
        )
        (n,) = self._db.execute("SELECT attempts FROM pages WHERE url = ?", (url,)).fetchone()
        status = "error" if n >= MAX_ATTEMPTS else "pending"
        self.mark(url, status, http_status=http_status)
        return status

    def reset_errors(self) -> int:
        cur = self._db.execute(
            "UPDATE pages SET status = 'pending', attempts = 0 WHERE status = 'error'")
        self._db.commit()
        return cur.rowcount

    def book_done(self, book) -> bool:
        row = self._db.execute("SELECT status FROM books WHERE book = ?", (book,)).fetchone()
        return row is not None and row[0] == "done"

    def mark_book(self, book, status, found=None, expected=None):
        self._db.execute(
            "INSERT OR REPLACE INTO books (book, status, found, expected) VALUES (?, ?, ?, ?)",
            (book, status, found, expected))
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
            except httpx.TransportError:
                resp = None
                continue
            if resp.status_code < 500:
                return resp
        return resp

    def get(self, url: str) -> httpx.Response | None:
        return self.request("GET", url)

    def head(self, url: str) -> httpx.Response | None:
        return self.request("HEAD", url)

    def iter_fetch(self, urls: list[str]) -> Iterator[dict[str, tuple[int, str]]]:
        """Yield one {url: (status, html)} per URL so callers can persist incrementally."""
        for url in urls:
            resp = self.get(url)
            yield {url: (resp.status_code, resp.text)} if resp is not None else {}

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for chunk in self.iter_fetch(urls):
            out.update(chunk)
        return out


class FirecrawlFetcher:
    def __init__(self, api_key: str, client: httpx.Client, sleep: Callable = time.sleep,
                 poll_interval: float = 5.0, max_polls: int = 1440, retries: int = 3):
        self.client = client
        self._sleep = sleep
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.retries = retries
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def iter_fetch(self, urls: list[str]) -> Iterator[dict[str, tuple[int, str]]]:
        """Yield the results of each 100-URL batch as soon as it completes."""
        for i in range(0, len(urls), BATCH_SIZE):
            yield self._batch(urls[i:i + BATCH_SIZE])

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for chunk in self.iter_fetch(urls):
            out.update(chunk)
        return out

    def _get(self, url: str) -> dict:
        """GET with retry on 429/5xx/network errors: the job id is the only handle on spent credits."""
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.poll_interval * 2 ** (attempt - 1))
            try:
                resp = self.client.get(url, headers=self._headers, timeout=60)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.retries:
                    resp.raise_for_status()
                continue
            resp.raise_for_status()
            return resp.json()

    def _batch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        resp = self.client.post(FIRECRAWL, headers=self._headers,
                                json={"urls": urls, "formats": ["rawHtml"]}, timeout=60)
        resp.raise_for_status()
        job = resp.json()["id"]
        poll_url = f"{FIRECRAWL}/{job}"
        for _ in range(self.max_polls):
            body = self._get(poll_url)
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
            body = self._get(nxt)


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


class ProbeError(RuntimeError):
    """A HEAD probe failed (timeout or 5xx), so absence cannot be concluded."""


@dataclass(frozen=True, slots=True)
class Enumerated:
    found: int
    expected: int  # props.stats.hadiths (hadith + passage entries)

    @property
    def shortfall(self) -> int:
        return max(0, self.expected - self.found)


def enumerate_book(fetcher: LocalFetcher, queue: Queue, book: str) -> Enumerated:
    """Enqueue every hadith/passage of a book (per chapter, so progress survives a crash)."""
    root = f"{BASE}/encyclopedia/book/{book}"
    top = _props(fetcher, root)
    chapters, stats = top["chapters"], top["stats"]
    found: dict[int, str | None] = {}
    headings: set[int] = {c["id"] for c in chapters}

    def collect(p: dict):
        for h in (p.get("hadiths") or []):
            found[h["id"]] = h.get("kind")
            queue.add(hadith_url(book, h["id"]), "hadith", id=h["id"], book=book, entry_kind=h.get("kind"))
        for g in p.get("hadith_groups") or []:
            collect({"hadiths": g.get("hadiths")})

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
                if resp is None or resp.status_code >= 500:
                    raise ProbeError(f"{book}: probe of id {i} failed")
                if resp.status_code == 200:
                    found[i] = None
                    queue.add(hadith_url(book, i), "hadith", id=i, book=book, entry_kind=None)

    return Enumerated(len(found), stats["hadiths"])


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
    pending = set(todo)
    for chunk in fetcher.iter_fetch(todo):  # persist after every batch / URL
        for url, (status, html) in chunk.items():
            if url not in pending:
                continue
            path = root / f"{queue.info(url)[1]}.html"
            if status == 200:
                if _PAGE_RE.search(html or ""):
                    path.write_text(html, encoding="utf-8")
                    queue.mark(url, "ok", path=path, http_status=status)
                else:  # empty body / challenge page: never cache it as ok
                    queue.mark(url, "error", http_status=status)
            elif status == 404:
                queue.mark(url, "404", http_status=status)
            elif status is None or status == 429 or status >= 500:
                queue.record_transient(url, status)
            else:
                queue.mark(url, "error", http_status=status)


def read_api_key(env_path=ENV_PATH) -> str:
    for line in Path(env_path).read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "FIRECRAWL_API_KEY":
            return value.strip().strip("'\"")
    raise KeyError("FIRECRAWL_API_KEY not found")
