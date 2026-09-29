"""Who lives in each LSOA, and crime rates whose denominators match the risk.

The crime problem, stated once so the code below is readable: a rate per
resident answers "how much crime happens here per person who sleeps here", and
in Soho, Oxford Street or the Square Mile that is not a question anyone asked.
Westminster 013G reads 17,000 crimes per 1,000 residents. Almost none of it
happens to those 2,189 people.

Splitting out burglary, vehicle crime and criminal damage helped, but not
enough, because a visitor's car is still broken into in an LSOA whose resident
count is tiny. The denominator was still wrong.

What is burgled is a dwelling. What is broken into is a car. So:

    burglary     per 1,000 households      (Census 2021 TS041)
    vehicle      per 1,000 cars            (TS045, estimated from the bands)
    violence     per 1,000 residents       (the victim is a person; still reads
                                             high where crowds are, and says so)

A place with few homes and heavy footfall no longer looks dangerous to live in
merely for having few homes. What it cannot fix is that a burgled shop and a
burgled flat are the same category to the police, so a retail core still carries
some of it -- hence `visitor_share`, the fraction of an LSOA's crime that is
shoplifting or theft from the person. That is computed from the crime data
itself, needs no other source, and is the cleanest available answer to "is this
number about residents or about crowds".
"""
import json, pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
M_PER_DEG_LAT = 111_320.0

# Households with three or more cars average a little over three; 3.4 is the
# usual working figure and the choice moves the rate by well under a percent.
CARS_3PLUS = 3.4


def pivot(name, dim):
    d = pd.read_csv(RAW / f"lsoa_{name}.csv")
    d.columns = [c.lower() for c in d.columns]
    return d.pivot_table(index="geography_code", columns=dim, values="obs_value",
                         aggfunc="sum")


def areas_km2(path):
    """Polygon area on a local equirectangular projection.

    Over an LSOA at London's latitude the error against a proper equal-area
    projection is a fraction of a percent, and the alternative is a dependency.
    """
    from shapely.geometry import shape
    from shapely.ops import transform
    g = json.loads(path.read_text())
    out = {}
    for f in g["features"]:
        geom = shape(f["geometry"])
        lat0 = geom.centroid.y
        k = M_PER_DEG_LAT * np.cos(np.radians(lat0))
        out[f["properties"]["LSOA21CD"]] = transform(
            lambda x, y, z=None: (x * k, y * M_PER_DEG_LAT), geom).area / 1e6
    return pd.Series(out, name="area_km2")


def main():
    hh = pivot("households", "c2021_hh_1")[0].rename("households")
    cars = pivot("cars", "c2021_cars_5")
    est_cars = (cars[2] + 2 * cars[3] + CARS_3PLUS * cars[4]).rename("cars")
    hh_with_car = (cars[0] - cars[1]).rename("hh_with_car")

    ten = pivot("tenure", "c2021_tenure_9")
    tenure = pd.DataFrame({
        "owned_pct": ten[1001] / ten[0] * 100,
        "social_pct": ten[1003] / ten[0] * 100,
        "private_rent_pct": ten[1004] / ten[0] * 100})

    q = pivot("quals", "c2021_hiqual_8")
    degree = (q[6] / q[0] * 100).rename("degree_pct")

    a = pivot("age", "c2021_age_19")
    young = ((a[6] + a[7] + a[8]) / a[0] * 100).rename("age_25_39_pct")

    saf = pd.read_csv(OUT / "lsoa_safety.csv").rename(columns={"LSOA code": "lsoa"})
    area = areas_km2(RAW / "lsoa_london_bgc.geojson")

    d = saf.set_index("lsoa").join([hh, est_cars, hh_with_car, tenure, degree, young, area])
    d["density"] = d["population"] / d["area_km2"]

    # --- rates with the right denominator --------------------------------------
    months = 36
    yr = 12 / months
    d["burglary_per_1000_hh"] = d["cat_burglary"] / d["households"] * 1000 * yr
    d["vehicle_per_1000_cars"] = d["cat_vehicle_crime"] / d["cars"] * 1000 * yr
    d["damage_per_1000_hh"] = d["cat_criminal_damage_and_arson"] / d["households"] * 1000 * yr
    d["violence_per_1000"] = ((d["cat_violence_and_sexual_offences"] + d["cat_robbery"])
                              / d["population"] * 1000 * yr)
    # Rates off a handful of households or cars are noise, and the places with a
    # handful of either are exactly the ones this is trying to read correctly.
    d.loc[d["households"] < 100, ["burglary_per_1000_hh", "damage_per_1000_hh"]] = np.nan
    d.loc[d["cars"] < 100, "vehicle_per_1000_cars"] = np.nan
    d.loc[d["no_snap_point"], ["burglary_per_1000_hh", "vehicle_per_1000_cars",
                               "damage_per_1000_hh", "violence_per_1000"]] = np.nan

    d["visitor_share"] = ((d["cat_shoplifting"] + d["cat_theft_from_the_person"])
                          / d["crimes"].replace(0, np.nan) * 100)

    d.reset_index().to_csv(OUT / "lsoa_social.csv", index=False)

    print(f"{len(d):,} LSOAs")
    for c, lab in (("density", "人/km²"), ("degree_pct", "本科以上%"),
                   ("age_25_39_pct", "25-39岁%"), ("owned_pct", "自有%"),
                   ("private_rent_pct", "私租%"), ("burglary_per_1000_hh", "入室/千户/年"),
                   ("vehicle_per_1000_cars", "车辆/千车/年"),
                   ("violence_per_1000", "暴力抢劫/千人/年"), ("visitor_share", "访客型犯罪%")):
        s = d[c].dropna()
        print(f"  {lab:16s} p10 {s.quantile(.1):9,.1f}  median {s.median():9,.1f}  "
              f"p90 {s.quantile(.9):9,.1f}")

    print("\nwhat the new denominators do to the worst LSOAs on the old measure:")
    cols = ["LSOA name", "population", "households", "resident_per_1000",
            "burglary_per_1000_hh", "vehicle_per_1000_cars", "visitor_share"]
    print(d.nlargest(6, "resident_per_1000")[cols].round(1).to_string(index=False))
    print("\nworst on burglary per household:")
    print(d.nlargest(6, "burglary_per_1000_hh")[cols].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
