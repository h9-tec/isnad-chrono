"""Turn cached HTML pages into the parquet tables later stages read."""

import csv
import dataclasses
import json
from pathlib import Path

import pandas as pd

from isnad.pageprops import NoPageData
from isnad.parse_hadith import Edge, edges, parse_hadith
from isnad.parse_rawi import RawiRecord, parse_rawi

_PARSE_ERRORS = (NoPageData, ValueError, KeyError, json.JSONDecodeError, TypeError, IndexError)
_RAWI_DROP = {"teachers", "students", "opinions", "death", "birth", "tuhfa_entries"}


def _log_error(errors_path: Path, path: Path, exc: Exception) -> None:
    new = not errors_path.exists()
    with errors_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["path", "error"])
        w.writerow([str(path), f"{type(exc).__name__}: {exc}"])


def _rawi_columns() -> list[str]:
    cols = [f.name for f in dataclasses.fields(RawiRecord) if f.name not in _RAWI_DROP]
    cols += ["teachers_ids", "students_ids"]
    for name in ("death", "birth"):
        cols += [f"{name}_year", f"{name}_sd", f"{name}_kind"]
    return cols


def _reset(errors: Path) -> None:
    errors.parent.mkdir(parents=True, exist_ok=True)
    errors.unlink(missing_ok=True)


def _pages(cache_root, kind: str):
    d = Path(cache_root) / kind
    return sorted(d.glob("*.html")) if d.is_dir() else []


def _write(rows: list[dict], columns: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_parquet(path, index=False)


def build_rawi(cache_root, out="data/rawi.parquet", reset: bool = True) -> int:
    out = Path(out)
    errors = out.parent / "build_errors.csv"
    if reset:
        _reset(errors)
    rawi, ops, tuhfa = [], [], []
    n_err = 0
    for p in _pages(cache_root, "rawi"):
        try:
            r = parse_rawi(p.read_text(encoding="utf-8"))
        except _PARSE_ERRORS as e:
            out.parent.mkdir(parents=True, exist_ok=True)
            _log_error(errors, p, e)
            n_err += 1
            continue
        row = {k: v for k, v in dataclasses.asdict(r).items() if k not in _RAWI_DROP}
        row["teachers_ids"] = [t[0] for t in r.teachers]
        row["students_ids"] = [s[0] for s in r.students]
        for name, y in (("death", r.death), ("birth", r.birth)):
            row[f"{name}_year"], row[f"{name}_sd"], row[f"{name}_kind"] = y.year, y.sd, y.kind
        rawi.append(row)
        for o in r.opinions:
            ops.append({"rawi_id": r.rawi_id, "scholar": o.scholar, "scholar_id": o.scholar_id,
                        "scholar_death": o.scholar_death, "classification": o.classification,
                        "bucket": o.bucket, "statement": o.statement})
        tuhfa.extend({"rawi_id": r.rawi_id, "content": c} for c in r.tuhfa_entries)
    _write(rawi, _rawi_columns(), out)
    _write(ops, ["rawi_id", "scholar", "scholar_id", "scholar_death", "classification",
                 "bucket", "statement"], out.parent / "opinions.parquet")
    _write(tuhfa, ["rawi_id", "content"], out.parent / "tuhfa.parquet")
    print(f"rawi: {len(rawi)} rows, {n_err} errors")
    return len(rawi)


def build_hadith(cache_root, out_h="data/hadith.parquet", out_e="data/edges.parquet",
                 reset: bool = True) -> tuple[int, int]:
    out_h, out_e = Path(out_h), Path(out_e)
    errors = out_h.parent / "build_errors.csv"
    if reset:
        _reset(errors)
    hs, es = [], []
    n_err = 0
    for p in _pages(cache_root, "hadith"):
        try:
            rec = parse_hadith(p.read_text(encoding="utf-8"))
            ed = edges(rec)
        except _PARSE_ERRORS as e:
            out_h.parent.mkdir(parents=True, exist_ok=True)
            _log_error(errors, p, e)
            n_err += 1
            continue
        hs.append({"hadith_id": rec.hadith_id, "book_slug": rec.book_slug,
                   "book_title": rec.book_title, "number": rec.number,
                   "entry_kind": rec.entry_kind, "chain_type": rec.chain_type,
                   "n_links": len(rec.chain),
                   "grading_json": json.dumps(rec.grading, ensure_ascii=False)})
        es.extend(dataclasses.asdict(x) for x in ed)
    _write(hs, ["hadith_id", "book_slug", "book_title", "number", "entry_kind", "chain_type",
                "n_links", "grading_json"], out_h)
    _write(es, [f.name for f in dataclasses.fields(Edge)], out_e)
    print(f"hadith: {len(hs)} rows, {len(es)} edges, {n_err} errors")
    return len(hs), len(es)
