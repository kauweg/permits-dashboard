const state = {
  meta: null,
  summary: null,
  selectedSlice: null,
  map: null,
  mapLayer: null,
};

const CATEGORIES = [
  "New SFR / ADU",
  "Townhome / Rowhouse / Duplex",
  "Multifamily / Apartment",
  "Demo",
];

const DEFAULT_YEARS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];

const byId = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat().format(Number(n || 0));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
}[m]));

function showFatal(message) {
  console.error(message);
  const errors = byId("loadErrors");
  if (errors) {
    errors.innerHTML = `<div style="font-weight:700;">Dashboard load error:</div><div>${esc(message)}</div>`;
  }
}

function qs(o) {
  return new URLSearchParams(o).toString();
}

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  const text = await r.text();

  if (!r.ok) {
    throw new Error(`${url} failed: ${r.status} ${r.statusText}. ${text.slice(0, 300)}`);
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`${url} did not return JSON. First 300 chars: ${text.slice(0, 300)}`);
  }
}

function years() {
  return state.meta?.years || state.summary?.years || DEFAULT_YEARS;
}

function filters() {
  return {
    jurisdiction: byId("jurisdiction")?.value || "all",
    category: byId("category")?.value || "all",
    market: byId("market")?.value || "all",
    neighborhood: byId("neighborhood")?.value || "all",
    start_year: byId("startYear")?.value || "2016",
    end_year: byId("endYear")?.value || "2026",
  };
}

function loadMsgs(notes, errors) {
  const notesEl = byId("loadNotes");
  const errorsEl = byId("loadErrors");

  if (notesEl) {
    notesEl.innerHTML = (notes || [])
      .map((n) => `<span class="note-pill">${esc(n)}</span>`)
      .join("");
  }

  if (errorsEl) {
    errorsEl.innerHTML = (errors || [])
      .map((e) => `<div>${esc(e)}</div>`)
      .join("");
  }
}

function populate(id, items, label) {
  const s = byId(id);
  if (!s) return;

  const cur = s.value || "all";
  s.innerHTML = `<option value="all">${label}</option>`;

  (items || []).forEach((x) => {
    const o = document.createElement("option");
    o.value = x;
    o.textContent = x;
    s.appendChild(o);
  });

  if ([...s.options].some((o) => o.value === cur)) {
    s.value = cur;
  }
}

