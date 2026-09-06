"""
build_bundle.py — synthesize a Pokemon-GO-0.29 asset bundle (pm####) WITHOUT Unity.

The 0.29 client (Unity 5.3.5f1) downloads each Pokemon's model as an AssetBundle named
`pm{N:0000}` and instantiates the prefab `pm{N:0000}_00_Rig` from it (see
memory: pogo-asset-contract). No 5.3.5 Unity editor and no preserved bundle are needed:
we assemble a self-contained UnityFS bundle straight from the APK's own 5.3.5 objects
using UnityPy (read/modify/inject) + UnityPy's bundled TPK typetree database.

Pipeline (all validated):
  1. Base = the APK's egg SerializedFile (03a831ef9a53...) — a real 5.3.5 file UnityPy
     fully round-trips. We clear its objects and inject our own.
  2. Structural template = the `BlobShadow` GameObject in sharedassets0 (a static
     GameObject + Transform + MeshFilter + MeshRenderer cluster).
  3. Geometry = the egg mesh (sharedassets0 path 667, inline vertex data, 1087 verts).
  4. Material = a cloned material with its shader nulled (Unity's error/"magenta" shader
     renders => visible proof) and external texture refs cleared -> self-contained.
  5. AssetBundle(142) manifest = built from the TPK typetree for 5.3.5, mapping
     `pm{N:0000}_00_rig` -> the prefab GameObject.
  6. Wrap the SerializedFile in an uncompressed UnityFS container (client loads it via the
     standard AssetBundle.LoadFromFile path).

Output: <out_dir>/pm{N:0000}  (a bundle file, no extension, matching the cache/CDN name).

NOTE: rendering is still to be confirmed on-device. Open unknowns (resolve on the phone):
the exact on-device cache dir/filename, whether a null-shader material renders as expected
from a bundle, and whether the client's LoadAsset key matches our container key exactly.
"""
import argparse
import copy
import glob
import hashlib
import io
import os
import struct

import UnityPy
from UnityPy.helpers import Tpk

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                       # work/
DATA = os.path.join(REPO, "extracted", "assets", "bin", "Data")
EGG_PREFIX = "03a831ef9a53"                        # HoloCharacterPrefabs/Eggs/Egg0001 bundle
EGG_MESH_PID = 667                                 # egg_default_rig mesh in sharedassets0

# Unity class ids
CID_GAMEOBJECT, CID_TRANSFORM = 1, 4
CID_MESHRENDERER, CID_MESHFILTER = 23, 33
CID_MATERIAL, CID_MESH, CID_ASSETBUNDLE = 21, 43, 142

# local path_ids in the output file
AB, GO, TF, MF, MR, MESH, MAT = 1, 2, 3, 4, 5, 6, 7


def reassemble_sharedassets0(cache_dir):
    """sharedassets0.assets ships split into .split0..N; concat in numeric order."""
    out = os.path.join(cache_dir, "sharedassets0.assets")
    if os.path.exists(out) and os.path.getsize(out) > 60_000_000:
        return out
    splits = sorted(
        glob.glob(os.path.join(DATA, "sharedassets0.assets.split*")),
        key=lambda p: int(p.rsplit("split", 1)[1]),
    )
    if not splits:
        raise SystemExit("sharedassets0 splits not found under " + DATA)
    with open(out, "wb") as fh:
        for s in splits:
            fh.write(open(s, "rb").read())
    return out


def _clone(src_obj, new_pid, class_id, target_file):
    c = copy.copy(src_obj)
    c.path_id = new_pid
    c.class_id = class_id
    c.type_id = class_id
    c.assets_file = target_file
    return c


