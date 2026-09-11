"""
Phone shop -- https://pgorelease.nianticlabs.com/shop

NOTE (2026-08-17): the old claim that "the client's own shop makes NO server
request" turned out to be WRONG -- opening the Shop sends a platform request
(envelope field 6, request_type 5) and the item list goes back in the response's
field 6. The NATIVE in-game shop is now filled in by build_platform_shop() below
(wired through protocol.py/rpc.py). This web page stays as a fallback and, for
now, as the way to actually SPEND coins (the in-game *buy* request isn't captured
yet). The DNS redirect points this hostname at us and the phone trusts our CA, so
it loads with no extra setup.

Styled to look like the 2016 shop. Item art is inline SVG -- we have no icon
assets, and this keeps the page a single self-contained response.
"""
import json
import os
import sys
import urllib.parse

import webui

# (sku, label, item_id, count, price_in_coins, icon, was_price)
# `was` is the pre-discount price; 0 means no discount badge.
#
# The `sku` is CRITICAL for the in-game shop: the client renders each item's icon
# by matching this string (after stripping "pgorelease.") against its own bundled
# store SKUs. Only the SKUs the 2016 store actually sold have a bundled sprite --
# these exact strings were pulled out of the client (pokeball.100, luckyegg.8,
# incenseordinary.8, troydisk.1, incubatorbasic.1, itemstorageupgrade.1,
# pokemonstorageupgrade.1). Items that were never in the 2016 store (Great/Ultra
# Balls, Potions, Revives, Razz) have NO bundled icon and so are not sold here;
# they still come from PokeStops and level-ups. Keep every sku on this list an
# exact client SKU or the phone shows a blank tile. Prices are the real 2016 ones.
CATALOGUE = [
    ("pokeball.20",             "20 Poke Balls",         1,  20,  100, "pokeball",   0),
    ("pokeball.100",            "100 Poke Balls",        1, 100,  460, "pokeball",  500),
    ("pokeball.200",            "200 Poke Balls",        1, 200,  800, "pokeball", 1000),
    ("troydisk.1",              "Lure Module",         501,   1,  100, "lure",        0),
    ("troydisk.8",              "8 Lure Modules",      501,   8,  680, "lure",      800),
    ("incenseordinary.8",       "8 Incense",           401,   8,  500, "incense8",  640),
    ("incenseordinary.25",      "25 Incense",          401,  25, 1250, "incense8",    0),
    ("luckyegg.8",              "8 Lucky Eggs",        301,   8,  500, "luckyegg",  640),
    ("luckyegg.25",             "25 Lucky Eggs",       301,  25, 1250, "luckyegg",    0),
    ("incubatorbasic.1",        "Egg Incubator",       902,   1,  150, "incubator",   0),
    ("itemstorageupgrade.1",    "Bag Upgrade (+50)",     0,  50,  200, "bag",         0),
    ("pokemonstorageupgrade.1", "Pokemon Storage (+50)", 0,  50,  200, "box",         0),
]

# Item art is the REAL 2016 texture, pulled out of the APK's Unity assets
# (sharedassets0 -> Texture2D "Item_0001" etc, which are named by item id) and
# written to shopicons/ by tools/extract_shop_icons.py. Served from /shop/icon/.
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shopicons")
if getattr(sys, "frozen", False):
    ICON_DIR = os.path.join(sys._MEIPASS, "shopicons")


def icon_version():
    """Newest icon mtime, appended to every icon URL. Without this the phone
    keeps serving whatever it cached for a day -- which is exactly how a fixed
    Incense icon kept showing up as the old honey pot."""
    try:
        return str(int(max(os.path.getmtime(os.path.join(ICON_DIR, f))
                           for f in os.listdir(ICON_DIR))))
    except (OSError, ValueError):
        return "1"


