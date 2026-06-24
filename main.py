# Bu dosya Friday'in ana program akışını içerir.
# Mod seçimi, uyandırma kelimesi kontrolü ve ana döngü burada yönetilir.

import time as _t
_t0 = _t.time()
print("Friday başlatılıyor...")

import os

from config import ASISTAN_ISMI, GECICI_SES_DOSYASI, UYANDIRMA_KELIMELERI, LLM_KULLAN, KLONLANMIS_SES_KULLAN
_t1 = _t.time(); print(f"  config: {_t1-_t0:.1f}s")

from ses import konus, arka_plan_dinle, komut_dinle, sohbet_komut_bekle, yaz
_t2 = _t.time(); print(f"  ses (Whisper modülü import + cuDNN init + arka plan başladı): {_t2-_t1:.1f}s")

from komutlar import komut_isle
_t3 = _t.time(); print(f"  komutlar: {_t3-_t2:.1f}s")

from hatirlatici import hatirlaticilari_kontrol_et
from hafiza import konusma_ekle, aliskanlik_oner
print(f"  toplam import: {_t.time()-_t0:.1f}s — menü hazır")


def uyandirma_kelimesi_var_mi(metin):
    # Duyulan metinde UYANDIRMA_KELIMELERI listesindeki ifadelerden biri var mı?
    metin = metin.lower().strip()
    for kelime in UYANDIRMA_KELIMELERI:
        if kelime in metin:
            return True
    return False


def program_cikisi_mi(metin):
    # Yalnızca sesli modun arka plan dinleme fazında (duyulan) kullanılır.
    # Gerçek komutlar için çıkış kontrolü komutlar.py/_cikis_mi() tarafından yapılır.
    #
    # GÜVENLİK: "kapat" TEK BAŞINA programı kapatmaz. Yalnızca net çıkış kelimeleri
    # ("çıkış"/"kapan"/"çık") veya programa açık atıf ("kendini/programı/friday kapat")
    # çıkış sayılır. Böylece "vifi kapat", "b.t. kapat" gibi yanlış duymalar programı
    # KAPATAMAZ (komutlar.py/_cikis_mi ile aynı mantık).
    _PROGRAM_KAPAT = ("kendini", "programı", "programi", "uygulamayı", "uygulamayi",
                      "friday", "jarvis", "seni", "asistanı", "asistani")
    if "çıkış" in metin or "çıkis" in metin or "kapan" in metin or metin.strip() == "çık":
        return True
    if "kapat" in metin and any(p in metin for p in _PROGRAM_KAPAT):
        return True
    return False


