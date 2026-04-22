const state = {
  meta: null,
  summary: null,
  selectedNeighborhood: 'all',
  map: null,
  mapLayer: null,
};

const byId = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[m]));
}

function formatNumber(n) {
  return new Intl.NumberFormat().format(Number(n || 0));
}

function queryString(obj) {
  return new URLSearchParams(obj).toString();
}

async function fetchJson(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function getFilters() {
  const neighborhoodSelect = byId('neighborhood');
  const selectedNeighborhood =
    state.selectedNeighborhood !== 'all' ? state.selectedNeighborhood : (neighborhoodSelect?.value || 'all');

  return {
    jurisdiction: byId('jurisdiction')?.value || 'all',
    category: byId('category')?.value || 'all',
    neighborhood: selectedNeighborhood,
    start_year: byId('startYear')?.value || '2022',
    end_year: byId('endYear')?.value || '2026',
  };
}

function renderLoadMessages(notes, errors) {
  const notesEl = byId('loadNotes');
  const errorsEl = byId('loadErrors');
  if (notesEl) {
    notesEl.innerHTML = (notes || []).map(n => `<span class="note-pill">${escapeHtml(n)}</span>`).join('');
  }
  if (errorsEl) {
    errorsEl.innerHTML = (errors || []).map(e => `<div>${escapeHtml(e)}</div>`).join('');
  }
}

function populateNeighborhoods(items) {
  const select = byId('neighborhood');
  const search = byId('neighborhoodSearch');
  if (!select) return;

  const current = state.selectedNeighborhood === 'all' ? select.value : state.selectedNeighborhood;
  select.innerHTML = '<option value="all">All neighborhoods</option>';

  (items || []).forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n;
    opt.textContent = n;
    select.appendChild(opt);
  });

  const options = [...select.options];
  if (options.some(o => o.value === current)) {
    select.value = current;
  } else {
    select.value = 'all';
    state.selectedNeighborhood = 'all';
  }

  if (search) {
    search.value = state.selectedNeighborhood !== 'all' ? state.selectedNeighborhood : '';
  }
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
  renderMap();
}

function renderCards() {
  const cardsEl = byId('cards');
  if (!cardsEl) return;
  const c = state.summary?.cards || {};
  const cards = [
    ['Total permits', c.total_permits],
    ['Seattle', c.seattle_permits],
    ['Bellevue', c.bellevue_permits],
    ['Known neighborhoods', c.known_neighborhoods],
    ['All New', c.all_new ?? ((c.new_sfr || 0) + (c.new_mf || 0) + (c.other_new || 0))],
    ['New MF', c.new_mf],
    ['Other New', c.other_new],
    ['Demo', c.demo],
  ];

  cardsEl.innerHTML = cards.map(([label, value]) => `
    <article class="card">
      <div class="card-label">${escapeHtml(label)}</div>
      <div class="card-value">${formatNumber(value)}</div>
    </article>
  `).join('');
}

function drawGroupedBars(canvas, labels, series, valueElId) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
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
  const colors = ['#6d8fb3', '#9cb4c9', '#87a9a4', '#d8a45b'];

  const allValues = series.flatMap(s => s.values);
  const maxVal = Math.max(1, ...allValues, 0);

  ctx.strokeStyle = '#d6dee8';
  ctx.fillStyle = '#6b7785';
  ctx.font = '12px Arial';

  for (let i = 0; i <= 4; i++) {
    const y = margin.top + plotH - (plotH * i / 4);
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(width - margin.right, y);
    ctx.stroke();
    ctx.fillText(String(Math.round(maxVal * i / 4)), 8, y + 4);
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
        label, series: s.name, value: val
      });
    });

    ctx.fillStyle = '#334155';
    ctx.fillText(String(label), gx, height - 10);
  });

  canvas.onclick = (evt) => {
    const r = canvas.getBoundingClientRect();
    const x = evt.clientX - r.left;
    const y = evt.clientY - r.top;
    const hit = hitboxes.find(h => x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h);
    const valueEl = byId(valueElId);
    if (!valueEl) return;
    if (hit) {
      valueEl.textContent = `${hit.label} • ${hit.series}: ${formatNumber(hit.value)}`;
    } else {
      valueEl.textContent = 'Click a bar for details.';
    }
  };
}

