"""Tube, DLR, Overground, Elizabeth line and tram geometry.

The basemap draws every railway as one grey hairline, which is true and useless:
what a reader takes off a London map is which colour runs through the area,
because the colour is the commute.

TfL publishes route geometry, but its Route/Sequence endpoint returns one point
per station -- the Victoria line comes back as sixteen points -- so drawn over a
real street map the lines cut diagonally through buildings. OpenStreetMap has
the track itself.

Overpass times out on a bounding-box query for route relations over London, and
answers the same question in a second when asked by network instead, because the
network tag is indexed and the bounding box is not. So each operator is asked for
by name.

A line is a set of relations (one per branch and direction) sharing a `ref`, and
those relations share member ways, so ways are deduplicated by id before the line
is assembled.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "transport"
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
UA = {"User-Agent": "housing-research/1.0"}

# Each operator is a list of selectors tried in order until one returns rows:
# OSM's network tag is not spelled consistently across operators, and a wrong
# guess is cheap while a regex is not (Overpass cannot index one and times out).
NETWORKS = [
    ("tube", ['["route"="subway"]["network"="London Underground"]']),
    ("dlr", ['["route"="light_rail"]["network"="Docklands Light Railway"]',
             '["route"="light_rail"]["network"="DLR"]']),
    # Only Liberty and Lioness answer to the network tag; the other four named
    # Overground lines are tagged some other way and have not been found yet, so
    # the map names what is missing rather than implying those lines do not run.
    ("overground", ['["route"="train"]["network"="London Overground"]',
                    '["route"="train"]["operator"="Arriva Rail London"]',
                    '["route_master"="train"]["network"="London Overground"]',
                    '["route"="train"]["network"="Overground"]']),
    ("elizabeth", ['["route"="train"]["network"="Elizabeth Line"]',
                   '["route"="train"]["network"="Elizabeth line"]',
                   '["route"="train"]["network"="Elizabeth Line"]',
                   '["route"="train"]["operator"="MTR Elizabeth line"]',
                   '["route"="train"]["network"="Crossrail"]',
                   '["route"="train"]["name"="Elizabeth line"]']),
    ("tram", ['["route"="tram"]["network"="London Trams"]',
              '["route"="tram"]["network"="Tramlink"]']),
]
# DLR and tram relations are tagged with internal route codes -- "S-L", "B-WA",
# "2", "3" -- which are not names a reader knows. Those modes collapse to one
# line each.
ONE_LINE = {"dlr": "DLR", "tram": "Tramlink"}
# Official colours, keyed by the line's OSM `ref`. OSM's own colour tag is close
# but drifts in shade between relations of the same line.
COLOR = {
    "bakerloo": "#B36305", "central": "#E32017", "circle": "#FFD300",
    "district": "#00782A", "hammersmith & city": "#F3A9BB", "jubilee": "#A0A5A9",
    "metropolitan": "#9B0056", "northern": "#000000", "piccadilly": "#003688",
    "victoria": "#0098D4", "waterloo & city": "#95CDBA", "dlr": "#00A4A7",
    "elizabeth line": "#6950A1", "elizabeth": "#6950A1", "tramlink": "#84B817",
    "liberty": "#5D6061", "lioness": "#FFB600", "mildmay": "#437EC0",
    "suffragette": "#76B82A", "weaver": "#823A62", "windrush": "#ED1B00",
}
# Drawing order: the busiest lines last, so a shared tunnel shows the line most
# people mean when they say how they get in.
ORDER = ["Tramlink", "DLR", "Liberty", "Lioness", "Mildmay", "Suffragette", "Weaver",
         "Windrush", "Hammersmith & City", "Circle", "District", "Metropolitan",
         "Bakerloo", "Waterloo & City", "Jubilee", "Piccadilly", "Central",
         "Northern", "Victoria", "Elizabeth line"]


def overpass(q, tries=5):
    for a in range(tries):
        ep = ENDPOINTS[a % len(ENDPOINTS)]
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                ep, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA),
                timeout=180).read())
        except Exception as e:
            print(f"    retry {a+1} ({type(e).__name__} "
                  f"{getattr(e, 'code', '')})", flush=True)
            if a == tries - 1:
                raise
            time.sleep(10 * (a + 1))


def fetch_mode(mode, selectors, cache):
    """Try each selector until one answers with relations; cache what comes back."""
    f = cache / f"{mode}.json"
    if f.exists():
        els = json.loads(f.read_text())
        print(f"{mode:11s} {len(els):3d} relations (cached)", flush=True)
        return els
    for sel in selectors:
        try:
            els = overpass(f"[out:json][timeout:180];(relation{sel};);out geom;"
                           ).get("elements", [])
        except Exception:
            continue
        if els:
            f.write_text(json.dumps(els))
            print(f"{mode:11s} {len(els):3d} relations  {sel}", flush=True)
            return els
        print(f"{mode:11s} 0 from {sel}", flush=True)
    print(f"{mode:11s} NOT FOUND -- this mode will be missing from the map", flush=True)
    return []


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "lines_raw"
    cache.mkdir(exist_ok=True)
    lines = {}                       # ref -> {mode, ways: {way id: coords}}
    for mode, selectors in NETWORKS:
        for rel in fetch_mode(mode, selectors, cache):
            ref = ONE_LINE.get(mode) or (rel["tags"].get("ref")
                                         or rel["tags"].get("name") or "").strip()
            if not ref:
                continue
            e = lines.setdefault(ref, {"mode": mode, "ways": {}})
            for m in rel.get("members", []):
                if m.get("type") != "way" or "geometry" not in m:
                    continue
                e["ways"][m["ref"]] = [[round(p["lon"], 5), round(p["lat"], 5)]
                                       for p in m["geometry"]]

    order = {n: i for i, n in enumerate(ORDER)}
    feats = []
    for ref, e in sorted(lines.items(), key=lambda kv: order.get(kv[0], -1)):
        coords = [c for c in e["ways"].values() if len(c) > 1]
        if not coords:
            continue
        feats.append({"type": "Feature",
                      "properties": {"name": ref, "mode": e["mode"],
                                     "color": COLOR.get(ref.lower(), "#5b6b78"),
                                     "z": order.get(ref, 0)},
                      "geometry": {"type": "MultiLineString", "coordinates": coords}})
        print(f"  {ref:22s} {len(coords):4d} ways, {sum(len(c) for c in coords):6d} points",
              flush=True)

    p = OUT / "lines.geojson"
    if p.exists() and len(feats) < len(json.loads(p.read_text())["features"]):
        raise SystemExit(f"refusing to overwrite: {len(feats)} lines found, "
                         f"{len(json.loads(p.read_text())['features'])} already on disk. "
                         f"Delete data/raw/transport/lines_raw to force a clean run.")
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                            separators=(",", ":")))
    print(f"{len(feats)} lines -> {p.name} ({p.stat().st_size/1e6:.2f} MB)")
    grey = [f["properties"]["name"] for f in feats if f["properties"]["color"] == "#5b6b78"]
    if grey:
        print(f"no official colour for {grey}; drawn grey")


if __name__ == "__main__":
    main()
