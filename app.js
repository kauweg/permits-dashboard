/* ═══════════════════════════════════════════════════════════
   PNW Construction Permit Dashboard
   ═══════════════════════════════════════════════════════════ */
'use strict';

/* ── Config ──────────────────────────────────────────────── */
const SEATTLE_BASE = 'https://data.seattle.gov/resource/76t5-zqzr.json';

// Bellevue: ArcGIS Online hosted feature service (COBGIS org)
// Dataset ID confirmed from data.bellevuewa.gov/datasets/cobgis::bellevue-permits
const BELLEVUE_BASE = 'https://services8.arcgis.com/rGGrs6HCnw29OGFW/arcgis/rest/services/Bellevue_Permits/FeatureServer/0/query';

const YEARS = [2021,2022,2023,2024,2025,2026];

const COLORS = { sfr:'#2563eb', mf:'#dc2626', demo:'#d97706', other:'#7c3aed' };
const LABELS = { sfr:'Single family', mf:'Multifamily', demo:'Demolition', other:'Other' };

const SEA_HOODS = [
  'Capitol Hill','Ballard','Fremont','Wallingford','Queen Anne','Magnolia','Belltown',
  'South Lake Union','Eastlake','Montlake','Madrona','Madison Park','Leschi','Beacon Hill',
  'Columbia City','Georgetown','SoDo','West Seattle','Delridge','Northgate','Greenwood',
  'Phinney Ridge','Roosevelt','Ravenna','Wedgwood','Maple Leaf','Lake City','Laurelhurst',
  'Sand Point','View Ridge','South Park','Rainier Beach','First Hill','Central District',
  'International District','Pioneer Square','Lower Queen Anne','Interbay','Bitter Lake',
  'Crown Hill','Licton Springs','Mount Baker','Seward Park','Judkins Park','Yesler Terrace'
];

/* ── State ───────────────────────────────────────────────── */
let ALL = [], FILTERED = [], currentCity = 'seattle';
let page = 0; const PER = 50;
let diagHtml = '', diagOpen = false;
let mapL = null, markers = null, trendC = null, typeC = null;

/* ── Boot ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => { initMap(); loadData(); });

/* ═══════════════════════════════════════════════════════════
   FETCH — Seattle (Socrata SODA)
   KEY FIX: build URL manually — URLSearchParams encodes single
   quotes as %27 which breaks Socrata SoQL string comparisons.
   ═══════════════════════════════════════════════════════════ */
async function fetchSeattle() {
  const rows = [];
  let offset = 0;

  // NOTE: use separate queries for Construction vs Demolition
  // to avoid the IN() operator which can cause issues
  for (const ptype of ['Construction', 'Demolition']) {
    offset = 0;
    do {
      // Build query string manually to preserve single quotes
      const where = `permittype='${ptype}' AND permitclass='Residential' AND issueddate>='2021-01-01T00:00:00' AND latitude IS NOT NULL`;
      const select = 'permitnum,issueddate,permittype,permitclassmapped,description,latitude,longitude,statuscurrent';

      const url = SEATTLE_BASE
        + '?$limit=50000'
        + '&$offset=' + offset
        + '&$order=issueddate+DESC'
        + '&$select=' + encodeURIComponent(select)
        + '&$where=' + encodeURIComponent(where).replace(/%27/g, "'");

      log('<span class="url">GET ' + url.slice(0,100) + '…</span>');
      setStatus('Seattle: fetching ' + ptype + ' permits (offset ' + offset + ')…');

      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error('Seattle ' + ptype + ' HTTP ' + res.status + ': ' + body.slice(0,120));
      }
      const batch = await res.json();
      if (!Array.isArray(batch)) throw new Error('Seattle: non-array response: ' + JSON.stringify(batch).slice(0,80));

      batch.forEach(r => rows.push(normalizeSeattle(r)));
      offset += 50000;
      if (batch.length < 50000) break;
    } while (true);
  }

  log('<span class="ok">✓ Seattle: ' + rows.length.toLocaleString() + ' records loaded</span>');
  return rows;
}

