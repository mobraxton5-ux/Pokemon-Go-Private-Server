"""
Generate a whole bunch of PokeStops/Gyms around a coordinate.

Real-world stop data (OpenStreetMap businesses, pogomap.info) is empty for remote
rural areas -- there's simply nothing mapped out there to turn into forts. When you
just want a field of stops to walk to, this lays them down for you: a jittered grid
of forts filling a circle around your location, spaced so you can spin as you move,
with ~1 in 6 promoted to a Gym (the same ratio the OSM tool uses).

Writes data/osm_forts.json -- the same file pois.py hot-reloads and fetch_osm_pois.py
produces -- so the stops appear on the next map refresh with no restart.

Usage (from work/server, or anywhere):
  py ../tools/make_stops.py <lat> <lng>                      # defaults below
  py ../tools/make_stops.py 42.94413 -102.23602 --count 2000 --spacing 60
  py ../tools/make_stops.py 42.94413 -102.23602 --radius-km 4 --append

Options:
  --count N        stop when N forts are placed          (default 1500)
  --spacing M      metres between neighbours             (default 70)
  --radius-km R    hard cap on how far out to place      (default: whatever --count needs)
  --gym-every K    ~1 in K forts becomes a gym           (default 6)
  --append         add to what's already in the file instead of replacing it

Fewer, farther-apart stops: raise --spacing. A dense city feel: --spacing 45.
"""
import hashlib
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import datadir  # noqa: E402

OUT = os.path.join(datadir.ensure(), "osm_forts.json")
KM_PER_DEG_LAT = 111.0
LANDMARK_NAMES = ["Park", "Plaza", "Monument", "Fountain", "Statue", "Mural",
                  "Trailhead", "Overlook", "Well", "Marker", "Garden", "Shrine"]


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except (ValueError, IndexError):
            pass
    return default


def _is_gym(fid, every):
    return int(hashlib.md5(fid.encode()).hexdigest(), 16) % every == 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return
    clat, clng = float(args[0]), float(args[1])
    count = _arg("--count", 1500, int)
    spacing = _arg("--spacing", 70.0, float)          # metres
    gym_every = max(2, _arg("--gym-every", 6, int))
    append = "--append" in sys.argv

    # A grid spaced `spacing` metres apart in a hex pattern (offset every other row so
    # neighbours sit evenly, like a honeycomb) fills a circle whose radius grows until
    # we have `count` cells. Default radius is derived from count; --radius-km caps it.
    dlat = spacing / (KM_PER_DEG_LAT * 1000.0)
    dlng = spacing / (KM_PER_DEG_LAT * 1000.0 * max(0.05, math.cos(math.radians(clat))))
    # radius needed for `count` cells: area = count * spacing^2  ->  r = sqrt(count/pi)*spacing
    need_km = math.sqrt(count / math.pi) * spacing / 1000.0
    max_km = _arg("--radius-km", need_km * 1.3, float)   # a little slack for circle packing
    rows = int(max_km * 1000.0 / spacing) + 1

    rng = random.Random(f"{clat},{clng},{spacing}")     # deterministic: same input -> same map
    forts, seen = [], set()
    if append:
        try:
            with open(OUT, encoding="utf-8") as fh:
                forts = json.load(fh).get("forts", [])
            seen = {f["id"] for f in forts}
        except (OSError, ValueError):
            forts, seen = [], set()

    placed = 0
    for i in range(-rows, rows + 1):
        if placed >= count:
            break
        offset = 0.5 if i % 2 else 0.0                  # hex stagger
        for j in range(-rows, rows + 1):
            # ring-by-ring-ish: skip cells outside the circle so the field is round
            plat = clat + i * dlat * math.sqrt(3) / 2   # hex rows are closer vertically
            plng = clng + (j + offset) * dlng
            dist_km = math.hypot((plat - clat) * KM_PER_DEG_LAT,
                                 (plng - clng) * KM_PER_DEG_LAT * math.cos(math.radians(clat)))
            if dist_km > max_km:
                continue
            # jitter so it doesn't look like graph paper (up to 25% of spacing)
            jlat = plat + rng.uniform(-0.25, 0.25) * dlat
            jlng = plng + rng.uniform(-0.25, 0.25) * dlng
            fid = f"GEN{i:+04d}{j:+04d}"
            if fid in seen:
                continue
            seen.add(fid)
            gym = _is_gym(fid, gym_every)
            name = (rng.choice(LANDMARK_NAMES) if gym else f"Stop {placed + 1}")
            forts.append({"id": fid, "lat": round(jlat, 7), "lng": round(jlng, 7),
                          "kind": "gym" if gym else "stop", "name": name, "image": ""})
            placed += 1
            if placed >= count:
                break

    # nearest-first so the ones right on top of you come out first
    forts.sort(key=lambda f: math.hypot(f["lat"] - clat, f["lng"] - clng))
    stops = sum(1 for f in forts if f["kind"] == "stop")
    gyms = len(forts) - stops
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"forts": forts}, fh, indent=1)
    print(f"wrote {OUT}: {len(forts)} forts ({stops} stops, {gyms} gyms) "
          f"around ({clat},{clng}), spacing {spacing:.0f}m, out to ~{max_km:.1f}km")
    print("-> live on the next map refresh (pois.py hot-reloads; no restart)")


if __name__ == "__main__":
    main()
