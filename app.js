/* ═══════════════════════════════════════════════════════════
   PNW Construction Permit Dashboard — app.js
   Seattle:  Socrata SODA API  (data.seattle.gov)
   Bellevue: ArcGIS Feature Service (data.bellevuewa.gov / COBGIS)
   ═══════════════════════════════════════════════════════════ */
'use strict';

/* ─── API Config ─────────────────────────────────────────── */
const SEATTLE_URL = 'https://data.seattle.gov/resource/76t5-zqzr.json';

// Bellevue uses ArcGIS Online hosted by COBGIS org.
// Dataset: "Bellevue Permits" — refreshed daily, 5-year rolling window.
// Primary endpoint (COBGIS ArcGIS Online org):
const BELLEVUE_URL = 'https://services8.arcgis.com/rGGrs6HCnw29OGFW/arcgis/rest/services/Bellevue_Permits/FeatureServer/0/query';
// Fallback: direct Bellevue GIS server
const BELLEVUE_FALLBACK = 'https://gis-web.bellevuewa.gov/gisext/rest/services/DS/BellevuePermits/FeatureServer/0/query';

/* ─── Constants ──────────────────────────────────────────── */
const YEARS = [2021,2022,2023,2024,2025,2026];
const TYPE_COLORS = { sfr:'#4f8ef7', mf:'#e8593c', demo:'#f5c842', other:'#9b7df7' };
const TYPE_LABELS = { sfr:'Single family', mf:'Multifamily', demo:'Demolition', other:'Other' };
const SEATTLE_NEIGHBORHOODS = [
  'Capitol Hill','Ballard','Fremont','Wallingford','Queen Anne','Magnolia','Belltown',
  'South Lake Union','Eastlake','Montlake','Madrona','Madison Park','Leschi','Beacon Hill',
  'Columbia City','Georgetown','Sodo','West Seattle','Delridge','Northgate','Greenwood',
  'Phinney Ridge','Roosevelt','Ravenna','Wedgwood','Maple Leaf','Lake City','Sand Point',
  'View Ridge','Laurelhurst','South Park','Rainier Beach','First Hill','Central District',
  'International District','Pioneer Square','Lower Queen Anne','Interbay','Bitter Lake',
  'Crown Hill','Licton Springs','Pinehurst','Cedar Park','Haller Lake','Rainier Valley',
  'Mount Baker','Seward Park','Othello','Judkins Park','Yesler Terrace','Chinatown'
];

/* ─── State ──────────────────────────────────────────────── */
let allPermits  = [];
let filtered    = [];
let currentCity = 'seattle';
let currentPage = 0;
const PAGE_SIZE = 50;
let leafletMap  = null;
let markerLayer = null;
let trendChart  = null;
let typeChart   = null;
let diagOpen    = false;

/* ─── Boot ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => { initMap(); loadData(); });

/* ═══════════════════════════════════════════════════════════
   LOAD DATA
   ═══════════════════════════════════════════════════════════ */
async function loadData() {
  setPulse('fetching');
  setStatus('Fetching live permit data…');
  clearDiag();
  allPermits = [];

  const cities = currentCity === 'both' ? ['seattle','bellevue'] : [currentCity];
  const results = await Promise.allSettled(cities.map(c => c==='seattle' ? fetchSeattle() : fetchBellevue()));

  results.forEach((r,i) => {
    if (r.status === 'fulfilled') allPermits = allPermits.concat(r.value);
    else { console.error(cities[i], r.reason); addDiag(`<span class="err">✗ ${cities[i]}: ${r.reason.message}</span>`); }
  });

  if (!allPermits.length) { setPulse('error'); setStatus('✗ No data loaded — see details', 'err'); showDiagBtn(); return; }

  const ts = new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  setPulse('live');
  setStatus(`✓ ${allPermits.length.toLocaleString()} permits loaded · ${ts}`, 'ok');
  populateNeighborhoodFilter();
  applyFilters();
}

