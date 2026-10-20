import math

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


def test_attribution_lowest_common_ancestor():
    t = _tree()
    a = attribute(t, {1, 2}, {3}, CHAINS)
    assert (a.rawi_id, a.depth, a.ambiguous) == (2, 1, False)
    a = attribute(t, {1}, {2, 3}, CHAINS)  # a single witness: its own compiler
    assert (a.rawi_id, a.depth, a.ambiguous) == (10, 3, False)
    # a carrier without a parsed chain is ignored
    a = attribute(t, {1, 2, 99}, {3}, CHAINS)
    assert (a.rawi_id, a.depth, a.ambiguous) == (2, 1, False)


def test_attribution_ambiguous_when_lca_covers_base():
    t = _tree()
    a = attribute(t, {1, 3}, {2}, CHAINS)  # only the companion is shared, and h2 runs through him
    assert (a.rawi_id, a.depth, a.ambiguous) == (1, 0, True)
    # carriers under different companions share no node: unattributed
    chains = {**CHAINS, 4: [[7, 8, 14]]}
    a = attribute(_tree(chains), {1, 4}, {2, 3}, chains)
    assert (a.rawi_id, a.depth, a.ambiguous) == (None, None, True)
    # no carrier has a chain: unattributed
    a = attribute(t, {98, 99}, {1, 2, 3}, CHAINS)
    assert (a.rawi_id, a.depth, a.ambiguous) == (None, None, True)


def test_attribution_needs_every_chain_of_a_carrier():
    # h1 has two chains (tahwil); only 1, 3 and 10 lie on both, 2 does not
    chains = {1: [[1, 2, 3, 10], [1, 6, 3, 10]], 2: [[1, 2, 4, 11]], 3: [[1, 2, 3, 12]]}
    a = attribute(_tree(chains), {1}, {2}, chains)
    assert (a.rawi_id, a.depth, a.ambiguous) == (10, 3, False)
    a = attribute(_tree(chains), {1, 3}, {2}, chains)  # 3 is shared, 2 is not on h1's 2nd chain
    assert (a.rawi_id, a.depth, a.ambiguous) == (3, 2, False)


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
                               "edit_type", "ambiguous", "n_carriers", "n_base_carriers"]
    assert list(e.seg_no) == [0, 2, 3, 5]  # base segments are not edits
    assert list(e.edit_type) == ["ins", "sub", "sub", "del"]
    # seg 2 and 3 substitute the same base text: base carriers exclude both substitutions' carriers
    assert list(e.n_base_carriers) == [2, 2, 2, 2]
    assert list(e.n_carriers) == [2, 1, 1, 2]
    assert list(e.introduced_by_rawi_id) == [2, 10, 12, 1]
    assert list(e.generation_depth) == [1, 3, 2, 0]
    assert list(e.ambiguous) == [False, False, False, True]


def test_rates_by_depth():
    stats: dict = {}
    e = edits_table(_segments(), _occ(), CHAINS, stats=stats)
    assert stats["carriers_without_chain"] == 0
    r = edit_rates(e, {"g": [c for h in (1, 2, 3, 77) for c in CHAINS.get(h, [])]})
    assert list(r.columns) == ["depth", "n_transmissions", "n_edits", "rate"]
    assert list(r.depth) == [0, 1, 2, 3]
    # student depths of links: h1 2,3,10 -> 1,2,3; h2 2,4,11 -> 1,2,3; h3 5,12 -> 1,2
    assert list(r.n_transmissions) == [0, 3, 3, 2]
    assert list(r.n_edits) == [1, 1, 1, 1]
    assert math.isnan(r.rate[0])
    assert list(r.rate[1:]) == [1 / 3, 1 / 3, 1 / 2]


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
    assert stats["carrier_refs_outside_occurrences"] == 1
