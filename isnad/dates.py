"""Hijri date parser: Arabic text (digits or number words) to a Year with uncertainty."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Year:
    year: float | None
    sd: float | None
    kind: str  # exact | alt | approx | after | before | era | none


CALIPHATES: dict[str, tuple[int, int]] = {
    "عبد الملك بن مروان": (65, 86),
    "الوليد بن عبد الملك": (86, 96),
    "سليمان بن عبد الملك": (96, 99),
    "عمر بن عبد العزيز": (99, 101),
    "يزيد بن عبد الملك": (101, 105),
    "هشام بن عبد الملك": (105, 125),
    "المنصور": (136, 158),
    "المهدي": (158, 169),
    "هارون الرشيد": (170, 193),
    "المأمون": (198, 218),
    "معاوية": (41, 60),
    "عثمان": (23, 35),
    "عمر بن الخطاب": (13, 23),
    "أبو بكر": (11, 13),
}

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile("[ً-ْٰـ]")


def _norm(s: str) -> str:
    s = _DIACRITICS.sub("", s.translate(_DIGITS))
    for a in "أإآٱ":
        s = s.replace(a, "ا")
    return s.replace("ة", "ه").replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")


_ERAS = {_norm(k): v for k, v in CALIPHATES.items()}

_UNITS = {
    "واحد": 1, "احد": 1, "احدي": 1, "اثنين": 2, "اثنتين": 2, "اثنان": 2, "اثنا": 2,
    "اثني": 2, "ثنتين": 2, "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4,
    "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7,
    "ثمان": 8, "ثماني": 8, "ثمانيه": 8, "تسع": 9, "تسعه": 9,
}
_TEENS_TEN = {"عشر": 10, "عشره": 10}
_TENS = {
    "عشرين": 20, "عشرون": 20, "ثلاثين": 30, "ثلاثون": 30, "اربعين": 40, "اربعون": 40,
    "خمسين": 50, "خمسون": 50, "ستين": 60, "ستون": 60, "سبعين": 70, "سبعون": 70,
    "ثمانين": 80, "ثمانون": 80, "تسعين": 90, "تسعون": 90,
}
_HUNDRED = {_norm(w) for w in ("مائة", "مئة", "ماية", "مايه")}
_TWO_HUNDRED = {_norm(w) for w in ("مائتين", "مئتين", "مائتان", "مئتان")}
# fused forms: ثلاثمائة ... تسعمائة
_FUSED = {}
for _w, _n in (("ثلاث", 3), ("اربع", 4), ("خمس", 5), ("ست", 6), ("سبع", 7), ("ثمان", 8), ("تسع", 9)):
    for _h in _HUNDRED:
        _FUSED[_w + _h] = _n * 100

_PUNCT = ".,;:،؛()[]«»\"'"


def _clean(tok: str) -> str:
    return tok.strip(_PUNCT)


def _word_value(tok: str) -> int | None:
    """Value of a single number word, trying the token with and without a leading و."""
    for t in (tok, tok[1:] if tok.startswith("و") else None):
        if not t:
            continue
        if t in _FUSED:
            return _FUSED[t]
        if t in _TWO_HUNDRED:
            return 200
        if t in _HUNDRED:
            return 100
        if t in _TENS:
            return _TENS[t]
        if t in _TEENS_TEN:
            return 10
        if t in _UNITS:
            return _UNITS[t]
    return None


def _sum_words(tokens: list[str]) -> int | None:
    total, prev_unit, found = 0, None, False
    for raw in tokens:
        tok = _clean(raw)
        v = _word_value(tok)
        if v is None:
            continue
        found = True
        if tok in _HUNDRED and prev_unit is not None and 3 <= prev_unit <= 9:
            total += prev_unit * 99  # "ثلاث مائة": unit already added once, make it unit*100
            prev_unit = None
            continue
        prev_unit = v if tok in _UNITS else None
        total += v
    return total if found else None


def _value(segment: str) -> int | None:
    m = re.search(r"\d+", segment)
    if m:
        return int(m.group())
    return _sum_words(segment.split())


def _bound(word: str) -> str:
    return rf"(?<!\S){word}(?!\S)"


_APPROX = re.compile(_bound("نحو") + "|" + _bound("تقريبا") + "|" + _bound("حدود") + "|~")
_AFTER = re.compile(_bound("بعد") + "|>")
_BEFORE = re.compile(_bound("قبل") + "|<")
_ALT = re.compile(r"(?<!\S)(?:او|or)(?!\S)|/")


def parse_year(text: str | None, num: int | None = None) -> Year:
    if text:
        t = _norm(text)
        parts = _ALT.split(t)
        if len(parts) == 2:
            a, b = _value(parts[0]), _value(parts[1])
            if a is not None and b is not None:
                return Year((a + b) / 2, max(2.0, abs(a - b) / 2), "alt")
        v = _value(t)
        if v is not None:
            if _APPROX.search(t):
                return Year(v, 5.0, "approx")
            if _AFTER.search(t):
                return Year(v + 3, 5.0, "after")
            if _BEFORE.search(t):
                return Year(v - 3, 5.0, "before")
            return Year(v, 1.0, "exact")
    if num is not None:
        return Year(num, 1.0, "exact")
    if text:
        for key in sorted(_ERAS, key=len, reverse=True):
            if key in t:
                lo, hi = _ERAS[key]
                return Year((lo + hi) / 2, (hi - lo) / 4, "era")
    return Year(None, None, "none")


_TRIGGER = re.compile(r"(?:مات|توفي|وفاته|هلك)[^.]{0,40}?" + _bound("سنه"))


def narrative_years(text: str) -> list[int]:
    t = _norm(text)
    out = []
    for m in _TRIGGER.finditer(t):
        toks = []
        for raw in t[m.end():].split():
            tok = _clean(raw)
            if tok.isdigit() or _word_value(tok) is not None:
                toks.append(tok)
                if raw != tok:  # trailing punctuation ends the expression
                    break
            else:
                break
        v = _value(" ".join(toks)) if toks else None
        if v is not None and 1 <= v <= 400:
            out.append(v)
    return out
