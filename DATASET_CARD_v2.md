---
license: cc-by-4.0
language:
- ar
tags:
- hadith
- isnad
- isnad-cum-matn
- chronology
- common-link
pretty_name: isnad-chrono
configs:
{{configs_yaml}}
---

# isnad-chrono {{version}}

## Summary

A corpus-wide isnad-cum-matn dataset derived from hdith.com: every parsed transmission chain, the
takhrij groups that bundle the versions of one report, merged chain trees with their common links
(k = 2 and k = 3), inferred death intervals for every narrator, report dates, and the attribution
of wording changes to the transmitter who introduced them. The release contains derived numbers,
ids, short categorical labels and 16-hex text hashes only. No hadith text, matn, narrator name or
critic statement is redistributed.

- Source: hdith.com (narrator ids are hdith.com `p-N` slugs, hadith ids are hdith.com entry ids,
  group ids are hdith.com takhrij group slugs). Years are Hijri.
- License of the derived numbers: CC-BY-4.0 with attribution to hdith.com as the data source.
  The license of hdith.com itself is unstated; the text stays on the site.
- Version: {{version}}. Groups whose occurrences are not all cached carry `complete = false`; a
  later rebuild after the full crawl will update them.

## Configs

| config | rows | content |
|---|---|---|
| `narrators` | {{rows_narrators}} | one row per narrator: recorded dates and inferred intervals |
| `chains` | {{rows_chains}} | one row per narrator position per chain |
| `groups` | {{rows_groups}} | one row per takhrij group |
| `occurrences` | {{rows_occurrences}} | group to hadith membership |
| `tree_nodes` | {{rows_tree_nodes}} | one row per narrator per group component |
| `report_dates` | {{rows_report_dates}} | one row per (group, root Companion) |
| `edits` | {{rows_edits}} | one row per wording change (substitution segment) |
| `edge_scores` | {{rows_edge_scores}} | v1 per-edge chronology scores (Six Books) |
| `checks` | {{rows_checks}} | one row: the automatic checks below |

Optional configs, present when their stage output exists: `segments` (alignment segments as
hashes), `shawahid` (corroborating reports by other Companions, ids only), `shawahid_companions`,
`edit_rates` (per-generation edit rates), `dropped_links` (links removed by the dating step).

### Columns

