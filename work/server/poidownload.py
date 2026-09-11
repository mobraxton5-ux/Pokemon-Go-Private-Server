"""
Country / US-state PokeStop+Gym downloads for the World Manager.

Each entry is a Geofabrik region (https://download.geofabrik.de/). Downloading one
pulls that region's `.osm.pbf`, parses real POIs with osmium, and appends them to
the same `data/osm_forts.json` the running server reads -- so a region goes playable
a few seconds after it finishes, no restart.

The actual download+parse lives in fetch_pois_pbf (osmium); it is imported lazily so
this module loads even where osmium is missing (the page still renders; a download
then reports the error instead of crashing the server).
"""
import json
import os
import threading

import datadir

DATA = datadir.ensure()
FORTS_FILE = os.path.join(DATA, "osm_forts.json")
LEDGER = os.path.join(DATA, "populated_regions.json")

# Country -> Geofabrik region. Add more from https://download.geofabrik.de/ anytime.
COUNTRIES = {
    "United States": "north-america/us",   # -> its own states sub-page
    "Canada": "north-america/canada", "Mexico": "north-america/mexico",
    "Great Britain": "europe/great-britain", "Ireland": "europe/ireland",
    "Germany": "europe/germany", "France": "europe/france", "Spain": "europe/spain",
    "Portugal": "europe/portugal", "Italy": "europe/italy",
    "Netherlands": "europe/netherlands", "Belgium": "europe/belgium",
    "Luxembourg": "europe/luxembourg", "Switzerland": "europe/switzerland",
    "Austria": "europe/austria", "Denmark": "europe/denmark",
    "Norway": "europe/norway", "Sweden": "europe/sweden", "Finland": "europe/finland",
    "Iceland": "europe/iceland", "Poland": "europe/poland",
    "Czechia": "europe/czech-republic", "Slovakia": "europe/slovakia",
    "Hungary": "europe/hungary", "Slovenia": "europe/slovenia",
    "Croatia": "europe/croatia", "Romania": "europe/romania",
    "Bulgaria": "europe/bulgaria", "Greece": "europe/greece",
    "Ukraine": "europe/ukraine", "Estonia": "europe/estonia",
    "Latvia": "europe/latvia", "Lithuania": "europe/lithuania",
    "Brazil": "south-america/brazil", "Argentina": "south-america/argentina",
    "Japan": "asia/japan", "South Korea": "asia/south-korea", "India": "asia/india",
    "Australia": "australia-oceania/australia",
    "New Zealand": "australia-oceania/new-zealand",
    "South Africa": "africa/south-africa",
}

# The US is offered per-state (the whole-country extract is enormous). Slugs are the
# Geofabrik ones under north-america/us/.
_US = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Puerto Rico", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]
US_STATES = {name: "north-america/us/" + name.lower().replace(" ", "-")
             for name in _US}

_lock = threading.Lock()
BUSY = {}                 # region -> status string while a populate runs
ERRORS = {}               # region -> last error message
_fort_count = None        # cached so the pages don't re-read the big file each poll


def _count_forts():
    global _fort_count
    if _fort_count is None:
        try:
            with open(FORTS_FILE, encoding="utf-8") as fh:
                _fort_count = len(json.load(fh).get("forts", []))
        except (OSError, ValueError):
            _fort_count = 0
    return _fort_count


def _load_ledger():
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            return set(json.load(fh).get("done", []))
    except (OSError, ValueError):
        # A big osm_forts.json already present is the seeded US import.
        seed = ["north-america/us"] if _count_forts() > 100000 else []
        _save_ledger(set(seed))
        return set(seed)


def _save_ledger(done):
    os.makedirs(DATA, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"done": sorted(done)}, fh, indent=1)
    os.replace(tmp, LEDGER)


def _do_populate(name, region):
    """Download + parse a region and append its forts to the live file."""
    global _fort_count
    try:
        import fetch_pois_pbf as pf   # lazy: pulls in osmium only when used
        with _lock:
            BUSY[region] = "downloading extract…"
        path = pf._download(region)
        with _lock:
            BUSY[region] = "parsing POIs (a few minutes)…"
        forts, scanned = pf._extract(path)
        with _lock:
            BUSY[region] = "merging into osm_forts.json…"
        try:
            with open(FORTS_FILE, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        have = {f["id"] for f in existing}
        merged = existing + [f for f in forts if f["id"] not in have]
        os.makedirs(DATA, exist_ok=True)
        tmp = FORTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"forts": merged}, fh, indent=1)
        os.replace(tmp, FORTS_FILE)
        added = len(merged) - len(existing)
        with _lock:
            done = _load_ledger()
            done.add(region)
            _save_ledger(done)
            _fort_count = len(merged)
            BUSY.pop(region, None)
            ERRORS.pop(region, None)
        # pois.py hot-reloads osm_forts.json by mtime, so the live server picks the
        # new forts up on the next map request -- no restart, nothing to call here.
        print(f"[downloads] {name}: +{added:,} forts ({scanned:,} scanned) -> "
              f"{len(merged):,} total", flush=True)
    except Exception as e:
        with _lock:
            BUSY.pop(region, None)
            ERRORS[region] = f"{type(e).__name__}: {e}"
        print(f"[downloads] {name} FAILED: {e}", flush=True)


def start(name, region):
    """Kick off a download in the background. No-op if it's already running."""
    with _lock:
        if region in BUSY:
            return False
        BUSY[region] = "starting…"
    threading.Thread(target=_do_populate, args=(name, region), daemon=True).start()
    return True


def _do_remove(name, region):
    """Undo a region: drop exactly the forts that region contributes.

    The region's own extract is re-parsed (from cache, no re-download) to get its
    fort ids, and those ids are subtracted from the live file. Fort ids are
    deterministic from OSM, so this removes precisely this region's stops/gyms and
    never a neighbour's, even where extracts overlap at a border.
    """
    global _fort_count
    try:
        import fetch_pois_pbf as pf
        with _lock:
            BUSY[region] = "finding this region's forts…"
        path = pf._download(region)            # cached from the original download
        forts, _ = pf._extract(path)
        ids = {f["id"] for f in forts}
        with _lock:
            BUSY[region] = "removing from osm_forts.json…"
        try:
            with open(FORTS_FILE, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        keep = [f for f in existing if f["id"] not in ids]
        removed = len(existing) - len(keep)
        os.makedirs(DATA, exist_ok=True)
        tmp = FORTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"forts": keep}, fh, indent=1)
        os.replace(tmp, FORTS_FILE)
        with _lock:
            done = _load_ledger()
            done.discard(region)
            _save_ledger(done)
            _fort_count = len(keep)
            BUSY.pop(region, None)
            ERRORS.pop(region, None)
        print(f"[downloads] {name}: -{removed:,} forts -> {len(keep):,} total", flush=True)
    except Exception as e:
        with _lock:
            BUSY.pop(region, None)
            ERRORS[region] = f"{type(e).__name__}: {e}"
        print(f"[downloads] remove {name} FAILED: {e}", flush=True)


def remove(name, region):
    """Kick off a region removal in the background. No-op if busy."""
    with _lock:
        if region in BUSY:
            return False
        BUSY[region] = "starting…"
    threading.Thread(target=_do_remove, args=(name, region), daemon=True).start()
    return True


def status():
    with _lock:
        return {
            "done": sorted(_load_ledger()),
            "busy": dict(BUSY),
            "errors": dict(ERRORS),
            "forts": _count_forts(),
        }
