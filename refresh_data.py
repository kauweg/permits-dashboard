from __future__ import annotations

import csv
import io
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

YEARS = {2022, 2023, 2024, 2025, 2026}

SEATTLE_CSV_URL = "https://data.seattle.gov/api/views/76t5-zqzr/rows.csv?accessType=DOWNLOAD"
BELLEVUE_DEFAULT_CSV_URL = (
    "https://hub.arcgis.com/api/download/v1/items/"
    "fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true"
)
BELLEVUE_CSV_URL = os.getenv("BELLEVUE_PERMITS_URL", "").strip() or BELLEVUE_DEFAULT_CSV_URL

# Better market mapping, especially around downtown / core Seattle areas.
MARKET_NAME_MAP = [
    ("Downtown Core", [
        "commercial core",
        "central business district",
        "west edge",
        "denny triangle",
        "belltown",
        "pike-market",
        "waterfront",
    ]),
    ("Pioneer Square / ID", [
        "pioneer square",
        "international district",
        "chinatown",
        "little saigon",
        "stadium district",
        "yesler terrace",
    ]),
    ("First Hill / Capitol Hill", [
        "first hill",
        "capitol hill",
        "pike/pine",
        "broadway",
    ]),
    ("South Lake Union / Eastlake", [
        "south lake union",
        "eastlake",
        "westlake",
        "cascade",
    ]),
    ("Queen Anne / Magnolia", [
        "uptown",
        "lower queen anne",
        "east queen anne",
        "west queen anne",
        "north queen anne",
        "queen anne",
        "lawton park",
        "briarcliff",
        "magnolia",
        "southeast magnolia",
        "interbay",
    ]),
    ("Ballard", [
        "ballard",
        "loyal heights",
        "adams",
        "whittier heights",
        "west woodland",
        "sunset hill",
        "golden gardens",
        "shilshole",
        "crown hill",
    ]),
    ("Fremont / Wallingford", [
        "fremont",
        "wallingford",
        "green lake",
        "phinney ridge",
        "woodland park",
        "northlake",
        "tangletown",
    ]),
    ("University District / Northeast", [
        "university district",
        "university heights",
        "cowen park",
        "roosevelt",
        "ravenna",
        "wedgwood",
        "laurelhurst",
        "bryant",
        "view ridge",
        "windermere",
        "sand point",
        "hawthorne hills",
        "university village",
    ]),
    ("North Seattle", [
        "north beach/blue ridge",
        "broadview",
        "bitter lake",
        "greenwood",
        "haller lake",
        "pinehurst",
        "north college park",
        "olympic view",
        "licton springs",
        "victory heights",
        "matthews beach",
        "meadowbrook",
        "cedar park",
        "northgate",
    ]),
    ("Central Seattle", [
        "central district",
        "madrona",
        "madison park",
        "mann",
        "minor",
        "atlantic",
        "judkins park",
        "squire park",
        "leschi",
        "denny-blaine",
        "colman",
        "garfield",
        "jackson place",
    ]),
    ("Beacon Hill", [
        "north beacon hill",
        "mid-beacon hill",
        "south beacon hill",
        "new holly",
        "holly park",
        "jefferson park",
        "beacon hill",
    ]),
    ("West Seattle", [
        "west seattle",
        "alki",
        "north admiral",
        "fairmount park",
        "genesee",
        "fauntleroy",
        "morgan junction",
        "alaska junction",
        "belvidere",
        "seaview",
        "gatewood",
        "arbor heights",
        "brace point",
        "endolyne",
        "arroyo heights",
        "highland park",
        "north delridge",
        "south delridge",
        "high point",
        "roxhill",
        "westwood",
        "avalon",
        "luna park",
        "pigeon point",
        "delridge",
    ]),
    ("South Seattle", [
        "mount baker",
        "columbia city",
        "seward park",
        "north rainier",
        "brighton",
        "dunlap",
        "rainier beach",
        "rainier view",
        "hillman city",
        "lakewood",
        "columbia heights",
        "lake ridge",
    ]),
    ("Bellevue Downtown", [
        "bellevue downtown",
        "downtown bellevue",
    ]),
    ("Wilburton", ["wilburton"]),
    ("Eastgate", ["eastgate"]),
    ("Crossroads", ["crossroads"]),
    ("Factoria", ["factoria"]),
    ("Bel-Red", ["bel-red", "belred"]),
    ("West Bellevue", ["west bellevue"]),
    ("Bellevue", ["bellevue"]),
]

