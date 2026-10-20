# Could They Have Met? Chronological Meeting Probabilities for Every Link in the Isnads of the Six Books

*Working title. Draft v0, 2026-10-20. Not for circulation.*

<!-- Number sources: every figure below is copied from data/metrics.json, data/run_report.md,
docs/runs/2026-10-20-stage{1,2}.md, data/weak_edges.csv, data/date_errors.csv, or printed by
paper/derived_numbers.py (read-only over data/ and gold/). Section-level source notes are given
in HTML comments. -->

## Abstract

A hadith reaches us through an isnad, a chain of narrators in which each person claims to have received the report from the one before. Classical critics tested these links one by one, and part of that test is chronological: a student cannot have heard from a teacher who died before the student was old enough to listen. We compute, for each of the 190,254 teacher-to-student links in the isnads of the Six Books on hdith.com, the probability that the student was at least eight lunar years old before the teacher died, using the site's narrator death and birth years with an explicit uncertainty for each kind of date. The model has no trained parameters. Against denials of contact recorded in Ibn Abi Hatim's *al-Marasil* and in *Tuhfat al-Tahsil*, the score separates "did not reach" (*no_idrak*) pairs from audition-attested links with AUROC 0.80 and 0.88, and *mursal* pairs with 0.90 and 0.88, while flagging 0.22% of attested links. It does not separate "did not hear" (*no_sama*) pairs between contemporaries (AUROC 0.63 and 0.65), and our current textual evidence adds only two to four points of recall there. We release per-link scores and verdicts as derived numbers, and report what the flagged links reveal about the narrator database.

## 1 Introduction

The isnad is the part of a hadith report that names who transmitted it: "A told us, from B, from C, that the Prophet said ...". Muslim scholars of the second and third Islamic centuries developed a detailed practice for judging such chains, and one of its basic questions is whether each link is *muttasil* (connected), meaning that the later narrator actually received the report from the earlier one. Critics answered this question pair by pair, and wrote their answers down. Works such as Ibn Abi Hatim's *al-Marasil* and Abu Zurʿa al-ʿIraqi's *Tuhfat al-Tahsil* collect statements of the form "X did not hear from Y", "X did not reach Y", or "X's narration from Y is *mursal*".

A large part of this judgement rests on dates. If Y died before X was born, the link is broken whatever the transmission formula says. Modern digital corpora now record, for tens of thousands of narrators, death years, some birth years, and the full chain of every hadith in the major collections. That makes it possible to apply the chronological test to every link at once, which no critic did and no existing computational work does.

Computational work on isnads so far has focused on chain structure: extracting narrator sequences from text, building transmission graphs, and learning which structural patterns indicate fabrication (Section 2.4). Structure-only methods give a score per chain but cannot say which link is weak or why. A per-link chronological score answers a narrower question, and answers it in terms a hadith scholar already uses.

This paper makes four contributions, stated with the strength the evidence supports:

1. **A per-link meeting probability with stated uncertainty.** For each teacher-to-student link we compute the probability that the student was at least eight lunar years old before the teacher died. Each date carries a standard deviation that depends on how it is recorded (exact, alternative years, approximate, "after", "before", or a caliphate era), and missing birth years are imputed from a lifespan prior. The closed form has no trained parameters (Section 4).
2. **Validation against classical denials.** On pairs denied by two classical sources, the score reproduces "did not reach" and *mursal* judgements well (AUROC 0.79 to 0.90, row- and pair-level) and "did not hear" judgements poorly (0.61 to 0.65), as a chronological test should. False flags on audition-attested links are rare (0.22% of rows at the default threshold) (Section 5.1).
3. **A measured, and small, contribution from textual evidence.** Adding the transmission formula and the student's known habit of *irsal* or *tadlis* raises recall on in-corpus "did not hear" pairs by 2.5 to 4.2 points. We report this lift with a matched denominator and separate it from the circular gain obtained when the critics' denials themselves feed the verdict (Section 5.2).
4. **An audit of the narrator data.** Links flagged as chronologically impossible point to specific records with implausible dates, and a cross-check of structured death years against years mentioned in the narrator's own biography text flags 934 narrators. We show that over half of these 934 are an artefact of the classical habit of writing years without the century, so the cross-check overstates the error rate; the flagged links are the more useful audit (Sections 5.4 and 6).

We release, for the Six Books, the link table, the per-link scores and verdicts, and narrator dates as identifiers and numbers only (Section 8).

## 2 Background

### 2.1 The isnad

A hadith report consists of the isnad and the *matn* (the text). In the canonical collections the isnad begins with the compiler's own teacher and ends with a Companion of the Prophet or another early source. Each adjacent pair is a link from a teacher (the earlier narrator) to a student (the later one). Collections often merge or branch chains: the letter *ḥāʾ* (ح) marks a switch to a parallel chain, and a compiler may omit the start of a chain (*taʿlīq*, giving a *muʿallaq* report). Our parser keeps these structures and tags *muʿallaq* links so they are never used as positive examples (Section 4.6).

### 2.2 Transmission formulae: *samāʿ* and *ʿanʿana*

Each link is introduced by a formula, printed before the teacher's name. Some formulae state direct reception: *ḥaddathanā* ("he told us"), *akhbaranā* ("he informed us"), *samiʿtu* ("I heard"). Others do not: *ʿan* ("from"), *anna* ("that"), *qāla* ("he said"). A chain built from *ʿan* is called *muʿanʿan*. Whether a *muʿanʿan* link counts as connected was itself a classical debate. In the introduction to his *Ṣaḥīḥ*, Muslim held that contemporaneity with the possibility of meeting is enough, provided the narrator is not known to conceal gaps; the stricter position, associated with ʿAlī b. al-Madīnī and al-Bukhārī, requires evidence that the two met at least once. A chronological score is a quantitative version of the necessary condition shared by both positions: if the two could not have overlapped, neither position accepts the link.

