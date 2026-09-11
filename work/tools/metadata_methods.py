"""
metadata_methods.py -- list a class's METHODS straight out of global-metadata.dat
(v21), the companion to metadata_fields.py (which does fields/enums).

Why this exists: the 0.29 client is Unity 5.3.5f1 / IL2CPP, so there is no C# DLL
to decompile -- the C# was compiled to native code in libil2cpp.so (Android) /
the Mach-O (iOS). But every method name still lives in global-metadata.dat, keyed
to a type. So we can enumerate exactly which methods a class has, and the global
method index that indexes the binary's Il2CppCodeRegistration.methodPointers[]
array -- i.e. the number you use to find the function's address for Ghidra/IDA.

This does NOT need the binary and needs no third-party tool. For the address of a
method (to open it in a disassembler) you still need libil2cpp.so; see the note at
the bottom -- that mapping is what Il2CppDumper/Il2CppInspector automate.

Layout (v21, cross-checked against metadata_fields.py's stride auto-detect):
  header 0x30 methodsOffset / 0x34 methodsSize   Il2CppMethodDefinition = 56 B
  method record: nameIndex@0 declaringType@4 returnType@8 parameterStart@12 (int32)
  Il2CppTypeDefinition (120 B): methodStart int32 @+68, method_count uint16 @+96
    (both confirmed here: methodStart back-refs declaringType 642/642; the count
     block gives declaringType==i for methods[start..start+count) 941/941.)

Usage:
    py metadata_methods.py AssetDecoder
    py metadata_methods.py --grep Bundle        # methods whose name matches
    py metadata_methods.py --type Decoder       # type names matching, then dump each
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metadata_fields import Metadata, _i32          # reuse the proven parser

METHODS_OFF_HDR = 0x30          # methodsOffset in the v21 header
METHOD_SIZE = 56                # Il2CppMethodDefinition (v21)
M_NAME, M_DECL, M_RET, M_PARAM_START = 0, 4, 8, 12
TYPE_METHOD_START = 68          # int32 in Il2CppTypeDefinition
TYPE_METHOD_COUNT = 96          # uint16


class Methods:
    def __init__(self, md: Metadata):
        self.md = md
        b = md.buf
        self.off = _i32(b, METHODS_OFF_HDR)
        self.size = _i32(b, METHODS_OFF_HDR + 4)
        self.count = self.size // METHOD_SIZE
        assert self.size % METHOD_SIZE == 0, "method stride mismatch (not v21?)"

    def _f(self, method_index, field_off):
        return _i32(self.md.buf, self.off + method_index * METHOD_SIZE + field_off)

    def name(self, i):
        return self.md.string(self._f(i, M_NAME))

    def declaring_type(self, i):
        return self._f(i, M_DECL)

    def param_start(self, i):
        return self._f(i, M_PARAM_START)

    def param_count(self, i):
        """Derive from the gap to the next method's parameterStart -- more robust
        than guessing the uint16 slot, and correct because parameters are stored
        contiguously in method order."""
        if i + 1 < self.count:
            nxt = self.param_start(i + 1)
            cur = self.param_start(i)
            if nxt >= cur:
                return nxt - cur
        return 0

    def of_type(self, type_index):
        b = self.md.buf
        base = self.md.types_off + type_index * self.md.type_stride
        start = _i32(b, base + TYPE_METHOD_START)
        cnt = struct.unpack_from("<H", b, base + TYPE_METHOD_COUNT)[0]
        if start < 0:
            return []
        return list(range(start, start + cnt))


def type_index_of(md, name):
    for i in range(md.type_count):
        base = md.types_off + i * md.type_stride
        if md.string(_i32(md.buf, base)) == name:
            return i
    return None


def dump_type(md, methods, name):
    ti = type_index_of(md, name)
    if ti is None:
        print(f"\n== {name}: NOT FOUND (try --type {name[:6]})")
        return
    idxs = methods.of_type(ti)
    print(f"\n== {name}  (type #{ti}, {len(idxs)} methods)")
    for mi in idxs:
        # #mi is the global method index -- it indexes the binary's
        # Il2CppCodeRegistration.methodPointers[] array, i.e. the number you use
        # to recover the function's address for Ghidra/IDA.
        print(f"   #{mi:<6} {methods.name(mi)}")


def main(argv):
    path = os.environ.get("METADATA")
    if not path:
        # same default the sibling tool uses
        from metadata_fields import DEFAULT_DAT
        path = DEFAULT_DAT
    md = Metadata(path)
    methods = Methods(md)
    print(f"metadata: {path}")
    print(f"  types {md.type_count}, methods {methods.count} @ stride {METHOD_SIZE}")

    args = [a for a in argv if not a.startswith("--")]

    if "--grep" in argv:
        needle = args[0].lower()
        seen = set()
        for mi in range(methods.count):
            nm = methods.name(mi)
            if needle in nm.lower():
                dt = methods.declaring_type(mi)
                base = md.types_off + dt * md.type_stride
                cls = md.string(_i32(md.buf, base)) if 0 <= dt < md.type_count else "?"
                key = (cls, nm)
                if key in seen:
                    continue
                seen.add(key)
                print(f"   #{mi:<6} {cls}::{nm}")
        return 0

    if "--type" in argv:
        needle = args[0].lower()
        hits = []
        for i in range(md.type_count):
            base = md.types_off + i * md.type_stride
            nm = md.string(_i32(md.buf, base))
            if needle in nm.lower() and nm not in hits:
                hits.append(nm)
        for nm in hits:
            dump_type(md, methods, nm)
        return 0

    for want in (args or ["AssetDecoder"]):
        dump_type(md, methods, want)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
