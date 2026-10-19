import json
import time

import httpx
import pytest

from isnad import fetch
from isnad.fetch import (
    FirecrawlFetcher,
    LocalFetcher,
    ProbeError,
    Queue,
    enumerate_book,
    load_rawi_sitemap,
    run_fetch,
)

BASE = "https://hdith.com"
FC = "https://api.firecrawl.dev/v2/batch/scrape"


def page_html(props: dict) -> str:
    data = {"component": "X", "props": props}
    return f'<html><script data-page="app" type="application/json">{json.dumps(data)}</script></html>'


def local(client, rate=1000.0):
    return LocalFetcher(client, rate=rate, sleep=lambda s: None)


GOOD = page_html({"x": 1})


# ---------- queue ----------

def test_queue_basics(tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    q.add("u1", "rawi", id=1)
    q.add("u1", "rawi", id=1)  # idempotent
    q.add("u2", "hadith", id=2, book="b-2", entry_kind="passage")
    q.add("u3", "hadith", id=3, book="b-2", entry_kind="hadith")
    assert q.pending() == ["u1", "u3"] or set(q.pending()) == {"u1", "u3"}
    assert set(q.pending(include_passages=True)) == {"u1", "u2", "u3"}
    assert q.pending(kind="hadith", book="b-2") == ["u3"]
    assert len(q.pending(limit=1)) == 1
    q.mark("u1", "ok", path="p", http_status=200)
    assert q.counts() == {"ok": 1, "pending": 2}
    assert q.info("u3") == ("hadith", 3)


# ---------- rawi sitemap ----------

def test_sitemap_rawis(httpx_mock):
    xml = (
        '<urlset><url><loc>https://hdith.com/encyclopedia/rawi/p-4494</loc></url>'
        '<url><loc>https://hdith.com/encyclopedia/rawi/p-7</loc></url></urlset>'
    )
    httpx_mock.add_response(url=f"{BASE}/sitemap-rawis.xml", text=xml)
    with httpx.Client() as c:
        rows = list(load_rawi_sitemap(local(c)))
    assert rows == [
        ("https://hdith.com/encyclopedia/rawi/p-4494", 4494),
        ("https://hdith.com/encyclopedia/rawi/p-7", 7),
    ]


# ---------- book enumeration ----------

def book_mocks(httpx_mock, listed):
    """Kitab 100 (hadith 101, bab 102 with hadith 103) and kitab 104 (hadith 105, passage 106).

    ids 100..106 -> entries 7; stats.hadiths counts hadith+passage = 4.
    """
    kinds = {101: "hadith", 103: "hadith", 105: "hadith", 106: "passage"}
    item = lambda i: {"id": i, "kind": kinds[i]}
    book = {
        "book": {"slug": "b-2", "title": "t"},
        "chapters": [{"id": 100, "t": "k1", "count": 2}, {"id": 104, "t": "k2", "count": 2}],
        "stats": {"hadiths": 4, "entries": 7},
        "hadiths": [], "hadith_groups": [],
    }
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2", text=page_html(book))
    ch1 = dict(book, hadiths=[item(101)] if 101 in listed else [],
               hadith_groups=[{"id": 102, "depth": 1, "title": "bab", "hadiths": []}])
    ch2 = dict(book, hadiths=[item(i) for i in (105, 106) if i in listed], hadith_groups=[])
    bab = dict(book, hadiths=[item(103)], hadith_groups=[])
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=100", text=page_html(ch1))
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=104", text=page_html(ch2))
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=102", text=page_html(bab))


PRE = f"{BASE}/encyclopedia/book/b-2/h/"


def test_enumerate_book(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 105, 106})
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        res = enumerate_book(local(c), q, "b-2")
    assert (res.found, res.expected, res.shortfall) == (4, 4, 0)
    assert not [r for r in httpx_mock.get_requests() if r.method == "HEAD"]
    assert set(q.pending(kind="hadith", include_passages=True)) == {PRE + str(i) for i in (101, 103, 105, 106)}
    assert set(q.pending(kind="hadith")) == {PRE + str(i) for i in (101, 103, 105)}
    assert q.info(PRE + "101") == ("hadith", 101)


