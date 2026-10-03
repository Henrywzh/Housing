"""Who would rent or buy here: the people, the jobs, and the rent.

For a point, over the LSOAs whose centre is within 1 km (Census 2021; sums of
numerators over sums of denominators, so a big LSOA counts for more):

  pr   share of employed residents in managerial or professional jobs (TS063)
  dg   share of adults with a degree or above (TS067)
  yg   share aged 25-39, the renting and first-buying years
  rn   share of households renting privately
  fi   share of employed residents in finance and insurance (TS060)
  tc   share in professional services or information and communication (TS060)
       -- industry is published only down to MSOA, so these two use MSOAs whose
       centre is within 1.5 km.
  jb   people working within 2 km, in thousands (2011 Census workplace population:
       the last time it was counted by LSOA; the offices have not moved).

Borough level, from ONS's Price Index of Private Rents (latest month):
  rent monthly rent for a flat or maisonette, rg its change over twelve months.
Whether a tenant would pay it is a matter of income; the yield on an asking price
is rent over price, worked out in build_web_payload.py where the price is known.
"""
import json, math, pathlib
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely import STRtree

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
KX = 111_320.0 * math.cos(math.radians(51.5))
KY = 111_320.0


def xy(lat, lon):
    return np.column_stack([np.asarray(lon) * KX, np.asarray(lat) * KY])


def pivot(name, dim):
    d = pd.read_csv(RAW / f"{name}.csv")
    return d.pivot_table(index="GEOGRAPHY_CODE", columns=dim.upper(), values="OBS_VALUE", aggfunc="sum")


# Census 2021 ethnic group (TS021): short key -> code. Shares are of all residents.
ETH = {"as": 1001, "ch": 13, "in": 10, "pk": 11, "bd": 12, "oa": 14,
       "bk": 1002, "af": 16, "cb": 15, "ob": 17,
       "mx": 1003, "wh": 1004, "wb": 1, "ir": 2, "wo": 5, "ar": 18, "ot": 19}


ETH_ALL = [*ETH, "ax"]


def ethnic_shares():
    """LSOA -> % of residents in each ethnic group (columns are ETH_ALL).
    "ax" is Asian other than Chinese, so Chinese and the rest can be told apart."""
    e = pivot("lsoa_ethnic", "c2021_eth_20")
    sh = pd.DataFrame({k: 100 * e[c] / e[0] for k, c in ETH.items()})
    sh["ax"] = sh["as"] - sh["ch"]
    return sh, e[0]


def lsoa_extra():
    """LSOA -> %: born outside the UK, religion (of residents), main language not English,
    poor English, and household types (of households). Keys are the short names the
    analysis page and the map's colouring both use."""
    cob = pd.read_csv(RAW / "lsoa_cob.csv").pivot_table(index="GEOGRAPHY_CODE", columns="C2021_COB_12", values="OBS_VALUE")
    d = pd.DataFrame({"nb": 100 * (1 - cob[1] / cob[0])})
    rel = pivot("lsoa_religion", "c2021_religion_10")
    for k, c in (("rn0", 1), ("rch", 2), ("rbu", 3), ("rhi", 4), ("rje", 5), ("rmu", 6), ("rsi", 7)):
        d[k] = 100 * rel[c] / rel[0]
    eng = pivot("lsoa_engprf", "c2021_engprf_6")
    d["nl"] = 100 * eng[1001] / eng[0]
    d["pe"] = 100 * (eng[4] + eng[5]) / eng[0]
    hh = pivot("lsoa_hhcomp", "c2021_hhcomp_15")
    for k, cs in (("h1o", [1]), ("h1", [2]), ("hnc", [4, 7]), ("hdc", [5, 8, 10, 13]), ("hlp", [10]), ("hst", [14])):
        d[k] = 100 * hh[cs].sum(axis=1) / hh[0]
    return d


