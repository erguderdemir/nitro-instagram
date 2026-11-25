#!/usr/bin/env python3
"""Instagram dışı kanallar için hazır metin paketi: data/paylas/

Hiçbir şey göndermez, hiçbir yere bağlanmaz; yalnız dosya yazar. Barış'a yalnız kullanıcı izniyle iletilir.
Gerçekler (telefon, adres, saat, servis paketi, kargo, fiyat) yalnız data/site.json ve data/products.json'dan
birebir alınır; takvimden yalnız post başlığı, kancası ve ipucu maddeleri gelir. Postlarda N-kodu kullanılmaz.

  gbp_haftalik.md     Google İşletme Profili: haftanın 2–3 gönderisi (ürün sayfası + utm_source=google&utm_medium=gbp)
  qr_tezgah.md        Tezgâh QR kartı: hedef URL ve kart metni (+ qr_tezgah.svg / qr_tezgah.png, saf Python)
  hizli_yanitlar.md   Instagram hızlı yanıtları: fiyat, servis randevusu, kargo, adres/saat
  one_cikan.md        4 Öne Çıkan başlığı, kapak rengi ve içerik önerisi (görsel üretilmez)
  grup_metinleri.md   Facebook yerel grup ve WhatsApp grup duyurusu (bilgi verir; çekiliş, aciliyet yok)

Dosyalar deterministiktir: aynı veri aynı çıktıyı verir. Tarih yalnız haftalık dosyaların başlığında, takvim
haftasından türetilerek yazılır. Hafta: Pazartesi–Perşembe çalışmada içinde bulunulan hafta, Cuma–Pazar
çalışmada gelecek hafta (Pazartesi–Pazar).

  python3 scripts/paylas.py
  python3 scripts/paylas.py --hafta 2026-11-23 --cikti /tmp/paylas
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import common
import content as C
from common import AY, DATA, fmt_price

OUT = DATA / "paylas"
QR_URL = "https://nitrobisiklet.com/?utm_source=magaza&utm_medium=qr&utm_campaign=qr-tezgah"
GBP_URUN = 2            # haftalık pakette en çok ürün gönderisi
# Gönderilen metinde olmaması gereken iddialar (denetim.BANNED'e ek): sahte aciliyet, çekiliş, yorum karşılığı ödül
ACILIYET = re.compile(r"son ürün|son gün|bugün bitiyor|kaçırma|acele|kontenjan|sınırlı sayıda|çekiliş|kura\b|"
                      r"hediye kazan|yorum yap.{0,20}kazan|takip et.{0,20}kazan", re.I)
N_KODU = re.compile(r"\bN\d{3,4}\b")


# ---- Yardımcılar ---------------------------------------------------------------------------------

def utm(url: str, source: str, medium: str, campaign: str, content: str | None = None) -> str:
    """content.utm'in kaynak seçilebilen hâli; #parça korunur."""
    base, _, frag = url.partition("#")
    q = {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign}
    if content:
        q["utm_content"] = content
    return f"{base}{'&' if '?' in base else '?'}{urlencode(q)}" + (f"#{frag}" if frag else "")


def hafta_basi(bugun: date) -> date:
    """Pzt–Per: bu haftanın Pazartesi'si; Cum–Paz: gelecek haftanın Pazartesi'si."""
    pzt = bugun - timedelta(days=bugun.weekday())
    return pzt if bugun.weekday() <= 3 else pzt + timedelta(days=7)


def hafta_etiketi(bas: date) -> str:
    son = bas + timedelta(days=6)
    yil, hf, _ = bas.isocalendar()
    if bas.month == son.month:
        aralik = f"{bas.day}–{son.day} {AY[son.month - 1]} {son.year}"
    else:
        aralik = f"{bas.day} {AY[bas.month - 1]} – {son.day} {AY[son.month - 1]} {son.year}"
    return f"{aralik} ({yil}-W{hf:02d})"


def kaynak_satiri(site: dict) -> str:
    t = (site.get("_extra") or {}).get("fetched_at") or "?"
    return f"Kaynak: `data/site.json` (site taraması {t}) ve `data/products.json`. Hiçbir şey otomatik gönderilmez."


