"""
PoGO server status/diagnostics -- a machine-readable health feed for a status page.

Checks every moving part and reports what's wrong (with a suggested fix), as JSON:

    py pogo_status.py                 # print the JSON status once
    py pogo_status.py --pretty        # human-readable
    py pogo_status.py --serve 8099    # serve it: GET /status.json  and a live page at /

The /status.json endpoint sends `Access-Control-Allow-Origin: *`, so a separate
status page (hosted anywhere) can fetch it in the browser.

JSON shape:
{
  "generated_at": "2026-08-24T06:40:00Z",
  "overall": "ok" | "degraded" | "down",
  "summary": "3 issues" | "all systems go",
  "components": [
     {"name": "...", "label": "...", "status": "ok|warn|down",
      "detail": "...", "fix": "...", "code": "E### | ''"} , ...
  ],
  "issues": [ {component}, ... ]   # only the non-ok ones, worst first
}

Every failing check carries a distinct error CODE so you can tell at a glance
what broke (and Google/grep it). The first digit is the component, e.g.
  E1xx game server   E2xx headscale   E3xx Caddy   E4xx playit
  E5xx Tailscale     E6xx public URL  E7xx assets  E8xx DNS   E9xx cert
and for the two HTTP checks the real HTTP status is folded in (E6503 = the
control URL answered 503, E600 = it was unreachable). "ok" components have no code.
"""
import os
import re
import ssl
import sys
import json
import socket
import datetime
import subprocess

_NOWIN = 0x08000000 if os.name == "nt" else 0


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# ---------- config / locations ------------------------------------------------
def _project_root():
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "server")) and os.path.isdir(os.path.join(d, "RELEASE")):
            return d
        p = os.path.dirname(d)
        if p == d:
            break
        d = p
    return os.path.abspath(os.path.join(here, "..", ".."))


ROOT = _project_root()
HS_DIR = os.path.join(ROOT, "server", "deploy", "headscale-pc")


def _hs_domain():
    env = os.path.join(HS_DIR, ".env")
    try:
        for line in open(env, encoding="utf-8"):
            if line.strip().startswith("HS_DOMAIN"):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "bracky.playit.plus"


HS_DOMAIN = _hs_domain()
HS_CONTAINER = "pogo-headscale"


def _find(path, name):
    return path if os.path.exists(path) else name


DOCKER = _find(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe", "docker")
TAILSCALE = _find(r"C:\Program Files\Tailscale\tailscale.exe", "tailscale")


def run(args, timeout=12):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NOWIN)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def _proc_running(image):
    rc, out = run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], 8)
    return "no tasks" not in out.lower() and image.lower() in out.lower()


def _http(url, timeout=8):
    """GET a URL. Returns (status_code|None, body_bytes, error)."""
    import urllib.request
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read(4096), None
    except Exception as e:
        code = getattr(e, "code", None)
        return code, b"", str(e)


def _cert_days_left(host, port=443, timeout=8):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                cert = ss.getpeercert()
        exp = datetime.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        return (exp - _utcnow()).days
    except Exception:
        return None


def _docker_names():
    rc, out = run([DOCKER, "ps", "--format", "{{.Names}}"], 10)
    return out if rc == 0 else ""


# ---------- the checks --------------------------------------------------------
def _c(name, label, status, detail, fix="", code=""):
    return {"name": name, "label": label, "status": status, "detail": detail,
            "fix": fix, "code": code}


