"""Amenity layers for the map, from OpenStreetMap via Overpass.

Artifact pages cannot load an external tile server -- the CSP blocks it -- so
every map layer has to ship with the page. Overpass gives us the features as
GeoJSON-able points, which is light enough to publish alongside the artifact
and rich enough to answer "is there a Waitrose / a park / a station near this
flat", which is what "convenient" actually means to a buyer.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "osm"
OUT.mkdir(parents=True, exist_ok=True)
BBOX = "51.35,-0.35,51.62,0.15"          # roughly Zone 1-4
UA = {"User-Agent": "housing-research/1.0"}
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]


def overpass(q, tries=4):
    for a in range(tries):
        ep = ENDPOINTS[a % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=420).read())
        except Exception as e:
            print(f"  retry {a+1} ({type(e).__name__})", flush=True)
            if a < tries - 1:
                time.sleep(15 * (a + 1)); continue
            raise


QUERIES = {
    "shops": f'''[out:json][timeout:300];
(node["shop"~"^(supermarket|convenience|department_store)$"]({BBOX});
 way["shop"~"^(supermarket|convenience|department_store)$"]({BBOX}););
out center tags;''',
    "parks": f'''[out:json][timeout:300];
(way["leisure"="park"]({BBOX});
 relation["leisure"="park"]({BBOX}););
out center tags;''',
    "health_edu": f'''[out:json][timeout:300];
(node["amenity"~"^(hospital|clinic|pharmacy)$"]({BBOX});
 way["amenity"~"^(hospital|clinic)$"]({BBOX});
 way["amenity"="school"]({BBOX}););
out center tags;''',
    "food": f'''[out:json][timeout:300];
(node["amenity"~"^(cafe|restaurant|pub)$"]({BBOX}););
out center tags;''',
}

if __name__ == "__main__":
    for name, q in QUERIES.items():
        print(f"{name} ...", flush=True)
        d = overpass(q)
        els = d.get("elements", [])
        feats = []
        for e in els:
            c = e.get("center") or e
            lat, lon = c.get("lat"), c.get("lon")
            if lat is None or lon is None:
                continue
            t = e.get("tags", {})
            feats.append({"lat": round(lat, 5), "lon": round(lon, 5),
                          "name": t.get("name"), "brand": t.get("brand"),
                          "kind": t.get("shop") or t.get("amenity") or t.get("leisure")})
        p = OUT / f"{name}.json"
        p.write_text(json.dumps(feats, ensure_ascii=False))
        print(f"  {len(feats):,} features -> {p.name} ({p.stat().st_size/1e6:.1f} MB)", flush=True)
