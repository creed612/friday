# Bu dosya Coqui XTTS-v2 modeliyle ses klonlama yapar.
# İlk çağrıda model GPU'ya yüklenir (~birkaç saniye).
# Sonraki çağrılarda önbellekten hızlıca çalışır.

import os
import threading
import torch
import torchaudio
from TTS.api import TTS

from config import GECICI_SES_DOSYASI

_PROJE_KLASORU = os.path.dirname(os.path.abspath(__file__))

_MP3_KAYNAK = os.path.join(_PROJE_KLASORU, "voice record for ai.mp3")
_WAV_KAYNAK = os.path.join(_PROJE_KLASORU, "benim_sesim.wav")
_WAV_CIKTI  = os.path.join(_PROJE_KLASORU, "friday_ses_klon.wav")

# Kayıttan 3 farklı noktadan (~%10, %50, %80) çıkarılan 20 saniyelik referans parçaları.
# Birden fazla referans XTTS'in ses benzerliğini artırır.
_REFERANS_DOSYALARI = [
    os.path.join(_PROJE_KLASORU, "referans_1.wav"),
    os.path.join(_PROJE_KLASORU, "referans_2.wav"),
    os.path.join(_PROJE_KLASORU, "referans_3.wav"),
]

_model = None
# XTTS thread-safe değil: iki kez yüklenirse GPU VRAM taşar.
# Lock ile double-checked loading — hem yükleme hem de arka plan önyükleme güvenli olur.
_model_kilidi = threading.Lock()


def is_model_loaded() -> bool:
    """XTTS modeli yüklenmiş mi? ses.py konus() bu kontrolle edge_tts fallback kararı verir."""
    return _model is not None


def _wav_hazirla():
    if os.path.exists(_WAV_KAYNAK):
        return
    try:
        dalga, ornekleme_hizi = torchaudio.load(_MP3_KAYNAK)
        if dalga.shape[0] > 1:
            dalga = torch.mean(dalga, dim=0, keepdim=True)
        if ornekleme_hizi != 24000:
            resample = torchaudio.transforms.Resample(ornekleme_hizi, 24000)
            dalga = resample(dalga)
        torchaudio.save(_WAV_KAYNAK, dalga, 24000)
    except Exception as hata:
        raise RuntimeError(f"Ses dosyası WAV'a çevrilemedi: {hata}")


def _referans_dosyalari_hazirla():
    """Tam kayıttan %10, %50, %80 noktalarında 3 ayrı 20 saniyelik parça çıkarır."""
    if all(os.path.exists(d) for d in _REFERANS_DOSYALARI):
        return

    _wav_hazirla()
    dalga, sr = torchaudio.load(_WAV_KAYNAK)
    toplam = dalga.shape[1]
    klip = 20 * sr  # 20 saniyelik klip uzunluğu (örnek sayısı)

    for i, oran in enumerate([0.10, 0.50, 0.80]):
        baslangic = int(toplam * oran)
        bitis = min(baslangic + klip, toplam)
        torchaudio.save(_REFERANS_DOSYALARI[i], dalga[:, baslangic:bitis], sr)


def _model_yukle():
    global _model
    if _model is not None:
        return
    with _model_kilidi:
        if _model is not None:  # double-checked: başka thread yüklemişse tekrar yükleme
            return
        _referans_dosyalari_hazirla()
        cihaz = "cuda" if torch.cuda.is_available() else "cpu"
        _model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(cihaz)


def konus_klonlanmis(metin):
    """
    Metni klonlanmış sesle WAV dosyasına kaydeder; dosya yolunu döner.

    - Kısa metinler (< 200 karakter): split_sentences=False → tek parça,
      parçalar arası sessizlik oluşmaz.
    - Uzun metinler: split_sentences=True → XTTS token limitini aşmamak için
      cümlelere böler.
    """
    _model_yukle()

    _model.tts_to_file(
        text=metin,
        speaker_wav=_REFERANS_DOSYALARI,
        language="tr",
        file_path=_WAV_CIKTI,
        speed=1.15,
        temperature=0.75,
        split_sentences=len(metin) >= 200,
    )

    return _WAV_CIKTI
