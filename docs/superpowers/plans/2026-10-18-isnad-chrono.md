# isnad-chrono Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every teacher→student isnad edge on hdith.com by meeting probability from narrator chronology plus textual sama' evidence, validate against classical critics' denials, and produce the dataset + tables the paper needs.

**Architecture:** Every hdith.com page embeds its full data as JSON in `<script data-page="app" type="application/json">`, so parsers read JSON, never HTML. Pipeline = sitemap → fetch queue (sqlite) → raw HTML cache → parquet tables (hadith, edges, rawi) → edge scores → metrics/report. One module per stage, each re-runnable from cache.

**Tech Stack:** Python 3.12 via uv; pandas, pyarrow, httpx, pytest; sqlite3 (stdlib); Firecrawl v2 HTTP API (no SDK).

**Spec:** `docs/superpowers/specs/2026-10-18-isnad-chrono-design.md`

## Global Constraints

- Python 3.12, managed by `uv`; dependencies: `pandas`, `pyarrow`, `httpx`, `pytest`, `pytest-httpx` only.
- `FIRECRAWL_API_KEY` read from `~/.config/isnad-chrono/.env`; never read from the repo, never logged.
- Fetchers: Firecrawl batch endpoint, or local httpx at ≤ 3 requests/s with `User-Agent: isnad-chrono/0.1 (+https://github.com/h9-tec/isnad-chrono)`; never request `/encyclopedia/*-preview/` or `/embed/`.
- Raw HTML cached at `data/raw/html/{hadith,rawi}/<id>.html`; a cached file is never re-fetched.
- Model constants (spec §3): `A0 = 8`, `MU_AGE = 68.0`, `SD_AGE = 14.0`, `AGE_MIN = 20`, `AGE_MAX = 100`, `GAP_THRESHOLD = 0.05`, `SUSPECT_THRESHOLD = 0.2`, `CONFLICT_YEARS = 20`; all in `isnad/constants.py`.
- Explicit audition terms: `{"حدثنا","حدثني","أخبرنا","أخبرني","سمعت","سمعنا","أنبأنا","أنبأني","قرأت على","قرئ على"}`; ambiguous: `{"عن","أن","قال","ذكر","روى","يرويه", None}`.
- Released data = IDs, years, scores, verdicts only; no hdith.com text columns in any released parquet.
- Commits: conventional prefixes, no Co-Authored-By trailers.

## Review Focus

1. A narrator page whose `person.death` is a caliphate phrase ("في خلافة عبد الملك بن مروان") and `death_num` is null: `parse_year` must return the caliphate interval, not `kind="none"` (Task 2 test `test_era_phrase`).
2. A hadith whose `isnad` has the compiler as last link with `formula: null`: the compiler edge must still be emitted with term `None` and the chain must not be truncated (Task 3 test `test_compiler_edge_has_none_term`).
3. A hadith with `chain_type == "معلق"` or `entry_kind == "passage"`: edges emitted but tagged, never counted as sound positives (Task 3 `test_chain_type_kept`, Task 7 `test_positive_set_excludes_muallaq`).
4. A Firecrawl batch job that returns fewer documents than requested, or a document with `statusCode != 200`: the queue must mark only the delivered 200s as `ok`, the rest stay `pending`/`404` (Task 5 `test_batch_partial_result`).
5. Two narrators with the same `abbrev` name when resolving al-Marasil names: resolver returns `None` with `ambiguous=True`, never the first match (Task 8 `test_resolver_ambiguous`).

---

### Task 1: Scaffold + page-props extractor

**Files:**
- Create: `pyproject.toml`, `isnad/__init__.py`, `isnad/pageprops.py`, `tests/test_pageprops.py`, `tests/conftest.py`
- Existing fixtures: `tests/fixtures/hadith_muslim_11563.html`, `tests/fixtures/hadith_muslim_11558_nochain.html`, `tests/fixtures/rawi_4494.html`

