"""Rota rehberi PDF'i: data/rotalar.json + data/rota_geo.json -> docs/rotalar/NITRO-Rota-Rehberi.pdf

Kullanım:
  python3 scripts/rota_pdf.py --geo-indir   # OSM'den rota ve göl geometrisini indirip data/rota_geo.json yazar
  python3 scripts/rota_pdf.py               # HTML + PDF üretir (headless Chrome ile)

Sayılar yalnız data/rotalar.json'dan gelir; bu betik hiçbir değeri hesaplamaz ya da yuvarlamaz
(tek türetilen değer, kaynak gösterilerek "m/km" ortalama eğimdir).
"""
import argparse
import html
import json
import math
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import rotalar  # noqa: E402

VERI = REPO / "data" / "rotalar.json"
GEO = REPO / "data" / "rota_geo.json"
CIKTI = REPO / "docs" / "rotalar"
HTML_AD = "rehber.html"
PDF_AD = "NITRO-Rota-Rehberi.pdf"
SITE = "https://nitrobisiklet.com/"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
GOL_REL = 1186573  # Köyceğiz Gölü (natural=water)
# Haritada yer adı noktaları (Nominatim, 26 Kasım 2026)
YERLER = [("Köyceğiz", 36.9585, 28.6889), ("Dalyan", 36.8350, 28.6424), ("Ortaca", 36.8389, 28.7654),
          ("Sultaniye", 36.8812, 28.5804), ("Ekincik", 36.8326, 28.5506), ("Sarıgerme", 36.7130, 28.7036)]
SIRA_KOD = {"k1-koycegiz-golu": "K1", "k2-sigla": "K2", "k3-trans-olemez": "K3", "k4-yuvarlakcay": "K4",
            "k5-trans-sandras": "K5", "o1-ortaca-3-kumsal": "O1", "o2-kosten-dagi": "O2",
            "o3-kaya-mezarlari": "O3", "o4-dalaman-cayi": "O4"}
DIGER_SIRA = ["koycegiz-eski-koycegiz", "gol-halkasi-feribotlu", "koycegiz-dalyan", "koycegiz-ekincik",
              "koycegiz-gokceova-goleti", "koycegiz-bisiklet-yolu"]
RENK = ["#f5821f", "#2a3220", "#dd6410", "#6b8a3a", "#14150f", "#b5541a", "#7c8f5a", "#c9641c", "#4d5a35"]
TIP_AD = {"halka": "Halka", "gidis-donus": "Gidiş-dönüş", "tek-yon": "Tek yön", "bilinmiyor": "—"}
KIS_AD = {"evet": "Uygun", "kosullu": "Koşullu", "hayir": "Uygun değil", "bilinmiyor": "Bilgi yok"}
ETKI_AD = {"kapatir": "rotayı kapattı", "kismen": "kısmen etkiledi", "etkilemez": "etkilemedi", "bilinmiyor": "etkisi belirsiz"}
GECERLI_AD = {"evet": "hâlâ geçerli", "hayir": "sona erdi", "bilinmiyor": "güncelliği belirsiz"}
SEVIYE = {"Kolay": "kolay", "Orta": "orta", "Orta zorlukta": "orta", "Zor": "zor", "Hard": "zor", "Çok zor": "cokzor"}
SEVIYE_AD = {"kolay": "Kolay", "orta": "Orta", "zor": "Zor", "cokzor": "Çok zor"}


# ---------- geometri ----------
def _getir(url):
    # curl: macOS Python sertifika deposu eksik olabiliyor
    r = subprocess.run(["curl", "-sf", "-m", "90", "-A", "nitro-rota-rehberi/1.0", url],
                       check=True, capture_output=True, timeout=120)
    return json.loads(r.stdout)


def _dp(pts, tol):
    """Douglas-Peucker; pts: [(x_km, y_km, lon, lat)]"""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0][:2], pts[-1][:2]
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1e-9
    i, dmax = 0, -1
    for k in range(1, len(pts) - 1):
        d = abs(dy * pts[k][0] - dx * pts[k][1] + x2 * y1 - y2 * x1) / n
        if d > dmax:
            i, dmax = k, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return _dp(pts[:i + 1], tol)[:-1] + _dp(pts[i:], tol)


def _yollar(full, rel_id, roller=None):
    el = full["elements"]
    dug = {e["id"]: (e["lon"], e["lat"]) for e in el if e["type"] == "node"}
    yol = {e["id"]: e["nodes"] for e in el if e["type"] == "way"}
    rel = next(e for e in el if e["type"] == "relation" and e["id"] == rel_id)
    cikti = []
    for m in rel["members"]:
        if m["type"] != "way" or m["ref"] not in yol or (roller and m["role"] not in roller):
            continue
        pts = [dug[n] for n in yol[m["ref"]] if n in dug]
        lat0 = math.radians(36.9)
        p = [(lo * 111.32 * math.cos(lat0), la * 110.57, lo, la) for lo, la in pts]
        cikti.append([[round(q[2], 5), round(q[3], 5)] for q in _dp(p, 0.012)])
    return cikti


