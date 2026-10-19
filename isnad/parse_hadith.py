"""Parse a cached hadith page into a record and teacher->student edges."""

from dataclasses import dataclass

from isnad import pageprops


@dataclass(frozen=True, slots=True)
class ChainLink:
    rawi_id: int
    position: int
    formula: str | None
    reliability: str | None
    dates: str | None
    flags: list[str]


@dataclass(frozen=True, slots=True)
class HadithRecord:
    hadith_id: int
    book_slug: str
    book_title: str
    number: str | None
    entry_kind: str
    chain_type: str | None
    grading: list[dict]
    chain: list[ChainLink]


@dataclass(frozen=True, slots=True)
class Edge:
    teacher_id: int
    student_id: int
    hadith_id: int
    position: int
    term: str | None
    chain_type: str | None
    entry_kind: str


def parse_hadith(html: str) -> HadithRecord:
    h = pageprops.extract(html)["hadith"]
    chain = [
        ChainLink(
            rawi_id=int(n["slug"][2:]),
            position=i,
            formula=n.get("formula"),
            reliability=n.get("reliability"),
            dates=n.get("dates"),
            flags=list(n.get("flags") or []),
        )
        for i, n in enumerate(h.get("isnad") or [])
    ]
    return HadithRecord(
        hadith_id=h["id"],
        book_slug=h["book"]["slug"],
        book_title=h["book"]["title"],
        number=h.get("numbering_harf"),
        entry_kind=h["entry_kind"],
        chain_type=h.get("chain_type"),
        grading=h.get("grading") or [],
        chain=chain,
    )


def edges(rec: HadithRecord) -> list[Edge]:
    return [
        Edge(
            teacher_id=a.rawi_id,
            student_id=b.rawi_id,
            hadith_id=rec.hadith_id,
            position=a.position,
            # Each node's formula is the word printed before that narrator's name,
            # i.e. how the next (later) narrator received from them: the teacher's.
            term=a.formula,
            chain_type=rec.chain_type,
            entry_kind=rec.entry_kind,
        )
        for a, b in zip(rec.chain, rec.chain[1:])
    ]
