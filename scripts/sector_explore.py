"""Find which postcode sectors actually carry the Nine Elms / Battersea new-build stock.

We do not hard-code a guess at the sector list: we let the transactions say where the
new-build flats are, then sanity-check the answer against the street names.
"""
import pandas as pd, warnings, pathlib
warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

df = pd.read_csv(ROOT / "data/raw/london_ppd.csv",
                 usecols=["date", "price", "postcode", "ptype", "newbuild", "street", "district"],
                 on_bad_lines="skip")
df["ym"] = df["date"].str.slice(0, 7)
df = df[(df.ptype == "F") & df.postcode.notna()]
df["sector"] = df.postcode.str.replace(r"^(.*?)\s+(\d).*$", r"\1 \2", regex=True)

nine = df[df.district.isin(["WANDSWORTH", "LAMBETH"]) & (df.newbuild == "Y") & (df.ym >= "2013-01")]
print("Wandsworth + Lambeth new-build FLATS since 2013, by sector:\n")
g = nine.groupby("sector").agg(n=("price", "size"), median=("price", "median"),
                               first=("ym", "min"), last=("ym", "max"))
g = g[g.n >= 40].sort_values("n", ascending=False)
print(f"{'sector':9s}{'n':>6s}{'median':>11s}  {'first':8s}{'last':8s} top streets")
for s, r in g.head(12).iterrows():
    tops = nine[nine.sector == s].street.value_counts().head(3)
    streets = ", ".join(f"{k.title()}({v})" for k, v in tops.items())
    print(f"{s:9s}{r.n:>6.0f}{r['median']:>11,.0f}  {r['first']:8s}{r['last']:8s} {streets}")

print("\n\nStreet-level check -- the named Nine Elms / Battersea Power Station addresses:")
pat = ("PONTON ROAD|NINE ELMS|EMBASSY GARDENS|VIADUCT GARDENS|PROSPECT WAY|SOPWITH WAY|"
       "CIRCUS ROAD WEST|CIRCUS ROAD EAST|SWITCH HOUSE|BATTERSEA PARK ROAD|KIRTLING STREET|"
       "PAVILION ROAD|ELECTRIC BOULEVARD")
hit = df[df.street.fillna("").str.contains(pat, regex=True)]
print(hit.groupby("sector").agg(n=("price", "size"), new=("newbuild", lambda s: (s == "Y").sum()),
                                median=("price", "median"), first=("ym", "min"), last=("ym", "max"))
        .query("n >= 20").sort_values("n", ascending=False).to_string())
