"""Every new-build scheme in Zone 1-4 that has started coming back to market.

The shortlist held four developments because four were typed in by hand. The
question behind it -- where can you buy a flat that is three to seven years old,
in a scheme whose resale market already exists, somewhere safe and convenient --
is answerable for the whole city from Price Paid alone.

A scheme is a street within a postcode sector. That is the finest identity Price
Paid carries and it is the same definition the hand-written development list
uses, only found rather than typed. A street qualifies when at least fifteen
new-build flats sold on it since 2016: below that it is a conversion or an infill
block, not a scheme with a resale market.

Resales are second-hand sales on the same street AFTER the first new-build sale
there. That is not enough on its own: an infill block on a Victorian street
would collect the whole terrace's resales as if they were its own. So a street
that already had eight or more flat sales before the scheme started is marked as
carrying pre-existing stock, and its resale figures are withheld rather than
quietly wrong -- the same error that once made Colindale Gardens look 26%
cheaper second-hand, found here at scale.

Shared-ownership sales are the other trap. Land Registry records the price paid
for the SHARE, so Barking Riverside reads as a place where flats resell at
GBP 107k. Anything below half the scheme's own upper quartile is treated as a
part-share and left out of the medians, the same rule the per-square-foot work
uses.

What this does not have is asking prices. Price Paid is registered sales, so it
lags by a couple of months and it says what flats went for, not what is on the
market today. The listings in data/manual are the other half of that and have to
be collected by hand.
"""
import json, pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from osm_layers import load as load_osm, is_premium  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, MAN, OUT = ROOT / "data" / "raw", ROOT / "data" / "manual", ROOT / "data" / "processed"
FROM = "2016-01-01"
MIN_NEW = 15
MIN_RESALE = 5
WALK_M = 800
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * np.cos(np.radians(51.5))


def xy(lat, lon):
    return np.c_[np.asarray(lon, float) * M_PER_DEG_LON, np.asarray(lat, float) * M_PER_DEG_LAT]


