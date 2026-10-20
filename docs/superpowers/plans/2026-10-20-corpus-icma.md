# Corpus-wide ICMA dataset (isnad-chrono v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the cached hdith.com pages, build and publish on Hugging Face the merged chain trees, common links with dates, wording-change attributions, and constraint-inferred narrator dates for every multiply-transmitted report.

**Architecture:** Five new parquet-in/parquet-out stages on top of v1: `chains` (all chains per hadith from the annotated isnad HTML, ح-aware) → `groups` (takhrīj groups, occurrences, alignment segments as hashes, shawāhid) → `dating` (difference-constraint propagation over the narrator graph) → `tree` (per-group merged tree, common links, report dates) → `edits` (attribute each substitution to the transmitter who introduced it) → `export-hf` (configs + checks + card + push). Text stays in a local store; released tables carry ids, years and hashes.

**Tech Stack:** Python 3.12 (uv); pandas, pyarrow; `huggingface_hub` (new, for push only); stdlib `re`, `hashlib`, `heapq`.

**Spec:** `docs/superpowers/specs/2026-10-20-corpus-icma-design.md` (and v1 spec for the scorer).

## Global Constraints

- Dependencies: v1 set plus `huggingface_hub>=0.25` only.
- Chains come from `isnad_html` spans: narrator `<span class="hp-rawi" … data-rawi-slug="p-N" … data-name="…">`, formula `<span class="hp-sigha" …>TEXT</span>`, transfer = standalone ح in text (not inside a word), parallel narrator = a narrator span with no formula between it and the previous narrator (its `data-name` may start with و).
- Reading order is compiler side first; the term of edge T→S is the formula token immediately preceding T's span; a parallel narrator inherits the preceding formula.
- Text never leaves `data/text/`; released tables hold `sha256(normalised text)[:16]` as `*_hash`. Normalisation = `isnad.dates._norm` + whitespace collapse.
- Constants (new, `isnad/constants.py`): `A0 = 8` (reuse), `AGE_MIN = 20`, `AGE_MAX = 100` (now used as hard lifespan bounds in dating), `MAX_SPAN = 100`, `K_CL = (2, 3)`, `HOLDOUT_FOLDS = 5`, `ALIGN_SAMPLE = 500`.
- HF repo: `HeshamHaroon/isnad-chrono`, dataset, license `cc-by-4.0`; token from `~/.config/isnad-chrono/.env` (`HF_TOKEN`), never printed.
- Commits: conventional prefixes, no Co-Authored-By trailers. Never run `fetch` during this plan (Stage 3 workers own `data/raw` and `data/queue.sqlite`); stages read `data/raw` only.

## Review Focus

1. A hadith whose `isnad_html` is empty (3% of pages) or has no narrator spans: `chains` must emit zero chains for it and count it, not crash (Task 1 `test_no_isnad_html_yields_no_chains`).
2. A ح-transfer whose first segment's last narrator is NOT in the final segment (e.g. ends at a parallel narrator spelled differently): the join must fall back to the next shared narrator; if none, the segment is emitted as its own chain ending at its last narrator and flagged `unjoined=True` (Task 1 `test_unjoined_segment_flagged`).
3. A group with only one chain: no common link exists; `report_dates` must carry nulls, not the single narrator (Task 4 `test_single_chain_has_no_cl`).
4. Narrators with no links and no dates: dating must return `support == 0` and the prior-only interval, never an empty interval (Task 3 `test_isolated_narrator_prior_only`).
5. A substitution whose carriers span two disjoint branches: attribution must return the lowest common ancestor, which may be above the base carriers; the edit is then flagged `ambiguous=True` (Task 5 `test_attribution_ambiguous_when_lca_covers_base`).

---

### Task 1: Chains from the annotated isnad HTML

**Files:** Create `isnad/chains.py`, `tests/test_chains.py`; CLI `chains --cache-root data/raw/html --out data/chains.parquet`.

**Interfaces:**
- `tokenize(isnad_html: str) -> list[Tok]`, `Tok = ("R", rawi_id:int, name:str) | ("F", formula:str) | ("H",)`; a narrator span directly following another narrator span (no F between) is marked parallel by the builder, not the tokenizer.
- `build_chains(tokens, compiler_id: int) -> list[Chain]`, `Chain(links: list[Link], unjoined: bool)`, `Link(rawi_id:int, position:int, term:str|None)` with position 0 = earliest narrator (companion end) and the compiler last; `term` on a link = how the NEXT link received from it (teacher-side formula, as v1).
- `chains_table(cache_root) -> DataFrame[hadith_id, chain_no, position, rawi_id, term, unjoined]` written by the CLI; uses `isnad.build.read_page`/`_pages` and `pageprops.extract`; `compiler_id = int(isnad[-1].slug[2:])`; pages with no narrator spans are counted in a printed summary.

