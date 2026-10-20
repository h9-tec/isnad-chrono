"""Human-readable outputs: weakest edges, database date errors, run summary."""

import pandas as pd

from isnad.score import adjusted_diff, date_conflict

WEAK = {"chronology_gap", "suspect"}
WEAK_COLS = ["teacher_id", "teacher_abbrev", "teacher_death", "student_id", "student_abbrev",
             "student_birth", "student_death", "p_meet", "term", "n_hadith",
             "example_hadith_ids", "verdict"]


def _labels(rawi: pd.DataFrame) -> pd.DataFrame:
    r = rawi.set_index("rawi_id")
    name = r["abbrev"].where(r["abbrev"].notna(), r["name"])
    return pd.DataFrame({"abbrev": name, "death": r["death_year"], "birth": r["birth_year"]})


def weak_edges(scores, rawi, hadith=None, n=50) -> pd.DataFrame:
    cols = WEAK_COLS + (["book_slugs"] if hadith is not None else [])
    s = scores[scores["verdict"].isin(WEAK)]
    if s.empty:
        return pd.DataFrame(columns=cols)
    if hadith is not None:
        s = s.merge(hadith[["hadith_id", "book_slug"]].drop_duplicates("hadith_id"),
                    on="hadith_id", how="left")
    lab = _labels(rawi)
    rows = []
    for (t, st), g in s.groupby(["teacher_id", "student_id"], sort=False):
        mode = g["term"].dropna().mode()
        row = {
            "teacher_id": t,
            "teacher_abbrev": lab["abbrev"].get(t),
            "teacher_death": lab["death"].get(t),
            "student_id": st,
            "student_abbrev": lab["abbrev"].get(st),
            "student_birth": lab["birth"].get(st),
            "student_death": lab["death"].get(st),
            "p_meet": g["p_meet"].iloc[0],
            "term": mode.iloc[0] if len(mode) else None,
            "n_hadith": g["hadith_id"].nunique(),
            "example_hadith_ids": "|".join(str(h) for h in g["hadith_id"].head(3)),
            "verdict": g["verdict"].iloc[0],
        }
        if hadith is not None:
            row["book_slugs"] = "|".join(sorted({str(b) for b in g["book_slug"].dropna()}))
        rows.append(row)
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("p_meet", kind="stable").head(n).reset_index(drop=True)


def date_errors(rawi) -> pd.DataFrame:
    cols = ["rawi_id", "abbrev", "death_year", "death_kind", "narrative_years", "diff"]
    rows = []
    for r in rawi.itertuples(index=False):
        ny = r.narrative_years
        if not date_conflict(r.death_year, ny):
            continue
        ny = list(ny)
        ab = r.abbrev if r.abbrev is not None and r.abbrev == r.abbrev else r.name
        rows.append({"rawi_id": r.rawi_id, "abbrev": ab, "death_year": r.death_year,
                     "death_kind": r.death_kind,
                     "narrative_years": "|".join(str(int(y)) for y in ny),
                     "diff": adjusted_diff(r.death_year, ny)})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("diff", ascending=False, kind="stable").reset_index(drop=True)


def _counts(series) -> dict:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).items()}


def _kv(d: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in d.items()) or "none"


def run_report(queue_counts, tables) -> str:
    out = ["# isnad-chrono run report", ""]
    if queue_counts is not None:
        out += ["## Fetch", "", _kv(queue_counts), ""]
    out += ["## Tables", ""] + [f"- {k}: {len(v)} rows" for k, v in tables.items()] + [""]
    scores, rawi = tables.get("scores"), tables.get("rawi")
    if scores is not None:
        out += ["## Coverage", "", f"- how: {_kv(_counts(scores['how']))}"]
        if rawi is not None:
            ids = set(scores["teacher_id"]) | set(scores["student_id"])
            sub = rawi[rawi["rawi_id"].isin(ids)]
            out.append(f"- death_kind (narrators in edges): {_kv(_counts(sub['death_kind']))}")
        out += ["", "## Verdicts", "", f"- overall: {_kv(_counts(scores['verdict']))}"]
        hadith = tables.get("hadith")
        if hadith is not None:
            m = scores.merge(hadith[["hadith_id", "book_slug"]].drop_duplicates("hadith_id"),
                             on="hadith_id", how="left")
            for b, g in m.groupby("book_slug", dropna=False):
                out.append(f"- {b}: {_kv(_counts(g['verdict']))}")
        out.append("")
    weak = tables.get("weak_edges")
    if weak is not None:
        out += ["## Top 10 weak edges", ""]
        for r in weak.head(10).itertuples(index=False):
            out.append(f"- {r.teacher_abbrev} -> {r.student_abbrev}: p_meet={r.p_meet:.3f}, "
                       f"{r.verdict}, n={r.n_hadith}, term={r.term}")
        out.append("")
    return "\n".join(out)


def run_report_files(scores_p, rawi_p, hadith_p, db, out_dir, n=50) -> str:
    scores, rawi, hadith = (pd.read_parquet(p) for p in (scores_p, rawi_p, hadith_p))
    weak = weak_edges(scores, rawi, hadith, n)
    errs = date_errors(rawi)
    weak.to_csv(f"{out_dir}/weak_edges.csv", index=False)
    errs.to_csv(f"{out_dir}/date_errors.csv", index=False)
    counts = None
    if db is not None:
        from isnad.fetch import Queue
        counts = Queue(db).counts()
    md = run_report(counts, {"scores": scores, "rawi": rawi, "hadith": hadith,
                             "weak_edges": weak, "date_errors": errs})
    with open(f"{out_dir}/run_report.md", "w") as f:
        f.write(md)
    return md
