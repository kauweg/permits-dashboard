# Permit Dashboard

This version keeps the app lightweight for Render and serves precomputed JSON from `data/summary.json` and `data/meta.json`.

## What changed
- Added `Other New` and `All New` to the dashboard so counts are not limited to only strict SFR/MF/demo buckets.
- Added a real map panel using Leaflet.
- `refresh_data.py` now captures latitude/longitude when available and writes broader new-construction categories.

## Deploy on Render
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 1 --timeout 60 --bind 0.0.0.0:$PORT`

## Refresh live data
1. Run `python refresh_data.py` locally
2. Commit `data/summary.json`, `data/meta.json`, and optionally `data/refresh_debug.json`
3. Push to GitHub
