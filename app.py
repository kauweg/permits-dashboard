import os
import time
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

SEATTLE_PERMITS_URL = "https://data.seattle.gov/resource/76t5-zqzr.json"
SEATTLE_NEIGHBORHOODS_URL = "https://data.seattle.gov/resource/w3qt-9btr.geojson?$limit=5000"

BELLEVUE_PERMITS_LAYER = "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Building_Permits/FeatureServer/0"
BELLEVUE_NEIGHBORHOOD_CANDIDATES = [
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Neighborhood_Areas/FeatureServer/0",
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/NeighborhoodAreas/FeatureServer/0",
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/Neighborhood_Areas_3/FeatureServer/0",
    "https://services6.arcgis.com/ONZht79c8QWuX759/arcgis/rest/services/COBGIS_Neighborhood_Areas/FeatureServer/0",
]

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "45"))
USER_AGENT = "permit-web-app/4.0"

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
            # ArcGIS often sends epoch ms.
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
    ):
        try:
            return datetime.strptime(text[:26], fmt)
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


def extract_lon_lat(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    lat = try_float(row.get("latitude") or row.get("Latitude") or row.get("LATITUDE") or row.get("y") or row.get("Y"))
    lon = try_float(row.get("longitude") or row.get("Longitude") or row.get("LONGITUDE") or row.get("x") or row.get("X"))

    if lat is None or lon is None:
        loc = row.get("location") or row.get("Location") or row.get("LOCATION")
        if isinstance(loc, dict):
            lat = lat if lat is not None else try_float(loc.get("latitude") or loc.get("lat"))
            lon = lon if lon is not None else try_float(loc.get("longitude") or loc.get("lon") or loc.get("lng"))
            coords = loc.get("coordinates")
            if (lat is None or lon is None) and isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon = lon if lon is not None else try_float(coords[0])
                lat = lat if lat is not None else try_float(coords[1])

    if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
        return lon, lat
    return None, None


def summarize_text(*parts: Any) -> str:
    return " ".join(str(p).strip() for p in parts if p not in (None, "")).lower()


def normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


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


def iter_polygon_rings(geometry: Dict[str, Any]) -> List[List[Tuple[float, float]]]:
    if not geometry:
        return []
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    rings: List[List[Tuple[float, float]]] = []
    if gtype == "Polygon" and isinstance(coords, list):
        for ring in coords:
            if isinstance(ring, list):
                rings.append([(float(x), float(y)) for x, y in ring if len([x, y]) == 2])
    elif gtype == "MultiPolygon" and isinstance(coords, list):
        for poly in coords:
            if isinstance(poly, list):
                for ring in poly:
                    if isinstance(ring, list):
                        rings.append([(float(x), float(y)) for x, y in ring if len([x, y]) == 2])
    return rings


def geometry_centroid(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    rings = iter_polygon_rings(geometry)
    pts = [pt for ring in rings for pt in ring]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def assign_neighborhood(lon: Optional[float], lat: Optional[float], jurisdiction: str, neighborhoods: List[Dict[str, Any]]) -> Optional[str]:
    if lon is None or lat is None:
        return None
    point = (lon, lat)
    for hood in neighborhoods:
        rings = hood.get("rings") or []
        if rings and polygon_contains(point, rings):
            return hood.get("name")
    return None


def extract_candidate(row: Dict[str, Any], keywords: Iterable[str]) -> Optional[Any]:
    lowers = {str(k).lower(): v for k, v in row.items()}
    for key, value in lowers.items():
        if any(token in key for token in keywords):
            return value
    return None


def classify_permit(text: str) -> Optional[str]:
    text = text.lower()
    if not text:
        return None

    has_demo = any(k in text for k in [" demol", "demolition", "teardown", "wrecking", "remove structure"])
    has_new = any(k in text for k in ["new", "construct", "construction", "building"])
    has_sf = any(k in text for k in ["single family", "single-family", "sfr", "residential house", "detached house"])
    has_mf = any(k in text for k in ["multifamily", "multi-family", "apartment", "townhome", "townhouse", "condo", "condominium", "duplex", "triplex", "fourplex", "mixed use", "mixed-use"])
    has_noise = any(k in text for k in [
        "electrical", "mechanical", "plumbing", "side sewer", "reroof", "re-roof",
        "sign", "fence", "tree", "grading only", "land use only", "tenant improvement",
        "ti only", "sprinkler", "fire alarm", "solar", "water heater", "window replacement",
        "interior alteration", "interior remodel", "kitchen remodel", "roof", "repair"
    ])

    if has_demo and not any(k in text for k in ["demo for event", "demonstration"]):
        return CATEGORY_DEMO
    if has_noise and not has_new:
        return None
    if has_new and has_mf:
        return CATEGORY_NEW_MF
    if has_new and has_sf:
        return CATEGORY_NEW_SF

    # Bellevue and Seattle descriptions can be terse. Use fallback patterns.
    if any(k in text for k in ["townhome", "townhouse", "duplex", "triplex", "fourplex", "apartment"]):
        return CATEGORY_NEW_MF if not has_demo else CATEGORY_DEMO
    if any(k in text for k in ["single family", "single-family", "sfr"]) and not has_demo:
        return CATEGORY_NEW_SF
    return None


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


def normalize_bellevue_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties") or feature.get("attributes") or feature
    geometry = feature.get("geometry") or {}
    lon = lat = None
    if geometry.get("type") == "Point":
        coords = geometry.get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = try_float(coords[0]), try_float(coords[1])
    if lon is None or lat is None:
        lon, lat = extract_lon_lat(props)
    description = normalize_whitespace(str(
        props.get("PERMITTYPEDESCRIPTION")
        or props.get("PERMIT_TYPE_DESCRIPTION")
        or props.get("DESCRIPTION")
        or props.get("description")
        or ""
    ))
    permit_type = normalize_whitespace(str(
        props.get("PERMITTYPE")
        or props.get("PERMIT_TYPE")
        or props.get("TYPE")
        or props.get("type")
        or ""
    ))
    permit_class = normalize_whitespace(str(
        props.get("PERMITCATEGORY")
        or props.get("PERMIT_CATEGORY")
        or props.get("CATEGORY")
        or props.get("category")
        or ""
    ))
    structure = normalize_whitespace(str(
        props.get("STRUCTURETYPE")
        or props.get("STRUCTURE_TYPE")
        or props.get("STRUCTURE")
        or props.get("structure")
        or ""
    ))
    work_class = normalize_whitespace(str(
        props.get("WORKCLASS")
        or props.get("WORK_CLASS")
        or props.get("WORKTYPE")
        or props.get("WORK_TYPE")
        or ""
    ))
    address = normalize_whitespace(str(
        props.get("SITEADDRESS")
        or props.get("SITE_ADDRESS")
        or props.get("ADDRESS")
        or props.get("FULLADDRESS")
        or ""
    ))
    status = normalize_whitespace(str(
        props.get("PERMITSTATUS")
        or props.get("STATUS")
        or props.get("status")
        or ""
    ))
    text = summarize_text(permit_type, permit_class, description, structure, work_class, status)
    category = classify_permit(text)
    if not category:
        return None
    hood = props.get("NEIGHBORHOOD") or props.get("NEIGHBORHOODNAME") or props.get("COMMUNITY") or extract_candidate(props, ["neighborhood", "community"])
    permit_id = (
        props.get("PERMITNUMBER")
        or props.get("PERMIT_NUMBER")
        or props.get("permit_number")
        or props.get("PERMITNUM")
        or props.get("PermitNumber")
        or ""
    )
    return {
        "jurisdiction": "Bellevue",
        "permit_id": str(permit_id).strip(),
        "permit_type": permit_type,
        "permit_class": permit_class,
        "description": description,
        "address": address,
        "status": status,
        "intake_date": parse_dt(
            props.get("APPLICATIONDATE")
            or props.get("APPLIEDDATE")
            or props.get("APPLICATION_DATE")
            or props.get("SubmittedDate")
        ),
        "issue_date": parse_dt(
            props.get("ISSUEDDATE")
            or props.get("ISSUE_DATE")
            or props.get("IssuedDate")
        ),
        "longitude": lon,
        "latitude": lat,
        "category": category,
        "neighborhood": normalize_whitespace(str(hood or "")) or None,
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
            "$where": "applieddate >= '2019-01-01T00:00:00.000'",
        }
        resp = SESSION.get(SEATTLE_PERMITS_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            raise RuntimeError("Seattle response was not a list")
        for row in rows:
            normalized = normalize_seattle_row(row)
            if normalized:
                out.append(normalized)
        if len(rows) < limit:
            break
        offset += limit
        if offset > 100000:
            break
    return out


def fetch_arcgis_geojson_paged(layer_url: str) -> List[Dict[str, Any]]:
    meta = SESSION.get(layer_url, params={"f": "json"}, timeout=REQUEST_TIMEOUT)
    meta.raise_for_status()
    info = meta.json()
    max_record_count = int(info.get("maxRecordCount") or 1000)
    oid_field = info.get("objectIdField") or info.get("objectIdFieldName") or info.get("fields", [{}])[0].get("name")
    supports_pagination = bool(info.get("advancedQueryCapabilities", {}).get("supportsPagination", False))

    features: List[Dict[str, Any]] = []

    if supports_pagination:
        offset = 0
        page_size = min(max_record_count, 2000)
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
            }
            resp = SESSION.get(f"{layer_url}/query", params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("features") or []
            features.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
            if offset > 250000:
                break
        return features

    # Fallback for services that do not paginate cleanly: get object IDs then chunk.
    ids_resp = SESSION.get(
        f"{layer_url}/query",
        params={"where": "1=1", "returnIdsOnly": "true", "f": "json"},
        timeout=REQUEST_TIMEOUT,
    )
    ids_resp.raise_for_status()
    ids_payload = ids_resp.json()
    object_ids = ids_payload.get("objectIds") or []
    if not object_ids:
        return []
    chunk = 500
    for i in range(0, len(object_ids), chunk):
        subset = object_ids[i : i + chunk]
        where = f"{oid_field} IN ({','.join(str(x) for x in subset)})"
        resp = SESSION.get(
            f"{layer_url}/query",
            params={
                "where": where,
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        features.extend(payload.get("features") or [])
    return features


def fetch_bellevue_permits() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    features = fetch_arcgis_geojson_paged(BELLEVUE_PERMITS_LAYER)
    for feature in features:
        normalized = normalize_bellevue_feature(feature)
        if normalized:
            out.append(normalized)
    return out


def fetch_seattle_neighborhoods() -> List[Dict[str, Any]]:
    resp = SESSION.get(SEATTLE_NEIGHBORHOODS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    features = payload.get("features") or []
    out = []
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        name = props.get("name") or props.get("L_HOOD") or props.get("S_HOOD") or extract_candidate(props, ["hood", "neigh"])
        if not name:
            continue
        rings = iter_polygon_rings(geometry)
        if not rings:
            continue
        out.append({"name": str(name).strip(), "rings": rings})
    return out


def fetch_bellevue_neighborhoods() -> List[Dict[str, Any]]:
    last_error = None
    for candidate in BELLEVUE_NEIGHBORHOOD_CANDIDATES:
        try:
            features = fetch_arcgis_geojson_paged(candidate)
            out = []
            for feature in features:
                props = feature.get("properties") or feature.get("attributes") or {}
                geometry = feature.get("geometry") or {}
                name = (
                    props.get("NAME")
                    or props.get("NEIGHBORHOOD")
                    or props.get("NEIGHBORHOOD_NAME")
                    or props.get("AREA_NAME")
                    or extract_candidate(props, ["name", "neighborhood"])
                )
                if not name:
                    continue
                rings = iter_polygon_rings(geometry)
                if not rings:
                    continue
                out.append({"name": str(name).strip(), "rings": rings})
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
        row["neighborhood"] = assign_neighborhood(row.get("longitude"), row.get("latitude"), row["jurisdiction"], hoods)


def refresh_cache(force: bool = False) -> Dict[str, Any]:
    stale = now_ts() - DATA_CACHE["loaded_at"] > CACHE_TTL_SECONDS
    if not force and DATA_CACHE["loaded_at"] and not stale:
        return DATA_CACHE

    errors = []
    neighborhoods: Dict[str, List[Dict[str, Any]]] = {"Seattle": [], "Bellevue": []}
    all_records: List[Dict[str, Any]] = []

    try:
        all_records.extend(fetch_seattle_permits())
    except Exception as exc:
        errors.append(f"Seattle permits failed: {exc}")

    try:
        all_records.extend(fetch_bellevue_permits())
    except Exception as exc:
        errors.append(f"Bellevue permits failed: {exc}")

    try:
        neighborhoods["Seattle"] = fetch_seattle_neighborhoods()
    except Exception as exc:
        errors.append(f"Seattle neighborhoods failed: {exc}")

    try:
        neighborhoods["Bellevue"] = fetch_bellevue_neighborhoods()
    except Exception as exc:
        errors.append(f"Bellevue neighborhoods failed: {exc}")

    enrich_neighborhoods(all_records, neighborhoods)

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
    }


def filter_rows(rows: List[Dict[str, Any]], args: Dict[str, str]) -> List[Dict[str, Any]]:
    jurisdiction = args.get("jurisdiction", "all")
    category = args.get("category", "all")
    neighborhood = args.get("neighborhood", "all")
    q = (args.get("q") or "").strip().lower()
    date_mode = args.get("date_mode", "intake")
    start_year = int(args.get("start_year") or 2019)
    end_year = int(args.get("end_year") or datetime.utcnow().year)

    out = []
    for row in rows:
        if jurisdiction != "all" and row["jurisdiction"] != jurisdiction:
            continue
        if category != "all" and row["category"] != category:
            continue
        if neighborhood != "all" and (row.get("neighborhood") or "Unknown") != neighborhood:
            continue
        year = row_year(row, date_mode)
        if year is None or year < start_year or year > end_year:
            continue
        if q:
            hay = summarize_text(
                row.get("permit_id"),
                row.get("permit_type"),
                row.get("permit_class"),
                row.get("description"),
                row.get("address"),
                row.get("status"),
                row.get("neighborhood"),
            )
            if q not in hay:
                continue
        out.append(row)
    return out


def compute_summary(rows: List[Dict[str, Any]], date_mode: str) -> Dict[str, Any]:
    years = sorted({row_year(r, date_mode) for r in rows if row_year(r, date_mode) is not None})
    category_counts = Counter(r["category"] for r in rows)
    by_neighborhood = Counter((r.get("neighborhood") or "Unknown") for r in rows)

    lag_days = []
    for row in rows:
        if row.get("intake_date") and row.get("issue_date"):
            delta = (row["issue_date"] - row["intake_date"]).days
            if 0 <= delta <= 2500:
                lag_days.append(delta)

    return {
        "count": len(rows),
        "avg_lag_days": round(sum(lag_days) / len(lag_days), 1) if lag_days else None,
        "years": years,
        "category_counts": category_counts,
        "top_neighborhoods": by_neighborhood.most_common(20),
    }


@app.route("/")
def index() -> str:
    cache = refresh_cache(force=False)
    rows = cache["permits"]
    years = sorted({row_year(r, "intake") for r in rows if row_year(r, "intake") is not None})
    neighborhoods = sorted({(r.get("neighborhood") or "Unknown") for r in rows})
    return render_template(
        "index.html",
        years=years,
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
    return jsonify(
        {
            "loaded_at": cache["loaded_at"],
            "errors": cache["errors"],
            "summary": summary,
            "rows": [serialize_row(r) for r in filtered[:1500]],
        }
    )


@app.route("/api/meta")
def api_meta():
    cache = refresh_cache(force=False)
    rows = cache["permits"]
    years = sorted({row_year(r, "intake") for r in rows if row_year(r, "intake") is not None})
    neighborhoods = sorted({(r.get("neighborhood") or "Unknown") for r in rows})
    return jsonify(
        {
            "years": years,
            "neighborhoods": neighborhoods,
            "categories": VALID_CATEGORIES,
            "errors": cache["errors"],
        }
    )


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