**Interfaces:**
- Produces: `pageprops.extract(html: str) -> dict` (the `props` dict of the Inertia JSON); `pageprops.component(html: str) -> str` (e.g. `"Encyclopedia/Rawi/Show"`, `"Encyclopedia/BookHadith/Show"`). Raises `pageprops.NoPageData` when the script tag is absent.
- `conftest.py`: fixture `fx(name) -> str` returning fixture file text.

- [ ] **Step 1: Write `pyproject.toml`** with `[project] name="isnad-chrono" requires-python=">=3.12"`, deps `pandas>=2.2, pyarrow>=16, httpx>=0.27`, dev deps `pytest, pytest-httpx`; `uv sync`.
- [ ] **Step 2: Write failing tests**

```python
def test_extract_rawi_props(fx):
    p = extract(fx("rawi_4494.html"))
    assert p["person"]["slug"] == "p-4494"
    assert component(fx("rawi_4494.html")) == "Encyclopedia/Rawi/Show"

def test_extract_hadith_props(fx):
    p = extract(fx("hadith_muslim_11563.html"))
    assert p["hadith"]["id"] == 11563 and len(p["hadith"]["isnad"]) == 7

def test_no_page_data():
    with pytest.raises(NoPageData): extract("<html></html>")
```

- [ ] **Step 3: Run** `uv run pytest tests/test_pageprops.py -v` → FAIL (ImportError).
- [ ] **Step 4: Implement** `extract` and `component` in `isnad/pageprops.py`: regex `<script data-page="app" type="application/json">(.*?)</script>` with DOTALL, `json.loads`, return `["props"]` / `["component"]`.
- [ ] **Step 5: Run** tests → PASS.
- [ ] **Step 6: Commit** `feat: scaffold and Inertia page-props extractor`.

### Task 2: Hijri date parser

**Files:**
- Create: `isnad/dates.py`, `tests/test_dates.py`

