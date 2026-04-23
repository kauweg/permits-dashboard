const state = {
  meta: null,
  summary: null,
  selectedNeighborhood: "all",
  selectedSlice: null,
  map: null,
  mapLayer: null,
};

const byId = (id) => document.getElementById(id);

const MARKET_NAME_MAP = [
  {
    short: "West Seattle",
    matches: [
      "seaview", "gatewood", "arbor heights", "alki", "north admiral",
      "fairmount park", "genesee", "fauntleroy", "morgan junction",
      "alaska junction", "belvidere", "west seattle junction",
      "brace point", "endolyne", "arroyo heights",
      "highland park", "north delridge", "south delridge",
      "high point", "roxhill", "westwood", "avalon",
      "luna park", "pigeon point", "delridge", "west seattle"
    ]
  },
  {
    short: "Downtown Seattle",
    matches: [
      "pike-market", "belltown", "international district",
      "central business district", "first hill", "yesler terrace",
      "pioneer square", "denny regrade", "denny triangle",
      "commercial core", "west edge", "pike place market",
      "chinatown", "little saigon", "id"
    ]
  },
  {
    short: "Ballard",
    matches: [
      "loyal heights", "adams", "whittier heights", "west woodland",
      "sunset hill", "golden gardens", "shilshole", "ballard"
    ]
  },
  {
    short: "Wallingford / Fremont",
    matches: [
      "phinney ridge", "wallingford", "fremont", "green lake",
      "woodland park", "meridian", "northlake", "tangle town"
    ]
  },
  {
    short: "North Seattle",
    matches: [
      "broadview", "bitter lake", "north beach/blue ridge", "crown hill",
      "greenwood", "haller lake", "pinehurst", "north college park",
      "maple leaf", "jackson park", "licton springs", "olympic view",
      "victory heights", "matthews beach", "meadowbrook",
      "olympic hills", "cedar park"
    ]
  },
  {
    short: "Northeast Seattle",
    matches: [
      "view ridge", "ravenna", "sand point", "bryant", "windermere",
      "laurelhurst", "roosevelt", "wedgwood", "hawthorne hills",
      "university village", "fairview"
    ]
  },
  {
    short: "Central Seattle",
    matches: [
      "madrona", "harrison/denny-blaine", "minor", "leschi", "mann",
      "atlantic", "squire park", "judkins park", "central district",
      "colman", "garfield", "jackson place"
    ]
  },
  {
    short: "South Seattle",
    matches: [
      "brighton", "dunlap", "rainier beach", "mount baker",
      "columbia city", "north rainier", "lake ridge",
      "rainier view", "columbia heights", "seward park",
      "lakewood", "hillman city"
    ]
  },
  {
    short: "Queen Anne / Magnolia",
    matches: [
      "east queen anne", "west queen anne", "lower queen anne",
      "north queen anne", "uptown", "seattle center",
      "lawton park", "briarcliff", "southeast magnolia", "carleton park"
    ]
  },
  {
    short: "Beacon Hill",
    matches: [
      "north beacon hill", "mid-beacon hill", "south beacon hill",
      "holly park", "jefferson park", "new holly"
    ]
  },
  {
    short: "South Lake Union / Eastlake",
    matches: ["westlake", "eastlake", "south lake union"]
  },
  {
    short: "U District",
    matches: ["university district", "cowen park", "university heights"]
  },
  {
    short: "Interbay",
    matches: ["interbay"]
  },
  {
    short: "Bellevue Downtown",
    matches: ["bellevue downtown", "downtown bellevue"]
  },
  {
    short: "Wilburton",
    matches: ["wilburton"]
  },
  {
    short: "Eastgate",
    matches: ["eastgate"]
  },
  {
    short: "Bellevue",
    matches: ["bellevue"]
  }
];

function shortMarketName(name = "") {
  const raw = String(name || "").toLowerCase();
  for (const bucket of MARKET_NAME_MAP) {
    if (bucket.matches.some((m) => raw.includes(m))) return bucket.short;
  }
  return name || "Unknown";
}

