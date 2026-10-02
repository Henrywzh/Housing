"""Census 2021 tables at LSOA level: households, cars, tenure, qualifications, age.

Two things need these.

The crime rates need better denominators. Burglary per resident is not a rate a
resident can act on -- what is burgled is a dwelling, so the denominator is
dwellings; what is broken into is a car, so the denominator is cars. That change
is what stops a place with few homes and heavy footfall, which is most of Zone 1,
from reading as if its residents were being robbed constantly.

The map also needs something other than crime and price to colour by. Who lives
somewhere -- how densely, how old, how qualified, owning or renting -- is the
part of "what is this area" that no transaction record contains.

NOMIS caps a response at 25,000 rows and serves England-wide requests
alphabetically, so every table is asked for borough by borough and cached per
borough: a run that stops costs one request, not the whole table.
"""
import json, pathlib, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CACHE = RAW / "census_lsoa"
UA = {"User-Agent": "housing-research/1.0"}

# dataset id, short name, dimension, the category codes worth carrying
TABLES = [
    ("NM_2059_1", "households", "c2021_hh_1", "0"),
    # TS045 is households by how many cars they have. TS045A has the exact car
    # count but only down to MSOA, and an estimate from the bands is close enough
    # for a denominator.
    ("NM_2063_1", "cars", "c2021_cars_5", "0,1,2,3,4"),
    ("NM_2072_1", "tenure", "c2021_tenure_9", "0,1001,1003,1004"),
    ("NM_2084_1", "quals", "c2021_hiqual_8", "0,6"),
    ("NM_2020_1", "age", "c2021_age_19", "0,6,7,8"),
    # TS063 occupation (1 managers, 2 professionals, 3 associate professionals):
    # who lives here and what they do, which is what a buyer or tenant pool is made of.
    # Industry (TS060) is only published down to MSOA: see fetch_census_msoa.py.
    ("NM_2080_1", "occ", "c2021_occ_10", "0,1,2,3"),
]
URL = ("https://www.nomisweb.co.uk/api/v01/dataset/{ds}.data.csv"
       "?geography={lad}TYPE151&{dim}={cells}&measures=20100"
       "&select=geography_code,{dim},obs_value")


def get(url, tries=5):
    for a in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                       timeout=180).read()
            if r.strip():
                return r
            return b""
        except Exception as e:
            print(f"    retry {a+1} ({type(e).__name__})", flush=True)
            if a == tries - 1:
                raise
            time.sleep(8 * (a + 1))


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    lads = [f["properties"]["LAD24CD"]
            for f in json.loads((RAW / "london_lad.geojson").read_text())["features"]]
    for ds, name, dim, cells in TABLES:
        out = RAW / f"lsoa_{name}.csv"
        if out.exists() and out.stat().st_size > 1000:
            print(f"have lsoa_{name}.csv"); continue
        header, rows = None, []
        for i, lad in enumerate(lads, 1):
            f = CACHE / f"{name}_{lad}.csv"
            if not f.exists() or not f.read_text().strip():
                f.write_bytes(get(URL.format(ds=ds, lad=lad, dim=dim, cells=cells)))
            lines = [x for x in f.read_text().splitlines() if x.strip()]
            if lines:
                header = header or lines[0]
                rows += lines[1:]
            print(f"  {name} {i}/{len(lads)} {lad}: {max(len(lines)-1, 0)} rows",
                  end="\r", flush=True)
        # City of London answers the borough-parent query with an empty set on
        # most of these tables, the same quirk the population fetch hit, so
        # whatever the boroughs missed is asked for by LSOA code.
        want = {f["properties"]["LSOA21CD"] for f in
                json.loads((RAW / "lsoa_london_bgc.geojson").read_text())["features"]}
        have = {r.split(",")[0].strip('"') for r in rows}
        gap = sorted(want - have)
        if gap:
            print(f"\n  {name}: {len(gap)} LSOAs missing from the borough queries; "
                  f"asking by code", flush=True)
            for i in range(0, len(gap), 50):
                extra = get(URL.format(ds=ds, lad="", dim=dim, cells=cells)
                            .replace("geography=TYPE151",
                                     "geography=" + ",".join(gap[i:i + 50])))
                rows += [x for x in extra.decode().splitlines()[1:] if x.strip()]
        out.write_text(header + "\n" + "\n".join(rows) + "\n")
        print(f"\n{name}: {len(rows):,} rows -> {out.name}")


if __name__ == "__main__":
    main()
