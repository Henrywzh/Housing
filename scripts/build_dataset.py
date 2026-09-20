"""Build a combined London borough house-price + rent panel from ONS / HM Land Registry.

Sources (full history, downloaded into data/raw):
  * UK House Price Index full file  -- monthly, from 1995-01, HM Land Registry
  * ONS Price Index of Private Rents (PIPR) -- monthly, from 2015-01
  * ONS Open Geography borough boundaries (BGC generalised)
"""
import json
import pathlib
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

HPI_FILE = RAW / "UK-HPI-full-file-2026-07.csv"
PIPR_FILE = RAW / "pipr-2026-09.xlsx"
GEO_FILE = RAW / "london_lad_bgc.geojson"

# ---------------------------------------------------------------- house prices
hpi_cols = [
    "Date", "RegionName", "AreaCode", "AveragePrice", "Index", "12m%Change",
    "SalesVolume", "FlatPrice", "Flat12m%Change", "TerracedPrice",
    "SemiDetachedPrice", "DetachedPrice", "NewPrice", "OldPrice",
    "FTBPrice", "FTB12m%Change", "New12m%Change", "NewSalesVolume",
    "Old12m%Change", "OldSalesVolume",
]
hpi = pd.read_csv(HPI_FILE, usecols=lambda c: c in hpi_cols, low_memory=False)
hpi["Date"] = pd.to_datetime(hpi["Date"], dayfirst=True, format="mixed")
hpi = hpi[hpi["AreaCode"].astype(str).str.startswith("E09") | hpi["AreaCode"].isin(["E12000007", "K02000001", "E92000001"])]
hpi = hpi.rename(columns={
    "AreaCode": "code", "RegionName": "name", "Date": "date",
    "AveragePrice": "price", "12m%Change": "price_yoy", "Index": "price_index",
    "SalesVolume": "sales", "FlatPrice": "flat_price", "Flat12m%Change": "flat_yoy",
    "TerracedPrice": "terraced_price", "SemiDetachedPrice": "semi_price",
    "DetachedPrice": "detached_price", "NewPrice": "new_price", "OldPrice": "old_price",
    "FTBPrice": "ftb_price", "FTB12m%Change": "ftb_yoy",
    "New12m%Change": "new_yoy", "NewSalesVolume": "new_sales",
    "Old12m%Change": "old_yoy", "OldSalesVolume": "old_sales",
})
hpi["ym"] = hpi["date"].dt.strftime("%Y-%m")

# ---------------------------------------------------------------------- rents
pipr = pd.read_excel(PIPR_FILE, sheet_name="Table 1", header=2)
keep = {
    "Time period": "date", "Area code": "code", "Area name": "name",
    "Annual change": "rent_yoy", "Rental price": "rent",
    "Annual change one bed": "rent1_yoy", "Rental price one bed": "rent1",
    "Rental price two bed": "rent2", "Annual change two bed": "rent2_yoy",
    "Rental price flat maisonette": "rent_flat",
    "Annual change flat maisonette": "rent_flat_yoy",
    "Index": "rent_index",
}
pipr = pipr[[c for c in keep if c in pipr.columns]].rename(columns=keep)
pipr = pipr[pipr["code"].astype(str).str.startswith("E09") | pipr["code"].isin(["E12000007", "K02000001", "E92000001"])]
pipr["date"] = pd.to_datetime(pipr["date"])
pipr["ym"] = pipr["date"].dt.strftime("%Y-%m")
for c in pipr.columns:
    if c not in ("date", "code", "name", "ym"):
        pipr[c] = pd.to_numeric(pipr[c], errors="coerce")   # '[x]' / '[z]' -> NaN

# --------------------------------------------------------------------- merge
panel = hpi.merge(pipr.drop(columns=["name", "date"]), on=["code", "ym"], how="outer")
panel["name"] = panel.groupby("code")["name"].transform(lambda s: s.ffill().bfill())
panel["ym"] = panel["ym"].astype(str)
panel = panel.sort_values(["code", "ym"])