async function loadMeta() {
  state.meta = await fetchJson("/api/meta");

  populate("category", state.meta.categories || CATEGORIES, "All");
  populate("market", state.meta.markets || [], "All markets");
  populate("neighborhood", state.meta.neighborhoods || [], "All neighborhoods");

  loadMsgs(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  state.summary = await fetchJson(`/api/summary?${qs(filters())}`);

  loadMsgs(state.summary.load_notes || [], state.summary.load_errors || []);

  renderCards();
  renderChart();
  renderMarkets();
  renderNeighborhoods();
  renderMap();
}

function validPnwPoint(lat, lng) {
  return Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    lat >= 47.0 &&
    lat <= 48.0 &&
    lng >= -123.0 &&
    lng <= -121.0;
}

function mapPoints() {
  let rows = state.summary?.map_points || [];

  if (state.selectedSlice?.year) {
    rows = rows.filter((r) => Number(r.year) === Number(state.selectedSlice.year));
  }

  if (state.selectedSlice?.category) {
    rows = rows.filter((r) => r.category === state.selectedSlice.category);
  }

  return rows;
}

function neighborhoodRows() {
  let rows = state.summary?.neighborhood_rows || [];

  if (state.selectedSlice?.year) {
    const y = String(state.selectedSlice.year);
    rows = rows.filter((r) => Number(r.years?.[y]?.Total || 0) > 0);
  }

  if (state.selectedSlice?.category) {
    const y = state.selectedSlice?.year ? String(state.selectedSlice.year) : null;

    rows = rows.filter((r) => {
      if (y) return Number(r.years?.[y]?.[state.selectedSlice.category] || 0) > 0;
      return Number(r.totals?.[state.selectedSlice.category] || 0) > 0;
    });
  }

  return rows;
}

function renderCards() {
  const pts = mapPoints();
  const c = state.summary?.cards || {};

  const knownUnits = pts.reduce((a, p) => a + Number(p.units || 0), 0);
  const estUnits = pts.reduce((a, p) => a + Number(p.estimated_units || 0), 0);

  const items = [
    ["Visible Permits", pts.length || c.total_permits || 0],
    ["Known Units", knownUnits || c.known_units || 0],
    ["Est. Units", estUnits || c.estimated_units || 0],
    ["Neighborhoods", new Set(pts.map((p) => p.raw_neighborhood).filter(Boolean)).size || c.known_neighborhoods || 0],
    ["SFR / ADU", pts.filter((p) => p.category === "New SFR / ADU").length || c.new_sfr_adu || 0],
    ["Townhome", pts.filter((p) => p.category === "Townhome / Rowhouse / Duplex").length || c.townhome_rowhouse_duplex || 0],
    ["MF / Apt", pts.filter((p) => p.category === "Multifamily / Apartment").length || c.multifamily_apartment || 0],
    ["Demo", pts.filter((p) => p.category === "Demo").length || c.demo || 0],
  ];

  const cards = byId("cards");
  if (!cards) return;

  cards.innerHTML = items.map(([label, value]) => `
    <article class="card executive-card">
      <div class="card-label">${esc(label)}</div>
      <div class="card-value">${fmt(value)}</div>
    </article>
  `).join("");
}

function drawBars(canvas, labels, series, click) {
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(300, Math.floor(rect.width || 800));
  const h = 260;
  const ratio = window.devicePixelRatio || 1;

  canvas.width = w * ratio;
  canvas.height = h * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const m = { l: 48, r: 20, t: 18, b: 42 };
  const pw = w - m.l - m.r;
  const ph = h - m.t - m.b;

  const colors = ["#0f766e", "#64748b", "#2563eb", "#a16207"];
  const max = Math.max(1, ...series.flatMap((s) => s.values));

  ctx.strokeStyle = "#d6dee8";
  ctx.fillStyle = "#667085";
  ctx.font = "12px Arial";

  for (let i = 0; i <= 4; i++) {
    const y = m.t + ph - (ph * i / 4);
    ctx.beginPath();
    ctx.moveTo(m.l, y);
    ctx.lineTo(w - m.r, y);
    ctx.stroke();
    ctx.fillText(String(Math.round(max * i / 4)), 10, y + 4);
  }

  const gw = pw / Math.max(1, labels.length);
  const bw = Math.min(18, Math.max(8, (gw - 12) / series.length));
  const hits = [];

  labels.forEach((label, li) => {
    const gx = m.l + li * gw + 6;

    series.forEach((s, si) => {
      const val = Number(s.values[li] || 0);
      const bh = (val / max) * ph;
      const x = gx + si * bw;
      const y = m.t + ph - bh;

      ctx.fillStyle = colors[si % colors.length];
      ctx.fillRect(x, y, bw - 2, bh);

      hits.push({
        x,
        y,
        w: bw - 2,
        h: bh,
        label,
        series: s.name,
        value: val,
      });
    });

    ctx.fillStyle = "#334155";
    ctx.fillText(String(label), gx, h - 10);
  });

  canvas.onclick = (e) => {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;

    const hit = hits.find((h) => (
      x >= h.x &&
      x <= h.x + h.w &&
      y >= h.y &&
      y <= h.y + h.h
    ));

    if (hit) click(hit);
  };
}

function renderChart() {
  const rows = state.summary?.annual_series || [];

  drawBars(
    byId("annualChart"),
    rows.map((r) => r.year),
    [
      {
        name: "New SFR / ADU",
        values: rows.map((r) => r["New SFR / ADU"] || 0),
      },
      {
        name: "Townhome / Rowhouse / Duplex",
        values: rows.map((r) => r["Townhome / Rowhouse / Duplex"] || 0),
      },
      {
        name: "Multifamily / Apartment",
        values: rows.map((r) => r["Multifamily / Apartment"] || 0),
      },
      {
        name: "Demo",
        values: rows.map((r) => r.Demo || 0),
      },
    ],
    (hit) => {
      state.selectedSlice = {
        year: Number(hit.label),
        category: hit.series,
      };

      byId("annualChartValue").textContent = `${hit.label} • ${hit.series}: ${fmt(hit.value)}`;

      renderCards();
      renderNeighborhoods();
      renderMap();
    }
  );
}

function badgeClass(value) {
  const v = String(value || "").toLowerCase();

  if (v.includes("saturated") || v.includes("caution")) return "badge caution";
  if (v.includes("underserved") || v.includes("opportunity")) return "badge opportunity";
  if (v.includes("accelerating") || v.includes("heating")) return "badge active";

  return "badge";
}

function renderMarkets() {
  const tbody = byId("marketTable")?.querySelector("tbody");
  if (!tbody) return;

  const rows = state.summary?.market_rows || [];

  tbody.innerHTML = rows.map((r) => `
    <tr data-market="${esc(r.name)}">
      <td>${esc(r.name)}</td>
      <td>${fmt(r.totals?.Total)}</td>
      <td>${fmt(r.totals?.["New SFR / ADU"])}</td>
      <td>${fmt(r.totals?.["Townhome / Rowhouse / Duplex"])}</td>
      <td>${fmt(r.totals?.["Multifamily / Apartment"])}</td>
      <td>${fmt(r.totals?.["Known Units"])}</td>
      <td><span class="${badgeClass(r.trajectory)}">${esc(r.trajectory)}</span></td>
      <td><span class="${badgeClass(r.opportunity)}">${esc(r.opportunity)}</span></td>
    </tr>
  `).join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.onclick = async () => {
      byId("market").value = tr.dataset.market;
      byId("neighborhood").value = "all";
      state.selectedSlice = null;
      await loadSummary();
      byId("mapContext").textContent = `${tr.dataset.market} • all neighborhoods`;
    };
  });
}

