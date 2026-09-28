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


FAILED = []


def lookup(batch):
    """One batch of up to 100. A batch that never answers is recorded, not
    swallowed: the input is sorted, so a run of dropped batches is a run of
    neighbouring postcodes, and the first time that happened it deleted every
    postcode in SE3, SE4 and SE23-SE28 -- which is to say most of the new-build
    stock south of the river -- without anything in the output saying so.
    """
    body = json.dumps({"postcodes": batch}).encode()
    for a in range(6):
        try:
            req = urllib.request.Request(API, data=body, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "housing-research/1.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            break
        except Exception as e:
            if a == 5:
                FAILED.append((batch[0], batch[-1], type(e).__name__))
                return []
            time.sleep(4 * (a + 1))
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
    have = set(pd.read_csv(OUT, usecols=["postcode"], dtype=str)["postcode"])
    n, gap = len(have), [p for p in want if p not in have]
    print(f"{n:,} postcodes geocoded ({n/len(want):.1%} of Price Paid)")
    if FAILED:
        print(f"WARNING: {len(FAILED)} batches never answered; rerun to fill them:")
        for a, b, e in FAILED[:10]:
            print(f"  {a} .. {b}  ({e})")
    print(f"{len(gap):,} postcodes returned no result -- terminated codes with no "
          f"current coordinate. Rerun this script to retry; it only asks for what is "
          f"missing, so a stable count across two runs means the gap is real.")


if __name__ == "__main__":
    main()
