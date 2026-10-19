from isnad.parse_hadith import edges, parse_hadith


def test_chain_order_and_ids(fx):
    r = parse_hadith(fx("hadith_muslim_11563.html"))
    assert [l.rawi_id for l in r.chain] == [2651, 3234, 1580, 2779, 6792, 3889, 6116]
    assert r.book_slug == "b-2" and r.hadith_id == 11563 and r.chain_type == "معلق"


def test_edges_terms(fx):
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert len(e) == 6
    assert (e[0].teacher_id, e[0].student_id, e[0].term) == (2651, 3234, "عن")
    assert (e[3].teacher_id, e[3].student_id, e[3].term) == (2779, 6792, "حدثنا")


def test_compiler_edge_has_none_term(fx):
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert (e[-1].teacher_id, e[-1].student_id, e[-1].term) == (3889, 6116, None)


def test_no_chain_passage(fx):
    r = parse_hadith(fx("hadith_muslim_11558_nochain.html"))
    assert r.entry_kind == "passage" and r.chain == [] and edges(r) == []


def test_chain_type_kept(fx):
    assert all(x.chain_type == "معلق" for x in edges(parse_hadith(fx("hadith_muslim_11563.html"))))