function renderNeighborhoods() {
  const table = byId("neighborhoodTable");
  const tbody = table?.querySelector("tbody");
  const thead = byId("neighborhoodTableHead");

  if (!tbody || !thead) return;

  const ys = years();
  const rows = neighborhoodRows();

  thead.innerHTML = `
    <tr>
      <th>Neighborhood</th>
      <th>Market</th>
      ${ys.map((y) => `<th>${y}</th>`).join("")}
      <th>Total</th>
      <th>SFR / ADU</th>
      <th>Townhome</th>
      <th>MF / Apt</th>
      <th>Units</th>
      <th>Trajectory</th>
      <th>Read</th>
    </tr>
  `;

  tbody.innerHTML = rows.map((r) => `
    <tr data-neighborhood="${esc(r.name)}">
      <td>${esc(r.name)}</td>
      <td>${esc(r.market)}</td>
      ${ys.map((y) => `<td>${fmt(r.years?.[String(y)]?.Total)}</td>`).join("")}
      <td>${fmt(r.totals?.Total)}</td>
      <td>${fmt(r.totals?.["New SFR / ADU"])}</td>
      <td>${fmt(r.totals?.["Townhome / Rowhouse / Duplex"])}</td>
      <td>${fmt(r.totals?.["Multifamily / Apartment"])}</td>
      <td>${fmt(r.totals?.["Known Units"])}</td>
      <td><span class="${badgeClass(r.trajectory)}">${esc(r.trajectory)}</span></td>
      <td><span class="${badgeClass(r.opportunity)}">${esc(r.opportunity)}</span></td>
    </tr>
  `).join("");

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${ys.length + 8}" class="muted">No neighborhoods in this selection.</td></tr>`;
  }

  tbody.querySelectorAll("tr[data-neighborhood]").forEach((tr) => {
    tr.onclick = async () => {
      byId("neighborhood").value = tr.dataset.neighborhood;
      state.selectedSlice = null;
      await loadSummary();
      byId("mapContext").textContent = `${tr.dataset.neighborhood} • selected neighborhood`;
    };
  });
}

function initMap() {
  if (state.map) return;

  if (typeof L === "undefined") {
    throw new Error("Leaflet did not load. Check internet/CDN access or the Leaflet script tag.");
  }

  state.map = L.map("permitMap", { preferCanvas: true }).setView([47.6062, -122.3321], 11);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);

  state.mapLayer = L.layerGroup().addTo(state.map);
}

function fallbackCenter(market) {
  const centers = {
    "Downtown Seattle": [47.608, -122.335],
    "First Hill / Capitol Hill": [47.62, -122.32],
    "South Lake Union / Eastlake": [47.631, -122.334],
    "Queen Anne / Magnolia": [47.639, -122.371],
    "Ballard": [47.668, -122.386],
    "Fremont / Wallingford": [47.654, -122.346],
    "University District / Northeast": [47.662, -122.307],
    "North Seattle": [47.705, -122.343],
    "Central Seattle": [47.608, -122.303],
    "Beacon Hill": [47.579, -122.312],
    "West Seattle": [47.571, -122.386],
    "South Seattle": [47.555, -122.285],
    "Greater Duwamish": [47.56, -122.335],
    "Unknown": [47.6062, -122.3321],
  };

  return centers[market] || [47.6062, -122.3321];
}

function markerColor(category) {
  if (category === "Demo") return "#a16207";
  if (category === "Multifamily / Apartment") return "#2563eb";
  if (category === "Townhome / Rowhouse / Duplex") return "#64748b";
  return "#0f766e";
}

