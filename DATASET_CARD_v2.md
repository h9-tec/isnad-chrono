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
- Version: {{version}}. `complete` on a group means every occurrence page was cached when the
  `groups` stage ran; `all_occurrences_have_chain` means every occurrence also has a parsed
  chain. A later rebuild after the full crawl will update both.

## Changelog

- v0.1 → v0.1.1: dating cleans repeated-narrator chains (as the trees do), edit-rate denominator
  restricted to the groups that have rated edits, `complete`-flag wording plus the new
  `all_occurrences_have_chain` flag, common-link date method (`cl_k{k}_date_method`).

## Release {{version}}: partial crawl

This release was built from a partial crawl of hdith.com: {{n_hadith_pages_cached}} hadith pages
were cached when the release was built (the chain and group stages ran on a slightly earlier
snapshot of the same crawl while it was still growing). {{prose_six_books}} The other collections
are partial or not yet crawled. As a result:

- complete groups (every occurrence page cached when the `groups` stage ran):
  {{groups_complete_rate}} of {{coverage_n_groups}} groups;
- groups whose every occurrence has a parsed chain (`all_occurrences_have_chain`):
  {{all_occurrences_have_chain_rate}};
- occurrences with a parsed chain: {{occurrence_chain_rate}};
- edit rows with status `no_chain` (no carrier has a parsed chain, mostly carriers in collections
  not yet crawled): {{edits_no_chain_rate}}.

Trees, common links and edit attributions of incomplete groups can change. v0.2 will be rebuilt
from the full crawl.

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
  `complete` (every occurrence page was cached when the `groups` stage ran),
  `all_occurrences_have_chain` (every occurrence hadith has a parsed, joined chain in `chains`;
  computed by the tree stage).
- `occurrences`: `group_id`, `hadith_id`, `book_slug`, `numbering` (the hadith number in its book).
- `tree_nodes`: `group_id`, `root_id` (the Companion of the component), `rawi_id`, `depth` (BFS
  distance from the root), `k_branches` (children whose subtree reaches a compiler),
  `n_descendant_chains`, `is_cl_k2`, `is_cl_k3` (common link), `is_pcl_k2`, `is_pcl_k3` (partial
  common link).
- `report_dates`: `group_id`, `root_id`, for k in {2, 3}: `cl_k{k}_id`, `cl_k{k}_date_lo`,
  `cl_k{k}_date_hi` (death interval of the common link = the report date), `cl_k{k}_date_method`
  (the common link's dating `method`: `known`, `inferred`, or `prior_only` = no chain constraint
  reached it, so the date is the prior alone), `cl_k{k}_all_chains` (every chain passes through
  it); `n_chains`, `n_compilers`, `complete`, `all_occurrences_have_chain` (copied from the group).
- `edits`: `group_id`, `seg_no`, `introduced_by_rawi_id`, `generation_depth`, `edit_type` (`sub`,
  `ins`, `del`), `status` (`attributed`, `ambiguous`, `partial`, `cross_root`, `no_chain`,
  `no_common_node`), `ambiguous`, `is_leaf_edit` (single-witness variant at the compiler),
  `has_tahwil_carrier`, `n_carriers`, `n_carriers_with_chain`, `n_base_carriers`.
- `edit_rates`: `depth`, `n_transmissions`, `n_edits`, `rate`, `n_edits_nonleaf`, `rate_nonleaf`,
  from `attributed` and `ambiguous` rows only. The denominator is restricted the same way as the
  numerator: `n_transmissions` counts the chain links of only those groups that have at least one
  `attributed` or `ambiguous` row. Depth 0 is the Companion: edits attributed there
  have no transmission into the node, so `n_transmissions` is 0 and the rates are null.
- `shawahid`: `group_id`, `hadith_ids` (the corroborating reports). {{shawahid_note}} For the
  Companion of each corroborating report use `shawahid_companions` (`group_id`, `hadith_id`,
  `companion_rawi_id`), resolved from the parsed chains: {{coverage_shawahid_companions_resolved_rate}}
  of its rows have a Companion.
- `edge_scores`: as in v1 (`teacher_id`, `student_id`, `hadith_id`, `position`, `term`, `p_meet`,
  evidence flags, `verdict`).
- `checks`: flattened keys, prefixed `alignment_`, `sanity_`, `coverage_`, `dating_`, plus the
  unprefixed release-status keys `n_hadith_pages_cached`, `six_books_cached_rate`,
  `groups_complete_rate`, `all_occurrences_have_chain_rate`, `occurrence_chain_rate`,
  `edits_no_chain_rate`, `cl_k2_rate_multi`, `cl_k3_rate_multi`, `cl_k2_bounded_rate`,
  `cl_k2_prior_only_rate`.

## Method

