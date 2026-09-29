"""LSOA-level price, volume and newness, to sit beside the crime rates.

Crime was the only thing the map could colour by, which made it the only
question the map could ask. Price Paid is geocoded to a postcode and every
postcode carries its LSOA, so the same 4,994 polygons can carry what flats
actually sold for, how often they sell, and how much of the market is
developer stock.

Volume is the one that is hard to get anywhere else. "Liquidity" in an estate
agent's mouth means a feeling; here it is sales per 1,000 residents per year,
and it separates a place where a flat takes three months to sell from one where
nothing has changed hands since the scheme completed.

A cell is left blank below ten sales. A median of four transactions is not a
price level, and a choropleth that paints it anyway is inventing a map.
"""
import json, pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
RECENT = "2024-01-01"
NEW_WINDOW = "2019-01-01"
MIN_N = 10


def main():
    pc = pd.read_csv(RAW / "postcodes.csv", usecols=["postcode", "lsoa"]).dropna()
    p = pd.read_csv(RAW / "london_ppd.csv",
                    usecols=["date", "price", "postcode", "ptype", "newbuild", "ppd_cat"],
                    dtype=str)
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    # ppd_cat A only: B covers repossessions, buy-to-let portfolios and transfers
    # that are not arm's-length sales, and they sit well below market.
    p = p[(p["ptype"] == "F") & (p["ppd_cat"] == "A") & p["price"].gt(1000)]
    p = p.merge(pc, on="postcode", how="inner")

    recent = p[p["date"] >= RECENT]
    g = recent.groupby("lsoa")["price"].agg(n="size", median="median", p25=lambda s: s.quantile(.25))
    g.loc[g["n"] < MIN_N, ["median", "p25"]] = np.nan

    since19 = p[p["date"] >= NEW_WINDOW]
    nb = since19.groupby("lsoa")["newbuild"].agg(n19="size", new=lambda s: (s == "Y").sum())
    nb["new_pct"] = nb["new"] / nb["n19"] * 100
    nb.loc[nb["n19"] < MIN_N, "new_pct"] = np.nan

    saf = pd.read_csv(OUT / "lsoa_safety.csv").rename(columns={"LSOA code": "lsoa"})
    d = saf[["lsoa", "population", "home_per_1000", "resident_per_1000"]].merge(
        g, on="lsoa", how="left").merge(nb[["n19", "new_pct"]], on="lsoa", how="left")
    d["n"] = d["n"].fillna(0)
    # Price Paid is published to 2026-07 and RECENT starts 2024-01, so the window
    # is 2.5 years; the rate is per year so it can be read against a gut feeling.
    years = 2.5
    d["turnover"] = d["n"] / years / d["population"] * 1000
    d.loc[d["n"] < 3, "turnover"] = np.nan          # a rate off one sale is noise

    psf = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    psf = psf[(psf["date"] >= RECENT) & (~psf["shared_ownership_likely"])].merge(
        pc, on="postcode", how="inner")
    q = psf.groupby("lsoa")["psf"].agg(n_psf="size", psf="median")
    q.loc[q["n_psf"] < MIN_N, "psf"] = np.nan
    d = d.merge(q, on="lsoa", how="left")

    d.to_csv(OUT / "lsoa_metrics.csv", index=False)
    cover = {c: int(d[c].notna().sum()) for c in ("median", "psf", "new_pct", "turnover")}
    print(f"{len(d):,} LSOAs; cells with a value: {cover}")
    for c, lab in (("median", "公寓中位价"), ("psf", "每平尺"), ("new_pct", "新房占比%"),
                   ("turnover", "年成交/千人")):
        s = d[c].dropna()
        print(f"  {lab:12s} p10 {s.quantile(.1):>9,.0f}  median {s.median():>9,.0f}  "
              f"p90 {s.quantile(.9):>9,.0f}")


if __name__ == "__main__":
    main()
