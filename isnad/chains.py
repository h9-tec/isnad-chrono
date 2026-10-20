"""Isnad chains from the annotated ``isnad_html``, aware of tahwil (ح) and parallel narrators.

Reading order is compiler side first. A transfer splits the text into segments: a
standalone ح, a و-formula (وحدثنا, وأخبرنا, ...) after a narrator, or "وقال NAME:" naming an
earlier narrator (the new segment replays the path down to that narrator). The last segment
is a full path and each earlier one joins it at a shared narrator; a join phrase (كلاهما,
كلهم, جميعا, ثلاثتهم) before "عن X" makes every open segment continue through X. Two
narrator spans with no formula between them are parallel and fork the chain at that level.
Chains that stop short of the flat isnad's earliest narrators are completed from it.
"""

import html as _html
import itertools
import logging
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from isnad import pageprops
from isnad.build import _PARSE_ERRORS, _pages, read_page
from isnad.dates import _DIACRITICS, _norm

Tok = tuple  # ("R", rawi_id, name) | ("F", formula) | ("H",) | ("H", kind) | ("J",)
# ("H",) is a ح; ("H", "و") an implicit transfer at a و-formula; ("H", "قال") a "وقال NAME:"
# restart; ("J",) a join phrase (كلاهما ...) before the shared narrator.

# Opening tags only: a formula span can wrap the narrator span that follows it, so span
# bodies are never matched as a whole.
_OPEN_RE = re.compile(r'<span\b(?P<attrs>[^>]*\bclass="(?P<cls>hp-rawi|hp-sigha)"[^>]*)>')
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_SLUG_RE = re.compile(r"p-(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^ء-يٮ-ۓ ]+")  # punctuation inside formula spans ("، عن")
_HA_RE = re.compile(r"(?<![ء-ٟٮ-ۓ])ح(?![ء-ٟٮ-ۓ])")  # letters/harakat only, so "ح،" counts
_WAW_ROOTS = tuple(_norm(w) for w in ("وحدثن", "وأخبرن", "وأنبأن"))  # وحدثنا/ني, وأخبرنا/ني, وأنبأنا
_JOIN_RE = re.compile(r"(?:^|\s)(?:كلاهما|كلهما|كلهم|جميعا|ثلاثتهم)(?:\s|[،,.]|$)[\s،,.-]*$")
_RESTART_RE = re.compile(r"(?:^|\s)وقال\s+([^:،,.]+?)\s*:[\s،,.-]*$")
MAX_VARIANTS = 64
log = logging.getLogger(__name__)
PLACEHOLDER_IDS = frozenset({1, 2})  # slugs p-1/p-2: unresolved/anonymous, no rawi page
COLUMNS = ["hadith_id", "chain_no", "position", "rawi_id", "term", "unjoined", "source"]


@dataclass(frozen=True, slots=True)
class Link:
    rawi_id: int
    position: int  # 0 = earliest narrator (companion end); compiler last
    term: str | None  # how the NEXT link received from this one


@dataclass(frozen=True, slots=True)
class Chain:
    links: list[Link]
    unjoined: bool
    source: str = "html"  # "html" | "html+flat" (completed from the flat isnad) | "flat"


def _plain(s: str) -> str:
    return _DIACRITICS.sub("", _html.unescape(s)).strip()


def _term(formula: str | None) -> str | None:
    if not formula:
        return None
    t = _plain(formula)
    if t.startswith("و") and len(t) > 2 and not t.startswith("وجد"):  # وحدثنا -> حدثنا
        t = t[1:]
    return t or None


def _gap_text(fragment: str) -> str:
    return " ".join(_norm(_html.unescape(_TAG_RE.sub(" ", fragment))).split())


def _restart(toks: list[Tok], name: str) -> list[Tok]:
    """Tokens replaying the path down to the earlier narrator called ``name`` (or [])."""
    want = name.split()[0] if name.split() else ""
    for i in range(len(toks) - 1, -1, -1):
        t = toks[i]
        if t[0] == "R" and want and _norm(t[2]).split()[:1] == [want]:
            start = max((j + 1 for j in range(i) if toks[j][0] == "H"), default=0)
            return [x for x in toks[start:i + 1] if x[0] in ("R", "F")]
    return []


