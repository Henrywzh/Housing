"""Geocode every postcode in the London Price Paid extract.

Everything the map wants to say at neighbourhood level -- price within walking
distance of a station, which LSOA a sale sits in -- needs a coordinate per
postcode, and Price Paid ships none. The ONS Postcode Directory would do it but
is a ~1 GB download; postcodes.io serves the same ONS data over a bulk endpoint
that takes 100 postcodes per request, which is ~1,400 requests for all of London.

Resumable: results are checkpointed, so a stopped run picks up where it left off.
"""
import json, pathlib, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = RAW / "postcodes.csv"
API = "https://api.postcodes.io/postcodes"
CHUNK, WORKERS, CHECKPOINT = 100, 6, 200


def lookup(batch):
    body = json.dumps({"postcodes": batch}).encode()
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "housing-research/1.0"})
    for a in range(4):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except Exception:
            if a == 3:
                return []
            time.sleep(3 * (a + 1))
    rows = []
    for r in d.get("result", []):
        v = r.get("result")
        if not v:
            continue
        rows.append({"postcode": r["query"], "lat": v["latitude"], "lon": v["longitude"],
                     "lsoa": v.get("codes", {}).get("lsoa"),
                     "msoa": v.get("codes", {}).get("msoa"),
                     "lad": v.get("codes", {}).get("admin_district")})
    return rows


def main():
    ppd = pd.read_csv(RAW / "london_ppd.csv", usecols=["postcode"], dtype=str)
    want = sorted(ppd["postcode"].dropna().unique())
    have = set()
    if OUT.exists():
        have = set(pd.read_csv(OUT, usecols=["postcode"], dtype=str)["postcode"])
    todo = [p for p in want if p not in have]
    print(f"{len(want):,} postcodes, {len(have):,} done, {len(todo):,} to fetch", flush=True)
    if not todo:
        return
    batches = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    buf, done = [], 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for rows in ex.map(lookup, batches):
            buf += rows
            done += 1
            if done % CHECKPOINT == 0 or done == len(batches):
                pd.DataFrame(buf).to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
                buf = []
                print(f"  {done}/{len(batches)} batches", flush=True)
    n = len(pd.read_csv(OUT, usecols=["postcode"]))
    print(f"{n:,} postcodes geocoded ({n/len(want):.1%} of Price Paid; "
          f"the rest are terminated postcodes with no current coordinate)")


if __name__ == "__main__":
    main()
