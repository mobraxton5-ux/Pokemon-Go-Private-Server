"""
OSM-sourced PokeStops / Gyms.

Loads data/osm_forts.json (produced by tools/fetch_osm_pois.py from OpenStreetMap)
and hands the map builder real businesses/parks/churches/etc. as forts. Because
they sit on actual buildings they are off the road and close enough to spin --
unlike the procedural cell-centre forts, which can land in the middle of a road.

Same shape as places.forts: {id, lat, lng, kind: "stop"|"gym", name, image}.
Hot-reloaded by mtime, so re-running the fetch tool takes effect on the next map
refresh with no restart.
"""
import json
import os
import threading

import datadir

POIS_FILE = os.path.join(datadir.ensure(), "osm_forts.json")

_lock = threading.RLock()
_cache = {"mtime": None, "forts": [], "by_cell": None}


def forts():
    """Every OSM fort, or [] if there's no file yet. Cheap: only re-reads the file
    when its mtime changes."""
    with _lock:
        try:
            m = os.path.getmtime(POIS_FILE)
        except OSError:
            _cache["mtime"], _cache["forts"] = None, []
            return []
        if _cache["mtime"] != m:
            out = []
            try:
                with open(POIS_FILE, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                for f in (d.get("forts") or []):
                    try:
                        out.append({
                            "id": str(f["id"]),
                            "lat": float(f["lat"]), "lng": float(f["lng"]),
                            "kind": "gym" if f.get("kind") == "gym" else "stop",
                            "name": str(f.get("name", ""))[:40],
                            "image": str(f.get("image", ""))[:300],
                            # level-15 S2 cell, precomputed by the grab tools; "" if an
                            # older file didn't store it (forts_by_cell fills it in then).
                            "cell": str(f.get("cell", "")),
                        })
                    except (KeyError, TypeError, ValueError):
                        continue
            except (OSError, ValueError):
                out = []
            _cache["mtime"], _cache["forts"], _cache["by_cell"] = m, out, None
        return list(_cache["forts"])


def forts_by_cell():
    """Every OSM fort grouped by its level-15 S2 cell id (int), built once per file
    change and cached. Lets the map builder pull just the cells it needs with a dict
    lookup instead of walking every fort on each request -- the difference between
    a few thousand and several million forts staying instant.

    Uses the "cell" precomputed by the grab tools; for an older file without it, the
    ids are computed here once and cached (still O(N) once, not per request)."""
    with _lock:
        forts()                                     # refresh cache if the file changed
        if _cache["by_cell"] is None:
            idx = {}
            need_s2 = [f for f in _cache["forts"] if not f.get("cell")]
            if need_s2:
                try:
                    import s2sphere
                    for f in need_s2:
                        try:
                            f["cell"] = str(s2sphere.CellId.from_lat_lng(
                                s2sphere.LatLng.from_degrees(
                                    f["lat"], f["lng"])).parent(15).id())
                        except Exception:
                            f["cell"] = ""
                except ImportError:
                    pass
            for f in _cache["forts"]:
                c = f.get("cell")
                if not c:
                    continue
                try:
                    idx.setdefault(int(c), []).append(f)
                except ValueError:
                    continue
            _cache["by_cell"] = idx
        return _cache["by_cell"]