# ---------------------------------------------------------------------------
# The NATIVE in-game shop (the client's own Shop screen).
#
# Long assumed impossible ("the client makes no server request for the shop") --
# but a live capture proved otherwise: opening the Shop sends an envelope with an
# EMPTY requests list plus a platform request (envelope field 6, request_type 5,
# "list IAP items"). The reply carries the item list in the response's field 6 as
# an Unknown6Response(response_type=5). So the real shop screen CAN be filled in,
# and it reuses the exact same CATALOGUE as the web shop above.
#
# Wire format (from node-pogo-protos POGOProtos.Networking.Envelopes):
#   Unknown6Response { response_type=1:int; unknown2=2:{
#       unknown1=1:uint (1=ok); items=2:repeated StoreItem;
#       player_currencies=3:repeated Currency; unknown4=4:string }}
#   StoreItem { item_id=1:str; is_iap=2:bool; currency_to_buy=3:Currency;
#       yields_currency=4:Currency; yields_item=5:ItemData; tags=6:repeated Tag;
#       unknown7=7:int }
#   Currency { name=1:str; amount=2:int }   ItemData { item_id=1:enum; count=2:int }
#   Tag { key=1:str; value=2:str }
# Storage upgrades have no bag item, so they yield the storage-upgrade ItemIds.
# storage-upgrade skus -> their ItemId (ITEM_ITEM_STORAGE_UPGRADE / _POKEMON_)
_STORAGE_ITEM = {"itemstorageupgrade.1": 1002, "pokemonstorageupgrade.1": 1001}


def _storage_kind(sku):
    """'items' (bag) or 'pokemon' (box) for a storage-upgrade sku."""
    return "items" if sku.startswith("itemstorage") else "pokemon"


def build_platform_shop(coins, stardust):
    """Bytes of the Unknown6Response(response_type=5) that fills the in-game Shop
    screen, priced in PokeCoins, ending with the player's live currencies."""
    import pb

    def _currency(name, amount):
        w = pb.Writer().string(1, name)
        if amount:
            w.uint(2, int(amount))
        return w.to_bytes()

    def _item_data(item_id, count):
        return pb.Writer().uint(1, int(item_id)).uint(2, int(count)).to_bytes()

    def _tag(key, value):
        return pb.Writer().string(1, key).string(2, value).to_bytes()

    def _store_item(sku, iid, cnt, price, sort):
        item_id = _STORAGE_ITEM.get(sku, iid)
        # A storage upgrade is "1 upgrade item"; the +50 comes from the item
        # template's additional_storage. Sending the 50 here (as if it were a
        # stack of 50 upgrade items) breaks the client's tile formatting so its
        # "+{0}" placeholder never fills. Mirror the authentic store data: count 1.
        is_upgrade = sku in _STORAGE_ITEM
        count = 1 if is_upgrade else cnt
        category = "UPGRADES" if is_upgrade else "ITEMS"
        w = pb.Writer().string(1, "pgorelease." + sku)   # item_id (display sku)
        w.message(3, _currency("POKECOIN", price))       # currency_to_buy
        w.message(5, _item_data(item_id, count))         # yields_item
        w.message(6, _tag("CATEGORY", category))         # tags (repeated)
        w.message(6, _tag("SORT", str(sort)))
        return w.to_bytes()

    inner = pb.Writer().uint(1, 1)                        # unknown1 = 1 (success)
    for sort, entry in enumerate(CATALOGUE, 1):
        sku, _label, iid, cnt, price, _icon, _was = entry
        inner.message(2, _store_item(sku, iid, cnt, price, sort))
    inner.message(3, _currency("POKECOIN", coins))        # player_currencies
    inner.message(3, _currency("STARDUST", stardust))

    return pb.Writer().uint(1, 5).message(2, inner).to_bytes()


def _sku_from_item_id(item_id):
    return (item_id[len("pgorelease."):]
            if item_id.startswith("pgorelease.") else item_id)


