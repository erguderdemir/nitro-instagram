#!/usr/bin/env python3
"""GitHub Actions giriş noktası: görevi seçer, ilgili betikleri sırayla çalıştırır.

İş akışı dosyası yalnız bu betiği çağırır; görevlerin içeriği burada ve çağrılan betiklerde yaşar
(iş akışı dosyasına dokunmadan görev değiştirilebilsin diye).

  GOREV       elle tetiklemede görev adı: check | plan | publish | probe | report
  ZAMANLAMA   zamanlanmış çalışmada tetikleyen cron ifadesi
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "scripts"
PLAN_CRON = "10 1 * * *"
LOG: list[str] = []
SECRETS = ("IG_ACCESS_TOKEN", "IG_USER_ID")


def run(script: str, *args: str, must: bool = True, log: bool = False) -> int:
    """Betiği çalıştır. log=True: sırlar ortamdan çıkarılır, çıktı data/son-calisma.log'a da yazılır."""
    path = S / script
    if not path.exists():
        print(f"[gorev] {script} yok, atlandı", flush=True)
        LOG.append(f"$ {script}: yok, atlandı")
        return 0
    print(f"[gorev] {script} {' '.join(args)}", flush=True)
    cmd = [sys.executable, str(path), *args]
    if log:
        env = {k: v for k, v in os.environ.items() if k not in SECRETS}
        p = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(p.stdout, flush=True)
        LOG.append(f"$ {script} {' '.join(args)} -> çıkış {p.returncode}")
        LOG.extend(p.stdout.splitlines()[-150:])
        code = p.returncode
    else:
        code = subprocess.call(cmd, cwd=ROOT)
    if code and must:
        raise SystemExit(code)
    return code


def alarmlar() -> list[str]:
    """İnsanın bilmesi gereken durumlar: yayınlanamayan/taslağa çekilen kayıt, Suite uyarısı, jeton sorunu.

    Bulut tetikleriyle başlayan çalışmaları github-actions[bot] tetikler; kırmızı biten bu çalışmalar için GitHub
    kimseye e-posta atmaz. Alarm, durum düzelene (ya da 48 saat geçene) kadar günlük plan çalışmasını kırmızı
    bitirir; depo sahibinin tetiklediği zamanlanmış plan (cron) çalışması kırmızı biter ve günde bir e-posta gider.
    publish çalışmaları alarmla kırmızıya çekilmez (15 dakikada bir e-posta yağmuru olmasın); kendi hatalarında
    zaten kırmızı biterler."""
    sys.path.insert(0, str(S))
    import common  # noqa: E402

    now, out = common.now(), []
    for c in common.load_calendar():
        try:
            dt = common.item_dt(c)
        except (KeyError, TypeError, ValueError):
            continue
        st = c.get("status")
        if st in ("error", "missed") and timedelta(0) <= now - dt <= timedelta(hours=48):
            out.append(f"{c.get('id')} {st}: {str(c.get('error') or 'geç kaldı')[:160]}")
        elif st == "draft" and -timedelta(hours=3) <= dt - now <= timedelta(hours=36):
            out.append(f"{c.get('id')} denetim bulgusuyla taslağa çekildi, yayınlanmayacak (data/denetim.json)")
    den = common.read_json(common.DATA / "denetim.json", {})
    ileri = {c.get("id") for c in common.load_calendar() if c.get("status") == "planned"}
    for f in den.get("suite_warnings") or []:
        if f.get("id") in ileri:
            out.append(f"{f.get('id')} Suite uyarısı [{f.get('code')}]: {str(f.get('msg'))[:160]}")
    jet = common.read_json(common.DATA / "jeton.json", {})
    if jet:
        if jet.get("gecerli") is False:
            out.append("Instagram erişim jetonu GEÇERSİZ ya da yetkisiz: paylaşımlar API ile yayınlanamaz (jetonu yenile)"
                       + (f" [{str(jet.get('hata'))[:120]}]" if jet.get("hata") else ""))
        for alan, ad in (("bitis", "jeton"), ("veri_erisim_bitis", "jetonun veri erişimi")):
            t = jet.get(alan) or 0
            if t and datetime.fromtimestamp(t, timezone.utc) - now <= timedelta(days=10):
                out.append(f"Instagram {ad} {datetime.fromtimestamp(t, timezone.utc):%Y-%m-%d} tarihinde bitiyor: yenile")
    tar = common.read_json(common.DATA / "tarama.json", {})
    if tar:
        # Alarm günde bir (plan çalışmasında) bakılır; 30 saat eşiği, cron gecikmesi ne olursa olsun iki ardışık
        # başarısız günde alarm verir (tek başarısız gün, ertesi gün başarılıysa alarm vermez).
        try:
            yas = now - datetime.fromisoformat(tar["son_basari"])
        except (KeyError, TypeError, ValueError):
            yas = timedelta(days=99)  # hiç başarılı tarama kaydı yok
        if yas > timedelta(hours=30):
            out.append(("Site taraması hiç başarılı olmadı" if yas >= timedelta(days=99) else
                        f"Site taraması {int(yas.total_seconds() // 3600)} saattir başarısız")
                       + "; ürün/stok/fiyat verisi eski"
                       + (f" [{str(tar.get('son_hata'))[:160]}]" if tar.get("son_hata") else ""))
    return out