function normalizeSeattle(r) {
  const cls  = (r.permitclassmapped || '').toLowerCase();
  const typ  = (r.permittype || '').toLowerCase();
  const desc = (r.description || '').toLowerCase();
  let cat = 'other';
  if (typ === 'demolition') cat = 'demo';
  else if (cls.includes('single') || cls.includes('duplex') || desc.includes('single family') || desc.includes(' sfr')) cat = 'sfr';
  else if (cls.includes('multi') || desc.includes('multifamily') || desc.includes('apartment') || desc.includes('townhouse') || desc.includes('condo')) cat = 'mf';
  const date = r.issueddate ? new Date(r.issueddate) : null;
  return {
    id: r.permitnum || '', city: 'Seattle', date,
    year: date ? date.getFullYear() : null,
    month: date ? date.getMonth() : null,
    cat, desc: (r.description || '').slice(0, 130),
    address: '', hood: guessHood(r.description || ''),
    lat: parseFloat(r.latitude), lon: parseFloat(r.longitude),
    status: r.statuscurrent || ''
  };
}

function guessHood(desc) {
  const d = desc.toLowerCase();
  for (const h of SEA_HOODS) { if (d.includes(h.toLowerCase())) return h; }
  return 'Seattle';
}

/* ═══════════════════════════════════════════════════════════
   FETCH — Bellevue (ArcGIS Feature Service)
   Tries multiple known endpoint patterns with graceful fallback
   ═══════════════════════════════════════════════════════════ */
async function fetchBellevue() {
  // Multiple endpoint candidates — Bellevue's ArcGIS org uses cobgis
  const candidates = [
    BELLEVUE_BASE,
    'https://cobgis.maps.arcgis.com/sharing/rest/content/items/bellevue-permits/FeatureServer/0/query',
    'https://gis-web.bellevuewa.gov/gisext/rest/services/DS/BellevuePermits/FeatureServer/0/query',
    'https://gis-web.bellevuewa.gov/gisext/rest/services/DS/Permits/FeatureServer/0/query',
  ];

  for (const base of candidates) {
    try {
      const rows = await tryBellevueEndpoint(base);
      if (rows.length > 0) return rows;
    } catch (e) {
      log('<span class="err">Bellevue endpoint failed (' + base.slice(0,60) + '…): ' + e.message + '</span>');
    }
  }

  // All endpoints failed — return empty and explain
  log('<span class="err">⚠ Bellevue: all endpoints failed. Seattle data still loaded. To fix Bellevue, visit data.bellevuewa.gov/datasets/bellevue-permits and copy the API URL into BELLEVUE_BASE in app.js</span>');
  return [];
}

async function tryBellevueEndpoint(base) {
  const params = new URLSearchParams({
    where: "IssueDate >= '2021-01-01' AND IssueDate IS NOT NULL",
    outFields: 'PermitNumber,IssueDate,PermitTypeCode,PermitTypeDesc,WorkDesc,SiteAddress,Neighborhood,Latitude,Longitude,StatusDesc',
    returnGeometry: 'false',
    resultRecordCount: '2000',
    orderByFields: 'IssueDate DESC',
    f: 'json'
  });
  const url = base + '?' + params;
  log('<span class="url">GET ' + url.slice(0,100) + '…</span>');
  setStatus('Bellevue: fetching permits…');

  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const json = await res.json();
  if (json.error) throw new Error(json.error.message || JSON.stringify(json.error).slice(0,80));
  if (!json.features) throw new Error('No features array in response');

  const rows = json.features.map(f => normalizeBellevue(f.attributes || f));
  log('<span class="ok">✓ Bellevue: ' + rows.length.toLocaleString() + ' records from ' + base.slice(0,50) + '</span>');
  return rows;
}

function normalizeBellevue(a) {
  const code = (a.PermitTypeCode || '').toUpperCase();
  let cat = 'other';
  if (['BT','BD'].includes(code)) cat = 'demo';
  else if (['BS'].includes(code)) cat = 'sfr';
  else if (['BB','BH','BM'].includes(code)) cat = 'mf';
  const raw = a.IssueDate;
  const date = raw ? new Date(typeof raw === 'number' ? raw : raw) : null;
  return {
    id: a.PermitNumber || '', city: 'Bellevue', date,
    year: date ? date.getFullYear() : null,
    month: date ? date.getMonth() : null,
    cat, desc: (a.WorkDesc || a.PermitTypeDesc || '').slice(0,130),
    address: a.SiteAddress || '', hood: a.Neighborhood || 'Bellevue',
    lat: parseFloat(a.Latitude), lon: parseFloat(a.Longitude),
    status: a.StatusDesc || ''
  };
}

