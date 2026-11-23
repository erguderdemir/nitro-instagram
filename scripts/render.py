#!/usr/bin/env python3
"""Ürün verisinden Instagram post (1080x1350) ve story (1080x1920) görseli üretir.

HTML şablonu oluşturur, headless Chrome ile PNG ekran görüntüsü alır, Pillow ile JPEG'e çevirir.
Kullanım (tek ürün denemesi):  python3 scripts/render.py <ürün-slug> [post|story]
"""
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "img"
LOGO = ROOT / "assets" / "logo.png"

SIZES = {"post": (1080, 1350), "story": (1080, 1920)}

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    sys.exit("Chrome bulunamadı. CHROME_BIN ortam değişkeniyle yolunu ver.")


def cached_image(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    ext = Path(url).suffix or ".jpg"
    p = CACHE / (hashlib.md5(url.encode()).hexdigest()[:12] + ext)
    if not p.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            p.write_bytes(urllib.request.urlopen(req, timeout=30).read())
        except Exception:  # noqa: BLE001  (python.org kurulumunda sertifika sorunu)
            subprocess.run(["curl", "-sSfL", "-m", "30", url, "-o", str(p)], check=True)
    return normalized(p)


def normalized(src: Path) -> Path:
    """Şeffaflığı beyaza düzle, beyaz kenar boşluklarını kırp (ürün kadrajı doldursun)."""
    dst = src.with_name(src.stem + "_n.png")
    if dst.exists():
        return dst
    im = Image.open(src)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    mask = im.convert("L").point(lambda v: 255 if v < 240 else 0)
    box = mask.getbbox()
    if box:
        pad = int(0.03 * max(im.size))
        box = (max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height))
        im = im.crop(box)
    im.save(dst)
    return dst


def fmt_price(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:,.0f}".replace(",", ".") + " ₺"


KEY_SPECS = ["Jant Ölçüsü", "Vites", "Fren Tipi", "Kadro Malzemesi", "Kadro Boyu", "Maşa",
             "Ölçü", "Malzeme", "Uyumluluk", "Renk", "Beden"]


def spec_chips(p: dict, n: int = 3) -> list[str]:
    out = []
    for k in KEY_SPECS:
        v = p["specs"].get(k)
        if v and len(v) <= 28:
            out.append(v if k not in ("Kadro Boyu",) else f"{v} kadro")
        if len(out) == n:
            break
    return out


def badge(p: dict) -> str:
    if p.get("condition", "").lower().startswith("kontrollü"):
        return "KONTROLLÜ<br>2. EL"
    if p.get("stock_left") and p["stock_left"] <= 3:
        return f"SON<br>{p['stock_left']} ADET"
    if p.get("old_price"):
        pct = round(100 * (1 - p["price"] / p["old_price"]))
        return f"%{pct}<br>İNDİRİM"
    if (p.get("price") or 0) >= 3000:
        return "ÜCRETSİZ<br>KARGO"
    return ""


FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800;900'
         '&family=Barlow:wght@500;600;700&family=Space+Mono:wght@400;700&display=block" rel="stylesheet">')

BASE_CSS = """
:root{--accent:#f5821f;--accent-ink:#a8480a;--ink:#14150f;--ink2:#6b6658;--cream:#f1ede2;
--olive:#2a3220;--olive2:#3d4a2c;--sage:#a8b78a}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:W;height:H;overflow:hidden}
body{font-family:Barlow,system-ui,sans-serif;color:var(--ink);-webkit-font-smoothing:antialiased}
.mono{font-family:'Space Mono',monospace}
.disp{font-family:Archivo,system-ui,sans-serif}
"""

