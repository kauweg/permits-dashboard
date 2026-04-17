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

SUMMARY_PATH = DATA_DIR / 'summary.json'
META_PATH = DATA_DIR / 'meta.json'
DEBUG_PATH = DATA_DIR / 'refresh_debug.json'

YEARS = [2022, 2023, 2024, 2025, 2026]

SEATTLE_PERMITS_URL = 'https://data.seattle.gov/resource/76t5-zqzr.json'
SEATTLE_NEIGHBORHOODS_URL = (
    'https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/'
    'nma_nhoods_main/FeatureServer/0/query'
)
BELLEVUE_URL_CANDIDATES = [
    os.getenv('BELLEVUE_PERMITS_URL', '').strip(),
    'https://hub.arcgis.com/api/v3/datasets/fc7da7bd29d4493481b17d032e117d09_0/downloads/data?format=csv&spatialRefId=4326',
    'https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true',
]
REQUEST_TIMEOUT = 120
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'permit-dashboard-refresh/14.0'})


def load_existing(path: Path, default: Any):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


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


def classify(text: str):
    t = f" {normalize(text).lower()} "
    if any(k in t for k in [' demol', ' demolition', ' demo ', ' teardown', ' raze', ' remove structure']):
        return 'Demo'
    has_new = any(k in t for k in [' new ', 'new construction', 'ground up', 'construct', 'new bldg', 'new building'])
    has_sf = any(k in t for k in [' single family', 'single-family', ' sfr ', 'detached', 'one-family', 'single family residence'])
    has_mf = any(k in t for k in [
        ' multifamily', 'multi-family', 'multi family', ' apartment', 'apartments', 'townhome',
        'townhouse', 'condo', 'condominium', 'duplex', 'triplex', 'fourplex', 'mixed use', 'mixed-use',
        'rowhouse', 'live/work', 'stacked flat'
    ])
    if has_new and has_sf and not has_mf:
        return 'New SFR'
    if has_new and has_mf:
        return 'New MF'
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
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
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
        name = clean_neighborhood(attrs.get('S_HOOD_ALT_NAMES') or attrs.get('L_HOOD'))
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
                continue
            issue_dt = parse_dt(r.get('issueddate'))
            intake_dt = parse_dt(r.get('applieddate'))
            year_dt = issue_dt or intake_dt
            if not year_dt or year_dt.year not in YEARS:
                continue
            neighborhood = clean_neighborhood(r.get('neighborhood') or r.get('neighborhoodname'))
            if neighborhood == 'Unknown':
                neighborhood = assign_seattle_neighborhood(extract_point(r), neighborhoods)
            out.append({
                'jurisdiction': 'Seattle',
                'category': category,
                'neighborhood': neighborhood,
                'address': normalize(r.get('originaladdress1') or r.get('address')),
                'issue_date': issue_dt.isoformat()[:10] if issue_dt else '',
                'intake_date': intake_dt.isoformat()[:10] if intake_dt else '',
            })
        offset += len(rows)
        if len(rows) < 1000:
            break
    return out, {'pages': pages, 'rows_kept': len(out)}


def stream_csv_dicts(url: str) -> Iterable[dict[str, str]]:
    with SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        encoding = resp.encoding or 'utf-8'
        lines = (line.decode(encoding, errors='replace') for line in resp.iter_lines() if line)
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
    out = []
    diagnostics = {'source_url': None, 'rows_examined': 0, 'rows_kept': 0, 'columns_seen': []}
    last_error = None

    candidates = [u for u in BELLEVUE_URL_CANDIDATES if u]
    for url in candidates:
        seen_columns = set()
        examined = 0
        current_out = []
        try:
            for r in stream_csv_dicts(url):
                examined += 1
                seen_columns.update(r.keys())
                text = ' '.join(str(v or '') for v in r.values())
                category = classify(text)
                if not category:
                    continue
                issue_dt = parse_dt(pick_first(r, ['ISSUEDATE', 'ISSUE_DATE', 'ISSUED DATE']))
                intake_dt = parse_dt(pick_first(r, ['APPLICATIONDATE', 'APPLIEDDATE', 'APPLIED DATE', 'APPLICATION_DATE']))
                year_dt = issue_dt or intake_dt
                if not year_dt or year_dt.year not in YEARS:
                    continue
                neighborhood = clean_neighborhood(pick_first(r, ['NEIGHBORHOODAREA', 'NEIGHBORHOOD AREA', 'NEIGHBORHOOD', 'AREA_NAME']))
                current_out.append({
                    'jurisdiction': 'Bellevue',
                    'category': category,
                    'neighborhood': neighborhood,
                    'address': normalize(pick_first(r, ['SITEADDRESS', 'SITE ADDRESS', 'ADDRESS', 'FULLADDRESS', 'FULL ADDRESS'])),
                    'issue_date': issue_dt.isoformat()[:10] if issue_dt else '',
                    'intake_date': intake_dt.isoformat()[:10] if intake_dt else '',
                })
            diagnostics.update({
                'source_url': url,
                'rows_examined': examined,
                'rows_kept': len(current_out),
                'columns_seen': sorted(seen_columns)[:60],
            })
            if current_out:
                return current_out, diagnostics
            last_error = RuntimeError(f'Zero target rows from {url}')
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error
    return out, diagnostics


