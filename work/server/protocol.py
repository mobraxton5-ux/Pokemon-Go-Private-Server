"""
PoGO 0.29 RPC protocol: field-number map + message builders.

Field numbers/enum values are the canonical community POGOProtos values for
this era. They are kept as NAMED CONSTANTS in one place so that if the real
client's logged layout (see rpc.py request dumps) ever disagrees, it's a
one-line fix. The request side is parsed generically (pb.decode), so only the
RESPONSE builders below depend on these numbers being right.
"""
import os
import time
import pb
import settings as _cfg

# ----------------------------------------------------------- RequestEnvelope
# (request side — VERIFIED against the real 0.29 client's raw envelope dump:
#  #1 status_code, #3 request_id, #4 requests, #6 signature(ignored),
#  #10 auth_info, #12 ms_since_last_locationfix. Note these differ from the
#  commonly-documented POGOProtos numbers — this build uses 3/4, not 2/3.)
RE_STATUS_CODE = 1
RE_REQUEST_ID = 3
RE_REQUESTS = 4          # repeated Request
RE_LATITUDE = 7
RE_LONGITUDE = 8
RE_ACCURACY = 9
RE_AUTH_INFO = 10
RE_AUTH_TICKET = 11
RE_UNKNOWN6 = 6          # repeated platform request (signature; shop-screen poll)
PLAT_SHOP = 5            # platform request_type 5 = "list IAP items" (Shop open)
PLAT_BUY = 2             # platform request_type 2 = buy an item (payload {item_id=1})

# Request { request_type = 1 (enum), request_message = 2 (bytes) }
REQ_TYPE = 1
REQ_MESSAGE = 2

# ---------------------------------------------------------- ResponseEnvelope
RESP_STATUS_CODE = 1
RESP_REQUEST_ID = 2
RESP_API_URL = 3         # == Niantic internal "assigned_host"
RESP_ERROR = 4           # == "debug_message"
RESP_UNKNOWN6 = 6        # repeated platform response (shop data)
RESP_AUTH_TICKET = 7
RESP_RETURNS = 100       # repeated bytes, positional with requests

# ResponseEnvelope.status_code values
STATUS_OK = 2            # request handled, returns[] valid
STATUS_REDIRECT = 53     # client must re-send to api_url

# AuthInfo { provider=1 string, token=2 {contents=1 string, unknown2=2 int} }
AI_PROVIDER = 1
AI_TOKEN = 2
AI_TOKEN_CONTENTS = 1

# AuthTicket { start=1 bytes, expire_timestamp_ms=2 uint64, end=3 bytes }
AT_START = 1
AT_EXPIRE = 2
AT_END = 3
_AT_MAGIC = b"U:"        # we stash the username in AuthTicket.start so it
                         # survives the client switching from token to ticket

# ------------------------------------------------------------- RequestType
# Only the ones we are confident about; everything else is logged numerically
# and answered with an empty response. The live client will reveal any others.
class RT:
    METHOD_UNSET = 0
    GET_PLAYER = 2
    GET_INVENTORY = 4
    DOWNLOAD_SETTINGS = 5
    DOWNLOAD_ITEM_TEMPLATES = 6
    DOWNLOAD_REMOTE_CONFIG_VERSION = 7
    FORT_SEARCH = 101
    ENCOUNTER = 102
    CATCH_POKEMON = 103
    FORT_DETAILS = 104
    FORT_DEPLOY_POKEMON = 110
    RELEASE_POKEMON = 112
    START_GYM_BATTLE = 135
    ATTACK_GYM = 136
    COLLECT_DAILY_DEFENDER_BONUS = 146     # the shield in the Shop: coins+stardust
                                           # for every gym you're defending, once a
                                           # day (VERIFIED = 146 in POGOProtos)
    EVOLVE_POKEMON = 125
    UPGRADE_POKEMON = 147
    SET_FAVORITE_POKEMON = 148
    NICKNAME_POKEMON = 149
    GET_HATCHED_EGGS = 126
    LEVEL_UP_REWARDS = 128
    CHECK_AWARDED_BADGES = 129
    GET_GYM_DETAILS = 134
    USE_ITEM_POTION = 113
    USE_ITEM_EGG_INCUBATOR = 140
    USE_ITEM_CAPTURE = 114
    USE_ITEM_XP_BOOST = 139
    USE_INCENSE = 141
    GET_INCENSE_POKEMON = 142
    ADD_FORT_MODIFIER = 144
    ENCOUNTER_TUTORIAL_COMPLETE = 127      # the first-starter catch in onboarding
                                           # (VERIFIED from the live iOS log: the
                                           # client sends #127 here, NOT 163)
    GET_SUGGESTED_CODENAMES = 401
    CHECK_CODENAME_AVAILABLE = 402
    CLAIM_CODENAME = 403                    # NAME_SELECTION step
    SET_AVATAR = 404
    SET_PLAYER_TEAM = 405
    MARK_TUTORIAL_COMPLETE = 406
    USE_ITEM_REVIVE = 116
    RECYCLE_INVENTORY_ITEM = 137
    GET_MAP_OBJECTS = 106
    GET_PLAYER_PROFILE = 121
    GET_ASSET_DIGEST = 300
    GET_DOWNLOAD_URLS = 301
    SFIDA_ACTION_LOG = 801   # per POGOProtos; in this 0.29 build it fires when the
                             # in-game Journal is opened (see rpc.py handler)
    # 0.35 ONLY. Sent in EVERY request batch by the 0.35 client (measured on a
    # real device 2026-08-30); the 0.29 client never sends it. It is the captcha
    # gate Niantic added in the Aug-2016 anti-cheat wave -- answering it with
    # show_challenge=false is what tells the client "no captcha, carry on".
    CHECK_CHALLENGE = 600
    SET_CONTACT_SETTINGS = 151
    # The rest of the 0.29 client's Method enum (read from its metadata with
    # tools/metadata_fields.py Method). None of these is reachable from the
    # 2016 UI -- trading, the item/gem store (the Shop goes through platform
    # requests instead), debug and Go Plus calls. Incense and lure Pokemon are
    # spawned as ordinary wild ones, so INCENSE_/DISK_ENCOUNTER never fire
    # either. Named here only so a surprise shows up readably in the log.
    PLAYER_UPDATE = 1
    ITEM_USE = 105
    FORT_RECALL_POKEMON = 111
    USE_ITEM_FLEE = 115
    TRADE_SEARCH = 117
    TRADE_OFFER = 118
    TRADE_RESPONSE = 119
    TRADE_RESULT = 120
    GET_ITEM_PACK = 122
    BUY_ITEM_PACK = 123
    BUY_GEM_PACK = 124
    USE_ITEM_GYM = 133
    COLLECT_DAILY_BONUS = 138
    INCENSE_ENCOUNTER = 143
    DISK_ENCOUNTER = 145
    EQUIP_BADGE = 150
    LOAD_SPAWN_POINTS = 500
    ECHO = 666
    DEBUG_UPDATE_INVENTORY = 700
    DEBUG_DELETE_PLAYER = 701
    SFIDA_REGISTRATION = 800
    SFIDA_CERTIFICATION = 802
    SFIDA_UPDATE = 803
    SFIDA_ACTION = 804
    SFIDA_DOWSER = 805
    SFIDA_CAPTURE = 806

NAME = {v: k for k, v in vars(RT).items() if not k.startswith("_")}
def rt_name(n): return NAME.get(n, f"UNKNOWN_{n}")

# ----------------------------------------------------------------- PlayerData
# (VERIFIED against POGOProtos PlayerData.proto — field numbers are NOT
#  sequential; tutorial_state=7 is what makes the client skip new-user onboarding)
PD_CREATION_MS = 1
PD_USERNAME = 2
PD_TEAM = 5
PD_TUTORIAL = 7          # repeated enum (packed)  <-- was 4; the key fix
PD_AVATAR = 8
PD_MAX_POKEMON = 9
PD_MAX_ITEMS = 10
PD_DAILY_BONUS = 11
PD_CONTACT = 13
PD_CURRENCIES = 14

# GetPlayerResponse { success=1 bool, player_data=2 PlayerData }
GP_SUCCESS = 1
GP_PLAYER_DATA = 2

# TutorialCompletion (from the client): 0=LEGAL_SCREEN, 1=AVATAR_SELECTION,
# 2=ACCOUNT_CREATION, 3=POKEMON_CAPTURE, 4=NAME_SELECTION, 5=POKEMON_BERRY,
# 6=USE_ITEM, 7=FIRST_TIME_EXPERIENCE_COMPLETE, 8=POKESTOP_TUTORIAL, 9=GYM_TUTORIAL.
# Marking them all done is what makes the client skip onboarding and open the map.
TUTORIAL_COMPLETE = [0, 1, 2, 3, 4, 5, 6, 7]
TUT_AVATAR_SELECTION = 1


def tutorial_state():
    """The onboarding steps the trainer has finished. With run_tutorial off (or an
    existing account) this is the full [0..7], so the client goes straight to the
    map -- the proven behaviour. A brand-new trainer with run_tutorial on starts
    empty and the client walks them through onboarding, each step persisted as the
    client reports it via MARK_TUTORIAL_COMPLETE."""
    try:
        import world
        return world.tutorial_steps()
    except Exception:
        return list(TUTORIAL_COMPLETE)


# TeamColor: 0=NEUTRAL, 1=BLUE(Mystic), 2=RED(Valor), 3=YELLOW(Instinct).
# Must be non-zero or the client refuses Gym interaction ("join a team first").
def _team():
    return _cfg.get("gyms", "team", env="TEAM", cast=int)


def _player_team():
    """The team to report in PlayerData. The trainer's chosen team if they have
    one; otherwise 0 -- which is what makes the client run the team-selection
    screen at level 5 -- unless auto-assign is on (gyms.let_players_choose off),
    in which case everyone gets the gyms.team default and the screen never shows.
    (build_player_data used to always send the default, so the choice screen never
    appeared and 'pick your team' never worked.)"""
    try:
        import world
        raw = int(world.current().TEAM or 0)
    except Exception:
        raw = 0
    if raw:
        return raw
    try:
        if _cfg.get("gyms", "let_players_choose", cast=bool):
            return 0
    except Exception:
        pass
    return _team()


# PlayerAvatarProto, straight out of the client's metadata. Field 8 is NOT the
# "gender" flag it was long assumed to be -- it is PlayerAvatarType, and it was
# being sent as 0 = PLAYER_AVATAR_UNSET on every response.
AV_SLOTS = (("skin", 2), ("hair", 3), ("shirt", 4), ("pants", 5), ("hat", 6),
            ("shoes", 7), ("gender", 8), ("eyes", 9), ("backpack", 10))
PLAYER_AVATAR_MALE, PLAYER_AVATAR_FEMALE = 1, 2


def avatar_look():
    """{slot: index} for the trainer -- what they picked in game if they ever
    did, otherwise the settings.json defaults."""
    try:
        import world
        saved = world.avatar()
    except Exception:
        saved = {}
    look = {}
    for name, _fld in AV_SLOTS:
        val = saved.get(name)
        if val is None:
            val = _cfg.get("avatar", name, cast=int)
        look[name] = max(0, int(val))
    # An unset avatar type leaves the client with no body to dress.
    if look["gender"] not in (PLAYER_AVATAR_MALE, PLAYER_AVATAR_FEMALE):
        look["gender"] = PLAYER_AVATAR_MALE
    return look


def build_player_avatar() -> bytes:
    """The avatar exactly as it was before the customisation experiment.

    Field 8 is PlayerAvatarType and 0 is UNSET, which leaves the client drawing
    the avatar it stored locally -- and that is what worked. Sending a real type
    (1 = MALE by the client's own enum) turned the trainer into a girl, and
    letting the client's dress-up screen pick produced a shadow with no body, so
    both routes are worse than not touching it. The plumbing underneath
    (SET_AVATAR, per-player storage, avatar_look) is still here and still
    records what the client sends; nothing reads it back into this message.
    """
    return (pb.Writer()
            .uint(2, 1)   # skin
            .uint(3, 1)   # hair
            .uint(4, 1)   # shirt
            .uint(5, 1)   # pants
            .uint(6, 0)   # hat
            .uint(7, 1)   # shoes
            .uint(8, 0)   # avatar type: UNSET, deliberately
            .uint(9, 1)   # eyes
            .uint(10, 1)  # backpack
            .to_bytes())


def build_currency(name: str, amount: int) -> bytes:
    return pb.Writer().string(1, name).int_(2, amount).to_bytes()


def _coins():
    try:
        import world
        return world.COINS
    except Exception:
        return 0


def _stardust():
    """Stardust reaches the client ONLY through PlayerData.currencies -- the
    client's PlayerCurrencyProto has a single field, Gems, and no stardust at all,
    so the inventory route never worked. This used to be hardcoded to 5000, which
    is why the number never moved no matter what was earned or spent."""
    try:
        import world
        return world.STARDUST
    except Exception:
        return 0


def _storage():
    """(max_pokemon, max_items) -- raised by buying upgrades in the World Manager."""
    try:
        import world
        return world.MAX_POKEMON, world.MAX_ITEMS
    except Exception:
        return 250, 350


def build_player_data(username: str) -> bytes:
    # The in-game name is the codename the trainer claimed in onboarding, if any;
    # otherwise the login name. (Existing accounts have no codename -> unchanged.)
    name = username
    try:
        import world
        name = world.codename() or username
    except Exception:
        pass
    w = (pb.Writer()
         .uint(PD_CREATION_MS, int(time.time() * 1000) - 86_400_000)
         .string(PD_USERNAME, name)
         .uint(PD_TEAM, _player_team())              # 0 until chosen -> team screen
         .packed_varints(PD_TUTORIAL, tutorial_state())
         .message(PD_AVATAR, build_player_avatar())
         .uint(PD_MAX_POKEMON, _storage()[0])
         .uint(PD_MAX_ITEMS, _storage()[1])
         .message(PD_CURRENCIES, build_currency("POKECOIN", _coins()))
         .message(PD_CURRENCIES, build_currency("STARDUST", _stardust())))
    # The Shop's defender-bonus SHIELD is greyed out until PlayerData.daily_bonus
    # says a collection is due -- without this the shield never lights up and the
    # client never sends COLLECT_DAILY_DEFENDER_BONUS, so the bonus looks broken.
    w.message(PD_DAILY_BONUS, build_daily_bonus())
    return w.to_bytes()


def build_daily_bonus() -> bytes:
    """DailyBonus { next_collected_timestamp_ms=1,
    next_defender_bonus_collect_timestamp_ms=2 }. The client greys the Shop shield
    until the field-2 timestamp, so reporting when our 21-hour cooldown next
    elapses is what makes the shield tappable (a past time = collect now; a future
    one shows the countdown). The server still has the final say on the payout."""
    import world
    try:
        nxt = world.defender_bonus_next_ms()
    except Exception:
        nxt = 0
    return pb.Writer().int_(2, int(nxt)).to_bytes()


def build_set_contact_settings_response(username: str) -> bytes:
    """SetContactSettingsOutProto { status=1, player=2 PlayerData } (tags read
    from the 0.29 metadata). The email/push toggles mean nothing offline, so we
    just say SUCCESS -- but the player MUST come back too, or the client would
    swap its PlayerData for an empty one."""
    return (pb.Writer()
            .uint(1, 1)                                   # SUCCESS
            .message(2, build_player_data(username))
            .to_bytes())


def build_get_player_response(username: str) -> bytes:
    return (pb.Writer()
            .bool_(GP_SUCCESS, True)
            .message(GP_PLAYER_DATA, build_player_data(username))
            .to_bytes())


# ------------------------------------------------------------- GET_INVENTORY
# (VERIFIED field numbers, POGOProtos 2016 layout:
#  GetInventoryResponse{success=1, inventory_delta=2}
#  InventoryDelta{original_ts=1, new_ts=2, inventory_items=3}
#  InventoryItem{modified_ts=1, deleted_item_key=2, inventory_item_data=3}
#  InventoryItemData{pokemon_data=1, item=2, pokedex_entry=3, player_stats=4, ...}
#  Item{item_id=1, count=2, unseen=3}   PlayerStats{level=1, xp=2, prev=3, next=4})
# Returning a real (non-empty) inventory clears the client's perpetual "syncing"
# spinner, which otherwise suppresses the live map (Pokemon/PokeStops).
ITEM_POKE_BALL = 1
ITEM_GREAT_BALL = 2
ITEM_POTION = 101
ITEM_REVIVE = 201
ITEM_ULTRA_BALL = 3
ITEM_RAZZ_BERRY = 701
ITEM_SUPER_POTION = 102
ITEM_LUCKY_EGG = 301
ITEM_INCENSE = 401
ITEM_LURE = 501
ITEM_INCUBATOR = 902     # ITEM_INCUBATOR_BASIC (3 uses). 901 is the UNLIMITED one,
                         # which every trainer already has exactly one of.


def build_player_stats(level=None, xp=None) -> bytes:
    # PlayerStatsProto, field numbers read out of the client itself:
    #   Level=1, Experience=2, PrevLevelExp=3, NextLevelExp=4, KmWalked=5 float,
    #   NumPokemonEncountered=6, NumUniquePokedexEntries=7, NumPokemonCaptured=8,
    #   NumEvolutions=9, PokeStopVisits=10, NumberOfPokeballThrown=11,
    #   NumEggsHatched=12, BigMagikarpCaught=13, NumBattleAttackWon=14,
    #   NumBattleAttackTotal=15, NumBattleDefendedWon=16, NumBattleTrainingWon=17,
    #   NumBattleTrainingTotal=18, PrestigeRaisedTotal=19, PrestigeDroppedTotal=20,
    #   NumPokemonDeployed=21, NumPokemonCaughtByType=22, SmallRattataCaught=23.
    # 22 is a repeated field of uncertain ordering, and nothing we show depends
    # on it (the Medals page reads the badges we send in GET_PLAYER_PROFILE), so
    # it is deliberately left out rather than guessed at.
    # prev/next come from the REAL XP table (game master PlayerLevelSettings) --
    # the old code sent 0 and xp*2, so the client's level ring was nonsense.
    import world
    if level is None or xp is None:
        level, xp = world.LEVEL, world.XP
    prev, nxt = world.level_bounds(xp)
    st = world.STATS
    return (pb.Writer()
            .int_(1, level)
            .int_(2, xp)
            .int_(3, prev)
            .int_(4, nxt)
            .float_(5, float(st.get("km_walked", 0.0)))
            .int_(6, st.get("pokemons_encountered", 0))
            .int_(7, st.get("unique_pokedex_entries", 0))
            .int_(8, st.get("pokemons_captured", 0))
            .int_(9, st.get("evolutions", 0))
            .int_(10, st.get("poke_stop_visits", 0))
            .int_(11, st.get("pokeballs_thrown", 0))
            .int_(12, st.get("eggs_hatched", 0))
            .int_(13, st.get("big_magikarp", 0))
            .int_(14, st.get("battle_attack_won", 0))
            .int_(15, st.get("battle_attack_total", 0))
            .int_(16, st.get("battle_defended_won", 0))
            .int_(17, st.get("battle_training_won", 0))
            .int_(18, st.get("battle_training_total", 0))
            .int_(21, st.get("pokemon_deployed", 0))
            .int_(23, st.get("small_rattata", 0))
            .to_bytes())


def build_bag_item(item_id, count) -> bytes:
    return pb.Writer().uint(1, item_id).int_(2, count).to_bytes()


def _inventory_item(data_field, body, now=None) -> bytes:
    """InventoryItemProto { ModifiedTimestamp=1, DeletedItemKey=2, Item=3 }.
    `now` is passed in so every item shares the delta's NewTimestamp -- items used
    to be stamped later than the delta they arrived in, which is backwards."""
    data = pb.Writer().message(data_field, body).to_bytes()   # InventoryItemData
    return (pb.Writer()
            .int_(1, int(now if now is not None else time.time() * 1000))
            .message(3, data)                                 # inventory_item_data
            .to_bytes())


def _deleted_item(data_field, body, now) -> bytes:
    """An inventory entry that tells the client to REMOVE something.

    DeletedItemKey is the same shape as the item data with only the identifying
    field filled in. Without this a transferred Pokemon never goes away: the delta
    is additive, so leaving it out means "no change", and the client rolls back the
    deletion it had optimistically predicted."""
    key = pb.Writer().message(data_field, body).to_bytes()
    return (pb.Writer()
            .int_(1, int(now))
            .message(2, key)                                  # DeletedItemKey
            .to_bytes())


def parse_get_inventory(msg) -> int:
    """GetInventoryProto { timestamp_millis=1, item_been_seen=2 } -- the
    new_timestamp of the last delta the client applied (0 on a cold start)."""
    try:
        return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0
    except Exception:
        return 0


def build_get_inventory_response(since_ms=0) -> bytes:
    # Built from the LIVE bag/caught state (world.py) rather than a hardcoded list,
    # so items awarded by spinning a PokeStop and Pokemon you catch actually show up.
    #
    # since_ms is echoed back as InventoryDelta.original_timestamp. The client
    # has two paths -- FullInventoryUpdateEventArgs when original_timestamp is 0
    # (a reload: it just replaces its cache) and InventoryUpdateEventArgs for a
    # real delta. We used to always leave it 0, so EVERY poll was a "full reload"
    # and the client never compared old vs new player_stats -- which is where the
    # mid-play level-up screen is triggered (PlayerService.leveledUp ->
    # RequestLevelUpRewards). Echoing the client's own timestamp makes each poll
    # an incremental update against the cache it already holds.
    import world
    now = int(time.time() * 1000)
    level, xp = world.stats()
    items = [_inventory_item(4, build_player_stats(level, xp), now)]  # player_stats
    # Every item the trainer has EVER held, zeros included. Since polls became
    # deltas the client keeps its cached counts, so an item used up to 0 (or an
    # incubator moved out of the bag) must be sent as count 0 or its old number
    # stays on screen. Real 2016 servers sent zero-count items the same way.
    for iid, cnt in world.bag_items(include_empty=True):
        items.append(_inventory_item(2, build_bag_item(iid, cnt), now))
    for iid in world.INCUBATOR_ITEMS:            # incubators never live in the bag
        items.append(_inventory_item(2, build_bag_item(iid, 0), now))
    for c in world.caught():
        items.append(_inventory_item(1, build_pokemon_data(          # pokemon_data
            c["pokemon_id"], c["uid"], c["cp"], extra=c), now))
    for fam, n in sorted(world.CANDY.items()):                       # pokemon_family
        if n > 0:
            items.append(_inventory_item(
                10, pb.Writer().uint(1, fam).int_(2, n).to_bytes(), now))
    _act = world.applied_items()
    if _act:                                                         # applied_items
        _aw = pb.Writer()
        for _a in _act:
            _aw.message(4, _applied_item(_a))      # AppliedItemsProto.Item = 4
        items.append(_inventory_item(8, _aw.to_bytes(), now))
    for _e in world.eggs():                                          # eggs
        items.append(_inventory_item(1, build_egg_data(_e), now))
    _incs = world.incubators()
    if _incs:                                                        # egg_incubators
        _iw = pb.Writer()
        for _i in _incs:
            _iw.message(1, build_incubator(_i))
        items.append(_inventory_item(9, _iw.to_bytes(), now))
    for _pid, _seen, _caught in world.pokedex():                     # pokedex_entry
        items.append(_inventory_item(3, pb.Writer()
                                     .uint(1, _pid).int_(2, _seen)
                                     .int_(3, _caught).to_bytes(), now))
    # Transferred/evolved Pokemon: tell the client they are GONE.
    alive = {int(c["uid"]) for c in world.caught()}
    for uid, _ts in world.recent_deletions():
        if uid in alive:            # belt and braces: never delete a live Pokemon
            continue
        items.append(_deleted_item(1, pb.Writer().fixed64(1, uid).to_bytes(), now))
    # NOTE: no player_currency item here. InventoryItemData.player_currency is a
    # PlayerCurrencyProto, whose only field is Gems -- putting stardust in it just
    # set gems to the stardust value. Stardust goes out via PlayerData.currencies.
    delta = pb.Writer()
    if since_ms > 0:
        delta.int_(1, int(since_ms))                          # original_timestamp_ms
    delta.int_(2, now)                                        # new_timestamp_ms
    for it in items:
        delta.message(3, it)                                  # inventory_items
    return (pb.Writer()
            .bool_(1, True)                                   # success
            .message(2, delta.to_bytes())                     # inventory_delta
            .to_bytes())


# Asset/template versions we pin the world to. Returning matching timestamps in
# DOWNLOAD_REMOTE_CONFIG_VERSION and the digest/settings responses keeps the
# client from looping on downloads it can't complete.
ASSET_TS = 1_470_600_000_000        # both must be NON-zero or config-version fails
                                    # (bump this to force the client to re-fetch the
                                    #  asset digest after we change bundle entries;
                                    #  bumped when we swapped the fake egg for the real
                                    #  151-bundle digest w/ genuine keys, 2026-08-02)
TEMPLATES_TS = 1_474_300_000_000    # bumped 2026-08-16: swapped our home-CONVERTED
                                    # master for the AUTHENTIC 2016 game_master (the
                                    # converter differed on 278 templates incl.
                                    # camera_encounterintro + BATTLE_SETTINGS, which
                                    # broke the catch/encounter animation). Bumping
                                    # forces the client to re-download it.
                                    # (was 1_473_300_000_000.) This constant OVERRIDES
                                    # the timestamp baked into game_master.bin, so
                                    # bumping only the converter changes nothing and
                                    # the client silently keeps its cached copy.
                                    # 1_473_100_000_000 was the flattened
                                    # camera_encounterintro (instant encounter).
                                    # Previously 1_473_000_000_000 for the 832-template master (Camera +
                                    # MoveSequence restored). Without a bump the client never
                                    # sends DOWNLOAD_ITEM_TEMPLATES at all -- it just keeps using
                                    # its cached copy, so a rebuilt game_master.bin has no effect.
                                    # (2026-08-02 bump was for the stale-templates/no-Pokemon fix.)
                                    # build_download_item_templates_response OVERRIDES the bin's
                                    # baked timestamp_ms with this, so the two always agree.
