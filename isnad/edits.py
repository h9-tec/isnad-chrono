"""Wording-change attribution and per-generation edit rates.

Each substitution segment of a takhrij group is a wording change carried by some witnesses
(carrier hadith_ids); every other occurrence of the group reads the base text there (base
carriers). seg_no is unique per row, so substitutions are grouped by the base segment
immediately preceding them (consecutive substitutions are alternatives for the same base text;
substitutions before any base form their own slot): the base carriers of a substitution are the
group's occurrences minus the carriers of every substitution against that base segment.

Attribution ("every chain" reading): the candidates are the narrators that lie on EVERY parsed
chain of EVERY carrier hadith (ancestor-or-self of each chain's compiler); a carrier with several
chains (tahwil) therefore constrains the candidates by each of its chains (rows with such a
carrier are flagged ``has_tahwil_carrier`` for sensitivity analysis). The lowest candidate (max
BFS depth in its component; ties -> more chains through it, then smaller rawi_id) introduced
the change. ``status``:

* ``no_chain``: no carrier has a parsed chain (or the segment lists no carrier);
* ``cross_root``: the carriers' chains start at more than one root (different Companions); no
  attribution even when they share a compiler;
* ``no_common_node``: one root but no narrator on every carrier chain (cannot happen with a
  shared root, kept for safety);
* ``partial``: some carriers have no parsed chain (``n_carriers_with_chain < n_carriers``); the
  node is still computed for information but the row is excluded from the rates;
* ``ambiguous``: the node also lies on a base carrier's chain (it transmitted the base text too);
* ``attributed``: otherwise.

``ambiguous`` (nullable bool) is set only for attributed/ambiguous rows. ``is_leaf_edit``: the
node is the terminal (compiler) of one of the carrier chains, i.e. a single-witness variant.

Edit rates count only status attributed/ambiguous rows: per depth d, ``n_edits`` counts edits at
depth d, and ``n_transmissions`` counts (hadith, chain) links whose student is at depth d, summed
over the groups that have at least one attributed/ambiguous row (the denominator is restricted
to the same groups as the numerator; groups whose edits are all partial/no_chain/... add
nothing). ``rate`` is edits per transmission, not a probability: one transmission can carry
several edits, so it can exceed 1. ``n_edits_nonleaf``/``rate_nonleaf`` exclude leaf edits.
Depth 0 (the Companion) is never a student: n_transmissions 0, rates null.

A carrier missing from the group's occurrence list still joins the group's tree (and its
transmissions are counted), but it is never a base carrier (``carriers_outside_group`` stat).
Chains are cleaned with ``tree.clean_chains``, exactly as ``merge_tree`` does.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from isnad.tree import Tree, clean_chains, load_chains, merge_tree

STATUSES = ("attributed", "ambiguous", "partial", "cross_root", "no_chain", "no_common_node")
RATED = ("attributed", "ambiguous")


@dataclass(frozen=True)
class Attribution:
    rawi_id: int | None
    depth: int | None
    ambiguous: bool | None
    status: str = "attributed"
    is_leaf: bool = False
    n_with_chain: int = 0
    has_tahwil: bool = False


def _chains(chains_by_hadith, h) -> list[tuple[int, ...]]:
    return clean_chains(chains_by_hadith.get(h))[0]


def attribute(tree: Tree, carriers: set[int], base_carriers: set[int],
              chains_by_hadith: dict[int, list[list[int]]]) -> Attribution:
    per = {h: _chains(chains_by_hadith, h) for h in carriers}
    with_chain = [cs for cs in per.values() if cs]
    n_with, tahwil = len(with_chain), any(len(cs) >= 2 for cs in with_chain)
    carrier_chains = [c for cs in with_chain for c in cs]
    if not carrier_chains:
        return Attribution(None, None, None, "no_chain", False, 0, False)
    roots = {c[0] for c in carrier_chains}
    if len(roots) > 1:
        return Attribution(None, None, None, "cross_root", False, n_with, tahwil)
    cand = set(carrier_chains[0]).intersection(*carrier_chains[1:])
    if not cand:
        return Attribution(None, None, None, "no_common_node", False, n_with, tahwil)
    depth = tree.component(next(iter(roots))).depth
    node = min(cand, key=lambda n: (-depth.get(n, -1), -tree.n_chains_through(n), n))
    leaf = any(c[-1] == node for c in carrier_chains)
    if n_with < len(carriers):
        return Attribution(node, depth.get(node), None, "partial", leaf, n_with, tahwil)
    amb = any(node in c for h in base_carriers for c in _chains(chains_by_hadith, h))
    return Attribution(node, depth.get(node), amb, "ambiguous" if amb else "attributed", leaf,
                       n_with, tahwil)


def _edit_type(base_hash, variant_hash) -> str:
    if base_hash is None or pd.isna(base_hash):
        return "ins"
    if variant_hash is None or pd.isna(variant_hash):
        return "del"
    return "sub"


EDIT_COLS = ["group_id", "seg_no", "introduced_by_rawi_id", "generation_depth", "edit_type",
             "status", "ambiguous", "is_leaf_edit", "has_tahwil_carrier", "n_carriers",
             "n_carriers_with_chain", "n_base_carriers"]


def edits_table(segments: pd.DataFrame, occurrences: pd.DataFrame,
                chains_by_hadith: dict[int, list[list[int]]], stats: dict | None = None
                ) -> pd.DataFrame:
    """One row per substitution segment. ``stats`` (if given) receives the counters."""
    st: Counter = Counter()
    hids = occurrences.groupby("group_id").hadith_id.agg(lambda s: {int(h) for h in s})
    no_chain: set[int] = set()
    rows: list[dict] = []
    seg = segments.sort_values(["group_id", "seg_no"])
    for g, gs in seg.groupby("group_id", sort=False):
        occ = hids.get(g, set())
        slot, slots, subs = -1, {}, []
        for r in gs.itertuples(index=False):
            if r.kind == "base":
                slot = r.seg_no
                continue
            car = {int(h) for h in (r.carrier_hadith_ids if r.carrier_hadith_ids is not None
                                    else [])}
            slots.setdefault(slot, set()).update(car)
            subs.append((slot, r, car))
        witnesses = occ.union(*slots.values())
        st["carriers_outside_group"] += len(witnesses - occ)
        tree = merge_tree([c for h in sorted(witnesses) for c in chains_by_hadith.get(h, [])])
        cleaned = {h: list(_chains(chains_by_hadith, h)) for h in witnesses}
        for slot, r, car in subs:
            base = occ - slots[slot]
            st["segments_no_carriers"] += not car
            no_chain |= {h for h in car if not cleaned[h]}
            a = attribute(tree, car, base, cleaned)
            st["carrier_refs_without_chain"] += len(car) - a.n_with_chain
            rows.append({"group_id": g, "seg_no": int(r.seg_no), "introduced_by_rawi_id": a.rawi_id,
                         "generation_depth": a.depth,
                         "edit_type": _edit_type(r.base_hash, r.variant_hash),
                         "status": a.status, "ambiguous": a.ambiguous, "is_leaf_edit": a.is_leaf,
                         "has_tahwil_carrier": a.has_tahwil, "n_carriers": len(car),
                         "n_carriers_with_chain": a.n_with_chain, "n_base_carriers": len(base)})
    e = pd.DataFrame(rows, columns=EDIT_COLS)
    for c in ("seg_no", "n_carriers", "n_carriers_with_chain", "n_base_carriers"):
        e[c] = e[c].astype("int64")
    for c in ("introduced_by_rawi_id", "generation_depth"):
        e[c] = pd.array(list(e[c]), dtype="Int64")
    e["ambiguous"] = pd.array(list(e.ambiguous), dtype="boolean")
    e["is_leaf_edit"] = e.is_leaf_edit.astype(bool)
    e["has_tahwil_carrier"] = e.has_tahwil_carrier.astype(bool)
    e["status"] = e.status.astype(str)
    if stats is not None:
        counts = e.status.value_counts()
        stats.update({"segments": len(e), **{s: int(counts.get(s, 0)) for s in STATUSES},
                      "carriers_without_chain": len(no_chain), **st})
    return e


def edit_rates(edits: pd.DataFrame, chains: dict[str, list[list[int]]]) -> pd.DataFrame:
    """``chains``: group_id -> every parsed chain of the group's witnesses. Only rows with
    status attributed/ambiguous count as edits, and only groups with at least one such row
    count transmissions."""
    rated_groups = set(edits.loc[edits.status.isin(RATED), "group_id"])
    trans: Counter = Counter()
    for g, raw in chains.items():
        if g not in rated_groups:
            continue
        tree = merge_tree(raw)
        for c in tree.chains:
            d = tree.component(c[0]).depth
            trans.update(d[n] for n in c[1:])
    att = edits[edits.status.isin(RATED) & edits.generation_depth.notna()]
    n_edits = Counter(int(x) for x in att.generation_depth)
    n_nonleaf = Counter(int(x) for x in att.generation_depth[~att.is_leaf_edit.astype(bool)])
    depths = sorted(set(trans) | set(n_edits) | {0})  # depth 0 always present (rates null)
    r = pd.DataFrame({"depth": depths, "n_transmissions": [trans[d] for d in depths],
                      "n_edits": [n_edits[d] for d in depths],
                      "n_edits_nonleaf": [n_nonleaf[d] for d in depths]}, dtype="int64")

    def _rate(n):
        return pd.array([x / t if t else None for x, t in zip(n, r.n_transmissions)],
                        dtype="Float64")
    r["rate"] = _rate(r.n_edits)
    r["rate_nonleaf"] = _rate(r.n_edits_nonleaf)
    return r[["depth", "n_transmissions", "n_edits", "rate", "n_edits_nonleaf", "rate_nonleaf"]]


def group_witnesses(segments: pd.DataFrame, occurrences: pd.DataFrame) -> dict[str, set[int]]:
    """group_id -> occurrence hadith_ids plus any substitution carrier not listed among them."""
    out: dict[str, set[int]] = {}
    for g, h in zip(occurrences.group_id, occurrences.hadith_id):
        out.setdefault(g, set()).add(int(h))
    sub = segments[segments.kind == "substitution"]
    for g, car in zip(sub.group_id, sub.carrier_hadith_ids):
        out.setdefault(g, set()).update(int(h) for h in (car if car is not None else []))
    keep = set(segments.group_id)
    return {g: hs for g, hs in out.items() if g in keep}


def run_edits(segments_path, chains_path, occurrences_path, out_path, rates_path) -> dict:
    seg = pd.read_parquet(segments_path)
    occ = pd.read_parquet(occurrences_path, columns=["group_id", "hadith_id"])
    chains = load_chains(chains_path)
    stats: dict = {}
    e = edits_table(seg, occ, chains, stats=stats)
    r = edit_rates(e, {g: [c for h in sorted(hs) for c in chains.get(h, [])]
                       for g, hs in group_witnesses(seg, occ).items()})
    for p in (out_path, rates_path):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    e.to_parquet(out_path, index=False)
    r.to_parquet(rates_path, index=False)
    print(" ".join(f"{k} {v}" for k, v in stats.items()))
    return stats
