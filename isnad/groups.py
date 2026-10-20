"""Takhrij groups, word-level variant alignment and shawahid from the cached hadith pages.

Text never leaves the local text table: ``segments.parquet`` carries only hashes. A text that is
empty after normalisation gets hash None (no text-table entry): an empty substitution surface is a
deletion (variant_hash None), an empty or missing base an insertion (base_hash None).

The build streams: a group is written the first time it is seen and only its signature and
segment count are kept afterwards. Dedup rule: FIRST WINS. A later page of the same group
whose segments differ is counted as a discrepancy (and as "longer later" when it has more
segments) but never replaces the written group. Parquet outputs are written in chunks.
"""

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from isnad import pageprops
from isnad.build import _PARSE_ERRORS, _pages, read_page
from isnad.dates import _norm

log = logging.getLogger(__name__)
_WS = re.compile(r"\s+")


def hash_text(s: str) -> str:
    return hashlib.sha256(_WS.sub(" ", _norm(s)).strip().encode("utf-8")).hexdigest()[:16]


def hash_or_none(s: str | None) -> str | None:
    """hash_text, or None when the text is empty after normalisation (an insertion/deletion)."""
    if s is None or not _WS.sub(" ", _norm(s)).strip():
        return None
    return hash_text(s)


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
            out.append(Segment(len(out), "base", hash_or_none(base_text), None, [], base_text, None))
        elif kind == "substitution":
            vt = raw.get("surface_text") or ""
            out.append(Segment(
                len(out), "substitution",
                hash_or_none(base_text), hash_or_none(vt),
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


CHUNK = 100_000
_I = pa.list_(pa.int64())
SCHEMAS = {
    "groups": pa.schema([("group_id", pa.string()), ("n_entries", pa.int64()),
                         ("n_chains", pa.int64()), ("books", pa.list_(pa.string())),
                         ("n_occurrences", pa.int64()), ("complete", pa.bool_())]),
    "occurrences": pa.schema([("group_id", pa.string()), ("hadith_id", pa.int64()),
                              ("book_slug", pa.string()), ("numbering", pa.string())]),
    "segments": pa.schema([("group_id", pa.string()), ("seg_no", pa.int64()),
                           ("kind", pa.string()), ("base_hash", pa.string()),
                           ("variant_hash", pa.string()), ("carrier_hadith_ids", _I)]),
    "shawahid": pa.schema([("group_id", pa.string()), ("companion_rawi_id", pa.int64()),
                           ("companion_name", pa.string()), ("hadith_ids", _I)]),
    "text": pa.schema([("hash", pa.string()), ("text", pa.string())]),
}


class _Chunked:
    """Buffer dict rows and append them to a parquet file every CHUNK rows."""

    def __init__(self, path, schema, chunk=CHUNK):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.schema, self.chunk, self.rows = schema, chunk, []
        self.w = pq.ParquetWriter(path, schema)

    def add(self, row) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.chunk:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.w.write_table(pa.Table.from_pylist(self.rows, schema=self.schema))
            self.rows = []

    def close(self) -> None:
        self.flush()
        self.w.close()


def _sig(g: GroupRecord):
    return hashlib.sha256(repr([(s.kind, s.base_hash, s.variant_hash, s.carrier_hadith_ids)
                                for s in g.segments]).encode()).hexdigest()[:16]


class _Sink:
    """Streams groups to parquet; first record of a group wins."""

    def __init__(self, out_dir, cached, chunk=CHUNK):
        out_dir = Path(out_dir)
        self.cached, self.stats = cached, Counter()
        self.seen: dict[str, tuple[str, int]] = {}  # group_id -> (signature, n segments)
        self.text_seen: set[str] = set()
        self.w = {k: _Chunked(out_dir / (f"text/segments_text.parquet" if k == "text"
                                         else f"{k}.parquet"), v, chunk)
                  for k, v in SCHEMAS.items()}

    def add(self, g: GroupRecord) -> None:
        sig = _sig(g)
        old = self.seen.get(g.group_id)
        if old is not None:
            if old[0] != sig:
                self.stats["segment discrepancies"] += 1
                if len(g.segments) > old[1]:
                    self.stats["discrepancy longer later (ignored)"] += 1
            return
        self.seen[g.group_id] = (sig, len(g.segments))
        gid, w = g.group_id, self.w
        complete = all(hid in self.cached for hid, _, _ in g.occurrences)
        self.stats["complete groups"] += complete
        w["groups"].add(dict(group_id=gid, n_entries=g.n_entries, n_chains=g.n_chains,
                             books=g.books, n_occurrences=len(g.occurrences), complete=complete))
        for h, b, n in g.occurrences:
            w["occurrences"].add(dict(group_id=gid, hadith_id=h, book_slug=b, numbering=n))
        for s in g.segments:
            w["segments"].add(dict(group_id=gid, seg_no=s.seg_no, kind=s.kind,
                                   base_hash=s.base_hash, variant_hash=s.variant_hash,
                                   carrier_hadith_ids=s.carrier_hadith_ids))
            for hh, t in ((s.base_hash, s.base_text), (s.variant_hash, s.variant_text)):
                if hh and t is not None and hh not in self.text_seen:
                    self.text_seen.add(hh)
                    w["text"].add(dict(hash=hh, text=_WS.sub(" ", t).strip()))
        for (rid, ids), name in zip(g.shawahid, g.shawahid_names):
            w["shawahid"].add(dict(group_id=gid, companion_rawi_id=rid, companion_name=name,
                                   hadith_ids=ids))
            self.stats["shawahid resolved" if rid is not None else "shawahid unresolved"] += 1
        self.stats["groups"] += 1
        self.stats["segments"] += len(g.segments)
        self.stats["occurrences"] += len(g.occurrences)

    def close(self) -> None:
        for x in self.w.values():
            x.close()


def run_groups(cache_root, out_dir, limit: int | None = None, rawi_path=None) -> dict:
    paths = _pages(cache_root, "hadith")
    cached = {int(p.name.split(".")[0]) for p in paths if p.name.split(".")[0].isdigit()}
    if limit is not None:
        paths = paths[:limit]
    index = None
    rawi_path = rawi_path or "data/rawi.parquet"
    if Path(rawi_path).exists():
        from isnad.gold import NameIndex
        index = NameIndex.from_rawi(rawi_path)
    sink = _Sink(out_dir, cached)
    stats = sink.stats
    try:
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
            sink.add(rec)
    finally:
        sink.close()
    for k in ("pages", "no group", "errors", "groups", "complete groups", "occurrences",
              "segments", "segment discrepancies", "discrepancy longer later (ignored)",
              "shawahid resolved", "shawahid unresolved"):
        print(f"{k}: {stats[k]}")
    return dict(stats)