### 2.3 *Mursal*, *munqaṭiʿ*, and the critics' literature

A chain with a missing link is broken. In early usage *mursal* covers several kinds of break; in later technical usage it usually means a Successor citing the Prophet directly, while *munqaṭiʿ* names a break further down the chain. Two narrator traits make breaks likely: *irsāl* (a habit of citing people one did not hear from) and *tadlīs* (presenting a report with an ambiguous formula so that an intermediary is hidden).

Critics recorded their judgements on specific pairs. Ibn Abi Hatim al-Razi's *al-Marasil* gathers statements, mostly from his father Abu Hatim and from Abu Zurʿa al-Razi, that a given narrator did not hear from, or did not reach, another. Al-ʿAlaʾi's *Jamiʿ al-Tahsil* compiled the narrators accused of *irsāl*, and Abu Zurʿa al-ʿIraqi's *Tuhfat al-Tahsil* extends it. <!-- [verify] death dates if added: Ibn Abi Hatim d. 327, al-ʿAlaʾi d. 761, Abu Zurʿa al-ʿIraqi d. 826 AH. --> In these sources we distinguish three negative relations: *no_idrak* ("did not reach him": the student was too young, or born after the teacher's death), *no_sama* ("did not hear from him", typically between contemporaries), and *mursal* (the narration from him is *mursal*). A fourth relation, *sama*, records explicit statements that the student did hear from the teacher.

### 2.4 Related computational work

Most computational isnad work treats the chain as a sequence or graph. Sanadset 650K (*Data in Brief*, 2022) provides narrator chains extracted from a large number of hadith books, with narrators given by name [verify: authors, exact counts]. Multi-IsnadSet (*Data in Brief*, 2024) gives a narrator graph for *Ṣaḥīḥ Muslim* with narrator identifiers [verify: authors]; we used it in a preliminary study (Section 4.7). IsnadGuard (ICML 2026) detects fabricated isnads from chain structure alone, reporting AUROC rising from 0.727 to 0.836 on 43,539 chains [verify: authors, exact setting]. "Crowdsourced Information Authentication: A Graph-based Model from the Science of Hadith" (ICML 2025) models hadith authentication as information verification over a transmission graph [verify: authors, scope]. These methods score chains or graphs; none of them scores an individual link by the chronology of the two people on it, and none is validated against the classical per-pair denials.

Benchmarks of model knowledge about Islamic sciences are a separate line: IslamicMMLU (arXiv 2603.23750, 2026) and FiqhQA (arXiv 2508.08287) test language models on question answering [verify: scope of each]. Our work does not evaluate language models; it uses one only to extract gold pairs from classical text (Section 4.6).

In Western scholarship, the isnad-cum-matn method of Motzki and others analyses the variants of a single report across chains to date its common source [verify: Motzki, *The Origins of Islamic Jurisprudence*, 2002]. Yanagihashi's monograph applies related source-critical analysis to legal hadith [verify: Yanagihashi, *Studies in Legal Hadith*, Brill 2019]. Those methods work report by report and use the matn; ours works link by link and uses only dates and formulae.

## 3 Data

<!-- Sources: docs/superpowers/specs/2026-10-18-isnad-chrono-design.md §2; docs/runs/2026-10-20-stage1.md;
docs/runs/2026-10-20-stage2.md; data/run_report.md; paper/derived_numbers.py §8. -->

