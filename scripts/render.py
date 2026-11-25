#!/usr/bin/env python3
"""Tasarım motoru: Instagram carousel, story ve reel karelerini üretir.

Her kare bir <section class="cv post|story"> parçasıdır. Parçalar tek sayfada alt alta dizilir,
headless Chrome ile bir kez ekran görüntüsü alınır, Pillow ile kırpılıp JPEG'e çevrilir.

Görsellerde emoji ve ok karakteri kullanılmaz (sunucuda o fontlar yok); simgeler satır içi SVG'dir.
Deneme:  python3 scripts/render.py <ürün-slug>   ->  out/deneme/
"""
from __future__ import annotations

import hashlib
import html
import re
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from common import DOCS, IG_USERNAME, ROOT, ssl_context

CACHE = ROOT / "cache" / "img"
LOGO = (ROOT / "assets" / "logo.png").as_uri()
FONTS = (DOCS / "fonts" / "fonts.css").as_uri()
SIZES = {"post": (1080, 1350), "story": (1080, 1920)}
PER_PAGE = {"post": 11, "story": 8}  # tek ekran görüntüsünde en çok kare (16 384 px sınırının altında)
VARIANTS = ("cream", "olive", "ink")

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


# ---- Ürün fotoğrafı hazırlığı ------------------------------------------------------------------

def cached_image(url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    ext = Path(url.split("?")[0]).suffix or ".jpg"
    p = CACHE / (hashlib.md5(url.encode()).hexdigest()[:12] + ext)
    if not p.exists() or p.stat().st_size == 0:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            p.write_bytes(urllib.request.urlopen(req, timeout=30, context=ssl_context()).read())
        except Exception:  # noqa: BLE001
            subprocess.run(["curl", "-sSfL", "-m", "40", url, "-o", str(p)], check=True)
    return p


def prep(url: str) -> dict | None:
    """Fotoğrafı indirir, türünü belirler ve kullanıma hazırlar.

    Tür: 'white' (beyaz fon: kenar boşluğu kırpılır), 'flat' (düz renkli fon), 'photo' (ortam fotoğrafı).
    Dönen sözlük: path, kind, bg (#rrggbb), w, h. İndirilemeyen ya da bozuk görselde None.
    """
    try:
        src = cached_image(url)
        meta = src.with_name(src.stem + "_p.json")
        dst = src.with_name(src.stem + "_p.png")
        if meta.exists() and dst.exists():
            info = json.loads(meta.read_text())
            info["path"] = dst
            return info
        im = Image.open(src)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im)
        im = im.convert("RGB")
        w, h = im.size
        t = max(2, int(min(w, h) * 0.02))
        strips = [im.crop(b) for b in ((0, 0, w, t), (0, h - t, w, h), (0, 0, t, h), (w - t, 0, w, h))]
        stats = [ImageStat.Stat(s) for s in strips]
        mean = [sum(s.mean[i] for s in stats) / 4 for i in range(3)]
        spread = max(max(s.stddev) for s in stats) + max(abs(s.mean[i] - mean[i]) for s in stats for i in range(3))
        hists = [ImageChops.darker(ImageChops.darker(*s.split()[:2]), s.split()[2]).histogram() for s in strips]
        white = sum(sum(hh[232:]) for hh in hists) / max(1, sum(sum(hh) for hh in hists))
        if white >= 0.62 or (min(mean) >= 232 and spread < 22):
            kind = "white"
            box = im.convert("L").point(lambda v: 255 if v < 238 else 0).getbbox()
            if box:
                pad = int(0.02 * max(im.size))
                im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                              min(box[2] + pad, w), min(box[3] + pad, h)))
        elif spread < 14:
            kind = "flat"
        else:
            kind = "photo"
        if max(im.size) > 1500:
            im.thumbnail((1500, 1500), Image.LANCZOS)
        im.save(dst)
        info = {"kind": kind, "bg": "#%02x%02x%02x" % tuple(int(round(c)) for c in mean), "w": im.width, "h": im.height}
        meta.write_text(json.dumps(info))
        info["path"] = dst
        return info
    except Exception:  # noqa: BLE001
        return None


def image_ok(info: dict | None) -> bool:
    """Tasarımda bulanık ya da garip duracak görselleri eler."""
    if not info:
        return False
    w, h = info["w"], info["h"]
    return max(w, h) >= 460 and min(w, h) >= 190 and 0.36 <= w / h <= 2.8


# ---- HTML yardımcıları -------------------------------------------------------------------------

