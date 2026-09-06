"""
Convert the 2016 GAME_MASTER text dump (gm_2016.txt, an earlier-proto PascalCase
dump) into a serialized DownloadItemTemplatesResponse using the compiled 0.29-era
POGOProtos (commit 05afd1d). Output: game_master.bin (raw protobuf bytes) that the
server serves verbatim for DOWNLOAD_ITEM_TEMPLATES.

Strategy: parse the text dump ourselves (the field names don't match this proto, so
text_format.Parse won't work), then map each field into the proto message by
NORMALIZED name (lowercase, strip underscores) with a few explicit aliases, plus
string->enum resolution and packed-bytes decoding for repeated scalar fields.
"""
import os, re, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
PYOUT = os.path.join(HERE, "POGOProtos-05afd1d0969203591c6a38a7c5f2b4060efa85a3", "pyout")
sys.path.insert(0, PYOUT)

from google.protobuf.descriptor import FieldDescriptor as FD
from Networking.Responses import DownloadItemTemplatesResponse_pb2 as DT

# ----------------------------------------------------------------- text parser
def _unescape(s: str) -> bytes:
    """C-style escaped string (octal \\ddd, \\xhh, \\n ...) -> raw bytes."""
    out = bytearray(); i = 0; n = len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out += c.encode("latin1", "replace"); i += 1; continue
        nxt = s[i+1]
        if nxt in "01234567":                       # octal, up to 3 digits
            j = i+1; k = j
            while k < n and k < j+3 and s[k] in "01234567":
                k += 1
            out.append(int(s[j:k], 8)); i = k
        elif nxt == "x":
            j = i+2; k = j
            while k < n and k < j+2 and s[k] in "0123456789abcdefABCDEF":
                k += 1
            out.append(int(s[j:k], 16)); i = k
        else:
            out.append({"n":10,"t":9,"r":13,"\\":92,'"':34,"'":39}.get(nxt, ord(nxt)))
            i += 2
    return bytes(out)


def tokenize(text):
    toks = []; i = 0; n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1; continue
        if c in "{}:":
            toks.append((c, c)); i += 1; continue
        if c == '"':
            j = i+1; buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    buf.append(text[j:j+2]); j += 2
                else:
                    buf.append(text[j]); j += 1
            toks.append(("str", "".join(buf))); i = j+1; continue
        j = i
        while j < n and text[j] not in " \t\r\n{}:\"":
            j += 1
        toks.append(("tok", text[i:j])); i = j
    return toks


def parse_body(toks, pos, top=False):
    """Return (list of (key, value), next_pos). value = ('s', token)/('b', bytes)/('m', body)."""
    items = []
    while pos < len(toks):
        kind, val = toks[pos]
        if kind == "}":
            return items, pos+1
        # key is a bare token
        key = val; pos += 1
        if pos < len(toks) and toks[pos][0] == ":":
            pos += 1
            vk, vv = toks[pos]; pos += 1
            if vk == "str":
                items.append((key, ("b", _unescape(vv))))
            else:
                items.append((key, ("s", vv)))
        elif pos < len(toks) and toks[pos][0] == "{":
            pos += 1
            body, pos = parse_body(toks, pos)
            items.append((key, ("m", body)))
        else:
            items.append((key, ("s", "")))
        if top and pos >= len(toks):
            break
    return items, pos


# ------------------------------------------------------------- field resolver
def _norm(s): return s.replace("_", "").lower()

