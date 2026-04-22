"""Refresh precomputed permit dashboard data.

Run locally, then commit the generated data/*.json files.
This keeps Render startup instant while still allowing fresh civic-data pulls.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)

YEARS = [2022, 2023, 2024, 2025, 2026]
VALID_CATEGORIES = ['New SFR', 'New MF', 'Other New', 'Demo']
SEATTLE_PERMITS_URL = 'https://data.seattle.gov/resource/76t5-zqzr.json'
SEATTLE_NEIGHBORHOODS_URL = (
    'https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/'
    'nma_nhoods_main/FeatureServer/0/query'
)
BELLEVUE_PERMITS_CSV_FALLBACKS = [
    os.getenv('BELLEVUE_PERMITS_URL', '').strip(),
    'https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true',
]
REQUEST_TIMEOUT = 120
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'permit-dashboard-precompute/20.0'})

SEATTLE_ROLLUPS = {
    'West Seattle': {'admiral', 'alki', 'arbor heights', 'delridge', 'fairmount park', 'fauntleroy', 'gatewood', 'genesee', 'high point', 'highland park', 'junction', 'morgan junction', 'north delridge', 'south delridge', 'roxhill', 'seaview', 'west seattle', 'north admiral', 'sunset hill west seattle'},
    'Ballard': {'ballard', 'sunset hill', 'whittier heights', 'crown hill', 'loyal heights', 'adams', 'gilman park'},
    'Capitol Hill': {'capitol hill', 'north capitol hill', 'montlake', 'madison valley', 'eastlake', 'broadway'},
    'Queen Anne': {'queen anne', 'east queen anne', 'lower queen anne', 'west queen anne', 'north queen anne', 'uptown'},
    'Wallingford': {'wallingford', 'fremont', 'east fremont', 'westlake'},
    'Central District': {'central district', 'minor', 'madison park', 'madrona', 'mann', 'leschi'},
    'Beacon Hill': {'beacon hill', 'north beacon hill', 'mid beacon hill', 'south beacon hill', 'north beacon hill'},
    'Magnolia': {'magnolia', 'discovery park'},
    'Green Lake': {'green lake', 'phinney ridge', 'greenwood', 'woodland'},
    'Roosevelt': {'roosevelt', 'ravenna', 'wedgwood', 'view ridge', 'university district', 'laurelhurst', 'bryant', 'maple leaf'},
    'Georgetown / South Park': {'georgetown', 'south park'},
    'Rainier Valley': {'columbia city', 'mount baker', 'rainier beach', 'rainier view', 'seward park', 'brighton', 'hillman city', 'north rainier', 'oakhurst', 'genesee park'},
}

BELLEVUE_ROLLUPS = {
    'Bellevue Downtown': {'bellevue downtown', 'downtown', 'old bellevue'},
    'BelRed': {'belred', 'bel-red', 'spring district'},
    'Eastgate': {'eastgate'},
    'Factoria': {'factoria'},
    'Wilburton': {'wilburton'},
    'Crossroads': {'crossroads'},
    'West Bellevue': {'west bellevue', 'meydenbauer', 'enatai'},
    'Lake Hills': {'lake hills', 'lakehills'},
    'Newport': {'newport', 'newport hills'},
    'Somerset': {'somerset'},
    'Bridle Trails': {'bridle trails'},
    'Lakemont / Cougar Mountain': {'lakemont', 'cougar mountain'},
}


def parse_dt(value: Any):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    candidates = [text, text.replace(' ', 'T')]
    fmts = (
        '%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %I:%M:%S %p'
    )
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            pass
    for fmt in fmts:
        try:
            return datetime.strptime(text[:26], fmt)
        except Exception:
            pass
    return None


def normalize(text: Any) -> str:
    return ' '.join(str(text or '').replace('\xa0', ' ').split())


def norm_key(text: Any) -> str:
    return normalize(text).lower().replace('_', ' ').strip()


def clean_neighborhood(text: Any) -> str:
    value = normalize(text)
    if not value:
        return 'Unknown'
    low = value.lower()
    if low in {'na', 'n/a', 'none', 'null', 'unknown'}:
        return 'Unknown'
    return value


def normalize_seattle_neighborhood(name: Any) -> str:
    raw = clean_neighborhood(name)
    if raw == 'Unknown':
        return raw
    low = raw.lower()
    for rollup, aliases in SEATTLE_ROLLUPS.items():
        if low == rollup.lower() or low in aliases:
            return rollup
    return raw.title() if raw.islower() else raw


def normalize_bellevue_neighborhood(name: Any) -> str:
    raw = clean_neighborhood(name)
    if raw == 'Unknown':
        return raw
    low = raw.lower()
    for rollup, aliases in BELLEVUE_ROLLUPS.items():
        if low == rollup.lower() or low in aliases:
            return rollup
    return raw.title() if raw.islower() else raw


def classify(text: str):
    t = f" {normalize(text).lower()} "
    is_demo = any(k in t for k in [' demol', ' demolition', ' demo ', ' teardown', ' raze', ' remove structure', 'deconstruct'])
    if is_demo:
        return 'Demo'

    new_markers = [
        ' new ', 'new construction', 'ground up', 'construct', 'new bldg', 'new building',
        'new res', 'new residence', 'new single family', 'new multifamily', 'new apartment',
        'new townhome', 'new townhouse', 'erect', 'proposed new', 'new mixed use', 'new mixed-use',
        'construct new', 'construction of new', 'new structure', 'new commercial shell'
    ]
    has_new = any(k in t for k in new_markers)
    if not has_new:
        return None

    has_sf = any(k in t for k in [' single family', 'single-family', ' sfr ', 'detached', 'one-family', 'single family residence', 'one unit', '1 unit'])
    has_mf = any(k in t for k in [
        ' multifamily', 'multi-family', 'multi family', ' apartment', 'apartments', 'townhome',
        'townhouse', 'condo', 'condominium', 'duplex', 'triplex', 'fourplex', 'mixed use', 'mixed-use',
        'rowhouse', 'live/work', 'stacked flat', 'multi unit', '5 unit', '6 unit', '7 unit', '8 unit',
        '9 unit', '10 unit', '11 unit', '12 unit', '13 unit', '14 unit', '15 unit'
    ])
    if has_sf and not has_mf:
        return 'New SFR'
    if has_mf:
        return 'New MF'
    return 'Other New'


def extract_point(row: dict[str, Any]):
    lat_keys = ['latitude', 'lat', 'y']
    lon_keys = ['longitude', 'lon', 'lng', 'x']
    for la in lat_keys:
        for lo in lon_keys:
            if row.get(la) not in (None, '') and row.get(lo) not in (None, ''):
                try:
                    return float(row[lo]), float(row[la])
                except Exception:
                    pass
    loc = row.get('location') or row.get('point') or row.get('coordinates')
    if isinstance(loc, dict):
        coords = loc.get('coordinates')
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                return float(coords[0]), float(coords[1])
            except Exception:
                pass
        try:
            if loc.get('longitude') and loc.get('latitude'):
                return float(loc['longitude']), float(loc['latitude'])
        except Exception:
            pass
    return None


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, rings: list[list[list[float]]]) -> bool:
    if not rings:
        return False
    if not point_in_ring(x, y, rings[0]):
        return False
    for hole in rings[1:]:
        if point_in_ring(x, y, hole):
            return False
    return True


def fetch_seattle_neighborhoods():
    params = {
        'where': '1=1',
        'outFields': 'L_HOOD,S_HOOD_ALT_NAMES',
        'returnGeometry': 'true',
        'f': 'json',
        'outSR': '4326',
        'resultOffset': 0,
        'resultRecordCount': 2000,
    }
    resp = SESSION.get(SEATTLE_NEIGHBORHOODS_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    features = payload.get('features') or []
    out = []
    for feature in features:
        attrs = feature.get('attributes') or {}
        geom = feature.get('geometry') or {}
        rings = geom.get('rings') or []
        if not rings:
            continue
        bbox = [
            min(pt[0] for ring in rings for pt in ring),
            min(pt[1] for ring in rings for pt in ring),
            max(pt[0] for ring in rings for pt in ring),
            max(pt[1] for ring in rings for pt in ring),
        ]
        name = normalize_seattle_neighborhood(attrs.get('S_HOOD_ALT_NAMES') or attrs.get('L_HOOD'))
        out.append({'name': name, 'rings': rings, 'bbox': bbox})
    return out


def assign_seattle_neighborhood(point, neighborhoods):
    if not point:
        return 'Unknown'
    x, y = point
    for item in neighborhoods:
        xmin, ymin, xmax, ymax = item['bbox']
        if x < xmin or x > xmax or y < ymin or y > ymax:
            continue
        if point_in_polygon(x, y, item['rings']):
            return item['name']
    return 'Unknown'


def fetch_seattle_rows(neighborhoods):
    offset = 0
    out = []
    pages = 0
    examined = 0
    unknown_rows = 0
    dropped_examples: list[str] = []
    while True:
        params = {
            '$limit': '1000',
            '$offset': str(offset),
            '$order': 'applieddate ASC',
            '$where': "applieddate >= '2022-01-01T00:00:00.000'",
        }
        res = SESSION.get(SEATTLE_PERMITS_URL, params=params, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        rows = res.json()
        if not rows:
            break
        pages += 1
        examined += len(rows)
        for r in rows:
            text = ' '.join(str(r.get(k, '')) for k in ['permitclass', 'permittype', 'description', 'workdescription', 'subtype'])
            category = classify(text)
            if not category:
                if len(dropped_examples) < 20:
                    dropped_examples.append(normalize(text)[:180])
                continue
            issue_dt = parse_dt(r.get('issueddate'))
            intake_dt = parse_dt(r.get('applieddate'))
            year_dt = issue_dt or intake_dt
            if not year_dt or year_dt.year not in YEARS:
                continue
            point = extract_point(r)
            neighborhood = normalize_seattle_neighborhood(r.get('neighborhood') or r.get('neighborhoodname'))
            if neighborhood == 'Unknown':
                neighborhood = assign_seattle_neighborhood(point, neighborhoods)
            if neighborhood == 'Unknown':
                unknown_rows += 1
            out.append({
                'jurisdiction': 'Seattle',
                'category': category,
                'neighborhood': neighborhood,
                'address': normalize(r.get('originaladdress1') or r.get('address')),
                'issue_date': issue_dt.isoformat()[:10] if issue_dt else '',
                'intake_date': intake_dt.isoformat()[:10] if intake_dt else '',
                'lat': point[1] if point else None,
                'lon': point[0] if point else None,
            })
        offset += len(rows)
        if len(rows) < 1000:
            break
    return out, {'pages': pages, 'rows_examined': examined, 'rows_kept': len(out), 'unknown_rows': unknown_rows, 'dropped_examples': dropped_examples}


def stream_csv_dicts(url: str) -> Iterable[dict[str, str]]:
    with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        resp.encoding = resp.encoding or 'utf-8'
        lines = (line.decode(resp.encoding, errors='replace') for line in resp.iter_lines() if line)
        reader = csv.DictReader(lines)
        for row in reader:
            yield row


def pick_first(row: dict[str, Any], keys: list[str]):
    for key in keys:
        if key in row and normalize(row.get(key)):
            return row.get(key)
    normalized_map = {norm_key(k).replace(' ', ''): k for k in row.keys()}
    for key in keys:
        probe = norm_key(key).replace(' ', '')
        actual = normalized_map.get(probe)
        if actual and normalize(row.get(actual)):
            return row.get(actual)
    return None


def stream_bellevue_rows():
    errors = []
    for url in [u for u in BELLEVUE_PERMITS_CSV_FALLBACKS if u]:
        try:
            yield from stream_csv_dicts(url)
            return
        except Exception as e:
            errors.append(f'{url}: {e}')
    raise RuntimeError(' | '.join(errors) if errors else 'No Bellevue CSV URL configured')


def fetch_bellevue_rows():
    out = []
    seen_columns = set()
    examined = 0
    unknown_rows = 0
    dropped_examples: list[str] = []
    for r in stream_bellevue_rows():
        examined += 1
        seen_columns.update(r.keys())
        text = ' '.join(str(v or '') for v in r.values())
        category = classify(text)
        if not category:
            if len(dropped_examples) < 20:
                dropped_examples.append(normalize(text)[:180])
            continue
        issue_dt = parse_dt(pick_first(r, ['ISSUEDATE', 'ISSUE_DATE', 'ISSUED DATE']))
        intake_dt = parse_dt(pick_first(r, ['APPLICATIONDATE', 'APPLIEDDATE', 'APPLIED DATE', 'APPLICATION_DATE']))
        year_dt = issue_dt or intake_dt
        if not year_dt or year_dt.year not in YEARS:
            continue
        neighborhood = normalize_bellevue_neighborhood(pick_first(r, ['NEIGHBORHOODAREA', 'NEIGHBORHOOD AREA', 'NEIGHBORHOOD', 'AREA_NAME']))
        if neighborhood == 'Unknown':
            unknown_rows += 1
        lat = pick_first(r, ['LATITUDE', 'LAT', 'Y'])
        lon = pick_first(r, ['LONGITUDE', 'LON', 'LNG', 'X'])
        try:
            lat = float(lat) if lat not in (None, '') else None
            lon = float(lon) if lon not in (None, '') else None
        except Exception:
            lat = None
            lon = None
        out.append({
            'jurisdiction': 'Bellevue',
            'category': category,
            'neighborhood': neighborhood,
            'address': normalize(pick_first(r, ['SITEADDRESS', 'SITE ADDRESS', 'ADDRESS', 'FULLADDRESS', 'FULL ADDRESS'])),
            'issue_date': issue_dt.isoformat()[:10] if issue_dt else '',
            'intake_date': intake_dt.isoformat()[:10] if intake_dt else '',
            'lat': lat,
            'lon': lon,
        })
    return out, {
        'rows_examined': examined,
        'rows_kept': len(out),
        'columns_seen': sorted(seen_columns)[:60],
        'unknown_rows': unknown_rows,
        'dropped_examples': dropped_examples,
    }


def zero_bucket():
    return {'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'All New': 0, 'Total': 0}


def build_outputs(rows, diagnostics):
    agg: dict[str, Any] = {}
    samples = []
    map_points = []
    for row in rows:
        hood = row['neighborhood'] or 'Unknown'
        year = (row['issue_date'] or row['intake_date'])[:4]
        if year not in {str(y) for y in YEARS}:
            continue
        agg.setdefault(hood, {
            'neighborhood': hood,
            'jurisdictions': set(),
            'years': {str(y): zero_bucket() for y in YEARS},
        })
        agg[hood]['jurisdictions'].add(row['jurisdiction'])
        bucket = agg[hood]['years'][year]
        bucket[row['category']] += 1
        if row['category'] != 'Demo':
            bucket['All New'] += 1
        bucket['Total'] = bucket['All New'] + bucket['Demo']
        if len(samples) < 30:
            samples.append(row)
        if row.get('lat') is not None and row.get('lon') is not None and len(map_points) < 120:
            map_points.append(row)

    neighborhood_rows = []
    for hood, item in agg.items():
        totals = zero_bucket()
        for y in YEARS:
            yr = item['years'][str(y)]
            for k in totals:
                totals[k] += yr[k]
        neighborhood_rows.append({
            'neighborhood': hood,
            'jurisdictions': sorted(item['jurisdictions']),
            'years': item['years'],
            'totals': totals,
        })
    neighborhood_rows.sort(key=lambda r: (-r['totals']['Total'], r['neighborhood']))

    annual_series = []
    for y in YEARS:
        record = {'year': y, **zero_bucket()}
        for row in neighborhood_rows:
            yr = row['years'][str(y)]
            for k in zero_bucket():
                record[k] += yr[k]
        annual_series.append(record)

    known_hoods = [r for r in neighborhood_rows if r['neighborhood'] != 'Unknown']
    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cards': {
            'total_permits': sum(r['totals']['Total'] for r in neighborhood_rows),
            'seattle_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Seattle' in r['jurisdictions']),
            'bellevue_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Bellevue' in r['jurisdictions']),
            'known_neighborhoods': len(known_hoods),
            'unknown_neighborhoods': sum(r['totals']['Total'] for r in neighborhood_rows if r['neighborhood'] == 'Unknown'),
            'new_sfr': sum(r['totals']['New SFR'] for r in neighborhood_rows),
            'new_mf': sum(r['totals']['New MF'] for r in neighborhood_rows),
            'other_new': sum(r['totals']['Other New'] for r in neighborhood_rows),
            'all_new': sum(r['totals']['All New'] for r in neighborhood_rows),
            'demo': sum(r['totals']['Demo'] for r in neighborhood_rows),
        },
        'annual_series': annual_series,
        'neighborhood_rows': neighborhood_rows,
        'samples': samples,
        'map_points': map_points,
        'load_notes': [
            f"Precomputed refresh generated {len(rows)} target permit rows.",
            f"Known neighborhoods after refresh: {len(known_hoods)}.",
            f"Seattle kept {diagnostics.get('seattle_rows_kept', 0)} rows after scanning {diagnostics.get('seattle_rows_examined', 0)} rows.",
            f"Bellevue kept {diagnostics.get('bellevue_rows_kept', 0)} rows after scanning {diagnostics.get('bellevue_rows_examined', 0)} rows.",
        ],
        'load_errors': diagnostics.get('errors', []),
    }
    meta = {
        'generated_at': summary['generated_at'],
        'neighborhoods': sorted(r['neighborhood'] for r in known_hoods),
        'load_notes': summary['load_notes'],
        'load_errors': summary['load_errors'],
    }
    return summary, meta


def main():
    rows = []
    errors = []
    diagnostics: dict[str, Any] = {'errors': errors}

    seattle_neighborhoods = []
    try:
        seattle_neighborhoods = fetch_seattle_neighborhoods()
        diagnostics['seattle_neighborhood_polygons'] = len(seattle_neighborhoods)
    except Exception as e:
        errors.append(f'Seattle neighborhoods refresh failed: {e}')

    try:
        seattle_rows, seattle_info = fetch_seattle_rows(seattle_neighborhoods)
        diagnostics['seattle_pages'] = seattle_info['pages']
        diagnostics['seattle_rows_examined'] = seattle_info['rows_examined']
        diagnostics['seattle_rows_kept'] = seattle_info['rows_kept']
        diagnostics['seattle_unknown_rows'] = seattle_info['unknown_rows']
        diagnostics['seattle_dropped_examples'] = seattle_info['dropped_examples']
        rows.extend(seattle_rows)
    except Exception as e:
        errors.append(f'Seattle refresh failed: {e}')

    try:
        bellevue_rows, bellevue_info = fetch_bellevue_rows()
        diagnostics['bellevue_rows_examined'] = bellevue_info['rows_examined']
        diagnostics['bellevue_rows_kept'] = bellevue_info['rows_kept']
        diagnostics['bellevue_columns_seen'] = bellevue_info['columns_seen']
        diagnostics['bellevue_unknown_rows'] = bellevue_info['unknown_rows']
        diagnostics['bellevue_dropped_examples'] = bellevue_info['dropped_examples']
        rows.extend(bellevue_rows)
        if bellevue_info['rows_kept'] == 0:
            errors.append('Bellevue refresh returned zero target rows. Inspect columns_seen and dropped_examples in data/refresh_debug.json.')
    except Exception as e:
        errors.append(f'Bellevue refresh failed: {e}')

    summary, meta = build_outputs(rows, diagnostics)
    (DATA_DIR / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (DATA_DIR / 'meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    (DATA_DIR / 'refresh_debug.json').write_text(json.dumps(diagnostics, indent=2), encoding='utf-8')
    print('Wrote', DATA_DIR / 'summary.json')
    print('Wrote', DATA_DIR / 'meta.json')
    print('Wrote', DATA_DIR / 'refresh_debug.json')


if __name__ == '__main__':
    main()
