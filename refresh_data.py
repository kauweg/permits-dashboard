"""Refresh precomputed permit dashboard data.

Run locally, then commit the generated data/*.json files.
This keeps Render startup instant while still allowing fresh civic-data pulls.
"""
from __future__ import annotations

import csv
import io
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
CATEGORY_KEYS = ['New SFR', 'New MF', 'Other New', 'Demo']

SEATTLE_PERMITS_URL = 'https://data.seattle.gov/resource/76t5-zqzr.json'
SEATTLE_NEIGHBORHOODS_URL = (
    'https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/'
    'nma_nhoods_main/FeatureServer/0/query'
)
BELLEVUE_PERMITS_CSV_FALLBACKS = [
    os.getenv('BELLEVUE_PERMITS_URL', '').strip(),
    'https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true',
    'https://opendata.arcgis.com/api/v3/datasets/fc7da7bd29d4493481b17d032e117d09_0/downloads/data?format=csv&spatialRefId=4326',
]
REQUEST_TIMEOUT = 120
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'permit-dashboard-precompute/19.0'})

SEATTLE_GROUP_ALIASES = {
    'West Seattle': {
        'west seattle', 'admiral', 'alki', 'arbor heights', 'gatewood', 'genesee', 'fairmount park',
        'fauntleroy', 'high point', 'highland park', 'junction', 'morgan junction', 'north delridge',
        'south delridge', 'roxhill', 'seaview', 'sunset hill west seattle'
    },
    'Ballard': {'ballard', 'adams', 'loyal heights', 'sunset hill', 'whittier heights', 'crown hill'},
    'Capitol Hill': {'capitol hill', 'broadway', 'pike pine', 'miller park'},
    'Queen Anne': {'queen anne', 'lower queen anne', 'uptown', 'east queen anne', 'west queen anne'},
    'Wallingford': {'wallingford'},
    'Fremont': {'fremont'},
    'Green Lake': {'green lake', 'phinney ridge', 'greenwood'},
    'Central District': {'central area', 'central district', 'madison valley', 'madrona', 'leschi'},
    'Beacon Hill': {'beacon hill', 'north beacon hill', 'mid beacon hill', 'south beacon hill'},
    'Magnolia': {'magnolia', 'discovery park'},
    'Georgetown': {'georgetown'},
    'South Park': {'south park'},
    'Ravenna': {'ravenna', 'wedgwood', 'view ridge', 'bryant', 'laurelhurst'},
    'Roosevelt': {'roosevelt', 'maple leaf', 'northgate', 'haller lake', 'pinehurst'},
    'Mount Baker': {'mount baker', 'columbia city', 'seward park', 'rainier beach', 'rainier valley', 'brighton'},
}

