# PoGO 0.29 private server — milestone 1: login

Personal/offline server for Pokémon GO **0.29.0**. This milestone gets you
**past the login screen with just a username** (any password), straight onto
the map, with no Niantic/Google account.

> Personal, offline, single-player use only. Don't distribute a patched client
> or host this publicly.

## What's here

| File | Role |
|------|------|
| `pb.py` | tiny protobuf codec + generic decoder/logger (no protoc needed) |
| `protocol.py` | field-number map + response builders (PlayerData, envelope, auth ticket) |
| `sso.py` | fake PTC SSO (`sso.pokemon.com`) — accepts any username/password |
| `rpc.py` | game RPC (`pgorelease.nianticlabs.com/plfe/rpc`) — answers GET_PLAYER |
| `server.py` | one HTTPS listener, routes by Host header |
| `gen_certs.py` | makes `certs/ca.crt` (install on device) + server cert |
| `test_login.py` | end-to-end login test, no device needed |

The username you type on the PTC login screen becomes your in-game trainer
name. We mark the tutorial as already complete so the client skips straight to
the map.

## How it works

1. **PTC login is faked.** The client's CAS/OAuth flow
   (`/sso/login` → `/sso/oauth2.0/accessToken` → `/sso/oauth2.0/profile`) is
   answered with a token that *embeds the username*. Any credentials pass.
2. **RPC handshake.** First call to `/plfe/rpc` returns status `53` (redirect)
   with an `api_url`; the client re-sends to it; we return status `2` with an
   `auth_ticket` and a `GET_PLAYER` response naming you. Other startup requests
   get empty responses for now (enough to reach the map).

## Run it

```sh
py gen_certs.py        # once — creates certs/
py server.py           # listens on 0.0.0.0:443  (run as admin/root for :443)
# local smoke test, no device:
PORT=8443 py server.py            # terminal A
USERNAME=YourName PORT=8443 py test_login.py   # terminal B
```

## Point the real client at it

The endpoints are hardcoded in the client, so we redirect the hostnames to this
PC and make the client trust our TLS. **No APK patching needed** — 0.29 targets
Android 4.4–6, which trust user-installed CAs by default.

**1. Pick where to run the game.** The APK is `armeabi-v7a` only, so you need
ARM support: a real Android 5/6 phone, or an emulator with ARM translation
(NoxPlayer / MEmu / Genymotion-with-ARM). A plain x86 AVD won't load the libs.

**2. Redirect the hostnames to this PC's LAN IP** (`ipconfig` to find it, e.g.
`192.168.1.50`). Point all of these at it:
```
sso.pokemon.com
pgorelease.nianticlabs.com
holo.nianticlabs.com
www.nianticlabs.com
```
Easiest options:
- **Device with root / emulator:** edit `/system/etc/hosts`.
- **No root:** run a tiny DNS server on this PC (e.g. `dnsmasq`/`Acrylic`/`CoreDNS`)
  that answers those names with this PC's IP, then set the device's Wi-Fi DNS to
  this PC. (Quick `dnsmasq` config provided below.)

**3. Install the CA.** Copy `certs/ca.crt` to the device and install it
(Settings → Security → *Install from storage* / *Trusted credentials → User*).
On Android ≤6 the app will trust it automatically.

**4. Run the server on this PC** on port 443 (must be 443 — that's where the
client connects):
```sh
py server.py
```

**5. Launch Pokémon GO**, choose **Pokémon Trainer Club**, type any username +
any password → you should land on the map as that trainer. Watch `server.py`'s
console: every request is logged, and the first few RequestEnvelopes are dumped
field-by-field.

### Minimal dnsmasq example
```
address=/sso.pokemon.com/192.168.1.50
address=/pgorelease.nianticlabs.com/192.168.1.50
address=/holo.nianticlabs.com/192.168.1.50
address=/www.nianticlabs.com/192.168.1.50
```

## If it doesn't go through

The server **logs every request and dumps the raw RequestEnvelope**. If the
client rejects a response or loops, compare the dumped field numbers against the
constants in `protocol.py` — those are the canonical community values and the
one place worth correcting if this exact build differs. Common symptoms:

- **Loops on tutorial / avatar:** `PlayerData` field numbers off — check the
  `PD_*` constants and `tutorial_state`.
- **"Unable to authenticate":** `sso.py` token flow, or `AuthInfo` field numbers.
- **TLS errors in log / client can't connect:** CA not trusted, or DNS not
  redirected (confirm with the device hitting this PC).

## Next milestones (not done yet)

`GET_MAP_OBJECTS` (spawns/stops/gyms), `ENCOUNTER`/`CATCH_POKEMON`,
`FORT_SEARCH`, real `DOWNLOAD_SETTINGS`/`GET_INVENTORY`. The handshake plumbing
and decoder built here are what those build on.
