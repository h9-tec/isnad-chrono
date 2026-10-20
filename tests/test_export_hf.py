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


def _texts():
    return {hash_text(t): t for t in (BASE1, BASE2, SUB)}


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
    _segments().to_parquet(d / "segments.parquet")
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
        "method": {"median_abs_error": 12.5, "coverage_90": 0.979, "median_width": 92.0},
        "depth": {"median_abs_error": 15.45, "coverage_90": 0.901},
        "per_fold": [{"fold": 0}], "run": {"n_dropped": 1, "seconds": {"links": 0.1}}}))
    pd.DataFrame({"teacher_id": [1], "student_id": [2], "hadith_id": [9], "position": [0],
                  "term": ["عن"], "p_meet": [0.4], "how": ["birth_imputed"], "verdict": ["ok"]}
                 ).to_parquet(d / "edge_scores.parquet")
    tree.run_tree(d / "chains.parquet", d / "occurrences.parquet", d / "groups.parquet",
                  d / "rawi_dates_inferred.parquet", d, shawahid_path=d / "shawahid.parquet")
    edits.run_edits(d / "segments.parquet", d / "chains.parquet", d / "occurrences.parquet",
                    d / "edits.parquet", d / "edit_rates.parquet")


def test_release_configs_and_denylist(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    out.mkdir()
    (out / "stale_text.parquet").write_text("x")  # must not survive into the upload folder
    man = export_hf.build_release(d, out, matns={1: BASE1 + " " + BASE2, 2: _variant()})
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
    assert checks["alignment_n_pairs_scored"] == 1
    assert checks["sanity_n_dropped_links"] == 1
    assert checks["sanity_compiler_leaf_rate"] == 1.0
    assert checks["sanity_root_no_parent_rate"] == 1.0
    assert checks["dating_method_median_abs_error"] == 12.5
    assert not [k for k in checks if "per_fold" in k or "seconds" in k]
    assert len(pd.read_parquet(out / "data" / "checks.parquet")) == 1
    readme = (out / "README.md").read_text()
    for s in ("12.500", "0.979", "15.450", "v0.1", "config_name: narrators", "hdith.com"):
        assert s in readme, s
    assert "{{" not in readme
    assert man["chains"]["rows"] == 12


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
    two = pd.DataFrame({
        "group_id": ["tk-2"] * 4, "seg_no": [0, 1, 2, 3],
        "kind": ["base", "substitution", "base", "substitution"],
        "base_hash": [hash_text(BASE1), hash_text(BASE1), hash_text(BASE2), hash_text(BASE2)],
        "variant_hash": [None, hash_text(SUB), None, hash_text("رجب")],
        "carrier_hadith_ids": [[], [2], [], [3]]})
    other = BASE1 + " " + " ".join(BASE2.split()[:-1] + ["رجب"])
    r = export_hf.alignment_check(two, _texts(), {2: _variant(), 3: other})
    assert r["agreement"] == 1.0 and r["n_control_pairs"] == 2 and r["control_hit_rate"] == 0.0
    assert r["surface_found_rate"] == 1.0 and r["control_surface_found_rate"] == 0.0
    # missing carrier text is counted, not scored; a loader callable works too
    r = export_hf.alignment_check(seg, _texts(), lambda ids: {2: _variant()})
    assert r["n_pairs_no_carrier_matn"] == 1 and r["agreement"] == 1.0


def test_push_is_mocked(tmp_path, capsys):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nHF_TOKEN='hf_secret123'\n")
    with mock.patch("huggingface_hub.HfApi") as api_cls:
        cli.main(["export-hf", "--data-dir", str(d), "--out", str(out), "--push",
                  "--env-file", str(env), "--cache-root", str(tmp_path / "nocache")])
    api_cls.assert_called_once_with(token="hf_secret123")
    api = api_cls.return_value
    api.create_repo.assert_called_once_with("HeshamHaroon/isnad-chrono", repo_type="dataset",
                                            exist_ok=True, private=False)
    kw = api.upload_folder.call_args.kwargs
    assert kw["folder_path"] == str(out) and kw["repo_type"] == "dataset"
    assert "hf_secret123" not in capsys.readouterr().out


def test_push_without_token_fails(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release_hf"
    _inputs(d)
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(SystemExit):
        cli.main(["export-hf", "--data-dir", str(d), "--out", str(out), "--push",
                  "--env-file", str(tmp_path / "missing.env")])
    api_cls.assert_not_called()


def test_push_refuses_unverified_folder(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    with mock.patch("huggingface_hub.HfApi") as api_cls, pytest.raises(ValueError):
        export_hf.push(tmp_path, token="t")
    api_cls.assert_not_called()
