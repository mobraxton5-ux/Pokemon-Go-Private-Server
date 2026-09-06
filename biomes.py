"""
Biomes -- geography-flavoured wild spawns for the PoGO private server.

The real 2016 game grouped wild spawns into "biomes" tied to the terrain around
you (the Silph Road community mapped this out: water Pokemon by rivers/coasts,
rock/ground on mountains, city trash downtown, ...). An offline server has no map
data to read the terrain from, so instead we assign every REGION a biome
deterministically from its location: a coarse S2 cell (a few km across) hashes to
one biome, so a given neighbourhood always has the same flavour and the world
feels varied and consistent as you walk between areas -- which is exactly what the
biome system felt like to play.

This module is deliberately data-only + pure functions: it knows which TYPES a
biome favours and which biome a location is in. protocol.py owns the actual
species tables (it already has the base rarity tiers and the game master's
per-species types) and just asks us for the type boosts to apply.

Type values are HoloPokemonType (POGOProtos), which is what convert_gm.py wrote
into game_master.bin and what protocol.pokemon_types() reads back -- so the
numbers here line up with the served data. If a value were ever off the only cost
is a less thematic biome (the base pool still contains every species), never a
broken spawn.
"""

import s2sphere

# HoloPokemonType
NORMAL, FIGHTING, FLYING, POISON, GROUND, ROCK, BUG, GHOST, STEEL = range(1, 10)
FIRE, WATER, GRASS, ELECTRIC, PSYCHIC, ICE, DRAGON, DARK, FAIRY = range(10, 19)

# Each biome favours a handful of types. The number is how much more likely a
# species of that type is to appear here, applied on TOP of its normal rarity, so
# a rare water Pokemon is still rarer than a common one -- the biome just decides
# WHICH types dominate, not which individuals ignore rarity. A species takes the
# strongest boost among its (one or two) types; everything else spawns at its
# normal low-but-present rate, so no area is ever empty of the usual city trash.
BIOMES = {
    # by water: rivers, lakes, coast
    "water":      {WATER: 9, ICE: 5, FLYING: 2},
    # open grass, parks, fields
    "grassland":  {GRASS: 7, NORMAL: 4, BUG: 3, FAIRY: 3},
    # dense woods
    "forest":     {BUG: 8, GRASS: 5, POISON: 4, FAIRY: 2},
    # hills, cliffs, quarries
    "mountain":   {ROCK: 8, GROUND: 6, FIGHTING: 4, FIRE: 3},
    # downtown: concrete, cables, sewers
    "city":       {NORMAL: 5, ELECTRIC: 6, POISON: 5, STEEL: 4, GHOST: 4},
    # bogs, riverbanks, rice paddies
    "wetland":    {WATER: 6, POISON: 5, GROUND: 4, GRASS: 4, BUG: 3},
    # dry, sandy, hot
    "desert":     {GROUND: 8, ROCK: 6, FIRE: 5},
    # houses, gardens, quiet streets
    "suburban":   {NORMAL: 6, FAIRY: 4, ELECTRIC: 3, PSYCHIC: 3},
}

BIOME_NAMES = list(BIOMES)


def type_boosts(biome):
    """{type_value: multiplier} for a biome. Empty for an unknown biome, which
    leaves the base rarity pool untouched (a perfectly good 'no biome' fallback)."""
    return BIOMES.get(biome, {})


def _mix(n):
    """A stable 64-bit hash (Python's hash() is salted per process, so a cell
    would land in a different biome every restart -- the world has to be the same
    place tomorrow that it was today)."""
    n &= (1 << 64) - 1
    n ^= n >> 33
    n = (n * 0xFF51AFD7ED558CCD) & ((1 << 64) - 1)
    n ^= n >> 33
    n = (n * 0xC4CEB9FE1A85EC53) & ((1 << 64) - 1)
    n ^= n >> 33
    return n


# ---- REAL terrain from OSM (data/osm_biomes.json, made by fetch_osm_biomes.py) --
# A list of {lat,lng,biome} points; a location takes the biome of the nearest one
# within _MAX_M. Where there's no OSM terrain nearby (rural gaps), we fall back to
# the deterministic hash model, so the world is still varied everywhere.
import json
import math
import os
import threading

import datadir

_TERRAIN_FILE = os.path.join(datadir.ensure(), "osm_biomes.json")
_MAX_M = 1500.0
_tlock = threading.RLock()
_terrain = {"mtime": None, "pts": []}
# National coverage: a precomputed {level-`cell_level` S2 cell id -> biome} map from
# fetch_us_biomes.py, looked up in O(1) by the same cell biome_for already computes.
# This scales to the whole US where the nearest-point scan above never could.
_cells = {"mtime": None, "map": {}, "level": 12}
_cache = {}                      # region-cell id -> biome name (memoised lookups)


