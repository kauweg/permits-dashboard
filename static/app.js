const byId = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat('en-US').format(n || 0);
const fmt1 = (n) => (Number.isFinite(n) ? n.toFixed(1) : '—');
const state = { map: null, layer: null, rows: [] };

function categoryClass(name) {
  if (name === 'New SFR') return 'sf';
  if (name === 'New MF') return 'mf';
  return 'demo';
}

function badge(category) {
  const klass = categoryClass(category);
  return `<span class="badge ${klass}">${category}</span>`;
}

function initMap() {
  state.map = L.map('map').setView([47.611, -122.21], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19,
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
}

function currentFilters() {
  return {
    jurisdiction: byId('jurisdiction').value,
    category: byId('category').value,
    date_mode: byId('dateMode').value,
    neighborhood: byId('neighborhood').value,
    start_year: byId('startYear').value,
    end_year: byId('endYear').value,
    q: byId('search').value.trim(),
  };
}

function qs(params) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, v);
  });
  return sp.toString();
}

async function loadRows(force = false) {
  const params = currentFilters();
  if (force) params.refresh = '1';
  const res = await fetch(`/api/permits?${qs(params)}`);
  if (!res.ok) throw new Error(`API failed (${res.status})`);
  const data = await res.json();
  state.rows = data.rows || [];
  render(data);
}

function render(data) {
  const rows = data.rows || [];
  const summary = data.summary || {};
  byId('kpiCount').textContent = fmt(summary.count || 0);
  byId('kpiWindow').textContent = `${byId('startYear').value}–${byId('endYear').value} · ${byId('jurisdiction').value === 'all' ? 'Both jurisdictions' : byId('jurisdiction').value}`;
  byId('kpiLag').textContent = Number.isFinite(summary.avg_lag_days) ? fmt1(summary.avg_lag_days) : '—';

  const categories = summary.category_counts || {};
  const topCategory = Object.entries(categories).sort((a, b) => b[1] - a[1])[0];
  byId('kpiMix').textContent = topCategory ? topCategory[0] : '—';
  byId('kpiMixSub').textContent = topCategory ? `${fmt(topCategory[1])} permits` : 'No permits in view';

  const topHood = (summary.top_neighborhoods || [])[0];
  byId('kpiHood').textContent = topHood ? topHood[0] : '—';
  byId('kpiHoodSub').textContent = topHood ? `${fmt(topHood[1])} permits` : 'No neighborhood signal';

  byId('rowCount').textContent = `${fmt(rows.length)} shown`;
  byId('sourceBadge').textContent = (data.errors || []).length ? 'Partial live load' : 'Live service';

  renderCategoryBars(categories, summary.count || 0);
  renderNeighborhoodTable(summary.top_neighborhoods || []);
  renderTable(rows);
  renderMap(rows);
}

function renderCategoryBars(categories, total) {
  const ordered = ['New SFR', 'New MF', 'Demo'];
  byId('categoryBars').innerHTML = ordered.map((name) => {
    const count = categories[name] || 0;
    const pct = total ? (count / total) * 100 : 0;
    const klass = categoryClass(name);
    return `
      <div class="bar-row ${klass}">
        <div>${name}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <div>${fmt(count)}</div>
      </div>`;
  }).join('');
}

function renderNeighborhoodTable(rows) {
  byId('hoodTable').innerHTML = rows.length
    ? rows.slice(0, 12).map(([name, count]) => `<tr><td>${name}</td><td>${fmt(count)}</td></tr>`).join('')
    : '<tr><td colspan="2">No neighborhoods in current view.</td></tr>';
}

function renderTable(rows) {
  byId('permitTable').innerHTML = rows.length ? rows.map((r) => `
    <tr>
      <td>${r.jurisdiction}</td>
      <td>${r.neighborhood || 'Unknown'}</td>
      <td>${badge(r.category)}</td>
      <td>${r.permit_id || '—'}</td>
      <td>${r.address || '—'}</td>
      <td>${r.permit_type || r.description || '—'}</td>
      <td>${r.status || '—'}</td>
      <td>${r.intake_date || '—'}</td>
      <td>${r.issue_date || '—'}</td>
    </tr>
  `).join('') : '<tr><td colspan="9">No permits found.</td></tr>';
}

function renderMap(rows) {
  state.layer.clearLayers();
  const mapped = rows.filter((r) => Number.isFinite(r.latitude) && Number.isFinite(r.longitude)).slice(0, 900);
  mapped.forEach((r) => {
    const color = r.jurisdiction === 'Seattle' ? '#316fdd' : '#0f766e';
    const fill = r.jurisdiction === 'Seattle' ? '#93c5fd' : '#5eead4';
    const marker = L.circleMarker([r.latitude, r.longitude], {
      radius: 5,
      color,
      fillColor: fill,
      fillOpacity: 0.85,
      weight: 1,
    }).bindPopup(`<strong>${r.jurisdiction}</strong><br>${r.neighborhood || 'Unknown'}<br>${r.permit_id || 'No permit #'}<br>${r.address || 'No address'}<br>${r.category}`);
    marker.addTo(state.layer);
  });

  byId('mapMeta').textContent = `${fmt(mapped.length)} mapped permits`;
  if (mapped.length) {
    const bounds = L.latLngBounds(mapped.map((r) => [r.latitude, r.longitude]));
    state.map.fitBounds(bounds.pad(0.14));
  }
}

function wire() {
  ['jurisdiction', 'category', 'dateMode', 'neighborhood', 'startYear', 'endYear'].forEach((id) => {
    byId(id).addEventListener('change', () => loadRows(false).catch(showError));
  });
  byId('search').addEventListener('input', debounce(() => loadRows(false).catch(showError), 250));
  byId('refreshBtn').addEventListener('click', () => loadRows(true).catch(showError));
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function showError(err) {
  console.error(err);
  byId('sourceBadge').textContent = err.message || 'Load failed';
}

window.addEventListener('DOMContentLoaded', () => {
  initMap();
  wire();
  loadRows(false).catch(showError);
});
