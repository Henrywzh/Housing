"""Cross property type with the new-build flag -- the cut UK HPI never publishes.

HPI ships a flat index and a new-build index, but never new-build *flats*. Price Paid
carries both flags on every transaction, so we rebuild that cell ourselves.

Medians, not a mix-adjusted index: a single tower completing a batch of studios moves a
borough's new-build median on its own. We use a trailing 12-month window to damp that,
and suppress any cell thinner than MIN_N rather than draw a line through noise.
"""
import json, pathlib, warnings
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

WINDOW = 12        # months, trailing
MIN_N = 20         # transactions in the window below which we publish nothing
COMPLETE = 0.5     # a month counts as registered once it reaches this share of reference volume

NAME2CODE = {}
base = json.loads((PROC / "map_data.json").read_text())
for code, rec in base["areas"].items():
    if code.startswith("E09"):
        NAME2CODE[rec["name"].upper()] = code
MONTHS = base["months"]
MIDX = {m: i for i, m in enumerate(MONTHS)}

df = pd.read_csv(ROOT / "data" / "raw" / "london_ppd.csv",
                 usecols=["date", "price", "ptype", "newbuild", "district", "ppd_cat"],
                 dtype={"price": "int64", "ptype": "category",
                        "newbuild": "category", "ppd_cat": "category"},
                 on_bad_lines="skip")
df = df[df["ppd_cat"] == "A"]                      # standard-price sales only
df["ym"] = df["date"].str.slice(0, 7)
df["code"] = df["district"].str.upper().map(NAME2CODE)
df = df.dropna(subset=["code", "ym"])
df["mi"] = df["ym"].map(MIDX)
df = df.dropna(subset=["mi"])
df["mi"] = df["mi"].astype(int)

def last_reliable(mask):
    """Last month index whose registrations look complete for THIS segment.

    New-build first registrations queue at HM Land Registry far longer than resales --
    London new-build flat registrations fall off a cliff ~10 months before the resale
    series does -- so each segment gets its own cutoff rather than one global one.
    Reference volume is the median of a 12-month window ending 15 months back, which is
    old enough to be fully registered and long enough to ride out the April-2025 stamp
    duty distortion.
    """
    tot = np.zeros(len(MONTHS))
    v = df.loc[mask, "mi"].value_counts()
    tot[v.index.to_numpy()] = v.to_numpy()
    end = int(df["mi"].max())
    ref = np.median(tot[end - 26:end - 14])
    if ref <= 0:
        return end
    ok = np.where(tot >= COMPLETE * ref)[0]
    return int(ok.max()) if len(ok) else end

SEGMENTS = {
    "flat_new":  (df.ptype == "F") & (df.newbuild == "Y"),
    "flat_old":  (df.ptype == "F") & (df.newbuild == "N"),
    "house_new": (df.ptype.isin(["D", "S", "T"])) & (df.newbuild == "Y"),
    "house_old": (df.ptype.isin(["D", "S", "T"])) & (df.newbuild == "N"),
}

def rolling(sub):
    """Trailing-WINDOW median and count per month index, or NaN when too thin."""
    med = np.full(len(MONTHS), np.nan)
    cnt = np.zeros(len(MONTHS))
    if not len(sub):
        return med, cnt
    s = sub.sort_values("mi")
    mi = s["mi"].to_numpy()
    px = s["price"].to_numpy()
    for i in range(len(MONTHS)):
        lo, hi = np.searchsorted(mi, [i - WINDOW + 1, i + 1])
        n = hi - lo
        cnt[i] = n
        if n >= MIN_N:
            med[i] = np.median(px[lo:hi])
    return med, cnt

CUTOFF = {seg: last_reliable(mask) for seg, mask in SEGMENTS.items()}
for seg, ci in CUTOFF.items():
    print(f"  cutoff {seg:10s} -> {MONTHS[ci]}")

def build(g):
    rec = {}
    store = {}
    for seg, mask in SEGMENTS.items():
        med, cnt = rolling(g[mask.loc[g.index]])
        med[CUTOFF[seg] + 1:] = np.nan          # drop the under-registered tail
        cnt[CUTOFF[seg] + 1:] = 0
        store[seg] = (med, cnt)
        rec[seg + "_price"] = [None if np.isnan(v) else int(round(v)) for v in med]
        rec[seg + "_n"] = [int(v) for v in cnt]
    fn, fo = store["flat_new"][0], store["flat_old"][0]
    prem = np.where(np.isnan(fn) | np.isnan(fo), np.nan, (fn / fo - 1) * 100)
    rec["flat_new_prem"] = [None if np.isnan(v) else round(float(v), 2) for v in prem]
    nn, no = store["flat_new"][1], store["flat_old"][1]
    tot = nn + no
    share = np.where(tot >= MIN_N, nn / np.maximum(tot, 1) * 100, np.nan)
    rec["flat_new_share"] = [None if np.isnan(v) else round(float(v), 2) for v in share]
    # year-on-year on the rolling medians
    for key in ("flat_new_price", "flat_old_price"):
        a = np.array([np.nan if v is None else v for v in rec[key]], dtype=float)
        yoy = np.full(len(a), np.nan)
        yoy[12:] = (a[12:] / a[:-12] - 1) * 100
        rec[key.replace("_price", "_yoy")] = [None if np.isnan(v) else round(float(v), 2) for v in yoy]
    return rec

out = {code: build(g) for code, g in df.groupby("code", observed=True)}
out["E12000007"] = build(df)          # Greater London, so the default panel is not empty

payload = {"months": MONTHS, "areas": out,
           "meta": {"window": WINDOW, "min_n": MIN_N,
                    "source": "HM Land Registry Price Paid Data, category A only",
                    "rows": int(len(df)), "last": df["ym"].max()}}
(PROC / "ppd_metrics.json").write_text(json.dumps(payload, separators=(",", ":")))

print(f"transactions (cat A) : {len(df):,}")
print(f"coverage             : {df.ym.min()} .. {df.ym.max()}")
print(f"boroughs             : {len(out)}")
print(f"ppd_metrics.json     : {(PROC/'ppd_metrics.json').stat().st_size/1e6:.2f} MB")
last = len(MONTHS) - 1
ok = [(base['areas'][c]['name'], out[c]['flat_new_price'][last], out[c]['flat_old_price'][last],
       out[c]['flat_new_prem'][last], out[c]['flat_new_n'][last])
      for c in out if out[c]['flat_new_price'][last]]
ok.sort(key=lambda r: -(r[1] or 0))
print(f"\n{MONTHS[last]} trailing-12m flat medians (top 8 by new-build median):")
print(f"{'borough':24s}{'new':>10s}{'existing':>10s}{'premium':>9s}{'n(new)':>8s}")
for r in ok[:8]:
    print(f"{r[0]:24s}{r[1]:>10,}{r[2]:>10,}{r[3]:>8.1f}%{r[4]:>8}")
