"""Are eight inputs too many? Compared with simpler, explainable models, out of sample, with a locked holdout.

The questions, and how they are answered:

  Correlation among the inputs   correlation matrix, variance-inflation factors and the condition number.
                                 Moderate, not severe (largest VIF below 3). The real problem is not that
                                 inputs overlap but that there are ~30 independent 12-month outcomes
                                 behind a thousand-month-looking sample, so eight free coefficients overfit.
  Simpler models                 same-as-last-year, the long-run mean, one input at a time, three-input models
                                 built from one input per idea (price momentum / lenders' latest data / rates),
                                 a lasso, two principal components, an average of the three-input models,
                                 and the eight-input ridge.
  Out of sample                  every model is re-fitted every month on what had been published by then
                                 (expanding window, 12-month outcome lag, publication lags as in build_radar).
                                 The choice of model is made on origins up to 2017-12 only (their outcomes end
                                 2018-12); origins from 2019-01 are a holdout that selection never sees. The
                                 chosen model is the simplest whose RMSE is within one standard error of the
                                 best on the selection window.
  Intervals                      linear quantile regression on the chosen inputs, against two simpler ways
                                 of getting a range, scored on coverage and pinball loss.

Caveat that cannot be removed: the eight-input model and several of these comparisons were looked at on the
whole history in earlier sessions, so the holdout is clean for the selection made here, not for every idea tried.
Writes data/processed/radar_simple.json.
"""
import json, math, pathlib, sys, warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import LassoCV, QuantileRegressor
from sklearn.model_selection import TimeSeriesSplit
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import build_radar as br  # noqa: E402

warnings.filterwarnings("ignore")
H = br.H
MIN_TRAIN, FIRST = 60, "2005-01"
SEL_END, HOLD_START = "2017-12", "2019-01"
ALL = br.SETS["all"]
M, A, R = "mom12", "nw3", "mort_chg6"        # one input per idea: price momentum, lenders' latest, rates


# ----------------------------------------------------------------------------- models
def design(f, cols, rows):
    return f.loc[rows, cols].to_numpy(float)


def ols_fit(X, y):
    A_ = np.column_stack([np.ones(len(X)), X])
    b = np.linalg.lstsq(A_, y, rcond=None)[0]
    return lambda x: float(b[0] + np.asarray(x, float) @ b[1:]), b


def z(X):
    mu, sd = X.mean(0), X.std(0, ddof=1)
    sd[sd == 0] = 1
    return mu, sd


def make_models():
    models = {}
    models["same as last year"] = dict(k=0, kind="naive")
    models["zero"] = dict(k=0, kind="zero")
    models["long-run mean"] = dict(k=0, kind="mean")
    for c in ALL:
        models[f"only {c}"] = dict(k=1, kind="ols", cols=[c])
    models["momentum + lenders"] = dict(k=2, kind="ols", cols=[M, A])
    models["momentum + rates"] = dict(k=2, kind="ols", cols=[M, R])
    models["lenders + rates"] = dict(k=2, kind="ols", cols=[A, R])
    models["momentum + lenders + rates"] = dict(k=3, kind="ols", cols=[M, A, R])
    models["average of the 2- and 3-input models"] = dict(k=3, kind="combo", parts=["momentum + lenders", "momentum + rates", "lenders + rates", "momentum + lenders + rates"])
    models["lasso (8 inputs)"] = dict(k=8, kind="lasso", cols=ALL)
    models["2 principal components"] = dict(k=2, kind="pca", cols=ALL)
    models["ridge (8 inputs)"] = dict(k=8, kind="ridge", cols=ALL)
    return models


