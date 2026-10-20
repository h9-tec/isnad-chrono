# Weak-edge and date-error audit (2026-10-20)

Manual audit of the top 50 `chronology_gap` edges (`data/weak_edges.csv`) and the top 30 rows of `data/date_errors.csv` by `diff`. It tests spec §5 claim 3 ("finds date errors in widely used rijal data") and supplies the "Top-50 edges with one-line manual checks" table that paper outline §5 asks for. Machine-readable labels: `data/weak_edges_labeled.csv` (columns `label`, `cause`, `justification`) and `data/date_errors_labeled.csv` (`label`, `justification`). Both are gitignored.

## Method

For each weak edge I read three things. First, both narrators' `birth_text` and `death_text` together with the parsed year and kind (`data/rawi.parquet`). Second, every critic statement and Tuḥfat al-Taḥṣīl passage for either narrator that mentions مرسل / لم يسمع / لم يدرك / لم يلق / منقطع / أرسل (`opinions.parquet`, `tuhfa.parquet`). Third, the cached page of the first example hadith: the linked `isnad` nodes, the site's `chain_type`, and the printed isnād text (`isnad_prefix`/`isnad_html`). Where the date was in doubt I also read the dated phrases (مات/توفي/ولد) in the cached rawi biographies (Tahdhīb, Taqrīb, Siyar, Taʾrīkh al-Islām, al-Thiqāt). Each edge got exactly one label:

- `db_date_error`: the structured date that drove p_meet is wrong. The `cause` column says where the error came from. `site_data` means hdith.com's field itself is wrong. `our_parser` means the site's text is fine but `isnad.dates.parse_year` picked the wrong figure.
- `chain_or_id_error`: the edge does not exist in the printed isnād. Causes include a homonym linked to the wrong id, a dropped link, or two routes merged.
- `genuine_gap`: the link really is disconnected. Evidence is a classical critic statement on this link, the site's own `chain_type` مرسل, or the author's own wording (حُدِّثت عن, قرأت في كتاب).
- `plausible_but_undated`: the dates are too soft to decide either way.

For date errors, I traced every narrative year back to the phrase that `isnad.dates.narrative_years` extracted it from. Each row got one of four labels: `century_dropped` (the source omits the century by convention), `wrong_person_year`, `parser_error`, or `genuine_conflict_in_sources`.

One analyst did the labelling in a single pass, with no second rater. Edges 14 and 38 rest on the standard printed text of Muslim and Abū Dāwūd, not on the site's text, and are marked "likely".

## Label counts

| Top-50 weak edges | n |
|---|---|
| db_date_error | 25 (site_data 19, our_parser 6) |
| genuine_gap | 15 |
| chain_or_id_error | 6 |
| plausible_but_undated | 4 |

| Top-30 date_errors | n |
|---|---|
| century_dropped | 19 |
| parser_error | 8 |
| wrong_person_year | 3 |
| genuine_conflict_in_sources | 0 (3 rows also carry a 1-year source disagreement: 22467, 21288, 14003) |

## Findings

1. **Only 15/50 top flags are real breaks.** Every one of those 15 is already recognised classically: the site types it مرسل, a critic names it, or the author marks it as reported or read rather than heard. The other 35 are artefacts: 25 date errors, 6 chain/ID errors and 4 undecidable cases. Do not report the top of the ranked list as discoveries. Report it as a test of data quality.
2. **The 19 `site_data` edges trace back to just 7 narrator records.** Abū ʿAwāna's birth 122 alone accounts for 9 edges. Darrāj accounts for 3, and Ḥakīm b. Ḥakīm and Sulaymān b. Kathīr for 2 each. The last 3 edges come from century slips in later shaykhs: Sulaymān b. ʿAbd al-Jabbār "151:160", Abū Ḥuṣayn "51:260" and al-Haytham b. Marwān "199". Fixing these 7 records removes 19 of the 50 top flags.
3. **Two parser fixes would remove more flags.**
   - (a) Read a range "X هـ : Y هـ" or "بين X و Y" as a range. Today it is read as the exact lower bound. This affects the teacher side of edges 0, 1, 26, 35, 40, 41, 43, 44 and 46.
   - (b) Treat lists with three or more alternatives (أو/وقيل) as alternatives. Today the first figure is taken; see edges 2, 8, 13, 15 and 39 (ʿAlī b. al-Ḥusayn: first of eight alternatives is 72, the consensus is 94).
   - (c) Do not parse relative dates such as "قبل ابن المقرئ بـ 12 سنة". Edge 16 currently reads it as the year 9.
