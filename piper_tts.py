# piper_tts.py — Piper TTS (CPU) konuşma motoru
#
# NEDEN PIPER?
#   GPU'yu tamamen LLM'e (qwen3:8b) ayırmak için TTS'i CPU'ya aldık.
#   Piper CPU'da ÇOK hızlıdır (onnxruntime) ve internet gerektirmez.
#   Klonlanmış XTTS (GPU, ~2GB) kod olarak KALIR — config.SES_MOTORU="xtts" ile
#   geri dönülebilir (bkz. ses.py konus()).
#
# MİMARİ: Bu modül yalnızca SENTEZLER → wav dosya yolu döndürür.
#   Oynatma (pygame) ses.konus() içinde MERKEZİ yapılır — böylece konuşma kilidi
#   (_konusma_kilidi) ve çakışma yönetimi tek yerde kalır (XTTS ile aynı desen).

import os
import wave
import threading

from piper.voice import PiperVoice
from piper.config import SynthesisConfig

from config import (
    PIPER_MODEL_YOLU, PIPER_CONFIG_YOLU,
    PIPER_LENGTH_SCALE, PIPER_NOISE_SCALE, PIPER_NOISE_W,
)

# Ses tonu ayarı (config'ten): enerjik/canlı delivery için hız + tonlama.
# length_scale DÜŞÜK = hızlı/enerjik; noise yüksek = daha canlı.
_SYN_CONFIG = SynthesisConfig(
    length_scale=PIPER_LENGTH_SCALE,
    noise_scale=PIPER_NOISE_SCALE,
    noise_w_scale=PIPER_NOISE_W,
)

_PROJE_KLASORU = os.path.dirname(os.path.abspath(__file__))

# Üretilen konuşma bu sabit dosyaya yazılır (her çağrıda üzerine yazılır).
PIPER_WAV_CIKTI = os.path.join(_PROJE_KLASORU, "friday_piper.wav")

_voice = None
# Yükleme kilidi: arka plan önyükleme ile ilk konus() çağrısı çakışmasın (XTTS deseni).
_voice_kilidi = threading.Lock()


def is_model_loaded() -> bool:
    """Piper sesi yüklenmiş mi? ses.konus() bunu kontrol edip edge_tts'e düşebilir."""
    return _voice is not None


def _model_yukle():
    # PiperVoice'u bir kez yükler (singleton). CPU'da çalışır (use_cuda=False).
    global _voice
    if _voice is not None:
        return
    with _voice_kilidi:
        if _voice is not None:   # double-checked: başka thread yüklemiş olabilir
            return
        model_yolu  = PIPER_MODEL_YOLU
        config_yolu = PIPER_CONFIG_YOLU
        # Göreli yol verildiyse proje klasörüne göre çöz
        if not os.path.isabs(model_yolu):
            model_yolu = os.path.join(_PROJE_KLASORU, model_yolu)
        if config_yolu and not os.path.isabs(config_yolu):
            config_yolu = os.path.join(_PROJE_KLASORU, config_yolu)

        # config_path None ise Piper, model_yolu + ".json"u otomatik arar;
        # yine de açıkça veriyoruz (netlik + farklı isimlere tolerans).
        _voice = PiperVoice.load(model_yolu, config_path=config_yolu, use_cuda=False)
        print(f"[Piper] Ses modeli yüklendi (CPU): {os.path.basename(model_yolu)}")


def piper_uret(metin: str) -> str:
    """Metni Piper ile sentezleyip WAV dosyasına yazar; dosya yolunu döndürür.

    ses.konus() bu yolu alıp pygame ile çalar (oynatma orada merkezi).
    """
    _model_yukle()
    # synthesize_wav: metni wave.Wave_write nesnesine yazar (piper-tts 1.4.x API).
    # _SYN_CONFIG ile enerjik ton uygulanır (hız + tonlama, config'ten ayarlanır).
    with wave.open(PIPER_WAV_CIKTI, "wb") as wf:
        _voice.synthesize_wav(metin, wf, syn_config=_SYN_CONFIG)
    return PIPER_WAV_CIKTI