function rowUnits(row) {
  return Number(
    row?.totals?.units ||
    row?.totals?.total_units ||
    row?.units ||
    row?.unit_count ||
    0
  );
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[m]));
}

function formatNumber(n) {
  return new Intl.NumberFormat().format(Number(n || 0));
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
  const neighborhoodSelect = byId("neighborhood");
  const selectedNeighborhood =
    state.selectedNeighborhood !== "all"
      ? state.selectedNeighborhood
      : (neighborhoodSelect?.value || "all");

  return {
    jurisdiction: byId("jurisdiction")?.value || "all",
    category: byId("category")?.value || "all",
    neighborhood: selectedNeighborhood,
    start_year: byId("startYear")?.value || "2022",
    end_year: byId("endYear")?.value || "2026",
  };
}

function renderLoadMessages(notes, errors) {
  const notesEl = byId("loadNotes");
  const errorsEl = byId("loadErrors");

  if (notesEl) {
    notesEl.innerHTML = (notes || [])
      .map((n) => `<span class="note-pill">${escapeHtml(n)}</span>`)
      .join("");
  }

  if (errorsEl) {
    errorsEl.innerHTML = (errors || [])
      .map((e) => `<div>${escapeHtml(e)}</div>`)
      .join("");
  }
}

function populateNeighborhoods(items) {
  const select = byId("neighborhood");
  const search = byId("neighborhoodSearch");
  if (!select) return;

  const current =
    state.selectedNeighborhood === "all"
      ? select.value
      : state.selectedNeighborhood;

  select.innerHTML = '<option value="all">All neighborhoods</option>';

  (items || []).forEach((n) => {
    const opt = document.createElement("option");
    opt.value = n;
    opt.textContent = n;
    select.appendChild(opt);
  });

  const options = [...select.options];
  if (options.some((o) => o.value === current)) {
    select.value = current;
  } else {
    select.value = "all";
    state.selectedNeighborhood = "all";
  }

  if (search) {
    search.value =
      state.selectedNeighborhood !== "all" ? state.selectedNeighborhood : "";
  }
}

async function loadMeta() {
  state.meta = await fetchJson("/api/meta");
  populateNeighborhoods(state.meta.neighborhoods || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  state.summary = await fetchJson(`/api/summary?${queryString(getFilters())}`);
  renderLoadMessages(
    state.summary.load_notes || [],
    state.summary.load_errors || []
  );
  renderCards();
  renderAnnualChart();
  renderNeighborhoodTable();
  renderDrilldownChart();
  renderProjectTable();
  renderMap();
}

function renderCards() {
  const cardsEl = byId("cards");
  if (!cardsEl) return;

  const c = state.summary?.cards || {};
  const rows = state.summary?.neighborhood_rows || [];

  const topByPermits = rows.length
    ? shortMarketName(rows[0].neighborhood)
    : "—";

  const topByUnits = [...rows].sort((a, b) => rowUnits(b) - rowUnits(a))[0];
  const topUnitsMarket = topByUnits ? shortMarketName(topByUnits.neighborhood) : "—";

  const totalUnits = c.total_units || c.units || 0;
  const totalPermits = c.total_permits || 0;
  const avgUnits = totalPermits ? (totalUnits / totalPermits).toFixed(1) : "0.0";

  const cards = [
    ["Total permits", totalPermits],
    ["Total units", totalUnits],
    ["Avg units / permit", avgUnits],
    ["All New", c.all_new ?? ((c.new_sfr || 0) + (c.new_mf || 0) + (c.other_new || 0))],
    ["Demo", c.demo || 0],
    ["Seattle", c.seattle_permits || 0],
    ["Bellevue", c.bellevue_permits || 0],
    ["Top permits area", topByPermits],
    ["Top units area", topUnitsMarket],
  ];

  cardsEl.innerHTML = cards.map(([label, value]) => `
    <article class="card executive-card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value">${typeof value === "number" ? formatNumber(value) : escapeHtml(value)}</div>
    </article>
  `).join("");
}

function drawGroupedBars(canvas, labels, series, valueElId, clickHandler) {
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(300, Math.floor(rect.width));
  const height = Math.max(220, Math.floor(rect.height || canvas.height || 260));
  const ratio = window.devicePixelRatio || 1;

  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const margin = { left: 46, right: 20, top: 18, bottom: 40 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const colors = ["#6d8fb3", "#9cb4c9", "#87a9a4", "#d8a45b"];

  const allValues = series.flatMap((s) => s.values);
  const maxVal = Math.max(1, ...allValues, 0);

  ctx.strokeStyle = "#d6dee8";
  ctx.fillStyle = "#6b7785";
  ctx.font = "12px Arial";

  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(width - margin.right, y);
    ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
  }

  const groupW = plotW / Math.max(1, labels.length);
  const barW = Math.min(20, Math.max(9, (groupW - 12) / Math.max(1, series.length)));
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
        x,
        y,
        w: barW - 2,
        h: barH,
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

    const valueEl = byId(valueElId);
    if (!valueEl) return;

    if (hit) {
      valueEl.textContent = `${hit.label} • ${hit.series}: ${formatNumber(hit.value)}`;
      if (clickHandler) clickHandler(hit);
    } else {
      valueEl.textContent = "Click a bar for details.";
    }
  };
}

