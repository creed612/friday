# Bu dosya Friday'in ses tanıma özelliğini içerir.
# faster-whisper kullanır; model ilk çağrıda GPU'ya yüklenir (CUDA 12 + cuDNN 9).
# GPU başlatma hatası olursa otomatik olarak CPU/small modeline düşer.

import os

# Windows'ta HuggingFace Hub sembolik bağlantı oluşturamaz; bu uyarıyı/hatayı
# devre dışı bırakmak hem uyarıyı hem de takılma sorununu önler.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

from config import (
    WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_OFFLINE,
    VAD_KULLAN, VAD_ESIK, VAD_MIN_SESSIZLIK_MS, VAD_KONUSMA_PAY_MS,
)

# ── İNTERNETSİZ (OFFLINE) YÜKLEME ─────────────────────────────────────────────
# HF Hub'ı offline moduna al → faster-whisper modeli YALNIZCA yerel önbellekten
# yükler, huggingface.co'ya (port 443) BAĞLANMAYI DENEMEZ.
# Sebep: internet yok/sınırlıyken ağ denemesi SSL hatası ("wrong version number",
# 1006) verip model yüklemesini çökertiyordu. Bu env değişkenleri faster_whisper
# (ve onun kullandığı huggingface_hub) import edilmeden ÖNCE ayarlanmalıdır.
if WHISPER_OFFLINE:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

# ── GPU HAZIRLIĞI — YALNIZCA WHISPER_DEVICE="cuda" İSE ───────────────────────
# YENİ MİMARİ: Whisper CPU'da çalışıyor (WHISPER_DEVICE="cpu"). Bu durumda GPU'ya
# HİÇ DOKUNMUYORUZ — torch.zeros(1, device="cuda") bile CUDA context'i açıp
# ~birkaç yüz MB VRAM tüketir; o VRAM tamamen LLM'e (qwen3:8b) kalmalı.
# Aşağıdaki cuDNN DLL + torch CUDA önyükleme bloğu SADECE cuda seçiliyse çalışır.
if WHISPER_DEVICE == "cuda":
    # nvidia-cublas-cu12 / nvidia-cudnn-cu12 DLL'leri Windows'ta otomatik PATH'e
    # eklenmez; os.add_dll_directory() ile ctranslate2'nin doğru cuDNN 9'u bulmasını
    # sağlarız. Bu blok faster_whisper import edilmeden ÖNCE çalışmalıdır.
    try:
        import nvidia.cublas
        import nvidia.cudnn
        _cublas_dll = os.path.join(nvidia.cublas.__path__[0], "bin")
        _cudnn_dll  = os.path.join(nvidia.cudnn.__path__[0],  "bin")
        if os.path.isdir(_cublas_dll):
            os.add_dll_directory(_cublas_dll)   # cublas64_12.dll vb.
        if os.path.isdir(_cudnn_dll):
            os.add_dll_directory(_cudnn_dll)    # cudnn64_9.dll vb.
    except (ImportError, AttributeError, OSError):
        pass

    # PyTorch'u ctranslate2'den ÖNCE import edip CUDA'yı başlatırız (cuDNN sırası).
    import torch
    if torch.cuda.is_available():
        torch.zeros(1, device="cuda")

from faster_whisper import WhisperModel

# Model singleton — modül ömrü boyunca bir kez yüklenir
_model = None


def _model_yukle():
    # İlk çağrıda modeli GPU'ya yüklemeyi dener.
    # Başarısız olursa (VRAM yetersizliği, sürücü uyumsuzluğu vb.)
    # "small" modeli CPU'da int8 ile yükler — Friday her durumda çalışmaya devam eder.
    global _model
    if _model is not None:
        return

    # ── 1. TERCİH: config.py'daki ayarlarla yükle (varsayılan: medium, cpu, int8) ──
    try:
        # compute_type config'ten gelir: CPU için "int8" (hızlı, düşük bellek),
        # cuda için genelde "int8_float16". WHISPER_COMPUTE bunu belirler.
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print(f"[Whisper] '{WHISPER_MODEL}' modeli {WHISPER_DEVICE.upper()}'da yüklendi "
              f"(compute_type={WHISPER_COMPUTE}).")

    except Exception as hata:
        # CUDA/model/bellek hatası → hafif "small" modeli CPU'da int8 ile (yedek)
        print(f"[Whisper] '{WHISPER_MODEL}' yüklemesi başarısız: {hata}")
        print("[Whisper] 'small' modeli CPU/int8 ile yükleniyor (yedek)...")
        _model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[Whisper] 'small' modeli CPU'da hazır (yedek mod).")


