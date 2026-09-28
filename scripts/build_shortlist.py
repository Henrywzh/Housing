"""Shortlist of second-hand flats in recently built schemes, priced on measured area.

The five-year plan pays the new-build premium once and gives it back once. A
flat that is already three to seven years old has had the premium taken out of
it by someone else, still has most of its warranty and none of its dilapidation,
and is the side of that trade worth being on -- so this looks only at resales in
schemes completed since 2019.

What this adds to a Rightmove search is the cost side. An asking rent is not a
yield: the service charge on these schemes runs from GBP 2.9 to GBP 6.2 a square
foot, which on a one-bed is the difference between keeping GBP 1,700 a year and
keeping nothing much. Service charge is charged by area, so the area has to be
real -- an assumed 540 sqft carries straight into the net yield as an error, and
EPC gives the surveyed figure instead.

  gross           rent x 12 / price
  net             less service charge and ground rent
  net_after_mgmt  less 12% of rent for letting fees and a void

Ground rent is a peppercorn on leases granted after 30 Jun 2022 (Leasehold
Reform (Ground Rent) Act 2022), which is why two flats in one scheme can differ.

Listings and scheme-level figures are hand-collected snapshots in data/manual/,
dated in the file. Everything else is computed from Price Paid, EPC and police
data by the rest of the pipeline.
"""
import json, pathlib, statistics
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, MAN, OUT = ROOT / "data" / "raw", ROOT / "data" / "manual", ROOT / "data" / "processed"
MGMT_VOID = 0.12
FALLBACK_SQFT = {1: 540, 2: 750}
MIN_EPC = 8
MIN_GAP = 8


# EPC records floor area but not bedrooms, so bedrooms have to be inferred from
# area. The bands come from the 15,594 London flats in our own EPC match that DO
# carry a habitable-room count: rooms = bedrooms + 1, and the room classes cross
# at about 600 and 820 square feet.
#
#   rooms  n      p25   median  p75
#   2      4,726  463   517     581     -> 1 bed
#   3      8,041  624   732     840     -> 2 bed
#   4      1,769  797   947   1,119     -> 3 bed
BEDS_SQFT = {1: (0, 600), 2: (600, 820), 3: (820, 10_000)}


def dev_area(psf, streets, beds):
    """Median measured area for a bedroom count within one scheme."""
    lo, hi = BEDS_SQFT[beds]
    d = psf[psf["street"].isin(streets) & psf["sqft"].between(lo, hi, inclusive="left")]
    if len(d) < MIN_EPC:
        return None, len(d)
    return float(d["sqft"].median()), len(d)


def gap(ppd, psf, streets):
    """New-build against second-hand inside one scheme, 2023 onwards.

    Per flat AND per square foot, because the two answer different questions. The
    developer's last phase is usually not the same product as the resales coming
    back to market -- often smaller, sometimes larger -- so a per-flat gap mixes
    the newness premium with a change of mix. Per square foot isolates the
    premium, and only the sales with an EPC area can be measured that way.
    """
    d = ppd[ppd["street"].isin(streets) & (ppd["date"] >= "2023-01-01") & (ppd["ptype"] == "F")]
    n, o = d[d["newbuild"] == "Y"]["price"], d[d["newbuild"] == "N"]["price"]
    g = {"n_new": len(n), "n_resale": len(o)}
    if len(n) >= MIN_GAP and len(o) >= MIN_GAP:
        g |= {"new_median": float(n.median()), "resale_median": float(o.median()),
              "gap_pct": round((o.median() / n.median() - 1) * 100, 1)}
    f = psf[psf["street"].isin(streets) & (psf["date"] >= "2023-01-01")]
    fn, fo = f[f["newbuild"] == "Y"]["psf"], f[f["newbuild"] == "N"]["psf"]
    g |= {"n_new_psf": len(fn), "n_resale_psf": len(fo)}
    if len(fn) >= MIN_GAP and len(fo) >= MIN_GAP:
        g |= {"new_psf": round(float(fn.median())), "resale_psf": round(float(fo.median())),
              "gap_psf_pct": round((fo.median() / fn.median() - 1) * 100, 1)}
    return g


