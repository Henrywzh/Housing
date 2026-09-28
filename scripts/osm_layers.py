"""Load the OSM amenity layers, with the one filter both consumers need.

leisure=garden is 22,542 of the 25,601 features Overpass returns for the park
query, and most of them are the communal courtyard of a block of flats rather
than somewhere to walk. A garden counts only if it carries a name; parks and
nature reserves count either way. Keeping this in one place stops the station
catchments and the map legend from disagreeing about what a park is.
"""
import json, pathlib
import pandas as pd

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "osm"
PREMIUM = ("waitrose", "marks & spencer", "m&s ", "whole foods")


def load():
    out = {}
    # Partially fetched tiles are hidden files in the same directory, and
    # pathlib's glob does not skip a leading dot -- they hold raw Overpass
    # elements, not our normalised points, so they must not be picked up here.
    for f in sorted(f for f in RAW.glob("*.json") if not f.name.startswith(".")):
        d = pd.DataFrame(json.loads(f.read_text()))
        if f.stem == "parks":
            d = d[d["kind"].isin(["park", "nature_reserve"]) | d["name"].notna()]
        out[f.stem] = d.reset_index(drop=True)
    return out


def is_premium(d):
    lab = (d["brand"].fillna("") + "|" + d["name"].fillna("")).str.lower()
    return lab.apply(lambda s: any(p in s for p in PREMIUM))
