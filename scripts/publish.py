#!/usr/bin/env python3
"""Zamanı gelen post/story'leri Instagram Graph API ile yayınlar.

Ortam değişkenleri (GitHub Secrets):
  IG_ACCESS_TOKEN   Meta System User token'ı (süresiz)
  IG_USER_ID        Instagram işletme hesabı ID'si (bilmiyorsan: python3 scripts/publish.py --check)
  PUBLIC_BASE_URL   Görsellerin yayınlandığı GitHub Pages adresi, ör. https://kullanici.github.io/nitro-instagram

Kullanım:
  python3 scripts/publish.py            zamanı gelenleri yayınla
  python3 scripts/publish.py --dry-run  yalnızca ne yapılacağını yaz
  python3 scripts/publish.py --check    token'ı ve bağlı Instagram hesabını doğrula
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from plan import CFG, TZ, build_bio, build_takvim, item_dt, load_calendar, save_calendar

GRAPH = f"https://graph.facebook.com/{CFG['graph_api_version']}"
LATE_LIMIT = timedelta(hours=3)  # bu kadar gecikmiş paylaşım atlanır (gece yarısı story atmasın)


def api(method: str, path: str, **params) -> dict:
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    url = f"{GRAPH}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = body[:300]
        raise RuntimeError(f"Graph API {e.code}: {msg}") from None


def url_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def publish_one(c: dict, base: str) -> str:
    ig = os.environ["IG_USER_ID"]
    image_url = f"{base.rstrip('/')}/{c['image']}"
    if not url_ok(image_url):
        raise RuntimeError(f"Görsel herkese açık değil (Pages henüz güncellenmemiş olabilir): {image_url}")
    params = {"image_url": image_url}
    if c["type"] == "story":
        params["media_type"] = "STORIES"
    else:
        params["caption"] = c["caption"]
    container = api("POST", f"{ig}/media", **params)["id"]
    for _ in range(30):
        st = api("GET", container, fields="status_code").get("status_code")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Medya hazırlanamadı: {st}")
        time.sleep(5)
    return api("POST", f"{ig}/media_publish", creation_id=container)["id"]


def check() -> None:
    me = api("GET", "me", fields="id,name")
    print(f"Token sahibi: {me.get('name')} ({me['id']})")
    pages = api("GET", "me/accounts", fields="name,instagram_business_account{id,username}").get("data", [])
    for p in pages:
        ig = p.get("instagram_business_account")
        print(f"Sayfa: {p['name']}  ->  Instagram: {ig['username'] + ' / IG_USER_ID=' + ig['id'] if ig else 'bağlı değil'}")
    if not pages:
        print("Token'a hiç Facebook Sayfası atanmamış. System User'a sayfayı varlık olarak ekle.")


def main() -> None:
    if "--check" in sys.argv:
        return check()
    dry = "--dry-run" in sys.argv or not os.environ.get("IG_ACCESS_TOKEN")
    if dry:
        print("DRY-RUN: IG_ACCESS_TOKEN yok ya da --dry-run verildi, hiçbir şey yayınlanmayacak.")
    base = os.environ.get("PUBLIC_BASE_URL", "")
    now = datetime.now(TZ)
    cal = load_calendar()
    changed = False
    new_errors = 0
    for c in sorted(cal, key=item_dt):
        if c["status"] != "planned" or item_dt(c) > now:
            continue
        if now - item_dt(c) > LATE_LIMIT:
            c["status"] = "missed"
            changed = True
            print(f"ATLANDI (geç kaldı): {c['id']}")
            continue
        print(f"YAYIN: {c['id']}  {c['name']}")
        if dry:
            continue
        try:
            c["media_id"] = publish_one(c, base)
            c["status"] = "published"
            c["published_at"] = datetime.now(TZ).isoformat(timespec="seconds")
        except Exception as e:  # noqa: BLE001
            c["status"] = "error"
            c["error"] = str(e)[:500]
            print(f"HATA: {c['id']}: {e}", file=sys.stderr)
            new_errors += 1
        changed = True
    if changed and not dry:
        save_calendar(cal)
    build_bio(cal, now)
    build_takvim(cal)
    if new_errors:
        # İş akışı kırmızı görünsün, GitHub e-posta bildirimi göndersin
        sys.exit(f"{new_errors} paylaşım hata verdi. Ayrıntı: data/calendar.json içindeki 'error' alanı.")

if __name__ == "__main__":
    main()
