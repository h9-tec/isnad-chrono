// Narrator page: narrator.html?id=N (or ?q=name for a search, nothing for the index).
(function () {
  "use strict";
  const { esc, int, range, chains, narratorLink, groupLink, sortableTable } = window.ISNADUI;
  const main = document.getElementById("narrator");
  const form = document.getElementById("narrator-form");
  const input = document.getElementById("nq");

  const KIND = {
    exact: "دقيق", before: "قبل", after: "بعد", approx: "تقريبًا", alt: "قول آخر", era: "عصر", none: "",
  };
  const METHOD = {
    known: ["معروف", "known"], inferred: ["مقدر", "inferred"], prior_only: ["تقدير أولي", "prior only"],
  };
  const REASON = { negative_cycle: "تعارض زمني (دورة سالبة)" };
  const TOP_N = 20;

  function methodText(m) {
    const t = METHOD[m];
    return t ? `${t[0]} <span class="en">${t[1]}</span>` : esc(m || "—");
  }
  function recorded(y, k) {
    if (y == null) return '<span class="muted">غير مسجلة</span>';
    // Arabic kind first, then the year; the English kind isolated (bidi-safe).
    const ar = k && k !== "exact" && k !== "none" ? KIND[k] ?? "" : "";
    const en = k && k !== "none" ? ` <span class="en">${esc(k)}</span>` : "";
    return `${ar ? `${esc(ar)} ` : ""}<bdi>${esc(y)}</bdi> هـ${en}`;
  }

  // ---------- index / search ----------

  async function showIndex(q) {
    const nm = await ISNAD.narrators();
    document.title = "isnad-chrono · الرواة";
    const all = [...nm.values()].filter((n) => !n.placeholder);
    let hits;
    let head;
    if (q) {
      input.value = q;
      const k = IsnadExplorer.arNorm(q);
      const prefix = [];
      const inner = [];
      for (const n of all) {
        const s = IsnadExplorer.arNorm(n.name);
        if (s.startsWith(k)) prefix.push(n);
        else if (s.includes(" " + k)) inner.push(n);
      }
      const by = (a, b) => (b.n_chains || 0) - (a.n_chains || 0);
      hits = prefix.sort(by).concat(inner.sort(by)).slice(0, 50);
      head = hits.length
        ? `<h1>نتائج «${esc(q)}» <span class="muted small">(${hits.length}${prefix.length + inner.length > hits.length ? "+" : ""})</span></h1>`
        : `<h1>لا يوجد راوٍ باسم «${esc(q)}»</h1>`;
    } else {
      hits = all.sort((a, b) => (b.n_chains || 0) - (a.n_chains || 0)).slice(0, 50);
      head = `<h1>الرواة <span class="en">narrators</span></h1>
        <p class="muted">${int(all.length)} راوٍ لهم سند واحد على الأقل. هؤلاء أكثرهم أسانيد؛ ابحث بالاسم أو الرقم.
        <span class="en">${int(all.length)} narrators with at least one chain; the 50 with most chains are listed.</span></p>`;
    }
    main.innerHTML = head;
    if (hits.length)
      main.appendChild(
        sortableTable(
          [
            { label: "الراوي", en: "narrator", value: (n) => n.name, html: (n) => narratorLink(n.id, nm) },
            { label: "الوفاة المقدرة", en: "death", value: (n) => n.dlo, html: (n) => range(n.dlo, n.dhi), num: true },
            { label: "المنهج", en: "method", value: (n) => n.method, html: (n) => methodText(n.method) },
            { label: "الأسانيد", en: "chains", value: (n) => n.n_chains, html: (n) => int(n.n_chains), num: true },
          ],
          hits,
          { sortCol: q ? -1 : 3 }
        )
      );
  }

  // ---------- timeline ----------

  // Axis clamp (AH): prior-only and other near-unbounded intervals would otherwise
  // stretch the axis to ~1500 and squash every real date into a few pixels.
  const CLAMP = [-60, 400];

  function timeline(n, el) {
    const lows = [n.blo, n.dlo, n.by, n.dy].filter((v) => v != null);
    const highs = [n.bhi, n.dhi, n.dy, n.by].filter((v) => v != null);
    if (!lows.length || !highs.length) return '<p class="muted">لا توجد تواريخ.</p>';
    const lo = Math.max(CLAMP[0], Math.min(...lows) - 10);
    const hi = Math.min(CLAMP[1], Math.max(...highs) + 10);
    const W = Math.max(280, Math.min((el && el.clientWidth) || 600, 1100));
    const H = 176;
    const pad = { l: 22, r: 22 };
    const x = d3.scaleLinear().domain([lo, Math.max(hi, lo + 20)]).nice();
    const [d0, d1] = x.domain();
    x.domain([Math.max(CLAMP[0], d0), Math.min(CLAMP[1], d1)]).range([pad.l, W - pad.r]);
    const [e0, e1] = x.domain();
    const cx = (v) => x(Math.max(e0, Math.min(e1, v)));
    const svg = d3.create("svg").attr("class", "timeline").attr("viewBox", `0 0 ${W} ${H}`)
      .attr("width", "100%").attr("role", "img")
      .attr("aria-label", `الولادة المقدرة ${n.blo ?? "?"}–${n.bhi ?? "?"}، الوفاة المقدرة ${n.dlo ?? "?"}–${n.dhi ?? "?"} هـ`);
    const faint = n.method === "prior_only";
    const rows = [
      { y: 44, label: "الولادة", en: "birth", lo: n.blo, hi: n.bhi, rec: n.by, kind: n.bk, cls: "birth" },
      { y: 112, label: "الوفاة", en: "death", lo: n.dlo, hi: n.dhi, rec: n.dy, kind: n.dk, cls: "death" },
    ];
    for (const r of rows) {
      const g = svg.append("g").attr("class", `row ${r.cls}`);
      g.append("text").attr("class", "row-label").attr("x", W - pad.r).attr("y", r.y - 20)
        .attr("text-anchor", "end").text(`${r.label} · ${r.en}`);
      if (r.lo != null && r.hi != null) {
        const x0 = cx(r.lo);
        const x1 = Math.max(x0 + 3, cx(r.hi));
        const cutL = r.lo < e0;
        const cutR = r.hi > e1;
        g.append("rect").attr("class", `bar ${n.method || "unknown"}${faint ? " faint" : ""}`)
          .attr("x", x0).attr("y", r.y - 7).attr("width", x1 - x0).attr("height", 14).attr("rx", 3)
          .append("title").text(`${r.label} المقدرة: ${r.lo}–${r.hi} هـ (${n.method})`);
        // Arrowheads where the interval runs past the clamped axis.
        if (cutL) g.append("path").attr("class", "cut").attr("d", `M${x0 - 10},${r.y}L${x0},${r.y - 8}L${x0},${r.y + 8}Z`);
        if (cutR) g.append("path").attr("class", "cut").attr("d", `M${x1 + 10},${r.y}L${x1},${r.y - 8}L${x1},${r.y + 8}Z`);
        // True bounds as labels (even when the bar is cut at the edge).
        const narrow = x1 - x0 < 48; // labels beside the bar ends, not centred on them
        g.append("text").attr("class", "bound").attr("x", narrow && !cutL ? x0 - 3 : x0).attr("y", r.y + 20)
          .attr("text-anchor", cutL ? "start" : narrow ? "end" : "middle").text(cutL ? `← ${r.lo}` : `${r.lo}`);
        if (r.hi !== r.lo)
          g.append("text").attr("class", "bound").attr("x", narrow && !cutR ? x1 + 3 : x1).attr("y", r.y + 20)
            .attr("text-anchor", cutR ? "end" : narrow ? "start" : "middle").text(cutR ? `${r.hi} →` : `${r.hi}`);
      }
      if (r.rec != null) {
        g.append("circle").attr("class", `rec${r.kind === "exact" ? "" : " hollow"}`)
          .attr("cx", cx(r.rec)).attr("cy", r.y).attr("r", 6)
          .append("title").text(`${r.label} المسجلة: ${r.rec} هـ (${r.kind || "?"})`);
      }
    }
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - 34})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(W / 80))).tickFormat(d3.format("d")));
    svg.append("text").attr("class", "axis-label").attr("x", W - pad.r).attr("y", H - 2).attr("text-anchor", "end").text("AH · سنة هجرية");
    return `<div class="timeline-wrap">${svg.node().outerHTML}</div>
      <p class="legend small"><span><i class="swatch ${esc(n.method)}"></i>مجال مقدر</span>
      <span><i class="pt"></i>سنة مسجلة (دقيقة)</span><span><i class="pt hollow"></i>مسجلة غير دقيقة (قبل/بعد/تقريبًا)</span>
      <span>المحور مقصور على <bdi dir="ltr">${CLAMP[0]}…${CLAMP[1]}</bdi> هـ؛ السهم يعني أن المجال يتجاوزه</span>
      ${faint ? '<span class="muted">تقدير أولي: لم يصل إليه أي قيد من الأسانيد</span>' : ""}</p>`;
  }

  // ---------- narrator ----------

  function linkList(pairs, nm, label) {
    if (!pairs.length) return `<p class="muted">لا يوجد ${label}.</p>`;
    return `<ol class="people">${pairs
      .slice(0, TOP_N)
      .map(([id, c]) => `<li>${narratorLink(id, nm)} <span class="muted small">${chains(c)}</span></li>`)
      .join("")}</ol>`;
  }

  async function showNarrator(raw) {
    if (!/^\d+$/.test(raw)) {
      main.innerHTML = `<p class="error">رقم راوٍ غير صالح: <span dir="ltr">${esc(raw)}</span> <span class="en">invalid narrator id</span></p>`;
      return;
    }
    const id = Number(raw);
    const nm = await ISNAD.narrators();
    const n = nm.get(id);
    if (!n) {
      main.innerHTML = `<p class="error">الراوي <span dir="ltr">${id}</span> غير موجود في الفهرس (لا سند له). <span class="en">Narrator not in the index (no chains).</span></p>`;
      return;
    }
    let det = null;
    let detErr = null;
    try {
      det = await ISNAD.narratorDetail(id);
    } catch (e) {
      if (e.status === 404) det = null;
      else detErr = e;
    }
    const d = det || { teachers: [], students: [], cl_groups: [], dropped: [] };
    document.title = `${n.name} · isnad-chrono`;

    const facts = [];
    if (n.kunya) facts.push(`<dt>الكنية</dt><dd>${esc(n.kunya)}</dd>`);
    facts.push(`<dt>الطبقة</dt><dd>${n.gen != null ? esc(n.gen) : '<span class="muted">—</span>'}</dd>`);
    facts.push(`<dt>الوفاة المسجلة</dt><dd>${recorded(n.dy, n.dk)}</dd>`);
    facts.push(`<dt>الولادة المسجلة</dt><dd>${recorded(n.by, n.bk)}</dd>`);
    // Placeholder ids merge every unnamed narrator into one node: their inferred
    // dates and support describe no single person, so they are not shown.
    const ph = !!n.placeholder;
    if (!ph) {
      facts.push(`<dt>الوفاة المقدرة</dt><dd>${range(n.dlo, n.dhi)} هـ</dd>`);
      facts.push(`<dt>الولادة المقدرة</dt><dd>${range(n.blo, n.bhi)} هـ</dd>`);
      facts.push(`<dt>منهج التأريخ</dt><dd>${methodText(n.method)}</dd>`);
      facts.push(`<dt>الدعم</dt><dd>${int(n.support)} <span class="muted small">صلة شيخ–تلميذ باقية</span></dd>`);
    }
    facts.push(`<dt>الأسانيد المارة به</dt><dd>${int(n.n_chains)}</dd>`);
    const conflict = !ph && n.dy != null && n.dlo != null && n.dhi != null && (n.dy < n.dlo || n.dy > n.dhi);
    const caveat = ph
      ? `<p class="note placeholder-caveat">عقدة مدمجة لراوٍ غير مسمّى؛ التواريخ والروابط لا تدل على شخص واحد.
         <span class="en">A merged node for unnamed narrators: its dates and links do not describe one person.</span></p>`
      : "";

    const parts = [];
    parts.push(`<header class="nar-head"><h1>${esc(n.name)}</h1>
      ${n.placeholder
        ? '<p class="muted">راوٍ غير مسمى في الإسناد (لا صفحة له على hdith.com). <span class="en">Unnamed narrator.</span></p>'
        : `<p class="links"><span dir="ltr" class="muted">p-${id}</span> · <a href="${ISNAD.rawiUrl(id)}" rel="noopener">hdith.com</a></p>`}
      </header>`);
    if (ph) parts.push(caveat);
    parts.push(`<div class="nar-grid${ph ? " single" : ""}"><section class="card"><h2>البيانات <span class="en">facts</span></h2><dl class="facts">${facts.join("")}</dl>
      ${conflict ? `<p class="note">سنة الوفاة المسجلة (${esc(n.dy)}) خارج المجال المقدر من الأسانيد. <span class="en">Recorded death year lies outside the inferred interval.</span></p>` : ""}</section>
      ${ph ? "" : '<section class="card"><h2>الخط الزمني <span class="en">timeline</span></h2><div id="timeline"></div></section>'}</div>`);

    if (detErr) parts.push(`<p class="error">تعذر تحميل الصلات: ${esc(detErr.message)}</p>`);
    else if (!det) parts.push('<p class="muted card">لا صلات مسجلة لهذا الراوي. <span class="en">No links.</span></p>');

    parts.push(`<div class="nar-grid">
      <section class="card"><h2>الشيوخ <span class="en">teachers · top ${TOP_N}</span></h2>${linkList(d.teachers, nm, "شيوخ")}</section>
      <section class="card"><h2>التلاميذ <span class="en">students · top ${TOP_N}</span></h2>${linkList(d.students, nm, "تلاميذ")}</section></div>`);

    parts.push(`<section class="card"><h2>حلقة مشتركة (k2) في ${int(d.cl_groups.length)} مجموعة <span class="en">common link of</span></h2>
      <div id="cl-table">${d.cl_groups.length ? "" : '<p class="muted">ليس حلقة مشتركة في أي مجموعة.</p>'}</div></section>`);

    parts.push(`<section class="card"><h2>صلات أسقطها التأريخ (${int(d.dropped.length)}) <span class="en">links dropped by the dating step</span></h2>
      ${d.dropped.length
        ? `<p class="small muted">صلة شيخ–تلميذ تجعل المجالات متناقضة فتُحذف قبل الحساب.</p><ul class="dropped">${d.dropped
            .map(([o, r]) => `<li>${narratorLink(o, nm)} <span class="muted small">${esc(REASON[r] || r)}</span></li>`)
            .join("")}</ul>`
        : '<p class="muted">لا شيء.</p>'}</section>`);

    main.innerHTML = parts.join("");
    const tl = document.getElementById("timeline");
    if (tl) tl.innerHTML = timeline(n, tl);
    if (d.cl_groups.length) {
      const num = (gid) => Number(String(gid).split("-").pop());
      document.getElementById("cl-table").appendChild(
        sortableTable(
          [
            { label: "المجموعة", en: "group", value: (r) => num(r[0]), html: (r) => groupLink(r[0]), num: true },
            { label: "تاريخ الرواية", en: "report date (death of CL)", value: (r) => r[1], html: (r) => `${range(r[1], r[2])} هـ`, num: true },
          ],
          d.cl_groups
        )
      );
    }
  }

  form.addEventListener("submit", (ev) => {
    const q = input.value.trim();
    ev.preventDefault();
    if (!q) return;
    location.href = /^\d+$/.test(IsnadExplorer.asciiDigits(q))
      ? `narrator.html?id=${IsnadExplorer.asciiDigits(q)}`
      : `narrator.html?q=${encodeURIComponent(q)}`;
  });

  const p = new URLSearchParams(location.search);
  const run = p.get("id") ? showNarrator(p.get("id").trim()) : showIndex(p.get("q"));
  run.catch((e) => {
    console.error(e);
    main.innerHTML = `<p class="error">تعذر التحميل: ${esc(e.message)}</p>`;
  });
})();
