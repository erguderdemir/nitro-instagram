#!/usr/bin/env python3
"""İki takvim sürümünü kayıt bazında, ortak ataya göre (3 yollu) birleştir (Actions'ta push yarışında).

Aynı anda iki iş main'e yazınca git satır bazında çakışır ya da birinin yayın durumu kaybolur; kaybolan
'published' durumu sonraki çalışmada aynı paylaşımın ikinci kez yayınlanmasına yol açar. Bu betik:
  - içeriği tek taraftan alır (--base): plan görevinde kendi yeni takvimimiz, yayın görevinde uzak main;
  - yayın durumu alanlarını ve Suite bayrağını, ortak ataya göre hangi taraf değiştirdiyse ondan alır
    (bilerek yapılan geri almalar da korunur); iki taraf da değiştirdiyse "daha ilerlemiş" durum
    (published > error/missed/skipped > kapsayıcısı kurulmuş > denenmiş > hiç) kazanır, eşitlikte bizimki,
    bayrakta VEYA;
  - Suite'te zamanlanmış hâli diğer taraftan gelen kaydın içeriğini de oradan alır (Suite o içeriği yayınlar);
    iki tarafta da zamanlanmışsa içeriği, ataya göre yalnız diğer taraf değiştirdiyse oradan alır;
  - yalnız bir tarafta olan kaydı, ata yoksa (yeni eklenmiş) ya da durumu değişmişse korur;
  - sonucu data/calendar.json'a yazar ve sayfaları (bio, simülasyon, takvim, Suite listesi) yeniden üretir.

  python scripts/takvim_birlestir.py BIZIM.json UZAK.json --base ours|theirs [--ata ATA.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

STATE = ("status", "via", "error", "media_id", "permalink", "published_at", "container_id", "attempts")
ICERIK_DISI = set(STATE) | {"suite_scheduled"}


def icerik(c: dict | None) -> str | None:
    """Kaydın yayın durumu ve Suite bayrağı dışındaki içeriği (karşılaştırma için)."""
    return json.dumps({k: v for k, v in c.items() if k not in ICERIK_DISI}, sort_keys=True) if c else None


def rank(c: dict) -> int:
    st = c.get("status")
    if st == "published":
        return 4
    if st in ("error", "missed", "skipped"):
        return 3
    if c.get("container_id"):
        return 2
    return 1 if isinstance(c.get("attempts"), int) and c["attempts"] > 0 else 0


def load(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("items", [])


def durum(c: dict | None) -> tuple:
    return tuple(json.dumps(c.get(k), sort_keys=True) for k in STATE) if c else ()


def merge(base: list[dict], other: list[dict], ata: list[dict] | None = None, base_ours: bool = True) -> list[dict]:
    """base: içeriği alınacak taraf; other: diğer taraf; ata: ortak ata (yoksa 2 yollu kurala düşer)."""
    by_id = {c.get("id"): c for c in other}
    anc = {c.get("id"): c for c in (ata or [])}
    seen = set()
    out = []
    for c in base:
        cid = c.get("id")
        o, a = by_id.get(cid), anc.get(cid)
        seen.add(cid)
        if o is None:
            out.append(c)
            continue
        fa, fb, fo = bool((a or {}).get("suite_scheduled")), bool(c.get("suite_scheduled")), bool(o.get("suite_scheduled"))
        if a is not None:
            flag = fo if fb == fa else (fb if fo == fa else (fb or fo))
        else:
            flag = fb or fo
        if flag and fo and not fb:
            # Suite'te zamanlanan diğer taraftaki hâl: Suite onu yayınlayacak, içerik de ondan gelsin.
            if (o.get("fp"), o.get("sticker")) != (c.get("fp"), c.get("sticker")):
                print(f"UYARI: {cid} Suite'te zamanlanmış hâliyle korunuyor; bu taraftaki yeniden kurulum atıldı.")
            c = dict(o)
        else:
            if fb and fo and a is not None and icerik(c) == icerik(a) != icerik(o):
                # İki tarafta da Suite'te zamanlanmış; içeriği yalnız diğer taraf değiştirmiş (Suite'te elle
                # yeniden planlanan kayıt): içerik oradan gelsin, yayın durumu aşağıdaki kuralla birleşsin.
                st = {k: c[k] for k in STATE if k in c}
                c = {k: v for k, v in o.items() if k not in STATE}
                c.update(st)
            if a is not None:
                bchg, ochg = durum(c) != durum(a), durum(o) != durum(a)
            else:
                bchg = ochg = True
            if ochg and not bchg:
                al = True
            elif ochg and bchg:
                al = rank(o) > rank(c) or (rank(o) == rank(c) and not base_ours)
            else:
                al = False
            if al:
                for k in STATE:
                    if k in o:
                        c[k] = o[k]
                    else:
                        c.pop(k, None)
        if flag:
            c["suite_scheduled"] = True
        else:
            c.pop("suite_scheduled", None)
        out.append(c)
    extra = []
    for o in other:
        cid = o.get("id")
        if cid in seen:
            continue
        a = anc.get(cid)
        if ata is None:
            keep = rank(o) > 0 or o.get("suite_scheduled")
        else:  # atada yoksa diğer taraf yeni eklemiş; varsa içerik tarafı silmiş, durumu ilerlediyse yine koru
            keep = a is None or durum(o) != durum(a) or bool(o.get("suite_scheduled"))
        if keep:
            extra.append(o)
    if extra:
        out.extend(extra)
        out.sort(key=lambda c: (str(c.get("date")), str(c.get("time")), str(c.get("id"))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ours")
    ap.add_argument("theirs")
    ap.add_argument("--base", choices=("ours", "theirs"), required=True)
    ap.add_argument("--ata", help="ortak atadaki takvim (git merge-base); yoksa 2 yollu birleştirme")
    a = ap.parse_args()
    ours, theirs = load(a.ours), load(a.theirs)
    ata = None
    if a.ata:
        try:
            ata = load(a.ata)
        except (OSError, ValueError) as e:
            print(f"UYARI: ata takvimi okunamadı ({e}); 2 yollu birleştiriliyor.")
    if a.base == "ours":
        cal = merge(ours, theirs, ata, base_ours=True)
    else:
        cal = merge(theirs, ours, ata, base_ours=False)
    common.save_calendar(cal)
    print(f"Takvim birleştirildi: {len(cal)} kayıt (içerik: {'bizim' if a.base == 'ours' else 'uzak'} sürüm, "
          f"{'3' if ata is not None else '2'} yollu).")
    import publish  # noqa: E402  (ağır modül: yalnız gerektiğinde)
    publish.build_pages(cal)
    try:  # Suite listesi publish.PAGES'te yok; birleşen bayraklar sayfada da görünsün
        import suite  # noqa: E402
        suite.build_suite(cal)
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Suite sayfası üretilemedi: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
