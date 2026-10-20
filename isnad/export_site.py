"""Static-site export: JSON tables for the GitHub Pages site (derived numbers and names only).

``run_export_site`` writes ``meta.json``, ``narrators.json``, ``search.json`` (+ shards),
``groups/<NN>/<group_id>.json``, ``narrator/<NN>/<rawi_id>.json`` and ``atlas.json`` under ``out``.
Every file goes through ``write_json``, which rejects text-bearing keys (``SITE_DENYLIST``).
"""

import datetime
import gzip
import json
import logging
import re
import zlib
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pandas as pd

from isnad import export_hf
from isnad.constants import K_CL
from isnad.edits import RATED, STATUSES
from isnad.parse_hadith import parse_hadith
from isnad.tree import clean_chain

log = logging.getLogger(__name__)

SITE_DENYLIST = re.compile(r"^(text|matn|statement|lineage|narrative_years|name_forms)$|_text$", re.I)

BOOK_ALIASES = {
    "bukhari": "b-1", "البخاري": "b-1", "صحيح البخاري": "b-1",
    "muslim": "b-2", "مسلم": "b-2",
    "abudawud": "b-3", "abu dawud": "b-3", "أبو داود": "b-3", "أبي داود": "b-3",
    "tirmidhi": "b-4", "الترمذي": "b-4",
    "nasai": "b-5", "النسائي": "b-5",
    "ibnmajah": "b-6", "ibn majah": "b-6", "ابن ماجه": "b-6",
}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def check_keys(obj, path: str = "") -> None:
    """Raise ValueError naming the first denylisted key anywhere in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SITE_DENYLIST.search(str(k)):
                raise ValueError(f"denylisted key {k!r} at {path or '/'}")
            check_keys(v, f"{path}/{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            check_keys(v, f"{path}[{i}]")


def write_json(path: Path, obj) -> int:
    """Write compact UTF-8 JSON after the denylist check; return the bytes written."""
    check_keys(obj)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def search_key(book_alias: str, numbering: str) -> str:
    """``"<slug>:<numbering>"`` with ASCII digits, collapsed whitespace and resolved alias."""
    book = " ".join(str(book_alias).translate(_DIGITS).split())
    slug = BOOK_ALIASES.get(book.lower(), BOOK_ALIASES.get(book, book.lower()))
    num = "".join(str(numbering).translate(_DIGITS).split())
    return f"{slug}:{num}"


PLACEHOLDER_IDS = (1, 2)
PLACEHOLDER_NAME = "راوٍ غير مسمّى"
NARRATOR_COLS = ["id", "name", "kunya", "gen", "dy", "dk", "by", "bk", "dlo", "dhi", "blo", "bhi",
                 "method", "support", "n_chains", "placeholder"]


def _int(v):
    return None if v is None or pd.isna(v) else int(v)


def _str(v):
    return None if v is None or pd.isna(v) else str(v)


def _page_title(d: Path, hadith_id: int):
    base = Path(d) / "raw" / "html" / "hadith"
    bad = (OSError, EOFError, zlib.error, UnicodeDecodeError)
    try:
        with gzip.open(base / f"{hadith_id}.html.gz", "rt", encoding="utf-8") as f:
            html = f.read()
    except bad:
        try:
            html = (base / f"{hadith_id}.html").read_text(encoding="utf-8")
        except bad:
            return None
    try:
        return parse_hadith(html).book_title or None
    except Exception:
        return None


def _titles(d: Path, occ: pd.DataFrame) -> dict:
    had = pd.read_parquet(Path(d) / "hadith.parquet", columns=["book_slug", "book_title"])
    titles = had.dropna().drop_duplicates("book_slug").set_index("book_slug")["book_title"].to_dict()
    ids = occ.drop_duplicates(["book_slug", "hadith_id"]).groupby("book_slug")["hadith_id"]
    out = {}
    for slug, hs in sorted(ids):
        if slug in titles:
            out[slug] = str(titles[slug])
            continue
        out[slug] = slug
        for h in hs:  # first occurrence whose cached page exists and parses
            t = _page_title(d, int(h))
            if t:
                out[slug] = t
                break
    return out


def _n_pages(d: Path) -> int:
    base = Path(d) / "raw" / "html" / "hadith"
    if not base.is_dir():
        return 0
    return sum(1 for f in base.iterdir() if f.name.endswith((".html.gz", ".html")))


def meta_table(d: Path, checks: dict | None = None) -> dict:
    d = Path(d)
    occ = pd.read_parquet(d / "occurrences.parquet", columns=["hadith_id", "book_slug"])
    titles = _titles(d, occ)
    counts = occ.groupby("book_slug")["hadith_id"].nunique()
    books = [{"slug": s, "title": titles[s], "n_hadith_cached": int(n)}
             for s, n in sorted(counts.items(), key=lambda kv: (len(kv[0]), kv[0]))]
    return {"version": export_hf.VERSION, "built": datetime.date.today().isoformat(),
            "n_hadith_pages_cached": _n_pages(d), "checks": checks or {}, "books": books}


def narrators_table(d: Path) -> list[dict]:
    """One dict per narrator with at least one chain (keys: NARRATOR_COLS)."""
    d = Path(d)
    ch = pd.read_parquet(d / "chains.parquet", columns=["hadith_id", "chain_no", "rawi_id"])
    nch = (ch.drop_duplicates(["hadith_id", "chain_no", "rawi_id"]).groupby("rawi_id").size())
    rawi = pd.read_parquet(d / "rawi.parquet").drop_duplicates("rawi_id").set_index("rawi_id")
    dates = (pd.read_parquet(d / "rawi_dates_inferred.parquet")
             .drop_duplicates("rawi_id").set_index("rawi_id"))
    rows = []
    for rid, n in sorted(nch.items()):
        r = rawi.loc[rid] if rid in rawi.index else None
        t = dates.loc[rid] if rid in dates.index else None
        name = None
        if r is not None:
            name = _str(r["abbrev"]) or _str(r["name"])
        ph = int(rid) in PLACEHOLDER_IDS
        if ph:
            name = PLACEHOLDER_NAME
        rows.append({
            "id": int(rid), "name": name or f"p-{rid}",
            "kunya": _str(r["kunya"]) if r is not None else None,
            "gen": _int(r["generation_num"]) if r is not None else None,
            "dy": _int(r["death_year"]) if r is not None else None,
            "dk": _str(r["death_kind"]) if r is not None else None,
            "by": _int(r["birth_year"]) if r is not None else None,
            "bk": _str(r["birth_kind"]) if r is not None else None,
            "dlo": _int(t["death_lo"]) if t is not None else None,
            "dhi": _int(t["death_hi"]) if t is not None else None,
            "blo": _int(t["birth_lo"]) if t is not None else None,
            "bhi": _int(t["birth_hi"]) if t is not None else None,
            "method": _str(t["method"]) if t is not None else None,
            "support": _int(t["support"]) if t is not None else None,
            "n_chains": int(n), "placeholder": ph})
    return rows


def _sorted(groups) -> list:
    return sorted(groups)


def search_tables(d: Path) -> dict:
    """{path: obj}: search.json plus lazy shards search/n/<slug>.json and search/h/<NN>.json."""
    d = Path(d)
    occ = pd.read_parquet(d / "occurrences.parquet")
    titles = _titles(d, occ)
    out = {"search.json": {"books": titles, "aliases": dict(BOOK_ALIASES)}}
    nums: dict[str, dict[str, set]] = {}
    hids: dict[str, dict[str, set]] = {}
    for g, h, s, n in zip(occ["group_id"], occ["hadith_id"], occ["book_slug"], occ["numbering"]):
        gn = str(g)
        hids.setdefault(f"{int(h) % 100:02d}", {}).setdefault(str(int(h)), set()).add(gn)
        if n is None or pd.isna(n):
            continue
        nums.setdefault(s, {}).setdefault(search_key(s, n).split(":", 1)[1], set()).add(gn)
    for s, m in nums.items():
        out[f"search/n/{s}.json"] = {"numbering": {k: _sorted(v) for k, v in m.items()}}
    for sh, m in hids.items():
        out[f"search/h/{sh}.json"] = {k: _sorted(v) for k, v in m.items()}
    return out


def _columnar(rows: list[dict]) -> dict:
    return {"cols": NARRATOR_COLS, "rows": [[r[c] for c in NARRATOR_COLS] for r in rows]}


# ---- groups, narrator details, atlas ---------------------------------------------------------

BOARD_N = 50
TOP_LINKS = 20
EDIT_STATUSES = ("attributed", "ambiguous", "partial", "cross_root", "no_chain", "no_common_node")
assert set(EDIT_STATUSES) == set(STATUSES)


def _shard(n: int) -> str:
    return f"{int(n) % 100:02d}"


def group_path(group_id: str) -> Path:
    """``groups/<last two digits of N>/<group_id>.json`` for ``tk-N`` / ``tg-N``."""
    return Path("groups") / _shard(str(group_id).rsplit("-", 1)[1]) / f"{group_id}.json"


def narrator_path(rawi_id: int) -> Path:
    return Path("narrator") / _shard(rawi_id) / f"{int(rawi_id)}.json"


def _gid_key(g: str):
    pre, _, n = str(g).rpartition("-")
    return (pre, int(n) if n.isdigit() else 0, str(g))


def _rate(v):
    return None if v is None or pd.isna(v) else round(float(v), 3)


def _bool(v):
    return None if v is None or pd.isna(v) else bool(v)


def _read(d: Path, name: str, columns=None) -> pd.DataFrame | None:
    p = d / f"{name}.parquet"
    if not p.exists():
        log.warning("export-site: %s missing, treated as empty", p)
        return None
    return pd.read_parquet(p, columns=columns)


def _by_group(df: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    return {str(g): x for g, x in df.groupby("group_id", sort=False)}


@dataclass
class SiteContext:
    """Every input table loaded once, indexed by group / hadith / narrator."""
    data_dir: str | Path
    occ: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self):
        d = self.d = Path(self.data_dir)
        self.occ = pd.read_parquet(d / "occurrences.parquet",
                                   columns=["group_id", "hadith_id", "book_slug"])
        g = _read(d, "groups", ["group_id", "complete"])
        self.complete = {} if g is None else {str(k): _bool(v) for k, v in zip(g.group_id, g.complete)}
        self.nodes = _by_group(_read(d, "tree_nodes"))
        self.reports = _by_group(_read(d, "report_dates"))
        self.edits = _by_group(_read(d, "edits", ["group_id", "seg_no", "introduced_by_rawi_id",
                                                   "edit_type", "status"]))
        rates = _read(d, "edit_rates")
        self.rates = rates if rates is not None else pd.DataFrame()
        sh = _read(d, "shawahid_companions", ["group_id", "companion_rawi_id"])
        self.shawahid: dict[str, list[int]] = {}
        if sh is not None:
            sh = sh.dropna(subset=["companion_rawi_id"])
            for gid, x in sh.groupby("group_id", sort=False):
                self.shawahid[str(gid)] = sorted({int(c) for c in x.companion_rawi_id})
        dr = _read(d, "dropped_links", ["teacher_id", "student_id", "reason"])
        self.dropped: dict[int, list] = {}
        if dr is not None:
            for t, s, r in zip(dr.teacher_id, dr.student_id, dr.reason):
                self.dropped.setdefault(int(t), []).append([int(s), _str(r)])
                self.dropped.setdefault(int(s), []).append([int(t), _str(r)])
        self.books: dict[str, dict[str, set]] = {}
        for gid, h, slug in zip(self.occ.group_id, self.occ.hadith_id, self.occ.book_slug):
            self.books.setdefault(str(gid), {}).setdefault(str(slug), set()).add(int(h))
        self._load_chains()

    def _load_chains(self):
        """hadith_id -> [(cleaned chain, {rawi_id: term})] with the same filtering as
        ``tree.load_chains`` + ``tree.clean_chains``; plus global teacher/student counts."""
        c = pd.read_parquet(self.d / "chains.parquet",
                            columns=["hadith_id", "chain_no", "position", "rawi_id", "term",
                                     "unjoined"])
        self.chain_rawi = sorted({int(r) for r in c.rawi_id.unique()})
        bad = set(zip(c.hadith_id[c.unjoined], c.chain_no[c.unjoined]))
        c = c.sort_values(["hadith_id", "chain_no", "position"])
        self.hadith_chains: dict[int, list] = {}
        self.teachers: dict[int, Counter] = {}
        self.students: dict[int, Counter] = {}
        cur, ids, terms = None, [], []

        def flush():
            if cur is None or cur in bad:
                return
            ch, truncated = clean_chain(ids)
            if not ch or (truncated and len(ch) < 2):
                return
            term_of: dict[int, str | None] = {}
            for r, t in zip(ids, terms):
                term_of.setdefault(int(r), t)  # first row of the narrator (consecutive dups)
            self.hadith_chains.setdefault(int(cur[0]), []).append((ch, term_of))
            for a, b in zip(ch, ch[1:]):
                self.students.setdefault(a, Counter())[b] += 1
                self.teachers.setdefault(b, Counter())[a] += 1

        for h, n, r, t in zip(c.hadith_id, c.chain_no, c.rawi_id, c.term):
            key = (h, n)
            if key != cur:
                flush()
                cur, ids, terms = key, [], []
            ids.append(int(r))
            terms.append(None if t is None or pd.isna(t) else str(t))
        flush()

    @cached_property
    def narrators(self) -> list[dict]:
        return narrators_table(self.d)

    @cached_property
    def group_ids(self) -> list[str]:
        gs = set(self.books) | set(self.complete) | set(self.reports)
        return sorted(gs, key=_gid_key)

    @cached_property
    def cl_groups(self) -> dict[int, list]:
        """rawi_id -> [[group_id, lo, hi]…] for every group where it is a k2 CL (any root)."""
        out: dict[int, dict] = {}
        for g, rep in self.reports.items():
            for cid, lo, hi in zip(rep.cl_k2_id, rep.cl_k2_date_lo, rep.cl_k2_date_hi):
                if pd.notna(cid):
                    out.setdefault(int(cid), {}).setdefault(g, [g, _int(lo), _int(hi)])
        return {r: sorted(v.values(), key=lambda x: _gid_key(x[0])) for r, v in out.items()}

    def group_chains(self, group_id: str) -> list:
        hids = sorted(h for hs in self.books.get(group_id, {}).values() for h in hs)
        return [x for h in hids for x in self.hadith_chains.get(h, [])]

    def chosen_cl(self, group_id: str) -> dict:
        """{k: report row} for the group's CL under k: when several roots have one, the root
        carrying the most chains (ties: smaller root id)."""
        rep = self.reports.get(group_id)
        out = {}
        if rep is None:
            return out
        for k in K_CL:
            x = rep[rep[f"cl_k{k}_id"].notna()]
            if len(x):
                x = x.assign(_r=x.root_id.astype("int64")).sort_values(
                    ["n_chains", "_r"], ascending=[False, True])
                out[k] = x.iloc[0]
        return out


def _cl_obj(row, k: int) -> dict:
    return {"id": int(row[f"cl_k{k}_id"]), "lo": _int(row[f"cl_k{k}_date_lo"]),
            "hi": _int(row[f"cl_k{k}_date_hi"]), "method": _str(row[f"cl_k{k}_date_method"]),
            "all_chains": _bool(row[f"cl_k{k}_all_chains"])}


def group_json(group_id: str, ctx: SiteContext) -> dict:
    """The spec §3 group object. ``nodes`` / ``cl`` come from tree_nodes / report_dates, the
    chains and terms from the same cleaned chains the tree stage merged."""
    g = str(group_id)
    chs = ctx.group_chains(g)
    terms: dict[str, str] = {}
    for ch, term_of in chs:
        for a, b in zip(ch, ch[1:]):
            key = f"{a}-{b}"
            if key not in terms and term_of.get(a) is not None:
                terms[key] = term_of[a]
    nd = ctx.nodes.get(g)
    nodes = [] if nd is None else [
        {"id": int(r.rawi_id), "root": int(r.root_id), "depth": int(r.depth),
         "k": int(r.k_branches), "n_desc": int(r.n_descendant_chains),
         "cl2": bool(r.is_cl_k2), "cl3": bool(r.is_cl_k3),
         "pcl2": bool(r.is_pcl_k2), "pcl3": bool(r.is_pcl_k3)}
        for r in nd.sort_values(["root_id", "depth", "rawi_id"]).itertuples(index=False)]
    roots = sorted({ch[0] for ch, _ in chs})
    node_roots = {n["root"] for n in nodes}
    if node_roots != set(roots):
        log.warning("export-site: %s roots %s disagree with tree_nodes %s", g, roots,
                    sorted(node_roots))
    ed = ctx.edits.get(g)
    edits = {s: 0 for s in EDIT_STATUSES}
    by_node: dict[str, list] = {}
    if ed is not None:
        edits.update({str(s): int(n) for s, n in ed.status.value_counts().items()})
        rated = ed[ed.status.isin(RATED) & ed.introduced_by_rawi_id.notna()].sort_values("seg_no")
        for r in rated.itertuples(index=False):
            by_node.setdefault(str(int(r.introduced_by_rawi_id)), []).append(
                {"seg": int(r.seg_no), "type": str(r.edit_type), "status": str(r.status)})
    edits["by_node"] = by_node
    rep = ctx.reports.get(g)
    all_chained = None
    if rep is not None and len(rep):
        all_chained = _bool(rep.all_occurrences_have_chain.iloc[0])
    return {
        "id": g, "complete": ctx.complete.get(g), "all_chained": all_chained,
        "books": {s: sorted(hs) for s, hs in sorted(ctx.books.get(g, {}).items(),
                                                     key=lambda kv: _gid_key(kv[0]))},
        "chains": [list(ch) for ch, _ in chs], "roots": roots, "nodes": nodes,
        "cl": {f"k{k}": _cl_obj(row, k) for k, row in ctx.chosen_cl(g).items()},
        "edits": edits, "terms": terms, "shawahid": ctx.shawahid.get(g, [])}


def _top(counter: Counter | None, n: int) -> list:
    if not counter:
        return []
    return [[int(i), int(c)] for i, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def narrator_detail(rawi_id: int, ctx: SiteContext) -> dict:
    rid = int(rawi_id)
    return {"teachers": _top(ctx.teachers.get(rid), TOP_LINKS),
            "students": _top(ctx.students.get(rid), TOP_LINKS),
            "cl_groups": ctx.cl_groups.get(rid, []),
            "dropped": sorted(ctx.dropped.get(rid, []), key=lambda x: (x[0], x[1] or ""))}


def atlas_table(ctx: SiteContext) -> dict:
    hist: dict[str, Counter] = {"all": Counter()}
    earliest = []
    for g in ctx.group_ids:
        row = ctx.chosen_cl(g).get(2)
        if row is None or _str(row["cl_k2_date_method"]) == "prior_only":
            continue
        lo, hi = _int(row["cl_k2_date_lo"]), _int(row["cl_k2_date_hi"])
        if lo is None or hi is None:
            continue
        b = ((lo + hi) // 2) // 10 * 10
        hist["all"][b] += 1
        for slug in ctx.books.get(g, {}):
            hist.setdefault(slug, Counter())[b] += 1
        earliest.append([g, int(row["cl_k2_id"]), lo, hi])
    cl_hist = {s: [[int(b), int(n)] for b, n in sorted(c.items())]
               for s, c in sorted(hist.items(), key=lambda kv: (kv[0] != "all", _gid_key(kv[0])))}
    earliest.sort(key=lambda x: (x[3], x[2], _gid_key(x[0])))

    top_cls = Counter({r: len(v) for r, v in ctx.cl_groups.items()})
    narr = {r["id"]: r for r in ctx.narrators}
    conflicts = []
    rawi = pd.read_parquet(ctx.d / "rawi.parquet", columns=["rawi_id", "death_year", "death_kind"])
    dates = pd.read_parquet(ctx.d / "rawi_dates_inferred.parquet",
                            columns=["rawi_id", "death_lo", "death_hi"]).drop_duplicates("rawi_id")
    iv = {int(r): (_int(lo), _int(hi)) for r, lo, hi in zip(dates.rawi_id, dates.death_lo,
                                                            dates.death_hi)}
    for rid, dy, dk in zip(rawi.rawi_id, rawi.death_year, rawi.death_kind):
        lo, hi = iv.get(int(rid), (None, None))
        dy = _int(dy)
        if _str(dk) != "exact" or dy is None or lo is None or hi is None:
            continue
        dist = lo - dy if dy < lo else dy - hi if dy > hi else 0
        if dist > 0:
            conflicts.append((dist, int(rid), dy, lo, hi))
    conflicts = [[r, dy, lo, hi] for _, r, dy, lo, hi in
                 sorted(set(conflicts), key=lambda x: (-x[0], x[1]))[:BOARD_N]]

    n_att: Counter = Counter()
    for ed in ctx.edits.values():
        a = ed[(ed.status == "attributed") & ed.introduced_by_rawi_id.notna()]
        n_att.update(int(r) for r in a.introduced_by_rawi_id)
    top_editors = [[r, n, narr[r]["n_chains"] if r in narr else 0]
                   for r, n in _top(n_att, BOARD_N)]

    drift = [{c: (_rate(v) if c.startswith("rate") else _int(v)) for c, v in row.items()}
             for row in ctx.rates.to_dict("records")]
    return {"cl_hist": cl_hist, "drift": drift,
            "boards": {"top_cls": _top(top_cls, BOARD_N), "earliest": earliest[:BOARD_N],
                       "conflicts": conflicts, "top_editors": top_editors}}


def run_export_site(data_dir: str, out: str, checks_path: str | None = None) -> dict:
    d, o = Path(data_dir), Path(out)
    checks = {}
    if checks_path and Path(checks_path).exists():
        checks = json.loads(Path(checks_path).read_text(encoding="utf-8"))
    man = {}
    man["meta.json"] = write_json(o / "meta.json", meta_table(d, checks))
    man["narrators.json"] = write_json(o / "narrators.json", _columnar(narrators_table(d)))
    for rel, obj in search_tables(d).items():
        man[rel] = write_json(o / rel, obj)
    ctx = SiteContext(d)
    for g in ctx.group_ids:
        rel = group_path(g)
        man[rel.as_posix()] = write_json(o / rel, group_json(g, ctx))
    for rid in sorted(set(ctx.chain_rawi) | {r["id"] for r in ctx.narrators}):
        rel = narrator_path(rid)
        man[rel.as_posix()] = write_json(o / rel, narrator_detail(rid, ctx))
    man["atlas.json"] = write_json(o / "atlas.json", atlas_table(ctx))
    return man