def predict_all(f, models, origins, idx):
    out = {k: {} for k in models}
    coefs = {}
    for s in origins:
        k0 = idx.index(s)
        trn_all = f.iloc[: max(k0 - H + 1, 0)]
        preds = {}
        for name, md in models.items():
            kind = md["kind"]
            if kind == "naive":
                preds[name] = float(f.at[s, "mom12"]); continue
            if kind == "zero":
                preds[name] = 0.0; continue
            if kind == "combo":
                continue
            cols = md.get("cols", [])
            tr = trn_all.dropna(subset=cols + ["y"]) if cols else trn_all.dropna(subset=["y"])
            if kind == "mean":
                preds[name] = float(tr["y"].mean()); continue
            if len(tr) < MIN_TRAIN or f.loc[[s], cols].isna().any(axis=None):
                continue
            X, y = tr[cols].to_numpy(float), tr["y"].to_numpy(float)
            x0 = f.loc[s, cols].to_numpy(float)
            if kind == "ols":
                fn, b = ols_fit(X, y); preds[name] = fn(x0)
                if name == "momentum + lenders + rates":
                    coefs[s] = (b, X.std(0, ddof=1), X.mean(0))
            elif kind == "ridge":
                lam = br.tune_lambda(tr, cols)
                mdl = br.ridge_fit(tr[cols], y, lam); preds[name] = float(br.ridge_pred(mdl, f.loc[[s], cols])[0])
            elif kind == "lasso":
                mu, sd = z(X)
                lm = LassoCV(cv=TimeSeriesSplit(4), n_alphas=25, max_iter=4000).fit((X - mu) / sd, y)
                preds[name] = float(lm.predict(((x0 - mu) / sd)[None, :])[0])
            elif kind == "pca":
                mu, sd = z(X)
                Zs = (X - mu) / sd
                _, _, Vt = np.linalg.svd(Zs, full_matrices=False)
                P = Vt[:2].T
                fn, _ = ols_fit(Zs @ P, y); preds[name] = fn(((x0 - mu) / sd) @ P)
        for name, md in models.items():
            if md["kind"] == "combo" and all(p in preds for p in md["parts"]):
                preds[name] = float(np.mean([preds[p] for p in md["parts"]]))
        for name, v in preds.items():
            out[name][s] = v
    return out, coefs


def rmse(e):
    return float(np.sqrt(np.mean(np.square(e))))


def lrv_se_rmse(e, rm, h=12):
    """Standard error of an RMSE from a series of errors that overlap by h months (Newey-West on squared errors)."""
    d = np.square(e) - np.mean(np.square(e))
    n = len(d)
    lrv = float(np.mean(d * d))
    for k in range(1, h):
        lrv += 2 * (1 - k / h) * float(np.mean(d[k:] * d[:-k]))
    return math.sqrt(max(lrv, 1e-12) / n) / (2 * rm)


def dm(e1, e2, h=12):
    d = np.square(e1) - np.square(e2)
    n = len(d)
    dc = d - d.mean()
    lrv = float(np.mean(dc * dc))
    for k in range(1, h):
        lrv += 2 * (1 - k / h) * float(np.mean(dc[k:] * dc[:-k]))
    t = float(d.mean() / math.sqrt(max(lrv, 1e-12) / n))
    return t, math.erfc(abs(t) / math.sqrt(2))


