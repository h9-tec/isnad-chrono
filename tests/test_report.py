import pandas as pd

from isnad import cli, report


def _scores(rows):
    base = dict(teacher_id=1, student_id=2, hadith_id=1, position=0, term="سمعت",
                chain_type="متصل", entry_kind="x", p_meet=0.9, how="birth_known",
                conflict_t=False, conflict_s=False, confirmed=False, explicit_term=True,
                ambiguous_term=False, denied=False, irsal=False, tadlis=False, verdict="ok")
    return pd.DataFrame([{**base, **r} for r in rows])


def _rawi():
    return pd.DataFrame({
        "rawi_id": [1, 2, 3, 4], "name": ["A full", "B full", "C full", "D full"],
        "abbrev": ["A", None, "C", "D"], "death_year": [100.0, 200.0, 300.0, None],
        "death_kind": ["exact", "exact", "approx", None],
        "birth_year": [50.0, 150.0, None, None],
        "narrative_years": [[100], [200, 205], [350, 360], []]})


def _hadith():
    return pd.DataFrame({"hadith_id": [1, 2, 3, 4], "book_slug": ["b-1", "b-2", "b-1", "b-1"]})


def _sc():
    return _scores([
        dict(teacher_id=1, student_id=2, hadith_id=1, p_meet=0.2, verdict="suspect"),
        dict(teacher_id=1, student_id=2, hadith_id=2, p_meet=0.2, verdict="suspect", term="عن"),
        dict(teacher_id=1, student_id=2, hadith_id=3, p_meet=0.2, verdict="suspect"),
        dict(teacher_id=1, student_id=2, hadith_id=4, p_meet=0.2, verdict="suspect"),
        dict(teacher_id=3, student_id=4, hadith_id=1, p_meet=0.05, verdict="chronology_gap"),
        dict(teacher_id=3, student_id=2, hadith_id=1, p_meet=0.99, verdict="ok"),
    ])


def test_weak_edges():
    w = report.weak_edges(_sc(), _rawi(), _hadith())
    assert list(w["p_meet"]) == [0.05, 0.2]
    assert list(w.columns) == report.WEAK_COLS + ["book_slugs"]
    r = w.iloc[1]
    assert r["n_hadith"] == 4 and r["term"] == "سمعت"
    assert r["example_hadith_ids"] == "1|2|3"
    assert r["student_abbrev"] == "B full"  # fallback to name
    assert r["book_slugs"] == "b-1|b-2"
    assert "book_slugs" not in report.weak_edges(_sc(), _rawi()).columns
    assert len(report.weak_edges(_sc(), _rawi(), n=1)) == 1


def test_weak_edges_empty():
    w = report.weak_edges(_scores([{}]), _rawi())
    assert w.empty and list(w.columns) == report.WEAK_COLS


def test_date_errors():
    d = report.date_errors(_rawi())
    assert list(d["rawi_id"]) == [3]
    assert d.iloc[0]["narrative_years"] == "350|360" and d.iloc[0]["diff"] == 50


def test_run_report_sections():
    sc, rw, h = _sc(), _rawi(), _hadith()
    md = report.run_report({"done": 3}, {"scores": sc, "rawi": rw, "hadith": h,
                                         "weak_edges": report.weak_edges(sc, rw, h)})
    for s in ("## Fetch", "## Tables", "## Coverage", "## Verdicts", "## Top 10 weak edges",
              "done: 3", "b-2"):
        assert s in md
    assert "## Fetch" not in report.run_report(None, {"scores": sc, "rawi": rw})


def test_cli_report(tmp_path, capsys):
    _sc().to_parquet(tmp_path / "s.parquet")
    r = _rawi()
    r.to_parquet(tmp_path / "r.parquet")
    _hadith().to_parquet(tmp_path / "h.parquet")
    cli.main(["report", "--scores", str(tmp_path / "s.parquet"), "--rawi", str(tmp_path / "r.parquet"),
              "--hadith", str(tmp_path / "h.parquet"), "--db", str(tmp_path / "none.sqlite"),
              "--out-dir", str(tmp_path)])
    assert "## Verdicts" in capsys.readouterr().out
    for f in ("weak_edges.csv", "date_errors.csv", "run_report.md"):
        assert (tmp_path / f).exists()