SETTINGS_HASH = "pogoprivserver02"   # bumped when GlobalSettings field numbers were
                                     # fixed -> forces the client to re-read settings
                                     # instead of reusing the cached (broken) ones


def build_asset_digest_entry(asset_id, bundle_name, version=1, checksum=0,
                             size=1, key=b"") -> bytes:
    # AssetDigestEntry { asset_id=1, bundle_name=2, version=3 int64,
    #   checksum=4 fixed32, size=5 int32, key=6 bytes }
    w = (pb.Writer()
         .string(1, asset_id)
         .string(2, bundle_name)
         .uint(3, version)
         .fixed32(4, checksum)
         .int_(5, size))
    if key:
        w.bytes_(6, key)                    # empty key -> (test) no decryption
    return w.to_bytes()


# --- real 2016 CDN bundles (encrypted) + their genuine digest, served for download ---
# assets/ holds the encrypted pm#### bundles AND the shipped `asset_digest`
# (the real GetAssetDigestResponse). We serve the encrypted bytes verbatim and
# hand the client the REAL per-bundle key/checksum/version/size from that digest,
# so the client's own DecodeAndroid decrypts + CRC-validates each bundle.
_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(_HERE, "assets")

# Unity AssetBundles are PLATFORM-SPECIFIC: assets/ holds the Android builds
# (UnityFS target_platform=13) and assets_ios/ the iOS ones (target_platform=9).
# Hand an iPhone the Android bundles and it downloads them, fails to load them,
# and renders the outline with no model -- measured 2026-08-14, and the reason
# this split exists. The two sets have DISJOINT asset_ids (0 of 151 overlap) and
# their own asset_digest with its own per-bundle keys, sizes and timestamp, so a
# digest and its bundles must always be used as a pair.
ASSETS_DIR_IOS = os.path.join(_HERE, "assets_ios")

# What the client puts in field 1 of GetAssetDigestMessage /
# DownloadRemoteConfigVersionMessage. Confirmed live against 0.29 rather than
# taken from POGOProtos (which disagrees with this build elsewhere).
PLATFORM_IOS = 1
PLATFORM_ANDROID = 2


def parse_platform(msg: bytes) -> str:
    """'ios' or 'android' from a request that carries a Platform field.

    Anything unrecognised falls back to android -- that is the set the server
    shipped with, so an unknown client behaves exactly as it did before.
    """
    try:
        v = pb.get(pb.decode(msg), 1, pb.WT_VARINT)
    except Exception:
        return "android"
    return "ios" if v == PLATFORM_IOS else "android"


# DownloadRemoteConfigVersionMessage field 5 carries the app version as an int:
# 0.29 sends 2900, 0.35 sends 3500. This is the ONLY place either client states
# its version before the boot handshake completes, so it is what we key
# version-specific behaviour off. Unknown/absent -> 2900, because that is the
# build the server was written against and the one the iOS client is pinned to.
CLIENT_VERSION_DEFAULT = 2900


def build_check_challenge_response() -> bytes:
    """CheckChallengeResponse { bool show_challenge = 1; string challenge_url = 2 }

    We never challenge anyone, so show_challenge is false and the url is empty.
    An EMPTY response also happens to satisfy this build (proto3 defaults both
    fields to exactly this), but sending it explicitly means the client is
    answered rather than merely not-contradicted, and it shows up in the log.
    """
    return pb.Writer().int_(1, 0).to_bytes()


def parse_client_version(msg: bytes) -> int:
    """App version as an int (2900 = 0.29.0, 3500 = 0.35.0) from a request that
    carries it. Falls back to CLIENT_VERSION_DEFAULT so an unrecognised client
    behaves exactly as every client did before this function existed."""
    try:
        v = pb.get(pb.decode(msg), 5, pb.WT_VARINT)
    except Exception:
        return CLIENT_VERSION_DEFAULT
    return v if isinstance(v, int) and v > 0 else CLIENT_VERSION_DEFAULT


def assets_dir(platform="android"):
    """Bundle directory for a platform, falling back to android if the iOS set
    isn't installed (so a half-populated tree degrades to the old behaviour)."""
    if platform == "ios" and os.path.isdir(ASSETS_DIR_IOS):
        return ASSETS_DIR_IOS
    return ASSETS_DIR

# Photos for your PokeStops/Gyms: drop image files here and reference them by
# filename in the World Manager. Lives next to the .exe so it's easy to find.
import datadir
PHOTO_DIR = datadir.path("photos")
try:
    os.makedirs(PHOTO_DIR, exist_ok=True)
except OSError:
    pass

# PLAIN_ASSETS=1 (default): serve the PRE-DECRYPTED bundles from assets_plain/ with
# an EMPTY digest key (tells the client "no decryption needed") and a checksum we
# compute ourselves. The encrypted path provably reaches the device intact (43
# bundles cached on-device, byte-identical to ours) yet no model ever renders, so
# the failure is in the client's decrypt/validate step -- this takes both out of
# the picture. PLAIN_ASSETS=0 restores the encrypted bundles + genuine keys.
# DISPROVEN 2026-08-02: served pm0142 decrypted with an empty key; the client
# downloaded it and REFUSED TO CACHE IT (0 plain bundles on device afterwards),
# i.e. it always runs DecodeAndroid and rejects anything that isn't the encrypted
# [ver|IV|ct|HMAC] container. Encrypted is the only format it accepts -- default OFF.
PLAIN_ASSETS = os.environ.get("PLAIN_ASSETS", "0") == "1"
# CRC_FIX=1 (default): advertise CRC32(decrypted bundle) as the digest checksum
# instead of the genuine (unidentified-algorithm) value. Set 0 to pass through.
CRC_FIX = os.environ.get("CRC_FIX", "0") == "1"   # 1 = advertise CRC32(decrypted)
PLAIN_DIR = os.path.join(_HERE, "assets_plain")
_PLAIN_MANIFEST = None
_REAL_DIGEST = {}          # platform -> {bundle_name: entry}


def _plain_manifest():
    """{bundle_name: {size, crc32}} for the pre-decrypted bundles, or {}."""
    global _PLAIN_MANIFEST
    if _PLAIN_MANIFEST is None:
        import json
        try:
            with open(os.path.join(PLAIN_DIR, "manifest.json"), encoding="utf-8") as fh:
                _PLAIN_MANIFEST = json.load(fh)
        except (OSError, ValueError):
            _PLAIN_MANIFEST = {}
    return _PLAIN_MANIFEST


_RAW_DIGEST_BYTES = {}
_DIGEST_TS = {}


def _raw_digest_bytes(platform="android"):
    """The genuine GetAssetDigestResponse exactly as Niantic sent it."""
    if platform not in _RAW_DIGEST_BYTES:
        try:
            with open(os.path.join(assets_dir(platform), "asset_digest"), "rb") as fh:
                _RAW_DIGEST_BYTES[platform] = fh.read()
        except OSError:
            _RAW_DIGEST_BYTES[platform] = b""
    return _RAW_DIGEST_BYTES[platform]


def digest_timestamp(platform="android"):
    """The digest's OWN timestamp (field 2). DOWNLOAD_REMOTE_CONFIG_VERSION must
    advertise exactly this value as asset_digest_timestamp_ms, or the client never
    accepts the digest as current and re-requests GET_ASSET_DIGEST forever (observed
    live: 6 fetches in one session, models never usable). maierfelix/POGOServer
    hardcodes the same thing: asset_digest_timestamp_ms == '1467338276561000', which
    is the microsecond value baked into its digest file -- NOT a millisecond clock.

    Per platform: the two digests carry DIFFERENT timestamps (android
    1467338276561000, ios 1467338277329000), so the remote-config response has
    to quote the one matching the digest that client was served."""
    if platform not in _DIGEST_TS:
        raw = _raw_digest_bytes(platform)
        _DIGEST_TS[platform] = (pb.get(pb.decode(raw), 2, pb.WT_VARINT) or 0) if raw else 0
    return _DIGEST_TS[platform]


def _load_real_digest(platform="android"):
    """Parse assets/asset_digest -> {bundle_name: {asset_id, version, checksum,
    size, key}}. Fields per the 0.29 AssetDigestEntry contract: asset_id=1,
    bundle_name=2, version=3, checksum=4 (fixed32 CRC32 of the DECRYPTED bundle),
    size=5 (encrypted size on the wire), key=6 (16-byte AES key)."""
    if platform in _REAL_DIGEST:
        return _REAL_DIGEST[platform]
    out = _REAL_DIGEST[platform] = {}
    path = os.path.join(assets_dir(platform), "asset_digest")
    if not os.path.isfile(path):
        return out
    with open(path, "rb") as fh:
        data = fh.read()
    for raw in pb.get_all(pb.decode(data), 1):        # repeated AssetDigestEntry
        if not isinstance(raw, bytes):
            continue
        e = pb.decode(raw)
        name = pb.get(e, 2, pb.WT_LEN)
        if not isinstance(name, bytes):
            continue
        name = name.decode("ascii", "replace")
        aid = pb.get(e, 1, pb.WT_LEN)
        key = pb.get(e, 6, pb.WT_LEN)
        out[name] = {
            "asset_id": aid.decode("ascii", "replace") if isinstance(aid, bytes) else name,
            "version":  pb.get(e, 3, pb.WT_VARINT) or 0,
            "checksum": pb.get(e, 4, pb.WT_32) or 0,
            "size":     pb.get(e, 5, pb.WT_VARINT) or 0,
            "key":      key if isinstance(key, bytes) else b"",
        }
    return out


def _our_bundles(platform="android"):
    """Every pm#### bundle on disk that also has a genuine digest entry, with the
    REAL metadata (version/checksum/size/key). asset_id is kept == bundle_name so
    the existing /asset/<id> download path resolves straight to the file on disk;
    the client treats asset_id opaquely (crypto uses the per-entry key, not the id)."""
    digest = _load_real_digest(platform)
    plain = _plain_manifest() if PLAIN_ASSETS else {}
    out = []
    adir = assets_dir(platform)
    if os.path.isdir(adir):
        for fn in sorted(os.listdir(adir)):
            if not fn.startswith("pm") or fn not in digest:
                continue
            m = digest[fn]
            if fn in plain:
                # decrypted bytes -> no key, our own size + CRC32
                out.append({"asset_id": fn, "bundle_name": fn, "version": m["version"],
                            "checksum": plain[fn]["crc32"], "size": plain[fn]["size"],
                            "key": b""})
                continue
            checksum = m["checksum"]
            if CRC_FIX:
                # The client's load path is decrypt -> ValidateBundle(CRC32) -> create.
                # The genuine digest checksum is NOT zlib-CRC32 of the decrypted bundle
                # (verified: no standard CRC variant matches), so if the client computes
                # a plain CRC32 it will call every bundle corrupt and silently drop the
                # model -- which is exactly what we see (bundle cached on device, nothing
                # rendered). Advertise the CRC32 we actually measure instead.
                pc = _plain_manifest().get(fn)
                if pc:
                    checksum = pc["crc32"]
            out.append({"asset_id": m["asset_id"], "bundle_name": fn,
                        "version": m["version"], "checksum": checksum,
                        "size": m["size"], "key": m["key"]})
    return out


def bundle_path(asset_id):
    """File to serve for a download. asset_id is now the GENUINE Niantic id
    ('<guid>/<version>'), so map it back to its pm#### bundle via the digest.
    Prefers the pre-decrypted copy when PLAIN_ASSETS is on.

    GetDownloadUrlsMessage carries no platform field, but it doesn't need one:
    the android and ios digests share ZERO asset_ids (checked: 0 of 151), so the
    id alone says which set the client is asking for. Search both and serve the
    match -- that's what lets an iPhone and an Android phone play at the same
    time against one server."""
    for platform in ("android", "ios"):
        adir = assets_dir(platform)
        if platform == "ios" and adir == ASSETS_DIR:
            continue                              # ios set not installed
        for bn, m in _load_real_digest(platform).items():
            if m["asset_id"] == asset_id:
                if PLAIN_ASSETS and platform == "android":
                    p = os.path.join(PLAIN_DIR, bn)
                    if os.path.isfile(p):
                        return p
                p = os.path.join(adir, bn)
                if os.path.isfile(p):
                    return p
    name = os.path.basename(asset_id)            # fall back to a bare 'pm####'
    if PLAIN_ASSETS:
        p = os.path.join(PLAIN_DIR, name)
        if os.path.isfile(p):
            return p
    p = os.path.join(ASSETS_DIR, name)
    return p if os.path.isfile(p) else None


def build_get_asset_digest_response(platform="android") -> bytes:
    # GetAssetDigestResponse { digest=1 (repeated), timestamp_ms=2,
    #   result=3 (1=SUCCESS), page_offset=4 }. The client rejects an EMPTY digest
    # as a null response, so include at least one entry. We list our real pm####
    # bundles so the client will fetch them via GET_DOWNLOAD_URLS.
    # Preferred: hand back the GENUINE digest bytes untouched (this is exactly what
    # POGOServer does -- it serves player.asset_digest.buffer verbatim). Rebuilding it
    # risks changing the timestamp/entries the client keys off. We only append the
    # result field, which this 0.29 build wants and which protobuf tolerates anywhere.
    # EXPERIMENT (off unless DUPE_TEST_ID is set): advertise one extra bundle on an
    # out-of-enum id, to find out whether this client will fetch/render it. See
    # dupe_test.py. The client only asks for bundles the digest lists, so without
    # this the test could never get a request.
    extra = b""
    try:
        import dupe_test
        if dupe_test.enabled():
            dupe_test.ensure_bundle(assets_dir(platform),
                                    PLAIN_DIR if PLAIN_ASSETS else None)
            d = dupe_test.digest_entry(_load_real_digest(platform),
                                       _plain_manifest() if PLAIN_ASSETS else None)
            if d:
                extra = build_asset_digest_entry(
                    d["asset_id"], d["bundle_name"], version=d["version"],
                    checksum=d["checksum"], size=d["size"], key=d["key"])
                extra = pb.Writer().message(1, extra).to_bytes()
    except Exception:
        extra = b""

    raw = _raw_digest_bytes(platform)
    if raw and not PLAIN_ASSETS:
        # repeated fields may appear anywhere, so appending is safe
        return raw + extra + pb.Writer().uint(3, 1).to_bytes()   # result = SUCCESS

    w = pb.Writer()
    entries = _our_bundles(platform)
    if not entries:
        # no real digest present -> single placeholder so the client doesn't treat
        # the digest as a null response (enough to reach the map, no models).
        w.message(1, build_asset_digest_entry("A0", "bundle0", version=1, checksum=0, size=1))
    for b in entries:
        w.message(1, build_asset_digest_entry(
            b["asset_id"], b["bundle_name"], version=b["version"],
            checksum=b["checksum"], size=b["size"], key=b["key"]))
    out = w.to_bytes() + extra
    return out + pb.Writer().uint(2, ASSET_TS).uint(3, 1).to_bytes()


def parse_get_download_urls(msg: bytes):
    """GetDownloadUrlsMessage { asset_id = 1 (repeated string) }."""
    f = pb.decode(msg)
    ids = []
    for v in pb.get_all(f, 1):
        if isinstance(v, bytes):
            ids.append(v.decode("utf-8", "replace"))
    return ids


def build_get_download_urls_response(asset_ids, base_url) -> bytes:
    # GetDownloadUrlsResponse { download_urls=1 (repeated DownloadUrlEntry) }
    #   DownloadUrlEntry { asset_id=1, url=2, size=3 int32, checksum=4 uint32 }
    # Field numbers per POGOProtos + maierfelix/POGOServer. (Earlier builds put a
    # result at #1 and the list at #2 with no size/checksum -- WRONG; this path was
    # never reached before so it went unverified.) size/checksum are the genuine
    # digest values so the client's pre-decrypt download check passes.
    digest = _load_real_digest()
    w = pb.Writer()
    for aid in asset_ids:
        entry = pb.Writer().string(1, aid).string(2, f"{base_url}/{aid}")
        m = digest.get(aid)
        if m:
            entry.int_(3, m["size"]).uint(4, m["checksum"])
        w.message(1, entry.to_bytes())
    return w.to_bytes()


def build_item_template(template_id: str, body: bytes = b"") -> bytes:
    # ItemTemplate { template_id=1, pokemon_settings=2, item_settings=3, ... }
    w = pb.Writer().string(1, template_id)
    if body:
        w.raw(body)
    return w.to_bytes()


# ------------------------------------------------------------- GET_MAP_OBJECTS
import struct as _struct
import random as _random
import hashlib as _hashlib
import math as _math
import re as _re
import s2sphere
import world as _world


def _hex_id(seed, n=32):
    """Deterministic random-looking hex id, so fort/spawn ids look like the real
    Niantic ones ('108dc9c703a94b619a53a3c29b5c676f') rather than a padded int."""
    return _hashlib.md5(str(seed).encode()).hexdigest()[:n]

KANTO_MIN, KANTO_MAX = 1, 151        # all of Gen 1 (Kanto)


def _kanto_for(seed):
    # deterministic per-seed so a given cell always shows the same mon (no flicker)
    return _random.Random(seed).randint(KANTO_MIN, KANTO_MAX)


def _f64_to_double(v):
    return _struct.unpack("<d", _struct.pack("<Q", v))[0] if v is not None else 0.0


def parse_get_map_objects(msg: bytes):
    """GetMapObjectsMessage { cell_id=1 (repeated uint64 packed),
    since_timestamp_ms=2, latitude=3 double, longitude=4 double }."""
    f = pb.decode(msg)
    raw = pb.get(f, 1, pb.WT_LEN)
    cell_ids = []
    if isinstance(raw, bytes):
        pos = 0
        while pos < len(raw):
            v, pos = pb._read_varint(raw, pos)
            cell_ids.append(v)
    return cell_ids, _f64_to_double(pb.get(f, 3, pb.WT_64)), _f64_to_double(pb.get(f, 4, pb.WT_64))


def wild_uid(encounter_id):
    """The individual id a wild Pokemon keeps once caught. The ENCOUNTER must show
    the SAME id (and therefore the same IVs/size) that lands in the bag, or the
    post-catch summary can't find the Pokemon it just caught and never pops up.
    MUST equal world.new_uid(encounter_id)'s primary output (encounter_id ^ 0xC0FFEE)."""
    return (int(encounter_id) ^ 0xC0FFEE) & 0x3FFFFFFFFFFFFFFF


def build_map_pokemon(spawn_id, encounter_id, pokemon_id, lat, lng, expire_ms) -> bytes:
    # MapPokemon { spawn_point_id=1, encounter_id=2 fixed64, pokemon_id=3,
    #   expiration_timestamp_ms=4, latitude=5, longitude=6 }
    # expiration is x1000 like MapCell.current_timestamp_ms -- POGOServer sends
    # `(getTime() + 1e6) * 1e3`. In plain ms the spawn reads as long expired and
    # the client filters it out before drawing.
    return (pb.Writer()
            .string(1, spawn_id)
            .fixed64(2, encounter_id)
            .uint(3, pokemon_id)
            .int_(4, expire_ms * 1000)
            .double(5, lat)
            .double(6, lng)
            .to_bytes())


# Fallback move ids that exist as real Move templates in our game master
# (Bulbasaur's quick_moves), used only if gamedata.py is missing.
_MOVE_1, _MOVE_2 = 214, 221

try:
    import gamedata as _gd                        # generated by tools/convert_gm.py
except ImportError:                               # pragma: no cover
    _gd = None


def moves_for(pokemon_id, uid):
    """The (quick, charged) move ids for one Pokemon, stable for a given uid.

    Everything used to get move_1=214/move_2=221 -- Vine Whip and Tackle, BOTH of
    which are FAST moves. So no Pokemon in the game had a charged move at all,
    and the charged attack animated as `tackle_fast`. Species movesets come
    straight from the game master now.
    """
    if _gd is None:
        return _MOVE_1, _MOVE_2
    q = _gd.QUICK.get(pokemon_id) or [_MOVE_1]
    c = _gd.CHARGED.get(pokemon_id) or [_MOVE_2]
    r = _random.Random(uid)
    return r.choice(q), r.choice(c)


def _ivs(uid):
    """The three IVs for a Pokemon, stable for a given uid."""
    r = _random.Random(uid)
    return r.randint(0, 15), r.randint(0, 15), r.randint(0, 15)


def cpm_for(pokemon_id, cp, iv_a, iv_d, iv_s):
    """The cp_multiplier that makes this Pokemon's CP add up.

    PokemonProto.CpMultiplier is field 20 and we were never sending it, so it
    arrived as 0.0 -- and the client's damage formula is
    (base_attack + iv) * cp_multiplier * ..., so EVERY attack computed zero
    damage and no health bar ever moved. Inverting the CP formula
    CP = (atk * sqrt(def) * sqrt(sta) * cpm^2) / 10
    gives a multiplier consistent with the CP we already handed out, so CP, HP
    and damage all agree instead of being three unrelated numbers.
    """
    st = _gd.STATS.get(pokemon_id) if _gd else None
    if not st:
        return 0.5
    ba, bd, bs = st
    denom = (ba + iv_a) * _math.sqrt(bd + iv_d) * _math.sqrt(bs + iv_s)
    if denom <= 0:
        return 0.5
    cpm = _math.sqrt(max(10.0, float(cp)) * 10.0 / denom)
    # Deliberately NOT clamped to the level-40 maximum (0.7903). The client
    # recomputes the CP it displays from this multiplier, so clamping meant a
    # requested CP the species cannot naturally reach was silently shown much
    # lower -- only 21 of 151 species can hit 2500 and exactly one can hit 4000,
    # which made the High CP event look broken. An event is allowed to hand out
    # Pokemon stronger than the wild game ever could; the ceiling here is only to
    # stop a silly value producing an absurd health bar.
    lo = _gd.CPM[0] if (_gd and _gd.CPM) else 0.094
    return max(lo, min(6.0, cpm))


def cp_at_level(pokemon_id, uid, cpm):
    """The CP this exact individual (its fixed IVs) has at a given cp_multiplier --
    the forward CP formula, so a power-up that steps the multiplier lands on the CP
    the real game would show. Mirrors the inversion in cpm_for()."""
    st = _gd.STATS.get(pokemon_id) if _gd else None
    if not st:
        return 10
    ba, bd, bs = st
    iv_a, iv_d, iv_s = _ivs(uid)
    cp = (ba + iv_a) * _math.sqrt(bd + iv_d) * _math.sqrt(bs + iv_s) * cpm * cpm / 10.0
    return max(10, int(cp))


def move_timing(move_id, fallback_duration=700):
    """(duration_ms, damage_window_start_ms, damage_window_end_ms, energy_delta),
    the windows relative to the action start. The client matches an action to an
    animation through the performer's moveset, so these have to be the move's
    REAL numbers -- an invented duration resolves to nothing and the action is
    dropped without a word in the log."""
    m = _gd.MOVES.get(move_id) if _gd else None
    if not m:
        return fallback_duration, fallback_duration // 3, fallback_duration, 0
    dur, dws, dwe, energy, _power = m
    return dur, dws, dwe, energy


# How much each healing item restores. Max Potion/Max Revive are "full".
POTIONS = {101: 20, 102: 50, 103: 200, 104: 10 ** 9}      # potion..max potion
REVIVES = {201: 0.5, 202: 1.0}                            # revive, max revive


def max_hp(pokemon_id, uid, cp):
    """A Pokemon's full health -- the same stamina formula the battle code uses."""
    return _hp_for(cp, pokemon_id, uid)


def current_hp(c):
    """Stored health, defaulting to full for Pokemon caught before HP was tracked."""
    m = max_hp(c["pokemon_id"], c["uid"], c.get("cp", 100))
    v = c.get("stamina")
    return m if v is None else max(0, min(int(v), m))


# --------------------------------------------------------------------- EGGS
EGG_TIERS = (2.0, 5.0, 10.0)


def _egg_species_pools():
    """Split the (non-legendary) Kanto species into 2/5/10 km tiers by how strong
    they can get. Deriving it from the game master's own base stats beats
    inventing an egg chart, and it gives the right feel: commons at 2 km, the
    rare and powerful at 10 km."""
    global _EGG_POOLS
    if _EGG_POOLS is None:
        pool = _spawn_pool()                       # already excludes legendaries
        ranked = sorted(set(pool), key=lambda pid: _max_reachable_cp(pid))
        n = len(ranked)
        _EGG_POOLS = {2.0: ranked[:int(n * 0.55)],
                      5.0: ranked[int(n * 0.55):int(n * 0.85)],
                      10.0: ranked[int(n * 0.85):]}
        for k, v in _EGG_POOLS.items():            # never hand back an empty tier
            if not v:
                _EGG_POOLS[k] = ranked or [1]
    return _EGG_POOLS


def _max_reachable_cp(pokemon_id):
    st = _gd.STATS.get(pokemon_id) if _gd else None
    if not st:
        return 0.0
    a, d, sta = st
    cpm = _gd.CPM[-1] if (_gd and _gd.CPM) else 0.7903
    return ((a + 15) * _math.sqrt(d + 15) * _math.sqrt(sta + 15) * cpm * cpm) / 10


def hatch_species(target_km):
    """(pokemon_id, cp) for an egg of this tier. Hatchlings skew strong, the way
    a 10 km egg felt worth the walk."""
    pools = _egg_species_pools()
    tier = min(EGG_TIERS, key=lambda t: abs(t - float(target_km)))
    rnd = _random.Random()
    pid = rnd.choice(pools[tier])
    lo = int(200 + tier * 60)
    hi = int(lo + tier * 110)
    return pid, rnd.randint(lo, hi)


def build_egg_data(egg) -> bytes:
    """An egg is just a PokemonProto with IsEgg set.
    { id=1, is_egg=10, egg_km_walked_target=11, egg_km_walked_start=12,
      egg_incubator_id=25 }."""
    w = (pb.Writer()
         .fixed64(1, egg["uid"])
         .uint(10, 1)                                   # is_egg
         .double(11, float(egg.get("target_km", 2.0)))
         .double(12, float(egg.get("start_km", 0.0))))
    if egg.get("incubator"):
        w.string(25, str(egg["incubator"]))
    return w.to_bytes()


