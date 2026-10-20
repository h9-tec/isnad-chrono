import json

import pandas as pd
import pytest

from isnad.export_site import (check_keys, narrators_table, run_export_site, search_key,
                               write_json)


@pytest.fixture
def tmp_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    pd.DataFrame({
        "rawi_id": [1, 2, 3], "name": ["a", "b", "c"], "abbrev": ["A", None, "C"],
        "kunya": ["abu", None, None], "generation_num": [3.0, float("nan"), 5.0],
        "death_year": [100.0, float("nan"), 120.0], "death_kind": ["exact", "none", "exact"],
        "birth_year": [float("nan")] * 3, "birth_kind": ["none"] * 3,
        "lineage": ["x"] * 3}).to_parquet(d / "rawi.parquet")
    pd.DataFrame({
        "rawi_id": [1], "birth_lo": [10.0], "birth_hi": [20.0], "death_lo": [98.0],
        "death_hi": [102.0], "death_mode": [100.0], "support": [4],
        "method": ["known"]}).to_parquet(d / "rawi_dates_inferred.parquet")
    pd.DataFrame({
        "hadith_id": [11, 11, 12], "chain_no": [0, 0, 0], "position": [0, 1, 0],
        "rawi_id": [1, 99, 1], "term": ["عن"] * 3, "unjoined": [False] * 3,
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
    assert set(by) == {1, 99}  # narrators 2, 3 have no chains
    assert by[1]["n_chains"] == 2 and by[1]["name"] == "A" and by[1]["gen"] == 3
    assert (by[1]["dlo"], by[1]["dhi"], by[1]["method"]) == (98, 102, "known")
    assert set(rows[0]) == {"id", "name", "kunya", "gen", "dy", "dk", "by", "bk", "dlo", "dhi",
                            "blo", "bhi", "method", "support", "n_chains"}


def test_search_key_normalises_digits():
    assert search_key("مسلم", " ٢٨٦٤ ") == "b-2:2864"
    assert search_key("b-4", "100") == "b-4:100"
    assert search_key("Abu  Dawud", "5") == "b-3:5"


def test_run_export_site_writes_core(tmp_data, tmp_path):
    m = run_export_site(str(tmp_data), str(tmp_path / "out"))
    assert {"meta.json", "narrators.json", "search.json"} <= set(m)
    s = json.loads((tmp_path / "out/search.json").read_text())
    assert s["hadith"]["11"] == "tk-5" and s["numbering"]["b-2:6"] == "tk-5"
    meta = json.loads((tmp_path / "out/meta.json").read_text())
    assert meta["checks"] == {} and meta["books"][0] == {
        "slug": "b-1", "title": "b-1", "n_hadith_cached": 1}
