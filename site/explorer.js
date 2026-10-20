// Report explorer: search box, group rendering, side panel.
(function () {
  "use strict";

  const MAX_NARRATOR_HITS = 20;
  const MAX_CHOICES = 24;
  const EDIT_LABELS = [
    ["attributed", "منسوبة", "attributed"],
    ["ambiguous", "ملتبسة", "ambiguous"],
    ["partial", "جزئية", "partial"],
    ["cross_root", "عبر الأطراف", "cross-root"],
    ["no_chain", "بلا إسناد", "no chain"],
    ["no_common_node", "بلا راوٍ مشترك", "no common node"],
  ];

  const { esc, narratorName, narratorLink, asciiDigits, arNorm, announce } = window.ISNADUI;

  // ---------- pure helpers (mirrors isnad.export_site.search_key) ----------

  function resolveBook(book, idx) {
    const aliases = (idx && idx.aliases) || {};
    const books = (idx && idx.books) || {};
    const lower = book.toLowerCase();
    if (Object.hasOwn(aliases, lower)) return aliases[lower];
    if (Object.hasOwn(aliases, book)) return aliases[book];
    if (Object.hasOwn(books, lower)) return lower;
    for (const [slug, title] of Object.entries(books)) if (title === book) return slug;
    return null;
  }

  // q -> {kind: "numbering"|"hadith"|"group"|"narrator", key, ...}
  function normalizeQuery(q, idx) {
    const s = asciiDigits(q || "").split(/\s+/).filter(Boolean).join(" ");
    if (!s) return null;
    if (/^t[kg]-\d+$/i.test(s)) return { kind: "group", key: s.toLowerCase() };
    if (/^\d+$/.test(s)) return { kind: "hadith", key: String(Number(s)) };
    const toks = s.split(" ");
    if (toks.length >= 2 && /^\d/.test(toks[toks.length - 1])) {
      for (let i = toks.length - 1; i >= 1; i--) {
        const book = toks.slice(0, i).join(" ");
        const num = toks.slice(i).join("");
        const slug = resolveBook(book, idx);
        if (slug) return { kind: "numbering", key: `${slug}:${num}`, slug, num };
      }
      const book = toks.slice(0, -1).join(" ").toLowerCase();
      const num = toks[toks.length - 1];
      return { kind: "numbering", key: `${book}:${num}`, slug: book, num, unknownBook: true };
    }
    return { kind: "narrator", key: s };
  }

  window.IsnadExplorer = { normalizeQuery };
  if (typeof document === "undefined" || !document.getElementById("search-form")) return;

  // ---------- page ----------

  const $ = (s) => document.querySelector(s);
  const input = $("#q");
  const results = $("#results");
  const panel = $("#panel");
  const svg = d3.select("#tree");
  const scroller = $("#tree-scroll");
  const empty = $("#tree-empty");
  const emptyHTML = empty.innerHTML;
  let state = null; // {g, layout, meta, nm}
  let scale = 1;
  let normIndex = null;
  let loadToken = 0; // newest showGroup request wins
  const GROUP_RE = /^t[kg]-\d+$/;

  function bookTitle(slug, meta) {
    const b = meta && (meta.books || []).find((x) => x.slug === slug);
    return (b && b.title) || slug;
  }

  function setResults(html, status) {
    results.innerHTML = html || "";
    if (status != null) announce(status);
  }

  // Back to the start page (popstate to a bare URL): no group, no results, empty panel.
  function resetPage() {
    ++loadToken; // drop any in-flight group load
    state = null;
    input.value = "";
    setResults("");
    svg.selectAll("*").remove();
    svg.attr("width", 0).attr("height", 0);
    empty.innerHTML = emptyHTML;
    empty.hidden = false;
    panel.innerHTML = "";
    document.title = "isnad-chrono · مستكشف الأسانيد";
    announce("");
  }

  function setURL(params, push) {
    const u = new URL(location.href);
    u.search = new URLSearchParams(params).toString();
    if (u.href === location.href) return;
    history[push ? "pushState" : "replaceState"](null, "", u);
  }

  async function runQuery(q, opts) {
    opts = opts || {};
    input.value = q;
    const idx = await ISNAD.search().catch(() => ({}));
    const nq = normalizeQuery(q, idx);
    if (!nq) return;
    if (opts.push !== false) setURL({ q }, true);
    setResults('<p class="muted">جارٍ البحث…</p>');
    try {
      if (nq.kind === "group") {
        setResults("");
        return showGroup(nq.key, { push: false });
      }
      if (nq.kind === "hadith") {
        const shard = await ISNAD.hadithShard(nq.key);
        return choose(Object.hasOwn(shard, nq.key) ? shard[nq.key] : null, `رقم الحديث ${nq.key}`);
      }
      if (nq.kind === "numbering") {
        if (nq.unknownBook && !Object.hasOwn(idx.books || {}, nq.slug)) {
          return setResults(`<p class="error">كتاب غير معروف: ${esc(nq.slug)}. جرّب bukhari أو مسلم أو b-1…</p>`);
        }
        const shard = await ISNAD.numberingShard(nq.slug);
        const title = Object.hasOwn(idx.books || {}, nq.slug) ? idx.books[nq.slug] : nq.slug;
        return choose(Object.hasOwn(shard.numbering, nq.num) ? shard.numbering[nq.num] : null, `${title} ${nq.num}`);
      }
      return narratorSearch(nq.key);
    } catch (e) {
      if (e.status === 404) return setResults('<p class="error">لا نتائج.</p>');
      console.error(e);
      setResults(`<p class="error">تعذر التحميل: ${esc(e.message)}</p>`);
    }
  }

  async function choose(ids, label) {
    if (!ids || !ids.length) return setResults(`<p class="error">لا توجد مجموعة لـ ${esc(label)}.</p>`, `لا توجد مجموعة لـ ${label}`);
    if (ids.length === 1) {
      setResults("");
      return showGroup(ids[0], { push: false });
    }
    const [nm, groups] = await Promise.all([
      ISNAD.narrators(),
      Promise.all(ids.slice(0, MAX_CHOICES).map((id) => ISNAD.group(id).catch(() => null))),
    ]);
    const items = ids.slice(0, MAX_CHOICES).map((id, i) => {
      const g = groups[i];
      if (!g) return `<li><a href="?g=${esc(id)}" data-g="${esc(id)}" dir="ltr">${esc(id)}</a></li>`;
      const nOcc = Object.values(g.books).reduce((s, v) => s + v.length, 0);
      const cl = g.cl && g.cl.k2 ? ` · CL: ${esc(narratorName(g.cl.k2.id, nm))}` : "";
      return `<li><a href="?g=${esc(id)}" data-g="${esc(id)}"><span dir="ltr">${esc(id)}</span></a>
        <span class="muted">${g.chains.length} سند · ${nOcc} موضع · ${Object.keys(g.books).length} كتاب${cl}</span></li>`;
    });
    setResults(
      `<p>${esc(label)} يقع في ${ids.length} مجموعات، اختر واحدة:</p><ul class="choices">${items.join("")}</ul>` +
        (ids.length > MAX_CHOICES ? `<p class="muted">و${ids.length - MAX_CHOICES} أخرى…</p>` : ""),
      `${label}: ${ids.length} مجموعات`
    );
  }

  async function narratorSearch(q) {
    const nm = await ISNAD.narrators();
    if (!normIndex) {
      normIndex = [];
      for (const n of nm.values()) if (!n.placeholder) normIndex.push([arNorm(n.name), n]);
    }
    const k = arNorm(q);
    const prefix = [];
    const inner = [];
    for (const [s, n] of normIndex) {
      if (s.startsWith(k)) prefix.push(n);
      else if (s.includes(" " + k)) inner.push(n);
    }
    const byChains = (a, b) => (b.n_chains || 0) - (a.n_chains || 0);
    const hits = prefix.sort(byChains).concat(inner.sort(byChains)).slice(0, MAX_NARRATOR_HITS);
    if (!hits.length) return setResults(`<p class="error">لا يوجد راوٍ باسم «${esc(q)}».</p>`, `لا يوجد راوٍ باسم ${q}`);
    setResults(
      `<p>الرواة المطابقون (${hits.length}${prefix.length + inner.length > hits.length ? "+" : ""}):</p><ul class="choices">` +
        hits
          .map(
            (n) => `<li><a href="narrator.html?id=${encodeURIComponent(n.id)}">${esc(n.name)}</a>
            <span class="muted">${n.kunya ? esc(n.kunya) + " · " : ""}${IsnadTree.intervalText(n.dlo, n.dhi)} · ${n.n_chains} سند</span></li>`
          )
          .join("") +
        "</ul>",
      `${hits.length} راوٍ مطابق`
    );
  }

  async function showGroup(id, opts) {
    opts = opts || {};
    id = String(id).trim().toLowerCase();
    const token = ++loadToken;
    if (!GROUP_RE.test(id)) {
      state = null;
      svg.selectAll("*").remove();
      svg.attr("width", 0).attr("height", 0);
      empty.hidden = false;
      panel.innerHTML = `<p class="error">معرّف غير صالح: <span dir="ltr">${esc(id)}</span> <span class="en">invalid group id (expected tk-N or tg-N)</span></p>`;
      return;
    }
    const fit = new URLSearchParams(location.search).get("z") === "fit";
    if (opts.push !== false) setURL({ g: id }, true);
    else if (!new URLSearchParams(location.search).has("q")) setURL(fit ? { g: id, z: "fit" } : { g: id }, false);
    panel.innerHTML = '<p class="muted">جارٍ التحميل…</p>';
    let g, nm, meta;
    try {
      [g, nm, meta] = await Promise.all([ISNAD.group(id), ISNAD.narrators(), ISNAD.meta()]);
    } catch (e) {
      if (token !== loadToken) return;
      panel.innerHTML =
        e.status === 404
          ? `<p class="error">المجموعة <span dir="ltr">${esc(id)}</span> غير موجودة.</p>`
          : `<p class="error">تعذر التحميل: ${esc(e.message)}</p>`;
      return;
    }
    if (token !== loadToken) return; // a newer request superseded this one
    const layout = IsnadTree.layoutGroup(g, nm);
    state = { g, nm, meta, layout };
    document.title = `${g.id} · isnad-chrono`;
    announce(`المجموعة ${g.id}: ${g.chains.length} سند`);
    scale = 1;
    draw(true);
    renderPanel();
    // ?z=fit opens the whole drawing scaled to the view (useful for big groups).
    if (fit) zoom("fit");
  }

  function draw(recenter) {
    if (!state) return;
    const { g, layout } = state;
    const hasTree = layout.components.length && g.chains.length;
    empty.hidden = !!hasTree;
    if (!hasTree) {
      svg.selectAll("*").remove();
      svg.attr("width", 0).attr("height", 0);
      empty.innerHTML = '<p>لا توجد أسانيد مستخرجة لهذه المجموعة.</p><p class="en">No chains were extracted for this group.</p>';
      return;
    }
    IsnadTree.drawGroup(svg, layout, { scale, cl: g.cl, onNode: selectNode });
    if (recenter) {
      // Center the first root (rightmost component) in view.
      const c = layout.components[0];
      const r = c.nodes.find((n) => n.id === c.root);
      const x = (c.x0 + (r ? r.x : c.width / 2)) * scale;
      scroller.scrollLeft = Math.max(0, x - scroller.clientWidth / 2);
      scroller.scrollTop = 0;
    }
  }

  function zoom(kind) {
    if (!state) return;
    const W = state.layout.width || 1;
    const centerFrac = (scroller.scrollLeft + scroller.clientWidth / 2) / (W * scale);
    if (kind === "in") scale = Math.min(2, scale * 1.25);
    else if (kind === "out") scale = Math.max(0.05, scale / 1.25);
    else if (kind === "reset") scale = 1;
    else if (kind === "fit") scale = Math.min(1, (scroller.clientWidth - 8) / W);
    // viewBox is fixed by drawGroup; zoom only resizes the SVG (no re-render,
    // so the selection highlight and focus survive).
    svg.attr("width", W * scale).attr("height", (state.layout.height || 1) * scale);
    scroller.scrollLeft = Math.max(0, centerFrac * W * scale - scroller.clientWidth / 2);
  }

  // comp = the component the clicked node belongs to: the same narrator can
  // appear under several roots, so only this component's links are listed.
  function selectNode(d, comp) {
    const own = new Set(comp ? comp.links : []);
    svg.selectAll("g.node").classed("selected", (n) => n === d);
    svg.selectAll("g.link").classed("hl", (l) => own.has(l) && (l.source.id === d.id || l.target.id === d.id));
    const box = panel.querySelector("#selected");
    if (!box) return;
    const i = d.info;
    const rows = [];
    if (i) {
      if (i.kunya) rows.push(`<dt>الكنية</dt><dd>${esc(i.kunya)}</dd>`);
      if (i.gen != null) rows.push(`<dt>الطبقة</dt><dd>${esc(i.gen)}</dd>`);
      if (i.dy != null) rows.push(`<dt>الوفاة المسجلة</dt><dd>${i.dy} هـ${i.dk ? ` (${esc(i.dk)})` : ""}</dd>`);
      if (i.by != null) rows.push(`<dt>الولادة المسجلة</dt><dd>${i.by} هـ${i.bk ? ` (${esc(i.bk)})` : ""}</dd>`);
      if (d.interval) rows.push(`<dt>الوفاة المقدرة</dt><dd><bdi dir="ltr">${i.dlo ?? "?"}–${i.dhi ?? "?"}</bdi> هـ · ${esc(i.method)}</dd>`);
      if (i.blo != null || i.bhi != null) rows.push(`<dt>الولادة المقدرة</dt><dd><bdi dir="ltr">${i.blo ?? "?"}–${i.bhi ?? "?"}</bdi> هـ</dd>`);
      rows.push(`<dt>الدعم</dt><dd>${i.support ?? 0}</dd><dt>عدد الأسانيد</dt><dd>${i.n_chains ?? 0}</dd>`);
    }
    rows.push(`<dt>العمق</dt><dd>${d.depth ?? "?"} · k=${d.k} · ${d.n_desc} مصنف تحته</dd>`);
    const incoming = [...own].filter((l) => l.target.id === d.id);
    if (d.edits.length)
      rows.push(
        `<dt>تغييرات اللفظ</dt><dd>${d.edits.map((e) => `مقطع ${e.seg}: ${esc(e.type)} (${esc(e.status)})`).join("<br>")}</dd>`
      );
    const links =
      i && i.placeholder
        ? '<p class="muted">راوٍ غير مسمى في الإسناد.</p>'
        : `<p class="links"><a href="narrator.html?id=${encodeURIComponent(d.id)}">صفحة الراوي</a> · <a href="${esc(ISNAD.rawiUrl(d.id))}" rel="noopener">hdith.com</a></p>`;
    const inc = incoming.length
      ? `<p class="small">يروي عن <span class="en">incoming edges</span></p><ul class="incoming small">${incoming
          .map((l) => `<li>${esc(l.source.name)}: ${l.term ? esc(l.term) : '<span class="muted">صيغة غير معروفة</span>'} <span class="muted">(${l.n} سند)</span></li>`)
          .join("")}</ul>`
      : "";
    box.innerHTML = `<h3>${esc(d.name)}</h3><dl class="facts">${rows.join("")}</dl>${inc}${links}`;
    box.hidden = false;
  }

  function renderPanel() {
    const { g, nm, meta } = state;
    const nOcc = Object.values(g.books).reduce((s, v) => s + v.length, 0);
    const yes = (b) => (b ? "نعم" : "لا");
    const parts = [];
    parts.push(`<h2>المجموعة <span dir="ltr">${esc(g.id)}</span></h2>`);
    parts.push(`<dl class="facts">
      <dt>المواضع</dt><dd>${nOcc} في ${Object.keys(g.books).length} كتاب</dd>
      <dt>الأسانيد</dt><dd>${g.chains.length}</dd>
      <dt>الأطراف (الصحابة)</dt><dd>${g.roots.length}</dd>
      <dt>مكتملة</dt><dd>${yes(g.complete)}</dd>
      <dt>لكل موضع إسناد</dt><dd>${yes(g.all_chained)}</dd></dl>`);

    // Report date line.
    const k2 = g.cl && g.cl.k2;
    const k3 = g.cl && g.cl.k3;
    if (k2) {
      const name = narratorName(k2.id, nm);
      parts.push(`<p class="date-line">أقدم راوٍ يمكن تأريخه (الحلقة المشتركة k2): ${narratorLink(k2.id, nm)}،
        توفي بين ${k2.lo ?? "?"} و${k2.hi ?? "?"} هـ <span class="muted">(${esc(k2.method)}${k2.all_chains ? "" : "، لا يمر به كل سند"})</span>
        <span class="en">Earliest datable transmitter: ${esc(name)}, died between ${k2.lo ?? "?"} and ${k2.hi ?? "?"} AH.</span></p>`);
      if (k3 && k3.id !== k2.id)
        parts.push(`<p class="date-line small">الحلقة المشتركة k3: ${narratorLink(k3.id, nm)}، توفي بين ${k3.lo ?? "?"} و${k3.hi ?? "?"} هـ</p>`);
    } else {
      parts.push('<p class="date-line muted">لا توجد حلقة مشتركة k2 في هذه المجموعة. <span class="en">No k2 common link.</span></p>');
    }

    // Selected narrator.
    parts.push('<section id="selected" class="selected" hidden></section>');

    // Edits.
    const e = g.edits || {};
    const ext = e.by_node_external || [];
    parts.push(`<h3>تغييرات اللفظ <span class="en">wording changes</span></h3><table class="edits"><tbody>` +
      EDIT_LABELS.map(([k, ar, en]) => `<tr><th>${ar} <span class="en">${en}</span></th><td>${e[k] ?? 0}</td></tr>`).join("") +
      "</tbody></table>");
    if (ext.length) {
      const who = [...new Set(ext.map((x) => x.id))];
      parts.push(`<p class="small">${ext.length} تغييرًا منسوبة إلى رواة خارج الأسانيد المرسومة:
        ${who.map((id) => narratorLink(id, nm)).join("، ")}
        <span class="en">${ext.length} edits attributed to transmitters outside the drawn chains.</span></p>`);
    }

    // Occurrences per book.
    const books = Object.entries(g.books);
    parts.push(`<h3>المواضع <span class="en">occurrences</span></h3><ul class="books">` +
      books
        .map(([slug, hids]) => {
          const links = hids.map((h) => `<a href="${esc(ISNAD.hadithUrl(slug, h))}" rel="noopener">${esc(h)}</a>`).join(" ");
          const title = `${esc(bookTitle(slug, meta))} <span class="muted">(${hids.length})</span>`;
          return hids.length > 8
            ? `<li><details><summary>${title}</summary><div class="hids">${links}</div></details></li>`
            : `<li>${title}<div class="hids">${links}</div></li>`;
        })
        .join("") +
      "</ul>");

    // Shawahid companions.
    if (g.shawahid && g.shawahid.length)
      parts.push(`<h3>الشواهد <span class="en">shawahid companions</span></h3><p class="shawahid">${g.shawahid
        .map((id) => narratorLink(id, nm))
        .join("، ")}</p>`);

    parts.push('<p class="muted small">انقر على راوٍ لعرض تفاصيله. مرّر فوق الوصلات لرؤية صيغة التحمل.</p>');
    panel.innerHTML = parts.join("");
  }

  // ---------- wiring ----------

  $("#search-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = input.value.trim();
    if (q) runQuery(q);
  });
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-q], a[data-g]");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    if (a.dataset.q) runQuery(a.dataset.q);
    else {
      setResults("");
      showGroup(a.dataset.g);
    }
  });
  document.querySelectorAll("[data-zoom]").forEach((b) => b.addEventListener("click", () => zoom(b.dataset.zoom)));

  function fromURL() {
    const p = new URLSearchParams(location.search);
    if (p.get("g")) {
      input.value = p.get("g");
      setResults("");
      showGroup(p.get("g"), { push: false });
    } else if (p.get("q")) runQuery(p.get("q"), { push: false });
    else resetPage();
  }
  window.addEventListener("popstate", fromURL);
  fromURL();
})();
