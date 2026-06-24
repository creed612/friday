# Bu dosya kullanıcıdan gelen komutları analiz edip doğru işleme yönlendirir.
# komut_isle() fonksiyonu burada tanımlıdır.

from rapidfuzz import fuzz as _fuzz

from config import LLM_KULLAN
from ses import konus, komut_dinle, yaz
from gmail_yonetimi import mailleri_oku, mail_gonder, mail_komut_isle
from kisiler import kisi_mail_bul
from drive_yonetimi import drive_dosya_ara
from bilgisayar_kontrol import (
    tarayici_ac,
    not_defteri_ac,
    hesap_makinesi_ac,
    bilgisayari_kapat,
)
from dosya_yonetimi import dosya_ara_ve_ac
from hava_durumu import hava_durumu_soyle, sehir_sifirla
from takvim import takvimi_soyle, etkinlik_ekle, belirli_tarih_etkinlikleri
from ozel_gunler import ozel_gun_soyle
from notlar import not_ekle, notlari_oku, notlar_komut_isle
from hatirlatici import hatirlatici_kur
from cevirmen import metni_cevir
from pano_yonetimi import pano_oku, pano_ozetle, pano_cevir
from spotify_kontrol import (
    sarki_calar, muzik_duraklat, muzik_devam_et, sonraki_sarki, onceki_sarki,
    simdi_calan, ses_ayarla, karistir_ac_kapa, tekrar_modu_degistir,
    sarki_begen, playliste_ekle, calma_yonet, playlist_cal,
)
from sabah_raporu import sabah_raporu_ver
from sistem_ayarlari import (
    sistem_sesi_ayarla, sistem_sesi_sustur, sistem_sesi_ac,
    parlaklik_ayarla,
    wifi_ac, wifi_kapat, ucak_modu,
    bluetooth_ac, bluetooth_kapat,
    performans_modu, denge_modu, tasarruf_modu,
    ekran_kilitle, ekrani_kapat, gece_modu,
    uyku_modu, yeniden_baslat, oturum_kapat,
    pil_durumu, sistem_durumu, cpu_sicakligi,
    uygulama_kapat,
    klavye_isigi_ayarla,
    klavye_renk_ayarla,
    klavye_efekt_ayarla,
    fan_modu_ayarla,
    gpu_modu_ayarla,
    touchpad_ac, touchpad_kapat,
    windows_tusu_ac, windows_tusu_kapat,
    ekran_modu_ayarla,
)
from hafiza import (
    bilgi_kaydet, bilgi_getir, kullanici_ozeti,
    asistan_adi_getir, asistan_adi_kaydet,
    komut_say, en_cok_kullanilan,
    aliskanlik_kaydet,
    konusma_ekle, son_konusmalar,
)


# ── WIFI KELİME AİLESİ ───────────────────────────────────────────────────────
# Whisper "wifi"yi sık sık Türkçe fonetikle yazıyor (vifi, vayfay…). Hepsini ekle.
# Tek noktadan: _sistem_donanim_yonlendir() ve _CIKIS_ISTISNALAR buradan okur.
_WIFI_KELIMELER = (
    "wifi", "wi-fi", "wi fi", "vifi", "wıfı", "vıfı", "wayfi", "vayfi",
    "vayfay", "wayfay", "wayfı", "vayfı", "wai fai", "vay fay", "kablosuz",
)


def _wifi_kelimesi_var_mi(metin: str) -> bool:
    # Metinde wifi/varyasyonlarından biri geçiyor mu?
    return any(k in metin for k in _WIFI_KELIMELER)


# ── BLUETOOTH KELİME AİLESİ ──────────────────────────────────────────────────
# "bt"/"b.t." kısaltması ve Whisper'ın üretebileceği varyasyonlar dahil.
# _CIKIS_ISTISNALAR, _sistem_donanim_yonlendir() ve dispatch için tek noktadan kontrol edilir.
_BT_KELIMELER = (
    "bluetooth", "blutut", "blue tooth", "blututh", "blu tut", "blutuş",
    "blue tut", "be te",
)


def _bluetooth_kelimesi_var_mi(metin: str) -> bool:
    # "bluetooth"/varyasyonları VEYA "bt"/"b.t." (tek kelime/noktalı) içeriyor mu?
    # Token bazlı "bt": "bt", "b.t.", "b.t" → noktasız "bt" → eşleşir.
    # "sabt"/"subtitle" gibi gömülü eşleşmeler ENGELLENİR (token tam "bt" olmalı).
    if any(k in metin for k in _BT_KELIMELER):
        return True
    for parca in metin.split():
        if parca.replace(".", "") == "bt":   # "bt", "b.t.", "b.t" → "bt"
            return True
    return False


# Spotify çalma tetikleyicilerinin ilk-kelime seti.
# komut_isle() içinde her çağrıda yeniden oluşturmamak için modül düzeyinde tutulur.
_SPOTI_CALI_ILKLERI = {"çal", "kal", "oynat", "oyna", "oant", "oynayt", "başlat"}


# Fuzzy eşleştirme eşiği.
# 80 → "durak tat" (Whisper hatası) ile "duraklat" tam eşikte eşleşir.
# Düşürme: sahte tetiklemeler artar. Yükseltme: gerçek hatalar atlanır.
_FUZZY_ESIK = 80

# ── ÇIKIŞ ALGILAMA ───────────────────────────────────────────────────────────
# Tüm komutlar kontrol edildikten sonra SONUNDA çalışan çıkış mantığı.
# Önceki sürümde main.py bu kontrolü komut işlemeden ÖNCE yapıyordu;
# bu da "wifi kapat" gibi komutların yanlışlıkla program çıkışı olarak
# yorumlanmasına yol açıyordu. Şimdi sadece hiçbir komut eşleşmezse devreye girer.

# Kesin çıkış anlamına gelen ifadeler. DİKKAT: yalın "kapat" KASITLI olarak YOK —
# "vifi kapat"/"b.t. kapat" gibi yanlış duyulan komutlar programı kapatmasın diye.
# Çıkmak için: "çıkış", "kapan", "çık" veya "kendini/programı kapat".
_CIKIS_IFADELERI = frozenset({
    "çıkış", "çıkis", "kapan", "çık",
    "görüşürüz", "görüşmek üzere", "hoşçakal", "bay bay",
    "kendini kapat", "friday'ı kapat", "jarvis'i kapat",
    "uygulamayı kapat", "programı kapat",
})

# "çıkış"/"kapan" geçen ama aslında komut olan ifadeleri elemek için nesne listesi.
_CIKIS_ISTISNALAR = frozenset({
    "touchpad",
    "ekran", "ekranı", "monitör", "monitörü",
    "parlaklık",
    "müzik", "şarkı", "spotify", "ses",
    "chrome", "firefox", "edge", "discord", "notepad",
    "word", "excel", "powerpoint", "outlook", "teams", "zoom",
    "vlc", "steam", "armoury", "explorer", "paint", "obs", "vscode",
    "fan", "gpu", "klavye",
    "pencere", "sekme", "uygulama",
    "tarayıcı", "not defteri",
    "bilgisayarı", "bilgisayari",
})

# "kapat" YALNIZCA bu kelimelerden biriyle birlikteyse programı kapatır.
_PROGRAM_KAPAT_KELIMELERI = (
    "kendini", "kendi̇ni", "programı", "programi", "uygulamayı", "uygulamayi",
    "friday", "jarvis", "seni", "asistanı", "asistani",
)


def _cikis_mi(metin: str) -> bool:
    # Metnin program çıkışı komutu olup olmadığını döndürür.
    # komut_isle()'nin EN SONUNDA çağrılır (hiçbir komut eşleşmediyse).
    m = metin.strip()

    # 1) Tam ifade eşleşmesi
    if m in _CIKIS_IFADELERI:
        return True

    # 2) "çıkış"/"çıkis"/"kapan" — net çıkış kelimeleri; ama wifi/bt/komut nesnesi
    #    varsa çıkış DEĞİL ("wifi kapan" gibi tuhaf duymalar programı kapatmasın).
    if any(k in m for k in ("çıkış", "çıkis", "kapan")):
        if not (_wifi_kelimesi_var_mi(m) or _bluetooth_kelimesi_var_mi(m)
                or any(ist in m for ist in _CIKIS_ISTISNALAR)):
            return True

    # 3) GÜVENLİK KİLİDİ: "kapat" YALNIZCA programın KENDİSİNE açık atıf varsa
    #    ("kendini kapat", "programı kapat", "friday'i kapat") çıkış sayılır.
    #    "vifi kapat", "b.t. kapat", tanınmayan "X kapat" → programı KAPATMAZ.
    #    (Eski kural "kapat + istisna-yok → çıkış" idi; istisna listesinde olmayan
    #     yeni bir yanlış-duyma — vifi, b.t. — programı kapatıyordu. Artık kapanmıyor.)
    if "kapat" in m and any(p in m for p in _PROGRAM_KAPAT_KELIMELERI):
        return True

    return False


