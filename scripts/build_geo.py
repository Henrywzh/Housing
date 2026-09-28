"""Map-ready geometry: simplified LSOA polygons and borough outlines.

The ONS generalised-clipped LSOA file is 7.3 MB, which is more precision than a
screen can show and more bytes than a page should carry. Simplifying to a 15 m
tolerance is below one pixel at any zoom this map offers and cuts it by roughly
three quarters.

The clip is doing a second job for free: ONS boundaries stop at the tidal
coastline, so the Thames is the hole the polygons leave, and the river draws
itself without a river layer.
"""
import json, pathlib
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
TOL_DEG = 15 / 111_320.0          # ~15 m, in degrees of latitude
PRECISION = 5                     # ~1.1 m; finer than the tolerance, so it is free


def round_coords(o, p=PRECISION):
    if isinstance(o, (list, tuple)):
        return [round_coords(x, p) for x in o]
    return round(o, p) if isinstance(o, float) else o


def main():
    src = json.loads((RAW / "lsoa_london_bgc.geojson").read_text())
    feats, by_borough = [], {}
    for f in src["features"]:
        g = shape(f["geometry"]).buffer(0).simplify(TOL_DEG, preserve_topology=True)
        if g.is_empty:
            continue
        name = f["properties"]["LSOA21NM"]
        feats.append({"type": "Feature",
                      "properties": {"c": f["properties"]["LSOA21CD"], "n": name},
                      "geometry": {**mapping(g), "coordinates":
                                   round_coords(mapping(g)["coordinates"])}})
        by_borough.setdefault(name.rsplit(" ", 1)[0], []).append(g)

    lsoa = {"type": "FeatureCollection", "features": feats}
    p = OUT / "lsoa_london.geojson"
    p.write_text(json.dumps(lsoa, separators=(",", ":")))
    print(f"{len(feats):,} LSOAs -> {p.name} "
          f"({(RAW / 'lsoa_london_bgc.geojson').stat().st_size/1e6:.1f} MB -> "
          f"{p.stat().st_size/1e6:.1f} MB)")

    # Borough outlines are the union of their LSOAs, so the two layers cannot
    # disagree about where a boundary is.
    bf = []
    for name, gs in sorted(by_borough.items()):
        g = unary_union(gs).simplify(TOL_DEG, preserve_topology=True)
        bf.append({"type": "Feature", "properties": {"n": name},
                   "geometry": {**mapping(g),
                                "coordinates": round_coords(mapping(g)["coordinates"])}})
    q = OUT / "borough_outline.geojson"
    q.write_text(json.dumps({"type": "FeatureCollection", "features": bf}, separators=(",", ":")))
    print(f"{len(bf)} boroughs -> {q.name} ({q.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