def kargo_satirlari(site: dict) -> list[str]:
    return [f"{r['teslimat_sekli']}: {r['ucret']} · {r['sure']}"
            for r in (site.get("_extra") or {}).get("shipping_table") or []]


def paketler(site: dict) -> list[dict]:
    return ((site.get("service") or {}).get("items") or [])[:3]


def fakt(liste: list[str], basi: str) -> str:
    """site.json'daki bir facts satırını başından tanıyıp birebir döndürür; yoksa boş."""
    return next((f for f in liste if f.startswith(basi)), "")


def cumle_duzeni(s: str) -> str:
    """BÜYÜK HARFLİ başlığı Türkçe cümle düzenine çevirir (İ/I doğru)."""
    t = C.tr_lower(s.strip())
    return ({"i": "İ", "ı": "I"}.get(t[:1], t[:1].upper()) + t[1:]) if t else ""


def odeme_yontemi(site: dict) -> str:
    """site.json payment: "Ödeme, Alıcı'nın seçtiği yöntemle (kredi/banka kartı veya havale/EFT) yapılır." """
    f = fakt((site.get("payment") or {}).get("facts") or [], "Ödeme, Alıcı'nın")
    m = re.search(r"\(([^)]+)\)", f)
    return m.group(1) if m else "ödeme sayfasında gösterilir"


def kod(metin: str) -> str:
    """Kopyalanacak metin bloğu (Markdown)."""
    return "```text\n" + metin.strip() + "\n```"


def hafta_postlari(cal: list[dict], bas: date) -> list[dict]:
    son = bas + timedelta(days=6)
    iptal = common.cancelled_ids()
    return [c for c in sorted(cal, key=lambda x: (x["date"], x["time"], x["id"]))
            if c.get("type") == "post" and c.get("status") in common.ACTIVE and c["id"] not in iptal
            and bas.isoformat() <= c["date"] <= son.isoformat()]


def urun_bul(slug: str, prods: dict) -> dict | None:
    p = prods.get(slug)
    if not p or not p.get("in_stock") or p.get("price") is None or C.excluded(p):
        return None
    return p


def ipucu_maddeleri(c: dict) -> list[str]:
    """Kaydırmalı ipucu postunun madde başlıkları ("1. Sürüşten Sonra Kurula")."""
    out = []
    for a in c.get("alts") or []:
        m = re.match(r"^(\d)\.\s*([^:]+):", a)
        if m:
            out.append(f"{m.group(1)}. {m.group(2).strip()}")
    return out


def haftanin_ipucu(cal: list[dict], bas: date) -> dict | None:
    """Haftadaki ilk ipucu postu; yoksa haftadan sonraki ilk ipucu postu."""
    ipucu = [c for c in hafta_postlari(cal, bas) if c.get("theme") == "ipucu" and ipucu_maddeleri(c)]
    if ipucu:
        return ipucu[0]
    iptal = common.cancelled_ids()
    sonra = [c for c in sorted(cal, key=lambda x: (x["date"], x["time"], x["id"]))
             if c.get("type") == "post" and c.get("theme") == "ipucu" and c["date"] > bas.isoformat()
             and c.get("status") in common.ACTIVE and c["id"] not in iptal and ipucu_maddeleri(c)]
    return sonra[0] if sonra else None


def cta_adresi(c: dict, site: dict) -> str:
    """İpucu postunun yönlendirdiği nitrobisiklet.com sayfası (UTM'siz)."""
    urls = site.get("urls") or {}
    return urls.get("servis") if c.get("cta") == "servis" else urls.get("magaza") or common.SITE + "/"


# ---- GBP haftalık paketi -------------------------------------------------------------------------

def gbp_urun(c: dict, p: dict, site: dict) -> tuple[str, str, str, str]:
    """(başlık, metin, düğme, düğme bağlantısı)"""
    link = utm(p["url"], "google", "gbp", c.get("theme") or "urun", c["id"])
    satir = [C.plain(c.get("title") or ""), c.get("hook") or "", "",
             f"{p['name']} · {fmt_price(p['price'])} (KDV dahil)"]
    satir += [f"• {k}: {v}" for k, v in C.clean_specs(p, 3)]
    satir += ["", *kargo_satirlari(site)[:2], "", f"Mağaza: {site.get('address', '')} · {site.get('hours', '')}"]
    return C.plain(c.get("title") or p["name"]), "\n".join(satir).strip(), "Satın al", link


