"""Hugging Face release (v2): derived numbers and text hashes only, plus automatic checks.

``build_release`` reads the stage outputs from ``data_dir`` (each input path can be overridden),
selects an explicit column list per config, rejects any denylisted column (``isnad.export``:
no ``*_text``, ``*_name``, names, statements) and any string cell longer than ``MAX_STR_LEN``
(a guard against text leaking through an innocently named column), writes one parquet per config
under ``out/data/``, ``checks.json``, ``MANIFEST.json`` and ``README.md`` (the dataset card
``DATASET_CARD_v2.md`` with the check numbers filled in).

The local text store (``text/segments_text.parquet``) and the cached pages are read only for the
alignment check and never copied. ``push`` re-verifies the folder before uploading.
"""

import difflib
import json
import logging
import math
import random
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from isnad import chains as chains_mod
from isnad import dating, edits, tree
from isnad.constants import ALIGN_SAMPLE, K_CL
from isnad.dates import _norm
from isnad.export import check_columns
from isnad.groups import SCHEMAS

log = logging.getLogger(__name__)

VERSION = "v0.1"
REPO_ID = "HeshamHaroon/isnad-chrono"
ENV_FILE = "~/.config/isnad-chrono/.env"
CARD = Path(__file__).resolve().parent.parent / "DATASET_CARD_v2.md"
ALIGN_SLACK = 3  # an agreeing opcode spans at most the substitution length + this many tokens
MAX_STR_LEN = 96  # longest real transmission formula is 65 chars
Manifest = dict

INPUTS = {
    "chains": "chains.parquet",
    "groups": "groups.parquet",
    "occurrences": "occurrences.parquet",
    "segments": "segments.parquet",
    "shawahid": "shawahid.parquet",
    "text": "text/segments_text.parquet",  # local only: alignment check
    "dates": "rawi_dates_inferred.parquet",
    "dropped": "dropped_links.parquet",
    "checks_dating": "checks_dating.json",
    "tree_nodes": "tree_nodes.parquet",
    "report_dates": "report_dates.parquet",
    "shawahid_companions": "shawahid_companions.parquet",
    "edits": "edits.parquet",
    "edit_rates": "edit_rates.parquet",
    "rawi": "rawi.parquet",
    "edge_scores": "edge_scores.parquet",
}

NARRATOR_COLS = ["rawi_id", "generation_num", "death_year", "death_kind", "birth_year",
                 "birth_kind", "death_lo", "death_hi", "death_mode", "birth_lo", "birth_hi",
                 "support", "method"]
EDGE_SCORE_COLS = ["teacher_id", "student_id", "hadith_id", "position", "term", "chain_type",
                   "entry_kind", "p_meet", "how", "conflict_t", "conflict_s", "confirmed",
                   "explicit_term", "ambiguous_term", "denied", "irsal", "tadlis", "verdict"]
EDIT_RATE_COLS = ["depth", "n_transmissions", "n_edits", "rate", "n_edits_nonleaf",
                  "rate_nonleaf"]
# config -> (input key, columns; None = every column of the input)
_TABLES = {
    "chains": ("chains", chains_mod.COLUMNS),
    "groups": ("groups", SCHEMAS["groups"].names),
    "occurrences": ("occurrences", SCHEMAS["occurrences"].names),
    "tree_nodes": ("tree_nodes", tree._NODE_COLS),
    "report_dates": ("report_dates", tree._REPORT_COLS),
    "edits": ("edits", edits.EDIT_COLS),
    "edge_scores": ("edge_scores", EDGE_SCORE_COLS),
}
# written when the input exists; ids and hashes only (shawahid loses companion_name)
_OPTIONAL = {
    "segments": ("segments", SCHEMAS["segments"].names),
    "shawahid": ("shawahid", ["group_id", "companion_rawi_id", "hadith_ids"]),
    "shawahid_companions": ("shawahid_companions", ["group_id", "hadith_id", "companion_rawi_id"]),
    "edit_rates": ("edit_rates", EDIT_RATE_COLS),
    "dropped_links": ("dropped", dating.DROPPED_COLS),
}
REQUIRED_CONFIGS = ["narrators", *_TABLES, "checks"]
RELEASE_FILES = frozenset({"README.md", "checks.json", "MANIFEST.json"}
                          | {f"data/{c}.parquet" for c in [*REQUIRED_CONFIGS, *_OPTIONAL]})
