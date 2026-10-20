import pandas as pd

from isnad.cli import main
from isnad.tree import REPORT_COLS, clean_chains, common_links, k_branches, merge_tree, partial_common_links, report_dates


def test_merge_two_chains_shared_prefix():
    t = merge_tree([[1, 2, 3, 10], [1, 2, 4, 11]])
    assert t.roots == [1]
    assert t.children[1] == {2} and t.children[2] == {3, 4}
    assert t.children[10] == set() and t.children[11] == set()
    assert t.depth == {1: 0, 2: 1, 3: 2, 4: 2, 10: 3, 11: 3}
    assert t.terminals == {10, 11}
    assert t.n_chains_through(2) == 2 and t.n_chains_through(3) == 1


def test_merge_several_roots_and_noise():
    # two companions -> two roots; consecutive duplicate rawi collapsed
    t = merge_tree([[1, 2, 2, 10], [5, 2, 11], []])
    assert t.roots == [1, 5] and len(t.chains) == 2
    assert t.component(1).chains == [(1, 2, 10)]
    assert t.component(5).depth == {5: 0, 2: 1, 11: 2}


def test_k_branches_counts_disjoint_children():
    t = merge_tree([[1, 2, 3, 10], [1, 2, 4, 11], [1, 2, 5, 12], [1, 2, 5, 13]])
    assert k_branches(t, 2) == 3  # 3, 4, 5 each reach a compiler
    assert k_branches(t, 5) == 2
    assert k_branches(t, 1) == 1
    assert k_branches(t, 10) == 0


def test_k_branches_compiler_mid_chain():
    # compiler 10 also narrates mid-chain to compiler 20
    t = merge_tree([[1, 2, 10], [1, 2, 10, 20], [1, 3, 30]])
    assert t.terminals == {10, 20, 30}
    assert k_branches(t, 10) == 1 and k_branches(t, 1) == 2
    assert common_links(t, 2) == [1]


def test_cl_k2_and_k3_differ():
    # root 1 -> 2 fans to 3 (single) and 4; 4 fans out three ways
    chains = [[1, 2, 3, 10], [1, 2, 4, 5, 11], [1, 2, 4, 6, 12], [1, 2, 4, 7, 13]]
    t = merge_tree(chains)
    assert common_links(t, 2) == [2]
    assert common_links(t, 3) == []  # 4 has 3 branches but misses compiler 10
    assert partial_common_links(t, 3) == [4]
    assert partial_common_links(t, 2) == [4]
    t3 = merge_tree(chains + [[1, 2, 8, 14]])
    assert common_links(t3, 3) == [2] and common_links(t3, 2) == [2]


def test_cl_tie_on_depth_picks_more_chains():
    # DAG: root has 2 branches (fails k=3); 2 and 3 tie at depth 1, each with 3 branches
    # covering every compiler; 3 carries more chains
    t = merge_tree([[0, 2, 4, 10], [0, 2, 5, 11], [0, 2, 6, 12], [0, 3, 4, 10], [0, 3, 5, 11],
                    [0, 3, 6, 12], [0, 3, 6, 12]])
    assert t.n_chains_through(3) == 4 and t.n_chains_through(2) == 3
    assert common_links(t, 3) == [3] and partial_common_links(t, 3) == [2]
    assert common_links(t, 2) == [0]


def test_single_chain_has_no_cl():
    t = merge_tree([[1, 2, 3, 10]])
    assert common_links(t, 2) == [] and common_links(t, 3) == []
    assert partial_common_links(t, 2) == []


