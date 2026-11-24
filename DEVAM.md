DURUM: TAMAM
Son güncelleme: 2026-11-24 (yerel oturum; canlı onayı bekliyor)

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
- `scripts/reel.py` (KAPALI, sahibi reel istemedi; kod duruyor): `make_reel(frames, out, hold=2.3, fade=0.45, last_hold=3.2, fps=30)`; 5 kare ≈ 10,6 sn.
- `scripts/publish.py` (yeniden yazıldı; bulut oturumunda okundu, şema v2 ile uyumlu): Graph API v23.0; `--check`, `--probe`; çift yayın
  kilidi; sayfa üreticilerini çağırır: `bio.build_bio`, `simulasyon.build_sim`, `takvim.build_takvim` (yoksa atlar).
- `scripts/report.py` HAZIR: `data/metrics.json`, `data/scores.json`, `RAPOR.md`; `--no-api`.
- `scripts/common.py`, `scripts/graph.py` ortak yardımcılar. `scripts/gorev.py` Actions giriş noktası.
- `.github/workflows/instagram.yml`: yarım saatte bir `publish` (kilitliyken hiçbir şey yapmaz), 04:10 TR `plan`,
  elle `check|plan|publish|probe|report`. Çıktıları (`data`, `docs`, `RAPOR.md`) `main`'e geri yazar.
- Yayın: GitHub Pages `main:/docs` → https://erguderdemir.github.io/nitro-instagram/

## 4. Durum ve kalan işler

TAMAMLANDI (24 Kasım, yerel oturum + Actions):
- Bulut çalışması (`claude/devam`) main'e alındı; Claude GitHub App depoda yazma yetkili.
- Reel üretimi kapatıldı (sahibinin isteği): Pzt ve Cum akışı da ürün carousel'i. Takvim 148 kayıt
  (111 story, 36 carousel, 1 görsel), 25 Kas → 31 Ara.
- `check` (token sahibi nitro-instagram-bot, 24 saatte 0/100) ve `probe` (carousel 8 medya, görsel, story
  container FINISHED, yayın yok) başarılı.
- GERÇEK ürün fotoğraflarıyla göz denetimi yapıldı. Düzeltilenler: yanlış renk fotoğrafı (Carraro antrasit, Sorrento
  koyu yeşil 3. kare), ölçü çizimli lamba görseli (`common.GORSEL_ENGEL`), sahibinden filigranlı Tanke TK6
  (`content.HARIC_SLUG`), büyük harf Türkçe başlıklarda İ/Ş/Ğ çakışması (line-height 1.04), ipucu kapağında
  "madde" rozeti, ipucu postlarında ürün yerine "profildeki link" CTA, liste alt başlığında küçük harf, alt
  metinde "?." çift noktalama, İngilizce teknik değerler (STEEL, SUSPENSION FORK) Türkçeye.
- `denetim.py` yeni kurallar: engelli görsel, çift noktalama.
- İkinci göz denetimi (24 Kasım): başlık son satırında Ş/Ç alt çengeli kesilmesi (`.hl/.th/.q .h` alt dolgu),
  yarım bisiklet/galeri oku/MOSSO/duvar içeren kareler `GORSEL_ENGEL`'e, uygun fotoğrafı olmayan 10 ürün
  `HARIC_SLUG`'a; teknik değer biçimi (`content._spec_value`: büyük harf → başlık, V/Ah birimi), "Orjinal",
  "Cable Lock", çift "Fren Sistemi"; çocuk jant ipucu için `cta: "cocuk"` (kategori linki, CTA karesi, story).
- Sabah değer story'leri konu linkine bağlı (`plan.py` tip_target/fact_target/_linked_value).
- Üçüncü tur (24 Kasım): ürün story çıkartması hep "ÜRÜNE GİT"; `content.FORMATS` (mm/ml/psi boşluğu, 26x1.95,
  34'lü, 16-20 Jant, "Dağ Bisikleti", model kodu büyük harf); 5 ürün daha `HARIC_SLUG`'a, 4 görsel `GORSEL_ENGEL`'e;
  `title_for` başlığı tüm takvimde en az kullanılanlardan seçer (gün arası tekrar yok); `render.hl` sayı+sözcük
  arası &nbsp;; `.h` line-height 1.08, `.q .h` 1.14 (Ş çengeli–Ü noktası çakışması).

BEKLEYEN (yalnız sahibinin onayıyla):
1. Canlıya geçiş: `config.json` → `"live": true`. Sahibi simülasyonu
   (https://erguderdemir.github.io/nitro-instagram/onizleme/) görüp onay verene kadar AÇMA.
2. Onaydan sonra yerel oturum (sahibinin Chrome'u): Business Suite'te link çıkartmalı story planlama
   (`docs/suite/`), Öne Çıkanlar.

Günlük önizleme rutini: her gün 05:00 UTC (08:00 TR) bulut oturumu o günün kayıtlarını denetler ve özet verir
(https://claude.ai/code/routines/trig_01JpWx6k9XF1YtHEQKGa2Xq2).

Yayın güvencesi (bilgisayardan bağımsız): Actions 15 dakikada bir (09:02–22:47 TR) zamanı gelen kaydı yayınlar;
geciken kayıt 3 saate kadar telafi edilir. Bulut bekçi rutini 2 saatte bir (09:50–21:50 TR) kaçan kayıt görürse
`claude/bekci-*` dalına `tetik.txt = publish` push eder; `birlestir.yml` main'e alıp `publish` başlatır
(https://claude.ai/code/routines/trig_01VXidum3KAj3Ghf2Wrk5Dc5). Business Suite'e planlanmamış linkli story,
API yedeğiyle ("Link profilde" sürümü) yine yayınlanır; yalnız tıklanabilir çıkartma olmaz.

Bilinen küçük notlar (site verisinden, bırakıldı): Conti iç lastik fotoğrafında farklı kutu, düşük çözünürlüklü
görsellerde bulanık dolgu, bandana fotoğraf çerçevesi, bazı mağaza fotoğraflarında arka plan, forma görselinde "İSMİNİZ" yazısı. Teknik özelliği 3'ten az üründe carousel 3 karedir.

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
- Akış (haftada 7): Pzt 19:30 ürün carousel (performans bisikleti, "Haftanın bisikleti"); Sal 19:30 ürün carousel (parça/
  aksesuar); Çar 19:30 ipucu carousel; Per 19:30 ürün carousel (mevsim); Cum 19:30 ürün carousel ("Hafta sonu vitrini");
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
