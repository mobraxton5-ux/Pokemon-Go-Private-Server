"""
unity_assets.py -- Unity ASSET-level modding for the 0.29 client (Unity 5.3.5f1).

Companion to the code-level tools. This edits the actual Unity SerializedFiles that
ship in the APK/IPA -- textures, sprites, meshes, audio, shaders, GameObjects/prefabs
-- via UnityPy, and handles the Android quirk that every big file is split into 1 MB
`.split*` chunks (iOS keeps them whole).

Files worth editing (iOS names; Android is the same set, split):
  globalgamemanagers            engine managers (PlayerSettings, GraphicsSettings)
  globalgamemanagers.assets     the 20 shaders (incl. Holo/Character), + MonoScripts
  sharedassets0.assets          467 Texture2D + 487 Sprite + all the UI atlases
  resources.assets              751 meshes, 283 AudioClip, 645 Animator, prefabs
  level0..level3                scenes

Commands:
  py unity_assets.py list    <file> [--type Texture2D]     inventory / filter
  py unity_assets.py export  <file> <name> <out.png>       Texture2D -> PNG
  py unity_assets.py replace <file> <name> <in.png> [-o OUT]  edit texture, save file
  py unity_assets.py join    <dir> <base>                  concat Android .split* -> base
  py unity_assets.py split   <file> [--chunk 1048576]      re-split a file for the APK

Android repack flow:  join .split* -> edit the whole file -> split back -> zip into the
APK at assets/bin/Data/<name>.split* -> zipalign + apksigner (your existing keystore).
iOS: edit the whole .assets in place -> repack Payload/.../Data -> re-sign the .app.
UnityPy resolves cross-file refs (e.g. .resS streamed data) when siblings sit in the
same dir, so always edit inside a full copy of Data/.
"""
import os
import sys
import glob


def _load(path):
    import UnityPy
    return UnityPy.load(path)


def cmd_list(args):
    path = args[0]
    want = None
    if "--type" in args:
        want = args[args.index("--type") + 1]
    env = _load(path)
    import collections
    c = collections.Counter()
    rows = []
    for o in env.objects:
        tn = o.type.name
        c[tn] += 1
        if want and tn == want:
            try:
                d = o.read()
                name = getattr(d, "m_Name", "") or ""
                if tn == "Texture2D":
                    rows.append(f"  {d.m_Width}x{d.m_Height:<5} fmt{int(d.m_TextureFormat):<3} {name}")
                else:
                    rows.append(f"  [{tn}] {name}")
            except Exception as e:
                rows.append(f"  [{tn}] <unreadable: {e}>")
    if want:
        print(f"{path}: {c[want]} {want}")
        print("\n".join(rows))
    else:
        for k, v in c.most_common():
            print(f"  {v:6} {k}")


def _find_texture(env, name):
    for o in env.objects:
        if o.type.name == "Texture2D":
            d = o.read()
            if (getattr(d, "m_Name", "") or "") == name:
                return o, d
    return None, None


def cmd_export(args):
    path, name, out = args[0], args[1], args[2]
    env = _load(path)
    o, d = _find_texture(env, name)
    if not d:
        print(f"texture {name!r} not found"); return 1
    img = d.image                      # PIL Image (UnityPy decodes the format)
    img.save(out)
    print(f"exported {name} ({d.m_Width}x{d.m_Height} fmt{int(d.m_TextureFormat)}) -> {out}")


def cmd_replace(args):
    path, name, src = args[0], args[1], args[2]
    out = path
    if "-o" in args:
        out = args[args.index("-o") + 1]
    from PIL import Image
    env = _load(path)
    o, d = _find_texture(env, name)
    if not d:
        print(f"texture {name!r} not found"); return 1
    new = Image.open(src).convert("RGBA")
    d.image = new                      # UnityPy re-encodes to the texture's format
    d.save()                           # write back into the object
    with open(out, "wb") as fh:
        fh.write(env.file.save())      # serialize the whole file
    print(f"replaced {name} <- {src} ({new.width}x{new.height}); wrote {out}")


def cmd_join(args):
    d, base = args[0], args[1]
    parts = sorted(glob.glob(os.path.join(d, base + ".split*")),
                   key=lambda p: int(p.rsplit("split", 1)[1]))
    if not parts:
        print(f"no {base}.split* in {d}"); return 1
    dst = os.path.join(d, base)
    with open(dst, "wb") as out:
        for p in parts:
            out.write(open(p, "rb").read())
    print(f"joined {len(parts)} chunks -> {dst} ({os.path.getsize(dst)} bytes)")


def cmd_split(args):
    path = args[0]
    chunk = 1048576
    if "--chunk" in args:
        chunk = int(args[args.index("--chunk") + 1])
    data = open(path, "rb").read()
    n = 0
    for i in range(0, len(data), chunk):
        with open(f"{path}.split{n}", "wb") as fh:
            fh.write(data[i:i + chunk])
        n += 1
    print(f"split {path} -> {n} chunks of <= {chunk} bytes")


CMDS = {"list": cmd_list, "export": cmd_export, "replace": cmd_replace,
        "join": cmd_join, "split": cmd_split}


def main(argv):
    if not argv or argv[0] not in CMDS:
        print(__doc__); return 2
    return CMDS[argv[0]](argv[1:]) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
