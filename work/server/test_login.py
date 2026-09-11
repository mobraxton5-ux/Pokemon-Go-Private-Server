"""
Local end-to-end test of the LOGIN path, no emulator required.

Simulates exactly what the 0.29 client does:
  PTC: login page -> submit creds -> accessToken -> profile
  RPC: bootstrap (expect 53 redirect) -> resend (expect 2 OK + GET_PLAYER)

It points urllib at 127.0.0.1 but sends the real Host headers, trusts our CA,
and verifies the chosen username comes back inside the GET_PLAYER PlayerData.

Run the server first (in another terminal):
    PORT=8443 py server.py
Then:
    USERNAME=AshKetchum py test_login.py
"""
import http.client
import json
import os
import socket
import ssl
import sys
import urllib.parse

import pb
import protocol as P

CONNECT_ADDR = ("127.0.0.1", int(os.environ.get("PORT", "8443")))
USERNAME = os.environ.get("USERNAME", "AshKetchum")


def _guard_real_account():
    """Refuse to test-login as a REAL trainer who hasn't set a password yet.

    The first login for a name CLAIMS it and stores whatever password was sent --
    so running this against a live account silently changes its password to
    "whatever", and the owner is then locked out with "unable to authenticate".
    That happened. Set FORCE_LOGIN_TEST=1 if you really mean it."""
    if os.environ.get("FORCE_LOGIN_TEST") == "1":
        return
    try:
        import world
        save = os.path.join(world.SAVES_DIR, world._safe_name(USERNAME) + ".json")
        if not os.path.exists(save):
            return
        import json
        with open(save, encoding="utf-8") as fh:
            d = json.load(fh)
        if not d.get("pw"):
            print(f"REFUSING: '{USERNAME}' is a real account with no password set.")
            print("  Logging in as them would claim the account and set its")
            print("  password to the test one, locking the owner out. Use a")
            print("  throwaway name, or FORCE_LOGIN_TEST=1 if you really mean it.")
            sys.exit(2)
    except SystemExit:
        raise
    except Exception:
        pass                       # a guard must never be the thing that breaks


