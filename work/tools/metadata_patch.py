"""
Patch il2cpp global-metadata.dat so the string literal "libNianticLabsPlugin.so"
becomes an ABSOLUTE path. This removes the need for any runtime hook (Frida) to
satisfy Android 7+'s System.load absolute-path rule.

Technique: append the longer path bytes at end-of-file and repoint the literal's
(dataIndex, length). il2cpp reads metadata[stringLiteralDataOffset + dataIndex]
for `length` bytes with no bounds check, and loads the whole file into memory, so
pointing past the declared section into our appended bytes works.

Stable path: /data/data/<pkg>/lib is a symlink to the app's native lib dir.
"""
import struct
import sys

SRC = sys.argv[1]
DST = sys.argv[2]
# argv[3] lets us retarget the path when the APK is repackaged under a different
# package name (side-by-side install alongside the official app).
PKG = sys.argv[3] if len(sys.argv) > 3 else "com.nianticlabs.pokemongo"
NEW_PATH = f"/data/data/{PKG}/lib/libNianticLabsPlugin.so".encode()
OLD = b"libNianticLabsPlugin.so"

d = bytearray(open(SRC, "rb").read())
sanity, version = struct.unpack_from("<II", d, 0)
assert sanity == 0xFAB11BAF and version == 21, (hex(sanity), version)

str_lit_off, str_lit_size, sld_off, sld_size = struct.unpack_from("<iiii", d, 8)
print(f"stringLiteral @{str_lit_off} size {str_lit_size} ({str_lit_size//8} entries)")
print(f"stringLiteralData @{sld_off} size {sld_size}")

# rel offset of the old string within stringLiteralData
abs_pos = d.find(OLD, sld_off, sld_off + sld_size)
rel = abs_pos - sld_off
print(f"old string at abs {abs_pos} (rel {rel}), len {len(OLD)}")

# find the StringLiteral entry {uint32 length; int32 dataIndex} pointing there
entry_i = None
for i in range(str_lit_size // 8):
    ln, di = struct.unpack_from("<Ii", d, str_lit_off + i * 8)
    if di == rel and ln == len(OLD):
        entry_i = i
        break
assert entry_i is not None, "literal entry not found"
print(f"literal entry index {entry_i}")

# append new path at EOF; new dataIndex is relative to stringLiteralData
new_di = len(d) - sld_off
d += NEW_PATH
struct.pack_into("<Ii", d, str_lit_off + entry_i * 8, len(NEW_PATH), new_di)
print(f"repointed -> len {len(NEW_PATH)}, dataIndex {new_di}, path={NEW_PATH.decode()}")

open(DST, "wb").write(d)
print(f"wrote {DST} ({len(d)} bytes, +{len(NEW_PATH)})")
