import pytest

from isnad.dates import CALIPHATES, Year, narrative_years, parse_year


@pytest.mark.parametrize("txt,num,exp", [
    ("58هـ", None, (58, 1.0, "exact")),
    ("١٠٦ أو ١٠٨", None, (107, 2.0, "alt")),
    ("نحو ١٣٠", None, (130, 5.0, "approx")),
    ("بعد ١٢٠", None, (123, 5.0, "after")),
    ("قبل ١٠٠", None, (97, 5.0, "before")),
    ("مات سنة ست وثمانين ومائة", None, (186, 1.0, "exact")),
    ("في خلافة عبد الملك بن مروان", None, (75.5, 5.25, "era")),
    (None, 93, (93, 1.0, "exact")),
    ("ولد على عهد النبي", None, (None, None, "none")),
])
def test_parse_year(txt, num, exp):
    y = parse_year(txt, num)
    assert (y.year, y.sd, y.kind) == exp


def test_narrative_years():
    s = "وقال ابن سعد: توفي بالمدينة سنة أربع ومائة. وقيل مات سنة 103"
    assert narrative_years(s) == [104, 103]


def test_era_phrase():
    assert parse_year("في خلافة عبد الملك بن مروان").kind == "era"


def test_year_is_frozen_and_positional():
    y = Year(33, 1, "exact")
    with pytest.raises(Exception):
        y.year = 5


def test_text_beats_num_and_none_without_num():
    assert parse_year("١٠٠", 93).year == 100
    assert parse_year("", None).kind == "none"
    assert CALIPHATES["أبو بكر"] == (11, 13)


@pytest.mark.parametrize("txt,val", [
    ("ثلاث وتسعين", 93), ("مائتين", 200), ("ثلاثمائة", 300),
    ("إحدى وخمسين ومائة", 151), ("ثمان عشرة ومئة", 118),
    ("سنة 7", 7), ("ثلاث مائة", 300), ("أربع ومائة", 104),
])
def test_number_words(txt, val):
    assert parse_year(txt).year == val


def test_narrative_filters_range():
    assert narrative_years("مات سنة 900 ثم مات سنة 5") == [5]


def test_num_beats_era():
    assert parse_year("في خلافة عبد الملك بن مروان", 86) == Year(86, 1.0, "exact")
