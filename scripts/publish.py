#!/usr/bin/env python3
"""Zamanı gelen paylaşımları Instagram Graph API ile yayınlar. Canlı hesaba yayın yapan TEK betik budur.

Ortam değişkenleri (GitHub Secrets / Variables):
  IG_ACCESS_TOKEN   Meta System User token'ı (süresiz). Yoksa betik dry-run çalışır
  IG_USER_ID        Instagram işletme hesabı ID'si. İsteğe bağlı: boşsa token'a bağlı tek hesap otomatik bulunur
  PUBLIC_BASE_URL   Medyanın yayınlandığı GitHub Pages adresi, ör. https://kullanici.github.io/nitro-instagram

Kullanım:
  python3 scripts/publish.py               zamanı gelenleri yayınla (config.json'da live=true değilse hiçbir şey yapmaz)
  python3 scripts/publish.py --dry-run     yalnızca ne yapılacağını yaz
  python3 scripts/publish.py --check       token'ı, hesabı, kotayı ve medya sunucusunu doğrula
  python3 scripts/publish.py --probe [ID]  kapsayıcıları oluşturup hazır olmalarını bekle; ASLA yayınlamaz

Çift yayın koruması:
  1. Üst kapsayıcı oluşur oluşmaz kimliği takvime yazılıp diske kaydedilir; media_publish ondan sonra çağrılır
     ve asla otomatik yeniden denenmez (yanıtı kaybolan istek yayınlanmış olabilir).
  2. container_id'si dolu kayıt yeniden işlenirken önce kapsayıcının durumu sorulur: PUBLISHED ise yayınlanmaz,
     FINISHED ise yalnız media_publish çağrılır.
  3. Post/reel/carousel yayınlanmadan önce hesabın son 20 medyasında aynı açıklama aranır (commit'i kaçmış
     bir önceki çalışmanın yayınını yakalar).
"""
from __future__ import annotations

import argparse
import copy
import importlib
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any

import common
import graph
from common import item_dt
from graph import GraphError

LOCK_MSG = "YAYIN KAPALI: config.json içinde live=false. Onay gelene kadar hiçbir şey yayınlanmaz."
LATE_LIMIT = timedelta(hours=3)     # bu kadar gecikmiş paylaşım atlanır (gece yarısı story atmasın)
EARLY_WINDOW = timedelta(minutes=35)  # tetik bu kadar erken geldiyse çalışma paylaşım saatini bekleyip tam vaktinde yayınlar
                                      # (:02 ve :17 cron'ları :30 paylaşımını, :32 ve :47 cron'ları :00 paylaşımını yakalar)
DEDUP_WINDOW = timedelta(hours=36)  # aynı açıklamalı medya bu süre içinde yayınlandıysa yeniden yayınlanmaz
MAX_ATTEMPTS = 3                    # bu kadar başarısız denemeden sonra kayıt 'error' olur
CAROUSEL_MAX = 10                   # Instagram bir carousel'de en çok 10 çocuk kabul eder
CAPTION_KEY = 60                    # açıklama eşleştirmesinde bakılan karakter sayısı
ALT_MAX = 1000
AUTH_CODES = {190, 10, 200}         # geçersiz token / uygulama izni yok / izin hatası
FORMATS = ("carousel", "reel", "image", "story")
# İsteğe bağlı parametre → hata mesajında geçerse "reddedilen budur" dedirten ipuçları
OPTIONAL_HINTS = {"alt_text": ("alt_text", "alt text"), "location_id": ("location",)}
# Yayın döngüsünden sonra yeniden üretilen sayfalar: (modül, işlev)
PAGES = (("bio", "build_bio"), ("simulasyon", "build_sim"), ("takvim", "build_takvim"))

# Kapsayıcı durum sorgusu: aralık (sn) × deneme sayısı. Testte aralıklar 0 yapılabilir.
POLL_IMAGE, POLL_IMAGE_TRIES = 3, 20   # görsel: en çok ~60 sn
POLL_VIDEO, POLL_VIDEO_TRIES = 10, 30  # reel: en çok ~300 sn (video işleme uzun sürebilir)


