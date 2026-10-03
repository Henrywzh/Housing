"""Refresh everything that moves month to month, rebuild, check, and say what changed.

    python3 scripts/update_monthly.py              # the monthly job: prices, rents, rates, radar, trend page
    python3 scripts/update_monthly.py --devs       # also the developers' listings and the commute times (slow)
    python3 scripts/update_monthly.py --ppd        # also Price Paid (re-reads the current year) and what is built on it
    python3 scripts/update_monthly.py --all
    python3 scripts/update_monthly.py --if-new     # do nothing, quickly, unless a new Land Registry month is out
    python3 scripts/update_monthly.py --dry-run    # list the steps

What it does, in order, and what each is for:

  1. hpi       newest UK-HPI-full-file-YYYY-MM.csv from Land Registry (the file name is the month)
  2. pipr      newest ONS Price Index of Private Rents workbook, read off ONS's dataset page
  3. macro     Bank of England rates / approvals / yield and swap curves, Nationwide, HMRC (fetch_macro.py)
  4. dataset   the borough price + rent panel (build_dataset.py)
  5. trend     the price-trend page (build_site.py)
  6. radar     backtest, forecast and the radar page (build_radar.py, radar_page.py)
  with --ppd:   fetch_ppd, build_ppd_aggregates, build_ppd_agg, build_sector_agg, build_schemes first
  with --devs:  Barratt and the other developers, then TfL times to the three workplaces
  then, when the map's own data moved: build_web_payload.py

Every step's output goes to data/processed/logs/. The files the published page serves are copied to
data/processed/prev/ before anything is rebuilt, so a bad month can be rolled back by copying them
back. A step that fails stops the steps that depend on it and nothing else.

Publishing is not done here: an Artifact can only be republished from a Claude session. The last line
of the run lists the files that changed since the last publish, which is what to hand over;
`--mark-published` records the current state once that is done.

The Land Registry index appears around the third Wednesday of the month, with ONS rents the same day,
Bank of England approvals in the first days, HMRC at the end. Running this on the 22nd catches the first.
"""
import argparse, datetime as dt, hashlib, json, pathlib, re, shutil, subprocess, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, PROC, WEB = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "web" / "data"
SITE = ROOT / "web"                       # PUBLISHED paths are relative to this
LOGS, PREV = PROC / "logs", PROC / "prev"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) housing-research"}
PY = sys.executable

# files the published page serves, relative to web/
PUBLISHED = ["zone14.html"] + [f"data/{n}" for n in (
    "radar.html", "radar.json", "trend.html", "analysis.html", "analysis.json", "schemes.json", "stations.json",
    "devs.json", "lsoa.geojson", "breaks.json", "schools.json", "shortlist.json")]
MANIFEST = PROC / "published_manifest.json"


