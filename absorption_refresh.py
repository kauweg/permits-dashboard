"""Absorption early-warning refresh.

Joins Seattle new-construction permit completions (SDCI) to King County
Assessor recorded sales to measure days-from-completion-to-sale per
neighborhood and product type, plus pipeline pressure (issued-not-completed
units) and months of supply.

Inputs
------
1. Seattle permits CSV (auto-downloaded, same source as refresh_data.py),
   or pass a local file:  python absorption_refresh.py --permits-csv path.csv
2. King County Assessor extracts (manual download, like the Redmond CSV):
   https://info.kingcounty.gov/assessor/datadownload/default.aspx
   Unzip and place in data/kc_extracts/:
     - EXTR_RPSale.csv    (Real Property Sales)
     - EXTR_ResBldg.csv   (Residential Building - has address + YrBuilt)

Outputs (commit these, same pattern as summary.json)
------
  data/absorption.json
  data/absorption_debug.json

Run locally:  python absorption_refresh.py
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from refresh_data import (
    SEATTLE_CSV_URL,
    assign_market_neighborhood,
    classify,
    clean_coordinates,
    norm,
    parse_dt,
    pick,
    safe_float,
    to_int,
    unit_counts,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
EXTRACT_DIR = DATA_DIR / "kc_extracts"

# ---------------------------------------------------------------- parameters
PARAMS = {
    # Sales below this are treated as non-market transfers (quit claims, etc.)
    "min_sale_price": 200_000,
    # Presale closings can record slightly before the final-inspection date.
    "presale_grace_days": 60,
    # A sale more than this long after completion is ignored (likely resale
    # of a unit we failed to catch earlier, or data noise).
    "max_days_to_sale": 1095,
    # Building must be roughly as new as the permit completion to count
    # (guards against matching an old house record at the same address).
    "yr_built_tolerance": 2,
    # Fuzzy tier: same street, same parity, house number within +/- N.
    "house_number_window": 6,
    # Pipeline = issued within this many months, no completion date yet.
    "pipeline_window_months": 36,
    # Standing inventory = completed within this window, no sale matched.
    "standing_window_months": 24,
    # Warning thresholds.
    "yellow_median_days": 90,
    "red_median_days": 120,
    "yellow_months_of_supply": 6.0,
    "red_months_of_supply": 10.0,
    "yellow_trend_days": 30,
    "min_sales_for_signal": 5,
}

# Absorption only makes sense for for-sale product.
SALE_CATEGORIES = ["New SFR / ADU", "Townhome / Rowhouse / Duplex"]

# ------------------------------------------------------------ address logic
SUFFIXES = {
    "AVENUE": "AVE", "AV": "AVE", "AVE": "AVE",
    "STREET": "ST", "STR": "ST", "ST": "ST",
    "PLACE": "PL", "PL": "PL",
    "COURT": "CT", "CT": "CT",
    "DRIVE": "DR", "DR": "DR",
    "LANE": "LN", "LN": "LN",
    "ROAD": "RD", "RD": "RD",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "WAY": "WAY", "WY": "WAY",
    "TERRACE": "TER", "TER": "TER",
    "CIRCLE": "CIR", "CIR": "CIR",
    "PARKWAY": "PKWY", "PKWY": "PKWY", "PKY": "PKWY",
    "TRAIL": "TRL", "TRL": "TRL",
    "LOOP": "LOOP", "ALLEY": "ALY", "ALY": "ALY",
}
DIRECTIONALS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW",
    "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    "N": "N", "S": "S", "E": "E", "W": "W",
    "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW",
}
UNIT_TOKENS = {"UNIT", "APT", "STE", "SUITE", "BLDG", "FL", "FLOOR", "#"}


def normalize_address(raw: str) -> tuple[int | None, str]:
    """Return (house_number, street_key). street_key excludes the number so
    fuzzy matching can slide along the same street."""
    s = norm(raw).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    # King County's ResBldg Address field appends the zip: "6510 14TH AVE NW 98107"
    s = re.sub(r"\s+9[85]\d{3}$", "", s)
    tokens = [t for t in s.split() if t]
    if not tokens:
        return None, ""
    house = None
    rest: list[str] = []
    for i, t in enumerate(tokens):
        if i == 0 and t.isdigit():
            house = int(t)
            continue
        if t in UNIT_TOKENS:
            break  # drop unit designator and everything after
        if t.isdigit() and i > 0 and rest and rest[-1] in UNIT_TOKENS:
            break
        rest.append(t)
    # Strip a single trailing unit letter glued to nothing ("9201 A 3RD AVE" -> drop "A"? No:
    # a lone letter right after the house number is a unit letter, keep street intact.)
    if rest and len(rest[0]) == 1 and rest[0].isalpha() and rest[0] not in DIRECTIONALS and len(rest) > 1:
        rest = rest[1:]
    out: list[str] = []
    for t in rest:
        if t in DIRECTIONALS:
            out.append(DIRECTIONALS[t])
        elif t in SUFFIXES:
            out.append(SUFFIXES[t])
        else:
            out.append(t)
    return house, " ".join(out)


TOWNHOME_WORDS = ["townhome", "townhouse", "rowhouse", "duplex", "triplex",
                  "fourplex", "two-family", "two family", "cottage"]
SFR_WORDS = ["single family", "single-family", "one-family", "one family", "sfr",
             "accessory dwelling", "adu", "dadu", "aadu"]


def refine_category(category: str, description: str, units: int) -> str:
    """Seattle's PermitClass is literally 'Single Family/Duplex', which trips
    the classifier's duplex hint and pushes 1-unit SFRs into the Townhome
    bucket. Re-check against the description alone for single-unit permits."""
    if category != "Townhome / Rowhouse / Duplex" or units > 1:
        return category
    low = f" {norm(description).lower()} "
    if any(w in low for w in TOWNHOME_WORDS):
        return category
    if any(w in low for w in SFR_WORDS):
        return "New SFR / ADU"
    return category


# ------------------------------------------------------------- permit fetch
def load_permit_rows(debug: dict[str, Any], local_csv: str | None) -> list[dict[str, Any]]:
    if local_csv:
        text = Path(local_csv).read_text(encoding="utf-8", errors="replace")
        raw = list(csv.DictReader(io.StringIO(text)))
        debug["permits_source"] = f"local:{local_csv}"
    else:
        r = requests.get(SEATTLE_CSV_URL, timeout=300)
        r.raise_for_status()
        raw = list(csv.DictReader(io.StringIO(r.text)))
        debug["permits_source"] = SEATTLE_CSV_URL
    out = []
    reasons: dict[str, int] = defaultdict(int)
    for row in raw:
        description = norm(pick(row, ["Description"]))
        permit_class = norm(pick(row, ["PermitClass", "PermitClassMapped"]))
        permit_type = norm(pick(row, ["PermitTypeDesc", "PermitTypeMapped"]))
        text = " ".join([permit_class, permit_type, description]).strip()
        category = classify(row, text)
        if category not in SALE_CATEGORIES:
            reasons["not_for_sale_category"] += 1
            continue
        issued = parse_dt(pick(row, ["IssuedDate"]))
        if not issued:
            reasons["missing_issue_date"] += 1
            continue
        completed = parse_dt(pick(row, ["CompletedDate"]))
        status = norm(pick(row, ["StatusCurrent", "Status"]))
        lat = safe_float(pick(row, ["Latitude"]))
        lon = safe_float(pick(row, ["Longitude"]))
        lat, lon, _ = clean_coordinates(lat, lon)
        market, hood = assign_market_neighborhood(lat, lon, norm(pick(row, ["OriginalZip"])))
        known, estimated, suspicious = unit_counts(row, category)
        if suspicious:
            reasons["suspicious_units"] += 1
            continue
        units = known or estimated or 1
        refined = refine_category(category, description, units)
        if refined != category:
            reasons["category_refined_to_sfr"] += 1
            category = refined
        address = norm(pick(row, ["OriginalAddress1", "OriginalAddress"]))
        house, street = normalize_address(address)
        out.append({
            "permit": norm(pick(row, ["PermitNum"])),
            "category": category,
            "units": units,
            "issued": issued,
            "completed": completed,
            "status": status,
            "market": market,
            "neighborhood": hood,
            "address": address,
            "house": house,
            "street": street,
        })
        reasons["kept"] += 1
    debug["permits_examined"] = len(raw)
    debug["permits_kept"] = reasons["kept"]
    debug["permit_drop_reasons"] = dict(reasons)
    debug["permits_with_completion_date"] = sum(1 for p in out if p["completed"])
    return out


# --------------------------------------------------------- assessor loading
# Seattle proper (98146/98168/98177/98178/98133 straddle the city line and are
# kept; the YrBuilt freshness check guards against cross-city collisions).
SEATTLE_ZIPS = {
    "98101", "98102", "98103", "98104", "98105", "98106", "98107", "98108",
    "98109", "98112", "98115", "98116", "98117", "98118", "98119", "98121",
    "98122", "98125", "98126", "98133", "98134", "98136", "98144", "98146",
    "98154", "98164", "98168", "98174", "98177", "98178", "98195", "98199",
}


def load_resbldg(debug: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return street_key -> list of buildings (Seattle zips only)."""
    path = EXTRACT_DIR / "EXTR_ResBldg.csv"
    by_street: dict[str, list[dict[str, Any]]] = defaultdict(list)
    kept = examined = 0
    with path.open(encoding="latin-1", newline="") as f:
        for row in csv.DictReader(f):
            examined += 1
            zipcode = norm(pick(row, ["ZipCode"]))[:5]
            if zipcode not in SEATTLE_ZIPS:
                continue
            # Component columns are cleaner than the Address field (which has
            # the zip glued on). Compose when StreetName exists, else fall back.
            if norm(pick(row, ["StreetName"])):
                parts = [norm(pick(row, [k])) for k in (
                    "BuildingNumber", "DirectionPrefix",
                    "StreetName", "StreetType", "DirectionSuffix")]
                addr = " ".join(p for p in parts if p)
            else:
                addr = norm(pick(row, ["Address"]))
            house, street = normalize_address(addr)
            if house is None or not street:
                continue
            major = norm(pick(row, ["Major"])).zfill(6)
            minor = norm(pick(row, ["Minor"])).zfill(4)
            by_street[street].append({
                "pin": major + minor,
                "house": house,
                "yr_built": to_int(pick(row, ["YrBuilt"])),
                "units": max(1, to_int(pick(row, ["NbrLivingUnits"]))),
            })
            kept += 1
    debug["resbldg_rows_examined"] = examined
    debug["resbldg_rows_kept_seattle"] = kept
    debug["resbldg_streets"] = len(by_street)
    return by_street


