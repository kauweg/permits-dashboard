const state = {
  meta: null,
  summary: null,
  projects: [],
  filteredProjects: [],
  selectedId: null,
  map: null,
  markerLayer: null,
};

const byId = (id) => document.getElementById(id);

const HOOD_COORDS = {
  "West Seattle": [47.571, -122.386],
  "Admiral": [47.577, -122.387],
  "Alki": [47.576, -122.409],
  "Ballard": [47.668, -122.386],
  "Beacon Hill": [47.579, -122.312],
  "Belltown": [47.614, -122.349],
  "Capitol Hill": [47.624, -122.320],
  "Central District": [47.608, -122.303],
  "Columbia City": [47.559, -122.286],
  "Delridge": [47.571, -122.362],
  "Downtown": [47.6062, -122.3321],
  "First Hill": [47.609, -122.325],
  "Fremont": [47.651, -122.350],
  "Georgetown": [47.548, -122.321],
  "Greenwood": [47.690, -122.355],
  "Interbay": [47.642, -122.376],
  "Lake City": [47.717, -122.297],
  "Madison Park": [47.633, -122.277],
  "Magnolia": [47.648, -122.399],
  "Mount Baker": [47.576, -122.296],
  "Northgate": [47.708, -122.325],
  "Phinney Ridge": [47.675, -122.354],
  "Queen Anne": [47.637, -122.356],
  "Rainier Beach": [47.522, -122.269],
  "Rainier Valley": [47.552, -122.285],
  "Ravenna": [47.675, -122.299],
  "Roosevelt": [47.681, -122.317],
  "SODO": [47.579, -122.334],
  "South Lake Union": [47.623, -122.338],
  "U District": [47.661, -122.313],
  "University District": [47.661, -122.313],
  "Wallingford": [47.661, -122.337],
  "West Seattle Junction": [47.562, -122.386],

  "Bellevue Downtown": [47.6101, -122.2015],
  "Downtown Bellevue": [47.6101, -122.2015],
  "Bellevue": [47.6101, -122.2015],
  "Wilburton": [47.595, -122.178],
  "BelRed": [47.630, -122.184],
  "Crossroads": [47.619, -122.121],
  "Factoria": [47.576, -122.169],
  "Eastgate": [47.579, -122.135],
  "Newport": [47.571, -122.180],
  "West Bellevue": [47.617, -122.214],
  "Woodridge": [47.587, -122.153],
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[m]));
}

function formatNumber(n) {
  return new Intl.NumberFormat().format(Number(n || 0));
}

function notePills(items) {
  return (items || []).map(x => `<span class="note-pill">${escapeHtml(x)}</span>`).join("");
}

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function normalizeType(row) {
  const raw = String(
    row.category ||
    row.type ||
    row.project_type ||
    ""
  ).trim();

  if (raw === "New SFR") return "New SFR";
  if (raw === "New MF") return "New MF";
  if (raw === "Demo") return "Demo";
  if (raw === "Other New") return "Other New";

  const text = [
    row.category,
    row.type,
    row.description,
    row.summary,
    row.address,
  ].join(" ").toLowerCase();

  if (text.includes("demo")) return "Demo";
  if (text.includes("multi")) return "New MF";
  if (text.includes("single family") || text.includes("sfr")) return "New SFR";

  return "Other New";
}

function normalizeStatus(row) {
  const text = [
    row.status,
    row.permit_status,
    row.description,
    row.summary,
  ].join(" ").toLowerCase();

  if (
    text.includes("complete") ||
    text.includes("completed") ||
    text.includes("final")
  ) return "Completed";

  if (
    text.includes("issued") ||
    text.includes("approved") ||
    text.includes("ready")
  ) return "Approved";

  return "Applied";
}

function parseDate(row) {
  return row.issue_date || row.intake_date || row.updated || "";
}

function parsePermit(row, idx) {
  return (
    row.permit ||
    row.permit_number ||
    row.id ||
    row.number ||
    `Permit-${idx + 1}`
  );
}

function cleanNeighborhood(row) {
  const n = String(row.neighborhood || "").trim();
  if (!n || n.toLowerCase() === "unknown") {
    return row.jurisdiction === "Bellevue" ? "Bellevue" : "Unknown";
  }
  return n;
}

function hasValidCoord(val) {
  return val !== null && val !== undefined && val !== "" && !Number.isNaN(Number(val));
}

