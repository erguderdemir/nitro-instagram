#!/usr/bin/env python3
"""Her ürün için nitrobisiklet.com aramasında o ürünü TEK sonuç olarak bulan kısa terimi bulur.

Instagram profil linki nitrobisiklet.com'dur; sitenin araması (/ara/?q=) N-kodlarını tanımaz. Açıklama ve
görsellerdeki "Nasıl alırım?" yönlendirmesi bu yüzden ürün kodu yerine buradaki doğrulanmış terimi kullanır.

Arama, ürün adında büyük/küçük harf duyarsız alt dize eşleşmesi yapar. Terim, ad içindeki ardışık kelime
pencerelerinden seçilir (önce kısa, sonra baştan başlayan); canlı aramada yalnız o ürünü döndüren ilk pencere
alınır. Bulunamazsa SKU (tekse), o da olmazsa ürünü ilk sırada döndüren (≤3 sonuç), o da olmazsa ürünü
içeren ≤2 sonuçlu pencere kullanılır (adı başka ürünün adının öneki olan ürünler: "… 2'li Set").

Sonuç data/arama.json: {slug: {"q": terim, "n": sonuç sayısı, "ad": ürün adı, "t": tarih}}.
Ad değişen ya da terimi olmayan ürünler yeniden denenir; site erişilemezse eldeki kayıtlar korunur.

  python3 scripts/arama.py            # terimi olmayan / adı değişen ürünler
  python3 scripts/arama.py --yenile   # hepsini yeniden doğrula
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DOSYA = common.DATA / "arama.json"
ARA = "https://nitrobisiklet.com/ara/?q="
MAX_KELIME = 5


def yukle() -> dict:
    return common.read_json(DOSYA, {})


def terim(p: dict, tablo: dict | None = None) -> str:
    """Ürünün doğrulanmış arama terimi; kayıt yoksa ya da ad değiştiyse ürün adının kendisi (alt dize olarak
    kendisiyle her zaman eşleşir)."""
    k = (yukle() if tablo is None else tablo).get(p.get("slug") or "")
    if k and k.get("ad") == p.get("name") and k.get("q"):
        return k["q"]
    return p.get("name") or ""


@lru_cache(maxsize=None)
def ara(q: str) -> tuple[str, ...]:
    import scrape  # noqa: E402  (get: urllib, sertifika sorununda curl)
    sayfa = scrape.get(ARA + urllib.parse.quote(q))
    return tuple(dict.fromkeys(re.findall(r'href="/urun/([^/"]+)/', sayfa)))


def _temiz(w: list[str]) -> str | None:
    q = " ".join(w).strip(" ,;:()[]-–/")
    if len(q) < 4 or not re.search(r"\w", q):
        return None
    if q.count("(") != q.count(")") or q.count('"') % 2:
        return None  # yarım parantez / tırnak: yazması zor, eşleşmesi kırılgan
    return q


def adaylar(ad: str) -> list[str]:
    w = ad.split()
    out = []
    for n in range(1, min(MAX_KELIME, len(w)) + 1):
        for i in range(0, len(w) - n + 1):
            q = _temiz(w[i:i + n])
            if q is None or (n == 1 and (len(q) < 4 or not re.search(r"\d", q) and len(q) < 6)):
                continue
            if q not in out:
                out.append(q)
    return out


def bul(p: dict) -> dict | None:
    slug, ad, sku = p["slug"], p.get("name") or "", p.get("sku")
    ilk = iki = None
    try:
        for q in adaylar(ad):
            r = ara(q)
            if r == (slug,):
                return {"q": q, "n": 1}
            if ilk is None and r[:1] == (slug,) and len(r) <= 3:
                ilk = {"q": q, "n": len(r)}
            if iki is None and slug in r and len(r) <= 2:
                iki = {"q": q, "n": len(r)}  # ör. adı "… 2'li Set" ürününün önekiyse tek sonuç imkânsız
        if sku and ara(sku) == (slug,):
            return {"q": sku, "n": 1}
        return ilk or iki
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: {slug} aranamadı: {e}", file=sys.stderr)
        return None


def guncelle(prods: list[dict], yenile: bool = False) -> dict:
    tablo = yukle()
    is_ = [p for p in prods if p.get("slug") and p.get("name") and (
        yenile or (tablo.get(p["slug"]) or {}).get("ad") != p["name"])]
    bugun = date.today().isoformat()
    with ThreadPoolExecutor(6) as ex:
        for p, r in zip(is_, ex.map(bul, is_)):
            if r:
                tablo[p["slug"]] = {**r, "ad": p["name"], "t": bugun}
            elif yenile:
                tablo.pop(p["slug"], None)
    canli = {p["slug"] for p in prods}
    tablo = {k: v for k, v in sorted(tablo.items()) if k in canli}
    common.write_json(DOSYA, tablo)
    eksik = [p["slug"] for p in prods if p["slug"] not in tablo]
    print(f"Arama terimi: {len(is_)} ürün denendi, {len(tablo)}/{len(prods)} doğrulanmış"
          + (f"; doğrulanamayan {len(eksik)}: {', '.join(eksik[:10])}" if eksik else ""))
    return tablo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yenile", action="store_true")
    a = ap.parse_args()
    guncelle(common.load_products(), a.yenile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
