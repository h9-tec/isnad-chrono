import json

import numpy as np
import pandas as pd

from isnad.cli import main
from isnad.dating import build_links, chain_depth, holdout, propagate


def nar(rows):
    """rows: (rawi_id, death_year|None, birth_year|None[, generation_num])."""
    out = []
    for r in rows:
        rid, d, b = r[:3]
        out.append({"rawi_id": rid,
                    "death_year": np.nan if d is None else float(d),
                    "death_sd": np.nan if d is None else 1.0,
                    "death_kind": "none" if d is None else "exact",
                    "birth_year": np.nan if b is None else float(b),
                    "birth_sd": np.nan if b is None else 1.0,
                    "birth_kind": "none" if b is None else "exact",
                    "generation_num": r[3] if len(r) > 3 else np.nan,
                    "is_companion": False})
    return pd.DataFrame(out)


def lk(rows):
    """rows: (teacher_id, student_id, weight, cls)."""
    return pd.DataFrame(rows, columns=["teacher_id", "student_id", "weight", "cls"])


def row(df, rid):
    return df.set_index("rawi_id").loc[rid]


def test_link_tightens_birth_and_death():
    iv, dropped = propagate(nar([(1, 100, None), (2, None, None)]), lk([(1, 2, 3, "explicit")]))
    s, t = row(iv, 2), row(iv, 1)
    assert s.birth_hi == 94  # teacher death_hi (100 + 2*1) - A0
    assert s.death_hi == 194  # birth_hi + AGE_MAX
    assert (t.death_lo, t.death_hi) == (98, 102)
    assert s.method == "inferred" and t.method == "known"
    assert s.support == 1 and t.support == 1 and dropped.empty


def test_chain_of_three_propagates():
    # top-down: A known -> B -> C
    iv, _ = propagate(nar([(1, 100, None), (2, None, None), (3, None, None)]),
                      lk([(1, 2, 1, "explicit"), (2, 3, 1, "explicit")]))
    assert row(iv, 2).birth_hi == 94 and row(iv, 3).birth_hi == 186 and row(iv, 3).death_hi == 286
    # bottom-up: A -> B -> C known death 300 (birth >= 198) lifts the teachers' deaths
    iv, _ = propagate(nar([(1, None, None), (2, None, None), (3, 300, None)]),
                      lk([(1, 2, 1, "explicit"), (2, 3, 1, "explicit")]))
    assert row(iv, 2).death_lo == 206 and row(iv, 1).death_lo == 114
    assert row(iv, 1).death_mode == (114 + row(iv, 1).death_hi) / 2


def test_negative_cycle_drops_weakest_link():
    # T died ~100; S1 born ~120 cannot have heard from T; S2 born ~93 can.
    # The ambiguous link is dropped even though it is heavier than the explicit one.
    n = nar([(1, 100, None), (2, None, 120), (3, None, 93)])
    iv, dropped = propagate(n, lk([(1, 2, 5, "ambiguous"), (1, 3, 1, "explicit")]))
    assert list(zip(dropped.teacher_id, dropped.student_id)) == [(1, 2)]
    assert set(dropped.reason) == {"negative_cycle"} and "round" in dropped
    t = row(iv, 1)
    assert (t.death_lo, t.death_hi) == (99, 102) and t.support == 1
    assert row(iv, 2).support == 0 and row(iv, 2).birth_lo == 118


def test_drop_targets_the_binding_link():
    # Ibn Umar (d. 72) -> Nafi (d. 116), heavy ambiguous; Nafi -> X (born ~200) is a light
    # explicit misresolution. Only the Nafi -> X link made Nafi infeasible, so it goes.
    n = nar([(1, 72, None), (2, 116, None), (3, None, 200)])
    iv, dropped = propagate(n, lk([(1, 2, 168, "ambiguous"), (2, 3, 1, "explicit")]))
    assert list(zip(dropped.teacher_id, dropped.student_id)) == [(2, 3)]
    assert row(iv, 2).support == 1 and row(iv, 2).birth_hi == 66


def test_explicit_dropped_only_when_no_ambiguous_left():
    n = nar([(1, 100, None), (2, None, 120)])
    iv, dropped = propagate(n, lk([(1, 2, 9, "explicit")]))
    assert list(zip(dropped.teacher_id, dropped.student_id)) == [(1, 2)]
    assert row(iv, 1).death_hi == 102


def test_isolated_narrator_prior_only():
    iv, _ = propagate(nar([(1, 100, None), (2, None, None), (7, None, None)]),
                      lk([(1, 2, 1, "explicit")]))
    r = row(iv, 7)
    assert r.support == 0 and r.method == "prior_only"
    # priors (death [0, 1500], birth [-100, 1500]) closed only under the lifespan bounds
    assert (r.birth_lo, r.birth_hi, r.death_lo, r.death_hi) == (-100, 1480, 0, 1500)


def test_early_death_feasible_without_birth():
    # an early Companion (died 13 AH) needs a pre-Hijra birth; no link may be dropped for it
    iv, dropped = propagate(nar([(1, 13, None), (2, None, None)]), lk([(1, 2, 1, "ambiguous")]))
    assert dropped.empty and row(iv, 1).death_hi == 15 and row(iv, 1).birth_lo == -89