def load_sales(debug: dict[str, Any], wanted_pins: set[str]) -> dict[str, list[tuple[datetime, int]]]:
    """Return pin -> sorted list of (document_date, price), market sales only."""
    path = EXTRACT_DIR / "EXTR_RPSale.csv"
    sales: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    examined = kept = 0
    min_price = PARAMS["min_sale_price"]
    with path.open(encoding="latin-1", newline="") as f:
        for row in csv.DictReader(f):
            examined += 1
            major = norm(pick(row, ["Major"])).zfill(6)
            minor = norm(pick(row, ["Minor"])).zfill(4)
            pin = major + minor
            if pin not in wanted_pins:
                continue
            price = to_int(pick(row, ["SalePrice"]))
            if price < min_price:
                continue
            dt = parse_dt(pick(row, ["DocumentDate"]))
            if not dt:
                continue
            sales[pin].append((dt, price))
            kept += 1
    for pin in sales:
        sales[pin].sort()
    debug["sales_rows_examined"] = examined
    debug["sales_rows_kept"] = kept
    debug["pins_with_sales"] = len(sales)
    return sales


# ------------------------------------------------------------------ joining
def match_pins(permit: dict[str, Any], by_street: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], str]:
    """Tier 1: exact house+street. Tier 2: same street/parity within window,
    filtered by YrBuilt near the completion year."""
    street = permit["street"]
    house = permit["house"]
    if house is None or not street or street not in by_street:
        return [], "no_street_match"
    candidates = by_street[street]
    comp_year = permit["completed"].year if permit["completed"] else permit["issued"].year + 1
    tol = PARAMS["yr_built_tolerance"]

    def fresh(b: dict[str, Any]) -> bool:
        return b["yr_built"] == 0 or b["yr_built"] >= comp_year - tol

    exact = [b for b in candidates if b["house"] == house and fresh(b)]
    exact_units = sum(b["units"] for b in exact)
    if exact and exact_units >= permit["units"]:
        return exact, "exact"
    # Townhome fan-out: one permit address, units platted at neighboring
    # numbers (6510 -> 6512, 6514, 6516). Expand along the street, nearest
    # first, same parity, until the permit's unit count is covered.
    win = PARAMS["house_number_window"]
    fuzzy = sorted(
        (b for b in candidates
         if b["house"] != house
         and abs(b["house"] - house) <= win
         and (b["house"] % 2) == (house % 2)
         and b["yr_built"] >= comp_year - tol),  # stricter: require known fresh year
        key=lambda b: abs(b["house"] - house),
    )
    matched = list(exact)
    total = exact_units
    for b in fuzzy:
        if total >= permit["units"]:
            break
        matched.append(b)
        total += b["units"]
    if matched and exact:
        return matched, "exact" if len(matched) == len(exact) else "exact+fanout"
    if matched:
        return matched, "fuzzy"
    return [], "no_pin_match" if candidates else "no_street_match"