# ── KOMUT TAKİP YARDIMCISI ────────────────────────────────────────────────────

def _izle(komut_adi: str) -> None:
    """Başarılı komut kullanımını hafıza istatistik ve alışkanlık takibine kaydeder.

    Her başarılı komut bloğundan return False öncesinde çağrılır.
    Hata sessizce yutulur — hafıza modülü yoksa uygulama çökmez.
    """
    try:
        komut_say(komut_adi)
        aliskanlik_kaydet(komut_adi)
    except Exception:
        pass


# ── FUZZY KOMUT TABLOSU ───────────────────────────────────────────────────────

# Fuzzy komut tablosu — ilk kullanımda _fuzzy_tablo_olustur() ile doldurulur.
_FUZZY_TABLO: list = []


def _fuzzy_tablo_olustur() -> list:
    # Lambda'lar çağrı anında çözümlenir, import sırasında değil.
    # Bu yüzden tüm importlar tamamlandıktan sonra güvenle çağrılabilir.
    return [
        # Spotify — duraklatma / devam
        (["duraklat", "durdur"],                        lambda m, d: muzik_duraklat()),
        (["devam et"],                                  lambda m, d: calma_yonet(m)),
        # Spotify — navigasyon
        # "geç" KALDIRILDI: 3 harfli, "gece modu" gibi kelimelere 80 skorla yanlış eşleşiyordu.
        (["sonraki şarkı", "sonraki parça", "sonraki"],  lambda m, d: sonraki_sarki()),
        (["önceki şarkı", "önceki parça", "önceki"],    lambda m, d: onceki_sarki()),
        # Spotify — bilgi
        (["ne çalıyor", "hangi şarkı", "ne oynuyor"],   lambda m, d: simdi_calan()),
        # Spotify — mod
        (["karıştır", "karışık"],                       lambda m, d: karistir_ac_kapa()),
        (["tekrar modu", "tekrarla"],                   lambda m, d: tekrar_modu_degistir()),
        (["şarkıyı beğen", "beğen", "bunu beğendim"],  lambda m, d: sarki_begen()),
        # "çal"/"oynat" KALDIRILDI: 3 harflik anahtarlar fuzzy'de yanlış eşleşiyordu
        # ("altyazı m.k." → "çal" skor 80 → istenmeden müzik çalıyordu). Bu tetikleyiciler
        # zaten SPO-11'de ilk-kelime TAM eşleşmeyle yakalanıyor; fuzzy'ye gerek yok.
        # Sabah raporu
        (["sabah raporu", "günaydın brifing", "rapor ver", "günlük rapor"],
                                                         lambda m, d: sabah_raporu_ver(d)),
        # Bilgi / arama
        # "hava durumu"/"hava nasıl" KALDIRILDI: pre-brain KOMUT 6b zaten yakalıyor.
        # Fuzzy'de bırakılırsa "pil durumu" (skor 82) gibi yanlış eşleşmeler oluyordu.
        (["takvim", "bugün ne var"],                    lambda m, d: takvimi_soyle(d)),
        (["notlarımı oku", "notlarım ne"],              lambda m, d: notlari_oku()),
        (["tarayıcı", "chrome", "internet"],            lambda m, d: tarayici_ac()),
        (["not defteri", "notepad"],                    lambda m, d: not_defteri_ac()),
        (["hesap makinesi"],                            lambda m, d: hesap_makinesi_ac()),
        # "hatırlat" KALDIRILDI: KOMUT 8 zaten tam eşleşmeyle yakalıyor; fuzzy'de
        # bırakılınca "hayır" (skor 80) gibi kısa kelimeler yanlış tetikliyordu.
        (["çevir"],                                     lambda m, d: metni_cevir(m)),
        # Sistem/donanım komutları FUZZY'DEN ÇIKARILDI.
        # wifi, bluetooth, ses, parlaklık, klavye ışığı, performans, touchpad vb.
        # artık Tier 1'de _sistem_donanim_yonlendir() ile DETERMİNİSTİK yönlendiriliyor
        # (kesin kelimeler; yanlış fuzzy eşleşme riski yok).
        # Hafıza (fuzzy yedek)
        (["beni tanı", "hakkımda ne biliyorsun"],       lambda m, d: konus(kullanici_ozeti())),
        (["ben kimim", "adımı biliyor musun"],          lambda m, d: konus(
            f"Adın {bilgi_getir('isim')}." if bilgi_getir("isim") else "Adını bilmiyorum."
        )),
        (["en çok ne kullanıyorum", "alışkanlıklarım ne"], lambda m, d: _fuzzy_istatistik()),
        (["en son ne konuştuk", "neler konuştuk"],      lambda m, d: _fuzzy_gecmis()),
    ]


def _fuzzy_istatistik():
    """Fuzzy tablodan çağrılan istatistik yardımcısı."""
    liste = en_cok_kullanilan(5)
    if not liste:
        konus("Henüz yeterli komut geçmişim yok.")
    else:
        parcalar = [f"{ad.replace('_', ' ')} ({sayi} kez)" for ad, sayi in liste]
        konus("En çok kullandığın komutlar: " + ", ".join(parcalar) + ".")


def _fuzzy_gecmis():
    """Fuzzy tablodan çağrılan geçmiş yardımcısı."""
    gecmis = son_konusmalar(3)
    if not gecmis:
        konus("Henüz kaydedilmiş bir konuşmamız yok.")
    else:
        for k in gecmis:
            saat_str = k["tarih"][11:16]
            konus(f"Saat {saat_str}'de '{k['kullanici']}' dedin.")


# ── LLM DISPATCH TABLOSU ─────────────────────────────────────────────────────
# komut_adi string'i (beyin.py çıktısı) → gerçek Python fonksiyon çağrısı.
# İlk LLM kullanımında _llm_dispatch_al() ile doldurulur (lazy init).
# Yeni komut eklenirken hem buraya hem beyin.py _KOMUT_LISTESI'ne ekle.
_LLM_DISPATCH: dict = {}


