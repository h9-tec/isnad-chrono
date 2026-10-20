"""Wording-change attribution and per-generation edit rates.

Each substitution segment of a takhrij group is a wording change carried by some witnesses
(carrier hadith_ids); every other occurrence of the group reads the base text there (base
carriers). Consecutive substitutions after one base segment are alternatives for the same base
text, so the base carriers of a substitution are the group's occurrences minus the carriers of
every substitution in that slot.

Attribution: the candidates are the narrators that lie on every parsed chain of every carrier
(ancestor-or-self of each chain's compiler). The lowest one (max BFS depth in its component;
ties -> more chains through it, then smaller rawi_id) introduced the change. It is ``ambiguous``
when it also lies on a base carrier's chain (it transmitted the base text too), or when no
candidate exists (carriers under different Companions, or no carrier has a chain).

Edit rates: per depth d, ``n_transmissions`` counts (hadith, chain) links whose student is at
depth d, summed over groups; ``n_edits`` counts attributed edits at depth d. Depth 0 (the
Companion) is never a student, so its rate is NaN.

A carrier missing from the group's occurrence list still joins the group's tree (and its
transmissions are counted), but it is never a base carrier. Chains are cleaned exactly as ``merge_tree`` does (repeats collapsed / truncated).
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from isnad.tree import Tree, _clean, load_chains, merge_tree


@dataclass(frozen=True)
class Attribution:
    rawi_id: int | None
    depth: int | None
    ambiguous: bool


def _cleaned(raw) -> list[tuple[int, ...]]:
    out = []
    for ch in raw or []:
        c, truncated = _clean(ch)
        if c and not (truncated and len(c) < 2):
            out.append(c)
    return out


def _node_depth(tree: Tree, node: int, roots: set[int]) -> int:
    ds = [tree.component(r).depth[node] for r in roots if node in tree.component(r).depth]
    return min(ds) if ds else tree.depth.get(node, -1)


def attribute(tree: Tree, carriers: set[int], base_carriers: set[int],
              chains_by_hadith: dict[int, list[list[int]]]) -> Attribution:
    carrier_chains = [c for h in carriers for c in _cleaned(chains_by_hadith.get(h))]
    if not carrier_chains:
        return Attribution(None, None, True)
    cand = set(carrier_chains[0]).intersection(*carrier_chains[1:])
    if not cand:
        return Attribution(None, None, True)
    roots = {c[0] for c in carrier_chains}
    depth = {n: _node_depth(tree, n, roots) for n in cand}
    node = min(cand, key=lambda n: (-depth[n], -tree.n_chains_through(n), n))
    ambiguous = any(node in c for h in base_carriers for c in _cleaned(chains_by_hadith.get(h)))
    return Attribution(node, depth[node], ambiguous)


def _edit_type(base_hash, variant_hash) -> str:
    if base_hash is None or pd.isna(base_hash):
        return "ins"
    if variant_hash is None or pd.isna(variant_hash):
        return "del"
    return "sub"


EDIT_COLS = ["group_id", "seg_no", "introduced_by_rawi_id", "generation_depth", "edit_type",
             "ambiguous", "n_carriers", "n_base_carriers"]


def edits_table(segments: pd.DataFrame, occurrences: pd.DataFrame,
                chains_by_hadith: dict[int, list[list[int]]], stats: dict | None = None
                ) -> pd.DataFrame:
    """One row per substitution segment. ``stats`` (if given) receives the counters."""
    st = Counter()
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
        st["carrier_refs_outside_occurrences"] += sum(len(car - occ) for _, _, car in subs)
        tree = merge_tree([c for h in sorted(witnesses) for c in chains_by_hadith.get(h, [])])
        cleaned: dict[int, list] = {}
        for slot, r, car in subs:
            base = occ - slots[slot]
            missing = {h for h in car if not chains_by_hadith.get(h)}
            no_chain |= missing
            st["carrier_refs_without_chain"] += len(missing)
            st["segments_no_carrier_chain"] += len(missing) == len(car)
            for h in car | base:
                if h not in cleaned:
                    cleaned[h] = _cleaned(chains_by_hadith.get(h))
            a = attribute(tree, car, base, cleaned)
            rows.append({"group_id": g, "seg_no": int(r.seg_no), "introduced_by_rawi_id": a.rawi_id,
                         "generation_depth": a.depth,
                         "edit_type": _edit_type(r.base_hash, r.variant_hash),
                         "ambiguous": a.ambiguous, "n_carriers": len(car),
                         "n_base_carriers": len(base)})
    e = pd.DataFrame(rows, columns=EDIT_COLS)
    e["seg_no"] = e.seg_no.astype("int64")
    e["introduced_by_rawi_id"] = pd.array(list(e.introduced_by_rawi_id), dtype="Int64")
    e["generation_depth"] = pd.array(list(e.generation_depth), dtype="Int64")
    e["ambiguous"] = e.ambiguous.astype(bool)
    e["n_carriers"] = e.n_carriers.astype("int64")
    e["n_base_carriers"] = e.n_base_carriers.astype("int64")
    if stats is not None:
        attributed = e.introduced_by_rawi_id.notna()
        stats.update({"segments": len(e), "attributed": int(attributed.sum()),
                      "ambiguous": int((attributed & e.ambiguous).sum()),
                      "unattributed": int((~attributed).sum()),
                      "carriers_without_chain": len(no_chain), **st})
    return e


def edit_rates(edits: pd.DataFrame, chains: dict[str, list[list[int]]]) -> pd.DataFrame:
    """``chains``: group_id -> every parsed chain of the group's occurrences."""
    trans: Counter = Counter()
    for g, raw in chains.items():
        tree = merge_tree(raw)
        for c in tree.chains:
            d = tree.component(c[0]).depth
            trans.update(d[n] for n in c[1:])
    n_edits = Counter(int(x) for x in edits.generation_depth.dropna())
    depths = sorted(set(trans) | set(n_edits))
    r = pd.DataFrame({"depth": depths, "n_transmissions": [trans[d] for d in depths],
                      "n_edits": [n_edits[d] for d in depths]}, dtype="int64")
    r["rate"] = r.n_edits / r.n_transmissions.where(r.n_transmissions > 0)
    return r


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
