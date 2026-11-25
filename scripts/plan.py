#!/usr/bin/env python3
"""İçerik takvimini üretir ve günceller (şema v2): ürün seçer, görselleri ve reel'leri çizer, sayfaları yazar.

  python3 scripts/plan.py                takvimi tamamla; gelecekteki kayıtlarda fiyat/stok değişimini yenile
  python3 scripts/plan.py --yeniden      gelecekteki bütün planlı kayıtları baştan seç ve çiz
  python3 scripts/plan.py --kuru         görsel çizmeden yalnız seçimi ve metni üret (Chrome gerekmez; sınama için)

Her gün çalışır (04:10 TR). Dokunmadığı kayıtlar: yayınlanmış/atlanmış/hatalı olanlar ve zamanı gelmiş olanlar.
Gelecekteki planlı kayıtta ürün stoktan çıktıysa yeni ürün seçilir; fiyatı ya da adı değiştiyse aynı ürünle yeniden
çizilir; şablon ya da metin kodu değiştiyse (parmak izi) yine yeniden çizilir.

Sıra: önce listeler (tek ürünlü kuralları onlar ayırır), sonra gün gün post ve story'ler. Önce post kareleri çizilir;
20:30 tanıtım story'si günün postunun kapak görselini gömer. Kuralı sağlanamayan içerik üretilmez (yeri boş kalır).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import arama
import common
import content as C
from common import CFG, DATA, DOCS, MEDIA, ROOT, THUMBS, fmt_price

SCHEMA = 2
REEL_TMP = ROOT / "cache" / "reel"
YENIDEN = DATA / "yeniden.txt"      # bu dosya varsa gelecekteki kayıtlar baştan seçilir, sonra dosya silinir
LEAD = timedelta(hours=1)           # bu kadar yakın kayıtlara dokunulmaz
ACTIVE = ("planned", "draft", "published")
STICKER_TEXTS = ("ÜRÜNE GİT", "FİYATI GÖR", "MAĞAZAYA GİT", "SERVİS RANDEVUSU AL")
VARIANTS = ("cream", "olive", "ink")


def _version() -> str:
    """Şablon ve metin kodunun parmak izi: değişince gelecekteki kayıtlar aynı ürünle yeniden çizilir."""
    h = hashlib.md5()
    for name in ("render.py", "content.py", "plan.py", "reel.py"):
        h.update((ROOT / "scripts" / name).read_bytes())
    return h.hexdigest()[:10]


VERSION = _version()


def md5(*parts) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()


def _kok(url: str) -> str:
    """Adresin UTM'siz, çapasız kökü: iki linkin aynı sayfaya gidip gitmediğini karşılaştırmak için."""
    return (url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _site_mi(url: str | None) -> bool:
    """Hedef link yalnız nitrobisiklet.com olabilir (github.io bio sayfası post/story linki olmaz)."""
    return bool(url) and url.startswith(common.SITE + "/")


class Planner:
    def __init__(self, now: datetime, start: date, end: date, reset: bool = False, dry: bool = False):
        self.now, self.start, self.end, self.reset, self.dry = now, start, end, reset, dry
        self.products = common.load_products()
        self.by_slug = {p["slug"]: p for p in self.products}
        self.codes = common.load_codes()
        self.arama = arama.yukle()   # slug -> nitrobisiklet.com'da ürünü tek bulan terim (scripts/arama.py)
        self.site = common.load_site()
        self.tips = common.load_tips()
        # Kategori sayfasına giden çıkartmanın metni: ipucu story'lerinde kullanılan (denetimden geçen) metinler
        self.kat_st = {t["link"]: t["st"] for t in self.tips.get("story_tips", []) if t.get("link") and t.get("st")}
        # Bu tarihten itibaren mevcut kilitsiz kayıtlara da yeni seçim kuralları uygulanır (need_specs, ±1 gün alt tür);
        # öncesindeki kayıtların ürünü korunur (Suite'te taslağı ya da kilitli tanıtım story'si var).
        self.kural_bas = date.fromisoformat(CFG.get("yeni_kural_baslangic", "2026-12-24"))
        self.rule_id = {p["slug"]: (r["id"] if (r := C.rule_of(p)) else None) for p in self.products}
        self.eligible = [p for p in self.products if C.eligible(p)]
        self.cal = [c for c in common.load_calendar() if c.get("schema") == SCHEMA]
        self._img: dict[str, list] = {}
        self.post_jobs: list[tuple[str, Path]] = []
        self.story_jobs: list[tuple[str, Path]] = []
        self.reels: list[tuple[list[Path], Path, Path]] = []
        self.thumbs: list[tuple[Path, Path]] = []
        self.touched: set[str] = set()
        self._kalsin: dict[str, bool] = {}
        self.log: list[str] = []
        self.ensure_codes()

    # ---- yardımcılar ---------------------------------------------------------------------------

    def say(self, msg: str) -> None:
        if msg.startswith("UYARI") and msg in self.log:  # state() aynı kayıt için birden çok kez sorulabilir
            return
        print(msg, flush=True)
        self.log.append(msg)

    def ensure_codes(self) -> None:
        """Kodu olmayan (siteye yeni eklenmiş) ürüne sıradaki kısa kodu ver. Verilen kod hiç değişmez."""
        nums = [int(v[1:]) for v in self.codes.values() if v[:1] == "N" and v[1:].isdigit()]
        nxt, added = (max(nums) if nums else 100) + 1, 0
        for p in self.products:
            if p["slug"] not in self.codes:
                self.codes[p["slug"]] = f"N{nxt}"
                nxt, added = nxt + 1, added + 1
        if added and not self.dry:
            common.write_json(DATA / "codes.json", dict(sorted(self.codes.items())))
            self.say(f"{added} yeni ürüne kod verildi.")

    def get(self, sid: str) -> dict | None:
        return next((c for c in self.cal if c["id"] == sid), None)

    def drop(self, sid: str, force: bool = False) -> None:
        """Kaydı takvimden çıkar. Business Suite'te zamanlanmış kayıt (ör. postla birlikte yenilenen tanıtım
        story'si) silinmez: bayraksız yeniden kurulursa Suite eski hâlini, API de yenisini yayınlar (çift story)."""
        if not force and any(c["id"] == sid and c.get("suite_scheduled") for c in self.cal):
            return
        self.cal = [c for c in self.cal if c["id"] != sid]

    def settled(self, c: dict) -> bool:
        """Kayıt bu çalışmada kesinleşti mi (yenilendi ya da olduğu gibi kalacak)? Yenilenecek kayıtların eski
        başlık/ref'i seçimi saptırmasın diye çeşitlilik sayımları yalnız kesinleşmiş kayıtlara bakar."""
        if c["id"] in self.touched:
            return True
        if c["id"] not in self._kalsin:
            self._kalsin[c["id"]] = self.state(c) == "kalsin"
        return self._kalsin[c["id"]]

    def put(self, rec: dict) -> None:
        self.drop(rec["id"], force=True)
        self.cal.append(rec)
        self.touched.add(rec["id"])

    def uses(self, skip: str | None = None):
        """(tarih, slug, aile, kural): tanıtım story'leri dışındaki etkin kayıtların ürünleri."""
        for c in self.cal:
            if c["id"] == skip or c.get("status") not in ACTIVE or c.get("theme") == "promo":
                continue
            d = date.fromisoformat(c["date"])
            for x in c.get("products") or []:
                yield d, x["slug"], x.get("family") or x["slug"], x.get("rule")

    def free(self, p: dict, day: date, skip: str | None = None) -> bool:
        """Ürün (ve renk/ölçü ailesi) tekrar penceresi içinde başka kayıtta kullanılmamış mı?"""
        fam, win = C.family(p), CFG["repeat_after_days"]
        return not any((s == p["slug"] or f == fam) and abs((d - day).days) < win for d, s, f, _ in self.uses(skip))

    def rule_distance(self, rid: str, day: date, posts: bool = False) -> int:
        """Kuralın en yakın kullanımına gün uzaklığı (posts=True: yalnız postlardaki kullanımlar)."""
        ds = []
        for c in self.cal:
            if c.get("status") in ACTIVE and c.get("theme") != "promo" and (c["type"] == "post" or not posts):
                ds += [abs((date.fromisoformat(c["date"]) - day).days) for x in c.get("products") or [] if x.get("rule") == rid]
        return min(min(ds), 28) if ds else 28

    def yeni_kural(self, day: date) -> bool:
        return day >= self.kural_bas

    def kilitli_ref(self, sid: str) -> bool:
        """Bu kayda bağlı, Business Suite'te zamanlanmış (kilitli) bir tanıtım story'si var mı?"""
        return any(x.get("suite_scheduled") and x.get("ref") == sid for x in self.cal)

    def komsu_kurallar(self, day: date, skip: str | None = None, sabit: bool = False) -> set[str]:
        """±1 gün içindeki post ve story'lerin (tanıtım hariç) alt türleri (kural kimlikleri).

        sabit=True: yalnız bu çalışmada artık yer değiştirmeyecek komşular (önceki günler, kilitli ya da
        yayınlanmış kayıtlar); sonraki günün kilitsiz kaydı zaten bu kayıttan kaçınarak yeniden seçilir."""
        out = set()
        for c in self.cal:
            if c["id"] == skip or c.get("status") not in ACTIVE or c.get("theme") == "promo":
                continue
            d = date.fromisoformat(c["date"])
            if abs((d - day).days) > 1:
                continue
            if sabit and not (d < day or c.get("suite_scheduled") or c.get("status") == "published"):
                continue
            out.update(x["rule"] for x in c.get("products") or [] if x.get("rule"))
        return out

    def post_sec(self, rules: list[str], day: date, sid: str, avoid: set[str], reel: bool = False):
        """Post ürünü: önce ≥3 teknik özellikli ve komşu günlerle alt türü çakışmayan ürün. Havuz yetmezse eski
        davranışa (özelliksiz ürün / çakışma serbest) düşülür ve bu loglanır. Reel'de özellik şartı gevşemez."""
        steps = [(3, avoid), (3, frozenset())] + ([] if reel else [(0, avoid), (0, frozenset())])
        for need, av in steps:
            p = self.choose(rules, day, sid, need_specs=need, avoid=av, post=True)
            if not p:
                continue
            if need < 3:
                self.say(f"UYARI: {sid}: havuzda ≥3 teknik özellikli boş ürün yok; özelliksiz ürüne düşüldü "
                         f"({p['slug']}).")
            if avoid and not av and self.rule_id[p["slug"]] in avoid:
                self.say(f"UYARI: {sid}: ±1 günde aynı alt tür ({self.rule_id[p['slug']]}) kaçınılmaz oldu.")
            return p
        return None

    def images(self, p: dict) -> list:
        """Ürünün tasarımda kullanılabilir fotoğrafları (hazırlanmış). Kuru çalışmada indirme yapılmaz."""
        if p["slug"] not in self._img:
            if self.dry:
                self._img[p["slug"]] = [{"kind": "white", "bg": "#ffffff", "w": 1000, "h": 1000, "path": Path("/x.png")}
                                        for _ in p["images"][:3]]
            else:
                import render
                infos = [render.prep(u) for u in p["images"][:4]]
                self._img[p["slug"]] = [i for i in infos if render.image_ok(i)] if render.image_ok(infos[0]) else []
        return self._img[p["slug"]]

    def q(self, p: dict) -> str:
        """Açıklama ve görsellerde 'aramaya yaz' denecek terim (profil linki nitrobisiklet.com; site N-kodunu tanımaz)."""
        return arama.terim(p, self.arama)

    def view(self, p: dict) -> dict:
        return {"name": C.short_name(p), "price": fmt_price(p["price"]), "code": self.codes[p["slug"]], "q": self.q(p),
                "cat": C.cat_label(p["category"]), "img": self.images(p)[0]}

    def prod(self, p: dict, sid: str, theme: str, medium: str) -> dict:
        r = C.rule_of(p)
        return {"slug": p["slug"], "name": C.display_name(p), "price": p["price"], "code": self.codes[p["slug"]],
                "q": self.q(p), "category": p["category"], "rule": r["id"], "label": r["label"], "family": C.family(p),
                "link": C.utm(p["url"], medium, theme, sid), "bio_link": C.utm(p["url"], "bio", theme, sid),
                "image": p["images"][0]}

    def fp(self, slugs: list[str], extra: str = "") -> str:
        parts = [VERSION, extra]
        for s in slugs:
            p = self.by_slug.get(s) or {}
            parts.append(f"{s}:{p.get('price')}:{p.get('name')}:{self.codes.get(s)}:{self.q(p) if p else ''}")
        return md5(*parts)[:12]

    def title_for(self, rule: dict, day: date, seed: str, keep: str | None = None, force: bool = False) -> str:
        opts = C.headlines(rule, day.month)
        # Başlık tüm takvimde ne kadar az kullanıldıysa o seçilir (aynı başlık farklı günlerde tekrar etmesin)
        counts = {h: sum(1 for c in self.cal if c.get("headline") == h and c.get("theme") != "promo"
                         and c["id"] != seed and self.settled(c)) for h in opts}
        if keep and keep in opts and (force or counts[keep] == min(counts.values())):
            return keep
        low = min(counts.values())
        return C.pick([h for h in opts if counts[h] == low], seed)

    def choose(self, rules: list[str], day: date, sid: str, need_specs: int = 0, avoid: set[str] = frozenset(),
               post: bool = False):
        """Havuzdaki kurallardan, en uzun süredir kullanılmamış olanın en zengin içerikli boş ürününü seç.

        Postlarda önce postlar arası çeşitlilik (aynı alt tür art arda gelmesin), sonra story'lerle yakınlık gözetilir.
        """
        k = 0 if post else day.toordinal() % max(1, len(rules))
        rot = rules[k:] + rules[:k]
        gap = CFG.get("rule_gap_days", 6)
        order = sorted((r for r in rot if r not in avoid),
                       key=lambda r: (-(self.rule_distance(r, day, True) if post else 0),
                                      -min(self.rule_distance(r, day), gap if post else 28), rot.index(r)))
        for rid in order:
            cands = [p for p in self.eligible if self.rule_id[p["slug"]] == rid and self.free(p, day, sid)]
            if need_specs:
                cands = [p for p in cands if len(C.clean_specs(p)) >= need_specs]
            cands.sort(key=lambda p: (-(min(len(p["images"]), 3) + 2 * (len(C.clean_specs(p)) >= 3)), md5(sid, p["slug"])))
            for p in cands:
                if self.images(p):
                    return p
        return None

    def rec(self, sid: str, day: date, tm: str, typ: str, fmt: str, theme: str, **kw) -> dict:
        base = {"schema": SCHEMA, "id": sid, "date": str(day), "time": tm, "type": typ, "format": fmt, "theme": theme,
                "kicker": "", "title": "", "headline": "", "hook": "", "media": [], "cover": "", "thumb": f"media/t/{sid}.jpg",
                "caption": "", "alt": "", "alts": [], "products": [], "link": "", "bio_link": "", "code": "",
                "channel": "api", "sticker": None, "media_link": "", "ref": "", "rule": "",
                "status": "planned" if CFG.get("auto_publish", True) else "draft", "fp": ""}
        base.update(kw)
        base["title"] = C.plain(base["headline"]) if base["headline"] else base["title"]
        return base

    def frames(self, sid: str, sections: list[str], story: bool = False) -> list[str]:
        """Kareleri çizim kuyruğuna ekle; docs/ köküne göreli yolları döndür."""
        rels = [f"media/{sid}-{i}.jpg" for i in range(1, len(sections) + 1)]
        (self.story_jobs if story else self.post_jobs).extend((s, DOCS / r) for s, r in zip(sections, rels))
        return rels

    # ---- postlar -------------------------------------------------------------------------------

    def product_carousel(self, sid: str, day: date, tm: str, slot: dict, p: dict, keep: str | None = None,
                         force: bool = False) -> dict:
        import render as R
        rule = C.rule_of(p)
        v, code = self.view(p), self.codes[p["slug"]]
        kicker = C.MEVSIM_KICKER.get(day.month, slot["kicker"]) if slot.get("pool") == "mevsim" else slot["kicker"]
        head = self.title_for(rule, day, sid, keep, force)
        rows, desc, extra = C.clean_specs(p, 6), C.description(p), self.images(p)[1:3]
        mid = [("gal", i) for i in extra]
        mid += [("specs", rows)] if len(rows) >= 3 else ([("detail", desc)] if desc else [])
        n = len(mid) + 3
        sec = [R.p_cover(v, kicker, head, C.pick(VARIANTS, sid))]
        alts = [C.product_alt(p, head)]
        for i, (kind, val) in enumerate(mid, 2):
            if kind == "gal":
                sec.append(R.p_gallery(v, val, i, n))
                alts.append(f"{C.display_name(p)}: ürün fotoğrafı.")
            elif kind == "specs":
                sec.append(R.p_specs(v, val, i, n))
                alts.append("Teknik özellikler: " + "; ".join(f"{k}: {x}" for k, x in val) + ".")
            else:
                sec.append(R.p_detail(v, val, i, n))
                alts.append("Ürün detayı: " + val)
        sec += [R.p_why(C.perks(p), n - 1, n), R.p_cta("urun", n, n, q=v["q"])]
        alts += ["Neden NITRO: " + "; ".join(f"{t}, {C.tr_lower(s[:1])}{s[1:]}" for _, t, s in C.perks(p)) + ".",
                 f"Nasıl alırım: profildeki nitrobisiklet.com linkine dokun, aramaya “{v['q']}” yaz."]
        media = self.frames(sid, sec)
        cap, hook = C.product_caption(p, v["q"], rule, str(day), onceki=self.cal)
        x = self.prod(p, sid, "urun", "social")
        return self.rec(sid, day, tm, "post", "carousel", "urun", kicker=kicker, headline=head, hook=hook, media=media,
                        cover=media[0], caption=cap, alt=alts[0], alts=[a[:1000] for a in alts], products=[x],
                        link=x["link"], bio_link=x["bio_link"], code=code, rule=rule["id"], fp=self.fp([p["slug"]]))

    def reel(self, sid: str, day: date, tm: str, slot: dict, p: dict, keep: str | None = None,
             force: bool = False) -> dict:
        import render as R
        rule = C.rule_of(p)
        v, code = self.view(p), self.codes[p["slug"]]
        head = self.title_for(rule, day, sid, keep, force)
        sec = [R.r_hook(v, slot["kicker"], head), R.r_hero(v), R.r_specs(v, C.clean_specs(p, 3)),
               R.r_perks(C.perks(p)[:3]), R.r_cta(v)]
        tmp = [REEL_TMP / f"{sid}-{i}.jpg" for i in range(1, 6)]
        self.post_jobs.extend(zip(sec, tmp))
        mp4, cover = f"media/{sid}.mp4", f"media/{sid}-kapak.jpg"
        self.reels.append((tmp, DOCS / mp4, DOCS / cover))
        cap, hook = C.product_caption(p, v["q"], rule, str(day), onceki=self.cal)
        x = self.prod(p, sid, "urun", "social")
        return self.rec(sid, day, tm, "post", "reel", "urun", kicker=slot["kicker"], headline=head, hook=hook,
                        media=[mp4], cover=cover, caption=cap, alt=C.product_alt(p, head), alts=[C.product_alt(p, head)],
                        products=[x], link=x["link"], bio_link=x["bio_link"], code=code, rule=rule["id"],
                        fp=self.fp([p["slug"]]))

    def list_post(self, sid: str, day: date, tm: str, list_id: str, items: list[dict]) -> dict:
        import render as R
        cfg = C.LISTS[list_id]
        xs = [self.prod(p, sid, "liste", "social") for p in items]
        title, sub = C.list_title(list_id, xs), C.list_sub(list_id, xs)   # eşik sağlanmıyorsa ValueError
        views = [self.view(p) for p in items]
        n = len(items) + 2
        sec = [R.l_cover(cfg["kicker"], title, sub, views)]
        sec += [R.l_item(v, k, k + 1, n, "cream" if k % 2 else "olive", label=x["label"])
                for k, (v, x) in enumerate(zip(views, xs), 1)]
        sec.append(R.p_cta("magaza", n, n))
        media = self.frames(sid, sec)
        lst = {"id": list_id, "items": xs, "hook": cfg["hook"], "q": cfg["q"], "tags": cfg["tags"]}
        cap, hook = C.list_caption(lst, gun=str(day), onceki=self.cal)
        store = self.site["urls"]["magaza"]
        alts = [f"{C.LISTS[list_id].get('konu') or 'Bisiklet aksesuarı'}: {C.plain(title)}. {sub}"] + [f"{k}. {x['name']}, {fmt_price(x['price'])}, sitede ara: “{x['q']}”."
                                                for k, x in enumerate(xs, 1)]
        alts.append("Hepsi profildeki nitrobisiklet.com linkinde: karttaki ARA terimini aramaya yaz.")
        return self.rec(sid, day, tm, "post", "carousel", "liste", kicker=cfg["kicker"], headline=title, hook=hook,
                        media=media, cover=media[0], caption=cap, alt=alts[0], alts=alts, products=xs,
                        link=C.utm(store, "social", "liste", sid), bio_link=C.utm(store, "bio", "liste", sid),
                        ref=list_id, rule=f"liste:{list_id}", fp=self.fp([p["slug"] for p in items], list_id))

    def tip_post(self, sid: str, day: date, tm: str, tip: dict) -> dict:
        import render as R
        steps = tip["steps"]
        n = len(steps) + 3
        servis = tip.get("cta") == "servis"
        sec = [R.t_cover(tip["kicker"], tip["title"], tip["intro"], len(steps))]
        sec += [R.t_step(s["h"], s["t"], k, len(steps), k + 1, n, "cream" if k % 2 else "olive")
                for k, s in enumerate(steps, 1)]
        sec += [R.t_end(tip["takeaway"], n - 1, n),
                R.p_cta("servis" if servis else ("cocuk" if tip.get("cta") == "cocuk" else "ipucu"), n, n,
                        phone=self.site.get("phone", ""))]
        media = self.frames(sid, sec)
        cap, hook = C.tip_caption(tip, gun=str(day), onceki=self.cal)
        cocuk = tip.get("cta") == "cocuk"
        url = (self.site["service"]["booking_url"] if servis else
               self.site["urls"]["categories"].get("Çocuk Bisikleti", self.site["urls"]["magaza"]) if cocuk else
               self.site["urls"]["magaza"])
        alts = [("Çocuk bisikleti: " if cocuk else "Bisiklet bakımı: " if servis else "Bisiklet ipucu: ") + (tip.get("alt") or f"{tip['title']}. {tip['intro']}")]
        alts += [f"{k}. {s['h']}: {s['t']}" for k, s in enumerate(steps, 1)]
        alts += [f"Özetle: {tip['takeaway']}", "Servis randevusu için profildeki linke dokun." if servis
                 else "Çocuk bisikletleri profildeki linkte." if cocuk
                 else "İhtiyacın olan parça ve aksesuarlar profildeki linkte."]
        return self.rec(sid, day, tm, "post", "carousel", "ipucu", kicker=tip["kicker"], title=tip["title"], hook=hook,
                        media=media, cover=media[0], caption=cap, alt=alts[0][:1000], alts=[a[:1000] for a in alts],
                        link=C.utm(url, "social", "ipucu", sid), bio_link=C.utm(url, "bio", "ipucu", sid),
                        ref=tip["id"], rule=C.RULE_IPUCU, cta="servis" if servis else "cocuk" if cocuk else "magaza",
                        fp=self.fp([], md5(tip["id"], tip["title"], tip["caption"], *[s["t"] for s in steps])))

    def newyear_post(self, sid: str, day: date, tm: str) -> dict:
        import render as R
        year = day.year + 1
        media = self.frames(sid, [R.b_newyear(year, "Yeni yılda da satış ve servis için Köyceğiz'deyiz.")])
        cap, hook = C.newyear_caption(year, gun=str(day), onceki=self.cal)
        store = self.site["urls"]["magaza"]
        alt = f"Bisiklet mağazası: Mutlu yıllar. {year} bol kilometreli bir yıl olsun. NITRO Bisiklet, Köyceğiz."
        return self.rec(sid, day, tm, "post", "image", "marka", kicker="Mutlu yıllar", title=f"Mutlu yıllar {year}",
                        hook=hook, media=media, cover=media[0], caption=cap, alt=alt, alts=[alt],
                        link=C.utm(store, "social", "marka", sid), bio_link=C.utm(store, "bio", "marka", sid),
                        ref="yilbasi", rule=C.RULE_YILBASI, fp=self.fp([], f"yilbasi{year}"))

    # ---- story'ler -----------------------------------------------------------------------------

    def suite_story(self, sid: str, sections: tuple[str, str]) -> tuple[list[str], str]:
        """Linkli story iki sürüm çizilir: API yedeği ('Link profilde') ve çıkartma yuvalı Suite sürümü."""
        media, link = f"media/{sid}.jpg", f"media/{sid}-link.jpg"
        self.story_jobs += [(sections[0], DOCS / media), (sections[1], DOCS / link)]
        return [media], link

    def product_story(self, sid: str, day: date, tm: str, p: dict, keep: str | None = None) -> dict:
        import render as R
        rule, kicker = C.rule_of(p), CFG["stories"]["urun"]["kicker"]
        v, code = self.view(p), self.codes[p["slug"]]
        head = self.title_for(rule, day, sid, keep)
        var = C.pick(("cream", "olive"), sid)
        media, mlink = self.suite_story(sid, (R.s_product(v, kicker, head, False, var), R.s_product(v, kicker, head, True, var)))
        x = self.prod(p, sid, "urun", "story")
        text = "ÜRÜNE GİT"
        return self.rec(sid, day, tm, "story", "story", "urun", kicker=kicker, headline=head, media=media, cover=media[0],
                        alt=C.product_alt(p, head), products=[x], link=x["link"], bio_link=x["bio_link"], code=code,
                        channel="suite", sticker={"url": x["link"], "text": text, **R.STICKER}, media_link=mlink,
                        rule=rule["id"], fp=self.fp([p["slug"]]))

    def carousel_tip(self, tid: str | None) -> dict | None:
        return next((t for t in self.tips.get("carousels", []) if t["id"] == tid), None) if tid else None

    def kategori_hedefi(self, cat: str | None) -> tuple[str, str, str, str] | None:
        """Kategori sayfası (data/site.json urls.categories). Çıkartma metni ipucu story'lerindeki kategori
        metnidir; o kategori için metin yoksa 'MAĞAZAYA GİT' (kategori sayfası mağazanın içindedir)."""
        url = self.site["urls"]["categories"].get(cat or "")
        if not _site_mi(url):
            return None
        return url, self.kat_st.get(cat, "MAĞAZAYA GİT"), "Benzerlerini görmek için dokun", f"Link profilde<u>·</u>{cat}"

    def tanitim_hedefi(self, post: dict) -> tuple[str, str, str, str] | None:
        """20:30 tanıtım story'sinin hedefi: aynı günün postundan FARKLI bir nitrobisiklet.com sayfası
        (post linkiyle yarışmasın). Ürün: carousel'in 2. ürünü (stokta) ya da ürünün kategori sayfası;
        ipucu: tips.json cta_url; liste: listedeki en kalabalık kategorinin sayfası; yılbaşı: iletişim/adres."""
        theme, ps = post["theme"], post.get("products") or []
        if theme == "urun" and ps:
            p2 = self.by_slug.get(ps[1]["slug"]) if len(ps) > 1 else None
            if p2 and C.eligible(p2) and _site_mi(p2["url"]):
                return p2["url"], "ÜRÜNE GİT", "Ürüne gitmek için dokun", "Ürüne git"
            p = self.by_slug.get(ps[0]["slug"]) or {}
            return self.kategori_hedefi(p.get("category") or ps[0].get("category"))
        if theme == "liste" and ps:
            cats = [x.get("category") for x in ps if x.get("category")]
            cnt = Counter(cats)
            for cat in sorted(cnt, key=lambda k: (-cnt[k], cats.index(k))):
                if hedef := self.kategori_hedefi(cat):
                    return hedef
            return None
        if theme == "ipucu":
            tip = self.carousel_tip(post.get("ref")) or {}
            url, st = tip.get("cta_url"), tip.get("cta_st")
            if not _site_mi(url) or not st:
                return None
            label = "Mağazaya gitmek için dokun" if st == "MAĞAZAYA GİT" else "Ürünleri görmek için dokun"
            return url, st, label, f"Link profilde<u>·</u>{st}"
        if theme == "marka":
            u = self.site["urls"]
            return (u["iletisim"], "ADRES VE İLETİŞİM", "Adres ve yol tarifi için dokun",
                    "Link profilde<u>·</u>İletişim") if _site_mi(u.get("iletisim")) else None
        return None

    def promo_story(self, sid: str, day: date, tm: str, post: dict, kicker: str = "", yonlendir: bool = False) -> dict:
        """Postun story duyurusu. yonlendir=True (20:30 tanıtım): link postla aynı sayfaya değil tanitim_hedefi'ne
        gider. utm_campaign postun teması (urun/ipucu/liste/marka); 'promo' kampanyası yazılmaz."""
        import render as R
        kicker = kicker or CFG["stories"]["tanitim"]["kicker"]
        theme = post["theme"]
        store, cover = self.site["urls"]["magaza"], DOCS / post["cover"]
        if theme == "urun":
            x = post["products"][0]
            head, url, text = post["headline"], self.by_slug[x["slug"]]["url"], "ÜRÜNE GİT"
            label, fallback = "Ürüne gitmek için dokun", "Ürüne git"
        elif theme == "ipucu":
            # Konuya özgü başlık (tips.json story_baslik); yoksa genel başlık
            head = (self.carousel_tip(post.get("ref")) or {}).get("story_baslik") or "Yeni rehber <em>akışta</em>"
            if post.get("cta") == "servis":
                url, text = self.site["service"]["booking_url"], "SERVİS RANDEVUSU AL"
                label, fallback = "Randevu almak için dokun", "Link profilde<u>·</u>Servis randevusu"
            elif post.get("cta") == "cocuk":
                url = self.site["urls"]["categories"].get("Çocuk Bisikleti", store)
                text, label, fallback = "ÇOCUK BİSİKLETLERİ", "Çocuk bisikletleri için dokun", "Link profilde<u>·</u>Çocuk bisikletleri"
            else:
                url, text, label, fallback = store, "MAĞAZAYA GİT", "Mağazaya gitmek için dokun", "Link profilde<u>·</u>Mağaza"
        elif theme == "liste":
            head, url, text = post["headline"], store, "MAĞAZAYA GİT"
            label, fallback = "Mağazaya gitmek için dokun", "Mağazaya git"
        else:
            head, url, text = "Mutlu <em>yıllar!</em>", store, "MAĞAZAYA GİT"
            label, fallback = "Mağazaya gitmek için dokun", "Link profilde<u>·</u>Mağaza"
        if yonlendir:
            hedef = self.tanitim_hedefi(post)
            if hedef and _kok(hedef[0]) != _kok(post.get("link") or url):
                url, text, label, fallback = hedef
            else:
                self.say(f"UYARI: {sid}: tanıtım story'si için postundan farklı bir hedef bulunamadı; postun linkine gidiyor.")
        camp = theme   # utm_campaign = postun teması (eskiden sabit "promo")
        link = C.utm(url, "story", camp, sid)
        mock = None
        p0 = self.by_slug.get(post["products"][0]["slug"]) if theme == "urun" and post.get("format") == "carousel" \
            and post.get("products") else None
        if p0 and self.images(p0):
            # Post kapağı ARA satırı taşır; story'de ARA yazmasın diye kart için ARA'sız kopya çizilir
            # (post kareleriyle birlikte, story'lerden önce; cache/ altında kalır, docs/'a girmez).
            mock = REEL_TMP.parent / "mock" / f"{sid}.jpg"
            self.post_jobs.append((R.p_cover(self.view(p0), post["kicker"], post["headline"],
                                             C.pick(VARIANTS, post["id"]), ara=False), mock))
        media, mlink = self.suite_story(sid, (R.s_promo(cover, kicker, head, False, label, fallback, mock=mock),
                                              R.s_promo(cover, kicker, head, True, label, fallback, mock=mock)))
        prods = [dict(x, link=C.utm(self.by_slug[x["slug"]]["url"], "story", camp, sid),
                      bio_link=C.utm(self.by_slug[x["slug"]]["url"], "bio", camp, sid)) for x in post["products"]]
        return self.rec(sid, day, tm, "story", "story", "promo", kicker=kicker, headline=head, media=media, cover=media[0],
                        alt=C.cumle(f"Bugünün gönderisi: {post['title']}"), products=prods, link=link,
                        bio_link=C.utm(url, "bio", camp, sid), code=post.get("code", ""), channel="suite",
                        sticker={"url": link, "text": text, **R.STICKER}, media_link=mlink, ref=post["id"],
                        rule=post["rule"], fp=md5(VERSION, post["fp"])[:12])

    def value_story(self, sid: str, day: date, tm: str, kind: str) -> dict | None:
        import render as R
        refs = [c["ref"] for c in self.cal if c.get("ref") and c["id"] != sid and self.settled(c)]
        used, m = set(refs), day.month
        if kind == "ipucu":
            pool = [t for t in self.tips.get("story_tips", []) if C.in_season(t["h"] + " " + t["t"], m)]
            t = next((t for t in pool if "ipucu:" + md5(t["h"])[:8] not in used), None)
            if not t:
                return None
            ref, title = "ipucu:" + md5(t["h"])[:8], t["h"]
            var, alt = C.pick(("olive", "ink"), sid), f"İpucu: {C.cumle(t['h'])} {t['t']}"
            target = self.tip_target(t)
            if not target:
                sec = R.s_tip("İpucu", t["h"], t["t"], var)
                rec = self._value(sid, day, tm, "ipucu", sec, title, alt, ref, C.RULE_IPUCU, md5(t["h"], t["t"]))
            else:
                url, text, label, fallback = target
                media, mlink = self.suite_story(sid, (R.s_tip("İpucu", t["h"], t["t"], var, (False, label, fallback)),
                                                      R.s_tip("İpucu", t["h"], t["t"], var, (True, label, fallback))))
                rec = self._linked_value(sid, day, tm, "ipucu", media, mlink, title, alt, ref, C.RULE_IPUCU,
                                         md5(VERSION, t["h"], t["t"], url, text), url, text, "ipucu")
            rec["kicker"] = "İpucu"
            return rec
        if kind == "soru":
            pool = [q for q in self.tips.get("questions", []) if C.in_season(q, m)]
            q = next((q for q in pool if "soru:" + md5(q)[:8] not in used), None)
            if not q:
                return None
            rec = self._value(sid, day, tm, "etkilesim", R.s_question(q), q, f"Soru: {q}", "soru:" + md5(q)[:8],
                              C.RULE_SORU, md5(q))
            rec["kicker"] = "Soru"
            return rec
        variants = C.service_facts(self.site) if kind == "servis" else C.brand_facts(self.site)
        tag = "servis" if kind == "servis" else "marka"
        k = next((i for i in range(len(variants)) if f"{tag}:{i}" not in used), None)
        if k is None:
            k = sum(1 for r in refs if r.startswith(tag + ":")) % len(variants)
        f = variants[k]
        chip = "Servis" if kind == "servis" else "NITRO"
        url, text, label, fallback = self.fact_target(kind, f["kicker"])
        variant = "ink" if kind == "servis" else "olive"
        media, mlink = self.suite_story(sid, (R.s_facts(chip, f["kicker"], f["title"], f["facts"], False, label, fallback, variant),
                                              R.s_facts(chip, f["kicker"], f["title"], f["facts"], True, label, fallback, variant)))
        alt = f"{C.plain(f['title'])}: " + "; ".join(f"{t} ({s})" for _, t, s in f["facts"]) + "."
        rec = self._linked_value(sid, day, tm, tag, media, mlink, "", alt, f"{tag}:{k}",
                                 C.RULE_SERVIS if kind == "servis" else C.RULE_MARKA, md5(VERSION, str(f), url, text),
                                 url, text, tag)
        rec.update(kicker=f["kicker"], headline=f["title"], title=C.plain(f["title"]))
        return rec

    def tip_target(self, t: dict) -> tuple[str, str, str, str] | None:
        """İpucu story'sinin konusuna göre link: ilgili kategori ya da servis randevusu. Eşleşme yoksa None."""
        dest = t.get("link")
        if dest == "servis":
            return (self.site["service"]["booking_url"], "SERVİS RANDEVUSU AL", "Randevu almak için dokun",
                    "Link profilde<u>·</u>Servis randevusu")
        url = self.site["urls"]["categories"].get(dest or "")
        if not url or not t.get("st"):
            return None
        return url, t["st"], f"{t['st']} için dokun", f"Link profilde<u>·</u>{t['st']}"

    def fact_target(self, kind: str, kicker: str) -> tuple[str, str, str, str]:
        """Servis/marka story'sinin konusuna göre link hedefi, çıkartma metni, yuva etiketi, API yedeği."""
        u = self.site["urls"]
        if kind == "servis":
            return (self.site["service"]["booking_url"], "SERVİS RANDEVUSU AL", "Randevu almak için dokun",
                    "Link profilde<u>·</u>Servis randevusu")
        return {
            "Kargo ve teslimat": (u["kargo"], "TESLİMAT BİLGİSİ", "Teslimat ayrıntıları için dokun",
                                  "Link profilde<u>·</u>Teslimat"),
            "İade ve garanti": (u["iade"], "İADE KOŞULLARI", "İade koşulları için dokun", "Link profilde<u>·</u>İade"),
            "Mağaza": (u["iletisim"], "ADRES VE İLETİŞİM", "Adres ve yol tarifi için dokun",
                       "Link profilde<u>·</u>İletişim"),
        }.get(kicker, (u["hikaye"], "HİKAYEMİZ", "Hikayemizi okumak için dokun", "Link profilde<u>·</u>Hikayemiz"))

    def _linked_value(self, sid, day, tm, theme, media, mlink, title, alt, ref, rule, sig, url, text, camp) -> dict:
        import render as R
        link = C.utm(url, "story", camp, sid)
        return self.rec(sid, day, tm, "story", "story", theme, title=title, media=media, cover=media[0], alt=alt[:1000],
                        ref=ref, rule=rule, fp=self.fp([], sig), link=link, bio_link=C.utm(url, "bio", camp, sid),
                        channel="suite", sticker={"url": link, "text": text, **R.STICKER}, media_link=mlink)

    def _value(self, sid, day, tm, theme, section, title, alt, ref, rule, sig) -> dict:
        media = f"media/{sid}.jpg"
        self.story_jobs.append((section, DOCS / media))
        return self.rec(sid, day, tm, "story", "story", theme, title=title, media=[media], cover=media, alt=alt[:1000],
                        ref=ref, rule=rule, fp=self.fp([], sig))

    # ---- mevcut kayıtların denetimi ----------------------------------------------------------------

    def state(self, c: dict | None) -> str:
        """'yok' | 'kalsin' | 'ayni' (aynı ürünle yeniden çiz) | 'yeni' (baştan seç)."""
        if c is None:
            return "yok"
        if c.get("status") not in ("planned", "draft") or common.item_dt(c) <= self.now + LEAD:
            return "kalsin"
        # Business Suite'te zamanlanmış story dondurulur: yeniden kurulursa Suite eski içeriği yayınlar,
        # bayrak düşerse API de aynı story'yi ikinci kez atar.
        if c.get("suite_scheduled"):
            slugs = [x["slug"] for x in c.get("products") or []]
            if any(s not in self.by_slug or not C.eligible(self.by_slug[s]) for s in slugs):
                self.say(f"UYARI: {c['id']} Suite'te zamanlanmış ama ürünü artık uygun değil (stok/fiyat); Suite'ten kaldır.")
            return "kalsin"
        st = self._state(c)
        if st != "kalsin":
            promo = [x["id"] for x in self.cal if x.get("suite_scheduled") and x.get("ref") == c["id"]]
            if promo:
                self.say(f"UYARI: {c['id']} yeniden kuruluyor; Suite'te zamanlanmış {', '.join(promo)} eski kapağı "
                         f"gösteriyor. Suite'teki story'yi güncelle.")
        return st

    def _state(self, c: dict) -> str:
        if self.reset:
            return "yeni"
        slugs = [x["slug"] for x in c.get("products") or []]
        if c.get("theme") != "promo":
            if any(s not in self.by_slug or not C.eligible(self.by_slug[s]) for s in slugs):
                return "yeni"
            if any(C.rule_of(self.by_slug[s])["id"] != x.get("rule") for s, x in zip(slugs, c["products"])):
                return "yeni"
        files = list(c.get("media") or []) + [c.get("cover"), c.get("thumb"), c.get("media_link")]
        missing = not self.dry and any(f and not (DOCS / f).exists() for f in files)
        return "ayni" if missing or c.get("audit") or self.current_fp(c) != c.get("fp") else "kalsin"

    def current_fp(self, c: dict) -> str:
        """Kaydın bugünkü veriye göre parmak izi (ürün dışı kayıtlarda içerik yeniden kurulmadan bilinemez: sürüm)."""
        slugs = [x["slug"] for x in c.get("products") or []]
        if c.get("theme") == "promo":
            post = self.get(c.get("ref", ""))
            return md5(VERSION, post["fp"])[:12] if post else ""
        if c.get("theme") == "liste":
            return self.fp(slugs, c.get("ref", ""))
        if slugs:
            return self.fp(slugs)
        return c.get("fp") if c.get("ver") == VERSION else ""

    # ---- gün gün planlama --------------------------------------------------------------------------

    def days(self):
        d = self.start
        while d <= self.end:
            yield d
            d += timedelta(days=1)

    def sid(self, day: date, typ: str, tm: str) -> str:
        return f"{day}-{typ}-{tm.replace(':', '')}"

    def open(self, day: date, tm: str) -> bool:
        return datetime.fromisoformat(f"{day}T{tm}").replace(tzinfo=common.TZ) > self.now + LEAD

    def keep_flags(self, old: dict | None, new: dict) -> dict:
        """Yeniden kurulan kayıtta korunacak alanlar; Suite'te zamanlanmış kayıt değiştiyse uyarılır."""
        new["ver"] = VERSION
        # Elle eklenen collab daveti (O14) yeniden kurulumda kaybolmasın.
        if old and old.get("collaborators") and "collaborators" not in new:
            new["collaborators"] = old["collaborators"]
        if old and old.get("suite_scheduled") and (old.get("sticker") != new.get("sticker") or old.get("fp") != new.get("fp")):
            self.say(f"UYARI: {new['id']} Business Suite'te zamanlanmıştı ama içeriği değişti; Suite'te yeniden planla.")
        return new

    def plan_lists(self) -> None:
        for ds, list_id in sorted(CFG.get("lists", {}).items()):
            day = date.fromisoformat(ds)
            slot = CFG["posts"][str(day.weekday())]
            sid = self.sid(day, "post", slot["time"])
            old = self.get(sid)
            st = self.state(old)
            # config.json'da o günün listesi değiştiyse (ör. 26 Aralık yükseltme → hediye seçkisi) kilitsiz gelecek kayıt
            # baştan seçilir; parmak izi eski listeye göre hesaplandığından kendiliğinden yenilenmez.
            if old and old.get("ref") != list_id and st in ("kalsin", "ayni") and not old.get("suite_scheduled") \
                    and not self.kilitli_ref(sid) \
                    and old.get("status") in ("planned", "draft") and common.item_dt(old) > self.now + LEAD:
                st = "yeni"
            if not (self.start <= day <= self.end) or st == "kalsin" or (st == "yok" and not self.open(day, slot["time"])):
                continue
            items = None
            if st == "ayni":
                items = [self.by_slug[x["slug"]] for x in old["products"]]
            self.drop(sid)
            self.drop(self.sid(day, "story", CFG["stories"]["tanitim"]["time"]))
            self.drop(self.sid(day, "story", slot["time"]))   # paylaşım story'si postla aynı dakikada
            try:
                if items is None or not all(self.images(p) for p in items):
                    items = C.build_list(list_id, self.eligible, lambda p: self.free(p, day, sid) and bool(self.images(p)))
                if not items:
                    raise ValueError("yeterli ürün yok")
                self.put(self.keep_flags(old, self.list_post(sid, day, slot["time"], list_id, items)))
                self.say(f"{sid}  liste:{list_id}  {len(items)} ürün")
            except ValueError as e:
                self.say(f"ATLANDI {sid}: liste kuralı sağlanamadı ({e}); içerik üretilmedi.")

    def plan_post(self, day: date) -> dict | None:
        slot = CFG["posts"][str(day.weekday())]
        special = CFG.get("specials", {}).get(str(day))
        kind = "yilbasi" if special == "yilbasi" else slot["kind"]
        tm = slot["time"]
        sid = self.sid(day, "post", tm)
        old = self.get(sid)
        st = self.state(old)
        if kind == "liste" or st == "kalsin" or (st == "yok" and not self.open(day, tm)):
            return self.get(sid)
        self.drop(self.sid(day, "story", CFG["stories"]["tanitim"]["time"]))   # tanıtım story'si postla birlikte yenilenir
        self.drop(self.sid(day, "story", tm))   # paylaşım story'si (postla aynı dakikada) da
        self.drop(sid)
        new = None
        if kind == "yilbasi":
            new = self.newyear_post(sid, day, tm)
        elif kind == "ipucu":
            tips = {t["id"]: t for t in self.tips.get("carousels", [])}
            order = [i for i in CFG.get("tips", []) if i in tips] + [i for i in tips if i not in CFG.get("tips", [])]
            used = {c["ref"] for c in self.cal if c.get("theme") == "ipucu" and c["type"] == "post"}
            tid = old["ref"] if st == "ayni" and old.get("ref") in tips else next(
                (i for i in order if i not in used and C.in_season(tips[i]["title"], day.month)), None)
            if tid:
                new = self.tip_post(sid, day, tm, tips[tid])
        else:
            reel = kind == "reel"
            p = self.by_slug[old["products"][0]["slug"]] if st == "ayni" and old.get("products") else None
            if p and (not self.images(p) or (reel and len(C.clean_specs(p)) < 3)):
                p = None
            # Tarihe özel alt tür (config.json post_kural; ör. 24–31 Aralık'ta çocuk ve 2. el bisiklet postu)
            zorunlu = CFG.get("post_kural", {}).get(str(day))
            pool = C.pool_rules(slot["pool"], day.month)
            avoid = self.komsu_kurallar(day, sid)
            if p and self.yeni_kural(day) and not self.kilitli_ref(sid):
                # Kilitsiz kayıtta korunan ürün yeni kurallara uymuyorsa yeniden seçilir (uyan varsa)
                neden = ("tarihe özel alt tür" if zorunlu and self.rule_id[p["slug"]] != zorunlu else
                         "±1 günde aynı alt tür" if self.rule_id[p["slug"]] in self.komsu_kurallar(day, sid, sabit=True) else
                         "teknik özellik < 3" if len(C.clean_specs(p)) < 3 else "")
                if neden:
                    q = self.post_sec([zorunlu] if zorunlu else pool, day, sid, avoid, reel)
                    if neden == "teknik özellik < 3" and q and len(C.clean_specs(q)) < 3:
                        q = None   # özellikli aday yoksa özelliksiz bir üründen ötekine geçilmez
                    if q and q is not p:
                        self.say(f"{sid}: {p['slug']} yeniden seçildi ({neden}).")
                        p, old = q, dict(old, headline="")
            keep = old.get("headline") if p else None
            # Suite'te zamanlanmış tanıtım story'si eski başlığı gösteriyor: aynı ürünle kuruluyorsa başlık korunsun
            force = bool(keep) and any(x.get("suite_scheduled") and x.get("ref") == sid for x in self.cal)
            if not p and zorunlu:
                p = self.post_sec([zorunlu], day, sid, avoid, reel)
            p = p or self.post_sec(pool, day, sid, avoid, reel)
            if p and zorunlu and self.rule_id[p["slug"]] != zorunlu:
                self.say(f"UYARI: {sid}: tarihe özel alt tür '{zorunlu}' için stokta uygun ürün yok; "
                         f"günün havuzundan seçildi ({p['slug']}).")
            if p:
                new = (self.reel if reel else self.product_carousel)(sid, day, tm, slot, p, keep, force)
        if not new:
            self.say(f"ATLANDI {sid}: kurala uyan içerik bulunamadı; yeri boş bırakıldı.")
            return None
        self.put(self.keep_flags(old, new))
        self.say(f"{sid}  {new['format']:8} {new['theme']:6} {new['title'][:38]:38} "
                 f"{(new['products'][0]['name'] if new['products'] else new['ref'])[:50]}")
        return new

    def plan_stories(self, day: date, post: dict | None) -> None:
        st_cfg = CFG["stories"]
        # 09:30 değer story'si
        tm = st_cfg["deger"]["time"]
        sid = self.sid(day, "story", tm)
        old, s = self.get(sid), None
        s = self.state(old)
        if s in ("ayni", "yeni") or (s == "yok" and self.open(day, tm)):
            self.drop(sid)
            new = self.value_story(sid, day, tm, st_cfg["deger"]["weekdays"][day.weekday()])
            if new:
                self.put(self.keep_flags(old, new))
            else:
                self.say(f"ATLANDI {sid}: mevsime uyan içerik kalmadı.")
        # 12:30 Günün ürünü
        tm = st_cfg["urun"]["time"]
        sid = self.sid(day, "story", tm)
        old = self.get(sid)
        s = self.state(old)
        if s in ("ayni", "yeni") or (s == "yok" and self.open(day, tm)):
            p = self.by_slug[old["products"][0]["slug"]] if s == "ayni" else None
            keep = old.get("headline") if p else None
            self.drop(sid)
            if p and not self.images(p):
                p = None
            avoid = {x.get("rule") for x in (post or {}).get("products") or []}
            # ±1 gün: önceki/sonraki günün post ve story'leriyle aynı alt tür olmasın
            komsu = avoid | self.komsu_kurallar(day, sid)
            if p and self.yeni_kural(day) and self.rule_id[p["slug"]] in komsu:
                self.say(f"{sid}: {p['slug']} yeniden seçildi (±1 günde aynı alt tür: {self.rule_id[p['slug']]}).")
                p, keep = None, None
            if not p:
                p = self.choose(C.pool_rules("hepsi", day.month), day, sid, avoid=komsu)
                if not p and komsu != avoid:
                    p = self.choose(C.pool_rules("hepsi", day.month), day, sid, avoid=avoid)
                    if p:
                        self.say(f"UYARI: {sid}: ±1 günde alt türü çakışmayan boş ürün yok; yalnız günün postundan kaçınıldı.")
            if p:
                self.put(self.keep_flags(old, self.product_story(sid, day, tm, p, keep)))
            else:
                self.say(f"ATLANDI {sid}: boş ürün kalmadı.")
        # Her post story'de TEK kez duyurulur. Paylaşım story'si (postla aynı dakikada) kurulabiliyorsa 20:30
        # tanıtımı kurulmaz: ikisi birden aynı post kapağını iki kez story'ye koyar (25 Kas 2026 hatası).
        aktif = bool(post) and post.get("status") in ("planned", "draft", "published")
        paylasim = aktif and bool(st_cfg.get("paylasim")) and \
            post["time"] not in {st_cfg[k]["time"] for k in ("deger", "urun", "tanitim")}
        # 20:30 günün postunun tanıtımı (yalnız paylaşım story'si yoksa)
        tm = st_cfg["tanitim"]["time"]
        sid = self.sid(day, "story", tm)
        old = self.get(sid)
        s = self.state(old)
        if not aktif or paylasim:
            if old and s != "kalsin":
                self.drop(sid)
            elif old and paylasim and old.get("status") in ("planned", "draft") \
                    and sid not in common.cancelled_ids() and common.item_dt(old) > self.now:
                self.say(f"UYARI: {sid} Suite'te zamanlanmış ikinci story ({post['id']} zaten paylaşım story'siyle "
                         f"duyuruluyor): Suite'ten sil, kimliği data/iptal.txt'ye yaz.")
            if not paylasim:
                return
        elif s in ("ayni", "yeni") or (s == "yok" and self.open(day, tm)):
            self.drop(sid)
            self.put(self.keep_flags(old, self.promo_story(sid, day, tm, post, yonlendir=True)))
        # Postla aynı dakikada paylaşım story'si: her post story'de de duyurulur (post kapağı + tıklanabilir link)
        if paylasim:
            tm = post["time"]
            sid = self.sid(day, "story", tm)
            old = self.get(sid)
            s = self.state(old)
            if s in ("ayni", "yeni") or (s == "yok" and self.open(day, tm)):
                self.drop(sid)
                self.put(self.keep_flags(old, self.promo_story(sid, day, tm, post, st_cfg["paylasim"]["kicker"])))

    # ---- çizim -------------------------------------------------------------------------------------

    def render(self) -> None:
        if self.dry:
            return
        import render as R
        if self.post_jobs:
            self.say(f"Post kareleri çiziliyor: {len(self.post_jobs)}")
            R.render_all(self.post_jobs)
        if self.reels:  # reel üretimi şu an kapalı (config'te kind "reel" yok); yeniden açılırsa çalışır
            from reel import make_reel
        for frames, mp4, cover in self.reels:
            make_reel(frames, mp4)
            cover.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frames[0], cover)
        if self.reels:
            self.say(f"Reel üretildi: {len(self.reels)}")
        if self.story_jobs:
            self.say(f"Story kareleri çiziliyor: {len(self.story_jobs)}")
            R.render_all(self.story_jobs)
        for c in self.cal:
            if c["id"] in self.touched:
                R.thumb(DOCS / c["cover"], DOCS / c["thumb"])

    def verify(self) -> None:
        """Dosyası oluşmayan kayıt takvime girmez."""
        if self.dry:
            return
        for c in list(self.cal):
            if c["id"] not in self.touched:
                continue
            files = list(c["media"]) + [c["cover"], c["thumb"]] + ([c["media_link"]] if c["media_link"] else [])
            lost = [f for f in files if not (DOCS / f).exists() or (DOCS / f).stat().st_size == 0]
            if lost:
                self.say(f"HATA {c['id']}: dosya oluşmadı ({', '.join(lost)}); kayıt takvime alınmadı.")
                self.drop(c["id"], force=True)

    def cleanup(self) -> None:
        """Takvimde geçmeyen medya dosyalarını sil (eski şemanın görselleri dahil)."""
        if self.dry:
            return
        keep = set()
        for c in self.cal:
            keep.update(f for f in list(c.get("media") or []) + [c.get("cover"), c.get("thumb"), c.get("media_link")] if f)
        gone = 0
        for folder in (MEDIA, THUMBS):
            if not folder.exists():
                continue
            for f in folder.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".mp4", ".png") \
                        and str(f.relative_to(DOCS)).replace("\\", "/") not in keep:
                    f.unlink()
                    gone += 1
        if gone:
            self.say(f"{gone} eski medya dosyası silindi.")

    # ---- kilitli postlar için düzeltme önerisi (O6) ------------------------------------------------------

    def oneri_caption(self, c: dict) -> str:
        """Kaydın açıklamasının bugünkü content.py kurallarıyla yeniden üretilmiş hâli (kayda yazılmaz).
        Öneri gerçek bir paylaşım değil: tekrar sayacına (_URETILEN) iz bırakmasın diye sayaç geri yüklenir."""
        sakla = dict(C._URETILEN)
        try:
            return self._oneri_caption(c)
        finally:
            C._URETILEN.clear()
            C._URETILEN.update(sakla)

    def _oneri_caption(self, c: dict) -> str:
        theme = c.get("theme")
        if theme == "ipucu":
            tip = self.carousel_tip(c.get("ref"))
            if not tip:
                raise ValueError(f"ipucu bulunamadı: {c.get('ref')}")
            return C.tip_caption(tip, gun=c["date"], onceki=self.cal)[0]
        if theme == "urun":
            p = self.by_slug[c["products"][0]["slug"]]
            return C.product_caption(p, self.q(p), C.rule_of(p), c["date"], onceki=self.cal)[0]
        if theme == "liste":
            cfg = C.LISTS[c["ref"]]
            # Ad/fiyat bugünkü veriden (kayıttaki değer eski olabilir)
            xs = [dict(x, name=C.display_name(p), price=p["price"], q=self.q(p))
                  for x in c["products"] for p in [self.by_slug[x["slug"]]]]
            return C.list_caption({"id": c["ref"], "items": xs, "hook": cfg["hook"], "q": cfg["q"], "tags": cfg["tags"]},
                                  gun=c["date"], onceki=self.cal)[0]
        if c.get("ref") == "yilbasi":
            return C.newyear_caption(date.fromisoformat(c["date"]).year + 1, gun=c["date"], onceki=self.cal)[0]
        raise ValueError(f"tema için öneri yok: {theme}")

    def suite_duzelt(self) -> list[dict]:
        """data/suite_duzelt.json: Business Suite'te zamanlanmış (kilitli) postlar için önerilen açıklama ve konum
        satırı. Yalnız öneri dosyasıdır: takvimdeki kaydı DEĞİŞTİRMEZ, kimseye gönderilmez (Barış'a yalnız kullanıcı
        izniyle iletilir). --kuru'da dosya yazılmaz."""
        out = []
        for c in sorted(self.cal, key=lambda c: (c["date"], c["time"], c["id"])):
            if c["type"] != "post" or not c.get("suite_scheduled"):
                continue
            if c.get("status") not in ("planned", "draft"):   # yayınlanmış/iptal kayıt için öneri anlamsız
                continue
            row = {"id": c["id"], "tarih": c["date"], "mevcut_caption": c.get("caption", ""),
                   "onerilen_caption": None, "konum_satiri": "Köyceğiz, Muğla"}
            try:
                row["onerilen_caption"] = self.oneri_caption(c)
            except Exception as e:   # ürün sitede yoksa ya da metin kuralı sağlanamıyorsa öneri boş kalır
                row["not"] = f"öneri üretilemedi: {e}"
                self.say(f"UYARI: {c['id']}: Suite düzeltme önerisi üretilemedi ({e}).")
            out.append(row)
        if self.dry:
            self.say(f"Suite düzeltme önerisi: {len(out)} kilitli post (--kuru: dosya yazılmadı).")
        else:
            common.write_json(DATA / "suite_duzelt.json", out)
            self.say(f"Suite düzeltme önerisi: {len(out)} kilitli post → data/suite_duzelt.json")
        return out

    def run(self) -> list[dict]:
        before = len(common.load_calendar())
        if before != len(self.cal):
            self.say(f"Eski şemadaki {before - len(self.cal)} kayıt takvimden çıkarıldı.")
        self.plan_lists()
        for day in self.days():
            post = self.plan_post(day)
            self.plan_stories(day, post)
        self.render()
        self.verify()
        self.cleanup()
        self.suite_duzelt()
        if not self.dry:
            common.save_calendar(self.cal)
        self.say(f"Takvim: {len(self.cal)} kayıt ({len(self.touched)} yeni/yenilenen), {self.start} → {self.end}.")
        return self.cal


