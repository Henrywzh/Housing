"""Aggregate London Price Paid rows into flat-vs-house x new-vs-existing series.

Why this file exists: the UK HPI publishes a flat series and a new-build series,
but never the two crossed. Only transaction-level data can tell you what a NEW
FLAT sold for as distinct from an existing one -- which is the relevant cut if you
are buying a new-build one-bed and will eventually sell it as a second-hand one.

Caveats baked into the output, not hidden:
  * These are MEDIAN ACHIEVED PRICES, not mix-adjusted like the HPI. A quarter in
    which one tower of studios completes will drag a borough's new-flat median down
    even if nothing repriced. Always read alongside the `n` column.
  * PPD has no floor area, so "new-build premium" here is NOT like-for-like per sqft.
  * Category B sales (repossessions, bulk transfers, right-to-buy) are dropped.
  * New-build registrations lag; the most recent 2 quarters are usually incomplete.
"""
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "london_ppd.csv"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

# Curated submarkets -> postcode sectors. The script prints the top streets in each
# so the mapping can be eyeballed rather than trusted blindly.
SUBMARKETS = {
    "Nine Elms / Battersea":   ["SW8 5", "SW11 8"],
    "Canary Wharf":            ["E14 5", "E14 9", "E14 3"],
    "North Greenwich":         ["SE10 0"],
    "Canada Water":            ["SE16 7"],
    "Stratford":               ["E15 1", "E15 2", "E20 1"],
    "Canning Town / Royal Docks": ["E16 1", "E16 2"],
    "Wembley Park":            ["HA9 0", "HA9 8"],
    "North Acton":             ["W3 6", "NW10 7"],
    "White City":              ["W12 7"],
    "Elephant & Castle":       ["SE1 6", "SE17 1"],
}
SECTOR_TO_MKT = {s: m for m, ss in SUBMARKETS.items() for s in ss}

df = pd.read_csv(SRC, dtype=str, on_bad_lines="skip")
df["price"] = pd.to_numeric(df["price"], errors="coerce")
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df = df.dropna(subset=["price", "date"])
df = df[(df["ppd_cat"] == "A") & (df["price"] > 1000)]

df["seg"] = np.where(df["ptype"] == "F", "flat",
             np.where(df["ptype"].isin(["D", "S", "T"]), "house", "other"))
df = df[df["seg"] != "other"]
df["build"] = np.where(df["newbuild"] == "Y", "new", "existing")
df["q"] = df["date"].dt.to_period("Q").astype(str)
df["year"] = df["date"].dt.year
pc = df["postcode"].fillna("")
df["sector"] = pc.str.replace(r"^(\S+)\s+(\d).*$", r"\1 \2", regex=True).where(pc.str.contains(" "), None)
df["market"] = df["sector"].map(SECTOR_TO_MKT)

def agg(g):
    return pd.Series({"n": len(g), "median": g["price"].median(),
                      "p25": g["price"].quantile(.25), "p75": g["price"].quantile(.75)})

# ---- borough x quarter x seg x build -------------------------------------
bq = df.groupby(["district", "q", "seg", "build"]).apply(agg, include_groups=False).reset_index()
bq.to_csv(OUT / "ppd_borough_quarter.csv", index=False)

# ---- submarket x year x seg x build --------------------------------------
sm = df.dropna(subset=["market"]).groupby(["market", "year", "seg", "build"]) \
       .apply(agg, include_groups=False).reset_index()
sm.to_csv(OUT / "ppd_submarket_year.csv", index=False)

# which borough each submarket actually sits in, taken from the data rather than asserted
meta = (df.dropna(subset=["market"]).groupby("market")
          .agg(district=("district", lambda x: x.mode().iat[0]), n=("price", "size"))
          .reset_index())
meta["sectors"] = meta["market"].map(lambda m: " ".join(SUBMARKETS[m]))
meta.to_csv(OUT / "ppd_submarket_meta.csv", index=False)

# London-wide flat medians by year, as the reference line for every submarket panel
lonq = (df[df.seg == "flat"].groupby(["q", "build"])
          .apply(agg, include_groups=False).reset_index())
lonq.to_csv(OUT / "ppd_london_flat_quarter.csv", index=False)

lon = (df[df.seg == "flat"].groupby(["year", "build"])
         .apply(agg, include_groups=False).reset_index())
lon.to_csv(OUT / "ppd_london_flat_year.csv", index=False)

print(f"rows used        : {len(df):,}")
print(f"date range       : {df['date'].min().date()} .. {df['date'].max().date()}")
print(f"flats            : {(df.seg=='flat').sum():,}  ({(df.seg=='flat').mean()*100:.1f}%)")
print(f"new-build        : {(df.build=='new').sum():,}  ({(df.build=='new').mean()*100:.1f}%)")
print(f"new-build flats  : {((df.seg=='flat')&(df.build=='new')).sum():,}")
print(f"borough rows out : {len(bq):,}   submarket rows out : {len(sm):,}")

print("\n=== submarket sanity check: top streets by new-build flat sales ===")
nf = df[(df.seg == "flat") & (df.build == "new")].dropna(subset=["market"])
for m in SUBMARKETS:
    sub = nf[nf.market == m]
    if not len(sub):
        print(f"{m:28s} (no new-build flats yet in downloaded years)")
        continue
    top = sub["street"].value_counts().head(4)
    print(f"{m:28s} n={len(sub):>6,}  " + "; ".join(f"{s} ({c})" for s, c in top.items()))
