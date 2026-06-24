# aura_hid.py — ASUS Aura klavye aydınlatması USB HID erişim katmanı
#
# NEDEN ACPI DEĞİL HID?
#   Bu makine ROG tipi (GPU MUX kodu 0x00090016 = GPUMuxROG). ROG klavye
#   aydınlatması ACPI (0x00050021) üzerinden DEĞİL, USB HID "Aura" protokolü
#   ile kontrol edilir. ACPI yöntemi yalnızca bazı TUF modellerde çalışır;
#   bu makinede klavye için çalışmadı. Fan ve GPU ACPI'de KALIR (onlar çalışıyor).
#
# G-Helper (github.com/seerge/g-helper, app/USB/AsusHid.cs + Aura.cs) ile AYNI yöntem:
#   - Cihaz   : Vendor 0x0B05 + MAIN_AURA_PIDS'ten bir Product ID
#   - Yazma   : HID FEATURE REPORT (send_feature_report), output report DEĞİL.
#               Tampon, cihazın feature report uzunluğuna (genelde 64) sıfırla doldurulur.
#   - Parlaklık: [0x5A, 0xBA, 0xC5, 0xC4, seviye]   (INPUT_ID raporu, seviye 0-3)
#   - Renk/efekt: [0x5D, 0xB3, zone, mod, R, G, B, hız, yön, ...]  (AURA_ID raporu)
#                 ardından APPLY [0x5D,0xB4] ve SET [0x5D,0xB5,0,0,0] commit paketleri
#
# NOTLAR:
#   - G-Helper KAPALI olmalı (aynı HID cihazına eşzamanlı erişim çakışabilir).
#   - hidapi gerekli: pip install hidapi
#   - HID gönderimi teknik olarak başarılı olsa BİLE ışığın fiziksel değişimi
#     garanti değildir; çağıran taraf "kesin yapıldı" dememeli, kullanıcı görmeli.

# hidapi'yi GÜVENLİ import et: kurulu değilse modül yine de yüklenebilsin,
# fonksiyonlar dürüstçe "hidapi yok" desin (sistem_ayarlari import'u çökmesin).
try:
    import hid
    _HID_VAR = True
    _HID_HATA = ""
except Exception as _e:           # ImportError veya DLL hatası
    hid = None
    _HID_VAR = False
    _HID_HATA = str(_e)


# ── SABİTLER (G-Helper AsusHid.cs / Aura.cs kaynağından doğrulandı) ───────────
ASUS_VENDOR = 0x0B05
INPUT_ID    = 0x5A   # parlaklık raporu başlığı
AURA_ID     = 0x5D   # renk/efekt raporu başlığı

# Klavye Aura cihazlarının Product ID'leri (REAR_LIGHT 0x18c6 HARİÇ — o arka ışık).
MAIN_AURA_PIDS = {
    0x1a30, 0x1854, 0x1869, 0x1866, 0x19b6, 0x1822, 0x1837, 0x184a, 0x183d,
    0x8502, 0x1807, 0x17e0, 0x1abe, 0x1b4c, 0x1b6e, 0x1b2c, 0x8854, 0x1ce7,
    0x1bf2,
}

# AuraMode enum (Aura.cs) — Türkçe komutlarda kullanılan alt küme + tamamı bilgi için.
MOD_STATIC     = 0    # sabit renk
MOD_BREATHE    = 1    # nefes
MOD_COLORCYCLE = 2    # renk döngüsü
MOD_RAINBOW    = 3    # gökkuşağı
MOD_STAR       = 4
MOD_RAIN       = 5
MOD_STROBE     = 10   # strobe

# Feature report taban uzunluğu. ASUS Aura klavyelerinde neredeyse her zaman 64.
# Reddedilirse 65 de denenir (hidapi'de report ID + 64 veri = 65 durumu).
_RAPOR_UZUNLUK = 64


# ── DÜŞÜK SEVİYELİ HID GÖNDERİMİ ──────────────────────────────────────────────

def _aday_cihazlar() -> list:
    # Vendor 0x0B05 + MAIN_AURA_PIDS eşleşen TÜM HID arayüzlerini döndürür.
    # hidapi TryGetReport sunmadığından doğru arayüzü kesin seçemeyiz; bu yüzden
    # G-Helper'ın FindDevices foreach davranışını taklit edip TÜM adaylara yazarız
    # (doğru arayüz uygular, yanlışlar hatasız reddeder).
    adaylar = []
    try:
        for d in hid.enumerate(ASUS_VENDOR, 0):
            if d.get("product_id") in MAIN_AURA_PIDS:
                adaylar.append(d)
    except Exception as e:
        print(f"[AURA] hid.enumerate hatası: {e}")
    return adaylar