def build_outputs(rows, diagnostics):
    agg: dict[str, Any] = {}
    samples = []
    for row in rows:
        hood = row['neighborhood'] or 'Unknown'
        year = (row['issue_date'] or row['intake_date'])[:4]
        if year not in {str(y) for y in YEARS}:
            continue
        agg.setdefault(hood, {
            'neighborhood': hood,
            'jurisdictions': set(),
            'years': {str(y): {'New SFR': 0, 'New MF': 0, 'Demo': 0, 'Total': 0} for y in YEARS},
        })
        agg[hood]['jurisdictions'].add(row['jurisdiction'])
        bucket = agg[hood]['years'][year]
        bucket[row['category']] += 1
        bucket['Total'] += 1
        if len(samples) < 60:
            samples.append(row)

    neighborhood_rows = []
    for hood, item in agg.items():
        totals = {'New SFR': 0, 'New MF': 0, 'Demo': 0, 'Total': 0}
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
        record = {'year': y, 'New SFR': 0, 'New MF': 0, 'Demo': 0, 'Total': 0}
        for row in neighborhood_rows:
            yr = row['years'][str(y)]
            for k in ('New SFR', 'New MF', 'Demo', 'Total'):
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
            'new_sfr': sum(r['totals']['New SFR'] for r in neighborhood_rows),
            'new_mf': sum(r['totals']['New MF'] for r in neighborhood_rows),
            'demo': sum(r['totals']['Demo'] for r in neighborhood_rows),
        },
        'annual_series': annual_series,
        'neighborhood_rows': neighborhood_rows,
        'samples': samples[:20],
        'map_points': samples[:24],
        'load_notes': [
            f"Precomputed refresh generated {len(rows)} target permit rows.",
            f"Known neighborhoods after refresh: {len(known_hoods)}.",
            f"Seattle kept {diagnostics.get('seattle_rows_kept', 0)} rows across {diagnostics.get('seattle_pages', 0)} pages.",
            f"Bellevue kept {diagnostics.get('bellevue_rows_kept', 0)} rows after scanning {diagnostics.get('bellevue_rows_examined', 0)} CSV rows.",
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
    previous_summary = load_existing(SUMMARY_PATH, {})
    previous_meta = load_existing(META_PATH, {})
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
        rows.extend(seattle_rows)
    except Exception as e:
        errors.append(f'Seattle refresh failed: {e}')

    try:
        bellevue_rows, bellevue_info = fetch_bellevue_rows()
        diagnostics['bellevue_source_url'] = bellevue_info['source_url']
        diagnostics['bellevue_rows_examined'] = bellevue_info['rows_examined']
        diagnostics['bellevue_rows_kept'] = bellevue_info['rows_kept']
        diagnostics['bellevue_columns_seen'] = bellevue_info['columns_seen']
        rows.extend(bellevue_rows)
    except Exception as e:
        errors.append(f'Bellevue refresh failed: {e}')

    if not rows:
        errors.append('Refresh produced zero target rows. Preserving prior summary/meta files.')
        summary = previous_summary
        meta = previous_meta
    else:
        summary, meta = build_outputs(rows, diagnostics)

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    META_PATH.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    DEBUG_PATH.write_text(json.dumps(diagnostics, indent=2), encoding='utf-8')
    print('Wrote', SUMMARY_PATH)
    print('Wrote', META_PATH)
    print('Wrote', DEBUG_PATH)


if __name__ == '__main__':
    main()