**Source.** hdith.com is a public hadith encyclopedia covering 245 books (612,548 hadith by the site's sitemaps) and 20,777 narrators. Each hadith page lists its isnad as a sequence of narrator identifiers with the formula printed before each name; each narrator page gives structured fields (name, *kunya*, lineage, generation, birth and death as text, places), lists of teachers and students with identifiers, the critics' statements about the narrator, biography excerpts, a list of teachers from whom audition is confirmed (*ithbāt samāʿ*), flags for *irsāl*, *tadlīs* and *ikhtilāṭ*, and, where they exist, the narrator's entries from *Tuhfat al-Tahsil*. Both page types embed this data as JSON; our parsers read the JSON and never the rendered HTML.

**Fetch.** We fetched all 20,777 narrator pages and the hadith pages of the Six Books: al-Bukhari (book b-1), Muslim (b-2), Abu Dawud (b-3), al-Tirmidhi (b-4), al-Nasaʾi (b-5) and Ibn Maja (b-6). Book enumeration listed 34,995 hadith entries, excluding entries the site marks as passages (non-hadith text such as chapter headings and commentary). 34,816 hadith pages were fetched and parsed with no parse errors; 179 remain pending in the fetch queue (`data/run_report.md`). Per book, the parsed counts are b-1 7,324, b-2 7,651, b-3 5,259, b-4 4,335, b-5 5,780, b-6 4,467.

**Links.** Parsing yields 190,254 link rows (teacher, student, hadith, position, formula). A link that appears in many hadith appears once per hadith; we call these *rows*, and call a de-duplicated (teacher, student) combination a *pair*. 6,963 distinct narrators appear in Six-Book links.

**Dates.** A Hijri date parser maps each birth or death phrase to a year, a standard deviation and a *kind*: `exact`, `alt` (two or more alternative years), `approx` ("about"), `after`, `before`, `era` (a caliphate phrase such as "in the caliphate of ʿAbd al-Malik", mapped to the caliphate's interval), or `none`. It handles Arabic-Indic and ASCII digits, compound number words and ranges. Across all 20,777 narrators, 10,251 have a death year and 1,649 a birth year. Among narrators who appear in Six-Book links, the death kinds are exact 3,463, alt 564, after 162, era 85, approx 72, before 53, and none 2,370 (`metrics.json` → `coverage.death_kind`). The parser also extracts every year stated in a death phrase inside the critics' statements and biography excerpts ("he died in the year ..."); we call these *narrative years*.

**Formula classes.** Each link's formula is normalised (hamza forms unified, diacritics removed) and assigned to a class by prefix:

- *explicit*: forms of *ḥaddatha*, *akhbara*, *samiʿa*, *anbaʾa*, reading formulae (*qaraʾtu ʿalā*, *quriʾa ʿalā*), *saʾala*, *raʾaytu*, *shahidtu*, *kataba ilayya*, *qāla lī/lanā*, *laqiya*, *qultu*, *khaṭaba*, and the scribal abbreviations *nā*, *thanā*, *anā* (matched exactly so that the name Nāfiʿ is not captured);
- *ambiguous*: *ʿan*, *anna*, *qāla*, *fa-qāla*, *dhakara*, *rawā*, *yarwīhi*, *balagha*, *yuḥaddithu*, *yaqūlu*, *suʾila*, *zaʿama*, and a missing formula;
- *unclassified*: anything else.

Over the 190,254 rows: explicit 98,549, ambiguous 91,549, unclassified 156 (`docs/runs/2026-10-20-stage2.md`). The prefix rule has a known flaw: it counts passive forms such as *ḥuddithtu ʿan* ("I was told, from ...") and *ukhbirtu* ("I was informed") as explicit, although they announce an unnamed intermediary. Without diacritics *ḥuddithtu* cannot always be told apart from the active *ḥaddathat* ("she told"); up to 47 rows carry such forms (`paper/derived_numbers.py` §7).

## 4 Method

<!-- Sources: isnad/score.py, isnad/constants.py, isnad/gold.py, isnad/validate.py. -->

### 4.1 Meeting probability

For a link from teacher T to student S, let $D_T$ be T's death year and $B_S$ be S's birth year. We define

$$p_{\text{meet}} = P(D_T - B_S \ge A_0), \qquad A_0 = 8,$$

the probability that the student was at least eight lunar years old before the teacher died. Eight years is a conservative lower bound on the age of audition; classical practice records audition at five and later, and the choice errs toward not flagging a link.

Each recorded year $y$ is treated as normal with mean $y$ and a standard deviation set by its kind: 1 year for `exact`; half the range, at least 2, for `alt`; 5 for `approx`; for `after` and `before`, the mean is moved 3 years in the stated direction with sd 5; for `era`, the caliphate interval gives the mean (its midpoint) and an sd of one quarter of its length. When the student's birth year is unknown, we impute it from the student's death year and a lifespan prior, $B_S = D_S - L$, $L \sim \mathcal{N}(68, 14)$. When the teacher's death year is unknown but the teacher's birth year is known, $D_T = B_T + L$ in the same way. All terms are independent normals, so

$$p_{\text{meet}} = \Phi\!\left(\frac{\mu}{\sigma}\right), \quad
\mu = \begin{cases} D_T - B_S - A_0 & \text{birth known} \\ D_T - D_S + 68 - A_0 & \text{birth imputed} \end{cases}, \quad
\sigma = \begin{cases} \sqrt{\sigma_T^2 + \sigma_{B_S}^2} \\ \sqrt{\sigma_T^2 + \sigma_{D_S}^2 + 14^2} \end{cases}$$

with $\Phi$ computed through the error function. The code defines truncation bounds of 20 and 100 years for the lifespan prior, but v1 uses the untruncated normal, so the closed form above is exact for the implementation. Each link records `how`: `birth_known`, `birth_imputed`, `no_dates` (both narrators present but too undated to score) or `missing_rawi` (a narrator identifier on the hadith page has no narrator row). Over Six-Book rows these are 101,580, 77,876, 9,895 and 903 (`metrics.json` → `coverage.how`).

The score depends only on the two narrators, not on the hadith, so every row of a pair has the same $p_{\text{meet}}$. The model has no fitted parameters: $A_0$, the lifespan prior and the per-kind deviations are set by hand and fixed before validation.

### 4.2 Date-conflict flag

A narrator's structured death year can disagree with the narrative years in the same page. If the closest narrative year differs from the structured death year by 20 years or more, the narrator is flagged, and every link touching that narrator receives the verdict `data_error` instead of a chronological verdict. Section 5.4 shows that this flag is much noisier than intended.

### 4.3 Textual evidence

For each link we record, separately from $p_{\text{meet}}$:

- `confirmed`: T is in S's list of teachers with confirmed audition on hdith.com;
- `explicit_term` or `ambiguous_term`: the formula class (Section 3);
- `irsal`, `tadlis`: S carries the corresponding flag on hdith.com;
- `denied`: the pair (S, T) is in the gold denial set (Section 4.6).

### 4.4 Verdicts

Each link receives exactly one verdict; the first matching condition wins.

| condition | verdict |
|---|---|
| date conflict on T or S | `data_error` |
| (S, T) denied by a critic | `denied_by_critic` |
| $p_{\text{meet}}$ unknown | `no_dates` |
| $p_{\text{meet}} < 0.05$ | `chronology_gap` |
| $p_{\text{meet}} < 0.2$, ambiguous formula, and S has *irsāl* or *tadlīs* | `suspect` |
| otherwise | `ok` |

The thresholds 0.05 and 0.2 are fixed; we report recall at 0.05, 0.1 and 0.2 to show sensitivity.

### 4.5 What the verdicts mean

A `chronology_gap` says that, given the recorded dates, the two people very probably did not overlap with the student old enough to hear. It does not say that the hadith is weak: the compiler or a later scholar may have known the link was broken, an intermediary may be well known, or the dates may be wrong. An `ok` verdict says only that chronology does not rule the link out.

### 4.6 Gold sets

**Negatives.** We use two sources of per-pair denials.

- *al-Marasil.* 1,011 (student, teacher, relation, authority, quote) records were extracted from the OpenITI text of Ibn Abi Hatim's *al-Marasil* with a large language model (Claude, through the `claude` command-line tool) in the preliminary study <!-- TODO: record the exact model version used for the al-Marasil extraction -->. Records whose teacher is the Prophet are dropped, leaving 944. Both names must be resolved to hdith.com identifiers.
- *Tuhfat al-Tahsil.* hdith.com attaches each narrator's *Tuhfa* entry to the narrator's page (1,032 entries in our fetch). The student is therefore known by identifier; an LLM (Claude Sonnet, batches of 40 entries) extracts the teacher name and relation from each entry, giving 1,700 records, and only the teacher name must be resolved.

**Name resolution and the homonym problem.** Classical texts name narrators by short forms ("Ḥamza b. ʿAbd Allāh", "Saʿīd b. Jubayr", "ʿUmar"), and many short forms match several narrators. A token-overlap scorer compares the query with every recorded name form of every narrator; the first token (or particle plus token, as in *Abū Hurayra*) earns a bonus, and the particles *ibn*, *abū* and *umm* are kept as tokens but never count as overlap on their own, so that "ʿUmar" does not resolve to "Ibn ʿUmar" and "Umm Sulaym" does not resolve to Anas, who is "Ibn Umm Sulaym". Candidates scoring at least 0.6 are kept. We then resolve the student and teacher *jointly*:

1. among candidate pairs whose name scores are within 0.1 of the best on each side, prefer a pair in which hdith.com already records the teacher-student relation; ties are broken by summed name score and narration counts;
2. otherwise, drop pairs in which the teacher died more than 5 years after the student, and rank the rest by summed name score plus a small prior on the log narration count of each narrator; accept the top pair only if it leads the next by at least 0.05;
3. otherwise the record is *ambiguous* and excluded.

The band in step 1 matters: without it, a weakly matching homonym that happens to be a recorded student of the teacher beats the narrator the name actually denotes. The outcome (`paper/derived_numbers.py` §1):

| source | records | resolved by relation | by prior | ambiguous | unresolved |
|---|---|---|---|---|---|
| al-Marasil | 944 | 725 | 149 | 58 | 12 |
| Tuhfa | 1,700 | 1,270 | 303 | 123 | 4 |

**Hadith-specific statements.** Some statements deny a link for one report only ("he did not hear *this hadith* from him"). These are not pair-level denials, and a bounded pattern over the quote marks them `specific`; they are excluded (1 al-Marasil and 4 Tuhfa records). Statements of the *sama* relation are never negatives; they form an additional positive class (`sama_attested`).

After these steps the denial file holds 2,255 (student, teacher, relation, source) rows over 1,504 distinct pairs. Negatives are evaluated per (student, teacher, relation) pair within each source, with $p_{\text{meet}}$ computed from narrator dates whether or not the pair occurs in the Six Books.

**Positives.** Positives are rows in al-Bukhari and Muslim whose formula is explicit, excluding *muʿallaq* links and rows with verdict `no_dates`, together with all rows whose pair hdith.com lists as confirmed audition. *ʿAn*-links are never positives. This gives 18,356 rows (18,127 with a score) over 1,800 pairs (1,715 with a score). Because frequent pairs dominate the row count, we report AUROC both against rows (`auroc`) and against de-duplicated pairs (`auroc_pairs`).

**Sound-chain controls.** To check that name resolution does not turn well-attested links into denials, we inspected six links that no critic disputes: Mālik ← Nāfiʿ, Nāfiʿ ← Ibn ʿUmar, al-Zuhrī ← Sālim, Sālim ← Ibn ʿUmar, Hishām b. ʿUrwa ← ʿUrwa, and ʿUrwa ← ʿĀʾisha. None is in the denial set, and all of their rows (287, 1,572, 444, 570, 910 and 1,419) have verdict `ok`, with $p_{\text{meet}}$ between 0.87 (Nāfiʿ ← Ibn ʿUmar) and 1.00 (`paper/derived_numbers.py` §2). An earlier resolver that dropped the *ibn* particle had resolved "ʿUmar" to Ibn ʿUmar; this control is the guard against that class of error. <!-- TODO: confirm these six pairs match the control list used when the resolver was fixed (Task 8c); the list here was reconstructed for the draft. -->

### 4.7 Preliminary study

Before building the pipeline, we tested the same score on *Ṣaḥīḥ Muslim* using Multi-IsnadSet links and narrator dates from a separate biographical site, against the al-Marasil pairs. That study found AUROC 0.81 for *no_idrak*, 0.74 for *mursal* and 0.57 for *no_sama* (`~/research/sanad-spike/REPORT.md`). The present paper replaces both data sources with hdith.com, covers all Six Books, adds Tuhfa, and changes name resolution, so the numbers are not directly comparable.

## 5 Results

### 5.1 Chronology against classical denials

<!-- Source: data/metrics.json → negatives.<source>.<relation>; positives; false_flag_rate. -->

Table 1 gives, for each source and relation, the number of scored negative pairs ($n$; total resolved pairs in parentheses), AUROC against row-level and pair-level positives, and recall: the share of negative pairs with $p_{\text{meet}}$ below each threshold.

**Table 1.** Separation of denied pairs from audition-attested links by $p_{\text{meet}}$.

| source | relation | $n$ (total) | AUROC rows | AUROC pairs | recall@0.05 | recall@0.1 | recall@0.2 |
|---|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 66 (79) | 0.803 | 0.786 | 0.106 | 0.167 | 0.227 |
| al-Marasil | mursal | 185 (215) | 0.904 | 0.897 | 0.341 | 0.395 | 0.492 |
| al-Marasil | no_sama | 383 (405) | 0.634 | 0.612 | 0.052 | 0.076 | 0.117 |
| Tuhfa | no_idrak | 191 (223) | 0.881 | 0.869 | 0.251 | 0.309 | 0.351 |
| Tuhfa | mursal | 435 (516) | 0.884 | 0.873 | 0.292 | 0.354 | 0.437 |
| Tuhfa | no_sama | 594 (676) | 0.649 | 0.626 | 0.069 | 0.088 | 0.116 |

The pattern matches what a chronological test can and cannot see. Pairs denied because the student "did not reach" the teacher, and pairs whose narration is called *mursal*, are ranked well below attested links (AUROC 0.79 to 0.90). Pairs denied because the student "did not hear" from a contemporary are barely separated (0.61 to 0.65): the two people overlapped, and dates cannot tell whether they met. Pair-level AUROC is 0.007 to 0.023 below row-level AUROC in every cell, so the row weighting of positives does not drive the result.

Recall at the default threshold is modest even where AUROC is high: 10.6% of al-Marasil *no_idrak* pairs and 25.1% of Tuhfa *no_idrak* pairs fall below 0.05. Many denied pairs are near-misses where the student was a child when the teacher died, which the critics judged and an eight-year cut with several years of uncertainty does not settle. The al-Marasil *no_idrak* set is also small (66 scored pairs). Figures `figures/p_meet_marasil_no_idrak.png`, `figures/p_meet_tuhfa_no_idrak.png`, `figures/p_meet_marasil_mursal.png`, `figures/p_meet_tuhfa_mursal.png`, `figures/p_meet_marasil_no_sama.png` and `figures/p_meet_tuhfa_no_sama.png` show the distributions of $p_{\text{meet}}$ for each negative class against the positives.

**False flags.** Table 2 gives the share of positives below each threshold.

**Table 2.** False-flag rate on positives.

| positives | $n$ scored | @0.05 | @0.1 | @0.2 |
|---|---|---|---|---|
| explicit-audition rows (al-Bukhari, Muslim) + confirmed pairs | 18,127 rows | 0.22% | 0.28% | 1.32% |
| same, de-duplicated | 1,715 pairs | 0.35% | 0.70% | 0.99% |
| *sama* statements, al-Marasil | 39 pairs | 0.0% | 0.0% | 0.0% |
| *sama* statements, Tuhfa | 120 pairs | 5.8% | 5.8% | 9.2% |

At the default threshold, 0.22% of positive rows and 0.35% of positive pairs are flagged. Some of these flags are correct in the sense of Section 6: a positive is only a link printed with an explicit formula, and a few such links are themselves chronologically impossible because of date or linking errors. The higher rate on Tuhfa *sama* statements (7 of 120 pairs at 0.05) is unexplained; candidate causes are LLM extraction errors (a denial read as an attestation) and resolution to the wrong homonym. <!-- TODO: inspect the 7 Tuhfa sama pairs below 0.05. -->

### 5.2 Textual evidence for *no_sama*

<!-- Sources: data/metrics.json → negatives.<source>.<relation>.{n_in_corpus, chron_recall_in_corpus@*,
text_recall_in_corpus, text_recall_in_corpus_excl_denial, student_irsal_frac}; matched-denominator
figures from paper/derived_numbers.py §6. -->

Chronology cannot decide whether contemporaries met. The classical tools for that question are textual: whether the student uses explicit audition formulae from this teacher, and whether the student is known for *irsāl* or *tadlīs*. To measure what this evidence adds, we restrict each negative class to pairs that actually occur in the Six Books (`n_in_corpus`) and compare two flags on the same pairs:

- **chronology only**: $p_{\text{meet}}$ below a threshold;
- **chronology + text**: the verdict is `chronology_gap` or `suspect`, computed without the gold denial (`text_recall_in_corpus_excl_denial`). A pair counts as flagged if any of its rows is flagged.

**Circularity.** The production verdict also includes `denied_by_critic`, which is set from the same gold denials we evaluate against. With it, in-corpus recall is 0.91 to 0.99 for every class (`text_recall_in_corpus`); this measures only that the denial lookup works. We report it in Table 3 for completeness and do not treat it as a result.

**Table 3.** In-corpus recall of denied pairs. Chronology columns are over pairs with a score, as stored in `metrics.json`.

| source | relation | in corpus | chron.@0.05 | chron.@0.1 | chron.@0.2 | chron. + text (excl. denial) | with denial (circular) | students with *irsāl* flag |
|---|---|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 22 | 0.095 | 0.143 | 0.190 | 0.091 | 0.909 | 0.867 |
| al-Marasil | mursal | 53 | 0.234 | 0.298 | 0.404 | 0.321 | 0.981 | 0.852 |
| al-Marasil | no_sama | 165 | 0.019 | 0.039 | 0.077 | 0.061 | 0.994 | 0.899 |
| Tuhfa | no_idrak | 80 | 0.258 | 0.333 | 0.379 | 0.263 | 0.963 | 0.923 |
| Tuhfa | mursal | 154 | 0.230 | 0.281 | 0.348 | 0.305 | 0.987 | 0.966 |
| Tuhfa | no_sama | 316 | 0.040 | 0.058 | 0.076 | 0.060 | 0.987 | 0.920 |

The chronology columns in `metrics.json` exclude pairs without a score, while the text column includes them as unflagged, so the two denominators differ. Table 4 recomputes the chronology-only flag over the same in-corpus pairs (pairs without a score counted as unflagged) and gives the lift.

**Table 4.** Lift from textual evidence, matched denominator (`paper/derived_numbers.py` §6).

| source | relation | pairs | chron.@0.05 | chron. + text | lift (points) | pairs gained |
|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 22 | 0.091 | 0.091 | 0.0 | 0 |
| al-Marasil | mursal | 53 | 0.208 | 0.321 | 11.3 | 6 |
| al-Marasil | no_sama | 165 | 0.018 | 0.061 | 4.2 | 7 |
| Tuhfa | no_idrak | 80 | 0.212 | 0.263 | 5.0 | 4 |
| Tuhfa | mursal | 154 | 0.201 | 0.305 | 10.4 | 16 |
| Tuhfa | no_sama | 316 | 0.035 | 0.060 | 2.5 | 8 |

The textual rule adds 10 to 11 points of recall on *mursal* pairs and 2.5 to 4.2 points on *no_sama* pairs. This is a real but small gain, and it is not the "lift" that would make *no_sama* tractable: more than nine in ten in-corpus *no_sama* pairs are still unflagged at the default thresholds. Two facts explain why. First, the `suspect` rule only fires below $p_{\text{meet}} = 0.2$, so it cannot reach contemporaries with high $p_{\text{meet}}$; in every row of Table 4 the chronology + text recall is at most the chronology-only recall at 0.2 (Table 3, with matched denominators: 0.182, 0.358, 0.073, 0.312, 0.305, 0.066). Second, the student-level flags are not discriminative: 85% to 97% of the students in every negative class carry an *irsāl* flag on hdith.com, which is close to saying that the critics deny contact mainly for narrators already known for *irsāl*. A student-level flag cannot say which of a student's teachers he did not hear from. The data needed for that are per-pair: the confirmed-audition lists, and explicit-formula links between the same pair elsewhere in the corpus. We return to this in Section 7.

### 5.3 Verdicts across the Six Books

<!-- Source: data/metrics.json → verdict_counts_by_book; data/run_report.md; figures/verdicts_by_book.png. -->

**Table 5.** Verdict counts (rows) per book.

| book | rows | ok | no_dates | denied_by_critic | data_error | chronology_gap | suspect |
|---|---|---|---|---|---|---|---|
| al-Bukhari (b-1) | 37,282 | 35,921 | 565 | 529 | 191 | 70 | 6 |
| Muslim (b-2) | 41,907 | 40,026 | 1,010 | 581 | 205 | 71 | 14 |
| Abu Dawud (b-3) | 28,832 | 24,868 | 2,961 | 653 | 262 | 76 | 12 |
| al-Tirmidhi (b-4) | 24,009 | 21,261 | 1,804 | 670 | 161 | 100 | 13 |
| al-Nasaʾi (b-5) | 33,375 | 30,386 | 2,034 | 603 | 263 | 77 | 12 |
| Ibn Maja (b-6) | 24,849 | 21,448 | 2,226 | 721 | 392 | 52 | 10 |
| total | 190,254 | 173,910 | 10,600 | 3,757 | 1,474 | 446 | 67 |

`figures/verdicts_by_book.png` plots the same counts. 91.4% of rows are `ok`. The 446 `chronology_gap` rows come from 127 distinct pairs; 101 of the 446 rows carry an explicit audition formula (`paper/derived_numbers.py` §4), which is either a data error or a linking error, since an explicit formula across an impossible gap cannot be literally true. `no_dates` is lowest in al-Bukhari and Muslim (1.5% and 2.4% of rows) and highest in Abu Dawud (10.3%), reflecting how many lesser-known narrators each book uses. The `denied_by_critic` count is a property of the gold sets, not a finding.

### 5.4 Auditing the narrator dates

<!-- Sources: data/date_errors.csv; paper/derived_numbers.py §3. -->

The date-conflict flag (Section 4.2) marks 934 narrators across the full narrator table, and 1,474 Six-Book rows touching 88 of them receive `data_error`. The planned claim was that these are errors in the structured dates. Inspection does not support that claim as stated.

- For 505 of the 934 narrators, some narrative year equals the structured death year modulo 100: a narrator recorded as dying in 257 has a biography saying he "died in the year fifty-seven". Classical biographers routinely omit the century when context makes it clear. The difference is exactly 200 years for 388 narrators, 100 for 20 and 300 for 18. These flags are artefacts of reading narrative years without their implied century, not errors in the database.
- For another 94, every narrative year is a single digit, which suggests the parser picked up numbers that are not years (for instance "in the year eight" referring to an event, or an age).
- The remaining 335, and in particular the 66 with a difference between 20 and 99 years, are the candidates for genuine disagreement, and need reading.

In the Six Books, 40 of the 88 conflicted narrators belong to the century-omission group, and 729 of the 1,474 `data_error` rows are explained by those narrators alone. The `data_error` verdict therefore hides, rather than reports, about half of its rows. The fix is straightforward (add the structured year's century to a two-digit narrative year before comparing, and require a death phrase rather than any number) and will be applied before release.

The more useful audit comes from the `chronology_gap` links. Among the 50 weakest pairs (`data/weak_edges.csv`), several flags trace to narrator records whose dates are impossible on their face: two students have a recorded birth year at or after their death year, and the full narrator table contains 3 narrators with birth year after death year. Section 6 gives examples. The preliminary study found the same kinds of error in a different narrator database (`~/research/sanad-spike/REPORT.md`), which suggests the problem is general to biographical databases built from structured fields, not specific to one site.

## 6 Examples

<!-- TODO: replace with audit labels. docs/analysis/2026-10-20-weak-edge-audit.md and
data/weak_edges_labeled.csv were not present when this section was written; the groupings
below are read off data/weak_edges.csv and are hypotheses, not verified judgements. -->

The 50 weakest pairs in `data/weak_edges.csv` cover 122 hadith rows. 33 have an ambiguous formula, 16 an explicit one and 1 an unclassified one (*qaraʾtu fī kitāb*, "I read in a book"). All have $p_{\text{meet}} < 3 \times 10^{-9}$. They fall into five groups; each assignment below is provisional until the manual audit is complete.

**(a) Implausible birth years for the student.** Nine of the 50 pairs have the same student, al-Waḍḍāḥ b. ʿAbd Allāh al-Yashkurī (Abū ʿAwāna), recorded as born in 122, with teachers who died between 100 and 121. The preliminary study noted the same birth year in another database while Abū ʿAwāna narrates from Qatāda (d. 117). Three pairs have Darrāj Abū al-Samḥ as student, recorded as born in 125 and died in 126; one of them covers 29 hadith rows across four books. Ḥakīm b. Ḥakīm b. ʿAbbād al-Anṣārī is recorded as born in 110 and died in 101. In all three cases the link is probably fine and the birth year is wrong; the score is doing what it should, and the verdict should be read as a data error.

**(b) Implausible death years for the teacher.** Abū Dāwūd (born 202.5 by the record) is linked with *ḥaddathanā* to Abū Ḥuṣayn b. Yaḥyā b. Sulaymān al-Rāzī, recorded as dying in 51. Al-Zuhrī is linked with an explicit formula to Ḥuṣayn b. Muḥammad al-Sālimī, recorded as dying in 9. A death year two centuries early, or a narrator resolved to the wrong person on the source page, would both produce this. These are the cases the date-conflict flag was meant to catch and did not.

**(c) Explicit formulae across a gap between generations.** Al-Tirmidhī (born 210) ← Sulaymān b. ʿAbd al-Jabbār al-Khayyāṭ (d. 151), al-Nasāʾī ← al-Haytham b. Marwān al-ʿAnsī (d. 199) and ← Ḥammād b. Masʿada (d. 202), Hishām b. ʿAmmār ← ʿAmr b. Wāqid (d. 130), and ʿAbd Allāh b. Wahb ← al-Zuhrī with *akhbaranī*. An explicit formula across a gap of decades is not a classical *irsāl*; the likely causes are a homonym linked to the wrong narrator identifier, or a node missing from the parsed chain. These rows are where a scholar's check is most informative for the source database.

**(d) Formulae that themselves announce indirect reception.** Abū Dāwūd ← Hārūn b. al-Mughīra and ← ʿAbd Allāh b. Wahb, both with *ḥuddithtu ʿan* ("I was told, from"); Abū Dāwūd ← ʿAbd Allāh b. Sālim al-Wuḥāẓī with *qaraʾtu fī kitāb* ("I read in [his] book"); al-Shaʿbī ← Bashīr b. Saʿd with *ukhbirtu*. Here the compiler or narrator states that there was no direct audition, and the flag is correct but not news. The first two are also the passive forms our formula classifier wrongly counts as explicit (Section 3).

**(e) Successors citing Companions they could not have met.** Al-Zuhrī ← ʿUmar b. al-Khaṭṭāb (two rows, *anna*), Qatāda ← ʿUmar (*anna*), al-Zuhrī ← Ḥafṣa (*ʿan*), ʿAṭāʾ b. Abī Rabāḥ ← Surāqa b. Mālik (*qāla*), ʿUrwa b. al-Zubayr ← Bashīr b. Saʿd (*anna*), Mujāhid ← Ayman b. ʿUbayd (*ʿan*), and ʿUmar b. ʿAbd al-ʿAzīz ← ʿUmar b. al-Khaṭṭāb. These are the classical *mursal* pattern: a later narrator reporting an earlier figure's words or acts with *anna* or *ʿan*, often as narrative rather than as a claim of hearing. They are the cases where the score reproduces what the critics already knew. Ayyūb al-Sakhtiyānī ← ʿĀʾisha in Muslim, flagged here, was also flagged in the preliminary study on a different edge dataset, which suggests the *anna*-construction is in the text itself rather than an extraction artefact.

A sixth, smaller group involves family chains where the parser may have attached a formula to the wrong pair, such as al-Zubayr b. al-ʿAwwām ← Hishām b. ʿUrwa with *fa-qāla*, where the chain plausibly runs through ʿUrwa. <!-- TODO: check hadith 102632 on the source page. -->

## 7 Limitations

**Row weighting.** A pair that appears in many hadith appears in many rows. Verdict counts (Table 5) and row-level false-flag rates weight frequent pairs heavily. We report pair-level AUROC and false-flag rates alongside the row-level ones (Tables 1 and 2); negatives are always counted per pair.

**Era dates and coarse dates.** About 85 narrators in Six-Book links have only an era date and 2,370 have no death date at all. Era intervals are converted to a normal distribution, which treats a caliphate of twenty years as a broad, centred uncertainty. Dates of the form "after 170" are shifted by a fixed 3 years.

**Imputed births.** 77,876 rows depend on a birth year imputed from a population lifespan prior, $\mathcal{N}(68, 14)$, untruncated. This prior is not an individual estimate, is the same for all generations, and, untruncated, assigns small probability to implausible lifespans. Long-lived narrators (*muʿammarūn*), who matter most for disputed links, are exactly where it is weakest.

**Name resolution.** Resolution is measured by coverage, not by precision. 181 records (58 al-Marasil, 123 Tuhfa) are excluded as ambiguous, and 16 are unresolved. The resolved pairs have not been checked against a hand-labelled sample, so we cannot state a precision figure; the six controls (Section 4.6) test only a known failure. <!-- TODO: hand-label a random sample of 100 resolved pairs per source and report precision. -->

**LLM extraction.** Both gold sets were extracted by a language model from classical Arabic text. Extraction errors (a misread relation, a teacher name taken from the wrong clause, an attestation read as a denial) enter the gold sets directly. The *sama* false-flag rate on Tuhfa (Table 2) may reflect such errors. We have not measured extraction accuracy against a manual reading.

**Hadith-specific statements.** We exclude statements limited to one report by a pattern over the quote. The pattern is conservative (5 exclusions in total), and statements that are hadith-specific without using one of its markers remain as pair-level denials. Conversely, a critic's denial for one route may be reported by later compilers as a general one.

**The date-conflict flag.** As shown in Section 5.4, at least 505 of 934 flags are artefacts of century omission. Until fixed, `data_error` verdicts should not be read as data errors.

**Formula classification.** The prefix rule counts passive forms (*ḥuddithtu*, *ukhbirtu*) as explicit, and 156 rows remain unclassified. Formulae are taken as printed on the source page; they may differ between manuscripts and editions.

**Textual evidence is student-level.** The *irsāl* and *tadlīs* flags describe the student, not the pair, which limits the `suspect` rule (Section 5.2).

**Scope.** Main results cover the Six Books only. The remaining 239 books on hdith.com have not been fetched. The positives come from al-Bukhari and Muslim, whose explicit links are among the most scrutinised in the tradition; the false-flag rate on less-studied books may be higher.

**Chronology is not authenticity.** A possible meeting does not establish audition, and an impossible one does not by itself make a report weak: the intermediary may be known, or the compiler may have included the report knowingly. The scores are aids for locating links worth reading, not grades of hadith.

## 8 Ethics and licensing

The data source is hdith.com. Its terms of use do not state a license for reuse of its content. We therefore release only derived numbers: narrator and hadith identifiers, years, uncertainty kinds, short categorical flags, link formulae as categories, scores and verdicts. No hadith text, isnad text, narrator biography or critic statement is redistributed, and the export applies a column denylist. The derived dataset is released under CC-BY-4.0 with required attribution to hdith.com; the code is released under the MIT license. We will contact the site's owners before publishing the dataset.

Fetching followed the site's robots.txt, which allows crawlers and disallows preview and embed paths; those paths were never requested. The local crawler sent an identifying User-Agent. For most of the Six-Book fetch it ran 16 and then 48 parallel workers (about 500 to 700 pages per minute), and we observed no rate-limit (429) or server (5xx) responses (`docs/runs/2026-10-20-stage2.md`). <!-- TODO: this exceeds the 3 requests/second ceiling in the design spec; decide how to state and justify it, or re-run slower for the remaining books. -->

Hadith grading is a religious and scholarly matter with practical consequences. A computed `chronology_gap` is not a ruling, and we ask users of the dataset not to present it as one. The gold sets encode the judgements of particular classical critics, which later scholars sometimes disputed; agreement with them is a measure of reproduction, not of correctness.

## 9 Conclusion

A closed-form meeting probability, computed from recorded death and birth years with explicit uncertainty, reproduces the classical critics' "did not reach" and *mursal* judgements on the Six Books (AUROC 0.79 to 0.90) and flags under a quarter of a percent of attested links. As expected, it cannot decide whether contemporaries met, and the student-level textual evidence we added recovers only a few more of those pairs. The links it flags as impossible are, in our first reading, more often evidence of errors in the narrator records or in chain linking than of hidden breaks, which makes the score useful for auditing the databases that computational hadith work increasingly relies on. Next steps are to fix the century-omission artefact in the date-conflict flag, measure name-resolution and extraction precision on hand-labelled samples, use pair-level audition evidence from the whole corpus for the *no_sama* class, and extend the fetch beyond the Six Books.

## References

<!-- Only works named in the brief; author lists and full bibliographic details to be filled and verified. -->

- Ibn Abi Hatim al-Razi. *al-Marasil*. OpenITI digital text. [verify: edition]
- Abu Zurʿa al-ʿIraqi. *Tuhfat al-Tahsil fi Dhikr Ruwat al-Marasil*. Entries as attached to narrator pages on hdith.com. [verify: edition]
- al-ʿAlaʾi. *Jamiʿ al-Tahsil fi Ahkam al-Marasil*. [verify: edition]
- Muslim b. al-Hajjaj. *al-Musnad al-Sahih*, introduction. [verify: edition]
- hdith.com. Hadith encyclopedia, accessed October 2026.
- IsnadGuard. ICML 2026. [verify: authors, title]
- Crowdsourced Information Authentication: A Graph-based Model from the Science of Hadith. ICML 2025. [verify: authors]
- IslamicMMLU. arXiv:2603.23750, 2026. [verify: authors, title]
- FiqhQA. arXiv:2508.08287. [verify: authors, title, year]
- Sanadset 650K. *Data in Brief*, 2022. [verify: authors, title]
- Multi-IsnadSet. *Data in Brief*, 2024. [verify: authors, title]
- Motzki, H. *The Origins of Islamic Jurisprudence*. Brill, 2002. [verify]
- Yanagihashi, H. *Studies in Legal Hadith*. Brill, 2019. [verify]