BELLEVUE_GROUP_ALIASES = {
    'Bellevue Downtown': {'downtown', 'bellevue downtown', 'old bellevue'},
    'Wilburton': {'wilburton'},
    'Eastgate': {'eastgate'},
    'BelRed': {'belred', 'bel-red'},
    'Crossroads': {'crossroads'},
    'Factoria': {'factoria'},
    'West Bellevue': {'west bellevue', 'meydenbauer', 'enatai'},
    'Lake Hills': {'lake hills', 'phantom lake'},
    'Newport': {'newport'},
    'Bridle Trails': {'bridle trails'},
    'Somerset': {'somerset'},
    'Lakemont': {'lakemont', 'cougar mountain'},
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


def clean_neighborhood(text: Any) -> str:
    value = normalize(text)
    if not value:
        return 'Unknown'
    low = value.lower()
    if low in {'na', 'n/a', 'none', 'null', 'unknown'}:
        return 'Unknown'
    return value


def apply_alias(name: str, alias_map: dict[str, set[str]]) -> str:
    raw = clean_neighborhood(name)
    if raw == 'Unknown':
        return raw
    low = raw.lower()
    for group, aliases in alias_map.items():
        if low == group.lower() or low in aliases:
            return group
    return raw


def classify(text: str):
    t = f" {normalize(text).lower()} "
    has_demo = any(k in t for k in [' demol', ' demolition', ' demo ', ' teardown', ' raze', ' remove structure'])
    if has_demo:
        return 'Demo'
    new_signals = [' new ', 'new construction', 'ground up', 'new bldg', 'new building', 'construct new', 'construction of', 'erect']
    has_new = any(k in t for k in new_signals)
    has_sf = any(k in t for k in [' single family', 'single-family', ' sfr ', 'detached', 'one-family', 'single family residence'])
    has_mf = any(k in t for k in [
        ' multifamily', 'multi-family', 'multi family', ' apartment', 'apartments', 'townhome', 'townhouse', 'condo',
        'condominium', 'duplex', 'triplex', 'fourplex', 'mixed use', 'mixed-use', 'rowhouse', 'stacked flat', 'live/work'
    ])
    if has_new and has_sf and not has_mf:
        return 'New SFR'
    if has_new and has_mf:
        return 'New MF'
    if has_new:
        return 'Other New'
    return None


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
        name = apply_alias(attrs.get('S_HOOD_ALT_NAMES') or attrs.get('L_HOOD'), SEATTLE_GROUP_ALIASES)
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
    unknown_rows = 0
    dropped_examples = []
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
        for r in rows:
            text = ' '.join(str(r.get(k, '')) for k in ['permitclass', 'permittype', 'description'])
            category = classify(text)
            if not category:
                if len(dropped_examples) < 30:
                    dropped_examples.append(normalize(text)[:200])
                continue
            issue_dt = parse_dt(r.get('issueddate'))
            intake_dt = parse_dt(r.get('applieddate'))
            year_dt = issue_dt or intake_dt
            if not year_dt or year_dt.year not in YEARS:
                continue
            point = extract_point(r)
            neighborhood = apply_alias(r.get('neighborhood') or r.get('neighborhoodname'), SEATTLE_GROUP_ALIASES)
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
                'longitude': point[0] if point else None,
                'latitude': point[1] if point else None,
            })
        offset += len(rows)
        if len(rows) < 1000:
            break
    return out, {'pages': pages, 'rows_kept': len(out), 'unknown_rows': unknown_rows, 'dropped_examples': dropped_examples}


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
    normalized_map = {normalize(k).lower().replace('_', '').replace(' ', ''): k for k in row.keys()}
    for key in keys:
        probe = normalize(key).lower().replace('_', '').replace(' ', '')
        actual = normalized_map.get(probe)
        if actual and normalize(row.get(actual)):
            return row.get(actual)
    return None


def fetch_bellevue_rows():
    last_error = None
    for url in [u for u in BELLEVUE_PERMITS_CSV_FALLBACKS if u]:
        try:
            out = []
            seen_columns = set()
            examined = 0
            unknown_rows = 0
            dropped_examples = []
            for r in stream_csv_dicts(url):
                examined += 1
                seen_columns.update(r.keys())
                text = ' '.join(str(v or '') for v in r.values())
                category = classify(text)
                if not category:
                    if len(dropped_examples) < 30:
                        dropped_examples.append(normalize(text)[:200])
                    continue
                issue_dt = parse_dt(pick_first(r, ['ISSUEDATE', 'ISSUE_DATE', 'ISSUED DATE']))
                intake_dt = parse_dt(pick_first(r, ['APPLICATIONDATE', 'APPLIEDDATE', 'APPLIED DATE', 'APPLICATION_DATE']))
                year_dt = issue_dt or intake_dt
                if not year_dt or year_dt.year not in YEARS:
                    continue
                neighborhood = apply_alias(pick_first(r, ['NEIGHBORHOODAREA', 'NEIGHBORHOOD AREA', 'NEIGHBORHOOD', 'AREA_NAME']), BELLEVUE_GROUP_ALIASES)
                if neighborhood == 'Unknown':
                    unknown_rows += 1
                lon = pick_first(r, ['LONGITUDE', 'LON', 'X'])
                lat = pick_first(r, ['LATITUDE', 'LAT', 'Y'])
                try:
                    lon = float(lon) if lon not in (None, '') else None
                    lat = float(lat) if lat not in (None, '') else None
                except Exception:
                    lon = None
                    lat = None
                out.append({
                    'jurisdiction': 'Bellevue',
                    'category': category,
                    'neighborhood': neighborhood,
                    'address': normalize(pick_first(r, ['SITEADDRESS', 'SITE ADDRESS', 'ADDRESS', 'FULLADDRESS', 'FULL ADDRESS'])),
                    'issue_date': issue_dt.isoformat()[:10] if issue_dt else '',
                    'intake_date': intake_dt.isoformat()[:10] if intake_dt else '',
                    'longitude': lon,
                    'latitude': lat,
                })
            return out, {
                'rows_examined': examined,
                'rows_kept': len(out),
                'unknown_rows': unknown_rows,
                'columns_seen': sorted(seen_columns)[:80],
                'source_url': url,
                'dropped_examples': dropped_examples,
            }
        except Exception as e:
            last_error = e
    raise RuntimeError(f'Bellevue refresh failed across all CSV URLs: {last_error}')


