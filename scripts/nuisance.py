"""Which of the unwelcome neighbours (fetch_nuisance.py) is close to a point.

Each kind has the distance inside which a buyer, or the tenant who follows, would
notice it: a prison is a presence for a few hundred metres, a viaduct train is
heard at fifty, an aircraft on the approach is heard for kilometres. Outside the
distance nothing is flagged, so most points come back with an empty list.
"""
import json, math, pathlib, re
import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "osm_nuisance"
KX = 111_320.0 * math.cos(math.radians(51.5))
KY = 111_320.0
# kind -> (metres, label shown on the page). Building sites are fetched but not used: OSM
# marks 1,300 of them in London, most a few flats' worth, and the tag carries no size. 'runway' is the under-the-approach zone.
LIMIT = {"prison": (500, "监狱"), "waste": (400, "垃圾场/污水厂"), "power": (500, "发电厂"),
         "motorway": (120, "高速公路"),
         "viaduct": (60, "高架铁路"), "runway": (1800, "机场跑道/航线")}


def _xy(lat, lon):
    return lon * KX, lat * KY


class Nuisance:
    def __init__(self):
        self.t = {}
        for kind in LIMIT:
            f = DIR / f"{kind}.json"
            if not f.exists():
                continue
            geoms = []
            for x in json.loads(f.read_text()):
                # OSM's "power plant" is mostly district-heating energy centres, solar
                # roofs and batteries, which sit in the middle of new neighbourhoods and
                # are not a nuisance. What is: incinerators and power stations.
                if kind == "power" and not re.search(
                        r"incinerat|energy recovery|energy from waste|eco ?park|south east london combined"
                        r"|power station|power plant", x.get("name") or "", re.I):
                    continue
                if "line" in x:
                    geoms.append(LineString([_xy(la, lo) for la, lo in x["line"]]))
                else:
                    geoms.append(Point(*_xy(x["lat"], x["lon"])))
            if geoms:
                self.t[kind] = (STRtree(geoms), geoms)

    def flags(self, lat, lon):
        p = Point(*_xy(lat, lon))
        out = []
        for kind, (tree, geoms) in self.t.items():
            i, d = tree.query_nearest(p, return_distance=True, all_matches=False)
            m = float(d[0])
            if m <= LIMIT[kind][0]:
                out.append([kind, int(round(m, -1)) or 10])
        return out
