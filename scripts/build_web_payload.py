"""Web payload: the files the Zone 1-4 map page fetches alongside itself.

An artifact page can publish supporting files and fetch them same-origin, which
is the only way this much geometry travels: 4,994 LSOA polygons, 695 stations
and ~20,000 amenity points do not belong inlined in a single HTML file.

Everything here is rounded and renamed short. Five decimal places is about a
metre, which is finer than the 15 m simplification the polygons already carry,
and one-letter keys off a 20,000-row array are worth roughly a third of the file.
"""
import json, pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from osm_layers import load as load_osm, is_premium  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
WEB = ROOT / "web" / "data"


def num(x, nd=0):
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def main():
    WEB.mkdir(parents=True, exist_ok=True)

    # --- stations -----------------------------------------------------------
    s = pd.read_csv(PROC / "stations.csv")
    s = s[s["zone_min"] <= 4].copy()
    out = []
    for r in s.itertuples():
        out.append({
            "n": r.name, "y": round(r.lat, 5), "x": round(r.lon, 5), "z": r.zone,
            "zm": int(r.zone_min), "L": json.loads(r.lines.replace("'", '"')),
            "md": json.loads(r.modes.replace("'", '"')),
            "price": num(r.median_price), "p25": num(r.p25_price), "ns": int(r.n_sales),
            "psf": num(r.psf), "sqft": num(r.sqft), "npsf": int(r.n_psf),
            "new": int(r.n_new),
            "home": num(r.home_per_1000, 1), "res": num(r.resident_per_1000, 1),
            "pop": int(r.population),
            "shop": num(getattr(r, "n_shops", None)), "smkt": num(getattr(r, "n_supermarket", None)),
            "park": num(getattr(r, "n_parks", None)), "food": num(getattr(r, "n_food", None)),
            "he": num(getattr(r, "n_health_edu", None)),
            "prem": bool(getattr(r, "premium_grocer", False)),
        })
    (WEB / "stations.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(out)} Zone 1-4 stations -> stations.json "
          f"({(WEB / 'stations.json').stat().st_size/1e3:.0f} KB)")

    # --- LSOA geometry with its values baked in ----------------------------
    # MapLibre colours a fill from the feature's own properties, so the numbers
    # travel inside the geometry rather than in a second file joined at runtime.
    saf = pd.read_csv(PROC / "lsoa_safety.csv").set_index("LSOA code")
    geo = json.loads((PROC / "lsoa_london.geojson").read_text())
    hit = 0
    for f in geo["features"]:
        code = f["properties"]["c"]
        if code in saf.index:
            r = saf.loc[code]
            f["properties"]["h"] = num(r["home_per_1000"], 1)
            f["properties"]["r"] = num(r["resident_per_1000"])
            hit += 1
    (WEB / "lsoa.geojson").write_text(json.dumps(geo, separators=(",", ":")))
    print(f"lsoa.geojson: {hit:,}/{len(geo['features']):,} with values, "
          f"{(WEB / 'lsoa.geojson').stat().st_size/1e6:.1f} MB")

    (WEB / "boroughs.geojson").write_bytes((PROC / "borough_outline.geojson").read_bytes())
    print(f"boroughs.geojson: {(WEB / 'boroughs.geojson').stat().st_size/1e6:.1f} MB")

    # Break points for the choropleth, computed here so the page does not have to
    # hold every LSOA value just to work out its own legend.
    breaks = {k: [round(v, 1) for v in saf[c].quantile(
        [i / 7 for i in range(1, 7)]).tolist()]
        for k, c in (("h", "home_per_1000"), ("r", "resident_per_1000"))}
    (WEB / "breaks.json").write_text(json.dumps(breaks))
    print("breaks:", breaks)

    # --- amenities ----------------------------------------------------------
    # Parks and schools are drawn as one dot each; only the premium grocers are
    # named, because the name is the signal there and nowhere else.
    pts = {}
    for name, d in load_osm().items():
        prem = is_premium(d)
        rows = [[round(r.lat, 5), round(r.lon, 5), r.kind or ""]
                + ([r.name] if p else [])
                for r, p in zip(d.itertuples(), prem)]
        pts[name] = rows
        print(f"  {name}: {len(rows):,} ({int(prem.sum())} premium grocers)")
    (WEB / "amenities.json").write_text(json.dumps(pts, separators=(",", ":")))
    print(f"amenities.json: {(WEB / 'amenities.json').stat().st_size/1e6:.1f} MB")

    sl = PROC / "shortlist.json"
    if sl.exists():
        (WEB / "shortlist.json").write_bytes(sl.read_bytes())
        print(f"shortlist.json: {(WEB / 'shortlist.json').stat().st_size/1e3:.0f} KB")


if __name__ == "__main__":
    main()
