#!/usr/bin/env python3
"""Performans raporu: yayınlanan gönderilerin etkileşimini toplar, planlayıcı puanlarını ve RAPOR.md'yi üretir.

Kullanım:
  python3 scripts/report.py            Graph API'den güncel sayıları topla, puanları ve raporu yaz
  python3 scripts/report.py --no-api   API'ye bağlanma; yalnız kayıtlı dosyalardan rapor üret
  python3 scripts/report.py --esle     hafif mod (publish adımında): yalnız Suite eşlemesi ve 72 saat dondurması;
                                       RAPOR.md ve scores.json yazılmaz, jeton yoksa sessizce atlanır
  python3 scripts/report.py --story    hafif mod (publish adımında ve 04:10 planında): yayındaki story'lerin insights
                                       son değeri, Suite story eşlemesi ve link dokunuşu API testi; jeton yoksa atlanır

Yazdıkları (takvime, yani data/calendar.json'a hiçbir durumda dokunmaz):
  data/metrics.json   hesap (takipçi) geçmişi ve gönderi başına ham sayılar; Suite'ten yayınlanan postların
                      eşlenen media_id/permalink'i (kaynak=suite) ve yayından ≥72 saat sonraki ilk ölçüm (dondurulmus);
                      story başına son insights değeri (stories), haftalık hesap insights'ı (hesap_insights) ve
                      link dokunuşu API testinin sonucu (link_testi)
  data/scores.json    planlayıcı için 0..1 arası göreli puanlar: kategori, biçim, tema, saat
  RAPOR.md            okunur haftalık özet ve haftalık KPI tablosu (data/manuel.json'daki elle girilen değerlerle)

Token'da `instagram_manage_insights` izni yokken yalnız beğeni ve yorum toplanır. İzin eklendiğinde erişim,
kaydetme, gönderme ve görüntülenme kendiliğinden gelir; kod değişikliği gerekmez.
Rapor işi yayın işini kırmasın diye çıkış kodu her durumda 0'dır; sorunlar stderr'e yazılır.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import traceback
import unicodedata
from datetime import date, datetime, timedelta

import graph
from common import (AY, CFG, DATA, GUN, GUN_KISA, IG_USERNAME, ROOT, TZ, cancelled_ids, item_dt, load_calendar, now,
                    read_json, tr_date, write_json)

# Çıktı yolları. İşlevler bunları çağrı anında okur; testte başka dizine yönlendirmek için üzerine yazılabilir.
# Aynı şekilde `graph.api` ve bu modüldeki `now` da sahtesiyle değiştirilebilir.
METRICS = DATA / "metrics.json"
SCORES = DATA / "scores.json"
REPORT = ROOT / "RAPOR.md"
MANUEL = DATA / "manuel.json"                 # Barış'ın pazartesi Suite okuması (elle girilir; yalnız okunur)
SUITE_INSIGHTS = DATA / "suite_insights.json"  # baz değer: Suite Insights ekranından alınmış günlük seriler

ACCOUNT_FIELDS = "username,followers_count,follows_count,media_count"
MEDIA_FIELDS = "like_count,comments_count,permalink,media_type,media_product_type,timestamp"
INSIGHT_METRICS = "reach,saved,shares,views,total_interactions"
INSIGHT_KEYS = ("reach", "saved", "shares", "views")
RECORD_KEYS = ("media_id", "permalink", "likes", "comments", *INSIGHT_KEYS, "checked")
PERMISSION_NOTE = "Erişim/kaydetme/gönderme verisi için instagram_manage_insights izni gerekli."

MATURE = timedelta(hours=48)  # ölçüm yayından en az bu kadar sonra alınmışsa gönderi hesaba girer
MIN_POSTS = 6                 # bundan az gönderiyle puan da öneri de üretilmez
MIN_GROUP = 2                 # bundan az gönderisi olan grup puanlanmaz
NOTABLE = 0.15                # öneriye dönüşmesi için gereken en küçük fark
SCORE_EXTRA = (("saved", 4), ("shares", 5))  # beğeni + 3×yorum üstüne, veri varsa eklenen terimler
DIMS = ("category", "format", "theme", "hour")
ACCOUNT_KEEP = 400            # hesap geçmişinde tutulan en çok kayıt (günde bir)
STREAK_LIMIT = 3              # art arda bu kadar başarısız çağrı: bu çalışmada denemeyi bırak
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
GRACE = timedelta(hours=3)    # publish.py'deki LATE_LIMIT: bundan eski "planned" kayıt, yayıncı işlemedi demektir

# Suite eşlemesi: Business Suite'te zamanlanan (suite_scheduled, kilitli) postlar yayıncıdan geçmez; media_id'leri
# hesabın /media listesinden zaman damgasıyla bulunur ve yalnız metrics.json'a yazılır (takvime asla yazılmaz).
MEDIA_LIST_FIELDS = "id,timestamp,permalink,caption,media_type"
ESLE_TOL = timedelta(minutes=10)        # planlanan saat ile /media zaman damgası arasındaki en büyük fark
ESLE_GERI = timedelta(days=21)          # günlük raporda bundan eski eşlenmemiş post artık aranmaz
ESLE_GERI_HAFIF = timedelta(hours=6)    # --esle (15 dakikada bir) yalnız yakın geçmişteki postları arar
ESLE_GEC = timedelta(minutes=45)        # planlanan saatten bu kadar sonra eşlenmemiş post "eşlenemedi" sayılır
ESLE_BASLANGIC = "2026-11-25"           # bu tarihten itibaren planlanan Suite postları eşlenir
ESLE_SAYFA = 4                          # /media'da gezilen en çok sayfa (sayfa başına 50 medya)
ESLE_TUR = {"carousel": "CAROUSEL_ALBUM", "image": "IMAGE", "reel": "VIDEO"}   # eşit puanda türü tutan seçilir
DONDUR = timedelta(hours=72)            # yayından en az bu kadar sonra alınan ilk ölçüm "dondurulmus"a bir kez yazılır
DONDUR_HAFIF = timedelta(hours=48)      # --esle yalnız 72..120 saatlik postları dondurur; daha eskisini günlük rapor
EXTRA_KEYS = ("kaynak", "yayin", "eslesme", "dondurulmus")   # yeniden toplamada korunan eşleme/dondurma alanları

# Story ve hesap insights (O7). Story'ler /stories'te yalnız 24 saat görünür; her publish çalışmasında son değer
# metrics.json "stories" altına yazılır, story yayından düşünce son değer kalır. Takvime hiçbir durumda yazılmaz.
STORY_LIST_FIELDS = "id,timestamp,media_type,permalink"
STORY_METRICS = ("reach", "views", "replies", "shares", "total_interactions", "follows", "profile_visits", "navigation")
STORY_KIRILIM = "story_navigation_action_type"   # navigation metriğinin kırılımı (link testi için istenir)
STORY_SAYFA = 2                                   # /stories'te gezilen en çok sayfa (sayfa başına 50)
LINK_ANAHTAR = ("link", "sticker")                # yanıttaki metrik/kırılım adında aranan parçalar
LINK_NOT = "link dokunuşu Barış'ın haftalık Suite okumasından (manuel.json) alınır"
LINK_TR = {"donuyor": "dönüyor", "donmuyor": "dönmüyor", "denenmedi": "denenmedi"}
HESAP_METRICS = ("reach", "profile_links_taps", "follows_and_unfollows", "profile_views")
HESAP_TR = {"reach": "erişim", "profile_views": "profil görüntüleme", "profile_links_taps": "profile_links_taps",
            "follows_and_unfollows": "takip/takipten çıkma"}

# data/manuel.json hafta kaydının alanları: sayı (int ya da pay için ondalık) ya da null; null/eksik = veri yok.
MANUEL_SAYI = ("profil_ziyareti", "link_tiklamasi", "goruntulenme", "izleyen", "etkilesim", "takip", "nkod_talep",
               "nkod_satis", "ga4_oturum", "ga4_utm_content_payi", "ga4_arama_payi", "bio_kategori_tiklama",
               "bio_iletisim_tiklama", "blog_yazisi", "collab_kabul", "merchant_onayli")
MANUEL_EVETHAYIR = ("merchant_uygun",)
BAZ_TR = (("views", "görüntülenme"), ("viewers", "izleyen"), ("interactions", "etkileşim"),
          ("link_clicks", "link tıklaması"), ("profile_visits", "profil ziyareti"), ("follows", "takip"))

STATUS_TR = (("published", "Yayınlandı (published)"), ("missed", "Kaçırıldı (missed)"), ("error", "Hata (error)"),
             ("skipped", "Atlandı (skipped)"))
FORMAT_TR = {"carousel": "carousel", "reel": "reel", "image": "tek görsel", "story": "story"}
THEME_TR = {"urun": "Ürün", "ipucu": "İpucu", "liste": "Liste", "servis": "Servis", "marka": "Marka",
            "promo": "Kampanya", "etkilesim": "Etkileşim"}
METRIC_TR = {"reach": "erişim", "saved": "kaydetme", "shares": "gönderme"}


# ---- Küçük yardımcılar -------------------------------------------------------------------------

def _warn(msg: str) -> None:
    print(f"UYARI: {msg}", file=sys.stderr)


def _emsg(e: Exception) -> str:
    """Hatanın stderr'e ve rapora yazılacak tek satırlık metni."""
    if isinstance(e, KeyError):   # graph._call token'ı os.environ[...] ile okur
        key = e.args[0] if e.args else "?"
        return "IG_ACCESS_TOKEN tanımlı değil" if key == "IG_ACCESS_TOKEN" else f"beklenen alan yok: {key}"
    if isinstance(e, graph.GraphError):
        # GraphError'ın kendi metni alt kod yokken "(kod 4/None)" yazar; burada yalnız dolu olanlar yazılır.
        code = "/".join(str(x) for x in (e.code, e.subcode) if x)
        s = (f"Graph API {e.status}: " if e.status else "") + str(e.message or "") + (f" (kod {code})" if code else "")
    else:
        s = str(e)
    return " ".join(s.split())[:300] or type(e).__name__


def _num(v, default=None):
    """Sayıysa int'e çevirir; değilse (None, metin, sözlük, NaN) varsayılanı döndürür."""
    try:
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
    except (ValueError, OverflowError):
        return default


