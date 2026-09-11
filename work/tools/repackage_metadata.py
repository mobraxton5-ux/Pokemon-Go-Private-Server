"""Rebuild the APK with the patched global-metadata.dat (an asset). Copies every
other entry verbatim (preserving compression), drops old signature files."""
import sys
import zipfile

SRC_APK = sys.argv[1]
PATCHED_META = sys.argv[2]
OUT_APK = sys.argv[3]
META_ENTRY = "assets/bin/Data/Managed/Metadata/global-metadata.dat"

patched = open(PATCHED_META, "rb").read()
zin = zipfile.ZipFile(SRC_APK, "r")
zout = zipfile.ZipFile(OUT_APK, "w")

skip_sig = (".SF", ".RSA", ".DSA", ".EC")
for item in zin.infolist():
    name = item.filename
    if name.upper().startswith("META-INF/") and (
        name.upper().endswith(skip_sig) or name.upper().endswith("MANIFEST.MF")):
        continue                                   # drop old signature
    data = patched if name == META_ENTRY else zin.read(name)
    # preserve original compression + external attrs
    zi = zipfile.ZipInfo(name, date_time=item.date_time)
    zi.compress_type = item.compress_type
    zi.external_attr = item.external_attr
    zi.internal_attr = item.internal_attr
    zi.create_system = item.create_system
    zout.writestr(zi, data)

zout.close()
zin.close()
print(f"wrote {OUT_APK}")
