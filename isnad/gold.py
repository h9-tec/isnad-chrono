"""Gold denial sets (al-Marasil pairs, Tuhfa entries) and Arabic name resolution."""

import json
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
_DROP = {"بن", "ابو", "عن"}


def tokens(s) -> list[str]:
    if not s:
        return []
    s = _norm(str(s))
    s = re.sub(r"\bابن\b", "بن", s)
    s = re.sub(r"\b(ابي|ابو)\b", "ابو", s)
    return [t for t in re.findall(r"[\w]+", s) if t not in _DROP]


@dataclass
class Resolution:
    rawi_id: int | None
    score: float
    ambiguous: bool
    candidates: list[int] = field(default_factory=list)


def _score(q: list[str], c: list[str]) -> float:
    if not q or not c:
        return 0.0
    qs, cs = set(q), set(c)
    overlap = len(qs & cs)
    extra = len(cs - qs)
    s = overlap / len(qs) - 0.15 * extra / len(cs)
    if q[0] == c[0]:
        s += 0.3
    return s


class NameIndex:
    def __init__(self):
        self.forms: dict[int, list[list[str]]] = defaultdict(list)
        self.inv: dict[str, set[int]] = defaultdict(set)

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
        return idx

    def resolve(self, name: str) -> Resolution:
        q = tokens(name)
        cands = set().union(*(self.inv.get(t, set()) for t in set(q))) if q else set()
        scored = sorted(
            ((max(_score(q, f) for f in self.forms[c]), c) for c in cands),
            key=lambda x: (-x[0], x[1]),
        )
        if not scored or scored[0][0] < ACCEPT:
            return Resolution(None, scored[0][0] if scored else 0.0, False, [])
        top = scored[0][0]
        tied = [c for s, c in scored if abs(s - top) < 1e-9]
        if len(tied) > 1:
            return Resolution(None, top, True, tied)
        return Resolution(scored[0][1], top, False, [scored[0][1]])


def _resolve_col(index: NameIndex, names) -> tuple[list, list]:
    ids, amb = [], []
    for n in names:
        r = index.resolve(n)
        ids.append(r.rawi_id)
        amb.append(r.ambiguous)
    return ids, amb


def _opt_int(ids) -> pd.Series:
    return pd.Series(ids, dtype="Int64")


def marasil_denials(index: NameIndex, path="gold/marasil_pairs.json") -> pd.DataFrame:
    rows = [r for r in json.loads(Path(path).read_text(encoding="utf-8"))
            if "النبي" not in r["teacher"]]
    out = pd.DataFrame(rows)
    cols = ["student", "teacher", "student_id", "teacher_id", "relation", "authority",
            "resolved", "ambiguous"]
    if out.empty:
        return pd.DataFrame(columns=cols)
    sid, samb = _resolve_col(index, out["student"])
    tid, tamb = _resolve_col(index, out["teacher"])
    out["student_id"], out["teacher_id"] = _opt_int(sid), _opt_int(tid)
    out["resolved"] = out["student_id"].notna() & out["teacher_id"].notna()
    out["ambiguous"] = [a or b for a, b in zip(samb, tamb)]
    return out[cols]


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
    cols = ["student_id", "teacher", "teacher_id", "relation", "quote", "resolved", "ambiguous"]
    if not recs:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(recs)
    if "quote" not in df:
        df["quote"] = ""
    tid, amb = _resolve_col(index, df["teacher"])
    df["teacher_id"] = _opt_int(tid)
    df["resolved"] = df["teacher_id"].notna()
    df["ambiguous"] = amb
    df["student_id"] = df["student_id"].astype("Int64")
    return df[cols]


def denial_set(dfs) -> set[tuple[int, int]]:
    out = set()
    for df in dfs:
        if df is None or len(df) == 0:
            continue
        m = df[df["resolved"] & ~df["ambiguous"] & df["relation"].isin(DENY)
               & df["student_id"].notna() & df["teacher_id"].notna()]
        out |= {(int(a), int(b)) for a, b in zip(m["student_id"], m["teacher_id"])}
    return out


def run_gold(rawi, tuhfa, marasil, out_dir, runner=claude_p) -> None:
    idx = NameIndex.from_rawi(rawi)
    m = marasil_denials(idx, marasil)
    t = tuhfa_denials(tuhfa, idx, runner)
    out = Path(out_dir)
    m.to_parquet(out / "denials_marasil.parquet")
    t.to_parquet(out / "denials_tuhfa.parquet")
    parts = []
    for name, df in (("marasil", m), ("tuhfa", t)):
        d = df[["student_id", "teacher_id", "relation", "resolved", "ambiguous"]].copy()
        d["source"] = name
        parts.append(d)
        print(name, "resolved", int((df["resolved"] & ~df["ambiguous"]).sum()),
              "ambiguous", int(df["ambiguous"].sum()),
              "unresolved", int((~df["resolved"] & ~df["ambiguous"]).sum()))
    pd.concat(parts, ignore_index=True).to_parquet(out / "denials.parquet")
