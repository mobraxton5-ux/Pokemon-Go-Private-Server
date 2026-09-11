"""
Fill an area with real PokeStops/Gyms from an OpenStreetMap .osm.pbf extract --
the offline, NO-RATE-LIMIT way. Overpass caps out well before a whole country;
this downloads a Geofabrik extract, parses it locally with osmium, and throws it
away -- exactly like fetch_us_biomes.py, but pulling POIs -> forts instead of
terrain.

The POI keys, the junk blocklist, the stop/gym classifier and the fort JSON shape
are all imported from fetch_osm_pois.py, so this file and the Overpass fetchers
produce identical forts. pois.py hot-reloads osm_forts.json.

Usage (from work/server, or anywhere):
  py ../tools/fetch_pois_pbf.py europe/austria            # download a region + parse
  py ../tools/fetch_pois_pbf.py north-america/us/texas
  py ../tools/fetch_pois_pbf.py C:\\path\\to\\some.osm.pbf  # a file you already have
  py ../tools/fetch_pois_pbf.py europe/austria --out data/osm_forts.austria.json
  py ../tools/fetch_pois_pbf.py europe/switzerland --append   # add to the current file
  py ../tools/fetch_pois_pbf.py europe/austria --keep         # don't delete the .pbf

A Geofabrik "region" is anything under https://download.geofabrik.de/, e.g.
"europe/austria", "europe", "north-america/us/california". Extracts are cached in
tools/_osm_cache and reused. No Overpass, no mirrors, no rate limits.
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import fetch_osm_pois as base   # noqa: E402  KEYS, BLOCK, _classify, _is_gym, OUT
import osmium                   # noqa: E402
from osmium.filter import KeyFilter  # noqa: E402

CACHE = os.path.join(HERE, "_osm_cache")
GEOFABRIK = "https://download.geofabrik.de/{}-latest.osm.pbf"


def _download(region):
    os.makedirs(CACHE, exist_ok=True)
    slug = region.replace("/", "-")
    path = os.path.join(CACHE, f"{slug}-latest.osm.pbf")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        print(f"  using cached {path}", flush=True)
        return path
    url = GEOFABRIK.format(region)
    print(f"  downloading {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "pogo-private-server/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as fh:
        total, got, mark = int(r.headers.get("Content-Length", 0)), 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if got - mark > 25 * (1 << 20):
                mark = got
                tail = f" / {total // 1048576} MB ({got * 100 // total}%)" if total else ""
                print(f"    {got // 1048576} MB{tail}", flush=True)
    return path


def _extract(path):
    """Every named POI of interest in the extract, as forts. osmium streams the
    file (low memory) and attaches node locations so a way gets its centroid."""
    fp = osmium.FileProcessor(path).with_locations().with_filter(KeyFilter(*base.KEYS))
    forts = []
    scanned = 0
    for o in fp:
        scanned += 1
        if scanned % 200000 == 0:
            print(f"    scanned {scanned:,}  kept {len(forts):,}", flush=True)
        tags = dict(o.tags)
        lat = lng = None
        try:
            loc = o.location                       # only nodes have .location
            oid = f"n{o.id}"
            if loc.valid():
                lat, lng = loc.lat, loc.lon
        except Exception:
            oid = f"w{o.id}"                        # a way -> centroid of its nodes
            try:
                pts = [(nd.location.lat, nd.location.lon)
                       for nd in o.nodes if nd.location.valid()]
            except Exception:
                pts = []                            # a relation: no simple geometry
            if pts:
                lat = sum(p[0] for p in pts) / len(pts)
                lng = sum(p[1] for p in pts) / len(pts)
        if lat is None:
            continue
        keep, kind, name = base._classify(oid, tags)
        if not keep:
            continue
        forts.append({"id": f"OSM{oid}", "lat": round(lat, 7), "lng": round(lng, 7),
                      "kind": kind, "name": name, "image": ""})
    return forts, scanned


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return
    region_or_file = args[0]
    out = base.OUT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        if not os.path.isabs(out):
            out = os.path.join(os.getcwd(), out)
    append = "--append" in sys.argv
    keep = "--keep" in sys.argv

    if region_or_file.lower().endswith(".pbf") or os.path.exists(region_or_file):
        path, downloaded = region_or_file, False
    else:
        path, downloaded = _download(region_or_file), True

    print(f"  parsing {path} ...", flush=True)
    forts, scanned = _extract(path)

    if append:
        try:
            with open(out, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        have = {f["id"] for f in existing}
        forts = existing + [f for f in forts if f["id"] not in have]

    stops = sum(1 for f in forts if f["kind"] == "stop")
    gyms = len(forts) - stops
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"forts": forts}, fh, indent=1)
    print(f"wrote {out}: {len(forts):,} forts ({stops:,} stops, {gyms:,} gyms) "
          f"from {scanned:,} keyed features", flush=True)

    if downloaded and not keep:
        try:
            os.remove(path)
            print(f"  removed cached extract {path}", flush=True)
        except OSError:
            pass
    print("copy into RELEASE/data/osm_forts.json to go live (hot-reloads, no rebuild)")


if __name__ == "__main__":
    main()
