import json
from pathlib import Path
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
SUMMARY_PATH = DATA_DIR / 'summary.json'
META_PATH = DATA_DIR / 'meta.json'

VALID_CATEGORIES = ['New SFR', 'New MF', 'Other New', 'Demo']
YEARS = [2022, 2023, 2024, 2025, 2026]

app = Flask(__name__)


def load_json(path: Path, default):
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def load_meta():
    return load_json(META_PATH, {
        'neighborhoods': [],
        'load_notes': [
            'Serving precomputed dataset for instant startup.',
            'Use refresh_data.py locally to rebuild from live Seattle and Bellevue sources.'
        ],
        'load_errors': []
    })


def load_summary():
    default = {
        'cards': {
            'total_permits': 0,
            'seattle_permits': 0,
            'bellevue_permits': 0,
            'known_neighborhoods': 0,
            'new_sfr': 0,
            'new_mf': 0,
            'other_new': 0,
            'total_new_construction': 0,
            'demo': 0,
        },
        'annual_series': [{
            'year': y, 'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'Total': 0
        } for y in YEARS],
        'neighborhood_rows': [],
        'samples': [],
        'map_points': [],
        'load_notes': ['No precomputed data found.'],
        'load_errors': []
    }
    return load_json(SUMMARY_PATH, default)


def clamp_years(start_year: int, end_year: int):
    start_year = max(YEARS[0], min(YEARS[-1], start_year))
    end_year = max(YEARS[0], min(YEARS[-1], end_year))
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    return start_year, end_year


def filter_summary(summary, jurisdiction, category, neighborhood, start_year, end_year):
    if all(
        ('Other New' not in row.get('totals', {})) and
        all('Other New' not in yr for yr in (row.get('years') or {}).values())
        for row in summary.get('neighborhood_rows', [])
    ):
        notes = list(summary.get('load_notes', []))
        notes.append('Current precomputed data was generated before "Other New" was added. Run refresh_data.py locally to capture all new construction.')
        summary['load_notes'] = notes
    start_year, end_year = clamp_years(start_year, end_year)
    years = [y for y in YEARS if start_year <= y <= end_year]
    year_set = set(str(y) for y in years)

    def keep_sample(row):
        if jurisdiction != 'all' and row.get('jurisdiction') != jurisdiction:
            return False
        if category != 'all' and row.get('category') != category:
            return False
        if neighborhood != 'all' and row.get('neighborhood') != neighborhood:
            return False
        year = str((row.get('issue_date') or row.get('intake_date') or '')[:4])
        return year in year_set

    neighborhood_rows = []
    for row in summary.get('neighborhood_rows', []):
        if jurisdiction != 'all' and jurisdiction not in row.get('jurisdictions', []):
            continue
        if neighborhood != 'all' and row.get('neighborhood') != neighborhood:
            continue
        years_obj = {}
        totals = {'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'Total': 0}
        for y in years:
            src = (row.get('years') or {}).get(str(y), {'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'Total': 0})
            if category == 'all':
                item = {
                    'New SFR': int(src.get('New SFR', 0)),
                    'New MF': int(src.get('New MF', 0)),
                    'Other New': int(src.get('Other New', 0)),
                    'Demo': int(src.get('Demo', 0)),
                }
            else:
                item = {'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0}
                item[category] = int(src.get(category, 0))
            item['Total'] = item['New SFR'] + item['New MF'] + item['Other New'] + item['Demo']
            years_obj[str(y)] = item
            for k in ('New SFR', 'New MF', 'Other New', 'Demo', 'Total'):
                totals[k] += item[k]
        if totals['Total'] == 0:
            continue
        neighborhood_rows.append({
            'neighborhood': row.get('neighborhood'),
            'jurisdictions': row.get('jurisdictions', []),
            'years': years_obj,
            'totals': totals,
        })

    neighborhood_rows.sort(key=lambda r: (-r['totals']['Total'], r['neighborhood'] or ''))

    annual_series = []
    for y in years:
        record = {'year': y, 'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'Total': 0}
        for row in neighborhood_rows:
            item = row['years'][str(y)]
            for k in ('New SFR', 'New MF', 'Other New', 'Demo', 'Total'):
                record[k] += item[k]
        annual_series.append(record)

    cards = {
        'total_permits': sum(r['totals']['Total'] for r in neighborhood_rows),
        'seattle_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Seattle' in r.get('jurisdictions', [])),
        'bellevue_permits': sum(r['totals']['Total'] for r in neighborhood_rows if 'Bellevue' in r.get('jurisdictions', [])),
        'known_neighborhoods': len(neighborhood_rows),
        'new_sfr': sum(r['totals']['New SFR'] for r in neighborhood_rows),
        'new_mf': sum(r['totals']['New MF'] for r in neighborhood_rows),
        'other_new': sum(r['totals']['Other New'] for r in neighborhood_rows),
        'total_new_construction': sum(r['totals']['New SFR'] + r['totals']['New MF'] + r['totals']['Other New'] for r in neighborhood_rows),
        'demo': sum(r['totals']['Demo'] for r in neighborhood_rows),
    }

    samples = [r for r in summary.get('samples', []) if keep_sample(r)][:20]
    map_points = [r for r in summary.get('map_points', []) if keep_sample(r)][:24]

    return {
        'cards': cards,
        'annual_series': annual_series,
        'neighborhood_rows': neighborhood_rows,
        'samples': samples,
        'map_points': map_points,
        'load_notes': summary.get('load_notes', []),
        'load_errors': summary.get('load_errors', []),
    }


@app.route('/')
def index():
    return render_template('index.html', categories=VALID_CATEGORIES, years=YEARS)


@app.route('/api/meta')
def api_meta():
    meta = load_meta()
    return jsonify(meta)


@app.route('/api/summary')
def api_summary():
    summary = load_summary()
    jurisdiction = request.args.get('jurisdiction', 'all')
    category = request.args.get('category', 'all')
    neighborhood = request.args.get('neighborhood', 'all')
    try:
        start_year = int(request.args.get('start_year', YEARS[0]))
    except Exception:
        start_year = YEARS[0]
    try:
        end_year = int(request.args.get('end_year', YEARS[-1]))
    except Exception:
        end_year = YEARS[-1]
    if category not in {'all', *VALID_CATEGORIES}:
        category = 'all'
    if jurisdiction not in {'all', 'Seattle', 'Bellevue'}:
        jurisdiction = 'all'
    return jsonify(filter_summary(summary, jurisdiction, category, neighborhood, start_year, end_year))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
