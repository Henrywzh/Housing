"""London-wide LSOA safety: 36-month crime per 1,000 residents.

Rates, not counts. A count map is a population map -- Westminster tops it
because 290k crimes happen where a quarter of a million people work, not because
its residential streets are the worst. The denominator is Census 2021 usual
residents on the same 2021 LSOA geography the police publish on.

Three rates are kept.

`crimes_per_1000` is everything reported. `resident_per_1000` drops shoplifting
and the 'other crime' residual, which load onto shopping streets and make a high
street look dangerous to live beside when what it actually has is shops.

Neither fixes the real problem with a resident denominator, which is that Soho
and the Square Mile are full of people who do not live there. Westminster 013G
reads 17,000 crimes per 1,000 residents; almost none of it happens to the 2,189
people whose beds are there. So `home_per_1000` counts only burglary, vehicle
crime and criminal damage/arson -- offences against a resident's home or car,
where the population living there IS the exposed population. That is the number
to compare a Zone 1 flat against a Zone 4 one.
"""
import pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"


def main():
    c = pd.read_csv(OUT / "crime_lsoa_london.csv")
    pop = pd.read_csv(RAW / "lsoa_pop21.csv").drop_duplicates("GEOGRAPHY_CODE")
    pop = pop.rename(columns={"GEOGRAPHY_CODE": "LSOA code", "OBS_VALUE": "population"})

    pop = pop.rename(columns={"GEOGRAPHY_NAME": "lsoa_name"})
    d = pop[["LSOA code", "lsoa_name", "population"]].merge(c, on="LSOA code", how="left")
    # Population is the spine: an LSOA with no crime row had none reported in 36
    # months, which is a real zero and must not drop out of the denominator set.
    d["LSOA name"] = d["LSOA name"].fillna(d["lsoa_name"])
    d["borough"] = d["LSOA name"].str.replace(r"\s+\d{3}[A-Z]$", "", regex=True)
    for col in [x for x in d.columns if x.startswith("cat_")] + ["crimes", "resident_relevant"]:
        d[col] = d[col].fillna(0)
    d = d.drop(columns=["lsoa_name"])
    print(f"{(d['crimes'] == 0).sum()} LSOAs with no recorded crime in 36 months")
    d = d[d["population"] > 0]

    d["crimes_per_1000"] = d["crimes"] / d["population"] * 1000
    d["resident_per_1000"] = d["resident_relevant"] / d["population"] * 1000
    home = ["cat_burglary", "cat_vehicle_crime", "cat_criminal_damage_and_arson"]
    missing = [c for c in home if c not in d.columns]
    if missing:
        raise SystemExit(f"crime categories renamed upstream, home index broken: {missing}")
    d["home_crimes"] = d[home].sum(axis=1)
    d["home_per_1000"] = d["home_crimes"] / d["population"] * 1000
    # Same window for every LSOA, so a rank needs no annualising; state it anyway
    # because a reader will assume "per year" unless told.
    d["months"] = 36
    d["resident_per_1000_yr"] = d["resident_per_1000"] / 3

    d["pct_rank"] = d["resident_per_1000"].rank(pct=True)     # 1.0 = worst in London
    d["home_pct_rank"] = d["home_per_1000"].rank(pct=True)

    # Zero over 36 months is not a safety record, it is a missing snap point.
    # data.police.uk publishes each crime at the nearest of a fixed set of
    # anonymised points tied to named features, and a block built after that set
    # was drawn can contain none -- so the LSOA reads clean because nothing there
    # is on the map, not because nothing happens there.
    d["no_snap_point"] = d["crimes"] == 0
    for c in ("crimes_per_1000", "resident_per_1000", "resident_per_1000_yr",
              "home_per_1000", "pct_rank", "home_pct_rank"):
        d.loc[d["no_snap_point"], c] = pd.NA

    d.to_csv(OUT / "lsoa_safety.csv", index=False)

    print(f"{len(d):,} LSOAs, {d['crimes'].sum():,.0f} crimes over 36 months; "
          f"{d['no_snap_point'].sum()} suppressed as no-snap-point")
    print(f"median resident-relevant {d['resident_per_1000'].median():.1f} / 1,000 / 36 months "
          f"({d['resident_per_1000_yr'].median():.1f} a year); "
          f"median home-crime {d['home_per_1000'].median():.1f}")
    print("resident-relevant deciles:",
          dict(d["resident_per_1000"].quantile([.1, .25, .5, .75, .9]).round(1)))
    print("home-crime deciles:",
          dict(d["home_per_1000"].quantile([.1, .25, .5, .75, .9]).round(1)))
    for label, col in (("resident-relevant", "resident_per_1000"), ("home", "home_per_1000")):
        cols = ["LSOA name", col, "population"]
        print(f"\n{label} -- safest 5:")
        print(d.nsmallest(5, col)[cols].to_string(index=False))
        print(f"{label} -- worst 5:")
        print(d.nlargest(5, col)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
