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
    assert "github.io" not in js and '"./data/"' in js and '"../site_data/"' in js
    assert 'DEV_HOSTS = ["localhost", "127.0.0.1"]' in js
    assert 'DEV_HOSTS.includes(location.hostname) ? "../site_data/" : "./data/"' in js
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


PAGES = ("index.html", "narrator.html", "atlas.html", "boards.html", "method.html")
NAV = (("index.html", "المستكشف"), ("narrator.html", "الرواة"), ("atlas.html", "الأطلس"),
       ("boards.html", "اللوائح"), ("method.html", "المنهج"))
METHOD_CHECKS = ("cl_k2_rate_multi", "cl_k3_rate_multi", "cl_k2_prior_only_rate",
                 "dating_method_median_abs_error", "dating_depth_median_abs_error",
                 "dating_method_mean_abs_error", "dating_depth_mean_abs_error",
                 "dating_method_bounded_mean_abs_error", "dating_method_coverage_90",
                 "alignment_surface_found_rate", "alignment_control_surface_found_rate",
                 "coverage_n_groups", "coverage_n_groups_multi_chain", "groups_complete_rate",
                 "occurrence_chain_rate", "n_hadith_pages_cached")


def _nav(html: str) -> str:
    m = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', html, re.S)
    assert m, "no site-nav"
    return m.group(1)


def test_every_page_has_nav_and_data_js():
    for name in PAGES:
        html = (SITE / name).read_text()
        nav = _nav(html)
        for href, label in NAV:
            assert re.search(rf'<a href="{re.escape(href)}"[^>]*>{label}</a>', nav), (name, href)
        assert len(re.findall(r"<a ", nav)) == 5, name
        assert 'aria-current="page"' in nav, name
        assert '<script src="data.js"></script>' in html, name
        assert 'dir="rtl"' in html and 'name="viewport"' in html, name
        for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
            assert (SITE / src).is_file(), (name, src)
        for href in re.findall(r'<link[^>]+href="([^"]+)"', html):
            assert (SITE / href).is_file(), (name, href)


def test_method_page_checks_use_real_keys():
    html = (SITE / "method.html").read_text()
    keys = set(re.findall(r'data-check="([^"]+)"', html))
    for k in METHOD_CHECKS:
        assert k in keys, k
    assert "https://huggingface.co/datasets/HeshamHaroon/isnad-chrono" in html
    assert "https://github.com/h9-tec/isnad-chrono" in html and "https://hdith.com/" in html
    assert len(re.findall(r"<li", html.split('id="steps-ar"')[1].split("</ol>")[0])) == 5
    assert len(re.findall(r"<li", html.split('id="steps-en"')[1].split("</ol>")[0])) == 5
    atlas = set(re.findall(r'data-check="([^"]+)"', (SITE / "atlas.html").read_text()))
    assert {"cl_k2_rate_multi", "cl_k3_rate_multi", "dating_method_median_abs_error",
            "dating_depth_median_abs_error", "alignment_surface_found_rate",
            "alignment_control_surface_found_rate", "coverage_n_groups_multi_chain"} <= atlas
    checks = ROOT / "release_hf/checks.json"
    if checks.is_file():  # the release build is not tracked; assert keys when present
        import json
        real = set(json.loads(checks.read_text()))
        assert keys | atlas <= real, sorted((keys | atlas) - real)


def test_pages_wire_their_scripts():
    pages = {"narrator.html": "narrator.js", "atlas.html": "atlas.js",
             "boards.html": "boards.js", "method.html": "common.js"}
    for page, js in pages.items():
        assert f'<script src="{js}"></script>' in (SITE / page).read_text(), page
    common = (SITE / "common.js").read_text()
    for name in ("esc", "fillChecks", "narratorLink", "sortableTable"):
        assert re.search(rf"\b{name}\b", common), name
    nar = (SITE / "narrator.js").read_text()
    assert "e.status === 404" in nar and "rawiUrl" in nar and "placeholder" in nar
    boards = (SITE / "boards.js").read_text()
    for b in ("top_cls", "earliest", "conflicts", "top_editors"):
        assert b in boards, b
    atlas = (SITE / "atlas.js").read_text()
    assert "rate_nonleaf" in atlas and "cl_hist" in atlas


