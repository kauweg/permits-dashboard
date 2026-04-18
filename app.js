const state = { meta: null, summary: null, selectedNeighborhood: 'all' };
const byId = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function formatNumber(n) { return new Intl.NumberFormat().format(n || 0); }
function queryString(obj) { return new URLSearchParams(obj).toString(); }
async function fetchJson(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); }

function getFilters() {
  const selected = state.selectedNeighborhood !== 'all' ? state.selectedNeighborhood : byId('neighborhood').value;
  return {
    jurisdiction: byId('jurisdiction').value,
    category: byId('category').value,
    neighborhood: selected || 'all',
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
  const unique = [...new Set((items || []).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  select.innerHTML = '<option value="all">All neighborhoods</option>';
  unique.forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n;
    opt.textContent = n;
    select.appendChild(opt);
  });
  if ([...select.options].some(o => o.value === current)) {
    select.value = current;
  } else {
    select.value = 'all';
    if (state.selectedNeighborhood !== 'all') state.selectedNeighborhood = 'all';
  }
  search.value = select.value !== 'all' ? select.value : '';
}

async function loadMeta() {
  state.meta = await fetchJson('/api/meta');
  populateNeighborhoods(state.meta.neighborhoods || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
}

async function loadSummary() {
  state.summary = await fetchJson(`/api/summary?${queryString(getFilters())}`);
  renderLoadMessages(state.summary.load_notes || [], state.summary.load_errors || []);
  renderCards();
  renderAnnualChart();
  renderNeighborhoodTable();
  renderAnnualNeighborhoodTable();
  renderDrilldownChart();
  renderSamples();
  renderMapList();
}


function renderLegend(targetId, items) {
  const el = byId(targetId);
  if (!el) return;
  el.innerHTML = items.map(item => `
    <span class="legend-item">
      <span class="legend-swatch" style="background:${item.color}"></span>
      <span>${escapeHtml(item.label)}</span>
    </span>
  `).join('');
}

const SERIES_META = [
  {key: 'New SFR', label: 'New SFR', color: '#6d8fb3'},
  {key: 'New MF', label: 'New MF', color: '#9cb4c9'},
  {key: 'Other New', label: 'Other New', color: '#8fa48f'},
  {key: 'Demo', label: 'Demo', color: '#d8a45b'},
];


function renderCards() {
  const c = state.summary.cards || {};
  const cards = [
    ['Total permits', c.total_permits], ['Seattle', c.seattle_permits], ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods], ['All new construction', c.total_new_construction], ['New SFR', c.new_sfr], ['New MF', c.new_mf], ['Other New', c.other_new], ['Demo', c.demo],
  ];
  byId('cards').innerHTML = cards.map(([label, value]) => `<article class="card"><div class="card-label">${escapeHtml(label)}</div><div class="card-value">${formatNumber(value)}</div></article>`).join('');
}

function drawGroupedBars(canvas, labels, series) {
  const ctx = canvas.getContext('2d');
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.width = canvas.clientWidth * ratio;
  const h = canvas.height = canvas.clientHeight * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  ctx.clearRect(0, 0, cw, ch);

  const margin = {left: 42, right: 18, top: 16, bottom: 32};
  const plotW = Math.max(1, cw - margin.left - margin.right);
  const plotH = Math.max(1, ch - margin.top - margin.bottom);
  const maxVal = Math.max(1, ...series.flatMap(s => s.values || []));
  const colors = ['#6d8fb3', '#9cb4c9', '#8fa48f', '#d8a45b'];

  ctx.strokeStyle = '#d6dee8';
  ctx.fillStyle = '#6b7785';
  ctx.font = '12px Arial';

  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(cw - margin.right, y);
    ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
  }

  if (!labels.length || !series.length) {
    ctx.fillStyle = '#6b7785';
    ctx.fillText('No data for current filters', margin.left, margin.top + 20);
    return;
  }

  const groupW = plotW / labels.length;
  const barW = Math.min(22, Math.max(8, (groupW - 12) / series.length));

  labels.forEach((label, li) => {
    const gx = margin.left + li * groupW + 6;
    series.forEach((s, si) => {
      const val = s.values[li] || 0;
      const barH = (val / maxVal) * plotH;
      const x = gx + si * barW;
      const y = margin.top + plotH - barH;
      ctx.fillStyle = colors[si % colors.length];
      ctx.fillRect(x, y, barW - 2, barH);
    });
    ctx.fillStyle = '#334155';
    ctx.fillText(String(label), gx, ch - 8);
  });
}

