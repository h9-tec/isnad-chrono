"""Fetch queue, enumeration, and fetchers. The only module that touches the network."""

import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
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
_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, kind TEXT, n INTEGER, first_url TEXT, last_url TEXT,
    submitted_at TEXT, status TEXT
)
"""
MAX_ATTEMPTS = 3
DB_TIMEOUT = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobLedger:
    """Records every submitted Firecrawl job (the only handle on credits already spent)."""

    def __init__(self, queue: "Queue", kind: str):
        self.queue, self.kind = queue, kind

    def job_submitted(self, job_id: str, urls: list[str]) -> None:
        self.queue.record_job(job_id, self.kind, urls)

    def job_status(self, job_id: str, status: str) -> None:
        self.queue.set_job_status(job_id, status)


class Queue:
    def __init__(self, db_path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, timeout=DB_TIMEOUT)
        try:  # don't wait on the busy handler: a concurrent old-mode connection may hold the file
            self._db.execute("PRAGMA busy_timeout = 0")
            self._db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        finally:
            self._db.execute(f"PRAGMA busy_timeout = {DB_TIMEOUT * 1000}")
        self._db.execute(_SCHEMA)
        self._db.execute(_BOOKS)
        self._db.execute(_JOBS)
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

    def ledger(self, kind: str) -> JobLedger:
        return JobLedger(self, kind)

    def record_job(self, job_id, kind, urls, status="submitted") -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO jobs (job_id, kind, n, first_url, last_url, submitted_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, len(urls), urls[0] if urls else None, urls[-1] if urls else None,
             _now(), status))
        self._db.commit()

    def set_job_status(self, job_id, status) -> None:
        self._db.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
        self._db.commit()

    def jobs(self) -> list[dict]:
        cur = self._db.execute("SELECT * FROM jobs ORDER BY submitted_at, rowid")
        names = [c[0] for c in cur.description]
        return [dict(zip(names, r)) for r in cur]

    def job(self, job_id) -> dict | None:
        return next((j for j in self.jobs() if j["job_id"] == job_id), None)

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
            (status, str(path) if path else None, http_status, _now(), url),
        )
        self._db.commit()

    def info(self, url) -> tuple[str, int] | None:
        return self._db.execute("SELECT kind, id FROM pages WHERE url = ?", (url,)).fetchone()

    def status(self, url) -> str | None:
        row = self._db.execute("SELECT status FROM pages WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None

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
    """httpx fetcher: <= `rate` requests/s, 5 retries (2/4/8/16/32 s backoff) on 5xx, timeouts and transport errors."""

    def __init__(self, client: httpx.Client, rate: float = 3.0, sleep: Callable = time.sleep,
                 retries: int = 5, backoff: float = 2.0, timeout: float = 120.0):
        self.client = client
        self.interval = 1.0 / rate
        self._sleep = sleep
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
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
                resp = self.client.request(method, url, headers=self._headers,
                                           timeout=self.timeout, **kw)
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

    def iter_fetch(self, urls: list[str]) -> Iterator[tuple[list[str], dict[str, tuple[int, str]]]]:
        """Yield ([url], {url: (status, html)}) per URL so callers can persist incrementally.

        The result dict is empty when every attempt timed out (or the URL is forbidden).
        """
        for url in urls:
            resp = self.get(url)
            yield [url], ({url: (resp.status_code, resp.text)} if resp is not None else {})

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for _, chunk in self.iter_fetch(urls):
            out.update(chunk)
        return out


class FirecrawlFetcher:
    def __init__(self, api_key: str, client: httpx.Client, batch_size: int = BATCH_SIZE,
                 concurrency: int = 1, poll_interval: float = 5.0,
                 sleep: Callable = time.sleep, max_polls: int = 1440, retries: int = 3,
                 ledger: JobLedger | None = None, log: Callable = print):
        self.client = client
        self.ledger = ledger  # job_submitted(job_id, urls) / job_status(job_id, status)
        self._log = log
        self._sleep = sleep
        self.batch_size = batch_size
        self.concurrency = max(1, concurrency)
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.retries = retries
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _status(self, job: str, status: str) -> None:
        if self.ledger is not None:
            self.ledger.job_status(job, status)

    def iter_fetch(self, urls: list[str]) -> Iterator[tuple[list[str], dict[str, tuple[int, str]]]]:
        """Run up to `concurrency` batch jobs at once, polled round-robin.

        Yields (requested_urls, results) for each job as soon as it completes. After a job
        fails, no new jobs are submitted; the others are drained and yielded, then the first
        error is raised. Job statuses go to the ledger: submitted -> collected (results fetched)
        -> persisted (the consumer finished with the chunk), or failed/timeout/error.
        """
        batches = [urls[i:i + self.batch_size] for i in range(0, len(urls), self.batch_size)]
        batches.reverse()  # pop() takes the next batch in order
        inflight: dict[str, list] = {}  # job id -> [polls so far, requested urls]
        error: Exception | None = None

        def fail(e: Exception, job: str | None):
            nonlocal error
            if job is not None:
                e.add_note(f"firecrawl job {job}")
            error = error or e

        while inflight or (batches and error is None):
            while batches and len(inflight) < self.concurrency and error is None:
                try:
                    inflight[self._submit(batches[-1])] = [0, batches[-1]]
                    batches.pop()
                except Exception as e:
                    fail(e, None)
            for job in list(inflight):
                try:
                    body = self._get(f"{FIRECRAWL}/{job}")
                    status = body.get("status")
                    if status == "completed":
                        out = self._collect(body)
                        requested = inflight.pop(job)[1]
                        self._status(job, "collected")
                        yield requested, out
                        self._status(job, "persisted")
                        continue
                    if status in ("failed", "cancelled"):
                        inflight.pop(job)
                        self._status(job, status)
                        raise RuntimeError(f"firecrawl batch {job} {status}")
                    inflight[job][0] += 1
                    if inflight[job][0] >= self.max_polls:
                        inflight.pop(job)
                        self._status(job, "timeout")
                        raise TimeoutError(f"firecrawl batch {job} did not complete")
                except Exception as e:
                    if inflight.pop(job, None) is not None:  # HTTP error while polling
                        self._status(job, "error")
                    fail(e, job)
            if inflight:
                self._sleep(self.poll_interval)
        if error is not None:
            raise error

    def fetch(self, urls: list[str]) -> dict[str, tuple[int, str]]:
        out = {}
        for _, chunk in self.iter_fetch(urls):
            out.update(chunk)
        return out

    def recover(self, job_id: str) -> dict[str, tuple[int, str]]:
        """GET an existing job and return its results; raises if it is not completed."""
        body = self._get(f"{FIRECRAWL}/{job_id}")
        status = body.get("status")
        if status != "completed":
            raise RuntimeError(f"firecrawl job {job_id} is {status!r}, not completed")
        return self._collect(body)

    def _request(self, method: str, url: str, on_timeout: Callable | None = None, **kw) -> dict:
        """Request with retry on 429/5xx/transport errors (backoff poll_interval * 2**k)."""
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.poll_interval * 2 ** (attempt - 1))
            try:
                resp = self.client.request(method, url, headers=self._headers, timeout=60, **kw)
            except httpx.TransportError as e:
                if on_timeout is not None and isinstance(e, httpx.TimeoutException):
                    on_timeout()
                if attempt == self.retries:
                    raise
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.retries:
                    resp.raise_for_status()
                continue
            resp.raise_for_status()
            return resp.json()

    def _get(self, url: str) -> dict:
        """GET with retry: the job id is the only handle on spent credits."""
        return self._request("GET", url)

    def _submit(self, urls: list[str]) -> str:
        """POST a batch job with retry (a 429 creates no job). A timed-out POST may still have
        created a job, so it is logged with the batch's first/last URL before retrying."""
        def timed_out():
            self._log(f"firecrawl POST timed out; a job may exist: n={len(urls)} "
                      f"first={urls[0]} last={urls[-1]}", flush=True)

        body = self._request("POST", FIRECRAWL, on_timeout=timed_out,
                             json={"urls": urls, "formats": ["rawHtml"]})
        job = body["id"]
        self._log(f"firecrawl job {job} submitted: n={len(urls)} first={urls[0]} last={urls[-1]}",
                  flush=True)
        if self.ledger is not None:
            self.ledger.job_submitted(job, urls)
        return job

    def _collect(self, body: dict) -> dict[str, tuple[int, str]]:
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
    failed_chapters: list[int] = field(default_factory=list)

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

    failed_chapters: list[int] = []

    def chapter(cid: int) -> dict | None:
        try:
            return _props(fetcher, f"{root}?chapter={cid}")
        except (RuntimeError, httpx.HTTPError):  # one bad page must not abort the book
            failed_chapters.append(cid)
            return None

    for ch in chapters:
        page = chapter(ch["id"])
        if page is None:
            continue
        collect(page)
        for g in page.get("hadith_groups") or []:
            headings.add(g["id"])
            sub = chapter(g["id"])
            if sub is not None:
                collect(sub)

    # stats["hadiths"] counts hadith and passage entries together (b-2: 7651 + 15 = 7666)
    # with failed chapters the listing is knowingly incomplete: skip probing, the re-run redoes it
    if len(found) < stats["hadiths"] and not failed_chapters:
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

    return Enumerated(len(found), stats["hadiths"], failed_chapters)