def build_pm_bundle(pokemon_id, out_dir, cache_dir):
    name = f"pm{pokemon_id:04d}"                    # pm0001
    prefab = f"{name}_00_Rig"                        # pm0001_00_Rig
    container_key = prefab.lower()                   # pm0001_00_rig

    egg_path = next(f for f in glob.glob(os.path.join(DATA, "*"))
                    if os.path.basename(f).startswith(EGG_PREFIX))
    env = UnityPy.load(egg_path)
    sf = env.file
    ver = sf.version

    sa = UnityPy.load(reassemble_sharedassets0(cache_dir))
    sa_objs = {o.path_id: o for o in sa.objects}

    # --- structural template: the BlobShadow static-mesh cluster ---
    blob_go = next(o for o in sa.objects
                   if o.type.name == "GameObject"
                   and o.read_typetree().get("m_Name") == "BlobShadow")
    comp = {cid: p["m_PathID"] for cid, p in blob_go.read_typetree()["m_Component"]}
    tf_src, mf_src, mr_src = comp[CID_TRANSFORM], comp[CID_MESHFILTER], comp[CID_MESHRENDERER]
    mat_src = sa_objs[mr_src].read_typetree()["m_Materials"][0]["m_PathID"]

    # --- Mesh: raw byte-copy of the egg mesh (self-contained, no PPtrs inside) ---
    mesh = _clone(sa_objs[EGG_MESH_PID], MESH, CID_MESH, sf)
    mesh.set_raw_data(sa_objs[EGG_MESH_PID].get_raw_data())

    # --- GameObject prefab ---
    go = _clone(blob_go, GO, CID_GAMEOBJECT, sf)
    t = blob_go.read_typetree()
    t["m_Name"] = prefab
    t["m_Layer"] = 0
    t["m_Component"] = [
        [CID_TRANSFORM,    {"m_FileID": 0, "m_PathID": TF}],
        [CID_MESHFILTER,   {"m_FileID": 0, "m_PathID": MF}],
        [CID_MESHRENDERER, {"m_FileID": 0, "m_PathID": MR}],
    ]
    go.save_typetree(t)

    # --- Transform (identity, root) ---
    tf = _clone(sa_objs[tf_src], TF, CID_TRANSFORM, sf)
    t = sa_objs[tf_src].read_typetree()
    t["m_GameObject"] = {"m_FileID": 0, "m_PathID": GO}
    t["m_Father"] = {"m_FileID": 0, "m_PathID": 0}
    t["m_Children"] = []
    t["m_LocalPosition"] = {"x": 0.0, "y": 0.0, "z": 0.0}
    t["m_LocalRotation"] = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    t["m_LocalScale"] = {"x": 1.0, "y": 1.0, "z": 1.0}
    tf.save_typetree(t)

    # --- MeshFilter -> our mesh ---
    mf = _clone(sa_objs[mf_src], MF, CID_MESHFILTER, sf)
    t = sa_objs[mf_src].read_typetree()
    t["m_GameObject"] = {"m_FileID": 0, "m_PathID": GO}
    t["m_Mesh"] = {"m_FileID": 0, "m_PathID": MESH}
    mf.save_typetree(t)

    # --- MeshRenderer -> our material ---
    mr = _clone(sa_objs[mr_src], MR, CID_MESHRENDERER, sf)
    t = sa_objs[mr_src].read_typetree()
    t["m_GameObject"] = {"m_FileID": 0, "m_PathID": GO}
    t["m_Materials"] = [{"m_FileID": 0, "m_PathID": MAT}]
    mr.save_typetree(t)

    # --- Material: null shader (error shader = visible) + drop external tex refs ---
    mat = _clone(sa_objs[mat_src], MAT, CID_MATERIAL, sf)
    t = sa_objs[mat_src].read_typetree()
    t["m_Name"] = f"{name}_mat"
    t["m_Shader"] = {"m_FileID": 0, "m_PathID": 0}
    for te in t.get("m_SavedProperties", {}).get("m_TexEnvs", []):
        tv = te[1] if isinstance(te, (list, tuple)) else te
        if isinstance(tv, dict) and "m_Texture" in tv:
            tv["m_Texture"] = {"m_FileID": 0, "m_PathID": 0}
    mat.save_typetree(t)

    # --- AssetBundle manifest (typetree from TPK for this exact engine version) ---
    ab_node = Tpk.get_typetree_node(CID_ASSETBUNDLE, ver)
    manifest = {
        "m_Name": name,
        "m_PreloadTable": [{"m_FileID": 0, "m_PathID": p} for p in (GO, TF, MF, MR, MESH, MAT)],
        "m_Container": [[container_key,
                         {"preloadIndex": 0, "preloadSize": 6,
                          "asset": {"m_FileID": 0, "m_PathID": GO}}]],
        "m_MainAsset": {"preloadIndex": 0, "preloadSize": 0,
                        "asset": {"m_FileID": 0, "m_PathID": 0}},
        "m_RuntimeCompatibility": 1,
        "m_AssetBundleName": name,
        "m_Dependencies": [],
        "m_IsStreamedSceneAssetBundle": False,
    }
    ab = _clone(blob_go, AB, CID_ASSETBUNDLE, sf)
    ab.save_typetree(manifest, nodes=ab_node)

    # --- rebuild the file with only our objects; drop the egg's externals ---
    sf.objects.clear()
    for o in (ab, go, tf, mf, mr, mesh, mat):
        sf.objects[o.path_id] = o
    sf.externals = []
    sf.mark_changed()

    serialized = sf.save()
    bundle = pack_unityfs(serialized, cab="CAB-" + hashlib.md5(name.encode()).hexdigest())

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name)
    with open(out, "wb") as fh:
        fh.write(bundle)
    return out, container_key, prefab


