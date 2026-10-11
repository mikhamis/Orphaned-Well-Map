/* Orphaned Well Map — front end. Reads data/manifest.json, data/points.json,
 * and data/states/XX.json as written by pipeline/owm/build.py. */
(() => {
  "use strict";

  // Set window.OWM_BASEMAP = null before this script to skip the tile basemap
  // (e.g. where the page can't reach tile servers); state outlines are used instead.
  const BASEMAP = window.OWM_BASEMAP === undefined ? "https://tiles.openfreemap.org/styles/positron" : window.OWM_BASEMAP;
  const DATA = "data/";

  // join codes (must match build.py)
  const CATS = [
    { j: 3, key: "operator", label: "Operator found", desc: "Matched to a state record that names a company." },
    { j: 2, key: "placeholder", label: "State record names no operator", desc: "Matched, but the record says unknown, orphan, or similar." },
    { j: 1, key: "unmatched", label: "No matching state record", desc: "State data was joined, but this well wasn't found in it." },
    { j: 0, key: "noconfig", label: "USGS record only", desc: "This state's own well records aren't connected yet, so no operator is shown." },
  ];

  // API state code -> postal code (API Bulletin D12A; mirrors pipeline/owm/util.py)
  const API_STATE = Object.fromEntries(
    "AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AK HI"
      .split(" ").map((c, i) => [String(i + 1).padStart(2, "0"), c]));

  // Land-ownership classes, by index stored per well (must match OWNERSHIP in usgs.py).
  const OWN_CATS = [
    { j: 4, key: "operator", label: "Federal surface", desc: "Surface managed by a federal agency (USGS estimate from BLM's land map)." },
    { j: 3, key: "placeholder", label: "Federal minerals, non-federal surface", desc: "Split estate. Only mapped in New Mexico, Colorado, North Dakota and Utah." },
    { j: 2, key: "unmatched", label: "State, local or tribal", desc: "State or local government surface, or tribal surface or minerals." },
    { j: 1, key: "private", label: "Private (confirmed)", desc: "Land map identifies the surface as private." },
    { j: 0, key: "noconfig", label: "Not determined", desc: "Not federal, state or tribal on the land map; owner not identified. Most of these are likely private." },
  ];
  const LENSES = {
    match: { field: "j", cats: CATS },
    owner: { field: "w", cats: OWN_CATS },
  };

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("en-US");
  const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
  const miles = (m) => (m / 1609.344).toFixed(m < 1609 ? 2 : 1).replace(/\.?0+$/, "") + " mi";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const state = {
    manifest: null, pts: null, map: null,
    lens: "match", showBy: { match: new Set([0, 1, 2, 3]), owner: new Set([0, 1, 2, 3, 4]) },
    stateFilter: "", operatorFilter: -1, agencyFilter: -1,
    risk: null, showRisk: true, riskOperator: -1,
    details: {}, selected: -1, hasGlyphs: false,
  };

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  }

  function outlineStyle() {
    return {
      version: 8,
      sources: { states: { type: "geojson", data: "us-states.geojson" } },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": css("--page") } },
        { id: "states-fill", type: "fill", source: "states", paint: { "fill-color": css("--surface") } },
        { id: "states-line", type: "line", source: "states", paint: { "line-color": css("--muted"), "line-width": 0.6, "line-opacity": 0.6 } },
      ],
    };
  }

  async function loadBasemap() {
    if (!BASEMAP) return outlineStyle();
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
      console.warn("Basemap unavailable, using state outlines", e);
      return outlineStyle();
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
    const w = state.pts.w || [], g = state.pts.g || [];
    const lensVals = state.pts[LENSES[state.lens].field] || [], show = state.showBy[state.lens];
    const sf = state.stateFilter ? state.manifest.state_codes.indexOf(state.stateFilter) : -1;
    const feats = [];
    for (let i = 0; i < lon.length; i++) {
      if (!show.has(lensVals[i] ?? 0)) continue;
      if (sf >= 0 && s[i] !== sf) continue;
      if (state.operatorFilter >= 0 && o[i] !== state.operatorFilter) continue;
      if (state.agencyFilter >= 0 && g[i] !== state.agencyFilter) continue;
      feats.push({ type: "Feature", id: i, properties: { j: j[i], a: a[i], w: w[i] ?? 0 }, geometry: { type: "Point", coordinates: [lon[i], lat[i]] } });
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
    const { field, cats } = LENSES[state.lens];
    const pairs = cats.filter((c) => c.key !== "noconfig").flatMap((c) => [c.j, css("--c-" + c.key)]);
    return ["match", ["get", field], ...pairs, css("--c-noconfig")];
  }

  // Two heat layers, toggled by visibility: all wells, and (ownership view) only wells
  // on federal land or minerals. A heatmap layer doesn't redraw reliably when its
  // filter or data-driven weight changes after creation, so each gets a fixed filter.
  const HEAT_LAYERS = { heat: "match", "heat-fed": "owner" };

  function syncHeatLayers() {
    for (const [id, lens] of Object.entries(HEAT_LAYERS)) {
      state.map.setLayoutProperty(id, "visibility", state.lens === lens ? "visible" : "none");
    }
  }

  // Heat map below POINTS_ZOOM, individual wells above it, cross-faded.
  const POINTS_ZOOM = 7;

  function heatColorExpr() {
    const steps = [0, 1, 2, 3, 4, 5, 6].map((k) => css(`--heat-${k}`));
    // Fade in from a transparent copy of the lightest step; transparent black leaves a grey halo.
    const h = steps[0].replace("#", "");
    const clear = `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},0)`;
    return ["interpolate", ["linear"], ["heatmap-density"],
      0, clear, 0.05, steps[0], 0.2, steps[1], 0.4, steps[2],
      0.6, steps[3], 0.75, steps[4], 0.9, steps[5], 1, steps[6]];
  }

  function riskCollection() {
    const r = state.risk, feats = [];
    const sf = state.stateFilter ? state.manifest.state_codes.indexOf(state.stateFilter) : -1;
    for (let i = 0; i < r.lon.length; i++) {
      if (sf >= 0 && r.s[i] !== sf) continue;
      if (state.riskOperator >= 0 && r.o[i] !== state.riskOperator) continue;
      feats.push({ type: "Feature", id: i, properties: {}, geometry: { type: "Point", coordinates: [r.lon[i], r.lat[i]] } });
    }
    return { type: "FeatureCollection", features: feats };
  }

  function selectRisk(i) {
    const r = state.risk, m = state.manifest;
    const s = m.states[r.s[i]];
    const op = r.o[i] >= 0 ? r.operators[r.o[i]] : null;
    if (state.selected >= 0) state.map.setFeatureState({ source: "wells", id: state.selected }, { sel: false });
    state.selected = -1;
    $("#detail-body").innerHTML = `
      <h3>${esc(r.n[i] || r.id[i] || "Unnamed well")}</h3>
      <div class="muted">${esc(s.name)} · inactive well with an owner on record</div>
      <dl>
        <dt>API</dt><dd>${esc(r.id[i] || "–")}</dd>
        <dt>Coordinates</dt><dd>${r.lat[i].toFixed(5)}, ${r.lon[i].toFixed(5)}</dd>
        <dt>${esc(s.status_label || "State status")}</dt><dd>${esc(r.st[i])}</dd>
      </dl>
      <h2>Operator of record</h2>
      <div class="op">${op ? esc(op) : '<span class="muted">No operator named</span>'}</div>
      <p class="note">Not an orphan yet: ${esc(s.name)} still lists a responsible operator. ${esc((s.at_risk || {}).definition || "")}</p>
      <p class="note">Source: ${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source || "state records")}</a>` : esc(s.source || "state records")}. Not part of the USGS orphaned well count.</p>`;
    $("#detail").hidden = false;
    state.map.resize();
  }

  function refreshRisk(fit) {
    if (!state.risk || !state.map || !state.map.getSource("risk")) return;
    const fc = riskCollection();
    state.map.getSource("risk").setData(fc);
    state.map.setLayoutProperty("risk", "visibility", state.showRisk ? "visible" : "none");
    if (fit) { const b = bounds(fc); if (b) state.map.fitBounds(b, { padding: 40, maxZoom: 11, duration: 600 }); }
  }

  function renderRisk() {
    const r = state.risk, m = state.manifest;
    $("#risk-section").hidden = !r || !r.lon.length;
    if (!r) return;
    const sf = state.stateFilter;
    const states = m.states.filter((s) => s.at_risk && (!sf || s.code === sf));
    $("#risk-toggle-count").textContent = fmt(states.reduce((a, s) => a + s.at_risk.count, 0));
    const ops = r.operators.map((name, i) => {
      const by = r.operator_states[String(i)] || {};
      return { name, i, n: sf ? (by[sf] || 0) : Object.values(by).reduce((a, b) => a + b, 0), st: Object.keys(by) };
    }).filter((o) => o.n > 0).sort((a, b) => b.n - a.n).slice(0, 12);
    $("#risk-operators").innerHTML = ops.map((o) => `
      <li><button type="button" data-risk-op="${o.i}" aria-pressed="${state.riskOperator === o.i}">
        <span>${esc(o.name)}<span class="st">${esc(o.st.join(", "))}</span></span><span class="n">${fmt(o.n)}</span>
      </button></li>`).join("");
    $("#risk-states").textContent = states.length ? "Included: " + states.map((s) => `${s.name} (${s.at_risk.definition})`).join(" ") : "";
  }

  function addLayers(map) {
    map.addSource("wells", { type: "geojson", data: featureCollection() });
    for (const [id, lens] of Object.entries(HEAT_LAYERS)) {
      map.addLayer({
        id, type: "heatmap", source: "wells", maxzoom: POINTS_ZOOM + 2,
        ...(lens === "owner" ? { filter: [">=", ["get", "w"], 3] } : {}),
        layout: { visibility: state.lens === lens ? "visible" : "none" },
        paint: {
          // Tuned so dense basins (SE Ohio, W Pennsylvania, central Oklahoma) still separate
          // from sparse areas at national zoom instead of saturating into one blob.
          "heatmap-weight": 1,
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 3, 0.04, 5, 0.1, POINTS_ZOOM, 0.22, POINTS_ZOOM + 2, 0.6],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 4, 5, 7, POINTS_ZOOM, 12, POINTS_ZOOM + 2, 18],
          "heatmap-color": heatColorExpr(),
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM, 0.92, POINTS_ZOOM + 1.5, 0],
        },
      });
    }
    map.addLayer({
      id: "wells", type: "circle", source: "wells", minzoom: POINTS_ZOOM - 0.5,
      paint: {
        "circle-color": colorExpr(),
        "circle-radius": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM, 2.5, 10, 4.5, 14, 7],
        "circle-opacity": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM - 0.5, 0, POINTS_ZOOM + 1, 1],
        "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM - 0.5, 0, POINTS_ZOOM + 1, 1],
        "circle-stroke-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 1],
        "circle-stroke-color": ["case", ["boolean", ["feature-state", "sel"], false], css("--ink"), css("--surface")],
      },
    });

    // Clicking the heat map zooms toward the wells under the cursor.
    map.on("click", (e) => {
      if (map.getZoom() >= POINTS_ZOOM || map.queryRenderedFeatures(e.point, { layers: ["wells"] }).length) return;
      map.easeTo({ center: e.lngLat, zoom: Math.min(POINTS_ZOOM + 1.5, map.getZoom() + 2.5) });
    });
    if (state.risk) {
      map.addSource("risk", { type: "geojson", data: riskCollection() });
      map.addLayer({
        id: "risk", type: "circle", source: "risk", minzoom: POINTS_ZOOM - 0.5,
        layout: { visibility: state.showRisk ? "visible" : "none" },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM, 3, 10, 5, 14, 8],
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-width": ["case", ["boolean", ["feature-state", "sel"], false], 3, 1.6],
          "circle-stroke-color": css("--ink-2"),
          "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], POINTS_ZOOM - 0.5, 0, POINTS_ZOOM + 1, 0.9],
        },
      }, "wells");
      map.on("click", "risk", (e) => {
        if (map.queryRenderedFeatures(e.point, { layers: ["wells"] }).length) return;
        selectRisk(e.features[0].id);
      });
      map.on("mouseenter", "risk", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "risk", () => (map.getCanvas().style.cursor = ""));
    }
    map.on("click", "wells", (e) => select(e.features[0].id));
    map.on("mouseenter", "wells", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "wells", () => (map.getCanvas().style.cursor = ""));

    const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on("mousemove", "wells", (e) => {
      const f = e.features[0];
      const { field, cats } = LENSES[state.lens];
      const cat = cats.find((c) => c.j === f.properties[field]) || cats[cats.length - 1];
      hover.setLngLat(f.geometry.coordinates)
        .setHTML(`${esc(cat.label)}${f.properties.j > 0 && stateOf(f.id).nearby ? ` · ${fmt(f.properties.a)} active within ${miles(state.manifest.params.radius_m)}` : ""}<br><span class="muted">Click for details</span>`)
        .addTo(map);
    });
    map.on("mouseleave", "wells", () => hover.remove());

    const syncMode = () => {
      const points = map.getZoom() >= POINTS_ZOOM;
      $("#zoom-hint").hidden = points;
      $("#legend-heat").hidden = points;
      $("#legend-points-note").hidden = points;
    };
    map.on("zoomend", syncMode);
    syncMode();
  }

  function repaint() {
    const map = state.map;
    if (!map || !map.getLayer("wells")) return;
    map.setPaintProperty("wells", "circle-color", colorExpr());
    for (const id of Object.keys(HEAT_LAYERS)) map.setPaintProperty(id, "heatmap-color", heatColorExpr());
    if (map.getLayer("risk")) map.setPaintProperty("risk", "circle-stroke-color", css("--ink-2"));
    syncHeatLayers();
    if (map.getLayer("states-fill")) {
      map.setPaintProperty("bg", "background-color", css("--page"));
      map.setPaintProperty("states-fill", "fill-color", css("--surface"));
      map.setPaintProperty("states-line", "line-color", css("--muted"));
    }
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

  function verifiedNote(s) {
    const v = s.verification;
    if (!v) return "";
    return `<p class="note"><span class="pill ok">✓ checked</span> ${fmt(v.agree)} of ${fmt(v.checked)} ${esc(s.name)} operators matched a second agency source (${esc(v.date)}). See About the data.</p>`;
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
      opHtml = `<p class="note">${esc(s.name)}'s own well records aren't connected to this map yet, so only the USGS record is shown and the operator isn't known here.</p>`;
    } else if (!d.m) {
      opHtml = `<p class="note">No record with this API number in ${esc(s.source || "the state file")}, and no well within ${m.params.loc_tolerance_m} m of this location.</p>`;
    } else {
      const how = d.m === "api" ? "Matched on API number."
        : d.m === "id" ? "Matched on the state's well ID (permit number)."
        : (s.location_match || {}).name_match
          ? `Matched by location and lease name: a state well ${d.md} m away on a lease with the same name. This identifies the lease, not necessarily this exact well.`
          : `Matched by location: the nearest state record, ${d.md} m away. Treat this as a lead, not a confirmed match.`;
      opHtml = `
        <div class="op">${d.opp ? `<span class="muted">${esc(d.op || "Blank")}</span>` : esc(d.op)}</div>
        ${d.opp ? `<p class="note">The state record lists no real operator.</p>` : ""}
        <p class="note">${esc(how)} ${esc(s.status_label || "State status")}: ${esc(d.ss || "–")}${d.ls ? ` · Lease: ${esc(d.ls)}` : ""}${d.sa && d.sa !== d.id ? ` · State API: ${esc(d.sa)}` : ""}</p>
        <p class="note">Source: ${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source || "state records")}</a>` : esc(s.source || "state records")}</p>
        ${d.md != null && d.m !== "location" && d.md > m.params.disagree_m ? `<p class="note"><strong>Location check:</strong> the USGS and state coordinates for this well are ${miles(d.md)} apart. The dot uses the USGS location.</p>` : ""}
        ${verifiedNote(s)}`;
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
    const { s, o } = state.pts, g = state.pts.g || [];
    const vals = state.pts[LENSES[state.lens].field] || [];
    const sf = state.stateFilter ? state.manifest.state_codes.indexOf(state.stateFilter) : -1;
    const c = [0, 0, 0, 0, 0];
    for (let i = 0; i < s.length; i++) {
      if (sf >= 0 && s[i] !== sf) continue;
      if (state.operatorFilter >= 0 && o[i] !== state.operatorFilter) continue;
      if (state.agencyFilter >= 0 && g[i] !== state.agencyFilter) continue;
      c[vals[i] ?? 0]++;
    }
    return c;
  }

  function renderLegend() {
    const c = counts(), show = state.showBy[state.lens];
    const owner = state.lens === "owner";
    $("#legend-heat-title").textContent = owner ? "Orphaned wells on federal land or minerals, per area" : "Orphaned wells per area";
    $("#agencies-section").hidden = !owner;
    $("#legend").innerHTML = LENSES[state.lens].cats.map((cat) => `
      <li><label>
        <input type="checkbox" data-j="${cat.j}" ${show.has(cat.j) ? "checked" : ""}>
        <span class="swatch" style="background:${css("--c-" + cat.key)}"></span>
        <span>${esc(cat.label)}</span><span class="count">${fmt(c[cat.j])}</span>
        <span class="desc">${esc(cat.desc)}</span>
      </label></li>`).join("");
  }

  function setLens(lens) {
    state.lens = lens;
    document.querySelectorAll("#lens button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lens === lens)));
    if (lens !== "owner") state.agencyFilter = -1;
    renderAgencies();
    refresh(false);
    repaint();
  }

  const AGENCY_NAMES = {
    USFS: "U.S. Forest Service", BLM: "Bureau of Land Management", BIA: "Bureau of Indian Affairs (tribal trust land)",
    FWS: "Fish and Wildlife Service", USACE: "Army Corps of Engineers", DOD: "Defense Department", NPS: "National Park Service",
    USAF: "Air Force", USBR: "Bureau of Reclamation", ARMY: "Army", USMC: "Marine Corps", NAVY: "Navy",
  };

  function renderAgencies() {
    const m = state.manifest, g = state.pts.g || [], s = state.pts.s;
    const sf = state.stateFilter ? m.state_codes.indexOf(state.stateFilter) : -1;
    const n = (m.fed_agencies || []).map(() => 0);
    g.forEach((gi, i) => { if (gi >= 0 && (sf < 0 || s[i] === sf)) n[gi]++; });
    const rows = (m.fed_agencies || []).map((code, i) => ({ code, i, n: n[i] })).filter((r) => r.n > 0).sort((a, b) => b.n - a.n);
    $("#agencies").innerHTML = rows.length ? rows.map((r) => `
      <li><button type="button" data-agency="${r.i}" aria-pressed="${state.agencyFilter === r.i}">
        <span>${esc(AGENCY_NAMES[r.code] || r.code)}</span><span class="n">${fmt(r.n)}</span>
      </button></li>`).join("") : '<li class="muted small">No wells on federal land here.</li>';
  }

  function renderOperators() {
    const m = state.manifest;
    const sf = state.stateFilter && m.states.find((s) => s.code === state.stateFilter);
    let ops;
    if (sf) {
      ops = m.operators.map((op, i) => ({ ...op, i, count: (op.by_state || {})[sf.code] || 0 }))
        .filter((op) => op.count > 0).sort((a, b) => b.count - a.count);
      const lbl = sf.operator_label || "Last operator";
      $("#operators-title").textContent = sf.configured ? `Most orphaned wells, by ${lbl[0].toLowerCase()}${lbl.slice(1)}` : "Most orphaned wells, by operator";
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
        <td>${esc(s.name)}${s.configured ? (s.verified ? '<span class="tag ok" title="Operator matches checked against a second agency source">✓ checked</span>' : '<span class="tag">not yet checked</span>') : '<span class="tag">USGS only</span>'}</td>
        <td class="num">${fmt(s.count)}</td>
        <td class="num">${s.configured ? pct(st.with_operator || 0, s.count) : "–"}</td>
        <td class="num">${s.configured && s.nearby ? pct(st.with_nearby_active || 0, s.count) : "–"}</td>
        <td class="num">${s.at_risk ? fmt(s.at_risk.count) : "–"}</td></tr>`;
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
    if (!joined.length) notes.push("No state well records are connected yet, so the map shows USGS records only.");
    else {
      const list = (xs) => new Intl.ListFormat("en", { type: "conjunction" }).format(xs);
      const missing = m.states.filter((s) => !s.configured);
      notes.push(`State well records are connected for ${joined.length} of ${m.states.length} states (${fmt(joined.reduce((a, s) => a + s.count, 0))} of ${fmt(total)} wells).` +
        (missing.length ? ` Not yet connected: ${list(missing.map((s) => s.name))}.` : ""));
      const checked = joined.filter((s) => s.verified).length;
      notes.push(`Operators cross-checked against a second source in ${checked} of ${joined.length}; see About the data.`);
    }
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
      <p><strong>State sources connected:</strong> ${states.length ? states.map((s) => `${esc(s.name)} (${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source || "source")}</a>` : esc(s.source || "source")})`).join("; ") : "none yet."}</p>
      <p><strong>How the matches were checked:</strong></p>
      <ul>${states.map((s) => {
        const v = s.verification, st = s.stats || {};
        return `<li><strong>${esc(s.name)}:</strong> ${v ? `${fmt(v.agree)} of ${fmt(v.checked)} operators agree. ${esc(v.method)} (${esc(v.date)})` : esc(s.verification_note || "not yet cross-checked.")}
          USGS and state coordinates agree within ${st.match_dist_median_m ?? "–"} m for the median well; ${fmt(st.location_disagrees || 0)} wells differ by more than ${miles(m.params.disagree_m)} and are flagged.</li>`;
      }).join("")}</ul>
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
    renderAgencies();
    renderRisk();
    refreshRisk(false);
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
        const lv = (state.pts[LENSES[state.lens].field] || [])[i] ?? 0;
        state.showBy[state.lens].add(lv);
        if (state.agencyFilter >= 0 && (state.pts.g || [])[i] !== state.agencyFilter) { state.agencyFilter = -1; renderAgencies(); }
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
      const j = Number(e.target.dataset.j), show = state.showBy[state.lens];
      e.target.checked ? show.add(j) : show.delete(j);
      refresh(false);
    });
    $("#state-select").addEventListener("change", (e) => setState(e.target.value));
    document.querySelectorAll("#lens button").forEach((b) => b.addEventListener("click", () => setLens(b.dataset.lens)));
    $("#agencies").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-agency]");
      if (!b) return;
      const i = Number(b.dataset.agency);
      state.agencyFilter = state.agencyFilter === i ? -1 : i;
      renderAgencies();
      refresh(state.agencyFilter >= 0);
    });
    $("#operators").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-op]");
      if (!b) return;
      const i = Number(b.dataset.op);
      setOperator(state.operatorFilter === i ? -1 : i);
    });
    $("#operator-clear").addEventListener("click", () => setOperator(-1));
    $("#risk-toggle").addEventListener("change", (e) => { state.showRisk = e.target.checked; refreshRisk(false); });
    $("#risk-operators").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-risk-op]");
      if (!b) return;
      const i = Number(b.dataset.riskOp);
      state.riskOperator = state.riskOperator === i ? -1 : i;
      state.showRisk = true; $("#risk-toggle").checked = true;
      renderRisk();
      refreshRisk(state.riskOperator >= 0);
    });
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
      state.risk = await getJSON(DATA + "atrisk.json").catch(() => null);
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
    renderAgencies();
    renderRisk();
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
