const SEATTLE_BASE = 'https://data.seattle.gov/resource/76t5-zqzr.json';
const BELLEVUE_BASE = 'https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Building_Permits/FeatureServer/0/query';

const DEMO_DATA = [
  { jurisdiction: 'Seattle', permitId: 'SE-DEMO-001', permitType: 'New Construction', permitClass: 'Building', description: 'Single family new construction', address: '1234 Demo Ave N', status: 'Issued', intakeDate: new Date('2025-05-10'), issueDate: new Date('2025-07-08'), latitude: 47.624, longitude: -122.321 },
  { jurisdiction: 'Seattle', permitId: 'SE-DEMO-002', permitType: 'Demolition', permitClass: 'Building', description: 'Demo existing structure', address: '2101 Example St', status: 'Issued', intakeDate: new Date('2025-11-02'), issueDate: new Date('2026-01-19'), latitude: 47.609, longitude: -122.338 },
  { jurisdiction: 'Seattle', permitId: 'SE-DEMO-003', permitType: 'Addition', permitClass: 'Building', description: 'Major residential addition', address: '500 Market View Dr', status: 'Pending', intakeDate: new Date('2026-01-12'), issueDate: null, latitude: 47.651, longitude: -122.347 },
  { jurisdiction: 'Bellevue', permitId: 'BE-DEMO-001', permitType: 'New Construction', permitClass: 'Residential', description: 'Townhome project', address: '400 Bellevue Way NE', status: 'Issued', intakeDate: new Date('2025-04-05'), issueDate: new Date('2025-08-01'), latitude: 47.615, longitude: -122.201 },
  { jurisdiction: 'Bellevue', permitId: 'BE-DEMO-002', permitType: 'Demolition', permitClass: 'Residential', description: 'Existing teardown', address: '8811 Main St', status: 'Issued', intakeDate: new Date('2025-08-18'), issueDate: new Date('2025-10-01'), latitude: 47.610, longitude: -122.193 },
  { jurisdiction: 'Bellevue', permitId: 'BE-DEMO-003', permitType: 'Apartment', permitClass: 'Commercial', description: 'Multifamily permit activity', address: '120 106th Ave NE', status: 'Pending', intakeDate: new Date('2026-02-09'), issueDate: null, latitude: 47.612, longitude: -122.198 }
];

const state = {
  all: [],
  filtered: [],
  charts: {},
  map: null,
  mapLayer: null,
  loading: false,
  loadMode: 'live',
};

