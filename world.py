"""
World + player state for the PoGO private server, saved to disk.

MULTI-ACCOUNT: each username gets its own file in saves/<name>.json (bag, Pokemon,
XP, candy, storage...). The GYMS are deliberately SHARED in gyms.json, so two
accounts play in the same world and can see -- and battle -- each other's
defenders, the way the real game worked.

rpc.py calls use(username) at the top of every request. ThreadingHTTPServer gives
each request its own thread, so the "current player" is a thread-local and two
people playing at once never step on each other. Module-level names (world.BAG,
world.CANDY, ...) still work: a module __getattr__ forwards them to the player
whose request is being handled, so the rest of the server didn't have to change.
"""
import contextlib
import hashlib
import hmac
import json
import math
import os
import threading
import time

import random as _random
import sys as _sys

import settings as _cfg


import datadir

HERE = datadir.ensure()                           # <exe folder>/data
SAVE_FILE = os.path.join(HERE, "save.json")       # legacy single-player save
SAVES_DIR = os.path.join(HERE, "saves")           # one file per account
GYMS_FILE = os.path.join(HERE, "gyms.json")       # SHARED between accounts
LURES_FILE = os.path.join(HERE, "lures.json")     # SHARED between accounts

_lock = threading.RLock()
_current = threading.local()
_players = {}                                     # username -> Player

# TutorialCompletion steps 0..7 (LEGAL_SCREEN..FIRST_TIME_EXPERIENCE_COMPLETE).
# A trainer who has done all of these skips onboarding; an empty list runs it.
_TUTORIAL_COMPLETE = [0, 1, 2, 3, 4, 5, 6, 7]

# --- items -------------------------------------------------------------------
ITEM_POKE_BALL = 1
ITEM_GREAT_BALL = 2
ITEM_POTION = 101
ITEM_REVIVE = 201
ITEM_RAZZ_BERRY = 701

_STARTING_BAG = {ITEM_POKE_BALL: 50, ITEM_GREAT_BALL: 20,
                 ITEM_POTION: 20, ITEM_REVIVE: 10, ITEM_RAZZ_BERRY: 20}

# Real 2016 XP thresholds (PlayerLevelSettings.required_experience). These are
# the genuine 40 and are never generated -- levels 1-40 must cost exactly what
# they cost in the real game.
_LEVEL_XP_2016 = [0, 1000, 3000, 6000, 10000, 15000, 21000, 28000, 36000, 45000,
                  55000, 65000, 75000, 85000, 100000, 120000, 140000, 160000, 185000,
                  210000, 260000, 335000, 435000, 560000, 710000, 900000, 1100000,
                  1350000, 1650000, 2000000, 2500000, 3000000, 3750000, 4750000,
                  6000000, 7500000, 9500000, 12000000, 15000000, 20000000]

# PlayerStats.experience is a varint, but whether THIS client reads it as int32
# or int64 is unverified (POGOProtos disagrees with 0.29 often enough not to bet
# on it). Staying under the int32 ceiling is correct either way; past it the
# level ring can wrap into nonsense.
_XP_CEILING = 2_147_483_647

_LEVEL_XP_CACHE = None
_LEVEL_XP_KEY = None


def _build_level_xp():
    """The XP table, extended past 40 when max_level says so. Rebuilt only when
    the relevant settings change, since this is read on every XP award."""
    global _LEVEL_XP_CACHE, _LEVEL_XP_KEY
    try:
        cap = int(_cfg.get("progression", "max_level", cast=int))
        step = int(_cfg.get("progression", "level_xp_step", cast=int))
        accel = int(_cfg.get("progression", "level_xp_accel", cast=int))
    except Exception:
        cap, step, accel = 40, 2000000, 5000
    cap = max(1, min(500, cap))
    key = (cap, step, accel)
    if _LEVEL_XP_CACHE is not None and _LEVEL_XP_KEY == key:
        return _LEVEL_XP_CACHE
    table = list(_LEVEL_XP_2016[:cap])
    base = _LEVEL_XP_2016[-1]
    for lvl in range(len(_LEVEL_XP_2016) + 1, cap + 1):
        d = lvl - len(_LEVEL_XP_2016)
        table.append(min(_XP_CEILING, base + step * d + accel * d * d))
    _LEVEL_XP_CACHE, _LEVEL_XP_KEY = table, key
    return table


def max_level():
    return len(_build_level_xp())


class _LevelXP:
    """LEVEL_XP stayed a plain list for years and other code indexes/len()s it,
    so keep that shape while making it follow the configured cap."""

    def _t(self):
        return _build_level_xp()

    def __getitem__(self, i):
        return self._t()[i]

    def __len__(self):
        return len(self._t())

    def __iter__(self):
        return iter(self._t())


LEVEL_XP = _LevelXP()


def level_for_xp(xp):
    table = _build_level_xp()
    lvl = 1
    for i, need in enumerate(table):
        if xp >= need:
            lvl = i + 1
    return min(len(table), lvl)


def level_bounds(xp):
    table = _build_level_xp()
    lvl = level_for_xp(xp)
    prev = table[lvl - 1] if lvl - 1 < len(table) else table[-1]
    nxt = table[lvl] if lvl < len(table) else table[-1]
    return prev, nxt


def _safe_name(username):
    keep = "".join(c for c in (username or "player") if c.isalnum() or c in "-_")
    return (keep or "player")[:32].lower()


