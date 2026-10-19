import json

import pandas as pd

from isnad import gold


def _rawi(tmp_path, rows):
    p = tmp_path / "rawi.parquet"
    pd.DataFrame(rows).to_parquet(p)
    return p


def _row(i, name, abbrev=None, forms=()):
    return {"rawi_id": i, "name": name, "abbrev": abbrev, "name_forms": list(forms),
            "death_year": None}


def test_resolver_exact(tmp_path):
    p = _rawi(tmp_path, [_row(1, "إبراهيم بن يزيد بن قيس النخعي", "إبراهيم النخعي"),
                         _row(2, "شعبة بن الحجاج", "شعبة")])
    idx = gold.NameIndex.from_rawi(p)
    r = idx.resolve("إبراهيم النخعي")
    assert r.rawi_id == 1 and not r.ambiguous
    assert idx.resolve("أبو زيد الغريب").rawi_id is None


def test_resolver_ambiguous(tmp_path):
    p = _rawi(tmp_path, [_row(1, "محمد بن سيرين الأول", "محمد سيرين"),
                         _row(2, "محمد بن سيرين الثاني", "محمد سيرين")])
    r = gold.NameIndex.from_rawi(p).resolve("محمد سيرين")
    assert r.rawi_id is None and r.ambiguous and sorted(r.candidates) == [1, 2]


def _idx(tmp_path):
    p = _rawi(tmp_path, [_row(1, "إبراهيم النخعي", "إبراهيم النخعي"),
                         _row(2, "أبو عبد الله الجدلي", "أبو عبد الله الجدلي"),
                         _row(3, "شعبة", "شعبة")])
    return gold.NameIndex.from_rawi(p)


def test_marasil_denials_shape(tmp_path):
    pairs = [{"student": "إبراهيم النخعي", "teacher": "أبي عبد الله الجدلي",
              "relation": "no_sama", "authority": "شعبة", "quote": "q"},
             {"student": "إبراهيم النخعي", "teacher": "النبي", "relation": "mursal",
              "authority": "x", "quote": "q"},
             {"student": "مجهول تماما", "teacher": "شعبة", "relation": "mursal",
              "authority": "x", "quote": "q"}]
    f = tmp_path / "m.json"
    f.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
    df = gold.marasil_denials(_idx(tmp_path), f)
    assert list(df.columns) == ["student", "teacher", "student_id", "teacher_id", "relation",
                                "authority", "resolved", "ambiguous", "method"]
    assert len(df) == 2 and df["resolved"].tolist() == [True, False]
    assert gold.denial_set([df]) == {(1, 2)}


def test_tuhfa_fake_runner(tmp_path):
    t = tmp_path / "t.parquet"
    pd.DataFrame([{"rawi_id": 1, "content": "لم يسمع من أبي عبد الله الجدلي"}]).to_parquet(t)
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return "\n".join([
            '{"student_id": 1, "teacher": "أبو عبد الله الجدلي", "relation": "no_sama", "quote": "لم يسمع"}',
            "garbage line {",
            '{"student_id": 1, "teacher": "شعبة", "relation": "sama", "quote": "x"}',
            '{"student_id": 99, "teacher": "شعبة", "relation": "mursal", "quote": "x"}',
        ])

    df = gold.tuhfa_denials(t, _idx(tmp_path), runner=fake)
    assert len(prompts) == 1 and "### 1" in prompts[0]
    assert list(df.columns) == ["student_id", "teacher", "teacher_id", "relation", "quote",
                                "resolved", "ambiguous", "method"]
    assert len(df) == 2 and df["resolved"].all()
    assert gold.denial_set([df]) == {(1, 2)}


def test_run_gold_denials_only_valid(tmp_path):
    rawi = _rawi(tmp_path, [_row(1, "إبراهيم النخعي", "إبراهيم النخعي"),
                            _row(2, "أبو عبد الله الجدلي", "أبو عبد الله الجدلي"),
                            _row(3, "شعبة", "شعبة"),
                            _row(4, "محمد سيرين الأول", "محمد سيرين"),
                            _row(5, "محمد سيرين الثاني", "محمد سيرين")])
    t = tmp_path / "t.parquet"
    pd.DataFrame([{"rawi_id": 1, "content": "x"}]).to_parquet(t)
    m = tmp_path / "m.json"
    m.write_text(json.dumps([
        {"student": "إبراهيم النخعي", "teacher": "أبو عبد الله الجدلي", "relation": "no_sama",
         "authority": "a", "quote": "q"},
        {"student": "إبراهيم النخعي", "teacher": "شعبة", "relation": "sama",
         "authority": "a", "quote": "q"},
        {"student": "إبراهيم النخعي", "teacher": "مجهول تماما", "relation": "mursal",
         "authority": "a", "quote": "q"},
        {"student": "إبراهيم النخعي", "teacher": "محمد سيرين", "relation": "mursal",
         "authority": "a", "quote": "q"}], ensure_ascii=False), encoding="utf-8")
    gold.run_gold(rawi, t, m, tmp_path, runner=lambda p: "")
    d = pd.read_parquet(tmp_path / "denials.parquet")
    assert [(int(a), int(b)) for a, b in zip(d.student_id, d.teacher_id)] == [(1, 2)]
    assert str(d.student_id.dtype) == "int64" and str(d.teacher_id.dtype) == "int64"
    assert len(pd.read_parquet(tmp_path / "denials_marasil.parquet")) == 4


