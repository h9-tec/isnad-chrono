"""Validation metrics and figures: do low p_meet scores flag known-bad pairs?"""
import json
import math
from pathlib import Path

import pandas as pd

from isnad.dates import Year
from isnad.score import _year, p_meet

THRESHOLDS = (0.05, 0.1, 0.2)
BOOKS = ("b-1", "b-2")
_NONE = Year(None, None, "none")


def _with_book(scores: pd.DataFrame, hadith: pd.DataFrame | None) -> pd.DataFrame:
    if "book_slug" in scores.columns or hadith is None:
        return scores
    h = hadith[["hadith_id", "book_slug"]].drop_duplicates("hadith_id")
    return scores.merge(h, on="hadith_id", how="left")


def positives(scores: pd.DataFrame, books=BOOKS, hadith: pd.DataFrame | None = None) -> pd.DataFrame:
    """Explicit-sama' edges of the given books (not mu'allaq, dated) plus confirmed pairs."""
    s = _with_book(scores, hadith)
    in_books = s["book_slug"].isin(books) if "book_slug" in s.columns else pd.Series(True, index=s.index)
    explicit = (in_books & s["explicit_term"].fillna(False).astype(bool)
                & (s["chain_type"] != "معلق") & (s["verdict"] != "no_dates"))
    return s[explicit | s["confirmed"].fillna(False).astype(bool)]


def negatives(denials: pd.DataFrame, rawi: pd.DataFrame) -> pd.DataFrame:
    """Resolved, unambiguous denial pairs with p_meet computed from rawi dates."""
    d = denials[denials["resolved"].fillna(False).astype(bool)
                & ~denials["ambiguous"].fillna(False).astype(bool)]
    d = d.dropna(subset=["student_id", "teacher_id"])
    recs = {int(r["rawi_id"]): r for r in rawi.to_dict("records")}
    out = []
    for r in d.to_dict("records"):
        t, s = recs.get(int(r["teacher_id"])), recs.get(int(r["student_id"]))
        p = None
        if t is not None and s is not None:
            p, _ = p_meet(_year(t, "death"), _year(s, "birth"), _year(s, "death"), _year(t, "birth"))
        out.append({"student_id": int(r["student_id"]), "teacher_id": int(r["teacher_id"]),
                    "relation": r.get("relation"), "p_meet": p})
    return pd.DataFrame(out, columns=["student_id", "teacher_id", "relation", "p_meet"])


def auroc(pos: pd.Series, neg: pd.Series) -> float:
    """P(score_pos > score_neg), ties counted half, via average ranks (Mann-Whitney U)."""
    pos, neg = pos.dropna(), neg.dropna()
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.concat([pos, neg], ignore_index=True).rank(method="average")
    u = ranks.iloc[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2
    return float(u / (len(pos) * len(neg)))


def _clean(v):
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return _clean(v.item())
    return v


def _flag_rates(p: pd.Series) -> dict:
    p = p.dropna()
    return {t: (float((p < t).mean()) if len(p) else None) for t in THRESHOLDS}


def metrics(scores, denials_by_class, rawi, hadith) -> dict:
    """denials_by_class: {class_name: denial DataFrame}."""
    s = _with_book(scores, hadith)
    pos = positives(s)
    out: dict = {"n_positives": int(len(pos))}
    for name, den in denials_by_class.items():
        neg = negatives(den, rawi)
        rates = _flag_rates(neg["p_meet"])
        out[name] = {"auroc": auroc(pos["p_meet"], neg["p_meet"]),
                     "n": int(neg["p_meet"].notna().sum()),
                     **{f"recall@{t}": rates[t] for t in THRESHOLDS}}
    pr = _flag_rates(pos["p_meet"])
    out["false_flag_rate"] = {f"@{t}": pr[t] for t in THRESHOLDS}
    if "book_slug" in s.columns:
        vc = s.groupby("book_slug")["verdict"].value_counts()
        by_book: dict = {}
        for (b, v), n in vc.items():
            by_book.setdefault(b, {})[v] = int(n)
    else:
        by_book = {}
    out["verdict_counts_by_book"] = by_book
    ids = pd.concat([s["teacher_id"], s["student_id"]]).dropna().astype(int).unique()
    r = rawi[rawi["rawi_id"].isin(ids)]
    out["coverage"] = {"how": {k: int(v) for k, v in s["how"].value_counts().items()},
                       "death_kind": {k: int(v) for k, v in r["death_kind"].value_counts().items()}}
    return _clean(out)


def figures(scores, denials_by_class, rawi, hadith, fig_dir) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    Path(fig_dir).mkdir(parents=True, exist_ok=True)
    s = _with_book(scores, hadith)
    pos = positives(s)["p_meet"].dropna()
    for name, den in denials_by_class.items():
        neg = negatives(den, rawi)["p_meet"].dropna()
        fig, ax = plt.subplots(figsize=(6, 4))
        bins = [i / 20 for i in range(21)]
        ax.hist(pos, bins=bins, alpha=0.6, density=True, label=f"positives (n={len(pos)})")
        ax.hist(neg, bins=bins, alpha=0.6, density=True, label=f"{name} (n={len(neg)})")
        ax.set_xlabel("p_meet")
        ax.set_ylabel("density")
        ax.legend()
        fig.tight_layout()
        fig.savefig(Path(fig_dir) / f"p_meet_{name}.png", dpi=150)
        plt.close(fig)
    if "book_slug" in s.columns:
        tab = s.groupby("book_slug")["verdict"].value_counts().unstack(fill_value=0)
        ax = tab.plot.bar(figsize=(7, 4))
        ax.set_ylabel("edges")
        ax.figure.tight_layout()
        ax.figure.savefig(Path(fig_dir) / "verdicts_by_book.png", dpi=150)
        plt.close(ax.figure)


def run_validate(scores_path, rawi_path, hadith_path, denial_paths: dict, out_path, fig_dir) -> dict:
    scores = pd.read_parquet(scores_path)
    rawi = pd.read_parquet(rawi_path)
    hadith = pd.read_parquet(hadith_path)
    den = {k: pd.read_parquet(v) for k, v in denial_paths.items()}
    m = metrics(scores, den, rawi, hadith)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(m, f, indent=2, ensure_ascii=False, allow_nan=False)
    if fig_dir:
        figures(scores, den, rawi, hadith, fig_dir)
    return m
