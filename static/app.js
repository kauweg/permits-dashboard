const state = { meta: null, summary: null, selectedNeighborhood: 'all', map: null, markers: null };
const byId = (id) => document.getElementById(id);
const SERIES = [
  { key: 'New SFR', label: 'New SFR', color: '#6d8fb3' },
  { key: 'New MF', label: 'New MF', color: '#9cb4c9' },
  { key: 'Other New', label: 'Other New', color: '#7aa37a' },
  { key: 'Demo', label: 'Demo', color: '#d8a45b' },
];

function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function formatNumber(n) { return new Intl.NumberFormat().format(n || 0); }
function queryString(obj) { return new URLSearchParams(obj).toString(); }
async function fetchJson(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); }

function getFilters() {
  return {
    jurisdiction: byId('jurisdiction').value,
    category: byId('category').value,
    neighborhood: state.selectedNeighborhood !== 'all' ? state.selectedNeighborhood : byId('neighborhood').value,
    start_year: byId('startYear').value,
    end_year: byId('endYear').value,
  };
}

function renderLoadMessages(notes, errors) {
  byId('loadNotes').innerHTML = (notes || []).map(n => `<span class="note-pill">${escapeHtml(n)}</span>`).join('');
  byId('loadErrors').innerHTML = (errors || []).map(e => `<div>${escapeHtml(e)}</div>`).join('');
}

function populateNeighborhoods(items) {
  const select = byId('neighborhood');
  const search = byId('neighborhoodSearch');
  const current = state.selectedNeighborhood === 'all' ? select.value : state.selectedNeighborhood;
  select.innerHTML = '<option value="all">All neighborhoods</option>';
  items.forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n;
    opt.textContent = n;
    select.appendChild(opt);
  });
  if ([...select.options].some(o => o.value === current)) select.value = current;
  search.value = current !== 'all' ? current : '';
}

async function loadMeta() {
  state.meta = await fetchJson('/api/meta');
  populateNeighborhoods(state.meta.neighborhoods || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  state.summary = await fetchJson(`/api/summary?${queryString(getFilters())}`);
  renderLoadMessages(state.summary.load_notes || [], state.summary.load_errors || []);
  renderCards(); renderLegend(byId('annualLegend')); renderLegend(byId('drilldownLegend')); renderAnnualChart(); renderNeighborhoodTable(); renderAnnualNeighborhoodTable(); renderDrilldownChart(); renderSamples(); renderMap();
}

function renderCards() {
  const c = state.summary.cards || {};
  const cards = [
    ['Total permits', c.total_permits], ['All new', c.all_new], ['Seattle', c.seattle_permits], ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods], ['Unknown permits', c.unknown_neighborhoods], ['New SFR', c.new_sfr], ['New MF', c.new_mf], ['Other New', c.other_new], ['Demo', c.demo],
  ];
  byId('cards').innerHTML = cards.map(([label, value]) => `<article class="card"><div class="card-label">${escapeHtml(label)}</div><div class="card-value">${formatNumber(value)}</div></article>`).join('');
}

function renderLegend(el) {
  el.innerHTML = SERIES.map(s => `<span class="legend-item"><span class="legend-swatch" style="background:${s.color}"></span>${escapeHtml(s.label)}</span>`).join('');
}

function drawGroupedBars(canvas, labels, series) {
  const ctx = canvas.getContext('2d');
  const ratio = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * ratio;
  canvas.height = canvas.clientHeight * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  ctx.clearRect(0, 0, cw, ch);
  const margin = { left: 44, right: 18, top: 16, bottom: 36 };
  const plotW = cw - margin.left - margin.right;
  const plotH = ch - margin.top - margin.bottom;
  const flat = series.flatMap(s => s.values || []);
  const maxVal = Math.max(1, ...flat, 1);
  ctx.strokeStyle = '#d6dee8';
  ctx.fillStyle = '#6b7785';
  ctx.font = '12px Arial';
  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cw - margin.right, y); ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
  }
  const groupW = plotW / Math.max(1, labels.length);
  const barW = Math.min(18, Math.max(8, (groupW - 10) / Math.max(1, series.length)));
  labels.forEach((label, li) => {
    const gx = margin.left + li * groupW + 4;
    series.forEach((s, si) => {
      const val = s.values[li] || 0;
      const barH = (val / maxVal) * plotH;
      const x = gx + si * barW;
      const y = margin.top + plotH - barH;
      ctx.fillStyle = s.color;
      ctx.fillRect(x, y, barW - 2, barH);
    });
    ctx.fillStyle = '#334155';
    ctx.fillText(String(label), gx, ch - 10);
  });
}

function renderAnnualChart() {
  const data = state.summary.annual_series || [];
  drawGroupedBars(byId('annualChart'), data.map(r => r.year), SERIES.map(s => ({ ...s, values: data.map(r => r[s.key] || 0) })));
}