def build_incubator(inc) -> bytes:
    """EggIncubatorProto { item_id=1, item=2, incubator_type=3, uses_remaining=4,
    pokemon_id=5, start_km_walked=6, target_km_walked=7 }."""
    w = (pb.Writer()
         .string(1, str(inc["id"]))
         .uint(2, int(inc.get("item", 901)))
         .uint(3, 1))                                   # INCUBATOR_TYPE_DISTANCE
    if int(inc.get("uses", -1)) >= 0:
        w.int_(4, int(inc["uses"]))
    if inc.get("egg"):
        w.fixed64(5, int(inc["egg"]))
        w.double(6, float(inc.get("start_km", 0.0)))
        w.double(7, float(inc.get("target_km", 0.0)))
    return w.to_bytes()


def parse_use_item_egg_incubator(msg):
    """UseItemEggIncubatorProto { item_id=1, pokemon_id=2 } -- the client really
    does spell it PokemondId."""
    f = pb.decode(msg)
    iid = pb.get(f, 1, pb.WT_LEN)
    return ((iid.decode("utf-8", "replace") if isinstance(iid, bytes) else ""),
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_egg_incubator_response(incubator_id, egg_uid) -> bytes:
    """UseItemEggIncubatorOutProto { result=1, egg_incubator=2 }."""
    import world
    code, inc = world.use_incubator(incubator_id, egg_uid)
    w = pb.Writer().uint(1, code)
    if code == 1 and inc:
        w.message(2, build_incubator(inc))
    return w.to_bytes()


def build_get_hatched_eggs_response() -> bytes:
    """GetHatchedEggsResponse { success=1 bool, pokemon_id=2 (repeated uint64,
    PACKED), experience_awarded=3, candy_awarded=4, stardust_awarded=5 } -- four
    PARALLEL packed arrays. pokemon_id is the hatchling's UID (uint64), not the
    species -- and it is PACKED, so sending it as repeated fixed64 (the old bug)
    gave the client a field it couldn't read and the hatch result never showed."""
    import world
    done = world.drain_hatched()
    for h in done:
        world.add_xp(h["xp"])
        world.add_candy(pokemon_family(h["pokemon_id"]), h["candy"])
        world.add_stardust(h["stardust"])
        world.pokedex_caught(h["pokemon_id"])
    w = pb.Writer().bool_(1, True)
    if done:
        w.packed_varints(2, [h["uid"] for h in done])
        w.packed_varints(3, [h["xp"] for h in done])
        w.packed_varints(4, [h["candy"] for h in done])
        w.packed_varints(5, [h["stardust"] for h in done])
    return w.to_bytes()


ITEM_LUCKY_EGG = 301
ITEM_INCENSE = 401
ITEM_LURE = 501


def parse_use_item_xp_boost(msg):
    """UseItemXpBoostProto { item=1 }."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


# HoloItemType, read off the client: the applied-item entry has to say WHICH
# kind of buff it is or the game shows no timer at all. This was hardcoded to 1
# (ITEM_TYPE_POKEBALL), so a burning Lucky Egg matched nothing and looked dead.
ITEM_TYPE = {301: 11,      # ITEM_TYPE_XP_BOOST
             401: 10,      # ITEM_TYPE_INCENSE
             501: 8,       # ITEM_TYPE_DISK  (Lure Module)
             902: 9}       # ITEM_TYPE_INCUBATOR


def _applied_item(entry) -> bytes:
    """AppliedItemProto { item=1, item_type=2, expiration_ms=3, applied_ms=4 }."""
    iid = int(entry["item"])
    return (pb.Writer()
            .uint(1, iid)
            .uint(2, ITEM_TYPE.get(iid, 0))
            .int_(3, int(entry["expires_ms"]))
            .int_(4, int(entry["applied_ms"]))
            .to_bytes())


def build_use_item_xp_boost_response(item_id) -> bytes:
    """UseItemXpBoostOutProto { result=1, applied_items=2 }.
    1=SUCCESS 2=INVALID_ITEM_TYPE 3=ALREADY_ACTIVE 4=NO_ITEMS_REMAINING."""
    import world
    if int(item_id) != ITEM_LUCKY_EGG:
        return pb.Writer().uint(1, 2).to_bytes()
    mins = _cfg.get("boosts", "lucky_egg_minutes", cast=float)
    code, entry = world.apply_item(ITEM_LUCKY_EGG, mins)
    code = {1: 1, 2: 3, 3: 4}.get(code, 4)
    w = pb.Writer().uint(1, code)
    if code == 1:
        aw = pb.Writer()
        for a in world.applied_items():
            # AppliedItemsProto.Item is field 4, NOT 1. Field 1 is what
            # AppliedItemProto uses internally; putting the list there meant the
            # client read an EMPTY set of active items and showed no buff at all.
            aw.message(4, _applied_item(a))
        w.message(2, aw.to_bytes())
    return w.to_bytes()


def build_use_incense_response(item_id) -> bytes:
    """UseIncenseActionOutProto { result=1, applied_incense=2 }.
    1=SUCCESS 2=ALREADY_ACTIVE 3=NONE_IN_INVENTORY."""
    import world
    mins = _cfg.get("boosts", "incense_minutes", cast=float)
    code, entry = world.apply_item(ITEM_INCENSE, mins)
    w = pb.Writer().uint(1, code)
    if code == 1 and entry:
        w.message(2, _applied_item(entry))
    return w.to_bytes()


def parse_add_fort_modifier(msg):
    """AddFortModifierProto { modifier_type=1, fort_id=2, player_lat=3,
    player_lng=4 }."""
    f = pb.decode(msg)
    fid = pb.get(f, 2, pb.WT_LEN)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            fid.decode("utf-8", "replace") if isinstance(fid, bytes) else "",
            _f64_to_double(pb.get(f, 3, pb.WT_64)),
            _f64_to_double(pb.get(f, 4, pb.WT_64)))


def build_add_fort_modifier_response(item_id, fort_id, now_ms,
                                     lat=0.0, lng=0.0) -> bytes:
    """AddFortModifierOutProto { result=1, fort_details=2 }.
    1=SUCCESS 2=FORT_ALREADY_HAS_MODIFIER 3=TOO_FAR_AWAY 4=NO_ITEM_IN_INVENTORY.

    Field 2 is NOT optional in practice: the client holds the lure-placing
    animation open until it gets the refreshed fort back, so answering with a
    bare result left it stuck on that screen until the game was restarted.
    """
    import world
    mins = _cfg.get("boosts", "lure_minutes", cast=float)
    code, _mod = world.add_fort_modifier(fort_id, ITEM_LURE, mins,
                                         world.current().username)
    w = pb.Writer().uint(1, code)
    if code == 1:
        w.message(2, build_fort_details_response(fort_id, lat, lng))
    return w.to_bytes()


def build_get_incense_pokemon_response() -> bytes:
    """GetIncensePokemonOutProto -- we answer "nothing extra here" and instead
    make incense work by thickening the ordinary wild spawns around the trainer,
    which is the part that actually shows up on the map."""
    return pb.Writer().uint(1, 0).to_bytes()


def parse_use_item_capture(msg):
    """UseItemCaptureProto { item=1, encounter_id=2, spawn_point_guid=3 }."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_capture_response(item_id, encounter_id) -> bytes:
    """UseItemCaptureOutProto { success=1, item_capture_mult=2, item_flee_mult=3,
    stop_movement=4, stop_attack=5, target_max=6, target_slow=7 }.

    A Razz Berry makes the next ball much likelier to hold and the Pokemon much
    less likely to bolt. The multiplier is remembered against THIS encounter and
    spent on the next throw."""
    import world
    if item_id != ITEM_RAZZ_BERRY or not world.take_item(item_id, 1):
        return pb.Writer().bool_(1, False).to_bytes()
    cap = _cfg.get("catching", "razz_capture_mult", cast=float)
    flee = _cfg.get("catching", "razz_flee_mult", cast=float)
    world.use_berry(encounter_id, cap)
    return (pb.Writer()
            .bool_(1, True)
            .double(2, cap)
            .double(3, flee)
            .bool_(4, True)                  # the berry calms it down
            .to_bytes())


def parse_set_player_team(msg):
    """SetPlayerTeamProto { team=1 }. 1=Mystic(blue) 2=Valor(red) 3=Instinct(yellow)."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


def build_set_player_team_response(team, username) -> bytes:
    """SetPlayerTeamOutProto { status=1, player=2 }.
    1=SUCCESS 2=TEAM_ALREADY_SET 3=FAILURE."""
    import world
    status, _t = world.set_team(team)
    return (pb.Writer()
            .uint(1, status)
            .message(2, build_player_data(username))
            .to_bytes())


# ===================================================== NEW-TRAINER ONBOARDING
# Only reached when progression.run_tutorial is on and a brand-new trainer is
# being walked through the 2016 first-run flow. Each builder acks the step and
# returns fresh PlayerData so the client's copy stays in step. Request-type
# numbers 401/402/403 follow the same POGOProtos run as the confirmed
# 404/405/406; 163 (ENCOUNTER_TUTORIAL_COMPLETE) is the POGOProtos value -- verify
# from the live log if the starter step misbehaves.
def parse_mark_tutorial(msg):
    """The completed steps from MarkTutorialCompleteMessage { tutorials_completed=1
    repeated enum }. The client sends them PACKED (field 1 = one length-delimited
    blob of varints), so reading field 1 as plain varints returned nothing and no
    step was ever recorded -> onboarding looped forever. Handle both packed and
    unpacked."""
    steps = []
    for v in pb.get_all(pb.decode(msg), 1):
        if isinstance(v, int):
            steps.append(v)
        elif isinstance(v, (bytes, bytearray)):
            pos = 0
            while pos < len(v):
                n, pos = pb._read_varint(v, pos)
                steps.append(n)
    return steps


def build_mark_tutorial_complete_response(username) -> bytes:
    """MarkTutorialCompleteResponse { success=1 bool, player_data=2 }. The steps
    themselves are recorded in rpc.py (world.mark_tutorial) before this is built,
    so the PlayerData below already reflects them."""
    return (pb.Writer()
            .bool_(1, True)
            .message(2, build_player_data(username))
            .to_bytes())


def parse_set_avatar(msg):
    """SetAvatarProto { player_avatar=2 PlayerAvatarProto }. Reads the dress-up
    choices by the slot field numbers in AV_SLOTS."""
    inner = pb.get(pb.decode(msg), 2, pb.WT_LEN)
    look = {}
    if inner:
        pa = pb.decode(inner)
        for name, fld in AV_SLOTS:
            v = pb.get(pa, fld, pb.WT_VARINT)
            if v is not None:
                look[name] = v
    return look


def build_set_avatar_response(look, username) -> bytes:
    """SetAvatarResponse { status=1, player_data=2 } (status 1=SUCCESS).

    The client keeps its OWN copy of the look it just built and draws from that;
    we only record it and acknowledge. build_player_data still sends the known-good
    avatar (type UNSET), which is what avoided the shadow-trainer problem before --
    we are NOT trying to drive the avatar from the server here."""
    try:
        import world
        if look:
            world.set_avatar(look)
    except Exception:
        pass
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_player_data(username))
            .to_bytes())


def parse_claim_codename(msg):
    """ClaimCodenameMessage / CheckCodenameAvailableMessage { codename=1 string }."""
    v = pb.get(pb.decode(msg), 1, pb.WT_LEN) or b""
    return v.decode("utf-8", "replace")


def _codename_ok(name):
    return bool(_re.fullmatch(r"[A-Za-z0-9]{3,15}", name or ""))


def build_claim_codename_response(codename, username) -> bytes:
    """ClaimCodenameResponse { codename=1 string, user_message=2 string,
    is_assignable=3 bool, status=4 enum } -- field numbers VERIFIED against the
    real proto + a known-good server (POGOServer). The earlier version put the
    status in field 1 (which is actually the codename STRING) and never sent field
    4 at all, so the client read status=UNSET(0) and the name screen 'failed'.
    status: 1=SUCCESS 2=NOT_AVAILABLE 3=NOT_VALID."""
    clean = (codename or "").strip()
    if not _codename_ok(clean):
        return (pb.Writer().string(1, clean).string(2, clean)
                .bool_(3, False).uint(4, 3).to_bytes())        # NOT_VALID
    try:
        import world
        world.set_codename(clean)
    except Exception:
        pass
    return (pb.Writer()
            .string(1, clean)          # codename
            .string(2, clean)          # user_message
            .bool_(3, True)            # is_assignable
            .uint(4, 1)                # status = SUCCESS
            .to_bytes())


def build_check_codename_available_response(codename) -> bytes:
    """CheckCodenameAvailableResponse { codename=1, user_message=2, is_assignable=3,
    status=4 } -- same shape as ClaimCodename. On a private server every valid name
    is free."""
    clean = (codename or "").strip()
    ok = _codename_ok(clean)
    return (pb.Writer()
            .string(1, clean)
            .string(2, clean)
            .bool_(3, ok)
            .uint(4, 1 if ok else 3)
            .to_bytes())


def build_suggested_codenames_response(username) -> bytes:
    """GetSuggestedCodenamesResponse { codenames=1 repeated string, success=2 bool }
    -- codenames are field 1 and success is field 2 (had them swapped before)."""
    base = _re.sub(r"[^A-Za-z0-9]", "", username or "Trainer")[:11] or "Trainer"
    picks = [f"{base}{n}" for n in (_random.Random(username).randint(10, 99),
                                    _random.Random(username or "x").randint(100, 999))]
    w = pb.Writer()
    for s in picks:
        w.string(1, s[:15])            # codenames (repeated)
    return w.bool_(2, True).to_bytes()  # success


def parse_encounter_tutorial_complete(msg):
    """EncounterTutorialCompleteProto { pokemon_id=1 }."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


def build_encounter_tutorial_complete_response(pokemon_id) -> bytes:
    """EncounterTutorialCompleteResponse { result=1, pokemon_data=2 }. The chosen
    starter (Bulbasaur/Charmander/Squirtle, or Pikachu if they walked away) is
    caught for real: it lands in the collection, the Pokedex, and the type medals,
    exactly like a normal first catch."""
    import world
    pid = int(pokemon_id or 0)
    if pid not in (1, 4, 7, 25):
        pid = 1
    uid = world.new_uid(pid ^ 0x57A47E)
    # A starter comes in weak -- a low-level individual, like the real one.
    cpm = _gd.CPM[1] if (_gd and _gd.CPM and len(_gd.CPM) > 1) else 0.166
    cp = cp_at_level(pid, uid, cpm)
    world.add_caught(uid, pid, cp)
    world.pokedex_caught(pid)
    world.bump_type(pid)
    world.add_xp(_cfg.get("catching", "xp_per_catch", cast=int))
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_pokemon_data(pid, uid, cp))
            .to_bytes())


def catch_chance(pokemon_id, cp, ball_id, reticle, berry_mult, hit_position=None):
    """Probability this throw holds.

    Everything used to be a guaranteed catch, which made a Pokeball a formality.
    Stronger Pokemon resist, better balls and better throws help, and a Razz
    Berry multiplies it."""
    base = _cfg.get("catching", "base_catch_rate", cast=float)
    # a 2000 CP Pokemon should be a real fight; a 100 CP one shouldn't
    base *= max(0.18, 1.0 - (max(0, int(cp)) / 3200.0))
    base *= {1: 1.0, 2: 1.5, 3: 2.0}.get(int(ball_id), 1.0)      # poke/great/ultra
    # The tight-ring aim bonus only counts if the ball actually LANDED in the ring
    # (validated throw); a small ring that clipped the edge gets nothing extra.
    if throw_accuracy_ok(hit_position):
        base *= 1.0 + max(0.0, min(1.0, float(reticle))) * 0.55  # aim helps
    base *= max(1.0, float(berry_mult))
    return max(0.05, min(0.95, base))


def parse_use_item(msg):
    """UseItemPotionProto / UseItemReviveProto { item_id=1, pokemon_id=2 }."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_potion_response(item_id, uid) -> bytes:
    """UseItemPotionOutProto { result=1, stamina=2 }.
    1=SUCCESS 2=ERROR_NO_POKEMON 3=ERROR_CANNOT_USE 4=ERROR_DEPLOYED_TO_FORT."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 4).to_bytes()
    m = max_hp(c["pokemon_id"], uid, c.get("cp", 100))
    hp = current_hp(c)
    # A potion cannot touch a fainted Pokemon -- that needs a Revive.
    if hp <= 0 or hp >= m or item_id not in POTIONS:
        return pb.Writer().uint(1, 3).to_bytes()           # ERROR_CANNOT_USE
    if not world.take_item(item_id, 1):
        return pb.Writer().uint(1, 3).to_bytes()
    hp = min(m, hp + POTIONS[item_id])
    world.update_caught(uid, stamina=hp)
    return pb.Writer().uint(1, 1).int_(2, hp).to_bytes()


def build_use_item_revive_response(item_id, uid) -> bytes:
    """UseItemReviveOutProto { result=1, stamina=2 }. Revives only work on a
    FAINTED Pokemon, which is the whole point of them."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 4).to_bytes()
    m = max_hp(c["pokemon_id"], uid, c.get("cp", 100))
    if current_hp(c) > 0 or item_id not in REVIVES:
        return pb.Writer().uint(1, 3).to_bytes()           # not fainted
    if not world.take_item(item_id, 1):
        return pb.Writer().uint(1, 3).to_bytes()
    hp = max(1, int(m * REVIVES[item_id]))
    world.update_caught(uid, stamina=hp)
    return pb.Writer().uint(1, 1).int_(2, hp).to_bytes()


def build_pokemon_data(pokemon_id, uid, cp=500, extra=None) -> bytes:
    # PokemonData { id=1 fixed64, pokemon_id=2 enum, cp=3, stamina=4, stamina_max=5,
    #   move_1=6, move_2=7, height_m=15 float, weight_kg=16 float,
    #   individual_attack=17, individual_defense=18, individual_stamina=19 }
    # (VERIFIED against POGOProtos PokemonData.proto.) A bare id/cp triple is legal
    # but leaves the client without moves/IVs to display; fill in a sane creature.
    import world
    e = extra if extra is not None else (world.get_caught(uid) or {})
    # Real health, so the bar means something and a fainted Pokemon reads as 0.
    # (Battle code passes stamina/stamina_max explicitly and still wins here.)
    if "stamina_max" in e:
        hp_max = int(e["stamina_max"])
        hp = int(e.get("stamina", hp_max))
    else:
        hp_max = _hp_for(cp, pokemon_id, uid)
        hp = hp_max if e.get("stamina") is None else max(0, min(int(e["stamina"]), hp_max))
    _m1, _m2 = moves_for(pokemon_id, uid)
    _iv_a, _iv_d, _iv_s = _ivs(uid)
    # Per-individual size, rolled from the uid so it never changes for a given
    # Pokemon. Also what the XL/XS medals are judged on.
    _h_m, _w_kg = pokemon_size(pokemon_id, uid)
    w = (pb.Writer()
         .fixed64(1, uid)
         .uint(2, pokemon_id)
         .int_(3, cp)
         .int_(4, hp).int_(5, max(hp, hp_max))        # stamina / stamina_max
         .uint(6, _m1).uint(7, _m2)                   # move_1 / move_2
         .float_(15, _h_m).float_(16, _w_kg)          # height_m / weight_kg
         .int_(17, _iv_a)                             # individual_attack
         .int_(18, _iv_d)                             # individual_defense
         .int_(19, _iv_s)                             # individual_stamina
         .float_(20, cpm_for(pokemon_id, cp, _iv_a, _iv_d, _iv_s)))
    # deployed_fort_id (field 8) + owner_name (field 9): set for a Pokemon that is
    # guarding a gym. The client counts these to know you have a defender -- without
    # it the Shop shield stays greyed and the defender bonus can never be collected.
    # (POGOProtos calls field 8 an int32, but ids are 32-hex strings here, same as
    # the field-1 id which is really a fixed64, not the int32 POGOProtos claims.)
    _fort = world.deployed_fort(uid)
    if _fort:
        w.string(8, _fort).string(9, e.get("owner") or world.codename() or "")
    if e.get("num_upgrades"):
        w.int_(27, int(e["num_upgrades"]))
    if e.get("favorite"):
        w.int_(29, 1)
    if e.get("nickname"):
        w.string(30, str(e["nickname"])[:12])
    return w.to_bytes()


def build_nearby_pokemon(pokemon_id, distance_m, encounter_id=None) -> bytes:
    # NearbyPokemon { pokemon_id=1, distance_in_meters=2 FLOAT, encounter_id=3 fixed64 }
    # The "nearby tracker" (bottom-right of the map). It draws from 2D icons bundled
    # in the APK, so it shows up even when a 3D model bundle doesn't load.
    # POGOServer omits encounter_id here, so it's optional for us too.
    w = pb.Writer().uint(1, pokemon_id).float_(2, float(distance_m))
    if encounter_id is not None:
        w.fixed64(3, encounter_id)
    return w.to_bytes()


def build_spawn_point(lat, lng) -> bytes:
    # SpawnPoint { latitude=2, longitude=3 }  (note: no field 1)
    return pb.Writer().double(2, lat).double(3, lng).to_bytes()


def build_wild_pokemon(encounter_id, lat, lng, spawn_id, pokemon_id, now_ms,
                       time_till_hidden_ms=15 * 60 * 1000, cp=500) -> bytes:
    # WildPokemon { encounter_id=1 fixed64, last_modified_ts=2 int64,
    #   latitude=3 double, longitude=4 double, spawnpoint_id=5 string,
    #   pokemon_data=7 PokemonData, time_till_hidden_ms=11 int32 }
    # (VERIFIED against POGOProtos 2016 layout — the 0.29 client renders the
    #  live map spawns from THIS list, not catchable_pokemons.)
    return (pb.Writer()
            .fixed64(1, encounter_id)
            .int_(2, now_ms)
            .double(3, lat)
            .double(4, lng)
            .string(5, spawn_id)
            # pokemon_data.id = the uid it will keep when caught (NOT the
            # encounter_id) so the encounter, the bag entry and the captured_pokemon_id
            # from CATCH all refer to the same individual -> the stats summary pops up.
            .message(7, build_pokemon_data(pokemon_id, wild_uid(encounter_id), cp))
            .uint(11, time_till_hidden_ms)
            .to_bytes())


def build_fort(fort_id, lat, lng, now_ms, is_gym=False) -> bytes:
    # FortData { id=1, last_modified_ts=2, latitude=3, longitude=4,
    #   owned_by_team=5, guard_pokemon_id=6, guard_pokemon_cp=7, enabled=8,
    #   type=9 (GYM=0, CHECKPOINT=1), gym_points=10, is_in_battle=11,
    #   cooldown_complete_timestamp_ms=14 }
    # The gym fields are what make a Gym render with a team colour and a defender
    # on top of it instead of an empty grey tower.
    w = (pb.Writer()
         .string(1, fort_id)
         .int_(2, now_ms)
         .double(3, lat)
         .double(4, lng))
    if not is_gym:
        # A Lure on the map fort is PokemonFortProto.ActiveFortModifier = 12, and
        # it is just the ITEM ID -- not a message.
        # This was previously written as a message into field 13, which on this
        # proto is ActivePokemon: the client parsed the lure as a Pokemon and
        # CRASHED the moment you tapped the stop.
        import world
        _m = world.fort_modifier(fort_id)
        if _m:
            w.uint(12, int(_m["item"]))
    if is_gym:
        import world
        guard = world.gym_guard(fort_id)
        # A gym with defenders flies your team's colour; an empty one goes back to
        # NEUTRAL (white/unclaimed). Sending TEAM here unconditionally was a guess
        # at the crash-on-tap -- the real cause was an empty `urls` list, so an
        # unowned gym is safe again.
        if guard:
            pid, cp, _pts = guard
            # whoever holds it -- may be another account's team now
            w.uint(5, world.gym_team(fort_id) or _team()).uint(6, pid).int_(7, cp)
            # Real prestige as gym_points: the client derives the gym LEVEL (and
            # how many defender slots it draws) from this against the same 2016
            # thresholds, so training/attacking is visible on the tower.
            points = world.gym_prestige(fort_id)
        else:
            points = 0
            w.uint(5, 0)                     # NEUTRAL -> white gym
        w.bool_(8, True).uint(9, 0).int_(10, points).bool_(11, False)
    else:
        w.bool_(8, True).uint(9, 1)
    return w.to_bytes()


# ----------------------------------------------------- FORT_DETAILS / SEARCH
# Personalized names; chosen deterministically per fort_id so each stop/gym keeps
# its name. (Edit these to taste.)
STOP_NAMES = [
    "Dad's PokeStop", "Home Sweet Home", "The Backyard", "Front Porch Stop",
    "Memory Lane Marker", "Old Neighborhood Stop", "Kanto Korner", "The Big Oak",
    "Mailbox Marker", "Garden Gnome", "Corner Hangout", "The Birdhouse",
    "Sunset Bench", "Grandpa's Spot", "The Lucky Tree",
]
GYM_NAMES = [
    "Dad's Gym", "Home Field Arena", "The Backyard Battleground",
    "Neighborhood Gym", "Living Room League",
]


def _fort_is_gym(fort_id: str) -> bool:
    # Fort ids use the real Niantic shape "<32 hex>.<n>" where the suffix encodes the
    # type (16 = Gym, 11 = PokeStop). The old "GYM"/"FORT" prefix check stopped working
    # when the ids were made authentic, which made every Gym report as a PokeStop.
    return fort_id.rsplit(".", 1)[-1] == "16"


def l17_forts(cid15, now_ms):
    """Forts for ONE requested level-15 cell (~300m across).

    Real 2016 GetMapObjects returns only a HANDFUL of forts per level-15 cell.
    We used to emit 1 Gym + 3 stops in each of the 16 level-17 children = 64 forts
    in a single cell, which is wildly denser than anything Niantic ever sent; a
    client that sanity-checks cell contents can reject the batch outright. Emit a
    realistic 2-3 forts per cell, spread over the cell, deterministic per cell id.
    """
    out = []
    try:
        rnd = _random.Random(cid15 ^ 0xF0E7)
        kids = _l17_centres(cid15)
        if not kids:
            return out                                     # 16 level-17
        per = max(0, _cfg.get("pokestops", "per_l15_cell", cast=int))
        gym_chance = _cfg.get("gyms", "chance_per_l15_cell", cast=float)
        # Sit each stop on a DIFFERENT level-17 child so several in one cell are
        # properly spread out rather than clustered at the centre.
        picks = rnd.sample(kids, min(per + 1, len(kids)))
        for kid, klat, klng in picks[:per]:
            out.append(build_fort(f"{_hex_id(kid)}.11", klat, klng,
                                  now_ms, is_gym=False))
        if rnd.random() < gym_chance and len(picks) > per:
            kid, klat, klng = picks[per]
            out.append(build_fort(f"{_hex_id(kid)}.16", klat, klng,
                                  now_ms, is_gym=True))
    except Exception:
        pass
    return out


def build_fort_details_response(fort_id, lat, lng) -> bytes:
    # FortDetailsResponse { fort_id=1, team_color=2, name=4, image_urls=5,
    #   type=9 (GYM=0, CHECKPOINT=1), latitude=10, longitude=11, description=12 }
    gym = _fort_is_gym(fort_id)
    names = GYM_NAMES if gym else STOP_NAMES
    import world as _w
    _mod = None if gym else _w.fort_modifier(fort_id)
    name = _PLACED_NAMES.get(fort_id) or names[abs(hash(fort_id)) % len(names)]
    w = (pb.Writer()
         .string(1, fort_id)
         .string(4, name))
    # FortDetailsResponse.image_urls = 5 -- always at least one, same reason.
    w.string(5, _fort_image_url(fort_id))
    w.uint(9, 0 if gym else 1)
    w.double(10, lat)
    w.double(11, lng)
    if gym:                                   # stops get no description; gyms keep theirs
        w.string(12, "A little piece of home.")
    if _mod:
        # On the DETAIL screen the lure is a full message -- FortDetailsOutProto
        # .Modifier = 13, ClientFortModifierProto{ type=1, expires=2, by=3 }.
        w.message(13, pb.Writer()
                  .uint(1, int(_mod["item"]))
                  .int_(2, int(_mod["expires_ms"]))
                  .string(3, str(_mod.get("by", "")))
                  .to_bytes())
    return w.to_bytes()


def build_item_award(item_id, count) -> bytes:
    return pb.Writer().uint(1, item_id).int_(2, count).to_bytes()


# ------------------------------------------------------ ENCOUNTER / CATCH
def parse_encounter(msg: bytes):
    """EncounterMessage { encounter_id=1 fixed64, spawnpoint_id=2,
    player_latitude=3, player_longitude=4 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_64)


