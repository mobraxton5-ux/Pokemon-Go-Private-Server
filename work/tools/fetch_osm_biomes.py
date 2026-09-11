"""
Pull real TERRAIN from OpenStreetMap so biomes match the actual world.

biomes.py normally guesses a region's biome from a hash of the map cell. This
fetches OSM land-use / natural / water features around your play area, classifies
each into one of the game biomes (water, forest, grassland, city, wetland, desert,
mountain), and writes data/osm_biomes.json -- a list of {lat,lng,biome} points.
biomes.py then reads it and gives a location the biome of the nearest terrain
feature, so Water types really cluster by water, Bug/Grass in the woods, city
trash downtown, etc. Falls back to the hash model wherever there's no OSM data.

Usage (from work/server):
  py ../tools/fetch_osm_biomes.py <lat> <lng> [radius_km]     # default 5 km

Writes data/osm_biomes.json. Drop it in RELEASE/data to go live (hot-reloaded, no
rebuild). Re-run any time to refresh.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import datadir  # noqa: E402

OUT = os.path.join(datadir.ensure(), "osm_biomes.json")
OVERPASS = ["https://overpass.kumi.systems/api/interpreter",
            "https://overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]

# (osm_key, value_substring) -> game biome. Checked in order; first hit wins. A
# value of "" matches any value for that key.
RULES = [
    ("natural", "water", "water"), ("natural", "wetland", "wetland"),
    ("natural", "bay", "water"), ("natural", "spring", "water"),
    ("waterway", "", "water"), ("landuse", "reservoir", "water"),
    ("landuse", "basin", "water"),
    ("natural", "wood", "forest"), ("landuse", "forest", "forest"),
    ("natural", "scrub", "forest"), ("natural", "heath", "forest"),
    ("natural", "peak", "mountain"), ("natural", "cliff", "mountain"),
    ("natural", "ridge", "mountain"), ("natural", "rock", "mountain"),
    ("natural", "bare_rock", "mountain"), ("natural", "scree", "mountain"),
    ("natural", "sand", "desert"), ("natural", "dune", "desert"),
    ("natural", "beach", "desert"), ("landuse", "quarry", "desert"),
    ("landuse", "residential", "city"), ("landuse", "commercial", "city"),
    ("landuse", "industrial", "city"), ("landuse", "retail", "city"),
    ("leisure", "park", "grassland"), ("leisure", "garden", "grassland"),
    ("leisure", "golf_course", "grassland"), ("leisure", "pitch", "grassland"),
    ("leisure", "recreation_ground", "grassland"),
    ("landuse", "grass", "grassland"), ("landuse", "meadow", "grassland"),
    ("landuse", "village_green", "grassland"), ("landuse", "cemetery", "grassland"),
    ("landuse", "farmland", "grassland"), ("landuse", "farmyard", "grassland"),
    ("landuse", "orchard", "grassland"), ("natural", "grassland", "grassland"),
    ("natural", "fell", "grassland"),
]

KEYS = sorted({k for k, _v, _b in RULES})


def _query(lat, lng, radius_m):
    parts = "".join(
        f'nwr(around:{radius_m},{lat},{lng})["{k}"];' for k in KEYS)
    return f"[out:json][timeout:180];({parts});out center tags;"


def _fetch(lat, lng, radius_m):
    body = urllib.parse.urlencode({"data": _query(lat, lng, radius_m)}).encode()
    last = None
    for url in OVERPASS:
        try:
            print(f"  trying {url.split('/')[2]} ...")
            req = urllib.request.Request(
                url, data=body,
                headers={"User-Agent": "pogo-private-server/1.0 (personal use)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:
            last = e
            print(f"    {type(e).__name__}: {e}")
    raise SystemExit(f"all Overpass mirrors failed ({last}). Try again in a minute.")


def _biome(tags):
    for k, v, b in RULES:
        val = tags.get(k)
        if val is not None and (v == "" or v in val):
            return b
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    lat, lng = float(sys.argv[1]), float(sys.argv[2])
    radius_km = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0

    print(f"querying OSM terrain around ({lat},{lng}) r={radius_km}km ...")
    data = _fetch(lat, lng, int(radius_km * 1000))
    from collections import Counter
    pts, counts = [], Counter()
    for el in data.get("elements", []):
        b = _biome(el.get("tags") or {})
        if not b:
            continue
        if el["type"] == "node":
            flat, flng = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            flat, flng = c.get("lat"), c.get("lon")
        if flat is None or flng is None:
            continue
        pts.append({"lat": round(flat, 6), "lng": round(flng, 6), "biome": b})
        counts[b] += 1

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"points": pts}, fh)
    print(f"wrote {OUT}: {len(pts)} terrain points -> {dict(counts)}")
    print("-> copy into RELEASE/data/ to go live (hot-reloads, no rebuild)")


if __name__ == "__main__":
    main()
