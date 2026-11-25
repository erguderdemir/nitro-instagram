#!/usr/bin/env python3
"""Instagram Graph API istemcisi (yalnız stdlib).

Ortam değişkenleri:
  IG_ACCESS_TOKEN   Meta System User token'ı (süresiz)
  IG_USER_ID        Instagram işletme hesabı ID'si; boşsa token'a bağlı tek hesap otomatik bulunur
"""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from common import CFG, ssl_context

GRAPH = f"https://graph.facebook.com/{CFG['graph_api_version']}"
_CTX = ssl_context()
# Meta'nın "sonra tekrar dene" dediği hata kodları: bilinmeyen, servis, uygulama/kullanıcı kotası, sayfa kotası
TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 613}


class GraphError(RuntimeError):
    def __init__(self, status: int, message: str, code: int | None = None, subcode: int | None = None,
                 transient: bool = False):
        super().__init__(f"Graph API {status}: {message}" + (f" (kod {code}/{subcode})" if code else ""))
        self.status, self.message, self.code, self.subcode, self.transient = status, message, code, subcode, transient


def _call(method: str, path: str, params: dict) -> dict:
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    url = f"{GRAPH}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90, context=_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(body)["error"]
            msg = err.get("error_user_msg") or err.get("message") or body[:300]
            code, sub = err.get("code"), err.get("error_subcode")
            transient = bool(err.get("is_transient")) or code in TRANSIENT_CODES or e.code >= 500
        except Exception:  # noqa: BLE001
            msg, code, sub, transient = body[:300], None, None, e.code >= 500
        raise GraphError(e.code, msg, code, sub, transient) from None
    except http.client.InvalidURL:
        # İstisna metni tam URL'yi (erişim jetonunu) içerir: yutulur, jetonsuz mesaj verilir.
        raise GraphError(0, "Geçersiz istek URL'si (erişim jetonunda boşluk ya da satır sonu olabilir)") from None


def api(method: str, path: str, *, retries: int | None = None, **params) -> dict:
    """Graph API çağrısı. GET'ler geçici hatalarda otomatik yeniden denenir.

    POST'lar varsayılan olarak yeniden DENENMEZ (aynı içeriğin iki kez yayınlanması riskine karşı);
    güvenli olduğu bilinen POST'lar için `retries=2` verilebilir.
    """
    if retries is None:
        retries = 2 if method == "GET" else 0
    for attempt in range(retries + 1):
        try:
            return _call(method, path, dict(params))
        except GraphError as e:
            if not e.transient or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise GraphError(0, f"Ağ hatası: {e}", transient=True) from None
        time.sleep(4 * (attempt + 1))
    raise AssertionError("unreachable")


def url_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ig_accounts() -> list[tuple[str, str, dict | None]]:
    """(sayfa adı, sayfa ID'si, bağlı Instagram hesabı) listesi."""
    pages = api("GET", "me/accounts", fields="id,name,instagram_business_account{id,username}").get("data", [])
    return [(p["name"], p["id"], p.get("instagram_business_account")) for p in pages]


def ig_user_id() -> str:
    if os.environ.get("IG_USER_ID"):
        return os.environ["IG_USER_ID"]
    found = [ig for _, _, ig in ig_accounts() if ig]
    if len(found) != 1:
        raise RuntimeError(f"Token'a bağlı {len(found)} Instagram hesabı var; IG_USER_ID secret'ını elle gir.")
    os.environ["IG_USER_ID"] = found[0]["id"]
    return found[0]["id"]