/* ═══════════════════════════════════════════════════════════
   LOAD ORCHESTRATOR
   ═══════════════════════════════════════════════════════════ */
async function loadData() {
  pulse('fetching'); setStatus('Fetching live permit data…');
  diagHtml = ''; document.getElementById('status-diag').innerHTML = '';
  ALL = [];

  const cities = currentCity === 'both' ? ['seattle','bellevue'] : [currentCity];
  const results = await Promise.allSettled(cities.map(c => c === 'seattle' ? fetchSeattle() : fetchBellevue()));

  results.forEach((r, i) => {
    if (r.status === 'fulfilled') ALL = ALL.concat(r.value);
    else log('<span class="err">✗ ' + cities[i] + ': ' + r.reason.message + '</span>');
  });

  if (!ALL.length) {
    pulse('error');
    setStatus('✗ No data loaded — click "Show details" to see why', 'err');
    showDiagBtn();
    return;
  }

  const ts = new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  pulse('live');
  setStatus('✓ ' + ALL.length.toLocaleString() + ' permits loaded · ' + ts, 'ok');
  populateHoodFilter();
  applyFilters();
}

/* ═══════════════════════════════════════════════════════════
   FILTER
   ═══════════════════════════════════════════════════════════ */
function applyFilters() {
  const q     = (document.getElementById('search-input').value || '').toLowerCase().trim();
  const fCat  = document.getElementById('filter-type').value;
  const fHood = document.getElementById('filter-neighborhood').value;
  const fYear = document.getElementById('filter-year').value;

  FILTERED = ALL.filter(p => {
    if (!isFinite(p.lat) || !isFinite(p.lon) || p.lat === 0) return false;
    if (fCat  !== 'all' && p.cat  !== fCat)        return false;
    if (fHood !== 'all' && p.hood !== fHood)        return false;
    if (fYear !== 'all' && String(p.year) !== fYear) return false;
    if (q) {
      const hay = [p.address, p.desc, p.hood, p.id, p.city].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  document.getElementById('result-count').textContent = FILTERED.length.toLocaleString() + ' permits';
  page = 0;
  renderAll();
}

function populateHoodFilter() {
  const hoods = [...new Set(ALL.map(p => p.hood).filter(Boolean))].sort();
  const sel = document.getElementById('filter-neighborhood');
  sel.innerHTML = '<option value="all">All neighborhoods</option>';
  hoods.forEach(h => { const o = document.createElement('option'); o.value = o.textContent = h; sel.appendChild(o); });
}

/* ═══════════════════════════════════════════════════════════
   RENDER
   ═══════════════════════════════════════════════════════════ */
function renderAll() {
  renderKPIs();
  renderTrend();
  renderHoods();
  renderTypeMix();
  renderInsights();
  renderMap();
  renderTable();
}

/* KPIs */
function renderKPIs() {
  const n = FILTERED.length;
  const sfr  = FILTERED.filter(p => p.cat === 'sfr').length;
  const mf   = FILTERED.filter(p => p.cat === 'mf').length;
  const demo = FILTERED.filter(p => p.cat === 'demo').length;

  const cy = new Date().getFullYear();
  const cur   = FILTERED.filter(p => p.year === cy).length;
  const prior = FILTERED.filter(p => p.year === cy - 1).length;
  let yoyVal = '—', yoyCls = '', yoySub = '';
  if (prior > 0) {
    const pct = Math.round((cur - prior) / prior * 100);
    yoyVal = (pct >= 0 ? '+' : '') + pct + '%';
    yoyCls = pct >= 0 ? 'green' : 'rose';
    yoySub = cy + ' vs ' + (cy - 1);
  }

  const nc = {}; FILTERED.forEach(p => { if (p.hood) nc[p.hood] = (nc[p.hood] || 0) + 1; });
  const hot = Object.entries(nc).sort((a,b) => b[1]-a[1])[0];

  kpi('k-total', n.toLocaleString(), '', '2021–2026');
  kpi('k-sfr',   sfr.toLocaleString(), 'blue', n ? Math.round(sfr/n*100)+'% of total' : '');
  kpi('k-mf',    mf.toLocaleString(),  'red',  n ? Math.round(mf/n*100)+'% of total'  : '');
  kpi('k-demo',  demo.toLocaleString(),'amber', n ? Math.round(demo/n*100)+'% of total' : '');
  kpi('k-yoy',   yoyVal, yoyCls, yoySub);
  kpi('k-hot',   hot ? hot[0].split(' ').slice(0,2).join(' ') : '—', 'teal', hot ? hot[1].toLocaleString() + ' permits' : '');
}
function kpi(id, val, cls, sub) {
  const el = document.getElementById(id);
  el.className = 'kpi-value' + (cls ? ' ' + cls : '');
  el.textContent = val;
  const s = el.nextElementSibling?.nextElementSibling;
  if (s) s.textContent = sub || '';
}

/* Trend line chart */
function renderTrend() {
  const by = {}; YEARS.forEach(y => by[y] = {sfr:0,mf:0,demo:0});
  FILTERED.forEach(p => { if (p.year && by[p.year]) by[p.year][p.cat]++; });

  const sets = [
    { label:'Single family', data: YEARS.map(y=>by[y].sfr),  borderColor:'#2563eb', backgroundColor:'rgba(37,99,235,0.07)', tension:.4, fill:true, pointRadius:3, pointHoverRadius:5 },
    { label:'Multifamily',   data: YEARS.map(y=>by[y].mf),   borderColor:'#dc2626', backgroundColor:'rgba(220,38,38,0.07)',  tension:.4, fill:true, pointRadius:3, pointHoverRadius:5 },
    { label:'Demolition',    data: YEARS.map(y=>by[y].demo),  borderColor:'#d97706', backgroundColor:'rgba(217,119,6,0.07)', tension:.4, fill:true, pointRadius:3, pointHoverRadius:5 },
  ];

  document.getElementById('trend-legend').innerHTML = sets.map(s =>
    `<div class="leg"><div class="leg-dot" style="background:${s.borderColor}"></div>${s.label}</div>`
  ).join('');

  if (trendC) trendC.destroy();
  trendC = new Chart(document.getElementById('trend-chart'), {
    type: 'line', data: { labels: YEARS.map(String), datasets: sets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode:'index', intersect:false },
      plugins: { legend: { display:false }, tooltip: { backgroundColor:'#fff', borderColor:'#e5e7eb', borderWidth:1, titleColor:'#111827', bodyColor:'#6b7280', padding:10, boxShadow:'0 4px 6px rgba(0,0,0,.05)' }},
      scales: {
        x: { grid:{ color:'#f3f4f6' }, ticks:{ color:'#9ca3af', font:{ family:'IBM Plex Mono', size:10 }}},
        y: { grid:{ color:'#f3f4f6' }, ticks:{ color:'#9ca3af', font:{ family:'IBM Plex Mono', size:10 }}, beginAtZero:true }
      }
    }
  });
}

/* Neighborhood bars */
function renderHoods() {
  const cnt = {}; FILTERED.forEach(p => { if (p.hood) cnt[p.hood] = (cnt[p.hood]||0)+1; });
  const sorted = Object.entries(cnt).sort((a,b) => b[1]-a[1]).slice(0,22);
  const maxV = sorted[0]?.[1] || 1;
  const fYear = document.getElementById('filter-year').value;
  document.getElementById('nbhd-meta').textContent = fYear === 'all' ? 'all years · click to filter' : fYear + ' · click to filter';
  document.getElementById('nbhd-bars').innerHTML = sorted.map(([h, n]) =>
    `<div class="nbhd-row" onclick="filterHood('${h.replace(/'/g,"\\'")}')">
      <span class="nbhd-name" title="${h}">${h}</span>
      <div class="nbhd-track">
        <div class="nbhd-fill" style="width:${(n/maxV*100).toFixed(1)}%;background:${n===maxV?'#2563eb':'#bfdbfe'}"></div>
      </div>
      <span class="nbhd-num">${n}</span>
    </div>`
  ).join('') || '<div style="padding:8px 0;color:#9ca3af;font-size:12px">No data for current filters</div>';
}
window.filterHood = h => { document.getElementById('filter-neighborhood').value = h; applyFilters(); };

/* Type mix stacked bar */
function renderTypeMix() {
  const by = {}; YEARS.forEach(y => by[y] = {sfr:0,mf:0,demo:0});
  FILTERED.forEach(p => { if (p.year && by[p.year]) by[p.year][p.cat]++; });
  if (typeC) typeC.destroy();
  typeC = new Chart(document.getElementById('type-chart'), {
    type: 'bar',
    data: { labels: YEARS.map(String), datasets: [
      { label:'Single family', data: YEARS.map(y=>by[y].sfr),  backgroundColor:'rgba(37,99,235,0.8)',  borderRadius:2 },
      { label:'Multifamily',   data: YEARS.map(y=>by[y].mf),   backgroundColor:'rgba(220,38,38,0.8)',  borderRadius:2 },
      { label:'Demolition',    data: YEARS.map(y=>by[y].demo),  backgroundColor:'rgba(217,119,6,0.8)', borderRadius:2 },
    ]},
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:false }, tooltip:{ backgroundColor:'#fff', borderColor:'#e5e7eb', borderWidth:1, titleColor:'#111827', bodyColor:'#6b7280', padding:10 }},
      scales:{
        x:{ stacked:true, grid:{color:'#f3f4f6'}, ticks:{color:'#9ca3af',font:{family:'IBM Plex Mono',size:10}} },
        y:{ stacked:true, grid:{color:'#f3f4f6'}, ticks:{color:'#9ca3af',font:{family:'IBM Plex Mono',size:10}}, beginAtZero:true }
      }
    }
  });
}

