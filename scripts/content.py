"""Ürün grupları, kancalar (hook), açıklama ve hashtag üretimi.

Metinler yalnızca sitede görünen bilgilere dayanır: fiyat, teknik döküm, kargo/iade koşulları.
Olmayan indirim, stok veya kampanya iddiası üretmez.
"""
import hashlib
from urllib.parse import urlencode

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
BIKE_GROUPS = ("bisiklet_performans", "bisiklet_gunluk")

# Ay -> öne çıkarılacak kategoriler (sezon ağırlığı)
SEASONAL = {
    11: ["Aydınlatma ve Reflektör", "Çamurluk ve Muhafaza", "Eldiven", "İç Lastik", "Dış Lastik", "Kimyasal", "Kilit", "Pompa"],
    12: ["Çocuk Bisikleti", "Kask", "Km Saati", "Telefon Tutucu", "Gözlük", "Aydınlatma ve Reflektör", "Eldiven", "Çamurluk ve Muhafaza"],
    1: ["Aydınlatma ve Reflektör", "Çamurluk ve Muhafaza", "Eldiven", "Kimyasal", "Atölye ve Tamir", "Balatalar & Pabuçlar"],
    2: ["Vites Grubu", "Fren Grubu", "Balatalar & Pabuçlar", "Kimyasal", "Dış Lastik", "Zincir"],
    3: ["Dış Lastik", "Vites Grubu", "Sele Grubu", "Matara ve Kafes", "Km Saati", "Kask"],
    4: ["Kask", "Gözlük", "Matara ve Kafes", "Çanta ve Sepet", "Forma", "Telefon Tutucu"],
    5: ["Gözlük", "Matara ve Kafes", "Forma", "Bandana", "Çanta ve Sepet", "Taşıyıcı ve Bagaj"],
    6: ["Gözlük", "Matara ve Kafes", "Bandana", "Forma", "Taşıyıcı ve Bagaj", "Kask"],
    7: ["Gözlük", "Matara ve Kafes", "Bandana", "Forma", "Kask", "Çanta ve Sepet"],
    8: ["Matara ve Kafes", "Gözlük", "Taşıyıcı ve Bagaj", "Çocuk Bisikleti", "Kilit", "Kask"],
    9: ["Çocuk Bisikleti", "Kilit", "Çanta ve Sepet", "Kask", "Aydınlatma ve Reflektör", "Zil, Korna, Ayna"],
    10: ["Aydınlatma ve Reflektör", "Çamurluk ve Muhafaza", "Dış Lastik", "Eldiven", "Kimyasal", "Pantolon"],
}


def group_of(cat: str | None) -> str:
    for g, cats in GROUPS.items():
        if cat in cats:
            return g
    return "aksesuar"


