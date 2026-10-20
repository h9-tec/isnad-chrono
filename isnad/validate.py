"""Validation metrics and figures: do low p_meet scores flag known-bad pairs?"""
import json
import math
from pathlib import Path

import pandas as pd

from isnad.constants import GAP_THRESHOLD, SUSPECT_THRESHOLD
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


NEG_RELATIONS = ("no_idrak", "mursal", "no_sama")
TEXT_FLAGGED = {"denied_by_critic", "chronology_gap", "suspect"}
_NEG_COLS = ["student_id", "teacher_id", "relation", "p_meet"]


def negatives(denials: pd.DataFrame, rawi: pd.DataFrame, relation: str | None = None) -> pd.DataFrame:
    """Resolved, unambiguous pairs (one row per student, teacher, relation) with p_meet.

    `relation` selects one relation; None keeps every denial relation. `sama` rows are never
    negatives: they are attestations of hearing (see `sama_attested`). With a
    `relation_scope` column only "pair" rows count; hadith-specific rows are dropped.
    """
    if denials is None or len(denials) == 0:
        return pd.DataFrame(columns=_NEG_COLS)
    keep = {relation} if relation is not None else set(NEG_RELATIONS)
    d = denials[denials["relation"].isin(keep)]
    if "relation_scope" in d:  # hadith-specific statements are not pair-level denials
        d = d[d["relation_scope"] == "pair"]
    return _pairs(d, rawi)


def sama_attested(denials: pd.DataFrame, rawi: pd.DataFrame) -> pd.DataFrame:
    if denials is None or len(denials) == 0:
        return pd.DataFrame(columns=_NEG_COLS)
    return _pairs(denials[denials["relation"] == "sama"], rawi)


def _pairs(d: pd.DataFrame, rawi: pd.DataFrame) -> pd.DataFrame:
    d = d[d["resolved"].fillna(False).astype(bool) & ~d["ambiguous"].fillna(False).astype(bool)]
    d = d.dropna(subset=["student_id", "teacher_id"])
    recs = {int(r["rawi_id"]): r for r in rawi.to_dict("records")}
    out, seen = [], set()
    for r in d.to_dict("records"):
        key = (int(r["student_id"]), int(r["teacher_id"]), r.get("relation"))
        if key in seen:
            continue
        seen.add(key)
        t, s = recs.get(key[1]), recs.get(key[0])
        p = None
        if t is not None and s is not None:
            p, _ = p_meet(_year(t, "death"), _year(s, "birth"), _year(s, "death"), _year(t, "birth"))
        out.append({"student_id": key[0], "teacher_id": key[1], "relation": key[2], "p_meet": p})
    df = pd.DataFrame(out, columns=_NEG_COLS)
    df["p_meet"] = df["p_meet"].astype("float64")
    return df


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


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return df[col].fillna(False).astype(bool)