def gbp_servis(c: dict | None, site: dict) -> tuple[str, str, str, str]:
    svc = site.get("service") or {}
    camp, icerik = ("ipucu", c["id"]) if c else ("servis", None)
    link = utm(svc.get("booking_url") or (site.get("urls") or {}).get("servis", ""), "google", "gbp", camp, icerik)
    satir = []
    if c:
        satir += [cumle_duzeni(C.plain(c.get("title") or "")), c.get("hook") or "", ""]
    satir.append(svc.get("headline") or "Servis")
    satir += [f"• {it['name']}: {it['price']} · {it['duration']}" for it in paketler(site)]
    satir += ["", fakt(svc.get("facts") or [], "Paketin içindekiler sabittir"),
              fakt(svc.get("facts") or [], "01 Randevu")]
    return "Servis randevusu", "\n".join(satir).strip(), "Randevu al", link


def gbp_paketi(cal: list[dict], prods: dict, site: dict, bas: date) -> str:
    postlar = hafta_postlari(cal, bas)
    gonderi, kategoriler = [], set()
    # Önce tek ürünlü postlar, sonra liste postlarının ürünleri; aynı kategoriden iki ürün yok.
    adaylar = [(c, x) for c in postlar if c.get("theme") == "urun" for x in (c.get("products") or [])[:1]]
    adaylar += [(c, x) for c in postlar if c.get("theme") == "liste" for x in (c.get("products") or [])]
    for c, x in adaylar:
        p = urun_bul(x.get("slug") or "", prods)
        if not p or p.get("category") in kategoriler or len(gonderi) >= GBP_URUN:
            continue
        kategoriler.add(p.get("category"))
        gonderi.append(gbp_urun(c, p, site))
    ip = next((c for c in postlar if c.get("theme") in ("ipucu", "servis") and c.get("cta") == "servis"), None)
    gonderi.append(gbp_servis(ip, site))

    out = [f"# Google İşletme Profili: haftalık gönderiler · {hafta_etiketi(bas)}", "",
           kaynak_satiri(site), "",
           "Nasıl kullanılır: GBP → Güncelleme ekle. Metni kopyala, düğmeyi seç, bağlantıyı yapıştır. "
           "Telefonu metne yazma; \"Ara\" düğmesi profildeki numarayı kullanır. Fiyatı paylaşmadan önce ürün "
           "sayfasında bir kez kontrol et.", ""]
    for i, (baslik, metin, dugme, link) in enumerate(gonderi, 1):
        out += [f"## {i}. {baslik}", "", kod(metin), "", f"- Düğme: **{dugme}** → {link}", ""]
    if len(gonderi) < 2:
        out += ["> Bu hafta takvimde stokta ürünü olan post yok; yalnız servis gönderisi hazırlandı.", ""]
    return "\n".join(out)


# ---- Tezgâh QR kartı -----------------------------------------------------------------------------

def qr_metni(site: dict, svg_var: bool) -> str:
    out = ["# Tezgâh QR kartı", "", kaynak_satiri(site), "",
           f"- Hedef: {QR_URL}",
           "- Ölçüm: GA4'te `utm_campaign=qr-tezgah` oturumları.", ""]
    if svg_var:
        out += ["- Dosyalar: `qr_tezgah.svg` (baskı için, vektör) ve `qr_tezgah.png` (önizleme). "
                "Hata düzeltme M; en az 2,5 cm basılmalı, çevresindeki beyaz boşluk kesilmemeli.",
                "- Basmadan önce telefon kamerasıyla okut; açılan adres yukarıdaki hedefle aynı olmalı.", ""]
    else:
        out += ["- QR görseli üretilemedi; hedef bağlantıyı herhangi bir QR üreticisine ver.", ""]
    satir = ["NITRO Bisiklet · Köyceğiz", fakt(site.get("taglines") or [], "Satış ve servis"), "",
             "Kameranı tut: mağaza, servis randevusu ve fiş takibi", "nitrobisiklet.com", "",
             f"{site.get('address', '')}", f"{site.get('hours', '')}", f"Telefon / WhatsApp: {site.get('phone', '')}"]
    out += ["## Kart metni", "", kod("\n".join(satir)), "",
            "Not: Kartta Google yorumu istenecekse yalnız gerçek müşteriden istenir; yorum karşılığında hiçbir "
            "şey verilmez.", ""]
    return "\n".join(out)