1. Chains. Parsed from the annotated isnad HTML of each hadith page (narrator spans and formula
   spans in reading order). The chain is split at every ح (tahwil), at و-formulas (وحدثنا,
   وأخبرنا, ...) and at "وقال NAME:" restarts that name an earlier narrator (the new segment
   replays the path down to that narrator); each earlier segment is joined to the final chain at
   its last shared narrator, giving one chain per path to the compiler. A join phrase (كلاهما,
   كلهم, جميعا, ثلاثتهم) before "عن X" makes every open segment continue through X. Two adjacent
   narrator spans are parallel (and fork the chain) only when joined by و; adjacent spans with no
   و are linked in sequence, with the connective in the gap (أن, عن, ...) as the term. Chains
   that stop short of the flat isnad's earliest narrators are completed from it.
2. Groups. Taken from the site's takhrij group of each page: occurrences, and the site's variant
   segments (base text plus substitutions with their carrier hadiths), kept as hashes.
3. Narrator dating. Variables birth and death per narrator; each link student <- teacher gives
   birth(student) + 8 <= death(teacher); lifespans are bounded to 20..100 years; recorded dates
   enter as tight intervals. Chains are cleaned as for the trees (a chain is cut before its first
   repeated narrator) before the links are read. Difference constraints are propagated over the
   narrator graph. When a narrator's interval empties in a round, one link is dropped for it
   (listed in `dropped_links`): among the links that bound it that round, a link whose removal
   alone restores feasibility is preferred, then an ambiguous-class link (عن, أن, ...) before an
   explicit one (حدثنا, ...), then the lowest weight (fewest chains). Accuracy is measured by a
   {{dating_folds}}-fold hold-out of recorded death years.
4. Trees and common links. All chains of a group's occurrences are merged into one graph per root
   Companion. The common link under k is the shallowest node with at least k branches reaching a
   compiler whose subtree contains every compiler; other nodes with at least k branches are partial
   common links. The report date is the common link's inferred death interval.
5. Edit attribution. For each substitution, the narrator that lies on every chain of every carrier
   and is deepest in the tree introduced the change; `ambiguous` when that narrator also transmitted
   the base text. Rows with status `partial` (some carriers without a parsed chain), `cross_root`,
   `no_chain` or `no_common_node` are excluded from the edit rates, which count only `attributed`
   and `ambiguous` rows. An edit's tree is built from all the group's witnesses, including
   substitution carriers that are missing from the group's occurrence list (such a carrier is
   never counted as a base carrier).

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
- Narrator dating hold-out (median absolute error in years / mean absolute error / 90% interval
  coverage / median width), n = {{dating_n_scored}}:
  - propagation: {{dating_method_median_abs_error}} / {{dating_method_mean_abs_error}} / {{dating_method_coverage_90}} / {{dating_method_median_width}}
  - propagation, bounded intervals only (width ≤ {{bounded_width}} years, n = {{dating_method_bounded_n}}): {{dating_method_bounded_median_abs_error}} / {{dating_method_bounded_mean_abs_error}} / {{dating_method_bounded_coverage_90}}
  - baseline by chain depth: {{dating_depth_median_abs_error}} / {{dating_depth_mean_abs_error}} / {{dating_depth_coverage_90}}
  - baseline by generation mean: {{dating_generation_mean_median_abs_error}} / {{dating_generation_mean_mean_abs_error}} / {{dating_generation_mean_coverage_90}}

  {{prose_dating}}
- Dropped links (negative cycles): {{sanity_n_dropped_links}}.
- Tree sanity: compilers that are leaves {{sanity_compiler_leaf_rate}} ({{sanity_n_compilers_nonleaf}} of
  {{sanity_n_compilers}} compilers also narrate inside another chain of the same component); roots
  without a parent in the group graph {{sanity_root_no_parent_rate}}; root death interval starting no
  later than every dated compiler's ends (spec "root earliest") {{sanity_root_earliest_rate}} of
  {{sanity_n_root_date_checked}} dated components.
- Coverage: {{sanity_n_chains}} chains ({{sanity_n_chains_unjoined}} unjoined); occurrences with a parsed
  chain {{occurrence_chain_rate}}; complete groups {{groups_complete_rate}}; edit rows in the rates
  (status `attributed` or `ambiguous`) {{coverage_edits_rated_rate}}.
- Common links: among the {{coverage_n_groups_multi_chain}} groups with at least 2 parsed chains,
  {{cl_k2_rate_multi}} have a k=2 common link and {{cl_k3_rate_multi}} a k=3 one; among all
  {{coverage_n_groups}} groups (including those with 0 or 1 chain) the rates are
  {{coverage_groups_cl_k2_rate}} and {{coverage_groups_cl_k3_rate}}. {{prose_cl_dates}};
  {{cl_k2_bounded_rate}} of the {{coverage_n_cl_k2}} k=2 common links have a bounded one (width
  ≤ {{bounded_width}} years). {{coverage_cl_k2_prior_only}} k=2 common links
  ({{cl_k2_prior_only_rate}}) are dated by the prior alone (`cl_k2_date_method = prior_only`: no
  chain constraint reached the narrator); {{prose_cl_k3_prior_only}}. Filter on `cl_k{k}_date_method` before using report dates.

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
- The spec's `earliest_text_hash` of `report_dates` is deferred to v0.2 (not computed in v0.1 or
  v0.1.1).
- Text hashes hide the text but are not a secrecy mechanism: a short segment (one or two words)
  can be confirmed by hashing candidate wordings.

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
