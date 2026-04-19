# Permit Dashboard v20

This version keeps Render fast by serving precomputed JSON from `data/summary.json` and `data/meta.json`.

## Deploy on Render
- Create or keep a Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 1 --timeout 60 --bind 0.0.0.0:$PORT`

## Refresh live data locally
1. Run `python refresh_data.py`
2. Review `data/refresh_debug.json`
3. Commit these files:
   - `data/summary.json`
   - `data/meta.json`
   - `data/refresh_debug.json`
4. Push to GitHub and let Render redeploy

## Scope
The refresh tries to keep all 2022–2026 permits that are either:
- Demo
- New SFR
- New MF
- Other New

## Why this design
The refresh can be heavy. The dashboard should not be.
