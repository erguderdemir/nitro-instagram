# Nitro Bisiklet · Instagram otomasyonu

nitrobisiklet.com'daki ürünlerden otomatik Instagram postu ve story'si üretip yayınlar.

## Ne yapar?

| Ne zaman | Ne olur |
|---|---|
| Her Pazar 21:00 | Site taranır (fiyat, stok, yeni ürün), önümüzdeki 14 günün boş slotları doldurulur, görseller ve açıklamalar üretilir |
| Pzt, Cum 19:30 | Bisiklet postu |
| Çar 19:30 | Sezon ürünü postu (Kasım: lamba, çamurluk, eldiven, lastik… / Aralık: çocuk bisikleti, kask, hediye) |
| Paz 11:00 | Giyim / aksesuar postu |
| Her gün 12:30 | Aksesuar / parça story |
| Her gün 20:30 | Post günleri o günün postu, diğer günler başka ürün story |

Haftada 4 post ve 14 story yayınlanır. Aynı ürün 60 gün, aynı kategori 4 gün içinde tekrar gelmez. Renk varyantları tek ürün sayılır.

**Siteye trafik:** Instagram açıklamadaki linki tıklatmaz. Bu yüzden bio linkin `docs/index.html` sayfasına gider. Bu sayfa Instagram'da paylaşılan ürünleri en yenisi üstte olacak şekilde listeler. Her buton ürün sayfasına UTM etiketiyle gider: `utm_source=instagram`. Böylece satışın Instagram'dan geldiğini site istatistiklerinde görürsün.

## Tek seferlik kurulum (~45 dk)

Bu adımlar senin hesaplarınla yapılmalı. Şifre ve token'ları kimseyle paylaşma, yalnızca GitHub Secrets'a gir.

### 1. Instagram ve Facebook
1. Instagram'ı **Profesyonel hesap → İşletme** yap: Ayarlar → Hesap türü ve araçlar.
2. Bir **Facebook Sayfası**na bağla: Instagram → Ayarlar → İşletme → Facebook Sayfasını bağla.

### 2. GitHub (görselleri barındırır, zamanlayıcı çalıştırır, ücretsiz)
1. github.com'da hesap aç. **Public** bir depo oluştur: `nitro-instagram`.
2. Bu klasördeki her şeyi depoya yükle. `cache/` ve `out/` hariç tutulur.
3. Depo → Settings → Pages → *Deploy from a branch* → `main` / `/docs` → Save.
   Adres şöyle olur: `https://KULLANICIADIN.github.io/nitro-instagram`
4. Depo → Settings → Secrets and variables → Actions:
   - **Variables** sekmesi: `PUBLIC_BASE_URL` = yukarıdaki adres
   - **Secrets** sekmesi: `IG_ACCESS_TOKEN` ve `IG_USER_ID` (3. adımda alınacak)

### 3. Meta erişim anahtarı (süresiz token)
1. developers.facebook.com → My Apps → **Create App** → tür: *Business*.
2. Uygulamaya **Instagram Graph API** ürününü ekle.
3. business.facebook.com → Ayarlar → Kullanıcılar → **Sistem kullanıcıları** → *Ekle* (Admin).
4. Sistem kullanıcısına varlık ata: Facebook Sayfan, Instagram hesabın ve uygulama (tam kontrol).
5. *Token oluştur* → uygulamayı seç → süre: **Hiçbir zaman** → izinler:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`
6. Token'ı GitHub Secret `IG_ACCESS_TOKEN` olarak kaydet.
7. `IG_USER_ID` değerini öğrenmek için bu klasörde şunu çalıştır:
   `IG_ACCESS_TOKEN=token python3 scripts/publish.py --check`
   Çıkan `IG_USER_ID=...` değerini Secret olarak ekle. Graph API Explorer'da `me/accounts?fields=instagram_business_account` sorgusu da aynı bilgiyi verir.

### 4. Instagram bio linki
Profili düzenle → Bağlantılar → `https://KULLANICIADIN.github.io/nitro-instagram/`

### 5. Başlat
Actions → *Instagram otomasyonu* → Run workflow → task: `plan`. Planı ve görselleri üretir. Sonrası otomatik çalışır.

## Rutin iş yükün: haftada ~2 dk (isteğe bağlı)

- `TAKVIM.md` dosyasına GitHub'dan göz at: tarih, ürün, görsel ve açıklamalar burada.
- Bir paylaşımı iptal etmek için `data/calendar.json` içinde o kaydın `"status"` değerini `"skipped"` yap.
- Bir paylaşım hata verirse GitHub e-posta gönderir. Hata metni `data/calendar.json` içindeki `error` alanındadır.

## Ayarlar (`config.json`)

- `posts` / `stories`: gün ve saatler. Saat değiştirirsen `.github/workflows/instagram.yml` içindeki cron satırlarını da güncelle. Cron saatleri UTC'dir, TR saatinden 3 çıkar.
- `auto_publish: false` yaparsan planlar `draft` olarak kalır ve yayınlanmaz.
- `repeat_after_days`: aynı ürünün tekrar paylaşılması için gereken gün sayısı.

## Bilinen sınırlar

- Instagram API'si story'ye **link etiketi** ekleyemez. Story'ler "Link profilde" yönlendirmesi yapar. İstersen 20:30 story'lerini telefondan elle paylaşıp link etiketi ekleyebilirsin.
- Görseller sitedeki ürün fotoğraflarından üretilir. Fotoğrafı kötü olan ürünün görseli de zayıf olur.
- GitHub zamanlayıcısı 5-20 dk gecikebilir. 3 saatten fazla geciken paylaşım `missed` olarak atlanır.
- Açıklamalar yalnızca sitedeki bilgileri kullanır: fiyat, teknik özellik, kargo ve iade. Sitede indirim yoksa indirim yazmaz.

## Dosyalar

| Dosya | Görev |
|---|---|
| `scripts/scrape.py` | Site haritasından tüm ürünleri çeker → `data/products.json` |
| `scripts/plan.py` | Ürün seçer, görsel ve açıklama üretir → `data/calendar.json`, `TAKVIM.md`, `docs/` |
| `scripts/render.py` | Post (1080×1350) ve story (1080×1920) şablonları, headless Chrome ile |
| `scripts/content.py` | Kancalar, açıklamalar, hashtag'ler, sezon takvimi |
| `scripts/publish.py` | Zamanı gelenleri Instagram Graph API ile yayınlar |
| `scripts/onizleme.py` | Takvimi görselleriyle tek sayfada gösterir → `out/onizleme.html` (yerel inceleme) |