- [ ] Step 1: failing tests (fixtures `hadith_bukhari_10_tahwil.html.gz`, `hadith_tirmidhi_100144_tahwil.html.gz`, `hadith_muslim_11563.html`):
```python
def test_bukhari_10_three_chains(fx_gz):
    ch = build_chains(tokenize(isnad_html(fx_gz("hadith_bukhari_10_tahwil.html.gz"))), 5495)
    paths = sorted(tuple(l.rawi_id for l in c.links) for c in ch)
    assert paths == sorted([(3732,4184,5917,7248,3875,3784,5495), (3732,4184,5917,7248,3875,941,5495), (3732,4184,5917,6279,3875,941,5495)])
    assert all(not c.unjoined for c in ch)
def test_tirmidhi_100144_two_chains(fx_gz):  # ids: 1339,3736,4789 shared; branches 3493→5187 and 650→4513; compiler 10859
def test_terms_follow_teacher_formula(fx_gz):  # Bukhari 10 chain via 3784: link 5917 term "عن", link 7248 term "أخبرنا", link 3784 term "حدثنا", compiler term None; parallel 6279 inherits "أخبرنا"
def test_single_chain_matches_v1(fx):  # 11563 → one chain equal to the v1 edge order, no unjoined
def test_no_isnad_html_yields_no_chains(): assert build_chains(tokenize(""), 1) == []
def test_unjoined_segment_flagged(): # synthetic tokens: segment ending at id 99 absent later → one chain with unjoined=True
```
- [ ] Step 2: run → FAIL. Step 3: implement tokenizer (regex over spans; standalone ح via `(?<![؀-ۿ])ح(?![؀-ۿ])` on the text between spans), builder (split at H; final segment = full path; earlier segments join at their last narrator's first occurrence in the final path; parallel narrators fork at that level), table writer, CLI. Step 4: run → PASS; full suite. Step 5: commit `feat: chains from annotated isnad html (tahwil-aware)`.

### Task 2: Groups, occurrences, alignment segments, shawāhid

**Files:** Create `isnad/groups.py`, `tests/test_groups.py`; CLI `groups --cache-root data/raw/html --out-dir data` writing `groups.parquet`, `occurrences.parquet`, `segments.parquet`, `shawahid.parquet`, and `data/text/segments_text.parquet` (seg hash → text, local only).

**Interfaces:**
- `parse_group(props_hadith: dict) -> GroupRecord(group_id:str, n_entries:int, n_chains:int, books:list[str], occurrences:list[(hadith_id:int, book_slug:str, numbering:str)], segments:list[Segment], shawahid:list[(companion_rawi_id:int|None, hadith_ids:list[int])])`; `Segment(seg_no:int, kind:str, base_hash:str|None, variant_hash:str|None, carrier_hadith_ids:list[int], base_text, variant_text)`.
- Source fields: `takhrij_isnad_summary.group_slug` (→ group_id "tk-N"), `takhrij.sources[].book_id` + `occurrences[].entry_id/hadith_num`, `variants.segments[]` (`kind` base → `text`; substitution → `surface_text`, `hids`), `shawahid.groups[].narrator` (name; resolve to id via `rawi.name_forms` index from `isnad.gold.NameIndex` when unambiguous, else None) and `books[].entries[].entry_id`.
- `hash_text(s) -> str` = sha256 of `_norm(s)` with whitespace collapsed, first 16 hex.
- Groups are keyed by group_id; the same group appears on every member page: the CLI de-duplicates by group_id and marks `complete = all occurrence hadith_ids present in the cache`.

- [ ] Step 1: tests on 11563: `group_id == "tk-28092"`, `n_entries == 12`, `n_chains == 19`, 7 segments with kinds `[base, substitution, base, substitution, base, substitution, base]` (verify count from fixture), substitution 1 carriers `[171551, 171618, 308649, 180874]`, `hash_text` stable and 16 chars, text table has the segment text while `segments.parquet` has none; `test_group_dedup_and_complete` on a tmp cache with two member pages of one group.
- [ ] Steps 2–5: FAIL → implement → PASS → commit `feat: takhrij groups, alignment segments, shawahid`.

### Task 3: Narrator dating by difference constraints

**Files:** Create `isnad/dating.py`, `tests/test_dating.py`; CLI `dating --chains data/chains.parquet --rawi data/rawi.parquet --out data/rawi_dates_inferred.parquet --dropped data/dropped_links.parquet --holdout data/checks_dating.json`.

**Interfaces:**
- Variables per narrator: `b_i` (birth), `d_i` (death). Constraints: known death exact → `[d−sd, d+sd]` (sd from v1 `death_sd`, era/approx widths kept); known birth likewise; lifespan `AGE_MIN ≤ d_i − b_i ≤ AGE_MAX`; link T→S (from chains, unique pairs, weight = count, class explicit/ambiguous via `isnad.score.classify_term`) → `b_S + A0 ≤ d_T` and `d_T ≤ d_S + MAX_SPAN` (teacher died no later than 100 years after the student... i.e. `d_T − d_S ≤ MAX_SPAN` is implied; the needed one is `b_S + A0 ≤ d_T`).
- `propagate(narrators: DataFrame, links: DataFrame, max_iter=50) -> (intervals: DataFrame[rawi_id, birth_lo, birth_hi, death_lo, death_hi, support], dropped: DataFrame[teacher_id, student_id, reason])`: iterative tightening (for each link: `d_T ≥ b_S + A0` raises `death_lo[T]`, `b_S ≤ d_T − A0` lowers `birth_hi[S]`; lifespan bounds couple b and d) until no change; when an interval would become empty (`lo > hi`), drop the link with the smallest weight among those that tightened it in this round (explicit-class links are never dropped before ambiguous ones), record it, and continue. `support` = number of links touching the narrator that survived.
- `death_mode` = midpoint of the final interval; `method` = "known" | "inferred" | "prior_only".
- `holdout(narrators, links, folds=5, seed=0) -> dict` hides known death years per fold, re-propagates, returns median absolute error (mode vs truth), 90% coverage, and the same two numbers for baselines `depth` (mean death year of known narrators at the same chain depth bucket) and `generation` (midpoint of the narrator's `generation_num` century, when present).

- [ ] Step 1: tests (synthetic): `test_link_tightens_birth_and_death` (T known d=100, S unknown → S.birth_hi ≤ 92; S.death_lo ≥ 92+20); `test_chain_of_three_propagates`; `test_negative_cycle_drops_weakest_link` (contradictory ambiguous link dropped, explicit kept); `test_isolated_narrator_prior_only` (support 0, interval = prior bounds [0, 1500] clipped by nothing; method prior_only); `test_holdout_returns_metrics_keys`.
- [ ] Steps 2–5: FAIL → implement (vectorised per-iteration passes with numpy over link arrays; 300k links × 50 iters is fine) → PASS → commit `feat: narrator dating by difference-constraint propagation`.

### Task 4: Merged chain tree, common links, report dates

**Files:** Create `isnad/tree.py`, `tests/test_tree.py`; CLI `tree --chains data/chains.parquet --occurrences data/occurrences.parquet --dates data/rawi_dates_inferred.parquet --out-dir data` writing `tree_nodes.parquet`, `report_dates.parquet`.

**Interfaces:**
- `merge_tree(chains: list[list[int]]) -> Tree` where each chain is earliest→compiler; nodes keyed by rawi_id; edges parent (earlier) → child (later); `depth` = distance from the root(s) (the earliest narrator(s); a group may have several companions → several roots, handled per root).
- `k_branches(tree, node) -> int` = number of children whose subtrees reach at least one compiler through disjoint next hops (children count, each child must reach a compiler).
- `common_links(tree, k) -> list[int]`: earliest nodes (smallest depth) with `k_branches ≥ k` whose subtree contains all compilers below them; partial common links = other nodes with `k_branches ≥ k` below.
- `report_dates(groups, trees, dates) -> DataFrame[group_id, cl_k2_id, cl_k2_date_lo, cl_k2_date_hi, cl_k3_id, cl_k3_date_lo, cl_k3_date_hi, n_chains, n_compilers, complete]`; date interval = the CL's `death_lo/hi` from Task 3 (known or inferred); nulls when no CL.

- [ ] Step 1: tests (synthetic): `test_merge_two_chains_shared_prefix`, `test_k_branches_counts_disjoint_children`, `test_cl_k2_and_k3_differ` (a fan of 2 vs 3), `test_single_chain_has_no_cl`, `test_report_dates_uses_cl_interval`.
- [ ] Steps 2–5 → commit `feat: merged chain trees, common links, report dates`.

### Task 5: Edit attribution and generation edit rates

**Files:** Create `isnad/edits.py`, `tests/test_edits.py`; CLI `edits --segments data/segments.parquet --chains data/chains.parquet --occurrences data/occurrences.parquet --out data/edits.parquet --rates data/edit_rates.parquet`.

**Interfaces:**
- `attribute(tree, carriers: set[int], base_carriers: set[int], chains_by_hadith: dict[int, list[list[int]]]) -> Attribution(rawi_id:int|None, depth:int|None, ambiguous:bool)`: candidate nodes = nodes that are ancestors (or the compiler itself) of every chain of every carrier hadith; choose the lowest (max depth); `ambiguous = True` if that node is also an ancestor of any base carrier's chains.
- `edits_table(...) -> DataFrame[group_id, seg_no, introduced_by_rawi_id, generation_depth, edit_type, ambiguous]`; `edit_type` = "sub" when both hashes exist, "ins" when base_hash None, "del" when variant_hash None.
- `edit_rates(edits, chains) -> DataFrame[depth, n_transmissions, n_edits, rate]`.

- [ ] Step 1: tests (synthetic tree with 3 chains): `test_attribution_lowest_common_ancestor`, `test_attribution_ambiguous_when_lca_covers_base`, `test_edit_type_classification`, `test_rates_by_depth`.
- [ ] Steps 2–5 → commit `feat: wording-change attribution and generation edit rates`.

### Task 6: Checks, HF export, dataset card, push

**Files:** Create `isnad/export_hf.py`, `tests/test_export_hf.py`, `DATASET_CARD_v2.md` (replaces `DATASET_CARD.md` content); CLI `export-hf --data-dir data --out release_hf [--push]`.

**Interfaces:**
- `alignment_check(sample=ALIGN_SAMPLE, seed=0) -> dict`: for sampled groups re-align base vs each variant text with `difflib.SequenceMatcher` on token lists (our own alignment) and report the fraction of site substitution spans that coincide with a difflib replace/insert/delete opcode (±1 token).
- `sanity_checks(trees, chains) -> dict`: compiler always a leaf, every root has no parent, negative-cycle/dropped-link count, coverage per table.
- `build_release(data_dir, out) -> Manifest`: configs `narrators` (rawi_id, generation_num, death_year, death_kind, birth_year, birth_kind, death_lo, death_hi, birth_lo, birth_hi, support, method), `chains`, `groups`, `occurrences`, `tree_nodes`, `report_dates`, `edits`, `edge_scores` (v1), `checks` (one-row JSON-ish table); denylist from v1 `isnad.export` applied to every config (no `*_text`, names, statements); writes `README.md` from the card template with the checks numbers filled in.
- `push(out, repo_id="HeshamHaroon/isnad-chrono", token)`: `huggingface_hub.HfApi().create_repo(repo_type="dataset", exist_ok=True)` then `upload_folder`.

- [ ] Step 1: tests: `test_release_configs_and_denylist` (tmp parquet inputs → all configs present, no denylisted column, README contains the check numbers), `test_alignment_check_on_synthetic` (identical texts → agreement 1.0), `test_push_is_mocked` (HfApi patched; token read from env file path parameter).
- [ ] Steps 2–5 → commit `feat: HF release build with checks and dataset card`.

### Task 7: Operational run on the current cache and v0.1 push

- [ ] Step 1: `chains` → report counts (hadith with chains, chains, unjoined); spot-check 5 ح hadith by hand.
- [ ] Step 2: `groups` → counts (groups, complete groups, segments); `dating` → hold-out numbers; `tree` → CL coverage (share of groups with k2/k3 CL); `edits` → rates table.
- [ ] Step 3: `export-hf` without push → inspect README numbers; then `--push` (creates/updates `HeshamHaroon/isnad-chrono`); record everything in `docs/runs/2026-10-xx-v2-run.md`; commit docs.
- [ ] Step 4: when Stage 3 workers finish: `build` (hadith/rawi), rerun stages 1–6, push v0.2 with `complete` groups updated.

---

## Self-review notes
- Spec coverage: §2 tables (T1 chains, T2 groups/occurrences/segments/shawahid, T3 rawi_dates_inferred, T4 tree_nodes/report_dates, T5 edits), §3 algorithms (T1–T5, checks in T6), §4 release (T6, T7).
- Types: `Chain/Link` (T1) consumed by T3/T4/T5 through `chains.parquet` columns; `Segment` hashes (T2) consumed by T5; `rawi_dates_inferred` columns (T3) consumed by T4/T6.
- Unverified until T7: exact segment count on 11563 (test asserts the list derived from the fixture at implementation time), shawāhid name resolution rate, CL coverage.
