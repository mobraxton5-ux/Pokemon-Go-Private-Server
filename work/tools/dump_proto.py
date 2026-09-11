import sys
from google.protobuf import descriptor_pb2

path = sys.argv[1]
targets = sys.argv[2].split(",")  # proto filenames of interest
want_msgs = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
data = open(path, "rb").read()

def marker(name):
    nb = name.encode()
    return bytes([0x0A, len(nb)]) + nb

TYPE = {v: k for k, v in descriptor_pb2.FieldDescriptorProto.Type.items()}
LABEL = {v: k for k, v in descriptor_pb2.FieldDescriptorProto.Label.items()}

for proto in targets:
    mk = marker(proto)
    i = data.find(mk)
    if i < 0:
        print(f"[{proto}] NOT FOUND"); continue
    # grow window to next .proto marker (rough end bound), cap 200KB
    end = data.find(b".proto", i + len(mk) + 4)
    end = min(len(data), (end if end > 0 else i + 200000) + 200000)
    window = data[i:end]
    # trim from end until it parses
    fdp = None
    hi = len(window)
    while hi > len(mk):
        try:
            cand = descriptor_pb2.FileDescriptorProto()
            cand.ParseFromString(window[:hi])
            if cand.name == proto:
                fdp = cand; break
        except Exception:
            pass
        hi -= 1
    if fdp is None:
        print(f"[{proto}] could not parse"); continue
    print(f"\n========== {fdp.name}  (package={fdp.package}) ==========")
    for m in fdp.message_type:
        if want_msgs and m.name not in want_msgs:
            continue
        print(f"\nmessage {m.name} {{")
        for f in m.field:
            t = TYPE.get(f.type, str(f.type)).replace("TYPE_", "").lower()
            tn = f.type_name if f.type_name else t
            lab = LABEL.get(f.label, "").replace("LABEL_", "").lower()
            lab = "" if lab == "optional" else lab + " "
            print(f"    {lab}{tn} {f.name} = {f.number};")
        for e in m.enum_type:
            print(f"    enum {e.name} {{ " + ", ".join(f'{v.name}={v.number}' for v in e.value[:6]) + (" ..." if len(e.value)>6 else "") + " }")
        print("}")
