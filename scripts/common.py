#!/usr/bin/env python3
"""Ortak yardımcılar: yollar, ayarlar, takvim ve veri dosyaları.

Tüm betikler bu modülü kullanır; ağır bağımlılığı (Pillow, Chrome) yoktur.
"""
from __future__ import annotations

import json
import os
import re
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
MEDIA = DOCS / "media"
THUMBS = MEDIA / "t"
CAL = DATA / "calendar.json"
IPTAL = DATA / "iptal.txt"

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = timezone(timedelta(hours=CFG["timezone_offset_hours"]))
SITE = "https://nitrobisiklet.com"
IG_USERNAME = CFG.get("instagram_username", "nitrobisiklet")
REPO = CFG.get("repo", "erguderdemir/nitro-instagram")

GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
GUN_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

# Ürünü/kategoriyi "kullanılmış" sayan durumlar (tekrar paylaşım aralığı için)
ACTIVE = ("planned", "draft", "published")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, obj, indent: int | None = 1) -> None:
    """Atomik yazım: önce yanındaki geçici dosyaya, sonra os.replace. Yarıda kesilen yazım dosyayı bozmaz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, path)


def now() -> datetime:
    return datetime.now(TZ)


# ---- Takvim ------------------------------------------------------------------------------------

def load_calendar() -> list[dict]:
    return read_json(CAL, [])


def save_calendar(cal: list[dict]) -> None:
    cal.sort(key=lambda x: (x["date"], x["time"], x["type"]))
    write_json(CAL, cal)


def item_dt(c: dict) -> datetime:
    return datetime.fromisoformat(f"{c['date']}T{c['time']}").replace(tzinfo=TZ)


def cancelled_ids() -> set[str]:
    """data/iptal.txt: her satırda iptal edilecek bir paylaşım kimliği (# ile başlayan satır yorumdur)."""
    if not IPTAL.exists():
        return set()
    out = set()
    for line in IPTAL.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line.split()[0])
    return out


# ---- Veri dosyaları ----------------------------------------------------------------------------

# Sitedeki bazı ürün fotoğrafları ürünü yanlış gösteriyor; bu dosya adları içerikte hiç kullanılmaz.
GORSEL_ENGEL = {
    "comet-isik.png",   # lamba yerine ölçü çizimi ve Çince yazı
    "bisan-sorrento-s-28-sehir-bisikleti-1x7-vites-koyu-yesil-3.jpeg",   # koyu yeşil ürünün altında açık yeşil kadro
    "bisan-sorrento-s-28-sehir-bisikleti-1x7-vites-koyu-yesil-4.jpeg",   # aynı: açık yeşil kadro
    # Bisikletin yarısını gösteren yakın plan site görselleri (karede kesik bisiklet gibi duruyor)
    "bisan-sorrento-s-28-sehir-bisikleti-1x7-vites-koyu-yesil-2.jpeg",
    "bisan-all-trail-eco-sora-gravel-bisiklet-28-jant.png",
    "Bisan-envious-29-22-jant-elektrikli-dag-bisikleti-m-kadro.png",
    "bisan-trx-8200-trekking-bisikleti-3x7-vites-45cm-acik-metali-2.jpeg",
    "carraro-gravel-g0-28-jant-bisiklet.png",   # site galerisinden kesilmiş, ok işareti kalmış
    "schwalbe-smart-sam-performance-29x2-25-d-2.jpg",   # kahverengi yanaklı varyant; ürün siyah
    # Kadro arası çanta: başka markalı bisiklet öne çıkıyor
    "procycle-pc-350-kadro-arasi-canta-siyah-1.jpg",
    "procycle-pc-350-kadro-arasi-canta-siyah-4.jpg",
    "procycle-pc-350-kadro-arasi-canta-siyah-5.jpg",
    # İkinci göz denetimi (24 Kasım)
    "shimano-kutusuz-balata-seti.png",   # tek takım ürün, görselde toplu servis kutusu
    "bisan-mtx-7200-27-5-dag-bisikleti-3x8-vi-3.jpg",   # arka teker kesik
    "360-donebilen-genis-acili-ikili-dikiz-ay-3.jpg",   # ölçü çizimi
    "ayna-mr-k03-360-donebilir-20-aci-ayarlanabilir-2503240200-1.jpg",   # gidon kesik kırpılmış
}


def load_products() -> list[dict]:
    prods = read_json(DATA / "products.json", [])
    for p in prods:
        if p.get("images"):
            p["images"] = [u for u in p["images"] if u.rsplit("/", 1)[-1] not in GORSEL_ENGEL]
    return prods


# O14 ortak gönderi (collab): en çok 3 kullanıcı adı; yalnız config.json'da "collab_onay": true iken gönderilir
COLLAB_MAX = 3
KULLANICI_ADI = re.compile(r"^[a-z0-9._]{1,30}$")


def collab_listesi(c: dict) -> list[str] | None:
    """Kaydın `collaborators` alanı geçerliyse küçük harfli kullanıcı adları, değilse None.

    Geçerli: boş olmayan liste, en çok 3, yinelenmeyen, Instagram kullanıcı adı biçiminde, kendi hesabımız değil.
    publish.py geçersiz listeyi göndermez; denetim.py aynı işlevle bulgu verir."""
    names = c.get("collaborators")
    if not isinstance(names, list) or not names:
        return None
    out = [str(n).strip().lstrip("@").lower() for n in names]
    own = str(CFG.get("instagram_username") or "").lower()
    if len(out) > COLLAB_MAX or len(set(out)) != len(out) or own in out or not all(KULLANICI_ADI.match(n) for n in out):
        return None
    return out


def load_codes() -> dict[str, str]:
    """Ürün slug'ı -> kısa ürün kodu (N101…). Görsellerde ve bio sayfasındaki aramada kullanılır."""
    return read_json(DATA / "codes.json", {})


def load_site() -> dict:
    """Siteden doğrulanmış mağaza bilgileri (telefon, adres, servis, kargo…). Dosya yoksa boş sözlük."""
    return read_json(DATA / "site.json", {})


def load_tips() -> dict:
    return read_json(DATA / "tips.json", {})


def load_scores() -> dict:
    """Geçmiş performanstan türetilen puanlar (scripts/report.py üretir). Yoksa boş."""
    return read_json(DATA / "scores.json", {})


# ---- Biçimlendirme -----------------------------------------------------------------------------

def fmt_price(v: float | None) -> str:
    """1.250 ₺ · 93,53 ₺. Kuruşlu fiyat yuvarlanmaz: görseldeki fiyat sitedeki fiyatla aynı olmalı."""
    if v is None:
        return ""
    if abs(v - round(v)) < 0.005:
        return f"{round(v):,}".replace(",", ".") + " ₺"
    whole, frac = f"{v:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{frac} ₺"


def tr_date(d, with_day: bool = True) -> str:
    """24 Kasım Salı"""
    s = f"{d.day} {AY[d.month - 1]}"
    return f"{s} {GUN[d.weekday()]}" if with_day else s


def public_base() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or CFG.get("public_base_url", "")).rstrip("/")


def ssl_context() -> ssl.SSLContext:
    """python.org macOS kurulumunda kök sertifikalar eksik olabilir; sistem paketini yükle."""
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for ca in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
            if Path(ca).exists():
                ctx.load_verify_locations(ca)
                break
    return ctx