def _llm_dispatch_olustur() -> dict:
    # Lambda imzası: (p: parametre str, d: mod str) → None
    # p: LLM'in çıkardığı ek bilgi (şehir, şarkı adı, komut parametresi vb.)
    # d: "sesli" veya "yazili"
    # Sistem/donanım komutları artık yalnızca buradan çağrılır (pre-brain SIS blokları kaldırıldı).
    return {
        # ── MÜZİK ────────────────────────────────────────────────────────────
        "muzik_cal":           lambda p, d: calma_yonet(p if p else "müzik çal"),
        "muzik_duraklat":      lambda p, d: muzik_duraklat(),
        "muzik_devam":         lambda p, d: muzik_devam_et(),
        "sonraki_sarki":       lambda p, d: sonraki_sarki(),
        "onceki_sarki":        lambda p, d: onceki_sarki(),
        "playlist_cal":        lambda p, d: (playlist_cal(p) if p
                                              else konus("Hangi playlist'i çalmamı istersin?")),
        # ── BİLGİ / TAKVIM / GÖREV ───────────────────────────────────────────
        "hava_durumu":         lambda p, d: hava_durumu_soyle(p if p else "hava durumu", d),
        "takvim":              lambda p, d: (belirli_tarih_etkinlikleri(p, d) if p
                                              else takvimi_soyle(d)),
        "etkinlik_ekle":       lambda p, d: etkinlik_ekle(p if p else "", d),
        "ozel_gun":            lambda p, d: ozel_gun_soyle(p if p else "bugün", d),
        "dosya_ara":           lambda p, d: (dosya_ara_ve_ac(p, d) if p
                                              else konus("Ne aramamı istersin?")),
        "not_al":              lambda p, d: (not_ekle(p) if p
                                              else konus("Ne not alayım?")),
        "notlari_oku":         lambda p, d: notlari_oku(),
        # Serbest ifade ("notlarımı temizle" gibi) → kapsamlı not tablosu
        "not_sil":             lambda p, d: notlar_komut_isle(f"{p} sil" if p else "notları sil", d),
        "hatirlatici_kur":     lambda p, d: (hatirlatici_kur(p) if p
                                              else konus("Ne zaman ne hatırlatayım?")),
        "cevir":               lambda p, d: (metni_cevir(p) if p
                                              else konus("Ne çevireyim?")),
        # Tüm mail niyetleri kapsamlı tabloya gider (oku/gönder/sil/ara/say/reklam).
        "mail_oku":            lambda p, d: mail_komut_isle(p if p else "mailleri oku", d),
        "mail_gonder":         lambda p, d: mail_komut_isle(f"mail at {p}" if p else "mail gönder", d),
        "sabah_raporu":        lambda p, d: sabah_raporu_ver(d),
        "beni_tani":           lambda p, d: konus(kullanici_ozeti()),
        "tarayici_ac":         lambda p, d: tarayici_ac(),
        "bilgisayar_kapat":    lambda p, d: bilgisayari_kapat(d),
        # ── SİSTEM SESİ ───────────────────────────────────────────────────────
        # "sustur" → ses_sustur; "mute kaldır" → ses_ac; seviye → sistem_sesi
        "sistem_sesi":         lambda p, d: sistem_sesi_ayarla(f"sesi {p}" if p else "sesi"),
        "ses_sustur":          lambda p, d: sistem_sesi_sustur(),
        "ses_ac":              lambda p, d: sistem_sesi_ac(),
        # ── EKRAN / GÖRÜNTÜ ───────────────────────────────────────────────────
        # parlaklik = EKRAN parlaklığı; klavye_isigi = KLAVYE — birbirinden FARKLI
        "parlaklik":           lambda p, d: parlaklik_ayarla(f"parlaklık {p}" if p else "parlaklık"),
        "klavye_isigi":        lambda p, d: klavye_isigi_ayarla(p if p else "aç"),
        "klavye_renk":         lambda p, d: klavye_renk_ayarla(p if p else "beyaz"),
        "klavye_efekt":        lambda p, d: klavye_efekt_ayarla(p if p else "sabit"),
        "ekran_kilitle":       lambda p, d: ekran_kilitle(),
        "ekran_kapat":         lambda p, d: ekrani_kapat(),
        "gece_modu":           lambda p, d: gece_modu(),
        "ekran_modu":          lambda p, d: ekran_modu_ayarla(p if p else "ekran"),
        # ── AĞ / BAĞLANTI ─────────────────────────────────────────────────────
        # wifi ve bluetooth AYRI cihazlar — dispatch'te birbirlerine asla köprü yok
        "wifi_ac":             lambda p, d: wifi_ac(),
        "wifi_kapat":          lambda p, d: wifi_kapat(),
        "bluetooth_ac":        lambda p, d: bluetooth_ac(),
        "bluetooth_kapat":     lambda p, d: bluetooth_kapat(),
        "ucak_modu":           lambda p, d: ucak_modu(),
        # ── GÜÇ / PERFORMANS ──────────────────────────────────────────────────
        "performans_modu":     lambda p, d: performans_modu(),
        "denge_modu":          lambda p, d: denge_modu(),
        "tasarruf_modu":       lambda p, d: tasarruf_modu(),
        "uyku_modu":           lambda p, d: uyku_modu(d),
        "yeniden_baslat":      lambda p, d: yeniden_baslat(d),
        "oturum_kapat":        lambda p, d: oturum_kapat(),
        # ── DONANIM (ASUS) ────────────────────────────────────────────────────
        "fan_modu":            lambda p, d: fan_modu_ayarla(p if p else "dengeli"),
        "gpu_modu":            lambda p, d: gpu_modu_ayarla(p if p else "standart", d),
        # ── GİRİŞ AYGITLARI ──────────────────────────────────────────────────
        "touchpad_ac":         lambda p, d: touchpad_ac(),
        "touchpad_kapat":      lambda p, d: touchpad_kapat(),
        "windows_tusu_ac":     lambda p, d: windows_tusu_ac(),
        "windows_tusu_kapat":  lambda p, d: windows_tusu_kapat(),
        # ── SİSTEM BİLGİSİ ────────────────────────────────────────────────────
        "pil_durumu":          lambda p, d: pil_durumu(),
        "sistem_durumu":       lambda p, d: sistem_durumu(),
        "cpu_sicakligi":       lambda p, d: cpu_sicakligi(),
        # ── UYGULAMA YÖNETİMİ ─────────────────────────────────────────────────
        "uygulama_kapat":      lambda p, d: (uygulama_kapat(p) if p
                                              else konus("Hangi uygulamayı kapatayım?")),
    }


def _llm_dispatch_al() -> dict:
    """Dispatch tablosunu ilk çağrıda oluşturur; sonraki çağrılarda önbellekten döner."""
    global _LLM_DISPATCH
    if not _LLM_DISPATCH:
        _LLM_DISPATCH = _llm_dispatch_olustur()
    return _LLM_DISPATCH


