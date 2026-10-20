# SDD ledger — plan: docs/superpowers/plans/2026-10-20-site.md
Spec: docs/superpowers/specs/2026-10-20-site-design.md. Worktree .worktrees/v1, branch v1, base 7a1bedb.

## Preflight scan
| pair / task | produces vs consumes | finding |
|---|---|---|
| T1→T2 | run_export_site manifest, check_keys/write_json, SiteContext introduced in T2 | T2 extends run_export_site; consistent |
| T1→T3 | search_key(book_alias, numbering) vs JS normalizeQuery mirror | same alias table must be duplicated in JS — accepted (no build step) |
| T2→T3/T4 | group JSON keys (id, roots, nodes[].root/depth/k, cl.k2.{id,lo,hi,method}, edits.by_node, terms, shawahid), narrator detail keys | names fixed in spec §3; JS consumes exactly those |
| T2 atlas boards.conflicts | needs death_kind == exact + inferred interval | narrators_table carries dk/dlo/dhi — ok |
| T4 method.html | data-check keys: plan guesses `dating_median_abs_error`; real keys to be read from release_hf/checks.json | Ruling: implementer picks real key names from checks.json; test asserts those — cost none |
| T5 pages.yml | checkout of branch site-data that does not exist until T6 | continue-on-error: true — ok |
| T6 step 2 | orphan branch via scratch repo in /tmp (not a worktree, not a stash) | ok; controller executes T6 (push + Pages enable via Chrome) |
| each task self-consistency | tests reference functions each task defines | T2 `group_path` defined in T2 (plan says produces SiteContext etc.; add `group_path`, `narrator_path`) — Ruling: T2 brief includes them |
Global: Stage 3 workers live in this worktree — no fetch, no data/raw writes, no kills.
Task 1: dispatched (sonnet) base 7a1bedb
Task 1: DONE_WITH_CONCERNS (3339e7e, 314 tests). Facts: narrators.json 3.62 MB (cap 3 MB), search.json 8.5 MB; 2,717 of 16,419 chain narrators missing from rawi.parquet (0.9% of chain rows; ids like 100052 are narrator pages absent from the Stage 1 sitemap). Ruling: (a) narrators.json becomes columnar {cols:[…], rows:[[…]…]} to fit the cap; search split into lazy shards search/n/<slug>.json (numbering→N) and search/h/<shard>.json (hadith_id→N, shard = id % 100) with group ids as ints; (b) ids 1 and 2 are placeholders → name 'راوٍ غير مسمّى', flag placeholder:true; other missing ids keep 'p-<id>'; (c) v0.2: queue the 2,717 missing narrator pages for fetch after Stage 3 — why: page weight and honesty — cost: JS in T3 must read columnar + shards (carried into T3 brief).
Task 1: review (sonnet) Needs fixes — Critical: search last-wins collisions (4% of keys map to >1 group). Important: raw slug case; null numbering. Minors: denylist re.I; book titles only for Six Books. Ruling: search values are LISTS of group ints (UI offers a chooser when >1); book titles for non-Six-Books come from one cached page per slug via parse_hadith (read-only cache access). Fix round 1/5 dispatched (resume implementer).
Task 1: fix round 1/5 (9 items; 3339e7e..84f4264; narrators.json 2.08 MB columnar; search sharded; 319 tests). Ruling (reverses int ids): 538 occurrences carry tg-N cluster groups → group ids stay full strings everywhere; T2/T3 use strings. Round 2/5 dispatched: string ids + title lookup over cached occurrences (b-7/b-8 had no readable first page).
Task 1: fix round 2/5 (84f4264..6b7dc4e; string ids; title lookup; b-7/b-8 titles resolve once a page is cached). Re-review pending.
Task 1: re-review (sonnet): 9/9 addressed, NEW Important: truncated .gz raises EOFError in _page_title → fix round 3/5 dispatched. Deferred minor: _titles loops over all occurrences for books with no cached page.
Task 1: fix round 3/5 (9502421; EOFError/zlib tolerance + test; controller-verified: except tuple at export_site.py:78, test present, full suite 320 passed)
Task 1: complete (commits 7a1bedb..9502421, review clean after 3 rounds)
Task 2: dispatched (opus) base 9502421
Task 2: DONE_WITH_CONCERNS (122007e, 329 tests; real export 47,515 files 72 MB, largest group 67.6 KB, 1.5 min). Rulings: boards.conflicts redefined = top 50 narrators by number of dropped dating links [id, n_dropped, dy] (recorded-vs-inferred distance is ~0 by construction because known dates pin the interval); rates in site JSON use 4 decimals (spec said 3; drift at depth 1 is 0.0054); multi-root cl from the root with most chains accepted; top_editors third value = n_chains accepted; re-export wipes out/groups, out/narrator, out/search first (guard: out ≠ data_dir/ancestor/repo root).
Task 2: review (opus) Needs fixes — Important 1: edits.by_node names introducers outside the drawn tree (113 rows / 17 groups; edits tree includes external carriers) → Ruling: option B, move them to by_node_external [{id, seg, type, status}] + test by_node ⊆ nodes (drawing carrier chains deferred to site v2); Important 2: fractional years truncated → floor lo / ceil hi everywhere incl. narrators.json. Minors: reuse dating.clean_chain_rows (term of collapsed duplicate), docstring on term selection, schemas for narrator/atlas + search shard ≤ 600 KB test, top_editors label n_chains. Carry to T3: lay out edges from chains, not depth (DAG depth ≠ parent depth+1). Scaling note (per-group DataFrames) deferred to v0.2. Fix round 1/5 dispatched.
Task 2: fix round 1/5 (9 items; 122007e..44ec22c; 334 tests; export 72.8 MB). Ruling: placeholders 1/2 excluded from all boards (they ranked 3rd/4th on conflicts) → round 2/5 dispatched.
Task 2: fix round 2/5 (bb4a23c; placeholders off boards). Re-review pending.
Task 2: complete (commits 9502421..bb4a23c, review clean after 2 rounds). Deferred minors: mixed joined/unjoined chain handling differs between tree.load_chains and dating.clean_chain_rows (0 cases today); wipe-before-success; per-group DataFrames scaling.
Task 3: dispatched (opus) base bb4a23c
Task 3: DONE (c8470c4, 341 tests; headless-Chrome verified 6 groups; controller viewed tk-61734 in Chrome: readable, CL rings correct). Ruling for fix round: layer rows by longest path from the root (removes the 5% upward/sideways edges that draw as long arcs); tap-to-show details on touch (already partly there). Review (opus) dispatched.
Task 3: review (opus) Approved; minors 1–6 (unvalidated ?g=, prototype keys as aliases, stale-load race, zoom rebuild clears selection, keyboard/touch access, narrow tests). Ruling: minors 1–5 + longest-path layering fixed now as 'fix round 1' before T4 (they share explorer code); minor 6 partially (http:// and //cdn in test).
Task 3: fix round 1/5 (c8470c4..719e098; longest-path layering: 0 non-downward edges except 68 cycle-closing edges in 61 groups drawn red dashed; 343 tests). Re-review pending.
Task 3: complete (commits bb4a23c..719e098, review clean; one new minor carried into T4: selectNode lists incoming edges across components — scope to comp). Deferred: choose()/result lists not covered by the stale token.
Task 4: dispatched (opus) base 719e098
Task 4: DONE (6c03dea, 347 tests). Rulings for fix round: cl_hist (export) counts only CLs with bounded intervals (hi−lo ≤ 300, dating.BOUNDED_WIDTH) — the 0.7% tail at 750–940 AH is unbounded-interval midpoints; narrator timeline axis clamped to [−60, 400] with 'beyond' arrows for prior_only; meta.n_hadith_pages_cached (export time) vs checks value (release time) both labelled — accepted.
Task 4: review (opus) Approved; 8 minors. Fix round 1 dispatched with: cl_hist bounded-only (export), prior_only axis clamp, placeholders hide dating facts on narrator page, drift low-n styling (n<30 hollow), caption/range escaping, bidi fixes, plural, tests for p-<id> and 404 path.
Task 4: fix round 1/5 (6c03dea..75a18ba; 349 tests; histogram excluded 19 prior_only + 72 unbounded). Note: earliest board sorts by lowest hi so unbounded CLs cannot rank — no change. Re-review pending.
Task 4: complete (commits 719e098..75a18ba, review clean after 1 round)
Task 5: dispatched (sonnet) base 75a18ba
Task 5: DONE (31f2b95, 350 tests). Review (sonnet) dispatched.
Task 5: complete (commits 75a18ba..31f2b95, review clean). Minors deferred: --all-extras flag, footer duplication, README commit message hard-codes v0.1.1, spec §4 still says release tarball (update in final fix).
Final review dispatched (opus) over 7a1bedb..31f2b95; Task 6 (controller): site-data push in progress.
Final review (opus): Needs fixes — Important 1 kunya editorial text (635 values, max 152 chars) in public data; 2 README explore paragraph describes a different site; 3 pages.yml continue-on-error now stale. Minors 4–15. Ruling: ONE fix dispatch (brief final-fix-brief.md) covering 1–3 + minors 4–12 (14 partially; 15 terms accepted at 65 chars); then re-export, rebuild site-data, scoped re-review, push + merge.
Final fix round (31f2b95..f80c7d9; 360 tests; kunya: 1,198 trimmed, 42 nulled, max 25 chars). Ruling: names carry the same وقيل notes (89 of 16,419) → addendum commit trims names to the first variant + kunya rule accepts ابو without hamza; then scoped re-review of the whole fix range.
Final fix addendum (f2afd53; names: 133 trimmed, max 63; kunya max 25; 361 tests; 64-char name cap accepted for two real nasabs). Scoped re-review pending.
Final re-review clean. site-data pushed (91665c2), main fast-forwarded to f2afd53 and pushed; Pages source set to GitHub Actions via Chrome. Awaiting deploy.
Site LIVE: https://h9-tec.github.io/isnad-chrono/ (pages run green; data served from site-data branch). Plan complete.
