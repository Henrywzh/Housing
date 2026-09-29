"""A PMTiles v3 reader and writer, in the standard library only.

The published tooling for this is a Go binary. Installing one on someone's
machine to copy a few hundred tiles out of a file is not a fair trade, and the
format does not need it: PMTiles is a 127-byte header, two levels of directory
and a blob of tiles, all addressed by a Hilbert curve, and every part of that is
documented. So this reads the world basemap over HTTP range requests -- the
access pattern the format exists for -- and writes the extract back out as a
valid archive.

Spec: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md

The one subtlety is the directory encoding. A directory is a run of varints in
four columns -- tile id deltas, run lengths, byte lengths, byte offsets -- and
an offset of 0 does not mean offset zero; it means "directly after the previous
tile", which is how a clustered archive stores a run of adjacent tiles for
almost nothing. Both the reader and the writer have to agree on that.
"""
import gzip, io, json, math, struct, urllib.request

HEADER_BYTES = 127
MAGIC = b"PMTiles"
COMPRESSION = {0: "unknown", 1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}
TILETYPE = {0: "unknown", 1: "mvt", 2: "png", 3: "jpeg", 4: "webp", 5: "avif"}


# --------------------------------------------------------------------------- #
# varints
# --------------------------------------------------------------------------- #
def read_varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def write_varint(out, v):
    while v >= 0x80:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)


# --------------------------------------------------------------------------- #
# tile ids: Hilbert order within a zoom, zooms stacked in order
# --------------------------------------------------------------------------- #
def zxy_to_tileid(z, x, y):
    if z > 31 or x >= 1 << z or y >= 1 << z:
        raise ValueError(f"tile {z}/{x}/{y} out of range")
    acc = ((1 << (z * 2)) - 1) // 3      # every tile in every zoom below z
    n, rx, ry, d = 1 << z, 0, 0, 0
    s = n >> 1
    while s > 0:
        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        # rotate the quadrant so the curve stays continuous
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def lonlat_to_tile(lon, lat, z):
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


# --------------------------------------------------------------------------- #
# header and directories
# --------------------------------------------------------------------------- #
class Header(dict):
    @staticmethod
    def parse(b):
        if b[:7] != MAGIC or b[7] != 3:
            raise ValueError("not a PMTiles v3 archive")
        f = struct.unpack_from("<QQQQQQQQQQQ", b, 8)
        h = Header(root_offset=f[0], root_length=f[1], metadata_offset=f[2],
                   metadata_length=f[3], leaf_offset=f[4], leaf_length=f[5],
                   data_offset=f[6], data_length=f[7], addressed=f[8],
                   tile_entries=f[9], tile_contents=f[10])
        h["clustered"] = b[96]
        h["internal_compression"] = b[97]
        h["tile_compression"] = b[98]
        h["tile_type"] = b[99]
        h["min_zoom"], h["max_zoom"] = b[100], b[101]
        (h["min_lon"], h["min_lat"], h["max_lon"], h["max_lat"]) = [
            v / 1e7 for v in struct.unpack_from("<iiii", b, 102)]
        h["center_zoom"] = b[118]
        h["center_lon"], h["center_lat"] = [v / 1e7 for v in struct.unpack_from("<ii", b, 119)]
        return h

    def pack(self):
        b = bytearray(HEADER_BYTES)
        b[0:7], b[7] = MAGIC, 3
        struct.pack_into("<QQQQQQQQQQQ", b, 8, self["root_offset"], self["root_length"],
                         self["metadata_offset"], self["metadata_length"], self["leaf_offset"],
                         self["leaf_length"], self["data_offset"], self["data_length"],
                         self["addressed"], self["tile_entries"], self["tile_contents"])
        b[96] = self["clustered"]
        b[97] = self["internal_compression"]
        b[98] = self["tile_compression"]
        b[99] = self["tile_type"]
        b[100], b[101] = self["min_zoom"], self["max_zoom"]
        struct.pack_into("<iiii", b, 102, *[round(self[k] * 1e7) for k in
                                            ("min_lon", "min_lat", "max_lon", "max_lat")])
        b[118] = self["center_zoom"]
        struct.pack_into("<ii", b, 119, round(self["center_lon"] * 1e7),
                         round(self["center_lat"] * 1e7))
        return bytes(b)


