# NITRO Bisiklet · Instagram otomasyonu

@nitrobisiklet hesabını nitrobisiklet.com verisiyle yönetir: takvim, post / reel / story görselleri, açıklamalar,
UTM'li bağlantılar ve yayın. Bilgisayardan bağımsızdır; her şey GitHub Actions'ta çalışır.

**Yayın kilidi:** `config.json` içinde `"live": false` iken Instagram'a hiçbir şey gönderilmez. Önce simülasyon:

- Simülasyon (telefondan): https://erguderdemir.github.io/nitro-instagram/onizleme/
- Bio sayfası (profildeki link): https://erguderdemir.github.io/nitro-instagram/
- Okunur takvim: [`docs/TAKVIM.md`](docs/TAKVIM.md) · Business Suite listesi: https://erguderdemir.github.io/nitro-instagram/suite/

## Ritim (`config.json`)

| Gün | Post | Not |
|---|---|---|
| Pazartesi 19:30 | Carousel | Performans bisikleti, “Haftanın bisikleti” |
| Salı 19:30 | Ürün carousel | Parça ve aksesuar |
| Çarşamba 19:30 | İpucu carousel | `data/tips.json` |
| Perşembe 19:30 | Ürün carousel | Mevsim seçkisi (kışın lamba, çamurluk, balata…) |
| Cuma 19:30 | Carousel | Şehir / çocuk / elektrikli bisiklet |
| Cumartesi 11:00 | Liste carousel | `config.json` → `lists` |
| Pazar 11:00 | Ürün carousel | Giyim ve aksesuar |

Her gün üç story: 09:30 değer (ipucu, soru, servis, marka; API), 12:30 “Günün ürünü” (linkli), 20:30 günün postunun
tanıtımı (linkli). Takvim `plan_start` → `plan_end` arasını kapsar. Aynı ürün ve aynı ürün ailesi (renk / ölçü
varyantları) `repeat_after_days` gün içinde ikinci kez kullanılmaz.

## Sıfır mantık hatası için kurallar

- **Başlık ürüne kilitlidir.** Ürün, kategorisi ve adındaki anahtar kelimeyle bir kurala (alt türe) bağlanır; her
  kuralın kendi başlık havuzu vardır (`scripts/content.py` → `RULES`). Kuralı olmayan ürün içerik olmaz.
- **Liste başlığı hesaplanır.** Adet = ürün sayısı; eşik yalnız bütün ürünler eşiğin altındaysa yazılır. Sağlanamazsa
  içerik üretilmez.
- **Yalnız site gerçekleri.** Fiyat, teknik özellik, kargo, iade, garanti. İndirim, kampanya, stok ve süre iddiası yok.
- **Scooter / motosiklet / otomobil ürünleri** içerik dışıdır.
- **Denetim.** `scripts/denetim.py` her kaydı yeniden sınar (başlık–kural, liste iddiası, fiyat = güncel fiyat, stok,
  link/UTM/kod, metin sınırları, dosya ölçüleri, ritim, tekrar). Bulgulu kayıt taslağa çekilir, yayınlanmaz.

## Nasıl çalışır?

| Ne zaman | Ne olur |
|---|---|
| Her gün 04:10 | `plan`: site taranır, takvim tamamlanır; gelecekteki kayıtlarda fiyat değiştiyse yeniden çizilir, stok bittiyse yeni ürün seçilir; ardından denetim |
| 09:02–21:32, yarım saatte bir | `publish`: zamanı gelen kayıt yayınlanır (kilit kapalıyken hiçbir şey yapmaz) |
| Elle | Actions → *Instagram otomasyonu* → Run workflow → `check` · `plan` · `probe` · `report` |

Linkli story'ler: Instagram API'si link çıkartması ekleyemez. Bu story'ler iki sürüm üretilir: çıkartma yuvalı sürüm
Business Suite'te elle planlanır ([liste](https://erguderdemir.github.io/nitro-instagram/suite/)); planlanmazsa aynı
saatte API “Link profilde” sürümünü yayınlar.

## Günlük kullanım

