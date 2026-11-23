#!/usr/bin/env python3
"""Ortak yardımcılar: yollar, ayarlar, takvim ve veri dosyaları.

Tüm betikler bu modülü kullanır; ağır bağımlılığı (Pillow, Chrome) yoktur.
"""
from __future__ import annotations

import json
import os
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


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

def load_products() -> list[dict]:
    return read_json(DATA / "products.json", [])


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
    if v is None:
        return ""
    return f"{v:,.0f}".replace(",", ".") + " ₺"


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
