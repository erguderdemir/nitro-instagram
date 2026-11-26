#!/usr/bin/env python3
"""İçerik kuralları: ürün alt türleri, başlık havuzları, açıklama metni, alt metin, UTM, listeler, mevsim süzgeci.

Temel ilke: her başlık yalnızca kuralına uyan ürüne yazılır. Ürün önce kategorisine, sonra adındaki
anahtar kelimeye göre bir KURALA bağlanır (`rule_of`); kuralı olmayan ürün içerik olmaz. Liste
başlıklarındaki adet ve fiyat eşiği seçilen ürünlerden hesaplanır (`list_title`), `denetim.py` aynı
işlevlerle yeniden hesaplayıp karşılaştırır.

Metinler yalnız data/products.json ve data/site.json gerçeklerine dayanır: uydurma indirim, kampanya,
stok ya da süre iddiası üretilmez. Görsellere giden metinde emoji yoktur; İngilizce sözcük ve marka
adı CSS'in Türkçe büyük harf kuralına takılmasın diye büyük harfle yazılır ("NITRO").
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urlencode

from common import fmt_price

# ---- Gruplar (rapor ve etiketler için; kategori -> grup) ---------------------------------------

GROUPS = {
    "bisiklet_performans": ["Dağ Bisikleti", "Gravel", "Elektrikli Bisiklet", "BMX/Dirtjump"],
    "bisiklet_gunluk": ["Şehir Bisikleti", "Çocuk Bisikleti", "2. El Bisiklet"],
    "parca": ["Vites Grubu", "Fren Grubu", "Jant Grubu", "Dış Lastik", "İç Lastik", "Lastik", "Disk Fren Rotorları",
              "Balatalar & Pabuçlar", "Fren Setleri", "Fren Kolları", "Amortisör", "Gidon Grubu", "Kadro ve Kulak",
              "Sele Grubu", "Pedal ve Kal", "Elcik Sargı Barend", "Elektronik Yedek Parça"],
    "aksesuar": ["Çanta ve Sepet", "Zil, Korna, Ayna", "Matara ve Kafes", "Çamurluk ve Muhafaza", "Park Ayağı ve Sehpa",
                 "Sele ve Kılıf", "Telefon Tutucu", "Km Saati", "Pompa", "Aydınlatma ve Reflektör", "Kilit", "Aksesuar",
                 "Taşıyıcı ve Bagaj", "Kimyasal", "Atölye ve Tamir", "Anahtar ve Alet", "Outlet"],
    "giyim": ["Eldiven", "Kask", "Gözlük", "Bandana", "Forma", "Pantolon"],
}
BIKE_CATS = ("Dağ Bisikleti", "Gravel", "Elektrikli Bisiklet", "BMX/Dirtjump", "Şehir Bisikleti", "Çocuk Bisikleti",
             "2. El Bisiklet")
# Görseldeki kategori etiketi CSS ile büyütülür; Türkçe kuralın bozacağı adlar hazır büyük harfle verilir
CAT_LABEL = {"BMX/Dirtjump": "BMX / DIRT JUMP", "Outlet": "OUTLET", "Elcik Sargı Barend": "Elcik · Sargı · Bar ucu"}

KIS_AYLARI = (11, 12, 1, 2)
YAZ_AYLARI = (5, 6, 7, 8, 9)


def group_of(cat: str | None) -> str:
    for g, cats in GROUPS.items():
        if cat in cats:
            return g
    return "aksesuar"


def cat_label(cat: str | None) -> str:
    return CAT_LABEL.get(cat or "", cat or "")


# ---- Türkçe ad düzeni --------------------------------------------------------------------------

TR_LOWER = str.maketrans("Iİ", "ıi")
TR_UPPER = str.maketrans("ıi", "Iİ")
KEEP_UPPER = {"MTB", "BMX", "USB", "LED", "LM", "XS", "S", "M", "L", "XL", "XXL", "DH", "XC", "CNC", "MTX", "TRX", "XLC",
              "CX", "TL", "PC", "FV", "AV", "SV", "OEM", "NS", "KNT", "TW", "CST", "RKS", "UGR", "WRC", "HD", "GRX", "KDX",
              "CRX", "II", "AS", "DIA", "UNIX", "FOX", "VELO", "ARWIC", "OLD", "PVC", "QR", "BCD", "NITRO"}
# Büyük harfle yazılmış adlarda I harfi: Türkçe sözcükte "ı", yabancı sözcükte "i" olur
FOREIGN_I = {"ACTIVE", "BRIVIGA", "CLASSIC", "CRUISER", "HELIX", "LINE", "LITE", "QUICK", "RAINBOW", "SHIMANO",
             "RELEASE", "PREMIUM", "LINKGLIDE", "BIKE", "CITY", "TRAIL", "DIRT", "LIGHT", "MINI", "PRIME", "SPRINT",
             "MAXXIS", "AIR", "ASSIZE", "BITE", "CENTERLINE", "CLARIS", "DIFFUSION", "DISC", "HYDRAULIC", "INTEGRAL",
             "LAPIERRE", "LITHIUM", "ORTLIEB", "RAPID", "RIM", "RODI", "SHIFTER", "SINGLE", "SUSPENSION", "TRIGGER",
             "TRIX", "VIVO", "WELDING", "BISIKLET"}
# Sitedeki yazım hataları (Türkçe küçük harfe çevrilmiş yabancı adlar)
FIXES = (("Shımano", "Shimano"), ("SHİMANO", "SHIMANO"), ("Premıum", "Premium"), ("Iç Lastik", "İç Lastik"), ("Gıneyea", "Gineyea"), ("Slikon", "Silikon"), ("Solusyonsuz", "Solüsyonsuz"),
         ("Bisiklet&Kayak&Cross", "Bisiklet & Kayak & Cross"), ("Orjinal", "Orijinal"), ("ORJİNAL", "ORİJİNAL"),
         ("Cable Lock", "Kablo Kilidi"), ('700"x', "700x"), ("Malzeme Plastik olduğu için", "Malzemesi plastik olduğu için"),
         ("Maxxıs", "Maxxis"), ("Rockshox", "RockShox"), ("ZİL 070 - Kırmızı - Zır Zır", "Zır Zır Zil 070 Kırmızı"),
         ("Bisiklet Zili Pembe Kalp Desenli Çocuk Bisiklet Zili", "Pembe Kalp Desenli Çocuk Bisiklet Zili"))
# Biçim düzeltmeleri: birim boşluğu/küçük harf, ölçü çarpısı, parantez boşlukları, sayı ekleri, tamlama
FORMATS = ((r"(\d+(?:[.,]\d+)?)\s*(?:mm|MM|Mm)\b", r"\1 mm"), (r"(\d+(?:[.,]\d+)?)\s*(?:ml|ML|Ml)\b", r"\1 ml"),
           (r"(\d+(?:[.,]\d+)?)\s*(?:PSI|Psi|PSİ)\b", r"\1 psi"), (r"(\d)X(\d)", r"\1x\2"),
           (r"\(\s+", "("), (r"\s+\)", ")"), (r"\s+°", "°"),
           (r"\b(\d+) (?:Lü|LÜ)\b", r"\1'lü"), (r"\b(\d+) (?:Li|Lİ)\b", r"\1'li"), (r"\b(\d+) (?:Lu|LU)\b", r"\1'lu"),
           (r"\b(\d+) (?:Lı|LI)\b", r"\1'lı"), (r"\b(\d{2}) (\d{2}) Jant\b", r"\1-\2 Jant"),
           (r"\b(Dağ|Şehir|Yol|Çocuk) Bisiklet\b(?! Kask| Zil| Eldiven| Sele)", r"\1 Bisikleti"),
           (r"\b([a-z]{2,3}-[a-z]{1,3}\d{3,}[a-z]?)\b", lambda m: m.group(1).upper()))
COLORS = {"siyah", "beyaz", "kırmızı", "mavi", "yeşil", "gri", "sarı", "turuncu", "mor", "pembe", "lacivert",
          "mat", "parlak", "renkli", "antrasit", "bordo", "kahverengi", "füme", "haki", "krom", "gümüş", "gold",
          "krem", "metalik", "koyu", "açık", "bebek", "çağla", "yeşili", "mavisi", "pudra", "oilsick", "neon",
          "bronz", "lime", "manyetik", "mercan", "rengi", "candy", "ocean", "kutusuz", "sağ", "sol", "ön", "arka"}
SIZES = {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}


def tr_lower(s: str) -> str:
    return s.translate(TR_LOWER).lower()


def _title_word(w: str) -> str:
    if not w or w in KEEP_UPPER or any(ch.isdigit() for ch in w) or not w.isupper():
        return w
    if "-" in w and len(w) > 1:
        return "-".join(_title_word(x) for x in w.split("-"))
    core = w.strip("[]()'\".,:;")
    if core in KEEP_UPPER:
        return w
    low = w.lower() if core in FOREIGN_I else w.translate(TR_LOWER).lower()
    for i, ch in enumerate(low):  # ilk harfi büyüt (parantez/köşeli ayraç atlanır)
        if ch.isalpha():
            up = ch.upper() if core in FOREIGN_I else ch.translate(TR_UPPER).upper()
            return low[:i] + up + low[i + 1:]
    return low


def fix_text(s: str) -> str:
    for a, b in FIXES:
        s = s.replace(a, b)
    for a, b in FORMATS:
        s = re.sub(a, b, s)
    return s


def display_name(p: dict) -> str:
    """Ürün adı: stok kodları atılır, tümü büyük harfli adlar Türkçe başlık düzenine çevrilir, marka NITRO yazılır."""
    n = (p.get("name") or "").split("|")[0]
    n = re.sub(r"\s+\d{7,}(\.\d+)?(\s.*)?$", "", n)          # sondaki stok kodu ve arkasındaki paket notu
    n = re.sub(r"\s+A\d{5}$", "", n)
    n = re.sub(r"\s*/\s*1 ADET FİYAT\w*\s*$", "", n)
    n = re.sub(r"\s{2,}", " ", n).strip(" ,-–")
    letters = [ch for ch in n if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        n = " ".join(_title_word(w) for w in n.split(" "))
    n = fix_text(n)
    return re.sub(r"\b[Nn][iıİI][Tt][Rr][Oo]\b", "NITRO", n)


_STOP = re.compile(r"^(enduro|dağ|şehir|kadın|çocuk|elektrikli|katlanır|trekking|gravel|jant|dirt|bmx|bisiklet\w*|"
                   r"city|\d+x\d+|\d+-v|vites|çift|hidrolik)$")


def short_name(p: dict) -> str:
    """Bisikletlerde görsele giden kısa ad: marka + model (+ jant). Diğer ürünlerde tam ad."""
    full = display_name(p)
    if p.get("category") not in BIKE_CATS or p.get("category") == "2. El Bisiklet":
        return full
    out = []
    for i, w in enumerate(full.split(" ")):
        if i >= 2 and _STOP.match(tr_lower(w.strip(",()"))):
            break
        out.append(w)
    s = " ".join(out).strip(" ,-")
    return s if len(out) >= 2 and len(s) >= 8 else full


def family(p: dict) -> str:
    """Renk/beden varyantlarını aynı aileye toplar (aynı ürünün renkleri ayrı ürün sayılmasın)."""
    if p.get("category") in BIKE_CATS and p.get("category") != "2. El Bisiklet":
        return tr_lower(short_name(p))
    n = re.sub(r"\b\d+([.,]\d+)?\s*(\"|”|mm\b|cm\b|lü\b|li\b)", " ", display_name(p), flags=re.I)  # ölçü varyantı
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ.]+", tr_lower(n))
    words = [w for w in words if w not in COLORS and w not in SIZES]
    return " ".join(words[:4]) or p["slug"]


def pick(options: list, *seed):
    h = int(hashlib.md5("|".join(map(str, seed)).encode()).hexdigest(), 16)
    return options[h % len(options)]


def plain(s: str) -> str:
    """Başlıktaki <em> vurgusunu at."""
    return s.replace("<em>", "").replace("</em>", "")


# ---- Hariç tutulanlar ----------------------------------------------------------------------------
# Scooter / motosiklet / otomobil ürünleri ve yedek parça tokası bisiklet içeriğine girmez.
HARIC = re.compile(r"scooter|motosiklet|motor kilidi|jump starter|akü|kompresör|otomobil|onvo|xiaomi|scoowy|"
                   r"ortlieb e227|xbyc blt|balata xbyc|hediyeli")   # "hediyeli": addaki kampanya iddiası yinelenmez


# Fotoğrafı ürünü yanlış gösteren ya da başka sitenin filigranını taşıyan ürünler içeriğe girmez.
HARIC_SLUG = (
    "carraro-sportive-225-28-jant-24-vites-hidrolik-disk-sehir-bisikleti-46cm-mat-ant",  # adı antrasit, fotoğrafları mavi
    "tanke-tk6-29-enduro-dag-bisikleti",   # fotoğraflarda sahibinden.com filigranı
    # Tek/tüm görseli ürünle çelişen ya da paylaşılamaz ürünler (site görseli düzelince çıkarılabilir)
    "maya-m410-zincir",                    # kutuda X410 yazıyor
    "wake-wk-rt01-160-mm-6-vidali-disk-fren-rotoru",   # tek görsel ölçü çizimi
    "i-love-my-bike-zil-mavi",             # adı mavi, fotoğrafta 7 renk
    "zil-070-kirmizi-zir-zir",             # adı kırmızı, fotoğrafta 4 renk
    "bisiklet-zili-pembe-kalp-desenli",    # elde çekilmiş amatör fotoğraf
    "asistan-cape-gl-200-kisa-parmak-eldiven-gri",   # adı gri, fotoğrafta siyah eldiven
    "404-balata-spreyi-metal-temizleyici",  # açılır pencere ekran görüntüsü (X simgesi)
    "i-love-my-bike-zil-kirmizi",          # fotoğrafta 7 renk zil
    "sarissa-elektrikli-bisiklet-uyumlu-kadro-baglantili-cocuk-koltugu-siyah-kirmizi",  # fotoğraf siyah-sarı
    "far-helix-lite-w-150-lm",             # İngilizce pazarlama bandı
    "far-helix-pro-w-250-lm",              # İngilizce pazarlama bandı
    "shimano-deore-xt-sm-rt76-203-mm",     # fotoğraftaki rotor 180 mm
    "vona-1928-comfort-sele",              # fotoğrafta başka marka sele
    "asistan-drox-gr170-bisiklet-elcigi",  # görsellerde yapay zekâ filigranı
    "matara-kafesi-bcg-323",               # İngilizce "Extendable" yazısı
)


def excluded(p: dict) -> bool:
    return bool(HARIC.search(tr_lower(p.get("name") or ""))) or (p.get("slug") or "").startswith(HARIC_SLUG)


# ---- Kurallar: (kategori + ad anahtar kelimesi) -> alt tür ve o alt türe uyan başlık havuzu --------
# heads: (başlık, aylar | None). Başlık kuralın TÜM ürünleri için doğru olmalıdır.
# İlk eşleşen kural geçerlidir; sıra önemlidir (özel olan önce).

def _r(id, label, cats, heads, hooks, q, tags, inc=None, exc=None):
    return {"id": id, "label": label, "cats": set(cats), "inc": re.compile(inc) if inc else None,
            "exc": re.compile(exc) if exc else None, "heads": [h if isinstance(h, tuple) else (h, None) for h in heads],
            "hooks": hooks, "q": q, "tags": tags}


KIS = KIS_AYLARI
RULES = [
    # --- Bisikletler
    _r("ikinciel", "Kontrollü 2. el", ["2. El Bisiklet"],
       ["Kontrollü <em>2. el</em>", "Elden geçti, <em>yola hazır</em>"],
       ["Kontrollü 2. el: atölyemizin elinden geçti, yeni sahibini bekliyor.",
        "Sıfır şart değil; atölyede elden geçti, yola hazır."],
       "Senin ilk bisikletin sıfır mıydı, 2. el mi?", ["#ikincielbisiklet", "#bisikletsevenler"]),
    _r("ebike", "Elektrikli bisiklet", ["Elektrikli Bisiklet"],
       ["Pedalına <em>güç kat</em>", "Elektrik <em>desteğiyle</em> sür", "Daha uzağa, <em>daha rahat</em>", "Yokuşlar <em>dert olmasın</em>"],
       ["Pedalı sen çevir, desteği motor versin.", "Yokuş da rüzgâr da artık bahane değil.",
        "Elektrik desteğiyle rotanı uzat."],
       "E-bisiklet denedin mi, ilk izlenimin neydi?", ["#elektriklibisiklet", "#ebisiklet"]),
    _r("dag", "Dağ bisikleti", ["Dağ Bisikleti"],
       ["Patikaya <em>hazır</em>", "Rotanı <em>dağa çevir</em>", "Asfaltın <em>bittiği yerde</em>",
        "Yokuşa <em>meydan oku</em>"],
       ["Asfaltın bittiği yerde başlar.", "Hafta sonu rotanı çiz, gerisini bu bisiklete bırak.",
        "Patika seni bekliyor.", "Köyceğiz'in tepeleri için bir dağ bisikleti."],
       "Senin favori patikan neresi?", ["#dağbisikleti", "#mtb"]),
    _r("gravel", "Gravel bisiklet", ["Gravel"],
       ["Asfalt da <em>toprak da</em>", "Yol bitince <em>devam et</em>", "Uzun rotaların <em>bisikleti</em>"],
       ["Asfaltta hızlı, toprakta rahat: gravel.", "Yol bitince dönmek zorunda değilsin."],
       "Asfalt mı, toprak yol mu?", ["#gravel", "#gravelbisiklet"]),
    _r("bmx", "BMX / DIRT JUMP", ["BMX/Dirtjump"],
       ["Rampaya <em>hazır</em>", "Havalanmaya <em>hazır</em>"],
       ["Rampa, pist, atlayış: bu bisiklet bunun için.", "Tekerlek küçük, eğlence büyük."],
       "İlk numaranı hangi bisikletle denedin?", ["#bmx", "#dirtjump"]),
    _r("sehir", "Şehir bisikleti", ["Şehir Bisikleti"],
       ["Şehirde <em>özgürlük</em>", "Her güne <em>bir pedal</em>", "İşe, okula, <em>sahile</em>",
        "Günlük sürüşün <em>bisikleti</em>"],
       ["İşe, okula, sahile: tek bisiklet, her yere.", "Arabayı park et, keyfi pedalla.",
        "Her güne bir pedal.", "Günlük sürüş için rahat bir bisiklet."],
       "Bisikletle işe ya da okula gidiyor musun?", ["#şehirbisikleti", "#bisikletlehayat"]),
    _r("cocuk", "Çocuk bisikleti", ["Çocuk Bisikleti"],
       ["Pedal çevirme <em>zamanı</em>", "Küçük sürücüye <em>büyük keyif</em>", "Çocuğunun <em>yeni bisikleti</em>"],
       ["Bir çocuğun unutmadığı hediye: ilk bisikleti.", "Küçük sürücüler için.",
        "Doğru boy bisiklet, çocuğa güven verir."],
       "Senin ilk bisikletin kaç janttı?", ["#çocukbisikleti", "#bisikletsevenler"]),
    # --- Giyim ve koruma
    _r("eldiven_kis", "Kışlık eldiven", ["Eldiven"], ["Ellerin <em>sıcak kalsın</em>", "Soğukta <em>sürmeye devam</em>"],
       ["Üşüyen parmak fren kolunu geç sıkar.", "Soğuk havada eller ilk üşüyen yer."],
       "Kışın da sürenlerden misin, baharı bekleyenlerden mi?", ["#bisikleteldiveni", "#kışbisikleti"], inc="kışlık"),
    _r("eldiven_cocuk", "Çocuk eldiveni", ["Eldiven"], ["Küçük ellere <em>eldiven</em>", "Minik sürücüye <em>eldiven</em>"],
       ["Küçük eller için kısa parmak eldiven.", "Minik sürücünün gidonu sağlam tutması için."],
       "Çocuğun bisiklete kaç yaşında başladı?", ["#çocukbisikleti", "#bisikleteldiveni"], inc="çocuk"),
    _r("eldiven", "Kısa parmak eldiven", ["Eldiven"], ["Gidonu <em>sağlam tut</em>", "Avuçların <em>rahat etsin</em>"],
       ["Eldiven, gidonu daha sağlam tutmanı sağlar.", "Küçük bir ekipman, hissedilir bir fark."],
       "Eldivenle mi sürersin, eldivensiz mi?", ["#bisikleteldiveni", "#bisikletekipmanı"], inc="kısa parmak"),
    _r("kask_cocuk", "Çocuk kaskı", ["Kask"], ["Küçük başlara <em>kask</em>", "Önce <em>kask</em>, sonra pedal"],
       ["Önce kask, sonra pedal.", "Kısa mesafede de kask."],
       "Çocuğun kaskını severek takıyor mu?", ["#bisikletkaskı", "#çocukbisikleti"], inc="çocuk"),
    _r("bandana", "Bandana", ["Bandana"], ["Rüzgâra karşı <em>bandana</em>", "Küçük ama <em>işe yarar</em>"],
       ["Küçük, hafif, her sürüşte işe yarar.", "Rüzgârlı günlerin küçük yardımcısı."],
       "Sürüşe çıkarken yanından ayırmadığın şey ne?", ["#bisikletekipmanı", "#hediyefikri"]),
    _r("gozluk", "Bisiklet gözlüğü", ["Gözlük"], ["Gözünü <em>rüzgârdan koru</em>", "Gözlük yalnızca <em>güneş için değil</em>"],
       ["Gözlük gözünü rüzgârdan, tozdan ve böcekten korur.", "Gözlük yalnızca güneş için değil."],
       "Gözlüksüz sürüşe çıkar mısın?", ["#bisikletgözlüğü", "#bisikletekipmanı"]),
    _r("forma", "Takım forması", ["Forma"], ["Takımın <em>forması</em>", "NITRO BIKE TEAM <em>forması</em>"],
       ["NITRO Bike Team forması.", "Enduro ve downhill için takım forması."],
       "Enduro mu, downhill mi?", ["#enduro", "#downhill"], inc="nitro bike team"),
    # --- Aydınlatma, çamurluk, güvenlik
    _r("lamba", "Bisiklet lambası", ["Aydınlatma ve Reflektör"],
       ["Karanlıkta <em>görün</em>", "Akşam sürüşüne <em>ışık</em>", ("Gün erken <em>kararıyor</em>", KIS)],
       ["Seni görmeyen sürücü sana yol veremez.", "Akşam sürüşünde ışığın yanında olsun.",
        "Işık yalnızca görmek için değil, görünmek için."],
       "Akşam sürüşünde ışıkların hep yanında mı?", ["#bisikletlambası", "#güvenlisürüş"], inc="lamba|far|ışık"),
    _r("camurluk", "Çamurluk", ["Çamurluk ve Muhafaza"],
       ["Çamur <em>sende kalmasın</em>", "Islak yola <em>hazırlan</em>"],
       ["Çamurluk, tekerlekten sıçrayan suyu ve çamuru keser.", "Yağmurdan sonra da sürenler için."],
       "Çamurluk takar mısın, çamura aldırmaz mısın?", ["#çamurluk", "#kışbisikleti"], inc="çamurluk"),
    _r("kilit", "Bisiklet kilidi", ["Kilit"], ["Bisikletin <em>yerinde kalsın</em>", "Kilitle, <em>için rahat etsin</em>"],
       ["İki dakikalığına da olsa kilitle.", "Bisikleti alıp gitmek için birkaç saniye yeter."],
       "Bisikletini dışarıda bırakırken nasıl kilitliyorsun?", ["#bisikletkilidi", "#bisikletaksesuarı"]),
    _r("zil_cocuk", "Çocuk zili", ["Zil, Korna, Ayna"], ["Minik sürücüye <em>zil</em>", "Zil çal, <em>haber ver</em>"],
       ["Çocukların en sevdiği aksesuar: zil.", "Küçük sürücü geliyor, haberiniz olsun."],
       "Çocukken bisikletinde zil var mıydı?", ["#çocukbisikleti", "#bisikletzili"], inc=r"\bzil.*çocuk|çocuk.*\bzil"),
    _r("zil", "Bisiklet zili", ["Zil, Korna, Ayna"], ["Zil çal, <em>haber ver</em>", "Geliyorum demenin <em>kibar yolu</em>"],
       ["Yayanın yanından geçmeden önce zil çal.", "Küçük bir zil, büyük bir kolaylık."],
       "Zil mi çalarsın, seslenir misin?", ["#bisikletzili", "#bisikletaksesuarı"], inc=r"\bzil"),
    _r("ayna", "Bisiklet aynası", ["Zil, Korna, Ayna"], ["Arkanı <em>gör</em>", "Arkadan geleni <em>gör</em>"],
       ["Başını çevirmeden arkanı gör.", "Trafikte arkadan geleni bilmek rahatlatır."],
       "Bisikletinde ayna kullanıyor musun?", ["#bisikletaynası", "#güvenlisürüş"], inc="ayna"),
    # --- Sürüş aksesuarları
    _r("pompa", "Bisiklet pompası", ["Pompa"],
       ["Lastiğin <em>inik kalmasın</em>", "Doğru basınç, <em>rahat sürüş</em>", "Pompan <em>hazır olsun</em>"],
       ["Lastikler sürmesen de hava kaybeder.", "İnik lastikle sürüş hem yorar hem lastiği yıpratır."],
       "Lastik basıncını pompayla mı ölçersin, parmakla mı?", ["#bisikletpompası", "#bisikletbakımı"], inc="pompa"),
    _r("matara_kafesi", "Matara kafesi", ["Matara ve Kafes"],
       ["Mataran <em>elinin altında</em>", "Mataraya <em>sağlam yuva</em>", "Suyun <em>hep yanında</em>"],
       ["Matara çantada değil, bisikletinde dursun.", "Su elinin altında olunca daha sık içersin."],
       "Mataran bisiklette mi durur, çantada mı?", ["#matarakafesi", "#bisikletaksesuarı"], inc="kafes|tutucu"),
    _r("matara", "Matara", ["Matara ve Kafes"], ["Suyun <em>yanında olsun</em>", ("Kışın da <em>su iç</em>", KIS)],
       ["Susamayı bekleme, sürüş boyunca yudum yudum iç.", "Her sürüşte yanında olması gereken şey: su."],
       "Mataranda ne olur: sade su mu, başka bir şey mi?", ["#matara", "#bisikletaksesuarı"], inc="matara",
       exc="kafes|tutucu"),
    _r("telefon_tutucu", "Telefon tutucu", ["Telefon Tutucu"],
       ["Rotan <em>gözünün önünde</em>", "Telefonun <em>yerinde dursun</em>"],
       ["Rotaya bakmak için durmana gerek yok.", "Telefon cepte değil, gözünün önünde."],
       "Sürerken navigasyon kullanıyor musun?", ["#telefontutucu", "#bisikletaksesuarı"]),
    _r("km_saati", "Kilometre saati", ["Km Saati"], ["Hızını <em>gör</em>", "Sürüşünü <em>ölç</em>"],
       ["Ölçmediğin sürüşü geliştiremezsin.", "Hızını tahmin etme, gör."],
       "Bugüne kadarki en uzun sürüşün kaç kilometreydi?", ["#kilometresaati", "#bisikletaksesuarı"]),
    _r("sepet", "Ön sepet", ["Çanta ve Sepet"], ["Yükünü <em>sepete bırak</em>", "Alışveriş <em>sepette</em>"],
       ["Poşeti gidona asma, sepete koy.", "Çarşı pazar için pratik bir ekleme."],
       "Bisikletle alışverişe gider misin?", ["#bisikletsepeti", "#bisikletlehayat"], inc="sepet"),
    _r("canta", "Bisiklet çantası", ["Çanta ve Sepet"],
       ["Yükün <em>bisiklette dursun</em>", "Eşyaların <em>yanında gelsin</em>", "Tura <em>hazırlan</em>"],
       ["Sırt çantası sırtını terletir; yükü bisiklet taşısın.", "Eşyanı cebinde değil, bisikletinde taşı.",
        "Tura çıkmadan önce yükün yerini belirle."],
       "Turda yükü nerede taşırsın: bisiklet çantası mı, sırt çantası mı?", ["#bisikletçantası", "#bisikletturu"],
       inc="çanta|heybe", exc="taşıma|toka"),
    _r("cocuk_koltugu", "Çocuk koltuğu", ["Taşıyıcı ve Bagaj"], ["Küçük yolcuya <em>yer aç</em>", "Birlikte <em>sürün</em>"],
       ["Sürüşe küçük yolcunu da al.", "Aile sürüşleri için."],
       "Çocuğunla ilk sürüşünü hatırlıyor musun?", ["#çocukkoltuğu", "#ailecebisiklet"], inc="çocuk koltuğu"),
    _r("park_ayagi", "Park ayağı", ["Park Ayağı ve Sehpa"],
       ["Bisikletin <em>ayakta dursun</em>", "Yere yatırma, <em>ayağa kaldır</em>"],
       ["Bisikleti duvara yaslamak ya da yere yatırmak zorunda değilsin.", "Küçük bir parça, her gün işe yarar."],
       "Bisikletini nereye yaslarsın?", ["#parkayağı", "#bisikletaksesuarı"], inc="park ayağı"),
    # --- Parçalar
    _r("sele_cocuk", "Çocuk bisikleti selesi", ["Sele ve Kılıf", "Sele Grubu"],
       ["Minik sürücüye <em>yeni sele</em>", "Çocuk bisikletine <em>sele</em>"],
       ["16 ve 20 jant çocuk bisikletleri için sele.", "Yıpranan seleyi yenile, bisiklet yeni gibi olsun."],
       "Çocuğunun bisikleti kaç jant?", ["#çocukbisikleti", "#bisikletselesi"], inc=r"sele.*16 20 jant"),
    _r("sele", "Sele", ["Sele ve Kılıf", "Sele Grubu"], ["Seleni <em>yenile</em>", "Rahat otur, <em>uzun sür</em>"],
       ["Sürüş keyfi çoğu zaman selede başlar.", "Yıpranan seleyi değiştirmek sürüşü değiştirir."],
       "Seleni hiç değiştirdin mi?", ["#bisikletselesi", "#bisikletparçası"], inc=r"\bsele\b|selesi",
       exc="kelepçe|boru|minder|koltu"),
    _r("pedal", "Pedal", ["Pedal ve Kal"], ["Gücün <em>pedaldan geçer</em>", "Pedalını <em>yenile</em>"],
       ["Gücün bisiklete geçtiği yer: pedal.", "Yıpranan pedal ayağı kaydırır; yenisi takılır, fark hissedilir."],
       "Düz pedal mı, kilitli pedal mı?", ["#bisikletpedalı", "#bisikletparçası"], inc="pedal", exc="pedal kolu"),
    _r("sargi", "Gidon sargısı", ["Elcik Sargı Barend"], ["Gidonunu <em>yeniden sar</em>", "Yeni sargı, <em>yeni his</em>"],
       ["Yıpranan sargıyı yenile, gidon yeni gibi olsun.", "Elin her sürüşte gidonda; sargı önemli."],
       "Gidon sargını en son ne zaman değiştirdin?", ["#gidonsargısı", "#bisikletparçası"], inc="sargı"),
    _r("elcik", "Elcik", ["Elcik Sargı Barend"], ["Gidonu <em>sağlam kavra</em>", "Elciğini <em>yenile</em>"],
       ["Elin her sürüşte gidonda; elcik düşündüğünden önemli.", "Yıpranan elcik kayar. Yenisi takılır, fark hissedilir."],
       "Bisikletinde ilk değiştirdiğin parça neydi?", ["#elcik", "#bisikletparçası"], inc="elci[kğ]"),
    _r("ic_lastik", "İç lastik", ["İç Lastik"], ["Yedek iç lastik <em>yanında mı?</em>", "Patlak <em>yolda bırakmasın</em>", "Lastiğin <em>havası yerinde</em>"],
       ["Yolda yama yapmak yerine iç lastik değiştirmek daha hızlıdır.", "Yedek iç lastik: küçük yük, büyük rahatlık."],
       "Yolda lastiğin patladı mı hiç, o gün ne yaptın?", ["#içlastik", "#bisikletbakımı"]),
    _r("dis_lastik", "Dış lastik", ["Dış Lastik"],
       ["Yol tutuş <em>lastikten gelir</em>", "Lastiğini <em>yenile</em>", "Dişler silindiyse <em>vakit geldi</em>"],
       ["Yanağında çatlak, sırtında silinmiş diş varsa değişim zamanı.", "Bisikletin yola değen tek yeri lastiği."],
       "Lastiklerini en son ne zaman değiştirdin?", ["#bisikletlastiği", "#bisikletparçası"]),
    _r("zincir", "Zincir", ["Vites Grubu"], ["Zincirini <em>yenile</em>", "Uzamış zinciri <em>değiştir</em>"],
       ["Zincir kullandıkça uzar; zamanında değişmezse rubleyi ve aynakolu da yıpratır.",
        "Yeni zincir, aktarmanın geri kalanını korur."],
       "Zincirini en son ne zaman değiştirdin?", ["#bisikletzinciri", "#bisikletbakımı"], inc="zincir",
       exc="gergi|kılavuz|powerlink|aynakol|koruma|teli"),
    _r("kaset", "Kaset dişli", ["Vites Grubu"], ["Kasetini <em>yenile</em>", "Arka dişlini <em>yenile</em>", "Vitesler <em>pürüzsüz geçsin</em>"],
       ["Aşınmış dişli zinciri attırır.", "Zincirle birlikte kaset de yıpranır."],
       "Arkada kaç vitesin var?", ["#bisikletparçası", "#shimano"], inc="kaset"),
    _r("balata", "Fren balatası", ["Fren Grubu", "Balatalar & Pabuçlar"],
       ["Frenine <em>güven</em>", "Balatan <em>bitmeden</em> değiştir"],
       ["Islak ve çamurlu yolda balata daha hızlı aşınır.", "Frenden metal sesi geliyorsa balata bitmiş olabilir."],
       "Senin bisikletinde disk fren mi var, jant freni mi?", ["#frenbalatası", "#bisikletbakımı"], inc="balata|pabu",
       exc="sprey|seti|temizle"),
    _r("rotor", "Disk fren rotoru", ["Disk Fren Rotorları"], ["Rotorunu <em>yenile</em>", "Fren gücü <em>rotordan geçer</em>"],
       ["Aşınmış ya da eğrilmiş rotor freni zayıflatır.", "Disk frenin yarısı balata, yarısı rotor."],
       "Rotorun kaç milim?", ["#diskfren", "#bisikletparçası"], inc="rotor"),
    _r("gidon", "Gidon", ["Gidon Grubu"], ["Kontrol <em>gidonda</em>", "Gidonunu <em>yenile</em>"],
       ["Bisikleti yönettiğin yer: gidon.", "Gidon değişir, sürüş pozisyonun değişir."],
       "Gidonun kaç milim genişliğinde?", ["#gidon", "#bisikletparçası"], inc="gidon",
       exc="boğaz|yükselt|furç|adaptör"),
    _r("masa", "Ön maşa", ["Amortisör"], ["Ön takımı <em>yükselt</em>", "İnişe <em>hazır</em>"],
       ["Sürüş karakterini en çok değiştiren parçalardan biri: maşa.", "Ön takımını yenilemek isteyenler için."],
       "Maşanda kaç milim hareket mesafesi var?", ["#enduro", "#mtb"], inc=r"maşa|fox 36 float", exc="kilitleme kolu"),
    # --- Bakım
    _r("zincir_yagi", "Zincir yağlayıcı", ["Kimyasal"], ["Zincirin <em>yağsız kalmasın</em>", "Zincirine <em>bakım yap</em>"],
       ["Yağmur zincirdeki yağı yıkayıp götürür.", "Kuru zincir ses yapar, çabuk yıpranır."],
       "Zincirini en son ne zaman yağladın?", ["#zinciryağı", "#bisikletbakımı"], inc="zincir yağ"),
    _r("balata_spreyi", "Balata temizleme spreyi", ["Kimyasal"],
       ["Frenlerin <em>temiz kalsın</em>", "Fren bakımına <em>sprey</em>"],
       ["Kirli fren ses yapar.", "Fren bakımında işini kolaylaştırır."],
       "Frenlerin ses yapıyor mu?", ["#bisikletbakımı", "#diskfren"], inc="balata"),
    _r("bakim_spreyi", "Bakım spreyi", ["Kimyasal"], ["Bakım çantana <em>ekle</em>", "Bakım <em>elinin altında</em>"],
       ["Çok amaçlı bir bakım spreyi.", "Bakım çantasında bulunması iyi olanlardan."],
       "Bisikletinin bakımını kendin mi yaparsın?", ["#bisikletbakımı", "#bisikletservisi"], inc="bakım spreyi"),
    _r("yama", "Yama ve tamir kiti", ["Atölye ve Tamir", "Anahtar ve Alet"],
       ["Patlak <em>sürüşü bitirmesin</em>", "Tamir kitin <em>yanında olsun</em>", "Delik lastiğe <em>yolda çözüm</em>"],
       ["Patlak lastik sürüşün sonu olmak zorunda değil.", "Küçük bir kit, yolda büyük rahatlık."],
       "Yolda lastik tamir ettin mi hiç?", ["#bisiklettamiri", "#bisikletbakımı"], inc="yama|tamir kiti"),
]
RULE = {r["id"]: r for r in RULES}

# İkinci, bağımsız güvence: kuralın başlıkları yalnız adı şu kalıba uyan ürüne yazılabilir (kural sırasından bağımsız).
MUST = {
    "lamba": (r"lamba|far\b|ışık", None), "camurluk": (r"çamurluk", None), "kilit": (r"kilit|lock", None),
    "pompa": (r"pompa", r"jump"), "matara": (r"matara", r"kafes|tutucu"), "matara_kafesi": (r"kafes|tutucu", None),
    "telefon_tutucu": (r"telefon", None), "km_saati": (r"kilometre saati|hız göstergesi|bisiklet bilgisayarı", None),
    "zil": (r"\bzil", r"ayna"), "zil_cocuk": (r"\bzil", r"ayna"), "ayna": (r"ayna", None),
    "eldiven": (r"eldiven", r"çocuk|kışlık"), "eldiven_cocuk": (r"çocuk eldiven", None), "eldiven_kis": (r"kışlık eldiven", None),
    "kask_cocuk": (r"çocuk.*kask", None), "bandana": (r"bandana", None), "gozluk": (r"gözlü", None), "forma": (r"forma", None),
    "sepet": (r"sepet", None), "canta": (r"çanta|heybe", r"taşıma|toka"), "cocuk_koltugu": (r"çocuk koltuğu", None),
    "park_ayagi": (r"park ayağı", None), "sele": (r"\bsele\b|selesi", r"kelepçe|boru|minder|16 20 jant"),
    "sele_cocuk": (r"sele.*16 20 jant", None), "pedal": (r"pedal", r"pedal kolu"), "sargi": (r"sargı", None),
    "elcik": (r"elci[kğ]", None), "ic_lastik": (r"[iı]ç lastik|tube", None), "dis_lastik": (r"dış lastik|\d+x\d", r"[iı]ç lastik"),
    "zincir": (r"zincir", r"gergi|kılavuz|powerlink|aynakol|sprey|yağ"), "kaset": (r"kaset", None),
    "balata": (r"balata|pabu", r"sprey|temizle"), "rotor": (r"rotor", None), "gidon": (r"gidon", r"boğaz|sargı|ayna|çanta"),
    "masa": (r"maşa|fox 36", r"kol"), "zincir_yagi": (r"zincir yağ", None), "balata_spreyi": (r"balata.*sprey", None),
    "bakim_spreyi": (r"bakım spreyi", None), "yama": (r"yama|tamir kiti", None),
}


def name_fits(rule_id: str, name: str) -> bool:
    """Ürün adı kuralın alt türüne gerçekten uyuyor mu? (Bisiklet kurallarında kategori yeterlidir.)"""
    if rule_id not in MUST:
        return rule_id in RULE
    need, ban = MUST[rule_id]
    n = tr_lower(name)
    return bool(re.search(need, n)) and not (ban and re.search(ban, n))


# ---- Soru havuzları (O3): açıklamanın 2. satırı, iki seçenekli soru ---------------------------------
# Evet/hayır sorusu yok: her soru iki seçenek sunar ("X mı, Y mı?"). Kural başına ≥3 soru; bir soru yalnız
# bir havuzda geçer (30 gün tekrar denetimi havuzlar arası çakışmayı da yakalar). Kuralların eski tek
# sorusu (`q`) artık kullanılmaz: aşağıda havuzun ilk sorusuyla değiştirilir.
SORULAR = {
    "ikinciel": ["İlk bisikletin sıfır mıydı, 2. el mi?", "2. el alırken önce kadroya mı bakarsın, parçalara mı?",
                 "Sıfır mı alırsın, kontrollü 2. el mi?"],
    "ebike": ["E-bisikleti işe gidişte mi kullanırdın, hafta sonu turunda mı?",
              "Yokuşta motor desteği mi, kendi bacak gücün mü?", "E-bisiklette menzil mi önemli, hafiflik mi?"],
    "dag": ["Tırmanış mı, iniş mi?", "Patika mı, orman yolu mu?", "Sabah sürüşü mü, gün batımı sürüşü mü?"],
    "gravel": ["Asfalt mı, toprak yol mu?", "Gravelle uzun tur mu, kısa kaçamak mı?", "Sahil yolu mu, köy yolları mı?"],
    "bmx": ["Rampa mı, pist mi?", "Zıplama mı, tek teker mi?", "Park mı, sokak mı?"],
    "sehir": ["İşe bisikletle mi, arabayla mı?", "Sepetli mi, sepetsiz mi?", "Sahil turu mu, çarşı turu mu?"],
    "cocuk": ["Senin ilk bisikletin 16 jant mıydı, 20 jant mı?", "Yardımcı tekerlek mi, denge bisikleti mi?",
              "Çocuğunla sahilde mi sürersin, parkta mı?"],
    "eldiven_kis": ["Kışın da sürenlerden misin, baharı bekleyenlerden mi?",
                    "Soğukta önce ellerin mi üşür, ayakların mı?", "Kış sürüşü sabah mı, öğlen mi?"],
    "eldiven_cocuk": ["Çocuğun bisiklete 4 yaşında mı başladı, 6 yaşında mı?",
                      "Minik sürücü eldivenle mi sürer, eldivensiz mi?",
                      "Çocuğunun en sevdiği renk kırmızı mı, mavi mi?"],
    "eldiven": ["Eldivenle mi sürersin, eldivensiz mi?", "Kısa parmak mı, uzun parmak mı?",
                "Eldivende jel destekli mi seversin, ince mi?"],
    "kask_cocuk": ["Çocuğun kaskını kendisi mi seçti, sen mi?", "Çocuk kaskı desenli mi olsun, düz renk mi?",
                   "Kaskı çocuk mu ilk takar, sen mi hatırlatırsın?"],
    "bandana": ["Bandana boyunda mı, başta mı?", "Bandana mı, boyunluk mu?", "Sürüşte seni rüzgâr mı yorar, toz mu?"],
    "gozluk": ["Koyu cam mı, şeffaf cam mı?", "Gözlüklü mü sürersin, gözlüksüz mü?",
               "Sürüşte gözünü rüzgâr mı yorar, güneş mi?"],
    "forma": ["Enduro mu, downhill mi?", "Kısa kollu forma mı, uzun kollu mu?", "Yarış günü mü, antrenman mı?"],
    "lamba": ["Akşam sürüşünde sabit ışık mı, yanıp sönen mi?", "Önce ön far mı alınır, arka stop mu?",
              "Gün batınca sürmeye devam mı, eve dönüş mü?"],
    "camurluk": ["Çamurluk takar mısın, çamura aldırmaz mısın?",
                 "Yağmurdan sonra hemen sürer misin, yolun kurumasını mı beklersin?",
                 "Sabit çamurluk mu, sökülüp takılan mı?"],
    "kilit": ["Zincir kilit mi, U kilit mi?", "Şifreli kilit mi, anahtarlı mı?",
              "Bisikletin gece içeride mi kalır, dışarıda mı?"],
    "zil_cocuk": ["Çocukken bisikletinde zil var mıydı, korna mı?", "Çocuk bisikletine zil mi, korna mı?",
                  "Çocuğun zili en çok parkta mı çalar, sokakta mı?"],
    "zil": ["Zil mi çalarsın, seslenir misin?", "Klasik zil mi, tiz sesli zil mi?",
            "Zili en çok sahilde mi çalarsın, şehirde mi?"],
    "ayna": ["Sağ ayna mı, sol ayna mı?", "Arkana ayna ile mi bakarsın, omzunun üstünden mi?",
             "Gidon aynası mı, kask aynası mı?"],
    "pompa": ["Lastik basıncını pompayla mı ölçersin, parmakla mı?", "Ayak pompası mı, el pompası mı?",
              "Basıncı haftada bir mi kontrol edersin, sürüşten önce mi?"],
    "matara_kafesi": ["Mataran bisiklette mi durur, çantada mı?", "Tek matara mı, iki matara mı?",
                      "Matara kafesi kadroda mı, gidonda mı?"],
    "matara": ["Mataranda soğuk su mu olur, ılık su mu?", "Matarayı sürüşte mi bitirirsin, eve dolu mu dönersin?",
               "Küçük matara mı, büyük matara mı?"],
    "telefon_tutucu": ["Sürerken navigasyon mu, ezberden rota mı?", "Telefon gidonda mı, cepte mi?",
                       "Rotayı haritadan mı izlersin, saatten mi?"],
    "km_saati": ["Hızı mı takip edersin, mesafeyi mi?", "Kablolu mu, kablosuz mu?",
                 "En uzun sürüşün 50 kilometreden kısa mı, uzun mu?"],
    "sepet": ["Alışverişe bisikletle mi gidersin, arabayla mı?", "Ön sepet mi, arka sepet mi?",
              "Sepete pazar alışverişi mi girer, piknik çantası mı?"],
    "canta": ["Turda yükü bisiklet çantası mı taşır, sırt çantası mı?", "Kadro çantası mı, sele altı çantası mı?",
              "Günübirlik tur mu, kamp turu mu?"],
    "cocuk_koltugu": ["Çocuk koltuğu önde mi, arkada mı?", "Küçük yolcuyla sahil mi, park mı?",
                      "Küçük yolcuyla kısa tur mu, uzun tur mu?"],
    "park_ayagi": ["Bisikletini duvara mı yaslarsın, park ayağına mı?", "Orta ayak mı, arka ayak mı?",
                   "Bisiklet evde mi durur, balkonda mı?"],
    "sele_cocuk": ["Çocuğunun bisikleti 16 jant mı, 20 jant mı?", "Sele yüksekliğini sen mi ayarlarsın, çocuğun mu?",
                   "Renkli sele mi, siyah sele mi?"],
    "sele": ["Geniş sele mi, ince sele mi?", "Sele yumuşak mı olsun, sert mi?",
             "Seleni sürüş tarzına göre mi seçersin, görünüşe göre mi?"],
    "pedal": ["Düz pedal mı, kilitli pedal mı?", "Metal pedal mı, plastik pedal mı?",
              "Pedala ayak ucuyla mı basarsın, orta tabanla mı?"],
    "sargi": ["Gidon sargısı siyah mı olsun, renkli mi?", "İnce sargı mı, kalın sargı mı?",
              "Sargıyı kendin mi sararsın, atölyeye mi bırakırsın?"],
    "elcik": ["Kilitli elcik mi, geçmeli elcik mi?", "İnce elcik mi, kalın elcik mi?",
              "Bisikletinde ilk değiştirdiğin parça elcik miydi, sele mi?"],
    "ic_lastik": ["Yolda patlakta yama mı yaparsın, iç lastik mi değiştirirsin?",
                  "Yedek iç lastik çantada mı durur, evde mi?", "İnce sibop mu, kalın sibop mu?"],
    "dis_lastik": ["Dişli lastik mi, düz lastik mi?", "Lastiği sezon başında mı değiştirirsin, dişler bitince mi?",
                   "Geniş lastik mi, ince lastik mi?"],
    "zincir": ["Zincirini kilometreye göre mi değiştirirsin, sesine göre mi?",
               "Zincir ölçer mi kullanırsın, ustaya mı bırakırsın?",
               "Zincir değişimini kendin mi yaparsın, atölyede mi?"],
    "kaset": ["Arkada 8 vites mi, 11 vites mi?", "Kaset ile zinciri birlikte mi değiştirirsin, ayrı ayrı mı?",
              "Geniş vites aralığı mı, sık vites mi?"],
    "balata": ["Disk fren mi, jant freni mi?", "Balatayı ses gelince mi değiştirirsin, kontrolde mi?",
               "Organik balata mı, metal balata mı?"],
    "rotor": ["160 mm rotor mu, 180 mm mi?", "Rotoru kendin mi değiştirirsin, atölyeye mi bırakırsın?",
              "Ön ve arka rotor aynı mı, farklı mı?"],
    "gidon": ["Geniş gidon mu, dar gidon mu?", "Düz gidon mu, yükseltilmiş gidon mu?",
              "Gidonu konfor için mi değiştirirsin, kontrol için mi?"],
    "masa": ["Maşa kilidi tırmanışta açık mı, kapalı mı?", "Hava maşa mı, yaylı maşa mı?",
             "Maşa ayarını kendin mi yaparsın, atölyede mi?"],
    "zincir_yagi": ["Kuru yağ mı, ıslak yağ mı?", "Zincirini her sürüşten sonra mı yağlarsın, ses gelince mi?",
                    "Zinciri yağlamadan önce siler misin, doğrudan mı yağlarsın?"],
    "balata_spreyi": ["Frenlerin sessiz mi, ötüyor mu?", "Fren temizliği ayda bir mi, sezonda bir mi?",
                      "Fren bakımını evde mi yaparsın, atölyede mi?"],
    "bakim_spreyi": ["Bisikletinin bakımını kendin mi yaparsın, atölyeye mi bırakırsın?",
                     "Bakımı her ay mı yaparsın, sezon başında mı?", "Bakım çantasında sprey mi olur, bez mi?"],
    "yama": ["Yolda lastiği yamayla mı kurtarırsın, iç lastik değişimiyle mi?",
             "Tamir kiti sele çantasında mı, sırt çantasında mı?", "Patlak lastiği yolda mı tamir edersin, eve mi dönersin?"],
}
for _r_ in RULES:
    _r_["qs"] = SORULAR[_r_["id"]]
    _r_["q"] = _r_["qs"][0]

# İpucu carousel'leri (data/tips.json → carousels[].id). Tanımsız ipucunda genel havuz kullanılır.
IPUCU_SORULARI = {
    "kis-bakimi": ["Yağmurdan sonra bisikleti hemen mi silersin, ertesi gün mü?",
                   "Bisikletin kışın içeride mi durur, balkonda mı?", "Kış bakımı evde mi, atölyede mi?"],
    "cocuk-jant-boyu": ["Çocuğa bisiklet alırken boya mı bakarsın, yaşa mı?",
                        "Bisikleti çocukla birlikte mi denersin, ölçüyle mi seçersin?", "İlk bisiklet 16 jant mı, 20 jant mı?"],
    "islak-zemin": ["Islak yolda erken fren mi, yavaş viraj mı?", "Yağmurlu günde bisiklet mi, otobüs mü?",
                    "Islakta seni rögar kapağı mı şaşırtır, boyalı çizgi mi?"],
    "servis-isaretleri": ["Bisikletin önce frenden mi ses verir, vitesten mi?",
                          "Servise arıza çıkınca mı gelirsin, düzenli bakıma mı?",
                          "Fren kolu gidona yaklaşınca hemen mi bakarsın, sonraya mı bırakırsın?"],
    "lastik-basinci": ["Basıncı göstergeyle mi ölçersin, elle mi?", "Lastik basıncın yüksek mi, düşük mü?",
                       "Basıncı her sürüşten önce mi kontrol edersin, ayda bir mi?"],
    "zincir-bakimi": ["Zinciri önce temizler misin, doğrudan yağlar mısın?", "Zincir yağı damla damla mı, sprey mi?",
                      "Zincir bakımı her ay mı, ses gelince mi?"],
    "kask-ayari": ["Kask ayarını evde mi yaparsın, yola çıkınca mı?", "Çene kayışı sıkı mı, gevşek mi?",
                   "Kısa yolda da kask mı, yalnız uzun turda mı?"],
    "ebike-batarya-kis": ["Bataryayı içeride mi şarj edersin, garajda mı?",
                          "Kışın e-bisiklet mi, klasik bisiklet mi?", "Menzil kışın mı düşer, yokuşta mı?"],
}
IPUCU_GENEL = ["Bisiklet bakımını kendin mi yaparsın, atölyeye mi getirirsin?",
               "Bu ipucunu biliyor muydun, yeni mi öğrendin?", "Bu ipucunu hemen mi denersin, sonraya mı saklarsın?"]
YILBASI_SORULARI = ["Yeni yılın ilk sürüşü patika mı, sahil yolu mu?",
                    "Yeni yılda daha çok kilometre mi, daha çok rota mı?", "Yılın ilk turu sabah mı, öğleden sonra mı?"]

# 1. satırdaki konu adı (SEO): kural etiketi görselde büyük harfle yazılanlarda düz metne çevrilir
SEO_AD = {"ikinciel": "Kontrollü 2. el bisiklet", "bmx": "BMX ve dirt jump bisikleti",
          "eldiven": "Kısa parmak bisiklet eldiveni", "bandana": "Bisiklet bandanası", "forma": "Enduro forması",
          "camurluk": "Bisiklet çamurluğu", "matara_kafesi": "Bisiklet matara kafesi", "matara": "Bisiklet matarası",
          "telefon_tutucu": "Bisiklet telefon tutucu", "km_saati": "Bisiklet kilometre saati", "sepet": "Bisiklet sepeti",
          "cocuk_koltugu": "Bisiklet çocuk koltuğu", "park_ayagi": "Bisiklet park ayağı", "sele": "Bisiklet selesi",
          "pedal": "Bisiklet pedalı", "sargi": "Gidon sargısı", "elcik": "Bisiklet elciği",
          "ic_lastik": "Bisiklet iç lastiği", "dis_lastik": "Bisiklet dış lastiği", "zincir": "Bisiklet zinciri",
          "gidon": "Bisiklet gidonu", "masa": "Bisiklet ön maşası", "zincir_yagi": "Zincir yağı",
          "bakim_spreyi": "Bisiklet bakım spreyi", "yama": "Bisiklet tamir kiti"}

# ---- Havuzlar: hangi yayın türü hangi kurallardan ürün seçer ------------------------------------------
POOLS = {
    "performans": ["dag", "gravel", "ebike", "bmx"],                       # Pzt carousel: Haftanın bisikleti
    "gunluk": ["sehir", "cocuk", "ebike"],                                 # Cum carousel: Hafta sonu vitrini
    "parca": ["pedal", "canta", "elcik", "sele", "km_saati", "kaset", "telefon_tutucu", "zincir", "rotor", "gidon",
              "park_ayagi", "kilit", "masa", "sargi", "ic_lastik", "sepet", "pompa"],
    "pazar": ["canta", "telefon_tutucu", "kilit", "km_saati", "ayna", "matara", "zil", "gozluk", "forma", "bandana",
              "eldiven", "kask_cocuk", "cocuk_koltugu", "matara_kafesi", "yama", "sele"],
}
# Perşembe "mevsim" havuzu: aya göre. Tanımsız ayda "parca" havuzu kullanılır.
MEVSIM = {m: ["lamba", "camurluk", "balata", "dis_lastik", "zincir_yagi", "eldiven_kis", "balata_spreyi"]
          for m in KIS_AYLARI}
MEVSIM.update({m: ["matara", "matara_kafesi", "gozluk", "bandana", "eldiven", "canta", "telefon_tutucu", "km_saati"]
               for m in YAZ_AYLARI})
MEVSIM_KICKER = {**{m: "Kış seçkisi" for m in KIS_AYLARI}, **{m: "Yaz seçkisi" for m in YAZ_AYLARI}}


def pool_rules(pool: str, month: int) -> list[str]:
    if pool == "mevsim":
        return MEVSIM.get(month) or POOLS["parca"]
    if pool == "hepsi":
        return [r["id"] for r in RULES]
    return POOLS[pool]


# Ürün dışı içeriklerin kural kimlikleri (takvimdeki `rule` alanı)
RULE_IPUCU, RULE_SERVIS, RULE_MARKA, RULE_SORU, RULE_YILBASI = "ipucu", "servis", "marka", "soru", "yilbasi"


def rule_of(p: dict) -> dict | None:
    """Ürünün kuralı; hariç tutulan ya da hiçbir kurala uymayan üründe None (içerik üretilmez)."""
    if excluded(p):
        return None
    name, cat = tr_lower(p.get("name") or ""), p.get("category")
    for r in RULES:
        if cat in r["cats"] and (not r["inc"] or r["inc"].search(name)) and not (r["exc"] and r["exc"].search(name)):
            return r if name_fits(r["id"], p.get("name") or "") else None
    return None


def headlines(rule: dict, month: int) -> list[str]:
    """Kuralın o ay kullanılabilecek başlıkları (mevsime bağlı başlıklar mevsimi dışında çıkmaz)."""
    return [h for h, months in rule["heads"] if months is None or month in months]


def headline_ok(rule_id: str, title: str, month: int) -> bool:
    r = RULE.get(rule_id)
    return bool(r) and plain(title) in [plain(h) for h in headlines(r, month)]


def eligible(p: dict) -> bool:
    """İçerik olabilecek ürün: fiyatı, stoğu, fotoğrafı ve kuralı var; indirim iddiası doğuracak eski fiyatı yok."""
    return bool(p.get("price")) and p.get("in_stock", True) is True and bool(p.get("images")) and rule_of(p) is not None


# ---- Teknik özellikler ---------------------------------------------------------------------------
# Site ürün sayfasındaki "Teknik döküm" alanı altbilgiyle ve açıklama satırlarıyla karışık gelir.
# Yalnızca bilinen anahtarlar, kısa ve cümle olmayan değerlerle alınır.

SPEC_ORDER = ["Jant Ölçüsü", "Vites", "Fren Tipi", "Motor", "Batarya", "Menzil", "Maşa", "Kadro Malzemesi", "Kadro Boyu",
              "Süspansiyon", "Fren Sistemi", "Arka Aktarıcı", "Lastik", "Ölçü", "Çap", "Uzunluk", "Genişlik", "Hacim",
              "Toplam Hacim", "Uyumluluk", "Malzeme", "Bağlantı", "Montaj", "Ağırlık", "Seri", "Model", "Konum",
              "Delik Sayısı", "Diş Aralığı", "Dişli Dizilimi", "Hareket mesafesi", "Renk", "Kadro", "Aynakol",
              "Ruble (Kaset)", "Jant Takımı", "Vites Kolları", "Şarj Süresi", "Tip", "Kullanım", "Marka"]
SPEC_KEYS = set(SPEC_ORDER)
FOOTER_KEYS = {"Atölye", "Fiş takibi", "Destek", "Sipariş takibi", "Kargo", "Mağaza", "Yedek Parça", "Giyim", "Yasal",
               "Bisiklet", "Aksesuar", "2. El Bisiklet", "İletişim", "Servis randevusu", "Made by", "Barış Şen"}
FOOTER_VALUES = FOOTER_KEYS | {"Çamur günlüğü", "Uygulamayı kur", "İade & değişim", "Reddet", "Açıklama"}


EN_TR = [(r"\bsuspension fork\b", "süspansiyonlu maşa"), (r"\brear hub motor\b", "arka göbek motoru"),
         (r"\bfront hub motor\b", "ön göbek motoru"), (r"\blithium battery\b", "lityum batarya"),
         (r"\balloy suspension\b", "alüminyum süspansiyonlu"), (r"\bcarbon\b", "Karbon"), (r"\bbarend\b", "bar uç")]


def _spec_value(v: str) -> str:
    """Değer biçimi: tümü büyük harfli değer başlık düzenine, birimler standart yazıma (36v/10.4ah -> 36 V / 10,4 Ah)."""
    letters = [ch for ch in v if ch.isalpha()]
    if len(letters) > 3 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        v = " ".join(_title_word(w) for w in v.split(" "))
    v = re.sub(r"(\d+)\.(\d+)\s*ah\b", r"\1,\2 Ah", v, flags=re.I)
    v = re.sub(r"(\d+)\s*ah\b", r"\1 Ah", v, flags=re.I)
    v = re.sub(r"(\d+)\s*v\b", r"\1 V", v, flags=re.I)
    v = re.sub(r"\s*/\s*(?=\d+(,\d+)? Ah)", " / ", v)
    for a, b in FIXES:  # başlık düzeni FIXES'ten sonra çalıştığı için yazım düzeltmeleri yeniden uygulanır
        v = v.replace(a, b)
    return v


def clean_specs(p: dict, n: int = 6) -> list[tuple[str, str]]:
    """Görsele ve açıklamaya girebilecek temiz (anahtar, değer) çiftleri, öncelik sırasıyla."""
    raw = p.get("specs") or {}
    name = tr_lower(p.get("name") or "")
    out = {}
    for k, v in raw.items():
        k, v = str(k).strip(), fix_text(str(v).strip())
        if k in FOOTER_KEYS or k.endswith(":") or tr_lower(k) == name or k not in SPEC_KEYS:
            continue
        if not v or len(v) > 44 or v in FOOTER_VALUES or v in SPEC_KEYS or v.endswith(":"):
            continue
        if re.search(r"[.!?]$", v) or v.count(" ") > 6 or re.match(r"^[-•●*]", v):  # cümle ya da madde imi
            continue
        if "/" in v and re.search(r"[a-z]{4,}\s*/\s*[A-Za-z]{4,}|/[a-z]+ [a-z]+|/\s*(steel|alloy|alumin[i]?um|carbon)\b",
                                  v, re.I):   # çift dilli değer: Türkçesi
            v = v.split("/")[0].strip()
        for en, tr in EN_TR:
            v = re.sub(en, tr, v, flags=re.I)
        out[k] = _spec_value(v)
    rows = [(k, out[k]) for k in SPEC_ORDER if k in out]
    if "Kadro Malzemesi" in out:     # aynı bilgiyi iki kez gösterme
        rows = [(k, v) for k, v in rows if k != "Kadro"]
    if "Fren Tipi" in out and "Fren Sistemi" in out:
        rows = [(k, v) for k, v in rows if k != "Fren Sistemi"]
    return rows[:n]


_BAD_SENT = re.compile(r"motosiklet|scooter|otomobil|iş güvenliği|profesyonel|indirim|kampanya|stok|hediye|"
                       r"gönderil|fiyatıdır|faturalı|orijinal|en üst|en iyi|üstün|mükemmel|garanti|tutkun|deneyim|"
                       r"şık|estetik|favori|kalite|çözüm|araç sahip|performans|maksimum|özel olarak|tercih|keyif|"
                       r"konfor|güvenilir|ideal|hassasiyet|optimize|önceki model|kategorisinde|üst seviye|denye|viskoz|"
                       r"uyumlu sadece|"
                       r"[:/●•*]| - ", re.I)
_BAD_CASE = re.compile(r"[a-zçğıöşü][A-ZÇĞİÖŞÜ]{2}|\b[A-ZÇĞİÖŞÜ]{2}[a-zçğıöşü]| ,")
_VERB_END = re.compile(r"(d[ıiuü]r|t[ıiuü]r|yor|[ıiuü]l[ıiuü]r|[ıiuü]n[ıiuü]r|abilir|ebilir|sağlar|sunar|korur)\.$")


def description(p: dict, limit: int = 300) -> str:
    """Site açıklamasından yalnız tam cümleler; kesik, liste ya da iddia içeren cümleler alınmaz."""
    d = fix_text((p.get("description") or "").strip())
    if not d:
        return ""
    name_l = tr_lower(display_name(p))
    out, total = [], 0
    for s in re.findall(r"[^.!?…]+[.!?]", d):
        words = s.strip().split(" ")
        while len(words) > 1 and len(words[0]) > 1 and not any(ch.islower() for ch in words[0]):  # baştaki BÜYÜK ad
            words.pop(0)
        s = " ".join(words)
        if tr_lower(s).startswith(name_l + " ") and len(s) > len(name_l) + 35:   # cümle ürün adıyla başlıyorsa ad atılır
            s = s[len(name_l):].strip()
            s = s[:1].translate(TR_UPPER).upper() + s[1:]
        letters = [ch for ch in s if ch.isalpha()]
        if len(s) < 35 or not s[0].isupper() or _BAD_SENT.search(s) or _BAD_CASE.search(s) or not letters:
            continue
        if not _VERB_END.search(s):      # yüklemle biten tam cümle değil
            continue
        if sum(ch.isupper() for ch in letters) / len(letters) > 0.3 or tr_lower(s.rstrip(".")) == name_l:
            continue
        if total + len(s) > limit:
            break
        out.append(s)
        total += len(s) + 1
    return " ".join(out)


# ---- Gerçek avantajlar (data/site.json: kargo, iade, garanti) --------------------------------------

def perks(p: dict | None = None) -> list[tuple[str, str, str]]:
    """(simge, başlık, alt satır). Hepsi sitedeki kargo/iade sayfalarında yazan koşullardır."""
    used = bool(p) and p.get("category") == "2. El Bisiklet"
    out = [("truck", "Köyceğiz içi aynı gün", "Teslimat ücretsiz"),
           ("send", "Türkiye geneli kargo", "3.000 ₺ ve üzeri siparişte ücretsiz"),
           ("return", "14 gün içinde iade", "İade kargosu bizden")]
    out.append(("pin", "Mağazada gör", "Köyceğiz'de, Pazar hariç her gün") if used else
               ("shield", "2 yıl yasal garanti", "Teslimden itibaren"))
    return out


PERK_LINES = ["Köyceğiz içi aynı gün, ücretsiz teslimat", "Türkiye geneli kargo; 3.000 ₺ ve üzeri siparişte ücretsiz",
              "14 gün içinde iade, iade kargosu bizden"]


# ---- UTM -----------------------------------------------------------------------------------------

def utm(url: str, medium: str, campaign: str, content: str) -> str:
    """utm_source=instagram&utm_medium=social|story|bio&utm_campaign=<tema>&utm_content=<id>"""
    base, _, frag = url.partition("#")
    q = urlencode({"utm_source": "instagram", "utm_medium": medium, "utm_campaign": campaign, "utm_content": content})
    return f"{base}{'&' if '?' in base else '?'}{q}" + (f"#{frag}" if frag else "")


def utm_ok(link: str, medium: str, campaign: str, content: str) -> bool:
    return all(f"{k}={v}" in link for k, v in (("utm_source", "instagram"), ("utm_medium", medium),
                                               ("utm_campaign", campaign), ("utm_content", content)))


# ---- Açıklama metni ------------------------------------------------------------------------------

# O9: #bisiklet ve #nitrobisiklet çıktı. Set: #köyceğiz + dönüşümlü bölge etiketi + 3 konu etiketi = 5.
# Bölge etiketi yalnız etikettir; açıklamada o bölgeye özel hizmet iddiası yazılmaz.
BASE_TAGS = ["#köyceğiz"]
BOLGE_TAGS = ["#muğla", "#dalyan", "#ortaca", "#marmaris", "#fethiye"]
YASAK_TAGS = {"#bisiklet", "#nitrobisiklet"}
KONU_YEDEK = {"bisiklet_performans": "#bisikletsevenler", "bisiklet_gunluk": "#bisikletlehayat",
              "parca": "#bisikletparçası", "aksesuar": "#bisikletaksesuarı", "giyim": "#bisikletekipmanı"}
KONU_GENEL = ["#bisikletsevenler", "#bisikletbakımı", "#bisikletlehayat", "#bisikletaksesuarı"]
SEO_LINE = "📍 NITRO Bisiklet · Köyceğiz / Muğla · bisiklet satış ve servis"
CAPTION_MAX, FIRST_LINE_MAX, TAG_MAX = 2200, 125, 5
TEKRAR_GUN = 30   # aynı kanca / soru bu kadar gün içinde (önce ya da sonra) tekrar etmez


def bolge_tag(gun: str | None = None, *seed) -> str:
    """Tarihe göre dönüşümlü (ardışık günler farklı bölge); tarih yoksa tohumdan."""
    d = _gun(gun)
    return BOLGE_TAGS[d.toordinal() % len(BOLGE_TAGS)] if d else pick(BOLGE_TAGS, gun, *seed)


def tags_for(extra: list[str], gun: str | None = None, grup: str | None = None) -> str:
    """#köyceğiz + bölge + 3 konu etiketi (önce verilenler, eksik kalırsa grup / genel yedek)."""
    konu = [t for t in dict.fromkeys(list(extra) + [KONU_YEDEK.get(grup or "", "")] + KONU_GENEL)
            if t and t not in YASAK_TAGS and t not in BASE_TAGS and t not in BOLGE_TAGS]
    return " ".join(BASE_TAGS + [bolge_tag(gun, *extra)] + konu[:TAG_MAX - len(BASE_TAGS) - 1])


