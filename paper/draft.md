# Could They Have Met? Chronological Meeting Probabilities for Every Link in the Isnads of the Six Books

*Working title. Draft v1, 2026-10-20. Not for circulation.*

<!-- Numbers: data/metrics.json, data/run_report.md, docs/runs/, data/*.csv, the audit
docs/analysis/2026-10-20-weak-edge-audit.md, paper/derived_numbers.py; all after the Task 7d fix. -->

## Abstract

A hadith reaches us through an isnad, a chain of narrators in which each person claims to have received the report from the one before. Classical critics tested these links one by one, and part of the test is chronological: a student cannot have heard from a teacher who died before the student was old enough to listen. For each of the 190,254 teacher-to-student links in the isnads of the Six Books on hdith.com, we compute the probability that the student was at least eight lunar years old before the teacher died, using the site's narrator dates with an explicit uncertainty for each kind of date. The model has no trained parameters. Against denials of contact in Ibn Abi Hatim's *al-Marasil* and in *Tuhfat al-Tahsil*, the score separates "did not reach" (*no_idrak*) pairs from audition-attested links with AUROC 0.80 and 0.88, and *mursal* pairs with 0.90 and 0.88, while flagging 0.22% of attested links. It does not separate "did not hear" (*no_sama*) pairs between contemporaries (AUROC 0.63 and 0.65), and student-level textual evidence adds only two to four points of recall there. A manual audit of the 50 most confidently flagged pairs finds 15 genuine breaks, all already known to the critics, and 19 errors in the site's dates that trace to just 7 narrator records. We release per-link scores and verdicts as derived numbers.

## 1 Introduction

The isnad is the part of a hadith report that names who transmitted it: "A told us, from B, from C, that the Prophet said ...". Muslim critics of the second and third Islamic centuries asked of each link whether it is *muttasil* (connected), answered pair by pair, and wrote the answers down. Ibn Abi Hatim's *al-Marasil* and Abu Zurʿa al-ʿIraqi's *Tuhfat al-Tahsil* collect statements of the form "X did not hear from Y", "X did not reach Y", or "X's narration from Y is *mursal*".

Much of this judgement rests on dates: if Y died before X was born, the link is broken whatever the formula says. Digital corpora now record narrator dates and full chains at scale, so the chronological test can be applied to every link at once. Computational isnad work has so far scored whole chains or graphs (Section 2.3); it cannot say which link is weak or why. A per-link chronological score answers a narrower question in terms a hadith scholar already uses.

We contribute a method and three claims, each stated with the strength the evidence supports.

- **Method.** A closed-form probability that the student was at least eight lunar years old before the teacher died, with a standard deviation for each kind of recorded date and a lifespan prior for missing birth years (Section 4).
- **Claim 1: chronology reproduces "did not reach" and *mursal* judgements, not "did not hear".** On pairs denied in two classical sources, AUROC is 0.79 to 0.90 for *no_idrak* and *mursal* (row- and pair-level) and 0.61 to 0.65 for *no_sama*; 0.22% of audition-attested rows are falsely flagged (Section 5.1).
- **Claim 2: textual evidence adds little for contemporaries.** Adding the transmission formula and the student's *irsāl*/*tadlīs* flags raises in-corpus recall of *no_sama* pairs by 2.5 to 4.2 points, measured with a matched denominator and without the circular gain from the denials themselves (Section 5.2).
- **Claim 3: the flagged links audit the data, and most "date conflicts" were our own parser.** A cross-check of structured death years against years in each narrator's biography first flagged 934 narrators; most were our parser reading years whose century the source leaves implicit. After the fix, 152 narrators and 252 Six-Book rows remain as the audit set. The manual audit of the 50 weakest pairs finds 19 site-side date errors on 7 narrator records, headed by Abū ʿAwāna's birth year 122, which Ibn Ḥibbān rejects as «هو خطأ» in the same record (Sections 5.4 and 6).

## 2 Background

### 2.1 The isnad and its formulae

A hadith consists of the isnad and the *matn* (text). In the canonical collections the isnad begins with the compiler's teacher and ends with a Companion or another early source; each adjacent pair is a link from a teacher (earlier) to a student (later). Our parser keeps parallel chains (marked ح) and omitted chain starts (*muʿallaq* reports), and never uses *muʿallaq* links as positives.

Each link is introduced by a formula. Some state direct reception: *ḥaddathanā* ("he told us"), *akhbaranā* ("he informed us"), *samiʿtu* ("I heard"). Others do not: *ʿan* ("from"), *anna* ("that"), *qāla* ("he said"). Whether a *muʿanʿan* link (built with *ʿan*) counts as connected was itself debated. In the introduction to his *Ṣaḥīḥ*, Muslim held that contemporaneity with the possibility of meeting suffices for a narrator not known to conceal gaps; the stricter position, associated with ʿAlī b. al-Madīnī and al-Bukhārī, requires evidence of at least one meeting. A chronological score quantifies the necessary condition shared by both positions.

