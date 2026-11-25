#!/usr/bin/env python3
"""Performans raporu: yayınlanan gönderilerin etkileşimini toplar, planlayıcı puanlarını ve RAPOR.md'yi üretir.

Kullanım:
  python3 scripts/report.py            Graph API'den güncel sayıları topla, puanları ve raporu yaz
  python3 scripts/report.py --no-api   API'ye bağlanma; yalnız kayıtlı dosyalardan rapor üret
  python3 scripts/report.py --esle     hafif mod (publish adımında): yalnız Suite eşlemesi ve 72 saat dondurması;
                                       RAPOR.md ve scores.json yazılmaz, jeton yoksa sessizce atlanır

Yazdıkları (takvime, yani data/calendar.json'a hiçbir durumda dokunmaz):
  data/metrics.json   hesap (takipçi) geçmişi ve gönderi başına ham sayılar; Suite'ten yayınlanan postların
                      eşlenen media_id/permalink'i (kaynak=suite) ve yayından ≥72 saat sonraki ilk ölçüm (dondurulmus)
  data/scores.json    planlayıcı için 0..1 arası göreli puanlar: kategori, biçim, tema, saat
  RAPOR.md            okunur haftalık özet

Token'da `instagram_manage_insights` izni yokken yalnız beğeni ve yorum toplanır. İzin eklendiğinde erişim,
kaydetme, gönderme ve görüntülenme kendiliğinden gelir; kod değişikliği gerekmez.
Rapor işi yayın işini kırmasın diye çıkış kodu her durumda 0'dır; sorunlar stderr'e yazılır.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
import unicodedata
from datetime import date, datetime, timedelta

import graph
from common import (AY, CFG, DATA, GUN, IG_USERNAME, ROOT, TZ, cancelled_ids, item_dt, load_calendar, now, read_json,
                    tr_date, write_json)

# Çıktı yolları. İşlevler bunları çağrı anında okur; testte başka dizine yönlendirmek için üzerine yazılabilir.
# Aynı şekilde `graph.api` ve bu modüldeki `now` da sahtesiyle değiştirilebilir.
METRICS = DATA / "metrics.json"
SCORES = DATA / "scores.json"
REPORT = ROOT / "RAPOR.md"

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

def load_metrics() -> dict:
    """data/metrics.json; dosya yoksa ya da bozuksa boş iskelet."""
    try:
        raw = read_json(METRICS, {})
    except (ValueError, OSError) as e:
        _warn(f"{METRICS.name} okunamadı, boş veriyle devam ediliyor: {e}")
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    account, media, errors = raw.get("account"), raw.get("media"), raw.get("errors")
    return {"updated": raw.get("updated"),
            "account": [a for a in account if isinstance(a, dict)] if isinstance(account, list) else [],
            "media": {k: v for k, v in media.items() if isinstance(v, dict)} if isinstance(media, dict) else {},
            "insights": raw.get("insights") if isinstance(raw.get("insights"), bool) else None,
            "errors": [str(x) for x in errors] if isinstance(errors, list) else []}


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


def _insights(media_id: str) -> dict[str, int]:
    """Gönderinin insights değerleri ({ad: sayı}). `instagram_manage_insights` izni yoksa GraphError fırlatır."""
    out = {}
    for d in graph.api("GET", f"{media_id}/insights", metric=INSIGHT_METRICS).get("data") or []:
        if not isinstance(d, dict):
            continue
        values, total = d.get("values"), d.get("total_value")
        first = values[0] if isinstance(values, list) and values and isinstance(values[0], dict) else {}
        v = _num(first.get("value"), _num(total.get("value")) if isinstance(total, dict) else None)
        if v is not None:
            out[str(d.get("name"))] = v
    return out


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


def esle_hafif() -> None:
    """--esle: publish adımında (15 dakikada bir) çalışan hafif mod. Yalnız yakın geçmişteki Suite postlarını eşler
    ve 72..120 saatlik postların ilk ölçümünü dondurur. RAPOR.md/scores.json yazılmaz; jeton yoksa sessizce atlanır.
    Hatalar yalnız uyarıdır (çıkış kodu main() sayesinde her durumda 0)."""
    if not os.environ.get("IG_ACCESS_TOKEN"):
        return
    cal = load_calendar()
    cal = [c for c in cal if isinstance(c, dict)] if isinstance(cal, list) else []
    m, t = load_metrics(), now()
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
    suite = sorted(w for c in cal if _is_story(c) and c.get("channel") == "suite" and not c.get("suite_scheduled")
                   and c.get("status") not in ("published", "skipped", "missed", "error")
                   and (w := _planned(c)) is not None and w > t)
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


def write_report(cal: list[dict], metrics: dict, sc: dict, notes: list[str] | None = None) -> str:
    """RAPOR.md metnini üretir, dosyaya yazar ve döndürür. `notes`: bu çalıştırmaya özgü uyarılar (isteğe bağlı)."""
    cal = [c for c in cal if isinstance(c, dict)]
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
                         ("Yayın sağlığı (son 7 gün)", _health(cal, t)),
                         ("Suite eşlemesi", _suite_esleme(cal, metrics, t)),
                         ("En iyi 5 gönderi", _top(rows, formula, t)),
                         ("Biçim ve tema karşılaştırması", _compare(rows, sc)),
                         ("Kategori performansı", _categories(rows, sc)),
                         ("Önümüzdeki 7 gün", _upcoming(cal, t)),
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
    args, unknown = ap.parse_known_args()
    if unknown:
        _warn(f"bilinmeyen argüman yok sayıldı: {' '.join(unknown)}")
    if args.esle:
        esle_hafif()
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
