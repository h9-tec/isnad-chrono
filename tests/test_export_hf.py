import json
import re
from unittest import mock

import pandas as pd
import pytest

from isnad import cli, edits, export, export_hf, tree
from isnad.groups import hash_text

BASE1 = "كَانَ رَسُولُ اللَّهِ يَعْرِضُ الْكِتَابَ"
BASE2 = "عَلَى جِبْرِيلَ فِي رَمَضَانَ"
SUB = "القرآن"


def _segments(group="tk-1", carriers=(2,)):
    return pd.DataFrame({
        "group_id": [group] * 3, "seg_no": [0, 1, 2],
        "kind": ["base", "substitution", "base"],
        "base_hash": [hash_text(BASE1), hash_text(BASE1), hash_text(BASE2)],
        "variant_hash": [None, hash_text(SUB), None],
        "carrier_hadith_ids": [[], list(carriers), []]})


SUB2 = "رجب"


def _texts():
    return {hash_text(t): t for t in (BASE1, BASE2, SUB, SUB2)}


def _two_slots(group="tk-1"):
    """Substitution SUB after BASE1 carried by 2, SUB2 after BASE2 carried by 3."""
    return pd.DataFrame({
        "group_id": [group] * 4, "seg_no": [0, 1, 2, 3],
        "kind": ["base", "substitution", "base", "substitution"],
        "base_hash": [hash_text(BASE1), hash_text(BASE1), hash_text(BASE2), hash_text(BASE2)],
        "variant_hash": [None, hash_text(SUB), None, hash_text(SUB2)],
        "carrier_hadith_ids": [[], [2], [], [3]]})


def _other():  # BASE1, then BASE2 with its last word replaced by SUB2
    return BASE1 + " " + " ".join(BASE2.split()[:-1] + [SUB2])


def _variant():  # BASE1 with its last word replaced by SUB, then BASE2
    return " ".join(BASE1.split()[:-1] + [SUB]) + " " + BASE2