def tokenize(isnad_html: str) -> list[Tok]:
    html = isnad_html or ""
    toks: list[Tok] = []
    pos = 0
    for m in _OPEN_RE.finditer(html):
        if m.start() < pos:  # inside a narrator body already consumed
            continue
        raw_gap = _html.unescape(_TAG_RE.sub(" ", html[pos:m.start()]))
        if _HA_RE.search(raw_gap) and toks and toks[-1][0] != "H":
            toks.append(("H",))
        attrs = dict(_ATTR_RE.findall(m["attrs"]))
        if m["cls"] == "hp-sigha":  # formula text runs to the first nested tag
            gap = _gap_text(html[pos:m.start()])
            end = html.find("<", m.end())
            end = len(html) if end < 0 else end
            f = " ".join(_NON_WORD_RE.sub(" ", _plain(html[m.end():end])).split())
            restart = _RESTART_RE.search(gap)
            replay = _restart(toks, restart[1]) if restart else []
            if replay:
                toks += [("H", "قال")] + replay
            elif _JOIN_RE.search(gap) and any(t[0] == "R" for t in toks):
                toks.append(("J",))
            elif (_norm(f).startswith(_WAW_ROOTS) and any(t[0] == "R" for t in toks)
                  and toks[-1][0] != "H"):
                toks.append(("H", "و"))
            toks.append(("F", f))
            pos = end
            continue
        close = html.find("</span>", m.end())
        pos = len(html) if close < 0 else close + len("</span>")
        slug = _SLUG_RE.fullmatch(attrs.get("data-rawi-slug", ""))
        if slug:
            toks.append(("R", int(slug[1]), _html.unescape(attrs.get("data-name", ""))))
    while toks and toks[-1][0] in ("H", "J"):
        toks.pop()
    return toks


Level = list[tuple[int, str | None]]  # parallel narrators sharing one term


def _segments(tokens: list[Tok]) -> list[list[Level]]:
    segs: list[list[Level]] = [[]]
    formula, prev = None, None
    open_start, cont = 0, None  # cont: index of the segment after a join phrase

    def close_join() -> None:
        nonlocal open_start, cont
        if cont is None:
            return
        tail = segs.pop(cont)
        for seg in segs[open_start:cont]:
            seg.extend([list(level) for level in tail])
        open_start, cont = len(segs), None

    for t in tokens:
        if t[0] in ("H", "J"):
            close_join()
            if t[0] == "J":
                cont = len(segs)
            segs.append([])
            formula, prev = None, None
        elif t[0] == "F":
            formula, prev = t[1], "F"
        elif t[0] == "R":
            seg = segs[-1]
            if prev == "R" and seg:  # parallel: no formula since the last narrator
                if all(t[1] != r for r, _ in seg[-1]):
                    seg[-1].append((t[1], seg[-1][0][1]))
            else:
                seg.append([(t[1], _term(formula))])
            formula, prev = None, "R"
    close_join()
    return [s for s in segs if s]


def _variants(levels: list[Level], compiler_id: int | None, unjoined: bool):
    for combo in itertools.product(*levels):
        path = list(reversed(combo))  # earliest first
        if compiler_id is not None:
            path.append((compiler_id, None))
        yield Chain([Link(r, i, term) for i, (r, term) in enumerate(path)], unjoined)


def _join(seg: list[Level], final: list[Level]) -> list[Level] | None:
    for k in range(len(seg) - 1, -1, -1):
        ids = {r for r, _ in seg[k]}
        for j, level in enumerate(final):
            if ids & {r for r, _ in level}:
                return seg[:k + 1] + final[j + 1:]
    return None


def _below_compiler(seg: list[Level], compiler_id: int | None) -> list[Level]:
    """Drop the compiler's own span (and any later transmitters read before it)."""
    for k in range(len(seg) - 1, -1, -1):
        if any(r == compiler_id for r, _ in seg[k]):
            return seg[k + 1:]
    return seg


