import pandas as pd

from isnad.cli import main
from isnad.edits import attribute, edit_rates, edits_table
from isnad.tree import merge_tree

# synthetic group: three chains under one companion (1)
#   h1: 1 -> 2 -> 3 -> 10      depths 1:0 2:1 3:2 10:3
#   h2: 1 -> 2 -> 4 -> 11
#   h3: 1 -> 5 -> 12
CHAINS = {1: [[1, 2, 3, 10]], 2: [[1, 2, 4, 11]], 3: [[1, 5, 12]]}


def _tree(chains=CHAINS):
    return merge_tree([c for cs in chains.values() for c in cs])


def _a(a):
    return (a.rawi_id, a.depth, a.ambiguous, a.status)


def test_attribution_lowest_common_ancestor():
    t = _tree()
    assert _a(attribute(t, {1, 2}, {3}, CHAINS)) == (2, 1, False, "attributed")
    a = attribute(t, {1}, {2, 3}, CHAINS)  # a single witness: its own compiler
    assert _a(a) == (10, 3, False, "attributed") and a.is_leaf and a.n_with_chain == 1


def test_attribution_partial_coverage():
    # only h1 has a chain: node still computed (its compiler) but the row is partial
    a = attribute(_tree(), {1, 98, 99}, {2, 3}, CHAINS)
    assert _a(a) == (10, 3, None, "partial") and a.n_with_chain == 1


def test_attribution_ambiguous_when_lca_covers_base():
    t = _tree()
    a = attribute(t, {1, 3}, {2}, CHAINS)  # only the companion is shared, and h2 runs through him
    assert _a(a) == (1, 0, True, "ambiguous") and not a.is_leaf
    # no carrier has a chain
    assert _a(attribute(t, {98, 99}, {1, 2, 3}, CHAINS)) == (None, None, None, "no_chain")
    assert _a(attribute(t, set(), {1, 2, 3}, CHAINS)) == (None, None, None, "no_chain")


def test_attribution_cross_root():
    # different companions -> no attribution, even when they share the compiler (10)
    chains = {1: [[1, 2, 3, 10]], 4: [[7, 8, 10]]}
    a = attribute(_tree(chains), {1, 4}, set(), chains)
    assert _a(a) == (None, None, None, "cross_root") and a.n_with_chain == 2
    chains = {**CHAINS, 4: [[7, 8, 14]]}
    assert attribute(_tree(chains), {1, 4}, {2, 3}, chains).status == "cross_root"


def test_attribution_needs_every_chain_of_a_carrier():
    # h1 has two chains (tahwil); only 1, 3 and 10 lie on both, 2 does not
    chains = {1: [[1, 2, 3, 10], [1, 6, 3, 10]], 2: [[1, 2, 4, 11]], 3: [[1, 2, 3, 12]]}
    a = attribute(_tree(chains), {1}, {2}, chains)
    assert _a(a) == (10, 3, False, "attributed") and a.has_tahwil and a.is_leaf
    a = attribute(_tree(chains), {1, 3}, {2}, chains)  # 3 is shared, 2 is not on h1's 2nd chain
    assert _a(a) == (3, 2, False, "attributed") and a.has_tahwil and not a.is_leaf
    assert not attribute(_tree(chains), {2, 3}, {1}, chains).has_tahwil


def test_leaf_is_terminal_of_carrier_chains_not_of_tree():
    # 10 compiles h1 but narrates mid-chain for h2's compiler 11: for carrier h2 it is not a leaf
    chains = {1: [[1, 2, 10]], 2: [[1, 2, 10, 11]], 3: [[1, 5, 12]]}
    a = attribute(_tree(chains), {1, 2}, {3}, chains)
    assert (a.rawi_id, a.is_leaf) == (10, True)
    chains = {1: [[1, 2, 10]], 2: [[1, 2, 10, 11]], 3: [[1, 2, 10, 13]]}
    a = attribute(_tree(chains), {2, 3}, {1}, chains)
    assert (a.rawi_id, a.status, a.is_leaf) == (10, "ambiguous", False)


def _segments():
    return pd.DataFrame({
        "group_id": ["g"] * 6,
        "seg_no": [0, 1, 2, 3, 4, 5],
        "kind": ["substitution", "base", "substitution", "substitution", "base", "substitution"],
        "base_hash": [None, "b1", "b1", "b1", "b4", "b4"],
        "variant_hash": ["v0", None, "v2", "v3", None, None],
        "carrier_hadith_ids": [[1, 2], [], [1], [3], [], [1, 3]],
    })


def _occ():
    return pd.DataFrame({"group_id": ["g"] * 4, "hadith_id": [1, 2, 3, 77],
                         "book_slug": ["b-1"] * 4, "numbering": ["1", "2", "3", "4"]})


def test_edit_type_classification():
    e = edits_table(_segments(), _occ(), CHAINS)
    assert list(e.columns) == ["group_id", "seg_no", "introduced_by_rawi_id", "generation_depth",
                               "edit_type", "status", "ambiguous", "is_leaf_edit",
                               "has_tahwil_carrier", "n_carriers", "n_carriers_with_chain",
                               "n_base_carriers"]
    assert list(e.seg_no) == [0, 2, 3, 5]  # base segments are not edits
    assert list(e.edit_type) == ["ins", "sub", "sub", "del"]
    # seg 2 and 3 substitute the same base text: base carriers exclude both substitutions' carriers
    assert list(e.n_base_carriers) == [2, 2, 2, 2]
    assert list(e.n_carriers) == [2, 1, 1, 2]
    assert list(e.introduced_by_rawi_id) == [2, 10, 12, 1]
    assert list(e.generation_depth) == [1, 3, 2, 0]
    assert list(e.ambiguous) == [False, False, False, True]
    assert list(e.status) == ["attributed", "attributed", "attributed", "ambiguous"]
    assert list(e.is_leaf_edit) == [False, True, True, False]


