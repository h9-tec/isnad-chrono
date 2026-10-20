"""Static checks on the hand-written site (no browser, no node)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_site_files_exist_and_reference_vendor():
    html = (SITE / "index.html").read_text()
    assert "vendor/d3.v7.min.js" in html and "explorer.js" in html and 'dir="rtl"' in html
    assert (SITE / "vendor/d3.v7.min.js").stat().st_size > 200_000


def _is_external(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith(("http://", "https://", "//")) or ":" in u.split("/")[0]


def test_no_external_scripts():
    pages = list(SITE.glob("*.html"))
    assert pages
    for p in pages:
        html = p.read_text()
        for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)", html):
            assert not _is_external(src), (p.name, src)
        for tag in re.findall(r"<link\b[^>]*>", html):
            if re.search(r"rel=[\"']?stylesheet", tag):
                href = re.search(r"href=[\"']([^\"']+)", tag).group(1)
                assert not _is_external(href), (p.name, href)


def test_external_detector():
    for bad in ("https://x/y.js", "http://x/y.js", "//cdn.x/y.js", "HTTPS://X"):
        assert _is_external(bad)
    for ok in ("vendor/d3.v7.min.js", "styles.css", "./data.js"):
        assert not _is_external(ok)


def test_vendored_d3_is_pinned_and_licensed():
    head = (SITE / "vendor/d3.v7.min.js").read_text()[:80]
    assert head.startswith("// https://d3js.org v7.9.0")
    assert "Permission to use, copy, modify" in (SITE / "vendor/LICENSE-d3.txt").read_text()


def test_scripts_referenced_by_index_exist():
    html = (SITE / "index.html").read_text()
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        assert (SITE / src).is_file(), src
    for href in re.findall(r'<link[^>]+href="([^"]+)"', html):
        assert (SITE / href).is_file(), href


def test_examples_and_data_base():
    html = (SITE / "index.html").read_text()
    for ex in ("bukhari 10", "مسلم 2864", "tk-12688", "سفيان بن عيينة"):
        assert ex in html
    js = (SITE / "data.js").read_text()
    assert 'endsWith("github.io")' in js and '"./data/"' in js and '"../site_data/"' in js
    for name in ("load", "narrators", "meta", "search", "group", "narratorDetail",
                 "groupPath", "narratorPath", "rawiUrl", "hadithUrl"):
        assert re.search(rf"\b{name}\b", js), name


def test_tree_and_explorer_interfaces():
    tree = (SITE / "tree.js").read_text()
    assert "function layoutGroup" in tree and "function drawGroup" in tree
    assert "function normalizeQuery" in (SITE / "explorer.js").read_text()


def test_explorer_hardening():
    js = (SITE / "explorer.js").read_text()
    assert "/^t[kg]-\\d+$/" in js and "معرّف غير صالح" in js
    assert "Object.hasOwn(aliases" in js and "loadToken" in js
    tree = (SITE / "tree.js").read_text()
    assert "longestPathLayers" in tree and '"tabindex", 0' in tree
    assert 'role="img"' not in (SITE / "index.html").read_text()
