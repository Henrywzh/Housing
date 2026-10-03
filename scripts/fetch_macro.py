"""The macro series that lead London house prices, fetched and put on one monthly table.

Why these, and what each is for:

  Bank Rate, 2- and 5-year fixed mortgage rates (Bank of England)   the price of money for a buyer
  2- and 5-year gilt yields, 2- and 5-year SONIA swap rates          where the market thinks rates go;
      the swap forward curve is the market's own path for Bank Rate, which is what a fixed rate prices off
  Mortgage approvals for house purchase (Bank of England)             led completions by two to three
      months, and is the best single early read on whether the market is picking up
  Nationwide House Price Index, UK (monthly)                          out about a month before the
      official index, built from the lender's own approvals
  HMRC residential transactions (England, UK seasonally adjusted)     from stamp duty returns, so earlier
      than Land Registry
  RICS Residential Market Survey                                      only published as PDF, and the London
      figures are in charts, so only the narrative headline balances can be read; see rics.csv

Each source is downloaded once and kept under data/raw/macro/, so the build runs offline after the
first time unless --refresh is given. Everything is stamped with the month it refers to, not the month
it was published: the lead and lag between them is handled in build_radar.py, where it matters.
"""
import argparse, glob, io, json, pathlib, re, subprocess, sys, urllib.request, zipfile
import numpy as np
import pandas as pd
import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "macro"
RAW.mkdir(parents=True, exist_ok=True)
PROC = ROOT / "data" / "processed"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) housing-research"}

IADB = {  # code -> short name
    "IUDBEDR": "bank_rate", "LPMVTVX": "approvals", "LPMB4B3": "remortgage",
    "IUMBV34": "mort2y75", "IUMB482": "mort2y90", "IUMBV42": "mort5y75", "IUDSNPY": "gilt5y",
}


def get(url, tries=3):
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()
        except Exception as e:
            if a == tries - 1:
                raise
            print(f"  retry {url[:80]}: {type(e).__name__}")


def cached(name, url, refresh):
    f = RAW / name
    if refresh or not f.exists() or f.stat().st_size < 1000:
        f.write_bytes(get(url))
    return f


def boe(refresh):
    """Daily or monthly Bank of England series -> month-end values."""
    f = RAW / "iadb.csv"
    if refresh or not f.exists():
        u = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/1993"
             "&Dateto=now&SeriesCodes=" + ",".join(IADB) + "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
        f.write_bytes(get(u))
    d = pd.read_csv(f)
    d["date"] = pd.to_datetime(d["DATE"], format="%d %b %Y")
    d["ym"] = d["date"].dt.strftime("%Y-%m")
    d = d.rename(columns=IADB).drop(columns=["DATE"])
    # daily series (Bank Rate, gilt yield): the month's last observation. Monthly series: the one value.
    return d.groupby("ym")[list(IADB.values())].last()


def curves(refresh):
    """BoE gilt and SONIA-swap (OIS) curves, month-end: spot 2y/5y and, for swaps, forward 1y/2y/3y/5y."""
    out = {}
    for tag, zipname in (("glc", "glcnominalmonthedata"), ("ois", "oismonthedata")):
        z = cached(f"{zipname}.zip", f"https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/{zipname}.zip", refresh)
        with zipfile.ZipFile(z) as zf:
            names = sorted(n for n in zf.namelist() if n.endswith(".xlsx"))
            for n in names:
                wb = openpyxl.load_workbook(io.BytesIO(zf.read(n)), read_only=True, data_only=True)
                for sheet, key in (("4. spot curve", "spot"), ("2. fwd curve", "fwd")):
                    if sheet not in wb.sheetnames or (tag == "glc" and key == "fwd"):
                        continue
                    rows = list(wb[sheet].iter_rows(values_only=True))
                    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "years:")
                    years = [float(x) for x in rows[hdr][1:] if isinstance(x, (int, float))]
                    for r in rows[hdr + 1:]:
                        if not r or r[0] is None or not hasattr(r[0], "strftime"):
                            continue
                        ym = r[0].strftime("%Y-%m")
                        vals = dict(zip(years, r[1:1 + len(years)]))
                        for y in (1, 2, 3, 5):
                            v = vals.get(float(y))
                            if isinstance(v, (int, float)):
                                out.setdefault(ym, {})[f"{tag}_{key}{y}y"] = float(v)
    return pd.DataFrame.from_dict(out, orient="index").sort_index()