- **İzle:** simülasyon sayfası. Takvim, gün akışı, profil ızgarası, tam ekran story.
- **İptal et:** paylaşımın kimliğini (`2026-12-05-post-1100`) `data/iptal.txt` dosyasına bir satır olarak yaz.
- **Takvimi baştan kur:** boş bir `data/yeniden.txt` dosyası ekle; sonraki `plan` gelecekteki kayıtları yeniden seçer.
- **Canlıya geç:** `config.json` → `"live": true`. Yalnız depo sahibi yapar.
- **Hata:** iş akışı kırmızı olur, GitHub e-posta gönderir. Günlük: `data/son-calisma.log`, denetim: `data/denetim.json`.

## Dosyalar

| Dosya | Görev |
|---|---|
| `scripts/scrape.py` | Site haritasından ürünleri çeker → `data/products.json` |
| `scripts/content.py` | Kurallar, başlık havuzları, açıklama, alt metin, UTM, listeler, mevsim süzgeci |
| `scripts/plan.py` | Takvimi üretir ve günceller (şema v2), görselleri ve reel'leri çizdirir |
| `scripts/render.py` | Tasarım motoru: HTML şablon → headless Chrome → JPEG (post 1080×1350, story 1080×1920) |
| `scripts/reel.py` | Karelerden Reels MP4 (H.264/AAC, 9:16). Şu an kullanılmıyor: takvimde reel yuvası yok |
| `scripts/denetim.py` | Denetçi; bulgu varsa çıkış kodu 1 |
| `scripts/simulasyon.py` · `bio.py` · `takvim.py` · `suite.py` | `docs/onizleme/`, `docs/index.html`, `docs/TAKVIM.md`, `docs/suite/` |
| `scripts/publish.py` · `graph.py` | Graph API ile yayın, `--check`, `--probe` (canlıya yayın yapan tek betik) |
| `scripts/report.py` | Ölçümler → `data/metrics.json`, `RAPOR.md` |
| `scripts/gorev.py` | Actions giriş noktası |
| `data/codes.json` | Ürün → kısa kod (N101…); verilen kod değişmez |
| `data/site.json` · `data/tips.json` | Mağaza gerçekleri; ipuçları ve sorular |

Yerelde: `pip install -r requirements.txt`, sonra `python3 scripts/plan.py` (Chrome gerekir; `--kuru` çizmeden
dener), `python3 scripts/denetim.py`.

## Meta kurulum kaydı (tamamlandı)

1. ✅ Instagram profesyonel (işletme) hesap, Facebook Sayfasına bağlı.
2. ✅ GitHub Pages: `main` / `docs`. Actions değişkeni `PUBLIC_BASE_URL`, secret `IG_ACCESS_TOKEN`
   (`IG_USER_ID` isteğe bağlı; tek hesap varsa otomatik bulunur).
3. ✅ Meta uygulaması **Nitro Bisiklet Paylasim** · App ID `2153370375296980` · türü *Business* · durumu *Published*.
   Kullanım alanları: *Manage messaging & content on Instagram*, *Manage everything on your Page*.
   [Gizlilik](https://erguderdemir.github.io/nitro-instagram/gizlilik.html) ve
   [veri silme](https://erguderdemir.github.io/nitro-instagram/veri-silme.html) sayfaları tanımlı.
   Uygulama **Ankara Bisiklet Bakım** işletme portföyüne bağlı.
4. ✅ Sistem kullanıcısı `nitro-instagram-bot` (Çalışan); varlıklar: Nitro Bisiklet Sayfası, @nitrobisiklet, uygulama.
5. ✅ Süresiz token; izinler: `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `business_management`. Token yalnız GitHub secret'ıdır; hiçbir dosyaya yazılmaz.
   Sızarsa: sistem kullanıcısında *Revoke tokens*, yenisini oluştur, secret'ı güncelle.
6. ✅ Doğrulama: Actions → `check` (“HAZIR” yazmalı), `probe` (kapsayıcıları kurar, asla yayınlamaz).
7. Instagram bio bağlantısı: `https://erguderdemir.github.io/nitro-instagram/`

## Bilinen sınırlar

- Görseller sitedeki ürün fotoğraflarından üretilir; küçük ya da bozuk fotoğraflı ürün seçilmez.
- GitHub zamanlayıcısı 5–20 dk gecikebilir; 3 saatten fazla geciken paylaşım `missed` olur.
- Öne Çıkanlar ve Business Suite planlaması elle yapılır (yalnız onaydan sonra).
