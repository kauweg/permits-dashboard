\
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

YEARS = {2022, 2023, 2024, 2025, 2026}
SEATTLE_CSV_URL = "https://data.seattle.gov/api/views/76t5-zqzr/rows.csv?accessType=DOWNLOAD"

MIN_LAT, MAX_LAT = 47.00, 48.00
MIN_LON, MAX_LON = -123.00, -121.00

CATEGORIES = [
    "New SFR / ADU",
    "Townhome / Rowhouse / Duplex",
    "Multifamily / Apartment",
    "Demo",
]

MARKET_BOUNDS = [
    ("West Seattle", 47.49, 47.61, -122.43, -122.34),
    ("Downtown Seattle", 47.595, 47.625, -122.36, -122.315),
    ("First Hill / Capitol Hill", 47.608, 47.642, -122.335, -122.29),
    ("South Lake Union / Eastlake", 47.615, 47.655, -122.35, -122.31),
    ("Queen Anne / Magnolia", 47.615, 47.675, -122.43, -122.34),
    ("Ballard", 47.655, 47.695, -122.41, -122.355),
    ("Fremont / Wallingford", 47.645, 47.675, -122.365, -122.32),
    ("University District / Northeast", 47.645, 47.73, -122.33, -122.25),
    ("North Seattle", 47.675, 47.735, -122.38, -122.29),
    ("Central Seattle", 47.59, 47.63, -122.32, -122.285),
    ("Beacon Hill", 47.535, 47.595, -122.335, -122.29),
    ("South Seattle", 47.49, 47.575, -122.33, -122.24),
    ("Greater Duwamish", 47.50, 47.60, -122.36, -122.30),
]

NEIGHBORHOOD_BOUNDS = [
    ("Alki / Admiral", "West Seattle", 47.57, 47.60, -122.42, -122.37),
    ("West Seattle Junction", "West Seattle", 47.55, 47.58, -122.40, -122.36),
    ("Delridge", "West Seattle", 47.52, 47.58, -122.37, -122.33),
    ("Fauntleroy / Arbor Heights", "West Seattle", 47.49, 47.54, -122.42, -122.36),
    ("Belltown / Pike Market", "Downtown Seattle", 47.608, 47.620, -122.355, -122.335),
    ("Commercial Core", "Downtown Seattle", 47.603, 47.615, -122.340, -122.325),
    ("Pioneer Square / ID", "Downtown Seattle", 47.595, 47.607, -122.340, -122.315),
    ("First Hill", "First Hill / Capitol Hill", 47.605, 47.615, -122.330, -122.315),
    ("Capitol Hill", "First Hill / Capitol Hill", 47.615, 47.642, -122.330, -122.295),
    ("South Lake Union", "South Lake Union / Eastlake", 47.615, 47.630, -122.350, -122.325),
    ("Eastlake", "South Lake Union / Eastlake", 47.630, 47.655, -122.335, -122.315),
    ("Queen Anne", "Queen Anne / Magnolia", 47.625, 47.655, -122.37, -122.34),
    ("Magnolia", "Queen Anne / Magnolia", 47.625, 47.675, -122.43, -122.37),
    ("Ballard", "Ballard", 47.66, 47.69, -122.41, -122.36),
    ("Fremont", "Fremont / Wallingford", 47.645, 47.66, -122.36, -122.34),
    ("Wallingford", "Fremont / Wallingford", 47.655, 47.675, -122.345, -122.32),
    ("U District / Ravenna", "University District / Northeast", 47.655, 47.685, -122.325, -122.295),
    ("Wedgwood / View Ridge", "University District / Northeast", 47.675, 47.71, -122.305, -122.25),
    ("Greenwood / Northgate", "North Seattle", 47.68, 47.735, -122.37, -122.30),
    ("Central District", "Central Seattle", 47.598, 47.625, -122.315, -122.29),
    ("Madison / Leschi", "Central Seattle", 47.595, 47.635, -122.30, -122.275),
    ("Beacon Hill", "Beacon Hill", 47.535, 47.595, -122.325, -122.295),
    ("Columbia City / Rainier", "South Seattle", 47.54, 47.575, -122.305, -122.275),
    ("Rainier Beach", "South Seattle", 47.49, 47.54, -122.29, -122.24),
]

