"""Pull EPC floor areas for the transactions we actually analyse.

The bulk extract is 8.26GB and its presigned S3 link serves at ~50KB/s from
here, which is 45 hours -- not a route. The search endpoint is fast but returns
only addresses, no floor area; the certificate endpoint has the floor area but
serves one certificate per request. So we do this in three stages and only pay
for the certificates that correspond to a real transaction:

  1. search by council   -> certificate number + address + postcode  (~40 reqs/borough)
  2. match to Price Paid -> postcode + the numeric tokens of the address
  3. fetch certificates  -> only for matched pairs

Auth: bearer token from EPC_API_TOKEN or data/raw/epc/.token (gitignored).
Never passed as an argument, never printed.
"""
import argparse, json, os, pathlib, re, sys, time
import urllib.error, urllib.parse, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, EPC = ROOT / "data" / "raw", ROOT / "data" / "raw" / "epc"
API = "https://api.get-energy-performance-data.communities.gov.uk"

SECTORS = ["SW8 5", "SW11 8", "SW11 7", "SE10 0", "E16 1", "E16 2", "E14 9",
           "E14 3", "E14 5", "SE16 7", "SE1 6", "SE17 1", "HA9 0", "HA9 8",
           "W3 6", "NW10 7", "W12 7", "E15 1", "E15 2", "E20 1",
           # Outer-London schemes on the resale shortlist: Millbrook Park,
           # Colindale Gardens, The Brentford Project, Kidbrooke Village. Their
           # yields were computed on an assumed 540/750 sqft; these give the
           # measured area instead, which feeds straight into the service charge.
           "NW7 1", "NW9 4", "NW9 5", "TW8 8", "SE3 9"]
COUNCILS = ["Wandsworth", "Greenwich", "Newham", "Tower Hamlets", "Southwark",
            "Brent", "Ealing", "Hammersmith and Fulham"]


def token():
    t = os.environ.get("EPC_API_TOKEN")
    if not t and (EPC / ".token").exists():
        t = (EPC / ".token").read_text()
    if not t:
        raise SystemExit("No EPC token: set EPC_API_TOKEN or write data/raw/epc/.token")
    return t.strip()


def call(path, params, tok, tries=4):
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}",
                                               "Accept": "application/json"})
    for a in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("401 - the EPC token was rejected.")
            if e.code in (400, 404):
                return None
            if e.code in (429, 500, 502, 503) and a < tries - 1:
                time.sleep(6 * (a + 1)); continue
            raise
        except Exception:
            if a < tries - 1:
                time.sleep(4 * (a + 1)); continue
            raise
    return None


def sector_of(pc):
    pc = (pc or "").upper().strip()
    m = re.match(r"^(\S+)\s+(\d)", pc)
    return f"{m.group(1)} {m.group(2)}" if m else None


def stage1(tok):
    """Certificate index for every postcode that carries a transaction we analyse.

    Searching by postcode beats crawling whole boroughs: ~2,800 small requests
    instead of ~300 pages of 2MB, and nothing is fetched for postcodes with no
    transactions. (A postcode with no certificates returns 404; that is normal.)

    Checkpointed every 250 postcodes and resumable, because an hour of requests
    is too much to lose to one crash.
    """
    import threading
    import pandas as pd
    d = pd.read_csv(RAW / "london_ppd.csv", usecols=["postcode", "ppd_cat"], dtype=str)
    d = d[d["ppd_cat"] == "A"].dropna(subset=["postcode"])
    d = d[d["postcode"].map(sector_of).isin(SECTORS)]
    pcs = sorted(d["postcode"].unique())

    ckpt = EPC / "epc_index_partial.json"
    state = json.loads(ckpt.read_text()) if ckpt.exists() else {"done": [], "rows": []}
    seen = set(state["done"])
    keep = state["rows"]
    todo = [p for p in pcs if p not in seen]
    print(f"stage 1: {len(pcs):,} postcodes, {len(seen):,} already done, "
          f"{len(todo):,} to query", flush=True)

    lock, n = threading.Lock(), [0]

    def one(pc):
        r = call("/api/domestic/search", {"postcode": pc}, tok)
        rows = (r or {}).get("data") or []
        with lock:
            keep.extend(rows)
            seen.add(pc)
            n[0] += 1
            if n[0] % 250 == 0:
                ckpt.write_text(json.dumps({"done": sorted(seen), "rows": keep}))
                print(f"  {n[0]:,}/{len(todo):,} — {len(keep):,} certs", flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))

    out = EPC / "epc_index.json"
    out.write_text(json.dumps(keep))
    ckpt.write_text(json.dumps({"done": sorted(seen), "rows": keep}))
    print(f"stage 1: {len(keep):,} certificates -> {out}", flush=True)
    return keep


