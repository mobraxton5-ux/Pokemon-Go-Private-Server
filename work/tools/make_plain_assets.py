"""
Pre-decrypt every pm#### bundle into work/server/assets_plain/ and write a
sidecar manifest (bundle -> decrypted size + CRC32).

Why: the client downloads our encrypted bundles fine (confirmed: 43 cached
on-device, byte-identical to ours) but never renders the model -- so it is
failing somewhere in decrypt/validate. Serving already-decrypted bundles with an
EMPTY digest key (which tells the client "no decryption needed") and a checksum
we compute ourselves takes both of those steps out of the picture.

Doing it here, offline, means the server needs no crypto library at runtime and
PyInstaller has nothing extra to bundle.

Run:  py work/tools/make_plain_assets.py
"""
import json
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "server", "assets")
DST = os.path.join(HERE, "..", "server", "assets_plain")

sys.path.insert(0, HERE)
from decrypt_bundle import decrypt, digest_key, unityfs_size  # noqa: E402


def main():
    os.makedirs(DST, exist_ok=True)
    manifest = {}
    ok = bad = 0
    for fn in sorted(os.listdir(SRC)):
        if not fn.startswith("pm"):
            continue
        enc = open(os.path.join(SRC, fn), "rb").read()
        try:
            pt = decrypt(enc, digest_key(SRC, fn))
        except Exception as e:
            print(f"  {fn}: decrypt FAILED {e}")
            bad += 1
            continue
        if not pt.startswith(b"UnityFS") or unityfs_size(pt) != len(pt):
            print(f"  {fn}: not a clean UnityFS bundle")
            bad += 1
            continue
        open(os.path.join(DST, fn), "wb").write(pt)
        manifest[fn] = {"size": len(pt), "crc32": zlib.crc32(pt) & 0xFFFFFFFF}
        ok += 1
    with open(os.path.join(DST, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"decrypted {ok} bundles ({bad} failed) -> {os.path.abspath(DST)}")
    if manifest:
        k = sorted(manifest)[0]
        print(f"  e.g. {k}: {manifest[k]['size']} B, crc32={manifest[k]['crc32']:08x}")


if __name__ == "__main__":
    raise SystemExit(main())
