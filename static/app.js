const state = {
  meta: null,
  summary: null,
  selectedNeighborhood: 'all',
};

const byId = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function formatNumber(n) {
  return new Intl.NumberFormat().format(n || 0);
}

function getFilters() {
  return {
    jurisdiction: byId('jurisdiction').value,
    category: byId('category').value,
    neighborhood: state.selectedNeighborhood !== 'all' ? state.selectedNeighborhood : byId('neighborhood').value,
    start_year: byId('startYear').value,
    end_year: byId('endYear').value,
  };
}

function queryString(obj) {
  return new URLSearchParams(obj).toString();
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return await res.json();
}

async function loadMeta() {
  state.meta = await fetchJson('/api/meta');
  populateNeighborhoods(state.meta.neighborhoods || []);
  renderLoadMessages(state.meta.load_notes || [], state.meta.load_errors || []);
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
  if ([...select.options].some(o => o.value === current)) {
    select.value = current;
  }
  search.value = current !== 'all' ? current : '';
}

async function loadSummary(refresh=false) {
  const params = getFilters();
  if (refresh) params.refresh = '1';
  state.summary = await fetchJson(`/api/summary?${queryString(params)}`);
  renderLoadMessages(state.summary.load_notes || [], state.summary.load_errors || []);
  renderCards();
  renderAnnualChart();
  renderNeighborhoodTable();
  renderAnnualNeighborhoodTable();
  renderDrilldownChart();
  renderSamples();
  renderMapList();
}

function renderLoadMessages(notes, errors) {
  byId('loadNotes').innerHTML = notes.length ? notes.map(n => `<span class="note-pill">${escapeHtml(n)}</span>`).join('') : '';
  byId('loadErrors').innerHTML = errors.length ? errors.map(n => `<div>${escapeHtml(n)}</div>`).join('') : '';
}

function renderCards() {
  const c = state.summary.cards;
  const cards = [
    ['Total permits', c.total_permits],
    ['Seattle', c.seattle_permits],
    ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods],
    ['New SFR', c.new_sfr],
    ['New MF', c.new_mf],
    ['Demo', c.demo],
  ];
  byId('cards').innerHTML = cards.map(([label, value]) => `
    <article class="card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value">${formatNumber(value)}</div>
    </article>
  `).join('');
}

function drawGroupedBars(canvas, labels, series) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth * window.devicePixelRatio;
  const h = canvas.height = canvas.clientHeight * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  ctx.clearRect(0,0,cw,ch);
  const margin = {left: 42, right: 18, top: 16, bottom: 32};
  const plotW = cw - margin.left - margin.right;
  const plotH = ch - margin.top - margin.bottom;
  const maxVal = Math.max(1, ...series.flatMap(s => s.values));

  ctx.strokeStyle = '#d6dee8';
  ctx.fillStyle = '#6b7785';
  ctx.font = '12px Arial';
  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(cw - margin.right, y); ctx.stroke();
    const val = Math.round(maxVal * i / 4);
    ctx.fillText(String(val), 8, y + 4);
  }

  const groupW = plotW / Math.max(1, labels.length);
  const barW = Math.min(22, (groupW - 12) / Math.max(1, series.length));
  const colors = ['#6d8fb3', '#9cb4c9', '#d8a45b'];

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

  let lx = margin.left;
  series.forEach((s, si) => {
    ctx.fillStyle = colors[si % colors.length];
    ctx.fillRect(lx, 2, 12, 12);
    ctx.fillStyle = '#334155';
    ctx.fillText(s.name, lx + 18, 12);
    lx += 88;
  });
}