function renderAnnualChart() {
  const data = state.summary?.annual_series || [];
  drawGroupedBars(
    byId("annualChart"),
    data.map((r) => r.year),
    [
      { name: "New SFR", values: data.map((r) => r["New SFR"] || 0) },
      { name: "New MF", values: data.map((r) => r["New MF"] || 0) },
      { name: "Other New", values: data.map((r) => r["Other New"] || 0) },
      { name: "Demo", values: data.map((r) => r["Demo"] || 0) },
    ],
    "annualChartValue",
    (hit) => {
      state.selectedSlice = {
        year: Number(hit.label),
        category: hit.series,
      };
      renderProjectTable();
      renderMap();
      byId("mapContext").textContent = `${hit.label} • ${hit.series}`;
    }
  );
}

function renderDrilldownChart() {
  const rows = state.summary?.neighborhood_rows || [];

  const grouped = {};
  rows.forEach((r) => {
    const market = shortMarketName(r.neighborhood);
    if (!grouped[market]) grouped[market] = {};
    Object.entries(r.years || {}).forEach(([year, vals]) => {
      if (!grouped[market][year]) {
        grouped[market][year] = { "New SFR": 0, "New MF": 0, "Other New": 0, "Demo": 0, Total: 0 };
      }
      grouped[market][year]["New SFR"] += Number(vals["New SFR"] || 0);
      grouped[market][year]["New MF"] += Number(vals["New MF"] || 0);
      grouped[market][year]["Other New"] += Number(vals["Other New"] || 0);
      grouped[market][year]["Demo"] += Number(vals["Demo"] || 0);
      grouped[market][year]["Total"] += Number(vals["Total"] || 0);
    });
  });

  const marketName =
    state.selectedNeighborhood !== "all"
      ? state.selectedNeighborhood
      : Object.keys(grouped)[0];

  const title = byId("drilldownTitle");
  if (title) title.textContent = marketName || "No market selected";

  if (!marketName || !grouped[marketName]) {
    drawGroupedBars(byId("drilldownChart"), [], [], "drilldownChartValue");
    return;
  }

  const years = Object.keys(grouped[marketName]).sort();

  drawGroupedBars(
    byId("drilldownChart"),
    years,
    [
      { name: "New SFR", values: years.map((y) => grouped[marketName][y]["New SFR"] || 0) },
      { name: "New MF", values: years.map((y) => grouped[marketName][y]["New MF"] || 0) },
      { name: "Other New", values: years.map((y) => grouped[marketName][y]["Other New"] || 0) },
      { name: "Demo", values: years.map((y) => grouped[marketName][y]["Demo"] || 0) },
    ],
    "drilldownChartValue"
  );
}

