const state = {
  meta: null,
  summary: null,
  selectedSlice: null, // { year, category }
  map: null,
  mapLayer: null,
};

const byId = (id) => document.getElementById(id);

function formatNumber(n) {
  return new Intl.NumberFormat().format(Number(n || 0));
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[m]));
}

function queryString(obj) {
  return new URLSearchParams(obj).toString();
}

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function getFilters() {
  return {
    jurisdiction: byId("jurisdiction")?.value || "all",
    category: byId("category")?.value || "all",
    market: byId("market")?.value || "all",
    start_year: byId("startYear")?.value || "2022",
    end_year: byId("endYear")?.value || "2026",
  };
}

function renderLoadMessages(notes, errors) {
  const notesEl = byId("loadNotes");
  const errorsEl = byId("loadErrors");

  notesEl.innerHTML = (notes || [])
    .map((n) => `<span class="note-pill">${escapeHtml(n)}</span>`)
    .join("");

  errorsEl.innerHTML = (errors || [])
    .map((e) => `<div>${escapeHtml(e)}</div>`)
    .join("");
}

function populateMarkets(markets) {
  const select = byId("market");
  const current = select.value || "all";
  select.innerHTML = '<option value="all">All markets</option>';

  (markets || []).forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    select.appendChild(opt);
  });

  if ([...select.options].some((o) => o.value === current)) {
    select.value = current;
  }
}

async function loadMeta() {
  state.meta = await fetchJson("/api/meta");
  populateMarkets(state.meta.markets || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  const qs = queryString(getFilters());
  state.summary = await fetchJson(`/api/summary?${qs}`);
  renderLoadMessages(state.summary.load_notes || [], state.summary.load_errors || []);
  renderCards();
  renderAnnualChart();
  renderMarketTable();
  renderSelectedNeighborhoodsTable();
  renderMap();
}

function renderCards() {
  const cardsEl = byId("cards");
  const c = state.summary?.cards || {};

  const items = [
    ["Total Permits", c.total_permits || 0],
    ["Total Units", c.total_units || 0],
    ["Seattle Permits", c.seattle_permits || 0],
    ["Bellevue Permits", c.bellevue_permits || 0],
    ["Markets", c.known_markets || 0],
    ["New SFR", c.new_sfr || 0],
    ["New MF", c.new_mf || 0],
    ["Demo", c.demo || 0],
  ];

  cardsEl.innerHTML = items.map(([label, value]) => `
    <article class="card executive-card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value">${formatNumber(value)}</div>
    </article>
  `).join("");
}

function filteredMapPoints() {
  let rows = state.summary?.map_points || [];

  if (state.selectedSlice?.year) {
    rows = rows.filter((r) => Number(r.year) === Number(state.selectedSlice.year));
  }
  if (state.selectedSlice?.category) {
    rows = rows.filter((r) => r.category === state.selectedSlice.category);
  }

  return rows;
}

function drawGroupedBars(canvas, labels, series, clickHandler) {
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(300, Math.floor(rect.width));
  const height = Math.max(240, Math.floor(rect.height || canvas.height || 250));
  const ratio = window.devicePixelRatio || 1;

  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const margin = { left: 46, right: 20, top: 18, bottom: 42 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;

  const colors = ["#5b7fa6", "#7fa7d6", "#c48b4d"];

  const allValues = series.flatMap((s) => s.values);
  const maxVal = Math.max(1, ...allValues, 0);

  ctx.strokeStyle = "#d6dee8";
  ctx.fillStyle = "#667085";
  ctx.font = "12px Arial";

  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(width - margin.right, y);
    ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 10, y + 4);
  }

  const groupW = plotW / Math.max(1, labels.length);
  const barW = Math.min(22, Math.max(10, (groupW - 12) / Math.max(1, series.length)));
  const hitboxes = [];

  labels.forEach((label, li) => {
    const gx = margin.left + li * groupW + 6;

    series.forEach((s, si) => {
      const val = Number(s.values[li] || 0);
      const barH = (val / maxVal) * plotH;
      const x = gx + si * barW;
      const y = margin.top + plotH - barH;

      ctx.fillStyle = colors[si % colors.length];
      ctx.fillRect(x, y, barW - 2, barH);

      hitboxes.push({
        x, y, w: barW - 2, h: barH,
        label,
        series: s.name,
        value: val,
      });
    });

    ctx.fillStyle = "#334155";
    ctx.fillText(String(label), gx, height - 10);
  });

  canvas.onclick = (evt) => {
    const r = canvas.getBoundingClientRect();
    const x = evt.clientX - r.left;
    const y = evt.clientY - r.top;

    const hit = hitboxes.find(
      (h) => x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h
    );

    if (hit && clickHandler) clickHandler(hit);
  };
}

