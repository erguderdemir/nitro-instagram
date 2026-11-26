"""O15 2. aşama testleri: yorum yanıt taslakları ve onaylı gönderim.

Gerçek Graph API'ye istek atılmaz; dosyalar geçici dizine yönlendirilir.
Çalıştırma: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402
import yorum  # noqa: E402
from graph import GraphError  # noqa: E402

SIMDI = datetime(2026, 11, 26, 12, 0, tzinfo=common.TZ)
URUN = {"slug": "pedal-m504-siyah", "name": "Pedal M504 Siyah", "price": 743.69, "in_stock": True,
        "category": "Pedal ve Kal", "url": "https://nitrobisiklet.com/urun/pedal-m504-siyah/"}
CAL = [{"id": "k1", "type": "post", "media_id": "M1", "products": [{"slug": "pedal-m504-siyah"}]},
       {"id": "k2", "type": "post", "media_id": "M2", "products": [{"slug": "a"}, {"slug": "b"}]},
       {"id": "k3", "type": "post", "products": [{"slug": "pedal-m504-siyah"}]},          # Suite postu
       {"id": "k4", "type": "story", "media_id": "S1", "products": [{"slug": "pedal-m504-siyah"}]}]
METRICS = {"media": {"k3": {"kaynak": "suite", "media_id": "M3"}}}


def kayit(yid="Y1", media="M1", tur="fiyat", gun=1, gerekli=True):
    return {"media_id": media, "permalink": f"https://www.instagram.com/p/{media}/", "yorum_id": yid,
            "zaman": (SIMDI - timedelta(days=gun)).isoformat(timespec="seconds"), "tur": tur, "net_fiyat": tur == "fiyat",
            "yanit_gerekli": gerekli, "metin_kisaltilmis": "GİZLİ METİN", "kullanici": "gizli_kullanici"}


class Ortam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.urunler = {URUN["slug"]: dict(URUN)}
        for ad, dosya in (("TASLAK", "t.json"), ("GONDERILEN", "g.json"), ("ONAY", "o.json")):
            p = mock.patch.object(yorum, ad, self.tmp / dosya)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(yorum, "_baglam",
                              lambda: (yorum._medya_haritasi(CAL, METRICS), self.urunler, {}))
        p.start()
        self.addCleanup(p.stop)

    def oku(self, ad):
        return json.loads((self.tmp / ad).read_text(encoding="utf-8"))

    def yaz(self, ad, veri):
        (self.tmp / ad).write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")


class SiniflandirTest(unittest.TestCase):
    def test_fiyata_olumsuz_tepki_sikayet(self):
        for m in ("bu fiyata kazık resmen", "ne kadar pahalı ya", "fiyat fahiş"):
            self.assertEqual(yorum.siniflandir(m), "sikayet", m)

    def test_fiyat_sorusu(self):
        self.assertEqual(yorum.siniflandir("Fiyatı ne kadar?"), "fiyat")
        for m in ("Fiyatı ne kadar?", "kaç tl", "fiyat?", "Bu bisikletin fiyatı nedir"):
            self.assertTrue(yorum.net_fiyat_sorusu(m), m)

    def test_net_olmayan_fiyat_yorumlari(self):
        for m in ("Bu fiyata değmez", "Fiyatı çok yüksek", "fiyatlar ateş pahası", "fiyatlar uçmuş",
                  "Bu fiyata kim alır", "fiyatı fazla değil mi", "Ne kadar sürede gelir?", "Kargo ücreti var mı?",
                  "son fiyat ne olur", "taksit var mı fiyatı ne", "fiyatı güzel"):
            self.assertFalse(yorum.net_fiyat_sorusu(m), m)


class TaslakTest(Ortam):
    def test_fiyat_sorusuna_taslak(self):
        out, elle = yorum.taslaklari_yaz([kayit()], SIMDI)
        self.assertEqual(len(out), 1)
        self.assertIn(common.fmt_price(743.69), out[0]["taslak"])
        self.assertEqual(out[0]["ozet"], yorum.ozet(out[0]["taslak"]))
        self.assertEqual(out[0]["gun"], "2026-11-25")
        self.assertEqual(yorum.yanit_denetle(out[0]["taslak"], URUN), "")
        self.assertEqual(elle, {})

    def test_net_fiyat_degilse_taslak_yok(self):
        r = kayit()
        r["net_fiyat"] = False
        out, elle = yorum.taslaklari_yaz([r], SIMDI)
        self.assertEqual(out, [])
        self.assertEqual(elle, {"net fiyat sorusu değil": 1})

    def test_yorum_linki(self):
        out, _ = yorum.taslaklari_yaz([kayit()], SIMDI)
        self.assertEqual(out[0]["yorum_link"], "https://www.instagram.com/p/M1/c/Y1/")

    def test_suite_postu_metrics_ile_eslenir(self):
        out, _ = yorum.taslaklari_yaz([kayit(media="M3")], SIMDI)
        self.assertEqual(len(out), 1)

    def test_dosyada_metin_kullanici_tur_saat_yok(self):
        yorum.taslaklari_yaz([kayit(), kayit("Y2", tur="sikayet"), kayit("Y3", tur="soru")], SIMDI)
        ham = (self.tmp / "t.json").read_text(encoding="utf-8")
        for yasak in ("GİZLİ METİN", "gizli_kullanici", "sikayet", '"soru"', "Y2", "Y3", '"tur"', '"zaman"'):
            self.assertNotIn(yasak, ham)
        self.assertIsNone(re.search(r"T\d\d:", ham))

    def test_elle_kalanlar_dosyaya_girmez(self):
        out, elle = yorum.taslaklari_yaz(
            [kayit("A", tur="sikayet"), kayit("B", tur="soru"), kayit("C", gun=20), kayit("D", media="M2"),
             kayit("E", media="YOK"), kayit("F", media="S1")], SIMDI)
        self.assertEqual(out, [])
        self.assertEqual(sum(elle.values()), 6)

    def test_bozuk_ya_da_saatsiz_zaman_eski_sayilir(self):
        for z in ("", "2026-11-25T10:00:00", None):
            r = kayit()
            r["zaman"] = z
            row, neden = yorum.taslak_kur(r, yorum._medya_haritasi(CAL, METRICS), self.urunler, {}, SIMDI)
            self.assertIsNone(row)
            self.assertIn("eski", neden)

    def test_stokta_degilse_taslak_yok(self):
        self.urunler[URUN["slug"]]["in_stock"] = False
        self.assertEqual(yorum.taslaklari_yaz([kayit()], SIMDI)[0], [])

    def test_yanit_gerekmeyen_ve_gonderilen_atlanir(self):
        self.yaz("g.json", {"Y2": {}})
        self.assertEqual(yorum.taslaklari_yaz([kayit("Y1", gerekli=False), kayit("Y2")], SIMDI)[0], [])

    def test_onay_dosyasina_dokunulmaz(self):
        self.yaz("o.json", {"Y1": "eski"})
        yorum.taslaklari_yaz([kayit()], SIMDI)
        self.assertEqual(self.oku("o.json"), {"Y1": "eski"})

    def test_yasak_ifade_yakalanir(self):
        self.assertTrue(yorum.yanit_denetle(f"{common.fmt_price(743.69)} indirimli", URUN))
        self.assertTrue(yorum.yanit_denetle("fiyat yok", URUN))


class SahteApi:
    def __init__(self, yanitlayanlar=(), hata=None):
        self.cagri = []
        self.yanitlayanlar = list(yanitlayanlar)
        self.hata = hata or {}

    def __call__(self, method, path, retries=None, **kw):
        self.cagri.append((method, path, retries, kw))
        if (method, path) in self.hata:
            raise self.hata[(method, path)]
        if method == "GET":
            return {"id": path, "replies": {"data": [{"username": u} for u in self.yanitlayanlar]}}
        return {"id": "R-" + path}

    def postlar(self):
        return [c for c in self.cagri if c[0] == "POST"]


class GonderTest(Ortam):
    def hazirla(self, *yidler, onayla=True):
        out, _ = yorum.taslaklari_yaz([kayit(y) for y in (yidler or ("Y1",))], SIMDI)
        if onayla:
            self.yaz("o.json", {t["yorum_id"]: t["ozet"] for t in out})
        return out

    def gonder(self, api, canli=True):
        with mock.patch.object(yorum, "_canli", return_value=canli), contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            return yorum.gonder(api=api, biz="nitrobisiklet")

    def test_onayli_bir_kez_gider(self):
        t = self.hazirla()[0]
        api = SahteApi()
        self.assertEqual(self.gonder(api), 1)
        self.assertEqual(len(api.postlar()), 1)
        method, path, retries, kw = api.postlar()[0]
        self.assertEqual((path, retries, kw["message"]), ("Y1/replies", 0, t["taslak"]))
        self.assertEqual(self.oku("g.json")["Y1"]["durum"], "gönderildi")
        api2 = SahteApi()
        self.assertEqual(self.gonder(api2), 0)
        self.assertEqual(api2.cagri, [])

    def test_onaysiz_ya_da_yanlis_ozet_gitmez(self):
        self.hazirla(onayla=False)
        api = SahteApi()
        self.assertEqual(self.gonder(api), 0)
        self.yaz("o.json", {"Y1": True})
        self.assertEqual(self.gonder(api), 0)
        self.yaz("o.json", {"Y1": "000000000000"})
        self.assertEqual(self.gonder(api), 0)
        self.assertEqual(api.cagri, [])

    def test_live_false_gitmez(self):
        self.hazirla()
        api = SahteApi()
        self.assertEqual(self.gonder(api, canli=False), 0)
        self.assertEqual(api.cagri, [])

    def test_fiyat_degistiyse_eski_onay_gecersiz(self):
        self.hazirla()
        self.urunler[URUN["slug"]]["price"] = 800
        yorum.taslaklari_yaz([kayit()], SIMDI)          # bot yeni metni yazar, onay dosyası eski özette kalır
        api = SahteApi()
        self.assertEqual(self.gonder(api), 0)
        self.assertFalse(api.postlar())

    def test_bot_metni_degisti_onay_kalmadi_birlestirme(self):
        # git birleştirmesi: taslak metni elle değiştirilmiş (özet tutmuyor) -> gönderilmez
        out = self.hazirla()
        out[0]["taslak"] += " ek"
        self.yaz("t.json", out)
        api = SahteApi()
        self.assertEqual(self.gonder(api), 0)

    def test_zaten_yanitladiysak_gitmez(self):
        self.hazirla()
        api = SahteApi(["NitroBisiklet"])
        self.assertEqual(self.gonder(api), 0)
        self.assertFalse(api.postlar())
        self.assertEqual(self.oku("g.json")["Y1"]["durum"], "zaten yanıtlanmış")

    def test_bir_yorumun_hatasi_digerlerini_durdurmaz(self):
        self.hazirla("Y1", "Y2", "Y3")
        api = SahteApi(hata={("GET", "Y1"): GraphError(400, "silinmiş", 100),
                             ("POST", "Y2/replies"): GraphError(400, "kısıtlı", 10)})
        self.assertEqual(self.gonder(api), 1)
        g = self.oku("g.json")
        self.assertNotIn("Y1", g)                       # okunamadı: kayıt yok, sonra tekrar okunabilir
        self.assertEqual(g["Y2"]["durum"], "hata")      # POST hatası: bir daha denenmez
        self.assertEqual(g["Y3"]["durum"], "gönderildi")
        api2 = SahteApi()
        self.gonder(api2)
        self.assertEqual([c[1] for c in api2.postlar()], ["Y1/replies"])

    def test_post_oncesi_deneniyor_yazilir(self):
        self.hazirla()
        gorulen = {}

        def api(method, path, retries=None, **kw):
            if method == "GET":
                return {"id": path}
            gorulen.update(self.oku("g.json"))
            raise RuntimeError("bağlantı koptu")

        with self.assertRaises(RuntimeError):
            self.gonder(api)
        self.assertEqual(gorulen["Y1"]["durum"], "deneniyor")
        api2 = SahteApi()
        self.gonder(api2)
        self.assertFalse(api2.postlar())


class MainTest(Ortam):
    def test_gonder_hatasi_cikis_sifir(self):
        with mock.patch.dict(os.environ, {"IG_ACCESS_TOKEN": "x"}), mock.patch.object(sys, "argv", ["yorum.py", "--gonder"]), \
                mock.patch.object(yorum, "gonder", side_effect=GraphError(500, "access_token=x", 1)), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(yorum.main(), 0)
        self.assertIn("gönderim durdu", err.getvalue())
        self.assertNotIn("access_token=x", err.getvalue())


if __name__ == "__main__":
    unittest.main()