- `narrators`: `rawi_id`; `generation_num` (the site's tabaqa number); `death_year`, `death_kind`,
  `birth_year`, `birth_kind` (recorded dates and their kind: exact, alt, approx, after, before,
  era, none); `death_lo`, `death_hi`, `birth_lo`, `birth_hi` (inferred interval, Hijri); `support`
  (number of distinct surviving teacher-student links touching the narrator); `method` (`known`, `inferred`, `prior_only`).
- `chains`: `hadith_id`, `chain_no` (one chain per path to the compiler after splitting at ح),
  `position` (0 = earliest narrator, the compiler is last), `rawi_id`, `term` (the transmission
  formula by which the next narrator received from this one, e.g. حدثنا, عن), `unjoined` (an earlier tahwil segment that could
  not be joined to the final chain), `source` (`html`, `flat`, `html+flat`).
- `groups`: `group_id`, `n_entries`, `n_chains` (the site's counts), `books`, `n_occurrences`,
  `complete` (every occurrence page was cached when the release was built).
- `occurrences`: `group_id`, `hadith_id`, `book_slug`, `numbering` (the hadith number in its book).
- `tree_nodes`: `group_id`, `root_id` (the Companion of the component), `rawi_id`, `depth` (BFS
  distance from the root), `k_branches` (children whose subtree reaches a compiler),
  `n_descendant_chains`, `is_cl_k2`, `is_cl_k3` (common link), `is_pcl_k2`, `is_pcl_k3` (partial
  common link).
- `report_dates`: `group_id`, `root_id`, for k in {2, 3}: `cl_k{k}_id`, `cl_k{k}_date_lo`,
  `cl_k{k}_date_hi` (death interval of the common link = the report date), `cl_k{k}_all_chains`
  (every chain passes through it); `n_chains`, `n_compilers`, `complete`.
- `edits`: `group_id`, `seg_no`, `introduced_by_rawi_id`, `generation_depth`, `edit_type` (`sub`,
  `ins`, `del`), `status` (`attributed`, `ambiguous`, `partial`, `cross_root`, `no_chain`,
  `no_common_node`), `ambiguous`, `is_leaf_edit` (single-witness variant at the compiler),
  `has_tahwil_carrier`, `n_carriers`, `n_carriers_with_chain`, `n_base_carriers`.
- `edge_scores`: as in v1 (`teacher_id`, `student_id`, `hadith_id`, `position`, `term`, `p_meet`,
  evidence flags, `verdict`).
- `checks`: flattened keys, prefixed `alignment_`, `sanity_`, `coverage_`, `dating_`.

## Method

1. Chains. Parsed from the annotated isnad HTML of each hadith page (narrator spans and formula
   spans in reading order). The chain is split at every ح (tahwil) and at و-formulas; each earlier
   segment is joined to the final chain at its last shared narrator, giving one chain per path to
   the compiler. Narrators joined by و without a formula are parallel and fork the chain.
2. Groups. Taken from the site's takhrij group of each page: occurrences, and the site's variant
   segments (base text plus substitutions with their carrier hadiths), kept as hashes.
3. Narrator dating. Variables birth and death per narrator; each link student <- teacher gives
   birth(student) + 8 <= death(teacher); lifespans are bounded to 20..100 years; recorded dates
   enter as tight intervals. Difference constraints are propagated over the narrator graph;
   negative cycles are attributed to their weakest link (fewest chains; an عن-class link before
   a حدثنا-class one), which is dropped (listed in `dropped_links`). Accuracy is measured by a {{dating_folds}}-fold hold-out of recorded death years.
4. Trees and common links. All chains of a group's occurrences are merged into one graph per root
   Companion. The common link under k is the shallowest node with at least k branches reaching a
   compiler whose subtree contains every compiler; other nodes with at least k branches are partial
   common links. The report date is the common link's inferred death interval.
5. Edit attribution. For each substitution, the narrator that lies on every chain of every carrier
   and is deepest in the tree introduced the change; `ambiguous` when that narrator also transmitted
   the base text. Rows with status `partial` (some carriers without a parsed chain), `cross_root`,
   `no_chain` or `no_common_node` are excluded from the edit rates, which count only `attributed`
   and `ambiguous` rows.

## Checks

Computed when the release is built and shipped in the `checks` config and `checks.json`.

- Alignment check: the site's variant segments were checked against each carrier's own text in
  {{alignment_n_groups}} sampled groups ({{alignment_n_groups_scored}} with carrier text available;
  {{alignment_n_pairs_scored}} scored (substitution, carrier) pairs, {{alignment_n_pairs_no_carrier_matn}}
  pairs without cached carrier text).
  - Surface: the substitution's wording occurs in the carrier's text in {{alignment_surface_found_rate}}
    of pairs, against {{alignment_control_surface_found_rate}} in texts of the same group that do not
    carry it (control).
  - Position: re-aligning the base reading against the carrier text with difflib on token lists, a
    local difference (at most the substitution length + {{alignment_slack}} tokens) lies within
    ±{{alignment_tolerance}} token of the site's span in {{alignment_agreement}} of pairs, against
    {{alignment_control_hit_rate}} at the same slots for texts without the variant
    ({{alignment_n_control_pairs}} control pairs). Carrier texts come from other books and editions
    and differ from the base reading in many places, so the positional agreement is indicative only.
- Narrator dating hold-out (median absolute error in years / 90% interval coverage / median
  width), n = {{dating_n_scored}}:
  - propagation: {{dating_method_median_abs_error}} / {{dating_method_coverage_90}} / {{dating_method_median_width}}
  - propagation, bounded intervals only: {{dating_method_bounded_median_abs_error}} / {{dating_method_bounded_coverage_90}}
  - baseline by chain depth: {{dating_depth_median_abs_error}} / {{dating_depth_coverage_90}}
  - baseline by generation mean: {{dating_generation_mean_median_abs_error}} / {{dating_generation_mean_coverage_90}}
- Dropped links (negative cycles): {{sanity_n_dropped_links}}.
- Tree sanity: compilers that are leaves {{sanity_compiler_leaf_rate}} ({{sanity_n_compilers_nonleaf}} of
  {{sanity_n_compilers}} compilers also narrate inside another chain of the same component); roots
  without a parent {{sanity_root_no_parent_rate}}.
- Coverage: {{sanity_n_chains}} chains ({{sanity_n_chains_unjoined}} unjoined); occurrences with a parsed
  chain {{coverage_occurrences_with_chain_rate}}; complete groups {{coverage_groups_complete_rate}};
  groups with a k=2 common link {{coverage_groups_cl_k2_rate}} (dated {{coverage_groups_cl_k2_dated_rate}});
  edit rows in the rates {{coverage_edits_rated_rate}}.

## Limitations

- The site's alignment is taken as given and only spot-checked (see Checks); the site places a
  substitution after the base segment it replaces the end of, so the exact replaced span is not
  known and long reports align partially.
- ح-splitting depends on the HTML markers; unjoined segments are flagged, not guessed.
- Narrators far from any recorded date get wide intervals; `method = prior_only` means no chain
  constraint reached them.
- A common link is a structural property of the parsed chains; it does not by itself establish who
  put a report into circulation.
- Groups with `complete = false` lack some occurrences; their trees, common links and edit
  attributions can change after the full crawl.
- Edit attribution uses every parsed chain of a carrier; tahwil carriers are flagged
  (`has_tahwil_carrier`) for sensitivity analysis. Edit rates are edits per transmission, not
  probabilities.
- Chronology and common-link results are not authenticity verdicts.

## Source and license

Derived from hdith.com. No source text is redistributed: segment texts appear only as 16-hex
SHA-256 prefixes of the normalised text. The derived numbers are released under CC-BY-4.0;
attribution to hdith.com as the data source is required. The license of hdith.com is unstated.

## Citation

```bibtex
@misc{isnadchrono2026,
  title  = {isnad-chrono: a corpus-wide isnad-cum-matn dataset},
  author = {Haroon, Hesham},
  year   = {2026},
  note   = {Version {{version}}. Derived from hdith.com},
  url    = {https://huggingface.co/datasets/HeshamHaroon/isnad-chrono}
}
```
