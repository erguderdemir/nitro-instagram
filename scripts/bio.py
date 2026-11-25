#!/usr/bin/env python3
"""Instagram bio linkinin açtığı sayfa: docs/index.html

Instagram profil linki nitrobisiklet.com'dur; açıklamalar oranın aramasına yönlendirir (scripts/arama.py).
Bu sayfa yardımcı/yedek ürün listesidir:
  ?k=N247   kodu verilen ürünü en üstte gösterir
  ?q=kask   adında/kategorisinde geçen ürünleri listeler
Arama tüm mağaza ürünlerinde (stokta, fiyatı olan) çalışır; "Instagram'da son paylaşılanlar" yalnız yayınlanmış
kayıtlardan oluşur. Her bağlantı UTM taşır (utm_medium=bio).

  python3 scripts/bio.py
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import common
import content as C
from common import DOCS, ROOT, fmt_price, item_dt

OUT = DOCS / "index.html"
RECENT = 24


def _catalog() -> list[dict]:
    codes = common.load_codes()
    out = []
    for p in common.load_products():
        if not p.get("price") or p.get("in_stock") is not True or p["slug"] not in codes or C.excluded(p):
            continue
        code = codes[p["slug"]]
        out.append({"c": code, "n": C.display_name(p), "p": fmt_price(p["price"]), "k": p.get("category") or "",
                    "u": C.utm(p["url"], "bio", "arama", code), "i": (p.get("images") or [""])[0]})
    return sorted(out, key=lambda x: x["c"])


def _recent(cal: list[dict], now: datetime) -> list[dict]:
    """Yayınlanmış kayıtların ürünleri, en yenisi üstte, ürün başına tek satır."""
    seen, rows = set(), []
    for c in sorted(cal, key=item_dt, reverse=True):
        if c.get("status") != "published" or item_dt(c) > now:
            continue
        for x in c.get("products") or []:
            if x["slug"] in seen:
                continue
            seen.add(x["slug"])
            rows.append({"c": x["code"], "n": x["name"], "p": fmt_price(x["price"]), "k": x.get("category") or "",
                         "u": x.get("bio_link") or x["link"], "i": x.get("image") or ""})
    return rows[:RECENT]


PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NITRO Bisiklet · Instagram</title>
<meta name="robots" content="noindex"><link rel="stylesheet" href="fonts/fonts.css">
<style>
*{box-sizing:border-box}body{margin:0;background:#f1ede2;font-family:Barlow,system-ui,sans-serif;color:#14150f}
header{background:#14150f;color:#f1ede2;padding:20px 18px 18px;text-align:center}
header img{height:84px}header p{margin:8px 0 0;color:#a8b78a;font-size:15px}
main{max-width:540px;margin:0 auto;padding:16px}
.s{display:flex;gap:8px;margin:0 0 6px}
.s input{flex:1;min-width:0;font:600 18px Barlow,sans-serif;padding:15px 18px;border:2.5px solid #14150f;border-radius:999px;background:#fff;color:#14150f}
.s button{font:800 16px Archivo,sans-serif;padding:0 22px;border:0;border-radius:999px;background:#f5821f;color:#14150f}
.hint{font-size:14px;color:#6b6658;margin:0 6px 16px}
.btn{display:block;text-align:center;background:#14150f;color:#f1ede2;font:800 17px Archivo,sans-serif;padding:15px;border-radius:999px;text-decoration:none;margin:0 0 10px}
.btn.alt{background:transparent;color:#14150f;border:2.5px solid #14150f}
.card{display:flex;gap:14px;align-items:center;background:#fff;border-radius:18px;padding:10px;margin:0 0 10px;text-decoration:none;color:inherit}
.card img{width:92px;height:92px;object-fit:contain;border-radius:12px;background:#fff;flex:none}
.card b{display:block;font-size:16px;line-height:1.25}.card span{display:block;color:#a8480a;font-weight:700;margin:5px 0 2px;font-size:17px}
.card i{font-style:normal;font:700 12px 'Space Mono',monospace;color:#6b6658;letter-spacing:.08em}
h2{font:800 14px Archivo,sans-serif;letter-spacing:.12em;color:#6b6658;margin:22px 4px 10px;text-transform:uppercase}
.none{background:#fff;border-radius:18px;padding:18px;font-size:16px}
.foot{text-align:center;font-size:13px;margin:28px 0 10px}.foot a{color:#6b6658}
</style></head><body>
<header><img src="logo.png" alt="NITRO Bisiklet"><p>Köyceğiz · Bisiklet satış ve servis</p></header>
<main>
<form class="s" onsubmit="go(event)"><input id="q" type="search" placeholder="Ürün kodu ya da adı: N247, kask…" autocomplete="off" aria-label="Ürün ara"><button>Ara</button></form>
<p class="hint">Gönderideki ürün kodunu yaz, ürün sayfasına git.</p>
<div id="res"></div>
<a class="btn" href="__STORE__">Tüm ürünler · Mağaza</a>
<a class="btn alt" href="__SERVICE__">Servis randevusu al</a>
<div id="recent"></div>
<p class="foot"><a href="gizlilik.html">Gizlilik</a> · <a href="veri-silme.html">Veri silme</a></p>
</main>
<script>
var ALL=__ALL__,RECENT=__RECENT__;
function low(s){return (s||'').toLocaleLowerCase('tr').trim()}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function card(x){return '<a class="card" href="'+esc(x.u)+'">'+(x.i?'<img src="'+esc(x.i)+'" loading="lazy" alt="">':'')+
 '<div><b>'+esc(x.n)+'</b><span>'+esc(x.p)+'</span><i>KOD '+esc(x.c)+' · ÜRÜNE GİT</i></div></a>'}
function find(q){q=low(q);if(!q)return null;var code=q.replace(/\\s+/g,'');
 var hit=ALL.filter(function(x){return low(x.c)===code});if(hit.length)return hit;
 var parts=q.split(/\\s+/);return ALL.filter(function(x){var t=low(x.n+' '+x.k+' '+x.c);return parts.every(function(p){return t.indexOf(p)>=0})}).slice(0,40)}
function show(q){var r=find(q),el=document.getElementById('res');if(r===null){el.innerHTML='';return}
 el.innerHTML='<h2>Arama: '+esc(q)+'</h2>'+(r.length?r.map(card).join(''):'<div class="none">Bu kodla ya da adla ürün bulunamadı. Kodu gönderideki gibi yaz (ör. N247) ya da mağazaya göz at.</div>')}
function go(e){e.preventDefault();var q=document.getElementById('q').value;show(q);
 try{history.replaceState(null,'','?q='+encodeURIComponent(q))}catch(_){}}
(function(){var p=new URLSearchParams(location.search),q=p.get('k')||p.get('q')||'';
 if(q){document.getElementById('q').value=q;show(q)}
 if(RECENT.length)document.getElementById('recent').innerHTML='<h2>Instagram\\'da son paylaşılanlar</h2>'+RECENT.map(card).join('')})();
</script></body></html>
"""


def build_bio(cal: list[dict], now: datetime | None = None, out: Path | None = None) -> Path:
    now, out = now or common.now(), out or OUT
    site = common.load_site()
    store = C.utm((site.get("urls") or {}).get("magaza") or common.SITE + "/magaza/", "bio", "magaza", "buton")
    service = C.utm((site.get("service") or {}).get("booking_url") or common.SITE + "/servis/", "bio", "servis", "buton")
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (PAGE.replace("__STORE__", html.escape(store)).replace("__SERVICE__", html.escape(service))
            .replace("__ALL__", dump(_catalog())).replace("__RECENT__", dump(_recent(cal, now))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    logo = ROOT / "assets" / "logo.png"
    if logo.exists() and out.parent == DOCS and not (DOCS / "logo.png").exists():
        (DOCS / "logo.png").write_bytes(logo.read_bytes())
    return out


if __name__ == "__main__":
    print(build_bio(common.load_calendar()))