function renderNeighborhoodTable() {
  const table = byId("neighborhoodTable");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const rows = state.summary?.neighborhood_rows || [];

  const grouped = {};

  rows.forEach((r) => {
    const market = shortMarketName(r.neighborhood);
    if (!grouped[market]) {
      grouped[market] = {
        market,
        permits: 0,
        units: 0,
        allNew: 0,
        demo: 0,
      };
    }

    grouped[market].permits += Number(r.totals?.Total || 0);
    grouped[market].units += rowUnits(r);
    grouped[market].allNew +=
      Number(r.totals?.["New SFR"] || 0) +
      Number(r.totals?.["New MF"] || 0) +
      Number(r.totals?.["Other New"] || 0);
    grouped[market].demo += Number(r.totals?.["Demo"] || 0);
  });

  const groupedRows = Object.values(grouped).sort((a, b) => b.permits - a.permits);

  tbody.innerHTML = groupedRows.map((r) => `
    <tr data-market="${escapeHtml(r.market)}">
      <td>${escapeHtml(r.market)}</td>
      <td>${formatNumber(r.permits)}</td>
      <td>${formatNumber(r.units)}</td>
      <td>${formatNumber(r.allNew)}</td>
      <td>${formatNumber(r.demo)}</td>
    </tr>
  `).join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      state.selectedNeighborhood = tr.dataset.market;
      byId("mapContext").textContent = `Market • ${state.selectedNeighborhood}`;
      renderProjectTable();
      renderMap();
      renderDrilldownChart();
    });
  });
}

function neighborhoodCenter(name) {
  const map = {
    "West Seattle": [47.571, -122.386],
    "Downtown Seattle": [47.6062, -122.3321],
    "Ballard": [47.668, -122.386],
    "Wallingford / Fremont": [47.655, -122.344],
    "North Seattle": [47.700, -122.340],
    "Northeast Seattle": [47.675, -122.299],
    "Central Seattle": [47.608, -122.303],
    "South Seattle": [47.558, -122.287],
    "Queen Anne / Magnolia": [47.640, -122.372],
    "Beacon Hill": [47.579, -122.312],
    "South Lake Union / Eastlake": [47.628, -122.338],
    "U District": [47.661, -122.313],
    "Interbay": [47.642, -122.376],
    "Bellevue Downtown": [47.6101, -122.2015],
    "Wilburton": [47.595, -122.178],
    "Eastgate": [47.579, -122.135],
    "Bellevue": [47.6101, -122.2015],
    "Unknown": [47.6062, -122.3321],
  };

  return map[name] || [47.6062, -122.3321];
}

function buildProjectRows() {
  const base = Array.isArray(state.summary?.map_points) && state.summary.map_points.length
    ? state.summary.map_points
    : (state.summary?.samples || []);

  return base.map((row, idx) => {
    const category = row.category || "Other New";
    const year = Number(String(row.issue_date || row.intake_date || "").slice(0, 4)) || null;
    const market = shortMarketName(row.neighborhood || "Unknown");

    let lat = row.latitude ?? row.lat ?? null;
    let lng = row.longitude ?? row.lng ?? row.lon ?? null;

    if (lat == null || lng == null || Number.isNaN(Number(lat)) || Number.isNaN(Number(lng))) {
      const center = neighborhoodCenter(market);
      lat = center[0] + ((idx % 7) - 3) * 0.0018;
      lng = center[1] + ((Math.floor(idx / 7) % 7) - 3) * 0.0018;
    }

    return {
      address: row.address || `Project ${idx + 1}`,
      neighborhood: row.neighborhood || "Unknown",
      market,
      jurisdiction: row.jurisdiction || "Seattle",
      category,
      units: Number(row.units || row.unit_count || 0),
      issue_date: row.issue_date || row.intake_date || "",
      year,
      latitude: Number(lat),
      longitude: Number(lng),
    };
  });
}

