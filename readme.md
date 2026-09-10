# Pokémon GO 0.29 Private Server

Pokémon GO 0.29 private servers let players run the game outside the official servers. These servers copy the original gameplay but add custom features or remove limits set by Niantic. Players can use them to try out new content, test hacks, or play without needing to connect to the main servers.

Setting up a private server needs technical know-how. You must download server files, set up your network, and change game settings. Many private servers stop working after a while because Niantic updates the game or takes legal action. Using these servers can also risk your account, since Niantic may ban players for not following their rules.

Private servers are popular among fans who want to explore the game in new ways. Still, they often face problems with stability and updates. Players should stay careful and know the risks before joining a private server.

A private server, built from the ground up and designed to operate offline, for the original Pokémon GO 0.29.0 (July 2016)
The actual 2016 client connects to it, logs in using any username (without having an account), and drops
you onto a live map at your location — to catch wild Pokémon, spin PokéStops, and battle,
Go to the train and use the gyms; the entire system operates on your own personal computer and doesn't connect to any external servers.

An independent reverse-engineering project. No part of Niantic's app, assets, or data is
— you must provide your own 0.29 client that you have obtained legally and (in the case of 3D models) your own
real 2016 asset bundles.

## What works

- Fake authentication — you can log in using any username and password; there is no need for a PTC or Google account or internet connection.
— a complete boot handshake, which involves the exact 0.29 RPC sequence (redirect → player → remote config →
  settings → asset digest → item templates → map), with field numbers verified against the
  live client.
- A live map based on your actual GPS shows wild Pokémon, PokéStops, and Gyms located around you.
- **Catching** — encounters, throw scoring (Nice/Great/Excellent, curveballs), Razz Berries,
  break-outs and flees, capture odds — all server-authoritative and **persisted** per account
  Your Pokémon, items, candy, stardust, and XP stay safe after restarts.
- **PokéStops** are displayed, given a name, and can be spun to obtain items and XP, but only after a cooling down period; eggs are dropped.
- **Gyms** — deploy defenders, **train** friendly gyms to raise prestige/level, **battle** to
  take enemy gyms, real 2016 **type-matchup damage** (so HP bars track the fight), **flee**
  mid-battle, the Shop **defender bonus** shield (coins + stardust for gyms you hold), a
  Prestige or level model, coin payouts when a defender returns home, and a raid mode.
- **Progression** — teams (Mystic/Valor/Instinct), level-up rewards, evolve / power-up /
  transfer / favorite / nickname, eggs + incubators + hatching by distance walked, the Pokédex,
  and medals and badges earned from actual 2016 targets.
- **In-game Shop** — you can purchase items using the coins that you earn.
- **Real 2016 game master** — a converter rebuilds the period-correct item-template database
  Convert the (151 Kanto Pokémon, moves, items, cameras) into the format that the client accepts.
