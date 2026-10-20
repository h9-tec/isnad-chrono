"""Narrator dating by difference-constraint propagation over the chain graph.

Variables per narrator: birth b_i and death d_i, each kept as an interval [lo, hi] (AH).
Constraints:
  * known date (any death_kind/birth_kind other than "none"): year +- DATE_K * max(sd, 1)
  * unknown: death [YEAR_LO, YEAR_HI], birth [BIRTH_LO, YEAR_HI] (pre-Hijra births allowed)
  * lifespan: AGE_MIN <= d_i - b_i <= AGE_MAX
  * link teacher T -> student S: b_S + A0 <= d_T
Propagation tightens the bounds (Jacobi rounds, vectorised over links) until nothing changes
or MAX_ITER rounds. A narrator whose interval empties in a round drops the lightest link that
bound it that round (preferring a link whose removal alone restores feasibility, then
ambiguous-class before explicit; see _choose_drops), gets its pre-round interval back, and the round continues. Once a pass converges with drops, propagation is
restarted from the priors with the surviving links so dropped links leave no residue.
"""

import json
import logging
import time

import numpy as np
import pandas as pd

from isnad.constants import (A0, AGE_MAX, AGE_MIN, BIRTH_LO, DATE_K, HOLDOUT_FOLDS, MAX_ITER,
                             YEAR_HI, YEAR_LO)
from isnad.score import classify_term

log = logging.getLogger(__name__)

MAX_PASSES = 5  # clean restarts after drops
BOUNDED_WIDTH = 3 * AGE_MAX  # hold-out: death intervals at most this wide count as bounded
INTERVAL_COLS = ["rawi_id", "birth_lo", "birth_hi", "death_lo", "death_hi", "death_mode",
                 "support", "method"]
DROPPED_COLS = ["teacher_id", "student_id", "weight", "cls", "reason", "pass", "round"]


# ---------------------------------------------------------------- inputs

def build_links(chains: pd.DataFrame) -> pd.DataFrame:
    """Unique teacher->student links from chains: weight = count, cls = majority term class.

    Position p is the teacher of position p+1 within one (hadith_id, chain_no); the term sits
    on the teacher row. Chains flagged unjoined are dropped. Unclassified terms count as
    ambiguous (no audition claim); explicit wins a tie.
    """
    c = chains[~chains["unjoined"].astype(bool)]
    c = c.sort_values(["hadith_id", "chain_no", "position"])
    nxt = c.shift(-1)
    same = ((nxt["hadith_id"] == c["hadith_id"]) & (nxt["chain_no"] == c["chain_no"])
            & (nxt["position"] == c["position"] + 1))
    pairs = pd.DataFrame({"teacher_id": c.loc[same, "rawi_id"].astype("int64"),
                          "student_id": nxt.loc[same, "rawi_id"].astype("int64"),
                          "term": c.loc[same, "term"]})
    pairs = pairs[pairs["teacher_id"] != pairs["student_id"]]
    classes = {t: classify_term(t) for t in pairs["term"].dropna().unique()}
    pairs["explicit"] = pairs["term"].map(classes).eq("explicit")
    g = pairs.groupby(["teacher_id", "student_id"])["explicit"].agg(["size", "sum"])
    out = pd.DataFrame({"weight": g["size"].astype("int64"),
                        "cls": np.where(2 * g["sum"] >= g["size"], "explicit", "ambiguous")},
                       index=g.index).reset_index()
    return out


def chain_depth(chains: pd.DataFrame) -> dict:
    """rawi_id -> mean chain position over joined chains (0 = earliest)."""
    c = chains[~chains["unjoined"].astype(bool)]
    return c.groupby("rawi_id")["position"].mean().to_dict()


def _known_interval(year, sd, kind, prior_lo):
    year = pd.to_numeric(year, errors="coerce").to_numpy(float)
    sd = np.maximum(pd.to_numeric(sd, errors="coerce").fillna(1.0).to_numpy(float), 1.0)
    known = ~np.isnan(year) & (kind.fillna("none").to_numpy() != "none")
    lo = np.where(known, year - DATE_K * sd, prior_lo).astype(float)
    hi = np.where(known, year + DATE_K * sd, YEAR_HI).astype(float)
    return lo, hi, known


