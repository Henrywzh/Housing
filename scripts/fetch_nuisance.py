"""Things a buyer, and then a tenant, would rather not live next to, from OpenStreetMap.

Prisons, waste sites and works, power stations, motorways, railway viaducts,
runways and big building sites. These are rare features, so each is one query over
the whole Zone 1-6 box (split by fetch_osm.collect-style retrying if the server
times out) rather than the tile grid the amenity layers need.

Stored as plain geometry (points, or lists of [lat, lon] for lines) under
data/raw/osm_nuisance/, one file per kind. The distances are computed in
build_web_payload.py, where a threshold per kind decides what is flagged.
"""
import json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from fetch_osm import overpass, quarters, Timeout  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "osm_nuisance"
OUT.mkdir(parents=True, exist_ok=True)
BOX = "51.27,-0.57,51.71,0.31"          # Zone 1-6 with a little room

# kind -> (overpass statements, "line" if it is a way to be drawn as a line)
KINDS = {
    "prison":   (['nwr["amenity"="prison"]', 'nwr["building"="prison"]'], "area"),
    "waste":    (['nwr["amenity"="waste_transfer_station"]', 'nwr["landuse"="landfill"]',
                  'nwr["man_made"="wastewater_plant"]', 'nwr["man_made"="sewage_works"]'], "area"),
    "power":    (['nwr["power"="plant"]'], "area"),
    "building_site": (['way["landuse"="construction"]'], "area"),
    "motorway": (['way["highway"="motorway"]'], "line"),
    "viaduct":  (['way["railway"="rail"]["bridge"="viaduct"]'], "line"),
    "runway":   (['way["aeroway"="runway"]'], "line"),
}


def fetch(stmts, kind, box, depth=0):
    body = "".join(f"{s}({box});" for s in stmts)
    q = f"[out:json][timeout:180];({body});out {'geom' if kind == 'line' else 'center'} tags;"
    try:
        return overpass(q).get("elements", [])
    except Timeout:
        if depth >= 3:
            raise
        print(f"    splitting {box}", flush=True)
        return [e for sub in quarters(box) for e in fetch(stmts, kind, sub, depth + 1)]


def main():
    for name, (stmts, kind) in KINDS.items():
        f = OUT / f"{name}.json"
        if f.exists() and "--refresh" not in sys.argv:
            print(f"have {f.name}"); continue
        els = fetch(stmts, kind, BOX)
        feats, seen = [], set()
        for e in els:
            if (e["type"], e["id"]) in seen:
                continue
            seen.add((e["type"], e["id"]))
            t = e.get("tags", {})
            nm = t.get("name") or t.get("operator")
            if kind == "line":
                g = [[p["lat"], p["lon"]] for p in e.get("geometry", [])]
                if len(g) > 1:
                    feats.append({"name": nm, "line": g})
            else:
                c = e.get("center") or e
                if "lat" in c:
                    feats.append({"name": nm, "lat": c["lat"], "lon": c["lon"]})
        f.write_text(json.dumps(feats, ensure_ascii=False))
        print(f"{name}: {len(feats)}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