function renderAnnualChart() {
  const data = state.summary?.annual_series || [];
  drawGroupedBars(
    byId('annualChart'),
    data.map(r => r.year),
    [
      { name: 'New SFR', values: data.map(r => r['New SFR'] || 0) },
      { name: 'New MF', values: data.map(r => r['New MF'] || 0) },
      { name: 'Other New', values: data.map(r => r['Other New'] || 0) },
      { name: 'Demo', values: data.map(r => r['Demo'] || 0) },
    ],
    'annualChartValue'
  );
}

function renderDrilldownChart() {
  const rows = state.summary?.neighborhood_rows || [];
  const current = state.selectedNeighborhood !== 'all'
    ? rows.find(r => r.neighborhood === state.selectedNeighborhood)
    : rows[0];

  const title = byId('drilldownTitle');
  if (title) title.textContent = current ? current.neighborhood : 'No neighborhood selected';

  if (!current) {
    drawGroupedBars(byId('drilldownChart'), [], [], 'drilldownChartValue');
    return;
  }

  const labels = Object.keys(current.years || {});
  drawGroupedBars(
    byId('drilldownChart'),
    labels,
    [
      { name: 'New SFR', values: labels.map(y => current.years[y]['New SFR'] || 0) },
      { name: 'New MF', values: labels.map(y => current.years[y]['New MF'] || 0) },
      { name: 'Other New', values: labels.map(y => current.years[y]['Other New'] || 0) },
      { name: 'Demo', values: labels.map(y => current.years[y]['Demo'] || 0) },
    ],
    'drilldownChartValue'
  );
}

function filteredSamples() {
  const q = (byId('addressSearch')?.value || '').trim().toLowerCase();
  const samples = state.summary?.samples || [];
  if (!q) return samples;
  return samples.filter(r => String(r.address || '').toLowerCase().includes(q));
}

