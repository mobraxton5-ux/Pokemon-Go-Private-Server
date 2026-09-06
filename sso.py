"""
Fake Pokemon Trainer Club (PTC) SSO — sso.pokemon.com

Reproduces the CAS/OAuth flow the 0.29 client performs, but accepts ANY
username/password. Whatever username is typed on the PTC login screen is
carried through to the RPC layer and used as the in-game trainer name.

Client flow (reverse-engineered from global-metadata.dat strings):
  1. GET  /sso/login?service=<callback>           -> JSON { lt, execution }
  2. POST /sso/login?service=<callback>            -> 302, Location ...?ticket=ST-..
        body: lt&execution&_eventId=submit&username&password
  3. POST /sso/oauth2.0/accessToken  (code=ST-..)  -> "access_token=..&expires=.."
  4. GET  /sso/oauth2.0/profile?access_token=..    -> JSON { "birthdate": "..." }

The access_token embeds the username (base64) so the RPC server can recover it
without shared state surviving restarts.
"""
import base64
import html
import json
import os
import time
import urllib.parse

CALLBACK = "https://sso.pokemon.com/sso/oauth2.0/callback"

# ---- branding for the webview login page (a patched client points its login
# webview at /sso/login; the stock client still gets the JSON flow below) -------
BRAND_NAME = "Project Windstock"
BRAND_TAGLINE = "Welcome to Kanto"
PRIVACY_URL = "/sso/privacy"           # served below; repoint to your site later


def _custom_login_on():
    """Whether to serve our branded HTML at the real PTC login URL (the webview
    experiment). See settings.server.custom_login_page."""
    try:
        import settings
        return bool(settings.get("server", "custom_login_page", cast=bool))
    except Exception:
        return False


def _wants_html(headers):
    """A browser / login webview sends Accept: text/html; the native PTC client
    fetches JSON. Serve the branded page only to the former so the stock login
    keeps working untouched."""
    try:
        return "text/html" in (headers.get("Accept", "") or "").lower()
    except Exception:
        return False


def login_page_html(service, error="", prefill=""):
    """The branded 'Welcome to Kanto' login screen -- email + password in a card.
    Self-contained (inline CSS, no external assets) so it renders inside an offline
    client webview. The email is passed through as the account identifier; the form
    still posts to the same /sso/login handler, so real website/Discord auth slots
    in later behind check_login() with no page change."""
    svc = html.escape(service or CALLBACK, quote=True)
    err = (f'<p class="err">{html.escape(error)}</p>') if error else ""
    name = html.escape(prefill or "", quote=True)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(BRAND_TAGLINE)}</title>
