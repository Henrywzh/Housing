"""Stream HM Land Registry Price Paid Data year by year, keeping only Greater London.

PPD is the only source that carries property type AND new-build flag AND full postcode
on the same row, so it is what lets us split flats from houses and new-build from
existing stock -- the UK HPI publishes those two cuts separately but never crossed.
"""
import csv, io, subprocess, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "london_ppd.csv"
BASE = "http://prod2.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com"
YEARS = range(1995, 2027)
COLS = ["date", "price", "postcode", "ptype", "newbuild", "tenure",
        "paon", "saon", "street", "locality", "district", "ppd_cat"]

done = set()
if OUT.exists():
    with OUT.open() as f:
        for row in csv.DictReader(f):
            done.add(row["date"][:4])
    done.discard(max(done)) if done else None      # redo the last (possibly partial) year

mode = "a" if done else "w"
with OUT.open(mode, newline="") as fh:
    w = csv.writer(fh)
    if mode == "w":
        w.writerow(COLS)
    for y in YEARS:
        if str(y) in done:
            print(f"{y}: cached", flush=True)
            continue
        p = subprocess.Popen(["curl", "-sL", "--retry", "3", "--max-time", "1800",
                              f"{BASE}/pp-{y}.csv"], stdout=subprocess.PIPE)
        n = kept = 0
        for r in csv.reader(io.TextIOWrapper(p.stdout, encoding="utf-8", errors="replace")):
            n += 1
            if len(r) < 15 or r[13] != "GREATER LONDON":
                continue
            kept += 1
            w.writerow([r[2][:10], r[1], r[3], r[4], r[5], r[6],
                        r[7], r[8], r[9], r[10], r[12], r[14]])
        p.wait()
        print(f"{y}: {n:,} rows -> {kept:,} London", flush=True)
        fh.flush()
print("DONE", OUT, f"{OUT.stat().st_size/1e6:.0f} MB")