def main():
    print("=" * 50)
    print(f"  {ASISTAN_ISMI} başlatılıyor")
    print("=" * 50)
    print("Hangi modda çalışmak istersin?")
    print("  1 -> Sesli mod (mikrofonla konuş, 'Hey Friday' ile uyandır)")
    print("  2 -> Yazılı mod (klavyeyle yaz, direkt cevap verir)")

    secim = input("Seçimin (1 veya 2): ").strip()
    mod = "yazili" if secim == "2" else "sesli"

    # Hatırlatıcı arka plan thread'ini başlat — daemon olduğu için program kapanınca durur
    hatirlaticilari_kontrol_et()

    # LLM beynini arka planda ısıt — modeli RAM'e yükler, açılışı yavaşlatmaz.
    # İlk gerçek LLM komutu geldiğinde model zaten hazır olur.
    if LLM_KULLAN:
        from threading import Thread
        from beyin import beyin_hazirla
        Thread(target=beyin_hazirla, daemon=True).start()

    # ── JARVIS TARZI AÇILIŞ: saygılı karşılama + günlük brifing ───────────────
    # Eski "Genelde bu saatlerde X yapıyorsun, yine yapalım mı?" önerisi KALDIRILDI
    # (kullanıcı saçma buldu). Yerine Iron Man'deki JARVIS gibi "Hoş geldiniz efendim"
    # deyip günlük raporu (hava, takvim, hatırlatıcı, notlar) sunar.
    if mod == "sesli":
        konus("Hoş geldiniz efendim. Emrinizdeyim. Günlük brifinginizi sunuyorum.")
    else:
        konus("Hoş geldiniz efendim. Günlük brifinginiz hazır.")

    # Günlük brifing — sabah_raporu_ver selamlama + hava + takvim + hatırlatıcı + notlar
    # sunar (her bölüm kendi try/except'inde; veri yoksa o bölüm sessizce atlanır).
    try:
        from sabah_raporu import sabah_raporu_ver
        sabah_raporu_ver(mod)
    except Exception:
        pass  # Rapor üretilemezse açılış yine de sorunsuz sürer

    # =====================================================
    # SONSUZ DÖNGÜ: Friday sürekli bekler ve komut alır.
    # "çıkış" veya "kapat" her iki modda da döngüyü sonlandırır.
    # =====================================================
    while True:

        # ==================== YAZILI MOD ====================
        # Uyandırma kelimesi YOK. Her yazılan şeye direkt cevap verilir.
        if mod == "yazili":
            komut = yaz().lower()

            if komut == "":
                continue

            # komut_isle() tüm komutları dener; hiçbiri eşleşmezse çıkış kontrolü de
            # orada yapılır (_cikis_mi) — True dönerse döngüyü kır.
            _sonuc = komut_isle(komut, mod)
            konusma_ekle(komut)
            if _sonuc:
                break

        # ==================== SESLİ MOD ====================
        # Uyandırma kelimesi SİSTEMİ AÇIK.
        # "Hey Friday" duyulana kadar sessizce arka planda dinlenir.
        else:
            # AŞAMA 1: openWakeWord ile "Hey Jarvis" uyandırma kelimesini bekle
            print("💤 Bekliyorum... ('Hey Jarvis' diyerek çağırın)")
            duyulan = arka_plan_dinle()

            if duyulan == "":
                continue

            # Çıkış komutu uyandırma kelimesi olmadan da her zaman çalışsın
            if program_cikisi_mi(duyulan):
                konus("Görüşmek üzere!")
                break

            # Uyandırma kelimesi yoksa sessizce döngüye devam et
            if not uyandirma_kelimesi_var_mi(duyulan):
                continue

            # AŞAMA 2: Uyandırma kelimesi duyuldu — "Efendim?" de ve komutu bekle
            print(f"✅ Uyandırma kelimesi algılandı: '{duyulan}'")
            konus("Efendim?")

            # AŞAMA 3: 5 saniye içinde komut bekle
            komut = komut_dinle()

            if komut == "":
                konus("Seni dinlemiyorum, tekrar çağırırsan buradayım.")
                continue

            # AŞAMA 4: Komutu işle; True dönerse çık.
            # Çıkış kontrolü de komut_isle() sonunda yapılır — erken kontrol yok.
            _sonuc = komut_isle(komut, mod)
            konusma_ekle(komut)
            if _sonuc:
                break

            # ── AŞAMA 5: SOHBET MODU ────────────────────────────────────────
            # Komut işlendikten sonra 15 saniye boyunca tekrar "Hey Jarvis"
            # demeden ek komut bekle.  Her başarılı komutta 15 saniye sıfırlanır.
            # "hayır/tamam/teşekkürler" veya sessizlik → uyku moduna dön.
            sohbet_aktif = True
            while sohbet_aktif:
                ek_komut = sohbet_komut_bekle(sure_saniye=15)

                if not ek_komut:
                    # Süre doldu veya kullanıcı konuşmayı bitirdi
                    sohbet_aktif = False
                    break

                # komut_isle() çıkış komutunda True döndürür ("Görüşmek üzere!"
                # de içinde söylenir). komut="çıkış" ile dış döngüyü kırarız.
                _ek_sonuc = komut_isle(ek_komut, mod)
                konusma_ekle(ek_komut)
                if _ek_sonuc:
                    sohbet_aktif = False
                    komut = "çıkış"
                    break
                # Komut işlendi → sohbet_komut_bekle() tekrar çağrılır (15 sn yenilendi)

            # Sohbet modunda çıkış komutu geldiyse dış döngüyü de kır
            if "çıkış" in komut:
                break

    # Program biterken geçici ses dosyasını temizle
    if os.path.exists(GECICI_SES_DOSYASI):
        os.remove(GECICI_SES_DOSYASI)


# Dosyayı çalıştırınca main() otomatik başlasın
if __name__ == "__main__":
    main()