UNIT_PATTERNS = [
    re.compile(r"(\d{1,4})\s+units?\b", re.I),
    re.compile(r"(\d{1,4})[-\s]+unit\b", re.I),
    re.compile(r"(\d{1,4})\s+apartment", re.I),
    re.compile(r"(\d{1,4})\s+apartments", re.I),
    re.compile(r"(\d{1,4})\s+condo", re.I),
    re.compile(r"(\d{1,4})\s+condominium", re.I),
    re.compile(r"(\d{1,4})\s+townhome", re.I),
    re.compile(r"(\d{1,4})\s+townhouse", re.I),
    re.compile(r"(\d{1,4})\s+dwelling", re.I),
    re.compile(r"(\d{1,4})\s+residential\s+units?", re.I),
]

def normalize(text: Any) -> str:
    return " ".join(str(text or "").replace("\xa0", " ").split())

def pick_first(row: dict[str, Any], keys: list[str]) -> Any:
    lower_map = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and normalize(row.get(key)):
            return row.get(key)
        lk = key.lower()
        if lk in lower_map and normalize(lower_map[lk]):
            return lower_map[lk]
    return None

def parse_dt(value: Any) -> datetime | None:
    s = normalize(value)
    if not s:
        return None

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(s[:26], fmt)
        except Exception:
            continue

    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def short_market_name(name: str) -> str:
    raw = normalize(name).lower()
    if not raw:
        return "Unknown"
    for market, patterns in MARKET_NAME_MAP:
        if any(p in raw for p in patterns):
            return market
    return normalize(name)

def classify(text: str) -> str | None:
    t = f" {normalize(text).lower()} "

    # demo
    if any(k in t for k in [
        " demol", " demolition", " demo ", "teardown", " raze ", "remove structure"
    ]):
        return "Demo"

    # must clearly be new construction
    is_new = any(k in t for k in [
        " new ",
        "new construction",
        "new building",
        "new structure",
        "ground up",
        "construct",
        "construction of",
        "new residence",
        "new apartment",
        "new townhome",
        "new townhouse",
    ])
    if not is_new:
        return None

    is_sf = any(k in t for k in [
        " single family",
        "single-family",
        " sfr ",
        "single family residence",
        "single family dwelling",
        "one-family",
    ])

    is_mf = any(k in t for k in [
        " multifamily",
        "multi-family",
        "multi family",
        " apartment",
        "apartments",
        "condo",
        "condominium",
        "townhome",
        "townhouse",
        "duplex",
        "triplex",
        "fourplex",
        "mixed use",
        "mixed-use",
        "stacked flat",
        "rowhouse",
    ])

    if is_sf and not is_mf:
        return "New SFR"
    if is_mf:
        return "New MF"
    return None

def extract_units(text: str) -> int:
    t = normalize(text)
    if not t:
        return 0
    for pattern in UNIT_PATTERNS:
        m = pattern.search(t)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return 0

def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "NULL"):
            return None
        return float(value)
    except Exception:
        return None

def download_csv_rows(url: str, timeout: int = 120) -> list[dict[str, Any]]:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    text_stream = io.StringIO(r.text)
    reader = csv.DictReader(text_stream)
    return list(reader)