def _tek_paket_gonder(dev, paket: list) -> bool:
    # Tek bir feature report gönderir. Önce 64, başarısızsa 65 byte uzunlukla dener.
    # paket: report_id ile başlayan int listesi (örn. [0x5A, 0xBA, ...]).
    for uzunluk in (_RAPOR_UZUNLUK, _RAPOR_UZUNLUK + 1):   # 64, sonra 65
        if len(paket) > uzunluk:
            continue
        tampon = bytes(list(paket) + [0] * (uzunluk - len(paket)))
        try:
            sonuc = dev.send_feature_report(tampon)
            # hidapi: yazılan byte sayısı (>=0) başarı, -1 başarısızlık
            if sonuc is not None and sonuc >= 0:
                return True
        except Exception as e:
            # Bu uzunluk reddedildi; diğer uzunluğu dene
            _SON_HATA[0] = str(e)
    return False


# Son HID hatasını teşhis için sakla (tek elemanlı liste = mutable referans)
_SON_HATA = [""]


def _paketleri_gonder(paketler: list) -> bool:
    # Verilen paket listesini TÜM aday Aura arayüzlerine, her arayüzde TEK açılışta
    # sırayla yazar (renk için msg+APPLY+SET aynı oturumda gitmeli).
    # En az bir arayüze en az bir paket başarıyla gittiyse True döner.
    if not _HID_VAR:
        print(f"[AURA] hidapi yüklü değil ({_HID_HATA}). Kur: pip install hidapi")
        return False

    adaylar = _aday_cihazlar()
    if not adaylar:
        print("[AURA] ASUS Aura HID cihazı bulunamadı (vendor 0x0B05 + bilinen PID).")
        return False

    genel_basari = False
    for d in adaylar:
        dev = hid.device()
        try:
            dev.open_path(d["path"])
        except Exception as e:
            print(f"[AURA] PID={d.get('product_id'):#06x} açılamadı: {e}")
            continue
        try:
            arayuz_basari = False
            for paket in paketler:
                if _tek_paket_gonder(dev, paket):
                    arayuz_basari = True
                    genel_basari = True
            if arayuz_basari:
                print(
                    f"[AURA] yazıldı → PID={d.get('product_id'):#06x} "
                    f"arayüz={d.get('interface_number')} "
                    f"usage_page={d.get('usage_page')}"
                )
        finally:
            try:
                dev.close()
            except Exception:
                pass

    if not genel_basari and _SON_HATA[0]:
        print(f"[AURA] Hiçbir arayüz kabul etmedi. Son hata: {_SON_HATA[0]}")
    return genel_basari


# ── ÜST SEVİYE API ────────────────────────────────────────────────────────────

def aura_parlaklik(seviye: int) -> bool:
    # Klavye parlaklığını ayarlar. seviye: 0=kapalı, 1=düşük, 2=orta, 3=yüksek.
    # G-Helper: [INPUT_ID, 0xBA, 0xC5, 0xC4, seviye]
    seviye = max(0, min(3, int(seviye)))
    paket = [INPUT_ID, 0xBA, 0xC5, 0xC4, seviye]
    return _paketleri_gonder([paket])


def aura_renk(mod: int, r: int, g: int, b: int, hiz: int = 0) -> bool:
    # Klavye rengini/efektini ayarlar.
    #   mod : AuraMode (MOD_STATIC, MOD_BREATHE, MOD_RAINBOW, ...)
    #   r,g,b: 0-255 renk (gökkuşağı/renk döngüsü modlarında firmware rengi yok sayar)
    #   hiz : efekt hızı (0-2 tipik; sabit renk için önemsiz)
    # G-Helper AuraMessage (17 byte) + APPLY + SET commit paketleri.
    msg = [0] * 17
    msg[0] = AURA_ID        # 0x5D
    msg[1] = 0xB3           # komut
    msg[2] = 0x00           # zone
    msg[3] = mod & 0xFF
    msg[4] = r & 0xFF
    msg[5] = g & 0xFF
    msg[6] = b & 0xFF
    msg[7] = hiz & 0xFF
    msg[8] = 0x00           # yön
    # msg[9] random bayrağı, msg[10..12] ikincil renk — 0 bırakılır

    apply_paket = [AURA_ID, 0xB4]                 # APPLY
    set_paket   = [AURA_ID, 0xB5, 0x00, 0x00, 0x00]  # SET (kaydet)

    return _paketleri_gonder([msg, apply_paket, set_paket])
