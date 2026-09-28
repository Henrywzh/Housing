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
# overpass-api.de rotates over several backends and some of them answer a query
# that touches ways with an immediate 504; the same query succeeds seconds later
# on another. So retries are cheap and worth taking, and the box only gets split
# after six of them. kumi.systems is not in the list because it hangs until the
# socket timeout rather than refusing, which turned every retry into a long wait
# for nothing. overpass.osm.ch returns an empty set outside Switzerland.
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]

# Exact tag values, never a regex. Overpass has an index on the value of a tag
# and a regex cannot use it, so ["shop"~"^(supermarket|convenience)$"] scans the
# whole box and times out over inner London while ["shop"="supermarket"] answers
# the same box in seconds.
LAYERS = {
    "shops": ({"node": [("shop", v) for v in
                        ("supermarket", "convenience", "department_store", "greengrocer",
                         "bakery", "mall")],
               "way": [("shop", v) for v in
                       ("supermarket", "convenience", "department_store", "mall")]}, 3),
    "parks": ({"way": [("leisure", v) for v in ("park", "garden", "nature_reserve")],
               "relation": [("leisure", v) for v in ("park", "garden", "nature_reserve")]}, 3),
    "health_edu": ({"node": [("amenity", v) for v in
                             ("hospital", "clinic", "pharmacy", "doctors", "school",
                              "college", "university")],
                    "way": [("amenity", v) for v in
                            ("hospital", "clinic", "school", "college", "university")]}, 3),
    "food": ({"node": [("amenity", v) for v in ("cafe", "restaurant", "pub", "bar")]}, 4),
}



class Timeout(Exception):
    pass


def overpass(q, tries=6):
    for a in range(tries):
        ep = ENDPOINTS[a % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except Exception as e:
            code = getattr(e, "code", None)
            print(f"    retry {a+1} ({type(e).__name__}{' ' + str(code) if code else ''})",
                  flush=True)
            if a == tries - 1:
                # 504 and a socket timeout both mean the box is too big to answer,
                # not that the server is down: the caller should split it.
                raise Timeout(q) from e
            time.sleep(10 * (a + 1))


def quarters(box):
    s, w, n, e = [float(x) for x in box.split(",")]
    for i in range(2):
        for j in range(2):
            yield (f"{s + (n - s) * i / 2},{w + (e - w) * j / 2},"
                   f"{s + (n - s) * (i + 1) / 2},{w + (e - w) * (j + 1) / 2}")


def collect(body, box, depth=0):
    """Elements in a box, splitting the box whenever the server times out.

    Central London answers a shop query in seconds at the edges and not at all
    over the middle, so a fixed grid either wastes requests on empty fields or
    dies on the dense ones. Splitting only what fails costs one wasted attempt
    per hot tile and needs no guess about where the hot tiles are.
    """
    stmts = "".join(f'{t}["{k}"="{v}"]({box});' for t, kv in body.items() for k, v in kv)
    q = f"[out:json][timeout:180];({stmts});out center tags;"
    try:
        return overpass(q).get("elements", [])
    except Timeout:
        if depth >= 3:
            raise
        print(f"    splitting {box} (depth {depth + 1})", flush=True)
        out = []
        for sub in quarters(box):
            out += collect(body, sub, depth + 1)
        return out


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
                part.write_text(json.dumps(collect(body, box)))
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