/* ── Seattle: Socrata SODA ── */
async function fetchSeattle() {
  const rows = [];
  let offset = 0;
  const where = "permittype IN('Construction','Demolition') AND permitclass='Residential' AND issueddate>='2021-01-01T00:00:00' AND latitude IS NOT NULL";
  const select = 'permitnum,issueddate,permittype,permitclassmapped,description,latitude,longitude,statuscurrent';

  do {
    const url = SEATTLE_URL
      + '?$limit=50000'
      + '&$offset=' + offset
      + '&$order=issueddate+DESC'
      + '&$select=' + encodeURIComponent(select)
      + '&$where=' + encodeURIComponent(where).replace(/%27/g,"'");
    addDiag('<span class="url">GET ' + url.substring(0,120) + '…</span>');
    setStatus('Seattle: fetching rows ' + offset.toLocaleString() + '+…');
    const res  = await fetch(url, {headers:{Accept:'application/json'}});
    if (!res.ok) throw new Error('Seattle HTTP ' + res.status + ' ' + res.statusText);
    const page = await res.json();
    if (!Array.isArray(page)) throw new Error('Seattle unexpected response: ' + JSON.stringify(page).slice(0,80));
    page.forEach(r => rows.push(normalizeSeattle(r)));
    offset += 50000;
    if (page.length < 50000) break;
  } while (true);

  addDiag(`<span style="color:#22c98e">✓ Seattle: ${rows.length.toLocaleString()} records</span>`);
  return rows;
}

function normalizeSeattle(r) {
  const cls  = (r.permitclassmapped||'').toLowerCase();
  const typ  = (r.permittype||'').toLowerCase();
  const desc = (r.description||'').toLowerCase();
  let cat = 'other';
  if      (typ==='demolition'||desc.includes('demolish')) cat='demo';
  else if (cls.includes('single')||cls.includes('duplex')||desc.includes('single family')||desc.includes('sfr')) cat='sfr';
  else if (cls.includes('multi')||desc.includes('multifamily')||desc.includes('apartment')||desc.includes('townhouse')||desc.includes('condo')) cat='mf';
  const date = r.issueddate ? new Date(r.issueddate) : null;
  return {
    id: r.permitnum||'', city:'Seattle', date, year:date?date.getFullYear():null, month:date?date.getMonth():null,
    category:cat, description:(r.description||'').substring(0,140), address:'',
    neighborhood: guessSeattleNeighborhood(r.description||''),
    lat:parseFloat(r.latitude), lon:parseFloat(r.longitude), status:r.statuscurrent||''
  };
}

function guessSeattleNeighborhood(desc) {
  const d = desc.toLowerCase();
  for (const n of SEATTLE_NEIGHBORHOODS) { if (d.includes(n.toLowerCase())) return n; }
  // fallback: assign based on lat/lon grid (rough)
  return 'Seattle (unspecified)';
}

/* ── Bellevue: ArcGIS Feature Service ── */
async function fetchBellevue() {
  // Try primary URL first, then fallback
  for (const base of [BELLEVUE_URL, BELLEVUE_FALLBACK]) {
    try {
      return await fetchBellevueFrom(base);
    } catch(e) {
      addDiag(`<span class="err">Bellevue endpoint failed: ${base.substring(0,60)}… — ${e.message}</span>`);
    }
  }
  // Both failed — return empty with info
  addDiag(`<span class="err">Bellevue: both endpoints failed. Visit data.bellevuewa.gov to find the current FeatureServer URL and update BELLEVUE_URL in app.js.</span>`);
  return [];
}

async function fetchBellevueFrom(baseUrl) {
  // ArcGIS date filter syntax
  const where = "IssueDate >= '2021-01-01' AND IssueDate IS NOT NULL";
  const params = new URLSearchParams({
    where,
    outFields: 'PermitNumber,IssueDate,PermitTypeCode,PermitTypeDesc,WorkDesc,SiteAddress,Neighborhood,Latitude,Longitude,StatusDesc',
    returnGeometry: 'false',
    resultRecordCount: '2000',
    resultOffset: '0',
    orderByFields: 'IssueDate DESC',
    f: 'json'
  });
  const url = baseUrl + '?' + params.toString();
  addDiag('<span class="url">GET ' + url.substring(0,120) + '…</span>');
  setStatus('Bellevue: fetching permits…');

  const res  = await fetch(url, {headers:{Accept:'application/json'}});
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const json = await res.json();
  if (json.error) throw new Error(json.error.message || JSON.stringify(json.error));
  if (!json.features) throw new Error('No features in response: ' + JSON.stringify(json).slice(0,100));

  const rows = json.features.map(f => normalizeBellevue(f.attributes || f));
  addDiag(`<span style="color:#22c98e">✓ Bellevue: ${rows.length.toLocaleString()} records</span>`);
  return rows;
}

