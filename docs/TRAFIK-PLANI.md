# NITRO Bisiklet: Instagram ve Site Trafik Planı (25 Kasım 2026 – 31 Mart 2027)


> **Düzeltme (25 Kasım 2026):**
> - **Profil linki:** `nitrobisiklet.com` olarak kalır. Bio sayfası (GitHub Pages) yalnız yardımcı ve yedek listedir; profil linki olarak önerilmez.
> - **Postlarda N-kodu yerine arama terimi:** Sitenin araması N-kodunu tanımadığı için postlarda N-kodu kullanılmaz. Her ürüne `scripts/arama.py` ile doğrulanmış bir arama terimi atanır (`data/arama.json`, 420/420 ürün). Açıklama, kapak kartı ve "Nasıl alırım?" karesi "nitrobisiklet.com → aramaya “terim” yaz" der.
> - **Story'ler:** Arama talimatı yoktur. Business Suite'teki tıklanabilir "ÜRÜNE GİT" link çıkartması doğrudan ürün sayfasına gider. API yedeği de yalnız "ÜRÜNE GİT" yazar.
> - **Suite postları:** N-kodlu 24 ürün ve liste postu (26 Kasım–22 Aralık) Suite'te taslağa alındı. Yeni metinle API'den yayınlanır.
> - **Bu belgedeki eski maddeler:** N-kodu defteri, N-kodu KPI'ı ve `/k/` yönlendirmesi maddeleri "arama terimi" olarak okunur.

## Yönetici özeti

