/* Orphaned Well Map — front end. Reads data/manifest.json, data/points.json,
 * and data/states/XX.json as written by pipeline/owm/build.py. */
(() => {
  "use strict";

  const BASEMAP = "https://tiles.openfreemap.org/styles/positron";
  const DATA = "data/";

  // join codes (must match build.py)
  const CATS = [
    { j: 3, key: "operator", label: "Operator found", desc: "Matched to a state record that names a company." },
    { j: 2, key: "placeholder", label: "State record names no operator", desc: "Matched, but the record says unknown, orphan, or similar." },
    { j: 1, key: "unmatched", label: "No matching state record", desc: "State data was joined, but this well wasn't found in it." },
    { j: 0, key: "noconfig", label: "State not joined yet", desc: "Only the USGS record is available for this state so far." },
  ];

  // API state code -> postal code (API Bulletin D12A; mirrors pipeline/owm/util.py)
  const API_STATE = Object.fromEntries(
    "AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AK HI"
      .split(" ").map((c, i) => [String(i + 1).padStart(2, "0"), c]));

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-US");
  const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
  const miles = (m) => (m / 1609.344).toFixed(m < 1609 ? 2 : 1).replace(/\.?0+$/, "") + " mi";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const state = {
    manifest: null, pts: null, map: null,
    show: new Set([0, 1, 2, 3]), stateFilter: "", operatorFilter: -1,
    details: {}, selected: -1, hasGlyphs: false,
  };

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  }

  async function loadBasemap() {
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 6000);
      const r = await fetch(BASEMAP, { signal: ctl.signal });
      clearTimeout(t);
      if (!r.ok) throw new Error(r.status);
      const style = await r.json();
      const sym = style.layers.find((l) => l.type === "symbol" && l.layout && l.layout["text-font"]);
      state.font = sym ? sym.layout["text-font"] : null;
      state.hasGlyphs = Boolean(style.glyphs && state.font);
      return style;
    } catch (e) {
      console.warn("Basemap unavailable, using plain background", e);
      return { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": css("--page") } }] };
    }
  }

  // ---------- data ----------

  function stateOf(i) {
    const st = state.manifest.states;
    let lo = 0, hi = st.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (st[mid].offset <= i) lo = mid; else hi = mid - 1;
    }
    return st[lo];
  }

  async function detail(i) {
    const s = stateOf(i);
    if (!state.details[s.code]) state.details[s.code] = getJSON(`${DATA}states/${s.code}.json`);
    const rows = await state.details[s.code];
    return { s, d: rows[i - s.offset] };
  }

  function featureCollection() {
    const { lon, lat, s, j, o, a } = state.pts;
    const sf = state.stateFilter ? state.manifest.state_codes.indexOf(state.stateFilter) : -1;
    const feats = [];
    for (let i = 0; i < lon.length; i++) {
      if (!state.show.has(j[i])) continue;
      if (sf >= 0 && s[i] !== sf) continue;
      if (state.operatorFilter >= 0 && o[i] !== state.operatorFilter) continue;
      feats.push({ type: "Feature", id: i, properties: { j: j[i], a: a[i] }, geometry: { type: "Point", coordinates: [lon[i], lat[i]] } });
    }
    return { type: "FeatureCollection", features: feats };
  }

  function bounds(fc) {
    if (!fc.features.length) return null;
    let w = 180, so = 90, e = -180, n = -90;
    for (const f of fc.features) {
      const [x, y] = f.geometry.coordinates;
      if (x < w) w = x; if (x > e) e = x; if (y < so) so = y; if (y > n) n = y;
    }
    return [[w, so], [e, n]];
  }

  function refresh(fit) {
    const fc = featureCollection();
    state.map.getSource("wells").setData(fc);
    if (fit) {
      const b = bounds(fc);
      if (b) state.map.fitBounds(b, { padding: 40, maxZoom: 11, duration: 600 });
    }
    renderLegend();
  }

  // ---------- map ----------

  function colorExpr() {
    return ["match", ["get", "j"],
      3, css("--c-operator"), 2, css("--c-placeholder"), 1, css("--c-unmatched"), css("--c-noconfig")];
  }

  function addLayers(map) {
    map.addSource("wells", { type: "geojson", data: featureCollection(), cluster: true, clusterRadius: 38, clusterMaxZoom: 9 });
    map.addLayer({
      id: "clusters", type: "circle", source: "wells", filter: ["has", "point_count"],
      paint: {
        "circle-color": css("--c-cluster"), "circle-opacity": 0.82,
        "circle-radius": ["step", ["get", "point_count"], 10, 50, 14, 500, 19, 5000, 25],
        "circle-stroke-width": 2, "circle-stroke-color": css("--surface"),
      },
    });
    if (state.hasGlyphs) {
      map.addLayer({
        id: "cluster-count", type: "symbol", source: "wells", filter: ["has", "point_count"],
        layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11, "text-font": state.font, "text-allow-overlap": true },
        paint: { "text-color": css("--surface") },
      });
    }
    map.addLayer({
      id: "wells", type: "circle", source: "wells", filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": colorExpr(),
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 4, 14, 7],
        "circle-stroke-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 1],
        "circle-stroke-color": ["case", ["boolean", ["feature-state", "sel"], false], css("--ink"), css("--surface")],
      },
    });

    map.on("click", "clusters", async (e) => {
      const f = e.features[0];
      const z = await map.getSource("wells").getClusterExpansionZoom(f.properties.cluster_id);
      map.easeTo({ center: f.geometry.coordinates, zoom: z });
    });
    map.on("click", "wells", (e) => select(e.features[0].id));
    for (const l of ["clusters", "wells"]) {
      map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", l, () => (map.getCanvas().style.cursor = ""));
    }

    const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on("mousemove", "wells", (e) => {
      const f = e.features[0];
      const cat = CATS.find((c) => c.j === f.properties.j);
      hover.setLngLat(f.geometry.coordinates)
        .setHTML(`${esc(cat.label)}${f.properties.j > 0 && stateOf(f.id).nearby ? ` · ${fmt(f.properties.a)} active within ${miles(state.manifest.params.radius_m)}` : ""}<br><span class="muted">Click for details</span>`)
        .addTo(map);
    });
    map.on("mouseleave", "wells", () => hover.remove());
  }

  function repaint() {
    const map = state.map;
    if (!map || !map.getLayer("wells")) return;
    map.setPaintProperty("wells", "circle-color", colorExpr());
    map.setPaintProperty("clusters", "circle-color", css("--c-cluster"));
    renderLegend();
  }

  // ---------- selection / detail ----------

  async function select(i) {
    const map = state.map;
    if (state.selected >= 0) map.setFeatureState({ source: "wells", id: state.selected }, { sel: false });
    state.selected = i;
    map.setFeatureState({ source: "wells", id: i }, { sel: true });
    const { s, d } = await detail(i);
    renderDetail(i, s, d);
  }

  function renderDetail(i, s, d) {
    const p = state.pts, m = state.manifest;
    const radius = miles(m.params.radius_m);
    const rows = [
      ["API / ID", d.id], ["Name", d.n], ["Type", d.t], ["USGS status", d.st],
      ["County", d.c ? `${d.c}, ${s.code}` : s.name],
      ["Coordinates", `${p.lat[i].toFixed(5)}, ${p.lon[i].toFixed(5)}`],
      ["Surface owner (USGS est.)", d.so], ["Mineral owner (USGS est.)", d.mo],
      ["Reported by", d.src], ["State data as of", d.sd],
    ].filter(([, v]) => v);

    let opHtml;
    if (!s.configured) {
      opHtml = `<p class="note">${esc(s.name)}'s well records haven't been joined yet, so the operator is unknown here. ${s.error ? `(${esc(s.error)})` : ""}</p>`;
    } else if (!d.m) {
      opHtml = `<p class="note">No record with this API number in ${esc(s.source || "the state file")}, and no well within ${m.params.loc_tolerance_m} m of this location.</p>`;
    } else {
      const how = d.m === "api" ? "Matched on API number."
        : d.m === "id" ? "Matched on the state's well ID (permit number)."
        : `Matched by location: the nearest state record, ${d.md} m away. Treat this as a lead, not a confirmed match.`;
      opHtml = `
        <div class="op">${d.opp ? `<span class="muted">${esc(d.op || "Blank")}</span>` : esc(d.op)}</div>
        ${d.opp ? `<p class="note">The state record lists no real operator.</p>` : ""}
        <p class="note">${esc(how)} ${esc(s.status_label || "State status")}: ${esc(d.ss || "–")}${d.ls ? ` · Lease: ${esc(d.ls)}` : ""}${d.sa && d.sa !== d.id ? ` · State API: ${esc(d.sa)}` : ""}</p>
        <p class="note">Source: ${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source || "state records")}</a>` : esc(s.source || "state records")}${s.verified ? "" : ' <span class="pill">unverified source</span>'}</p>`;
    }

    let nearHtml = "";
    if (s.configured && s.nearby) {
      if (!d.na) {
        nearHtml = `<p class="note">No active wells within ${radius} in the state file.</p>`;
      } else {
        nearHtml = `
          <p><strong>${fmt(d.na)}</strong> active well${d.na === 1 ? "" : "s"} within ${radius}.</p>
          ${d.no && d.no.length ? `<p class="note">Operators: ${d.no.map(([n, c]) => `${esc(n)} (${c})`).join(", ")}</p>` : ""}
          <table><thead><tr><th>Nearest</th><th>Operator / lease</th><th class="num">Distance</th></tr></thead><tbody>
          ${(d.nn || []).map(([api, op, lease, dist]) => `<tr><td>${esc(api)}</td><td>${esc(op)}${lease ? `<br><span class="muted">${esc(lease)}</span>` : ""}</td><td class="num">${miles(dist)}</td></tr>`).join("")}
          </tbody></table>`;
      }
    }

    $("#detail-body").innerHTML = `
      <h3>${esc(d.n || d.id || "Unnamed well")}</h3>
      <div class="muted">${esc(s.name)} · USGS orphaned well</div>
      <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      <h2>${esc(s.operator_label || "Last operator of record")}</h2>${opHtml}
      ${s.configured ? `<h2 style="margin-top:16px">Active wells nearby</h2>${nearHtml || `<p class="note">${esc(s.name)}'s well file has no current status, so active wells can't be identified.</p>`}` : ""}`;
    $("#detail").hidden = false;
    state.map.resize();
  }

  // ---------- sidebar ----------

  function counts() {
    const { j, s, o } = state.pts;
    const sf = state.stateFilter ? state.manifest.state_codes.indexOf(state.stateFilter) : -1;
    const c = [0, 0, 0, 0];
    for (let i = 0; i < j.length; i++) {
      if (sf >= 0 && s[i] !== sf) continue;
      if (state.operatorFilter >= 0 && o[i] !== state.operatorFilter) continue;
      c[j[i]]++;
    }
    return c;
  }

  function renderLegend() {
    const c = counts();
    $("#legend").innerHTML = CATS.map((cat) => `
      <li><label>
        <input type="checkbox" data-j="${cat.j}" ${state.show.has(cat.j) ? "checked" : ""}>
        <span class="swatch" style="background:${css("--c-" + cat.key)}"></span>
        <span>${esc(cat.label)}</span><span class="count">${fmt(c[cat.j])}</span>
        <span class="desc">${esc(cat.desc)}</span>
      </label></li>`).join("");
  }

  function renderOperators() {
    const m = state.manifest;
    const sf = state.stateFilter && m.states.find((s) => s.code === state.stateFilter);
    let ops;
    if (sf) {
      ops = m.operators.map((op, i) => ({ ...op, i, count: (op.by_state || {})[sf.code] || 0 }))
        .filter((op) => op.count > 0).sort((a, b) => b.count - a.count);
      $("#operators-title").textContent = sf.configured ? `Most orphaned wells, by ${(sf.operator_label || "last operator").toLowerCase()}` : "Most orphaned wells, by operator";
      $("#operators-note").textContent = "Click one to map its wells.";
    } else {
      ops = m.operators.map((op, i) => ({ ...op, i })).filter((op) => op.count > 0);
      const other = m.states.filter((s) => s.configured && s.operator_kind && s.operator_kind !== "last");
      $("#operators-title").textContent = "Most orphaned wells, by last operator";
      $("#operators-note").textContent = "Counts wells matched to a state record that names a real operator. Click one to map its wells." +
        (other.length ? ` Not included: ${other.map((s) => s.name).join(", ")}, whose records give a different operator (select the state to see it).` : "");
    }
    const el = $("#operators");
    if (!ops.length) {
      el.innerHTML = `<li class="muted small">No operators identified yet${state.stateFilter ? " in this state" : ""}. Operators appear once a state's records are joined.</li>`;
      return;
    }
    el.innerHTML = ops.slice(0, 15).map((op) => `
      <li><button type="button" data-op="${op.i}" aria-pressed="${state.operatorFilter === op.i}">
        <span>${esc(op.name)}<span class="st">${esc((sf ? op.states : op.states.filter((c) => { const s = m.states.find((x) => x.code === c); return !s || (s.operator_kind || "last") === "last"; })).join(", "))}</span></span>
        <span class="n">${fmt(op.count)}</span>
      </button></li>`).join("");
  }

  function renderStates() {
    const m = state.manifest;
    $("#states-table tbody").innerHTML = [...m.states].sort((a, b) => b.count - a.count).map((s) => {
      const st = s.stats || {};
      return `<tr data-state="${s.code}">
        <td>${esc(s.name)}${s.configured ? (s.verified ? "" : '<span class="tag">unverified</span>') : '<span class="tag">not joined</span>'}</td>
        <td class="num">${fmt(s.count)}</td>
        <td class="num">${s.configured ? pct(st.with_operator || 0, s.count) : "–"}</td>
        <td class="num">${s.configured && s.nearby ? pct(st.with_nearby_active || 0, s.count) : "–"}</td></tr>`;
    }).join("");
    document.querySelectorAll(".radius").forEach((e) => (e.textContent = miles(m.params.radius_m)));
  }

  function renderHeader() {
    const m = state.manifest;
    const total = m.states.reduce((a, s) => a + s.count, 0);
    const joined = m.states.filter((s) => s.configured);
    const withOp = joined.reduce((a, s) => a + ((s.stats || {}).with_operator || 0), 0);
    $("#headline").textContent = `${fmt(total)} unplugged orphaned wells in ${m.states.length} states (USGS, 2026)` +
      (joined.length ? ` · operator identified for ${fmt(withOp)} so far` : "");
    const notes = [];
    if (m.demo) notes.push("<strong>Synthetic demo data.</strong> These points are test fixtures, not real wells.");
    if (!joined.length) notes.push("No state records have been joined yet, so the map shows USGS locations only.");
    else if (joined.some((s) => !s.verified)) notes.push("Some state joins haven't been spot-checked yet and are marked “unverified.”");
    if (m.usgs.rows !== m.usgs.loaded) notes.push(`${fmt(m.usgs.rows - m.usgs.loaded)} USGS rows without usable coordinates or state aren't mapped.`);
    if (notes.length) { $("#banner").innerHTML = notes.join(" "); $("#banner").hidden = false; }

    const states = m.states.filter((s) => s.configured);
    $("#about-body").innerHTML = `
      <p><strong>Wells:</strong> ${esc(m.usgs.citation || m.usgs.title)}
      (<a href="https://doi.org/${esc(m.usgs.doi)}" target="_blank" rel="noopener">doi:${esc(m.usgs.doi)}</a>, public domain).
      ${fmt(m.usgs.loaded)} of ${fmt(m.usgs.rows)} rows mapped. The USGS file has no operator data, and its surface and mineral ownership figures are estimates, not official records.</p>
      <p><strong>Last operator:</strong> each USGS well is matched to state well records by its 10-digit API number
      (state + county + well), ignoring sidetrack suffixes. If a well has no usable API number, the nearest state record within
      ${m.params.loc_tolerance_m} m is used and labelled as a location match. When an API appears on several state rows,
      the most recent row naming a real company wins, so the operator shown may be the last company before the well was
      orphaned, not the current holder of record.</p>
      <p><strong>Active wells nearby:</strong> state wells with an active or producing status within
      ${miles(m.params.radius_m)}. This shows active wells, not lease boundaries. A nearby active operator isn't legally responsible
      for an orphaned well, but it shows who is still working the area.</p>
      <p><strong>State sources joined:</strong> ${states.length ? states.map((s) => `${esc(s.name)} (${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source || "source")}</a>` : esc(s.source || "source")}${s.verified ? "" : ", unverified"})`).join("; ") : "none yet."}</p>
      <p><strong>Known limits:</strong> operator names are grouped loosely (case, punctuation, and suffixes like “LLC” or “Inc” are ignored),
      so affiliated companies under different names are counted separately. States update their files on their own schedules.</p>
      <p class="muted small">Data built ${esc(m.built_at)}.</p>`;
  }

  function populateStateSelect() {
    const sel = $("#state-select");
    for (const s of [...state.manifest.states].sort((a, b) => a.name.localeCompare(b.name))) {
      const o = document.createElement("option");
      o.value = s.code;
      o.textContent = `${s.name} (${fmt(s.count)})`;
      sel.appendChild(o);
    }
  }

  function setState(code) {
    state.stateFilter = code;
    $("#state-select").value = code;
    renderOperators();
    refresh(true);
  }

  function setOperator(i) {
    state.operatorFilter = i;
    $("#operator-filter").hidden = i < 0;
    if (i >= 0) $("#operator-name").textContent = state.manifest.operators[i].name;
    renderOperators();
    refresh(i >= 0);
  }

  async function search(q) {
    const msg = $("#search-msg");
    const digits = q.replace(/\D/g, "");
    const needle = q.trim().toLowerCase();
    if (!needle) return;
    msg.textContent = "Searching…";
    // narrow by API state prefix when possible to avoid loading every state file
    const byPrefix = digits.length >= 10 && API_STATE[digits.slice(0, 2)];
    const codes = state.stateFilter ? [state.stateFilter]
      : byPrefix && state.manifest.state_codes.includes(byPrefix) ? [byPrefix]
      : state.manifest.state_codes;
    for (const code of codes) {
      const s = state.manifest.states.find((x) => x.code === code);
      if (!state.details[code]) state.details[code] = getJSON(`${DATA}states/${code}.json`);
      const rows = await state.details[code];
      const k = rows.findIndex((d) => {
        const id = String(d.id || "").toLowerCase();
        return id === needle || (digits.length >= 10 && id.replace(/\D/g, "").startsWith(digits.slice(0, 10)));
      });
      if (k >= 0) {
        const i = s.offset + k;
        msg.textContent = "";
        if (!state.show.has(state.pts.j[i])) { state.show.add(state.pts.j[i]); }
        if (state.operatorFilter >= 0 && state.pts.o[i] !== state.operatorFilter) setOperator(-1);
        refresh(false);
        state.map.flyTo({ center: [state.pts.lon[i], state.pts.lat[i]], zoom: 13 });
        select(i);
        return;
      }
    }
    msg.textContent = "No well with that API or ID.";
  }

  function wire() {
    $("#legend").addEventListener("change", (e) => {
      const j = Number(e.target.dataset.j);
      e.target.checked ? state.show.add(j) : state.show.delete(j);
      refresh(false);
    });
    $("#state-select").addEventListener("change", (e) => setState(e.target.value));
    $("#operators").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-op]");
      if (!b) return;
      const i = Number(b.dataset.op);
      setOperator(state.operatorFilter === i ? -1 : i);
    });
    $("#operator-clear").addEventListener("click", () => setOperator(-1));
    $("#states-table tbody").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-state]");
      if (tr) setState(tr.dataset.state);
    });
    $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); search($("#search").value); });
    $("#detail-close").addEventListener("click", () => {
      $("#detail").hidden = true;
      if (state.selected >= 0) state.map.setFeatureState({ source: "wells", id: state.selected }, { sel: false });
      state.selected = -1;
      state.map.resize();
    });
    $("#about-btn").addEventListener("click", () => $("#about").showModal());
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", repaint);
  }

  function showEmpty(html) {
    $("#map-empty").innerHTML = `<div>${html}</div>`;
    $("#map-empty").hidden = false;
    $("#headline").textContent = "No data built yet";
  }

  async function init() {
    let manifest, pts;
    try {
      [manifest, pts] = await Promise.all([getJSON(DATA + "manifest.json"), getJSON(DATA + "points.json")]);
    } catch (e) {
      showEmpty(`<p><strong>Data not built.</strong></p><p>Download the USGS 2026 orphaned well file
        (<a href="https://doi.org/10.5066/P13FHBYG">doi:10.5066/P13FHBYG</a>), then run:</p>
        <p><code>cd pipeline && python -m owm.build --usgs /path/to/file.csv</code></p>
        <p class="muted small">${esc(e.message)}</p>`);
      return;
    }
    state.manifest = manifest;
    state.pts = pts;
    renderHeader();
    populateStateSelect();
    renderLegend();
    renderOperators();
    renderStates();
    wire();

    const style = await loadBasemap();
    const map = new maplibregl.Map({
      container: "map", style, center: [-96, 38.5], zoom: 3.4, attributionControl: { compact: true,
        customAttribution: 'Wells: <a href="https://doi.org/10.5066/P13FHBYG">USGS</a>' },
    });
    state.map = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      addLayers(map);
      window.__mapReady = true;
    });
  }

  init();
})();