- **3D Pokémon models render** *when you supply genuine 2016 asset bundles* — the server
  implements the full asset pipeline (`GET_ASSET_DIGEST` → `GET_DOWNLOAD_URLS` → serve the
  The bundle is encrypted; the client then decrypts and loads it. The bundles are those made by Niantic.
  are not included in this repository; the map, catching, stopping, and the gyms all continue to function;
  The creatures retreat to the client's bundled 2D icons.
- **World Manager** is a local web user interface (http://127.0.0.1:8080) used for placing and managing PokéStops and
  Download real POIs, hold gym events, and check the state.
- A Help Center and a public status or site page.
- A single-file launcher and an optional standalone .exe file (there is no need for Python to be installed on the host).

## Platforms

- **iPhone (0.29):** can be used with the standard client — there is no need for patching — it has successfully reached Tailscale.
- **Android (0.29):** requires a one-off static metadata patch to the APK (see
  Reverse engineering, non-rooted, user-installed CA.
- **Android (0.35):** this is also supported through a plain-HTTP SSO bridge together with RPC using a real certificate.

For the device-specific steps, see work/server/DEVICE_SETUP.md, RUN.md, and VPN.md.

## Known limitations

- **Gym defender counter-attacks don't animate**, and enemy-gym battles are reported as
  The training involves battles. The 0.29 client simulates gym combat locally and ignores
  server-sent battle actions, so the outcome/HP/prestige are ours to control but the
  It is up to the client to carry out the swing animation (or not to do so). Fights are real; the
  The choreography is locked to the client and does not have native disassembly.
– 3D models require the actual 2016 bundles (as mentioned above): this is a limitation due to the unavailability of the data, not a fault.
- The Journal within the game is fed by the server and is not documented in this version, which is why it is empty.

## How it works

The client communicates with pgorelease.nianticlabs.com using HTTPS and Protocol Buffers and
We arrange for those hostnames to resolve to this computer and respond to them.

| Component | File | Role |
|---|---|---|
| DNS redirector | `work/server/dns_redirect.py` | Directs traffic for the Niantic/PTC hosts to this computer and forwards all other requests |
| HTTPS server | in the file `work/server/server.py` | has one TLS listener and routes based on the `Host` header |
| Fake PTC SSO | `work/server/sso.py` | Takes in any credentials and includes the username in the token |
| RPC handler | in work/server/rpc.py | Includes the game protocol such as the boot handshake, the map, catching, forts, gyms and the shop |
| Response builders | in the file `work/server/protocol.py` | Since every message sent to the client (which is the core of the project) |
| Codec for Protobuf | in the file work/server/pb.py | A manually written protobuf reader and writer (without using protoc) |
| World state | in the file `work/server/world.py` | includes the player's inventory, Pokémon, and XP plus the shared gyms, and saves them to disk |
| Game data | `work/server/gamedata.py`, `settings.py` | Stats, moves, types; hot-reloaded tuning in `settings.json` |
| Shop / Help / Site | `work/server/shop.py`, `helpcenter.py`, `windstock_site.py` | In-game store, support pages, status site |
World Manager | in the files `work/server/webui.py` and `admin.py` | provides a local web interface for stops, gyms, events, and POIs
| Launcher | the file work/server/run.py | operates the DNS server and the game server (including the bridges) within a single process |
| Game master converter | `work/tools/convert_gm.py` | Creates 0.29 item templates from the 2016 GAME_MASTER |

TLS makes use of a local CA which you install on the phone. The field numbers were checked against the live one.
client and several are different from public POGOProtos. For example, `RequestEnvelope.requests` is #4, not
The field `PokemonData.id` is of type `fixed64`, not `int32` as the protos state.

## Running it

**Prerequisites:** Python 3, the command `pip install s2sphere`, and OpenSSL (since it is needed for generating certificates).

```bash
cd work/server
py gen_certs.py
```

```bash
py run.py
```

The script run.py detects the LAN IP address of this computer and then starts the DNS redirector and the game server (if you pass an IP address,
For example, by using `py run.py 100.x.y.z` you can specify a particular one such as a Tailscale address). The World
Manager opens on `http://127.0.0.1:8080`.

Build a standalone exe (optional):

```bash
py -m PyInstaller "Start-Pokemon-GO-Server.spec" --distpath ../../RELEASE --noconfirm --clean
```

**On the phone (Android, non-rooted):**

1. As a user, install the patched 0.29 APK and the CA (certs/ca.crt) as a user certificate.
2. For Wi-Fi, set **DNS to the IP address that the launcher prints** (leave DNS 2 empty).
3. If you want a stable map inside buildings, use a **mock-GPS app** and set it as the mock-location app.
   Location mode is set to **GPS only** (not High accuracy).
4. Start the game and log in using any name.

The settings such as spawn rates, catch odds, gym payouts, the defender bonus, etc., are contained in `settings.json`,
The file is written for the first run, with a comment associated with every value, and it undergoes hot reloads as you edit it.

## Reverse engineering the client

The 0.29 version was designed for Android API levels up to and including 23, which means that the native plugin on modern Android fails to load.
The system.load function requires an absolute path. The Frida and x86 emulators didn't work (Samsung Knox /
ARM-translation crashes), the fix that worked is a **static il2cpp metadata patch** that
repoints the `libNianticLabsPlugin.so` string literal to an absolute path. No root. No Frida.
The scripts are `work/tools/metadata_patch.py` and `repackage_metadata.py`. You are responsible for running them yourself.
The patched APK is never made available.

## Repo layout

```
work/server/   the server (Python) + docs + deploy guides
work/tools/    game-master conversion + reverse-engineering scripts
```

Excluded from git (see .gitignore) are the APK/IPA, the Niantic asset bundles and the game-master.
binary, extracted app/engine data, TLS private keys, player save files, runtime data/logs,
builds that are packaged and also third-party tools.

## Legal / disclaimer

This is an independent, educational reverse-engineering project for **personal, offline** use
Having a client that you already possess; it includes none of Niantic's copyrighted code, assets, or data
— original interoperability code only. "Pokémon" and "Pokémon GO" are trademarks of Nintendo.
The Pokémon Company and Niantic; this project has no connection with them and is not endorsed by them. Don't
Distribute their APK or assets.

## Credits

- [AeonLucid/POGOProtos](https://github.com/AeonLucid/POGOProtos), protocol definitions (a
  ; several field numbers were checked again against the live 0.29 client here)
- [rastapasta/pokemon-go-mitm](https://github.com/rastapasta/pokemon-go-mitm). map-object field layout
The POGO Server by maierfelix — a server that is known to be good — is used.
  to cross-check response layouts (timestamps, GlobalSettings, defender bonus)
- The community 2016 GAME_MASTER dump