function renderAnnualChart() {
  const data = state.summary.annual_series || [];
  renderLegend('annualLegend', SERIES_META);
  drawGroupedBars(byId('annualChart'), data.map(r => r.year), [
    {name: 'New SFR', values: data.map(r => r['New SFR'])},
    {name: 'New MF', values: data.map(r => r['New MF'])},
    {name: 'Other New', values: data.map(r => r['Other New'])},
    {name: 'Demo', values: data.map(r => r['Demo'])},
  ]);
}

function renderDrilldownChart() {
  const rows = state.summary.neighborhood_rows || [];
  const current = state.selectedNeighborhood !== 'all'
    ? rows.find(r => r.neighborhood === state.selectedNeighborhood)
    : rows[0];
  byId('drilldownTitle').textContent = current ? current.neighborhood : 'No neighborhood selected';
  if (!current) {
    drawGroupedBars(byId('drilldownChart'), [], []);
    return;
  }
  const labels = Object.keys(current.years);
  renderLegend('drilldownLegend', SERIES_META);
  drawGroupedBars(byId('drilldownChart'), labels, [
    {name: 'New SFR', values: labels.map(y => current.years[y]['New SFR'])},
    {name: 'New MF', values: labels.map(y => current.years[y]['New MF'])},
    {name: 'Other New', values: labels.map(y => current.years[y]['Other New'])},
    {name: 'Demo', values: labels.map(y => current.years[y]['Demo'])},
  ]);
}

function renderNeighborhoodTable() {
  const tbody = byId('neighborhoodTable').querySelector('tbody');
  const rows = state.summary.neighborhood_rows || [];
  tbody.innerHTML = rows.slice(0, 40).map(r => `
    <tr data-neighborhood="${escapeHtml(r.neighborhood)}" class="${r.neighborhood === state.selectedNeighborhood ? 'selected' : ''}">
      <td>${escapeHtml(r.neighborhood)}</td>
      <td>${formatNumber(r.totals.Total)}</td>
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
  const target = state.selectedNeighborhood !== 'all'
    ? rows.filter(r => r.neighborhood === state.selectedNeighborhood)
    : rows.slice(0, 12);
  const years = (state.summary.annual_series || []).map(r => r.year);
  byId('annualNeighborhoodTable').querySelector('thead').innerHTML =
    `<tr><th>Neighborhood</th>${years.map(y => `<th>${y}</th>`).join('')}<th>Total</th></tr>`;
  byId('annualNeighborhoodTable').querySelector('tbody').innerHTML = target.map(r =>
    `<tr><td>${escapeHtml(r.neighborhood)}</td>${years.map(y => `<td>${formatNumber(r.years[String(y)].Total)}</td>`).join('')}<td>${formatNumber(r.totals.Total)}</td></tr>`
  ).join('');
}

function renderSamples() {
  byId('sampleTable').querySelector('tbody').innerHTML = (state.summary.samples || []).map(r =>
    `<tr><td>${escapeHtml(r.jurisdiction)}</td><td>${escapeHtml(r.category)}</td><td>${escapeHtml(r.neighborhood)}</td><td>${escapeHtml(r.address)}</td><td>${escapeHtml((r.issue_date || r.intake_date || '').slice(0, 10))}</td></tr>`
  ).join('');
}

function renderMapList() {
  const pts = state.summary.map_points || [];
  byId('mapList').innerHTML = pts.length
    ? pts.map(p => `<div class="map-pill"><strong>${escapeHtml(p.jurisdiction)}</strong><span>${escapeHtml(p.category)}</span><span>${escapeHtml(p.neighborhood)}</span><span>${escapeHtml(p.address)}</span></div>`).join('')
    : '<div class="muted">No mapped points in this filtered view.</div>';
}

function wireEvents() {
  ['jurisdiction', 'category', 'startYear', 'endYear'].forEach((id) => {
    byId(id).addEventListener('change', async () => { await loadSummary(); });
  });

  byId('neighborhood').addEventListener('change', async () => {
    state.selectedNeighborhood = byId('neighborhood').value;
    byId('neighborhoodSearch').value = state.selectedNeighborhood === 'all' ? '' : state.selectedNeighborhood;
    await loadSummary();
  });

  byId('neighborhoodSearch').addEventListener('input', () => {
    const q = byId('neighborhoodSearch').value.trim().toLowerCase();
    const opts = [...byId('neighborhood').options];
    if (!q) {
      byId('neighborhood').value = 'all';
      return;
    }
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
  try {
    await loadMeta();
    await loadSummary();
  } catch (err) {
    renderLoadMessages([], [err.message || String(err)]);
  }
});

window.addEventListener('resize', () => {
  if (state.summary) {
    renderAnnualChart();
    renderDrilldownChart();
  }
});