def _cstr(s):
    return s.encode("utf-8") + b"\x00"


def pack_unityfs(serialized, engine="5.3.5f1", player="5.x.x", cab="CAB-pm"):
    """Minimal uncompressed UnityFS (format v6) wrapping one serialized file."""
    bi = io.BytesIO()
    bi.write(b"\x00" * 16)                              # uncompressedDataHash
    bi.write(struct.pack(">i", 1))                      # blocksInfoCount
    bi.write(struct.pack(">I", len(serialized)))        # block uncompressedSize
    bi.write(struct.pack(">I", len(serialized)))        # block compressedSize
    bi.write(struct.pack(">H", 0))                      # block flags (uncompressed)
    bi.write(struct.pack(">i", 1))                      # nodesCount
    bi.write(struct.pack(">q", 0))                      # node offset
    bi.write(struct.pack(">q", len(serialized)))        # node size
    bi.write(struct.pack(">I", 4))                      # node flags (4 = serialized file)
    bi.write(_cstr(cab))                                # node path (CAB-...)
    blocks_info = bi.getvalue()

    flags = 0x40                                        # combined info, uncompressed, not-at-end
    head = _cstr("UnityFS") + struct.pack(">I", 6) + _cstr(player) + _cstr(engine)
    tail = (struct.pack(">I", len(blocks_info)) +       # compressedBlocksInfoSize
            struct.pack(">I", len(blocks_info)) +       # uncompressedBlocksInfoSize
            struct.pack(">I", flags))
    total = len(head) + 8 + len(tail) + len(blocks_info) + len(serialized)
    return head + struct.pack(">q", total) + tail + blocks_info + serialized


def verify(path, container_key):
    env = UnityPy.load(path)
    f0 = list(env.files.values())[0]
    sig = getattr(f0, "signature", type(f0).__name__)
    objs = {o.path_id: o.type.name for o in env.objects}
    ab = next(o for o in env.objects if o.type.name == "AssetBundle").read_typetree()
    mesh = next(o for o in env.objects if o.type.name == "Mesh").read_typetree()
    verts = mesh.get("m_VertexData", {}).get("m_VertexCount")
    ok = (sig == "UnityFS"
          and set(objs.values()) >= {"AssetBundle", "GameObject", "MeshFilter",
                                     "MeshRenderer", "Mesh", "Material", "Transform"}
          and ab["m_Container"] and ab["m_Container"][0][0] == container_key)
    print(f"  signature={sig}  objects={objs}")
    print(f"  container={ab['m_Container']}")
    print(f"  mesh='{mesh.get('m_Name')}' verts={verts}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Build a pm#### Pokemon GO 0.29 asset bundle (no Unity).")
    ap.add_argument("pokemon_id", nargs="?", type=int, default=1, help="Pokedex number (default 1)")
    ap.add_argument("--out", default=os.path.join(REPO, "server", "assets"), help="output dir")
    ap.add_argument("--cache", default=os.path.join(HERE, "_bundle_cache"), help="scratch dir for reassembled sharedassets0")
    args = ap.parse_args()

    os.makedirs(args.cache, exist_ok=True)
    out, key, prefab = build_pm_bundle(args.pokemon_id, args.out, args.cache)
    print(f"built {out}  ({os.path.getsize(out)} bytes)  prefab={prefab}")
    print("verifying (reload as bundle):")
    print("  OK" if verify(out, key) else "  FAILED")


if __name__ == "__main__":
    main()