def main():
    man = json.loads((MAN / "shortlist_developments.json").read_text())
    devs = man["developments"]
    lst = pd.read_csv(MAN / "shortlist_listings.csv")
    psf = pd.read_parquet(OUT / "ppd_epc_psf.parquet")
    psf = psf[~psf["shared_ownership_likely"]]
    ppd = pd.read_csv(RAW / "london_ppd.csv",
                      usecols=["date", "price", "postcode", "ptype", "newbuild", "street"],
                      dtype={"postcode": str})
    ppd["street"] = ppd["street"].str.upper()
    st = pd.read_csv(OUT / "stations.csv")

    meta = {}
    for name, d in devs.items():
        streets = [s.upper() for s in d["streets"]]
        row = {k: d[k] for k in ("area", "ll", "station", "sc_psf", "sc_src", "gr", "gr_src",
                                 "search")}
        row["rent_median"] = {b: statistics.median(v) for b, v in d["rents"].items()}
        row["rent_n"] = {b: len(v) for b, v in d["rents"].items()}
        row["sqft"], row["sqft_n"] = {}, {}
        for b in (1, 2):
            a, n = dev_area(psf, streets, b)
            row["sqft"][b], row["sqft_n"][b] = a, n
        row["new_vs_resale"] = gap(ppd, psf, streets)
        s = st[st["name"] == d["station"]]
        if len(s) == 1:
            s = s.iloc[0]
            row["catchment"] = {k: (None if pd.isna(s[k]) else
                                    (float(s[k]) if isinstance(s[k], (int, float, np.floating))
                                     else s[k]))
                                for k in ("zone", "n_lines", "median_price", "p25_price",
                                          "n_sales", "psf", "home_per_1000",
                                          "resident_per_1000", "n_shops", "n_parks",
                                          "n_food", "n_health_edu", "premium_grocer")}
        else:
            raise SystemExit(f"{name}: station {d['station']!r} matched {len(s)} rows")
        meta[name] = row

    rows = []
    for r in lst.itertuples():
        d, m = devs[r.development], meta[r.development]
        beds = int(r.beds)
        listed = None if pd.isna(r.listed_sqft) else float(r.listed_sqft)
        measured = m["sqft"][beds]
        size = listed or measured or FALLBACK_SQFT[beds]
        src = "listing" if listed else ("EPC scheme median" if measured else "assumed")
        rent = m["rent_median"][str(beds)]
        sc = round(d["sc_psf"] * size)
        gr = 0 if r.lease_post_jun2022 else d["gr"]
        gross = rent * 12 / r.asking_price
        net = (rent * 12 - sc - gr) / r.asking_price
        net2 = (rent * 12 * (1 - MGMT_VOID) - sc - gr) / r.asking_price
        rows.append({"id": r.id, "url": f"https://www.rightmove.co.uk/properties/{r.id}",
                     "development": r.development, "building": r.building, "beds": beds,
                     "price": r.asking_price, "sqft": round(size), "sqft_src": src,
                     "psf_asking": round(r.asking_price / size),
                     "built": r.first_newbuild_sale, "rent_pcm": rent,
                     "rent_n": m["rent_n"][str(beds)], "service_charge": sc, "ground_rent": gr,
                     "gross_yield": round(gross * 100, 2), "net_yield": round(net * 100, 2),
                     "net_after_mgmt": round(net2 * 100, 2)})
    out = pd.DataFrame(rows).sort_values("net_after_mgmt", ascending=False)
    out.to_csv(OUT / "shortlist.csv", index=False)
    (OUT / "shortlist.json").write_text(json.dumps(
        {"meta": {"retrieved": man["retrieved"], "mgmt_void": MGMT_VOID},
         "developments": meta, "listings": out.to_dict("records")},
        ensure_ascii=False, indent=1, default=float))

    for n, m in meta.items():
        g = m["new_vs_resale"]
        a1 = f"{m['sqft'][1]:.0f}" if m["sqft"][1] else "--"
        a2 = f"{m['sqft'][2]:.0f}" if m["sqft"][2] else "--"
        pf = (f"{g['gap_psf_pct']:+.0f}% psf" if "gap_psf_pct" in g
              else f"psf n/a ({g['n_new_psf']}/{g['n_resale_psf']})")
        pc = (f"{g['gap_pct']:+.0f}% flat" if "gap_pct" in g
              else f"flat n/a ({g['n_new']}/{g['n_resale']})")
        print(f"{n:22s} 1b {a1} sqft (n={m['sqft_n'][1]:3d})  2b {a2} sqft "
              f"(n={m['sqft_n'][2]:3d})  new->resale {pc}, {pf}  "
              f"home-crime {m['catchment']['home_per_1000']:.0f}")
    print()
    print(out[["development", "beds", "price", "sqft", "sqft_src", "psf_asking", "rent_pcm",
               "service_charge", "gross_yield", "net_after_mgmt"]].to_string(index=False))


if __name__ == "__main__":
    main()