function byId(id) { return document.getElementById(id); }
function fmt(n) { return new Intl.NumberFormat('en-US').format(Math.round(n || 0)); }
function fmt1(n) { return Number.isFinite(n) ? n.toFixed(1) : '—'; }
function fmtPct(v) { return Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : '—'; }
function safeLower(v) { return (v || '').toString().toLowerCase(); }
function formatDateShort(d) { return d ? d.toLocaleDateString() : '—'; }
function avg(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null; }
function yearMonth(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
function yearKey(d) { return String(d.getFullYear()); }

function parseDate(v) {
  if (!v && v !== 0) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

function normalizeSeattle(r) {
  return {
    jurisdiction: 'Seattle',
    permitId: r.permitnum || r.permitnumber || '',
    permitType: r.permittype || r.category || r.permitclass || 'Unknown',
    permitClass: r.permitclass || '',
    description: r.description || '',
    address: r.originaladdress1 || r.address || '',
    status: r.statuscurrent || r.currentstatus || '',
    intakeDate: parseDate(r.applieddate),
    issueDate: parseDate(r.issueddate),
    latitude: Number(r.latitude),
    longitude: Number(r.longitude),
  };
}

function normalizeBellevue(feature) {
  const r = feature && feature.attributes ? feature.attributes : feature;
  const g = feature && feature.geometry ? feature.geometry : null;
  return {
    jurisdiction: 'Bellevue',
    permitId: r.PERMITNUMBER || r.PERMIT_NUMBER || r.permit_number || r.PermitNumber || '',
    permitType: r.PERMITTYPE || r.PERMIT_TYPE || r.permit_type || r.PermitType || r.CATEGORY || 'Unknown',
    permitClass: r.PERMITCATEGORY || r.PERMIT_CATEGORY || r.CATEGORY || '',
    description: r.PERMITTYPEDESCRIPTION || r.DESCRIPTION || r.description || '',
    address: r.SITEADDRESS || r.SITE_ADDRESS || r.site_address || r.ADDRESS || '',
    status: r.PERMITSTATUS || r.STATUS || r.status || '',
    intakeDate: parseDate(r.APPLICATIONDATE || r.APPLIEDDATE || r.application_date || r.AppliedDate),
    issueDate: parseDate(r.ISSUEDDATE || r.ISSUE_DATE || r.issued_date || r.IssuedDate),
    latitude: g && Number.isFinite(g.y) ? Number(g.y) : Number(r.LATITUDE),
    longitude: g && Number.isFinite(g.x) ? Number(g.x) : Number(r.LONGITUDE),
  };
}

function isConstructionLike(row, mode) {
  if (mode === 'all') return true;
  const text = [row.permitType, row.permitClass, row.description, row.status].filter(Boolean).join(' ').toLowerCase();
  const hasPositive = /(new|construction|build|building|demo|demolition|townhouse|single family|sfr|duplex|triplex|fourplex|multifamily|apartment|adu|dadu|addition|foundation)/.test(text);
  const hasNegative = /(electrical|mechanical|plumbing|side sewer|reroof|re-roof|sign|tree|right of way|utility|utilities|tenant improvement|ti only|fire alarm|sprinkler|furnace|water heater)/.test(text);
  if (mode === 'strict') return hasPositive && !hasNegative;
  if (mode === 'broad') return hasPositive || !hasNegative;
  return true;
}

function primaryDate(row, mode) {
  return mode === 'issued' ? row.issueDate : row.intakeDate;
}

function searchText(row) {
  return [row.jurisdiction, row.permitId, row.permitType, row.permitClass, row.description, row.address, row.status]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

async function fetchSeattle() {
  const select = [
    'permitnum', 'permitclass', 'permittype', 'applieddate', 'issueddate', 'statuscurrent', 'originaladdress1', 'description', 'latitude', 'longitude'
  ].join(',');
  const where = encodeURIComponent("applieddate >= '2020-01-01T00:00:00'");
  const limit = 50000;
  let offset = 0;
  let out = [];

  while (true) {
    const url = `${SEATTLE_BASE}?$select=${select}&$where=${where}&$order=applieddate DESC&$limit=${limit}&$offset=${offset}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Seattle API request failed (${res.status})`);
    const rows = await res.json();
    out = out.concat(rows.map(normalizeSeattle));
    if (rows.length < limit) break;
    offset += limit;
  }
  return out;
}

async function fetchBellevue() {
  const baseParams = new URLSearchParams({
    where: '1=1',
    outFields: '*',
    returnGeometry: 'true',
    f: 'json'
  });

  const countRes = await fetch(`${BELLEVUE_BASE}?${baseParams.toString()}&returnCountOnly=true`);
  if (!countRes.ok) throw new Error(`Bellevue count request failed (${countRes.status})`);
  const countData = await countRes.json();
  const total = Number(countData.count || 0);

  const pageSize = 2000;
  let offset = 0;
  let out = [];

  while (offset < total) {
    const url = `${BELLEVUE_BASE}?${baseParams.toString()}&resultOffset=${offset}&resultRecordCount=${pageSize}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Bellevue API request failed (${res.status})`);
    const data = await res.json();
    const rows = Array.isArray(data.features) ? data.features : [];
    out = out.concat(rows.map(normalizeBellevue));
    if (rows.length < pageSize) break;
    offset += pageSize;
  }
  return out;
}

function populateYears(records) {
  const years = Array.from(new Set(records.flatMap(r => [r.intakeDate?.getFullYear(), r.issueDate?.getFullYear()]).filter(Boolean))).sort((a, b) => a - b);
  const start = byId('startYear');
  const end = byId('endYear');
  start.innerHTML = '';
  end.innerHTML = '';
  years.forEach(y => {
    const a = document.createElement('option');
    a.value = y; a.textContent = y; start.appendChild(a);
    const b = document.createElement('option');
    b.value = y; b.textContent = y; end.appendChild(b);
  });
  if (years.length) {
    start.value = Math.max(years[0], years[years.length - 5] || years[0]);
    end.value = years[years.length - 1];
  }
}

function getFilters() {
  return {
    jurisdiction: byId('jurisdictionFilter').value,
    startYear: Number(byId('startYear').value),
    endYear: Number(byId('endYear').value),
    dateMode: byId('dateMode').value,
    scopeMode: byId('scopeMode').value,
    search: byId('searchBox').value.trim().toLowerCase(),
  };
}

function applyFilters() {
  const f = getFilters();
  const base = state.all.filter(r => {
    if (f.jurisdiction !== 'all' && r.jurisdiction !== f.jurisdiction) return false;
    if (!isConstructionLike(r, f.scopeMode)) return false;
    const d = primaryDate(r, f.dateMode);
    if (!d) return false;
    const y = d.getFullYear();
    if (y < f.startYear || y > f.endYear) return false;
    return true;
  });
  state.filtered = base;
  render(base, f.search);
}

function rolling12(records, mode, startOffsetMonths, endOffsetMonths) {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - startOffsetMonths, 1);
  const end = new Date(now.getFullYear(), now.getMonth() - endOffsetMonths + 1, 1);
  return records.filter(r => {
    const d = primaryDate(r, mode);
    return d && d >= start && d < end;
  }).length;
}

