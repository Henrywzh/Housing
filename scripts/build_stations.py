"""Station catchments: the unit a London buyer actually chooses between.

A borough is too big to decide anything -- Greenwich contains both Blackheath
and North Greenwich -- and an LSOA is too small to have a housing market. What a
buyer picks is a station and the ten minutes around it, so that is the unit:
every London rail station, and a 800m walk from it.

Each catchment gets the three things the brief asks for, measured the same way
everywhere so they can be ranked against each other:

  safe        population-weighted crime over the LSOAs in the circle
  good value  median flat price from Price Paid, and per square foot where an
              EPC match exists
  convenient  fare zone, how many lines, and what is within the same 800m --
              supermarkets, parks, schools, cafes

Distances are computed on a local equirectangular projection. Over 800m at
London's latitude the error against a great circle is under a metre, and the
whole point is to be honest about a ten-minute walk, not to survey land.
"""
import json, pathlib, re, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from osm_layers import load as load_osm, is_premium  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
WALK_M = 800
LAT0 = 51.5
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * np.cos(np.radians(LAT0))
RECENT = "2024-01-01"


def xy(lat, lon):
    return np.c_[np.asarray(lon, float) * M_PER_DEG_LON, np.asarray(lat, float) * M_PER_DEG_LAT]


def within(sxy, pxy, r=WALK_M):
    """Indices of points within r metres of each station, as a list of arrays."""
    out = []
    for i in range(len(sxy)):
        d2 = ((pxy - sxy[i]) ** 2).sum(1)
        out.append(np.flatnonzero(d2 <= r * r))
    return out


def centroids(path):
    g = json.loads(path.read_text())
    code, lat, lon = [], [], []
    for f in g["features"]:
        pts = []
        gm = f["geometry"]
        polys = gm["coordinates"] if gm["type"] == "MultiPolygon" else [gm["coordinates"]]
        for p in polys:
            pts += p[0]
        a = np.array(pts, float)
        code.append(f["properties"]["LSOA21CD"])
        lon.append(a[:, 0].mean()); lat.append(a[:, 1].mean())
    return pd.DataFrame({"LSOA code": code, "lat": lat, "lon": lon})


def norm(n):
    return re.sub(r"\s*\(.*?\)", "", n).replace(" and ", " & ").replace("'", "").strip().lower()


def dedupe(s):
    """One interchange, one row.

    TfL gives Canary Wharf three NaPTAN ids and Abbey Wood two, because the tube,
    the DLR and National Rail are separate stop points. A buyer sees one place, and
    leaving them apart both double-counts the place in any ranking and understates
    how many lines it has. Same name within a kilometre is the same place."""
    s = s.copy()
    s["key"] = s["name"].map(norm)
    keep = []
    for k, g in s.groupby("key", sort=False):
        if len(g) > 1:
            d = xy(g["lat"], g["lon"])
            if ((d - d.mean(0)) ** 2).sum(1).max() ** .5 > 1000:
                keep += [r for _, r in g.iterrows()]     # same name, different place
                continue
        r = g.iloc[0].copy()
        r["lat"], r["lon"] = g["lat"].mean(), g["lon"].mean()
        r["lines"] = sorted({x for v in g["lines"] for x in v})
        r["modes"] = sorted({x for v in g["modes"] for x in v})
        r["zone"] = sorted(g["zone"].dropna(), key=lambda z: (str(z)[0], str(z)))[0]
        r["name"] = min(g["name"], key=len)
        keep.append(r)
    return pd.DataFrame(keep).reset_index(drop=True)


