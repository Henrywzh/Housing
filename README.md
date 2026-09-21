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
| ONS Open Geography borough & MSOA boundaries (BGC) | polygon | — | manual curl |
| **data.police.uk** street-level crime | any polygon | rolling 36 months | `scripts/fetch_crime.py` |
| **Census 2021 TS021** ethnic group (NOMIS) | MSOA | 2021 | manual curl |
| **ASHE** earnings, resident + workplace (NOMIS) | borough | 2010-2025 | manual curl |
| **ONS small-area income** | MSOA | FYE2023 | manual curl |

The UK HPI publishes a flat series and a new-build series but **never crosses
them**. Price Paid is the only source carrying property type, the new-build
flag and a full postcode on the same row, so the flat x new/existing cut and
the postcode-sector submarkets are both built from it.

## Two geographies, deliberately

Prices come from transactions, which carry a postcode, so the price submarkets
are built from **postcode sectors**. Crime, census and income are published on
**MSOAs**, so the social submarkets are built from those. The two definitions
cover nearly the same ground but are not identical, and the page says so rather
than pretending one is the other. Both live in `scripts/submarkets.py`.

MSOAs are named by the House of Commons Library naming project, which is why
`E02007083` can be called "Nine Elms" without anyone here inventing a boundary.

## Pipeline

```
scripts/fetch_ppd.py            # streams 5.5GB of PPD, keeps Greater London (~284MB)
scripts/build_ppd_aggregates.py # borough x quarter x seg x build; 10 submarkets
scripts/build_dataset.py        # merges HPI + PIPR + PPD -> data/processed/
scripts/fetch_crime.py          # crime by borough and submarket polygon
scripts/fetch_crime_lsoa.py     # crime at LSOA level inside the submarkets
scripts/build_social.py         # crime + ethnicity + earnings, borough & submarket
scripts/match_epc.py            # joins EPC floor area onto transactions -> £/sqft
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
* £/sqft comes from joining EPC floor areas onto transactions
  (`scripts/fetch_epc.py` then `scripts/build_psf.py`). The match rate is 42.7%
  overall but **55.2% for new-build against 31.4% for existing**: a home that
  has never been sold or let since EPCs became compulsory in 2008 has no
  certificate. The resale side is therefore skewed toward recently traded
  stock, and that bias cannot be removed.
* Land Registry records a shared-ownership sale at the price paid for the
  **share**, not the value of the flat. In these regeneration areas that is
  enough to move a median into the wrong mode — Nine Elms one-beds split into
  17 sales at £226-326/sqft and 13 at £999-1,766/sqft. `build_psf.py` drops
  anything below half the local upper quartile (1,414 transactions) and prints
  what it removed per submarket.
* Crime locations are snapped to anonymised points: reliable over an area,
  meaningless for one street.
* Crime rates use resident population as the denominator. Areas with large
  daytime or visitor populations (City of London has 8,584 residents) score
  far higher than a resident's actual exposure. Burglary and vehicle crime are
  the categories whose victims really are residents.
* An LSOA recording zero crimes over twelve months is **unmapped, not safe**.
  data.police.uk snaps each crime to a pre-existing anonymised point tied to a
  named feature; a newly built block often has none inside it, so its crimes
  land on the nearest named thing outside. Verified: every zero-crime LSOA here
  has 1,000+ crimes within a mile. New-build crime reads low for this reason,
  and the older LSOA next door reads high. Published as unknown, never zero.
* There is **no official rent data below borough level**. PIPR measures the whole
  rented stock, including tenancies signed years ago, so it sits well below what
  a new tower asks today. A submarket yield built from borough rent over
  submarket price is not a real number; the page has a calculator for the rents
  you actually observe instead.
* Census 2021 is the newest sub-borough ethnicity data that exists; the next
  census is 2031. It also predates most of the new-build delivery in these
  submarkets, so the composition is stale exactly where it matters most.