POST = """<!doctype html><html lang="tr"><head><meta charset="utf-8">{fonts}<style>{css}
body{background:var(--cream);background-image:radial-gradient(#14150f1c 1.6px,transparent 1.6px);
 background-size:28px 28px;position:relative}
.top{display:flex;align-items:center;justify-content:space-between;padding:44px 56px 0}
.top img{height:118px}
.top .loc{font-size:22px;letter-spacing:.14em;text-align:right;line-height:1.5;color:var(--ink2)}
.stage{position:absolute;left:40px;right:40px;top:150px;height:640px;display:flex;align-items:center;justify-content:center}
.stage img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:multiply}
.badge{position:absolute;right:56px;top:178px;width:190px;height:190px;border-radius:50%;
 background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;text-align:center;
 font:900 30px/1.1 Archivo,sans-serif;transform:rotate(-10deg);box-shadow:0 10px 0 var(--accent-ink)}
.info{position:absolute;left:56px;right:56px;top:808px}
.eyebrow{font-size:23px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent-ink);font-weight:700}
h1{font:800 {name_size}px/1.02 Archivo,sans-serif;letter-spacing:-.02em;margin-top:12px;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.row{display:flex;align-items:flex-end;justify-content:space-between;margin-top:26px;gap:24px}
.chips{display:flex;flex-wrap:wrap;gap:10px;max-width:560px}
.chip{border:2px solid var(--ink);border-radius:999px;padding:7px 18px;font-size:24px;font-weight:600}
.price{text-align:right;white-space:nowrap}
.price .old{font-size:28px;color:var(--ink2);text-decoration:line-through}
.price .now{font:700 66px/1 'Space Mono',monospace;color:var(--accent-ink)}
.price .vat{font-size:20px;color:var(--ink2);letter-spacing:.1em}
.bar{position:absolute;left:0;right:0;bottom:0;height:128px;background:var(--ink);color:var(--cream);
 display:flex;align-items:center;justify-content:space-between;padding:0 56px}
.bar .cta{font:800 40px Archivo,sans-serif;letter-spacing:.01em}
.bar .cta b{color:var(--accent)}
.bar .url{font-size:25px;color:var(--sage);text-align:right;line-height:1.35}
</style></head><body>
<div class="top"><img src="{logo}"><div class="loc mono">KÖYCEĞİZ / MUĞLA<br>SATIŞ · SERVİS</div></div>
<div class="stage"><img src="{img}"></div>
{badge_html}
<div class="info">
 <div class="eyebrow">{eyebrow}</div>
 <h1>{name}</h1>
 <div class="row"><div class="chips">{chips}</div>
  <div class="price">{old_html}<div class="now">{price}</div><div class="vat mono">KDV DAHİL</div></div></div>
</div>
<div class="bar"><div class="cta">SİPARİŞ VER <b>→</b></div>
 <div class="url mono">nitrobisiklet.com<br>link profilde</div></div>
</body></html>"""

STORY = """<!doctype html><html lang="tr"><head><meta charset="utf-8">{fonts}<style>{css}
body{background:radial-gradient(120% 70% at 50% 35%,var(--olive2) 0%,var(--olive) 45%,var(--ink) 100%);color:var(--cream)}
.hook{position:absolute;left:70px;right:70px;top:250px}
.hook .k{font-size:26px;letter-spacing:.2em;color:var(--sage);font-weight:700}
.hook h2{font:900 {hook_size}px/1 Archivo,sans-serif;letter-spacing:-.02em;margin-top:14px;text-transform:uppercase}
.hook h2 em{font-style:normal;color:var(--accent)}
.card{position:absolute;left:60px;right:60px;top:560px;height:860px;background:var(--cream);border-radius:44px;
 overflow:hidden;color:var(--ink)}
.card .stage{position:absolute;inset:30px 30px 250px;display:flex;align-items:center;justify-content:center}
.card .stage img{max-width:100%;max-height:100%;object-fit:contain;mix-blend-mode:multiply}
.card .meta{position:absolute;left:44px;right:44px;bottom:38px}
.card .name{font:800 44px/1.08 Archivo,sans-serif;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .pr{display:flex;align-items:baseline;gap:18px;margin-top:16px}
.card .now{font:700 64px/1 'Space Mono',monospace;color:var(--accent-ink)}
.card .old{font-size:30px;color:var(--ink2);text-decoration:line-through}
.badge{position:absolute;right:36px;top:36px;background:var(--accent);color:#fff;border-radius:999px;
 padding:14px 26px;font:900 26px/1.1 Archivo,sans-serif;text-align:center}
.perk{position:absolute;left:70px;right:70px;top:1460px;font-size:30px;font-weight:600;color:var(--sage);text-align:center}
.cta{position:absolute;left:150px;right:150px;top:1540px;height:112px;border-radius:999px;background:var(--accent);
 color:var(--ink);display:flex;align-items:center;justify-content:center;font:900 38px Archivo,sans-serif}
.foot{position:absolute;left:0;right:0;bottom:200px;text-align:center;font-size:24px;letter-spacing:.14em;color:var(--sage)}
.logo{position:absolute;left:70px;top:80px;height:110px}
</style></head><body>
<img class="logo" src="{logo}">
<div class="hook"><div class="k mono">{kicker}</div><h2>{hook}</h2></div>
<div class="card"><div class="stage"><img src="{img}"></div>{badge_html}
 <div class="meta"><div class="name">{name}</div><div class="pr"><div class="now">{price}</div>{old_html}</div></div></div>
<div class="perk">{perk}</div>
<div class="cta">İNCELE · LİNK PROFİLDE ↗</div>
<div class="foot mono">NITROBISIKLET.COM</div>
</body></html>"""


