const byId = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat('en-US').format(n || 0);
const fmt1 = (n) => (Number.isFinite(n) ? n.toFixed(1) : '—');
const state = { map: null, layer: null };

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

async function loadMeta(force = false) {
  const res = await fetch(`/api/meta${force ? '?refresh=1' : ''}`);
  if (!res.ok) throw new Error(`Meta failed (${res.status})`);
  const data = await res.json();

  const neighborhood = byId('neighborhood');
  const current = neighborhood.value;
  neighborhood.innerHTML = '<option value="all">All neighborhoods</option>';
  (data.neighborhoods || []).forEach((n) => {
    const opt = document.createElement('option');
    opt.value = n;
    opt.textContent = n;
    neighborhood.appendChild(opt);
  });
  if ([...neighborhood.options].some((o) => o.value === current)) {
    neighborhood.value = current;
  }
}

async function loadRows(force = false) {
  const params = currentFilters();
  if (force) params.refresh = '1';
  const res = await fetch(`/api/permits?${qs(params)}`);
  if (!res.ok) throw new Error(`API failed (${res.status})`);
  const data = await res.json();
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

  byId('rowCount').textContent = `${fmt(data.total_row_count || 0)} permits in current view`;
  byId('sourceBadge').textContent = (data.errors || []).length ? 'Partial live load' : 'Live service';

  renderTrend(summary.annual_trend || [], byId('trendChart'));
  renderCategoryBars(categories, summary.count || 0);
  renderNeighborhoodTable(summary.top_neighborhoods || []);
  renderNeighborhoodAnnual(summary.neighborhood_breakdown || []);
  renderNeighborhoodDrilldown(summary.selected_neighborhood || 'Unknown', summary.selected_neighborhood_annual || []);
  renderTable(rows);
  renderMap(rows);
}

function renderTrend(series, container) {
  if (!series.length) {
    container.innerHTML = '<div class="empty-note">No annual trend available for the current view.</div>';
    return;
  }
  const max = Math.max(...series.map((d) => d.count), 1);
  container.innerHTML = `
    <div class="trend-grid">
      ${series.map((d) => `
          <div class="trend-col">
            <div class="trend-value">${fmt(d.count)}</div>
            <div class="trend-stack">
              <div class="trend-segment demo" style="height:${max ? ((d.categories?.Demo || 0) / max) * 180 : 0}px"></div>
              <div class="trend-segment mf" style="height:${max ? ((d.categories?.['New MF'] || 0) / max) * 180 : 0}px"></div>
              <div class="trend-segment sf" style="height:${max ? ((d.categories?.['New SFR'] || 0) / max) * 180 : 0}px"></div>
            </div>
            <div class="trend-year">${d.year}</div>
          </div>`).join('')}
    </div>`;
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

function hookNeighborhoodClicks(rootId) {
  byId(rootId).querySelectorAll('[data-neighborhood]').forEach((el) => {
    el.addEventListener('click', (e) => {
      const hood = e.currentTarget.getAttribute('data-neighborhood');
      byId('neighborhood').value = hood;
      loadRows(false).catch(showError);
    });
  });
}

function renderNeighborhoodTable(rows) {
  byId('hoodTable').innerHTML = rows.length
    ? rows.slice(0, 12).map(([name, count]) => `<tr class="clickable-row" data-neighborhood="${escapeHtml(name)}"><td><button class="linkish" data-neighborhood="${escapeHtml(name)}">${name}</button></td><td>${fmt(count)}</td></tr>`).join('')
    : '<tr><td colspan="2">No neighborhoods in current view.</td></tr>';
  hookNeighborhoodClicks('hoodTable');
}

function renderNeighborhoodAnnual(rows) {
  byId('hoodAnnualTable').innerHTML = rows.length
    ? rows.map((row) => {
      const annual = Object.fromEntries((row.annual || []).map((x) => [x.year, x.count]));
      return `
        <tr class="clickable-row" data-neighborhood="${escapeHtml(row.name)}">
          <td><button class="linkish" data-neighborhood="${escapeHtml(row.name)}">${row.name}</button></td>
          <td>${fmt(annual[2022] || 0)}</td>
          <td>${fmt(annual[2023] || 0)}</td>
          <td>${fmt(annual[2024] || 0)}</td>
          <td>${fmt(annual[2025] || 0)}</td>
          <td>${fmt(annual[2026] || 0)}</td>
          <td><strong>${fmt(row.count || 0)}</strong></td>
        </tr>`;
    }).join('')
    : '<tr><td colspan="7">No neighborhood breakdown available.</td></tr>';
  hookNeighborhoodClicks('hoodAnnualTable');
}

function renderNeighborhoodDrilldown(name, annual) {
  byId('selectedHoodLabel').textContent = name && name !== 'Unknown' ? `${name} · annual trend` : 'Top neighborhood in current view';
  const container = byId('hoodDrilldownChart');
  if (!annual.length) {
    container.innerHTML = '<div class="empty-note">Select a neighborhood to see its annual trend.</div>';
    return;
  }
  const max = Math.max(...annual.map((d) => d.count), 1);
  container.innerHTML = `
    <div class="trend-grid small-grid">
      ${annual.map((d) => `
        <div class="trend-col">
          <div class="trend-value">${fmt(d.count)}</div>
          <div class="trend-stack single-series">
            <div class="trend-segment primary" style="height:${Math.max((d.count / max) * 150, d.count > 0 ? 10 : 2)}px"></div>
          </div>
          <div class="trend-year">${d.year}</div>
        </div>`).join('')}
    </div>`;
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
  const mapped = rows.filter((r) => Number.isFinite(r.latitude) && Number.isFinite(r.longitude)).slice(0, 50);
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
  byId('mapMeta').textContent = `${fmt(mapped.length)} mapped sample points`;
  if (mapped.length) {
    const bounds = L.latLngBounds(mapped.map((r) => [r.latitude, r.longitude]));
    state.map.fitBounds(bounds.pad(0.14));
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function showError(err) {
  alert(err?.message || String(err));
}

function wire() {
  ['jurisdiction', 'category', 'dateMode', 'neighborhood', 'startYear', 'endYear'].forEach((id) => {
    byId(id).addEventListener('change', () => loadRows(false).catch(showError));
  });
  byId('search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadRows(false).catch(showError);
  });
  byId('refreshBtn').addEventListener('click', async () => {
    try {
      await loadMeta(true);
      await loadRows(true);
    } catch (err) {
      showError(err);
    }
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  initMap();
  wire();
  try {
    await loadMeta(false);
    await loadRows(false);
  } catch (err) {
    showError(err);
  }
});
