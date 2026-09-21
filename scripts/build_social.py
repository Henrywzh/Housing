"""Crime, ethnicity and earnings for every London borough and each submarket.

Geography note: the census and income data are published on MSOAs, which nest
exactly inside boroughs, so borough figures here are summed from MSOAs rather
than pulled separately -- that keeps the borough and submarket numbers on the
same base. Earnings (ASHE) are survey estimates published only at borough
level; there is no sub-borough equivalent, so the submarket table carries
MSOA household income instead and says so.
"""
import json
import pathlib
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from submarkets import SUBMARKET_MSOA, MSOA_TO_SUBMARKET

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SOC = RAW / "social"
OUT = ROOT / "data" / "processed"

names = pd.read_csv(RAW / "msoa_names21.csv")[
    ["msoa21cd", "msoa21hclnm", "localauthorityname"]]
names.columns = ["msoa", "msoa_name", "la_name"]

# ---------------------------------------------------------------- ethnicity
eth = pd.read_csv(SOC / "eth_msoa.csv")
eth.columns = ["msoa_nm", "msoa", "group", "n"]
eth["group"] = eth["group"].str.split(":").str[0].str.split(",").str[0].str.strip()
w = eth.pivot_table(index="msoa", columns="group", values="n", aggfunc="sum")
w = w.rename(columns={"Total": "pop", "White": "white", "Asian": "asian",
                      "Black": "black", "Mixed or Multiple ethnic groups": "mixed",
                      "Other ethnic group": "other"})
w = w.reset_index().merge(names, on="msoa", how="inner")
w = w[w["msoa"].str.startswith("E02")]

# The five-group summary hides the distinctions that actually differ between
# neighbourhoods -- "Asian 44%" is Bangladeshi in Tower Hamlets and Indian in
# Harrow -- so keep the 19 detailed groups alongside it. Note where the groups
# sit: Arab is under "Other ethnic group", NOT under Asian; the census has no
# Middle East category at all, and Turkish/Iranian respondents mostly appear
# under "White: Other White".
det = pd.read_csv(SOC / "eth_msoa_detail.csv")
det.columns = ["msoa", "group", "n"]
det = det[~det["group"].str.startswith("Total")]
det["group"] = det["group"].str.split(": ").str[-1]
DETAIL = det

# ------------------------------------------------------------------- income
def inc_sheet(sheet, col):
    d = pd.read_excel(SOC / "msoa_income_fye2023.xlsx", sheet_name=sheet, header=3)
    d = d[["MSOA code", d.columns[6]]]
    d.columns = ["msoa", col]
    return d

inc = inc_sheet("Total annual income", "hh_income_total")
inc = inc.merge(inc_sheet("Net income after housing costs", "hh_income_ahc"), on="msoa")
w = w.merge(inc, on="msoa", how="left")

# -------------------------------------------------------------------- crime
# Crime is fetched per polygon, and we only fetch the 25 submarket MSOAs -- so
# MSOA crime rolls up to submarkets ONLY. Borough crime comes from its own
# borough-polygon query; rolling up the 25 MSOAs would silently undercount a
# borough by the ~95% of it we never asked about.
crime_msoa = OUT / "crime_msoa.csv"
if crime_msoa.exists():
    w = w.merge(pd.read_csv(crime_msoa), on="msoa", how="left")
else:
    print("crime_msoa.csv not built yet -- submarket crime omitted")

# ------------------------------------------------------- aggregate upwards
ETHCOLS = ["white", "asian", "black", "mixed", "other"]
CRIMECOLS = [c for c in w.columns if c.startswith("crime_")]

def roll(df, keys):
    g = df.groupby(keys)
    cc = [c for c in CRIMECOLS if c in df.columns]
    out = g[["pop"] + ETHCOLS + cc].sum()
    # income is a household-level model estimate, so weight it by population
    for c in ("hh_income_total", "hh_income_ahc"):
        out[c] = g.apply(lambda d: (d[c] * d["pop"]).sum() / d["pop"].sum()
                         if d[c].notna().any() else float("nan"))
    out["n_msoa"] = g.size()
    return out.reset_index()

