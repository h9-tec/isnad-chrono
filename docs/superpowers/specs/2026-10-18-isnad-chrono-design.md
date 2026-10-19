# isnad-chrono: chronology-based meeting probability for every isnad edge

Date: 2026-10-18. Status: approved in conversation (sections 1-4). Spike evidence: ~/research/sanad-spike/REPORT.md.

## 1. Goal and deliverables

Score every teacher→student edge in the isnads of hdith.com's hadith corpus by the probability the two narrators could have met, from narrator death/birth years with uncertainty, combined with textual sama' evidence. Validate against classical critics' denials. Deliver, in order:

1. Open dataset on Hugging Face: `edges`, `edge_scores`, `rawi_dates` (IDs, years, scores, verdicts). No hdith.com text is redistributed.
2. Paper (arXiv) with the four claims in §5.
3. Thin web tool later, out of scope for v1.

Scope of fetch: all 245 books (612,548 hadith) and all 20,777 narrators, staged by credits (§2.2). Scope of the paper's main results: the Six Books.

## 2. Pipeline

### 2.1 Data flow

```
sitemaps (free) ──> fetch queue (sqlite: url, kind, status, fetched_at, path)
      │
Firecrawl batch scrape (rawHtml), or local crawler ──> data/raw/html/{hadith,rawi}/<id>.html  (cached, never re-fetched)
      │
parse_hadith ──> hadith.parquet (hadith_id, book_id, number, grade, chain[(rawi_id, term, position)])
             ──> edges.parquet  (teacher_id, student_id, hadith_id, term, position)
parse_rawi   ──> rawi.parquet   (rawi_id, name, kunya, nisba, tabaqa, birth_text, death_text,
                                 death_year, death_sd, death_kind, death_place, places[],
                                 teachers[], students[], sama_confirmed[], flags{irsal,tadlis,ikhtilat,...},
                                 critic_quotes[(critic, critic_death, text, class)], narrative_years[])
score   ──> edge_scores.parquet (edge key, p_meet, how, date_conflict, sama_evidence, verdict)
validate ──> metrics.json, figures/
report  ──> weak_edges.csv, date_errors.csv, paper tables
```

Plain Python, parquet files, no database except the fetch queue. One script per stage, each re-runnable from cache.

### 2.2 Fetching

- Enumeration: `sitemap-rawis.xml` (20,777 URLs) and `sitemap-hadiths-{1..6}.xml` (`/h/<slug>` URLs, resolved by following the redirect to `/encyclopedia/book/b-N/h/<id>`).
- Fetcher A: Firecrawl v2 batch scrape, `formats=["rawHtml"]`, 1 credit/page. Key in `~/.config/isnad-chrono/.env` (`FIRECRAWL_API_KEY`), never in the repo.
- Fetcher B: local crawler, httpx, ≤3 req/s, honest User-Agent, retries with backoff. robots.txt allows all crawlers; `/encyclopedia/*-preview/` and `/embed/` are disallowed and never touched.
- Stages: (1) all narrators, 21k credits; (2) Six Books hadith, ~40k credits; (3) remaining 239 books, ~570k pages, by priority (Ahmad, Malik, Darimi, Ibn Hibban, Ibn Khuzayma, Sunan Kubra, then the rest), with Firecrawl as credits allow and fetcher B otherwise. The queue is keyed by URL so fetchers can be swapped mid-run.
- Every page's raw HTML is stored once; parsers never touch the network.

### 2.3 Parsing

- Both page types embed their data as JSON in `<script data-page="app" type="application/json">`; parsers read that JSON (`props.hadith.isnad[]` with `slug`, `formula`, `chain_type`; `props.person`, `props.rulings`, `props.criticism`, `props.teachers/students`, `props.biographies`), never the HTML.
- `parse_rawi`: structured card fields (الاسم, الكنية, النسب, الميلاد, الوفاة, بلد الوفاة, بلد الإقامة, الطبقة, مرتبة ابن حجر, مرتبة الذهبي), "أحكام نقدية خاصة" (إثبات سماع list, الإرسال/التدليس/الاختلاط flags), teachers/students links with IDs, critic statements with their class (تعديل/متوسط/جرح).
- `dates.py`: Hijri phrase → (year, sd, kind). Handles digits (Arabic-Indic and ASCII), Arabic number words incl. compound ("ست وثمانين ومائة"), ranges/alternatives ("١٠٦ أو ١٠٨"), qualifiers ("نحو", "بعد", "قبل"), and era phrases ("في خلافة عبد الملك" → interval from a caliphate table). Returns `kind ∈ {exact, alt, approx, after, before, era, none}`.
- Narrative years: every "مات/توفي ... سنة ..." in critic quotes parsed with the same function → `narrative_years[]`.