def _lifespan(blo, bhi, dlo, dhi):
    """Close birth/death intervals under AGE_MIN <= d - b <= AGE_MAX (in place)."""
    np.maximum(dlo, blo + AGE_MIN, out=dlo)
    np.minimum(dhi, bhi + AGE_MAX, out=dhi)
    np.maximum(blo, dlo - AGE_MAX, out=blo)
    np.minimum(bhi, dhi - AGE_MIN, out=bhi)


def _priors(narrators: pd.DataFrame):
    dlo, dhi, dknown = _known_interval(narrators["death_year"], narrators["death_sd"],
                                       narrators["death_kind"], YEAR_LO)
    blo, bhi, bknown = _known_interval(narrators["birth_year"], narrators["birth_sd"],
                                       narrators["birth_kind"], BIRTH_LO)
    # A recorded birth that contradicts the recorded death under the lifespan bounds is the
    # weaker datum: fall back to the birth prior.
    clash = bknown & ((dlo > bhi + AGE_MAX) | (dhi < blo + AGE_MIN))
    blo[clash], bhi[clash] = BIRTH_LO, YEAR_HI
    _lifespan(blo, bhi, dlo, dhi)
    if ((blo > bhi) | (dlo > dhi)).any():  # cannot happen once clashes are reset
        raise ValueError("dating: infeasible prior intervals")
    return blo, bhi, dlo, dhi, dknown, int(clash.sum())


# ---------------------------------------------------------------- propagation

def _feasible(blo, bhi, dlo, dhi) -> bool:
    a = np.array([blo, bhi, dlo, dhi], dtype=float)
    _lifespan(*(a[i:i + 1] for i in range(4)))
    return a[0] <= a[1] and a[2] <= a[3]


def _choose_drops(empty, rt, ridx, rval, ls, lidx, lval, prev, w, expl) -> np.ndarray:
    """One link to drop per emptied narrator.

    The links that tightened narrator k this round are the binding ones: the raise of
    death_lo[k] by the largest b_S + A0 (k as teacher) and the cut of birth_hi[k] by the
    smallest d_T - A0 (k as student). A side whose binding link alone, if removed, leaves k
    feasible is preferred; among the candidates ambiguous links go before explicit ones,
    then the lightest, then the lowest link index.
    """
    blo, bhi, dlo, dhi = prev
    ro, lo_ = np.argsort(rt, kind="stable"), np.argsort(ls, kind="stable")
    rt, ridx, rval = rt[ro], ridx[ro], rval[ro]
    ls, lidx, lval = ls[lo_], lidx[lo_], lval[lo_]
    kill = set()
    for k in empty:
        a, b = np.searchsorted(rt, k), np.searchsorted(rt, k, side="right")
        c, d = np.searchsorted(ls, k), np.searchsorted(ls, k, side="right")
        rv, ri, lv, li = rval[a:b], ridx[a:b], lval[c:d], lidx[c:d]
        new_dlo = rv.max() if len(rv) else dlo[k]
        new_bhi = lv.min() if len(lv) else bhi[k]
        resolving, binding = [], []
        if len(rv):
            top = ri[rv == new_dlo]
            binding += list(top)
            rest = rv[rv < new_dlo]
            alt = max(dlo[k], rest.max()) if len(rest) else dlo[k]
            if len(top) == 1 and _feasible(blo[k], new_bhi, alt, dhi[k]):
                resolving += list(top)
        if len(lv):
            top = li[lv == new_bhi]
            binding += list(top)
            rest = lv[lv > new_bhi]
            alt = min(bhi[k], rest.min()) if len(rest) else bhi[k]
            if len(top) == 1 and _feasible(blo[k], alt, new_dlo, dhi[k]):
                resolving += list(top)
        cand = np.array(resolving or binding, dtype=np.int64)
        if len(cand):
            kill.add(int(cand[np.lexsort((cand, w[cand], expl[cand]))[0]]))
    return np.array(sorted(kill), dtype=np.int64)


