// Layout + drawing of a group's merged transmission graph (one drawing per root).
//
// The export's `depth` is a shortest-path (BFS) depth in a DAG, so it is not
// parent depth + 1 along every chain. We therefore build the graph from the
// chains themselves (edges = consecutive pairs, teacher -> student), pick a
// spanning tree whose parent of each node is the first predecessor met on any
// chain with depth == node depth - 1 (one always exists for a BFS depth), lay
// that tree out with d3.tree (so y = depth), and then draw ALL chain edges;
// edges outside the spanning tree are thinner curves with an arrowhead.
(function () {
  "use strict";

  const NODE_W = 180; // horizontal slot per node (px)
  const LAYER_H = 100; // vertical distance between depths (px)
  const PAD_TOP = 48;
  const PAD_BOTTOM = 56;
  const GAP = 80; // between components
  const LABEL_DY = 46; // below name + interval lines
  const COLORS = { known: "#2a9d8f", inferred: "#e9c46a", prior_only: "#999999" };
  const EDIT_STATUSES = new Set(["attributed", "ambiguous"]);

  function intervalText(lo, hi) {
    if (lo == null && hi == null) return "";
    // LTR isolate so the range reads lo–hi inside RTL text (else bidi flips it).
    return `ت \u2066${lo ?? "?"}–${hi ?? "?"}\u2069`;
  }

  function truncate(s, n) {
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function layoutGroup(group, narrators) {
    narrators = narrators || new Map();
    const byKey = new Map();
    for (const n of group.nodes || []) byKey.set(`${n.root}:${n.id}`, n);
    const byNode = (group.edits && group.edits.by_node) || {};
    const terms = group.terms || {};
    const components = [];

    for (const root of group.roots || []) {
      const chains = (group.chains || []).filter((c) => c[0] === root);
      const depthOf = (id) => {
        const n = byKey.get(`${root}:${id}`);
        return n ? n.depth : null;
      };
      const edges = new Map(); // "a>b" -> {a, b, n}
      const order = new Map([[root, 0]]); // id -> first appearance
      const parent = new Map();
      for (const ch of chains) {
        for (const id of ch) if (!order.has(id)) order.set(id, order.size);
        for (let i = 1; i < ch.length; i++) {
          const a = ch[i - 1];
          const b = ch[i];
          const key = `${a}>${b}`;
          const e = edges.get(key);
          if (e) e.n++;
          else edges.set(key, { a, b, n: 1 });
          if (b !== root && !parent.has(b)) {
            const da = depthOf(a);
            const db = depthOf(b);
            if (da != null && db != null && da === db - 1) parent.set(b, a);
          }
        }
      }
      // Defensive fallback (does not trigger on a valid BFS depth): attach to
      // a strictly shallower predecessor, else to the root; never makes a cycle.
      for (const id of order.keys()) {
        if (id === root || parent.has(id)) continue;
        const d = depthOf(id);
        const e = [...edges.values()].find(
          (e) => e.b === id && d != null && depthOf(e.a) != null && depthOf(e.a) < d
        );
        parent.set(id, e ? e.a : root);
      }

      const kids = new Map();
      for (const id of order.keys()) {
        if (id === root) continue;
        const p = parent.get(id);
        if (!kids.has(p)) kids.set(p, []);
        kids.get(p).push(id);
      }
      for (const arr of kids.values()) arr.sort((x, y) => order.get(x) - order.get(y));

      const h = d3.hierarchy(root, (id) => kids.get(id));
      d3.tree()
        .nodeSize([NODE_W, LAYER_H])
        .separation((a, b) => (a.parent === b.parent ? 1 : 1.15))(h);

      let minX = Infinity;
      let maxX = -Infinity;
      let maxDepth = 0;
      h.each((d) => {
        minX = Math.min(minX, d.x);
        maxX = Math.max(maxX, d.x);
      });
      const nodes = new Map();
      h.each((d) => {
        const id = d.data;
        const src = byKey.get(`${root}:${id}`) || { id, root, depth: d.depth, k: 0, n_desc: 0 };
        const depth = src.depth ?? d.depth;
        maxDepth = Math.max(maxDepth, depth);
        const info = narrators.get(id) || null;
        const edits = byNode[String(id)] || [];
        nodes.set(id, {
          ...src,
          id,
          // RTL: the first chain is drawn on the right.
          x: maxX - d.x + NODE_W / 2,
          y: depth * LAYER_H,
          info,
          name: info ? info.name : `p-${id}`,
          placeholder: !!(info && info.placeholder),
          method: info ? info.method : null,
          interval: info ? intervalText(info.dlo, info.dhi) : "",
          edits,
          nEdits: edits.filter((e) => EDIT_STATUSES.has(e.status)).length,
        });
      });
      const links = [...edges.values()].map((e) => ({
        source: nodes.get(e.a),
        target: nodes.get(e.b),
        term: terms[`${e.a}-${e.b}`] || null,
        n: e.n,
        tree: parent.get(e.b) === e.a,
      }));
      components.push({
        root,
        width: maxX - minX + NODE_W,
        height: maxDepth * LAYER_H + PAD_TOP + PAD_BOTTOM,
        maxLayer: Math.max(...d3.rollup([...nodes.values()], (v) => v.length, (n) => n.depth).values()),
        nChains: chains.length,
        nodes: [...nodes.values()],
        links,
      });
    }

    // Largest component (most chains) first; stable for ties, so roots order otherwise.
    components.sort((a, b) => b.nChains - a.nChains);
    // RTL: first component on the right.
    const width = components.reduce((s, c) => s + c.width, 0) + GAP * Math.max(0, components.length - 1);
    let right = width;
    for (const c of components) {
      c.x0 = right - c.width;
      right = c.x0 - GAP;
    }
    const height = Math.max(0, ...components.map((c) => c.height));
    return { components, width, height };
  }

  function bend(s, t) {
    // Quadratic curve bulging to one side; works for same-layer and upward edges.
    const dx = t.x - s.x;
    const dy = t.y - s.y;
    const len = Math.hypot(dx, dy) || 1;
    const off = Math.max(28, len * 0.2);
    const cx = (s.x + t.x) / 2 - (dy / len) * off;
    const cy = (s.y + t.y) / 2 + (dx / len) * off;
    return `M${s.x},${s.y}Q${cx},${cy} ${t.x},${t.y}`;
  }

  function nodeTitle(n) {
    const i = n.info;
    if (!i) return `p-${n.id} (غير موجود في الفهرس)`;
    const lines = [i.name];
    if (i.kunya) lines.push(i.kunya);
    if (i.dy != null) lines.push(`الوفاة المسجلة: ${i.dy}${i.dk ? ` (${i.dk})` : ""}`);
    if (i.by != null) lines.push(`الولادة المسجلة: ${i.by}${i.bk ? ` (${i.bk})` : ""}`);
    if (n.interval) lines.push(`الوفاة المقدرة: \u2066${i.dlo ?? "?"}–${i.dhi ?? "?"}\u2069 هـ (${i.method})`);
    lines.push(`عدد الأسانيد: ${i.n_chains ?? 0}`);
    return lines.join("\n");
  }

  function drawGroup(svgSel, layout, opts) {
    opts = opts || {};
    const scale = opts.scale || 1;
    const cl = opts.cl || {};
    const W = Math.max(layout.width, 1);
    const H = Math.max(layout.height, 1);
    svgSel.selectAll("*").remove();
    svgSel
      .attr("viewBox", `0 0 ${W} ${H}`)
      .attr("width", W * scale)
      .attr("height", H * scale);

    svgSel
      .append("defs")
      .append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 17)
      .attr("refY", 5)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto-start-reverse")
      .append("path")
      .attr("d", "M0,0L10,5L0,10z")
      .attr("class", "arrowhead");

    const vlink = d3.linkVertical().x((d) => d.x).y((d) => d.y);

    for (const comp of layout.components) {
      const g = svgSel
        .append("g")
        .attr("class", "component")
        .attr("data-root", comp.root)
        .attr("transform", `translate(${comp.x0},${PAD_TOP})`);

      const lg = g.append("g").attr("class", "links");
      const link = lg
        .selectAll("g.link")
        .data(comp.links)
        .join("g")
        .attr("class", (d) => (d.tree ? "link tree" : "link extra"));
      // Tree links start below the source's two label lines so they do not cross them.
      const pathOf = (d) =>
        d.tree
          ? vlink({ source: { x: d.source.x, y: d.source.y + LABEL_DY }, target: d.target })
          : bend(d.source, d.target);
      link
        .append("path")
        .attr("class", "edge")
        .attr("d", pathOf)
        .attr("stroke-width", (d) => (d.tree ? 1.2 + Math.log2(d.n) : 1))
        .attr("marker-end", (d) => (d.tree ? null : "url(#arrow)"));
      link
        .append("path")
        .attr("class", "hit")
        .attr("d", pathOf)
        .append("title")
        .text(
          (d) =>
            `الشيخ: ${d.source.name}\nالتلميذ: ${d.target.name}\n` +
            `${d.term ? `الصيغة: ${d.term}` : "الصيغة غير معروفة"} · ${d.n} سند`
        );

      const node = g
        .append("g")
        .attr("class", "nodes")
        .selectAll("g.node")
        .data(comp.nodes)
        .join("g")
        .attr("class", (d) => `node${d.placeholder ? " placeholder" : ""}${d.info ? "" : " unknown"}`)
        .attr("data-id", (d) => d.id)
        .attr("transform", (d) => `translate(${d.x},${d.y})`)
        .on("click", (ev, d) => opts.onNode && opts.onNode(d, comp));
      node.append("title").text(nodeTitle);

      // Common-link rings: k2 -> one ring (double), k3 -> two rings (triple);
      // partial common links dashed.
      node
        .filter((d) => d.cl2 || d.cl3 || d.pcl2 || d.pcl3)
        .append("circle")
        .attr("r", 11)
        .attr("class", (d) => `ring${d.cl2 || d.cl3 ? "" : " partial"}`);
      node
        .filter((d) => d.cl3 || d.pcl3)
        .append("circle")
        .attr("r", 15)
        .attr("class", (d) => `ring${d.cl3 ? "" : " partial"}`);
      node
        .append("circle")
        .attr("r", 7)
        .attr("class", "dot")
        .attr("fill", (d) => (d.placeholder ? "#dddddd" : d.info ? COLORS[d.method] || "#bbbbbb" : "#ffffff"));

      node
        .append("text")
        .attr("class", "name")
        .attr("y", 26)
        .text((d) => truncate(d.name, 22));
      node
        .append("text")
        .attr("class", "interval")
        .attr("y", 41)
        .text((d) => d.interval);

      // CL badge above the node.
      const badge = node.filter((d) => d.cl2 || d.cl3);
      badge.each(function (d) {
        const ks = [];
        let lo = d.info ? d.info.dlo : null;
        let hi = d.info ? d.info.dhi : null;
        for (const k of ["k2", "k3"]) {
          if (d[`cl${k[1]}`]) {
            ks.push(k);
            if (cl[k] && cl[k].id === d.id) {
              lo = cl[k].lo;
              hi = cl[k].hi;
            }
          }
        }
        const label = `CL ${ks.join("/")} · ${intervalText(lo, hi) || "ت ؟"}`;
        const bg = d3.select(this).append("g").attr("class", "cl-badge").attr("transform", "translate(0,-30)");
        const w = label.length * 6.4 + 12;
        bg.append("rect").attr("x", -w / 2).attr("y", -9).attr("width", w).attr("height", 17).attr("rx", 8);
        bg.append("text").attr("y", 4).text(label);
      });

      // Edit pill: number of wording changes introduced (attributed or ambiguous).
      const pill = node
        .filter((d) => d.nEdits > 0)
        .append("g")
        .attr("class", "edit-pill")
        .attr("transform", (d) => `translate(${d.cl3 || d.pcl3 ? -28 : d.cl2 || d.pcl2 ? -24 : -18},0)`);
      pill.append("rect").attr("x", -10).attr("y", -8).attr("width", 20).attr("height", 15).attr("rx", 7);
      pill.append("text").attr("y", 4).text((d) => d.nEdits);
      pill
        .append("title")
        .text(
          (d) =>
            `${d.nEdits} تغيير في اللفظ\n` +
            d.edits.map((e) => `مقطع ${e.seg}: ${e.type} (${e.status})`).join("\n")
        );
    }
    return svgSel;
  }

  window.IsnadTree = { layoutGroup, drawGroup, intervalText, NODE_W, LAYER_H };
})();
