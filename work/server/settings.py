"""
settings.json -- the one file you edit by hand to tune how the game plays.

Written next to the .exe on first run, complete with a built-in explanation of
every value. Hot-reloaded by mtime, so saving the file applies within a few
seconds; no restart needed.

Precedence: environment variable > settings.json > built-in default. (The env
vars stayed supported so older shortcuts/batch files keep working.)

Things the World Manager UI owns -- placed stops/gyms (places.json) and the live
event (events.json) -- deliberately live elsewhere, so hand-edits here are never
fighting the web UI.
"""
import json
import os
import time
import sys
import threading

import datadir

SETTINGS_FILE = datadir.path("settings.json")

# Every tunable, with the shape the file is written in. Keep the comments here in
# sync with the "_readme" block below -- that's what the user actually reads.
DEFAULTS = {
    "catching": {
        "xp_per_catch": 100,
        "candy_per_catch": 3,
        "stardust_per_catch": 100,
        "xp_nice_throw": 500,
        "xp_great_throw": 1000,
        "xp_excellent_throw": 2000,
        "xp_curveball": 10,
        "fast_catch": False,        # true = one throw, one wobble, no escapes
        "base_catch_rate": 0.55,    # chance a Poke Ball holds a weak Pokemon
        "flee_chance": 0.12,        # chance it runs off after breaking out
        "razz_capture_mult": 1.8,   # how much a Razz Berry helps
        "razz_flee_mult": 0.4,      # ...and how much less likely it is to flee
        # The ball wobbles more the higher the capture chance we report to the
        # client (its GetNumShakes reads it). Resisting Pokemon have low real odds,
        # so they used to break out on the FIRST shake -- this floors the number we
        # report so a break-out rocks ~2-3 times first. Only the animation/ring is
        # affected; the true catch odds below are untouched. Lower it for snappier
        # break-outs, raise it (toward 1.0) for longer ones.
        "min_shake_probability": 0.7,
        # OFF, and best left off on this build: the Nice/Great/Excellent tier
        # already comes from the RING size the client reports at the moment the
        # ball lands, so hitting the circle is what earns the bonus -- a miss sends
        # a loose ring and scores nothing. Turning this on adds a SECOND gate on
        # normalized_hit_position, but this client reports ~99% of tight throws as
        # "in circle" regardless of where the ball went, so it only ends up
        # withholding bonuses from good throws. Left here (with its sense/tolerance)
        # only in case a different client actually populates hit_position.
        "require_ball_in_circle": False,
        "throw_accuracy_sense": "center_is_zero",   # or "center_is_one"
        "throw_accuracy_tolerance": 0.5,
    },
    "pokestops": {
        "per_l15_cell": 1,          # PokeStops per level-15 cell (~300m across)
        "max_per_request": 200,     # safety cap on one GetMapObjects batch
        # false (default) = PokeStops/Gyms sit at fixed geographic spots and stay
        # put as you pass them. true = also drop a trio (2 stops + a gym) right at
        # your feet -- handy standing still, but it re-spawns as you move, so DRIVING
        # spams stops/gyms down the whole road. Leave off unless you play stationary.
        "anchor_near_player": False,
        # true = use real OpenStreetMap places (data/osm_forts.json, made by
        # tools/fetch_osm_pois.py) as your PokeStops/Gyms -- on actual buildings,
        # off the roads. When that file has forts, the random procedural ones are
        # turned off. false (or no file) = fall back to procedural placement.
        "use_osm": True,
        "xp_per_spin": 50,
        "cooldown_minutes": 5,
        "min_items_per_spin": 5,        # a spin never gives fewer items than this
        "max_items_per_spin": 8,
        "great_ball_chance": 0.30,      # Great Balls turn up now and then
        "ultra_ball_chance": 0.10,      # Ultra Balls are rarer
        "razz_berry_chance": 0.35,
    },
    "gyms": {
        "chance_per_l15_cell": 0.25,   # ~1 gym per 4 level-15 cells
        # true = trainers pick their own team in game at level 5 (Mystic/Valor/
        # Instinct), the real 2016 way. false = everyone is auto-assigned the
        # "team" below and the choice screen never shows. Note: with this on, an
        # account that never chose (all existing ones) is asked once, next time
        # it's level 5+.
        "let_players_choose": True,
        "team": 1,                     # the auto-assigned team when choosing is off
        "defender_minutes": 15,
        "defender_coins": 20,
        "max_defenders": 6,
        # The Shop's shield ("defender bonus"): what you collect per gym you're
        # holding, once every `cooldown_hours`, up to `max_gyms` gyms. The 2016
        # values were 10 coins + 500 stardust per gym, 10-gym cap, 21-hour timer.
        "defender_bonus_coins": 10,
        "defender_bonus_stardust": 500,
        "defender_bonus_max_gyms": 10,
        "defender_bonus_cooldown_hours": 21,
    },
    "spawns": {
        "per_l15_cell": 20,         # wild Pokemon per level-15 cell (~300m across)
        "max_per_request": 120,     # HARD cap per map refresh. The phone has to
                                    # draw every one of these; ~180 was enough to
                                    # crash the 2016 client on a real device.
        "refresh_minutes": 15,
        "how_many_near_you": 5,
        "per_stop": 5,              # wild Pokemon scattered around each stop's area
        "nearest_distance_m": 25,
        "farthest_distance_m": 65,
        # Cells further than this from you get no wild Pokemon (0 = no limit).
        # Cuts the map payload hard, which is what a VPN on cellular needs.
        "radius_m": 300,
        "min_cp": 100,
        "max_cp": 1200,
        "allow_legendaries": False,
        # Spawn rarity tiers: the RELATIVE weight of each tier. A species' odds of
        # being the wild Pokemon rolled = its tier weight / the sum of every
        # species' weight, so higher = more common. Lower the rare tiers to make
        # the trophies genuinely scarce. "very_rare" is the pseudo-legendary /
        # chase list (Dratini line, Lapras, Snorlax, Chansey, the fossils, ...);
        # "rare" is starters and the strong single-stage Pokemon. Hot-reloads.
        "weight_common": 60,
        "weight_uncommon": 12,
        "weight_rare": 3,
        "weight_very_rare": 1,
        # Wild CP can never exceed what a species can actually reach (a level-40,
        # perfect-IV specimen). Without this a Caterpie could roll 1200 CP. Events
        # that WANT beyond-natural Pokemon (High CP, Legendary Hunt) opt out per
        # event, so this only tames ordinary wild spawns.
        "cap_cp_to_species": True,
        # Different areas favour different Pokemon, the way the 2016 biomes did:
        # water types by water, rock/ground on hills, city trash downtown, etc.
        # Each region keeps its biome, so a place always feels the same.
        "biomes": True,
        # How big a biome region is, as an S2 cell level. Lower = bigger regions.
        # 12 is ~3 km across; 13 ~1.5 km, 11 ~6 km.
        "biome_size": 12,
        # Nests: like 2016, ~1 region in 3 spawns mostly ONE species, and which
        # species rotates on a cycle so nests are worth re-checking.
        "nests": True,
        # Chance a spawn inside a nest region is the nest species (the rest are
        # normal biome spawns, so a nest is a strong bias, not the only thing).
        "nest_chance": 0.55,
        # How often nests rotate to a new species, in days (2016 was ~14).
        "nest_rotation_days": 14,
        # Day/night: nocturnal Pokemon (Zubat, ghosts, ...) favour the dark and
        # day types favour daylight, using local time at your longitude.
        "day_night": True,
    },
    "eggs": {
        "max_eggs": 9,              # egg bag size
        "drop_chance": 0.35,        # chance a PokeStop spin gives an egg
        "min_step_m": 1.0,          # GPS moves smaller than this are jitter
        # Bigger than this between two GPS fixes is treated as a teleport and does
        # NOT count towards eggs. 120 m was too low: DRIVING moves further than that
        # between fixes, so no distance counted and eggs never hatched. 1000 m counts
        # driving while still ignoring a real GPS glitch across town. Lower it to
        # 120 if you want the strict "walk only" behaviour.
        "max_step_m": 1000.0,
    },
    "boosts": {
        "lucky_egg_minutes": 30,    # double XP while it burns
        "incense_minutes": 30,      # extra wild Pokemon around you
        "incense_extra_spawns": 6,  # how many more, on top of the usual
        "lure_minutes": 30,         # a Lure on a PokeStop
        "lure_extra_spawns": 4,     # extra Pokemon around a lured stop
    },
    "pokemon": {
        # true = power-ups follow the real 2016 curve: each one raises the Pokemon
        # one half-level (the genuine CP multiplier step) and costs the real,
        # escalating Stardust/Candy the client shows -- gated by your trainer level.
        # false = the simple flat model below (fixed cost, fixed % CP gain).
        "real_powerups": True,
        "powerup_candy": 1,
        "powerup_stardust": 200,
        "powerup_cp_gain": 12,
        "evolve_xp": 500,
        "transfer_candy": 1,
        "faint_after_gym": True,
    },
    "battles": {
        "attack_damage": 12,
        "special_damage": 30,
        "defender_damage": 8,
        "win_xp": 1000,
        # This client (measured) only enters combat for TRAINING-type gym battles;
        # a NORMAL (attack an enemy gym) battle opens then freezes -- you can't
        # attack. true = report enemy battles as TRAINING so the client will fight
        # (you still take the gym on victory). Turn off if enemy battles ever start
        # working natively.
        "attack_as_training": True,
    },
    "distances": {
        # How far you can reach, in metres. These ship to the client inside
        # GlobalSettings; the client enforces them, the server never checks your
        # position. Defaults are the genuine 2016 values.
        "fort_interaction_m": 40.25,   # spinning a PokeStop / touching a Gym
        "encounter_m": 50.25,          # tapping a wild Pokemon to start a catch
        "pokemon_visible_m": 70.0,     # how far wild Pokemon are DRAWN
        # Raising pokemon_visible_m alone shows nothing new unless Pokemon
        # actually spawn out there -- see spawns.farthest_distance_m.
    },
    "progression": {
        # true = brand-new trainers run the real 2016 onboarding (legal screen,
        # avatar, name pick, first starter catch) instead of dropping straight onto
        # the map. Only affects NEW accounts; existing saves are never dragged back
        # through it. Needs a client whose login/first-run flow is intact. Off by
        # default -- the straight-to-map behaviour is the safe, proven one.
        "run_tutorial": False,
        # true = skip the slow SCRIPTED starter catch in onboarding (the drawn-out
        # "Pokemon sits in front of you" tutorial encounter) while keeping the rest
        # of the flow (legal screen, avatar, name, team). Your first catch is then a
        # normal, fast wild encounter instead. Only matters when run_tutorial is on.
        "tutorial_skip_starter": True,
        # Trainer level cap. 40 is the real 2016 ceiling; raise it for a longer
        # grind (500 is supported). Levels 1-40 always use the genuine 2016 XP
        # table -- anything above is generated, see world.LEVEL_XP.
        "max_level": 40,
        # Shape of the generated curve past 40:
        #   xp(L) = xp(40) + step*(L-40) + accel*(L-40)^2
        # The defaults land level 500 at ~1.998 billion XP, just under the
        # 2,147,483,647 int32 ceiling -- past that the client's level ring can
        # wrap into nonsense, so raising these is not free.
        "level_xp_step": 2000000,
        "level_xp_accel": 5000,
    },
    "storage": {
        "pokemon_upgrade_step": 50,
        "pokemon_upgrade_cost": 200,
        "max_pokemon_limit": 1000,
        "items_upgrade_step": 50,
        "items_upgrade_cost": 200,
        "max_items_limit": 1000,
    },
    "avatar": {
        # How your trainer looks. The client picks the clothing art by INDEX --
        # each number chooses one of the outfits baked into the 2016 APK, so the
        # useful range is small (0-4 for most slots) and an index the client has
        # no art for simply falls back to the first one.
        "choose_in_game": False,    # true = the dress-up screen opens at your
                                    # next login and whatever you pick there is
                                    # saved; false = use the numbers below
        "gender": 1,                # 1 = male, 2 = female
        "skin": 1,
        "hair": 1,
        "shirt": 1,
        "pants": 1,
        "hat": 0,                   # 0 = no hat
        "shoes": 1,
        "eyes": 1,
        "backpack": 1,
    },
    "server": {
        "world_manager_port": 8080,
        # Which client the server tells the game is the minimum. "0.29.0" lets both
        # the 0.29 and 0.35 clients in; "0.35.0" makes the 0.29 client show
        # "update required" so only 0.35 connects. Toggle it in the World Manager.
        "min_client_version": "0.29.0",
        # EXPERIMENT: serve our branded HTML page at the real PTC login URL
        # (/sso/login). If the client's PTC button opens a WEBVIEW, this replaces
        # the login screen with our own (logo, text, email+password, no Google).
        # If the client's login is NATIVE, this BREAKS login -> flip it back to
        # false. Default false = the proven JSON login. Test on a throwaway account.
        "custom_login_page": False,
    },
}