/* Insights */
function renderInsights() {
  const insights = [];
  const cy = new Date().getFullYear();
  const by = {}; YEARS.forEach(y => by[y] = {sfr:0,mf:0,demo:0,total:0});
  FILTERED.forEach(p => { if (p.year && by[p.year]) { by[p.year][p.cat]++; by[p.year].total++; }});

  if (by[cy-1].mf > 0) {
    const pct = Math.round((by[cy].mf - by[cy-1].mf) / by[cy-1].mf * 100);
    insights.push({ icon:'🏢', bg:'#eff6ff',
      text:`Multifamily pipeline is <strong class="${pct>=0?'up':'dn'}">${pct>=0?'+':''}${pct}%</strong> vs last year (${by[cy].mf} vs ${by[cy-1].mf} permits). ${pct>15?'Strong high-density demand.':pct<-10?'Cooling — monitor supply.':'Stable MF pipeline.'}` });
  }

  const d3 = YEARS.slice(-3).reduce((s,y)=>s+(by[y]?.demo||0),0);
  const n3 = YEARS.slice(-3).reduce((s,y)=>s+(by[y]?.sfr||0)+(by[y]?.mf||0),0);
  if (d3 > 0) {
    const ratio = (n3/d3).toFixed(1);
    insights.push({ icon:'🔄', bg:'#f5f3ff',
      text:`Demo-to-new-build ratio: <strong>${ratio}x</strong> over 3 years. ${ratio>1.5?'Net housing being added — healthy.':ratio<0.9?'Demos outpacing builds — watch supply.':'Near 1:1 replacement.'}` });
  }

  const nc = {}, ncMF = {};
  FILTERED.filter(p => p.year >= cy-1).forEach(p => {
    if (!p.hood) return;
    nc[p.hood] = (nc[p.hood]||0)+1;
    if (p.cat === 'mf') ncMF[p.hood] = (ncMF[p.hood]||0)+1;
  });
  const hot = Object.entries(nc).sort((a,b)=>b[1]-a[1])[0];
  if (hot) {
    const mfpct = Math.round((ncMF[hot[0]]||0)/hot[1]*100);
    insights.push({ icon:'📍', bg:'#eff6ff',
      text:`<strong>${hot[0]}</strong> leads with <strong>${hot[1]}</strong> permits in the last 2 years (${mfpct}% multifamily). Priority land acquisition zone.` });
  }

  if (by[cy-1].sfr > 0) {
    const pct = Math.round((by[cy].sfr - by[cy-1].sfr) / by[cy-1].sfr * 100);
    insights.push({ icon:'🏠', bg:'#fffbeb',
      text:`Single-family construction <strong class="${pct>=0?'up':'dn'}">${pct>=0?'+':''}${pct}%</strong> YoY. ${Math.abs(pct)<5?'SFR market stable.':pct>15?'SFR expansion — likely ADU/middle-housing policy driven.':'Monitor for continued trend.'}` });
  }

  const last90 = FILTERED.filter(p => p.date && Date.now()-p.date.getTime() < 90*864e5);
  if (last90.length > 5) {
    const ann = Math.round(last90.length*(365/90));
    insights.push({ icon:'📈', bg:'#f0fdf4',
      text:`Last 90 days: <strong>${last90.length}</strong> permits → annualizes to <strong>~${ann.toLocaleString()}</strong>. ${ann>(by[cy-1].total||0)*1.1?'Above prior-year run rate — pipeline accelerating.':'In line with historical pace.'}` });
  }

  if (currentCity === 'both') {
    const bv = FILTERED.filter(p=>p.city==='Bellevue').length;
    const se = FILTERED.filter(p=>p.city==='Seattle').length;
    if (bv > 0) insights.push({ icon:'🌆', bg:'#f0fdf4',
      text:`Bellevue: <strong>${bv.toLocaleString()}</strong> vs Seattle: <strong>${se.toLocaleString()}</strong>. Bellevue's smaller footprint = higher per-capita density of new construction — strong Eastside signal.` });
  }

  document.getElementById('insights-list').innerHTML = insights.slice(0,5).map(i =>
    `<div class="insight-item">
      <div class="insight-icon" style="background:${i.bg}">${i.icon}</div>
      <div class="insight-text">${i.text}</div>
    </div>`
  ).join('') || '<div style="padding:12px 16px;font-size:12px;color:#9ca3af">Load data to see insights.</div>';
}

