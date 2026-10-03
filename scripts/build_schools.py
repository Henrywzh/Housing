"""London's state primary and secondary schools, with how good they are and how to get in.

Three public sources joined on the school's URN:

  Ofsted    "State-funded schools inspections and outcomes", 31 March 2026. Until
            September 2024 a school got one overall grade (1 Outstanding .. 4
            Inadequate); from November 2025 it gets a report card of several areas on
            a five-point scale and no overall grade. The data carries both, so a school
            shows whichever it last had, with the date, and one inspected a long time
            ago shows that too. Ungraded visits ("School remains Good") are used only
            where there is nothing else.
  Results   Key stage 2 reading-writing-maths at the expected standard (primary,
            2024/25) and Attainment 8 (secondary, 2024/25) with Progress 8 from
            2023/24 -- it cannot be calculated for the two years after, because of the
            gap in the pupils' starting point. Attainment follows the intake as much as
            the teaching; Progress 8 is the fairer one.
  Admissions  Ofsted's flag for selective schools, and the school's religious
            character. Where a school admits is decided by its own oversubscription
            criteria and, for most London primaries, by how far away the last child
            offered lived. Neither is published nationally: the councils print them in
            their admissions booklets, so this file does not claim a catchment.

Position comes from the school's postcode, not the Easting and Northing in the
register, because there is no projection library here and the postcode file already
has what the rest of the map uses.
"""
import json, pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SCH = RAW / "schools"
OUT = ROOT / "web" / "data" / "schools.json"
BOX = (-0.57, 51.27, 0.31, 51.71)

RC = {"Exceptional": 4, "Strong standard": 3, "Expected standard": 2, "Needs attention": 1, "Urgent improvement": 0}
RC_SCORE = {4: 1.0, 3: 0.85, 2: 0.65, 1: 0.3, 0: 0.0}
OEIF = {"1": ("Outstanding", 1.0), "2": ("Good", 0.8), "3": ("Requires improvement", 0.4), "4": ("Inadequate", 0.0)}
UNGRADED = {"School remains Outstanding": 1.0, "School remains Good": 0.8, "Standards maintained": 0.8,
            "Improved significantly": 0.75}


def geocode(pcs):
    """postcodes.io, 100 at a time; answers are kept in data/raw/schools/postcodes_io.json."""
    import urllib.request
    f = SCH / "postcodes_io.json"
    have = json.loads(f.read_text()) if f.exists() else {}
    todo = [c for c in pcs if c not in have]
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        req = urllib.request.Request("https://api.postcodes.io/postcodes", data=json.dumps({"postcodes": chunk}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "housing-research"})
        for r in json.load(urllib.request.urlopen(req, timeout=60))["result"]:
            q = r["result"]
            have[r["query"].upper()] = [q["latitude"], q["longitude"]] if q and q.get("latitude") else None
    f.write_text(json.dumps(have))
    return {c: have[c] for c in pcs if have.get(c)}


