"""Postcode-sector level flat series for the regeneration submarkets.

A borough average is useless for judging Nine Elms: Wandsworth also contains Earlsfield
and Tooting. Sectors are the finest geography Price Paid supports without geocoding.
Same trailing-12m median and registration cutoff logic as the borough build.
"""
import json, pathlib, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
WINDOW, MIN_N, COMPLETE = 12, 20, 0.5

# Sector sets verified against the transaction record (street names + volumes), not a map.
SUBMARKETS = {
    "Nine Elms / Battersea": ["SW8 5", "SW11 7", "SW11 8"],
    "Vauxhall":              ["SW8 1", "SW8 2"],
    "Canada Water":          ["SE16 7"],
    "North Greenwich":       ["SE10 0"],
    "Canary Wharf":          ["E14 9", "E14 5"],
    "Stratford":             ["E15 1", "E20 1"],
    "Canning Town":          ["E16 1"],
    "Wembley Park":          ["HA9 0", "HA9 8"],
    "White City":            ["W12 7"],
    "North Acton":           ["W3 6", "NW10 7"],
    # added after the record showed these carry more new-build flats than half the list above
    "City Island / Leamouth": ["E14 0"],
    "Royal Arsenal":          ["SE18 6"],
    "Elephant Park":          ["SE17 1"],
    "Kidbrooke Village":      ["SE3 9"],
    "Royal Albert Wharf":     ["E16 2"],
}

# Sector volumes are an order of magnitude thinner than a borough's, so the London-wide
# new-build cutoff (2025-09) is still far too generous here: SE10 0 logged 133 new-build
# flats in 2024 and 8 in 2025. Report on a month that is unambiguously fully registered.
REPORT = "2024-12"

MONTHS = json.loads((PROC / "map_data.json").read_text())["months"]
MIDX = {m: i for i, m in enumerate(MONTHS)}

df = pd.read_csv(ROOT / "data/raw/london_ppd.csv",
                 usecols=["date", "price", "postcode", "ptype", "newbuild", "ppd_cat", "street"],
                 on_bad_lines="skip")
df = df[(df.ppd_cat == "A") & (df.ptype == "F") & df.postcode.notna()]
df["sector"] = df.postcode.str.replace(r"^(.*?)\s+(\d).*$", r"\1 \2", regex=True)
df["mi"] = df.date.str.slice(0, 7).map(MIDX)
df = df.dropna(subset=["mi"]); df["mi"] = df["mi"].astype(int)

end = int(df.mi.max())
def cutoff(sub):
    tot = np.zeros(len(MONTHS))
    v = sub.mi.value_counts(); tot[v.index.to_numpy()] = v.to_numpy()
    ref = np.median(tot[end - 26:end - 14])
    if ref <= 0: return end
    ok = np.where(tot >= COMPLETE * ref)[0]
    return int(ok.max()) if len(ok) else end

CUT = {"Y": cutoff(df[df.newbuild == "Y"]), "N": cutoff(df[df.newbuild == "N"])}

def roll(sub, cut):
    med = np.full(len(MONTHS), np.nan); cnt = np.zeros(len(MONTHS))
    if not len(sub): return med, cnt
    s = sub.sort_values("mi"); mi = s.mi.to_numpy(); px = s.price.to_numpy()
    for i in range(min(cut + 1, len(MONTHS))):
        lo, hi = np.searchsorted(mi, [i - WINDOW + 1, i + 1])
        cnt[i] = hi - lo
        if hi - lo >= MIN_N: med[i] = np.median(px[lo:hi])
    return med, cnt

out = {}
for name, sectors in SUBMARKETS.items():
    sub = df[df.sector.isin(sectors)]
    rec = {"sectors": sectors}
    for flag, key in (("Y", "new"), ("N", "old")):
        med, cnt = roll(sub[sub.newbuild == flag], CUT[flag])
        rec[key] = [None if np.isnan(v) else int(round(v)) for v in med]
        rec[key + "_n"] = [int(v) for v in cnt]
    rec["total_new"] = int((sub.newbuild == "Y").sum())
    rec["first_new"] = MONTHS[int(sub[sub.newbuild == "Y"].mi.min())] if (sub.newbuild == "Y").any() else None
    rec["top_streets"] = sub[sub.newbuild == "Y"].street.value_counts().head(4).to_dict()
    out[name] = rec

(PROC / "submarkets.json").write_text(json.dumps(
    {"months": MONTHS, "submarkets": out,
     "meta": {"window": WINDOW, "min_n": MIN_N,
              "cutoff_new": MONTHS[CUT["Y"]], "cutoff_old": MONTHS[CUT["N"]]}},
    separators=(",", ":")))

print(f"cutoff  new={MONTHS[CUT['Y']]}  existing={MONTHS[CUT['N']]}\n")
i = MIDX[REPORT]
print(f"{MONTHS[i]} 滚动12个月公寓中位价\n")
print(f"{'submarket':24s}{'sectors':22s}{'新建':>10s}{'二手':>10s}{'溢价':>8s}{'新建n':>7s}{'首次':>9s}")
for name, r in sorted(out.items(), key=lambda kv: -(kv[1]["new"][i] or 0)):
    n, o = r["new"][i], r["old"][i]
    prem = f"{(n/o-1)*100:>7.1f}%" if n and o else "      —"
    print(f"{name:24s}{','.join(r['sectors']):22s}"
          f"{(f'{n:,}' if n else '—'):>10s}{(f'{o:,}' if o else '—'):>10s}{prem}"
          f"{r['new_n'][i]:>7}{str(r['first_new']):>9s}")
