"""
The World Data pages for the World Manager: download real PokeStops + Gyms for a
country (or a US state) from OpenStreetMap. Same Windstock dashboard skin as the
manager (webui.CSS via __CSS__). Backend lives in poidownload.py.
"""
import json

import poidownload as DL
import webui

_HEAD = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style></head><body>
<header>
  <div class="brand">
    <div class="mark"><svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M5 3v18" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M5 6.6 L20 9 L20 13 L5 15.4 Z" fill="#fff"/>
      <path d="M10 7.3v6.9M14.4 7.9v5.6" stroke="#2358d8" stroke-width="1.4" stroke-linecap="round"/>
    </svg></div>
    <div class="word"><h1>Windstock</h1><small>World Manager</small></div>
  </div>
  <nav class="topnav"><a href="/">Manager</a><a class="active" href="/downloads">World Data</a></nav>
  <div class="spacer"></div>
  <div class="meta">Forts in world <b id="forts">&hellip;</b></div>
</header>
<main class="wrap">
"""

_TAIL = r"""
</main>
<script>
const ITEMS=__ITEMS__;
const $=s=>document.querySelector(s);
function card(it){
  if(it.group){
    return '<a class="dlcard group" href="'+it.href+'"><div><div class="nm">'+it.name+
      '</div><div class="sub">'+it.sub+'</div></div><div class="go-in">&rsaquo;</div></a>';
  }
  return '<div class="dlcard" data-region="'+it.region+'" data-name="'+it.name+'">'+
    '<div><div class="nm">'+it.name+'</div><div class="sub">'+it.region+'</div></div>'+
    '<div class="act"></div></div>';
}
function paint(st){
  if(st && typeof st.forts==='number') $('#forts').textContent=st.forts.toLocaleString();
  document.querySelectorAll('.dlcard[data-region]').forEach(c=>{
    const r=c.dataset.region, n=c.dataset.name, a=c.querySelector('.act');
    if(st && st.busy && st.busy[r]){
      a.innerHTML='<span class="st busy"><span class="spin"></span>'+st.busy[r]+'</span>';
    }else if(st && st.errors && st.errors[r]){
      c.classList.remove('done-c');
      a.innerHTML='<span class="st err" title="'+(st.errors[r]||'').replace(/"/g,'&quot;')+
        '">Failed &middot; retry</span>';
      a.querySelector('.st').onclick=()=>go(r,n);
    }else if(st && st.done && st.done.indexOf(r)>=0){
      c.classList.add('done-c');
      a.innerHTML='<span class="st done">&check; Added</span>'+
        '<button style="margin-left:10px" onclick="go(\''+r+'\',\''+n+'\')">Update</button>'+
        '<button class="danger" style="margin-left:6px" onclick="rm(\''+r+'\',\''+n+'\')">Remove</button>';
    }else{
      c.classList.remove('done-c');
      a.innerHTML='<button class="on" onclick="go(\''+r+'\',\''+n+'\')">Download</button>';
    }
  });
}
function go(region,name){
  fetch('/downloads/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({region,name})}).then(()=>refresh());
}
function rm(region,name){
  if(!confirm('Remove all of '+name+"'s PokeStops and Gyms from your world?"))return;
  fetch('/downloads/remove',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({region,name})}).then(()=>refresh());
}
function refresh(){fetch('/api/downloads/status').then(r=>r.json()).then(paint).catch(()=>{});}
$('#dlgrid').innerHTML=ITEMS.map(card).join('');
refresh(); setInterval(refresh,4000);
</script>
</body></html>"""


def _render(title, items, intro):
    body = ('<h2>' + title + '</h2>\n' + intro +
            '<div id="dlgrid" class="dlgrid"></div>')
    html = _HEAD.replace("__TITLE__", title) + body + _TAIL
    html = html.replace("__ITEMS__", json.dumps(items))
    return webui.render(html)


def world():
    """Countries. The United States is a group that opens its states sub-page."""
    items = []
    for name, region in DL.COUNTRIES.items():
        if region == "north-america/us":
            items.append({"group": True, "name": "United States",
                          "sub": str(len(DL.US_STATES)) + " states · pick a state",
                          "href": "/downloads/us"})
        else:
            items.append({"name": name, "region": region})
    intro = ('<div class="dlbar">Pick a country to pull its real PokeStops and Gyms '
             'from OpenStreetMap. Each one downloads and appends into your world &mdash; '
             'no restart, and adding one twice never doubles anything.</div>')
    return _render("World Data", items, intro)


def us():
    """US states sub-page."""
    items = [{"name": name, "region": region}
             for name, region in DL.US_STATES.items()]
    intro = ('<div class="crumbs"><a href="/downloads">World Data</a> '
             '&rsaquo; <span>United States</span></div>'
             '<div class="dlbar">The whole-country extract is enormous, so the US is '
             'offered a state at a time. Download the states you play in.</div>')
    html = _render("United States", items, intro)
    # this page's nav crumb already covers "back"; keep World Data tab highlighted
    return html
