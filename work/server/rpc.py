"""
RPC endpoint — pgorelease.nianticlabs.com/plfe/rpc

Milestone 1: get the player logged in and onto the map.
  - Decode + log the RequestEnvelope (so we can verify the real client's exact
    field layout against protocol.py's constants).
  - First call to /plfe/rpc  -> status 53 REDIRECT to an api_url on the same
    host (the documented bootstrap handshake).
  - Calls to the redirected url -> status 2 OK, with an auth_ticket and one
    return per request. GET_PLAYER gets a real PlayerData (nickname=username,
    tutorial complete). Every other request gets an empty response for now;
    that is enough to clear the login/handshake. We flesh them out next.

api_url stays on pgorelease.nianticlabs.com so the client keeps hitting a host
our DNS redirect + TLS cert already cover.
"""
import struct
import os
import time
import pb
import protocol as P

API_HOST = "pgorelease.nianticlabs.com"
API_PATH = "/plfe/0/rpc"          # any non-bootstrap path works
# Where GET_DOWNLOAD_URLS points the client for the ~65 MB of model bundles.
# Default: the Niantic host (resolves to this server via our DNS). Override with
# ASSET_BASE_URL to send downloads over a FAST public path (e.g. a playit tunnel)
# so remote players don't pull assets through the slow Tailscale relay.
ASSET_BASE_URL = os.environ.get("ASSET_BASE_URL", f"https://{API_HOST}/asset")
# Set LOG_VERBOSE=1 (or DEBUG=1) to include the raw protobuf dumps and the
# blow-by-blow battle diagnostics. OFF by default so the log reads as a plain
# account of what the game asked for and what we answered, one batch at a time.
VERBOSE = bool(os.environ.get("LOG_VERBOSE") or os.environ.get("DEBUG"))
_dump_budget = [8]                 # (verbose only) dump the first N raw envelopes
_last_loc = [0.0, 0.0]            # last non-zero player location we've seen
_last_logged_loc = [0.0, 0.0]     # last location we actually PRINTED (de-spam)
_last_user = [None]               # last trainer to make a request (for /shop)


def _moved_far(a, b, metres=15.0):
    """Roughly true if two lat/lngs are more than `metres` apart -- enough to be
    worth another [loc] line. ~1e-5 degrees is about a metre, so this is a cheap
    box test, no trig needed."""
    return (abs(a[0] - b[0]) + abs(a[1] - b[1])) > (metres / 111_000.0)


def _envelope_latlng(fields):
    la = pb.get(fields, P.RE_LATITUDE, pb.WT_64)
    lo = pb.get(fields, P.RE_LONGITUDE, pb.WT_64)
    if la is None or lo is None:
        return None
    return (struct.unpack("<d", struct.pack("<Q", la))[0],
            struct.unpack("<d", struct.pack("<Q", lo))[0])


