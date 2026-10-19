# TITLE (placeholder)

## Abstract (bullets)
- Problem: isnad continuity checks are manual; existing computational work is structure-only.
- Method: per-edge probability of meeting from narrator dates with uncertainty, plus sama' evidence; no training.
- Result 1: chronology reproduces no_idrak judgements.
- Result 2: chronology alone cannot reproduce no_sama; textual sama' evidence adds a quantified lift.
- Result 3: finds date errors in widely used rijal data.
- Release: derived dataset (IDs, years, scores, verdicts).

## 1. Introduction
Motivation, contributions (the four claims below).

## 2. Data and method
Corpus scope (all fetched books; main results on the Six Books), date parsing, p_meet, verdict table. Tables: `metrics.json` -> `coverage.how`, `coverage.death_kind`.

## 3. Claim 1: chronology reproduces no_idrak judgements
- Table: AUROC and recall at 0.05/0.1/0.2 for the no_idrak class, one row per source. Source: `metrics.json` -> `negatives.<source>.no_idrak` (`auroc` vs per-row positives, `auroc_pairs` vs positives de-duplicated to unique (teacher, student) pairs, `n` scored pairs, `n_pairs_total`, `recall@0.05`, `recall@0.1`, `recall@0.2`). Sources: `marasil`, `tuhfa`.
- Same table for `mursal` (`negatives.<source>.mursal`) as a secondary class.
- Positives: `n_positives` (rows), `n_positives_scored` (non-NaN p_meet), `positives.n_pairs`, `positives.n_pairs_scored`.
- Figure: p_meet distributions, positives vs. each (source, relation) (`figures/p_meet_<source>_<relation>.png`).

## 4. Claim 2: no_sama needs textual evidence
- Table: per source, no_sama (and no_idrak, mursal for contrast) restricted to pairs present in the corpus (`negatives.<source>.<relation>.n_in_corpus`): chronology-only recall `chron_recall_in_corpus@0.05/0.1/0.2` next to the model+text recall `text_recall_in_corpus` (verdict in {denied_by_critic, chronology_gap, suspect}). Because `denied_by_critic` is set from the same gold denials when `score --denials` is used, the headline lift uses `text_recall_in_corpus_excl_denial` (chronology + term + irsal/tadlis only); the with-denial number is reported for completeness.
- False flags on positives: `false_flag_rate` (`@0.05`, `@0.1`, `@0.2`, per row) and `positives.false_flag_rate_pairs`; on the extra positive class `sama_attested.<source>.false_flag_rate`.
- Descriptive: share of each negative class's students carrying a hdith.com irsal flag, `negatives.<source>.<relation>.student_irsal_frac` (not a third negative source).
- Lift quantified as the difference between the two configurations.

## 5. Claim 3: date errors in rijal data
- Table: count of `data_error` narrators and the century-dropped pattern. Source: `date_errors.csv`.
- Examples table: selected rows with structured vs. narrative years. Source: `date_errors.csv`.
- Top-50 `chronology_gap` edges with one-line manual checks. Source: `weak_edges.csv`.

## 6. Claim 4: per-edge, explainable, no training
- Table: Six-Book verdict counts. Source: `metrics.json` -> `verdict_counts_by_book`.
- Qualitative comparison with IsnadGuard (ICML 2026, structure-only); worked edge examples from `weak_edges.csv`.

## 7. Related work
- IsnadGuard (ICML 2026): structure-only isnad analysis.
- The Hadith-science graph model (ICML 2025).
- IslamicMMLU: benchmark of LLM Islamic knowledge.
- Classical rijal and marasil literature (al-Marasil, Tuhfat al-Tahsil) as the gold source.

## 8. Limitations
Per-row weighting, era-phrase dates, name-resolution ambiguity, imputed births, chronology is not authenticity.

## 9. Ethics and licensing
hdith.com is the source and is cited; only derived numbers are released (CC-BY-4.0); no text redistributed; site owners contacted before release. Scores are aids to scholars, not rulings on hadith grading.