def test_rates_by_depth():
    stats: dict = {}
    e = edits_table(_segments(), _occ(), CHAINS, stats=stats)
    assert stats["carriers_without_chain"] == 0
    # group "other" has no attributed/ambiguous row: its chains must not enter the denominator
    r = edit_rates(e, {"g": [c for h in (1, 2, 3, 77) for c in CHAINS.get(h, [])],
                       "other": [[1, 2, 3, 10], [1, 5, 6, 7, 8]]})
    assert list(r.columns) == ["depth", "n_transmissions", "n_edits", "rate", "n_edits_nonleaf",
                               "rate_nonleaf"]
    assert list(r.depth) == [0, 1, 2, 3]
    # student depths of links: h1 2,3,10 -> 1,2,3; h2 2,4,11 -> 1,2,3; h3 5,12 -> 1,2
    assert list(r.n_transmissions) == [0, 3, 3, 2]
    assert list(r.n_edits) == [1, 1, 1, 1]
    assert r.rate[0] is pd.NA and r.rate_nonleaf[0] is pd.NA
    assert list(r.rate[1:]) == [1 / 3, 1 / 3, 1 / 2]
    # seg 2 (-> 10) and seg 3 (-> 12) are single-witness compiler edits
    assert list(r.n_edits_nonleaf) == [1, 1, 0, 0]
    assert list(r.rate_nonleaf[1:]) == [1 / 3, 0, 0]
    # rate is edits per transmission and can exceed 1
    many = pd.concat([e[e.seg_no == 2]] * 3, ignore_index=True)
    r2 = edit_rates(many, {"g": [c for cs in CHAINS.values() for c in cs]})
    assert r2.set_index("depth").rate[3] == 3 / 2


def test_partial_and_unattributed_rows_excluded_from_rates():
    seg = pd.DataFrame({"group_id": ["g"] * 4, "seg_no": [0, 1, 2, 3],
                        "kind": ["base", "substitution", "substitution", "substitution"],
                        "base_hash": ["b"] * 4, "variant_hash": [None, "v1", "v2", "v3"],
                        "carrier_hadith_ids": [[], [1, 98, 99], [98], []]})
    stats: dict = {}
    e = edits_table(seg, _occ(), CHAINS, stats=stats)
    assert list(e.status) == ["partial", "no_chain", "no_chain"]
    assert list(e.n_carriers_with_chain) == [1, 0, 0] and list(e.n_carriers) == [3, 1, 0]
    assert e.introduced_by_rawi_id[0] == 10 and e.ambiguous.isna().all()
    assert (stats["partial"], stats["no_chain"], stats["segments_no_carriers"]) == (1, 2, 1)
    assert stats["carriers_without_chain"] == 2 and stats["carrier_refs_without_chain"] == 3
    r = edit_rates(e, {"g": [c for cs in CHAINS.values() for c in cs]})
    assert r.n_edits.sum() == 0 and r.n_edits_nonleaf.sum() == 0
    # no rated row in the group: its transmissions are not counted either
    assert r.n_transmissions.sum() == 0 and list(r.depth) == [0]
    assert r.depth[0] == 0 and r.n_transmissions[0] == 0 and r.rate[0] is pd.NA


def test_cli_edits(tmp_path):
    seg = tmp_path / "segments.parquet"
    occ = tmp_path / "occ.parquet"
    ch = tmp_path / "chains.parquet"
    _segments().to_parquet(seg, index=False)
    _occ().to_parquet(occ, index=False)
    rows = [(h, i, p, r) for h, cs in CHAINS.items() for i, c in enumerate(cs)
            for p, r in enumerate(c)]
    pd.DataFrame({"hadith_id": [r[0] for r in rows], "chain_no": [r[1] for r in rows],
                  "position": [r[2] for r in rows], "rawi_id": [r[3] for r in rows],
                  "term": ["عن"] * len(rows), "unjoined": [False] * len(rows),
                  "source": ["html"] * len(rows)}).to_parquet(ch, index=False)
    out, rates = tmp_path / "edits.parquet", tmp_path / "rates.parquet"
    main(["edits", "--segments", str(seg), "--chains", str(ch), "--occurrences", str(occ),
          "--out", str(out), "--rates", str(rates)])
    e = pd.read_parquet(out)
    assert len(e) == 4 and e.introduced_by_rawi_id.dtype == "Int64"
    assert list(pd.read_parquet(rates).n_edits) == [1, 1, 1, 1]


def test_carrier_outside_occurrences_joins_tree():
    chains = {**CHAINS, 5: [[1, 2, 6, 13]]}
    seg = pd.DataFrame({"group_id": ["g", "g"], "seg_no": [0, 1],
                        "kind": ["base", "substitution"], "base_hash": ["b", "b"],
                        "variant_hash": [None, "v"], "carrier_hadith_ids": [[], [5]]})
    stats: dict = {}
    e = edits_table(seg, _occ(), chains, stats=stats)
    assert (e.introduced_by_rawi_id[0], e.generation_depth[0], e.n_base_carriers[0]) == (13, 3, 4)
    assert stats["carriers_outside_group"] == 1