def _run(prior, t, s, w, expl, alive, max_iter, pass_no, drops):
    blo, bhi, dlo, dhi = (a.copy() for a in prior)
    rounds, converged = 0, False
    for rnd in range(1, max_iter + 1):
        rounds = rnd
        idx = np.flatnonzero(alive)
        T, S = t[idx], s[idx]
        cand_d = blo[S] + A0  # raises death_lo[T]
        cand_b = dhi[T] - A0  # lowers birth_hi[S]
        nblo, nbhi, ndlo, ndhi = blo.copy(), bhi.copy(), dlo.copy(), dhi.copy()
        np.maximum.at(ndlo, T, cand_d)
        np.minimum.at(nbhi, S, cand_b)
        _lifespan(nblo, nbhi, ndlo, ndhi)
        empty = (nblo > nbhi) | (ndlo > ndhi)
        dropped_now = 0
        if empty.any():
            tt = (cand_d > dlo[T]) & empty[T]
            ts = (cand_b < bhi[S]) & empty[S]
            kill = _choose_drops(np.flatnonzero(empty), T[tt], idx[tt], cand_d[tt],
                                 S[ts], idx[ts], cand_b[ts], (blo, bhi, dlo, dhi), w, expl)
            if len(kill):
                alive[kill] = False
                dropped_now = len(kill)
                drops.append((kill, pass_no, rnd))
            nblo[empty], nbhi[empty] = blo[empty], bhi[empty]
            ndlo[empty], ndhi[empty] = dlo[empty], dhi[empty]
        changed = not (np.array_equal(nblo, blo) and np.array_equal(nbhi, bhi)
                       and np.array_equal(ndlo, dlo) and np.array_equal(ndhi, dhi))
        blo, bhi, dlo, dhi = nblo, nbhi, ndlo, ndhi
        if not changed and not dropped_now:
            converged = True
            break
    return (blo, bhi, dlo, dhi), rounds, converged


def propagate(narrators: pd.DataFrame, links: pd.DataFrame, max_iter: int = MAX_ITER):
    """-> (intervals, dropped). See module docstring.

    narrators: rawi_id, death_year, death_sd, death_kind, birth_year, birth_sd, birth_kind.
    links: teacher_id, student_id, weight, cls. Link endpoints missing from narrators are added
    as unknown narrators.
    """
    nar = narrators.drop_duplicates("rawi_id").reset_index(drop=True)
    extra = pd.Index(pd.unique(pd.concat([links["teacher_id"], links["student_id"]])))
    extra = extra.difference(nar["rawi_id"])
    if len(extra):
        nar = pd.concat([nar, pd.DataFrame({"rawi_id": extra.astype("int64"),
                                            "death_kind": "none", "birth_kind": "none"})],
                        ignore_index=True)
    for col, default in (("death_year", np.nan), ("death_sd", np.nan), ("birth_year", np.nan),
                         ("birth_sd", np.nan), ("death_kind", "none"), ("birth_kind", "none")):
        if col not in nar:
            nar[col] = default
    pos = pd.Series(np.arange(len(nar)), index=nar["rawi_id"].to_numpy())
    t = pos.reindex(links["teacher_id"].to_numpy()).to_numpy()
    s = pos.reindex(links["student_id"].to_numpy()).to_numpy()
    w = links["weight"].to_numpy(float)
    expl = (links["cls"].to_numpy() == "explicit").astype(np.int8)
    alive = t != s

    *prior, dknown, n_clash = _priors(nar)
    drops: list = []
    n_before = 0
    for pass_no in range(1, MAX_PASSES + 1):
        final, rounds, converged = _run(prior, t, s, w, expl, alive, max_iter, pass_no, drops)
        n_now = sum(len(k) for k, _, _ in drops)
        if n_now == n_before:  # clean pass: a fixpoint of the surviving links
            break
        n_before = n_now
    blo, bhi, dlo, dhi = final

    support = (np.bincount(t[alive], minlength=len(nar))
               + np.bincount(s[alive], minlength=len(nar)))
    touched = ~(np.isclose(blo, prior[0]) & np.isclose(bhi, prior[1])
                & np.isclose(dlo, prior[2]) & np.isclose(dhi, prior[3]))
    method = np.where(dknown, "known", np.where(touched, "inferred", "prior_only"))
    iv = pd.DataFrame({"rawi_id": nar["rawi_id"].astype("int64").to_numpy(),
                       "birth_lo": blo, "birth_hi": bhi, "death_lo": dlo, "death_hi": dhi,
                       "death_mode": (dlo + dhi) / 2, "support": support.astype("int64"),
                       "method": method})
    iv.attrs.update(rounds=rounds, converged=converged, passes=pass_no, birth_clashes=n_clash)
    if not converged:
        log.warning("dating: not converged after %d rounds (pass %d)", rounds, pass_no)

    rows = [(k, p, r) for k, p, r in drops]
    if rows:
        kill = np.concatenate([k for k, _, _ in rows])
        dropped = links.iloc[kill][["teacher_id", "student_id", "weight", "cls"]].copy()
        dropped["reason"] = "negative_cycle"
        dropped["pass"] = np.concatenate([np.full(len(k), p) for k, p, _ in rows])
        dropped["round"] = np.concatenate([np.full(len(k), r) for k, _, r in rows])
        dropped = dropped.reset_index(drop=True)
    else:
        dropped = pd.DataFrame({c: pd.Series(dtype=d) for c, d in zip(
            DROPPED_COLS, ["int64", "int64", "int64", "str", "str", "int64", "int64"])})
    return iv, dropped


