"""Static-site export: JSON tables for the GitHub Pages site (derived numbers and names only).

``run_export_site`` writes ``meta.json``, ``narrators.json`` and ``search.json`` under ``out``.
Every file goes through ``write_json``, which rejects text-bearing keys (``SITE_DENYLIST``).
"""

import datetime
import json
import re
from pathlib import Path

import pandas as pd

from isnad import export_hf

SITE_DENYLIST = re.compile(r"^(text|matn|statement|lineage|narrative_years|name_forms)$|_text$")

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
    slug = BOOK_ALIASES.get(book.lower(), BOOK_ALIASES.get(book, book))
    num = "".join(str(numbering).translate(_DIGITS).split())
    return f"{slug}:{num}"


def _int(v):
    return None if v is None or pd.isna(v) else int(v)


def _str(v):
    return None if v is None or pd.isna(v) else str(v)


def meta_table(d: Path, checks: dict | None = None) -> dict:
    d = Path(d)
    occ = pd.read_parquet(d / "occurrences.parquet", columns=["hadith_id", "book_slug"])
    had = pd.read_parquet(d / "hadith.parquet", columns=["book_slug", "book_title"])
    titles = had.dropna().drop_duplicates("book_slug").set_index("book_slug")["book_title"]
    counts = occ.groupby("book_slug")["hadith_id"].nunique()
    books = [{"slug": s, "title": str(titles.get(s, s)), "n_hadith_cached": int(n)}
             for s, n in sorted(counts.items(), key=lambda kv: (len(kv[0]), kv[0]))]
    return {"version": export_hf.VERSION, "built": datetime.date.today().isoformat(),
            "checks": checks or {}, "books": books}


def narrators_table(d: Path) -> list[dict]:
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
            "n_chains": int(n)})
    return rows


def search_table(d: Path) -> dict:
    d = Path(d)
    occ = pd.read_parquet(d / "occurrences.parquet")
    had = pd.read_parquet(d / "hadith.parquet", columns=["book_slug", "book_title"])
    titles = had.dropna().drop_duplicates("book_slug").set_index("book_slug")["book_title"]
    books = {s: str(titles.get(s, s)) for s in sorted(occ["book_slug"].unique())}
    numbering = {search_key(s, n): g for s, n, g in
                 zip(occ["book_slug"], occ["numbering"], occ["group_id"])}
    hadith = {str(int(h)): g for h, g in zip(occ["hadith_id"], occ["group_id"])}
    return {"books": books, "numbering": numbering, "hadith": hadith}


def run_export_site(data_dir: str, out: str, checks_path: str | None = None) -> dict:
    d, o = Path(data_dir), Path(out)
    checks = {}
    if checks_path and Path(checks_path).exists():
        checks = json.loads(Path(checks_path).read_text(encoding="utf-8"))
    man = {}
    man["meta.json"] = write_json(o / "meta.json", meta_table(d, checks))
    man["narrators.json"] = write_json(o / "narrators.json", narrators_table(d))
    man["search.json"] = write_json(o / "search.json", search_table(d))
    return man
