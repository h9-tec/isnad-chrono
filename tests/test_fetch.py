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
    for _ in range(4):
        httpx_mock.add_response(method="HEAD", url=PRE + "105", status_code=503)
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c, pytest.raises(ProbeError):
        enumerate_book(local(c), q, "b-2")
    assert PRE + "101" in q.pending(kind="hadith")  # per-chapter progress persisted
    assert not q.book_done("b-2")


def test_enumerate_probe_timeout_raises(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 106})
    for _ in range(4):
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
    for _ in range(4):
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
