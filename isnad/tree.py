"""Merged chain trees, common links and report dates (one report = one takhrij group).

All parsed chains of every occurrence of a group are unioned into one graph keyed by
rawi_id, edge parent (earlier narrator) -> child (later narrator). A group may have several
roots (several Companions); each root's component is built from the chains that start at that
root and analysed on its own.

* chain-terminal node ("compiler"): the last narrator of a chain. A compiler may also narrate
  mid-chain in another chain; it stays a terminal.
* ``k_branches(node)``: number of children whose subtree contains a chain terminal.
* common link under k: the shallowest node with ``k_branches >= k`` whose subtree (itself
  included) contains every terminal of the component; ties on depth go to the node carried by
  more chains, then the smaller rawi_id. Partial common links: every other node with
  ``k_branches >= k``.
* report date: the common link's ``death_lo/death_hi`` from the inferred narrator dates.
* k_branches counts distinct pupils (children reaching a terminal), not distinct compilers;
  ``n_compilers`` is reported alongside; ``cl_kN_all_chains`` gives the strict reading (every
  chain of the component passes through the common link).
* a chain that repeats a narrator non-consecutively (e.g. an isnad parsed twice and
  concatenated) is truncated before the first repeat, so it cannot create a back edge that
  inflates k_branches; a truncated chain shorter than 2 narrators is dropped.

Real chains can repeat a narrator or disagree on order, so the "tree" is a general directed
graph: reachability is a fixed point over terminal bitmasks (cycle-safe), depth is BFS distance.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pandas as pd

from isnad.constants import K_CL

log = logging.getLogger(__name__)


def clean_chain(chain) -> tuple[tuple[int, ...], bool]:
    """Collapse consecutive duplicates; truncate before the first non-consecutive repeat.

    Returns (chain, truncated)."""
    out: list[int] = []
    seen: set[int] = set()
    for r in chain:
        r = int(r)
        if out and out[-1] == r:
            continue
        if r in seen:
            return tuple(out), True
        out.append(r)
        seen.add(r)
    return tuple(out), False


_clean = clean_chain  # deprecated alias, kept for one release


@dataclass
class Tree:
    chains: list[tuple[int, ...]]
    children: dict[int, set[int]]
    roots: list[int]
    n_truncated: int = 0
    _components: dict[int, "Tree"] = field(default_factory=dict, repr=False)

    @cached_property
    def terminals(self) -> set[int]:
        return {c[-1] for c in self.chains}

    @cached_property
    def depth(self) -> dict[int, int]:
        """BFS distance from the nearest root."""
        d = {r: 0 for r in self.roots}
        q = deque(self.roots)
        while q:
            n = q.popleft()
            for c in self.children[n]:
                if c not in d:
                    d[c] = d[n] + 1
                    q.append(c)
        return d

    @cached_property
    def _chain_count(self) -> dict[int, int]:
        cnt: dict[int, int] = {}
        for ch in self.chains:
            for n in set(ch):
                cnt[n] = cnt.get(n, 0) + 1
        return cnt

    def n_chains_through(self, node: int) -> int:
        return self._chain_count.get(node, 0)

    @cached_property
    def term_mask(self) -> dict[int, int]:
        """Bitmask of the terminals reachable from each node (itself included)."""
        bit = {t: 1 << i for i, t in enumerate(sorted(self.terminals))}
        mask = {n: bit.get(n, 0) for n in self.children}
        changed = True
        while changed:  # fixed point; terminates on cycles since masks only grow
            changed = False
            for n, cs in self.children.items():
                m = mask[n]
                for c in cs:
                    m |= mask[c]
                if m != mask[n]:
                    mask[n] = m
                    changed = True
        return mask

    @cached_property
    def all_terminals(self) -> int:
        return (1 << len(self.terminals)) - 1

    def component(self, root: int) -> "Tree":
        if len(self.roots) == 1 and root == self.roots[0]:
            return self
        if root not in self._components:
            self._components[root] = merge_tree([c for c in self.chains if c[0] == root])
        return self._components[root]


def clean_chains(chains) -> tuple[list[tuple[int, ...]], int]:
    """clean_chain each chain; drop empty ones and truncated ones shorter than 2 narrators.

    Returns (kept chains, number truncated)."""
    cleaned: list[tuple[int, ...]] = []
    n_truncated = 0
    for ch in chains or []:
        c, truncated = clean_chain(ch)
        n_truncated += truncated
        if c and not (truncated and len(c) < 2):
            cleaned.append(c)
    return cleaned, n_truncated


def merge_tree(chains: list[list[int]]) -> Tree:
    """Union of chains (earliest narrator first, compiler last) into one graph."""
    cleaned, n_truncated = clean_chains(chains)
    children: dict[int, set[int]] = {}
    roots: list[int] = []
    for ch in cleaned:
        if ch[0] not in roots:
            roots.append(ch[0])
        for n in ch:
            children.setdefault(n, set())
        for a, b in zip(ch, ch[1:]):
            children[a].add(b)
    return Tree(cleaned, children, sorted(roots), n_truncated)


def k_branches(tree: Tree, node: int) -> int:
    m = tree.term_mask
    return sum(1 for c in tree.children.get(node, ()) if m[c])


def _cl_one(comp: Tree, k: int) -> int | None:
    full, m = comp.all_terminals, comp.term_mask
    best = None
    for n, d in comp.depth.items():
        if m[n] == full and k_branches(comp, n) >= k:
            key = (d, -comp.n_chains_through(n), n)
            if best is None or key < best:
                best = key
    return None if best is None else best[2]


def common_links(tree: Tree, k: int) -> list[int]:
    """The common link under k of each root's component (roots without one are skipped)."""
    out = [_cl_one(tree.component(r), k) for r in tree.roots]
    return [c for c in out if c is not None]


