"""London flat developers: what each is selling, or about to, and where.

Barratt London has its own fetcher (fetch_barratt.py) because its pages list
individual plots. The rest are read here with one generic parser, because no
two of them publish the same structure but all of them say the same four things
somewhere on a development page: its name, a postcode, "from £X" and a bedroom
range ("Studio, 1, 2 and 3 bedroom apartments").

Each developer's sitemap gives the development pages; a per-developer pattern
keeps the development pages and drops the news, guides and plot pages. Each page
is fetched once (one a second, cached under data/raw/developers/<dev>/) and read
for:

  postcode   the first one on the page that is a London postcode. A postcode
             printed on more than a quarter of one developer's pages is its
             head office or a sales suite, not a site, and is skipped.
  coords     an explicit latitude/longitude on the page if there is one inside
             London; otherwise the postcode's centroid from data/raw/postcodes.csv,
             which only holds London postcodes -- so that lookup is also the
             filter that keeps this to London.
  price      the lowest "from £X" of £100k or more.
  status     sold out / coming soon / selling, from the page's own wording. A
             developer's sitemap keeps sold-out schemes for years, so this is
             what keeps the map to what can actually be bought.

It is a heuristic reader of marketing pages, so every row keeps its URL and the
map says the numbers are asking prices read off a page on a given day.

Every developer here allows these pages in robots.txt.
"""
import argparse, collections, csv, html, json, pathlib, re, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "developers"
OUT = ROOT / "data" / "raw" / "developers.json"
UA = "Mozilla/5.0 (housing-research; personal use)"
BOX = (-0.46, 51.31, 0.20, 51.70)

# name, sitemaps, pattern a development page's URL matches.
# Two big London flat builders are not here, and why:
#   Ballymore      its site is a corporate portfolio -- schemes finished in 1995
#                  and ones still in planning, side by side, no prices, mostly no
#                  postcode. Its live sales run on a separate site per scheme.
#   Taylor Wimpey  its development pages are drawn entirely by script; the HTML
#                  carries a title and nothing else.
# Developers whose page titles are SEO copy ("New Build Flats & Apartments in
# Barnet, ...") are named from their URL instead.
SLUG_NAMES = {"fairview", "londonsquare", "bellway"}
DEVS = {
    "berkeley": ("Berkeley", ["https://www.berkeleygroup.co.uk/sitemaps/sitemap-developments"],
                 r"/developments/london/[^/]+/[^/]+$"),
    "taylorwimpey": ("Taylor Wimpey", ["https://www.taylorwimpey.co.uk/developments.xml"],
                     r"/new-homes/[^/]*london[^/]*/[^/]+$"),
    "bellway": ("Bellway", ["https://www.bellway.co.uk/developments-sitemap.xml"],
                r"/new-homes/[^/]*london[^/]*/[^/]+/?$"),
    "londonsquare": ("London Square", ["https://londonsquare.co.uk/sitemap"],
                     r"/developments/(?!map$)[^/]+$"),
    "mountanvil": ("Mount Anvil", ["https://www.mountanvil.com/sitemap.xml"],
                   r"/find-your-home/[^/]+/?$"),
    "galliard": ("Galliard", ["https://www.galliardhomes.com/sitemap.xml"],
                 r"galliardhomes\.com/(?!guides|news|property|about-us|media-centre|careers|chinese|galliard-homes|"
                 r"reports-and-accounts|latest-offers|investor-information|contact|privacy|terms|cookie)[a-z0-9-]+/?$"),
    "fairview": ("Fairview", ["https://www.fairview.co.uk/sitemap.xml/sitemap/SilverStripe-CMS-Model-SiteTree/1"],
                 r"/find-your-new-home/[^/]+/?$"),
    "redrow": ("Redrow", ["https://www.redrow.co.uk/sitemaps/sitemap-redrow-developments.xml",
                          "https://www.redrow.co.uk/sitemaps/sitemap-redrow-comingsoon.xml"],
               r"/new-homes/[^/]+/?$"),
}

PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?) ?(\d[A-Z]{2})\b")
PRICE = re.compile(r"(?:[Ff]rom|[Pp]rices? (?:start )?from|[Ss]tarting (?:at|from))[:\s]*£\s?([\d,.]+)\s?(m|M|k|K)?")
BEDS = re.compile(r"((?:[Ss]tudios?|\d)(?:(?:, | and | & | to |-)(?:[Ss]tudios?|\d))*[ -]bed(?:room)?s?"
                  r"(?: (?:homes|apartments|flats|houses|residences|properties))?)")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def text_of(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", page, flags=re.S)
    t = re.sub(r"<(nav|footer|header)\b.*?</\1>", " ", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


def money(num, unit):
    v = float(num.replace(",", ""))
    if unit in ("m", "M"):
        v *= 1e6
    elif unit in ("k", "K"):
        v *= 1e3
    return int(v)


# Where a page stops describing itself and starts advertising its siblings --
# whose postcodes and prices would otherwise be read as this one's.
PROMO = re.compile(r"These May Be of Interest|You may also like|Other developments|Similar developments"
                   r"|More developments|Explore our other|Nearby developments|Related developments", re.I)


def own_part(t):
    m = PROMO.search(t)
    return t[:m.start()] if m else t


def status_of(t):
    low = t.lower()
    if re.search(r"\bsold out\b|\bfully sold\b|\ball (?:homes )?(?:are )?sold\b|\bnow (?:all )?sold\b"
                 r"|\bdevelopment completed\b", low) \
            and not re.search(r"\bavailable now\b|\bhomes available\b", low):
        return "sold"
    if re.search(r"\bcoming soon\b|\blaunching (?:soon|in|this)\b|\bregister (?:your )?interest\b"
                 r"|\bfuture release\b|\bpre-launch\b", low) and not PRICE.search(t):
        return "coming"
    return "selling"


class London(dict):
    """London postcodes -> (lat, lon), from the local file, falling back to
    postcodes.io for the ones too new to be in it -- a scheme still being sold is
    exactly where Royal Mail has just issued postcodes. Lookups are cached."""
    CACHE = RAW / "postcodes_io.json"

    def __init__(self, path):
        super().__init__()
        with open(path) as f:
            for r in csv.DictReader(f):
                if r["lat"] and r["lon"]:
                    self[r["postcode"]] = (float(r["lat"]), float(r["lon"]))
        self.io = json.loads(self.CACHE.read_text()) if self.CACHE.exists() else {}

    def __contains__(self, pc):
        return self.get(pc) is not None

    def get(self, pc, default=None):
        if dict.__contains__(self, pc):
            return dict.__getitem__(self, pc)
        if pc not in self.io:
            try:
                r = json.loads(get("https://api.postcodes.io/postcodes/" + pc.replace(" ", "%20")))["result"]
                self.io[pc] = [r["latitude"], r["longitude"]] if r.get("region") == "London" else None
            except Exception:
                self.io[pc] = None      # unknown or terminated
            self.CACHE.parent.mkdir(parents=True, exist_ok=True)
            self.CACHE.write_text(json.dumps(self.io))
        return tuple(self.io[pc]) if self.io[pc] else default

    def __getitem__(self, pc):
        v = self.get(pc)
        if v is None:
            raise KeyError(pc)
        return v


def parse(url, page, london, boiler):
    t = own_part(text_of(page))
    # The title often carries the status too: "250 City Road | Homes All Sold | Islington".
    title = re.search(r"<title>([^<]+)", page)
    if title and re.search(r"all sold|sold out", title.group(1), re.I):
        t = "sold out " + t
    name = html.unescape(title.group(1)).strip() if title else url.rstrip("/").rsplit("/", 1)[-1]
    name = re.split(r"\s+[|–‧:]\s+|\s*\|\s*|, ", name)[0].strip()
    # The page's own structured address first; then the first London postcode in
    # its text that is not the developer's office.
    js = [p.replace("  ", " ").strip().upper() for p in re.findall(r'"postalCode"\s*:\s*"([^"]+)"', page)]
    pcs = js + [f"{a} {b}" for a, b in PC.findall(t)]
    pc = next((p for p in pcs if p in london and p not in boiler), None)
    lat = lon = None
    m = re.search(r'"latitude"\s*:\s*"?(-?\d+\.\d+)"?.{0,120}?"longitude"\s*:\s*"?(-?\d+\.\d+)', page, re.S) \
        or re.search(r'data-lat(?:itude)?="(-?\d+\.\d+)"[^>]*data-(?:lng|lon|longitude)="(-?\d+\.\d+)"', page) \
        or re.search(r'"lat"\s*:\s*"?(5\d\.\d+)"?\s*,\s*"(?:lng|lon)"\s*:\s*"?(-?0\.\d+|0)', page) \
        or re.search(r'google\.com/maps/embed[^"]*?[?&;]q=(5\d\.\d+),(-?\d\.\d+)', page)   # Bellway
    if m:
        la, lo = float(m.group(1)), float(m.group(2))
        if BOX[0] <= lo <= BOX[2] and BOX[1] <= la <= BOX[3]:
            lat, lon = la, lo
    if lat is None and pc:
        lat, lon = london[pc]
    prices = [money(n, u) for n, u in PRICE.findall(t)]
    prices = [p for p in prices if 100_000 <= p <= 50_000_000]
    beds = BEDS.search(t)
    return {"name": name, "url": url, "postcode": pc,
            "lat": round(lat, 5) if lat else None, "lon": round(lon, 5) if lon else None,
            "from": min(prices) if prices else None,
            "summary": beds.group(1) if beds else None, "status": status_of(t)}


# Developers whose pages give no address at all, only an index that labels each
# scheme with an area and a postcode district ("Royal Docks, E16 Queens Cross").
# Such a scheme is placed at the district's centroid and flagged approximate:
# good to a kilometre or two, not to a street.
DISTRICT_INDEX = {"mountanvil": "https://www.mountanvil.com/find-your-home/"}


def districts(key, names):
    url = DISTRICT_INDEX.get(key)
    if not url:
        return {}
    f = RAW / key / "_index.html"
    if not f.exists():
        f.write_text(get(url))
    t = text_of(f.read_text())
    out = {}
    for n in names:
        m = re.search(r"([A-Z]{1,2}\d[A-Z\d]?) " + re.escape(n) + r"\b", t)
        if m:
            out[n] = m.group(1)
    return out


def district_centroid(london, dist):
    pts = [v for k, v in dict.items(london) if k.split(" ")[0] == dist]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def dev_urls(key):
    _, maps, pat = DEVS[key]
    out = []
    for sm in maps:
        try:
            xml = get(sm)
        except Exception as e:
            print(f"  ! {key} sitemap: {e}")
            continue
        out += [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", xml)]
    rx = re.compile(pat)
    return list(dict.fromkeys(u for u in out if rx.search(u.split("?")[0])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help="developer keys (default: all)")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    london = London(ROOT / "data" / "raw" / "postcodes.csv")
    prev = json.loads(OUT.read_text())["developments"] if OUT.exists() else []
    keys = a.only or list(DEVS)
    rows = [r for r in prev if r["dev"] not in keys and r["dev"] in DEVS]
    # Sold-out schemes are not for sale, but they say who built what stands there,
    # which is what a resale scheme's "developer" is read from.
    past = [r for r in (json.loads(OUT.read_text()).get("past", []) if OUT.exists() else [])
            if r["dev"] not in keys and r["dev"] in DEVS]
    for key in keys:
        label = DEVS[key][0]
        urls = dev_urls(key)
        d = RAW / key
        d.mkdir(parents=True, exist_ok=True)
        pages = {}
        for u in urls:
            f = d / (re.sub(r"[^a-z0-9-]+", "_", u.lower().split("//", 1)[-1])[-120:] + ".html")
            if a.refresh or not f.exists():
                try:
                    f.write_text(get(u))
                except Exception as e:
                    print(f"  ! {key} {u}: {e}")
                    continue
                time.sleep(1.0)
            pages[u] = f.read_text()
        # Postcodes on a quarter of a developer's pages are its own addresses.
        seen = collections.Counter()
        for p in pages.values():
            seen.update({f"{a} {b}" for a, b in PC.findall(text_of(p))})
        boiler = {pc for pc, n in seen.items() if len(pages) >= 4 and n > len(pages) / 4}
        kept = sold = far = 0
        parsed = {u: parse(u, p, london, boiler) for u, p in pages.items()}
        dist = districts(key, [r["name"] for r in parsed.values()
                               if r["lat"] is None and r["status"] != "sold"])
        for u, r in parsed.items():
            if r["lat"] is None and r["name"] in dist:
                c = district_centroid(london, dist[r["name"]])
                if c:
                    r["lat"], r["lon"] = round(c[0], 5), round(c[1], 5)
                    r["postcode"], r["approx"] = dist[r["name"]], True
            if r["lat"] is None:
                far += 1
                continue
            r["dev"] = key
            if r["status"] == "sold":
                sold += 1
                if key in SLUG_NAMES:
                    r["name"] = u.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
                past.append(r)
                continue
            if key in SLUG_NAMES:
                r["name"] = u.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            rows.append(r)
            kept += 1
        print(f"{label:14s} {len(urls):4d} pages  {kept:3d} on the map  {sold:3d} sold out  "
              f"{far:3d} not in London / no location" + (f"  (office postcodes: {', '.join(sorted(boiler))})" if boiler else ""))
    rows.sort(key=lambda r: (r["dev"], r["name"]))
    OUT.write_text(json.dumps({"fetched": time.strftime("%Y-%m-%d"),
                               "developers": {k: v[0] for k, v in DEVS.items()},
                               "developments": rows, "past": past}, ensure_ascii=False, indent=1))
    print(f"\n{len(rows)} developments -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
