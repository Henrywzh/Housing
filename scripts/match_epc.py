"""Join EPC floor areas onto Price Paid transactions to get £ per square foot.

Price Paid has no floor area and EPC has no price, so neither alone can say
whether a new-build premium is a premium for space or a premium for being new.
The join is on address, which is the awkward part: Land Registry splits an
address into PAON (building) and SAON (flat), EPC keeps it as free text, and
neither is normalised. We match on postcode plus the multiset of numeric
tokens, which is stable against "Flat 12" vs "Apartment 12" vs "12" and against
word order, then keep only unambiguous one-to-one matches.

Input: the EPC bulk download (domestic). Point EPC_DIR at the unzipped folder;
the script reads every certificates.csv beneath it.

Run:  python3 scripts/match_epc.py [path-to-unzipped-epc-folder]
"""
import pathlib
import re
import sys
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
EPC_DIR = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "raw" / "epc"
SQM_TO_SQFT = 10.7639

EPC_COLS = ["ADDRESS1", "ADDRESS2", "ADDRESS3", "POSTCODE", "TOTAL_FLOOR_AREA",
            "NUMBER_HABITABLE_ROOMS", "PROPERTY_TYPE", "BUILT_FORM",
            "LODGEMENT_DATE", "UPRN"]


def norm_pc(s):
    return s.astype(str).str.upper().str.replace(r"\s+", "", regex=True)


def nums(text):
    """Numeric tokens in an address, as a stable key. 'Flat 12, 5 Ponton Rd' -> '5|12'."""
    return "|".join(sorted(re.findall(r"\d+", str(text or "").upper())))


def load_epc():
    files = sorted(EPC_DIR.rglob("certificates.csv"))
    if not files:
        files = sorted(EPC_DIR.rglob("*.csv"))
    if not files:
        raise SystemExit(
            f"No EPC csv found under {EPC_DIR}.\n"
            "Download the domestic bulk extract from\n"
            "  https://get-energy-performance-data.communities.gov.uk/\n"
            "(it needs a GOV.UK One Login), unzip it, and pass the folder path."
        )
    print(f"reading {len(files)} EPC file(s)")
    parts = []
    for f in files:
        d = pd.read_csv(f, usecols=lambda c: c in EPC_COLS, low_memory=False)
        parts.append(d)
    e = pd.concat(parts, ignore_index=True)
    e["pc"] = norm_pc(e["POSTCODE"])
    e["area_sqm"] = pd.to_numeric(e["TOTAL_FLOOR_AREA"], errors="coerce")
    e = e[(e["area_sqm"] > 15) & (e["area_sqm"] < 600)]
    e["addr"] = (e["ADDRESS1"].fillna("") + " " + e["ADDRESS2"].fillna("")).str.strip()
    e["key"] = e["pc"] + "#" + e["addr"].map(nums)
    e["LODGEMENT_DATE"] = pd.to_datetime(e["LODGEMENT_DATE"], errors="coerce")
    # one row per address: the most recent certificate
    e = e.sort_values("LODGEMENT_DATE").drop_duplicates("key", keep="last")
    return e


def main():
    ppd = pd.read_csv(ROOT / "data/raw/london_ppd.csv", dtype=str, on_bad_lines="skip")
    ppd["price"] = pd.to_numeric(ppd["price"], errors="coerce")
    ppd["date"] = pd.to_datetime(ppd["date"], errors="coerce")
    ppd = ppd.dropna(subset=["price", "date", "postcode"])
    ppd = ppd[(ppd["ppd_cat"] == "A") & (ppd["price"] > 1000)]
    ppd["pc"] = norm_pc(ppd["postcode"])
    ppd["key"] = ppd["pc"] + "#" + (ppd["saon"].fillna("") + " " + ppd["paon"].fillna("")).map(nums)

    e = load_epc()
    # a key that appears twice on either side cannot be resolved by address alone
    dup_e = {k for k, n in Counter(e["key"]).items() if n > 1}
    amb = ppd.groupby("key")["postcode"].nunique()
    m = ppd.merge(e[~e["key"].isin(dup_e)][["key", "area_sqm", "NUMBER_HABITABLE_ROOMS",
                                            "PROPERTY_TYPE", "UPRN"]],
                  on="key", how="left")
    m["area_sqft"] = m["area_sqm"] * SQM_TO_SQFT
    m["psf"] = m["price"] / m["area_sqft"]
    m.loc[(m["psf"] < 100) | (m["psf"] > 5000), "psf"] = np.nan

    hit = m["psf"].notna()
    print(f"PPD rows           : {len(ppd):,}")
    print(f"EPC rows usable    : {len(e):,}  ({len(dup_e):,} ambiguous keys dropped)")
    print(f"matched with £/sqft: {hit.sum():,}  ({hit.mean()*100:.1f}%)")
    by_year = m[hit].groupby(m.loc[hit, "date"].dt.year)["psf"].agg(["size", "median"])
    print(by_year.tail(8).to_string(float_format=lambda v: f"{v:,.0f}"))
    m.loc[hit, ["date", "price", "postcode", "paon", "saon", "street", "district",
                "ptype", "newbuild", "area_sqm", "area_sqft", "psf",
                "NUMBER_HABITABLE_ROOMS"]].to_parquet(OUT / "ppd_epc_psf.parquet", index=False)
    print(f"wrote {OUT / 'ppd_epc_psf.parquet'}")


if __name__ == "__main__":
    main()
