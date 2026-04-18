
import json
from pathlib import Path
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
SUMMARY_PATH = DATA_DIR / 'summary.json'
META_PATH = DATA_DIR / 'meta.json'

VALID_CATEGORIES = ['New SFR', 'New MF', 'Other New', 'Demo']
YEARS = [2022, 2023, 2024, 2025, 2026]
CATEGORY_KEYS = ['New SFR', 'New MF', 'Other New', 'Demo']

app = Flask(__name__)


def load_json(path: Path, default):
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def zero_bucket():
    return {**{k: 0 for k in CATEGORY_KEYS}, 'All New': 0, 'Total': 0}


def enrich_summary(summary: dict):
    annual = []
    for row in summary.get('annual_series', []):
        r = {'year': int(row.get('year', 0))}
        for k in CATEGORY_KEYS:
            r[k] = int(row.get(k, 0))
        r['All New'] = r['New SFR'] + r['New MF'] + r['Other New']
        r['Total'] = r['All New'] + r['Demo']
        annual.append(r)

    nrows = []
    for row in summary.get('neighborhood_rows', []):
        years = {}
        totals = zero_bucket()
        for y in YEARS:
            src = (row.get('years') or {}).get(str(y), {})
            item = zero_bucket()
            for k in CATEGORY_KEYS:
                item[k] = int(src.get(k, 0))
            item['All New'] = item['New SFR'] + item['New MF'] + item['Other New']
            item['Total'] = item['All New'] + item['Demo']
            years[str(y)] = item
            for k in item:
                totals[k] += item[k]
        nrows.append({
            'neighborhood': row.get('neighborhood', 'Unknown'),
            'jurisdictions': row.get('jurisdictions', []),
            'years': years,
            'totals': totals,
        })
    nrows.sort(key=lambda r: (-r['totals']['Total'], r['neighborhood']))

    cards = summary.get('cards', {})
    cards = {
        'total_permits': int(cards.get('total_permits', 0) or sum(r['totals']['Total'] for r in nrows)),
        'seattle_permits': int(cards.get('seattle_permits', 0) or sum(r['totals']['Total'] for r in nrows if 'Seattle' in r.get('jurisdictions', []))),
        'bellevue_permits': int(cards.get('bellevue_permits', 0) or sum(r['totals']['Total'] for r in nrows if 'Bellevue' in r.get('jurisdictions', []))),
        'known_neighborhoods': int(cards.get('known_neighborhoods', 0) or len([r for r in nrows if r['neighborhood'] != 'Unknown'])),
        'new_sfr': int(cards.get('new_sfr', 0) or sum(r['totals']['New SFR'] for r in nrows)),
        'new_mf': int(cards.get('new_mf', 0) or sum(r['totals']['New MF'] for r in nrows)),
        'other_new': int(cards.get('other_new', 0) or sum(r['totals']['Other New'] for r in nrows)),
        'all_new': int(cards.get('all_new', 0) or sum(r['totals']['All New'] for r in nrows)),
        'demo': int(cards.get('demo', 0) or sum(r['totals']['Demo'] for r in nrows)),
    }

    summary['annual_series'] = annual
    summary['neighborhood_rows'] = nrows
    summary['cards'] = cards
    return summary


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
            'all_new': 0,
            'demo': 0,
        },
        'annual_series': [{
            'year': y, 'New SFR': 0, 'New MF': 0, 'Other New': 0, 'Demo': 0, 'All New': 0, 'Total': 0
        } for y in YEARS],
        'neighborhood_rows': [],
        'samples': [],
        'map_points': [],
        'load_notes': ['No precomputed data found.'],
        'load_errors': []
    }
    return enrich_summary(load_json(SUMMARY_PATH, default))


def filter_summary(summary, jurisdiction, category, neighborhood, start_year, end_year):
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
        totals = zero_bucket()
        for y in years:
            src = (row.get('years') or {}).get(str(y), zero_bucket())
            if category == 'all':
                item = {k: int(src.get(k, 0)) for k in CATEGORY_KEYS}
            else:
                item = {k: 0 for k in CATEGORY_KEYS}
                item[category] = int(src.get(category, 0))
            item['All New'] = item['New SFR'] + item['New MF'] + item['Other New']
            item['Total'] = item['All New'] + item['Demo']
            years_obj[str(y)] = item
            for k in totals:
                totals[k] += item[k]
        if totals['Total'] == 0:
            continue
        neighborhood_rows.append({
            'neighborhood': row.get('neighborhood'),
            'jurisdictions': row.get('jurisdictions', []),
            'years': years_obj,
            'totals': totals,
        })

    neighborhood_rows.sort(key=lambda r: (-r['totals']['Total'], r['neighborhood']))

    annual_series = []
    for y in years:
        record = {'year': y, **zero_bucket()}
        for row in neighborhood_rows:
            item = row['years'][str(y)]
            for k in zero_bucket():
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
        'all_new': sum(r['totals']['All New'] for r in neighborhood_rows),
        'demo': sum(r['totals']['Demo'] for r in neighborhood_rows),
    }

    samples = [r for r in summary.get('samples', []) if keep_sample(r)][:20]
    map_points = [r for r in summary.get('map_points', []) if keep_sample(r)][:100]

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
    start_year = int(request.args.get('start_year', YEARS[0]))
    end_year = int(request.args.get('end_year', YEARS[-1]))
    if category not in {'all', *VALID_CATEGORIES}:
        category = 'all'
    if jurisdiction not in {'all', 'Seattle', 'Bellevue'}:
        jurisdiction = 'all'
    return jsonify(filter_summary(summary, jurisdiction, category, neighborhood, start_year, end_year))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
