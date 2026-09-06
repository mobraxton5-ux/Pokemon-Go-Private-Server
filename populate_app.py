"""
Tiny local web app to populate the world with PokeStops/Gyms, one country at a
time -- and never the same country twice.

It lists countries, locks the ones already done (a ledger records them), and for a
fresh one it downloads that country's Geofabrik OSM extract and appends its POIs to
the live osm_forts.json (via fetch_pois_pbf). No Overpass, no rate limits. The
running game server hot-reloads osm_forts.json, so a country goes playable a few
seconds after it finishes.

Deliberately plain: no CSS, no JavaScript. The page just meta-refreshes every few
seconds so you can watch progress.

Run:
  py ../tools/populate_app.py           # serves http://localhost:8090
  py ../tools/populate_app.py 8099      # custom port
"""
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import fetch_pois_pbf as pf   # noqa: E402  (_download, _extract, base rules)


def _project_root():
    d = HERE
    for _ in range(8):
        if (os.path.isdir(os.path.join(d, "RELEASE"))
                and os.path.isdir(os.path.join(d, "server"))):
            return d
        p = os.path.dirname(d)
        if p == d:
            break
        d = p
    return os.path.abspath(os.path.join(HERE, "..", ".."))


ROOT = _project_root()
DATA = os.path.join(ROOT, "RELEASE", "data")           # the LIVE data the server reads
FORTS_FILE = os.path.join(DATA, "osm_forts.json")
LEDGER = os.path.join(DATA, "populated_regions.json")

# Country -> Geofabrik region. Add more from https://download.geofabrik.de/ any time.
COUNTRIES = {
    "Austria": "europe/austria", "Germany": "europe/germany",
    "Switzerland": "europe/switzerland", "France": "europe/france",
    "Italy": "europe/italy", "Spain": "europe/spain", "Portugal": "europe/portugal",
    "Netherlands": "europe/netherlands", "Belgium": "europe/belgium",
    "Luxembourg": "europe/luxembourg", "Great Britain": "europe/great-britain",
    "Ireland": "europe/ireland", "Denmark": "europe/denmark",
    "Norway": "europe/norway", "Sweden": "europe/sweden", "Finland": "europe/finland",
    "Iceland": "europe/iceland", "Poland": "europe/poland",
    "Czechia": "europe/czech-republic", "Slovakia": "europe/slovakia",
    "Hungary": "europe/hungary", "Slovenia": "europe/slovenia",
    "Croatia": "europe/croatia", "Romania": "europe/romania",
    "Bulgaria": "europe/bulgaria", "Greece": "europe/greece",
    "Ukraine": "europe/ukraine", "Estonia": "europe/estonia",
    "Latvia": "europe/latvia", "Lithuania": "europe/lithuania",
    "United States": "north-america/us", "Canada": "north-america/canada",
    "Mexico": "north-america/mexico", "Brazil": "south-america/brazil",
    "Argentina": "south-america/argentina", "Japan": "asia/japan",
    "South Korea": "asia/south-korea", "India": "asia/india",
    "Australia": "australia-oceania/australia", "New Zealand": "australia-oceania/new-zealand",
    "South Africa": "africa/south-africa",
}

_lock = threading.Lock()
BUSY = {}                 # region -> status string while a populate is running
ERRORS = {}               # region -> last error message
_fort_count = 0           # cached so the page doesn't re-read the big file each refresh


def _load_ledger():
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            d = json.load(fh)
        return set(d.get("done", []))
    except (OSError, ValueError):
        # First run: if a big osm_forts.json already exists it's the US import, so
        # seed the ledger with the US as done rather than offering to re-add it.
        seed = ["north-america/us"] if _fort_count > 100000 else []
        _save_ledger(set(seed))
        return set(seed)


def _save_ledger(done):
    os.makedirs(DATA, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"done": sorted(done)}, fh, indent=1)
    os.replace(tmp, LEDGER)


def _count_forts():
    try:
        with open(FORTS_FILE, encoding="utf-8") as fh:
            return len(json.load(fh).get("forts", []))
    except (OSError, ValueError):
        return 0


