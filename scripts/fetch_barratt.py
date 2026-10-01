"""Barratt London: every development on sale or coming soon, and its listed homes.

Barratt publishes two sitemaps that between them say what is being sold:
one of developments, one of developments marked coming soon. Neither says
where a development is -- the URLs carry an id and a name, not a region --
so each page is read once for the coordinates it embeds
(`data-area-lat-lng`) and kept only if it falls on this map.

From the page text come the headline ("1, 2 and 3 bedroom homes, £350,000
to £570,000") and the homes currently released, each as "Plot 273 Magnolia
Apartments 1 Bed Apartment From £350,000 Floor 1". Those are asking prices
on the day of the fetch, not achieved prices; Price Paid will say what they
went for a few months after completion.

robots.txt allows the sitemaps and development pages (it disallows search
results, which this does not touch). One request every 1.2 s, each page cached
under data/raw/barratt/, so a re-run fetches nothing it already has unless
--refresh is given.
"""
import argparse, html, json, pathlib, re, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "barratt"
OUT = ROOT / "data" / "raw" / "barratt.json"
BASE = "https://www.barratthomes.co.uk"
UA = "Mozilla/5.0 (housing-research; personal use)"
# The map's own bounds (zone14.html maxBounds).
BOX = (-0.46, 51.31, 0.20, 51.70)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def sitemap(name):
    xml = get(f"{BASE}/sitemaps/sitemap-barratt-{name}.xml")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def text_of(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


PLOT = re.compile(
    r"Plot (\w+) (.{2,60}?) (\d) Bed (Apartment|Flat|Studio|House|Townhouse|Duplex|Penthouse|Maisonette)"
    r"(?: [A-Za-z]+)* From £([\d,]+)(?: Floor (\w+))?")
STUDIO = re.compile(r"Plot (\w+) (.{2,60}?) Studio(?: Apartment| Flat)? From £([\d,]+)(?: Floor (\w+))?")


def parse(url, page, coming):
    m = (re.search(r'data-area-lat-lng="([-\d.]+),([-\d.]+)"', page)
         # A few pages have no map widget, only the schema.org geo block.
         or re.search(r'"latitude": *"([-\d.]+)".{0,80}?"longitude": *"([-\d.]+)"', page, re.S))
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    title = re.search(r"<title>([^<|]+)", page)
    name = html.unescape(title.group(1)).split(",")[0].strip() if title else url
    t = text_of(page)
    head = re.search(r"((?:Studio|\d)(?:[, ]+(?:(?:and|&) )?\d)*[ -]bedroom (?:homes|apartments|flats|houses))"
                     r"(?: £([\d,]+) to £([\d,]+)| From £([\d,]+))?", t)
    addr = re.search(re.escape(name) + r" ([^£]{8,120}?, [A-Z]{1,2}\d[\dA-Z]? \d[A-Z]{2})", t)
    plots, seen = [], set()
    for p in PLOT.finditer(t):
        if p.group(1) in seen:
            continue
        seen.add(p.group(1))
        plots.append({"plot": p.group(1), "bld": p.group(2).strip(), "beds": int(p.group(3)),
                      "type": p.group(4), "price": int(p.group(5).replace(",", "")),
                      "floor": p.group(6)})
    for p in STUDIO.finditer(t):
        if p.group(1) in seen:
            continue
        seen.add(p.group(1))
        plots.append({"plot": p.group(1), "bld": p.group(2).strip(), "beds": 0, "type": "Studio",
                      "price": int(p.group(3).replace(",", "")), "floor": p.group(4)})
    ready = re.search(r"[Rr]eady to move in(?: from)? ((?:early |late |spring |summer |autumn |winter )?\d{4})", t)
    lo = hi = None
    if head:
        if head.group(2):
            lo, hi = int(head.group(2).replace(",", "")), int(head.group(3).replace(",", ""))
        elif head.group(4):
            lo = int(head.group(4).replace(",", ""))
    if plots:
        lo = min([lo] + [p["price"] for p in plots] if lo else [p["price"] for p in plots])
    return {"name": name, "url": url, "lat": round(lat, 5), "lon": round(lon, 5),
            # The name can sit in front twice ("Eastman Village Eastman Village Sales ...").
            "address": addr.group(1).removeprefix(name).strip() if addr else None,
            "status": "coming" if coming else ("selling" if plots else "register"),
            "summary": head.group(1) if head else None, "from": lo, "to": hi,
            "ready": ready.group(1) if ready else None,
            "plots": sorted(plots, key=lambda p: p["price"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch cached pages")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    coming = set(sitemap("comingsoon"))
    urls = list(dict.fromkeys(sitemap("developments") + sorted(coming)))
    print(f"{len(urls)} developments in the sitemaps ({len(coming)} coming soon)")
    out = []
    for i, url in enumerate(urls, 1):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        f = RAW / f"{slug}.html"
        if a.refresh or not f.exists():
            try:
                f.write_text(get(url))
            except Exception as e:  # a withdrawn page is not worth stopping for
                print(f"  ! {slug}: {e}")
                continue
            time.sleep(1.2)
        d = parse(url, f.read_text(), url in coming)
        if d and BOX[0] <= d["lon"] <= BOX[2] and BOX[1] <= d["lat"] <= BOX[3]:
            out.append(d)
        if i % 25 == 0:
            print(f"  {i}/{len(urls)}  {len(out)} in London so far")
    OUT.write_text(json.dumps({"fetched": time.strftime("%Y-%m-%d"), "developments": out},
                              ensure_ascii=False, indent=1))
    print(f"\n{len(out)} on the map -> {OUT.relative_to(ROOT)}")
    for d in sorted(out, key=lambda d: (d["status"], d["from"] or 9e9)):
        print(f"  {d['status']:8s} {d['name'][:32]:32s} {d['summary'] or '':32.32s} "
              f"from £{d['from'] or 0:>9,}  {len(d['plots']):3d} homes listed")


if __name__ == "__main__":
    main()