_guard_real_account()
CA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs", "ca.crt")


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a fixed address while presenting `host` for SNI + cert check
    (mimics DNS redirecting the real hostname to our server)."""
    def connect(self):
        sock = socket.create_connection(CONNECT_ADDR)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def conn(server_hostname):
    ctx = ssl.create_default_context(cafile=CA)
    ctx.check_hostname = True   # validates the SAN matches the real hostname
    return PinnedHTTPSConnection(server_hostname, context=ctx)


def req(host, method, path, body=None, ctype=None):
    c = conn(host)
    headers = {"Host": host}
    if ctype:
        headers["Content-Type"] = ctype
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


def expect(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        sys.exit(1)


def main():
    print(f"== PTC SSO flow (username={USERNAME!r}) ==")
    s, h, b = req("sso.pokemon.com", "GET", "/sso/login?service=" +
                  urllib.parse.quote("https://sso.pokemon.com/sso/oauth2.0/callback"))
    page = json.loads(b)
    expect(s == 200 and "lt" in page and "execution" in page,
           f"login page returns lt/execution ({page.get('lt','')[:10]}...)")

    form = urllib.parse.urlencode({
        "lt": page["lt"], "execution": page["execution"],
        "_eventId": "submit", "username": USERNAME, "password": "whatever",
    })
    s, h, b = req("sso.pokemon.com", "POST",
                  "/sso/login?service=" + urllib.parse.quote(
                      "https://sso.pokemon.com/sso/oauth2.0/callback"),
                  body=form, ctype="application/x-www-form-urlencoded")
    loc = h.get("Location", "")
    ticket = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("ticket", [""])[0]
    expect(s == 302 and ticket.startswith("ST-"), f"creds accepted, ticket={ticket[:14]}...")

    body = urllib.parse.urlencode({
        "client_id": "mobile-app_pokemon-go", "grant_type": "refresh_token",
        "code": ticket,
        "redirect_uri": "https://www.nianticlabs.com/pokemongo/error",
    })
    s, h, b = req("sso.pokemon.com", "POST", "/sso/oauth2.0/accessToken",
                  body=body, ctype="application/x-www-form-urlencoded")
    tok = urllib.parse.parse_qs(b.decode()).get("access_token", [""])[0]
    expect(s == 200 and tok.startswith("PTC."), f"access_token issued ({tok[:16]}...)")

    s, h, b = req("sso.pokemon.com", "GET",
                  "/sso/oauth2.0/profile?access_token=" + urllib.parse.quote(tok) +
                  "&client_id=mobile-app_pokemon-go")
    prof = json.loads(b)
    expect(s == 200 and "birthdate" in prof, f"profile served (birthdate={prof.get('birthdate')})")

    print("\n== RPC handshake ==")
    # Build a RequestEnvelope like the client: GET_PLAYER alone, with auth_info.
    auth_info = (pb.Writer()
                 .string(P.AI_PROVIDER, "ptc")
                 .message(P.AI_TOKEN, pb.Writer().string(P.AI_TOKEN_CONTENTS, tok).uint(2, 59))
                 .to_bytes())
    get_player_req = pb.Writer().uint(P.REQ_TYPE, P.RT.GET_PLAYER).to_bytes()
    env = (pb.Writer()
           .uint(P.RE_STATUS_CODE, 2)
           .uint(P.RE_REQUEST_ID, 0x123456789A)
           .message(P.RE_REQUESTS, get_player_req)
           .double(P.RE_LATITUDE, 40.0).double(P.RE_LONGITUDE, -75.0).double(P.RE_ACCURACY, 10.0)
           .message(P.RE_AUTH_INFO, auth_info)
           .to_bytes())

    # 1) bootstrap -> expect 53 + api_url
    s, h, b = req("pgorelease.nianticlabs.com", "POST", "/plfe/rpc", body=env,
                  ctype="application/binary")
    f = pb.decode(b)
    status = pb.get(f, P.RESP_STATUS_CODE)
    api_url = pb.get(f, P.RESP_API_URL)
    api_url = api_url.decode() if isinstance(api_url, bytes) else api_url
    expect(s == 200 and status == P.STATUS_REDIRECT and api_url,
           f"bootstrap -> status {status} REDIRECT, api_url={api_url!r}")

    # 2) resend to api_url -> expect 2 OK + auth_ticket + GET_PLAYER(username)
    path = "/" + api_url.split("/", 1)[1]
    s, h, b = req("pgorelease.nianticlabs.com", "POST", path, body=env,
                  ctype="application/binary")
    f = pb.decode(b)
    status = pb.get(f, P.RESP_STATUS_CODE)
    has_ticket = pb.get(f, P.RESP_AUTH_TICKET, pb.WT_LEN) is not None
    returns = pb.get_all(f, P.RESP_RETURNS)
    expect(s == 200 and status == P.STATUS_OK, f"resend -> status {status} OK")
    expect(has_ticket, "auth_ticket present")
    expect(len(returns) == 1, f"one return for one request ({len(returns)})")

    # decode GET_PLAYER -> PlayerData.username
    gp = pb.decode(returns[0])
    success = pb.get(gp, P.GP_SUCCESS)
    pdata = pb.get(gp, P.GP_PLAYER_DATA, pb.WT_LEN)
    name = pb.get(pb.decode(pdata), P.PD_USERNAME, pb.WT_LEN)
    name = name.decode() if isinstance(name, bytes) else name
    expect(success in (1, True), "GetPlayerResponse.success = true")
    expect(name == USERNAME, f"PlayerData.username == {USERNAME!r} (got {name!r})")

    print("\n*** ALL LOGIN-PATH CHECKS PASSED ***")


if __name__ == "__main__":
    main()