def partial_common_links(tree: Tree, k: int) -> list[int]:
    out: list[int] = []
    for r in tree.roots:
        comp = tree.component(r)
        cl = _cl_one(comp, k)
        out += sorted(n for n in comp.children if n != cl and k_branches(comp, n) >= k)
    return out


def analyse(group_id: str, tree: Tree) -> tuple[list[dict], list[dict]]:
    """(tree_nodes rows, report rows without dates) for one group, one report row per root."""
    nodes, reports = [], []
    for r in tree.roots:
        comp = tree.component(r)
        cls = {k: _cl_one(comp, k) for k in K_CL}
        kb = {n: k_branches(comp, n) for n in comp.children}
        for n in sorted(comp.children):
            row = {"group_id": group_id, "root_id": r, "rawi_id": n,
                   "depth": comp.depth.get(n, -1), "k_branches": kb[n],
                   "n_descendant_chains": comp.n_chains_through(n)}
            for k in K_CL:
                row[f"is_cl_k{k}"] = n == cls[k]
            for k in K_CL:
                row[f"is_pcl_k{k}"] = kb[n] >= k and n != cls[k]
            nodes.append(row)
        rep = {"group_id": group_id, "root_id": r}
        for k in K_CL:
            rep[f"cl_k{k}_id"] = cls[k]
            rep[f"cl_k{k}_all_chains"] = (None if cls[k] is None
                                          else comp.n_chains_through(cls[k]) == len(comp.chains))
        rep["n_chains"] = len(comp.chains)
        rep["n_compilers"] = len(comp.terminals)
        reports.append(rep)
    return nodes, reports


_REPORT_COLS = ["group_id", "root_id"] + [
    c for k in K_CL for c in (f"cl_k{k}_id", f"cl_k{k}_date_lo", f"cl_k{k}_date_hi",
                              f"cl_k{k}_all_chains")
] + ["n_chains", "n_compilers", "complete"]


