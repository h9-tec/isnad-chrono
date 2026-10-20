// Leaderboards: four sortable tables from atlas.json boards.
(function () {
  "use strict";
  const { esc, int, range, narratorLink, narratorName, groupLink, sortableTable } = window.ISNADUI;

  function body(id) {
    return document.querySelector(`#${id} .board-body`);
  }

  async function main() {
    const [atlas, nm] = await Promise.all([ISNAD.load("atlas.json"), ISNAD.narrators()]);
    const b = atlas.boards || {};
    const name = (id) => narratorName(id, nm);
    const who = (id) => narratorLink(id, nm);
    const info = (id) => nm.get(Number(id)) || {};
    const rank = { label: "#", value: (r) => r._rank, html: (r) => esc(r._rank), num: true };
    const ranked = (rows) => (rows || []).map((r, i) => Object.assign(r.slice(), { _rank: i + 1 }));
    const nameCol = (pick) => ({ label: "الراوي", en: "narrator", value: (r) => name(pick(r)), html: (r) => who(pick(r)) });
    const deathCol = (pick) => ({
      label: "الوفاة المقدرة", en: "inferred death",
      value: (r) => info(pick(r)).dlo,
      html: (r) => (info(pick(r)).dlo != null ? `${range(info(pick(r)).dlo, info(pick(r)).dhi)} هـ` : "—"),
      num: true,
    });

    body("top_cls").replaceChildren(
      sortableTable(
        [rank, nameCol((r) => r[0]), deathCol((r) => r[0]),
          { label: "المجموعات", en: "groups", value: (r) => r[1], html: (r) => int(r[1]), num: true }],
        ranked(b.top_cls), { sortCol: 3 }
      )
    );

    const gnum = (g) => Number(String(g).split("-").pop());
    body("earliest").replaceChildren(
      sortableTable(
        [rank,
          { label: "المجموعة", en: "group", value: (r) => gnum(r[0]), html: (r) => groupLink(r[0]), num: true },
          nameCol((r) => r[1]),
          { label: "تاريخ الرواية", en: "report date AH", value: (r) => r[3], html: (r) => `${range(r[2], r[3])} هـ`, num: true }],
        ranked(b.earliest), { sortCol: 0, dir: 1 }
      )
    );

    body("conflicts").replaceChildren(
      sortableTable(
        [rank, nameCol((r) => r[0]),
          { label: "صلات مسقطة", en: "dropped links", value: (r) => r[1], html: (r) => int(r[1]), num: true },
          { label: "الوفاة المسجلة", en: "recorded death", value: (r) => r[2], html: (r) => (r[2] != null ? `${esc(r[2])} هـ` : "—"), num: true },
          deathCol((r) => r[0])],
        ranked(b.conflicts), { sortCol: 2 }
      )
    );

    body("top_editors").replaceChildren(
      sortableTable(
        [rank, nameCol((r) => r[0]),
          { label: "تغييرات منسوبة", en: "attributed edits", value: (r) => r[1], html: (r) => int(r[1]), num: true },
          { label: "الأسانيد", en: "chains", value: (r) => r[2], html: (r) => int(r[2]), num: true },
          { label: "لكل سند", en: "edits / chain", value: (r) => (r[2] ? r[1] / r[2] : null), html: (r) => (r[2] ? (r[1] / r[2]).toFixed(3) : "—"), num: true }],
        ranked(b.top_editors), { sortCol: 2 }
      )
    );
  }

  main().catch((e) => {
    console.error(e);
    body("top_cls").innerHTML = `<p class="error">تعذر التحميل: ${esc(e.message)}</p>`;
  });
})();