# gross yields: whole-stock, and flat-vs-flat (the apples-to-apples one)
# new-build vs existing, from the HPI's own mix-adjusted series
panel["new_premium"] = (panel["new_price"] / panel["old_price"] - 1) * 100
panel["new_share"] = panel["new_sales"] / panel["sales"] * 100

panel["yield_gross"] = panel["rent"] * 12 / panel["price"] * 100
panel["yield_flat"] = panel["rent_flat"] * 12 / panel["flat_price"] * 100
panel["yield_1bed_flat"] = panel["rent1"] * 12 / panel["flat_price"] * 100
# rent/price ratio rebased to Jan-2015 = 100 -> "is cashflow beating capital value?"
base = panel[panel["ym"] == "2015-01"].set_index("code")
panel["rent_vs_price"] = panel.apply(
    lambda r: (r["rent"] / r["price"]) / (base["rent"].get(r["code"], np.nan) / base["price"].get(r["code"], np.nan)) * 100
    if r["code"] in base.index else np.nan, axis=1)

# ---- flat x new/existing, from Price Paid transactions (quarterly, held flat
#      across the months of each quarter so it shares the monthly timeline) ----
ppd_path = OUT / "ppd_borough_quarter.csv"
if ppd_path.exists():
    name2code = (hpi[["name", "code"]].drop_duplicates()
                 .assign(key=lambda d: d["name"].str.upper()).set_index("key")["code"].to_dict())
    pp = pd.read_csv(ppd_path)
    pp = pp[pp["seg"] == "flat"]
    pp["code"] = pp["district"].str.upper().map(name2code)
    # the London-wide aggregate, so the default panel is not empty
    lq = OUT / "ppd_london_flat_quarter.csv"
    if lq.exists():
        lon_q = pd.read_csv(lq).assign(code="E12000007", district="LONDON", seg="flat")
        pp = pd.concat([pp, lon_q], ignore_index=True)
    missing = sorted(pp.loc[pp["code"].isna(), "district"].unique())
    if missing:
        print("WARN unmatched PPD districts:", missing)
    pp = pp.dropna(subset=["code"])
    w = pp.pivot_table(index=["code", "q"], columns="build",
                       values=["median", "n"], aggfunc="first")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    w = w.reset_index().rename(columns={"median_new": "pf_new", "median_existing": "pf_old",
                                        "n_new": "pf_n_new", "n_existing": "pf_n_old"})
    for c in ("pf_new", "pf_old", "pf_n_new", "pf_n_old"):
        if c not in w:
            w[c] = np.nan
    w["pf_prem"] = (w["pf_new"] / w["pf_old"] - 1) * 100
    w["pf_n"] = w[["pf_n_new", "pf_n_old"]].sum(axis=1, min_count=1)
    w["pf_newshare"] = w["pf_n_new"] / w["pf_n"] * 100
    # suppress medians computed off a thin sample -- they are noise, not signal
    w.loc[w["pf_n_new"] < 10, ["pf_new", "pf_prem"]] = np.nan
    w.loc[w["pf_n_old"] < 10, ["pf_old", "pf_prem"]] = np.nan

    panel["q"] = pd.PeriodIndex(pd.to_datetime(panel["ym"] + "-01"), freq="Q").astype(str)
    panel = panel.merge(w[["code", "q", "pf_new", "pf_old", "pf_prem", "pf_newshare", "pf_n"]],
                        on=["code", "q"], how="left")
    print(f"PPD flat series merged: {w['code'].nunique()} boroughs, "
          f"{w['q'].min()} .. {w['q'].max()}")
else:
    print("PPD aggregates not built yet -- skipping flat new/old series")

panel.to_parquet(OUT / "london_panel.parquet", index=False)
panel.to_csv(OUT / "london_panel.csv", index=False)

# --------------------------------------------------- compact json for the map
METRICS = ["price", "price_yoy", "flat_price", "flat_yoy", "sales",
           "new_price", "new_yoy", "old_price", "old_yoy", "new_premium", "new_share",
           "rent", "rent_yoy", "rent1", "rent1_yoy", "rent_flat", "rent_flat_yoy",
           "yield_gross", "yield_flat", "yield_1bed_flat", "rent_vs_price",
           "price_index", "rent_index",
           "pf_new", "pf_old", "pf_prem", "pf_newshare", "pf_n"]

