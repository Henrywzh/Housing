"""The housing pipeline around each place: sites that may add flats, from planning.data.gov.uk.

Supply is what makes a flat harder to sell in 2032: a 1,000-home site three streets
away is 1,000 more flats on the market, so the number of homes that are permitted
or likely within a kilometre says how crowded the next few years will be. The
Greater London Authority's own site-level database stopped at 2019 (it was replaced
by a datahub that is not public), so this reads the national Brownfield Land
Register instead: every council lists the previously developed sites it thinks
could take housing, with a point, a hectare size, the minimum and maximum net
dwellings, and whether planning permission is held, pending or absent.

Two caveats the page repeats. A register entry is a candidate site, not a decision,
and councils refresh at different times, so older entries are kept but dated. And
the register is brownfield only: greenfield and Green Belt sites are not in it.

Pages of 500 are cached under data/raw/supply/.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "supply" / "brownfield.json"
POLY = "POLYGON((-0.57 51.27,0.31 51.27,0.31 51.71,-0.57 51.71,-0.57 51.27))"
UA = {"User-Agent": "housing-research"}


def get(offset):
    q = urllib.parse.urlencode({"dataset": "brownfield-land", "geometry": POLY,
                                "geometry_relation": "intersects", "limit": 500, "offset": offset})
    for wait in (0, 5, 15, 40):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://www.planning.data.gov.uk/entity.json?{q}", headers=UA), timeout=90) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry offset {offset}: {type(e).__name__}", flush=True)
    raise RuntimeError(f"offset {offset} failed")


def main():
    rows, offset = [], 0
    while True:
        d = get(offset)
        es = d["entities"]
        rows += es
        print(f"  {len(rows)} / {d.get('count')}", flush=True)
        if len(es) < 500:
            break
        offset += 500
        time.sleep(1)
    OUT.write_text(json.dumps(rows, ensure_ascii=False))
    print(f"{len(rows)} sites -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
