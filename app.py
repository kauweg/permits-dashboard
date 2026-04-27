\
import json
from pathlib import Path
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUMMARY_PATH = DATA_DIR / "summary.json"
META_PATH = DATA_DIR / "meta.json"
YEARS = [2022, 2023, 2024, 2025, 2026]
VALID_CATEGORIES = [
    "New SFR / ADU",
    "Townhome / Rowhouse / Duplex",
    "Multifamily / Apartment",
    "Demo",
]

app = Flask(__name__)

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def to_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0

def point_year(row):
    if row.get("year"):
        return to_int(row.get("year"))
    for k in ("issue_date", "intake_date"):
        s = str(row.get(k, "") or "")
        if len(s) >= 4 and s[:4].isdigit():
            return int(s[:4])
    return 0

def classify_trajectory(vals):
    vals = [to_int(v) for v in vals]
    if not vals or sum(vals) == 0:
        return "No data"
    first_two = sum(vals[:2]) / max(1, len(vals[:2]))
    last_two = sum(vals[-2:]) / max(1, len(vals[-2:]))
    avg = sum(vals) / len(vals)
    if last_two >= max(6, first_two * 1.75):
        return "Accelerating"
    if last_two >= max(4, avg * 1.25):
        return "Active"
    if avg >= 3 and last_two <= avg * 0.55:
        return "Cooling"
    if avg <= 2 and last_two <= 2:
        return "Underserved"
    return "Stable"

def opportunity_label(row):
    recent = row["recent_permits"]
    avg = row["avg_permits"]
    mf = row["multifamily_apartment"]
    attached = row["townhome_rowhouse_duplex"]
    units = row["known_units"] + row["estimated_units"]
    if recent >= 25 or (mf >= 10 and recent >= 10) or (attached >= 25 and recent >= 15):
        return "Saturated / caution"
    if recent >= max(6, avg * 1.4):
        return "Heating up"
    if avg <= 3 and recent <= 3:
        return "Underserved"
    if units > 0 and recent <= 8:
        return "Selective opportunity"
    return "Monitor"

def default_summary():
    return {
        "cards": {},
        "annual_series": [{"year": y, **empty_year()} for y in YEARS],
        "market_rows": [],
        "neighborhood_rows": [],
        "map_points": [],
        "load_notes": ["No precomputed data found."],
        "load_errors": [],
    }

def empty_year():
    return {
        "New SFR / ADU": 0,
        "Townhome / Rowhouse / Duplex": 0,
        "Multifamily / Apartment": 0,
        "Demo": 0,
        "Total": 0,
        "Known Units": 0,
        "Estimated Units": 0,
    }

def load_meta():
    return load_json(META_PATH, {"markets": [], "neighborhoods": [], "categories": VALID_CATEGORIES, "load_notes": [], "load_errors": []})

def load_summary():
    return load_json(SUMMARY_PATH, default_summary())

def keep_point(row, jurisdiction, category, market, neighborhood, start_year, end_year):
    if jurisdiction != "all" and row.get("jurisdiction") != jurisdiction:
        return False
    if category != "all" and row.get("category") != category:
        return False
    if market != "all" and row.get("market") != market:
        return False
    if neighborhood != "all" and row.get("raw_neighborhood") != neighborhood:
        return False
    y = point_year(row)
    return start_year <= y <= end_year

