"""
Grab every business/POI in a city from OpenStreetMap and install them as stops.

Dead simple: name a city (or give coordinates), and this pulls all the real
businesses/shops/parks/churches/schools from OpenStreetMap, turns each into a
PokeStop, promotes ~1 in 10 to a Gym, and writes them straight into the running
server at their REAL coordinates. Set your in-game location to that city and there
they are. Every stop placed is written to server/data/stops_log.txt.

Usage (from work/server, or anywhere):
  py ../tools/grab_stops.py --city "Rapid City, SD"
  py ../tools/grab_stops.py --city "Denver" 8
  py ../tools/grab_stops.py 44.0805 -103.2310 6 --append

  <radius_km>       how far from the centre to grab   (default 8)
  --gym-every K     ~1 in K becomes a gym             (default 10)
  --append          add to existing stops instead of replacing
"""
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import fetch_osm_pois as osm            # noqa: E402  classify + Overpass fetch
import fetch_osm_pois_bulk as bulk      # noqa: E402  reliable tiling

REPO = os.path.abspath(os.path.join(HERE, ".."))
TARGETS = [os.path.join(REPO, "server", "data", "osm_forts.json"),           # source build
           os.path.join(REPO, "..", "server", "data", "osm_forts.json"),     # top-level server/ (live)
           os.path.join(REPO, "..", "RELEASE", "data", "osm_forts.json")]    # packaged RELEASE
LOG = os.path.join(REPO, "..", "server", "data", "stops_log.txt")


def geocode(city):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": city, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "pogo-private-server/1.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    if not d:
        raise SystemExit(f'could not find "{city}" -- try adding a state/country')
    return float(d[0]["lat"]), float(d[0]["lon"]), d[0]["display_name"]


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except (ValueError, IndexError):
            pass
    return default


def _atomic_write_json(path, obj):
    """Write JSON so the live file is never left half-written. We build the whole
    file under a temp name in the same folder, flush it to disk, then atomically
    swap it into place with os.replace(). If anything goes wrong mid-write -- the
    process is killed, the disk fills up -- the temp file is discarded and the
    existing osm_forts.json stays exactly as it was. This is what stops an
    interrupted export from wiping out your forts (the bug that left a stray .bak
    and an empty map)."""
    import tempfile
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".osm_forts.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)                 # atomic on the same filesystem
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(forts, append, header):
    import datetime
    # Precompute each fort's level-15 S2 cell and store it, so the server buckets
    # forts by a plain dict lookup instead of computing S2 over the whole file on
    # every map refresh (which is what makes statewide/US-scale data usable).
    try:
        import s2sphere
        missing = [f for f in forts if "cell" not in f]
        if missing:
            print(f"  computing S2 cells for {len(missing)} forts ...", flush=True)
            for f in missing:
                try:
                    f["cell"] = str(s2sphere.CellId.from_lat_lng(
                        s2sphere.LatLng.from_degrees(f["lat"], f["lng"])).parent(15).id())
                except Exception:
                    f["cell"] = ""
    except ImportError:
        pass
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"\n===== {ts}  {header}  ({len(forts)} forts) =====\n")
        for f in forts:
            fh.write(f"  {f['kind']:4} {f['lat']:.6f},{f['lng']:.6f}  {f['name']}\n")
    for path in TARGETS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cur = []
        if append:
            try:
                with open(path, encoding="utf-8") as fh:
                    cur = json.load(fh).get("forts", [])
            except FileNotFoundError:
                cur = []
            except (OSError, ValueError) as e:
                # The file is there but won't parse (e.g. a half-written file from a
                # previously interrupted run). Do NOT overwrite it with just this
                # batch -- that would throw away whatever forts it still holds. Skip
                # this target and let the user sort it out.
                print(f"  SKIP {path}: existing file unreadable ({e}); "
                      f"not overwriting so nothing is lost", flush=True)
                continue
        have = {f["id"] for f in cur}
        merged = cur + [f for f in forts if f["id"] not in have]
        _atomic_write_json(path, {"forts": merged})


def grab(clat, clng, radius_km, gym_every=10, progress=None):
    """Grab OSM businesses around a point and return them as forts with an exact
    1-in-`gym_every` gym ratio. `progress(msg)` is called per ring if given."""
    import hashlib
    import math
    osm.GYM_EVERY = max(2, int(gym_every))
    dlat = bulk.TILE_KM / bulk.KM_PER_DEG_LAT
    dlng = bulk.TILE_KM / (bulk.KM_PER_DEG_LAT * max(0.05, math.cos(math.radians(clat))))
    rings = max(1, int(math.ceil(radius_km / bulk.TILE_KM)))
    forts, seen = [], set()
    for ring in range(rings + 1):
        for s, w, n, e in bulk._ring_tiles(clat, clng, ring, dlat, dlng):
            forts += bulk._forts_from(bulk._fetch_tile(s, w, n, e), seen)
        if progress:
            progress(f"ring {ring}/{rings}: {len(forts)} businesses so far")
    for f in forts:                     # exact 1-in-K gyms, ignoring landmark forcing
        h = int(hashlib.md5(f["id"].encode()).hexdigest(), 16)
        f["kind"] = "gym" if h % osm.GYM_EVERY == 0 else "stop"
    return forts


def main():
    # Collect bare positional args, skipping flags and the values that follow
    # value-taking flags, so --city "X" and --gym-every 10 never look like a radius.
    argv = sys.argv[1:]
    takes_val = {"--city", "--gym-every"}
    positionals, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in takes_val:
            skip = True
            continue
        if a.startswith("--"):
            continue
        positionals.append(a)

    if "--city" in sys.argv:
        city = sys.argv[sys.argv.index("--city") + 1]
        clat, clng, label = geocode(city)
        print(f'"{city}" -> {clat},{clng}  ({label[:60]})')
        radius_km = float(positionals[0]) if positionals else 8.0
    else:
        if len(positionals) < 2:
            print(__doc__)
            return
        clat, clng, label = float(positionals[0]), float(positionals[1]), \
            f"{positionals[0]},{positionals[1]}"
        radius_km = float(positionals[2]) if len(positionals) > 2 else 8.0

    gym_every = max(2, _arg("--gym-every", 10, int))       # 1-in-K gym ratio
    append = "--append" in sys.argv

    print(f"grabbing OSM businesses within {radius_km}km, ~1 in {gym_every} a gym ...")
    forts = grab(clat, clng, radius_km, gym_every,
                 progress=lambda m: print("  " + m, flush=True))
    if not forts:
        raise SystemExit("found 0 businesses there. Try a bigger city or radius.")
    header = f'{label[:40]} r={radius_km}km 1/{gym_every}gym {"append" if append else "replace"}'
    install(forts, append, header)
    stops = sum(1 for f in forts if f["kind"] == "stop")
    print(f"installed {len(forts)} forts ({stops} stops, {len(forts) - stops} gyms)")
    print(f"logged to {LOG}")
    print("set your in-game location to that city; refresh the map (no restart).")


if __name__ == "__main__":
    main()
