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

SEATTLE_PERMITS_URL = "https://data.seattle.gov/resource/76t5-zqzr.json"
SEATTLE_NEIGHBORHOODS_GEOJSON_CANDIDATES = [
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/nma_nhoods_main/FeatureServer/0/query?where=1%3D1&outFields=L_HOOD%2CS_HOOD_ALT_NAMES&returnGeometry=true&outSR=4326&f=geojson",
    "https://data-seattlecitygis.opendata.arcgis.com/datasets/SeattleCityGIS::neighborhood-map-atlas-neighborhoods.geojson",
]
SEATTLE_NEIGHBORHOODS_URL = "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/nma_nhoods_main/FeatureServer/0"

BELLEVUE_PERMITS_CSV_CANDIDATES = [
    "https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=false",
    "https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true",
    "https://hub.arcgis.com/api/v3/datasets/fc7da7bd29d4493481b17d032e117d09_0/downloads/data?format=csv&spatialRefId=4326",
]
BELLEVUE_NEIGHBORHOOD_CANDIDATES = [
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Neighborhood_Areas/FeatureServer/0",
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Neighborhood_Areas_3/FeatureServer/0",
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/NeighborhoodAreas/FeatureServer/0",
]

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
USER_AGENT = "permit-web-app/9.0"
MIN_YEAR = 2022
MAX_YEAR = 2026

DATA_CACHE: Dict[str, Any] = {
    "loaded_at": 0,
    "permits": [],
    "neighborhoods": {"Seattle": [], "Bellevue": []},
    "errors": [],
}

CATEGORY_NEW_SF = "New SFR"
CATEGORY_NEW_MF = "New MF"
CATEGORY_DEMO = "Demo"
VALID_CATEGORIES = [CATEGORY_NEW_SF, CATEGORY_NEW_MF, CATEGORY_DEMO]


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


def normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def summarize_text(*parts: Any) -> str:
    return " ".join(str(p).strip() for p in parts if p not in (None, "")).lower()


def extract_candidate(row: Dict[str, Any], keywords: Iterable[str]) -> Optional[Any]:
    lowers = {str(k).lower(): v for k, v in row.items()}
    for key, value in lowers.items():
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
        or row.get("lon") or row.get("lng") or row.get("LON") or row.get("X") or row.get("x")
    )

    if lat is None or lon is None:
        for loc_key in ("location", "Location", "LOCATION", "geocoded_column"):
            loc = row.get(loc_key)
            if isinstance(loc, dict):
                lat = lat if lat is not None else try_float(loc.get("latitude") or loc.get("lat"))
                lon = lon if lon is not None else try_float(loc.get("longitude") or loc.get("lon") or loc.get("lng"))
                coords = loc.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    lon = lon if lon is not None else try_float(coords[0])
                    lat = lat if lat is not None else try_float(coords[1])

    # ArcGIS CSVs sometimes include state-plane X/Y in the ~400000/130000 range; don't treat those as lat/lon.
    if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
        return lon, lat
    return None, None


def iter_polygon_rings(geometry: Dict[str, Any]) -> List[List[Tuple[float, float]]]:
    if not geometry:
        return []
    rings: List[List[Tuple[float, float]]] = []
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and isinstance(coords, list):
        for ring in coords:
            pts = []
            if isinstance(ring, list):
                for pt in ring:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pts.append((float(pt[0]), float(pt[1])))
            if pts:
                rings.append(pts)
        return rings
    if gtype == "MultiPolygon" and isinstance(coords, list):
        for poly in coords:
            if isinstance(poly, list):
                for ring in poly:
                    pts = []
                    if isinstance(ring, list):
                        for pt in ring:
                            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                                pts.append((float(pt[0]), float(pt[1])))
                    if pts:
                        rings.append(pts)
        return rings
    esri_rings = geometry.get("rings")
    if isinstance(esri_rings, list):
        for ring in esri_rings:
            pts = []
            if isinstance(ring, list):
                for pt in ring:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pts.append((float(pt[0]), float(pt[1])))
            if pts:
                rings.append(pts)
    return rings