# ---------------------------------------------------------------- hold-out

def _metrics(pred, truth, lo, hi) -> dict:
    ok = ~np.isnan(pred)
    n = int(ok.sum())
    if not n:
        return {"median_abs_error": None, "coverage_90": None, "median_width": None, "n": 0}
    err = np.abs(pred[ok] - truth[ok])
    cov = (truth[ok] >= lo[ok]) & (truth[ok] <= hi[ok])
    return {"median_abs_error": float(np.median(err)), "mean_abs_error": float(np.mean(err)),
            "coverage_90": float(cov.mean()), "median_width": float(np.median(hi[ok] - lo[ok])),
            "n": n}


def _pool(per_fold: list[dict], key: str) -> dict:
    p = pd.concat([f[key] for f in per_fold], ignore_index=True)
    return _metrics(p["pred"].to_numpy(float), p["truth"].to_numpy(float),
                    p["lo"].to_numpy(float), p["hi"].to_numpy(float))


def holdout(narrators: pd.DataFrame, links: pd.DataFrame, folds: int = HOLDOUT_FOLDS,
            seed: int = 0, depth: dict | None = None) -> dict:
    """Hide exact death years fold by fold, re-propagate, score death_mode against the truth.

    Scored narrators: hidden ones that touch at least one link (the rest carry no chain
    evidence). Baselines on the same narrators: `depth` = mean known death of non-hidden
    narrators at the same rounded mean chain position (interval: that bucket's 5-95%
    quantiles); `generation` = midpoint of generation_num's century (interval: the century),
    NaN when absent; `generation_mean` = mean known death of non-hidden narrators of the same
    generation_num (interval: 5-95% quantiles). `method_bounded` = `method` restricted to
    death intervals no wider than BOUNDED_WIDTH; `method_no_birth` = `method` restricted to
    narrators without a recorded birth.
    """
    nar = narrators.drop_duplicates("rawi_id").reset_index(drop=True)
    in_graph = set(links["teacher_id"]) | set(links["student_id"])
    exact = nar.index[(nar["death_kind"] == "exact") & nar["death_year"].notna()].to_numpy()
    rng = np.random.default_rng(seed)
    parts = np.array_split(rng.permutation(exact), folds)
    depth_s = pd.Series(depth or {}, dtype=float)
    per_fold, summary = [], []
    for k, hide in enumerate(parts):
        f = nar.copy()
        truth = f.loc[hide, ["rawi_id", "death_year"]].set_index("rawi_id")["death_year"]
        f.loc[hide, ["death_year", "death_sd"]] = np.nan
        f.loc[hide, "death_kind"] = "none"
        iv, dropped = propagate(f, links)
        ev = truth[truth.index.isin(in_graph)]
        ids = ev.index.to_numpy()
        tr = ev.to_numpy(float)
        ivi = iv.set_index("rawi_id").loc[ids]
        res = {"method": pd.DataFrame({"pred": ivi["death_mode"].to_numpy(), "truth": tr,
                                       "lo": ivi["death_lo"].to_numpy(),
                                       "hi": ivi["death_hi"].to_numpy()})}
        # the midpoint of a half-open interval ([lo, 1500]) is not an estimate: report the
        # narrators the chains bound on both sides separately
        bounded = (ivi["death_hi"] - ivi["death_lo"]).to_numpy() <= BOUNDED_WIDTH
        res["method_bounded"] = res["method"].where(pd.Series(bounded), axis=0)
        # hidden narrators keep a recorded birth (only the death is hidden): score those
        # without one separately, as the birth alone pins death to [b + AGE_MIN, b + AGE_MAX]
        no_birth = (f.set_index("rawi_id").loc[ids, "birth_kind"].fillna("none") == "none")
        res["method_no_birth"] = res["method"].where(pd.Series(no_birth.to_numpy()), axis=0)
        # baselines from the non-hidden known deaths
        vis = f[f["death_kind"] != "none"].dropna(subset=["death_year"])
        vis_depth = depth_s.reindex(vis["rawi_id"]).round().to_numpy()
        bk = pd.DataFrame({"b": vis_depth, "y": vis["death_year"].to_numpy()}).dropna()
        stats = bk.groupby("b")["y"].agg(mean="mean", lo=lambda y: y.quantile(.05),
                                         hi=lambda y: y.quantile(.95))
        b = depth_s.reindex(ids).round()
        st = stats.reindex(b.to_numpy())
        res["depth"] = pd.DataFrame({"pred": st["mean"].to_numpy(), "truth": tr,
                                     "lo": st["lo"].to_numpy(), "hi": st["hi"].to_numpy()})
        gen = nar.set_index("rawi_id").loc[ids, "generation_num"].to_numpy(float)
        res["generation"] = pd.DataFrame({"pred": (gen - 0.5) * 100, "truth": tr,
                                          "lo": (gen - 1) * 100, "hi": gen * 100})
        gs = vis.groupby("generation_num")["death_year"].agg(
            mean="mean", lo=lambda y: y.quantile(.05), hi=lambda y: y.quantile(.95))
        gst = gs.reindex(gen)
        res["generation_mean"] = pd.DataFrame({"pred": gst["mean"].to_numpy(), "truth": tr,
                                               "lo": gst["lo"].to_numpy(),
                                               "hi": gst["hi"].to_numpy()})
        per_fold.append(res)
        summary.append({"fold": k, "n_hidden": int(len(hide)), "n_scored": int(len(ids)),
                        "n_dropped_links": int(len(dropped)),
                        **{key: _metrics(*(r[c].to_numpy(float) for c in
                                           ("pred", "truth", "lo", "hi")))
                           for key, r in res.items()}})
    out = {"folds": folds, "seed": seed, "n_exact": int(len(exact)),
           "n_scored": int(sum(s["n_scored"] for s in summary))}
    for key in ("method", "method_bounded", "method_no_birth", "depth", "generation",
                "generation_mean"):
        out[key] = _pool(per_fold, key)
    out["per_fold"] = summary
    return out


