import sys, re
path = sys.argv[1]
needle = sys.argv[2].encode()
window = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
data = open(path,'rb').read()
i = data.find(needle)
if i < 0:
    print("NOT FOUND"); sys.exit()
chunk = data[i:i+window]
# split into printable ascii runs of length >=2
strs = re.findall(rb'[\x20-\x7e]{2,}', chunk)
for s in strs:
    print(s.decode('ascii','replace'))