def compute_bbox(rings: List[List[Tuple[float, float]]]) -> Optional[Tuple[float, float, float, float]]:
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_contains(point: Tuple[float, float], rings: List[List[Tuple[float, float]]]) -> bool:
    x, y = point
    inside = False
    for ring in rings:
        if len(ring) < 3:
            continue
        j = len(ring) - 1
        ring_inside = False
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            )
            if intersects:
                ring_inside = not ring_inside
            j = i
        inside = inside or ring_inside
    return inside


def assign_neighborhood(lon: Optional[float], lat: Optional[float], neighborhoods: List[Dict[str, Any]]) -> Optional[str]:
    if lon is None or lat is None:
        return None
    point = (lon, lat)
    for hood in neighborhoods:
        bbox = hood.get("bbox")
        if bbox:
            xmin, ymin, xmax, ymax = bbox
            if lon < xmin or lon > xmax or lat < ymin or lat > ymax:
                continue
        rings = hood.get("rings") or []
        if rings and polygon_contains(point, rings):
            return hood.get("name")
    return None


def classify_permit(text: str) -> Optional[str]:
    text = f" {text.lower()} " if text else ""
    if not text:
        return None
    has_demo = any(k in text for k in [
        " demol", "demolition", " demo ", "teardown", "wrecking", "remove structure", "demo of"
    ])
    has_new = any(k in text for k in [
        " new ", "construct", "construction", "new building", "new residence", "new apartment",
        "new single family", "new multifamily", "building permit - new"
    ])
    has_sf = any(k in text for k in [
        "single family", "single-family", "sfr", "detached house", "new sfr", "single-family residence"
    ])
    has_mf = any(k in text for k in [
        "multifamily", "multi-family", "multi family", "apartment", "townhome",
        "townhouse", "condo", "condominium", "duplex", "triplex", "fourplex",
        "mixed use", "mixed-use", "rowhouse", "apartments", "multi-unit"
    ])
    has_noise = any(k in text for k in [
        "electrical", "mechanical", "plumbing", "side sewer", "reroof", "re-roof",
        "sign", "fence", "tree", "grading only", "land use only", "tenant improvement",
        "sprinkler", "fire alarm", "solar", "water heater", "window replacement",
        "interior alteration", "interior remodel", "repair only", "occupancy only"
    ])

    if has_demo and not any(k in text for k in ["demonstration"]):
        return CATEGORY_DEMO
    if has_noise and not has_new:
        return None
    if has_new and has_mf:
        return CATEGORY_NEW_MF
    if has_new and has_sf:
        return CATEGORY_NEW_SF
    if any(k in text for k in ["townhome", "townhouse", "duplex", "triplex", "fourplex", "apartment", "condo"]):
        return CATEGORY_NEW_MF if not has_demo else CATEGORY_DEMO
    if any(k in text for k in ["single family", "single-family", "sfr"]) and not has_demo:
        return CATEGORY_NEW_SF
    return None


def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    resp = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_text(url: str) -> str:
    resp = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_geojson_url(url: str) -> List[Dict[str, Any]]:
    payload = fetch_json(url)
    feats = payload.get("features") or []
    if not isinstance(feats, list):
        raise RuntimeError("GeoJSON response missing features")
    return feats