def nums(t):
    return "|".join(sorted(re.findall(r"\d+", str(t or "").upper())))


def stage2(index):
    """Match certificates to Price Paid rows on postcode + numeric address tokens."""
    import pandas as pd
    ppd = pd.read_csv(RAW / "london_ppd.csv", dtype=str, on_bad_lines="skip")
    ppd = ppd[ppd["ppd_cat"] == "A"].dropna(subset=["postcode"])
    ppd["sector"] = ppd["postcode"].map(sector_of)
    ppd = ppd[ppd["sector"].isin(SECTORS)]
    ppd["key"] = (ppd["postcode"].str.upper().str.replace(" ", "", regex=False) + "#"
                  + (ppd["saon"].fillna("") + " " + ppd["paon"].fillna("")).map(nums))
    idx = pd.DataFrame(index)
    addr = (idx["addressLine1"].fillna("") + " " + idx["addressLine2"].fillna("") + " "
            + idx["addressLine3"].fillna("") + " " + idx["addressLine4"].fillna(""))
    idx["key"] = (idx["postcode"].str.upper().str.replace(" ", "", regex=False) + "#"
                  + addr.map(nums))
    dup = {k for k, n in Counter(idx["key"]).items() if n > 1}
    idx2 = idx[~idx["key"].isin(dup)]
    need = sorted(set(ppd["key"]) & set(idx2["key"]))
    print(f"stage 2: {len(ppd):,} transactions, {len(idx):,} certificates "
          f"({len(dup):,} ambiguous keys), {len(need):,} matched keys")
    certs = idx2[idx2["key"].isin(need)]["certificateNumber"].tolist()
    (EPC / "epc_needed.json").write_text(json.dumps(certs))
    return certs


def stage3(certs, tok):
    """Full certificates, one request each, resumable.

    This is the expensive stage -- tens of thousands of requests -- so partial
    results are flushed to disk as they arrive and a rerun skips whatever is
    already held. Losing the process should cost minutes, not hours.
    """
    import threading
    path = EPC / "epc_certificates.json"
    out = json.loads(path.read_text()) if path.exists() else {}
    todo = [c for c in certs if c not in out]
    print(f"stage 3: {len(certs):,} certificates, {len(out):,} already held, "
          f"{len(todo):,} to fetch", flush=True)
    if not todo:
        return
    done, lock = [0], threading.Lock()
    FIELDS = ("uprn", "postcode", "address_line_1", "address_line_2",
              "address_line_3", "total_floor_area", "habitable_room_count",
              "property_type", "built_form", "transaction_type", "registration_date")

    def one(c):
        d = call("/api/certificate", {"certificate_number": c}, tok)
        r = (d or {}).get("data") or {}
        with lock:
            if r:
                out[c] = {k: r.get(k) for k in FIELDS}
            done[0] += 1
            if done[0] % 2000 == 0:
                path.write_text(json.dumps(out))
                print(f"  {done[0]:,}/{len(todo):,} — {len(out):,} held", flush=True)

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(one, todo))
    path.write_text(json.dumps(out))
    print(f"stage 3: {len(out):,} certificates with floor area -> {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, default=0, help="0 = all")
    a = ap.parse_args()
    tok = token()
    EPC.mkdir(parents=True, exist_ok=True)
    idxp, needp = EPC / "epc_index.json", EPC / "epc_needed.json"
    index = json.loads(idxp.read_text()) if (a.stage > 1 and idxp.exists()) else stage1(tok)
    certs = json.loads(needp.read_text()) if (a.stage > 2 and needp.exists()) else stage2(index)
    if a.stage in (0, 3):
        stage3(certs, tok)