function radius(units, estimatedUnits) {
  const u = Number(units || 0) || Number(estimatedUnits || 0);

  if (u >= 100) return 10;
  if (u >= 50) return 8;
  if (u >= 20) return 6;
  if (u >= 5) return 5;

  return 4;
}

function renderMap() {
  initMap();
  state.mapLayer.clearLayers();

  const rows = mapPoints();

  if (!rows.length) {
    byId("mapContext").textContent = "No points in current selection";
    return;
  }

  const bounds = [];
  let blocked = 0;

  rows.forEach((r, idx) => {
    let lat = Number(r.latitude);
    let lng = Number(r.longitude);

    if (!validPnwPoint(lat, lng)) {
      blocked += 1;

      const c = fallbackCenter(r.market || "Unknown");
      lat = c[0] + ((idx % 11) - 5) * 0.0012;
      lng = c[1] + ((Math.floor(idx / 11) % 11) - 5) * 0.0012;
    }

    if (!validPnwPoint(lat, lng)) return;

    const marker = L.circleMarker([lat, lng], {
      radius: radius(r.units, r.estimated_units),
      color: markerColor(r.category),
      weight: 1,
      fillColor: markerColor(r.category),
      fillOpacity: 0.72,
    });

    marker.bindPopup(`
      <div class="popup-card">
        <div class="popup-title">${esc(r.address || "Address unavailable")}</div>
        <div><strong>Market:</strong> ${esc(r.market || "Unknown")}</div>
        <div><strong>Neighborhood:</strong> ${esc(r.raw_neighborhood || "Unknown")}</div>
        <div><strong>Type:</strong> ${esc(r.category || "")}</div>
        <div><strong>Known units:</strong> ${fmt(r.units)}</div>
        <div><strong>Estimated units:</strong> ${fmt(r.estimated_units)}</div>
        <div><strong>Issued:</strong> ${esc((r.issue_date || r.intake_date || "").slice(0, 10))}</div>
      </div>
    `);

    marker.addTo(state.mapLayer);
    bounds.push([lat, lng]);
  });

  if (bounds.length === 1) {
    state.map.setView(bounds[0], 14);
  } else if (bounds.length > 1) {
    state.map.fitBounds(bounds, { padding: [18, 18] });
  }

  byId("mapContext").textContent =
    `${fmt(bounds.length)} points shown on map${blocked ? ` • ${fmt(blocked)} bad coordinates blocked` : ""}`;
}

async function onFilter() {
  state.selectedSlice = null;
  await loadSummary();
}

function wire() {
  ["jurisdiction", "category", "market", "neighborhood", "startYear", "endYear"]
    .forEach((id) => {
      const el = byId(id);
      if (el) el.addEventListener("change", onFilter);
    });
}

window.addEventListener("DOMContentLoaded", async () => {
  try {
    wire();
    await loadMeta();
    await loadSummary();
  } catch (e) {
    showFatal(e.message || String(e));
  }
});

/* ============================================================
   Absorption early-warning module (self-contained)
   ============================================================ */
const absorptionState = { data: null, map: null, layer: null, category: "Townhome / Rowhouse / Duplex" };

const ABSORPTION_COLORS = {
  green: "#027a48",
  yellow: "#b54708",
  red: "#b42318",
  "insufficient data": "#94a3b8",
};

const STATUS_LABELS = {
  green: "Healthy",
  yellow: "Slowing",
  red: "Warning",
  "insufficient data": "Thin data",
};

function absorptionRows() {
  const d = absorptionState.data;
  if (!d) return [];
  // Neighborhood-level rows only (market rollups excluded from map/table)
  return (d.areas || []).filter(
    (a) => a.category === absorptionState.category && a.neighborhood !== a.market
  );
}

function statusRank(s) {
  return { red: 0, yellow: 1, green: 2, "insufficient data": 3 }[s] ?? 4;
}

function renderAbsorptionToggle() {
  const wrap = byId("absorptionToggle");
  if (!wrap) return;
  const cats = absorptionState.data?.categories || [];
  wrap.innerHTML = cats
    .map(
      (c) =>
        `<button class="abs-toggle-btn${c === absorptionState.category ? " active" : ""}" data-cat="${esc(c)}">${esc(
          c === "Townhome / Rowhouse / Duplex" ? "Townhome / Duplex" : c
        )}</button>`
    )
    .join("");
  wrap.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      absorptionState.category = b.dataset.cat;
      renderAbsorptionToggle();
      renderAbsorptionMap();
      renderAbsorptionTable();
    })
  );
}