def _inputs(d):
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for hid, chain in {1: [10, 20, 30, 40], 2: [10, 20, 31, 41], 3: [10, 21, 32, 42]}.items():
        for pos, r in enumerate(chain):
            rows.append(dict(hadith_id=hid, chain_no=0, position=pos, rawi_id=r, term="حدثنا",
                             unjoined=False, source="html"))
    pd.DataFrame(rows).to_parquet(d / "chains.parquet")
    pd.DataFrame({"group_id": ["tk-1"], "n_entries": [3], "n_chains": [3], "books": [["b-1"]],
                  "n_occurrences": [3], "complete": [True]}).to_parquet(d / "groups.parquet")
    pd.DataFrame({"group_id": ["tk-1"] * 3, "hadith_id": [1, 2, 3], "book_slug": ["b-1"] * 3,
                  "numbering": ["1", "2", "3"]}).to_parquet(d / "occurrences.parquet")
    _two_slots().to_parquet(d / "segments.parquet")
    pd.DataFrame({"group_id": ["tk-1"], "companion_rawi_id": [11],
                  "companion_name": ["أبو هريرة"], "hadith_ids": [[5]]}
                 ).to_parquet(d / "shawahid.parquet")
    (d / "text").mkdir()
    t = _texts()
    pd.DataFrame({"hash": list(t), "text": list(t.values())}).to_parquet(
        d / "text" / "segments_text.parquet")
    ids = [10, 20, 21, 30, 31, 32, 40, 41, 42]
    pd.DataFrame({"rawi_id": ids, "name": ["secret"] * 9, "kunya": ["k"] * 9,
                  "generation_num": [1] * 9, "death_year": [50.0] * 9,
                  "death_kind": ["exact"] * 9, "birth_year": [None] * 9,
                  "birth_kind": ["none"] * 9}).to_parquet(d / "rawi.parquet")
    pd.DataFrame({"rawi_id": ids + [99], "birth_lo": [0.0] * 10, "birth_hi": [10.0] * 10,
                  "death_lo": [40.0] * 10, "death_hi": [60.0] * 10, "death_mode": [50.0] * 10,
                  "support": [1] * 10, "method": ["known"] * 9 + ["inferred"]}
                 ).to_parquet(d / "rawi_dates_inferred.parquet")
    pd.DataFrame({"teacher_id": [20], "student_id": [30], "weight": [1], "cls": ["ambiguous"],
                  "reason": ["cycle"], "pass": [1], "round": [2]}
                 ).to_parquet(d / "dropped_links.parquet")
    (d / "checks_dating.json").write_text(json.dumps({
        "folds": 5, "n_scored": 7,
        "method": {"median_abs_error": 12.5, "mean_abs_error": 35.5, "coverage_90": 0.979,
                   "median_width": 92.0},
        "method_bounded": {"median_abs_error": 11.5, "mean_abs_error": 14.8, "coverage_90": 0.98,
                           "n": 6},
        "depth": {"median_abs_error": 15.45, "mean_abs_error": 24.3, "coverage_90": 0.901},
        "generation_mean": {"median_abs_error": 13.2, "mean_abs_error": 18.4, "coverage_90": 0.91},
        "per_fold": [{"fold": 0}], "run": {"n_dropped": 1, "seconds": {"links": 0.1}}}))
    es = {c: [False] for c in export_hf.EDGE_SCORE_COLS}
    es |= {"teacher_id": [1], "student_id": [2], "hadith_id": [9], "position": [0],
           "term": ["عن"], "chain_type": ["x"], "entry_kind": ["x"], "p_meet": [0.4],
           "how": ["birth_imputed"], "verdict": ["ok"]}
    pd.DataFrame(es).to_parquet(d / "edge_scores.parquet")
    tree.run_tree(d / "chains.parquet", d / "occurrences.parquet", d / "groups.parquet",
                  d / "rawi_dates_inferred.parquet", d, shawahid_path=d / "shawahid.parquet")
    edits.run_edits(d / "segments.parquet", d / "chains.parquet", d / "occurrences.parquet",
                    d / "edits.parquet", d / "edit_rates.parquet")


