# Permit Dashboard

This repo serves a fast precomputed permit dashboard for Seattle and Bellevue.

## Repo structure
- `app.py`
- `templates/index.html`
- `static/app.js`
- `static/styles.css`
- `data/meta.json`
- `data/summary.json`
- `refresh_data.py`

## Render
Use a Web Service.

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
gunicorn app:app --workers 1 --threads 1 --timeout 60 --bind 0.0.0.0:$PORT
```

## Refresh data
Run locally:
```bash
python refresh_data.py
```

Then commit and push:
- `data/meta.json`
- `data/summary.json`
- optionally `data/refresh_debug.json`

## Notes
- The app starts from precomputed JSON so Render stays fast.
- The refresh script now tries multiple Bellevue CSV URLs before failing.
- If refresh fails completely, it preserves the prior summary/meta files instead of wiping them out.


## Broader category coverage
- The dashboard now shows Demo, New SFR, New MF, and Other New.
- To update counts for the broader all-new-construction bucket, run `python refresh_data.py` locally and commit the refreshed `data/*.json` files.
