"""
Turn a CSV from the "PoGo and OSM POI Exporter" into the server's forts.

That tool exports real PokeStop locations (from pogomap.info) plus OpenStreetMap
POIs to a CSV with columns: id,name,latitude,longitude,source,type. This reads
that CSV and writes data/osm_forts.json -- the same file tools/fetch_osm_pois.py
produces and pois.py serves -- so your real-world stops become in-game
PokeStops/Gyms, off the roads, close enough to spin.

Usage (from work/server):
  py ../tools/import_poi_csv.py "<path to the exported CSV>" [--append]

Writes data/osm_forts.json next to the server. Drop that file in RELEASE/data to
go live (pois.py hot-reloads it -- no rebuild). Re-run any time; --append merges
with what's there instead of replacing.
"""
import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import datadir  # noqa: E402

OUT = os.path.join(datadir.ensure(), "osm_forts.json")

# OSM 'type' values (and PoGo has none of these) that read as a landmark -> Gym.
# Everything else is a stop unless the hash below promotes ~1 in 10 to a Gym, so
# the stop:gym ratio stays realistic no matter the mix of PoGo/OSM rows.
LANDMARK = {"park", "stadium", "townhall", "monument", "memorial", "museum",
            "castle", "attraction", "sports_centre", "recreation_ground",
            "place_of_worship", "theme_park", "zoo"}
GYM_EVERY = 10


def _is_gym(oid, typ):
    if (typ or "").strip().lower() in LANDMARK:
        return True
    return int(hashlib.md5(oid.encode()).hexdigest(), 16) % GYM_EVERY == 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = sys.argv[1]
    append = "--append" in sys.argv
    if not os.path.isfile(src):
        raise SystemExit(f"no such file: {src}")

    forts, seen = [], set()
    with open(src, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        need = ("id", "name", "latitude", "longitude")
        if not all(k in cols for k in need):
            raise SystemExit(f"CSV must have columns {need}; got {reader.fieldnames}")
        for row in reader:
            try:
                oid = str(row[cols["id"]]).strip()
                lat = float(row[cols["latitude"]])
                lng = float(row[cols["longitude"]])
            except (KeyError, TypeError, ValueError):
                continue
            if not oid or (abs(lat) < 1e-9 and abs(lng) < 1e-9):
                continue
            fid = "POI" + oid
            if fid in seen:
                continue
            seen.add(fid)
            name = (row.get(cols.get("name", ""), "") or "").strip() or (
                "PokeStop" if str(row.get(cols.get("source", ""), "")).strip().lower()
                == "pogo" else "Waypoint")
            typ = row.get(cols.get("type", ""), "") if "type" in cols else ""
            forts.append({"id": fid, "lat": round(lat, 7), "lng": round(lng, 7),
                          "kind": "gym" if _is_gym(fid, typ) else "stop",
                          "name": name[:40], "image": ""})

    if append:
        try:
            with open(OUT, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        have = {f["id"] for f in existing}
        forts = existing + [f for f in forts if f["id"] not in have]

    stops = sum(1 for f in forts if f["kind"] == "stop")
    gyms = len(forts) - stops
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"forts": forts}, fh, indent=1)
    print(f"wrote {OUT}: {len(forts)} forts ({stops} stops, {gyms} gyms)")
    print("-> copy this file into RELEASE/data/ to go live (hot-reloads, no rebuild)")


if __name__ == "__main__":
    main()
