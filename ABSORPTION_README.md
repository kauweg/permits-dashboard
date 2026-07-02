# Absorption Early-Warning Module

Measures how long new-construction homes take to sell after completion, per
Seattle neighborhood and product type, and warns when supply is outpacing
sales — the failure mode from the NW 57th post-mortem (construction fine,
5-month sale gap fatal).

## What it computes

For each (market, neighborhood) × (New SFR/ADU, Townhome/Rowhouse/Duplex):

| Metric | Meaning |
|---|---|
| `median_days_to_sale` | Recorded sale date − permit `CompletedDate`, trailing-12mo completion cohort |
| `trend_days` | Change in median vs. the prior-year cohort (+30 = slowing) |
| `pipeline_units` | Units on permits issued in the last 36 months with no completion yet (incoming supply) |
| `standing_unsold_24mo` | Completed in last 24 months, no sale found |
| `months_of_supply` | (pipeline + standing unsold) ÷ trailing monthly sales pace |
| `status` | green / yellow (≥90d median, ≥6 MoS, or +30d trend) / red (≥120d or ≥10 MoS) |

## Data sources (all public, no MLS)

1. **Seattle permits** — same CSV `refresh_data.py` already pulls. The
   `CompletedDate` field is the completion anchor.
2. **King County Assessor extracts** — manual download (same pattern as the
   Redmond CSV): https://info.kingcounty.gov/assessor/datadownload/default.aspx
   - *Real Property Sales* → `EXTR_RPSale.csv`
   - *Residential Building* → `EXTR_ResBldg.csv` (situs address + YrBuilt)
   
   Unzip both into `data/kc_extracts/`. Re-download monthly; the extracts
   refresh weekly. Note the download page requires accepting RCW 42.56.070(9)
   terms (no use of individuals' names for commercial purposes — we only use
   parcel/date/price, no names).

## Run

```
python absorption_refresh.py
# options:
#   --permits-csv path.csv   reuse a local permits download
#   --extract-dir path       override data/kc_extracts
#   --as-of 2026-07-01       reproducible runs
```

Commit `data/absorption.json` + `data/absorption_debug.json`, push, Render
redeploys — identical workflow to `summary.json`.

To serve it, add to `app.py`:

```python
@app.route("/api/absorption")
def absorption():
    return jsonify(load_json(DATA_DIR / "absorption.json", {"areas": []}))
```

## How the join works

Permit address → normalized (house number, street key) → King County
residential buildings on that street (Seattle zips only) → PIN → first
qualifying recorded sale within [completion − 60 days, completion + 3 years],
price ≥ $200K.

- **Townhome fan-out:** a 4-unit permit at 6510 expands along the street
  (6512, 6514, 6516 — same parity, ±6 numbers) until the permit's unit count
  is covered, restricted to buildings with YrBuilt near the completion year.
- **Stale-record guard:** buildings with YrBuilt more than 2 years before
  completion are rejected (prevents matching the old house on a teardown).
- **Presales:** sales recorded up to 60 days before completion count as
  0 days-to-sale and are tallied separately in `presold`.

## Known limitations

- `standing_unsold` conflates join failures with genuinely unsold homes.
  Check `pin_match_stats` and the sale match rate in the debug file; treat
  standing inventory in low-match areas as an upper bound.
- Assessor `DocumentDate` is the excise/document date, which can lag the
  true mutual-acceptance date by weeks — days-to-sale is closing-based, so
  it runs ~30-45 days longer than MLS days-on-market. Compare areas against
  each other, not against MLS DOM.
- Rentals: build-to-rent townhomes never sell and inflate `standing_unsold`.
  No clean public signal for this; interpret red flags in known BTR pockets
  with care.
- Condos aren't handled (they live in the condo extracts, not ResBldg).
  Fine for now since the dashboard's for-sale focus is SFR/townhome.

## Classifier note (affects the main dashboard too)

Seattle's `PermitClass` is literally the string "Single Family/Duplex",
which trips the `duplex` hint in `classify()` — a 1-unit "construct new
single family residence" permit can land in the Townhome bucket.
`absorption_refresh.py` corrects this locally via `refine_category()`
(description-only re-check for 1-unit permits) without touching
`refresh_data.py`. Worth checking whether the dashboard's SFR/townhome
split shows the same skew.
