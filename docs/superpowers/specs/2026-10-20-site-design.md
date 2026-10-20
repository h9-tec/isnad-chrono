# isnad-chrono explorer: static site on GitHub Pages

Date: 2026-10-20. Status: approved in conversation (user: "show names, same repo"). Repo `h9-tec/isnad-chrono` (created 2026-10-20, `main` pushed). Builds on the v2 dataset (`2026-10-20-corpus-icma-design.md`, HF `HeshamHaroon/isnad-chrono` v0.1.1).

## 1. Goal
A static, server-less site at `https://h9-tec.github.io/isnad-chrono/` that lets anyone open a hadith report and see its merged transmission tree, the common link with its death interval, who introduced which wording changes, and every narrator's inferred dates. It is the public face of the dataset and the demo for the paper.

Decisions:
- **Narrator names are shown** (short name `abbrev` from the cached narrator pages, kunya on hover). Names of classical transmitters are public facts; each narrator links to its hdith.com page `https://hdith.com/encyclopedia/rawi/p-<id>` as attribution.
- **Hadith text is never shown or shipped.** Each occurrence links to its hdith.com page `https://hdith.com/encyclopedia/book/<book_slug>/h/<hadith_id>`.
- **Same repo**: code in `site/` (hand-written HTML/JS/CSS, no build step), data exported by a new CLI stage `export-site` into `site_data/` (gitignored), shipped as a GitHub Release asset `site-data.tar.gz` (tag `site-data-latest`) that the Pages workflow downloads at deploy, same pattern as `h9-tec/model-family-tree`. The repo stays small and v0.2 refreshes the site by re-uploading the asset.
- Arabic-first UI (RTL), English labels secondary. Mobile works (one column, tree scrolls horizontally).

## 2. Pages
1. **Home / Report explorer** (`index.html`): search box accepting a book + hadith number (e.g. `bukhari 10`, `مسلم 2864`), a hadith id, a group id (`tk-N`), or a narrator name (prefix match over a client-side index). Result: the group's merged tree drawn with D3 (top-down: Companion root(s) at the top, compilers as leaves at the bottom; one component per root). Node label = short name + death interval; colour by `method` (known / inferred / prior_only); the k2 common link gets a ring and a badge "CL k2 · d. lo–hi", k3 CL a second ring; partial common links a dashed ring. Edit badges: a node that introduced n wording changes (status attributed or ambiguous) shows "n" in a small pill; hover lists the segment numbers and edit types. Edges carry the transmission term (حدثنا / عن …) on hover. Side panel: group facts (n occurrences per book with links to hdith.com, complete flag, n chains, shawahid companions), report date line "earliest datable transmitter: NAME, died between lo and hi AH", and the edit summary (attributed / ambiguous / partial / no_chain counts).
2. **Narrator page** (`narrator.html?id=N`): name, kunya, generation, recorded birth/death with kind, inferred intervals on a horizontal timeline (recorded as a point, inferred as a bar, prior-only as a faint bar), `support`, number of chains through them, teachers and students (top 20 by shared chains, with names), reports where they are the k2 common link (table, links to the explorer), links dropped by the dating step that touch them.
3. **Atlas** (`atlas.html`): (a) histogram of k2 common-link death years (bin 10 y) with a compiler filter; (b) the drift curve: edit rate and non-leaf edit rate per generation depth with n; (c) coverage table from `checks.json` (chains, groups, CL rates, dating hold-out, alignment).
4. **Leaderboards** (`boards.html`): most frequent common links (by number of groups, with names), earliest datable reports (lowest `cl_k2_date_hi`), narrators with the widest known-vs-inferred conflict (recorded death year outside the inferred interval), top edit introducers (attributed edits, with their transmission count so rate is visible).
5. **Method** (`method.html`): the dataset card's method and checks sections rendered as HTML with the live numbers, links to HF and the paper.

