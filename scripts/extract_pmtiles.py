"""Cut a London-sized basemap out of the Protomaps world build.

The world build is 138 GB and lives behind HTTP range requests, which is what
PMTiles is for: the tiles covering Zone 1-4 from z0 to z14 are about 700 of
them, so the extract costs roughly 700 small reads rather than a download.

Size is the constraint at the other end -- the whole thing has to travel to a
browser as a published file -- so two things are trimmed. Vector layers can be
dropped from a tile without re-encoding any geometry, because a Mapbox Vector
Tile is just a protobuf whose field 3 repeats once per layer: read the layers,
keep the ones asked for, concatenate. Buildings are the obvious candidate at
27% of the bytes, and a map whose job is to say which streets and parks are
near a station does not need them.

Tiles are cached on disk, so a stopped run resumes and a re-run with different
layers costs nothing.
"""
import argparse, gzip, json, math, pathlib, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pmtiles  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "basemap"
BUILD = "https://build.protomaps.com/{date}.pmtiles"
# Zone 1-6 stations span 51.29-51.69 N, 0.51 W - 0.27 E (Heathrow to Upminster), plus walking room.
BOUNDS = (-0.56, 51.28, 0.30, 51.70)
FINER = {12: (-0.46, 51.33, 0.17, 51.68),    # z12: Zone 1-5 and most of 6
         13: (-0.36, 51.40, 0.05, 51.62)}    # z13: Zone 1-4 and Harrow
CENTER = (-0.10, 51.505, 11)


# --------------------------------------------------------------------------- #
# minimal protobuf: enough to split a tile into its layers
# --------------------------------------------------------------------------- #
def fields(buf):
    i = 0
    while i < len(buf):
        key, i = pmtiles.read_varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 2:
            n, i = pmtiles.read_varint(buf, i)
            yield fn, buf[i:i + n]
            i += n
        elif wt == 0:
            _, i = pmtiles.read_varint(buf, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            raise ValueError(f"unsupported wire type {wt}")


def layer_name(layer):
    for fn, payload in fields(layer):
        if fn == 1:                      # Layer.name
            return payload.decode()
    return None


def keep_layers(raw, keep):
    """Re-emit an MVT with only the named layers. Geometry is copied verbatim."""
    out = bytearray()
    for fn, payload in fields(raw):
        if fn != 3 or layer_name(payload) in keep:   # Tile.layers
            out.append((fn << 3) | 2)
            pmtiles.write_varint(out, len(payload))
            out += payload
    return bytes(out)


# --------------------------------------------------------------------------- #
def tiles_for(bounds, zmin, zmax, finer=None):
    """Tiles covering `bounds`, with smaller areas at the finest zooms.

    `finer` maps a zoom to the bounds its tiles are kept for, from that zoom up.
    The artifact host takes a binary file up to 15 MB and the last two zooms are
    most of the bytes, so the outer ring (Zone 5-6) is carried at coarser zooms
    only and MapLibre stretches them when you zoom past them.
    """
    cut = sorted((finer or {}).items())
    for z in range(zmin, zmax + 1):
        w, s, e, n = bounds
        for zf, bb in cut:
            if z >= zf:
                w, s, e, n = bb
        x0, y0 = pmtiles.lonlat_to_tile(w, n, z)
        x1, y1 = pmtiles.lonlat_to_tile(e, s, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="20260927", help="Protomaps build date")
    ap.add_argument("--min-zoom", type=int, default=9,
                    help="a z8 tile over London carries all of southern England and "
                         "costs more than the whole of z11; the map does not zoom out "
                         "that far, so those tiles are not worth carrying")
    ap.add_argument("--max-zoom", type=int, default=13)
    ap.add_argument("--drop-above", type=int, default=12,
                    help="zoom above which --drop layers are removed")
    ap.add_argument("--drop", default="buildings", help="comma-separated layers to drop")
    # .wasm because the artifact host serves only a fixed list of extensions and
    # that is the one on it that returns exact bytes. It is not WebAssembly.
    ap.add_argument("--out", default="web/data/london.pmtiles.wasm")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    drop = {x for x in a.drop.split(",") if x}

    CACHE.mkdir(parents=True, exist_ok=True)
    url = BUILD.format(date=a.date)
    r = pmtiles.Remote(url)
    print(f"source {url}\n  zooms {r.header['min_zoom']}-{r.header['max_zoom']}, "
          f"{r.header['addressed']:,} addressed tiles", flush=True)

    want = list(tiles_for(BOUNDS, a.min_zoom, a.max_zoom, FINER))
    by_zoom = {}
    for z, _, _ in want:
        by_zoom[z] = by_zoom.get(z, 0) + 1
    print(f"  {len(want)} tiles: " + " ".join(f"z{z}:{n}" for z, n in sorted(by_zoom.items())),
          flush=True)

    def fetch(t):
        z, x, y = t
        p = CACHE / f"{z}_{x}_{y}.mvt"
        if p.exists():
            return t, p.read_bytes()
        b = r.tile(z, x, y)
        p.write_bytes(b or b"")
        return t, (b or b"")

    got, t0 = {}, time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for k, (t, b) in enumerate(ex.map(fetch, want), 1):
            if b:
                got[t] = b
            if k % 100 == 0:
                print(f"  {k}/{len(want)}  {sum(len(v) for v in got.values())/1e6:.1f} MB  "
                      f"{time.time()-t0:.0f}s", flush=True)
    print(f"  {len(got)} non-empty tiles, {sum(len(v) for v in got.values())/1e6:.1f} MB raw",
          flush=True)

    if drop:
        before = sum(len(v) for v in got.values())
        vl = {l["id"] for l in r.metadata["vector_layers"]}
        missing = drop - vl
        if missing:
            raise SystemExit(f"layers named for dropping are not in this tileset: {missing}")
        keep = vl - drop
        for t in list(got):
            if t[0] <= a.drop_above:
                continue
            got[t] = gzip.compress(keep_layers(gzip.decompress(got[t]), keep), 9)
        after = sum(len(v) for v in got.values())
        print(f"  dropped {sorted(drop)} above z{a.drop_above}: "
              f"{before/1e6:.1f} -> {after/1e6:.1f} MB", flush=True)

    meta = dict(r.metadata)
    meta["name"] = "London Zone 1-4"
    meta["description"] = (f"Extract of the Protomaps {a.date} build for "
                           f"{BOUNDS}, z{a.min_zoom}-{a.max_zoom}"
                           + (f", without {sorted(drop)} above z{a.drop_above}" if drop else ""))
    meta["vector_layers"] = [l for l in meta["vector_layers"]
                             if l["id"] not in drop or a.drop_above >= a.max_zoom]

    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    h = pmtiles.write_archive(out, got, meta, BOUNDS, (a.min_zoom, a.max_zoom), CENTER)
    print(f"{out.relative_to(ROOT)}  {out.stat().st_size/1e6:.1f} MB  "
          f"{h['tile_entries']:,} entries, {h['tile_contents']:,} distinct tiles")
    print(f"network: {r.requests} range requests, {r.bytes_read/1e6:.1f} MB read")


if __name__ == "__main__":
    main()
