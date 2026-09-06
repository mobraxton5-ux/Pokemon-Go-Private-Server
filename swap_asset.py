"""Swap one file inside an APK, dropping the old signature.

APK Editor Studio can only edit res/ drawables, not files under assets/ -- and
the Unity splash lives at assets/bin/Data/splash.png. This replaces ANY single
entry in the APK zip with a file from disk, preserving every other entry (and its
compression) verbatim, then drops the old META-INF signature so the result can be
re-aligned + re-signed.

Usage:
  py swap_asset.py <src.apk> <entry/path/in/apk> <newfile> <out.apk>
Example (the splash):
  py swap_asset.py in.apk assets/bin/Data/splash.png mysplash.png out-unsigned.apk

Then:  zipalign -p -f 4 out-unsigned.apk out-aligned.apk
       apksigner sign --ks pogo.keystore --ks-pass pass:android out-aligned.apk
"""
import sys
import zipfile

if len(sys.argv) != 5:
    print(__doc__)
    raise SystemExit(1)

SRC_APK, ENTRY, NEWFILE, OUT_APK = sys.argv[1:5]
new_data = open(NEWFILE, "rb").read()

zin = zipfile.ZipFile(SRC_APK, "r")
if ENTRY not in zin.namelist():
    raise SystemExit(f"entry not found in APK: {ENTRY}\n"
                     f"(check the exact path; it is case-sensitive)")

zout = zipfile.ZipFile(OUT_APK, "w")
skip_sig = (".SF", ".RSA", ".DSA", ".EC")
replaced = False
for item in zin.infolist():
    name = item.filename
    up = name.upper()
    if up.startswith("META-INF/") and (up.endswith(skip_sig)
                                        or up.endswith("MANIFEST.MF")):
        continue                                   # drop old signature
    if name == ENTRY:
        data = new_data
        replaced = True
    else:
        data = zin.read(name)
    zi = zipfile.ZipInfo(name, date_time=item.date_time)
    zi.compress_type = item.compress_type          # keep per-entry compression
    zi.external_attr = item.external_attr
    zi.internal_attr = item.internal_attr
    zi.create_system = item.create_system
    zout.writestr(zi, data)
zout.close()
zin.close()

print(f"{'replaced' if replaced else 'DID NOT replace'} {ENTRY} "
      f"({len(new_data)} bytes) -> {OUT_APK}")