def collect():
    comps = []
    names = _docker_names()
    docker_ok = bool(names) or "error" not in names.lower()

    # game server
    if _proc_running("Start-Pokemon-GO-Server.exe"):
        comps.append(_c("game", "Game server", "ok", "Running and serving on :443"))
    else:
        comps.append(_c("game", "Game server", "down", "Not running",
                        "Open PoGO-Manager and click Start Game Server.", "E101"))

    # headscale container + reachability
    hs_up = HS_CONTAINER in names
    if hs_up:
        comps.append(_c("headscale", "Control server (headscale)", "ok", "Container up"))
    else:
        comps.append(_c("headscale", "Control server (headscale)", "down",
                        "headscale container is not running",
                        "In server/deploy/headscale-pc run: docker compose up -d", "E201"))

    # caddy
    if "pogo-caddy" in names:
        comps.append(_c("caddy", "HTTPS proxy (Caddy)", "ok", "Container up"))
    else:
        comps.append(_c("caddy", "HTTPS proxy (Caddy)", "down",
                        "Caddy container is not running",
                        "docker compose up -d in server/deploy/headscale-pc", "E301"))

    # playit agent (the daemon is 'playitd.exe'; a tray/service also run)
    if _proc_running("playitd.exe") or _proc_running("playitd-service.exe"):
        comps.append(_c("playit", "playit tunnel agent", "ok", "Running"))
    else:
        comps.append(_c("playit", "playit tunnel agent", "down",
                        "playit agent is not running -- the public tunnels are OFFLINE",
                        "Start the playit agent (tray app).", "E401"))

    # tailscale
    rc, out = run([TAILSCALE, "status", "--json"], 10)
    ts_ip = ""
    if rc == 0:
        try:
            j = json.loads(out)
            if j.get("BackendState") == "Running":
                ts_ip = (j.get("Self", {}) or {}).get("TailscaleIPs", [""])[0]
                comps.append(_c("tailscale", "Tailscale (player mesh)", "ok",
                                f"Up, this node = {ts_ip}"))
            else:
                comps.append(_c("tailscale", "Tailscale (player mesh)", "down",
                                f"Backend state: {j.get('BackendState')}",
                                "Launch tailscale-ipn.exe / reconnect Tailscale.", "E501"))
        except Exception:
            comps.append(_c("tailscale", "Tailscale (player mesh)", "warn",
                            "Could not parse status", "", "E502"))
    else:
        comps.append(_c("tailscale", "Tailscale (player mesh)", "down",
                        "Tailscale not responding", "Start the Tailscale service.", "E503"))

    # public control URL (proves tunnel + cert + headscale end-to-end)
    code, body, err = _http(f"https://{HS_DOMAIN}/health")
    if code == 200 and b"pass" in body:
        comps.append(_c("public", "Public reachability", "ok",
                        f"https://{HS_DOMAIN}/health = pass"))
    else:
        # Fold the real HTTP status into the code (E6503 = answered 503, E600 =
        # couldn't connect at all) so the failure mode is obvious from the number.
        pcode = f"E6{code}" if code else "E600"
        comps.append(_c("public", "Public reachability", "down",
                        f"Control URL not healthy ({err or 'HTTP ' + str(code)})",
                        "Check the playit agent + the bracky.playit.plus tunnel (->8443).",
                        pcode))

    # asset offload (the fast download path for remote players)
    code, body, err = _http(f"https://{HS_DOMAIN}/asset/pm0001")
    if code == 200 and len(body) > 1000:
        comps.append(_c("assets", "Asset downloads (offload)", "ok",
                        "Bundles serving over the public tunnel"))
    elif code == 200:
        comps.append(_c("assets", "Asset downloads (offload)", "warn",
                        "Responded but body looks empty/small", "", "E750"))
    else:
        acode = f"E7{code}" if code else "E700"
        comps.append(_c("assets", "Asset downloads (offload)", "down",
                        f"/asset/ not serving ({err or 'HTTP ' + str(code)}) -- remote players may crash",
                        "Check the game server is up and Caddy's /asset route + Host header.",
                        acode))

    # DNS redirect (game hosts -> the server)
    rc, out = run(["nslookup", "pgorelease.nianticlabs.com", "127.0.0.1"], 8)
    if "100." in out or (ts_ip and ts_ip in out):
        comps.append(_c("dns", "DNS redirect", "ok",
                        "Niantic hosts resolve to the server"))
    else:
        comps.append(_c("dns", "DNS redirect", "warn",
                        "Local DNS didn't return a tailnet IP (may be fine if game not started)",
                        "Ensure the game server is running (it hosts the DNS on :53).", "E801"))

    # cert expiry
    days = _cert_days_left(HS_DOMAIN)
    if days is None:
        comps.append(_c("cert", "HTTPS certificate", "warn", "Could not read cert", "", "E903"))
    elif days < 0:
        comps.append(_c("cert", "HTTPS certificate", "down", "Certificate EXPIRED",
                        "Caddy should auto-renew; check the caddy container/logs.", "E901"))
    elif days < 14:
        comps.append(_c("cert", "HTTPS certificate", "warn",
                        f"Expires in {days} days", "Caddy auto-renews ~30 days out.", "E902"))
    else:
        comps.append(_c("cert", "HTTPS certificate", "ok", f"Valid for {days} more days"))

    # connected players
    rc, out = run([DOCKER, "exec", HS_CONTAINER, "headscale", "nodes", "list",
                   "-o", "json"], 12)
    if rc == 0:
        try:
            nodes = json.loads(out)
            online = sum(1 for n in nodes if n.get("online"))
            comps.append(_c("players", "Connected devices", "ok",
                            f"{online} online / {len(nodes)} total"))
        except Exception:
            pass

    return comps


