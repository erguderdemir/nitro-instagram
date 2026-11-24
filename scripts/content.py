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
CAT_LABEL = {"BMX/Dirtjump": "BMX / DIRT JUMP", "Outlet": "OUTLET"}

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
             "RELEASE", "PREMIUM", "LINKGLIDE", "BIKE", "CITY", "TRAIL", "DIRT", "LIGHT", "MINI", "PRIME", "SPRINT"}
# Sitedeki yazım hataları (Türkçe küçük harfe çevrilmiş yabancı adlar)
FIXES = (("Shımano", "Shimano"), ("SHİMANO", "SHIMANO"), ("Premıum", "Premium"), ("Iç Lastik", "İç Lastik"), ("Gıneyea", "Gineyea"), ("Slikon", "Silikon"), ("Solusyonsuz", "Solüsyonsuz"),
         ("Bisiklet&Kayak&Cross", "Bisiklet & Kayak & Cross"))
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


def excluded(p: dict) -> bool:
    return bool(HARIC.search(tr_lower(p.get("name") or "")))


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
        "Sıfır şart değil. Bu bisiklet kontrollü 2. el."],
       "Senin ilk bisikletin sıfır mıydı, 2. el mi?", ["#ikincielbisiklet", "#bisikletsevenler"]),
    _r("ebike", "Elektrikli bisiklet", ["Elektrikli Bisiklet"],
       ["Pedalına <em>güç kat</em>", "Elektrik <em>desteğiyle</em> sür", "Daha uzağa, <em>daha rahat</em>"],
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
       ["Mataran <em>elinin altında</em>", "Mataraya <em>sağlam yuva</em>"],
       ["Matara çantada değil, kadroda dursun.", "Su elinin altında olunca daha sık içersin."],
       "Mataran kadroda mı durur, çantada mı?", ["#matarakafesi", "#bisikletaksesuarı"], inc="kafes|tutucu"),
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
    _r("ic_lastik", "İç lastik", ["İç Lastik"], ["Yedek iç lastik <em>yanında mı?</em>", "Patlak <em>yolda bırakmasın</em>"],
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
    _r("kaset", "Kaset dişli", ["Vites Grubu"], ["Kasetini <em>yenile</em>", "Arka dişlini <em>yenile</em>"],
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
       ["Patlak <em>sürüşü bitirmesin</em>", "Tamir kitin <em>yanında olsun</em>"],
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

# ---- Havuzlar: hangi yayın türü hangi kurallardan ürün seçer ------------------------------------------
POOLS = {
    "performans": ["dag", "gravel", "ebike", "bmx"],                       # Pzt reel: Haftanın bisikleti
    "gunluk": ["sehir", "cocuk", "ebike"],                                 # Cum reel
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
        if "/" in v and re.search(r"[a-z]{4,}\s*/\s*[A-Za-z]{4,}|/[a-z]+ [a-z]+", v):   # çift dilli değer: Türkçesi
            v = v.split("/")[0].strip()
        out[k] = v
    rows = [(k, out[k]) for k in SPEC_ORDER if k in out]
    if "Kadro Malzemesi" in out:     # aynı bilgiyi iki kez gösterme
        rows = [(k, v) for k, v in rows if k != "Kadro"]
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

BASE_TAGS = ["#nitrobisiklet", "#köyceğiz", "#bisiklet"]
SEO_LINE = "📍 NITRO Bisiklet · Köyceğiz / Muğla · bisiklet satış ve servis"
CAPTION_MAX, FIRST_LINE_MAX, TAG_MAX = 2200, 125, 5


def tags_for(extra: list[str]) -> str:
    return " ".join(list(dict.fromkeys(BASE_TAGS + list(extra)))[:TAG_MAX])


def how_to_buy(code: str | None = None) -> str:
    if code:
        return f"🛒 Nasıl alırım? Profildeki linke dokun, arama kutusuna {code} yaz."
    return "🛒 Nasıl alırım? Profildeki linke dokun, arama kutusuna ürün kodunu yaz."


def _join(blocks: list[list[str] | str]) -> str:
    parts = ["\n".join(b) if isinstance(b, list) else b for b in blocks]
    text = "\n\n".join(x for x in parts if x)
    assert len(text) <= CAPTION_MAX, "açıklama 2200 karakteri aşıyor"
    assert len(text.split("\n", 1)[0]) <= FIRST_LINE_MAX, "ilk satır 125 karakteri aşıyor"
    return text


def product_caption(p: dict, code: str, rule: dict, day: str) -> tuple[str, str]:
    """(açıklama, kanca). İlk satır kanca; ad + fiyat; 3-4 özellik; gerçek avantajlar; nasıl alırım; soru; yerel SEO."""
    hook = pick(rule["hooks"], p["slug"], day)
    head = [f"{display_name(p)} · {fmt_price(p['price'])} (KDV dahil)"]
    if p.get("category") == "2. El Bisiklet":
        head.append("Kontrollü 2. el.")
    specs = [f"▪️ {k}: {v}" for k, v in clean_specs(p, 4)]
    body = specs if len(specs) >= 3 else (description(p, 280) or specs)
    return _join([hook, head, body, ["Neden NITRO?"] + [f"✔️ {x}" for x in PERK_LINES], how_to_buy(code),
                  rule["q"], SEO_LINE, tags_for(rule["tags"])]), hook


def list_caption(lst: dict) -> tuple[str, str]:
    hook = lst["hook"]
    rows = [f"{i}. {x['name']} · {fmt_price(x['price'])} · Kod {x['code']}" for i, x in enumerate(lst["items"], 1)]
    return _join([hook, rows, ["Fiyatlar KDV dahildir."] + [f"✔️ {x}" for x in PERK_LINES], how_to_buy(),
                  lst["q"], SEO_LINE, tags_for(lst["tags"])]), hook


def tip_caption(tip: dict) -> tuple[str, str]:
    text = tip["caption"].strip()
    cta = ("🔧 Servis randevusu için profildeki linke dokun: “Servis randevusu al”." if tip.get("cta") == "servis"
           else "🛒 İhtiyacın olan parça ve aksesuarlar profildeki linkte.")
    return _join([text, cta, SEO_LINE, tags_for(["#bisikletbakımı", "#bisikletipuçları"])]), text.split("\n", 1)[0]


def newyear_caption(year: int) -> tuple[str, str]:
    hook = f"Mutlu yıllar! {year} bol kilometreli bir yıl olsun."
    return _join([hook, "Bu yıl bizimle süren, dükkâna uğrayan, bisikletini atölyemize emanet eden herkese teşekkürler.",
                  "Yeni yılda ilk rotan neresi olacak?", SEO_LINE, tags_for(["#mutluyıllar", "#bisikletsevenler"])]), hook


# ---- Alt metin -----------------------------------------------------------------------------------

def product_alt(p: dict, title: str) -> str:
    return f"{display_name(p)}, {fmt_price(p['price'])}. NITRO Bisiklet ürün görseli: “{plain(title)}”."[:1000]


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

LISTS = {
    "kis": {"kicker": "Kışa hazırlık", "need": 4, "want": 5, "cap": None, "floor": None,
            "slots": [("lamba", 1), ("camurluk", 1), ("eldiven_kis", 1), ("zincir_yagi", 1), ("balata", 1),
                      ("dis_lastik", 1)],
            "hook": "Kış geldi diye bisiklet kenara konmaz. Islak ve karanlık günler için liste burada.",
            "q": "Sen kışın sürmeye devam ediyor musun?", "tags": ["#kışbisikleti", "#bisikletbakımı"]},
    "hediye250": {"kicker": "Hediye rehberi", "need": 4, "want": 5, "cap": 250, "floor": None,
                  "slots": [("matara", 1), ("bandana", 1), ("canta", 1), ("zil", 1), ("ayna", 1), ("elcik", 1),
                            ("matara_kafesi", 1)],
                  "hook": "Bisikletçiye hediye almak pahalı olmak zorunda değil.",
                  "q": "Sana bisikletle ilgili alınan en güzel hediye neydi?", "tags": ["#hediyefikri", "#yılbaşıhediyesi"]},
    "hediye500": {"kicker": "Hediye rehberi", "need": 4, "want": 5, "cap": 500, "floor": 250,
                  "slots": [("eldiven", 1), ("telefon_tutucu", 1), ("kilit", 1), ("pompa", 1), ("km_saati", 1),
                            ("lamba", 1), ("sele", 1)],
                  "hook": "Yılbaşı listesindeki bisikletçi için fikirler.",
                  "q": "Bu listeden hangisi senin bisikletinde eksik?", "tags": ["#hediyefikri", "#yılbaşıhediyesi"]},
    "cocuk": {"kicker": "Yılbaşı hediyesi", "need": 4, "want": 6, "cap": None, "floor": None,
              "slots": [("cocuk", 2), ("kask_cocuk", 1), ("eldiven_cocuk", 1), ("zil_cocuk", 1), ("sele_cocuk", 1)],
              "hook": "Yılbaşında bir çocuğu en çok ne sevindirir? Bizce cevap belli.",
              "q": "Senin ilk bisikletin kaç janttı, hatırlıyor musun?", "tags": ["#çocukbisikleti", "#yılbaşıhediyesi"]},
    "yukseltme": {"kicker": "Yükseltme rehberi", "need": 4, "want": 5, "cap": None, "floor": None,
                  "slots": [("pedal", 1), ("elcik", 1), ("sele", 1), ("dis_lastik", 1), ("gidon", 1), ("rotor", 1)],
                  "hook": "Yeni yıla yeni bisiklet şart değil; birkaç parça da sürüşü değiştirir.",
                  "q": "Bisikletinde ilk değiştirdiğin parça neydi?", "tags": ["#bisikletparçası", "#bisikletbakımı"]},
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
    if list_id in ("hediye250", "hediye500"):
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
    if list_id in ("hediye250", "hediye500"):
        return f"Fiyatlar {rng} arasında. Hepsinin kodu görselde."
    labels = list(dict.fromkeys(x["label"] for x in items))
    return (", ".join(labels[:5]) + ".")[:110]


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
        {"kicker": "NITRO BIKE TEAM", "title": "Yarışlarda <em>takım olarak</em>",
         "facts": [("check", "6 takım sürücüsü", "Enduro · downhill"),
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