def fetch_seattle_rows(debug: dict[str, Any]) -> list[dict[str, Any]]:
    rows = download_csv_rows(SEATTLE_CSV_URL, timeout=180)
    out: list[dict[str, Any]] = []
    dropped = 0

    for row in rows:
        text = " ".join([
            normalize(pick_first(row, ["permitclass", "permit_class"])),
            normalize(pick_first(row, ["permittype", "permit_type"])),
            normalize(pick_first(row, ["description", "permitdescription", "permitdesc"])),
        ]).strip()

        category = classify(text)
        if not category:
            dropped += 1
            continue

        issue_dt = parse_dt(pick_first(row, ["issueddate", "issuedate", "issue_date"]))
        intake_dt = parse_dt(pick_first(row, ["applicationdate", "application_date"]))
        year_dt = issue_dt or intake_dt
        if not year_dt or year_dt.year not in YEARS:
            continue

        raw_neighborhood = normalize(
            pick_first(row, ["neighborhood", "neighborhoodname", "neighborhood_name"])
        ) or "Unknown"

        market = short_market_name(raw_neighborhood)

        out.append({
            "jurisdiction": "Seattle",
            "market": market,
            "neighborhood": market,  # dashboard filter/group field
            "raw_neighborhood": raw_neighborhood,  # actual neighborhood
            "address": normalize(
                pick_first(row, ["originaladdress1", "address", "siteaddress", "site_address"])
            ),
            "category": category,
            "units": extract_units(text),
            "issue_date": issue_dt.date().isoformat() if issue_dt else "",
            "intake_date": intake_dt.date().isoformat() if intake_dt else "",
            "year": year_dt.year,
            "latitude": safe_float(pick_first(row, ["latitude", "lat"])),
            "longitude": safe_float(pick_first(row, ["longitude", "long", "lng", "lon"])),
            "summary": normalize(text),
        })

    debug["seattle_rows_examined"] = len(rows)
    debug["seattle_rows_kept"] = len(out)
    debug["seattle_rows_dropped"] = dropped
    return out

def fetch_bellevue_rows(debug: dict[str, Any]) -> list[dict[str, Any]]:
    rows = download_csv_rows(BELLEVUE_CSV_URL, timeout=180)
    out: list[dict[str, Any]] = []
    dropped = 0
    columns_seen = set()

    for row in rows:
        columns_seen.update(row.keys())

        text = " ".join([
            normalize(pick_first(row, ["PermitType"])),
            normalize(pick_first(row, ["TypeDetailNames"])),
            normalize(pick_first(row, ["WorkDetail"])),
            normalize(pick_first(row, ["Description"])),
        ]).strip()

        category = classify(text)
        if not category:
            dropped += 1
            continue

        issue_dt = parse_dt(pick_first(row, ["IssueDate", "IssuedDate"]))
        intake_dt = parse_dt(pick_first(row, ["ApplicationDate", "IntakeDate"]))
        year_dt = issue_dt or intake_dt
        if not year_dt or year_dt.year not in YEARS:
            continue

        raw_neighborhood = normalize(
            pick_first(row, ["NeighborhoodNames", "NeighborhoodClusters", "Neighborhood"])
        ) or "Bellevue"

        market = short_market_name(raw_neighborhood)

        out.append({
            "jurisdiction": "Bellevue",
            "market": market,
            "neighborhood": market,
            "raw_neighborhood": raw_neighborhood,
            "address": normalize(
                pick_first(row, ["WorkLocationFullAddress", "Address", "SiteAddress"])
            ),
            "category": category,
            "units": extract_units(text),
            "issue_date": issue_dt.date().isoformat() if issue_dt else "",
            "intake_date": intake_dt.date().isoformat() if intake_dt else "",
            "year": year_dt.year,
            "latitude": safe_float(pick_first(row, ["Latitude", "Lat"])),
            "longitude": safe_float(pick_first(row, ["Longitude", "Lng", "Lon"])),
            "summary": normalize(text),
        })

    debug["bellevue_rows_examined"] = len(rows)
    debug["bellevue_rows_kept"] = len(out)
    debug["bellevue_rows_dropped"] = dropped
    debug["bellevue_columns_seen"] = sorted(columns_seen)
    return out