def test_enumerate_probe_fallback_last_chapter(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 106})  # 105 (last chapter) missing from listings
    httpx_mock.add_response(method="HEAD", url=PRE + "105", status_code=200)
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        res = enumerate_book(local(c), q, "b-2")
    assert (res.found, res.shortfall) == (4, 0)
    assert PRE + "105" in q.pending(kind="hadith")  # entry_kind NULL is fetched
    heads = [r for r in httpx_mock.get_requests() if r.method == "HEAD"]
    assert [r.url.path.rsplit("/", 1)[1] for r in heads] == ["105"]


def test_enumerate_probe_404_reports_shortfall(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 106})
    httpx_mock.add_response(method="HEAD", url=PRE + "105", status_code=404)
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        res = enumerate_book(local(c), q, "b-2")
    assert (res.found, res.shortfall) == (3, 1)


def test_enumerate_probe_failure_raises_but_keeps_rows(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 106})
    for _ in range(6):
        httpx_mock.add_response(method="HEAD", url=PRE + "105", status_code=503)
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c, pytest.raises(ProbeError):
        enumerate_book(local(c), q, "b-2")
    assert PRE + "101" in q.pending(kind="hadith")  # per-chapter progress persisted
    assert not q.book_done("b-2")


def test_enumerate_probe_timeout_raises(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 106})
    for _ in range(6):
        httpx_mock.add_exception(httpx.ReadTimeout("t"), method="HEAD", url=PRE + "105")
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c, pytest.raises(ProbeError):
        enumerate_book(local(c), q, "b-2")


def test_books_table(tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    assert not q.book_done("b-2")
    q.mark_book("b-2", "failed")
    assert not q.book_done("b-2")
    q.mark_book("b-2", "done", 4, 4)
    assert q.book_done("b-2")


# ---------- firecrawl ----------

def doc(url, status, html=page_html({})):
    return {"rawHtml": html, "metadata": {"sourceURL": url, "url": url, "statusCode": status}}


def test_firecrawl_paging_and_auth(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://api.firecrawl.dev/v2/batch/scrape",
                            json={"success": True, "id": "j1", "url": "x"})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1",
                            json={"status": "scraping", "total": 2, "completed": 0, "data": []})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1",
                            json={"status": "completed", "total": 2, "completed": 2,
                                  "data": [doc("a", 200, GOOD)], "next": "https://api.firecrawl.dev/v2/batch/scrape/j1?skip=1"})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1?skip=1",
                            json={"status": "completed", "data": [doc("b", 200, GOOD)]})
    with httpx.Client() as c:
        out = FirecrawlFetcher("KEY", c, sleep=lambda s: None).fetch(["a", "b"])
    assert out == {"a": (200, GOOD), "b": (200, GOOD)}
    assert all(r.headers["authorization"] == "Bearer KEY" for r in httpx_mock.get_requests())
    post = [r for r in httpx_mock.get_requests() if r.method == "POST"][0]
    assert json.loads(post.content) == {"urls": ["a", "b"], "formats": ["rawHtml"]}


def test_firecrawl_batches_of_100(httpx_mock):
    urls = [f"u{i}" for i in range(150)]
    httpx_mock.add_response(method="POST", url="https://api.firecrawl.dev/v2/batch/scrape",
                            json={"success": True, "id": "j"}, is_reusable=True)
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j",
                            json={"status": "completed", "data": []}, is_reusable=True)
    with httpx.Client() as c:
        FirecrawlFetcher("K", c, sleep=lambda s: None).fetch(urls)
    sizes = [len(json.loads(r.content)["urls"]) for r in httpx_mock.get_requests() if r.method == "POST"]
    assert sizes == [100, 50]