def _sayi(v) -> int | float | None:
    """Elle girilen sayı: negatif olmayan int/float (tam sayıysa int); bool, metin, NaN, sonsuz ve null -> None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return None
    return int(v) if float(v).is_integer() else float(v)


def _pazartesi(d: date) -> date:
    """Günün haftasının pazartesisi (hafta anahtarı)."""
    return d - timedelta(days=d.weekday())


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _dt(s) -> datetime | None:
    """ISO zaman damgası -> saat dilimli datetime; boş ya da bozuksa None."""
    try:
        d = datetime.fromisoformat(str(s)) if s else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=TZ)


def _date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _planned(c: dict) -> datetime | None:
    try:
        return item_dt(c)
    except (KeyError, ValueError, TypeError):
        return None


def _when(c: dict) -> datetime | None:
    """Kaydın zamanı: yayınlandıysa published_at, yoksa planlanan tarih-saat."""
    return (_dt(c.get("published_at")) if c.get("status") == "published" else None) or _planned(c)


def _is_story(c: dict) -> bool:
    """publish.py'deki kuralla aynı: Business Suite kaydı (API yedeğiyle yayınlansa da) her zaman story'dir."""
    return c.get("type") == "story" or c.get("format") == "story" or c.get("channel") == "suite"


def _hour(c: dict, pub: datetime) -> str:
    """Planlayıcının seçtiği saat dilimi ("19"); takvimde saat yoksa gerçek yayın saati."""
    try:
        return str(int(str(c.get("time") or "").split(":")[0]))
    except ValueError:
        return str(pub.astimezone(TZ).hour)


# ---- Veri toplama ------------------------------------------------------------------------------

def load_metrics(kati: bool = False) -> dict:
    """data/metrics.json; dosya yoksa ya da bozuksa boş iskelet.

    kati=True (hafif modlar): dosya var ama okunamıyor ya da bozuksa ValueError fırlatılır. Hafif modlar 15 dakikada
    bir yazar; bozuk dosyanın yerine boş iskelet yazılırsa account geçmişi ve dondurulmuş ölçümler silinirdi.
    """
    try:
        raw = read_json(METRICS, {})
    except (ValueError, OSError) as e:
        if kati:
            raise ValueError(f"{METRICS.name} okunamadı: {e}") from None
        _warn(f"{METRICS.name} okunamadı, boş veriyle devam ediliyor: {e}")
        raw = {}
    if not isinstance(raw, dict):
        if kati:
            raise ValueError(f"{METRICS.name} beklenen biçimde değil (JSON nesnesi değil)")
        raw = {}
    account, media, errors = raw.get("account"), raw.get("media"), raw.get("errors")
    stories, hesap, link = raw.get("stories"), raw.get("hesap_insights"), raw.get("link_testi")
    out = {"updated": raw.get("updated"),
           "account": [a for a in account if isinstance(a, dict)] if isinstance(account, list) else [],
           "media": {k: v for k, v in media.items() if isinstance(v, dict)} if isinstance(media, dict) else {},
           "insights": raw.get("insights") if isinstance(raw.get("insights"), bool) else None,
           "errors": [str(x) for x in errors] if isinstance(errors, list) else [],
           # O7: story başına son değer, haftalık hesap insights'ı (anahtar: haftanın pazartesisi), link testi
           "stories": {str(k): v for k, v in stories.items() if isinstance(v, dict)} if isinstance(stories, dict) else {},
           "hesap_insights": {str(k): v for k, v in hesap.items() if isinstance(v, dict)} if isinstance(hesap, dict)
           else {}}
    if isinstance(link, dict):
        out["link_testi"] = link
    if isinstance(raw.get("story_baslangic"), str):
        out["story_baslangic"] = raw["story_baslangic"]   # story takibinin ilk başarılı çalışması (eşleme oranı için)
    return out


def _global_error(e: Exception) -> bool:
    """Tek gönderiye özgü olmayan hata (token yok ya da geçersiz, ağ, kota): kalan çağrılar da boşa gider."""
    if isinstance(e, KeyError):
        return e.args[:1] == ("IG_ACCESS_TOKEN",)
    if not isinstance(e, graph.GraphError):
        return False
    return e.status in (0, 401, 429) or e.code in (4, 17, 32, 102, 104, 190, 613)


def _permission_error(e: Exception) -> bool:
    """Insights çağrısında izin eksikliği: HTTP 400/403 ve (kod 10/200 ya da mesajda "permission")."""
    if not isinstance(e, graph.GraphError):
        return False
    return e.status in (400, 403) and (e.code in (10, 200) or "permission" in (e.message or "").lower())


def _degerler(res) -> dict[str, int]:
    """/insights yanıtındaki metrik değerleri ({ad: sayı}): `values[0].value` ya da `total_value.value`."""
    out = {}
    data = res.get("data") if isinstance(res, dict) else None
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        values, total = d.get("values"), d.get("total_value")
        first = values[0] if isinstance(values, list) and values and isinstance(values[0], dict) else {}
        v = _num(first.get("value"), _num(total.get("value")) if isinstance(total, dict) else None)
        if v is not None:
            out[str(d.get("name"))] = v
    return out


def _kirilim(res) -> dict[str, int]:
    """/insights yanıtındaki kırılım değerleri: `total_value.breakdowns[].results[]` -> {"boyut/değer": sayı}.
    Anahtarlar API'nin döndürdüğü `dimension_values` olduğu gibidir (ad uydurulmaz)."""
    out = {}
    data = res.get("data") if isinstance(res, dict) else None
    for d in data if isinstance(data, list) else []:
        total = d.get("total_value") if isinstance(d, dict) else None
        for b in (total.get("breakdowns") or []) if isinstance(total, dict) else []:
            for r in (b.get("results") or []) if isinstance(b, dict) else []:
                if not isinstance(r, dict) or _num(r.get("value")) is None:
                    continue
                key = "/".join(str(x) for x in r.get("dimension_values") or []) or "?"
                out[key] = _num(r.get("value"))
    return out


def _insights(media_id: str) -> dict[str, int]:
    """Gönderinin insights değerleri ({ad: sayı}). `instagram_manage_insights` izni yoksa GraphError fırlatır."""
    return _degerler(graph.api("GET", f"{media_id}/insights", metric=INSIGHT_METRICS))


def _metrik_cek(path: str, metrikler: tuple[str, ...], desteksiz: set[str], **params) -> tuple[dict, dict]:
    """/insights çağrısı: önce tüm metrikler tek istekte, hata olursa metrik metrik istenir.

    Döndürür: ({metrik: sayı}, {metrik: hata metni}). Tek başına istendiğinde kalıcı hata veren metrik (o nesnede
    en az bir başka metrik geldiyse; yani hata nesneye değil metriğe özgüyse) `desteksiz` kümesine eklenir ve bu
    çalışmada bir daha istenmez. Token/ağ/kota ya da izin hatası dışarı fırlatılır (çağıran karar verir). Toplu
    istek geçici hatayla (5xx, is_transient) düşerse de metrik metrik denenmez, hata dışarı fırlatılır: kesintide
    her metrik için yeniden deneme (graph.api'nin bekleme süreleriyle) çalışmayı dakikalarca uzatırdı.
    """
    istek = [k for k in metrikler if k not in desteksiz]
    if not istek:
        return {}, {}
    try:
        return _degerler(graph.api("GET", path, metric=",".join(istek), **params)), {}
    except Exception as e:  # noqa: BLE001
        if _global_error(e) or _permission_error(e) or getattr(e, "transient", False):
            raise
        if len(istek) == 1:
            return {}, {istek[0]: _emsg(e)}
    out: dict[str, int] = {}
    hatalar: dict[str, str] = {}
    kalici = []
    for k in istek:
        try:
            out.update(_degerler(graph.api("GET", path, metric=k, **params)))
        except Exception as e:  # noqa: BLE001
            if _global_error(e) or _permission_error(e):
                raise
            hatalar[k] = _emsg(e)
            if not getattr(e, "transient", False):
                kalici.append(k)
    if out:
        desteksiz.update(kalici)
    return out, hatalar


def collect(cal: list[dict]) -> dict:
    """Hesap ve gönderi sayılarını Graph API'den toplar; metrics sözlüğünü günceller, dosyaya yazar ve döndürür.

    API hataları dışarı sızmaz. Tek gönderideki hata (silinmiş gönderi vb.) yalnız o gönderiyi atlar; token, ağ ya
    da kota hatası toplamayı keser. Her durumda eldeki eski veri korunur, sorun `errors` listesine yazılır.
    Story'lerde beğeni/yorum olmadığından yalnız post ve reel'ler sorgulanır.
    """
    m = load_metrics()
    stamp = now().isoformat(timespec="seconds")
    today = stamp[:10]
    errors: list[str] = []
    api_ok = False                     # bu çalışmada en az bir çağrı başarılı oldu
    stop: Exception | None = None      # toplamayı kesen hata

    try:
        a = graph.api("GET", graph.ig_user_id(), fields=ACCOUNT_FIELDS)
        rec = {"date": today, "followers": _num(a.get("followers_count")), "media_count": _num(a.get("media_count"))}
        if rec["followers"] is None:
            raise ValueError("yanıtta followers_count yok")
        m["account"] = sorted([x for x in m["account"] if x.get("date") != today] + [rec],
                              key=lambda x: str(x.get("date")))[-ACCOUNT_KEEP:]
        api_ok = True
        print(f"Hesap: @{a.get('username', '?')} · takipçi {_n(rec['followers'])} · medya {_n(rec['media_count'])}")
    except Exception as e:  # noqa: BLE001
        _warn(f"hesap verisi alınamadı: {_emsg(e)}")
        if _global_error(e):
            stop = e
        else:
            errors.append(f"Hesap verisi (takipçi sayısı) alınamadı: {_emsg(e)}")

    media = m["media"]
    if stop is None:
        try:
            n = esle(cal, m, stamp)
            if n:
                print(f"Suite eşlemesi: {n} post eşlendi")
        except Exception as e:  # noqa: BLE001
            _warn(f"Suite eşlemesi yapılamadı: {_emsg(e)}")
            if _global_error(e):
                stop = e
            elif not _permission_error(e):
                errors.append(f"Suite postları /media ile eşlenemedi: {_emsg(e)}")
    if stop is None:
        try:
            n = hesap_insights(m, stamp)
            if n:
                print(f"Hesap insights: {n} hafta güncellendi")
        except Exception as e:  # noqa: BLE001
            if _permission_error(e):
                _warn(f"hesap insights izni yok, atlandı: {_emsg(e)}")
            else:
                _warn(f"hesap insights alınamadı: {_emsg(e)}")
                if _global_error(e):
                    stop = e
                else:
                    errors.append(f"Hesap insights (erişim, profil görüntüleme) alınamadı: {_emsg(e)}")
    targets = _targets(cal, media)
    gone: dict[str, tuple[dict, str, str]] = {}   # kalıcı hata veren (silinmiş vb.) gönderiler: id -> (kayıt, media_id, hata)
    try_insights, denied, ins_ok, ins_fail, ins_err = True, False, 0, 0, ""
    done = streak = 0
    for c, mid in targets:
        if stop is not None:
            break
        cid = str(c["id"])
        try:
            d = graph.api("GET", mid, fields=MEDIA_FIELDS)
            if not isinstance(d, dict):
                raise ValueError("beklenmeyen yanıt biçimi")
        except Exception as e:  # noqa: BLE001
            _warn(f"{cid}: gönderi verisi alınamadı: {_emsg(e)}")
            streak += 1
            transient = bool(getattr(e, "transient", False))
            if _global_error(e) or (streak >= STREAK_LIMIT and (transient or not api_ok)):
                stop = e
            elif not transient:
                gone[cid] = (c, mid, _emsg(e))
            continue
        streak, api_ok, done = 0, True, done + 1
        old = media.get(cid, {})
        if str(old.get("media_id")) != mid:   # aynı takvim kaydı yeniden yayınlanmış: eski sayılar başka medyaya ait
            old = {}
        rec = _kayit(c, mid, d, old, stamp)
        taze: dict | None = {} if denied else None   # bu ölçümde alınan insights ({}: izin yok); None: alınamadı
        if try_insights:
            try:
                taze = {k: v for k, v in _insights(mid).items() if k in INSIGHT_KEYS}
                rec.update(taze)
                ins_ok += 1
            except Exception as e:  # noqa: BLE001
                if _global_error(e):
                    stop = e
                elif _permission_error(e):
                    # İzin gelene kadar her çalışmada yalnız bu tek deneme yapılır; izin gelince kendiliğinden açılır.
                    try_insights, denied, taze = False, True, {}
                    _warn(f"insights izni yok, bu çalışmada bir daha denenmeyecek: {_emsg(e)}")
                else:
                    ins_fail, ins_err = ins_fail + 1, ins_err or _emsg(e)
                    _warn(f"{cid}: insights alınamadı: {_emsg(e)}")
                    if ins_fail >= STREAK_LIMIT and not ins_ok:
                        try_insights = False
        _dondur(rec, _pub(c, rec), taze)
        media[cid] = rec

    if stop is not None:
        _warn(f"veri toplama kesildi: {_emsg(stop)}")
        errors.append(("Graph API'ye erişilemedi, veri güncellenemedi: " if not api_ok else
                       f"Veri toplama yarıda kesildi ({done}/{len(targets)} gönderi güncellendi): ") + _emsg(stop))
    if api_ok:
        # API'nin çalıştığı kesinken alınan kalıcı hata o gönderiye özgüdür: eski sayıları saklayıp işaretle.
        for cid, (c, mid, msg) in gone.items():
            old = media.get(cid, {})
            keep = old if str(old.get("media_id")) == mid else {}
            media[cid] = {**dict.fromkeys(RECORD_KEYS), **keep, "media_id": mid,
                          "permalink": keep.get("permalink") or c.get("permalink"), "error": msg}
        m["updated"] = stamp
    if denied:
        m["insights"] = False
    elif ins_ok:
        m["insights"] = True
    if ins_fail:
        errors.append(f"{ins_fail} gönderide erişim/kaydetme/gönderme verisi alınamadı: {ins_err}")
    m["media"] = dict(sorted(media.items()))
    m["errors"] = errors
    write_json(METRICS, m)
    print(f"Gönderi verisi: {done}/{len(targets)} güncellendi" + (f", {len(gone)} okunamadı" if gone else "")
          + (" · insights: izin yok" if denied else f" · insights: {ins_ok} gönderi" if ins_ok else ""))
    return m


