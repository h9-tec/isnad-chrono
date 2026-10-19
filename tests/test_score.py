import pandas as pd

from isnad.dates import Year
from isnad.score import date_conflict, p_meet, sama_evidence, score_edges, verdict

NONE = Year(None, None, "none")


def test_regression_sulaym_miqdad():
    p, how = p_meet(Year(33, 1, "exact"), NONE, Year(130, 1, "exact"))
    assert p < 0.05 and how == "birth_imputed"


def test_explicit_bukhari_edge():
    p, _ = p_meet(Year(197, 1, "exact"), NONE, Year(219, 1, "exact"))
    assert p > 0.9


def test_birth_known_beats_imputed():
    p, how = p_meet(Year(100, 1, "exact"), Year(60, 1, "exact"), Year(130, 1, "exact"))
    assert how == "birth_known" and p > 0.99
    assert p_meet(Year(100, 1, "exact"), NONE, NONE) == (None, "no_dates")
    assert p_meet(NONE, Year(60, 1, "exact"), NONE) == (None, "no_dates")


def test_teacher_birth_imputation():
    p, how = p_meet(NONE, Year(60, 1, "exact"), NONE, Year(40, 1, "exact"))
    assert how == "birth_known" and 0.9 < p < 1


def test_conflict():
    assert date_conflict(106, [186, 86]) is True
    assert date_conflict(117, [117, 118]) is False
    assert date_conflict(None, [1]) is False and date_conflict(5, []) is False


def test_sama_evidence_flags():
    st = {"rawi_id": 2, "sama_confirmed": [1], "flags": ["كثير الإرسال"]}
    e = sama_evidence("حَدَّثَنَا", 1, st, {(2, 1)})
    assert e["explicit_term"] and not e["ambiguous_term"] and e["confirmed"]
    assert e["denied"] and e["irsal"] and not e["tadlis"]
    e = sama_evidence("عن", 3, {**st, "flags": ["تدليس"]}, set())
    assert e["ambiguous_term"] and not e["explicit_term"] and not e["denied"]
    assert e["tadlis"] and not e["irsal"] and not e["confirmed"]
    assert sama_evidence("حدثنا قال", 1, st, set())["explicit_term"]
    assert sama_evidence(None, 1, st, set())["ambiguous_term"]


def test_verdict_order():
    # R2: data_error > denied_by_critic > no_dates > chronology_gap > suspect > ok
    ev = dict(denied=True, ambiguous_term=True, irsal=True, tadlis=False)
    assert verdict(None, True, False, ev) == "data_error"
    assert verdict(None, False, False, ev) == "denied_by_critic"
    assert verdict(0.01, True, False, ev) == "data_error"
    assert verdict(0.01, False, True, ev) == "data_error"
    assert verdict(0.01, False, False, ev) == "denied_by_critic"
    ev["denied"] = False
    assert verdict(None, False, False, ev) == "no_dates"
    assert verdict(0.01, False, False, ev) == "chronology_gap"
    assert verdict(0.1, False, False, ev) == "suspect"
    ev["irsal"] = False
    assert verdict(0.1, False, False, ev) == "ok"
    assert verdict(0.9, False, False, ev) == "ok"


def test_score_edges_small(tmp_path):
    def r(i, dy, by=None, nar=(), sc=(), fl=()):
        return dict(rawi_id=i, death_year=dy, death_sd=1.0, death_kind="exact", birth_year=by,
                    birth_sd=None if by is None else 1.0, birth_kind="exact" if by else "none",
                    narrative_years=list(nar), sama_confirmed=list(sc), flags=list(fl))
    rawi = pd.DataFrame([r(1, 197), r(2, 219), r(3, 33)])
    rawi.loc[rawi.rawi_id == 3, "death_year"] = 33.0
    ed = pd.DataFrame([
        dict(teacher_id=1, student_id=2, hadith_id=10, position=1, term="حدثنا",
             chain_type="x", entry_kind="k"),
        dict(teacher_id=3, student_id=2, hadith_id=11, position=1, term="عن",
             chain_type="x", entry_kind="k"),
        dict(teacher_id=99, student_id=2, hadith_id=12, position=1, term=None,
             chain_type="x", entry_kind="k"),
    ])
    ed.to_parquet(tmp_path / "e.parquet")
    rawi.to_parquet(tmp_path / "r.parquet")
    out = score_edges(tmp_path / "e.parquet", tmp_path / "r.parquet", {(2, 3)},
                      tmp_path / "o.parquet")
    assert len(out) == 3 and (tmp_path / "o.parquet").exists()
    for c in ("p_meet", "how", "conflict_t", "conflict_s", "confirmed", "explicit_term",
              "ambiguous_term", "denied", "irsal", "tadlis", "verdict", "hadith_id"):
        assert c in out.columns
    assert list(out.verdict) == ["ok", "denied_by_critic", "no_dates"]
    assert out.how[2] == "missing_rawi" and pd.isna(out.p_meet[2])


def _rawi_row(i, dy, nar=()):
    return dict(rawi_id=i, death_year=dy, death_sd=1.0, death_kind="exact" if dy else "none",
                birth_year=None, birth_sd=None, birth_kind="none", narrative_years=list(nar),
                sama_confirmed=[], flags=[])


def test_missing_rawi_vs_no_dates_and_denials_not_hidden(tmp_path):
    rawi = pd.DataFrame([_rawi_row(1, 197.0), _rawi_row(2, None), _rawi_row(3, 106.0, (186.0,))])
    ed = pd.DataFrame([
        # student 2 present but undated -> no_dates
        dict(teacher_id=1, student_id=2, hadith_id=1, position=0, term="عن", chain_type=None,
             entry_kind="hadith"),
        # teacher 99 absent, but denied -> denied_by_critic (not hidden behind no_dates)
        dict(teacher_id=99, student_id=1, hadith_id=2, position=0, term="عن", chain_type=None,
             entry_kind="hadith"),
        # teacher 3 has a date conflict, student 2 undated -> data_error
        dict(teacher_id=3, student_id=2, hadith_id=3, position=0, term="عن", chain_type=None,
             entry_kind="hadith"),
        # teacher 98 absent, not denied -> no_dates with how=missing_rawi
        dict(teacher_id=98, student_id=1, hadith_id=4, position=0, term="عن", chain_type=None,
             entry_kind="hadith"),
    ])
    ed.to_parquet(tmp_path / "e.parquet")
    rawi.to_parquet(tmp_path / "r.parquet")
    out = score_edges(tmp_path / "e.parquet", tmp_path / "r.parquet", {(1, 99)})
    assert list(out.verdict) == ["no_dates", "denied_by_critic", "data_error", "no_dates"]
    assert list(out.how) == ["no_dates", "missing_rawi", "no_dates", "missing_rawi"]
    assert out.p_meet.isna().all()
