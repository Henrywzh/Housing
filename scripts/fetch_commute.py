"""Door-to-door time to Green Park, arriving by 08:40, by TfL's planner.

Asked for every Zone 1-4 station and every developer scheme. The station
answers are what the map's 方便 score is now made of; a resale scheme takes its
nearest station's answer plus the walk to it.

TfL's Journey Planner is the same engine as the TfL app: it walks from the
coordinates to a stop, takes tube, Elizabeth line, Overground, DLR, National
Rail or bus, and walks out of Green Park. Asked to arrive by 08:40 on a weekday, it
answers with the latest few journeys that make it; the shortest is kept, with
its route and number of changes.

Green Park is the reference because it is three lines (Jubilee, Piccadilly,
Victoria) at the middle of the West End -- one number that stands in for "how
far is this from central London" better than straight-line distance does.

The date is a fixed ordinary Thursday so a re-run compares like with like. Two
requests at a time, backing off on 429; answers are cached in
data/raw/commute_gp_0840.json keyed by coordinates, so a re-run only asks about schemes
it has not seen.
"""
import json, pathlib, time, urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "data"
CACHE = ROOT / "data" / "raw" / "commute_gp_0840.json"
TO = "940GZZLUGPK"                        # Green Park Underground Station
DATE, TIME = "20261008", "0840"           # a Thursday; be at Green Park by 08:40
MODES = "tube,dlr,overground,elizabeth-line,national-rail,bus,walking"


def plan(lat, lon):
    q = urllib.parse.urlencode({"date": DATE, "time": TIME, "timeIs": "Arriving",
                                "journeyPreference": "LeastTime", "mode": MODES})
    url = f"https://api.tfl.gov.uk/Journey/JourneyResults/{lat},{lon}/to/{TO}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "housing-research"})
    for wait in (0, 10, 30, 60, 120):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:              # only "too many requests" is worth waiting out
                raise
    else:
        raise RuntimeError("still rate-limited after backing off")
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
    devs = json.loads((WEB / "devs.json").read_text())["developments"]
    stations = [{"name": s["n"], "lat": s["y"], "lon": s["x"], "dev": "station"}
                for s in json.loads((WEB / "stations.json").read_text())]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [d for d in devs + stations if f"{d['lat']:.5f},{d['lon']:.5f}" not in cache]
    # Each answer takes the planner several seconds, so two are asked at once;
    # an anonymous caller that asks faster gets 429s, which are waited out.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(2) as ex:
        futs = {ex.submit(plan, d["lat"], d["lon"]): d for d in todo}
        for n, f in enumerate(as_completed(futs), 1):
            d = futs[f]
            try:
                cache[f"{d['lat']:.5f},{d['lon']:.5f}"] = f.result()
            except Exception as e:
                print(f"  ! {d['name']}: {e}")
            if n % 25 == 0 or n == len(todo):
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
                print(f"  {n}/{len(todo)}", flush=True)
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