def _kayit(c: dict, mid: str, d: dict, old: dict, stamp: str) -> dict:
    """Gönderinin /{media-id} yanıtından metrics kaydı; insights ve eşleme/dondurma alanları eski kayıttan korunur."""
    return {**{k: old[k] for k in EXTRA_KEYS if k in old},
            "media_id": mid,
            "permalink": d.get("permalink") or old.get("permalink") or c.get("permalink"),
            "likes": _num(d.get("like_count"), _num(old.get("likes"), 0)),
            "comments": _num(d.get("comments_count"), _num(old.get("comments"), 0)),
            **{k: _num(old.get(k)) for k in INSIGHT_KEYS},
            "checked": stamp}


# ---- Suite eşlemesi ve 72 saat dondurması --------------------------------------------------------

def _graph_ts(s) -> datetime | None:
    """Graph API zaman damgası (2026-11-27T16:30:05+0000) -> datetime; çözülemezse None."""
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return _dt(s)


def _caption_key(text) -> str:
    """publish.py'deki kuralla aynı: boşlukları kırpılmış ilk 60 karakter."""
    return " ".join(str(text or "").split())[:60]


def _suite_posts(cal: list[dict]) -> list[dict]:
    """Suite kanalından yayınlanan (Suite'te zamanlanmış, kilitli) post kayıtları; story'ler ve iptal edilenler hariç."""
    cancelled = cancelled_ids()
    return [c for c in cal if isinstance(c, dict) and c.get("id") and c.get("suite_scheduled") and not _is_story(c)
            and not c.get("media_id") and str(c.get("id")) not in cancelled
            and str(c.get("date") or "") >= ESLE_BASLANGIC and _planned(c) is not None]


def _suite_rec(media: dict, cid: str) -> dict | None:
    """Suite eşlemesiyle metrics.json'a yazılmış kayıt (media_id'li); yoksa None."""
    rec = media.get(cid)
    return rec if isinstance(rec, dict) and rec.get("kaynak") == "suite" and rec.get("media_id") else None


def _pub(c: dict, rec: dict | None) -> datetime | None:
    """Gerçek yayın zamanı: Suite postunda /media zaman damgası, API postunda published_at."""
    if rec and rec.get("kaynak") == "suite":
        return _dt(rec.get("yayin"))
    return _dt(c.get("published_at")) if c.get("status") == "published" else None


def _targets(cal: list[dict], media: dict) -> list[tuple[dict, str]]:
    """Sayıları toplanacak postlar: (takvim kaydı, media_id). API ile yayınlananlar ve eşlenmiş Suite postları."""
    out = [(c, str(c["media_id"])) for c in cal if isinstance(c, dict) and c.get("id") and c.get("media_id")
           and c.get("status") == "published" and not _is_story(c)]
    out += [(c, str(r["media_id"])) for c in _suite_posts(cal) if (r := _suite_rec(media, str(c["id"])))]
    return sorted(out, key=lambda x: (str(x[0].get("date")), str(x[0].get("time"))))


def _medya_listesi(ig: str, oldest: datetime) -> list[dict]:
    """Hesabın /media listesi (yeniden eskiye); `oldest`tan eskiye inilince ya da ESLE_SAYFA sayfada durur."""
    out: list[dict] = []
    after = None
    for _ in range(ESLE_SAYFA):
        res = graph.api("GET", f"{ig}/media", fields=MEDIA_LIST_FIELDS, limit=50, after=after)
        data = [d for d in (res.get("data") or []) if isinstance(d, dict) and d.get("id")]
        out += data
        paging = res.get("paging") if isinstance(res.get("paging"), dict) else {}
        after = (paging.get("cursors") or {}).get("after")
        stamps = [ts for d in data if (ts := _graph_ts(d.get("timestamp"))) is not None]
        if not data or not after or not paging.get("next") or (stamps and min(stamps) < oldest):
            break
    return out


def esle(cal: list[dict], m: dict, stamp: str, geri: timedelta = ESLE_GERI) -> int:
    """Suite postlarını hesabın /media listesiyle ±ESLE_TOL zaman farkıyla eşler; yeni eşleşme sayısını döndürür.

    Sonuç yalnız `m["media"]`a yazılır (media_id, permalink, kaynak=suite, yayin, eslesme); kilitli takvim kaydına
    dokunulmaz. Aynı zaman aralığında birden çok aday varsa önce açıklaması tutan, sonra türü tutan, sonra zamana
    en yakın olan seçilir; bir medya yalnız bir kayda, bir kayıt yalnız bir medyaya eşlenir. Bekleyen post yoksa
    API'ye hiç gidilmez. Graph hatası dışarı fırlatılır (çağıran karar verir).
    """
    t, media = now(), m["media"]
    bekleyen = [c for c in _suite_posts(cal) if not _suite_rec(media, str(c["id"]))
                and t - geri <= _planned(c) <= t + ESLE_TOL]
    if not bekleyen:
        return 0
    liste = _medya_listesi(graph.ig_user_id(), min(_planned(c) for c in bekleyen) - ESLE_TOL)
    kullanilan = {str(c["media_id"]) for c in cal if isinstance(c, dict) and c.get("media_id")}
    kullanilan |= {str(r["media_id"]) for r in media.values() if isinstance(r, dict) and r.get("media_id")}
    adaylar = []
    for c in bekleyen:
        p, key, tur = _planned(c), _caption_key(c.get("caption")), ESLE_TUR.get(str(c.get("format")))
        for d in liste:
            ts = _graph_ts(d.get("timestamp"))
            if str(d["id"]) in kullanilan or ts is None or abs(ts - p) > ESLE_TOL:
                continue
            ayni = bool(key) and _caption_key(d.get("caption")) == key
            adaylar.append(((not ayni, bool(tur) and d.get("media_type") != tur, abs(ts - p)), c, d, ts, ayni))
    adaylar.sort(key=lambda x: x[0])
    yeni = 0
    for (_, _, fark), c, d, ts, ayni in adaylar:
        cid, mid = str(c["id"]), str(d["id"])
        if _suite_rec(media, cid) or mid in kullanilan:
            continue
        kullanilan.add(mid)
        media[cid] = {**dict.fromkeys(RECORD_KEYS), "media_id": mid, "permalink": d.get("permalink"),
                      "kaynak": "suite", "yayin": ts.astimezone(TZ).isoformat(timespec="seconds"),
                      "eslesme": {"zaman": stamp, "fark_sn": int(fark.total_seconds()), "aciklama_tutuyor": ayni,
                                  "tur": d.get("media_type")}}
        yeni += 1
        print(f"Suite eşlemesi: {cid} -> {mid} (fark {int(fark.total_seconds())} sn"
              + ("" if ayni else ", açıklama farklı") + ")")
    return yeni