4. **The top of `date_errors.csv` measures our parser, not errors in the rijal data.** All 30 top rows are post-500 AH scholars. `narrative_years` discards values above 400 and has no ألف. So for these scholars the only years that survive are the short forms where the source leaves the century implicit, which is the normal style of al-Ḍawʾ al-Lāmiʿ, Siyar and Taʾrīkh al-Islām (e.g. "سنة سبع"). In 0/30 rows is the structured death year actually wrong.
   - 242/934 rows (26%) have a death year above 400.
   - Among the 692 earlier rows, 441 have some narrative year that differs from the structured year by an exact multiple of 100. The cause is the same century-elision convention, which the Taqrīb uses too ("مات سنة ثمان وأربعين" for 148).
   - Spec §5 claim 3 should be reworded. "Century-dropped" is a convention of the sources, not an error in them. The real errors in the rijal data are the ones the weak-edge audit found (finding 2).
   - The date-conflict check should either (i) be limited to death_year ≤ 400 and accept a match modulo 100, or (ii) infer the century from the structured year before comparing.

## Highlighted cases (for the paper)

1. **Abū ʿAwāna al-Waḍḍāḥ b. ʿAbd Allāh (rawi 6785): a date the source itself calls wrong (9 edges).** The site gives his birth as 122, which flags his narration from nine teachers who died 100–121: Yaʿlā b. ʿAṭāʾ, Hilāl b. Abī Ḥumayd, ʿUthmān b. al-Mughīra, Abū Yaʿfūr, and others. The same record quotes Ibn Ḥibbān (al-Thiqāt): «كان مولده سنة اثنتين وعشرين ومائة، وقال: هو خطأ؛ للشك فيه، لأنه صح أنه رأى ابن سيرين، ومات ابن سيرين قبل ذلك بمدة». The site even lists Abū ʿAwāna in Yaʿlā b. ʿAṭāʾ's own samāʿ list. This is the clearest case of the pipeline catching a structured date that the critic quoted beside it already rejects.
2. **Sulaymān b. Kathīr al-ʿAbdī (2630): two dates in the sources, and the chains choose between them.** The structured death is 133, from Ibn Ḥibbān and Taqrīb «مات سنة ثلاث وثلاثين». Al-Dhahabī's Siyar has «مات في سنة ثلاث وستين ومائة». Ibn Māja and al-Nasāʾī have ʿAbd al-Raḥmān b. Mahdī (b. 135) and ʿAffān (b. 134) each saying «حدثنا سليمان بن كثير». The chronology flag sides with the Siyar date.
3. **Bukhārī 7098, «حدثنا إسماعيل، حدثني مالك» (homonym).** The site links the narrator to Ismāʿīl b. Jaʿfar (d. 180), who could not be al-Bukhārī's (b. 194) direct shaykh. The narrator is Ismāʿīl b. Abī Uways (d. 226), Mālik's nephew. A p_meet of 0 here exposes an entity-resolution error, not a defect in Ṣaḥīḥ al-Bukhārī.
4. **al-ʿAlāʾ b. Ziyād → Ḥammād b. Zayd (al-Nasāʾī, hadith 69817): a critic who reasoned the same way as the model.** Al-ʿAlāʾ died in 94 and Ḥammād was born in 98. Al-Mizzī states the same argument from dates: «إن صح تاريخ وفاته فإن رواية حماد بن زيد وأقرانه عنه مرسلة». This is a genuine gap that the classical method reached in the same way.
5. **Muḥammad b. Kaʿb al-Quraẓī ← al-ʿAbbās (Ibn Māja, hadith 108105): a genuine gap confirmed by name.** Yaʿqūb b. Shayba: «ولد في آخر خلافة علي … سنة أربعين، ولم يسمع من العباس، لأن العباس مات في خلافة عثمان». Tuḥfat al-Taḥṣīl also lists al-ʿAbbās among the Companions al-Quraẓī «مرسل لم يلقهم».

