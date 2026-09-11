import re
data = open("extracted/lib/armeabi-v7a/libNianticLabsPlugin.so","rb").read()
seen=set()
for m in re.finditer(rb'([\x20-\x7e]{2,40})\.proto', data):
    start=m.start(1); name=m.group(0)
    # length-delimited string marker: byte before name = len, byte before that = 0x0A
    if start>=2 and data[start-2]==0x0A and data[start-1]==len(name):
        tag="<-- FileDescriptorProto.name marker (0x0A)"
    elif start>=1 and data[start-1]==len(name):
        tag="(len-prefixed, no 0x0A)"
    else:
        tag=""
    key=name
    if key in seen: continue
    seen.add(key)
    print(f"off={m.start():#x} len={len(name)} name={name.decode()!r} prev2={data[max(0,start-2):start].hex()} {tag}")