def purchase(item_id):
    """Run an in-game shop purchase for the CURRENT world account (caller must
    world.use() first). item_id is the "pgorelease.<sku>" string the client sends
    back from the shop list. Returns (ok, message). Mirrors the web /shop/buy path
    so both shops charge coins and grant items identically."""
    import world
    sku = _sku_from_item_id(item_id)
    entry = next((e for e in CATALOGUE if e[0] == sku), None)
    if not entry:
        return False, f"unknown item {sku}"
    _sku, label, iid, cnt, price, _icon, _was = entry
    if iid == 0:                                    # a storage upgrade
        ok, message, _new = world.buy_storage(_storage_kind(sku))
        return ok, message
    if world.room_in_bag() < cnt:
        return False, f"bag full ({world.bag_count()}/{world.MAX_ITEMS})"
    if world.spend_coins(price):
        total = world.add_item(iid, cnt)
        return True, f"got {label} (now {total})"
    return False, f"need {price} coins"


def build_buy_response(ok=True):
    """Platform response to a shop purchase (request_type 2). Best-effort ack:
    Unknown6Response{response_type=2, unknown2{unknown1=1(=ok)}} -- mirrors the
    shop list's success marker. The buy response isn't documented anywhere, so
    this is provisional; adjust if the phone shows an error after buying."""
    import pb
    inner = pb.Writer().uint(1, 1 if ok else 0)
    return pb.Writer().uint(1, 2).message(2, inner).to_bytes()


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Shop</title>
<style>__CSS__
 /* ---------- shop only ---------- */
 body{color:#48606e;min-height:100vh;
  background:linear-gradient(90deg,#7fd08a 0,#dff3e2 3%,#fbfefb 22%,#ffffff 50%,
             #fbfefb 78%,#dff3e2 97%,#7fd08a 100%)}
 /* ---------- sign in ---------- */
 #login{min-height:100vh;display:flex;flex-direction:column;justify-content:center;
  padding:30px 26px;gap:14px;max-width:460px;margin:0 auto}
 .logo{text-align:center;margin-bottom:4px}
 .logo .ball{width:92px;height:92px;margin:0 auto 12px;
  background:url('/shop/icon/pokeball.png?v=__ICONV__') center/contain no-repeat;
  filter:drop-shadow(0 8px 10px rgba(0,0,0,.18))}
 .logo h1{margin:0;font-size:30px;font-weight:800;letter-spacing:.06em;color:#3d5563}
 .logo p{margin:7px 0 0;font-size:13.5px;color:#7d94a1}
 .field{position:relative}
 .field input{width:100%;background:#fff;color:#33474f;font:inherit;font-size:16px;
  border:2px solid #dbe6df;border-radius:14px;padding:14px 15px}
 .field input:focus{outline:none;border-color:#4fc3a1}
 #sugg{position:absolute;left:0;right:0;top:100%;margin-top:6px;z-index:5;background:#fff;
  border:2px solid #dbe6df;border-radius:14px;overflow:hidden;display:none;
  box-shadow:0 10px 24px rgba(0,0,0,.12)}
 #sugg div{padding:13px 15px;font-size:15px;border-bottom:1px solid #eef3ef;color:#3d5563}
 #sugg div:last-child{border-bottom:0}
 #sugg div:active{background:#e8f7f0}
 .go{width:100%;border:0;border-radius:999px;padding:15px;font:inherit;font-weight:800;
  font-size:17px;letter-spacing:.04em;color:#fff;
  background:linear-gradient(180deg,#4fd0a8,#22a583);box-shadow:0 4px 0 #178065;cursor:pointer}
 .go:active{transform:translateY(2px);box-shadow:0 2px 0 #178065}
 .note{text-align:center;font-size:11.5px;color:#8ba0ab;line-height:1.65}
 /* ---------- shop ---------- */
 #app{display:none;padding:74px 8px 120px}
 .hud{position:fixed;top:8px;right:8px;z-index:12;background:rgba(94,104,112,.92);
  border-radius:12px;padding:8px 14px 9px;min-width:172px;color:#fff;
  box-shadow:0 6px 18px rgba(0,0,0,.25)}
 .hud .c{display:flex;align-items:center;gap:9px;font-size:21px;font-weight:800;
  color:#ffd76a;letter-spacing:.02em}
 .hud hr{border:0;border-top:1px solid rgba(255,255,255,.32);margin:7px 0 6px}
 .hud .u{display:flex;align-items:center;gap:9px;font-size:19px;font-weight:700}
 .hud .u .av{width:26px;height:26px;border-radius:7px;flex:none;
  background:url('/shop/icon/pokeball.png?v=__ICONV__') center/contain no-repeat #fff}
 .hud .u span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px}
 .coin{width:24px;height:24px;flex:none;display:inline-block;
  background:url('/shop/icon/coin.png?v=__ICONV__') center/contain no-repeat}
 .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 4px;max-width:640px;margin:0 auto}
 .item{padding:6px 4px 14px;text-align:center;display:flex;flex-direction:column;
  align-items:center;gap:2px}
 .art{position:relative;width:100%;display:grid;place-items:center;padding:6px 0 2px}
 .art img{width:104px;height:104px;object-fit:contain;
  filter:drop-shadow(0 6px 6px rgba(0,0,0,.14))}
 .off{position:absolute;left:2px;bottom:0;background:rgba(90,101,110,.88);color:#fff;
  font-size:13px;font-weight:800;letter-spacing:.02em;padding:4px 9px;border-radius:5px}
 .nm{font-weight:700;font-size:14.5px;line-height:1.18;color:#4a6472;
  letter-spacing:.01em;text-transform:uppercase;min-height:34px;
  display:flex;align-items:center;justify-content:center;padding:0 2px}
 .buy{margin-top:4px;width:100%;border:0;border-radius:11px;padding:10px 6px;
  font:inherit;cursor:pointer;background:#eef3ee;color:#3f5a67;
  display:flex;align-items:center;justify-content:center;gap:7px}
 .buy b{font-size:19px;font-weight:800}
 .buy s{font-size:15px;color:#9fb0b8;font-weight:700}
 .buy:active{background:#e2ebe2;transform:translateY(1px)}
 .buy[disabled]{opacity:.45}
 .close{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:12;
  width:62px;height:62px;border-radius:50%;border:0;cursor:pointer;
  background:linear-gradient(180deg,#37b6c9,#1d94a8);box-shadow:0 5px 0 #14707f,
  0 10px 22px rgba(0,0,0,.28);color:#fff;font-size:30px;line-height:1;font-weight:300}
 .close:active{transform:translateX(-50%) translateY(3px);box-shadow:0 2px 0 #14707f}
 #toast{position:fixed;left:50%;bottom:104px;transform:translate(-50%,14px);
  background:rgba(52,66,74,.97);color:#fff;padding:13px 20px;border-radius:14px;
  font-size:14px;font-weight:600;max-width:86vw;text-align:center;opacity:0;
  transition:.25s;pointer-events:none;z-index:20}
 #toast.on{opacity:1;transform:translate(-50%,0)}
 #toast.bad{background:rgba(150,52,58,.97)}
 .foot{text-align:center;font-size:11px;color:#9fb2bb;padding:14px 20px 0;line-height:1.6}
</style></head><body>

<div id="login">
  <div class="logo"><div class="ball"></div><h1>SHOP</h1>
    <p>Sign in with your trainer name</p></div>
  <div class="field">
    <input id="user" placeholder="Trainer name" autocomplete="off"
           autocapitalize="off" spellcheck="false" oninput="search()" onfocus="search()">
    <div id="sugg"></div>
  </div>
  <div class="field">
    <input id="pass" type="password" placeholder="Password" autocomplete="off">
  </div>
  <button class="go" onclick="signIn()">SIGN IN</button>
  <div class="note">Same trainer name and password you use in game.<br>
    A brand new name claims itself, and the password you type becomes its password.</div>
</div>

<div id="app">
  <div class="hud">
    <div class="c"><span class="coin"></span><span id="coins">0</span></div>
    <hr>
    <div class="u"><span class="av"></span><span id="whoname">-</span></div>
  </div>
  <div class="grid" id="grid"></div>
  <div class="foot">Earn PokeCoins by leaving Pokemon to defend a Gym.<br>
  Purchases appear in your bag within a few seconds.</div>
  <button class="close" onclick="signOut()" title="Close">&#10005;</button>
</div>
<div id="toast"></div>

<script>
const CAT = __CATALOGUE__, IV = '__ICONV__';
const $ = id => document.getElementById(id);
let coins = 0, me = null, accounts = [], timer = null;

async function api(path, body){
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                               body: JSON.stringify(body||{})});
  return r.json();
}
function toast(msg, bad){
  const t = $('toast'); t.textContent = msg; t.className = 'on' + (bad ? ' bad' : '');
  clearTimeout(t._t); t._t = setTimeout(function(){ t.className=''; }, 2600);
}
/* ---- sign in ---- */
function search(){
  const q = $('user').value.trim().toLowerCase();
  const hits = accounts.filter(function(n){ return !q || n.toLowerCase().includes(q); }).slice(0, 6);
  const box = $('sugg');
  box.innerHTML = '';
  if (!hits.length){ box.style.display='none'; return; }
  hits.forEach(function(n){
    const d = document.createElement('div'); d.textContent = n;
    d.onclick = function(){ $('user').value = n; box.style.display='none'; };
    box.appendChild(d);
  });
  box.style.display = 'block';
}
async function signIn(){
  const name = $('user').value.trim();
  if (!name) return toast('Enter your trainer name', true);
  const r = await api('/shop/login', {player: name, password: $('pass').value});
  if (!r.ok) return toast(r.message, true);
  me = r.player; localStorage.setItem('pogo_shop_who', me);
  $('sugg').style.display='none';
  $('login').style.display='none'; $('app').style.display='block';
  $('whoname').textContent = me;
  refresh();
  if (!timer) timer = setInterval(refresh, 15000);
}
function signOut(){
  localStorage.removeItem('pogo_shop_who');
  me = null; $('app').style.display='none'; $('login').style.display='flex';
  $('pass').value=''; search();
}
/* ---- shop ---- */
function draw(){
  const g = $('grid'); g.innerHTML='';
  CAT.forEach(function(row){
    const sku=row[0], label=row[1], cnt=row[3], price=row[4], icon=row[5], was=row[6]||0;
    const it = document.createElement('div'); it.className='item';
    const off = was > price ? Math.round((1 - price/was) * 100) : 0;
    it.innerHTML =
      '<div class="art"><img src="/shop/icon/'+icon+'.png?v='+IV+'" alt="">'
      + (off ? '<div class="off">'+off+'% OFF</div>' : '')
      + '</div><div class="nm">'+label+'</div>';
    const b = document.createElement('button');
    b.className='buy'; b.disabled = coins < price;
    b.innerHTML = '<span class="coin"></span><b>'+price+'</b>'
                + (off ? '<s>'+was+'</s>' : '');
    b.onclick = function(){ buy(sku, b); };
    it.appendChild(b); g.appendChild(it);
  });
}
async function buy(sku, btn){
  btn.disabled = true;
  const r = await api('/shop/buy', {sku: sku, player: me});
  toast(r.message, !r.ok);
  if (r.coins !== undefined) coins = r.coins;
  draw();
}
async function refresh(){
  try {
    const r = await api('/shop/state', {player: me});
    coins = r.coins || 0; $('coins').textContent = coins;
  } catch (e) { /* keep the shelves up even if the balance cannot be read */ }
  draw();
}
// Draw the shelves FIRST. The page used to render nothing at all until the
// server answered, so any hiccup looked like an empty shop.
draw();
(async function(){
  try {
    const st = await api('/shop/state', {});
    accounts = st.accounts || [];
    const saved = localStorage.getItem('pogo_shop_who');
    if (saved && accounts.indexOf(saved) >= 0) { $('user').value = saved; $('pass').focus(); }
    else if (st.player) $('user').value = st.player;
  } catch (e) {
    toast('Could not reach the server', true);
  }
})();
</script></body></html>"""


def _json(obj, code=200):
    body = json.dumps(obj).encode("utf-8")
    return code, {"Content-Type": "application/json", "Cache-Control": "no-store"}, body


def handle(method, path, query, headers, body, log):
    import world
    if path in ("/shop", "/shop/"):
        page = (webui.render_phone(PAGE)
                    .replace("__CATALOGUE__", json.dumps(CATALOGUE))
                    .replace("__ICONV__", icon_version()))
        return (200, {"Content-Type": "text/html; charset=utf-8",
                      "Cache-Control": "no-store"}, page.encode("utf-8"))

    if path.startswith("/shop/icon/"):
        name = os.path.basename(path[len("/shop/icon/"):])
        fp = os.path.join(ICON_DIR, name)
        if name.endswith(".png") and os.path.isfile(fp):
            with open(fp, "rb") as fh:
                return (200, {"Content-Type": "image/png",
                              "Cache-Control": "public, max-age=600"}, fh.read())
        return 404, {"Content-Type": "text/plain"}, b"no icon"

    try:
        d = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        d = {}
    who = (d.get("player") or "").strip()
    names = world.account_names()

    if path == "/shop/state":
        # Default to whoever is actually playing, so the phone opens on the
        # right trainer without anyone having to pick one.
        import rpc
        cur = getattr(rpc, "_last_user", [None])[0]
        target = who if who in names else (cur if cur in names else
                                           (names[0] if names else None))
        if not target:
            return _json({"accounts": [], "coins": 0, "player": None})
        with world.acting_as(target):
            return _json({"accounts": names, "player": target,
                          "coins": world.COINS,
                          "bag": world.bag_count(), "bag_max": world.MAX_ITEMS})

    if path == "/shop/login":
        # Same credentials as the game: the trainer name is the account and the
        # password is the one set on that account's first login.
        ok, why, real = world.check_login(who, d.get("password") or "")
        if not ok:
            log("[shop] sign-in refused for " + repr(who) + " (" + why + ")")
            msg = ("Wrong password." if why == "wrong password"
                   else "Enter your trainer name.")
            return _json({"ok": False, "message": msg})
        log("[shop] " + real + " signed in")
        return _json({"ok": True, "player": real})

    if path == "/shop/buy":
        entry = next((e for e in CATALOGUE if e[0] == d.get("sku")), None)
        if not entry or who not in names:
            return _json({"ok": False, "message": "That didn't work."})
        _sku, label, iid, cnt, price, _icon, _was = entry
        with world.acting_as(who):
            if iid == 0:                                   # a storage upgrade
                ok, message, _new = world.buy_storage(_storage_kind(_sku))
                log(f"[shop] {who}: {label} -> {message}")
                return _json({"ok": ok, "message": message, "coins": world.COINS})
            if world.room_in_bag() < cnt:
                return _json({"ok": False, "coins": world.COINS,
                              "message": f"Your bag is full ({world.bag_count()}"
                                         f"/{world.MAX_ITEMS})."})
            if world.spend_coins(price):
                total = world.add_item(iid, cnt)
                log(f"[shop] {who} bought {cnt} x {label} for {price} coins "
                    f"(now has {total})")
                # the label already carries the count ("200 Poke Balls"), so
                # don't prefix it again
                return _json({"ok": True, "coins": world.COINS,
                              "message": f"Got {label}!"})
            return _json({"ok": False, "coins": world.COINS,
                          "message": f"You need {price} PokéCoins."})

    return 404, {"Content-Type": "text/plain"}, b"no"