Runner-up for a date-error example: al-Suyūṭī (15122). His narrative year 67 comes from «ولزمه حتى مات سنة سبع وستين», which is his teacher's death in 867, not his own (`wrong_person_year`).

## Table 1: top-50 weak edges

| # | teacher (d.) → student (b.) | term | hadith | label | justification |
|---|---|---|---|---|---|
| 0 | سليمان بن عمرو العتواري (91) → دراج أبي السمح (125) | عن | 100261 | db_date_error (site_data) | Darrāj's birth field holds Ibn Ḥibbān's anomalous 'مولده سنة خمس وعشرين ومائة' (paired with his d. 182) next to Ibn Yūnus's death 126, giving a one-year life; the teacher's range '91 هـ : 100 هـ' is also read as exact 91. |
| 1 | سليمان بن عبد الجبار الخياط (151) → الترمذي (210) | حدثنا | 100329 | db_date_error (site_data) | A ḥādiya-ʿashra-generation shaykh of al-Tirmidhī cannot die in '151 هـ : 160 هـ'; the century is dropped (read 251–260), and the range is parsed as exact 151. |
| 2 | عمرو بن واقد القرشي (130) → محمد بن المبارك القلانسي (153) | حدثنا | 100372 | db_date_error (our_parser) | death_text is '130 هـ : 140 هـ ، وقيل : 171 هـ : 180 هـ' and we took the first figure; two students born 153 say حدثنا عمرو بن واقد, which only the 171–180 alternative allows (Taqrīb: 'مات بعد الثلاثين'). |
| 3 | عبد الرحمن بن حجيرة الخولاني (83) → دراج أبي السمح (125) | عن | 100772 | db_date_error (site_data) | Same Darrāj record: birth 125 (Ibn Ḥibbān) beside death 126 (Ibn Yūnus/Taqrīb 'مات سنة ست وعشرين'); Darrāj is a well-attested student of Ibn Ḥujayra (d. 83). |
| 4 | عيسى بن هلال السليحي (100) → دراج أبي السمح (125) | عن | 100782 | db_date_error (site_data) | Same Darrāj birth-125 artefact; nothing in the chain or the critics questions Darrāj ← ʿĪsā b. Hilāl. |
| 5 | إسحاق بن طلحة القرشي التيمي (56) → إسحاق بن يحيى بن طلحة التيمي (61) | عن | 102523 | plausible_but_undated | Ibn Yaḥyā's birth 61 is an estimate (al-Ṣarīfīnī: 'مولده تقديرا سنة إحدى وستين') and the uncle's death is disputed (56 per Khalīfa, 'بقي إلى زمن يزيد' per al-Zubayr b. Bakkār); no critic calls عن عمه mursal. |
| 6 | الزبير بن العوام (36) → هشام بن عروة بن الزبير (60.5) | فقال | 102632 | genuine_gap | The site itself types the chain مرسل: Hishām (b. 60/61) reports 'فقال الزبير' about a grandfather who died 36. |
| 7 | العباس بن عبد المطلب عم رسول الله (32) → محمد بن كعب بن سليم القرظي (40) | عن | 108105 | genuine_gap | Yaʿqūb b. Shayba: 'ولد في آخر خلافة علي … سنة أربعين، ولم يسمع من العباس'; Tuḥfat al-Taḥṣīl lists al-ʿAbbās among those he did not meet. |
| 8 | علي بن الحسين زين العابدين (72) → زيد بن علي بن الحسين (80) | عن | 108821 | db_date_error (our_parser) | death_text lists eight alternatives ('72 … أو 92 … 94 … 100'); we took the first (72) although the consensus is 94 (al-Zuhrī: he was 23 at Karbalāʾ), and Zayd b. ʿAlī is his son. |
| 9 | أسعد بن سهل بن حنيف (100) → حكيم بن حكيم بن عباد الأنصاري (110) | عن | 111767 | db_date_error (site_data) | Ḥakīm b. Ḥakīm's birth '110 هـ' equals the upper bound of his own death range '101 هـ : 110 هـ' — an internally impossible record with no dating source in the bios. |
| 10 | نافع بن جبير بن مطعم النوفلي (99) → حكيم بن حكيم بن عباد الأنصاري (110) | عن | 112008 | db_date_error (site_data) | Same Ḥakīm b. Ḥakīm record (birth 110, death 101–110); Nāfiʿ b. Jubayr (d. 99) is an ordinary teacher for a khāmisa narrator. |
| 11 | إسحاق بن طلحة القرشي التيمي (56) → طلحة بن يحيى بن طلحة التيمي (61) | عن | 112126 | plausible_but_undated | Ṭalḥa b. Yaḥyā's birth 61 is from al-Fallās ('ولد سنة 61 هو والأعمش'), the uncle Isḥāq's death is 56 or 'until Yazīd'; no critic discusses the link — dates too soft to decide. |
| 12 | إسماعيل بن جعفر بن أبي كثير الزرقي (180) → البخاري (194) | في حكم العنعنة | 11313 | chain_or_id_error | In Bukhārī 7098 'حدثنا إسماعيل' is Ismāʿīl b. Abī Uways (d. 226), not the homonym Ismāʿīl b. Jaʿfar (d. 180) that the site linked. |
| 13 | عمرو بن واقد القرشي (130) → هشام بن عمار (153) | حدثنا | 113695 | db_date_error (our_parser) | Same ʿAmr b. Wāqid record: first alternative 130 taken; Hishām b. ʿAmmār (b. 153) says 'حدثنا عمرو بن واقد', consistent only with the listed 171–180. |
| 14 | سلمان الأعرج مولى عزة الأشجعية (100.5) → أبو معاوية الضرير (113) | عن | 11882 | chain_or_id_error | Muslim's chain is 'وكيع وأبو معاوية عن الأعمش عن أبي حازم'; the site's text omits al-Aʿmash, so Abū Muʿāwiya (b. 113) is wired directly to Abū Ḥāzim al-Ashjaʿī (d. ~100). |
| 15 | مالك بن ربيعة أبو أسيد الساعدي (30) → إبراهيم بن محمد بن طلحة التيمي (36) | سمعت | 19242 | db_date_error (our_parser) | death_text gives five dates (al-Wāqidī 30, al-Madāʾinī 60, al-ʿAskarī 65 …) and we took 30; the matn itself says 'سمعت أبا أسيد خطيبا عند ابن عتبة' (Umayyad Medina), supporting 60. |
| 16 | حصين بن محمد السالمي (9) → الزهري (50) | صريح في السماع | 6162 | db_date_error (our_parser) | death_text 'قبل ابن المقرئ بــ 12سنه' (relative to another person) was parsed as year 9 (12 − 3 for 'قبل'); al-Zuhrī's 'حدثني' from him is the attested Bukhārī chain. |
| 17 | أم كلثوم بنت أبي بكر الصديق (41) → طلحة بن يحيى بن طلحة التيمي (61) | عن | 67301 | plausible_but_undated | Umm Kulthūm (born after Abū Bakr's death) has only an unsourced range '41 هـ : 50 هـ' and Ṭalḥa b. Yaḥyā (her grandson) a single-source birth 61; undecidable. |
| 18 | حفصة بنت عمر بن الخطاب (41) → الزهري (50) | عن | 67314 | genuine_gap | Chain typed مرسل by the site: Mālik 'عن ابن شهاب عن عائشة وحفصة' — al-Zuhrī (b. 50+) never met Ḥafṣa (d. 41/45); this is the well-known Muwaṭṭaʾ mursal. |
| 19 | حر بن الصياح النخعي (111) → الوضاح بن عبد الله اليشكري (122) | عن | 67347 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); Abū ʿAwāna ← al-Ḥurr b. al-Ṣayyāḥ is in al-Nasāʾī. |
| 20 | خالد الحذاء (141) → وهب بن بقية الواسطي (155) | أنبأنا | 67386 | chain_or_id_error | Text is 'أنبأنا خالد، عن خالد - وهو الحذاء'; the first Khālid (b. ʿAbd Allāh al-Wāsiṭī) was dropped and the two homonyms merged. |
| 21 | الهيثم بن مروان بن الهيثم العنسي (199) → النسائي (214.5) | أخبرنا | 69274 | db_date_error (site_data) | Taʾrīkh al-Islām text reads 'مات سنة تسع وتسعين ومائة', but he is a ḥādiya-ʿashra shaykh of al-Nasāʾī narrating from Muḥammad b. Bakkār (d. 216): the century is wrong (≈299). |
| 22 | حماد بن مسعدة (202) → النسائي (214.5) | حدثني | 69745 | chain_or_id_error | Text 'حدثنا محمد بن بشار، وحدثني حماد بن مسعدة، قالا' is garbled; al-Nasāʾī (b. 215) receives via Ibn Bashshār, and the site linked Ḥammād (d. 202) to al-Nasāʾī directly. |
| 23 | العلاء بن زياد بن مطر (94) → حماد بن زيد (98) | عن | 69817 | genuine_gap | al-Mizzī on this exact link: 'إن صح تاريخ وفاته فإن رواية حماد بن زيد وأقرانه عنه مرسلة' (al-ʿAlāʾ d. 94, Ḥammād b. 98). |
| 24 | أيمن بن عبيد بن زيد الحبشي (8) → مجاهد بن جبر المخزومي (21) | عن | 70959 | genuine_gap | Abū Ḥātim: 'هو مرسل … وليست له صحبة' and al-Shāfiʿī: this Ayman 'ليس بابن أم أيمن ولم يدرك النبي'; either way the link is classically mursal (identity also disputed). |
| 25 | إبراهيم النخعي (94) → عبد الله بن المبارك (118.5) | يقول | 72091 | genuine_gap | Chain typed 'معلق، مرسل' by the site: Ibn al-Mubārak (b. 118) quotes a saying of al-Nakhaʿī (d. 96) without isnād. |
| 26 | أبو حصين بن يحيى بن سليمان الرازي (51) → أبو داود السجستاني (202.5) | حدثنا | 90836 | db_date_error (site_data) | death_text '51 هـ : 260 هـ' drops the century of the lower bound (251–260) for a ʿāshira-generation shaykh of Abū Dāwūd; parsed as exact 51. |
| 27 | عبد الله بن سالم الوحاظي (179) → أبو داود السجستاني (202.5) | قرأت في كتاب | 91142 | genuine_gap | Abū Dāwūd declares wijāda: 'وقرأت في كتاب عبد الله بن سالم بحمص' — no hearing is claimed. |
| 28 | عمر بن الخطاب (23) → عمر بن عبد العزيز بن مروان (59) | في حكم العنعنة | 93115 | genuine_gap | ʿUmar b. ʿAbd al-ʿAzīz (b. 59–63) reports a ruling of ʿUmar (d. 23) via 'ابن لعدي بن عدي'; a report about, not from, ʿUmar — classical irsāl. |
| 29 | عمر بن الخطاب (23) → الزهري (50) | أن | 93121 | genuine_gap | Chain typed مرسل by the site: 'عن الزهري قال: قال عمر'. |
| 30 | عمر بن الخطاب (23) → قتادة بن دعامة (60.5) | أن | 94499 | genuine_gap | Chain typed مرسل by the site: 'عن قتادة أن عمر بن الخطاب قال'. |
| 31 | هارون بن المغيرة المروزي (181) → أبو داود السجستاني (202.5) | حدثت عن | 94933 | genuine_gap | Abū Dāwūd declares an unnamed intermediary: 'وحُدِّثت عن هارون بن المغيرة'. |
| 32 | سراقة بن مالك المدلجي (24) → عطاء بن أبي رباح (27) | قال | 67976 | genuine_gap | Ibn Ḥajar (Tahdhīb): 'رواية الحسن وطاوس وعطاء عنه منقطعة'; al-Nasāʾī's text is 'عن عطاء قال: قال سراقة'. |
| 33 | بشير بن سعد بن ثعلبة الخزرجي (11) → الشعبي (19.5) | أخبرت | 69258 | genuine_gap | al-Shaʿbī says 'أُخبِرت أن بشير بن سعد…', and al-Mizzī: with Bashīr's death in 13 'تكون رواية هؤلاء القوم عنه مرسلة سوى ابنه النعمان'. |
| 34 | بشير بن سعد بن ثعلبة الخزرجي (11) → عروة بن الزبير (26) | أن | 69252 | genuine_gap | Abū Ḥātim: 'عروة بن الزبير … عن بشير والد النعمان مرسل' (Ibn Abī Ḥātim, al-Marāsīl). |
| 35 | القاسم بن عبد الله بن عمر بن حفص بن عاصم بن عمر بن الخطاب (151) → هشام بن عمار (153) | حدثنا | 112096 | plausible_but_undated | al-ʿUmarī's death is 'مات بعد الستين' (Taqrīb) / 150–160 (al-Bukhārī, al-Awsaṭ), parsed as exact 151; Hishām b. ʿAmmār (b. 153) would be a child either way — no critic discusses it. |
| 36 | وقدان العبدي أبو يعفور (120) → الوضاح بن عبد الله اليشكري (122) | عن | 12969 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110). |
| 37 | يعلى بن عطاء الطائفي (120) → الوضاح بن عبد الله اليشكري (122) | عن | 17226 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); the site's own samāʿ list for Yaʿlā b. ʿAṭāʾ includes Abū ʿAwāna. |
| 38 | الزهري (123) → عبد الله بن وهب المصري (125) | أخبرني | 95416 | chain_or_id_error | Site text 'نا ابن وهب أخبرني ابن شهاب' lacks the expected intermediary (Yūnus b. Yazīd); Ibn Wahb (b. 125) never met al-Zuhrī (d. 124/125). Likely dropped link. |
| 39 | عباس بن سهل بن سعد الساعدي (75) → عبد الرحمن بن سليمان الأوسي (101.5) | عن | 8150 | db_date_error (our_parser) | death_text lists '75 … أو 90 … أو 95 … في حدود 120' and we took 75; al-Bukhārī's chain via al-Ghasīl (b. ~101) fits only the last alternative. |
| 40 | عبد الأعلى بن عامر الثعلبي (121) → الوضاح بن عبد الله اليشكري (122) | عن | 100274 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); the teacher's range '121 هـ : 140 هـ' is also parsed as exact 121. |
| 41 | عثمان بن المغيرة الأعشى (121) → الوضاح بن عبد الله اليشكري (122) | عن | 101472 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); teacher's 'بين 121 هـ و130 هـ' parsed as exact 121. |
| 42 | سليمان بن كثير الأصيد (133) → عبد الرحمن بن مهدي (134) | حدثنا | 110386 | db_date_error (site_data) | Structured death 133 follows Ibn Ḥibbān/Taqrīb, but al-Dhahabī (Siyar) has 'مات في سنة ثلاث وستين ومائة' and both Ibn Mahdī (b. 135) and ʿAffān (b. 134) say حدثنا سليمان بن كثير. |
| 43 | هلال بن أبي حميد (121) → الوضاح بن عبد الله اليشكري (122) | عن | 12812 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); teacher's range '121 هـ : 130 هـ' parsed as exact 121. |
| 44 | خالد بن علقمة الوادعي (121) → الوضاح بن عبد الله اليشكري (122) | عن | 63904 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); teacher's range '121 هـ : 130 هـ' parsed as exact 121. |
| 45 | سليمان بن كثير الأصيد (133) → عفان بن مسلم الصفار (134) | حدثنا | 69225 | db_date_error (site_data) | Same Sulaymān b. Kathīr record: Siyar 'مات في سنة ثلاث وستين ومائة' vs structured 133; ʿAffān (b. 134) hears from him. |
| 46 | إبراهيم بن مهاجر بن جابر البجلي (121) → الوضاح بن عبد الله اليشكري (122) | عن | 89487 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); teacher's range '121 هـ : 130 هـ' parsed as exact 121. |
| 47 | عائشة بنت أبي بكر الصديق (57.5) → أيوب السختياني (67) | أن | 15935 | chain_or_id_error | Muslim's text is a two-route chain from Maʿmar ('…أيوب… قال الزهري: فأخبرني عروة عن عائشة'); the site wired Ayyūb directly to ʿĀʾisha. |
| 48 | عبد الله بن وهب المصري (197) → أبو داود السجستاني (202.5) | حدثت عن | 94889 | genuine_gap | Abū Dāwūd declares an unnamed intermediary: 'حُدِّثتُ عن ابن وهب'. |
| 49 | حطان بن خفاف الجرمي (100) → الوضاح بن عبد الله اليشكري (122) | عن | 71913 | db_date_error (site_data) | Abu ʿAwāna's birth 122 is wrong: Ibn Ḥibbān (al-Thiqāt) reports 'كان مولده سنة اثنتين وعشرين ومائة' and then 'هو خطأ … لأنه صح أنه رأى ابن سيرين' (d. 110); the text names the teacher by kunya 'أبي الجويرية' (= Ḥiṭṭān b. Khufāf, d. ~100). |

