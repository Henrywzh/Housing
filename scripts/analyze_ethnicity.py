"""How the ethnic make-up of a small area relates to income, crime and jobs.

An association, not an explanation. Ethnic mix is tangled up with where people
could afford to live, when each group arrived, what housing was on offer and how
old the household is, so a raw correlation says little by itself. This prints
three things for each group, over London's 4,994 LSOAs (income: MSOAs):

  raw    Pearson correlation with each outcome, weighted by population
  holding other things equal
         the same relationship after regressing out density, private renting,
         owner-occupation, share aged 25-39, share with a degree and (for crime)
         the visitor share, which is what separates a commercial area from a
         residential one
  gap    the outcome in the LSOAs where the group is in the top fifth against the
         bottom fifth

Outcomes: net household income (ONS model-based estimate, MSOA, FY2023),
managerial or professional jobs (Census), degree share, flat median price,
residential burglary and violence per capita.
"""
import pathlib, sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from demand import ethnic_shares, pivot, ETH  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"

GROUPS = {"wb": "英国白人", "wo": "其他白人", "as": "亚裔(合计)", "ch": "华裔", "in": "印度裔", "pk": "巴基斯坦裔",
          "bd": "孟加拉裔", "bk": "黑人(合计)", "af": "非洲裔", "cb": "加勒比裔", "mx": "混血", "ar": "阿拉伯裔"}


def load():
    sh, pop = ethnic_shares()
    soc = pd.read_csv(PROC / "lsoa_social.csv").set_index("lsoa")
    met = pd.read_csv(PROC / "lsoa_metrics.csv").set_index("lsoa")
    occ = pivot("lsoa_occ", "c2021_occ_10")
    d = sh.join(pop.rename("pop")).join(soc[["density", "degree_pct", "age_25_39_pct", "owned_pct", "private_rent_pct",
                                              "burglary_resid_per_1000_hh", "violence_per_1000", "visitor_share"]])
    d["pro_pct"] = 100 * (occ[1] + occ[2]) / occ[0]
    d["flat_price"] = met["median"]
    # income is published per MSOA: give each LSOA its MSOA's
    pc = pd.read_csv(RAW / "postcodes.csv", usecols=["lsoa", "msoa"]).drop_duplicates("lsoa").set_index("lsoa")
    inc = pd.read_excel(RAW / "msoa_income_fye2023.xlsx", sheet_name="Net income before housing costs", header=3)
    inc = inc.rename(columns={inc.columns[0]: "msoa", inc.columns[6]: "net_income"}).set_index("msoa")["net_income"]
    d["net_income"] = pd.to_numeric(pc["msoa"].map(inc), errors="coerce")
    d["log_density"] = np.log(d["density"])
    return d.dropna(subset=["pop"])


def wcorr(x, y, w):
    m = x.notna() & y.notna() & w.notna()
    x, y, w = x[m], y[m], w[m]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    c = np.average((x - mx) * (y - my), weights=w)
    return c / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)), int(m.sum())


def resid(y, X, w):
    """y with the part explained by X (weighted least squares) removed."""
    m = y.notna() & X.notna().all(axis=1) & w.notna()
    A = np.column_stack([np.ones(m.sum()), X[m].to_numpy(float)])
    sw = np.sqrt(w[m].to_numpy(float))
    beta = np.linalg.lstsq(A * sw[:, None], y[m].to_numpy(float) * sw, rcond=None)[0]
    r = pd.Series(np.nan, index=y.index)
    r[m] = y[m].to_numpy(float) - A @ beta
    return r


def main():
    d = load()
    ctrl = ["log_density", "private_rent_pct", "owned_pct", "age_25_39_pct", "degree_pct"]
    outcomes = {"net_income": "家庭净收入", "pro_pct": "管理/专业职业%", "degree_pct": "本科%", "flat_price": "公寓中位价",
                "burglary_resid_per_1000_hh": "住宅入室", "violence_per_1000": "暴力"}
    rows = []
    for g, name in GROUPS.items():
        for o, oname in outcomes.items():
            cs = [c for c in ctrl if c != o]
            if o == "violence_per_1000":
                cs = cs + ["visitor_share"]
            raw, n = wcorr(d[g], d[o], d["pop"])
            xr, yr = resid(d[g], d[cs], d["pop"]), resid(d[o], d[cs], d["pop"])
            adj, _ = wcorr(xr, yr, d["pop"])
            q = d[g].quantile([.2, .8])
            hi, lo = d[d[g] >= q[.8]][o].median(), d[d[g] <= q[.2]][o].median()
            rows.append({"group": name, "outcome": oname, "raw_r": round(raw, 2), "adjusted_r": round(adj, 2),
                         "top_fifth": round(hi, 1), "bottom_fifth": round(lo, 1), "n": n})
    out = pd.DataFrame(rows)
    out.to_csv(PROC / "ethnicity_correlations.csv", index=False)
    return d, out


if __name__ == "__main__":
    d, out = main()
    for oname in out.outcome.unique():
        print(f"\n== {oname}")
        print(out[out.outcome == oname][["group", "raw_r", "adjusted_r", "top_fifth", "bottom_fifth"]].to_string(index=False))