function lagDays(records) {
  const days = records
    .filter(r => r.intakeDate && r.issueDate)
    .map(r => (r.issueDate - r.intakeDate) / 86400000)
    .filter(v => Number.isFinite(v) && v >= 0 && v < 5000);
  return avg(days);
}

function signalFor(records, mode) {
  const recent = rolling12(records, mode, 11, 0);
  const prior = rolling12(records, mode, 23, 12);
  const yoy = prior > 0 ? (recent - prior) / prior : null;
  const days = lagDays(records);

  let read = 'Limited signal';
  if (yoy === null) read = 'Limited signal';
  else if (yoy > 0.2) read = 'Rising activity';
  else if (yoy < -0.2) read = 'Cooling activity';
  else read = 'Stable / normalizing';
  if (Number.isFinite(days) && days > 180 && yoy !== null && yoy >= 0) read = 'Rising with friction';

  return { recent, prior, yoy, days, read };
}

function groupedCounts(records, mode, groupFn) {
  const map = new Map();
  for (const r of records) {
    const d = primaryDate(r, mode);
    if (!d) continue;
    const k = groupFn(d);
    map.set(k, (map.get(k) || 0) + 1);
  }
  return Array.from(map.entries()).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
}

function initCharts() {
  state.charts.monthly = new Chart(byId('monthlyChart').getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: true } }
    }
  });
  state.charts.annual = new Chart(byId('annualChart').getContext('2d'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: { y: { beginAtZero: true } }
    }
  });
}