def main():
    st = json.loads((RAW / "transport" / "stations.json").read_text())
    s = dedupe(pd.DataFrame([{"id": k, **v} for k, v in st.items()]))
    s["n_lines"] = s["lines"].str.len()
    # Zones are strings because a station on a boundary is in two of them
    # ("2+3", "2/3"); the lower number is the one that sets the fare.
    s["zone_min"] = pd.to_numeric(s["zone"].str.extract(r"(\d)")[0], errors="coerce")
    sxy = xy(s["lat"], s["lon"])

    pc = pd.read_csv(RAW / "postcodes.csv").dropna(subset=["lat", "lon"])
    ppd = pd.read_csv(RAW / "london_ppd.csv",
                      usecols=["date", "price", "postcode", "ptype", "newbuild", "street"],
                      dtype={"postcode": str})
    ppd = ppd[(ppd["ptype"] == "F") & (ppd["date"] >= RECENT)].merge(
        pc[["postcode", "lat", "lon", "LSOA code" if "LSOA code" in pc else "lsoa"]]
        .rename(columns={"lsoa": "LSOA code"}), on="postcode", how="inner")
    print(f"{len(ppd):,} flat sales since {RECENT} with coordinates")
    txy = xy(ppd["lat"], ppd["lon"])

    psf = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    psf = psf[(psf["date"] >= RECENT) & (~psf["shared_ownership_likely"])].merge(
        pc[["postcode", "lat", "lon"]], on="postcode", how="inner")
    fxy = xy(psf["lat"], psf["lon"])

    saf = pd.read_csv(OUT / "lsoa_safety.csv").merge(centroids(RAW / "lsoa_london_bgc.geojson"),
                                                     on="LSOA code", how="inner")
    lxy = xy(saf["lat"], saf["lon"])

    amen = {k: (v, xy(v["lat"], v["lon"])) for k, v in load_osm().items()}
    print("amenity layers:", {k: len(v[0]) for k, v in amen.items()})

    rows = []
    near_t, near_f, near_l = within(sxy, txy), within(sxy, fxy), within(sxy, lxy)
    near_a = {k: within(sxy, v[1]) for k, v in amen.items()}
    for i, r in s.iterrows():
        t = ppd.iloc[near_t[i]]
        f = psf.iloc[near_f[i]]
        l = saf.iloc[near_l[i]].dropna(subset=["resident_per_1000"])
        w = l["population"]
        rec = {"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
               "zone": r["zone"], "zone_min": r["zone_min"], "n_lines": r["n_lines"],
               "lines": r["lines"], "modes": r["modes"],
               "n_sales": len(t),
               "median_price": t["price"].median() if len(t) >= 20 else np.nan,
               "p25_price": t["price"].quantile(.25) if len(t) >= 20 else np.nan,
               "n_new": int((t["newbuild"] == "Y").sum()),
               "n_psf": len(f),
               "psf": f["psf"].median() if len(f) >= 20 else np.nan,
               "sqft": f["sqft"].median() if len(f) >= 20 else np.nan,
               "n_lsoa": len(l), "population": int(w.sum()) if len(l) else 0,
               "resident_per_1000": float(np.average(l["resident_per_1000"], weights=w)) if len(l) else np.nan,
               "home_per_1000": float(np.average(l["home_per_1000"], weights=w)) if len(l) else np.nan}
        for k, idx in near_a.items():
            rec[f"n_{k}"] = len(idx[i])
        if "shops" in amen:
            sh = amen["shops"][0].iloc[near_a["shops"][i]]
            rec["n_supermarket"] = int((sh["kind"] == "supermarket").sum())
            # Waitrose and M&S Food are where they are because a retailer's own
            # catchment model said the households around them could afford it. It
            # is a second opinion on the area, formed independently of ours.
            rec["premium_grocer"] = bool(is_premium(sh).any()) if len(sh) else False
        rows.append(rec)

    d = pd.DataFrame(rows)
    d.to_csv(OUT / "stations.csv", index=False)
    z = d[d["zone_min"] <= 4]
    print(f"{len(d)} stations, {len(z)} in Zone 1-4, "
          f"{z['median_price'].notna().sum()} with 20+ recent flat sales")
    print(z.nsmallest(12, "median_price")[
        ["name", "zone", "median_price", "n_sales", "home_per_1000", "n_shops",
         "premium_grocer"]].to_string(index=False))


if __name__ == "__main__":
    main()
