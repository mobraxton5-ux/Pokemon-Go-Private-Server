"""
Shared look for the web pages this server serves:

  World Manager   http://127.0.0.1:8080           (admin.py, this PC only)
  Shop            https://pgorelease.../shop      (shop.py, on the phone)
  Help Center     https://pokemongo.zendesk.../hc (helpcenter.py, on the phone)

The two PHONE pages (shop, help) are dressed as Pokemon GO itself -- white rounded
cards on a blue-green map wash -- so they don't read as a different program bolted
onto the game. The World Manager runs only on this PC, is never seen inside the
game, and is a control panel, so it wears the Project Windstock identity instead:
a clean royal-blue admin dashboard.

Each page keeps its own <style> for what is genuinely its own (the map, the shop's
item art) and puts `__CSS__` in the <head> where the shared layer goes. Everything
is inline: the phone reaches its pages through our DNS redirect with no route to
the real internet, so a CDN font or stylesheet would just hang.
"""

# One palette for the two PHONE pages. Pulled towards the game's own: the map's
# teal-blue, the Poke Ball red, the PokeCoin gold, the team blue.
PALETTE = r"""
:root{
  --ink:#22404c; --ink2:#5b7683; --ink3:#8ba0ab;
  --card:#ffffff; --soft:#f3f9f6; --line:#dde8e3;
  --teal:#22987c; --teal-lt:#3ec39f; --teal-dk:#17705c;
  --blue:#1f9bd1; --blue-lt:#4ec3e8; --blue-dk:#14719c;
  --red:#ee6b5b; --red-dk:#c14a3c;
  --gold:#f5c33b; --grass:#6ecb63;
  --r:16px; --r-sm:12px; --r-pill:999px;
  --shadow:0 3px 12px rgba(20,60,80,.10);
  --shadow-lg:0 10px 30px rgba(20,60,80,.16);
  --font:-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,monospace;
  --safe-b:env(safe-area-inset-bottom,0px);
}
"""

# Shared behaviour for both phone pages. Goes FIRST in their <style> block so
# each page's own rules still win. It carries what is easy to forget on a phone
# and unpleasant when missing: notch insets, no zoom-on-focus, honest disabled
# states, no rubber-banding.
PHONE_CSS = PALETTE + r"""
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;font-family:var(--font);color:var(--ink);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  overscroll-behavior-y:contain;
}
/* 16px minimum on inputs, or iOS zooms the page in when one is tapped */
input,textarea,select,button{font-family:inherit;font-size:16px}
button{cursor:pointer;transition:transform .12s ease,background .16s ease,box-shadow .16s ease}
button:disabled{opacity:.5;cursor:not-allowed;transform:none!important}
:focus-visible{outline:3px solid rgba(56,165,140,.45);outline-offset:2px}
img{max-width:100%}
.close,#toast{margin-bottom:var(--safe-b)}
.wrap,#app,#login{padding-bottom:calc(28px + var(--safe-b))}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:#cfdcd6;border-radius:99px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

# The World Manager -- Project Windstock admin dashboard, sized for a desktop
# browser. Self-contained (its own :root). The variable NAMES match what admin.py's
# inline map CSS reads (--line, --ink, --soft, --r-sm, --shadow, --font, --mono, ...)
# so re-theming here needs no change there.
CSS = r"""
:root{
  /* Windstock -- royal blue brand on a cool neutral shell */
  --brand:#2358d8; --brand-dk:#173f9e; --brand-lt:#4c7bf0;
  --ink:#172236; --ink2:#586074; --ink3:#8b93a6;
  --bg:#eaeef6; --card:#ffffff; --soft:#f3f6fc; --line:#e4e9f2;
  --blue:#2358d8; --blue-lt:#4c7bf0; --blue-dk:#173f9e;
  --teal:#0e9e88; --teal-lt:#1fbfa4; --teal-dk:#0b7d6c;
  --red:#e2503b; --red-dk:#bd3c2b;
  --gold:#c98a12; --grass:#37b24d;
  --r:16px; --r-sm:11px; --r-pill:999px;
  --shadow:0 1px 2px rgba(23,40,80,.05),0 6px 18px -10px rgba(23,40,80,.18);
  --shadow-lg:0 12px 34px -14px rgba(23,40,80,.30);
  --font:-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,monospace;
  --safe-b:env(safe-area-inset-bottom,0px);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:var(--font);font-size:15px;line-height:1.55;color:var(--ink);
  -webkit-font-smoothing:antialiased;min-height:100vh;background:var(--bg);
}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