function renderNeighborhoodTable() {
  const table = byId('neighborhoodTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = state.summary?.neighborhood_rows || [];

  tbody.innerHTML = rows.slice(0, 50).map(r => {
    const allNew = (r.totals['New SFR'] || 0) + (r.totals['New MF'] || 0) + (r.totals['Other New'] || 0);
    const selected = r.neighborhood === state.selectedNeighborhood ? 'selected' : '';
    return `
      <tr data-neighborhood="${escapeHtml(r.neighborhood)}" class="${selected}">
        <td>${escapeHtml(r.neighborhood)}</td>
        <td>${formatNumber(r.totals.Total)}</td>
        <td>${formatNumber(allNew)}</td>
        <td>${formatNumber(r.totals['New MF'])}</td>
        <td>${formatNumber(r.totals['Other New'])}</td>
        <td>${formatNumber(r.totals['Demo'])}</td>
      </tr>
    `;
  }).join('');

  tbody.querySelectorAll('tr').forEach((tr) => {
    tr.addEventListener('click', async () => {
      state.selectedNeighborhood = tr.dataset.neighborhood;
      const sel = byId('neighborhood');
      const search = byId('neighborhoodSearch');
      if (sel) sel.value = state.selectedNeighborhood;
      if (search) search.value = state.selectedNeighborhood;
      await loadSummary();
    });
  });
}

function renderAnnualNeighborhoodTable() {
  const table = byId('annualNeighborhoodTable');
  if (!table) return;
  const rows = state.summary?.neighborhood_rows || [];
  const target = state.selectedNeighborhood !== 'all'
    ? rows.filter(r => r.neighborhood === state.selectedNeighborhood)
    : rows.slice(0, 12);
  const years = (state.summary?.annual_series || []).map(r => r.year);

  table.querySelector('thead').innerHTML =
    `<tr><th>Neighborhood</th>${years.map(y => `<th>${y}</th>`).join('')}<th>Total</th></tr>`;

  table.querySelector('tbody').innerHTML = target.map(r => `
    <tr>
      <td>${escapeHtml(r.neighborhood)}</td>
      ${years.map(y => `<td>${formatNumber((r.years[String(y)] || {}).Total || 0)}</td>`).join('')}
      <td>${formatNumber(r.totals.Total)}</td>
    </tr>
  `).join('');
}

function renderSamples() {
  const panel = byId('recentExamplesPanel');
  if (panel) panel.style.display = 'none';
  const table = byId('sampleTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  tbody.innerHTML = filteredSamples().slice(0, 20).map(r => `
    <tr>
      <td>${escapeHtml(r.jurisdiction)}</td>
      <td>${escapeHtml(r.category)}</td>
      <td>${escapeHtml(r.neighborhood)}</td>
      <td>${escapeHtml(r.address)}</td>
      <td>${escapeHtml((r.issue_date || r.intake_date || '').slice(0, 10))}</td>
    </tr>
  `).join('');
}

function initMap() {
  const mapEl = byId('permitMap');
  if (!mapEl || typeof L === 'undefined' || state.map) return;
  state.map = L.map(mapEl).setView([47.6062, -122.3321], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(state.map);
  state.mapLayer = L.layerGroup().addTo(state.map);
}

function renderMap() {
  const mapEl = byId('permitMap');
  if (!mapEl) return;
  initMap();
  if (!state.map || !state.mapLayer) return;

  state.mapLayer.clearLayers();

  const q = (byId('addressSearch')?.value || '').trim().toLowerCase();
  const points = (state.summary?.map_points || []).filter(p => {
    if (!q) return true;
    return String(p.address || '').toLowerCase().includes(q);
  });

  const withCoords = points.filter(p =>
    p.latitude !== undefined && p.latitude !== null &&
    p.longitude !== undefined && p.longitude !== null &&
    !Number.isNaN(Number(p.latitude)) && !Number.isNaN(Number(p.longitude))
  );

  if (!withCoords.length) {
    mapEl.innerHTML = '<div style="padding:20px;color:#6b7785;">No mappable points in this filtered view yet.</div>';
    return;
  }

  mapEl.innerHTML = '';
  state.map.invalidateSize(true);

  const bounds = [];
  withCoords.slice(0, 300).forEach(p => {
    const lat = Number(p.latitude);
    const lng = Number(p.longitude);
    bounds.push([lat, lng]);
    L.circleMarker([lat, lng], {
      radius: 5,
      weight: 1,
      color: '#355070',
      fillColor: '#6d8fb3',
      fillOpacity: 0.85
    }).bindPopup(`
      <strong>${escapeHtml(p.address || 'No address')}</strong><br/>
      ${escapeHtml(p.jurisdiction || '')} • ${escapeHtml(p.category || '')}<br/>
      ${escapeHtml(p.neighborhood || '')}
    `).addTo(state.mapLayer);
  });

  if (bounds.length === 1) {
    state.map.setView(bounds[0], 14);
  } else {
    state.map.fitBounds(bounds, { padding: [20, 20] });
  }
}

function wireEvents() {
  ['jurisdiction', 'category', 'neighborhood', 'startYear', 'endYear'].forEach((id) => {
    const el = byId(id);
    if (!el) return;
    el.addEventListener('change', async () => {
      if (id === 'neighborhood') {
        state.selectedNeighborhood = byId('neighborhood').value;
      }
      await loadSummary();
    });
  });

  const neighborhoodSearch = byId('neighborhoodSearch');
  if (neighborhoodSearch) {
    neighborhoodSearch.addEventListener('input', () => {
      const q = neighborhoodSearch.value.trim().toLowerCase();
      const select = byId('neighborhood');
      if (!select) return;
      const hit = [...select.options].find(o => o.value !== 'all' && o.value.toLowerCase().includes(q));
      if (hit) select.value = hit.value;
    });
    neighborhoodSearch.addEventListener('change', async () => {
      const select = byId('neighborhood');
      if (!select) return;
      state.selectedNeighborhood = select.value;
      await loadSummary();
    });
  }

  const addressSearch = byId('addressSearch');
  if (addressSearch) {
    addressSearch.addEventListener('input', () => {
      renderSamples();
      renderMap();
    });
  }
}

window.addEventListener('DOMContentLoaded', async () => {
  wireEvents();
  try {
    await loadMeta();
    await loadSummary();
  } catch (err) {
    renderLoadMessages([], [err.message || String(err)]);
    console.error(err);
  }
});