# ---- Kancalar --------------------------------------------------------------------------------
# post: açıklamanın ilk satırı · story: (kicker, başlık; <em> turuncu vurgu)
HOOKS = {
    "bisiklet_performans": {
        "post": ["Patikada fark yaratan detaylar burada. 🏔️",
                 "Bu hafta vitrinde: yokuşu sevdiren bir makine.",
                 "Köyceğiz'in tepeleri seni bekliyor, bisikletin hazır.",
                 "Hafta sonu rotanı çiz, gerisini bu bisiklete bırak.",
                 "Doğru bisiklet, sürüşün yarısıdır."],
        "story": [("HAFTANIN BİSİKLETİ", "Patikaya <em>hazır</em> mısın?"),
                  ("YENİ SEZON", "Yokuşlar <em>artık</em> kolay"),
                  ("NITRO SEÇKİSİ", "Rotanı <em>büyüt</em>"),
                  ("VİTRİNDE", "Bir sonraki <em>macera</em> burada")],
    },
    "bisiklet_gunluk": {
        "post": ["Her güne bir pedal: şehirde pratik, keyifli sürüş. 🚲",
                 "İşe, okula, sahile... Tek bisiklet, her yere.",
                 "Arabayı park et, keyfi pedalla.",
                 "Ailenin yeni sürüş arkadaşı vitrinde."],
        "story": [("GÜNLÜK SÜRÜŞ", "Şehirde <em>özgürlük</em>"),
                  ("VİTRİNDE", "Her güne bir <em>pedal</em>"),
                  ("NITRO SEÇKİSİ", "Sürüşe <em>hazır</em>"),
                  ("AİLECE", "Yeni sürüş <em>arkadaşı</em>")],
    },
    "parca": {
        "post": ["Bisikletin ilk günkü gibi çalışsın. 🔧",
                 "Küçük parça, büyük fark.",
                 "Yıpranan parçayı değiştir, sürüş keyfini geri al.",
                 "Aradığın yedek parça stokta, kargoya hazır.",
                 "Montaj için servis randevunu online alabilirsin."],
        "story": [("YEDEK PARÇA", "Küçük parça, <em>büyük</em> fark"),
                  ("ATÖLYEDEN", "İlk günkü <em>gibi</em>"),
                  ("BAKIM ZAMANI", "Sürüşünü <em>yenile</em>"),
                  ("STOKTA", "Aradığın <em>parça</em> burada")],
    },
    "aksesuar": {
        "post": ["Sürüşü kolaylaştıran küçük dokunuşlar. ✨",
                 "Bisikletine yakışacak bir ekleme.",
                 "Her sürüşte işine yarayacak.",
                 "Hediye arayanlar için pratik bir seçenek. 🎁",
                 "Eksik olan tek şey buydu."],
        "story": [("AKSESUAR", "Küçük ama <em>şart</em>"),
                  ("NITRO SEÇKİSİ", "Sürüşüne <em>ekle</em>"),
                  ("PRATİK", "Her sürüşte <em>yanında</em>"),
                  ("HEDİYE FİKRİ", "Bisikletçiye <em>hediye</em>")],
    },
    "giyim": {
        "post": ["Doğru ekipman, daha uzun ve konforlu sürüş. 🧤",
                 "Rüzgara, soğuğa, güneşe karşı hazırlıklı ol.",
                 "Güvenlik ve konfor bir arada.",
                 "Sürüş tarzını tamamla."],
        "story": [("EKİPMAN", "Hazırlıklı <em>sür</em>"),
                  ("KONFOR", "Uzun yola <em>hazır</em>"),
                  ("GÜVENLİK", "Önce <em>güvenlik</em>")],
    },
}

SPEC_PRIORITY = ["Jant Ölçüsü", "Vites", "Fren Tipi", "Maşa", "Kadro", "Kadro Malzemesi", "Kadro Boyu", "Motor",
                 "Batarya", "Menzil", "Ölçü", "Uyumluluk", "Malzeme", "Renk", "Beden", "Ağırlık"]

BASE_TAGS = ["#nitrobisiklet", "#köyceğiz", "#muğla", "#bisiklet"]
GROUP_TAGS = {
    "bisiklet_performans": ["#dağbisikleti", "#mtb", "#mountainbike", "#bisikletsevenler", "#bisikletturu", "#doğasporları"],
    "bisiklet_gunluk": ["#şehirbisikleti", "#bisikletsevenler", "#bisikletlehayat", "#pedal", "#günlüksürüş"],
    "parca": ["#bisikletparçası", "#bisikletservisi", "#bisikletbakımı", "#yedekparça", "#shimano"],
    "aksesuar": ["#bisikletaksesuarı", "#bisikletsevenler", "#bisikletekipmanı", "#hediyefikri"],
    "giyim": ["#bisikletgiyim", "#bisikletekipmanı", "#bisikletsevenler", "#güvenlisürüş"],
}
CAT_TAGS = {"Elektrikli Bisiklet": ["#elektriklibisiklet", "#ebike"], "Gravel": ["#gravel", "#gravelbike"],
            "Çocuk Bisikleti": ["#çocukbisikleti"], "2. El Bisiklet": ["#ikincielbisiklet"], "Kask": ["#bisikletkaskı"],
            "BMX/Dirtjump": ["#bmx", "#dirtjump"], "Aydınlatma ve Reflektör": ["#bisikletlambası"]}


TR_LOWER = str.maketrans("Iİ", "ıi")
TR_UPPER = str.maketrans("ıi", "Iİ")
KEEP_UPPER = {"MTB", "BMX", "USB", "LED", "LM", "XS", "S", "M", "L", "XL", "XXL", "DH", "XC", "CNC", "MTX", "TRX", "BRI-10"}


