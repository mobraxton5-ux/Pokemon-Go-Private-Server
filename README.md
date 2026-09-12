# Pokémon GO 0.29 Private Server

Pokémon GO private servers let people play the game without Niantic's official servers. They
recreate the original gameplay, and can add custom features or remove limits the official game
had. People use them to revisit old versions of the game, experiment, or play entirely offline.

Setting up a private server takes some technical know-how: you run the server on a PC, point
your phone's network at it, and install a certificate so the game will trust it. This server
needs **no Niantic, PTC or Google account** and never contacts Niantic, so there is no official
account involved and nothing to be banned.

This one is a private server built from scratch to run **offline**, for the original
**Pokémon GO 0.29.0** (July 2016). The real 2016 client connects to it, logs in with any
username (no account needed), and drops you onto a live map at your location, where you can
catch wild Pokémon, spin PokéStops, and battle, train and take Gyms. Everything runs on your own
PC; nothing connects to outside servers.

> An independent reverse-engineering project. **No part of Niantic's app, assets, or data is
> included** — you provide your own legally obtained 0.29 client and (for 3D models) your own
> genuine 2016 asset bundles. See [Legal](#legal--disclaimer).

## What works

- **Fake login** — log in with any username and password; no PTC or Google account, no internet.
- **Full boot handshake** — the exact 0.29 RPC sequence (redirect → player → remote config →
  settings → asset digest → item templates → map), with field numbers checked against the
  live client.
- **Every request the client can send gets a real answer.** All 71 request types in the 0.29
  client were checked against its own metadata; every one that has a message layout in the
  client is handled (gym recall, incense/lure encounters, badges, contact settings, and more).
- **Live map at your real GPS** — wild Pokémon, PokéStops, and Gyms placed around you.
- **Catching** — encounters, throw scoring (Nice/Great/Excellent, curveballs), Razz Berries,
  break-outs and flees, capture odds — all decided by the server and **saved** per account
  (your Pokémon, items, candy, stardust, and XP survive restarts).
- **PokéStops** — shown on the map, named, and spinnable for items and XP on a cooldown; they
  also drop eggs.
- **Gyms** — deploy defenders, **train** friendly gyms to raise their prestige and level,
  **battle** to take enemy gyms, real 2016 **type-matchup damage** (so HP bars follow the
  fight), **flee** mid-battle, the Shop **defender bonus** shield (coins and stardust for the
  gyms you hold), a prestige/level system, coin payouts when a defender comes home, and a
  raid mode.
- **Progression** — teams (Mystic/Valor/Instinct), evolve / power up / transfer / favorite /
  nickname, the Pokédex, and medals scored against the real 2016 targets.
- **Level-ups** — the level-up screen plays **the moment you level up**, not only after a
  restart, and each level's rewards are paid exactly once.
- **Eggs and incubators** — eggs from PokéStops hatch by the distance you actually walk. Every
  trainer has one unlimited incubator; basic incubators from the Shop or level rewards have
  three uses and break after the third hatch, like in 2016.
- **In-game Shop** — buy items with the coins you earn.
- **Real 2016 game master** — a converter rebuilds the period-correct item-template database
  (151 Kanto Pokémon, moves, items, cameras) into the format the client accepts.
- **3D Pokémon models render** *when you supply genuine 2016 asset bundles* — the server
  implements the full asset pipeline (`GET_ASSET_DIGEST` → `GET_DOWNLOAD_URLS` → serve the
  encrypted bundle, which the client decrypts and loads). The bundles belong to Niantic and are
  **not** in this repo. Without them the map, catching, stops, and gyms all still work; the
  creatures fall back to the client's built-in 2D icons.
- **World Manager** — a local web UI (`http://127.0.0.1:8080`) to place and manage PokéStops
  and Gyms, download real POIs, run events, and check the server's state.
- **Help Center** and a public status/site page.
- **One-file launcher** and an optional standalone `.exe` (no Python needed on the host).

## Recent changes

- **Level-up screen shows up during play.** Inventory replies used to leave
  `InventoryDelta.original_timestamp` at 0, so the client treated every poll as a full reload
  and never compared your old level with the new one. The server now echoes the client's own
  timestamp back, so each poll is a real update and the client fires the level-up itself.
- **Level rewards can't be paid twice.** The client asks for them twice at the same moment; the
  check-and-claim is now a single step.
- **Incubators work.** Shop and level-reward incubators used to land in the bag as ordinary
  items the client couldn't use. They are now real incubators with three uses, and any stuck in
  a bag are converted automatically when the player next logs in.
- **Used-up items update on screen.** Items that reach 0 are sent as count 0, so the bag
  never shows a stale number.
- **All remaining requests answered**, and `DOWNLOAD_SETTINGS` now fills in every
  `GlobalSettings` field the client reads (including `level_settings`).
- **Deleting a save resets the player.** Removing `data/saves/<name>.json` while the server is
  running now really starts that trainer over, instead of the server writing their old
  progress back from memory.

## Platforms

- **iPhone (0.29 and 0.35):** works with the stock client — no patching — reached over Tailscale.
- **Android (0.29):** needs a one-time static metadata patch to the APK (see
  [Reverse engineering](#reverse-engineering-the-client)); no root, user-installed CA.
- **Android (0.35):** also supported, through a plain-HTTP SSO bridge plus RPC over a real
  certificate.

See `work/server/DEVICE_SETUP.md`, `RUN.md`, and `VPN.md` for the steps for each device.

## Known limitations

- **Gym defender counter-attacks don't animate**, and battles at enemy gyms are shown as
  *training* battles. The 0.29 client simulates gym combat **on the phone** and ignores the
  battle actions the server sends, so the outcome, HP and prestige are ours to control, but the
  defender's attack animation is up to the client. The fights are real; the animation can't be
  changed without disassembling the client.
- **3D models need genuine 2016 bundles** (see above) — the data isn't available, it's not a bug.
- The in-game **Journal** is filled by the server in a format that isn't documented for this
  version, so it's left blank.
- Requests for features the 0.29 client doesn't contain (trading, Pokémon GO Plus, the item/gem
  packs) have no message layout in the client, so there is nothing to answer.

## How it works

The client talks HTTPS + Protocol Buffers to `pgorelease.nianticlabs.com` and
`sso.pokemon.com`. We make those hostnames point to this PC and answer them ourselves.

| Component | File | Role |
|---|---|---|
| DNS redirector | `work/server/dns_redirect.py` | Points the Niantic/PTC hosts at this PC; forwards everything else |
| HTTPS server | `work/server/server.py` | One TLS listener, routes by `Host` header |
| Fake PTC SSO | `work/server/sso.py` | Accepts any credentials, puts the username in the token |
| RPC handler | `work/server/rpc.py` | The game protocol: boot handshake, map, catching, forts, gyms, shop |
| Response builders | `work/server/protocol.py` | Every message sent to the client (the heart of the project) |
| Protobuf codec | `work/server/pb.py` | Hand-written protobuf reader/writer (no `protoc`) |
| World state | `work/server/world.py` | Per-account inventory, Pokémon and XP, plus shared gyms, saved to disk |
| Game data | `work/server/gamedata.py`, `settings.py` | Stats, moves, types; hot-reloaded tuning in `settings.json` |
| Shop / Help / Site | `work/server/shop.py`, `helpcenter.py`, `windstock_site.py` | In-game store, support pages, status site |
| World Manager | `work/server/webui.py`, `admin.py` | Local web UI for stops, gyms, events and POIs |
| Launcher | `work/server/run.py` | Runs the DNS and game server (plus bridges) in one process |
| Game master converter | `work/tools/convert_gm.py` | Rebuilds the 2016 GAME_MASTER into 0.29 item templates |
| Metadata reader | `work/tools/metadata_fields.py` | Reads exact protobuf field numbers straight out of the client |

TLS uses a local CA that you install on the phone. Field numbers were checked against the live
client, and several differ from the public POGOProtos (e.g. `RequestEnvelope.requests` is #4, not
#3; `PokemonData.id` is a `fixed64`, not the `int32` the protos claim).

## Running it

**Prerequisites:** Python 3, `pip install s2sphere`, and OpenSSL (for generating certificates).

```bash
cd work/server
py gen_certs.py
```

```bash
py run.py
```

`run.py` detects this PC's LAN IP and starts the DNS redirector and the game server. Pass an IP
to use a specific one, such as a Tailscale address: `py run.py 100.x.y.z`. The World Manager
opens on `http://127.0.0.1:8080`.

Build a standalone exe (optional):

```bash
py -m PyInstaller "Start-Pokemon-GO-Server.spec" --distpath ../../RELEASE --noconfirm --clean
```

**On the phone (Android, no root):**

1. Install your patched 0.29 APK, and install the CA (`certs/ca.crt`) as a **user** certificate.
2. In Wi-Fi settings, set **DNS to the IP the launcher prints** (leave DNS 2 blank).
3. For a stable map indoors, use a **mock-GPS app** set as the mock-location app, with
   Location mode set to **GPS only** (not High accuracy).
4. Start the game and log in with any name.

Tuning (spawn rates, catch odds, gym payouts, the defender bonus, …) lives in `settings.json`,
which is written on first run with a comment for every value and **hot-reloads** as you edit it.

To reset a player for testing, delete their `data/saves/<name>.json` — this works even while
the server is running.

## Reverse engineering the client

0.29 was built for Android API 23 and below, so on modern Android its native plugin fails to
load (`System.load` needs an absolute path). Frida and x86 emulators didn't work (Samsung Knox
and ARM-translation crashes); the fix that worked is a **static il2cpp metadata patch** that
points the `libNianticLabsPlugin.so` string to an absolute path — no root, no Frida.
Scripts: `work/tools/metadata_patch.py` and `repackage_metadata.py`. You run these on your own
APK; the patched APK is never distributed.

## Repo layout

```
work/server/   the server (Python) + docs + deploy guides
work/tools/    game-master conversion + reverse-engineering scripts
```

Only these two folders (plus this README) are published. Everything else is excluded by
`.gitignore`: the APK/IPA, Niantic's asset bundles and game-master binary, extracted app data,
TLS private keys, player saves, runtime data and logs, packaged builds, and third-party tools.

## Legal / disclaimer

This is an independent, educational reverse-engineering project for **personal, offline** use
with a client you already own. It includes **none** of Niantic's copyrighted code, assets, or
data — only original interoperability code. "Pokémon" and "Pokémon GO" are trademarks of
Nintendo / The Pokémon Company / Niantic; this project is not affiliated with or endorsed by
them. Don't redistribute their APK or assets.

## Credits

- [AeonLucid/POGOProtos](https://github.com/AeonLucid/POGOProtos) — protocol definitions (a
  reference; several field numbers were re-checked against the live 0.29 client here)
- [rastapasta/pokemon-go-mitm](https://github.com/rastapasta/pokemon-go-mitm) — map-object field layout
- [maierfelix/POGOServer](https://github.com/maierfelix/POGOServer) — a known-good server used
  to cross-check response layouts (timestamps, GlobalSettings, defender bonus)
- The community 2016 GAME_MASTER dump
