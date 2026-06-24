# Bu dosya Friday'in sesli konuşma ve dinleme işlemlerini içerir.
# konus(), arka_plan_dinle(), komut_dinle() ve yaz() fonksiyonları burada tanımlıdır.

import speech_recognition as sr   # Sesi dinleyip metne çeviren kütüphane
import edge_tts                   # Doğal, kaliteli sesli konuşma kütüphanesi
import asyncio                    # edge_tts'in arka planda çalışması için gerekli
import pygame                     # Üretilen ses dosyasını çalmak için
import os                         # Geçici ses dosyasını silmek için
import threading                  # Eş zamanlı konus() çağrılarını sıralamak için
import pyaudio                    # Düşük gecikmeli mikrofon akışı (openWakeWord için)
import numpy as np                # Ses çerçevelerini diziye dönüştürmek için
from openwakeword.model import Model as _OWWModel  # "Hey Jarvis" uyandırma modeli

from config import (
    ASISTAN_ISMI, SES_TIPI, GECICI_SES_DOSYASI,
    SES_MOTORU, OFFLINE_DINLEME_KULLAN, GECICI_DINLEME_DOSYASI,
    UYANDIRMA_ESIGI,
)

# Offline ses tanıma aktifse Whisper modülünü senkron import et (cuDNN sıralama şartı):
#   1. ses_tanima modülü import edilince torch.cuda.zeros(1) çalışır → PyTorch cuDNN'i DLL
#      tablosuna ekler (kritik: ctranslate2 bundan SONRA yüklenirse doğru cuDNN'i bulur).
#   2. Ancak ağırlık yüklemesi (~25 saniye) arka plana alınır → menü anında görünür.
# XTTS da arka planda önyüklenir; konus() XTTS hazır değilse edge_tts ile devam eder.
_whisper_hazir = threading.Event()

if OFFLINE_DINLEME_KULLAN:
    from ses_tanima import metni_tanı as _metni_tanı_impl, _model_yukle as _whisper_yukle

    def _whisper_arka_plan():
        try:
            _whisper_yukle()
            print("[Whisper] Model arka planda yüklendi.")
        except Exception as _e:
            print(f"[Whisper] Arka plan yükleme hatası: {_e}")
        _whisper_hazir.set()

    threading.Thread(target=_whisper_arka_plan, daemon=True, name="whisper-yukle").start()
else:
    _whisper_hazir.set()  # offline kullanılmıyorsa bekleme gerekmiyor


# ── TTS MOTORU ÖNYÜKLEMESİ (açılışı bloklamadan) ─────────────────────────────
# SES_MOTORU'na göre doğru motoru arka planda yükle:
#   "piper" → Piper sesini CPU'ya yükle (hızlı). XTTS'e DOKUNMA (VRAM/zaman harcamaz).
#   "xtts"  → XTTS'i GPU'ya yükle (klonlanmış ses; LLM ile GPU çakışabilir — yavaş).
#   "edge"  → önyükleme gerekmez (her çağrıda internetten üretilir).

def _piper_arka_plan():
    try:
        from piper_tts import _model_yukle as _piper_yukle
        _piper_yukle()
        print("[Piper] Model arka planda yüklendi (CPU).")
    except Exception as _e:
        print(f"[Piper] Arka plan yükleme hatası: {_e}")


def _xtts_arka_plan():
    # XTTS önyüklemesi: konus() ilk çağrıldığında hazır olması için arka planda başlar.
    # Whisper modülü import edildikten SONRA başlatılır → cuDNN kayıt sırası korunur.
    try:
        from ses_klon import _model_yukle as _xtts_yukle  # noqa: F401
        _xtts_yukle()
        print("[XTTS] Model arka planda yüklendi.")
    except Exception as _e:
        print(f"[XTTS] Arka plan yükleme hatası: {_e}")


if SES_MOTORU == "piper":
    threading.Thread(target=_piper_arka_plan, daemon=True, name="piper-yukle").start()
elif SES_MOTORU == "xtts":
    # XTTS yalnızca açıkça seçilince yüklenir — "piper" iken GPU/zaman harcamaz.
    threading.Thread(target=_xtts_arka_plan, daemon=True, name="xtts-yukle").start()

# Pygame ses sistemini başlat (modül yüklendiğinde bir kez çalışır)
pygame.mixer.init()

# Kilit: ana döngü ve hatırlatıcı iş parçacığı aynı anda konus() çağırırsa
# ses üretimi ve pygame çalması çakışmasın diye sıraya sokuyoruz.
_konusma_kilidi = threading.Lock()

# ── openWakeWord sabitleri ────────────────────────────────────────────────────
# PyAudio akışı için parametreler — openWakeWord 16 kHz, 16-bit mono ister.
_OWW_ORNEKLEME_HIZI = 16000
_OWW_CERCEVE_BOYU   = 1280   # 80 ms @ 16 kHz  (1280 / 16000 = 0.08 s)
_OWW_FORMAT         = pyaudio.paInt16
_OWW_KANAL_SAYISI   = 1