def test_report_dates_uses_cl_interval():
    trees = {
        "g1": merge_tree([[1, 2, 3, 10], [1, 2, 4, 11], [1, 2, 4, 12], [1, 2, 5, 13]]),
        "g2": merge_tree([[7, 8, 9]]),
        "g3": merge_tree([]),
    }
    groups = pd.DataFrame({"group_id": ["g1", "g2", "g3"], "complete": [True, False, True]})
    dates = pd.DataFrame({"rawi_id": [2, 4], "death_lo": [90, 120], "death_hi": [100, 130]})
    df = report_dates(groups, trees, dates).set_index("group_id")
    g1 = df.loc["g1"]
    assert g1.root_id == 1 and g1.cl_k2_id == 2 and g1.cl_k3_id == 2
    assert (g1.cl_k2_date_lo, g1.cl_k2_date_hi) == (90, 100)
    assert g1.n_chains == 4 and g1.n_compilers == 4 and bool(g1.complete)
    g2 = df.loc["g2"]
    assert pd.isna(g2.cl_k2_id) and pd.isna(g2.cl_k2_date_lo) and g2.n_chains == 1
    g3 = df.loc["g3"]
    assert pd.isna(g3.root_id) and g3.n_chains == 0 and pd.isna(g3.cl_k3_date_hi)


def test_report_dates_date_method_and_flags():
    trees = {"g": merge_tree([[1, 2, 10], [1, 3, 11]]), "h": merge_tree([[5, 6, 7], [5, 6, 8]])}
    groups = pd.DataFrame({"group_id": ["g", "h"], "complete": [True, False],
                           "all_occurrences_have_chain": [False, True]})
    dates = pd.DataFrame({"rawi_id": [1, 6], "death_lo": [0, 50], "death_hi": [300, 60],
                          "method": ["prior_only", "known"]})
    df = report_dates(groups, trees, dates).set_index("group_id")
    assert df.loc["g", "cl_k2_date_method"] == "prior_only"
    assert df.loc["h", "cl_k2_date_method"] == "known" and pd.isna(df.loc["h", "cl_k3_date_method"])
    assert not df.loc["g", "all_occurrences_have_chain"] and df.loc["h", "all_occurrences_have_chain"]
    assert list(df.reset_index().columns) == REPORT_COLS


def test_report_dates_cl_without_date_row():
    trees = {"g": merge_tree([[1, 2, 10], [1, 3, 11]])}
    groups = pd.DataFrame({"group_id": ["g"], "complete": [False]})
    dates = pd.DataFrame({"rawi_id": [2], "death_lo": [90], "death_hi": [100]})
    r = report_dates(groups, trees, dates).iloc[0]
    assert r.cl_k2_id == 1 and pd.isna(r.cl_k2_date_lo) and pd.isna(r.cl_k3_id)


def _rows(hid, chains, unjoined=False):
    out = []
    for no, ch in enumerate(chains):
        for pos, r in enumerate(ch):
            out.append({"hadith_id": hid, "chain_no": no, "position": pos, "rawi_id": r,
                        "term": "عن", "unjoined": unjoined, "source": "html"})
    return out


