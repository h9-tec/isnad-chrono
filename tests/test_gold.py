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
                                "authority", "resolved", "ambiguous"]
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
                                "resolved", "ambiguous"]
    assert len(df) == 2 and df["resolved"].all()
    assert gold.denial_set([df]) == {(1, 2)}