def how_to_buy(q: str | None = None) -> str:
    """Profil linki nitrobisiklet.com; sitenin araması ürün adında alt dize arar (N-kodlarını tanımaz).
    q: scripts/arama.py'nin canlı sitede doğruladığı, ürünü tek başına bulan terim.
    Zamandan bağımsız: CTA satırında "en üstte" / "bugün" yok (denetim.py yakalar)."""
    if q:
        return f"🛒 Nasıl alırım? Profildeki linke dokun: nitrobisiklet.com → 🔍 aramaya “{q}” yaz."
    return "🛒 Nasıl alırım? Profildeki linke dokun: nitrobisiklet.com → 🔍 aramaya ürünün yanındaki terimi yaz."


CTA_YASAK = re.compile(r"en üstte|bugün", re.I)
# Güven bilgisi başlıklı, maddeler ayrı satırda (tek satıra " · " ile sıkıştırılınca okunmuyordu, 26 Kasım).
GUVEN = ["Neden NITRO?"] + [f"✔️ {x}" for x in PERK_LINES]

# Türe göre tek çağrı (etkileşim yemi yok): rehber/ipucu "kaydet", ürün/hediye "gönder".
KAYDET = ["📌 Kaydet, servise gelmeden bak.", "📌 Kaydet; bir sonraki bakımda işine yarar.",
          "📌 Kaydet, sürüşten önce bir daha bak."]
