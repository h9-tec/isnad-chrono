// Atlas: common-link date histogram (with compiler filter), drift curve, coverage table.
(function () {
  "use strict";
  const { esc, int, fillChecks, sortableTable } = window.ISNADUI;
  const sel = document.getElementById("book");
  const histEl = document.getElementById("hist");
  const sumEl = document.getElementById("hist-sum");
  const driftEl = document.getElementById("drift");
  const short = d3.format("~s");

  function width(el) {
    return Math.max(300, Math.min(el.clientWidth || 900, 1200));
  }

  function drawHist(atlas, slug, title) {
    const all = atlas.cl_hist.all || [];
    let data = atlas.cl_hist[slug] || [];
    const W = width(histEl);
    const H = 280;
    const m = { t: 12, r: 16, b: 40, l: 52 };
    // Same year axis for every compiler so the filters compare.
    // The axis ends at the bin holding 99% of all groups; the sparse tail is
    // counted in the summary line instead of stretching the axis.
    const x0 = d3.min(all, (d) => d[0]) ?? 0;
    const total = d3.sum(all, (d) => d[1]);
    let acc = 0;
    let cut = x0;
    for (const [b, c] of all) {
      cut = b;
      acc += c;
      if (acc >= total * 0.99) break;
    }
    const x1 = cut + 10;
    const tail = data.filter((d) => d[0] >= x1);
    data = data.filter((d) => d[0] < x1);
    const x = d3.scaleLinear().domain([x0, x1]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, d3.max(data, (d) => d[1]) || 1]).nice().range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", "100%")
      .attr("role", "img").attr("aria-label", `توزيع سنوات وفاة الحلقة المشتركة: ${title}`);
    svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").selectAll("rect").data(data).join("rect").attr("class", "hbar")
      .attr("x", (d) => x(d[0]) + 0.5).attr("width", (d) => Math.max(1, x(d[0] + 10) - x(d[0]) - 1))
      .attr("y", (d) => y(d[1])).attr("height", (d) => y(0) - y(d[1]))
      .append("title").text((d) => `${d[0]}–${d[0] + 9} هـ: ${d[1]} مجموعة`);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).ticks(Math.floor(W / 70)).tickFormat(d3.format("d")));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5));
    svg.append("text").attr("class", "axis-label").attr("x", W / 2).attr("y", H - 4).attr("text-anchor", "middle")
      .text("سنة الوفاة المقدرة (هـ) · inferred death year AH");
    histEl.replaceChildren(svg.node());
    const nTail = d3.sum(tail, (d) => d[1]);
    const n = d3.sum(data, (d) => d[1]) + nTail;
    const peak = data.reduce((a, b) => (b[1] > (a ? a[1] : -1) ? b : a), null);
    sumEl.innerHTML = n
      ? `${esc(title)}: ${int(n)} مجموعة لها حلقة مشتركة مؤرخة${peak ? `؛ الذروة <bdi dir="ltr">${peak[0]}–${peak[0] + 9}</bdi> هـ (${int(peak[1])})` : ""}.
${nTail ? ` منها ${int(nTail)} بعد ${x1} هـ (خارج الرسم).` : ""}
         <span class="en">${int(n)} groups with a dated k2 common link${nTail ? `; ${int(nTail)} after ${x1} AH are not drawn` : ""}.</span>`
      : `${esc(title)}: لا مجموعات.`;
  }

  function drawDrift(drift) {
    const rows = drift.filter((r) => r.rate != null);
    const W = width(driftEl);
    const H = 300;
    const m = { t: 16, r: 20, b: 58, l: 52 };
    const x = d3.scaleLinear().domain(d3.extent(rows, (r) => r.depth)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, d3.max(rows, (r) => Math.max(r.rate, r.rate_nonleaf ?? 0)) || 1]).nice()
      .range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", "100%")
      .attr("role", "img").attr("aria-label", "معدل تغييرات اللفظ لكل نقل حسب العمق");
    svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat(""));
    const xa = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).tickValues(rows.map((r) => r.depth)).tickFormat(d3.format("d")));
    // n (transmissions) under each depth tick.
    xa.selectAll(".tick").append("text").attr("class", "n-label").attr("y", 30).attr("fill", "currentColor")
      .text((d) => {
        const r = rows.find((q) => q.depth === d);
        return r ? `n=${short(r.n_transmissions)}` : "";
      });
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(".0%")));
    svg.append("text").attr("class", "axis-label").attr("x", W / 2).attr("y", H - 4).attr("text-anchor", "middle")
      .text("العمق من الصحابي · depth from the Companion (n = transmissions)");
    const series = [
      { key: "rate", cls: "line-all", label: "كل التغييرات · all edits" },
      { key: "rate_nonleaf", cls: "line-nonleaf", label: "دون تغييرات المصنف · non-leaf" },
    ];
    for (const s of series) {
      const pts = rows.filter((r) => r[s.key] != null);
      svg.append("path").datum(pts).attr("class", `line ${s.cls}`)
        .attr("d", d3.line().x((r) => x(r.depth)).y((r) => y(r[s.key])));
      svg.append("g").selectAll("circle").data(pts).join("circle").attr("class", `pt ${s.cls}`)
        .attr("cx", (r) => x(r.depth)).attr("cy", (r) => y(r[s.key])).attr("r", 3.5)
        .append("title").text((r) => `العمق ${r.depth}: ${(r[s.key] * 100).toFixed(2)}% (${s.key === "rate" ? r.n_edits : r.n_edits_nonleaf} / ${r.n_transmissions})`);
    }
    const lg = svg.append("g").attr("class", "chart-legend").attr("transform", `translate(${m.l + 12},${m.t + 6})`);
    series.forEach((s, i) => {
      const g = lg.append("g").attr("transform", `translate(0,${i * 18})`);
      g.append("line").attr("class", `line ${s.cls}`).attr("x1", 0).attr("x2", 24).attr("y1", 0).attr("y2", 0);
      g.append("text").attr("x", 30).attr("y", 4).text(s.label);
    });
    driftEl.replaceChildren(svg.node());

    const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);
    document.getElementById("drift-table").replaceChildren(
      sortableTable(
        [
          { label: "العمق", en: "depth", value: (r) => r.depth, html: (r) => esc(r.depth), num: true },
          { label: "النقل", en: "transmissions", value: (r) => r.n_transmissions, html: (r) => int(r.n_transmissions), num: true },
          { label: "التغييرات", en: "edits", value: (r) => r.n_edits, html: (r) => int(r.n_edits), num: true },
          { label: "المعدل", en: "rate", value: (r) => r.rate, html: (r) => pct(r.rate), num: true },
          { label: "دون المصنف", en: "non-leaf edits", value: (r) => r.n_edits_nonleaf, html: (r) => int(r.n_edits_nonleaf), num: true },
          { label: "المعدل", en: "non-leaf rate", value: (r) => r.rate_nonleaf, html: (r) => pct(r.rate_nonleaf), num: true },
        ],
        drift,
        { sortCol: 0, dir: 1 }
      )
    );
  }

  async function main() {
    const [atlas, meta] = await Promise.all([ISNAD.load("atlas.json"), ISNAD.meta()]);
    fillChecks(meta.checks);
    document.getElementById("pages-now").textContent = int(meta.n_hadith_pages_cached);
    const titles = { all: "كل الكتب" };
    for (const b of meta.books || []) {
      if (!Object.hasOwn(atlas.cl_hist, b.slug)) continue;
      titles[b.slug] = b.title && b.title !== b.slug ? `${b.title}` : b.slug;
      const o = document.createElement("option");
      o.value = b.slug;
      o.textContent = b.title && b.title !== b.slug ? `${b.title} (${b.slug})` : b.slug;
      sel.appendChild(o);
    }
    const want = new URLSearchParams(location.search).get("book");
    if (want && Object.hasOwn(titles, want)) sel.value = want;
    const render = () => drawHist(atlas, sel.value, titles[sel.value] || sel.value);
    sel.addEventListener("change", () => {
      const u = new URL(location.href);
      if (sel.value === "all") u.searchParams.delete("book");
      else u.searchParams.set("book", sel.value);
      history.replaceState(null, "", u);
      render();
    });
    render();
    drawDrift(atlas.drift || []);
    let t = 0;
    let lastW = window.innerWidth;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth;
      clearTimeout(t);
      t = setTimeout(() => {
        render();
        drawDrift(atlas.drift || []);
      }, 150);
    });
  }

  main().catch((e) => {
    console.error(e);
    histEl.innerHTML = `<p class="error">تعذر التحميل: ${esc(e.message)}</p>`;
    fillChecks({});
  });
})();
