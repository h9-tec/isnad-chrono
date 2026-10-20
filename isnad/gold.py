"""Gold denial sets (al-Marasil pairs, Tuhfa entries) and Arabic name resolution."""

import json
import math
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from isnad.dates import _norm

DENY = {"no_sama", "mursal", "no_idrak"}
RELATIONS = DENY | {"sama"}
ACCEPT = 0.6
_PROMPT = Path(__file__).resolve().parent.parent / "gold" / "tuhfa_prompt.txt"
_DROP = {"بن", "عن"}
# Kunya/nasab particles are kept as tokens: "عمر" and "ابن عمر" are different people.
# They never count as name overlap on their own (see _score).
_PARTICLES = frozenset({"ابن", "ابو", "ام"})
# Quote markers of a hadith-specific statement ("did not hear THIS hadith from him").
# Each marker is whole-word bounded but may carry one proclitic (و ف ب ل ك): "وهذا الحديث"
# and "والحديث الذي" match, while "الحديث عنه في" and "حديث الزهري فيه" stay pair-level.
_SPECIFIC = re.compile("|".join(rf"(?<!\w)[وفبلك]?(?:{_norm(x)})(?!\w)" for x in (
    # "حديث <1-3 words> في": a named hadith ("حديث خزيمه بن ثابت في المسح"); "حديثه عن X"
    # (his hadith from X in general) has no space after حديث and stays pair-level.
    "هذا الحديث", "هذه الاحاديث", r"حديث(?: [^ ]+){1,3} في", "حديثه هذا", "هذا الخبر",
    "في هذا الحديث", "الحديث الذي")))
MAX_CANDS = 25
CHRONO_SLACK = 5  # teacher may die at most this many years after the student
PRIOR_W = 0.1
PRIOR_MARGIN = 0.05
# Relation step only considers candidates within this much of their side's best name
# score; without it a weak homonym that happens to be linked beats the right narrator.
REL_BAND = 0.1
_EPS = 1e-9


def tokens(s) -> list[str]:
    if not s:
        return []
    s = re.sub(r"\b(ابي|ابا|ابو)\b", "ابو", _norm(str(s)))
    return [t for t in re.findall(r"[\w]+", s) if t not in _DROP]


@dataclass
class Resolution:
    rawi_id: int | None
    score: float
    ambiguous: bool
    candidates: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Candidate:
    rawi_id: int
    score: float


@dataclass(frozen=True)
class Facts:
    """Per-narrator facts used to disambiguate a (student, teacher) pair."""
    teachers: frozenset[int] = frozenset()
    students: frozenset[int] = frozenset()
    death: float | None = None
    count: int = 0


@dataclass
class PairResolution:
    student_id: int | None
    teacher_id: int | None
    method: str  # relation | prior | ambiguous | none
    ambiguous: bool
    s_candidates: list[Candidate] = field(default_factory=list)
    t_candidates: list[Candidate] = field(default_factory=list)


def _ids(v) -> frozenset[int]:
    return frozenset(int(x) for x in v) if v is not None else frozenset()


