\
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
  const notes = byId("loadErrors");
  if (notes) {
    notes.innerHTML = `<div style="font-weight:700;">Dashboard load error:</div><div>${esc(message)}</div>`;
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

function filters() {
  return {
    jurisdiction: byId("jurisdiction")?.value || "all",
    category: byId("category")?.value || "all",
    market: byId("market")?.value || "all",
    neighborhood: byId("neighborhood")?.value || "all",
    start_year: byId("startYear")?.value || "2022",
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
  if ([...s.options].some((o) => o.value === cur)) s.value = cur;
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
  cards.innerHTML = items.map(([l, v]) => `
    <article class="card executive-card">
      <div class="card-label">${esc(l)}</div>
      <div class="card-value">${fmt(v)}</div>
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
      hits.push({ x, y, w: bw - 2, h: bh, label, series: s.name, value: val });
    });
    ctx.fillStyle = "#334155";
    ctx.fillText(String(label), gx, h - 10);
  });

  canvas.onclick = (e) => {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const hit = hits.find((h) => x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h);
    if (hit) click(hit);
  };
}

function renderChart() {
  const rows = state.summary?.annual_series || [];
  drawBars(
    byId("annualChart"),
    rows.map((r) => r.year),
    [
      { name: "New SFR / ADU", values: rows.map((r) => r["New SFR / ADU"] || 0) },
      { name: "Townhome / Rowhouse / Duplex", values: rows.map((r) => r["Townhome / Rowhouse / Duplex"] || 0) },
      { name: "Multifamily / Apartment", values: rows.map((r) => r["Multifamily / Apartment"] || 0) },
      { name: "Demo", values: rows.map((r) => r.Demo || 0) },
    ],
    (hit) => {
      state.selectedSlice = { year: Number(hit.label), category: hit.series };
      byId("annualChartValue").textContent = `${hit.label} • ${hit.series}: ${fmt(hit.value)}`;
      renderCards();
      renderNeighborhoods();
      renderMap();
    }
  );
}

function badgeClass(v) {
  v = String(v || "").toLowerCase();
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
  const tbody = byId("neighborhoodTable")?.querySelector("tbody");
  if (!tbody) return;
  const rows = neighborhoodRows();

  tbody.innerHTML = rows.map((r) => `
    <tr data-neighborhood="${esc(r.name)}">
      <td>${esc(r.name)}</td>
      <td>${esc(r.market)}</td>
      <td>${fmt(r.years?.["2022"]?.Total)}</td>
      <td>${fmt(r.years?.["2023"]?.Total)}</td>
      <td>${fmt(r.years?.["2024"]?.Total)}</td>
      <td>${fmt(r.years?.["2025"]?.Total)}</td>
      <td>${fmt(r.years?.["2026"]?.Total)}</td>
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
    tbody.innerHTML = `<tr><td colspan="14" class="muted">No neighborhoods in this selection.</td></tr>`;
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

function fallbackCenter(m) {
  const c = {
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
  return c[m] || [47.6062, -122.3321];
}

function markerColor(c) {
  if (c === "Demo") return "#a16207";
  if (c === "Multifamily / Apartment") return "#2563eb";
  if (c === "Townhome / Rowhouse / Duplex") return "#64748b";
  return "#0f766e";
}

function radius(u, e) {
  u = Number(u || 0) || Number(e || 0);
  return u >= 100 ? 10 : u >= 50 ? 8 : u >= 20 ? 6 : u >= 5 ? 5 : 4;
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

    const m = L.circleMarker([lat, lng], {
      radius: radius(r.units, r.estimated_units),
      color: markerColor(r.category),
      weight: 1,
      fillColor: markerColor(r.category),
      fillOpacity: 0.72,
    });

    m.bindPopup(`
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

    m.addTo(state.mapLayer);
    bounds.push([lat, lng]);
  });

  if (bounds.length === 1) {
    state.map.setView(bounds[0], 14);
  } else if (bounds.length > 1) {
    state.map.fitBounds(bounds, { padding: [18, 18] });
  }

  byId("mapContext").textContent = `${fmt(bounds.length)} points shown on map${blocked ? ` • ${fmt(blocked)} bad coordinates blocked` : ""}`;
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