function initMap() {
  state.map = L.map('permitMap').setView([47.611, -122.245], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(state.map);
  state.mapLayer = L.layerGroup().addTo(state.map);
}

function updateHeadlines(records) {
  const mode = getFilters().dateMode;
  const sig = signalFor(records, mode);
  let friction = 'Limited';
  if (Number.isFinite(sig.days)) {
    if (sig.days > 180) friction = 'Elevated';
    else if (sig.days > 90) friction = 'Moderate';
    else friction = 'Contained';
  }
  byId('headlineRead').textContent = sig.read;
  byId('headlineFriction').textContent = friction;
  byId('headlineSource').textContent = state.loadMode === 'demo' ? 'Demo fallback' : 'Live feeds';
}

function updateKPIs(records) {
  const f = getFilters();
  const sig = signalFor(records, f.dateMode);
  byId('kpiRecords').textContent = fmt(records.length);
  byId('kpiWindow').textContent = `${f.startYear}–${f.endYear} | ${f.jurisdiction === 'all' ? 'Both jurisdictions' : f.jurisdiction}`;
  byId('kpiLag').textContent = Number.isFinite(sig.days) ? fmt1(sig.days) : '—';
  byId('kpiYoY').textContent = fmtPct(sig.yoy);
  byId('kpiYoYSub').textContent = `Recent 12 mo: ${fmt(sig.recent)} | Prior 12 mo: ${fmt(sig.prior)}`;
  byId('kpiSignal').textContent = sig.read;
  byId('kpiSignalSub').textContent = Number.isFinite(sig.days) ? `Average issue lag ${fmt1(sig.days)} days` : 'Issue lag needs more usable dates';
}

function updateSignalTable(records) {
  const mode = getFilters().dateMode;
  const jurisdictions = ['Seattle', 'Bellevue'];
  byId('signalTable').innerHTML = jurisdictions.map(name => {
    const subset = records.filter(r => r.jurisdiction === name);
    const sig = signalFor(subset, mode);
    return `<tr>
      <td>${name}</td>
      <td>${fmt(sig.recent)}</td>
      <td>${fmt(sig.prior)}</td>
      <td>${fmtPct(sig.yoy)}</td>
      <td>${Number.isFinite(sig.days) ? fmt1(sig.days) : '—'}</td>
      <td>${sig.read}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6">No records.</td></tr>';
}

function updateMonthlyChart(records) {
  const mode = getFilters().dateMode;
  const sea = groupedCounts(records.filter(r => r.jurisdiction === 'Seattle'), mode, yearMonth);
  const bel = groupedCounts(records.filter(r => r.jurisdiction === 'Bellevue'), mode, yearMonth);
  const labels = Array.from(new Set([...sea.map(x => x[0]), ...bel.map(x => x[0])])).sort();
  const seaMap = new Map(sea);
  const belMap = new Map(bel);
  state.charts.monthly.data.labels = labels;
  state.charts.monthly.data.datasets = [
    { label: 'Seattle', data: labels.map(k => seaMap.get(k) || 0), borderColor: '#2f6fed', backgroundColor: 'rgba(47,111,237,0.12)', tension: 0.2, fill: false },
    { label: 'Bellevue', data: labels.map(k => belMap.get(k) || 0), borderColor: '#0f766e', backgroundColor: 'rgba(15,118,110,0.12)', tension: 0.2, fill: false }
  ];
  state.charts.monthly.update();
}

function updateAnnualChart(records) {
  const mode = getFilters().dateMode;
  const sea = groupedCounts(records.filter(r => r.jurisdiction === 'Seattle'), mode, yearKey);
  const bel = groupedCounts(records.filter(r => r.jurisdiction === 'Bellevue'), mode, yearKey);
  const labels = Array.from(new Set([...sea.map(x => x[0]), ...bel.map(x => x[0])])).sort();
  const seaMap = new Map(sea);
  const belMap = new Map(bel);
  state.charts.annual.data.labels = labels;
  state.charts.annual.data.datasets = [
    { label: 'Seattle', data: labels.map(k => seaMap.get(k) || 0), backgroundColor: 'rgba(47,111,237,0.82)' },
    { label: 'Bellevue', data: labels.map(k => belMap.get(k) || 0), backgroundColor: 'rgba(15,118,110,0.82)' }
  ];
  state.charts.annual.update();
}

function updateMixTable(records) {
  const total = records.length || 1;
  const counts = new Map();
  records.forEach(r => {
    const k = (r.permitType || 'Unknown').slice(0, 70);
    counts.set(k, (counts.get(k) || 0) + 1);
  });
  const rows = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 12);
  byId('mixTable').innerHTML = rows.map(([name, count]) => `
    <tr>
      <td>${name}</td>
      <td>${fmt(count)}</td>
      <td>${fmtPct(count / total)}</td>
    </tr>`).join('') || '<tr><td colspan="3">No records in current view.</td></tr>';
}

function updateSearchAndMap(records, search) {
  const rows = search ? records.filter(r => searchText(r).includes(search)) : records;
  const shown = rows.slice(0, 250);
  byId('searchCount').textContent = `${fmt(shown.length)} rows shown`;
  byId('searchTable').innerHTML = shown.map(r => `
    <tr>
      <td>${r.jurisdiction}</td>
      <td>${r.permitId || '—'}</td>
      <td>${r.address || '—'}</td>
      <td>${r.permitType || '—'}</td>
      <td>${r.status || '—'}</td>
      <td>${formatDateShort(r.issueDate)}</td>
    </tr>`).join('') || '<tr><td colspan="6">No matching permits.</td></tr>';

  state.mapLayer.clearLayers();
  const mapped = rows.filter(r => Number.isFinite(r.latitude) && Number.isFinite(r.longitude) && Math.abs(r.latitude) < 90 && Math.abs(r.longitude) < 180).slice(0, 500);
  mapped.forEach(r => {
    const isSeattle = r.jurisdiction === 'Seattle';
    const marker = L.circleMarker([r.latitude, r.longitude], {
      radius: 5,
      weight: 1,
      color: isSeattle ? '#1d4ed8' : '#0f766e',
      fillColor: isSeattle ? '#60a5fa' : '#2dd4bf',
      fillOpacity: 0.8,
    }).bindPopup(`<strong>${r.jurisdiction}</strong><br>${r.permitId || 'No permit #'}<br>${r.address || 'No address'}<br>${r.permitType || 'Unknown'}<br>Issued: ${formatDateShort(r.issueDate)}`);
    marker.addTo(state.mapLayer);
  });
  byId('mapCount').textContent = `${fmt(mapped.length)} mapped permits`;
  if (mapped.length) {
    const bounds = L.latLngBounds(mapped.map(r => [r.latitude, r.longitude]));
    state.map.fitBounds(bounds.pad(0.15));
  }
}

function render(records, search) {
  updateHeadlines(records);
  updateKPIs(records);
  updateSignalTable(records);
  updateMonthlyChart(records);
  updateAnnualChart(records);
  updateMixTable(records);
  updateSearchAndMap(records, search);
  byId('recordPill').textContent = `${fmt(records.length)} records in current filtered view`;
}

function setStatus(text, tone = 'info') {
  const pill = byId('statusPill');
  pill.textContent = text;
  pill.className = `pill ${tone}`;
}

function useDemoFallback(reason) {
  state.loadMode = 'demo';
  state.all = DEMO_DATA;
  populateYears(state.all);
  setStatus(`Live load failed — demo fallback loaded (${reason})`, 'warn');
  applyFilters();
}

async function loadData(forceRefresh = false) {
  if (state.loading) return;
  state.loading = true;
  setStatus(forceRefresh ? 'Refreshing live data…' : 'Loading live Seattle + Bellevue data…', 'info');

  try {
    const [seattle, bellevue] = await Promise.all([fetchSeattle(), fetchBellevue()]);
    state.loadMode = 'live';
    state.all = [...seattle, ...bellevue];
    populateYears(state.all);
    setStatus(`Live data loaded: Seattle ${fmt(seattle.length)} + Bellevue ${fmt(bellevue.length)}`, 'good');
    applyFilters();
  } catch (err) {
    console.error(err);
    useDemoFallback(err.message || 'unknown error');
  } finally {
    state.loading = false;
  }
}

function wireEvents() {
  ['jurisdictionFilter', 'startYear', 'endYear', 'dateMode', 'scopeMode'].forEach(id => {
    byId(id).addEventListener('change', applyFilters);
  });
  byId('searchBox').addEventListener('input', () => render(state.filtered, getFilters().search));
  byId('refreshButton').addEventListener('click', () => loadData(true));
}

function init() {
  initCharts();
  initMap();
  wireEvents();
  loadData();
}

window.addEventListener('DOMContentLoaded', init);
