# Permit Dashboard v10

Summary-first Flask app for Seattle + Bellevue permit trends.

## Render
- Create a **Web Service** from this repo
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --workers 1 --threads 1 --timeout 120 --bind 0.0.0.0:$PORT`

## What it does
- Limits scope to **2022–2026**
- Targets only **New SFR**, **New MF**, and **Demo**
- Keeps the UI light for executive review
- Supports neighborhood filtering, search, annual trends, and neighborhood drilldown

## Notes
- Bellevue is loaded from the Bellevue permits download candidates already wired in `app.py`.
- Seattle neighborhoods are assigned from the official Seattle neighborhood feature layer.
- If a source fails, the app surfaces that in the load notes instead of silently pretending nothing happened.
