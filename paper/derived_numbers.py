"""Numbers quoted in paper/draft.md that are not stored in data/metrics.json.

Read-only over data/ and gold/. Run: .venv/bin/python paper/derived_numbers.py
"""
import json

import pandas as pd

from isnad.score import classify_term

D = "data/"

# 1. Gold sets
pairs = json.load(open("gold/marasil_pairs.json", encoding="utf-8"))
print("marasil_pairs.json rows", len(pairs))
for name in ("marasil", "tuhfa"):
    df = pd.read_parquet(f"{D}denials_{name}.parquet")
    ok = df["resolved"] & ~df["ambiguous"]
    print(name, "rows", len(df), "resolved", int(ok.sum()), "ambiguous", int(df["ambiguous"].sum()),
          "unresolved", int((~df["resolved"] & ~df["ambiguous"]).sum()))
    print("  method", df["method"].value_counts().to_dict())
    print("  scope", df["relation_scope"].value_counts().to_dict())
    print("  relation (resolved)", df[ok]["relation"].value_counts().to_dict())
den = pd.read_parquet(f"{D}denials.parquet")
print("denials.parquet rows", len(den), "unique pairs",
      len(den.drop_duplicates(["student_id", "teacher_id"])))
print("  by source/relation", den.groupby(["source", "relation"]).size().to_dict())
tf = pd.read_parquet(f"{D}tuhfa.parquet")
print("tuhfa entries", len(tf))

# 2. Sound-chain controls: (student, teacher) pairs that no critic denies
CONTROLS = [("Malik <- Nafi'", 5361, 6509), ("Nafi' <- Ibn Umar", 6509, 3807),
            ("al-Zuhri <- Salim", 5917, 2249), ("Salim <- Ibn Umar", 2249, 3807),
            ("Hisham <- Urwa", 6702, 4361), ("Urwa <- Aisha", 4361, 3026)]
s = pd.read_parquet(f"{D}edge_scores.parquet")
dset = {(int(a), int(b)) for a, b in zip(den.student_id, den.teacher_id)}
for label, st, te in CONTROLS:
    e = s[(s.student_id == st) & (s.teacher_id == te)]
    print("control", label, "rows", len(e), "in_denials", (st, te) in dset,
          "p_meet", round(float(e.p_meet.iloc[0]), 4) if len(e) else None,
          "verdicts", e.verdict.value_counts().to_dict())

# 3. Date-conflict audit
de = pd.read_csv(f"{D}date_errors.csv")
ys = lambda v: [float(x) for x in str(v).split("|") if x not in ("", "nan")]  # noqa: E731
de["mod100"] = [any(y == dy % 100 for y in ys(v)) for dy, v in zip(de.death_year, de.narrative_years)]
de["small"] = [all(y < 10 for y in ys(v)) for v in de.narrative_years]
print("date_errors rows", len(de), "diff==200", int((de["diff"] == 200).sum()),
      "diff==100", int((de["diff"] == 100).sum()), "diff==300", int((de["diff"] == 300).sum()),
      "diff multiple of 100", int((de["diff"] % 100 == 0).sum()))
print("narrative year == structured year mod 100", int(de.mod100.sum()))
print("rest with only single-digit narrative years", int((~de.mod100 & de.small).sum()))
print("rest, other", int((~de.mod100 & ~de.small).sum()))
print("diff 20-99", int(((de["diff"] >= 20) & (de["diff"] < 100)).sum()))
mod_ids = set(de[de.mod100].rawi_id)
err = s[s.verdict == "data_error"]
conf = set(err.teacher_id[err.conflict_t.astype(bool)]) | set(err.student_id[err.conflict_s.astype(bool)])
print("six-book data_error rows", len(err), "distinct conflicted narrators", len(conf),
      "of which mod100", len(conf & mod_ids))
only = [((not ct) or t in mod_ids) and ((not cs) or st in mod_ids)
        for t, st, ct, cs in zip(err.teacher_id, err.student_id, err.conflict_t, err.conflict_s)]