/* ═══════════════════════════════════════════════════════════
   MAP
   ═══════════════════════════════════════════════════════════ */
function initMap() {
  mapL = L.map('map', { zoomControl:true }).setView([47.57,-122.25], 11);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution:'© OpenStreetMap © CARTO', maxZoom:19
  }).addTo(mapL);
  markers = L.layerGroup().addTo(mapL);
}

function renderMap() {
  markers.clearLayers();
  const pts = FILTERED.filter(p => isFinite(p.lat)&&isFinite(p.lon)&&Math.abs(p.lat)>10);
  const sample = pts.length > 5000 ? pts.slice(0,5000) : pts;

  document.getElementById('map-badge').innerHTML =
    '<strong>' + pts.length.toLocaleString() + '</strong> permits' +
    (pts.length > 5000 ? ' <span style="color:#9ca3af">(5k shown)</span>' : '');

  sample.forEach(p => {
    const c = COLORS[p.cat] || '#6b7280';
    L.circleMarker([p.lat,p.lon], {
      radius:4, fillColor:c, color:'rgba(255,255,255,0.7)', weight:1, fillOpacity:0.85
    }).bindPopup(
      '<b style="color:' + c + '">' + (LABELS[p.cat]||p.cat) + '</b> · ' + p.city + '<br>' +
      (p.date ? p.date.toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'}) + '<br>' : '') +
      (p.address ? p.address + '<br>' : '') +
      (p.hood ? '<span style="color:#6b7280">' + p.hood + '</span><br>' : '') +
      '<span style="color:#9ca3af;font-size:10px">' + p.desc.slice(0,80) + '</span>'
    ).addTo(markers);
  });

  if (pts.length > 0) {
    try { mapL.fitBounds(L.latLngBounds(sample.map(p=>[p.lat,p.lon])),{padding:[28,28],maxZoom:13}); }
    catch(e) {}
  }

  const fType = document.getElementById('filter-type').value;
  const fYear = document.getElementById('filter-year').value;
  document.getElementById('map-label').textContent = [
    currentCity==='both'?'Seattle & Bellevue':(currentCity.charAt(0).toUpperCase()+currentCity.slice(1)),
    fType!=='all' ? LABELS[fType] : 'All types',
    fYear!=='all' ? fYear : '2021–2026'
  ].join(' · ');

  setTimeout(() => mapL.invalidateSize(), 100);
}

window.setMapMode = mode => {
  document.querySelectorAll('.map-type-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('btn-'+mode).classList.add('active');
  renderMap();
};

/* ═══════════════════════════════════════════════════════════
   TABLE
   ═══════════════════════════════════════════════════════════ */
function renderTable() {
  const start = page * PER;
  const chunk = FILTERED.slice(start, start+PER);
  document.getElementById('table-meta').textContent =
    (start+1).toLocaleString() + '–' + Math.min(start+PER,FILTERED.length).toLocaleString() + ' of ' + FILTERED.length.toLocaleString();

  document.getElementById('table-body').innerHTML = chunk.map(p => {
    const bc = {sfr:'badge-sfr',mf:'badge-mf',demo:'badge-demo',other:'badge-other'}[p.cat]||'badge-other';
    const ds = p.date ? p.date.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}) : '—';
    return `<tr>
      <td style="white-space:nowrap;color:#6b7280;font-family:'IBM Plex Mono',monospace;font-size:11px">${ds}</td>
      <td><span class="badge ${bc}">${LABELS[p.cat]||p.cat}</span></td>
      <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#6b7280;font-size:11px">${p.address||'—'}</td>
      <td style="font-size:11px">${p.hood||'—'}</td>
      <td style="font-size:11px;color:#9ca3af">${p.city}</td>
      <td style="max-width:200px;color:#9ca3af;font-size:11px;line-height:1.4">${p.desc||'—'}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" style="padding:24px;text-align:center;color:#9ca3af">No permits match filters</td></tr>';

  renderPager();
}
function renderPager() {
  const total = Math.ceil(FILTERED.length/PER);
  const el = document.getElementById('pagination');
  if (total<=1){el.innerHTML='';return;}
  el.innerHTML =
    `<button class="page-btn" onclick="goPage(${page-1})" ${page===0?'disabled':''}>← Prev</button>` +
    `<span>Page ${page+1} of ${total}</span>` +
    `<button class="page-btn" onclick="goPage(${page+1})" ${page>=total-1?'disabled':''}>Next →</button>`;
}
window.goPage = p => { page=p; renderTable(); };

/* ═══════════════════════════════════════════════════════════
   CITY TOGGLE
   ═══════════════════════════════════════════════════════════ */
window.setCity = c => {
  currentCity = c;
  document.querySelectorAll('.city-btn').forEach(b=>b.classList.toggle('active',b.dataset.city===c));
  loadData();
};

/* ═══════════════════════════════════════════════════════════
   STATUS / PULSE HELPERS
   ═══════════════════════════════════════════════════════════ */
function pulse(s) {
  document.getElementById('pulse').className='live-dot '+s;
  const lbl={fetching:'Fetching…',live:'Live · '+new Date().toLocaleTimeString(),error:'Error'};
  document.getElementById('live-lbl').textContent=lbl[s]||s;
}
function setStatus(msg,cls) {
  const b=document.getElementById('status-bar');
  b.className='status-bar'+(cls?' '+cls:'');
  document.getElementById('status-text').textContent=msg;
}
function log(html) {
  diagHtml+=html+'<br>';
  document.getElementById('status-diag').innerHTML=diagHtml;
  showDiagBtn();
}
function showDiagBtn(){document.getElementById('status-diag-btn').style.display='inline-block';}
window.toggleDiag=()=>{
  diagOpen=!diagOpen;
  document.getElementById('status-diag').style.display=diagOpen?'block':'none';
  document.getElementById('status-diag-btn').textContent=diagOpen?'Hide details':'Show details';
};