## Table 2: top-30 date_errors by diff

| rawi_id | narrator | structured death | narrative years | diff | label | evidence |
|---|---|---|---|---|---|---|
| 21664 | محمد حياة بن إبراهيم السندي | 1163 | 3|3 | 1160 | parser_error | 'سنة ثلاث وسنين ومائة وألف' — source typo وسنين stops the number at 3, and the parser has no ألف. |
| 21681 | سراج أحمد بن مرشد السرهندي | 1230 | 230|230 | 1000 | parser_error | 'سنة ثلاثين ومائتين والف' → 230: thousands (ألف) are not parsed. |
| 21739 | عبد الحي اللكهنوي | 1304 | 304 | 1000 | parser_error | 'سنة أربع وثلاثمائة والف' → 304: thousands not parsed. |
| 21757 | محمد هاشم بن عبد الغفور السندي | 1174 | 174|174 | 1000 | parser_error | 'توفي سنة أربع وسبعين ومائة والف' → 174: thousands not parsed. |
| 22362 | ابن العماد عبد الحي بن أحمد بن محمد | 1089 | 89 | 1000 | parser_error | 'سنة تسع وثمانين والف' → 89: thousands not parsed. |
| 15122 | السيوطي | 911 | 67|67 | 844 | wrong_person_year | 'ولزمه حتى مات سنة سبع وستين' is the death of al-Suyūṭī's teacher (867), not his own. |
| 15074 | ابن حجر | 852 | 52 | 800 | century_dropped | al-Ḍawʾ al-Lāmiʿ: 'توفي في أواخر ذي الحجة سنة اثنتين وخمسين' (852, century implicit). |
| 15086 | إبراهيم بن موسى الأبناسي | 802 | 2|2 | 800 | century_dropped | al-Ḍawʾ: 'فمات في الطريق … سنة اثنتين' (802). |
| 21589 | الهيثمي | 807 | 7|7 | 800 | century_dropped | al-Ḍawʾ: 'حتى مات … سنة سبع بالقاهرة' (807). |
| 22345 | الفيروزآبادى | 817 | 17 | 800 | century_dropped | al-Ḍawʾ: 'مات … سنة سبع عشرة بزبيد' (817). |
| 22367 | ياقوت الحموي | 626 | 6|6 | 620 | century_dropped | Taʾrīkh al-Islām annal entry: 'ومات … سنة ست هذه' (626). |
| 21796 | عبد الكريم بن محمد الرافعي | 623.5 | 23|3|23|3 | 600.5 | century_dropped | 'وتوفي في حدود سنة ثلاث وعشرين'; Ibn al-Ṣalāḥ 'أواخر سنة ثلاث أو أوائل سنة أربع' (623/624). |
| 13973 | ابن طبرزذ عمر بن محمد الدارقزي | 607 | 7 | 600 | century_dropped | Siyar: 'توفي في تاسع رجب سنة سبع' (607); the full 'سنة سبع وستمائة' is discarded by the ≤400 cap. |
| 16596 | عبد الرحيم ابن السمعاني | 614 | 14|14 | 600 | parser_error | 'ما بين سنة أربع عشرة أو ست عشرة وستمائة' → 14: the shared century after the alternative is lost (and >400 is capped). |
| 17644 | أحمد بن شيرويه بن شهردار الديلمي | 625 | 25|25 | 600 | century_dropped | 'توفي بها … من سنة خمس وعشرين' (625). |
| 21638 | ابن المنير أحمد بن محمد بن منصور الجذامي | 683 | 83|83 | 600 | century_dropped | Ḥusn al-Muḥāḍara: 'ومات … سنة ثلاث وثمانين بالإسكندرية' (683). |
| 21694 | المنذري | 643 | 43|43 | 600 | century_dropped | Siyar on Rashīd al-Dīn Ibn al-Mundhirī: 'مات في ذي القعدة سنة ثلاث وأربعين' (643). |
| 22339 | عبد العزيز بن عبد السلام السلمي | 660 | 60|60 | 600 | century_dropped | 'مات في عاشر جمادى الأولى سنة ستين' (660). |
| 22467 | نصر بن أبي الفرج ابن الحصري | 618.5 | 18|19|19|18|19|18|19|18|19|19 | 599.5 | century_dropped | 'مات … سنة تسع عشرة' / 'سنة ثمان عشرة' (618/619 — a 1-year source disagreement on top); the explicit 'وستمائة' form is capped. |
| 21730 | عبد الرحمن بن محمد بن أحمد الجماعيلي | 682 | 43|85|72|68|85 | 597 | wrong_person_year | Years are his relatives' deaths: 'فمات سنة ثلاث وأربعين' (a son), 'فاطمة التي ماتت سنة خمس وثمانين', 'ست العرب التي توفيت سنة اثنتين وسبعين'. |
| 16587 | ابن القارص الحسين بن أبي نصر الحريمي | 605 | 15|15 | 590 | parser_error | 'وتوفي في التاسع والعشرين من شعبان، وولد سنة خمس عشرة' — the trigger window runs past توفي into the birth year (515). |
| 20906 | محمد بن أبي زيد الكراني | 597 | 7|7 | 590 | century_dropped | Siyar: 'مات في ثالث شوال سنة سبع' (597). |
| 21288 | فرحة بنت قراطاش العوني | 598.5 | 9|9 | 589.5 | century_dropped | 'وتوفيت … سنة تسع؛ قاله ابن النجار. وقال ابن الدبيثي: سنة ثمان' (598/599; minor real disagreement). |
| 21720 | ابن رشد | 594.5 | 4|5 | 589.5 | century_dropped | Siyar on Ibn Rushd: 'في أواخر سنة أربع … وقيل … سنة خمس' (594/595). |
| 18539 | رقية بنت أحمد بن محمد بن قدامة | 621 | 36|36 | 585 | parser_error | 'وتوفيت في شعبان، وولدت في حدود سنة ست وثلاثين' — trigger reads the birth year (536) as a death year. |
| 14003 | أحمد بن حمزة بن أبي الحسن المعدل | 585 | 5|5 | 580 | century_dropped | Ibn Ṣaṣrā: 'توفي في نصف ذي الحجة سنة خمس' (585), which al-Dhahabī doubts ('ولعله سبق قلم'). |
| 15131 | الحازمي | 584 | 4 | 580 | century_dropped | 'ومات معه في سنة أربع الأمير…' (584); the full 'أربع وثمانين وخمسمائة' is capped. |
| 16880 | عبد الغني المقدسي الجماعيلي | 600 | 29 | 571 | wrong_person_year | 'مات كهلا في شهر رمضان سنة تسع وعشرين' is his son Abū Mūsā (629), in a paragraph on his children. |
| 12926 | وجيه بن هبة الله السقطي | 567 | 7|7 | 560 | century_dropped | His son: 'توفي أبي في ذي القعدة سنة سبع بصريفين' (567). |
| 13393 | عمر بن محمد بن عبد الله البسطامي | 562 | 2|2 | 560 | century_dropped | 'توفي سنة اثنتين ببلخ' (562). |