def _sistem_donanim_yonlendir(metin: str, mod: str) -> bool:
    """TIER 1 — Tüm sistem/donanım komutlarını DETERMİNİSTİK kalıpla yönlendirir.

    Bu fonksiyon artık YEDEK DEĞİL, BİRİNCİL yoldur: komut_isle() içinde LLM
    beyninden ÖNCE çağrılır. Donanım ve kritik komutlar olasılığa bırakılamaz —
    her zaman aynı, kesin sonucu üretir ve anında çalışır (LLM beklemez).
    (Eski adı _sistem_komut_yedek idi; rolü "yedek"ten "birincil"e taşındı.)

    Kurallar:
    - Fuzzy eşleştirme YOK — yalnızca zorunlu, ayırt edici anahtar kelimeler
    - Sayılar HER ZAMAN regex ile orijinal metinden çıkarılır (ilgili fonksiyonlar
      kendi içinde re.search(r"\\d+", metin) yapar) — asla LLM'e sorulmaz
    - WiFi için: "wifi"/"kablosuz" ZORUNLU + bluetooth kelimeleri OLMAMALI
    - Bluetooth için: _bluetooth_kelimesi_var_mi() ZORUNLU
    - Klavye ışığı için: "klavye" ZORUNLU + ışık/parla bağlamı ZORUNLU
    - Parlaklık için: "parlaklık" ZORUNLU + "klavye" OLMAMALI
    - Ses için: müzik/spotify bağlamı OLMAMALI (o durumda Spotify sesi devreye girer)
    Eşleşme bulunamazsa False döner → komut_isle LLM beyne (Tier 2) geçer.
    """
    # ── WiFi ──────────────────────────────────────────────────────────────────
    # wifi/varyasyonları (vifi, vayfay…) ZORUNLU; bluetooth kelimeleri varsa WiFi DEĞİLDİR.
    if _wifi_kelimesi_var_mi(metin) and not _bluetooth_kelimesi_var_mi(metin):
        if "kapat" in metin or "söndür" in metin or "kapa" in metin:
            wifi_kapat(); _izle("yedek_wifi_kapat")
        else:
            wifi_ac(); _izle("yedek_wifi_ac")
        return True

    # ── Bluetooth ─────────────────────────────────────────────────────────────
    # "bluetooth"/"bt"/"blutut" ZORUNLU (kelime sınırı kontrolü _bluetooth_kelimesi_var_mi'de).
    if _bluetooth_kelimesi_var_mi(metin):
        if "kapat" in metin or "söndür" in metin or "kapa" in metin:
            bluetooth_kapat(); _izle("yedek_bt_kapat")
        else:
            bluetooth_ac(); _izle("yedek_bt_ac")
        return True

    # ── Klavye aydınlatması (parlaklık + renk + efekt) ────────────────────────
    # "klavye" ZORUNLU. Üç alt komut, ÖNCELİK sırasıyla (efekt → renk → parlaklık):
    #   1) EFEKT:  "klavye gökkuşağı/nefes/renk döngüsü/strobe/sabit"
    #   2) RENK:   "klavyeyi kırmızı/yeşil/mavi… yap"
    #   3) PARLAKLIK/AÇ-KAPAT: "klavye ışığını aç/kapat", "klavye parlaklığı"
    # Sıra önemli: efekt/renk kontrolü parlaklıktan ÖNCE, çünkü "klavyeyi kırmızı yap"
    # gibi komutlarda aç/kapat kelimesi yoktur ama renk vardır.
    if "klavye" in metin:
        _EFEKT_KELIMELERI = (
            "gökkuşağı", "gök kuşağı", "rainbow", "nefes", "breathe",
            "renk döngüsü", "color cycle", "döngü", "strobe", "yanıp sön",
            "sabit", "static",
        )
        _RENK_KELIMELERI = (
            "kırmızı", "yeşil", "mavi", "beyaz", "mor", "turuncu",
            "sarı", "pembe", "camgöbeği", "cyan",
        )
        if any(k in metin for k in _EFEKT_KELIMELERI):
            klavye_efekt_ayarla(metin)
            _izle("klavye_efekt")
            return True
        if any(k in metin for k in _RENK_KELIMELERI):
            klavye_renk_ayarla(metin)
            _izle("klavye_renk")
            return True
        # Parlaklık/aç-kapat/seviye kelimesi VEYA 0-3 arası sayı ("klavye ışığı 2").
        # Efekt ve renk yukarıda zaten kontrol edildiğinden buraya düşen sayı = seviye.
        # "ışıg"/"ışıgı" gibi ğ→g sapmalarını da yakalamak için "ışı" kökü eklendi.
        if (any(k in metin for k in ("ışı", "aydın", "parla", "parlaklık",
                                     "aç", "kapat", "söndür", "seviye",
                                     "düşük", "orta", "yüksek", "maksimum",
                                     "minimal", "ilk", "tam"))
                or any(c in metin for c in "0123")):
            klavye_isigi_ayarla(metin)
            _izle("klavye_isigi")
            return True

    # ── Ekran parlaklığı ──────────────────────────────────────────────────────
    # "parlaklı" ZORUNLU + "klavye" OLMAMALI.
    # "parlaklı" hem "parlaklık" hem "parlaklığı" formlarını yakalar
    # ("parlaklık" ve "parlaklığı" farklı Türkçe harf dizileridir — biri diğerinin substring'i değil).
    if "parlaklı" in metin and "klavye" not in metin:
        parlaklik_ayarla(metin)
        _izle("yedek_parlaklik")
        return True

    # ── Sistem sesi ───────────────────────────────────────────────────────────
    # Müzik/Spotify/şarkı bağlamı YOKSA ses komutları sisteme gider.
    # KÖK kontrolü (Türkçe ek toleransı): "müzi" → müzik/müziğin/müziği,
    # "şark" → şarkı/şarkının/şarkıyı, "parça" → parça/parçanın. Bu sayede
    # "müziğin sesini kıs" gibi çekimli formlar sistem sesine YANLIŞLIKLA gitmez;
    # Spotify bağlamı sayıldığından sistem sesi dalı atlanır (Spotify/LLM işler).
    if not any(k in metin for k in ("müzi", "spotify", "şark", "parça")):
        if "sustur" in metin or "sessize al" in metin:
            sistem_sesi_sustur(); _izle("yedek_ses_sustur"); return True
        if "sesi aç" in metin or "ses aç" in metin:
            sistem_sesi_ac(); _izle("yedek_ses_ac"); return True
        if ("sesi" in metin
                and any(k in metin for k in ("kıs", "yükselt", "artır", "azalt", "düşür"))):
            sistem_sesi_ayarla(metin); _izle("yedek_ses_ayarla"); return True

    # ── Ekranı kilitle ────────────────────────────────────────────────────────
    if "ekranı kilitle" in metin or "ekran kilitle" in metin:
        ekran_kilitle(); _izle("yedek_ekran_kilitle"); return True

    # ── Ekranı kapat (monitör off, PC kapatmaz) ───────────────────────────────
    if "ekranı kapat" in metin or "monitörü kapat" in metin or "monitör kapat" in metin:
        ekrani_kapat(); _izle("yedek_ekran_kapat"); return True

    # ── Güç / Performans modları ──────────────────────────────────────────────
    if "performans modu" in metin or "yüksek performans" in metin:
        performans_modu(); _izle("yedek_performans"); return True
    if "dengeli mod" in metin or "denge modu" in metin:
        denge_modu(); _izle("yedek_denge"); return True
    if "tasarruf modu" in metin or "güç tasarrufu" in metin or "pil tasarrufu" in metin:
        tasarruf_modu(); _izle("yedek_tasarruf"); return True

    # ── Uyku / Yeniden başlat / Oturum kapat ─────────────────────────────────
    if "uyku modu" in metin or "bilgisayarı uyut" in metin or "uyku moduna al" in metin:
        uyku_modu(mod); _izle("yedek_uyku"); return True
    if "yeniden başlat" in metin or "restart" in metin:
        yeniden_baslat(mod); _izle("yedek_restart"); return True
    # "oturumu kapat" / "oturumu sonlandır" — program çıkışından AYRI (komut_isle'deki çıkış kontrolüyle çakışmaz)
    if "oturumu kapat" in metin or "oturumu sonlandır" in metin or "oturum kapat" in metin:
        oturum_kapat(); _izle("yedek_oturum_kapat"); return True

    # ── Pil / Sistem / CPU bilgisi ────────────────────────────────────────────
    if "pil" in metin or "batarya" in metin or "şarj durumu" in metin:
        pil_durumu(); _izle("yedek_pil"); return True
    if "sıcaklık" in metin or "cpu sıcaklığı" in metin:
        cpu_sicakligi(); _izle("yedek_cpu_sicaklik"); return True
    if "sistem durumu" in metin or "bilgisayar durumu" in metin:
        sistem_durumu(); _izle("yedek_sistem_durumu"); return True

    # ── Gece modu / Uçak modu ─────────────────────────────────────────────────
    if "gece modu" in metin or "gece ışığı" in metin:
        gece_modu(); _izle("yedek_gece_modu"); return True
    if "uçak modu" in metin:
        ucak_modu(); _izle("yedek_ucak_modu"); return True

    # ── Touchpad ─────────────────────────────────────────────────────────────
    if "touchpad" in metin:
        if "kapat" in metin or "devre dışı" in metin:
            touchpad_kapat()
        else:
            touchpad_ac()
        _izle("yedek_touchpad"); return True

    # ── Fan / GPU / Windows tuşu / Ekran tazeleme ────────────────────────────
    if "fan" in metin and any(k in metin for k in ("mod", "sessiz", "turbo", "performans", "dengeli")):
        fan_modu_ayarla(metin); _izle("yedek_fan"); return True
    if "gpu modu" in metin or "ekran kartı modu" in metin or "optimus" in metin:
        gpu_modu_ayarla(metin, mod); _izle("yedek_gpu"); return True
    if "windows tuş" in metin:
        if "kapat" in metin or "devre dışı" in metin or "kilitle" in metin:
            windows_tusu_kapat()
        else:
            windows_tusu_ac()
        _izle("yedek_windows_tusu"); return True
    if ("tazeleme" in metin or "yenileme hızı" in metin
            or ("hz" in metin and "ekran" in metin)):
        ekran_modu_ayarla(metin); _izle("yedek_ekran_modu"); return True

    # ── Uygulama kapat ────────────────────────────────────────────────────────
    # Bilinen uygulama adı + "kapat" kombinasyonu.
    _UYGULAMALAR_YEDEK = {
        "chrome", "firefox", "edge", "spotify", "discord", "notepad",
        "not defteri", "word", "excel", "powerpoint", "outlook", "teams",
        "zoom", "vlc", "steam", "armoury", "explorer", "paint", "obs",
        "vscode", "visual studio",
    }
    if "kapat" in metin and any(u in metin for u in _UYGULAMALAR_YEDEK):
        uygulama_kapat(metin); _izle("yedek_uygulama_kapat"); return True

    return False  # Hiçbir sistem komutu eşleşmedi


def _saat_soyle():
    # Şu anki saati söyler. Deterministik — LLM'e gitmez (LLM "saat kaç"a
    # alakasız "İyiyim teşekkürler" diyebiliyordu).
    from datetime import datetime
    s = datetime.now()
    konus(f"Saat {s.hour:02d}:{s.minute:02d}.")


def _tarih_soyle():
    # Bugünün tarihini Türkçe söyler.
    from datetime import datetime
    _AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
              "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    _GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    s = datetime.now()
    konus(f"Bugün {s.day} {_AYLAR[s.month]} {s.year}, {_GUNLER[s.weekday()]}.")


# ── İSİM / KİMLİK KOMUTLARI (deterministik, LLM'e gitmez) ────────────────────
# KÖK SEBEP: Bu komutlar LLM'e düşünce karışıyordu (kullanıcı adı ↔ asistan adı,
# soru ↔ kayıt). Hepsi burada KESİN kalıplarla, zamir ayrımıyla çözülür.
#
# ZAMİR AYRIMI (çok önemli):
#   benim / bana / ben / adım / ismim  → KULLANICI ile ilgili
#   senin / sana / sen / adın / ismin  → ASİSTAN ile ilgili
#   "adım"(benim) ≠ "adın"(senin) — tek harf farkı (m/n) ama anlam zıt.

