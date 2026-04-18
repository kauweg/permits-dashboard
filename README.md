# Permit Dashboard v19

This version keeps Render fast by serving precomputed JSON from `data/summary.json` and `data/meta.json`.

## What changed
- Added `Other New` and `All New` so the dataset can capture broader new-construction permits instead of only strict SFR/MF/demo matches.
- Added a real map panel using Leaflet. It uses precomputed lat/lon points when available.
- Expanded Seattle and Bellevue neighborhood normalization so broad market areas can roll up cleanly.
- Kept the app summary-first so startup stays lightweight on Render.

## Deploy on Render
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 1 --timeout 60 --bind 0.0.0.0:$PORT`

## Refresh live data
1. Run `python refresh_data.py` locally.
2. Review `data/refresh_debug.json`.
3. Commit `data/summary.json`, `data/meta.json`, and optionally `data/refresh_debug.json`.
4. Push to GitHub and let Render redeploy.

## Notes
- The bundled JSON is still a starter dataset. Counts and map markers will improve after the next refresh.
- The app stays light because it does not pull Seattle and Bellevue live on startup.
