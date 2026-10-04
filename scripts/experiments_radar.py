"""Two questions about the radar model, answered on the record rather than by argument.

  1. Is the ridge penalty (30, chosen up front and never tested) hurting? Compare a grid of fixed
     penalties and a penalty chosen afresh at every forecast month by walking forward inside the training
     data only (nested cross-validation).
  2. Does "London is dear against earnings" help, especially near turning points? Two valuation
     features -- price to earnings, and the mortgage payment on that price to earnings -- each measured
     against its own average to date, added to the existing inputs and tested on exactly the same months.

The rules for adopting either change were set before the results were looked at:

  nested penalty   adopted if its RMSE is no worse than the fixed penalty of 30
  valuation terms  adopted if the RMSE is lower overall AND in at least two of the three sub-periods AND
                   no worse in the months where "same as last year" missed by 8 points or more

Everything is compared on the same origins (those where every model can forecast), because a model that
can only start later is otherwise flattered or punished by a different stretch of history. Significance:
Diebold-Mariano on squared errors with a Newey-West variance (12-month horizon overlaps), which is
still generous with 12-month overlapping outcomes; read p-values as indicative.

Writes data/processed/radar_experiments.json, which build_radar.py reads.
"""
import json, math, pathlib, sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import build_radar as br  # noqa: E402

MIN_TRAIN = 60
FIRST = "2005-01"
PERIODS = {"2008–2015": ("2008-01", "2015-12"), "2016–2019": ("2016-01", "2019-12"), "2020–": ("2020-01", "2099-12")}


def rmse(e):
    return float(np.sqrt(np.mean(np.square(e))))


def dm(e1, e2, h=12):
    """Diebold-Mariano test that model 1 has smaller squared error than model 2. Returns (stat, two-sided p)."""
    d = np.square(e1) - np.square(e2)
    n = len(d)
    dc = d - d.mean()
    lrv = float(np.mean(dc * dc))
    for k in range(1, h):
        lrv += 2 * (1 - k / h) * float(np.mean(dc[k:] * dc[:-k]))
    se = math.sqrt(max(lrv, 1e-12) / n)
    t = float(d.mean() / se)
    p = math.erfc(abs(t) / math.sqrt(2))
    return t, p


def stats(bt, ref_naive):
    e = (bt["y"] - bt["pred"]).to_numpy()
    out = {"n": int(len(bt)), "rmse": rmse(e), "hit": float((np.sign(bt["pred"]) == np.sign(bt["y"])).mean()),
           "periods": {}}
    for name, (a, b) in PERIODS.items():
        m = (bt.index >= a) & (bt.index <= b)
        out["periods"][name] = {"n": int(m.sum()), "rmse": rmse(e[m]) if m.sum() else None}
    turn = (bt["y"] - bt["naive"]).abs() >= 8
    out["turn"] = {"n": int(turn.sum()), "rmse": rmse(e[turn.to_numpy()]) if turn.sum() else None}
    return out


