# Bu dosya Friday'in yerel LLM beyin modülüdür.
# Ollama Python istemcisi (pip install -U ollama) üzerinden çalışır.
# think=False top-level parametre olarak gönderilir — Qwen3 düşünme modunu kapatır.
#
# LLM_KULLAN=False yapılınca bu dosya hiç çağrılmaz; mevcut kural sistemi bozulmaz.
# Mimari: kalıp eşleştirme → fuzzy → bu LLM katmanı (yedek)
#
# İleride hafıza verisi (hafiza.json) bu modül üzerinden LLM'e bağlam olarak verilir;
# yapı şimdiden buna uygun tutulmuştur.

import json
import time

from ollama import chat as _ollama_chat

from config import (
    LLM_MODEL, LLM_DUSUNME_KAPALI, LLM_HEMEN_BOSALT, LLM_CPU_MODU,
    LLM_BAGLAM, LLM_KEEP_ALIVE,
)


# Sentinel dönüş: beyin zaten kullanıcıya konuştu, ek mesaj gerekmez.
# komutlar.py bu değeri görünce sessizce return False yapar.
_HATA_BAGLANTI = {"tur": "baglanti_hatasi", "komut_adi": "", "parametre": "", "cevap": ""}

# ── KOMUT LİSTESİ (sistem promptu için) ──────────────────────────────────────
# Yeni komut eklendiğinde hem bu listeye hem komutlar.py _llm_dispatch_olustur()'a ekle.
# Sistem/donanım komutları artık buradan LLM'e geliyor (pre-brain kelime bloğu kaldırıldı).
_KOMUT_LISTESI = """\
muzik_cal          : Müzik/şarkı çal (parametre: şarkı veya sanatçı adı)
muzik_duraklat     : Çalan müziği duraklat
muzik_devam        : Duraklatılmış müziği devam ettir
sonraki_sarki      : Sonraki şarkıya geç
onceki_sarki       : Önceki şarkıya dön
playlist_cal       : Belirli bir playlist çal (parametre: playlist adı)
hava_durumu        : Hava durumu bilgisi al (parametre: şehir adı)
takvim             : Takvim etkinliklerini göster (parametre: tarih ifadesi, ör. "yarın", "30 ağustos")
etkinlik_ekle      : Takvime etkinlik EKLE (parametre: tarih+saat+başlık, ör. "yarın 15te doktor")
ozel_gun           : Belirli bir günün özel gün olup olmadığını söyle (parametre: tarih, ör. "14 mart")
dosya_ara          : Bilgisayarda dosya ara ve aç (parametre: dosya adı)
not_al             : Not kaydet (parametre: not içeriği)
notlari_oku        : Kayıtlı notları oku
not_sil            : Not sil (parametre: son/ilk/numara veya boş=hepsi)
hatirlatici_kur    : Hatırlatıcı kur (parametre: saat ve hatırlatma mesajı)
cevir              : Metin çevir (parametre: metin ve hedef dil)
mail_oku           : Mailleri oku
mail_gonder        : Mail gönder
sabah_raporu       : Sabah raporu / günlük brifing
beni_tani          : Kullanıcı hakkında kayıtlı bilgileri özetle
tarayici_ac        : Web tarayıcısını aç
bilgisayar_kapat   : Bilgisayarı tamamen kapat
sistem_sesi        : Ses SEVİYESİNİ ayarla (parametre: 0-100 sayı, artır/kıs)
ses_sustur         : Sesi SUSTUR — mute yap (müzikten bağımsız sistem sesi)
ses_ac             : MUTE'U KALDIR — sesi geri aç
parlaklik          : EKRAN parlaklığı — klavye ışığından FARKLI (parametre: 0-100 veya artır/azalt)
klavye_isigi       : KLAVYE arka aydınlatması — ekran parlaklığından FARKLI (parametre: aç/kapat/düşük/orta/yüksek)
ekran_kilitle      : Ekranı kilitle / oturumu kilitle
ekran_kapat        : Monitörü kapat — bilgisayar KAPATILMAZ, sadece ekran söner
gece_modu          : Gece ışığı / mavi ışık filtresi ayarlarını aç
ekran_modu         : Ekran tazeleme hızını değiştir (parametre: 60/120/144 Hz)
wifi_ac            : WiFi'yi AÇ — Bluetooth'tan tamamen FARKLI
wifi_kapat         : WiFi'yi KAPAT — Bluetooth'tan tamamen FARKLI
bluetooth_ac       : Bluetooth'u AÇ — WiFi'den tamamen FARKLI (bt ve blutut da bluetooth demektir)
bluetooth_kapat    : Bluetooth'u KAPAT — WiFi'den tamamen FARKLI (bt ve blutut da bluetooth demektir)
ucak_modu          : Uçak modu ayarlarını aç
performans_modu    : Yüksek performans güç planına geç
denge_modu         : Dengeli güç planına geç
tasarruf_modu      : Güç tasarrufu planına geç (pil ömrünü uzatır)
uyku_modu          : Bilgisayarı uyku/askı moduna al (MÜZIK/ŞARKI DEĞİL — "uyut" = uyku_modu)
yeniden_baslat     : Bilgisayarı yeniden başlat
oturum_kapat       : Windows OTURUMUNU kapat (bilgisayar kapanmaz, program çıkışından FARKLI)
fan_modu           : ASUS fan/termal profili (parametre: sessiz/dengeli/turbo)
gpu_modu           : GPU modunu değiştir — yeniden başlatma gerekir (parametre: eco/standart/ultimate)
touchpad_ac        : Dokunmatik yüzeyi etkinleştir
touchpad_kapat     : Dokunmatik yüzeyi devre dışı bırak
windows_tusu_ac    : Windows tuşunu etkinleştir
windows_tusu_kapat : Windows tuşunu devre dışı bırak
pil_durumu         : Pil/batarya yüzdesi ve şarj durumu
sistem_durumu      : CPU/RAM/disk kullanım durumu
cpu_sicakligi      : İşlemci sıcaklığı
uygulama_kapat     : Uygulamayı kapat (parametre: chrome/firefox/spotify/discord/word vb.)"""

