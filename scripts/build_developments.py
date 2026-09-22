"""Development-level £/sqft: what you buy new at, and what the same scheme resells for.

The submarket tables answer "is this area expensive". This answers the question
the five-year plan actually turns on: you buy a new flat, and five or ten years
later you sell it into the second-hand market of that same development. The gap
between the two prices, measured per square foot inside one scheme, is the
haircut -- and it is not the same everywhere.

Street is the only development identifier Price Paid carries, so a scheme is
defined as its set of streets. The mapping is written out rather than inferred,
so it can be checked and corrected.
"""
import json, pathlib, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

DEVELOPMENTS = {
    "Embassy Gardens": ["VIADUCT GARDENS", "CARNATION WAY", "NEW UNION SQUARE",
                        "PONTON ROAD", "CHARLES CLOWES WALK"],
    "Battersea Power Station": ["CIRCUS ROAD WEST", "CIRCUS ROAD EAST",
                                "CIRCUS ROAD SOUTH", "CIRCUS ROAD NORTH",
                                "ELECTRIC BOULEVARD", "PROSPECT WAY"],
    "Riverlight": ["RIVERLIGHT QUAY"],
    "Nine Elms Point": ["MALTHOUSE ROAD", "LANCHESTER WAY", "AURORA GARDENS"],
    "Wood Wharf (狗岛)": ["PARK DRIVE", "WARDS PLACE", "HARBORD SQUARE", "CHARTER STREET"],
    "South Quay / Marsh Wall (狗岛)": ["MARSH WALL", "SELSDON WAY", "HARBOUR WAY",
                                       "LINCOLN PLAZA", "MILLHARBOUR"],
    "Royal Wharf": ["ROYAL WHARF WALK", "BONNET STREET", "ROYAL CREST AVENUE",
                    "CLIPPER STREET", "SCHOONER ROAD", "ADMIRALTY AVENUE",
                    "NAUTICAL DRIVE", "SHIPWRIGHT STREET"],
    "Riverscape / Silvertown": ["RIVERSCAPE WALK", "SILLEY WEIR PROMENADE",
                                "GALLIONS ROAD", "NORTH WOOLWICH ROAD"],
    "Canning Town 新盘": ["WESTERN GATEWAY", "SILVERTOWN WAY", "SEAGULL LANE",
                          "EDEN PLACE", "HEARTWELL AVENUE"],
    "Upper Riverside (North Greenwich)": ["CUTTER LANE", "WEST PARKSIDE",
                                          "RIVER GARDENS WALK", "JOHN HARRISON WAY"],
}
STREET_TO_DEV = {s: d for d, ss in DEVELOPMENTS.items() for s in ss}
MIN = 8


def main():
    m = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    m["year"] = pd.to_datetime(m["date"]).dt.year
    m["dev"] = m["street"].map(STREET_TO_DEV)
    d = m[m["dev"].notna()]

    r = d[d["year"].between(2024, 2025)]
    t = r.groupby(["dev", "newbuild"]).agg(
        n=("psf", "size"), psf=("psf", "median"), sqm=("area_sqm", "median"),
        price=("price", "median")).unstack("newbuild")
    t.columns = [f"{a}_{b}" for a, b in t.columns]
    for c in ("n_Y", "n_N", "psf_Y", "psf_N", "sqm_Y", "sqm_N", "price_Y", "price_N"):
        if c not in t:
            t[c] = np.nan
    t.loc[t["n_Y"] < MIN, ["psf_Y", "sqm_Y", "price_Y"]] = np.nan
    t.loc[t["n_N"] < MIN, ["psf_N", "sqm_N", "price_N"]] = np.nan
    t["resale_vs_new_pct"] = (t["psf_N"] / t["psf_Y"] - 1) * 100

    yrs = list(range(2015, 2027))
    out = {}
    for dev in DEVELOPMENTS:
        sub = d[d["dev"] == dev]
        rec = {"streets": DEVELOPMENTS[dev]}
        for tag, flag in (("resale", "N"), ("new", "Y")):
            g = sub[sub["newbuild"] == flag].groupby("year")["psf"].agg(["size", "median"])
            rec[tag] = [None if (y not in g.index or g.loc[y, "size"] < 6)
                        else round(float(g.loc[y, "median"])) for y in yrs]
            rec[tag + "_n"] = [int(g.loc[y, "size"]) if y in g.index else 0 for y in yrs]
        if dev in t.index:
            for k in ("n_Y", "n_N", "psf_Y", "psf_N", "sqm_Y", "sqm_N",
                      "price_Y", "price_N", "resale_vs_new_pct"):
                v = t.loc[dev, k]
                rec[k] = None if pd.isna(v) else round(float(v), 1)
        out[dev] = rec
    out["_years"] = yrs
    (OUT / "developments.json").write_text(json.dumps(out, ensure_ascii=False))

    print(f"developments: {len(DEVELOPMENTS)}  (street-defined, {MIN}+ sales per side)")
    show = t[["n_Y", "n_N", "psf_Y", "psf_N", "sqm_Y", "sqm_N", "resale_vs_new_pct"]]
    show.columns = ["新n", "二手n", "新建£/sqft", "二手£/sqft", "新㎡", "旧㎡", "转售相对新建%"]
    print(show.sort_values("转售相对新建%").to_string(
        float_format=lambda v: f"{v:,.0f}", na_rep="—"))


if __name__ == "__main__":
    main()
