"""
Project Windstock -- the game server's own window.

Replaces the old black console: same look as PoGO-Manager (clam theme, labelled
sections, status dots, dark activity pane), branded Windstock. The server itself
is unchanged -- run.main() runs on a background thread and everything it prints
goes to the log file AND this window.

The exe is built from this file (Start-Pokemon-GO-Server.spec, console=False).
`py run.py` still gives the plain console version.
"""
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import run  # noqa: E402  (after sys.path is set)

BRAND_DIR = os.path.join(BASE, "brand")
BLUE = "#0b44a8"          # the Windstock logo blue
DOT_OK, DOT_BAD, DOT_WAIT = "#2ecc71", "#e74c3c", "#888888"
MAX_LOG_LINES = 3000


# ---- friendly activity ------------------------------------------------------
ITEM_NAMES = {1: "Pok\u00e9 Ball", 2: "Great Ball", 3: "Ultra Ball", 4: "Master Ball",
              101: "Potion", 102: "Super Potion", 103: "Hyper Potion", 104: "Max Potion",
              201: "Revive", 202: "Max Revive", 301: "Lucky Egg", 401: "Incense",
              501: "Lure Module", 701: "Razz Berry", 901: "Unlimited Incubator",
              902: "Egg Incubator", 1001: "Pok\u00e9mon Storage Upgrade",
              1002: "Bag Upgrade"}
TEAMS = {"1": "Mystic", "2": "Valor", "3": "Instinct"}
BALLS = {"1": "Pok\u00e9 Ball", "2": "Great Ball", "3": "Ultra Ball", "4": "Master Ball"}

# Background traffic the phone sends every few seconds -- never shown.
ROUTINE = {"GET_INVENTORY", "DOWNLOAD_SETTINGS", "CHECK_CHALLENGE", "GET_HATCHED_EGGS",
           "GET_DOWNLOAD_URLS", "CHECK_AWARDED_BADGES", "GET_PLAYER",
           "GET_INCENSE_POKEMON", "ECHO"}


def species(n):
    try:
        from admin import DEX
        return DEX[int(n)] or f"#{n}"
    except Exception:
        return f"#{n}"


def item_name(n, count=None):
    name = ITEM_NAMES.get(int(n), f"item {n}")
    return f"{count} \u00d7 {name}" if count is not None else name


def mon_ref(text):
    """'#25 CP312' anywhere in `text` -> 'Pikachu (CP 312)'; '' if absent."""
    m = re.search(r"#(\d+) CP ?(\d+)", text)
    return f"{species(m.group(1))} (CP {m.group(2)})" if m else "a Pok\u00e9mon"


def fort_kind(text):
    return "Gym" if re.search(r"\.16'?\b", text) else "Pok\u00e9Stop"