def _dondur(rec: dict, pub: datetime | None, taze: dict | None) -> bool:
    """Yayından ≥72 saat sonra alınmış ilk ölçümü `dondurulmus` alanına yazar. Bir kez yazılır, sonra değişmez.

    `taze`: bu ölçümde alınan insights değerleri; izin yoksa {} (erişim/kaydetme boş dondurulur). None ise insights
    geçici bir hatayla alınamamıştır: kayıttaki eski (72 saatten önceki) değerler dondurulmaz, sonraki ölçüm beklenir.
    """
    checked = _dt(rec.get("checked"))
    if (taze is None or rec.get("dondurulmus") or rec.get("error") or pub is None or checked is None
            or checked - pub < DONDUR or _num(rec.get("likes")) is None):
        return False
    rec["dondurulmus"] = {"saat": int((checked - pub).total_seconds() // 3600), "zaman": rec.get("checked"),
                          "likes": _num(rec.get("likes")), "comments": _num(rec.get("comments")),
                          **{k: _num(taze.get(k)) for k in INSIGHT_KEYS}}
    return True


def _eslenemeyen(cal: list[dict], metrics: dict, t: datetime) -> tuple[list[dict], int]:
    """Saati ESLE_GEC'ten fazla geçmiş ama media_id'si bulunamamış Suite postları ve saati geçmiş Suite post sayısı."""
    media = metrics.get("media") if isinstance(metrics.get("media"), dict) else {}
    due = [c for c in _suite_posts(cal) if _planned(c) < t - ESLE_GEC]
    return [c for c in due if not _suite_rec(media, str(c["id"]))], len(due)


def _hafif_metrics() -> dict | None:
    """Hafif modlar için metrics.json: bozuksa uyarı basılır ve None döner (çağıran dosyaya yazmadan çıkar)."""
    try:
        return load_metrics(kati=True)
    except ValueError as e:
        _warn(f"{e}; hafif modda dosyanın üzerine yazılmıyor, bu adım atlandı")
        return None


def esle_hafif() -> None:
    """--esle: publish adımında (15 dakikada bir) çalışan hafif mod. Yalnız yakın geçmişteki Suite postlarını eşler
    ve 72..120 saatlik postların ilk ölçümünü dondurur. RAPOR.md/scores.json yazılmaz; jeton yoksa sessizce atlanır.
    Hatalar yalnız uyarıdır (çıkış kodu main() sayesinde her durumda 0)."""
    if not os.environ.get("IG_ACCESS_TOKEN"):
        return
    cal = load_calendar()
    cal = [c for c in cal if isinstance(c, dict)] if isinstance(cal, list) else []
    m = _hafif_metrics()
    if m is None:
        return
    t = now()
    stamp = t.isoformat(timespec="seconds")
    degisti = 0
    try:
        degisti += esle(cal, m, stamp, ESLE_GERI_HAFIF)
    except Exception as e:  # noqa: BLE001
        _warn(f"Suite eşlemesi yapılamadı: {_emsg(e)}")
        if _global_error(e):
            return
    media, try_insights = m["media"], True
    for c, mid in _targets(cal, media):
        cid = str(c["id"])
        old = media.get(cid) if isinstance(media.get(cid), dict) else {}
        if str(old.get("media_id")) != mid:
            old = {}
        pub = _pub(c, old or None)
        if old.get("dondurulmus") or old.get("error") or pub is None or not DONDUR <= t - pub <= DONDUR + DONDUR_HAFIF:
            continue
        try:
            d = graph.api("GET", mid, fields=MEDIA_FIELDS)
            if not isinstance(d, dict):
                raise ValueError("beklenmeyen yanıt biçimi")
        except Exception as e:  # noqa: BLE001
            _warn(f"{cid}: dondurma için gönderi verisi alınamadı: {_emsg(e)}")
            if _global_error(e):
                break
            continue
        rec = _kayit(c, mid, d, old, stamp)
        taze: dict | None = None if try_insights else {}
        if try_insights:
            try:
                taze = {k: v for k, v in _insights(mid).items() if k in INSIGHT_KEYS}
                rec.update(taze)
            except Exception as e:  # noqa: BLE001
                if _permission_error(e):
                    # İzin (instagram_manage_insights) yoksa yalnız beğeni/yorum dondurulur; yayın akışı kırılmaz.
                    try_insights, taze = False, {}
                    _warn(f"insights izni yok, yalnız beğeni/yorum donduruluyor: {_emsg(e)}")
                else:
                    # Geçici hata: eski insights dondurulmaz; bu post sonraki çalışmada yeniden denenir.
                    _warn(f"{cid}: insights alınamadı, dondurma sonraki çalışmaya kaldı: {_emsg(e)}")
                    if _global_error(e):
                        break
        if not _dondur(rec, pub, taze):
            continue   # dondurulmayan kayıt yazılmaz: metrics.json 15 dakikada bir boşuna değişmesin
        print(f"Dondurma: {cid} ({rec['dondurulmus']['saat']} saat) beğeni {rec['likes']} yorum {rec['comments']}")
        media[cid] = rec
        degisti += 1
    if degisti:
        m["media"] = dict(sorted(media.items()))
        write_json(METRICS, m)


# ---- Story ve hesap insights (O7) ------------------------------------------------------------------

def _story_listesi(ig: str) -> list[dict]:
    """Yayındaki (son 24 saatteki) story'ler: /{ig-user-id}/stories."""
    out: list[dict] = []
    after = None
    for _ in range(STORY_SAYFA):
        res = graph.api("GET", f"{ig}/stories", fields=STORY_LIST_FIELDS, limit=50, after=after)
        out += [d for d in (res.get("data") or []) if isinstance(d, dict) and d.get("id")]
        paging = res.get("paging") if isinstance(res.get("paging"), dict) else {}
        after = (paging.get("cursors") or {}).get("after")
        if not after or not paging.get("next"):
            break
    return out


def _story_takvim(cal: list[dict]) -> list[dict]:
    """Eşlenebilecek takvim story'leri: iptal edilmemiş, atlanmamış, tarih-saati okunabilen story kayıtları."""
    cancelled = cancelled_ids()
    return [c for c in cal if isinstance(c, dict) and c.get("id") and _is_story(c) and str(c["id"]) not in cancelled
            and c.get("status") != "skipped" and _planned(c) is not None]


def _suite_story(c: dict) -> bool:
    """Business Suite'ten yayınlanan story: Suite'te zamanlanmış (suite_scheduled) ya da via=suite."""
    return bool(c.get("suite_scheduled")) or c.get("via") == "suite"


def story_esle(cal: list[dict], stories: dict, stamp: str) -> int:
    """metrics.json story kayıtlarını takvim story'leriyle eşler; yeni eşleşme sayısını döndürür.

    API ile yayınlanmış (media_id'li) kayıt doğrudan id ile bağlanır. Diğerlerinde planlanan zamanın ±ESLE_TOL
    içinde TEK story varsa ve o story'nin ±ESLE_TOL içinde de tek takvim kaydı varsa eşlenir; birden çok ya da sıfır
    aday varsa eşlenmez. Sonuç yalnız story kaydına (`takvim_id`, `eslesme`) yazılır; takvime asla yazılmaz.
    """
    kayitlar = _story_takvim(cal)
    yeni = 0
    by_mid = {str(c["media_id"]): c for c in kayitlar if c.get("media_id")}
    for sid, r in stories.items():
        if not r.get("takvim_id") and sid in by_mid:
            r["takvim_id"], r["eslesme"] = str(by_mid[sid]["id"]), {"zaman": stamp, "yol": "media_id"}
            yeni += 1
    bagli = {str(r["takvim_id"]) for r in stories.values() if r.get("takvim_id")}
    zaman = {sid: ts for sid, r in stories.items() if (ts := _dt(r.get("yayin"))) is not None}
    serbest = [c for c in kayitlar if not c.get("media_id")]
    for c in serbest:
        cid, p = str(c["id"]), _planned(c)
        if cid in bagli:
            continue
        aday = [sid for sid, ts in zaman.items() if abs(ts - p) <= ESLE_TOL]
        if len(aday) != 1 or stories[aday[0]].get("takvim_id"):
            continue
        sid = aday[0]
        if sum(1 for k in serbest if abs(_planned(k) - zaman[sid]) <= ESLE_TOL) != 1:
            continue
        stories[sid]["takvim_id"] = cid
        stories[sid]["eslesme"] = {"zaman": stamp, "fark_sn": int(abs(zaman[sid] - p).total_seconds())}
        bagli.add(cid)
        yeni += 1
        print(f"Story eşlemesi: {cid} -> {sid} (fark {int(abs(zaman[sid] - p).total_seconds())} sn)")
    return yeni


def _link_testi(test: tuple[str, dict] | None, neden: str, today: str) -> tuple[dict, dict]:
    """Link sticker dokunuşu API'de dönüyor mu: tek story'nin insights yanıtında (metrik adları ve navigation
    kırılımı) link/sticker geçen anahtar aranır. Döndürür: (link_testi kaydı, navigation kırılımı)."""
    if test is None:
        return {"tarih": today, "sonuc": "denenmedi", "not": neden}, {}
    sid, degerler = test
    kir: dict[str, int] = {}
    ek = ""
    try:
        kir = _kirilim(graph.api("GET", f"{sid}/insights", metric="navigation", breakdown=STORY_KIRILIM))
    except Exception as e:  # noqa: BLE001
        if _global_error(e) or _permission_error(e) or getattr(e, "transient", False):
            return {"tarih": today, "sonuc": "denenmedi", "not": f"navigation kırılımı alınamadı: {_emsg(e)}"}, {}
        ek = f"; navigation kırılımı alınamadı: {_emsg(e)}"
    anahtarlar = [*degerler, *kir]
    bulunan = [k for k in anahtarlar if any(a in k.lower() for a in LINK_ANAHTAR)]
    kayit = {"tarih": today, "story": sid, "anahtarlar": anahtarlar}
    if bulunan:
        return {**kayit, "sonuc": "donuyor", "not": f"yanıtta link/sticker anahtarı var: {', '.join(bulunan)}"}, kir
    return {**kayit, "sonuc": "donmuyor", "not": LINK_NOT + ek}, kir


def _kirilim_ekle(rec: dict, sid: str) -> bool:
    """Link testi "dönüyor" ise story'nin navigation kırılımını kayda ekler. Hata olursa uyarı basar ve False
    döndürür (bu çalışmada kırılım bir daha istenmez); izin/token hatası da yalnız uyarıdır."""
    try:
        kir = _kirilim(graph.api("GET", f"{sid}/insights", metric="navigation", breakdown=STORY_KIRILIM))
    except Exception as e:  # noqa: BLE001
        _warn(f"story {sid}: navigation kırılımı alınamadı: {_emsg(e)}")
        return False
    if kir:
        rec["navigation_kirilim"] = kir
    return True


def _story_iz(m: dict) -> str:
    """Yazma kararı için karşılaştırma izi: `checked` dışındaki story verisi, link testi ve başlangıç."""
    st = {k: {a: b for a, b in v.items() if a != "checked"} for k, v in m["stories"].items()}
    return json.dumps([st, m.get("link_testi"), m.get("story_baslangic")], sort_keys=True, ensure_ascii=False)


def story_hafif() -> None:
    """--story: yayındaki story'lerin insights son değerini metrics.json "stories" altına yazar, takvim story'leriyle
    eşler ve link dokunuşu API testini bir kez yapar. Jeton yoksa sessizce atlanır; izin yoksa yalnız uyarı basılır
    (liste ve eşleme yine yazılır). Bir metrik hata verirse yalnız o metrik atlanır. Veri değişmediyse dosya yazılmaz.
    """
    if not os.environ.get("IG_ACCESS_TOKEN"):
        return
    cal = load_calendar()
    cal = [c for c in cal if isinstance(c, dict)] if isinstance(cal, list) else []
    m = _hafif_metrics()
    if m is None:
        return
    t = now()
    stamp = t.isoformat(timespec="seconds")
    try:
        liste = _story_listesi(graph.ig_user_id())
    except Exception as e:  # noqa: BLE001
        _warn(("story listesi için izin yok" if _permission_error(e) else "story listesi alınamadı")
              + f", story insights atlandı: {_emsg(e)}")
        return
    iz = _story_iz(m)
    stories = m["stories"]
    m.setdefault("story_baslangic", stamp)
    link_eski = m.get("link_testi") if isinstance(m.get("link_testi"), dict) else {}
    kirilim_iste = link_eski.get("sonuc") == "donuyor"
    desteksiz: set[str] = set()
    izin, dur, alinan, seri = True, False, 0, 0   # seri: insights'ı art arda alınamayan story sayısı
    test: tuple[str, dict] | None = None
    for d in liste:
        sid = str(d["id"])
        ts = _graph_ts(d.get("timestamp"))
        old = stories.get(sid, {})
        rec = {**old, "media_id": sid, "permalink": d.get("permalink") or old.get("permalink"),
               "media_type": d.get("media_type") or old.get("media_type"),
               "yayin": ts.astimezone(TZ).isoformat(timespec="seconds") if ts else old.get("yayin")}
        if izin and not dur:
            try:
                degerler, hatalar = _metrik_cek(f"{sid}/insights", STORY_METRICS, desteksiz)
                degerler = {k: v for k, v in degerler.items() if k in STORY_METRICS}
                if degerler:
                    rec.update(degerler)
                    rec["checked"] = stamp
                    alinan, seri = alinan + 1, 0
                    test = test or (sid, degerler)
                    if kirilim_iste:
                        kirilim_iste = _kirilim_ekle(rec, sid)
                else:
                    seri += 1
                for k, msg in hatalar.items():
                    _warn(f"story {sid}: {k} alınamadı, atlandı: {msg}")
            except Exception as e:  # noqa: BLE001
                if _permission_error(e):
                    izin = False
                    _warn(f"story insights izni yok, bu çalışmada bir daha denenmeyecek: {_emsg(e)}")
                else:
                    seri += 1
                    _warn(f"story {sid}: insights alınamadı: {_emsg(e)}")
                    dur = _global_error(e)
            if not dur and seri >= STREAK_LIMIT:
                dur = True
                _warn(f"art arda {seri} story'de insights alınamadı, kalan story'ler bu çalışmada denenmeyecek")
        stories[sid] = rec
    if desteksiz:
        _warn(f"bu çalışmada desteklenmeyen story metrikleri atlandı: {', '.join(sorted(desteksiz))}")
    n = story_esle(cal, stories, stamp)
    if link_eski.get("sonuc") not in ("donuyor", "donmuyor"):
        neden = ("story insights izni yok" if not izin else "yayında story yok" if not liste
                 else "story insights alınamadı")
        try:
            yeni, kir = _link_testi(test, neden, stamp[:10])
        except Exception as e:  # noqa: BLE001
            yeni, kir = {"tarih": stamp[:10], "sonuc": "denenmedi", "not": f"test yapılamadı: {_emsg(e)}"}, {}
        if kir and test:
            stories[test[0]]["navigation_kirilim"] = kir
        if (yeni.get("sonuc"), yeni.get("not")) != (link_eski.get("sonuc"), link_eski.get("not")):
            m["link_testi"] = yeni
            print(f"Link dokunuşu API testi: {LINK_TR[yeni['sonuc']]} · {yeni['not']}")
    m["stories"] = dict(sorted(stories.items()))
    if _story_iz(m) != iz:
        write_json(METRICS, m)
    print(f"Story: {len(liste)} yayında · insights {alinan}" + (" (izin yok)" if not izin else "")
          + (f" · {n} yeni eşleşme" if n else ""))


def hesap_insights(m: dict, stamp: str) -> int:
    """Son tamamlanan iki haftanın (pazartesi–pazar) hesap insights'ı: /{ig-user-id}/insights, period=day,
    metric_type=total_value, since/until. `m["hesap_insights"]["<pazartesi>"]`e yazar; güncellenen hafta sayısını
    döndürür. Hata veren metrik tek tek atlanır (eski değeri korunur); izin/token hatası dışarı fırlatılır."""
    ig, t = graph.ig_user_id(), now()
    bu = _pazartesi(t.astimezone(TZ).date()) - WEEK
    hesap, desteksiz, n = m.setdefault("hesap_insights", {}), set(), 0
    for bas in (bu - WEEK, bu):
        since = datetime(bas.year, bas.month, bas.day, tzinfo=TZ)
        degerler, hatalar = _metrik_cek(f"{ig}/insights", HESAP_METRICS, desteksiz, period="day",
                                        metric_type="total_value", since=int(since.timestamp()),
                                        until=int((since + WEEK).timestamp()))
        for k in HESAP_METRICS:   # önceki haftada desteklenmediği görülen metrik bu haftada da kayda düşülür
            if k in desteksiz and k not in degerler and k not in hatalar:
                hatalar[k] = "desteklenmiyor (bu çalışmada yeniden istenmedi)"
        rec = {**hesap.get(bas.isoformat(), {}), "bitis": (bas + timedelta(days=6)).isoformat(),
               **{k: v for k, v in degerler.items() if k in HESAP_METRICS}}
        if hatalar:
            rec["hatalar"] = hatalar
            _warn(f"hesap insights {bas.isoformat()}: atlanan metrik: {', '.join(sorted(hatalar))}")
        else:
            rec.pop("hatalar", None)
        if degerler:
            rec["checked"] = stamp
            n += 1
        hesap[bas.isoformat()] = rec
    m["hesap_insights"] = dict(sorted(hesap.items()))
    return n


# ---- Puanlama ----------------------------------------------------------------------------------

def _measured(cal: list[dict], metrics: dict) -> tuple[list[dict], str]:
    """Hesaba giren gönderiler (puanlarıyla) ve kullanılan puan formülünün açıklaması.

    Yeni gönderi haksız yere düşük görünmesin diye yalnız ölçümü yayından en az 48 saat sonra alınmış olanlar
    girer. Kaydetme/gönderme terimleri, karşılaştırma adil kalsın diye ancak hesaba giren her gönderide
    varsa eklenir (yoksa biri insights'lı, diğeri insights'sız iki gönderi aynı terazide tartılmış olurdu).
    """
    media = metrics.get("media") if isinstance(metrics.get("media"), dict) else {}
    t = now()
    rows = []
    suite = {str(c["id"]) for c in _suite_posts(cal) if _suite_rec(media, str(c["id"]))}   # eşlenmiş Suite postları
    for c in cal:
        if not isinstance(c, dict) or _is_story(c) or (c.get("status") != "published" and str(c.get("id")) not in suite):
            continue
        rec = media.get(str(c.get("id")))
        if not isinstance(rec, dict) or rec.get("error") or _num(rec.get("likes")) is None:
            continue
        pub = _pub(c, rec) if str(c.get("id")) in suite else _when(c)
        checked = _dt(rec.get("checked")) or t   # ölçüm zamanı kayıtlı değilse şimdi alınmış sayılır
        if pub is None or checked - pub < MATURE:
            continue
        products = c.get("products") if isinstance(c.get("products"), list) else []
        cats = list(dict.fromkeys(str(p["category"]) for p in products if isinstance(p, dict) and p.get("category")))
        rows.append({"id": c.get("id"), "when": pub,
                     "title": str(c.get("title") or c.get("name") or c.get("id") or ""),
                     "permalink": rec.get("permalink") or c.get("permalink"),
                     "likes": _num(rec.get("likes"), 0), "comments": _num(rec.get("comments"), 0),
                     **{k: _num(rec.get(k)) for k in INSIGHT_KEYS},
                     "category": cats or ([str(c["category"])] if c.get("category") else []),
                     "format": c.get("format"), "theme": c.get("theme"), "hour": _hour(c, pub)})
    extra = [(k, w) for k, w in SCORE_EXTRA if rows and all(r[k] is not None for r in rows)]
    for r in rows:
        r["score"] = r["likes"] + 3 * r["comments"] + sum(w * r[k] for k, w in extra)
    formula = "beğeni + 3×yorum" + "".join(f" + {w}×{METRIC_TR[k]}" for k, w in extra)
    partial = [METRIC_TR[k] for k, w in SCORE_EXTRA if (k, w) not in extra and any(r[k] is not None for r in rows)]
    if partial:
        formula += f" ({' ve '.join(partial)} verisi her gönderide olmadığından puana katılmadı)"
    return rows, formula


def _groups(rows: list[dict], dim: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        v = r[dim]
        for key in v if isinstance(v, list) else [v]:
            if key not in (None, ""):
                out.setdefault(str(key), []).append(r)
    return out


def _ranked(rows: list[dict], dim: str, min_n: int = 1, field: str = "score") -> list[tuple[str, list[dict], float]]:
    """Bir boyutun grupları: (anahtar, gönderiler, ortalama); ortalamaya göre azalan."""
    out = [(k, g, _mean([r[field] for r in g])) for k, g in _groups(rows, dim).items() if len(g) >= min_n]
    return sorted(out, key=lambda x: (-x[2], x[0]))


def scores(cal: list[dict], metrics: dict) -> dict:
    """Planlayıcı için 0..1 arası göreli puanlar; data/scores.json'a yazar ve döndürür.

    Gönderi puanı = beğeni + 3×yorum (+ 4×kaydetme + 5×gönderme, veri varsa). Grup puanı = grubun ortalamasının
    tüm gönderilerin ortalamasına oranının yarısı, en çok 1 (0,5 = ortalama, 1 = ortalamanın en az iki katı).
    2'den az gönderisi olan grup yazılmaz; hesaba giren gönderi 6'dan azsa bütün gruplar boş kalır.
    """
    rows, _ = _measured(cal, metrics)
    out: dict = {"updated": now().isoformat(timespec="seconds"), "n": len(rows), **{dim: {} for dim in DIMS}}
    overall = _mean([r["score"] for r in rows])
    if len(rows) >= MIN_POSTS and overall > 0:
        for dim in DIMS:
            vals = {k: round(min(1.0, avg / overall / 2), 2) for k, _, avg in _ranked(rows, dim, MIN_GROUP)}
            out[dim] = dict(sorted(vals.items(), key=lambda kv: (-kv[1], kv[0])))
    write_json(SCORES, out)
    return out


# ---- Rapor: biçimlendirme ----------------------------------------------------------------------

def _n(v, nd: int = 0) -> str:
    """Türkçe sayı yazımı: 2712 -> 2.712 · 45.25 -> 45,2 · None -> —"""
    return "—" if v is None else f"{v:,.{nd}f}".translate(str.maketrans(",.", ".,"))


def _signed(v: int) -> str:
    return "0" if v == 0 else f"{v:+,d}".replace(",", ".")


def _rel(avg: float, overall: float) -> str:
    """Grubun genel ortalamaya göre konumu: +%40, -%12."""
    if overall <= 0:
        return "—"
    p = round((avg / overall - 1) * 100)
    return f"+%{p}" if p > 0 else f"-%{-p}" if p < 0 else "%0"


def _cap(s: str) -> str:
    return ("İ" if s[:1] == "i" else s[:1].upper()) + s[1:]


def _one(s) -> str:
    return " ".join(str(s).split())


def _md(s) -> str:
    """Dış kaynaklı metni tek satıra indirir; `<…>` HTML etiketi sanılıp yutulmasın diye `<` kaçırılır."""
    return _one(s).replace("<", "\\<")


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _day(d, t: datetime) -> str:
    """24 Kasım (yıl bu yıldan farklıysa yılıyla)."""
    return tr_date(d, False) + (f" {d.year}" if d.year != t.year else "")


def _slot(hour: str) -> str:
    """Saat dilimi: "19" -> 19:00–19:59"""
    return f"{int(hour):02d}:00–{int(hour):02d}:59"


def _table(head: list[str], rows: list[list], right: tuple[int, ...] = ()) -> list[str]:
    """Kaynak metinde de hizalı duran Markdown tablosu; `right` sütunları sağa yaslanır."""
    grid = [[unicodedata.normalize("NFC", _md("—" if v is None else v)).replace("|", "\\|") for v in r]
            for r in [head, *rows]]
    w = [max(3, *(len(r[i]) for r in grid)) for i in range(len(head))]

    def line(r: list[str]) -> str:
        return "| " + " | ".join(c.rjust(w[i]) if i in right else c.ljust(w[i]) for i, c in enumerate(r)) + " |"

    rule = "| " + " | ".join("-" * (w[i] - 1) + ":" if i in right else "-" * w[i] for i in range(len(head))) + " |"
    return [line(grid[0]), rule, *(line(r) for r in grid[1:])]


# ---- Rapor: bölümler ---------------------------------------------------------------------------

def _delta(acc: list[dict], days: int, tol: int) -> str:
    """Son kayıt ile yaklaşık `days` gün önceki kayıt arasındaki takipçi farkı; başvuru kaydıyla birlikte."""
    last, d0 = acc[-1], _date(acc[-1]["date"])
    ref, miss = None, tol + 1
    for a in acc[:-1]:
        off = abs((d0 - _date(a["date"])).days - days)
        if off < miss:
            ref, miss = a, off
    if ref is None:
        return "veri yok"
    diff = _num(last["followers"]) - _num(ref["followers"])
    return f"{_signed(diff)} ({tr_date(_date(ref['date']), False)}: {_n(ref['followers'])})"


def _summary(cal: list[dict], metrics: dict, rows: list[dict], t: datetime) -> list[str]:
    acc = sorted((a for a in metrics.get("account") or [] if isinstance(a, dict) and _date(a.get("date"))
                  and _num(a.get("followers")) is not None), key=lambda a: str(a["date"]))
    body = []
    if acc:
        d = _date(acc[-1]["date"])
        body.append(["Takipçi" + ("" if d == t.date() else f" ({_day(d, t)} itibarıyla)"), _n(acc[-1]["followers"])])
        body += [[f"{days} günlük değişim", _delta(acc, days, tol)] for days, tol in ((7, 2), (30, 5))]
    else:
        body.append(["Takipçi", "veri yok"])
    week = [c for c in cal if c.get("status") == "published" and (w := _when(c)) is not None and t - WEEK < w <= t]
    stories = sum(1 for c in week if _is_story(c))
    body.append(["Son 7 günde yayınlanan", f"{len(week) - stories} gönderi · {stories} story"])

    def pair(rs: list[dict]) -> str:
        return f"{_n(_mean([r['likes'] for r in rs]), 1)} / {_n(_mean([r['comments'] for r in rs]), 1)}"

    recent = [r for r in rows if t - r["when"] <= MONTH]
    if recent:
        body.append([f"Ort. beğeni / yorum · son 30 gün ({len(recent)} gönderi)", pair(recent)])
    if rows and len(recent) != len(rows):
        body.append([f"Ort. beğeni / yorum · tümü ({len(rows)} gönderi)", pair(rows)])
    if not rows:
        body.append(["Ort. beğeni / yorum", "veri yok"])
    base = recent or rows
    if any(r[k] is not None for r in base for k in METRIC_TR):
        cells = [_n(_mean(xs), 1) if (xs := [r[k] for r in base if r[k] is not None]) else "—" for k in METRIC_TR]
        scope = "son 30 gün" if recent else "tümü"
        body.append([f"Ort. {' / '.join(METRIC_TR.values())} · {scope}", " / ".join(cells)])
    return _table(["Gösterge", "Değer"], body)


def _zamanlanmamis(cal: list[dict], t: datetime) -> list[datetime]:
    """Business Suite'e henüz zamanlanmamış yaklaşan Suite story'lerinin planlanan zamanları (sıralı)."""
    return sorted(w for c in cal if _is_story(c) and c.get("channel") == "suite" and not c.get("suite_scheduled")
                  and c.get("status") not in ("published", "skipped", "missed", "error")
                  and (w := _planned(c)) is not None and w > t)


def _health(cal: list[dict], t: datetime) -> list[str]:
    recent = [c for c in cal if (w := _when(c)) is not None and t - WEEK < w <= t]

    def row(label: str, items: list[dict]) -> list:
        stories = sum(1 for c in items if _is_story(c))
        return [label, len(items) - stories, stories, len(items)]

    body = [row(label, [c for c in recent if c.get("status") == st]) for st, label in STATUS_TR]
    # Suite'te zamanlanmış postları Business Suite yayınlar (yayıncı değil); onlar "Suite eşlemesi" bölümünde izlenir.
    stuck = [c for c in recent if c.get("status") in ("planned", "draft") and _when(c) < t - GRACE
             and not (c.get("suite_scheduled") and not _is_story(c))]
    if stuck:
        body.append(row("Bekliyor (saati geçmiş planned/draft)", stuck))
    out = _table(["Durum", "Gönderi", "Story", "Toplam"], body, right=(1, 2, 3))
    errs = sorted((c for c in recent if c.get("status") == "error"), key=_when)
    if errs:
        out += ["", "Hata veren kayıtlar:", ""]
        out += [f"- `{c.get('id', '?')}` — {_md(_short(_one(c.get('error') or 'hata metni kaydedilmemiş'), 240))}"
                for c in errs]
    else:
        out += ["", "Hata veren kayıt yok."]
    if stuck:
        drafts = sum(1 for c in stuck if c.get("status") == "draft")  # yayıncı yalnız "planned" kayıtları işler
        why = [] if drafts == len(stuck) else [
            "yayın iş akışını kontrol et" if CFG.get("live") is True else
            "config.json'da `live` kapalı olduğu için yayıncı deneme modunda çalışıyor"]
        if drafts:
            why.append(f"taslak (draft) durumundaki {drafts} kayıt `planned` yapılmadan yayınlanmaz")
        out += ["", f"Saati geçtiği halde yayınlanmamış {len(stuck)} kayıt var; {'; '.join(why)}."]
    suite = _zamanlanmamis(cal, t)
    out += ["", f"Business Suite'e henüz zamanlanmamış yaklaşan story: **{len(suite)}** "
                f"(en yakını {tr_date(suite[0])} {suite[0]:%H:%M})." if suite else
            "Business Suite'e zamanlanmayı bekleyen yaklaşan story yok."]
    return out


def _top(rows: list[dict], formula: str, t: datetime) -> list[str]:
    if not rows:
        return ["Henüz hesaba giren gönderi yok: ölçümün yayından en az 48 saat sonra alınmış olması gerekir."]
    extra = [k for k in ("saved", "shares", "reach") if any(r[k] is not None for r in rows)]
    head = ["#", "Puan", "Beğeni", "Yorum", *(_cap(METRIC_TR[k]) for k in extra), "Tarih", "Başlık", "Bağlantı"]
    best = sorted(rows, key=lambda r: (-r["score"], -r["when"].timestamp()))[:5]
    body = [[i, _n(r["score"]), _n(r["likes"]), _n(r["comments"]), *(_n(r[k]) for k in extra), _day(r["when"], t),
             _short(_one(r["title"]), 48), f"[aç]({r['permalink']})" if r["permalink"] else "—"]
            for i, r in enumerate(best, 1)]
    return [*_table(head, body, right=tuple(range(4 + len(extra)))), "",
            f"Puan = {formula}. Hesaba giren: ölçümü yayından en az 48 saat sonra alınmış {len(rows)} gönderi."]


def _dim_table(title: str, data: list[tuple[str, list[dict], float]], overall: float, planner, label) -> list[str]:
    planner = planner if isinstance(planner, dict) else {}
    head = [title, "Gönderi", "Ort. puan", "Ort. beğeni", "Ort. yorum", "Ortalamaya göre"]
    body = [[label(k), len(g), _n(avg, 1), _n(_mean([r["likes"] for r in g]), 1),
             _n(_mean([r["comments"] for r in g]), 1), _rel(avg, overall)] for k, g, avg in data]
    if planner:
        head.append("Planlayıcı puanı")
        for (k, _, _), cells in zip(data, body):
            cells.append(_n(planner[k], 2) if isinstance(planner.get(k), (int, float)) else "—")
    return _table(head, body, right=tuple(range(1, len(head))))


def _compare(rows: list[dict], sc: dict) -> list[str]:
    overall = _mean([r["score"] for r in rows])
    out: list[str] = []
    for title, dim, label in (("Biçim", "format", lambda k: _cap(FORMAT_TR.get(k, k))),
                              ("Tema", "theme", lambda k: THEME_TR.get(k, k)),
                              ("Saat", "hour", _slot)):
        data = _ranked(rows, dim)
        if data:
            out += [*_dim_table(title, data, overall, sc.get(dim), label), ""]
    if not out:
        return ["Karşılaştırılacak veri yok: hesaba giren gönderi ya da takvimde biçim/tema bilgisi bulunmuyor."]
    return [*out, "Ortalamaya göre: grubun ortalama puanının tüm gönderilerin ortalamasından farkı. "
                  f"Planlayıcı puanı (0–1) en az {MIN_GROUP} gönderisi olan gruplara, toplam en az {MIN_POSTS} "
                  "gönderi varken yazılır; 0,50 ortalama demektir."]


def _categories(rows: list[dict], sc: dict) -> list[str]:
    data = _ranked(rows, "category", MIN_GROUP)
    if len(rows) < MIN_POSTS or not data:
        return [f"Kategori karşılaştırması için veri yetersiz: hesaba giren en az {MIN_POSTS} gönderi ve kategori "
                f"başına en az {MIN_GROUP} gönderi gerekir (şu an {len(rows)} gönderi, koşulu sağlayan "
                f"{len(data)} kategori)."]
    overall = _mean([r["score"] for r in rows])
    best, weak = data[:5], data[5:][-3:]
    out = [f"**En iyi {len(best)}**", "", *_dim_table("Kategori", best, overall, sc.get("category"), str)]
    if weak:
        out += ["", f"**En zayıf {len(weak)}**", "", *_dim_table("Kategori", weak, overall, sc.get("category"), str)]
    else:
        out += ["", f"Yalnız {len(data)} kategoride en az {MIN_GROUP} gönderi var; hepsi yukarıdaki tabloda, ayrı bir "
                    "en zayıf listesi çıkarılmadı."]
    return out


def _suite_esleme(cal: list[dict], metrics: dict, t: datetime) -> list[str]:
    """Business Suite'ten yayınlanan postların /media eşlemesi: oran ve eşlenemeyenlerin listesi."""
    miss, due = _eslenemeyen(cal, metrics, t)
    if not due:
        return [f"{tr_date(_dt(ESLE_BASLANGIC + 'T00:00') or t)} sonrasında saati gelmiş Suite postu yok."]
    out = [f"Saati gelmiş {due} Suite postunun **{due - len(miss)}** tanesi `media_id` ile eşlendi "
           f"(planlanan saat ±{int(ESLE_TOL.total_seconds() // 60)} dk; sonuç `data/metrics.json`, takvim değişmez)."]
    if miss:
        out += ["", f"Eşlenemeyen {len(miss)} post (yayınlanmamış, saati kaymış ya da silinmiş olabilir; permalink'i "
                    "elle kontrol et):", ""]
        out += [f"- `{c.get('id')}` · {tr_date(_planned(c))} {_planned(c):%H:%M} · "
                f"{_md(_short(_one(c.get('title') or ''), 60))}" for c in sorted(miss, key=_planned)]
    return out


def _upcoming(cal: list[dict], t: datetime) -> list[str]:
    pending = [(w, c) for c in cal if c.get("status") in ("planned", "draft")
               and (w := _planned(c)) is not None and w > t]
    today = t.date()
    start = today if any(w.date() == today for w, _ in pending) else today + timedelta(days=1)
    body, shown = [], []
    for i in range(7):
        d = start + timedelta(days=i)
        items = [c for w, c in pending if w.date() == d]
        stories = sum(1 for c in items if _is_story(c))
        body.append([tr_date(d) + (" (bugün)" if d == today else ""), len(items) - stories, stories])
        shown += items
    stories = sum(1 for c in shown if _is_story(c))
    body.append(["**Toplam**", len(shown) - stories, stories])
    out = _table(["Gün", "Gönderi", "Story"], body, right=(1, 2))
    drafts = sum(1 for c in shown if c.get("status") == "draft")
    if drafts:
        out += ["", f"Bunlardan {drafts} tanesi taslak (onay bekliyor)."]
    if not shown:
        out += ["", "Önümüzdeki 7 gün için planlanmış paylaşım yok; planlayıcının çalıştığını kontrol et."]
    return out


def _advice(rows: list[dict]) -> list[str]:
    """Veriden türeyen kural tabanlı öneriler (en çok 4). Veri yetmiyorsa bunu söyler, öneri uydurmaz."""
    if len(rows) < MIN_POSTS:
        return [f"Performans önerisi için veri yetersiz: ölçümü yayından en az 48 saat sonra alınmış en az "
                f"{MIN_POSTS} gönderi gerekir (şu an {len(rows)}). Öneri üretilmedi."]
    overall = _mean([r["score"] for r in rows])
    if overall <= 0:
        return ["Hesaba giren gönderilerin hiçbiri etkileşim almamış; karşılaştırma yapılamadı. Öneri üretilmedi."]

    def more(a: float, b: float) -> int:   # a, b'den yüzde kaç fazla
        return round((a / b - 1) * 100)

    def less(a: float) -> int:             # a, genel ortalamadan yüzde kaç az
        return round((1 - a / overall) * 100)

    tips = []
    fmt = _ranked(rows, "format", MIN_GROUP)
    if len(fmt) >= 2:
        (bk, bg, ba), (wk, wg, wa) = fmt[0], fmt[-1]
        best, worst = FORMAT_TR.get(bk, bk), FORMAT_TR.get(wk, wk)
        if wa > 0 and ba / wa - 1 >= NOTABLE:
            tips.append(f"{_cap(best)} gönderileri {worst} gönderilerinden %{more(ba, wa)} daha fazla etkileşim aldı "
                        f"(ortalama puan {_n(ba, 1)} ve {_n(wa, 1)}; {len(bg)} ve {len(wg)} gönderi). "
                        f"Haftalık {best} sayısı artırılabilir.")
        elif wa <= 0 < ba:
            tips.append(f"{_cap(best)} gönderileri ortalama {_n(ba, 1)} puan alırken {worst} gönderileri hiç "
                        f"etkileşim almadı ({len(bg)} ve {len(wg)} gönderi). Haftalık {best} sayısı artırılabilir.")
    theme = _ranked(rows, "theme", MIN_GROUP)
    if theme and theme[0][2] / overall - 1 >= NOTABLE:
        (bk, bg, ba), (wk, wg, wa) = theme[0], theme[-1]
        best = THEME_TR.get(bk, bk)
        s = (f"En yüksek etkileşimi “{best}” teması aldı: genel ortalamanın %{more(ba, overall)} üzerinde "
             f"({len(bg)} gönderi)")
        if len(theme) >= 2 and 1 - wa / overall >= NOTABLE:
            s += f"; en düşüğü “{THEME_TR.get(wk, wk)}” teması (%{less(wa)} altında, {len(wg)} gönderi)"
        tips.append(f"{s}. Takvimde “{best}” temasına daha sık yer verilebilir.")
    cat = _ranked(rows, "category", MIN_GROUP)
    if cat and cat[0][2] / overall - 1 >= NOTABLE:
        (bk, bg, ba), (wk, wg, wa) = cat[0], cat[-1]
        s = f"En çok etkileşim alan kategori {bk}: genel ortalamanın %{more(ba, overall)} üzerinde ({len(bg)} gönderi)"
        if len(cat) >= 2 and 1 - wa / overall >= NOTABLE:
            s += f"; en zayıfı {wk} (%{less(wa)} altında, {len(wg)} gönderi)"
        tips.append(f"{s}. {bk} ürünlerine takvimde öncelik verilebilir.")
    talk = _ranked(rows, "theme", MIN_GROUP, "comments")
    comments = _mean([r["comments"] for r in rows])
    if talk and talk[0][2] > 0 and talk[0][2] >= comments * (1 + NOTABLE):
        k, g, avg = talk[0]
        tips.append(f"En çok yorum alan konu: “{THEME_TR.get(k, k)}” teması (gönderi başına {_n(avg, 1)} yorum; "
                    f"genel ortalama {_n(comments, 1)}; {len(g)} gönderi).")
    hour = _ranked(rows, "hour", MIN_GROUP)
    if len(hour) >= 2:
        (bk, bg, ba), (wk, wg, wa) = hour[0], hour[-1]
        if wa > 0 and ba / wa - 1 >= NOTABLE:
            tips.append(f"{_slot(bk)} arasında yayınlanan gönderiler {_slot(wk)} arasındakilerden %{more(ba, wa)} "
                        f"daha fazla etkileşim aldı ({len(bg)} ve {len(wg)} gönderi). Yeni gönderilerde {_slot(bk)} "
                        "aralığı öne alınabilir.")
    return tips[:4] or [f"Biçim, tema, kategori ve saat grupları arasında %{round(NOTABLE * 100)}'i aşan bir fark "
                        f"görülmedi ya da karşılaştırılacak grup yok (grup başına en az {MIN_GROUP} gönderi gerekir). "
                        "Öneri üretilmedi."]


def _aylik_tema(rows: list[dict], t: datetime) -> list[str]:
    """O16: geçen takvim ayının tema × gün tablosu (ortalama puan ve gönderi sayısı n) ve yalnız öneri.

    Takvime, config.json'a ve scores.json'a hiçbir şey yazmaz. Rapor her gün yeniden üretildiğinden ay boyunca
    aynı (geçen ayın) tablosu görünür; ayın ilk pazartesisi de dahil. Ölçümlü gönderi yoksa yalnız n=0 notu yazılır.
    """
    bu_ay = t.astimezone(TZ).date().replace(day=1)
    gecen = (bu_ay - timedelta(days=1)).replace(day=1)
    ay = [r for r in rows if gecen <= r["when"].astimezone(TZ).date() < bu_ay]
    baslik = f"{AY[gecen.month - 1]} {gecen.year}"
    if not ay:
        return [f"{baslik}: hesaba giren gönderi yok (n=0). Tablo ve öneri üretilmedi."]
    gun = lambda r: r["when"].astimezone(TZ).weekday()  # noqa: E731
    body = []
    for k, g, _ in sorted(_ranked(ay, "theme"), key=lambda x: (-len(x[1]), x[0])):
        cells = []
        for d in range(7):
            gd = [r["score"] for r in g if gun(r) == d]
            cells.append(f"{_n(_mean(gd), 1)} (n={len(gd)})" if gd else "—")
        body.append([THEME_TR.get(k, k), *cells, f"{_n(_mean([r['score'] for r in g]), 1)} (n={len(g)})"])
    out = [f"{baslik} · hesaba giren {len(ay)} gönderi · hücre: ortalama puan (n)", "",
           *_table(["Tema", *GUN_KISA, "Toplam"], body, right=tuple(range(1, 9))), ""]
    if len(ay) < MIN_POSTS:
        return out + [f"Öneri için veri yetersiz: ayda en az {MIN_POSTS} gönderi gerekir (n={len(ay)})."]
    overall = _mean([r["score"] for r in ay])
    tips = []
    rk = _ranked(ay, "theme", MIN_GROUP)
    if len(rk) >= 2 and overall > 0 and rk[-1][2] > 0 and rk[0][2] / rk[-1][2] - 1 >= NOTABLE:
        (bk, bg, ba), (wk, wg, wa) = rk[0], rk[-1]
        tips.append(f"Tema: {THEME_TR.get(bk, bk)} ({_rel(ba, overall)}, n={len(bg)}) en yüksek, "
                    f"{THEME_TR.get(wk, wk)} ({_rel(wa, overall)}, n={len(wg)}) en düşük.")
    gunler = sorted(((d, [r["score"] for r in ay if gun(r) == d]) for d in range(7)), key=lambda x: -_mean(x[1]))
    gunler = [(d, xs) for d, xs in gunler if len(xs) >= MIN_GROUP]
    if len(gunler) >= 2 and overall > 0 and _mean(gunler[-1][1]) > 0 \
            and _mean(gunler[0][1]) / _mean(gunler[-1][1]) - 1 >= NOTABLE:
        tips.append(f"Gün: {GUN[gunler[0][0]]} ({_rel(_mean(gunler[0][1]), overall)}, n={len(gunler[0][1])}) en "
                    f"yüksek, {GUN[gunler[-1][0]]} ({_rel(_mean(gunler[-1][1]), overall)}, n={len(gunler[-1][1])}) "
                    "en düşük.")
    if not tips:
        tips.append(f"Tema ve günler arasında %{round(NOTABLE * 100)}'i aşan fark yok ya da grup başına en az "
                    f"{MIN_GROUP} gönderi yok.")
    return out + [f"- {s}" for s in tips] + ["- Yalnız öneri: takvim kendiliğinden değişmez; tema/gün değişikliği "
                                             "`config.json` `posts` alanında elle yapılır."]


# ---- Haftalık KPI (O7) ------------------------------------------------------------------------

def load_manuel() -> dict[str, dict]:
    """data/manuel.json -> {"<pazartesi>": {alan: sayı|None, ...}}. Dosya yoksa ya da bozuksa uyarı ve boş sözlük.

    Hafta anahtarı haftanın pazartesi tarihidir (YYYY-MM-DD); pazartesi olmayan ya da okunamayan anahtar atlanır.
    Sayı olmayan, negatif ya da null alan None olur: raporda "veri yok" yazılır, asla 0 sayılmaz.
    """
    try:
        raw = read_json(MANUEL, None)
    except (ValueError, OSError) as e:
        _warn(f"{MANUEL.name} okunamadı (bozuk), manuel KPI'lar veri yok sayılıyor: {e}")
        return {}
    if raw is None:
        _warn(f"{MANUEL.name} yok: manuel KPI'lar 'veri yok' yazılır")
        return {}
    haftalar = raw.get("haftalar") if isinstance(raw, dict) else None
    if not isinstance(haftalar, dict):
        _warn(f"{MANUEL.name}: 'haftalar' sözlüğü yok, manuel KPI'lar veri yok sayılıyor")
        return {}
    out: dict[str, dict] = {}
    for k, v in haftalar.items():
        d = _date(k) if len(str(k)) == 10 else None
        if d is None or d.weekday() != 0 or not isinstance(v, dict):
            _warn(f"{MANUEL.name}: '{k}' hafta anahtarı pazartesi tarihi (YYYY-MM-DD) değil ya da kayıt sözlük değil; "
                  "atlandı")
            continue
        rec: dict = {f: _sayi(v.get(f)) for f in MANUEL_SAYI}
        rec.update({f: v.get(f) if isinstance(v.get(f), bool) else None for f in MANUEL_EVETHAYIR})
        rec["not"] = _one(v.get("not") or "")
        out[d.isoformat()] = rec
    return dict(sorted(out.items()))


def _baz() -> str | None:
    """suite_insights.json'dan haftalık baz değerler (aralığın hafta sayısına bölünmüş toplam); yoksa None."""
    try:
        raw = read_json(SUITE_INSIGHTS, {})
    except (ValueError, OSError):
        return None
    aralik = raw.get("aralik") if isinstance(raw, dict) else None
    gunluk = raw.get("gunluk") if isinstance(raw, dict) else None
    if not isinstance(aralik, list) or len(aralik) != 2 or not isinstance(gunluk, dict):
        return None
    bas, bit = _date(aralik[0]), _date(aralik[1])
    if bas is None or bit is None or bit < bas:
        return None
    hafta = ((bit - bas).days + 1) / 7
    parca = [f"{ad} {_n(int(sum(xs) / hafta + 0.5))}" for k, ad in BAZ_TR
             if isinstance(xs := gunluk.get(k), list) and xs and all(_num(x) is not None for x in xs)]
    if not parca:
        return None
    return (f"Baz ({SUITE_INSIGHTS.name}, {tr_date(bas, False)}–{tr_date(bit, False)}, haftalık ortalama): "
            + " · ".join(parca) + ".")


def _aralik(bas: date) -> str:
    """Pazartesi–pazar aralığı: 16–22 Kasım · 30 Kasım–6 Aralık"""
    bit = bas + timedelta(days=6)
    return f"{bas.day}–{tr_date(bit, False)}" if bas.month == bit.month else f"{tr_date(bas, False)}–{tr_date(bit, False)}"


def _takipci_hafta(metrics: dict, bas: date) -> tuple[int, int] | None:
    """Haftanın son takipçi sayısı ve net değişimi (account geçmişi): pazar (ya da cumartesi) kaydı eksi önceki
    pazar (ya da cumartesi) kaydı. İki uçtan biri yoksa None."""
    acc = {d: f for a in metrics.get("account") or [] if isinstance(a, dict)
           and (d := _date(a.get("date"))) is not None and (f := _num(a.get("followers"))) is not None}

    def uc(gun: date) -> int | None:
        return next((acc[g] for g in (gun, gun - timedelta(days=1)) if g in acc), None)

    son, ilk = uc(bas + timedelta(days=6)), uc(bas - timedelta(days=1))
    return None if son is None or ilk is None else (son, son - ilk)


def _donmus_hafta(cal: list[dict], metrics: dict, bas: date) -> list[dict]:
    """Haftada yayınlanmış postların ilk ≥72 saatlik (dondurulmuş) ölçümleri; yayın zamanı bilinmeyen atlanır."""
    media = metrics.get("media") if isinstance(metrics.get("media"), dict) else {}
    out = []
    for c in cal:
        if not isinstance(c, dict) or _is_story(c):
            continue
        rec = media.get(str(c.get("id")))
        if not isinstance(rec, dict) or not isinstance(rec.get("dondurulmus"), dict) or rec.get("error"):
            continue
        pub = _pub(c, rec)
        if pub is not None and bas <= pub.astimezone(TZ).date() < bas + WEEK:
            out.append(rec["dondurulmus"])
    return out


def _yuzde(v) -> str:
    return f"%{_n(v, 0 if float(v).is_integer() else 1)}"


def story_esleme_orani(cal: list[dict], metrics: dict, t: datetime) -> tuple[int, int, list[dict]]:
    """Suite story eşlemesi: (eşlenen, saati ESLE_GEC'ten fazla geçmiş Suite story'si, eşlenemeyenler).
    Yalnız story takibi başladıktan (story_baslangic) sonra planlananlar sayılır; takip hiç çalışmadıysa (0, 0, [])."""
    bas = _dt(metrics.get("story_baslangic"))
    if bas is None:
        return 0, 0, []
    stories = metrics.get("stories") if isinstance(metrics.get("stories"), dict) else {}
    bagli = {str(r["takvim_id"]) for r in stories.values() if isinstance(r, dict) and r.get("takvim_id")}
    due = [c for c in _story_takvim(cal) if _suite_story(c) and bas <= _planned(c) < t - ESLE_GEC]
    miss = [c for c in due if str(c["id"]) not in bagli]
    return len(due) - len(miss), len(due), miss


def kpi_satirlari(cal: list[dict], metrics: dict, manuel: dict, t: datetime) -> list[list[str]]:
    """TRAFIK-PLANI §2'deki her KPI için bir satır: [KPI, hedef (31 Aralık), bu hafta, önceki hafta, kaynak, durum].

    "Bu hafta" son tamamlanan pazartesi–pazar haftasıdır (Barış pazartesi bu haftayı girer). Değer önceliği:
    API (metrics.json hesap_insights, account geçmişi, dondurulmuş post ölçümleri) > manuel.json > "veri yok".
    Durum yalnız bu haftanın değerine göre: hedefte / altında / veri yok (veri yoksa sıfır sayılmaz).
    """
    bu = _pazartesi(t.astimezone(TZ).date()) - WEEK
    onc = bu - WEEK
    hi = metrics.get("hesap_insights") if isinstance(metrics.get("hesap_insights"), dict) else {}

    def man(h: date, k: str):
        return (manuel.get(h.isoformat()) or {}).get(k)

    def api(h: date, k: str):
        r = hi.get(h.isoformat())
        return _sayi(r.get(k)) if isinstance(r, dict) else None

    rows: list[list[str]] = []

    def ekle(ad: str, hedef: str, kaynak: str, fn, kontrol) -> None:
        """fn(hafta) -> (değer ya da None, gösterilecek metin ya da None, kullanılan kaynak ya da None)."""
        b, o = fn(bu), fn(onc)
        durum = "veri yok" if b[0] is None else "hedefte" if kontrol(b[0]) else "altında"
        rows.append([ad, hedef, b[1] or "veri yok", o[1] or "veri yok", b[2] or o[2] or kaynak, durum])

    def sec(*adaylar: tuple[object, str]):
        for v, kaynak in adaylar:
            if v is not None:
                return v, _n(v), kaynak
        return None, None, None

    ekle("Haftalık profil ziyareti", "≥220", "Suite → manuel.json; izin gelince API",
         lambda h: sec((api(h, "profile_views"), "API hesap insights (profile_views)"),
                       (man(h, "profil_ziyareti"), "Suite → manuel.json")), lambda v: v >= 220)

    ga4 = [(k, r["ga4_oturum"]) for k, r in manuel.items() if r.get("ga4_oturum") is not None]
    esik = math.ceil(ga4[0][1] * 1.3) if ga4 else None
    ekle("Haftalık GA4 oturumu (instagram + gbp)",
         f"baz ×1,3 (baz {_aralik(_date(ga4[0][0]))}: {_n(ga4[0][1])} → ≥{_n(esik)})" if ga4 else "baz ×1,3 (baz yok)",
         "Looker Studio → manuel.json",
         lambda h: sec((man(h, "ga4_oturum"), "Looker Studio → manuel.json")),
         lambda v: esik is not None and v >= esik)

    def nkod(h: date):
        talep, satis = man(h, "nkod_talep"), man(h, "nkod_satis")
        if talep is None:
            return None, None, None
        return talep, _n(talep) + (f" (satış {_n(satis)})" if satis is not None else ""), "N-kodu defteri → manuel.json"

    ekle("Haftalık N-kodu talebi (satışa dönen ayrıca)", "≥5", "N-kodu defteri → manuel.json", nkod,
         lambda v: v >= 5)
    # API'nin profile_links_taps metriği story + bio link tıklamasını kapsamadığından bu KPI yalnız Suite okumasından.
    ekle("Haftalık link tıklaması (story + bio)", "≥100", "Suite → manuel.json",
         lambda h: sec((man(h, "link_tiklamasi"), "Suite → manuel.json")), lambda v: v >= 100)

    def takipci(h: date):
        r = _takipci_hafta(metrics, h)
        return (None, None, None) if r is None else (r[1], f"{_n(r[0])} (net {_signed(r[1])})",
                                                     "metrics.json account geçmişi, net")

    ekle("Takipçi (haftada net +15–30)", "2.740–2.815 (haftada net ≥+15)", "metrics.json account geçmişi, net",
         takipci, lambda v: v >= 15)

    def donmus(alan: str, ozet):
        def fn(h: date):
            xs = [v for d in _donmus_hafta(cal, metrics, h) if (v := _num(d.get(alan))) is not None]
            return (None, None, None) if not xs else (ozet(xs), f"{_n(ozet(xs), 1)} (n={len(xs)})",
                                                      "metrics.json ilk ≥72 saatlik ölçüm")
        return fn

    ekle("Post başı yorum", "≥1", "metrics.json ilk ≥72 saatlik ölçüm", donmus("comments", _mean), lambda v: v >= 1)
    ekle("Post beğeni medyanı (ilk ≥72 saatlik ölçüm)", "≥18", "metrics.json ilk ≥72 saatlik ölçüm",
         donmus("likes", statistics.median), lambda v: v >= 18)

    def pay(alan: str):
        def fn(h: date):
            v = man(h, alan)
            return (None, None, None) if v is None else (v, _yuzde(v), "GA4 → manuel.json")
        return fn

    ekle("Bio'ya kod veya aramayla gelen oturumlarda utm_content=<post-id> payı", "≥%90", "GA4 → manuel.json",
         pay("ga4_utm_content_payi"), lambda v: v >= 90)
    ekle("Aynı oturumlarda arama payı", "<%10", "GA4 → manuel.json", pay("ga4_arama_payi"), lambda v: v < 10)

    def bio(h: date):
        kat, ilt = man(h, "bio_kategori_tiklama"), man(h, "bio_iletisim_tiklama")
        if kat is None and ilt is None:
            return None, None, None
        metin = f"kategori {_n(kat) if kat is not None else 'veri yok'} · iletişim " \
                f"{_n(ilt) if ilt is not None else 'veri yok'}"
        return (None if kat is None or ilt is None else (kat, ilt)), metin, "GA4 utm_medium=bio → manuel.json"

    ekle("Bio kategori ve iletişim tıklaması (ayrı sayılır)", "baz değer alınır", "GA4 utm_medium=bio → manuel.json",
         bio, lambda v: True)

    def saglik(h: date):
        hafta = [c for c in cal if (w := _when(c)) is not None and h <= w.astimezone(TZ).date() < h + WEEK]
        zam = len(_zamanlanmamis(cal, t)) if h == bu else None
        if not hafta:
            # O hafta takvimde kayıt yok: missed/error ölçülmemiştir, 0 sayılmaz. Zamanlanmamış sayısı yalnız bilgi.
            return None, (None if zam is None else f"veri yok (takvimde kayıt yok) · zamanlanmamış {zam} (şu an)"), \
                None
        missed = sum(1 for c in hafta if c.get("status") == "missed")
        err = sum(1 for c in hafta if c.get("status") == "error")
        if h != bu:
            return (missed, err), f"{missed} / {err} / —", "takvim (RAPOR.md)"
        return (missed, err, zam), f"{missed} / {err} / {zam} (şu an)", "takvim (RAPOR.md)"

    ekle("Yayın sağlığı: missed/error, zamanlanmamış linkli story", "0 / 0 / 0", "takvim (RAPOR.md)", saglik,
         lambda v: not any(v))

    def sayac(alan: str, kaynak: str):
        return lambda h: sec((man(h, alan), kaynak))

    ekle("Sitede yayınlanmış rota ve bakım yazısı", "0 (31 Mart: ≥4)", "/blog/ → manuel.json",
         sayac("blog_yazisi", "/blog/ → manuel.json"), lambda v: v >= 0)
    ekle("Kabul edilmiş collab", "0 (31 Mart: ≥2)", "invite_status → manuel.json",
         sayac("collab_kabul", "invite_status → manuel.json"), lambda v: v >= 0)

    def merchant(h: date):
        uygun, onayli = man(h, "merchant_uygun"), man(h, "merchant_onayli")
        if uygun is None and onayli is None:
            return None, None, None
        metin = ("uygunluk " + ("veri yok" if uygun is None else "evet" if uygun else "hayır")
                 + (f" · onaylı ürün {_n(onayli)}" if onayli is not None else ""))
        return uygun, metin, "Merchant Center → manuel.json"

    ekle("Koşullu: Merchant'ta onaylı ürün", "uygunluk doğrulandı mı", "Merchant Center → manuel.json", merchant,
         lambda v: True)   # hedef sorunun yanıtlanması: evet ya da hayır girildiyse doğrulama yapılmıştır
    return rows


def _haftalik_kpi(cal: list[dict], metrics: dict, manuel: dict, t: datetime) -> list[str]:
    bu = _pazartesi(t.astimezone(TZ).date()) - WEEK
    out = [f"Bu hafta: {_aralik(bu)} (son tamamlanan pazartesi–pazar) · önceki hafta: {_aralik(bu - WEEK)}. "
           "Değer önceliği: API > `data/manuel.json` (Barış'ın pazartesi Suite okuması); verisi olmayan KPI "
           "\"veri yok\" yazar, sıfır sayılmaz. Durum bu haftanın değerini 31 Aralık hedefiyle karşılaştırır.", "",
           *_table(["KPI", "Hedef (31 Aralık)", "Bu hafta", "Önceki hafta", "Kaynak", "Durum"],
                   kpi_satirlari(cal, metrics, manuel, t)), ""]
    baz = _baz()
    if baz:
        out.append(f"- {baz}")
    hi = (metrics.get("hesap_insights") or {}).get(bu.isoformat())
    if isinstance(hi, dict) and any(_num(hi.get(k)) is not None for k in HESAP_METRICS):
        out.append("- Hesap insights (API, bu hafta): " + " · ".join(
            f"{HESAP_TR[k]} {_n(_num(hi.get(k)))}" for k in HESAP_METRICS if _num(hi.get(k)) is not None) + ".")
    else:
        out.append("- Hesap insights (API, bu hafta): veri yok.")
    esl, due, miss = story_esleme_orani(cal, metrics, t)
    if not metrics.get("story_baslangic"):
        out.append("- Suite story eşlemesi: veri yok (story takibi `report.py --story` henüz çalışmadı).")
    elif not due:
        out.append("- Suite story eşlemesi: veri yok (takip başladıktan sonra saati geçmiş Suite story'si yok).")
    else:
        out.append(f"- Suite story eşlemesi: saati geçmiş {due} Suite story'sinin **{esl}** tanesi /stories ile "
                   f"eşlendi (%{round(esl / due * 100)}; ±{int(ESLE_TOL.total_seconds() // 60)} dk, tek aday)"
                   + (f"; eşlenemeyen: " + ", ".join(f"`{c['id']}`" for c in sorted(miss, key=_planned)[:5])
                      + (" …" if len(miss) > 5 else "") if miss else "") + ".")
    lt = metrics.get("link_testi") if isinstance(metrics.get("link_testi"), dict) else None
    if lt and lt.get("sonuc") in LINK_TR:
        out.append(f"- Link dokunuşu API testi: **{LINK_TR[lt['sonuc']]}**"
                   + (f" ({lt['tarih']})" if lt.get("tarih") else "") + (f" · {lt['not']}" if lt.get("not") else "")
                   + ".")
    else:
        out.append("- Link dokunuşu API testi: denenmedi (story insights henüz çalışmadı).")
    out.append(f"- `manuel.json`: {len(manuel)} hafta girilmiş" + (f" (son: {_aralik(_date(max(manuel)))})"
                                                                     if manuel else "") + ".")
    return out


def write_report(cal: list[dict], metrics: dict, sc: dict, notes: list[str] | None = None,
                 manuel: dict | None = None) -> str:
    """RAPOR.md metnini üretir, dosyaya yazar ve döndürür. `notes`: bu çalıştırmaya özgü uyarılar (isteğe bağlı).
    `manuel`: load_manuel() çıktısı; verilmezse data/manuel.json okunur."""
    cal = [c for c in cal if isinstance(c, dict)]
    manuel = load_manuel() if manuel is None else manuel
    sc = sc if isinstance(sc, dict) else {}
    t = now()
    rows, formula = _measured(cal, metrics)
    updated = _dt(metrics.get("updated"))
    out = [f"# Instagram performans raporu · @{IG_USERNAME}", "",
           f"Üretim: {tr_date(t, False)} {t.year} {GUN[t.weekday()]} {t:%H:%M} · Veri: "
           + (f"{updated.day} {AY[updated.month - 1]} {updated.year} {updated:%H:%M}" if updated
              else "henüz toplanmadı"), ""]

    media = metrics.get("media") if isinstance(metrics.get("media"), dict) else {}
    posts = {str(c.get("id")) for c in cal if c.get("status") == "published" and not _is_story(c)}
    posts |= {str(c["id"]) for c in _suite_posts(cal) if _suite_rec(media, str(c["id"]))}
    gone = sorted(k for k, r in media.items() if k in posts and isinstance(r, dict) and r.get("error"))
    errors = metrics.get("errors") if isinstance(metrics.get("errors"), list) else []
    warn = [*(notes or []), *(f"Son veri toplamada sorun: {e}" for e in errors)]
    if metrics.get("insights") is False:
        warn.append(PERMISSION_NOTE)
    miss, _ = _eslenemeyen(cal, metrics, t)
    if miss:
        warn.append(f"{len(miss)} Suite postu /media ile eşlenemedi (liste: Suite eşlemesi bölümü)")
    if gone:
        warn.append(f"{len(gone)} gönderinin verisi okunamadı (silinmiş olabilir), hesaplara katılmadı: "
                    + ", ".join(f"`{k}`" for k in gone[:5]) + (" …" if len(gone) > 5 else ""))
    if warn:
        out += ["> **Notlar**", ">", *(f"> - {_md(w)}" for w in warn), ""]

    for title, lines in (("Özet", _summary(cal, metrics, rows, t)),
                         ("Haftalık KPI", _haftalik_kpi(cal, metrics, manuel, t)),
                         ("Yayın sağlığı (son 7 gün)", _health(cal, t)),
                         ("Suite eşlemesi", _suite_esleme(cal, metrics, t)),
                         ("En iyi 5 gönderi", _top(rows, formula, t)),
                         ("Biçim ve tema karşılaştırması", _compare(rows, sc)),
                         ("Kategori performansı", _categories(rows, sc)),
                         ("Önümüzdeki 7 gün", _upcoming(cal, t)),
                         ("Aylık tema raporu (geçen ay, yalnız öneri)", _aylik_tema(rows, t)),
                         ("Öneriler", [f"- {s}" for s in _advice(rows)])):
        out += [f"## {title}", "", *lines, ""]
    out += ["---", "", "Site trafiği için site panelinde `utm_source=instagram` filtresine bak.", ""]
    text = "\n".join(out)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    return text


# ---- Komut satırı ------------------------------------------------------------------------------

def _run() -> None:
    ap = argparse.ArgumentParser(description="Instagram performans raporu: metrics.json, scores.json ve RAPOR.md")
    ap.add_argument("--no-api", action="store_true",
                    help="Graph API'ye bağlanma; yalnız kayıtlı dosyalardan rapor üret")
    ap.add_argument("--esle", action="store_true",
                    help="hafif mod: yalnız Suite eşlemesi ve 72 saat dondurması (rapor yazılmaz)")
    ap.add_argument("--story", action="store_true",
                    help="hafif mod: yayındaki story'lerin insights'ı, story eşlemesi ve link testi (rapor yazılmaz)")
    args, unknown = ap.parse_known_args()
    if unknown:
        _warn(f"bilinmeyen argüman yok sayıldı: {' '.join(unknown)}")
    if args.esle:
        esle_hafif()
        return
    if args.story:
        story_hafif()
        return
    cal = load_calendar()
    cal = [c for c in cal if isinstance(c, dict)] if isinstance(cal, list) else []
    notes = []
    if args.no_api:
        metrics = load_metrics()
        notes.append("Bu rapor Graph API'ye bağlanmadan (--no-api), kayıtlı son verilerden üretildi.")
    elif not os.environ.get("IG_ACCESS_TOKEN"):
        _warn("IG_ACCESS_TOKEN yok: API atlandı, rapor kayıtlı son verilerden üretiliyor.")
        metrics = load_metrics()
        notes.append("Bu çalıştırmada veri güncellenemedi (IG_ACCESS_TOKEN tanımlı değil); "
                     "rapor kayıtlı son verilerden üretildi.")
    else:
        try:
            metrics = collect(cal)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            metrics = load_metrics()
            notes.append(f"Bu çalıştırmada veri güncellenemedi ({_emsg(e)}); rapor kayıtlı son verilerden üretildi.")
    sc = scores(cal, metrics)
    write_report(cal, metrics, sc, notes)
    print(f"Rapor yazıldı: {REPORT} · hesaba giren gönderi: {sc['n']}")


def main() -> None:
    try:
        _run()
    except SystemExit as e:  # argparse: -h ya da hatalı argüman (ayrıntıyı kendisi yazdı)
        if e.code:
            print("HATA: argümanlar okunamadı, rapor üretilmedi; çıkış kodu yine de 0.", file=sys.stderr)
    except Exception:  # noqa: BLE001 — rapor işi yayın işini kırmasın: hata stderr'e, çıkış kodu 0
        traceback.print_exc()
        print("HATA: rapor üretilemedi (ayrıntı yukarıda); çıkış kodu yine de 0.", file=sys.stderr)


if __name__ == "__main__":
    main()
