import csv
import io
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Data sources
SEATTLE_PERMITS_URL = "https://data.seattle.gov/resource/76t5-zqzr.json"
SEATTLE_NEIGHBORHOODS_QUERY_URL = (
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/"
    "nma_nhoods_main/FeatureServer/0/query"
)
BELLEVUE_PERMITS_CSV_CANDIDATES = [
    "https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true",
    "https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=false",
    "https://hub.arcgis.com/api/v3/datasets/fc7da7bd29d4493481b17d032e117d09_0/downloads/data?format=csv&spatialRefId=4326",
]

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "90"))
USER_AGENT = "permit-web-app/10.0"
MIN_YEAR = 2022
MAX_YEAR = 2026
MAX_SAMPLE_ROWS = 15

CATEGORY_NEW_SF = "New SFR"
CATEGORY_NEW_MF = "New MF"
CATEGORY_DEMO = "Demo"
VALID_CATEGORIES = [CATEGORY_NEW_SF, CATEGORY_NEW_MF, CATEGORY_DEMO]

DATA_CACHE: Dict[str, Any] = {
    "loaded_at": 0.0,
    "rows": [],
    "neighborhoods": [],
    "errors": [],
    "stats": {},
    "summary_all": {},
}


def now_ts() -> float:
    return time.time()


def requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


SESSION = requests_session()


def parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)):
        try:
            if value > 10_000_000_000:
                return datetime.utcfromtimestamp(value / 1000)
            return datetime.utcfromtimestamp(value)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in (text, text.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            pass
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S%z",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:32], fmt)
        except Exception:
            pass
    return None


def try_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def normalize_whitespace(text: Any) -> str:
    return " ".join(str(text or "").split())


def summarize_text(*parts: Any) -> str:
    return " ".join(str(p).strip() for p in parts if p not in (None, "")).lower()


def extract_candidate(row: Dict[str, Any], keywords: Iterable[str]) -> Optional[Any]:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key, value in lowered.items():
        if any(token in key for token in keywords):
            return value
    return None


def extract_lon_lat(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    lat = try_float(
        row.get("latitude") or row.get("Latitude") or row.get("LATITUDE")
        or row.get("lat") or row.get("LAT") or row.get("y") or row.get("Y")
    )
    lon = try_float(
        row.get("longitude") or row.get("Longitude") or row.get("LONGITUDE")
        or row.get("lon") or row.get("lng") or row.get("LON") or row.get("x") or row.get("X")
    )

    if lat is None or lon is None:
        for key in ("location", "Location", "LOCATION", "geocoded_column"):
            loc = row.get(key)
            if isinstance(loc, dict):
                lat = lat if lat is not None else try_float(loc.get("latitude") or loc.get("lat"))
                lon = lon if lon is not None else try_float(loc.get("longitude") or loc.get("lng") or loc.get("lon"))
                coords = loc.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    lon = lon if lon is not None else try_float(coords[0])
                    lat = lat if lat is not None else try_float(coords[1])

    if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
        return lon, lat
    return None, None


def point_in_ring(x: float, y: float, ring: List[Tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_contains(point: Tuple[float, float], rings: List[List[Tuple[float, float]]]) -> bool:
    if not rings:
        return False
    x, y = point
    return any(len(ring) >= 3 and point_in_ring(x, y, ring) for ring in rings)


def compute_bbox(rings: List[List[Tuple[float, float]]]) -> Optional[Tuple[float, float, float, float]]:
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def make_row(jurisdiction: str, category: str, permit_id: str, address: str, permit_type: str, description: str,
             status: str, neighborhood: str, intake_dt: Optional[datetime], issue_dt: Optional[datetime],
             latitude: Optional[float], longitude: Optional[float]) -> Dict[str, Any]:
    return {
        "jurisdiction": jurisdiction,
        "category": category,
        "permit_id": normalize_whitespace(permit_id),
        "address": normalize_whitespace(address),
        "permit_type": normalize_whitespace(permit_type),
        "description": normalize_whitespace(description),
        "status": normalize_whitespace(status),
        "neighborhood": normalize_whitespace(neighborhood) or "Unknown",
        "intake_dt": intake_dt,
        "issue_dt": issue_dt,
        "latitude": latitude,
        "longitude": longitude,
    }


def row_sort_dt(row: Dict[str, Any], date_mode: str = "intake") -> datetime:
    dt = row.get("issue_dt") if date_mode == "issued" else row.get("intake_dt")
    if not dt:
        dt = row.get("intake_dt") or row.get("issue_dt") or datetime(1900, 1, 1)
    return dt


def slim_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jurisdiction": row.get("jurisdiction"),
        "category": row.get("category"),
        "permit_id": row.get("permit_id"),
        "address": row.get("address"),
        "permit_type": row.get("permit_type"),
        "description": row.get("description"),
        "status": row.get("status"),
        "neighborhood": row.get("neighborhood"),
        "intake_dt": row.get("intake_dt"),
        "issue_dt": row.get("issue_dt"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
    }


def classify_permit(text: str) -> Optional[str]:
    if not text:
        return None
    text = f" {text.lower()} "

    has_demo = any(k in text for k in [
        " demol", " demolition", " demo ", " teardown", " remove structure", " raze"
    ])
    if has_demo:
        return CATEGORY_DEMO

    has_new = any(k in text for k in [
        " new ", "new construction", "construct", " ground up", "ground-up"
    ])

    has_sf = any(k in text for k in [
        " single family", "single-family", " sfr ", " sf residence", "detached house",
        " residential house", "one-family", "1 family", "single fam"
    ])
    has_mf = any(k in text for k in [
        " multifamily", "multi-family", " multi family", " apartment", " apartments",
        " townhome", " townhouse", " condo", " condominium", " duplex", " triplex",
        " fourplex", " rowhouse", " mixed-use", " mixed use", " adu", " dadu"
    ])

    if has_new and has_sf and not has_mf:
        return CATEGORY_NEW_SF
    if has_new and has_mf:
        return CATEGORY_NEW_MF

    # fallback where permit type already carries the product type but description is sparse
    if has_sf and any(k in text for k in [" permit", " residence", " dwelling"]):
        return CATEGORY_NEW_SF
    if has_mf and any(k in text for k in [" permit", " building", " dwelling"]):
        return CATEGORY_NEW_MF
    return None


def fetch_seattle_neighborhoods() -> List[Dict[str, Any]]:
    resp = SESSION.get(
        SEATTLE_NEIGHBORHOODS_QUERY_URL,
        params={
            "where": "1=1",
            "outFields": "L_HOOD,S_HOOD_ALT_NAMES",
            "returnGeometry": "true",
            "f": "geojson",
            "outSR": 4326,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    out: List[Dict[str, Any]] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        name = normalize_whitespace(props.get("L_HOOD") or props.get("S_HOOD_ALT_NAMES"))
        if not name:
            continue
        rings: List[List[Tuple[float, float]]] = []
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Polygon":
            polys = [coords]
        elif gtype == "MultiPolygon":
            polys = coords
        else:
            polys = []
        for poly in polys:
            for ring in poly:
                pts = []
                for pt in ring:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pts.append((float(pt[0]), float(pt[1])))
                if pts:
                    rings.append(pts)
        bbox = compute_bbox(rings)
        if rings and bbox:
            out.append({"name": name, "rings": rings, "bbox": bbox})
    if not out:
        raise RuntimeError("Seattle neighborhoods returned no polygon features")
    return out


def fetch_seattle_permits(neighborhoods: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    page_size = 2500
    pages = 0
    while True:
        pages += 1
        resp = SESSION.get(
            SEATTLE_PERMITS_URL,
            params={
                "$limit": str(page_size),
                "$offset": str(offset),
                "$order": "applieddate DESC",
                "$select": ",".join([
                    "permitnum", "permitclass", "permittype", "applieddate", "issueddate",
                    "statuscurrent", "originaladdress1", "description", "latitude", "longitude"
                ]),
                "$where": "applieddate >= '2022-01-01T00:00:00.000'",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for src in batch:
            intake = parse_dt(src.get("applieddate"))
            year = intake.year if intake else None
            if year is None or year < MIN_YEAR or year > MAX_YEAR:
                continue
            text_blob = summarize_text(src.get("permitclass"), src.get("permittype"), src.get("description"))
            category = classify_permit(text_blob)
            if not category:
                continue
            lon, lat = extract_lon_lat(src)
            neighborhood = None
            if lon is not None and lat is not None and neighborhoods:
                for hood in neighborhoods:
                    xmin, ymin, xmax, ymax = hood["bbox"]
                    if lon < xmin or lon > xmax or lat < ymin or lat > ymax:
                        continue
                    if polygon_contains((lon, lat), hood["rings"]):
                        neighborhood = hood["name"]
                        break
            rows.append(make_row(
                "Seattle", category, src.get("permitnum"), src.get("originaladdress1"),
                src.get("permittype") or src.get("permitclass"), src.get("description"),
                src.get("statuscurrent"), neighborhood or "Unknown", intake, parse_dt(src.get("issueddate")), lat, lon
            ))
        if len(batch) < page_size:
            break
        offset += page_size
        if pages >= 12:
            break
    return rows, {"pages": pages}

def iter_bellevue_csv_rows() -> Iterable[Dict[str, Any]]:
    last_err = None
    for url in BELLEVUE_PERMITS_CSV_CANDIDATES:
        try:
            with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True) as r:
                r.raise_for_status()
                iterator = (line.decode("utf-8", errors="replace") for line in r.iter_lines() if line)
                reader = csv.DictReader(iterator)
                first = next(reader, None)
                if first is None:
                    continue
                if not any("permit" in str(k).lower() for k in first.keys()):
                    continue
                yield first
                for row in reader:
                    yield row
                return
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"Bellevue permits download failed: {last_err}")


def fetch_bellevue_permits() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    total_seen = 0
    for src in iter_bellevue_csv_rows():
        total_seen += 1
        intake = parse_dt(src.get("APPLIED DATE") or src.get("Applied Date") or src.get("DATE APPLIED") or extract_candidate(src, ["applied"]))
        issue = parse_dt(src.get("ISSUED DATE") or src.get("Issued Date") or src.get("DATE ISSUED") or extract_candidate(src, ["issued"]))
        date_basis = intake or issue
        year = date_basis.year if date_basis else None
        if year is None or year < MIN_YEAR or year > MAX_YEAR:
            continue
        permit_type = src.get("PERMIT TYPE DESCRIPTION") or src.get("PERMIT TYPE") or extract_candidate(src, ["permit type", "type description"])
        subtype = src.get("PROJECT TYPE") or src.get("WORK DESCRIPTION") or src.get("DESCRIPTION") or extract_candidate(src, ["project type", "work description", "description"])
        status = src.get("PERMIT STATUS") or extract_candidate(src, ["status"])
        text_blob = summarize_text(permit_type, subtype, status)
        category = classify_permit(text_blob)
        if not category:
            continue
        lon, lat = extract_lon_lat(src)
        neighborhood = normalize_whitespace(
            src.get("NEIGHBORHOOD AREA") or src.get("Neighborhood Area") or src.get("NEIGHBORHOOD") or extract_candidate(src, ["neighborhood area", "neighborhood"])
        ) or "Unknown"
        rows.append(make_row(
            "Bellevue",
            category,
            src.get("PERMIT NUMBER") or src.get("Permit Number") or extract_candidate(src, ["permit number"]),
            src.get("SITE ADDRESS") or src.get("ADDRESS") or extract_candidate(src, ["site address", "address"]),
            permit_type,
            subtype,
            status,
            neighborhood,
            intake,
            issue,
            lat,
            lon,
        ))
    if not rows:
        raise RuntimeError("Bellevue permits parsed successfully but yielded zero target permits")
    return rows, {"csv_rows_seen": total_seen}

def load_data(force: bool = False) -> Dict[str, Any]:
    cached = DATA_CACHE
    if not force and cached["rows"] and (now_ts() - cached["loaded_at"]) < CACHE_TTL_SECONDS:
        return cached

    errors: List[str] = []
    stats: Dict[str, Any] = {}
    all_rows: List[Dict[str, Any]] = []

    seattle_polys: List[Dict[str, Any]] = []
    try:
        seattle_polys = fetch_seattle_neighborhoods()
        stats["seattle_neighborhoods"] = len(seattle_polys)
    except Exception as exc:
        errors.append(f"Seattle neighborhoods failed: {exc}")

    try:
        seattle_rows, seattle_stats = fetch_seattle_permits(seattle_polys)
        all_rows.extend(seattle_rows)
        stats["Seattle"] = {"permits": len(seattle_rows), **seattle_stats}
    except Exception as exc:
        errors.append(f"Seattle permits failed: {exc}")

    try:
        bellevue_rows, bellevue_stats = fetch_bellevue_permits()
        all_rows.extend(bellevue_rows)
        stats["Bellevue"] = {"permits": len(bellevue_rows), **bellevue_stats}
    except Exception as exc:
        errors.append(f"Bellevue permits failed: {exc}")

    neighborhoods = sorted({row["neighborhood"] for row in all_rows if row.get("neighborhood") and row["neighborhood"] != "Unknown"})
    all_rows.sort(key=lambda r: row_sort_dt(r), reverse=True)
    cached_rows = [slim_row(r) for r in all_rows[:900]]
    summary_all = compute_summary(all_rows, "intake", "all")

    cached.update({
        "loaded_at": now_ts(),
        "rows": cached_rows,
        "neighborhoods": neighborhoods,
        "errors": errors,
        "stats": stats,
        "summary_all": summary_all,
    })
    return cached

def row_in_year_range(row: Dict[str, Any], date_mode: str, start_year: int, end_year: int) -> bool:
    dt = row.get("issue_dt") if date_mode == "issued" else row.get("intake_dt")
    if not dt:
        dt = row.get("intake_dt") or row.get("issue_dt")
    if not dt:
        return False
    return start_year <= dt.year <= end_year


def filter_rows(rows: List[Dict[str, Any]], args: Dict[str, Any]) -> List[Dict[str, Any]]:
    jurisdiction = args.get("jurisdiction", "all")
    category = args.get("category", "all")
    neighborhood = args.get("neighborhood", "all")
    date_mode = args.get("date_mode", "intake")
    q = normalize_whitespace(args.get("q", "")).lower()
    try:
        start_year = int(args.get("start_year") or MIN_YEAR)
        end_year = int(args.get("end_year") or MAX_YEAR)
    except Exception:
        start_year, end_year = MIN_YEAR, MAX_YEAR
    start_year = max(MIN_YEAR, start_year)
    end_year = min(MAX_YEAR, end_year)

    out = []
    for row in rows:
        if jurisdiction != "all" and row["jurisdiction"] != jurisdiction:
            continue
        if category != "all" and row["category"] != category:
            continue
        if neighborhood != "all" and row.get("neighborhood") != neighborhood:
            continue
        if not row_in_year_range(row, date_mode, start_year, end_year):
            continue
        if q:
            blob = summarize_text(
                row.get("permit_id"), row.get("address"), row.get("permit_type"), row.get("description"), row.get("neighborhood")
            )
            if q not in blob:
                continue
        out.append(row)
    return out


def annual_series(rows: List[Dict[str, Any]], date_mode: str) -> List[Dict[str, Any]]:
    base = {y: {"year": y, "count": 0, "categories": {c: 0 for c in VALID_CATEGORIES}} for y in range(MIN_YEAR, MAX_YEAR + 1)}
    for row in rows:
        dt = row.get("issue_dt") if date_mode == "issued" else row.get("intake_dt")
        if not dt:
            dt = row.get("intake_dt") or row.get("issue_dt")
        if not dt:
            continue
        if dt.year not in base:
            continue
        base[dt.year]["count"] += 1
        base[dt.year]["categories"][row["category"]] += 1
    return [base[y] for y in range(MIN_YEAR, MAX_YEAR + 1)]


def compute_summary(rows: List[Dict[str, Any]], date_mode: str, selected_neighborhood: str = "all") -> Dict[str, Any]:
    category_counts = Counter(row["category"] for row in rows)
    lag_values = []
    hood_counts = Counter(row.get("neighborhood") for row in rows if row.get("neighborhood") and row.get("neighborhood") != "Unknown")
    for row in rows:
        intake = row.get("intake_dt")
        issue = row.get("issue_dt")
        if intake and issue:
            lag_values.append((issue - intake).days)

    hood_year_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
    hood_category_counts: Dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        hood = row.get("neighborhood") or "Unknown"
        if hood == "Unknown":
            continue
        dt = row.get("issue_dt") if date_mode == "issued" else row.get("intake_dt")
        if not dt:
            dt = row.get("intake_dt") or row.get("issue_dt")
        if not dt:
            continue
        hood_year_counts[hood][dt.year] += 1
        hood_category_counts[hood][row["category"]] += 1

    neighborhood_breakdown = []
    for hood, years in hood_year_counts.items():
        annual = [{"year": y, "count": years.get(y, 0)} for y in range(MIN_YEAR, MAX_YEAR + 1)]
        neighborhood_breakdown.append({
            "name": hood,
            "count": sum(years.values()),
            "annual": annual,
            "categories": dict(hood_category_counts[hood]),
        })
    neighborhood_breakdown.sort(key=lambda x: (-x["count"], x["name"]))

    if selected_neighborhood != "all":
        selected_name = selected_neighborhood
        selected_series = next((x["annual"] for x in neighborhood_breakdown if x["name"] == selected_name), [])
    else:
        selected_name = neighborhood_breakdown[0]["name"] if neighborhood_breakdown else "Unknown"
        selected_series = neighborhood_breakdown[0]["annual"] if neighborhood_breakdown else []

    return {
        "count": len(rows),
        "avg_lag_days": (sum(lag_values) / len(lag_values)) if lag_values else None,
        "category_counts": dict(category_counts),
        "annual_trend": annual_series(rows, date_mode),
        "top_neighborhoods": hood_counts.most_common(12),
        "neighborhood_breakdown": neighborhood_breakdown[:15],
        "selected_neighborhood": selected_name,
        "selected_neighborhood_annual": selected_series,
    }


def serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jurisdiction": row.get("jurisdiction"),
        "category": row.get("category"),
        "permit_id": row.get("permit_id"),
        "address": row.get("address"),
        "permit_type": row.get("permit_type"),
        "description": row.get("description"),
        "status": row.get("status"),
        "neighborhood": row.get("neighborhood"),
        "intake_date": row.get("intake_dt").strftime("%Y-%m-%d") if row.get("intake_dt") else "",
        "issue_date": row.get("issue_dt").strftime("%Y-%m-%d") if row.get("issue_dt") else "",
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
    }


@app.route("/")
def index():
    cache = load_data(force=False)
    loaded = datetime.utcfromtimestamp(cache["loaded_at"]).strftime("%Y-%m-%d %H:%M UTC") if cache["loaded_at"] else "Not loaded"
    return render_template(
        "index.html",
        loaded_at=loaded,
        errors=cache["errors"],
        categories=VALID_CATEGORIES,
        neighborhoods=cache["neighborhoods"],
        stats=cache.get("stats", {}),
    )


@app.get("/api/meta")
def api_meta():
    cache = load_data(force=(request.args.get("refresh") == "1"))
    return jsonify({
        "neighborhoods": cache["neighborhoods"],
        "categories": VALID_CATEGORIES,
        "stats": cache.get("stats", {}),
        "errors": cache["errors"],
        "loaded_at": cache["loaded_at"],
    })


@app.get("/api/permits")
def api_permits():
    cache = load_data(force=(request.args.get("refresh") == "1"))
    filtered = filter_rows(cache["rows"], request.args)
    date_mode = request.args.get("date_mode", "intake")
    summary = compute_summary(filtered, date_mode, request.args.get("neighborhood", "all"))

    sort_key = (lambda r: r.get("issue_dt") or r.get("intake_dt") or datetime(1900, 1, 1)) if date_mode == "issued" else (lambda r: r.get("intake_dt") or r.get("issue_dt") or datetime(1900, 1, 1))
    sample = sorted(filtered, key=sort_key, reverse=True)[:MAX_SAMPLE_ROWS]

    return jsonify({
        "summary": summary,
        "rows": [serialize_row(r) for r in sample],
        "errors": cache["errors"],
        "sample_row_count": len(sample),
        "total_row_count": len(filtered),
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