def _load_cells():
    try:
        m = os.path.getmtime(_TERRAIN_FILE)
    except OSError:
        m = None
    with _tlock:
        if _cells["mtime"] != m:
            cmap, lvl = {}, 12
            if m is not None:
                try:
                    with open(_TERRAIN_FILE, "r", encoding="utf-8") as fh:
                        d = json.load(fh)
                    lvl = int(d.get("cell_level", 12))
                    for k, v in (d.get("cells") or {}).items():
                        cmap[int(k)] = str(v)
                except (OSError, ValueError, KeyError, TypeError):
                    cmap = {}
            _cells["mtime"], _cells["map"], _cells["level"] = m, cmap, lvl
            _cache.clear()
        return _cells["map"], _cells["level"]


def _load_terrain():
    try:
        m = os.path.getmtime(_TERRAIN_FILE)
    except OSError:
        m = None
    with _tlock:
        if _terrain["mtime"] != m:
            pts = []
            if m is not None:
                try:
                    with open(_TERRAIN_FILE, "r", encoding="utf-8") as fh:
                        for p in (json.load(fh).get("points") or []):
                            pts.append((float(p["lat"]), float(p["lng"]),
                                        str(p["biome"])))
                except (OSError, ValueError, KeyError, TypeError):
                    pts = []
            _terrain["mtime"], _terrain["pts"] = m, pts
            _cache.clear()       # data changed -> drop memoised biomes
        return _terrain["pts"]


def _terrain_biome(lat, lng):
    pts = _load_terrain()
    if not pts:
        return None
    cosl = max(0.2, math.cos(math.radians(lat)))
    best, bestd = None, _MAX_M
    for plat, plng, b in pts:
        d = math.hypot((plat - lat) * 111320.0, (plng - lng) * 111320.0 * cosl)
        if d < bestd:
            best, bestd = b, d
    return best


# ---- NESTS + day/night ------------------------------------------------------
# 2016 nests: a patch of the map spawns mostly ONE species, and which species
# rotates on a cycle. We make ~1 in 3 regions a nest, picking from the classic
# nestable species, and rotate them every `rotation_days`.
NEST_SPECIES = [1, 4, 7, 25, 133, 147, 66, 63, 129, 92, 41, 74, 60, 72, 98, 116,
                43, 46, 48, 27, 21, 16, 19, 39, 37, 58, 88, 100, 104, 109]


def nest_species(lat, lng, now_ms, level=12, rotation_days=14):
    """The nest species for this region right now, or 0 if the region isn't a
    nest. Stable for the whole `rotation_days` window, then it rotates."""
    try:
        cid = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(int(level)).id()
    except Exception:
        return 0
    period = int(now_ms // (max(1, int(rotation_days)) * 86_400_000))
    if _mix(cid ^ 0x4E455354) % 8 != 0:            # only ~1 region in 8 is a nest
        return 0
    idx = _mix(cid ^ (period * 0x9E3779B97F4A7C15)) % len(NEST_SPECIES)
    return NEST_SPECIES[idx]


# Species that come out mostly after dark / mostly in daylight (2016 behaviour).
NIGHT_SPECIES = {41, 42, 92, 93, 94, 43, 44, 45, 96, 97, 104, 105, 37, 38, 52, 53,
                 35, 36, 39, 40, 46, 47, 48, 49, 66, 24}
DAY_SPECIES = {10, 11, 12, 13, 14, 15, 16, 17, 19, 21, 25, 46, 48, 63, 69, 60, 1,
               4, 7, 123, 127, 128}


def is_night(now_ms, lng=0.0):
    """Rough local night at the player's longitude (15 deg per hour), so it works
    regardless of the server's own timezone. Night = before 6am or after 8pm."""
    import time
    t = time.gmtime(now_ms / 1000.0)
    local_h = (t.tm_hour + t.tm_min / 60.0 + float(lng) / 15.0) % 24.0
    return local_h < 6.0 or local_h >= 20.0


def biome_for(lat, lng, level=12, salt=0):
    """The biome at a location. Uses the REAL terrain of the nearest OSM feature
    when we have data; otherwise a deterministic hash so a whole level-`level` S2
    cell (~3 km at 12) shares one biome. Memoised per region cell."""
    try:
        cid = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(int(level)).id()
    except Exception:
        return BIOME_NAMES[0]
    with _tlock:
        hit = _cache.get(cid)
    if hit is not None:
        return hit
    # Classify at the region cell's CENTRE so the whole cell is one biome.
    ctr = s2sphere.CellId(cid).to_lat_lng()
    # 1) nearest real terrain point (finest, from fetch_osm_biomes for a region)
    b = _terrain_biome(ctr.lat().degrees, ctr.lng().degrees)
    if b is None:
        # 2) the national cell map (fetch_us_biomes) -- direct lookup when this cell
        #    is at the map's level, else re-key the centre to that level.
        cmap, lvl = _load_cells()
        if cmap:
            key = cid if lvl == int(level) else s2sphere.CellId.from_lat_lng(ctr).parent(lvl).id()
            b = cmap.get(key)
    if b is None:
        # 3) deterministic hash, so rural gaps are still varied and consistent
        b = BIOME_NAMES[_mix(cid ^ (int(salt) * 0x9E3779B97F4A7C15)) % len(BIOME_NAMES)]
    with _tlock:
        _cache[cid] = b
    return b