def _pair_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (teacher, student); p_meet depends only on the pair."""
    return df.drop_duplicates(["teacher_id", "student_id"])


def _irsal_ids(rawi: pd.DataFrame) -> set[int]:
    if "flags" not in rawi.columns:
        return set()
    return {int(i) for i, f in zip(rawi["rawi_id"], rawi["flags"])
            if f is not None and not isinstance(f, float) and any("إرسال" in str(x) for x in f)}


def _text_flags(s: pd.DataFrame) -> pd.DataFrame:
    """Per (teacher, student) pair in the corpus: flagged by the full verdict (chronology +
    text + critic denial), and flagged ignoring the denial (chronology + text only)."""
    if s.empty:
        return pd.DataFrame(columns=["teacher_id", "student_id", "text", "text_no_denial"])
    p = s["p_meet"]
    no_denial = ~(_bool(s, "conflict_t") | _bool(s, "conflict_s")) & (
        (p < GAP_THRESHOLD)
        | ((p < SUSPECT_THRESHOLD) & _bool(s, "ambiguous_term")
           & (_bool(s, "irsal") | _bool(s, "tadlis"))))
    f = pd.DataFrame({"teacher_id": s["teacher_id"].astype("int64"),
                      "student_id": s["student_id"].astype("int64"),
                      "text": s["verdict"].isin(TEXT_FLAGGED), "text_no_denial": no_denial})
    # A pair counts as flagged if any of its edge rows is flagged.
    return f.groupby(["teacher_id", "student_id"], as_index=False)[["text", "text_no_denial"]].any()


def _neg_metrics(neg: pd.DataFrame, pos: pd.DataFrame, pos_pairs: pd.DataFrame,
                 flags: pd.DataFrame, irsal: set[int]) -> dict:
    rates = _flag_rates(neg["p_meet"])
    out = {"auroc": auroc(pos["p_meet"], neg["p_meet"]),
           "auroc_pairs": auroc(pos_pairs["p_meet"], neg["p_meet"]),
           "n": int(neg["p_meet"].notna().sum()),
           "n_pairs_total": int(len(neg)),
           **{f"recall@{t}": rates[t] for t in THRESHOLDS}}
    inc = neg.merge(flags, on=["teacher_id", "student_id"], how="inner")
    out["n_in_corpus"] = int(len(inc))
    cr = _flag_rates(inc["p_meet"])
    out.update({f"chron_recall_in_corpus@{t}": cr[t] for t in THRESHOLDS})
    out["text_recall_in_corpus"] = float(inc["text"].mean()) if len(inc) else None
    out["text_recall_in_corpus_excl_denial"] = (float(inc["text_no_denial"].mean())
                                                if len(inc) else None)
    students = neg["student_id"].astype(int).unique()
    out["student_irsal_frac"] = (float(sum(int(x) in irsal for x in students) / len(students))
                                 if len(students) else None)
    return out


def metrics(scores, denials_by_class, rawi, hadith) -> dict:
    """denials_by_class: {source_name: denial DataFrame with a `relation` column}.

    Negatives are reported per (source, relation) for relation in NEG_RELATIONS; `sama` rows
    are reported as the extra positive class `sama_attested`, never as negatives.
    """
    s = _with_book(scores, hadith)
    pos = positives(s)
    pos_pairs = _pair_dedup(pos)
    out: dict = {"n_positives": int(len(pos)),
                 "n_positives_scored": int(pos["p_meet"].notna().sum())}
    pr, pp = _flag_rates(pos["p_meet"]), _flag_rates(pos_pairs["p_meet"])
    out["false_flag_rate"] = {f"@{t}": pr[t] for t in THRESHOLDS}
    out["positives"] = {"n_rows": int(len(pos)),
                        "n_rows_scored": int(pos["p_meet"].notna().sum()),
                        "n_pairs": int(len(pos_pairs)),
                        "n_pairs_scored": int(pos_pairs["p_meet"].notna().sum()),
                        "false_flag_rate_pairs": {f"@{t}": pp[t] for t in THRESHOLDS}}
    flags = _text_flags(s)
    irsal = _irsal_ids(rawi)
    out["negatives"] = {}
    out["sama_attested"] = {}
    for source, den in denials_by_class.items():
        out["negatives"][source] = {
            rel: _neg_metrics(negatives(den, rawi, rel), pos, pos_pairs, flags, irsal)
            for rel in NEG_RELATIONS}
        sa = sama_attested(den, rawi)
        sr = _flag_rates(sa["p_meet"])
        out["sama_attested"][source] = {"n": int(sa["p_meet"].notna().sum()),
                                        "n_pairs_total": int(len(sa)),
                                        "false_flag_rate": {f"@{t}": sr[t] for t in THRESHOLDS}}
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
    for source, den in denials_by_class.items():
        for rel in NEG_RELATIONS:
            neg = negatives(den, rawi, rel)["p_meet"].dropna()
            fig, ax = plt.subplots(figsize=(6, 4))
            bins = [i / 20 for i in range(21)]
            if len(pos):  # density of an empty sample is 0/0
                ax.hist(pos, bins=bins, alpha=0.6, density=True,
                        label=f"positives (n={len(pos)})")
            if len(neg):
                ax.hist(neg, bins=bins, alpha=0.6, density=True,
                        label=f"{source} {rel} (n={len(neg)})")
            ax.set_xlabel("p_meet")
            ax.set_ylabel("density")
            if len(pos) or len(neg):
                ax.legend()
            fig.tight_layout()
            fig.savefig(Path(fig_dir) / f"p_meet_{source}_{rel}.png", dpi=150)
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