# ----------------------------------------------------------------------------- fetchers
def http(url, method="GET", tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read() if method == "GET" else (r.status, int(r.headers.get("Content-Length") or 0))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and a < tries - 1:
                time.sleep(8 * (a + 1)); continue
            raise
        except Exception:
            if a == tries - 1:
                raise
            time.sleep(5)


def latest_hpi_month():
    """The newest month for which Land Registry has published the full file (it is the month the data runs to)."""
    today = dt.date.today()
    for back in range(0, 5):
        y, m = today.year, today.month - back
        while m < 1:
            m += 12; y -= 1
        ym = f"{y}-{m:02d}"
        if http(f"https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data/UK-HPI-full-file-{ym}.csv", "HEAD"):
            return ym
    return None


def step_hpi():
    ym = latest_hpi_month()
    if not ym:
        raise RuntimeError("no UK HPI file found for the last five months")
    f = RAW / f"UK-HPI-full-file-{ym}.csv"
    if f.exists():
        print(f"already have {f.name}"); return "unchanged"
    data = http(f"https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data/UK-HPI-full-file-{ym}.csv")
    if not data or b"AreaCode" not in data[:400]:
        raise RuntimeError("downloaded HPI file does not look like the HPI")
    f.write_bytes(data)
    print(f"downloaded {f.name} ({len(data)/1e6:.0f} MB)"); return "new"


def step_pipr():
    page = http("https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/priceindexofprivaterentsukmonthlypricestatistics")
    if not page:
        raise RuntimeError("ONS rents dataset page not found")
    links = re.findall(r'href="(/file\?uri=[^"]*priceindexofprivaterentsukmonthlypricestatistics/(\d{1,2})([a-z]+)(\d{4})/[^"]*\.xlsx)"', page.decode("utf8", "ignore"))
    if not links:
        raise RuntimeError("no rents workbook links on the ONS page")
    mon = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
    best = max(links, key=lambda l: (int(l[3]), mon.get(l[2], 0), int(l[1])))
    ym = f"{best[3]}-{mon[best[2]]:02d}"
    f = RAW / f"pipr-{ym}.xlsx"
    if f.exists():
        print(f"already have {f.name}"); return "unchanged"
    data = http("https://www.ons.gov.uk" + best[0].replace("&amp;", "&"))
    if not data or data[:2] != b"PK":
        raise RuntimeError("downloaded rents file is not a workbook")
    f.write_bytes(data)
    print(f"downloaded {f.name} ({len(data)/1e6:.1f} MB)"); return "new"


# ----------------------------------------------------------------------------- plan
class Step:
    def __init__(self, name, cmd=None, fn=None, needs=(), group="core", note=""):
        self.name, self.cmd, self.fn, self.needs, self.group, self.note = name, cmd, fn, set(needs), group, note


def script(name, *args):
    return [PY, str(ROOT / "scripts" / name), *args]


def plan(a):
    S = [Step("hpi", fn=step_hpi, note="Land Registry UK HPI"), Step("pipr", fn=step_pipr, note="ONS private rents")]
    if a.ppd or a.all:
        S += [Step("ppd", script("fetch_ppd.py"), group="ppd", note="Price Paid, current year re-read"),
              Step("ppd_agg1", script("build_ppd_aggregates.py"), needs=["ppd"], group="ppd"),
              Step("ppd_agg2", script("build_ppd_agg.py"), needs=["ppd_agg1"], group="ppd"),
              Step("sector", script("build_sector_agg.py"), needs=["ppd_agg2"], group="ppd")]
    S += [Step("macro", script("fetch_macro.py", "--refresh"), note="Bank of England, Nationwide, HMRC"),
          Step("dataset", script("build_dataset.py"), needs=["hpi", "pipr"] + (["sector"] if (a.ppd or a.all) else []), note="borough price + rent panel"),
          Step("trend", script("build_site.py"), needs=["dataset"], note="price-trend page"),
          Step("radar", script("build_radar.py"), needs=["dataset", "macro"], note="backtest + forecast"),
          Step("radar_page", script("radar_page.py"), needs=["radar"])]
    if a.devs or a.all:
        S += [Step("barratt", script("fetch_barratt.py", "--refresh"), group="devs"),
              Step("developers", script("fetch_developers.py", "--refresh"), group="devs")]
        S += [Step(f"commute_{k}", script("fetch_commute.py", k), needs=["barratt", "developers"], group="devs", note="TfL, only places not seen before") for k in ("gp", "cw", "ls")]
    if a.ppd or a.devs or a.all:
        S += [Step("schemes", script("build_schemes.py"), needs=["ppd"] if (a.ppd or a.all) else [], group="map"),
              Step("payload", script("build_web_payload.py"), needs=["schemes"] + ([f"commute_{k}" for k in ("gp", "cw", "ls")] if (a.devs or a.all) else []), group="map",
                   note="stations, schemes, devs for the map")]
    return S


# ----------------------------------------------------------------------------- state and checks
def snapshot():
    s = {}
    try:
        import csv
        rows = list(csv.DictReader((PROC / "london_panel.csv").open()))
        lon = [r for r in rows if r["code"] == "E12000007" and r["price"]]
        s["hpi_month"], s["london_price"] = lon[-1]["ym"], float(lon[-1]["price"])
        rent = [r for r in rows if r["code"] == "E12000007" and r["rent"]]
        s["rent_month"], s["london_rent"] = rent[-1]["ym"], float(rent[-1]["rent"])
    except Exception:
        pass
    try:
        r = json.loads((WEB / "radar.json").read_text())
        s.update(forecast_p50=r["forecast"]["p50"], forecast_p10=r["forecast"]["p10"], forecast_p90=r["forecast"]["p90"],
                 mort2y=r["mort_now"], mort_month=r["mort_now_month"], bank_rate=r["bank_now"],
                 fixed_in_12m=r["rate_path"][-1]["fixed2y"], approvals=r["current"].get("approvals", {}).get("value"))
    except Exception:
        pass
    return s


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def changed_since_publish():
    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    return [f for f in PUBLISHED if (SITE / f).exists() and old.get(f) != sha(SITE / f)]


def checks():
    bad = []
    t = WEB / "trend.html"
    if not t.exists() or t.stat().st_size < 3e6:
        bad.append("trend.html missing or too small")
    try:
        r = json.loads((WEB / "radar.json").read_text())
        for k in ("forecast", "backtest", "rate_path", "current", "london"):
            if k not in r:
                bad.append(f"radar.json lacks {k}")
        if not (-60 < r["forecast"]["p50"] < 60):
            bad.append("forecast median is implausible")
    except Exception as e:
        bad.append(f"radar.json unreadable: {e}")
    if not (WEB / "radar.html").exists():
        bad.append("radar.html missing")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devs", action="store_true"); ap.add_argument("--ppd", action="store_true"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--if-new", action="store_true", help="exit early unless Land Registry has a month we do not")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--mark-published", action="store_true")
    a = ap.parse_args()
    if a.mark_published:
        MANIFEST.write_text(json.dumps({f: sha(SITE / f) for f in PUBLISHED if (SITE / f).exists()}, indent=1))
        print("recorded the current files as published"); return 0
    steps = plan(a)
    if a.dry_run:
        for s in steps:
            print(f"  {s.name:12s} [{s.group}] {' '.join(s.cmd[1:])[:70] if s.cmd else s.fn.__name__:70s} needs {sorted(s.needs) or '-'}  {s.note}")
        return 0
    if a.if_new:
        ym = latest_hpi_month()
        have = sorted(p.stem[-7:] for p in RAW.glob("UK-HPI-full-file-*.csv"))
        if ym and have and ym <= have[-1]:
            print(f"no new Land Registry month (latest {ym}, have {have[-1]}); nothing to do"); return 0
    LOGS.mkdir(parents=True, exist_ok=True); PREV.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    logf = (LOGS / f"update_{stamp}.log").open("w")
    before = snapshot()
    for f in PUBLISHED:                                   # something to roll back to
        if (SITE / f).exists():
            (PREV / f.replace("/", "__")).write_bytes((SITE / f).read_bytes())
    status = {}
    print(f"monthly update {stamp}: {len(steps)} steps")
    for s in steps:
        blocked = [n for n in s.needs if status.get(n, ("ok",))[0] == "failed" or status.get(n, ("ok",))[0] == "skipped"]
        if blocked:
            status[s.name] = ("skipped", f"needs {blocked[0]}"); print(f"  - {s.name:12s} skipped (needs {blocked[0]})"); continue
        t0 = time.time()
        logf.write(f"\n===== {s.name} =====\n"); logf.flush()
        try:
            if s.fn:
                import contextlib, io
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    res = s.fn()
                logf.write(buf.getvalue()); detail = res or ""
            else:
                p = subprocess.run(s.cmd, cwd=ROOT, capture_output=True, text=True, timeout=7200)
                logf.write(p.stdout + p.stderr)
                if p.returncode:
                    raise RuntimeError((p.stderr.strip().splitlines() or ["exit " + str(p.returncode)])[-1][:200])
                detail = (p.stdout.strip().splitlines() or [""])[-1][:90]
            status[s.name] = ("ok", detail); print(f"  ✓ {s.name:12s} {time.time()-t0:5.1f}s  {detail}")
        except Exception as e:
            status[s.name] = ("failed", str(e)); logf.write(f"FAILED: {e}\n"); print(f"  ✗ {s.name:12s} {time.time()-t0:5.1f}s  {e}")
    logf.close()
    after = snapshot()
    bad = checks()
    print("\nwhat changed")
    keys = [("hpi_month", "房价数据到"), ("london_price", "伦敦均价 £"), ("rent_month", "租金数据到"), ("london_rent", "伦敦均租 £"), ("bank_rate", "Bank Rate %"),
            ("mort2y", "2 年固定按揭 %"), ("fixed_in_12m", "市场隐含 12 个月后 %"), ("forecast_p50", "12 个月预测中位 %"), ("forecast_p10", "  下沿 %"), ("forecast_p90", "  上沿 %")]
    for k, label in keys:
        b, c = before.get(k), after.get(k)
        if c is None:
            continue
        mark = "" if b == c else ("   (new)" if b is None else f"   (was {b:,.2f})" if isinstance(b, float) else f"   (was {b})")
        print(f"  {label:20s} {c:,.2f}{mark}" if isinstance(c, float) else f"  {label:20s} {c}{mark}")
    if bad:
        print("\nCHECKS FAILED:", *bad, sep="\n  - ")
    failed = [n for n, (st, _) in status.items() if st == "failed"]
    ch = changed_since_publish()
    print(f"\n{len(failed)} failed, {sum(1 for v in status.values() if v[0]=='skipped')} skipped; log: {logf.name}")
    print("files changed since the last publish:", ", ".join(ch) if ch else "none")
    if ch and not failed and not bad:
        print("to publish: ask Claude to republish the Artifact with these files, then run  update_monthly.py --mark-published")
    (PROC / "update_log.json").write_text(json.dumps({"at": stamp, "status": {k: list(v) for k, v in status.items()}, "before": before, "after": after, "checks": bad}, indent=1))
    return 1 if failed or bad else 0


if __name__ == "__main__":
    sys.exit(main())