def main():
    d, L, m = br.load()
    f = br.features(d, m)
    base = br.SETS["all"]
    res = {"min_train": MIN_TRAIN, "first": FIRST}

    # ---- 1 · penalty
    fixed = {}
    bts = {}
    for lam in br.LAMBDAS:
        bts[f"lam{lam}"] = br.backtest(f, base, lam=lam, min_train=MIN_TRAIN, first=FIRST)
    bts["nested"] = br.backtest(f, base, min_train=MIN_TRAIN, first=FIRST, nested=True)
    common = bts["nested"].index
    for k in bts:
        common = common.intersection(bts[k].index)
    naive = bts["nested"].loc[common, "naive"]
    res["common_n"] = int(len(common)); res["common_from"] = common[0]; res["common_to"] = common[-1]
    for k, bt in bts.items():
        bt = bt.loc[common]
        s_ = stats(bt, naive)
        s_["post2016"] = rmse((bt["y"] - bt["pred"]).loc["2016-01":])
        fixed[k] = s_
    en = (bts["nested"].loc[common, "y"] - bts["nested"].loc[common, "naive"]).to_numpy()
    res["naive_rmse"] = rmse(en)
    res["naive_post2016"] = rmse((bts["nested"].loc[common, "y"] - bts["nested"].loc[common, "naive"]).loc["2016-01":])
    res["penalty"] = fixed
    res["nested_lambda_choices"] = {str(k): int(v) for k, v in bts["nested"].loc[common, "lam"].value_counts().sort_index().items()}
    e30 = (bts["lam30"].loc[common, "y"] - bts["lam30"].loc[common, "pred"]).to_numpy()
    enst = (bts["nested"].loc[common, "y"] - bts["nested"].loc[common, "pred"]).to_numpy()
    t_, p_ = dm(enst, e30)
    res["nested_vs_30"] = {"dm_t": t_, "p": p_}
    use_nested = fixed["nested"]["rmse"] <= fixed["lam30"]["rmse"]
    res["use_nested"] = bool(use_nested)

    # ---- 2 · valuation terms, with the chosen penalty rule
    sets = {"现有 8 项": base, "+ 房价/收入": base + ["pe_gap"], "+ 月供/收入": base + ["pti_gap"],
            "+ 两个估值项": base + br.VAL, "只用两个估值项": br.VAL, "不含动量 + 两个估值项": br.SETS["no momentum"] + br.VAL}
    vb = {k: br.backtest(f, c, lam=30.0, min_train=MIN_TRAIN, first=FIRST, nested=use_nested) for k, c in sets.items()}
    common2 = None
    for bt in vb.values():
        common2 = bt.index if common2 is None else common2.intersection(bt.index)
    ref = vb["现有 8 项"].loc[common2]
    e_ref = (ref["y"] - ref["pred"]).to_numpy()
    e_nv = (ref["y"] - ref["naive"]).to_numpy()
    out = {}
    for k, bt in vb.items():
        bt = bt.loc[common2]
        e = (bt["y"] - bt["pred"]).to_numpy()
        s_ = stats(bt, ref["naive"])
        s_["dm_vs_base"] = dict(zip(("t", "p"), dm(e, e_ref))) if k != "现有 8 项" else None
        s_["dm_vs_naive"] = dict(zip(("t", "p"), dm(e, e_nv)))
        out[k] = s_
    res["valuation"] = out
    res["valuation_n"] = int(len(common2)); res["valuation_from"] = common2[0]; res["valuation_to"] = common2[-1]
    res["valuation_naive"] = {"rmse": rmse(e_nv), "periods": {n: rmse(e_nv[(ref.index >= a) & (ref.index <= b)]) for n, (a, b) in PERIODS.items()},
                              "turn": rmse(e_nv[(ref["y"] - ref["naive"]).abs().to_numpy() >= 8])}
    # ---- the adoption rule
    b0 = out["现有 8 项"]
    verdict = {}
    for k, s_ in out.items():
        if k == "现有 8 项":
            continue
        wins = sum(1 for p_ in PERIODS if s_["periods"][p_]["rmse"] is not None and b0["periods"][p_]["rmse"] is not None
                   and s_["periods"][p_]["rmse"] < b0["periods"][p_]["rmse"])
        ok = (s_["rmse"] < b0["rmse"]) and wins >= 2 and (s_["turn"]["rmse"] is None or s_["turn"]["rmse"] <= b0["turn"]["rmse"])
        verdict[k] = {"adopt": bool(ok), "period_wins": wins}
    res["verdict"] = verdict
    res["adopt_valuation"] = [k for k, v in verdict.items() if v["adopt"] and k in ("+ 房价/收入", "+ 月供/收入", "+ 两个估值项")]
    res["valuation_features"] = {"+ 房价/收入": ["pe_gap"], "+ 月供/收入": ["pti_gap"], "+ 两个估值项": br.VAL}
    (br.PROC / "radar_experiments.json").write_text(json.dumps(res, ensure_ascii=False, default=float, indent=1))

    # ---- print
    print(f"penalty: {res['common_n']} common months {res['common_from']}..{res['common_to']}; 'same as last year' RMSE {res['naive_rmse']:.2f} (since 2016 {res['naive_post2016']:.2f})")
    for k, v in fixed.items():
        print(f"  {k:8s} RMSE {v['rmse']:5.2f}  since 2016 {v['post2016']:5.2f}  turning {v['turn']['rmse'] or 0:5.2f}  hit {v['hit']*100:3.0f}%")
    print("  nested choices", res["nested_lambda_choices"], f"nested vs 30: DM t={t_:+.2f} p={p_:.2f}; use_nested={use_nested}")
    print(f"valuation: {res['valuation_n']} common months {res['valuation_from']}..{res['valuation_to']}; naive RMSE {res['valuation_naive']['rmse']:.2f}, "
          f"by period {({k: round(v,2) for k,v in res['valuation_naive']['periods'].items()})}, turning {res['valuation_naive']['turn']:.2f}")
    for k, v in out.items():
        pr = "  ".join(f"{n} {x['rmse']:.2f}" for n, x in v["periods"].items())
        dmb = v["dm_vs_base"]
        print(f"  {k:20s} RMSE {v['rmse']:5.2f} | {pr} | turning {v['turn']['rmse']:.2f} (n={v['turn']['n']}) | hit {v['hit']*100:.0f}% | vs base p={dmb['p'] if dmb else float('nan'):.2f} | vs naive p={v['dm_vs_naive']['p']:.2f} | {verdict.get(k)}")
    print("adopt:", res["adopt_valuation"])


if __name__ == "__main__":
    main()
