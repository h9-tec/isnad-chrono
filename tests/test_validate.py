import json

import numpy as np
import pandas as pd

from isnad import cli, validate


def _scores(rows):
    base = dict(teacher_id=1, student_id=2, hadith_id=1, position=0, term="سمعت",
                chain_type="متصل", entry_kind="x", p_meet=0.9, how="birth_known",
                conflict_t=False, conflict_s=False, confirmed=False, explicit_term=True,
                ambiguous_term=False, denied=False, irsal=False, tadlis=False, verdict="ok")
    return pd.DataFrame([{**base, **r} for r in rows])


def _hadith():
    return pd.DataFrame({"hadith_id": [1, 2, 3], "book_slug": ["b-1", "b-2", "b-9"]})


def test_auroc_perfect():
    assert validate.auroc(pd.Series([0.9, 0.8]), pd.Series([0.1, 0.2])) == 1.0


def test_auroc_random():
    rng = np.random.default_rng(0)
    a = validate.auroc(pd.Series(rng.random(2000)), pd.Series(rng.random(2000)))
    assert abs(a - 0.5) < 0.05
    assert validate.auroc(pd.Series([1.0]), pd.Series([1.0])) == 0.5


def test_positives_filter():
    sc = _scores([{"hadith_id": 1}, {"hadith_id": 2, "explicit_term": False},
                  {"hadith_id": 3}, {"hadith_id": 3, "confirmed": True},
                  {"hadith_id": 1, "verdict": "no_dates"}])
    pos = validate.positives(sc, hadith=_hadith())
    assert len(pos) == 2
    assert set(pos["hadith_id"]) == {1, 3}


def test_positive_set_excludes_muallaq():
    sc = _scores([{"chain_type": "معلق", "student_id": 5}, {"chain_type": "متصل", "student_id": 6}])
    pos = validate.positives(sc, hadith=_hadith())
    assert list(pos["student_id"]) == [6]


def test_metrics_keys(tmp_path):
    sc = _scores([{"hadith_id": 1, "p_meet": 0.9}, {"hadith_id": 2, "p_meet": 0.5},
                  {"hadith_id": 2, "p_meet": float("nan"), "how": "no_dates", "verdict": "no_dates"}])
    rawi = pd.DataFrame({"rawi_id": [1, 2, 3, 4], "death_year": [100.0, 150.0, 300.0, 100.0],
                         "death_sd": [1.0] * 4, "death_kind": ["exact"] * 4,
                         "birth_year": [None, 60.0, 250.0, None], "birth_sd": [None, 1.0, 1.0, None],
                         "birth_kind": ["none", "exact", "exact", "none"]})
    den = pd.DataFrame({"student_id": [3, 2], "teacher_id": pd.array([1, None], dtype="Int64"),
                        "relation": ["x", "x"], "resolved": [True, False], "ambiguous": [False, False]})
    m = validate.metrics(sc, {"marasil": den}, rawi, _hadith())
    assert set(m["marasil"]) == {"auroc", "n", "recall@0.05", "recall@0.1", "recall@0.2"}
    assert m["marasil"]["n"] == 1 and m["marasil"]["recall@0.05"] == 1.0
    assert m["marasil"]["auroc"] == 1.0
    assert m["n_positives"] == 2
    assert set(m["false_flag_rate"]) == {"@0.05", "@0.1", "@0.2"}
    assert m["verdict_counts_by_book"]["b-2"]["ok"] == 2
    assert set(m["coverage"]) == {"how", "death_kind"}
    json.dumps(m, allow_nan=False)


def test_validate_cli_writes_outputs(tmp_path):
    sc = _scores([{"hadith_id": 1}])
    rawi = pd.DataFrame({"rawi_id": [1, 2], "death_year": [100.0, 150.0], "death_sd": [1.0, 1.0],
                         "death_kind": ["exact", "exact"], "birth_year": [None, 60.0],
                         "birth_sd": [None, 1.0], "birth_kind": ["none", "exact"]})
    den = pd.DataFrame({"student_id": [2], "teacher_id": pd.array([1], dtype="Int64"),
                        "relation": ["x"], "resolved": [True], "ambiguous": [False]})
    for n, d in [("sc", sc), ("rawi", rawi), ("h", _hadith()), ("dm", den), ("dt", den)]:
        d.to_parquet(tmp_path / f"{n}.parquet")
    cli.main(["validate", "--scores", str(tmp_path / "sc.parquet"), "--rawi", str(tmp_path / "rawi.parquet"),
              "--hadith", str(tmp_path / "h.parquet"), "--denials-marasil", str(tmp_path / "dm.parquet"),
              "--denials-tuhfa", str(tmp_path / "dt.parquet"), "--out", str(tmp_path / "m.json"),
              "--figures", str(tmp_path / "fig")])
    assert (tmp_path / "m.json").exists()
    assert (tmp_path / "fig" / "p_meet_marasil.png").exists()
    assert (tmp_path / "fig" / "verdicts_by_book.png").exists()
