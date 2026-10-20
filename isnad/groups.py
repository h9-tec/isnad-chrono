"""Takhrij groups, word-level variant alignment and shawahid from the cached hadith pages.

Text never leaves the local text table: ``segments.parquet`` carries only hashes.
"""

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from isnad import pageprops
from isnad.build import _PARSE_ERRORS, _pages, read_page
from isnad.dates import _norm

log = logging.getLogger(__name__)
_WS = re.compile(r"\s+")


def hash_text(s: str) -> str:
    return hashlib.sha256(_WS.sub(" ", _norm(s)).strip().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Segment:
    seg_no: int
    kind: str  # "base" | "substitution"
    base_hash: str | None
    variant_hash: str | None
    carrier_hadith_ids: list[int]
    base_text: str | None = field(default=None, repr=False)
    variant_text: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class GroupRecord:
    group_id: str
    n_entries: int
    n_chains: int
    books: list[str]
    occurrences: list[tuple[int, str, str]]  # (hadith_id, book_slug, numbering)
    segments: list[Segment]
    shawahid: list[tuple[int | None, list[int]]]  # (companion_rawi_id, hadith_ids)
    shawahid_names: list[str | None] = field(default_factory=list)


def _segments(variants) -> list[Segment]:
    out: list[Segment] = []
    base_text = None
    for raw in (variants or {}).get("segments") or []:
        kind = raw.get("kind")
        if kind == "base":
            base_text = raw.get("text") or ""
            out.append(Segment(len(out), "base", hash_text(base_text), None, [], base_text, None))
        elif kind == "substitution":
            vt = raw.get("surface_text") or ""
            out.append(Segment(
                len(out), "substitution",
                hash_text(base_text) if base_text is not None else None, hash_text(vt),
                [int(h) for h in raw.get("hids") or []], base_text, vt))
    return out


def parse_group(h: dict, name_index=None) -> GroupRecord | None:
    """Parse ``props["hadith"]``; None when the page has no takhrij group."""
    summ = h.get("takhrij_isnad_summary") or {}
    gid = summ.get("group_slug")
    if not gid:
        return None
    books, occs = [], []
    for src in (h.get("takhrij") or {}).get("sources") or []:
        slug = f"b-{src['book_id']}"
        books.append(slug)
        for o in src.get("occurrences") or []:
            occs.append((int(o["entry_id"]), slug, str(o.get("hadith_num") or "").strip()))
    sh, names = [], []
    for g in (h.get("shawahid") or {}).get("groups") or []:
        ids = [int(e["entry_id"]) for b in g.get("books") or [] for e in b.get("entries") or []]
        name = g.get("narrator")
        rid = None
        if name and name_index is not None:
            r = name_index.resolve(name)
            rid = r.rawi_id if not r.ambiguous else None
        sh.append((rid, ids))
        names.append(name)
    return GroupRecord(gid, int(summ.get("entry_count") or 0), int(summ.get("chain_count") or 0),
                       books, occs, _segments(h.get("variants")), sh, names)


def _sig(g: GroupRecord):
    return [(s.kind, s.base_hash, s.variant_hash, s.carrier_hadith_ids) for s in g.segments]


def run_groups(cache_root, out_dir, limit: int | None = None, rawi_path=None) -> dict:
    out_dir = Path(out_dir)
    paths = _pages(cache_root, "hadith")
    cached = {int(p.name.split(".")[0]) for p in paths if p.name.split(".")[0].isdigit()}
    if limit is not None:
        paths = paths[:limit]
    index = None
    rawi_path = rawi_path or "data/rawi.parquet"
    if Path(rawi_path).exists():
        from isnad.gold import NameIndex
        index = NameIndex.from_rawi(rawi_path)
    stats: Counter = Counter()
    groups: dict[str, GroupRecord] = {}
    for p in paths:
        stats["pages"] += 1
        try:
            rec = parse_group(pageprops.extract(read_page(p))["hadith"], index)
        except _PARSE_ERRORS as e:
            stats["errors"] += 1
            log.warning("%s: %s", p, e)
            continue
        if rec is None:
            stats["no group"] += 1
            continue
        old = groups.get(rec.group_id)
        if old is None:
            groups[rec.group_id] = rec
        elif _sig(old) != _sig(rec):
            stats["segment discrepancies"] += 1
            if len(rec.segments) > len(old.segments):
                groups[rec.group_id] = rec
    g_rows, o_rows, s_rows, w_rows, text = [], [], [], [], {}
    for gid, g in sorted(groups.items()):
        complete = all(hid in cached for hid, _, _ in g.occurrences)
        stats["complete groups"] += complete
        g_rows.append(dict(group_id=gid, n_entries=g.n_entries, n_chains=g.n_chains,
                           books=g.books, n_occurrences=len(g.occurrences), complete=complete))
        o_rows += [dict(group_id=gid, hadith_id=h, book_slug=b, numbering=n)
                   for h, b, n in g.occurrences]
        for s in g.segments:
            s_rows.append(dict(group_id=gid, seg_no=s.seg_no, kind=s.kind, base_hash=s.base_hash,
                               variant_hash=s.variant_hash, carrier_hadith_ids=s.carrier_hadith_ids))
            for hh, t in ((s.base_hash, s.base_text), (s.variant_hash, s.variant_text)):
                if hh and t is not None:
                    text[hh] = _WS.sub(" ", t).strip()
        for (rid, ids), name in zip(g.shawahid, g.shawahid_names):
            w_rows.append(dict(group_id=gid, companion_rawi_id=rid, companion_name=name,
                               hadith_ids=ids))
            stats["shawahid resolved" if rid is not None else "shawahid unresolved"] += 1
    cols = {
        "groups": ["group_id", "n_entries", "n_chains", "books", "n_occurrences", "complete"],
        "occurrences": ["group_id", "hadith_id", "book_slug", "numbering"],
        "segments": ["group_id", "seg_no", "kind", "base_hash", "variant_hash",
                     "carrier_hadith_ids"],
        "shawahid": ["group_id", "companion_rawi_id", "companion_name", "hadith_ids"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("groups", g_rows), ("occurrences", o_rows), ("segments", s_rows),
                       ("shawahid", w_rows)):
        df = pd.DataFrame(rows, columns=cols[name])
        if name == "shawahid":
            df["companion_rawi_id"] = df["companion_rawi_id"].astype("Int64")
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
    (out_dir / "text").mkdir(exist_ok=True)
    pd.DataFrame({"hash": list(text), "text": list(text.values())}).to_parquet(
        out_dir / "text" / "segments_text.parquet", index=False)
    stats["groups"] = len(groups)
    stats["segments"] = len(s_rows)
    stats["occurrences"] = len(o_rows)
    for k in ("pages", "no group", "errors", "groups", "complete groups", "occurrences",
              "segments", "segment discrepancies", "shawahid resolved", "shawahid unresolved"):
        print(f"{k}: {stats[k]}")
    return dict(stats)
