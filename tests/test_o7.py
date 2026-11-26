"""O7 testleri: story insights, hesap insights, manuel.json ve haftalık KPI tablosu.

Gerçek Graph API'ye istek atılmaz: `graph.api` sahtesiyle değiştirilir, çıktı dosyaları geçici dizine yönlendirilir.
Çalıştırma: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import graph  # noqa: E402
import gorev  # noqa: E402
import report  # noqa: E402

TZ = report.TZ
T = datetime(2026, 11, 26, 22, 0, tzinfo=TZ)          # perşembe; son tamamlanan hafta 16–22 Kasım
ENV = {"IG_ACCESS_TOKEN": "test-degil-gercek", "IG_USER_ID": "123"}


def _story(sid: str, saat: str) -> dict:
    """26 Kasım'da yerel `saat`te (HH:MM) yayınlanmış story; Graph zaman damgası UTC."""
    h, m = (int(x) for x in saat.split(":"))
    ts = datetime(2026, 11, 26, h, m, tzinfo=TZ).astimezone(timezone.utc)
    return {"id": sid, "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S%z"), "media_type": "IMAGE",
            "permalink": f"https://www.instagram.com/stories/x/{sid}/"}


def _takvim_story(cid: str, saat: str, **ek) -> dict:
    return {"id": cid, "date": "2026-11-26", "time": saat, "type": "story", "format": "story", "channel": "suite",
            "status": "planned", "suite_scheduled": True, **ek}


class Ortam(unittest.TestCase):
    """Her test geçici dizinde çalışır; zaman, takvim, iptal listesi ve Graph API sahtedir."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.cal: list[dict] = []
        self.stories: list[dict] = []
        self.calls: list[tuple[str, dict]] = []
        patches = [
            mock.patch.object(report, "METRICS", self.tmp / "metrics.json"),
            mock.patch.object(report, "REPORT", self.tmp / "RAPOR.md"),
            mock.patch.object(report, "SCORES", self.tmp / "scores.json"),
            mock.patch.object(report, "MANUEL", self.tmp / "manuel.json"),
            mock.patch.object(report, "SUITE_INSIGHTS", self.tmp / "suite_insights.json"),
            mock.patch.object(report, "now", lambda: T),
            mock.patch.object(report, "load_calendar", lambda: self.cal),
            mock.patch.object(report, "cancelled_ids", lambda: set()),
            mock.patch.object(graph, "api", side_effect=self.api),
            mock.patch.dict(os.environ, ENV),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # Sahte Graph API: alt sınıflar `insights` yöntemini değiştirir.
    def api(self, method: str, path: str, **params):
        self.calls.append((path, params))
        if path == "123/stories":
            return {"data": self.stories}
        if path.endswith("/insights"):
            return self.insights(path, params)
        raise AssertionError(f"beklenmeyen çağrı: {path}")

    def insights(self, path: str, params: dict) -> dict:
        if params.get("breakdown"):
            return {"data": [{"name": "navigation", "total_value": {"breakdowns": [
                {"dimension_keys": ["story_navigation_action_type"],
                 "results": [{"dimension_values": ["tap_forward"], "value": 5}]}]}}]}
        return {"data": [{"name": k, "values": [{"value": 7}]} for k in params["metric"].split(",")]}

    def calistir(self, *args: str) -> str:
        """report.main()'i argümanlarla çalıştırır; stderr metnini döndürür. main() asla SystemExit fırlatmamalı."""
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["report.py", *args]), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            report.main()
        return err.getvalue()

    def metrics(self) -> dict:
        return json.loads(report.METRICS.read_text(encoding="utf-8"))


class StoryIzin(Ortam):
    def test_insights_izni_yok_yalniz_uyari(self) -> None:
        eski = {"updated": "2026-11-25T10:00:00+03:00", "account": [{"date": "2026-11-25", "followers": 2665}],
                "media": {"p1": {"media_id": "M1", "likes": 13}}, "insights": True, "errors": []}
        report.METRICS.write_text(json.dumps(eski), encoding="utf-8")
        self.stories = [_story("S1", "20:31")]

        def izinsiz(path, params):
            raise graph.GraphError(403, "Application does not have permission for this action", 10)

        self.insights = izinsiz
        err = self.calistir("--story")   # SystemExit yok: çıkış kodu 0
        self.assertIn("izni yok", err)
        m = self.metrics()
        for k in ("updated", "account", "media", "insights", "errors"):
            self.assertEqual(m[k], eski[k], k)
        self.assertNotIn("reach", m["stories"]["S1"])
        self.assertEqual(m["link_testi"]["sonuc"], "denenmedi")
        # insights yalnız bir kez denendi (izin yoksa bu çalışmada bir daha denenmez)
        self.assertEqual(sum(1 for p, _ in self.calls if p.endswith("/insights")), 1)

    def test_story_listesi_izni_yok_dosya_bozulmaz(self) -> None:
        report.METRICS.write_text('{"updated": null, "account": [], "media": {}}', encoding="utf-8")
        once = report.METRICS.read_bytes()

        def api(method, path, **params):
            raise graph.GraphError(400, "missing permission", 200)

        with mock.patch.object(graph, "api", side_effect=api):
            err = self.calistir("--story")
        self.assertIn("UYARI", err)
        self.assertEqual(report.METRICS.read_bytes(), once)

    def test_jetonsuz_cikis_kodu_sifir(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("IG_ACCESS_TOKEN", "IG_USER_ID")}
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "report.py"), "--story"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)