### 2.2 *Mursal* and the critics' literature

A chain with a missing link is broken. In early usage *mursal* covers several kinds of break; later it usually means a Successor citing the Prophet directly, while *munqaṭiʿ* names a break further down. Two narrator traits make breaks likely: *irsāl* (citing people one did not hear from) and *tadlīs* (using an ambiguous formula to hide an intermediary).

*Al-Marasil* gathers statements, mostly from Abu Hatim and Abu Zurʿa al-Razi, that a narrator did not hear from, or did not reach, another. Al-ʿAlaʾi's *Jamiʿ al-Tahsil* compiled the narrators accused of *irsāl*, and Abu Zurʿa al-ʿIraqi's *Tuhfat al-Tahsil* extends it. <!-- [verify] death dates if added: Ibn Abi Hatim d. 327, al-ʿAlaʾi d. 761, Abu Zurʿa al-ʿIraqi d. 826 AH. --> We distinguish three negative relations: *no_idrak* ("did not reach him"), *no_sama* ("did not hear from him", typically between contemporaries) and *mursal*. A fourth, *sama*, records explicit statements that the student did hear from the teacher.

### 2.3 Related computational work

Sanadset 650K (*Data in Brief*, 2022) provides narrator chains extracted from many hadith books, with narrators given by name [verify: authors, exact counts]. Multi-IsnadSet (*Data in Brief*, 2024) gives a narrator graph for *Ṣaḥīḥ Muslim* with narrator identifiers [verify: authors]; we used it in a preliminary study (Section 4.5). IsnadGuard (ICML 2026) detects fabricated isnads from chain structure alone, reporting AUROC rising from 0.727 to 0.836 on 43,539 chains [verify: authors, exact setting]. "Crowdsourced Information Authentication: A Graph-based Model from the Science of Hadith" (ICML 2025) models authentication as verification over a transmission graph [verify: authors, scope]. None scores an individual link by chronology or validates against classical per-pair denials. Benchmarks such as IslamicMMLU (arXiv 2603.23750, 2026) and FiqhQA (arXiv 2508.08287) test language models on Islamic sciences [verify: scope of each]; we do not evaluate language models and use one only to extract gold pairs.

In Western scholarship, the isnad-cum-matn method of Motzki and others compares variants of one report across chains to date its common source [verify: Motzki, *The Origins of Islamic Jurisprudence*, 2002], and Yanagihashi applies related source criticism to legal hadith [verify: Yanagihashi, *Studies in Legal Hadith*, Brill 2019]. Those methods work report by report and use the matn; ours works link by link and uses only dates and formulae.

## 3 Data

<!-- Sources: docs/superpowers/specs/2026-10-18-isnad-chrono-design.md §2; docs/runs/2026-10-20-stage{1,2}.md;
data/run_report.md; paper/derived_numbers.py §7–8. -->

**Source.** hdith.com is a public hadith encyclopedia covering 245 books (612,548 hadith by its sitemaps) and 20,777 narrators. Each hadith page lists its isnad as a sequence of narrator identifiers with the formula printed before each name. Each narrator page gives structured fields (names, generation, birth and death as text), teachers and students with identifiers, critics' statements, biography excerpts, teachers with confirmed audition (*ithbāt samāʿ*), *irsāl*/*tadlīs*/*ikhtilāṭ* flags and any *Tuhfat al-Tahsil* entries. Our parsers read the JSON embedded in both page types.