def test_release_configs_and_denylist(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    out.mkdir()
    (out / "MANIFEST.json").write_text("{}")  # a previous release ...
    (out / "stale_text.parquet").write_text("x")  # ... whose stale files must not survive
    man = export_hf.build_release(d, out,
                                  matns={1: BASE1 + " " + BASE2, 2: _variant(), 3: _other()},
                                  cache_root=_cache(tmp_path / "cache"))
    for c in export_hf.REQUIRED_CONFIGS:
        assert (out / "data" / f"{c}.parquet").exists(), c
    assert not (out / "stale_text.parquet").exists()
    files = export_hf.verify_release(out)
    assert not [f for f in files if "text" in f]
    for f in (out / "data").glob("*.parquet"):
        df = pd.read_parquet(f)
        assert not [c for c in df.columns if re.search(export.DENYLIST, c, re.I)], f
        for col in df.columns:  # no segment text anywhere
            assert not df[col].astype(str).str.contains("جبريل|الكتاب").any(), (f, col)
    assert "companion_name" not in pd.read_parquet(out / "data" / "shawahid.parquet").columns
    nar = pd.read_parquet(out / "data" / "narrators.parquet")
    assert list(nar.columns) == export_hf.NARRATOR_COLS and len(nar) == 10
    checks = json.loads((out / "checks.json").read_text())
    assert checks["alignment_agreement"] == 1.0
    assert checks["alignment_n_pairs_scored"] == 2
    assert checks["alignment_control_surface_found_rate"] == 0.0
    assert checks["sanity_n_dropped_links"] == 1
    assert checks["sanity_compiler_leaf_rate"] == 1.0
    assert checks["sanity_root_no_parent_rate"] == 1.0
    assert checks["dating_method_median_abs_error"] == 12.5
    assert checks["n_hadith_pages_cached"] == 2
    assert checks["groups_complete_rate"] == 1.0 and checks["occurrence_chain_rate"] == 1.0
    assert checks["edits_no_chain_rate"] == 0.0
    assert checks["cl_k2_rate_multi"] == 1.0 and checks["cl_k3_rate_multi"] == 0.0
    assert checks["cl_k2_bounded_rate"] == 1.0  # synthetic intervals are 20 years wide
    assert "coverage_groups_cl_k2_dated_rate" not in checks
    assert checks["release_version"] == "v0.1.1"
    assert checks["cl_k2_prior_only_rate"] == 0.0 and checks["coverage_cl_k2_prior_only"] == 0
    assert checks["all_occurrences_have_chain_rate"] == 1.0
    assert checks["six_books_cached_rate"] == 2 / 3  # pages 2 and 3 of the 3 b-1 occurrences
    grp = pd.read_parquet(out / "data" / "groups.parquet")
    assert grp.all_occurrences_have_chain.tolist() == [True]
    rd = pd.read_parquet(out / "data" / "report_dates.parquet")
    assert list(rd.columns) == tree.REPORT_COLS and rd.cl_k2_date_method.tolist() == ["known"]
    row = pd.read_parquet(out / "data" / "checks.parquet").iloc[0]
    assert row["edits_no_chain_rate"] == 0.0 and row["cl_k2_rate_multi"] == 1.0
    assert not [k for k in checks if "per_fold" in k or "seconds" in k]
    assert len(pd.read_parquet(out / "data" / "checks.parquet")) == 1
    readme = (out / "README.md").read_text()
    for s in ("12.500", "0.979", "15.450", "v0.1", "config_name: narrators", "hdith.com",
              "35.500", "24.300", "14.800", "partial crawl", "2 hadith pages",
              "among the 1 groups with at least 2 parsed chains",
              "mean error is higher than the baseline's (35.5 vs 24.3)",
              "bounded intervals the mean error is 14.8 years",
              "The Six Books are not complete: 0.6667",
              "Every k=2 common link has an inferred death interval",
              "0 k=2 common links\n  (0.000) are dated by the prior alone", "v0.1 → v0.1.1"):
        assert s in readme, s
    assert "{{" not in readme and "n/a" not in readme
    assert man["chains"]["rows"] == 12


def test_card_prose_follows_the_numbers():
    better = export_hf.card_prose({
        "six_books_cached_rate": 1.0, "dating_method_median_abs_error": 10.0,
        "dating_depth_median_abs_error": 20.0, "dating_method_mean_abs_error": 15.0,
        "dating_depth_mean_abs_error": 25.0, "coverage_n_cl_k2": 4,
        "coverage_cl_k2_dated_rate": 0.5})
    assert better["prose_six_books"].startswith("The Six Books are complete")
    assert "mean error is lower than" in better["prose_dating"]
    assert "tail" not in better["prose_dating"]
    assert better["prose_cl_dates"].startswith("0.500 of the k=2 common links")
    worse = export_hf.card_prose({"dating_method_median_abs_error": 30.0,
                                  "dating_depth_median_abs_error": 20.0,
                                  "dating_method_mean_abs_error": 40.0,
                                  "dating_depth_mean_abs_error": 25.0})
    assert "median error of propagation is higher than" in worse["prose_dating"]
    assert "tail" in worse["prose_dating"]
    assert "not measured" in worse["prose_six_books"]
    assert worse["prose_cl_dates"] == "No k=2 common link was found."


def test_long_terms_rejected():
    export_hf.check_terms(pd.DataFrame({"term": ["حدثنا", None, "قرئ على فلان وأنا أسمع"]}), "c")
    with pytest.raises(ValueError):
        export_hf.check_terms(pd.DataFrame({"term": ["كان رسول الله يعرض الكتاب على جبريل"]}),
                              "chains")


def test_name_columns_denylisted():
    with pytest.raises(ValueError):
        export.check_columns(pd.DataFrame({"companion_name": ["x"]}), "shawahid")


def test_long_strings_rejected():
    with pytest.raises(ValueError):
        export_hf.check_strings(pd.DataFrame({"term": ["و" * 200]}), "chains")


def test_alignment_check_on_synthetic():
    seg = _segments(carriers=(2, 3))
    # carrier texts identical to the site's variant reading -> every span agrees
    r = export_hf.alignment_check(seg, _texts(), {2: _variant(), 3: _variant()})
    assert r["agreement"] == 1.0 and r["n_pairs_scored"] == 2
    # a carrier identical to the base shows no difference at the span -> disagreement
    r = export_hf.alignment_check(seg, _texts(), {2: _variant(), 3: BASE1 + " " + BASE2})
    assert r["agreement"] == 0.5
    # two slots: each carrier reads the base at the other slot -> control pairs without hits
    r = export_hf.alignment_check(_two_slots("tk-2"), _texts(), {2: _variant(), 3: _other()})
    assert r["agreement"] == 1.0 and r["n_control_pairs"] == 2 and r["control_hit_rate"] == 0.0
    assert r["surface_found_rate"] == 1.0 and r["control_surface_found_rate"] == 0.0
    # missing carrier text is counted, not scored; a loader callable works too
    r = export_hf.alignment_check(seg, _texts(), lambda ids: {2: _variant()})
    assert r["n_pairs_no_carrier_matn"] == 1 and r["agreement"] == 1.0


def _cache(root):
    """Cached pages for carriers 2 and 3, in the site's page-JSON form."""
    (root / "hadith").mkdir(parents=True)
    for h, matn in ((2, _variant()), (3, _other())):
        page = json.dumps({"component": "x", "props": {"hadith": {"matn": matn}}})
        (root / "hadith" / f"{h}.html").write_text(
            f'<script data-page="app" type="application/json">{page}</script>')
    return root


def test_push_is_mocked(tmp_path, capsys):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nHF_TOKEN='hf_secret123'\n")
    with mock.patch("huggingface_hub.HfApi") as api_cls:
        cli.main(["export-hf", "--data-dir", str(d), "--out", str(out), "--push",
                  "--env-file", str(env), "--cache-root", str(_cache(tmp_path / "cache"))])
    api_cls.assert_called_once_with(token="hf_secret123")
    api = api_cls.return_value
    api.create_repo.assert_called_once_with("HeshamHaroon/isnad-chrono", repo_type="dataset",
                                            exist_ok=True, private=False)
    kw = api.upload_folder.call_args.kwargs
    assert kw["folder_path"] == str(out) and kw["repo_type"] == "dataset"
    assert kw["delete_patterns"] == ["data/*.parquet", "*.json", "README.md"]
    assert "hf_secret123" not in capsys.readouterr().out


def test_push_without_token_fails(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(SystemExit):
        cli.main(["export-hf", "--data-dir", str(d), "--out", str(out), "--push",
                  "--env-file", str(tmp_path / "missing.env"),
                  "--cache-root", str(tmp_path / "nocache")])
    api_cls.assert_not_called()
    assert not out.exists()  # the token is read before the build


def test_push_refuses_unverified_folder(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(ValueError):
        export_hf.push(tmp_path, token="t")
    api_cls.assert_not_called()


def test_push_refuses_null_checks_and_na(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    export_hf.build_release(d, out)  # no carrier texts -> alignment checks null
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(ValueError, match="null"):
        export_hf.push(out, token="t")
    export_hf.build_release(d, out, matns={2: _variant(), 3: _other()})
    readme = out / "README.md"
    readme.write_text(readme.read_text() + "\nn/a\n")
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(ValueError, match="n/a"):
        export_hf.push(out, token="t")
    api_cls.assert_not_called()


def test_out_guard_protects_data(tmp_path):
    d = tmp_path / "data"
    _inputs(d)
    before = sorted(p for p in d.rglob("*"))
    for bad in (d, tmp_path, d / "text"):
        with pytest.raises(ValueError, match="refusing"):
            export_hf.build_release(d, bad, matns={})
    with pytest.raises(ValueError, match="refusing"):
        cli.main(["export-hf", "--data-dir", str(d), "--out", str(d),
                  "--cache-root", str(tmp_path / "nocache")])
    other = tmp_path / "notes"
    other.mkdir()
    (other / "keep.txt").write_text("x")
    with pytest.raises(ValueError, match="not a release"):
        export_hf.build_release(d, other, matns={})
    assert sorted(p for p in d.rglob("*")) == before and (other / "keep.txt").exists()
    out = tmp_path / "release_hf"  # a previous release folder may be rebuilt
    export_hf.build_release(d, out, matns={})
    export_hf.build_release(d, out, matns={})


def test_verify_rejects_unknown_release_file(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    export_hf.build_release(d, out, matns={2: _variant(), 3: _other()})
    pd.DataFrame({"hash": ["ab"], "text": ["x"]}).to_parquet(out / "data" / "segments_text.parquet")
    with pytest.raises(ValueError, match="unexpected"):
        export_hf.verify_release(out)
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(ValueError):
        export_hf.push(out, token="t")
    api_cls.assert_not_called()
    for col in ("text", "surface", "wording", "word", "words", "variant_text"):
        with pytest.raises(ValueError):
            export.check_columns(pd.DataFrame({col: ["x"]}), "x")


def test_long_strings_in_lists_rejected():
    with pytest.raises(ValueError):
        export_hf.check_strings(pd.DataFrame({"books": [["b-1", "و" * 200]]}), "groups")
    export_hf.check_strings(pd.DataFrame({"books": [["b-1", "b-2"]]}), "groups")


def test_sanity_root_parent_and_root_earliest():
    # group graph: Companion 1 heads one chain and sits below Companion 2 in another
    t = tree.merge_tree([[1, 5, 6], [2, 1, 7]])
    dates = pd.DataFrame({"rawi_id": [1, 2, 6, 7], "death_lo": [30.0, 90.0, 50.0, 60.0],
                          "death_hi": [40.0, 95.0, 70.0, 80.0],
                          "method": ["known"] * 4})
    chains = pd.DataFrame({"hadith_id": [1], "chain_no": [0], "unjoined": [False]})
    r = export_hf.sanity_checks({"g": t}, chains, dates=dates)
    assert r["n_components"] == 2 and r["n_roots_with_parent"] == 1
    assert r["root_no_parent_rate"] == 0.5
    # root 1 (lo 30) <= terminal 6 (hi 70): ok; root 2 (lo 90) > terminal 7 (hi 80): not ok
    assert r["n_root_date_checked"] == 2 and r["root_earliest_rate"] == 0.5
    undated = dates.assign(method=["prior_only"] * 4)
    assert export_hf.sanity_checks({"g": t}, chains, dates=undated)["root_earliest_rate"] is None


def test_malformed_input_is_argparse_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["export-hf", "--out", str(tmp_path / "o"), "--input", "chains"])
    assert e.value.code == 2 and "KEY=PATH" in capsys.readouterr().err


def test_all_null_shawahid_companion_dropped(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    sh = pd.read_parquet(d / "shawahid.parquet")
    sh.assign(companion_rawi_id=pd.array([None], dtype="Int64")).to_parquet(d / "shawahid.parquet")
    export_hf.build_release(d, out, matns={2: _variant(), 3: _other()},
                            cache_root=_cache(tmp_path / "cache"))
    assert "companion_rawi_id" not in pd.read_parquet(out / "data" / "shawahid.parquet").columns
    readme = (out / "README.md").read_text()
    assert "null on every row" in readme and "n/a" not in readme
