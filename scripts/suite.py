#!/usr/bin/env python3
"""Business Suite için story listesi: docs/suite/index.html

Instagram API'si story'ye link çıkartması ekleyemez. Linkli story'ler (channel=suite) Meta Business Suite'te elle
planlanır: görsel yüklenir, "Bağlantı" çıkartması görseldeki kesik çizgili yuvaya konur. Bu sayfa önümüzdeki günlerin
listesini verir: saat, indirilecek görsel, çıkartmaya girilecek adres ve metin.

Suite'te planlanan kayıt için data/calendar.json içinde "suite_scheduled": true yapılır; yapılmazsa aynı story
saatinde API ile "Link profilde" sürümüyle (yedek) yayınlanır. Yayın kilidi kapalıyken hiçbir şey yayınlanmaz.

  python3 scripts/suite.py [gün sayısı]      listeyi yazdırır ve sayfayı üretir
"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timedelta
from pathlib import Path

import common
from common import DOCS, item_dt, tr_date

OUT = DOCS / "suite" / "index.html"
DAYS = 8


def upcoming(cal: list[dict], now: datetime | None = None, days: int = DAYS) -> list[dict]:
    now = now or common.now()
    rows = [c for c in cal if c.get("channel") == "suite" and c.get("status") in ("planned", "draft")
            and c.get("sticker") and now < item_dt(c) <= now + timedelta(days=days)]
    return sorted(rows, key=item_dt)


def build_suite(cal: list[dict], now: datetime | None = None, out: Path | None = None, days: int = DAYS) -> Path:
    now, out = now or common.now(), out or OUT
    rows, live = upcoming(cal, now, days), common.CFG.get("live") is True
    E = lambda s: html.escape(str(s), quote=True)
    cards, cur = [], None
    for c in rows:
        if c["date"] != cur:
            cur = c["date"]
            cards.append(f"<h2>{E(tr_date(item_dt(c)))}</h2>")
        st = c["sticker"]
        done = "<span class='ok'>Suite'te planlandı</span>" if c.get("suite_scheduled") else "<span class='todo'>Planlanacak</span>"
        cards.append(
            f"<div class='c'><a href='../{E(c['media_link'])}' download><img src='../{E(c['media_link'])}' loading='lazy' alt=''></a>"
            f"<div><b>{E(c['time'])} · {E(c.get('title') or '')}</b> {done}"
            f"<p>{E((c.get('products') or [{}])[0].get('name') or c.get('kicker') or '')}</p>"
            f"<label>Çıkartma metni</label><code>{E(st['text'])}</code>"
            f"<label>Bağlantı</label><code class='u'>{E(st['url'])}</code>"
            f"<button onclick=\"navigator.clipboard.writeText('{E(st['url'])}');this.textContent='Kopyalandı'\">Bağlantıyı kopyala</button> "
            f"<a class='dl' href='../{E(c['media_link'])}' download>Görseli indir</a>"
            f"<small>{E(c['id'])}</small></div></div>")
    lock = ("" if live else "<p class='lock'>Yayın kilidi KAPALI (live=false). Sahibi simülasyonu onaylamadan Business Suite'te "
            "hiçbir şey planlanmaz; bu liste yalnız hazırlıktır.</p>")
    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NITRO · Business Suite story listesi</title>
<meta name="robots" content="noindex"><link rel="stylesheet" href="../fonts/fonts.css">
<style>body{{margin:0;background:#f1ede2;font-family:Barlow,system-ui,sans-serif;color:#14150f}}
main{{max-width:760px;margin:0 auto;padding:18px}}h1{{font:800 26px Archivo,sans-serif;margin:8px 0}}
h2{{font:800 15px Archivo,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:#6b6658;margin:26px 0 10px}}
.lock{{background:#14150f;color:#f1ede2;border-radius:14px;padding:14px 16px}}
ol{{padding-left:20px;line-height:1.5}}
.c{{display:flex;gap:16px;background:#fff;border-radius:18px;padding:12px;margin:0 0 12px}}
.c img{{width:120px;border-radius:10px;display:block}}.c div{{min-width:0;flex:1}}.c p{{margin:4px 0 8px;color:#6b6658}}
label{{display:block;font:700 11px 'Space Mono',monospace;letter-spacing:.1em;text-transform:uppercase;color:#6b6658;margin-top:6px}}
code{{display:block;background:#f1ede2;border-radius:8px;padding:6px 8px;font-size:13px;word-break:break-all}}
button,.dl{{display:inline-block;margin-top:10px;font:700 14px Barlow,sans-serif;padding:9px 14px;border-radius:999px;border:0;background:#f5821f;color:#14150f;text-decoration:none}}
.dl{{background:#14150f;color:#f1ede2}}small{{display:block;margin-top:8px;color:#a39d8c;font-size:11px}}
.ok{{color:#2a7a2a;font-weight:700}}.todo{{color:#a8480a;font-weight:700}}</style></head><body><main>
<h1>Business Suite · linkli story listesi</h1>{lock}
<ol><li>Görseli indir (kesik çizgili yuvası olan sürüm).</li>
<li>Business Suite → İçerik → Hikâye oluştur → görseli yükle, tarihi ve saati gir.</li>
<li>“Bağlantı” çıkartmasını ekle: bağlantıyı yapıştır, metni yaz, çıkartmayı yuvanın üstüne yerleştir.</li>
<li>Planladıktan sonra o kaydın <code style="display:inline">suite_scheduled</code> alanını <code style="display:inline">true</code> yap; yapılmazsa story aynı saatte API ile “Link profilde” sürümüyle yayınlanır.</li></ol>
{''.join(cards) or '<p>Önümüzdeki günlerde planlanacak linkli story yok.</p>'}
<p><small>Üretim: {now:%d.%m.%Y %H:%M} · önümüzdeki {days} gün · {len(rows)} story</small></p></main></body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DAYS
    cal = common.load_calendar()
    for c in upcoming(cal, days=n):
        print(f"{c['date']} {c['time']}  docs/{c['media_link']}\n    metin: {c['sticker']['text']}\n    link:  {c['sticker']['url']}")
    print(build_suite(cal, days=n))
