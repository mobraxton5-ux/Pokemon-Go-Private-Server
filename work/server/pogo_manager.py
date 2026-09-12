"""
PoGO Server Manager -- a small Tkinter control panel for the private server.

One window to:
  - see live status of every moving part (game server, headscale, Caddy, playit,
    Tailscale, and the public control URL),
  - start/stop the game server and the Docker (headscale+Caddy) stack,
  - approve an iPhone that's waiting to join (paste the code it shows),
  - copy the Android join key,
  - switch the live in-game event (Normal, Swarm, Pikachu Festival, ...) or set a
    custom one -- spawns change immediately, no restart,
  - watch a SIMPLIFIED activity log (players logging in, catches, stops) instead of
    the raw RPC firehose.

Pure standard library (tkinter + subprocess + urllib), so it bundles into one .exe
with PyInstaller and needs nothing installed on the target.

Build:  py -m PyInstaller --onefile --noconsole --name PoGO-Manager pogo_manager.py
"""
import os
import re
import sys
import json
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk
import urllib.request
import ssl

# ---- suppress console windows spawned by each subprocess on Windows -----------
_NOWIN = 0x08000000 if os.name == "nt" else 0

HS_USER = "pogo"                       # headscale user the players belong to
HS_CONTAINER = "pogo-headscale"
PUBLIC_URL = "https://bracky.playit.plus/health"
POLL_MS = 4000


# ---- locate everything relative to where this runs ---------------------------
def _project_root():
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    d = here
    for _ in range(8):
        if (os.path.isdir(os.path.join(d, "RELEASE"))
                and os.path.isdir(os.path.join(d, "server"))):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # last resort: assume this file sits in work/server -> up two
    return os.path.abspath(os.path.join(here, "..", ".."))


ROOT = _project_root()
GAME_EXE = os.path.join(ROOT, "RELEASE", "Start-Pokemon-GO-Server.exe")
GAME_LOG = os.path.join(ROOT, "RELEASE", "data", "server-log.txt")
GAME_DATA = os.path.dirname(GAME_LOG)                 # <exe folder>/data
SETTINGS_JSON = os.path.join(GAME_DATA, "settings.json")
# The manager mirrors its pending schedule here so the game server's in-game Help
# Center (Events page) can tell players what's coming up.
SCHEDULE_JSON = os.path.join(GAME_DATA, "event_schedule.json")
ADMIN_HOST = "127.0.0.1"                              # World Manager is localhost-only
HS_DIR = os.path.join(ROOT, "server", "deploy", "headscale-pc")
PLAYER_GUIDE = os.path.join(HS_DIR, "PLAYER-GUIDE.md")
TAILNET_IP = "100.64.0.1"

# Kanto species names for the custom-event picker (index 0 unused). Same order as
# admin.py's DEX so the numbers agree with the World Manager web page.
DEX = [""] + (
    "Bulbasaur Ivysaur Venusaur Charmander Charmeleon Charizard Squirtle Wartortle "
    "Blastoise Caterpie Metapod Butterfree Weedle Kakuna Beedrill Pidgey Pidgeotto Pidgeot "
    "Rattata Raticate Spearow Fearow Ekans Arbok Pikachu Raichu Sandshrew Sandslash NidoranF "
    "Nidorina Nidoqueen NidoranM Nidorino Nidoking Clefairy Clefable Vulpix Ninetales Jigglypuff "
    "Wigglytuff Zubat Golbat Oddish Gloom Vileplume Paras Parasect Venonat Venomoth Diglett "
    "Dugtrio Meowth Persian Psyduck Golduck Mankey Primeape Growlithe Arcanine Poliwag Poliwhirl "
    "Poliwrath Abra Kadabra Alakazam Machop Machoke Machamp Bellsprout Weepinbell Victreebel "
    "Tentacool Tentacruel Geodude Graveler Golem Ponyta Rapidash Slowpoke Slowbro Magnemite "
    "Magneton Farfetchd Doduo Dodrio Seel Dewgong Grimer Muk Shellder Cloyster Gastly Haunter "
    "Gengar Onix Drowzee Hypno Krabby Kingler Voltorb Electrode Exeggcute Exeggutor Cubone "
    "Marowak Hitmonlee Hitmonchan Lickitung Koffing Weezing Rhyhorn Rhydon Chansey Tangela "
    "Kangaskhan Horsea Seadra Goldeen Seaking Staryu Starmie MrMime Scyther Jynx Electabuzz "
    "Magmar Pinsir Tauros Magikarp Gyarados Lapras Ditto Eevee Vaporeon Jolteon Flareon Porygon "
    "Omanyte Omastar Kabuto Kabutops Aerodactyl Snorlax Articuno Zapdos Moltres Dratini Dragonair "
    "Dragonite Mewtwo Mew".split())

# Shown in the Schedule dialog when the server hasn't been reached yet to list its
# own presets. Kept in step with events.py's PRESETS.
PRESET_FALLBACK = ["Normal", "Swarm", "Pikachu Festival", "Starter Party",
                   "Legendary Hunt", "High CP"]