def _frow(i, name, death=None, count=0, teachers=(), students=()):
    return {"rawi_id": i, "name": name, "abbrev": name, "name_forms": [],
            "death_year": death, "count": count,
            "teachers_ids": list(teachers), "students_ids": list(students)}


def _pidx(tmp_path, rows):
    return gold.NameIndex.from_rawi(_rawi(tmp_path, rows))


def test_candidates_sorted_and_thresholded(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "حمزة بن عبد الله"), _frow(2, "حمزة بن عبد الله"),
                           _frow(3, "شعبة بن الحجاج")])
    c = idx.candidates("حمزة بن عبد الله")
    assert [x.rawi_id for x in c] == [1, 2] and c[0].score >= c[1].score >= gold.ACCEPT


def test_resolve_pair_relation_breaks_homonym_tie(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "حمزة بن عبد الله", teachers=[3]),
                           _frow(2, "حمزة بن عبد الله"),
                           _frow(3, "شعبة بن الحجاج", students=[1])])
    r = gold.resolve_pair(idx, "حمزة بن عبد الله", "شعبة بن الحجاج")
    assert (r.student_id, r.teacher_id, r.method, r.ambiguous) == (1, 3, "relation", False)


def test_resolve_pair_prior_breaks_tie(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "حمزة بن عبد الله", count=3),
                           _frow(2, "حمزة بن عبد الله", count=500),
                           _frow(3, "شعبة بن الحجاج", count=10)])
    r = gold.resolve_pair(idx, "حمزة بن عبد الله", "شعبة بن الحجاج")
    assert (r.student_id, r.teacher_id, r.method, r.ambiguous) == (2, 3, "prior", False)


def test_resolve_pair_chronology_rejects_impossible(tmp_path):
    # teacher 3 has more narrations but died 80 years after the student: dropped
    idx = _pidx(tmp_path, [_frow(1, "إبراهيم النخعي", death=96, count=50),
                           _frow(2, "سعيد بن جبير", death=95, count=5),
                           _frow(3, "سعيد بن جبير", death=176, count=900)])
    r = gold.resolve_pair(idx, "إبراهيم النخعي", "سعيد بن جبير")
    assert (r.student_id, r.teacher_id, r.method) == (1, 2, "prior")


def test_resolve_pair_still_ambiguous(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "حمزة بن عبد الله", count=5, teachers=[3]),
                           _frow(2, "حمزة بن عبد الله", count=5, teachers=[3]),
                           _frow(3, "شعبة بن الحجاج", count=5, students=[1, 2])])
    r = gold.resolve_pair(idx, "حمزة بن عبد الله", "شعبة بن الحجاج")
    assert r.ambiguous and r.method == "ambiguous" and r.student_id is None
    assert sorted(c.rawi_id for c in r.s_candidates) == [1, 2]


def test_resolve_pair_no_candidates(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "شعبة بن الحجاج")])
    r = gold.resolve_pair(idx, "مجهول تماما", "شعبة بن الحجاج")
    assert (r.student_id, r.method, r.ambiguous) == (None, "none", False)


def test_resolve_pair_fixed_student(tmp_path):
    idx = _pidx(tmp_path, [_frow(1, "إبراهيم النخعي", teachers=[3]),
                           _frow(2, "سعيد بن جبير"), _frow(3, "سعيد بن جبير")])
    r = gold.resolve_pair(idx, None, "سعيد بن جبير", student_id=1)
    assert (r.student_id, r.teacher_id, r.method) == (1, 3, "relation")


def test_resolve_pair_relation_ignores_weak_name_match(tmp_path):
    # 2 is only a partial name match (score well below 1) but is linked to the teacher;
    # the exact match 1 must win via the prior, not the weak homonym via the relation.
    idx = _pidx(tmp_path, [_frow(1, "زيد بن أرقم", count=50),
                           _frow(2, "زيد بن ثابت", count=50, students=[3]),
                           _frow(3, "إبراهيم النخعي", teachers=[2], count=50)])
    r = gold.resolve_pair(idx, "إبراهيم النخعي", "زيد بن أرقم")
    assert (r.student_id, r.teacher_id, r.method) == (3, 1, "prior")


def test_run_gold_prints_method_breakdown(tmp_path, capsys):
    rawi = _rawi(tmp_path, [_frow(1, "إبراهيم النخعي"), _frow(2, "شعبة")])
    t = tmp_path / "t.parquet"
    pd.DataFrame([{"rawi_id": 1, "content": "x"}]).to_parquet(t)
    m = tmp_path / "m.json"
    m.write_text(json.dumps([{"student": "إبراهيم النخعي", "teacher": "شعبة",
                              "relation": "mursal", "authority": "a", "quote": "q"}],
                            ensure_ascii=False), encoding="utf-8")
    gold.run_gold(rawi, t, m, tmp_path, runner=lambda p: "")
    out = capsys.readouterr().out
    assert "marasil methods {'relation': 0, 'prior': 1, 'ambiguous': 0, 'none': 0}" in out