class Humanizer:
    """Turn raw server-log lines into plain-English lines (None = hide).

    Every request the phone makes is described with its details (which
    Pokemon, which items, what happened); the constant background syncing is
    hidden, and start-up steps are shown once per trainer per session."""

    # A request batch: "06:35:58  [bracky67]  SET_AVATAR, CHECK_CHALLENGE, ...".
    # System lines look similar ("15:17:36  [tls] handshake FAILED"), so the
    # rest of the line must be request names only.
    _HEADER = re.compile(r"^\d\d:\d\d:\d\d\s+\[([^\]]+)\]\s+[A-Z_0-9]+(?:, [A-Z_0-9]+)*\s*$")
    _REPLY = re.compile(r"^\d\d:\d\d:\d\d\s+-> (.*)$")

    def __init__(self):
        self.user = None
        self.seen = set()          # trainers already announced this session
        self.last_seen = None
        self.once = set()          # (trainer, step) already shown
        self.target = {}           # trainer -> species they're trying to catch
        self.recent = {}           # message -> when last shown (repeat filter)

    def _first(self, key, text):
        k = (self.user, key)
        if k in self.once:
            return None
        self.once.add(k)
        return text

    def __call__(self, line):
        m = self._HEADER.match(line)
        if m:
            self.user = m.group(1)
            self.last_seen = self.user
            if self.user not in self.seen:
                self.seen.add(self.user)
                return f"\U0001F464 {self.user} connected"
            return None
        r = self._REPLY.match(line)
        text = self._reply(r.group(1)) if r else self._system(line)
        # The phone re-asks while a screen stays open (a Gym refreshes every few
        # seconds): show the same line for the same trainer once per 30 s.
        if text:
            now = time.time()
            if self.recent.get(text, 0) > now - 30:
                return None
            self.recent[text] = now
            if len(self.recent) > 500:
                self.recent = {k: v for k, v in self.recent.items() if v > now - 30}
        return text

    # ---- one reply line per request ----
    def _reply(self, s):
        who = self.user or "A player"
        name = s.split(" ", 1)[0].rstrip(":")
        if name in ROUTINE or s.split(" ", 1)[0] in ROUTINE:
            return None

        if s.startswith("config version check"):
            plat = re.search(r"\[(\w+)\]", s)
            ver = re.search(r"client v([\d.]+)", s)
            v = ver.group(1) if ver else ""
            v = {"2.90": "0.29", "3.50": "0.35"}.get(v, v)
            p = {"ios": "iPhone", "android": "Android"}.get(
                plat.group(1).lower(), plat.group(1)) if plat else ""
            return self._first("boot", f"\U0001F4F2 {who} is loading the game"
                                + (f" ({p}, v{v})" if p else ""))
        if s.startswith(("asset digest", "handshake", "game master")):
            return None
        if name == "GET_MAP_OBJECTS":
            return self._first("map", f"\U0001F5FA {who} arrived on the map")

        if name == "ENCOUNTER" or name in ("INCENSE_ENCOUNTER", "DISK_ENCOUNTER"):
            mm = re.search(r"#(\d+) cp(\d+)", s)
            if mm:
                self.target[self.user] = species(mm.group(1))
                src = {"INCENSE_ENCOUNTER": " (Incense)",
                       "DISK_ENCOUNTER": " (Lure)"}.get(name, "")
                return (f"\U0001F43E {who} found a wild {species(mm.group(1))}"
                        f" (CP {mm.group(2)}){src}")
            return f"\U0001F43E {who} tapped a Pok\u00e9mon that had already left"
        if name == "CATCH_POKEMON":
            mon = self.target.get(self.user, "the Pok\u00e9mon")
            ball = BALLS.get((re.search(r"ball=(\d+)", s) or [None, "1"])[1], "ball")
            if "CAUGHT" in s:
                bonus = re.search(r"\((\w+) throw! \+(\d+) XP\)", s)
                return (f"\U0001F534 {who} caught {mon} with a {ball}"
                        + (f" \u2014 {bonus.group(1)} throw, +{bonus.group(2)} XP"
                           if bonus else ""))
            if "broke out" in s:
                return f"\u26AA {mon} broke out of {who}'s {ball}"
            if "fled" in s:
                return f"\U0001F4A8 {mon} ran away from {who}"
            if "missed" in s:
                return f"\u2796 {who} threw a {ball} at {mon} and missed"
            return None
        if name == "USE_ITEM_CAPTURE":
            return f"\U0001F353 {who} fed a Razz Berry" if "Razz" in s else None

        if name == "FORT_DETAILS":
            return f"\U0001F535 {who} opened a {fort_kind(s)}"
        if name == "FORT_SEARCH":
            got = re.findall(r"item(\d+)x(\d+)", s)
            xp = re.search(r"\+(\d+)xp", s)
            if "BAG FULL" in s:
                return f"\U0001F392 {who} spun a Pok\u00e9Stop but their bag is full"
            items = ", ".join(item_name(i, int(c)) for i, c in got)
            return (f"\U0001F535 {who} spun a Pok\u00e9Stop"
                    + (f": {items}" if items else "")
                    + (f" (+{xp.group(1)} XP)" if xp else ""))
        if name == "ADD_FORT_MODIFIER":
            return (f"\U0001F338 {who} put a Lure on a Pok\u00e9Stop" if "attached" in s
                    else f"\U0001F338 {who} tried to add a Lure: {s.split('-> ')[-1]}")

        if name == "GET_GYM_DETAILS":
            n = re.search(r"\((\d+) defenders?\)", s)
            return (f"\U0001F3DF {who} looked at a Gym"
                    + (f" ({n.group(1)} defender{'s' if n.group(1) != '1' else ''})"
                       if n else ""))
        if name == "FORT_DEPLOY_POKEMON":
            return f"\U0001F6E1 {who} put a Pok\u00e9mon in a Gym to defend it"
        if s.startswith("gym battle START"):
            mm = re.search(r"your #(\d+) \(CP (\d+)\) vs their #(\d+) \(CP (\d+)\)", s)
            if mm:
                return (f"\u2694 {who} started a Gym battle: {species(mm.group(1))} "
                        f"(CP {mm.group(2)}) vs {species(mm.group(3))} (CP {mm.group(4)})")
            return f"\u2694 {who} started a Gym battle"
        if s.startswith("gym battle:"):
            out = s.split("-> ", 1)[-1]
            return f"\u2694 {who}'s Gym battle: {out}" if re.search(
                r"won|lost|victory|defeat|fled|timed", out, re.I) else None
        if name == "COLLECT_DAILY_DEFENDER_BONUS":
            mm = re.search(r"paid \[(\d+), (\d+)\]", s)
            return (f"\U0001FA99 {who} collected the defender bonus: {mm.group(1)} coins, "
                    f"{mm.group(2)} stardust" if mm else
                    f"\U0001FA99 {who} checked the defender bonus")
        if name == "FORT_RECALL_POKEMON":
            return f"\U0001F6E1 {who} called a defender back from a Gym"

        if name == "RELEASE_POKEMON":
            return f"\U0001F44B {who} transferred {mon_ref(s)} to the Professor"
        if name == "UPGRADE_POKEMON":
            return (f"\u2B06 {who} powered up {mon_ref(s)}" if "powered up" in s else
                    f"\u2B06 {who} couldn't power up: {s.split('-> ')[-1]}")
        if name == "EVOLVE_POKEMON":
            return (f"\u2728 {who} evolved {mon_ref(s)}" if "evolved" in s else
                    f"\u2728 {who} couldn't evolve: {s.split('-> ')[-1]}")
        if name == "NICKNAME_POKEMON":
            nick = re.search(r"= '(.*)'$", s)
            return (f"\u270F {who} renamed {mon_ref(s)}"
                    + (f" to \u201c{nick.group(1)}\u201d" if nick else ""))
        if name == "SET_FAVORITE_POKEMON":
            return (f"\u2B50 {who} {'favorited' if 'fav=True' in s else 'unfavorited'} "
                    f"{mon_ref(s)}")
        if name in ("USE_ITEM_POTION", "USE_ITEM_REVIVE"):
            hp = re.search(r"healed to (\d+) HP", s)
            verb = "revived" if name == "USE_ITEM_REVIVE" else "healed"
            return (f"\U0001F48A {who} {verb} a Pok\u00e9mon"
                    + (f" ({hp.group(1)} HP)" if hp else f": {s.split('-> ')[-1]}"))
        if name == "RECYCLE_INVENTORY_ITEM":
            mm = re.search(r"item=(\d+) x(\d+)", s)
            return (f"\U0001F5D1 {who} threw away {item_name(mm.group(1), mm.group(2))}"
                    if mm else None)

        if name == "USE_ITEM_XP_BOOST":
            return f"\U0001F95A {who} used a Lucky Egg (double XP)" if "active" in s else None
        if name == "USE_INCENSE":
            return f"\U0001F56F {who} lit an Incense" if "burning" in s else None
        if name == "USE_ITEM_EGG_INCUBATOR":
            res = s.split("-> ")[-1]
            return (f"\U0001F95A {who} put an egg in an incubator" if res == "incubating"
                    else f"\U0001F95A {who} couldn't incubate an egg: {res}")
        if name == "LEVEL_UP_REWARDS":
            mm = re.search(r"level (\d+): SUCCESS", s)
            return f"\U0001F389 {who} reached level {mm.group(1)}!" if mm else None
        if name == "GET_PLAYER_PROFILE":
            return f"\U0001F3C5 {who} opened their profile"
        if name == "JOURNAL":
            n = re.search(r"(\d+) entr", s)
            return (f"\U0001F4D6 {who} opened their Journal"
                    + (f" ({n.group(1)} entries)" if n else ""))
        if name == "EQUIP_BADGE":
            return f"\U0001F3C5 {who} equipped a medal"
        if name == "SET_AVATAR":
            return None if "nothing sent" in s else f"\U0001F455 {who} changed their look"
        if name == "SET_CONTACT_SETTINGS":
            return f"\u2699 {who} changed their settings"
        if name == "SET_PLAYER_TEAM":
            mm = re.search(r"joined (\w+)", s)
            return (f"\U0001F6A9 {who} joined Team {TEAMS.get(mm.group(1), mm.group(1))}"
                    if mm else None)
        if name == "CLAIM_CODENAME":
            mm = re.search(r"'(.+?)'", s)
            return f"\U0001F4DB {who} chose the name {mm.group(1)}" if mm else None
        if name == "ENCOUNTER_TUTORIAL_COMPLETE":
            mm = re.search(r"#(\d+)", s)
            return (f"\U0001F331 {who} picked {species(mm.group(1))} as their starter"
                    if mm else None)
        if name == "MARK_TUTORIAL_COMPLETE":
            return f"\U0001F4D8 {who} finished a tutorial step"
        if name == "PLAYER_UPDATE":
            return None

        mm = re.search(r"^([A-Z_]+) \(#(\d+)\) empty response", s)
        if mm:
            return (f"\u2754 {who}'s phone asked for {mm.group(1)} (#{mm.group(2)}),"
                    " which the server doesn't handle")
        if re.match(r"^[A-Z_]{4,}", name):
            return f"\u2022 {who}: {name.replace('_', ' ').lower()}"
        return None

    # ---- non-request lines ----
    def _system(self, line):
        who = self.user or "A player"
        mm = re.search(r"\[shop\] BUY \S+ -> OK: got (.+?) \(now", line)
        if mm:
            return f"\U0001F6D2 {who} bought {mm.group(1)} in the Shop"
        mm = re.search(r"\[shop\] BUY \S+ -> NO: (.+?) \(\d+ coins\)", line)
        if mm:
            return f"\U0001F6D2 {who} couldn't buy that: {mm.group(1)}"
        if "[shop] -> in-game shop" in line:
            return f"\U0001F6CD {who} opened the Shop"
        mm = re.search(r"\[egg\] a ([\d.]+) km egg hatched into #(\d+) CP(\d+)", line)
        if mm:
            return (f"\U0001F423 {who}'s {mm.group(1)} km egg hatched into "
                    f"{species(mm.group(2))} (CP {mm.group(3)})!")
        mm = re.search(r"\[gym\] defender #(\d+) came home .*\+(\d+) Poke", line)
        if mm:
            return (f"\U0001F3E0 {who}'s {species(mm.group(1))} came home from a Gym "
                    f"(+{mm.group(2)} coins)")
        if "[ptc] login page issued" in line:
            return "\U0001F511 Someone is logging in\u2026"
        if "[tls]" in line or "[dns]" in line or "[map]" in line:
            return None      # handshakes, lookups, map builds: normal, noisy
        # A phone dropping its connection prints a whole traceback ending in
        # ConnectionResetError -- normal on mobile, not worth a warning. Only a
        # real exception's closing line ("KeyError: ...") is shown.
        s = line.strip()
        mm = re.match(r"^([A-Za-z_.]+(?:Error|Exception)): (.*)", s)
        if mm and not re.search(r"Connection(Reset|Aborted)|BrokenPipe|SSLEOF|"
                                r"TimeoutError|socket\.timeout", mm.group(1) + mm.group(2)):
            return "\u26A0 Server error: " + s[:140]
        if s.startswith(("!!", "[bridge] restarting", "[dns] restarting")):
            return "\u26A0 " + s.lstrip("!").strip()[:140]
        return None