class Demand:
    def __init__(self):
        pc = pd.read_csv(RAW / "postcodes.csv", usecols=["postcode", "lat", "lon", "lsoa", "msoa"])
        cl = pc.groupby("lsoa")[["lat", "lon"]].mean()
        occ, qual = pivot("lsoa_occ", "c2021_occ_10"), pivot("lsoa_quals", "c2021_hiqual_8")
        age, ten = pivot("lsoa_age", "c2021_age_19"), pivot("lsoa_tenure", "c2021_tenure_9")
        t = pd.DataFrame({
            "occ_n": occ[1] + occ[2], "occ_d": occ[0],
            "deg_n": qual[6], "deg_d": qual[0],
            "yg_n": age[6] + age[7] + age[8], "yg_d": age[0],
            "rn_n": ten[1004], "rn_d": ten[0]}).join(cl, how="inner").dropna()
        sh, pop = ethnic_shares()
        self.eth = sh.join(pop.rename("pop"), how="inner").join(cl, how="inner").dropna()
        self.et = cKDTree(xy(self.eth.lat, self.eth.lon))
        self.l = t
        self.lt = cKDTree(xy(t.lat, t.lon))
        ind = pd.read_csv(RAW / "msoa_industry.csv").pivot_table(
            index="GEOGRAPHY_CODE", columns="C2021_IND_88", values="OBS_VALUE", aggfunc="sum")
        mc = pc.groupby("msoa")[["lat", "lon"]].mean()
        m = pd.DataFrame({"d": ind[0], "fi": ind[1011], "tc": ind[1010] + ind[1013]}).join(mc, how="inner").dropna()
        self.m = m
        self.mt = cKDTree(xy(m.lat, m.lon))
        w = pd.read_csv(RAW / "lsoa11_workplace_pop.csv").rename(columns={"GEOGRAPHY_CODE": "lsoa", "OBS_VALUE": "wp"})
        w = w.merge(cl.reset_index(), on="lsoa", how="inner")
        self.w = w
        self.wt = cKDTree(xy(w.lat, w.lon))
        # rents by borough
        import openpyxl
        ws = openpyxl.load_workbook(RAW / "pipr-2026-09.xlsx", read_only=True)["Table 1"]
        rows = list(ws.iter_rows(min_row=3, values_only=True))
        hdr = rows[0]
        ix = {h: i for i, h in enumerate(hdr)}
        latest = {}
        for r in rows[1:]:
            if r[1] and str(r[1]).startswith("E09") and (r[1] not in latest or r[0] > latest[r[1]][0]):
                latest[r[1]] = r
        num = lambda v: float(v) if isinstance(v, (int, float)) else None
        self.rent = {r[2]: (num(r[ix["Rental price flat maisonette"]]), num(r[ix["Annual change flat maisonette"]]))
                     for r in latest.values()}
        lad = json.loads((RAW / "london_lad.geojson").read_text())["features"]
        self.polys = [shape(f["geometry"]) for f in lad]
        self.names = [f["properties"]["LAD24NM"] for f in lad]
        self.tree = STRtree(self.polys)
        self.month = max(r[0] for r in latest.values()).strftime("%Y-%m")

    def borough(self, lat, lon):
        i = self.tree.query(Point(lon, lat), predicate="within")
        return self.names[i[0]] if len(i) else None

    def at(self, lat, lon):
        p = xy([lat], [lon])[0]
        out = {}
        ix = self.lt.query_ball_point(p, 1000)
        if ix:
            s = self.l.iloc[ix][["occ_n", "occ_d", "deg_n", "deg_d", "yg_n", "yg_d", "rn_n", "rn_d"]].sum()
            if s.occ_d >= 300:
                out["pr"] = round(float(100 * s.occ_n / s.occ_d), 1)
                out["dg"] = round(float(100 * s.deg_n / s.deg_d), 1)
                out["yg"] = round(float(100 * s.yg_n / s.yg_d), 1)
                out["rn"] = round(float(100 * s.rn_n / s.rn_d), 1)
        ex = self.et.query_ball_point(p, 1000)
        if ex:
            e = self.eth.iloc[ex]
            if e["pop"].sum() >= 500:
                w = e["pop"] / e["pop"].sum()
                out["eth"] = {k: round(float((e[k] * w).sum()), 1) for k in ETH_ALL}
        jx = self.mt.query_ball_point(p, 1500)
        if jx:
            s = self.m.iloc[jx][["d", "fi", "tc"]].sum()
            if s.d >= 300:
                out["fi"] = round(float(100 * s.fi / s.d), 1)
                out["tc"] = round(float(100 * s.tc / s.d), 1)
        wx = self.wt.query_ball_point(p, 2000)
        out["jb"] = round(float(self.w.iloc[wx].wp.sum()) / 1000, 1) if wx else 0.0
        b = self.borough(lat, lon)
        r = self.rent.get(b)
        if r and r[0]:
            out["rent"] = int(r[0])
            if r[1] is not None:
                out["rg"] = round(r[1], 1)
        return out