DEMO_HINTS = [" demol", " demolition", " demo ", "teardown", " raze ", "remove structure", "remove building", "deconstruct"]

EXCLUDE_NON_SUPPLY = [
    "repair", "repairs", "replace", "replacement", "roof", "reroof", "re-roof",
    "tenant improvement", "seismic", "retrofit", "interior", "remodel",
    "mechanical", "plumbing", "electrical", "solar", "deck", "retaining wall",
    "shoring", "excavation", "site work", "change of use", "install", "installation",
    "shed", "garage", "minor communication utility", "antenna", "equipment",
]

TOWNHOME_HINTS = [
    "townhome", "townhomes", "townhouse", "townhouses",
    "rowhouse", "rowhouses", "duplex", "triplex", "fourplex",
    "two-family", "2-family", "two family", "cottage housing"
]

MULTIFAMILY_HINTS = [
    "multifamily", "multi-family", "multi family", "apartment", "apartments",
    "condo", "condominium", "mixed use", "mixed-use", "sedu", "sedus",
]

SFR_HINTS = [
    "single family", "single-family", "single family residence",
    "single-family residence", "one-family", "one family",
    "one-family dwelling", "sfr", "detached", "single-family dwelling",
    "single family dwelling"
]

ADU_HINTS = ["adu", "aadu", "dadu", "accessory dwelling"]

STRONG_NEW_HINTS = [
    "construct new", "new construction", "new building", "new structure",
    "establish use", "new single", "new one-family", "new townhome",
    "new townhouse", "new rowhouse", "new apartment", "new multifamily",
    "construct a new", "construct one family", "construct one-family",
    "construct single family", "construct single-family",
]


def norm(v: Any) -> str:
    return " ".join(str(v or "").replace("\xa0", " ").split())


def pick(row: dict[str, Any], keys: list[str]) -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and norm(row.get(key)):
            return row.get(key)
        lk = key.lower()
        if lk in lower and norm(lower[lk]):
            return lower[lk]
    return None


def to_int(v: Any) -> int:
    try:
        if v in (None, ""):
            return 0
        return int(float(str(v).replace(",", "")))
    except Exception:
        return 0