**Fetch.** We fetched all 20,777 narrator pages and the hadith pages of the Six Books: al-Bukhari (b-1), Muslim (b-2), Abu Dawud (b-3), al-Tirmidhi (b-4), al-Nasaʾi (b-5) and Ibn Maja (b-6). Of 34,995 enumerated hadith entries (excluding the site's non-hadith passages), 34,816 were fetched and parsed without errors (7,324, 7,651, 5,259, 4,335, 5,780 and 4,467 per book); 179 remain pending.

**Links.** Parsing yields 190,254 link rows (teacher, student, hadith, position, formula) among 6,963 distinct narrators. A link occurring in many hadith appears once per hadith; we call these *rows*, and a de-duplicated (teacher, student) combination a *pair*.

**Dates.** A Hijri date parser maps each birth or death phrase to a year, a standard deviation and a *kind*: `exact`, `alt` (alternative years), `approx`, `after`, `before`, `era` (a caliphate phrase, mapped to the caliphate's interval) or `none`. It handles Arabic-Indic and ASCII digits, compound number words including thousands (*alf*), and ranges. Of the 20,777 narrators, 10,251 have a death year and 1,649 a birth year. Among narrators in Six-Book links the death kinds are exact 3,463, alt 564, after 162, era 85, approx 72, before 53 and none 2,370. The parser also extracts every year stated in a death phrase inside the critics' statements and biography excerpts; we call these *narrative years*.

**Formula classes.** Each formula is normalised (hamza forms unified, diacritics removed) and classed:

- *explicit*: forms of *ḥaddatha*, *akhbara*, *samiʿa*, *anbaʾa*, reading formulae (*qaraʾtu ʿalā*, *quriʾa ʿalā*), *saʾala*, *raʾaytu*, *shahidtu*, *kataba ilayya*, *qāla lī/lanā*, *laqiya*, *qultu*, *khaṭaba*, and the scribal abbreviations *nā*, *thanā*, *anā* (نا/ثنا/أنا, matched exactly so that the name Nāfiʿ is not captured);
- *ambiguous*: *ʿan*, *anna*, *qāla*, *fa-qāla*, *dhakara*, *rawā*, *balagha*, *yuḥaddithu*, *yaqūlu*, *suʾila*, *zaʿama*, a missing formula, and the passive formulae *ḥuddithtu (ʿan)* ("I was told, from") and *ukhbirtu* ("I was informed"), which announce an unnamed intermediary and are checked before the explicit roots (47 rows);
- *unclassified*: anything else.

Over the 190,254 rows: explicit 98,502, ambiguous 91,602, unclassified 150.

## 4 Method

<!-- Sources: isnad/score.py, isnad/constants.py, isnad/gold.py, isnad/validate.py. -->

### 4.1 Meeting probability

For a link from teacher T to student S, with $D_T$ T's death year and $B_S$ S's birth year,

$$p_{\text{meet}} = P(D_T - B_S \ge A_0), \qquad A_0 = 8,$$

the probability that the student was at least eight lunar years old before the teacher died. Audition is classically recorded from age five, so eight errs toward not flagging.

Each recorded year is normal with mean $y$ and a standard deviation set by its kind: 1 for `exact`; half the range, at least 2, for `alt`; 5 for `approx`; for `after` and `before` the mean moves 3 years in the stated direction with sd 5; for `era` the mean is the caliphate's midpoint and the sd a quarter of its length. A missing student birth year is imputed as $B_S = D_S - L$, $L \sim \mathcal{N}(68, 14)$; a missing teacher death year with a known birth year as $D_T = B_T + L$. All terms are independent normals, so

$$p_{\text{meet}} = \Phi\!\left(\frac{\mu}{\sigma}\right), \quad
\mu = \begin{cases} D_T - B_S - A_0 & \text{birth known} \\ D_T - D_S + 68 - A_0 & \text{birth imputed} \end{cases}, \quad
\sigma = \begin{cases} \sqrt{\sigma_T^2 + \sigma_{B_S}^2} \\ \sqrt{\sigma_T^2 + \sigma_{D_S}^2 + 14^2} \end{cases}$$

The lifespan prior is untruncated, so the closed form is exact for the implementation. Each link records `how`: `birth_known` (101,580 rows), `birth_imputed` (77,876), `no_dates` (9,895) or `missing_rawi` (903, a narrator identifier with no narrator row). Every row of a pair has the same $p_{\text{meet}}$. $A_0$, the prior and the per-kind deviations were fixed by hand before validation.

### 4.2 Date-conflict flag

A narrator's structured death year $d$ can disagree with the narrative years on the same page. Classical biographers often omit the century ("he died in the year fifty-seven" for 257), so the comparison is century-adjusted: a narrative year $y$ is consistent with $d$ if

$$\min_{k \ge 0} \lvert d - (y + 100k) \rvert < 20, \quad \text{with } y + 100k \le d + 5 \text{ for } k > 0,$$

and the narrator is flagged if no narrative year is consistent. The side condition stops a small year from being shifted past the death it is meant to confirm. Every link touching a flagged narrator receives `data_error` instead of a chronological verdict. Before this rule (Section 5.4) the flag compared years literally.

### 4.3 Textual evidence and verdicts

For each link we record, separately from $p_{\text{meet}}$: `confirmed` (T is in S's confirmed-audition list on hdith.com), the formula class, `irsal` and `tadlis` (S carries the flag), and `denied` (the pair is in the gold denial set). Each link receives one verdict; the first matching condition wins.

| condition | verdict |
|---|---|
| date conflict on T or S | `data_error` |
| (S, T) denied by a critic | `denied_by_critic` |
| $p_{\text{meet}}$ unknown | `no_dates` |
| $p_{\text{meet}} < 0.05$ | `chronology_gap` |
| $p_{\text{meet}} < 0.2$, ambiguous formula, and S has *irsāl* or *tadlīs* | `suspect` |
| otherwise | `ok` |

A `chronology_gap` says that, on the recorded dates, the two very probably did not overlap with the student old enough to hear. It does not say the hadith is weak: the break may be known, an intermediary may be well known, or the dates may be wrong. An `ok` says only that chronology does not rule the link out.

### 4.4 Gold sets

**Negatives.** Two sources of per-pair denials:

- *al-Marasil.* 1,011 (student, teacher, relation, authority, quote) records were extracted in the preliminary study from the OpenITI text of Ibn Abi Hatim's *al-Marasil* by Claude (Sonnet) through the `claude` command-line tool. Dropping records whose teacher is the Prophet leaves 944; both names must be resolved to hdith.com identifiers.
- *Tuhfat al-Tahsil.* hdith.com attaches each narrator's *Tuhfa* entry to his page (1,032 entries), so the student is known by identifier. Claude (Sonnet), again through the CLI and in batches of 40 entries, extracts the teacher name and relation, giving 1,700 records; only the teacher must be resolved.

**Name resolution.** Classical texts name narrators by short forms ("Saʿīd b. Jubayr", "ʿUmar") that often match several narrators. A token-overlap scorer compares the query with every recorded name form, with a bonus for the first token; the particles *ibn*, *abū* and *umm* never count as overlap on their own, so "ʿUmar" does not resolve to Ibn ʿUmar. Candidates scoring at least 0.6 are kept, and student and teacher are resolved *jointly*: (1) among candidate pairs within 0.1 of the best name score on each side, prefer one in which hdith.com records the teacher-student relation; (2) otherwise drop pairs where the teacher died more than 5 years after the student, rank by summed name score plus a small prior on log narration counts, and accept the top pair only if it leads by at least 0.05; (3) otherwise the record is *ambiguous* and excluded.

| source | records | resolved by relation | by prior | ambiguous | unresolved |
|---|---|---|---|---|---|
| al-Marasil | 944 | 725 | 149 | 58 | 12 |
| Tuhfa | 1,700 | 1,270 | 303 | 123 | 4 |

Hadith-specific statements ("he did not hear *this hadith* from him") are excluded by a bounded pattern (1 al-Marasil and 4 Tuhfa records). *Sama* statements are never negatives; they form a separate positive class. The denial file holds 2,255 (student, teacher, relation, source) rows over 1,504 distinct pairs. Negatives are evaluated per pair within each source, with $p_{\text{meet}}$ computed from narrator dates whether or not the pair occurs in the Six Books.

**Positives.** Rows in al-Bukhari and Muslim with an explicit formula, excluding *muʿallaq* links and `no_dates` rows, plus all rows whose pair is a confirmed audition: 18,355 rows (18,126 scored) over 1,799 pairs (1,714 scored). *ʿAn*-links are never positives. Because frequent pairs dominate rows, AUROC is reported against both rows and pairs.

**Negative controls.** During development of the resolver, six links that no critic disputes served as controls: Nāfiʿ ← Ibn ʿUmar, ʿUrwa ← ʿĀʾisha, Hishām ← ʿUrwa, Sālim ← Ibn ʿUmar, al-Zuhrī ← Abū Salama and al-Aʿmash ← Abū Wāʾil. None is in the denial set, and all their rows (1,572, 1,419, 910, 570, 409 and 282) are `ok`, with $p_{\text{meet}}$ from 0.87 (Nāfiʿ ← Ibn ʿUmar) to 1.00 (`derived_numbers.py` §2). An earlier resolver that ignored the *ibn* particle had resolved "ʿUmar" to Ibn ʿUmar; the controls guard against that class of error.

### 4.5 Preliminary study

Before building the pipeline we tested the score on *Ṣaḥīḥ Muslim* with Multi-IsnadSet links and narrator dates from a different biographical site, against the al-Marasil pairs: AUROC 0.81 for *no_idrak*, 0.74 for *mursal* and 0.57 for *no_sama* (`~/research/sanad-spike/REPORT.md`). Data sources, scope and name resolution all differ, so these numbers are not directly comparable with Section 5.

## 5 Results

### 5.1 Chronology against classical denials

<!-- Source: data/metrics.json → negatives.<source>.<relation>; positives; sama_attested. -->

**Table 1.** Separation of denied pairs from audition-attested links by $p_{\text{meet}}$. $n$ is scored negative pairs (resolved pairs in parentheses); recall is the share of negative pairs below each threshold.

| source | relation | $n$ (total) | AUROC rows | AUROC pairs | recall@0.05 | recall@0.1 | recall@0.2 |
|---|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 66 (79) | 0.803 | 0.786 | 0.106 | 0.167 | 0.227 |
| al-Marasil | mursal | 185 (215) | 0.904 | 0.897 | 0.341 | 0.395 | 0.492 |
| al-Marasil | no_sama | 383 (405) | 0.634 | 0.613 | 0.052 | 0.076 | 0.117 |
| Tuhfa | no_idrak | 191 (223) | 0.881 | 0.869 | 0.251 | 0.309 | 0.351 |
| Tuhfa | mursal | 435 (516) | 0.884 | 0.873 | 0.292 | 0.354 | 0.437 |
| Tuhfa | no_sama | 594 (676) | 0.649 | 0.626 | 0.069 | 0.088 | 0.116 |

"Did not reach" and *mursal* pairs rank well below attested links; "did not hear" pairs between contemporaries are barely separated, because the two overlapped and dates cannot say whether they met. Pair-level AUROC is 0.007 to 0.023 below row-level in every cell, so row weighting does not drive the result. Recall at 0.05 is modest even where AUROC is high (10.6% and 25.1% for *no_idrak*): many denied pairs are near-misses, which an eight-year cut with several years of uncertainty does not settle. Figures `figures/p_meet_{marasil,tuhfa}_{no_idrak,mursal,no_sama}.png` show the distributions.

**Table 2.** False-flag rate on positives.

| positives | $n$ scored | @0.05 | @0.1 | @0.2 |
|---|---|---|---|---|
| explicit-audition rows (al-Bukhari, Muslim) + confirmed pairs | 18,126 rows | 0.22% | 0.28% | 1.32% |
| same, de-duplicated | 1,714 pairs | 0.35% | 0.70% | 0.99% |
| *sama* statements, al-Marasil | 39 pairs | 0.0% | 0.0% | 0.0% |
| *sama* statements, Tuhfa | 120 pairs | 5.8% | 5.8% | 9.2% |

Some flags on positives are correct in the sense of Section 6: an explicit formula can sit on a wrong date or identifier. The 7 Tuhfa *sama* pairs below 0.05 are gold-set errors, not model errors. In six, the quoted passage calls the narration *mursal* ("وعن عمر بن الخطاب مرسلا", "وذلك مرسل لم يلقهم" for al-Quraẓī ← ʿAlī and ← Ibn Masʿūd), so the extractor mislabelled a denial as an attestation. In the seventh, "سمع من ابن عمر" was resolved to ʿUmar b. al-Khaṭṭāb, the homonym failure the controls target.

### 5.2 Textual evidence for *no_sama*

<!-- Sources: data/metrics.json → negatives.*.{n_in_corpus, chron_recall_in_corpus@*, text_recall_in_corpus*,
student_irsal_frac}; matched figures from paper/derived_numbers.py §6. -->

Whether contemporaries met is classically decided from text: the formulae the student uses and his reputation for *irsāl* or *tadlīs*. We restrict each negative class to pairs that occur in the Six Books and compare, on the same pairs, **chronology only** ($p_{\text{meet}}$ below a threshold) with **chronology + text** (verdict `chronology_gap` or `suspect`, computed without the gold denial). A pair is flagged if any of its rows is.

**Circularity.** The production verdict includes `denied_by_critic`, set from the very denials we evaluate against. With it, in-corpus recall is 0.91 to 0.99 in every class; this shows only that the lookup works, and we do not treat it as a result.

**Table 3.** In-corpus recall of denied pairs. Chronology columns are over scored pairs, as stored in `metrics.json`.

| source | relation | in corpus | chron.@0.05 | chron.@0.1 | chron.@0.2 | chron. + text (excl. denial) | with denial (circular) | students with *irsāl* flag |
|---|---|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 22 | 0.095 | 0.143 | 0.190 | 0.091 | 0.909 | 0.867 |
| al-Marasil | mursal | 53 | 0.234 | 0.298 | 0.404 | 0.321 | 0.981 | 0.852 |
| al-Marasil | no_sama | 165 | 0.019 | 0.039 | 0.077 | 0.061 | 0.994 | 0.899 |
| Tuhfa | no_idrak | 80 | 0.258 | 0.333 | 0.379 | 0.263 | 0.963 | 0.923 |
| Tuhfa | mursal | 154 | 0.230 | 0.281 | 0.348 | 0.305 | 0.994 | 0.966 |
| Tuhfa | no_sama | 316 | 0.040 | 0.058 | 0.076 | 0.060 | 0.991 | 0.920 |

The text column counts unscored pairs as unflagged while the chronology columns exclude them. Table 4 recomputes chronology-only recall over the same pairs.

**Table 4.** Lift from textual evidence, matched denominator (`derived_numbers.py` §6).

| source | relation | pairs | chron.@0.05 | chron. + text | lift (points) | pairs gained |
|---|---|---|---|---|---|---|
| al-Marasil | no_idrak | 22 | 0.091 | 0.091 | 0.0 | 0 |
| al-Marasil | mursal | 53 | 0.208 | 0.321 | 11.3 | 6 |
| al-Marasil | no_sama | 165 | 0.018 | 0.061 | 4.2 | 7 |
| Tuhfa | no_idrak | 80 | 0.212 | 0.263 | 5.0 | 4 |
| Tuhfa | mursal | 154 | 0.201 | 0.305 | 10.4 | 16 |
| Tuhfa | no_sama | 316 | 0.035 | 0.060 | 2.5 | 8 |

The textual rule adds 10 to 11 points on *mursal* and 2.5 to 4.2 on *no_sama*; over nine in ten in-corpus *no_sama* pairs stay unflagged. Two reasons. The `suspect` rule fires only below $p_{\text{meet}} = 0.2$, so it cannot reach contemporaries; in every row chronology + text is at most matched chronology-only recall at 0.2 (0.182, 0.358, 0.073, 0.312, 0.305, 0.066). And the student-level flags barely discriminate: 85% to 97% of students in every negative class carry an *irsāl* flag, so the flag cannot say which of a student's teachers he did not hear from. That needs per-pair evidence.

### 5.3 Verdicts across the Six Books

<!-- Source: data/metrics.json → verdict_counts_by_book; data/run_report.md. -->

**Table 5.** Verdict counts (rows) per book.

| book | rows | ok | no_dates | denied_by_critic | data_error | chronology_gap | suspect |
|---|---|---|---|---|---|---|---|
| al-Bukhari (b-1) | 37,282 | 36,078 | 565 | 530 | 33 | 70 | 6 |
| Muslim (b-2) | 41,907 | 40,207 | 1,014 | 582 | 16 | 74 | 14 |
| Abu Dawud (b-3) | 28,832 | 25,076 | 2,966 | 654 | 48 | 76 | 12 |
| al-Tirmidhi (b-4) | 24,009 | 21,386 | 1,807 | 671 | 32 | 100 | 13 |
| al-Nasaʾi (b-5) | 33,375 | 30,582 | 2,038 | 606 | 59 | 78 | 12 |
| Ibn Maja (b-6) | 24,849 | 21,754 | 2,246 | 722 | 64 | 53 | 10 |
| total | 190,254 | 175,083 | 10,636 | 3,765 | 252 | 451 | 67 |

92.0% of rows are `ok` (`figures/verdicts_by_book.png`). The 451 `chronology_gap` rows come from 131 pairs; 97 of them carry an explicit formula, which cannot be literally true across an impossible gap and so points to a date or linking error. `no_dates` is lowest in al-Bukhari and Muslim (1.5% and 2.4%) and highest in Abu Dawud (10.3%), reflecting how many lesser-known narrators each book uses. `denied_by_critic` is a property of the gold sets, not a finding.

### 5.4 Date conflicts: mostly our parser

<!-- Sources: Task 7d report; data/date_errors*.csv; derived_numbers.py §3. -->

The first date-conflict flag compared narrative years literally: 934 narrators, 1,474 Six-Book `data_error` rows. The audit showed that it mostly measured our parser. In the 30 largest conflicts, 19 were century elision ("سنة سبع" for 607 in the *Siyar*), 8 were parser errors (thousands written as *alf* were not parsed; a death trigger ran on into a birth year), 3 took a relative's death year for the narrator's, and in none was the structured death year wrong. Among the 692 flagged narrators who died before 400, 441 had a narrative year differing from the structured year by an exact multiple of 100. The Taqrīb uses the same convention ("مات سنة ثمان وأربعين" for 148).

We fixed the parser (century adjustment as in Section 4.2, parsing of *alf*, a narrative-year cap of 1500, CE years skipped). The flag now marks 152 narrators, and 252 Six-Book rows touching 25 of them are `data_error` (from 1,474), while AUROC and false-flag rates are unchanged to three decimals. These 152 narrators and 252 rows are the audit set for the date cross-check. They have not been relabelled since the fix, and some residue remains: 8 of the 30 labelled narrators are still flagged (5 century elisions that the 20-year tolerance does not absorb, 2 parser errors, 1 wrong-person year), and 43 of the 152 died after 400. Most of the 152 (149) now differ by 20 to 99 years, the range where a genuine disagreement between sources is possible.

The stronger evidence on the narrator data comes from the `chronology_gap` links (Section 6). The preliminary study found the same kinds of error in a different narrator database.

## 6 Audit of the 50 weakest links

<!-- Source: the audit + data/weak_edges_labeled.csv; top-50 pairs identical after Task 7d (50/50). -->

The 50 weakest pairs in `data/weak_edges.csv` cover 122 hadith rows; all have $p_{\text{meet}} < 3 \times 10^{-9}$. Their formulae are ambiguous in 36, explicit in 13 and unclassified in 1. For each pair one analyst read both narrators' date texts and parsed values, every critic statement and *Tuhfa* passage on either narrator about *irsāl* or non-audition, the cached page of an example hadith (linked identifiers, chain type, printed isnad), and, where a date was in doubt, the dated phrases in the biographies. Each pair received one label (single rater, one pass; two labels rest on the standard printed text of Muslim and Abū Dāwūd and are marked "likely").

**Table 6.** Labels for the 50 weakest pairs.

| label | n | meaning |
|---|---|---|
| `genuine_gap` | 15 | the link is broken; a critic names it, the site types the chain *mursal*, or the author says the report was relayed or read |
| `db_date_error` | 25 | the date that drove $p_{\text{meet}}$ is wrong: 19 in the site's field, 6 our parser's reading |
| `chain_or_id_error` | 6 | the link is not in the printed isnad: a homonym linked to the wrong identifier, a dropped link, or merged routes |
| `plausible_but_undated` | 4 | the dates are too soft to decide |

**Only 15 of 50 are real breaks, and all were known.** Each is recognised classically: the site types the chain *mursal* (al-Zuhrī and Qatāda ← ʿUmar, al-Zuhrī ← Ḥafṣa, Hishām b. ʿUrwa ← al-Zubayr), a critic names the link (ʿAṭāʾ ← Surāqa, ʿUrwa ← Bashīr b. Saʿd, Mujāhid ← Ayman b. ʿUbayd), or the author marks the report as relayed or read (Abū Dāwūd's «حُدِّثت عن» from Hārūn b. al-Mughīra and Ibn Wahb, his «قرأت في كتاب» from ʿAbd Allāh b. Sālim, al-Shaʿbī's «أُخبِرت»). The top of the list tests data quality; it does not yield discoveries.

**The 19 site-side date errors come from 7 narrator records.** Abū ʿAwāna's birth year accounts for 9, Darrāj Abū al-Samḥ for 3, and Ḥakīm b. Ḥakīm and Sulaymān b. Kathīr for 2 each. The other 3 are century slips in later shaykhs: Sulaymān b. ʿAbd al-Jabbār ("151 هـ : 160 هـ" for a shaykh of al-Tirmidhī, i.e. 251–260), Abū Ḥuṣayn al-Rāzī ("51 هـ : 260 هـ") and al-Haytham b. Marwān (199 for about 299). Correcting these 7 records removes 19 of the 50 top flags. Darrāj's record pairs a birth of 125 from Ibn Ḥibbān with a death of 126 from Ibn Yūnus, a one-year life; Ḥakīm b. Ḥakīm's birth of 110 equals the upper bound of his own death range 101–110.

**The 6 parser errors are fixable.** In five, our parser took the first of several alternatives (ʿAlī b. al-Ḥusayn: the first of eight is 72, the consensus 94; ʿAmr b. Wāqid: 130 where two students born in 153 need the listed 171–180). In one it read "قبل ابن المقرئ بـ 12 سنة" (12 years before another man) as the year 9. A third fault, reading a range "X هـ : Y هـ" as exact X, compounds several of the site-side errors. None is fixed yet.

**The 6 chain or identifier errors** are a homonym (case 3 below), two dropped links (the site's text of Muslim omits al-Aʿmash before Abū Ḥāzim; Ibn Wahb ← al-Zuhrī lacks Yūnus b. Yazīd), two merges (the two Khālids of «أنبأنا خالد، عن خالد - وهو الحذاء»; Ḥammād b. Masʿada wired to al-Nasāʾī past Ibn Bashshār), and Ayyūb ← ʿĀʾisha, where the site wires a two-route chain from Maʿmar directly.

Five cases show what the method does.

1. **Abū ʿAwāna al-Waḍḍāḥ b. ʿAbd Allāh: a date the record itself calls wrong (9 pairs).** The site gives his birth as 122, which flags his narration from nine teachers who died between 100 and 121, among them Yaʿlā b. ʿAṭāʾ, Hilāl b. Abī Ḥumayd, ʿUthmān b. al-Mughīra and Abū Yaʿfūr. The same record quotes Ibn Ḥibbān (*al-Thiqāt*): «كان مولده سنة اثنتين وعشرين ومائة، وقال: هو خطأ؛ للشك فيه، لأنه صح أنه رأى ابن سيرين، ومات ابن سيرين قبل ذلك بمدة». The site even lists Abū ʿAwāna in Yaʿlā b. ʿAṭāʾ's confirmed-audition list. The score caught a structured date that the critic quoted beside it already rejects.
2. **Sulaymān b. Kathīr al-ʿAbdī: two dates, and the chains choose.** The structured death, 133, follows Ibn Ḥibbān and the Taqrīb («مات سنة ثلاث وثلاثين»); al-Dhahabī's *Siyar* has «مات في سنة ثلاث وستين ومائة». In Ibn Māja and al-Nasāʾī, ʿAbd al-Raḥmān b. Mahdī (b. 135) and ʿAffān (b. 134) each say «حدثنا سليمان بن كثير». The chronology sides with the *Siyar*.
3. **Bukhārī 7098, «حدثنا إسماعيل، حدثني مالك»: a homonym.** The site links the narrator to Ismāʿīl b. Jaʿfar (d. 180), who cannot be the direct shaykh of al-Bukhārī (b. 194). The narrator is Ismāʿīl b. Abī Uways (d. 226), Mālik's nephew. A $p_{\text{meet}}$ of 0 exposes an entity-resolution error on the site, not a defect in the *Ṣaḥīḥ*.
4. **al-ʿAlāʾ b. Ziyād → Ḥammād b. Zayd (al-Nasāʾī): a critic reasoning as the model does.** Al-ʿAlāʾ died in 94 and Ḥammād was born in 98. Al-Mizzī argues from the same dates: «إن صح تاريخ وفاته فإن رواية حماد بن زيد وأقرانه عنه مرسلة».
5. **Muḥammad b. Kaʿb al-Quraẓī ← al-ʿAbbās (Ibn Māja): a gap confirmed by name.** Yaʿqūb b. Shayba: «ولد في آخر خلافة علي … سنة أربعين، ولم يسمع من العباس، لأن العباس مات في خلافة عثمان». *Tuhfat al-Tahsil* lists al-ʿAbbās among the Companions al-Quraẓī «مرسل لم يلقهم».

## 7 Limitations

**Row weighting.** Frequent pairs dominate row counts; we report pair-level figures alongside.

**Coarse and imputed dates.** 85 narrators in Six-Book links have only an era date and 2,370 none. 77,876 rows rest on a birth year imputed from one untruncated lifespan prior, the same for all generations and weakest for the long-lived narrators (*muʿammarūn*) who matter most in disputed links.

**Name resolution and extraction.** Resolution is measured by coverage, not precision: 181 records are excluded as ambiguous and 16 are unresolved, and we have not hand-labelled a sample of resolved pairs, so we state no precision figure; the six controls test only one known failure. Both gold sets were extracted by a language model, and the Tuhfa *sama* errors (Section 5.1) show that misread relations and homonyms enter the gold sets directly. Extraction accuracy has not been measured against a manual reading. The hadith-specific filter is conservative (5 exclusions), and a denial for one route may have been generalised by later compilers.

**Date parsing.** The century-adjusted flag still leaves residual artefacts among its 152 narrators (Section 5.4), and the three parser faults found in the audit (first of several alternatives, ranges read as exact, relative dates) are not yet fixed. Formulae are taken as printed on the source page and may differ between editions; 150 rows remain unclassified.

**Audit.** The labels come from one analyst in one pass, with no second rater, and cover only the 50 weakest pairs and the 30 largest date conflicts.

**Scope.** Results cover the Six Books; 239 books are not yet fetched. Positives come from al-Bukhari and Muslim, among the most scrutinised links in the tradition; false flags on less-studied books may be higher.

**Chronology is not authenticity.** The scores locate links worth reading; they are not grades of hadith (Section 4.3).

## 8 Ethics, licensing and reproducibility

The data source is hdith.com, whose terms do not state a license for reuse. We therefore release only derived numbers: identifiers, years, uncertainty kinds, categorical flags, formula categories, scores and verdicts. No hadith text, isnad text, biography or critic statement is redistributed, and the export applies a column denylist. The dataset is released under CC-BY-4.0 with attribution to hdith.com, the code under MIT, and we will contact the site's owners before publishing the dataset.

The site's robots.txt explicitly allows crawlers and disallows only preview and embed paths, which we never requested; our crawler sent an identifying User-Agent. The first ~6,700 pages were fetched through Firecrawl. For the rest we deviated from our design, which capped the local crawler at 3 requests per second: it ran up to 48 parallel workers with no throttling, about 500 to 700 pages per minute against a site latency of about 6 s per page. We observed no rate-limit (429) or server (5xx) responses, but the load exceeded what our design allowed.

Hadith grading has religious and practical consequences; a `chronology_gap` is not a ruling and should not be presented as one. The gold sets encode particular critics' judgements, which later scholars sometimes disputed; agreement with them measures reproduction, not correctness.

**Reproducibility.** The pipeline runs as `uv run python -m isnad.cli <command>`: `fetch` (narrator and hadith pages into a local cache), `build` (cache to parquet tables), `gold` (resolve the al-Marasil and Tuhfa records), `score --denials data/denials.parquet`, `validate` (`data/metrics.json`, figures), `report` (`weak_edges.csv`, `date_errors.csv`) and `export`. Every number in this paper comes from those outputs or from `PYTHONPATH=. uv run python paper/derived_numbers.py`. The release contains `edges.parquet` (identifiers, position, formula, chain type), `edge_scores.parquet` ($p_{\text{meet}}$, `how`, evidence flags, verdict), `rawi_dates.parquet` (narrator identifiers, generation, years, deviations, kinds, flags, teacher and student identifier lists) and a manifest; the code, the Tuhfa extraction prompt and the al-Marasil pairs extracted from OpenITI are in the repository. Not released: the raw page cache, narrator names, hadith and isnad text, biographies and critic statements, the Tuhfa extractions (which quote hdith.com pages), and the audit label files. Re-fetching reproduces them, subject to later changes on the site.

## 9 Conclusion

A closed-form meeting probability reproduces the critics' "did not reach" and *mursal* judgements on the Six Books (AUROC 0.79 to 0.90) while flagging under a quarter of a percent of attested links; it cannot decide whether contemporaries met, and student-level textual evidence helps little there. Among its most confident flags, the genuine breaks are ones the critics already knew; the rest point to specific errors in the narrator records and in chain linking, including a birth year that the record's own critic calls a mistake. That makes the score most useful as an auditing tool for the databases computational hadith work relies on. Next steps are to fix the remaining parser faults, correct or report the 7 site records, measure resolution and extraction precision on hand-labelled samples, use pair-level audition evidence for *no_sama*, and extend the fetch beyond the Six Books.

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
