# @nitrobisiklet otomasyonu — durum raporu (24 Kasım 2026)

## Özet
Sistem hazır, yayın KİLİTLİ (`config.json` → `"live": false`). Canlıya geçiş yalnız sahibinin onayıyla açılır.
Simülasyon: https://erguderdemir.github.io/nitro-instagram/onizleme/

## Ne kuruldu
- **Veri:** Ürün, fiyat, stok, görsel ve teknik özellikler nitrobisiklet.com'dan çekilir. Her ürün linki UTM'li.
- **Takvim:** 25 Kasım → 31 Aralık 2026, 148 kayıt.
  - 36 carousel post + 1 görsel (31 Ara yılbaşı).
  - 111 story: günde 3 (09:30 değer, 12:30 günün ürünü, 20:30 günün postunun tanıtımı).
  - Haftalık ritim: Pzt bisiklet, Sal parça/aksesuar, Çar ipucu, Per mevsim, Cum hafta sonu vitrini,
    Cmt liste (kış, 250 ₺ altı hediye, 500 ₺ altı hediye, çocuklara yılbaşı, yükseltme), Paz öneri.
  - Reel kapalı (sahibinin isteği).
- **Görsel üretim:** Ajans şablonları (kapak, galeri, teknik tablo, neden NITRO, CTA, liste, ipucu adımları, story).
- **Yayın:** GitHub Actions (bilgisayar kapalı olsa da çalışır). Instagram Graph API ile post ve story.
  - Link çıkartmalı story'ler API ile konamadığı için Business Suite'e planlanır (`docs/suite/`).
- **Mantık denetimi (`scripts/denetim.py`):** her yayından önce çalışır; bulgu varsa yayın durur.
  - Başlık–ürün uyumu, liste eşikleri (ör. "250 ₺ altı" listesinde her ürün < 250 ₺), ürün sayısı = başlıktaki sayı.
  - Fiyat/stok güncelliği, hariç ürünler, engelli (yanlış) görseller, link/UTM, alt metin, noktalama.

## Doğrulama
- `check`: token geçerli, hesap bağlı, 24 saatte 0/100 kota kullanımı.
- `probe`: carousel (8 medya), görsel ve story container'ları Instagram'da FINISHED; hiçbir şey yayınlanmadı.
- Gerçek ürün fotoğraflarıyla tüm kareler gözle denetlendi. Düzeltilen hatalar:
  - Yanlış renk fotoğrafı (antrasit adlı üründe mavi bisiklet; koyu yeşil üründe açık yeşil kare).
  - Lamba yerine ölçü çizimi/Çince yazılı görsel; sahibinden.com filigranlı ürün fotoğrafları (ürün çıkarıldı).
  - Büyük harfli Türkçe başlıklarda İ/Ş/Ğ'nin üst satıra değmesi.
  - "5 adım" rozeti "5 işaret" başlığında → "madde".
  - İpucu postlarında ürün satın alma çağrısı → "İhtiyacın profildeki linkte".
  - Alt metinde "?." çift noktalama; İngilizce teknik değerler (STEEL, SUSPENSION FORK) → Türkçe.
  - Başlık son satırında Ş/Ç/Ğ alt çengelinin kesilmesi (kapak, ipucu ve soru story başlıkları).
  - Yarım bisiklet yakın çekimi, galeri oku, MOSSO bisikleti ve renkli duvar içeren yanlış ürün kareleri engellendi;
    uygun fotoğrafı olmayan 10 ürün takvimden çıkarıldı, yerine uygun ürün geldi.
  - Teknik tabloda büyük harfli değerler ve birimler (36 V / 10,4 Ah, Karbon, Çelik), "Orjinal" → "Orijinal",
    "Cable Lock" → "Kablo Kilidi", tekrarlanan "Fren Sistemi" satırı.
  - Çocuk jant boyu ipucu artık doğrudan çocuk bisikletleri kategorisine yönlendiriyor (CTA ve story linki).
  - Servis ipucundaki doğrulanamayan "aynı gün servis" iddiası kaldırıldı.
- Sabah değer story'leri (ipucu, bilgi) de konuyla ilgili kategori/ürün linkine çıkartmayla bağlanır.
- İkinci göz denetimi (24 Kasım):
  - Story çıkartma metni kareyle tutarlı: her ürün story'sinde "ÜRÜNE GİT".
  - Ürün adlarında birim ve yazım düzeltmeleri (160 mm, 26x1.95, 34'lü, 16-20 Jant, Maxxis, RockShox, model kodları).
  - Fotoğrafı ürünle uyuşmayan 5 ürün (çok renkli zil, farklı renk eldiven, ölçü çizimi) ve 4 hatalı görsel çıkarıldı.
  - Aynı başlığın farklı günlerde tekrar etmesi engellendi; sayı ile birimi satır sonunda ayrılmıyor.
  - Büyük harfli başlıklarda Ş çengeli ile Ü noktalarının çakışması (satır aralığı) giderildi.
- Denetim sonucu: 0 bulgu.

## Bekleyen (sahibinin onayı)
1. Simülasyonu incele → onay → `live: true`.
2. Onaydan sonra: Business Suite'te link çıkartmalı story planlama ve Öne Çıkanlar (yerel Chrome ile).

## Günlük takip
- Bulut rutini her sabah 08:00 TR'de o günün kayıtlarını denetler, özet verir:
  https://claude.ai/code/routines/trig_01JpWx6k9XF1YtHEQKGa2Xq2
- Yayın bilgisayardan bağımsız. GitHub'ın kendi zamanlayıcısı gecikebildiği için asıl tetik bulut rutinleridir:
  yayın anları (09:31, 12:31, 19:31, 20:31 TR) https://claude.ai/code/routines/trig_01Xykq1LaT2aTbfZwaoWyM5y ,
  gece planı 04:01 + 11:01 TR yayını https://claude.ai/code/routines/trig_01J3bv59HU8my9XdG93nnsj9 ,
  bekçi 2 saatte bir kaçan kayıt arar https://claude.ai/code/routines/trig_01VXidum3KAj3Ghf2Wrk5Dc5 .
  Actions 15 dakikalık cron'u yedektir; geciken kayıt 3 saate kadar telafi edilir, çift yayın olmaz.
- Business Suite'e planlanmamış linkli story de bulutta API yedeğiyle yayınlanır ("Link profilde"); yalnız
  tıklanabilir çıkartma olmaz. Çıkartmalı planlama bir kez yapılınca Meta kendisi yayınlar.
- Ayrıntılı devir notu: `DEVAM.md`.

## Bilinen küçük notlar (site verisinden)
- Conti iç lastik fotoğrafında farklı kutu modeli; düşük çözünürlüklü görsellerde bulanık dolgu; bandana fotoğraf
  çerçevesi. Sitedeki fotoğraflar güncellenirse otomatik düzelir.
