"""
Pull real points-of-interest from OpenStreetMap and turn them into PokeStops/Gyms.

The server has no map data of its own, so procedural forts land wherever a cell
centre happens to fall -- including in the middle of roads. This fetches actual
businesses, shops, parks, churches, schools etc. around your play area from the
free OSM Overpass API and writes them as forts the server places verbatim. Because
they sit on real buildings, they are off the road and close enough to spin.

Usage (from work/server, or anywhere):
  py ../tools/fetch_osm_pois.py <lat> <lng> [radius_km]        # one area
  py ../tools/fetch_osm_pois.py 42.944 -102.236 3
Add more areas by running again with --append.

Writes data/osm_forts.json next to the server (the exe reads it there). Re-run any
time to refresh; without --append it replaces the file.
"""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import datadir  # noqa: E402

OUT = os.path.join(datadir.ensure(), "osm_forts.json")
# Several public Overpass mirrors -- we try them in turn (the main one 504s a lot).
OVERPASS = ["https://overpass.kumi.systems/api/interpreter",
            "https://overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]

# POI kinds worth a stop. We query these top-level keys and keep anything with a
# name, minus the junk blocklist below.
KEYS = ["amenity", "shop", "tourism", "leisure", "historic", "office",
        "craft", "club", "man_made"]

# amenity/leisure values that are NOT real destinations -- skip them.
BLOCK = {"parking", "parking_space", "parking_entrance", "bench", "waste_basket",
         "recycling", "bicycle_parking", "vending_machine", "drinking_water",
         "toilets", "fountain", "grit_bin", "hunting_stand", "shelter",
         "street_lamp", "clock", "telephone", "post_box", "atm", "bbq",
         "motorcycle_parking", "charging_station"}

# True landmarks are always gyms; everything else is a stop unless the hash below
# promotes it, so the stop:gym ratio stays realistic (~5:1) instead of turning
# every rural church/school into a gym.
LANDMARK = {"stadium", "townhall", "park", "monument", "memorial", "museum",
            "castle", "attraction", "sports_centre", "recreation_ground"}
GYM_EVERY = 6              # 1 in ~6 non-landmark POIs becomes a gym


def _is_gym(oid, vals):
    if vals & LANDMARK:
        return True
    return int(hashlib.md5(oid.encode()).hexdigest(), 16) % GYM_EVERY == 0


def _query(lat, lng, radius_m):
    # One nwr (node+way+relation) per key, named things only. `nwr` keeps the query
    # a third the size of separate node/way lines, which is what the mirrors can
    # actually serve without timing out.
    parts = "".join(
        f'nwr(around:{radius_m},{lat},{lng})["{key}"]["name"];' for key in KEYS)
    return f"[out:json][timeout:180];({parts});out center tags;"


def _fetch(lat, lng, radius_m):
    q = _query(lat, lng, radius_m)
    body = urllib.parse.urlencode({"data": q}).encode()
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


def _classify(oid, tags):
    """(keep?, kind, name). kind is 'gym' or 'stop'."""
    name = (tags.get("name") or "").strip()
    if not name:
        return False, None, None
    vals = {tags.get(k) for k in KEYS if tags.get(k)}
    if vals & BLOCK:
        return False, None, None
    return True, ("gym" if _is_gym(oid, vals) else "stop"), name[:40]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    lat, lng = float(sys.argv[1]), float(sys.argv[2])
    radius_km = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--append" else 3.0
    append = "--append" in sys.argv

    print(f"querying OSM around ({lat},{lng}) r={radius_km}km ...")
    data = _fetch(lat, lng, int(radius_km * 1000))
    forts, seen = [], set()
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        oid = f"{el['type'][0]}{el['id']}"
        keep, kind, name = _classify(oid, tags)
        if not keep:
            continue
        if el["type"] == "node":
            flat, flng = el.get("lat"), el.get("lon")
        else:                                   # way/relation -> use its center
            c = el.get("center") or {}
            flat, flng = c.get("lat"), c.get("lon")
        if flat is None or flng is None:
            continue
        if oid in seen:
            continue
        seen.add(oid)
        forts.append({"id": f"OSM{oid}", "lat": round(flat, 7), "lng": round(flng, 7),
                      "kind": kind, "name": name, "image": ""})

    existing = []
    if append:
        try:
            with open(OUT, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        have = {f["id"] for f in existing}
        forts = existing + [f for f in forts if f["id"] not in have]

    stops = sum(1 for f in forts if f["kind"] == "stop")
    gyms = sum(1 for f in forts if f["kind"] == "gym")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"forts": forts}, fh, indent=1)
    print(f"wrote {OUT}: {len(forts)} forts ({stops} stops, {gyms} gyms)")


if __name__ == "__main__":
    main()
