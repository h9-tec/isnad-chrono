import gzip
import json

from pathlib import Path

import jsonschema
import pandas as pd
import pytest

from isnad import tree
from isnad.edits import EDIT_COLS
from isnad.export_site import (SiteContext, atlas_table, check_keys, group_json, group_path,
                               meta_table, narrator_detail, narrator_path, narrators_table,
                               run_export_site, search_key, write_json)


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
    assert n["numbering"]["6"] == ["tk-107", "tk-5"]  # duplicated key keeps both, sorted strings
    assert json.loads((o / "search/n/b-1.json").read_text())["numbering"] == {"7": ["tk-6"], "8": ["tg-9"]}
    assert json.loads((o / "search/h/11.json").read_text())["11"] == ["tk-107", "tk-5"]
    s = json.loads((o / "search.json").read_text())
    assert s["books"]["b-2"] == "صحيح مسلم" and s["aliases"]["muslim"] == "b-2"
    nar = json.loads((o / "narrators.json").read_text())
    assert nar["cols"][0] == "id" and nar["cols"][-1] == "placeholder" and len(nar["rows"]) == 2
    meta = json.loads((o / "meta.json").read_text())
    assert meta["checks"] == {} and meta["n_hadith_pages_cached"] == 0
    assert meta["books"][0]["slug"] == "b-1"


def test_title_from_cached_page_and_page_count(tmp_data):
    from unittest import mock
    occ = pd.read_parquet(tmp_data / "occurrences.parquet")
    pd.concat([occ, pd.DataFrame({"group_id": ["tk-8"], "hadith_id": [13], "book_slug": ["b-1"],
                                  "numbering": ["9"]})]).to_parquet(tmp_data / "occurrences.parquet")
    base = tmp_data / "raw/html/hadith"
    base.mkdir(parents=True)
    with gzip.open(base / "13.html.gz", "wt", encoding="utf-8") as f:  # 12 is not cached
        f.write("<html/>")
    (base / "99.html").write_text("x")
    rec = mock.Mock(book_title="صحيح البخاري")
    with mock.patch("isnad.export_site.parse_hadith", return_value=rec):
        meta = meta_table(tmp_data)
    assert meta["n_hadith_pages_cached"] == 2
    assert {b["slug"]: b["title"] for b in meta["books"]} == {
        "b-1": "صحيح البخاري", "b-2": "صحيح مسلم"}
    (base / "13.html.gz").unlink()  # unreadable -> slug
    assert {b["slug"]: b["title"] for b in meta_table(tmp_data)["books"]}["b-1"] == "b-1"


