# Pokémon GO 0.29 Private Server

A from-scratch, **offline** private server for the original **Pokémon GO 0.29.0** (July 2016)
client. The real 2016 client connects to it, logs in with any username (no account), and drops
you onto a live map at your location — to catch wild Pokémon, spin PokéStops, and battle,
train, and take Gyms. Everything runs on your own PC; nothing phones home.

> An independent reverse-engineering project. **No part of Niantic's app, assets, or data is
> included** — you bring your own legally-obtained 0.29 client and (for 3D models) your own
> genuine 2016 asset bundles.

## What works

- **Fake auth** — log in with any username/password; no PTC/Google account, no internet.
- **Full boot handshake** — the exact 0.29 RPC sequence (redirect → player → remote config →
  settings → asset digest → item templates → map), with field numbers verified against the
  live client.
- **Live map at your real GPS** — wild Pokémon, PokéStops, and Gyms placed around you.
- **Catching** — encounters, throw scoring (Nice/Great/Excellent, curveballs), Razz Berries,
  break-outs and flees, capture odds — all server-authoritative and **persisted** per account
  (your Pokémon, items, candy, stardust, and XP survive restarts).
- **PokéStops** — rendered, named, and spinnable for items + XP on a cooldown; eggs drop.
- **Gyms** — deploy defenders, **train** friendly gyms to raise prestige/level, **battle** to
  take enemy gyms, real 2016 **type-matchup damage** (so HP bars track the fight), **flee**
  mid-battle, the Shop **defender bonus** shield (coins + stardust for gyms you hold), a
  prestige/level model, coin payouts when a defender comes home, and a raid mode.
- **Progression** — teams (Mystic/Valor/Instinct), level-up rewards, evolve / power-up /
  transfer / favorite / nickname, eggs + incubators + hatching by distance walked, the Pokédex,
  and medals/badges scored from real 2016 targets.
- **In-game Shop** — buy items with the coins you earn.
- **Real 2016 game master** — a converter rebuilds the period-correct item-template database
  (151 Kanto Pokémon, moves, items, cameras) into the wire format the client accepts.
- **3D Pokémon models render** *when you supply genuine 2016 asset bundles* — the server
  implements the full asset pipeline (`GET_ASSET_DIGEST` → `GET_DOWNLOAD_URLS` → serve the
  encrypted bundle; the client decrypts and loads it). The bundles themselves are Niantic's and
  are **not** in this repo. Without them, the map, catching, stops, and gyms all still work;
  creatures fall back to the client's bundled 2D icons.
- **World Manager** — a local web UI (`http://127.0.0.1:8080`) to place/manage PokéStops and
  Gyms, download real POIs, run events, and inspect state.
- **Help Center** and a public status/site page.
- **One-file launcher** and an optional standalone `.exe` (no Python needed on the host).

## Platforms

