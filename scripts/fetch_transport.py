"""Every rail station TfL knows about, with its fare zone and lines.

'Convenient' for a London buyer means a station, and which station decides both
the commute and a large part of the price. The earlier pass took only the modes
TfL operates, which quietly deleted National Rail -- and south of the river that
is most of the network: Kidbrooke, Brentford and Peckham Rye all vanished. This
takes national-rail too.

The API needs no key but rejects urllib's default User-Agent with a 403.
"""
import json, pathlib, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "transport"
OUT.mkdir(parents=True, exist_ok=True)
MODES = "tube,dlr,overground,elizabeth-line,national-rail,tram"
API = f"https://api.tfl.gov.uk/StopPoint/Mode/{MODES}?page={{p}}"
UA = {"User-Agent": "housing-research/1.0"}


def get(url, tries=4):
    for a in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=180).read())
        except Exception as e:
            print(f"  retry {a+1} ({type(e).__name__})", flush=True)
            if a == tries - 1:
                raise
            time.sleep(8 * (a + 1))


def zone_of(sp):
    for a in sp.get("additionalProperties") or []:
        if a.get("key") == "Zone":
            return a.get("value")
    return None


def main():
    seen, page = {}, 1
    while True:
        d = get(API.format(p=page))
        sps = d.get("stopPoints", [])
        for sp in sps:
            # Only the parent station has a zone and the full line set; the
            # platform-level children repeat the same place many times over.
            if sp.get("stopType") not in ("NaptanMetroStation", "NaptanRailStation"):
                continue
            k = sp["id"]
            if k in seen:
                continue
            seen[k] = {"name": sp["commonName"].replace(" Underground Station", "")
                                               .replace(" Rail Station", "")
                                               .replace(" DLR Station", ""),
                       "lat": sp["lat"], "lon": sp["lon"],
                       "zone": zone_of(sp),
                       "lines": sorted({g["name"] for g in sp.get("lines", [])}),
                       "modes": sorted(sp.get("modes", []))}
        print(f"  page {page}: {len(sps)} stop points, {len(seen)} stations", flush=True)
        if not sps:
            break
        page += 1
    # national-rail returns the whole GB network. A fare zone is TfL's own marker
    # for "inside the London fares area", so it is also the London filter.
    outside = [k for k, v in seen.items() if not (v["zone"] or "").strip("NA ")]
    for k in outside:
        del seen[k]
    print(f"dropped {len(outside)} stations with no London fare zone")
    (OUT / "stations.json").write_text(json.dumps(seen, ensure_ascii=False))
    z = {}
    for v in seen.values():
        z[v["zone"]] = z.get(v["zone"], 0) + 1
    print(f"{len(seen)} stations -> stations.json")
    print("zones:", dict(sorted(z.items(), key=lambda kv: str(kv[0]))))


if __name__ == "__main__":
    main()
