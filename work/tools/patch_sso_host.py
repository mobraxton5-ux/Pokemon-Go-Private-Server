"""
Repoint the client's PTC login URLs off sso.pokemon.com.

Why: the login URLs are the only ones that hardcode a *pokemon.com* host, and
that hostname is the one a phone's network keeps resolving to the real Niantic
servers -- a second resolver (the router's IPv6 one), a cached record, or an
encrypted-DNS mode all win the race, and the game then talks TLS to Niantic,
which refuses a 2016 client. The symptom is "unable to authenticate" with
nothing whatsoever in the server log. Meanwhile pgorelease.nianticlabs.com
resolves to our server perfectly reliably on the same phone at the same moment
-- the shop and the Help Center run over it.

So: rewrite the five SSO URLs to use pgorelease.nianticlabs.com, keeping their
/sso/... paths. server.py routes anything starting with /sso to the PTC handler
regardless of host, so both the patched and the original client work.

Same technique as metadata_patch.py: append the new string at end-of-file and
repoint the literal's (length, dataIndex). il2cpp doesn't bounds-check that
index and loads the whole file, so the new bytes can live past the declared
section and be longer than the original.

    py patch_sso_host.py <in.dat> <out.dat> [new-host]
"""
import struct
import sys

SRC = sys.argv[1]
DST = sys.argv[2]
NEW_HOST = (sys.argv[3] if len(sys.argv) > 3 else "pgorelease.nianticlabs.com").encode()
OLD_HOST = b"sso.pokemon.com"

d = bytearray(open(SRC, "rb").read())
sanity, version = struct.unpack_from("<II", d, 0)
assert sanity == 0xFAB11BAF and version == 21, (hex(sanity), version)

str_lit_off, str_lit_size, sld_off, sld_size = struct.unpack_from("<iiii", d, 8)
count = str_lit_size // 8
print(f"{count} string literals, data section {sld_size} bytes")

patched = 0
for i in range(count):
    ln, di = struct.unpack_from("<Ii", d, str_lit_off + i * 8)
    if ln <= 0 or di < 0 or di + ln > sld_size:
        continue
    start = sld_off + di
    s = bytes(d[start:start + ln])
    if OLD_HOST not in s:
        continue
    # Only the URLs. The bare hostname on its own is used for cookie/domain
    # comparisons, and rewriting that would break matching rather than fix it.
    if not s.startswith(b"http"):
        print(f"  [skip] not a URL: {s[:60]!r}")
        continue
    new = s.replace(OLD_HOST, NEW_HOST)
    new_di = len(d) - sld_off              # append at EOF, index past the section
    d += new
    struct.pack_into("<Ii", d, str_lit_off + i * 8, len(new), new_di)
    patched += 1
    print(f"  [{i}] {s.decode(errors='replace')[:72]}")
    print(f"       -> {new.decode(errors='replace')[:72]}")

assert patched, "no SSO URLs found -- wrong file?"
open(DST, "wb").write(d)
print(f"\npatched {patched} URL(s); wrote {DST} ({len(d)} bytes)")