function filteredProjectRows() {
  let rows = buildProjectRows();

  if (state.selectedSlice?.year) {
    rows = rows.filter((r) => r.year === state.selectedSlice.year);
  }

  if (state.selectedSlice?.category) {
    rows = rows.filter((r) => r.category === state.selectedSlice.category);
  }

  if (state.selectedNeighborhood !== "all") {
    rows = rows.filter((r) => shortMarketName(r.neighborhood) === state.selectedNeighborhood);
  }

  const jurisdiction = byId("jurisdiction")?.value || "all";
  if (jurisdiction !== "all") {
    rows = rows.filter((r) => r.jurisdiction === jurisdiction);
  }

  const categoryFilter = byId("category")?.value || "all";
  if (categoryFilter !== "all") {
    rows = rows.filter((r) => r.category === categoryFilter);
  }

  return rows;
}

function renderProjectTable() {
  const table = byId("projectTable");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const rows = filteredProjectRows();

  tbody.innerHTML = rows.slice(0, 250).map((r) => `
    <tr>
      <td>${escapeHtml(r.address)}</td>
      <td>${escapeHtml(r.market)}</td>
      <td>${escapeHtml(r.category)}</td>
      <td>${formatNumber(r.units)}</td>
      <td>${escapeHtml((r.issue_date || "").slice(0, 10))}</td>
    </tr>
  `).join("");

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">No properties in this selection.</td></tr>`;
  }
}

function initMap() {
  const mapEl = byId("permitMap");
  if (!mapEl || typeof L === "undefined" || state.map) return;

  state.map = L.map(mapEl).setView([47.6062, -122.3321], 11);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);

  state.mapLayer = L.layerGroup().addTo(state.map);
}

function markerRadius(units) {
  const u = Number(units || 0);
  if (u >= 100) return 14;
  if (u >= 50) return 11;
  if (u >= 20) return 9;
  if (u >= 5) return 7;
  return 5;
}

function markerColor(category) {
  if (category === "Demo") return "#b45309";
  if (category === "New MF") return "#2563eb";
  if (category === "New SFR") return "#0f766e";
  return "#64748b";
}

function renderMap() {
  initMap();
  if (!state.map || !state.mapLayer) return;

  state.mapLayer.clearLayers();

  const rows = filteredProjectRows();

  if (!rows.length) {
    byId("mapContext").textContent = "No properties in the current selection";
    return;
  }

  const bounds = [];

  rows.slice(0, 400).forEach((r) => {
    const marker = L.circleMarker([r.latitude, r.longitude], {
      radius: markerRadius(r.units),
      color: markerColor(r.category),
      weight: 1,
      fillColor: markerColor(r.category),
      fillOpacity: 0.75,
    });

    marker.bindPopup(`
      <div class="popup-card">
        <div class="popup-title">${escapeHtml(r.address)}</div>
        <div>${escapeHtml(r.market)} • ${escapeHtml(r.jurisdiction)}</div>
        <div>${escapeHtml(r.category)}</div>
        <div>Units: ${formatNumber(r.units)}</div>
        <div>Issued: ${escapeHtml((r.issue_date || "").slice(0, 10))}</div>
      </div>
    `);

    marker.addTo(state.mapLayer);
    bounds.push([r.latitude, r.longitude]);
  });

  if (bounds.length === 1) {
    state.map.setView(bounds[0], 14);
  } else {
    state.map.fitBounds(bounds, { padding: [20, 20] });
  }
}

function wireEvents() {
  ["jurisdiction", "category", "neighborhood", "startYear", "endYear"].forEach((id) => {
    const el = byId(id);
    if (!el) return;

    el.addEventListener("change", async () => {
      if (id === "neighborhood") {
        state.selectedNeighborhood = byId("neighborhood").value;
      }
      await loadSummary();
    });
  });

  const neighborhoodSearch = byId("neighborhoodSearch");
  if (neighborhoodSearch) {
    neighborhoodSearch.addEventListener("input", () => {
      const q = neighborhoodSearch.value.trim().toLowerCase();
      const select = byId("neighborhood");
      if (!select) return;
      const hit = [...select.options].find(
        (o) => o.value !== "all" && o.value.toLowerCase().includes(q)
      );
      if (hit) select.value = hit.value;
    });

    neighborhoodSearch.addEventListener("change", async () => {
      const select = byId("neighborhood");
      if (!select) return;
      state.selectedNeighborhood = select.value;
      await loadSummary();
    });
  }
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
