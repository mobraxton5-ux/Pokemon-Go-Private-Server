"""
Decrypt a Pokemon GO 0.29/0.35-era asset bundle (the encrypted pm#### files the
client downloads via GET_DOWNLOAD_URLS) into a plain Unity 5.x `UnityFS` bundle.

We normally DON'T need this: the server serves the encrypted bytes verbatim and
the client decrypts them itself using the per-bundle key from the asset digest.
This tool is for (a) confirming a bundle is genuine/decryptable offline, and
(b) the alternate path of pushing an already-decrypted bundle straight into the
on-device Unity cache (skips the client's crypto entirely).

Algorithm (reverse-engineered; confirmed against the shipped 2016 bundles):
  encrypted file layout:
      [0]        version byte (0x01)
      [1:17]     AES-128-CBC IV (16 bytes)
      [17:-20]   ciphertext (AES-128-CBC, PKCS7 padding)
      [-20:]     HMAC-SHA1 trailer (integrity; not needed to decrypt)
  AES key = digest_key(16 bytes)  XOR  KEY_MASK(16 bytes)
      KEY_MASK = b"PFAi$;]G7Rg>kz4w"  (\x50\x46...\x34\x77)
  -> AES-128-CBC decrypt, strip PKCS7 -> the plaintext is a `UnityFS` bundle whose
     header declares its own exact size.

Note: AssetDigestEntry.checksum (field 4) is NOT a standard CRC32 of either the
decrypted or the encrypted bytes -- it's a client-internal checksum. We never
recompute it; the server passes the genuine digest value through unchanged.

Usage:
    py work/tools/decrypt_bundle.py pm0001
    py work/tools/decrypt_bundle.py pm0025 --assets DIR --out OUT.bundle
Requires: pycryptodome  (py -m pip install pycryptodome)
"""
import os
import sys
import struct

from Crypto.Cipher import AES

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASSETS = os.path.join(HERE, "..", "server", "assets")
KEY_MASK = b"\x50\x46\x41\x69\x24\x3B\x5D\x47\x37\x52\x67\x3E\x6B\x7A\x34\x77"

# reuse the server's tiny protobuf codec to read the digest
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import pb  # noqa: E402


def digest_key(assets_dir, bundle_name):
    """Look up a bundle's 16-byte key from assets/asset_digest."""
    path = os.path.join(assets_dir, "asset_digest")
    with open(path, "rb") as fh:
        data = fh.read()
    for raw in pb.get_all(pb.decode(data), 1):
        e = pb.decode(raw)
        if pb.get(e, 2, pb.WT_LEN) == bundle_name.encode():
            return pb.get(e, 6, pb.WT_LEN)
    raise KeyError(f"{bundle_name} not in {path}")


def decrypt(enc_bytes, key16):
    """Encrypted bundle bytes -> plaintext UnityFS bundle bytes."""
    aes_key = bytes(a ^ b for a, b in zip(key16, KEY_MASK))
    iv, ct = enc_bytes[1:17], enc_bytes[17:-20]
    pt = AES.new(aes_key, AES.MODE_CBC, iv).decrypt(ct)
    pad = pt[-1]
    if 1 <= pad <= 16 and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


def unityfs_size(pt):
    """Total bundle size declared in the UnityFS header (sanity check)."""
    o = 12                                   # after "UnityFS\0" + int32 format
    for _ in range(2):                       # skip unityVersion + unityRevision strings
        while pt[o]:
            o += 1
        o += 1
    return struct.unpack(">q", pt[o:o + 8])[0]


def main(argv):
    name = argv[0] if argv else "pm0001"
    assets = DEFAULT_ASSETS
    out = None
    i = 1
    while i < len(argv):
        if argv[i] == "--assets":
            assets = argv[i + 1]; i += 2
        elif argv[i] == "--out":
            out = argv[i + 1]; i += 2
        else:
            i += 1
    enc = open(os.path.join(assets, name), "rb").read()
    key = digest_key(assets, name)
    pt = decrypt(enc, key)
    magic = pt[:8]
    declared = unityfs_size(pt) if magic.startswith(b"UnityFS") else -1
    ok = magic.startswith(b"UnityFS") and declared == len(pt)
    print(f"{name}: enc={len(enc)}B key={key.hex()} -> dec={len(pt)}B "
          f"magic={magic!r} declared_size={declared} {'OK' if ok else 'CHECK'}")
    if out is None:                          # keep decrypted files OUT of assets/
        out = os.path.join(HERE, name + ".decrypted.bundle")
    with open(out, "wb") as fh:
        fh.write(pt)
    print("wrote", out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