- **iPhone (0.29):** works with a stock client — no patching — reached over Tailscale.
- **Android (0.29):** needs a one-time static metadata patch to the APK (see
  [Reverse engineering](#reverse-engineering-the-client)); non-rooted, user-installed CA.
- **Android (0.35):** also supported, via a plain-HTTP SSO bridge + RPC over a real cert.

See `work/server/DEVICE_SETUP.md`, `RUN.md`, and `VPN.md` for the per-device steps.

## Known limitations

- **Gym defender counter-attacks don't animate**, and enemy-gym battles are reported as
  *training* battles. The 0.29 client simulates gym combat **locally** and ignores
  server-sent battle actions, so the outcome/HP/prestige are ours to control but the
  defender's swing animation is the client's to draw (or not). Fights are real; the
  choreography is client-locked without native disassembly.
- **3D models need genuine 2016 bundles** (see above) — a data-availability wall, not a bug.
- The in-game **Journal** is server-fed and undocumented in this build, so it's left blank.

## How it works

The client talks HTTPS + Protocol Buffers to `pgorelease.nianticlabs.com` and
`sso.pokemon.com`. We make those hostnames resolve to this PC and answer them.

| Component | File | Role |
|---|---|---|
| DNS redirector | `work/server/dns_redirect.py` | Points the Niantic/PTC hosts at this PC; forwards everything else |
| HTTPS server | `work/server/server.py` | One TLS listener, routes by `Host` header |
| Fake PTC SSO | `work/server/sso.py` | Accepts any credentials, embeds the username in the token |
| RPC handler | `work/server/rpc.py` | The game protocol: boot handshake, map, catching, forts, gyms, shop |
| Response builders | `work/server/protocol.py` | Every message the client is sent (the heart of the project) |
| Protobuf codec | `work/server/pb.py` | Hand-rolled protobuf reader/writer (no `protoc`) |
| World state | `work/server/world.py` | Per-account inventory/Pokémon/XP + shared gyms, saved to disk |
| Game data | `work/server/gamedata.py`, `settings.py` | Stats/moves/types; hot-reloaded tuning in `settings.json` |
| Shop / Help / Site | `work/server/shop.py`, `helpcenter.py`, `windstock_site.py` | In-game store, support pages, status site |
| World Manager | `work/server/webui.py`, `admin.py` | Local web UI for stops/gyms/events/POIs |
| Launcher | `work/server/run.py` | Runs DNS + game server (+ bridges) in one process |
| Game master converter | `work/tools/convert_gm.py` | Rebuilds the 2016 GAME_MASTER into 0.29 item templates |

TLS uses a local CA you install on the phone. Field numbers were verified against the live
client and several differ from public POGOProtos (e.g. `RequestEnvelope.requests` is #4, not
#3; `PokemonData.id` is a `fixed64`, not the `int32` the protos claim).

## Running it

**Prereqs:** Python 3, `pip install s2sphere`, and OpenSSL (for cert generation).

```bash
cd work/server
py gen_certs.py
```

```bash
py run.py
```

`run.py` auto-detects this PC's LAN IP and starts the DNS redirector + game server (pass an IP,
e.g. `py run.py 100.x.y.z`, to force a specific one such as a Tailscale address). The World
Manager opens on `http://127.0.0.1:8080`.

Build a standalone exe (optional):

```bash
py -m PyInstaller "Start-Pokemon-GO-Server.spec" --distpath ../../RELEASE --noconfirm --clean
```

**On the phone (Android, non-rooted):**

1. Install your patched 0.29 APK and the CA (`certs/ca.crt`) as a **user** certificate.
2. Wi-Fi → set **DNS = the IP the launcher prints** (leave DNS 2 blank).
3. For a stable map indoors, use a **mock-GPS app** set as the mock-location app, with
   Location mode = **GPS only** (not High accuracy).
4. Launch the game and log in with any name.

Tuning (spawn rates, catch odds, gym payouts, the defender bonus, …) lives in `settings.json`,
which is written on first run with a comment for every value and **hot-reloads** as you edit it.

## Reverse engineering the client

0.29 was built for Android API ≤ 23, so on modern Android its native plugin fails to load
(`System.load` needs an absolute path). After Frida and x86 emulators failed (Samsung Knox /
ARM-translation crashes), the fix that worked is a **static il2cpp metadata patch** that
repoints the `libNianticLabsPlugin.so` string literal to an absolute path — no root, no Frida.
Scripts: `work/tools/metadata_patch.py`, `repackage_metadata.py`. You run these on your own
APK; the patched APK is never distributed.

## Repo layout

```
work/server/   the server (Python) + docs + deploy guides
work/tools/    game-master conversion + reverse-engineering scripts
```

Excluded from git (see `.gitignore`): the APK/IPA, Niantic asset bundles and the game-master
binary, extracted app/engine data, TLS private keys, player save files, runtime data/logs,
packaged builds, and third-party tools.

## Legal / disclaimer

This is an independent, educational reverse-engineering project for **personal, offline** use
with a client you already own. It ships **none** of Niantic's copyrighted code, assets, or data
— only original interoperability code. "Pokémon" and "Pokémon GO" are trademarks of Nintendo /
The Pokémon Company / Niantic; this project is not affiliated with or endorsed by them. Don't
redistribute their APK or assets.

## Credits

- [AeonLucid/POGOProtos](https://github.com/AeonLucid/POGOProtos) — protocol definitions (a
  reference; several field numbers were re-verified against the live 0.29 client here)
- [rastapasta/pokemon-go-mitm](https://github.com/rastapasta/pokemon-go-mitm) — map-object field layout
- [maierfelix/POGOServer](https://github.com/maierfelix/POGOServer) — a known-good server used
  to cross-check response layouts (timestamps, GlobalSettings, defender bonus)
- The community 2016 GAME_MASTER dump
