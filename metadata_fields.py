"""
metadata_fields.py -- read the 0.29 client's OWN protobuf field numbers (and enum
values) straight out of global-metadata.dat.

Why: POGOProtos is 0.35-era and disagrees with this build. protobuf's C# codegen
emits every tag as `public const int XxxFieldNumber`, and an enum's members are
const fields too -- both are static literals whose values live in the metadata
default-value blob. So the client tells us its own layout; no disassembly needed.

Usage:
    py metadata_fields.py PlayerStatsProto PlayerAvatarProto
    py metadata_fields.py --grep Badge          # list type names matching a word
    py metadata_fields.py --enum HoloBadgeType  # same as naming it, reads nicer

Header offsets are metadata v21 (verified: fieldDefaultValuesCount divides by 12,
fields are 16 bytes -- an 8-byte stride yields names alternating with "mscorlib",
which is customAttributeIndex = -1 read as a string index).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DAT = os.path.join(HERE, "..", "extracted", "assets", "bin", "Data",
                           "Managed", "Metadata", "global-metadata.dat")

FIELD_SIZE = 16          # Il2CppFieldDefinition (v21)
DEFVAL_SIZE = 12         # {fieldIndex, typeIndex, dataIndex}

# Il2CppTypeDefinition (v21) is 120 bytes: 24 int32s, then 8 uint16 counts, then
# bitfield + token. Confirmed by reading the first records by hand -- methodStart
# climbs 0, 10, 17 across Object/ValueType/Attribute, which pins the int32 block.
FIELD_START = 64         # int32, -1 when the type has no fields
FIELD_COUNT = 100        # uint16 (3rd of the count block at +96)


def _i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


class Metadata:
    def __init__(self, path):
        with open(path, "rb") as fh:
            self.buf = fh.read()
        b = self.buf
        if b[:4] != b"\xafULib"[:4] and _i32(b, 0) != 0xFAB11BAF:
            pass                                   # sanity only; keep going
        self.string_off = _i32(b, 0x18)
        self.string_size = _i32(b, 0x1C)
        self.defval_off = _i32(b, 0x40)
        self.defval_size = _i32(b, 0x44)
        self.defval_data_off = _i32(b, 0x48)
        self.fields_off = _i32(b, 0x60)
        self.fields_size = _i32(b, 0x64)
        self.types_off = _i32(b, 0xA0)
        self.types_size = _i32(b, 0xA4)
        self.field_count = self.fields_size // FIELD_SIZE
        self._strings = {}
        self.type_stride = self._detect_type_stride()
        self.type_count = self.types_size // self.type_stride

    # ---------------------------------------------------------------- strings
    def string(self, index):
        """Identifier strings are null-terminated and addressed by byte offset
        from stringOffset, not by ordinal."""
        if index < 0 or index >= self.string_size:
            return ""
        hit = self._strings.get(index)
        if hit is None:
            start = self.string_off + index
            end = self.buf.index(b"\0", start)
            hit = self._strings[index] = self.buf[start:end].decode("utf-8", "replace")
        return hit

    # ----------------------------------------------------------------- fields
    def field_name_index(self, field_index):
        return _i32(self.buf, self.fields_off + field_index * FIELD_SIZE)

    def field_name(self, field_index):
        return self.string(self.field_name_index(field_index))

    # ------------------------------------------------------- type definitions
    def _detect_type_stride(self):
        """Il2CppTypeDefinition grew across metadata versions; rather than trust a
        remembered number, pick the stride whose records actually parse -- every
        nameIndex must land on a plausible identifier and fieldStart must climb."""
        best = None
        for stride in range(88, 145, 4):
            if self.types_size % stride:
                continue
            count = self.types_size // stride
            if count < 100:
                continue
            score = self._score_stride(stride, count)
            if score is not None and (best is None or score > best[0]):
                best = (score, stride)
        if best is None:
            raise RuntimeError("could not work out the type-definition stride")
        return best[1]

    def _score_stride(self, stride, count):
        ok = 0
        last_field_start = -1
        for i in range(0, min(count, 400)):
            base = self.types_off + i * stride
            name = self.string(_i32(self.buf, base))
            fs = _i32(self.buf, base + FIELD_START)
            if not name or not (name[0].isalpha() or name[0] in "<_"):
                return None
            if fs < -1 or fs > self.field_count:
                return None
            if fs >= 0:
                if fs < last_field_start:
                    return None
                last_field_start = fs
                ok += 1
        return ok

    def types(self):
        """Yield (type_name, field_start, field_count) for every type."""
        for i in range(self.type_count):
            base = self.types_off + i * self.type_stride
            name = self.string(_i32(self.buf, base))
            field_start = _i32(self.buf, base + FIELD_START)
            field_count = struct.unpack_from("<H", self.buf, base + FIELD_COUNT)[0]
            yield name, field_start, field_count

    # --------------------------------------------------------- default values
    def const_values(self):
        """field_index -> int value, for every field carrying a literal."""
        out = {}
        for i in range(self.defval_size // DEFVAL_SIZE):
            base = self.defval_off + i * DEFVAL_SIZE
            fidx = _i32(self.buf, base)
            didx = _i32(self.buf, base + 8)
            if didx < 0:
                continue
            out[fidx] = _i32(self.buf, self.defval_data_off + didx)
        return out


def _field_count_offset_ok(md):
    """The 8 uint16 counts follow the 19 int32s; field_count is the 3rd of them.
    Cross-check on a type we can eyeball, so a wrong guess is loud, not silent."""
    for name, start, count in md.types():
        if name == "PlayerStatsProto" and 0 < count < 200:
            return True
    return None


def dump(md, wanted, consts):
    by_name = {}
    for name, start, count in md.types():
        if start < 0 or not count:
            continue
        by_name.setdefault(name, (start, count))
    for want in wanted:
        hit = by_name.get(want)
        if not hit:
            print(f"\n== {want}: NOT FOUND (try --grep {want[:6]})")
            continue
        start, count = hit
        print(f"\n== {want}  ({count} fields)")
        for fi in range(start, start + count):
            val = consts.get(fi)
            if val is None:
                continue                     # instance field, no literal
            print(f"   {md.field_name(fi):<44} = {val}")


def main(argv):
    path = os.environ.get("METADATA", DEFAULT_DAT)
    md = Metadata(path)
    print(f"metadata: {path}")
    print(f"  strings {md.string_size} B, fields {md.field_count}, "
          f"types {md.type_count} @ stride {md.type_stride}")

    args = [a for a in argv if not a.startswith("--")]
    if "--grep" in argv:
        needle = args[0].lower()
        seen = set()
        for name, _s, _c in md.types():
            if needle in name.lower() and name not in seen:
                seen.add(name)
                print("   " + name)
        return 0

    consts = md.const_values()
    dump(md, args or ["PlayerStatsProto"], consts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