def parse_catch(msg: bytes):
    """CatchPokemonMessage { encounter_id=1 fixed64, pokeball=2,
    normalized_reticle_size=3 double, spawn_point_guid=4, hit_pokemon=5,
    spin_modifier=6 double, normalized_hit_position=7 double }.

    Returns (encounter_id, pokeball, hit, reticle, spin, hit_position).

    normalized_reticle_size is the ring size AT THE MOMENT OF THE THROW, which is
    what decides the Nice/Great/Excellent tier. normalized_hit_position is where
    the ball actually landed -- the two are independent, so a tight ring plus a
    sloppy throw is what produces "it said Excellent but I missed the circle".
    We used to drop field 7 on the floor; see throw_bonus()."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_64),
            pb.get(f, 2, pb.WT_VARINT) or ITEM_POKE_BALL,
            bool(pb.get(f, 5, pb.WT_VARINT)),
            _f64_to_double(pb.get(f, 3, pb.WT_64)),
            _f64_to_double(pb.get(f, 6, pb.WT_64)),
            _f64_to_double(pb.get(f, 7, pb.WT_64)))


# ActivityType values used for catch bonuses
ACT_CATCH = 1
ACT_NICE = 10
ACT_GREAT = 11
ACT_EXCELLENT = 12
ACT_CURVEBALL = 13

# Throw quality comes from normalized_reticle_size: the ring shrinks as you hold,
# and a bigger number means a tighter ring. Thresholds match the 2016 game.
def _throw_tiers():
    return [(1.7, ACT_EXCELLENT, "Excellent",
             _cfg.get("catching", "xp_excellent_throw", cast=int)),
            (1.3, ACT_GREAT, "Great",
             _cfg.get("catching", "xp_great_throw", cast=int)),
            (1.0, ACT_NICE, "Nice",
             _cfg.get("catching", "xp_nice_throw", cast=int))]


def throw_accuracy_ok(hit_position):
    """Did the ball actually land inside the ring?

    The tier comes from the RING size, so on its own it will happily hand out
    "Excellent" for a ball that clipped the edge of the Pokemon while the ring
    happened to be small. Gating on where the ball landed is what makes the
    bonus mean something.

    normalized_hit_position is a 0..1 double, but which end is the bullseye is
    not documented for 0.29 and POGOProtos is unreliable for this build, so the
    sense is a setting rather than a guess baked into the code:
      center_is_one  -> 1.0 is dead centre (bonus needs value >= tolerance)
      center_is_zero -> 0.0 is dead centre (bonus needs value <= 1 - tolerance)
    Read the `hitpos=` values the log now prints for a few throws and set
    catching.throw_accuracy_sense to whichever matches what you did.
    """
    if not _cfg.get("catching", "require_ball_in_circle", cast=bool):
        return True
    if hit_position is None:
        return True                    # client didn't send it; don't punish that
    tol = _cfg.get("catching", "throw_accuracy_tolerance", cast=float)
    if _cfg.get("catching", "throw_accuracy_sense") == "center_is_zero":
        return float(hit_position) <= (1.0 - tol)
    return float(hit_position) >= tol


def throw_bonus(reticle, spin=0.0, hit_position=None):
    """(activity, label, xp) for the throw, or None for an ordinary one."""
    if not throw_accuracy_ok(hit_position):
        return None
    for threshold, act, label, xp in _throw_tiers():
        if reticle >= threshold:
            return act, label, xp
    return None


def build_capture_award(reticle=0.0, spin=0.0, hit_position=None):
    """CaptureAward { activity_type=1, xp=2, candy=3, stardust=4 } -- four PARALLEL
    repeated arrays, one slot per bonus line the client shows on the catch screen."""
    acts, xps, candy, dust = ([ACT_CATCH],
                              [_cfg.get("catching", "xp_per_catch", cast=int)],
                              [_cfg.get("catching", "candy_per_catch", cast=int)],
                              [_cfg.get("catching", "stardust_per_catch", cast=int)])
    bonus = throw_bonus(reticle, spin, hit_position)
    if bonus:
        act, _label, xp = bonus
        acts.append(act); xps.append(xp); candy.append(0); dust.append(0)
    if spin and spin >= 1.0:                       # curveball
        acts.append(ACT_CURVEBALL)
        xps.append(_cfg.get("catching", "xp_curveball", cast=int))
        candy.append(0); dust.append(0)
    return (pb.Writer()
            .packed_varints(1, acts)
            .packed_varints(2, xps)
            .packed_varints(3, candy)
            .packed_varints(4, dust)
            .to_bytes()), sum(xps)


def fast_catch():
    """True = catching is over quickly: see settings.json catching.fast_catch."""
    try:
        return bool(_cfg.get("catching", "fast_catch", cast=bool))
    except Exception:
        return False


def build_capture_probability(pokemon_id=None, cp=0) -> bytes:
    """CaptureProbability { pokeball_type=1 (repeated enum), capture_probability=2
    (repeated FLOAT), reticle_difficulty_scale=12 }.

    This is what colours the target ring, and it is also what the client's
    GetNumShakes reads to decide how long the ball rocks before it settles -- so
    a high number here is both honest signalling and a shorter animation. It used
    to be a fixed 0.55/0.75/0.9 for every Pokemon regardless of what you were
    facing; now it reports this Pokemon's real odds with each ball."""
    balls = [ITEM_POKE_BALL, ITEM_GREAT_BALL, ITEM_ULTRA_BALL]
    if fast_catch() or pokemon_id is None:
        odds = [1.0, 1.0, 1.0] if fast_catch() else [0.55, 0.75, 0.9]
    else:
        odds = [round(catch_chance(pokemon_id, cp, b, 0.0, 1.0), 3) for b in balls]
        # The client's GetNumShakes reads these to decide how long the ball rocks.
        # Resisting Pokemon have low real odds and so broke out on the first shake;
        # floor the REPORTED number so a break-out wobbles a couple of times first.
        # This only changes the animation -- the true odds in catch_chance() decide
        # whether it holds.
        floor = _cfg.get("catching", "min_shake_probability", cast=float)
        odds = [round(max(o, floor), 3) for o in odds]
    return (pb.Writer()
            .packed_varints(1, balls)
            .packed_floats(2, odds)
            .to_bytes())


def build_encounter_response(encounter_id, now_ms) -> bytes:
    """EncounterResponse { wild_pokemon=1, background=2, status=3, capture_probability=4 }
    Status: 1=ENCOUNTER_SUCCESS, 2=NOT_FOUND, 5=NOT_IN_RANGE.

    Tapping a Pokemon sends ENCOUNTER. We used to answer with an EMPTY response,
    which the client reads as 'this spawn is gone' -- so the Pokemon vanished on tap.
    Look the spawn up in world.SPAWNS (recorded when we announced it on the map) and
    hand back the full WildPokemon so the catch screen can open.
    """
    import world
    s = world.get_spawn(encounter_id)
    if not s:
        return pb.Writer().uint(3, 2).to_bytes()          # ENCOUNTER_NOT_FOUND
    world.bump("pokemons_encountered")
    world.pokedex_saw(s["pokemon_id"])
    wild = build_wild_pokemon(encounter_id, s["lat"], s["lng"], s["spawn_id"],
                              s["pokemon_id"], now_ms, 10 * 60 * 1000, cp=s["cp"])
    return (pb.Writer()
            .message(1, wild)
            .uint(3, 1)                                   # ENCOUNTER_SUCCESS
            .message(4, build_capture_probability(s["pokemon_id"], s["cp"]))
            .to_bytes())


def _score_medals(pokemon_id, uid):
    """Everything a catch counts towards on the Medals page: the 18 type medals,
    the two size medals, and Pikachu Fan."""
    import world
    world.bump_type(pokemon_id)
    _h, w_kg = pokemon_size(pokemon_id, uid)
    if pokemon_id == 129 and is_xl(pokemon_id, w_kg):        # Magikarp
        world.bump("big_magikarp")
    if pokemon_id == 19 and is_xs(pokemon_id, w_kg):         # Rattata
        world.bump("small_rattata")
    if pokemon_id == 25:                                     # Pikachu
        world.bump("pikachu_caught")


def build_catch_pokemon_response(encounter_id, pokeball, hit, now_ms,
                                 reticle=0.0, spin=0.0, hit_position=None) -> bytes:
    """CatchPokemonResponse { status=1, miss_percent=2, captured_pokemon_id=3,
    capture_award=4 }. CatchStatus: 1=SUCCESS, 2=ESCAPE, 3=FLEE, 4=MISSED."""
    import world
    s = world.get_spawn(encounter_id)
    if not s:
        return pb.Writer().uint(1, 3).to_bytes()          # CATCH_FLEE (unknown spawn)
    if not hit:
        # A missed throw STILL COSTS THE BALL -- it does in the real game, and
        # without this a dropped or wide ball was free, so the counter never
        # moved and you could farm an encounter forever on one Poke Ball.
        world.take_item(pokeball, 1)
        return pb.Writer().uint(1, 4).double(2, 0.0).to_bytes()   # CATCH_MISSED
    if world.pokemon_full():
        # Nowhere to put it. Fleeing is the closest honest answer the protocol has.
        return pb.Writer().uint(1, 3).to_bytes()          # CATCH_FLEE
    if not world.take_item(pokeball, 1):                  # consume the thrown ball
        return pb.Writer().uint(1, 4).double(2, 0.0).to_bytes()   # out of that ball

    # Does it hold? A berry bought for THIS encounter is spent here.
    mult = world.berry_mult(encounter_id)
    # Fast catching: no break-outs and no fleeing, so an encounter is one throw
    # instead of three or four. Together with the capture_probability of 1.0 the
    # ball settles on the first wobble, which is where the rest of the time goes.
    chance = 2.0 if fast_catch() else catch_chance(s["pokemon_id"], s["cp"],
                                                   pokeball, reticle, mult,
                                                   hit_position)
    # Mix the seed properly. `encounter_id ^ now_ms` looks random but both values
    # climb together, so their low bits cancel and successive throws came out
    # correlated -- the flee roll never fired once in 64 break-outs.
    seed = (int(encounter_id) * 0x9E3779B97F4A7C15) ^ (int(now_ms) * 0xC2B2AE3D27D4EB4F)
    seed = (seed ^ (seed >> 29)) & 0x7FFFFFFFFFFFFFFF
    rnd = _random.Random(seed)
    if rnd.random() > chance:
        world.berry_mult(encounter_id, consume=True)      # the berry is used up
        flee = _cfg.get("catching", "flee_chance", cast=float) / max(1.0, mult)
        if rnd.random() < flee:
            world.remove_spawn(encounter_id)              # gone for good
            world.mark_despawned(encounter_id, _window(now_ms)[1])
            return pb.Writer().uint(1, 3).to_bytes()      # CATCH_FLEE
        return pb.Writer().uint(1, 2).to_bytes()          # CATCH_ESCAPE - try again
    world.berry_mult(encounter_id, consume=True)
    # NOT `encounter_id ^ 0xC0FFEE` any more -- that is fixed per spawn point, so
    # catching at the same place twice reused the id and the client, which keys
    # Pokemon by id, just overwrote the earlier one.
    uid = world.new_uid(encounter_id)
    world.add_caught(uid, s["pokemon_id"], s["cp"])
    world.pokedex_caught(s["pokemon_id"])
    _score_medals(s["pokemon_id"], uid)
    world.remove_spawn(encounter_id)                      # it's ours now; clear the map
    world.drop_bonus_spawn(world.current().username, encounter_id)
    # ...and keep it gone. Spawns are regenerated deterministically per window, so
    # without this the next GET_MAP_OBJECTS would put it right back on the map.
    world.mark_despawned(encounter_id, _window(now_ms)[1])
    award, total_xp = build_capture_award(reticle, spin, hit_position)
    world.add_xp(total_xp)
    # The catch screen has always SHOWN "+candy, +stardust", but nothing ever
    # credited them -- stardust sat at its starting value forever and the only
    # candy you could get was 1 per transfer.
    world.add_candy(pokemon_family(s["pokemon_id"]),
                    _cfg.get("catching", "candy_per_catch", cast=int))
    world.add_stardust(_cfg.get("catching", "stardust_per_catch", cast=int))
    return (pb.Writer()
            .uint(1, 1)                                   # CATCH_SUCCESS
            .double(2, 0.0)                               # miss_percent
            .uint(3, uid)                                 # captured_pokemon_id
            .message(4, award)                            # capture_award
            .to_bytes())


# ------------------------------------------------- POKEMON MANAGEMENT (evolve etc)
_EVO = None
_EGG_POOLS = None


def _evo_table():
    """{pokemon_id: {"family": id, "evolves_to": [ids], "candy": n}} read straight
    out of the game master we already serve, so costs match what the client shows."""
    global _EVO
    if _EVO is None:
        table = {}
        try:
            # read game_master.bin DIRECTLY -- going through the response builder
            # made this depend on SERVE_GAME_MASTER being set, so evolution data
            # silently vanished and everything reported CANNOT_EVOLVE.
            gm = os.path.join(_HERE, "game_master.bin")
            with open(gm, "rb") as fh:
                data = fh.read()
            for t in pb.get_all(pb.decode(data), 2):
                tt = pb.decode(t)
                ps = pb.get(tt, 2, pb.WT_LEN)
                if not ps:
                    continue
                p = pb.decode(ps)
                pid = pb.get(p, 1, pb.WT_VARINT)
                if not pid:
                    continue
                raw = pb.get(p, 12, pb.WT_LEN) or b""      # evolution_ids (packed)
                evo, i = [], 0
                while i < len(raw):
                    v, sh = 0, 0
                    while True:
                        b = raw[i]; i += 1
                        v |= (b & 0x7F) << sh
                        if not b & 0x80:
                            break
                        sh += 7
                    evo.append(v)
                table[pid] = {"family": pb.get(p, 21, pb.WT_VARINT) or pid,
                              "evolves_to": evo,
                              "candy": pb.get(p, 22, pb.WT_VARINT) or 0}
        except Exception:
            pass
        _EVO = table
    return _EVO


def pokemon_family(pokemon_id):
    return _evo_table().get(pokemon_id, {}).get("family", pokemon_id)


_POKE_META = None


def _poke_meta():
    """{pokemon_id: {"types": (t1, t2), "height": m, "weight": kg,
                     "height_sd": m, "weight_sd": kg}} from the game master.

    Field numbers read out of the client itself (PokemonSettingsProto):
    Type1=4, Type2=5, PokedexHeightM=15, PokedexWeightKg=16, HeightStdDev=18,
    WeightStdDev=19."""
    global _POKE_META
    if _POKE_META is None:
        table = {}
        try:
            with open(os.path.join(_HERE, "game_master.bin"), "rb") as fh:
                data = fh.read()
            for t in pb.get_all(pb.decode(data), 2):
                ps = pb.get(pb.decode(t), 2, pb.WT_LEN)
                if not ps:
                    continue
                p = pb.decode(ps)
                pid = pb.get(p, 1, pb.WT_VARINT)
                if not pid:
                    continue
                types = tuple(x for x in (pb.get(p, 4, pb.WT_VARINT),
                                          pb.get(p, 5, pb.WT_VARINT)) if x)
                table[pid] = {
                    "types": types,
                    "height": _f32(pb.get(p, 15, pb.WT_32)) or 0.6,
                    "weight": _f32(pb.get(p, 16, pb.WT_32)) or 8.0,
                    "height_sd": _f32(pb.get(p, 18, pb.WT_32)) or 0.05,
                    "weight_sd": _f32(pb.get(p, 19, pb.WT_32)) or 1.0,
                }
        except Exception:
            pass
        _POKE_META = table
    return _POKE_META


def _f32(raw):
    """pb decodes wire-type 5 as a raw uint32; reinterpret it as a float."""
    if raw is None:
        return 0.0
    return _struct.unpack("<f", _struct.pack("<I", raw))[0]


def pokemon_types(pokemon_id):
    """(type,) or (type, type_2) as HoloPokemonType values -- what the type
    medals (Bug Catcher, Fisherman, ...) are counted against."""
    return _poke_meta().get(int(pokemon_id or 0), {}).get("types", ())


# --- battle type effectiveness -----------------------------------------------
# July-2016 multipliers: 1.25x up / 0.8x down (the pre-2017 chart). A Pokemon's
# attack is treated as one of its OWN types (its STAB move) -- the common case,
# and it keeps this to the species type data we already have. This is what makes
# a gym fight a matchup instead of a flat number: HP and victory are read from
# build_attack_gym_response, so a super-effective attacker really does win faster
# and a bad matchup can lose. HoloPokemonType ints, per pokemon_types().
_T = {"normal": 1, "fighting": 2, "flying": 3, "poison": 4, "ground": 5,
      "rock": 6, "bug": 7, "ghost": 8, "steel": 9, "fire": 10, "water": 11,
      "grass": 12, "electric": 13, "psychic": 14, "ice": 15, "dragon": 16,
      "dark": 17, "fairy": 18}


def _mk_chart(pairs):
    return {_T[k]: {_T[x] for x in v.split()} for k, v in pairs.items()}


_SE = _mk_chart({
    "fighting": "normal rock steel ice dark",
    "flying": "fighting bug grass",
    "poison": "grass fairy",
    "ground": "poison rock steel fire electric",
    "rock": "flying bug fire ice",
    "bug": "grass psychic dark",
    "ghost": "ghost psychic",
    "steel": "rock ice fairy",
    "fire": "bug steel grass ice",
    "water": "ground rock fire",
    "grass": "ground rock water",
    "electric": "flying water",
    "psychic": "fighting poison",
    "ice": "flying ground grass dragon",
    "dragon": "dragon",
    "dark": "ghost psychic",
    "fairy": "fighting dragon dark",
})
# Not-very-effective, with immunities folded in as one further step down (0.8),
# so a "no effect" matchup slows the fight rather than stalling it at zero.
_NVE = _mk_chart({
    "normal": "rock steel ghost",
    "fighting": "flying poison bug psychic fairy ghost",
    "flying": "rock steel electric",
    "poison": "poison ground rock ghost steel",
    "ground": "bug grass flying",
    "rock": "fighting ground steel",
    "bug": "fighting flying poison ghost steel fire fairy",
    "ghost": "dark normal",
    "steel": "steel fire water electric",
    "fire": "rock fire water dragon",
    "water": "water grass dragon",
    "grass": "flying poison bug steel fire grass dragon",
    "electric": "grass electric dragon ground",
    "psychic": "steel psychic dark",
    "ice": "steel fire water ice",
    "dragon": "steel fairy",
    "dark": "fighting dark fairy",
    "fairy": "poison steel fire",
})


def type_multiplier(atk_types, def_types):
    """2016 effectiveness of an attacker's STAB move against a (possibly dual)
    defender, using the attacker's most advantageous type. Neutral (1.0) when
    either side's types are unknown, so this can never make a battle worse."""
    atk_types = tuple(atk_types or ())
    def_types = tuple(def_types or ())
    if not atk_types or not def_types:
        return 1.0
    best = 0.0
    for at in atk_types:
        m = 1.0
        for dt in def_types:
            if dt in _SE.get(at, ()):
                m *= 1.25
            elif dt in _NVE.get(at, ()):
                m *= 0.8
        best = max(best, m)
    return best or 1.0


def _effectiveness(move_type, def_types):
    """2016 effectiveness of one MOVE type against a (possibly dual) defender."""
    m = 1.0
    for dt in (def_types or ()):
        if dt in _SE.get(move_type, ()):
            m *= 1.25
        elif dt in _NVE.get(move_type, ()):
            m *= 0.8
    return m


def pokemon_size(pokemon_id, uid):
    """(height_m, weight_kg) for one individual, rolled deterministically from
    its uid around the species' pokedex values. Every Pokemon used to report a
    flat 0.6 m / 8.0 kg, which made the Pokedex size readout meaningless and the
    two size medals unearnable."""
    m = _poke_meta().get(int(pokemon_id or 0))
    if not m:
        return 0.6, 8.0
    rnd = _random.Random((int(uid) or 1) * 0x27D4EB2F)
    # The real game rolls a size multiplier and scales weight by its cube, so a
    # tall Pokemon is heavy too rather than the two drifting apart.
    dev = max(-2.5, min(2.5, rnd.gauss(0.0, 1.0)))
    height = max(0.01, m["height"] + dev * m["height_sd"])
    ratio = height / m["height"] if m["height"] else 1.0
    weight = max(0.01, (m["weight"] + dev * m["weight_sd"]) * (ratio ** 0.5))
    return round(height, 3), round(weight, 3)


def is_xl(pokemon_id, weight_kg):
    """Big enough for the XL medals (Magikarp) -- two standard deviations up."""
    m = _poke_meta().get(int(pokemon_id or 0))
    return bool(m) and weight_kg >= m["weight"] + 2.0 * m["weight_sd"]


def is_xs(pokemon_id, weight_kg):
    """Small enough for the XS medals (Rattata)."""
    m = _poke_meta().get(int(pokemon_id or 0))
    return bool(m) and weight_kg <= m["weight"] - 2.0 * m["weight_sd"]


# ---------------------------------------------------------------- MEDALS
# The Medals page of the trainer profile. All of it comes from
# GET_PLAYER_PROFILE (=121): PlayerProfileOutProto{ result=1, start_time=2,
# badges=3 } with a PlayerBadgeProto{ badge_type=1, rank=2, start_value=3,
# end_value=4, current_value=5 } per medal. Field numbers and the HoloBadgeType
# values below were read out of the client's own global-metadata.dat
# (tools/metadata_fields.py), not from POGOProtos.
BADGE_TRAVEL_KM = 1
BADGE_POKEDEX_ENTRIES = 2
BADGE_CAPTURE_TOTAL = 3
BADGE_EVOLVED_TOTAL = 5
BADGE_HATCHED_TOTAL = 6
BADGE_POKESTOPS_VISITED = 8
BADGE_BIG_MAGIKARP = 11
BADGE_BATTLE_ATTACK_WON = 13
BADGE_BATTLE_TRAINING_WON = 14
BADGE_TYPE_FIRST = 18        # BADGE_TYPE_NORMAL; the 18 type medals run 18..35
BADGE_SMALL_RATTATA = 36
BADGE_PIKACHU = 37

# HoloBadgeType for a type medal = BADGE_TYPE_FIRST + (HoloPokemonType - 1),
# which holds for all 18: NORMAL(1)->18 ... FAIRY(18)->35.
def _type_badge(pokemon_type):
    return BADGE_TYPE_FIRST + int(pokemon_type) - 1


_BADGE_TARGETS = None


def _badge_targets():
    """{badge_type: [rank1, rank2, rank3]} from the game master's BadgeSettings
    (badge_type=1, badge_ranks=2, targets=3 packed). Serving thresholds we made
    up would put the client's progress bars out of step with the medal art it
    already has, so read Niantic's own numbers."""
    global _BADGE_TARGETS
    if _BADGE_TARGETS is None:
        table = {}
        try:
            with open(os.path.join(_HERE, "game_master.bin"), "rb") as fh:
                data = fh.read()
            for t in pb.get_all(pb.decode(data), 2):
                bs = pb.get(pb.decode(t), 10, pb.WT_LEN)       # badge settings
                if not bs:
                    continue
                b = pb.decode(bs)
                bt = pb.get(b, 1, pb.WT_VARINT)
                raw = pb.get(b, 3, pb.WT_LEN) or b""
                if bt:
                    table[bt] = _unpack_varints(raw)
        except Exception:
            pass
        _BADGE_TARGETS = table
    return _BADGE_TARGETS


def _unpack_varints(raw):
    out, i = [], 0
    while i < len(raw):
        v, sh = 0, 0
        while i < len(raw):
            b = raw[i]; i += 1
            v |= (b & 0x7F) << sh
            if not b & 0x80:
                break
            sh += 7
        out.append(v)
    return out