# context-specific aliases: {proto message name: {normalized gist key: proto field}}
# (most fields auto-match by normalized name; these are the renamed ones.)
ALIASES = {
    "ItemTemplate": {
        "pokemon": "pokemon_settings", "item": "item_settings",
        "move": "move_settings", "movesequence": "move_sequence_settings",
        "badge": "badge_settings",
    },
    "PokemonSettings": {
        "uniqueid": "pokemon_id", "type1": "type", "pokemonclass": "class",
        "animtime": "animation_time", "evolution": "evolution_ids",
        "parentid": "parent_pokemon_id",
    },
    "MoveSettings": {
        "uniqueid": "movement_id", "type": "pokemon_type",
    },
    # The dump abbreviates "Cylinder" to "Cyl", so these never matched by
    # normalized name and were SILENTLY DROPPED -> every Pokemon got
    # cylinder_height_m = 0, which makes the client's encounter camera compute a
    # zero look vector ("Look rotation viewing vector is zero" spam) and frame
    # nothing -- the Pokemon model loads but is never visible.
    # More dump-vs-proto name mismatches that were silently dropping data.
    # ItemSettings.item_id is what lets the client match a bag entry to its
    # template (name/icon/behaviour) -- without it the bag can't display items.
    "ItemSettings": {"uniqueid": "item_id"},
    # The shop entries. The dump calls the contents "Items", the proto calls them
    # "item_ids", so every shop pack shipped with an EMPTY contents list.
    "IapItemDisplay": {"items": "item_ids"},
    # required_experience is the XP-per-level table; without it the client
    # cannot work out your level or draw the progress ring.
    "PlayerLevelSettings": {"requiredexp": "required_experience"},
    "GymLevelSettings": {"requiredexp": "required_experience"},
    "BadgeSettings": {"badgeranks": "badge_rank"},
    "CameraAttributes": {
        "cylradiusm": "cylinder_radius_m",
        "cylheightm": "cylinder_height_m",
        "cylgroundm": "cylinder_ground_m",
    },
    # The battle-camera templates. Every one of these 10 fields failed to match,
    # so all 322 Camera templates serialized as EMPTY messages -- which is what
    # made the client throw ArgumentOutOfRangeException on the loading screen and
    # got Camera (and MoveSequence with it) excluded in the first place.
    # Field NUMBERS are right in POGOProtos; only the names are off, and
    # "east_out_speed" is a genuine typo in POGOProtos, not ours.
    "CameraSettings": {
        "easeoutspeed": "east_out_speed",
        "durations": "duration_seconds",
        "waits": "wait_seconds",
        "transitions": "transition_seconds",
        "angledeg": "angle_degree",
        "angleoffsetdeg": "angle_offset_degree",
        "pitchdeg": "pitch_degree",
        "pitchoffsetdeg": "pitch_offset_degree",
        "rolldeg": "roll_degree",
        "distancem": "distance_meters",
    },
}

# every (message, field) the converter could not map -- printed at the end so a
# silent drop like the Cyl* one above can never go unnoticed again
SKIPPED = {}

def field_map(msg_descriptor):
    m = {}
    for f in msg_descriptor.fields:
        m[_norm(f.name)] = f
    return m

def resolve_enum(field, s):
    """gist enum token -> int value. For V####_NAME ids the number IS the enum
    value (pokemon/move/family are numbered to match), so use it directly; this
    guarantees Pokemon move refs line up with Move templates. Otherwise by name."""
    if re.fullmatch(r"-?\d+", s):                 # bare int (fast moves: "UniqueId: 200")
        return int(s)
    m = re.match(r"^V(\d+)_", s)
    if m:
        return int(m.group(1))
    et = field.enum_type
    v = et.values_by_name.get(s)
    if v is not None:
        return v.number
    for ev in et.values:                          # last resort: suffix match
        if s.endswith(ev.name):
            return ev.number
    return None

_PACK = {FD.TYPE_FLOAT: ("<f", 4), FD.TYPE_DOUBLE: ("<d", 8)}

def decode_packed(field, raw: bytes):
    """Packed repeated scalar bytes -> list of python values."""
    if field.type in _PACK:
        fmt, sz = _PACK[field.type]
        return [struct.unpack(fmt, raw[i:i+sz])[0] for i in range(0, len(raw)-sz+1, sz)]
    # varint-packed (int/enum/bool)
    out = []; i = 0
    while i < len(raw):
        shift = 0; res = 0
        while True:
            b = raw[i]; i += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift += 7
        out.append(res)
    return out


