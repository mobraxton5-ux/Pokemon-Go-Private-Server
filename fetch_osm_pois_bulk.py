"""
Bulk version of fetch_osm_pois: fill a whole area with real PokeStops/Gyms.

fetch_osm_pois.py grabs one radius in a single Overpass call, which is fine for a
few hundred forts but falls over past a couple thousand -- the public mirrors time
out or rate-limit a query that big. This walks the area as a grid of small tiles
instead, querying each one on its own and spiralling outward ring by ring from the
centre until it has collected up to <cap> real forts (default 10000) or runs out of
real businesses to find. Each tile is small enough that the mirrors answer happily.

Same output as fetch_osm_pois: writes data/osm_forts.json (the classify/dedup rules
and fort shape are imported from it, so both tools agree). pois.py hot-reloads it.

Usage (from work/server, or anywhere):
  py ../tools/fetch_osm_pois_bulk.py <lat> <lng>                  # up to 10000, <=25km
  py ../tools/fetch_osm_pois_bulk.py 40.758 -73.985 --cap 5000
  py ../tools/fetch_osm_pois_bulk.py 40.758 -73.985 --max-km 40 --append

10000 is a *ceiling*, not a promise: you only get that many if that many named
businesses actually exist within --max-km. A small town simply has fewer, and the
run stops early once it stops finding new ones. Re-run with --append to add another
city to the same file. Progress is saved after every ring, so a Ctrl-C keeps what
was collected so far.
"""
import math
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_osm_pois as base  # noqa: E402  (constants + classify + output path)
import json  # noqa: E402

OUT = base.OUT
OVERPASS = base.OVERPASS

TILE_KM = 2.0          # side of one grid tile; small enough that a mirror answers
PAUSE_S = 1.5          # be polite to the free mirrors between tiles
DEFAULT_CAP = 10000
DEFAULT_MAX_KM = 25.0
KM_PER_DEG_LAT = 111.0


def _bbox_query(south, west, north, east):
    """One Overpass query for a single tile: every named POI of interest in the box."""
    parts = "".join(
        f'nwr({south},{west},{north},{east})["{key}"]["name"];' for key in base.KEYS)
    return f"[out:json][timeout:60];({parts});out center tags;"


def _fetch_tile(south, west, north, east):
    """Fetch one tile, rotating mirrors on failure. Returns [] rather than dying so a
    single bad tile never sinks the whole run."""
    body = urllib.parse.urlencode({"data": _bbox_query(south, west, north, east)}).encode()
    for url in OVERPASS:
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"User-Agent": "pogo-private-server/1.0 (personal use)"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r).get("elements", [])
        except Exception:
            continue
    return []


def _forts_from(elements, seen):
    """Turn raw Overpass elements into forts, skipping junk and anything already seen."""
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        oid = f"{el['type'][0]}{el['id']}"
        if oid in seen:
            continue
        keep, kind, name = base._classify(oid, tags)
        if not keep:
            continue
        if el["type"] == "node":
            flat, flng = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            flat, flng = c.get("lat"), c.get("lon")
        if flat is None or flng is None:
            continue
        seen.add(oid)
        out.append({"id": f"OSM{oid}", "lat": round(flat, 7), "lng": round(flng, 7),
                    "kind": kind, "name": name, "image": ""})
    return out


def _ring_tiles(clat, clng, ring, dlat, dlng):
    """The (south,west,north,east) boxes forming the square border `ring` tiles out
    from centre. ring 0 is the single centre tile; ring r is its 8r-tile border."""
    coords = range(-ring, ring + 1)
    for i in coords:
        for j in coords:
            if ring and max(abs(i), abs(j)) != ring:
                continue                     # interior tiles belong to smaller rings
            s = clat + i * dlat - dlat / 2
            n = clat + i * dlat + dlat / 2
            w = clng + j * dlng - dlng / 2
            e = clng + j * dlng + dlng / 2
            yield s, w, n, e


def _save(forts):
    stops = sum(1 for f in forts if f["kind"] == "stop")
    gyms = len(forts) - stops
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"forts": forts}, fh, indent=1)
    return stops, gyms


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except (ValueError, IndexError):
            pass
    return default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return
    clat, clng = float(args[0]), float(args[1])
    cap = _arg("--cap", DEFAULT_CAP, int)
    max_km = _arg("--max-km", DEFAULT_MAX_KM, float)
    append = "--append" in sys.argv

    # Tiles are ~TILE_KM on a side; lng degrees shrink with latitude so the boxes stay
    # roughly square in real distance.
    dlat = TILE_KM / KM_PER_DEG_LAT
    dlng = TILE_KM / (KM_PER_DEG_LAT * max(0.05, math.cos(math.radians(clat))))
    max_rings = max(1, int(math.ceil(max_km / TILE_KM)))

    forts, seen = [], set()
    if append:
        try:
            with open(OUT, encoding="utf-8") as fh:
                forts = json.load(fh).get("forts", [])
            seen = {f["id"].replace("OSM", "", 1) for f in forts}
        except (OSError, ValueError):
            forts, seen = [], set()

    print(f"filling ({clat},{clng}) up to {cap} forts, out to {max_km}km "
          f"({max_rings} rings of {TILE_KM}km tiles){' [append]' if append else ''}")
    empty_rings = 0
    for ring in range(max_rings + 1):
        before = len(forts)
        tiles = list(_ring_tiles(clat, clng, ring, dlat, dlng))
        for k, (s, w, n, e) in enumerate(tiles, 1):
            forts += _forts_from(_fetch_tile(s, w, n, e), seen)
            print(f"\r  ring {ring:>2}  tile {k:>3}/{len(tiles):<3}  "
                  f"forts {len(forts)}", end="", flush=True)
            if len(forts) >= cap:
                break
            time.sleep(PAUSE_S)
        gained = len(forts) - before
        _save(forts)                          # checkpoint after every ring
        print(f"\r  ring {ring:>2}  done          forts {len(forts)}  (+{gained})")
        if len(forts) >= cap:
            print("  reached cap.")
            break
        # Once we're past the centre and a whole ring adds nothing, the area is spent.
        empty_rings = empty_rings + 1 if (ring and gained == 0) else 0
        if empty_rings >= 2:
            print("  no new forts in the last two rings -- area exhausted.")
            break

    stops, gyms = _save(forts[:cap])
    print(f"wrote {OUT}: {min(len(forts), cap)} forts ({stops} stops, {gyms} gyms)")


if __name__ == "__main__":
    main()
