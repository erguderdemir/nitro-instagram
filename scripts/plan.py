#!/usr/bin/env python3
"""İçerik takvimini oluşturur: ürün seçer, görselleri ve açıklamaları üretir, bio sayfasını yazar.

Kullanım:  python3 scripts/plan.py [--start YYYY-MM-DD] [--days N]
Mevcut takvimdeki kayıtlara dokunmaz; yalnızca boş slotları doldurur.
"""
import argparse
import html
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import content
from render import render

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
TZ = timezone(timedelta(hours=CFG["timezone_offset_hours"]))
CAL = ROOT / "data" / "calendar.json"
DOCS = ROOT / "docs"
MEDIA = DOCS / "media"
GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def load_calendar() -> list[dict]:
    return json.loads(CAL.read_text()) if CAL.exists() else []


def save_calendar(cal: list[dict]) -> None:
    cal.sort(key=lambda x: (x["date"], x["time"], x["type"]))
    CAL.parent.mkdir(parents=True, exist_ok=True)
    CAL.write_text(json.dumps(cal, ensure_ascii=False, indent=1), encoding="utf-8")


def eligible(p: dict) -> bool:
    return bool(p.get("price")) and p.get("in_stock", True) and bool(p.get("images"))


def candidates(products: list[dict], group: str, month: int) -> list[dict]:
    if group == "sezon":
        cats = set(content.SEASONAL.get(month, []))
        return [p for p in products if p["category"] in cats]
    return [p for p in products if content.group_of(p["category"]) == group]


def choose(products, groups, day: date, slot: str, last_used: dict, taken: set) -> dict | None:
    rng = random.Random(f"{day}{slot}")
    limit = day - timedelta(days=CFG["repeat_after_days"])
    recent = day - timedelta(days=4)  # aynı kategori 4 gün içinde tekrar gelmesin
    for g in groups:
        pool = [p for p in candidates(products, g, day.month) if p["slug"] not in taken]
        fresh = [p for p in pool if last_used.get(content.family(p), date.min) < limit]
        if fresh:
            rng.shuffle(fresh)
            # hiç paylaşılmamış ürünlere öncelik
            fresh.sort(key=lambda p: (last_used.get("cat:" + p["category"], date.min) >= recent,
                                      last_used.get(content.family(p), date.min)))
            return fresh[0]
    # hepsi yakın zamanda kullanıldıysa en eski kullanılanı al
    pool = [p for g in groups for p in candidates(products, g, day.month) if p["slug"] not in taken]
    return min(pool, key=lambda p: last_used.get(content.family(p), date.min)) if pool else None


def plan(start: date, days: int) -> list[dict]:
    products = [p for p in json.loads((ROOT / "data" / "products.json").read_text()) if eligible(p)]
    by_slug = {p["slug"]: p for p in products}
    cal = load_calendar()
    existing = {c["id"] for c in cal}
    last_used = {}
    for c in cal:
        d = date.fromisoformat(c["date"])
        # Yayınlanmamış (kaçırılan/iptal/hatalı) kayıtlar ürünü 60 gün kilitlemesin
        if c["slug"] in by_slug and c["status"] in ("planned", "draft", "published"):
            f = content.family(by_slug[c["slug"]])
            last_used[f] = max(last_used.get(f, date.min), d)
            k = "cat:" + c["category"]
            last_used[k] = max(last_used.get(k, date.min), d)

    new = []
    for i in range(days):
        day = start + timedelta(days=i)
        taken = {c["slug"] for c in cal + new if c["date"] == str(day)}
        post_today = None
        slots = [("post", s) for s in CFG["posts"] if s["weekday"] == day.weekday()]
        slots += [("story", s) for s in CFG["stories"]]
        for kind, s in slots:
            sid = f"{day}-{kind}-{s['time'].replace(':', '')}"
            if sid in existing:
                if kind == "post":
                    post_today = by_slug.get(next(c["slug"] for c in cal if c["id"] == sid))
                continue
            groups = s["groups"]
            kicker_hook = None
            if groups[0] == "ayni_gun_post" and post_today:
                p = post_today
                kicker_hook = ("AKIŞTA YENİ", "Yeni gönderiye <em>göz at</em>")
            else:
                p = choose(products, [g for g in groups if g != "ayni_gun_post"], day, sid, last_used, taken)
            if not p:
                continue
            taken.add(p["slug"])
            last_used[content.family(p)] = day
            last_used["cat:" + p["category"]] = day
            if kind == "post":
                post_today = p
            stamp = day.strftime("%Y%m%d")
            item = {
                "id": sid, "date": str(day), "time": s["time"], "type": kind,
                "slug": p["slug"], "name": content.display_name(p), "price": p["price"], "category": p["category"],
                "link": content.utm_url(p, "social", kind, stamp),
                "bio_link": content.utm_url(p, "bio", kind, stamp),
                "image": f"media/{sid}.jpg",
                "caption": content.caption(p, str(day)) if kind == "post" else "",
                "status": "planned" if CFG["auto_publish"] else "draft",
            }
            kicker, hook = kicker_hook or content.story_hook(p, str(day), sid)
            render(p, kind, DOCS / item["image"], hook=hook, kicker=kicker)
            item["hook"] = html.unescape(hook.replace("<em>", "").replace("</em>", ""))
            new.append(item)
            print(f"{sid}  {p['name'][:60]}")
    cal += new
    save_calendar(cal)
    return cal