# push refuses a release whose headline checks are null
PUSH_REQUIRED_CHECKS = ("alignment_agreement", "alignment_surface_found_rate",
                        "sanity_n_dropped_links")
REPO_ROOT = Path(__file__).resolve().parent.parent

_WS = re.compile(r"\s+")
_NONWORD = re.compile(r"[^\w]+")


# ---------------------------------------------------------------- alignment check

def tokens(s: str | None) -> list[str]:
    """Normalised word tokens (diacritics and punctuation stripped)."""
    out = (_NONWORD.sub("", t) for t in _WS.split(_norm(s or "")))
    return [t for t in out if t]


def site_spans(seg: pd.DataFrame, texts: dict[str, str]
               ) -> tuple[list[str], list[tuple[int, set, tuple[str, ...]]]]:
    """(base tokens, [(gap position, carrier ids, substitution tokens)]) of a group.

    The base reading is the concatenation of the base segments. A substitution replaces the
    tail of the base segment before it, so its site span ends at the gap after that segment.
    """
    base: list[str] = []
    spans: list[tuple[int, set, tuple[str, ...]]] = []
    for kind, bh, vh, car in zip(seg.kind, seg.base_hash, seg.variant_hash,
                                 seg.carrier_hadith_ids):
        if kind == "base":
            base += tokens(texts.get(bh) if isinstance(bh, str) else None)
        elif kind == "substitution":
            sub = tuple(tokens(texts.get(vh) if isinstance(vh, str) else None))
            spans.append((len(base), {int(h) for h in (car if car is not None else [])}, sub))
    return base, spans


def _rate(st: Counter, num: str, den: str) -> float | None:
    return st[num] / st[den] if st[den] else None


def _hit(ops, pos: int, tol: int, limit: float) -> bool:
    return any(size <= limit and i1 - tol <= pos <= i2 + tol for i1, i2, size in ops)