def alarm_bitir() -> None:
    a = alarmlar()
    if not a:
        print("[gorev] alarm yok", flush=True)
        return
    for x in a:
        print(f"::error::{x}", flush=True)
    raise SystemExit(f"[gorev] {len(a)} alarm: çalışma kırmızı bitiriliyor (bildirim için).")


def live() -> bool:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("live") is True


def yayinla() -> None:
    try:
        if not live():
            print("[gorev] Yayın kilitli (config.json live=false). Hiçbir şey yayınlanmadı.")
            return
        run("denetim.py", must=False)  # bulgulu kayıt taslağa çekilir; yayıncı yalnız planlı kayıtları işler
        run("publish.py")
    finally:
        # Suite'te zamanlanmış postları Business Suite yayınlar (kilitten bağımsız): /media ile eşle, 72 saat
        # dolmuş ölçümü dondur -> data/metrics.json. Hafif mod; hatası ya da izin eksikliği yayını kırmaz.
        run("report.py", "--esle", must=False)


def main() -> None:
    task = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GOREV", "")).strip()
    if not task:
        task = "plan" if os.environ.get("ZAMANLAMA", "").strip() == PLAN_CRON else "publish"
    print(f"[gorev] görev: {task}", flush=True)
    # Zamanlanmış plan cron'u saatlerce gecikip gün içinde gelebiliyor; aynı concurrency grubunda kuyrukta
    # bekleyen publish çalışmasını iptal ettirir. Gecikmiş plan bu yüzden yayın işini de üstlenir.
    gecikmis = (not os.environ.get("GOREV", "").strip() and task == "plan"
                and not 0 <= datetime.now(timezone.utc).hour < 4)
    if task == "plan":
        try:
            try:
                run("scrape.py", must=False, log=True)  # site erişilemezse eldeki ürün verisiyle devam
                run("arama.py", must=False, log=True)   # yeni/adı değişen ürünler için site arama terimi (CTA)
                run("plan.py", log=True)
                run("denetim.py", log=True)   # sıfır bulgu şartı: bulgu varsa görev kırmızı biter, bulgulu kayıt yayınlanmaz
            finally:
                head = f"görev: plan · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
                (ROOT / "data" / "son-calisma.log").write_text("\n".join([head, *LOG[-400:]]) + "\n", encoding="utf-8")
            run("report.py", must=False)
            run("paylas.py", must=False)   # O12: data/paylas/ paketleri; betik yoksa atlanır
            run("yorum.py", must=False)    # O15: yorum özeti; betik yoksa atlanır, hatası planı kırmaz
            run("publish.py", "--check", must=False)  # jeton geçerliliği ve bitiş tarihi -> data/jeton.json
        finally:
            if gecikmis:  # plan düşse bile kuyruktan düşmüş olabilecek yayın yapılsın
                print("[gorev] plan cron'u gecikmeli geldi: kuyruktan düşmüş olabilecek publish de çalıştırılıyor",
                      flush=True)
                os.environ["YAYIN_BEKLEME_YOK"] = "1"  # 50 dk iş zaman aşımı: yaklaşan paylaşımı sonraki tetik alır
                yayinla()
        alarm_bitir()
    elif task == "publish":
        yayinla()
    elif task == "check":
        run("publish.py", "--check")
    elif task == "probe":
        run("publish.py", "--probe")
    elif task == "report":
        run("report.py")
    else:
        raise SystemExit(f"Bilinmeyen görev: {task}")


if __name__ == "__main__":
    main()