def fetch_geojson_from_candidates(candidates: List[str]) -> List[Dict[str, Any]]:
    last_error = None
    for url in candidates:
        try:
            feats = fetch_geojson_url(url)
            if feats:
                return feats
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def fetch_arcgis_features_paged(layer_url: str, where: Optional[str] = None) -> List[Dict[str, Any]]:
    info = fetch_json(layer_url, {"f": "json"})
    max_record_count = int(info.get("maxRecordCount") or 1000)
    oid_field = info.get("objectIdField") or info.get("objectIdFieldName") or "OBJECTID"
    supports_pagination = bool(info.get("advancedQueryCapabilities", {}).get("supportsPagination", False))
    where_clause = where or "1=1"
    base_params = {
        "where": where_clause,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    features: List[Dict[str, Any]] = []

    if supports_pagination:
        offset = 0
        page_size = min(max_record_count, 1000)
        while True:
            payload = fetch_json(f"{layer_url}/query", {
                **base_params,
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
            })
            page = payload.get("features") or []
            features.extend(page)
            exceeded = payload.get("exceededTransferLimit")
            if (not exceeded and len(page) < page_size) or not page:
                break
            offset += page_size
            if offset > 100000:
                break
        return features

    ids_payload = fetch_json(f"{layer_url}/query", {
        "where": where_clause,
        "returnIdsOnly": "true",
        "f": "json",
    })
    object_ids = ids_payload.get("objectIds") or []
    if not object_ids:
        return []
    chunk = min(max_record_count, 250)
    for i in range(0, len(object_ids), chunk):
        subset = object_ids[i:i + chunk]
        payload = fetch_json(f"{layer_url}/query", {
            **base_params,
            "where": f"{oid_field} IN ({','.join(str(x) for x in subset)})",
        })
        features.extend(payload.get("features") or [])
    return features


def normalize_neighborhood_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    name = (
        props.get("L_HOOD")
        or props.get("NAME")
        or props.get("NEIGHBORHOOD")
        or props.get("NEIGHBORHOOD_NAME")
        or props.get("AREA_NAME")
        or props.get("S_HOOD_ALT_NAMES")
        or extract_candidate(props, ["hood", "neighborhood", "area_name", "name"])
    )
    if not name:
        return None
    rings = iter_polygon_rings(geometry)
    if not rings:
        return None
    return {
        "name": normalize_whitespace(str(name)),
        "rings": rings,
        "bbox": compute_bbox(rings),
    }


def normalize_seattle_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lon, lat = extract_lon_lat(row)
    description = normalize_whitespace(str(row.get("description") or ""))
    permit_type = normalize_whitespace(str(row.get("permittype") or row.get("permitclass") or ""))
    permit_class = normalize_whitespace(str(row.get("permitclass") or ""))
    status = normalize_whitespace(str(row.get("statuscurrent") or ""))
    address = normalize_whitespace(str(row.get("originaladdress1") or row.get("address") or ""))
    text = summarize_text(permit_type, permit_class, description, status)
    category = classify_permit(text)
    if not category:
        return None
    hood = row.get("neighborhood") or row.get("neighborhoods") or row.get("atlas_neighborhood")
    return {
        "jurisdiction": "Seattle",
        "permit_id": str(row.get("permitnum") or row.get("permitnumber") or "").strip(),
        "permit_type": permit_type,
        "permit_class": permit_class,
        "description": description,
        "address": address,
        "status": status,
        "intake_date": parse_dt(row.get("applieddate")),
        "issue_date": parse_dt(row.get("issueddate")),
        "longitude": lon,
        "latitude": lat,
        "category": category,
        "neighborhood": normalize_whitespace(str(hood or "")) or None,
        "source": "Seattle Building Permits",
    }


def normalize_bellevue_csv_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lon, lat = extract_lon_lat(row)
    description = normalize_whitespace(str(
        row.get("PERMIT TYPE DESCRIPTION") or row.get("PERMIT_TYPE_DESCRIPTION")
        or row.get("WORK DESCRIPTION") or row.get("WORK_DESCRIPTION")
        or row.get("DESCRIPTION") or row.get("PROJECT DESCRIPTION")
        or row.get("PROJECT_DESCRIPTION") or ""
    ))
    permit_type = normalize_whitespace(str(
        row.get("PERMIT TYPE") or row.get("PERMIT_TYPE")
        or row.get("FOLDER GROUP") or row.get("FOLDER_GROUP")
        or row.get("TYPE") or ""
    ))
    permit_class = normalize_whitespace(str(
        row.get("PROJECT TYPE") or row.get("PROJECT_TYPE")
        or row.get("PERMIT CATEGORY") or row.get("PERMIT_CATEGORY")
        or row.get("SUB TYPE") or row.get("SUB_TYPE") or ""
    ))
    address = normalize_whitespace(str(
        row.get("SITE ADDRESS") or row.get("SITE_ADDRESS")
        or row.get("ADDRESS") or row.get("PROJECT ADDRESS") or row.get("PROJECT_ADDRESS") or ""
    ))
    status = normalize_whitespace(str(row.get("PERMIT STATUS") or row.get("STATUS") or ""))
    neighborhood = normalize_whitespace(str(
        row.get("NEIGHBORHOOD AREA") or row.get("NEIGHBORHOOD_AREA")
        or row.get("NEIGHBORHOOD") or row.get("AREA_NAME") or ""
    )) or None
    permit_id = str(
        row.get("PERMIT NUMBER") or row.get("PERMIT_NUMBER")
        or row.get("PERMITNUM") or row.get("FOLDER NUMBER") or row.get("FOLDER_NUMBER") or ""
    ).strip()
    intake_dt = parse_dt(
        row.get("APPLICATION DATE") or row.get("APPLICATION_DATE") or row.get("APPLIEDDATE")
        or row.get("FILE DATE") or row.get("FILE_DATE") or row.get("NOTICE OF APPLICATION")
    )
    issue_dt = parse_dt(
        row.get("ISSUE DATE") or row.get("ISSUE_DATE") or row.get("ISSUEDDATE")
        or row.get("NOTICE OF DECISION") or row.get("FINAL DATE") or row.get("FINAL_DATE")
    )
    text = summarize_text(
        permit_type,
        permit_class,
        description,
        status,
        row.get("FOLDER GROUP"),
        row.get("PROJECT TYPE"),
        row.get("STRUCTURE TYPE"),
        row.get("CATEGORY"),
        neighborhood,
    )
    category = classify_permit(text)
    if not category:
        return None
    return {
        "jurisdiction": "Bellevue",
        "permit_id": permit_id,
        "permit_type": permit_type,
        "permit_class": permit_class,
        "description": description,
        "address": address,
        "status": status,
        "intake_date": intake_dt,
        "issue_date": issue_dt,
        "longitude": lon,
        "latitude": lat,
        "category": category,
        "neighborhood": neighborhood,
        "source": "Bellevue Permits",
    }


def fetch_seattle_permits() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 5000
    while True:
        params = {
            "$limit": str(limit),
            "$offset": str(offset),
            "$order": "applieddate DESC",
            "$where": "applieddate >= '2022-01-01T00:00:00.000'",
        }
        rows = fetch_json(SEATTLE_PERMITS_URL, params)
        if not isinstance(rows, list):
            raise RuntimeError("Seattle response was not a list")
        for row in rows:
            normalized = normalize_seattle_row(row)
            if normalized:
                year = normalized["intake_date"].year if normalized.get("intake_date") else None
                if year is None or year < MIN_YEAR or year > MAX_YEAR:
                    continue
                out.append(normalized)
        if len(rows) < limit:
            break
        offset += limit
        if offset > 100000:
            break
    return out


def fetch_bellevue_permits() -> List[Dict[str, Any]]:
    last_error = None
    for url in BELLEVUE_PERMITS_CSV_CANDIDATES:
        try:
            text = fetch_text(url)
            reader = csv.DictReader(io.StringIO(text))
            out: List[Dict[str, Any]] = []
            for row in reader:
                normalized = normalize_bellevue_csv_row(row)
                if not normalized:
                    continue
                year = normalized["intake_date"].year if normalized.get("intake_date") else None
                if year is None and normalized.get("issue_date"):
                    year = normalized["issue_date"].year
                if year is None or year < MIN_YEAR or year > MAX_YEAR:
                    continue
                out.append(normalized)
            if out:
                return out
            last_error = RuntimeError("Bellevue CSV loaded but no target permits matched filters")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def fetch_seattle_neighborhoods() -> List[Dict[str, Any]]:
    last_error = None
    for url in SEATTLE_NEIGHBORHOODS_GEOJSON_CANDIDATES:
        try:
            features = fetch_geojson_url(url)
            out = [n for n in (normalize_neighborhood_feature(f) for f in features) if n]
            if out:
                return out
            last_error = RuntimeError("Seattle neighborhood source returned no polygons")
        except Exception as exc:
            last_error = exc
    try:
        features = fetch_arcgis_features_paged(SEATTLE_NEIGHBORHOODS_URL)
        out = [n for n in (normalize_neighborhood_feature(f) for f in features) if n]
        if out:
            return out
    except Exception as exc:
        last_error = exc
    if last_error:
        raise last_error
    return []


def fetch_bellevue_neighborhoods() -> List[Dict[str, Any]]:
    last_error = None
    for candidate in BELLEVUE_NEIGHBORHOOD_CANDIDATES:
        try:
            features = fetch_arcgis_features_paged(candidate)
            out = [n for n in (normalize_neighborhood_feature(f) for f in features) if n]
            if out:
                return out
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def enrich_neighborhoods(records: List[Dict[str, Any]], neighborhoods: Dict[str, List[Dict[str, Any]]]) -> None:
    for row in records:
        if row.get("neighborhood"):
            continue
        hoods = neighborhoods.get(row["jurisdiction"], [])
        row["neighborhood"] = assign_neighborhood(row.get("longitude"), row.get("latitude"), hoods)


def refresh_cache(force: bool = False) -> Dict[str, Any]:
    stale = now_ts() - DATA_CACHE["loaded_at"] > CACHE_TTL_SECONDS
    if not force and DATA_CACHE["loaded_at"] and not stale:
        return DATA_CACHE

    errors: List[str] = []
    neighborhoods: Dict[str, List[Dict[str, Any]]] = {"Seattle": [], "Bellevue": []}
    all_records: List[Dict[str, Any]] = []

    try:
        seattle = fetch_seattle_permits()
        all_records.extend(seattle)
    except Exception as exc:
        errors.append(f"Seattle permits failed: {exc}")

    try:
        bellevue = fetch_bellevue_permits()
        all_records.extend(bellevue)
        if not bellevue:
            errors.append("Bellevue permits loaded zero target records")
    except Exception as exc:
        errors.append(f"Bellevue permits failed: {exc}")

    try:
        neighborhoods["Seattle"] = fetch_seattle_neighborhoods()
        if not neighborhoods["Seattle"]:
            errors.append("Seattle neighborhoods loaded zero polygons")
    except Exception as exc:
        errors.append(f"Seattle neighborhoods failed: {exc}")

    try:
        neighborhoods["Bellevue"] = fetch_bellevue_neighborhoods()
    except Exception as exc:
        # Bellevue can still work from permit row neighborhood field.
        errors.append(f"Bellevue neighborhoods failed: {exc}")

    enrich_neighborhoods(all_records, neighborhoods)

    seattle_unknown = sum(1 for r in all_records if r["jurisdiction"] == "Seattle" and not r.get("neighborhood"))
    seattle_total = sum(1 for r in all_records if r["jurisdiction"] == "Seattle")
    if seattle_total and seattle_unknown == seattle_total:
        errors.append("Seattle neighborhoods loaded but no Seattle permits were spatially assigned")

    DATA_CACHE.update(
        {
            "loaded_at": now_ts(),
            "permits": all_records,
            "neighborhoods": neighborhoods,
            "errors": errors,
        }
    )
    return DATA_CACHE


def row_year(row: Dict[str, Any], date_mode: str) -> Optional[int]:
    key = "issue_date" if date_mode == "issued" else "intake_date"
    dt = row.get(key)
    return dt.year if isinstance(dt, datetime) else None


def serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **row,
        "intake_date": row["intake_date"].date().isoformat() if row.get("intake_date") else None,
        "issue_date": row["issue_date"].date().isoformat() if row.get("issue_date") else None,
        "neighborhood": row.get("neighborhood") or "Unknown",
    }


