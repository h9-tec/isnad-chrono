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
- Table: AUROC and recall at 0.05/0.1/0.2 for the no_idrak class. Source: `metrics.json` keys for the denial class (`auroc`, `n`, `recall@0.05`, `recall@0.1`, `recall@0.2`).
- Figure: p_meet distributions, positives vs. negatives (`figures/`).

## 4. Claim 2: no_sama needs textual evidence
- Table: AUROC and recall for no_sama / contemporaries (chronology alone) vs. with sama' evidence. Source: `metrics.json` per-class keys; `false_flag_rate` (`@0.05`, `@0.1`, `@0.2`) and `n_positives`.
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
