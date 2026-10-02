"""Census 2021 industry of the people who live in each MSOA (TS060).

Industry is not published below MSOA (a few thousand people), so unlike the other
tables it cannot be had per LSOA: the LSOA rows come back blank. MSOAs are big
enough for what it is used for, which is the share of residents who work in
finance, in professional services or in information and communication -- the
people who rent or buy near the City, Canary Wharf and the West End.

Cached per borough under data/raw/census_lsoa/, like the LSOA tables.
"""
import json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fetch_census_lsoa import get, RAW, CACHE  # noqa: E402

URL = ("https://www.nomisweb.co.uk/api/v01/dataset/NM_2077_1.data.csv"
       "?geography={lad}TYPE152&c2021_ind_88=0,1010,1011,1013&measures=20100"
       "&select=geography_code,c2021_ind_88,obs_value")


def main():
    out = RAW / "msoa_industry.csv"
    lads = [f["properties"]["LAD24CD"]
            for f in json.loads((RAW / "london_lad.geojson").read_text())["features"]]
    header, rows = None, []
    for lad in lads:
        f = CACHE / f"msoa_industry_{lad}.csv"
        if not f.exists() or not f.read_text().strip():
            f.write_bytes(get(URL.format(lad=lad)))
        lines = [x for x in f.read_text().splitlines() if x.strip()]
        if lines:
            header = header or lines[0]
            rows += lines[1:]
        print(f"  {lad}: {max(len(lines) - 1, 0)} rows", end="\r", flush=True)
    out.write_text(header + "\n" + "\n".join(rows) + "\n")
    print(f"\n{len(rows):,} rows -> {out.name}")


if __name__ == "__main__":
    main()