def _halkala(parcalar):
    """Dış halka parçalarını uç uca ekleyip kapalı halkalar yapar."""
    kalan = [list(p) for p in parcalar]
    halkalar = []
    while kalan:
        h = kalan.pop(0)
        degisti = True
        while degisti and h[0] != h[-1]:
            degisti = False
            for i, p in enumerate(kalan):
                if p[0] == h[-1]:
                    h += p[1:]
                elif p[-1] == h[-1]:
                    h += p[::-1][1:]
                elif p[-1] == h[0]:
                    h = p + h[1:]
                elif p[0] == h[0]:
                    h = p[::-1] + h[1:]
                else:
                    continue
                kalan.pop(i)
                degisti = True
                break
        halkalar.append(h)
    return halkalar


def rel_id(r):
    for u in [r.get("konum_kaynak") or ""] + r.get("kaynaklar", []):
        m = re.search(r"(?:waymarkedtrails\.org/api/v1/details/relation|openstreetmap\.org/api/0\.6/relation)/(\d+)", u)
        if m:
            return int(m.group(1))
    return None


def geo_indir():
    veri = json.loads(VERI.read_text(encoding="utf-8"))
    geo = {"kaynak": "© OpenStreetMap katkıcıları, ODbL", "indirme": date.today().isoformat(), "rotalar": {}}
    for r in veri["rotalar"]:
        rid = rel_id(r)
        if not rid:
            continue
        full = _getir(f"https://api.openstreetmap.org/api/0.6/relation/{rid}/full.json")
        geo["rotalar"][r["id"]] = {"relation": rid, "yollar": _yollar(full, rid)}
        print(r["id"], rid, len(geo["rotalar"][r["id"]]["yollar"]), "yol")
    gol = _getir(f"https://api.openstreetmap.org/api/0.6/relation/{GOL_REL}/full.json")
    geo["gol"] = _halkala(_yollar(gol, GOL_REL, roller={"outer"}))
    GEO.write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("yazıldı:", GEO)


# ---------- biçim ----------
def e(s):
    return html.escape(str(s), quote=True)


def sayi_tr(v, ondalik=None):
    if v is None:
        return "—"
    if isinstance(v, float) and not v.is_integer():
        s = f"{v:,.{ondalik if ondalik is not None else len(repr(v).split('.')[1])}f}"
    else:
        s = f"{int(v):,}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def kes(s, n):
    s = s or ""
    if len(s) <= n:
        return e(s)
    return e(s[:n].rsplit(" ", 1)[0].rstrip(",;:(")) + "…"


def ad(r):
    return r["ad"].replace("The ECO Trails ", "")


def deger(r, alan):
    g = r.get(alan)
    return g["deger"] if isinstance(g, dict) else None


def kod(r, i_diger):
    return SIRA_KOD.get(r["id"]) or f"D{i_diger}"


def alan_adi(u):
    m = re.match(r"https?://(?:www\.)?([^/]+)", u or "")
    return m.group(1) if m else ""


def utm(rid, medium="rehber"):
    return f"{SITE}?utm_source=pdf&utm_medium={medium}&utm_campaign=rotalar&utm_content={rid}"


def qr_svg(veri, boy=88):
    from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel
    q = QRCode(None, QRErrorCorrectLevel.M)
    q.addData(veri)
    q.make()
    n = q.getModuleCount()
    rects = "".join(f'<rect x="{c}" y="{r_}" width="1.02" height="1.02"/>'
                    for r_ in range(n) for c in range(n) if q.isDark(r_, c))
    return (f'<svg viewBox="-2 -2 {n + 4} {n + 4}" width="{boy}" height="{boy}" shape-rendering="crispEdges">'
            f'<rect x="-2" y="-2" width="{n + 4}" height="{n + 4}" fill="#fff"/><g fill="#14150f">{rects}</g></svg>')


# ---------- harita ----------
LAT0 = math.cos(math.radians(36.9))


def _xy(lo, la):
    return lo * 111.32 * LAT0, -la * 110.57


