#!/usr/bin/env python3
"""Takvim denetçisi: yayınlanacak her kaydı kurallara karşı sınar. Sıfır bulgu olmadan teslim yok.

  python3 scripts/denetim.py              tüm denetimler (dosyalar dahil)
  python3 scripts/denetim.py --dosyasiz   medya dosyalarına bakmadan (kuru sınama)

Bulgulu kayıt yayınlanmaz: durumu `draft` yapılır ve bulgular kaydın `audit` alanına yazılır (yayıncı yalnız
`planned` kayıtları işler). Bulgu temizlenince kayıt yeniden `planned` olur. Sonuç data/denetim.json'a yazılır,
simülasyon sayfası güncellenir. Bulgu varsa çıkış kodu 1'dir.

Denetimler:
  kural      başlık, ürünün kuralının (alt türünün) o ayki başlık havuzundan mı; ürün adı alt türe uyuyor mu
  liste      başlıktaki adet = ürün sayısı; eşik: tüm fiyatlar eşiğin altında; liste içinde yinelenen ürün yok
  veri       takvimdeki ad/fiyat/kod = güncel ürün verisi; ürün stokta; hariç tutulan ürün yok
  link       ürün adresi + UTM (source, medium, campaign, content); linkli story Suite kanalında ve çıkartmalı
  metin      açıklama ≤2200, ilk satır ≤125, ≤5 etiket, fiyat ve kod açıklamada; yasak iddia yok; çıkartma ≤25
  dosya      dosya var, JPEG, ölçü (post 1080×1350, story 1080×1920), ≤8 MB; reel MP4 H.264/AAC 9:16
  ritim      günde tek post, haftada tek "Haftanın bisikleti", günde tek "Günün ürünü"
  tekrar     tekrar penceresi içinde aynı ürün ya da aynı ürün ailesi iki kayıtta yok
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import common
import content as C
from common import CFG, DATA, DOCS, fmt_price

OUT = DATA / "denetim.json"
STATUSES = ("planned", "draft", "published", "skipped", "missed", "error")
THEMES = ("urun", "ipucu", "liste", "servis", "marka", "promo", "etkilesim")
FORMATS = {"post": ("carousel", "reel", "image"), "story": ("story",)}
STICKERS = ("ÜRÜNE GİT", "FİYATI GÖR", "MAĞAZAYA GİT", "SERVİS RANDEVUSU AL")
SIZE = {"post": (1080, 1350), "story": (1080, 1920)}
MAX_IMAGE, MAX_VIDEO = 8 * 1024 * 1024, 100 * 1024 * 1024
BANNED = re.compile(r"indirim|kampanya|fırsat|bedava|son \d+ (adet|gün|saat)|stokta son|tükenmeden|%\s?\d+|\d+\s?%'?\s?(indirim|ucuz)",
                    re.I)
# Görselde CSS Türkçe büyük harfe çevirir: küçük harfle yazılmış "i" içeren yabancı sözcük bozulur (BİKE)
FOREIGN = re.compile(r"\b(bike|nitro|trail|city|line|dirt|ride|light|mini|shimano|helix|unix|link)\b")
REQUIRED = ("id", "date", "time", "type", "format", "theme", "media", "cover", "thumb", "status", "rule", "channel")


class Audit:
    def __init__(self, cal: list[dict], files: bool = True):
        self.cal, self.files = cal, files
        self.products = {p["slug"]: p for p in common.load_products()}
        self.codes = common.load_codes()
        self.tips = common.load_tips()
        self.by_id = {c.get("id"): c for c in cal}
        self.found: list[dict] = []

    def add(self, c: dict, code: str, msg: str) -> None:
        self.found.append({"id": c.get("id", "?"), "code": code, "msg": msg})

    # ---- tek kayıt ---------------------------------------------------------------------------------

    def check(self, c: dict) -> None:
        miss = [k for k in REQUIRED if k not in c]
        if miss:
            self.add(c, "sema", f"eksik alan: {', '.join(miss)}")
            return
        try:
            day = date.fromisoformat(c["date"])
            common.item_dt(c)
        except ValueError:
            self.add(c, "sema", "date/time okunamadı")
            return
        if c["id"] != f"{c['date']}-{c['type']}-{c['time'].replace(':', '')}":
            self.add(c, "sema", "kimlik tarih/saat/tür ile uyuşmuyor")
        if c["status"] not in STATUSES or c["theme"] not in THEMES or c["format"] not in FORMATS.get(c["type"], ()):
            self.add(c, "sema", f"geçersiz durum/tema/biçim: {c['status']}/{c['theme']}/{c['format']}")
        self.rule(c, day)
        self.data(c)
        self.links(c)
        self.text(c, day)
        if self.files:
            self.media(c)

    def rule(self, c: dict, day: date) -> None:
        theme, ps = c["theme"], c.get("products") or []
        if theme == "urun":
            if len(ps) != 1:
                self.add(c, "kural", f"ürün içeriğinde tek ürün olmalı ({len(ps)})")
                return
            p = self.products.get(ps[0]["slug"])
            r = C.rule_of(p) if p else None
            if not r:
                self.add(c, "kural", f"ürünün kuralı yok ya da hariç tutulmuş: {ps[0]['slug']}")
                return
            if not (r["id"] == c["rule"] == ps[0].get("rule")):
                self.add(c, "kural", f"kayıttaki kural ({c['rule']}) ürünün kuralı ({r['id']}) değil")
            if not C.name_fits(r["id"], p["name"]):
                self.add(c, "kural", f"ürün adı '{r['label']}' alt türüne uymuyor: {p['name']}")
            if not C.headline_ok(r["id"], c.get("headline") or c.get("title") or "", day.month):
                self.add(c, "kural", f"başlık '{c.get('title')}' {r['id']} kuralının bu ayki havuzunda yok")
        elif theme == "liste":
            lid = c.get("ref")
            if lid not in C.LISTS:
                self.add(c, "liste", f"bilinmeyen liste: {lid}")
                return
            cfg = C.LISTS[lid]
            allowed = {r for r, _ in cfg["slots"]}
            cur = [self.products.get(x["slug"]) for x in ps]
            if any(p is None for p in cur):
                return                                   # veri denetimi bildirir
            for p, x in zip(cur, ps):
                r = C.rule_of(p)
                if not r or r["id"] not in allowed or r["id"] != x.get("rule") or not C.name_fits(r["id"], p["name"]):
                    self.add(c, "liste", f"listeye uymayan ürün: {x['name']}")
                if cfg["cap"] is not None and not p["price"] < cfg["cap"]:
                    self.add(c, "liste", f"{x['name']} {fmt_price(p['price'])}: {cfg['cap']} ₺ eşiğinin altında değil")
                if cfg["floor"] is not None and p["price"] < cfg["floor"]:
                    self.add(c, "liste", f"{x['name']} {fmt_price(p['price'])}: {cfg['floor']} ₺ alt sınırının altında")
            try:
                want = C.plain(C.list_title(lid, [{"price": p["price"]} for p in cur]))
            except ValueError as e:
                self.add(c, "liste", f"liste kuralı sağlanmıyor: {e}")
                return
            if c.get("title") != want:
                self.add(c, "liste", f"başlık '{c.get('title')}' hesaplanan '{want}' değil")
            nums = re.findall(r"(\d+) (?:ürün|hediye|yılbaşı|yükseltme)", c.get("title") or "")
            if not nums or int(nums[-1]) != len(ps):
                self.add(c, "liste", f"başlıktaki adet ürün sayısı ({len(ps)}) değil")
            n_img = len(c.get("media") or [])
            if n_img != len(ps) + 2:
                self.add(c, "liste", f"kare sayısı ({n_img}) ürün sayısı + 2 değil")
            slugs, fams = [x["slug"] for x in ps], [C.family(p) for p in cur]
            if len(set(slugs)) != len(slugs) or len(set(fams)) != len(fams):
                self.add(c, "liste", "liste içinde yinelenen ürün/aile var")
        elif theme == "promo":
            post = self.by_id.get(c.get("ref"))
            if not post or post["type"] != "post" or post["date"] != c["date"]:
                self.add(c, "kural", "tanıtım story'si aynı günün postuna bağlı değil")
                return
            if post["theme"] in ("urun", "liste") and c.get("title") != post.get("title"):
                self.add(c, "kural", "tanıtım başlığı postun başlığı değil")
            if [x["slug"] for x in ps] != [x["slug"] for x in post.get("products") or []] or c["rule"] != post["rule"]:
                self.add(c, "kural", "tanıtım story'sinin ürünleri/kuralı postla aynı değil")
            if common.item_dt(c) <= common.item_dt(post):
                self.add(c, "kural", "tanıtım story'si posttan önce")
        elif theme == "ipucu":
            text = c.get("title") or ""
            if c["type"] == "post":
                tip = next((t for t in self.tips.get("carousels", []) if t["id"] == c.get("ref")), None)
                if not tip:
                    self.add(c, "kural", f"ipucu bulunamadı: {c.get('ref')}")
                elif len(c["media"]) != len(tip["steps"]) + 3:
                    self.add(c, "kural", "ipucu kare sayısı adım sayısı + 3 değil")
            else:
                t = next((t for t in self.tips.get("story_tips", []) if t["h"] == text), None)
                if not t:
                    self.add(c, "kural", "story ipucu data/tips.json içinde yok")
                elif not C.in_season(t["h"] + " " + t["t"], day.month):
                    self.add(c, "mevsim", f"mevsim dışı ipucu: {text}")
        elif theme == "etkilesim":
            q = c.get("title") or ""
            if q not in self.tips.get("questions", []):
                self.add(c, "kural", "soru data/tips.json içinde yok")
            elif not C.in_season(q, day.month):
                self.add(c, "mevsim", f"mevsim dışı soru: {q}")
        if theme not in ("urun", "liste", "promo") and ps:
            self.add(c, "kural", "ürün dışı içerikte ürün var")

    def data(self, c: dict) -> None:
        for x in c.get("products") or []:
            p = self.products.get(x["slug"])
            if not p:
                self.add(c, "veri", f"ürün artık sitede yok: {x['slug']}")
                continue
            if C.excluded(p):
                self.add(c, "veri", f"hariç tutulan ürün (scooter/motosiklet/otomobil): {p['name']}")
            if p.get("in_stock") is not True:
                self.add(c, "stok", f"ürün stokta değil: {x['name']}")
            if not p.get("price") or abs(p["price"] - x["price"]) > 0.004:
                self.add(c, "fiyat", f"{x['name']}: takvimde {fmt_price(x['price'])}, sitede {fmt_price(p.get('price'))}")
            if p.get("old_price"):
                self.add(c, "fiyat", f"{x['name']}: eski fiyat alanı dolu; indirim iddiası doğrulanmadan içerik olmaz")
            if x["name"] != C.display_name(p):
                self.add(c, "veri", f"ürün adı değişmiş: {x['name']} → {C.display_name(p)}")
            if x.get("code") != self.codes.get(x["slug"]) or not re.fullmatch(r"N\d{3,4}", x.get("code") or ""):
                self.add(c, "kod", f"ürün kodu uyuşmuyor: {x.get('code')} / {self.codes.get(x['slug'])}")
        ps = c.get("products") or []
        if c["theme"] == "urun" and ps and c.get("code") != ps[0].get("code"):
            self.add(c, "kod", "kayıt kodu ürün kodu değil")

    def links(self, c: dict) -> None:
        medium = "story" if c["type"] == "story" else "social"
        camp = c["theme"]
        for x in c.get("products") or []:
            p = self.products.get(x["slug"])
            if not p:
                continue
            if not x["link"].startswith(p["url"] + "?") or not C.utm_ok(x["link"], medium, camp, c["id"]):
                self.add(c, "link", f"ürün linki/UTM hatalı: {x['link']}")
            if not x.get("bio_link", "").startswith(p["url"] + "?") or not C.utm_ok(x["bio_link"], "bio", camp, c["id"]):
                self.add(c, "link", f"bio linki/UTM hatalı: {x.get('bio_link')}")
        link = c.get("link") or ""
        if link:
            if not link.startswith(common.SITE + "/") or not C.utm_ok(link, medium, camp, c["id"]):
                self.add(c, "link", f"kayıt linki/UTM hatalı: {link}")
            if c["theme"] == "urun" and link != c["products"][0]["link"]:
                self.add(c, "link", "kayıt linki ürün linki değil")
        linked = c["type"] == "story" and c["theme"] in ("urun", "promo")
        if c["type"] == "story" and (linked or c.get("sticker") or c["channel"] == "suite"):
            st = c.get("sticker") or {}
            if c["channel"] != "suite" or not st or not link:
                self.add(c, "link", "linkli story Suite kanalında, çıkartmalı ve linkli olmalı")
                return
            if st.get("url") != link:
                self.add(c, "link", "çıkartma adresi kayıt linki değil")
            if st.get("text") not in STICKERS or len(st.get("text") or "") > 25:
                self.add(c, "metin", f"çıkartma metni geçersiz ya da 25 karakterden uzun: {st.get('text')}")
            if not all(isinstance(st.get(k), (int, float)) and 0 < st[k] < 1 for k in ("x", "y", "w")):
                self.add(c, "link", "çıkartma konumu (x, y, w) eksik")
            if not c.get("media_link"):
                self.add(c, "dosya", "çıkartma yuvalı sürüm (media_link) yok")
            if c["theme"] == "urun" and st.get("text") not in STICKERS[:2]:
                self.add(c, "metin", "ürün story'sinde çıkartma metni ürüne götürmeli")
        elif c["type"] == "story" and c["channel"] != "api":
            self.add(c, "link", "linksiz story API kanalında olmalı")
        if c["type"] == "post" and c["channel"] != "api":
            self.add(c, "link", "post API kanalında olmalı")

    def text(self, c: dict, day: date) -> None:
        cap = c.get("caption") or ""
        for field in ("kicker", "title"):
            m = FOREIGN.search(c.get(field) or "")
            if m:
                self.add(c, "metin", f"{field} içinde küçük harfli yabancı sözcük (görselde bozulur): {m.group(0)}")
        if c["type"] == "story":
            if cap:
                self.add(c, "metin", "story'de açıklama olmaz")
            return
        if not cap.strip():
            self.add(c, "metin", "açıklama boş")
            return
        if len(cap) > C.CAPTION_MAX:
            self.add(c, "metin", f"açıklama {len(cap)} karakter (sınır {C.CAPTION_MAX})")
        first = cap.split("\n", 1)[0]
        if len(first) > C.FIRST_LINE_MAX:
            self.add(c, "metin", f"ilk satır {len(first)} karakter (sınır {C.FIRST_LINE_MAX})")
        tags = re.findall(r"(?<!\w)#\w+", cap)
        if len(tags) > C.TAG_MAX:
            self.add(c, "metin", f"{len(tags)} etiket var (sınır {C.TAG_MAX})")
        if "#nitrobisiklet" not in tags:
            self.add(c, "metin", "#nitrobisiklet etiketi yok")
        m = BANNED.search(cap) if c["theme"] != "ipucu" else re.search(r"indirim|kampanya|bedava|stokta son", cap, re.I)
        if m:
            self.add(c, "metin", f"açıklamada doğrulanamayan iddia: “{m.group(0)}”")
        if "Köyceğiz" not in cap:
            self.add(c, "metin", "yerel SEO satırı (Köyceğiz) yok")
        ps = c.get("products") or []
        for x in ps:
            if fmt_price(x["price"]) not in cap or x["code"] not in cap:
                self.add(c, "metin", f"açıklamada {x['name']} için fiyat ya da kod yok")
        if c["theme"] == "urun" and ps and f"arama kutusuna {ps[0]['code']} yaz" not in cap:
            self.add(c, "metin", "açıklamada 'arama kutusuna <kod> yaz' yönlendirmesi yok")
        alts = c.get("alts") or []
        if not c.get("alt") or (c["format"] == "carousel" and len(alts) != len(c["media"])):
            self.add(c, "metin", "alt metin eksik (her kare için bir alt metin olmalı)")
        if any(len(a) > 1000 for a in alts + [c.get("alt") or ""]):
            self.add(c, "metin", "alt metin 1000 karakteri aşıyor")

    # ---- dosyalar ----------------------------------------------------------------------------------

    def image(self, c: dict, rel: str, size: tuple[int, int] | None) -> None:
        from PIL import Image
        f = DOCS / rel
        if not rel or not f.is_file():
            self.add(c, "dosya", f"dosya yok: {rel}")
            return
        if f.stat().st_size > MAX_IMAGE or f.stat().st_size < 5000:
            self.add(c, "dosya", f"dosya boyutu sınır dışı ({f.stat().st_size} bayt): {rel}")
        try:
            with Image.open(f) as im:
                if im.format != "JPEG":
                    self.add(c, "dosya", f"JPEG değil ({im.format}): {rel}")
                if size and im.size != size:
                    self.add(c, "dosya", f"ölçü {im.size}, beklenen {size}: {rel}")
        except Exception as e:  # noqa: BLE001
            self.add(c, "dosya", f"görsel açılamadı: {rel} ({e})")

    def video(self, c: dict, rel: str) -> None:
        f = DOCS / rel
        if not f.is_file() or f.stat().st_size < 20000:
            self.add(c, "dosya", f"reel dosyası yok ya da boş: {rel}")
            return
        if f.stat().st_size > MAX_VIDEO:
            self.add(c, "dosya", f"reel {f.stat().st_size // 1_000_000} MB (sınır 100 MB)")
        head = f.read_bytes()[:64]
        if b"ftyp" not in head:
            self.add(c, "dosya", f"MP4 değil: {rel}")
            return
        try:
            import reel
            info = subprocess.run([reel.ffmpeg_bin(), "-hide_banner", "-i", str(f)], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace").stderr
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: ffmpeg bulunamadı, reel içeriği ayrıntılı denetlenemedi ({e})", file=sys.stderr)
            return
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
        if not re.search(r"Video: h264", info) or "1080x1920" not in info:
            self.add(c, "dosya", "reel H.264 1080x1920 değil")
        if "Audio: aac" not in info:
            self.add(c, "dosya", "reel ses izi AAC değil")
        if not 3 <= dur <= 90:
            self.add(c, "dosya", f"reel süresi {dur:.1f} sn (3–90 sn olmalı)")

    def media(self, c: dict) -> None:
        media, fmt = c.get("media") or [], c["format"]
        if fmt == "carousel" and not 2 <= len(media) <= 10:
            self.add(c, "dosya", f"carousel {len(media)} kare (2–10 olmalı)")
        if fmt in ("image", "story", "reel") and len(media) != 1:
            self.add(c, "dosya", f"{fmt} tek medya ister ({len(media)})")
        if fmt == "reel":
            for m in media:
                if not m.endswith(".mp4"):
                    self.add(c, "dosya", f"reel medyası MP4 değil: {m}")
                else:
                    self.video(c, m)
            self.image(c, c["cover"], SIZE["story"])
        else:
            for m in media:
                self.image(c, m, SIZE[c["type"]])
            if c["cover"] != (media[0] if media else None):
                self.add(c, "dosya", "kapak ilk kare değil")
        if c.get("media_link"):
            self.image(c, c["media_link"], SIZE["story"])
        self.image(c, c["thumb"], None)

    # ---- takvim geneli -----------------------------------------------------------------------------

    def calendar(self, live: list[dict]) -> None:
        ids = [c.get("id") for c in self.cal]
        for i in {i for i in ids if ids.count(i) > 1}:
            self.found.append({"id": i, "code": "sema", "msg": "aynı kimlik birden çok kayıtta"})
        per_day, weekly, daily = defaultdict(list), defaultdict(list), defaultdict(list)
        for c in live:
            d = date.fromisoformat(c["date"])
            if c["type"] == "post":
                per_day[c["date"]].append(c)
            k = common_lower(c.get("kicker"))
            if k == "haftanın bisikleti":
                weekly[d.isocalendar()[:2]].append(c)
                if not (c["type"] == "post" and d.weekday() == 0):
                    self.add(c, "ritim", "'Haftanın bisikleti' yalnız Pazartesi postunda kullanılır")
            if k == "günün ürünü":
                daily[c["date"]].append(c)
                if not (c["type"] == "story" and c["theme"] == "urun"):
                    self.add(c, "ritim", "'Günün ürünü' yalnız ürün story'sinde kullanılır")
        for group, msg in ((per_day, "aynı gün birden çok post"), (weekly, "aynı hafta birden çok 'Haftanın bisikleti'"),
                           (daily, "aynı gün birden çok 'Günün ürünü'")):
            for rows in group.values():
                for c in rows[1:]:
                    self.add(c, "ritim", msg)
        # tekrar penceresi: tanıtım story'si aynı içeriğin duyurusudur, sayılmaz
        win, uses = CFG["repeat_after_days"], []
        for c in live:
            if c["theme"] == "promo":
                continue
            for x in c.get("products") or []:
                p = self.products.get(x["slug"])
                uses.append((date.fromisoformat(c["date"]), x["slug"], C.family(p) if p else x["slug"], c))
        uses.sort(key=lambda u: (u[0], u[3]["id"]))
        for i, (d1, s1, f1, c1) in enumerate(uses):
            for d2, s2, f2, c2 in uses[i + 1:]:
                if c1 is not c2 and (s1 == s2 or f1 == f2) and (d2 - d1).days < win:
                    self.add(c2, "tekrar", f"{s2} ({f2}) {c1['id']} kaydında da var; tekrar penceresi {win} gün")

    def run(self) -> list[dict]:
        live = [c for c in self.cal if c.get("status") in ("planned", "draft")]
        for c in live:
            self.check(c)
        ok = [c for c in live if all(k in c for k in REQUIRED)]
        self.calendar(ok)
        return self.found


def common_lower(s) -> str:
    return C.tr_lower(str(s or "")).strip()


def apply(cal: list[dict], found: list[dict]) -> bool:
    """Bulgulu kayıtları taslağa çek, temizlenenleri geri al. Takvim değiştiyse True."""
    by = defaultdict(list)
    for f in found:
        by[f["id"]].append(f"{f['code']}: {f['msg']}")
    changed = False
    for c in cal:
        msgs = by.get(c.get("id"))
        if msgs and c.get("status") in ("planned", "draft"):
            if c.get("status") != "draft" or c.get("audit") != msgs:
                c["status"], c["audit"], changed = "draft", msgs, True
        elif c.get("audit"):
            c.pop("audit")
            if c.get("status") == "draft" and CFG.get("auto_publish", True):
                c["status"] = "planned"
            changed = True
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Takvim denetçisi")
    ap.add_argument("--dosyasiz", action="store_true", help="medya dosyalarını denetleme")
    ap.add_argument("--takvim", type=Path, help="denetlenecek takvim dosyası (varsayılan data/calendar.json; yazılmaz)")
    a = ap.parse_args(argv)
    cal = common.read_json(a.takvim, []) if a.takvim else common.load_calendar()
    found = Audit(cal, files=not a.dosyasiz).run()
    live = [c for c in cal if c.get("status") in ("planned", "draft")]
    for f in found:
        print(f"BULGU {f['id']} [{f['code']}] {f['msg']}")
    if not a.takvim:
        if apply(cal, found):
            common.save_calendar(cal)
        common.write_json(OUT, {"updated": common.now().isoformat(timespec="seconds"), "records": len(cal),
                                "checked": len(live), "files": not a.dosyasiz, "live": CFG.get("live") is True,
                                "findings": found})
        try:
            import simulasyon
            simulasyon.build_sim(cal)
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: simülasyon sayfası güncellenemedi: {e}", file=sys.stderr)
    held = len({f["id"] for f in found})
    print(f"DENETİM: {len(live)} kayıt denetlendi, {len(found)} bulgu" + (f" ({held} kayıt taslağa çekildi)" if found else "")
          + (" · dosyalar denetlenmedi" if a.dosyasiz else ""))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
