const state = { meta: null, summary: null, selectedNeighborhood: 'all', map: null, markers: null };
const byId = (id) => document.getElementById(id);
const SERIES = [
  { key: 'New SFR', color: '#6d8fb3' },
  { key: 'New MF', color: '#9cb4c9' },
  { key: 'Other New', color: '#7f8fa6' },
  { key: 'Demo', color: '#d8a45b' },
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

function renderLegend(targetId) {
  byId(targetId).innerHTML = SERIES.map(s => `<span class="legend-item"><span class="legend-swatch" style="background:${s.color}"></span>${escapeHtml(s.key)}</span>`).join('');
}

function populateNeighborhoods(items) {
  const select = byId('neighborhood');
  const search = byId('neighborhoodSearch');
  const current = state.selectedNeighborhood === 'all' ? select.value : state.selectedNeighborhood;
  select.innerHTML = '<option value="all">All neighborhoods</option>';
  (items || []).forEach((n) => {
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
  renderCards(); renderAnnualChart(); renderNeighborhoodTable(); renderAnnualNeighborhoodTable(); renderDrilldownChart(); renderSamples(); renderMap();
}

function renderCards() {
  const c = state.summary.cards || {};
  const cards = [
    ['Total permits', c.total_permits], ['Seattle', c.seattle_permits], ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods], ['Unknown permits', c.unknown_neighborhoods],
    ['All New', c.all_new], ['New SFR', c.new_sfr], ['New MF', c.new_mf], ['Other New', c.other_new], ['Demo', c.demo],
  ];
  byId('cards').innerHTML = cards.map(([label, value]) => `<article class="card"><div class="card-label">${escapeHtml(label)}</div><div class="card-value">${formatNumber(value)}</div></article>`).join('');
}

function drawGroupedBars(canvas, labels, series) {
  const ctx = canvas.getContext('2d');
  const ratio = window.devicePixelRatio || 1;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  canvas.width = cw * ratio;
  canvas.height = ch * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  const margin = {left: 42, right: 18, top: 16, bottom: 32};
  const plotW = cw - margin.left - margin.right, plotH = ch - margin.top - margin.bottom;
  const maxVal = Math.max(1, ...series.flatMap(s => s.values || [0]));
  ctx.strokeStyle = '#d6dee8'; ctx.fillStyle = '#6b7785'; ctx.font = '12px Arial';
  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cw - margin.right, y); ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
  }
  const groupW = plotW / Math.max(1, labels.length), barW = Math.max(8, Math.min(18, (groupW - 12) / Math.max(1, series.length)));
  labels.forEach((label, li) => {
    const gx = margin.left + li * groupW + 6;
    series.forEach((s, si) => {
      const val = s.values[li] || 0;
      const barH = (val / maxVal) * plotH;
      const x = gx + si * barW;
      const y = margin.top + plotH - barH;
      ctx.fillStyle = s.color || '#6d8fb3';
      ctx.fillRect(x, y, barW - 2, barH);
    });
    ctx.fillStyle = '#334155';
    ctx.fillText(String(label), gx, ch - 8);
  });
}

function renderAnnualChart() {
  renderLegend('annualLegend');
  const data = state.summary.annual_series || [];
  drawGroupedBars(byId('annualChart'), data.map(r => r.year), SERIES.map(s => ({ ...s, values: data.map(r => r[s.key] || 0) })));
}

function renderDrilldownChart() {
  renderLegend('drilldownLegend');
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
  tbody.innerHTML = rows.slice(0, 60).map(r => `
    <tr data-neighborhood="${escapeHtml(r.neighborhood)}" class="${r.neighborhood === state.selectedNeighborhood ? 'selected' : ''}">
      <td>${escapeHtml(r.neighborhood)}</td><td>${formatNumber(r.totals.Total)}</td><td>${formatNumber(r.totals['All New'])}</td><td>${formatNumber(r.totals['New SFR'])}</td><td>${formatNumber(r.totals['New MF'])}</td><td>${formatNumber(r.totals['Other New'])}</td><td>${formatNumber(r.totals['Demo'])}</td>
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
  state.map = L.map('map', { zoomControl: true }).setView([47.61, -122.20], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap' }).addTo(state.map);
  state.markers = L.layerGroup().addTo(state.map);
}

function renderMap() {
  initMap();
  state.markers.clearLayers();
  const pts = (state.summary.map_points || []).filter(p => Number.isFinite(+p.lat) && Number.isFinite(+p.lon));
  if (!pts.length) {
    state.map.setView([47.61, -122.20], 10);
    return;
  }
  const bounds = [];
  pts.forEach((p) => {
    const marker = L.circleMarker([+p.lat, +p.lon], { radius: 5, weight: 1, color: '#36536b', fillColor: '#6d8fb3', fillOpacity: 0.85 });
    marker.bindPopup(`<strong>${escapeHtml(p.category)}</strong><br>${escapeHtml(p.neighborhood)}<br>${escapeHtml(p.address)}`);
    marker.addTo(state.markers);
    bounds.push([+p.lat, +p.lon]);
  });
  state.map.fitBounds(bounds, { padding: [20, 20] });
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