function renderAnnualChart() {
  const rows = state.summary?.annual_series || [];
  drawGroupedBars(
    byId("annualChart"),
    rows.map((r) => r.year),
    [
      { name: "New SFR", values: rows.map((r) => r["New SFR"] || 0) },
      { name: "New MF", values: rows.map((r) => r["New MF"] || 0) },
      { name: "Demo", values: rows.map((r) => r["Demo"] || 0) },
    ],
    (hit) => {
      state.selectedSlice = {
        year: Number(hit.label),
        category: hit.series,
      };
      byId("annualChartValue").textContent =
        `${hit.label} • ${hit.series}: ${formatNumber(hit.value)}`;
      byId("mapContext").textContent =
        `${hit.label} • ${hit.series} • ${formatNumber(filteredMapPoints().length)} points`;
      renderSelectedNeighborhoodsTable();
      renderMap();
    }
  );
}

function renderMarketTable() {
  const table = byId("marketTable");
  const tbody = table.querySelector("tbody");
  const rows = state.summary?.neighborhood_rows || [];

  tbody.innerHTML = rows.map((r) => `
    <tr data-market="${escapeHtml(r.neighborhood)}">
      <td>${escapeHtml(r.neighborhood)}</td>
      <td>${formatNumber(r.totals?.Total || 0)}</td>
      <td>${formatNumber(r.totals?.Units || 0)}</td>
      <td>${formatNumber(r.totals?.["New SFR"] || 0)}</td>
      <td>${formatNumber(r.totals?.["New MF"] || 0)}</td>
      <td>${formatNumber(r.totals?.["Demo"] || 0)}</td>
    </tr>
  `).join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", async () => {
      byId("market").value = tr.dataset.market;
      state.selectedSlice = null;
      await loadSummary();
      byId("mapContext").textContent =
        `${tr.dataset.market} • ${formatNumber(filteredMapPoints().length)} points`;
    });
  });
}