<style>
  :root {{ --ink:#22324a; --blue:#1f6fd6; --blue-2:#2a5aa8; --muted:#7c8aa0;
           --line:#e2e8f2; --card:#ffffff; }}
  * {{ box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
  html,body {{ margin:0; height:100%; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          color:var(--ink);
          background:radial-gradient(1200px 500px at 50% -8%, #eaf3ff 0%, #f4f8f4 42%, #eef7e8 100%);
          min-height:100%; display:flex; flex-direction:column; align-items:center;
          padding:max(20px,env(safe-area-inset-top)) 20px env(safe-area-inset-bottom); }}
  .logo {{ margin-top:6vh; text-align:center; line-height:0.86; user-select:none; }}
  .logo .p {{ font-weight:900; font-size:clamp(40px,13vw,74px); letter-spacing:2px;
              color:#f6c945; -webkit-text-stroke:3px var(--blue-2);
              paint-order:stroke fill; text-shadow:0 3px 0 var(--blue-2); }}
  .logo .g {{ font-weight:900; font-size:clamp(26px,9vw,50px); letter-spacing:4px;
              color:#cfd6dc; -webkit-text-stroke:2px #37475a; paint-order:stroke fill; }}
  h1 {{ font-weight:800; font-size:clamp(20px,5.5vw,27px); margin:3.4vh 0 2px; text-align:center; }}
  /* the primary action -- a light card-button, matching the screenshot */
  .discord {{ width:100%; max-width:360px; padding:18px; font-size:15px; font-weight:700;
              letter-spacing:1.5px; text-transform:uppercase; color:#5b6e70;
              background:#f2f3f2; border:1px solid #e6e8e6; border-radius:14px;
              box-shadow:0 6px 16px -8px rgba(40,60,60,.25); cursor:pointer; }}
  .discord:active {{ background:#e8eae8; }}
  /* revealed email/password step */
  #loginForm {{ display:none; width:100%; max-width:360px; flex-direction:column; gap:11px; }}
  input {{ width:100%; padding:15px 16px; font-size:16px; border:1px solid var(--line);
           border-radius:13px; background:#fbfdff; color:var(--ink); outline:none;
           transition:border-color .15s, box-shadow .15s; }}
  input:focus {{ border-color:var(--blue); box-shadow:0 0 0 3px rgba(31,111,214,.15); background:#fff; }}
  .primary {{ margin-top:4px; width:100%; padding:16px; font-size:15px; font-weight:800;
              letter-spacing:1.5px; text-transform:uppercase; border:0; border-radius:13px;
              color:#fff; cursor:pointer; background:linear-gradient(180deg,#2a86ee,var(--blue)); }}
  .primary:active {{ filter:brightness(.94); }}
  .err {{ color:#c0392b; font-size:14px; text-align:center; margin:0 0 12px; max-width:360px;
          background:#fdecea; border:1px solid #f5c6c0; border-radius:10px; padding:9px 12px; }}
  .links {{ margin-top:22px; }}
  a {{ color:var(--blue); text-decoration:none; font-weight:600; }}
  footer {{ margin-top:auto; align-self:flex-start; padding-top:26px; font-size:12px;
            color:#8fa0a0; line-height:1.55; }}
</style></head>
<body>
  <div class="logo"><div class="p">Pok&eacute;mon</div><div class="g">GO</div></div>
  <h1>{html.escape(BRAND_TAGLINE)}</h1>
  {err}
  <!-- Step 1: the Discord button, matching the screenshot. -->
  <button id="discordBtn" class="discord" onclick="reveal()">Login with Discord</button>
  <!-- Step 2: revealed on tap (real Discord OAuth replaces this later). -->
  <form id="loginForm" method="post" action="/sso/login?service={svc}">
    <input type="hidden" name="web" value="1">
    <input id="em" name="username" type="email" inputmode="email" placeholder="Email"
           autocapitalize="none" autocomplete="username" value="{name}" required>
    <input name="password" type="password" placeholder="Password"
           autocomplete="current-password" required>
    <button class="primary" type="submit">Enter Kanto</button>
  </form>
  <div class="links"><a href="{html.escape(PRIVACY_URL, quote=True)}">Privacy Policy</a></div>
  <footer>&copy;2016 Niantic Inc.<br>&copy;2016 Pok&eacute;mon<br>
    &copy;1995-2016 Nintendo / Creatures Inc. / GAME FREAK Inc.</footer>
  <script>
    function reveal(){{
      document.getElementById('discordBtn').style.display='none';
      var f=document.getElementById('loginForm'); f.style.display='flex';
      document.getElementById('em').focus();
    }}
    // If the page was reloaded with an error, jump straight to the form.
    if (document.querySelector('.err')) reveal();
  </script>
</body></html>"""


def privacy_page_html():
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 color:#2f5d62;background:linear-gradient(180deg,#fff,#eaf7e4);margin:0;
 padding:32px 24px;line-height:1.6;}}h1{{font-size:24px;}}a{{color:#26a69a;}}
 .card{{max-width:560px;margin:0 auto;}}</style></head>
<body><div class="card"><h1>Privacy Policy</h1>
<p>{html.escape(BRAND_NAME)} is a private, personal Pok&eacute;mon GO server run for
friends and family. It stores only the email you log in with and your in-game
progress (Pok&eacute;mon, items, level) on the server operator's own machine.</p>
<p>Nothing is shared with third parties. There are no ads and no tracking. Delete your
account by asking the server operator to remove your save file.</p>
<p><a href="/sso/login">&larr; Back to login</a></p></div></body></html>"""


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode()


def make_token(username: str) -> str:
    return f"PTC.{_b64(username)}.{os.urandom(6).hex()}"


def username_from_token(token: str) -> str:
    try:
        if token.startswith("PTC."):
            return _unb64(token.split(".")[1])
    except Exception:
        pass
    return token or "Trainer"


def _resp(status, body, ctype="text/plain", extra=None):
    headers = {"Content-Type": ctype, "Cache-Control": "no-store"}
    if extra:
        headers.update(extra)
    if isinstance(body, str):
        body = body.encode("utf-8")
    return status, headers, body


def handle(method, path, query, headers, body, log):
    qs = urllib.parse.parse_qs(query)
    form = urllib.parse.parse_qs(body.decode("utf-8", "replace")) if body else {}

    # branded privacy page for the webview login
    if path == "/sso/privacy" and method == "GET":
        return _resp(200, privacy_page_html(), "text/html; charset=utf-8")

    # Branded "Welcome to Kanto" page lives on its OWN path. Point a patched
    # client's login webview (or a browser) here. It is DELIBERATELY separate from
    # /sso/login: the native PTC client fetches /sso/login expecting JSON, and it
    # sends an Accept header that includes text/html, so content-negotiating there
    # served it HTML and broke login. This path never collides with that.
    if path in ("/sso/welcome", "/sso/login/page") and method == "GET":
        service = qs.get("service", [CALLBACK])[0]
        log(f"[ptc] branded login page served (service={service})")
        return _resp(200, login_page_html(service), "text/html; charset=utf-8")

    # 1) login page. EXPERIMENT (server.custom_login_page): if on, serve our
    # branded HTML here at the real login URL -- works IF the PTC button opens a
    # webview, breaks IF login is native (flip the setting back). Off by default =
    # the proven JSON lt/execution tokens the native client expects.
    if path == "/sso/login" and method == "GET":
        service = qs.get("service", [CALLBACK])[0]
        if _custom_login_on():
            log(f"[ptc] custom HTML login served at /sso/login (webview test; "
                f"service={service})")
            return _resp(200, login_page_html(service), "text/html; charset=utf-8")
        payload = {
            "lt": "LT-" + os.urandom(8).hex(),
            "execution": "e1s1",
            "_eventId": "submit",
            "service": service,
        }
        log(f"[ptc] login page issued lt/execution (service={service})")
        return _resp(200, json.dumps(payload), "application/json")

    # 2) credential submit -> check the password, then issue a service ticket
    if path == "/sso/login" and method == "POST":
        username = (form.get("username", [""])[0] or "Trainer").strip()
        password = form.get("password", [""])[0] or ""
        service = qs.get("service", [CALLBACK])[0]
        from_web = bool(form.get("web"))
        import world
        ok, why, real = world.check_login(username, password)
        if not ok:
            log(f"[ptc] LOGIN REFUSED  username={username!r}  ({why})")
            if from_web:
                # Re-render the branded page with the error, so a webview login
                # shows it inline instead of a raw JSON body.
                msg = ("That trainer name is already taken and the password "
                       "doesn't match." if why == "wrong password"
                       else "Unable to log in with the details provided.")
                return _resp(200, login_page_html(service, error=msg, prefill=username),
                             "text/html; charset=utf-8")
            # CAS reports a bad login as 200 with an "errors" body and NO ticket.
            # The client then shows its own authentication-failed message.
            return _resp(200, json.dumps(
                {"errors": ["Unable to log in with the credentials provided."]}),
                "application/json")
        if why == "claimed":
            log(f"[ptc] NEW TRAINER {real!r} -- password set from this first login")
        ticket = "ST-" + make_token(real)            # carries username
        location = f"{service}?ticket={urllib.parse.quote(ticket)}"
        log(f"[ptc] LOGIN OK  username={real!r}  ->  ticket issued")
        # 302 with the ticket in Location; also echo in body for robustness
        return _resp(302, f"ticket={ticket}", extra={"Location": location})

    # 3) exchange ticket (code) for an access token
    if path == "/sso/oauth2.0/accessToken":
        code = (form.get("code", qs.get("code", [""]))[0]) or ""
        username = username_from_token(code[3:] if code.startswith("ST-") else code)
        token = make_token(username)
        log(f"[ptc] access_token issued for username={username!r}")
        return _resp(200, f"access_token={token}&expires=7200")

    # 4) profile -> only 'birthdate' is parsed by the client (age gate)
    if path == "/sso/oauth2.0/profile":
        token = qs.get("access_token", [""])[0]
        username = username_from_token(token)
        profile = {
            "id": _b64(username),
            "username": username,
            "screen_name": username,
            "birthdate": "1990-01-01",       # adult, passes the age gate
            "country": "US",
            "email_verified": "true",
        }
        log(f"[ptc] profile served for username={username!r}")
        return _resp(200, json.dumps(profile), "application/json")

    # OAuth authorize entrypoint -> bounce to the login page
    if path == "/sso/oauth2.0/authorize":
        service = qs.get("redirect_uri", [CALLBACK])[0]
        # RELATIVE redirect: keep the client on whatever host it reached us on
        # (bracky.playit.plus for a patched no-VPN client; sso.pokemon.com for a
        # DNS/VPN client). An absolute sso.pokemon.com URL would strand patched apps.
        loc = f"/sso/login?service={urllib.parse.quote(service)}"
        log("[ptc] authorize -> redirect to login")
        return _resp(302, "", extra={"Location": loc})

    log(f"[ptc] UNHANDLED {method} {path}?{query}")
    return _resp(404, "not found")