print("data_error rows explained only by mod100 narrators", int(sum(only)))
r = pd.read_parquet(f"{D}rawi.parquet")
print("narrators birth_year > death_year", int((r.birth_year > r.death_year).sum()))

# 4. Weak edges
w = pd.read_csv(f"{D}weak_edges.csv")
w["cls"] = [classify_term(t) for t in w.term]
print("weak_edges", len(w), "classes", w.cls.value_counts().to_dict(),
      "hadith rows covered", int(w.n_hadith.sum()))
print("  students (top)", w.student_abbrev.value_counts().head(5).to_dict())
print("  student birth >= student death", int((w.student_birth >= w.student_death).sum()))
gap = s[s.verdict == "chronology_gap"]
print("chronology_gap rows", len(gap), "unique pairs", len(gap.drop_duplicates(["teacher_id", "student_id"])),
      "explicit-term rows", int(gap.explicit_term.astype(bool).sum()))

# 5. Lift of textual evidence over chronology alone (from metrics.json)
m = json.load(open(f"{D}metrics.json"))
for src, rels in m["negatives"].items():
    for rel, v in rels.items():
        print("lift", src, rel, "chron@0.05", round(v["chron_recall_in_corpus@0.05"], 3),
              "chron@0.2", round(v["chron_recall_in_corpus@0.2"], 3),
              "text_excl", round(v["text_recall_in_corpus_excl_denial"], 3),
              "lift_vs_0.05", round(v["text_recall_in_corpus_excl_denial"] - v["chron_recall_in_corpus@0.05"], 3))
tot = {k: sum(b.get(k, 0) for b in m["verdict_counts_by_book"].values())
       for k in ("ok", "no_dates", "denied_by_critic", "data_error", "chronology_gap", "suspect")}
print("verdict totals", tot, "sum", sum(tot.values()))
for b, v in m["verdict_counts_by_book"].items():
    print("book", b, "edges", sum(v.values()))

# 6. Matched-denominator lift: same in-corpus pairs, p_meet NaN counted as not flagged
from isnad import validate  # noqa: E402

hadith = pd.read_parquet(f"{D}hadith.parquet")
sb = validate._with_book(s, hadith)
flags = validate._text_flags(sb)
rawi = r
for src in ("marasil", "tuhfa"):
    dfd = pd.read_parquet(f"{D}denials_{src}.parquet")
    for rel in validate.NEG_RELATIONS:
        inc = validate.negatives(dfd, rawi, rel).merge(flags, on=["teacher_id", "student_id"])
        n = len(inc)
        c05 = float((inc.p_meet < 0.05).sum()) / n
        c20 = float((inc.p_meet < 0.2).sum()) / n
        t = float(inc.text_no_denial.mean())
        print("matched", src, rel, "n", n, "p_nan", int(inc.p_meet.isna().sum()),
              "chron@0.05", round(c05, 3), "chron@0.2", round(c20, 3), "text_excl", round(t, 3),
              "lift", round(t - c05, 3), "pairs gained", int(round((t - c05) * n)))

# 7. Passive forms classed as explicit by the root-prefix rule
from isnad.dates import _norm  # noqa: E402

nt = s.term.dropna().map(lambda t: " ".join(_norm(str(t)).split()))
passive = nt.str.match(r"^(حدثت|اخبرت|انبئت)(\s|$)")
print("passive-form edge rows", int(passive.sum()),
      "terms", s.term.dropna()[passive].value_counts().head(8).to_dict())

# 8. Corpus per book, narrator date coverage
print("hadith per book", hadith.groupby("book_slug").size().to_dict())
print("narrators", len(r), "death_year known", int(r.death_year.notna().sum()),
      "birth_year known", int(r.birth_year.notna().sum()))
print("narrators in six-book edges", len(set(s.teacher_id) | set(s.student_id)))
