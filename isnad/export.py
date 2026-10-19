"""Release export: IDs, years, flags, scores and verdicts only. No source text."""

import json
import re
from pathlib import Path

import pandas as pd

DENYLIST = (r"^(name|abbrev|kunya|lineage|statement|content|matn|fullname|quote|teacher|student"
            r"|scholar)$|_text$|^narrative_years$|^name_forms$|^grading_json$|^book_title$|^number$")
EDGE_COLS = ["teacher_id", "student_id", "hadith_id", "position", "term", "chain_type",
             "entry_kind"]
RAWI_COLS = ["rawi_id", "generation_num", "death_year", "death_sd", "death_kind", "birth_year",
             "birth_sd", "birth_kind", "is_companion", "flags", "sama_confirmed",
             "teachers_ids", "students_ids"]


def check_columns(df: pd.DataFrame, label: str) -> None:
    bad = [c for c in df.columns if re.search(DENYLIST, c, re.IGNORECASE)]
    if bad:
        raise ValueError(f"{label}: denylisted columns {bad}")


def run_export(data_dir: str = "data", out_dir: str = "release") -> dict:
    d, out = Path(data_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    edges = pd.read_parquet(d / "edges.parquet")
    outputs = {
        "edges.parquet": edges[[c for c in EDGE_COLS if c in edges.columns]],
        "edge_scores.parquet": pd.read_parquet(d / "edge_scores.parquet"),
        "rawi_dates.parquet": pd.read_parquet(d / "rawi.parquet")[RAWI_COLS],
    }
    manifest = {}
    for fname, df in outputs.items():
        check_columns(df, fname)
        df.to_parquet(out / fname, index=False)
        manifest[fname] = {"rows": int(len(df)), "columns": list(df.columns)}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