# ---- stdout -> window --------------------------------------------------------
class QueueStream:
    """File-like object: whole lines go onto a queue for the Tk thread."""

    def __init__(self, q):
        self.q = q
        self.buf = ""
        self.lock = threading.Lock()

    def write(self, text):
        with self.lock:
            self.buf += text
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                self.q.put(line)
        return len(text)

    def flush(self):
        pass


# ---- status probes -------------------------------------------------------------
def tcp_up(port, host="127.0.0.1", timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# The game server, DNS and login bridge are judged by their own startup lines,
# NOT by poking their ports: every probe of :443 logs a failed TLS handshake and
# every DNS probe logs a lookup, which buried the real activity. Each part
# restarts itself on failure and announces again when it comes back.
READY_MARKERS = {
    "game": "PoGO private server listening",
    "dns": "DNS redirector on",
    "bridge": "[bridge] http://",
}
DOWN_MARKERS = {
    "dns": "[dns] restarting after",
    "bridge": "[bridge] restarting after",
}


def admin_port():
    try:
        import settings as _cfg
        return int(_cfg.get("server", "world_manager_port", env="ADMIN_PORT", cast=int))
    except Exception:
        return int(os.environ.get("ADMIN_PORT", "8080"))


def data_dir():
    try:
        import datadir
        return datadir.ensure()
    except Exception:
        return os.path.join(os.path.dirname(sys.executable), "data")


def open_path(path):
    try:
        os.startfile(path)                     # Windows
    except AttributeError:
        subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


# ============================ window ==========================================
class ServerWindow:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.human = Humanizer()
        self.raw = tk.BooleanVar(value=False)
        self.lines = []                        # (raw, friendly) for re-filtering
        self.ip = (sys.argv[1] if len(sys.argv) > 1
                   else os.environ.get("RUN_IP") or run.detect_ip())
        self.others = [i for i in run._local_ips() if run._usable(i) and i != self.ip]
        self.aport = admin_port()
        self.started = time.time()
        self.ready = {"game": False, "dns": False, "bridge": False}
        self.server_alive = True
        self._images = []                      # keep PhotoImages alive

        root.title("Project Windstock \u2014 Pok\u00e9mon GO Server")
        root.geometry("860x680")
        root.minsize(720, 540)
        self._set_icon()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.stop)

        threading.Thread(target=self._run_server, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        root.after(100, self._drain)
        root.after(1000, self._tick)

    # ---- branding ----
    def _img(self, name):
        try:
            im = tk.PhotoImage(file=os.path.join(BRAND_DIR, name))
            self._images.append(im)
            return im
        except Exception:
            return None

    def _set_icon(self):
        ico = os.path.join(BRAND_DIR, "windstock.ico")
        try:
            self.root.iconbitmap(default=ico)
        except Exception:
            icon = self._img("windstock_icon.png")
            if icon:
                self.root.iconphoto(True, icon)

    # ---- layout ----
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Big.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Stop.TButton", foreground="#b3261e")

        # header banner
        head = tk.Frame(self.root, bg="white", highlightthickness=0)
        head.pack(fill="x")
        mark = self._img("windstock_mark.png")
        if mark:
            tk.Label(head, image=mark, bg="white").pack(side="left", padx=(10, 8), pady=6)
        titles = tk.Frame(head, bg="white")
        titles.pack(side="left", pady=6)
        tk.Label(titles, text="PROJECT WINDSTOCK", bg="white", fg=BLUE,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(titles, text="Pok\u00e9mon GO 0.29 / 0.35 private server",
                 bg="white", fg="#556", font=("Segoe UI", 10)).pack(anchor="w")
        self.state_lbl = tk.Label(head, text="\u25CF Starting\u2026", bg="white",
                                  fg="#c98a00", font=("Segoe UI", 13, "bold"))
        self.state_lbl.pack(side="right", padx=16)
        tk.Frame(self.root, bg=BLUE, height=3).pack(fill="x")

        # status dots
        top = ttk.LabelFrame(self.root, text="Status")
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.dots = {}
        env = os.environ.get
        comps = [("game", f"Game Server ({env('PORT', '443')})"),
                 ("bridge", f"Login Bridge ({env('SSO_BRIDGE_PORT', '80')})"),
                 ("dns", f"DNS Redirect ({env('DNS_PORT', '53')})"),
                 ("admin", f"World Manager ({self.aport})")]
        for i, (key, label) in enumerate(comps):
            f = ttk.Frame(top)
            f.grid(row=0, column=i, padx=10, pady=6, sticky="w")
            dot = tk.Label(f, text="\u25CF", fg=DOT_WAIT, font=("Segoe UI", 12))
            dot.pack(side="left")
            ttk.Label(f, text=label).pack(side="left")
            self.dots[key] = dot

        # connect a phone
        con = ttk.LabelFrame(self.root, text="Connect a phone")
        con.pack(fill="x", padx=8, pady=4)
        r1 = ttk.Frame(con); r1.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(r1, text="Set the phone's Wi-Fi DNS to:").pack(side="left")
        self.ip_var = tk.StringVar(value=self.ip)
        ent = ttk.Entry(r1, textvariable=self.ip_var, width=18, font=("Consolas", 12, "bold"),
                        state="readonly")
        ent.pack(side="left", padx=8)
        ttk.Button(r1, text="\U0001F4CB Copy", command=self.copy_ip).pack(side="left")
        ttk.Label(r1, text="(leave DNS 2 blank)", foreground="#777").pack(side="left", padx=8)
        if self.others:
            ttk.Label(con, text="This PC is also reachable at: " + ", ".join(self.others)
                      + "  \u2014 use one of these if the phone can't connect.",
                      foreground="#777").pack(anchor="w", padx=6, pady=(0, 6))

        # controls
        ctl = ttk.LabelFrame(self.root, text="Controls")
        ctl.pack(fill="x", padx=8, pady=4)
        ttk.Button(ctl, text="\U0001F30D Open World Manager",
                   command=self.open_manager).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(ctl, text="\U0001F4C1 Open Data Folder",
                   command=lambda: open_path(data_dir())).grid(row=0, column=1, padx=6)
        ttk.Button(ctl, text="\U0001F4C4 Open Log File",
                   command=lambda: open_path(os.path.join(data_dir(), "server-log.txt"))
                   ).grid(row=0, column=2, padx=6)
        ttk.Button(ctl, text="\u25A0 Stop Server", style="Stop.TButton",
                   command=self.stop).grid(row=0, column=3, padx=6)

        # activity
        lf = ttk.LabelFrame(self.root, text="Activity")
        lf.pack(fill="both", expand=True, padx=8, pady=4)
        bar = ttk.Frame(lf); bar.pack(fill="x")
        ttk.Checkbutton(bar, text="Raw log", variable=self.raw,
                        command=self._refilter).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=self._clear).pack(side="right", padx=4)
        body = ttk.Frame(lf); body.pack(fill="both", expand=True, padx=4, pady=4)
        self.log = tk.Text(body, height=14, wrap="word", bg="#0f1720", fg="#d6e2f0",
                           insertbackground="#d6e2f0", font=("Consolas", 9),
                           state="disabled", relief="flat")
        sb = ttk.Scrollbar(body, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("warn", foreground="#ffb4a8")
        self.log.tag_configure("time", foreground="#6f8399")

        self.status = ttk.Label(self.root, text="", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    # ---- server thread ----
    def _run_server(self):
        stream = QueueStream(self.q)
        try:
            run.main(ui_stream=stream)
            self.q.put("!! The game server stopped.")
        except SystemExit:
            self.q.put("!! The game server could not start (see the messages above).")
        except Exception as e:                  # never let the window die with it
            self.q.put(f"!! The game server crashed: {type(e).__name__}: {e}")
        self.server_alive = False

    # ---- status polling ----
    def _poll_loop(self):
        while True:
            st = dict(self.ready)
            st["game"] = st["game"] and self.server_alive
            st["admin"] = tcp_up(self.aport)    # plain HTTP, logs nothing
            self.root.after(0, self._apply_status, st)
            time.sleep(2)

    def _note_status(self, raw):
        for key, marker in READY_MARKERS.items():
            if marker in raw:
                self.ready[key] = True
        for key, marker in DOWN_MARKERS.items():
            if marker in raw:
                self.ready[key] = False

    def _apply_status(self, st):
        grace = time.time() - self.started < 8          # still booting
        for key, ok in st.items():
            self.dots[key].configure(fg=DOT_OK if ok else (DOT_WAIT if grace else DOT_BAD))
        if st["game"] and st["dns"]:
            self.state_lbl.configure(text="\u25CF Running", fg="#1e9e57")
        elif grace:
            self.state_lbl.configure(text="\u25CF Starting\u2026", fg="#c98a00")
        else:
            self.state_lbl.configure(text="\u25CF Problem", fg="#d0342c")

    def _tick(self):
        up = int(time.time() - self.started)
        h, m = divmod(up // 60, 60)
        who = self.human.last_seen
        self.status.configure(
            text=f"  Up {h}h {m:02d}m   \u00b7   Trainers seen this session: "
                 f"{len(self.human.seen)}" + (f"   \u00b7   Last active: {who}" if who else ""))
        self.root.after(1000, self._tick)

    # ---- activity pane ----
    def _drain(self):
        added = False
        try:
            while True:
                raw = self.q.get_nowait()
                self._note_status(raw)
                friendly = self.human(raw)
                if raw.startswith("!!"):
                    friendly = "\u26A0 " + raw[2:].strip()
                self.lines.append((raw, friendly))
                self._show(raw, friendly)
                added = True
        except queue.Empty:
            pass
        if len(self.lines) > MAX_LOG_LINES:
            self.lines = self.lines[-MAX_LOG_LINES:]
        if added:
            self._trim()
        self.root.after(100, self._drain)

    def _show(self, raw, friendly):
        if self.raw.get():
            text, tag = raw, ("warn" if raw.startswith("!!") else None)
        elif friendly:
            text, tag = friendly, ("warn" if friendly.startswith("\u26A0") else None)
        else:
            return
        at_end = self.log.yview()[1] > 0.98
        self.log.configure(state="normal")
        if not self.raw.get():
            self.log.insert("end", time.strftime("%H:%M  "), "time")
        self.log.insert("end", text + "\n", tag or ())
        self.log.configure(state="disabled")
        if at_end:
            self.log.see("end")

    def _trim(self):
        n = int(self.log.index("end-1c").split(".")[0])
        if n > MAX_LOG_LINES:
            self.log.configure(state="normal")
            self.log.delete("1.0", f"{n - MAX_LOG_LINES}.0")
            self.log.configure(state="disabled")

    def _refilter(self):
        self._clear(keep=True)
        for raw, friendly in self.lines[-800:]:
            self._show(raw, friendly)
        self.log.see("end")

    def _clear(self, keep=False):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        if not keep:
            self.lines.clear()

    # ---- actions ----
    def copy_ip(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.ip)
        self.status.configure(text=f"  Copied {self.ip}")

    def open_manager(self):
        webbrowser.open(f"http://127.0.0.1:{self.aport}")

    def stop(self):
        if messagebox.askokcancel(
                "Stop the server?",
                "Stop the Pok\u00e9mon GO server?\n\nEveryone playing will be disconnected.",
                icon="warning", parent=self.root):
            try:
                sys.stdout.flush()
            except Exception:
                pass
            os._exit(0)


def run_in_console():
    """The old look: a real black console window, raw server text, Ctrl-C to stop.

    The exe is built windowed (no console attached), so ask Windows for one and
    point stdout/stderr at it -- then run exactly what `py run.py` runs."""
    try:
        import ctypes
        ctypes.windll.kernel32.AllocConsole()
        ctypes.windll.kernel32.SetConsoleTitleW("Pokémon GO Server")
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")
        sys.__stdout__, sys.__stderr__ = sys.stdout, sys.stderr
        sys.stdin = open("CONIN$", "r")
    except Exception:
        pass                      # no console to be had: still runs, just silent
    run.main()


def window_style():
    try:
        import settings as _cfg
        return str(_cfg.get("server", "window")).strip().lower()
    except Exception:
        return "windstock"


def main():
    # settings.json -> server.window: "console" brings back the old black window.
    if window_style() == "console":
        run_in_console()
        return
    root = tk.Tk()
    ServerWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
