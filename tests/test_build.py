import gzip
import shutil
from pathlib import Path

import pandas as pd

from isnad import build

FIX = Path(__file__).parent / "fixtures"


def _setup(tmp_path):
    root = tmp_path / "raw" / "html"
    (root / "hadith").mkdir(parents=True)
    (root / "rawi").mkdir()
    shutil.copy(FIX / "rawi_4494.html", root / "rawi" / "4494.html")
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "11563.html")
    shutil.copy(FIX / "hadith_muslim_11558_nochain.html", root / "hadith" / "11558.html")
    (root / "rawi" / "bad.html").write_text("<html>")
    (root / "hadith" / "bad.html").write_text("<html>")
    return root


def test_build_tables(tmp_path):
    root = _setup(tmp_path)
    out = tmp_path / "data"
    assert build.build_rawi(root, out / "rawi.parquet") == 1
    assert build.build_hadith(root, out / "hadith.parquet", out / "edges.parquet", reset=False) == (2, 6)
    rawi = pd.read_parquet(out / "rawi.parquet")
    assert len(rawi) == 1 and len(rawi.iloc[0]["teachers_ids"]) == 13
    assert 3026 in set(rawi.iloc[0]["teachers_ids"]) and rawi.iloc[0]["death_kind"] == "era"
    assert len(pd.read_parquet(out / "opinions.parquet")) == 19
    assert len(pd.read_parquet(out / "tuhfa.parquet")) == 1
    h = pd.read_parquet(out / "hadith.parquet")
    assert {"n_links", "grading_json"} <= set(h.columns)
    errs = pd.read_csv(out / "build_errors.csv")
    assert len(errs) == 2 and all(errs["path"].str.endswith("bad.html"))


def test_errors_reset_on_rebuild(tmp_path):
    root = _setup(tmp_path)
    out = tmp_path / "data"
    for _ in range(2):
        build.build_rawi(root, out / "rawi.parquet")
        build.build_hadith(root, out / "hadith.parquet", out / "edges.parquet", reset=False)
    # second round's rawi call reset the file, hadith re-appended: one per page
    assert len(pd.read_csv(out / "build_errors.csv")) == 2


def test_empty_cache_keeps_schema(tmp_path):
    root = tmp_path / "raw" / "html"
    (root / "rawi").mkdir(parents=True)
    out = tmp_path / "data"
    assert build.build_rawi(root, out / "rawi.parquet") == 0
    df = pd.read_parquet(out / "rawi.parquet")
    assert len(df) == 0 and {"rawi_id", "teachers_ids", "death_year", "birth_kind"} <= set(df.columns)


def test_attribute_error_page_is_logged_not_fatal(tmp_path):
    root = _setup(tmp_path)
    # valid page data whose `rulings` is a list: parse_rawi raises AttributeError
    (root / "rawi" / "attr.html").write_text(
        '<script data-page="app" type="application/json">'
        '{"component": "x", "props": {"person": {"slug": "p-9", "name": "n"}, "rulings": [1]}}'
        '</script>')
    out = tmp_path / "data"
    assert build.build_rawi(root, out / "rawi.parquet") == 1
    errs = pd.read_csv(out / "build_errors.csv")
    assert any(errs["error"].str.startswith("AttributeError"))


def test_count_parsed_and_built(tmp_path):
    root = _setup(tmp_path)
    out = tmp_path / "data"
    build.build_rawi(root, out / "rawi.parquet")
    rawi = pd.read_parquet(out / "rawi.parquet")
    assert "count" in rawi.columns and int(rawi.iloc[0]["count"]) == 197


def test_build_reads_gz_and_plain(tmp_path):
    root = tmp_path / "raw" / "html"
    (root / "hadith").mkdir(parents=True)
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "11563.html")
    page = (FIX / "hadith_muslim_11558_nochain.html").read_text(encoding="utf-8")
    with gzip.open(root / "hadith" / "11558.html.gz", "wt", encoding="utf-8") as f:
        f.write(page)
    # present in both forms: counted once
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "11563.html")
    with gzip.open(root / "hadith" / "11563.html.gz", "wt", encoding="utf-8") as f:
        f.write((FIX / "hadith_muslim_11563.html").read_text(encoding="utf-8"))
    out = tmp_path / "data"
    assert build.build_hadith(root, out / "h.parquet", out / "e.parquet") == (2, 6)


def _hroot(tmp_path):
    root = tmp_path / "raw" / "html"
    (root / "hadith").mkdir(parents=True)
    return root


def test_corrupt_and_truncated_gz_are_logged_not_fatal(tmp_path):
    root = _hroot(tmp_path)
    good = gzip.compress((FIX / "hadith_muslim_11563.html").read_bytes())
    (root / "hadith" / "1.html.gz").write_bytes(b"\x00random not gzip bytes" * 5)
    (root / "hadith" / "2.html.gz").write_bytes(good[:50])
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "3.html")
    out = tmp_path / "data"
    assert build.build_hadith(root, out / "h.parquet", out / "e.parquet") == (1, 6)
    errs = pd.read_csv(out / "build_errors.csv")
    assert sorted(Path(p).name for p in errs["path"]) == ["1.html.gz", "2.html.gz"]


def test_corrupt_gz_falls_back_to_plain_sibling(tmp_path):
    root = _hroot(tmp_path)
    (root / "hadith" / "7.html.gz").write_bytes(b"garbage garbage garbage")
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "7.html")
    out = tmp_path / "data"
    assert build.build_hadith(root, out / "h.parquet", out / "e.parquet") == (1, 6)
    assert not (out / "build_errors.csv").exists()
