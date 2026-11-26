#!/usr/bin/env python3
"""Rota verisi (O13): data/rotalar.json'ı okur, kurallara karşı sınar ve seçilebilir rotaları verir.

Kural: her sayının kaynak adresi vardır; "kapalı" görünen rota seçilmez. Sayılar kaynaktan aynen alınır,
kaynaklar çelişirse ortalama alınmaz: bir değer seçilir (öncelik resmi rota sayfası), diğerleri `alternatif`
listesinde kaynağıyla durur.

Kayıt biçimi (rotalar[]):
  id, ad, baslangic, bitis, tip (halka|gidis-donus|tek-yon|bilinmiyor), guzergah [..], konum_kaynak (adres|null)
  mesafe_km, tirmanis_m, inis_m, max_rakim_m :
      null ya da {"deger", "kaynak", "kaynak_tur", "erisim", "alinti"?, "not"?, "alternatif": [{"deger","kaynak","kaynak_tur"}]}
  zemin, zorluk : null ya da {"deger", "kaynak"}
  durum : {"deger": acik|kapali|bilinmiyor, "kaynak", "kontrol" (YYYY-AA-GG), "not"}
  kis_uygun : {"deger": evet|kosullu|hayir|bilinmiyor, "gerekce", "kaynak"}
  uyarilar : [{"metin", "kaynak", "tarih"?, "etki"? (kapatir|kismen|etkilemez|bilinmiyor), "gecerli"? (evet|hayir|bilinmiyor)}]
  kaynaklar : kayıtta geçen bütün adresler

Seçim (`secilebilir`): durumu "kapali" olan, mesafesi kaynaklı olmayan ya da hâlâ geçerli ve rotayı kapatan bir
uyarısı olan rota seçilmez; Aralık–Şubat'ta kış uygunluğu "hayir" olan da seçilmez. Durum denetimi
DURUM_GECERLILIK_GUN günden eskiyse durum "bilinmiyor" sayılır (`durum_etkin`): eski bir "açık" etiketi bugün için
kanıt değildir, metinde "çıkmadan önce güncel durumu kontrol et" notu gerekir.

  python3 scripts/rotalar.py                    # doğrula; bulgu varsa çıkış 1
  python3 scripts/rotalar.py --tarih 2026-12-20 # o gün seçilebilir rotaları da listele
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DOSYA = common.DATA / "rotalar.json"
TIPLER = ("halka", "gidis-donus", "tek-yon", "bilinmiyor")
DURUMLAR = ("acik", "kapali", "bilinmiyor")
KIS = ("evet", "kosullu", "hayir", "bilinmiyor")
ETKILER = ("kapatir", "kismen", "etkilemez", "bilinmiyor")
GECERLI = ("evet", "hayir", "bilinmiyor")
KAYNAK_TURLERI = ("resmi-rota-baslik", "resmi-rota-istatistik", "resmi-turizm", "osm", "gps-kaydi", "planlayici",
                  "haber", "diger")
# (alan, alt sınır, üst sınır): sınır dışı değer büyük olasılıkla birim ya da okuma hatasıdır.
SAYILAR = (("mesafe_km", 0.5, 300), ("tirmanis_m", 1, 6000), ("inis_m", 1, 6000), ("max_rakim_m", 1, 2400))
NITELIKLER = ("zemin", "zorluk")
KIS_AYLARI = (12, 1, 2)
DURUM_GECERLILIK_GUN = 30
ALINTI_KELIME = 15
YASAK_ALAN = ("instagram.com", "facebook.com")
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$")


def yukle(yol: Path = DOSYA) -> dict:
    return common.read_json(yol, {}) or {}


def tarih_mi(s) -> bool:
    try:
        date.fromisoformat(s)
        return isinstance(s, str) and len(s) == 10
    except (TypeError, ValueError):
        return False


def url_mi(s) -> bool:
    return isinstance(s, str) and bool(URL.match(s)) and not any(a in s.lower() for a in YASAK_ALAN)


def sayi_mi(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _adresler(r: dict) -> set[str]:
    """Kayıtta kaynak olarak kullanılan bütün adresler (kaynaklar listesi hariç)."""
    out = set()
    if r.get("konum_kaynak"):
        out.add(r["konum_kaynak"])
    for alan, _, _ in SAYILAR:
        o = r.get(alan)
        if isinstance(o, dict):
            out.add(o.get("kaynak"))
            out.update(a.get("kaynak") for a in o.get("alternatif") or [] if isinstance(a, dict))
    for alan in NITELIKLER + ("durum", "kis_uygun"):
        o = r.get(alan)
        if isinstance(o, dict) and o.get("kaynak"):
            out.add(o["kaynak"])
    out.update(u.get("kaynak") for u in r.get("uyarilar") or [] if isinstance(u, dict))
    return {a for a in out if a}


def dogrula(veri: dict) -> list[str]:
    """Bulgu listesi döndürür; boş liste = veri kurallara uyuyor."""
    b: list[str] = []
    if not tarih_mi(veri.get("guncelleme")):
        b.append("guncelleme: YYYY-AA-GG tarihi yok")
    rotalar = veri.get("rotalar")
    if not isinstance(rotalar, list) or not rotalar:
        return b + ["rotalar: liste boş ya da yok"]
    atif = " ".join(veri.get("atif") or []) if isinstance(veri.get("atif"), list) else ""
    gorulen: set[str] = set()
    osm = False
    for i, r in enumerate(rotalar):
        if not isinstance(r, dict):
            b.append(f"rotalar[{i}]: nesne değil")
            continue
        rid = r.get("id")
        on = f"{rid or i}: "
        if not isinstance(rid, str) or not ID.match(rid):
            b.append(on + "id biçimi hatalı")
        elif rid in gorulen:
            b.append(on + "id yineleniyor")
        gorulen.add(rid)
        for alan in ("ad", "baslangic", "bitis"):
            if not isinstance(r.get(alan), str) or not r[alan].strip():
                b.append(on + f"{alan} boş")
        if r.get("tip") not in TIPLER:
            b.append(on + f"tip geçersiz: {r.get('tip')!r}")
        if not isinstance(r.get("guzergah"), list) or not all(isinstance(g, str) and g.strip() for g in r["guzergah"]):
            b.append(on + "guzergah metin listesi değil")
        konum_bilinen = r.get("tip") != "bilinmiyor" or any(
            isinstance(r.get(a), str) and r[a].strip() and r[a] != "bilinmiyor" for a in ("baslangic", "bitis"))
        if r.get("konum_kaynak") is not None and not url_mi(r["konum_kaynak"]):
            b.append(on + "konum_kaynak adres değil")
        elif konum_bilinen and not r.get("konum_kaynak"):
            b.append(on + "başlangıç/bitiş/tip dolu ama konum_kaynak yok")

        for alan, alt, ust in SAYILAR:
            o = r.get(alan)
            if o is None:
                continue
            if not isinstance(o, dict):
                b.append(on + f"{alan} nesne ya da null olmalı")
                continue
            for ad, g in [("", o)] + [(f".alternatif[{k}]", a) for k, a in enumerate(o.get("alternatif") or [])]:
                yer = on + alan + ad
                if not isinstance(g, dict):
                    b.append(yer + " nesne değil")
                    continue
                if not sayi_mi(g.get("deger")):
                    b.append(yer + " sayı değil")
                elif not alt <= g["deger"] <= ust:
                    b.append(yer + f" sınır dışı ({g['deger']}; beklenen {alt}–{ust})")
                if not url_mi(g.get("kaynak")):
                    b.append(yer + " kaynak adresi yok")
                if g.get("kaynak_tur") not in KAYNAK_TURLERI:
                    b.append(yer + f" kaynak_tur geçersiz: {g.get('kaynak_tur')!r}")
                osm = osm or g.get("kaynak_tur") == "osm"
                if g.get("alinti") and len(g["alinti"].split()) > ALINTI_KELIME:
                    b.append(yer + f" alıntı {ALINTI_KELIME} kelimeyi aşıyor")
            if not tarih_mi(o.get("erisim")):
                b.append(on + f"{alan} erisim tarihi yok")

        for alan in NITELIKLER:
            o = r.get(alan)
            if o is None:
                continue
            if not isinstance(o, dict) or not isinstance(o.get("deger"), str) or not o["deger"].strip():
                b.append(on + f"{alan} değeri boş")
            elif not url_mi(o.get("kaynak")):
                b.append(on + f"{alan} kaynak adresi yok")

        d = r.get("durum")
        if not isinstance(d, dict) or d.get("deger") not in DURUMLAR:
            b.append(on + "durum geçersiz")
        else:
            if not tarih_mi(d.get("kontrol")):
                b.append(on + "durum.kontrol tarihi yok")
            if d["deger"] != "bilinmiyor" and not url_mi(d.get("kaynak")):
                b.append(on + f"durum '{d['deger']}' ama kaynak adresi yok")
            if d.get("kaynak") and not url_mi(d["kaynak"]):
                b.append(on + "durum.kaynak adres değil")

        k = r.get("kis_uygun")
        if not isinstance(k, dict) or k.get("deger") not in KIS:
            b.append(on + "kis_uygun geçersiz")
        else:
            if not isinstance(k.get("gerekce"), str) or not k["gerekce"].strip():
                b.append(on + "kis_uygun.gerekce boş")
            if k["deger"] != "bilinmiyor" and not url_mi(k.get("kaynak")):
                b.append(on + f"kis_uygun '{k['deger']}' ama kaynak adresi yok")

        kapatan = False
        if not isinstance(r.get("uyarilar"), list):
            b.append(on + "uyarilar liste değil")
        else:
            for j, u in enumerate(r["uyarilar"]):
                yer = on + f"uyarilar[{j}]"
                if not isinstance(u, dict) or not isinstance(u.get("metin"), str) or not u["metin"].strip():
                    b.append(yer + " metin boş")
                    continue
                if not url_mi(u.get("kaynak")):
                    b.append(yer + " kaynak adresi yok")
                if u.get("etki") is not None and u["etki"] not in ETKILER:
                    b.append(yer + f" etki geçersiz: {u['etki']!r}")
                if u.get("gecerli") is not None and u["gecerli"] not in GECERLI:
                    b.append(yer + f" gecerli geçersiz: {u['gecerli']!r}")
                if u.get("tarih") is not None and not tarih_mi(u["tarih"]):
                    b.append(yer + " tarih YYYY-AA-GG değil")
                kapatan = kapatan or (u.get("etki") == "kapatir" and u.get("gecerli") == "evet")
        if kapatan and isinstance(d, dict) and d.get("deger") != "kapali":
            b.append(on + "geçerli ve rotayı kapatan uyarı var ama durum 'kapali' değil")

        kay = r.get("kaynaklar")
        if not isinstance(kay, list) or not kay or not all(url_mi(x) for x in kay):
            b.append(on + "kaynaklar adres listesi değil ya da boş")
        else:
            eksik = sorted(_adresler(r) - set(kay))
            if eksik:
                b.append(on + f"kaynaklar listesinde olmayan adres: {eksik[0]}")
    if osm and "OpenStreetMap" not in atif:
        b.append("atif: OSM değeri kullanılıyor ama OpenStreetMap atfı yok")
    return b


def durum_etkin(r: dict, gun: date) -> str:
    """Seçim anındaki durum: denetim DURUM_GECERLILIK_GUN günden eskiyse 'acik' etiketi 'bilinmiyor' sayılır.
    'kapali' eskise de kapalı kalır (yeniden açıldığı kaynakla doğrulanana kadar)."""
    d = r.get("durum") or {}
    deger = d.get("deger", "bilinmiyor")
    if deger == "kapali":
        return "kapali"
    if any(u.get("etki") == "kapatir" and u.get("gecerli") == "evet" for u in r.get("uyarilar") or []):
        return "kapali"
    if deger == "acik" and tarih_mi(d.get("kontrol")) \
            and 0 <= (gun - date.fromisoformat(d["kontrol"])).days <= DURUM_GECERLILIK_GUN:
        return "acik"
    return "bilinmiyor"


def secilebilir(veri: dict | None = None, gun: date | None = None) -> list[dict]:
    """O gün paylaşılabilecek rotalar. Veri bulguluysa hiçbir rota seçilmez (yanlış sayı paylaşmaktansa paylaşma)."""
    veri = yukle() if veri is None else veri
    gun = gun or common.now().date()
    if dogrula(veri):
        return []
    out = []
    for r in veri["rotalar"]:
        if durum_etkin(r, gun) == "kapali" or r.get("mesafe_km") is None:
            continue
        if gun.month in KIS_AYLARI and r["kis_uygun"]["deger"] == "hayir":
            continue
        out.append(r)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tarih", help="YYYY-AA-GG: o gün seçilebilir rotaları listele")
    ap.add_argument("--dosya", default=str(DOSYA))
    a = ap.parse_args(argv)
    if a.tarih and not tarih_mi(a.tarih):
        print("HATA: --tarih YYYY-AA-GG olmalı", file=sys.stderr)
        return 2
    veri = yukle(Path(a.dosya))
    bulgu = dogrula(veri)
    for s in bulgu:
        print("BULGU: " + s)
    gun = date.fromisoformat(a.tarih) if a.tarih else common.now().date()
    sec = secilebilir(veri, gun)
    print(f"ROTA: {len(veri.get('rotalar') or [])} rota, {len(bulgu)} bulgu · {gun.isoformat()} için seçilebilir {len(sec)}")
    if a.tarih:
        for r in sec:
            print(f"  {r['id']}: {r['mesafe_km']['deger']} km · durum {durum_etkin(r, gun)} · kış {r['kis_uygun']['deger']}")
    return 1 if bulgu else 0


if __name__ == "__main__":
    sys.exit(main())
