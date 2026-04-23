import json
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUMMARY_PATH = DATA_DIR / "summary.json"
META_PATH = DATA_DIR / "meta.json"

VALID_CATEGORIES = ["New SFR", "New MF", "Demo"]
YEARS = [2022, 2023, 2024, 2025, 2026]

app = Flask(__name__)


def load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_meta():
    return load_json(
        META_PATH,
        {
            "markets": [],
            "load_notes": [
                "Serving precomputed dataset for instant startup.",
                "Use refresh_data.py locally to rebuild from live Seattle and Bellevue sources.",
            ],
            "load_errors": [],
        },
    )


def load_summary():
    default = {
        "cards": {
            "total_permits": 0,
            "seattle_permits": 0,
            "bellevue_permits": 0,
            "known_markets": 0,
            "new_sfr": 0,
            "new_mf": 0,
            "demo": 0,
            "total_units": 0,
        },
        "annual_series": [
            {"year": y, "New SFR": 0, "New MF": 0, "Demo": 0, "Total": 0, "Units": 0}
            for y in YEARS
        ],
        "neighborhood_rows": [],
        "samples": [],
        "map_points": [],
        "load_notes": ["No precomputed data found."],
        "load_errors": [],
    }
    return load_json(SUMMARY_PATH, default)


def to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def point_year(row):
    if row.get("year"):
        return to_int(row.get("year"), 0)
    for key in ("issue_date", "intake_date"):
        value = str(row.get(key, "") or "")
        if len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])
    return 0


def keep_point(row, jurisdiction, category, market, start_year, end_year):
    if jurisdiction != "all" and row.get("jurisdiction") != jurisdiction:
        return False
    if category != "all" and row.get("category") != category:
        return False
    if market != "all" and row.get("market") != market:
        return False

    y = point_year(row)
    return start_year <= y <= end_year


def summarize_points(points):
    cards = {
        "total_permits": len(points),
        "seattle_permits": sum(1 for p in points if p.get("jurisdiction") == "Seattle"),
        "bellevue_permits": sum(1 for p in points if p.get("jurisdiction") == "Bellevue"),
        "known_markets": len({p.get("market") for p in points if p.get("market")}),
        "new_sfr": sum(1 for p in points if p.get("category") == "New SFR"),
        "new_mf": sum(1 for p in points if p.get("category") == "New MF"),
        "demo": sum(1 for p in points if p.get("category") == "Demo"),
        "total_units": sum(to_int(p.get("units"), 0) for p in points),
    }

    annual_map = {
        y: {"year": y, "New SFR": 0, "New MF": 0, "Demo": 0, "Total": 0, "Units": 0}
        for y in YEARS
    }
    for p in points:
        y = point_year(p)
        if y not in annual_map:
            continue
        cat = p.get("category")
        if cat in ("New SFR", "New MF", "Demo"):
            annual_map[y][cat] += 1
        annual_map[y]["Total"] += 1
        annual_map[y]["Units"] += to_int(p.get("units"), 0)

    annual_series = [annual_map[y] for y in YEARS]

    market_rollup = {}
    for p in points:
        market = p.get("market") or "Unknown"
        if market not in market_rollup:
            market_rollup[market] = {
                "neighborhood": market,
                "jurisdictions": set(),
                "years": {
                    str(y): {
                        "New SFR": 0,
                        "New MF": 0,
                        "Demo": 0,
                        "Total": 0,
                        "Units": 0,
                    }
                    for y in YEARS
                },
                "totals": {"New SFR": 0, "New MF": 0, "Demo": 0, "Total": 0, "Units": 0},
            }

        entry = market_rollup[market]
        entry["jurisdictions"].add(p.get("jurisdiction", ""))
        y = str(point_year(p))
        cat = p.get("category")
        units = to_int(p.get("units"), 0)

        if y in entry["years"]:
            if cat in ("New SFR", "New MF", "Demo"):
                entry["years"][y][cat] += 1
            entry["years"][y]["Total"] += 1
            entry["years"][y]["Units"] += units

        if cat in ("New SFR", "New MF", "Demo"):
            entry["totals"][cat] += 1
        entry["totals"]["Total"] += 1
        entry["totals"]["Units"] += units

    neighborhood_rows = []
    for row in market_rollup.values():
        row["jurisdictions"] = sorted([j for j in row["jurisdictions"] if j])
        neighborhood_rows.append(row)

    neighborhood_rows.sort(key=lambda r: (-r["totals"]["Total"], r["neighborhood"]))

    selected_neighborhoods_rollup = defaultdict(lambda: {"permits": 0, "units": 0, "market": ""})
    for p in points:
        raw = p.get("raw_neighborhood") or "Unknown"
        selected_neighborhoods_rollup[raw]["permits"] += 1
        selected_neighborhoods_rollup[raw]["units"] += to_int(p.get("units"), 0)
        selected_neighborhoods_rollup[raw]["market"] = p.get("market") or "Unknown"

    selected_neighborhoods = [
        {
            "raw_neighborhood": n,
            "market": v["market"],
            "permits": v["permits"],
            "units": v["units"],
        }
        for n, v in selected_neighborhoods_rollup.items()
    ]
    selected_neighborhoods.sort(key=lambda r: (-r["permits"], r["raw_neighborhood"]))

    return cards, annual_series, neighborhood_rows, selected_neighborhoods


def filter_summary(summary, jurisdiction, category, market, start_year, end_year):
    all_points = summary.get("map_points", []) or []
    filtered_points = [
        p
        for p in all_points
        if keep_point(p, jurisdiction, category, market, start_year, end_year)
    ]

    cards, annual_series, neighborhood_rows, selected_neighborhoods = summarize_points(
        filtered_points
    )

    return {
        "cards": cards,
        "annual_series": annual_series,
        "neighborhood_rows": neighborhood_rows,
        "selected_neighborhoods": selected_neighborhoods,
        "map_points": filtered_points,  # ALL filtered points, no hard cap
        "load_notes": summary.get("load_notes", []),
        "load_errors": summary.get("load_errors", []),
    }


@app.route("/")
def index():
    return render_template("index.html", categories=VALID_CATEGORIES, years=YEARS)


@app.route("/api/meta")
def api_meta():
    meta = load_meta()
    return jsonify(meta)


@app.route("/api/summary")
def api_summary():
    summary = load_summary()
    jurisdiction = request.args.get("jurisdiction", "all")
    category = request.args.get("category", "all")
    market = request.args.get("market", "all")
    start_year = int(request.args.get("start_year", YEARS[0]))
    end_year = int(request.args.get("end_year", YEARS[-1]))

    if category not in {"all", *VALID_CATEGORIES}:
        category = "all"
    if jurisdiction not in {"all", "Seattle", "Bellevue"}:
        jurisdiction = "all"

    return jsonify(filter_summary(summary, jurisdiction, category, market, start_year, end_year))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