def build_chains(tokens: list[Tok], compiler_id: int | None,
                 stats: Counter | None = None) -> list[Chain]:
    segs = [s for s in (_below_compiler(s, compiler_id) for s in _segments(tokens)) if s]
    if not segs:
        return []
    final = segs[-1]
    groups = []
    for seg in segs[:-1]:
        joined = _join(seg, final)
        groups.append(_variants(seg if joined is None else joined, compiler_id, joined is None))
    groups.append(_variants(final, compiler_id, False))
    seen, out = set(), []
    for c in itertools.chain.from_iterable(groups):
        key = tuple((link.rawi_id, link.term) for link in c.links)
        if key in seen:
            continue
        if len(out) == MAX_VARIANTS:  # keep the first 64
            if stats is not None:
                stats["capped hadith"] += 1
            break
        seen.add(key)
        out.append(c)
    return out


def _compiler_id(h: dict) -> int | None:
    flat = h.get("isnad") or []
    return int(flat[-1]["slug"][2:]) if flat else None


def _resolve_placeholders(toks: list[Tok], flat_ids: list[int]) -> list[Tok]:
    """Replace p-1/p-2 spans by the flat-isnad narrator between the same two neighbours.

    Neighbours are the nearest narrator spans on either side within the same ح segment
    (the compiler stands in on the compiler side). A candidate is taken only when it is
    unambiguous and not already named elsewhere in the html; otherwise the placeholder stays.
    """
    if not flat_ids or not any(t[0] == "R" and t[1] in PLACEHOLDER_IDS for t in toks):
        return toks
    named = {t[1] for t in toks if t[0] == "R"}
    out = list(toks)
    for i, t in enumerate(toks):
        if t[0] != "R" or t[1] not in PLACEHOLDER_IDS:
            continue

        def neighbour(step: int) -> int | None:
            j = i + step
            while 0 <= j < len(toks) and toks[j][0] != "H":
                if toks[j][0] == "R" and toks[j][1] not in PLACEHOLDER_IDS:
                    return toks[j][1]
                j += step
            return flat_ids[-1] if step < 0 else None  # compiler side ends at the compiler

        student, teacher = neighbour(-1), neighbour(+1)
        i_s = flat_ids.index(student) if student in flat_ids else None
        i_t = flat_ids.index(teacher) if teacher in flat_ids else None
        if i_s is not None and i_t is not None:
            cand = flat_ids[i_t + 1] if i_s - i_t == 2 else None
        elif i_t is not None:
            cand = flat_ids[i_t + 1] if i_t + 1 < len(flat_ids) else None
        elif i_s is not None:
            cand = flat_ids[i_s - 1] if i_s > 0 else None
        else:
            cand = None
        if cand is not None and cand not in PLACEHOLDER_IDS and cand not in named:
            out[i] = ("R", cand, t[2])
    return out


def _complete(c: Chain, flat: list[dict], stats: Counter) -> Chain:
    """Prepend the flat-isnad narrators earlier than the chain's earliest narrator X."""
    flat_ids = [int(n["slug"][2:]) for n in flat]
    x = c.links[0].rawi_id
    if x not in flat_ids:
        stats["truncated_unmatched"] += 1
        return c
    i = flat_ids.index(x)
    if i == 0:
        return c
    head = [(flat_ids[k], _term(flat[k].get("formula"))) for k in range(i)]
    if {r for r, _ in head} & {link.rawi_id for link in c.links}:
        stats["truncated_unmatched"] += 1  # completing would repeat a narrator
        return c
    stats["truncated completed"] += 1
    path = head + [(link.rawi_id, link.term) for link in c.links]
    return Chain([Link(r, k, term) for k, (r, term) in enumerate(path)], c.unjoined, "html+flat")