# İsim olarak KAYDEDİLMEYECEK soru kelimeleri (bunlar sorgu işaretidir)
_SORU_KELIMELERI = {"ne", "nedir", "kim", "kimdir", "kimim", "kimsin", "neyim", "ne?"}

# İsim ayıklarken atılacak dolgu/ek kelimeler ("ismin jarvis olsun" → "jarvis")
_ISIM_DOLGU = {
    "olsun", "olacak", "diyeceğim", "diyebilirsin", "diyebilir", "de", "der",
    "desinler", "bundan", "sonra", "artık", "lütfen", "diye", "çağır", "seslen",
    "koy", "yap",
}


def _isim_temizle(ham: str) -> str:
    # Ham metinden dolgu/ek ve noktalama temizler, çok kelimeli ismi korur.
    # "bundan sonra jarvis" → "Jarvis"; "ahmet mehmet" → "Ahmet Mehmet".
    s = ham.strip(" ,.!?'\"")
    kelimeler = [k for k in s.split()
                 if k.lower() not in _ISIM_DOLGU and k.lower() not in _SORU_KELIMELERI]
    return " ".join(kelimeler).strip()


def _isim_komut_isle(metin: str, mod: str) -> bool:
    # İsim/kimlik komutlarını işler. True → işlendi (LLM'e gitmesin).
    # SIRA: ASK (soru) kalıpları SET'ten ÖNCE — "adın ne" yanlışlıkla kayıt olmasın.
    m = metin.strip()
    m_soru = m.rstrip("?").strip()

    # ── 1) ASİSTAN ADI SOR ── "sen kimsin", "senin adın ne", "adın ne/nedir"
    if ("sen kimsin" in m
            or m_soru.endswith("adın ne") or m_soru.endswith("adın nedir")
            or m_soru.endswith("ismin ne") or m_soru.endswith("ismin nedir")
            or m_soru.endswith("senin adın") or m_soru == "adın"):
        konus(f"Ben {asistan_adi_getir()}.")
        _izle("asistan_adi_sor")
        return True

    # ── 2) KULLANICI ADI SOR ── "ben kimim", "adımı söyle", "benim adım ne"
    if ("ben kimim" in m or "adımı söyle" in m or "ismimi söyle" in m
            or "adımı biliyor" in m or "ismimi biliyor" in m or "beni tanıyor musun" in m
            or m_soru.endswith("adım ne") or m_soru.endswith("adım nedir")
            or m_soru.endswith("ismim ne") or m_soru.endswith("ismim nedir")):
        isim = bilgi_getir("isim")
        if isim:
            konus(f"Senin adın {isim}.")
        else:
            konus("Adını henüz bilmiyorum, bana adını söyleyebilirsin.")
        _izle("kullanici_adi_sor")
        return True

    # Fiil-sonu (naming verb) — "sana/bana X de/diyeceğim" kalıbını güvenle ayırt eder.
    _NAMING_FIIL = ("de", "diyeceğim", "diyebilirsin", "desinler", "der", "diye")
    _fiil_sonu = any(m_soru.endswith(v) for v in _NAMING_FIIL)

    # ── 3) ASİSTAN ADI DEĞİŞTİR ── (kullanıcı adına DOKUNMAZ)
    # Yalnızca YÜKSEK KESİNLİKLİ kalıplar; "sana teşekkür ederim" gibi cümleler
    # yanlışlıkla isim atamasın diye sıkı kurallar:
    _asis_ad = ""
    if m.startswith("senin adın "):
        _asis_ad = _isim_temizle(m[len("senin adın "):])
    elif m.startswith("senin ismin "):
        _asis_ad = _isim_temizle(m[len("senin ismin "):])
    elif ("adın " in m or "ismin " in m) and ("olsun" in m or "bundan sonra" in m):
        # "adın jarvis olsun", "ismin bundan sonra jarvis"
        _tetik = "adın " if "adın " in m else "ismin "
        _asis_ad = _isim_temizle(m.split(_tetik, 1)[1])
    elif m.startswith("sana ") and _fiil_sonu:
        # "sana jarvis de" — sonda naming fiili şart (yoksa "sana yardım et" gibi cümle değil)
        _asis_ad = _isim_temizle(m[len("sana "):])
    if _asis_ad:
        asistan_adi_kaydet(_asis_ad.title())
        konus(f"Tamam, bundan sonra bana {_asis_ad.title()} diyebilirsin.")
        _izle("asistan_adi_degistir")
        return True

    # ── 4) KULLANICI ADI DEĞİŞTİR ── (asistan adına DOKUNMAZ)
    _kul_ad = ""
    if m.startswith("benim adım "):
        _kul_ad = _isim_temizle(m[len("benim adım "):])
    elif m.startswith("benim ismim "):
        _kul_ad = _isim_temizle(m[len("benim ismim "):])
    elif m.startswith("bana ") and _fiil_sonu:
        # "bana doğukan de" — sonda naming fiili şart ("bana yardım et" → isim DEĞİL)
        _kul_ad = _isim_temizle(m[len("bana "):])
    elif (m.startswith("adım ") or m.startswith("ismim ")) and len(m.split()) <= 3:
        # bare "adım doğukan" — kısa tut (ASK "adım ne" yukarıda elendi)
        _tetik = "adım " if m.startswith("adım ") else "ismim "
        _kul_ad = _isim_temizle(m[len(_tetik):])
    if _kul_ad:
        bilgi_kaydet("isim", _kul_ad.title())
        konus(f"Anladım, adın {_kul_ad.title()}. Bunu aklımda tutacağım.")
        _izle("kullanici_adi_kaydet")
        return True

    # "ben X" — yalnızca tam iki kelime ("ben doğukan") ve X bir isim gibiyse.
    # "ben geliyorum/iyiyim" gibi cümleleri YANLIŞLIKLA isim sanmamak için dar tutuldu.
    _kel = m.split()
    if (len(_kel) == 2 and _kel[0] == "ben"
            and _kel[1] not in _SORU_KELIMELERI
            and _kel[1] not in _ISIM_DOLGU
            and _kel[1] not in {"geliyorum", "gidiyorum", "iyiyim", "buradayım",
                                 "kötüyüm", "yoruldum", "hazırım", "uykusuzum"}
            and _kel[1].isalpha()):
        bilgi_kaydet("isim", _kel[1].title())
        konus(f"Anladım, adın {_kel[1].title()}. Bunu aklımda tutacağım.")
        _izle("kullanici_adi_kaydet")
        return True

    return False


def _fuzzy_komut_isle(metin: str, mod: str) -> bool:
    # Tabloyu ilk kullanımda oluştur (circular-import riski olmadan).
    global _FUZZY_TABLO
    if not _FUZZY_TABLO:
        _FUZZY_TABLO = _fuzzy_tablo_olustur()

    for anahtar_listesi, eylem in _FUZZY_TABLO:
        for anahtar in anahtar_listesi:
            skor = _fuzz.partial_ratio(anahtar, metin)
            if skor >= _FUZZY_ESIK:
                print(f"[FUZZY] '{metin}' → '{anahtar}' (skor: {skor})")
                eylem(metin, mod)
                return True

    return False