function normalizeBellevue(a) {
  const code = (a.PermitTypeCode||'').toUpperCase();
  let cat = 'other';
  if      (['BT','BD'].includes(code))      cat='demo';
  else if (['BS'].includes(code))            cat='sfr';
  else if (['BB','BH','BM'].includes(code)) cat='mf';
  // IssueDate can be epoch ms (ArcGIS) or ISO string
  const raw  = a.IssueDate;
  const date = raw ? new Date(typeof raw==='number' ? raw : raw) : null;
  return {
    id: a.PermitNumber||'', city:'Bellevue', date, year:date?date.getFullYear():null, month:date?date.getMonth():null,
    category:cat, description:(a.WorkDesc||a.PermitTypeDesc||'').substring(0,140),
    address:a.SiteAddress||'', neighborhood:a.Neighborhood||'Bellevue',
    lat:parseFloat(a.Latitude), lon:parseFloat(a.Longitude), status:a.StatusDesc||''
  };
}

/* ═══════════════════════════════════════════════════════════
   FILTERING
   ═══════════════════════════════════════════════════════════ */
function applyFilters() {
  const q     = (document.getElementById('search-input').value||'').toLowerCase().trim();
  const fType = document.getElementById('filter-type').value;
  const fNbhd = document.getElementById('filter-neighborhood').value;
  const fYear = document.getElementById('filter-year').value;

  filtered = allPermits.filter(p => {
    if (!isFinite(p.lat)||!isFinite(p.lon)||p.lat===0) return false;
    if (fType!=='all' && p.category!==fType) return false;
    if (fNbhd!=='all' && p.neighborhood!==fNbhd) return false;
    if (fYear!=='all' && String(p.year)!==fYear) return false;
    if (q) {
      const hay = [p.address,p.description,p.neighborhood,p.id,p.city].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  document.getElementById('filter-count').textContent = filtered.length.toLocaleString() + ' permits';
  currentPage = 0;
  renderAll();
}

function populateNeighborhoodFilter() {
  const nbhds = [...new Set(allPermits.map(p=>p.neighborhood).filter(Boolean))].sort();
  const sel = document.getElementById('filter-neighborhood');
  sel.innerHTML = '<option value="all">All neighborhoods</option>';
  nbhds.forEach(n => { const o=document.createElement('option'); o.value=o.textContent=n; sel.appendChild(o); });
}

/* ═══════════════════════════════════════════════════════════
   RENDER
   ═══════════════════════════════════════════════════════════ */
function renderAll() {
  renderKPIs();
  renderTrendChart();
  renderNeighborhoodBars();
  renderTypeChart();
  renderInsights();
  renderMap();
  renderTable();
}

/* ── KPIs ── */
function renderKPIs() {
  const total = filtered.length;
  const sfr   = filtered.filter(p=>p.category==='sfr').length;
  const mf    = filtered.filter(p=>p.category==='mf').length;
  const demo  = filtered.filter(p=>p.category==='demo').length;
  const curY  = new Date().getFullYear();
  const cur   = filtered.filter(p=>p.year===curY).length;
  const prior = filtered.filter(p=>p.year===curY-1).length;
  let yoy='—', yoyClass='';
  if (prior>0) { const p=Math.round((cur-prior)/prior*100); yoy=(p>=0?'+':'')+p+'%'; yoyClass=p>=0?'up':'down'; }
  const nc={}; filtered.forEach(p=>{if(p.neighborhood)nc[p.neighborhood]=(nc[p.neighborhood]||0)+1;});
  const hot=Object.entries(nc).sort((a,b)=>b[1]-a[1])[0];
  setKPI('kpi-total', total.toLocaleString(),'Total permits');
  setKPI('kpi-sfr',   sfr.toLocaleString(),  'Single family');
  setKPI('kpi-mf',    mf.toLocaleString(),   'Multifamily');
  setKPI('kpi-demo',  demo.toLocaleString(), 'Demolitions');
  setKPI('kpi-yoy',   yoy, curY+' vs '+(curY-1), yoyClass);
  setKPI('kpi-hot',   hot?hot[0].split(' ').slice(0,2).join(' '):'—', hot?hot[1].toLocaleString()+' permits':'Hottest neighborhood');
}
function setKPI(id,val,lbl,cls) {
  const el=document.getElementById(id);
  el.querySelector('.kpi-val').textContent=val;
  el.querySelector('.kpi-lbl').textContent=lbl;
  el.className='kpi'+(cls?' '+cls:'');
}

/* ── Trend chart ── */
function renderTrendChart() {
  const by={}; YEARS.forEach(y=>by[y]={sfr:0,mf:0,demo:0,other:0});
  filtered.forEach(p=>{if(p.year&&by[p.year]!==undefined)by[p.year][p.category]++;});
  const datasets=[
    {label:'Single family',data:YEARS.map(y=>by[y].sfr), borderColor:'#4f8ef7',backgroundColor:'rgba(79,142,247,0.12)',tension:.4,fill:true,pointRadius:3,pointHoverRadius:5},
    {label:'Multifamily',  data:YEARS.map(y=>by[y].mf),  borderColor:'#e8593c',backgroundColor:'rgba(232,89,60,0.10)', tension:.4,fill:true,pointRadius:3,pointHoverRadius:5},
    {label:'Demolition',   data:YEARS.map(y=>by[y].demo), borderColor:'#f5c842',backgroundColor:'rgba(245,200,66,0.10)',tension:.4,fill:true,pointRadius:3,pointHoverRadius:5},
  ];
  document.getElementById('trend-legend').innerHTML = datasets.map(d=>
    `<div class="leg-item"><div class="leg-dot" style="background:${d.borderColor}"></div>${d.label}</div>`).join('');
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(document.getElementById('trend-chart'),{
    type:'line', data:{labels:YEARS.map(String),datasets},
    options:{responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#11141c',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#e4e2da',bodyColor:'#8a90a0',padding:10}},
      scales:{x:{grid:{color:'rgba(255,255,255,0.05)'},ticks:{color:'#626878',font:{family:'DM Mono',size:10}}},
              y:{grid:{color:'rgba(255,255,255,0.05)'},ticks:{color:'#626878',font:{family:'DM Mono',size:10}},beginAtZero:true}}}
  });
}

/* ── Neighborhood bars ── */
function renderNeighborhoodBars() {
  const counts={};
  filtered.forEach(p=>{if(p.neighborhood)counts[p.neighborhood]=(counts[p.neighborhood]||0)+1;});
  const sorted=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,25);
  const maxV=sorted[0]?.[1]||1;
  const fYear=document.getElementById('filter-year').value;
  document.getElementById('nbhd-year-label').textContent=fYear==='all'?'all years':fYear;
  document.getElementById('nbhd-bars').innerHTML=sorted.map(([name,count])=>{
    const pct=(count/maxV*100).toFixed(1);
    const isTop=count===maxV;
    return `<div class="nbhd-row" onclick="filterByNeighborhood('${name.replace(/'/g,"\\'")}')">
      <span class="nbhd-name" title="${name}">${name}</span>
      <div class="nbhd-track"><div class="nbhd-bar" style="width:${pct}%;background:${isTop?'#4f8ef7':'rgba(79,142,247,0.4)'}"></div></div>
      <span class="nbhd-count">${count}</span>
    </div>`;
  }).join('')||'<div style="color:var(--muted);font-size:12px;padding:8px 0">No data for current filters</div>';
}
window.filterByNeighborhood=n=>{document.getElementById('filter-neighborhood').value=n;applyFilters();};

/* ── Type mix stacked bar ── */
function renderTypeChart() {
  const by={}; YEARS.forEach(y=>by[y]={sfr:0,mf:0,demo:0});
  filtered.forEach(p=>{if(p.year&&by[p.year]!==undefined)by[p.year][p.category]++;});
  if (typeChart) typeChart.destroy();
  typeChart=new Chart(document.getElementById('type-chart'),{
    type:'bar',
    data:{labels:YEARS.map(String),datasets:[
      {label:'Single family',data:YEARS.map(y=>by[y].sfr), backgroundColor:'#4f8ef7cc',borderRadius:3},
      {label:'Multifamily',  data:YEARS.map(y=>by[y].mf),  backgroundColor:'#e8593ccc',borderRadius:3},
      {label:'Demolition',   data:YEARS.map(y=>by[y].demo), backgroundColor:'#f5c842cc',borderRadius:3},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#11141c',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#e4e2da',bodyColor:'#8a90a0',padding:10}},
      scales:{x:{stacked:true,grid:{color:'rgba(255,255,255,0.05)'},ticks:{color:'#626878',font:{family:'DM Mono',size:10}}},
              y:{stacked:true,grid:{color:'rgba(255,255,255,0.05)'},ticks:{color:'#626878',font:{family:'DM Mono',size:10}},beginAtZero:true}}}
  });
}

/* ── Executive insights ── */
function renderInsights() {
  const insights=[];
  const curY=new Date().getFullYear();
  const by={}; YEARS.forEach(y=>by[y]={sfr:0,mf:0,demo:0,total:0});
  filtered.forEach(p=>{if(p.year&&by[p.year]!==undefined){by[p.year][p.category]++;by[p.year].total++;}});

  // MF momentum
  if (by[curY-1].mf>0) {
    const pct=Math.round((by[curY].mf-by[curY-1].mf)/by[curY-1].mf*100);
    insights.push({icon:'🏢',color:pct>=0?'#22c98e22':'#f0525222',
      text:`Multifamily pipeline is <strong class="${pct>=0?'up':'dn'}">${pct>=0?'+':''}${pct}%</strong> vs last year (${by[curY].mf.toLocaleString()} vs ${by[curY-1].mf.toLocaleString()} permits). ${pct>15?'Strong demand signal — high-density underway.':pct<-10?'Cooling multifamily — monitor for over-supply.':'Stable multifamily pipeline.'}`});
  }

  // Demo-to-build ratio
  const demo3=YEARS.slice(-3).reduce((s,y)=>s+(by[y]?.demo||0),0);
  const new3 =YEARS.slice(-3).reduce((s,y)=>s+(by[y]?.sfr||0)+(by[y]?.mf||0),0);
  if (demo3>0) {
    const ratio=(new3/demo3).toFixed(1);
    insights.push({icon:'🔄',color:'#9b7df722',
      text:`Demo-to-new-build ratio: <strong>${ratio}x</strong> over 3 years (${new3.toLocaleString()} new vs ${demo3.toLocaleString()} demos). ${ratio>1.5?'Net new housing being added.':ratio<0.9?'Demolition outpacing replacement — watch supply.':'Near 1:1 replacement rate.'}`});
  }

  // Hottest neighborhood (recent 2 years)
  const nc={}; const ncMF={};
  filtered.filter(p=>p.year>=curY-1).forEach(p=>{if(p.neighborhood){nc[p.neighborhood]=(nc[p.neighborhood]||0)+1;if(p.category==='mf')ncMF[p.neighborhood]=(ncMF[p.neighborhood]||0)+1;}});
  const hot=Object.entries(nc).sort((a,b)=>b[1]-a[1])[0];
  if (hot) {
    const mfShare=Math.round((ncMF[hot[0]]||0)/hot[1]*100);
    insights.push({icon:'📍',color:'#4f8ef722',
      text:`<strong>${hot[0]}</strong> is the hottest zone — <strong>${hot[1]}</strong> permits in the last 2 years (${mfShare}% multifamily). Prioritize land acquisition here.`});
  }

  // SFR trend
  if (by[curY-1].sfr>0) {
    const pct=Math.round((by[curY].sfr-by[curY-1].sfr)/by[curY-1].sfr*100);
    insights.push({icon:'🏠',color:'#f5c84222',
      text:`Single-family construction <strong class="${pct>=0?'up':'dn'}">${pct>=0?'+':''}${pct}%</strong> YoY. ${pct>15?'SFR expansion — likely driven by ADU/middle-housing policy.':Math.abs(pct)<5?'SFR market stable.':'Watch for continued SFR softening.'}`});
  }

  // 90-day run rate
  const ninety=filtered.filter(p=>p.date&&(Date.now()-p.date.getTime())<90*864e5);
  if (ninety.length>10) {
    const ann=Math.round(ninety.length*(365/90));
    const prior=by[curY-1].total;
    insights.push({icon:'📈',color:'#4f8ef722',
      text:`Last 90 days: <strong>${ninety.length}</strong> permits → annualizes to <strong>~${ann.toLocaleString()}</strong>. ${prior>0&&ann>prior*1.1?'Above prior-year run rate — pipeline accelerating.':'In line with historical pace.'}`});
  }

  // Both cities comparison
  if (currentCity==='both') {
    const bv=filtered.filter(p=>p.city==='Bellevue').length;
    const se=filtered.filter(p=>p.city==='Seattle').length;
    if (bv>0) insights.push({icon:'🌆',color:'#22c98e22',
      text:`Bellevue: <strong>${bv.toLocaleString()}</strong> permits vs Seattle: <strong>${se.toLocaleString()}</strong>. Bellevue's denser footprint suggests higher per-capita construction intensity — strong signal for Eastside opportunity.`});
  }

  document.getElementById('insights').innerHTML=insights.slice(0,5).map(i=>
    `<div class="insight-item"><div class="insight-icon" style="background:${i.color}">${i.icon}</div><div class="insight-text">${i.text}</div></div>`
  ).join('')||'<div style="color:var(--muted);font-size:12px">Load data to see insights.</div>';
}

/* ═══════════════════════════════════════════════════════════
   MAP
   ═══════════════════════════════════════════════════════════ */
function initMap() {
  leafletMap=L.map('map',{zoomControl:true}).setView([47.57,-122.27],11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:19}).addTo(leafletMap);
  markerLayer=L.layerGroup().addTo(leafletMap);
}

function renderMap() {
  markerLayer.clearLayers();
  const pts=filtered.filter(p=>isFinite(p.lat)&&isFinite(p.lon)&&p.lat!==0&&Math.abs(p.lat)>10);
  const sample=pts.length>5000?pts.slice(0,5000):pts;
  document.getElementById('map-badge').innerHTML=
    `<strong>${pts.length.toLocaleString()}</strong> permits`+(pts.length>5000?' <span style="color:var(--muted)">(showing 5k)</span>':'');

  sample.forEach(p=>{
    const c=TYPE_COLORS[p.category]||'#888';
    L.circleMarker([p.lat,p.lon],{radius:4,fillColor:c,color:'rgba(0,0,0,0.25)',weight:0.5,fillOpacity:0.85})
     .bindPopup(`<b style="color:${c}">${TYPE_LABELS[p.category]||p.category}</b> · ${p.city}<br>`
       +(p.date?p.date.toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric'})+'<br>':'')
       +(p.address?p.address+'<br>':'')
       +(p.neighborhood?`<span style="color:#8a90a0">${p.neighborhood}</span><br>`:'')
       +`<span style="color:#626878;font-size:10px">${p.description.substring(0,80)}</span>`)
     .addTo(markerLayer);
  });

  if (pts.length>0) {
    try { leafletMap.fitBounds(L.latLngBounds(sample.map(p=>[p.lat,p.lon])),{padding:[28,28],maxZoom:13}); } catch(e) {}
  }

  const fType=document.getElementById('filter-type').value;
  const fYear=document.getElementById('filter-year').value;
  document.getElementById('map-title').textContent=[
    currentCity==='both'?'Seattle & Bellevue':(currentCity.charAt(0).toUpperCase()+currentCity.slice(1)),
    fType!=='all'?TYPE_LABELS[fType]:'All types',
    fYear!=='all'?fYear:'2021–2026'
  ].join(' · ');
}

window.setMapMode=mode=>{
  document.querySelectorAll('.map-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('btn-'+mode).classList.add('active');
  renderMap();
};

/* ═══════════════════════════════════════════════════════════
   TABLE
   ═══════════════════════════════════════════════════════════ */
function renderTable() {
  const start=currentPage*PAGE_SIZE;
  const page=filtered.slice(start,start+PAGE_SIZE);
  document.getElementById('table-count').textContent=
    `${(start+1).toLocaleString()}–${Math.min(start+PAGE_SIZE,filtered.length).toLocaleString()} of ${filtered.length.toLocaleString()}`;

  document.getElementById('table-body').innerHTML=page.map(p=>{
    const bc={sfr:'type-sfr',mf:'type-mf',demo:'type-demo',other:'type-other'}[p.category]||'type-other';
    const ds=p.date?p.date.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'—';
    return `<tr>
      <td style="white-space:nowrap;color:var(--muted2)">${ds}</td>
      <td><span class="type-badge ${bc}">${TYPE_LABELS[p.category]||p.category}</span></td>
      <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.address||'—'}</td>
      <td>${p.neighborhood||'—'}</td>
      <td><span style="color:var(--muted2)">${p.city}</span></td>
      <td style="max-width:220px;color:var(--muted2);font-size:11px;line-height:1.4">${p.description||'—'}</td>
    </tr>`;
  }).join('')||'<tr><td colspan="6" style="color:var(--muted);padding:24px;text-align:center">No permits match current filters</td></tr>';
  renderPagination();
}

function renderPagination() {
  const total=Math.ceil(filtered.length/PAGE_SIZE);
  const pg=document.getElementById('pagination');
  if (total<=1){pg.innerHTML='';return;}
  pg.innerHTML=
    `<button class="page-btn" onclick="gotoPage(${currentPage-1})" ${currentPage===0?'disabled':''}>← Prev</button>`+
    `<span>Page ${currentPage+1} of ${total}</span>`+
    `<button class="page-btn" onclick="gotoPage(${currentPage+1})" ${currentPage>=total-1?'disabled':''}>Next →</button>`;
}
window.gotoPage=p=>{currentPage=p;renderTable();};

/* ═══════════════════════════════════════════════════════════
   CITY SWITCH & GLOBAL HANDLERS
   ═══════════════════════════════════════════════════════════ */
window.setCity=city=>{
  currentCity=city;
  document.querySelectorAll('.city-tab').forEach(t=>t.classList.toggle('active',t.dataset.city===city));
  loadData();
};

/* ═══════════════════════════════════════════════════════════
   STATUS / PULSE HELPERS
   ═══════════════════════════════════════════════════════════ */
function setPulse(s) {
  document.getElementById('pulse').className='pulse-dot '+s;
  const labels={fetching:'Fetching…',live:'Live · '+new Date().toLocaleTimeString(),error:'Error'};
  document.getElementById('live-lbl').textContent=labels[s]||s;
}
function setStatus(msg,cls) {
  const bar=document.getElementById('status-bar');
  bar.className=cls||'';
  document.getElementById('status-text').textContent=msg;
}
let diagHtml='';
function clearDiag(){diagHtml='';document.getElementById('status-detail').innerHTML='';}
function addDiag(html){
  diagHtml+=html+'<br>';
  document.getElementById('status-detail').innerHTML=diagHtml;
  showDiagBtn();
}
function showDiagBtn(){document.getElementById('status-detail-btn').style.display='inline-block';}
window.toggleStatusDetail=()=>{
  diagOpen=!diagOpen;
  document.getElementById('status-detail').style.display=diagOpen?'block':'none';
  document.getElementById('status-detail-btn').textContent=diagOpen?'hide ▴':'details ▾';
};
