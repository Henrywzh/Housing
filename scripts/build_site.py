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
