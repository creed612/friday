# Bu dosya Friday'in "sabah raporu / günaydın brifing" özelliğini içerir.
# Mevcut modülleri (hava durumu, takvim, hatırlatıcı, notlar) tek bir akıcı
# brifing olarak birleştirir; yeni bir API veya servis kullanmaz.
#
# Her bölüm kendi try/except bloğuna sahiptir: bir modül hata verse
# (internet yok, takvim erişimi yok vb.) o bölüm atlanır, rapor devam eder.

import os
import re
import random
from datetime import datetime

from ses import konus


# ── SABİT VERİLER ────────────────────────────────────────────────────────────

_AYLAR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
_GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

# Raporun sonunda rastgele seçilecek kapanış cümleleri
_KAPANIS_CUMLELER = [
    "İyi bir gün geçirmeni dilerim. Bir şeye ihtiyacın olursa buradayım.",
    "Bugünün güzel ve verimli geçmesi dileğiyle, her an buradayım.",
    "Harika bir gün olsun! Yardımcı olabileceğim bir şey varsa yalnızca seslen.",
    "Kolay gelsin. İstediğin zaman yardım için buradayım.",
    "Bugün de bol şans. Ne zaman çağırırsan buradayım.",
]


# ── BÖLÜM 1: SELAMLAMA ───────────────────────────────────────────────────────

def _selamlama_olustur() -> str:
    # Günün saatine göre selam ve tarihi içeren açılış cümlesini döndürür.
    simdi  = datetime.now()
    saat   = simdi.hour
    gun    = simdi.day
    ay     = _AYLAR[simdi.month - 1]
    hafta  = _GUNLER[simdi.weekday()]

    if 5 <= saat < 12:
        selam = "Günaydın"
    elif 12 <= saat < 18:
        selam = "İyi günler"
    elif 18 <= saat < 22:
        selam = "İyi akşamlar"
    else:
        selam = "İyi geceler"

    return f"{selam}! Bugün {gun} {ay} {hafta}."


# ── BÖLÜM 2: HAVA DURUMU ─────────────────────────────────────────────────────

def _hava_bolumu() -> str | None:
    # Kaydedilmiş şehrin hava durumunu metin olarak döndürür.
    # Kayıtlı şehir yoksa veya herhangi bir hata olursa None döner (bölüm atlanır).
    # hava_durumu_soyle() kullanıcıya soru sorduğu için burada alt fonksiyonlar
    # doğrudan çağrılır; kayıtlı şehir yoksa sessizce atlanır.
    from hava_durumu import (
        _sehir_oku, _koordinat_bul, _koordinattan_hava_al,
        hava_kodu_yorumla, yuruyus_onerisi,
    )
    sehir = _sehir_oku()
    if not sehir:
        return None   # Kayıtlı şehir yok → hava bölümünü atla

    koordinatlar = _koordinat_bul(sehir)
    if not koordinatlar:
        return None

    enlem, boylam   = koordinatlar
    sicaklik, kod   = _koordinattan_hava_al(enlem, boylam)
    aciklama        = hava_kodu_yorumla(kod)
    oneri           = yuruyus_onerisi(sicaklik, kod)

    return (
        f"{sehir.title()}'de hava {round(sicaklik)} derece ve {aciklama}. {oneri}"
    )


# ── BÖLÜM 3: TAKVİM ──────────────────────────────────────────────────────────

def _takvim_bolumu() -> str | None:
    # Bugünün Google Takvim etkinliklerini metin olarak döndürür.
    # Etkinlik yoksa "takviminde etkinlik yok" döndürür.
    # Hata olursa None döner (bölüm atlanır).
    from takvim import gunluk_etkinlikleri_getir

    etkinlikler = gunluk_etkinlikleri_getir()

    if not etkinlikler:
        return "Bugün takviminde herhangi bir etkinlik yok."

    parcalar = []
    for e in etkinlikler:
        if e["saat"] == "tüm gün":
            parcalar.append(f"tüm gün {e['baslik']}")
        else:
            parcalar.append(f"saat {e['saat']}'de {e['baslik']}")

    # Virgülle birleştir, son öğeden önce "ve" — daha doğal Türkçe
    if len(parcalar) == 1:
        icerik = parcalar[0]
    else:
        icerik = ", ".join(parcalar[:-1]) + " ve " + parcalar[-1]

    return f"Bugün takviminde {len(etkinlikler)} etkinliğin var: {icerik}."


# ── BÖLÜM 4: HATIRLATICILAR ──────────────────────────────────────────────────

