"""
Build a whole-US real-terrain biome map, state by state.

biomes.py can tie spawns to real terrain from an osm_biomes.json, but the whole-US
extract's node cache won't fit on a small disk. So this walks the 50 states (+DC)
ONE AT A TIME: download the state's OSM extract, classify its water/forest/city/etc.
features into game biomes, vote the dominant biome into each level-12 S2 cell (~3km),
then delete the extract before moving on. The result is a compact {cell -> biome} map
that biomes.py looks up in O(1).

Resumable: progress is checkpointed after every state, so a crash or Ctrl-C picks up
where it left off. Writes data/osm_biomes.json (cells + any existing region points).

Usage (from work/server, or anywhere):
  py ../tools/fetch_us_biomes.py                 # all states
  py ../tools/fetch_us_biomes.py --only texas    # one state (repeatable)
"""
import json
import os
import pickle
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import fetch_osm_biomes as fob   # noqa: E402  (RULES + _biome classifier)
import s2sphere                  # noqa: E402
import osmium                    # noqa: E402
from osmium.filter import KeyFilter  # noqa: E402

CACHE = os.path.join(HERE, "_osm_cache")
PROGRESS = os.path.join(CACHE, "us_biomes_progress.pkl")
OUT = os.path.join(HERE, "..", "server", "data", "osm_biomes.json")
CELL_LEVEL = 12                  # must match spawns.biome_size in settings
KEYS = sorted({k for k, _v, _b in fob.RULES})   # natural, landuse, waterway, leisure

STATES = ["alabama", "alaska", "arizona", "arkansas", "california", "colorado",
          "connecticut", "delaware", "district-of-columbia", "florida", "georgia",
          "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
          "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
          "mississippi", "missouri", "montana", "nebraska", "nevada", "new-hampshire",
          "new-jersey", "new-mexico", "new-york", "north-carolina", "north-dakota",
          "ohio", "oklahoma", "oregon", "pennsylvania", "rhode-island",
          "south-carolina", "south-dakota", "tennessee", "texas", "utah", "vermont",
          "virginia", "washington", "west-virginia", "wisconsin", "wyoming"]