def alignment_check(segments: pd.DataFrame, texts: dict[str, str],
                    matns: Callable[[Iterable[int]], dict[int, str]] | dict[int, str],
                    sample: int = ALIGN_SAMPLE, seed: int = 0, tol: int = 1,
                    slack: int | None = ALIGN_SLACK) -> dict:
    """Re-align the base reading against each carrier's own matn with difflib on token lists.

    For sampled groups with at least one substitution, a (substitution, carrier) pair agrees
    when a difflib replace/insert/delete opcode lies within ``tol`` tokens of the site span's
    gap on the base side and is local: its larger side is at most the substitution's length
    plus ``slack`` tokens (None = any size; a carrier that covers only part of a long report
    yields one huge delete that would "agree" with every span). ``matns`` maps hadith_id ->
    matn (or loads them for a list of ids); pairs whose carrier has no text are counted, not
    scored. Control: every scored text of the group that carries no substitution at a slot is
    checked at that slot by the same rule; ``control_hit_rate`` (lower is better) is the rate at
    which a text without the variant still "agrees", i.e. the agreement expected by chance.

    A second, position-free reading: ``surface_found_rate`` = share of scored pairs whose
    carrier text contains the substitution's surface as a whole-token run;
    ``control_surface_found_rate`` = the same for the group's texts that do not carry any
    substitution at that slot.
    """
    subs = segments[segments.kind == "substitution"]
    ids = sorted(set(subs.group_id))
    chosen = sorted(random.Random(seed).sample(ids, min(sample, len(ids))))
    seg = segments[segments.group_id.isin(set(chosen))].sort_values(["group_id", "seg_no"])
    per_group = {g: site_spans(df, texts) for g, df in seg.groupby("group_id", sort=True)}
    need = sorted({h for _, spans in per_group.values() for _, cs, _ in spans for h in cs})
    joined: dict[int, str] = {}
    text_of = matns if isinstance(matns, dict) else matns(need)
    lim = (lambda n: float("inf")) if slack is None else (lambda n: n + slack)
    st: Counter = Counter()
    for g in chosen:
        base, spans = per_group.get(g, ([], []))
        st["groups"] += 1
        if not base:
            st["groups_no_base"] += 1
            continue
        diffs: dict[int, list[tuple[int, int, int]] | None] = {}
        scored = False
        for pos, carriers, sub in spans:
            for h in sorted(carriers):
                if h not in diffs:
                    var = tokens(text_of.get(h))
                    joined[h] = f" {' '.join(var)} "
                    diffs[h] = None if not var else [
                        (i1, i2, max(i2 - i1, j2 - j1)) for tag, i1, i2, j1, j2 in
                        difflib.SequenceMatcher(None, base, var, autojunk=False).get_opcodes()
                        if tag != "equal"]
                st["pairs"] += 1
                if diffs[h] is None:
                    st["pairs_missing_text"] += 1
                    continue
                scored = True
                st["pairs_scored"] += 1
                st["pairs_agree"] += _hit(diffs[h], pos, tol, lim(len(sub)))
                if sub:
                    st["surface_pairs"] += 1
                    st["surface_found"] += f" {' '.join(sub)} " in joined[h]
        st["groups_scored"] += scored
        at_slot: dict[int, tuple[set, int]] = {}
        for pos, carriers, sub in spans:
            cs, n = at_slot.get(pos, (set(), 0))
            at_slot[pos] = (cs | carriers, max(n, len(sub)))
        for pos, _, sub in spans:
            for h, d in diffs.items():
                if d is not None and sub and h not in at_slot[pos][0]:
                    st["control_surface_pairs"] += 1
                    st["control_surface_found"] += f" {' '.join(sub)} " in joined[h]
        for pos, (carriers, n_sub) in at_slot.items():
            for h, d in diffs.items():
                if d is not None and h not in carriers:
                    st["control_pairs"] += 1
                    st["control_hits"] += _hit(d, pos, tol, lim(n_sub))
    n, nc = st["pairs_scored"], st["control_pairs"]
    return {"agreement": (st["pairs_agree"] / n) if n else None,
            "control_hit_rate": (st["control_hits"] / nc) if nc else None,
            "n_groups": st["groups"], "n_groups_scored": st["groups_scored"],
            "n_groups_no_base": st["groups_no_base"], "n_pairs": st["pairs"],
            "n_pairs_scored": n, "n_control_pairs": nc,
            "surface_found_rate": _rate(st, "surface_found", "surface_pairs"),
            "control_surface_found_rate": _rate(st, "control_surface_found",
                                                "control_surface_pairs"),
            "n_pairs_no_carrier_matn": st["pairs_missing_text"], "tolerance": tol,
            "slack": slack, "sample": sample, "seed": seed}


def matn_loader(cache_root: str | Path) -> Callable[[Iterable[int]], dict[int, str]]:
    """Read each carrier's ``matn`` from the cached hadith pages (read-only)."""
    from isnad import pageprops
    from isnad.build import _PARSE_ERRORS, read_page

    root = Path(cache_root) / "hadith"

    def load(ids: Iterable[int]) -> dict[int, str]:
        out: dict[int, str] = {}
        for h in ids:
            p = next((q for q in (root / f"{h}.html.gz", root / f"{h}.html") if q.exists()), None)
            if p is None:
                continue
            try:
                m = pageprops.extract(read_page(p))["hadith"].get("matn")
            except (*_PARSE_ERRORS, KeyError) as e:
                log.warning("%s: %s", p, e)
                continue
            if m:
                out[int(h)] = m
        return out

    return load


# ---------------------------------------------------------------- sanity checks

def build_trees(chains_by_hadith: dict[int, list[list[int]]], occurrences: pd.DataFrame
                ) -> dict[str, tree.Tree]:
    hids = occurrences.groupby("group_id").hadith_id.agg(lambda s: sorted(set(s)))
    return {g: tree.merge_tree([c for h in hs for c in chains_by_hadith.get(int(h), [])])
            for g, hs in hids.items()}


def _dated(dates: pd.DataFrame | None) -> tuple[dict, dict]:
    """rawi_id -> death_lo / death_hi for narrators with a usable (not prior-only) interval."""
    if dates is None or dates.empty:
        return {}, {}
    d = dates.dropna(subset=["death_lo", "death_hi"])
    if "method" in d:
        d = d[d["method"] != "prior_only"]
    return dict(zip(d.rawi_id, d.death_lo)), dict(zip(d.rawi_id, d.death_hi))


