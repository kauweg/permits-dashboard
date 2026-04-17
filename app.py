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

MIN_YEAR = 2022
MAX_YEAR = 2026
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '45'))
CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '14400'))
USER_AGENT = 'permit-web-app/10.0'
MAX_SAMPLE_ROWS = 20
MAP_POINT_LIMIT = 150

SEATTLE_PERMITS_URL = 'https://data.seattle.gov/resource/76t5-zqzr.json'
SEATTLE_NEIGHBORHOODS_QUERY = (
    'https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/'
    'nma_nhoods_main/FeatureServer/0/query'
)

BELLEVUE_PERMITS_CSV_CANDIDATES = [
    'https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=false',
    'https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true',
    'https://hub.arcgis.com/api/v3/datasets/fc7da7bd29d4493481b17d032e117d09_0/downloads/data?format=csv&spatialRefId=4326',
]

CATEGORY_NEW_SF = 'New SFR'
CATEGORY_NEW_MF = 'New MF'
CATEGORY_DEMO = 'Demo'
VALID_CATEGORIES = [CATEGORY_NEW_SF, CATEGORY_NEW_MF, CATEGORY_DEMO]

DATA_CACHE: Dict[str, Any] = {
    'loaded_at': 0.0,
    'permits': [],
    'errors': [],
    'source_notes': {},
}


def now_ts() -> float:
    return time.time()


def requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': USER_AGENT})
    return s


SESSION = requests_session()


def parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, '', 'null'):
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
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    for candidate in (text, text.replace(' ', 'T')):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            pass
    for fmt in (
        '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %H:%M',
        '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
        '%Y/%m/%d %H:%M:%S%z', '%Y/%m/%d %H:%M:%S',
    ):
        try:
            return datetime.strptime(text[:32], fmt)
        except Exception:
            pass
    return None


def try_float(value: Any) -> Optional[float]:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except Exception:
        return None


def normalize_whitespace(text: str) -> str:
    return ' '.join((text or '').split())


def summarize_text(*parts: Any) -> str:
    return ' '.join(str(p).strip() for p in parts if p not in (None, '')).lower()


def extract_candidate(row: Dict[str, Any], keywords: Iterable[str]) -> Optional[Any]:
    lowers = {str(k).lower(): v for k, v in row.items()}
    for key, value in lowers.items():
        if any(token in key for token in keywords):
            return value
    return None