def harita_svg(geo, idler, w, h, pay=0.08, etiket=True, renkler=None, kalin=3.2, kod_etiket=None):
    pts = [_xy(*p) for i in idler for y in geo["rotalar"][i]["yollar"] for p in y]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    dx, dy = (x1 - x0) or 1, (y1 - y0) or 1
    x0, x1, y0, y1 = x0 - dx * pay, x1 + dx * pay, y0 - dy * pay, y1 + dy * pay
    s = min(w / (x1 - x0), h / (y1 - y0))
    ox, oy = (w - (x1 - x0) * s) / 2, (h - (y1 - y0) * s) / 2

    def P(lo, la):
        x, y = _xy(lo, la)
        return (x - x0) * s + ox, (y - y0) * s + oy

    def yol(p):
        return "M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in (P(*q) for q in p))

    o = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="harita" preserveAspectRatio="xMidYMid meet">']
    o.append(f'<rect width="{w}" height="{h}" fill="var(--kagit)"/>')
    for g in geo.get("gol", []):
        o.append(f'<path d="{yol(g)}Z" fill="#cfdcd6" stroke="#a9bfb6" stroke-width=".8"/>')
    for k, i in enumerate(idler):
        renk = (renkler or {}).get(i, "#f5821f")
        for y in geo["rotalar"][i]["yollar"]:
            o.append(f'<path d="{yol(y)}" fill="none" stroke="#fff" stroke-width="{kalin + 2.6}" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
        for y in geo["rotalar"][i]["yollar"]:
            o.append(f'<path d="{yol(y)}" fill="none" stroke="{renk}" stroke-width="{kalin}" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
    if kod_etiket:
        for i in idler:
            ys = geo["rotalar"][i]["yollar"]
            en = max(ys, key=len)
            a, b = P(*en[len(en) // 2])
            renk = (renkler or {}).get(i, "#f5821f")
            o.append(f'<g transform="translate({a:.1f},{b:.1f})"><rect x="-13" y="-9" width="26" height="18" rx="9" '
                     f'fill="{renk}" stroke="#fff" stroke-width="1.5"/><text y="4" text-anchor="middle" '
                     f'class="hk">{e(kod_etiket[i])}</text></g>')
    if etiket:
        for ad, la, lo in YERLER:
            a, b = P(lo, la)
            if 4 < a < w - 4 and 4 < b < h - 4:
                o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3.2" fill="#14150f" stroke="#fff" stroke-width="1.2"/>'
                         f'<text x="{a + 6:.1f}" y="{b - 5:.1f}" class="yer">{e(ad)}</text>')
    # ölçek çubuğu
    km = next(k for k in (1, 2, 5, 10, 20) if k * s > w * 0.14)
    o.append(f'<g transform="translate(16,{h - 18})"><rect width="{km * s:.1f}" height="5" fill="#14150f"/>'
             f'<rect width="{km * s / 2:.1f}" height="5" fill="#fff" stroke="#14150f" stroke-width=".8"/>'
             f'<text y="-6" class="olcek">{km} km</text></g>')
    o.append(f'<g transform="translate({w - 22},26)"><path d="M0,-14 L6,4 L0,0 L-6,4Z" fill="#14150f"/>'
             f'<text y="16" text-anchor="middle" class="olcek">K</text></g>')
    o.append("</svg>")
    return "".join(o)


def sema_svg(duraklar, w=520):
    """Geometrisi olmayan rota için metro tipi güzergah şeması (dikey)."""
    n = len(duraklar)
    h = max(160, 44 * n + 20)
    o = [f'<svg viewBox="0 0 {w} {h}" width="100%" class="sema">',
         f'<rect width="{w}" height="{h}" fill="var(--kagit)"/>',
         f'<line x1="40" y1="30" x2="40" y2="{30 + 44 * (n - 1)}" stroke="#f5821f" stroke-width="7" stroke-linecap="round"/>']
    for k, d in enumerate(duraklar):
        y = 30 + 44 * k
        uc = k in (0, n - 1)
        o.append(f'<circle cx="40" cy="{y}" r="{9 if uc else 6.5}" fill="{"#14150f" if uc else "#fff"}" '
                 f'stroke="#14150f" stroke-width="2.6"/>')
        o.append(f'<text x="64" y="{y + 5}" class="durak{" uc" if uc else ""}">{e(d[:70])}</text>')
    o.append("</svg>")
    return "".join(o)


# ---------- sayfalar ----------
def seviye(r):
    z = deger(r, "zorluk")
    return SEVIYE.get(z) if z else None


def zorluk_html(r):
    z = deger(r, "zorluk")
    sv = seviye(r)
    if sv:
        ek = ' <span class="kucuk">(kaynakta “Hard”)</span>' if z == "Hard" else ""
        return f'<span class="chip sv-{sv}">{SEVIYE_AD[sv]}</span>{ek}'
    if z:
        return '<span class="chip sv-yok">Seviye yok</span>'
    return '<span class="chip sv-yok">Bilgi yok</span>'


def stat(baslik, v, birim, ondalik=None):
    return (f'<div class="stat"><div class="sl">{baslik}</div><div class="sv">{sayi_tr(v, ondalik)}'
            f'{"<small> " + birim + "</small>" if v is not None else ""}</div></div>')


def rota_sayfa(r, k, geo, no, toplam):
    rid = r["id"]
    tip = TIP_AD.get(r["tip"], r["tip"]).replace("—", "Tip belirtilmemiş")
    z = deger(r, "zorluk")
    zor_not = f"<h3>Zorluk notu</h3><p class='kucuk'>{kes(z, 200)}</p>" if z and not seviye(r) else ""
    bas, bit = r["baslangic"], r["bitis"]
    yon = "" if bas == "bilinmiyor" else (f"{e(bas)} → {e(bit)}" if bit not in ("bilinmiyor", bas) else e(bas) + " çıkışlı")
    mes, tir, ini, rak = (deger(r, a) for a in ("mesafe_km", "tirmanis_m", "inis_m", "max_rakim_m"))
    egim = f"{sayi_tr(round(tir / mes, 1), 1)} m/km" if mes and tir else "—"
    if rid in geo["rotalar"]:
        gorsel = harita_svg(geo, [rid], 720, 560, kod_etiket=None)
        gorsel_not = "Harita: OpenStreetMap rota ilişkisi " + str(geo["rotalar"][rid]["relation"]) + " · © OpenStreetMap katkıcıları, ODbL"
    else:
        gorsel = sema_svg(r["guzergah"] or ["Güzergah bilgisi yok"], 460)
        gorsel_not = "Güzergah şeması: kaynakta geçen ara noktalar, ölçeksiz. Konum kaynağı: " + alan_adi(r.get("konum_kaynak"))
    duraklar = "".join(f"<li>{e(d)}</li>" for d in r["guzergah"]) or "<li>Kaynakta ara nokta yok</li>"
    gz = f'<h3>Güzergah</h3><ol class="durakl">{duraklar}</ol>' if rid in geo["rotalar"] else ""
    kis = r["kis_uygun"]
    uy = sorted(r["uyarilar"], key=lambda u: u.get("tarih") or u["metin"][:10], reverse=True)[:4]
    uyl = "".join(
        f'<li><b>{e(u.get("tarih") or "")}</b> {kes(u["metin"], 200)} '
        f'<span class="etiket g-{u.get("gecerli", "bilinmiyor")}">{GECERLI_AD.get(u.get("gecerli"), "güncelliği belirsiz")}</span></li>'
        for u in uy) or "<li>Kayıtlı olay yok.</li>"
    zemin = deger(r, "zemin")
    durum = r["durum"]
    durum_txt = {"acik": "Resmi sayfa: Açık", "kapali": "Kapalı", "bilinmiyor": "Resmi durum yok"}[durum["deger"]]
    kaynak = r.get("konum_kaynak") or ""
    return f"""
<section class="sayfa rota">
  <header class="rbas">
    <div class="kod">{e(k)}</div>
    <div><h2>{e(ad(r))}</h2><p class="alt">{e(tip)}{" · " + yon if yon else ""}</p></div>
    <div class="zor">{zorluk_html(r)}</div>
  </header>
  <div class="rgovde">
    <figure class="kart gorsel">{gorsel}<figcaption>{e(gorsel_not)}</figcaption></figure>
    <aside class="statlar">
      {stat("Mesafe", mes, "km")}
      {stat("Tırmanış", tir, "m")}
      {stat("İniş", ini, "m")}
      {stat("Maks. rakım", rak, "m")}
      <div class="stat"><div class="sl">Ort. tırmanış</div><div class="sv sm">{egim}</div></div>
      <div class="stat durum"><div class="sl">Kış (Ara–Şub)</div><div class="sv sm">{KIS_AD[kis["deger"]]}</div></div>
      <div class="stat durum"><div class="sl">Durum</div><div class="sv sm">{durum_txt}</div></div>
    </aside>
  </div>
  <div class="ikili">
    <div>{gz}
      {"<h3>Zemin</h3><p class='kucuk'>" + kes(zemin, 260) + "</p>" if zemin else ""}
      <h3>Kış notu</h3><p class="kucuk">{kes(kis["gerekce"], 320)}</p>{zor_not}</div>
    <div><h3>Son olaylar (en yeni 4)</h3><ul class="uyl">{uyl}</ul>
      <p class="kucuk not">{e(durum["not"])}</p></div>
  </div>
  <footer class="rayak">
    <div class="qr">{qr_svg(utm(rid))}</div>
    <div class="cta"><b>Rotaya hazırlık:</b> bisiklet bakımı, iç lastik, matara, ışık ve kask NITRO Bisiklet'te.
      <span>nitrobisiklet.com · Köyceğiz</span>
      <span class="kucuk">Kaynak: {e(alan_adi(kaynak))} · Veri kontrolü: {e(durum["kontrol"])}</span></div>
    <div class="no">{no}/{toplam}</div>
  </footer>
</section>"""


def kapak(veri, geo, kodlar, renkler):
    osm = [r["id"] for r in veri["rotalar"] if r["id"] in geo["rotalar"]]
    harita = harita_svg(geo, osm, 760, 640, renkler=renkler, kalin=2.6, kod_etiket=kodlar)
    toplam_km = sum(deger(r, "mesafe_km") or 0 for r in veri["rotalar"])
    return f"""
<section class="sayfa kapak">
  <div class="kust"><img src="../logo.png" class="logo" alt="NITRO"><span>Köyceğiz · Ortaca · Dalyan</span></div>
  <h1>Bisiklet<br>Rota Rehberi</h1>
  <p class="kalt">{len(veri["rotalar"])} rota · toplam {sayi_tr(round(toplam_km, 1), 1)} km · kaynaklı veri, {e(veri["guncelleme"])}</p>
  <div class="kart kharita">{harita}</div>
  <p class="katif">Harita: © OpenStreetMap katkıcıları, ODbL. K ve O kodları resmi işaretli rota numaralarıdır; D kodlarını bu rehber topluluk kayıtları için verdi.</p>
</section>"""


def ozet(veri, kodlar):
    satir = []
    for r in veri["rotalar"]:
        sv = seviye(r)
        z = f'<span class="chip sv-{sv}">{SEVIYE_AD[sv]}</span>' if sv else '<span class="chip sv-yok">—</span>'
        mes, tir, rak = deger(r, "mesafe_km"), deger(r, "tirmanis_m"), deger(r, "max_rakim_m")
        satir.append(f"<tr><td><b>{e(kodlar[r['id']])}</b></td><td>{e(ad(r))}</td><td>{e(TIP_AD[r['tip']])}</td>"
                     f"<td class='s'>{sayi_tr(mes)}</td><td class='s'>{sayi_tr(tir)}</td><td class='s'>{sayi_tr(rak)}</td>"
                     f"<td>{z}</td><td>{e(KIS_AD[r['kis_uygun']['deger']])}</td></tr>")
    olcu = max(deger(r, "tirmanis_m") or 0 for r in veri["rotalar"])
    cubuk = "".join(
        f'<div class="cub"><span class="ck">{e(kodlar[r["id"]])}</span><div class="cb"><i style="width:{(deger(r, "tirmanis_m") or 0) / olcu * 100:.1f}%"></i></div>'
        f'<span class="cv">{sayi_tr(deger(r, "tirmanis_m"))}{" m" if deger(r, "tirmanis_m") else ""}</span></div>'
        for r in sorted(veri["rotalar"], key=lambda r: -(deger(r, "tirmanis_m") or -1)))
    return f"""
<section class="sayfa ozet">
  <h2 class="bolum">Rotalar bir bakışta</h2>
  <table class="tablo"><thead><tr><th>Kod</th><th>Rota</th><th>Tip</th><th class='s'>km</th><th class='s'>Tırm. m</th>
  <th class='s'>Maks. m</th><th>Seviye</th><th>Kış</th></tr></thead><tbody>{"".join(satir)}</tbody></table>
  <h3>Toplam tırmanışa göre sıralama</h3><div class="cubuklar">{cubuk}</div>
  <div class="bilgi"><b>Bu rehber nasıl okunur?</b> Sayılar resmi rota sayfaları, OpenStreetMap ve GPS kayıtlarından alındı; her rota sayfasının
  altında kaynak adresi var. “Resmi sayfa: Açık” ifadesi o sayfanın yazdığıdır, bugünkü yol durumunu garanti etmez.
  D kodlu rotalar resmi işaretli değildir; topluluk kayıtlarından derlenmiştir. Çıkmadan önce hava, yol ve feribot durumunu kontrol edin.</div>
</section>"""


def plan_sayfalari():
    return """
<section class="sayfa plan">
  <h2 class="bolum">1 · Sisteme dahil etme</h2>
  <div class="akis">
    <div><b>Veri</b><span>data/rotalar.json<br>15 rota, kaynaklı</span></div><i>→</i>
    <div><b>Doğrulama</b><span>scripts/rotalar.py<br>0 bulgu şartı</span></div><i>→</i>
    <div><b>Üretim</b><span>scripts/rota_pdf.py<br>harita + PDF</span></div><i>→</i>
    <div><b>Yayın</b><span>site · Instagram<br>story · Google profili</span></div>
  </div>
  <ol class="adimlar">
    <li><b>Tek kaynak.</b> Bütün sayılar yalnız <code>data/rotalar.json</code>'dan okunur. PDF, site metni ve
      Instagram görseli aynı dosyadan üretildiği için iki yerde farklı sayı çıkmaz.</li>
    <li><b>Doğrulama kapısı.</b> Her yayından önce <code>python3 scripts/rotalar.py --tarih GG</code> çalışır. Bulgu varsa
      paylaşım durur. Durum kontrolü 30 günden eskiyse rota “seçilemez” olur ve paylaşılmaz.</li>
    <li><b>Yeniden üretim.</b> Veri değişince <code>python3 scripts/rota_pdf.py</code> PDF'i yeniler. Geometri
      <code>--geo-indir</code> ile OpenStreetMap'ten tazelenir. Haritalarda OSM atfı zorunludur ve otomatik basılır.</li>
    <li><b>İçerik otomasyonu (sonraki adım).</b> <code>content.py</code>'ye “rota” teması eklenir. <code>render.py</code>
      bu PDF'teki harita çizimini kullanarak 1080×1350 carousel kareleri üretir. Yayın, mevcut kurallarla
      <code>publish.py</code>'den geçer: her post aynı gün bir kez story olur, link tıklanabilir sticker'dır, UTM'lidir.</li>
    <li><b>Kış filtresi.</b> Aralık–Şubat'ta yalnız düşük rakımlı rotalar öne çıkar (K1, K2, O3, O4, D1, D2).
      K5 ve D5 (1.800 m üstü) kar haberleri nedeniyle kışın paylaşılmaz; ilkbaharda açılır.</li>
  </ol>
  <h2 class="bolum">2 · Siteye dahil etme (ikas)</h2>
  <ol class="adimlar">
    <li><b>“Rotalar” sayfası.</b> ikas panelinde yeni sayfa ya da blog yazısı: giriş metni, genel harita, 15 rota kartı,
      “Rehberi indir (PDF)” düğmesi. Ana menüye ve Instagram bio linkine eklenir.</li>
    <li><b>Her rotaya ayrı yazı.</b> Örnek adres: <code>/blog/k2-sigla-bisiklet-rotasi</code>. İçerik: harita görseli, sayı kutuları,
      güzergah, kış notu, kaynak linki ve “Bu rotaya uygun bisiklet” bölümü. Bölüm Şehir Bisikleti ve
      Dağ Bisikleti kategorilerine bağlanır, ayrıca iç lastik, matara ve ışık ürünlerine.</li>
    <li><b>SEO.</b> Başlık kalıbı: “K2 Sığla Rotası: 32 km Köyceğiz bisiklet rotası | NITRO Bisiklet”. Meta açıklamada
      mesafe, tırmanış ve başlangıç noktası yer alır. Sayfalar Google İşletme Profili gönderilerinden link alır.</li>
    <li><b>PDF'in yeri.</b> Dosya ikas'a yüklenebilir. Ya da otomatik güncellenen kopya kullanılır:
      <code>erguderdemir.github.io/nitro-instagram/rotalar/NITRO-Rota-Rehberi.pdf</code>.</li>
    <li><b>Ölçüm.</b> Bütün linkler UTM'lidir: <code>utm_campaign=rotalar</code>, <code>utm_content=&lt;rota-id&gt;</code>.
      GA4'te hangi rotanın siteye, hangi ürüne trafik getirdiği görülür. PDF'teki QR kodlar
      <code>utm_source=pdf</code> taşır.</li>
    <li><b>Kim yapar?</b> Sayfa metinlerini ve görselleri Claude hazırlar. ikas panelinde yayınlamak Barış'ın ya da geliştiricinin işidir.
      Panel erişimi verilirse Claude da yapabilir.</li>
  </ol>
</section>
<section class="sayfa plan">
  <h2 class="bolum">3 · Sosyal medyada paylaşım</h2>
  <div class="formatlar">
    <div class="fkart"><b>Carousel · 5 kare</b><ol><li>Kapak: harita + rota adı + km</li><li>Sayılar: mesafe, tırmanış, rakım, seviye</li>
      <li>Güzergah şeması (durak durak)</li><li>Dikkat: kış notu, feribot ve yol durumu</li><li>CTA: “Rotaya hazır mısın?” + kaydet/paylaş</li></ol></div>
    <div class="fkart"><b>Story · aynı gün, tek kez</b><ol><li>Postun story paylaşımı</li><li>Tıklanabilir link sticker'ı rota sayfasına gider (UTM'li)</li>
      <li>Anket: “Bu rotayı sürdün mü?”</li><li>Story “ROTALAR” öne çıkanına eklenir</li></ol></div>
    <div class="fkart"><b>Google profili</b><ol><li>Haftanın rotası gönderisi</li><li>“Daha fazla bilgi” düğmesi rota sayfasına gider</li>
      <li>Harita görseli + 1 cümle özet</li></ol></div>
  </div>
  <h3>Takvim önerisi (Aralık 2026, Perşembe akşamı, hafta sonu öncesi)</h3>
  <table class="tablo kucuk"><thead><tr><th>Tarih</th><th>Rota</th><th>Neden</th></tr></thead><tbody>
    <tr><td>3 Aralık</td><td>D1 Köyceğiz – Eski Köyceğiz</td><td>Wikiloc kaydı NITRO Bisiklet'ten başlıyor; en düşük rakım (54 m)</td></tr>
    <tr><td>10 Aralık</td><td>K2 Sığla</td><td>Kolay, 32 km, K rotalarının en az tırmanışlısı (304 m)</td></tr>
    <tr><td>17 Aralık</td><td>O3 Kaya Mezarları</td><td>Kolay, Dalyan çıkışlı, kış koşullu</td></tr>
    <tr><td>24 Aralık</td><td>K1 Köyceğiz Gölü</td><td>Gölün çevresi, feribot geçişli klasik</td></tr>
    <tr><td>31 Aralık</td><td>Rehberin tamamı (PDF)</td><td>Yeni yıl hedefi: “2027'de 15 rota”</td></tr>
  </tbody></table>
  <p class="kucuk">Takvim mevcut planla çakışma kontrolünden sonra kesinleşir. Her paylaşımdan önce rotanın durumu yeniden kontrol edilir.</p>
  <h3>Örnek açıklama (K2)</h3>
  <div class="ornek">K2 Sığla Rotası: Köyceğiz merkezden çıkıp merkeze dönen 32 km'lik kolay bir halka. Toplam tırmanış 304 m, en yüksek nokta 78 m.
  Kışın koşullu: yağışlı günlerin ardından göl kenarındaki yolları kontrol et. 📍 Köyceğiz · Rota sayfası ve PDF rehber profildeki linkte. Kaydet, hafta sonu sür. 🚲
  <br><span class="kucuk">#köyceğiz #bisikletrotası #muğla #nitrobisiklet</span></div>
  <h3>Kurallar</h3>
  <ul class="kurallar">
    <li>Güncel teyit yoksa “açık” denmez. Paylaşımda “çıkmadan önce kontrol et” notu yer alır.</li>
    <li>Fiyat, stok ve indirim iddiası yalnız doğrulanmış veriyle yazılır. Sahte aciliyet kullanılmaz.</li>
    <li>OSM haritası kullanılan her görselde “© OpenStreetMap katkıcıları” yazar.</li>
    <li>Takipçi fotoğrafları yalnız izinle paylaşılır. Önerilen etiket: #nitrorota</li>
    <li>Başarı ölçüsü: kaydetme, paylaşım, link tıklaması (GA4, utm_campaign=rotalar) ve rota sayfasından ürün ziyareti.</li>
  </ul>
</section>"""


CSS = """
@import url('../fonts/fonts.css');
@page{size:A4;margin:0}
*{box-sizing:border-box}
:root{--bg:#f1ede2;--fg:#14150f;--mut:#6b6658;--acc:#f5821f;--em:#dd6410;--soft:#e3dccb;--ol:#2a3220;--kagit:#f7f4ec}
body{margin:0;font-family:Barlow,sans-serif;color:var(--fg);background:var(--bg);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.sayfa{width:210mm;height:297mm;padding:14mm 14mm 12mm;position:relative;overflow:hidden;page-break-after:always;background:var(--bg)}
h1,h2,h3{font-family:Archivo,sans-serif;margin:0}
h3{font-size:10.5pt;text-transform:uppercase;letter-spacing:.06em;color:var(--em);margin:10px 0 5px}
code{font-family:'Space Mono',monospace;font-size:8pt;background:var(--soft);padding:1px 4px;border-radius:3px}
.kucuk{font-size:8.2pt;color:var(--mut);line-height:1.35}
.kart{background:var(--kagit);border-radius:14px;overflow:hidden;border:1px solid rgba(20,21,15,.12)}
.harita text.yer{font:600 13px Barlow;fill:#14150f;paint-order:stroke;stroke:#f7f4ec;stroke-width:4px}
.harita text.olcek{font:700 11px 'Space Mono';fill:#14150f}
.harita text.hk{font:800 10px Archivo;fill:#fff}
.sema text.durak{font:500 15px Barlow;fill:#14150f}.sema text.uc{font-weight:700}
/* kapak */
.kapak{background:var(--ol);color:var(--bg);padding:16mm}
.kust{display:flex;justify-content:space-between;align-items:center;font:600 10pt Barlow;letter-spacing:.12em;text-transform:uppercase;color:#a8b78a}
.logo{height:16mm;background:#f1ede2;border-radius:12px;padding:6px 12px}
.kapak h1{font-size:54pt;line-height:.95;margin:14mm 0 4mm;letter-spacing:-.02em}
.kapak h1::after{content:"";display:block;width:34mm;height:5px;background:var(--acc);margin-top:6mm}
.kalt{font:500 12pt Barlow;color:#d9d4c4;margin:0 0 7mm}
.kharita{border:none}
.katif{font-size:8pt;color:#a8b78a;margin-top:4mm}
/* özet */
.bolum{font-size:22pt;margin-bottom:6mm;padding-bottom:3mm;border-bottom:3px solid var(--acc)}
.tablo{width:100%;border-collapse:collapse;font-size:8.6pt}
.tablo th{text-align:left;white-space:nowrap;font:700 7.5pt Archivo;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);border-bottom:1.5px solid var(--fg);padding:4px 5px}
.tablo td{padding:4.3px 5px;border-bottom:1px solid rgba(20,21,15,.12);vertical-align:middle}
.tablo td.s{text-align:right;font-family:'Space Mono',monospace;font-size:8pt}.tablo th.s{text-align:right}
.chip{display:inline-block;font:700 7.5pt Archivo;text-transform:uppercase;letter-spacing:.05em;padding:2px 8px;border-radius:20px}
.sv-kolay{background:#6b8a3a;color:#fff}.sv-orta{background:var(--acc);color:#14150f}.sv-zor{background:#b23c12;color:#fff}
.sv-cokzor{background:#14150f;color:#fff}.sv-yok{background:var(--soft);color:var(--mut)}
.cubuklar{display:grid;gap:3px}
.cub{display:grid;grid-template-columns:9mm 1fr 18mm;align-items:center;gap:6px;font-size:8pt}
.ck{font:800 8pt Archivo}.cv{font-family:'Space Mono';font-size:7.5pt;text-align:right}
.cb{height:8px;background:var(--soft);border-radius:4px;overflow:hidden}.cb i{display:block;height:100%;background:var(--acc)}
.bilgi{margin-top:6mm;background:var(--kagit);border-left:4px solid var(--acc);padding:4mm 5mm;font-size:8.6pt;line-height:1.45;border-radius:6px}
/* rota */
.rbas{display:grid;grid-template-columns:auto 1fr auto;gap:5mm;align-items:center;margin-bottom:5mm}
.kod{background:var(--acc);color:#14150f;font:900 22pt Archivo;width:22mm;height:22mm;border-radius:50%;display:grid;place-items:center}
.rbas h2{font-size:17pt;line-height:1.1}.alt{margin:2px 0 0;color:var(--mut);font-size:10pt}
.rgovde{display:grid;grid-template-columns:1fr 46mm;gap:4mm}
.gorsel{margin:0}.gorsel svg{display:block}
figcaption{font-size:7pt;color:var(--mut);padding:4px 8px 6px}
.statlar{display:grid;gap:2.4mm;align-content:start}
.stat{background:var(--ol);color:var(--bg);border-radius:10px;padding:2.4mm 3.4mm}
.stat.durum{background:var(--soft);color:var(--fg)}
.sl{font:700 6.8pt Archivo;text-transform:uppercase;letter-spacing:.08em;opacity:.75}
.sv{font:800 17pt Archivo;line-height:1.15}.sv small{font-size:9pt;font-weight:600}.sv.sm{font-size:10pt;font-weight:700}
.ikili{display:grid;grid-template-columns:1fr 1fr;gap:6mm;margin-top:2mm}
.durakl{margin:0;padding-left:16px;font-size:8.6pt;line-height:1.4;columns:1}
.durakl li::marker{color:var(--acc);font-weight:700}
.uyl{margin:0;padding-left:14px;font-size:8.2pt;line-height:1.38}.uyl li{margin-bottom:3px}
.etiket{font:700 6.6pt Archivo;text-transform:uppercase;padding:1px 5px;border-radius:8px;background:var(--soft);color:var(--mut);white-space:nowrap}
.g-evet{background:#b23c12;color:#fff}
.not{border-top:1px dashed rgba(20,21,15,.25);padding-top:3px;margin-top:6px}
.rayak{position:absolute;left:14mm;right:14mm;bottom:10mm;display:grid;grid-template-columns:24mm 1fr auto;gap:5mm;align-items:center;
  border-top:2px solid var(--fg);padding-top:3mm}
.cta{font-size:8.6pt;line-height:1.4}.cta span{display:block}
.no{font:800 11pt Archivo;color:var(--mut)}
/* plan */
.akis{display:flex;align-items:center;gap:3mm;margin-bottom:5mm}
.akis div{flex:1;background:var(--ol);color:var(--bg);border-radius:10px;padding:3mm;font-size:8pt}
.akis div b{display:block;font:800 10pt Archivo;color:var(--acc)}.akis i{font-style:normal;font-weight:800;color:var(--acc)}
.adimlar{padding-left:18px;font-size:9pt;line-height:1.45;margin:0 0 5mm}.adimlar li{margin-bottom:2.2mm}
.adimlar li::marker{font-weight:800;color:var(--em)}
.formatlar{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm;margin-bottom:3mm}
.fkart{background:var(--kagit);border-radius:12px;padding:4mm;border-top:4px solid var(--acc);font-size:8.4pt}
.fkart b{font:800 10pt Archivo}.fkart ol{padding-left:15px;margin:2mm 0 0;line-height:1.4}
.ornek{background:var(--ol);color:var(--bg);border-radius:12px;padding:4mm 5mm;font-size:9pt;line-height:1.5}
.ornek .kucuk{color:#a8b78a}
.kurallar{font-size:8.8pt;line-height:1.45;padding-left:16px;margin:0}
"""


def uret():
    veri = json.loads(VERI.read_text(encoding="utf-8"))
    bulgu = rotalar.dogrula(veri) if hasattr(rotalar, "dogrula") else []
    if bulgu:
        sys.exit(f"rotalar.json doğrulanmadı: {bulgu[:3]}")
    geo = json.loads(GEO.read_text(encoding="utf-8"))
    sira = [i for i in SIRA_KOD] + DIGER_SIRA
    rmap = {r["id"]: r for r in veri["rotalar"]}
    eksik = set(rmap) - set(sira)
    if eksik:
        sys.exit(f"sıraya eklenmemiş rota: {eksik}")
    veri["rotalar"] = [rmap[i] for i in sira if i in rmap]
    kodlar, d = {}, 0
    for r in veri["rotalar"]:
        if r["id"] not in SIRA_KOD:
            d += 1
        kodlar[r["id"]] = kod(r, d)
    renkler = {i: RENK[k % len(RENK)] for k, i in enumerate(i for i in SIRA_KOD if i in geo["rotalar"])}
    toplam = len(veri["rotalar"]) + 4
    sayfalar = [kapak(veri, geo, kodlar, renkler), ozet(veri, kodlar)]
    sayfalar += [rota_sayfa(r, kodlar[r["id"]], geo, k + 3, toplam) for k, r in enumerate(veri["rotalar"])]
    sayfalar.append(plan_sayfalari())
    CIKTI.mkdir(parents=True, exist_ok=True)
    h = (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>NITRO Bisiklet · Rota Rehberi</title>'
         f'<style>{CSS}</style></head><body>{"".join(sayfalar)}</body></html>')
    (CIKTI / HTML_AD).write_text(h, encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    f"--print-to-pdf={CIKTI / PDF_AD}", (CIKTI / HTML_AD).as_uri()],
                   check=True, capture_output=True, timeout=180)
    print("PDF:", CIKTI / PDF_AD)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--geo-indir", action="store_true")
    a = ap.parse_args()
    if a.geo_indir:
        geo_indir()
    else:
        uret()
