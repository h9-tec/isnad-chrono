"""Static-site export: JSON tables for the GitHub Pages site (derived numbers and names only).

``run_export_site`` writes ``meta.json``, ``narrators.json`` and ``search.json`` under ``out``.
Every file goes through ``write_json``, which rejects text-bearing keys (``SITE_DENYLIST``).
"""

import datetime
import gzip
import json
import re
from pathlib import Path

import pandas as pd

from isnad import export_hf
from isnad.parse_hadith import parse_hadith

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
    try:
        with gzip.open(base / f"{hadith_id}.html.gz", "rt", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        try:
            html = (base / f"{hadith_id}.html").read_text(encoding="utf-8")
        except OSError:
            return None
    try:
        return parse_hadith(html).book_title or None
    except Exception:
        return None


def _titles(d: Path, occ: pd.DataFrame) -> dict:
    had = pd.read_parquet(Path(d) / "hadith.parquet", columns=["book_slug", "book_title"])
    titles = had.dropna().drop_duplicates("book_slug").set_index("book_slug")["book_title"].to_dict()
    first = occ.drop_duplicates("book_slug").set_index("book_slug")["hadith_id"]
    out = {}
    for slug in sorted(first.index):
        out[slug] = str(titles[slug]) if slug in titles else (
            _page_title(d, int(first[slug])) or slug)
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


def _num(group_id: str):
    """tk-N -> N; any other id (the 538 tg-N cluster groups) is kept as its full string."""
    g = str(group_id)
    return int(g[3:]) if g.startswith("tk-") else g


def _sorted(groups) -> list:
    return sorted(groups, key=lambda g: (isinstance(g, str), g))


def search_tables(d: Path) -> dict:
    """{path: obj}: search.json plus lazy shards search/n/<slug>.json and search/h/<NN>.json."""
    d = Path(d)
    occ = pd.read_parquet(d / "occurrences.parquet")
    titles = _titles(d, occ)
    out = {"search.json": {"books": titles, "aliases": dict(BOOK_ALIASES)}}
    nums: dict[str, dict[str, set]] = {}
    hids: dict[str, dict[str, set]] = {}
    for g, h, s, n in zip(occ["group_id"], occ["hadith_id"], occ["book_slug"], occ["numbering"]):
        gn = _num(g)
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
    return man
