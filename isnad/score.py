"""Chronology scoring: meeting probability, date conflicts, sama' evidence, verdicts."""
import math

import pandas as pd

from isnad.constants import (
    A0, AMBIGUOUS_TERMS, CONFLICT_YEARS, EXPLICIT_TERMS, GAP_THRESHOLD, MU_AGE, SD_AGE,
    SUSPECT_THRESHOLD,
)
from isnad.dates import Year, _norm

# Note: AGE_MIN/AGE_MAX (lifespan truncation bounds) are not applied; v1 uses the untruncated
# normal closed form.


def _strip(term) -> str | None:
    if term is None or (isinstance(term, float) and math.isnan(term)):
        return None
    t = " ".join(_norm(str(term)).split())
    return t or None


_EXPLICIT = {_strip(t) for t in EXPLICIT_TERMS}
_AMBIGUOUS = {_strip(t) for t in AMBIGUOUS_TERMS}


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _sd(y: Year) -> float:
    return y.sd if y.sd is not None else 1.0


def p_meet(t_death: Year, s_birth: Year, s_death: Year,
           t_birth: Year | None = None) -> tuple[float | None, str]:
    """P(student was >= A0 lunar years old before the teacher died)."""
    if t_death.year is not None:
        dt, sdt = t_death.year, _sd(t_death)
    elif t_birth is not None and t_birth.year is not None:
        dt, sdt = t_birth.year + MU_AGE, math.hypot(_sd(t_birth), SD_AGE)
    else:
        return None, "no_dates"
    if s_birth.year is not None:
        mu = dt - s_birth.year - A0
        sd = math.hypot(sdt, _sd(s_birth))
        how = "birth_known"
    elif s_death.year is not None:
        mu = dt - s_death.year + MU_AGE - A0
        sd = math.sqrt(sdt**2 + _sd(s_death)**2 + SD_AGE**2)
        how = "birth_imputed"
    else:
        return None, "no_dates"
    return _phi(mu / sd), how


def date_conflict(death_year, narrative_years) -> bool:
    if death_year is None or isinstance(death_year, float) and math.isnan(death_year):
        return False
    if narrative_years is None or len(narrative_years) == 0:
        return False
    return min(abs(death_year - y) for y in narrative_years) >= CONFLICT_YEARS


def _get(student, key, default):
    try:
        v = student[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def sama_evidence(term, teacher_id, student, denials) -> dict:
    t = _strip(term)
    explicit = t is not None and any(t == e or t.startswith(e + " ") for e in _EXPLICIT)
    ambiguous = (not explicit) and t in _AMBIGUOUS
    confirmed = [int(x) for x in _get(student, "sama_confirmed", [])]
    flags = [str(f) for f in _get(student, "flags", [])]
    sid = _get(student, "rawi_id", None)
    return {
        "confirmed": int(teacher_id) in confirmed,
        "explicit_term": explicit,
        "ambiguous_term": ambiguous,
        "denied": sid is not None and (int(sid), int(teacher_id)) in denials,
        "irsal": any("إرسال" in f for f in flags),
        "tadlis": any("تدليس" in f for f in flags),
    }


def verdict(p, conflict_t: bool, conflict_s: bool, ev: dict) -> str:
    """First match wins: data_error > denied_by_critic > no_dates > chronology_gap > suspect > ok."""
    if conflict_t or conflict_s:
        return "data_error"
    if ev["denied"]:
        return "denied_by_critic"
    if p is None:
        return "no_dates"
    if p < GAP_THRESHOLD:
        return "chronology_gap"
    if p < SUSPECT_THRESHOLD and ev["ambiguous_term"] and (ev["irsal"] or ev["tadlis"]):
        return "suspect"
    return "ok"


def _year(row, name) -> Year:
    def f(k):
        v = row.get(f"{name}_{k}")
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v
    return Year(f("year"), f("sd"), f("kind") or "none")


def _nar(v) -> list:
    return [] if v is None else list(v)


def score_edges(edges_path, rawi_path, denials: set, out_path=None) -> pd.DataFrame:
    edges = pd.read_parquet(edges_path)
    rawi = pd.read_parquet(rawi_path)
    recs = {int(r["rawi_id"]): r for r in rawi.to_dict("records")}
    none = Year(None, None, "none")
    cols = ["p_meet", "how", "conflict_t", "conflict_s", "confirmed", "explicit_term",
            "ambiguous_term", "denied", "irsal", "tadlis", "verdict"]

    rows = []
    keys = edges[["teacher_id", "student_id", "term"]].drop_duplicates()
    for t_id, s_id, term in keys.itertuples(index=False):
        t, s = recs.get(int(t_id)), recs.get(int(s_id))
        term = None if pd.isna(term) else term
        if t is None or s is None:
            # Narrator row absent from rawi.parquet: distinct from a present but undated row.
            p, how = None, "missing_rawi"
            ct = t is not None and date_conflict(_year(t, "death").year,
                                                 _nar(t.get("narrative_years")))
            cs = s is not None and date_conflict(_year(s, "death").year,
                                                 _nar(s.get("narrative_years")))
            ev = sama_evidence(term, t_id, s if s is not None else {"rawi_id": s_id}, denials)
        else:
            p, how = p_meet(_year(t, "death"), _year(s, "birth") if s else none,
                            _year(s, "death"), _year(t, "birth"))
            ct = date_conflict(_year(t, "death").year, _nar(t.get("narrative_years")))
            cs = date_conflict(_year(s, "death").year, _nar(s.get("narrative_years")))
            ev = sama_evidence(term, t_id, s, denials)
        rows.append({"teacher_id": t_id, "student_id": s_id, "term": term, "p_meet": p,
                     "how": how, "conflict_t": ct, "conflict_s": cs, **ev,
                     "verdict": verdict(p, ct, cs, ev)})
    sc = pd.DataFrame(rows, columns=["teacher_id", "student_id", "term"] + cols)
    e = edges.copy()
    e["_term"] = e["term"].where(e["term"].notna(), None)
    sc = sc.rename(columns={"term": "_term"})
    sc["_term"] = sc["_term"].astype(object)
    e["_term"] = e["_term"].astype(object)
    out = e.merge(sc, on=["teacher_id", "student_id", "_term"], how="left").drop(columns="_term")
    out["p_meet"] = out["p_meet"].astype("float64")
    if out_path is not None:
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(out_path, index=False)
    return out


def term_table(scores: pd.DataFrame, top: int = 20) -> dict:
    """Edge-row counts per term class, and the most frequent unclassified raw terms."""
    explicit = scores["explicit_term"].fillna(False).astype(bool)
    ambiguous = scores["ambiguous_term"].fillna(False).astype(bool)
    other = ~explicit & ~ambiguous
    vc = scores.loc[other, "term"].fillna("<none>").value_counts()
    ranked = sorted(vc.items(), key=lambda kv: (-kv[1], str(kv[0])))[:top]
    return {"explicit": int(explicit.sum()), "ambiguous": int(ambiguous.sum()),
            "unclassified": int(other.sum()),
            "top_unclassified": [(str(k), int(v)) for k, v in ranked]}


def format_term_table(t: dict) -> str:
    lines = ["term class (edge rows):",
             f"  explicit {t['explicit']}", f"  ambiguous {t['ambiguous']}",
             f"  unclassified {t['unclassified']}"]
    if t["top_unclassified"]:
        lines.append(f"top {len(t['top_unclassified'])} unclassified terms:")
        lines += [f"  {term}\t{n}" for term, n in t["top_unclassified"]]
    return "\n".join(lines)
