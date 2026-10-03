"""Does anything lead London house prices, and what does it say now? -> web/data/radar.json.

The question is when to buy over the next year, and which way prices and rents head over five. Price
changes are not forecastable to a point, so this does three honest things:

  1. Backtest. For every month since 2003, forecast the next twelve months of the London HPI using only
     what had been published by then (the Land Registry index lags about three months, the rates and
     lenders' data a few weeks), and compare with simply assuming prices keep doing what they did over
     the last year. A model that does not beat that is reported as not beating it.
  2. Forecast. Fit the same model on all history and read it at the latest month, with the range taken
     from how wrong it has been out of sample, not from a textbook error term.
  3. Scenarios for the five years. With six independent five-year windows since 1995 there is nothing to
     fit a five-year forecast to; the page instead takes a rate and an earnings assumption from the
     reader and applies the rate sensitivity estimated below to it.

What the model uses at forecast month s (the last month of the London HPI), and when it is known:
  London price momentum (1y, 3y)                          known at s
  mortgage approvals for house purchase, 3m vs year ago   month s+1  (published ~4 weeks after month end)
  2-year fixed mortgage rate, level and 6m change         month s+2
  Bank Rate change over 12m, and 5y gilt minus Bank Rate  month s+2
  Nationwide UK index, 3m change                          month s+2
"""
import json, pathlib, sys
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC, WEB, RAW = ROOT / "data" / "processed", ROOT / "web" / "data", ROOT / "data" / "raw"
H = 12            # months ahead
FIRST_TEST = "2003-01"
MIN_TRAIN = 96    # months of training targets before the first test origin


def load():
    p = pd.read_csv(PROC / "london_panel.csv")
    L = p[p.code == "E12000007"].set_index("ym").sort_index()
    m = pd.read_csv(PROC / "macro_monthly.csv", index_col=0)
    idx = pd.period_range("1995-01", L.index[L.price.notna()].max(), freq="M").strftime("%Y-%m")
    d = pd.DataFrame(index=idx)
    d["lp"] = np.log(L["price_index"].reindex(idx))
    return d, L, m


def shifted(m, col, k):
    """The macro series as it would be known at an origin s: the value k months after s."""
    s = m[col].copy()
    s.index = pd.PeriodIndex(s.index, freq="M")
    return s.shift(-k)          # value at s = series at s+k


def features(d, m):
    P = pd.PeriodIndex(d.index, freq="M")
    f = pd.DataFrame(index=d.index)
    lp = d["lp"]
    f["mom12"] = (lp - lp.shift(12)) * 100
    f["mom36"] = (lp - lp.shift(36)) * 100 / 3
    ap = np.log(m["approvals"].replace(0, np.nan)); ap.index = pd.PeriodIndex(ap.index, freq="M")
    ap3 = ap.rolling(3).mean()
    f["appr"] = ((ap3 - ap3.shift(12)) * 100).shift(-1).reindex(P).to_numpy()          # known at s+1
    mr = shifted(m, "mort2y75", 2).reindex(P)
    f["mort"] = mr.to_numpy()
    mr6 = (m["mort2y75"] - m["mort2y75"].shift(6)); mr6.index = pd.PeriodIndex(mr6.index, freq="M")
    f["mort_chg6"] = mr6.shift(-2).reindex(P).to_numpy()
    br = m["bank_rate"] - m["bank_rate"].shift(12); br.index = pd.PeriodIndex(br.index, freq="M")
    f["bank_chg12"] = br.shift(-2).reindex(P).to_numpy()
    sl = m["glc_spot5y"] - m["bank_rate"]; sl.index = pd.PeriodIndex(sl.index, freq="M")
    f["slope"] = sl.shift(-2).reindex(P).to_numpy()
    nw = np.log(m["nw_sa"]); nw.index = pd.PeriodIndex(nw.index, freq="M")
    f["nw3"] = ((nw - nw.shift(3)) * 400 / 3).shift(-2).reindex(P).to_numpy()           # annualised, known at s+2
    f["y"] = (lp.shift(-H) - lp) * 100
    return f