# Whisper'a verilen ipucu: modelin bu kelimelere yatkın olmasını sağlar.
# Komutlarda sık geçen kelimeler burada listelenince Whisper onları daha az
# bozuk tanır (örn. "duraklat" → "durak tat" gibi hatalar azalır).
_INITIAL_PROMPT = (
    "Friday sesli asistan. Komutlar: tarayıcı aç, not defteri aç, hesap makinesi aç, "
    "bilgisayarı kapat, dosya ara, hava durumu, takvim, not al, hatırlat, çevir, "
    "çal, duraklat, devam et, sonraki şarkı, önceki şarkı, sesi aç, sesi kıs, "
    "ne çalıyor, şarkıyı beğen, karıştır, tekrarla, notlarımı oku."
)


# ── WHISPER HALÜSİNASYON FİLTRESİ ────────────────────────────────────────────
# Whisper, sessizlik/gürültüde eğitim verisindeki YouTube altyazı kredilerini
# ("Altyazı M.K.", "Amara.org", "abone olun", "izlediğiniz için teşekkürler"…)
# UYDURUR. Bunlar gerçek komut değildir; aşağıdaki ifadelerden biriyse boş döndür.
# (Yaşanan hata: "altyazı m.k." → fuzzy "çal" → müzik çalıyordu.)
_HALUSINASYON_ICEREN = (
    "altyazı", "alt yazı", "amara.org", "amara org",
    "abone ol", "izlediğiniz için", "izlemeye devam", "kanalıma abone",
    "beğenmeyi unutmayın", "subscribe",
)


def _halusinasyon_mu(metin: str) -> bool:
    # metin küçük harf, strip edilmiş gelir.
    t = metin.strip().strip(".!?,;:- ").lower()
    if not t:
        return True   # boş → işleme
    if any(ifade in t for ifade in _HALUSINASYON_ICEREN):
        return True
    # "m.k." gibi yalnızca 1-2 harf içeren gürültü artefaktları
    harfler = [c for c in t if c.isalpha()]
    if len(harfler) <= 2:
        return True
    return False


# ── SILERO VAD PARAMETRELERİ ─────────────────────────────────────────────────
# faster-whisper'a verilecek VAD ayarları (config.py'den okunur, oradan ayarlanabilir).
# min_speech_duration_ms=250: çok kısa sesleri/tıkırtıları konuşma sayma (sabit, makul).
_VAD_PARAMETRELERI = {
    "threshold":               VAD_ESIK,
    "min_speech_duration_ms":  250,
    "min_silence_duration_ms": VAD_MIN_SESSIZLIK_MS,
    "speech_pad_ms":           VAD_KONUSMA_PAY_MS,
}


def metni_tanı(ses_dosyasi_yolu):
    _model_yukle()

    # initial_prompt: Whisper'ı Friday'in komut kelime dağarcığına yönlendirir.
    # beam_size=5: doğruluk ve hız arasındaki standart denge.
    # language="tr": dil tespiti bekleme süresini ortadan kaldırır.
    #
    # VAD (Silero): vad_filter=True ise sesteki KONUŞMA bölümleri bulunur, sessizlik/
    # gürültü atılır → yanlış tanıma azalır, konuşma sonu doğru algılanır. CPU'da hafif.
    # VAD_KULLAN=False yapılırsa filtre kapanır (ham ses doğrudan işlenir).
    parcalar, _ = _model.transcribe(
        ses_dosyasi_yolu,
        language="tr",
        beam_size=5,
        initial_prompt=_INITIAL_PROMPT,
        vad_filter=VAD_KULLAN,
        vad_parameters=_VAD_PARAMETRELERI if VAD_KULLAN else None,
    )

    metin = " ".join(p.text.strip() for p in parcalar).strip().lower()

    # Halüsinasyon/gürültü artefaktı ise (altyazı m.k., abone ol vb.) boş döndür —
    # böyle metinler komut işleyiciye GİTMEZ, sahte komut tetiklenmez.
    if _halusinasyon_mu(metin):
        print(f"[Whisper] Halüsinasyon/gürültü elendi: {metin!r}")
        return ""

    return metin