# ---------------------------------------------------------------- CLI entry

def run_dating(chains_path, rawi_path, out_path, dropped_path, holdout_path,
               folds: int = HOLDOUT_FOLDS) -> dict:
    t0 = time.time()
    chains = pd.read_parquet(chains_path)
    rawi = pd.read_parquet(rawi_path)
    links = build_links(chains)
    t1 = time.time()
    iv, dropped = propagate(rawi, links)
    t2 = time.time()
    iv[INTERVAL_COLS].to_parquet(out_path, index=False)
    dropped.to_parquet(dropped_path, index=False)
    m = holdout(rawi, links, folds=folds, depth=chain_depth(chains))
    t3 = time.time()
    m["run"] = {"n_links": int(len(links)), "n_narrators": int(len(iv)),
                "n_dropped": int(len(dropped)),
                "methods": iv["method"].value_counts().to_dict(),
                "methods_in_graph": iv.loc[iv["support"] > 0, "method"].value_counts().to_dict(),
                **{k: (bool(v) if isinstance(v, (bool, np.bool_)) else int(v))
                   for k, v in iv.attrs.items()},
                "seconds": {"links": round(t1 - t0, 2), "propagate": round(t2 - t1, 2),
                            "holdout": round(t3 - t2, 2)}}
    with open(holdout_path, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    return m
