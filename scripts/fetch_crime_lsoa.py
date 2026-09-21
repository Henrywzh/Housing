"""Crime at LSOA level inside the ten submarkets.

An MSOA of 7,500 people can hide a lot: Nine Elms on the river and Nine Elms
behind the railway are the same MSOA but not the same place. LSOAs are ~1,500
people, which is roughly the scale at which "this street feels different from
that one" starts to show up in the numbers.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fetch_crime import MONTHS, outer_ring, to_poly, run, write   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

if __name__ == "__main__":
    feats = json.load(open(ROOT / "data/raw/lsoa_sub_bgc.geojson"))["features"]
    print(f"{len(feats)} LSOAs x {len(MONTHS)} months")
    write(run(feats, "LSOA21CD", 30, "lsoa"), "lsoa", OUT / "crime_lsoa.csv")
    print("DONE")