1. **Kilit gerçeği:** `suite_scheduled=true` olan 115 kayıt (4 ipucu postu: 25 Kasım, 2, 9 ve 16 Aralık; 111 story: 24 Aralık 12:30'a kadar) donmuş durumda. Otomasyondaki caption, CTA, konum ve etiket iyileştirmeleri kalan 33 kilitsiz posta (25 Kasım–31 Aralık) uygulanır. Kilitli 4 post için öneriler `data/suite_duzelt.json`'da; Barış isterse Suite'te elle düzeltir.
2. **Ölçüm hemen başlar, büyüme beklemez.** Baz değer zaten var: `data/suite_insights.json` (28 Ekim–24 Kasım) haftada ortalama 33 link tıklaması, 172 profil ziyareti ve 38 takip gösteriyor. "Yalnız ölçüm" dönemi yok. Her yeni kanal kendi UTM'ini taşır; böylece baz değer ölçümü ile büyüme işleri aynı anda yürür.
3. **Hediye sezonunun en hızlı kaldıraçları Barış'ın elinde:** 1 Aralık'a kadar Google İşletme Profili, IG→FB çapraz paylaşım, Hızlı yanıtlar, 3 sabitlenmiş post ve tezgâh QR kartı. İsteğe bağlı olarak 10–14 Aralık'ta yerel "Öne çıkar" testi yapılabilir (bütçe ve ödeme yalnız sahibin kararı).
4. **Otomasyonun P0 işleri:** Suite postlarını API medyasıyla eşlemek (bu olmadan baz dönem boş kalır), bio atfını düzeltmek ve son 14 günün post kartlarını göstermek, tarihten bağımsız CTA, sorular ve tekrar yasağı (yalnız kilitsiz kayıtlarda). 24–31 Aralık'taki 8 adet 20:30 story'si aynı ürünü ikinci kez göstermek yerine seçki veya servis hedefine çevrilir.
5. **Bağımlılıklar:** Barış 27 zamanlanmamış linkli story'yi 15 Aralık'a kadar Suite'te zamanlar. Ocak takvimi için `plan_end` 15 Aralık'tan önce uzatılır. Site geliştiricisinin `/k/` yönlendirmesi, JSON-LD ve blog işleri tarihlidir. Otomatik takvim optimizasyonu yapılmaz; yalnız aylık öneri raporu üretilir.

---

**Temel kural.** `suite_scheduled=true` kayıtların hepsi donmuştur. Kilidi `plan.py` içinde iki yer uygular: `state()` (satır 488) bu kayıtlar için `kalsin` döndürür, `drop()` (satır 99) de onları silmez. `keep_flags` (satır 540-545) bayrağı düşürmez, yalnız UYARI basar. `publish.py:433` bu kayıtları API'ye göndermez, `via=suite` ile `published` olarak işaretler. Asıl risk, değişikliğin kilitli kayda **sessizce hiç uygulanmamasıdır**. Bu yüzden her değişikliğin kabul ölçütü iki parçalıdır:
- (a) Kilitli kayıtlarda `fp` ve caption değişmedi.
- (b) Kilitsiz kayıtlarda yeni kural uygulandı.

Kilitli postlar için yapılabilecek elle düzeltmeler `data/suite_duzelt.json`'a yazılır (tarih, eski satır, önerilen satır). Bu liste Barış'a yalnız kullanıcı izniyle gider ve Barış isterse uygular.

---

## 1. Durum teşhisi

1. **Ölçüm.** `metrics.json` `insights:false` diyor ve yalnız 24 Kasım postunu içeriyor (13 beğeni, 0 yorum). Suite'te yayınlanan postlara `media_id` yazılmıyor. `report.collect()` (satır 217) yalnız `media_id` olan kayıtları ölçüyor, yani 28 Suite postu hiç ölçülmeyecek. `scores.json` n=0 ve `load_scores` hiçbir yerden çağrılmıyor. GA4 (G-CHD8NRMBC9) çerez onayından sonra yükleniyor, bu yüzden sayıları alt sınırdır. Hesap düzeyinde baz değer `suite_insights.json`'da var (aşağıdaki tablo).
2. **Siteye giden yol 4 adım ve kopuk.** Kullanıcı profile gider, linke dokunur, kodu yazar, kartı seçer. RECENT'ta 1 öğe var ve bu öğe story kaynaklı (`utm_campaign=promo`, `utm_content=story-2030`). Sitenin kendi araması kodu tanımıyor: `/ara/?q=N302` "Sonuç yok" döndürüyor.
3. **Atıf bozuk.** Kodla yapılan arama `utm_campaign=arama` olarak düşüyor. RECENT kartı post tıklamasını 20:30 story'sine yazıyor. Promo story'lerin hepsi `campaign=promo`.
4. **İçerik tek yönlü.** 38 postun 26'sı tek ürün; bunların 12'sinde özellik satırı yok. 19:30 postu ile 20:30 story'si aynı ürüne 1 saat arayla iki kez link veriyor, ikisi aynı tıklamayı paylaşıyor. Bazı sorular evet/hayır sorusu ya da tekrar ediyor. Kaydetme veya gönderme çağrısı yok. Kış sezonunun ana ürünü olan servis içerikte neredeyse yok.
5. **Kullanılmayan kaldıraçlar.** `location_id` boş (`publish.py:212-226` hazır). Bio sayfasında WhatsApp, telefon, harita, saat ve "Köyceğiz Bisiklet Turları" WhatsApp grubu yok; hepsi `site.json`'da var. 10 adet 2. el ve 7 çocuk bisikleti hiç post almadı. Sitede JSON-LD, og:price, Instagram linki ve wa.me butonu yok. GBP durumu, Yandex/Apple/Bing haritaları, FB çapraz paylaşım ve Marketplace kullanılmıyor.
6. **Takvim riski.** 24–31 Aralık'ta tam 27 linkli story Suite'e zamanlanmamış: 20:30'da 8, 12:30'da 7, 19:30'da 6, 09:30'da 4, 11:00'de 2. Zamanlanmazlarsa tıklanamayan "Link profilde · Kod" yedeğine düşerler. `plan_end=2026-12-31` uzatılmadan Ocak planı üretilmez.

---

## 2. Hedefler ve KPI'lar

**Baz değer** (`suite_insights.json`, 28 Ekim–24 Kasım, 4 haftanın ortalaması; son hafta parantez içinde):
- Görüntülenme: 13.692 (11.854)
- İzleyen: 4.472 (4.059)
- Etkileşim: 339 (268)
- Link tıklaması: 33 (104)
- Profil ziyareti: 172 (182)
- Takip: 38 (21)

Barış her pazartesi aynı Suite ekranını `data/manuel.json`'a işler. Hedefler 4 Ocak'ta 5 haftalık veriyle gözden geçirilir. Verisi olmayan KPI raporda "veri yok" yazar, sıfır sayılmaz.

**Ana göstergeler (3)**

| KPI | Bugün | 31 Aralık | 31 Mart | Kaynak |
|---|---|---|---|---|
| Haftalık profil ziyareti | 172 | ≥220 | ≥300 | Suite → `manuel.json`; izin gelince API |
| Haftalık GA4 oturumu (`instagram` + `gbp`) | bilinmiyor; ilk Looker haftası baz değer | baz ×1,3 | baz ×2 | Looker Studio pazartesi e-postası |
| Haftalık N-kodu talebi (satışa dönen ayrıca) | ölçülmüyor | ≥5 | ≥10 | N-kodu defteri |

**İkincil göstergeler**

| KPI | Bugün | 31 Aralık | 31 Mart | Kaynak |
|---|---|---|---|---|
| Haftalık link tıklaması (story + bio) | 33 (son hafta 104) | ≥100 | ≥150 | Suite → `manuel.json` |
| Takipçi (haftada net +15–30) | 2.665 | 2.740–2.815 | 2.935–3.205 | `metrics.json` account geçmişi, net |
| Post başı yorum | 0 | ≥1 | ≥2 | ilk ≥72 saatlik ölçüm |
| Post beğeni medyanı (ilk ≥72 saatlik ölçüm) | 13 | ≥18 | ≥25 | `metrics.json` |
| Bio'ya kod veya aramayla gelen oturumlarda `utm_content=<post-id>` payı | ~0 | ≥%90 | ≥%90 | GA4 |
| Aynı oturumlarda `arama` payı | ~%100 | <%10 | <%10 | GA4 |
| Bio kategori ve iletişim tıklaması (ayrı sayılır) | yok | baz değer alınır | artış eğilimi | GA4 `utm_medium=bio` |
| Yayın sağlığı: missed/error, zamanlanmamış linkli story | 27 zamanlanmamış | 0 / 0 / 0 | 0 | RAPOR.md |
| Sitede yayınlanmış rota ve bakım yazısı | 0 | 0 | ≥4 (blog şablonu teslim edilirse) | /blog/ |
| Kabul edilmiş collab | 0 | 0 | ≥2 | `invite_status` |
| *Koşullu:* Merchant'ta onaylı ürün | 0 | uygunluk doğrulandı mı | stoktaki ürünlerin ≥%85'i | yalnız TR uygunluğu doğrulanırsa |

GA4 sayıları alt sınırdır; yalnız eğilime bakılır.

---

## 3. Hızlı kazanımlar: bu hafta (25 Kasım–1 Aralık)

Öncelik sırası: erişim, sonra dönüşüm, sonra ölçüm inceliği.

### Barış'ın yapacakları

| # | İş | Etki | Efor | Ölçüt |
|---|---|---|---|---|
| B1 | **Google İşletme Profili:** var mı, doğrulanmış mı kontrol et. Kategoriler: Bisiklet mağazası ve Bisiklet tamircisi. Hizmetler `site.json`'dan girilir. En çok satan 10 ürün gerçek fiyatıyla eklenir. 10'dan fazla gerçek fotoğraf yüklenir. Saat `site.json` ile aynı olur ("Pzt–Cmt 08:30–19:00, Pazar kapalı"). Web sitesi linki: `utm_source=google&utm_medium=organic&utm_campaign=gbp` | Yüksek | 45 dk | 1 Aralık'ta profil doğrulanmış ve dolu |
| B2 | **Token'ı yeniden üret:** sistem kullanıcısı token'ına `instagram_manage_insights`, `instagram_manage_comments` ve `pages_read_engagement` izinleri eklensin. `IG_ACCESS_TOKEN` secret'ını Barış kendisi günceller; Claude token görmez ve girmez. | Yüksek | 15 dk | `metrics.json` `insights:true` |
| B3 | **Profil:** ad alanı "NITRO Bisiklet Köyceğiz" (23 karakter; sınır 30, ad 14 günde en fazla 2 kez değişir). "Bisiklet satış ve servis · Köyceğiz" bio metnine ve kategoriye girer. WhatsApp iletişim butonunu açsın, "Arama motorlarında görünme" ayarını kontrol etsin. | Orta | 10 dk | Ad ≤30 karakter; "köyceğiz bisiklet" aramasında profil görünüyor |
| B4 | **Hesaplar Merkezi'nde IG→FB otomatik paylaşımı açsın.** Facebook Sayfası'ndaki adresin doğru olduğunu teyit etsin (`location_id` bu Sayfa'dan okunur). | Orta | 10 dk | Sonraki post FB'de görünüyor |
| B5 | **Hızlı yanıtlar:** fiyat/kod, kargo-iade, servis randevusu, konum. Metinler yalnız site gerçeklerinden üretilir. | Orta | 10 dk | 4 yanıt tanımlı |
| B6 | **Sabitlenmiş 3 post:** mevcut postlardan en çok etkileşim alan, servis içerikli ve seçki/hediye postu. | Orta | 5 dk | 3 post sabit |
| B7 | **İlk saat yorum yanıtları** (yanıtta kod yazılır) ve **günde 10 dk giden etkileşim:** Köyceğiz, Dalyan ve Ortaca işletmeleri ile belediye ve turizm hesaplarına anlamlı yorum. | Orta | günde 15 dk | Yanıtlanan yorum %100 |
| B8 | **N-kodu defteri:** tarih, kod, kanal, satışa döndü mü. Müşterinin kişisel verisi yazılmaz. | Yüksek | günde 2 dk | Haftalık talep sayısı |
| B9 | **Tezgâh QR kartı** (Instagram takip ve Google yorum; `utm_campaign=qr-tezgah`). Servisten çıkan bisiklete ve kargoya da kart. Yorum yalnız gerçek müşteriden istenir, karşılığında teşvik verilmez. | Orta | 30 dk (baskı ayrı) | GA4 `qr-tezgah` oturumu, yeni yorum sayısı |

Şablon ve görselleri otomasyon `data/paylas/` altına üretir. Barış'a yalnız kullanıcı izniyle gönderilir.

### Otomasyonun yapacakları

İşler ayrıntılı olarak sondaki iş listesinde (O1–O5). Kısa özet:
- Suite postlarını API medyasıyla eşleme.
- Bio atfı ve son 14 günün post kartları, iletişim ve topluluk butonları.
- Tarihten bağımsız CTA ve sorular (kilitsiz kayıtlarda).
- `location_id`'nin probe ile okunması.

### İsteğe bağlı: ücretli test (karar ve ödeme yalnız sahipte)

- **Zaman:** 10–14 Aralık, 5–7 gün.
- **Bütçe:** küçük bir günlük bütçe; tutarı sahip belirler.
- **Hedefleme:** 25–30 km yarıçap.
- **Kreatif:** organik olarak en iyi giden seçki postu.
- **Hedef:** profil ziyareti ya da site. Linkte `utm_campaign=boost`.
- **Ölçüt:** profil ziyareti başına maliyet ve GA4 boost oturumu.
- **Metin:** yalnız site gerçekleri. Claude ödeme bilgisi girmez.

---

## 4. Instagram trafiği planı

**Aralık (kilitli takvim olduğu gibi kalır)**
- 23–31 Aralık'taki 9 kilitsiz posta yeni caption, CTA, konum ve etiket uygulanır.
- 24–31 Aralık'ta çocuk bisikletine (7 ürün) ve kontrollü 2. ele (10 ürün) öncelik verilir. 2. el için "Kontrollü 2. el" dışında iddia yazılmaz. 2. el postu Barış tarafından Facebook Marketplace'e de elle girilir.
- 26 Aralık listesi (kilitsiz) fiyat bandına göre hediye seçkisine dönüşür. Seçkide yalnız `products.json`'daki gerçek fiyatlar ve stoktaki ürünler yer alır; teslim süresi vaadi yazılmaz. Bio'da `?p=` koleksiyonu olarak da açılır.
- **20:30 kararı (beklemeden):** 24–31 Aralık'taki 8 kilitsiz 20:30 story'si, aynı ürünü ikinci kez göstermek yerine hediye seçkisine (`?p=`) ya da servis randevu sayfasına gider. Değerlendirme ölçütü günlük toplam link dokunuşudur; 19:30 ile 20:30 ayrı ayrı kıyaslanmaz. Ocak'ta da varsayılan budur.

**Ocak'tan itibaren haftada 7 post**
- 1 rehber: ipucu ya da sezon hazırlığı.
- 1 servis veya kış bakımı postu: `site.json` paketleri ve gerçek fiyatlarıyla; CTA randevu sayfasına gider.
- 1 rota: yalnız kaynaklı veriyle. Kışın düşük rakımlı rotalar seçilir (Göl turu, Sultaniye–Dalyan).
- 1 seçki: 3–5 ürün, `?p=` kartıyla.
- 2 tek ürün: rotasyonda bisiklet, 2. el ve çocuk bisikleti de yer alır.
- 1 esnek slot: önce/sonra fotoğrafı geldiyse o, gelmediyse ipucu.
- **Dengeli gün rotasyonu:** temalar haftadan haftaya farklı günlere kayar. Amaç aylık raporda gün etkisini kabaca ayırmaktır, otomatik karar vermek değildir.

**Ürün seçimi**
- Postlar yalnız en az 3 özelliği olan ya da açıklaması dolu üründen seçilir (`need_specs=3`).
- 12:30 story'si ±1 gündeki postların alt türünden kaçınır.
- Carousel'de "Neden NITRO" ve CTA tek karede birleşir. Boşalan yere gerçek veriden bir kare gelir.

**Caption ve CTA**
- Sıra: kanca, iki seçenekli soru (2. satır), ad ve fiyat, özellikler, nasıl alırım, tek satır güven bilgisi (site gerçeği), SEO satırı, etiketler.
- İlk cümle tek bir birincil arama kelimesi ve yer adı taşır, ≤125 karakter.
- CTA zamandan bağımsızdır: **"Profildeki linke dokun, N342 yaz."** "En üstte", "bugün" gibi ifadeler CTA satırında yasaktır.
- Türe göre tek çağrı: seçkide "Hediye alacağın kişiye gönder", rehberde "Kaydet". "Yorum yaz EVET" tarzı etkileşim yemi kullanılmaz.
- Aynı soru ve kanca 30 gün içinde tekrar edilmez. Her kurala en az 3 soru tanımlanır.

**Story**
- Günde 3 story.
- 09:30 değer story'si soru odaklı olur. Barış isterse anket çıkartması ekler.
- İpucu story'si ipucunun kendi başlığını taşır. Linki ilgili kategoriye gider: lastik-basinci Pompa'ya, islak-zemin Aydınlatma ve Reflektör'e, kask-ayari Kask'a.
- Liste story'si `?p=` sayfasına gider, yalnız kilitsiz kayıtlarda. 28 Kasım, 5 Aralık, 12 Aralık ve 19 Aralık liste sticker'ları kilitli; Barış isterse elle değiştirir, değiştirmezse eski link çalışmaya devam eder.

**Arama SEO'su**
- Konum etiketi, profil ad alanı, kategori kelimesiyle başlayan alt metin.
- Etiketler (5): `#köyceğiz` sabit; yanına dönüşümlü bir bölge etiketi (`#muğla`, `#dalyan`, `#ortaca`); kalan 3 etiket konuya özgü.
- Caption'da o bölgeye özel hizmet iddiası yazılmaz.
- `#bisiklet` ve `#nitrobisiklet` çıkar. UGC için hashtag değil @etiket istenir.

**Collab**
- Aralık'ta 10 adaylık liste hazırlanır: tamamlayıcı yerel işletmeler, belediye ve etkinlik hesapları, yetişkin yerel doğa içerik üreticileri. Rakip dükkân, takım üyesi ve reşit olmayan kimse listede yer almaz.
- Hesapların varlığı doğrulanır, Barış onaylar ve ilk teması kurar.
- Ocak'tan itibaren ayda en fazla 2 collab yapılır.

**Topluluk**
- Öne Çıkanlar: Nasıl Alırım, Servis, 2. El, Teslimat-İade.
- `site.json`'daki "Köyceğiz Bisiklet Turları" WhatsApp grubu bio'da "Topluluk sürüşleri" butonu olarak yer alır. Haftalık rota/ipucu postu grupta paylaşılır (`utm_source=whatsapp&utm_medium=group`).
- Grup üyelerine toplu ticari mesaj gönderilmez. ETK/İYS onayı olmadan pazarlama mesajı yok.
- UGC yalnız yazılı izinle repost edilir. `paylas/ugc/izinler.json` yalnız elle düzenlenir; otomasyon bu dosyayı yalnız okur. Fotoğrafta reşit olmayan biri varsa kullanılmaz.

**Yorum otomasyonu (aşamalı)**
1. Salt okuma: yanıtsız yorumların özeti çıkarılır.
2. N-kodu ya da "fiyat" yazan yoruma `products.json` fiyatıyla herkese açık yanıt verilir. Yanıt `denetim.py`'den geçer.
3. **DM / private reply ayrı ve koşullu bir projedir.** Advanced Access, App Review ve İşletme doğrulaması gerekir. IG uygulamasında "Mesajlara erişime izin ver" de açık olmalıdır.

---

## 5. Site trafiği planı

**Sıra**

1. **Yerel haritalar (1 Aralık'tan itibaren):** GBP (B1). Ardından Yandex Business, Apple Business Connect ve Bing Places. Hepsi ücretsiz ve tek seferlik. NAP (ad, adres, telefon) bilgisi `site.json` ile birebir aynı olur. GBP için haftalık gönderi paketi `data/paylas/gbp_haftalik.md` olarak üretilir (her plan çalışmasında güncellenir); Barış'a yalnız kullanıcı izniyle gider.
2. **Instagram'dan siteye yol**
   - Bio'da "Instagram'da son 14 gün" bölümü yer alır: post kapağı ve başlık, tek dokunuşla ürüne ya da koleksiyona geçiş.
   - Daha eski postlar kodla bulunur. Kod, RECENT'taki posta eşlenir.
   - Suite postu yayınlandıktan sonra bio kartı, 15 dakikalık cron'un bir sonraki çalışmasında görünür.
3. **Bio sayfası**
   - İletişim: WhatsApp'tan sor (kod ve ürün adıyla ön doldurmalı `wa.me`), Ara, Yol tarifi, saat.
   - "Topluluk sürüşleri" butonu.
   - Stokta en çok ürünü olan 8 kategoriden UTM'li kısayollar.
   - "Rotalar" butonu ilk blog yazısı yayınlanınca eklenir.
   - Bio sayfası noindex kalır.
4. **Site geliştiricisinin işleri (tarihli)**
   1. Footer'a Instagram linki ve ürün sayfasına WhatsApp butonu: 9 Aralık.
   2. `nitrobisiklet.com/k/N302` adresinden ürüne 302 yönlendirmesi; eşleme `docs/feed/kodlar.json`'dan okunur: 20 Aralık.
   3. Product/Offer ve BikeStore JSON-LD ile og:price: 15 Ocak.
   4. Blog şablonu ve kategori/servis meta açıklamaları: 31 Ocak. Rota/blog KPI'ı ancak bu madde teslim edilince başlar.
5. **Diğer kanallar**
   - Facebook bisiklet gruplarına rota özeti: yalnız grup yöneticisinin izniyle ve elle.
   - 2. el bisikletler için Facebook Marketplace (Barış elle).
6. **Park edilenler (Mart sonrası ya da koşullu)**
   - Merchant feed'i (`google.tsv`, `meta.csv`) ve ücretsiz listeleme: Türkiye uygunluğu doğrulanana kadar bekler. Doğrulanırsa `old_price` hep boş olduğu için sale_price yazılmaz.
   - Meta Shopping, Pinterest, yayın kanalı, jüri yarışması, otel QR kartı.

---

## 6. Ölçüm ve öğrenme döngüsü

**Katmanlar**

1. **Suite post eşleme:** `/{ig-user-id}/media?fields=id,timestamp,permalink,media_type` çekilir. `via=suite` olan kayıtta planlanan zamanın ±10 dk içinde tek aday varsa `media_id` ve permalink yazılır; yoksa "eşlenemedi" yazılır.
2. **Post metrikleri:** "ilk ≥72 saatlik ölçüm" donmuş değer olarak saklanır, yaş bilgisiyle birlikte. Toplama publish adımında `must=False` olarak çalışır. Puanlama kümülatif değerle yapılmaz.
3. **Story insights:** publish adımında (15 dakikada bir, `must=False`) `/stories` uç noktasından yayındaki story'ler çekilir ve her story için son değer saklanır. 04:10 plan çalışması 20:30 story'sinin gece değerini tamamlar. Suite story'leri ±10 dk içinde tek adayla eşlenir.
   - Link sticker dokunuşunun API'de dönüp dönmediği 1 story ile test edilir. Dönmüyorsa link dokunuşu yalnız Barış'ın haftalık Suite okumasından alınır.
4. **Hesap düzeyi:** `profile_links_taps`, takip/takipten çıkma, erişim. Hata veren metrik tek tek atlanır.
5. **Barış'ın pazartesi okuması:** 2 sayı (toplam link tıklaması ve N-kodu defteri özeti) artı Suite ekranındaki haftalık değerler. Hepsi `manuel.json`'a işlenir.
6. **GA4:** Looker Studio raporu pazartesi e-postayla gelir (medium / campaign / content). Workflow env'i değiştirilemediği için otomatik çekilmez.
7. **Kanal UTM'leri:** `gbp`, `boost`, `qr-tezgah`, `whatsapp/group`, `fb`. Her kaldıraç ayrı sayılır.

**Döngü**
- RAPOR.md'ye haftalık KPI tablosu eklenir: tablodaki her KPI için 1 satır (hedef, gerçekleşen, önceki hafta, durum).
- Denetim bulguları kilitli ve kilitsiz olarak ayrı sayılır. Kilitli kayıtlardaki SUITE-UYARI'lar BULGU sayılmaz (`denetim.py:430-433`).
- Ayın ilk pazartesi günü tek sayfalık tema raporu üretilir: tema ve gün bazında ortalamalar, n ve önceki ay. Rapor yalnız **öneridir**. Takvime otomatik yazılmaz; kararı kullanıcı ve Barış verir.
- Post başına yaklaşık 13 beğeni ve kol başına birkaç post olan bu ölçekte istatistiksel otomatik uygulama gürültüye göre karar verir. Bu yüzden yapılmaz.

---

## 7. Otomasyona eklenecek işler: ilkeler

- Ortak kabul ölçütü: `denetim.py` temiz geçer; kilitli kayıtlarda `fp` ve caption değişmez; kilitsiz kayıtlarda yeni kural görünür.
- `.github/workflows` dosyalarına dokunulmaz. Workflow yalnız `data`, `docs` ve RAPOR.md'yi commit ettiği için otomasyonun yazdığı her dosya `data/` ya da `docs/` altında olur.
- Yeni adımlar `gorev.py` içinde `must=False` çalışır. İzin yoksa yalnız uyarı basılır, publish kırılmaz.
- Her değişiklikten sonra lint, test ve `plan.py --dry` çalıştırılır.
- İş listesi en sondaki tabloda.

---

## 8. Barış'tan gerekenler

**Bu hafta (1 Aralık'a kadar):** B1–B9 (Bölüm 3).

**2–15 Aralık**
- 27 zamanlanmamış linkli story'yi Suite'te zamanlamak. Otomasyon 20:30 ve liste değişikliklerini 5 Aralık'a kadar bitirir; zamanlama 6–15 Aralık'ta yapılır.
- İsteğe bağlı: 4 kilitli liste sticker'ını ve `data/suite_duzelt.json`'daki caption/konum önerilerini Suite'te uygulamak.
- 4 Öne Çıkan; Yandex, Apple ve Bing kayıtları.
- Collab aday listesine onay.
- Ücretli test için karar (isteğe bağlı).
- **Ocak linkli story kapasitesi için karar.** Suite en fazla 29 gün ileriye zamanlıyor.
  - A) Günde 2 linkli story: ayda yaklaşık 60 zamanlama, 2–3 saat.
  - B) Günde 1 linkli story (12:30): ayda yaklaşık 30 zamanlama. Diğer story'ler API'den linksiz gider.
  - Karar 15 Aralık'ta verilir. Ocak'ın zamanlaması 31 Aralık'a kadar yapılır.

**Aralık sonuna kadar (tek seferlik):** GA4 Looker Studio raporu ve pazartesi e-postası; Search Console.

**Site geliştiricisine iletilecekler:** Bölüm 5'teki tarihli liste. İsteğe bağlı: GA4 consent mode v2.

**Sürekli**
- Pazartesi okuması.
- Haftada 1–2 servis önce/sonra fotoğrafı: yalnız parça; yüz, plaka ve fiş görünmez.
- Günde 10 dk giden etkileşim.
- UGC izinlerinin kaydı.
- 2. el ilanlarının Marketplace'e girilmesi.
- Sandras Adventure Trail tarihini organizatörden teyit etmek (resmî site 9–11 Nisan 2027, Advenway 9–10 Ocak 2027 diyor).

---

## 9. Riskler ve yasaklar

**Yasaklar**
- Sahte indirim, kampanya, stok ya da süre iddiası yazılmaz ("son gün", "kontenjan" dahil).
- Takım üyelerinin bireysel verisi hiçbir akışta kullanılmaz (UGC ve collab dahil).
- Reels üretilmez.
- Şifre, token, doğrulama kodu ve ödeme bilgisini yalnız Barış girer.
- Barış'a materyal yalnız kullanıcı izniyle gönderilir.
- `.github/workflows` dosyaları değişmez.
- Kurayla çekiliş yapılmaz. Yorum için teşvik verilmez. ETK/İYS onayı olmadan toplu ticari mesaj gönderilmez.

**Riskler ve önlemleri**
- **Değişikliğin kilitli kayda sessizce uygulanmaması:** iki parçalı kabul ölçütü ve kilitli/kilitsiz bulgu ayrımı.
- **Suite postunun eşlenememesi:** "eşlenemedi" sayısı RAPOR.md'de görünür; Barış permalink'i `manuel.json`'a girebilir.
- **Yanlış konum:** ilk API postunun permalink'i elle kontrol edilir.
- **Story verisi kaybı:** 15 dakikalık toplama ve 04:10 yedeği. Link dokunuşu API'de yoksa elle okunur.
- **Otomatik yanıtta yanlış fiyat:** yanıtlar `denetim.py`'den geçer; şikâyet içeren yoruma otomatik yanıt verilmez.
- **GA4 eksik sayım:** sayılar alt sınırdır, yalnız eğilim okunur.
- **Rota bilgisinin eskimesi:** yayından 48 saat önce rotanın açık olduğu kontrol edilir; ECO Trails'te "Kapalı" görünen rota seçilmez.
- **Barış'ın elle iş yükü:** Ocak için A/B kapasite seçeneği; elle işler 3 sayı ve 2 rutinle sınırlı tutulur.
- **Site geliştiricisinin gecikmesi:** `/k/` gelmezse kod akışı bio'da çalışmaya devam eder; blog KPI'ı ertelenir.

**Çözülen çelişkiler**
- "Postlar hemen değişir" iddiası düzeltildi: Aralık'ta yalnız 23–31 Aralık postları değişir, öncekiler için opsiyonel elle düzeltme listesi var.
- "Yalnız ölçüm dönemi" kaldırıldı; baz değer `suite_insights.json`'dan alındı.
- Latin kare, bootstrap ve otomatik uygulama kaldırıldı; yerine aylık öneri raporu geldi.
- "Bu gönderi en üstte" CTA'sı yerine zamandan bağımsız kod CTA'sı ve 14 günlük bio bölümü kondu.
- Post atıf KPI'ının paydası kod ve arama oturumlarıyla sınırlandı.
- 20:30 kararı, ham karşılaştırma yerine yamyamlığı önleyen yeniden hedeflemeye dönüştü.
- `location_id` için ID istenmiyor, probe ile okunuyor.
- Takipçi hedefleri haftalık bandla tutarlı hale getirildi.
- N-kodu için site tarafında yalnız `/k/` yönlendirmesi seçildi.

**Doğrulanmamış iddialar:** Merchant ücretsiz listeleme ve Shopping'in Türkiye'de kullanılabilirliği; link sticker dokunuşunun API'de dönüp dönmediği; collab adaylarının hesaplarının aktifliği; "çerezsiz sayaç KVKK açısından sorunsuzdur" yorumu (hukuki onay sayılmaz).

---

## Otomasyon iş listesi

### Durum (25 Kasım 2026)

| İş | Durum | Not |
|---|---|---|
| O1 | Tamam (kod) | `report.py --esle` her publish çalışmasının sonunda; canlı eşleme ilk Suite postunda doğrulanacak |
| O2 | Tamam | Bio: son 14 günün yayınlanmış postları, stok ve fiyat kontrolü, iletişim butonları `site.json`'dan |
| O3 | Tamam | SEO 1. satır, iki seçenekli soru, arama terimli CTA, 30 gün tekrar yasağı; kilitli kayıtlar değişmedi |
| O4 | Tamam (kod) | Konum probe görevinde okunur (`data/konum.json`); Sayfa konumu boşsa post konumsuz yayınlanır |
| O5 | Tamam | 20:30 story'leri kategori/servis hedefine; promo kampanyası = post teması; 26 Aralık: 1.000 ₺ altı hediye seçkisi |
| O6 | Tamam | `data/suite_duzelt.json`: 4 kilitli post için öneri; Barış'a yalnız kullanıcı izniyle |
| O7 | Bekliyor | Story/hesap insights için jetonda `instagram_manage_insights` izni gerekir (B2) |
| O8 | Tamam | Postlarda ≥3 teknik özellik, ±1 gün alt tür kontrolü, 25 Aralık çocuk ve 28 Aralık 2. el postu |
| O9 | Tamam | 5 etiket: `#köyceğiz` + dönüşümlü bölge + 3 konu; alt metinler kategori kelimesiyle başlar |
| O10 | Bekliyor | Barış'ın linkli story A/B kararı; `plan_end` 15 Aralık'a kadar 2027-01-31'e uzatılacak |
| O11 | İptal | N-kodu kaldırıldı; CTA doğrulanmış site arama terimini kullanıyor, `/k/` yönlendirmesi gerekmiyor |
| O12 | Tamam | `scripts/paylas.py` → `data/paylas/` (GBP, QR, hızlı yanıtlar, öne çıkanlar, grup metinleri) |
| O13 | Bekliyor | Rota verisi (kaynaklı) gerekli |
| O14 | Tamam (kod) | `collaborators` alanı + `collab_onay` bayrağı (varsayılan kapalı); Barış onayıyla açılır |
| O15 | 1. aşama tamam | `scripts/yorum.py` salt okuma özeti (`data/yorumlar.json`, depoya girmez); 2. aşama (yanıt) onay bekliyor |
| O16 | Tamam | RAPOR.md'de "Aylık tema raporu" (yalnız öneri); veri biriktikçe dolar |

| Sıra | İş | Dosya | Kabul kriteri | Efor |
|---|---|---|---|---|
| O1 (P0) | Suite postlarını `/media` ile ±10 dk eşleme; `media_id` ve permalink yazma; ilk ≥72 saatlik metrik dondurma (publish adımında `must=False`) | `scripts/report.py`, `scripts/gorev.py` | 25 Kasım'dan itibaren Suite postlarının ≥%90'ında `media_id` var; eşlenemeyenler RAPOR.md'de; izin yoksa publish kırılmıyor | 1 gün |
| O2 (P0) | Bio: `_recent` yalnız `type=='post'`; `find()` önce RECENT'ta arar; "son 14 gün" kartları (post kapağı `docs/media/t/<id>.jpg`, yoksa ürün görseli); `?p=<post-id>` koleksiyonu; WhatsApp ön doldurma, Ara, Yol tarifi, saat, "Topluluk sürüşleri" (`site.json`) | `scripts/bio.py` | RECENT'ta story kaynaklı link yok; N302 araması `utm_content=<post-id>` döndürüyor; `?p=` 5 ürünü sırayla gösteriyor; telefon, saat ve grup linki `site.json` ile birebir | 1 gün |
| O3 (P0) | Caption sırası; CTA "Profildeki linke dokun, N… yaz."; türe göre gönder/kaydet çağrısı; iki seçenekli sorular (kural başına ≥3); 30 gün kanca/soru tekrar yasağı; CTA satırında "en üstte"/"bugün" yasağı | `scripts/content.py`, `scripts/plan.py`, `scripts/denetim.py` | Kilitsiz kayıtlarda ilk satır ≤125 karakter, soru ilk 3 satırda, evet/hayır sorusu 0, tekrar 0; kilitli kayıtlarda `fp` ve caption değişmedi; bulgular kilitli/kilitsiz ayrı sayılıyor | 1 gün |
| O4 (P0) | `location_id`: probe görevinde `/{page-id}?fields=location` okunur, doluysa Sayfa ID'si `config.json`'a yazılır | `scripts/gorev.py`, `config.json` | 23 Aralık–5 Ocak arasındaki 14 API postunun hepsinde konum dolu; ilk postun permalink'i elle kontrol edilmiş | 2 saat |
| O5 (P0, 5 Aralık'a kadar) | 24–31 Aralık'taki kilitsiz 20:30 story'leri seçki `?p=` ya da servis randevu hedefine; promo `utm_campaign`=tema; ipucu story başlığı ve `tips.json` `cta_url`; 26 Aralık fiyat bandı hediye seçkisi; liste story'si `?p=` | `scripts/plan.py`, `data/tips.json`, `config.json` | Yeni kayıtlarda `campaign=promo` yok; 20:30 ile 19:30 aynı URL'ye gitmiyor; seçkide yalnız stoktaki ürünler ve `products.json` fiyatları var; kilitli kayıtlarda değişiklik yok | 4 saat |
| O6 (P0) | Kilitli postlar için opsiyonel düzeltme listesi | `data/suite_duzelt.json` (`plan.py` üretir) | 4 kilitli postun her biri için önerilen caption ve konum satırı var; Barış'a yalnız kullanıcı izniyle gidiyor | 2 saat |
| O7 (P1) | Story insights (her publish çalışmasında `/stories`, son değer saklanır; 04:10 tamamlar); hesap insights'ı; `manuel.json` okuma; haftalık KPI tablosu | `scripts/report.py`, `scripts/gorev.py` | İzin yoksa yalnız uyarı basılıyor; Suite story eşleme oranı raporlanıyor; KPI tablosunda §2'deki her KPI için 1 satır var; link dokunuşu API testi sonucu RAPOR.md'de | 1 gün |
| O8 (P1) | Postlarda `need_specs=3`; 12:30 story'sinde ±1 gün alt tür çakışma kontrolü; 24–31 Aralık'ta çocuk ve 2. el havuzu | `scripts/plan.py` | Yeni postlarda özelliksiz ürün 0; ardışık günde aynı alt tür 0; 24–31 Aralık'ta ≥1 çocuk ve ≥1 2. el postu | 4 saat |
| O9 (P1) | Yeni etiket seti (5), SEO ilk satırı, alt metin | `scripts/content.py`, `scripts/plan.py` | Etiket sayısı 5; `#köyceğiz` var; `#bisiklet` ve `#nitrobisiklet` yok; bölgeye özel hizmet iddiası yok | 2 saat |
| O10 (P1, 15 Aralık'a kadar) | `plan_end` 2027-01-31'e uzatılır (sonra aylık); Ocak karışımı (rehber, servis, rota, seçki, 2 ürün, esnek) ve dengeli gün rotasyonu; linkli story sayısı Barış'ın A/B kararına göre | `config.json`, `scripts/plan.py` | Ocak takvimi denetimden temiz geçiyor; haftada 7 post; servis postunda `site.json` paket adı ve fiyatı birebir; linkli story sayısı seçilen kapasiteye eşit | 1 gün |
| O11 (P1) | N-kodu eşleme dosyası (site `/k/` yönlendirmesi için) | `scripts/feed.py` (yeni, `plan.py`'den çağrılır) → `docs/feed/kodlar.json` | Her aktif kod tek bir ürün URL'sine eşleniyor; excluded ürün yok | 2 saat |
| O12 (P2) | `data/paylas/` üreticileri: GBP haftalık paketi, QR kartları, Hızlı yanıt metinleri, Öne Çıkan görselleri, Facebook grup ve WhatsApp grup metinleri | `scripts/paylas.py` (yeni) → `data/paylas/` | Yalnız site gerçekleri; denetimden temiz geçiyor; Barış'a yalnız kullanıcı izniyle gidiyor | 1 gün |
| O13 (P2) | Rota verisi ve şema çizimi (telifli foto yok; OSM kullanılırsa atıf) | `data/rotalar.json`, `scripts/content.py`, `scripts/render.py` | Her sayının kaynak URL'si var; "Kapalı" görünen rota seçilmiyor | 1 gün |
| O14 (P2) | İsteğe bağlı `collaborators` (OPTIONAL_HINTS ile; reddedilirse onsuz yayın); `collab_onay` bayrağı | `scripts/publish.py`, `scripts/denetim.py` | Bayrak yoksa collab gönderilmiyor; davet reddedilse de yayın kaçmıyor | 3 saat |
| O15 (P2) | Yorum 1. aşama (salt okuma özeti) ve 2. aşama (N-kodu ve fiyat yorumuna herkese açık yanıt) | `scripts/yorum.py` (yeni, publish adımında `must=False`), `data/yorumlar.json` | Her yoruma en fazla 1 yanıt; fiyat `products.json` ile aynı; şikâyete otomatik yanıt yok | 1 gün |
| O16 (P3) | Aylık tema raporu (yalnız öneri, takvime yazmaz) | `scripts/report.py` | Ayın ilk pazartesi RAPOR.md'de tema×gün tablosu ve n var; takvimde otomatik değişiklik 0 | 3 saat |
| Park | Merchant/Meta feed'i (`google.tsv`, `meta.csv`), DM 3. aşaması | — | Yalnız TR uygunluğu doğrulanırsa (DM için Advanced Access, App Review ve İşletme doğrulaması) | — |