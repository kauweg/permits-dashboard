const COLORS = {
  'New SFR': '#6d8fb3',
  'New MF': '#9cb4c9',
  'Other New': '#78a6a1',
  'Demo': '#d8a45b'
};
const state = { meta: null, summary: null, selectedNeighborhood: 'all', annualHitboxes: [], drillHitboxes: [], map: null, mapLayer: null };
const byId = (id) => document.getElementById(id);

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
    address_query: byId('addressSearch').value.trim(),
  };
}

function renderLegend(targetId) {
  byId(targetId).innerHTML = ['New SFR', 'New MF', 'Other New', 'Demo']
    .map((name) => `<span class="legend-item"><span class="legend-swatch" style="background:${COLORS[name]}"></span>${escapeHtml(name)}</span>`)
    .join('');
}

function renderLoadMessages(notes, errors) {
  byId('loadNotes').innerHTML = (notes || []).map(n => `<span class="note-pill">${escapeHtml(n)}</span>`).join('');
  byId('loadErrors').innerHTML = (errors || []).map(e => `<div>${escapeHtml(e)}</div>`).join('');
}

function populateNeighborhoods(items) {
  const select = byId('neighborhood');
  const current = state.selectedNeighborhood === 'all' ? select.value : state.selectedNeighborhood;
  select.innerHTML = '<option value="all">All neighborhoods</option>';
  (items || []).forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n; opt.textContent = n; select.appendChild(opt);
  });
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

async function loadMeta() {
  state.meta = await fetchJson('/api/meta');
  populateNeighborhoods(state.meta.neighborhoods || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  state.summary = await fetchJson(`/api/summary?${queryString(getFilters())}`);
  renderLoadMessages(state.summary.load_notes || [], state.summary.load_errors || []);
  renderCards(); renderAnnualChart(); renderNeighborhoodTable(); renderAnnualNeighborhoodTable(); renderDrilldownChart(); renderMap();
}

function renderCards() {
  const c = state.summary.cards || {};
  const cards = [
    ['Total permits', c.total_permits], ['Seattle', c.seattle_permits], ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods], ['All New', c.all_new], ['New MF', c.new_mf],
    ['Other New', c.other_new], ['New SFR', c.new_sfr], ['Demo', c.demo],
  ];
  byId('cards').innerHTML = cards.map(([label, value]) => `<article class="card"><div class="card-label">${escapeHtml(label)}</div><div class="card-value">${formatNumber(value)}</div></article>`).join('');
}

function drawGroupedBars(canvas, labels, series, readoutId, hitboxTarget) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth * window.devicePixelRatio;
  const h = canvas.height = canvas.clientHeight * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  ctx.clearRect(0,0,cw,ch);
  const margin = {left: 42, right: 18, top: 16, bottom: 32};
  const plotW = cw - margin.left - margin.right, plotH = ch - margin.top - margin.bottom;
  const maxVal = Math.max(1, ...series.flatMap(s => s.values));
  ctx.strokeStyle = '#d6dee8'; ctx.fillStyle = '#6b7785'; ctx.font = '12px Arial';
  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cw - margin.right, y); ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
  }
  const groupW = plotW / Math.max(1, labels.length), barW = Math.min(18, (groupW - 12) / Math.max(1, series.length));
  state[hitboxTarget] = [];
  labels.forEach((label, li) => {
    const gx = margin.left + li * groupW + 6;
    series.forEach((s, si) => {
      const val = s.values[li] || 0, barH = (val / maxVal) * plotH, x = gx + si * barW, y = margin.top + plotH - barH;
      ctx.fillStyle = COLORS[s.name] || '#999'; ctx.fillRect(x, y, barW - 2, barH);
      state[hitboxTarget].push({ x, y, w: barW - 2, h: barH, label, series: s.name, value: val, readoutId });
    });
    ctx.fillStyle = '#334155'; ctx.fillText(String(label), gx, ch - 8);
  });
}

function attachBarClicks(canvas, hitboxTarget) {
  canvas.onclick = (evt) => {
    const rect = canvas.getBoundingClientRect();
    const x = evt.clientX - rect.left; const y = evt.clientY - rect.top;
    const hit = (state[hitboxTarget] || []).find(h => x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h);
    if (hit) byId(hit.readoutId).textContent = `${hit.label} • ${hit.series}: ${formatNumber(hit.value)}`;
  };
}

function renderAnnualChart() {
  const data = state.summary.annual_series || [];
  drawGroupedBars(byId('annualChart'), data.map(r => r.year), [
    {name: 'New SFR', values: data.map(r => r['New SFR'] || 0)},
    {name: 'New MF', values: data.map(r => r['New MF'] || 0)},
    {name: 'Other New', values: data.map(r => r['Other New'] || 0)},
    {name: 'Demo', values: data.map(r => r['Demo'] || 0)},
  ], 'annualReadout', 'annualHitboxes');
}