SETS = {"all": ["mom12", "mom36", "appr", "mort", "mort_chg6", "bank_chg12", "slope", "nw3"],
        "momentum only": ["mom12", "mom36"],
        "rates only": ["mort", "mort_chg6", "bank_chg12", "slope"],
        "approvals + Nationwide": ["appr", "nw3"],
        "no momentum": ["appr", "mort", "mort_chg6", "bank_chg12", "slope", "nw3"]}


def ridge_fit(X, y, lam):
    mu, sd = X.mean(0), X.std(0).replace(0, 1)
    Z = (X - mu) / sd
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    b = np.linalg.solve(A, Z.T @ (y - y.mean()))
    return {"mu": mu, "sd": sd, "b": b, "c": y.mean()}


def ridge_pred(m, X):
    return m["c"] + ((X - m["mu"]) / m["sd"]).to_numpy() @ m["b"]


def backtest(f, cols, lam=30.0):
    """Expanding window, refit every origin; training targets only from origins whose outcome is known."""
    rows = []
    origins = [s for s in f.index if s >= FIRST_TEST and not np.isnan(f.at[s, "y"])]
    idx = list(f.index)
    for s in origins:
        k = idx.index(s)
        tr = f.iloc[: max(k - H + 1, 0)].dropna(subset=cols + ["y"])
        if len(tr) < MIN_TRAIN or f.loc[[s], cols].isna().any(axis=None):
            continue
        mdl = ridge_fit(tr[cols], tr["y"].to_numpy(float), lam)
        rows.append((s, float(ridge_pred(mdl, f.loc[[s], cols])[0]), f.at[s, "y"], f.at[s, "mom12"]))
    return pd.DataFrame(rows, columns=["s", "pred", "y", "naive"]).set_index("s")


def score(bt):
    e = bt["y"] - bt["pred"]; en = bt["y"] - bt["naive"]; e0 = bt["y"] - bt["y"].mean()
    return {"n": int(len(bt)), "rmse": float(np.sqrt((e ** 2).mean())), "rmse_naive": float(np.sqrt((en ** 2).mean())),
            "rmse_mean": float(np.sqrt((e0 ** 2).mean())),
            "r2_vs_naive": float(1 - (e ** 2).sum() / (en ** 2).sum()), "r2": float(1 - (e ** 2).sum() / (e0 ** 2).sum()),
            "hit": float((np.sign(bt["pred"]) == np.sign(bt["y"])).mean()),
            "hit_naive": float((np.sign(bt["naive"]) == np.sign(bt["y"])).mean())}