# ── KRİTİK AYRIM KURALLARI + FEW-SHOT ÖRNEKLER ───────────────────────────────
# Beynin en çok karıştırdığı komutları (bt/wifi, parlaklık/klavye) için
# kesin kurallar ve minimum örnekler. Çok fazla örnek promptu şişirir.
_AYRIM_VE_ORNEKLER = """
KRİTİK AYRIM — ASLA KARIŞTIRMA:
• "bt"/"blutut"/"bluetooth" = BLUETOOTH (wifi ile ilgisi YOK) → bluetooth_ac/bluetooth_kapat
• "wifi"/"kablosuz"/"internet" = WİFİ (bluetooth ile ilgisi YOK) → wifi_ac/wifi_kapat
• "parlaklık"/"ekranı karart/aydınlat" = EKRAN → parlaklik (klavye ile KARIŞTIRMA)
• "klavye ışığı"/"klavye aydınlatma" = KLAVYE → klavye_isigi (ekrandan FARKLI)
• "sustur"/"sesi kapat" = ses_sustur; mute kaldır = ses_ac; seviye = sistem_sesi
• "ekranı kapat" = ekran_kapat (monitörü söndür, PC kapanmaz)
• "bilgisayarı uyut"/"uyku moduna al" = uyku_modu (MÜZIK/ŞARKI DEĞİL)
• "oturumu kapat"/"oturumu sonlandır" = oturum_kapat (program çıkışından FARKLI)

ÖRNEKLER:
"bt kapat"             → {"tur":"komut","komut_adi":"bluetooth_kapat","parametre":"","cevap":""}
"kablosuz ağı kapat"   → {"tur":"komut","komut_adi":"wifi_kapat","parametre":"","cevap":""}
"blutut'u aç"          → {"tur":"komut","komut_adi":"bluetooth_ac","parametre":"","cevap":""}
"klavye ışığını kapat" → {"tur":"komut","komut_adi":"klavye_isigi","parametre":"kapat","cevap":""}
"parlaklığı azalt"     → {"tur":"komut","komut_adi":"parlaklik","parametre":"azalt","cevap":""}
"sesi 40 yap"          → {"tur":"komut","komut_adi":"sistem_sesi","parametre":"40","cevap":""}
"sustur"               → {"tur":"komut","komut_adi":"ses_sustur","parametre":"","cevap":""}
"fanı sessiz yap"      → {"tur":"komut","komut_adi":"fan_modu","parametre":"sessiz","cevap":""}
"bilgisayarı uyut"     → {"tur":"komut","komut_adi":"uyku_modu","parametre":"","cevap":""}
"oturumu kapat"        → {"tur":"komut","komut_adi":"oturum_kapat","parametre":"","cevap":""}
"nasılsın"             → {"tur":"sohbet","komut_adi":"","parametre":"","cevap":"İyiyim, teşekkürler!"}"""