def first_sale_after(completion: datetime, pin_sales: list[tuple[datetime, int]]) -> tuple[datetime, int] | None:
    floor = completion - timedelta(days=PARAMS["presale_grace_days"])
    ceiling = completion + timedelta(days=PARAMS["max_days_to_sale"])
    for dt, price in pin_sales:
        if floor <= dt <= ceiling:
            return dt, price
    return None


# ------------------------------------------------------------------ metrics
def median_or_none(vals: list[int]) -> int | None:
    return int(statistics.median(vals)) if vals else None


def p75_or_none(vals: list[int]) -> int | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(0.75 * (len(s) - 1))))]


def status_for(median_days: int | None, months_supply: float | None, trend: int | None, n_sales: int) -> str:
    if n_sales < PARAMS["min_sales_for_signal"]:
        return "insufficient data"
    red = ((median_days is not None and median_days >= PARAMS["red_median_days"])
           or (months_supply is not None and months_supply >= PARAMS["red_months_of_supply"]))
    if red:
        return "red"
    yellow = ((median_days is not None and median_days >= PARAMS["yellow_median_days"])
              or (months_supply is not None and months_supply >= PARAMS["yellow_months_of_supply"])
              or (trend is not None and trend >= PARAMS["yellow_trend_days"]))
    return "yellow" if yellow else "green"


