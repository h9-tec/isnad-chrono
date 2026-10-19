"""Parse a cached narrator page into a record of dates, relations and critic statements."""

from dataclasses import dataclass

from isnad import pageprops
from isnad.dates import Year, narrative_years, parse_year

TUHFA_BOOK = "تحفة التحصيل في المراسيل"


@dataclass(frozen=True, slots=True)
class Opinion:
    scholar: str
    scholar_id: int | None
    scholar_death: int | None
    statement: str
    classification: int
    bucket: str


@dataclass(frozen=True, slots=True)
class RawiRecord:
    rawi_id: int
    name: str
    abbrev: str | None
    kunya: str | None
    lineage: str | None
    generation: str | None
    generation_num: int | None
    birth_text: str | None
    death_text: str | None
    death_num: int | None
    death: Year
    birth: Year
    birth_city: str | None
    death_city: str | None
    living_city: str | None
    ibn_hajar: str | None
    dhahabi: str | None
    is_companion: bool
    teachers: list[tuple[int, int | None]]
    students: list[tuple[int, int | None]]
    sama_confirmed: list[int]
    flags: list[str]
    opinions: list[Opinion]
    narrative_years: list[int]
    tuhfa_entries: list[str]
    name_forms: list[str]


def _rel(items: list[dict] | None) -> list[tuple[int, int | None]]:
    return [(int(t["slug"][2:]), t.get("death")) for t in items or []]


def parse_rawi(html: str) -> RawiRecord:
    props = pageprops.extract(html)
    p = props["person"]
    rulings = props.get("rulings") or {}
    raw_ops = (props.get("criticism") or {}).get("opinions") or []
    bios = props.get("biographies") or []

    opinions = [
        Opinion(
            scholar=o["scholar"],
            scholar_id=int(o["scholar_slug"][2:]) if o.get("scholar_slug") else None,
            scholar_death=o.get("scholar_death"),
            statement=o["statement"],
            classification=o["classification"],
            bucket=o["bucket"],
        )
        for o in raw_ops
    ]
    years: list[int] = []
    for b in bios:
        years += narrative_years(b.get("content") or "")
    for o in raw_ops:
        years += narrative_years(o["statement"])

    return RawiRecord(
        rawi_id=int(p["slug"][2:]),
        name=p["name"],
        abbrev=p.get("abbrev"),
        kunya=p.get("patronymic"),
        lineage=p.get("lineage"),
        generation=p.get("generation"),
        generation_num=p.get("generation_num"),
        birth_text=p.get("birth"),
        death_text=p.get("death"),
        death_num=p.get("death_num"),
        death=parse_year(p.get("death"), p.get("death_num")),
        birth=parse_year(p.get("birth")),
        birth_city=p.get("birth_city"),
        death_city=p.get("death_city"),
        living_city=p.get("living_city"),
        ibn_hajar=p.get("ibn_hajar"),
        dhahabi=p.get("dhahabi"),
        is_companion=bool(p.get("is_companion")),
        teachers=_rel(props.get("teachers")),
        students=_rel(props.get("students")),
        sama_confirmed=[  # entries missing kind/teacher_slug are skipped, not fatal
            int(s["teacher_slug"][2:])
            for s in rulings.get("sama") or []
            if (s.get("kind") or "").startswith("إثبات") and s.get("teacher_slug")
        ],
        flags=[f["type"] for f in rulings.get("flags") or [] if f.get("type")],
        opinions=opinions,
        narrative_years=years,
        tuhfa_entries=[b["content"] for b in bios
                       if b.get("book") == TUHFA_BOOK and b.get("content")],
        name_forms=[n["form"] for n in props.get("name_forms") or []],
    )