def E(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def hl(s: str) -> str:
    """Başlık: yalnızca <em> vurgusuna izin verir."""
    s = E(s).replace("&lt;em&gt;", "<em>").replace("&lt;/em&gt;", "</em>")
    return re.sub(r"(?<![\d.,])(\d{1,3}) (?=[^\s<])", "\\1&nbsp;", s)   # sayı, ait olduğu sözcükten kopmasın


ICONS = {
    "tool": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "truck": '<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
    "return": '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    "pin": '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    "bookmark": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "cart": '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "chat": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "down": '<polyline points="6 9 12 15 18 9"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "gift": '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
}
ARROW = ('<svg width="52" height="22" viewBox="0 0 52 22" fill="none" stroke="currentColor" stroke-width="3.4" '
         'stroke-linecap="round" stroke-linejoin="round"><path d="M2 11h46M39 2l9 9-9 9"/></svg>')


def ico(name: str, size: int = 40, sw: float = 2) -> str:
    return (f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


def contour(seed: str, cx: int, cy: int, r: int = 560, n: int = 8, op: float = 0.1) -> str:
    """Marka motifi: eş yükselti eğrileri (Ölemez Dağı etekleri)."""
    rng = random.Random(seed)
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    am = [rng.uniform(0.07, 0.15), rng.uniform(0.04, 0.1), rng.uniform(0.02, 0.06)]
    paths = []
    for i in range(n):
        rr = r * (1 - i / (n + 0.6))
        pts = []
        for j in range(72):
            a = 2 * math.pi * j / 72
            rad = rr * (1 + am[0] * math.sin(2 * a + ph[0] + i * 0.25) + am[1] * math.sin(3 * a + ph[1] - i * 0.2)
                        + am[2] * math.sin(5 * a + ph[2]))
            pts.append(f"{rad * math.cos(a):.0f},{rad * math.sin(a):.0f}")
        paths.append(f'<polygon points="{" ".join(pts)}"/>')
    d = int(r * 2.5)
    return (f'<svg class="ct" style="left:{cx - d // 2}px;top:{cy - d // 2}px" width="{d}" height="{d}" '
            f'viewBox="{-d // 2} {-d // 2} {d} {d}"><g fill="none" stroke="currentColor" stroke-width="2.4" '
            f'stroke-linejoin="round" opacity="{op}">{"".join(paths)}</g></svg>')


def sbg(seed: str) -> str:
    """Story zemini: üstte ve alttaki güvenli alan dışında birer eş yükselti motifi."""
    return contour(seed, 980, 430, 620, op=0.11) + contour(seed + "b", 130, 1800, 620, op=0.11)


def stage(info: dict, ar: float, style: str = "", cls: str = "") -> str:
    """Ürün fotoğrafı kartı. ar: kartın en/boy oranı (ortam fotoğrafını kırpma kararında kullanılır)."""
    src = info["path"].as_uri()
    if info["kind"] == "photo":
        rel = (info["w"] / info["h"]) / ar
        if 0.8 <= rel <= 1.25:
            return f'<div class="stage k-cover {cls}" style="{style}"><img src="{src}" alt=""></div>'
        return (f'<div class="stage k-photo {cls}" style="{style}"><div class="bg" style="background-image:url({src})">'
                f'</div><img src="{src}" alt=""></div>')
    bg = "#fff" if info["kind"] == "white" else info["bg"]
    return f'<div class="stage k-{info["kind"]} {cls}" style="background:{bg};{style}"><img src="{src}" alt=""></div>'


def top(right: str = "") -> str:
    return f'<div class="top"><img class="logo" src="{LOGO}" alt="">{right}</div>'


def chip(t: str, fill: bool = False) -> str:
    return f'<span class="chip mono{" fill" if fill else ""}">{E(t)}</span>'


def cnt(i: int, n: int) -> str:
    return f'<span class="cnt mono">{i:02d}<i>/{n:02d}</i></span>'


def bot(right: str = "", left: str | None = None) -> str:
    return f'<div class="bot mono"><span>{E(left or "@" + IG_USERNAME)}</span><span class="r">{right}</span></div>'


SWIPE = f"KAYDIR {ARROW}"
SITE_TXT = "nitrobisiklet.com"

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;background:#777;font-family:Barlow,sans-serif;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
.cv{position:relative;width:1080px;overflow:hidden;background:var(--bg);color:var(--fg)}
.post{height:1350px}.story{height:1920px}
.v-cream{--bg:#f1ede2;--fg:#14150f;--mut:#6b6658;--acc:#f5821f;--accfg:#14150f;--em:#dd6410;--soft:#e3dccb;--line:rgba(20,21,15,.16)}
.v-olive{--bg:#2a3220;--fg:#f1ede2;--mut:#a8b78a;--acc:#f5821f;--accfg:#14150f;--em:#f5821f;--soft:#3d4a2c;--line:rgba(241,237,226,.2)}
.v-ink{--bg:#14150f;--fg:#f1ede2;--mut:#a8b78a;--acc:#f5821f;--accfg:#14150f;--em:#f5821f;--soft:#24271c;--line:rgba(241,237,226,.18)}
.v-orange{--bg:#f5821f;--fg:#14150f;--mut:#4d2505;--acc:#14150f;--accfg:#f1ede2;--em:#f1ede2;--soft:#e2700f;--line:rgba(20,21,15,.24)}
.ct{position:absolute;color:var(--fg);pointer-events:none}
.pad{position:absolute;inset:0;padding:54px 64px 50px;display:flex;flex-direction:column}
.story .pad{padding:262px 64px 326px}
.reel .pad{padding:262px 64px 0;height:1262px;inset:0 0 auto 0}
.h{font-family:Archivo,sans-serif;font-weight:800;font-stretch:72%;text-transform:uppercase;line-height:1.08}
.mono{font-family:'Space Mono',monospace;font-weight:700;text-transform:uppercase;letter-spacing:.13em}
em{font-style:normal;color:var(--em)}
.top{display:flex;justify-content:space-between;align-items:center;height:104px;flex:none}
.logo{height:104px;width:auto;flex:none}
.story .top,.story .logo{height:118px}
.v-orange .logo{background:#14150f;border-radius:26px;padding:8px 14px}
.chip{font-size:21px;padding:12px 22px;border:2.5px solid var(--fg);border-radius:999px;white-space:nowrap;max-width:560px;overflow:hidden;text-overflow:ellipsis}
.chip.fill{background:var(--fg);color:var(--bg)}
.story .chip{font-size:24px;padding:14px 26px}
.cnt{font-size:30px;letter-spacing:.06em}.cnt i{font-style:normal;color:var(--mut);font-size:22px}
.kick{font-size:24px;color:var(--em);margin-top:26px;flex:none;display:flex;align-items:center;gap:14px;white-space:nowrap;overflow:hidden}
.kick:before{content:"";width:44px;height:5px;background:var(--em);flex:none}
.story .kick{font-size:28px;margin-top:34px}
.hl{overflow:hidden;flex:none;margin-top:12px;box-sizing:content-box;padding-bottom:.34em;margin-bottom:-.34em;text-wrap:balance}
.stage{position:relative;border-radius:40px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:0;flex:none}
.stage img{position:relative;width:100%;height:100%;object-fit:contain}
.k-white{padding:34px}.k-flat{padding:26px}
.k-cover img{object-fit:cover}
.k-photo{padding:24px;background:#14150f}
.k-photo .bg{position:absolute;inset:-70px;background-size:cover;background-position:center;filter:blur(38px) brightness(.8)}
.k-photo img{width:auto;height:auto;max-width:100%;max-height:100%;border-radius:22px}
.meta{display:flex;justify-content:space-between;align-items:flex-end;gap:26px;margin-top:24px;flex:none}
.pname{font-weight:600;font-size:36px;line-height:1.13;max-height:84px;overflow:hidden}
.code{font-size:21px;color:var(--mut);margin-top:10px;white-space:nowrap;overflow:hidden}
.price{font-size:62px;background:var(--acc);color:var(--accfg);padding:17px 28px 12px;border-radius:24px;white-space:nowrap;flex:none}
.price.sm{font-size:44px;padding:13px 22px 9px;border-radius:20px}
.bot{display:flex;justify-content:space-between;align-items:center;font-size:20px;color:var(--mut);margin-top:22px;flex:none;height:26px}
.bot .r{display:flex;align-items:center;gap:14px;color:var(--fg)}
h2.h{font-size:92px;margin-top:10px;flex:none}
.rows{flex:1;margin-top:22px;display:flex;flex-direction:column;justify-content:center;min-height:0}
.row{display:flex;justify-content:space-between;align-items:center;gap:28px;padding:17px 0;border-bottom:2px solid var(--line)}
.row:first-child{border-top:2px solid var(--line)}
.row b{font:700 20px 'Space Mono',monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);flex:none;max-width:380px}
.row span{font-weight:600;font-size:33px;text-align:right;line-height:1.12}
.strip{display:flex;align-items:center;gap:22px;margin-top:22px;flex:none;background:var(--soft);border-radius:30px;padding:16px 20px 16px 16px}
.strip .stage{width:124px;height:124px;border-radius:22px;padding:10px}
.strip .tx{flex:1;min-width:0}.strip .pname{font-size:29px;max-height:66px}.strip .code{margin-top:6px;font-size:19px}
.txt{flex:1;min-height:0;overflow:hidden;font-size:44px;line-height:1.3;font-weight:500;margin-top:30px}
.why{flex:1;display:flex;flex-direction:column;justify-content:center;gap:26px;margin-top:10px}
.wy{display:flex;align-items:center;gap:28px}
.wy .ic{width:104px;height:104px;border-radius:30px;background:var(--acc);color:var(--accfg);display:flex;align-items:center;justify-content:center;flex:none}
.wy b{font-family:Archivo,sans-serif;font-weight:800;font-stretch:72%;text-transform:uppercase;font-size:50px;line-height:1.04;display:block}
.wy span{display:block;font-size:28px;color:var(--mut);margin-top:6px;font-weight:500;line-height:1.2}
.steps{flex:1;display:flex;flex-direction:column;justify-content:center;gap:20px;margin-top:8px}
.st{display:flex;align-items:center;gap:26px;background:var(--soft);border-radius:30px;padding:22px 28px}
.st i{font-family:Archivo,sans-serif;font-style:normal;font-weight:800;font-stretch:72%;font-size:84px;line-height:.9;width:64px;flex:none;color:var(--em)}
.st b{font-weight:700;font-size:38px;line-height:1.14}
.tile{display:flex;align-items:center;justify-content:space-between;gap:20px;background:var(--acc);color:var(--accfg);border-radius:30px;padding:22px 32px;margin-top:20px;flex:none}
.tile small{font:700 22px 'Space Mono',monospace;letter-spacing:.13em;text-transform:uppercase;display:block;line-height:1.35}
.tile b{font-family:Archivo,sans-serif;font-weight:800;font-stretch:72%;font-size:82px;line-height:.95;white-space:nowrap}
.acts{display:flex;gap:16px;margin-top:20px;flex:none}
.act{flex:1;display:flex;align-items:center;gap:14px;border:2.5px solid var(--fg);border-radius:24px;padding:16px 20px;font-size:25px;font-weight:600;line-height:1.15}
.trio{display:flex;gap:18px;flex:1;min-height:0;margin-top:26px}
.trio .stage{flex:1;height:100%;border-radius:30px;padding:18px}
.sub{font-size:33px;line-height:1.25;font-weight:500;margin-top:22px;flex:none;color:var(--fg)}
.lrow{display:flex;align-items:center;gap:26px;margin-top:20px;flex:none}
.num{font-size:190px;line-height:.8;color:var(--em);flex:none}
.ltx{min-width:0;flex:1}.ltx .kick{margin-top:0}
.ltx .pname{font-size:42px;max-height:96px;margin-top:10px;font-weight:700}
.big{font-size:150px}
.tnum{font-size:300px;line-height:.78;color:var(--em);flex:none;margin-top:34px}
.th{font-size:86px;margin-top:22px;flex:none;max-height:250px;overflow:hidden;box-sizing:content-box;padding-bottom:.34em;margin-bottom:-.34em;text-wrap:balance}
.tt{font-size:45px;line-height:1.3;font-weight:500;margin-top:28px;flex:1;min-height:0;overflow:hidden}
.dots{display:flex;gap:10px;flex:none;margin-top:18px}
.dots i{height:8px;flex:1;border-radius:9px;background:var(--line)}.dots i.on{background:var(--em)}
.badge{display:inline-flex;align-items:center;gap:14px;background:var(--acc);color:var(--accfg);border-radius:999px;padding:16px 30px;font-size:26px;align-self:flex-start;margin-top:26px;flex:none}
.dock{flex:none;height:214px;margin-top:20px;display:flex;flex-direction:column;align-items:center}
.dk-l{font-size:24px;color:var(--fg);display:flex;align-items:center;gap:12px;height:40px}
.dk-s{width:620px;height:128px;margin-top:14px;border:3px dashed var(--line);border-radius:34px}
.pill{display:inline-flex;align-items:center;gap:16px;background:var(--fg);color:var(--bg);font-size:27px;padding:30px 44px;border-radius:999px;margin-top:30px;letter-spacing:.1em}
.pill u{text-decoration:none;color:var(--acc)}
.mock{align-self:center;width:560px;height:700px;border-radius:34px;overflow:hidden;transform:rotate(-3deg);box-shadow:0 30px 70px rgba(0,0,0,.38);border:10px solid #fff;flex:none;margin-top:44px;background:#fff}
.mock img{width:100%;height:100%;object-fit:cover;display:block}
.s-sub{font-size:36px;line-height:1.25;font-weight:500;text-align:center;margin-top:44px;flex:1}
.q{flex:1;display:flex;flex-direction:column;justify-content:center}
.q .h{font-size:132px;line-height:1.14;overflow:hidden;max-height:760px;box-sizing:content-box;padding-bottom:.34em;margin-bottom:-.34em;text-wrap:balance}
.q p{font-size:40px;line-height:1.3;font-weight:500;margin-top:34px}
.tr{display:flex;align-items:center;gap:24px;background:var(--soft);border-radius:32px;padding:16px 26px 16px 16px}
.tr .stage{width:168px;height:168px;border-radius:24px;padding:12px}
.tr .tx{flex:1;min-width:0}.tr .pname{font-size:33px;max-height:76px}.tr .code{font-size:20px;margin-top:8px}
.trs{flex:1;display:flex;flex-direction:column;justify-content:center;gap:18px;margin-top:20px;min-height:0}
.facts{flex:1;display:flex;flex-direction:column;justify-content:center;gap:24px;margin-top:10px}
.rbox{flex:1;min-height:0;display:flex;flex-direction:column}
.rfoot{position:absolute;left:64px;right:64px;top:1290px;display:flex;justify-content:space-between;font-size:22px;color:var(--mut)}
.rsp{background:var(--soft);border-radius:34px;padding:26px 34px;flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0}
.rsp small{font:700 24px 'Space Mono',monospace;letter-spacing:.13em;text-transform:uppercase;color:var(--mut)}
.rsp b{font-family:Archivo,sans-serif;font-weight:800;font-stretch:72%;text-transform:none;font-size:84px;line-height:.98;margin-top:8px;max-height:168px;overflow:hidden;display:block}
.rprice{font-size:230px;color:var(--em);line-height:.86;margin-top:8px;white-space:nowrap;flex:none}
.ny{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:flex-start}
.ny .yr{font-size:420px;line-height:.8;color:var(--em);letter-spacing:-.02em}
.stage{min-width:0}
.bot,.rfoot{text-transform:none;letter-spacing:.06em}
.why{gap:20px;margin-top:14px}
.wy{background:var(--soft);border-radius:32px;padding:26px 30px}
.wy .ic{width:108px;height:108px;border-radius:28px}
.wy b{font-size:58px}
.wy span{font-size:30px}
.st{padding:28px 30px}.st b{font-size:44px}
.act{font-size:27px}
.row{padding:20px 0}.row b{font-size:21px}.row span{font-size:38px}
.txt{font-size:58px;line-height:1.28}
.th{font-size:100px;max-height:300px}
.tt{font-size:54px}
.q p{font-size:54px}
.dk-l{font-size:28px}
.tr .stage{width:200px;height:200px}.tr .pname{font-size:38px;max-height:88px}.tr .code{font-size:22px}
.mockw{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;margin-top:30px}
.mock{height:94%;width:auto;aspect-ratio:4/5;margin-top:0;align-self:auto}
.reel .pad{padding:310px 64px 0;height:1280px}
.rfoot{top:1312px}
"""

FIT_JS = """
document.fonts.ready.then(function(){
  document.querySelectorAll('[data-fit]').forEach(function(el){
    var fs=parseFloat(getComputedStyle(el).fontSize),min=+el.dataset.fit||20;
    while((el.scrollHeight>el.clientHeight+Math.max(2,fs*0.22)||el.scrollWidth>el.clientWidth+1)&&fs>min){fs-=2;el.style.fontSize=fs+'px';}
    // data-tam: metin asla kesilmez (arama terimi eksik görünürse yanlış aranır); en küçük boyda da sığmazsa satır kaydır
    if(el.dataset.tam&&el.scrollWidth>el.clientWidth+1){el.style.whiteSpace='normal';el.style.overflowWrap='anywhere';el.style.overflow='visible';el.style.lineHeight='1.15';}
  });
});
"""


def page(sections: list[str]) -> str:
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><link rel="stylesheet" href="{FONTS}">'
            f'<style>{CSS}</style></head><body>{"".join(sections)}<script>{FIT_JS}</script></body></html>')


# ---- Carousel kareleri (1080x1350) -------------------------------------------------------------
# v (ürün görünümü): name, price (yazı), code (iç kimlik: desen tohumu), q (nitrobisiklet.com arama terimi), cat, img,
# imgs (ek fotoğraflar)


def _ara(v: dict, style: str = "") -> str:
    """Kartta sitede aranacak terim (scripts/arama.py doğrular). Terim aranacağı gibi (büyük harfe çevrilmeden) yazılır.
    Sığmazsa yazı küçülür, yine sığmazsa satır kayar; kesilmez."""
    st = f' style="{style}"' if style else ""
    return f'<div class="code mono" data-fit="13" data-tam="1"{st}>ARA: <span style="text-transform:none;letter-spacing:.04em">“{E(v["q"])}”</span></div>'


def _meta(v: dict, small: bool = False, ara: bool = True) -> str:
    """ara=False: story'lerde ARA satırı yok (story'de yalnız tıklanabilir ÜRÜNE GİT çıkartması yönlendirir)."""
    return (f'<div class="meta"><div style="min-width:0"><div class="pname" data-fit="24">{E(v["name"])}</div>'
            + (_ara(v) if ara else "") + '</div>'
            f'<div class="price h{" sm" if small else ""}">{E(v["price"])}</div></div>')


def _strip(v: dict) -> str:
    return (f'<div class="strip">{stage(v["img"], 1)}<div class="tx"><div class="pname" data-fit="20">{E(v["name"])}</div>'
            + _ara(v) + f'</div><div class="price h sm">{E(v["price"])}</div></div>')


def p_cover(v: dict, kicker: str, headline: str, variant: str = "cream", ara: bool = True) -> str:
    """ara=False: tanıtım story'sinin içine gömülen kapak kopyası (story'de ARA yazmaz)."""
    return f'''<section class="cv post v-{variant}">{contour(v["code"], 1010, 210)}
<div class="pad">{top(chip(v["cat"]))}<div class="kick mono">{E(kicker)}</div>
<h1 class="h hl" data-fit="58" style="font-size:108px;max-height:204px">{hl(headline)}</h1>
{stage(v["img"], 952 / 590, "flex:1;margin-top:24px")}{_meta(v, ara=ara)}{bot(SWIPE)}</div></section>'''


def p_gallery(v: dict, info: dict, i: int, n: int, variant: str = "cream") -> str:
    return f'''<section class="cv post v-{variant}"><div class="pad">{top(cnt(i, n))}
{stage(info, 952 / 960, "flex:1;margin-top:22px")}{_meta(v, True)}{bot(SWIPE)}</div></section>'''


def p_specs(v: dict, rows: list[tuple[str, str]], i: int, n: int, variant: str = "ink") -> str:
    body = "".join(f'<div class="row"><b>{E(k)}</b><span>{E(val)}</span></div>' for k, val in rows)
    return f'''<section class="cv post v-{variant}">{contour(v["code"] + "s", 60, 1240, 460)}
<div class="pad">{top(cnt(i, n))}<h2 class="h">Teknik <em>özellikler</em></h2>
<div class="rows">{body}</div>{_strip(v)}{bot(SWIPE)}</div></section>'''


def p_detail(v: dict, text: str, i: int, n: int, variant: str = "ink") -> str:
    return f'''<section class="cv post v-{variant}">{contour(v["code"] + "d", 60, 1240, 460)}
<div class="pad">{top(cnt(i, n))}<h2 class="h">Ürün <em>detayı</em></h2>
<div class="txt" data-fit="30">{E(text)}</div>{_strip(v)}{bot(SWIPE)}</div></section>'''


def p_why(facts: list[tuple[str, str, str]], i: int, n: int, variant: str = "olive") -> str:
    """facts: (simge, başlık, alt satır)."""
    body = "".join(f'<div class="wy"><div class="ic">{ico(ic, 52)}</div><div><b>{E(t)}</b>'
                   f'{f"<span>{E(s)}</span>" if s else ""}</div></div>' for ic, t, s in facts)
    return f'''<section class="cv post v-{variant}">{contour("why" + str(i), 1000, 1200, 480)}
<div class="pad">{top(cnt(i, n))}<h2 class="h">Neden <em>NITRO?</em></h2>
<div class="why">{body}</div>{bot(SWIPE, SITE_TXT)}</div></section>'''


def p_cta(mode: str, i: int, n: int, q: str = "", phone: str = "", variant: str = "orange") -> str:
    if mode == "servis":
        title = "Servis <em>randevusu</em>"
        steps = ["Profildeki linke dokun", "“Servis randevusu al” düğmesine bas", "Bisikletini atölyeye getir"]
        tile = f'<div><small>Telefonla da olur</small></div><b style="font-size:66px">{E(phone)}</b>'
    elif mode == "ipucu":
        title = "İhtiyacın <em>profildeki linkte</em>"
        steps = ["Profildeki linke dokun", "Parça ya da aksesuarı adıyla ara", "Ürün sayfasından sepete ekle"]
        tile = f'<div><small>Tüm ürünler</small></div><b style="font-size:66px">{SITE_TXT}</b>'
    elif mode == "cocuk":
        title = "Çocuk bisikletleri <em>profildeki linkte</em>"
        steps = ["Profildeki linke dokun", "Çocuk bisikletleri bölümüne gir", "Jant boyunu seç, sepete ekle"]
        tile = f'<div><small>Tüm ürünler</small></div><b style="font-size:66px">{SITE_TXT}</b>'
    elif mode == "magaza":
        title = "Hepsi <em>profildeki linkte</em>"
        steps = ["Profildeki nitrobisiklet.com linkine dokun", "Karttaki “ARA” terimini aramaya yaz",
                 "Ürün sayfasından sepete ekle"]
        tile = f'<div><small>Tüm ürünler</small></div><b style="font-size:66px">{SITE_TXT}</b>'
    else:
        title = "Nasıl <em>alırım?</em>"
        steps = ["Profildeki nitrobisiklet.com linkine dokun", "Arama simgesine dokun, alttakini yaz",
                 "Ürün sayfasından sepete ekle"]
        tile = (f'<div style="flex:none"><small>Aramaya<br>yaz</small></div>'
                f'<b data-fit="30" data-tam="1" style="flex:1;min-width:0;text-align:right;overflow:hidden">“{E(q)}”</b>')
    body = "".join(f'<div class="st"><i>{k}</i><b>{E(s)}</b></div>' for k, s in enumerate(steps, 1))
    return f'''<section class="cv post v-{variant}">{contour("cta" + mode, 1010, 150, 520, op=0.14)}
<div class="pad">{top(cnt(i, n))}<h2 class="h">{title}</h2><div class="steps">{body}</div>
<div class="tile">{tile}</div>
<div class="acts"><div class="act">{ico("bookmark", 38)}<span>Sonra bakmak için kaydet</span></div>
<div class="act">{ico("send", 38)}<span>Bisikletçi arkadaşına gönder</span></div></div>
{bot("", "@" + IG_USERNAME)}</div></section>'''


def l_cover(kicker: str, title: str, sub: str, views: list[dict], variant: str = "olive") -> str:
    tr = "".join(stage(v["img"], 0.82) for v in views[:3])
    return f'''<section class="cv post v-{variant}">{contour(title, 1000, 300, 600)}
<div class="pad">{top(chip(kicker, True))}
<h1 class="h hl" data-fit="72" style="font-size:150px;max-height:420px;margin-top:34px">{hl(title)}</h1>
<div class="trio">{tr}</div><div class="sub">{E(sub)}</div>{bot(SWIPE)}</div></section>'''


def l_item(v: dict, idx: int, i: int, n: int, variant: str = "cream", label: str | None = None) -> str:
    num = f'<div class="num h">{idx:02d}</div>' if idx else ""
    return f'''<section class="cv post v-{variant}"><div class="pad">{top(cnt(i, n))}
<div class="lrow">{num}<div class="ltx"><div class="kick mono">{E(label or v["cat"])}</div>
<div class="pname" data-fit="26">{E(v["name"])}</div></div></div>
{stage(v["img"], 952 / 690, "flex:1;margin-top:22px")}
<div class="meta"><div style="min-width:0;flex:1">{_ara(v, "font-size:26px;color:var(--fg)")}</div>
<div class="price h">{E(v["price"])}</div></div>{bot(SWIPE)}</div></section>'''


def t_cover(kicker: str, title: str, intro: str, n_steps: int, variant: str = "olive") -> str:
    return f'''<section class="cv post v-{variant}">{contour(title, 900, 1080, 640, op=0.13)}
<div class="pad">{top(chip(kicker, True))}
<h1 class="h hl" data-fit="74" style="font-size:168px;max-height:660px;margin-top:44px">{hl(title)}</h1>
<div style="flex:1"></div><div class="sub" style="font-size:42px;max-width:900px">{E(intro)}</div>
<div class="badge mono">{ico("bookmark", 30)} {n_steps} madde · kaydet</div>{bot(SWIPE)}</div></section>'''


def t_step(h: str, t: str, k: int, total: int, i: int, n: int, variant: str = "cream") -> str:
    dots = "".join(f'<i class="{"on" if d < k else ""}"></i>' for d in range(total))
    return f'''<section class="cv post v-{variant}"><div class="pad">{top(cnt(i, n))}
<div class="tnum h">{k:02d}</div><div class="h th" data-fit="52">{E(h)}</div>
<div class="tt" data-fit="32">{E(t)}</div><div class="dots">{dots}</div>{bot(SWIPE)}</div></section>'''


def t_end(text: str, i: int, n: int, variant: str = "ink") -> str:
    return f'''<section class="cv post v-{variant}">{contour("end" + text[:8], 980, 260, 560)}
<div class="pad">{top(cnt(i, n))}<div class="kick mono" style="margin-top:70px">Özetle</div>
<div class="h hl" data-fit="60" style="font-size:124px;max-height:700px;margin-top:22px;line-height:1.04">{E(text)}</div>
<div class="badge mono">{ico("bookmark", 30)} Lazım olunca bulmak için kaydet</div>
<div style="flex:1"></div>{bot(SWIPE)}</div></section>'''


def b_newyear(year: int, line: str, variant: str = "ink") -> str:
    return f'''<section class="cv post v-{variant}">{contour("ny", 900, 380, 700, n=10, op=0.14)}
<div class="pad">{top(chip("Mutlu yıllar", True))}<div class="ny"><div class="kick mono">Yeni yıl, yeni rotalar</div>
<div class="h yr">{year}</div><div class="h" style="font-size:112px;margin-top:26px">Bol <em>kilometreli</em><br>bir yıl olsun</div>
<div class="sub" style="font-size:38px;margin-top:30px;max-width:860px">{E(line)}</div></div>
{bot("", SITE_TXT)}</div></section>'''


# ---- Story kareleri (1080x1920; güvenli alan y 262…1594) ---------------------------------------

def _dock(link: bool, label: str, fallback: str) -> str:
    """link=True: Business Suite'te link çıkartması bu yuvaya oturur. False: API yedeği, 'link profilde' hapı."""
    if link:
        return (f'<div class="dock"><div class="dk-l mono">{ico("down", 30, 3)}{E(label)}{ico("down", 30, 3)}</div>'
                f'<div class="dk-s"></div></div>')
    return f'<div class="dock"><div class="pill mono">{ico("link", 34, 2.4)}{fallback}</div></div>'


STICKER = {"x": 0.5, "y": 0.781, "w": 0.5}  # yuvanın merkezi (kanvas oranı)


def s_product(v: dict, kicker: str, headline: str, link: bool, variant: str = "cream") -> str:
    return f'''<section class="cv story v-{variant}">{sbg(v["code"] + "st")}
<div class="pad">{top(chip(v["cat"]))}<div class="kick mono">{E(kicker)}</div>
<h1 class="h hl" data-fit="64" style="font-size:118px;max-height:224px">{hl(headline)}</h1>
{stage(v["img"], 952 / 520, "flex:1;margin-top:26px")}{_meta(v, ara=False)}
{_dock(link, "Ürüne gitmek için dokun", "Ürüne git")}</div></section>'''


def s_promo(cover: Path, kicker: str, headline: str, link: bool, label: str, fallback: str,
            variant: str = "ink", mock: Path | None = None) -> str:
    """mock: kartta gösterilecek kapak görseli (ARA'sız kopya); yoksa postun kendi kapağı."""
    return f'''<section class="cv story v-{variant}">{sbg(str(cover.name))}
<div class="pad">{top(chip("Yeni gönderi", True))}<div class="kick mono">{E(kicker)}</div>
<h1 class="h hl" data-fit="60" style="font-size:112px;max-height:212px">{hl(headline)}</h1>
<div class="mockw"><div class="mock"><img src="{(mock or cover).as_uri()}" alt=""></div></div>
{_dock(link, label, fallback)}</div></section>'''


def s_tip(kicker: str, h: str, t: str, variant: str = "olive", dock: tuple[bool, str, str] | None = None) -> str:
    """dock=(link, label, fallback): konuya özel linkli story; None: linksiz değer story'si."""
    tail = _dock(*dock) if dock else bot("", SITE_TXT)
    return f'''<section class="cv story v-{variant}">{sbg(h)}
<div class="pad">{top(chip(kicker, True))}<div class="q"><div class="kick mono" style="margin-top:0">Atölyeden not</div>
<div class="h" data-fit="70" style="margin-top:22px">{E(h)}</div><p>{E(t)}</p>
<div class="badge mono">{ico("send", 30)} Lazım olana gönder</div></div>{tail}</div></section>'''


def s_question(q: str, variant: str = "orange") -> str:
    return f'''<section class="cv story v-{variant}">{sbg(q)}
<div class="pad">{top(chip("Soru", True))}<div class="q"><div class="kick mono" style="margin-top:0">Senin cevabın ne?</div>
<div class="h" data-fit="70" style="margin-top:22px">{E(q)}</div>
<div class="badge mono" style="background:var(--fg);color:var(--bg)">{ico("chat", 30)} Cevabını mesajla yaz</div></div>
{bot("", SITE_TXT)}</div></section>'''


def s_trio(kicker: str, title: str, views: list[dict], link: bool, variant: str = "cream") -> str:
    rows = "".join(f'<div class="tr">{stage(v["img"], 1)}<div class="tx"><div class="pname" data-fit="22">{E(v["name"])}</div>'
                   + f'</div><div class="price h sm">{E(v["price"])}</div></div>'
                   for v in views[:3])
    return f'''<section class="cv story v-{variant}">{sbg(title)}
<div class="pad">{top(chip(kicker, True))}
<h1 class="h hl" data-fit="64" style="font-size:112px;max-height:212px;margin-top:30px">{hl(title)}</h1>
<div class="trs">{rows}</div>{_dock(link, "Mağazaya gitmek için dokun", "Mağazaya git")}</div></section>'''


def s_facts(chip_txt: str, kicker: str, title: str, facts: list[tuple[str, str, str]], link: bool, label: str,
            fallback: str, variant: str = "ink") -> str:
    body = "".join(f'<div class="wy"><div class="ic">{ico(ic, 52)}</div><div><b>{E(t)}</b>'
                   f'{f"<span>{E(s)}</span>" if s else ""}</div></div>' for ic, t, s in facts)
    tail = _dock(link, label, fallback) if (link or fallback) else bot("", SITE_TXT)
    return f'''<section class="cv story v-{variant}">{sbg(title)}
<div class="pad">{top(chip(chip_txt, True))}<div class="kick mono">{E(kicker)}</div>
<h1 class="h hl" data-fit="64" style="font-size:124px;max-height:348px">{hl(title)}</h1>
<div class="facts">{body}</div>{tail}</div></section>'''


# ---- Reel sahneleri (1080x1920; önemli içerik y 262…1262, alt bölüm Instagram arayüzünün altında kalır) ----

def _reel(variant: str, seed: str, inner: str) -> str:
    return (f'<section class="cv story reel v-{variant}">{contour(seed, 900, 1560, 700, op=0.12)}'
            f'<div class="pad">{inner}</div><div class="rfoot mono"><span>@{IG_USERNAME}</span><span>{SITE_TXT}</span></div></section>')


def r_hook(v: dict, kicker: str, headline: str) -> str:
    return _reel("ink", v["code"] + "r1", f'''{top(chip(v["cat"]))}<div class="kick mono">{E(kicker)}</div>
<h1 class="h hl" data-fit="70" style="font-size:150px;max-height:290px">{hl(headline)}</h1>
{stage(v["img"], 952 / 520, "flex:1;margin-top:26px")}''')


def r_hero(v: dict) -> str:
    return _reel("cream", v["code"] + "r2", f'''{top(chip("nitrobisiklet.com", True))}
{stage(v["img"], 952 / 640, "flex:1;margin-top:26px")}
<div class="h" data-fit="52" style="font-size:84px;max-height:164px;margin-top:26px;overflow:hidden;text-transform:none">{E(v["name"])}</div>''')


def r_specs(v: dict, rows: list[tuple[str, str]]) -> str:
    body = "".join(f'<div class="rsp"><small>{E(k)}</small><b data-fit="44">{E(val)}</b></div>' for k, val in rows[:3])
    return _reel("olive", v["code"] + "r3", f'''{top(chip("Öne çıkanlar", True))}
<div class="rbox" style="gap:20px;margin-top:30px">{body}</div>''')


def r_perks(facts: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<div class="wy"><div class="ic">{ico(ic, 52)}</div><div><b>{E(t)}</b>'
                   f'{f"<span>{E(s)}</span>" if s else ""}</div></div>' for ic, t, s in facts[:3])
    return _reel("ink", "perks", f'''{top(chip("Neden NITRO", True))}
<h1 class="h" style="font-size:118px;margin-top:34px">NITRO'dan <em>alınca</em></h1><div class="facts">{body}</div>''')


def r_cta(v: dict) -> str:
    return _reel("cream", v["code"] + "r5", f'''{top(chip(v["cat"]))}<div class="kick mono" style="margin-top:40px">Fiyat</div>
<div class="h rprice" data-fit="110">{E(v["price"])}</div>
<div class="tile" style="margin-top:34px"><div style="flex:none"><small>Aramaya<br>yaz</small></div><b data-fit="30" data-tam="1" style="flex:1;min-width:0;text-align:right;overflow:hidden">“{E(v["q"])}”</b></div>
<div class="steps" style="justify-content:flex-start;margin-top:22px;flex:1">
<div class="st"><i>1</i><b>Profildeki nitrobisiklet.com linkine dokun</b></div><div class="st"><i>2</i><b>Arama simgesine dokun, üstteki terimi yaz</b></div></div>''')


# ---- Çizim ---------------------------------------------------------------------------------------

def _kind(section: str) -> str:
    return "story" if 'class="cv story' in section[:40] else "post"


def _shoot(sections: list[str], outs: list[Path], kind: str) -> None:
    w, h = SIZES[kind]
    with tempfile.TemporaryDirectory() as td:
        src, png = Path(td) / "p.html", Path(td) / "p.png"
        src.write_text(page(sections), encoding="utf-8")
        cmd = [chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
               "--force-device-scale-factor=1", f"--user-data-dir={td}/ud", f"--window-size={w},{h * len(sections)}",
               "--virtual-time-budget=12000", f"--screenshot={png}", src.as_uri()]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=240)
        except subprocess.TimeoutExpired:
            # Chrome bazen takılır: kareleri tek tek yeniden dene (tek karede bir kez daha dene, sonra hata ver)
            if len(sections) > 1:
                for s, o in zip(sections, outs):
                    _shoot([s], [o], kind)
                return
            subprocess.run(cmd, check=True, capture_output=True, timeout=240)
        im = Image.open(png).convert("RGB")
        if im.size != (w, h * len(sections)):
            if len(sections) == 1:
                raise RuntimeError(f"Ekran görüntüsü boyutu beklenmedik: {im.size}")
            for s, o in zip(sections, outs):  # yedek: kareleri tek tek çiz
                _shoot([s], [o], kind)
            return
        for i, o in enumerate(outs):
            o.parent.mkdir(parents=True, exist_ok=True)
            im.crop((0, i * h, w, (i + 1) * h)).save(o, "JPEG", quality=88, optimize=True, progressive=True)


def render_all(jobs: list[tuple[str, Path]], workers: int = 4) -> None:
    """jobs: (section HTML, çıktı JPEG yolu). Kareler tür bazında toplu çizilir."""
    chunks = []
    for kind in SIZES:
        sel = [(s, Path(o)) for s, o in jobs if _kind(s) == kind]
        n = PER_PAGE[kind]
        chunks += [(sel[i:i + n], kind) for i in range(0, len(sel), n)]

    def run(chunk):
        part, kind = chunk
        _shoot([s for s, _ in part], [o for _, o in part], kind)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run, chunks))


def thumb(src: Path, dst: Path, w: int = 360) -> None:
    im = Image.open(src).convert("RGB")
    im.thumbnail((w, w * 3), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=80, optimize=True)


def contact_sheet(paths: list[Path], out: Path, cols: int = 6, tw: int = 300) -> None:
    """Kalite denetimi için küçük resim föyü."""
    ims = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((tw, tw * 2), Image.LANCZOS)
        ims.append(im)
    if not ims:
        return
    th = max(i.height for i in ims)
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (cols * (tw + 8) + 8, rows * (th + 8) + 8), (60, 60, 60))
    for k, im in enumerate(ims):
        sheet.paste(im, (8 + (k % cols) * (tw + 8), 8 + (k // cols) * (th + 8)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=82)


if __name__ == "__main__":
    import content
    from common import fmt_price, load_codes, load_products

    slug = sys.argv[1] if len(sys.argv) > 1 else None
    prods = load_products()
    p = next((x for x in prods if x["slug"] == slug), prods[0])
    info = prep(p["images"][0])
    v = {"name": content.display_name(p), "price": fmt_price(p["price"]), "code": load_codes().get(p["slug"], "N000"), "q": __import__("arama").terim(p),
         "cat": p["category"], "img": info}
    out = ROOT / "out" / "deneme"
    render_all([(p_cover(v, "Günün ürünü", "Sürüşü <em>kolaylaştır</em>"), out / "kapak.jpg"),
                (s_product(v, "Günün ürünü", "Sürüşü <em>kolaylaştır</em>", True), out / "story.jpg")])
    print(out)
