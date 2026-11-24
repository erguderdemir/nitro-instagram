DURUM: DEVAM EDİYOR
Son güncelleme: 2026-11-24 08:00 TR (bulut devam oturumu)

# Devir notu — nitro-instagram

İşi devralan oturum içindir. İlk satır `DURUM: TAMAM` ise iş bitmiştir: hiçbir şeyi değiştirme.

## 1. Amaç
@nitrobisiklet Instagram hesabını nitrobisiklet.com verisiyle tam otomatik yönetmek: 31 Aralık 2026'ya kadar
takvim; ajans kalitesinde post, story, reel; her üründe UTM'li link; bilgisayardan bağımsız yayın (GitHub Actions).
Hedef: en yüksek etkileşim, siteye trafik, satış. Depo sahibi denetçidir; tasarım ve kontrol sistemdedir.

## 2. Değişmez kurallar
1. Yayın kilidi: `config.json` içinde `"live": false` KALIR. Sahibi simülasyonu (docs/onizleme) görüp onaylamadan
   Instagram'a hiçbir şey yayınlanmaz, Business Suite'te hiçbir şey planlanmaz.
2. Sır yok: token/şifre isteme, yazma, loglama. `IG_ACCESS_TOKEN` yalnız GitHub Actions secret'ıdır.
3. Paket yalnız PyPI'den (`requirements.txt`). Başka kaynaktan indirme/çalıştırma yok.
4. Mantık hatası sıfır (sahibinin açık şartı). Yaşanmış örnekler: pompa ürününe "Karanlıkta görün" başlığı;
   "250 ₺ altı 5 hediye" başlığı altında 250 ₺ ve üstü ürün. Başlık ürünün kategorisine ve alt türüne kilitlenir;
   liste başlığındaki eşik ve adet seçilen ürünlerden hesaplanır (`all(fiyat < eşik)`, adet = ürün sayısı);
   kural sağlanamıyorsa içerik üretilmez. `scripts/denetim.py` sıfır bulgu vermeden teslim yok.
5. Uydurma indirim, kampanya, stok, süre yok; yalnız `data/site.json` gerçekleri. "Aynı gün servis" sitede var ama
   "her iş aynı gün biter" denmez; "48s" birimi yorumlanmaz. `old_price` hep boş: indirim iddiası yok.
6. Ürün adı ve teknik değer CSS ile büyük harfe çevrilmez (lang=tr → "SHİMANO"). Marka adı hep "NITRO" yazılır.
7. Scooter/motosiklet/otomobil ürünleri bisiklet içeriğine girmez ("Jump Starter", "Motosiklet Çantası",
   e-scooter iç lastiği/şarj aleti, "ORTLIEB E227 Bağlantı tokası" yedek parçası).