def build_pages(cal: list[dict]) -> None:
    """Simülasyon, bio, takvim ve Suite listesi sayfalarını yeniden üret."""
    import bio
    import simulasyon
    import suite
    import takvim
    bio.build_bio(cal)
    simulasyon.build_sim(cal)
    takvim.build_takvim(cal)
    suite.build_suite(cal)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="İçerik takvimini üretir ve günceller.")
    ap.add_argument("--start", type=date.fromisoformat, default=date.fromisoformat(CFG["plan_start"]))
    ap.add_argument("--end", type=date.fromisoformat, default=date.fromisoformat(CFG["plan_end"]))
    ap.add_argument("--now", type=datetime.fromisoformat, help="sınama için şimdiki zaman (YYYY-AA-GGTSS:DD)")
    ap.add_argument("--yeniden", action="store_true", help="gelecekteki planlı kayıtları baştan seç")
    ap.add_argument("--kuru", action="store_true", help="görsel çizme, dosya yazma")
    a = ap.parse_args(argv)
    now = a.now.replace(tzinfo=common.TZ) if a.now else common.now()
    reset = a.yeniden or YENIDEN.exists()
    pl = Planner(now, a.start, a.end, reset=reset, dry=a.kuru)
    cal = pl.run()
    if a.kuru:
        return 0
    if YENIDEN.exists():
        YENIDEN.unlink()
    build_pages(cal)
    print("Sayfalar yazıldı: docs/onizleme/, docs/index.html, docs/TAKVIM.md, docs/suite/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
