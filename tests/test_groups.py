import gzip

import pandas as pd

from isnad.build import read_page
from isnad.cli import main
from isnad.groups import hash_text, parse_group
from isnad.pageprops import extract
from tests.conftest import FIXTURES


def rec():
    return parse_group(extract(read_page(FIXTURES / "hadith_muslim_11563.html"))["hadith"])


def test_group_fixture():
    g = rec()
    assert g.group_id == "tk-28092" and g.n_entries == 12 and g.n_chains == 19
    assert [s.kind for s in g.segments] == ["base", "substitution"] * 3 + ["base"]
    assert g.segments[1].carrier_hadith_ids == [171551, 171618, 308649, 180874]
    assert g.segments[1].base_hash == g.segments[0].base_hash
    assert (11563, "b-2", "1") in g.occurrences
    assert g.shawahid and all(isinstance(ids, list) for _, ids in g.shawahid)


def test_hash_text():
    h = hash_text("مَنْ  حَدَّثَ")
    assert len(h) == 16 and h == hash_text("من حدث") and h == hash_text(" من\nحدث ")


def test_no_group():
    assert parse_group({}) is None


def _run(tmp_path, ids):
    src = (FIXTURES / "hadith_muslim_11563.html").read_text(encoding="utf-8")
    d = tmp_path / "raw" / "hadith"
    d.mkdir(parents=True)
    for i, hid in enumerate(ids):
        if i % 2:
            with gzip.open(d / f"{hid}.html.gz", "wt", encoding="utf-8") as f:
                f.write(src)
        else:
            (d / f"{hid}.html").write_text(src, encoding="utf-8")
    out = tmp_path / "out"
    main(["groups", "--cache-root", str(tmp_path / "raw"), "--out-dir", str(out),
          "--rawi", str(tmp_path / "none.parquet")])
    return out


def test_group_dedup_and_complete(tmp_path):
    out = _run(tmp_path, [11563, 11564])
    g = pd.read_parquet(out / "groups.parquet")
    assert list(g["group_id"]) == ["tk-28092"] and not g["complete"][0]
    seg = pd.read_parquet(out / "segments.parquet")
    assert len(seg) == 7 and set(seg.columns).isdisjoint({"text", "base_text", "variant_text"})
    txt = pd.read_parquet(out / "text" / "segments_text.parquet")
    hashes = set(seg["base_hash"].dropna()) | set(seg["variant_hash"].dropna())
    assert hashes <= set(txt["hash"]) and all(hash_text(t) == h for h, t in zip(txt["hash"], txt["text"]))


def test_group_complete_when_all_cached(tmp_path):
    occ = [o[0] for o in rec().occurrences]
    out = _run(tmp_path, occ)
    g = pd.read_parquet(out / "groups.parquet")
    assert len(g) == 1 and bool(g["complete"][0])
    assert len(pd.read_parquet(out / "occurrences.parquet")) == len(occ)


def _mk(n_segs, variant="x"):
    from isnad.groups import Segment
    segs = [Segment(i, "base", hash_text(f"b{i}{variant}"), None, [], f"b{i}{variant}", None)
            for i in range(n_segs)]
    from isnad.groups import GroupRecord
    return GroupRecord("tk-1", 1, 1, ["b-1"], [(1, "b-1", "1")], segs, [], [])


def _sink(tmp_path, recs):
    from isnad.groups import _Sink
    s = _Sink(tmp_path, {1})
    for r in recs:
        s.add(r)
    s.close()
    return s.stats, pd.read_parquet(tmp_path / "segments.parquet")


def test_dedup_shorter_later_first_wins(tmp_path):
    st, seg = _sink(tmp_path, [_mk(3), _mk(2)])
    assert st["segment discrepancies"] == 1 and st["groups"] == 1 and len(seg) == 3
    assert st["discrepancy longer later (ignored)"] == 0


def test_dedup_longer_later_ignored(tmp_path):
    st, seg = _sink(tmp_path, [_mk(2), _mk(3)])
    assert st["segment discrepancies"] == 1 and len(seg) == 2
    assert st["discrepancy longer later (ignored)"] == 1


def test_dedup_tie_first_wins(tmp_path):
    st, seg = _sink(tmp_path, [_mk(2, "x"), _mk(2, "y")])
    txt = pd.read_parquet(tmp_path / "text" / "segments_text.parquet")
    assert st["segment discrepancies"] == 1 and len(seg) == 2
    assert set(txt["text"]) == {"b0x", "b1x"}


def test_identical_duplicate_no_discrepancy(tmp_path):
    st, seg = _sink(tmp_path, [_mk(2), _mk(2)])
    assert st["segment discrepancies"] == 0 and len(seg) == 2


def test_chunked_flush(tmp_path):
    from isnad.groups import SCHEMAS, _Chunked
    c = _Chunked(tmp_path / "o.parquet", SCHEMAS["occurrences"], chunk=2)
    for i in range(5):
        c.add(dict(group_id="g", hadith_id=i, book_slug="b", numbering="1"))
    c.close()
    assert len(pd.read_parquet(tmp_path / "o.parquet")) == 5
