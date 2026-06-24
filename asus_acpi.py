# asus_acpi.py — ASUS ATKACPI doğrudan erişim katmanı
#
# G-Helper (github.com/seerge/g-helper, AsusACPI.cs) aynı yöntemi kullanır:
#   - Aygıt yolu : \\.\ATKACPI  (asci.sys — ASUS System Control Interface sürücüsü)
#   - Protokol   : DeviceIoControl(0x0022240C) → DSTS(okuma) / DEVS(yazma)
#   - Tampon     : method_id(4) + args_uzunluğu(4) + device_id(4) + değer(4) = 16 bayt
#
# WMI yerine bu yöntemin tercih sebebi:
#   AsusAtkWmi_WMNB WMI sınıfı bazı modellerde eksik/yanlış eşlenmiş.
#   ATKACPI aygıtı ise System Control Interface ile her zaman gelir ve
#   G-Helper'ın sorunsuz çalıştığı kanıtlanmış arayüzdür.
#
# Yönetici (Administrator) yetkisi gereklidir.
# G-Helper açıkken: FILE_SHARE_READ|WRITE ile aygıt paylaşımlı açılır,
# çakışma riski düşük. Belirsiz sonuç alınırsa G-Helper'ı kapat ve tekrar dene.

import ctypes
import ctypes.wintypes
import struct

# ── Kernel32 dönüş tipi tanımları ────────────────────────────────────────────
_k32 = ctypes.windll.kernel32
_k32.CreateFileW.restype   = ctypes.c_void_p   # HANDLE → int (veya None=NULL)
_k32.CloseHandle.restype   = ctypes.wintypes.BOOL
_k32.DeviceIoControl.restype = ctypes.wintypes.BOOL
_k32.GetLastError.restype  = ctypes.wintypes.DWORD

# INVALID_HANDLE_VALUE = (HANDLE)(-1) — CreateFile'ın başarısız dönüş değeri
# ctypes c_void_p(-1).value: 64-bit sistemde 18446744073709551615
_GECERSIZ_HANDLE = ctypes.c_void_p(-1).value

# ── IOCTL ve method ID sabitleri ─────────────────────────────────────────────
# CTL_CODE(DeviceType=0x22, Function=0x903, Method=BUFFERED, Access=ANY) = 0x0022240C
# G-Helper AsusACPI.cs'ten doğrulandı.
_IOCTL   = 0x0022240C

# Method ID = ASCII adı little-endian uint32 olarak paketlenmiş.
# struct.pack("<I", 0x53545344) → b"DSTS"  (D=0x44 S=0x53 T=0x54 S=0x53)
# struct.pack("<I", 0x53564544) → b"DEVS"  (D=0x44 E=0x45 V=0x56 S=0x53)
_DSTS_ID = 0x53545344   # Device STatuS — okuma
_DEVS_ID = 0x53564544   # DEVice Set    — yazma

# ── Aygıt ID sabitleri (G-Helper AsusACPI.cs kaynağından doğrulandı) ─────────

# Klavye arka aydınlatması — TUF_KB_BRIGHTNESS
# DEVS değerleri: 0=kapalı, 1=düşük, 2=orta, 3=yüksek
KBD_BACKLIGHT = 0x00050021

# Fan/termal profil — PerformanceMode (THROTTLE_THERMAL_POLICY)
# DEVS değerleri: 0=dengeli (Balanced), 1=turbo, 2=sessiz (Silent)
FAN_MODE = 0x00120075

# GPU MUX modu (ROG/TUF) — GPUMuxROG
# DEVS değerleri: 0=Eco (sadece iGPU), 1=Standart/Optimus, 2=Ultimate (sadece dGPU)
# DİKKAT: Bu değişiklik yeniden başlatma gerektirir.
GPU_MUX = 0x00090016


# ── Düşük seviyeli ATKACPI erişim fonksiyonları ───────────────────────────────

def _atk_ac() -> int:
    """
    \\.\ATKACPI çekirdek aygıtını açar, handle (int) döndürür.

    Başarısızlıkta anlamlı istisna fırlatır — sessiz başarısız olmaz.
    Hata kodu 5  → yönetici yetkisi gerekmektedir.
    Hata kodu 2  → ASUS System Control Interface sürücüsü bulunamadı.
    Hata kodu 32 → aygıt meşgul (genellikle G-Helper ile çakışma değil;
                   driver iç kilitlemesi. Nadir — programı yeniden başlat).
    """
    h = _k32.CreateFileW(
        r"\\.\ATKACPI",
        0xC0000000,   # GENERIC_READ | GENERIC_WRITE
        3,            # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        3,            # OPEN_EXISTING
        0,
        None,
    )
    if h is None or h == _GECERSIZ_HANDLE:
        kod = _k32.GetLastError()
        if kod == 5:
            raise PermissionError(
                "ATKACPI: Erişim reddedildi (hata 5). "
                "Friday'i yönetici olarak çalıştır."
            )
        if kod == 2:
            raise FileNotFoundError(
                "ATKACPI: Aygıt bulunamadı (hata 2). "
                "ASUS System Control Interface sürücüsü kurulu olmalı."
            )
        raise OSError(f"ATKACPI: CreateFile başarısız — GetLastError={kod}")
    return h