def extract_lon_lat(row: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    lat = try_float(
        row.get('latitude') or row.get('Latitude') or row.get('LATITUDE')
        or row.get('lat') or row.get('LAT') or row.get('y') or row.get('Y')
    )
    lon = try_float(
        row.get('longitude') or row.get('Longitude') or row.get('LONGITUDE')
        or row.get('lon') or row.get('lng') or row.get('LON') or row.get('X') or row.get('x')
    )
    if lat is None or lon is None:
        loc = row.get('location') or row.get('Location') or row.get('LOCATION')
        if isinstance(loc, dict):
            lat = lat if lat is not None else try_float(loc.get('latitude') or loc.get('lat'))
            lon = lon if lon is not None else try_float(loc.get('longitude') or loc.get('lon') or loc.get('lng'))
            coords = loc.get('coordinates')
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon = lon if lon is not None else try_float(coords[0])
                lat = lat if lat is not None else try_float(coords[1])
    if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
        return lon, lat
    return None, None


def iter_polygon_rings_from_esri(geometry: Dict[str, Any]) -> List[List[Tuple[float, float]]]:
    rings_out: List[List[Tuple[float, float]]] = []
    rings = geometry.get('rings') if geometry else None
    if not isinstance(rings, list):
        return rings_out
    for ring in rings:
        pts: List[Tuple[float, float]] = []
        if isinstance(ring, list):
            for pt in ring:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    x = try_float(pt[0])
                    y = try_float(pt[1])
                    if x is not None and y is not None:
                        pts.append((x, y))
        if pts:
            rings_out.append(pts)
    return rings_out


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
    for hood in neighborhoods:
        bbox = hood.get('bbox')
        if bbox:
            xmin, ymin, xmax, ymax = bbox
            if lon < xmin or lon > xmax or lat < ymin or lat > ymax:
                continue
        rings = hood.get('rings') or []
        if rings and polygon_contains((lon, lat), rings):
            return hood.get('name')
    return None


def classify_permit(text: str) -> Optional[str]:
    text = f' {text.lower()} ' if text else ''
    has_demo = any(k in text for k in [
        ' demol', 'demolition', 'demo', 'teardown', 'wrecking', 'remove structure', 'demolish'
    ])
    if has_demo:
        return CATEGORY_DEMO

    newish = any(k in text for k in [
        'new', 'new construction', 'construct', 'ground up', 'ground-up', 'new building', 'building permit new'
    ])
    sf = any(k in text for k in [
        'single family', 'single-family', 'sfr', 'detached house', 'residential house', ' sf '])
    mf = any(k in text for k in [
        'multifamily', 'multi-family', 'multi family', 'apartment', 'apartments', 'townhome',
        'townhouse', 'condo', 'condominium', 'duplex', 'triplex', 'fourplex', 'rowhouse',
        'mixed use', 'mixed-use', 'multifam', 'multi unit', 'multi-unit'
    ])

    if newish and sf and not mf:
        return CATEGORY_NEW_SF
    if newish and mf:
        return CATEGORY_NEW_MF
    if ' townhouse ' in text or ' duplex ' in text or ' triplex ' in text or ' apartment ' in text:
        return CATEGORY_NEW_MF
    if ' single family ' in text and ('new' in text or 'construct' in text):
        return CATEGORY_NEW_SF
    return None


def year_in_scope(dt: Optional[datetime]) -> bool:
    return bool(dt and MIN_YEAR <= dt.year <= MAX_YEAR)


def normalize_permit(
    jurisdiction: str,
    permit_id: str,
    category: str,
    status: str,
    address: str,
    neighborhood: Optional[str],
    issue_date: Optional[datetime],
    intake_date: Optional[datetime],
    lon: Optional[float],
    lat: Optional[float],
    raw_text: str,
) -> Dict[str, Any]:
    dt = issue_date or intake_date
    return {
        'jurisdiction': jurisdiction,
        'permit_id': permit_id,
        'category': category,
        'status': normalize_whitespace(status or ''),
        'address': normalize_whitespace(address or ''),
        'neighborhood': normalize_whitespace(neighborhood or '') or 'Unknown',
        'issue_date': issue_date.isoformat() if issue_date else None,
        'intake_date': intake_date.isoformat() if intake_date else None,
        'year': dt.year if dt else None,
        'longitude': lon,
        'latitude': lat,
        'raw_text': raw_text[:500],
    }


def fetch_seattle_target_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    page = 5000
    while True:
        params = {
            '$limit': str(page),
            '$offset': str(offset),
            '$order': 'issueddate DESC',
            '$select': 'permitnum,permitclass,permittype,applieddate,issueddate,statuscurrent,originaladdress1,description,latitude,longitude,location',
            '$where': "applieddate >= '2022-01-01T00:00:00.000'",
        }
        resp = SESSION.get(SEATTLE_PERMITS_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        for r in batch:
            intake = parse_dt(r.get('applieddate'))
            issue = parse_dt(r.get('issueddate'))
            dt = issue or intake
            if not year_in_scope(dt):
                continue
            text = summarize_text(r.get('permittype'), r.get('permitclass'), r.get('description'))
            category = classify_permit(text)
            if not category:
                continue
            lon, lat = extract_lon_lat(r)
            rows.append(normalize_permit(
                jurisdiction='Seattle',
                permit_id=str(r.get('permitnum') or ''),
                category=category,
                status=str(r.get('statuscurrent') or ''),
                address=str(r.get('originaladdress1') or ''),
                neighborhood=None,
                issue_date=issue,
                intake_date=intake,
                lon=lon,
                lat=lat,
                raw_text=text,
            ))
        if len(batch) < page:
            break
        offset += page
        if offset > 60000:
            break
    return rows


def fetch_seattle_neighborhoods() -> List[Dict[str, Any]]:
    params = {
        'where': '1=1',
        'outFields': 'L_HOOD,S_HOOD_ALT_NAMES',
        'returnGeometry': 'true',
        'f': 'json',
        'outSR': '4326',
        'resultRecordCount': '200',
        'returnExceededLimitFeatures': 'true',
        'geometryPrecision': '5',
    }
    resp = SESSION.get(SEATTLE_NEIGHBORHOODS_QUERY, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    features = payload.get('features') or []
    out: List[Dict[str, Any]] = []
    for f in features:
        attrs = f.get('attributes') or {}
        geom = f.get('geometry') or {}
        name = normalize_whitespace(str(attrs.get('L_HOOD') or '').strip())
        if not name:
            continue
        rings = iter_polygon_rings_from_esri(geom)
        if not rings:
            continue
        out.append({'name': name, 'rings': rings, 'bbox': compute_bbox(rings)})
    return out


def stream_bellevue_csv() -> Iterable[Dict[str, str]]:
    last_error = None
    for url in BELLEVUE_PERMITS_CSV_CANDIDATES:
        try:
            with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True, allow_redirects=True) as resp:
                resp.raise_for_status()
                text_stream = io.TextIOWrapper(resp.raw, encoding='utf-8-sig', newline='')
                reader = csv.DictReader(text_stream)
                yielded = False
                for row in reader:
                    yielded = True
                    yield row
                if yielded:
                    return
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise RuntimeError(f'Bellevue permits failed: {last_error}')
    raise RuntimeError('Bellevue permits failed: no candidate CSV produced rows')


def normalize_bellevue_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    permit_id = str(
        row.get('PERMIT NUMBER') or row.get('Permit Number') or row.get('permit_number') or row.get('PERMITNUMBER')
        or extract_candidate(row, ['permit number', 'permitnum']) or ''
    ).strip()
    permit_type = str(
        row.get('PERMIT TYPE DESCRIPTION') or row.get('Permit Type Description') or row.get('PERMIT TYPE')
        or extract_candidate(row, ['permit type']) or ''
    )
    permit_class = str(
        row.get('PERMIT CLASS') or row.get('Permit Class') or extract_candidate(row, ['permit class']) or ''
    )
    description = str(
        row.get('WORK DESCRIPTION') or row.get('Work Description') or row.get('DESCRIPTION')
        or extract_candidate(row, ['description', 'work']) or ''
    )
    neighborhood = str(
        row.get('NEIGHBORHOOD AREA') or row.get('Neighborhood Area') or row.get('NEIGHBORHOOD')
        or extract_candidate(row, ['neighborhood area', 'neighborhood']) or ''
    )
    address = str(
        row.get('SITE ADDRESS') or row.get('Site Address') or row.get('ADDRESS')
        or extract_candidate(row, ['site address', 'address']) or ''
    )
    status = str(
        row.get('STATUS') or row.get('Status') or row.get('PERMIT STATUS') or extract_candidate(row, ['status']) or ''
    )
    intake = parse_dt(
        row.get('APPLICATION DATE') or row.get('Application Date') or row.get('APPLIED DATE')
        or extract_candidate(row, ['application date', 'applied'])
    )
    issue = parse_dt(
        row.get('ISSUE DATE') or row.get('Issue Date') or row.get('ISSUED DATE')
        or extract_candidate(row, ['issue date', 'issued'])
    )
    dt = issue or intake
    if not year_in_scope(dt):
        return None

    lon, lat = extract_lon_lat(row)
    text = summarize_text(permit_type, permit_class, description, status)
    category = classify_permit(text)
    if not category:
        return None
    return normalize_permit(
        jurisdiction='Bellevue',
        permit_id=permit_id,
        category=category,
        status=status,
        address=address,
        neighborhood=neighborhood,
        issue_date=issue,
        intake_date=intake,
        lon=lon,
        lat=lat,
        raw_text=text,
    )


def fetch_bellevue_target_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in stream_bellevue_csv():
        norm = normalize_bellevue_row(raw)
        if norm:
            rows.append(norm)
    if not rows:
        raise RuntimeError('Bellevue permits returned zero filtered rows for 2022-2026 target categories')
    return rows


def enrich_seattle_neighborhoods(rows: List[Dict[str, Any]], neighborhoods: List[Dict[str, Any]]) -> None:
    for row in rows:
        if row['jurisdiction'] != 'Seattle' or row['neighborhood'] != 'Unknown':
            continue
        hood = assign_neighborhood(row.get('longitude'), row.get('latitude'), neighborhoods)
        if hood:
            row['neighborhood'] = hood


def load_data(force: bool = False) -> Dict[str, Any]:
    fresh = (not force and DATA_CACHE['loaded_at'] and now_ts() - DATA_CACHE['loaded_at'] < CACHE_TTL_SECONDS)
    if fresh:
        return DATA_CACHE

    errors: List[str] = []
    notes: Dict[str, str] = {}
    all_rows: List[Dict[str, Any]] = []

    seattle_rows: List[Dict[str, Any]] = []
    try:
        seattle_rows = fetch_seattle_target_rows()
        notes['Seattle permits'] = f'{len(seattle_rows)} filtered target permits'
    except Exception as exc:
        errors.append(f'Seattle permits failed: {exc}')

    if seattle_rows:
        try:
            hoods = fetch_seattle_neighborhoods()
            notes['Seattle neighborhoods'] = f'{len(hoods)} neighborhoods loaded'
            enrich_seattle_neighborhoods(seattle_rows, hoods)
        except Exception as exc:
            errors.append(f'Seattle neighborhoods failed: {exc}')

    all_rows.extend(seattle_rows)

    bellevue_rows: List[Dict[str, Any]] = []
    try:
        bellevue_rows = fetch_bellevue_target_rows()
        notes['Bellevue permits'] = f'{len(bellevue_rows)} filtered target permits'
    except Exception as exc:
        errors.append(f'Bellevue permits failed: {exc}')
    all_rows.extend(bellevue_rows)

    DATA_CACHE.update({
        'loaded_at': now_ts(),
        'permits': all_rows,
        'errors': errors,
        'source_notes': notes,
    })
    return DATA_CACHE


def filter_rows(rows: List[Dict[str, Any]], args: Dict[str, str]) -> List[Dict[str, Any]]:
    jurisdiction = args.get('jurisdiction', 'all')
    category = args.get('category', 'all')
    neighborhood = normalize_whitespace(args.get('neighborhood', 'all'))
    start_year = int(args.get('start_year') or MIN_YEAR)
    end_year = int(args.get('end_year') or MAX_YEAR)

    out = []
    for row in rows:
        year = row.get('year')
        if not year or year < start_year or year > end_year:
            continue
        if jurisdiction != 'all' and row['jurisdiction'] != jurisdiction:
            continue
        if category != 'all' and row['category'] != category:
            continue
        if neighborhood != 'all' and row['neighborhood'] != neighborhood:
            continue
        out.append(row)
    return out


def compute_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    annual_counts: Dict[int, Dict[str, int]] = {}
    for year in range(MIN_YEAR, MAX_YEAR + 1):
        annual_counts[year] = {cat: 0 for cat in VALID_CATEGORIES}

    by_hood_year: Dict[str, Dict[int, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {cat: 0 for cat in VALID_CATEGORIES}))
    by_jurisdiction = Counter()
    by_category = Counter()
    known_neighborhoods = set()

    for row in rows:
        year = row['year']
        category = row['category']
        annual_counts[year][category] += 1
        by_hood_year[row['neighborhood']][year][category] += 1
        by_jurisdiction[row['jurisdiction']] += 1
        by_category[category] += 1
        if row['neighborhood'] and row['neighborhood'] != 'Unknown':
            known_neighborhoods.add(row['neighborhood'])

    annual_series = []
    for year in range(MIN_YEAR, MAX_YEAR + 1):
        rec = {'year': year}
        total = 0
        for cat in VALID_CATEGORIES:
            rec[cat] = annual_counts[year][cat]
            total += annual_counts[year][cat]
        rec['Total'] = total
        annual_series.append(rec)

    neighborhood_rows = []
    for hood, year_map in by_hood_year.items():
        totals = {cat: 0 for cat in VALID_CATEGORIES}
        total = 0
        years = {}
        for year in range(MIN_YEAR, MAX_YEAR + 1):
            yr = year_map.get(year, {cat: 0 for cat in VALID_CATEGORIES})
            subtotal = 0
            years[str(year)] = {cat: int(yr.get(cat, 0)) for cat in VALID_CATEGORIES}
            for cat in VALID_CATEGORIES:
                totals[cat] += int(yr.get(cat, 0))
                subtotal += int(yr.get(cat, 0))
            years[str(year)]['Total'] = subtotal
            total += subtotal
        neighborhood_rows.append({
            'neighborhood': hood,
            'totals': {**totals, 'Total': total},
            'years': years,
        })
    neighborhood_rows.sort(key=lambda r: (-r['totals']['Total'], r['neighborhood']))

    samples = sorted(rows, key=lambda r: (r.get('issue_date') or '', r.get('intake_date') or ''), reverse=True)[:MAX_SAMPLE_ROWS]
    map_points = [
        {'jurisdiction': r['jurisdiction'], 'category': r['category'], 'neighborhood': r['neighborhood'], 'address': r['address'], 'latitude': r['latitude'], 'longitude': r['longitude']}
        for r in rows if r.get('latitude') is not None and r.get('longitude') is not None
    ][:MAP_POINT_LIMIT]

    return {
        'cards': {
            'total_permits': len(rows),
            'seattle_permits': int(by_jurisdiction.get('Seattle', 0)),
            'bellevue_permits': int(by_jurisdiction.get('Bellevue', 0)),
            'known_neighborhoods': len(known_neighborhoods),
            'new_sfr': int(by_category.get(CATEGORY_NEW_SF, 0)),
            'new_mf': int(by_category.get(CATEGORY_NEW_MF, 0)),
            'demo': int(by_category.get(CATEGORY_DEMO, 0)),
        },
        'annual_series': annual_series,
        'neighborhood_rows': neighborhood_rows,
        'samples': samples,
        'map_points': map_points,
        'neighborhoods': sorted(known_neighborhoods),
    }


@app.route('/')
def index():
    return render_template('index.html', years=list(range(MIN_YEAR, MAX_YEAR + 1)), categories=VALID_CATEGORIES)


@app.route('/api/meta')
def api_meta():
    data = load_data()
    rows = data['permits']
    neighborhoods = sorted({r['neighborhood'] for r in rows if r['neighborhood'] and r['neighborhood'] != 'Unknown'})
    return jsonify({
        'years': list(range(MIN_YEAR, MAX_YEAR + 1)),
        'categories': VALID_CATEGORIES,
        'jurisdictions': ['Seattle', 'Bellevue'],
        'neighborhoods': neighborhoods,
        'load_notes': list(data['source_notes'].values()),
        'load_errors': data['errors'],
    })


@app.route('/api/summary')
def api_summary():
    data = load_data(force=request.args.get('refresh') == '1')
    rows = filter_rows(data['permits'], request.args)
    payload = compute_payload(rows)
    payload['load_notes'] = list(data['source_notes'].values())
    payload['load_errors'] = data['errors']
    payload['filters'] = {
        'jurisdiction': request.args.get('jurisdiction', 'all'),
        'category': request.args.get('category', 'all'),
        'neighborhood': request.args.get('neighborhood', 'all'),
        'start_year': int(request.args.get('start_year') or MIN_YEAR),
        'end_year': int(request.args.get('end_year') or MAX_YEAR),
    }
    return jsonify(payload)


@app.route('/healthz')
def healthz():
    return 'ok', 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=True)