def test_batch_partial_result(httpx_mock, tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    urls = [f"https://hdith.com/encyclopedia/rawi/p-{i}" for i in (1, 2, 3)]
    for i, u in zip((1, 2, 3), urls):
        q.add(u, "rawi", id=i)
    httpx_mock.add_response(method="POST", url="https://api.firecrawl.dev/v2/batch/scrape",
                            json={"success": True, "id": "j"})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j",
                            json={"status": "completed",
                                  "data": [doc(urls[0], 200, GOOD), doc(urls[1], 404)]})
    with httpx.Client() as c:
        run_fetch(q, FirecrawlFetcher("K", c, sleep=lambda s: None), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 1, "404": 1, "pending": 1}
    assert (tmp_path / "html" / "rawi" / "1.html").read_text() == GOOD
    assert not (tmp_path / "html" / "rawi" / "2.html").exists()
    assert q.pending() == [urls[2]]


# ---------- cache / local ----------

class Boom:
    def fetch(self, urls):
        raise AssertionError("must not fetch")


def test_cache_skip(tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    q.add("https://x/rawi/p-5", "rawi", id=5)
    (tmp_path / "html" / "rawi").mkdir(parents=True)
    (tmp_path / "html" / "rawi" / "5.html").write_text("cached")
    run_fetch(q, Boom(), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 1}


def test_local_rate_limit(httpx_mock):
    urls = [f"https://hdith.com/p/{i}" for i in range(6)]
    httpx_mock.add_response(text="hi", is_reusable=True)
    with httpx.Client() as c:
        f = LocalFetcher(c, rate=3.0)
        t = time.monotonic()
        out = f.fetch(urls)
        assert time.monotonic() - t >= 1.5
    assert len(out) == 6 and out[urls[0]] == (200, "hi")
    assert httpx_mock.get_requests()[0].headers["user-agent"].startswith("isnad-chrono/0.1")


def test_local_retries_5xx_then_ok(httpx_mock):
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(text="fine")
    with httpx.Client() as c:
        assert local(c).fetch(["https://hdith.com/a"]) == {"https://hdith.com/a": (200, "fine")}


def test_local_gives_up_on_timeouts(httpx_mock):
    for _ in range(6):
        httpx_mock.add_exception(httpx.ReadTimeout("t"))
    with httpx.Client() as c:
        assert local(c).fetch(["https://hdith.com/a"]) == {}


def test_local_refuses_preview_and_embed(httpx_mock):
    with httpx.Client() as c:
        out = local(c).fetch(["https://hdith.com/encyclopedia/x-preview/", "https://hdith.com/embed/1"])
    assert out == {}
    assert httpx_mock.get_requests() == []


# ---------- run_fetch persistence / validation / retries ----------

def mkq(tmp_path, n):
    q = Queue(tmp_path / "q.sqlite")
    urls = [f"https://hdith.com/encyclopedia/rawi/p-{i}" for i in range(1, n + 1)]
    for i, u in enumerate(urls, 1):
        q.add(u, "rawi", id=i)
    return q, urls


def fc(c):
    return FirecrawlFetcher("K", c, sleep=lambda s: None)


def test_batch2_failure_keeps_batch1(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 150)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, status_code=402)
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "completed",
                            "data": [doc(u, 200, GOOD) for u in urls[:100]]})
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 100, "pending": 50}
    assert len(list((tmp_path / "html" / "rawi").glob("*.html"))) == 100


def test_failed_job_marks_nothing(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 2)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "failed"})
    with httpx.Client() as c, pytest.raises(RuntimeError):
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"pending": 2}


def test_http_error_mid_poll_after_retries(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 2)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "scraping"})
    for _ in range(4):
        httpx_mock.add_response(url=f"{FC}/j", status_code=503)
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"pending": 2}


def test_transient_poll_error_is_retried(httpx_mock):
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", status_code=429)
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [doc("a", 200, GOOD)],
                                                 "next": f"{FC}/j?skip=1"})
    httpx_mock.add_response(url=f"{FC}/j?skip=1", status_code=502)
    httpx_mock.add_response(url=f"{FC}/j?skip=1", json={"status": "completed", "data": [doc("b", 200, GOOD)]})
    with httpx.Client() as c:
        assert set(fc(c).fetch(["a", "b"])) == {"a", "b"}