def test_build_links_weight_majority_and_unjoined():
    ch = pd.DataFrame({
        "hadith_id": [1, 1, 1, 2, 2, 3, 3, 4, 4],
        "chain_no": [0] * 9,
        "position": [0, 1, 2, 0, 1, 0, 1, 0, 1],
        "rawi_id": [10, 20, 30, 10, 20, 10, 20, 40, 50],
        "term": ["عن", "حدثنا", None, "حدثنا", None, "عن", None, "حدثنا", None],
        "unjoined": [False] * 7 + [True, True],
        "source": ["html"] * 9,
    })
    links = build_links(ch).set_index(["teacher_id", "student_id"])
    assert set(links.index) == {(10, 20), (20, 30)}  # unjoined chain 4 dropped
    assert links.loc[(10, 20), "weight"] == 3
    assert links.loc[(10, 20), "cls"] == "ambiguous"  # 2 ambiguous vs 1 explicit
    assert links.loc[(20, 30), "cls"] == "explicit"


def test_holdout_returns_metrics_keys():
    rows, links = [], []
    for c in range(30):  # 30 three-link chains with known deaths roughly a generation apart
        base = 10 * c
        ids = [base + i for i in range(4)]
        for i, rid in enumerate(ids):
            rows.append((rid, 40 + 30 * i + c % 5, None, 1.0 if i == 0 else np.nan))
        links += [(ids[i], ids[i + 1], 1, "explicit") for i in range(3)]
    n, lks = nar(rows), lk(links)
    depth = {rid: float(i) for c in range(30) for i, rid in enumerate(range(10 * c, 10 * c + 4))}
    m = holdout(n, lks, folds=5, seed=0, depth=depth)
    for k in ("method", "depth", "generation"):
        assert {"median_abs_error", "coverage_90", "n"} <= set(m[k])
    assert m["folds"] == 5 and m["method"]["n"] > 0
    assert m["depth"]["median_abs_error"] < 30


def test_cli_dating(tmp_path):
    ch = pd.DataFrame({"hadith_id": [1, 1, 1], "chain_no": [0, 0, 0], "position": [0, 1, 2],
                       "rawi_id": [1, 2, 3], "term": ["حدثنا", "عن", None],
                       "unjoined": [False] * 3, "source": ["html"] * 3})
    ch.to_parquet(tmp_path / "c.parquet")
    nar([(1, 100, None), (2, None, None), (3, 150, None)]).to_parquet(tmp_path / "r.parquet")
    main(["dating", "--chains", str(tmp_path / "c.parquet"), "--rawi", str(tmp_path / "r.parquet"),
          "--out", str(tmp_path / "o.parquet"), "--dropped", str(tmp_path / "d.parquet"),
          "--holdout", str(tmp_path / "h.json")])
    out = pd.read_parquet(tmp_path / "o.parquet")
    assert set(out.columns) >= {"rawi_id", "birth_lo", "birth_hi", "death_lo", "death_hi",
                                "death_mode", "support", "method"}
    assert row(out, 2).method == "inferred"
    assert "method" in json.loads((tmp_path / "h.json").read_text())
    assert pd.read_parquet(tmp_path / "d.parquet").empty



def test_build_links_and_depth_skip_truncated_tail(tmp_path):
    # Muslim 17428 parsed from the fixture, then each chain doubled (an isnad parsed twice and
    # concatenated): the repeat truncates the chain, as tree.merge_tree does, so no link may come
    # from the tail (no back edge compiler -> Companion) and depths stay those of the clean chain.
    import shutil

    from isnad.chains import chains_table
    from tests.conftest import FIXTURES

    (tmp_path / "hadith").mkdir()
    shutil.copy(FIXTURES / "hadith_muslim_17428_repeat.html.gz",
                tmp_path / "hadith" / "17428.html.gz")
    ch = chains_table(tmp_path)
    clean = build_links(ch)
    n = ch.groupby(["hadith_id", "chain_no"]).position.transform("size")
    doubled = pd.concat([ch, ch.assign(position=ch.position + n, term="عن")],
                        ignore_index=True)
    links = build_links(doubled)
    pairs = set(zip(links.teacher_id, links.student_id))
    assert pairs == set(zip(clean.teacher_id, clean.student_id)) and len(pairs) == 7
    assert (6116, 3856) not in pairs
    assert links.weight.tolist() == clean.weight.tolist()
    assert links.cls.tolist() == clean.cls.tolist()
    assert chain_depth(doubled) == chain_depth(ch) and chain_depth(doubled)[6116] == 5


def test_build_links_collapses_consecutive_duplicate_keeping_adjacent_term():
    ch = pd.DataFrame({"hadith_id": [1] * 4, "chain_no": [0] * 4, "position": [0, 1, 2, 3],
                       "rawi_id": [10, 20, 20, 30], "term": ["عن", "عن", "حدثنا", None],
                       "unjoined": [False] * 4, "source": ["html"] * 4})
    links = build_links(ch).set_index(["teacher_id", "student_id"])
    assert set(links.index) == {(10, 20), (20, 30)}
    assert links.loc[(20, 30), "cls"] == "explicit"
    assert chain_depth(ch) == {10: 0, 20: 1, 30: 2}