# ----------------------------------------------------------------------------- main
def main():
    d, L, m = br.load()
    f = br.features(d, m)
    idx = list(f.index)
    origins = [s for s in f.index if s >= FIRST and not np.isnan(f.at[s, "y"])]
    models = make_models()
    P, coefs = predict_all(f, models, origins, idx)
    pred = pd.DataFrame(P)
    common = pred.dropna().index
    res = {"first": FIRST, "min_train": MIN_TRAIN, "selection_end": SEL_END, "holdout_start": HOLD_START}
    # ---- correlation among the inputs
    X = f[ALL].dropna()
    Zs = (X - X.mean()) / X.std()
    vif = {}
    for c in ALL:
        o = [k for k in ALL if k != c]
        A_ = np.column_stack([np.ones(len(Zs)), Zs[o]])
        b = np.linalg.lstsq(A_, Zs[c], rcond=None)[0]
        vif[c] = float(1 / (1 - (1 - ((Zs[c] - A_ @ b) ** 2).sum() / (Zs[c] ** 2).sum())))
    ev = np.linalg.eigvalsh(np.corrcoef(Zs.T))
    res["inputs"] = {"names": ALL, "corr": X.corr().round(2).values.tolist(), "vif": vif, "condition": float(ev.max() / ev.min()),
                     "n_rows": int(len(X)), "n_outcomes_independent": int(len(X) // H),
                     "corr_with_y": f[ALL + ["y"]].dropna().corr()["y"].drop("y").round(2).to_dict()}
    # ---- scores
    y = f.loc[common, "y"]
    sel = common[common <= SEL_END]; hold = common[common >= HOLD_START]
    res["n_common"], res["n_sel"], res["n_hold"] = int(len(common)), int(len(sel)), int(len(hold))
    res["common_from"], res["common_to"] = common[0], common[-1]
    table = {}
    for name in models:
        e_all = (y - pred.loc[common, name]).to_numpy()
        e_sel = (f.loc[sel, "y"] - pred.loc[sel, name]).to_numpy()
        e_hold = (f.loc[hold, "y"] - pred.loc[hold, name]).to_numpy()
        e_nv_h = (f.loc[hold, "y"] - pred.loc[hold, "same as last year"]).to_numpy()
        e_nv_s = (f.loc[sel, "y"] - pred.loc[sel, "same as last year"]).to_numpy()
        table[name] = {"k": models[name]["k"], "rmse_all": rmse(e_all), "rmse_sel": rmse(e_sel), "rmse_hold": rmse(e_hold),
                       "hit_sel": float((np.sign(pred.loc[sel, name]) == np.sign(f.loc[sel, "y"])).mean()),
                       "hit_hold": float((np.sign(pred.loc[hold, name]) == np.sign(f.loc[hold, "y"])).mean()),
                       "dm_sel_p": dm(e_sel, e_nv_s)[1] if name != "same as last year" else None,
                       "dm_hold_p": dm(e_hold, e_nv_h)[1] if name != "same as last year" else None}
    res["models"] = table
    # ---- selection: simplest within one standard error of the best, on the selection window only
    cand = {k: v for k, v in table.items() if k not in ("same as last year",)}
    best = min(cand, key=lambda k: cand[k]["rmse_sel"])
    e_best = (f.loc[sel, "y"] - pred.loc[sel, best]).to_numpy()
    tol = lrv_se_rmse(e_best, cand[best]["rmse_sel"])
    ok = [k for k, v in cand.items() if v["rmse_sel"] <= cand[best]["rmse_sel"] + tol]
    chosen = min(ok, key=lambda k: (cand[k]["k"], cand[k]["rmse_sel"]))
    res["selection"] = {"best": best, "best_rmse": cand[best]["rmse_sel"], "one_se": tol, "within": ok, "chosen": chosen}
    # ---- quantile regression on the chosen inputs
    qcols = models[chosen].get("cols") or models["momentum + lenders + rates"]["cols"]
    if models[chosen]["kind"] in ("combo", "naive", "zero", "mean", "lasso", "pca", "ridge"):
        qcols = models["momentum + lenders + rates"]["cols"]
    res["quantile_inputs"] = qcols
    taus = [0.1, 0.25, 0.5, 0.75, 0.9]
    qrows, bench_u, bench_r = {}, {}, {}
    for s in common:
        k0 = idx.index(s)
        tr = f.iloc[: max(k0 - H + 1, 0)].dropna(subset=qcols + ["y"])
        Xt, yt = tr[qcols].to_numpy(float), tr["y"].to_numpy(float)
        mu, sd = z(Xt)
        x0 = ((f.loc[s, qcols].to_numpy(float) - mu) / sd)[None, :]
        qs = []
        for t in taus:
            qr = QuantileRegressor(quantile=t, alpha=0.0, solver="highs").fit((Xt - mu) / sd, yt)
            qs.append(float(qr.predict(x0)[0]))
        qrows[s] = np.sort(qs)
        bench_u[s] = np.quantile(yt, taus)
        fn, _ = ols_fit(Xt, yt)
        resid = yt - np.array([fn(x) for x in Xt])
        bench_r[s] = np.sort(fn(f.loc[s, qcols].to_numpy(float)) + np.quantile(resid, taus))
    def pin(qm, rows):
        out = {}
        for j, t in enumerate(taus):
            e = np.array([f.at[s, "y"] - qm[s][j] for s in rows])
            out[str(t)] = float(np.mean(np.maximum(t * e, (t - 1) * e)))
        cov80 = float(np.mean([qm[s][0] <= f.at[s, "y"] <= qm[s][4] for s in rows]))
        cov50 = float(np.mean([qm[s][1] <= f.at[s, "y"] <= qm[s][3] for s in rows]))
        width80 = float(np.mean([qm[s][4] - qm[s][0] for s in rows]))
        score80 = float(np.mean([(qm[s][4] - qm[s][0]) + (2 / 0.2) * (max(qm[s][0] - f.at[s, "y"], 0) + max(f.at[s, "y"] - qm[s][4], 0)) for s in rows]))
        return {"pinball": out, "pinball_mean": float(np.mean(list(out.values()))), "cov80": cov80, "cov50": cov50, "width80": width80, "interval_score80": score80}
    res["quantile"] = {}
    for label, rows in (("selection", sel), ("holdout", hold)):
        res["quantile"][label] = {"quantile regression": pin(qrows, rows), "unconditional history": pin(bench_u, rows), "OLS + residual quantiles": pin(bench_r, rows)}
    # ---- the latest forecast from the chosen simple model and from the quantile regression
    last = d.index[d.lp.notna()].max()
    trn = f.iloc[: len(f) - H]
    x_now = f.loc[[last], qcols].copy()
    for c in qcols:
        if np.isnan(x_now.iloc[0][c]):
            x_now[c] = f[c].dropna().iloc[-1]
    tr = trn.dropna(subset=qcols + ["y"])
    Xt, yt = tr[qcols].to_numpy(float), tr["y"].to_numpy(float)
    mu, sd = z(Xt)
    x0 = ((x_now.iloc[0].to_numpy(float) - mu) / sd)[None, :]
    qnow = np.sort([float(QuantileRegressor(quantile=t, alpha=0.0, solver="highs").fit((Xt - mu) / sd, yt).predict(x0)[0]) for t in taus])
    fn, b = ols_fit(Xt, yt)
    res["now"] = {"origin": last, "quantile_inputs": qcols, "quantiles": dict(zip(map(str, taus), qnow.tolist())),
                  "ols_point": fn(x_now.iloc[0].to_numpy(float)), "ols_coef": dict(zip(["intercept"] + qcols, b.tolist())),
                  "input_values": x_now.iloc[0].to_dict(), "input_mean": dict(zip(qcols, Xt.mean(0).tolist())), "input_sd": dict(zip(qcols, Xt.std(0, ddof=1).tolist())),
                  "unconditional": dict(zip(map(str, taus), np.quantile(yt, taus).tolist())), "n_train": int(len(tr))}
    # the record for a chart: chosen model and the 10-90 band, by origin
    res["record"] = [{"s": s, "y": round(float(f.at[s, "y"]), 2), "naive": round(float(pred.at[s, "same as last year"]), 2),
                      "chosen": round(float(pred.at[s, chosen]), 2), "q10": round(float(qrows[s][0]), 2), "q50": round(float(qrows[s][2]), 2), "q90": round(float(qrows[s][4]), 2)} for s in common]
    (br.PROC / "radar_simple.json").write_text(json.dumps(res, ensure_ascii=False, default=float, indent=1))

    # ---- print
    print(f"inputs: {res['inputs']['n_rows']} rows, ~{res['inputs']['n_outcomes_independent']} independent 12-month outcomes; max VIF {max(vif.values()):.1f}; condition {res['inputs']['condition']:.0f}")
    print(f"common origins {res['common_from']}..{res['common_to']} n={len(common)} (selection {len(sel)} to {SEL_END}; holdout {len(hold)} from {HOLD_START})")
    print(f"{'model':40s} k  sel RMSE  hold RMSE  hit(sel/hold)  DM p vs naive (sel/hold)")
    for n_, v in sorted(table.items(), key=lambda kv: kv[1]["rmse_sel"]):
        pp = lambda x: "  -  " if x is None else f"{x:.2f}"
        print(f"  {n_:38s} {v['k']}  {v['rmse_sel']:7.2f}  {v['rmse_hold']:8.2f}   {v['hit_sel']*100:3.0f}%/{v['hit_hold']*100:3.0f}%      {pp(v['dm_sel_p'])}/{pp(v['dm_hold_p'])}")
    print("selection:", res["selection"])
    for lab in ("selection", "holdout"):
        print(lab, {k: (round(v["pinball_mean"], 2), round(v["cov80"], 2), round(v["cov50"], 2), round(v["width80"], 1), round(v["interval_score80"], 1)) for k, v in res["quantile"][lab].items()})
    print("now", {k: round(v, 1) for k, v in res["now"]["quantiles"].items()}, "ols", round(res["now"]["ols_point"], 1), res["now"]["ols_coef"])


if __name__ == "__main__":
    main()