def test_200_without_page_data_is_error(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 2)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [
        doc(urls[0], 200, ""), doc(urls[1], 200, "<html>Just a moment...</html>")]})
    with httpx.Client() as c:
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"error": 2}
    assert not list((tmp_path / "html" / "rawi").glob("*.html"))


def test_transient_status_retries_then_errors_then_reset(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 1)
    for status in (429, 503, None):
        httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
        httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [doc(urls[0], status)]})
        with httpx.Client() as c:
            run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
        assert q.counts() == ({"error": 1} if status is None else {"pending": 1})
    assert q.counts() == {"error": 1}
    assert q.pending() == []
    assert q.reset_errors() == 1
    assert q.counts() == {"pending": 1}


def test_local_midrun_exception_keeps_earlier(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 2)
    httpx_mock.add_response(url=urls[0], text=GOOD)
    httpx_mock.add_exception(RuntimeError("boom"), url=urls[1])
    with httpx.Client() as c, pytest.raises(RuntimeError):
        run_fetch(q, local(c), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 1, "pending": 1}


# ---------- task 5b: throughput and robustness ----------

def fcn(c, **kw):
    return FirecrawlFetcher("K", c, sleep=lambda s: None, **kw)


def test_concurrent_batches_yield_in_completion_order(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 250)
    for j in ("j1", "j2", "j3"):
        httpx_mock.add_response(method="POST", url=FC, json={"id": j})
    done = lambda us: {"status": "completed", "data": [doc(u, 200, GOOD) for u in us]}
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "scraping"})
    httpx_mock.add_response(url=f"{FC}/j2", json=done(urls[100:200]))
    httpx_mock.add_response(url=f"{FC}/j1", json=done(urls[:100]))
    httpx_mock.add_response(url=f"{FC}/j3", json=done(urls[200:]))
    order = []
    orig = q.mark
    q.mark = lambda url, *a, **k: (order.append(url), orig(url, *a, **k))[0]
    with httpx.Client() as c:
        run_fetch(q, fcn(c, concurrency=2), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 250}
    assert order[0] == urls[100] and urls[0] in order[100:]
    posts = [json.loads(r.content)["urls"] for r in httpx_mock.get_requests() if r.method == "POST"]
    assert [len(p) for p in posts] == [100, 100, 50]


def test_concurrent_batch_failure_drains_others(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 250)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j2"})
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "failed"})
    httpx_mock.add_response(url=f"{FC}/j2", json={"status": "completed",
                            "data": [doc(u, 200, GOOD) for u in urls[100:200]]})
    with httpx.Client() as c, pytest.raises(RuntimeError, match="j1"):
        run_fetch(q, fcn(c, concurrency=2), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 100, "pending": 150}
    assert q.pending(limit=1) == [urls[0]]
    assert len([r for r in httpx_mock.get_requests() if r.method == "POST"]) == 2  # no new jobs after failure


def test_local_backoff_and_timeout(httpx_mock):
    for _ in range(6):
        httpx_mock.add_exception(httpx.ReadTimeout("t"))
    sleeps = []
    with httpx.Client() as c:
        f = LocalFetcher(c, rate=1000.0, sleep=sleeps.append)
        assert f.get("https://hdith.com/a") is None
    assert [s for s in sleeps if s >= 1] == [2, 4, 8, 16, 32]
    assert all(r.extensions["timeout"]["read"] == 120 for r in httpx_mock.get_requests())


def test_enumerate_chapter_failure_continues(httpx_mock, tmp_path):
    item = lambda i: {"id": i, "kind": "hadith"}
    book = {"book": {"slug": "b-3", "title": "t"},
            "chapters": [{"id": 10, "t": "a", "count": 1}, {"id": 20, "t": "b", "count": 1},
                         {"id": 30, "t": "c", "count": 1}],
            "stats": {"hadiths": 3, "entries": 6}, "hadiths": [], "hadith_groups": []}
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-3", text=page_html(book))
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-3?chapter=10", text=page_html(dict(book, hadiths=[item(11)])))
    for _ in range(6):
        httpx_mock.add_exception(httpx.ReadTimeout("t"), url=f"{BASE}/encyclopedia/book/b-3?chapter=20")
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-3?chapter=30", text=page_html(dict(book, hadiths=[item(31)])))
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        res = enumerate_book(local(c), q, "b-3")
    assert res.failed_chapters == [20]
    assert set(q.pending(kind="hadith")) == {f"{BASE}/encyclopedia/book/b-3/h/{i}" for i in (11, 31)}
    assert not [r for r in httpx_mock.get_requests() if r.method == "HEAD"]