def sanity_checks(trees: dict[str, tree.Tree], chains: pd.DataFrame,
                  dropped: pd.DataFrame | None = None, dates: pd.DataFrame | None = None
                  ) -> dict:
    """Tree sanity per root component.

    * compilers (chain terminals) without children in their component;
    * roots without a parent in the GROUP graph (a root that another chain of the group places
      below some narrator, e.g. Companion A <- Companion B, counts as having a parent);
    * root earliest (spec 3.6): the root's inferred death_lo <= the death_hi of every dated
      terminal of its component; components with an undated root or no dated terminal other
      than the root are skipped (prior-only intervals count as undated);
    * chain counts and dropped (negative-cycle) links.
    """
    lo, hi = _dated(dates)
    st: Counter = Counter()
    for t in trees.values():
        if not t.roots:
            st["trees_empty"] += 1
            continue
        st["trees"] += 1
        has_parent = {c for cs in t.children.values() for c in cs}
        for r in t.roots:
            comp = t.component(r)
            st["components"] += 1
            st["compilers"] += len(comp.terminals)
            st["compilers_nonleaf"] += sum(1 for n in comp.terminals if comp.children.get(n))
            st["roots_with_parent"] += r in has_parent
            term_hi = [hi[n] for n in comp.terminals if n != r and n in hi]
            if r in lo and term_hi:
                st["root_date_checked"] += 1
                st["root_date_ok"] += lo[r] <= min(term_hi)
    keys = chains[["hadith_id", "chain_no"]].drop_duplicates()
    unjoined = chains.loc[chains.unjoined, ["hadith_id", "chain_no"]].drop_duplicates()
    comp_n, comp_ = st["compilers"], st["components"]
    return {
        "n_trees": st["trees"], "n_trees_empty": st["trees_empty"], "n_components": comp_,
        "n_compilers": comp_n, "n_compilers_nonleaf": st["compilers_nonleaf"],
        "compiler_leaf_rate": (1 - st["compilers_nonleaf"] / comp_n) if comp_n else None,
        "n_roots_with_parent": st["roots_with_parent"],
        "root_no_parent_rate": (1 - st["roots_with_parent"] / comp_) if comp_ else None,
        "n_root_date_checked": st["root_date_checked"],
        "root_earliest_rate": (st["root_date_ok"] / st["root_date_checked"]
                               if st["root_date_checked"] else None),
        "n_chains": int(len(keys)), "n_chains_unjoined": int(len(unjoined)),
        "n_hadith_with_chain": int(keys.hadith_id.nunique()),
        "n_dropped_links": None if dropped is None else int(len(dropped)),
    }


def coverage(tables: dict[str, pd.DataFrame], chains: pd.DataFrame) -> dict:
    occ, rep, nar, ed = (tables[k] for k in ("occurrences", "report_dates", "narrators", "edits"))
    g = tables["groups"]
    occ_h = set(occ.hadith_id.astype(int))
    with_chain = set(chains.loc[~chains.unjoined, "hadith_id"].astype(int))
    per_group = rep.groupby("group_id")
    out = {
        "n_groups": int(len(g)),
        "groups_complete_rate": float(g.complete.mean()) if len(g) else None,
        "occurrences_with_chain_rate": (len(occ_h & with_chain) / len(occ_h)) if occ_h else None,
        "groups_with_chains_rate": (float((per_group.n_chains.max() > 0).mean())
                                    if len(rep) else None),
    }
    for k in K_CL:
        has = per_group[f"cl_k{k}_id"].agg(lambda s: s.notna().any())
        dated = per_group[f"cl_k{k}_date_lo"].agg(lambda s: s.notna().any())
        out[f"groups_cl_k{k}_rate"] = float(has.mean()) if len(has) else None
        out[f"groups_cl_k{k}_dated_rate"] = float(dated.mean()) if len(dated) else None
    out["n_narrators"] = int(len(nar))
    out |= {f"narrators_method_{m}": int(c) for m, c in nar["method"].value_counts().items()}
    out["n_edits"] = int(len(ed))
    out |= {f"edits_status_{s}": int((ed.status == s).sum()) for s in edits.STATUSES}
    out["edits_rated_rate"] = float(ed.status.isin(edits.RATED).mean()) if len(ed) else None
    return out


# ---------------------------------------------------------------- release