def summarize(points):
    cards = {
        "total_permits": len(points),
        "seattle_permits": sum(1 for p in points if p.get("jurisdiction") == "Seattle"),
        "bellevue_permits": sum(1 for p in points if p.get("jurisdiction") == "Bellevue"),
        "known_markets": len({p.get("market") for p in points if p.get("market") and p.get("market") != "Unknown"}),
        "known_neighborhoods": len({p.get("raw_neighborhood") for p in points if p.get("raw_neighborhood") and p.get("raw_neighborhood") != "Unknown"}),
        "new_sfr_adu": sum(1 for p in points if p.get("category") == "New SFR / ADU"),
        "townhome_rowhouse_duplex": sum(1 for p in points if p.get("category") == "Townhome / Rowhouse / Duplex"),
        "multifamily_apartment": sum(1 for p in points if p.get("category") == "Multifamily / Apartment"),
        "demo": sum(1 for p in points if p.get("category") == "Demo"),
        "known_units": sum(to_int(p.get("units")) for p in points),
        "estimated_units": sum(to_int(p.get("estimated_units")) for p in points),
    }

    annual = {y: {"year": y, **empty_year()} for y in YEARS}
    for p in points:
        y = point_year(p)
        if y not in annual:
            continue
        c = p.get("category")
        if c in VALID_CATEGORIES:
            annual[y][c] += 1
        annual[y]["Total"] += 1
        annual[y]["Known Units"] += to_int(p.get("units"))
        annual[y]["Estimated Units"] += to_int(p.get("estimated_units"))

    def rollup(field):
        grouped = {}
        for p in points:
            key = p.get(field) or "Unknown"
            if key not in grouped:
                grouped[key] = {
                    "name": key,
                    "market": p.get("market") or "Unknown",
                    "jurisdictions": set(),
                    "years": {str(y): empty_year() for y in YEARS},
                    "totals": empty_year(),
                }

            g = grouped[key]
            g["jurisdictions"].add(p.get("jurisdiction", ""))
            y = str(point_year(p))
            c = p.get("category")
            if y in g["years"]:
                if c in VALID_CATEGORIES:
                    g["years"][y][c] += 1
                g["years"][y]["Total"] += 1
                g["years"][y]["Known Units"] += to_int(p.get("units"))
                g["years"][y]["Estimated Units"] += to_int(p.get("estimated_units"))
            if c in VALID_CATEGORIES:
                g["totals"][c] += 1
            g["totals"]["Total"] += 1
            g["totals"]["Known Units"] += to_int(p.get("units"))
            g["totals"]["Estimated Units"] += to_int(p.get("estimated_units"))

        out = []
        for g in grouped.values():
            vals = [g["years"][str(y)]["Total"] for y in YEARS]
            recent = g["years"]["2025"]["Total"] + g["years"]["2026"]["Total"]
            avg = round(sum(vals) / len(vals), 1) if vals else 0
            row = {
                **g,
                "jurisdictions": sorted([j for j in g["jurisdictions"] if j]),
                "trajectory": classify_trajectory(vals),
                "recent_permits": recent,
                "avg_permits": avg,
                "new_sfr_adu": g["totals"]["New SFR / ADU"],
                "townhome_rowhouse_duplex": g["totals"]["Townhome / Rowhouse / Duplex"],
                "multifamily_apartment": g["totals"]["Multifamily / Apartment"],
                "known_units": g["totals"]["Known Units"],
                "estimated_units": g["totals"]["Estimated Units"],
            }
            row["opportunity"] = opportunity_label(row)
            out.append(row)
        return sorted(out, key=lambda r: (-r["totals"]["Total"], r["name"]))

    return cards, [annual[y] for y in YEARS], rollup("market"), rollup("raw_neighborhood")

def filter_summary(summary, jurisdiction, category, market, neighborhood, start_year, end_year):
    points = [p for p in summary.get("map_points", []) if keep_point(p, jurisdiction, category, market, neighborhood, start_year, end_year)]
    cards, annual, market_rows, neighborhood_rows = summarize(points)
    return {
        "cards": cards,
        "annual_series": annual,
        "market_rows": market_rows,
        "neighborhood_rows": neighborhood_rows,
        "map_points": points,
        "categories": summary.get("categories", VALID_CATEGORIES),
        "load_notes": summary.get("load_notes", []),
        "load_errors": summary.get("load_errors", []),
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/meta")
def api_meta():
    meta = load_meta()
    meta["categories"] = meta.get("categories", VALID_CATEGORIES)
    return jsonify(meta)

@app.route("/api/summary")
def api_summary():
    s = load_summary()
    jurisdiction = request.args.get("jurisdiction", "all")
    category = request.args.get("category", "all")
    market = request.args.get("market", "all")
    neighborhood = request.args.get("neighborhood", "all")
    start_year = int(request.args.get("start_year", YEARS[0]))
    end_year = int(request.args.get("end_year", YEARS[-1]))
    if category not in {"all", *VALID_CATEGORIES}:
        category = "all"
    if jurisdiction not in {"all", "Seattle", "Bellevue"}:
        jurisdiction = "all"
    return jsonify(filter_summary(s, jurisdiction, category, market, neighborhood, start_year, end_year))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
