# Strong goal for this stage: a temporal constraint model of hadith transmission

## What we uniquely hold (2026-10-20)
- 612,548 hadith across 245 books with every chain link resolved to a narrator id (34,816 built; the rest fetching), i.e. ~3M teacher→student instances.
- 20,777 narrators: 10,100 with a death year (uncertainty kinds), 1,400 with a birth year, teacher/student lists, 148k critic quotes, confirmed-samaʿ lists, tadlīs/irsāl flags.
- A per-link meeting-probability engine validated against the critics (AUROC 0.79–0.90 on reach/mursal); 1,505 gold denial pairs.

## Why the current goal is weak
It reproduces judgements the critics already made. Agreement with Abū Ḥātim is a sanity check, not knowledge.

## Candidates (criteria: new knowledge, falsifiable, method novelty, ≤4 weeks with current assets)
| # | goal | new knowledge | falsifiable | novelty | weeks | verdict |
|---|---|---|---|---|---|---|
| A | Date the undated narrators by constraint propagation | ~10k narrator date intervals | yes: hide known dates, recover them | yes (STN on isnad graph; prior work uses only graph depth) | 2–3 | **do now** |
| B | Undiscussed breaks in the 239 non-canonical books | a ranked list the critics never covered | partly (expert audit) | no (existing model) | 1 after Stage 3 | **do when Stage 3 lands** |
| C | Corpus-wide common-link dating of reports | origin dates for 600k reports | contested | yes | 6+ | next paper |
| D | Empirical tadlīs profiles (ʿan vs ḥaddathanā meeting odds per narrator) | per-narrator evidence | yes | modest | 1 | side result of A |

## The chosen goal: A + B as one paper
**Claim:** The isnad corpus is a system of temporal constraints. Every link "S heard from T" implies birth(S) + A0 ≤ death(T), and every narrator's lifespan is bounded. Solving these constraints over the whole corpus (a) dates narrators the biographical dictionaries never dated, with validated error bars, and (b) exposes exactly the links that cannot be satisfied — which are either data errors or real breaks, and we classify them.

**Method (new):** a Simple Temporal Network (Dechter) over ~3M difference constraints with soft (probabilistic) bounds: variables birth_i, death_i; hard-ish constraints from links; priors on lifespan (Age ~ N(68,14)) and on ḥaddathanā vs ʿan reliability; inference by iterative interval tightening (Bellman-Ford on the constraint graph) for the hard core, then a Gaussian/loopy-BP pass for posteriors. Inconsistent cycles are found by the same algorithm (negative cycles) and attributed to the weakest link, which is the error-detection output. Prior art: Shuaib et al. 2022 (Applied Network Science) use trophic level (graph depth) as a time proxy without constraints or error bars [verify details]; the UC Davis Hadith Network Project proposed automated dating but has not published a method.

**Validation (falsifiable):** 5-fold hide-out of narrators with exact death years: report median absolute error and 90%-interval coverage; compare with (i) trophic-depth baseline, (ii) tabaqa-only baseline (generation → century). Also: do inferred dates for the 6 negative-control sound chains stay consistent; does the method re-find the 19 site-side date errors the audit already confirmed.

**Deliverables:** `rawi_dates_inferred.parquet` (interval per narrator, method, support), `inconsistent_links.parquet` (with attribution), the paper rewritten around the constraint model with the current validation as the sanity section, and the Stage 3 list of previously undiscussed breaks.

**Plan:** week 1 — STN prototype on the Six Books graph + hold-out validation; week 2 — robust version (soft constraints, cycle attribution), full narrator set; week 3 — Stage 3 corpus, undiscussed breaks, paper v2.
