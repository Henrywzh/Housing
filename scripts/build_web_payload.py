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
MAN = ROOT / "data" / "manual"
WEB = ROOT / "web" / "data"
MAX_ZONE = 6


def num(x, nd=0):
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def main():
    WEB.mkdir(parents=True, exist_ok=True)

    # --- stations -----------------------------------------------------------
    s = pd.read_csv(PROC / "stations.csv")
    s = s[s["zone_min"] <= MAX_ZONE].copy()
    out = []
    for r in s.itertuples():
        out.append({
            "n": r.name, "y": round(r.lat, 5), "x": round(r.lon, 5), "z": r.zone,
            "zm": int(r.zone_min), "L": json.loads(r.lines.replace("'", '"')),
            "md": json.loads(r.modes.replace("'", '"')),
            "price": num(r.median_price), "p25": num(r.p25_price), "ns": int(r.n_sales),
            "psf": num(r.psf), "sqft": num(r.sqft), "npsf": int(r.n_psf),
            "new": int(r.n_new),
            "home": num(r.home_per_1000, 1), "bh": num(r.burglary_per_1000_hh, 1),
            "br": num(r.burglary_resid_per_1000_hh, 1), "rs": num(r.residential_share),
            "vc": num(r.vehicle_per_1000_cars, 1), "vs": num(r.visitor_share, 1), "res": num(r.resident_per_1000, 1),
            "pop": int(r.population),
            "shop": num(getattr(r, "n_shops", None)), "smkt": num(getattr(r, "n_supermarket", None)),
            "park": num(getattr(r, "n_parks", None)), "food": num(getattr(r, "n_food", None)),
            "he": num(getattr(r, "n_health_edu", None)),
            "prem": bool(getattr(r, "premium_grocer", False)),
        })
    # Minutes to be at Green Park by 08:40 (fetch_commute.py), the 方便 score's input.
    cmp = RAW / "commute_gp_0840.json"
    gp = json.loads(cmp.read_text()) if cmp.exists() else {}
    for o in out:
        g = gp.get(f"{o['y']:.5f},{o['x']:.5f}")
        if g:
            o["gp"] = g
    (WEB / "stations.json").write_text(json.dumps(out, separators=(",", ":")))
    stn = out                   # `out` is reused below
    print(f"{len(out)} Zone 1-{MAX_ZONE} stations -> stations.json "
          f"({(WEB / 'stations.json').stat().st_size/1e3:.0f} KB)")

    # --- LSOA geometry with its values baked in ----------------------------
    # MapLibre colours a fill from the feature's own properties, so the numbers
    # travel inside the geometry rather than in a second file joined at runtime.
    met = pd.read_csv(PROC / "lsoa_metrics.csv").set_index("lsoa")
    soc = pd.read_csv(PROC / "lsoa_social.csv").set_index("lsoa")
    met = met.join(soc[["burglary_per_1000_hh", "burglary_resid_per_1000_hh",
                        "residential_share", "vehicle_per_1000_cars",
                        "violence_per_1000", "visitor_share", "density",
                        "degree_pct", "age_25_39_pct", "owned_pct",
                        "private_rent_pct"]])
    geo = json.loads((PROC / "lsoa_london.geojson").read_text())
    KEYS = {"h": ("home_per_1000", 1), "r": ("resident_per_1000", 0),
            "br": ("burglary_resid_per_1000_hh", 1), "rs": ("residential_share", 0),
            "bh": ("burglary_per_1000_hh", 1), "vc": ("vehicle_per_1000_cars", 1),
            "vi": ("violence_per_1000", 1), "vs": ("visitor_share", 1),
            "de": ("density", 0), "dg": ("degree_pct", 1), "ag": ("age_25_39_pct", 1),
            "ow": ("owned_pct", 1), "pr": ("private_rent_pct", 1),
            "p": ("median", 0), "nb": ("new_pct", 0), "t": ("turnover", 1)}
    hit = 0
    for f in geo["features"]:
        code = f["properties"]["c"]
        if code in met.index:
            r = met.loc[code]
            for k, (col, nd) in KEYS.items():
                v = num(r[col], nd)
                if v is not None:
                    f["properties"][k] = v
            hit += 1
    (WEB / "lsoa.geojson").write_text(json.dumps(geo, separators=(",", ":")))
    print(f"lsoa.geojson: {hit:,}/{len(geo['features']):,} with values, "
          f"{(WEB / 'lsoa.geojson').stat().st_size/1e6:.1f} MB")

    (WEB / "boroughs.geojson").write_bytes((PROC / "borough_outline.geojson").read_bytes())
    print(f"boroughs.geojson: {(WEB / 'boroughs.geojson').stat().st_size/1e6:.1f} MB")

    # Break points for the choropleth, computed here so the page does not have to
    # hold every LSOA value just to work out its own legend.
    breaks = {k: [round(v, 1) for v in met[c].dropna().quantile(
        [i / 7 for i in range(1, 7)]).tolist()]
        for k, (c, _) in KEYS.items()}
    # Two thirds of LSOAs have sold no new-build at all since 2019, so quantile
    # breaks put six of the seven bands at zero and the map goes flat. Fixed
    # bands instead, at shares a reader can name.
    breaks["nb"] = [1, 5, 10, 20, 35, 55]
    # Most LSOAs are wholly residential, so the top quantiles all land on 100 and
    # the interesting end -- the mixed and commercial ones -- gets one band.
    breaks["rs"] = [50, 70, 85, 92, 97, 99.5]
    (WEB / "breaks.json").write_text(json.dumps(breaks))
    print("breaks:", breaks)

    # --- amenities ----------------------------------------------------------
    # Parks and schools are drawn as one dot each; only the premium grocers are
    # named, because the name is the signal there and nowhere else.
    pts = {}
    for name, d in load_osm().items():
        # Only a shop can be a premium grocer. Five cafes carry "M&S" in their
        # name and an M&S Cafe is not the signal we are reading off a Waitrose.
        prem = is_premium(d) if name == "shops" else pd.Series(False, index=d.index)
        rows = [[round(r.lat, 5), round(r.lon, 5), r.kind or ""]
                + ([r.name] if p else [])
                for r, p in zip(d.itertuples(), prem)]
        pts[name] = rows
        print(f"  {name}: {len(rows):,} ({int(prem.sum())} premium grocers)")
    (WEB / "amenities.json").write_text(json.dumps(pts, separators=(",", ":")))
    print(f"amenities.json: {(WEB / 'amenities.json').stat().st_size/1e6:.1f} MB")

    # Rail lines, simplified to 10m: below a pixel at any zoom this map offers.
    from shapely.geometry import LineString, mapping
    src = json.loads((RAW / "transport" / "lines.geojson").read_text())

    # The Overground's six named lines are dropped in favour of one orange line,
    # which is how the map this one grew out of drew it and how the network is
    # still read; Liberty and Lioness were the only two OSM would give up anyway,
    # so keeping them would have shown two sixths of a network as if it were all
    # of it.
    sup = json.loads((MAN / "lines_supplement.json").read_text())
    src["features"] = [f for f in src["features"]
                       if f["properties"]["name"] not in ("Liberty", "Lioness")]
    for name, parts in sup["lines"].items():
        src["features"].append({
            "type": "Feature",
            "properties": {"name": name, "mode": "rail",
                           "color": sup["_colors"][name], "z": 0},
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[lon, lat] for lat, lon in seg]
                                         for seg in parts if len(seg) > 1]}})
    # National Rail last in the file so it draws first, under the TfL colours:
    # where they share track -- and through south London they often do -- the
    # line a reader is looking for is the coloured one.
    rail = RAW / "transport" / "rail.geojson"
    if rail.exists():
        src["features"] = json.loads(rail.read_text())["features"] + src["features"]

    tol = 10 / 111_320.0
    for f in src["features"]:
        out = []
        for c in f["geometry"]["coordinates"]:
            g = LineString(c).simplify(tol, preserve_topology=False)
            if len(g.coords) > 1:
                out.append([[round(x, 5), round(y, 5)] for x, y in g.coords])
        f["geometry"]["coordinates"] = out
    (WEB / "lines.geojson").write_text(json.dumps(src, separators=(",", ":")))
    print(f"{len(src['features'])} rail lines -> lines.geojson "
          f"({(WEB / 'lines.geojson').stat().st_size/1e3:.0f} KB)")

    sc = pd.read_csv(PROC / "schemes.csv")
    lst_pts = []
    slp = PROC / "shortlist.json"
    if slp.exists():
        lst_pts = [(r["street"].upper(), r["lat"], r["lon"])
                   for r in json.loads(slp.read_text())["listings"]
                   if r.get("street") and r.get("lat") is not None]
    # A resale scheme's commute is its nearest station's plus the walk to it, at
    # 80 m a minute -- not asked of TfL separately for 1,099 points.
    st_gp = {o["n"]: o["gp"]["min"] for o in stn if o.get("gp")}
    rows = []
    for r in sc.itertuples():
        rows.append({
            "s": r.label, "sec": r.sector, "pc": r.postcode, "st_name": r.street.title(), "y": round(r.lat, 5), "x": round(r.lon, 5),
            "st": r.station, "z": r.zone, "zm": int(r.zone_min), "d": int(r.station_m),
            "nn": int(r.n_new), "nr": int(r.n_resale),
            "f": r.first_new[:7], "l": (r.last_resale[:7] if isinstance(r.last_resale, str) else None),
            "rm": num(r.resale_median), "r25": num(r.resale_p25), "nm": num(r.new_median),
            "psf": num(r.psf), "gap": num(r.gap_pct, 1),
            "ps": num(r.part_share_pct, 1), "pre": bool(r.pre_existing_stock), "sh": bool(r.share_suspect),
            "home": num(r.home_per_1000, 1), "bh": num(r.burglary_per_1000_hh, 1),
            "br": num(r.burglary_resid_per_1000_hh, 1), "rs": num(r.residential_share),
            "vc": num(r.vehicle_per_1000_cars, 1), "vs": num(r.visitor_share, 1),
            "shop": int(r.n_shops), "food": int(r.n_food), "park": int(r.n_parks),
            "prem": bool(r.premium_grocer),
            # A hand-collected listing counts only if it is on this scheme's street
            # AND within 400 m: with the scheme now a postcode, a long street has
            # many, and most of them are not where the listing is.
            "has": any(r.street == a and abs(r.lat - la) < .0036 and abs(r.lon - lo) < .0058
                       for a, la, lo in lst_pts),
            "gp": (st_gp[r.station] + round(r.station_m / 80)) if r.station in st_gp else None})
    (WEB / "schemes.json").write_text(json.dumps(rows, separators=(",", ":")))
    print(f"{len(rows):,} Zone 1-4 schemes -> schemes.json "
          f"({(WEB / 'schemes.json').stat().st_size/1e3:.0f} KB)")

    # Developers' own sites: what is selling or coming soon, at asking prices read
    # off the page on the day of the fetch. Barratt has its own fetcher because its
    # pages list individual plots (fetch_barratt.py); the rest come from one
    # generic reader (fetch_developers.py). Merged here into one file the page
    # draws as one layer.
    devs, names, fetched = [], {}, []
    bt = RAW / "barratt.json"
    if bt.exists():
        b = json.loads(bt.read_text())
        names["barratt"] = "Barratt London"
        fetched.append(b["fetched"])
        devs += [dict(d, dev="barratt") for d in b["developments"]]
    ot = RAW / "developers.json"
    if ot.exists():
        o = json.loads(ot.read_text())
        names.update(o["developers"])
        fetched.append(o["fetched"])
        devs += [d for d in o["developments"] if d["dev"] != "barratt"]
    # Door-to-door minutes to Green Park at the weekday morning peak, from TfL's
    # planner (fetch_commute.py), joined by coordinates.
    for d in devs:
        g = gp.get(f"{d['lat']:.5f},{d['lon']:.5f}")
        if g:
            d["gp"] = g
    if devs:
        (WEB / "devs.json").write_text(json.dumps(
            {"fetched": min(fetched), "developers": names, "developments": devs},
            ensure_ascii=False, separators=(",", ":")))
        by = {}
        for d in devs:
            by[d["dev"]] = by.get(d["dev"], 0) + 1
        print(f"devs.json: {len(devs)} developments  " + ", ".join(f"{k} {n}" for k, n in by.items()))

    sl = PROC / "shortlist.json"
    if sl.exists():
        (WEB / "shortlist.json").write_bytes(sl.read_bytes())
        print(f"shortlist.json: {(WEB / 'shortlist.json').stat().st_size/1e3:.0f} KB")


if __name__ == "__main__":
    main()