_README = [
    "==================== POKEMON GO SERVER SETTINGS ====================",
    "Edit the numbers below, save the file, and they apply within a few",
    "seconds. You do NOT need to restart the server.",
    "",
    "To reset everything: delete this file. It will be recreated.",
    "",
    "catching:",
    "   fast_catch ........... true = a catch takes one throw instead of three",
    "                          or four. The Pokemon never breaks out and never",
    "                          runs, and the ball is reported as a sure thing,",
    "                          which also cuts the wobbling short. Most of the",
    "                          time a slow catch takes is repeat throws.",
    "   xp_per_catch ......... XP for catching anything at all",
    "   xp_nice_throw ........ bonus XP for a Nice throw",
    "   xp_great_throw ....... bonus XP for a Great throw",
    "   xp_excellent_throw ... bonus XP for an Excellent throw",
    "   xp_curveball ......... small extra bonus for a curveball",
    "",
    "pokestops:",
    "   xp_per_spin .......... XP each time you spin a stop",
    "   cooldown_minutes ..... how long a stop stays purple before reuse",
    "   min/max_items_per_spin  how many items a spin gives",
    "   anchor_near_player ... false = stops/gyms stay at fixed spots (best for",
    "                          driving). true = also drops a trio at your feet that",
    "                          follows you -- spams the road when you move.",
    "",
    "gyms:",
    "   team ................. your team: 1=Blue, 2=Red, 3=Yellow",
    "   defender_minutes ..... how long a Pokemon guards before coming home",
    "   defender_coins ....... PokeCoins paid when it returns",
    "   max_defenders ........ how many Pokemon fit in one gym",
    "   defender_bonus_coins/stardust  Shop shield payout per gym held",
    "   defender_bonus_max_gyms ...... cap on gyms the shield pays for",
    "   defender_bonus_cooldown_hours  how often the shield can be collected",
    "",
    "spawns:",
    "   refresh_minutes ...... how often all wild Pokemon change",
    "   how_many_near_you .... wild Pokemon around you (0-60)",
    "   nearest/farthest_distance_m   how spread out they are, in metres",
    "   min_cp / max_cp ...... how strong wild Pokemon are",
    "   cap_cp_to_species .... true = a wild Pokemon is never stronger than that",
    "                          species can really get (no 1200 CP Caterpie)",
    "   biomes ............... true = different areas favour different Pokemon",
    "                          (water by water, rock on hills, city trash downtown)",
    "   biome_size ........... how large each biome region is (S2 cell level; 12",
    "                          is ~3 km, lower = bigger regions)",
    "   nests ................ true = ~1 region in 3 spawns mostly one species,",
    "                          rotating on a cycle (like the 2016 nests)",
    "   nest_chance .......... 0..1 chance a spawn in a nest is the nest species",
    "   nest_rotation_days ... how often a nest rotates species (2016 was ~14)",
    "   day_night ............ true = nocturnal Pokemon favour night, day types",
    "                          favour daylight (local time at your longitude)",
    "",
    " catching",
    "   base_catch_rate ...... Pokemon can now BREAK OUT. Raise towards 1.0 to",
    "                          make catching easier, lower it to make it a fight.",
    "                          Strong Pokemon resist more; Great/Ultra Balls,",
    "                          good throws and Razz Berries all help.",
    "   flee_chance .......... chance it runs away after breaking out",
    "   require_ball_in_circle  true = Nice/Great/Excellent also need the ball to",
    "                          land in the ring, not just a small ring at throw",
    "                          time. Check the hitpos= values in the log and set",
    "                          throw_accuracy_sense to match before enabling.",
    "",
    " eggs",
    "   drop_chance .......... how often a PokeStop hands you an egg (0-1)",
    "   max_step_m ........... distance only counts if you really walked it --",
    "                          a GPS jump bigger than this is ignored, so you",
    "                          cannot hatch an egg by teleporting",
    "   per_l15_cell ......... wild Pokemon in each level-15 cell (~300m across).",
    "                          The client asks for several cells at once, so this",
    "                          multiplies -- lower it if the map gets sluggish.",
    "   max_per_request ...... hard cap per map refresh, so a big per_l17_cell",
    "                          cannot produce a batch the client chokes on",
    "   radius_m ............. cells further away than this get no wild Pokemon",
    "                          (0 = no limit). The cell you stand in is always",
    "                          filled. Lower it if the map fails to load over a",
    "                          VPN or on cellular; raise it to see more around you",
    "   allow_legendaries .... true = Mewtwo etc. can appear in the wild",
    "",
    "pokemon:  (powering up, evolving, transferring)",
    "   real_powerups ........ true = the real 2016 curve (one half-level per",
    "                          power-up, genuine escalating Stardust/Candy the game",
    "                          shows, capped by your trainer level). false = the",
    "                          simple flat model below.",
    "   powerup_candy / powerup_stardust   flat-model cost of one power-up",
    "   powerup_cp_gain ...... flat-model % CP added per power-up",
    "   evolve_xp ............ XP for evolving one Pokemon",
    "   transfer_candy ....... candy you get for transferring",
    "   faint_after_gym ...... true = gym defenders come home with 0 HP",
    "",
    "battles:  (attacking a Gym)",
    "   attack_damage ........ damage your normal tap does",
    "   special_damage ....... damage your charged move does",
    "   defender_damage ...... damage the gym Pokemon does back to you",
    "   win_xp ............... XP for taking down a whole Gym",
    "",
    "avatar:  (what your trainer wears)",
    "   choose_in_game ....... true = the game's own dress-up screen opens the",
    "                          next time you log in, and your choice is saved",
    "   gender ............... 1 = male, 2 = female",
    "   skin/hair/shirt/pants/hat/shoes/eyes/backpack",
    "                          which outfit piece to wear, by number. Most slots",
    "                          only have a handful (try 0-4); hat 0 = bare head.",
    "",
    "storage:  (bought from the World Manager with gym PokeCoins)",
    "   pokemon_upgrade_step/cost  space added per purchase, and its price",
    "   items_upgrade_step/cost    same for the item bag",
    "   max_pokemon_limit / max_items_limit   the ceiling you can buy up to",
    "",
    "server:",
    "   world_manager_port ... the http://127.0.0.1:PORT control panel",
    "====================================================================",
]

