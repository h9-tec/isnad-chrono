import pandas as pd

from isnad.build import read_page
from isnad.chains import Chain, Link, build_chains, chains_table, hadith_chains, tokenize
from isnad.cli import main
from isnad.pageprops import extract
from tests.conftest import FIXTURES

BUKHARI_10 = [
    ("F", "حدثنا"), ("R", 3784), ("F", "أخبرنا"), ("R", 3875), ("F", "أخبرنا"), ("R", 7248),
    ("F", "عن"), ("R", 5917), ("H",), ("F", "وحدثنا"), ("R", 941), ("F", "أخبرنا"), ("R", 3875),
    ("F", "أخبرنا"), ("R", 7248), ("R", 6279), ("F", "عن"), ("R", 5917), ("F", "أخبرني"),
    ("R", 4184), ("F", "عن"), ("R", 3732),
]
TIRMIDHI_100144 = [
    ("F", "حدثنا"), ("R", 5187), ("F", "حدثنا"), ("R", 3493), ("F", "عن"), ("R", 4789), ("H",),
    ("F", "وحدثنا"), ("R", 4513), ("F", "أخبرنا"), ("R", 650), ("F", "عن"), ("R", 4789),
    ("F", "عن"), ("R", 3736), ("F", "عن"), ("R", 1339),
]


def hadith(html: str) -> dict:
    return extract(html)["hadith"]


def isnad_html(html: str) -> str:
    return hadith(html)["isnad_html"]


def paths(chains):
    return sorted(tuple(link.rawi_id for link in c.links) for c in chains)


def short(tokens):
    return [t[:2] if t[0] == "R" else t for t in tokens]


def test_tokenize_bukhari_10(fx_gz):
    toks = tokenize(isnad_html(fx_gz("hadith_bukhari_10_tahwil.html.gz")))
    assert short(toks) == BUKHARI_10
    assert toks[1] == ("R", 3784, "عبدان")


def test_tokenize_tirmidhi_100144(fx_gz):
    assert short(tokenize(isnad_html(fx_gz("hadith_tirmidhi_100144_tahwil.html.gz")))) == TIRMIDHI_100144


def test_tokenize_ha_inside_word_is_not_transfer():
    html = ('<span class="hp-sigha">حَدَّثَنَا </span><span class="hp-rawi" data-rawi-slug="p-1" '
            'data-name="أ">أ</span> حَتَّى ح، <span class="hp-rawi" data-rawi-slug="p-2" data-name="ب">ب</span>')
    assert short(tokenize(html)) == [("F", "حدثنا"), ("R", 1), ("H",), ("R", 2)]


def test_bukhari_10_three_chains(fx_gz):
    ch = build_chains(tokenize(isnad_html(fx_gz("hadith_bukhari_10_tahwil.html.gz"))), 5495)
    assert paths(ch) == sorted([(3732, 4184, 5917, 7248, 3875, 3784, 5495),
                                (3732, 4184, 5917, 7248, 3875, 941, 5495),
                                (3732, 4184, 5917, 6279, 3875, 941, 5495)])
    assert all(not c.unjoined for c in ch)
    assert all([link.position for link in c.links] == list(range(len(c.links))) for c in ch)


def test_tirmidhi_100144_two_chains(fx_gz):
    ch = build_chains(tokenize(isnad_html(fx_gz("hadith_tirmidhi_100144_tahwil.html.gz"))), 10859)
    assert paths(ch) == sorted([(1339, 3736, 4789, 3493, 5187, 10859),
                                (1339, 3736, 4789, 650, 4513, 10859)])
    assert all(not c.unjoined for c in ch)


def test_terms_follow_teacher_formula(fx_gz):
    ch = build_chains(tokenize(isnad_html(fx_gz("hadith_bukhari_10_tahwil.html.gz"))), 5495)
    via_3784 = next(c for c in ch if 3784 in [link.rawi_id for link in c.links])
    terms = {link.rawi_id: link.term for link in via_3784.links}
    assert terms[5917] == "عن"
    assert terms[7248] == "أخبرنا"
    assert terms[3784] == "حدثنا"
    assert terms[5495] is None
    via_6279 = next(c for c in ch if 6279 in [link.rawi_id for link in c.links])
    terms = {link.rawi_id: link.term for link in via_6279.links}
    assert terms[6279] == "أخبرنا"
    assert terms[941] == "حدثنا"  # "وحدثنا" with the leading waw stripped
    assert terms[4184] == "أخبرني"


def test_single_chain_matches_v1(fx):
    h = hadith(fx("hadith_muslim_11563.html"))
    ch = hadith_chains(h)
    assert len(ch) == 1 and not ch[0].unjoined
    flat = h["isnad"]
    assert [(link.rawi_id, link.term) for link in ch[0].links] == [
        (int(n["slug"][2:]), n.get("formula")) for n in flat]


def test_no_isnad_html_yields_no_chains():
    assert build_chains(tokenize(""), 1) == []


