#!/usr/bin/env python3
"""Son postlardaki yorumları okur ve yanıt bekleyenleri işaretler (1. aşama: SALT OKUMA).

Graph API'den son 10 medyanın yorumlarını çeker, her yorumu basit anahtar kelime kurallarıyla sınıflar
(sikayet > fiyat > soru > diger) ve data/yorumlar.json'a yazar:

  [{"media_id", "yorum_id", "zaman", "metin_kisaltilmis" (≤140, @adlar/e-posta/telefon maskeli),
    "tur": "soru|fiyat|sikayet|diger", "yanit_gerekli": bool}, …]

Kullanıcı adı SAKLANMAZ: yalnız bellekte, kendi yorumlarımızı ayıklamak ve yanıt verilip verilmediğini görmek
için kullanılır. Bu betik hiçbir yorum/mesaj GÖNDERMEZ; yanıtlar elle verilir.

IG_ACCESS_TOKEN ya da IG_USER_ID yoksa atlanır; izin/ağ hatasında uyarı verip eldeki dosyayı korur. Çıkış hep 0.

  python3 scripts/yorum.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import graph  # noqa: E402
from graph import GraphError  # noqa: E402

DOSYA = common.DATA / "yorumlar.json"
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
    ],
    "fiyat": [
        "fiyat", "kaç tl", "kaç lira", "kaç para", "kaça", "ne kadar", "ücret", "taksit", "₺",
    ],
    "soru": [
        "var mı", "varmı", "nasıl", "nerede", "nerde", "ne zaman", "hangi", "kaç ", "bilgi", "stok",
        "kargo", "servis", "randevu", "adres", "beden", "kadro", "jant", "uyar mı", "olur mu",
    ],
}
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


def topla(api=None, ig: str | None = None, biz: str | None = None) -> list[dict]:
    """Son medyaların yorumlarını okuyup kayıt listesi döndürür. Testte `api` sahtesiyle değiştirilebilir."""
    api = api or graph.api
    ig = ig or os.environ.get("IG_USER_ID") or graph.ig_user_id()
    biz = tr_kucuk(biz or common.IG_USERNAME)
    medyalar = api("GET", f"{ig}/media", fields="id,timestamp,comments_count", limit=MEDYA_SAYISI).get("data") or []
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
                "yorum_id": y.get("id") or "",
                "zaman": yerel_zaman(y.get("timestamp")),
                "metin_kisaltilmis": kisalt(y.get("text") or ""),
                "tur": tur,
                "yanit_gerekli": tur != "diger" and biz not in yanitlayan,
            })
    out.sort(key=lambda r: (r["zaman"], r["yorum_id"]), reverse=True)
    return out


def main() -> int:
    if not os.environ.get("IG_ACCESS_TOKEN") or not os.environ.get("IG_USER_ID"):
        print("[yorum] jeton yok, atlandı")
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
    bekleyen = sum(r["yanit_gerekli"] for r in kayit)
    sayac = {t: sum(r["tur"] == t for r in kayit) for t in TURLER}
    print(f"[yorum] {len(kayit)} yorum · yanıt bekleyen {bekleyen} · "
          + ", ".join(f"{t} {n}" for t, n in sayac.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
