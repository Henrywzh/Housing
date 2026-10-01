"""Inline the processed data into the map template and emit a standalone HTML page."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
tpl = (ROOT / "web" / "template.html").read_text()
mapd = (ROOT / "data" / "processed" / "map_data.json").read_text()
geo = (ROOT / "data" / "processed" / "london_boroughs.geojson").read_text()
ppd_path = ROOT / "data" / "processed" / "ppd_metrics.json"
ppd = ppd_path.read_text() if ppd_path.exists() else '{"areas":{}}'
sub_path = ROOT / "data" / "processed" / "submarkets.json"
sub = sub_path.read_text() if sub_path.exists() else '{"submarkets":{}}'

for blob, name in ((mapd, "map_data.json"), (geo, "geojson"), (ppd, "ppd_metrics.json"), (sub, "submarkets.json")):
    if "</script" in blob.lower():
        raise SystemExit(f"{name} contains a closing script tag; cannot inline")

out = (tpl.replace("__MAP_DATA__", mapd)
          .replace("__GEO_DATA__", geo)
          .replace("__PPD_DATA__", ppd)
          .replace("__SUB_DATA__", sub))
dest = ROOT / "london_housing_map.html"
dest.write_text(out)
print(f"{dest}  {dest.stat().st_size/1e6:.2f} MB")

# The same page as a supporting file of the Zone 1-4 map, which shows it under
# its own tab. A published page gets a document skeleton wrapped round it; a
# supporting file is served as-is, so it brings its own or renders in quirks mode.
web = ROOT / "web" / "data" / "trend.html"
web.parent.mkdir(parents=True, exist_ok=True)
web.write_text('<!doctype html>\n<html lang="zh"><head>\n'
               '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
               + out + "\n</html>\n")
print(f"{web}  {web.stat().st_size/1e6:.2f} MB")

# --- guard: every metric the UI offers must exist in the payload -------------
import json, re
data = json.loads(mapd)
keys = set()
for a in data["areas"].values():
    keys |= set(a.keys())
# point-in-time metrics (crime, census, earnings) live alongside the monthly panel
for a in (data.get("social") or {}).values():
    keys |= set(a.keys())
declared = set(re.findall(r"\{k:'([a-z0-9_]+)'", tpl))
missing = sorted(declared - keys)
if missing:
    raise SystemExit(f"FAIL: metrics declared in the UI but absent from map_data.json: {missing}")
print(f"metrics checked  : {len(declared)} declared, all present")
