"""Street-level crime counts for each London borough and each submarket MSOA.

data.police.uk exposes a rolling 36 months of street-level crime. We ask it by
polygon rather than downloading the 1.7GB national archive, and we ask on the
SAME geographies the census and income data use, so a crime rate can share a
population denominator with everything else in the submarket table.

Two things to know about this data before reading any rate off it:
  * Locations are snapped to anonymised map points near the incident, not the
    incident itself, so counts are reliable over an area and meaningless for a
    single street or building.
  * The denominator is resident population. Places with large daytime or
    visitor populations -- Canary Wharf, Stratford, the West End -- record
    crimes committed against people who do not live there, so crime per
    resident overstates the risk to a resident. Compare like with like.
"""
import json, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
API = "https://data.police.uk/api/crimes-street/all-crime"
MONTHS = [f"2{y}-{m:02d}" for y, m in
          [(25, 8), (25, 9), (25, 10), (25, 11), (25, 12),
           (26, 1), (26, 2), (26, 3), (26, 4), (26, 5), (26, 6), (26, 7)]]
MONTHS = [m.replace("2", "20", 1) for m in MONTHS]


def outer_ring(geom):
    """Largest outer ring of a Polygon/MultiPolygon, as [lon,lat] pairs.

    Eight London boroughs are MultiPolygons, but every secondary part is a
    4-35 point river islet or sliver, so taking the largest ring loses a
    negligible slice of each. The ring is then decimated to `max_pts`, which
    shifts the boundary by tens of metres in places -- fine for a borough rate,
    not fine if you wanted an exact count along a boundary street.
    """
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return max((p[0] for p in polys), key=len)


def to_poly(ring, max_pts):
    step = max(1, len(ring) // max_pts)
    pts = ring[::step]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return ":".join(f"{p[1]:.5f},{p[0]:.5f}" for p in pts)


def fetch(poly, date, tries=4):
    body = urllib.parse.urlencode({"poly": poly, "date": date}).encode()
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(API, data=body),
                                        timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            if e.code in (429, 502, 503) and a < tries - 1:
                time.sleep(4 * (a + 1)); continue
            raise
        except Exception:
            if a < tries - 1:
                time.sleep(3 * (a + 1)); continue
            raise
    return []


def run(features, key_field, max_pts, label):
    jobs = []
    for f in features:
        poly = to_poly(outer_ring(f["geometry"]), max_pts)
        for m in MONTHS:
            jobs.append((f["properties"][key_field], m, poly))
    rows = {}
    done = [0]

    def work(job):
        code, month, poly = job
        c = Counter(x["category"] for x in fetch(poly, month))
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {label} {done[0]}/{len(jobs)}", flush=True)
        return code, month, c

    with ThreadPoolExecutor(max_workers=6) as ex:
        for code, month, c in ex.map(work, jobs):
            rows.setdefault(code, Counter()).update(c)
    return rows


def write(rows, key_name, path):
    cats = sorted({c for v in rows.values() for c in v})
    with path.open("w") as fh:
        fh.write(key_name + ",crime_total," + ",".join("crime_" + c.replace("-", "_")
                                                       for c in cats) + "\n")
        for code, c in sorted(rows.items()):
            fh.write(f"{code},{sum(c.values())}," + ",".join(str(c.get(k, 0)) for k in cats) + "\n")
    print(f"{path.name}: {len(rows)} areas, {sum(sum(c.values()) for c in rows.values()):,} crimes")


if __name__ == "__main__":
    print(f"months: {MONTHS[0]} .. {MONTHS[-1]}")
    msoa = json.load(open(ROOT / "data/raw/msoa_sub_bgc.geojson"))["features"]
    write(run(msoa, "MSOA21CD", 45, "msoa"), "msoa", OUT / "crime_msoa.csv")
    lad = json.load(open(ROOT / "data/raw/london_lad_bgc.geojson"))["features"]
    write(run(lad, "LAD24CD", 110, "lad"), "code", OUT / "crime_borough.csv")
    print("DONE")