def main():
    d, L, m = load()
    f = features(d, m)
    out = {"asof_hpi": d.index[d.lp.notna()].max(), "horizon": H}
    res = {}
    for name, cols in SETS.items():
        bt = backtest(f, cols)
        sc = score(bt)
        sc["post2009"] = score(bt.loc["2009-01":])
        sc["post2016"] = score(bt.loc["2016-01":])
        sc["periods"] = {"至 2008": score(bt.loc[:"2008-12"]), "2009–2015": score(bt.loc["2009-01":"2015-12"]),
                         "2016–": score(bt.loc["2016-01":])}
        res[name] = sc
        if name == "all":
            all_bt = bt
    out["backtest"] = res
    # --- forecast at the latest HPI month
    last = out["asof_hpi"]
    cols = SETS["all"]
    tr = f.iloc[: len(f) - H].dropna(subset=cols + ["y"])
    mdl = ridge_fit(tr[cols], tr["y"].to_numpy(float), 30.0)
    x = f.loc[[last], cols]
    missing = [c for c in cols if np.isnan(x.iloc[0][c])]
    # the newest macro months may not exist yet: fall back to the latest value of each feature
    for c in missing:
        x[c] = f[c].dropna().iloc[-1]
    point = float(ridge_pred(mdl, x)[0])
    resid = (all_bt["y"] - all_bt["pred"]).to_numpy()
    q = np.quantile(resid, [.1, .25, .5, .75, .9])
    out["forecast"] = {"origin": last, "point": point, "p10": point + q[0], "p25": point + q[1], "p50": point + q[2], "p75": point + q[3],
                       "p90": point + q[4], "prob_fall": float((point + resid < 0).mean()),
                       "features_used_from": {c: (last if c not in missing else "latest available") for c in cols},
                       "contrib": {c: float(((x.iloc[0][c] - mdl["mu"][c]) / mdl["sd"][c]) * mdl["b"][i]) for i, c in enumerate(cols)},
                       "coef": {c: float(mdl["b"][i]) for i, c in enumerate(cols)},
                       "current": {c: float(x.iloc[0][c]) for c in cols}}
    # --- analogues: the months whose conditions looked most like now, and what followed
    Z = (f[cols] - mdl["mu"]) / mdl["sd"]
    hist = Z.dropna().loc[: f.index[len(f) - H - 1]]
    z0 = ((x - mdl["mu"]) / mdl["sd"]).iloc[0]
    dist = ((hist - z0) ** 2).sum(axis=1) ** .5
    nn = dist.sort_values().index[:30]
    ys = f.loc[nn, "y"].dropna()
    out["analogues"] = {"n": int(len(ys)), "p10": float(ys.quantile(.1)), "p50": float(ys.median()), "p90": float(ys.quantile(.9)),
                        "share_up": float((ys > 0).mean()), "years": sorted({s[:4] for s in nn})}
    # --- the out-of-sample record, for the chart
    out["backtest_from"] = all_bt.index[0]
    out["record"] = [{"s": s, "pred": round(r.pred, 2), "y": round(r.y, 2), "naive": round(r.naive, 2)} for s, r in all_bt.iterrows()]
    out["ois"] = json.loads((PROC / "ois_path.json").read_text())
    # --- what a higher mortgage rate does, arithmetically, and what it did last time
    def annuity(r, n=25):
        i = r / 1200
        return i / (1 - (1 + i) ** (-n * 12))
    mm = m["mort2y75"].dropna()
    lpx = d["lp"]
    def episode(a_, b_, lag=12):
        ra, rb = float(mm.get(a_)), float(mm.get(b_))
        cap = (annuity(ra) / annuity(rb) - 1) * 100
        end = str(pd.Period(b_, "M") + lag)
        price = float((lpx.get(end) - lpx.get(a_)) * 100) if end in lpx.index and not np.isnan(lpx.get(end)) else None
        return {"from": a_, "to": b_, "end": end, "r_from": ra, "r_to": rb, "capacity": cap, "london_price": price}
    out["episode"] = episode("2021-12", "2023-08")
    # --- the market-implied path of the 2-year fixed rate, month by month, off the swap forward curve
    pts = out["ois"]["path"]
    ys_, fs_ = np.array([p_[0] for p_ in pts]), np.array([p_[1] for p_ in pts])
    def f2(mo):
        t = np.linspace(mo / 12, mo / 12 + 2, 41)
        return float(np.interp(t, ys_, fs_).mean())
    base_ = f2(0)
    out["rate_path"] = [{"m": mo, "swap2y": round(f2(mo), 3), "fixed2y": round(float(mm.iloc[-1]) + f2(mo) - base_, 3)} for mo in range(0, 13)]
    # --- the five-year record
    five = ((d["lp"].shift(-60) - d["lp"]) * 100 / 5).dropna()
    out["five_year"] = {"p10": float(five.quantile(.1)), "p25": float(five.quantile(.25)), "p50": float(five.median()),
                        "p75": float(five.quantile(.75)), "p90": float(five.quantile(.9)), "min": float(five.min()), "max": float(five.max()),
                        "independent_windows": 6}
    out["five_year_by_start"] = {s: round(float(v), 1) for s, v in five.items() if s.endswith("-01") and s[:4] in {str(y) for y in range(1995, 2022, 2)}}
    # --- where things are now
    lastm = m.dropna(subset=["bank_rate"]).index[-1]
    cur = {}
    def series(col, label, unit, hist_from="2005-01", good=None):
        s = m[col].dropna()
        if s.empty: return
        v, t = float(s.iloc[-1]), s.index[-1]
        s2 = s.loc[hist_from:]
        cur[col] = {"label": label, "unit": unit, "value": v, "month": t,
                    "chg3": float(v - s.iloc[-4]) if len(s) > 3 else None,
                    "chg12": float(v - s.iloc[-13]) if len(s) > 12 else None,
                    "pct": float((s2 < v).mean() * 100),
                    "spark": [round(float(x), 2) for x in s.iloc[-36:]]}
    series("bank_rate", "Bank Rate", "%"); series("mort2y75", "2 年固定按揭利率（75% LTV）", "%"); series("mort5y75", "5 年固定按揭利率（75% LTV）", "%")
    series("glc_spot2y", "2 年期国债收益率", "%"); series("glc_spot5y", "5 年期国债收益率", "%")
    series("approvals", "按揭批贷（购房，季调）", "套"); series("nw_sa", "Nationwide 房价指数（UK，季调，1993 Q1 = 100）", "指数")
    series("hmrc_eng", "HMRC 住宅成交（英格兰，月）", "套"); series("hmrc_uk_sa", "HMRC 住宅成交（UK，季调）", "套")
    out["current"] = cur
    # --- London fundamentals from the panel
    fl = L[["price", "flat_price", "rent", "rent_flat", "price_yoy", "rent_yoy", "yield_flat", "sales12", "sales_idx", "cash_share"]].dropna(how="all")
    lastp = fl["price"].dropna().index[-1]
    out["london"] = {"month": lastp, "price": float(fl.at[lastp, "price"]), "flat_price": float(fl["flat_price"].dropna().iloc[-1]),
                     "price_yoy": float(fl["price_yoy"].dropna().iloc[-1]),
                     "rent_month": fl["rent"].dropna().index[-1], "rent": float(fl["rent"].dropna().iloc[-1]),
                     "rent_flat": float(fl["rent_flat"].dropna().iloc[-1]), "rent_yoy": float(fl["rent_yoy"].dropna().iloc[-1]),
                     "yield_flat": float(fl["yield_flat"].dropna().iloc[-1]),
                     "sales_idx": float(fl["sales_idx"].dropna().iloc[-7]), "sales_idx_month": fl["sales_idx"].dropna().index[-7]}
    # --- seasonality: Nationwide's own seasonal factor (unadjusted over seasonally adjusted), by calendar month
    nw = m[["nw_idx", "nw_sa"]].dropna()
    sf = (nw["nw_idx"] / nw["nw_sa"]).loc["2000-01":]
    out["season"] = {mo: round(float((sf[sf.index.str[5:] == f"{mo:02d}"].mean() - 1) * 100), 2) for mo in range(1, 13)}
    # --- the market's path for rates
    out["mort_now"] = float(m["mort2y75"].dropna().iloc[-1]); out["mort_now_month"] = m["mort2y75"].dropna().index[-1]
    out["bank_now"] = float(m["bank_rate"].dropna().iloc[-1])
    rics = RAW / "macro" / "rics.json"
    out["rics"] = json.loads(rics.read_text()) if rics.exists() else None
    out["generated"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    def clean(o):
        if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)): return None if np.isnan(o) else round(float(o), 3)
        if isinstance(o, np.integer): return int(o)
        return o
    (WEB / "radar.json").write_text(json.dumps(clean(out), ensure_ascii=False, separators=(",", ":")))
    # a plain-text summary for the console
    a = res["all"]
    print(f"HPI to {out['asof_hpi']}; backtest n={a['n']}: model RMSE {a['rmse']:.1f}pp vs 'same as last year' {a['rmse_naive']:.1f}pp "
          f"(R2 vs naive {a['r2_vs_naive']:+.2f}); direction right {a['hit']*100:.0f}% vs {a['hit_naive']*100:.0f}%")
    for k, v in res.items():
        print(f"  {k:24s} RMSE {v['rmse']:5.1f}  vs naive {v['rmse_naive']:5.1f}  R2vsNaive {v['r2_vs_naive']:+.2f}  | since 2016: {v['post2016']['rmse']:.1f} vs {v['post2016']['rmse_naive']:.1f}")
    fc = out["forecast"]
    print(f"forecast {fc['origin']}+12m: {fc['point']:+.1f}%  80% range {fc['p10']:+.1f} .. {fc['p90']:+.1f}  P(fall) {fc['prob_fall']*100:.0f}%")
    print("contrib", {k: round(v, 1) for k, v in fc["contrib"].items()})
    print("analogues", out["analogues"])
    print("episode", out["episode"], "5y", out["five_year"])


if __name__ == "__main__":
    main()