def _tr_title(w: str) -> str:
    if w in KEEP_UPPER or any(ch.isdigit() for ch in w):
        return w
    # Türkçe harf içeren kelimede I->ı, yabancı kelimede (HELIX) I->i
    low = w.translate(TR_LOWER).lower() if any(ch in "ŞĞÜÖÇİ" for ch in w) else w.lower()
    return low[:1].translate(TR_UPPER).upper() + low[1:]


def display_name(p: dict) -> str:
    """Büyük harfli adları Türkçe başlık düzenine çevir, uzun stok kodlarını at."""
    import re
    n = re.sub(r"\s+\d{7,}\b", "", p["name"]).strip()
    n = re.sub(r"\s{2,}", " ", n)
    letters = [ch for ch in n if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        n = " ".join(_tr_title(w) for w in n.split(" "))
    return n


COLORS = {"siyah", "beyaz", "kırmızı", "mavi", "yeşil", "gri", "sarı", "turuncu", "mor", "pembe", "lacivert",
          "mat", "parlak", "renkli", "antrasit", "bordo", "kahverengi", "füme", "haki"}


def family(p: dict) -> str:
    """Renk/beden varyantlarını aynı aileye toplar (aynı ürünün renkleri art arda gelmesin)."""
    import re
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ.]+", display_name(p).translate(TR_LOWER).lower())
    words = [w for w in words if w not in COLORS and w not in {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}]
    return " ".join(words[:5])


def pick(options: list, *seed) -> object:
    h = int(hashlib.md5("|".join(map(str, seed)).encode()).hexdigest(), 16)
    return options[h % len(options)]


def fmt_price(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".") + " ₺"


def utm_url(p: dict, medium: str, campaign: str, content: str) -> str:
    q = urlencode({"utm_source": "instagram", "utm_medium": medium, "utm_campaign": campaign, "utm_content": content})
    return f"{p['url']}?{q}"


def bullets(p: dict, n: int = 4) -> list[str]:
    out = [f"{k}: {p['specs'][k]}" for k in SPEC_PRIORITY if k in p["specs"]][:n]
    if len(out) < 2:
        extra = [f"{k}: {v}" for k, v in p["specs"].items() if f"{k}: {v}" not in out and len(v) <= 40]
        out += extra[: n - len(out)]
    return out


def perks(p: dict) -> list[str]:
    g = group_of(p.get("category"))
    out = []
    if g in BIKE_GROUPS:
        out.append("🛠️ Atölyemizde kurulup ayarlanmış teslim")
    out.append("🚚 Köyceğiz içi aynı gün ücretsiz teslim")
    out.append("📦 Türkiye geneli kargo" + (" (ücretsiz)" if p["price"] >= 3000 else " · 3.000 ₺ üzeri ücretsiz"))
    out.append("↩️ 14 gün iade")
    return out


def story_hook(p: dict, day: str, slot: str) -> tuple[str, str]:
    g = group_of(p.get("category"))
    return pick(HOOKS[g]["story"], p["slug"], day, slot)


def caption(p: dict, day: str, campaign: str = "post") -> str:
    g = group_of(p.get("category"))
    hook = pick(HOOKS[g]["post"], p["slug"], day)
    lines = [hook, "", display_name(p)]
    price = f"💰 {fmt_price(p['price'])} (KDV dahil)"
    if p.get("old_price"):
        price = f"💰 {fmt_price(p['old_price'])} yerine {fmt_price(p['price'])} (KDV dahil)"
    lines.append(price)
    if p.get("condition", "").lower().startswith("kontrollü"):
        lines.append("✅ Kontrollü 2. el")
    b = bullets(p)
    if b:
        lines += [""] + [f"▪️ {x}" for x in b]
    elif p.get("description"):
        lines += ["", p["description"][:220].rstrip("…") + "…"]
    lines += [""] + perks(p)
    if p.get("stock_left") and p["stock_left"] <= 3:
        lines.append(f"⚠️ Stokta son {p['stock_left']} adet")
    lines += ["",
              "🛒 Satın almak için profildeki linke dokun: “Instagram’da gördüğün ürünler” listesinde.",
              f"🔗 {p['url'].replace('https://', '')}",
              "📍 Köyceğiz'deki mağazamızda deneyebilirsin. Sorular için DM 💬",
              ""]
    tags = BASE_TAGS + GROUP_TAGS[g] + CAT_TAGS.get(p.get("category"), [])
    lines.append(" ".join(dict.fromkeys(tags)))
    return "\n".join(lines)