# ---- Instagram hızlı yanıtları -------------------------------------------------------------------

def hizli_yanitlar(site: dict) -> str:
    urls = site.get("urls") or {}
    svc = site.get("service") or {}
    pay = (site.get("payment") or {}).get("facts") or []
    ship = (site.get("shipping") or {}).get("facts") or []
    ret = (site.get("returns") or {}).get("facts") or []

    def dm(url: str, konu: str) -> str:
        return utm(url, "instagram", "dm", "hizli-yanit", konu)

    yanit = [
        ("fiyat", "Fiyat", [
            "Merhaba! Güncel fiyat ürün sayfasında yazıyor; fiyatlar KDV dahil.",
            "Ürünün adını ya da postta yazan arama terimini nitrobisiklet.com'da aramaya yazarsan ürün sayfası "
            "açılır: "
            + dm(urls.get("magaza", ""), "fiyat"),
            fakt(pay, "Taksitli ödemelerde vade farkı"),
            f"Telefon / WhatsApp: {site.get('phone', '')}"]),
        ("servis", "Servis randevusu", [
            "Merhaba! Servis randevusunu online alabilirsin: " + dm(svc.get("booking_url", ""), "servis"),
            fakt(svc.get("facts") or [], "01 Randevu").removeprefix("01 Randevu: "),
            "Paketler: " + " · ".join(f"{it['name']} {it['price']} ({it['duration']})" for it in paketler(site)),
            fakt(svc.get("facts") or [], "Paketin içindekiler sabittir")]),
        ("kargo", "Kargo", [
            "Merhaba! " + fakt(ship, "Stoktaki ürünler"),
            *kargo_satirlari(site),
            fakt(ship, "Hafta sonu ve resmi tatillerde"),
            fakt(ret, "Nitro Bisiklet'ten aldığın ürünü"),
            "Ayrıntı: " + dm(urls.get("kargo", ""), "kargo")]),
        ("adres", "Adres ve saat", [
            "Merhaba! Adresimiz: " + site.get("address", ""),
            "Çalışma saatleri: " + site.get("hours", ""),
            "Yol tarifi: " + site.get("maps_url", ""),
            f"Telefon / WhatsApp: {site.get('phone', '')}"]),
    ]
    out = ["# Instagram hızlı yanıtları", "", kaynak_satiri(site), "",
           "Instagram → Ayarlar → İşletme araçları → Kayıtlı yanıtlar (sürüme göre \"Hızlı yanıtlar\"). "
           "Kısayolu yaz, mesajı yapıştır. "
           "Yanıtı mesajı okuyan kişi elle gönderir; otomatik gönderim yok.", ""]
    for kisayol, baslik, satirlar in yanit:
        out += [f"## {baslik} · kısayol: `{kisayol}`", "", kod("\n".join(s for s in satirlar if s)), ""]
    return "\n".join(out)


# ---- Öne Çıkanlar --------------------------------------------------------------------------------