def _sistem_promptu_olustur(hafiza_baglami: str) -> str:
    """Hafıza bağlamını içeren kişiselleştirilmiş sistem promptu üretir.

    hafiza_baglami: hafiza.kullanici_ozeti() çıktısı — kullanıcının adı, şehri, tercihleri.
    Bu bilgi LLM'e kişiselleştirilmiş yanıt verebilmesi için sisteme eklenir.
    """
    baglam = ""
    if (hafiza_baglami
            and hafiza_baglami.strip()
            and "bilmiyorum" not in hafiza_baglami):
        baglam = f"\n\nKullanıcı hakkında kayıtlı bilgiler:\n{hafiza_baglami}"

    return (
        "Sen Friday adında Türkçe kişisel asistansın. "
        "Kullanıcının mesajını analiz et ve SADECE geçerli bir JSON döndür. "
        "Başka hiçbir şey yazma — açıklama, markdown ya da düşünce zinciri ekleme.\n\n"
        "JSON formatı tam olarak şu şekilde olmalı:\n"
        '{"tur": "komut" veya "sohbet", "komut_adi": "...", "parametre": "...", "cevap": "..."}\n\n'
        "Kurallar:\n"
        "• Kullanıcı bir işlem istiyorsa (müzik, hava, dosya, sistem, mail, takvim vb.) "
        "→ tur=\"komut\", aşağıdan uygun komut_adi seç, gerekli bilgiyi parametre alanına yaz, "
        "cevap alanını boş bırakabilirsin.\n"
        "• Sadece sohbet/selam/teşekkür/genel soru/şaka → tur=\"sohbet\", "
        "cevap alanına kısa ve samimi Türkçe yanıt yaz, komut_adi ve parametre boş bırak.\n\n"
        f"Kullanılabilir komut_adi değerleri:\n{_KOMUT_LISTESI}"
        f"{_AYRIM_VE_ORNEKLER}"
        f"{baglam}"
    )


