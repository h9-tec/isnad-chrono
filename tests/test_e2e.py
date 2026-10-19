"""End-to-end wiring: fixtures -> build -> gold (stub runner) -> score -> validate -> report -> export.

The narrator fixture (rawi 4494) is in no fixture chain, so every edge is missing_rawi /
no_dates; this asserts the stages connect and write their outputs, not the numbers.
"""
import json
import shutil
from pathlib import Path

import pandas as pd

from isnad import cli, gold

FIX = Path(__file__).parent / "fixtures"


def _stub_runner(prompt: str) -> str:
    return "\n".join([
        '{"student_id": 4494, "teacher": "عمر بن الخطاب", "relation": "no_sama", "quote": "q"}',
        '{"student_id": 4494, "teacher": "عائشة", "relation": "sama", "quote": "q"}',
        "not json",
    ])


def test_pipeline_end_to_end(tmp_path, capsys):
    root = tmp_path / "raw" / "html"
    (root / "hadith").mkdir(parents=True)
    (root / "rawi").mkdir()
    shutil.copy(FIX / "rawi_4494.html", root / "rawi" / "4494.html")
    shutil.copy(FIX / "hadith_muslim_11563.html", root / "hadith" / "11563.html")
    shutil.copy(FIX / "hadith_muslim_11558_nochain.html", root / "hadith" / "11558.html")
    data = tmp_path / "data"
    d = lambda name: str(data / name)

    cli.main(["build", "--cache-root", str(root), "--out-dir", str(data)])
    for name in ("rawi.parquet", "hadith.parquet", "edges.parquet", "opinions.parquet",
                 "tuhfa.parquet"):
        assert (data / name).exists(), name
    edges = pd.read_parquet(data / "edges.parquet")
    assert len(edges) == 6 and edges["term"].notna().all()

    marasil = tmp_path / "marasil.json"
    marasil.write_text(json.dumps([
        {"student": "علقمة بن وقاص", "teacher": "عمر بن الخطاب", "relation": "no_sama",
         "authority": "x", "quote": "q"},
        {"student": "شعبة", "teacher": "الحكم", "relation": "sama", "authority": "x", "quote": "q"},
    ], ensure_ascii=False), encoding="utf-8")
    gold.run_gold(d("rawi.parquet"), d("tuhfa.parquet"), marasil, data, runner=_stub_runner)
    for name in ("denials_marasil.parquet", "denials_tuhfa.parquet", "denials.parquet"):
        assert (data / name).exists(), name
    assert {"student_id", "teacher_id", "relation", "source"} <= set(
        pd.read_parquet(data / "denials.parquet").columns)

    cli.main(["score", "--edges", d("edges.parquet"), "--rawi", d("rawi.parquet"),
              "--denials", d("denials.parquet"), "--out", d("edge_scores.parquet")])
    sc = pd.read_parquet(data / "edge_scores.parquet")
    assert len(sc) == 6
    assert {"p_meet", "how", "verdict", "explicit_term", "ambiguous_term", "hadith_id"} <= set(sc.columns)
    assert set(sc["how"]) == {"missing_rawi"} and set(sc["verdict"]) == {"no_dates"}
    assert "term class (edge rows):" in capsys.readouterr().out

    cli.main(["validate", "--scores", d("edge_scores.parquet"), "--rawi", d("rawi.parquet"),
              "--hadith", d("hadith.parquet"), "--denials-marasil", d("denials_marasil.parquet"),
              "--denials-tuhfa", d("denials_tuhfa.parquet"), "--out", d("metrics.json"),
              "--figures", str(tmp_path / "figures")])
    m = json.loads((data / "metrics.json").read_text())
    assert set(m["negatives"]) == {"marasil", "tuhfa"}
    assert set(m["negatives"]["marasil"]) == {"no_idrak", "mursal", "no_sama"}
    assert {"n_positives", "n_positives_scored", "positives", "sama_attested",
            "verdict_counts_by_book", "coverage"} <= set(m)
    assert (tmp_path / "figures" / "verdicts_by_book.png").exists()

    cli.main(["report", "--scores", d("edge_scores.parquet"), "--rawi", d("rawi.parquet"),
              "--hadith", d("hadith.parquet"), "--db", str(tmp_path / "absent.sqlite"),
              "--out-dir", str(data)])
    for name in ("weak_edges.csv", "date_errors.csv", "run_report.md"):
        assert (data / name).exists(), name
    assert "teacher_id" in pd.read_csv(data / "weak_edges.csv").columns

    cli.main(["export", "--data-dir", str(data), "--out", str(tmp_path / "release")])
    man = json.loads((tmp_path / "release" / "MANIFEST.json").read_text())
    assert set(man) == {"edges.parquet", "edge_scores.parquet", "rawi_dates.parquet"}
    assert man["edges.parquet"]["rows"] == 6 and man["rawi_dates.parquet"]["rows"] == 1
    for name in man:
        assert (tmp_path / "release" / name).exists()
