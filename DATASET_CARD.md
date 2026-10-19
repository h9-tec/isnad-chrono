---
license: cc-by-4.0
language:
- ar
tags:
- hadith
- isnad
- chronology
pretty_name: isnad-chrono
---

# isnad-chrono

## Summary

Per-edge chronology scores for the teacher-to-student links in the hadith chains of hdith.com, plus narrator dates. Each edge carries the probability that the student could have heard from the teacher (`p_meet`), the evidence flags, and a verdict. The files contain IDs, years, flags, scores and verdicts only.

## Files

- `edges.parquet`: `teacher_id, student_id, hadith_id, position, term, chain_type, entry_kind`
- `edge_scores.parquet`: per edge keys, `p_meet`, `how`, date-conflict and sama' evidence flags, `verdict`
- `rawi_dates.parquet`: `rawi_id, generation_num, death_year, death_sd, death_kind, birth_year, birth_sd, birth_kind, is_companion, flags, sama_confirmed, teachers_ids, students_ids`
- `MANIFEST.json`: row counts and columns per file

IDs are hdith.com narrator and hadith IDs. Years are Hijri.

## Method

1. `p_meet` = P(student was at least A0 = 8 lunar years old before the teacher died).
2. Known student birth is used; otherwise birth = death - Age, with Age ~ N(68, 14) truncated to [20, 100].
3. Death years carry an sd by `kind` (exact 1, alt half-range >= 2, approx 5, after/before +3 +-5, era = interval); the normal CDF is computed via erf.
4. Verdict, first match wins: `data_error` (date conflict on either narrator) > `denied_by_critic` > `chronology_gap` (p_meet < 0.05) > `suspect` (p_meet < 0.2, ambiguous term, student has irsal/tadlis) > `ok`.
5. Sensitivity is reported at thresholds 0.05, 0.1 and 0.2.

## Limitations

- Edges are per row: an edge appearing in many hadith appears many times, so aggregate counts are weighted by frequency unless deduplicated.
- Era-phrase dates are intervals and coarse.
- Name resolution for the gold sets is token-overlap based; ambiguous matches are excluded and counted.
- Imputed birth years use a population prior and are not individual estimates.
- Scores flag chronology, not authenticity; a high score does not establish sama'.

## Source and license

Derived from hdith.com. No source text is redistributed. The derived numbers are released under CC-BY-4.0; attribution to hdith.com as the data source is required. The source site's own license is unstated and the owners are to be contacted before release.

## Citation

TODO: add BibTeX after the arXiv posting.
