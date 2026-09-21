"""£ per square foot: what the new-build premium actually is.

Every premium figure in this project so far compares whole flats, so it cannot
separate "this costs more because it is bigger" from "this costs more because
it is new". New flats are usually smaller than the older stock around them, so
the per-sqft premium should come out materially below the per-flat one. That
gap is the number worth having.

Inputs: data/raw/epc/epc_certificates.json (from fetch_epc.py) and the Price
Paid extract. Matching is postcode + the multiset of numeric tokens in the
address, one-to-one only.
"""
import json, pathlib, re, sys, warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from submarkets import SUBMARKET_MSOA  # noqa: F401  (kept for symmetry)

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
SQFT = 10.7639
SECTOR_TO_MKT = {
    "SW8 5": "Nine Elms", "SW11 8": "Battersea Power Station", "SW11 7": "Battersea North",
    "SE10 0": "North Greenwich", "E16 1": "Canning Town", "E16 2": "Royal Docks",
    "E14 9": "Isle of Dogs West", "E14 3": "Isle of Dogs East", "E14 5": "Canary Wharf",
    "SE16 7": "Canada Water", "SE1 6": "Elephant & Castle", "SE17 1": "Elephant & Castle",
    "HA9 0": "Wembley Park", "HA9 8": "Wembley Park", "W3 6": "North Acton",
    "NW10 7": "North Acton", "W12 7": "White City", "E15 1": "Stratford",
    "E15 2": "Stratford", "E20 1": "Stratford",
}


def nums(t):
    return "|".join(sorted(re.findall(r"\d+", str(t or "").upper())))


def sector(pc):
    m = re.match(r"^(\S+)\s+(\d)", str(pc or "").upper().strip())
    return f"{m.group(1)} {m.group(2)}" if m else None


