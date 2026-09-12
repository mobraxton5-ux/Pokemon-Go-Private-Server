"""
PoGO private server — ONE launcher that runs everything in a single process:
the DNS redirector (UDP 53) and the game server (TCP 443, fake PTC SSO + RPC).

  Local (same Wi-Fi as the phone):
      py run.py                      # auto-detects this PC's LAN IP
  Remote (server with a public IP / VPS):
      py run.py 203.0.113.7          # the IP the phone should be pointed at
      RUN_IP=203.0.113.7 py run.py

Point the phone's Wi-Fi DNS at the IP this prints. Both 53/udp and 443/tcp must be
reachable from the phone (open them in the firewall; on Windows low ports are fine
without admin, but a firewall *allow* rule for inbound may be needed).

Build a standalone .exe (no Python needed on the target):
      py -m PyInstaller --onefile --name pogo-server \
         --add-data "certs;certs" --collect-all s2sphere run.py
"""
import os
import socket
import sys
import threading
import time

# ---- resource base (works when frozen by PyInstaller too) -------------------
if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS                         # bundled read-only data
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


# Plain ASCII on purpose: the Windows console is cp1252, so block-drawing
# characters raise UnicodeEncodeError the moment they're printed.
BANNER = r"""
  ____   ____      _      ____  _  __ __   __
 | __ ) |  _ \    / \    / ___|| |/ / \ \ / /
 |  _ \ | |_) |  / _ \  | |    | ' /   \ V /
 | |_) )|  _ <  / ___ \ | |___ | . \    | |
 |____/ |_| \_\/_/   \_\ \____||_|\_\   |_|
"""


def _route_ip():
    """The address the OS would send internet traffic from."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))              # no packets sent; reveals iface IP
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def _local_ips():
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
    except OSError:
        pass
    return out


def is_cgnat(ip):
    """100.64.0.0/10 -- carrier-grade NAT, which is what Tailscale hands out."""
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127


def _usable(ip):
    return bool(ip) and not ip.startswith(("127.", "169.254."))


def detect_ip():
    """This PC's address on the phone's network.

    The obvious trick -- open a UDP socket towards the internet and read back the
    local address -- returns whichever interface holds the DEFAULT ROUTE, and with
    Tailscale running that is the 100.x tailnet address. The DNS redirector then
    answers the game with an address the phone can only reach while its own
    Tailscale is up, so the game silently fails to connect while everything else
    looks fine. Prefer a real LAN address, and only fall back to the tailnet one.
    """
    route = _route_ip()
    if _usable(route) and not is_cgnat(route):
        return route
    # Host-only adapters (VMware, VirtualBox, Hyper-V) always take the .1 of their
    # own subnet, so a .1 is the last thing to try, not the first.
    lan = [ip for ip in _local_ips() if _usable(ip) and not is_cgnat(ip)]
    lan.sort(key=lambda ip: ip.endswith(".1"))
    if lan:
        return lan[0]
    return route or "127.0.0.1"


def _setup_logging(ui_stream=None):
    """Tee ALL console output to server-log.txt next to the exe/script, so the
    full RPC / asset / map trace can be sent for debugging (the game client strips
    its own logs, so this server log is our only window into what happened).
    `ui_stream` (the server window's activity pane) gets a copy too."""
    import datadir
    log_dir = datadir.ensure()
    # APPEND, don't truncate. Opening "w" wiped the log on every restart, so
    # anything that happened in the previous session -- exactly the session you
    # want to look at when something "stopped working" -- was already gone by the
    # time anyone went looking. Roll over at 5 MB so it can't grow forever.
    log_path = os.path.join(log_dir, "server-log.txt")
    try:
        if os.path.getsize(log_path) > 5_000_000:
            os.replace(log_path, log_path + ".1")
    except OSError:
        pass
    try:
        logf = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    except OSError:
        logf = None
    try:
        import datetime as _dt
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if logf:
            logf.write("\n" + "=" * 60 + "\n")
            logf.write(f"  bracky's PoGO private server  --  session started {stamp}\n")
            logf.write("=" * 60 + "\n")
    except Exception:
        pass

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, t):
            for s in self.streams:
                if s:
                    try:
                        s.write(t); s.flush()
                    except Exception:
                        pass
            return len(t)

        def flush(self):
            for s in self.streams:
                if s:
                    try:
                        s.flush()
                    except Exception:
                        pass

    # sys.__stdout__ is None in the windowed exe; _Tee skips missing streams.
    sys.stdout = _Tee(sys.__stdout__, logf, ui_stream)
    sys.stderr = _Tee(sys.__stderr__, logf, ui_stream)