def set_field(msg, key, value):
    fmap = field_map(msg.DESCRIPTOR)
    nk = _norm(key)
    aliased = ALIASES.get(msg.DESCRIPTOR.name, {}).get(nk)
    f = fmap.get(nk) or (fmap.get(_norm(aliased)) if aliased else None)
    if f is None:
        key = f"{msg.DESCRIPTOR.name}.{key}"
        SKIPPED[key] = SKIPPED.get(key, 0) + 1
        return False                              # unknown field for this version; skip
    kind = value[0]
    repeated = f.label == FD.LABEL_REPEATED
    if f.type == FD.TYPE_MESSAGE:
        if kind != "m":
            return False
        sub = getattr(msg, f.name).add() if repeated else getattr(msg, f.name)
        for k2, v2 in value[1]:
            set_field(sub, k2, v2)
        return True
    # scalar / enum
    if repeated and kind == "b":                  # repeated value dumped as bytes
        if f.type == FD.TYPE_STRING:              # one string entry (e.g. MoveSequence)
            getattr(msg, f.name).append(value[1].decode("utf-8", "replace"))
            return True
        if f.type == FD.TYPE_BYTES:
            getattr(msg, f.name).append(value[1])
            return True
        if f.type == FD.TYPE_MESSAGE:
            return False
        try:                                      # packed numeric/enum
            getattr(msg, f.name).extend(decode_packed(f, value[1]))
        except (TypeError, ValueError):
            return False
        return True
    if f.type == FD.TYPE_ENUM:
        ev = resolve_enum(f, value[1] if kind == "s" else "")
        if ev is None:
            return False
        if repeated: getattr(msg, f.name).append(ev)
        else: setattr(msg, f.name, ev)
        return True
    if f.type == FD.TYPE_BYTES:
        setattr(msg, f.name, value[1] if kind == "b" else b"")
        return True
    # numeric / bool / string
    raw = value[1]
    if f.type in (FD.TYPE_FLOAT, FD.TYPE_DOUBLE):
        py = float(raw)
    elif f.type == FD.TYPE_BOOL:
        py = raw in ("true", "1", "True")
    elif f.type == FD.TYPE_STRING:
        py = raw if kind == "s" else value[1].decode("utf-8", "replace")
    else:
        py = int(raw)
    if repeated: getattr(msg, f.name).append(py)
    else: setattr(msg, f.name, py)
    return True


# --------------------------------------------------------------------- driver
def main():
    text = open(os.path.join(HERE, "gm_2016.txt"), encoding="utf-8", errors="replace").read()
    toks = tokenize(text)
    body, _ = parse_body(toks, 0, top=True)

    resp = DT.DownloadItemTemplatesResponse()
    resp.success = True
    resp.timestamp_ms = 1473300000000          # MUST match protocol.TEMPLATES_TS

    # types we cannot convert cleanly (skipped repeated-string fields) -> exclude
    EXCLUDE = set(x for x in os.environ.get("GM_EXCLUDE", "").split(",") if x)
    n_items = 0; skipped_fields = {}; excluded = 0
    for key, value in body:
        if key != "Items" or value[0] != "m":
            continue
        settings_keys = [k for k, v in value[1] if v[0] == "m"]
        if any(k in EXCLUDE for k in settings_keys):
            excluded += 1
            continue
        tmpl = resp.item_templates.add()
        for k2, v2 in value[1]:
            ok = set_field(tmpl, k2, v2)
            if not ok:
                skipped_fields[k2] = skipped_fields.get(k2, 0) + 1
        n_items += 1
    print(f"excluded {excluded} templates of types {EXCLUDE}")

    # The 2016 dump's FamilyId values are corrupt: Charmander is listed under
    # FAMILY_CATERPIE, and unrelated lines get merged onto one id -- family 98
    # ends up holding Oddish/Gloom/Vileplume AND Krabby/Kingler, so they share a
    # candy pool. 59 families for 151 Pokemon when Gen 1 has ~73. The evolution
    # chains in the same dump ARE correct, and a family id is by definition the
    # pokedex number of the base form, so derive it from those instead.
    evo_of = {}
    for t in resp.item_templates:
        if t.HasField("pokemon_settings"):
            evo_of[t.pokemon_settings.pokemon_id] = list(t.pokemon_settings.evolution_ids)
    parent = {}
    for pid, kids in evo_of.items():
        for k in kids:
            parent[k] = pid

    def root_of(pid):
        seen = set()
        while pid in parent and pid not in seen:
            seen.add(pid)
            pid = parent[pid]
        return pid

    fixed = 0
    for t in resp.item_templates:
        if t.HasField("pokemon_settings"):
            p = t.pokemon_settings
            r = root_of(p.pokemon_id)
            if p.family_id != r:
                p.family_id = r
                fixed += 1
    print(f"rebuilt family_id from evolution chains ({fixed} corrected, "
          f"{len(set(root_of(p) for p in evo_of))} families)")

    # The encounter intro camera holds the Pokemon in close for ~3s before the
    # catch UI. It only started happening once the Camera templates were restored
    # (it had never worked before), and it is not wanted. Zero the timings rather
    # than drop the template -- a MISSING camera template is what threw
    # ArgumentOutOfRangeException on the loading screen in the first place.
    # Set GM_KEEP_ENCOUNTER_INTRO=1 to get the original 2016 behaviour back.
    if os.environ.get("GM_KEEP_ENCOUNTER_INTRO") != "1":
        for t in resp.item_templates:
            if t.template_id == "camera_encounterintro":
                c = t.camera
                for fld in ("duration_seconds", "wait_seconds", "transition_seconds"):
                    vals = getattr(c, fld)
                    n = len(vals)
                    del vals[:]
                    vals.extend([0.0] * n)
                print(f"flattened {t.template_id} (instant encounter intro)")

    out = resp.SerializeToString()
    open(os.path.join(HERE, "game_master.bin"), "wb").write(out)
    print(f"templates: {n_items}, bytes: {len(out)}")
    if skipped_fields:
        print("skipped top-level fields:", skipped_fields)
    if SKIPPED:
        print("DROPPED fields (message.Field -> count):")
        for k, v in sorted(SKIPPED.items(), key=lambda kv: -kv[1]):
            print(f"   {k}: {v}")
    # sanity: re-parse and count pokemon settings
    chk = DT.DownloadItemTemplatesResponse(); chk.ParseFromString(out)
    npk = sum(1 for t in chk.item_templates if t.HasField("pokemon_settings"))
    nit = sum(1 for t in chk.item_templates if t.HasField("item_settings"))
    nmv = sum(1 for t in chk.item_templates if t.HasField("move_settings"))
    print(f"verify: {npk} pokemon, {nit} items, {nmv} moves")
    if npk:
        p = next(t.pokemon_settings for t in chk.item_templates if t.HasField("pokemon_settings"))
        print(f"  first pokemon: id={p.pokemon_id} type={p.type} quick_moves={list(p.quick_moves)} "
              f"stats(sta/atk/def)={p.stats.base_stamina}/{p.stats.base_attack}/{p.stats.base_defense}")

    write_gamedata(chk)


