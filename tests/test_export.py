import json
import re

import pandas as pd
import pytest

from isnad import export


def _inputs(d):
    pd.DataFrame({"teacher_id": [1], "student_id": [2], "hadith_id": [9], "position": [0],
                  "term": ["حدثنا"], "chain_type": ["مسند"], "entry_kind": ["x"]}
                 ).to_parquet(d / "edges.parquet")
    pd.DataFrame({"teacher_id": [1], "student_id": [2], "term": ["عن"], "p_meet": [0.4],
                  "how": ["birth_imputed"], "verdict": ["ok"]}).to_parquet(d / "edge_scores.parquet")
    pd.DataFrame({"rawi_id": [1], "name": ["secret"], "kunya": ["k"], "generation_num": [3],
                  "death_year": [100], "death_sd": [1.0], "death_kind": ["exact"],
                  "birth_year": [None], "birth_sd": [None], "birth_kind": ["none"],
                  "is_companion": [False], "flags": ["{}"], "sama_confirmed": [[]],
                  "teachers_ids": [[]], "students_ids": [[2]], "narrative_years": [[1]]}
                 ).to_parquet(d / "rawi.parquet")


def test_export_writes_clean_files(tmp_path):
    d, out = tmp_path / "data", tmp_path / "release"
    d.mkdir()
    _inputs(d)
    export.run_export(str(d), str(out))
    for f in ("edges", "edge_scores", "rawi_dates"):
        df = pd.read_parquet(out / f"{f}.parquet")
        assert not [c for c in df.columns if re.search(export.DENYLIST, c, re.I)]
    assert list(pd.read_parquet(out / "rawi_dates.parquet").columns) == export.RAWI_COLS
    man = json.loads((out / "MANIFEST.json").read_text())
    assert man["edges.parquet"]["rows"] == 1


def test_denylist_enforced(tmp_path):
    with pytest.raises(ValueError):
        export.check_columns(pd.DataFrame({"matn": [1]}), "x")
