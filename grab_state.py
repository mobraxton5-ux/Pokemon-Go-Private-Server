"""
Grab EVERY business/POI in a whole US state from OpenStreetMap and install as stops.

Tiling the Overpass API over a whole state would be tens of thousands of requests and
get us banned, so this does it the right way: downloads the state's OSM extract from
Geofabrik once (~100MB), parses it offline with osmium, and turns every named
business/shop/park/church/school into a fort with ~1 in 10 a gym. The server only
ships forts near the player (they're bucketed by S2 cell), so statewide data is fine.

Writes to both server data dirs and logs every fort to server/data/stops_log.txt.

Usage (from work/server, or anywhere):
  py ../tools/grab_state.py nebraska
  py ../tools/grab_state.py nebraska --gym-every 8 --append
  py ../tools/grab_state.py "south-dakota"        # geofabrik slug, us/<slug>

The .pbf is cached under tools/_osm_cache so re-runs skip the download.
"""
import hashlib
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import fetch_osm_pois as osm   # noqa: E402  (KEYS / BLOCK)
import grab_stops as gs        # noqa: E402  (install + TARGETS/LOG)
import osmium                  # noqa: E402

CACHE = os.path.join(HERE, "_osm_cache")
KEYS = set(osm.KEYS)
BLOCK = set(osm.BLOCK)


def _url(slug):
    # Whole country lives at north-america/us-latest.osm.pbf; a state at
    # north-america/us/<state>-latest.osm.pbf.
    if slug in ("us", "usa", "united-states"):
        return "https://download.geofabrik.de/north-america/us-latest.osm.pbf"
    return f"https://download.geofabrik.de/north-america/us/{slug}-latest.osm.pbf"


def download(slug):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{slug}-latest.osm.pbf")
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
        print(f"using cached {path} ({os.path.getsize(path)/1048576:.0f}MB)")
        return path
    url = _url(slug)
    print(f"downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "pogo-private-server/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as fh:
        total = int(r.headers.get("Content-Length", 0)); got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk); got += len(chunk)
            if total:
                print(f"\r  {got/1048576:.0f}/{total/1048576:.0f} MB", end="", flush=True)
    print(f"\n  saved {path}")
    return path


class POIHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.forts = []

    def _name(self, tags):
        name = tags.get("name")
        if not name:
            return None
        vals = {tags.get(k) for k in KEYS if tags.get(k)}
        if not vals or (vals & BLOCK):
            return None
        return name[:40]

    def node(self, o):
        nm = self._name(o.tags)
        if nm is not None and o.location.valid():
            self.forts.append((f"n{o.id}", o.location.lat, o.location.lon, nm))

    def way(self, o):
        nm = self._name(o.tags)
        if nm is None:
            return
        la = ln = 0.0; c = 0
        for nd in o.nodes:
            if nd.location.valid():
                la += nd.location.lat; ln += nd.location.lon; c += 1
        if c:
            self.forts.append((f"w{o.id}", la / c, ln / c, nm))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return
    slug = args[0].lower().replace(" ", "-")
    gym_every = 10
    if "--gym-every" in sys.argv:
        try:
            gym_every = max(2, int(sys.argv[sys.argv.index("--gym-every") + 1]))
        except (ValueError, IndexError):
            pass
    append = "--append" in sys.argv

    nodes_only = "--nodes-only" in sys.argv     # whole-US: way geometry won't fit in RAM
    stage = None
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]

    path = download(slug)
    print(f"parsing {'nodes only ' if nodes_only else ''}(big files take a while) ...")
    if nodes_only:
        # Fast path for huge files: KeyFilter drops untagged nodes in C++ so only the
        # ~10-20M objects carrying our keys ever reach Python (vs ~2.8B for the US).
        from osmium.filter import KeyFilter
        raw, n = [], 0
        for o in osmium.FileProcessor(path).with_filter(KeyFilter(*KEYS)):
            n += 1
            if n % 5_000_000 == 0:
                print(f"    scanned {n:,} keyed objects, {len(raw):,} POIs", flush=True)
            nm = o.tags.get("name")
            if not nm:
                continue
            vals = {o.tags.get(k) for k in KEYS if o.tags.get(k)}
            if not vals or (vals & BLOCK):
                continue
            try:                                 # nodes have a location; ways don't here
                loc = o.location
            except Exception:
                continue
            if loc.valid():
                raw.append((f"n{o.id}", loc.lat, loc.lon, nm[:40]))
        h_forts = raw
    else:
        h = POIHandler()
        h.apply_file(path, locations=True, idx="flex_mem")
        h_forts = h.forts
    print(f"  {len(h_forts)} named POIs found")

    forts, seen = [], set()
    for oid, la, ln, nm in h_forts:
        fid = "OSM" + oid
        if fid in seen:
            continue
        seen.add(fid)
        gym = int(hashlib.md5(fid.encode()).hexdigest(), 16) % gym_every == 0
        forts.append({"id": fid, "lat": round(la, 7), "lng": round(ln, 7),
                      "kind": "gym" if gym else "stop", "name": nm, "image": ""})

    if not forts:
        raise SystemExit("no POIs parsed -- check the state slug.")

    # Precompute the level-15 S2 cell for every fort so the server never runs S2 over
    # the whole file at runtime (see pois.forts_by_cell).
    try:
        import s2sphere
        print(f"  computing S2 cells for {len(forts)} forts ...", flush=True)
        for i, f in enumerate(forts):
            try:
                f["cell"] = str(s2sphere.CellId.from_lat_lng(
                    s2sphere.LatLng.from_degrees(f["lat"], f["lng"])).parent(15).id())
            except Exception:
                f["cell"] = ""
            if i % 500000 == 0 and i:
                print(f"    {i}/{len(forts)}", flush=True)
    except ImportError:
        pass

    stops = sum(1 for f in forts if f["kind"] == "stop")
    if stage:
        # Write ONE staging file only -- do not touch the live exe's data yet.
        import json as _json
        os.makedirs(os.path.dirname(stage) or ".", exist_ok=True)
        with open(stage, "w", encoding="utf-8") as fh:
            _json.dump({"forts": forts}, fh)
        print(f"staged {len(forts)} forts ({stops} stops, {len(forts) - stops} gyms) -> {stage}")
        return
    header = f"{slug} (whole state) 1/{gym_every}gym {'append' if append else 'replace'}"
    gs.install(forts, append, header)
    print(f"installed {len(forts)} forts ({stops} stops, {len(forts) - stops} gyms)")
    print(f"logged to {gs.LOG}")
    print("set your in-game location anywhere in the state; refresh the map (no restart).")


if __name__ == "__main__":
    main()
