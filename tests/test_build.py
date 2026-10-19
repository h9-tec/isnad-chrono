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
    assert build.build_hadith(root, out / "hadith.parquet", out / "edges.parquet") == (2, 6)
    rawi = pd.read_parquet(out / "rawi.parquet")
    assert len(rawi) == 1 and len(rawi.iloc[0]["teachers_ids"]) == 13
    assert 3026 in set(rawi.iloc[0]["teachers_ids"]) and rawi.iloc[0]["death_kind"] == "era"
    assert len(pd.read_parquet(out / "opinions.parquet")) == 19
    assert len(pd.read_parquet(out / "tuhfa.parquet")) == 1
    h = pd.read_parquet(out / "hadith.parquet")
    assert {"n_links", "grading_json"} <= set(h.columns)
    errs = pd.read_csv(out / "build_errors.csv")
    assert len(errs) == 2 and all(errs["path"].str.endswith("bad.html"))
