"""Run site/tree.js (with the vendored d3) under node on a fixture group and check the layout.

Skips when ``node`` is not installed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[1] / "site"

# Root 10: 20 -> 30 in one chain and 30 -> 20 in another (a cycle); 20 -> 50 skips a layer
# under longest-path layering. Root 11 shares narrator 20 with root 10.
GROUP = {
    "id": "tk-1", "roots": [10, 11],
    "chains": [[10, 20, 30, 40], [10, 30, 20, 50], [10, 20, 50], [10, 60, 40], [11, 20, 70]],
    "nodes": [{"id": i, "root": 10, "depth": d, "k": 1, "n_desc": 1, "cl2": False, "cl3": False,
               "pcl2": False, "pcl3": False}
              for i, d in [(10, 0), (20, 1), (30, 1), (60, 1), (40, 2), (50, 2)]],
    "edits": {"by_node": {}}, "terms": {"10-20": "عن"},
}

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
globalThis.window = globalThis;
const [d3path, treepath, grouppath] = process.argv.slice(2);
vm.runInThisContext(fs.readFileSync(d3path, "utf8"), { filename: d3path });
vm.runInThisContext(fs.readFileSync(treepath, "utf8"), { filename: treepath });
const g = JSON.parse(fs.readFileSync(grouppath, "utf8"));
const lay = window.IsnadTree.layoutGroup(g, new Map());
const out = { components: [], missing: [] };
for (const c of lay.components) {
  const ids = new Set(c.nodes.map((n) => n.id));
  const linkKeys = new Set(c.links.map((l) => `${l.source.id}>${l.target.id}`));
  for (const ch of g.chains.filter((x) => x[0] === c.root)) {
    for (const id of ch) if (!ids.has(id)) out.missing.push([c.root, "node", id]);
    for (let i = 1; i < ch.length; i++)
      if (!linkKeys.has(`${ch[i - 1]}>${ch[i]}`)) out.missing.push([c.root, "edge", ch[i - 1], ch[i]]);
  }
  out.components.push({
    root: c.root,
    links: c.links.map((l) => ({ a: l.source.id, b: l.target.id, ya: l.source.y, yb: l.target.y,
                                 back: l.back, tree: l.tree })),
  });
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def layout(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    d = tmp_path_factory.mktemp("layout")
    (d / "run.js").write_text(SCRIPT, encoding="utf-8")
    (d / "group.json").write_text(json.dumps(GROUP, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([node, str(d / "run.js"), str(SITE / "vendor/d3.v7.min.js"),
                        str(SITE / "tree.js"), str(d / "group.json")],
                       capture_output=True, text=True, timeout=60, check=True)
    return json.loads(r.stdout)


def test_every_chain_is_embedded(layout):
    assert {c["root"] for c in layout["components"]} == {10, 11}
    assert layout["missing"] == []


def test_edges_go_down_unless_back(layout):
    links = [l for c in layout["components"] for l in c["links"]]
    bad = [l for l in links if not l["back"] and l["yb"] <= l["ya"]]
    assert bad == []
    # the 20 <-> 30 cycle forces exactly one back edge; the rest point down
    assert sum(l["back"] for l in links) == 1