# Singleton: openWakeWord modeli bir kez yüklenir, sonraki çağrılarda yeniden kullanılır.
_oww_model: "_OWWModel | None" = None

# Singleton: sr.Recognizer her komut_dinle() çağrısında yeniden oluşturulmasın.
# adjust_for_ambient_noise her çağrıda eşiği zaten güncelliyor; paylaşım güvenli.
_taniyici: "sr.Recognizer | None" = None

# Sohbet modunda "konuşmayı bitiriyorum" anlamına gelen Türkçe kelimeler
_SOHBET_BITIS_KELIMELERI = {"hayır", "yok", "tamam", "teşekkürler", "teşekkür", "görüşürüz"}


def _oww_model_yukle():
    # hey_jarvis modelini yükler; vad_threshold Silero VAD filtresini devreye sokar
    # (yalnızca insan sesi içeren çerçevelerde uyandırma tahmini yapar → yanlış
    # pozitif sayısını azaltır).
    global _oww_model
    if _oww_model is not None:
        return
    _oww_model = _OWWModel(wakeword_models=["hey_jarvis"], vad_threshold=UYANDIRMA_ESIGI)


async def _sesi_uret(metin):
    # edge_tts ile metni sese çevirip geçici dosyaya kaydediyoruz
    ses_motoru = edge_tts.Communicate(metin, voice=SES_TIPI)
    await ses_motoru.save(GECICI_SES_DOSYASI)


def konus(metin):
    # Kilit: aynı anda sadece bir ses üretilip çalınabilir.
    # Hatırlatıcı thread ana döngüyle çakışmaz; bekler, sonra seslenir.
    #
    # TTS motoru SES_MOTORU ile seçilir (tek anahtarla geçiş):
    #   "piper" → Piper (CPU, hızlı, VARSAYILAN)
    #   "xtts"  → klonlanmış XTTS (GPU); hazır değilse edge_tts'e düşer
    #   "edge"  → Microsoft Edge TTS (internet)
    # Her motor bir WAV/MP3 yolu üretir; oynatma burada MERKEZİ (pygame) yapılır.
    with _konusma_kilidi:
        print(f"{ASISTAN_ISMI}: {metin}")

        ses_dosyasi = None

        if SES_MOTORU == "piper":
            # Piper CPU'da hızlı sentezler; hata olursa edge_tts'e düş.
            try:
                from piper_tts import piper_uret
                ses_dosyasi = piper_uret(metin)
            except Exception as e:
                print(f"[Piper] Üretim hatası, edge_tts'e düşülüyor: {e}")
                asyncio.run(_sesi_uret(metin))
                ses_dosyasi = GECICI_SES_DOSYASI

        elif SES_MOTORU == "xtts":
            # XTTS arka planda yükleniyor olabilir. Hazırsa klonlanmış ses kullan;
            # yoksa edge_tts ile geç (ses değişir ama blok olmaz).
            try:
                from ses_klon import konus_klonlanmis, is_model_loaded
                if is_model_loaded():
                    ses_dosyasi = konus_klonlanmis(metin)
                else:
                    asyncio.run(_sesi_uret(metin))
                    ses_dosyasi = GECICI_SES_DOSYASI
            except Exception:
                asyncio.run(_sesi_uret(metin))
                ses_dosyasi = GECICI_SES_DOSYASI

        else:
            # "edge" veya bilinmeyen motor → Microsoft Edge TTS
            asyncio.run(_sesi_uret(metin))
            ses_dosyasi = GECICI_SES_DOSYASI

        pygame.mixer.music.load(ses_dosyasi)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)

        pygame.mixer.music.unload()


def _sesi_metne_cevir(ses):
    """
    AudioData nesnesini metne çevirir.
    OFFLINE_DINLEME_KULLAN=True → ses geçici WAV'a yazılır, Whisper'a gönderilir.
    OFFLINE_DINLEME_KULLAN=False → Google Speech Recognition API'ye gönderilir.
    Dönüş: küçük harfli metin ya da boş string.
    """
    if OFFLINE_DINLEME_KULLAN:
        # Whisper arka planda yükleniyor olabilir; hazır olana kadar bekle (max 3 dk)
        if not _whisper_hazir.is_set():
            print("[Whisper] Model yükleniyor, lütfen bekleyin...")
            _whisper_hazir.wait(timeout=180)
        with open(GECICI_DINLEME_DOSYASI, "wb") as f:
            f.write(ses.get_wav_data())
        return _metni_tanı_impl(GECICI_DINLEME_DOSYASI)
    else:
        taniyici = sr.Recognizer()
        return taniyici.recognize_google(ses, language="tr-TR").lower()