def ym(s):
    try:
        d, m, y = str(s).split("/")
        return f"{y}-{m}"
    except ValueError:
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    o = pd.read_csv(SCH / "ofsted_2026-03.csv", low_memory=False, encoding="latin-1")
    o = o[(o["Region"] == "London") & o["Ofsted phase"].isin(["Primary", "Secondary"])].copy()
    pc = pd.read_csv(RAW / "postcodes.csv", usecols=["postcode", "lat", "lon"]).drop_duplicates("postcode").set_index("postcode")
    o["pc"] = o["Postcode"].astype(str).str.upper().str.strip()
    o = o.join(pc, on="pc")
    # the postcode file only holds postcodes that have had a sale; a school's often has not
    miss = sorted(set(o[o.lat.isna()].pc))
    if miss:
        o = o.set_index("pc")
        got = geocode(miss)
        for c in miss:
            if c in got:
                o.loc[c, ["lat", "lon"]] = got[c]
        o = o.reset_index()
    o = o[o.lat.between(BOX[1], BOX[3]) & o.lon.between(BOX[0], BOX[2])]

    k2 = pd.read_csv(SCH / "ks2_london.csv", dtype=str)
    t = k2[(k2.breakdown_topic == "All pupils") & (k2.subject == "Reading, writing and maths")]
    ks2 = t.set_index(t.school_urn.astype(float).astype(int))["expected_standard_pupil_percent"].map(num)
    a = k2[(k2.breakdown_topic == "Average (2023 to 2025)") & (k2.subject == "Reading, writing and maths")]
    ks2avg = a.set_index(a.school_urn.astype(float).astype(int))["expected_standard_pupil_percent"].map(num)
    k4 = pd.read_csv(SCH / "ks4_london.csv", dtype=str)
    k4["urn"] = k4.school_urn.astype(float).astype(int)
    a8 = k4[k4.time_period == "202425"].set_index("urn")["attainment8_average"].map(num)
    p8 = k4[k4.time_period == "202324"].set_index("urn")["progress8_average"].map(num)

    # a school can appear twice (e.g. a merger year): keep the first
    ks2, ks2avg, a8, p8 = (x[~x.index.duplicated()] for x in (ks2, ks2avg, a8, p8))
    rows = []
    for _, r in o.iterrows():
        urn = int(r["URN"])
        prim = r["Ofsted phase"] == "Primary"
        # Ofsted: the newer report card if there is one, else the old overall grade, else an ungraded visit
        rc = [RC.get(r[c]) for c in ("Achievement", "Curriculum and teaching", "Inclusion",
                                      "Attendance and behaviour", "Leadership and governance")]
        label, score, when, kind = None, None, None, None
        if any(v is not None for v in rc):
            vs = [v for v in rc if v is not None]
            score = float(np.mean([RC_SCORE[v] for v in vs]))
            label, kind, when = "report card", "rc", ym(r["Inspection start date"])
        elif str(r["Latest OEIF overall effectiveness"]) in OEIF:
            label, score = OEIF[str(r["Latest OEIF overall effectiveness"])]
            kind, when = "oeif", ym(r["Inspection start date of latest OEIF graded inspection"])
        else:
            u = str(r["Ungraded inspection overall outcome"]).split(" - ")[0].split(" (")[0]
            if u in UNGRADED:
                label, score, kind, when = u.replace("School ", ""), UNGRADED[u], "ung", ym(r["Date of latest ungraded inspection"])
        res = (ks2.get(urn), ks2avg.get(urn)) if prim else (a8.get(urn), p8.get(urn))
        rows.append({
            "u": urn, "n": r["School name"], "y": round(float(r["lat"]), 5), "x": round(float(r["lon"]), 5),
            "p": "P" if prim else "S", "la": r["Local authority"],
            "ol": label, "ok": kind, "od": when, "os": None if score is None else round(score, 2),
            "rc": [v for v in rc] if kind == "rc" else None,
            "r": res[0], "r2": res[1],
            "sel": r["Admissions policy"] == "Selective",
            "fa": r["Designated religious character"] if r["Faith grouping"] != "Non-faith" else None,
            "np": None if pd.isna(r["Total number of pupils"]) else int(r["Total number of pupils"]),
            "ty": r["Type of education"], "sf": r["Sixth form"] == "Has a sixth form"})
    df = pd.DataFrame(rows)
    # one 0-1 quality number per school: Ofsted and results ranked within the phase, averaged
    for ph in "PS":
        m = df.p == ph
        if ph == "P":
            res = df.loc[m, "r"].where(df.loc[m, "r"].notna(), df.loc[m, "r2"])
        else:
            # Progress 8 where it exists is the fairer measure; Attainment 8 otherwise
            res = df.loc[m, "r"].astype(float)
            pr = df.loc[m, "r2"].astype(float)
            res = (res.rank(pct=True) + pr.rank(pct=True)) / 2
            res = res.where(pr.notna(), df.loc[m, "r"].astype(float).rank(pct=True))
            df.loc[m, "rr"] = res
        if ph == "P":
            df.loc[m, "rr"] = res.astype(float).rank(pct=True)
    q = df[["os", "rr"]].astype(float)
    df["q"] = q.mean(axis=1, skipna=True).round(3)
    df["rr"] = df["rr"].round(3)
    recs = []
    for r in df.to_dict("records"):
        recs.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in r.items()
                     if v is not None and not (isinstance(v, float) and np.isnan(v))})
    OUT.write_text(json.dumps(recs, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(recs):,} schools -> {OUT.name} ({OUT.stat().st_size/1e3:.0f} KB); "
          f"{sum('q' in r for r in recs):,} with a quality number; "
          f"Ofsted kinds: {df.ok.value_counts().to_dict()}; selective {int(df.sel.sum())}")


if __name__ == "__main__":
    main()