def build_absorption(permits: list[dict[str, Any]],
                     by_street: dict[str, list[dict[str, Any]]],
                     debug: dict[str, Any],
                     now: datetime) -> dict[str, Any]:
    completed = [p for p in permits if p["completed"]]
    pipeline_cutoff = now - timedelta(days=30 * PARAMS["pipeline_window_months"])
    pipeline = [p for p in permits if not p["completed"] and p["issued"] >= pipeline_cutoff]

    # Pass 1: resolve PINs for completed permits.
    match_stats: dict[str, int] = defaultdict(int)
    unit_rows: list[dict[str, Any]] = []   # one row per matched building/unit-group
    wanted_pins: set[str] = set()
    for p in completed:
        pins, how = match_pins(p, by_street)
        match_stats[how] += 1
        for b in pins:
            wanted_pins.add(b["pin"])
            unit_rows.append({"permit": p, "pin": b["pin"], "bldg_units": b["units"]})
    debug["completed_permits"] = len(completed)
    debug["pin_match_stats"] = dict(match_stats)
    debug["distinct_pins_matched"] = len(wanted_pins)

    sales = load_sales(debug, wanted_pins)

    # Pass 2: attach first qualifying sale to each matched building.
    for u in unit_rows:
        hit = first_sale_after(u["permit"]["completed"], sales.get(u["pin"], []))
        if hit:
            sale_dt, price = hit
            u["sale_date"] = sale_dt
            u["price"] = price
            u["days"] = max(0, (sale_dt - u["permit"]["completed"]).days)
            u["presold"] = sale_dt < u["permit"]["completed"]
        else:
            u["sale_date"] = None
    debug["units_matched_to_sale"] = sum(1 for u in unit_rows if u["sale_date"])
    debug["units_no_sale_found"] = sum(1 for u in unit_rows if not u["sale_date"])

    # Aggregate per (market, neighborhood, category) and per (market, category).
    trailing_start = now - timedelta(days=365)
    prior_start = now - timedelta(days=730)
    standing_start = now - timedelta(days=30 * PARAMS["standing_window_months"])

    def keyset(p: dict[str, Any]) -> list[tuple[str, str, str]]:
        keys = [(p["market"], p["market"], p["category"])]
        if p["neighborhood"] and p["neighborhood"] != p["market"]:
            keys.append((p["market"], p["neighborhood"], p["category"]))
        return keys

    buckets: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {
        "trailing_days": [], "prior_days": [], "sold_12mo": 0, "presold": 0,
        "completions_12mo": 0, "standing_unsold": 0, "pipeline_units": 0,
    })

    for u in unit_rows:
        p = u["permit"]
        for k in keyset(p):
            b = buckets[k]
            if u["sale_date"]:
                if u["sale_date"] >= trailing_start:
                    b["sold_12mo"] += 1
                    if u.get("presold"):
                        b["presold"] += 1
                cohort = u["permit"]["completed"]
                if cohort >= trailing_start:
                    b["trailing_days"].append(u["days"])
                elif cohort >= prior_start:
                    b["prior_days"].append(u["days"])
            else:
                if p["completed"] >= standing_start:
                    b["standing_unsold"] += 1

    seen_completed = set()
    for p in completed:
        if p["permit"] in seen_completed:
            continue
        seen_completed.add(p["permit"])
        if p["completed"] >= trailing_start:
            for k in keyset(p):
                buckets[k]["completions_12mo"] += p["units"]

    for p in pipeline:
        for k in keyset(p):
            buckets[k]["pipeline_units"] += p["units"]

    areas = []
    for (market, hood, category), b in sorted(buckets.items()):
        med = median_or_none(b["trailing_days"])
        prior_med = median_or_none(b["prior_days"])
        trend = (med - prior_med) if (med is not None and prior_med is not None) else None
        pace = b["sold_12mo"] / 12.0
        supply_units = b["pipeline_units"] + b["standing_unsold"]
        mos = round(supply_units / pace, 1) if pace > 0 else None
        areas.append({
            "market": market,
            "neighborhood": hood,
            "category": category,
            "median_days_to_sale": med,
            "p75_days_to_sale": p75_or_none(b["trailing_days"]),
            "prior_year_median_days": prior_med,
            "trend_days": trend,
            "sold_last_12mo": b["sold_12mo"],
            "presold": b["presold"],
            "completions_last_12mo": b["completions_12mo"],
            "pipeline_units": b["pipeline_units"],
            "standing_unsold_24mo": b["standing_unsold"],
            "months_of_supply": mos,
            "status": status_for(med, mos, trend, b["sold_12mo"]),
        })

    return {
        "generated_at": now.isoformat(),
        "params": PARAMS,
        "categories": SALE_CATEGORIES,
        "areas": areas,
        "notes": [
            "days_to_sale = King County recorded sale date minus SDCI permit CompletedDate.",
            "Presales (recorded up to grace period before completion) count as 0 days.",
            "months_of_supply = (pipeline + standing unsold) / trailing-12mo sales pace.",
            "standing_unsold includes join failures; check absorption_debug.json match rate before trusting it in thin areas.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--permits-csv", default=None, help="Use a local Seattle permits CSV instead of downloading")
    ap.add_argument("--extract-dir", default=None, help="Override King County extract directory")
    ap.add_argument("--as-of", default=None, help="Override 'now' (YYYY-MM-DD) for reproducible runs")
    args = ap.parse_args()

    global EXTRACT_DIR
    if args.extract_dir:
        EXTRACT_DIR = Path(args.extract_dir)

    for name in ("EXTR_RPSale.csv", "EXTR_ResBldg.csv"):
        if not (EXTRACT_DIR / name).exists():
            print(f"Missing {EXTRACT_DIR / name}")
            print("Download from https://info.kingcounty.gov/assessor/datadownload/default.aspx")
            print("(Real Property Sales + Residential Building zips), unzip into that folder.")
            sys.exit(1)

    now = parse_dt(args.as_of) or datetime.now()
    debug: dict[str, Any] = {"errors": []}

    print("Loading Seattle permits...")
    permits = load_permit_rows(debug, args.permits_csv)
    print(f"  kept {len(permits)} for-sale new-construction permits")

    print("Loading King County residential buildings (Seattle zips)...")
    by_street = load_resbldg(debug)
    print(f"  indexed {debug['resbldg_rows_kept_seattle']} buildings on {debug['resbldg_streets']} streets")

    print("Joining sales and computing absorption...")
    absorption = build_absorption(permits, by_street, debug, now)

    (DATA_DIR / "absorption.json").write_text(json.dumps(absorption, indent=2), encoding="utf-8")
    (DATA_DIR / "absorption_debug.json").write_text(json.dumps(debug, indent=2, default=str), encoding="utf-8")
    print("Wrote", DATA_DIR / "absorption.json")
    print("Wrote", DATA_DIR / "absorption_debug.json")

    matched = debug.get("units_matched_to_sale", 0)
    total = matched + debug.get("units_no_sale_found", 0)
    if total:
        print(f"Sale match rate: {matched}/{total} ({100 * matched / total:.0f}%)")


if __name__ == "__main__":
    main()