def beyin_hazirla() -> None:
    """Program açılışında Ollama'ya kısa bir istek göndererek modeli RAM'e yükler.

    main.py'de daemon thread olarak çağrılır — açılışı yavaşlatmaz.
    Başarısız olursa (Ollama kapalı vb.) sadece konsola yazar ve sessizce geçer.
    Isınma yapılmazsa ilk gerçek LLM komutu biraz daha uzun sürer.
    """
    try:
        # YENİ MİMARİ: GPU tamamen LLM'in (TTS+Whisper CPU'da). Varsayılan ayarlar:
        #   LLM_CPU_MODU=False     → num_gpu varsayılan (GPU)
        #   LLM_HEMEN_BOSALT=False → keep_alive=LLM_KEEP_ALIVE ("30m") → GPU'da kalır
        # num_ctx=LLM_BAGLAM (4096) VRAM'i şişirmez.
        _ka      = 0 if LLM_HEMEN_BOSALT else LLM_KEEP_ALIVE
        _options = {"num_ctx": LLM_BAGLAM}
        if LLM_CPU_MODU:
            _options["num_gpu"] = 0   # yalnızca CPU modunda; varsayılan GPU
        _konum   = "CPU" if LLM_CPU_MODU else "GPU"

        _ollama_chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": "hazır"}],
            think=False,
            keep_alive=_ka,
            options=_options,
        )
        print(f"[BEYİN] '{LLM_MODEL}' {_konum}'de yüklendi, hazır.")
    except Exception as e:
        # Ollama kapalı veya model henüz indirilmedi — ilk gerçek komutta yüklenir
        print(f"[BEYİN] Isınma başarısız (Ollama kapalı olabilir): {e}")


def beyin_metin_uret(sistem_promptu: str, kullanici_metni: str) -> str | None:
    """Genel amaçlı LLM çağrısı — düz metin döndürür (JSON ayrıştırma YOK).

    Özetleme gibi serbest metin görevleri için kullanılır (pano_yonetimi.pano_ozetle).
    Ollama config'i (think=False, keep_alive, num_ctx) burada merkezi uygulanır.

    Dönüş:
        str  → LLM'in ürettiği metin (örn. özet)
        None → Ollama kapalı / hata (çağıran taraf kullanıcıyı bilgilendirir)
    """
    try:
        _ka      = 0 if LLM_HEMEN_BOSALT else LLM_KEEP_ALIVE
        _options = {"temperature": 0.3, "num_ctx": LLM_BAGLAM}
        if LLM_CPU_MODU:
            _options["num_gpu"] = 0

        yanit = _ollama_chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": sistem_promptu},
                {"role": "user",   "content": kullanici_metni},
            ],
            think=not LLM_DUSUNME_KAPALI,
            keep_alive=_ka,
            options=_options,
        )
        metin = yanit["message"]["content"].strip()

        # think=False'a rağmen bazı modeller <think> bloğu ekleyebilir — temizle
        if "<think>" in metin:
            son = metin.rfind("</think>")
            if son != -1:
                metin = metin[son + len("</think>"):].strip()
        return metin or None

    except Exception as e:
        print(f"[BEYİN] Metin üretme hatası: {type(e).__name__}: {e}")
        return None