def test_explorer_selects_within_component():
    js = (SITE / "explorer.js").read_text()
    assert "function selectNode(d, comp)" in js
    assert "for (const c of state.layout.components)" not in js


def test_fix_round_1_strings():
    common = (SITE / "common.js").read_text()
    assert "`<span class=\"ph\" dir=\"ltr\">p-${esc(id)}</span>`" in common  # unknown-id fallback
    assert "createCaption().textContent" in common and "أسانيد" in common
    assert "narratorLink" in (SITE / "boards.js").read_text()
    nar = (SITE / "narrator.js").read_text()
    assert "e.status === 404" in nar and "No links." in nar
    assert "const CLAMP = [-60, 400]" in nar and 'class", "cut"' in nar
    assert "عقدة مدمجة لراوٍ غير مسمّى؛ التواريخ والروابط لا تدل على شخص واحد" in nar
    atlas = (SITE / "atlas.js").read_text()
    assert "cl_hist_excluded" in atlas and "MIN_N = 30" in atlas and "hollow" in atlas
    for page in ("atlas.html", "method.html"):
        html = (SITE / page).read_text()
        for td in re.findall(r'<td class="num">(.*?)</td>', html):
            if " / " in td:
                assert td.startswith('<bdi dir="ltr">'), (page, td)


def test_footers_and_workflows():
    pages = list(SITE.glob("*.html"))
    assert pages
    for p in pages:
        m = re.search(r'<footer class="site-footer">(.*?)</footer>', p.read_text(), re.S)
        assert m, p.name
        for needle in ("hdith.com", "huggingface.co/datasets/HeshamHaroon/isnad-chrono",
                       "github.com/h9-tec/isnad-chrono", "CC-BY-4.0",
                       "no hadith text is redistributed"):
            assert needle in m.group(1), (p.name, needle)
    wf = ROOT / ".github/workflows"
    pages_yml = (wf / "pages.yml").read_text()
    assert "ref: site-data" in pages_yml and "deploy-pages" in pages_yml
    assert "pytest" in (wf / "validate.yml").read_text()


def test_final_fix_round():
    index = (SITE / "index.html").read_text()
    scripts = re.findall(r'<script src="([^"]+)"', index)
    assert scripts.index("common.js") < scripts.index("explorer.js")
    assert "explorer.js" not in (SITE / "narrator.html").read_text()
    common = (SITE / "common.js").read_text()
    for name in ("esc", "narratorName", "narratorLink", "arNorm", "asciiDigits"):
        assert re.search(rf"function {name}\b", common), name
    js = (SITE / "explorer.js").read_text()
    for name in ("esc", "narratorName", "narratorLink", "arNorm", "asciiDigits"):
        assert not re.search(rf"function {name}\b", js), name
    assert "IsnadExplorer." not in (SITE / "narrator.js").read_text()
    assert "${esc(ISNAD.hadithUrl(slug, h))}" in js
    assert "else resetPage();" in js and "function resetPage()" in js
    assert "maxLayer" not in (SITE / "tree.js").read_text()
    for z in re.findall(r"<button[^>]*data-zoom[^>]*>", index):
        assert "aria-label=" in z, z
    for page in PAGES:
        html = (SITE / page).read_text()
        for tag in re.findall(r"<[^>]*aria-live[^>]*>", html):
            assert 'id="status"' in tag and 'role="status"' in tag, (page, tag)
    for page in ("index.html", "narrator.html"):
        assert 'id="status"' in (SITE / page).read_text(), page


def test_footer_names_clause_and_pages_hardening():
    for p in SITE.glob("*.html"):
        foot = re.search(r'<footer class="site-footer">(.*?)</footer>', p.read_text(), re.S).group(1)
        assert "الأسماء والكنى وصيغ التحمّل من hdith.com (خارج رخصة CC-BY)" in foot, p.name
        assert "Names, kunyas and transmission terms: hdith.com (not covered by CC-BY)" in foot, p.name
    wf = (ROOT / ".github/workflows/pages.yml").read_text()
    assert "continue-on-error" not in wf
    assert wf.count("persist-credentials: false") == 2
    assert "test -f _site/data/meta.json" in wf
    readme = (ROOT / "README.md").read_text()
    assert ("derived numbers plus narrator names, kunyas and transmission terms from hdith.com; "
            "no hadith text") in readme