def flatten(d: dict, prefix: str = "", skip=("per_fold", "seconds")) -> dict:
    out: dict = {}
    for k, v in d.items():
        if k in skip:
            continue
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out |= flatten(v, f"{key}_", skip)
        elif isinstance(v, (list, tuple)):
            continue
        else:
            out[key] = v
    return out


def _max_str(x) -> int:
    if isinstance(x, str):
        return len(x)
    if isinstance(x, (list, tuple, np.ndarray)):
        return max((len(v) for v in x if isinstance(v, str)), default=0)
    return 0


def check_strings(df: pd.DataFrame, label: str, max_len: int = MAX_STR_LEN) -> None:
    """Reject any string cell, or string item of a list cell, longer than max_len (text leaking
    under another name)."""
    for c in df.columns:
        s = df[c]
        if s.dtype == object or pd.api.types.is_string_dtype(s):
            ln = s.map(_max_str)
            if len(ln) and ln.max() > max_len:
                raise ValueError(f"{label}.{c}: string cell longer than {max_len} chars")


def _select(df: pd.DataFrame, cols: list[str] | None, label: str) -> pd.DataFrame:
    if cols is None:
        return df
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label}: missing columns {missing}")
    return df[cols]


def narrators_table(rawi: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    base = rawi[["rawi_id", "generation_num", "death_year", "death_kind", "birth_year",
                 "birth_kind"]]
    iv = dates[["rawi_id", "death_lo", "death_hi", "death_mode", "birth_lo", "birth_hi", "support",
                "method"]]
    out = base.merge(iv, on="rawi_id", how="outer").sort_values("rawi_id", ignore_index=True)
    return out[NARRATOR_COLS]


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def render_card(template: str, ctx: dict) -> str:
    """Fill ``{{key}}`` placeholders; a key absent from ctx renders as n/a (logged)."""
    def sub(m):
        k = m.group(1)
        if k not in ctx:
            log.warning("card placeholder %s has no value", k)
        return _fmt(ctx.get(k))
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def _configs_yaml(names: list[str]) -> str:
    return "\n".join(f"- config_name: {n}\n  data_files:\n  - split: train\n"
                     f"    path: data/{n}.parquet" for n in names)


def _paths(data_dir, overrides: dict | None) -> dict[str, Path]:
    p = {k: Path(data_dir) / v for k, v in INPUTS.items()}
    for k, v in (overrides or {}).items():
        if k not in INPUTS:
            raise ValueError(f"unknown input {k!r}; known: {sorted(INPUTS)}")
        p[k] = Path(v)
    return p


def guard_out(out: str | Path, data_dir: str | Path, inputs: Iterable[Path] = ()) -> Path:
    """Refuse an output folder whose deletion could destroy data: data_dir or an ancestor, the
    repo root or the cwd or an ancestor of them, a folder holding any input, or an existing
    non-empty folder that is not a previous release (no MANIFEST.json)."""
    o = Path(out).resolve()
    for name, q in [("data dir", Path(data_dir)), ("repo root", REPO_ROOT), ("cwd", Path.cwd()),
                    *(("input", Path(i)) for i in inputs)]:
        q = q.resolve()
        if q == o or q.is_relative_to(o):
            raise ValueError(f"refusing --out {out}: it is or contains the {name} {q}")
    if o.exists() and (not o.is_dir() or (any(o.iterdir()) and not (o / "MANIFEST.json").exists())):
        raise ValueError(f"refusing --out {out}: exists, non-empty and not a release folder")
    return o


def build_release(data_dir: str | Path = "data", out: str | Path = "release_hf",
                  inputs: dict | None = None, matns=None, align_sample: int = ALIGN_SAMPLE,
                  seed: int = 0, card: str | Path = CARD) -> Manifest:
    """Write the release folder; returns the manifest (config -> rows, columns)."""
    p = _paths(data_dir, inputs)
    out = Path(out)
    guard_out(out, data_dir, p.values())

    def read(k, cols=None):
        if not p[k].exists():
            raise FileNotFoundError(f"release input {k}: {p[k]}")
        return pd.read_parquet(p[k], columns=cols)

    tables: dict[str, pd.DataFrame] = {
        "narrators": narrators_table(read("rawi"), read("dates"))}
    for name, (key, cols) in _TABLES.items():
        tables[name] = _select(read(key), cols, name)
    for name, (key, cols) in _OPTIONAL.items():
        if p[key].exists():
            tables[name] = _select(read(key), cols, name)
        else:
            log.warning("optional config %s skipped: %s missing", name, p[key])

    chains = tables["chains"]
    trees = build_trees(tree.load_chains(p["chains"]), tables["occurrences"])
    sanity = sanity_checks(trees, chains, tables.get("dropped_links"), read("dates"))
    cov = coverage(tables, chains)
    if p["text"].exists() and p["segments"].exists():
        txt = read("text")
        texts = dict(zip(txt["hash"], txt["text"]))
        del txt
        align = alignment_check(read("segments"), texts, matns if matns is not None else {},
                                sample=align_sample, seed=seed)
        del texts
    else:
        log.warning("no local text store at %s: alignment check skipped", p["text"])
        align = {"agreement": None}
    dating_m = json.loads(p["checks_dating"].read_text()) if p["checks_dating"].exists() else {}
    checks = {"release_version": VERSION, **flatten(align, "alignment_"),
              **flatten(sanity, "sanity_"), **flatten(cov, "coverage_"),
              **flatten(dating_m, "dating_")}
    tables["checks"] = pd.DataFrame([checks])

    if out.exists():  # stale files must never ride along with an upload (guarded above)
        guard_out(out, data_dir, p.values())
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    manifest: Manifest = {}
    for name, df in tables.items():
        check_columns(df, name)
        check_strings(df, name)
        df.to_parquet(out / "data" / f"{name}.parquet", index=False)
        manifest[name] = {"rows": int(len(df)), "columns": list(df.columns)}
    (out / "checks.json").write_text(json.dumps(checks, indent=2, ensure_ascii=False))
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    ctx = dict(checks) | {f"rows_{n}": m["rows"] for n, m in manifest.items()}
    ctx["configs_yaml"] = _configs_yaml(list(manifest))
    ctx["version"] = VERSION
    (out / "README.md").write_text(render_card(Path(card).read_text(encoding="utf-8"), ctx),
                                   encoding="utf-8")
    verify_release(out)
    return manifest


def verify_release(out: str | Path) -> list[str]:
    """Only README.md, checks.json, MANIFEST.json and data/<known config>.parquet; every parquet
    passes the denylist and the string-length guard. Returns the relative file list."""
    out = Path(out)
    files = sorted(str(f.relative_to(out)) for f in out.rglob("*") if f.is_file())
    for f in files:
        if f not in RELEASE_FILES:
            raise ValueError(f"unexpected file in release: {f}")
        if not f.endswith(".parquet"):
            continue
        df = pd.read_parquet(out / f)
        check_columns(df, f)
        check_strings(df, f)
    missing = [c for c in REQUIRED_CONFIGS if f"data/{c}.parquet" not in files]
    if missing or "README.md" not in files:
        raise ValueError(f"release incomplete: missing {missing or 'README.md'}")
    return files


# ---------------------------------------------------------------- push

def read_token(env_file: str | Path = ENV_FILE) -> str | None:
    """HF_TOKEN from a KEY=VALUE env file; None when the file or key is absent."""
    path = Path(env_file).expanduser()
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.strip().removeprefix("export ").strip() == "HF_TOKEN":
            return v.strip().strip("'\"") or None
    return None


def push(out: str | Path, repo_id: str = REPO_ID, token: str | None = None,
         private: bool = False) -> str:
    """Create the dataset repo if needed and upload the verified release folder."""
    from huggingface_hub import HfApi

    verify_release(out)
    out = Path(out)
    cj = out / "checks.json"
    checks = json.loads(cj.read_text()) if cj.exists() else {}
    null = [k for k in PUSH_REQUIRED_CHECKS if checks.get(k) is None]
    if null:
        raise ValueError(f"refusing push: checks {null} are null")
    if "n/a" in (out / "README.md").read_text(encoding="utf-8"):
        raise ValueError("refusing push: README.md has unfilled values (n/a)")
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True, private=private)
    # files of the previous version that this one no longer has are removed from the repo
    api.upload_folder(repo_id=repo_id, folder_path=str(out), repo_type="dataset",
                      commit_message=f"isnad-chrono {VERSION}",
                      delete_patterns=["data/*.parquet", "*.json", "README.md"])
    return f"https://huggingface.co/datasets/{repo_id}"