def write_gamedata(chk):
    """Emit server/gamedata.py: the move timings and per-species movesets.

    The server has to build BattleActions that match a REAL move, because the
    client resolves an action to an animation through the defender's moveset ->
    MoveSettings.vfx_name -> the `sequence_<vfx>` template. An invented duration
    or damage window matches no move, so the client silently drops the action --
    which is why gym defenders never attacked back.
    """
    moves, quick, charged, stats, mtypes = {}, {}, {}, {}, {}
    cpm_table = []
    for t in chk.item_templates:
        if t.HasField("move_settings"):
            m = t.move_settings
            moves[m.movement_id] = (m.duration_ms, m.damage_window_start_ms,
                                    m.damage_window_end_ms, m.energy_delta,
                                    round(m.power))
            mtypes[m.movement_id] = int(m.pokemon_type)
        elif t.HasField("pokemon_settings"):
            p = t.pokemon_settings
            if p.quick_moves:
                quick[p.pokemon_id] = list(p.quick_moves)
            if p.cinematic_moves:
                charged[p.pokemon_id] = list(p.cinematic_moves)
            s = p.stats
            stats[p.pokemon_id] = (s.base_attack, s.base_defense, s.base_stamina)
        elif t.HasField("player_level"):
            cpm_table = list(t.player_level.cp_multiplier)
    dst = os.path.join(HERE, "..", "server", "gamedata.py")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write('"""GENERATED by tools/convert_gm.py -- do not edit by hand."""\n\n')
        fh.write("# move_id -> (duration_ms, damage_window_start_ms,\n")
        fh.write("#             damage_window_end_ms, energy_delta, power)\n")
        fh.write("MOVES = {\n")
        for k in sorted(moves):
            fh.write(f"    {k}: {moves[k]},\n")
        fh.write("}\n\n# move_id -> HoloPokemonType of the move"
                 " (for STAB + type effectiveness)\n")
        fh.write("MOVE_TYPES = {\n")
        for k in sorted(mtypes):
            fh.write(f"    {k}: {mtypes[k]},\n")
        fh.write("}\n\n# pokemon_id -> legal quick / charged move ids\nQUICK = {\n")
        for k in sorted(quick):
            fh.write(f"    {k}: {quick[k]},\n")
        fh.write("}\n\nCHARGED = {\n")
        for k in sorted(charged):
            fh.write(f"    {k}: {charged[k]},\n")
        fh.write("}\n\n# pokemon_id -> (base_attack, base_defense, base_stamina)\n")
        fh.write("STATS = {\n")
        for k in sorted(stats):
            fh.write(f"    {k}: {stats[k]},\n")
        fh.write("}\n\n# cp_multiplier by trainer level (index 0 == level 1)\n")
        fh.write(f"CPM = {[round(x, 7) for x in cpm_table]}\n")
    print(f"wrote gamedata.py: {len(moves)} moves, {len(quick)} quick sets, "
          f"{len(charged)} charged sets, {len(stats)} stat lines, "
          f"{len(cpm_table)} cpm entries")


if __name__ == "__main__":
    main()
