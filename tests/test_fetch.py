import json
import time

import httpx
import pytest

from isnad import fetch
from isnad.fetch import (
    FirecrawlFetcher,
    LocalFetcher,
    Queue,
    enumerate_book,
    load_rawi_sitemap,
    run_fetch,
)

BASE = "https://hdith.com"


def page_html(props: dict) -> str:
    data = {"component": "X", "props": props}
    return f'<html><script data-page="app" type="application/json">{json.dumps(data)}</script></html>'


def local(client, rate=1000.0):
    return LocalFetcher(client, rate=rate, sleep=lambda s: None)


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

def book_mocks(httpx_mock, listed_hadith_ids):
    """Chapters 100 (count 2) and 200 (count 1); stats count hadith+passage = 4, 6 entries."""
    book = {
        "book": {"slug": "b-2", "title": "t"},
        "chapters": [{"id": 100, "t": "k1", "count": 2}, {"id": 200, "t": "k2", "count": 1}],
        "stats": {"hadiths": 4, "entries": 6},
        "hadiths": [],
        "hadith_groups": [],
    }
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2", text=page_html(book))
    ch1 = dict(book, hadiths=[{"id": 101, "n": 1, "kind": "hadith"}] if 101 in listed_hadith_ids else [],
               hadith_groups=[{"id": 150, "depth": 1, "title": "bab",
                               "hadiths": [{"id": 102, "kind": "hadith"}] if 102 in listed_hadith_ids else []}])
    ch2 = dict(book, hadiths=[{"id": 201, "n": 1, "kind": "hadith"}, {"id": 202, "kind": "passage"}],
               hadith_groups=[])
    bab = dict(book, hadiths=[{"id": 102, "kind": "hadith"}] if 102 in listed_hadith_ids else [],
               hadith_groups=[])
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=100", text=page_html(ch1))
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=200", text=page_html(ch2))
    httpx_mock.add_response(url=f"{BASE}/encyclopedia/book/b-2?chapter=150", text=page_html(bab))


def test_enumerate_book(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101, 102})
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        n = enumerate_book(local(c), q, "b-2")
    assert n == 4
    assert not [r for r in httpx_mock.get_requests() if r.method == "HEAD"]
    pre = f"{BASE}/encyclopedia/book/b-2/h/"
    assert set(q.pending(kind="hadith", include_passages=True)) == {pre + str(i) for i in (101, 102, 201, 202)}
    assert set(q.pending(kind="hadith")) == {pre + str(i) for i in (101, 102, 201)}
    assert q.info(pre + "101") == ("hadith", 101)


def test_enumerate_probe_fallback(httpx_mock, tmp_path):
    book_mocks(httpx_mock, {101})  # 102 missing from listings
    known = {100, 101, 150, 200, 201, 202}
    for i in range(101, 200):
        if i in known:
            continue
        url = f"{BASE}/encyclopedia/book/b-2/h/{i}"
        if i == 102:
            httpx_mock.add_response(method="HEAD", url=url, status_code=200)
        else:
            httpx_mock.add_response(method="HEAD", url=url, status_code=404)
    q = Queue(tmp_path / "q.sqlite")
    with httpx.Client() as c:
        n = enumerate_book(local(c), q, "b-2")
    assert n == 4
    pre = f"{BASE}/encyclopedia/book/b-2/h/"
    assert pre + "102" in q.pending(kind="hadith")  # entry_kind NULL is fetched
    heads = [r for r in httpx_mock.get_requests() if r.method == "HEAD"]
    assert {r.url.path.rsplit("/", 1)[1] for r in heads} == {str(i) for i in range(102, 200) if i != 150}


# ---------- firecrawl ----------

def doc(url, status, html="<html/>"):
    return {"rawHtml": html, "metadata": {"sourceURL": url, "url": url, "statusCode": status}}


def test_firecrawl_paging_and_auth(httpx_mock):
    httpx_mock.add_response(method="POST", url="https://api.firecrawl.dev/v2/batch/scrape",
                            json={"success": True, "id": "j1", "url": "x"})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1",
                            json={"status": "scraping", "total": 2, "completed": 0, "data": []})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1",
                            json={"status": "completed", "total": 2, "completed": 2,
                                  "data": [doc("a", 200, "A")], "next": "https://api.firecrawl.dev/v2/batch/scrape/j1?skip=1"})
    httpx_mock.add_response(url="https://api.firecrawl.dev/v2/batch/scrape/j1?skip=1",
                            json={"status": "completed", "data": [doc("b", 200, "B")]})
    with httpx.Client() as c:
        out = FirecrawlFetcher("KEY", c, sleep=lambda s: None).fetch(["a", "b"])
    assert out == {"a": (200, "A"), "b": (200, "B")}
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
                                  "data": [doc(urls[0], 200, "<p>one</p>"), doc(urls[1], 404)]})
    with httpx.Client() as c:
        run_fetch(q, FirecrawlFetcher("K", c, sleep=lambda s: None), "rawi", cache_root=tmp_path / "html")
    assert q.counts() == {"ok": 1, "404": 1, "pending": 1}
    assert (tmp_path / "html" / "rawi" / "1.html").read_text() == "<p>one</p>"
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
