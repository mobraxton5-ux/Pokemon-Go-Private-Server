"""
Tiny local web UI to grab businesses -> stops for the server, with a click-to-pick map.

Undesigned on purpose: a small OpenStreetMap minimap you click (or search a city) to
set the centre, then one button pulls every real business/park/shop from OSM in that
area, makes ~1 in 10 a gym, and installs them into the running server at their real
coordinates. Every stop placed is written to server/data/stops_log.txt.

Run:
  py ../tools/exporter_web.py        # then open http://127.0.0.1:8891
"""
import http.server
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import grab_stops as gs  # noqa: E402  (geocode + grab + install + TARGETS/LOG)

PORT = 8891


def run_job(form):
    clat = float(form["lat"][0]); clng = float(form["lng"][0])
    radius = float(form.get("radius", ["8"])[0])
    gym_every = int(form.get("gym_every", ["10"])[0])
    append = "append" in form
    forts = gs.grab(clat, clng, radius, gym_every)
    if not forts:
        return "Found 0 businesses there. Pick a more built-up spot or a bigger radius."
    header = f"{clat},{clng} r={radius}km 1/{gym_every}gym {'append' if append else 'replace'}"
    gs.install(forts, append, header)
    s = sum(1 for f in forts if f["kind"] == "stop")
    return (f"OK: installed {len(forts)} forts ({s} stops, {len(forts) - s} gyms)\n"
            f"at {clat},{clng} (real coordinates)\n"
            f"logged to {gs.LOG} (view at /log)\n"
            "Set your in-game location there and refresh the map (no restart).")


PAGE = """<!doctype html><meta charset=utf-8><title>Grab stops</title>
<link rel=stylesheet href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>#map{height:320px;width:100%;max-width:640px;border:1px solid #999}
 body{font-family:sans-serif;margin:1em;max-width:660px}
 input{padding:2px}</style>
<h2>Grab businesses &rarr; stops</h2>
<p>Search a city, or <b>click the map</b> to set the center. Then Install.</p>
<p><input id=q size=32 placeholder="city, e.g. Rapid City, SD">
   <button onclick="search()">search</button></p>
<div id=map></div>
<form onsubmit="go(event)">
 <p>lat <input name=lat id=lat size=12 readonly>
    lng <input name=lng id=lng size=12 readonly></p>
 <p>radius km <input name=radius value="8" size=5>
    &nbsp; 1 in <input name=gym_every value="10" size=4> is a gym</p>
 <p><label><input type=checkbox name=append> append (keep existing stops)</label></p>
 <p><button>Install stops</button> &nbsp; <a href="/log" target=_blank>view stop log</a></p>
</form>
<pre id=out>(pick a spot, then Install &mdash; grabbing a whole city takes a minute)</pre>
<script>
let map=L.map('map').setView([42.94413,-102.23602],5), marker=null;
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,
  attribution:'&copy; OpenStreetMap'}).addTo(map);
function setPt(la,ln){document.getElementById('lat').value=la.toFixed(5);
  document.getElementById('lng').value=ln.toFixed(5);
  if(marker)marker.setLatLng([la,ln]); else marker=L.marker([la,ln]).addTo(map);}
map.on('click',e=>setPt(e.latlng.lat,e.latlng.lng));
async function search(){let q=document.getElementById('q').value;if(!q)return;
  let r=await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q='
    +encodeURIComponent(q));let d=await r.json();
  if(!d.length){alert('city not found');return;}
  let la=+d[0].lat,ln=+d[0].lon;map.setView([la,ln],13);setPt(la,ln);}
async function go(e){e.preventDefault();
  if(!document.getElementById('lat').value){alert('pick a spot on the map first');return;}
  let out=document.getElementById('out');out.textContent='working... (may take a minute)';
  let r=await fetch('/run',{method:'POST',body:new URLSearchParams(new FormData(e.target))});
  out.textContent=await r.text();}
</script>"""


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/log"):
            try:
                with open(gs.LOG, encoding="utf-8") as fh:
                    body = fh.read()
            except OSError:
                body = "(no stops placed yet)"
            return self._send(body, "text/plain; charset=utf-8")
        self._send(PAGE)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
        try:
            self._send(run_job(form), "text/plain; charset=utf-8")
        except Exception as e:
            self._send(f"error: {type(e).__name__}: {e}", "text/plain; charset=utf-8")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Grab-stops UI -> http://127.0.0.1:{PORT}")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