def beyin_dusun(kullanici_metni: str, hafiza_baglami: str = "") -> dict | None:
    """Kullanıcı mesajını LLM ile analiz eder; komut mu sohbet mi olduğuna karar verir.

    Parametreler:
        kullanici_metni : Kullanıcının söyledikleri (küçük harf, komutlar.py'den gelir)
        hafiza_baglami  : kullanici_ozeti() çıktısı — kişiselleştirme için

    Dönüş değerleri:
        {"tur": "komut", "komut_adi": "...", "parametre": "...", "cevap": ""}
            → LLM bir eylem tanıdı; komutlar.py dispatch tablosundan çalıştırır
        {"tur": "sohbet", "komut_adi": "", "parametre": "", "cevap": "..."}
            → Doğal dil yanıtı; komutlar.py konus() ile seslendirir
        {"tur": "baglanti_hatasi", ...}
            → Ollama kapalı; beyin zaten konuştu, komutlar.py sessizce döner
        None
            → Sessiz hata; komutlar.py "tanınmayan komut" mesajı verir

    Uygulama asla çökmez — tüm hatalar yakalanır.
    """
    # ses modülü gecikmeli import edilir — döngüsel bağımlılık riski
    from ses import konus as _konus

    ham_metin = ""   # JSONDecodeError bloğunda her zaman tanımlı olsun
    _baslangic = time.time()

    try:
        sistem = _sistem_promptu_olustur(hafiza_baglami)

        # GPU stratejisi: LLM_CPU_MODU veya LLM_HEMEN_BOSALT ayarına göre
        # keep_alive ve num_gpu her çağrıda hesaplanır. num_ctx=4096 (LLM_BAGLAM).
        _ka      = 0 if LLM_HEMEN_BOSALT else LLM_KEEP_ALIVE
        _options = {"temperature": 0.3, "num_ctx": LLM_BAGLAM}
        if LLM_CPU_MODU:
            _options["num_gpu"] = 0   # CPU'da çalıştır — GPU'ya hiç dokunmaz

        # think: TOP-LEVEL parametre — options içine koyma, çalışmaz.
        yanit = _ollama_chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": sistem},
                {"role": "user",   "content": kullanici_metni},
            ],
            think=not LLM_DUSUNME_KAPALI,
            keep_alive=_ka,
            options=_options,
        )

        _sure = time.time() - _baslangic
        print(f"[BEYİN] '{kullanici_metni[:50]}' → {_sure:.1f}s")

        ham_metin = yanit["message"]["content"].strip()

        # <think>...</think> bloğunu temizle — güvenlik katmanı.
        # think=False gönderilmiş olsa bile model bazen bu blokları ekleyebilir.
        if "<think>" in ham_metin:
            son_idx = ham_metin.rfind("</think>")
            if son_idx != -1:
                ham_metin = ham_metin[son_idx + len("</think>"):].strip()

        # Markdown kod bloğu sargısını at (```json ... ```)
        # Bazı modeller JSON'u kod bloğu içinde döndürür
        if "```" in ham_metin:
            satirlar = [
                s for s in ham_metin.splitlines()
                if not s.strip().startswith("```")
            ]
            ham_metin = "\n".join(satirlar).strip()

        sonuc: dict = json.loads(ham_metin)

        # Zorunlu alan garantisi — eksik alan varsa varsayılanla tamamla
        sonuc.setdefault("tur",       "sohbet")
        sonuc.setdefault("komut_adi", "")
        sonuc.setdefault("parametre", "")
        sonuc.setdefault("cevap",     "")

        return sonuc

    except json.JSONDecodeError:
        # Model geçerli JSON döndürmedi — ham metni sohbet cevabı olarak kullan
        _sure = time.time() - _baslangic
        print(f"[BEYİN] JSON ayrıştırma hatası ({_sure:.1f}s), ham metin sohbet olarak kullanılıyor.")
        if ham_metin:
            return {
                "tur":       "sohbet",
                "komut_adi": "",
                "parametre": "",
                "cevap":     ham_metin[:300],   # Çok uzun yanıtları kırp
            }
        return None   # Ham metin de boşsa → "tanınmayan komut"

    except Exception as e:
        _sure = time.time() - _baslangic
        _tip  = type(e).__name__.lower()
        _msj  = str(e).lower()

        # Bağlantı hatası tespiti: ConnectError, ConnectionRefused, ECONNREFUSED vb.
        if any(k in _tip + _msj for k in ("connect", "refused", "errno", "socket", "unreachable")):
            print(f"[BEYİN] Bağlantı hatası ({_sure:.1f}s): {e}")
            _konus("Beynim şu an kapalı, sadece temel komutları çalıştırabilirim.")
            return _HATA_BAGLANTI   # Sentinel → komutlar.py sessizce döner

        # Zaman aşımı
        if "timeout" in _tip + _msj:
            print(f"[BEYİN] Zaman aşımı ({_sure:.1f}s).")
            _konus("Düşünmem biraz uzun sürdü, tekrar deneyebilirsin.")
            return _HATA_BAGLANTI   # Sentinel → komutlar.py sessizce döner

        # Diğer beklenmedik hatalar — sessizce None döndür
        print(f"[BEYİN] Beklenmedik hata ({_sure:.1f}s): {type(e).__name__}: {e}")
        return None