def test_truncated_gz_is_skipped(tmp_data):
    from unittest import mock
    occ = pd.read_parquet(tmp_data / "occurrences.parquet")
    pd.concat([occ, pd.DataFrame({"group_id": ["tk-8"], "hadith_id": [13], "book_slug": ["b-1"],
                                  "numbering": ["9"]})]).to_parquet(tmp_data / "occurrences.parquet")
    base = tmp_data / "raw/html/hadith"
    base.mkdir(parents=True)
    raw = gzip.compress(("<html>" + "x" * 5000 + "</html>").encode())
    (base / "12.html.gz").write_bytes(raw[: len(raw) // 2])
    with gzip.open(base / "13.html.gz", "wt", encoding="utf-8") as f:
        f.write("<html/>")
    rec = mock.Mock(book_title="صحيح البخاري")
    with mock.patch("isnad.export_site.parse_hadith", return_value=rec):
        books = {b["slug"]: b["title"] for b in meta_table(tmp_data)["books"]}
    assert books["b-1"] == "صحيح البخاري"


# ---- Task 2: groups, narrator details, atlas ------------------------------------------------

_CHAINS = {  # hadith_id -> [(rawi_id, term)…], Companion first
    21: [(1, "عن"), (2, "حدثنا"), (3, "أخبرنا"), (10, "حدثنا")],
    22: [(1, "عن"), (2, "عن"), (4, "حدثنا"), (10, "حدثنا")],
    23: [(1, "عن"), (2, None), (4, "سمعت"), (11, "حدثنا")],
    24: [(1, "عن"), (2, "حدثنا"), (3, "أخبرنا"), (10, "حدثنا")],
    25: [(7, "عن"), (4, "عن"), (11, "حدثنا")],
}


@pytest.fixture
def site_data(tmp_data):
    """tmp_data plus the Task 2 inputs: tk-5 (one root, CL 2), tk-6 (roots 1, 7), tk-7 (no chains)."""
    d = tmp_data
    rows = [{"hadith_id": h, "chain_no": 0, "position": i, "rawi_id": r, "term": t,
             "unjoined": False, "source": "html"}
            for h, ch in _CHAINS.items() for i, (r, t) in enumerate(ch)]
    pd.DataFrame(rows).to_parquet(d / "chains.parquet")
    pd.DataFrame({
        "group_id": ["tk-5", "tk-5", "tk-5", "tk-6", "tk-6", "tk-7"],
        "hadith_id": [21, 22, 23, 24, 25, 26],
        "book_slug": ["b-1", "b-2", "b-2", "b-1", "b-3", "b-1"],
        "numbering": ["1", "2", "3", "4", "5", "6"]}).to_parquet(d / "occurrences.parquet")
    pd.DataFrame({"group_id": ["tk-5", "tk-6", "tk-7"],
                  "complete": [True, False, True]}).to_parquet(d / "groups.parquet")
    pd.DataFrame({
        "rawi_id": [5, 2, 7, 1], "birth_lo": [10.0, 20, 50, None], "birth_hi": [20.0, 30, 60, None],
        "death_lo": [98.0, 100, 130, 40], "death_hi": [102.0, 110, 140, 60],
        "death_mode": [100.0, 105, 135, 50], "support": [4, 3, 2, 0],
        "method": ["known", "known", "inferred", "prior_only"]}
    ).to_parquet(d / "rawi_dates_inferred.parquet")
    pd.DataFrame({"group_id": ["tk-5"], "hadith_ids": [[24, 25, 26]]}).to_parquet(
        d / "shawahid.parquet")
    tree.run_tree(d / "chains.parquet", d / "occurrences.parquet", d / "groups.parquet",
                  d / "rawi_dates_inferred.parquet", d, shawahid_path=d / "shawahid.parquet")
    e = pd.DataFrame([
        ["tk-5", 1, 4, 2, "sub", "attributed", False, True, False, 1, 1, 2],
        ["tk-5", 2, 3, 2, "del", "partial", None, True, False, 1, 1, 2],
        ["tk-5", 3, None, None, "ins", "no_chain", None, False, False, 1, 0, 2],
        ["tk-5", 4, 2, 1, "sub", "ambiguous", True, False, False, 2, 2, 1],
        ["tk-5", 5, 99, 3, "ins", "attributed", False, True, False, 1, 1, 2],  # carrier-only
        ["tk-6", 1, 4, 1, "sub", "attributed", False, False, False, 1, 1, 1],
    ], columns=EDIT_COLS)
    e["introduced_by_rawi_id"] = e.introduced_by_rawi_id.astype("Int64")
    e["generation_depth"] = e.generation_depth.astype("Int64")
    e.to_parquet(d / "edits.parquet")
    pd.DataFrame({"depth": [0, 1], "n_transmissions": [0, 3], "n_edits": [0, 1],
                  "rate": pd.array([None, 1 / 3], dtype="Float64"), "n_edits_nonleaf": [0, 1],
                  "rate_nonleaf": pd.array([None, 1 / 3], dtype="Float64")}
                 ).to_parquet(d / "edit_rates.parquet")
    pd.DataFrame({"teacher_id": [2, 9], "student_id": [4, 2], "weight": [1, 1],
                  "cls": ["explicit", "explicit"], "reason": ["negative_cycle", "death_gap"],
                  "pass": [1, 1], "round": [1, 1]}).to_parquet(d / "dropped_links.parquet")
    return d


def test_group_json_matches_schema_and_cl(site_data):
    g = group_json("tk-5", SiteContext(site_data))
    jsonschema.validate(g, _schema("group"))
    assert g["cl"]["k2"]["id"] == 2 and g["roots"] == [1]
    assert g["cl"]["k2"] == {"id": 2, "lo": 100, "hi": 110, "method": "known", "all_chains": True}
    assert "k3" not in g["cl"]
    assert g["terms"]["2-4"] == "عن"
    assert g["terms"]["2-3"] == "حدثنا" and "4-11" in g["terms"] and g["terms"]["1-2"] == "عن"
    assert g["edits"]["by_node"]["4"] == [{"seg": 1, "type": "sub", "status": "attributed"}]
    assert g["edits"]["by_node"]["2"] == [{"seg": 4, "type": "sub", "status": "ambiguous"}]
    assert set(g["edits"]["by_node"]) == {"2", "4"}
    assert set(g["edits"]["by_node"]) <= {str(n["id"]) for n in g["nodes"]}
    assert g["edits"]["by_node_external"] == [
        {"id": 99, "seg": 5, "type": "ins", "status": "attributed"}]
    assert (g["edits"]["attributed"], g["edits"]["partial"], g["edits"]["no_chain"]) == (2, 1, 1)
    assert g["chains"] == [[1, 2, 3, 10], [1, 2, 4, 10], [1, 2, 4, 11]]
    assert g["books"] == {"b-1": [21], "b-2": [22, 23]}
    assert g["complete"] is True and g["all_chained"] is True
    assert g["shawahid"] == [1, 7]
    n2 = next(n for n in g["nodes"] if n["id"] == 2)
    assert n2 == {"id": 2, "root": 1, "depth": 1, "k": 2, "n_desc": 3, "cl2": True, "cl3": False,
                  "pcl2": False, "pcl3": False}


def test_group_json_two_roots(site_data):
    g = group_json("tk-6", SiteContext(site_data))
    assert g["roots"] == [1, 7] and {n["root"] for n in g["nodes"]} == {1, 7}
    assert g["cl"] == {} and g["shawahid"] == []


def test_group_json_without_chains(site_data):
    g = group_json("tk-7", SiteContext(site_data))     # occurrences only
    assert g["chains"] == [] and g["nodes"] == [] and g["cl"] == {}
    assert g["roots"] == [] and g["terms"] == {} and g["all_chained"] is False
    assert g["books"] == {"b-1": [26]}


def test_narrator_detail(site_data):
    ctx = SiteContext(site_data)
    n2 = narrator_detail(2, ctx)
    assert n2["teachers"] == [[1, 4]]
    assert n2["students"] == [[3, 2], [4, 2]]
    assert n2["cl_groups"] == [["tk-5", 100, 110]]
    assert n2["dropped"] == [[4, "negative_cycle"], [9, "death_gap"]]
    n404 = narrator_detail(404, ctx)
    assert n404 == {"teachers": [], "students": [], "cl_groups": [], "dropped": []}


def test_narrator_detail_written_for_every_chain_narrator(site_data, tmp_path):
    run_export_site(str(site_data), str(tmp_path / "out"))
    for rid in (1, 2, 3, 4, 7, 10, 11):
        assert (tmp_path / f"out/narrator/{rid % 100:02d}/{rid}.json").exists()
    for gid in ("tk-5", "tk-6", "tk-7"):
        assert (tmp_path / "out" / group_path(gid)).exists()
    assert (tmp_path / "out/atlas.json").exists()


def test_atlas(site_data):
    a = atlas_table(SiteContext(site_data))
    assert a["cl_hist"] == {"all": [[100, 1]], "b-1": [[100, 1]], "b-2": [[100, 1]]}
    assert a["drift"][1] == {"depth": 1, "n_transmissions": 3, "n_edits": 1, "rate": 0.3333,
                             "n_edits_nonleaf": 1, "rate_nonleaf": 0.3333}
    assert a["drift"][0]["rate"] is None
    assert a["boards"]["top_cls"] == [[2, 1]]
    assert a["boards"]["earliest"] == [["tk-5", 2, 100, 110]]
    # narrators by dropped dating links touching them: 2 (two links), then 4 and 9; 2 has no dy
    assert a["boards"]["conflicts"] == [[2, 2, None], [4, 1, None], [9, 1, None]]
    assert a["boards"]["top_editors"] == [[4, 2, 3], [99, 1, 0]]  # attributed, n_chains
    jsonschema.validate(a, _schema("atlas"))


def test_atlas_skips_prior_only(site_data):
    rd = pd.read_parquet(site_data / "report_dates.parquet")
    rd["cl_k2_date_method"] = pd.array(["prior_only"] * len(rd), dtype="string")
    rd.to_parquet(site_data / "report_dates.parquet")
    a = atlas_table(SiteContext(site_data))
    assert a["cl_hist"] == {"all": []} and a["boards"]["earliest"] == []


def test_shard_paths():
    assert group_path("tk-7") == Path("groups/07/tk-7.json")
    assert group_path("tk-1234") == Path("groups/34/tk-1234.json")
    assert group_path("tg-57182") == Path("groups/82/tg-57182.json")
    assert narrator_path(3) == Path("narrator/03/3.json")
    assert narrator_path(12345) == Path("narrator/45/12345.json")


def _schema(name):
    return json.loads(Path(f"tests/fixtures/site_{name}_schema.json").read_text(encoding="utf-8"))


def test_narrator_schema(site_data):
    ctx = SiteContext(site_data)
    for rid in (1, 2, 3, 4, 7, 10, 11, 404):
        jsonschema.validate(narrator_detail(rid, ctx), _schema("narrator"))


def test_years_rounded_outward(site_data):
    rd = pd.read_parquet(site_data / "report_dates.parquet")
    rd.loc[rd.group_id == "tk-5", ["cl_k2_date_lo", "cl_k2_date_hi"]] = [69.5, 77.5]
    rd.to_parquet(site_data / "report_dates.parquet")
    dt = pd.read_parquet(site_data / "rawi_dates_inferred.parquet")
    dt.loc[dt.rawi_id == 1, ["death_lo", "death_hi", "birth_lo", "birth_hi"]] = [-0.5, 77.5, -3.2, -0.5]
    dt.to_parquet(site_data / "rawi_dates_inferred.parquet")
    ctx = SiteContext(site_data)
    cl = group_json("tk-5", ctx)["cl"]["k2"]
    assert (cl["lo"], cl["hi"]) == (69, 78)
    assert narrator_detail(2, ctx)["cl_groups"] == [["tk-5", 69, 78]]
    a = atlas_table(ctx)
    assert a["boards"]["earliest"] == [["tk-5", 2, 69, 78]] and a["cl_hist"]["all"] == [[70, 1]]
    n1 = {r["id"]: r for r in narrators_table(site_data)}[1]
    assert (n1["dlo"], n1["dhi"], n1["blo"], n1["bhi"]) == (-1, 78, -4, 0)


def test_terms_from_collapsed_duplicate_use_row_next_to_student(site_data):
    ch = pd.read_parquet(site_data / "chains.parquet")
    dup = pd.DataFrame([{"hadith_id": 22, "chain_no": 0, "position": 1.5, "rawi_id": 2,
                         "term": "قال", "unjoined": False, "source": "html"}])
    ch = pd.concat([ch.astype({"position": float}), dup]).sort_values(["hadith_id", "position"])
    ch["position"] = ch.groupby(["hadith_id", "chain_no"]).cumcount()
    ch.to_parquet(site_data / "chains.parquet")
    g = group_json("tk-5", SiteContext(site_data))
    assert g["chains"][1] == [1, 2, 4, 10] and g["terms"]["2-4"] == "قال"


def test_export_refuses_out_over_data(site_data):
    with pytest.raises(ValueError, match="data dir"):
        run_export_site(str(site_data), str(site_data))
    with pytest.raises(ValueError, match="data dir"):
        run_export_site(str(site_data), str(site_data.parent))
    with pytest.raises(ValueError, match="cwd|repo root"):
        run_export_site(str(site_data), ".")


def test_reexport_drops_stale_groups(site_data, tmp_path):
    out = tmp_path / "out"
    stale = out / "groups/99/tk-99.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    (out / "keep.txt").write_text("x")
    run_export_site(str(site_data), str(out))
    assert not stale.exists() and (out / "keep.txt").exists()
    assert (out / group_path("tk-5")).exists()


def test_page_weight_on_real_export():
    out = Path("site_data")
    if not (out / "atlas.json").exists():
        pytest.skip("no real export")
    assert (out / "narrators.json").stat().st_size <= 3_000_000
    assert max(p.stat().st_size for p in out.glob("groups/*/*.json")) <= 200_000
    assert max(p.stat().st_size for p in out.glob("search/**/*.json")) <= 600_000
    jsonschema.validate(json.loads((out / "atlas.json").read_text(encoding="utf-8")),
                        _schema("atlas"))