def _num(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return None
    return float(v)


def facts_from_frame(df: pd.DataFrame) -> dict[int, Facts]:
    n = len(df)
    col = lambda c: df[c].tolist() if c in df else [None] * n  # noqa: E731
    out = {}
    for rid, t, s, d, c in zip(df["rawi_id"], col("teachers_ids"), col("students_ids"),
                               col("death_year"), col("count")):
        c = _num(c)
        out[int(rid)] = Facts(_ids(t), _ids(s), _num(d), int(c) if c else 0)
    return out


def _head(t: list[str]) -> list[str]:
    """First token, or particle + following token ("ابو هريره")."""
    return t[:2] if t[0] in _PARTICLES else t[:1]


def _score(q: list[str], c: list[str]) -> float:
    if not q or not c:
        return 0.0
    if q[0] in _PARTICLES and c[0] != q[0]:
        return 0.0  # kunya/ibn query only matches forms led by the same particle
    qs, cs = set(q) - _PARTICLES, set(c) - _PARTICLES
    if not qs or not cs:
        return 0.0
    overlap = len(qs & cs)
    extra = len(cs - qs)
    s = overlap / len(qs) - 0.15 * extra / len(cs)
    if _head(q) == _head(c):
        s += 0.3
    return s


class NameIndex:
    def __init__(self):
        self.forms: dict[int, list[list[str]]] = defaultdict(list)
        self.inv: dict[str, set[int]] = defaultdict(set)
        self.facts: dict[int, Facts] = {}

    def add(self, rawi_id: int, name) -> None:
        t = tokens(name)
        if not t or t in self.forms[rawi_id]:
            return
        self.forms[rawi_id].append(t)
        for tok in set(t):
            self.inv[tok].add(rawi_id)

    @classmethod
    def from_rawi(cls, path) -> "NameIndex":
        df = pd.read_parquet(path)
        idx = cls()
        for r in df.itertuples():
            rid = int(r.rawi_id)
            idx.add(rid, r.name)
            idx.add(rid, getattr(r, "abbrev", None))
            for f in getattr(r, "name_forms", None) if getattr(r, "name_forms", None) is not None else []:
                idx.add(rid, f)
        idx.facts = facts_from_frame(df)
        return idx

    def _scored(self, name) -> list[tuple[float, int]]:
        q = tokens(name)
        keys = set(q) - _PARTICLES  # particles alone can never reach ACCEPT
        cands = set().union(*(self.inv.get(t, set()) for t in keys)) if keys else set()
        return sorted(
            ((max(_score(q, f) for f in self.forms[c]), c) for c in cands),
            key=lambda x: (-x[0], x[1]),
        )

    def candidates(self, name, limit: int = MAX_CANDS) -> list[Candidate]:
        """All candidates scoring >= ACCEPT, best first (ties by rawi_id)."""
        return [Candidate(c, s) for s, c in self._scored(name) if s >= ACCEPT][:limit]

    def resolve(self, name: str) -> Resolution:
        scored = self._scored(name)
        if not scored or scored[0][0] < ACCEPT:
            return Resolution(None, scored[0][0] if scored else 0.0, False, [])
        top = scored[0][0]
        tied = [c for s, c in scored if abs(s - top) < 1e-9]
        if len(tied) > 1:
            return Resolution(None, top, True, tied)
        return Resolution(scored[0][1], top, False, [scored[0][1]])


def _pick(scored: list[tuple[tuple, int, int]]) -> tuple[int, int] | None:
    """Unique best (s, t) by key, or None on a tie."""
    scored = sorted(scored, key=lambda x: x[0], reverse=True)
    if len(scored) > 1 and all(abs(a - b) < _EPS for a, b in zip(scored[0][0], scored[1][0])):
        return None
    return scored[0][1], scored[0][2]


def resolve_pair(index: NameIndex, student_name, teacher_name, rawi=None,
                 student_id: int | None = None) -> PairResolution:
    """Jointly resolve a (student, teacher) pair of names.

    Order: candidates (score >= ACCEPT) -> recorded teacher/student relation ->
    chronology filter + narration-count prior -> ambiguous. With `student_id`
    the student side is fixed and only the teacher is resolved.
    """
    facts = rawi if isinstance(rawi, dict) else (
        facts_from_frame(rawi) if rawi is not None else index.facts)
    S = [Candidate(int(student_id), 1.0)] if student_id is not None else \
        index.candidates(student_name)
    T = index.candidates(teacher_name)
    if not S or not T:
        return PairResolution(None, None, "none", False, S, T)
    f = lambda i: facts.get(i, Facts())  # noqa: E731
    pairs = [(s, t) for s in S for t in T if s.rawi_id != t.rawi_id]

    s_top, t_top = S[0].score - REL_BAND - _EPS, T[0].score - REL_BAND - _EPS
    related = [(s, t) for s, t in pairs if s.score >= s_top and t.score >= t_top and (
               t.rawi_id in f(s.rawi_id).teachers or s.rawi_id in f(t.rawi_id).students)]
    if related:
        best = _pick([((s.score + t.score, f(s.rawi_id).count + f(t.rawi_id).count),
                       s.rawi_id, t.rawi_id) for s, t in related])
        if best is None:
            return PairResolution(None, None, "ambiguous", True, S, T)
        return PairResolution(*best, "relation", False, S, T)

    def plausible(s, t):
        ds, dt = f(s.rawi_id).death, f(t.rawi_id).death
        return ds is None or dt is None or dt <= ds + CHRONO_SLACK

    prior = sorted(((s.score + t.score + PRIOR_W * math.log10(1 + f(s.rawi_id).count)
                     + PRIOR_W * math.log10(1 + f(t.rawi_id).count), s.rawi_id, t.rawi_id)
                    for s, t in pairs if plausible(s, t)), reverse=True)
    if not prior:
        return PairResolution(None, None, "none", False, S, T)
    if len(prior) > 1 and prior[0][0] - prior[1][0] < PRIOR_MARGIN - _EPS:
        return PairResolution(None, None, "ambiguous", True, S, T)
    return PairResolution(prior[0][1], prior[0][2], "prior", False, S, T)


def _opt_int(ids) -> pd.Series:
    return pd.Series(ids, dtype="Int64")


def relation_scope(quote) -> str:
    """"specific" when the quote limits the statement to one hadith, else "pair"."""
    if not isinstance(quote, str) or not quote:
        return "pair"
    q = " ".join(re.findall(r"[\w]+", _norm(quote)))
    return "specific" if _SPECIFIC.search(q) else "pair"


def recheck(index: NameIndex, frame: pd.DataFrame) -> pd.DataFrame:
    """Re-resolve a denial frame's names and recompute its scope.

    With a `student` column both names are resolved jointly (al-Marasil); otherwise
    `student_id` is fixed and only `teacher` is resolved (Tuhfa).
    """
    out = frame.copy()
    by_name = "student" in out
    if by_name:
        res = [resolve_pair(index, s, t) for s, t in zip(out["student"], out["teacher"])]
        out["student_id"] = _opt_int([r.student_id for r in res])
    else:
        res = [resolve_pair(index, None, t, student_id=int(sid))
               for sid, t in zip(out["student_id"], out["teacher"])]
        out["student_id"] = out["student_id"].astype("Int64")
    out["teacher_id"] = _opt_int([r.teacher_id for r in res])
    out["resolved"] = out["student_id"].notna() & out["teacher_id"].notna()
    out["ambiguous"] = [r.ambiguous for r in res]
    out["method"] = [r.method for r in res]
    quotes = out["quote"] if "quote" in out else [None] * len(out)
    out["relation_scope"] = [relation_scope(q) for q in quotes]
    return out


def marasil_denials(index: NameIndex, path="gold/marasil_pairs.json") -> pd.DataFrame:
    rows = [r for r in json.loads(Path(path).read_text(encoding="utf-8"))
            if "النبي" not in r["teacher"]]
    out = pd.DataFrame(rows)
    cols = ["student", "teacher", "student_id", "teacher_id", "relation", "authority",
            "resolved", "ambiguous", "method", "relation_scope"]
    if out.empty:
        return pd.DataFrame(columns=cols)
    return recheck(index, out)[cols]


def claude_p(prompt: str) -> str:
    r = subprocess.run(["claude", "-p", "--model", "sonnet", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr[:500]}")
    return r.stdout


def parse_lines(text: str) -> tuple[list[dict], int]:
    good, bad = [], 0
    for line in text.splitlines():
        line = line.strip().strip("`,")
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            if (isinstance(d, dict) and d.get("relation") in RELATIONS
                    and d.get("teacher") and d.get("student_id") is not None):
                d["student_id"] = int(d["student_id"])
                good.append(d)
            else:
                bad += 1
        except (ValueError, TypeError):
            bad += 1
    return good, bad


TUHFA_COLS = ["student_id", "teacher", "teacher_id", "relation", "quote", "resolved",
              "ambiguous", "method", "relation_scope"]


def tuhfa_denials(tuhfa_path, index: NameIndex, runner=claude_p, batch_size=40,
                  prompt_path=_PROMPT) -> pd.DataFrame:
    tf = pd.read_parquet(tuhfa_path)
    template = Path(prompt_path).read_text(encoding="utf-8")
    valid = {int(i) for i in tf["rawi_id"]}
    entries = [(int(r.rawi_id), r.content) for r in tf.itertuples() if r.content]
    recs, bad = [], 0
    for i in range(0, len(entries), batch_size):
        chunk = entries[i:i + batch_size]
        prompt = template + "\n\n".join(f"### {rid}\n{txt}" for rid, txt in chunk)
        good, b = parse_lines(runner(prompt))
        bad += b
        recs += [g for g in good if g["student_id"] in valid]
    if bad:
        print(f"tuhfa: skipped {bad} unparseable lines")
    if not recs:
        return pd.DataFrame(columns=TUHFA_COLS)
    df = pd.DataFrame(recs)
    if "quote" not in df:
        df["quote"] = ""
    return recheck(index, df)[TUHFA_COLS]


def tuhfa_denials_from_frame(frame, index: NameIndex) -> pd.DataFrame:
    """Re-resolve an existing Tuhfa denial frame (path or DataFrame) without the LLM."""
    df = pd.read_parquet(frame) if not isinstance(frame, pd.DataFrame) else frame
    if df.empty:
        return pd.DataFrame(columns=TUHFA_COLS)
    df = df[["student_id", "teacher", "relation"] + (["quote"] if "quote" in df else [])]
    if "quote" not in df:
        df = df.assign(quote="")
    return recheck(index, df)[TUHFA_COLS]


def _valid(df: pd.DataFrame) -> pd.DataFrame:
    pair = df["relation_scope"] == "pair" if "relation_scope" in df else True
    return df[df["resolved"] & ~df["ambiguous"] & df["relation"].isin(DENY) & pair
              & df["student_id"].notna() & df["teacher_id"].notna()]


def denial_set(dfs) -> set[tuple[int, int]]:
    out = set()
    for df in dfs:
        if df is None or len(df) == 0:
            continue
        m = _valid(df)
        out |= {(int(a), int(b)) for a, b in zip(m["student_id"], m["teacher_id"])}
    return out


def method_breakdown(df: pd.DataFrame) -> dict[str, int]:
    vc = df["method"].value_counts() if "method" in df else pd.Series(dtype=int)
    return {m: int(vc.get(m, 0)) for m in ("relation", "prior", "ambiguous", "none")}


def run_gold(rawi, tuhfa, marasil, out_dir, runner=claude_p, tuhfa_frame=None) -> None:
    """Build the gold denial files. With `tuhfa_frame` (an existing denials_tuhfa
    parquet) Tuhfa rows are re-resolved from it and the LLM runner is not used."""
    idx = NameIndex.from_rawi(rawi)
    m = marasil_denials(idx, marasil)
    t = (tuhfa_denials_from_frame(tuhfa_frame, idx) if tuhfa_frame is not None
         else tuhfa_denials(tuhfa, idx, runner))
    out = Path(out_dir)
    m.to_parquet(out / "denials_marasil.parquet")
    t.to_parquet(out / "denials_tuhfa.parquet")
    parts = []
    for name, df in (("marasil", m), ("tuhfa", t)):
        print(name, "resolved", int((df["resolved"] & ~df["ambiguous"]).sum()),
              "ambiguous", int(df["ambiguous"].sum()),
              "unresolved", int((~df["resolved"] & ~df["ambiguous"]).sum()))
        print(f"  {name} methods", method_breakdown(df))
        vc = df["relation_scope"].value_counts() if "relation_scope" in df else {}
        print(f"  {name} scope", {k: int(vc.get(k, 0)) for k in ("pair", "specific")})
        if len(df):
            v = _valid(df)[["student_id", "teacher_id", "relation"]].copy()
            v["source"] = name
            parts.append(v)
    cols = ["student_id", "teacher_id", "relation", "source"]
    u = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
    u["student_id"] = u["student_id"].astype("int64")
    u["teacher_id"] = u["teacher_id"].astype("int64")
    u[cols].to_parquet(out / "denials.parquet")