/* ---------------------------------------------------------- app bar */
header{
  position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:16px;
  padding:13px clamp(16px,4vw,30px);
  background:var(--card);border-bottom:1px solid var(--line);
}
header .brand{display:flex;align-items:center;gap:12px;min-width:0}
header .mark{
  flex:none;width:40px;height:40px;border-radius:11px;background:var(--brand);
  display:flex;align-items:center;justify-content:center;
}
header .mark svg{width:25px;height:25px;display:block}
header .word{display:flex;flex-direction:column;line-height:1.12;min-width:0}
h1{
  margin:0;font-size:19px;font-weight:800;letter-spacing:-.01em;color:var(--ink);
  text-transform:none;text-shadow:none;white-space:nowrap;
}
header .word small{font-size:11px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink3)}
header .spacer{flex:1}
.topnav{display:flex;gap:4px;margin-left:14px}
.topnav a{
  padding:8px 14px;border-radius:var(--r-pill);font-size:13px;font-weight:700;
  color:var(--ink2);text-decoration:none;transition:background .15s,color .15s;
}
.topnav a:hover{background:var(--soft);color:var(--ink)}
.topnav a.active{background:#e9effb;color:var(--brand-dk)}
@media(max-width:680px){.topnav{margin-left:0;order:3;width:100%}}
.pill{
  display:inline-flex;align-items:center;gap:8px;flex:none;
  background:#eafaf2;border:1px solid #bfead4;border-radius:var(--r-pill);
  padding:7px 14px;color:#127a45;font-size:11.5px;font-weight:800;letter-spacing:.09em;
}
.pill::before{
  content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;
  box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:beat 2s infinite;
}
@keyframes beat{70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}
                100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.meta{
  flex:none;text-align:right;font-size:12px;color:var(--ink2);line-height:1.7;
  padding-left:16px;border-left:1px solid var(--line);
}
.meta b{font-family:var(--mono);font-weight:700;color:var(--ink)}
@media(max-width:680px){header{flex-wrap:wrap;gap:10px}.meta{display:none}}

/* ---------------------------------------------------------- layout */
.wrap{max-width:1060px;margin:0 auto;padding:26px clamp(14px,4vw,26px) 60px}
h2{
  display:flex;align-items:center;gap:10px;
  font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;
  color:var(--brand-dk);margin:30px 2px 12px;
}
h2::before{content:"";width:5px;height:15px;border-radius:3px;background:var(--brand)}
h2:first-of-type{margin-top:6px}

/* each control group / list is a clean panel */
.bar{
  display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:flex-start;
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:14px 16px;margin:0 0 12px;box-shadow:var(--shadow);
}
.bar+.bar{margin-top:-4px}
.list{margin:0 0 12px}

/* ---------------------------------------------------------- controls */
button,select,input[type=text],input[type=password],input[type=number],input:not([type]){
  font:inherit;font-size:14px;color:var(--ink);background:var(--card);
  border:1.5px solid var(--line);border-radius:var(--r-sm);padding:10px 14px;
  transition:background .15s,border-color .15s,box-shadow .15s,transform .1s;
}
input::placeholder{color:var(--ink3)}
button{cursor:pointer;font-weight:700;color:var(--ink)}
button:hover{border-color:#cdd7ea;background:var(--soft)}
button:focus-visible,input:focus,select:focus{
  outline:none;border-color:var(--brand-lt);box-shadow:0 0 0 3.5px rgba(76,123,240,.2)}
select{background:var(--card)}

button.on{background:var(--brand);border-color:var(--brand);color:#fff}
button.on:hover{background:var(--brand-dk);border-color:var(--brand-dk);color:#fff}
button.on:active{transform:translateY(1px)}
button.danger{color:#fff;background:var(--red);border-color:var(--red)}
button.danger:hover{background:var(--red-dk);border-color:var(--red-dk);color:#fff}
button.danger:active{transform:translateY(1px)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
button.go,.go{
  width:100%;padding:14px;font-size:15px;font-weight:800;letter-spacing:.03em;
  text-transform:uppercase;color:#fff;border:none;border-radius:var(--r-pill);
  background:var(--teal);
}
.go:hover{background:var(--teal-dk);color:#fff}
.go:active{transform:translateY(1px)}

label,.field label{display:block;font-size:11px;color:var(--ink2);
  letter-spacing:.07em;text-transform:uppercase;margin-bottom:6px;font-weight:800}
.inline-label{align-self:center;font-size:13px;color:var(--ink2);font-weight:700}
.field{margin-bottom:14px}
.field input,.field select{width:100%}

/* ---------------------------------------------------------- cards/rows */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:20px;margin:0 0 14px;box-shadow:var(--shadow)}
.sub{color:var(--ink2);font-size:13.5px;margin:6px 0 16px}
.hint{font-size:12.5px;color:var(--ink2);padding:2px 2px 14px;line-height:1.6}
.note,.foot,.quota{font-size:12.5px;color:var(--ink3);line-height:1.7}
.empty{color:var(--ink3);text-align:center;padding:22px;font-size:13.5px;
  background:var(--card);border:1px dashed var(--line);border-radius:var(--r)}
.row{
  display:flex;align-items:center;gap:12px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--r-sm);
  padding:12px 15px;margin-bottom:8px;font-size:14px;box-shadow:var(--shadow);
  transition:transform .1s,box-shadow .15s,border-color .15s;
}
.row:hover{transform:translateY(-1px);box-shadow:var(--shadow-lg);border-color:#d7e0f0}
.row .t{flex:1;color:var(--ink)}
.row .x{color:var(--red);cursor:pointer;padding:4px 10px;border-radius:8px;font-weight:800}
.row .x:hover{background:rgba(226,80,59,.12)}
.tag{border-radius:var(--r-pill);padding:4px 11px;font-size:10px;font-weight:800;
  letter-spacing:.06em;text-transform:uppercase;color:#fff}
.stop{background:var(--blue)}
.gym{background:var(--red)}
.mon{background:var(--grass)}
.coins{color:var(--gold);font-family:var(--mono);font-weight:800}
.by{color:var(--ink3)}

/* ---------------------------------------------------------- misc */
.warn{
  margin:0 0 14px;padding:14px 16px;
  background:#fff7e6;border:1px solid #f2dca0;border-left:5px solid var(--gold);
  border-radius:var(--r);color:#7a5a12;font-size:13.5px;box-shadow:var(--shadow);
}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
  gap:12px;padding:4px 0 10px}

/* -------------------------------------------------- world-data downloads */
.crumbs{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink3);margin:2px 0 14px}
.crumbs a{color:var(--brand);font-weight:700}
.dlbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:0 0 16px;
  font-size:13.5px;color:var(--ink2)}
.dlbar b{font-family:var(--mono);color:var(--brand-dk)}
.dlgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.dlcard{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  background:var(--card);border:1px solid var(--line);border-radius:var(--r-sm);
  padding:13px 15px;box-shadow:var(--shadow);
  transition:transform .1s,box-shadow .15s,border-color .15s;
}
.dlcard:hover{transform:translateY(-1px);box-shadow:var(--shadow-lg);border-color:#d7e0f0}
.dlcard .nm{font-weight:700;color:var(--ink);font-size:14.5px}
.dlcard .sub{font-size:11px;color:var(--ink3);margin:2px 0 0}
.dlcard button{padding:8px 15px;font-size:13px}
.dlcard .st{font-size:12.5px;font-weight:800;white-space:nowrap}
.dlcard .st.done{color:var(--grass)} .dlcard .st.busy{color:var(--brand)}
.dlcard .st.err{color:var(--red);cursor:pointer;text-decoration:underline}
.dlcard.group{cursor:pointer;text-decoration:none;background:#f2f6fe;border-color:#d7e2fb}
.dlcard.group .go-in{color:var(--brand-dk);font-weight:800;font-size:20px;line-height:1}
.dlcard.done-c{background:#f1fbf4;border-color:#c7ecd2}
.spin{display:inline-block;width:13px;height:13px;border:2px solid #c9d6f2;
  border-top-color:var(--brand);border-radius:50%;animation:sp .7s linear infinite;
  vertical-align:-2px;margin-right:6px}
@keyframes sp{to{transform:rotate(360deg)}}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#cdd7ea;border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:#b7c4de}
@media(max-width:520px){
  .bar{gap:8px;padding:12px}
  button,select,input{padding:9px 12px;font-size:13.5px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def render(page: str) -> str:
    """Drop the World Manager stylesheet into a page marked with `__CSS__`."""
    return page.replace("__CSS__", CSS)


def render_phone(page: str) -> str:
    """Same, for the two pages the phone opens."""
    return page.replace("__CSS__", PHONE_CSS)