def filter_rows(rows: List[Dict[str, Any]], args: Dict[str, str]) -> List[Dict[str, Any]]:
    jurisdiction = args.get("jurisdiction", "all")
    category = args.get("category", "all")
    neighborhood = args.get("neighborhood", "all")
    q = (args.get("q") or "").strip().lower()
    date_mode = args.get("date_mode", "intake")
    start_year = int(args.get("start_year") or MIN_YEAR)
    end_year = int(args.get("end_year") or MAX_YEAR)

    out = []
    for row in rows:
        if jurisdiction != "all" and row["jurisdiction"] != jurisdiction:
            continue
        if category != "all" and row["category"] != category:
            continue
        row_neighborhood = row.get("neighborhood") or "Unknown"
        if neighborhood != "all" and row_neighborhood != neighborhood:
            continue
        year = row_year(row, date_mode)
        if year is None or year < start_year or year > end_year:
            continue
        if q:
            hay = summarize_text(
                row.get("permit_id"), row.get("permit_type"), row.get("permit_class"),
                row.get("description"), row.get("address"), row.get("status"), row_neighborhood,
            )
            if q not in hay:
                continue
        out.append(row)
    return out


def compute_summary(rows: List[Dict[str, Any]], date_mode: str) -> Dict[str, Any]:
    years = list(range(MIN_YEAR, MAX_YEAR + 1))
    category_counts = Counter(r["category"] for r in rows)
    by_neighborhood = Counter((r.get("neighborhood") or "Unknown") for r in rows)
    lag_days = []
    annual_counts = {year: 0 for year in years}
    annual_category_counts = {year: {cat: 0 for cat in VALID_CATEGORIES} for year in years}
    neighborhood_year_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: {year: 0 for year in years})

    for row in rows:
        year = row_year(row, date_mode)
        if year in annual_counts:
            annual_counts[year] += 1
            annual_category_counts[year][row["category"]] += 1
            hood = row.get("neighborhood") or "Unknown"
            neighborhood_year_counts[hood][year] += 1
        if row.get("intake_date") and row.get("issue_date"):
            delta = (row["issue_date"] - row["intake_date"]).days
            if 0 <= delta <= 2500:
                lag_days.append(delta)

    top_hoods = by_neighborhood.most_common(12)
    annual_trend = [{"year": y, "count": annual_counts[y], "categories": annual_category_counts[y]} for y in years]
    selected_hood = next((h for h, c in top_hoods if h != "Unknown"), "Unknown")
    neighborhood_breakdown = []
    for hood, count in top_hoods:
        neighborhood_breakdown.append({
            "name": hood,
            "count": count,
            "annual": [{"year": y, "count": neighborhood_year_counts[hood][y]} for y in years],
        })
    return {
        "count": len(rows),
        "avg_lag_days": round(sum(lag_days) / len(lag_days), 1) if lag_days else None,
        "years": years,
        "category_counts": category_counts,
        "top_neighborhoods": top_hoods,
        "annual_trend": annual_trend,
        "neighborhood_breakdown": neighborhood_breakdown,
        "selected_neighborhood": selected_hood,
        "selected_neighborhood_annual": [{"year": y, "count": neighborhood_year_counts[selected_hood][y]} for y in years] if selected_hood in neighborhood_year_counts else [],
    }


