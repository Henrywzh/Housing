"""How much new housing is landing near a place: what has been sold, and what is coming.

Three measures, each answering a different question, because no single public
source covers London evenly:

  sold   New-build flat sales within 1 km, 2023-25 against 2020-22 (Price Paid;
         complete and uniform across London, but it only sees a flat once it
         completes and is registered). Divided by the households already living
         within 1 km (2021 Census) this is the share of the neighbourhood that
         arrived new in three years -- the supply a resale flat competes with.
  pipe   Homes on the Brownfield Land Register within 1 km that hold, or are
         waiting on, planning permission (fetch_supply.py). Councils fill this in
         unevenly -- Tower Hamlets lists 27 sites and no homes, Ealing lists 16
         homes -- so it is only used where the borough's own register looks
         complete, and otherwise reported as unknown, not as zero.
  devs   Developments on sale now within 1 km (the developers' own sites).
"""
import json, math, pathlib
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely import STRtree

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
KX = 111_320.0 * math.cos(math.radians(51.5))
KY = 111_320.0
R = 1000.0


def xy(lat, lon):
    return np.column_stack([np.asarray(lon) * KX, np.asarray(lat) * KY])


class Supply:
    def __init__(self):
        devs = []
        for f, key in (((RAW / "barratt.json"), "developments"), ((RAW / "developers.json"), "developments")):
            if f.exists():
                devs += [d for d in json.loads(f.read_text())[key] if d.get("lat") is not None]
        pc = pd.read_csv(RAW / "postcodes.csv", usecols=["postcode", "lat", "lon", "lsoa"])
        ppd = pd.read_csv(RAW / "london_ppd.csv", usecols=["date", "postcode", "ptype", "newbuild"])
        nb = ppd[(ppd.ptype == "F") & (ppd.newbuild == "Y")].merge(pc, on="postcode", how="inner")
        yr = nb.date.str[:4].astype(int)
        self.t_new = cKDTree(xy(nb[yr.between(2023, 2025)].lat, nb[yr.between(2023, 2025)].lon))
        self.t_old = cKDTree(xy(nb[yr.between(2020, 2022)].lat, nb[yr.between(2020, 2022)].lon))
        # households per LSOA, placed at the mean of the LSOA's postcodes
        hh = pd.read_csv(RAW / "lsoa_households.csv")
        hh = hh[hh["C2021_HH_1"].astype(str) == "0"].rename(
            columns={"GEOGRAPHY_CODE": "lsoa", "OBS_VALUE": "hh"})[["lsoa", "hh"]]
        c = pc.groupby("lsoa")[["lat", "lon"]].mean().reset_index().merge(hh, on="lsoa")
        self.t_hh = cKDTree(xy(c.lat, c.lon))
        self.hh = c.hh.to_numpy(float)
        # register
        b = json.loads((RAW / "supply" / "brownfield.json").read_text())
        b = [x for x in b if not x.get("end-date") and x.get("point")]
        lad = json.loads((RAW / "london_lad.geojson").read_text())["features"]
        self.polys = [shape(f["geometry"]) for f in lad]
        self.names = [f["properties"]["LAD24NM"] for f in lad]
        self.tree = STRtree(self.polys)
        pts, cls, units = [], [], []
        stat = defaultdict(lambda: [0, "0000"])
        for x in b:
            lo, la = x["point"][7:-1].split()
            lo, la = float(lo), float(la)
            try:
                u = int(float(x.get("maximum-net-dwellings") or x.get("minimum-net-dwellings") or 0))
            except ValueError:
                u = 0
            s = (x.get("planning-permission-status") or "").lower()
            k = ("p" if s in ("permissioned", "started", "prior approval given") or "permission" in s and "not" not in s
                 else "q" if "pending" in s or "awaiting" in s or "submitted" in s or "application" in s else "n")
            borough = self.borough(la, lo)
            if borough is None:
                continue
            stat[borough][0] += u
            stat[borough][1] = max(stat[borough][1], (x.get("entry-date") or "")[:4])
            pts.append((la, lo)); cls.append(k); units.append(u)
        # a borough's register is trusted only if it is recent and has real numbers
        self.ok = {n: (v[1] >= "2022" and v[0] >= 2000) for n, v in stat.items()}
        pts = np.array(pts)
        self.t_pipe = cKDTree(xy(pts[:, 0], pts[:, 1]))
        self.cls, self.units = np.array(cls), np.array(units)
        self.dev_t = cKDTree(xy([d["lat"] for d in devs], [d["lon"] for d in devs])) if len(devs) else None

    def borough(self, lat, lon):
        i = self.tree.query(Point(lon, lat), predicate="within")
        return self.names[i[0]] if len(i) else None

    def at(self, lat, lon):
        p = xy([lat], [lon])[0]
        n3 = len(self.t_new.query_ball_point(p, R))
        n3p = len(self.t_old.query_ball_point(p, R))
        ix = self.t_hh.query_ball_point(p, R)
        hh = float(self.hh[ix].sum()) if ix else 0.0
        out = {"n3": n3, "n3p": n3p, "hh": int(round(hh, -1))}
        if hh >= 500:
            out["r"] = round(100 * n3 / hh, 1)           # new flats sold 2023-25 per 100 households
        b = self.borough(lat, lon)
        if b is not None and self.ok.get(b):
            ix = self.t_pipe.query_ball_point(p, R)
            out["pu"] = int(sum(self.units[i] for i in ix if self.cls[i] == "p"))
            out["pq"] = int(sum(self.units[i] for i in ix if self.cls[i] == "q"))
        if self.dev_t is not None:
            out["dv"] = len(self.dev_t.query_ball_point(p, R))
        return out