# ---------- run ----------

@dataclass
class FetchStats:
    missing: int = 0  # requested but absent from the results (counted as a transient failure)
    unmatched: int = 0  # results whose sourceURL matched no requested/queued URL (discarded)


def _persist(queue: Queue, root: Path, url: str, status, html) -> None:
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


def run_fetch(queue: Queue, fetcher, kind: str, book=None, limit=None,
              cache_root="data/raw/html", include_passages=False, log: Callable = print) -> FetchStats:
    root = Path(cache_root) / kind
    root.mkdir(parents=True, exist_ok=True)
    stats = FetchStats()
    todo = []
    for url in queue.pending(kind=kind, book=book, limit=limit, include_passages=include_passages):
        path = root / f"{queue.info(url)[1]}.html"
        if path.exists():
            queue.mark(url, "ok", path=path)
        else:
            todo.append(url)
    if not todo:
        return stats
    if getattr(fetcher, "ledger", False) is None:
        fetcher.ledger = queue.ledger(kind)
    pending = set(todo)
    try:
        for requested, chunk in fetcher.iter_fetch(todo):  # persist after every batch / URL
            for url, (status, html) in chunk.items():
                if url not in pending:
                    stats.unmatched += 1
                    continue
                _persist(queue, root, url, status, html)
            for url in requested:
                if url in pending and url not in chunk:
                    stats.missing += 1
                    queue.record_transient(url, None)
    finally:
        if stats.missing or stats.unmatched:
            log(f"fetch: {stats.missing} requested URLs missing from results (retried later), "
                f"{stats.unmatched} unmatched sourceURLs discarded", flush=True)
    return stats