def test_books_rerun_failed(httpx_mock, tmp_path, monkeypatch, capsys):
    from isnad import cli
    db = tmp_path / "q.sqlite"
    q = Queue(db)
    q.mark_book("b-2", "failed")
    q.mark_book("b-9", "done", 1, 1)
    calls = []
    monkeypatch.setattr(fetch, "enumerate_book",
                        lambda f, queue, book: calls.append(book) or fetch.Enumerated(4, 4))
    cli.main(["--db", str(db), "fetch", "books", "--book", "b-2"])
    cli.main(["--db", str(db), "fetch", "books", "--book", "b-9"])
    assert calls == ["b-2"]
    assert Queue(db).book_done("b-2")


# ---------- final-review R4: credit safety ----------

def done_body(us):
    return {"status": "completed", "data": [doc(u, 200, GOOD) for u in us]}


def test_multi_round_drain_after_failure(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 250)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j2"})
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "failed"})
    httpx_mock.add_response(url=f"{FC}/j2", json={"status": "scraping"})  # survives a round
    httpx_mock.add_response(url=f"{FC}/j2", json=done_body(urls[100:200]))
    with httpx.Client() as c, pytest.raises(RuntimeError, match="j1"):
        run_fetch(q, fcn(c, concurrency=2), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 100, "pending": 150}
    assert len([r for r in httpx_mock.get_requests() if r.method == "POST"]) == 2
    st = {j["job_id"]: j["status"] for j in q.jobs()}
    assert st == {"j1": "failed", "j2": "persisted"}


def test_submit_failure_with_jobs_in_flight(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 250)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, status_code=402)
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "scraping"})
    httpx_mock.add_response(url=f"{FC}/j1", json=done_body(urls[:100]))
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        run_fetch(q, fcn(c, concurrency=2), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 100, "pending": 150}
    assert len([r for r in httpx_mock.get_requests() if r.method == "POST"]) == 2  # 402 not retried


def test_max_polls_with_concurrency(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 200)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j2"})
    httpx_mock.add_response(url=f"{FC}/j1", json={"status": "scraping"}, is_reusable=True)
    httpx_mock.add_response(url=f"{FC}/j2", json={"status": "scraping"})
    httpx_mock.add_response(url=f"{FC}/j2", json=done_body(urls[100:]))
    with httpx.Client() as c, pytest.raises(TimeoutError, match="j1"):
        run_fetch(q, fcn(c, concurrency=2, max_polls=3), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 100, "pending": 100}
    assert {j["job_id"]: j["status"] for j in q.jobs()}["j1"] == "timeout"


def test_job_ledger_and_stdout(httpx_mock, tmp_path, capsys):
    q, urls = mkq(tmp_path, 150)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j2"})
    httpx_mock.add_response(url=f"{FC}/j1", json=done_body(urls[:100]))
    httpx_mock.add_response(url=f"{FC}/j2", json=done_body(urls[100:]))
    with httpx.Client() as c:
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    jobs = Queue(tmp_path / "q.sqlite").jobs()
    assert [(j["job_id"], j["kind"], j["n"], j["first_url"], j["last_url"], j["status"]) for j in jobs] == [
        ("j1", "rawi", 100, urls[0], urls[99], "persisted"),
        ("j2", "rawi", 50, urls[100], urls[149], "persisted")]
    assert all(j["submitted_at"] for j in jobs)
    out = capsys.readouterr().out
    assert f"firecrawl job j1 submitted: n=100 first={urls[0]} last={urls[99]}" in out


