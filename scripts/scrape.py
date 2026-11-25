#!/usr/bin/env python3
"""nitrobisiklet.com ürünlerini sitemap üzerinden çekip data/products.json'a yazar.

Kullanım:  python3 scripts/scrape.py
Yalnızca standart kütüphane kullanır. Siteye nazik olmak için istekler arası bekler.
"""
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://nitrobisiklet.com"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "products.json"
UA = "Mozilla/5.0 (NitroInstagramPlanner)"


def get(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        # python.org kurulumlarında sertifika deposu eksik olabilir: sistem curl'ünü kullan
        out = subprocess.run(["curl", "-sSfL", "-m", "25", "-A", UA, url],
                             capture_output=True, check=True)
        return out.stdout.decode("utf-8", "replace")


def text_lines(page: str) -> list[str]:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [l.strip() for l in t.split("\n") if l.strip()]


def parse_price(s: str) -> float | None:
    m = re.search(r"([\d.]+(?:,\d+)?)\s*₺", s)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def parse(url: str, page: str) -> dict:
    meta = lambda p: (re.search(rf'property="{p}" content="([^"]*)"', page) or [None, None])[1]
    lines = text_lines(page)

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    name = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else meta("og:title")

    eyebrow = re.search(r't-eyebrow[^"]*">\s*([^<]+)', page)
    cat, cond, sku = None, None, None
    if eyebrow:
        parts = [p.strip() for p in html.unescape(eyebrow.group(1)).split("·")]
        cat = parts[0] if parts else None
        cond = parts[1] if len(parts) > 1 else None
        sku = parts[2].replace("SKU", "").strip() if len(parts) > 2 else None

    # Fiyat bloğu: ilk border-y bloğundaki tüm ₺ değerleri
    block = re.search(r'border-y border-line py-5">(.*?)</div>', page, re.S)
    prices = [parse_price(m) for m in re.findall(r">([^<]*₺)<", block.group(1))] if block else []
    prices = [p for p in prices if p]
    price = min(prices) if prices else None
    old_price = max(prices) if len(prices) > 1 and max(prices) > min(prices) else None

    stock = None
    m = re.search(r"Bu üründen son\D{0,40}(\d+)\D{0,10}adet", page, re.S)
    if m:
        stock = int(m.group(1))
    out_of_stock = bool(re.search(r"(Bu ürün şu an tükendi|Stokta yok|Gelince haber ver)", page, re.I))

    specs = {}
    if "Teknik döküm" in lines:
        i = lines.index("Teknik döküm") + 1
        while i + 1 < len(lines) and len(specs) < 40:
            k, v = lines[i], lines[i + 1]
            if len(k) > 40 or k in ("Açıklama", "Benzer ürünler", "İlgili ürünler", "Yorumlar"):
                break
            specs[k] = v
            i += 2

    crumbs = []
    nav = re.search(r'aria-label="(?:Breadcrumb|breadcrumb|Konum)"(.*?)</nav>', page, re.S)
    if nav:
        crumbs = [c for c in text_lines(nav.group(1)) if c != "/"]

    imgs = []
    for src in re.findall(r'(?:src|data-src|href)="(/media/product/[^"]+)"', page):
        u = BASE + src
        if u not in imgs:
            imgs.append(u)
    og = meta("og:image")
    if og and og not in imgs:
        imgs.insert(0, og)

    return {
        "url": url,
        "slug": url.rstrip("/").split("/")[-1],
        "name": name,
        "category": cat,
        "condition": cond,
        "sku": sku,
        "breadcrumbs": crumbs,
        "price": price,
        "old_price": old_price,
        "stock_left": stock,
        "in_stock": not out_of_stock,
        "description": html.unescape(meta("og:description") or ""),
        "specs": specs,
        "images": imgs,
    }


def fetch(url: str) -> dict | None:
    for attempt in range(3):
        try:
            time.sleep(0.25)
            return parse(url, get(url))
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"HATA {url}: {e}", file=sys.stderr)
            time.sleep(2)
    return None


def durum_yaz(**alan) -> None:
    """data/tarama.json: son başarılı tarama zamanı ve son hata (gorev.py alarmı okur)."""
    yol = ROOT / "data" / "tarama.json"
    try:
        d = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.update(alan)
    yol.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    sm = get(BASE + "/sitemap.xml")
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", sm) if "/urun/" in u]
    print(f"{len(urls)} ürün bulundu, çekiliyor…")
    with ThreadPoolExecutor(max_workers=4) as ex:
        products = [p for p in ex.map(fetch, urls) if p]
    try:
        onceki = len(json.loads(OUT.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        onceki = 0
    # Kısmi tarama (site yavaş/erişilemez): eksik ürünler 'kaldırıldı' sanılıp kayıtlar toplu yeniden kurulmasın.
    # Ölçüt sitemap'teki ürün sayısıdır (gerçek katalog küçülmesi geçer); sitemap'in kendisi yarıdan fazla
    # küçüldüyse bozuk/eksik sitemap sayılır. Engellenen tarama data/tarama.json'a yazılır; 48 saat başarısız
    # kalırsa gorev.py alarmı verir.
    if not urls or len(products) < 0.9 * len(urls) or (onceki and len(urls) < 0.5 * onceki):
        msg = (f"UYARI: kısmi tarama ({len(products)}/{len(urls)} ürün çekildi, sitemap {len(urls)}, önceki {onceki}); "
               "yazılmadı, eldeki ürün verisiyle devam.")
        durum_yaz(son_hata=msg)
        sys.exit(msg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(products, ensure_ascii=False, indent=1), encoding="utf-8")
    durum_yaz(son_basari=datetime.now(timezone.utc).isoformat(timespec="seconds"), urun=len(products), son_hata="")
    print(f"{len(products)} ürün yazıldı: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