# ================================================================== the player
class Player:
    def __init__(self, username):
        self.username = username
        self.file = os.path.join(SAVES_DIR, _safe_name(username) + ".json")
        self.BAG = dict(_STARTING_BAG)
        self.CAUGHT = []
        self.CANDY = {}
        self.STARDUST = 5000
        self.XP = 0
        self.LEVEL = 1
        self.COINS = 0
        self.MAX_POKEMON = 250
        self.MAX_ITEMS = 350
        self.CLAIMED_LEVELS = []
        # uid -> ms it was removed. A GET_INVENTORY delta is ADDITIVE, so simply
        # dropping a Pokemon from CAUGHT does not delete it on the client -- the
        # client predicts the deletion locally and ROLLS IT BACK when the server
        # never confirms, which is why transferred Pokemon reappeared. We have to
        # keep reporting them as deleted for a while.
        self.DELETED = {}
        # pokemon_id -> [times_encountered, times_captured]. Without this the
        # Pokedex screen is simply empty, however much you catch.
        self.POKEDEX = {}
        # Eggs live apart from CAUGHT so nothing else (battles, transfers, the
        # box count) has to learn what an egg is. Each is
        # {uid, target_km, start_km, incubator}.
        self.EGGS = []
        # One unlimited incubator, exactly like the real game gave you.
        self.INCUBATORS = [{"id": "incubator-unlimited", "item": 901,
                            "uses": -1, "egg": 0, "start_km": 0.0,
                            "target_km": 0.0}]
        self.HATCHED = []        # hatched, not yet reported to the client
        self.LAST_POS = None     # (lat, lng) for the walked-distance tally
        self.TEAM = 0            # 0 = not chosen yet; set in game at level 5
        # Onboarding: which TutorialCompletion steps this trainer has finished.
        # DEFAULT COMPLETE so every account skips onboarding unless it is a brand
        # new one AND progression.run_tutorial is on (set in use()). An existing
        # save with no "tutorial" key is also treated as complete (see load_from),
        # so turning the tutorial on never drags a current player back through it.
        self.TUTORIAL = list(_TUTORIAL_COMPLETE)
        # The codename the trainer picked in the NAME_SELECTION step. Shown in game
        # (PlayerData.username) in preference to the login name when set.
        self.CODENAME = ""
        # Whether this trainer has used their FREE "make a PokeStop here" yet. The
        # first one costs nothing; after that each costs coins (see buy_stop).
        self.FREE_STOP_USED = False
        # ms of the last time the Shop's defender bonus (coins+stardust for gyms
        # you're holding) was collected -- gates the once-a-day cooldown.
        self.LAST_DEFENDER_BONUS = 0
        # Wild Pokemon this trainer has caught or that fled FROM THEM, so it
        # vanishes from THEIR map only -- other phones still see the shared spawn.
        # {encounter_id: expiry_ms}, transient (not saved; re-rolls with the world).
        self.DESPAWNED = {}
        self.BERRIES = {}        # encounter_id -> capture multiplier in effect
        self.PW = ""             # "salt$hash"; empty until the account is claimed
        self.APPLIED = []        # active Lucky Egg / Incense: {item, applied_ms, expires_ms}
        # Everything the Medals screen is scored on. The client draws each medal
        # from the badge list we return in GET_PLAYER_PROFILE, and that list is
        # computed from these counters against the game master's rank targets --
        # so a counter that is never bumped is a medal that never moves.
        self.STATS = {"pokemons_encountered": 0, "pokemons_captured": 0,
                      "poke_stop_visits": 0, "pokeballs_thrown": 0,
                      "unique_pokedex_entries": 0, "km_walked": 0.0,
                      "evolutions": 0, "eggs_hatched": 0,
                      "big_magikarp": 0, "small_rattata": 0, "pikachu_caught": 0,
                      "battle_attack_won": 0, "battle_attack_total": 0,
                      "battle_training_won": 0, "battle_training_total": 0,
                      "battle_defended_won": 0, "pokemon_deployed": 0}
        # HoloPokemonType -> how many of that type you've caught (a Pokemon with
        # two types counts for both, as it did in 2016).
        self.CAUGHT_BY_TYPE = {}
        # badge_type -> highest rank we've already shown the award popup for.
        self.BADGES = {}
        # Look: {avatar, skin, hair, shirt, pants, hat, shoes, eyes, backpack}.
        # Empty = use the defaults from settings.json.
        self.AVATAR = {}
        # "Let me pick in the game": holds AVATAR_SELECTION back from the
        # tutorial list so the client runs its own dress-up screen next launch.
        self.AVATAR_ASK = False

    def snapshot(self):
        return {"username": self.username,
                "bag": {str(k): v for k, v in self.BAG.items()},
                "caught": self.CAUGHT,
                "candy": {str(k): v for k, v in self.CANDY.items()},
                "stardust": self.STARDUST, "xp": self.XP, "level": self.LEVEL,
                "coins": self.COINS, "stats": self.STATS,
                "claimed_levels": self.CLAIMED_LEVELS,
                "deleted": {str(k): v for k, v in self.DELETED.items()},
                "pokedex": {str(k): list(v) for k, v in self.POKEDEX.items()},
                "team": self.TEAM, "pw": self.PW, "applied": self.APPLIED,
                "tutorial": list(self.TUTORIAL), "codename": self.CODENAME,
                "free_stop_used": self.FREE_STOP_USED,
                "last_defender_bonus": self.LAST_DEFENDER_BONUS,
                "eggs": self.EGGS, "incubators": self.INCUBATORS,
                "hatched": self.HATCHED,
                "caught_by_type": {str(k): v for k, v in self.CAUGHT_BY_TYPE.items()},
                "badges": {str(k): v for k, v in self.BADGES.items()},
                "avatar": self.AVATAR, "avatar_ask": self.AVATAR_ASK,
                "max_pokemon": self.MAX_POKEMON, "max_items": self.MAX_ITEMS}

    def save(self):
        try:
            os.makedirs(SAVES_DIR, exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.snapshot(), fh, indent=1)
            os.replace(tmp, self.file)     # atomic; never a half-written save
        except OSError:
            pass                           # a failed save must never break play

    def load_from(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return False
        self.BAG = {}
        for k, v in (d.get("bag") or {}).items():
            try:
                self.BAG[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        if not self.BAG:
            self.BAG = dict(_STARTING_BAG)
        self.CAUGHT = [c for c in (d.get("caught") or []) if isinstance(c, dict)]
        # Repair saves written while ids came from the spawn point: several
        # Pokemon could share one uid, and the client (which keys by uid) then
        # showed only one of them. Give the collisions fresh ids.
        seen = set()
        for c in self.CAUGHT:
            u = int(c.get("uid", 0) or 0)
            if not u or u in seen:
                u = _fresh_uid(seen)
                c["uid"] = u
            seen.add(u)
        self.CANDY = {}
        for k, v in (d.get("candy") or {}).items():
            try:
                self.CANDY[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.DELETED = {}
        for k, v in (d.get("deleted") or {}).items():
            try:
                self.DELETED[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.POKEDEX = {}
        for k, v in (d.get("pokedex") or {}).items():
            try:
                self.POKEDEX[int(k)] = [int(v[0]), int(v[1])]
            except (TypeError, ValueError, IndexError):
                pass
        # Backfill from the collection so an existing save doesn't show an empty
        # Pokedex for Pokemon that were caught before it was recorded.
        for c in self.CAUGHT:
            pid = int(c.get("pokemon_id", 0) or 0)
            if pid and pid not in self.POKEDEX:
                self.POKEDEX[pid] = [1, 1]
        self.TEAM = int(d.get("team", 0) or 0)
        # Old saves (written before onboarding existed) have no "tutorial" key --
        # treat them as fully done so a current player is never sent through it.
        self.TUTORIAL = sorted({int(x) for x in d.get("tutorial", _TUTORIAL_COMPLETE)
                                if str(x).lstrip("-").isdigit()})
        self.CODENAME = str(d.get("codename", "") or "")
        self.FREE_STOP_USED = bool(d.get("free_stop_used", False))
        self.LAST_DEFENDER_BONUS = int(d.get("last_defender_bonus", 0) or 0)
        self.PW = str(d.get("pw", "") or "")
        self.APPLIED = [a for a in (d.get("applied") or []) if isinstance(a, dict)]
        self.EGGS = [e for e in (d.get("eggs") or []) if isinstance(e, dict)]
        inc = [i for i in (d.get("incubators") or []) if isinstance(i, dict)]
        if inc:
            self.INCUBATORS = inc
        self.HATCHED = [h for h in (d.get("hatched") or []) if isinstance(h, dict)]
        self.STARDUST = int(d.get("stardust", self.STARDUST) or self.STARDUST)
        self.XP = int(d.get("xp", 0) or 0)
        self.COINS = int(d.get("coins", 0) or 0)
        self.MAX_POKEMON = int(d.get("max_pokemon", 250) or 250)
        self.MAX_ITEMS = int(d.get("max_items", 350) or 350)
        for k, v in (d.get("stats") or {}).items():
            if k in self.STATS:
                self.STATS[k] = v
        for k, v in (d.get("caught_by_type") or {}).items():
            try:
                self.CAUGHT_BY_TYPE[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        for k, v in (d.get("badges") or {}).items():
            try:
                self.BADGES[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        # Backfill the type tally from the collection, so a save made before
        # medals existed doesn't show every type medal at zero.
        if not self.CAUGHT_BY_TYPE:
            import protocol
            for c in self.CAUGHT:
                for t in protocol.pokemon_types(int(c.get("pokemon_id", 0) or 0)):
                    self.CAUGHT_BY_TYPE[t] = self.CAUGHT_BY_TYPE.get(t, 0) + 1
        self.AVATAR_ASK = bool(d.get("avatar_ask"))
        av = d.get("avatar")
        if isinstance(av, dict):
            self.AVATAR = {str(k): int(v) for k, v in av.items()
                           if str(v).lstrip("-").isdigit()}
        self.CLAIMED_LEVELS = [int(x) for x in (d.get("claimed_levels") or [])
                               if str(x).lstrip("-").isdigit()]
        self.LEVEL = level_for_xp(self.XP)
        if not self.CLAIMED_LEVELS:      # pre-existing save: don't replay old popups
            self.CLAIMED_LEVELS = list(range(1, self.LEVEL + 1))
        return True


_uid_rng = _random.Random()


def _fresh_uid(used):
    """An unused 63-bit Pokemon id."""
    while True:
        u = _uid_rng.getrandbits(62) | 1
        if u not in used:
            return u


def new_uid(seed=0):
    """A UNIQUE id for a newly caught Pokemon.

    This used to be `encounter_id ^ 0xC0FFEE`, which is derived from the spawn
    point and therefore repeats: catching at the same place twice produced the
    SAME id. The client keys Pokemon by id, so the second catch silently replaced
    the first instead of showing up, and transferring one removed only one of the
    duplicates while the rest kept it on screen.
    """
    p = current()
    with _lock:
        used = {int(c.get("uid", 0)) for c in p.CAUGHT} | set(p.DELETED)
        base = (int(seed) ^ 0xC0FFEE) & 0x3FFFFFFFFFFFFFFF
        return base if base and base not in used else _fresh_uid(used)


def use(username):
    """Make `username` the account for this request (called by rpc.py)."""
    name = username or "player"
    with _lock:
        p = _players.get(name)
        if p is None:
            p = Player(name)
            path = os.path.join(SAVES_DIR, _safe_name(name) + ".json")
            if os.path.exists(path):
                p.load_from(path)
            else:
                # No save for this account yet. If the old single-player save.json
                # is still around and nobody has claimed it, adopt it so an
                # existing collection carries over instead of starting from zero.
                have_any = os.path.isdir(SAVES_DIR) and any(
                    f.endswith(".json") for f in os.listdir(SAVES_DIR))
                if not have_any and os.path.exists(SAVE_FILE) and p.load_from(SAVE_FILE):
                    p.username = name
                else:
                    # A genuinely new trainer: run onboarding if it's switched on.
                    # (Adopted legacy saves keep their complete state above.)
                    try:
                        if _cfg.get("progression", "run_tutorial", cast=bool):
                            # Optionally pre-complete POKEMON_CAPTURE (step 3) so the
                            # slow scripted starter catch is skipped and the first
                            # catch is a normal fast wild encounter -- the rest of
                            # onboarding (legal/avatar/name/team) still runs.
                            if _cfg.get("progression", "tutorial_skip_starter", cast=bool):
                                p.TUTORIAL = [3]
                            else:
                                p.TUTORIAL = []
                    except Exception:
                        pass
                p.save()
            _players[name] = p
    _current.player = p
    return p


def current():
    p = getattr(_current, "player", None)
    if p is None:
        p = use("player")
    return p


def accounts():
    """Summary of every save on disk, for the World Manager."""
    out = []
    try:
        for fn in sorted(os.listdir(SAVES_DIR)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(SAVES_DIR, fn), encoding="utf-8") as fh:
                    d = json.load(fh)
                out.append({"username": d.get("username", fn[:-5]),
                            "level": level_for_xp(int(d.get("xp", 0) or 0)),
                            "xp": int(d.get("xp", 0) or 0),
                            "caught": len(d.get("caught") or []),
                            "coins": int(d.get("coins", 0) or 0)})
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return out


# module-level names (world.BAG, world.CANDY, ...) forward to the current player
_FORWARD = {"BAG", "CAUGHT", "CANDY", "STARDUST", "XP", "LEVEL", "COINS", "DELETED", "POKEDEX",
            "EGGS", "INCUBATORS", "HATCHED", "TEAM", "BERRIES", "APPLIED",
            "MAX_POKEMON", "MAX_ITEMS", "CLAIMED_LEVELS", "STATS",
            "CAUGHT_BY_TYPE", "BADGES", "AVATAR", "AVATAR_ASK"}


def __getattr__(name):
    if name in _FORWARD:
        return getattr(current(), name)
    raise AttributeError(name)


def save():
    current().save()


# ================================================= shared world (all accounts)
GYMS = {}                          # fort_id -> [{uid, pokemon_id, cp, trainer, team}]
# 2016 gym prestige -> level (1..10). A gym holds `level` defenders; attacking an
# enemy gym drains its prestige (dropping levels and ejecting the lowest defender,
# neutral at 0), training a friendly one raises it. fort_id -> prestige points.
# Shared across accounts, saved alongside GYMS in gyms.json.
PRESTIGE = {}
GYM_LEVELS = (0, 2000, 4000, 8000, 12000, 16000, 20000, 30000, 40000, 50000)
BATTLES = {}                       # battle_id -> live battle state
SPAWNS = {}                        # transient
DESPAWNED = {}                     # encounter_id -> expiry_ms
# Lures are attached to a FORT and are visible to everyone, so they live in the
# shared world rather than on one player. fort_id -> {item, expires_ms, by}
FORT_MODIFIERS = {}
# "Raid" mode: one boss standing in EVERY gym, shared by all accounts. 0.29 has
# no raid support at all, so this fakes it with the pieces the client does have --
# a gym defender under the trainer name "raid" that becomes a catchable wild
# Pokemon at your feet the moment you knock it out.
RAID = {"on": False, "pokemon_id": 150, "cp": 3000, "trainer": "raid"}
RAID_FILE = os.path.join(HERE, "raid.json")
BONUS_SPAWNS = {}                  # username -> [ {eid,pid,cp,lat,lng,expires_ms} ]
_MAX_SPAWNS = 4000


def save_gyms():
    try:
        tmp = GYMS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"gyms": GYMS, "prestige": PRESTIGE}, fh, indent=1)
        os.replace(tmp, GYMS_FILE)
    except OSError:
        pass


def _backfill_prestige():
    """A gym that has defenders but no prestige entry is one from before prestige
    existed -- give it enough to match its current defender count so it isn't
    instantly over capacity."""
    for fid, members in GYMS.items():
        if members and fid not in PRESTIGE:
            PRESTIGE[fid] = GYM_LEVELS[min(10, max(1, len(members))) - 1]


def load_gyms():
    try:
        with open(GYMS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.clear()
        GYMS.update({k: v for k, v in (d.get("gyms") or {}).items()
                     if isinstance(v, list)})
        PRESTIGE.clear()
        PRESTIGE.update({k: int(v) for k, v in (d.get("prestige") or {}).items()
                         if isinstance(v, (int, float))})
        _backfill_prestige()
        return True
    except (OSError, ValueError):
        pass
    try:                       # migrate gyms out of the old single-player save
        with open(SAVE_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.update({k: v for k, v in (d.get("gyms") or {}).items()
                     if isinstance(v, list)})
        if GYMS:
            _backfill_prestige()
            save_gyms()
    except (OSError, ValueError):
        pass
    return False


# --- spawns ------------------------------------------------------------------
def remember_spawn(encounter_id, pokemon_id, lat, lng, cp, spawn_id, expires_ms):
    with _lock:
        if len(SPAWNS) >= _MAX_SPAWNS:
            for k in sorted(SPAWNS, key=lambda k: SPAWNS[k]["expires_ms"])[:_MAX_SPAWNS // 2]:
                SPAWNS.pop(k, None)
        SPAWNS[encounter_id] = {"pokemon_id": pokemon_id, "lat": lat, "lng": lng,
                                "cp": cp, "spawn_id": spawn_id, "expires_ms": expires_ms}


def get_spawn(encounter_id):
    with _lock:
        # If THIS trainer already caught it (or it fled from them) it's gone for
        # them, even though the shared spawn still exists for other phones.
        if is_despawned(encounter_id):
            return None
        s = SPAWNS.get(encounter_id)
        return dict(s) if s else None


def remove_spawn(encounter_id):
    # PER-ACCOUNT: a catch/flee removes the Pokemon for THIS trainer only. It used
    # to pop the shared SPAWNS dict, which made it vanish on every other phone too.
    mark_despawned(encounter_id, int(time.time() * 1000) + 20 * 60 * 1000)


def mark_despawned(encounter_id, until_ms):
    p = current()
    with _lock:
        p.DESPAWNED[encounter_id] = until_ms
        if len(p.DESPAWNED) > 5000:
            now = int(time.time() * 1000)
            for k in [k for k, v in p.DESPAWNED.items() if v < now]:
                p.DESPAWNED.pop(k, None)


def is_despawned(encounter_id):
    p = current()
    with _lock:
        exp = p.DESPAWNED.get(encounter_id)
        if exp is None:
            return False
        if exp < int(time.time() * 1000):
            p.DESPAWNED.pop(encounter_id, None)
            return False
        return True


# --- bag ---------------------------------------------------------------------
def add_item(item_id, count):
    p = current()
    with _lock:
        p.BAG[item_id] = p.BAG.get(item_id, 0) + count
        n = p.BAG[item_id]
    p.save()
    return n


def take_item(item_id, count=1):
    p = current()
    with _lock:
        if p.BAG.get(item_id, 0) < count:
            return False
        p.BAG[item_id] -= count
    p.save()
    return True


def bag_items():
    p = current()
    with _lock:
        return [(i, c) for i, c in sorted(p.BAG.items()) if c > 0]


def bag_count():
    with _lock:
        return sum(current().BAG.values())


# --- caught pokemon ----------------------------------------------------------
def add_caught(uid, pokemon_id, cp):
    p = current()
    with _lock:
        p.DELETED.pop(int(uid), None)     # never report a live Pokemon as deleted
        p.CAUGHT.append({"uid": uid, "pokemon_id": pokemon_id, "cp": cp,
                         "caught_ms": int(time.time() * 1000)})
        p.STATS["pokemons_captured"] += 1
        p.STATS["pokeballs_thrown"] += 1
        p.STATS["unique_pokedex_entries"] = len({c["pokemon_id"] for c in p.CAUGHT})
        n = len(p.CAUGHT)
    p.save()
    return n


def caught():
    with _lock:
        return list(current().CAUGHT)


def get_caught(uid):
    with _lock:
        for c in current().CAUGHT:
            if c["uid"] == uid:
                return dict(c)
    return None


def update_caught(uid, **fields):
    p = current()
    with _lock:
        for c in p.CAUGHT:
            if c["uid"] == uid:
                c.update(fields)
                out = dict(c)
                break
        else:
            return None
    p.save()
    return out


def release(uid):
    if is_deployed(uid):
        return False, "deployed"
    p = current()
    with _lock:
        for i, c in enumerate(p.CAUGHT):
            if c["uid"] == uid:
                p.CAUGHT.pop(i)
                break
        else:
            return False, "not found"
        p.DELETED[int(uid)] = int(time.time() * 1000)
    p.save()
    return True, "ok"


def recent_deletions(max_age_ms=1800000):
    """Pokemon removed recently, so the inventory delta can keep confirming the
    deletion until the client has certainly seen it. Old entries are dropped so
    the list cannot grow without bound."""
    p = current()
    cutoff = int(time.time() * 1000) - max_age_ms
    with _lock:
        stale = [u for u, ts in p.DELETED.items() if ts < cutoff]
        for u in stale:
            p.DELETED.pop(u, None)
        return sorted(p.DELETED.items())


def stats():
    p = current()
    with _lock:
        return p.LEVEL, p.XP


def add_xp(n):
    p = current()
    n = int(n) * xp_multiplier()          # Lucky Egg
    with _lock:
        p.XP += n
        p.LEVEL = level_for_xp(p.XP)
    p.save()
    return p.XP


def bump(counter, n=1):
    p = current()
    with _lock:
        if counter in p.STATS:
            p.STATS[counter] += n
    p.save()


def bump_type(pokemon_id):
    """Count a catch towards the type medals (Bug Catcher, Fisherman, ...).
    Dual-type Pokemon count for both types."""
    import protocol
    p = current()
    with _lock:
        for t in protocol.pokemon_types(pokemon_id):
            p.CAUGHT_BY_TYPE[t] = p.CAUGHT_BY_TYPE.get(t, 0) + 1
    p.save()


def caught_by_type():
    with _lock:
        return dict(current().CAUGHT_BY_TYPE)


def badge_rank(badge_type):
    """Highest rank the player has already been shown the popup for."""
    with _lock:
        return int(current().BADGES.get(int(badge_type), 0))


def claim_badge(badge_type, rank):
    p = current()
    with _lock:
        p.BADGES[int(badge_type)] = int(rank)
    p.save()


def avatar():
    with _lock:
        return dict(current().AVATAR)


def avatar_ask(on=None):
    """Whether to let the client's own dress-up screen run next launch."""
    p = current()
    with _lock:
        if on is not None:
            p.AVATAR_ASK = bool(on)
    if on is not None:
        p.save()
    return p.AVATAR_ASK


def set_avatar(look):
    """Remember the look the client sent from the customisation screen."""
    p = current()
    clean = {}
    for k, v in (look or {}).items():
        try:
            clean[str(k)] = max(0, int(v))
        except (TypeError, ValueError):
            continue
    with _lock:
        p.AVATAR.update(clean)
        p.AVATAR_ASK = False           # they've chosen; stop asking
    p.save()
    return dict(p.AVATAR)


def add_coins(n):
    p = current()
    with _lock:
        p.COINS = max(0, p.COINS + n)
    p.save()
    return p.COINS


def level_claimed(level):
    with _lock:
        return int(level) in current().CLAIMED_LEVELS


def claim_level(level):
    p = current()
    with _lock:
        if int(level) not in p.CLAIMED_LEVELS:
            p.CLAIMED_LEVELS.append(int(level))
    p.save()


# --- candy / stardust --------------------------------------------------------
def add_candy(family, n):
    p = current()
    with _lock:
        p.CANDY[family] = p.CANDY.get(family, 0) + n
        out = p.CANDY[family]
    p.save()
    return out


def _hash_pw(password, salt=None):
    """PBKDF2 -- passwords are never stored in the clear, not even on a server
    that only your family can reach."""
    salt = salt or os.urandom(8).hex()
    h = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                            salt.encode("ascii"), 60000).hex()
    return f"{salt}${h}"


def check_login(username, password):
    """(ok, reason, name). The FIRST login for a name claims it and sets the
    password; after that the password has to match. An unknown name is claimed
    rather than refused, so a new trainer can just sign in and start playing."""
    name = (username or "").strip()
    if not name:
        return False, "no username", None
    real = next((n for n in account_names() if n.lower() == name.lower()), name)
    prev = getattr(_current, "player", None)
    try:
        p = use(real)
        if not p.PW:
            p.PW = _hash_pw(password)
            p.save()
            return True, "claimed", real
        salt = p.PW.split("$", 1)[0]
        if hmac.compare_digest(p.PW, _hash_pw(password, salt)):
            return True, "ok", real
        return False, "wrong password", real
    finally:
        _current.player = prev


def set_password(username, password):
    """Used by the World Manager to reset a forgotten password."""
    real = next((n for n in account_names() if n.lower() == (username or "").lower()),
                None)
    if not real:
        return False
    prev = getattr(_current, "player", None)
    try:
        p = use(real)
        p.PW = _hash_pw(password)
        p.save()
        return True
    finally:
        _current.player = prev


def has_password(username):
    real = next((n for n in account_names() if n.lower() == (username or "").lower()),
                None)
    if not real:
        return False
    prev = getattr(_current, "player", None)
    try:
        return bool(use(real).PW)
    finally:
        _current.player = prev


def account_names():
    """Every account we know of: loaded ones plus saved files."""
    names = set(_players)
    try:
        for fn in os.listdir(SAVES_DIR):
            if fn.endswith(".json") and not fn.startswith("_"):
                names.add(fn[:-len(".json")])
    except OSError:
        pass
    return sorted(names)


@contextlib.contextmanager
def acting_as(username):
    """Run a block as another account, on THIS thread only.

    The admin site runs on its own thread, so switching the thread-local player
    here cannot disturb an in-flight game request. Restores the previous player
    afterwards either way. Raises KeyError if the account has never been seen --
    we do NOT want a typo silently creating a new save.
    """
    name = (username or "").strip()
    if not name or name not in account_names():
        raise KeyError(name)
    prev = getattr(_current, "player", None)
    try:
        yield use(name)
    finally:
        _current.player = prev


# ------------------------------------------------------------------ EGGS
def km_walked():
    return float(current().STATS.get("km_walked", 0.0) or 0.0)


def add_distance(lat, lng):
    """Accumulate real walked distance from successive GPS fixes.

    Eggs only make sense if the distance is EARNED, so this is deliberately
    strict: a jump bigger than `max_step_m` is treated as a teleport (or GPS
    glitch) and contributes nothing, and sub-metre jitter is ignored so a
    stationary phone can't hatch an egg by trembling.
    """
    p = current()
    prev = p.LAST_POS
    p.LAST_POS = (lat, lng)
    if not prev:
        return 0.0
    dlat = (lat - prev[0]) * 111320.0
    dlng = ((lng - prev[1]) * 111320.0
            * math.cos(math.radians((lat + prev[0]) / 2.0)))
    metres = math.hypot(dlat, dlng)
    lo = _cfg.get("eggs", "min_step_m", cast=float)
    hi = _cfg.get("eggs", "max_step_m", cast=float)
    if metres < lo or metres > hi:
        return 0.0
    with _lock:
        p.STATS["km_walked"] = km_walked() + metres / 1000.0
    return metres


def eggs():
    with _lock:
        return [dict(e) for e in current().EGGS]


def incubators():
    with _lock:
        return [dict(i) for i in current().INCUBATORS]


def give_egg(target_km):
    """A new egg from a PokeStop. Returns None if the egg bag is full."""
    p = current()
    with _lock:
        if len(p.EGGS) >= _cfg.get("eggs", "max_eggs", cast=int):
            return None
        uid = _fresh_uid({c["uid"] for c in p.CAUGHT}
                         | {e["uid"] for e in p.EGGS} | set(p.DELETED))
        egg = {"uid": uid, "target_km": float(target_km),
               "start_km": 0.0, "incubator": ""}
        p.EGGS.append(egg)
    p.save()
    return dict(egg)


def use_incubator(incubator_id, egg_uid):
    """Put an egg in an incubator. Returns a UseItemEggIncubator result code:
    1=SUCCESS 2=NO_INCUBATOR 3=NO_EGG 4=NOT_AN_EGG 5=INCUBATOR_BUSY
    6=EGG_ALREADY_INCUBATING 7=NO_USES_LEFT."""
    p = current()
    with _lock:
        inc = next((i for i in p.INCUBATORS if i["id"] == incubator_id), None)
        if inc is None:
            return 2, None
        egg = next((e for e in p.EGGS if e["uid"] == egg_uid), None)
        if egg is None:
            return (4, None) if any(c["uid"] == egg_uid for c in p.CAUGHT) else (3, None)
        if inc.get("egg"):
            return 5, None
        if egg.get("incubator"):
            return 6, None
        if inc.get("uses", -1) == 0:
            return 7, None
        start = km_walked()
        egg["start_km"] = start
        egg["incubator"] = incubator_id
        inc.update(egg=egg_uid, start_km=start,
                   target_km=start + egg["target_km"])
    p.save()
    return 1, dict(inc)


def check_hatches(pick_species):
    """Hatch any egg that has covered its distance. `pick_species(target_km)`
    supplies the species so the rarity logic can live in protocol.py."""
    p = current()
    done = []
    with _lock:
        walked = km_walked()
        for egg in list(p.EGGS):
            if not egg.get("incubator"):
                continue
            if walked - egg["start_km"] < egg["target_km"]:
                continue
            tier = egg["target_km"]
            pid, cp = pick_species(tier)
            uid = _fresh_uid({c["uid"] for c in p.CAUGHT}
                             | {e["uid"] for e in p.EGGS} | set(p.DELETED))
            p.CAUGHT.append({"uid": uid, "pokemon_id": pid, "cp": cp,
                             "caught_ms": int(time.time() * 1000)})
            p.EGGS.remove(egg)
            for i in p.INCUBATORS:
                if i["id"] == egg["incubator"]:
                    i.update(egg=0, start_km=0.0, target_km=0.0)
                    if i.get("uses", -1) > 0:
                        i["uses"] -= 1
            xp = int(tier) * 100
            candy = 2 + int(tier)
            dust = int(tier) * 100
            rec = {"uid": uid, "pokemon_id": pid, "cp": cp, "km": tier,
                   "xp": xp, "candy": candy, "stardust": dust,
                   "egg_uid": egg["uid"]}
            p.HATCHED.append(rec)
            done.append(rec)
            p.STATS["eggs_hatched"] = p.STATS.get("eggs_hatched", 0) + 1
    if done:
        p.save()
    # A hatchling counts towards the type and species medals exactly like a
    # catch does. Done outside the lock -- bump_type takes it itself.
    for rec in done:
        import protocol
        protocol._score_medals(rec["pokemon_id"], rec["uid"])
    return done


def drain_hatched():
    """Hand the client the eggs that hatched since it last asked."""
    p = current()
    with _lock:
        out, p.HATCHED = list(p.HATCHED), []
    if out:
        p.save()
    return out


def pokedex_saw(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        e[0] += 1
    p.save()


def pokedex_caught(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        e[1] += 1
        if e[0] < e[1]:
            e[0] = e[1]          # caught implies seen
    p.save()


def pokedex():
    with _lock:
        return sorted((pid, v[0], v[1]) for pid, v in current().POKEDEX.items())


def apply_item(item_id, minutes):
    """Start a Lucky Egg / Incense. (result_code, entry): 1=SUCCESS,
    2=ALREADY_ACTIVE, 3=NONE_IN_INVENTORY."""
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        if any(a["item"] == int(item_id) for a in p.APPLIED):
            return 2, None
    if not take_item(int(item_id), 1):
        return 3, None
    entry = {"item": int(item_id), "applied_ms": now,
             "expires_ms": now + int(minutes * 60000)}
    with _lock:
        p.APPLIED.append(entry)
    p.save()
    return 1, dict(entry)


def applied_items():
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        return [dict(a) for a in p.APPLIED]


def item_active(item_id):
    return any(a["item"] == int(item_id) for a in applied_items())


def xp_multiplier():
    """A Lucky Egg doubles everything you earn while it burns."""
    return 2 if item_active(301) else 1


def save_lures():
    """Lures live in the shared world, so -- like gyms -- they need their own
    file. Without this a Lure the player SPENT an item on vanished the moment the
    server restarted, while Lucky Egg/Incense (stored in the per-player save)
    survived. Same 30 minutes, two different outcomes."""
    try:
        tmp = LURES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"lures": FORT_MODIFIERS}, fh, indent=1)
        os.replace(tmp, LURES_FILE)
    except OSError:
        pass


def load_lures():
    now = int(time.time() * 1000)
    try:
        with open(LURES_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return False
    FORT_MODIFIERS.clear()
    # Drop anything that burned out while the server was down -- a lure's timer
    # is wall-clock, so it does not pause for a restart.
    FORT_MODIFIERS.update({k: v for k, v in (d.get("lures") or {}).items()
                           if isinstance(v, dict) and v.get("expires_ms", 0) > now})
    return True


def add_fort_modifier(fort_id, item_id, minutes, by):
    """Attach a Lure to a PokeStop. 1=SUCCESS 2=ALREADY_HAS_ONE 4=NO_ITEM."""
    now = int(time.time() * 1000)
    with _lock:
        cur = FORT_MODIFIERS.get(fort_id)
        if cur and cur.get("expires_ms", 0) > now:
            return 2, None
    if not take_item(int(item_id), 1):
        return 4, None
    mod = {"item": int(item_id), "expires_ms": now + int(minutes * 60000), "by": by}
    with _lock:
        FORT_MODIFIERS[fort_id] = mod
    save_lures()
    return 1, dict(mod)


def fort_modifier(fort_id):
    now = int(time.time() * 1000)
    with _lock:
        m = FORT_MODIFIERS.get(fort_id)
        if not m:
            return None
        if m.get("expires_ms", 0) <= now:
            FORT_MODIFIERS.pop(fort_id, None)
            expired = True
        else:
            expired = False
            out = dict(m)
    if expired:
        save_lures()
        return None
    return out


def lured_forts():
    now = int(time.time() * 1000)
    with _lock:
        dead = [k for k, m in FORT_MODIFIERS.items()
                if m.get("expires_ms", 0) <= now]
        for fid in dead:
            FORT_MODIFIERS.pop(fid, None)
        out = {k: dict(v) for k, v in FORT_MODIFIERS.items()}
    # Only touch the disk when a lure actually burned out; this runs on every
    # map refresh.
    if dead:
        save_lures()
    return out


def add_stardust(n):
    """Stardust had no adder at all -- it could only ever be SPENT (spend()), so
    the total drifted down from its starting value and never up."""
    p = current()
    with _lock:
        p.STARDUST += int(n)
        out = p.STARDUST
    p.save()
    return out


def candy(family):
    with _lock:
        return current().CANDY.get(family, 0)


def spend(family=None, candy_n=0, dust_n=0):
    p = current()
    with _lock:
        if candy_n and p.CANDY.get(family, 0) < candy_n:
            return False
        if dust_n and p.STARDUST < dust_n:
            return False
        if candy_n:
            p.CANDY[family] = p.CANDY.get(family, 0) - candy_n
        if dust_n:
            p.STARDUST -= dust_n
    p.save()
    return True


# --- storage -----------------------------------------------------------------
def spend_coins(n):
    """Take PokeCoins for a shop purchase. False if there aren't enough."""
    p = current()
    with _lock:
        if p.COINS < int(n):
            return False
        p.COINS -= int(n)
    p.save()
    return True


def add_coins(n):
    p = current()
    with _lock:
        p.COINS += int(n)
        out = p.COINS
    p.save()
    return out


def buy_storage(kind):
    p = current()
    step = _cfg.get("storage", "pokemon_upgrade_step" if kind == "pokemon"
                    else "items_upgrade_step", cast=int)
    cost = _cfg.get("storage", "pokemon_upgrade_cost" if kind == "pokemon"
                    else "items_upgrade_cost", cast=int)
    cap = _cfg.get("storage", "max_pokemon_limit" if kind == "pokemon"
                   else "max_items_limit", cast=int)
    with _lock:
        cur = p.MAX_POKEMON if kind == "pokemon" else p.MAX_ITEMS
        if cur + step > cap:
            return False, f"already at the maximum ({cap})", cur
        if p.COINS < cost:
            return False, f"need {cost} PokeCoins, you have {p.COINS}", cur
        p.COINS -= cost
        if kind == "pokemon":
            p.MAX_POKEMON = cur + step
            new = p.MAX_POKEMON
        else:
            p.MAX_ITEMS = cur + step
            new = p.MAX_ITEMS
    p.save()
    return True, f"+{step} space for {cost} coins", new


def storage():
    p = current()
    with _lock:
        return {"max_pokemon": p.MAX_POKEMON, "max_items": p.MAX_ITEMS,
                "pokemon_used": len(p.CAUGHT), "items_used": sum(p.BAG.values()),
                "coins": p.COINS, "stardust": p.STARDUST}


# --- gyms (shared between accounts) ------------------------------------------
def _defender_minutes():
    return _cfg.get("gyms", "defender_minutes", env="DEFENDER_MINUTES", cast=float)


def _defender_coins():
    return _cfg.get("gyms", "defender_coins", env="DEFENDER_COINS", cast=int)


def _max_defenders():
    return _cfg.get("gyms", "max_defenders", cast=int)


def my_team():
    """The team this trainer picked in game. Falls back to the settings value for
    accounts created before teams could be chosen."""
    t = current().TEAM
    return t if t else _cfg.get("gyms", "team", env="TEAM", cast=int)


def tutorial_steps():
    """The TutorialCompletion steps this trainer has finished. Empty = run the
    whole new-trainer onboarding; [0..7] = skip straight to the map."""
    return sorted(set(current().TUTORIAL))


def mark_tutorial(steps):
    """Record onboarding steps the client just reported complete."""
    p = current()
    add = [int(s) for s in (steps or []) if str(s).lstrip("-").isdigit()]
    if not add:
        return
    with _lock:
        p.TUTORIAL = sorted(set(p.TUTORIAL) | set(add))
    p.save()


def codename():
    return current().CODENAME or ""


def set_codename(name):
    """The trainer's chosen in-game name (NAME_SELECTION step)."""
    p = current()
    with _lock:
        p.CODENAME = str(name or "")[:15]
    p.save()
    return p.CODENAME


def buy_stop(cost):
    """Pay for a 'make a PokeStop here'. The FIRST one is free; after that it costs
    `cost` PokeCoins. Returns (ok, charged, reason)."""
    p = current()
    with _lock:
        if not p.FREE_STOP_USED:
            p.FREE_STOP_USED = True
            p.save()
            return True, 0, "first one free"
    if spend_coins(cost):
        return True, cost, "ok"
    return False, cost, f"need {cost} PokeCoins, you have {p.COINS}"


def set_team(team):
    """SetPlayerTeam. Returns (status, team): 1=SUCCESS, 2=TEAM_ALREADY_SET."""
    p = current()
    with _lock:
        if p.TEAM:
            return 2, p.TEAM
        p.TEAM = max(1, min(3, int(team)))
        out = p.TEAM
    p.save()
    return 1, out


def use_berry(encounter_id, mult):
    """Remember that a berry is in effect for this encounter."""
    current().BERRIES[int(encounter_id)] = float(mult)


def berry_mult(encounter_id, consume=False):
    p = current()
    m = p.BERRIES.get(int(encounter_id), 1.0)
    if consume:
        p.BERRIES.pop(int(encounter_id), None)
    return m


def pokemon_full():
    p = current()
    return len(p.CAUGHT) + len(p.EGGS) >= p.MAX_POKEMON


def bag_count():
    return sum(current().BAG.values())


def bag_full():
    return bag_count() >= current().MAX_ITEMS


def room_in_bag():
    return max(0, current().MAX_ITEMS - bag_count())


def _raid_member(fort_id):
    """The boss that stands in every gym while raid mode is on. Its uid is derived
    from the fort so it is stable per gym and never collides with a real Pokemon."""
    uid = (abs(hash(("raid", fort_id))) & 0x3FFFFFFFFFFFFFFF) | 1
    return {"uid": uid, "pokemon_id": int(RAID["pokemon_id"]),
            "cp": int(RAID["cp"]), "trainer": RAID.get("trainer", "raid"),
            "team": 0, "raid": True, "deployed_ms": int(time.time() * 1000)}


def is_raid_uid(fort_id, uid):
    return RAID["on"] and _raid_member(fort_id)["uid"] == uid


def gym_members(fort_id):
    with _lock:
        if RAID["on"]:
            # The boss REPLACES whatever was defending. Real defenders were sent
            # home when raid mode was switched on, so nothing is lost.
            return [_raid_member(fort_id)]
        return list(GYMS.get(fort_id, []))


def load_raid():
    global RAID
    try:
        with open(RAID_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        RAID.update({"on": bool(d.get("on", False)),
                     "pokemon_id": int(d.get("pokemon_id", 150) or 150),
                     "cp": int(d.get("cp", 3000) or 3000),
                     "trainer": str(d.get("trainer", "raid") or "raid")})
    except (OSError, ValueError, TypeError):
        pass
    return dict(RAID)


def save_raid():
    try:
        tmp = RAID_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(RAID, fh, indent=1)
        os.replace(tmp, RAID_FILE)
    except OSError:
        pass


def set_raid(on=None, pokemon_id=None, cp=None, trainer=None):
    """Turn raid mode on/off. Switching it ON sends every deployed Pokemon home
    first, so nobody loses a defender to the boss taking its place."""
    sent_home = 0
    with _lock:
        if on is not None:
            RAID["on"] = bool(on)
        if pokemon_id is not None:
            RAID["pokemon_id"] = max(1, min(151, int(pokemon_id)))
        if cp is not None:
            RAID["cp"] = max(10, min(9999, int(cp)))
        if trainer is not None:
            RAID["trainer"] = str(trainer)[:16] or "raid"
        if RAID["on"]:
            sent_home = sum(len(v) for v in GYMS.values())
            GYMS.clear()
            PRESTIGE.clear()
    save_gyms()
    save_raid()
    return dict(RAID), sent_home


def raid():
    with _lock:
        return dict(RAID)


def add_bonus_spawn(username, eid, pid, cp, lat, lng, expires_ms):
    """A one-off wild Pokemon placed for ONE trainer -- the defeated raid boss
    dropping at your feet. Kept per account so it doesn't appear for everyone."""
    with _lock:
        lst = BONUS_SPAWNS.setdefault(username, [])
        lst.append({"eid": eid, "pid": pid, "cp": cp, "lat": lat, "lng": lng,
                    "expires_ms": expires_ms})
        del lst[:-10]


def bonus_spawns(username):
    now = int(time.time() * 1000)
    with _lock:
        lst = [b for b in BONUS_SPAWNS.get(username, []) if b["expires_ms"] > now]
        BONUS_SPAWNS[username] = lst
        return [dict(b) for b in lst]


def drop_bonus_spawn(username, eid):
    with _lock:
        lst = BONUS_SPAWNS.get(username, [])
        BONUS_SPAWNS[username] = [b for b in lst if b["eid"] != eid]


def gym_team(fort_id):
    """Which team holds this gym (0 = neutral/white)."""
    ms = gym_members(fort_id)
    return ms[0].get("team", 0) if ms else 0


def _level_for(prestige):
    lvl = 1
    for i, thr in enumerate(GYM_LEVELS):
        if prestige >= thr:
            lvl = i + 1
    return max(1, min(10, lvl))


def gym_prestige(fort_id):
    with _lock:
        return int(PRESTIGE.get(fort_id, 0))


def gym_level(fort_id):
    """A gym's level, 1..10, derived from its prestige (also its defender slots)."""
    return _level_for(gym_prestige(fort_id))


def gym_capacity(fort_id):
    return gym_level(fort_id)


def prestige_for_defeat(atk_cp, def_cp):
    """Prestige swing for beating one defender. Scales with the CP you were up
    against, so toppling a stronger Pokemon is worth more (2016 behaviour)."""
    ratio = (int(def_cp or 0) or 1) / max(1, int(atk_cp or 0) or 1)
    return int(max(400, min(2500, 800 * (0.4 + ratio))))


def add_prestige(fort_id, delta):
    """Apply the prestige change from a finished battle. Positive = training a
    friendly gym up; negative = an attack draining it. Returns
    (new_prestige, new_level, ejected_members); at <=0 the gym goes NEUTRAL (every
    defender sent home) so the winner can claim it with a fresh deploy."""
    ejected = []
    with _lock:
        new = int(PRESTIGE.get(fort_id, 0)) + int(delta)
        if new <= 0:
            ejected = list(GYMS.get(fort_id, []))
            GYMS.pop(fort_id, None)
            PRESTIGE.pop(fort_id, None)
            level, new = 1, 0
        else:
            PRESTIGE[fort_id] = new
            level = _level_for(new)
            members = GYMS.get(fort_id, [])
            over = len(members) - level
            if over > 0:                      # a level-down kicks out the weakest
                lowest = sorted(members, key=lambda m: m.get("cp", 0))[:over]
                drop = {m["uid"] for m in lowest}
                GYMS[fort_id] = [m for m in members if m["uid"] not in drop]
                ejected = lowest
    save_gyms()
    return new, level, ejected


def is_deployed(uid):
    with _lock:
        return any(m["uid"] == uid for ms in GYMS.values() for m in ms)


def deployed_fort(uid):
    """The fort_id this Pokemon is defending, or None. The client counts your
    defenders by which Pokemon in the inventory carry a deployed_fort_id, and it
    greys the Shop's defender-bonus shield (never even sends the collect request)
    when that count is zero -- so this is what makes the shield collectable."""
    with _lock:
        for fid, ms in GYMS.items():
            if any(m["uid"] == uid for m in ms):
                return fid
    return None


def deploy(fort_id, uid, trainer=None, team=None):
    p = current()
    trainer = trainer or p.username
    team = team if team is not None else my_team()
    c = get_caught(uid)
    if not c:
        return False, "unknown pokemon"
    with _lock:
        members = GYMS.setdefault(fort_id, [])
        if members and members[0].get("team", team) != team:
            return False, "held by another team"
        if any(m["uid"] == uid for m in members):
            return False, "already deployed"
        # Slots scale with the gym's level (its prestige), not a flat cap -- a fresh
        # gym holds one, and it must be TRAINED up before more can join. Computed
        # inline because we already hold _lock here.
        if len(members) >= _level_for(int(PRESTIGE.get(fort_id, 0))):
            return False, "gym full"
        members.append({"uid": uid, "pokemon_id": c["pokemon_id"], "cp": c["cp"],
                        "trainer": trainer, "team": team, "owner": p.username,
                        "deployed_ms": int(time.time() * 1000)})
    save_gyms()
    return True, "ok"


def recall(fort_id, uid):
    with _lock:
        members = GYMS.get(fort_id, [])
        n = len(members)
        GYMS[fort_id] = [m for m in members if m["uid"] != uid]
        changed = n != len(GYMS[fort_id])
        if not GYMS[fort_id]:
            GYMS.pop(fort_id, None)
    save_gyms()
    return changed


def clear_gym(fort_id):
    """Every defender is knocked out -- the gym goes neutral."""
    with _lock:
        GYMS.pop(fort_id, None)
    save_gyms()


def gym_guard(fort_id):
    ms = gym_members(fort_id)
    if not ms:
        return None
    best = max(ms, key=lambda m: m.get("cp", 0))
    return best["pokemon_id"], best["cp"], 500 * len(ms)


def collect_gym_returns():
    """Bring home any Pokemon that has served its shift and pay its coins. Only
    the account that OWNS a defender gets paid for it."""
    now = int(time.time() * 1000)
    cutoff = _defender_minutes() * 60_000
    coins = _defender_coins()
    faint = _cfg.get("pokemon", "faint_after_gym", cast=bool)
    returned = []
    with _lock:
        for fid in list(GYMS):
            keep = []
            for m in GYMS.get(fid, []):
                dep = m.get("deployed_ms")
                if dep is None:
                    m["deployed_ms"] = now
                    keep.append(m)
                elif now - dep >= cutoff:
                    returned.append((fid, m["pokemon_id"], coins,
                                     m.get("owner"), m["uid"]))
                else:
                    keep.append(m)
            if keep:
                GYMS[fid] = keep
            else:
                GYMS.pop(fid, None)
    mine = []
    if returned:
        save_gyms()
        me = current()
        for fid, pid, c, owner, uid in returned:
            if owner and owner != me.username:
                continue                    # someone else's defender; they get paid
            with _lock:
                me.COINS += c
                if faint:
                    for pk in me.CAUGHT:
                        if pk["uid"] == uid:
                            pk["stamina"] = 0
                            break
            mine.append((fid, pid, c))
        if mine:
            me.save()
    return mine


def time_left(fort_id, uid):
    for m in gym_members(fort_id):
        if m["uid"] == uid:
            dep = m.get("deployed_ms") or 0
            return max(0, int(_defender_minutes() * 60 - (time.time() - dep / 1000)))
    return 0


def my_defended_gyms():
    """How many DISTINCT gyms this account currently has a Pokemon defending.
    The defender bonus pays per gym, not per Pokemon, exactly as it did in 2016."""
    me = current().username
    with _lock:
        return sum(1 for ms in GYMS.values()
                   if any(m.get("owner") == me for m in ms))


def defender_bonus_next_ms():
    """The timestamp (ms) at which this account may next collect the Shop defender
    bonus. In the past (or now) => collectable right now; the client greys the
    shield until this moment. A never-collected account (LAST_DEFENDER_BONUS = 0)
    lands in 1970, so the shield is live from the first login."""
    cooldown_ms = _cfg.get("gyms", "defender_bonus_cooldown_hours", cast=float) * 3_600_000
    return int(current().LAST_DEFENDER_BONUS or 0) + int(cooldown_ms)


def collect_defender_bonus():
    """The Shop's shield: coins + stardust for every gym you're holding, once a
    day. Returns (result, coins, stardust, gyms):
      result 1=SUCCESS 3=TOO_SOON 4=NO_DEFENDERS   (matches the client's enum).
    On SUCCESS the coins/stardust are already banked and the cooldown is armed."""
    coin_each = _cfg.get("gyms", "defender_bonus_coins", cast=int)
    dust_each = _cfg.get("gyms", "defender_bonus_stardust", cast=int)
    cap = _cfg.get("gyms", "defender_bonus_max_gyms", cast=int)
    cooldown_ms = _cfg.get("gyms", "defender_bonus_cooldown_hours", cast=float) * 3_600_000
    now = int(time.time() * 1000)
    p = current()
    gyms = min(my_defended_gyms(), max(1, cap))
    if gyms <= 0:
        return 4, 0, 0, 0                              # NO_DEFENDERS
    if now - int(p.LAST_DEFENDER_BONUS or 0) < cooldown_ms:
        return 3, 0, 0, gyms                           # TOO_SOON
    coins, dust = coin_each * gyms, dust_each * gyms
    with _lock:
        p.COINS += coins
        p.STARDUST += dust
        p.LAST_DEFENDER_BONUS = now
    p.save()
    return 1, coins, dust, gyms


load_gyms()
load_raid()
load_lures()