def _download(slug):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{slug}-latest.osm.pbf")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return path
    url = f"https://download.geofabrik.de/north-america/us/{slug}-latest.osm.pbf"
    req = urllib.request.Request(url, headers={"User-Agent": "pogo-private-server/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as fh:
        total, got, mark = int(r.headers.get("Content-Length", 0)), 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk); got += len(chunk)
            if total and got - mark > 20 * (1 << 20):
                mark = got
                print(f"    {got//1048576}/{total//1048576} MB", flush=True)
    return path


def _cid(lat, lng):
    return s2sphere.CellId.from_lat_lng(
        s2sphere.LatLng.from_degrees(lat, lng)).parent(CELL_LEVEL).id()


MAJOR_WATERWAY = {"river", "riverbank"}   # named rivers only; canals/streams/ditches dropped

# OSM coverage is lopsided: parks/pitches/cemeteries/golf/farmland all read as
# "grassland" and are mapped EVERYWHERE, so they swamp cities (only residential
# landuse) and deserts (rarely tagged). Weight each biome by how strongly its tags
# actually pin down the terrain, so a downtown cell wins "city" and a sandy one
# "desert" instead of everything collapsing to grassland.
WEIGHTS = {"city": 5, "desert": 5, "mountain": 4, "forest": 3,
           "wetland": 1, "water": 1, "grassland": 1}


def _classify(tags):
    """(biome, is_line). Minor waterways (stream/ditch/drain) are dropped so a creek
    doesn't turn a whole rural cell into 'water' -- water comes from real water BODIES
    (natural=water, reservoirs, coast) plus major rivers, which vote lightly as lines."""
    wtr = tags.get("waterway")
    if wtr is not None:
        if wtr in MAJOR_WATERWAY:
            return "water", True
        return None, False                    # ignore minor waterways entirely
    return fob._biome(tags), False


def _tally_state(path, votes):
    """Vote each terrain feature's biome into the level-12 cells it covers -- ONE vote
    per cell per feature, so a big lake and a small park each count once in a cell."""
    n = kept = 0
    fp = osmium.FileProcessor(path).with_locations().with_filter(KeyFilter(*KEYS))
    for o in fp:
        n += 1
        b, is_line = _classify(dict(o.tags))
        if not b:
            continue
        pts = []
        try:                                  # node: one point
            loc = o.location
            if loc.valid():
                pts = [(loc.lat, loc.lon)]
        except Exception:                     # way
            try:
                nodes = [nd.location for nd in o.nodes if nd.location.valid()]
            except Exception:
                nodes = []
            if is_line and nodes:             # a river marks only its midpoint's cell
                mid = nodes[len(nodes) // 2]
                pts = [(mid.lat, mid.lon)]
            elif b == "water" and len(nodes) < 20:
                continue                      # only substantial water bodies count
            else:                             # an area colours every cell it covers
                step = max(1, len(nodes) // 40)
                pts = [(nd.lat, nd.lon) for nd in nodes[::step]]
        seen_cells = set()
        for la, ln in pts:
            try:
                seen_cells.add(_cid(la, ln))
            except Exception:
                pass
        wt = WEIGHTS.get(b, 1)
        for c in seen_cells:                  # one weighted vote per distinct cell
            d = votes.get(c)
            if d is None:
                votes[c] = {b: wt}
            else:
                d[b] = d.get(b, 0) + wt
            kept += 1
    return n, kept


def _write_out(votes):
    cells = {}
    for c, d in votes.items():
        cells[str(c)] = max(d.items(), key=lambda kv: kv[1])[0]
    points = []                               # keep any existing region points
    try:
        with open(OUT, encoding="utf-8") as fh:
            points = json.load(fh).get("points", [])
    except (OSError, ValueError):
        points = []
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"cell_level": CELL_LEVEL, "cells": cells, "points": points}, fh)
    return len(cells)


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    todo = [only] if only else STATES

    done, votes = set(), {}
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS, "rb") as fh:
                p = pickle.load(fh)
            done, votes = set(p.get("done", [])), p.get("votes", {})
            print(f"resuming: {len(done)} states already done, {len(votes)} cells so far")
        except Exception:
            done, votes = set(), {}

    # Prefetch downloads a couple of states ahead in background threads while the
    # main loop parses the current one -- so downloading and parsing overlap instead
    # of blocking each other, roughly halving the wall time.
    from concurrent.futures import ThreadPoolExecutor
    remaining = [s for s in todo if s not in done]
    pool = ThreadPoolExecutor(max_workers=3)
    futures = {}

    def _prefetch(upto):
        for s in remaining[:upto]:
            if s not in futures:
                futures[s] = pool.submit(_download, s)

    for i, slug in enumerate(todo, 1):
        if slug in done:
            continue
        # keep 3 states downloading ahead of where we're parsing
        idx = remaining.index(slug)
        _prefetch(idx + 3)
        print(f"[{i}/{len(todo)}] {slug}: waiting for download ...", flush=True)
        try:
            path = futures[slug].result()
        except Exception as e:
            print(f"    download failed ({e}); skipping", flush=True)
            done.add(slug)
            continue
        print(f"    parsing terrain ...", flush=True)
        try:
            scanned, kept = _tally_state(path, votes)
            print(f"    {scanned:,} keyed features, {kept:,} biome votes; "
                  f"{len(votes):,} cells total", flush=True)
        except MemoryError:
            print("    OUT OF MEMORY on this state; skipping it", flush=True)
        finally:
            try:
                os.remove(path)               # reclaim disk before the next state
            except OSError:
                pass
        done.add(slug)
        with open(PROGRESS, "wb") as fh:      # checkpoint after every state
            pickle.dump({"done": list(done), "votes": votes}, fh)
        ncells = _write_out(votes)            # keep the live file usable as we go
        print(f"    checkpoint saved; osm_biomes.json now has {ncells:,} cells", flush=True)

    ncells = _write_out(votes)
    print(f"\nDONE: {ncells:,} biome cells across {len(done)} states -> {OUT}")
    print("copy into RELEASE/data/ to go live (hot-reloads, no rebuild)")


if __name__ == "__main__":
    main()
