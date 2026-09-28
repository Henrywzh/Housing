"""London-wide LSOA base layer: Census 2021 population and generalised boundaries.

Crime counts on their own rank an area by how many people live in it. Rates need
a denominator on the same geography the crime is reported on -- 2021 LSOAs, which
is what data.police.uk uses.
"""
import json, pathlib, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "housing-research/1.0"}

# TS001, LSOA (TYPE151), residence type 0 = all usual residents. NOMIS caps a
# response at 25,000 rows and answers England-wide requests alphabetically, so we
# ask borough by borough instead of asking for every LSOA in the country.
POP = ("https://www.nomisweb.co.uk/api/v01/dataset/NM_2021_1.data.csv"
       "?geography={geo}&measures=20100&c2021_restype_3=0"
       "&select=geography_code,geography_name,obs_value")
SVC = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
       "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5/FeatureServer/0/query")
# Greater London's envelope, in WGS84. The extra margin costs a few hundred
# features that the borough-name filter then drops.
ENV = {"xmin": -0.55, "ymin": 51.24, "xmax": 0.35, "ymax": 51.72}
PAGE = 1000


def nomis(url, tries=5):
    for k in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()
            if r.strip():
                return r.decode().strip().splitlines()
            return []                      # a real empty result, not a failure
        except Exception as e:
            print(f"  retry {k+1} ({type(e).__name__})", flush=True)
            if k == tries - 1:
                raise
            time.sleep(10 * (k + 1))


def population():
    """One request per borough, cached, then a sweep for whatever the parent
    lookup missed. City of London answers an empty set to the borough-parent
    query, so its LSOAs have to be asked for by code."""
    out = RAW / "lsoa_pop21.csv"
    if out.exists() and out.stat().st_size > 1000:
        print("have lsoa_pop21.csv"); return
    cache = RAW / "nomis_pop"
    cache.mkdir(exist_ok=True)
    lads = [f["properties"]["LAD24CD"]
            for f in json.loads((RAW / "london_lad.geojson").read_text())["features"]]
    header, rows = None, []
    for i, lad in enumerate(lads, 1):
        f = cache / f"{lad}.csv"
        if not f.exists() or not f.read_text().strip():
            r = nomis(POP.format(geo=lad + "TYPE151"))
            f.write_text("\n".join(r))
        r = [x for x in f.read_text().splitlines() if x.strip()]
        if r:
            header = header or r[0]
            rows += r[1:]
        print(f"  {i}/{len(lads)} {lad}: {max(len(r)-1, 0)} LSOAs", flush=True)

    want = {f["properties"]["LSOA21CD"]
            for f in json.loads((RAW / "lsoa_london_bgc.geojson").read_text())["features"]}
    have = {x.split(",")[0].strip('"') for x in rows}
    gap = sorted(want - have)
    if gap:
        print(f"  {len(gap)} LSOAs not returned by any borough query; asking by code")
        for i in range(0, len(gap), 100):
            r = nomis(POP.format(geo=",".join(gap[i:i + 100])))
            rows += r[1:]
    out.write_text(header + "\n" + "\n".join(rows) + "\n")
    print(f"Census 2021 LSOA population: {len(rows):,} LSOAs")


def boundaries():
    out = RAW / "lsoa_london_bgc.geojson"
    if out.exists() and out.stat().st_size > 1000:
        print("have lsoa_london_bgc.geojson"); return
    boroughs = {f["properties"]["LAD24NM"]
                for f in json.loads((RAW / "london_lad.geojson").read_text())["features"]}
    feats, off = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "outFields": "LSOA21CD,LSOA21NM", "outSR": 4326, "f": "geojson",
            "geometry": json.dumps(ENV), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": off, "resultRecordCount": PAGE})
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{SVC}?{q}", headers=UA), timeout=300).read())
        got = d.get("features", [])
        feats += got
        print(f"  {len(feats):,} fetched", flush=True)
        if len(got) < PAGE:
            break
        off += PAGE
    # LSOA names carry their borough, so the name is the filter for "in London".
    feats = [f for f in feats
             if f["properties"]["LSOA21NM"].rsplit(" ", 1)[0] in boroughs]
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"{len(feats):,} London LSOAs -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    population()
    boundaries()