def one_cikan(site: dict) -> str:
    urls = site.get("urls") or {}
    kat = urls.get("categories") or {}
    oneriler = [
        ("Nasıl Alırım", "NASIL ALIRIM", "sepet",
         ["\"ÜRÜNE GİT\" çıkartmalı ürün story'leri (çıkartma doğrudan ürün sayfasına gider).",
          "Ödeme yöntemleri: " + odeme_yontemi(site) + "; fiyatlar KDV dahil."],
         urls.get("magaza", "")),
        ("Servis", "SERVİS", "anahtar",
         ["Servis paketleri story'si: " + " · ".join(f"{it['name']} {it['price']}" for it in paketler(site)),
          "\"SERVİS RANDEVUSU AL\" çıkartmalı randevu story'si."],
         (site.get("service") or {}).get("booking_url", "")),
        ("2. El", "2. EL", "bisiklet",
         ["2. el bisiklet story'leri; yalnız \"Kontrollü 2. el\" yazılır, başka durum iddiası yok.",
          "Fiyat yalnız products.json'daki fiyat."],
         kat.get("2. El Bisiklet", "")),
        ("Teslimat-İade", "TESLİMAT", "kamyon",
         ["Kargo ve teslimat story'si: " + "; ".join(kargo_satirlari(site)[:2]),
          "İade story'si: " + (fakt((site.get("returns") or {}).get("facts") or [],
                                    "Nitro Bisiklet'ten aldığın ürünü")
                               or "iade sayfasındaki metin birebir kullanılır.")],
         urls.get("kargo", "")),
    ]
    out = ["# Instagram Öne Çıkanlar", "", kaynak_satiri(site), "",
           "Kapaklar render.py ile üretilmedi; aşağıdaki renk ve yazıyla elle hazırlanır (1080×1920, ortadaki "
           "daire güvenli alan). Zemin `#14150f` (koyu), yazı ve simge `#f5821f` (turuncu), ince çerçeve "
           "`#f1ede2` (krem). Yazıtipi takvim görselleriyle aynı.", ""]
    for i, (ad, kapak, simge, icerik, link) in enumerate(oneriler, 1):
        out += [f"## {i}. {ad}", "", f"- Kapak yazısı: **{kapak}** · simge: {simge}",
                f"- Story çıkartmasının hedefi: {link}", *[f"- İçerik: {s}" for s in icerik], ""]
    return "\n".join(out)


# ---- Facebook / WhatsApp grup metinleri ----------------------------------------------------------

def grup_metinleri(cal: list[dict], site: dict, bas: date) -> str:
    ip = haftanin_ipucu(cal, bas)
    story = (site.get("story") or {}).get("facts") or []
    topluluk = (site.get("_extra") or {}).get("community") or {}
    out = [f"# Grup metinleri · {hafta_etiketi(bas)}", "", kaynak_satiri(site), "",
           "Yalnız grup kuralları izin veriyorsa, gerekiyorsa yöneticiye sorarak ve elle paylaş. Kişilere tek tek "
           "ya da toplu ticari mesaj gönderilmez (ETK/İYS onayı yok).", ""]

    def ipucu_blogu(source: str, medium: str) -> list[str]:
        if not ip:
            return []
        link = utm(cta_adresi(ip, site), source, medium, "ipucu", ip["id"])
        return [cumle_duzeni(C.plain(ip.get("title") or "")), ip.get("hook") or "", "",
                *ipucu_maddeleri(ip), "", f"Ayrıntı: {link}"]

    wa = ipucu_blogu("whatsapp", "group")
    if not wa:  # takvimde ipucu postu yoksa WhatsApp metni yine üretilir: yalnız site.json gerçekleri
        wa = [fakt(site.get("taglines") or [], "Satış ve servis"), fakt(story, "Dağ, yol, gravel"), "",
              f"{site.get('address', '')} · {site.get('hours', '')}",
              utm(common.SITE + "/", "whatsapp", "group", "wa-grup")]
    out += [f"## WhatsApp grubu ({topluluk.get('name', 'topluluk')})", "",
            kod("\n".join(wa)), ""]
    fb = [fakt(site.get("taglines") or [], "Satış ve servis"),
          fakt(story, "Dağ, yol, gravel"), "",
          "Servis paketleri: " + " · ".join(f"{it['name']} {it['price']} ({it['duration']})" for it in paketler(site)),
          *kargo_satirlari(site)[:2], "",
          f"{site.get('address', '')} · {site.get('hours', '')}",
          utm(common.SITE + "/", "facebook", "group", "fb-grup")]
    if ip:
        fb += ["", "Bu haftanın ipucu:", *ipucu_blogu("facebook", "group")]
    out += ["## Facebook yerel grup", "", kod("\n".join(fb)), ""]
    if topluluk.get("whatsapp_group"):
        out += [f"Topluluk grubu bağlantısı (site.json): {topluluk['whatsapp_group']}", ""]
    return "\n".join(out)


# ---- QR kodlayıcı (saf Python; bayt kipi, hata düzeltme M, sürüm 1–10) ------------------------------
# Kaynak algoritma: ISO/IEC 18004; yapı Nayuki'nin açık "QR Code generator" kütüphanesini izler.

