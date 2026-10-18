import pytest

from isnad.pageprops import NoPageData, component, extract


def test_extract_rawi_props(fx):
    p = extract(fx("rawi_4494.html"))
    assert p["person"]["slug"] == "p-4494"
    assert component(fx("rawi_4494.html")) == "Encyclopedia/Rawi/Show"


def test_extract_hadith_props(fx):
    p = extract(fx("hadith_muslim_11563.html"))
    assert p["hadith"]["id"] == 11563 and len(p["hadith"]["isnad"]) == 7


def test_no_page_data():
    with pytest.raises(NoPageData):
        extract("<html></html>")