def main():
    cert_path = RAW / "epc" / "epc_certificates.json"
    if not cert_path.exists():
        raise SystemExit(f"{cert_path} not found — run scripts/fetch_epc.py first")
    certs = json.loads(cert_path.read_text())
    e = pd.DataFrame(certs.values())
    e["area_sqm"] = pd.to_numeric(e["total_floor_area"], errors="coerce")
    e = e[(e["area_sqm"] > 15) & (e["area_sqm"] < 600)]
    addr = (e["address_line_1"].fillna("") + " " + e["address_line_2"].fillna("")
            + " " + e["address_line_3"].fillna(""))
    e["key"] = (e["postcode"].str.upper().str.replace(" ", "", regex=False) + "#"
                + addr.map(nums))
    e["rooms"] = pd.to_numeric(e["habitable_room_count"], errors="coerce")
    dup = {k for k, n in Counter(e["key"]).items() if n > 1}
    e = e[~e["key"].isin(dup)].drop_duplicates("key")

    p = pd.read_csv(RAW / "london_ppd.csv", dtype=str, on_bad_lines="skip")
    p["price"] = pd.to_numeric(p["price"], errors="coerce")
    p["date"] = pd.to_datetime(p["date"], errors="coerce")
    p = p.dropna(subset=["price", "date", "postcode"])
    p = p[(p["ppd_cat"] == "A") & (p["price"] > 1000) & (p["ptype"] == "F")]
    p["sector"] = p["postcode"].map(sector)
    p = p[p["sector"].isin(SECTOR_TO_MKT)]
    p["market"] = p["sector"].map(SECTOR_TO_MKT)
    p["key"] = (p["postcode"].str.upper().str.replace(" ", "", regex=False) + "#"
                + (p["saon"].fillna("") + " " + p["paon"].fillna("")).map(nums))
    p["year"] = p["date"].dt.year
    p["build"] = np.where(p["newbuild"] == "Y", "new", "existing")

    m = p.merge(e[["key", "area_sqm", "rooms"]], on="key", how="left")
    m["sqft"] = m["area_sqm"] * SQFT
    m["psf"] = m["price"] / m["sqft"]
    m.loc[(m["psf"] < 100) | (m["psf"] > 5000), "psf"] = np.nan

    # Shared-ownership sales are recorded by Land Registry at the price paid for
    # the SHARE, not the value of the flat, and in the regeneration areas they
    # are numerous enough to drag a median into the wrong mode: Nine Elms
    # one-beds split cleanly into 17 sales at £226-326/sqft on Sleaford Street
    # and 13 at £999-1,766/sqft around Embassy Gardens. A share is typically
    # 25-40%, so anything under half the local upper quartile is not a
    # full-market price. The cut is per market and year so it follows the
    # local level rather than imposing one national threshold.
    ref = m.groupby(["market", "year"])["psf"].transform(lambda s: s.quantile(.75))
    m["shared_ownership_likely"] = m["psf"] < ref * 0.5
    n_so = int(m["shared_ownership_likely"].sum())
    by_mkt = (m[m["shared_ownership_likely"]].groupby("market").size()
              .sort_values(ascending=False))
    m.loc[m["shared_ownership_likely"], "psf"] = np.nan
    hit = m["psf"].notna()
    print(f"dropped as part-share sales     : {n_so:,}")
    if len(by_mkt):
        print("  " + ", ".join(f"{k} {v}" for k, v in by_mkt.head(8).items()))

    print(f"flat transactions in sectors : {len(m):,}")
    print(f"matched with a floor area    : {hit.sum():,}  ({hit.mean()*100:.1f}%)")
    print("match rate by build type     :")
    print((m.groupby("build")["psf"].apply(lambda s: s.notna().mean() * 100)
             .round(1).to_string()))
    m[hit].to_parquet(OUT / "ppd_epc_psf.parquet", index=False)

    r = m[hit & m["year"].between(2022, 2026)]
    g = r.groupby(["market", "build"]).agg(n=("psf", "size"), psf=("psf", "median"),
                                           sqm=("area_sqm", "median"),
                                           price=("price", "median"))
    w = g.unstack("build")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    for c in ("n_new", "n_existing", "psf_new", "psf_existing",
              "sqm_new", "sqm_existing", "price_new", "price_existing"):
        if c not in w:
            w[c] = np.nan
    # suppress each side on its own sample -- a thin resale count is no reason
    # to hide a new-build figure built on hundreds of sales
    w.loc[w["n_new"] < 20, ["psf_new", "sqm_new", "price_new"]] = np.nan
    w.loc[w["n_existing"] < 20, ["psf_existing", "sqm_existing", "price_existing"]] = np.nan
    w["溢价_每套%"] = (w["price_new"] / w["price_existing"] - 1) * 100
    w["溢价_每平尺%"] = (w["psf_new"] / w["psf_existing"] - 1) * 100
    w["面积差%"] = (w["sqm_new"] / w["sqm_existing"] - 1) * 100
    print("\n=== 2022–2026 · 新建 vs 二手（样本<20 不出数）===")
    print(w[["n_new", "n_existing", "psf_new", "psf_existing", "sqm_new", "sqm_existing",
             "溢价_每套%", "溢价_每平尺%", "面积差%"]]
          .sort_values("psf_existing", ascending=False)
          .to_string(float_format=lambda v: f"{v:,.0f}", na_rep="—"))
    w.to_csv(OUT / "psf_submarket.csv")

    yr = m[hit].groupby(["market", "year"])["psf"].agg(["size", "median"]).reset_index()
    yr.loc[yr["size"] < 15, "median"] = np.nan
    piv = yr.pivot(index="market", columns="year", values="median")
    keep = [y for y in piv.columns if 2015 <= y <= 2026]
    print("\n=== 二手+新建合计 · 每平尺中位价（样本<15 不出数）===")
    print(piv[keep].to_string(float_format=lambda v: f"{v:,.0f}", na_rep="—"))
    piv.to_csv(OUT / "psf_submarket_year.csv")


if __name__ == "__main__":
    main()
