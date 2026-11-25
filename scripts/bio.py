#!/usr/bin/env python3
"""Instagram bio linkinin açtığı sayfa: docs/index.html

Instagram profil linki nitrobisiklet.com'dur; açıklamalar oranın aramasına yönlendirir (scripts/arama.py).
Bu sayfa yardımcı/yedek ürün listesidir:
  ?k=N247   eski bağlantılar için: kodu verilen ürünü en üstte gösterir (sayfada kod gösterilmez, istenmez)
  ?q=kask   adında/kategorisinde (ya da doğrulanmış arama teriminde) geçen ürünleri listeler
Arama önce son paylaşılan postlarda (bağlantı utm_content=<post-id>), sonra tüm mağaza ürünlerinde (stokta, fiyatı
olan) çalışır; "Instagram'da son paylaşılanlar" yalnız son 14 günde yayınlanmış POST kayıtlarından oluşur (story
kaynaklı bağlantı yok). Telefon, WhatsApp, yol tarifi, saat ve topluluk grubu data/site.json'dan birebir alınır;
alan yoksa düğmesi çıkmaz. ?p=<post-id> koleksiyonu yok: story'ler bu sayfaya yönlenmez.
Her ürün bağlantısı UTM taşır (utm_medium=bio).

  python3 scripts/bio.py
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta
from pathlib import Path

import common
import content as C
from common import DATA, DOCS, ROOT, THUMBS, fmt_price, item_dt

OUT = DOCS / "index.html"
RECENT = 24
RECENT_DAYS = 14  # "son 14 gün" penceresi


def _terms() -> dict[str, str]:
    """data/arama.json: ürün slug'ı -> sitede doğrulanmış arama terimi (postlarda yazan terim)."""
    return {k: v.get("q") or "" for k, v in common.read_json(DATA / "arama.json", {}).items() if isinstance(v, dict)}


def _catalog() -> list[dict]:
    # "c" (N-kodu) yalnız eski ?k= bağlantıları için veride durur; sayfada gösterilmez
    codes, terms = common.load_codes(), _terms()
    out = []
    for p in common.load_products():
        if not p.get("price") or p.get("in_stock") is not True or C.excluded(p):
            continue
        code = codes.get(p["slug"], "")
        out.append({"s": p["slug"], "c": code, "n": C.display_name(p), "p": fmt_price(p["price"]),
                    "k": p.get("category") or "", "a": terms.get(p["slug"], ""),
                    "u": C.utm(p["url"], "bio", "arama", code or p["slug"]), "i": (p.get("images") or [""])[0]})
    return sorted(out, key=lambda x: (x["c"] or "~", x["n"]))


def _recent(cal: list[dict], now: datetime) -> list[dict]:
    """Son 14 günde yayınlanmış POST'ların ürünleri, en yenisi üstte, ürün başına tek satır.
    Story kayıtları alınmaz. Bağlantı postun bio_link'i (utm_content=<post-id>). Kart görseli: tek ürünlü postta
    post kapağı (docs/media/t/<id>.jpg varsa, göreli yol), yoksa ya da çok ürünlü postta ürün görseli.
    Stok ve fiyat bugünkü data/products.json'dan: stokta/fiyatlı değilse (ya da hariçse) satır çıkmaz; fiyat güncel
    fiyattır. Kapak yalnız arama terimi döneminde çizildiyse ("q" var; eski kapaklarda "KOD N…" yazar) ve kapaktaki
    fiyat güncel fiyatla aynıysa kullanılır."""
    terms, since = _terms(), now - timedelta(days=RECENT_DAYS)
    cur = {p["slug"]: p for p in common.load_products()}
    seen, rows = set(), []
    for c in sorted(cal, key=item_dt, reverse=True):
        if c.get("type") != "post" or c.get("status") != "published" or not since <= item_dt(c) <= now:
            continue
        prods = c.get("products") or []
        cover = (len(prods) == 1 and prods[0].get("q") and (THUMBS / f"{c['id']}.jpg").exists())
        for x in prods:
            if x["slug"] in seen:
                continue
            p = cur.get(x["slug"])
            if not p or not p.get("price") or p.get("in_stock") is not True or C.excluded(p):
                continue
            seen.add(x["slug"])
            price = fmt_price(p["price"])
            thumb = f"media/t/{c['id']}.jpg" if cover and price == fmt_price(x.get("price")) else ""
            rows.append({"s": x["slug"], "c": x.get("code") or "", "n": x["name"], "p": price,
                         "k": x.get("category") or "", "a": terms.get(x["slug"], ""),
                         "u": x.get("bio_link") or x["link"], "i": thumb or x.get("image") or ""})
    return rows[:RECENT]


