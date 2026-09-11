"""
Plain-HTTP front door for the PTC login endpoints, for the 0.35 client only.

Why this exists: 0.35 dropped the `MyRemoteCertificateValidationCallback` that
0.29's PTC login class installed. Without it, the Mono/C# login path validates
server certs against Unity 5.3.5's bundled 2016-era root store, which trusts
neither our private CA nor a modern Let's Encrypt chain (today's LE certs chain
to ISRG Root X1, which that store predates). Measured symptom, from the client's
own log:

    System.Net.WebException: Error getting response stream
        (Write: BeginWrite failure): SendFailure
    Authentication failed state: Initial PTC login failed.

Since no certificate can satisfy that store, take TLS out of the login hop
entirely: the 0.35 APK's five SSO URLs are rewritten to http:// and this bridge
forwards them to the real HTTPS server on loopback. Only PTC login crosses it --
the RPC path stays HTTPS on the native stack, which has its own (working) trust.

This is safe here because the hop is our own tailnet: the phone reaches
100.64.0.1:80 over WireGuard, which is already encrypted end to end.

    import sso_bridge; sso_bridge.serve()        # or run this file directly
"""
import http.client
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_CTX = ssl._create_unverified_context()          # loopback hop; our own cert
UPSTREAM = 443                                   # set by serve()


class Bridge(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[bridge] {self.command} {self.path}", flush=True)

    def _relay(self):
        # Only the login endpoints belong on this cleartext door. Anything else
        # that finds port 80 (Tailscale probes for /ts2021, scanners) is refused
        # rather than quietly proxied into the game server.
        if not self.path.startswith("/sso"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b""
        n = self.headers.get("Content-Length")
        if n:
            body = self.rfile.read(int(n))
        c = http.client.HTTPSConnection("127.0.0.1", UPSTREAM, context=_CTX, timeout=30)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("content-length", "accept-encoding")}
        # Keep the Host the client sent; server.py routes /sso by path, but the
        # PTC handler echoes this host back into the URLs it hands the client,
        # so rewriting it here would send the client somewhere it cannot reach.
        try:
            c.request(self.command, self.path, body=body, headers=headers)
            r = c.getresponse()
            data = r.read()
        except Exception as e:
            print(f"[bridge] upstream error: {e}", flush=True)
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ("transfer-encoding", "content-length", "connection"):
                continue
            # Redirects point back at https://<host>/sso/... -- the 0.35 client
            # cannot do TLS to us at all, so keep the whole login flow on http.
            if k.lower() == "location":
                v = v.replace("https://", "http://")
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_HEAD = _relay


def serve(listen=80, upstream=443):
    """Blocking. Run me in a daemon thread next to the DNS redirector."""
    global UPSTREAM
    UPSTREAM = upstream
    print(f"[bridge] http://0.0.0.0:{listen}  ->  https://127.0.0.1:{upstream}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", listen), Bridge).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 80,
          int(sys.argv[2]) if len(sys.argv) > 2 else 443)