def hadith_chains(h: dict, stats: Counter | None = None) -> list[Chain]:
    """Chains for one ``props["hadith"]``; falls back to the flat isnad if no narrator spans."""
    stats = Counter() if stats is None else stats
    toks = tokenize(h.get("isnad_html") or "")
    flat = h.get("isnad") or []
    if any(t[0] == "R" for t in toks):
        flat_ids = [int(n["slug"][2:]) for n in flat]
        for t in toks:
            if t[0] in ("H", "J"):
                stats[{("H",): "ح transfers", ("H", "و"): "implicit و transfers",
                       ("H", "قال"): "وقال restarts", ("J",): "join phrases"}[t]] += 1
        chains = build_chains(_resolve_placeholders(toks, flat_ids), _compiler_id(h), stats)
        return [_complete(c, flat, stats) for c in chains] if flat else chains
    if not flat:
        return []
    links = [Link(int(n["slug"][2:]), i, _term(n.get("formula"))) for i, n in enumerate(flat)]
    return [Chain(links, False, "flat")]


def chains_table(cache_root, stats: Counter | None = None) -> pd.DataFrame:
    stats = Counter() if stats is None else stats
    rows = []
    for p in _pages(cache_root, "hadith"):
        try:
            h = pageprops.extract(read_page(p))["hadith"]
            hid = int(h["id"])
            capped = stats["capped hadith"]
            chains = hadith_chains(h, stats)
        except _PARSE_ERRORS:
            stats["errors"] += 1
            continue
        stats["hadith pages"] += 1
        if stats["capped hadith"] > capped:
            log.warning("hadith %s: more than %d chain variants, kept the first %d",
                        hid, MAX_VARIANTS, MAX_VARIANTS)
        html = h.get("isnad_html") or ""
        if not html.strip():
            stats["empty isnad_html"] += 1
        if "hp-rawi" not in html:
            stats["no narrator spans"] += 1
            if chains:
                stats["flat fallback"] += 1
                if _HA_RE.search(_TAG_RE.sub(" ", html)):
                    stats["flat fallback with ح (tahwil lost)"] += 1
        if not chains:
            stats["zero chains"] += 1
        if len(chains) > 1:
            stats["hadith with >1 chain"] += 1
        flat = tuple(int(n["slug"][2:]) for n in h.get("isnad") or [])
        if flat and chains and flat not in {tuple(x.rawi_id for x in c.links) for c in chains}:
            stats["flat isnad not among chains"] += 1
        for no, c in enumerate(chains):
            stats["chains"] += 1
            stats["unjoined chains"] += c.unjoined
            stats["chains without compiler link"] += c.source != "flat" and not h.get("isnad")
            stats["chains with placeholder id (p-1/p-2)"] += any(
                link.rawi_id in PLACEHOLDER_IDS for link in c.links)
            rows += [{"hadith_id": hid, "chain_no": no, "position": link.position,
                      "rawi_id": link.rawi_id, "term": link.term, "unjoined": c.unjoined,
                      "source": c.source} for link in c.links]
    return pd.DataFrame(rows, columns=COLUMNS)


def run_chains(cache_root, out, limit: int | None = None) -> pd.DataFrame:
    stats: Counter = Counter()
    if limit is None:
        df = chains_table(cache_root, stats)
    else:  # symlink the first `limit` pages into a temporary root; the cache is only read
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "hadith").mkdir()
            for p in _pages(cache_root, "hadith")[:limit]:
                (Path(tmp) / "hadith" / p.name).symlink_to(Path(p).resolve())
            df = chains_table(tmp, stats)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    for k in ("hadith pages", "chains", "unjoined chains", "hadith with >1 chain",
              "empty isnad_html", "no narrator spans", "flat fallback",
              "flat fallback with ح (tahwil lost)", "zero chains",
              "flat isnad not among chains", "chains with placeholder id (p-1/p-2)",
              "truncated completed", "truncated_unmatched", "ح transfers",
              "implicit و transfers", "وقال restarts", "join phrases", "capped hadith",
              "chains without compiler link", "errors"):
        print(f"{k}: {stats[k]}")
    return df