## 3. Data files (`export-site`, output `site_data/`)
All JSON, UTF-8, ids as ints, years as ints (interval bounds rounded outward), rates rounded to 4 decimals.
- `meta.json`: version, build date, cached page count, checks (flattened as in the release), book list `{slug, title, n_hadith_cached}`.
- `narrators.json`: array of `{id, name, kunya, gen, dy, dk, by, bk, dlo, dhi, blo, bhi, method, support, n_chains}` for every narrator with at least one chain (about 20k; ~2 MB). Names from `data/rawi.parquet` (`abbrev`, `kunya`); `dy/by` recorded years, `dk/bk` kinds.
- `search.json`: `{books: {slug: title}, numbering: {"<slug>:<numbering>": group_id}, hadith: {hadith_id: group_id}}` built from `occurrences`; narrators are searched from `narrators.json` client-side.
- `groups/<shard>/<group_id>.json` where shard = the last two decimal digits of N in `tk-N`: `{id, complete, all_chained, books: {slug: [hadith_id…]}, chains: [[rawi_id…]…] (cleaned, Companion first), roots: [rawi_id], nodes: [{id, root, depth, k, n_desc, cl2, cl3, pcl2, pcl3}], cl: {k2: {id, lo, hi, method, all_chains}, k3: {…}}, edits: {attributed: n, ambiguous: n, partial: n, cross_root: n, no_chain: n, no_common_node: n, by_node: {rawi_id: [{seg, type, status}]}, by_node_external: [{id, seg, type, status}]}, terms: {"<teacher>-<student>": term}, shawahid: [rawi_id…]}`. Terms come from `chains.parquet` (term on the teacher row).
- `narrator/<shard>/<id>.json` (shard = last two digits of id): `{teachers: [[id, n]…], students: [[id, n]…], cl_groups: [[group_id, lo, hi]…], dropped: [[other_id, reason]…]}`.
- `atlas.json`: `{cl_hist: {compiler_slug: [[bin_start, n]…], all: […]}, drift: edit_rates rows, boards: {top_cls: [[id, n_groups]…], earliest: [[group_id, cl_id, lo, hi]…], conflicts: [[id, n_dropped, dy]…], top_editors: [[id, n_edits, n_chains]…]}}`. `conflicts` = top 50 narrators by dropped dating links touching them (`dy` recorded death year or null); `top_editors` third value is the narrator's `n_chains` (as in `narrators.json`), not a transmission count; rates use 4 decimals; year bounds are rounded outward (lo floor, hi ceil).
Denylist for the site data, enforced by a test: no key may be `text`, `matn`, `statement`, `*_text`, `narrative_years`, `name_forms`, `lineage`; only `name` and `kunya` are allowed name-like keys.

## 4. Delivery
- `site/`: `index.html`, `narrator.html`, `atlas.html`, `boards.html`, `method.html`, `app.js` (router-free, one script per page), `tree.js` (D3 layout + drawing), `data.js` (fetch + cache + shard paths), `styles.css`, `vendor/d3.v7.min.js` (vendored, pinned). Loads `../site_data` locally via `python -m http.server` and `./data/` on Pages (the workflow extracts the tarball into `_site/data/`).
- `.github/workflows/pages.yml`: on push to `main` and `workflow_dispatch`; stages `site/`, downloads `site-data.tar.gz` from release `site-data-latest`, deploys with `actions/deploy-pages`. `.github/workflows/validate.yml`: `uv run pytest -q` on push/PR.
- `export-site` CLI: `--data-dir data --out site_data [--tar site-data.tar.gz]`. Upload of the asset is done by the operator with `gh release upload` (documented in README); not automated in v1 of the site.
- Repo README gets a "Explore" link and the site gets a footer: data from hdith.com (link), dataset on HF (link), code (link), CC-BY-4.0 for derived numbers, no hadith text redistributed.

## 5. Checks
- Every group JSON validates against the schema in §3 (jsonschema test over a 200-group sample) and contains no denylisted key.
- `search.json` maps every occurrence of the Six Books; a spot test resolves `bukhari 10` and `muslim 2864`.
- Tree drawing tested by a headless check: `node` is not required; instead a Python test asserts the layout input (nodes/edges per root) is a DAG with every chain embedded. Visual check by hand on five groups (ح, كلاهما, cross-root, partial, single-chain) recorded in the run record.
- Page weight: `narrators.json` ≤ 3 MB, a group JSON ≤ 200 KB; test asserts both on the real export.

## 6. Out of scope (v2 of the site)
Hadith text display, diff view of variants (needs text), dynamic search over 600k hadith numbers of all 245 books (v0.2 data), i18n beyond Arabic/English labels.
