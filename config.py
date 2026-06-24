# Bu dosya Friday'in tüm sabit ayarlarını içerir.
# Asistan adı, ses tipi veya uyandırma kelimeleri gibi ayarları
# değiştirmek istersen sadece bu dosyayı düzenlemen yeterli.

# Asistanın adı — tüm modüller buradan okur
ASISTAN_ISMI = "Friday"

# Kullanılacak ses tipi (Microsoft Edge TTS — yalnızca SES_MOTORU="edge" yedeğinde)
# Türkçe erkek ses: "tr-TR-AhmetNeural"
# Türkçe kadın ses: "tr-TR-EmelNeural"
SES_TIPI = "tr-TR-AhmetNeural"

# Her konuşmada geçici olarak oluşturulan ses dosyasının adı
GECICI_SES_DOSYASI = "friday_ses.mp3"

# ── SES MOTORU SEÇİMİ (TTS) ───────────────────────────────────────────────────
# "piper" → Piper TTS, CPU'da çalışır, ÇOK hızlı, hazır Türkçe ses (VARSAYILAN).
#           GPU'yu tamamen LLM'e (qwen3:8b) bırakır → ses gecikmesi/çakışma biter.
# "xtts"  → Coqui XTTS-v2 klonlanmış SESİM, GPU'da çalışır, kaliteli AMA YAVAŞ.
#           DİKKAT: "xtts" iken XTTS (~2GB) + LLM 8B (~6GB) GPU'da ÇAKIŞABİLİR;
#           ses üretimi yavaşlar. Yani "xtts" = kaliteli ama yavaş; "piper" = hızlı.
# "edge"  → Microsoft Edge TTS (internet gerekli) — son çare yedek.
SES_MOTORU = "piper"

# Piper ses modeli dosyaları (piper_sesler/ klasöründe). .onnx + .onnx.json birlikte.
# NOT: Türkçe Piper'da tek ses var (dfki, medium). Tonu aşağıdaki ayarlarla değiştiririz.
PIPER_MODEL_YOLU  = "piper_sesler/tr_TR-dfki-medium.onnx"
PIPER_CONFIG_YOLU = "piper_sesler/tr_TR-dfki-medium.onnx.json"

# ── PIPER SES TONU (enerjik/canlı ayar) ───────────────────────────────────────
# length_scale : konuşma hızı. 1.0 = normal. DÜŞÜK = HIZLI/ENERJİK, yüksek = yavaş/sakin.
# noise_scale  : tonlama değişkenliği. Yüksek = daha canlı/duygusal, düşük = düz/monoton.
# noise_w      : hece süresi değişkenliği. Yüksek = daha dinamik/hareketli ritim.
# Daha enerjik/heyecanlı bir ses için: hız biraz artırıldı, tonlama canlandırıldı.
PIPER_LENGTH_SCALE = 0.9    # ~%10 daha hızlı → enerjik (daha da hızlı: 0.85)
PIPER_NOISE_SCALE  = 0.75   # daha canlı tonlama (varsayılan ~0.667)
PIPER_NOISE_W      = 0.9    # daha dinamik ritim (varsayılan ~0.8)

# Geriye uyumluluk: eski kod KLONLANMIS_SES_KULLAN okuyordu; SES_MOTORU'ndan türetilir.
# (Tek doğruluk kaynağı SES_MOTORU'dur — ses motorunu DEĞİŞTİRMEK için SES_MOTORU'nu düzenle.)
KLONLANMIS_SES_KULLAN = (SES_MOTORU == "xtts")

# Mikrofon kaydını metne çevirirken kullanılacak geçici WAV dosyası
GECICI_DINLEME_DOSYASI = "dinleme_gecici.wav"

# True  → Whisper ile offline ses tanıma (internet gerektirmez, GPU kullanır)
# False → Google Speech Recognition'a dön (internet gerektirir, kurulum gerekmez)
OFFLINE_DINLEME_KULLAN = True

# Whisper model adı, çalışma cihazı ve hesaplama tipi.
# YENİ MİMARİ: Whisper CPU'da → GPU tamamen LLM'e (qwen3:8b) kalır.
#   "medium" / "cpu" / "int8" → doğruluk/hız dengesi iyi (VARSAYILAN, CPU için önerilen)
#   "small"  / "cpu" / "int8" → daha hızlı ama biraz daha az doğru
#   "large-v3" / "cuda" / "int8_float16" → GPU'da en doğru (artık ÖNERİLMEZ: GPU LLM'in)
# ses_tanima.py cuda başlatma hatası alırsa otomatik olarak "small"/"cpu"'ya düşer.
WHISPER_MODEL   = "medium"
WHISPER_DEVICE  = "cpu"
WHISPER_COMPUTE = "int8"

# İNTERNETSİZ (offline) yükleme. True → Whisper modeli YALNIZCA yerel önbellekten
# yüklenir, huggingface.co'ya BAĞLANMAYI DENEMEZ.
# Sebep: internet yok/sınırlıyken faster-whisper ağ denemesi yapıp SSL hatası
# ("wrong version number", port 443) verip yüklemeyi çökertiyordu. Model zaten
# indirilmiş (medium) → offline yükleme sorunsuz çalışır ve açılış hızlanır.
# YENİ/indirilmemiş bir modele geçeceksen: bir kez False yap (online indir), sonra True'ya dön.
WHISPER_OFFLINE = True

