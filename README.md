# Permit Dashboard v12

This version is built to start instantly on Render free tier.

## What changed
- The web app serves precomputed JSON from `data/summary.json` and `data/meta.json`.
- Render no longer tries to fetch Seattle and Bellevue at startup.
- To refresh live data, run `python refresh_data.py` locally, then commit the updated JSON files.

## Deploy on Render
- Create or keep a Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 1 --timeout 60 --bind 0.0.0.0:$PORT`

## Refresh live data
1. Run `python refresh_data.py`
2. Commit `data/summary.json` and `data/meta.json`
3. Push to GitHub
4. Let Render redeploy

## Notes
- The bundled JSON is a lightweight starter dataset so the UI works immediately.
- The live refresh script is where Seattle and Bellevue pulls happen.


## v13 refresh notes
- Run `python refresh_data.py` locally to rebuild `data/summary.json` and `data/meta.json`.
- If Bellevue changes its CSV item URL, set `BELLEVUE_PERMITS_URL` before running the script.
- Check `data/refresh_debug.json` after each refresh; it records Seattle page counts and Bellevue columns seen so you can diagnose field-name drift quickly.