def test_job_recorded_before_polling_survives_crash(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 2)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j1"})
    httpx_mock.add_exception(KeyboardInterrupt(), url=f"{FC}/j1")
    with httpx.Client() as c, pytest.raises(KeyboardInterrupt):
        run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert [(j["job_id"], j["status"]) for j in Queue(tmp_path / "q.sqlite").jobs()] == [("j1", "submitted")]


def test_recover_job_persists_results(httpx_mock, tmp_path, capsys):
    q, urls = mkq(tmp_path, 3)
    q.record_job("j9", "rawi", urls)
    q.mark(urls[2], "ok", path="x")
    httpx_mock.add_response(url=f"{FC}/j9", json={"status": "completed", "data": [
        doc(urls[0], 200, GOOD), doc(urls[1], 404), doc(urls[2], 200, GOOD),
        doc("https://hdith.com/elsewhere", 200, GOOD)]})
    with httpx.Client() as c:
        st = fetch.recover_job(q, fc(c), "j9", cache_root=tmp_path / "html")
    assert st.unmatched == 1
    assert q.counts() == {"ok": 2, "404": 1}
    assert (tmp_path / "html" / "rawi" / "1.html").read_text() == GOOD
    assert not (tmp_path / "html" / "rawi" / "3.html").exists()  # already ok: untouched
    assert q.job("j9")["status"] == "recovered"


def test_recover_unknown_job_needs_kind(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 1)
    with httpx.Client() as c:
        with pytest.raises(ValueError):
            fetch.recover_job(q, fc(c), "nope", cache_root=tmp_path / "html")
        httpx_mock.add_response(url=f"{FC}/nope", json={"status": "completed", "data": [doc(urls[0], 200, GOOD)]})
        fetch.recover_job(q, fc(c), "nope", kind="rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 1}
    assert q.job("nope")["status"] == "recovered"


def test_recover_refuses_incomplete_job(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 1)
    q.record_job("j", "rawi", urls)
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "scraping"})
    with httpx.Client() as c, pytest.raises(RuntimeError, match="scraping"):
        fetch.recover_job(q, fc(c), "j", cache_root=tmp_path / "html")
    assert q.counts() == {"pending": 1}


def test_cli_jobs_and_recover(httpx_mock, tmp_path, monkeypatch, capsys):
    from isnad import cli
    q, urls = mkq(tmp_path, 1)
    q.record_job("j5", "rawi", urls)
    cli.main(["--db", str(tmp_path / "q.sqlite"), "fetch", "jobs"])
    assert "j5 rawi 1 submitted" in capsys.readouterr().out
    monkeypatch.setattr(fetch, "read_api_key", lambda: "K")
    seen = {}
    monkeypatch.setattr(fetch, "recover_job",
                        lambda queue, f, job, kind=None: seen.update(job=job, kind=kind))
    cli.main(["--db", str(tmp_path / "q.sqlite"), "fetch", "recover", "--job", "j5"])
    assert seen == {"job": "j5", "kind": None}


def test_missing_urls_are_transient_and_unmatched_counted(httpx_mock, tmp_path, capsys):
    q, urls = mkq(tmp_path, 3)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [
        doc(urls[0], 200, GOOD), doc(urls[1] + "/", 200, GOOD)]})
    with httpx.Client() as c:
        st = run_fetch(q, fc(c), "rawi", cache_root=tmp_path / "html")
    assert (st.missing, st.unmatched) == (2, 1)
    assert q.counts() == {"ok": 1, "pending": 2}
    att = dict(q._db.execute("SELECT url, attempts FROM pages"))
    assert att[urls[1]] == 1 and att[urls[2]] == 1 and att[urls[0]] == 0
    assert "2 requested URLs missing" in capsys.readouterr().out


def test_local_timeout_counts_as_transient(httpx_mock, tmp_path):
    q, urls = mkq(tmp_path, 1)
    for _ in range(6):
        httpx_mock.add_exception(httpx.ReadTimeout("t"), url=urls[0])
    with httpx.Client() as c:
        run_fetch(q, local(c), "rawi", cache_root=tmp_path / "html")
    assert dict(q._db.execute("SELECT url, attempts FROM pages"))[urls[0]] == 1
    assert q.counts() == {"pending": 1}