class StoryMetrik(Ortam):
    def insights(self, path: str, params: dict) -> dict:
        if not params.get("breakdown") and "navigation" in params["metric"].split(","):
            raise graph.GraphError(400, "(#100) metric[7] must be one of the following values", 100)
        return super().insights(path, params)

    def test_metrik_tek_tek_atlanir(self) -> None:
        self.stories = [_story("S1", "09:31"), _story("S2", "12:31")]
        self.calistir("--story")
        m = self.metrics()
        for sid in ("S1", "S2"):
            rec = m["stories"][sid]
            for k in ("reach", "views", "replies", "shares", "total_interactions", "follows", "profile_visits"):
                self.assertEqual(rec[k], 7, (sid, k))
            self.assertNotIn("navigation", rec)
            self.assertIn("checked", rec)
        # desteklenmeyen metrik ikinci story'de yeniden istenmedi
        nav = [p for p, q in self.calls if not q.get("breakdown") and "navigation" in q.get("metric", "").split(",")]
        self.assertEqual(nav, ["S1/insights", "S1/insights"])   # 1 toplu + 1 tek başına; S2'de hiç

    def test_link_testi_donmuyor(self) -> None:
        self.stories = [_story("S1", "09:31")]
        self.calistir("--story")
        lt = self.metrics()["link_testi"]
        self.assertEqual(lt["sonuc"], "donmuyor")
        self.assertIn("manuel.json", lt["not"])
        self.assertEqual(set(lt), {"tarih", "sonuc", "not", "story", "anahtarlar"})

    def test_link_testi_donuyor(self) -> None:
        # Varsayımsal yanıt: kırılımda adında "link" geçen bir değer dönerse test "donuyor" der.
        def insights(path, params):
            if params.get("breakdown"):
                return {"data": [{"name": "navigation", "total_value": {"breakdowns": [
                    {"results": [{"dimension_values": ["ornek_link_degeri"], "value": 3}]}]}}]}
            return Ortam.insights(self, path, params)

        self.insights = insights
        self.stories = [_story("S1", "09:31")]
        self.calistir("--story")
        m = self.metrics()
        self.assertEqual(m["link_testi"]["sonuc"], "donuyor")
        self.assertEqual(m["stories"]["S1"]["navigation_kirilim"], {"ornek_link_degeri": 3})


class StoryGeciciHata(Ortam):
    def insights(self, path: str, params: dict) -> dict:
        raise graph.GraphError(500, "An unexpected error has occurred", 2, transient=True)

    def test_gecici_hatada_metrik_metrik_denenmez_ve_durur(self) -> None:
        self.stories = [_story(f"S{i}", f"0{i}:31") for i in range(1, 5)]
        err = self.calistir("--story")
        ins = [p for p, q in self.calls if p.endswith("/insights") and not q.get("breakdown")]
        # her story'de yalnız toplu istek; STREAK_LIMIT story'den sonra kalanlar denenmez
        self.assertEqual(ins, [f"S{i}/insights" for i in range(1, report.STREAK_LIMIT + 1)])
        self.assertIn("art arda", err)
        self.assertEqual(len(self.metrics()["stories"]), 4)   # liste yine yazılır


class MetricsBozuk(Ortam):
    def test_hafif_mod_bozuk_dosyanin_uzerine_yazmaz(self) -> None:
        report.METRICS.write_text('{"account": [{"date": "2026-11-25", "followers": 2665}], "media": {"P1": {',
                                  encoding="utf-8")
        once = report.METRICS.read_bytes()
        self.stories = [_story("S1", "09:31")]
        for mod in ("--story", "--esle"):
            err = self.calistir(mod)
            self.assertIn("üzerine yazılmıyor", err, mod)
            self.assertEqual(report.METRICS.read_bytes(), once, mod)

    def test_write_json_atomik(self) -> None:
        report.write_json(report.METRICS, {"a": 1})
        self.assertEqual(self.metrics(), {"a": 1})
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["metrics.json"])   # geçici dosya kalmaz


