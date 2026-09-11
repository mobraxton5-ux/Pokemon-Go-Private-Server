"""
Shorten the wild-encounter zoom-in so you reach the Poke Balls faster.

The authentic 2016 game master's `camera_encounterintro` template (a CameraSettings
message) holds the encounter camera for ~3 seconds -- transition_seconds and
duration_seconds are both 3.0 on the second keyframe. That is the slow zoom you
wait through every time you tap a wild Pokemon. This rewrites JUST those two float
arrays on JUST that one template, leaving every other byte of the authentic master
untouched, so nothing else changes.

Run from work/server:  py ../tools/tweak_encounter_camera.py [duration] [transition]
Defaults: duration 0.5s, transition 0.5s. Pass e.g. `1.0 0.8` for a gentler cut,
or `0 0` for an instant snap. Re-run any time; it always starts from the authentic
backup, so it is fully reversible (restore game_master.authentic.bak to undo).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import pb  # noqa: E402

HERE = os.path.join(os.path.dirname(__file__), "..", "server")
GM = os.path.join(HERE, "game_master.bin")
AUTH = os.path.join(HERE, "game_master.authentic.bak")

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
TRANSITION = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5

# CameraSettings field numbers (POGOProtos): duration_seconds=6, transition_seconds=8.
CAM_FIELD = 11            # the camera message inside the ItemTemplate
F_DURATION = 6
F_TRANSITION = 8


def reemit(decoded, replace=None):
    """Serialize a pb.decode() field list back to bytes, preserving order. Any
    field number in `replace` gets its raw value swapped for replace[field]."""
    replace = replace or {}
    out = bytearray()
    for f in decoded:
        fld, wire = f["field"], f["wire"]
        val = replace.get(fld, f["value"]) if fld in replace else f["value"]
        out += pb.varint((fld << 3) | wire)
        if wire == pb.WT_VARINT:
            out += pb.varint(val)
        elif wire == pb.WT_LEN:
            out += pb.varint(len(val)) + val
        elif wire == pb.WT_32:
            out += struct.pack("<I", val)
        elif wire == pb.WT_64:
            out += struct.pack("<Q", val)
        else:
            raise ValueError(f"unhandled wire type {wire}")
    return bytes(out)


def packed_floats_like(original: bytes, new_last: float) -> bytes:
    """Same number of floats as `original`, but every value after the first set to
    `new_last` (the keyframes we want fast). The first value stays 0.0 (the initial
    keyframe), matching the authentic shape."""
    n = len(original) // 4
    vals = [struct.unpack("<f", original[i * 4:i * 4 + 4])[0] for i in range(n)]
    out = [vals[0] if vals else 0.0] + [new_last] * (n - 1)
    return b"".join(struct.pack("<f", v) for v in out)


def main():
    # Always start from the authentic master so this is reversible + idempotent.
    if not os.path.exists(AUTH):
        with open(GM, "rb") as fh:
            open(AUTH, "wb").write(fh.read())
        print(f"backed up authentic master -> {os.path.basename(AUTH)}")
    with open(AUTH, "rb") as fh:
        data = fh.read()

    top = pb.decode(data)
    out_templates = 0
    patched = False
    rebuilt = bytearray()
    for f in top:
        if f["field"] != 2:                       # not an item_template: copy as-is
            rebuilt += reemit([f])
            continue
        out_templates += 1
        t = f["value"]
        td = pb.decode(t)
        tid = (pb.get(td, 1, pb.WT_LEN) or b"").decode("utf-8", "replace")
        if tid == "camera_encounterintro":
            cam = pb.get(td, CAM_FIELD, pb.WT_LEN)
            cd = pb.decode(cam)
            dur = pb.get(cd, F_DURATION, pb.WT_LEN) or b""
            trans = pb.get(cd, F_TRANSITION, pb.WT_LEN) or b""
            new_cam = reemit(cd, {
                F_DURATION: packed_floats_like(dur, DURATION),
                F_TRANSITION: packed_floats_like(trans, TRANSITION),
            })
            new_t = reemit(td, {CAM_FIELD: new_cam})
            rebuilt += pb.varint((2 << 3) | pb.WT_LEN) + pb.varint(len(new_t)) + new_t
            patched = True
            print(f"patched camera_encounterintro: duration->{DURATION}s "
                  f"transition->{TRANSITION}s")
        else:
            rebuilt += reemit([f])

    if not patched:
        print("WARNING: camera_encounterintro not found -- nothing changed")
        return
    with open(GM, "wb") as fh:
        fh.write(bytes(rebuilt))
    print(f"wrote {GM} ({len(rebuilt)} bytes, {out_templates} templates)")


if __name__ == "__main__":
    main()
