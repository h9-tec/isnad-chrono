from isnad.parse_rawi import parse_rawi


def test_rawi_card(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert r.rawi_id == 4494 and r.abbrev == "علقمة بن وقاص العتواري"
    assert r.death.kind == "era" and 70 < r.death.year < 80
    assert r.living_city == "المدينة" and r.ibn_hajar == "ثقة ثبت"


def test_rawi_relations(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert (3026, 57) in r.teachers and len(r.teachers) == 13 and len(r.students) == 9
    assert r.sama_confirmed == [4677, 3026, 5917, 5443, 4868, 3799]
    assert r.flags == ["الإرسال"]


def test_rawi_opinions_and_text(fx):
    r = parse_rawi(fx("rawi_4494.html"))
    assert len(r.opinions) == 19 and r.opinions[0].scholar == "الواقدي" and r.opinions[0].scholar_death == 207
    assert len(r.tuhfa_entries) == 1
    assert "علقمة بن وقاص" in r.name_forms