def _badge_values():
    """{badge_type: how far the player has got}. Only medals the game master
    actually defines are worth reporting -- the client has no art or targets for
    the rest."""
    import world
    st = world.STATS
    by_type = world.caught_by_type()
    vals = {
        BADGE_TRAVEL_KM: st.get("km_walked", 0.0),
        BADGE_POKEDEX_ENTRIES: st.get("unique_pokedex_entries", 0),
        BADGE_CAPTURE_TOTAL: st.get("pokemons_captured", 0),
        BADGE_EVOLVED_TOTAL: st.get("evolutions", 0),
        BADGE_HATCHED_TOTAL: st.get("eggs_hatched", 0),
        BADGE_POKESTOPS_VISITED: st.get("poke_stop_visits", 0),
        BADGE_BIG_MAGIKARP: st.get("big_magikarp", 0),
        BADGE_BATTLE_ATTACK_WON: st.get("battle_attack_won", 0),
        BADGE_BATTLE_TRAINING_WON: st.get("battle_training_won", 0),
        BADGE_SMALL_RATTATA: st.get("small_rattata", 0),
        BADGE_PIKACHU: st.get("pikachu_caught", 0),
    }
    for ptype, n in by_type.items():
        vals[_type_badge(ptype)] = n
    return vals


def badge_progress():
    """[(badge_type, rank, start_value, end_value, current_value)] for every
    medal the client knows about.

    rank = how many targets have been passed. start/end bracket the CURRENT
    rank, so the progress bar fills from the last threshold to the next one."""
    out = []
    targets = _badge_targets()
    values = _badge_values()
    for bt, tgts in sorted(targets.items()):
        if not tgts:
            continue
        cur = values.get(bt, 0)
        rank = sum(1 for t in tgts if cur >= t)
        start = tgts[rank - 1] if rank else 0
        end = tgts[min(rank, len(tgts) - 1)]
        out.append((bt, rank, start, end, cur))
    return out


def build_player_badge(badge_type, rank, start, end, current) -> bytes:
    """PlayerBadge { badge_type=1, rank=2, start_value=3 int32, end_value=4 int32,
    current_value=5 DOUBLE }. current_value is a DOUBLE (verified vs the proto) --
    it was being written as an int varint, so the client read it as garbage and
    every medal showed 0 progress no matter how much you'd done."""
    return (pb.Writer()
            .uint(1, int(badge_type))
            .int_(2, int(rank))
            .int_(3, int(start))
            .int_(4, int(end))
            .double(5, float(current))
            .to_bytes())


def build_player_profile_response(now_ms=None) -> bytes:
    """PlayerProfileOutProto { result=1, start_time=2, badges=3 }.
    result 1=SUCCESS. This request used to fall through to an empty response,
    which is why the Medals page was blank however much you played."""
    import world
    w = pb.Writer().uint(1, 1)
    # "Trainer since": the day this account's save first appeared on disk.
    try:
        start = int(os.path.getctime(world.current().file) * 1000)
    except OSError:
        start = int((now_ms or time.time() * 1000) - 86_400_000)
    w.int_(2, start)
    for bt, rank, lo, hi, cur in badge_progress():
        w.message(3, build_player_badge(bt, rank, lo, hi, cur))
    return w.to_bytes()


def build_check_awarded_badges_response() -> bytes:
    """CheckAwardedBadgesOutProto { success=1, awarded_badges=2,
    awarded_badge_levels=3 } -- the medal-earned popup. Both lists are packed
    and positional: badge[i] was just awarded at level[i].

    Only ranks we have never announced are sent, so the popup fires once."""
    import world
    badges, levels = [], []
    for bt, rank, _lo, _hi, _cur in badge_progress():
        if rank > world.badge_rank(bt):
            world.claim_badge(bt, rank)
            badges.append(bt)
            levels.append(rank)
    w = pb.Writer().bool_(1, True)
    if badges:
        w.packed_varints(2, badges).packed_varints(3, levels)
    return w.to_bytes()


def badge_name(badge_type):
    """For the server log -- the client shows its own localised names."""
    return _BADGE_NAMES.get(int(badge_type), f"badge {badge_type}")


_BADGE_NAMES = {
    BADGE_TRAVEL_KM: "Jogger", BADGE_POKEDEX_ENTRIES: "Kanto",
    BADGE_CAPTURE_TOTAL: "Collector", BADGE_EVOLVED_TOTAL: "Scientist",
    BADGE_HATCHED_TOTAL: "Breeder", BADGE_POKESTOPS_VISITED: "Backpacker",
    BADGE_BIG_MAGIKARP: "Fisherman", BADGE_BATTLE_ATTACK_WON: "Battle Girl",
    BADGE_BATTLE_TRAINING_WON: "Ace Trainer", BADGE_SMALL_RATTATA: "Youngster",
    BADGE_PIKACHU: "Pikachu Fan",
    18: "Schoolkid", 19: "Black Belt", 20: "Bird Keeper", 21: "Punk Girl",
    22: "Ruin Maniac", 23: "Hiker", 24: "Bug Catcher", 25: "Hex Maniac",
    26: "Depot Agent", 27: "Kindler", 28: "Swimmer", 29: "Gardener",
    30: "Rocker", 31: "Psychic", 32: "Skier", 33: "Dragon Tamer",
    34: "Delinquent", 35: "Fairy Tale Girl",
}


def parse_pokemon_id(msg):
    """Every one of these messages is just { pokemon_id = 1 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_64) or pb.get(f, 1, pb.WT_VARINT) or 0


def build_release_response(uid) -> bytes:
    """ReleasePokemonResponse { result=1, candy_awarded=2 }.
    1=SUCCESS, 2=POKEMON_DEPLOYED, 3=FAILED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 3).to_bytes()               # FAILED
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 2).to_bytes()               # POKEMON_DEPLOYED
    ok, _why = world.release(uid)
    if not ok:
        return pb.Writer().uint(1, 3).to_bytes()
    fam = pokemon_family(c["pokemon_id"])
    world.add_candy(fam, 1)
    return pb.Writer().uint(1, 1).int_(2, 1).to_bytes()        # SUCCESS, 1 candy


def build_upgrade_response(uid) -> bytes:
    """UpgradePokemonResponse { result=1, upgraded_pokemon=2 }.
    1=SUCCESS, 2=NOT_FOUND, 3=INSUFFICIENT_RESOURCES, 5=IS_DEPLOYED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 5).to_bytes()
    pid = c["pokemon_id"]
    fam = pokemon_family(pid)

    newcp = None
    if _cfg.get("pokemon", "real_powerups", cast=bool):
        try:
            import leveling
            iv_a, iv_d, iv_s = _ivs(uid)
            cur = leveling.level_index_for_cpm(cpm_for(pid, c["cp"], iv_a, iv_d, iv_s))
            trainer_level, _ = world.stats()
            target = cur + 1
            # Already maxed, or the next step is above what your trainer level
            # allows: the real client greys the button -> UPGRADE_NOT_AVAILABLE.
            if target > leveling.MAX_INDEX or target > leveling.max_index_for_trainer(trainer_level):
                return pb.Writer().uint(1, 4).to_bytes()
            _cpm, cost_dust, cost_candy = leveling.LEVELS[cur]
            if not world.spend(fam, cost_candy, cost_dust):
                return pb.Writer().uint(1, 3).to_bytes()       # can't afford it
            newcp = cp_at_level(pid, uid, leveling.LEVELS[target][0])
        except Exception:
            newcp = None               # leveling unavailable: fall back to flat

    if newcp is None:
        cost_candy = _cfg.get("pokemon", "powerup_candy", cast=int)
        cost_dust = _cfg.get("pokemon", "powerup_stardust", cast=int)
        if not world.spend(fam, cost_candy, cost_dust):
            return pb.Writer().uint(1, 3).to_bytes()           # can't afford it
        gain = _cfg.get("pokemon", "powerup_cp_gain", cast=int)
        newcp = int(c["cp"] * (1 + gain / 100.0)) + 10

    upd = world.update_caught(uid, cp=newcp,
                              num_upgrades=int(c.get("num_upgrades", 0)) + 1)
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_pokemon_data(upd["pokemon_id"], uid, newcp))
            .to_bytes())


def build_evolve_response(uid) -> bytes:
    """EvolvePokemonResponse { result=1, evolved_pokemon_data=2,
    experience_awarded=3, candy_awarded=4 }.
    1=SUCCESS, 2=MISSING, 3=INSUFFICIENT_RESOURCES, 4=CANNOT_EVOLVE, 5=DEPLOYED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 5).to_bytes()
    info = _evo_table().get(c["pokemon_id"], {})
    evo = info.get("evolves_to") or []
    if not evo:
        return pb.Writer().uint(1, 4).to_bytes()               # CANNOT_EVOLVE
    need = info.get("candy") or 25
    fam = info.get("family", c["pokemon_id"])
    if not world.spend(fam, need, 0):
        return pb.Writer().uint(1, 3).to_bytes()
    new_id = _random.Random(uid).choice(evo)                   # Eevee branches
    newcp = int(c["cp"] * 1.6) + 20
    world.update_caught(uid, pokemon_id=new_id, cp=newcp)
    xp = _cfg.get("pokemon", "evolve_xp", cast=int)
    world.add_xp(xp)
    world.add_candy(fam, 1)                                    # evolving pays 1 back
    world.bump("evolutions")                                   # Scientist medal
    world.pokedex_caught(new_id)                               # the new form is yours
    world.bump_type(new_id)
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_pokemon_data(new_id, uid, newcp))
            .int_(3, xp)
            .int_(4, 1)
            .to_bytes())


def build_nickname_response(uid, nickname) -> bytes:
    """NicknamePokemonResponse { result=1 } (1=SUCCESS)."""
    import world
    world.update_caught(uid, nickname=nickname[:12])
    return pb.Writer().uint(1, 1).to_bytes()


def build_favorite_response(uid, is_fav) -> bytes:
    """SetFavoritePokemonResponse { result=1 } (1=SUCCESS)."""
    import world
    world.update_caught(uid, favorite=1 if is_fav else 0)
    return pb.Writer().uint(1, 1).to_bytes()


# ------------------------------------------------------------- GYM BATTLES
# BattleState: 1=ACTIVE 2=VICTORY 3=DEFEATED 4=TIMED_OUT (all VERIFIED against
# POGOProtos BattleState.proto).
BS_ACTIVE, BS_VICTORY, BS_DEFEATED, BS_TIMED_OUT = 1, 2, 3, 4
# BattleType: 0=UNSET 1=NORMAL 2=TRAINING. Leaving this UNSET meant the client
# never knew which kind of battle to run, so it started one and then refused to
# send a single ATTACK_GYM. Attacking your OWN team's gym is TRAINING.
BT_NORMAL, BT_TRAINING = 1, 2
# BattleActionType (VERIFIED against POGOProtos BattleActionType.proto):
# 1=ATTACK 2=DODGE 3=SPECIAL_ATTACK 5=FAINT 6=PLAYER_JOIN 7=PLAYER_QUIT
# 8=VICTORY 9=DEFEAT. QUIT is what the client sends when you swipe out of a
# gym battle (flee); handling it lets the fight end cleanly instead of leaving
# a stale battle behind.
BA_ATTACK, BA_DODGE, BA_SPECIAL, BA_FAINT = 1, 2, 3, 5
BA_PLAYER_JOIN, BA_QUIT, BA_VICTORY, BA_DEFEAT = 6, 7, 8, 9


def _battle_pokemon_info(pokemon_id, uid, cp, hp, energy=0, extra=None,
                         hp_max=None) -> bytes:
    """BattlePokemonInfo { pokemon_data=1, current_health=2, current_energy=3 }.
    The HP BAR the client draws comes from pokemon_data.stamina/stamina_max, so
    those must carry the battle HP -- leaving stamina_max at 20 made a 260-HP
    defender look nearly dead and the fight ended on the first tap."""
    e = dict(extra or {})
    e["stamina"] = int(hp)
    e["stamina_max"] = int(hp_max if hp_max is not None else max(hp, 1))
    return (pb.Writer()
            .message(1, build_pokemon_data(pokemon_id, uid, cp, extra=e))
            .int_(2, int(hp))
            .int_(3, int(energy))
            .to_bytes())


def _battle_participant(pokemon_id, uid, cp, hp, trainer, level) -> bytes:
    """BattleParticipant { active_pokemon=1, trainer_public_profile=2,
    reverse_pokemon=3, defeated_pokemon=4 }."""
    profile = (pb.Writer().string(1, trainer).int_(2, level)
               .message(3, build_player_avatar()).to_bytes())
    return (pb.Writer()
            .message(1, _battle_pokemon_info(pokemon_id, uid, cp, hp))
            .message(2, profile)
            .to_bytes())


def _hp_for(cp, pokemon_id=None, uid=None):
    """Battle HP.

    Uses the REAL stamina formula, (base_stamina + iv) * cp_multiplier, whenever
    we know the species. The old cp*0.6+20 gave a 1200-CP defender 740 HP while
    a hit takes off ~12 -- 60 taps to win, which just reads as "attacks do no
    damage". Real max HP for that Pokemon is about 100, so a fight now runs the
    handful of hits it should, and the bar agrees with the CP on screen.
    """
    if pokemon_id is not None and uid is not None and _gd and pokemon_id in _gd.STATS:
        _ba, _bd, bs = _gd.STATS[pokemon_id]
        iv_a, iv_d, iv_s = _ivs(uid)
        return max(10, int((bs + iv_s) * cpm_for(pokemon_id, cp, iv_a, iv_d, iv_s)))
    return max(20, int(cp * 0.6) + 20)


def _battle_damage(atk_pid, atk_uid, atk_cp, def_pid, def_uid, def_cp, move_id,
                   own_types, tgt_types):
    """One hit's damage by the REAL 2016 formula:

        floor(0.5 * power * (Atk / Def) * STAB * effectiveness) + 1

    where Atk/Def are the effective stats -- (base + iv) * cp_multiplier -- of the
    two Pokemon. The client runs this same simulation locally to animate the swing,
    so matching it here is what keeps the HP BAR in step with the damage: the old
    flat `attack_damage`/`defender_damage` numbers had no relation to what the
    client computed, so the bar it drew and the HP we reported disagreed and the
    bar jumped. Returns None when we lack the species/move data, so the caller can
    fall back to the flat config values.
    """
    m = _gd.MOVES.get(move_id) if _gd else None
    if not (m and _gd and atk_pid in _gd.STATS and def_pid in _gd.STATS):
        return None
    power = m[4]
    if not power:
        return 1                              # a no-power move still chips 1 HP
    ba, _bd, _bs = _gd.STATS[atk_pid]         # attacker's base ATTACK
    _ad, bd, _ds = _gd.STATS[def_pid]         # defender's base DEFENSE
    ia_a, ia_d, ia_s = _ivs(atk_uid)
    id_a, id_d, id_s = _ivs(def_uid)
    atk = (ba + ia_a) * cpm_for(atk_pid, atk_cp, ia_a, ia_d, ia_s)
    dfn = (bd + id_d) * cpm_for(def_pid, def_cp, id_a, id_d, id_s)
    if dfn <= 0:
        return None
    mt = _gd.MOVE_TYPES.get(move_id)
    stab = 1.25 if (mt and mt in (own_types or ())) else 1.0
    eff = _effectiveness(mt, tgt_types) if mt else type_multiplier(own_types, tgt_types)
    return max(1, int(0.5 * power * (atk / dfn) * stab * eff) + 1)


def parse_start_gym_battle(msg):
    """StartGymBattleMessage { gym_id=1, attacking_pokemon_ids=2 (repeated fixed64),
    defending_pokemon_id=3, player_latitude=4, player_longitude=5 }."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    # attacking_pokemon_ids is `repeated fixed64` and the client sends it PACKED,
    # so it arrives as ONE length-delimited blob of 8-byte ids -- not as separate
    # fixed64 fields. Reading it as ints found nothing, so every battle reported
    # ERROR_ALL_POKEMON_FAINTED. Handle both encodings.
    attackers = []
    for v in pb.get_all(f, 2):
        if isinstance(v, int):
            attackers.append(v)                       # unpacked fixed64
        elif isinstance(v, bytes):
            for i in range(0, len(v) - 7, 8):         # packed: 8 bytes each
                attackers.append(_struct.unpack_from("<Q", v, i)[0])
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            attackers, pb.get(f, 3, pb.WT_VARINT) or pb.get(f, 3, pb.WT_64) or 0)


def build_start_gym_battle_response(gym_id, attacker_uids, defender_uid, now_ms) -> bytes:
    """StartGymBattleResponse { result=1, battle_start_timestamp_ms=2,
    battle_end_timestamp_ms=3, battle_id=4, defender=5, battle_log=6 }.
    1=SUCCESS 3=GYM_NEUTRAL 5=GYM_EMPTY 8=ALL_POKEMON_FAINTED 13=NOT_IN_RANGE."""
    import world
    members = world.gym_members(gym_id)
    if not members:
        return pb.Writer().uint(1, 5).to_bytes()               # GYM_EMPTY
    defender = next((m for m in members if m["uid"] == defender_uid),
                    max(members, key=lambda m: m.get("cp", 0)))
    # A Pokemon defending the gym cannot also attack it. Allowing that gave both
    # participants the SAME ActivePokemonId, so the client could not tell the two
    # sides apart -- it quietly restarted the battle under a fresh id, and every
    # reply we sent for the old id came back as "mismatched battleId".
    def _usable(c):
        return (c is not None and int(c.get("stamina", 20)) > 0
                and c["uid"] != defender["uid"]
                and not world.is_deployed(c["uid"]))

    atk = next((c for c in (world.get_caught(u) for u in attacker_uids)
                if _usable(c)), None)
    if atk is None:
        # Fall back to your strongest healthy Pokemon. The client's chosen team
        # should normally be honoured, but refusing the battle outright over a
        # parsing detail is much worse than picking a sensible attacker.
        healthy = [c for c in world.caught() if _usable(c)]
        if healthy:
            atk = max(healthy, key=lambda c: c.get("cp", 0))
    if atk is None:
        return pb.Writer().uint(1, 8).to_bytes()               # ALL_POKEMON_FAINTED

    is_raid = bool(defender.get("raid"))
    bid = "B%x%04x" % (now_ms, (defender["uid"] ^ atk["uid"]) & 0xFFFF)
    dhp = _hp_for(defender["cp"], defender["pokemon_id"], defender["uid"])
    ahp = _hp_for(atk["cp"], atk["pokemon_id"], atk["uid"])
    # Same-team gyms are TRAINING; enemy gyms are NORMAL (attack). The client runs
    # the fight locally and -- measured on this build -- will enter combat for a
    # TRAINING battle but NOT a NORMAL one, so enemy battles open and then freeze
    # ("can't attack"). battles.attack_as_training forces the TRAINING type for
    # enemy gyms too, as a workaround, so you can actually fight (the server still
    # clears the gym on victory).
    if world.gym_team(gym_id) == world.my_team() or _cfg.get(
            "battles", "attack_as_training", cast=bool):
        btype = BT_TRAINING
    else:
        btype = BT_NORMAL
    # Prestige: are we TRAINING our own team's gym (raise it) or ATTACKING an enemy
    # one (drain it)? The reported battle type is forced to TRAINING as a client
    # workaround, so decide from the real team relationship instead. `lineup` is a
    # snapshot of every defender (weakest first) so one battle run works through the
    # whole gym, and `beaten` tracks who's fallen this run without mutating the gym
    # until it's over.
    friendly = (world.gym_team(gym_id) == world.my_team()) and not is_raid
    lineup = [m["uid"] for m in sorted(members, key=lambda m: m.get("cp", 0))]
    world.BATTLES[bid] = {"gym": gym_id, "attacker": atk["uid"],
                          "defender": defender["uid"],
                          "atk_pid": atk["pokemon_id"], "def_pid": defender["pokemon_id"],
                          "atk_cp": atk["cp"], "def_cp": defender["cp"],
                          "atk_hp": ahp, "def_hp": dhp,
                          "atk_max": ahp, "def_max": dhp, "type": btype,
                          "raid": is_raid, "friendly": friendly,
                          "lineup": lineup, "beaten": [], "prestige_delta": 0,
                          "start": now_ms, "player": world.current().username}
    lvl, _xp = world.stats()
    me = _battle_participant(atk["pokemon_id"], atk["uid"], atk["cp"], ahp,
                             world.current().username, lvl)
    # A raid boss is not a person -- report level -1 so nobody mistakes "raid"
    # for a real trainer who parked a Mewtwo in every gym.
    def_lvl = -1 if is_raid else lvl
    join = (pb.Writer()
            .uint(1, BA_PLAYER_JOIN)
            .int_(2, now_ms)
            .int_(3, 0)
            .uint(8, atk["uid"])
            .message(9, me)                        # player_joined
            .to_bytes())
    log = (pb.Writer()
           .uint(1, BS_ACTIVE)
           .uint(2, btype)                         # <- was missing entirely
           .int_(3, now_ms)
           .message(4, join)
           .int_(5, now_ms).int_(6, now_ms + 180000)
           .to_bytes())
    return (pb.Writer()
            .uint(1, 1)                                        # SUCCESS
            .int_(2, now_ms)
            .int_(3, now_ms + 180000)
            .string(4, bid)
            .message(5, _battle_participant(defender["pokemon_id"], defender["uid"],
                                            defender["cp"], dhp,
                                            defender.get("trainer", "Rival"), def_lvl))
            .message(6, log)
            .to_bytes())


def _raid_drop(b, now_ms):
    """Put the defeated raid boss on the map at the trainer's feet, catchable."""
    import world
    import rpc as _rpc
    lat, lng = _rpc._last_loc[0], _rpc._last_loc[1]
    if not (abs(lat) > 1e-6 or abs(lng) > 1e-6):
        return None
    # a couple of metres away so it isn't inside the avatar
    lat += 0.00002
    eid = (now_ms ^ (b["def_uid"] if "def_uid" in b else b["defender"])
           ^ 0x5A1DD40D) & ((1 << 62) - 1)
    sid = _hex_id((eid, "raid"), 11)
    expires = now_ms + 10 * 60 * 1000               # ten minutes to catch it
    world.remember_spawn(eid, b["def_pid"], lat, lng, b["def_cp"], sid, expires)
    world.add_bonus_spawn(world.current().username, eid, b["def_pid"],
                          b["def_cp"], lat, lng, expires)
    return eid