_lock = threading.Lock()
_cache = {"mtime": None, "data": None, "checked": 0.0}


def _merged(user):
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for section, vals in (user or {}).items():
        if section.startswith("_") or section not in out or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if not k.startswith("_") and k in out[section]:
                out[section][k] = v
    return out


def _write_default_file():
    try:
        doc = {"_readme": _README}
        doc.update({k: dict(v) for k, v in DEFAULTS.items()})
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    except OSError:
        pass


# How often we're willing to stat settings.json. get() is called hundreds of
# times while building ONE map response, and stat'ing the file every time cost
# ~590 syscalls and a third of the total time. A second of staleness is
# imperceptible for a hot-reload; the saving is not.
_RECHECK_SEC = 1.0


def all():
    """The full settings dict, hot-reloaded when settings.json changes."""
    with _lock:
        now = time.monotonic()
        if _cache["data"] is not None and now - _cache.get("checked", 0.0) < _RECHECK_SEC:
            return _cache["data"]
        _cache["checked"] = now
        try:
            m = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            _write_default_file()               # first run: create it for the user
            try:
                m = os.path.getmtime(SETTINGS_FILE)
            except OSError:
                m = None
        if _cache["data"] is None or m != _cache["mtime"]:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    user = json.load(fh)
            except (OSError, ValueError):
                user = {}
            _cache["data"] = _merged(user)
            # A settings.json written by an older build is missing whatever has
            # been added since, and nothing ever put it there -- so new settings
            # were invisible unless you deleted the file. Top it up in place,
            # keeping every value you had.
            if _top_up(user, _cache["data"]):
                try:
                    m = os.path.getmtime(SETTINGS_FILE)
                except OSError:
                    pass
            _cache["mtime"] = m
        return _cache["data"]


