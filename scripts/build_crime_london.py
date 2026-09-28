"""London-wide LSOA crime from the data.police.uk bulk archive.

The API answers polygon queries one at a time; covering every London LSOA that
way is ~12,000 requests. The bulk archive is one 1.7 GB download that carries
all 36 published months for every force, so we take the two forces that police
London -- the Met, and the City of London force for the Square Mile -- and
aggregate them ourselves.

"Resident-relevant" excludes the categories that a resident walking home is not
exposed to in the way the headline count implies: shoplifting is a retail
problem that loads onto high streets, and 'other crime' is a residual bucket.
Keeping them in makes a town centre look dangerous to live beside when what it
actually has is shops.
"""
import json, pathlib, re
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "crime" / "street"
OUT = ROOT / "data" / "processed"

# Retail- and residual-heavy categories, excluded from the resident-relevant rate.
NON_RESIDENT = {"Shoplifting", "Other crime"}

COLS = ["Month", "Longitude", "Latitude", "LSOA code", "LSOA name", "Crime type"]


def main():
    files = sorted(SRC.glob("*-street.csv"))
    print(f"{len(files)} monthly files")
    parts = []
    for f in files:
        d = pd.read_csv(f, usecols=COLS, dtype=str)
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    print(f"{len(d):,} crime records")

    d = d.dropna(subset=["LSOA code"])
    # The Met's boundary is Greater London minus the Square Mile, but a handful of
    # records snap to LSOAs just outside it; the borough prefix in the LSOA name is
    # the cleanest filter we have.
    d["borough"] = d["LSOA name"].str.replace(r"\s+\d{3}[A-Z]$", "", regex=True)
    lad = json.loads((ROOT / "data" / "raw" / "london_lad.geojson").read_text())
    boroughs = {f["properties"]["LAD24NM"] for f in lad["features"]}
    keep = d["borough"].isin(boroughs)
    print(f"dropping {(~keep).sum():,} records outside Greater London: "
          f"{sorted(d.loc[~keep, 'borough'].unique())[:8]}")
    d = d[keep]

    months = sorted(d["Month"].unique())
    print(f"{len(months)} months: {months[0]} .. {months[-1]}")

    d["resident_relevant"] = ~d["Crime type"].isin(NON_RESIDENT)
    g = d.groupby(["LSOA code", "LSOA name", "borough"], as_index=False).agg(
        crimes=("Crime type", "size"), resident_relevant=("resident_relevant", "sum"))
    g["months"] = len(months)

    # Per-category counts, wide, so the map can show what kind of crime an area has.
    cat = (d.groupby(["LSOA code", "Crime type"]).size().unstack(fill_value=0))
    cat.columns = ["cat_" + re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in cat.columns]
    g = g.merge(cat.reset_index(), on="LSOA code", how="left")

    g.to_csv(OUT / "crime_lsoa_london.csv", index=False)
    print(f"{len(g):,} LSOAs -> crime_lsoa_london.csv")
    print(g.groupby("borough")["crimes"].sum().sort_values(ascending=False).head(8))


if __name__ == "__main__":
    main()