class StoryEsleme(Ortam):
    def test_tek_aday_eslenir_takvim_degismez(self) -> None:
        self.cal = [_takvim_story("2026-11-26-story-2030", "20:30")]
        once = copy.deepcopy(self.cal)
        self.stories = [_story("S1", "20:33")]
        self.calistir("--story")
        m = self.metrics()
        self.assertEqual(m["stories"]["S1"]["takvim_id"], "2026-11-26-story-2030")
        self.assertEqual(m["stories"]["S1"]["eslesme"]["fark_sn"], 180)
        self.assertEqual(self.cal, once)
        esl, due, miss = report.story_esleme_orani(self.cal, m | {"story_baslangic": "2026-11-26T00:00:00+03:00"}, T)
        self.assertEqual((esl, due, miss), (1, 1, []))

    def test_iki_aday_eslenmez(self) -> None:
        self.cal = [_takvim_story("2026-11-26-story-2030", "20:30")]
        self.stories = [_story("S1", "20:31"), _story("S2", "20:35")]
        self.calistir("--story")
        m = self.metrics()
        self.assertFalse(any(r.get("takvim_id") for r in m["stories"].values()))

    def test_aday_yok_eslenmez(self) -> None:
        self.cal = [_takvim_story("2026-11-26-story-2030", "20:30")]
        self.stories = [_story("S1", "20:45")]
        self.calistir("--story")
        self.assertNotIn("takvim_id", self.metrics()["stories"]["S1"])

    def test_son_deger_korunur(self) -> None:
        report.METRICS.write_text(json.dumps({"stories": {"ESKI": {"media_id": "ESKI", "reach": 40}}}),
                                  encoding="utf-8")
        self.stories = [_story("S1", "09:31")]
        self.calistir("--story")
        m = self.metrics()
        self.assertEqual(m["stories"]["ESKI"]["reach"], 40)   # yayından düşen story'nin son değeri kalır
        self.assertIn("S1", m["stories"])


class HesapInsights(Ortam):
    def insights(self, path: str, params: dict) -> dict:
        self.assertEqual(path, "123/insights")
        self.assertEqual((params["period"], params["metric_type"]), ("day", "total_value"))
        self.assertEqual(params["until"] - params["since"], 7 * 86400)
        if "profile_links_taps" in params["metric"].split(","):
            raise graph.GraphError(400, "(#100) metric not supported", 100)
        return {"data": [{"name": k, "total_value": {"value": 11}} for k in params["metric"].split(",")]}

    def test_hafta_anahtari_ve_metrik_atlama(self) -> None:
        m = report.load_metrics()
        with contextlib.redirect_stderr(io.StringIO()):
            n = report.hesap_insights(m, T.isoformat())
        self.assertEqual(n, 2)
        self.assertEqual(sorted(m["hesap_insights"]), ["2026-11-09", "2026-11-16"])
        rec = m["hesap_insights"]["2026-11-16"]
        self.assertEqual((rec["reach"], rec["profile_views"], rec["follows_and_unfollows"]), (11, 11, 11))
        self.assertNotIn("profile_links_taps", rec)
        self.assertIn("profile_links_taps", rec["hatalar"])
        self.assertIn("profile_links_taps", m["hesap_insights"]["2026-11-09"]["hatalar"])
        # desteklenmeyen metrik ikinci haftada yeniden istenmedi: 1 toplu + 1 tek başına (ilk hafta) ve sonra yok
        taps = [q for _, q in self.calls if "profile_links_taps" in q["metric"].split(",")]
        self.assertEqual(len(taps), 2)
        self.assertEqual(rec["bitis"], "2026-11-22")