8. Sahibi merge/push için önceden onay verdi: `main`'e doğrudan push; olmuyorsa `claude/…` dalına push
   (`.github/workflows/birlestir.yml` dalı `main`'e alır). İş akışı dosyalarını değiştirme: GITHUB_TOKEN
   iş akışı dosyası içeren birleştirmeyi itemez. Görev mantığı `scripts/gorev.py` içindedir, orayı değiştir.
9. Kullanıcıya Türkçe; kod, yorum ve commit mesajları deponun üslubunda (Türkçe).

## 3. Mimari
- `scripts/scrape.py` site haritası → `data/products.json` (413 ürün; alanlar: url, slug, name, category, price,
  in_stock, description, specs, images…). `data/codes.json` slug → kısa kod (N101…), `data/site.json` mağaza
  gerçekleri, `data/tips.json` ipucu carousel'leri (8), story ipuçları (40), sorular (24).
- `scripts/render.py` HTML şablon → headless Chrome → Pillow JPEG. Post 1080×1350, story 1080×1920. HAZIR ve
  sınanmış. Şablonlar: p_cover/p_gallery/p_specs/p_detail/p_why/p_cta, l_cover/l_item, t_cover/t_step/t_end,
  b_newyear, s_product/s_promo/s_tip/s_question/s_trio/s_facts, r_hook/r_hero/r_specs/r_perks/r_cta;
  `render_all(jobs)`, `thumb`, `contact_sheet`, `prep(url)`; `STICKER = {x:0.5, y:0.781, w:0.5}`.
  Küçük kalanlar: `.q p` 54px; ürün adı/teknik değerde `text-transform:none`; `s_facts` link yoksa `fallback` ver.
- `scripts/reel.py` HAZIR: `make_reel(frames, out, hold=2.3, fade=0.45, last_hold=3.2, fps=30)`; 5 kare ≈ 10,6 sn.
- `scripts/publish.py` (yeniden yazıldı; bulut oturumunda okundu, şema v2 ile uyumlu): Graph API v23.0; `--check`, `--probe`; çift yayın
  kilidi; sayfa üreticilerini çağırır: `bio.build_bio`, `simulasyon.build_sim`, `takvim.build_takvim` (yoksa atlar).
- `scripts/report.py` HAZIR: `data/metrics.json`, `data/scores.json`, `RAPOR.md`; `--no-api`.
- `scripts/common.py`, `scripts/graph.py` ortak yardımcılar. `scripts/gorev.py` Actions giriş noktası.
- `.github/workflows/instagram.yml`: yarım saatte bir `publish` (kilitliyken hiçbir şey yapmaz), 04:10 TR `plan`,
  elle `check|plan|publish|probe|report`. Çıktıları (`data`, `docs`, `RAPOR.md`) `main`'e geri yazar.
- Yayın: GitHub Pages `main:/docs` → https://erguderdemir.github.io/nitro-instagram/

## 4. Durum ve kalan işler

YAPILDI (bulut devam oturumu, 24 Kasım; yerelde sahte ürün görselleriyle uçtan uca sınandı: 148 kayıt, 10 reel,
`denetim.py` dosyalar dahil 0 bulgu, 12 olumsuz sınamanın hepsi yakalandı):
- `scripts/content.py` baştan: 46 kural (alt tür) ve başlık havuzları, `MUST` ile bağımsız ad doğrulaması, hariç
  tutma, `clean_specs` (beyaz liste), kısa ad, tam cümle süzgeci, açıklama / alt metin / UTM, listeler, mevsim süzgeci.
- `scripts/plan.py` baştan: şema v2, 25 Kas → 31 Ara; listeler önce, sonra gün gün; reel = 5 kare; parmak iziyle
  fiyat/stok/şablon değişiminde yenileme; `data/yeniden.txt` ile baştan seçim; `--kuru`.
- `scripts/denetim.py`, `simulasyon.py`, `bio.py`, `takvim.py` (→ `docs/TAKVIM.md`; iş akışı kök dizini kaydetmediği
  için), `suite.py` (→ `docs/suite/`). Eski `onizleme.py`, eski takvim ve eski `docs/media` silindi.
- `render.py`: `.q p` 54px, ürün adı / teknik değer büyük harfe çevrilmez, "Neden NITRO" etiketi.
  `common.fmt_price`: kuruşlu fiyat yuvarlanmaz (93,53 ₺). `gorev.py`: yayından önce denetim.
- `config.json` ritim ayarları (live=false), `README.md` baştan.

KALDI (sırayla):
1. **PUSH.** Bulut oturumunun GitHub yazma izni yoktu (git push ve API 403: Claude GitHub App depoda yazma yetkili
   değil). Çalışma `claude/devam` dalında tek commit olarak hazır; oturum sahibine git paketi (bundle) olarak verildi.
   Yazma izni olan oturum: `git push -u origin claude/devam` (tetik.txt = `plan`; birlestir.yml main'e alır ve
   `plan` görevini başlatır).
2. Actions `plan` bitince `git pull`; `data/son-calisma.log` ve `data/denetim.json` (0 bulgu olmalı) denetlenir;
   GERÇEK ürün fotoğraflarıyla kontak föyü göz denetimi yapılır (bulutta siteye erişim yoktu, bu adım yapılamadı).
3. `tetik.txt` → `check`, sonra `probe` (yayın kilitli; günlükleri Actions'tan okunur).
4. İlk satır `DURUM: TAMAM`, özet; sahibinden canlıya geçiş onayı istenir (live anahtarını sahibi açar).

Bilinen notlar: site açıklamaları çoğunlukla pazarlama metni olduğu için yalnız yüklemle biten, iddiasız tam
cümleler alınır (16 ürün); teknik özelliği 3'ten az ürünlerde carousel 3 karedir. "Hediyeli" adlı ürün içerik dışıdır.

Yalnız yerelde (sahibinin Chrome'u) yapılabilenler, bulutta ATLA ve raporla: Business Suite'te link çıkartmalı
story planlama (onaydan sonra), Öne Çıkanlar, günlük önizleme bildirimi rutini.

## 5. Takvim şeması v2 ve ritim
Kayıt: `id` ("2026-11-25-post-1930" / "…-story-0930"), `date`, `time`, `type` post|story, `format`
carousel|reel|image|story, `theme` urun|ipucu|liste|servis|marka|promo|etkilesim, `kicker`, `title`, `hook`,
`media` (docs/ altına göreli: `media/<id>-1.jpg`…, reel `media/<id>.mp4`, story `media/<id>.jpg`), `cover`,
`thumb`, `caption`, `alt`, `alts`, `products` [{slug,name,price,code,category,link,bio_link,image}], `link`,
`bio_link`, `code`, `channel` api|suite, `sticker` {url,text,x,y,w}|null, `media_link` (`media/<id>-link.jpg`),
`ref`, `rule`, `status` planned|draft|published|skipped|missed|error.
- Linkli her story `channel:"suite"` + `sticker` (API link çıkartması desteklemez); `media[0]` API yedeği
  ("Link profilde"), `media_link` çıkartma boşluklu sürüm. Çıkartma metni ≤25: "ÜRÜNE GİT", "FİYATI GÖR",
  "MAĞAZAYA GİT", "SERVİS RANDEVUSU AL".
- Akış (haftada 7): Pzt 19:30 reel (performans bisikleti, "Haftanın bisikleti"); Sal 19:30 ürün carousel (parça/
  aksesuar); Çar 19:30 ipucu carousel; Per 19:30 ürün carousel (mevsim); Cum 19:30 reel (bisiklet, farklı kicker);
  Cmt 11:00 liste carousel (28 Kas kışa hazırlık, 5 Ara 250 ₺ altı hediye, 12 Ara 500 ₺ altı hediye, 19 Ara
  çocuklara yılbaşı, 26 Ara yükseltme); Paz 11:00 ürün carousel; 31 Ara yılbaşı marka postu (`b_newyear`).
- Story (günde 3): 09:30 değer (ipucu/servis/marka/soru, API); 12:30 ürün ("Günün ürünü", suite + link);
  20:30 günün postunun tanıtımı (suite + link).
- Instagram sınırları: en çok 5 etiket; görsel JPEG ≤8 MB; carousel ≤10; reel MP4 H264/AAC 9:16; ızgara 3:4 kırpar.

## 6. Katalog notları (mantık kuralları için)
- Kask (2) = ikisi de ÇOCUK kaskı. Eldiven: Asistan kısa parmak, Asistan ÇOCUK eldiveni, Rectus KIŞLIK eldiven.
- Pompa: Vona GP-03 266, Giyo GP-04S 300, Giyo GP-45E 350 (Jump Starter hariç). Aydınlatma (4) = hepsi lamba.
- "Zil, Korna, Ayna": zil 80–149, ayna 190–778 → alt tür ada göre. "Çamurluk ve Muhafaza": çamurluk + aynakol
  koruyucu. "Pedal ve Kal": pedal + bir pedal kolu. "Kimyasal": balata spreyi, zincir yağı, bakım spreyi, solüsyon.
- 250 ₺ ALTI havuz (tam 250 hariç): zil, ayna 190–240, matara kafesi 115–200, Polisport C600 220, bandana 189,
  Procycle PC-300 çanta 220, elcik 180. 500 ₺ altı: eldiven, telefon tutucu, kilit, pompa, Comet lamba 450…
- Çocuk listesi: Çocuk Bisikleti (7), Raptor çocuk kaskı, Asistan çocuk eldiveni, çocuk zili, çocuk selesi.
- Kış listesi: lamba, adı "Çamurluk" olanlar, Rectus kışlık eldiven, zincir yağlayıcı, balata.
- Gruplar eski `content.py` içindeki `GROUPS` tablosunda (yeniden yazarken koru).

## 7. Bulut oturumu için
- Chrome yoksa görsel üretme: kodu yaz, saf Python kısımlarını sına, push et. `tetik.txt` ilk satırına `plan`
  yazıp push edince Actions takvimi ve görselleri üretir, sonucu `main`'e yazar; günlük
  `data/son-calisma.log` içindedir. `git pull` ile al, denetle.
- Sahibi telefondan izler: kısa, net Türkçe rapor ver.