_ECC_M = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]   # blok başına hata düzeltme kod sözcüğü
_BLOK_M = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]            # blok sayısı


def _rs_carp(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_bolen(derece: int) -> list[int]:
    r = [0] * (derece - 1) + [1]
    kok = 1
    for _ in range(derece):
        for j in range(derece):
            r[j] = _rs_carp(r[j], kok)
            if j + 1 < derece:
                r[j] ^= r[j + 1]
        kok = _rs_carp(kok, 0x02)
    return r


def _rs_kalan(veri: list[int], bolen: list[int]) -> list[int]:
    r = [0] * len(bolen)
    for b in veri:
        f = b ^ r.pop(0)
        r.append(0)
        for i, k in enumerate(bolen):
            r[i] ^= _rs_carp(k, f)
    return r


def _ham_modul(v: int) -> int:
    r = (16 * v + 128) * v + 64
    if v >= 2:
        n = v // 7 + 2
        r -= (25 * n - 10) * n - 55
        if v >= 7:
            r -= 36
    return r


def _veri_kod_sozcugu(v: int) -> int:
    return _ham_modul(v) // 8 - _ECC_M[v] * _BLOK_M[v]


def _hizalama(v: int, boy: int) -> list[int]:
    if v == 1:
        return []
    n = v // 7 + 2
    adim = (v * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    return list(reversed([boy - 7 - i * adim for i in range(n - 1)] + [6]))


def qr_matris(metin: str) -> list[list[bool]]:
    veri = metin.encode("utf-8")
    for v in range(1, 11):
        sayac = 8 if v < 10 else 16
        if 4 + sayac + 8 * len(veri) <= _veri_kod_sozcugu(v) * 8:
            break
    else:
        raise ValueError("metin QR sürüm 10'a sığmıyor")
    kapasite = _veri_kod_sozcugu(v) * 8
    bit: list[int] = []

    def ekle(deger: int, n: int) -> None:
        bit.extend((deger >> i) & 1 for i in reversed(range(n)))

    ekle(0b0100, 4)
    ekle(len(veri), sayac)
    for b in veri:
        ekle(b, 8)
    ekle(0, min(4, kapasite - len(bit)))
    ekle(0, -len(bit) % 8)
    dolgu = 0xEC
    while len(bit) < kapasite:
        ekle(dolgu, 8)
        dolgu ^= 0xEC ^ 0x11
    kodlar = [int("".join(map(str, bit[i:i + 8])), 2) for i in range(0, len(bit), 8)]

    # Bloklara böl, hata düzeltme ekle, iç içe geçir
    nblok, ecc = _BLOK_M[v], _ECC_M[v]
    ham = _ham_modul(v) // 8
    kisa_n = nblok - ham % nblok
    kisa_boy = ham // nblok
    bolen = _rs_bolen(ecc)
    bloklar, k = [], 0
    for i in range(nblok):
        d = kodlar[k:k + kisa_boy - ecc + (0 if i < kisa_n else 1)]
        k += len(d)
        e = _rs_kalan(d, bolen)
        if i < kisa_n:
            d = d + [0]
        bloklar.append(d + e)
    sirali = [blk[i] for i in range(len(bloklar[0])) for j, blk in enumerate(bloklar)
              if i != kisa_boy - ecc or j >= kisa_n]

    boy = v * 4 + 17
    m = [[False] * boy for _ in range(boy)]
    fn = [[False] * boy for _ in range(boy)]

    def koy(x: int, y: int, koyu: bool) -> None:
        m[y][x] = koyu
        fn[y][x] = True

    for i in range(boy):
        koy(6, i, i % 2 == 0)
        koy(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (boy - 4, 3), (3, boy - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < boy and 0 <= y < boy:
                    koy(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    hz = _hizalama(v, boy)
    for i, a in enumerate(hz):
        for j, b in enumerate(hz):
            if (i, j) in ((0, 0), (0, len(hz) - 1), (len(hz) - 1, 0)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    koy(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)

    def bicim(maske: int) -> None:
        d = (0 << 3) | maske          # M düzeyinin biçim bitleri 00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        bits = (d << 10 | r) ^ 0x5412
        b = [(bits >> i) & 1 == 1 for i in range(15)]
        for i in range(6):
            koy(8, i, b[i])
        koy(8, 7, b[6])
        koy(8, 8, b[7])
        koy(7, 8, b[8])
        for i in range(9, 15):
            koy(14 - i, 8, b[i])
        for i in range(8):
            koy(boy - 1 - i, 8, b[i])
        for i in range(8, 15):
            koy(8, boy - 15 + i, b[i])
        koy(8, boy - 8, True)

    bicim(0)
    if v >= 7:
        r = v
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        bits = v << 12 | r
        for i in range(18):
            b = (bits >> i) & 1 == 1
            a, c = boy - 11 + i % 3, i // 3
            koy(a, c, b)
            koy(c, a, b)

    i = 0
    sag = boy - 1
    while sag >= 1:
        if sag == 6:
            sag = 5
        for dikey in range(boy):
            for j in range(2):
                x = sag - j
                yukari = ((sag + 1) & 2) == 0
                y = boy - 1 - dikey if yukari else dikey
                if not fn[y][x] and i < len(sirali) * 8:
                    m[y][x] = (sirali[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
        sag -= 2

    maskeler = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
                lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
                lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
                lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def uygula(k: int) -> None:
        for y in range(boy):
            for x in range(boy):
                if not fn[y][x] and maskeler[k](x, y):
                    m[y][x] = not m[y][x]

    en_iyi, en_az = 0, None
    for k in range(8):
        uygula(k)
        bicim(k)
        p = _ceza(m)
        if en_az is None or p < en_az:
            en_iyi, en_az = k, p
        uygula(k)          # maskeyi geri al (XOR)
    uygula(en_iyi)
    bicim(en_iyi)
    return m


def _ceza(m: list[list[bool]]) -> int:
    """ISO 18004 ceza puanı (kural 3 sadeleştirilmiş: 1011101 + 4 açık modül, iki yönde)."""
    boy, p = len(m), 0
    satirlar = [m[y] for y in range(boy)] + [[m[y][x] for y in range(boy)] for x in range(boy)]
    desen1 = [True, False, True, True, True, False, True, False, False, False, False]
    desen2 = desen1[::-1]
    for s in satirlar:
        n = 1
        for i in range(1, boy + 1):
            if i < boy and s[i] == s[i - 1]:
                n += 1
            else:
                if n >= 5:
                    p += 3 + (n - 5)
                n = 1
        for i in range(boy - 10):
            if s[i:i + 11] in (desen1, desen2):
                p += 40
    for y in range(boy - 1):
        for x in range(boy - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                p += 3
    koyu = sum(sum(r) for r in m)
    toplam = boy * boy
    p += max(0, (abs(koyu * 20 - toplam * 10) + toplam - 1) // toplam - 1) * 10
    return p


def qr_svg(m: list[list[bool]], bosluk: int = 4) -> str:
    boy = len(m) + 2 * bosluk
    yol = "".join(f"M{x + bosluk},{y + bosluk}h1v1h-1z" for y, r in enumerate(m) for x, k in enumerate(r) if k)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {boy} {boy}" shape-rendering="crispEdges">'
            f'<rect width="100%" height="100%" fill="#ffffff"/><path d="{yol}" fill="#000000"/></svg>\n')


def qr_png(m: list[list[bool]], olcek: int = 10, bosluk: int = 4) -> bytes:
    """8 bit gri PNG (stdlib zlib); zaman damgası ya da üst veri yok, çıktı deterministik."""
    boy = (len(m) + 2 * bosluk) * olcek
    satirlar = bytearray()
    for py in range(boy):
        y = py // olcek - bosluk
        satirlar.append(0)
        for px in range(boy):
            x = px // olcek - bosluk
            koyu = 0 <= y < len(m) and 0 <= x < len(m) and m[y][x]
            satirlar.append(0 if koyu else 255)

    def parca(tur: bytes, veri: bytes) -> bytes:
        return struct.pack(">I", len(veri)) + tur + veri + struct.pack(">I", zlib.crc32(tur + veri) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + parca(b"IHDR", struct.pack(">IIBBBBB", boy, boy, 8, 0, 0, 0, 0))
            + parca(b"IDAT", zlib.compress(bytes(satirlar), 9)) + parca(b"IEND", b""))


# ---- Denetim ve yazma ----------------------------------------------------------------------------

def denetle(ad: str, metin: str, site: dict) -> list[str]:
    """Gönderilecek metinde yasak iddia, N-kodu, github.io ya da site.json dışı telefon/saat yok."""
    from denetim import BANNED  # takvim denetçisinin yasak iddia listesi (tek kaynak)
    out = []
    for etiket, rx in (("yasak iddia", BANNED), ("aciliyet/çekiliş", ACILIYET), ("N-kodu", N_KODU)):
        for m in rx.finditer(metin):
            out.append(f"{ad}: {etiket} «{m.group(0)}»")
    if "github.io" in metin or common.public_base() and common.public_base() in metin:
        out.append(f"{ad}: github.io bağlantısı")
    for tel in re.findall(r"0\d{3} \d{3} \d{2} \d{2}", metin):
        if tel != site.get("phone"):
            out.append(f"{ad}: telefon site.json'dakinden farklı «{tel}»")
    for saat in re.findall(r"\d{2}:\d{2}–\d{2}:\d{2}", metin):
        if saat not in (site.get("hours") or ""):
            out.append(f"{ad}: saat site.json'dakinden farklı «{saat}»")
    for url in re.findall(r"https?://[^\s)>\"]+", metin):
        if not re.match(r"https://(nitrobisiklet\.com/|share\.google/|chat\.whatsapp\.com/|wa\.me/)", url):
            out.append(f"{ad}: izinsiz bağlantı «{url}»")
    return out


def yaz(yol: Path, veri: str | bytes) -> bool:
    """Yalnız içerik değiştiyse yazar."""
    eski = yol.read_bytes() if yol.exists() else None
    yeni = veri.encode("utf-8") if isinstance(veri, str) else veri
    if eski == yeni:
        return False
    yol.write_bytes(yeni)
    return True


def uret(bugun: date, cikti: Path = OUT, hafta: date | None = None) -> int:
    site = common.load_site()
    if not site.get("phone") or not site.get("hours"):
        print("[paylas] site.json eksik (telefon/saat yok); paket üretilmedi")
        return 1
    cal = common.load_calendar()
    prods = {p["slug"]: p for p in common.load_products()}
    bas = hafta or hafta_basi(bugun)
    metinler = {
        "gbp_haftalik.md": gbp_paketi(cal, prods, site, bas),
        "qr_tezgah.md": "",
        "hizli_yanitlar.md": hizli_yanitlar(site),
        "one_cikan.md": one_cikan(site),
        "grup_metinleri.md": grup_metinleri(cal, site, bas),
    }
    ikili: dict[str, bytes | str] = {}
    try:
        mat = qr_matris(QR_URL)
        ikili = {"qr_tezgah.svg": qr_svg(mat), "qr_tezgah.png": qr_png(mat)}
    except Exception as e:  # noqa: BLE001
        print(f"[paylas] QR görseli üretilemedi: {e}")
    metinler["qr_tezgah.md"] = qr_metni(site, bool(ikili))

    bulgu = [b for ad, t in metinler.items() for b in denetle(ad, t, site)]
    if bulgu:
        for b in bulgu:
            print(f"[paylas] BULGU {b}")
        print("[paylas] bulgu var; dosyalar yazılmadı")
        return 1
    cikti.mkdir(parents=True, exist_ok=True)
    degisen = [ad for ad, t in {**metinler, **ikili}.items() if yaz(cikti / ad, t)]
    print(f"[paylas] {cikti}: {len(metinler) + len(ikili)} dosya, {len(degisen)} değişti"
          + (f" ({', '.join(degisen)})" if degisen else "") + f" · hafta {hafta_etiketi(bas)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--hafta", help="haftanın herhangi bir günü (YYYY-AA-GG); verilirse o haftanın Pazartesi'si")
    ap.add_argument("--cikti", type=Path, default=OUT, help="çıktı klasörü (varsayılan data/paylas)")
    a = ap.parse_args(argv)
    hafta = None
    if a.hafta:
        g = date.fromisoformat(a.hafta)
        hafta = g - timedelta(days=g.weekday())
    return uret(common.now().date(), a.cikti, hafta)


if __name__ == "__main__":
    sys.exit(main())