class ManuelVeKpi(Ortam):
    def kpi(self, manuel: dict, metrics: dict | None = None) -> dict[str, list[str]]:
        return {r[0]: r for r in report.kpi_satirlari(self.cal, metrics or report.load_metrics(), manuel, T)}

    def test_manuel_yok(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(report.load_manuel(), {})
        self.assertIn("UYARI", err.getvalue())
        r = self.kpi({})["Haftalık profil ziyareti"]
        self.assertEqual((r[2], r[3], r[5]), ("veri yok", "veri yok", "veri yok"))

    def test_manuel_bozuk(self) -> None:
        report.MANUEL.write_text("{bozuk", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(report.load_manuel(), {})
        self.assertIn("bozuk", err.getvalue())

    def test_manuel_null_veri_yok(self) -> None:
        report.MANUEL.write_text(json.dumps({"haftalar": {
            "2026-11-16": {"profil_ziyareti": None, "link_tiklamasi": 130, "nkod_talep": True, "ga4_arama_payi": 8.5},
            "2026-11-18": {"profil_ziyareti": 999}}}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            man = report.load_manuel()
        self.assertEqual(list(man), ["2026-11-16"])          # pazartesi olmayan anahtar atlandı
        rows = self.kpi(man)
        self.assertEqual(rows["Haftalık profil ziyareti"][5], "veri yok")   # null sıfır sayılmaz
        self.assertEqual(rows["Haftalık N-kodu talebi (satışa dönen ayrıca)"][5], "veri yok")   # bool sayı değil
        self.assertEqual(rows["Haftalık link tıklaması (story + bio)"][2:], ["130", "veri yok", "Suite → manuel.json",
                                                                           "hedefte"])
        self.assertEqual(rows["Aynı oturumlarda arama payı"][2], "%8,5")
        self.assertEqual(rows["Aynı oturumlarda arama payı"][5], "hedefte")

    def test_api_once_gelir(self) -> None:
        man = {"2026-11-16": {"profil_ziyareti": 230}}
        m = report.load_metrics()
        m["hesap_insights"] = {"2026-11-16": {"profile_views": 150}}
        r = self.kpi(man, m)["Haftalık profil ziyareti"]
        self.assertEqual((r[2], r[5]), ("150", "altında"))
        self.assertIn("API", r[4])
        self.assertEqual(self.kpi(man)["Haftalık profil ziyareti"][5], "hedefte")

    def test_kpi_tablosunda_plandaki_her_kpi_var(self) -> None:
        plan = (ROOT / "docs" / "TRAFIK-PLANI.md").read_text(encoding="utf-8")
        bolum = plan.split("## 2. Hedefler ve KPI'lar", 1)[1].split("\n## 3.", 1)[0]
        beklenen = []
        for satir in bolum.splitlines():
            if not satir.startswith("| ") or satir.startswith("| KPI ") or re.match(r"^\|\s*-", satir):
                continue
            beklenen.append(satir.split("|")[1].strip().replace("*", "").replace("`", ""))
        self.assertEqual(len(beklenen), 14)   # 3 ana + 11 ikincil
        rows = report.kpi_satirlari(self.cal, report.load_metrics(), {}, T)
        self.assertEqual([r[0] for r in rows], beklenen)
        for r in rows:
            self.assertEqual(len(r), 6)
            self.assertIn(r[5], ("hedefte", "altında", "veri yok"))

    def test_yayin_sagligi_kayitsiz_hafta_veri_yok(self) -> None:
        ad = "Yayın sağlığı: missed/error, zamanlanmamış linkli story"
        self.cal = [{"id": "2026-11-24-post", "date": "2026-11-24", "time": "12:00", "type": "post",
                     "status": "planned"}]
        r = self.kpi({})[ad]
        self.assertTrue(r[2].startswith("veri yok"), r)   # 16–22 Kasım takvimde yok: 0 sayılmaz
        self.assertEqual((r[3], r[5]), ("veri yok", "veri yok"))
        self.cal.append({"id": "2026-11-17-post", "date": "2026-11-17", "time": "12:00", "type": "post",
                         "status": "missed"})
        r = self.kpi({})[ad]
        self.assertTrue(r[2].startswith("1 / 0 / "), r)
        self.assertEqual(r[5], "altında")

    def test_rapor_bolumu(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            text = report.write_report(self.cal, report.load_metrics(), {}, manuel={})
        self.assertIn("## Haftalık KPI", text)
        self.assertIn("Link dokunuşu API testi", text)
        self.assertIn("Suite story eşlemesi", text)
        self.assertIn("| KPI ", text)

    def test_load_metrics_geriye_uyumlu(self) -> None:
        report.METRICS.write_text(json.dumps({"updated": "x", "account": [], "media": {}, "insights": None,
                                              "errors": []}), encoding="utf-8")
        m = report.load_metrics()
        self.assertEqual(set(m), {"updated", "account", "media", "insights", "errors", "stories", "hesap_insights"})


class Gorev(unittest.TestCase):
    def test_yayinla_story_calistirir(self) -> None:
        cagri = []
        with mock.patch.object(gorev, "live", return_value=False), \
                mock.patch.object(gorev, "run", side_effect=lambda *a, **k: cagri.append((a, k))), \
                contextlib.redirect_stdout(io.StringIO()):
            gorev.yayinla()
        self.assertEqual(cagri, [(("report.py", "--esle"), {"must": False}), (("report.py", "--story"), {"must": False}),
                                 (("yorum.py", "--gonder"), {"must": False})])


if __name__ == "__main__":
    unittest.main()