def test_unjoined_segment_flagged():
    toks = [("F", "حدثنا"), ("R", 99, ""), ("H",), ("F", "وحدثنا"), ("R", 1, ""),
            ("F", "عن"), ("R", 2, "")]
    ch = build_chains(toks, 7)
    assert [(tuple(link.rawi_id for link in c.links), c.unjoined) for c in ch] == [
        ((99, 7), True), ((2, 1, 7), False)]


def test_join_falls_back_to_earlier_narrator():
    # segment ends 1 -> 50; 50 never appears in the final path, so it joins at 1
    toks = [("R", 1, ""), ("F", "عن"), ("R", 50, ""), ("H",), ("R", 3, ""), ("R", 1, ""),
            ("F", "عن"), ("R", 2, "")]
    ch = build_chains(toks, 7)
    # joined chain 2,1,7 duplicates a final-path variant (3 and 1 are parallel): kept once
    assert [[link.rawi_id for link in c.links] for c in ch] == [[2, 1, 7], [2, 3, 7]]
    assert not any(c.unjoined for c in ch)


def test_types():
    assert Chain(links=[Link(1, 0, None)], unjoined=False).links[0].rawi_id == 1


def test_chains_table_and_cli(tmp_path, fx_gz, fx, capsys):
    root = tmp_path / "html" / "hadith"
    root.mkdir(parents=True)
    for name, hid in (("hadith_bukhari_10_tahwil.html.gz", "10"),
                      ("hadith_tirmidhi_100144_tahwil.html.gz", "100144")):
        (root / f"{hid}.html.gz").write_bytes((FIXTURES / name).read_bytes())
    (root / "11563.html").write_text(fx("hadith_muslim_11563.html"), encoding="utf-8")
    df = chains_table(tmp_path / "html")
    assert list(df.columns) == ["hadith_id", "chain_no", "position", "rawi_id", "term", "unjoined",
                                "source"]
    assert df.groupby("hadith_id")["chain_no"].nunique().to_dict() == {10: 3, 11563: 1, 100144: 2}
    assert set(df.loc[df.hadith_id == 11563, "source"]) == {"flat"}
    out = tmp_path / "chains.parquet"
    main(["chains", "--cache-root", str(tmp_path / "html"), "--out", str(out)])
    assert pd.read_parquet(out).equals(df)
    assert "hadith pages: 3" in capsys.readouterr().out


def test_fixture_pages_read(fx_gz):
    assert "hp-rawi" in fx_gz("hadith_bukhari_10_tahwil.html.gz")
    assert read_page(FIXTURES / "hadith_bukhari_10_tahwil.html.gz")


def _r(i, sub="رواة_الحديث"):
    return (f'<span class="hp-rawi" data-kind="narrator" data-rawi-slug="p-{i}" data-subkind="{sub}" '
            f'data-name="n{i}">اسم </span>')


def _f(text):
    return f'<span class="hp-mustalah"><span class="hp-sigha" data-kind="tahdeth_formula">{text} </span></span>'


def test_tokenize_narrator_nested_in_formula_span():
    # seen in Ibn Abi Dawud #148085: the sigha span wraps the sheikh's narrator span
    html = ('<span class="hp-sigha" data-kind="tahdeth_formula">حَدَّثَنَا ' + _r(11532)
            + '<span class="hp-mustalah">قِرَاءَةً عَلَيْهِ </span></span>، ' + _f("حَدَّثَنَا") + _r(5573))
    assert short(tokenize(html)) == [("F", "حدثنا"), ("R", 11532), ("F", "حدثنا"), ("R", 5573)]


def test_compiler_span_in_html_is_not_duplicated():
    # Musannaf Abd al-Razzaq: the compiler (subkind المصنف) opens the html; no self-loop
    html = _r(3447, "المصنف") + _f("عَنْ") + _r(7345) + _f("عَنْ") + _r(4851)
    ch = build_chains(tokenize(html), 3447)
    assert paths(ch) == [(4851, 7345, 3447)]
    assert [link.term for link in ch[0].links] == ["عن", "عن", None]


def test_compiler_span_drops_later_transmitters_before_it():
    html = _f("حدثنا") + _r(9) + _f("حدثني") + _r(3447) + _f("عن") + _r(7345)
    assert paths(build_chains(tokenize(html), 3447)) == [(7345, 3447)]


def test_placeholder_ids_resolved_from_flat_neighbours():
    # p-1 / p-2 are placeholder slugs (no rawi page); the flat isnad names the narrator
    html = _f("حدثنا") + _r(8) + _f("حدثنا") + _r(2) + _f("عن") + _r(5)
    flat = [{"slug": f"p-{i}", "formula": f} for i, f in
            ((5, "عن"), (102393, "عن"), (8, "حدثنا"), (77, None))]
    ch = hadith_chains({"isnad_html": html, "isnad": flat})
    assert paths(ch) == [(5, 102393, 8, 77)]


def test_placeholder_kept_when_flat_is_ambiguous():
    html = _f("حدثنا") + _r(8) + _f("حدثنا") + _r(1) + _f("عن") + _r(5)
    flat = [{"slug": f"p-{i}"} for i in (5, 6, 4, 8, 77)]  # two narrators between 5 and 8
    assert paths(hadith_chains({"isnad_html": html, "isnad": flat})) == [(5, 1, 8, 77)]