def _attach_dates(rep: pd.DataFrame, groups: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    lo = dict(zip(dates.rawi_id, dates.death_lo))
    hi = dict(zip(dates.rawi_id, dates.death_hi))
    for k in K_CL:
        ids = rep[f"cl_k{k}_id"]
        rep[f"cl_k{k}_date_lo"] = [float(lo.get(i, float("nan"))) if pd.notna(i) else float("nan")
                                   for i in ids]
        rep[f"cl_k{k}_date_hi"] = [float(hi.get(i, float("nan"))) if pd.notna(i) else float("nan")
                                   for i in ids]
        rep[f"cl_k{k}_id"] = ids.astype("Int64")
        rep[f"cl_k{k}_all_chains"] = pd.array(list(rep[f"cl_k{k}_all_chains"]), dtype="boolean")
    rep["root_id"] = rep["root_id"].astype("Int64")
    complete = dict(zip(groups.group_id, groups.complete)) if "complete" in groups else {}
    rep["complete"] = pd.array([complete.get(g) for g in rep.group_id], dtype="boolean")
    rep["n_chains"] = rep["n_chains"].astype("int64")
    rep["n_compilers"] = rep["n_compilers"].astype("int64")
    return rep[_REPORT_COLS]


def _empty_report(group_id: str) -> dict:
    return {"group_id": group_id, "root_id": None,
            **{f"cl_k{k}_id": None for k in K_CL},
            **{f"cl_k{k}_all_chains": None for k in K_CL}, "n_chains": 0, "n_compilers": 0}


def report_dates(groups: pd.DataFrame, trees: dict[str, Tree], dates: pd.DataFrame
                 ) -> pd.DataFrame:
    """One row per (group, root); a group without chains gets one all-null row, n_chains 0."""
    rows: list[dict] = []
    for g in groups.group_id:
        t = trees.get(g)
        if t is None or not t.roots:
            rows.append(_empty_report(g))
        else:
            rows += analyse(g, t)[1]
    return _attach_dates(pd.DataFrame(rows, columns=[c for c in _REPORT_COLS
                                                      if "date" not in c and c != "complete"]),
                         groups, dates)


def load_chains(path: str | Path) -> dict[int, list[list[int]]]:
    """hadith_id -> chains (earliest first), unjoined chains dropped."""
    c = pd.read_parquet(path, columns=["hadith_id", "chain_no", "position", "rawi_id", "unjoined"])
    bad = c.loc[c.unjoined, ["hadith_id", "chain_no"]].drop_duplicates()
    if len(bad):
        c = c.merge(bad.assign(_bad=True), on=["hadith_id", "chain_no"], how="left")
        c = c[c._bad.isna()]
    c = c.sort_values(["hadith_id", "chain_no", "position"])
    per_chain = c.groupby(["hadith_id", "chain_no"], sort=False).rawi_id.agg(list)
    out: dict[int, list[list[int]]] = {}
    for (hid, _), ch in per_chain.items():
        out.setdefault(int(hid), []).append(ch)
    return out


_NODE_COLS = ["group_id", "root_id", "rawi_id", "depth", "k_branches", "n_descendant_chains"] + [
    f"is_cl_k{k}" for k in K_CL] + [f"is_pcl_k{k}" for k in K_CL]


def run_tree(chains_path, occurrences_path, groups_path, dates_path, out_dir,
             shawahid_path=None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chains = load_chains(chains_path)
    occ = pd.read_parquet(occurrences_path, columns=["group_id", "hadith_id"])
    groups = pd.read_parquet(groups_path, columns=["group_id", "complete"])
    extra = sorted(set(occ.group_id) - set(groups.group_id))
    if extra:
        groups = pd.concat([groups, pd.DataFrame({"group_id": extra, "complete": None})],
                           ignore_index=True)
    dates = (pd.read_parquet(dates_path, columns=["rawi_id", "death_lo", "death_hi"])
             if dates_path and Path(dates_path).exists()
             else pd.DataFrame({"rawi_id": [], "death_lo": [], "death_hi": []}))
    if dates.empty:
        log.warning("no narrator dates at %s: report dates will be null", dates_path)

    hids = occ.groupby("group_id").hadith_id.agg(lambda s: sorted(set(s)))
    node_rows: list[dict] = []
    rep_rows: list[dict] = []
    stats = {"groups": 0, "ge2_chains": 0, "k2_cl": 0, "k3_cl": 0, "multi_root": 0,
             "no_chains": 0, "chains_truncated_repeat": 0}
    for g in groups.group_id:
        stats["groups"] += 1
        t = merge_tree([ch for h in hids.get(g, []) for ch in chains.get(h, [])])
        stats["chains_truncated_repeat"] += t.n_truncated
        if not t.roots:
            stats["no_chains"] += 1
            rep_rows.append(_empty_report(g))
            continue
        n, r = analyse(g, t)
        node_rows += n
        rep_rows += r
        stats["ge2_chains"] += len(t.chains) >= 2
        stats["k2_cl"] += any(x["cl_k2_id"] is not None for x in r)
        stats["k3_cl"] += any(x["cl_k3_id"] is not None for x in r)
        stats["multi_root"] += len(t.roots) > 1

    nodes = pd.DataFrame(node_rows, columns=_NODE_COLS)
    nodes.to_parquet(out / "tree_nodes.parquet", index=False)
    rep = _attach_dates(pd.DataFrame(rep_rows, columns=[c for c in _REPORT_COLS if "date" not in c
                                                         and c != "complete"]), groups, dates)
    rep.to_parquet(out / "report_dates.parquet", index=False)
    stats["report_rows"] = len(rep)
    stats["k2_dated"] = int(rep.cl_k2_date_lo.notna().sum())

    if shawahid_path and Path(shawahid_path).exists():
        sh = pd.read_parquet(shawahid_path, columns=["group_id", "hadith_ids"])
        rows = []
        for g, ids in zip(sh.group_id, sh.hadith_ids):
            for h in ids if ids is not None else []:
                comps = sorted({clean_chain(ch)[0][0] for ch in chains.get(int(h), []) if len(ch)})
                rows += ([(g, int(h), c) for c in comps] or [(g, int(h), None)])
        sc = pd.DataFrame(rows, columns=["group_id", "hadith_id", "companion_rawi_id"])
        sc["companion_rawi_id"] = sc.companion_rawi_id.astype("Int64")
        sc.to_parquet(out / "shawahid_companions.parquet", index=False)
        stats["shawahid_rows"] = len(sc)
        stats["shawahid_resolved"] = int(sc.companion_rawi_id.notna().sum())
    print(" ".join(f"{k} {v}" for k, v in stats.items()))
    return stats
