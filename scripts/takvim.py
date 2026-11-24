#!/usr/bin/env python3
"""İnsan okunur takvim: docs/TAKVIM.md (GitHub'da doğrudan okunur; iş akışı yalnız data/ ve docs/ klasörlerini kaydeder).

  python3 scripts/takvim.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import common
from common import DOCS, GUN, fmt_price, item_dt

OUT = DOCS / "TAKVIM.md"
TUR = {"carousel": "Carousel", "reel": "Reel", "image": "Görsel", "story": "Story"}
TEMA = {"urun": "ürün", "ipucu": "ipucu", "liste": "liste", "servis": "servis", "marka": "marka", "promo": "tanıtım",
        "etkilesim": "soru"}
DURUM = {"planned": "planlı", "draft": "taslak", "published": "yayında", "skipped": "iptal", "missed": "kaçtı",
         "error": "hata"}


def _cell(s: str) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def build_takvim(cal: list[dict], out: Path | None = None) -> Path:
    out = out or OUT
    live = common.CFG.get("live") is True
    rows = sorted(cal, key=item_dt)
    lines = ["# Instagram içerik takvimi", "",
             "Otomatik üretilir (`scripts/plan.py`); elle düzenleme bir sonraki çalışmada silinir.",
             f"Yayın kilidi: **{'AÇIK (live=true)' if live else 'KAPALI (live=false) — hiçbir şey yayınlanmaz'}**. "
             "Görsel önizleme: [simülasyon](https://erguderdemir.github.io/nitro-instagram/onizleme/). "
             "Bir paylaşımı iptal etmek için kimliğini `data/iptal.txt` dosyasına yaz.", ""]
    cur = None
    for c in rows:
        if c["date"] != cur:
            cur = c["date"]
            d = date.fromisoformat(cur)
            lines += ["", f"## {d.strftime('%d.%m.%Y')} {GUN[d.weekday()]}", "",
                      "| Saat | Tür | Başlık | Ürün | Fiyat | Kanal | Durum | Görsel |", "|---|---|---|---|---|---|---|---|"]
        ps = c.get("products") or []
        name = ps[0]["name"] + (f" +{len(ps) - 1}" if len(ps) > 1 else "") if ps else "—"
        price = fmt_price(ps[0]["price"]) if len(ps) == 1 else "—"
        prod = f"[{_cell(name)}]({c['link']})" if c.get("link") and ps else _cell(name)
        kanal = "Suite + link" if c.get("channel") == "suite" else "API"
        lines.append(f"| {c['time']} | {TUR.get(c['format'], c['format'])} · {TEMA.get(c['theme'], c['theme'])} "
                     f"| {_cell(c.get('title') or '')} | {prod} | {price} | {kanal} "
                     f"| {DURUM.get(c['status'], c['status'])} | [görsel]({c['cover']}) |")
    posts = [c for c in rows if c["type"] == "post"]
    if posts:
        lines += ["", "---", "", "# Post açıklamaları", ""]
        for c in posts:
            lines += [f"### {c['date']} {c['time']} · {c.get('title') or ''}", "", "```", c.get("caption") or "", "```", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build_takvim(common.load_calendar()))