function renderAnnualChart() {
  const data = state.summary.annual_series;
  const labels = data.map(r => r.year);
  drawGroupedBars(byId('annualChart'), labels, [
    {name: 'New SFR', values: data.map(r => r['New SFR'])},
    {name: 'New MF', values: data.map(r => r['New MF'])},
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
  drawGroupedBars(byId('drilldownChart'), labels, [
    {name: 'New SFR', values: labels.map(y => current.years[y]['New SFR'])},
    {name: 'New MF', values: labels.map(y => current.years[y]['New MF'])},
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
      <td>${formatNumber(r.totals['Demo'])}</td>
    </tr>
  `).join('');
  tbody.querySelectorAll('tr').forEach((tr) => {
    tr.addEventListener('click', async () => {
      state.selectedNeighborhood = tr.dataset.neighborhood;
      byId('neighborhood').value = state.selectedNeighborhood;
      byId('neighborhoodSearch').value = state.selectedNeighborhood;
      await loadSummary(false);
    });
  });
}

function renderAnnualNeighborhoodTable() {
  const rows = state.summary.neighborhood_rows || [];
  const target = state.selectedNeighborhood !== 'all'
    ? rows.filter(r => r.neighborhood === state.selectedNeighborhood)
    : rows.slice(0, 12);
  const years = state.summary.annual_series.map(r => r.year);
  const thead = byId('annualNeighborhoodTable').querySelector('thead');
  const tbody = byId('annualNeighborhoodTable').querySelector('tbody');
  thead.innerHTML = `
    <tr>
      <th>Neighborhood</th>
      ${years.map(y => `<th>${y}</th>`).join('')}
      <th>Total</th>
    </tr>
  `;
  tbody.innerHTML = target.map(r => `
    <tr>
      <td>${escapeHtml(r.neighborhood)}</td>
      ${years.map(y => `<td>${formatNumber(r.years[String(y)].Total)}</td>`).join('')}
      <td>${formatNumber(r.totals.Total)}</td>
    </tr>
  `).join('');
}

function renderSamples() {
  const tbody = byId('sampleTable').querySelector('tbody');
  tbody.innerHTML = (state.summary.samples || []).map(r => `
    <tr>
      <td>${escapeHtml(r.jurisdiction)}</td>
      <td>${escapeHtml(r.category)}</td>
      <td>${escapeHtml(r.neighborhood)}</td>
      <td>${escapeHtml(r.address)}</td>
      <td>${escapeHtml((r.issue_date || r.intake_date || '').slice(0, 10))}</td>
    </tr>
  `).join('');
}

function renderMapList() {
  const wrap = byId('mapList');
  const pts = state.summary.map_points || [];
  wrap.innerHTML = pts.length ? pts.slice(0, 40).map(p => `
    <div class="map-pill">
      <strong>${escapeHtml(p.jurisdiction)}</strong>
      <span>${escapeHtml(p.category)}</span>
      <span>${escapeHtml(p.neighborhood)}</span>
      <span>${escapeHtml(p.address)}</span>
    </div>
  `).join('') : '<div class="muted">No mapped points in this filtered view.</div>';
}

function wireEvents() {
  ['jurisdiction', 'category', 'neighborhood', 'startYear', 'endYear'].forEach((id) => {
    byId(id).addEventListener('change', async () => {
      if (id === 'neighborhood') state.selectedNeighborhood = byId('neighborhood').value;
      await loadSummary(false);
    });
  });
  byId('neighborhoodSearch').addEventListener('input', () => {
    const q = byId('neighborhoodSearch').value.trim().toLowerCase();
    const select = byId('neighborhood');
    const opts = [...select.options];
    const hit = opts.find(o => o.value !== 'all' && o.value.toLowerCase().includes(q));
    if (hit) {
      select.value = hit.value;
      state.selectedNeighborhood = hit.value;
    } else if (!q) {
      select.value = 'all';
      state.selectedNeighborhood = 'all';
    }
  });
  byId('neighborhoodSearch').addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      await loadSummary(false);
    }
  });
  byId('refreshBtn').addEventListener('click', async () => {
    await loadSummary(true);
    await loadMeta();
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  wireEvents();
  try {
    await loadMeta();
    await loadSummary(false);
  } catch (err) {
    byId('loadErrors').textContent = err.message;
  }
  window.addEventListener('resize', () => {
    if (state.summary) {
      renderAnnualChart();
      renderDrilldownChart();
    }
  });
});