def recover_job(queue: Queue, fetcher: "FirecrawlFetcher", job_id: str, kind: str | None = None,
                cache_root="data/raw/html", log: Callable = print) -> FetchStats:
    """Persist the results of an already-paid Firecrawl job through the normal path.

    URLs already `ok` are left alone; results for URLs not in the queue are discarded and counted.
    """
    row = queue.job(job_id)
    kind = kind or (row["kind"] if row else None)
    if kind is None:
        raise ValueError(f"job {job_id} is not in the ledger; pass --kind")
    root = Path(cache_root) / kind
    root.mkdir(parents=True, exist_ok=True)
    stats = FetchStats()
    persisted = 0
    for url, (status, html) in fetcher.recover(job_id).items():
        info = queue.info(url)
        if info is None or info[0] != kind:
            stats.unmatched += 1
            continue
        if queue.status(url) == "ok":
            continue
        _persist(queue, root, url, status, html)
        persisted += 1
    if row is None:
        queue.record_job(job_id, kind, [], status="recovered")
    else:
        queue.set_job_status(job_id, "recovered")
    log(f"recovered job {job_id}: {persisted} results persisted, "
        f"{stats.unmatched} unmatched sourceURLs discarded", flush=True)
    return stats


def read_api_key(env_path=ENV_PATH) -> str:
    for line in Path(env_path).read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "FIRECRAWL_API_KEY":
            return value.strip().strip("'\"")
    raise KeyError("FIRECRAWL_API_KEY not found")
