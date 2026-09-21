"""Pull EPC domestic certificates from the MHCLG Energy Certificate Data API.

Auth: a bearer token, read from the environment or a gitignored file. It is
never printed, never passed on the command line (where it would land in shell
history and `ps`), and never written to any output.

  export EPC_API_TOKEN=...        # or
  echo '...' > data/raw/epc/.token   # already in .gitignore

Two modes, because the API offers both:

  --council "Tower Hamlets" "Newham" ...
      Paged search by local authority. This is the efficient route when you
      want whole boroughs: a few dozen requests instead of one per postcode.

  --postcodes
      Only the postcodes that actually appear in the Price Paid extract for
      the submarket sectors. Far fewer certificates, and every one of them is
      attached to a transaction we care about.

The full bulk zip (GET /api/files/domestic/csv) is ~2.9GB and is not used here;
neither mode needs it.
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EPC = RAW / "epc"
API = "https://api.get-energy-performance-data.communities.gov.uk"
SECTORS = ["SW8 5", "SW11 8", "SW11 7", "SE10 0", "E16 1", "E16 2", "E14 9",
           "E14 3", "E14 5", "SE16 7", "SE1 6", "SE17 1", "HA9 0", "HA9 8",
           "W3 6", "NW10 7", "W12 7", "E15 1", "E15 2", "E20 1"]


def token():
    t = os.environ.get("EPC_API_TOKEN")
    if not t:
        f = EPC / ".token"
        if f.exists():
            t = f.read_text().strip()
    if not t:
        raise SystemExit(
            "No EPC token. Set EPC_API_TOKEN, or write it to data/raw/epc/.token\n"
            "(that path is gitignored). Do not pass it as a command-line argument."
        )
    return t.strip()


def get(path, params, tok, tries=4):
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/json"})
    for a in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("401 from the EPC API - the token was rejected.")
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503) and a < tries - 1:
                time.sleep(6 * (a + 1)); continue
            raise
        except Exception:
            if a < tries - 1:
                time.sleep(4 * (a + 1)); continue
            raise
    return None


def paged(path, base, tok, label):
    """Walk the API's pagination, returning every row."""
    rows, page = [], 1
    while True:
        p = dict(base); p["page"] = 5000; p["current_page"] = page
        d = get(path, p, tok)
        if not d:
            break
        batch = d.get("data") or []
        rows.extend(batch)
        pg = d.get("pagination") or {}
        total = pg.get("totalPages") or pg.get("total_pages")
        print(f"  {label} page {page}"
              + (f"/{total}" if total else "") + f" -> {len(rows):,} rows", flush=True)
        if not batch or (total and page >= total):
            break
        page += 1
        if page > 400:
            print(f"  {label}: stopping at 400 pages", flush=True)
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--council", nargs="*", default=None)
    ap.add_argument("--postcodes", action="store_true")
    a = ap.parse_args()
    tok = token()
    EPC.mkdir(parents=True, exist_ok=True)
    out, rows = EPC / "epc_domestic.json", []

    if a.postcodes:
        import pandas as pd
        ppd = pd.read_csv(RAW / "london_ppd.csv", usecols=["postcode"], dtype=str)
        pc = ppd["postcode"].dropna().unique()
        sec = {s.replace(" ", "") for s in SECTORS}
        want = sorted({p for p in pc
                       if p.replace(" ", "")[:len(p.split()[0]) + 1] in sec} if False else
                      {p for p in pc if any(p.startswith(s.split()[0] + " " + s.split()[1])
                                            for s in SECTORS)})
        print(f"{len(want):,} postcodes in the submarket sectors")
        for i, p in enumerate(want, 1):
            d = get("/api/domestic/search", {"postcode": p}, tok)
            if d:
                rows.extend(d.get("data") or [])
            if i % 200 == 0:
                print(f"  {i}/{len(want)} -> {len(rows):,} certs", flush=True)
    else:
        councils = a.council or ["Tower Hamlets", "Newham", "Wandsworth", "Greenwich",
                                 "Southwark", "Brent", "Ealing", "Hammersmith and Fulham",
                                 "Lambeth", "Barnet"]
        for c in councils:
            print(f"council: {c}", flush=True)
            rows.extend(paged("/api/domestic/search", {"council[]": c}, tok, c))

    out.write_text(json.dumps(rows))
    print(f"\n{len(rows):,} certificates -> {out}  ({out.stat().st_size/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
