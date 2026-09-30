"""National Rail track through London, by operator, so the suburban map is legible.

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
asks for the rails inside the map's own frame, then for the passenger routes
that run over them, which come back as member lists and cost almost nothing.

Which operator, though, is not the `operator` tag. OSM records the legal entity:
every Thameslink, Southern, Great Northern and Gatwick Express route is
`operator=Greater Thameslink Railway`, and -- the one that matters -- all
twenty-four Elizabeth line routes are `operator=GTS Rail Operations`, which
looks like a train company nobody has heard of rather than the purple line the
map already draws. The relation's NAME carries the brand ("Southern: Brighton ->
London Victoria"), so the prefix before the colon is the key, with the operator
tag as the fallback for the routes that have no such name.

Two filters. `usage=main|branch` separates a running line from a siding or a
depot throat but says nothing about passengers, and London has freight-only
routes -- the Dudding Hill line, the Barking curves -- so a way in no passenger
route at all is dropped. And a way whose only brands are TfL's belongs to the
Overground and Elizabeth layers, which have their own colours.

A way that carries four operators is emitted four times, once per operator.
That is the point of the filter: with everything on you see the top one, and
with one operator selected you see exactly where that company's trains go, which
is the question a buyer actually has.
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

OTHER = "长途 · 其他"
# Brand -> the name this map uses. Sub-brands fold into the operator whose track
# they share and whose stations they call at: Gatwick Express is Southern metals,
# Stansted Express is Greater Anglia's, and a reader choosing a flat is asking
# which company's trains stop nearby, not which product they are sold as.
CANON = {
    "Southeastern": "Southeastern", "Southeastern High Speed": "Southeastern",
    "South Eastern": "Southeastern",
    "Thameslink": "Thameslink", "Govia Thameslink Railway": "Thameslink",
    "Southern": "Southern", "Gatwick Express": "Southern",
    "Great Northern": "Great Northern",
    "South Western Railway": "South Western Railway", "SWR": "South Western Railway",
    "SWT": "South Western Railway",
    "Greater Anglia": "Greater Anglia", "Abellio Greater Anglia": "Greater Anglia",
    "Stansted Express": "Greater Anglia",
    "c2c": "c2c",
    "CH": "Chiltern Railways", "Chiltern Railways": "Chiltern Railways",
    "Chiltern Main Line": "Chiltern Railways",
    "GWR": "Great Western Railway", "Great Western Railway": "Great Western Railway",
}
# Everything that runs through London without being a way to commute into it.
# Grouped rather than dropped: the track is real and the map should show it, but
# it is context, so it is drawn in grey under everything else.
LONG_DISTANCE = {
    "Avanti West Coast", "AWC", "London North Eastern Railway", "LNER",
    "Virgin Trains East Coast", "Lumo", "Grand Central", "Hull Trains",
    "CrossCountry", "East Midlands Railway", "Midland Main Line",
    "West Midlands Trains", "LNWR", "London Northwestern Railway",
    "Eurostar", "Eurostar International Ltd", "Caledonian Sleeper",
    "Highland Sleeper", "Lowland Sleeper", "Heathrow Express",
}
# Drawn elsewhere, in their own colours.
TFL = {"Elizabeth line", "London Overground", "Transport for London",
       "Arriva Rail London", "MTR Elizabeth line", "Crossrail", "TfL Rail",
       "Windrush Line", "Weaver Line", "Mildmay Line", "Liberty Line",
       "Lioness Line", "Suffragette Line"}

# Each operator's own brand colour, approximately, except where that would put
# two operators on the same hue -- these have to be told apart from each other
# first and resemble the livery second. What keeps them from being read as tube
# lines is not the hue, which the tube has all of, but the dash.
COLOR = {
    "Southeastern": "#0071B9", "Thameslink": "#EE4B95", "Southern": "#78BE20",
    "Great Northern": "#6B2C91", "South Western Railway": "#1B3D6D",
    "Greater Anglia": "#B01020", "c2c": "#D41B8C", "Chiltern Railways": "#00857D",
    "Great Western Railway": "#0A493E", OTHER: "#8A939B",
}

# What fits in a legend column. The full name stays on the feature.
SHORT = {"Great Western Railway": "GWR", "South Western Railway": "SWR",
         "Chiltern Railways": "Chiltern", "Greater Anglia": "Greater Anglia"}

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


def brand(tags):
    """The company a passenger would name, from the route's name, not its owner."""
    name = tags.get("name", "")
    head = name.split(":")[0].strip() if ":" in name else ""
    for cand in (head, tags.get("operator", "").split(";")[0].strip(), name.strip()):
        if cand in TFL:
            return None                       # drawn in its own colour elsewhere
        if cand in CANON:
            return CANON[cand]
        if cand in LONG_DISTANCE:
            return OTHER
    return OTHER if (head or tags.get("operator")) else None


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
            for e in els if e["type"] == "way" and "geometry" in e
            and len(e["geometry"]) > 1}
    routed = set()                            # in any passenger route at all
    ops = defaultdict(set)                    # way id -> operators this map draws
    for e in els:
        if e["type"] != "relation":
            continue
        b = brand(e.get("tags", {}))
        members = [m["ref"] for m in e.get("members", []) if m.get("type") == "way"]
        routed.update(members)
        if b:
            for w in members:
                ops[w].add(b)

    from shapely.geometry import MultiLineString
    from shapely.ops import linemerge
    by_op = defaultdict(list)
    for wid, coords in ways.items():
        for b in ops.get(wid, ()):
            by_op[b].append(coords)

    # 长途 first so it sits at the bottom, then largest network to smallest: a
    # shared corridor should show the operator whose corridor it mostly is.
    order = sorted(by_op, key=lambda b: (b != OTHER, -len(by_op[b])))
    # The legend reads the other way round: the operator a reader is most likely
    # to commute on first, the long-distance grab-bag last.
    ui = {b: i for i, b in enumerate(
        sorted(by_op, key=lambda b: (b == OTHER, -len(by_op[b]))))}
    feats = []
    for i, b in enumerate(order):
        merged = linemerge(MultiLineString(by_op[b]))
        parts = ([list(merged.coords)] if merged.geom_type == "LineString"
                 else [list(g.coords) for g in merged.geoms])
        feats.append({"type": "Feature",
                      "properties": {"name": b, "op": b, "mode": "national-rail",
                                     "color": COLOR.get(b, "#8A939B"), "z": -100 + i,
                                     "n": len(by_op[b]), "ui": ui[b],
                                     "short": SHORT.get(b, b)},
                      "geometry": {"type": "MultiLineString",
                                   "coordinates": [[[round(x, 5), round(y, 5)]
                                                    for x, y in p] for p in parts]}})
        print(f"  {b:24s} {len(by_op[b]):5d} ways -> {len(parts):4d} strokes, "
              f"{sum(len(p) for p in parts):6d} points")

    drawn = {w for w in ways if ops.get(w)}
    print(f"\n{len(ways):,} rail ways in the box; "
          f"{len(ways) - len(ways.keys() & routed):,} in no passenger route "
          f"(freight, depot or disused), "
          f"{len(ways.keys() & routed) - len(drawn):,} carry only TfL services")
    print(f"{len(drawn):,} drawn, over {len(feats)} operators")

    p = OUT / "rail.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                            separators=(",", ":")))
    print(f"-> {p.name} ({p.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