def _contact(site: dict) -> str:
    """Ara / WhatsApp / Yol tarifi / saat / Topluluk sürüşleri: site.json'da olan alanlardan birebir; olmayan çıkmaz."""
    extra = site.get("_extra") or {}
    social = site.get("social") or {}
    e = lambda s: html.escape(s, quote=True)
    out = []
    phone, e164 = site.get("phone") or "", site.get("phone_e164") or extra.get("phone_e164") or ""
    tel = e164 or "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if tel:
        out.append(f'<a class="btn alt" href="tel:{e(tel)}">Ara{" · " + e(phone) if phone else ""}</a>')
    # whatsapp_url olduğu gibi kullanılır (ön doldurulmuş metni wa.me ?text= ile zaten site.json'da)
    wa = site.get("whatsapp_url") or social.get("whatsapp") or ""
    if wa:
        out.append(f'<a class="btn alt" href="{e(wa)}">WhatsApp\'tan yaz</a>')
    if site.get("maps_url"):
        out.append(f'<a class="btn alt" href="{e(site["maps_url"])}">Yol tarifi</a>')
    info = [x for x in (site.get("hours") and "Çalışma saatleri: " + site["hours"], site.get("address")) if x]
    if info:
        out.append('<p class="info">' + "<br>".join(e(x) for x in info) + "</p>")
    community = extra.get("community") or {}
    group = social.get("whatsapp_group") or community.get("whatsapp_group") or ""
    if group:
        out.append('<h2>Topluluk sürüşleri</h2>'
                   + (f'<p class="info">{e(community["text"])}</p>' if community.get("text") else "")
                   + f'<a class="btn" href="{e(group)}">Topluluk sürüşleri · WhatsApp grubu</a>')
    return "\n".join(out)


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
.info{font-size:15px;color:#3d3a31;text-align:center;margin:6px 6px 14px;line-height:1.45}
.foot{text-align:center;font-size:13px;margin:28px 0 10px}.foot a{color:#6b6658}
</style></head><body>
<header><img src="logo.png" alt="NITRO Bisiklet"><p>Köyceğiz · Bisiklet satış ve servis</p></header>
<main>
<form class="s" onsubmit="go(event)"><input id="q" type="search" placeholder="Ürün adı ya da kategori: kask, pedal…" autocomplete="off" aria-label="Ürün ara"><button>Ara</button></form>
<p class="hint">Ürün adını ya da kategorisini yaz, ürün sayfasına git.</p>
<div id="res"></div>
<a class="btn" href="__STORE__">Tüm ürünler · Mağaza</a>
<a class="btn alt" href="__SERVICE__">Servis randevusu al</a>
__CONTACT__
<div id="recent"></div>
<p class="foot"><a href="gizlilik.html">Gizlilik</a> · <a href="veri-silme.html">Veri silme</a></p>
</main>
<script>
var ALL=__ALL__,RECENT=__RECENT__;
function low(s){return (s||'').toLocaleLowerCase('tr').trim()}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function card(x){return '<a class="card" href="'+esc(x.u)+'">'+(x.i?'<img src="'+esc(x.i)+'" loading="lazy" alt="">':'')+
 '<div><b>'+esc(x.n)+'</b><span>'+esc(x.p)+'</span><i>ÜRÜNE GİT</i></div></a>'}
function merge(a,b){var s={};a.forEach(function(x){s[x.s]=1});return a.concat(b.filter(function(x){return !s[x.s]}))}
function byCode(c){c=low(c).replace(/\\s+/g,'');var m=function(x){return x.c&&low(x.c)===c};
 return merge(RECENT.filter(m),ALL.filter(m))}
function find(q){q=low(q);if(!q)return null;var parts=q.split(/\\s+/);
 var m=function(x){var t=low(x.n+' '+x.k+' '+x.a);return parts.every(function(p){return t.indexOf(p)>=0})};
 return merge(RECENT.filter(m),ALL.filter(m)).slice(0,40)}
function show(q,code){var r=code?byCode(code):find(q),el=document.getElementById('res');if(r===null){el.innerHTML='';return}
 el.innerHTML='<h2>'+(code?'Aradığın ürün':'Arama: '+esc(q))+'</h2>'+(r.length?r.map(card).join(''):'<div class="none">Bu adla ürün bulunamadı. Başka bir kelime dene ya da mağazaya göz at.</div>')}
function go(e){e.preventDefault();var q=document.getElementById('q').value;show(q);
 try{history.replaceState(null,'','?q='+encodeURIComponent(q))}catch(_){}}
(function(){var p=new URLSearchParams(location.search),k=p.get('k')||'',q=p.get('q')||'';
 if(k)show('',k);else if(q){document.getElementById('q').value=q;show(q)}
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
            .replace("__CONTACT__", _contact(site))
            .replace("__ALL__", dump(_catalog())).replace("__RECENT__", dump(_recent(cal, now))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    logo = ROOT / "assets" / "logo.png"
    if logo.exists() and out.parent == DOCS and not (DOCS / "logo.png").exists():
        (DOCS / "logo.png").write_bytes(logo.read_bytes())
    return out


if __name__ == "__main__":
    print(build_bio(common.load_calendar()))
