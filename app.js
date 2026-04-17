:root {
  --bg: #eef3f8;
  --panel: #ffffff;
  --ink: #0f172a;
  --muted: #64748b;
  --line: #d8e1ec;
  --blue: #d8e8ff;
  --blue-strong: #316fdd;
  --green: #d8f3ea;
  --green-strong: #0f766e;
  --red: #fde2e1;
  --red-strong: #b42318;
  --shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, system-ui, sans-serif;
  background: linear-gradient(180deg, #f8fbff 0%, var(--bg) 100%);
  color: var(--ink);
}
.shell {
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px;
}
.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
}
.topbar h1 { margin: 6px 0 8px; font-size: 34px; }
.eyebrow {
  display: inline-block;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--blue);
  color: var(--blue-strong);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.lede { margin: 0; color: var(--muted); max-width: 760px; }
.topbar-right { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.stamp { color: var(--muted); font-size: 13px; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow);
  padding: 18px;
}
.warn-box {
  margin-bottom: 16px;
  padding: 14px 18px;
  border-radius: 18px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
}
.warn-box ul { margin: 8px 0 0 18px; color: #9a3412; }
.filters { margin-bottom: 16px; }
.filter-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 12px;
}
label span {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: .04em;
}
select, input {
  width: 100%;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #fff;
  font: inherit;
}
.search-wrap { grid-column: span 2; }
.btn {
  border: 0;
  border-radius: 12px;
  padding: 12px 16px;
  font-weight: 700;
  cursor: pointer;
}
.btn-primary { background: var(--blue-strong); color: #fff; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.kpi-card { min-height: 142px; }
.kpi-label { color: var(--muted); font-size: 13px; font-weight: 700; text-transform: uppercase; }
.kpi-value { font-size: 34px; font-weight: 800; margin-top: 14px; }
.kpi-sub { color: var(--muted); margin-top: 8px; }
.two-col {
  display: grid;
  grid-template-columns: 1.1fr .9fr;
  gap: 16px;
  margin-bottom: 16px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.panel-header h2 { margin: 0; font-size: 20px; }
.muted { color: var(--muted); font-size: 13px; }
.pill {
  padding: 8px 10px;
  border-radius: 999px;
  background: var(--blue);
  color: var(--blue-strong);
  font-size: 12px;
  font-weight: 700;
}
.chart-note, .empty-note { color: var(--muted); font-size: 13px; }
.trend-chart { min-height: 250px; }
.trend-grid {
  height: 230px;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  align-items: end;
  gap: 14px;
  padding-top: 12px;
}
.trend-col { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.trend-value { font-size: 12px; color: var(--muted); font-weight: 700; }
.trend-stack {
  width: 100%;
  max-width: 120px;
  height: 180px;
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-start;
  border-radius: 18px 18px 8px 8px;
  overflow: hidden;
  background: #edf2f7;
  border: 1px solid var(--line);
}
.trend-segment { width: 100%; }
.trend-segment.sf { background: var(--blue-strong); }
.trend-segment.mf { background: var(--green-strong); }
.trend-segment.demo { background: var(--red-strong); }
.trend-year { font-weight: 700; font-size: 13px; }
.stack-bars { display: grid; gap: 12px; }
.bar-row { display: grid; grid-template-columns: 160px 1fr 80px; gap: 12px; align-items: center; }
.bar-track {
  position: relative;
  width: 100%;
  height: 14px;
  border-radius: 999px;
  background: #edf2f7;
  overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 999px; }
.bar-row.sf .bar-fill { background: var(--blue-strong); }
.bar-row.mf .bar-fill { background: var(--green-strong); }
.bar-row.demo .bar-fill { background: var(--red-strong); }
.map-panel { margin-bottom: 16px; }
#map { height: 430px; border-radius: 18px; overflow: hidden; }
.table-panel { padding-bottom: 6px; }
.table-wrap { overflow: auto; }
.compact-wrap { max-height: 360px; }
.table {
  width: 100%;
  border-collapse: collapse;
  min-width: 980px;
}
.table.compact, .annual-table { min-width: 0; }
.table th, .table td {
  text-align: left;
  padding: 10px 10px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  vertical-align: top;
}
.table thead th {
  position: sticky;
  top: 0;
  background: #f8fbff;
  z-index: 1;
}
.annual-table th, .annual-table td { text-align: right; }
.annual-table th:first-child, .annual-table td:first-child { text-align: left; }
.badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 12px;
}
.badge.sf { background: var(--blue); color: var(--blue-strong); }
.badge.mf { background: var(--green); color: var(--green-strong); }
.badge.demo { background: var(--red); color: var(--red-strong); }
@media (max-width: 1180px) {
  .filter-grid, .kpi-grid, .two-col { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .search-wrap { grid-column: span 2; }
}
@media (max-width: 760px) {
  .shell { padding: 14px; }
  .topbar, .topbar-right, .filter-grid, .kpi-grid, .two-col { grid-template-columns: 1fr; display: grid; }
  .search-wrap { grid-column: span 1; }
  .topbar-right { justify-content: start; }
  .topbar h1 { font-size: 28px; }
  .trend-grid { grid-template-columns: repeat(5, minmax(48px, 1fr)); }
}

.clickable-row {
  cursor: pointer;
}

.linkish {
  background: none;
  border: 0;
  padding: 0;
  margin: 0;
  color: #1d4ed8;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.linkish:hover {
  text-decoration: underline;
}

.drill-chart .trend-stack.single-series {
  justify-content: flex-end;
}

.trend-segment.primary {
  width: 44px;
  background: linear-gradient(180deg, #93c5fd 0%, #316fdd 100%);
  border-radius: 10px 10px 0 0;
}

.click-table tbody tr:hover,
.annual-table tbody tr:hover {
  background: #f8fbff;
}