GONDER = ["📤 Bunu soracak birine gönder.", "📤 Arayan birini biliyorsan ona gönder.",
          "📤 Birlikte sürdüğün birine gönder."]
GONDER_HEDIYE = ["📤 Hediye alacağın kişiye gönder.", "📤 Hediye arayan birine gönder.",
                 "📤 Listeyi hediye alacak birine gönder."]


# ---- Soru / kanca yardımcıları (denetim.py de kullanır) -------------------------------------------

_SORU_EKI = re.compile(r"m[ıiuü](?:s[ıiuü]n(?:[ıiuü]z)?|y[ıiuü][mz]|yd[ıiuü](?:[mkn]|n[ıiuü]z)?|d[ıiuü]r)?")


def ilk_satir(cap: str) -> str:
    return (cap or "").strip().split("\n", 1)[0].strip()


def sorular(cap: str) -> list[str]:
    """Açıklamada "?" ile biten satırlar."""
    return [x.strip() for x in (cap or "").split("\n") if x.strip().endswith("?")]


def soru_satiri(cap: str, n: int = 3) -> str:
    """İlk n (boş olmayan) satırdaki ilk soru; yoksa ""."""
    satirlar = [x.strip() for x in (cap or "").strip().split("\n") if x.strip()][:n]
    return next((x for x in satirlar if x.endswith("?")), "")