def build_status():
    comps = collect()
    rank = {"down": 2, "warn": 1, "ok": 0}
    issues = sorted([c for c in comps if c["status"] != "ok"],
                    key=lambda c: -rank[c["status"]])
    if any(c["status"] == "down" for c in comps):
        overall = "down"
    elif issues:
        overall = "degraded"
    else:
        overall = "ok"
    summary = ("all systems go" if not issues
               else f"{len(issues)} issue" + ("s" if len(issues) != 1 else ""))
    return {
        "generated_at": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall": overall,
        "summary": summary,
        "components": comps,
        "issues": issues,
    }


# ---------- built-in live page ------------------------------------------------
_PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>PoGO Server Status</title>
<style>
 body{font-family:system-ui,Segoe UI,sans-serif;background:#0f1720;color:#e6eef7;margin:0;padding:24px}
 h1{font-size:20px;margin:0 0 4px}.sub{color:#8aa;margin-bottom:20px}
 .banner{padding:14px 18px;border-radius:10px;font-weight:600;margin-bottom:18px}
 .ok{background:#12351f;color:#57e08a}.degraded{background:#3a3213;color:#e8c24a}
 .down{background:#3a1717;color:#f26d6d}
 .row{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:8px;background:#16202b;margin-bottom:8px}
 .dot{width:12px;height:12px;border-radius:50%;flex:none}
 .d-ok{background:#2ecc71}.d-warn{background:#e8c24a}.d-down{background:#e74c3c}
 .lab{font-weight:600;min-width:210px}.det{color:#9fb2c4;font-size:14px}
 .fix{color:#e8c24a;font-size:13px;margin-top:2px}
 .code{font-family:ui-monospace,Consolas,monospace;font-size:13px;font-weight:700;
  padding:4px 9px;border-radius:6px;flex:none;letter-spacing:.03em;align-self:center}
 .c-down{background:#4a1b1b;color:#ff9a9a}.c-warn{background:#43380f;color:#f0d070}
 .banner .codes{font-weight:700;opacity:.85;margin-left:8px;font-family:ui-monospace,Consolas,monospace}
 .t{color:#67788a;font-size:12px;margin-top:16px}
</style></head><body>
<h1>PoGO Server Status</h1><div class=sub id=dom></div>
<div id=banner class=banner>loading…</div><div id=list></div>
<div class=t id=ts></div>
<script>
async function tick(){
 try{const r=await fetch('status.json',{cache:'no-store'});const s=await r.json();
  document.getElementById('dom').textContent=location.host;
  const b=document.getElementById('banner');b.className='banner '+s.overall;
  const codes=(s.issues||[]).filter(c=>c.code).map(c=>c.code).join(', ');
  b.innerHTML=(s.overall==='ok'?'✅ ':(s.overall==='down'?'⛔ ':'⚠️ '))+s.summary.toUpperCase()
   +(codes?`<span class=codes>${codes}</span>`:'');
  document.getElementById('list').innerHTML=s.components.map(c=>
   `<div class=row><div class="dot d-${c.status}"></div><div style="flex:1"><div class=lab>${c.label}</div>`+
   `<div class=det>${c.detail}</div>${c.status!=='ok'&&c.fix?`<div class=fix>→ ${c.fix}</div>`:''}</div>`+
   `${c.code?`<div class="code c-${c.status}">${c.code}</div>`:''}</div>`).join('');
  document.getElementById('ts').textContent='updated '+s.generated_at;
 }catch(e){document.getElementById('banner').textContent='cannot reach status service';}
}
tick();setInterval(tick,5000);
</script></body></html>"""


def serve(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/status.json"):
                body = json.dumps(build_status()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_PAGE.encode())

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print(f"PoGO status serving on http://localhost:{port}/  (JSON at /status.json)")
    srv.serve_forever()


def main():
    args = sys.argv[1:]
    if "--serve" in args:
        i = args.index("--serve")
        port = int(args[i + 1]) if i + 1 < len(args) else 8099
        serve(port)
    elif "--pretty" in args:
        s = build_status()
        print(f"OVERALL: {s['overall'].upper()}  ({s['summary']})  @ {s['generated_at']}")
        for c in s["components"]:
            mark = {"ok": "OK  ", "warn": "WARN", "down": "DOWN"}[c["status"]]
            code = f" [{c['code']}]" if c.get("code") else ""
            print(f"  [{mark}]{code} {c['label']}: {c['detail']}")
            if c["status"] != "ok" and c["fix"]:
                print(f"         fix: {c['fix']}")
    else:
        print(json.dumps(build_status(), indent=2))


if __name__ == "__main__":
    main()