def parse_attack_gym(msg):
    """AttackGymMessage { gym_id=1, battle_id=2, attack_actions=3 (repeated),
    last_retrieved_actions=4, player_latitude=5, player_longitude=6 }."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    bid = pb.get(f, 2, pb.WT_LEN)
    actions = []
    for raw in pb.get_all(f, 3):
        if isinstance(raw, bytes):
            a = pb.decode(raw)
            actions.append({"type": pb.get(a, 1, pb.WT_VARINT) or 0,
                            "start": pb.get(a, 2, pb.WT_VARINT) or 0,
                            "duration": pb.get(a, 3, pb.WT_VARINT) or 0})
    last = 0
    raw_last = pb.get(f, 4, pb.WT_LEN)
    if isinstance(raw_last, bytes):
        la = pb.decode(raw_last)
        last = pb.get(la, 2, pb.WT_VARINT) or 0
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            bid.decode("utf-8", "replace") if isinstance(bid, bytes) else "",
            actions, last)


def _action(kind, start_ms, duration, attacker_idx, target_idx,
            active_uid, target_uid, energy=0, dw_start=None, dw_end=None) -> bytes:
    # attacker_idx/target_idx index the battle's ATTACKING PLAYERS
    # (BattleResultsProto.Attackers is a repeated list, one entry per player in a
    # multi-attacker gym fight) -- they are NOT "me vs them". A solo battle has
    # exactly one entry, so anything other than 0 is out of range and the client
    # drops the action silently. WHO is acting comes from active_pokemon_id /
    # target_pokemon_id, which is how the defender is identified.
    """One BattleAction the client will replay.
    { Type=1, action_start_ms=2, duration_ms=3, energy_delta=5, attacker_index=6,
      target_index=7, active_pokemon_id=8, damage_windows_start=11,
      damage_windows_end=12, target_pokemon_id=14 }"""
    return (pb.Writer()
            .uint(1, kind)
            .int_(2, start_ms)
            .int_(3, duration)
            .int_(5, energy)
            .int_(6, attacker_idx)
            .int_(7, target_idx)
            .fixed64(8, active_uid)
            .int_(11, start_ms + (max(0, duration // 3) if dw_start is None
                                  else int(dw_start)))
            .int_(12, start_ms + (max(1, duration) if dw_end is None
                                  else int(dw_end)))
            .fixed64(14, target_uid)
            .to_bytes())


def build_attack_gym_response(gym_id, battle_id, actions, now_ms, last_seen=0) -> bytes:
    """AttackGymResponse { result=1, battle_log=2, battle_id=3,
    active_defender=4, active_attacker=5 }.

    This is a SYNC protocol, not a one-way report. The client tells us the moves it
    made and then waits for the server to hand back the authoritative list of
    actions -- its own, echoed, plus the defender hitting back -- which it replays
    as animation. Returning only a state (and no actions) is why it would take two
    taps and then sit there sending empty heartbeats."""
    import world
    b = world.BATTLES.get(battle_id)
    if not b:
        # The client keeps polling for a moment after a battle ends. Answering
        # without a battle_id made it log "AttackGymOutProto for mismatched
        # battleId"; echo the id back with a terminal log instead.
        done = (pb.Writer().uint(1, BS_VICTORY).uint(2, BT_NORMAL)
                .int_(3, now_ms).to_bytes())
        return (pb.Writer().uint(1, 1).message(2, done)
                .string(3, battle_id).to_bytes())

    if b.get("finished"):
        # The client polls a few more times before it tears the battle screen
        # down. Falling through re-ran the win logic on every one of those polls,
        # re-awarding the XP and re-emitting VICTORY -- report the settled state
        # and touch nothing.
        done = (pb.Writer().uint(1, b.get("end_state", BS_VICTORY))
                .uint(2, b.get("type", BT_NORMAL))
                .int_(3, now_ms)
                .int_(5, b["start"]).int_(6, b["start"] + 180000).to_bytes())
        return (pb.Writer().uint(1, 1).message(2, done)
                .string(3, battle_id)
                .message(4, _battle_pokemon_info(b["def_pid"], b["defender"],
                                                 b["def_cp"], max(0, b["def_hp"]),
                                                 hp_max=b.get("def_max")))
                .message(5, _battle_pokemon_info(b["atk_pid"], b["attacker"],
                                                 b["atk_cp"], max(0, b["atk_hp"]),
                                                 energy=b.get("energy", 0),
                                                 hp_max=b.get("atk_max")))
                .to_bytes())

    # Fleeing: swiping out of a battle makes the client send a PLAYER_QUIT action.
    # It is not a loss -- no prestige swings either way, and your attacker does NOT
    # faint (it was never deployed, so its stored HP is untouched). Just settle the
    # battle as TIMED_OUT and echo a QUIT so the client tears the screen down
    # cleanly instead of polling a battle we've forgotten.
    if any(a["type"] == BA_QUIT for a in actions):
        b["finished"] = now_ms
        b["end_state"] = BS_TIMED_OUT
        for old, ob in list(world.BATTLES.items()):
            if ob.get("finished") and now_ms - ob["finished"] > 30000:
                world.BATTLES.pop(old, None)
        quit_act = _action(BA_QUIT, now_ms, 0, 0, 0, b["attacker"], b["defender"])
        lw = (pb.Writer().uint(1, BS_TIMED_OUT)
              .uint(2, b.get("type", BT_NORMAL))
              .int_(3, now_ms).int_(5, b["start"]).int_(6, b["start"] + 180000)
              .message(4, quit_act))
        return (pb.Writer()
                .uint(1, 1)                                    # SUCCESS
                .message(2, lw.to_bytes())
                .string(3, battle_id)
                .message(4, _battle_pokemon_info(b["def_pid"], b["defender"],
                                                 b["def_cp"], max(0, b["def_hp"]),
                                                 hp_max=b.get("def_max")))
                .message(5, _battle_pokemon_info(b["atk_pid"], b["attacker"],
                                                 b["atk_cp"], max(0, b["atk_hp"]),
                                                 energy=b.get("energy", 0),
                                                 hp_max=b.get("atk_max")))
                .to_bytes())

    dmg_atk = _cfg.get("battles", "attack_damage", cast=int)
    dmg_special = _cfg.get("battles", "special_damage", cast=int)
    dmg_back = _cfg.get("battles", "defender_damage", cast=int)

    log_actions = []
    # The client SCHEDULES every action we return at its ActionStartMs, on its own
    # battle clock. The old code stacked each action onto a server cursor that ran
    # ahead of real time (it added every duration, and taps arrive faster than
    # that), so the actions were always dated in the future: the damage applied --
    # HP is read straight off active_defender -- but the animation never played,
    # and occasionally a whole backlog resolved at once. Echo the client's own
    # timestamps verbatim and hang the counter-attack off the end of each.
    # Which moves the two sides are actually using. The client resolves an action
    # to an animation via the performer's moveset, so every action we emit has to
    # carry that move's real duration and damage window.
    atk_quick, atk_charged = moves_for(b["atk_pid"], b["attacker"])
    def_quick, _dc = moves_for(b["def_pid"], b["defender"])

    # Real matchup: each hit is scaled by the MOVE's own type -- its effectiveness
    # against the target plus STAB when it matches the user's type -- so who wins
    # depends on the Pokemon (and moves) you brought, not a flat number.
    atk_types = pokemon_types(b["atk_pid"])
    def_types = pokemon_types(b["def_pid"])

    def _hit_mult(move_id, own_types, tgt_types):
        mt = _gd.MOVE_TYPES.get(move_id) if _gd else None
        if not mt:                                    # unknown move -> species approx
            return type_multiplier(own_types, tgt_types)
        stab = 1.25 if mt in (own_types or ()) else 1.0
        return _effectiveness(mt, tgt_types) * stab

    eff_quick = _hit_mult(atk_quick, atk_types, def_types)
    eff_special = _hit_mult(atk_charged, atk_types, def_types)
    eff_back = _hit_mult(def_quick, def_types, atk_types)
    _cm = _gd.MOVES.get(atk_charged) if _gd else None
    pow_factor = max(0.6, min(1.8, _cm[4] / 55.0)) if _cm else 1.0
    # Prefer the REAL damage formula (keeps the HP bars honest -- see
    # _battle_damage); the flat-config numbers scaled by effectiveness stay as a
    # fallback for when the game master lacks the move/species.
    _rq = _battle_damage(b["atk_pid"], b["attacker"], b["atk_cp"],
                         b["def_pid"], b["defender"], b["def_cp"], atk_quick,
                         atk_types, def_types)
    _rs = _battle_damage(b["atk_pid"], b["attacker"], b["atk_cp"],
                         b["def_pid"], b["defender"], b["def_cp"], atk_charged,
                         atk_types, def_types)
    _rb = _battle_damage(b["def_pid"], b["defender"], b["def_cp"],
                         b["atk_pid"], b["attacker"], b["atk_cp"], def_quick,
                         def_types, atk_types)
    hit_quick = _rq if _rq is not None else max(1, round(dmg_atk * eff_quick))
    hit_special = _rs if _rs is not None else max(1, round(dmg_special * eff_special * pow_factor))
    hit_back = _rb if _rb is not None else max(1, round(dmg_back * eff_back))

    cursor = max(now_ms, int(last_seen) + 1, int(b.get("last_emit", 0)) + 1)
    tail = None          # end of the last action we echoed, on the CLIENT's clock
    for a in actions:
        kind = a["type"]
        start = int(a.get("start") or 0) or cursor
        if kind == BA_ATTACK:
            move = atk_quick
            b["def_hp"] -= hit_quick
        elif kind == BA_SPECIAL:
            move = atk_charged
            b["def_hp"] -= hit_special
        elif kind == BA_DODGE:
            move = None                             # dodged: no counter this beat
        else:
            continue
        if move is None:
            dur = int(a["duration"] or 700)
            log_actions.append(_action(kind, start, dur, 0, 0,
                                       b["attacker"], b["defender"]))
        else:
            dur, dws, dwe, energy = move_timing(move, int(a["duration"] or 700))
            # Charged moves carry a negative energy_delta, so this drains on its
            # own -- no need to special-case the special.
            b["energy"] = max(0, min(100, b.get("energy", 0) + energy))
            log_actions.append(_action(kind, start, dur, 0, 0,
                                       b["attacker"], b["defender"],
                                       energy=energy, dw_start=dws, dw_end=dwe))
        end = start + dur
        if kind != BA_DODGE and b["def_hp"] > 0:
            # ...and the defender answers, which is what makes it feel like a fight
            ddur, ddws, ddwe, denergy = move_timing(def_quick)
            b["atk_hp"] -= hit_back
            # NOTE: measured 2026-08-04 -- this client does NOT replay server-sent
            # battle actions (a probe action attributed to the player animated 0 of
            # 4 times, and "Action start:" never appears in the client log). Gym
            # battles are simulated client-side; the log we send carries the
            # authoritative outcome, not the choreography. We still emit the
            # defender's counter so the log is truthful and the HP we report is
            # explained, but the animation for it comes from the client or not at all.
            log_actions.append(_action(BA_ATTACK, end, ddur, 0, 0,
                                       b["defender"], b["attacker"],
                                       energy=denergy, dw_start=ddws, dw_end=ddwe))
            end += ddur
        tail = end if tail is None else max(tail, end)
    # Faints and the victory banner have to be dated on whatever clock the echoed
    # actions used, not on ours -- if the client turns out to send battle-relative
    # times, a wall-clock faint would land ~1.7e12 ms away and never play.
    t = tail if tail is not None else cursor

    state = BS_ACTIVE
    if b["def_hp"] <= 0:
        log_actions.append(_action(BA_FAINT, t, 0, 0, 0,
                                   b["defender"], b["defender"]))
        # Tally prestige for beating THIS defender (raids have no gym to move).
        if not b.get("raid"):
            dp = world.prestige_for_defeat(b["atk_cp"], b["def_cp"])
            b["prestige_delta"] = b.get("prestige_delta", 0) + (
                dp if b.get("friendly") else -dp)
        b.setdefault("beaten", []).append(b["defender"])
        # Advance to the next un-beaten defender from the run's snapshot. The gym
        # roster is left untouched until the run ends, so prestige is applied once.
        # In raid mode gym_members() always reports the boss, so a raid is one
        # boss, then over.
        nxt = None
        if not b.get("raid"):
            nxt_uid = next((u for u in b.get("lineup", [])
                            if u not in b["beaten"]), None)
            if nxt_uid is not None:
                nxt = next((m for m in world.gym_members(gym_id)
                            if m["uid"] == nxt_uid), None)
        if nxt:
            b.update(defender=nxt["uid"], def_pid=nxt["pokemon_id"],
                     def_cp=nxt["cp"],
                     def_hp=_hp_for(nxt["cp"], nxt["pokemon_id"], nxt["uid"]),
                     def_max=_hp_for(nxt["cp"], nxt["pokemon_id"], nxt["uid"]))
        else:
            state = BS_VICTORY
            if b.get("raid"):
                # Beating the boss doesn't take the gym -- it drops the Pokemon at
                # your feet so you can actually catch the thing you just fought.
                _raid_drop(b, now_ms)
            else:
                # Whole lineup down: bank the run's prestige. Training raises the
                # gym; attacking drains it, and at 0 add_prestige() sends everyone
                # home so the winner can claim it with a fresh deploy.
                newp, lvl, ejected = world.add_prestige(
                    gym_id, b.get("prestige_delta", 0))
                b["gym_result"] = (newp, lvl, len(ejected))
            world.add_xp(_cfg.get("battles", "win_xp", cast=int))
            # Ace Trainer (training your own team's gym) vs Battle Girl (taking
            # someone else's) -- scored from the REAL relationship, not the type we
            # reported to the client.
            if b.get("friendly"):
                world.bump("battle_training_won")
                world.bump("battle_training_total")
            else:
                world.bump("battle_attack_won")
                world.bump("battle_attack_total")
            log_actions.append(_action(BA_VICTORY, t, 0, 0, 0,
                                       b["attacker"], b["defender"]))
    elif b["atk_hp"] <= 0:
        state = BS_DEFEATED
        # A lost run still counts the prestige for defenders you DID topple first,
        # so a strong gym can be worn down over several attacks.
        if not b.get("raid") and b.get("prestige_delta"):
            newp, lvl, ejected = world.add_prestige(gym_id, b["prestige_delta"])
            b["gym_result"] = (newp, lvl, len(ejected))
        if b.get("friendly"):
            world.bump("battle_training_total")
        else:
            world.bump("battle_attack_total")
        world.update_caught(b["attacker"], stamina=0)           # your Pokemon fainted
        log_actions.append(_action(BA_FAINT, t, 0, 0, 0,
                                   b["attacker"], b["attacker"]))
        log_actions.append(_action(BA_DEFEAT, t, 0, 0, 0,
                                   b["defender"], b["attacker"]))

    b["last_emit"] = t
    if state != BS_ACTIVE:
        b["finished"] = now_ms          # keep it briefly so late taps still match
        b["end_state"] = state
        for old, ob in list(world.BATTLES.items()):
            if ob.get("finished") and now_ms - ob["finished"] > 30000:
                world.BATTLES.pop(old, None)

    lw = (pb.Writer().uint(1, state)
          .uint(2, b.get("type", BT_NORMAL))
          .int_(3, now_ms).int_(5, b["start"]).int_(6, b["start"] + 180000))
    for a in log_actions:
        lw.message(4, a)
    return (pb.Writer()
            .uint(1, 1)                                        # SUCCESS
            .message(2, lw.to_bytes())
            .string(3, battle_id)
            .message(4, _battle_pokemon_info(b["def_pid"], b["defender"],
                                             b["def_cp"], max(0, b["def_hp"]),
                                             hp_max=b.get("def_max")))
            .message(5, _battle_pokemon_info(b["atk_pid"], b["attacker"],
                                             b["atk_cp"], max(0, b["atk_hp"]),
                                             energy=b.get("energy", 0),
                                             hp_max=b.get("atk_max")))
            .to_bytes())


def build_collect_daily_defender_bonus_response() -> bytes:
    """CollectDailyDefenderBonusResponse { result=1, currency_type=2 (repeated
    string), currency_awarded=3 (repeated int32), defenders_count=4 }.
    Result: 1=SUCCESS 2=FAILURE 3=TOO_SOON 4=NO_DEFENDERS.

    This is the shield button in the Shop. It pays coins + stardust for every gym
    you are currently defending, once a day. The two currency arrays are parallel:
    currency_type[i] names the currency, currency_awarded[i] is the amount."""
    import world
    result, coins, dust, gyms = world.collect_defender_bonus()
    w = pb.Writer().uint(1, result)
    if result == 1:                                   # SUCCESS -> report the payout
        w.string(2, "POKECOIN").string(2, "STARDUST")
        w.int_(3, coins).int_(3, dust)
    w.int_(4, gyms)
    return w.to_bytes()


# --------------------------------------------------------------- GYMS / ITEMS
def build_gym_membership(m) -> bytes:
    """GymMembership { pokemon_data=1, trainer_public_profile=2 }.
    PlayerPublicProfile { name=1, level=2, avatar=3 }. We used to send only the
    Pokemon; a membership with no trainer attached is a likely null/index crash in
    the gym screen, so always include the owner."""
    import world
    lvl, _ = world.stats()
    profile = (pb.Writer()
               .string(1, m.get("trainer") or "Trainer")
               .int_(2, lvl)
               .message(3, build_player_avatar())
               .to_bytes())
    return (pb.Writer()
            .message(1, build_pokemon_data(m["pokemon_id"], m["uid"], m["cp"]))
            .message(2, profile)
            .to_bytes())


def parse_gym_details(msg):
    """GetGymDetailsMessage { gym_id=1, player_latitude=2, player_longitude=3,
    gym_latitude=4, gym_longitude=5 }.

    NOTE this differs from FortDetailsMessage, where 2/3 ARE the fort's position.
    Reusing the fort parser here put the Gym's FortData at the PLAYER's coordinates,
    so the gym the client got back wasn't where the map said it was -- and it
    refused to open."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            _f64_to_double(pb.get(f, 4, pb.WT_64)),      # gym latitude
            _f64_to_double(pb.get(f, 5, pb.WT_64)))      # gym longitude


def build_gym_details_response(fort_id, lat, lng, now_ms) -> bytes:
    """GetGymDetailsResponse { gym_state=1, name=2, urls=3, result=4, description=5 }
    Result: 1=SUCCESS, 2=ERROR_NOT_IN_RANGE.
    GymState { fort_data=1, memberships=2 }; GymMembership { pokemon_data=1,
    trainer_public_profile=2 }. Without this the client can't open a Gym at all."""
    import world
    name = _PLACED_NAMES.get(fort_id) or GYM_NAMES[abs(hash(fort_id)) % len(GYM_NAMES)]
    fort = build_fort(fort_id, lat, lng, now_ms, is_gym=True)
    gs = pb.Writer().message(1, fort)
    for m in world.gym_members(fort_id):
        gs.message(2, build_gym_membership(m))
    w = (pb.Writer()
         .message(1, gs.to_bytes())
         .string(2, name))
    w.string(3, _fort_image_url(fort_id))                 # urls = 3, never empty
    return (w
            .uint(4, 1)                                   # SUCCESS
            .string(5, "A gym in your neighbourhood.")
            .to_bytes())


def parse_deploy(msg):
    """FortDeployPokemonMessage { fort_id=1, pokemon_id=2 fixed64, lat=3, lng=4 }."""
    f = pb.decode(msg)
    fid = pb.get(f, 1, pb.WT_LEN)
    return (fid.decode("utf-8", "replace") if isinstance(fid, bytes) else "",
            pb.get(f, 2, pb.WT_64) or 0)


def build_fort_deploy_response(fort_id, uid, lat, lng, now_ms) -> bytes:
    """FortDeployPokemonResponse { result=1, fort_details=2, pokemon_data=3, gym_state=4 }
    Result: 1=SUCCESS, 2=ALREADY_HAS_POKEMON, 4=FORT_IS_FULL, 5=NOT_IN_RANGE,
    6=PLAYER_HAS_NO_TEAM."""
    import world
    ok, why = world.deploy(fort_id, uid)
    if not ok:
        code = 2 if why == "already deployed" else (4 if why == "gym full" else 5)
        return pb.Writer().uint(1, code).to_bytes()
    c = world.get_caught(uid) or {"pokemon_id": 1, "cp": 100}
    world.bump("pokemon_deployed")
    gs = pb.Writer().message(1, build_fort(fort_id, lat, lng, now_ms, is_gym=True))
    for m in world.gym_members(fort_id):
        gs.message(2, build_gym_membership(m))
    return (pb.Writer()
            .uint(1, 1)                                   # SUCCESS
            .message(3, build_pokemon_data(c["pokemon_id"], uid, c["cp"]))
            .message(4, gs.to_bytes())
            .to_bytes())


def parse_recycle(msg):
    """RecycleInventoryItemMessage { item_id=1, count=2 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_VARINT) or 0, pb.get(f, 2, pb.WT_VARINT) or 0


def build_recycle_response(item_id, count) -> bytes:
    """RecycleInventoryItemResponse { result=1, new_count=2 }.
    Result: 1=SUCCESS, 2=ERROR_NOT_ENOUGH_COPIES. Lets you drop items from the bag."""
    import world
    if not world.take_item(item_id, count):
        return pb.Writer().uint(1, 2).to_bytes()
    remaining = dict(world.bag_items()).get(item_id, 0)
    return pb.Writer().uint(1, 1).int_(2, remaining).to_bytes()


def parse_level_up_rewards(msg):
    """LevelUpRewardsMessage { level = 1 } -- the level being claimed."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


