# Corpus-wide isnad-cum-matn dataset (isnad-chrono v2)

Date: 2026-10-20. Status: approved in conversation (sections 1–4). Builds on v1 (`2026-10-18-isnad-chrono-design.md`) and the strong-goal analysis (`docs/analysis/2026-10-20-strong-goal.md`).

## 1. Goal and deliverables
Deliverable order (user decision): **dataset first on Hugging Face, paper later.** For every multiply-transmitted report in hdith.com's 245 books, compute the merged chain tree, the common link(s) with dates, the earliest wording (as hashes), and the attribution of each wording change to the transmitter who introduced it; date the undated narrators by constraint propagation. Ship as parquet configs on HF with automatic quality checks. The paper phase later adds the 12 held-out published case studies.

Decisions: alignment source = the site's precomputed variant segments, verified by re-aligning 500 groups; validation set for the paper = Motzki core (zakāt al-fiṭr, Ibn Abī l-Ḥuqayq, the cat, ʿUrwa corpus), Juynboll standard cases (Nāfiʿ, man kadhaba), recent ICMA (Pavlovitch kalāla, Sadeghi travelling-tradition); common link = parametric (k≥2 and k≥3 both reported); headline = dating the tradition.

## 2. Data model (all from cached page JSON; one new parser stage `parse_group`)
```
groups.parquet        group_id (tk-N), n_entries, n_chains, books[]
occurrences.parquet   group_id, hadith_id, book_slug, numbering
chains.parquet        hadith_id, chain_no, position, rawi_id, term           (ح-transfers split into separate chains)
segments.parquet      group_id, seg_no, kind(base|substitution), base_text_hash, variant_text_hash, carrier_hadith_ids[]
shawahid.parquet      group_id, companion_rawi_id, hadith_ids[]
rawi_dates_inferred   rawi_id, death_lo, death_hi, death_mode, birth_lo, birth_hi, support, method
tree_nodes.parquet    group_id, rawi_id, depth, k_branches, n_descendant_chains, is_cl_k2, is_cl_k3
report_dates.parquet  group_id, cl_k2_id, cl_k2_date_lo, cl_k2_date_hi, cl_k3_id, cl_k3_date_lo, cl_k3_date_hi, earliest_text_hash, complete
edits.parquet         group_id, seg_no, introduced_by_rawi_id, generation_depth, edit_type(sub|ins|del)
```
Text (matn, segment text) lives only in a gitignored local `text/` store; released tables carry hashes (sha256 of normalised text) and ids. Source fields: `takhrij.sources[].occurrences[].entry_id`, `takhrij_isnad_summary.group_slug` (tk-N), `variants.segments[] {kind, text|surface_text, hids}`, `composite_matn`, `shawahid.groups[]`, `isnad[]` + `isnad_html` (transfer markers), `similars`.

## 3. Algorithms
1. Chain extraction from `isnad_html` (verified 2026-10-20: the flat `isnad` list keeps only the LAST branch of a ح-transfer, e.g. Bukhārī #10 drops the ʿAbdān path; ح is plain text, narrators are `<span class="hp-rawi" data-rawi-slug="p-N">`, formulas are `hp-sigha` spans). Parse the span sequence in reading order (compiler side first), split at standalone ح, treat و-joined consecutive narrators without a formula as parallel narrators at one level, and join each earlier segment to the final chain at its last shared narrator → one chain per path to the compiler. Fixtures: `tests/fixtures/hadith_bukhari_10_tahwil.html.gz`, `hadith_tirmidhi_100144_tahwil.html.gz`. Consequence for v1: `edges.parquet` undercounts ح branches; v2 `chains.parquet` supersedes it.
2. Merged chain tree per group (union of chains, rooted at the earliest narrator); per node: depth, independent downstream branches k (branches reaching distinct compilers through disjoint next hops), descendant chain count; common link = earliest node with k≥2 / k≥3; partial common links by the same rule below it.
3. Narrator dating: variables birth_i, death_i; constraints birth_S + A0 ≤ death_T per link (ḥaddathanā-class weighted above ʿan), lifespan prior Age ~ N(68,14), known dates as tight intervals; iterative difference-constraint propagation over the narrator graph; negative cycles attributed to their weakest link and dropped (the dropped list is an output); outputs intervals + support.
4. Report date = common link's death interval (lo/hi), under k≥2 and k≥3.
5. Edit attribution: for a substitution segment with carriers H, the lowest tree node whose descendant chains include all of H and none of the base carriers; generation depth = node depth; edit rate per generation = attributed substitutions at depth d / transmissions at depth d.
6. Automatic checks shipped with the data: narrator-dating 5-fold hold-out (median abs error, 90% coverage) vs depth and generation baselines; alignment agreement on 500 re-aligned groups; tree sanity (compiler leaf, root earliest); negative-cycle count; coverage per table.

## 4. Release, repo, plan
- Modules: `isnad/chains.py`, `isnad/groups.py`, `isnad/tree.py`, `isnad/dating.py`, `isnad/edits.py`, `isnad/export_hf.py`; one parquet in/out per stage; fixtures + unit tests; CLI subcommands `chains`, `groups`, `tree`, `dating`, `edits`, `export-hf`.
- HF dataset `HeshamHaroon/isnad-chrono` (CC-BY-4.0 derived data) with configs: narrators, chains, groups, occurrences, tree_nodes, report_dates, edits, edge_scores (Six Books), checks. Dataset card: source, unstated upstream license, method, checks, limitations. Text only as hashes.
- Stage 3 dependency: `complete` flag per group (all occurrences cached); rebuild when Stage 3 finishes.
- Plan: week 1 chains + groups + tree + common links on the current cache; week 2 dating + edits + checks; week 3 export, card, push; then Stage 3 rebuild. Paper phase afterwards.
- Risks: partial site alignment on long reports (measured); ح-split precision depends on HTML markers (fixture-tested); wide intervals for isolated narrators (reported, not hidden).