def ois_forward_path(refresh):
    """The latest OIS instantaneous forward curve, as the market-implied Bank Rate path."""
    z = RAW / "oisddata.zip"
    z = cached("latest-yield-curve-data.zip", "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip", refresh)
    with zipfile.ZipFile(z) as zf:
        n = next(n for n in zf.namelist() if n.startswith("OIS daily"))
        wb = openpyxl.load_workbook(io.BytesIO(zf.read(n)), read_only=True, data_only=True)
    rows = list(wb["2. fwd curve"].iter_rows(values_only=True))
    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "years:")
    years = [float(x) for x in rows[hdr][1:] if isinstance(x, (int, float))]
    last = [r for r in rows[hdr + 1:] if r and hasattr(r[0], "strftime")][-1]
    return {"asof": last[0].strftime("%Y-%m-%d"),
            "path": [[y, round(float(v), 3)] for y, v in zip(years, last[1:1 + len(years)]) if isinstance(v, (int, float)) and y <= 6]}


def nationwide(refresh):
    """Nationwide monthly UK index. The file's address changes, so read it off the data page."""
    f = RAW / "nationwide_monthly.xlsx"
    if refresh or not f.exists():
        page = get("https://www.nationwidehousepriceindex.co.uk/resources/f/uk-data-series").decode("utf8", "ignore")
        for u in sorted(set(re.findall(r'https://cdn\.prgloo\.com/media/[0-9a-f]+\.xlsx', page))):
            try:
                x = pd.ExcelFile(io.BytesIO(get(u)))
            except Exception:
                continue
            if x.sheet_names == ["Monthly"]:
                f.write_bytes(get(u))
                break
        else:
            raise RuntimeError("Nationwide monthly workbook not found on the data page")
    d = pd.read_excel(f, sheet_name="Monthly")
    # columns: date, average price (£), index Q1 1993 = 100 (not adjusted), seasonally adjusted index, ...
    d = d.rename(columns={d.columns[0]: "date", d.columns[1]: "nw_price", d.columns[2]: "nw_idx", d.columns[3]: "nw_sa"})
    d["ym"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m")
    return d.set_index("ym")[["nw_price", "nw_idx", "nw_sa"]].dropna(how="all")


def hmrc(refresh):
    f = RAW / "hmrc_mpt.ods"
    if refresh or not f.exists():
        meta = json.loads(get("https://www.gov.uk/api/content/government/statistics/monthly-property-transactions-completed-in-the-uk-with-value-40000-or-above"))
        url = next(a["url"] for a in meta["details"]["attachments"] if a["url"].endswith(".ods") and "tables" in a["title"].lower())
        f.write_bytes(get(url))
    d = pd.read_excel(f, engine="odf", sheet_name="Residential_monthly", header=None)
    h = d.index[d[0] == "Month and year"][0]
    d = d.iloc[h + 1:, :7]
    d.columns = ["month", "hmrc_eng", "hmrc_sco", "hmrc_wal", "hmrc_ni", "hmrc_uk", "hmrc_uk_sa"]
    d = d[d["month"].astype(str).str.contains(r"\d{4}")]
    d["ym"] = pd.to_datetime(d["month"].astype(str).str.replace(r"\s*\[.*", "", regex=True), format="%B %Y").dt.strftime("%Y-%m")
    for c in d.columns[1:7]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["hmrc_provisional"] = d["month"].astype(str).str.contains("provisional")
    return d.set_index("ym").drop(columns=["month"])


def rics_latest():
    """The headline readings in the most recent RICS narrative (net balances, %). Hand-checkable and
    dated; there is no machine-readable series, and the London figures are only drawn as a chart."""
    f = RAW / "rics.json"
    return json.loads(f.read_text()) if f.exists() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    parts = {"boe": boe(a.refresh), "curves": curves(a.refresh), "nationwide": nationwide(a.refresh), "hmrc": hmrc(a.refresh)}
    for k, v in parts.items():
        print(f"{k:11s} {len(v):4d} months  {v.index.min()} .. {v.index.max()}  cols {list(v.columns)[:6]}")
    m = pd.concat(parts.values(), axis=1).sort_index()
    m.index.name = "ym"
    m.to_csv(PROC / "macro_monthly.csv")
    path = ois_forward_path(a.refresh)
    (PROC / "ois_path.json").write_text(json.dumps(path))
    print(f"macro_monthly.csv: {len(m)} months; OIS forward path as of {path['asof']}: "
          + ", ".join(f"{y:g}y {v:.2f}" for y, v in path["path"][:6]))


if __name__ == "__main__":
    main()