def komut_isle(metin, mod):
    # Kullanıcıdan gelen komutu analiz eder ve uygun işlemi gerçekleştirir.
    #
    # metin : komut metni (küçük harfe çevrilmiş olmalı)
    # mod   : "sesli" veya "yazili"
    #
    # Dönüş değeri:
    #   True  → ana döngü sonlandırılmalı
    #   False → döngüye devam et
    #
    # ═══════════════════════════════════════════════════════════════════════
    # İKİ KATMANLI MİMARİ — "KOD BİRİNCİL, LLM YEDEK"
    # ───────────────────────────────────────────────────────────────────────
    # TIER 1 (DETERMİNİSTİK KOD — kalıp eşleştirme + regex, her zaman kesin sonuç):
    #   1) Genel komutlar (tarayıcı, mail, takvim, hava, not, hatırlatıcı, çeviri…)
    #   2) Hafıza / kişiselleştirme (isim, istatistik, geçmiş…)
    #   3) Spotify (çal, duraklat, sonraki, playlist, müzik sesi…)
    #   4) Sistem/donanım (wifi, bluetooth, parlaklık, klavye, ses, fan, gpu,
    #      güç planı, uyku, oturum kapat, pil, sıcaklık…) — _sistem_donanim_yonlendir
    #   5) Fuzzy (yalnızca düşük riskli metin komutları için Whisper hata ağı)
    #   → Sayılar HER ZAMAN regex ile metinden çıkarılır, ASLA LLM'e sorulmaz.
    #   → Çıkış kontrolü (_cikis_mi) Tier 1'den SONRA, LLM'den ÖNCE.
    #
    # TIER 2 (LLM BEYİN — yalnızca yedek): Tier 1'de HİÇBİR kalıp eşleşmezse.
    #   Sadece (a) serbest/dolaylı ifadeler ve (b) sohbet için kullanılır.
    # ═══════════════════════════════════════════════════════════════════════

    # ── GENEL KOMUTLAR ───────────────────────────────────────────────────────

    # ----- KOMUT 0a: Saat -----
    # "saat kaç", "saat kaçtı", "kaçta" → şu anki saat. Deterministik.
    # NOT: "saat 5'te hatırlat" gibi komutlar "kaç" içermez → buraya takılmaz.
    if ("saat kaç" in metin or "saat kac" in metin or "saat kaçtı" in metin
            or metin.strip() in ("saat", "kaçta", "saat kaçta")):
        _saat_soyle()
        _izle("saat")
        return False

    # ----- KOMUT 0b: Tarih / gün -----
    if ("bugün günlerden ne" in metin or "günlerden ne" in metin
            or "hangi gündeyiz" in metin or "bugün ayın kaçı" in metin
            or "tarih ne" in metin or metin.strip() in ("tarih", "bugün ne günü")):
        _tarih_soyle()
        _izle("tarih")
        return False

    # ----- KOMUT 0c: Pano (clipboard) — oku / özetle / çevir -----
    # "pano" veya "kopyaladığım" geçen komutlar. ÇEVİR (KOMUT 9) ve mail/not gibi
    # kontrollerden ÖNCE gelmeli: yoksa "panodakini çevir" komut metnini çevirir.
    # Alt yönlendirme: özetle → çevir → (varsayılan) oku.
    if "pano" in metin or "kopyaladığım" in metin or "kopyaladigim" in metin:
        if "özetle" in metin or "özet" in metin or "ozetle" in metin:
            pano_ozetle(mod)
            _izle("pano_ozetle")
        elif "çevir" in metin or "cevir" in metin:
            # Tam metni gönder → hedef dil (almancaya/ingilizceye…) orada ayıklanır
            pano_cevir(mod, metin)
            _izle("pano_cevir")
        else:
            # "panodakini oku", "panoyu oku", "kopyaladığımı oku" → varsayılan oku
            pano_oku(mod)
            _izle("pano_oku")
        return False

    # ----- KOMUT 1: Tarayıcı aç -----
    if "tarayıcı" in metin or "chrome" in metin or "internet" in metin:
        tarayici_ac()
        _izle("tarayıcı")
        return False

    # ----- KOMUT 2: Not defteri aç -----
    if "not defteri" in metin or "notepad" in metin:
        not_defteri_ac()
        _izle("not_defteri")
        return False

    # ----- KOMUT 3: Hesap makinesi aç -----
    if "hesap makinesi" in metin:
        hesap_makinesi_ac()
        _izle("hesap_makinesi")
        return False

    # ----- KOMUT 4: Bilgisayarı kapat -----
    # DİKKAT: "kapat" kelimesi burada özel anlam taşır — bilgisayarı kapatır.
    if "bilgisayarı kapat" in metin or "bilgisayari kapat" in metin:
        _izle("bilgisayari_kapat")
        return bilgisayari_kapat(mod)

    # ----- KOMUT 5: Dosya ara -----
    for tetikleyici in ("dosya ara ", "dosya bul "):
        if metin.startswith(tetikleyici):
            arama_terimi = metin[len(tetikleyici):].strip()
            if arama_terimi:
                dosya_ara_ve_ac(arama_terimi, mod)
                _izle("dosya_ara")
            else:
                konus("Hangi dosyayı aramamı istersin? Lütfen bir isim belirt.")
            return False

    # ----- KOMUT 5c: Sabah/öğlen/akşam raporu — günlük brifing -----
    # "bugün ne var" → KOMUT 7 (takvim) ile çakışmaması için buraya dahil edilmedi.
    # ÖNEMLİ: "öğlen/öğle/akşam raporu" eskiden routing'de YOKTU → LLM'e düşüp
    # "verileri topladım" deyip boş çıkıyordu. Artık hepsi deterministik burada.
    # (Saat dilimine göre selamlamayı sabah_raporu_ver kendisi seçer.)
    if ("sabah raporu" in metin or "öğlen raporu" in metin or "öğle raporu" in metin
            or "akşam raporu" in metin or "gün raporu" in metin or "günlük rapor" in metin
            or "durum raporu" in metin or "rapor ver" in metin
            or "günaydın" in metin or "brifing" in metin):
        sabah_raporu_ver(mod)
        _izle("sabah_raporu")
        return False

    # ----- KOMUT 6a: Şehir / konum değiştir -----
    # Kaydedilmiş şehri siler ve yenisini sorar.
    if ("şehir değiştir" in metin or "konumu değiştir" in metin
            or "konum değiştir" in metin or "şehri değiştir" in metin):
        sehir_sifirla(mod)
        _izle("sehir_degistir")
        return False

    # ----- KOMUT 6b: Hava durumu -----
    # Tüm metin gönderilir; hava_durumu_soyle() şehir adını içinden çıkarır.
    if "hava durumu" in metin or "hava nasıl" in metin or "hava nasıl olacak" in metin:
        hava_durumu_soyle(metin, mod)
        _izle("hava_durumu")
        return False

    # ----- KOMUT 7a: Özel gün ("bugün ne günü", "14 mart ne günü") -----
    # Takvimden ÖNCE: "ne günü" ≠ "ne var". Tarih metinden çıkarılır (dateparser).
    if ("ne günü" in metin or "özel gün" in metin or "özel bir gün" in metin
            or "hangi özel" in metin):
        ozel_gun_soyle(metin, mod)
        _izle("ozel_gun")
        return False

    # ----- KOMUT 7b: Google Takvim — EKLE veya SORGULA -----
    # "ekle/oluştur/kaydet" → etkinlik ekle; aksi halde (belirtilen) tarihin
    # etkinliklerini listele. "ne var" tetikleyicisi "30 ağustosta ne var"ı da yakalar.
    if ("takvim" in metin or "etkinlik" in metin or "randevu" in metin
            or "programım" in metin or "ne var" in metin):
        if any(k in metin for k in ("ekle", "oluştur", "kaydet", "ekler misin",
                                     "ekleyebilir", "koy")):
            etkinlik_ekle(metin, mod)
            _izle("etkinlik_ekle")
        else:
            # Belirli tarih (yoksa bugün) etkinliklerini sorgula — eski "hep bugün" hatası giderildi
            belirli_tarih_etkinlikleri(metin, mod)
            _izle("takvim")
        return False

    # ----- KOMUT 8: Hatırlatıcı kur -----
    if "hatırlat" in metin:
        hatirlatici_kur(metin)
        _izle("hatirlatici")
        return False

    # ----- KOMUT 9: Çeviri -----
    if "çevir" in metin:
        metni_cevir(metin)
        _izle("ceviri")
        return False

    # ----- KOMUT 10-11: Notlar — TÜM not komutları tek kapıdan -----
    # ekle/oku/sil/say niyet ayrımı notlar_komut_isle()'de yapılır (kapsamlı tablo).
    # "not defteri" (Notepad) KOMUT 2'de yakalandığı için buraya düşmez.
    # Yeni not özelliği için notlar.notlar_komut_isle()'ye dal ekle — buraya dokunma.
    _NOT_TETIK = ("not al", "not ekle", "not düş", "not olarak",
                  "notu sil", "notları", "notların", "notlarım", "notumu", "notum",
                  "kaç not", "not sayısı")
    if any(t in metin for t in _NOT_TETIK):
        notlar_komut_isle(metin, mod)
        _izle("not")
        return False

    # ----- KOMUT 12-13: Gmail — TÜM mail komutları tek kapıdan -----
    # "mail"/"e-posta" geçen her komut mail_komut_isle()'ye gider; oku/gönder/sil/
    # ara/say/reklam-oku gibi niyet ayrımı ORADA yapılır (kapsamlı mail komut tablosu).
    # Yeni mail özelliği eklemek için gmail_yonetimi.mail_komut_isle()'ye dal ekle —
    # buraya dokunma. (Deterministik, LLM'e gitmez.)
    if "mail" in metin or "e-posta" in metin or "eposta" in metin or "maillerim" in metin:
        mail_komut_isle(metin, mod)
        _izle("mail")
        return False

    # ----- KOMUT 14: Google Drive -----
    if "drive" in metin:
        for on_ek in ("drive'da ara ", "drive ara ", "drive'da ", "drive "):
            if metin.startswith(on_ek):
                arama = metin[len(on_ek):].strip()
                break
        else:
            arama = metin.replace("drive", "").strip()
        if arama:
            drive_dosya_ara(arama, mod)
        else:
            konus("Drive'da ne aramamı istersin?")
        _izle("drive")
        return False

    # ── HAFIZA / KİŞİSELLEŞTİRME KOMUTLARI ─────────────────────────────────────
    # LLM bağlamı için ayrı bir bölümde tutulur — ileride kolay genişletilebilir.

    # ----- HAFIZA-1: Tüm bilgileri özetle -----
    # "beni" ile başlayan diğer kalıplardan önce gelmeli (beni tanı vs benim adım)
    if ("beni tanı" in metin or "hakkımda ne biliyorsun" in metin
            or "beni ne kadar tanıyorsun" in metin):
        konus(kullanici_ozeti())
        _izle("bilgi_ozeti")
        return False

    # ----- HAFIZA-2/3: İsim / kimlik (kullanıcı adı ↔ asistan adı) -----
    # Tüm isim mantığı _isim_komut_isle()'de: sor/kaydet ve kullanıcı/asistan ayrımı.
    # Zamir ayrımı sayesinde "senin adın jarvis" asistanı, "benim adım X" kullanıcıyı
    # değiştirir; "adımı söyle"/"benim adım ne" sorgudur (kayıt değil).
    if _isim_komut_isle(metin, mod):
        return False

    # ----- HAFIZA-4: Komut istatistikleri -----
    if any(k in metin for k in ("en çok ne kullanıyorum", "alışkanlıklarım ne",
                                 "sık kullandıklarım", "hangi komutları kullanıyorum")):
        _ist_liste = en_cok_kullanilan(5)
        if not _ist_liste:
            konus("Henüz yeterli komut geçmişim yok. Biraz daha kullandıktan sonra söyleyebilirim.")
        else:
            _ist_parcalar = [f"{ad.replace('_', ' ')} ({sayi} kez)" for ad, sayi in _ist_liste]
            konus("En çok kullandığın komutlar: " + ", ".join(_ist_parcalar) + ".")
        _izle("istatistik_sorgu")
        return False

    # ----- HAFIZA-5: Konuşma geçmişi -----
    if any(k in metin for k in ("en son ne konuştuk", "neler konuştuk",
                                 "konuşma geçmişimiz", "son konuşmalar")):
        _gecmis_liste = son_konusmalar(5)
        if not _gecmis_liste:
            konus("Henüz kaydedilmiş bir konuşmamız yok.")
        else:
            konus(f"Son {len(_gecmis_liste)} konuşmamdan bazıları:")
            for _gk in _gecmis_liste[-3:]:   # en fazla son 3'ü oku
                _gk_saat = _gk["tarih"][11:16]   # HH:MM kısmı
                konus(f"Saat {_gk_saat}'de sen '{_gk['kullanici']}' dedin.")
        _izle("gecmis_sorgu")
        return False

    # ── SİSTEM/DONANIM KOMUTLARI — KONUM NOTU ────────────────────────────────
    # WiFi, Bluetooth, parlaklık, klavye ışığı, ses, fan, GPU, touchpad, güç
    # planları vb. TÜM sistem komutları DETERMİNİSTİK olarak işlenir; ancak
    # yönlendirici (_sistem_donanim_yonlendir) Spotify bloğundan SONRA çağrılır.
    # Sebep: "müziğin sesini aç" gibi Spotify ses komutları (SPO-7) ÖNCE
    # denenmeli; sistem sesi dalı yalnızca müzik bağlamı YOKKEN devreye girsin.
    # (Çağrı noktası: aşağıdaki "TIER 1 — SİSTEM / DONANIM KOMUTLARI" bloğu.)

    # ── SPOTİFY KOMUTLARI ────────────────────────────────────────────────────
    # Sıra kritiktir: spesifik kontroller önce, genel tetikleyiciler en sona.
    # "bilgisayarı kapat" KOMUT 4'te yakalandı → "durdur"/"dur" burada güvenli.

    # ----- SPO-1: Playlist çal (ESNEK kelime sırası + ad ayıklama) -----
    # Desteklenen varyasyonlar: "playlist çal X", "X playlist çal",
    # "sakin bir playlist çal", "sakin çalma listemi aç" …
    # NİYET = ("playlist"/"çalma listesi/listemi") + ("çal"/"oynat"/"başlat"/"aç").
    # "playliste ekle X" buraya DÜŞMEZ (ekle ≠ çal/aç) → SPO-2'ye gider.
    # Tam metin playlist_cal'a verilir; ad ayıklama + bulanık eşleştirme orada yapılır.
    if (any(k in metin for k in ("playlist", "çalma listesi", "çalma listemi",
                                 "çalma listesini"))
            and any(k in metin for k in ("çal", "oynat", "başlat", "aç"))):
        playlist_cal(metin)
        _izle("playlist_cal")
        return False

    # ----- SPO-2: Playlist'e ekle -----
    for tetik in ("playliste ekle ", "playlist'e ekle ", "listesine ekle "):
        if metin.startswith(tetik):
            pl_adi = metin[len(tetik):].strip()
            if pl_adi:
                playliste_ekle(pl_adi)
                _izle("playliste_ekle")
            else:
                konus("Hangi playlist'e ekleyeyim?")
            return False

    # ----- SPO-3: Şu an ne çalıyor -----
    if ("ne çalıyor" in metin or "şu an ne çalıyor" in metin
            or "hangi şarkı" in metin or "ne oynuyor" in metin):
        simdi_calan()
        _izle("ne_caliyor")
        return False

    # ----- SPO-4: Duraklat / Durdur -----
    # "bilgisayarı" ile birlikte gelmez → güvenli.
    if "duraklat" in metin or "durdur" in metin or metin.strip() == "dur":
        muzik_duraklat()
        _izle("muzik_duraklat")
        return False

    # ----- SPO-5: Sonraki şarkı / şarkı değiştir -----
    # "önceki" içeriyorsa çakışmayı önlemek için geç; önceki kontrolüne düş.
    # "şarkı/parça/müzik değiştir", "başka şarkı", "şarkı atla" = sonraki şarkı demektir.
    # "değiştir" TEK BAŞINA belirsiz (şehir/gpu/ekran değiştir) → şarkı/parça/müzik
    # bağlamı ZORUNLU. "müzi" kökü "müzik"/"müziği" çekimlerini yakalar.
    # ğ→g TOLERANSI: kullanıcı sık sık "degiştir" (düz g) yazıyor; "değiştir" (ğ)
    # bunun içinde substring DEĞİL. Bu yüzden her iki yazımı da kabul ediyoruz.
    _degistir_var = "değiştir" in metin or "degiştir" in metin
    _sarki_degistir = (
        (_degistir_var and any(k in metin for k in ("şarkı", "parça", "müzi")))
        or "başka şarkı" in metin or "başka parça" in metin or "başka bir şarkı" in metin
        or "şarkı atla" in metin or "şarkıyı atla" in metin or "parça atla" in metin
    )
    if ("sonraki şarkı" in metin or "sonraki parça" in metin
            or "sonraki" in metin or metin.strip() in ("geç", "atla")
            or _sarki_degistir):
        if "önceki" not in metin:
            sonraki_sarki()
            _izle("sonraki_sarki")
            return False

    # ----- SPO-6: Önceki şarkı -----
    if ("önceki şarkı" in metin or "önceki parça" in metin
            or "önceki" in metin or "geri git" in metin):
        onceki_sarki()
        _izle("onceki_sarki")
        return False

    # ----- SPO-7: Ses seviyesi (Spotify bağlamı) -----
    # "müziğin sesini/spotify sesi" → Spotify ses_ayarla().
    # Bağlamsız "sesi aç/kıs" → Tier 1 _sistem_donanim_yonlendir() (sistem sesi) işler.
    if ("sesi" in metin
            and any(k in metin for k in ("müzik", "spotify", "şarkı"))
            and (
                any(k in metin for k in ("aç", "kıs", "yükselt", "azalt", "düşür", "artır"))
                or any(c.isdigit() for c in metin)
            )):
        ses_ayarla(metin)
        _izle("muzik_ses")
        return False

    # ----- SPO-8: Karıştır -----
    if "karıştır" in metin or "karışık" in metin:
        karistir_ac_kapa()
        _izle("karistir")
        return False

    # ----- SPO-9: Tekrar modu -----
    if "tekrar modu" in metin or "tekrarla" in metin:
        tekrar_modu_degistir()
        _izle("tekrar_modu")
        return False

    # ----- SPO-10: Şarkı beğen -----
    if "beğen" in metin or "bunu beğendim" in metin:
        sarki_begen()
        _izle("sarki_begen")
        return False

    # ----- SPO-11: Genel çalma → calma_yonet() -----
    # calma_yonet() içerik analizi yapar: şarkı adı varsa sarki_calar(),
    # "devam et" ise muzik_devam_et(), genel müzik isteğiyse beğenilenleri çalar.
    kelimeler  = metin.split()
    ilk_kelime = kelimeler[0] if kelimeler else ""
    # Genel müzik kalıpları — spotify_kontrol._GENEL_MUZIK_KALIPLARI ile hizalı.
    # "müzik aç", "müzik koy", "bir şeyler çal", "bana müzik" gibi formlar da
    # ARTIK Tier 1'de yakalanır (eskiden eksikti → LLM'e düşüp "hangi şarkı?" diyordu).
    if (
        ilk_kelime in _SPOTI_CALI_ILKLERI
        or "müzik çal" in metin
        or "müzik başlat" in metin
        or "müzik oynat" in metin
        or "müzik aç" in metin
        or "müzik koy" in metin
        or "biraz müzik" in metin
        or "bir şeyler çal" in metin
        or "bana müzik" in metin
        or "devam et" in metin
    ):
        calma_yonet(metin)
        _izle("muzik_cal")
        return False

    # ── TIER 1 — SİSTEM / DONANIM KOMUTLARI (DETERMİNİSTİK, LLM'DEN ÖNCE) ─────
    # Tüm donanım ve kritik sistem komutları burada KESİN kalıp eşleştirmeyle
    # işlenir: fuzzy YOK, olasılık YOK, anında sonuç. "Kod birincil, LLM yedek"
    # prensibi gereği bu blok LLM beyninden ÖNCE çalışır.
    #
    # ÇAKIŞMA KORUMASI (fonksiyon içindeki zorunlu kelime şartlarıyla sağlanır):
    #   • wifi  ↔ bluetooth : WiFi dalı bluetooth kelimesi varsa tetiklenmez
    #   • parlaklık ↔ klavye: parlaklık dalı "klavye" varsa tetiklenmez
    #   • sistem sesi ↔ Spotify sesi: sistem sesi dalı müzik/şarkı/spotify varsa
    #     tetiklenmez; ayrıca Spotify SES kontrolü (SPO-7) bu satırdan ÖNCE çalışır
    #
    # ÇIKIŞ KORUMASI: "wifi kapat" / "bluetooth kapat" / "oturumu kapat" gibi
    # "kapat" içeren komutlar, program çıkışı kontrolünden (_cikis_mi) ÖNCE
    # burada yakalanır — yanlışlıkla programı kapatmazlar.
    if _sistem_donanim_yonlendir(metin, mod):
        return False

    # ── FUZZY EŞLEŞTİRME (yedek güvenlik ağı) ───────────────────────────────
    # Tam eşleşme başarısız olduysa buraya düşülür.
    # Whisper "duraklat" → "durak tat", "sesi kıs" → "ses kıs" gibi üretebilir.
    #
    # KAPSAM DIŞI (kasıtlı — yanlış pozitif riski):
    #   "bilgisayarı kapat"  → yıkıcı eylem
    #   "çal <şarkı>"        → içerik çıkarmayı bozar
    #   "not al <metin>"     → içerik çıkarmayı bozar
    if _fuzzy_komut_isle(metin, mod):
        return False

    # ── ÇIKIŞ KONTROLÜ (en sona) ─────────────────────────────────────────────
    # Hiçbir hızlı komut eşleşmedi. Şimdi çıkış ifadesi olup olmadığına bakabiliriz.
    # _CIKIS_ISTISNALAR sayesinde "wifi kapat", "bt kapat" vb. bu noktada çıkış
    # olarak yorumlanmaz — LLM/yedek katmana geçer.
    if _cikis_mi(metin):
        konus("Görüşmek üzere!")
        return True  # main.py döngüyü bu True ile sonlandırır

    # ── TIER 2 — LLM BEYNİ (YALNIZCA YEDEK) ──────────────────────────────────
    # Buraya GELİNDİYSE Tier 1'in (genel + Spotify + sistem/donanım + fuzzy)
    # hiçbir kalıbı eşleşmemiş demektir. LLM yalnızca İKİ iş için kullanılır:
    #   (1) kalıba uymayan serbest/dolaylı ifadeler (ör. "ortamı biraz canlandır")
    #   (2) sohbet (ör. "nasılsın")
    # LLM bir komuta yönlendirse bile sayılı komutlarda sayı orijinal metinden
    # regex ile çıkarılır (aşağıdaki SAYI GÜVENLİĞİ bloğuna bak).
    # LLM_KULLAN=False veya Ollama kapalı → Tier 1 zaten çoğu şeyi karşıladı;
    # eşleşmeyen için "anlayamadım" denir (çökme yok).
    _llm_basarisiz = False

    if LLM_KULLAN:
        try:
            from beyin import beyin_dusun
            # Hafıza bağlamı: kullanıcının adı, şehri, tercihleri
            _llm_sonuc = beyin_dusun(metin, kullanici_ozeti())
            if _llm_sonuc:
                _tur = _llm_sonuc.get("tur", "sohbet")

                if _tur == "baglanti_hatasi":
                    # Beyin kapalı; "Beynim şu an kapalı..." zaten seslendirildi.
                    # Sistem/donanım komutu olabilir → çevrimdışı yedekle dene.
                    _llm_basarisiz = True

                elif _tur == "komut":
                    _komut_adi = _llm_sonuc.get("komut_adi", "")
                    _parametre = _llm_sonuc.get("parametre", "")
                    if _komut_adi:
                        _disp = _llm_dispatch_al()
                        if _komut_adi in _disp:
                            # SAYI GÜVENLİĞİ: Küçük LLM sayıları güvenilir çıkaramaz
                            # (örn. "parlaklığı 50 yap" → 80). Parlaklık/ses gibi sayılı
                            # komutlarda LLM'in parametresine GÜVENME; fonksiyonu ORİJİNAL
                            # metinle çağır — kendi regex'iyle (re.search r"\d+") doğru
                            # sayıyı çıkarsın. (Bu komutlar zaten çoğunlukla Tier 1'de
                            # yakalanır; bu yalnızca serbest ifade için ek güvenlik ağıdır.)
                            if _komut_adi == "parlaklik":
                                parlaklik_ayarla(metin)
                            elif _komut_adi == "sistem_sesi":
                                sistem_sesi_ayarla(metin)
                            else:
                                _disp[_komut_adi](_parametre, mod)
                            _izle(f"llm_{_komut_adi}")
                            return False
                    # Bilinmeyen komut_adi veya cevap alanı varsa seslendir
                    _cevap = _llm_sonuc.get("cevap", "")
                    if _cevap:
                        konus(_cevap)
                        return False

                else:  # sohbet
                    _cevap = _llm_sonuc.get("cevap", "")
                    if _cevap:
                        konus(_cevap)
                        return False
        except Exception:
            _llm_basarisiz = True  # Beklenmedik LLM hatası → yedek dene
    else:
        # LLM devre dışı — sistem komutları için çevrimdışı yedek her zaman çalışır
        _llm_basarisiz = True

    # ----- Tanınmayan komut -----
    # Tier 1 (deterministik sistem/donanım + genel + Spotify + fuzzy) ve
    # Tier 2 (LLM beyin) hiçbir şey eşleştiremedi.
    # NOT: Sistem/donanım komutları artık Tier 1'de (LLM'den ÖNCE) işlendiği için
    # burada ayrı bir "sistem yedeği" çağrısına GEREK YOK — eskiden buradaki
    # _sistem_komut_yedek() çağrısı bu işi yapıyordu, şimdi yukarı taşındı.
    # _llm_basarisiz bayrağı (LLM kapalı/erişilemez) artık yalnızca bilgi amaçlı:
    # LLM çevrimdışıyken de Tier 1 zaten çalıştığından donanım komutları karşılanır.
    konus("Bu komutu henüz öğrenmedim ama yakında öğreneceğim.")
    return False
