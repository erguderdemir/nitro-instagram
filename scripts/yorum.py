#!/usr/bin/env python3
"""Son postlardaki yorumları okur, yanıt bekleyenleri işaretler (1. aşama) ve onaylı fiyat yanıtlarını gönderir (2. aşama).

Graph API'den son 10 medyanın yorumlarını çeker, her yorumu basit anahtar kelime kurallarıyla sınıflar
(sikayet > fiyat > soru > diger) ve data/yorumlar.json'a yazar:

  [{"media_id", "permalink", "yorum_id", "zaman", "metin_kisaltilmis" (≤140, @adlar/e-posta/telefon maskeli),
    "tur": "soru|fiyat|sikayet|diger", "net_fiyat": bool, "yanit_gerekli": bool}, …]

Kullanıcı adı SAKLANMAZ: yalnız bellekte, kendi yorumlarımızı ayıklamak ve yanıt verilip verilmediğini görmek
için kullanılır. Varsayılan çalıştırma hiçbir yorum/mesaj GÖNDERMEZ; yalnız --gonder, kullanıcının onayladığı
taslakları gönderir (aşağıda). DM'ler ve diğer yanıtlar elle verilir.

IG_ACCESS_TOKEN yoksa atlanır (IG_USER_ID boşsa hesap jetondan bulunur); izin/ağ hatasında uyarı verip eldeki dosyayı korur. Çıkış hep 0.

2. aşama (O15, onaylı yanıt):
  Taslak yalnız şu durumda kurulur: yorum net bir fiyat sorusu (net_fiyat_sorusu: kısa, soru biçiminde, olumsuz
  ifade ya da kargo/süre/servis bağlamı yok; fiyata olumsuz tepki şikâyet sayılır), yorum ≤ TASLAK_GUN gün,
  medya tek ürünlü bir posta bağlı (API postu calendar.json'da, Suite postu metrics.json media[cid]'de), ürün
  products.json'da stokta ve fiyatlı. Taslaklar data/yorum_taslak.json'a yazılır. Depo herkese açık olduğu için bu
  dosyada yorum metni, kullanıcı adı, tür ve saat YOK; "elle" kalan yorumlar (şikâyet, soru, eşlenmeyen) dosyaya hiç
  girmez, yalnız neden sayısı loglanır.
  Onay: kullanıcı yorumu "yorum_link"ten (yoksa post permalink'inden) açıp okur; uygunsa data/yorum_onay.json'a {"<yorum_id>": "<ozet>"} ekler.
  Bu dosyayı bot hiç yazmaz. Onay metnin özetine bağlıdır: fiyat/ad değişip metin değişirse onay geçersizleşir.
  --gonder: onayı bugünkü metnin özetiyle eşleşen taslaklar gönderilir. Göndermeden önce yorumun yanıtları API'den
  okunur (bizim yanıtımız varsa gönderilmez). POST'tan önce data/yorum_gonderilen.json'a "deneniyor" yazılır ve orada
  olan yorum bir daha hiç denenmez: her yoruma en fazla 1 yanıt. config.json live=false iken gönderilmez.

  python3 scripts/yorum.py            # okuma + taslak
  python3 scripts/yorum.py --gonder   # onaylı taslakları gönder
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arama  # noqa: E402
import common  # noqa: E402
import graph  # noqa: E402
from graph import GraphError  # noqa: E402

DOSYA = common.DATA / "yorumlar.json"
TASLAK = common.DATA / "yorum_taslak.json"          # depoya girer: yorum metni/kullanıcı adı içermez
GONDERILEN = common.DATA / "yorum_gonderilen.json"  # depoya girer, yalnız bot yazar: yorum_id -> {zaman, durum, yanit_id}
ONAY = common.DATA / "yorum_onay.json"              # depoya girer, YALNIZ kullanıcı yazar: yorum_id -> taslak özeti
TASLAK_GUN = 14
YASAK = ("indirim", "son gün", "son fırsat", "acele", "kaçırma", "stokta son", "sınırlı")
MEDYA_SAYISI = 10
YORUM_SAYISI = 50          # medya başına tek sayfa; daha fazlası bu aşamada okunmaz
KISA = 140
TURLER = ("sikayet", "fiyat", "soru", "diger")

# Kelime başı eşleşmesi (Türkçe ekler için sonu açık): "fiyatı", "arızalı geldi", "kargoya"…
KURAL = {
    "sikayet": [
        "şikayet", "şikâyet", "berbat", "rezalet", "memnun değil", "memnun kalmadım", "bozuk", "arızal",
        "kırık", "hasarl", "ayıpl", "gelmedi", "ulaşmadı", "geç geldi", "eksik geldi", "yanlış ürün",
        "dönüş yapmad", "cevap vermiyor", "yanıt vermiyor", "ulaşamıyorum", "açmıyor", "mağdur",
        "dolandır", "paramı", "iade ettim", "iade edemiyorum", "kötü",
        # fiyata olumsuz tepki: "fiyat" sayılıp hazır fiyat yanıtı önerilmesin
        "paha", "kazık", "fahiş", "soygun", "rezil", "saçma", "yazık", "abartı", "uçuk", "uçmuş", "çok para",
        "değmez", "yüksek", "alınmaz", "kim alır", "insaf",
    ],
    "fiyat": [
        "fiyat", "kaç tl", "kaç lira", "kaç para", "kaça", "ne kadar", "ücret", "taksit", "₺",
    ],
    "soru": [
        "var mı", "varmı", "nasıl", "nerede", "nerde", "ne zaman", "hangi", "kaç ", "bilgi", "stok",
        "kargo", "servis", "randevu", "adres", "beden", "kadro", "jant", "uyar mı", "olur mu",
    ],
}
# Taslak için ek süzgeç: fiyat sorusu sayılsa da bunlar varsa hazır fiyat yanıtı önerilmez (elle bakılır).
NET_DEGIL = ("fazla", "çok", "kargo", "süre", "gün", "teslim", "montaj", "servis", "tamir", "bakım", "taksit",
             "ücreti", "ikinci el", "2. el", "takas", "indirim", "pazarlık", "son fiyat", "değil", "olmaz")
NET_SORU = ("kaç tl", "kaç lira", "kaç para", "kaça", "ne kadar", "fiyatı nedir", "fiyat nedir", "fiyatı ne",
            "fiyat ne", "fiyat bilgisi", "fiyatı?", "fiyat?")
SORU_EKI = re.compile(r"(?<!\w)(mı|mi|mu|mü|mıdır|midir|mudur|müdür)(?!\w)")


def tr_kucuk(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def siniflandir(metin: str) -> str:
    t = " " + re.sub(r"\s+", " ", tr_kucuk(metin or "")) + " "
    for tur in ("sikayet", "fiyat", "soru"):
        for k in KURAL[tur]:
            if k in ("₺",) and k in t:
                return tur
            if re.search(r"(?<!\w)" + re.escape(k), t):
                return tur
    if "?" in t or SORU_EKI.search(t):
        return "soru"
    return "diger"


def maskele(metin: str) -> str:
    """Kişisel bilgiyi sakla: @adlar, e-posta ve telefon numaraları maskelenir."""
    s = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[e-posta]", metin or "")
    s = re.sub(r"@[\w.]+", "@…", s)
    s = re.sub(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)", "[telefon]", s)
    return re.sub(r"\s+", " ", s).strip()


def kisalt(metin: str, n: int = KISA) -> str:
    s = maskele(metin)
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def yerel_zaman(ts: str | None) -> str:
    """Graph zamanı (2026-11-25T07:30:00+0000) -> yerel ISO (2026-11-25T10:30:00+03:00)."""
    if not ts:
        return ""
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(common.TZ).isoformat()
    except ValueError:
        return ts


def gizle(s: str) -> str:
    """Hata metninden jetonu ayıklar. http.client.InvalidURL gibi hatalar tam URL'yi (access_token dahil)
    içerebilir (ör. IG_USER_ID sonunda boşluk/satır sonu); kırpmadan ÖNCE ayıklanır ki yarım jeton kalmasın."""
    s = re.sub(r"(access_token=)[^&\s'\"]+", r"\1***", s or "")
    tok = os.environ.get("IG_ACCESS_TOKEN") or ""
    return s.replace(tok, "***") if tok else s


def net_fiyat_sorusu(metin: str) -> bool:
    """Hazır fiyat yanıtı önerilebilecek kadar net bir fiyat sorusu mu? Şüphede False (elle bakılır)."""
    t = re.sub(r"\s+", " ", tr_kucuk(metin or "")).strip()
    if siniflandir(metin) != "fiyat" or len(t) > 100:
        return False
    if any(re.search(r"(?<!\w)" + re.escape(k), t) for k in NET_DEGIL):
        return False
    return any(k in t for k in NET_SORU) or ("fiyat" in t and ("?" in t or bool(SORU_EKI.search(t))))


def topla(api=None, ig: str | None = None, biz: str | None = None) -> list[dict]:
    """Son medyaların yorumlarını okuyup kayıt listesi döndürür. Testte `api` sahtesiyle değiştirilebilir."""
    api = api or graph.api
    ig = ig or os.environ.get("IG_USER_ID") or graph.ig_user_id()
    biz = tr_kucuk(biz or common.IG_USERNAME)
    medyalar = api("GET", f"{ig}/media", fields="id,timestamp,comments_count,permalink", limit=MEDYA_SAYISI).get("data") or []
    out = []
    for m in medyalar[:MEDYA_SAYISI]:
        if not m.get("comments_count"):
            continue
        res = api("GET", f"{m['id']}/comments", fields="id,text,timestamp,username,replies{username}",
                  limit=YORUM_SAYISI)
        for y in res.get("data") or []:
            if tr_kucuk(y.get("username") or "") == biz:
                continue  # kendi yorumumuz
            yanitlayan = {tr_kucuk(r.get("username") or "") for r in (y.get("replies") or {}).get("data") or []}
            tur = siniflandir(y.get("text") or "")
            out.append({
                "media_id": m["id"],
                "permalink": m.get("permalink") or "",
                "yorum_id": y.get("id") or "",
                "zaman": yerel_zaman(y.get("timestamp")),
                "metin_kisaltilmis": kisalt(y.get("text") or ""),
                "tur": tur,
                "net_fiyat": net_fiyat_sorusu(y.get("text") or ""),
                "yanit_gerekli": tur != "diger" and biz not in yanitlayan,
            })
    out.sort(key=lambda r: (r["zaman"], r["yorum_id"]), reverse=True)
    return out


# ---- 2. aşama: taslak ve onaylı gönderim ----------------------------------------------------------

def ozet(metin: str) -> str:
    """Onay anahtarı: taslak metninin kısa SHA-256 özeti. Metin değişirse onay kendiliğinden geçersizleşir."""
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:12]


def _medya_haritasi(cal: list[dict], metrics: dict) -> dict:
    """media_id -> takvim kaydı. API postları calendar.json'da, Suite postları metrics.json media[cid]'de eşlenir."""
    by_id = {c.get("id"): c for c in cal if c.get("id")}
    out = {}
    for cid, m in (metrics.get("media") or {}).items():
        if isinstance(m, dict) and m.get("media_id") and cid in by_id:
            out[m["media_id"]] = by_id[cid]
    for c in cal:
        if c.get("media_id"):
            out[c["media_id"]] = c
    return out


def _urun(media_id: str, medya: dict, urunler: dict) -> tuple[dict | None, str]:
    """Medyanın takvim kaydındaki tek ürün (products.json'daki güncel hâli) ya da neden yok."""
    kayit = medya.get(media_id) if media_id else None
    if not kayit:
        return None, "medya takvimde yok"
    if kayit.get("type") not in (None, "post"):
        return None, "post değil"
    slugs = [x.get("slug") for x in kayit.get("products") or []]
    if len(slugs) != 1:
        return None, "postta tek ürün yok"
    p = urunler.get(slugs[0])
    if not p or not p.get("price") or p.get("in_stock") is not True:
        return None, "ürün stokta değil ya da fiyatı yok"
    return p, ""


def yanit_metni(p: dict, tablo: dict | None = None) -> str:
    import content as C  # ağır modül: yalnız taslak kurulurken
    site = common.read_json(common.DATA / "site.json", {})
    tel = site.get("phone") or ""
    return (f"Merhaba! {C.display_name(p)}: {common.fmt_price(p['price'])} (KDV dahil). "
            f"Profildeki linke dokun, nitrobisiklet.com'da aramaya “{arama.terim(p, tablo)}” yaz. "
            f"Köyceğiz içi aynı gün ücretsiz teslimat"
            + (f"; soruların için WhatsApp: {tel}" if tel else "") + " 🚲")


def yanit_denetle(metin: str, p: dict) -> str:
    """Boş dize = sorun yok. Fiyat products.json ile birebir, yasak/aciliyet ifadesi yok, uzunluk sınırı."""
    if common.fmt_price(p.get("price")) not in metin:
        return "fiyat products.json ile aynı değil"
    t = tr_kucuk(metin)
    for k in YASAK:
        if k in t:
            return f"yasak ifade: {k}"
    if len(metin) > 300:
        return "300 karakterden uzun"
    return ""


def taslak_kur(r: dict, medya: dict, urunler: dict, tablo: dict | None, simdi: datetime) -> tuple[dict | None, str]:
    """Yanıt bekleyen tek yorum için (taslak satırı, neden). Satır yorum metni, kullanıcı adı, tür ve saat içermez."""
    if r["tur"] != "fiyat":
        return None, "şikâyet" if r["tur"] == "sikayet" else "fiyat sorusu değil"
    if r.get("net_fiyat") is not True:
        return None, "net fiyat sorusu değil"
    try:
        zaman = datetime.fromisoformat(r["zaman"])
        eski = zaman.tzinfo is None or zaman < simdi - timedelta(days=TASLAK_GUN)
    except (TypeError, ValueError):
        eski = True
    if eski:
        return None, f"{TASLAK_GUN} günden eski"
    p, neden = _urun(r["media_id"], medya, urunler)
    if not p:
        return None, neden
    metin = yanit_metni(p, tablo)
    sorun = yanit_denetle(metin, p)
    if sorun:
        return None, sorun
    perma = r.get("permalink") or ""
    return {"yorum_id": r["yorum_id"], "media_id": r["media_id"], "permalink": perma,
            # Instagram web'in yorum bağlantısı (/p/<kod>/c/<yorum_id>/): onaydan önce DOĞRU yorumu okumak için
            "yorum_link": f"{perma.rstrip('/')}/c/{r['yorum_id']}/" if perma else "",
            "gun": r["zaman"][:10], "slug": p["slug"], "taslak": metin, "ozet": ozet(metin)}, ""


def _baglam():
    cal = common.read_json(common.DATA / "calendar.json", [])
    urunler = {p["slug"]: p for p in common.read_json(common.DATA / "products.json", []) if p.get("slug")}
    medya = _medya_haritasi(cal, common.read_json(common.DATA / "metrics.json", {}))
    return medya, urunler, arama.yukle()


def taslaklari_yaz(kayit: list[dict], simdi: datetime | None = None) -> tuple[list[dict], dict]:
    """Taslak satırlarını TASLAK'a yazar; (satırlar, elle bırakılanların neden sayımı) döndürür.
    Depo herkese açık: yalnız taslağı kurulan fiyat yorumları yazılır, "elle" kalanlar yalnız sayı olarak loglanır."""
    simdi = simdi or common.now()
    medya, urunler, tablo = _baglam()
    gonderilen = common.read_json(GONDERILEN, {})
    out, elle = [], {}
    for r in kayit:
        if not r["yanit_gerekli"] or r["yorum_id"] in gonderilen:
            continue
        row, neden = taslak_kur(r, medya, urunler, tablo, simdi)
        if row:
            out.append(row)
        else:
            elle[neden] = elle.get(neden, 0) + 1
    if common.read_json(TASLAK, None) != out:
        common.write_json(TASLAK, out)
    return out, elle


def _canli() -> bool:
    try:
        return json.loads((common.ROOT / "config.json").read_text(encoding="utf-8")).get("live") is True
    except (OSError, ValueError):
        return False


def _kaydet(gonderilen: dict, yid: str, **alan) -> None:
    gonderilen[yid] = {"zaman": common.now().isoformat(timespec="seconds"), **alan}
    common.write_json(GONDERILEN, gonderilen)


def gonder(api=None, biz: str | None = None) -> int:
    """Onaylı taslakları gönderir; gönderilen sayısını döndürür.

    Her yoruma en fazla 1 deneme: POST'tan ÖNCE GONDERILEN'e "deneniyor" yazılır; GONDERILEN'de olan yorum bir daha
    hiç denenmez (belirsiz bir hata sonrası da). Tek bir yorumun hatası diğer onaylı yanıtları durdurmaz."""
    api = api or graph.api
    biz = tr_kucuk(biz or common.IG_USERNAME)
    if not _canli():
        print("[yorum] yayın kilitli (live=false); yanıt gönderilmedi")
        return 0
    onay = common.read_json(ONAY, {})
    if not isinstance(onay, dict) or not onay:
        return 0
    taslaklar = common.read_json(TASLAK, [])
    gonderilen = common.read_json(GONDERILEN, {})
    medya, urunler, tablo = _baglam()
    n = 0
    for t in taslaklar:
        yid = t.get("yorum_id") if isinstance(t, dict) else None
        if not yid or yid in gonderilen or onay.get(yid) is None:
            continue
        p, neden = _urun(t.get("media_id") or "", medya, urunler)
        metin = yanit_metni(p, tablo) if p else ""
        if (not p or metin != t.get("taslak") or onay.get(yid) != ozet(metin) or t.get("ozet") != ozet(metin)
                or yanit_denetle(metin, p)):
            print(f"UYARI: [yorum] {yid} gönderilmedi: onay bugünkü taslak metniyle eşleşmiyor "
                  f"({neden or 'metin değişti'}); yeniden onay gerekir.", file=sys.stderr)
            continue
        try:
            res = api("GET", yid, fields="id,replies.limit(50){username,from}")
        except GraphError as e:
            print(f"UYARI: [yorum] {yid} okunamadı (HTTP {e.status}, kod {e.code}); gönderilmedi.", file=sys.stderr)
            continue
        yanitlayan = set()
        for r in (res.get("replies") or {}).get("data") or []:
            yanitlayan.add(tr_kucuk(r.get("username") or ""))
            yanitlayan.add(tr_kucuk((r.get("from") or {}).get("username") or ""))
        if biz in yanitlayan:
            _kaydet(gonderilen, yid, durum="zaten yanıtlanmış")
            continue
        _kaydet(gonderilen, yid, durum="deneniyor")   # POST'tan önce: çökme/belirsiz hata sonrası ikinci yanıt gitmez
        try:
            cevap = api("POST", f"{yid}/replies", retries=0, message=metin)
        except GraphError as e:
            _kaydet(gonderilen, yid, durum="hata", kod=e.code, http=e.status)
            print(f"UYARI: [yorum] {yid} yanıtı gönderilemedi (HTTP {e.status}, kod {e.code}); tekrar denenmeyecek, "
                  f"gerekirse elle yanıtlanmalı.", file=sys.stderr)
            continue
        _kaydet(gonderilen, yid, durum="gönderildi", yanit_id=cevap.get("id"))
        n += 1
        print(f"[yorum] yanıtlandı: {yid} ({t.get('permalink') or t.get('media_id')})")
    return n

def main() -> int:
    # IG_USER_ID secret'ı boş olabilir (graph.ig_user_id() jetona bağlı tek hesabı kendisi bulur); yalnız jeton şart.
    if not os.environ.get("IG_ACCESS_TOKEN"):
        print("[yorum] jeton yok, atlandı")
        return 0
    if "--gonder" in sys.argv[1:]:
        try:
            n = gonder()
        except GraphError as e:
            print(f"UYARI: [yorum] gönderim durdu (HTTP {e.status}, kod {e.code}): {gizle(e.message)[:200]}",
                  file=sys.stderr)
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: [yorum] gönderim durdu: {type(e).__name__}: {gizle(str(e))[:200]}", file=sys.stderr)
            return 0
        print(f"[yorum] gönderilen yanıt: {n}")
        return 0
    try:
        kayit = topla()
    except GraphError as e:
        izin = e.code in (10, 190) or (e.code or 0) in range(200, 300) or e.status in (401, 403)
        print(f"UYARI: [yorum] {'izin yok' if izin else 'Graph hatası'} "
              f"(HTTP {e.status}, kod {e.code}): {gizle(e.message)[:200]}; eldeki dosya korundu.", file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001  (ağ vb.: otomasyonu durdurma)
        print(f"UYARI: [yorum] okunamadı: {type(e).__name__}: {gizle(str(e))[:200]}; eldeki dosya korundu.",
              file=sys.stderr)
        return 0
    if common.read_json(DOSYA, None) != kayit:
        common.write_json(DOSYA, kayit)
    try:
        taslak, elle = taslaklari_yaz(kayit)
        onay = common.read_json(ONAY, {})
        onayli = sum(isinstance(onay, dict) and onay.get(t["yorum_id"]) == t["ozet"] for t in taslak)
        print(f"[yorum] taslak {len(taslak)} · onaylı {onayli} · elle {sum(elle.values())} "
              f"({', '.join(f'{k}: {v}' for k, v in sorted(elle.items())) or '-'})")
    except Exception as e:  # noqa: BLE001  (taslak hatası okuma özetini bozmasın)
        print(f"UYARI: [yorum] taslak yazılamadı: {type(e).__name__}: {e}", file=sys.stderr)
    takili = sorted(k for k, v in common.read_json(GONDERILEN, {}).items()
                    if isinstance(v, dict) and v.get("durum") in ("hata", "deneniyor"))
    if takili:
        print(f"UYARI: [yorum] otomatik yanıtı tamamlanamayan {len(takili)} yorum elle kontrol edilmeli "
              f"(data/yorum_gonderilen.json): {', '.join(takili[:10])}", file=sys.stderr)
    bekleyen = sum(r["yanit_gerekli"] for r in kayit)
    sayac = {t: sum(r["tur"] == t for r in kayit) for t in TURLER}
    print(f"[yorum] {len(kayit)} yorum · yanıt bekleyen {bekleyen} · "
          + ", ".join(f"{t} {n}" for t, n in sayac.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