def arka_plan_dinle():
    # openWakeWord ile "Hey Jarvis" uyandırma kelimesini bekler.
    #
    # Eski Whisper/Google tabanlı yaklaşımın aksine bu fonksiyon artık ses
    # tanıma YAPMAZ — yalnızca uyandırma sinyali üretir.  Gürültülü ortamda
    # çok daha güvenilirdir çünkü openWakeWord özel bir sinir ağı modelidir.
    #
    # Dönüş: UYANDIRMA_KELIMELERI listesinde bulunan sabit bir metin ("friday").
    # Bu sayede main.py'daki uyandirma_kelimesi_var_mi() kontrolü değişmez.
    #
    # NOT: Bu mod aktifken arka planda "çıkış/kapat" söylemek programı
    # durdurmaz; çıkış komutunu Friday uyandıktan SONRA söylemek gerekir.
    _oww_model_yukle()

    pa     = pyaudio.PyAudio()
    stream = pa.open(
        format=_OWW_FORMAT,
        channels=_OWW_KANAL_SAYISI,
        rate=_OWW_ORNEKLEME_HIZI,
        input=True,
        frames_per_buffer=_OWW_CERCEVE_BOYU,
    )

    try:
        while True:
            # Her döngüde 80 ms'lik ses çerçevesi oku
            ham_veri    = stream.read(_OWW_CERCEVE_BOYU, exception_on_overflow=False)
            ses_dizisi  = np.frombuffer(ham_veri, dtype=np.int16)
            tahminler   = _oww_model.predict(ses_dizisi)
            skor        = tahminler.get("hey_jarvis", 0.0)

            if skor >= UYANDIRMA_ESIGI:
                # "friday" → main.py'daki uyandirma_kelimesi_var_mi() True döner
                return "friday"
    finally:
        # Uyandırma gerçekleşti veya hata oluştu — akışı her durumda kapat
        # (kapanmazsa komut_dinle()'nin açacağı mikrofon çakışabilir)
        stream.stop_stream()
        stream.close()
        pa.terminate()


def komut_dinle():
    # "Efendim?" dedikten sonra asıl komutu dinlemek için kullanılır.
    # 5 saniye içinde ses gelmezse boş string döner (timeout sinyali).
    global _taniyici
    if _taniyici is None:
        _taniyici = sr.Recognizer()
        # pause_threshold: konuşma bitti saymak için gereken sessizlik süresi (sn).
        # Varsayılan 0.8s cümle ortasındaki kısa duraklamada kaydı ERKEN kesebiliyordu;
        # 1.0s'ye çıkarıldı → kullanıcı cümlesini rahatça bitirir. Asıl konuşma
        # sonu/sessizlik temizliğini zaten Whisper'daki Silero VAD yapıyor.
        _taniyici.pause_threshold = 1.0
    taniyici = _taniyici

    with sr.Microphone() as mikrofon:
        print("\n🎤 Komutunuzu dinliyorum... (5 saniyeniz var)")
        taniyici.adjust_for_ambient_noise(mikrofon, duration=0.3)
        try:
            # timeout=5: 5 saniye İÇİNDE konuşma başlamazsa WaitTimeoutError.
            # phrase_time_limit=15: konuşma 15 sn'ye kadar sürebilir (üst sınır) —
            # kullanıcı uzun cümle kurabilsin; VAD bu ses içindeki konuşmayı çıkarır.
            ses = taniyici.listen(mikrofon, timeout=5, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return ""   # 5 saniye doldu, komut gelmedi

    try:
        metin = _sesi_metne_cevir(ses)
        if metin:
            print(f"👤 Sen: {metin}")
        else:
            print("(Anlayamadım)")
        return metin
    except Exception:
        print("(Ses tanıma hatası)")
        return ""


def sohbet_komut_bekle(sure_saniye: int = 15) -> str:
    # Sohbet modu dinleyicisi: uyandırma kelimesine gerek kalmadan komut bekler.
    #
    # sure_saniye boyunca (varsayılan 15) komut_dinle() döngüsü çalışır.
    # komut_dinle() her çağrıda en fazla 5 saniye bekler; dolayısıyla
    # ceil(15/5) = 3 deneme yapılır.
    #
    # Dönüş:
    #   geçerli komut metni → komut_isle() tarafından işlensin
    #   ""                  → süre doldu veya kullanıcı konuşmayı bitirdi
    deneme_sayisi = -(-sure_saniye // 5)  # tavan bölme (ceil)

    for deneme in range(deneme_sayisi):
        kalan_sure = sure_saniye - deneme * 5
        print(f"💬 Sohbet modu — {kalan_sure} saniye kaldı...")
        komut = komut_dinle()

        if not komut:
            continue  # bu denemede ses gelmedi, kalan süreyi kullan

        # Kullanıcı konuşmayı bitirmek istiyorsa uyku moduna dön
        if any(bitis in komut for bitis in _SOHBET_BITIS_KELIMELERI):
            return ""

        return komut  # geçerli komut bulundu

    return ""  # toplam sure_saniye boyunca hiç komut gelmedi


def yaz():
    # Yazılı modda mikrofon yerine klavyeden komut almak için kullanılır
    metin = input("👤 Sen (yaz): ")
    return metin