function jitter(baseLat, baseLng, idx) {
  const lat = baseLat + ((idx % 7) - 3) * 0.0022;
  const lng = baseLng + ((Math.floor(idx / 7) % 7) - 3) * 0.0022;
  return [lat, lng];
}

function resolveCoords(row, idx) {
  const lat = row.latitude ?? row.lat;
  const lng = row.longitude ?? row.lng ?? row.lon;

  if (hasValidCoord(lat) && hasValidCoord(lng)) {
    return [Number(lat), Number(lng)];
  }

  const hood = cleanNeighborhood(row);
  if (HOOD_COORDS[hood]) {
    return jitter(HOOD_COORDS[hood][0], HOOD_COORDS[hood][1], idx);
  }

  if (row.jurisdiction === "Bellevue") {
    return jitter(47.6101, -122.2015, idx);
  }

  return jitter(47.6062, -122.3321, idx);
}

function buildProjects(summary) {
  const rows =
    Array.isArray(summary?.map_points) && summary.map_points.length
      ? summary.map_points
      : (summary?.samples || []);

  return rows.map((row, idx) => {
    const neighborhood = cleanNeighborhood(row);
    const city = row.jurisdiction || row.city || "Seattle";
    const type = normalizeType(row);
    const status = normalizeStatus(row);
    const [lat, lng] = resolveCoords(row, idx);

    return {
      id: `${parsePermit(row, idx)}-${idx}`,
      address: row.address || `Project ${idx + 1}`,
      neighborhood,
      city,
      type,
      status,
      permit: parsePermit(row, idx),
      updated: parseDate(row),
      summary:
        row.summary ||
        row.description ||
        `${type} activity in ${neighborhood}, ${city}.`,
      latitude: lat,
      longitude: lng,
      raw: row,
    };
  });
}

function initMap() {
  if (state.map) return;

  state.map = L.map("permitMap", {
    zoomControl: true,
    preferCanvas: true,
  }).setView([47.6062, -122.3321], 11);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(state.map);

  state.markerLayer = L.markerClusterGroup({
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 15,
    chunkedLoading: true,
  });

  state.map.addLayer(state.markerLayer);
}

function markerColor(type) {
  if (type === "Demo") return "#b45309";
  if (type === "New MF") return "#1d4ed8";
  if (type === "New SFR") return "#0f766e";
  return "#475569";
}

