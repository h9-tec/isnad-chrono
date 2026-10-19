from isnad.parse_hadith import edges, parse_hadith

# Printed chain of Muslim 11563:
# "حدثنا أبو بكر بن أبي شيبة، حدثنا وكيع، عن شعبة، عن الحكم، عن ابن أبي ليلى، عن سمرة"
# Each node's formula is the word printed before that narrator's name, i.e. how the
# next (later) narrator received from them, so edge teacher->student takes the
# TEACHER's formula.
SAMURA, IBN_ABI_LAYLA, HAKAM, SHUBA, WAKI, ABU_BAKR, MUSLIM = 2651, 3234, 1580, 2779, 6792, 3889, 6116


def test_chain_order_and_ids(fx):
    r = parse_hadith(fx("hadith_muslim_11563.html"))
    assert [l.rawi_id for l in r.chain] == [SAMURA, IBN_ABI_LAYLA, HAKAM, SHUBA, WAKI, ABU_BAKR, MUSLIM]
    assert r.book_slug == "b-2" and r.hadith_id == 11563 and r.chain_type == "معلق"


def test_edges_terms_are_teacher_formula(fx):
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert [(x.teacher_id, x.student_id, x.term) for x in e] == [
        (SAMURA, IBN_ABI_LAYLA, "عن"),
        (IBN_ABI_LAYLA, HAKAM, "عن"),
        (HAKAM, SHUBA, "عن"),
        (SHUBA, WAKI, "عن"),
        (WAKI, ABU_BAKR, "حدثنا"),
        (ABU_BAKR, MUSLIM, "حدثنا"),
    ]


def test_compiler_formula_never_used_as_term(fx):
    # The compiler (last node, formula None) is only ever a student.
    e = edges(parse_hadith(fx("hadith_muslim_11563.html")))
    assert e[-1].student_id == MUSLIM and e[-1].term == "حدثنا"
    assert all(x.term is not None for x in e)


def test_no_chain_passage(fx):
    r = parse_hadith(fx("hadith_muslim_11558_nochain.html"))
    assert r.entry_kind == "passage" and r.chain == [] and edges(r) == []


def test_chain_type_kept(fx):
    assert all(x.chain_type == "معلق" for x in edges(parse_hadith(fx("hadith_muslim_11563.html"))))
