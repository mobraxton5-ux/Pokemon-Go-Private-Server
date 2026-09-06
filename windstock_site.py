"""
The public Project Windstock website, served by the game server itself.

Why here rather than a separate static host: the status page has to fetch a health
endpoint, and a browser blocks that cross-origin unless the endpoint sends CORS
headers (the site's own README calls this out). Serving the pages from the same
origin the health check uses removes the problem entirely -- no CORS, no second
host to keep alive.

Routes (Caddy on bracky.playit.plus forwards exactly these to us):
    /                 -> index.html
    /index.html       -> the landing page
    /status.html      -> the status page
    /assets/*         -> css / js / images
    /api/health       -> JSON liveness for the status page

/api/health is deliberately NOT /health: on that domain /health already belongs to
headscale, and the status page must report whether the GAME server is up, not
whether the tailnet control plane is.
"""
import json
import mimetypes
import os
import sys
import time

SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
if getattr(sys, "frozen", False):
    SITE_DIR = os.path.join(sys._MEIPASS, "site")

_STARTED = time.time()

# Only these are reachable. A prefix check on SITE_DIR alone would still let a
# crafted path walk out of it on some platforms, so the resolved real path is
# re-checked against the real site dir before anything is read.
PAGES = {"/": "index.html", "/index.html": "index.html", "/status.html": "status.html"}


def owns(path: str) -> bool:
    return path in PAGES or path.startswith("/assets/") or path == "/api/health"


def handle(method, path, query, headers, body, log):
    if path == "/api/health":
        out = json.dumps({
            "ok": True,
            "service": "project-windstock",
            "uptime_seconds": int(time.time() - _STARTED),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }).encode()
        return 200, {"Content-Type": "application/json",
                     "Cache-Control": "no-store",
                     # harmless here (same-origin already), but lets the page be
                     # opened from a file:// copy while someone is editing it
                     "Access-Control-Allow-Origin": "*"}, out

    rel = PAGES.get(path) or path.lstrip("/")
    full = os.path.realpath(os.path.join(SITE_DIR, rel))
    if not full.startswith(os.path.realpath(SITE_DIR) + os.sep) or not os.path.isfile(full):
        log(f"[site] 404 {path}")
        return 404, {"Content-Type": "text/plain"}, b"not found"

    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as f:
        out = f.read()
    cache = "no-store" if full.endswith(".html") else "public, max-age=3600"
    return 200, {"Content-Type": ctype, "Cache-Control": cache}, out