def decompress(b, kind):
    if kind in (0, 1):
        return b
    if kind == 2:
        return gzip.decompress(b)
    raise ValueError(f"unsupported internal compression: {COMPRESSION.get(kind, kind)}")


def deserialize_directory(b):
    """-> list of (tile_id, offset, length, run_length)."""
    n, i = read_varint(b, 0)
    ids, last = [0] * n, 0
    for k in range(n):
        d, i = read_varint(b, i)
        last += d
        ids[k] = last
    runs = [0] * n
    for k in range(n):
        runs[k], i = read_varint(b, i)
    lens = [0] * n
    for k in range(n):
        lens[k], i = read_varint(b, i)
    offs = [0] * n
    for k in range(n):
        v, i = read_varint(b, i)
        # 0 is the "immediately after the previous tile" shorthand, not offset 0.
        offs[k] = offs[k - 1] + lens[k - 1] if v == 0 and k > 0 else v - 1
    return list(zip(ids, offs, lens, runs))


def serialize_directory(entries):
    out = bytearray()
    write_varint(out, len(entries))
    last = 0
    for tid, _, _, _ in entries:
        write_varint(out, tid - last)
        last = tid
    for _, _, _, run in entries:
        write_varint(out, run)
    for _, _, ln, _ in entries:
        write_varint(out, ln)
    for k, (_, off, _, _) in enumerate(entries):
        if k > 0 and off == entries[k - 1][1] + entries[k - 1][2]:
            write_varint(out, 0)
        else:
            write_varint(out, off + 1)
    return bytes(out)


def find_tile(entries, tid):
    lo, hi = 0, len(entries) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if tid < entries[mid][0]:
            hi = mid - 1
        elif tid > entries[mid][0]:
            lo = mid + 1
        else:
            return entries[mid]
    # Not an exact hit: the entry before it may cover this id with a run, or be
    # a leaf-directory pointer (run_length 0) that owns the whole range.
    if hi >= 0:
        e = entries[hi]
        if e[3] == 0 or tid - e[0] < e[3]:
            return e
    return None


# --------------------------------------------------------------------------- #
# remote reader
# --------------------------------------------------------------------------- #
class Remote:
    """Random access into a PMTiles archive over HTTP range requests."""

    def __init__(self, url, ua="housing-research/1.0"):
        self.url = url
        self.ua = ua
        self.requests = self.bytes_read = 0
        self._leaf_cache = {}
        head = self.range(0, 16384)
        self.header = Header.parse(head)
        h = self.header
        if h["tile_type"] != 1:
            raise ValueError(f"expected MVT tiles, got {TILETYPE.get(h['tile_type'])}")
        if h["root_offset"] + h["root_length"] <= len(head):
            root = head[h["root_offset"]:h["root_offset"] + h["root_length"]]
        else:
            root = self.range(h["root_offset"], h["root_length"])
        self.root = deserialize_directory(decompress(root, h["internal_compression"]))
        self.metadata = json.loads(decompress(
            self.range(h["metadata_offset"], h["metadata_length"]),
            h["internal_compression"]).decode())

    def range(self, offset, length, tries=5):
        req = urllib.request.Request(
            self.url, headers={"Range": f"bytes={offset}-{offset + length - 1}",
                               "User-Agent": self.ua})
        for a in range(tries):
            try:
                b = urllib.request.urlopen(req, timeout=90).read()
                self.requests += 1
                self.bytes_read += len(b)
                return b
            except Exception:
                if a == tries - 1:
                    raise
                import time
                time.sleep(3 * (a + 1))

    def leaf(self, offset, length):
        if offset not in self._leaf_cache:
            self._leaf_cache[offset] = deserialize_directory(decompress(
                self.range(self.header["leaf_offset"] + offset, length),
                self.header["internal_compression"]))
        return self._leaf_cache[offset]

    def entry(self, z, x, y):
        """-> (offset, length) of the tile blob, or None. Follows one leaf level."""
        tid = zxy_to_tileid(z, x, y)
        e = find_tile(self.root, tid)
        if e is None:
            return None
        if e[3] == 0:                      # leaf directory pointer
            e = find_tile(self.leaf(e[1], e[2]), tid)
            if e is None or e[3] == 0:
                return None
        return e[1], e[2]

    def tile(self, z, x, y):
        e = self.entry(z, x, y)
        if e is None:
            return None
        return self.range(self.header["data_offset"] + e[0], e[1])