function makeMarker(project) {
  const icon = L.divIcon({
    className: "custom-marker-wrap",
    html: `<div class="custom-marker" style="background:${markerColor(project.type)}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10],
  });

  const marker = L.marker([project.latitude, project.longitude], { icon });

  marker.on("click", () => {
    state.selectedId = project.id;
    renderDetail(project);
    highlightSelectedRow();
  });

  marker.bindPopup(`
    <div class="popup-card">
      <div class="popup-title">${escapeHtml(project.address)}</div>
      <div>${escapeHtml(project.neighborhood)} • ${escapeHtml(project.city)}</div>
      <div>${escapeHtml(project.type)} • ${escapeHtml(project.status)}</div>
      <div>${escapeHtml(project.permit)}</div>
    </div>
  `);

  return marker;
}

function renderCounts() {
  const visible = state.filteredProjects.length;
  const seattle = state.filteredProjects.filter(p => p.city === "Seattle").length;
  const bellevue = state.filteredProjects.filter(p => p.city === "Bellevue").length;

  byId("visibleCount").textContent = formatNumber(visible);
  byId("seattleCount").textContent = formatNumber(seattle);
  byId("bellevueCount").textContent = formatNumber(bellevue);
  byId("projectListCount").textContent = `${formatNumber(visible)} projects`;
}

function renderList() {
  const el = byId("projectList");
  const rows = state.filteredProjects.slice(0, 300);

  if (!rows.length) {
    el.innerHTML = `<div class="empty-state">No matching projects.</div>`;
    return;
  }

  el.innerHTML = rows.map(project => `
    <button class="project-row ${state.selectedId === project.id ? "active" : ""}" data-project-id="${escapeHtml(project.id)}">
      <div class="project-row-title">${escapeHtml(project.address)}</div>
      <div class="project-row-sub">${escapeHtml(project.neighborhood)} • ${escapeHtml(project.city)}</div>
      <div class="project-row-tags">
        <span class="tag">${escapeHtml(project.status)}</span>
        <span class="tag">${escapeHtml(project.type)}</span>
      </div>
    </button>
  `).join("");

  el.querySelectorAll(".project-row").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-project-id");
      const project = state.filteredProjects.find(p => p.id === id);
      if (!project) return;
      state.selectedId = project.id;
      renderDetail(project);
      highlightSelectedRow();
      state.map.setView([project.latitude, project.longitude], 15);
    });
  });
}

function highlightSelectedRow() {
  document.querySelectorAll(".project-row").forEach(row => {
    row.classList.toggle("active", row.getAttribute("data-project-id") === state.selectedId);
  });
}

function renderDetail(project) {
  const el = byId("detailCard");

  if (!project) {
    el.innerHTML = `<div class="muted">Select a project from the list or the map.</div>`;
    return;
  }

  el.innerHTML = `
    <div class="detail-title">${escapeHtml(project.address)}</div>
    <div class="detail-sub">${escapeHtml(project.neighborhood)} • ${escapeHtml(project.city)}</div>

    <div class="detail-grid">
      <div class="detail-stat">
        <div class="detail-stat-label">Status</div>
        <div class="detail-stat-value">${escapeHtml(project.status)}</div>
      </div>
      <div class="detail-stat">
        <div class="detail-stat-label">Type</div>
        <div class="detail-stat-value">${escapeHtml(project.type)}</div>
      </div>
      <div class="detail-stat">
        <div class="detail-stat-label">Permit</div>
        <div class="detail-stat-value">${escapeHtml(project.permit)}</div>
      </div>
      <div class="detail-stat">
        <div class="detail-stat-label">Updated</div>
        <div class="detail-stat-value">${escapeHtml(project.updated || "—")}</div>
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-section-title">Summary</div>
      <div class="detail-copy">${escapeHtml(project.summary)}</div>
    </div>
  `;
}

function renderMap() {
  if (!state.map || !state.markerLayer) return;

  state.markerLayer.clearLayers();

  if (!state.filteredProjects.length) return;

  const markers = state.filteredProjects.map(project => makeMarker(project));
  state.markerLayer.addLayers(markers);

  const bounds = L.latLngBounds(
    state.filteredProjects.map(p => [p.latitude, p.longitude])
  );

  if (bounds.isValid()) {
    state.map.fitBounds(bounds, { padding: [25, 25] });
  }
}

function applyFilters() {
  const q = (byId("searchInput").value || "").trim().toLowerCase();
  const city = byId("cityFilter").value;
  const status = byId("statusFilter").value;
  const type = byId("typeFilter").value;

  state.filteredProjects = state.projects.filter(project => {
    const haystack = [
      project.address,
      project.neighborhood,
      project.city,
      project.permit,
      project.summary,
    ].join(" ").toLowerCase();

    const qMatch = !q || haystack.includes(q);
    const cityMatch = city === "all" || project.city === city;
    const statusMatch = status === "all" || project.status === status;
    const typeMatch = type === "all" || project.type === type;

    return qMatch && cityMatch && statusMatch && typeMatch;
  });

  if (!state.filteredProjects.some(p => p.id === state.selectedId)) {
    state.selectedId = state.filteredProjects[0]?.id || null;
  }

  renderCounts();
  renderList();
  renderMap();

  const selected = state.filteredProjects.find(p => p.id === state.selectedId) || state.filteredProjects[0] || null;
  renderDetail(selected);
  highlightSelectedRow();
}

function wireEvents() {
  ["searchInput", "cityFilter", "statusFilter", "typeFilter"].forEach(id => {
    const el = byId(id);
    if (!el) return;
    const evt = id === "searchInput" ? "input" : "change";
    el.addEventListener(evt, applyFilters);
  });
}

async function boot() {
  try {
    const [meta, summary] = await Promise.all([
      fetchJson("/api/meta"),
      fetchJson("/api/summary"),
    ]);

    state.meta = meta;
    state.summary = summary;
    state.projects = buildProjects(summary);

    byId("loadNotes").innerHTML = notePills([
      ...(meta.load_notes || []),
      ...(summary.load_notes || []),
    ]);

    byId("loadErrors").innerHTML = ([
      ...(meta.load_errors || []),
      ...(summary.load_errors || []),
    ]).map(x => `<div class="error-pill">${escapeHtml(x)}</div>`).join("");

    initMap();
    wireEvents();
    applyFilters();
  } catch (err) {
    byId("loadErrors").innerHTML = `<div class="error-pill">${escapeHtml(err.message || String(err))}</div>`;
  }
}

window.addEventListener("DOMContentLoaded", boot);
