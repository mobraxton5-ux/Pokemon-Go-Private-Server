"""
Thin out stops that sit almost on top of each other.

Dense cities map several businesses in one building as separate OSM nodes, so you
end up with a pile of stops within a few metres. This drops any STOP that lands
within <min_m> metres (default 10) of a stop we're already keeping. Gyms are left
completely alone: never removed, and they don't push out nearby stops.

Rewrites osm_forts.json in place (RELEASE + work/server) so it hot-reloads -- no exe
rebuild. Order is preserved and the pick is deterministic (nearest-to-first-seen wins).

Usage (from work/server, or anywhere):
  py ../tools/thin_stops.py               # 10 m, live data
  py ../tools/thin_stops.py --min-m 30    # spread them out more
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
TARGETS = [os.path.join(REPO, "..", "RELEASE", "data", "osm_forts.json"),   # live
           os.path.join(REPO, "server", "data", "osm_forts.json")]          # source
M_PER_DEG = 111320.0


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except (ValueError, IndexError):
            pass
    return default


def thin(forts, min_m):
    """Keep every gym; keep a stop only if no already-kept stop is within min_m."""
    cell_lat = min_m / M_PER_DEG                       # grid cell height in degrees
    grid = {}                                          # (gi,gj) -> [(lat,lng), ...] kept stops
    out, removed = [], 0
    for f in forts:
        if f.get("kind") == "gym":
            out.append(f)
            continue
        la, ln = f["lat"], f["lng"]
        clat = max(0.05, math.cos(math.radians(la)))
        cell_lng = min_m / (M_PER_DEG * clat)
        gi = int(la / cell_lat)
        gj = int(ln / cell_lng)
        too_close = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (kla, kln) in grid.get((gi + di, gj + dj), ()):  # kept neighbours
                    dm = math.hypot((la - kla) * M_PER_DEG,
                                    (ln - kln) * M_PER_DEG * clat)
                    if dm < min_m:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break
        if too_close:
            removed += 1
            continue
        grid.setdefault((gi, gj), []).append((la, ln))
        out.append(f)
    return out, removed


def main():
    min_m = _arg("--min-m", 10.0, float)
    src = next((t for t in TARGETS if os.path.exists(t)), None)
    if not src:
        raise SystemExit("no osm_forts.json found in RELEASE/data or server/data")
    with open(src, encoding="utf-8") as fh:
        forts = json.load(fh).get("forts", [])
    stops0 = sum(1 for f in forts if f.get("kind") != "gym")
    gyms = len(forts) - stops0
    print(f"loaded {len(forts):,} forts ({stops0:,} stops, {gyms:,} gyms) from {src}")
    print(f"thinning stops closer than {min_m:.0f} m ...")
    kept, removed = thin(forts, min_m)
    stops1 = sum(1 for f in kept if f.get("kind") != "gym")
    for path in TARGETS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"forts": kept}, fh)
    print(f"removed {removed:,} crowded stops -> kept {len(kept):,} forts "
          f"({stops1:,} stops, {gyms:,} gyms)")
    print("written to RELEASE/data + work/server/data; refresh the map in-game.")


if __name__ == "__main__":
    main()
