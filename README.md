# Permit Signal Dashboard

Seattle + Bellevue permit dashboard built for a simple **GitHub → Render** deployment.

## What is in this repo

- `index.html` — main dashboard markup
- `styles.css` — executive-facing styling
- `app.js` — live data loading, filtering, charts, map, and fallback logic
- `render.yaml` — optional Render Blueprint file
- `.gitignore` — standard cleanup

## What this version fixes

The prior package was too thin. This one is more deployable and more resilient:

- better executive layout and signal framing
- live Seattle + Bellevue data wiring
- fallback demo mode if a browser-side public API request fails
- refresh button and cleaner status messaging
- repo structure that is easier to push directly to GitHub

## GitHub steps

1. Create a new GitHub repo
2. Upload all files from this folder into the repo root
3. Commit and push

## Render deploy steps

### Simple path

1. In Render, click **New > Static Site**
2. Connect your GitHub repo
3. Use:
   - **Build Command:** leave blank
   - **Publish Directory:** `.`
4. Deploy

### Blueprint path

1. Keep `render.yaml` in the repo root
2. In Render, create a new **Blueprint**
3. Point it to the repo
4. Sync and deploy

## Notes

- This is still an MVP, but it is styled and framed more like an internal executive tool.
- Bellevue and Seattle are both configured as live browser-side public sources.
- If a public endpoint blocks the browser request or times out, the page will still open in demo fallback mode so you are not staring at a broken screen.

## Smart next upgrades

- neighborhood filter
- permit clustering / heatmap mode
- permit status backlog panel
- issue-lag percentile bands
- export filtered results to CSV
- Purple-style jurisdiction scoring