function renderSelectedNeighborhoodsTable() {
  const table = byId("selectedNeighborhoodsTable");
  const tbody = table.querySelector("tbody");

  const rows = filteredMapPoints();
  const grouped = {};

  rows.forEach((r) => {
    const raw = r.raw_neighborhood || "Unknown";
    if (!grouped[raw]) {
      grouped[raw] = {
        raw_neighborhood: raw,
        market: r.market || "Unknown",
        permits: 0,
        units: 0,
      };
    }
    grouped[raw].permits += 1;
    grouped[raw].units += Number(r.units || 0);
  });

  const out = Object.values(grouped).sort((a, b) => b.permits - a.permits);

  tbody.innerHTML = out.map((r) => `
    <tr>
      <td>${escapeHtml(r.raw_neighborhood)}</td>
      <td>${escapeHtml(r.market)}</td>
      <td>${formatNumber(r.permits)}</td>
      <td>${formatNumber(r.units)}</td>
    </tr>
  `).join("");

  if (!out.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="muted">No neighborhoods in this selection.</td></tr>`;
  }
}

function initMap() {
  if (state.map) return;

  state.map = L.map("permitMap", {
    preferCanvas: true
  }).setView([47.6062, -122.3321], 11);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);

  state.mapLayer = L.layerGroup().addTo(state.map);
}

function fallbackCenter(market) {
  const centers = {
    "Downtown Core": [47.6105, -122.3365],
    "Pioneer Square / ID": [47.5985, -122.3275],
    "First Hill / Capitol Hill": [47.6200, -122.3200],
    "South Lake Union / Eastlake": [47.6310, -122.3340],
    "Queen Anne / Magnolia": [47.6390, -122.3710],
    "Ballard": [47.6680, -122.3860],
    "Fremont / Wallingford": [47.6540, -122.3460],
    "University District / Northeast": [47.6620, -122.3070],
    "North Seattle": [47.7050, -122.3430],
    "Central Seattle": [47.6080, -122.3030],
    "Beacon Hill": [47.5790, -122.3120],
    "West Seattle": [47.5710, -122.3860],
    "South Seattle": [47.5550, -122.2850],
    "Bellevue Downtown": [47.6101, -122.2015],
    "Wilburton": [47.5950, -122.1780],
    "Eastgate": [47.5790, -122.1350],
    "Crossroads": [47.6180, -122.1360],
    "Factoria": [47.5750, -122.1700],
    "Bel-Red": [47.6220, -122.1800],
    "West Bellevue": [47.6150, -122.2190],
    "Bellevue": [47.6101, -122.2015],
    "Unknown": [47.6062, -122.3321],
  };
  return centers[market] || [47.6062, -122.3321];
}

function markerColor(category) {
  if (category === "Demo") return "#a16207";
  if (category === "New MF") return "#2563eb";
  return "#0f766e";
}

function markerRadius(units) {
  const u = Number(units || 0);
  if (u >= 100) return 10;
  if (u >= 50) return 8;
  if (u >= 20) return 6;
  if (u >= 5) return 5;
  return 4;
}

function renderMap() {
  initMap();
  state.mapLayer.clearLayers();

  const rows = filteredMapPoints();

  if (!rows.length) {
    byId("mapContext").textContent = "No points in current selection";
    return;
  }

  const bounds = [];

  rows.forEach((r, idx) => {
    let lat = Number(r.latitude);
    let lng = Number(r.longitude);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      const c = fallbackCenter(r.market || "Unknown");
      lat = c[0] + ((idx % 11) - 5) * 0.0012;
      lng = c[1] + ((Math.floor(idx / 11) % 11) - 5) * 0.0012;
    }

    const marker = L.circleMarker([lat, lng], {
      radius: markerRadius(r.units),
      color: markerColor(r.category),
      weight: 1,
      fillColor: markerColor(r.category),
      fillOpacity: 0.75,
    });

    marker.bindPopup(`
      <div class="popup-card">
        <div class="popup-title">${escapeHtml(r.address || "Address unavailable")}</div>
        <div><strong>Market:</strong> ${escapeHtml(r.market || "Unknown")}</div>
        <div><strong>Neighborhood:</strong> ${escapeHtml(r.raw_neighborhood || "Unknown")}</div>
        <div><strong>Type:</strong> ${escapeHtml(r.category || "")}</div>
        <div><strong>Units:</strong> ${formatNumber(r.units || 0)}</div>
        <div><strong>Issued:</strong> ${escapeHtml((r.issue_date || r.intake_date || "").slice(0, 10))}</div>
      </div>
    `);

    marker.addTo(state.mapLayer);
    bounds.push([lat, lng]);
  });

  if (bounds.length === 1) {
    state.map.setView(bounds[0], 14);
  } else {
    state.map.fitBounds(bounds, { padding: [18, 18] });
  }

  byId("mapContext").textContent = `${formatNumber(rows.length)} points shown on map`;
}

async function onFilterChange() {
  state.selectedSlice = null;
  await loadSummary();
}

function wireEvents() {
  ["jurisdiction", "category", "market", "startYear", "endYear"].forEach((id) => {
    byId(id).addEventListener("change", onFilterChange);
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  wireEvents();

  try {
    await loadMeta();
    await loadSummary();
  } catch (err) {
    renderLoadMessages([], [err.message || String(err)]);
    console.error(err);
  }
});
