// Shared helpers for the narrator, atlas, boards and method pages.
(function () {
  "use strict";

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  const nf = new Intl.NumberFormat("en-US");
  function int(n) {
    return n == null || !Number.isFinite(Number(n)) ? "—" : nf.format(Math.round(Number(n)));
  }

  // "lo–hi" inside an LTR isolate so RTL text does not flip the range.
  function range(lo, hi) {
    return `<bdi dir="ltr">${esc(lo ?? "?")}–${esc(hi ?? "?")}</bdi>`;
  }

  // "n سند" with the plural أسانيد for 3–10 (Arabic counted-noun rule, simplified).
  function chains(n) {
    const k = Number(n);
    return `${int(k)} ${k >= 3 && k <= 10 ? "أسانيد" : "سند"}`;
  }

  // Check values: data-fmt="pct" (rate -> %), "int", "years" (1 decimal), default 3 decimals.
  function fmtCheck(v, fmt) {
    if (v == null || v === "") return "—";
    if (typeof v === "boolean") return v ? "true" : "false";
    const x = Number(v);
    if (!Number.isFinite(x)) return String(v); // used with textContent
    if (fmt === "pct") return `${(x * 100).toFixed(1)}%`;
    if (fmt === "int") return int(x);
    if (fmt === "years") return x.toFixed(1);
    return Number.isInteger(x) ? int(x) : x.toFixed(3);
  }

  // Fill every [data-check] span under root from meta.checks.
  function fillChecks(checks, root) {
    (root || document).querySelectorAll("[data-check]").forEach((el) => {
      const k = el.dataset.check;
      const has = checks && Object.hasOwn(checks, k);
      el.textContent = has ? fmtCheck(checks[k], el.dataset.fmt) : "—";
      el.title = k;
      if (!has) el.classList.add("missing");
    });
  }

  function narratorName(id, nm) {
    const n = nm && nm.get(Number(id));
    return n ? n.name : `p-${id}`;
  }

  // Name link to narrator.html; placeholders are plain text; unknown ids p-<id>.
  function narratorLink(id, nm) {
    const n = nm && nm.get(Number(id));
    if (!n) return `<span class="ph" dir="ltr">p-${esc(id)}</span>`;
    if (n.placeholder) return `<span class="ph">${esc(n.name)}</span>`;
    return `<a href="narrator.html?id=${encodeURIComponent(n.id)}">${esc(n.name)}</a>`;
  }

  function groupLink(gid) {
    return `<a href="index.html?g=${encodeURIComponent(gid)}" dir="ltr">${esc(gid)}</a>`;
  }

  // Sortable table. cols: [{label, en, value(row) -> sortable, html(row) -> cell html, num}]
  // Click a header to sort (again to reverse). Returns the wrapper element.
  function sortableTable(cols, rows, opts) {
    opts = opts || {};
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    table.className = "board";
    if (opts.caption) table.createCaption().textContent = opts.caption;
    const thead = table.createTHead().insertRow();
    const tbody = table.createTBody();
    let sortCol = opts.sortCol ?? -1;
    let dir = opts.dir ?? -1;
    cols.forEach((c, i) => {
      const th = document.createElement("th");
      th.scope = "col";
      if (c.num) th.className = "num";
      const b = document.createElement("button");
      b.type = "button";
      b.innerHTML = `${esc(c.label)}${c.en ? ` <span class="en">${esc(c.en)}</span>` : ""}<span class="arrow" aria-hidden="true"></span>`;
      b.addEventListener("click", () => {
        dir = sortCol === i ? -dir : c.num ? -1 : 1;
        sortCol = i;
        render();
      });
      th.appendChild(b);
      thead.appendChild(th);
    });
    function render() {
      const r = rows.slice();
      if (sortCol >= 0) {
        const v = cols[sortCol].value;
        r.sort((a, b) => {
          const x = v(a);
          const y = v(b);
          if (x == null && y == null) return 0;
          if (x == null) return 1; // nulls last either way
          if (y == null) return -1;
          return (typeof x === "string" ? x.localeCompare(y, "ar") : x - y) * dir;
        });
      }
      [...thead.children].forEach((th, i) => {
        th.setAttribute("aria-sort", i === sortCol ? (dir > 0 ? "ascending" : "descending") : "none");
        th.querySelector(".arrow").textContent = i === sortCol ? (dir > 0 ? " ▲" : " ▼") : "";
      });
      tbody.innerHTML = r
        .map((row) => `<tr>${cols.map((c) => `<td${c.num ? ' class="num"' : ""}>${c.html(row)}</td>`).join("")}</tr>`)
        .join("");
    }
    render();
    wrap.appendChild(table);
    return wrap;
  }

  window.ISNADUI = { esc, int, range, chains, fmtCheck, fillChecks, narratorName, narratorLink, groupLink, sortableTable };

  // Pages with [data-check] spans and no own script fill them here.
  if (typeof document !== "undefined" && document.body && document.body.dataset.checks === "auto") {
    window.ISNAD.meta()
      .then((m) => fillChecks(m.checks))
      .catch((e) => {
        console.error(e);
        fillChecks({});
      });
  }
})();
