"""Every new-build scheme in Zone 1-4 that has started coming back to market.

The shortlist held four developments because four were typed in by hand. The
question behind it -- where can you buy a flat that is three to seven years old,
in a scheme whose resale market already exists, somewhere safe and convenient --
is answerable for the whole city from Price Paid alone.

A scheme is a unit postcode. That is the finest identity Price Paid carries that
survives from one sale to the next. The street is too coarse -- "College Road,
Harrow" pooled 220 new flats from several schemes and was then withheld as
carrying pre-existing stock, so Bond Apartments never appeared -- and the
address text is too unstable: the first sale of a flat in Bond Apartments is
recorded as "PERCEVAL SQUARE, FLAT 34 BOND APARTMENTS" and a resale of another as
"BOND APARTMENTS, FLAT 13". A block of flats almost always has a postcode to
itself, and that postcode does not change when the clerk's wording does.
A postcode qualifies when at least fifteen new-build flats sold in it since
2016: below that it is a conversion or an infill block, not a scheme with a
resale market. Its name is read back from the address lines ("Bond Apartments").

Resales are second-hand sales in the same postcode AFTER the first new-build sale
there. That is not enough on its own: a new block next to an old terrace that
shares its postcode would collect the terrace's resales as its own. So a postcode
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
import json, pathlib, re, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from osm_layers import load as load_osm, is_premium  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, MAN, OUT = ROOT / "data" / "raw", ROOT / "data" / "manual", ROOT / "data" / "processed"
FROM = "2016-01-01"
MAX_ZONE = 6
MIN_NEW = 15
MIN_RESALE = 5
WALK_M = 800
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * np.cos(np.radians(51.5))


def xy(lat, lon):
    return np.c_[np.asarray(lon, float) * M_PER_DEG_LON, np.asarray(lat, float) * M_PER_DEG_LAT]


UNIT = re.compile(r"^(?:FLAT|APARTMENT|APT|UNIT|ROOM|STUDIO|PENTHOUSE|MAISONETTE)\s*[\dA-Z]{1,5}\b[\s,]*")


def block_name(rows):
    """The name the address lines give the block, else '<number> <street>'.

    The flat's own line ("FLAT 34 BOND APARTMENTS") names the block more often
    than the building line does, so it is read first; a bare "12" is a unit.
    """
    cands = []
    for saon, paon in zip(rows["saon"].fillna("").str.upper(), rows["paon"].fillna("").str.upper()):
        n = UNIT.sub("", saon).strip(" ,")
        if len(re.findall(r"[A-Z]{3,}", n)):
            cands.append(n)
    if not cands:
        for paon in rows["paon"].fillna("").str.upper():
            n = re.sub(r",?\s*\d+[A-Z]?$", "", paon).strip(" ,")
            if re.search(r"[A-Z]{3,}", n):
                cands.append(n)
    if cands:
        # "Trinity Square, 23 - 40" is a range of door numbers, not part of the name.
        n = pd.Series(cands).mode().iat[0]
        return re.sub(r"[\s,]*\d+[A-Z]?(?:\s*[-–]\s*\d*[A-Z]?)?\s*$", "", n).strip(" ,-").title() or n.title()
    num = rows["paon"].fillna("").mode()
    st = rows["street"].mode()
    return f"{num.iat[0] if len(num) else ''} {st.iat[0] if len(st) else ''}".strip().title()


def main():
    pc = pd.read_csv(RAW / "postcodes.csv").dropna(subset=["lat", "lon"])
    p = pd.read_csv(RAW / "london_ppd.csv",
                    usecols=["date", "price", "postcode", "ptype", "newbuild", "street",
                             "paon", "saon", "ppd_cat"], dtype=str)
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    p = p[(p["ptype"] == "F") & (p["ppd_cat"] == "A") & p["price"].gt(1000)]
    p["street"] = p["street"].fillna("").str.upper()
    p = p.merge(pc, on="postcode", how="inner")
    p["sector"] = p["postcode"].str.extract(r"^(\S+\s\d)")[0]
    p = p.dropna(subset=["sector"])

    new = p[(p["newbuild"] == "Y") & (p["date"] >= FROM)]
    g = new.groupby("postcode").agg(
        n_new=("price", "size"), first_new=("date", "min"), last_new=("date", "max"),
        new_median=("price", "median"), lat=("lat", "first"), lon=("lon", "first"),
        lsoa=("lsoa", "first"), sector=("sector", "first"),
        street=("street", lambda s: s.mode().iat[0] if len(s.mode()) else ""))
    g = g[g["n_new"] >= MIN_NEW].reset_index()
    names = new[new["postcode"].isin(g["postcode"])].groupby("postcode").apply(block_name)
    g["label"] = g["postcode"].map(names)
    print(f"{len(g):,} postcodes with {MIN_NEW}+ new-build flat sales since {FROM[:4]}")

    # A price floor per scheme: half its own upper quartile. Below that is a share
    # of a flat, not a flat.
    ref = p.merge(g[["postcode"]], on="postcode", how="inner")
    floor = (ref.groupby(["postcode"])["price"].quantile(.75) * 0.5).rename("floor")
    g = g.merge(floor, on="postcode", how="left")
    p = p.merge(floor, on="postcode", how="left")
    p["part_share"] = p["price"] < p["floor"]
    share = p[p["floor"].notna()].groupby(["postcode"])["part_share"].mean().mul(100)
    g = g.merge(share.rename("part_share_pct").round(1), on="postcode", how="left")

    # Did this postcode sell flats before the scheme existed? If so its resales are
    # not the scheme's resales.
    before = p.merge(g[["postcode", "first_new"]], on="postcode",
                     how="inner", suffixes=("", "_g"))
    before = before[before["date"] < before["first_new"]]
    nb = before.groupby(["postcode"]).size().rename("n_before")
    g = g.merge(nb, on="postcode", how="left")
    g["n_before"] = g["n_before"].fillna(0).astype(int)
    g["pre_existing_stock"] = g["n_before"] >= 8

    full = p[~p["part_share"]]
    old = full[full["newbuild"] == "N"].merge(g[["postcode", "first_new"]],
                                              on="postcode", how="inner")
    old = old[old["date"] >= old["first_new"]]
    r = old.groupby(["postcode"]).agg(
        n_resale=("price", "size"), resale_median=("price", "median"),
        resale_p25=("price", lambda s: s.quantile(.25)), last_resale=("date", "max"))
    g = g.merge(r, on="postcode", how="left")
    g["n_resale"] = g["n_resale"].fillna(0).astype(int)
    # A resale median far below the scheme's own new-build median is almost never
    # a market: Land Registry records a shared-ownership sale at the price of the
    # share, and a resale of a 40% share reads as a flat that fell 60%. The
    # part-share floor above catches schemes where some sales are shares; this
    # catches the ones where all of them are.
    g["share_suspect"] = (g["resale_median"] / g["new_median"] < 0.70) & (g["n_resale"] >= 3)
    g.loc[g["pre_existing_stock"] | g["share_suspect"], ["resale_median", "resale_p25"]] = np.nan

    # The gap is only meaningful against a comparable window, so both sides are
    # taken from 2023 on rather than over the scheme's whole life.
    recent = full[full["date"] >= "2023-01-01"].merge(g[["postcode", "first_new"]],
                                                      on="postcode", how="inner")
    rg = recent.groupby(["postcode", "newbuild"])["price"].agg(["size", "median"])
    rg = rg.unstack("newbuild")
    for col in [("size", "Y"), ("size", "N"), ("median", "Y"), ("median", "N")]:
        if col not in rg:
            rg[col] = np.nan
    gap = pd.DataFrame({
        "n_new23": rg[("size", "Y")].fillna(0), "n_resale23": rg[("size", "N")].fillna(0),
        "new_med23": rg[("median", "Y")], "resale_med23": rg[("median", "N")]}).reset_index()
    gap["gap_pct"] = np.where(
        (gap["n_new23"] >= 5) & (gap["n_resale23"] >= 5),
        (gap["resale_med23"] / gap["new_med23"] - 1) * 100, np.nan)
    g = g.merge(gap[["postcode", "n_new23", "n_resale23", "gap_pct"]],
                on="postcode", how="left")
    g.loc[g["pre_existing_stock"] | g["share_suspect"], "gap_pct"] = np.nan

    # £/sqft where an EPC area exists for the postcode.
    psf = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    psf = psf[(psf["date"] >= "2023-01-01") & (~psf["shared_ownership_likely"])].copy()
    psf["sector"] = psf["postcode"].str.extract(r"^(\S+\s\d)")[0]
    q = psf.groupby(["postcode"])["psf"].agg(n_psf="size", psf="median")
    q.loc[q["n_psf"] < 8, "psf"] = np.nan
    g = g.merge(q.reset_index(), on="postcode", how="left")

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

    soc = pd.read_csv(OUT / "lsoa_social.csv")
    g = g.merge(soc[["lsoa", "home_per_1000", "resident_per_1000", "burglary_per_1000_hh",
                     "burglary_resid_per_1000_hh", "residential_share",
                     "vehicle_per_1000_cars", "visitor_share"]], on="lsoa", how="left")

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

    z = g[g["zone_min"] <= MAX_ZONE].copy()
    z["has_resale"] = z["n_resale"] >= MIN_RESALE
    z = z.sort_values(["n_new"], ascending=False)
    z.to_csv(OUT / "schemes.csv", index=False)
    print(f"{len(z):,} in Zone 1-{MAX_ZONE}; {int(z['has_resale'].sum()):,} with {MIN_RESALE}+ resales; "
          f"{int(z['gap_pct'].notna().sum()):,} with a measurable new-to-resale gap")
    print(f"  {int(z['share_suspect'].sum()):,} look like shared ownership (resale far below new), withheld")
    print(f"  {int(z['pre_existing_stock'].sum()):,} carry pre-existing stock "
          f"(resale figures withheld); "
          f"{int((z['part_share_pct'] >= 15).sum()):,} are 15%+ part-share sales")
    print(z.groupby("zone_min")["street"].size().to_string())
    cheap = z[z["has_resale"] & z["resale_median"].le(550_000)
              & z["home_per_1000"].le(60)
              & z["part_share_pct"].lt(15)].nsmallest(12, "resale_median")
    print("\ncheapest safe schemes with a resale market:")
    print(cheap[["label", "postcode", "station", "zone", "n_new", "n_resale",
                 "resale_median", "part_share_pct", "home_per_1000",
                 "first_new"]].to_string(index=False))


if __name__ == "__main__":
    main()