months = [m for m in sorted(panel["ym"].dropna().unique()) if m >= "1995-01"]
areas = {}
for code, g in panel.groupby("code"):
    g = g.set_index("ym").reindex(months)
    rec = {"name": str(g["name"].dropna().iloc[0]) if g["name"].notna().any() else code}
    for m in METRICS:
        if m not in g:
            continue
        s = g[m]
        dec = 0 if m in ("price", "flat_price", "rent", "rent1", "rent2", "rent_flat",
                         "sales", "new_price", "old_price", "pf_new", "pf_old", "pf_n") else 2
        rec[m] = [None if pd.isna(v) else round(float(v), dec) for v in s]
    areas[code] = rec

# ---------------------------------------------- submarket (postcode-sector) layer
def year_series(df, years, build, col, nmin=10):
    d = df[df["build"] == build].set_index("year")
    out = []
    for y in years:
        if y not in d.index or d.loc[y, "n"] < nmin:
            out.append(None)
        else:
            out.append(round(float(d.loc[y, col])))
    return out

submarkets = {}
london_flat = {}
sm_path = OUT / "ppd_submarket_year.csv"
if sm_path.exists():
    meta = pd.read_csv(OUT / "ppd_submarket_meta.csv")
    sm = pd.read_csv(sm_path)
    sm = sm[sm["seg"] == "flat"]
    lf = pd.read_csv(OUT / "ppd_london_flat_year.csv")
    YEARS = list(range(2000, int(sm["year"].max()) + 1))
    name2code = (hpi[["name", "code"]].drop_duplicates()
                 .assign(key=lambda d: d["name"].str.upper()).set_index("key")["code"].to_dict())
    for _, m in meta.iterrows():
        g = sm[sm["market"] == m["market"]]
        submarkets[m["market"]] = {
            "district": m["district"].title(), "code": name2code.get(m["district"]),
            "sectors": m["sectors"], "n": int(m["n"]),
            "old_med": year_series(g, YEARS, "existing", "median"),
            "old_p25": year_series(g, YEARS, "existing", "p25"),
            "old_n":   year_series(g, YEARS, "existing", "n", nmin=1),
            "new_med": year_series(g, YEARS, "new", "median"),
            "new_p25": year_series(g, YEARS, "new", "p25"),
            "new_n":   year_series(g, YEARS, "new", "n", nmin=1),
        }
    london_flat = {
        "years": YEARS,
        "old_med": year_series(lf, YEARS, "existing", "median", nmin=50),
        "new_med": year_series(lf, YEARS, "new", "median", nmin=50),
    }
    print(f"submarkets       : {len(submarkets)}  years {YEARS[0]}..{YEARS[-1]}")

geo = json.loads(GEO_FILE.read_text())
payload = {
    "months": months,
    "areas": areas,
    "submarkets": submarkets,
    "london_flat": london_flat,
    "meta": {
        "hpi_vintage": "2026-07 (HM Land Registry UK HPI, published 2026-09-16)",
        "pipr_vintage": "2026-08 (ONS Price Index of Private Rents, published 2026-09-16)",
        "price_history_from": min(m for m in months),
        "rent_history_from": "2015-01",
    },
}
(OUT / "map_data.json").write_text(json.dumps(payload, separators=(",", ":")))
(OUT / "london_boroughs.geojson").write_text(json.dumps(geo, separators=(",", ":")))

print(f"months           : {months[0]} .. {months[-1]}  ({len(months)})")
print(f"areas            : {len(areas)}")
print(f"panel rows       : {len(panel):,}")
px = panel.dropna(subset=['price']); rx = panel.dropna(subset=['rent'])
print(f"price coverage   : {px['ym'].min()} .. {px['ym'].max()}")
print(f"rent  coverage   : {rx['ym'].min()} .. {rx['ym'].max()}")
print(f"map_data.json    : {(OUT/'map_data.json').stat().st_size/1e6:.2f} MB")
print(f"geojson          : {(OUT/'london_boroughs.geojson').stat().st_size/1e3:.0f} KB")