@app.route("/")
def index() -> str:
    cache = refresh_cache(force=False)
    neighborhoods = sorted({(r.get("neighborhood") or "Unknown") for r in cache["permits"] if (r.get("neighborhood") or "Unknown") != "Unknown"})
    return render_template(
        "index.html",
        years=list(range(MIN_YEAR, MAX_YEAR + 1)),
        neighborhoods=neighborhoods,
        categories=VALID_CATEGORIES,
        loaded_at=datetime.utcfromtimestamp(cache["loaded_at"]).strftime("%Y-%m-%d %H:%M UTC") if cache["loaded_at"] else "Not loaded",
        errors=cache["errors"],
    )


@app.route("/api/permits")
def api_permits():
    force = request.args.get("refresh") == "1"
    cache = refresh_cache(force=force)
    filtered = filter_rows(cache["permits"], request.args)
    summary = compute_summary(filtered, request.args.get("date_mode", "intake"))
    return jsonify({
        "loaded_at": cache["loaded_at"],
        "errors": cache["errors"],
        "summary": summary,
        "rows": [serialize_row(r) for r in filtered[:25]],
    })


@app.route("/api/meta")
def api_meta():
    cache = refresh_cache(force=False)
    neighborhoods = sorted({(r.get("neighborhood") or "Unknown") for r in cache["permits"] if (r.get("neighborhood") or "Unknown") != "Unknown"})
    return jsonify({
        "years": list(range(MIN_YEAR, MAX_YEAR + 1)),
        "neighborhoods": neighborhoods,
        "categories": VALID_CATEGORIES,
        "errors": cache["errors"],
    })


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