# ── SILERO VAD (Ses Etkinliği Algılama) ───────────────────────────────────────
# faster-whisper içinde hazır gelen Silero VAD'ı etkinleştirir. Konuşmayı
# sessizlik/gürültüden ayırır: gürültüyü işlemez, konuşma başını/sonunu doğru bulur.
# CPU'da çalışır, çok hafiftir (Whisper zaten CPU'da → uyumlu, ek gecikme yok denecek kadar az).
VAD_KULLAN = True
# Konuşma algılama eşiği (0.0-1.0). Gürültülü ortamda 0.6'ya çıkarılabilir.
VAD_ESIK = 0.5
# Bu kadar ms sessizlik = "konuşma bitti". Çok kısa → cümle ortasında keser;
# çok uzun → bekletir. 500 ms iyi denge.
VAD_MIN_SESSIZLIK_MS = 500
# Konuşmanın başına/sonuna bırakılan pay (ms) — kelime başı/sonu kesilmesin.
VAD_KONUSMA_PAY_MS = 200

# openWakeWord uyandırma skoru eşiği (0.0-1.0).
# Düşürürsen daha kolay tetiklenir ama yanlış pozitif artar;
# yükseltirsen daha güvenilir ama daha net söylemek gerekir.
UYANDIRMA_ESIGI = 0.5

# Uyandırma kelimelerinin listesi.
# Ses tanıma servisi "friday"i bazen farklı yazabilir (freyd, fryday vb.),
# bu yüzden bilinen tüm varyasyonları buraya ekliyoruz.
UYANDIRMA_KELIMELERI = [
    "friday",
    "hey friday",
    "freyd",
    "hey freyd",
    "freyday",
    "hey freyday",
    "fryday",
    "hey fryday",
    "fridey",
    "hey fridey",
    "frayday",
    "hey frayday",
]

# ── DOSYA ARAMA (Everything / es.exe) ─────────────────────────────────────────
# Everything (voidtools) tüm diskleri anında indeksler; es.exe komut satırı aracı
# milisaniyede sonuç verir. ÖN KOŞUL: Everything kurulu + ÇALIŞIR durumda, es.exe indirilmiş.
# Varsayılan: proje klasöründeki es.exe. Farklı yerdeyse tam yolu buraya yaz
# (örn. r"C:\Everything\es.exe").
ES_YOLU = r"d:\JARVIS\es.exe"

# G-Helper çalıştırılabilir dosyasının tam yolu.
# G-Helper kurulu değilse ya da farklı bir dizindeyse buradan değiştir.
# ASUS fan modu, GPU modu ve klavye ışığı WMI ile kontrol edilir;
# WMI başarısız olursa son çare olarak G-Helper penceresi açılır.
G_HELPER_YOLU = r"C:\GHelper\GHelper.exe"

# ── LLM BEYNİ AYARLARI ───────────────────────────────────────────────────────
# LLM_KULLAN=False → beyin.py hiç çağrılmaz; sistem tamamen kural tabanlı çalışır.
# Ollama kapalıyken veya düşük kaynak modunda False yap.
LLM_KULLAN = True

# Ollama'da kullanılacak model adı. Yüklü modelleri görmek için: ollama list
# YENİ: qwen3:8b — daha akıllı beyin. GPU'da çalışır (TTS+Whisper CPU'ya alındı,
# GPU artık tamamen LLM'in → çakışma yok).
LLM_MODEL = "qwen3:8b"

# True → Qwen3 serisi için "think=False" parametresi gönderilir — daha hızlı yanıt.
# False → Düşünme modu açık kalır — daha yavaş ama potansiyel olarak daha doğru.
LLM_DUSUNME_KAPALI = True

# LLM bağlam penceresi (num_ctx). 4096 = VRAM'i şişirmeyen makul değer.
LLM_BAGLAM = 4096

# Model bellekte ne kadar kalsın (keep_alive). "30m" → 8B model yeniden yüklenmesin,
# ilk komuttan sonra GPU'da hazır beklesin (her sorguda yeniden yükleme gecikmesi olmaz).
LLM_KEEP_ALIVE = "30m"

# ── GPU BELLEK STRATEJİSİ ─────────────────────────────────────────────────────
# YENİ MİMARİ: TTS (Piper) ve Whisper CPU'da → GPU TAMAMEN LLM'e kaldı.
# Bu yüzden LLM artık GPU'da çalışır (her ikisi de False):
#   LLM_CPU_MODU=False     → num_gpu varsayılan (GPU kullanılır)
#   LLM_HEMEN_BOSALT=False → keep_alive=LLM_KEEP_ALIVE (model GPU'da kalır)
# NOT: Yalnızca SES_MOTORU="xtts" yapılırsa XTTS(~2GB)+LLM 8B(~6GB) GPU'da
#      çakışabilir; o durumda bu ayarları gözden geçir.
LLM_HEMEN_BOSALT = False
LLM_CPU_MODU     = False
