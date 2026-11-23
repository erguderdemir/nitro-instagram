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
from datetime import datetime, timezone
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


def live() -> bool:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("live") is True


def main() -> None:
    task = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GOREV", "")).strip()
    if not task:
        task = "plan" if os.environ.get("ZAMANLAMA", "").strip() == PLAN_CRON else "publish"
    print(f"[gorev] görev: {task}", flush=True)
    if task == "plan":
        try:
            run("scrape.py", must=False, log=True)  # site erişilemezse eldeki ürün verisiyle devam
            run("plan.py", log=True)
            run("denetim.py", log=True)
        finally:
            head = f"görev: plan · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
            (ROOT / "data" / "son-calisma.log").write_text("\n".join([head, *LOG[-400:]]) + "\n", encoding="utf-8")
        run("report.py", must=False)
    elif task == "publish":
        if not live():
            print("[gorev] Yayın kilitli (config.json live=false). Hiçbir şey yayınlanmadı.")
            return
        run("publish.py")
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