def test_iter_fetch_yields_requested_urls(httpx_mock):
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [doc("a", 200, GOOD)]})
    with httpx.Client() as c:
        assert list(fc(c).iter_fetch(["a", "b"])) == [(["a", "b"], {"a": (200, GOOD)})]


def test_submit_retries_429_and_5xx_and_transport(httpx_mock):
    httpx_mock.add_response(method="POST", url=FC, status_code=429)
    httpx_mock.add_response(method="POST", url=FC, status_code=503)
    httpx_mock.add_exception(httpx.ConnectError("x"), method="POST", url=FC)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [doc("a", 200, GOOD)]})
    sleeps = []
    with httpx.Client() as c:
        f = FirecrawlFetcher("K", c, sleep=sleeps.append, poll_interval=5.0)
        assert f.fetch(["a"]) == {"a": (200, GOOD)}
    assert sleeps[:3] == [5.0, 10.0, 20.0]


def test_submit_timeout_logged(httpx_mock, capsys):
    httpx_mock.add_exception(httpx.ReadTimeout("t"), method="POST", url=FC)
    httpx_mock.add_response(method="POST", url=FC, json={"id": "j"})
    httpx_mock.add_response(url=f"{FC}/j", json={"status": "completed", "data": [doc("b", 200, GOOD)]})
    with httpx.Client() as c:
        fc(c).fetch(["a", "b"])
    out = capsys.readouterr().out
    assert "POST timed out; a job may exist: n=2 first=a last=b" in out


def test_submit_gives_up_after_retries(httpx_mock):
    for _ in range(4):
        httpx_mock.add_response(method="POST", url=FC, status_code=429)
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        fc(c).fetch(["a"])


def test_queue_wal_and_timeout(tmp_path):
    q = Queue(tmp_path / "q.sqlite")
    assert q._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert q._db.execute("PRAGMA busy_timeout").fetchone()[0] == 60000


def test_queue_tolerates_wal_pragma_failure(tmp_path):
    import sqlite3
    db = tmp_path / "q.sqlite"
    import threading
    # an old-mode (rollback journal) database held by a concurrent connection
    holder = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    holder.execute(fetch._SCHEMA)
    holder.execute("BEGIN")
    holder.execute("SELECT * FROM pages").fetchall()  # shared lock blocks the mode switch
    t = threading.Timer(0.3, lambda: holder.execute("COMMIT"))  # released shortly after
    t.start()
    q = Queue(db)  # pragma fails fast and is ignored; schema writes wait on busy_timeout
    t.join()
    assert q._db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    q.add("u", "rawi", id=1)
    assert q.counts() == {"pending": 1}


def test_cli_refuses_firecrawl_hadith_without_book_or_limit(tmp_path, monkeypatch, capsys):
    from isnad import cli
    db = tmp_path / "q.sqlite"
    q = Queue(db)
    q.add("h1", "hadith", id=1, book="b-1")
    q.add("h2", "hadith", id=2, book="b-2")
    monkeypatch.setattr(fetch, "read_api_key", lambda: pytest.fail("must not reach the fetcher"))
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(db), "fetch", "run", "--kind", "hadith", "--fetcher", "firecrawl"])
    assert e.value.code == 2
    assert "2 hadith pages pending" in capsys.readouterr().out


def test_cli_allows_firecrawl_hadith_with_book(tmp_path, monkeypatch):
    from isnad import cli
    db = tmp_path / "q.sqlite"
    monkeypatch.setattr(fetch, "read_api_key", lambda: "K")
    seen = {}
    monkeypatch.setattr(fetch, "run_fetch", lambda queue, f, kind, **kw: seen.update(kind=kind, **kw))
    cli.main(["--db", str(db), "fetch", "run", "--kind", "hadith", "--fetcher", "firecrawl", "--book", "b-1"])
    assert seen["book"] == "b-1"
    cli.main(["--db", str(db), "fetch", "run", "--kind", "hadith", "--fetcher", "firecrawl", "--limit", "5"])
    assert seen["limit"] == 5
