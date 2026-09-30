"""National Rail track through London, so the suburban rail map stops being blank.

The map draws fifteen TfL lines and nothing else, which paints half of south
London as a transport desert. It is not one: Kidbrooke, Catford, Hither Green,
Sydenham and the whole Southeastern and Thameslink fan have no tube at all and
never will, and the train is the commute. 191 of the 621 stations already on the
map are National Rail only, sitting there with no line through them.

Route relations are how the tube lines were fetched, but National Rail cannot be
asked for the same way: `network=National Rail` is every train route in Great
Britain, and asking by operator pulls Southeastern all the way to Dover. The
track itself is a way, and a way query IS bounded by a bounding box cheaply --
ways are in the spatial index, which is exactly what relations are not. So this
asks for the rails inside the map's own frame.

`usage=main|branch` is what separates a running line from a siding, a depot
throat or a headshunt. It does not separate passenger track from freight track,
and London has freight-only routes -- the Dudding Hill line, the Barking curves
-- that would otherwise be drawn as if trains stopped on them. So each way is
checked against the passenger route relations that contain it, and a way in no
passenger route is dropped. The same check is what keeps this layer from
redrawing the Overground and the Elizabeth line, which are `railway=rail` too and
already have their own colours: a way whose only routes are those two is theirs,
not this layer's.

Everything that survives is one feature. The tube map draws National Rail as a
single styling rather than a colour per operator, because outside TfL there is no
line colour a reader carries in their head -- people say "the train to London
Bridge", not "the green line". The operators are kept as a property so the map
can name them, and the station panel already lists them per station.
"""
import json, pathlib, time, urllib.parse, urllib.request
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "transport"
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass.osm.ch/api/interpreter"]
UA = {"User-Agent": "housing-research/1.0"}

# The map's own frame with room to spare, so lines leave the edge instead of
# stopping in mid-air at the last pixel.
BOX = (51.28, -0.55, 51.72, 0.30)

# Operators whose track this layer does not claim: they are drawn in their own
# colours already. A way is only theirs if it carries nothing else.
TFL = {"London Overground", "Elizabeth line", "Elizabeth Line", "Arriva Rail London",
       "MTR Elizabeth line", "Crossrail", "TfL Rail", "Transport for London"}

QUERY = """[out:json][timeout:600];
(way["railway"="rail"]["usage"="main"]({0},{1},{2},{3});
 way["railway"="rail"]["usage"="branch"]({0},{1},{2},{3}););
out geom;
rel(bw)["route"="train"];
out body;"""


def overpass(q, tries=6):
    for a in range(tries):
        ep = ENDPOINTS[a % len(ENDPOINTS)]
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                ep, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA),
                timeout=900).read())
        except Exception as e:
            print(f"  retry {a+1} ({type(e).__name__} {getattr(e, 'code', '')})",
                  flush=True)
            if a == tries - 1:
                raise
            time.sleep(15 * (a + 1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "rail_raw.json"
    if cache.exists():
        els = json.loads(cache.read_text())
        print(f"{len(els):,} elements (cached)")
    else:
        els = overpass(QUERY.format(*BOX))["elements"]
        cache.write_text(json.dumps(els))
        print(f"{len(els):,} elements -> {cache.name} "
              f"({cache.stat().st_size/1e6:.1f} MB)")

    ways = {e["id"]: [[round(p["lon"], 5), round(p["lat"], 5)] for p in e["geometry"]]
            for e in els if e["type"] == "way" and "geometry" in e}
    # way id -> the operators of the passenger routes running over it
    ops = defaultdict(set)
    for e in els:
        if e["type"] != "relation":
            continue
        t = e.get("tags", {})
        op = (t.get("operator") or t.get("network") or "").split(";")[0].strip()
        for m in e.get("members", []):
            if m.get("type") == "way":
                ops[m["ref"]].add(op)

    keep, freight, tfl_only = [], 0, 0
    names = defaultdict(int)
    for wid, coords in ways.items():
        if len(coords) < 2:
            continue
        o = ops.get(wid)
        if not o:
            freight += 1
            continue
        if o <= TFL:
            tfl_only += 1
            continue
        keep.append(coords)
        for x in o - TFL:
            names[x] += 1

    print(f"{len(ways):,} rail ways in the box; {freight:,} in no passenger route "
          f"(freight, depot or disused), {tfl_only:,} carry only TfL services")
    print(f"{len(keep):,} kept, {sum(len(c) for c in keep):,} points")
    print("\noperators found:")
    for k, v in sorted(names.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {v:5d} ways  {k or '(untagged)'}")

    feat = {"type": "Feature",
            "properties": {"name": "National Rail", "mode": "national-rail",
                           # The double-arrow navy. One styling, as the tube map
                           # does it, because National Rail has no line colours.
                           "color": "#1F3864", "z": -1,
                           "operators": sorted(k for k in names if k)},
            "geometry": {"type": "MultiLineString", "coordinates": keep}}
    p = OUT / "rail.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [feat]},
                            separators=(",", ":")))
    print(f"\n-> {p.name} ({p.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