def _do_populate(name, region):
    """Download + parse the country and append its forts to the live file."""
    global _fort_count
    try:
        with _lock:
            BUSY[region] = "downloading extract..."
        path = pf._download(region)
        with _lock:
            BUSY[region] = "parsing POIs (a few minutes)..."
        forts, scanned = pf._extract(path)
        with _lock:
            BUSY[region] = "merging into osm_forts.json..."
        try:
            with open(FORTS_FILE, encoding="utf-8") as fh:
                existing = json.load(fh).get("forts", [])
        except (OSError, ValueError):
            existing = []
        have = {f["id"] for f in existing}
        merged = existing + [f for f in forts if f["id"] not in have]
        os.makedirs(DATA, exist_ok=True)
        tmp = FORTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"forts": merged}, fh, indent=1)
        os.replace(tmp, FORTS_FILE)
        with _lock:
            done = _load_ledger()
            done.add(region)
            _save_ledger(done)
            _fort_count = len(merged)
            BUSY.pop(region, None)
            ERRORS.pop(region, None)
        added = len(merged) - len(existing)
        print(f"[populate] {name}: +{added:,} forts ({scanned:,} scanned) -> "
              f"{len(merged):,} total", flush=True)
    except Exception as e:
        with _lock:
            BUSY.pop(region, None)
            ERRORS[region] = f"{type(e).__name__}: {e}"
        print(f"[populate] {name} FAILED: {e}", flush=True)


def _page():
    done = _load_ledger()
    with _lock:
        busy = dict(BUSY)
        errs = dict(ERRORS)
    avail, busy_rows, done_rows = [], [], []
    for name, region in COUNTRIES.items():
        if region in busy:
            busy_rows.append(f"<li>{name} &mdash; {busy[region]}</li>")
        elif region in done:
            done_rows.append(f"<li>{name} &#10003;</li>")
        else:
            err = f" &mdash; last error: {errs[region]}" if region in errs else ""
            q = urllib.parse.urlencode({"region": region, "name": name})
            avail.append(f"<li>{name}: <a href=\"/populate?{q}\">populate</a>{err}</li>")
    refresh = "<meta http-equiv=refresh content=5>" if busy else ""
    return (
        "<!doctype html><meta charset=utf-8>" + refresh +
        "<title>Populate countries</title>"
        "<h1>Populate a country with PokeStops/Gyms</h1>"
        f"<p>Server has <b>{_fort_count:,}</b> forts. Pick a country to add its real "
        "OpenStreetMap places. Already-populated countries are locked so you can't "
        "double up. Each one downloads that country and appends it &mdash; the server "
        "hot-reloads, no restart.</p>"
        "<h2>In progress</h2><ul>" + ("".join(busy_rows) or "<li>(nothing running)</li>") + "</ul>"
        "<h2>Available</h2><ul>" + ("".join(avail) or "<li>(all done!)</li>") + "</ul>"
        "<h2>Populated &#10003;</h2><ul>" + ("".join(done_rows) or "<li>(none yet)</li>") + "</ul>"
    )


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/populate":
            qs = urllib.parse.parse_qs(parsed.query)
            region = (qs.get("region") or [""])[0]
            name = (qs.get("name") or [region])[0]
            with _lock:
                done = _load_ledger()
                ok = (region in COUNTRIES.values() and region not in done
                      and region not in BUSY)
                if ok:
                    BUSY[region] = "queued..."
            if ok:
                threading.Thread(target=_do_populate, args=(name, region),
                                 daemon=True).start()
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self._send(200, _page())


def main():
    global _fort_count
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8090
    _fort_count = _count_forts()
    _load_ledger()   # create/seed the ledger
    url = f"http://localhost:{port}/"
    print(f"populate app on {url}   (live file: {FORTS_FILE}, {_fort_count:,} forts)",
          flush=True)
    # pop the page open in the default browser once the server is listening
    if "--no-open" not in sys.argv:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("127.0.0.1", port), _H).serve_forever()


if __name__ == "__main__":
    main()