function renderDrilldownChart() {
  const rows = state.summary.neighborhood_rows || [];
  const current = state.selectedNeighborhood !== 'all' ? rows.find(r => r.neighborhood === state.selectedNeighborhood) : rows[0];
  byId('drilldownTitle').textContent = current ? current.neighborhood : 'No neighborhood selected';
  if (!current) return drawGroupedBars(byId('drilldownChart'), [], [], 'drilldownReadout', 'drillHitboxes');
  const labels = Object.keys(current.years);
  drawGroupedBars(byId('drilldownChart'), labels, [
    {name: 'New SFR', values: labels.map(y => current.years[y]['New SFR'] || 0)},
    {name: 'New MF', values: labels.map(y => current.years[y]['New MF'] || 0)},
    {name: 'Other New', values: labels.map(y => current.years[y]['Other New'] || 0)},
    {name: 'Demo', values: labels.map(y => current.years[y]['Demo'] || 0)},
  ], 'drilldownReadout', 'drillHitboxes');
}

function renderNeighborhoodTable() {
  const tbody = byId('neighborhoodTable').querySelector('tbody');
  const rows = state.summary.neighborhood_rows || [];
  tbody.innerHTML = rows.slice(0, 40).map(r => `
    <tr data-neighborhood="${escapeHtml(r.neighborhood)}" class="${r.neighborhood === state.selectedNeighborhood ? 'selected' : ''}">
      <td>${escapeHtml(r.neighborhood)}</td><td>${formatNumber(r.totals.Total)}</td><td>${formatNumber((r.totals['New SFR'] || 0) + (r.totals['New MF'] || 0) + (r.totals['Other New'] || 0))}</td><td>${formatNumber(r.totals['New MF'])}</td><td>${formatNumber(r.totals['Other New'] || 0)}</td><td>${formatNumber(r.totals['Demo'])}</td>
    </tr>`).join('');
  tbody.querySelectorAll('tr').forEach((tr) => tr.addEventListener('click', async () => {
    state.selectedNeighborhood = tr.dataset.neighborhood; byId('neighborhood').value = state.selectedNeighborhood; byId('neighborhoodSearch').value = state.selectedNeighborhood; await loadSummary();
  }));
}

function renderAnnualNeighborhoodTable() {
  const rows = state.summary.neighborhood_rows || [];
  const target = state.selectedNeighborhood !== 'all' ? rows.filter(r => r.neighborhood === state.selectedNeighborhood) : rows.slice(0, 12);
  const years = (state.summary.annual_series || []).map(r => r.year);
  byId('annualNeighborhoodTable').querySelector('thead').innerHTML = `<tr><th>Neighborhood</th>${years.map(y => `<th>${y}</th>`).join('')}<th>Total</th></tr>`;
  byId('annualNeighborhoodTable').querySelector('tbody').innerHTML = target.map(r => `<tr><td>${escapeHtml(r.neighborhood)}</td>${years.map(y => `<td>${formatNumber(r.years[String(y)].Total)}</td>`).join('')}<td>${formatNumber(r.totals.Total)}</td></tr>`).join('');
}

function renderMap() {
  const pts = state.summary.map_points || [];
  state.mapLayer.clearLayers();
  const coords = pts.filter(p => Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude)));
  if (!coords.length) {
    byId('mapStatus').textContent = 'No mapped points in this filtered view yet. Run the refreshed data script that includes latitude/longitude to populate markers.';
    return;
  }
  coords.forEach((p) => {
    const marker = L.circleMarker([Number(p.latitude), Number(p.longitude)], {
      radius: 5,
      color: COLORS[p.category] || '#4b5563',
      weight: 2,
      fillOpacity: 0.7
    }).bindPopup(`<strong>${escapeHtml(p.category)}</strong><br>${escapeHtml(p.address)}<br>${escapeHtml(p.neighborhood || '')}`);
    marker.addTo(state.mapLayer);
  });
  const group = L.featureGroup(state.mapLayer.getLayers());
  state.map.fitBounds(group.getBounds().pad(0.15));
  byId('mapStatus').textContent = `${formatNumber(coords.length)} points shown on the map.`;
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
  byId('neighborhoodSearch').addEventListener('change', async () => { state.selectedNeighborhood = byId('neighborhood').value; await loadSummary(); });
  byId('addressSearch').addEventListener('change', loadSummary);
  byId('addressSearch').addEventListener('keyup', (e) => { if (e.key === 'Enter') loadSummary(); });
  attachBarClicks(byId('annualChart'), 'annualHitboxes');
  attachBarClicks(byId('drilldownChart'), 'drillHitboxes');
}

window.addEventListener('DOMContentLoaded', async () => {
  renderLegend('annualLegend'); renderLegend('drilldownLegend'); initMap(); wireEvents();
  try { await loadMeta(); await loadSummary(); } catch (err) { renderLoadMessages([], [err.message || String(err)]); }
});