def fill(tpl: str, **kw) -> str:
    """CSS süslü parantezleriyle çakışmayan basit {anahtar} doldurucu."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), tpl)


def build_html(p: dict, kind: str, hook: str = "", kicker: str = "") -> str:
    w, h = SIZES[kind]
    css = BASE_CSS.replace("W", f"{w}px", 1).replace("H", f"{h}px", 1)
    img = cached_image(p["images"][0]).as_uri()
    b = badge(p)
    from content import display_name
    name = html.escape(display_name(p))
    old = fmt_price(p.get("old_price"))
    common = dict(fonts=FONTS, css=css, logo=LOGO.as_uri(), img=img, name=name, price=fmt_price(p["price"]))
    if kind == "post":
        eyebrow = " · ".join(x for x in [p.get("category"), p.get("condition")] if x)
        chips = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in spec_chips(p))
        return fill(POST, **common,
                           name_size=72 if len(name) <= 30 else 60 if len(name) <= 48 else 52,
                           eyebrow=html.escape(eyebrow), chips=chips,
                           badge_html=f'<div class="badge">{b}</div>' if b else "",
                           old_html=f'<div class="old mono">{old}</div>' if old else "")
    perk = ("Köyceğiz içi aynı gün ücretsiz teslim · 3.000 ₺ üzeri ücretsiz kargo"
            if (p.get("price") or 0) >= 3000 else "Köyceğiz içi aynı gün teslim · Türkiye geneli kargo")
    return fill(STORY, **common, hook=hook or "Bugün <em>vitrinde</em>", kicker=html.escape(kicker or "NITRO SEÇKİSİ"),
                        hook_size=96 if len(hook) < 40 else 80,
                        badge_html=f'<div class="badge">{b.replace("<br>", " ")}</div>' if b else "",
                        old_html=f'<div class="old mono">{old}</div>' if old else "", perk=perk)


def render(p: dict, kind: str, out: Path, hook: str = "", kicker: str = "") -> Path:
    w, h = SIZES[kind]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_html = out.with_suffix(".html")
    tmp_png = out.with_suffix(".png")
    tmp_html.write_text(build_html(p, kind, hook, kicker), encoding="utf-8")
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={w},{h}", "--virtual-time-budget=10000",
                    f"--screenshot={tmp_png}", tmp_html.as_uri()],
                   check=True, capture_output=True, timeout=90)
    Image.open(tmp_png).convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    tmp_png.unlink()
    tmp_html.unlink()
    return out


if __name__ == "__main__":
    import json
    products = {p["slug"]: p for p in json.loads((ROOT / "data" / "products.json").read_text())}
    slug, kind = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "post")
    print(render(products[slug], kind, ROOT / "out" / "test" / f"{slug}-{kind}.jpg",
                 hook="Patikaya <em>hazır</em> mısın?", kicker="HAFTANIN BİSİKLETİ"))