def _build_returns(reqs, username, log):
    # Everything below reads/writes THIS account's state (saves/<name>.json).
    # Must happen before any world.* call in the request.
    import world
    world.use(username)
    # Bring home any Gym defenders that have served their time and pay the coins.
    # Checked on every batch so it happens while you play, not only on a restart.
    try:
        for fid, pid, coins in world.collect_gym_returns():
            log(f"   [gym] defender #{pid} came home from {fid[:12]}... "
                f"after {world._defender_minutes():g} min -> +{coins} PokeCoins "
                f"(total {world.current().COINS})")
    except Exception as e:
        log(f"   [gym] return check failed: {e}")
    returns = []
    for rtype, msg in reqs:
        if rtype == P.RT.GET_PLAYER:
            returns.append(P.build_get_player_response(username))
            log(f"      -> GET_PLAYER answered as {username!r}")
        elif rtype == P.RT.SET_CONTACT_SETTINGS:
            returns.append(P.build_set_contact_settings_response(username))
            log("      -> SET_CONTACT_SETTINGS -> SUCCESS (nothing to email offline)")
        elif rtype == P.RT.GET_MAP_OBJECTS:
            cells, lat, lng = P.parse_get_map_objects(msg)
            if not lat and not lng:                 # map msg had no fix; use the
                lat, lng = _last_loc                # player's last known location
            returns.append(P.build_get_map_objects_response(cells, lat, lng))
            log(f"      -> GET_MAP_OBJECTS: {len(cells)} cells @ ({lat:.5f},{lng:.5f}) + spawns")
        elif rtype == P.RT.GET_INVENTORY:
            since = P.parse_get_inventory(msg)
            returns.append(P.build_get_inventory_response(since))
            log("      -> GET_INVENTORY answered " +
                (f"as a delta since {since}" if since else "in full (cold start)"))
        elif rtype == P.RT.DOWNLOAD_REMOTE_CONFIG_VERSION:
            plat = P.parse_platform(msg)
            returns.append(P.build_download_remote_config_version_response(plat))
            ver = P.parse_client_version(msg)
            log(f"      -> config version check [{plat}] client v{ver // 100 / 10:.2f}"
                + ("\n" + pb.pretty(msg) if VERBOSE else ""))
        elif rtype == P.RT.CHECK_CHALLENGE:
            returns.append(P.build_check_challenge_response())
            log("      -> CHECK_CHALLENGE answered (no captcha)")
        elif rtype == P.RT.DOWNLOAD_SETTINGS:
            returns.append(P.build_download_settings_response())
            log("      -> DOWNLOAD_SETTINGS answered")
        elif rtype == P.RT.GET_ASSET_DIGEST:
            plat = P.parse_platform(msg)
            r = P.build_get_asset_digest_response(plat)
            returns.append(r)
            log(f"      -> asset digest [{plat}]: {len(P._our_bundles(plat))} bundles"
                + ("\n" + pb.pretty(msg) if VERBOSE else ""))
        elif rtype == P.RT.GET_DOWNLOAD_URLS:
            ids = P.parse_get_download_urls(msg)
            returns.append(P.build_get_download_urls_response(ids, ASSET_BASE_URL))
            log(f"      -> GET_DOWNLOAD_URLS for {ids} -> {ASSET_BASE_URL}/...")
        elif rtype == P.RT.DOWNLOAD_ITEM_TEMPLATES:
            r = P.build_download_item_templates_response()
            returns.append(r)
            log(f"      -> game master sent ({len(r):,} bytes)"
                + ("\n" + pb.pretty(msg) if VERBOSE else ""))
        elif rtype == P.RT.FORT_DETAILS:
            fid, flat, flng = P.parse_fort_request(msg)
            returns.append(P.build_fort_details_response(fid, flat, flng))
            log(f"      -> FORT_DETAILS {fid!r}")
        elif rtype == P.RT.GET_GYM_DETAILS:
            fid, glat, glng = P.parse_gym_details(msg)
            import world
            returns.append(P.build_gym_details_response(
                fid, glat or _last_loc[0], glng or _last_loc[1], int(time.time() * 1000)))
            log(f"      -> GET_GYM_DETAILS {fid!r} ({len(world.gym_members(fid))} defenders)")
        elif rtype == P.RT.FORT_DEPLOY_POKEMON:
            fid, uid = P.parse_deploy(msg)
            returns.append(P.build_fort_deploy_response(
                fid, uid, _last_loc[0], _last_loc[1], int(time.time() * 1000)))
            import world
            log(f"      -> FORT_DEPLOY_POKEMON {fid!r} pokemon={uid} "
                f"-> {len(world.gym_members(fid))} at gym")
        elif rtype == P.RT.START_GYM_BATTLE:
            gid, atk_ids, def_id = P.parse_start_gym_battle(msg)
            r = P.build_start_gym_battle_response(gid, atk_ids, def_id,
                                                  int(time.time() * 1000))
            returns.append(r)
            if VERBOSE:
                # Full request+response dump, for spotting a 0.35 proto drift.
                try:
                    log("      [gymdbg] START req:" + chr(10) + pb.pretty(msg))
                    log("      [gymdbg] START resp:" + chr(10) + pb.pretty(r))
                except Exception as _e:
                    log(f"      [gymdbg] dump failed: {_e}")
            d = pb.decode(r); res = pb.get(d, 1, pb.WT_VARINT)
            bid = pb.get(d, 4, pb.WT_LEN)
            import world
            b = world.BATTLES.get(bid.decode()) if bid else None
            log("      -> gym battle START: " +
                (f"begun ({len(atk_ids)} attacker(s))"
                 + (f", your #{b['atk_pid']} (CP {b['atk_cp']}) vs their "
                    f"#{b['def_pid']} (CP {b['def_cp']})" if b else "")
                 if res == 1 and bid else
                 {5: "the gym is empty",
                  8: "no Pokemon fit to fight (all fainted, or your only Pokemon is "
                     "the one guarding this gym)"}.get(res, f"couldn't start (code {res})")))
        elif rtype == P.RT.ATTACK_GYM:
            gid, bid, actions, last_seen = P.parse_attack_gym(msg)
            if VERBOSE:
                try:
                    log("      [gymdbg] ATTACK req:" + chr(10) + pb.pretty(msg))
                except Exception:
                    pass
            r = P.build_attack_gym_response(gid, bid, actions,
                                            int(time.time() * 1000), last_seen)
            returns.append(r)
            d = pb.decode(r)
            lg = pb.decode(pb.get(d, 2, pb.WT_LEN) or b"")
            state = pb.get(lg, 1, pb.WT_VARINT)
            rid = pb.get(d, 3, pb.WT_LEN)
            import world
            now = int(time.time() * 1000)
            b = world.BATTLES.get(bid)
            outcome = {1: "trading blows", 2: "VICTORY -- gym taken!",
                       3: "your Pokemon fainted",
                       4: "you left the battle"}.get(state, f"state {state}")
            hp = (f" (your HP {max(0, b['atk_hp'])}/{b['atk_max']}, "
                  f"their HP {max(0, b['def_hp'])}/{b['def_max']})" if b else "")
            prestige = ""
            if b and b.get("gym_result"):
                gr = b["gym_result"]
                prestige = (f"  gym prestige now {gr[0]:,} (level {gr[1]})"
                            + (f", {gr[2]} sent home" if gr[2] else ""))
            log(f"      -> gym battle: {len(actions)} tap(s) -> {outcome}{hp}{prestige}")
            if VERBOSE:
                out = [pb.decode(a) for a in pb.get_all(lg, 4) if isinstance(a, bytes)]
                offs = [(pb.get(a, 2, pb.WT_VARINT) or 0) - now for a in out]
                log(f"         [gymdbg] known={b is not None} "
                    f"match={bool(rid) and rid.decode() == bid} "
                    f"out={len(out)} actions offset_ms={offs}")
        elif rtype == P.RT.COLLECT_DAILY_DEFENDER_BONUS:
            r = P.build_collect_daily_defender_bonus_response()
            returns.append(r)
            d = pb.decode(r)
            res = pb.get(d, 1, pb.WT_VARINT)
            got = pb.get_all(d, 3)
            gyms = pb.get(d, 4, pb.WT_VARINT) or 0
            log("      -> COLLECT_DAILY_DEFENDER_BONUS -> "
                + {1: f"paid {got} for {gyms} gym(s)", 3: "too soon (once a day)",
                   4: "no gyms being defended"}.get(res, f"result {res}"))
        elif rtype == P.RT.USE_ITEM_XP_BOOST:
            iid = P.parse_use_item_xp_boost(msg)
            r = P.build_use_item_xp_boost_response(iid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log("      -> USE_ITEM_XP_BOOST -> " +
                {1: "Lucky Egg active: double XP", 3: "one is already running",
                 4: "you have none"}.get(res, f"result {res}"))
        elif rtype == P.RT.USE_INCENSE:
            r = P.build_use_incense_response(P.ITEM_INCENSE)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log("      -> USE_INCENSE -> " +
                {1: "Incense burning: more Pokemon nearby",
                 2: "one is already burning",
                 3: "you have none"}.get(res, f"result {res}"))
        elif rtype == P.RT.GET_INCENSE_POKEMON:
            returns.append(P.build_get_incense_pokemon_response())
        elif rtype == P.RT.ADD_FORT_MODIFIER:
            iid, fid, mlat, mlng = P.parse_add_fort_modifier(msg)
            r = P.build_add_fort_modifier_response(
                iid, fid, int(time.time() * 1000),
                mlat or _last_loc[0], mlng or _last_loc[1])
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> ADD_FORT_MODIFIER {fid[:12]}... -> " +
                {1: "Lure attached", 2: "that stop already has one",
                 4: "you have no Lure Modules"}.get(res, f"result {res}"))
        elif rtype == P.RT.USE_ITEM_CAPTURE:
            iid, eid = P.parse_use_item_capture(msg)
            r = P.build_use_item_capture_response(iid, eid)
            returns.append(r)
            ok = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> USE_ITEM_CAPTURE item={iid} encounter={eid} -> " +
                ("Razz Berry used, next ball is much likelier to hold"
                 if ok else "couldn't use that item"))
        elif rtype == P.RT.SET_AVATAR:
            look = P.parse_set_avatar(msg)
            returns.append(P.build_set_avatar_response(look, username))
            log("      -> SET_AVATAR " + (", ".join(f"{k}={v}" for k, v in look.items())
                                          if look else "(nothing sent)"))
        elif rtype == P.RT.MARK_TUTORIAL_COMPLETE:
            done = P.parse_mark_tutorial(msg)         # handles packed steps
            import world
            world.mark_tutorial(done)                 # persist before we reply
            returns.append(P.build_mark_tutorial_complete_response(username))
            log(f"      -> MARK_TUTORIAL_COMPLETE {done or 'all'} "
                f"(done now: {world.tutorial_steps()})")
        elif rtype == P.RT.ENCOUNTER_TUTORIAL_COMPLETE:
            pid = P.parse_encounter_tutorial_complete(msg)
            returns.append(P.build_encounter_tutorial_complete_response(pid))
            log(f"      -> ENCOUNTER_TUTORIAL_COMPLETE starter #{pid} caught")
        elif rtype == P.RT.CLAIM_CODENAME:
            name = P.parse_claim_codename(msg)
            r = P.build_claim_codename_response(name, username)
            returns.append(r)
            st = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> CLAIM_CODENAME {name!r} -> " +
                {1: "claimed", 2: "already taken", 3: "not valid"}.get(st, str(st)))
        elif rtype == P.RT.GET_SUGGESTED_CODENAMES:
            returns.append(P.build_suggested_codenames_response(username))
            log("      -> GET_SUGGESTED_CODENAMES answered")
        elif rtype == P.RT.CHECK_CODENAME_AVAILABLE:
            name = P.parse_claim_codename(msg)
            returns.append(P.build_check_codename_available_response(name))
            log(f"      -> CHECK_CODENAME_AVAILABLE {name!r}")
        elif rtype == P.RT.SET_PLAYER_TEAM:
            team = P.parse_set_player_team(msg)
            r = P.build_set_player_team_response(team, username)
            returns.append(r)
            st = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            names = {1: "Mystic (blue)", 2: "Valor (red)", 3: "Instinct (yellow)"}
            log(f"      -> SET_PLAYER_TEAM -> " +
                (f"joined {names.get(team, team)}" if st == 1 else
                 "team was already chosen" if st == 2 else "failed"))
        elif rtype == P.RT.GET_HATCHED_EGGS:
            import world
            for h in world.check_hatches(P.hatch_species):
                log(f"   [egg] a {h['km']:g} km egg hatched into #{h['pokemon_id']} "
                    f"CP{h['cp']} (+{h['xp']} XP, +{h['candy']} candy, "
                    f"+{h['stardust']} stardust)")
            returns.append(P.build_get_hatched_eggs_response())
        elif rtype == P.RT.USE_ITEM_EGG_INCUBATOR:
            inc_id, egg_uid = P.parse_use_item_egg_incubator(msg)
            r = P.build_use_item_egg_incubator_response(inc_id, egg_uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> USE_ITEM_EGG_INCUBATOR {inc_id!r} egg={egg_uid} -> " +
                {1: "incubating", 2: "no such incubator", 3: "no such egg",
                 4: "that isn't an egg", 5: "incubator already in use",
                 6: "egg already incubating",
                 7: "incubator has no uses left"}.get(res, f"result {res}"))
        elif rtype in (P.RT.USE_ITEM_POTION, P.RT.USE_ITEM_REVIVE):
            iid, uid = P.parse_use_item(msg)
            revive = rtype == P.RT.USE_ITEM_REVIVE
            r = (P.build_use_item_revive_response(iid, uid) if revive
                 else P.build_use_item_potion_response(iid, uid))
            returns.append(r)
            d = pb.decode(r)
            res = pb.get(d, 1, pb.WT_VARINT)
            hp = pb.get(d, 2, pb.WT_VARINT)
            log(f"      -> {'USE_ITEM_REVIVE' if revive else 'USE_ITEM_POTION'} "
                f"item={iid} pokemon={uid} -> " +
                (f"healed to {hp} HP" if res == 1 else
                 {2: "no such Pokemon", 3: "cannot use it on that Pokemon",
                  4: "it's defending a gym"}.get(res, f"result {res}")))
        elif rtype == P.RT.RELEASE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_release_response(uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> RELEASE_POKEMON {uid} -> " +
                {1: "transferred (+1 candy)", 2: "REFUSED: it's at a gym",
                 3: "FAILED"}.get(res, str(res)))
        elif rtype == P.RT.UPGRADE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_upgrade_response(uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> UPGRADE_POKEMON {uid} -> " +
                {1: "powered up", 2: "not found", 3: "not enough candy/stardust",
                 5: "it's at a gym"}.get(res, str(res)))
        elif rtype == P.RT.EVOLVE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_evolve_response(uid)
            returns.append(r)
            d = pb.decode(r); res = pb.get(d, 1, pb.WT_VARINT)
            log(f"      -> EVOLVE_POKEMON {uid} -> " +
                {1: f"evolved! +{pb.get(d,3,pb.WT_VARINT)} xp", 2: "missing",
                 3: "not enough candy", 4: "cannot evolve",
                 5: "it's at a gym"}.get(res, str(res)))
        elif rtype == P.RT.NICKNAME_POKEMON:
            f = pb.decode(msg)
            uid = pb.get(f, 1, pb.WT_64) or 0
            nick = pb.get(f, 2, pb.WT_LEN) or b""
            returns.append(P.build_nickname_response(uid, nick.decode("utf-8", "replace")))
            log(f"      -> NICKNAME_POKEMON {uid} = {nick.decode('utf-8','replace')!r}")
        elif rtype == P.RT.SET_FAVORITE_POKEMON:
            f = pb.decode(msg)
            uid = pb.get(f, 1, pb.WT_64) or pb.get(f, 1, pb.WT_VARINT) or 0
            fav = bool(pb.get(f, 2, pb.WT_VARINT))
            returns.append(P.build_favorite_response(uid, fav))
            log(f"      -> SET_FAVORITE_POKEMON {uid} fav={fav}")
        elif rtype == P.RT.RECYCLE_INVENTORY_ITEM:
            iid, cnt = P.parse_recycle(msg)
            returns.append(P.build_recycle_response(iid, cnt))
            log(f"      -> RECYCLE_INVENTORY_ITEM item={iid} x{cnt} (dropped from bag)")
        elif rtype == P.RT.GET_PLAYER_PROFILE:
            r = P.build_player_profile_response(int(time.time() * 1000))
            returns.append(r)
            got = P.badge_progress()
            earned = [f"{P.badge_name(bt)} {'I' * rank}"
                      for bt, rank, _lo, _hi, _c in got if rank]
            log(f"      -> GET_PLAYER_PROFILE: {len(got)} medals"
                + (f", earned: {', '.join(earned)}" if earned else ", none earned yet"))
        elif rtype == P.RT.CHECK_AWARDED_BADGES:
            r = P.build_check_awarded_badges_response()
            returns.append(r)
            d = pb.decode(r)
            new = pb.get(d, 2, pb.WT_LEN)
            if new:
                log("      -> CHECK_AWARDED_BADGES: new medal(s) awarded")
        elif rtype == P.RT.LEVEL_UP_REWARDS:
            import world
            lvl = P.parse_level_up_rewards(msg) or world.stats()[0]
            already = world.level_claimed(lvl)
            returns.append(P.build_level_up_rewards_response(lvl))
            log(f"      -> LEVEL_UP_REWARDS level {lvl}: "
                + ("AWARDED_ALREADY (no popup)" if already else "SUCCESS, items granted"))
        elif rtype == P.RT.FORT_SEARCH:
            fid, _, _ = P.parse_fort_request(msg)
            returns.append(P.build_fort_search_response(fid, int(time.time() * 1000)))
            log(f"      -> FORT_SEARCH {fid!r} (items added to bag + 50xp, 5m cooldown)")
        elif rtype == P.RT.ENCOUNTER:
            eid = P.parse_encounter(msg)
            returns.append(P.build_encounter_response(eid, int(time.time() * 1000)))
            import world
            s = world.get_spawn(eid)
            log(f"      -> ENCOUNTER {eid} -> " +
                (f"pokemon #{s['pokemon_id']} cp{s['cp']} (catch screen)"
                 if s else "NOT_FOUND (unknown spawn)"))
        elif rtype == P.RT.CATCH_POKEMON:
            eid, ball, hit, reticle, spin, hitpos = P.parse_catch(msg)
            # Read BEFORE building the response -- the response consumes it.
            import world as _w
            berry = _w.berry_mult(eid)
            returns.append(P.build_catch_pokemon_response(
                eid, ball, hit, int(time.time() * 1000), reticle, spin, hitpos))
            b = P.throw_bonus(reticle, spin, hitpos)
            st = pb.get(pb.decode(returns[-1]), 1, pb.WT_VARINT)
            log(f"      -> CATCH_POKEMON {eid} ball={ball} hit={hit} "
                f"reticle={reticle:.2f} hitpos={hitpos:.3f} spin={spin:.2f}"
                + (f" berry=x{berry:.1f}" if berry and berry > 1.0 else "")
                + " -> "
                + {1: "CAUGHT", 2: "broke out", 3: "fled",
                   4: "missed"}.get(st, f"status {st}")
                + (f" ({b[1]} throw! +{b[2]} XP)" if b and hit and st == 1 else ""))
        elif rtype == P.RT.FORT_RECALL_POKEMON:
            fid, uid, rlat, rlng = P.parse_fort_recall(msg)
            r = P.build_fort_recall_response(fid, uid, rlat or _last_loc[0],
                                             rlng or _last_loc[1])
            returns.append(r)
            ok = pb.get(pb.decode(r), 1, pb.WT_VARINT) == 1
            log(f"      -> FORT_RECALL_POKEMON {fid[:12]}... pokemon={uid} -> "
                + ("back in your box" if ok else "it wasn't at that gym"))
        elif rtype == P.RT.USE_ITEM_GYM:
            _iid, gid = P.parse_use_item_gym(msg)
            returns.append(P.build_use_item_gym_response(gid))
            log(f"      -> USE_ITEM_GYM {gid[:12]}... -> SUCCESS")
        elif rtype == P.RT.COLLECT_DAILY_BONUS:
            returns.append(P.build_collect_daily_bonus_response())
            log("      -> COLLECT_DAILY_BONUS -> SUCCESS")
        elif rtype in (P.RT.INCENSE_ENCOUNTER, P.RT.DISK_ENCOUNTER):
            eid = P.parse_special_encounter(msg)
            r = P.build_special_encounter_response(eid)
            returns.append(r)
            ok = pb.get(pb.decode(r), 1, pb.WT_VARINT) == 1
            log(f"      -> {P.rt_name(rtype)} {eid} -> "
                + ("catch screen" if ok else "NOT_FOUND (unknown spawn)"))
        elif rtype == P.RT.EQUIP_BADGE:
            returns.append(P.build_equip_badge_response(msg))
            log("      -> EQUIP_BADGE -> SUCCESS")
        elif rtype == P.RT.ECHO:
            returns.append(P.build_echo_response())
            log("      -> ECHO")
        elif rtype == P.RT.DEBUG_UPDATE_INVENTORY:
            returns.append(P.build_debug_update_inventory_response(msg))
            log("      -> DEBUG_UPDATE_INVENTORY -> items granted")
        elif rtype == P.RT.DEBUG_DELETE_PLAYER:
            returns.append(P.build_debug_delete_player_response())
            log("      -> DEBUG_DELETE_PLAYER -> REFUSED (saves are never wiped)")
        elif rtype == P.RT.PLAYER_UPDATE:
            ulat, ulng = P.parse_player_update(msg)
            if ulat or ulng:
                _last_loc[0], _last_loc[1] = ulat, ulng
            # Nearby Pokemon/forts already come from GET_MAP_OBJECTS; an empty
            # PlayerUpdateOutProto means "nothing extra".
            returns.append(b"")
            log(f"      -> PLAYER_UPDATE @ ({ulat:.5f},{ulng:.5f})")
        else:
            returns.append(b"")            # placeholder; client tolerates empties
            log(f"      -> {P.rt_name(rtype)} (#{rtype}) empty response")
    return returns