def soru_ekleri(s: str) -> int:
    """Soru eki (mı/mi/mu/mü, mısın, mıydı...) sayısı."""
    return sum(1 for w in tr_lower(s).split() if _SORU_EKI.fullmatch(w.strip(".,;:!?…\"“”'")))


def iki_secenekli(s: str) -> bool:
    """"X mı, Y mı?" ya da "..., yoksa ...?" biçimi."""
    return s.strip().endswith("?") and (soru_ekleri(s) >= 2 or "yoksa" in tr_lower(s).split())


def evet_hayir(s: str) -> bool:
    """Tek soru ekli, seçeneksiz soru ("Denedin mi?", "Sürüyor musun?")."""
    return s.strip().endswith("?") and soru_ekleri(s) == 1 and "yoksa" not in tr_lower(s).split()


def _gun(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


_URETILEN: dict[str, tuple[str, str]] = {}   # bu çalışmada üretilen post açıklamaları: tarih -> (ilk satır, soru)
_TAKVIM: list[dict] | None = None


def _takvim(onceki: list[dict] | None) -> list[dict]:
    global _TAKVIM
    if onceki is not None:
        return onceki
    if _TAKVIM is None:
        try:
            import common
            _TAKVIM = common.load_calendar()
        except Exception:
            _TAKVIM = []
    return _TAKVIM


def kullanilan(gun: str | None, onceki: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """±TEKRAR_GUN gün içindeki (aynı gün hariç) postların ilk satırları ve soruları.
    onceki: plan.py'nin takvimi; verilmezse data/calendar.json. Bu çalışmada yeniden üretilenler takvimdeki eskisinin yerine geçer."""
    g = _gun(gun)
    if g is None:
        return [], []
    yakin = lambda d: d is not None and d != g and abs((d - g).days) < TEKRAR_GUN
    ilkler, sorus = [], []
    for c in _takvim(onceki):
        if c.get("type") != "post" or c.get("status") not in ("planned", "draft", "published"):
            continue
        if not yakin(_gun(c.get("date"))):
            continue
        # yeniden üretilen kaydın eskisi sayılmaz; kilitli / yayınlanmış kaydın metni ise değişmez, hep sayılır
        if c.get("date") in _URETILEN and not c.get("suite_scheduled") and c.get("status") != "published":
            continue
        ilkler.append(ilk_satir(c.get("caption") or ""))
        sorus += sorular(c.get("caption") or "")
    for d, (ilk, soru) in _URETILEN.items():
        if yakin(_gun(d)):
            ilkler.append(ilk)
            sorus.append(soru)
    return ilkler, sorus


def _sec(options: list[str], say, *seed, yedek: list[str] | tuple = ()) -> str:
    """En az kullanılan seçenekler arasından pick ile (deterministik) seç. Asıl seçeneklerin hepsi pencerede
    kullanılmışsa yedekler de adaya katılır: yedek yalnız gerektiğinde, asıl seçeneklerin yerine geçmez."""
    n = {o: say(o) for o in options}
    if yedek and min(n.values()) > 0:
        n.update({o: say(o) for o in yedek if o not in n})
    m = min(n.values())
    return pick([o for o in n if n[o] == m], *seed)


def yakin_basliklar(gun: str | None, onceki: list[dict] | None = None) -> list[str]:
    """±TEKRAR_GUN gün içindeki tüm kayıtların (post + story) görsel başlıkları, küçük harfle."""
    g = _gun(gun)
    if g is None:
        return []
    out = []
    for c in _takvim(onceki):
        d = _gun(c.get("date"))
        if d is None or abs((d - g).days) >= TEKRAR_GUN or c.get("status") not in ("planned", "draft", "published"):
            continue
        t = tr_lower((c.get("title") or "").strip())
        if t:
            out.append(t)
    return out


def kanca_sec(options: list[str], gun: str | None, onceki=None, *seed, yedek=()) -> str:
    """Kanca seçimi: pencerede ilk satır olarak kullanılmış ya da yakın bir görsel başlığıyla aynı sözle
    başlayan kanca geriye düşer (ör. story başlığı “Asfaltın bittiği yerde” iken aynı sözle açılan kanca)."""
    ilkler, _ = kullanilan(gun, onceki)
    # İlk satır kancanın kendisi ya da seo_ilk'in "Konu: kanca" biçimi olabilir: ikisi de kullanılmış sayılır.
    say = lambda h: sum(1 for x in ilkler
                        if x.startswith(h) or tr_lower(x).partition(": ")[2].startswith(tr_lower(h)))
    h = _sec(options, say, gun, *seed, yedek=yedek)
    basliklar = yakin_basliklar(gun, onceki)
    carpar = lambda k: sum(1 for t in basliklar if tr_lower(k).startswith(t))
    if not carpar(h):
        return h   # çakışma yoksa seçim aynen kalır (öteki kayıtların kancası oynamaz)
    return _sec(options, lambda k: say(k) + carpar(k), gun, *seed, yedek=yedek)


def soru_sec(options: list[str], gun: str | None, onceki=None, *seed, yedek=()) -> str:
    _, sorus = kullanilan(gun, onceki)
    return _sec(options, lambda q: sorus.count(q), gun, *seed, yedek=yedek)


def _kaydet(gun: str | None, cap: str) -> None:
    if _gun(gun):
        _URETILEN[str(gun)[:10]] = (ilk_satir(cap), soru_satiri(cap))


OZEL_AD = ("Köyceğiz", "Türkiye", "Muğla", "NITRO")   # cümle içinde de büyük harfle başlar


def cumle_ici(s: str) -> str:
    """Cümle içi söz: ilk harf küçük; BMX gibi kısaltmalar ve özel adlar (Köyceğiz'de) olduğu gibi kalır."""
    return s if s[:2].isupper() or s.startswith(OZEL_AD) else tr_lower(s[:1]) + s[1:]


_kucuk = cumle_ici


def seo_ilk(hook: str, konu: str) -> str:
    """1. satır: kanca; birincil arama kelimesi (konu) kancada yoksa başa "Konu: kanca" olarak gelir, ≤125 karakter.
    Yer adı 1. satıra eklenmez (SEO satırı ve #köyceğiz taşır): kancanın sonuna yapıştırılan
    "Konu: NITRO Bisiklet, Köyceğiz." eki cümleyi bozuyordu (26 Kasım)."""
    h = hook.strip()
    if tr_lower(konu) in tr_lower(h):
        return h
    # Kanca konunun baş adını zaten taşıyorsa ("Lastik basıncı parmakla…") ya da kendi iki noktası varsa
    # önek tekrar ("Bisiklet lastik basıncı: lastik basıncı…") ya da çift iki nokta üretir: kanca tek başına kalır.
    # Baş ad "bisiklet…" ise (Şehir bisikleti) ayırt edici kelime öndedir: kural uygulanmaz.
    bas = tr_lower(konu).split()[-1]
    kok = bas[:max(4, len(bas) - 2)]
    if ":" in h or (not bas.startswith("bisiklet")
                    and any(w.startswith(kok) for w in re.findall(r"\w+", tr_lower(h)))):
        return h
    x = f"{konu}: {cumle_ici(h)}"
    return x if len(x) <= FIRST_LINE_MAX else h


def _join(blocks: list[list[str] | str]) -> str:
    parts = ["\n".join(x for x in b if x) if isinstance(b, list) else b for b in blocks]
    text = "\n\n".join(x for x in parts if x)
    assert len(text) <= CAPTION_MAX, "açıklama 2200 karakteri aşıyor"
    assert len(text.split("\n", 1)[0]) <= FIRST_LINE_MAX, "ilk satır 125 karakteri aşıyor"
    return text


# Kuralın kendi kancaları azsa (30 gün tekrar yasağı) konuya göre kurulan genel kancalar eklenir.
# Yalnız yedek: kuralın kancalarının hepsi pencerede kullanılmışsa devreye girer. "Bu haftanın" gibi zaman
# ifadesi yok (günlük postta "haftanın seçimi" doğru olmaz; "Haftanın bisikleti" ayrı bir yayın).
GENEL_KANCA = ["{Konu} arıyorsan bu modele yakından bak.", "{Konu} seçerken özelliklere bak; bu modelinkiler aşağıda.",
               "{Konu}: özellikleri ve fiyatı aşağıda."]
# Kuralın 3 sorusu pencerede kullanılmışsa (aynı kural 30 günde 4+ kez) yedek ürün soruları; denetim tekrarı yakalar.
GENEL_SORU = ["Bisiklette önce konfor mu gelir, hız mı?", "Hafta içi mi sürersin, hafta sonu mu?",
              "Sürüşe sabah mı çıkarsın, akşam mı?", "Kısa rota mı, uzun rota mı?",
              "Bisikletle yalnız mı sürersin, arkadaşlarla mı?"]


def konu_of(rule: dict) -> str:
    return SEO_AD.get(rule["id"], rule["label"])


def product_caption(p: dict, q: str, rule: dict, day: str, onceki: list[dict] | None = None) -> tuple[str, str]:
    """(açıklama, ilk satır). Paragraflar: kanca (SEO); iki seçenekli soru; ad + fiyat ve 3-4 özellik;
    "Neden NITRO?" güven maddeleri; nasıl alırım + gönder çağrısı; yerel SEO; 5 etiket."""
    konu = konu_of(rule)
    genel = [k.format(Konu=konu, konu=_kucuk(konu)) for k in GENEL_KANCA]
    hook = kanca_sec(list(rule["hooks"]) or genel, day, onceki, p["slug"], yedek=genel)
    soru = soru_sec(rule.get("qs") or [rule["q"]], day, onceki, p["slug"], yedek=GENEL_SORU)
    head = [f"{display_name(p)} · {fmt_price(p['price'])} (KDV dahil)"]
    if p.get("category") == "2. El Bisiklet":
        head.append("Kontrollü 2. el.")
    specs = [f"▪️ {k}: {v}" for k, v in clean_specs(p, 4)]
    ilk = seo_ilk(hook, konu)
    urun = [head + specs] if len(specs) >= 3 else [head, description(p, 280) or specs]
    cap = _join([ilk, soru, *urun, GUVEN, [how_to_buy(q), pick(GONDER, p["slug"], day)], SEO_LINE,
                 tags_for(rule["tags"], day, group_of(p.get("category")))])
    _kaydet(day, cap)
    return cap, ilk


def _liste_id(lst: dict) -> str | None:
    return lst.get("id") or next((k for k, v in LISTS.items() if v["hook"] == lst.get("hook")), None)


def _liste_gunu(lst: dict) -> str | None:
    for x in lst.get("items") or []:
        m = re.search(r"utm_content=(\d{4}-\d{2}-\d{2})", x.get("link") or "")
        if m:
            return m.group(1)
    return None


def list_caption(lst: dict, gun: str | None = None, onceki: list[dict] | None = None) -> tuple[str, str]:
    cfg = LISTS.get(_liste_id(lst) or "", {})
    gun = gun or _liste_gunu(lst)
    hook = lst["hook"]
    soru = soru_sec(cfg.get("qs") or [lst["q"]], gun, onceki, hook)
    ilk = seo_ilk(hook, cfg.get("konu") or "Bisiklet aksesuarı")
    cagri = GONDER_HEDIYE if cfg.get("cagri") == "gonder" else KAYDET
    rows = [f"{i}. {x['name']} · {fmt_price(x['price'])} · 🔍 “{x['q']}”" for i, x in enumerate(lst["items"], 1)]
    cap = _join([ilk, soru, rows, "Fiyatlar KDV dahildir.", GUVEN, [how_to_buy(), pick(cagri, hook, gun)],
                 SEO_LINE, tags_for(lst["tags"], gun, "aksesuar")])
    _kaydet(gun, cap)
    return cap, ilk


IPUCU_KONU = {"kis-bakimi": "Kışın bisiklet bakımı", "cocuk-jant-boyu": "Çocuk bisikleti jant boyu",
              "islak-zemin": "Islak zeminde bisiklet sürüşü", "servis-isaretleri": "Bisiklet servisi",
              "lastik-basinci": "Bisiklet lastik basıncı", "zincir-bakimi": "Bisiklet zincir bakımı",
              "kask-ayari": "Bisiklet kaskı ayarı", "ebike-batarya-kis": "E-bisiklet bataryası"}


def _ipucu_gunu(tip: dict, onceki: list[dict] | None) -> str | None:
    return next((c.get("date") for c in _takvim(onceki)
                 if c.get("type") == "post" and c.get("theme") == "ipucu" and c.get("ref") == tip.get("id")), None)


def tip_caption(tip: dict, gun: str | None = None, onceki: list[dict] | None = None) -> tuple[str, str]:
    """İpucunun 1. paragrafı kanca; kendi kapanış sorusu çıkarılır, yerine iki seçenekli havuz sorusu 2. satıra gelir."""
    paras = [x.strip() for x in tip["caption"].strip().split("\n\n") if x.strip()]
    hook, body = paras[0], paras[1:]
    havuz = list(IPUCU_SORULARI.get(tip.get("id"), IPUCU_GENEL))
    if body and body[-1].endswith("?") and "\n" not in body[-1]:
        son = body.pop()
        if iki_secenekli(son) and son not in havuz:
            havuz.insert(0, son)
    # İpucunun kendi "kaydet" paragrafı varsa çağrı o olur (iki kez "kaydet" yazılmaz)
    kendi = [x for x in body if "\n" not in x and re.search(r"\bkaydet", tr_lower(x))]
    body = [x for x in body if x not in kendi]
    gun = gun or _ipucu_gunu(tip, onceki)
    soru = soru_sec(havuz, gun, onceki, tip.get("id"), yedek=[x for x in IPUCU_GENEL if x not in havuz])
    konu = IPUCU_KONU.get(tip.get("id"), tip.get("kicker", "").capitalize() or "Bisiklet bakımı")
    ilk = seo_ilk(hook, konu)
    cta = ("🔧 Servis randevusu için profildeki linke dokun: “Servis randevusu al”." if tip.get("cta") == "servis"
           else "🚲 Çocuk bisikletleri profildeki linkte; jant boyuna göre seçebilirsin." if tip.get("cta") == "cocuk"
           else "🛒 İhtiyacın olan parça ve aksesuarlar profildeki linkte.")
    ek = {"servis": "#bisikletservisi", "cocuk": "#çocukbisikleti"}.get(tip.get("cta"), "#bisikletsevenler")
    cagri = "📌 " + kendi[-1] if kendi else pick(KAYDET, tip.get("id"), gun)
    cap = _join([ilk, soru] + body + [[cta, cagri], SEO_LINE,
                                        tags_for(["#bisikletbakımı", "#bisikletipuçları", ek], gun)])
    _kaydet(gun, cap)
    return cap, ilk


def newyear_caption(year: int, gun: str | None = None, onceki: list[dict] | None = None) -> tuple[str, str]:
    gun = gun or f"{year - 1}-12-31"
    ilk = f"Mutlu yıllar! {year} bol kilometreli bir yıl olsun. NITRO Bisiklet, Köyceğiz."
    soru = soru_sec(YILBASI_SORULARI, gun, onceki, year)
    cap = _join([ilk, soru, "Bu yıl bizimle süren, dükkâna uğrayan, bisikletini atölyemize emanet eden herkese teşekkürler.",
                 GONDER[2], SEO_LINE, tags_for(["#mutluyıllar", "#bisikletsevenler", "#yılbaşı"], gun)])
    _kaydet(gun, cap)
    return cap, ilk


# ---- Alt metin -----------------------------------------------------------------------------------

def cumle(s: str) -> str:
    """Cümle sonuna nokta koy; zaten . ? ! ile bitiyorsa ikinci noktalama ekleme ("UYAR?." olmaz)."""
    s = s.strip()
    return s if s[-1:] in ".?!…" else s + "."


def product_alt(p: dict, title: str) -> str:
    """Alt metin kategori kelimesiyle başlar (arama SEO'su)."""
    kat = p.get("category") or "Ürün"
    return f"{kat}: {display_name(p)}, {fmt_price(p['price'])}. NITRO Bisiklet ürün görseli: “{plain(title)}”."[:1000]


# ---- Mevsim süzgeci ------------------------------------------------------------------------------

def in_season(text: str, month: int) -> bool:
    """Kışa özgü metin yalnız kış aylarında, sıcak hava metni yalnız yaz aylarında kullanılır."""
    t = tr_lower(text)
    if re.search(r"\bkış|soğuk", t):
        return month in (10, 11, 12, 1, 2, 3)
    if re.search(r"sıcak hava|sıcakta|\byaz(ın|da)\b", t):
        return month in YAZ_AYLARI
    return True


# ---- Listeler: başlıktaki adet ve eşik seçilen ürünlerden hesaplanır ---------------------------------
# slots: (kural, adet). cap: fiyat üst sınırı (dahil değil), floor: alt sınır (dahil).
# qs: iki seçenekli soru havuzu (≥3; q = ilki, plan.py uyumu). konu: 1. satır arama kelimesi. cagri: kaydet | gonder.

LISTS = {
    "kis": {"kicker": "Kışa hazırlık", "need": 4, "want": 5, "cap": None, "floor": None,
            "slots": [("lamba", 1), ("camurluk", 1), ("eldiven_kis", 1), ("zincir_yagi", 1), ("balata", 1),
                      ("dis_lastik", 1)],
            "hook": "Kış geldi diye bisiklet kenara konmaz. Islak ve karanlık günler için liste burada.",
            "q": "Kışın sürmeye devam mı, bahara kadar mola mı?", "tags": ["#kışbisikleti", "#bisikletbakımı", "#bisikletaksesuarı"],
            "qs": ["Kışın sürmeye devam mı, bahara kadar mola mı?", "Kış sürüşünde önce görünürlük mü, konfor mu?",
                   "Islak yolda lastik mi önemli, fren mi?"], "konu": "Kış bisiklet ekipmanı", "cagri": "kaydet"},
    "hediye250": {"kicker": "Hediye rehberi", "need": 4, "want": 5, "cap": 250, "floor": None,
                  "slots": [("matara", 1), ("bandana", 1), ("canta", 1), ("zil", 1), ("ayna", 1), ("elcik", 1),
                            ("matara_kafesi", 1)],
                  "hook": "Bisikletçiye hediye almak pahalı olmak zorunda değil.",
                  "q": "Hediye pratik mi olsun, sürpriz mi?", "tags": ["#hediyefikri", "#yılbaşıhediyesi", "#bisikletaksesuarı"],
                  "qs": ["Hediye pratik mi olsun, sürpriz mi?", "Hediyeyi kendin mi seçersin, listeden mi?",
                         "Küçük bir hediye mi, ortak büyük bir hediye mi?"], "konu": "Bisikletçiye hediye", "cagri": "gonder"},
    "hediye500": {"kicker": "Hediye rehberi", "need": 4, "want": 5, "cap": 500, "floor": 250,
                  "slots": [("eldiven", 1), ("telefon_tutucu", 1), ("kilit", 1), ("pompa", 1), ("km_saati", 1),
                            ("lamba", 1), ("sele", 1)],
                  "hook": "Listendeki bisikletçi için fikirler.",
                  "q": "Hediye sürüşe mi yarasın, bisiklete mi?", "tags": ["#hediyefikri", "#yılbaşıhediyesi", "#bisikletaksesuarı"],
                  "qs": ["Hediye sürüşe mi yarasın, bisiklete mi?", "Hediyeyi kendin mi seçersin, listeden mi?",
                         "Yılbaşı hediyesi kullanışlı mı olsun, eğlenceli mi?"], "konu": "Bisikletçiye yılbaşı hediyesi",
                  "cagri": "gonder"},
    "hediye1000": {"kicker": "Yılbaşı hediyesi", "need": 4, "want": 5, "cap": 1000, "floor": 500,
                   "slots": [("canta", 1), ("km_saati", 1), ("pedal", 1), ("kilit", 1), ("lamba", 1), ("sele", 1),
                             ("telefon_tutucu", 1), ("eldiven_kis", 1), ("eldiven", 1), ("pompa", 1),
                             ("canta", 1)],
                   "hook": "Yılbaşı yaklaşıyor; bisiklet sevene işe yarar hediyeler burada.",
                   "q": "Hediye sürüşe mi yarasın, bisiklete mi?", "tags": ["#yılbaşıhediyesi", "#hediyefikri", "#bisikletaksesuarı"],
                   "qs": ["Hediye sürüşe mi yarasın, bisiklete mi?", "Yılbaşı hediyesi kullanışlı mı olsun, şık mı?",
                          "Hediyeyi paketletir misin, elden mi verirsin?"], "konu": "Bisikletçiye yılbaşı hediyesi",
                   "cagri": "gonder"},
    "cocuk": {"kicker": "Yılbaşı hediyesi", "need": 4, "want": 6, "cap": None, "floor": None,
              "slots": [("cocuk", 2), ("kask_cocuk", 1), ("eldiven_cocuk", 1), ("zil_cocuk", 1), ("sele_cocuk", 1)],
              "hook": "Yılbaşında bir çocuğu en çok ne sevindirir? Bizce cevap belli.",
              "q": "Çocuğa ilk bisiklet mi, ilk kask mı?", "tags": ["#çocukbisikleti", "#yılbaşıhediyesi", "#hediyefikri"],
              "qs": ["Çocuğa ilk bisiklet mi, ilk kask mı?", "Hediye paketi bisikletli mi olsun, aksesuarlı mı?",
                     "Çocuğun yılbaşında bisiklet mi ister, oyuncak mı?"], "konu": "Çocuk bisikleti", "cagri": "gonder"},
    "yukseltme": {"kicker": "Yükseltme rehberi", "need": 4, "want": 5, "cap": None, "floor": None,
                  "slots": [("pedal", 1), ("elcik", 1), ("sele", 1), ("dis_lastik", 1), ("gidon", 1), ("rotor", 1)],
                  "hook": "Yeni yıla yeni bisiklet şart değil; birkaç parça da sürüşü değiştirir.",
                  "q": "Önce sele mi değişir, pedal mı?", "tags": ["#bisikletparçası", "#bisikletbakımı", "#bisikletsevenler"],
                  "qs": ["Önce sele mi değişir, pedal mı?", "Yükseltmede konfor mu önce, performans mı?",
                         "Yeni parçayı kendin mi takarsın, atölyede mi taktırırsın?"], "konu": "Bisiklet parçası",
                  "cagri": "kaydet"},
}


def _int_tl(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def list_title(list_id: str, items: list[dict]) -> str:
    """Liste başlığı. Adet = ürün sayısı; eşik yalnız TÜM ürünler eşiğin altındaysa yazılır (değilse ValueError)."""
    n, cap = len(items), LISTS[list_id]["cap"]
    if n < LISTS[list_id]["need"]:
        raise ValueError(f"{list_id}: liste için yeterli ürün yok ({n})")
    if cap is not None and not all(x["price"] < cap for x in items):
        raise ValueError(f"{list_id}: eşik ({cap}) sağlanmıyor")
    if list_id == "kis":
        return f"Kışa hazırlayan <em>{n} ürün</em>"
    if list_id.startswith("hediye"):
        return f"{_int_tl(cap)} ₺ altı <em>{n} hediye</em>"
    if list_id == "cocuk":
        return f"Çocuklara <em>{n} yılbaşı hediyesi</em>"
    if list_id == "yukseltme":
        return f"Bisikletine <em>{n} yükseltme</em>"
    raise ValueError(list_id)


def list_sub(list_id: str, items: list[dict]) -> str:
    """Kapak alt satırı; fiyat aralığı ürünlerden hesaplanır."""
    lo, hi = min(x["price"] for x in items), max(x["price"] for x in items)
    rng = f"{fmt_price(lo)} – {fmt_price(hi)}" if lo != hi else fmt_price(lo)
    if list_id.startswith("hediye"):
        return f"Fiyatlar {rng} arasında."
    labels = list(dict.fromkeys(x["label"] for x in items))[:5]
    labels = labels[:1] + [tr_lower(s[:1]) + s[1:] for s in labels[1:]]
    return (", ".join(labels) + ".")[:110]


def build_list(list_id: str, pool: list[dict], ok) -> list[dict] | None:
    """Listeye girecek ürünleri seç. pool: uygun ürünler; ok(p): ürün kullanılabilir mi (tekrar penceresi, görsel).

    Her kuraldan istenen adet kadar, aile başına tek ürün alınır. Yeterli ürün yoksa None (içerik üretilmez).
    """
    cfg = LISTS[list_id]
    chosen, fams = [], set()
    for rid, count in cfg["slots"]:
        if len(chosen) >= cfg["want"]:
            break
        cands = [p for p in pool if (r := rule_of(p)) and r["id"] == rid
                 and (cfg["cap"] is None or p["price"] < cfg["cap"])
                 and (cfg["floor"] is None or p["price"] >= cfg["floor"])]
        cands.sort(key=lambda p: (-len(p.get("images") or []), p["price"], p["slug"]))
        got = 0
        for p in cands:
            if got >= count or len(chosen) >= cfg["want"]:
                break
            f = family(p)
            if f in fams or not ok(p):
                continue
            fams.add(f)
            chosen.append(p)
            got += 1
    return chosen if len(chosen) >= cfg["need"] else None


# ---- Değer story'leri: servis ve marka (data/site.json gerçekleri) ---------------------------------

def service_facts(site: dict) -> list[dict]:
    """Servis story çeşitleri. Paket adları, fiyatları ve süreleri sitedeki servis sayfasından okunur."""
    items = (site.get("service") or {}).get("items") or []
    out = []
    if len(items) >= 3:
        out.append({"kicker": "Servis paketleri", "title": "Bisikletine <em>bakım zamanı</em>",
                    "facts": [("tool", it["name"], f"{it['price']} · {it['duration']}") for it in items[:3]]})
    out.append({"kicker": "Atölyede süreç", "title": "Sürpriz <em>kalem yok</em>",
                "facts": [("clock", "Randevunu sen seç", "Günü ve saati online belirle"),
                          ("check", "Onaysız parça değişmez", "Ek iş çıkarsa önce sana sorulur"),
                          ("search", "Fişini canlı takip et", "Fiş numaranla durumu gör")]})
    out.append({"kicker": "Servis randevusu", "title": "Randevunu <em>online al</em>",
                "facts": [("clock", "Gün ve saat senden", "Tezgâh o saat senin"),
                          ("tool", "Teşhis fişe yazılır", "Çıkan her şeyi görürsün"),
                          ("check", "Dökümüyle teslim", "Yapılan iş kalem kalem")]})
    return out


def brand_facts(site: dict) -> list[dict]:
    """Marka story çeşitleri: hikâye, takım, kargo, mağaza, iade. Hepsi sitede yazan bilgilerdir."""
    hours = site.get("hours") or ""
    out = [
        {"kicker": "Bizi tanı", "title": "Dükkânı <em>pistte öğrendik</em>",
         "facts": [("pin", "2021'den beri", "Köyceğiz, Ölemez Dağı etekleri"),
                   ("tool", "Satış ve servis", "İkisi tek çatı altında"),
                   ("shield", "Yarışan bir kurucu", "Enduro ve downhill")]},
        {"kicker": "NITRO BIKE TEAM", "title": "Yarışlarda artık <em>takımız</em>",
         "facts": [("check", "6 takım sürücüsü", "Enduro ve downhill"),
                   ("shield", "2026'da kuruldu", "NITRO BIKE TEAM"),
                   ("pin", "Köyceğiz'den", "Yarış pistlerine")]},
        {"kicker": "Kargo ve teslimat", "title": "Siparişin <em>nasıl gelir?</em>",
         "facts": [("truck", "Köyceğiz içi aynı gün", "Teslimat ücretsiz"),
                   ("send", "Türkiye geneli kargo", "3.000 ₺ ve üzeri siparişte ücretsiz"),
                   ("pin", "Mağazadan teslim", "Ücretsiz")]},
        {"kicker": "İade ve garanti", "title": "İçin <em>rahat olsun</em>",
         "facts": [("return", "14 gün içinde iade", "Sebep belirtmeden"),
                   ("truck", "İade kargosu bizden", "Yurtiçi Kargo ile"),
                   ("shield", "2 yıl yasal garanti", "Teslimden itibaren")]},
    ]
    if "08:30" in hours and "Pazar kapalı" in hours:
        out.insert(3, {"kicker": "Mağaza", "title": "Dükkâna <em>uğra</em>",
                       "facts": [("pin", "Köyceğiz / Muğla", "Fevzi Paşa Cd. No:73/B"),
                                 ("clock", "08:30 – 19:00", "Pazartesi – Cumartesi"),
                                 ("phone", site.get("phone") or "Telefon", "Ara ya da WhatsApp'tan yaz")]})
    return out
