"""
dupe_test.py — EXPERIMENT: can the 0.29 client render a Pokemon on an id that
does not exist in its baked-in HoloPokemonId enum (1..151)?

Why this exists
---------------
The plan is "shiny = duplicate a model onto a new id and recolor it". The client
picks a model purely from the numeric pokemon_id (build_bundle.py: the bundle is
named pm{id:04d}), so a twin that coexists with the normal species needs its OWN
id -- 152+. But HoloPokemonId is compiled into global-metadata.dat and stops at
151, so an out-of-enum id may be clamped to MISSINGNO, dropped, or ignored.

That is an empirical question, and guessing costs a weekend of metadata surgery.
This harness answers it in one launch.

The trick
---------
pm0152 is a BYTE-IDENTICAL copy of pm0001 (Bulbasaur). Because the bytes are the
same, pm0001's genuine 2016 AES key, checksum, size and version all remain valid,
so we can clone its digest entry under the new bundle name and the client's real
decrypt -> CRC-validate -> load path still passes. No forged crypto, no Unity.
If a Bulbasaur renders while the server says "species 152", the dupe plan works.

Usage
-----
    DUPE_TEST_ID=152 FORCE_POKEMON=152 py run.py

Then walk the phone to a spawn and read server-log.txt. Everything is OFF unless
DUPE_TEST_ID is set, so this cannot affect a normal run.

Reading the result (grep server-log.txt)
----------------------------------------
  "GET_DOWNLOAD_URLS for [... 'pm0152' ...]"  -> client ACCEPTED the id and is
                                                 fetching the model. Dupe plan is
                                                 alive; next step is a real
                                                 template + metadata entry.
  "[asset] SERVING pm0152"                    -> model delivered. If a Bulbasaur
                                                 now appears on the map, the
                                                 client renders out-of-enum ids
                                                 and the plan is CONFIRMED.
  neither line, or a blank/invisible spawn    -> the enum is hard-blocking. Fall
                                                 back to recoloring an existing
                                                 species.
"""
import os
import shutil

TEST_ID = int(os.environ.get("DUPE_TEST_ID", "0"))       # 0 = harness disabled
SRC_ID = int(os.environ.get("DUPE_TEST_SRC", "1"))       # model to clone (1=Bulbasaur)


def enabled():
    return TEST_ID > 0


def _names():
    return f"pm{SRC_ID:04d}", f"pm{TEST_ID:04d}"


def ensure_bundle(assets_dir, plain_dir=None, log=print):
    """Copy pm{SRC} -> pm{TEST} on disk so there is something to serve.

    Byte-identical on purpose: it keeps the source bundle's genuine key/checksum
    valid. The copy is only made if it is missing, so restarts are cheap.
    """
    if not enabled():
        return
    src_name, dst_name = _names()
    for d in filter(None, (assets_dir, plain_dir)):
        src, dst = os.path.join(d, src_name), os.path.join(d, dst_name)
        if not os.path.isfile(src):
            continue
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        try:
            shutil.copyfile(src, dst)
            log(f"[dupe-test] copied {src_name} -> {dst_name} in {os.path.basename(d)}/")
        except OSError as e:
            log(f"[dupe-test] could not copy {src_name} -> {dst_name}: {e}")


def digest_entry(real_digest, plain_manifest=None):
    """A synthetic AssetDigestEntry for pm{TEST}, cloned from pm{SRC}.

    Returns a dict shaped like _our_bundles() entries, or None if the source
    bundle has no genuine digest entry to clone (nothing to fake safely).

    asset_id is set to the bare bundle name so protocol.bundle_path()'s
    basename() fallback resolves it straight to the file we copied above.
    """
    if not enabled():
        return None
    src_name, dst_name = _names()
    m = (real_digest or {}).get(src_name)
    if not m:
        return None
    checksum = m["checksum"]
    if plain_manifest and src_name in plain_manifest:
        # Match whatever the server is actually serving; a decrypted copy has a
        # different CRC than the encrypted original.
        checksum = plain_manifest[src_name]["crc32"]
    return {"asset_id": dst_name, "bundle_name": dst_name,
            "version": m["version"], "checksum": checksum,
            "size": m["size"], "key": m["key"]}