def test_cli_tree(tmp_path, capsys):
    rows = (_rows(100, [[1, 2, 3, 10]]) + _rows(101, [[1, 2, 4, 11]])
            + _rows(102, [[1, 2, 5, 12]]) + _rows(103, [[6, 7, 13]])
            + _rows(104, [[1, 9, 14]], unjoined=True))
    pd.DataFrame(rows).to_parquet(tmp_path / "chains.parquet")
    pd.DataFrame({"group_id": ["a", "a", "a", "a", "b", "c"],
                  "hadith_id": [100, 101, 102, 103, 104, 200],
                  "book_slug": ["b-1"] * 6, "numbering": ["1"] * 6}
                 ).to_parquet(tmp_path / "occ.parquet")
    pd.DataFrame({"group_id": ["a", "b", "c"], "n_entries": [4, 1, 1], "n_chains": [4, 1, 1],
                  "books": [["b-1"]] * 3, "complete": [True, True, False]}
                 ).to_parquet(tmp_path / "groups.parquet")
    pd.DataFrame({"rawi_id": [2], "birth_lo": [0], "birth_hi": [10], "death_lo": [80],
                  "death_hi": [90], "death_mode": ["known"], "support": [3], "method": ["x"]}
                 ).to_parquet(tmp_path / "dates.parquet")
    pd.DataFrame({"group_id": ["a"], "companion_rawi_id": [None], "companion_name": ["x"],
                  "hadith_ids": [[100, 103, 999]]}).to_parquet(tmp_path / "shaw.parquet")
    main(["tree", "--chains", str(tmp_path / "chains.parquet"),
          "--occurrences", str(tmp_path / "occ.parquet"),
          "--groups", str(tmp_path / "groups.parquet"),
          "--dates", str(tmp_path / "dates.parquet"),
          "--shawahid", str(tmp_path / "shaw.parquet"), "--out-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "groups 3" in out and "k3_cl 1" in out and "multi_root 1" in out
    rd = pd.read_parquet(tmp_path / "report_dates.parquet")
    assert len(rd) == 4  # a has two roots; b (unjoined only) and c (no chains) one null row each
    a1 = rd[(rd.group_id == "a") & (rd.root_id == 1)].iloc[0]
    assert a1.cl_k3_id == 2 and a1.cl_k3_date_lo == 80 and a1.n_chains == 3
    assert rd[rd.group_id == "b"].iloc[0].n_chains == 0
    assert a1.cl_k3_date_method == "x"
    # a: every occurrence has a joined chain; b: only an unjoined chain; c: no chain at all
    flag = rd.groupby("group_id").all_occurrences_have_chain.first().to_dict()
    assert flag == {"a": True, "b": False, "c": False}
    assert rd.complete.tolist().count(False) == 1  # c, from groups.parquet
    assert "all_occurrences_have_chain 1" in out
    tn = pd.read_parquet(tmp_path / "tree_nodes.parquet")
    assert set(tn.group_id) == {"a"}
    n2 = tn[tn.rawi_id == 2].iloc[0]
    assert n2.is_cl_k2 and n2.is_cl_k3 and n2.k_branches == 3 and n2.depth == 1
    assert n2.n_descendant_chains == 3 and not n2.is_pcl_k2
    sc = pd.read_parquet(tmp_path / "shawahid_companions.parquet")
    assert sorted(sc.dropna().itertuples(index=False, name=None)) == [("a", 100, 1), ("a", 103, 6)]
    assert sc[sc.hadith_id == 999].companion_rawi_id.isna().all()


def test_repeated_narrator_truncates_chain():
    t = merge_tree([[1, 2, 3, 2, 10]])
    assert t.chains == [(1, 2, 3)] and t.n_truncated == 1
    assert common_links(t, 2) == [] and common_links(t, 3) == []
    t2 = merge_tree([[1, 2, 1, 10]])
    assert t2.chains == [(1, 2)] and common_links(t2, 2) == []
    assert k_branches(t, 2) == 1


def test_truncated_chain_too_short_dropped():
    t = merge_tree([[1, 1, 1], [5, 6, 5]])  # first collapses to (1,), kept; second -> (5, 6)
    assert t.chains == [(1,), (5, 6)] and t.n_truncated == 1


def test_cl_all_chains_flag():
    # tk-52101 shape: chain 4 reaches compiler 10 through 6, bypassing the k3 CL 2
    trees = {"g": merge_tree([[1, 2, 3, 10], [1, 2, 4, 11], [1, 2, 5, 12], [1, 6, 3, 10]])}
    groups = pd.DataFrame({"group_id": ["g"], "complete": [True]})
    dates = pd.DataFrame({"rawi_id": [], "death_lo": [], "death_hi": []})
    r = report_dates(groups, trees, dates).iloc[0]
    assert r.cl_k3_id == 2 and not r.cl_k3_all_chains
    assert r.cl_k2_id == 1 and r.cl_k2_all_chains
    single = report_dates(pd.DataFrame({"group_id": ["s"], "complete": [True]}),
                          {"s": merge_tree([[1, 2]])}, dates).iloc[0]
    assert pd.isna(single.cl_k2_all_chains)


def test_clean_chains_filter():
    kept, n = clean_chains([[1, 2, 2, 3], [], [4, 5, 4], [6, 6, 7, 6], [8]])
    assert kept == [(1, 2, 3), (4, 5), (6, 7), (8,)] and n == 2
    assert clean_chains(None) == ([], 0)
