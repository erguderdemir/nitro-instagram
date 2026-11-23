#!/usr/bin/env python3
"""Takvimdeki paylaşımları tek sayfada gösterir: out/onizleme.html (yalnızca yerel inceleme için).

Kullanım:  python3 scripts/onizleme.py
"""
import html
from datetime import date

import content
from plan import GUN, ROOT, item_dt, load_calendar

DURUM = {"planned": "planlandı", "draft": "taslak", "published": "yayında", "error": "hata",
         "missed": "atlandı", "skipped": "iptal"}


def main() -> None:
    cal = sorted(load_calendar(), key=item_dt)
    days, cur = [], None
    for c in cal:
        if c["date"] != cur:
            cur = c["date"]
            d = date.fromisoformat(cur)
            days.append(f'<h2>{d.strftime("%d.%m.%Y")} · {GUN[d.weekday()]}</h2><div class="row">')
        cap = (f'<details><summary>Açıklama</summary><pre>{html.escape(c["caption"])}</pre></details>'
               if c["caption"] else f'<p class="hook">“{html.escape(c.get("hook", ""))}”</p>')
        days.append(
            f'<div class="item {c["type"]}"><a href="../docs/{c["image"]}" target="_blank">'
            f'<img src="../docs/{c["image"]}" loading="lazy"></a>'
            f'<div class="meta"><span class="tag">{c["time"]} · {"POST" if c["type"] == "post" else "STORY"}</span>'
            f'<span class="st {c["status"]}">{DURUM.get(c["status"], c["status"])}</span></div>'
            f'<a class="name" href="{html.escape(c["link"])}" target="_blank">{html.escape(c["name"])}</a>'
            f'<b>{content.fmt_price(c["price"])}</b><code>{c["id"]}</code>{cap}</div>')
        nxt = cal.index(c) + 1
        if nxt == len(cal) or cal[nxt]["date"] != cur:
            days.append("</div>")
    posts = sum(c["type"] == "post" for c in cal)
    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Instagram önizleme</title>
<style>
body{{margin:0;background:#f1ede2;font-family:system-ui,sans-serif;color:#14150f}}
header{{background:#14150f;color:#f1ede2;padding:20px 28px}} header h1{{margin:0;font-size:22px}}
header p{{margin:6px 0 0;color:#a8b78a}} main{{padding:8px 28px 40px}}
h2{{font-size:16px;margin:28px 0 12px;color:#a8480a;letter-spacing:.04em}}
.row{{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}}
.item{{background:#fff;border-radius:14px;padding:10px;width:230px;box-shadow:0 2px 0 #14150f1a}}
.item img{{width:100%;border-radius:8px;display:block}} .item.post{{outline:3px solid #f5821f}}
.meta{{display:flex;justify-content:space-between;margin:8px 0 4px;font-size:12px}}
.tag{{font-weight:700}} .st{{padding:1px 8px;border-radius:99px;background:#eee}}
.st.published{{background:#a8b78a}} .st.error,.st.missed{{background:#f5821f;color:#fff}}
.name{{display:block;font-weight:600;color:inherit;font-size:14px;line-height:1.3}}
b{{display:block;color:#a8480a;margin:4px 0}} code{{font-size:11px;color:#6b6658}}
.hook{{font-size:13px;color:#6b6658;margin:6px 0 0}}
details{{margin-top:6px;font-size:13px}} pre{{white-space:pre-wrap;font:12px/1.45 system-ui;background:#f7f5ef;padding:8px;border-radius:8px}}
</style></head><body>
<header><h1>Nitro Bisiklet · Instagram önizleme</h1>
<p>{len(cal)} paylaşım · {posts} post · {len(cal) - posts} story · turuncu çerçeve = post.
İptal için: data/calendar.json içinde ilgili id'nin status değerini "skipped" yap.</p></header>
<main>{''.join(days)}</main></body></html>"""
    out = ROOT / "out" / "onizleme.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