def empty_bucket():
    return {k: 0 for k in ['New SFR', 'New MF', 'Other New', 'Demo', 'All New', 'Total']}


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
            'years': {str(y): empty_bucket() for y in YEARS},
        })
        agg[hood]['jurisdictions'].add(row['jurisdiction'])
        bucket = agg[hood]['years'][year]
        bucket[row['category']] += 1
        if row['category'] != 'Demo':
            bucket['All New'] += 1
        bucket['Total'] += 1
        if len(samples) < 80:
            samples.append(row)
        if row.get('latitude') not in (None, '') and row.get('longitude') not in (None, '') and len(map_points) < 250:
            map_points.append(row)

    neighborhood_rows = []
    for hood, item in agg.items():
        totals = empty_bucket()
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
        record = {'year': y, **empty_bucket()}
        for row in neighborhood_rows:
            yr = row['years'][str(y)]
            for k in ['New SFR', 'New MF', 'Other New', 'Demo', 'All New', 'Total']:
                record[k] += yr[k]
        annual_series.append(record)

    known_hoods = [r for r in neighborhood_rows if r['neighborhood'] != 'Unknown']
    unknown_bucket = next((r for r in neighborhood_rows if r['neighborhood'] == 'Unknown'), None)
    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cards': {
            'total_permits': sum(r['totals']['Total'] for r in neighborhood_rows),
            'all_new': sum(r['totals']['All New'] for r in neighborhood_rows),
            'seattle_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Seattle' in r['jurisdictions']),
            'bellevue_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Bellevue' in r['jurisdictions']),
            'known_neighborhoods': len(known_hoods),
            'unknown_neighborhoods': unknown_bucket['totals']['Total'] if unknown_bucket else 0,
            'new_sfr': sum(r['totals']['New SFR'] for r in neighborhood_rows),
            'new_mf': sum(r['totals']['New MF'] for r in neighborhood_rows),
            'other_new': sum(r['totals']['Other New'] for r in neighborhood_rows),
            'demo': sum(r['totals']['Demo'] for r in neighborhood_rows),
        },
        'annual_series': annual_series,
        'neighborhood_rows': neighborhood_rows,
        'samples': samples[:25],
        'map_points': map_points[:200],
        'load_notes': [
            f"Precomputed refresh generated {len(rows)} target permit rows.",
            f"Known neighborhoods after refresh: {len(known_hoods)}.",
            f"Seattle kept {diagnostics.get('seattle_rows_kept', 0)} rows across {diagnostics.get('seattle_pages', 0)} pages.",
            f"Bellevue kept {diagnostics.get('bellevue_rows_kept', 0)} rows after scanning {diagnostics.get('bellevue_rows_examined', 0)} CSV rows.",
            "Unknown-neighborhood permits still in dataset: pending."
        ],
        'load_errors': diagnostics.get('errors', []),
    }
    # fill placeholder after summary exists
    summary['load_notes'][-1] = f"Unknown-neighborhood permits still in dataset: {summary['cards']['unknown_neighborhoods']}."
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
        diagnostics['bellevue_unknown_rows'] = bellevue_info['unknown_rows']
        diagnostics['bellevue_columns_seen'] = bellevue_info['columns_seen']
        diagnostics['bellevue_source_url'] = bellevue_info['source_url']
        diagnostics['bellevue_dropped_examples'] = bellevue_info['dropped_examples']
        rows.extend(bellevue_rows)
        if bellevue_info['rows_kept'] == 0:
            errors.append('Bellevue refresh returned zero target rows. Check BELLEVUE_PERMITS_URL or inspect columns_seen in data/refresh_debug.json.')
    except Exception as e:
        errors.append(f'Bellevue refresh failed: {e}')

    if not rows and (DATA_DIR / 'summary.json').exists() and (DATA_DIR / 'meta.json').exists():
        print('Refresh produced zero rows. Preserving existing summary/meta files.')
        diagnostics['preserved_existing'] = True
    else:
        summary, meta = build_outputs(rows, diagnostics)
        (DATA_DIR / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        (DATA_DIR / 'meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        print('Wrote', DATA_DIR / 'summary.json')
        print('Wrote', DATA_DIR / 'meta.json')
    (DATA_DIR / 'refresh_debug.json').write_text(json.dumps(diagnostics, indent=2), encoding='utf-8')
    print('Wrote', DATA_DIR / 'refresh_debug.json')


if __name__ == '__main__':
    main()