class PublishError(RuntimeError):
    """Yayın akışında bu betiğin saptadığı hata (medya erişilemiyor, kapsayıcı hazır olmadı…)."""


class ContainerDead(PublishError):
    """Kapsayıcı ERROR/EXPIRED oldu: yayınlanamaz, sıfırdan kurulmalı."""


# ---- Graph API'ye açılan tek kapı ----------------------------------------------------------------

def api(method: str, path: str, *, retries: int | None = None, **params: Any) -> dict:
    """Bu betiğin tüm Graph API çağrıları buradan geçer.

    Testte `graph.api` değiştirilirse her çağrı (graph.ig_user_id / graph.ig_accounts içindekiler dahil) kesilir.
    """
    return graph.api(method, path, retries=retries, **params)


def url_ok(url: str) -> bool:
    return graph.url_ok(url)


def ig_id() -> str:
    """Yayın yapılacak Instagram hesabı (IG_USER_ID ya da token'a bağlı tek hesap)."""
    return graph.ig_user_id()


def is_auth(e: BaseException) -> bool:
    """Token/izin hatası mı? Yeniden denemek anlamsızdır, insan müdahalesi gerekir."""
    return isinstance(e, GraphError) and (e.code in AUTH_CODES or e.status == 401)


# ---- Takvim kaydını okuma ------------------------------------------------------------------------

def when(c: dict) -> datetime | None:
    """Kaydın planlanan zamanı; date/time eksik ya da bozuksa None."""
    try:
        return item_dt(c)
    except (KeyError, ValueError, TypeError):
        return None


def media_list(c: dict) -> list[str]:
    """Kaydın medya yolları (docs/ köküne göreli). Eski şemadaki tekil `image` alanı da kabul edilir."""
    media = c.get("media") or c.get("image") or []
    return [media] if isinstance(media, str) else [m for m in media if m]


def resolve_format(c: dict) -> str:
    """Yayın biçimi: story | image | carousel | reel. Suite kaydı (API yedeği dahil) her zaman story'dir."""
    if c.get("channel") == "suite" or "story" in (c.get("type"), c.get("format")):
        return "story"
    if c.get("format"):
        return str(c["format"])
    media = media_list(c)  # eski şema: biçimi medyadan çıkar
    if len(media) > 1:
        return "carousel"
    return "reel" if media and media[0].lower().endswith(".mp4") else "image"


def alt_texts(c: dict, n: int) -> list[str]:
    """n görselin alt metinleri: `alts` varsa slayt başına, yoksa `alt` yalnız ilk görsele."""
    alts = c.get("alts") if isinstance(c.get("alts"), list) else []
    out = [str(a or "") for a in alts[:n]] + [""] * max(0, n - len(alts))
    if out and not out[0]:
        out[0] = str(c.get("alt") or "")
    return [a[:ALT_MAX] for a in out]


def caption_key(text: Any) -> str:
    """Açıklama karşılaştırma anahtarı: boşlukları kırpılmış ilk 60 karakter."""
    return " ".join(str(text or "").split())[:CAPTION_KEY]


def parse_ts(value: Any) -> datetime | None:
    """Graph API zaman damgası (2026-11-27T16:30:05+0000) → datetime; çözülemezse None."""
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def public_url(rel: str) -> str:
    base = common.public_base()
    if not base:
        raise PublishError("PUBLIC_BASE_URL tanımlı değil; medya adresi kurulamıyor.")
    return f"{base}/{str(rel).lstrip('/')}"


# ---- Kapsayıcılar --------------------------------------------------------------------------------

def create_container(ig: str, params: dict[str, Any], optional: dict[str, Any] | None = None) -> str:
    """`POST {ig}/media` ile kapsayıcı oluştur, kimliğini döndür.

    Kapsayıcı oluşturmak yayın değildir; geçici hatada yeniden denemek güvenlidir (retries=2).
    İsteğe bağlı parametre (alt_text, location_id) reddedilirse onsuz bir kez daha denenir: hata mesajında
    adı geçen çıkarılır, hiçbiri geçmiyorsa hepsi.
    """
    params = {k: v for k, v in params.items() if v not in (None, "")}
    extra = {k: v for k, v in (optional or {}).items() if v}
    while True:
        try:
            res = api("POST", f"{ig}/media", retries=2, **params, **extra)
        except GraphError as e:
            if e.transient or is_auth(e) or not extra:
                raise
            msg = str(e.message).lower()
            drop = [k for k in extra if any(h in msg for h in OPTIONAL_HINTS.get(k, (k,)))] or list(extra)
            print(f"UYARI: kapsayıcı reddedildi ({e}); {', '.join(drop)} olmadan yeniden deneniyor.", file=sys.stderr)
            for k in drop:
                del extra[k]
            continue
        if not res.get("id"):
            raise PublishError(f"Kapsayıcı yanıtında id yok: {res}")
        return str(res["id"])