def handle(method, path, query, headers, body, log):
    # Asset bundle download: the client GETs the URL we returned from
    # GET_DOWNLOAD_URLS (https://pgorelease.nianticlabs.com/asset/pm0001).
    if method == "GET" and path.startswith("/asset/"):
        asset_id = path[len("/asset/"):]
        fp = P.bundle_path(asset_id)
        if fp:
            data = open(fp, "rb").read()
            log(f"[asset] SERVING {asset_id} ({len(data)} bytes) to client")
            return 200, {"Content-Type": "application/octet-stream"}, data
        log(f"[asset] 404 unknown asset {asset_id!r}")
        return 404, {"Content-Type": "text/plain"}, b"no such asset"

    # PokeStop / Gym photos: files the user dropped in photos/ next to the server,
    # referenced from FortDetailsResponse.image_urls.
    if method == "GET" and path.startswith("/fortimg/"):
        name = os.path.basename(path[len("/fortimg/"):])
        if name == P.DEFAULT_FORT_IMAGE:            # built-in placeholder photo
            data = P.default_fort_png()
            return 200, {"Content-Type": "image/png"}, data
        fp = os.path.join(P.PHOTO_DIR, name)
        if name and os.path.isfile(fp):
            data = open(fp, "rb").read()
            ext = os.path.splitext(name)[1].lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")
            log(f"[photo] SERVING {name} ({len(data)} bytes)")
            return 200, {"Content-Type": ctype}, data
        log(f"[photo] 404 {name!r} (put it in the photos/ folder)")
        return 404, {"Content-Type": "text/plain"}, b"no such photo"

    if method != "POST" or not body:
        return 405, {"Content-Type": "text/plain"}, b"method not allowed"

    request_id, reqs, fields = P.parse_request_envelope(body)
    username = P.resolve_username(fields) or "Trainer"
    _last_user[0] = username

    # A blank line + this header frame each request batch, so the log reads as a
    # sequence of "the game asked for X, we answered Y" rather than one endless
    # stream. The per-request answers below are indented under it.
    log("")
    if reqs:
        log(f"[{username}]  " + ", ".join(P.rt_name(t) for t, _ in reqs))

    # track the player's reported location (envelope #7/#8); remember last good
    ll = _envelope_latlng(fields)
    if ll and (abs(ll[0]) > 1e-6 or abs(ll[1]) > 1e-6):
        _last_loc[0], _last_loc[1] = ll
        try:
            import world as _w
            _w.use(username)
            _w.add_distance(ll[0], ll[1])
        except Exception:
            pass
        # The phone reports its position on EVERY request (a few a second), so
        # only note it when it has actually moved -- otherwise it drowns the log.
        if _moved_far(ll, _last_logged_loc):
            _last_logged_loc[0], _last_logged_loc[1] = ll
            log(f"   [loc] now at {ll[0]:.5f},{ll[1]:.5f}")

    # (verbose) the raw envelope, for the first few batches only.
    if VERBOSE and reqs and _dump_budget[0] > 0:
        _dump_budget[0] -= 1
        log("   raw envelope:\n" + pb.pretty(body))

    # Echo the host the client actually reached us on, so the bootstrap redirect
    # and every api_url keep the client on THAT host. Essential for patched, no-VPN
    # clients (baked to e.g. bracky.playit.plus): redirecting them to pgorelease
    # would strand them. Unchanged for DNS/VPN clients -- they arrive as pgorelease
    # and get pgorelease back.
    api_host = (headers.get("Host") or "").strip() or API_HOST

    # Bootstrap handshake: tell the client which host to use from now on.
    # A patched client's RPC base is padded to fill the fixed 32-byte Unity slot
    # (e.g. "/plfe000000000"), so its first call is "/plfe000000000/rpc", not the
    # bare "/plfe/rpc". Accept any /plfe*/rpc that isn't the post-redirect api path.
    if path.startswith("/plfe") and path.endswith("/rpc") and "/0/rpc" not in path:
        env = P.build_response_envelope(
            status_code=P.STATUS_REDIRECT,
            request_id=request_id,
            api_url=f"{api_host}{API_PATH}",
        )
        log(f"   -> handshake redirect to {API_HOST}{API_PATH}")
        return 200, {"Content-Type": "application/binary"}, env

    # In-game Shop PURCHASE: platform request type 2 carrying the item_id we
    # listed. Charge coins / grant the item server-side, then ack.
    if not reqs:
        _buy_id = P.buy_item_id(fields)
        if _buy_id:
            try:
                import shop as _shop
                import world as _w
                _w.use(username)
                ok, msg = _shop.purchase(_buy_id)
                env = P.build_response_envelope(
                    status_code=P.STATUS_OK,
                    request_id=request_id,
                    unknown6=_shop.build_buy_response(ok),
                    api_url=f"{api_host}{API_PATH}",
                    auth_ticket=P.build_auth_ticket(username),
                )
                log(f"[shop] BUY {_buy_id} -> {'OK' if ok else 'NO'}: {msg} "
                    f"({_w.current().COINS} coins)")
                return 200, {"Content-Type": "application/binary"}, env
            except Exception as e:
                log(f"[shop] buy failed: {type(e).__name__}: {e}")

    # In-game Shop screen: an empty-requests envelope carrying platform request
    # type 5. Answer with the shop item list in the response's field-6 platform
    # response (NOT a normal RPC return). Items + live currencies come from shop.py.
    if not reqs and P.wants_shop(fields):
        try:
            import shop as _shop
            import world as _w
            _w.use(username)
            p = _w.current()
            u6 = _shop.build_platform_shop(p.COINS, p.STARDUST)
            env = P.build_response_envelope(
                status_code=P.STATUS_OK,
                request_id=request_id,
                unknown6=u6,
                api_url=f"{api_host}{API_PATH}",
                auth_ticket=P.build_auth_ticket(username),
            )
            log(f"[shop] -> in-game shop ({len(_shop.CATALOGUE)} items, "
                f"{p.COINS} coins)")
            return 200, {"Content-Type": "application/binary"}, env
        except Exception as e:
            log(f"[shop] in-game shop failed: {type(e).__name__}: {e}")

    # Normal handling.
    returns = _build_returns(reqs, username, log)
    env = P.build_response_envelope(
        status_code=P.STATUS_OK,
        request_id=request_id,
        returns=returns,
        api_url=f"{api_host}{API_PATH}",
        auth_ticket=P.build_auth_ticket(username),
    )
    log(f"   ({len(returns)} answered)")
    return 200, {"Content-Type": "application/binary"}, env