def _hatirlatici_bolumu() -> str | None:
    # Henüz zamanı gelmemiş aktif hatırlatıcıları metin olarak döndürür.
    # Aktif hatırlatıcı yoksa None döner (bölüm tamamen atlanır).
    from hatirlatici import _hatirlaticilar, _liste_kilidi

    simdi = datetime.now()
    with _liste_kilidi:
        # Zamanı henüz gelmemiş hatırlatıcıları saat sırasına göre al
        aktif = sorted(
            [h for h in _hatirlaticilar if h["zaman"] > simdi],
            key=lambda h: h["zaman"],
        )

    if not aktif:
        return None   # Aktif hatırlatıcı yok → bölümü atla

    parcalar = []
    for h in aktif:
        saat_str = h["zaman"].strftime("%H:%M")
        parcalar.append(f"saat {saat_str}'de {h['mesaj']}")

    adet = len(parcalar)
    if adet == 1:
        return f"Aktif bir hatırlatıcın var: {parcalar[0]}."
    else:
        icerik = ", ".join(parcalar[:-1]) + " ve " + parcalar[-1]
        return f"{adet} aktif hatırlatıcın var: {icerik}."


# ── BÖLÜM 5: NOTLAR ──────────────────────────────────────────────────────────

def _notlar_bolumu() -> str | None:
    # notlarim.txt'den son 3 notu okur ve metin olarak döndürür.
    # Not yoksa veya dosya yoksa None döner (bölüm atlanır).
    from notlar import _NOTLAR_DOSYASI

    if not os.path.exists(_NOTLAR_DOSYASI):
        return None

    with open(_NOTLAR_DOSYASI, "r", encoding="utf-8") as dosya:
        satirlar = [s.strip() for s in dosya if s.strip()]

    if not satirlar:
        return None

    # Not içeriğini zaman damgasından ([GG.AA.YYYY SS:DD]) ayır
    def icerik_al(satir: str) -> str:
        temiz = re.sub(r"^\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}\]\s*", "", satir)
        return temiz if temiz else satir

    son_notlar = satirlar[-3:]   # En fazla son 3 not
    parcalar   = [icerik_al(s) for s in son_notlar]

    toplam = len(satirlar)
    if toplam > 3:
        on_ek = f"Toplam {toplam} notun var; son üçü: "
    elif toplam == 1:
        on_ek = "Kayıtlı bir notun var: "
    else:
        on_ek = f"Kayıtlı {toplam} notun var: "

    return on_ek + "; ".join(parcalar) + "."


# ── ANA FONKSİYON ────────────────────────────────────────────────────────────

def sabah_raporu_ver(mod: str):
    # Tüm bölümleri sırayla çağırır ve her birini konus() ile seslendirir.
    # Her bölüm kendi try/except bloğu içindedir; bir bölüm hata verirse
    # diğerleri etkilenmeden rapor devam eder.

    # ── 1. Selamlama ─────────────────────────────────────────────────────────
    try:
        konus(_selamlama_olustur())
    except Exception:
        konus("Merhaba!")   # Fallback — bu neredeyse hiç başarısız olmaz

    # ── 1ب. Özel gün (varsa) ─────────────────────────────────────────────────
    # Bugün global/eğlenceli bir özel günse brifinge hoş bir dokunuş ekle.
    try:
        from ozel_gunler import ozel_gun_kontrol
        _ozel = ozel_gun_kontrol()
        if _ozel:
            konus(f"Bugün {_ozel}!")
    except Exception:
        pass   # ozel_gunler yoksa veya hata olursa sessizce geç

    # ── 2. Hava durumu ───────────────────────────────────────────────────────
    try:
        hava = _hava_bolumu()
        if hava:
            konus(hava)
        # Kayıtlı şehir yoksa sessizce atla
    except Exception:
        pass   # İnternet yok veya başka sorun → sessizce atla

    # ── 3. Takvim ────────────────────────────────────────────────────────────
    try:
        takvim = _takvim_bolumu()
        if takvim:
            konus(takvim)
    except Exception:
        pass   # Google Takvim bağlantısı yoksa atla

    # ── 4. Hatırlatıcılar ────────────────────────────────────────────────────
    try:
        hatirlatici = _hatirlatici_bolumu()
        if hatirlatici:
            konus(hatirlatici)
        # Aktif hatırlatıcı yoksa sessizce atla
    except Exception:
        pass

    # ── 5. Notlar ────────────────────────────────────────────────────────────
    try:
        notlar = _notlar_bolumu()
        if notlar:
            konus(notlar)
        # Not yoksa sessizce atla
    except Exception:
        pass

    # ── 6. Kapanış ───────────────────────────────────────────────────────────
    try:
        konus(random.choice(_KAPANIS_CUMLELER))
    except Exception:
        pass