def wait_ready(container: str, video: bool = False) -> str:
    """Kapsayıcı hazır olana dek bekle; 'FINISHED' ya da 'PUBLISHED' döndür.

    ERROR/EXPIRED → ContainerDead. Süre dolarsa PublishError (kapsayıcı duruyor; sonraki çalıştırma sürdürür).
    """
    interval, tries = (POLL_VIDEO, POLL_VIDEO_TRIES) if video else (POLL_IMAGE, POLL_IMAGE_TRIES)
    code = ""
    for n in range(tries + 1):
        st = api("GET", container, fields="status_code,status")
        code = st.get("status_code") or ""
        if code in ("FINISHED", "PUBLISHED"):
            return code
        if code in ("ERROR", "EXPIRED"):
            raise ContainerDead(f"Medya hazırlanamadı ({code}): {st.get('status') or 'ayrıntı yok'}")
        if n < tries:
            time.sleep(interval)
    raise PublishError(f"Medya ~{interval * tries} sn içinde hazır olmadı (son durum: {code or '?'}); "
                       "sonraki çalıştırmada sürdürülecek.")


def build_container(ig: str, c: dict, fmt: str) -> str:
    """Medya adreslerini denetle, kapsayıcıyı (carousel'de önce çocukları) oluştur; üst kapsayıcının kimliğini döndür.

    Hiçbir şey yayınlamaz; --probe da bu işlevi kullanır.
    """
    if fmt not in FORMATS:
        raise PublishError(f"Bilinmeyen biçim: {fmt!r}")
    media = media_list(c)[:CAROUSEL_MAX if fmt == "carousel" else 1]
    if len(media) < (2 if fmt == "carousel" else 1):
        raise PublishError(f"{fmt} için yeterli medya yok ({len(media)} dosya).")
    urls = [public_url(m) for m in media]
    cover = public_url(c["cover"]) if fmt == "reel" and c.get("cover") else ""
    for u in urls + ([cover] if cover else []):
        if not url_ok(u):
            raise PublishError(f"Medya herkese açık değil (Pages henüz güncellenmemiş olabilir): {u}")
    caption, loc = c.get("caption") or "", common.CFG.get("location_id")
    if fmt == "story":
        return create_container(ig, {"image_url": urls[0], "media_type": "STORIES"})
    if fmt == "image":
        return create_container(ig, {"image_url": urls[0], "caption": caption},
                                {"alt_text": alt_texts(c, 1)[0], "location_id": loc})
    if fmt == "reel":
        return create_container(ig, {"media_type": "REELS", "video_url": urls[0], "caption": caption,
                                     "share_to_feed": "true", "cover_url": cover}, {"location_id": loc})
    children = [create_container(ig, {"image_url": u, "is_carousel_item": "true"}, {"alt_text": a})
                for u, a in zip(urls, alt_texts(c, len(urls)))]
    for child in children:
        wait_ready(child)
    return create_container(ig, {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
                            {"location_id": loc})


def media_publish(ig: str, container: str) -> str:
    """Kapsayıcıyı yayınla, medya kimliğini döndür. Canlıya çıkan TEK çağrı budur.

    Otomatik yeniden deneme YOK (retries=0): yanıtı kaybolan bir istek yayınlanmış olabilir.
    """
    if common.CFG.get("live", False) is not True:  # ikinci kilit: bu işlev başka yerden çağrılsa da geçerli
        raise PublishError("live=true değilken yayın denendi; engellendi.")
    res = api("POST", f"{ig}/media_publish", retries=0, creation_id=container)
    if not res.get("id"):
        raise PublishError(f"media_publish yanıtında id yok: {res}")
    return str(res["id"])


def permalink(media_id: str) -> str:
    """Yayınlanan medyanın bağlantısı; alınamazsa boş (yayın zaten başarılı, hata yutulur)."""
    try:
        return api("GET", media_id, fields="permalink").get("permalink") or ""
    except Exception:  # noqa: BLE001
        return ""


# ---- Yayın döngüsü -------------------------------------------------------------------------------

class Publisher:
    """Tek çalıştırmanın durumu: takvim ve çalışma başına bir kez yapılan sorguların (kota, son medyalar) önbelleği."""

    def __init__(self, cal: list[dict], now: datetime, dry: bool) -> None:
        self.cal, self.now, self.dry = cal, now, dry
        self._quota_full: bool | None = None
        self._recent: list[dict] | None = None
        self._recent_asked = False

    def save(self) -> None:
        if not self.dry:
            common.save_calendar(self.cal)

    def quota_full(self) -> bool:
        """24 saatlik yayın kotası dolu mu? Bir kez sorulur; sorgu başarısızsa dolu değil sayılır."""
        if self._quota_full is None:
            self._quota_full = False
            try:
                data = api("GET", f"{ig_id()}/content_publishing_limit", fields="quota_usage,config").get("data")
                lim = (data or [{}])[0]
                used, total = lim.get("quota_usage"), (lim.get("config") or {}).get("quota_total")
                if isinstance(used, int) and isinstance(total, int) and 0 < total <= used:
                    self._quota_full = True
                    print(f"UYARI: 24 saatlik yayın kotası dolu ({used}/{total}); bu çalıştırmada yayın yapılmıyor, "
                          "kayıtlara dokunulmadı.", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"UYARI: yayın kotası sorgulanamadı, devam ediliyor: {e}", file=sys.stderr)
        return self._quota_full

    def recent(self) -> list[dict]:
        """Hesabın son 20 medyası (bir kez sorulur). Sorgu başarısızsa uyarır ve boş liste döndürür."""
        if not self._recent_asked:
            self._recent_asked = True
            try:
                self._recent = api("GET", f"{ig_id()}/media", fields="id,caption,permalink,timestamp",
                                   limit=20).get("data") or []
            except Exception as e:  # noqa: BLE001
                print(f"UYARI: son medyalar sorgulanamadı, açıklama eşleştirmesi (çift yayın denetimi) atlandı: {e}",
                      file=sys.stderr)
        return self._recent or []

    def find_recent(self, c: dict, fmt: str) -> dict | None:
        """Son 36 saatte bu kaydın açıklamasıyla yayınlanmış medya (story'de ve boş açıklamada aranmaz)."""
        key = caption_key(c.get("caption"))
        if fmt == "story" or not key:
            return None
        for m in self.recent():
            if caption_key(m.get("caption")) != key:
                continue
            ts = parse_ts(m.get("timestamp"))
            if ts is None or self.now - ts <= DEDUP_WINDOW:  # zamanı okunamayan eşleşme de yeni sayılır
                return m
        return None

    def adopt(self, c: dict, via: str, found: dict | None, why: str) -> None:
        """Kaydı yeniden yayınlamadan 'published' yap (önceki çalıştırmanın yayını)."""
        found = found or {}
        ts = parse_ts(found.get("timestamp"))
        c.update(status="published", via=via, error="",
                 media_id=found.get("id") or c.get("media_id") or "",
                 permalink=found.get("permalink") or c.get("permalink") or "",
                 published_at=(ts.astimezone(common.TZ) if ts else common.now()).isoformat(timespec="seconds"))
        print(f"ZATEN YAYINDA: {c.get('id')} ({why}); yeniden yayınlanmadı. {c['permalink']}".rstrip())

    def resume(self, c: dict, video: bool) -> str:
        """Önceki çalıştırmadan kalan kapsayıcının durumu: 'FINISHED' | 'PUBLISHED'.

        Kapsayıcı ölmüşse (ERROR/EXPIRED/artık yok) container_id temizlenir ve '' döner: sıfırdan kurulur.
        """
        cid = c["container_id"]
        try:
            state = wait_ready(cid, video)
        except ContainerDead as e:
            why = str(e)
        except GraphError as e:
            if e.transient or is_auth(e):
                raise  # ağ/token sorunu: kapsayıcı yayınlanmış olabilir, silme; sonraki çalıştırma yeniden sorar
            why = f"durumu sorgulanamadı: {e}"
        else:
            print(f"SÜRDÜRÜLÜYOR: {c.get('id')} önceki kapsayıcı {cid} ({state})")
            return state
        print(f"UYARI: {c.get('id')}: önceki kapsayıcı {cid} kullanılamıyor ({why}); sıfırdan kuruluyor.",
              file=sys.stderr)
        c["container_id"] = ""
        self.save()
        return ""

    def publish(self, c: dict, fmt: str, via: str) -> None:
        """Tek kaydı yayınla; zaten yayındaysa yalnız kayda işle. Başarısızlıkta istisna fırlatır."""
        ig = ig_id()
        video = fmt == "reel"
        state = self.resume(c, video) if c.get("container_id") else ""
        if not state:  # sıfırdan kur
            found = self.find_recent(c, fmt)
            if found:
                self.adopt(c, via, found, "aynı açıklamalı medya hesapta zaten var")
                return
            c["container_id"] = build_container(ig, c, fmt)
            self.save()  # media_publish'ten ÖNCE diske: yanıt kaybolursa sonraki çalıştırma durumu buradan sorar
            try:
                state = wait_ready(c["container_id"], video)
            except ContainerDead:
                c["container_id"] = ""
                raise
        if state == "PUBLISHED":
            self.adopt(c, via, self.find_recent(c, fmt), "kapsayıcı zaten yayınlanmış")
            return
        media_id = media_publish(ig, c["container_id"])
        c.update(status="published", via=via, error="", media_id=media_id, permalink="",
                 published_at=common.now().isoformat(timespec="seconds"))
        self.save()  # yayın gerçekleşti: bağlantıyı sormadan önce durumu diske yaz
        c["permalink"] = permalink(media_id)
        print(f"YAYINLANDI: {c.get('id')}  {c['permalink']}".rstrip())

    def late_but_published(self, c: dict, fmt: str, via: str) -> bool:
        """Geç kalmış kaydın yarım kalan kapsayıcısı aslında yayınlanmış mı? Öyleyse 'published' olarak işle."""
        if self.dry or not c.get("container_id"):
            return False
        try:
            state = api("GET", c["container_id"], fields="status_code,status").get("status_code")
        except Exception:  # noqa: BLE001
            return False
        if state != "PUBLISHED":
            return False
        self.adopt(c, via, self.find_recent(c, fmt), "kapsayıcı zaten yayınlanmış")
        return True

    def fail(self, c: dict, e: Exception, fatal: bool) -> bool:
        """Hatayı kayda işle. Kayıt kalıcı olarak 'error' olduysa True, yeniden denenecekse False döndürür."""
        c["error"] = str(e)[:500]
        if not fatal and c["attempts"] < MAX_ATTEMPTS and common.now() - item_dt(c) <= LATE_LIMIT:
            print(f"HATA (deneme {c['attempts']}/{MAX_ATTEMPTS}, sonraki çalıştırmada yeniden denenecek): "
                  f"{c.get('id')}: {e}", file=sys.stderr)
            return False
        c["status"] = "error"
        print(f"HATA: {c.get('id')}: {e}", file=sys.stderr)
        return True


def build_pages(cal: list[dict]) -> None:
    """Bio, simülasyon ve takvim sayfalarını yeniden üret. Modül yoksa sessizce geç, hata verirse yalnız uyar."""
    for mod, fn in PAGES:
        try:
            getattr(importlib.import_module(mod), fn)(cal)  # tembel içe aktarma: modüller ağır/eksik olabilir
        except ImportError as e:
            if getattr(e, "name", None) != mod:  # modül var ama kendi bağımlılığı eksik
                print(f"UYARI: {mod}.{fn} yüklenemedi: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: {mod}.{fn} çalışmadı: {e}", file=sys.stderr)


def run(dry: bool) -> int:
    """Takvimi işle: iptaller, Suite kayıtları, geç kalanlar, API yayınları. Yeni 'error' varsa 1 döner."""
    cal = common.load_calendar()
    now = common.now()
    p = Publisher(cal, now, dry)
    cancelled = common.cancelled_ids()
    errors, dirty = 0, False
    due: list[tuple[datetime, dict]] = []
    for c in cal:
        if c.get("status") in ("planned", "draft") and c.get("id") in cancelled:
            c.update(status="skipped", error="iptal.txt ile iptal edildi")
            print(f"İPTAL: {c.get('id')} (iptal.txt)")
            dirty = True
        elif c.get("status") == "planned":
            dt = when(c)
            if dt is None:  # elle düzenlemede bozulmuş kayıt: diğerlerini engellemesin ama görünür olsun
                print(f"HATA: {c.get('id')}: date/time alanı okunamadı.", file=sys.stderr)
                if not dry:
                    c.update(status="error", error="date/time alanı okunamadı (beklenen: YYYY-AA-GG ve SS:DD)")
                    errors, dirty = errors + 1, True
            elif dt <= now:
                due.append((dt, c))
    if dirty:
        p.save()
    if not due:
        print("Zamanı gelen paylaşım yok.")

    # Aynı dakikada post önce: postla eş zamanlı paylaşım story'si postun yayında olmasını bekler
    for dt, c in sorted(due, key=lambda x: (x[0], x[1].get("type") != "post")):
        suite = c.get("channel") == "suite"
        if c.get("suite_scheduled"):  # story ya da post: Suite'te zamanlanan kayda API dokunmaz (çift paylaşım olmasın)
            # Business Suite planlanan saatte kendisi yayınlar; burada yalnız kayıt güncellenir (gecikme önemsiz)
            c.update(status="published", via="suite", error="", published_at=dt.isoformat(timespec="seconds"))
            print(f"SUITE: {c.get('id')} Business Suite'te zamanlanmış; yayınlandı sayıldı (API'ye dokunulmadı).")
            p.save()
            continue
        if c.get("theme") == "promo" and c.get("ref"):
            # Tanıtım story'si "bugün akışta" der: tanıttığı post yayında değilse yayınlanmaz
            post = next((x for x in cal if x.get("id") == c["ref"]), None)
            pst = post.get("status") if post else "yok"
            if pst != "published":
                if pst in ("planned", "draft") and now - dt <= LATE_LIMIT:
                    print(f"BEKLİYOR: {c.get('id')} tanıttığı post ({c['ref']}) henüz yayında değil.")
                    continue
                c.update(status="skipped", error=f"tanıttığı post yayınlanmadı ({c['ref']}: {pst})")
                print(f"ATLANDI: {c.get('id')} tanıttığı post yayınlanmadı ({pst}).")
                p.save()
                continue
        fmt, via = resolve_format(c), ("api-yedek" if suite else "api")
        if now - dt > LATE_LIMIT:
            if not p.late_but_published(c, fmt, via):
                c["status"] = "missed"
                print(f"ATLANDI (geç kaldı): {c.get('id')}")
            p.save()
            continue
        if not dry and p.quota_full():
            continue
        print(f"YAYIN: {c.get('id')}  [{fmt} · {via}]  {c.get('title') or c.get('name') or ''}".rstrip())
        if dry:
            continue
        tried = c.get("attempts")
        c["attempts"] = (tried if isinstance(tried, int) else 0) + 1
        try:
            p.publish(c, fmt, via)
        except Exception as e:  # noqa: BLE001
            fatal = is_auth(e)
            errors += int(p.fail(c, e, fatal))
            p.save()
            if fatal:
                print("Token/izin hatası: kalan paylaşımlar denenmedi.", file=sys.stderr)
                break
        else:
            p.save()

    if not dry:
        build_pages(cal)
    if errors:
        # Çıkış kodu 1: iş akışı kırmızı görünür, GitHub e-posta bildirimi gönderir. sys.exit değil, çünkü main()
        # bu dönüşten sonra sıradaki API paylaşımını bekleyip tam vaktinde yayınlamalı.
        print(f"{errors} paylaşım hata verdi. Ayrıntı: data/calendar.json içindeki 'error' alanı.", file=sys.stderr)
        return 1
    return 0


# ---- Doğrulama komutları -------------------------------------------------------------------------

def check() -> int:
    """Token'ı, bağlı Instagram hesabını, kotayı ve medya sunucusunu doğrula. Kilitten bağımsızdır, yayınlamaz."""
    problems: list[str] = []
    if not os.environ.get("IG_ACCESS_TOKEN"):
        problems.append("IG_ACCESS_TOKEN tanımlı değil (Graph API denetimleri yapılamadı)")
    else:
        try:
            me = api("GET", "me", fields="id,name")
            print(f"Token sahibi: {me.get('name')} ({me.get('id')})")
            accounts = graph.ig_accounts()
            for name, _page_id, ig in accounts:
                linked = f"{ig.get('username')} / IG_USER_ID={ig.get('id')}" if ig else "bağlı değil"
                print(f"Sayfa: {name}  ->  Instagram: {linked}")
            if not accounts:
                raise PublishError("Token'a hiç Facebook Sayfası atanmamış. System User'a sayfayı varlık olarak ekle.")
            ig_user = ig_id()
            data = api("GET", f"{ig_user}/content_publishing_limit", fields="quota_usage,config").get("data")
            lim = (data or [{}])[0]
            print(f"Kullanılan hesap: {ig_user} · son 24 saatte yayın: {lim.get('quota_usage', '?')}/"
                  f"{(lim.get('config') or {}).get('quota_total', '?')}")
        except RuntimeError as e:  # GraphError ve graph.ig_user_id hataları dahil
            problems.append(str(e))
    base = common.public_base()
    if not base:
        problems.append("PUBLIC_BASE_URL tanımlı değil")
    else:
        ok = url_ok(f"{base}/logo.png")
        print(f"Görsel sunucusu: {base} -> {'erişilebilir' if ok else 'ERİŞİLEMİYOR'}")
        if not ok:
            problems.append(f"görsel sunucusu erişilemiyor ({base}/logo.png)")

    live = common.CFG.get("live", False) is True
    print("Yayın kilidi: " + ("live=true (AÇIK: zamanı gelen paylaşımlar yayınlanır)" if live
                             else "live=false (KAPALI: onay gelene kadar hiçbir şey yayınlanmaz)"))
    cal, now = common.load_calendar(), common.now()
    planned = [c for c in cal if c.get("status") == "planned"]
    print(f"Takvim: {len(cal)} kayıt, {len(planned)} planned")
    upcoming = sorted(((dt, c) for c in planned if (dt := when(c)) and now - dt <= LATE_LIMIT), key=lambda x: x[0])
    print("Sıradaki 5 paylaşım:" if upcoming else "Sıradaki paylaşım: yok")
    for dt, c in upcoming[:5]:
        print(f"  {dt:%Y-%m-%d %H:%M}  {c.get('id')}  {resolve_format(c)}  {c.get('channel') or 'api'}")
    if problems:
        sys.exit("HAZIR DEĞİL: " + "; ".join(problems))
    print("HAZIR: yayın yapılabilir.")
    return 0


def probe(target: str | None) -> int:
    """Canlıya çıkmadan uçtan uca doğrulama: kapsayıcıları oluşturur ve hazır olmalarını bekler.

    media_publish ASLA çağrılmaz, takvim DEĞİŞTİRİLMEZ. Biri bile başarısızsa 1 döndürür.
    """
    if not os.environ.get("IG_ACCESS_TOKEN"):
        sys.exit("--probe: IG_ACCESS_TOKEN tanımlı değil.")
    cal = common.load_calendar()
    if target:
        picks = [c for c in cal if c.get("id") == target]
        if not picks:
            print(f"PROBE HATA {target} takvimde böyle bir kayıt yok")
            return 1
    else:
        now = common.now()
        future = sorted(((dt, c) for c in cal if c.get("status") == "planned" and (dt := when(c)) and dt > now),
                        key=lambda x: x[0])
        picks = []
        for fmt in FORMATS:
            first = next((c for _, c in future if resolve_format(c) == fmt), None)
            if first:
                picks.append(first)
            else:
                print(f"PROBE: gelecekte planned {fmt} kaydı yok; bu biçim denenmedi.")
        if not picks:
            print("PROBE HATA - denenecek kayıt yok (gelecekte planned paylaşım bulunamadı)")
            return 1
    failed = 0
    for c in copy.deepcopy(picks):  # kopya üzerinde çalış: takvim kayıtlarına dokunulmaz
        fmt, started = resolve_format(c), time.monotonic()
        try:
            container = build_container(ig_id(), c, fmt)
            state = wait_ready(container, video=fmt == "reel")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"PROBE HATA {c.get('id')} {fmt} {e}")
        else:
            count = min(len(media_list(c)), CAROUSEL_MAX) if fmt == "carousel" else 1
            print(f"PROBE OK {c.get('id')} {fmt} kapsayıcı={container} durum={state} medya={count} "
                  f"süre={time.monotonic() - started:.0f}sn")
    print(f"PROBE: {len(picks) - failed}/{len(picks)} başarılı. Hiçbir şey yayınlanmadı, takvim değişmedi; "
          "oluşturulan kapsayıcılar kendiliğinden geçersiz olur.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Zamanı gelen paylaşımları Instagram'da yayınlar.")
    ap.add_argument("--dry-run", action="store_true", help="yalnızca ne yapılacağını yaz")
    ap.add_argument("--check", action="store_true", help="token'ı, hesabı, kotayı ve medya sunucusunu doğrula")
    ap.add_argument("--probe", nargs="?", const="", metavar="ID",
                    help="kapsayıcıları oluşturup hazır olmalarını bekle; ASLA yayınlamaz")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # Actions günlüğünde stdout/stderr sırası korunsun
    if args.check:
        return check()
    if args.probe is not None:
        return probe(args.probe or None)
    live = common.CFG.get("live", False) is True
    if not live:
        print(LOCK_MSG)
        if not args.dry_run:
            return 0
    if live and not args.dry_run:
        # IG_USER_ID isteğe bağlı (graph.ig_user_id token'dan bulur); token yoksa yayın imkânsız.
        if not os.environ.get("IG_ACCESS_TOKEN"):  # kilit açıkken sessizce dry-run'a düşmek yayının durduğunu gizler
            sys.exit("YAYIN YAPILAMADI: IG_ACCESS_TOKEN tanımlı değil (GitHub secrets).")
    dry = args.dry_run or not live or not os.environ.get("IG_ACCESS_TOKEN")
    if dry:
        print("DRY-RUN: IG_ACCESS_TOKEN yok ya da --dry-run verildi, hiçbir şey yayınlanmayacak.")
    rc = run(dry)
    # Tetikler (GitHub :17/:47, bulut tetikçisi) paylaşımdan 10-15 dk önce gelir. Kuyruk ve koşu süresi yüzünden
    # paylaşım geç çıkmasın diye: yakında API ile yayınlanacak kayıt varsa saatini bekle, sonra tam vaktinde yayınla.
    # Bekleyen çalışma 'instagram' concurrency grubunu tutar; aynı anda ikinci bir yayın çalışması olmaz.
    # Tek bekleme: en çok ~35 dk, iş akışının 50 dk zaman aşımı içinde kalır (yayın kaydı commit'i kaybolmaz).
    nxt = None if dry else next_api_slot(common.now())
    if nxt is not None:
        wait = (nxt - common.now()).total_seconds() + 3
        print(f"BEKLENİYOR: sıradaki API paylaşımı {nxt:%H:%M}; {wait / 60:.1f} dk sonra tam vaktinde yayınlanacak.")
        sys.stdout.flush()
        time.sleep(max(wait, 0))
        rc = run(dry) or rc
    return rc


def next_api_slot(now: datetime) -> datetime | None:
    """EARLY_WINDOW içinde API ile yayınlanacak (Suite'te zamanlanmamış, iptal edilmemiş) ilk planned kaydın zamanı."""
    cancelled = common.cancelled_ids()
    slots = [dt for c in common.load_calendar()
             if c.get("status") == "planned" and not c.get("suite_scheduled") and c.get("id") not in cancelled
             and (dt := when(c)) is not None and now < dt <= now + EARLY_WINDOW]
    return min(slots) if slots else None


if __name__ == "__main__":
    sys.exit(main())