boroughs = roll(w.drop(columns=CRIMECOLS), ["la_name"]) if CRIMECOLS else roll(w, ["la_name"])
w["submarket"] = w["msoa"].map(MSOA_TO_SUBMARKET)
subs = roll(w[w["submarket"].notna()], ["submarket"])
subs["msoa_names"] = subs["submarket"].map(
    lambda s: ", ".join(w.loc[w.submarket == s, "msoa_name"]))
subs["borough"] = subs["submarket"].map(
    lambda s: w.loc[w.submarket == s, "la_name"].mode().iat[0])

# borough crime, from the borough-polygon query, joined on the LAD code the
# boundary file carries (the census rollup above is keyed on name)
crime_lad = OUT / "crime_borough.csv"
if crime_lad.exists():
    lad = json.loads((RAW / "london_lad_bgc.geojson").read_text())
    code2name = {f["properties"]["LAD24CD"]: f["properties"]["LAD24NM"]
                 for f in lad["features"]}
    cl = pd.read_csv(crime_lad)
    cl["la_name"] = cl["code"].map(code2name)
    unmatched = cl.loc[cl["la_name"].isna(), "code"].tolist()
    if unmatched:
        print("WARN borough crime rows with no boundary name:", unmatched)
    boroughs = boroughs.merge(
        cl.drop(columns=["code"]).dropna(subset=["la_name"]), on="la_name", how="left")
    LADCRIME = [c for c in cl.columns if c.startswith("crime_")]
    for c in LADCRIME:
        boroughs[c + "_k"] = boroughs[c] / boroughs["pop"] * 1000
else:
    print("crime_borough.csv not built yet -- borough crime omitted")

for df in (boroughs, subs):
    for c in ETHCOLS:
        df[c + "_pct"] = df[c] / df["pop"] * 100
    for c in CRIMECOLS:
        if c in df.columns:
            df[c + "_k"] = df[c] / df["pop"] * 1000

# ----------------------------------------------------------------- earnings
def detail_mix(msoas, top=6):
    d = DETAIL[DETAIL["msoa"].isin(msoas)].groupby("group")["n"].sum()
    tot = d.sum()
    return [{"g": g, "pct": round(v / tot * 100, 1)}
            for g, v in d.nlargest(top).items()] if tot else []

m_by_la = w.groupby("la_name")["msoa"].apply(list).to_dict()
boroughs["eth_detail"] = boroughs["la_name"].map(
    lambda k: json.dumps(detail_mix(m_by_la.get(k, [])), ensure_ascii=False))
subs["eth_detail"] = subs["submarket"].map(
    lambda k: json.dumps(detail_mix(SUBMARKET_MSOA[k]), ensure_ascii=False))

ashe = pd.read_csv(SOC / "ashe_resident.csv")
ashe.columns = ["year", "la_name", "la_code", "pay_resident"]
latest = ashe[ashe["year"] == ashe["year"].max()][["la_name", "la_code", "pay_resident"]]
wp = pd.read_csv(SOC / "ashe_workplace.csv")
wp.columns = ["year", "la_name", "la_code", "pay_workplace"]
boroughs = boroughs.merge(latest, on="la_name", how="left") \
                   .merge(wp[["la_name", "pay_workplace"]], on="la_name", how="left")

boroughs.to_csv(OUT / "social_borough.csv", index=False)
subs.to_csv(OUT / "social_submarket.csv", index=False)
ashe.to_csv(OUT / "ashe_history.csv", index=False)

print(f"boroughs   : {len(boroughs)}   population {boroughs['pop'].sum():,.0f}")
print(f"submarkets : {len(subs)}   population {subs['pop'].sum():,.0f}")
print(f"crime cols : {CRIMECOLS or 'none yet'}")
print()
print(subs[["submarket", "borough", "pop", "white_pct", "asian_pct", "black_pct",
            "hh_income_total", "hh_income_ahc"]]
      .sort_values("hh_income_total", ascending=False)
      .to_string(index=False, float_format=lambda v: f"{v:,.0f}"))
