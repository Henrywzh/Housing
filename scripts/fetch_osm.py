"""Amenity layers for the map, from OpenStreetMap via Overpass.

An artifact page cannot load an external tile server -- the CSP blocks it -- so
every layer has to ship with the page. Overpass returns the features as points,
light enough to publish alongside the artifact and enough to answer "is there a
Waitrose, a park, a station within a ten-minute walk", which is what
"convenient" means to a buyer.

The box covers every Zone 1-4 station plus a kilometre of walking room. It is
asked for in tiles rather than whole: a single query for all of London's cafes
and pubs times out at the Overpass gateway, and a tile that fails only costs
that tile, because finished tiles are kept on disk.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "osm"
OUT.mkdir(parents=True, exist_ok=True)
# Zone 1-4 stations span 51.375-51.638 N, 0.379 W - 0.121 E; +1km of walking room.
S, W, N, E = 51.365, -0.392, 51.650, 0.135
UA = {"User-Agent": "housing-research/1.0"}
# overpass.kumi.systems hangs until the socket timeout rather than refusing, so
# alternating to it turned every retry into a seven-minute wait for nothing.
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]

LAYERS = {
    "shops": ('node["shop"~"^(supermarket|convenience|department_store|greengrocer|bakery)$"]({b});'
              'way["shop"~"^(supermarket|convenience|department_store)$"]({b});'
              'node["shop"="mall"]({b});way["shop"="mall"]({b});', 3),
    "parks": ('way["leisure"~"^(park|garden|nature_reserve)$"]({b});'
              'relation["leisure"~"^(park|garden|nature_reserve)$"]({b});', 3),
    "health_edu": ('node["amenity"~"^(hospital|clinic|pharmacy|doctors)$"]({b});'
                   'way["amenity"~"^(hospital|clinic)$"]({b});'
                   'way["amenity"~"^(school|college|university)$"]({b});'
                   'node["amenity"~"^(school|college|university)$"]({b});', 3),
    "food": ('node["amenity"~"^(cafe|restaurant|pub|bar)$"]({b});', 4),
}


def overpass(q, tries=5):
    for a in range(tries):
        ep = ENDPOINTS[a % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=240).read())
        except Exception as e:
            print(f"    retry {a+1} ({type(e).__name__})", flush=True)
            if a == tries - 1:
                raise
            time.sleep(20 * (a + 1))


def tiles(n):
    for i in range(n):
        for j in range(n):
            yield (f"{S + (N - S) * i / n},{W + (E - W) * j / n},"
                   f"{S + (N - S) * (i + 1) / n},{W + (E - W) * (j + 1) / n}")


def main():
    for name, (body, n) in LAYERS.items():
        out = OUT / f"{name}.json"
        if out.exists():
            print(f"have {out.name}"); continue
        feats, seen = [], set()
        for k, box in enumerate(tiles(n), 1):
            part = OUT / f".{name}.{n}x{n}.{k}.json"
            if not part.exists():
                q = f"[out:json][timeout:300];({body.format(b=box)});out center tags;"
                part.write_text(json.dumps(overpass(q).get("elements", [])))
            els = json.loads(part.read_text())
            for e in els:
                # A tile boundary splits nothing, but a way can be returned by two
                # tiles when its centre falls on the line; id dedupes it.
                oid = (e["type"], e["id"])
                if oid in seen:
                    continue
                seen.add(oid)
                c = e.get("center") or e
                if c.get("lat") is None:
                    continue
                t = e.get("tags", {})
                feats.append({"lat": round(c["lat"], 5), "lon": round(c["lon"], 5),
                              "name": t.get("name"), "brand": t.get("brand"),
                              "kind": t.get("shop") or t.get("amenity") or t.get("leisure")})
            print(f"  {name} tile {k}/{n*n}: {len(feats):,} kept", flush=True)
        out.write_text(json.dumps(feats, ensure_ascii=False))
        for p in OUT.glob(f".{name}.*.json"):
            p.unlink()
        print(f"{name}: {len(feats):,} features ({out.stat().st_size/1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