# ---- Çıktılar ----------------------------------------------------------------------------------

def item_dt(c: dict) -> datetime:
    return datetime.fromisoformat(f"{c['date']}T{c['time']}").replace(tzinfo=TZ)


def build_bio(cal: list[dict], now: datetime | None = None) -> None:
    """Instagram bio linki için: yayınlanmış ürünler, en yenisi en üstte."""
    now = now or datetime.now(TZ)
    seen, rows = set(), []
    for c in sorted(cal, key=item_dt, reverse=True):
        if c["slug"] in seen or item_dt(c) > now or c["status"] != "published":
            continue
        seen.add(c["slug"])
        rows.append(c)
        if len(rows) == 30:
            break
    cards = "\n".join(
        f'<a class="card" href="{html.escape(c["bio_link"])}"><img src="{c["image"]}" loading="lazy" alt="">'
        f'<div><b>{html.escape(c["name"])}</b><span>{content.fmt_price(c["price"])}</span><i>Satın al →</i></div></a>'
        for c in rows)
    page = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Nitro Bisiklet · Instagram ürünleri</title>
<meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@800&family=Barlow:wght@500;700&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#f1ede2;font-family:Barlow,system-ui,sans-serif;color:#14150f}}
header{{background:#14150f;color:#f1ede2;padding:22px 18px;text-align:center}}
header img{{height:84px}} header p{{margin:8px 0 0;color:#a8b78a;font-size:15px}}
main{{max-width:520px;margin:0 auto;padding:16px}}
.btn{{display:block;text-align:center;background:#f5821f;color:#14150f;font:800 18px Archivo,sans-serif;
 padding:16px;border-radius:999px;text-decoration:none;margin:0 0 16px}}
.btn.alt{{background:transparent;border:2px solid #14150f}}
.card{{display:flex;gap:14px;align-items:center;background:#fff;border-radius:18px;padding:10px;margin:0 0 12px;
 text-decoration:none;color:inherit;box-shadow:0 2px 0 #14150f1a}}
.card img{{width:96px;height:120px;object-fit:cover;border-radius:12px}}
.card b{{display:block;font-size:16px;line-height:1.25}} .card span{{display:block;color:#a8480a;font-weight:700;margin:6px 0}}
.card i{{font-style:normal;font-weight:700;color:#f5821f}}
.foot{{text-align:center;font-size:13px;margin-top:28px}} .foot a{{color:#6b6658}}
h2{{font:800 15px Archivo,sans-serif;letter-spacing:.12em;color:#6b6658;margin:22px 4px 12px}}
</style></head><body>
<header><img src="logo.png" alt="Nitro Bisiklet"><p>Köyceğiz · Bisiklet satış ve servis</p></header>
<main>
<a class="btn" href="https://nitrobisiklet.com/magaza/?utm_source=instagram&utm_medium=bio&utm_campaign=magaza">Tüm ürünler · Mağaza</a>
<a class="btn alt" href="https://nitrobisiklet.com/servis/?utm_source=instagram&utm_medium=bio&utm_campaign=servis">Servis randevusu al</a>
<h2>INSTAGRAM'DA GÖRDÜĞÜN ÜRÜNLER</h2>
{cards or '<p>Yakında burada.</p>'}
<p class="foot"><a href="gizlilik.html">Gizlilik</a> · <a href="veri-silme.html">Veri silme</a></p>
</main></body></html>"""
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    logo = ROOT / "assets" / "logo.png"
    if logo.exists():
        (DOCS / "logo.png").write_bytes(logo.read_bytes())


def build_takvim(cal: list[dict]) -> None:
    """İnsan okunur takvim: TAKVIM.md"""
    out = ["# Instagram içerik takvimi", "", "Otomatik üretilir (`scripts/plan.py`). Bir paylaşımı iptal etmek için "
           "`data/calendar.json` içinde `status` değerini `skipped` yap.", ""]
    cur = None
    for c in sorted(cal, key=item_dt):
        if c["date"] != cur:
            cur = c["date"]
            d = date.fromisoformat(cur)
            out += ["", f"## {d.strftime('%d.%m.%Y')} {GUN[d.weekday()]}", "",
                    "| Saat | Tür | Ürün | Fiyat | Durum | Görsel |", "|---|---|---|---|---|---|"]
        tur = "Post" if c["type"] == "post" else "Story"
        out.append(f"| {c['time']} | {tur} | [{c['name']}]({c['link']}) | {content.fmt_price(c['price'])} "
                   f"| {c['status']} | [görsel](docs/{c['image']}) |")
    posts = [c for c in sorted(cal, key=item_dt) if c["type"] == "post"]
    if posts:
        out += ["", "---", "", "# Post açıklamaları", ""]
        for c in posts:
            out += [f"### {c['date']} {c['time']} · {c['name']}", "", "```", c["caption"], "```", ""]
    (ROOT / "TAKVIM.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=datetime.now(TZ).date() + timedelta(days=1))
    ap.add_argument("--days", type=int, default=CFG["plan_days_ahead"])
    a = ap.parse_args()
    cal = plan(a.start, a.days)
    build_bio(cal)
    build_takvim(cal)
    print(f"Takvimde {len(cal)} kayıt. TAKVIM.md ve docs/index.html güncellendi.")