def main():
    pc = pd.read_csv(RAW / "postcodes.csv").dropna(subset=["lat", "lon"])
    p = pd.read_csv(RAW / "london_ppd.csv",
                    usecols=["date", "price", "postcode", "ptype", "newbuild", "street",
                             "ppd_cat"], dtype=str)
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    p = p[(p["ptype"] == "F") & (p["ppd_cat"] == "A") & p["price"].gt(1000)]
    p["street"] = p["street"].str.upper()
    p = p.merge(pc, on="postcode", how="inner")
    p["sector"] = p["postcode"].str.extract(r"^(\S+\s\d)")[0]
    p = p.dropna(subset=["street", "sector"])

    new = p[(p["newbuild"] == "Y") & (p["date"] >= FROM)]
    g = new.groupby(["street", "sector"]).agg(
        n_new=("price", "size"), first_new=("date", "min"), last_new=("date", "max"),
        new_median=("price", "median"), lat=("lat", "median"), lon=("lon", "median"),
        lsoa=("lsoa", lambda s: s.mode().iat[0]))
    g = g[g["n_new"] >= MIN_NEW].reset_index()
    print(f"{len(g):,} streets with {MIN_NEW}+ new-build flat sales since {FROM[:4]}")

    # A price floor per scheme: half its own upper quartile. Below that is a share
    # of a flat, not a flat.
    ref = p.merge(g[["street", "sector"]], on=["street", "sector"], how="inner")
    floor = (ref.groupby(["street", "sector"])["price"].quantile(.75) * 0.5).rename("floor")
    g = g.merge(floor, on=["street", "sector"], how="left")
    p = p.merge(floor, on=["street", "sector"], how="left")
    p["part_share"] = p["price"] < p["floor"]
    share = p[p["floor"].notna()].groupby(["street", "sector"])["part_share"].mean().mul(100)
    g = g.merge(share.rename("part_share_pct").round(1), on=["street", "sector"], how="left")

    # Did this street sell flats before the scheme existed? If so its resales are
    # not the scheme's resales.
    before = p.merge(g[["street", "sector", "first_new"]], on=["street", "sector"],
                     how="inner", suffixes=("", "_g"))
    before = before[before["date"] < before["first_new"]]
    nb = before.groupby(["street", "sector"]).size().rename("n_before")
    g = g.merge(nb, on=["street", "sector"], how="left")
    g["n_before"] = g["n_before"].fillna(0).astype(int)
    g["pre_existing_stock"] = g["n_before"] >= 8

    full = p[~p["part_share"]]
    old = full[full["newbuild"] == "N"].merge(g[["street", "sector", "first_new"]],
                                              on=["street", "sector"], how="inner")
    old = old[old["date"] >= old["first_new"]]
    r = old.groupby(["street", "sector"]).agg(
        n_resale=("price", "size"), resale_median=("price", "median"),
        resale_p25=("price", lambda s: s.quantile(.25)), last_resale=("date", "max"))
    g = g.merge(r, on=["street", "sector"], how="left")
    g["n_resale"] = g["n_resale"].fillna(0).astype(int)
    g.loc[g["pre_existing_stock"], ["resale_median", "resale_p25"]] = np.nan

    # The gap is only meaningful against a comparable window, so both sides are
    # taken from 2023 on rather than over the scheme's whole life.
    recent = full[full["date"] >= "2023-01-01"].merge(g[["street", "sector", "first_new"]],
                                                      on=["street", "sector"], how="inner")
    rg = recent.groupby(["street", "sector", "newbuild"])["price"].agg(["size", "median"])
    rg = rg.unstack("newbuild")
    for col in [("size", "Y"), ("size", "N"), ("median", "Y"), ("median", "N")]:
        if col not in rg:
            rg[col] = np.nan
    gap = pd.DataFrame({
        "n_new23": rg[("size", "Y")].fillna(0), "n_resale23": rg[("size", "N")].fillna(0),
        "new_med23": rg[("median", "Y")], "resale_med23": rg[("median", "N")]}).reset_index()
    gap["gap_pct"] = np.where(
        (gap["n_new23"] >= 8) & (gap["n_resale23"] >= 8),
        (gap["resale_med23"] / gap["new_med23"] - 1) * 100, np.nan)
    g = g.merge(gap[["street", "sector", "n_new23", "n_resale23", "gap_pct"]],
                on=["street", "sector"], how="left")
    g.loc[g["pre_existing_stock"], "gap_pct"] = np.nan

    # £/sqft where an EPC area exists for the street.
    psf = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    psf = psf[(psf["date"] >= "2023-01-01") & (~psf["shared_ownership_likely"])].copy()
    psf["sector"] = psf["postcode"].str.extract(r"^(\S+\s\d)")[0]
    q = psf.groupby(["street", "sector"])["psf"].agg(n_psf="size", psf="median")
    q.loc[q["n_psf"] < 8, "psf"] = np.nan
    g = g.merge(q.reset_index(), on=["street", "sector"], how="left")

    # Nearest station, and the fare zone that comes with it.
    st = pd.read_csv(OUT / "stations.csv")
    sxy, gxy = xy(st["lat"], st["lon"]), xy(g["lat"], g["lon"])
    idx, dist = [], []
    for i in range(len(g)):
        d = np.hypot(*(sxy - gxy[i]).T)
        j = int(d.argmin())
        idx.append(j); dist.append(float(d[j]))
    g["station"] = st["name"].values[idx]
    g["zone"] = st["zone"].values[idx]
    g["zone_min"] = st["zone_min"].values[idx]
    g["station_m"] = np.round(dist).astype(int)

    saf = pd.read_csv(OUT / "lsoa_safety.csv").rename(columns={"LSOA code": "lsoa"})
    g = g.merge(saf[["lsoa", "home_per_1000", "resident_per_1000"]], on="lsoa", how="left")

    amen = {k: (v, xy(v["lat"], v["lon"])) for k, v in load_osm().items()}
    for k, (df, axy) in amen.items():
        counts, prem = [], []
        for i in range(len(g)):
            sel = np.flatnonzero(((axy - gxy[i]) ** 2).sum(1) <= WALK_M ** 2)
            counts.append(len(sel))
            if k == "shops":
                prem.append(bool(is_premium(df.iloc[sel]).any()) if len(sel) else False)
        g[f"n_{k}"] = counts
        if k == "shops":
            g["premium_grocer"] = prem

    z = g[g["zone_min"] <= 4].copy()
    z["has_resale"] = z["n_resale"] >= MIN_RESALE
    z = z.sort_values(["n_new"], ascending=False)
    z.to_csv(OUT / "schemes.csv", index=False)
    print(f"{len(z):,} in Zone 1-4; {int(z['has_resale'].sum()):,} with {MIN_RESALE}+ resales; "
          f"{int(z['gap_pct'].notna().sum()):,} with a measurable new-to-resale gap")
    print(f"  {int(z['pre_existing_stock'].sum()):,} carry pre-existing stock "
          f"(resale figures withheld); "
          f"{int((z['part_share_pct'] >= 15).sum()):,} are 15%+ part-share sales")
    print(z.groupby("zone_min")["street"].size().to_string())
    cheap = z[z["has_resale"] & z["resale_median"].le(550_000)
              & z["home_per_1000"].le(60)
              & z["part_share_pct"].lt(15)].nsmallest(12, "resale_median")
    print("\ncheapest safe schemes with a resale market:")
    print(cheap[["street", "sector", "station", "zone", "n_new", "n_resale",
                 "resale_median", "part_share_pct", "home_per_1000",
                 "first_new"]].to_string(index=False))


if __name__ == "__main__":
    main()