def parse_dt(v: Any) -> datetime | None:
    s = norm(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%y"):
        try:
            return datetime.strptime(s[:26], fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def safe_float(v: Any) -> float | None:
    try:
        if v in (None, "", "NULL"):
            return None
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def valid_pnw(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON


def clean_coordinates(lat: float | None, lon: float | None) -> tuple[float | None, float | None, bool]:
    if valid_pnw(lat, lon):
        return lat, lon, False
    if valid_pnw(lon, lat):
        return lon, lat, True
    return None, None, True


def assign_market_neighborhood(lat: float | None, lon: float | None, fallback: str) -> tuple[str, str]:
    fallback = norm(fallback)

    for hood, market, min_lat, max_lat, min_lon, max_lon in NEIGHBORHOOD_BOUNDS:
        if lat is not None and lon is not None and min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return market, hood

    for market, min_lat, max_lat, min_lon, max_lon in MARKET_BOUNDS:
        if lat is not None and lon is not None and min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return market, fallback if fallback and not fallback.isdigit() else market

    if fallback and not fallback.isdigit():
        return fallback, fallback
    return "Unknown", "Unknown"


def has(text: str, terms: list[str]) -> bool:
    t = f" {norm(text).lower()} "
    return any(term in t for term in terms)


def is_demo(text: str, units_added: int, units_removed: int) -> bool:
    # A permit that says "demolish existing ... and construct new..." should be classified as the new supply, not demo.
    low = f" {norm(text).lower()} "
    if any(h in low for h in STRONG_NEW_HINTS) and units_added > 0:
        return False
    return has(text, DEMO_HINTS) or (units_removed > 0 and units_added <= 0)


def is_non_supply(text: str) -> bool:
    low = f" {norm(text).lower()} "
    if any(h in low for h in STRONG_NEW_HINTS) or "create an attached accessory dwelling unit" in low or "detached accessory dwelling unit" in low:
        return False
    return any(h in low for h in EXCLUDE_NON_SUPPLY)


def classify(row: dict[str, Any], text: str) -> str | None:
    units_added = to_int(pick(row, ["HousingUnitsAdded"]))
    units_removed = to_int(pick(row, ["HousingUnitsRemoved"]))
    units_total = to_int(pick(row, ["HousingUnits"]))

    dwelling_type = norm(pick(row, ["DwellingUnitType"]))
    housing_category = norm(pick(row, ["HousingCategory"]))
    permit_class = norm(pick(row, ["PermitClass", "PermitClassMapped"]))
    permit_type = norm(pick(row, ["PermitTypeDesc", "PermitTypeMapped"]))

    combined = " ".join([text, dwelling_type, housing_category, permit_class, permit_type]).lower()
    low = f" {combined} "

    if is_demo(combined, units_added, units_removed):
        return "Demo"

    if units_added <= 0 and is_non_supply(combined):
        return None

    # Primary correction: Single Family/Duplex permit class + one-family language should not become Townhome.
    is_single_family_class = "single family/duplex" in low or "single family" in low
    is_explicit_townhome = has(combined, ["townhome", "townhomes", "townhouse", "townhouses", "rowhouse", "rowhouses", "cottage housing"])
    is_explicit_duplex_triplex = has(combined, ["duplex", "triplex", "fourplex", "two-family", "2-family", "two family"])
    is_explicit_mf = has(combined, MULTIFAMILY_HINTS)
    is_explicit_sfr = has(combined, SFR_HINTS)
    is_adu = has(combined, ADU_HINTS)

    # If it is an SFR class and says single/one-family, classify as SFR/ADU unless it clearly says townhome/rowhouse/duplex.
    if is_single_family_class and is_explicit_sfr and not is_explicit_townhome and not is_explicit_duplex_triplex:
        return "New SFR / ADU"

    if is_adu and not is_explicit_townhome and not is_explicit_mf:
        return "New SFR / ADU"

    # Structured unit field.
    if units_added > 0:
        if is_explicit_mf and not is_explicit_townhome:
            return "Multifamily / Apartment"
        if is_explicit_townhome or is_explicit_duplex_triplex:
            return "Townhome / Rowhouse / Duplex"
        if units_added == 1:
            return "New SFR / ADU"
        if 2 <= units_added <= 8:
            # Multi-lot SFR plats frequently show multiple added units but text says one-family.
            if is_single_family_class and is_explicit_sfr:
                return "New SFR / ADU"
            return "Townhome / Rowhouse / Duplex"
        return "Multifamily / Apartment"

    if units_total > 0 and any(h in combined for h in STRONG_NEW_HINTS):
        if is_explicit_mf and not is_explicit_townhome:
            return "Multifamily / Apartment"
        if is_explicit_townhome or is_explicit_duplex_triplex:
            return "Townhome / Rowhouse / Duplex"
        if units_total == 1 or (is_single_family_class and is_explicit_sfr):
            return "New SFR / ADU"
        if 2 <= units_total <= 8:
            return "Townhome / Rowhouse / Duplex"
        return "Multifamily / Apartment"

    if not any(h in combined for h in STRONG_NEW_HINTS):
        return None

    if is_explicit_mf and not is_explicit_townhome:
        return "Multifamily / Apartment"
    if is_explicit_townhome or is_explicit_duplex_triplex:
        return "Townhome / Rowhouse / Duplex"
    if is_explicit_sfr or is_adu:
        return "New SFR / ADU"

    return None


def unit_counts(row: dict[str, Any], category: str) -> tuple[int, int, bool]:
    added = to_int(pick(row, ["HousingUnitsAdded"]))
    total = to_int(pick(row, ["HousingUnits"]))
    known = added or total

    if category == "Demo":
        return 0, 0, False

    if known > 500:
        return 0, 0, True

    if known > 0:
        return known, known, False

    if category == "New SFR / ADU":
        return 0, 1, False
    if category == "Townhome / Rowhouse / Duplex":
        return 0, 3, False

    return 0, 0, False


def download_csv_rows(url: str) -> list[dict[str, Any]]:
    r = requests.get(url, timeout=240)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def build_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    description = norm(pick(row, ["Description"]))
    permit_class = norm(pick(row, ["PermitClass", "PermitClassMapped"]))
    permit_type = norm(pick(row, ["PermitTypeDesc", "PermitTypeMapped"]))
    text = " ".join([permit_class, permit_type, description]).strip()

    category = classify(row, text)
    if not category:
        return None, "excluded_by_classifier"

    issue = parse_dt(pick(row, ["IssuedDate"]))
    intake = parse_dt(pick(row, ["AppliedDate"]))
    dt = issue or intake
    if not dt or dt.year not in YEARS:
        return None, "outside_years_or_missing_date"

    lat = safe_float(pick(row, ["Latitude"]))
    lon = safe_float(pick(row, ["Longitude"]))
    lat, lon, bad_coord = clean_coordinates(lat, lon)

    fallback = norm(pick(row, ["OriginalZip"]))
    market, hood = assign_market_neighborhood(lat, lon, fallback)

    known_units, estimated_units, suspicious_units = unit_counts(row, category)

    return {
        "jurisdiction": "Seattle",
        "market": market,
        "neighborhood": market,
        "raw_neighborhood": hood,
        "address": norm(pick(row, ["OriginalAddress1"])),
        "category": category,
        "units": known_units,
        "estimated_units": estimated_units,
        "issue_date": issue.date().isoformat() if issue else "",
        "intake_date": intake.date().isoformat() if intake else "",
        "year": dt.year,
        "latitude": lat,
        "longitude": lon,
        "bad_coordinate_removed": bad_coord,
        "suspicious_units_removed": suspicious_units,
        "summary": text,
    }, "kept"


def fetch_rows(debug: dict[str, Any]) -> list[dict[str, Any]]:
    raw = download_csv_rows(SEATTLE_CSV_URL)
    out = []
    reasons = {}
    columns = set()

    for row in raw:
        columns.update(row.keys())
        item, reason = build_row(row)
        reasons[reason] = reasons.get(reason, 0) + 1
        if item:
            out.append(item)

    debug["seattle_rows_examined"] = len(raw)
    debug["seattle_rows_kept"] = len(out)
    debug["seattle_rows_dropped"] = len(raw) - len(out)
    debug["seattle_drop_reasons"] = reasons
    debug["seattle_unknown_market_rows"] = sum(1 for r in out if r["market"] == "Unknown")
    debug["seattle_bad_coordinate_rows_removed_or_swapped"] = sum(1 for r in out if r.get("bad_coordinate_removed"))
    debug["seattle_suspicious_unit_rows_removed"] = sum(1 for r in out if r.get("suspicious_units_removed"))
    debug["seattle_columns_seen"] = sorted(columns)
    return out


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


def trajectory(vals):
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


def opportunity(row):
    recent = row["years"]["2025"]["Total"] + row["years"]["2026"]["Total"]
    vals = [row["years"][str(y)]["Total"] for y in sorted(YEARS)]
    avg = sum(vals) / len(vals) if vals else 0
    mf = row["totals"]["Multifamily / Apartment"]
    attached = row["totals"]["Townhome / Rowhouse / Duplex"]
    units = row["totals"]["Known Units"] + row["totals"]["Estimated Units"]

    saturation_signals = 0
    if recent >= 25:
        saturation_signals += 1
    if avg > 0 and recent >= avg * 1.4:
        saturation_signals += 1
    if units >= 75:
        saturation_signals += 1
    if recent > 0 and ((mf + attached) / recent) >= 0.65:
        saturation_signals += 1

    opportunity_signals = 0
    if recent <= 6:
        opportunity_signals += 1
    if units <= 15:
        opportunity_signals += 1
    if row.get("trajectory") in {"Stable", "Cooling", "Underserved"}:
        opportunity_signals += 1
    if recent == 0 or ((mf + attached) / max(1, recent)) < 0.50:
        opportunity_signals += 1

    if saturation_signals >= 2:
        return "Saturated / caution"
    if saturation_signals == 1 and row.get("trajectory") == "Accelerating":
        return "Heating up"
    if opportunity_signals >= 2:
        return "Underserved"
    if units > 0 and recent <= 8:
        return "Selective opportunity"
    return "Monitor"


def rollup(rows, field):
    grouped = {}
    for r in rows:
        key = r.get(field) or "Unknown"
        if key not in grouped:
            grouped[key] = {
                "name": key,
                "market": r.get("market") or "Unknown",
                "jurisdictions": set(),
                "years": {str(y): empty_year() for y in sorted(YEARS)},
                "totals": empty_year(),
            }

        g = grouped[key]
        y = str(r["year"])
        cat = r["category"]
        known = int(r.get("units") or 0)
        est = int(r.get("estimated_units") or 0)

        g["jurisdictions"].add(r["jurisdiction"])
        g["years"][y][cat] += 1
        g["years"][y]["Total"] += 1
        g["years"][y]["Known Units"] += known
        g["years"][y]["Estimated Units"] += est
        g["totals"][cat] += 1
        g["totals"]["Total"] += 1
        g["totals"]["Known Units"] += known
        g["totals"]["Estimated Units"] += est

    out = []
    for g in grouped.values():
        vals = [g["years"][str(y)]["Total"] for y in sorted(YEARS)]
        g["jurisdictions"] = sorted(g["jurisdictions"])
        g["trajectory"] = trajectory(vals)
        g["opportunity"] = opportunity(g)
        out.append(g)

    return sorted(out, key=lambda x: (-x["totals"]["Total"], x["name"]))


def build_outputs(rows, debug):
    cards = {
        "total_permits": len(rows),
        "seattle_permits": len(rows),
        "bellevue_permits": 0,
        "known_markets": len({r["market"] for r in rows if r["market"] and r["market"] != "Unknown"}),
        "known_neighborhoods": len({r["raw_neighborhood"] for r in rows if r["raw_neighborhood"] and r["raw_neighborhood"] != "Unknown"}),
        "new_sfr_adu": sum(1 for r in rows if r["category"] == "New SFR / ADU"),
        "townhome_rowhouse_duplex": sum(1 for r in rows if r["category"] == "Townhome / Rowhouse / Duplex"),
        "multifamily_apartment": sum(1 for r in rows if r["category"] == "Multifamily / Apartment"),
        "demo": sum(1 for r in rows if r["category"] == "Demo"),
        "known_units": sum(int(r.get("units") or 0) for r in rows),
        "estimated_units": sum(int(r.get("estimated_units") or 0) for r in rows),
    }

    annual = {y: {"year": y, **empty_year()} for y in sorted(YEARS)}
    for r in rows:
        y = r["year"]
        cat = r["category"]
        annual[y][cat] += 1
        annual[y]["Total"] += 1
        annual[y]["Known Units"] += int(r.get("units") or 0)
        annual[y]["Estimated Units"] += int(r.get("estimated_units") or 0)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": CATEGORIES,
        "cards": cards,
        "annual_series": [annual[y] for y in sorted(annual)],
        "market_rows": rollup(rows, "market"),
        "neighborhood_rows": rollup(rows, "raw_neighborhood"),
        "map_points": rows,
        "load_notes": [
            f"Seattle-first refresh generated {len(rows)} target permit rows.",
            f"Seattle kept {debug.get('seattle_rows_kept', 0)} rows out of {debug.get('seattle_rows_examined', 0)} examined.",
            "Bellevue is intentionally excluded from this run while Seattle classification is being corrected.",
            f"Known markets after refresh: {cards['known_markets']}.",
            f"Known neighborhoods after refresh: {cards['known_neighborhoods']}.",
            f"Known units: {cards['known_units']}; estimated units: {cards['estimated_units']}.",
            f"Bad coordinates removed/swapped: Seattle {debug.get('seattle_bad_coordinate_rows_removed_or_swapped', 0)}.",
            f"Suspicious >500-unit rows removed from unit count: {debug.get('seattle_suspicious_unit_rows_removed', 0)}.",
        ],
        "load_errors": debug.get("errors", []),
    }

    meta = {
        "generated_at": summary["generated_at"],
        "categories": CATEGORIES,
        "markets": sorted({r["market"] for r in rows if r.get("market")}),
        "neighborhoods": sorted({r["raw_neighborhood"] for r in rows if r.get("raw_neighborhood")}),
        "load_notes": summary["load_notes"],
        "load_errors": summary["load_errors"],
    }

    return summary, meta


def main():
    debug = {"errors": []}
    print("Fetching Seattle permits...")
    try:
        rows = fetch_rows(debug)
    except Exception as e:
        rows = []
        debug["errors"].append(f"Seattle refresh failed: {e}")

    summary, meta = build_outputs(rows, debug)

    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (DATA_DIR / "refresh_debug.json").write_text(json.dumps(debug, indent=2), encoding="utf-8")

    print("Wrote", DATA_DIR / "summary.json")
    print("Wrote", DATA_DIR / "meta.json")
    print("Wrote", DATA_DIR / "refresh_debug.json")


if __name__ == "__main__":
    main()