function renderDrilldownChart() {
  const rows = state.summary.neighborhood_rows || [];
  const current = state.selectedNeighborhood !== 'all' ? rows.find(r => r.neighborhood === state.selectedNeighborhood) : rows[0];
  byId('drilldownTitle').textContent = current ? current.neighborhood : 'No neighborhood selected';
  if (!current) return drawGroupedBars(byId('drilldownChart'), [], []);
  const labels = Object.keys(current.years || {});
  drawGroupedBars(byId('drilldownChart'), labels, SERIES.map(s => ({ ...s, values: labels.map(y => current.years[y][s.key] || 0) })));
}

function renderNeighborhoodTable() {
  const tbody = byId('neighborhoodTable').querySelector('tbody');
  const rows = state.summary.neighborhood_rows || [];
  tbody.innerHTML = rows.slice(0, 50).map(r => `
    <tr data-neighborhood="${escapeHtml(r.neighborhood)}" class="${r.neighborhood === state.selectedNeighborhood ? 'selected' : ''}">
      <td>${escapeHtml(r.neighborhood)}</td>
      <td>${formatNumber(r.totals.Total)}</td>
      <td>${formatNumber(r.totals['All New'])}</td>
      <td>${formatNumber(r.totals['New SFR'])}</td>
      <td>${formatNumber(r.totals['New MF'])}</td>
      <td>${formatNumber(r.totals['Other New'])}</td>
      <td>${formatNumber(r.totals['Demo'])}</td>
    </tr>`).join('');
  tbody.querySelectorAll('tr').forEach((tr) => tr.addEventListener('click', async () => {
    state.selectedNeighborhood = tr.dataset.neighborhood;
    byId('neighborhood').value = state.selectedNeighborhood;
    byId('neighborhoodSearch').value = state.selectedNeighborhood;
    await loadSummary();
  }));
}

function renderAnnualNeighborhoodTable() {
  const rows = state.summary.neighborhood_rows || [];
  const target = state.selectedNeighborhood !== 'all' ? rows.filter(r => r.neighborhood === state.selectedNeighborhood) : rows.slice(0, 12);
  const years = (state.summary.annual_series || []).map(r => r.year);
  byId('annualNeighborhoodTable').querySelector('thead').innerHTML = `<tr><th>Neighborhood</th>${years.map(y => `<th>${y}</th>`).join('')}<th>Total</th></tr>`;
  byId('annualNeighborhoodTable').querySelector('tbody').innerHTML = target.map(r => `<tr><td>${escapeHtml(r.neighborhood)}</td>${years.map(y => `<td>${formatNumber(r.years[String(y)].Total)}</td>`).join('')}<td>${formatNumber(r.totals.Total)}</td></tr>`).join('');
}

function renderSamples() {
  byId('sampleTable').querySelector('tbody').innerHTML = (state.summary.samples || []).map(r => `<tr><td>${escapeHtml(r.jurisdiction)}</td><td>${escapeHtml(r.category)}</td><td>${escapeHtml(r.neighborhood)}</td><td>${escapeHtml(r.address)}</td><td>${escapeHtml((r.issue_date || r.intake_date || '').slice(0, 10))}</td></tr>`).join('');
}

function initMap() {
  if (state.map) return;
  state.map = L.map('map', { scrollWheelZoom: false }).setView([47.61, -122.20], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(state.map);
  state.markers = L.layerGroup().addTo(state.map);
}

function renderMap() {
  initMap();
  state.markers.clearLayers();
  const pts = state.summary.map_points || [];
  const bounds = [];
  pts.forEach((p) => {
    if (typeof p.latitude !== 'number' || typeof p.longitude !== 'number') return;
    const marker = L.circleMarker([p.latitude, p.longitude], {
      radius: 5,
      color: '#3b4a5a',
      weight: 1,
      fillColor: SERIES.find(s => s.key === p.category)?.color || '#6d8fb3',
      fillOpacity: 0.85,
    }).bindPopup(`<strong>${escapeHtml(p.address)}</strong><br>${escapeHtml(p.neighborhood)}<br>${escapeHtml(p.category)}<br>${escapeHtml(p.jurisdiction)}`);
    marker.addTo(state.markers);
    bounds.push([p.latitude, p.longitude]);
  });
  if (bounds.length) state.map.fitBounds(bounds, { padding: [24, 24] });
  else state.map.setView([47.61, -122.20], 10);
}

function wireEvents() {
  ['jurisdiction', 'category', 'neighborhood', 'startYear', 'endYear'].forEach((id) => {
    byId(id).addEventListener('change', async () => {
      if (id === 'neighborhood') state.selectedNeighborhood = byId('neighborhood').value;
      await loadSummary();
    });
  });
  byId('neighborhoodSearch').addEventListener('input', () => {
    const q = byId('neighborhoodSearch').value.trim().toLowerCase();
    const opts = [...byId('neighborhood').options];
    const hit = opts.find(o => o.value !== 'all' && o.value.toLowerCase().includes(q));
    if (hit) byId('neighborhood').value = hit.value;
  });
  byId('neighborhoodSearch').addEventListener('change', async () => {
    state.selectedNeighborhood = byId('neighborhood').value;
    await loadSummary();
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  wireEvents();
  try { await loadMeta(); await loadSummary(); } catch (err) { renderLoadMessages([], [err.message || String(err)]); }
});