## 3. Scoring model

Per edge T→S, three signals kept separate:

1. **p_meet**: P(S was ≥ A0 = 8 lunar years old before T died). Birth of S known → use it; unknown → imputed as death_S − Age, Age ~ N(68, 14) (bounds [20, 100] defined, not applied in v1). Death years carry sd from `kind` (exact 1, alt half-range ≥2, approx 5, after/before +3 ±5, era = interval). `how ∈ {birth_known, birth_imputed, no_dates, missing_rawi}` (`missing_rawi`: the teacher or student row is absent from rawi.parquet; `no_dates`: both rows present but too undated to score).
2. **date_conflict**: structured death_year vs narrative_years differ by ≥ 20 → flag on that narrator; any edge touching it is a data error, not a gap.
3. **sama_evidence**: `confirmed` if T ∈ S.sama_confirmed; `explicit_term` if the link term (the teacher node's formula, i.e. the word printed before T's name) ∈ {حدثنا, حدثني, أخبرنا, سمعت, …}; `ambiguous_term` for عن/أن/قال; `denied` if a critic denial exists for (S, T) in the gold sets; S-level flags irsal/tadlis.

Verdict, first match wins:

| condition | verdict |
|---|---|
| date_conflict on T or S | data_error |
| denied by critic | denied_by_critic |
| p_meet unknown (how ∈ {no_dates, missing_rawi}) | no_dates |
| p_meet < 0.05 | chronology_gap |
| p_meet < 0.2 and ambiguous_term and S has irsal or tadlis | suspect |
| else | ok |

All constants in `isnad/constants.py`. Sensitivity reported at 0.05 / 0.1 / 0.2. Out of scope: learned thresholds, graph-structure features, matn text.

## 4. Validation

Gold negatives: (a) al-Marasil, 1,011 pairs already extracted (student, teacher, relation ∈ {no_sama, mursal, no_idrak, sama}, authority, quote); (b) Tuhfat al-Tahsil (Abu Zurʿa al-ʿIraqi, a superset of al-ʿAlaʾiʼs Jamiʿ al-Tahsil), whose entries hdith.com attaches per narrator page, so the student side needs no name resolution; (c) hdith.com irsal flags. Gold positives: Bukhari/Muslim edges whose term is an explicit audition term; عن-edges are excluded from positives. hdith.com `sama_confirmed` pairs are additional positives.

Name resolution for (a) and (b): Arabic name → hdith.com rawi_id via the narrator name index, token-overlap scorer from the spike with first-token bonus; score < 0.6 or tie → ambiguous → excluded from metrics (counted and reported).

Metrics per negative class and threshold: AUROC of p_meet; recall of denials; false-flag rate on positives; Six-Book verdict counts; top-50 chronology_gap edges with a one-line manual check.

## 5. Paper claims (in evidence order)

1. Chronology with uncertainty reproduces classical no_idrak judgements (spike: AUROC 0.81 on Sahih Muslim).
2. It cannot reproduce no_sama for contemporaries (spike: 0.57); textual sama' evidence gives the lift, quantified.
3. It finds date errors in widely used rijal data (century-dropped pattern; counts and examples).
4. Per-edge, explainable, no training; contrast with IsnadGuard (ICML 2026, structure-only).

## 6. Repo, testing, errors, release

```
~/isnad-chrono/
  pyproject.toml   (uv; python 3.12; pandas, pyarrow, httpx, lxml, pytest)
  isnad/{fetch,parse_hadith,parse_rawi,dates,score,gold,validate,report,constants}.py
  tests/           fixtures: one saved HTML per page type; unit tests per parser and for dates.py
  data/raw/html/   gitignored cache; data/*.parquet gitignored
  paper/
```

- TDD on parsers and dates.py. Scorer regression tests: Sulaym b. ʿAmir ← al-Miqdad < 0.05; a حدثنا edge in Bukhari 1 > 0.9.
- Fetch queue records status per URL (ok / 404 / parse_fail); parsers log and skip bad pages; each run prints counts per status.
- Release: GitHub `h9-tec/isnad-chrono` (MIT, code only). HF dataset with IDs/years/scores/verdicts only. No Claude commit trailers.
- v1 excludes: web tool, matn text, model training, the muslimscholars.info cross-link (stretch goal after v1 numbers are stable).

## 7. Risks

- hdith.com license unstated: redistribute derived numbers only; cite the site; contact them before the HF release.
- Firecrawl credits: 76k now; stages 1–2 fit; stage 3 needs an upgrade or the local crawler.
- Date phrase coverage: era phrases and "لم يذكر" cases; measured as `how`/`kind` coverage in the run report.
- Chain parsing edge cases: multiple isnads per hadith ("ح" transfers), compiler link at the end; handled by position and tested with fixtures.