def acpi_oku(device_id: int) -> int:
    """
    DSTS (Device STatuS) çağrısıyla aygıt durumunu okur. HAM int32 döndürür.

    Tampon yapısı — 16 bayt, tümü little-endian:
      Bayt [0-3]   Yöntem = 0x53545344  ("DSTS")
      Bayt [4-7]   Args uzunluğu = 8    (2 × int32 = 8 bayt)
      Bayt [8-11]  Aygıt ID             (okumak istediğimiz kayıt)
      Bayt [12-15] Param = 0            (DSTS için sabit sıfır)

    DSTS HAM dönüş formatı (ASUS):
      bit 16 (0x00010000) = "destekleniyor/var" bayrağı
      alt baytlar         = gerçek değer
    G-Helper bu değeri `raw - 65536` ile yorumlar (0x10000 bayrağını çıkarır).
    Gerçek değeri almak için acpi_deger() yardımcısını kullan.

    DİKKAT: Bazı aygıtlarda (özellikle fan/performans modu ve klavye ışığı)
    DSTS geri okuması yazılan değeri YANSITMAZ — G-Helper bile bu modları
    yazıp geri okumaya güvenmez, durumu yazılımda takip eder. Bu yüzden
    geri okumayı BAŞARI KRİTERİ değil, yalnızca bilgi amaçlı kullan.

    Hata durumunda -1 döndürür; istisna fırlatmaz.
    """
    girdi = struct.pack("<IIII", _DSTS_ID, 8, device_id, 0)
    cikti = ctypes.create_string_buffer(16)
    donen = ctypes.wintypes.DWORD(0)
    h = None
    try:
        h = _atk_ac()
        tamam = _k32.DeviceIoControl(
            h, _IOCTL,
            girdi, len(girdi),
            cikti, 16,
            ctypes.byref(donen), None,
        )
        if not tamam:
            kod = _k32.GetLastError()
            print(f"[ATKACPI] DSTS({device_id:#010x}) DeviceIoControl başarısız: hata={kod}")
            return -1
        return struct.unpack_from("<i", cikti, 0)[0]
    except (PermissionError, FileNotFoundError, OSError) as e:
        print(f"[ATKACPI] acpi_oku({device_id:#010x}): {e}")
        return -1
    finally:
        if h is not None and h != _GECERSIZ_HANDLE:
            _k32.CloseHandle(h)


def acpi_deger(ham: int) -> int:
    """
    DSTS ham dönüş değerinden gerçek ayar değerini çıkarır.

    ASUS DSTS formatında bit 16 (0x00010000) "destekleniyor" bayrağıdır,
    gerçek değer alt baytlardadır. Alt baytı maskeleyerek (& 0xFF) değeri alırız.
    (G-Helper `raw - 65536` yapar; alt bayt maskeleme eşdeğer ve daha güvenlidir.)

    ham < 0 (okuma hatası) ise -1 döndürür.
    """
    if ham < 0:
        return -1
    return ham & 0xFF


def acpi_yaz(device_id: int, deger: int) -> bool:
    """
    DEVS (DEVice Set) çağrısıyla aygıta değer yazar.

    Tampon yapısı — 16 bayt, tümü little-endian:
      Bayt [0-3]   Yöntem = 0x53564544  ("DEVS")
      Bayt [4-7]   Args uzunluğu = 8    (2 × int32 = 8 bayt)
      Bayt [8-11]  Aygıt ID             (ayarlamak istediğimiz kayıt)
      Bayt [12-15] Değer                (yeni ayar — signed int32)

    BAŞARI ÖLÇÜTÜ: DeviceIoControl çağrısının kendisi başarılı olması.
    ASUS DEVS'in döndürdüğü değer aygıttan aygıta DEĞİŞİR (klavye 0, fan 1
    dönebilir) ve güvenilir bir başarı göstergesi DEĞİLDİR — G-Helper da bu
    değeri başarı kontrolü için kullanmaz, IOCTL geçtiyse komutu kabul edilmiş
    sayar. Biz de aynısını yapıyoruz: ham yanıt yalnızca teşhis için yazdırılır.

    IOCTL başarılıysa True (komut donanıma ulaştı), Win32 hatası varsa False.
    """
    # Değer alanı signed int32 ("i") — negatif değerler bazı kayıtlarda geçerli
    girdi = struct.pack("<IIIi", _DEVS_ID, 8, device_id, deger)
    cikti = ctypes.create_string_buffer(16)
    donen = ctypes.wintypes.DWORD(0)
    h = None
    try:
        h = _atk_ac()
        tamam = _k32.DeviceIoControl(
            h, _IOCTL,
            girdi, len(girdi),
            cikti, 16,
            ctypes.byref(donen), None,
        )
        if not tamam:
            kod = _k32.GetLastError()
            print(
                f"[ATKACPI] DEVS({device_id:#010x}, {deger}) "
                f"DeviceIoControl başarısız: hata={kod}"
            )
            if kod == 5:
                print("[ATKACPI] İpucu: Programı yönetici olarak çalıştır.")
            return False
        sonuc = struct.unpack_from("<i", cikti, 0)[0]
        # Ham yanıt yalnızca teşhis amaçlı — başarı ölçütü DEĞİL (yukarıdaki nota bak)
        print(f"[ATKACPI] DEVS({device_id:#010x}, {deger}) → ham_yanıt={sonuc} (IOCTL OK)")
        return True
    except (PermissionError, FileNotFoundError, OSError) as e:
        print(f"[ATKACPI] acpi_yaz({device_id:#010x}, {deger}): {e}")
        return False
    finally:
        if h is not None and h != _GECERSIZ_HANDLE:
            _k32.CloseHandle(h)
