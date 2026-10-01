"""Door-to-door time from every developer scheme to Green Park, by TfL's planner.

TfL's Journey Planner is the same engine as the TfL app: it walks from the
coordinates to a stop, takes tube, Elizabeth line, Overground, DLR, National
Rail or bus, and walks out of Green Park. Asked for a weekday departure at 08:30,
it answers with the few fastest journeys; the fastest is kept, with its route
and its number of changes.

Green Park is the reference because it is three lines (Jubilee, Piccadilly,
Victoria) at the middle of the West End -- one number that stands in for "how
far is this from central London" better than straight-line distance does.

The date is a fixed ordinary Thursday so a re-run compares like with like. One
request every 1.5 s (the anonymous API allows far more); answers are cached in
data/raw/commute.json keyed by coordinates, so a re-run only asks about schemes
it has not seen.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "data" / "devs.json"
CACHE = ROOT / "data" / "raw" / "commute.json"
TO = "940GZZLUGPK"                        # Green Park Underground Station
DATE, TIME = "20261008", "0830"           # a Thursday, morning peak
MODES = "tube,dlr,overground,elizabeth-line,national-rail,bus,walking"


def plan(lat, lon):
    q = urllib.parse.urlencode({"date": DATE, "time": TIME, "timeIs": "Departing",
                                "journeyPreference": "LeastTime", "mode": MODES})
    url = f"https://api.tfl.gov.uk/Journey/JourneyResults/{lat},{lon}/to/{TO}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "housing-research"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    js = d.get("journeys") or []
    if not js:
        return None
    j = min(js, key=lambda j: j["duration"])
    ride = [l for l in j["legs"] if l["mode"]["id"] != "walking"]
    return {"min": j["duration"], "changes": max(len(ride) - 1, 0),
            "walk": sum(l["duration"] for l in j["legs"] if l["mode"]["id"] == "walking"),
            "route": " → ".join(
                (l["routeOptions"][0]["name"] if l.get("routeOptions") and l["routeOptions"][0].get("name")
                 else l["mode"]["name"]) for l in ride)}


def main():
    devs = json.loads(WEB.read_text())["developments"]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    for d in devs:
        k = f"{d['lat']:.5f},{d['lon']:.5f}"
        if k in cache:
            continue
        try:
            cache[k] = plan(d["lat"], d["lon"])
        except Exception as e:
            print(f"  ! {d['name']}: {e}")
            continue
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        time.sleep(1.5)
    rows = []
    for d in devs:
        c = cache.get(f"{d['lat']:.5f},{d['lon']:.5f}")
        rows.append((c["min"] if c else 999, d, c))
    for m, d, c in sorted(rows, key=lambda r: r[0]):
        print(f"{m:4d} min  {d['dev'][:10]:10s} {d['name'][:30]:30s} "
              f"{'£%dk' % (d['from'] // 1000) if d.get('from') else '    -':>7s}  "
              f"{(c or {}).get('changes', '-')} 换乘  {(c or {}).get('route', '')}")


if __name__ == "__main__":
    main()