def _top_up(user, merged):
    """Add any missing section/key to settings.json. Returns True if it wrote."""
    if not isinstance(user, dict) or not user:
        return False                       # no file yet, or unreadable: leave it
    missing = any(s not in user or not isinstance(user.get(s), dict)
                  or any(k not in user[s] for k in keys)
                  for s, keys in merged.items())
    if not missing:
        return False
    doc = {"_readme": _README}
    for section, keys in merged.items():
        doc[section] = dict(keys)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    except OSError:
        return False
    return True


def set(section, key, value):
    """Persist one setting to settings.json (created/merged). all() hot-reloads it
    by mtime, so the change applies within a few seconds -- no restart."""
    all()                                   # ensure the file exists first
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = {}
    doc.setdefault(section, {})[key] = value
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, SETTINGS_FILE)
    with _lock:                             # force the very next all() to re-read
        _cache["checked"] = 0.0
        _cache["mtime"] = None
    return value


def get(section, key, env=None, cast=None):
    """One setting. An environment variable of the same name still wins, so old
    shortcuts keep working."""
    data = all()            # always first, so settings.json is created even when
                            # an env var would short-circuit the lookup below
    if env:
        raw = os.environ.get(env)
        if raw not in (None, ""):
            try:
                return (cast or type(DEFAULTS[section][key]))(raw)
            except (TypeError, ValueError):
                pass
    val = data.get(section, {}).get(key, DEFAULTS[section][key])
    if cast:
        try:
            return cast(val)
        except (TypeError, ValueError):
            return DEFAULTS[section][key]
    return val
