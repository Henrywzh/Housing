# London housing — borough & submarket price / rent panel

Interactive choropleth of London house prices and private rents, plus a
flat-by-flat cut of new-build vs existing stock that the published indices
do not provide.

## Data sources (all official, all full history)

| Source | Grain | From | Fetched by |
|---|---|---|---|
| HM Land Registry / ONS **UK House Price Index** | borough, monthly | 1995-01 | manual curl (see below) |
| ONS **Price Index of Private Rents** (PIPR) | borough, monthly | 2015-01 | manual curl |
| HM Land Registry **Price Paid Data** | every transaction, postcode | 1995-01 | `scripts/fetch_ppd.py` |
| ONS Open Geography borough boundaries (BGC) | polygon | — | manual curl |

The UK HPI publishes a flat series and a new-build series but **never crosses
them**. Price Paid is the only source carrying property type, the new-build
flag and a full postcode on the same row, so the flat x new/existing cut and
the postcode-sector submarkets are both built from it.

## Pipeline

```
scripts/fetch_ppd.py            # streams 5.5GB of PPD, keeps Greater London (~284MB)
scripts/build_ppd_aggregates.py # borough x quarter x seg x build; 10 submarkets
scripts/build_dataset.py        # merges HPI + PIPR + PPD -> data/processed/
scripts/build_site.py           # inlines the data into web/template.html
```

`build_site.py` fails the build if the UI declares a metric the payload does
not carry — the two drifted apart once and the map silently rendered blank.

## Monthly refresh

Replace the two files in `data/raw/` after the ONS release, then rerun
`build_dataset.py` and `build_site.py`.

## Caveats that matter

* PIPR rent is the **whole rented stock**, not new lettings, so it sits below
  Rightmove asking rents.
* Price Paid figures are **median achieved prices**, not mix-adjusted like the
  HPI. One tower of studios completing moves a borough's new-build median
  without anything repricing — always read the `n` column alongside.
* New-build registrations lag; the most recent two quarters are incomplete.
* Price Paid has no floor area, so the new-build premium is **not** a
  like-for-like per-sqft comparison.
