import gzip
import json

import pandas as pd
import pytest

from isnad.export_site import (check_keys, meta_table, narrators_table, run_export_site,
                               search_key, write_json)


@pytest.fixture
def tmp_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    pd.DataFrame({
        "rawi_id": [5, 6, 7], "name": ["a", "b", "c"], "abbrev": ["A", None, "C"],
        "kunya": ["abu", None, None], "generation_num": [3.0, float("nan"), 5.0],
        "death_year": [100.0, float("nan"), 120.0], "death_kind": ["exact", "none", "exact"],
        "birth_year": [float("nan")] * 3, "birth_kind": ["none"] * 3,
        "lineage": ["x"] * 3}).to_parquet(d / "rawi.parquet")
    pd.DataFrame({
        "rawi_id": [5], "birth_lo": [10.0], "birth_hi": [20.0], "death_lo": [98.0],
        "death_hi": [102.0], "death_mode": [100.0], "support": [4],
        "method": ["known"]}).to_parquet(d / "rawi_dates_inferred.parquet")
    pd.DataFrame({
        "hadith_id": [11, 11, 12], "chain_no": [0, 0, 0], "position": [0, 1, 0],
        "rawi_id": [5, 99, 5], "term": ["عن"] * 3, "unjoined": [False] * 3,
        "source": ["html"] * 3}).to_parquet(d / "chains.parquet")
    pd.DataFrame({
        "group_id": ["tk-5", "tk-6"], "hadith_id": [11, 12], "book_slug": ["b-2", "b-1"],
        "numbering": ["6", "7"]}).to_parquet(d / "occurrences.parquet")
    pd.DataFrame({
        "hadith_id": [11], "book_slug": ["b-2"],
        "book_title": ["صحيح مسلم"]}).to_parquet(d / "hadith.parquet")
    return d


def test_check_keys_rejects_denylisted():
    with pytest.raises(ValueError, match="matn"):
        check_keys({"a": [{"matn": "x"}]})
    with pytest.raises(ValueError, match="foo_text"):
        check_keys([{"foo_text": 1}])
    check_keys({"name": "x", "kunya": None})


def test_write_json_checks_and_compacts(tmp_path):
    with pytest.raises(ValueError):
        write_json(tmp_path / "x.json", {"lineage": 1})
    assert not (tmp_path / "x.json").exists()
    n = write_json(tmp_path / "y.json", {"a": "ب"})
    assert (tmp_path / "y.json").read_text(encoding="utf-8") == '{"a":"ب"}'
    assert n == len('{"a":"ب"}'.encode())


def test_narrators_missing_name_falls_back(tmp_data):
    rows = narrators_table(tmp_data)
    by = {r["id"]: r for r in rows}
    assert by[99]["name"] == "p-99" and by[99]["kunya"] is None and by[99]["dlo"] is None
    assert set(by) == {5, 99}  # narrators 6, 7 have no chains
    assert by[5]["n_chains"] == 2 and by[5]["name"] == "A" and by[5]["gen"] == 3
    assert (by[5]["dlo"], by[5]["dhi"], by[5]["method"]) == (98, 102, "known")
    assert set(rows[0]) == {"id", "name", "kunya", "gen", "dy", "dk", "by", "bk", "dlo", "dhi",
                            "blo", "bhi", "method", "support", "n_chains", "placeholder"}


def test_search_key_normalises_digits():
    assert search_key("مسلم", " ٢٨٦٤ ") == "b-2:2864"
    assert search_key("b-4", "100") == "b-4:100"
    assert search_key("Abu  Dawud", "5") == "b-3:5"


def test_search_key_fallback_lowercase():
    assert search_key("B-3", "1") == "b-3:1"


def test_check_keys_inside_checks():
    with pytest.raises(ValueError, match="matn"):
        check_keys({"meta": {"checks": {"x": [{"matn": 1}]}}})
    with pytest.raises(ValueError):
        check_keys({"Text": 1})


def test_n_chains_dedup_and_null_dates(tmp_data):
    ch = pd.read_parquet(tmp_data / "chains.parquet")
    pd.concat([ch, ch]).to_parquet(tmp_data / "chains.parquet")
    by = {r["id"]: r for r in narrators_table(tmp_data)}
    assert by[5]["n_chains"] == 2
    assert by[99]["support"] is None and by[99]["method"] is None


def test_placeholder(tmp_data):
    ch = pd.read_parquet(tmp_data / "chains.parquet")
    ch.loc[0, "rawi_id"] = 2
    ch.to_parquet(tmp_data / "chains.parquet")
    by = {r["id"]: r for r in narrators_table(tmp_data)}
    assert by[2]["placeholder"] is True and by[2]["name"] == "راوٍ غير مسمّى"
    assert by[5]["placeholder"] is False and by[99]["name"] == "p-99"


def test_run_export_site_writes_core(tmp_data, tmp_path):
    occ = pd.read_parquet(tmp_data / "occurrences.parquet")
    extra = pd.DataFrame({"group_id": ["tk-107", "tk-6", "tg-9"], "hadith_id": [11, 13, 14],
                          "book_slug": ["b-2", "b-1", "b-1"], "numbering": ["6", None, "٨"]})
    pd.concat([occ, extra]).to_parquet(tmp_data / "occurrences.parquet")
    m = run_export_site(str(tmp_data), str(tmp_path / "out"))
    assert {"meta.json", "narrators.json", "search.json", "search/n/b-2.json",
            "search/h/11.json"} <= set(m)
    o = tmp_path / "out"
    n = json.loads((o / "search/n/b-2.json").read_text())
    assert n["numbering"]["6"] == [5, 107]  # duplicated key keeps both, sorted ints
    assert json.loads((o / "search/n/b-1.json").read_text())["numbering"] == {"7": [6], "8": ["tg-9"]}
    assert json.loads((o / "search/h/11.json").read_text())["11"] == [5, 107]
    s = json.loads((o / "search.json").read_text())
    assert s["books"]["b-2"] == "صحيح مسلم" and s["aliases"]["muslim"] == "b-2"
    nar = json.loads((o / "narrators.json").read_text())
    assert nar["cols"][0] == "id" and nar["cols"][-1] == "placeholder" and len(nar["rows"]) == 2
    meta = json.loads((o / "meta.json").read_text())
    assert meta["checks"] == {} and meta["n_hadith_pages_cached"] == 0
    assert meta["books"][0]["slug"] == "b-1"


def test_title_from_cached_page_and_page_count(tmp_data):
    from unittest import mock
    base = tmp_data / "raw/html/hadith"
    base.mkdir(parents=True)
    with gzip.open(base / "12.html.gz", "wt", encoding="utf-8") as f:
        f.write("<html/>")
    (base / "99.html").write_text("x")
    rec = mock.Mock(book_title="صحيح البخاري")
    with mock.patch("isnad.export_site.parse_hadith", return_value=rec):
        meta = meta_table(tmp_data)
    assert meta["n_hadith_pages_cached"] == 2
    assert {b["slug"]: b["title"] for b in meta["books"]} == {
        "b-1": "صحيح البخاري", "b-2": "صحيح مسلم"}
    (base / "12.html.gz").unlink()  # unreadable -> slug
    assert {b["slug"]: b["title"] for b in meta_table(tmp_data)["books"]}["b-1"] == "b-1"