def main(ui_stream=None):
    """Run everything. Blocks in server.main(). The server window
    (server_gui.py) calls this on a background thread with its own stream."""
    _setup_logging(ui_stream)
    redirect_ip = (sys.argv[1] if len(sys.argv) > 1
                   else os.environ.get("RUN_IP") or detect_ip())
    # Show the alternatives. When the phone can't reach the server, the first
    # thing to check is whether this is even the right address for the network
    # the phone is on -- so make it impossible to miss.
    others = [ip for ip in _local_ips()
              if _usable(ip) and ip != redirect_ip]
    if others:
        print(f"  (this PC is also reachable at: {', '.join(others)} -- if the"
              f" phone can't connect, run this with the right one as an argument)")
    # hand config to the imported modules via env (read at their import time)
    os.environ["REDIRECT_IP"] = redirect_ip
    os.environ.setdefault("PORT", "443")
    os.environ.setdefault("BIND", "0.0.0.0")
    os.environ.setdefault("DNS_PORT", "53")
    os.environ.setdefault("CERT_DIR", os.path.join(BASE, "certs"))
    # Serve the real 2016 game master so the client has Pokemon templates and will
    # actually request + render the wild Pokemon (asset bundles now shipped in
    # assets/). Set SERVE_GAME_MASTER=0 to fall back to the bare template set.
    os.environ.setdefault("SERVE_GAME_MASTER", "1")

    import server
    import dns_redirect
    import sso_bridge

    if not (os.path.exists(server.CERT) and os.path.exists(server.KEY)):
        print(f"!! TLS certs not found in {os.environ['CERT_DIR']}.\n"
              f"   Run gen_certs.py once, or ship the certs/ folder alongside this.")
        sys.exit(1)

    # World Manager (localhost only -- never exposed to the phone/network)
    try:
        import settings as _cfg
        admin_port = _cfg.get("server", "world_manager_port", env="ADMIN_PORT", cast=int)
    except Exception:
        admin_port = int(os.environ.get("ADMIN_PORT", "8080"))
    try:
        import admin
        admin.start(port=admin_port)
        admin_url = f"http://127.0.0.1:{admin_port}"
    except Exception as e:
        admin_url = f"(failed to start: {e})"

    print()
    print(BANNER)
    print("=" * 60)
    print("  a Pokemon GO 0.29 (July 2016) server, made from scratch")
    print("-" * 60)
    print(f"  World Manager (this PC):          {admin_url}")
    print(f"  Point the phone's Wi-Fi DNS at:   {redirect_ip}")
    print(f"  Game server : https://{redirect_ip}:{os.environ['PORT']}")
    print(f"  DNS redirect: udp {redirect_ip}:{os.environ['DNS_PORT']}")
    print("  (Ctrl-C to stop)")
    print("=" * 60)
    print("  bracky's PoGO server -- everything below is live server activity")
    print()

    # DNS in a supervised background thread (auto-restarts if it ever dies)
    def dns_loop():
        while True:
            try:
                dns_redirect.main()
            except Exception as e:
                print(f"[dns] restarting after: {e}", flush=True)
                time.sleep(1)
    threading.Thread(target=dns_loop, daemon=True).start()

    # Plain-HTTP door for the 0.35 client's PTC login, supervised the same way.
    # 0.35 dropped the permissive cert-validation callback 0.29 had, so its
    # Mono/C# login trusts NO certificate we can serve -- not our CA and not a
    # real Let's Encrypt one (Unity 5.3.5's root store predates ISRG Root X1).
    # The 0.35 build's SSO URLs are patched to http:// and land here; the hop is
    # inside the tailnet, so it is still encrypted end to end. 0.29 is untouched
    # and keeps using HTTPS. Only /sso is served; everything else gets a 404.
    def sso_bridge_loop():
        while True:
            try:
                sso_bridge.serve(int(os.environ.get("SSO_BRIDGE_PORT", "80")),
                                 int(os.environ["PORT"]))
            except Exception as e:
                print(f"[bridge] restarting after: {e}", flush=True)
                time.sleep(1)
    threading.Thread(target=sso_bridge_loop, daemon=True).start()

    # HTTPS server on the main thread (blocks until Ctrl-C)
    try:
        server.main()
    except KeyboardInterrupt:
        print("\nshutting down.")


if __name__ == "__main__":
    main()