def build_outputs(rows: list[dict[str, Any]], debug: dict[str, Any]):
    cards = {
        "total_permits": len(rows),
        "seattle_permits": sum(1 for r in rows if r["jurisdiction"] == "Seattle"),
        "bellevue_permits": sum(1 for r in rows if r["jurisdiction"] == "Bellevue"),
        "known_markets": len({r["market"] for r in rows if r["market"] != "Unknown"}),
        "new_sfr": sum(1 for r in rows if r["category"] == "New SFR"),
        "new_mf": sum(1 for r in rows if r["category"] == "New MF"),
        "demo": sum(1 for r in rows if r["category"] == "Demo"),
        "total_units": sum(int(r.get("units") or 0) for r in rows),
    }

    annual_map = {
        y: {"year": y, "New SFR": 0, "New MF": 0, "Demo": 0, "Total": 0, "Units": 0}
        for y in sorted(YEARS)
    }
    for r in rows:
        y = r["year"]
        if y not in annual_map:
            continue
        annual_map[y][r["category"]] += 1
        annual_map[y]["Total"] += 1
        annual_map[y]["Units"] += int(r.get("units") or 0)

    annual_series = [annual_map[y] for y in sorted(annual_map)]

    grouped = {}
    for r in rows:
        market = r["market"]
        if market not in grouped:
            grouped[market] = {
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
                    for y in sorted(YEARS)
                },
                "totals": {"New SFR": 0, "New MF": 0, "Demo": 0, "Total": 0, "Units": 0},
            }

        entry = grouped[market]
        entry["jurisdictions"].add(r["jurisdiction"])

        y = str(r["year"])
        entry["years"][y][r["category"]] += 1
        entry["years"][y]["Total"] += 1
        entry["years"][y]["Units"] += int(r.get("units") or 0)

        entry["totals"][r["category"]] += 1
        entry["totals"]["Total"] += 1
        entry["totals"]["Units"] += int(r.get("units") or 0)

    neighborhood_rows = []
    for entry in grouped.values():
        entry["jurisdictions"] = sorted(entry["jurisdictions"])
        neighborhood_rows.append(entry)

    neighborhood_rows.sort(key=lambda x: (-x["totals"]["Total"], x["neighborhood"]))

    # IMPORTANT: all map points
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": cards,
        "annual_series": annual_series,
        "neighborhood_rows": neighborhood_rows,
        "samples": rows[:100],
        "map_points": rows,
        "load_notes": [
            f"Precomputed refresh generated {len(rows)} target permit rows.",
            f"Seattle kept {debug.get('seattle_rows_kept', 0)} rows out of {debug.get('seattle_rows_examined', 0)} examined.",
            f"Bellevue kept {debug.get('bellevue_rows_kept', 0)} rows out of {debug.get('bellevue_rows_examined', 0)} examined.",
            f"Known markets after refresh: {cards['known_markets']}.",
            f"Total known units: {cards['total_units']}.",
        ],
        "load_errors": debug.get("errors", []),
    }

    meta = {
        "generated_at": summary["generated_at"],
        "markets": sorted({r["market"] for r in rows}),
        "load_notes": summary["load_notes"],
        "load_errors": summary["load_errors"],
    }

    return summary, meta

def main():
    debug: dict[str, Any] = {"errors": []}
    rows: list[dict[str, Any]] = []

    print("Fetching Seattle permits...")
    try:
        rows.extend(fetch_seattle_rows(debug))
    except Exception as e:
        debug["errors"].append(f"Seattle refresh failed: {e}")

    print("Fetching Bellevue permits...")
    try:
        rows.extend(fetch_bellevue_rows(debug))
    except Exception as e:
        debug["errors"].append(f"Bellevue refresh failed: {e}")

    summary, meta = build_outputs(rows, debug)

    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (DATA_DIR / "refresh_debug.json").write_text(json.dumps(debug, indent=2), encoding="utf-8")

    print("Wrote", DATA_DIR / "summary.json")
    print("Wrote", DATA_DIR / "meta.json")
    print("Wrote", DATA_DIR / "refresh_debug.json")

if __name__ == "__main__":
    main()