# --------------------------------------------------------------------------- #
# writer
# --------------------------------------------------------------------------- #
def write_archive(path, tiles, metadata, bounds, zooms, center,
                  tile_compression=2, max_root_bytes=16384 - HEADER_BYTES):
    """Write a clustered v3 archive.

    `tiles` maps (z, x, y) -> compressed tile bytes. Identical tiles are stored
    once and addressed many times, which matters here because most of the sea
    and most of z0-z8 outside the extract is the same empty tile.
    """
    items = sorted(((zxy_to_tileid(z, x, y), b) for (z, x, y), b in tiles.items()),
                   key=lambda t: t[0])
    blob, seen, entries = bytearray(), {}, []
    for tid, b in items:
        if b in seen:
            off, ln = seen[b]
        else:
            off, ln = len(blob), len(b)
            blob += b
            seen[b] = (off, ln)
        # A run extends only when the ids are consecutive AND point at the same
        # bytes, which is what makes a clustered archive cheap to store.
        if entries and entries[-1][0] + entries[-1][3] == tid and entries[-1][1] == off \
                and entries[-1][2] == ln:
            entries[-1][3] += 1
        else:
            entries.append([tid, off, ln, 1])
    entries = [tuple(e) for e in entries]

    meta = gzip.compress(json.dumps(metadata, separators=(",", ":")).encode())

    # One root directory if it fits; otherwise split into leaves and point at them.
    root_bytes = gzip.compress(serialize_directory(entries))
    leaves = b""
    if len(root_bytes) > max_root_bytes:
        size = 1
        while True:
            size *= 2
            chunks = [entries[i:i + size] for i in range(0, len(entries), size)]
            leaves, root_entries = bytearray(), []
            for c in chunks:
                d = gzip.compress(serialize_directory(c))
                root_entries.append((c[0][0], len(leaves), len(d), 0))
                leaves += d
            root_bytes = gzip.compress(serialize_directory(root_entries))
            if len(root_bytes) <= max_root_bytes:
                leaves = bytes(leaves)
                break
            if size > len(entries):
                raise RuntimeError("cannot fit a root directory")

    root_off = HEADER_BYTES
    meta_off = root_off + len(root_bytes)
    leaf_off = meta_off + len(meta)
    data_off = leaf_off + len(leaves)
    h = Header(root_offset=root_off, root_length=len(root_bytes),
               metadata_offset=meta_off, metadata_length=len(meta),
               leaf_offset=leaf_off, leaf_length=len(leaves),
               data_offset=data_off, data_length=len(blob),
               addressed=sum(e[3] for e in entries), tile_entries=len(entries),
               tile_contents=len(seen), clustered=1, internal_compression=2,
               tile_compression=tile_compression, tile_type=1,
               min_zoom=zooms[0], max_zoom=zooms[1],
               min_lon=bounds[0], min_lat=bounds[1], max_lon=bounds[2], max_lat=bounds[3],
               center_zoom=center[2], center_lon=center[0], center_lat=center[1])
    with open(path, "wb") as f:
        f.write(h.pack())
        f.write(root_bytes)
        f.write(meta)
        f.write(leaves)
        f.write(blob)
    return h