def _find_docker():
    cands = [
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        r"C:\Program Files\Docker\Docker\resources\bin\com.docker.cli.exe",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return "docker"   # hope it's on PATH


def _find_tailscale():
    c = r"C:\Program Files\Tailscale\tailscale.exe"
    return c if os.path.exists(c) else "tailscale"


DOCKER = _find_docker()
TAILSCALE = _find_tailscale()
TAILNET_FALLBACK = "100.64.0.1"       # only used if Tailscale can't be queried


def tailnet_ip():
    """This machine's current tailnet (100.x) IP, or None if Tailscale is down."""
    rc, out = run([TAILSCALE, "ip", "-4"], timeout=8)
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("100."):
                return line
    return None


def run(args, timeout=15, cwd=None):
    """Run a command, return (rc, stdout+stderr). Never raises."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd, creationflags=_NOWIN)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def spawn(args, cwd=None):
    """Fire-and-forget a process (start server, etc.)."""
    try:
        subprocess.Popen(args, cwd=cwd, creationflags=_NOWIN,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ---- status probes -----------------------------------------------------------
def _tasklist_has(image):
    # CSV + no-header: tasklist does NOT truncate the image name in CSV mode
    # (the default table mode clips it to 25 chars, which hid ".exe").
    rc, out = run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                  timeout=8)
    return "no tasks" not in out.lower() and image.lower() in out.lower()


def probe_all():
    """Return a dict of component -> (ok:bool, detail:str)."""
    st = {}
    st["game"] = (_tasklist_has("Start-Pokemon-GO-Server.exe"), "")
    rc, out = run([DOCKER, "ps", "--format", "{{.Names}}"], timeout=10)
    names = out if rc == 0 else ""
    st["headscale"] = (HS_CONTAINER in names, "")
    st["caddy"] = ("pogo-caddy" in names, "")
    st["playit"] = (_tasklist_has("playitd.exe")
                    or _tasklist_has("playitd-service.exe"), "")
    rc, out = run([TAILSCALE, "status", "--json"], timeout=10)
    ts_ok, ts_ip = False, ""
    if rc == 0:
        try:
            j = json.loads(out)
            ts_ok = j.get("BackendState") == "Running"
            ts_ip = (j.get("Self", {}) or {}).get("TailscaleIPs", [""])[0]
        except Exception:
            pass
    st["tailscale"] = (ts_ok, ts_ip)
    return st


def probe_public():
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(PUBLIC_URL, timeout=8, context=ctx) as r:
            return (r.status == 200, f"HTTP {r.status}")
    except Exception as e:
        return (False, str(e)[:40])


def list_nodes():
    rc, out = run([DOCKER, "exec", HS_CONTAINER, "headscale", "nodes", "list",
                   "-o", "json"], timeout=12)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None
    rows = []
    for n in data:
        name = n.get("given_name") or n.get("name") or "?"
        ips = n.get("ip_addresses") or []
        ip = next((a for a in ips if a.startswith("100.")), ips[0] if ips else "")
        online = bool(n.get("online"))
        rows.append((name, ip, "online" if online else "offline"))
    return rows


_PENDING_RE = re.compile(r"/register/(hskey-authreq-[A-Za-z0-9_-]+)")


def pending_authids(since_epoch):
    """Auth-ids of devices that hit the /register page since `since_epoch`.
    A waiting iPhone re-polls that URL, so it shows up here until approved."""
    rc, out = run([DOCKER, "logs", "--since", str(int(since_epoch)), HS_CONTAINER],
                  timeout=12)
    if rc != 0:
        return set()
    return set(_PENDING_RE.findall(out))


def approve_id(aid):
    """Approve one pending device. Returns (ok, message)."""
    rc, out = run([DOCKER, "exec", HS_CONTAINER, "headscale", "auth", "register",
                   "--user", HS_USER, "--auth-id", aid], timeout=20)
    ok = rc == 0 and "registered" in out.lower()
    return ok, out.strip()[:100]


def current_key():
    import time
    rc, out = run([DOCKER, "exec", HS_CONTAINER, "headscale", "preauthkeys", "list",
                   "-o", "json"], timeout=12)
    if rc != 0:
        return None
    try:
        now = time.time()
        for k in json.loads(out):
            if not k.get("reusable"):
                continue
            exp = (k.get("expiration") or {}).get("seconds", 0)
            if exp and exp < now:          # expired
                continue
            if k.get("key"):
                return k["key"]
    except Exception:
        pass
    return None


# ---- events (live spawn config) via the local World Manager API ---------------
# The game server runs on THIS machine and exposes the World Manager on
# 127.0.0.1:<port>. Driving that same API means events go through events.py's
# validation and the running server hot-reloads them on the next map refresh --
# exactly what the web page does, so there's no second copy of the presets here.
def admin_port():
    """World Manager port from the server's settings.json, or 8080 if unset."""
    try:
        with open(SETTINGS_JSON, "r", encoding="utf-8") as fh:
            j = json.load(fh)
        p = int((j.get("server") or {}).get("world_manager_port") or 8080)
        return p if 1 <= p <= 65535 else 8080
    except Exception:
        return 8080


def _api(path, body=None, timeout=6):
    """GET (body=None) or POST JSON to the World Manager. Returns parsed JSON,
    or None if the server isn't running / the call failed."""
    url = f"http://{ADMIN_HOST}:{admin_port()}{path}"
    try:
        data, headers = None, {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else {}
    except Exception:
        return None


def ev_state():
    """(config, presets) from the running server, or (None, None) if it's down."""
    j = _api("/api/world")
    if not j:
        return None, None
    return j.get("config"), (j.get("presets") or [])


def ev_apply_preset(name):
    return _api("/api/preset", {"name": name})


def ev_save(cfg):
    return _api("/api/save", cfg)


# ---- simplified log parsing --------------------------------------------------
_LAST_USER = {"name": None}


def humanize(line):
    """Map a raw server-log line to a friendly message, or None to drop it."""
    m = re.search(r"user='([^']+)'", line)
    if m:
        _LAST_USER["name"] = m.group(1)
    who = _LAST_USER["name"] or "a player"

    if "GET_PLAYER answered as" in line:
        mm = re.search(r"answered as '?([\w]+)'?", line)
        return f"\U0001F464 {mm.group(1) if mm else who} connected"
    if "-> CAUGHT" in line:
        return f"\U0001F534 {who} caught a Pokemon"
    if "broke out" in line:
        return f"\u26aa {who}'s Pokemon broke out"
    if "-> FORT_SEARCH" in line and "got [" in line:
        return f"\U0001F535 {who} spun a PokeStop"
    if "LEVEL_UP_REWARDS" in line and "SUCCESS" in line:
        return f"\u2B50 {who} leveled up"
    if "ENCOUNTER" in line and "catch screen" in line:
        return f"\U0001F43E {who} found a wild Pokemon"
    if "[ptc] login page issued" in line:
        return "\U0001F511 someone is logging in..."
    if "PoGO private server listening" in line:
        return "\u2705 game server started"
    if re.search(r"traceback|error|failed|exception", line, re.I):
        return "\u26a0\ufe0f " + line.strip()[:120]
    return None


# ============================ GUI ============================================
class App:
    def __init__(self, root):
        self.root = root
        root.title("PoGO Server Manager")
        root.geometry("820x730")
        root.minsize(720, 590)
        self.raw = tk.BooleanVar(value=False)
        self.logq = queue.Queue()
        self._tailnet_ip = None       # auto-detected from Tailscale; used to start game
        self._build()
        self._start_threads()
        self.root.after(200, self._drain_log)
        self.refresh_nodes()
        self._events_tick()           # poll the live event and keep the label fresh
        self._write_schedule_file()   # clear any stale schedule from a past session

    # ---- layout ----
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        top = ttk.LabelFrame(self.root, text="Status")
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.dots = {}
        comps = [("game", "Game Server"), ("headscale", "Headscale"),
                 ("caddy", "Caddy/HTTPS"), ("playit", "playit"),
                 ("tailscale", "Tailscale"), ("public", "Public URL")]
        for i, (key, label) in enumerate(comps):
            f = ttk.Frame(top)
            f.grid(row=0, column=i, padx=8, pady=6, sticky="w")
            dot = tk.Label(f, text="\u25CF", fg="#888", font=("Segoe UI", 12))
            dot.pack(side="left")
            ttk.Label(f, text=label).pack(side="left")
            self.dots[key] = dot
        self.detail = ttk.Label(top, text="", foreground="#555")
        self.detail.grid(row=1, column=0, columnspan=6, sticky="w", padx=8, pady=(0, 4))

        # controls
        ctl = ttk.LabelFrame(self.root, text="Controls")
        ctl.pack(fill="x", padx=8, pady=4)
        self.btn_game = ttk.Button(ctl, text="\u25B6 Start Game Server",
                                   command=self.toggle_game)
        self.btn_game.grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(ctl, text="\u25B6 Start Stack",
                   command=self.start_stack).grid(row=0, column=1, padx=6)
        ttk.Button(ctl, text="\u25A0 Stop Stack",
                   command=self.stop_stack).grid(row=0, column=2, padx=6)
        ttk.Button(ctl, text="\u21BB Restart Headscale",
                   command=self.restart_hs).grid(row=0, column=3, padx=6)
        ttk.Button(ctl, text="\U0001F4CB Copy Android Key",
                   command=self.copy_key).grid(row=0, column=4, padx=6)
        ttk.Button(ctl, text="\U0001F4D6 Player Guide",
                   command=self.open_guide).grid(row=0, column=5, padx=6)

        # events -- one-click spawn "themes" plus a custom builder. These drive the
        # game server's World Manager API, so a click changes the wild Pokemon live.
        ev = ttk.LabelFrame(self.root, text="Events (live spawns)")
        ev.pack(fill="x", padx=8, pady=4)
        self.ev_presets = ttk.Frame(ev)
        self.ev_presets.pack(fill="x", padx=6, pady=(4, 2))
        self._ev_buttons_done = False
        self._ev_config = None
        self._ev_presets_list = []          # preset names last seen from the server
        self._sched = None                  # the one pending/active scheduled event
        evrow = ttk.Frame(ev); evrow.pack(fill="x", padx=6, pady=(0, 2))
        self.ev_now = ttk.Label(evrow, text="Current event: (checking...)",
                                foreground="#777")
        self.ev_now.pack(side="left")
        evbtns = ttk.Frame(evrow); evbtns.pack(side="right")
        ttk.Button(evbtns, text="↻", width=3,
                   command=self.refresh_events).pack(side="left", padx=4)
        ttk.Button(evbtns, text="Custom event…",
                   command=self.open_custom_event).pack(side="left", padx=4)
        ttk.Button(evbtns, text="⏰ Schedule…",
                   command=self.open_schedule_event).pack(side="left", padx=4)
        schrow = ttk.Frame(ev); schrow.pack(fill="x", padx=6, pady=(0, 4))
        self.ev_sched = ttk.Label(schrow, text="", foreground="#3b6ea5")
        self.ev_sched.pack(side="left")
        self.btn_sched_cancel = ttk.Button(schrow, text="Cancel schedule",
                                           command=self.cancel_schedule,
                                           state="disabled")
        self.btn_sched_cancel.pack(side="right", padx=4)

        # approve iphone -- auto-detected pending list + auto-approve + manual paste
        appr = ttk.LabelFrame(self.root, text="iPhones waiting to join")
        appr.pack(fill="x", padx=8, pady=4)
        row1 = ttk.Frame(appr); row1.pack(fill="x")
        self.auto_approve = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="Auto-approve new iPhones", variable=self.auto_approve
                        ).pack(side="left", padx=6, pady=4)
        ttk.Label(row1, text="(waiting devices appear below automatically)",
                  foreground="#777").pack(side="left")
        row2 = ttk.Frame(appr); row2.pack(fill="x", pady=(0, 4))
        self.pend_list = tk.Listbox(row2, height=3)
        self.pend_list.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row2, text="Approve selected",
                   command=self.approve_selected).pack(side="left", padx=6)
        row3 = ttk.Frame(appr); row3.pack(fill="x", pady=(0, 4))
        ttk.Label(row3, text="Manual:").pack(side="left", padx=(6, 0))
        self.appr_entry = ttk.Entry(row3, width=52)
        self.appr_entry.pack(side="left", padx=6)
        self.appr_entry.insert(0, "hskey-authreq-...")
        ttk.Button(row3, text="Approve",
                   command=self.approve).pack(side="left", padx=6)
        self._pending = {}            # aid -> listbox index
        self._pending_since = None

        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        # nodes
        nf = ttk.LabelFrame(mid, text="Connected devices")
        nf.pack(side="left", fill="both", expand=False, padx=(0, 4))
        self.tree = ttk.Treeview(nf, columns=("ip", "state"), show="tree headings",
                                 height=10)
        self.tree.heading("#0", text="Name")
        self.tree.heading("ip", text="Tailnet IP")
        self.tree.heading("state", text="State")
        self.tree.column("#0", width=140)
        self.tree.column("ip", width=110)
        self.tree.column("state", width=70)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(nf, text="Refresh", command=self.refresh_nodes).pack(pady=(0, 4))

        # log
        lf = ttk.LabelFrame(mid, text="Activity")
        lf.pack(side="left", fill="both", expand=True, padx=(4, 0))
        bar = ttk.Frame(lf)
        bar.pack(fill="x")
        ttk.Checkbutton(bar, text="Raw log", variable=self.raw).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=lambda: self.log.delete("1.0", "end")
                   ).pack(side="right", padx=4)
        self.log = tk.Text(lf, height=14, wrap="word", bg="#0f1720", fg="#d6e2f0",
                           insertbackground="#d6e2f0", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        self.status = ttk.Label(self.root, text="", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    # ---- background threads ----
    def _start_threads(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._log_loop, daemon=True).start()
        threading.Thread(target=self._pending_loop, daemon=True).start()
        self._pub_counter = 0

    def _pending_loop(self):
        import time
        since = time.time() - 30      # small look-back so a device already waiting shows
        while True:
            try:
                now = time.time()
                found = pending_authids(since)
                since = now
                for aid in found:
                    if aid not in self._pending:
                        self.root.after(0, self._on_pending, aid)
            except Exception:
                pass
            time.sleep(6)

    def _on_pending(self, aid):
        if aid in self._pending:
            return
        if self.auto_approve.get():
            self._append(f"\U0001F4F1 approving iPhone {aid[-6:]}...")
            self._do_approve(aid, from_list=False)
            self._pending[aid] = None       # mark handled so we don't loop
            return
        self.pend_list.insert("end", aid)
        self._pending[aid] = self.pend_list.size() - 1
        self._toast(f"iPhone waiting to join ({self.pend_list.size()} pending)")

    def _poll_loop(self):
        import time
        while True:
            st = probe_all()
            # public check every other cycle (it's slower)
            self._pub_counter = (self._pub_counter + 1) % 2
            pub = probe_public() if self._pub_counter == 0 else None
            self.root.after(0, self._apply_status, st, pub)
            time.sleep(POLL_MS / 1000.0)

    def _apply_status(self, st, pub):
        colors = {True: "#2ecc71", False: "#e74c3c"}
        for key in ("game", "headscale", "caddy", "playit", "tailscale"):
            ok = st.get(key, (False, ""))[0]
            self.dots[key].config(fg=colors[ok])
        if pub is not None:
            self.dots["public"].config(fg=colors[pub[0]])
        ts_ip = st.get("tailscale", (False, ""))[1]
        if ts_ip:
            self._tailnet_ip = ts_ip
        self.detail.config(text=f"Tailnet IP: {self._tailnet_ip or '(down)'}"
                                f"   |   Control: {PUBLIC_URL}")
        self.btn_game.config(text=("\u25A0 Stop Game Server" if st["game"][0]
                                   else "\u25B6 Start Game Server"))
        self._game_running = st["game"][0]

    def _log_loop(self):
        import time
        # follow the game log file
        pos = None
        while True:
            try:
                if not os.path.exists(GAME_LOG):
                    time.sleep(1); continue
                size = os.path.getsize(GAME_LOG)
                if pos is None:
                    pos = max(0, size - 4000)      # start near the end
                if size < pos:                     # rotated
                    pos = 0
                with open(GAME_LOG, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    if not line.strip():
                        continue
                    self.logq.put(line)
            except Exception:
                pass
            time.sleep(1)

    def _drain_log(self):
        try:
            while True:
                raw = self.logq.get_nowait()
                if self.raw.get():
                    self._append(raw)
                else:
                    msg = humanize(raw)
                    if msg:
                        self._append(msg)
        except queue.Empty:
            pass
        self.root.after(400, self._drain_log)

    def _append(self, text):
        self.log.insert("end", text + "\n")
        # cap the buffer
        if int(self.log.index("end-1c").split(".")[0]) > 500:
            self.log.delete("1.0", "100.0")
        self.log.see("end")

    def _toast(self, msg):
        self.status.config(text=msg)

    # ---- actions (run off the UI thread) ----
    def _bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def toggle_game(self):
        if getattr(self, "_game_running", False):
            self._bg(lambda: (run(["taskkill", "/F", "/IM",
                                    "Start-Pokemon-GO-Server.exe"]),
                              self.root.after(0, self._toast, "Game server stopped")))
        else:
            if not os.path.exists(GAME_EXE):
                self._toast(f"Not found: {GAME_EXE}"); return
            ip = self._tailnet_ip or tailnet_ip() or TAILNET_FALLBACK
            self._tailnet_ip = ip
            spawn([GAME_EXE, ip], cwd=os.path.dirname(GAME_EXE))
            self._toast(f"Game server starting on {ip}...")

    def start_stack(self):
        self._toast("Starting Docker stack...")
        self._bg(lambda: (run([DOCKER, "compose", "up", "-d"], timeout=120, cwd=HS_DIR),
                          self.root.after(0, self._toast, "Stack up")))

    def stop_stack(self):
        self._toast("Stopping Docker stack...")
        self._bg(lambda: (run([DOCKER, "compose", "down"], timeout=60, cwd=HS_DIR),
                          self.root.after(0, self._toast, "Stack down")))

    def restart_hs(self):
        self._toast("Restarting headscale...")
        self._bg(lambda: (run([DOCKER, "compose", "restart", "headscale"],
                              timeout=60, cwd=HS_DIR),
                          self.root.after(0, self._toast, "Headscale restarted")))

    def approve(self):
        m = re.search(r"(hskey-authreq-[A-Za-z0-9_-]+)", self.appr_entry.get())
        if not m:
            self._toast("Paste the code that starts with hskey-authreq-"); return
        self._do_approve(m.group(1), from_list=False)

    def approve_selected(self):
        sel = self.pend_list.curselection()
        if not sel:
            self._toast("Select a waiting iPhone first"); return
        aid = self.pend_list.get(sel[0])
        self._do_approve(aid, from_list=True)

    def _do_approve(self, aid, from_list):
        self._toast(f"Approving {aid[-8:]}...")

        def go():
            ok, msg = approve_id(aid)
            self.root.after(0, self._after_approve, aid, ok, msg, from_list)
        self._bg(go)

    def _after_approve(self, aid, ok, msg, from_list):
        self._toast("iPhone approved!" if ok else f"Failed: {msg}")
        self._append((f"✅ iPhone approved ({aid[-6:]})" if ok
                      else f"⚠️ approve failed: {msg}"))
        self._pending[aid] = None       # don't resurface it
        # drop it from the visible list if present
        for i in range(self.pend_list.size()):
            if self.pend_list.get(i) == aid:
                self.pend_list.delete(i)
                break
        self.refresh_nodes()

    def copy_key(self):
        def go():
            key = current_key()
            if key:
                self.root.clipboard_clear(); self.root.clipboard_append(key)
                self.root.after(0, self._toast, "Android key copied to clipboard")
            else:
                self.root.after(0, self._toast, "No reusable key found (is the stack up?)")
        self._bg(go)

    def open_guide(self):
        try:
            os.startfile(PLAYER_GUIDE)      # noqa: available on Windows
        except Exception:
            self._toast(f"Guide: {PLAYER_GUIDE}")

    def refresh_nodes(self):
        def go():
            rows = list_nodes()
            self.root.after(0, self._fill_nodes, rows)
        self._bg(go)

    def _fill_nodes(self, rows):
        self.tree.delete(*self.tree.get_children())
        if rows is None:
            self.tree.insert("", "end", text="(headscale not reachable)",
                             values=("", ""))
            return
        for name, ip, state in rows:
            self.tree.insert("", "end", text=name, values=(ip, state))

    # ---- events ----
    def _events_tick(self):
        """Refresh the live event every few seconds so the label tracks changes
        made anywhere (here, the web page, or a hand edit)."""
        self.refresh_events()
        self._update_sched_label()
        self.root.after(6000, self._events_tick)

    def refresh_events(self):
        def go():
            cfg, presets = ev_state()
            self.root.after(0, self._fill_events, cfg, presets)
        self._bg(go)

    def _fill_events(self, cfg, presets):
        # Build the one-click preset buttons once, from whatever the server lists.
        if presets:
            self._ev_presets_list = list(presets)
        if presets and not self._ev_buttons_done:
            for name in presets:
                ttk.Button(self.ev_presets, text=name,
                           command=lambda n=name: self.apply_event_preset(n)
                           ).pack(side="left", padx=3, pady=2)
            self._ev_buttons_done = True
        if cfg:
            self._ev_config = cfg
            self.ev_now.config(
                text=(f"Current event: {cfg.get('event_name', '?')}   "
                      f"(density {cfg.get('spawn_density', '?')}, "
                      f"CP {cfg.get('min_cp', '?')}–{cfg.get('max_cp', '?')})"),
                foreground="#1a8a4a")
        else:
            self.ev_now.config(
                text="Current event: start the game server to change events",
                foreground="#b5651d")

    def apply_event_preset(self, name):
        self._toast(f"Applying event: {name}…")

        def go():
            r = ev_apply_preset(name)
            self.root.after(0, self._after_event, r, name)
        self._bg(go)

    def _after_event(self, r, name):
        if r and not r.get("error"):
            self._toast(f"Event applied: {r.get('event_name', name)}")
            self._append(f"\U0001F389 event -> {r.get('event_name', name)} "
                         f"(density {r.get('spawn_density', '?')})")
            self._fill_events(r, None)
        else:
            self._toast("Couldn't apply event -- is the game server running?")

    def _event_fields(self, parent, cfg, r0=0):
        """Lay the event builder (name / density / species / CP / overcap) into a
        grid starting at row r0. Returns (collect, next_row): call collect() to
        read the widgets back as a config dict. Shared by the custom-event dialog
        and the scheduler so both can pick exactly which Pokemon spawn."""
        cfg = cfg or {}
        pad = {"padx": 6, "pady": 4}

        ttk.Label(parent, text="Name").grid(row=r0, column=0, sticky="e", **pad)
        e_name = ttk.Entry(parent, width=24)
        e_name.grid(row=r0, column=1, columnspan=2, sticky="w", **pad)
        e_name.insert(0, cfg.get("event_name", "My Event"))

        ttk.Label(parent, text="Density (0-60)").grid(row=r0 + 1, column=0,
                                                      sticky="e", **pad)
        e_den = ttk.Spinbox(parent, from_=0, to=60, width=6)
        e_den.grid(row=r0 + 1, column=1, sticky="w", **pad)
        e_den.set(cfg.get("spawn_density", 5))

        ttk.Label(parent, text="Species").grid(row=r0 + 2, column=0,
                                               sticky="ne", **pad)
        mode = tk.StringVar(value=cfg.get("species_mode", "all"))
        ttk.Radiobutton(parent, text="All 151", variable=mode, value="all"
                        ).grid(row=r0 + 2, column=1, sticky="w")
        ttk.Radiobutton(parent, text="From list", variable=mode, value="list"
                        ).grid(row=r0 + 3, column=1, sticky="w")
        ttk.Radiobutton(parent, text="One species", variable=mode, value="single"
                        ).grid(row=r0 + 4, column=1, sticky="w")

        e_list = ttk.Entry(parent, width=20)
        e_list.grid(row=r0 + 3, column=2, sticky="w", **pad)
        e_list.insert(0, ",".join(str(x) for x in
                                  (cfg.get("species_list") or [1, 4, 7, 25])))

        one = ttk.Combobox(parent, width=16, state="readonly",
                           values=[f"{i} {DEX[i]}" for i in range(1, len(DEX))])
        one.grid(row=r0 + 4, column=2, sticky="w", **pad)
        si = int(cfg.get("single_species", 25) or 25)
        one.set(f"{si} {DEX[si]}" if 1 <= si < len(DEX) else "25 Pikachu")

        ttk.Label(parent, text="CP min / max").grid(row=r0 + 5, column=0,
                                                    sticky="e", **pad)
        cpf = ttk.Frame(parent)
        cpf.grid(row=r0 + 5, column=1, columnspan=2, sticky="w", **pad)
        e_min = ttk.Spinbox(cpf, from_=10, to=5000, width=6)
        e_min.pack(side="left")
        e_min.set(cfg.get("min_cp", 100))
        ttk.Label(cpf, text="  –  ").pack(side="left")
        e_max = ttk.Spinbox(cpf, from_=10, to=5000, width=6)
        e_max.pack(side="left")
        e_max.set(cfg.get("max_cp", 1200))

        over = tk.BooleanVar(value=bool(cfg.get("allow_overcap", False)))
        ttk.Checkbutton(parent, text="Allow above-natural CP (overpowered spawns)",
                        variable=over).grid(row=r0 + 6, column=1, columnspan=2,
                                            sticky="w", **pad)

        def _int(widget, default):
            try:
                return int(float(widget.get()))
            except (TypeError, ValueError):
                return default

        def collect():
            try:
                one_id = int(one.get().split()[0])
            except (ValueError, IndexError):
                one_id = 25
            species_list = [int(t) for t in e_list.get().split(",")
                            if t.strip().isdigit()]
            return {
                "event_name": e_name.get().strip() or "Event",
                "spawn_density": _int(e_den, 5),
                "species_mode": mode.get(),
                "species_list": species_list or [25],
                "single_species": one_id,
                "min_cp": _int(e_min, 100),
                "max_cp": _int(e_max, 1200),
                "allow_overcap": bool(over.get()),
            }

        return collect, r0 + 7

    def open_custom_event(self):
        win = tk.Toplevel(self.root)
        win.title("Custom event")
        win.transient(self.root)
        win.resizable(False, False)
        pad = {"padx": 6, "pady": 4}
        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=8, pady=8)

        collect, nr = self._event_fields(frm, self._ev_config or {}, 0)
        msg = ttk.Label(frm, text="", foreground="#b5651d")
        msg.grid(row=nr, column=0, columnspan=3, sticky="w", **pad)

        def apply():
            body = collect()
            msg.config(text="Applying…", foreground="#777")

            def go():
                r = ev_save(body)
                self.root.after(0, done, r)
            self._bg(go)

        def done(r):
            if r and not r.get("error"):
                self._toast(f"Event applied: {r.get('event_name', 'Event')}")
                self._append(f"\U0001F389 event -> {r.get('event_name', 'Event')} "
                             f"(density {r.get('spawn_density', '?')})")
                self._fill_events(r, None)
                win.destroy()
            else:
                msg.config(text="Couldn't apply -- is the game server running?",
                           foreground="#c0392b")

        btns = ttk.Frame(frm)
        btns.grid(row=nr + 1, column=0, columnspan=3, sticky="e", **pad)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Apply event", command=apply).pack(side="right", padx=4)

    # ---- scheduling ----
    # A scheduled event is timed with Tk's own after(): it applies a preset at the
    # start time and (optionally) reverts to another preset when the duration is up.
    # This runs inside the manager, so leave the manager open for the schedule to
    # fire -- it's the always-on control panel you host from anyway.
    def open_schedule_event(self):
        import time as _t
        presets = self._ev_presets_list or list(PRESET_FALLBACK)
        win = tk.Toplevel(self.root)
        win.title("Schedule an event")
        win.transient(self.root)
        win.resizable(False, False)
        pad = {"padx": 6, "pady": 5}
        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # What to run: a custom event (pick the Pokemon) or a named preset.
        ttk.Label(frm, text="What to run").grid(row=0, column=0, sticky="e", **pad)
        src = tk.StringVar(value="custom")
        ttk.Radiobutton(frm, text="Custom event (choose Pokemon)",
                        variable=src, value="custom"
                        ).grid(row=0, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(frm, text="Preset:", variable=src, value="preset"
                        ).grid(row=1, column=1, sticky="w")
        ev_sel = ttk.Combobox(frm, width=18, state="readonly", values=presets)
        ev_sel.grid(row=1, column=2, columnspan=2, sticky="w", **pad)
        ev_sel.set(presets[1] if len(presets) > 1 else presets[0])

        # The full event builder (same one the Custom-event dialog uses).
        collect, nr = self._event_fields(frm, self._ev_config or {}, r0=2)

        ttk.Separator(frm, orient="horizontal").grid(row=nr, column=0,
                                                     columnspan=4, sticky="ew",
                                                     pady=8)
        r = nr + 1
        ttk.Label(frm, text="Start").grid(row=r, column=0, sticky="e", **pad)
        smode = tk.StringVar(value="in")
        ttk.Radiobutton(frm, text="In", variable=smode, value="in"
                        ).grid(row=r, column=1, sticky="w")
        e_inmin = ttk.Spinbox(frm, from_=0, to=1440, width=6)
        e_inmin.set(0)
        e_inmin.grid(row=r, column=2, sticky="w")
        ttk.Label(frm, text="minutes").grid(row=r, column=3, sticky="w")
        ttk.Radiobutton(frm, text="At (HH:MM)", variable=smode, value="at"
                        ).grid(row=r + 1, column=1, sticky="w")
        e_at = ttk.Entry(frm, width=8)
        e_at.grid(row=r + 1, column=2, sticky="w")
        e_at.insert(0, _t.strftime("%H:%M", _t.localtime(_t.time() + 3600)))

        ttk.Label(frm, text="Duration").grid(row=r + 2, column=0, sticky="e", **pad)
        e_dur = ttk.Spinbox(frm, from_=0, to=1440, width=6)
        e_dur.set(60)
        e_dur.grid(row=r + 2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="minutes  (0 = until I change it)"
                  ).grid(row=r + 2, column=2, columnspan=2, sticky="w")

        ttk.Label(frm, text="Then revert to").grid(row=r + 3, column=0,
                                                   sticky="e", **pad)
        rev_sel = ttk.Combobox(frm, width=18, state="readonly", values=presets)
        rev_sel.grid(row=r + 3, column=1, columnspan=2, sticky="w", **pad)
        rev_sel.set("Normal" if "Normal" in presets else presets[0])

        msg = ttk.Label(frm, text="", foreground="#b5651d")
        msg.grid(row=r + 4, column=0, columnspan=4, sticky="w", **pad)

        def do_schedule():
            now = _t.time()
            if smode.get() == "in":
                try:
                    mins = max(0, int(float(e_inmin.get())))
                except (TypeError, ValueError):
                    mins = 0
                start_ts = now + mins * 60
            else:
                try:
                    hh, mm = (int(x) for x in e_at.get().strip().split(":"))
                    import datetime as _dt
                    lt = _t.localtime(now)
                    start_ts = _dt.datetime(lt.tm_year, lt.tm_mon, lt.tm_mday,
                                            hh, mm).timestamp()
                    if start_ts <= now:            # already past today -> tomorrow
                        start_ts += 86400
                except (ValueError, OverflowError):
                    msg.config(text="Time must look like 20:30 (24-hour)")
                    return
            try:
                dur = max(0, int(float(e_dur.get())))
            except (TypeError, ValueError):
                dur = 0
            if src.get() == "preset":
                name = ev_sel.get() or presets[0]
                spec = {"kind": "preset", "name": name}
            else:
                cfg = collect()
                name = cfg["event_name"]
                spec = {"kind": "custom", "cfg": cfg}
            self._schedule_set(name, spec, start_ts, dur, rev_sel.get() or "Normal")
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=r + 5, column=0, columnspan=4, sticky="e", **pad)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Schedule", command=do_schedule).pack(side="right", padx=4)

    def _schedule_set(self, event, spec, start_ts, duration_min, revert):
        import time as _t
        self._sched_cancel_timers()
        delay_ms = max(0, int((start_ts - _t.time()) * 1000))
        sid = self.root.after(delay_ms, self._sched_start)
        self._sched = {"event": event, "spec": spec, "revert": revert,
                       "duration": duration_min, "start_ts": start_ts,
                       "end_ts": (start_ts + duration_min * 60) if duration_min else None,
                       "start_id": sid, "end_id": None, "active": False}
        self._update_sched_label()
        self._write_schedule_file()
        when = _t.strftime("%H:%M", _t.localtime(start_ts))
        self._toast(f"Scheduled {event} at {when}")
        self._append(f"⏰ scheduled '{event}' at {when}"
                     + (f" for {duration_min} min → {revert}"
                        if duration_min else " (no auto-revert)"))

    def _apply_spec(self, spec):
        """Apply a scheduled event, whether it's a named preset or a full custom
        config (with its own species list)."""
        if spec and spec.get("kind") == "custom":
            self.apply_event_custom(spec["cfg"])
        else:
            self.apply_event_preset((spec or {}).get("name", "Normal"))

    def apply_event_custom(self, cfg):
        self._toast(f"Applying event: {cfg.get('event_name', 'Event')}…")

        def go():
            r = ev_save(cfg)
            self.root.after(0, self._after_event, r, cfg.get("event_name", "Event"))
        self._bg(go)

    def _sched_start(self):
        s = self._sched
        if not s:
            return
        self._apply_spec(s.get("spec"))
        s["active"] = True
        s["start_id"] = None
        if s.get("duration"):
            s["end_id"] = self.root.after(int(s["duration"] * 60 * 1000),
                                          self._sched_end)
        self._update_sched_label()
        self._write_schedule_file()      # now live -> clears the "upcoming" board

    def _sched_end(self):
        s = self._sched
        if not s:
            return
        revert = s.get("revert") or "Normal"
        self.apply_event_preset(revert)
        self._append(f"⏰ scheduled event ended → {revert}")
        self._sched = None
        self._update_sched_label()
        self._write_schedule_file()

    def _sched_cancel_timers(self):
        s = self._sched
        if not s:
            return
        for k in ("start_id", "end_id"):
            if s.get(k):
                try:
                    self.root.after_cancel(s[k])
                except Exception:
                    pass

    def cancel_schedule(self):
        s = self._sched
        if not s:
            return
        self._sched_cancel_timers()
        active, revert = s.get("active"), s.get("revert")
        self._sched = None
        self._update_sched_label()
        self._write_schedule_file()
        if active and revert:
            self.apply_event_preset(revert)
            self._toast(f"Schedule cancelled -- reverted to {revert}")
            self._append(f"⏰ schedule cancelled → {revert}")
        else:
            self._toast("Schedule cancelled")
            self._append("⏰ schedule cancelled")

    def _update_sched_label(self):
        import time as _t
        s = self._sched
        if not s:
            self.ev_sched.config(text="")
            self.btn_sched_cancel.config(state="disabled")
            return
        self.btn_sched_cancel.config(state="normal")
        now = _t.time()
        if not s.get("active"):
            mins = max(0, int(round((s["start_ts"] - now) / 60)))
            when = _t.strftime("%H:%M", _t.localtime(s["start_ts"]))
            tail = (f" for {s['duration']} min → {s['revert']}"
                    if s.get("duration") else "")
            self.ev_sched.config(
                text=f"⏰ Scheduled: {s['event']} at {when} (in {mins} min){tail}")
        elif s.get("end_ts"):
            mins = max(0, int(round((s["end_ts"] - now) / 60)))
            when = _t.strftime("%H:%M", _t.localtime(s["end_ts"]))
            self.ev_sched.config(
                text=f"⏰ {s['event']} running → {s['revert']} "
                     f"at {when} (in {mins} min)")
        else:
            self.ev_sched.config(
                text=f"⏰ {s['event']} running (no auto-revert)")

    def _spec_detail(self, spec):
        """A short, player-friendly line about a scheduled event's Pokemon, for
        the in-game Help Center. Presets need none -- their name says it."""
        if not spec:
            return ""
        if spec.get("kind") == "custom":
            cfg = spec.get("cfg") or {}
            mode = cfg.get("species_mode", "all")
            if mode == "single":
                i = int(cfg.get("single_species", 25) or 25)
                who = DEX[i] if 1 <= i < len(DEX) else f"#{i}"
                sp = f"{who} everywhere"
            elif mode == "list":
                names = [DEX[i] for i in (cfg.get("species_list") or [])
                         if 1 <= i < len(DEX)]
                sp = (", ".join(names[:6]) + (", and more" if len(names) > 6 else "")
                      if names else "a themed line-up")
            else:
                sp = "All Pokemon"
            return f"{sp} · CP {cfg.get('min_cp', '?')}-{cfg.get('max_cp', '?')}"
        return ""

    def _write_schedule_file(self):
        """Publish the PENDING schedule to event_schedule.json for the Help Center.
        Once an event starts it becomes the live event (events.json), so only
        not-yet-started schedules are written; anything else clears the file."""
        s = self._sched
        try:
            os.makedirs(GAME_DATA, exist_ok=True)
            if s and not s.get("active"):
                data = {"upcoming": [{
                    "event_name": s.get("event", "Event"),
                    "start_ts": s.get("start_ts"),
                    "end_ts": s.get("end_ts"),
                    "revert": s.get("revert"),
                    "detail": self._spec_detail(s.get("spec")),
                }]}
            else:
                data = {"upcoming": []}
            with open(SCHEDULE_JSON, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except OSError:
            pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
