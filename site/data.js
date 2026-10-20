// Data access for the isnad-chrono site: fetch + cache + shard paths.
// On GitHub Pages the export lives under ./data/; locally the repo root is
// served (python -m http.server) and the export is ../site_data/.
(function () {
  "use strict";
  const base = location.hostname.endsWith("github.io") ? "./data/" : "../site_data/";
  const cache = new Map();

  function load(path) {
    if (!cache.has(path)) {
      const p = fetch(base + path).then((r) => {
        if (!r.ok) {
          const err = new Error(`${r.status} ${path}`);
          err.status = r.status;
          throw err;
        }
        return r.json();
      });
      p.catch(() => cache.delete(path));
      cache.set(path, p);
    }
    return cache.get(path);
  }

  // Last two decimal digits, zero padded: 7 -> "07", 12688 -> "88".
  function shard(n) {
    return String(Number(n) % 100).padStart(2, "0");
  }
  function groupPath(id) {
    const n = String(id).split("-").pop();
    return `groups/${shard(n)}/${id}.json`;
  }
  function narratorPath(id) {
    return `narrator/${shard(id)}/${Number(id)}.json`;
  }

  let narratorsP = null;
  // narrators.json is columnar {cols, rows}; build Map id -> object once.
  function narrators() {
    if (!narratorsP) {
      narratorsP = load("narrators.json").then((d) => {
        const map = new Map();
        for (const row of d.rows) {
          const o = {};
          d.cols.forEach((c, i) => (o[c] = row[i]));
          map.set(o.id, o);
        }
        return map;
      });
      narratorsP.catch(() => (narratorsP = null));
    }
    return narratorsP;
  }

  window.ISNAD = {
    base,
    load,
    shard,
    narrators,
    meta: () => load("meta.json"),
    search: () => load("search.json"),
    numberingShard: (slug) => load(`search/n/${slug}.json`),
    hadithShard: (hid) => load(`search/h/${shard(hid)}.json`),
    group: (id) => load(groupPath(id)),
    narratorDetail: (id) => load(narratorPath(id)),
    groupPath,
    narratorPath,
    rawiUrl: (id) => `https://hdith.com/encyclopedia/rawi/p-${id}`,
    hadithUrl: (slug, hid) => `https://hdith.com/encyclopedia/book/${slug}/h/${hid}`,
  };
})();