def _level_rewards(level):
    """(items_awarded, items_unlocked) for reaching `level`. Rewards GROW with level
    and new item types UNLOCK at the real 2016 milestones (Razz Berries at 8, Great
    Balls at 12, Ultra Balls at 20), plus Incense/Lucky Egg every 5 levels and a
    Lure + Incubator at each 10 -- instead of the old flat 10 balls / 5 potions."""
    aw, unlocked = [], []
    aw.append((ITEM_POKE_BALL, 10 + min(level, 30)))              # 11 .. 40
    if level >= 5:
        aw.append((ITEM_SUPER_POTION if level >= 10 else ITEM_POTION, 10))
        aw.append((ITEM_REVIVE, 5 + (level // 10) * 5))
    if level >= 8:
        aw.append((ITEM_RAZZ_BERRY, 10))
        if level == 8:
            unlocked.append(ITEM_RAZZ_BERRY)
    if level >= 12:
        aw.append((ITEM_GREAT_BALL, 10 + (level - 12) // 2))
        if level == 12:
            unlocked.append(ITEM_GREAT_BALL)
    if level >= 20:
        aw.append((ITEM_ULTRA_BALL, 10 + (level - 20) // 2))
        if level == 20:
            unlocked.append(ITEM_ULTRA_BALL)
    if level % 5 == 0:                                            # milestone bonus
        aw += [(ITEM_INCENSE, 1), (ITEM_LUCKY_EGG, 1)]
    if level % 10 == 0:
        aw += [(ITEM_LURE, 1), (ITEM_INCUBATOR, 1)]
    return aw, unlocked


def build_level_up_rewards_response(level) -> bytes:
    """LevelUpRewardsResponse { result=1, items_awarded=2 (repeated ItemAward),
    items_unlocked=4 (repeated ItemId) }. Result: 1=SUCCESS, 2=AWARDED_ALREADY.

    The client asks on every boot AND when it levels up, so a level is paid out
    exactly ONCE (claim_level) and every later claim gets AWARDED_ALREADY -- without
    that it replays the level-up screen and re-hands the items on every launch."""
    import world
    if level <= 0 or not world.claim_level(level):        # atomic check+claim
        return pb.Writer().uint(1, 2).to_bytes()          # AWARDED_ALREADY
    awards, unlocked = _level_rewards(level)
    w = pb.Writer().uint(1, 1)
    for iid, cnt in awards:
        w.message(2, build_item_award(iid, cnt))
        world.add_item(iid, cnt)
    for iid in unlocked:
        w.uint(4, iid)                                    # items_unlocked (ItemId)
    return w.to_bytes()


def build_fort_search_response(fort_id, now_ms) -> bytes:
    # FortSearchResponse { result=1 (SUCCESS=1), items_awarded=2, experience_awarded=5,
    #   cooldown_complete_timestamp_ms=6 }. ItemAward { item_id=1, item_count=2 }.
    import world
    rnd = _random.Random(hash(fort_id) ^ (now_ms // 300000))   # re-rolls per 5-min spin
    _lo = _cfg.get("pokestops", "min_items_per_spin", cast=int)
    _hi = max(_lo, _cfg.get("pokestops", "max_items_per_spin", cast=int))
    # A spin ALWAYS gives Poke Balls, a Potion and a Revive; Great/Ultra Balls and
    # berries turn up now and then. Poke Balls are topped up at the end so the haul
    # never comes to fewer than min_items_per_spin items in total.
    awards = [(ITEM_POTION, rnd.randint(1, 2)), (ITEM_REVIVE, 1)]
    if rnd.random() < _cfg.get("pokestops", "great_ball_chance", cast=float):
        awards.append((ITEM_GREAT_BALL, rnd.randint(1, 2)))
    if rnd.random() < _cfg.get("pokestops", "ultra_ball_chance", cast=float):
        awards.append((ITEM_ULTRA_BALL, 1))
    if rnd.random() < _cfg.get("pokestops", "razz_berry_chance", cast=float):
        awards.append((ITEM_RAZZ_BERRY, rnd.randint(1, 2)))
    other = sum(c for _i, c in awards)
    awards.insert(0, (ITEM_POKE_BALL, max(rnd.randint(1, 3), _lo - other)))
    # ...and trim back to the maximum, taking from the extras first and never
    # dropping any award below one, so the guaranteed three always survive.
    total = sum(c for _i, c in awards)
    for i in range(len(awards) - 1, -1, -1):
        if total <= _hi:
            break
        iid, cnt = awards[i]
        take = min(cnt - 1, total - _hi)
        if take > 0:
            awards[i] = (iid, cnt - take)
            total -= take
    room = world.room_in_bag()
    if room <= 0:
        # FortSearchResult 4 = INVENTORY_FULL: the client says "your bag is full".
        return pb.Writer().uint(1, 4).to_bytes()
    if sum(c for _i, c in awards) > room:                       # partial haul
        trimmed, left = [], room
        for iid, cnt in awards:
            if left <= 0:
                break
            take = min(cnt, left)
            trimmed.append((iid, take)); left -= take
        awards = trimmed
    w = pb.Writer().uint(1, 1)                                  # result = SUCCESS
    if rnd.random() < _cfg.get("eggs", "drop_chance", cast=float):
        # 2 km eggs are common, 10 km rare -- same shape as the real drop table.
        tier = rnd.choices(EGG_TIERS, weights=(60, 30, 10))[0]
        # No item award for the egg: item 901 is an INCUBATOR, not an egg, and
        # reporting it made the spin look like it handed out an incubator. The egg
        # itself arrives with the next inventory delta.
        world.give_egg(tier)
    world.bump("poke_stop_visits")
    world.add_xp(_cfg.get("pokestops", "xp_per_spin", cast=int))
    for iid, cnt in awards:
        w.message(2, build_item_award(iid, cnt))
        # actually PUT them in the bag -- otherwise the spin animation shows a
        # Poke Ball but GET_INVENTORY never reports it and it's nowhere to be found
        world.add_item(iid, cnt)
    _cool = _cfg.get("pokestops", "cooldown_minutes", cast=float)
    return (w.int_(5, _cfg.get("pokestops", "xp_per_spin", cast=int))   # experience_awarded
             .int_(6, now_ms + int(_cool * 60_000))            # cooldown (goes purple)
             .to_bytes())


def parse_fort_request(msg):
    """fort_id + lat/lng from a FortDetails/FortSearch message."""
    f = pb.decode(msg)
    fid = pb.get(f, 1, pb.WT_LEN)
    fid = fid.decode("utf-8", "replace") if isinstance(fid, bytes) else ""
    return fid, _f64_to_double(pb.get(f, 2, pb.WT_64)), _f64_to_double(pb.get(f, 3, pb.WT_64))


def build_map_cell(cell_id, now_ms, catchable=(), forts=(), wild=(),
                   spawn_points=(), nearby=()) -> bytes:
    # MapCell { s2_cell_id=1, current_timestamp_ms=2, forts=3, spawn_points=4,
    #   wild_pokemons=5, catchable_pokemons=10, nearby_pokemons=11 }
    # (field numbers VERIFIED against POGOProtos MapCell.proto)
    #
    # NOTE the x1000 on the timestamp. Despite the "_ms" name, the working
    # maierfelix/POGOServer sends `new Date().getTime() * 1e3` here (microseconds),
    # while leaving fort/pokemon last_modified_timestamp_ms in plain ms. Sending
    # plain ms makes the cell look ancient to the client, which then discards the
    # whole cell -- no forts, no Pokemon, nothing.
    w = pb.Writer().uint(1, cell_id).int_(2, now_ms * 1000)
    for f in forts:
        w.message(3, f)
    for sp in spawn_points:
        w.message(4, sp)
    for wp in wild:
        w.message(5, wp)
    for c in catchable:
        w.message(10, c)
    for nb in nearby:
        w.message(11, nb)
    return w.to_bytes()


def _cell_center(cid):
    try:
        c = s2sphere.CellId(cid)
        if c.level() == 15:
            ll = s2sphere.LatLng.from_point(s2sphere.Cell(c).get_center())
            return ll.lat().degrees, ll.lng().degrees
    except Exception:
        pass
    return None


_FORCE_POKEMON = int(os.environ.get("FORCE_POKEMON", "0"))   # spawn only this id (debug)
_PLACED_NAMES = {}      # fort_id -> user-given name (World Manager placements)
_PLACED_IMAGES = {}     # fort_id -> user-given photo (url or photos/ filename)

# A fort MUST come back with at least one image url: the gym screen indexes
# urls[0] and threw ArgumentOutOfRangeException ("Promise<T>.Then<T> threw an
# exception") when we sent an empty list for a photo-less gym. This little PNG is
# served at /fortimg/_default.png whenever the user hasn't set their own picture.
DEFAULT_FORT_IMAGE = "_default.png"
_DEFAULT_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAIAAADTED8xAAAEZklEQVR42u3dsVUrQQyFYS3HVbkSAgpwGS7CJRBQFxEhJRCQOgCMvRrd78/fg9HcX5pdfMbb8XQpIJUnJQABAAIABAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAcJ2DEjyGt/PLb//J8/lV3e7NdjxdVGH3rLOCAEJPBgIIPRkIIPdMIIDcM4EAok8DAog+DQgg+jQggOjTgACiTwMCiD4NyofhpN/aTQDbbxSYANKvGiaAzTYKTADpVx8C2F1VcgQSfcchE0D61S1cAOlXvVwBpF8NcwWQfpXMFUD61TNXAOlX1VwBpF9tcwWQfhXOFUD61TlXAOlX7VwBpF/NHYGASAG0f5XPFUD61T9XAOm3C45AQKQA2r+9yBVA+u2IIxAQKYD2b19yBZB+u1O+J7hG37NA8nItyphk3Hi5SOCSTQCX6lz5f4yF9AmwRAIe0PzUwQSI3vLvH2QgZE2Azvu9Y7dTlvKHsORt9h1HEROgZ59rFT4lMgGit9YoGCtAw97WM20Nf6v+T+reAo1qtF4QTZsArfZylWOGhxPPAOmHbI8EBEjPEweWF8BZtnxG2gTQSg0BAsgQB8IE6DA3Z6SnwyranoJMAJgAmH54cBAiQHpiOLCSAF6AlpehJoBmaV0EAAigTVpdjgAeADwGmAAAAZwQrJEAAAGAu7C9f3yqAkwAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIABAAIAAAAEAAgAt2Y6nS7k/rLLuzFFhEwAgAAigBGn38rp7mABAYwHc3lru5TUBnBCsjgAAAbRJ60oTwGOABwATQLO0IgJIjLUQAIgToMORcUbj7LCKtg91JsBwBxx+CJCbIelfWwAvQ8sLUBNAK9X+CSBP0h8pQKvpuUqqWv2ezc+xBz3gD9lqu6ka/8AjUMO09cxZw9+q/2sMzwBD0qb315hrUdba4N2bnMqYALn50/hTJkD/zX5ww1ON8hYo8wWRrh86Adba+383IXntJsDCzwY3pkG/NwHmBOKHMiSs0QTwygjlNajPSJdPPhOAA9JPAIAAhoAdIQAH7AUBAAIYAnaBABxQfwJwQOUJABDAEFBzAnBAtQnAAXUmAAdUmAAcUFsCcEBVCcAB9SQAB1SSABxQQ38J5oDqxX8UggPqVmOuRSmXMoi+CWBfVYkAdld9HIEch0TfBLDfqmECGAWibwJIgLWbAEaB6BOABqJPABqIPgFoIPoE8J00IECSBqJPAF/QCwJkmCD3BIiTQegJECeD0BMgxQpZJwBQPgwHEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIACwG19/ntxysev+5gAAAABJRU5ErkJggg=="


# Drop your own image here to replace the built-in placeholder for every
# photo-less PokeStop/Gym: data/default_fort.png (PNG or JPG bytes). It is read
# fresh on each request, so a new file takes effect immediately -- no rebuild,
# no restart. Delete it to go back to the built-in default.
DEFAULT_FORT_FILE = datadir.path("default_fort.png")


def default_fort_png():
    import base64
    try:
        if os.path.isfile(DEFAULT_FORT_FILE):
            with open(DEFAULT_FORT_FILE, "rb") as fh:
                return fh.read()
    except OSError:
        pass
    return base64.b64decode(_DEFAULT_PNG_B64)


def _fort_image_url(fort_id):
    img = _PLACED_IMAGES.get(fort_id) or DEFAULT_FORT_IMAGE
    return (img if img.lower().startswith("http")
            else f"https://pgorelease.nianticlabs.com/fortimg/{img}")


def _event_cfg():
    """Live event settings (events.json), hot-reloaded. Falls back to defaults."""
    try:
        import events
        return events.get()
    except Exception:
        return {"species_mode": "all", "species_list": [25], "single_species": 25,
                "spawn_density": 6, "min_cp": 100, "max_cp": 1200}


# ------------------------------------------------- realistic spawn distribution
# A uniform randint(1,151) meant Mewtwo was as common as a Pidgey. These tiers
# reproduce the feel of a normal 2016 day: mostly city-trash Pokemon, occasional
# evolved ones, rare starters/pseudo-legendaries, and NO legendaries in the wild.
# (Legendary Hunt and the other presets still force them via species_mode.)
_LEGENDARY = {144, 145, 146, 150, 151}          # never spawn naturally
# The chase list: pseudo-legendaries and the genuine trophies. Kept scarce in
# EVERY biome (a biome shifts which commons dominate, it must not mint a Dratini).
_VERY_RARE = {83, 113, 115, 122, 128, 131, 132, 137,   # Farfetchd, Chansey,
              138, 139, 140, 141, 142, 143,            # Kangaskhan, MrMime, Tauros,
              147, 148, 149}                            # Ditto, Porygon, fossils,
                                                        # Aerodactyl, Snorlax, Lapras,
                                                        # Dratini line
_RARE = {1, 2, 3, 4, 5, 6, 7, 8, 9,             # starters + their lines
         63, 65, 68, 71, 76, 94, 97,
         123, 124, 125, 126, 127, 134, 135, 136}       # Scyther/Jynx/Electabuzz/
                                                        # Magmar/Pinsir, Eevee-evos
_UNCOMMON = {17, 20, 22, 24, 25, 26, 28, 30, 33, 36, 38, 40, 42, 44, 45, 47, 49,
             51, 53, 55, 57, 59, 61, 62, 64, 67, 70, 73, 75, 78, 80, 82, 85, 87,
             89, 91, 93, 99, 101, 103, 105, 106, 107, 108, 110, 112, 114, 117,
             119, 121, 130, 133}
# Biome boost ceilings per tier: a favoured biome can lift a species this many
# times its base rate at most, so trophies stay trophies even where their type
# is favoured (a very_rare is never boosted at all).
_BIOME_CAP = {"very_rare": 1, "rare": 2, "uncommon": 4, "common": 999}
_POOL = None
_POOL_KEY = None


def _tier_weights():
    """The rarity tier weights, tunable in settings.json (hot-reloaded)."""
    return {t: max(1, _cfg.get("spawns", f"weight_{t}", cast=int))
            for t in ("common", "uncommon", "rare", "very_rare")}


def _tier_of(pid):
    return ("very_rare" if pid in _VERY_RARE else
            "rare" if pid in _RARE else
            "uncommon" if pid in _UNCOMMON else "common")


def _spawn_pool():
    """Weighted list of species for a 'normal day'. Rebuilt when the rarity
    weights or allow_legendaries change (both hot-reloaded)."""
    global _POOL, _POOL_KEY
    allow_leg = _cfg.get("spawns", "allow_legendaries", cast=bool)
    w = _tier_weights()
    key = (allow_leg, tuple(sorted(w.items())))
    if _POOL is None or _POOL_KEY != key:
        _POOL_KEY = key
        pool = []
        for pid in range(1, 152):
            if pid in _LEGENDARY and not allow_leg:
                continue
            pool += [pid] * w[_tier_of(pid)]
        _POOL = pool
    return _POOL


# The base pool above, re-weighted for a biome: a species whose type the biome
# favours appears much more often, everything else keeps its normal low rate.
# Cached per (biome, allow_legendaries) since the tables never change at runtime.
_BIOME_POOLS = {}


def _biome(lat, lng):
    """The biome name at a location (see biomes.py)."""
    import biomes as _bio
    return _bio.biome_for(lat, lng, _cfg.get("spawns", "biome_size", cast=int))


def _biome_pool(biome, allow_leg):
    w = _tier_weights()
    key = (biome, allow_leg, tuple(sorted(w.items())))
    pool = _BIOME_POOLS.get(key)
    if pool is not None:
        return pool
    import biomes as _bio
    boosts = _bio.type_boosts(biome)
    pool = []
    for pid in range(1, 152):
        if pid in _LEGENDARY and not allow_leg:
            continue
        tier = _tier_of(pid)
        # strongest boost among this species' one-or-two types (1 = not favoured)
        mult = 1
        for t in pokemon_types(pid):
            m = boosts.get(t, 1)
            if m > mult:
                mult = m
        # A biome shifts WHICH commons/uncommons dominate -- it must NOT turn a
        # rare into a common. Cap the boost hard for the scarce tiers (a very_rare
        # gets none) so Dratini stays a trophy by the water even though Water is
        # favoured there.
        mult = min(mult, _BIOME_CAP[tier])
        pool += [pid] * (w[tier] * mult)
    _BIOME_POOLS[key] = pool or _spawn_pool()
    return _BIOME_POOLS[key]


def _pick_species(rnd, cfg=None, lat=None, lng=None):
    """Which Pokemon spawns, honouring the event's species mode. In the normal
    'all' mode the spawn is flavoured by the biome at (lat, lng) when we know it,
    so different areas favour different Pokemon the way 2016's biomes did. An
    event that forces a species/list overrides the biome (a Pikachu event is a
    Pikachu event everywhere)."""
    if _FORCE_POKEMON:
        return _FORCE_POKEMON
    c = cfg or _event_cfg()
    m = c.get("species_mode", "all")
    if m == "single":
        return int(c.get("single_species", 25))
    if m == "list":
        lst = c.get("species_list") or [25]
        return int(rnd.choice(lst))
    if lat is not None and lng is not None and _cfg.get("spawns", "biomes", cast=bool):
        try:
            import biomes as _bio
            allow_leg = _cfg.get("spawns", "allow_legendaries", cast=bool)
            now = int(time.time() * 1000)
            # NEST: some regions spawn mostly one species (rotates on a cycle).
            if _cfg.get("spawns", "nests", cast=bool):
                nest = _bio.nest_species(
                    lat, lng, now, _cfg.get("spawns", "biome_size", cast=int),
                    _cfg.get("spawns", "nest_rotation_days", cast=int))
                if nest and rnd.random() < _cfg.get("spawns", "nest_chance", cast=float):
                    return int(nest)
            pool = _biome_pool(_biome(lat, lng), allow_leg)
            pid = int(rnd.choice(pool))
            # DAY/NIGHT: shy away from wrong-time species so nocturnal Pokemon
            # (Zubat, ghosts, ...) really are a night thing and vice versa.
            if _cfg.get("spawns", "day_night", cast=bool):
                wrong = (_bio.DAY_SPECIES if _bio.is_night(now, lng)
                         else _bio.NIGHT_SPECIES)
                if pid in wrong and rnd.random() < 0.6:
                    pid = int(rnd.choice(pool))
            return pid
        except Exception:
            pass                       # biomes unavailable: fall back to the flat pool
    return int(rnd.choice(_spawn_pool()))


def _pick_cp(rnd, cfg=None, pid=None):
    c = cfg or _event_cfg()
    lo = int(c.get("min_cp", _cfg.get("spawns", "min_cp", cast=int)))
    hi = int(c.get("max_cp", _cfg.get("spawns", "max_cp", cast=int)))
    if lo > hi:
        lo, hi = hi, lo
    # A wild Pokemon can't be stronger than its species can actually reach -- so a
    # Caterpie tops out around 444 CP, not the flat map max. Events that hand out
    # deliberately overpowered Pokemon set allow_overcap to bypass this.
    if (pid and not c.get("allow_overcap")
            and _cfg.get("spawns", "cap_cp_to_species", cast=bool)):
        cap = int(_max_reachable_cp(pid))
        if cap > 0:
            hi = min(hi, cap)
            lo = min(lo, hi)
    return rnd.randint(lo, hi)
# Wild Pokemon rotate on a fixed clock: every SPAWN_WINDOW_MIN minutes the whole
# map re-rolls. Spawn ids/species are seeded from (cell, window), so a spawn lasts
# exactly one window and then a fresh set appears -- and a Pokemon you caught can
# be suppressed for the rest of its window instead of reappearing next refresh.
def _spawn_window_min():
    return _cfg.get("spawns", "refresh_minutes", env="SPAWN_WINDOW_MIN", cast=float)
def _near_player():
    return _cfg.get("spawns", "how_many_near_you", env="NEAR_PLAYER", cast=int)


def _config_generation():
    """Changes whenever events.json / settings.json / places.json is saved. Mixed
    into the spawn seed so editing a setting re-rolls the wild Pokemon IMMEDIATELY
    instead of waiting up to refresh_minutes for the next window."""
    gen = 0
    try:
        import events as _e, settings as _s, places as _p
        for f in (_e.EVENTS_FILE, _s.SETTINGS_FILE, _p.PLACES_FILE):
            try:
                gen ^= int(os.path.getmtime(f))
            except OSError:
                pass
    except Exception:
        pass
    return gen


def _window(now_ms):
    """(index of the current spawn window, ms at which it ends).

    The index also folds in a config generation, so a settings change re-rolls
    spawns straight away; the END time stays on the real clock so the client's
    despawn timers remain honest."""
    span = max(60_000, int(_spawn_window_min() * 60_000))
    idx = now_ms // span
    return (idx ^ (_config_generation() << 20)), (idx + 1) * span        # wild mons clustered on the trainer
                                                             # (real spawns are sparse; a huge
                                                             #  cluster looks bogus to the client)


_L17_CACHE = {}


def _l17_centres(cid15):
    """The 16 level-17 child centres of a level-15 cell, worked out once.

    Deriving these from s2sphere on every map refresh was one of the biggest
    remaining costs -- and the same handful of cells come round again and again
    as you walk, so caching them removes nearly all of it.
    """
    got = _L17_CACHE.get(cid15)
    if got is None:
        got = []
        try:
            c15 = s2sphere.CellId(cid15)
            if c15.level() == 15:
                for c16 in c15.children():
                    for c17 in c16.children():
                        ll = s2sphere.LatLng.from_point(
                            s2sphere.Cell(c17).get_center())
                        got.append((c17.id(), ll.lat().degrees, ll.lng().degrees))
        except Exception:
            got = []
        if len(_L17_CACHE) > 4000:          # bounded; walking can't grow it forever
            _L17_CACHE.clear()
        _L17_CACHE[cid15] = got
    return got


def build_get_map_objects_response(cell_ids, lat, lng) -> bytes:
    # GetMapObjectsResponse { map_cells=1, status=2 (1=SUCCESS), time_of_day=3 (1=DAY) }
    now = int(time.time() * 1000)
    # Everything in this batch belongs to the current spawn window and dies with it,
    # so the client's timers agree with when we actually re-roll.
    _win, _win_end = _window(now)
    expire = _win_end
    SPAWN_MS = max(60_000, _win_end - now)
    have_fix = abs(lat) > 1e-6 or abs(lng) > 1e-6

    # Answer with EXACTLY the cells the client asked for, in the SAME ORDER. The
    # client pairs cell_id[i] with since_timestamp_ms[i] in its request, so it treats
    # the response cell list positionally -- re-sorting them or appending extra cells
    # (which we used to do) desynchronises that mapping and the client silently drops
    # the whole batch. Only synthesise cells if it asked for none.
    cells = list(dict.fromkeys(cell_ids))          # requested cells (dedup, in order)
    if not cells and have_fix:
        pc = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(15)
        cells = [pc.id()]
        try:
            cells += [n.id() for n in pc.get_edge_neighbors()]
        except Exception:
            pass

    # Which of the REQUESTED cells holds the player (that's where the dense cluster
    # goes). Prefer the exact level-15 parent; fall back to the nearest requested cell
    # so the trainer always has Pokemon at their feet even if the client's cell list
    # lags behind the GPS.
    player_cell = None
    if have_fix and cells:
        pid_cell = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(15).id()
        if pid_cell in cells:
            player_cell = pid_cell
        else:
            def _cdist(cid):
                c = _cell_center(cid)
                return (c[0] - lat) ** 2 + (c[1] - lng) ** 2 if c else 9e9
            player_cell = min(cells, key=_cdist)

    # Per-request safety caps: the density settings are PER CELL and the client
    # asks for several cells at once, so a generous value multiplies quickly.
    # Without a ceiling one refresh can build a batch the client drops outright.
    MAX_FORTS = max(1, _cfg.get("pokestops", "max_per_request", cast=int))
    MAX_WILD = max(1, _cfg.get("spawns", "max_per_request", cast=int))
    _per_cell = max(0, _cfg.get("spawns", "per_l15_cell", cast=int))

    # live event settings drive species / CP / how many spawn around the trainer
    _ev = _event_cfg()
    _near_n = max(0, min(60, int(_ev.get("spawn_density", _near_player()))))

    # Hand-placed objects from the World Manager (places.json), bucketed by the
    # level-15 cell they fall in so they only ship with the cell that owns them.
    import places as _places
    _pl = _places.get()
    # OSM-sourced forts (real businesses/parks/etc., off-road) join the hand-placed
    # ones and render identically. When we have any, the procedural cell-centre forts
    # (which can land in the middle of a road) are turned OFF -- that's the point.
    # OSM forts come pre-bucketed by level-15 cell (pois.forts_by_cell, built once per
    # file change). We only pull the cells THIS request asks for, so a file with
    # millions of forts costs the same per request as one with a few hundred.
    _osm_by_cell = {}
    try:
        if _cfg.get("pokestops", "use_osm", cast=bool):
            import pois as _pois
            _osm_by_cell = _pois.forts_by_cell()
    except Exception:
        _osm_by_cell = {}
    _osm_any = bool(_osm_by_cell)
    _placed_forts, _placed_spawns = {}, {}
    # Hand-placed forts (few) are bucketed in full...
    for _f in _pl["forts"]:
        try:
            _c = s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(_f["lat"], _f["lng"])).parent(15).id()
        except Exception:
            continue
        _placed_forts.setdefault(_c, []).append(_f)
    # ...then the OSM index tops up only the requested cells.
    for _cid_osm in cells:
        _bucket = _osm_by_cell.get(_cid_osm)
        if _bucket:
            _placed_forts.setdefault(_cid_osm, []).extend(_bucket)
    for _s in _pl["spawns"]:
        try:
            _c = s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(_s["lat"], _s["lng"])).parent(15).id()
        except Exception:
            continue
        _placed_spawns.setdefault(_c, []).append(_s)
    # Real OSM forts win over procedural ones: no random road-centre stops when we
    # have actual places to put them.
    _proc_forts = _pl["procedural_forts"] and not _osm_any
    _proc_spawns = _pl["procedural_spawns"]

    # Lured stops, and where each fort sits, so the lure cluster lands on it. Built
    # only from the forts actually in play this request (hand-placed + requested cells).
    _lured = _world.lured_forts()
    _fort_pos = {}
    for _flist in _placed_forts.values():
        for _f in _flist:
            _gym = _f.get("kind") == "gym"
            _fort_pos[f"{_hex_id(_f['id'])}.{16 if _gym else 11}"] = (_f["lat"], _f["lng"])
    if _lured:
        for _cid2 in cells:
            for _kid, _kla, _kln in _l17_centres(_cid2):
                _fort_pos.setdefault(f"{_hex_id(_kid)}.11", (_kla, _kln))

    def _cell_of(la, ln):
        try:
            return s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(la, ln)).parent(15).id()
        except Exception:
            return None

    # Spread the wild-Pokemon budget by DISTANCE. Filling far-away cells first
    # and then hitting the cap left the player surrounded by nothing, and handing
    # the client 180+ Pokemon at once is what makes a 2016 phone fall over. The
    # cells you can actually walk to get the full density; the rest get a taste.
    # Hard radius: cells whose centre is further than spawns.radius_m get NO wild
    # Pokemon. The client asks for a 3x3-ish block of level-15 cells (~900m across)
    # and most of that you will never walk to, so filling it is pure payload -- which
    # is what breaks a map refresh over a VPN on cellular, where login and RPC are
    # fine but the big batch never lands. 0 disables the filter.
    #
    # The cell is still EMITTED, just empty: the client pairs cell_id[i] with
    # since_timestamp_ms[i] positionally, so dropping a cell from the response
    # desynchronises that mapping and it silently discards the whole batch.
    _radius_m = max(0.0, _cfg.get("spawns", "radius_m", cast=float))

    def _cell_dist_m(cid):
        c = _cell_center(cid)
        if not c:
            return 9e9
        dy = (c[0] - lat) * 111320.0
        dx = (c[1] - lng) * 111320.0 * max(0.2, _math.cos(_math.radians(lat)))
        return _math.hypot(dx, dy)

    _budget = {}
    if cells:
        def _cdist2(cid):
            c = _cell_center(cid)
            return ((c[0] - lat) ** 2 + (c[1] - lng) ** 2) if c else 9e9
        _ranked = sorted(cells, key=_cdist2)
        _left = MAX_WILD
        for _rank, _cid3 in enumerate(_ranked):
            if _rank == 0:
                _share = _per_cell                       # the cell you stand in
            elif _rank <= 4:
                _share = max(1, _per_cell // 2)          # the ring around you
            else:
                _share = max(1, _per_cell // 4)          # distant scenery
            # Out of range: keep the cell, drop its contents. Never the cell you
            # stand in -- a fix that lands just outside a boundary must not empty
            # the ground under your feet.
            if _radius_m and have_fix and _rank > 0 and _cell_dist_m(_cid3) > _radius_m:
                _share = 0
            _share = min(_share, max(0, _left))
            _budget[_cid3] = _share
            _left -= _share

    w = pb.Writer()
    spawned = forts_n = wild_n = 0
    for cid in cells:
        catch, forts, wild, spawns, nearby = [], [], [], [], []
        ctr = _cell_center(cid)
        # ~N wild Pokemon in the general area of each real stop in this cell, so the map
        # is alive wherever there are stops -- not only around the trainer. Runs BEFORE
        # the random field so stops get first claim on the per-refresh budget; the hard
        # MAX_WILD cap still applies (a dense city fills up across the nearest stops).
        _per_stop = max(0, _cfg.get("spawns", "per_stop", cast=int))
        if _proc_spawns and _per_stop:
            for _sf in _placed_forts.get(cid, []):
                if wild_n >= MAX_WILD:
                    break
                if _sf.get("kind") == "gym":
                    continue
                _sla, _sln = _sf["lat"], _sf["lng"]
                for k in range(_per_stop):
                    if wild_n >= MAX_WILD:
                        break
                    r = _random.Random((hash(_sf["id"]) ^ (_win * 0x9E3779B1)
                                        ^ (k * 0x2545F491) ^ 0x570F5) & 0x7FFFFFFF)
                    ang = 2 * _math.pi * k / _per_stop + r.uniform(-0.4, 0.4)
                    dist = 15.0 + r.random() * 45.0        # 15-60m: the stop's general area
                    dl = _sla + (dist * _math.cos(ang)) / 111320.0
                    dn = _sln + (dist * _math.sin(ang)) / (
                        111320.0 * max(0.2, _math.cos(_math.radians(_sla))))
                    eid = (hash(_sf["id"]) ^ (k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)
                           ^ 0x570F5) & ((1 << 62) - 1)
                    if _world.is_despawned(eid):
                        continue
                    pid = _pick_species(r, _ev, dl, dn)
                    cp = _pick_cp(r, _ev, pid)
                    sid = _hex_id((_sf["id"], "s", k), 11)
                    wild.append(build_wild_pokemon(eid, dl, dn, sid, pid, now, SPAWN_MS, cp=cp))
                    catch.append(build_map_pokemon(sid, eid, pid, dl, dn, expire))
                    _world.remember_spawn(eid, pid, dl, dn, cp, sid, expire)
                    spawns.append(build_spawn_point(dl, dn))
                    nearby.append(build_nearby_pokemon(pid, dist))
                    wild_n += 1
        if ctr and _proc_spawns and wild_n < MAX_WILD:
            # Wild Pokemon in EVERY level-17 child of this cell (16 of them), rather
            # than one at the level-15 centre. Seeded per (l17 cell, index, window)
            # so the map is stable for the whole window and re-rolls with it.
            _kids = _l17_centres(cid)
            for k in range(_budget.get(cid, 0)):
                if wild_n >= MAX_WILD or not _kids:
                    break
                # Spread them over the level-15 cell by walking its level-17
                # children in turn, then jittering inside whichever one we land on.
                _kid, _clat, _clng = _kids[k % len(_kids)]
                seed = (_kid ^ (_win * 0x9E3779B97F4A7C15)
                        ^ (k * 0x2545F4914F6CDD1D)) & ((1 << 63) - 1)
                rnd = _random.Random(seed)
                pid = _pick_species(rnd, _ev, _clat, _clng)
                eid = (seed ^ 0x5BD1E995ABCD) & ((1 << 63) - 1)
                sid = _hex_id((_kid, k), 11)
                _cp = _pick_cp(rnd, _ev, pid)
                # The spawn point's LOCATION is seeded WITHOUT the window, so the
                # spot stays put every window and only the species/CP rotate --
                # real 2016 spawn points you can learn, not a spot that hops each
                # refresh. (Scatter inside the ~75m level-17 cell so they don't sit
                # in a visible grid.)
                loc = _random.Random((_kid ^ (k * 0x2545F4914F6CDD1D))
                                     & ((1 << 63) - 1))
                jl = _clat + (loc.random() - 0.5) * 0.00060
                jn = _clng + (loc.random() - 0.5) * 0.00060
                # skip it if it was already caught during this window, otherwise
                # the next map refresh hands the same Pokemon straight back
                if _world.is_despawned(eid):
                    continue
                wild.append(build_wild_pokemon(eid, jl, jn, sid, pid, now,
                                               SPAWN_MS, cp=_cp))
                catch.append(build_map_pokemon(sid, eid, pid, jl, jn, expire))
                _world.remember_spawn(eid, pid, jl, jn, _cp, sid, expire)
                spawns.append(build_spawn_point(jl, jn))
                nearby.append(build_nearby_pokemon(pid, 120.0))
                wild_n += 1
        if cid == player_cell and _proc_spawns:
            # a cluster of wild Pokemon right around the trainer (spread within ~65m)
            # so there are always plenty in view no matter which way you look
            for k in range(_near_n):
                r = _random.Random(cid ^ (_win * 0x9E3779B97F4A7C15)
                                    ^ (k * 0x2545F4914F6CDD1D))
                pid2 = _pick_species(r, _ev, lat, lng)
                # Spread them around the trainer instead of stacking them on the
                # same spot: each one gets its own angular slice, at 25-65m. That
                # keeps them inside MapSettings.pokemon_visible_range (~70m) while
                # leaving real walking distance between them.
                ang = (2 * _math.pi * k / max(1, _near_n)) + r.uniform(-0.35, 0.35)
                _d0 = _cfg.get("spawns", "nearest_distance_m", cast=float)
                _d1 = _cfg.get("spawns", "farthest_distance_m", cast=float)
                dist = _d0 + r.random() * max(1.0, _d1 - _d0)     # metres
                dlat = lat + (dist * _math.cos(ang)) / 111320.0
                dlng = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat))))
                eid2 = (cid ^ (0x1234ABCD5678 + k * 0x9E3779B1)
                        ^ (_win * 0x85EBCA6B)) & ((1 << 63) - 1)
                sid2 = _hex_id((cid, k), 11)
                _cp2 = _pick_cp(r, _ev, pid2)
                if _world.is_despawned(eid2):   # already caught in this window
                    continue
                wild.append(build_wild_pokemon(eid2, dlat, dlng, sid2, pid2, now,
                                               SPAWN_MS, cp=_cp2))
                catch.append(build_map_pokemon(sid2, eid2, pid2, dlat, dlng, expire))
                _world.remember_spawn(eid2, pid2, dlat, dlng, _cp2, sid2, expire)
                spawns.append(build_spawn_point(dlat, dlng))
                nearby.append(build_nearby_pokemon(pid2, 10.0 + k * 5))
        if _proc_forts and forts_n < MAX_FORTS:
            forts = l17_forts(cid, now)[:max(0, MAX_FORTS - forts_n)]
            forts_n += len(forts)
        if (cid == player_cell and _proc_forts
                and _cfg.get("pokestops", "anchor_near_player", cast=bool)):
            # OFF by default. These were placed RELATIVE to the trainer so a
            # stationary player always had a spinnable stop within the ~40m radius --
            # but that means a fresh trio (2 stops + a gym) is dropped at your feet on
            # every move, so DRIVING spammed stops/gyms all down the road. With this
            # off, forts come only from the fixed geographic cell centres (l17_forts)
            # + hand-placed ones, which stay put as you pass them.
            near = [(0.00020, -0.00010, False),    # PokeStop ~24m NW
                    (-0.00012, 0.00016, False),    # PokeStop ~22m SE
                    (0.00025, 0.00028, True)]      # Gym ~40m NE
            for j, (dla, dln, is_gym) in enumerate(near):
                fid = f"{_hex_id((cid, 'near', j))}.{16 if is_gym else 11}"
                forts = list(forts) + [build_fort(fid, lat + dla, lng + dln,
                                                  now, is_gym=is_gym)]
            forts_n += len(near)
        # --- hand-placed objects from the World Manager -------------------
        for _f in _placed_forts.get(cid, []):
            _gym = _f.get("kind") == "gym"
            forts = list(forts) + [build_fort(
                f"{_hex_id(_f['id'])}.{16 if _gym else 11}",
                _f["lat"], _f["lng"], now, is_gym=_gym)]
            _fid = f"{_hex_id(_f['id'])}.{16 if _gym else 11}"
            _PLACED_NAMES[_fid] = _f.get("name", "")
            if _f.get("image"):
                _PLACED_IMAGES[_fid] = _f["image"]
            forts_n += 1
        for _s in _placed_spawns.get(cid, []):
            _pid = int(_s.get("pokemon_id", 0) or 0)
            if _pid == 0:                      # "random spawn point"
                _pid = _pick_species(_random.Random(now // 600000 ^ hash(_s["id"])),
                                     _ev, _s["lat"], _s["lng"])
            _eid = (hash(_s["id"]) ^ 0x50AC3D) & ((1 << 62) - 1)
            _sid = _hex_id(_s["id"], 11)
            _pcp = 200 + (_eid % 800)
            _pcap = int(_max_reachable_cp(_pid))
            if _pcap > 0:
                _pcp = min(_pcp, _pcap)
            wild.append(build_wild_pokemon(_eid, _s["lat"], _s["lng"], _sid, _pid,
                                           now, SPAWN_MS, cp=_pcp))
            catch.append(build_map_pokemon(_sid, _eid, _pid, _s["lat"], _s["lng"], expire))
            _world.remember_spawn(_eid, _pid, _s["lat"], _s["lng"], _pcp, _sid, expire)
            spawns.append(build_spawn_point(_s["lat"], _s["lng"]))
            nearby.append(build_nearby_pokemon(_pid, 20.0))

        # Incense: more wild Pokemon around the trainer while it burns.
        if cid == player_cell and _proc_spawns and _world.item_active(401):
            _n = _cfg.get("boosts", "incense_extra_spawns", cast=int)
            for k in range(_n):
                r = _random.Random((cid ^ (_win * 0x9E3779B1) ^ (k * 0x51ED2701)
                                    ^ 0x1CE45E) & 0x7FFFFFFF)
                ang = 2 * _math.pi * k / max(1, _n) + r.uniform(-0.3, 0.3)
                dist = 18.0 + r.random() * 40.0
                dl = lat + (dist * _math.cos(ang)) / 111320.0
                dn = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat))))
                eid = (cid ^ 0x1CE45E ^ (k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)) & ((1 << 62) - 1)
                if _world.is_despawned(eid):
                    continue
                pid = _pick_species(r, _ev, lat, lng)
                cp = _pick_cp(r, _ev, pid)
                sid = _hex_id((eid, "inc"), 11)
                wild.append(build_wild_pokemon(eid, dl, dn, sid, pid, now, SPAWN_MS, cp=cp))
                catch.append(build_map_pokemon(sid, eid, pid, dl, dn, expire))
                _world.remember_spawn(eid, pid, dl, dn, cp, sid, expire)
                spawns.append(build_spawn_point(dl, dn))
                nearby.append(build_nearby_pokemon(pid, 15.0))

        # Lures: extra Pokemon clustered on any lured stop in this cell.
        if _proc_spawns:
            for _lf, _lm in _lured.items():
                _pos = _fort_pos.get(_lf)
                if not _pos or _cell_of(_pos[0], _pos[1]) != cid:
                    continue
                _n = _cfg.get("boosts", "lure_extra_spawns", cast=int)
                for k in range(_n):
                    r = _random.Random((hash(_lf) ^ (_win * 0x9E3779B1)
                                        ^ (k * 0x2545F491)) & 0x7FFFFFFF)
                    ang = 2 * _math.pi * k / max(1, _n) + r.uniform(-0.4, 0.4)
                    dist = 8.0 + r.random() * 22.0
                    dl = _pos[0] + (dist * _math.cos(ang)) / 111320.0
                    dn = _pos[1] + (dist * _math.sin(ang)) / (
                        111320.0 * max(0.2, _math.cos(_math.radians(_pos[0]))))
                    eid = (hash(_lf) ^ 0x1D4E ^ (k * 0x9E3779B1)
                           ^ (_win * 0x85EBCA6B)) & ((1 << 62) - 1)
                    if _world.is_despawned(eid):
                        continue
                    pid = _pick_species(r, _ev, _pos[0], _pos[1])
                    cp = _pick_cp(r, _ev, pid)
                    sid = _hex_id((eid, "lure"), 11)
                    wild.append(build_wild_pokemon(eid, dl, dn, sid, pid, now, SPAWN_MS, cp=cp))
                    catch.append(build_map_pokemon(sid, eid, pid, dl, dn, expire))
                    _world.remember_spawn(eid, pid, dl, dn, cp, sid, expire)
                    spawns.append(build_spawn_point(dl, dn))
                    nearby.append(build_nearby_pokemon(pid, 12.0))

        # A defeated raid boss waiting at the trainer's feet (their cell only).
        if cid == player_cell:
            for _b in _world.bonus_spawns(_world.current().username):
                if _world.is_despawned(_b["eid"]):
                    continue
                _bsid = _hex_id((_b["eid"], "raid"), 11)
                wild.append(build_wild_pokemon(_b["eid"], _b["lat"], _b["lng"],
                                               _bsid, _b["pid"], now,
                                               max(60_000, _b["expires_ms"] - now),
                                               cp=_b["cp"]))
                catch.append(build_map_pokemon(_bsid, _b["eid"], _b["pid"],
                                               _b["lat"], _b["lng"], _b["expires_ms"]))
                _world.remember_spawn(_b["eid"], _b["pid"], _b["lat"], _b["lng"],
                                      _b["cp"], _bsid, _b["expires_ms"])
                spawns.append(build_spawn_point(_b["lat"], _b["lng"]))
                nearby.append(build_nearby_pokemon(_b["pid"], 5.0))

        spawned += len(wild)
        w.message(1, build_map_cell(cid, now, catch, forts, wild,
                                    spawn_points=spawns, nearby=nearby))
    w.uint(2, 1).uint(3, 1)   # status=SUCCESS, time_of_day=DAY
    # NOTE: POGOServer (0.35) omits time_of_day, but the 0.29 client defaults to
    # NIGHT without it -- the encounter screen renders black. Keep sending DAY.
    tag = "real fix -> spawns at player" if have_fix else "NO-GPS-FIX (0,0)"
    print(f"   [map] {len(cell_ids)} req cells, {len(cells)} sent; "
          f"player ({lat:.5f},{lng:.5f}) [{tag}]; "
          f"{spawned} mons, {forts_n} stops/gyms", flush=True)
    return w.to_bytes()


_GAME_MASTER = None

def build_download_item_templates_response(templates=None) -> bytes:
    # SERVE_GAME_MASTER=1 -> serve the full 2016 game master (game_master.bin). The
    # client loads+applies it but then boot-loops on the asset layer (wants the real
    # CDN asset bundles we don't host). Default OFF -> minimal templates so the client
    # finishes loading and reaches the playable MAP (trainer at your location).
    global _GAME_MASTER
    if os.environ.get("SERVE_GAME_MASTER") == "1":
        if _GAME_MASTER is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_master.bin")
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                # STRIP the master's OWN timestamp (field 3) and keep only result +
                # templates, so the TEMPLATES_TS we append below is the ONLY version
                # the client sees. The authentic 2016 master carries its own ts
                # (1471916269862) which != TEMPLATES_TS; leaving both in means a client
                # that reads the first field-3 sees a version different from what
                # DOWNLOAD_REMOTE_CONFIG_VERSION advertised -> it rejects the master and
                # rendering (incl. the tutorial starter) glitches. Rebuilding drops the
                # stray timestamp. (The old CONVERTED master happened to bake the same
                # ts as TEMPLATES_TS, so the duplicate was harmless -- hence this only
                # broke after swapping in the authentic file.)
                d = pb.decode(raw)
                w = pb.Writer()
                res = pb.get(d, 1, pb.WT_VARINT)
                if res is not None:
                    w.uint(1, res)
                for t in pb.get_all(d, 2):
                    w.message(2, t)
                _GAME_MASTER = w.to_bytes()
            except OSError:
                _GAME_MASTER = b""
        if _GAME_MASTER:
            # Append the single authoritative version. Bump TEMPLATES_TS to force a
            # re-download without regenerating the .bin.
            return _GAME_MASTER + pb.Writer().uint(3, TEMPLATES_TS).to_bytes()
    w = pb.Writer().uint(1, 1)                          # success
    for t in (templates or [build_item_template("PRIVATE_SERVER_0001")]):
        w.message(2, t)
    return w.uint(3, TEMPLATES_TS).to_bytes()


def build_download_remote_config_version_response(platform="android") -> bytes:
    # DownloadRemoteConfigVersionResponse { result=1 SUCCESS,
    #   item_templates_timestamp_ms=2, asset_digest_timestamp_ms=3 }
    # asset_digest_timestamp_ms MUST equal the digest file's own timestamp (a
    # microsecond value, e.g. 1467338276561000) -- not a millisecond clock and not an
    # invented constant. If it doesn't match, the client never treats the digest as
    # current and keeps re-fetching it instead of using the bundles.
    return (pb.Writer()
            .uint(1, 1)                 # result = SUCCESS
            .uint(2, TEMPLATES_TS)      # item templates: ordinary ms
            .uint(3, digest_timestamp(platform) or ASSET_TS)
            .to_bytes())


def build_download_settings_response() -> bytes:
    # DownloadSettingsResponse { error=1, hash=2, settings=3 GlobalSettings }
    # GlobalSettings { fort_settings=2, map_settings=3, level_settings=4,
    #                  inventory_settings=5, minimum_client_version=6 }
    #
    # These field numbers were previously GUESSED and were WRONG: map_settings was
    # written into slot 2 (fort_settings) and a bare string into slot 5
    # (inventory_settings). Consequences, both observed live:
    #   * FortSettings.interaction_range_meters never arrived -> defaulted to 0
    #     -> PokeStops render but CANNOT BE SPUN at any distance.
    #   * MapSettings.pokemon_visible_range never arrived -> defaulted to 0
    #     -> wild Pokemon are never drawn.
    # Values below are the genuine 2016 ones taken from maierfelix/POGOServer.
    # Reach is configurable (settings.distances); the defaults are the genuine
    # 2016 numbers. The client enforces all of this -- we never check position --
    # so these values ARE the reach.
    _reach = _cfg.get("distances", "fort_interaction_m", cast=float)
    _enc = _cfg.get("distances", "encounter_m", cast=float)
    _vis = _cfg.get("distances", "pokemon_visible_m", cast=float)
    fort_settings = (pb.Writer()
                     .double(1, _reach)                 # interaction_range_meters
                     .int_(2, 10)                       # max_total_deployed_pokemon
                     .int_(3, 1)                        # max_player_deployed_pokemon
                     .double(4, 8.062745098039215)      # deploy_stamina_multiplier
                     .double(5, 0.0)                    # deploy_attack_multiplier
                     .double(6, max(1000.0156862745098, _reach))
                     .to_bytes())                       # far_interaction_range_meters
    map_settings = (pb.Writer()
                    .double(1, _vis)                    # pokemon_visible_range
                    .double(2, 751.0156862745098)       # poke_nav_range_meters
                    .double(3, _enc)                    # encounter_range_meters
                    .float_(4, 10.007843017578125)      # get_map_objects_min_refresh_seconds
                    .float_(5, 11.01568603515625)       # get_map_objects_max_refresh_seconds
                    .float_(6, 10.007843017578125)      # get_map_objects_min_distance_meters
                    .string(7, "")                      # google_maps_api_key (ours: none)
                    .to_bytes())
    inventory_settings = (pb.Writer()
                          .int_(1, 1000)                # max_pokemon
                          .int_(2, 1000)                # max_bag_items
                          .int_(3, 250)                 # base_pokemon
                          .int_(4, 350)                 # base_bag_items
                          .int_(5, 9)                   # base_eggs
                          .to_bytes())
    # LevelSettingsProto { trainer_cp_modifier=2, trainer_difficulty_modifier=3 }
    # (tags read from the 0.29 metadata). Values are the ones seen in 2016
    # captures. Wire type is double per POGOProtos; if the client disagrees it
    # skips the unknown tag rather than failing, so a mismatch is harmless.
    level_settings = (pb.Writer()
                      .double(2, 2.0)                   # trainer_cp_modifier
                      .double(3, 0.2)                   # trainer_difficulty_modifier
                      .to_bytes())
    # This is every field the 0.29 GlobalSettingsProto has (checked with
    # tools/metadata_fields.py) -- nothing the client reads is left unset.
    settings = (pb.Writer()
                .message(2, fort_settings)
                .message(3, map_settings)
                .message(4, level_settings)
                .message(5, inventory_settings)
                .string(6, _cfg.get("server", "min_client_version")
                        or "0.29.0")                    # minimum_client_version (toggle)
                .to_bytes())
    # The client caches GlobalSettings against this hash and will NOT re-read
    # them while it stays the same -- which is how a settings change silently
    # does nothing. Derive it from the bytes so any edit invalidates the cache
    # by itself, instead of relying on someone remembering to bump a constant.
    _hash = SETTINGS_HASH + "-" + _hashlib.md5(settings).hexdigest()[:8]
    return (pb.Writer()
            .string(2, _hash)           # hash
            .message(3, settings)       # settings
            .to_bytes())


def build_auth_ticket(username: str = "", ttl_seconds: int = 2 * 60 * 60) -> bytes:
    start = _AT_MAGIC + username.encode("utf-8") + b"\x00" + os.urandom(16)
    return (pb.Writer()
            .bytes_(AT_START, start)
            .uint(AT_EXPIRE, int(time.time() * 1000) + ttl_seconds * 1000)
            .bytes_(AT_END, os.urandom(32))
            .to_bytes())


def username_from_auth_ticket(ticket_bytes: bytes):
    """Recover the username we stashed in AuthTicket.start, if present."""
    try:
        start = pb.get(pb.decode(ticket_bytes), AT_START, pb.WT_LEN)
        if start and start.startswith(_AT_MAGIC):
            return start[len(_AT_MAGIC):].split(b"\x00", 1)[0].decode("utf-8")
    except Exception:
        pass
    return None


def auth_token_from_envelope(fields):
    """Pull the PTC/Google token string out of RequestEnvelope.auth_info."""
    auth_info = pb.get(fields, RE_AUTH_INFO, pb.WT_LEN)
    if not isinstance(auth_info, bytes):
        return None
    ai = pb.decode(auth_info)
    token_msg = pb.get(ai, AI_TOKEN, pb.WT_LEN)
    if isinstance(token_msg, bytes):
        contents = pb.get(pb.decode(token_msg), AI_TOKEN_CONTENTS, pb.WT_LEN)
        if isinstance(contents, bytes):
            return contents.decode("utf-8", "replace")
    return None


def build_response_envelope(*, status_code, request_id, returns=(),
                            api_url=None, auth_ticket=None, error=None,
                            unknown6=None) -> bytes:
    w = pb.Writer().uint(RESP_STATUS_CODE, status_code)
    if request_id is not None:
        w.uint(RESP_REQUEST_ID, request_id)
    if api_url:
        w.string(RESP_API_URL, api_url)
    if error:
        w.string(RESP_ERROR, error)
    if unknown6 is not None:                 # platform response(s): the shop screen
        for u in (unknown6 if isinstance(unknown6, (list, tuple)) else [unknown6]):
            w.bytes_(RESP_UNKNOWN6, u)
    if auth_ticket is not None:
        w.message(RESP_AUTH_TICKET, auth_ticket)
    for r in returns:
        w.bytes_(RESP_RETURNS, r)
    return w.to_bytes()


def resolve_username(fields):
    """Best-effort username: from auth_info token, else from auth_ticket."""
    from sso import username_from_token
    token = auth_token_from_envelope(fields)
    if token:
        return username_from_token(token)
    ticket = pb.get(fields, RE_AUTH_TICKET, pb.WT_LEN)
    if isinstance(ticket, bytes):
        u = username_from_auth_ticket(ticket)
        if u:
            return u
    return None


def parse_request_envelope(buf: bytes):
    """Return (request_id, [(request_type, request_message_bytes), ...], fields)."""
    fields = pb.decode(buf)
    request_id = pb.get(fields, RE_REQUEST_ID, pb.WT_VARINT)
    reqs = []
    for raw in pb.get_all(fields, RE_REQUESTS):
        if isinstance(raw, bytes):
            inner = pb.decode(raw)
            rtype = pb.get(inner, REQ_TYPE, pb.WT_VARINT) or 0
            rmsg = pb.get(inner, REQ_MESSAGE, pb.WT_LEN) or b""
            reqs.append((rtype, rmsg))
    return request_id, reqs, fields


def wants_shop(fields):
    """True if this envelope is the client's Shop-screen poll: it carries a
    platform request of type 5 ("list IAP items"). The client sends this (with an
    empty requests list) whenever the in-game Shop is open, and expects the item
    list back in the response's field-6 platform response."""
    for raw in pb.get_all(fields, RE_UNKNOWN6):
        if isinstance(raw, bytes):
            try:
                if pb.get(pb.decode(raw), 1, pb.WT_VARINT) == PLAT_SHOP:
                    return True
            except Exception:
                pass
    return False


def buy_item_id(fields):
    """If this envelope is a shop PURCHASE (platform request type 2), return the
    item_id string being bought (e.g. 'pgorelease.pokeball.20'); else None."""
    for raw in pb.get_all(fields, RE_UNKNOWN6):
        if isinstance(raw, bytes):
            try:
                d = pb.decode(raw)
                if pb.get(d, 1, pb.WT_VARINT) == PLAT_BUY:
                    payload = pb.get(d, 2, pb.WT_LEN)
                    if isinstance(payload, bytes):
                        item = pb.get(pb.decode(payload), 1, pb.WT_LEN)
                        if isinstance(item, bytes):
                            return item.decode("utf-8", "replace")
            except Exception:
                pass
    return None


# ---------------------------------------------- the rest of the 0.29 Method enum
# Everything below answers a request the 2016 UI rarely or never sends. Field
# numbers are read from the 0.29 client's own metadata (tools/metadata_fields.py
# <Name>Proto <Name>OutProto). Result enums follow Niantic's usual 0=UNSET,
# 1=SUCCESS; the failure codes are NOT verified against the client.

def _str_field(f, n):
    v = pb.get(f, n, pb.WT_LEN)
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else ""


def parse_fort_recall(msg):
    """FortRecallProto { fort_id=1, pokemon_id=2 fixed64, lat=3, lng=4 }."""
    f = pb.decode(msg)
    return (_str_field(f, 1), pb.get(f, 2, pb.WT_64) or 0,
            _f64_to_double(pb.get(f, 3, pb.WT_64)),
            _f64_to_double(pb.get(f, 4, pb.WT_64)))


def build_fort_recall_response(fort_id, uid, lat, lng) -> bytes:
    """FortRecallOutProto { result=1, fort_details_out_proto=2 }. Takes your
    defender back off the gym (world.recall already exists for gym logic)."""
    import world
    if not world.recall(fort_id, uid):
        return pb.Writer().uint(1, 2).to_bytes()          # not there (unverified code)
    return (pb.Writer().uint(1, 1)
            .message(2, build_fort_details_response(fort_id, lat, lng))
            .to_bytes())


def parse_use_item_gym(msg):
    """UseItemGymProto { item=1, gym_id=2, lat=3, lng=4 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_VARINT) or 0, _str_field(f, 2)


def build_use_item_gym_response(gym_id) -> bytes:
    """UseItemGymOutProto { result=1, updated_gp=2 } -- gp = the gym's prestige.
    No gym item exists in 2016, so nothing is spent; we report the gym as is."""
    import world
    return (pb.Writer().uint(1, 1)
            .int_(2, int(world.gym_prestige(gym_id) or 0)).to_bytes())


def build_collect_daily_bonus_response() -> bytes:
    """CollectDailyBonusOutProto { result=1 }. The 2016 daily bonus is the
    defender shield (#146, handled separately); this generic one has no payout
    defined anywhere in the client, so it just succeeds."""
    return pb.Writer().uint(1, 1).to_bytes()


def parse_special_encounter(msg):
    """IncenseEncounterProto { encounter_id=1, encounter_location=2 } and
    DiskEncounterProto { encounter_id=1, fort_id=2, ... } -- both start with a
    fixed64 encounter id."""
    return pb.get(pb.decode(msg), 1, pb.WT_64) or 0


def build_special_encounter_response(encounter_id) -> bytes:
    """IncenseEncounterOutProto / DiskEncounterOutProto { result=1, pokemon=2
    PokemonProto, capture_probability=3 }. Our incense/lure Pokemon are ordinary
    wild spawns, so the same spawn table answers both. After this the client
    uses the normal CATCH_POKEMON, which already works off world.SPAWNS."""
    import world
    s = world.get_spawn(encounter_id)
    if not s:
        return pb.Writer().uint(1, 2).to_bytes()          # gone (unverified code)
    world.bump("pokemons_encountered")
    world.pokedex_saw(s["pokemon_id"])
    return (pb.Writer().uint(1, 1)
            .message(2, build_pokemon_data(s["pokemon_id"], encounter_id, s["cp"]))
            .message(3, build_capture_probability(s["pokemon_id"], s["cp"]))
            .to_bytes())


def build_equip_badge_response(msg) -> bytes:
    """EquipBadgeProto { badge=1 } -> EquipBadgeOutProto { result=1, equipped=2
    EquippedBadgeProto { equipped_badge=1, level=2, next_change_ms=3 } }."""
    badge = pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0
    rank = next((r for bt, r, *_ in badge_progress() if bt == badge), 0)
    eq = pb.Writer().uint(1, badge).int_(2, rank).int_(3, 0).to_bytes()
    return pb.Writer().uint(1, 1).message(2, eq).to_bytes()


def build_echo_response() -> bytes:
    """EchoOutProto { context=1 } -- a ping."""
    return pb.Writer().string(1, "windstock").to_bytes()


def build_debug_update_inventory_response(msg) -> bytes:
    """DebugUpdateInventoryProto { pokemon=1, item=2 (ItemProto {item_id=1,
    count=2}) } -> { success=1 }. Grants the listed items; Pokemon are ignored."""
    import world
    for raw in pb.get_all(pb.decode(msg), 2):
        if isinstance(raw, bytes):
            it = pb.decode(raw)
            iid, n = pb.get(it, 1, pb.WT_VARINT) or 0, pb.get(it, 2, pb.WT_VARINT) or 0
            if iid and n > 0:
                world.add_item(iid, n)
    return pb.Writer().bool_(1, True).to_bytes()


def build_debug_delete_player_response() -> bytes:
    """DebugDeletePlayerOutProto { success=1 }. Deliberately REFUSED: a stray
    debug call must never wipe a save."""
    return pb.Writer().bool_(1, False).to_bytes()


def parse_player_update(msg):
    """PlayerUpdateProto { lat=1 double, lng=2 double }."""
    f = pb.decode(msg)
    return (_f64_to_double(pb.get(f, 1, pb.WT_64)),
            _f64_to_double(pb.get(f, 2, pb.WT_64)))