function absorptionPopup(a) {
  const days = a.median_days_to_sale;
  const trend = a.trend_days;
  return `
    <div class="map-pop">
      <div><strong>${esc(a.neighborhood)}</strong> — ${esc(STATUS_LABELS[a.status] || a.status)}</div>
      <div><strong>Median days to sale:</strong> ${days == null ? "–" : fmt(days)}</div>
      <div><strong>Trend vs prior yr:</strong> ${trend == null ? "–" : (trend > 0 ? "+" : "") + fmt(trend) + " days"}</div>
      <div><strong>Sold last 12mo:</strong> ${fmt(a.sold_last_12mo)}${a.presold ? ` (${fmt(a.presold)} presold)` : ""}</div>
      <div><strong>Pipeline units:</strong> ${fmt(a.pipeline_units)}</div>
      <div><strong>Standing unsold:</strong> ${fmt(a.standing_unsold_24mo)}</div>
      <div><strong>Months of supply:</strong> ${a.months_of_supply == null ? "–" : a.months_of_supply}</div>
    </div>`;
}

function renderAbsorptionMap() {
  const el = byId("absorptionMap");
  if (!el || !absorptionState.data) return;
  if (!absorptionState.map) {
    absorptionState.map = L.map("absorptionMap", { preferCanvas: true }).setView([47.6062, -122.3321], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(absorptionState.map);
  }
  if (absorptionState.layer) absorptionState.layer.remove();
  absorptionState.layer = L.layerGroup().addTo(absorptionState.map);

  const bounds = absorptionState.data.bounds || {};
  const drawn = [];
  absorptionRows().forEach((a) => {
    const b = bounds[a.neighborhood];
    if (!b) return;
    const rect = L.rectangle(
      [[b[0], b[1]], [b[2], b[3]]],
      {
        color: ABSORPTION_COLORS[a.status] || "#94a3b8",
        weight: 1.5,
        fillColor: ABSORPTION_COLORS[a.status] || "#94a3b8",
        fillOpacity: a.status === "insufficient data" ? 0.12 : 0.28,
      }
    );
    rect.bindPopup(absorptionPopup(a));
    rect.addTo(absorptionState.layer);
    drawn.push([b[0], b[1]], [b[2], b[3]]);
  });
  if (drawn.length) absorptionState.map.fitBounds(drawn, { padding: [12, 12] });
}

function renderAbsorptionTable() {
  const tbody = document.querySelector("#absorptionTable tbody");
  if (!tbody) return;
  const rows = absorptionRows().slice().sort((x, y) => {
    const r = statusRank(x.status) - statusRank(y.status);
    if (r) return r;
    return (y.median_days_to_sale ?? -1) - (x.median_days_to_sale ?? -1);
  });
  tbody.innerHTML = rows
    .map((a) => {
      const trend = a.trend_days;
      const trendTxt = trend == null ? "–" : `${trend > 0 ? "+" : ""}${fmt(trend)}d`;
      return `
      <tr>
        <td>${esc(a.neighborhood)}</td>
        <td>${a.median_days_to_sale == null ? "–" : fmt(a.median_days_to_sale)}</td>
        <td class="${trend > 0 ? "trend-bad" : trend < 0 ? "trend-good" : ""}">${trendTxt}</td>
        <td>${fmt(a.sold_last_12mo)}</td>
        <td>${fmt(a.pipeline_units)}</td>
        <td>${fmt(a.standing_unsold_24mo)}</td>
        <td>${a.months_of_supply == null ? "–" : a.months_of_supply}</td>
        <td><span class="status-pill status-${esc(a.status).replace(/\s+/g, "-")}">${esc(STATUS_LABELS[a.status] || a.status)}</span></td>
      </tr>`;
    })
    .join("");
}

async function loadAbsorption() {
  try {
    const res = await fetch("/api/absorption");
    if (!res.ok) throw new Error(`absorption HTTP ${res.status}`);
    absorptionState.data = await res.json();
    if (!(absorptionState.data.categories || []).includes(absorptionState.category)) {
      absorptionState.category = (absorptionState.data.categories || [])[0] || absorptionState.category;
    }
    const meta = byId("absorptionMeta");
    if (meta && absorptionState.data.generated_at) {
      meta.textContent = `Days from permit completion to recorded sale • refreshed ${absorptionState.data.generated_at.slice(0, 10)}`;
    }
    renderAbsorptionToggle();
    renderAbsorptionMap();
    renderAbsorptionTable();
  } catch (e) {
    console.error("absorption load failed", e);
    const sec = byId("absorptionSection");
    if (sec) sec.style.display = "none";
  }
}

window.addEventListener("DOMContentLoaded", loadAbsorption);