**Interfaces:**
- Produces: `parse_year(text: str | None, num: int | None = None) -> Year` where `Year` is a frozen dataclass `(year: float | None, sd: float | None, kind: str)`, `kind ∈ {"exact","alt","approx","after","before","era","none"}`. If `num` (hdith's `death_num`) is given and text has no better info, return `(num, 1.0, "exact")`.
- `narrative_years(text: str) -> list[int]`: every `مات|توفي|وفاته|هلك … سنة <words or digits>` occurrence converted to an int in [1, 400].
- `CALIPHATES: dict[str, tuple[int,int]]` with at least: عبد الملك بن مروان (65,86), الوليد بن عبد الملك (86,96), سليمان بن عبد الملك (96,99), عمر بن عبد العزيز (99,101), يزيد بن عبد الملك (101,105), هشام بن عبد الملك (105,125), المنصور (136,158), المهدي (158,169), هارون الرشيد (170,193), المأمون (198,218), معاوية (41,60), عثمان (23,35), عمر بن الخطاب (13,23), أبو بكر (11,13). Era → `year = midpoint`, `sd = (hi-lo)/4`, kind `"era"`.

- [ ] **Step 1: Write failing tests** (values pinned):

```python
@pytest.mark.parametrize("txt,num,exp", [
  ("58هـ", None, (58, 1.0, "exact")),
  ("١٠٦ أو ١٠٨", None, (107, 2.0, "alt")),
  ("نحو ١٣٠", None, (130, 5.0, "approx")),
  ("بعد ١٢٠", None, (123, 5.0, "after")),
  ("قبل ١٠٠", None, (97, 5.0, "before")),
  ("مات سنة ست وثمانين ومائة", None, (186, 1.0, "exact")),
  ("في خلافة عبد الملك بن مروان", None, (75.5, 5.25, "era")),
  (None, 93, (93, 1.0, "exact")),
  ("ولد على عهد النبي", None, (None, None, "none")),
])
def test_parse_year(txt, num, exp):
    y = parse_year(txt, num); assert (y.year, y.sd, y.kind) == exp

def test_narrative_years():
    s = "وقال ابن سعد: توفي بالمدينة سنة أربع ومائة. وقيل مات سنة 103"
    assert narrative_years(s) == [104, 103]

def test_era_phrase():  # Review Focus 1
    assert parse_year("في خلافة عبد الملك بن مروان").kind == "era"
```

- [ ] **Step 2: Run** → FAIL. 
- [ ] **Step 3: Implement** in `isnad/dates.py`: normalise Arabic-Indic digits to ASCII; number-word table (units, tens, مائة/مئة/مائتين/ثلاثمائة, with و-prefix stripping, compound sums); qualifier detection (نحو/تقريبا/~ → approx; بعد/> → after +3; قبل/< → before −3; أو/or/slash → alt, sd = max(2, range/2)); caliphate lookup by substring. Port the spike's `dates.py` logic for the English forms too (muslimscholars strings are not used in v1, but the test cases above are the contract).
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: hijri date parser with uncertainty kinds`.

### Task 3: Hadith parser → records + edges

**Files:**
- Create: `isnad/parse_hadith.py`, `tests/test_parse_hadith.py`

**Interfaces:**
- Consumes: `pageprops.extract`.
- Produces: `parse_hadith(html: str) -> HadithRecord` with fields `hadith_id:int, book_slug:str, book_title:str, number:str|None (numbering_harf), entry_kind:str, chain_type:str|None, grading:list[dict] (raw hadith["grading"]), chain:list[ChainLink]`; `ChainLink(rawi_id:int, position:int, formula:str|None, reliability:str|None, dates:str|None, flags:list[str])` where `rawi_id = int(slug[2:])`, `position` 0 = earliest narrator.
- `edges(rec: HadithRecord) -> list[Edge]`, `Edge(teacher_id:int, student_id:int, hadith_id:int, position:int, term:str|None, chain_type:str|None, entry_kind:str)`; edge i links chain[i] → chain[i+1], `term = chain[i+1].formula` (the student's formula describes how they received from the teacher).

- [ ] **Step 1: Write failing tests**

```python
def test_chain_order_and_ids(fx):
    r = parse_hadith(fx("hadith_muslim_11563.html"))
    assert [l.rawi_id for l in r.chain] == [2651, 3234, 1580, 2779, 6792, 3889, 6116]
    assert r.book_slug == "b-2" and r.hadith_id == 11563 and r.chain_type == "معلق"

def test_edges_terms(fx):
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert len(e) == 6
    assert (e[0].teacher_id, e[0].student_id, e[0].term) == (2651, 3234, "عن")
    assert (e[3].teacher_id, e[3].student_id, e[3].term) == (2779, 6792, "حدثنا")

def test_compiler_edge_has_none_term(fx):  # Review Focus 2
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert (e[-1].teacher_id, e[-1].student_id, e[-1].term) == (3889, 6116, None)

def test_no_chain_passage(fx):
    r = parse_hadith(fx("hadith_muslim_11558_nochain.html"))
    assert r.entry_kind == "passage" and r.chain == [] and edges(r) == []

def test_chain_type_kept(fx):  # Review Focus 3
    assert all(x.chain_type == "معلق" for x in edges(parse_hadith(fx("hadith_muslim_11563.html"))))
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** dataclasses + functions. **Step 4: Run** → PASS. **Step 5: Commit** `feat: hadith page parser and edge extraction`.

### Task 4: Narrator parser

**Files:**
- Create: `isnad/parse_rawi.py`, `tests/test_parse_rawi.py`

**Interfaces:**
- Consumes: `pageprops.extract`, `dates.parse_year`, `dates.narrative_years`.
- Produces: `parse_rawi(html: str) -> RawiRecord` with fields: `rawi_id:int, name:str, abbrev:str|None, kunya:str|None (patronymic), lineage:str|None, generation:str|None, generation_num:int|None, birth_text, death_text, death_num:int|None, death:Year (parse_year(death_text, death_num)), birth:Year, birth_city, death_city, living_city, ibn_hajar:str|None, dhahabi:str|None, is_companion:bool, teachers:list[tuple[int, int|None]] (rawi_id, death), students:list[tuple[int,int|None]], sama_confirmed:list[int] (teacher ids from rulings.sama where kind startswith "إثبات"), flags:list[str] (rulings.flags[].type), opinions:list[Opinion] (scholar, scholar_id:int|None, scholar_death:int|None, statement, classification:int, bucket), narrative_years:list[int] (from all biographies[].content + opinions[].statement), tuhfa_entries:list[str] (content of biographies whose book == "تحفة التحصيل في المراسيل"), name_forms:list[str]`.

- [ ] **Step 1: Write failing tests**

```python
def test_rawi_card(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert r.rawi_id == 4494 and r.abbrev == "علقمة بن وقاص العتواري"
    assert r.death.kind == "era" and 70 < r.death.year < 80
    assert r.living_city == "المدينة" and r.ibn_hajar == "ثقة ثبت"

def test_rawi_relations(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert (3026, 57) in r.teachers and len(r.teachers) == 13 and len(r.students) == 9
    assert r.sama_confirmed == [4677, 3026, 5917, 5443, 4868, 3799]
    assert r.flags == ["الإرسال"]

def test_rawi_opinions_and_text(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert len(r.opinions) == 19 and r.opinions[0].scholar == "الواقدي" and r.opinions[0].scholar_death == 207
    assert any("تحفة" in b for b in [ "تحفة التحصيل في المراسيل" ]) and len(r.tuhfa_entries) == 1
    assert "علقمة بن وقاص" in r.name_forms
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**. **Step 4: Run** → PASS. **Step 5: Commit** `feat: narrator page parser`.

### Task 5: Fetch queue, sitemaps, Firecrawl + local fetchers

**Files:**
- Create: `isnad/fetch.py`, `isnad/cli.py` (argparse entry `python -m isnad.cli fetch ...`), `tests/test_fetch.py`

**Interfaces:**
- `Queue(db_path)` over sqlite table `pages(url TEXT PRIMARY KEY, kind TEXT, id INTEGER, book TEXT, status TEXT, path TEXT, fetched_at TEXT, http_status INTEGER)`; methods `add(url, kind, id=None, book=None)`, `pending(kind=None, book=None, limit=None) -> list[str]`, `mark(url, status, path=None, http_status=None)`, `counts() -> dict[str,int]`.
- `load_sitemaps(client) -> Iterator[tuple[str, str]]` yields `(url, kind)` for `sitemap-rawis.xml` (kind `"rawi"`, id from `p-N`) and `sitemap-hadiths-*.xml` (kind `"hadith_slug"`, url `/h/<slug>`).
- `resolve_slug(client, url) -> str | None`: HEAD/GET without following redirects, returns the `Location` (`/encyclopedia/book/b-N/h/<id>`), or None on 404. Queue stores the resolved URL with kind `"hadith"`, id, book.
- `FirecrawlFetcher(api_key, client).fetch(urls: list[str]) -> dict[str, tuple[int, str]]` (url → (status, rawHtml)) using `POST /v2/batch/scrape` with `{"urls": [...], "formats": ["rawHtml"]}` then polling `GET /v2/batch/scrape/{id}` until `status == "completed"`, following `next` pages; batches of 100.
- `LocalFetcher(client, rate=3.0).fetch(urls)` same return; token-bucket sleep; retries 3× with backoff on 5xx/timeouts.
- `run_fetch(queue, fetcher, kind, book=None, limit=None, cache_root="data/raw/html")`: writes `<cache_root>/<kind>/<id>.html`, marks `ok`/`404`/`error`. Skips urls whose cache file exists (marks `ok`).

- [ ] **Step 1: Write failing tests** (use `pytest-httpx` to mock):

```python
def test_sitemap_enumeration(httpx_mock): ...  # 2 rawi urls + 2 slug urls → 4 queue rows with kinds
def test_resolve_slug_redirect(httpx_mock): ...  # 302 Location → kind hadith, id 11563, book b-2
def test_batch_partial_result(httpx_mock, tmp_path):  # Review Focus 4
    # batch of 3 urls; API returns 2 docs (one 200, one 404) → statuses ok, 404, pending
def test_cache_skip(tmp_path): ...  # existing file → no fetch call, status ok
def test_local_rate_limit(httpx_mock): ...  # 6 urls at rate 3/s take >= 1.5s
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**. **Step 4: Run** → PASS.
- [ ] **Step 5: CLI**: `fetch sitemaps`, `fetch resolve [--limit]`, `fetch run --kind rawi|hadith [--book b-2] [--fetcher firecrawl|local] [--limit]`, `fetch status` (prints `counts()`). Read key from `~/.config/isnad-chrono/.env`.
- [ ] **Step 6: Smoke run**: `fetch sitemaps` then `fetch run --kind rawi --limit 20 --fetcher firecrawl` → 20 files in `data/raw/html/rawi/`, `fetch status` shows `ok: 20`. (Costs 20 credits.)
- [ ] **Step 7: Commit** `feat: fetch queue with sitemap enumeration and Firecrawl/local fetchers`.

### Task 6: Build parquet tables

**Files:**
- Create: `isnad/build.py`, `tests/test_build.py`; CLI subcommand `build`.

**Interfaces:**
- `build_rawi(cache_root, out="data/rawi.parquet") -> int` rows; columns = RawiRecord scalars + list columns (`teachers_ids`, `students_ids`, `sama_confirmed`, `flags`, `narrative_years`, `name_forms`) + `death_year, death_sd, death_kind, birth_year, birth_sd, birth_kind`; opinions to `data/opinions.parquet` (rawi_id, scholar_id, scholar_death, classification, bucket, statement); tuhfa entries to `data/tuhfa.parquet` (rawi_id, content).
- `build_hadith(cache_root, out_h="data/hadith.parquet", out_e="data/edges.parquet") -> tuple[int,int]`; edges columns = Edge fields.
- Parse failures are logged to `data/build_errors.csv` (path, error) and skipped; the function never raises on one bad page.

- [ ] **Step 1: Tests**: copy the three fixtures into `tmp_path/raw/html/{hadith,rawi}/`, run both builders, assert row counts (rawi 1, hadith 2, edges 6) and that a corrupt file (`bad.html` = "<html>") lands in `build_errors.csv` without raising.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**. **Step 4: Run** → PASS. **Step 5: Commit** `feat: build parquet tables from cached pages`.

### Task 7: Scoring

**Files:**
- Create: `isnad/constants.py`, `isnad/score.py`, `tests/test_score.py`; CLI `score`.

**Interfaces:**
- `p_meet(t_death: Year, s_birth: Year, s_death: Year) -> tuple[float|None, str]` per spec §3 (closed form with `math.erf`; `how ∈ {"birth_known","birth_imputed","no_dates"}`). Era years use their `sd`.
- `date_conflict(death_year: float|None, narrative_years: list[int]) -> bool` (min |diff| ≥ `CONFLICT_YEARS`).
- `sama_evidence(term: str|None, teacher_id: int, student: RawiRow, denials: set[tuple[int,int]]) -> dict` with keys `confirmed:bool, explicit_term:bool, ambiguous_term:bool, denied:bool, irsal:bool, tadlis:bool`.
- `verdict(p: float|None, conflict_t: bool, conflict_s: bool, ev: dict) -> str` in `{"data_error","denied_by_critic","chronology_gap","suspect","ok","no_dates"}` (`no_dates` when p is None; spec table otherwise, in order).
- `score_edges(edges.parquet, rawi.parquet, denials: set) -> edge_scores.parquet` with columns: all Edge fields + `p_meet, how, conflict_t, conflict_s, confirmed, explicit_term, ambiguous_term, denied, irsal, tadlis, verdict`.

- [ ] **Step 1: Tests**

```python
def test_regression_sulaym_miqdad():  # Miqdad d.33 exact; Sulaym d.130 exact, birth unknown
    p,_ = p_meet(Year(33,1,"exact"), Year(None,None,"none"), Year(130,1,"exact")); assert p < 0.05
def test_explicit_bukhari_edge():  # Sufyan d.197, Humaydi b.? d.219
    p,_ = p_meet(Year(197,1,"exact"), Year(None,None,"none"), Year(219,1,"exact")); assert p > 0.9
def test_birth_known_beats_imputed(): ...
def test_conflict(): assert date_conflict(106, [186, 86]) is True and date_conflict(117, [117, 118]) is False
def test_verdict_order(): ...  # conflict wins over denied wins over gap
def test_positive_set_excludes_muallaq(): ...  # helper positives(df) drops chain_type=="معلق" and ambiguous terms (Review Focus 3)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; port the spike's `score.py`. **Step 4: Run** → PASS. **Step 5: Commit** `feat: chronology score, conflict flag, sama evidence, verdicts`.

### Task 8: Gold sets and name resolution

**Files:**
- Create: `isnad/gold.py`, `gold/marasil_pairs.json` (copy of `~/research/sanad-spike/marasil_pairs_all.json`), `gold/tuhfa_prompt.txt`, `tests/test_gold.py`; CLI `gold`.

**Interfaces:**
- `NameIndex.from_rawi(rawi.parquet)`: maps normalised Arabic tokens → rawi_ids using `name`, `abbrev`, `name_forms`. `resolve(name: str) -> Resolution(rawi_id:int|None, score:float, ambiguous:bool, candidates:list[int])`; normalisation and token scorer as in the spike (`أ/إ/آ→ا, ة→ه, ى→ي`, strip diacritics, drop بن/ابو), score = overlap/len(query) − 0.15·extra/len(cand) + 0.3 if first tokens equal; accept ≥ 0.6; `ambiguous=True` when top two scores tie.
- `marasil_denials(index) -> DataFrame(student_id, teacher_id, relation, authority, resolved:bool, ambiguous:bool)`.
- `tuhfa_denials(tuhfa.parquet, index, runner=claude_p) -> DataFrame(student_id, teacher_id, relation, quote)`: each `tuhfa_entries` content is already attached to `student_id`; the prompt (spec: same schema as al-Marasil extraction) extracts teacher names + relation; teacher names resolved with the index. `runner` is injectable so tests use a fake.
- `denial_set(df_list) -> set[tuple[int,int]]` for Task 7.

- [ ] **Step 1: Tests**: `test_resolver_exact` (abbrev match → id), `test_resolver_ambiguous` (two rawi rows with identical abbrev → `rawi_id is None and ambiguous`) [Review Focus 5], `test_marasil_denials_shape`, `test_tuhfa_fake_runner`.
- [ ] **Step 2–4**: FAIL → implement → PASS. **Step 5: Commit** `feat: gold denial sets with name resolution`.

### Task 9: Validation metrics and figures

**Files:**
- Create: `isnad/validate.py`, `tests/test_validate.py`; CLI `validate`.

**Interfaces:**
- `positives(scores: DataFrame, books=("b-1","b-2")) -> DataFrame` = edges in those books with `explicit_term` and `chain_type != "معلق"`, plus `confirmed` pairs.
- `negatives(denials_df, scores_df) -> DataFrame` per relation class with each pair's `p_meet` (looked up from rawi dates even if the pair is not an edge).
- `auroc(pos: Series, neg: Series) -> float` (rank-based, no sklearn).
- `metrics(scores, denials) -> dict` = `{class: {auroc, n, recall@0.05, recall@0.1, recall@0.2}, false_flag_rate@thr, verdict_counts_by_book, coverage{how, death_kind}}` written to `data/metrics.json`; `figures/` PNGs via matplotlib (add to deps in this task).

- [ ] **Step 1: Tests** on synthetic frames: `test_auroc_perfect == 1.0`, `test_auroc_random ≈ 0.5`, `test_positives_filter`, `test_metrics_keys`.
- [ ] **Step 2–4**: FAIL → implement → PASS. **Step 5: Commit** `feat: validation metrics`.

### Task 10: Report tables

**Files:**
- Create: `isnad/report.py`, `tests/test_report.py`; CLI `report`.

**Interfaces:**
- `weak_edges(scores, rawi, n=50) -> DataFrame` columns `teacher_id, teacher_abbrev, teacher_death, student_id, student_abbrev, student_birth, student_death, p_meet, term, n_hadith, example_hadith_ids(3), verdict` sorted by p_meet asc, only `verdict in {"chronology_gap","suspect"}` → `data/weak_edges.csv`.
- `date_errors(rawi) -> DataFrame` rows with `conflict` = True: `rawi_id, abbrev, death_year, death_kind, narrative_years, diff` → `data/date_errors.csv`.
- `run_report(queue, tables) -> str` markdown summary of fetch counts, rows, coverage, verdict counts; printed and saved to `data/run_report.md`.

- [ ] **Step 1: Tests** on synthetic frames (sorting, filtering, column set). **Step 2–4**: FAIL → implement → PASS. **Step 5: Commit** `feat: report tables`.

### Task 11: Stage 1 + 2 runs (narrators, Six Books)

**Files:** none new; operational checkpoints recorded in `docs/runs/2026-10-xx-stage1.md`.

- [ ] **Step 1:** `fetch sitemaps`; `fetch status` → rawi pending ≈ 20,777.
- [ ] **Step 2:** `fetch run --kind rawi --fetcher firecrawl` (≈ 21k credits). Check `fetch status`: ok ≥ 20,600, record 404/error counts.
- [ ] **Step 3:** `build rawi` → `data/rawi.parquet`; run report shows death_kind coverage; expected ≥ 60% non-`none`.
- [ ] **Step 4:** `fetch resolve` for all slugs (local, free); `fetch run --kind hadith --book b-1 --fetcher firecrawl`, then b-2, b-3 (Abu Dawud), b-4 (Tirmidhi), b-5 (Nasa'i), b-6 (Ibn Majah) — confirm the slug→book mapping from `books.md` before each (book ids beyond b-2 are not verified yet).
- [ ] **Step 5:** `build hadith`; `gold`; `score`; `validate`; `report`. Record metrics.json headline numbers in the run doc.
- [ ] **Step 6: Commit** run docs `docs: stage 1-2 run record`.

### Task 12: Stage 3 queue + release prep

**Files:**
- Create: `isnad/export.py` (HF dataset export: `edges`, `edge_scores`, `rawi_dates` with ID/year/score/verdict columns only), `README.md`, `DATASET_CARD.md`, `paper/outline.md`.

- [ ] **Step 1:** `export.py` test: output parquet schemas contain no column from a denylist (`name, abbrev, statement, content, matn, fullname, *_text`).
- [ ] **Step 2:** Implement; `uv run python -m isnad.cli export` → `release/`.
- [ ] **Step 3:** Start stage 3: `fetch run --kind hadith --book <next> --fetcher firecrawl` while credits last, then `--fetcher local` (≤ 3 req/s) for the rest; run as a detached background job with `fetch status` logged hourly.
- [ ] **Step 4:** `paper/outline.md` with the four claims (spec §5) and the tables each needs; `README.md` with setup, pipeline commands, licensing note (derived data only, cite hdith.com).
- [ ] **Step 5: Commit** `feat: release export, docs, paper outline`.

---

## Self-review notes

- Spec coverage: §2.1 (T1,3,4,6), §2.2 (T5,11,12), §2.3 (T2,3,4), §3 (T7), §4 (T8,9; Jamiʿ al-Tahsil replaced by Tuhfat al-Tahsil entries already attached per narrator on hdith.com — a superset of al-ʿAlaʾi, and no name resolution needed for the student side; spec §4 updated by this plan), §5 (T12 outline), §6 (T1,12), §7 (T5 cache + fetcher swap, T12 denylist).
- Types: `Year`, `HadithRecord`, `ChainLink`, `Edge`, `RawiRecord`, `Opinion`, `Resolution` named consistently across tasks.
- Unverified facts to confirm during T11: book slugs for the Six Books other than b-2; `person.death_num` semantics (int year) across companions; whether `/h/<slug>` redirects are 301/302.
