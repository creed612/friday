# Bu dosya Friday'in sesli sistem kontrol merkezi özelliklerini içerir.
# Windows 11 (ASUS laptop, RTX 4050) üzerinde çalışır.
# Armoury Crate benzeri donanım kontrolü + temel Windows ayarları.
#
# Gerekli paketler: pycaw, comtypes, screen-brightness-control, psutil
# Kur: pip install pycaw comtypes screen-brightness-control psutil
#
# HATA YÖNETİMİ: Tüm fonksiyonlar try/except ile korunmuştur.
# Program asla çökmez; başarısız işlemler konus() ile bildirilir.

import ctypes
import os
import re
import subprocess
import winreg
from pathlib import Path

import psutil
import screen_brightness_control as sbc
from comtypes import CLSCTX_ALL
from ctypes import POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from ses import konus, komut_dinle, yaz
from config import G_HELPER_YOLU
# Fan ve GPU ACPI'de KALIR (çalışıyor). KBD_BACKLIGHT artık klavye için KULLANILMIYOR:
# bu ROG makinede klavye USB HID Aura ile kontrol edilir (aura_hid), ACPI ile değil.
from asus_acpi import acpi_yaz, acpi_oku, acpi_deger, FAN_MODE, GPU_MUX
import aura_hid


# ── UYGULAMA SÖZLÜĞÜ ────────────────────────────────────────────────────────
# Sesli komuttaki uygulama adı → kapatılacak .exe eşleşmeleri
_UYGULAMA_SOZLUGU = {
    "chrome":           "chrome.exe",
    "chromium":         "chromium.exe",
    "firefox":          "firefox.exe",
    "edge":             "msedge.exe",
    "spotify":          "Spotify.exe",
    "discord":          "Discord.exe",
    "notepad":          "notepad.exe",
    "not defteri":      "notepad.exe",
    "word":             "WINWORD.EXE",
    "excel":            "EXCEL.EXE",
    "powerpoint":       "POWERPNT.EXE",
    "outlook":          "OUTLOOK.EXE",
    "teams":            "Teams.exe",
    "zoom":             "Zoom.exe",
    "vlc":              "vlc.exe",
    "steam":            "steam.exe",
    "armoury":          "ArmouryCrate.UserSessionHelper.exe",
    "armoury crate":    "ArmouryCrate.UserSessionHelper.exe",
    "explorer":         "explorer.exe",
    "görev yöneticisi": "Taskmgr.exe",
    "task manager":     "Taskmgr.exe",
    "paint":            "mspaint.exe",
    "obs":              "obs64.exe",
    "vscode":           "Code.exe",
    "visual studio":    "devenv.exe",
}


# _BT_PNP_SABLONU sabiti KALDIRILDI.
# Eski raw string (r"""...""") + .replace("{EYLEM}", ...) yaklaşımında {{}} PowerShell'e
# literal {{ }} olarak gidiyordu — scriptblock syntax'ı bozuluyordu.
# Yeni yaklaşım: f-string inline _bluetooth_pnp_calistir() içinde (aşağıya bak).
# Teşhis çıktısı: Intel(R) Wireless Bluetooth(R) → InstanceId: USB\VID_8087&PID_0033\...
# Filtre InstanceId -like 'USB\*' kullanarak sadece fiziksel adaptörü hedefler.


# ── DEVMODE YAPISI (ekran tazeleme hızı için) ─────────────────────────────────
# Windows EnumDisplaySettings/ChangeDisplaySettings API'nin gerektirdiği C yapısı.
class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName",         ctypes.c_wchar * 32),
        ("dmSpecVersion",        ctypes.c_ushort),
        ("dmDriverVersion",      ctypes.c_ushort),
        ("dmSize",               ctypes.c_ushort),
        ("dmDriverExtra",        ctypes.c_ushort),
        ("dmFields",             ctypes.c_ulong),
        ("dmPositionX",          ctypes.c_long),
        ("dmPositionY",          ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor",              ctypes.c_short),
        ("dmDuplex",             ctypes.c_short),
        ("dmYResolution",        ctypes.c_short),
        ("dmTTOption",           ctypes.c_short),
        ("dmCollate",            ctypes.c_short),
        ("dmFormName",           ctypes.c_wchar * 32),
        ("dmLogPixels",          ctypes.c_ushort),
        ("dmBitsPerPel",         ctypes.c_ulong),
        ("dmPelsWidth",          ctypes.c_ulong),
        ("dmPelsHeight",         ctypes.c_ulong),
        ("dmDisplayFlags",       ctypes.c_ulong),
        ("dmDisplayFrequency",   ctypes.c_ulong),
        ("dmICMMethod",          ctypes.c_ulong),
        ("dmICMIntent",          ctypes.c_ulong),
        ("dmMediaType",          ctypes.c_ulong),
        ("dmDitherType",         ctypes.c_ulong),
        ("dmReserved1",          ctypes.c_ulong),
        ("dmReserved2",          ctypes.c_ulong),
        ("dmPanningWidth",       ctypes.c_ulong),
        ("dmPanningHeight",      ctypes.c_ulong),
    ]


# ── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────

def _ses_arabirimi():
    # pycaw aracılığıyla Windows ses uç noktası arabirimini döndürür.
    # pycaw SÜRÜM FARKI: Yeni sürümlerde GetSpeakers() artık ham IMMDevice değil,
    # bir AudioDevice sarmalayıcısı döndürür (Activate metodu YOK → eski kod
    # 'AudioDevice object has no attribute Activate' hatası veriyordu).
    # Bu yüzden üç yola da hazırız:
    cihazlar = AudioUtilities.GetSpeakers()

    # YOL 1 (yeni pycaw): hazır .EndpointVolume özelliği doğrudan
    # POINTER(IAudioEndpointVolume) verir — Activate gerekmez.
    ev = getattr(cihazlar, "EndpointVolume", None)
    if ev is not None:
        return ev

    # YOL 2 (eski pycaw): GetSpeakers() doğrudan IMMDevice döndürür → Activate + cast
    if hasattr(cihazlar, "Activate"):
        arabirim = cihazlar.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(arabirim, POINTER(IAudioEndpointVolume))

    # YOL 3 (ara durum): AudioDevice._dev (asıl IMMDevice) üzerinden Activate
    dev = getattr(cihazlar, "_dev", None)
    if dev is not None and hasattr(dev, "Activate"):
        arabirim = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(arabirim, POINTER(IAudioEndpointVolume))

    raise RuntimeError("pycaw ses arabirimi alınamadı (bilinmeyen sürüm).")


def _kablosuz_arayuz_adi() -> str | None:
    # "netsh interface show interface" çıktısını ayrıştırıp
    # kablosuz ağ arayüzünün gerçek adını döndürür.
    try:
        sonuc = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True, text=True,
            encoding="cp857", errors="ignore",   # Türkçe Windows konsolunu destekle
        )
        for satir in sonuc.stdout.splitlines():
            alt = satir.lower()
            if any(k in alt for k in ("wireless", "wi-fi", "wifi", "kablosuz", "wlan")):
                # Satır formatı: "Yönetici Durumu  Bağlantı Durumu  Tür  Ad"
                # Sütunlar boşlukla ayrılmış; son kısım arayüz adıdır.
                parcalar = satir.split()
                if len(parcalar) >= 4:
                    return " ".join(parcalar[3:])
    except Exception:
        pass
    return None


def _g_helper_var_mi() -> str | None:
    # G-Helper çalıştırılabilir dosyasının yolunu döndürür; yoksa None.
    # Önce config.py'deki G_HELPER_YOLU'na bakar (kullanıcı tanımlı).
    # NOT: G-Helper'ın CLI desteği yoktur; bu yol yalnızca WMI başarısız
    #       olduğunda son çare olarak G-Helper penceresini öne getirmek için
    #       kullanılır (tek-instance uygulama olduğu için ikinci çalıştırma
    #       mevcut pencereyi öne getirir).
    if G_HELPER_YOLU and Path(G_HELPER_YOLU).exists():
        return G_HELPER_YOLU
    # config yolu bulunamazsa bilinen varsayılan konumları dene
    olasi_yollar = [
        Path(os.environ.get("APPDATA", "")) / "G-Helper" / "GHelper.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "G-Helper" / "GHelper.exe",
        Path("C:/Program Files/G-Helper/GHelper.exe"),
        Path("C:/Program Files (x86)/G-Helper/GHelper.exe"),
    ]
    for yol in olasi_yollar:
        if yol.exists():
            return str(yol)
    # Çalışan süreçlerde G-Helper ara
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            ad = (proc.info.get("name") or "").lower()
            if "ghelper" in ad:
                return proc.info.get("exe") or ad
    except Exception:
        pass
    return None


def _asus_wmi_komut_calistir(metod: str, parametre: int) -> bool:
    # ASUS ACPI WMI arayüzü üzerinden donanım komutu gönderir.
    # metod     : "DEVS" (set) veya "DSTS" (status)
    # parametre : ASUS WMI özellik kodu
    # Dönüş     : True başarılı, False başarısız/mevcut değil
    ps_script = f"""
try {{
    $wmi = Get-WmiObject -Namespace "root\\WMI" -Class "AsusAtkWmi_WMNB" -ErrorAction Stop
    $sonuc = $wmi.{metod}(0x{parametre:08X})
    Write-Output "OK:$sonuc"
}} catch {{
    Write-Output "HATA"
}}
"""
    try:
        cikti = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=5,
        ).stdout
        return "OK" in cikti
    except Exception:
        return False


def _devmode_al() -> _DEVMODEW | None:
    # Mevcut birincil ekran modunu (çözünürlük, tazeleme hızı vb.) döndürür.
    dm = _DEVMODEW()
    dm.dmSize = ctypes.sizeof(_DEVMODEW)
    ENUM_CURRENT_SETTINGS = ctypes.c_uint(-1)  # -1 == 0xFFFFFFFF
    tamam = ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    return dm if tamam else None


# ── 1) SİSTEM SESİ ──────────────────────────────────────────────────────────

def sistem_sesi_ayarla(metin: str):
    # Sistem ses seviyesini ayarlar (pycaw + Windows Core Audio API).
    # Sayı varsa → 0-100 sınırında o değere ayarlar.
    # "aç/yükselt/artır" → +15; "kıs/azalt/düşür" → -15.
    # CoInitialize: pycaw COM arayüzünü ana UI thread'i dışından (örn. hatırlatıcı thread)
    # çağırırken "CoInitialize has not been called" hatasını önler.
    from comtypes import CoInitialize, CoUninitialize
    try:
        CoInitialize()
        vol  = _ses_arabirimi()
        sayi = re.search(r"\d+", metin)
        if sayi:
            hedef = max(0, min(100, int(sayi.group()))) / 100.0
        else:
            mevcut = vol.GetMasterVolumeLevelScalar()
            if any(k in metin for k in ("aç", "yükselt", "artır")):
                hedef = min(1.0, mevcut + 0.15)
            else:
                hedef = max(0.0, mevcut - 0.15)
        vol.SetMasterVolumeLevelScalar(hedef, None)
        # Geri oku — gerçekten değişip değişmediğini doğrula
        gercek = vol.GetMasterVolumeLevelScalar()
        print(f"[SES] hedef={round(hedef*100)}% → gerçek={round(gercek*100)}%")
        konus(f"Sistem sesi yüzde {round(gercek * 100)}.")
    except Exception as e:
        print(f"[SES] Hata: {e}")
        konus("Sistem sesini ayarlayamadım.")
    finally:
        try:
            CoUninitialize()
        except Exception:
            pass


def sistem_sesi_sustur():
    # Windows'un genel sesini kapatır (mute = True).
    try:
        _ses_arabirimi().SetMute(1, None)
        konus("Ses susturuldu.")
    except Exception:
        konus("Sesi susturamadım.")


def sistem_sesi_ac():
    # Susturulmuş sistem sesini açar (mute = False).
    try:
        _ses_arabirimi().SetMute(0, None)
        konus("Ses açıldı.")
    except Exception:
        konus("Sesi açamadım.")


# ── 2) EKRAN PARLAKLIĞI ──────────────────────────────────────────────────────

def _parlaklik_oku() -> int:
    # sbc.get_brightness() bazı sürümlerde liste döndürür ([55]) — ilk değeri al.
    try:
        deger = sbc.get_brightness()
        if isinstance(deger, (list, tuple)):
            return int(deger[0]) if deger else 50
        return int(deger)
    except Exception:
        return 50


def parlaklik_ayarla(metin: str):
    # Ekran parlaklığını screen_brightness_control (sbc) ile doğrudan ayarlar.
    # Sayı varsa → tam o değere; "artır/aç/yükselt" → mevcut+20; "azalt/kıs/düşür" → mevcut-20.
    # İşlem sonrası sbc.get_brightness() ile geri okuyup GERÇEK değeri bildiririz.
    #
    # ESKİ HATA: WmiSetBrightness(1, N) panelin desteklediği EN YAKIN seviyeye
    # yuvarlıyordu (ör. "50" → 80). sbc.set_brightness değeri doğrudan uyguladığı
    # için daha tutarlı; yine de geri okuma ile doğrulanır.
    sayi = re.search(r"\d+", metin)
    if sayi:
        # Metindeki ilk tam sayıyı doğrudan hedef parlaklık olarak al
        hedef = max(0, min(100, int(sayi.group())))
    else:
        mevcut = _parlaklik_oku()
        if any(k in metin for k in ("artır", "aç", "yükselt")):
            hedef = min(100, mevcut + 20)
        else:
            hedef = max(0, mevcut - 20)

    try:
        sbc.set_brightness(hedef)
        # Geri oku — panel hedefe gerçekten ulaştı mı doğrula
        gercek = _parlaklik_oku()
        print(f"[PARLAKLIK] istenen={hedef} → gerçek={gercek}")
        konus(f"Ekran parlaklığı yüzde {gercek}.")
    except Exception as e:
        print(f"[PARLAKLIK] Hata: {e}")
        konus("Ekran parlaklığını ayarlayamadım.")


# ── 3) AĞ KONTROLÜ ──────────────────────────────────────────────────────────

def wifi_ac():
    # Kablosuz ağ arayüzünü etkinleştirir (netsh). Yönetici yetkisi gerekebilir.
    # Not: simge kayboluyor → normal davranış. WiFi açılınca yeniden görünür.
    try:
        arayuz = _kablosuz_arayuz_adi()
        if not arayuz:
            konus("Kablosuz ağ arayüzü bulunamadı.")
            return
        sonuc = subprocess.run(
            ["netsh", "interface", "set", "interface", arayuz, "admin=enabled"],
            capture_output=True, text=True, encoding="cp857", errors="ignore",
        )
        if sonuc.returncode == 0:
            konus("Wi-Fi açıldı.")
        else:
            cikti = (sonuc.stdout + sonuc.stderr).lower()
            if any(k in cikti for k in ("access", "denied", "erişim", "yetki")):
                konus("Wi-Fi açmak için yönetici olarak çalıştırmam gerekiyor.")
            else:
                konus("Wi-Fi'yi açmayı denedim ama başarısız oldu.")
    except Exception:
        konus("Wi-Fi'yi açamadım.")


def wifi_kapat():
    # Kablosuz ağ arayüzünü devre dışı bırakır (netsh). Yönetici yetkisi gerekebilir.
    # Not: işlem sonrası sistem tepsisindeki Wi-Fi simgesinin kaybolması normaldir.
    try:
        arayuz = _kablosuz_arayuz_adi()
        if not arayuz:
            konus("Kablosuz ağ arayüzü bulunamadı.")
            return
        sonuc = subprocess.run(
            ["netsh", "interface", "set", "interface", arayuz, "admin=disabled"],
            capture_output=True, text=True, encoding="cp857", errors="ignore",
        )
        if sonuc.returncode == 0:
            konus("Wi-Fi kapatıldı.")
        else:
            cikti = (sonuc.stdout + sonuc.stderr).lower()
            if any(k in cikti for k in ("access", "denied", "erişim", "yetki")):
                konus("Wi-Fi kapatmak için yönetici olarak çalıştırmam gerekiyor.")
            else:
                konus("Wi-Fi'yi kapatmayı denedim ama başarısız oldu.")
    except Exception:
        konus("Wi-Fi'yi kapatamadım.")


def ucak_modu():
    # Uçak modu ayar sayfasını açar.
    # Windows API üzerinden programatik uçak modu toggle'ı güvenilir değil;
    # ayarlar sayfası her zaman çalışır.
    try:
        os.startfile("ms-settings:network-airplanemode")
        konus("Uçak modu ayarları açıldı.")
    except Exception:
        konus("Uçak modu ayarlarına ulaşamadım.")


# ── 4) BLUETOOTH ─────────────────────────────────────────────────────────────

def _bluetooth_radio_api_calistir(eylem: str) -> str:
    # Windows.Devices.Radios WinRT API ile Bluetooth radyosunu açar/kapatır.
    # "Generic failure" döndüren Disable-PnpDevice'ın yerine BIRINCIL yöntem budur.
    # eylem: "On" veya "Off" (RadioState enum adı)
    #
    # WinRT async'i PS 5.1'de GÜVENİLİR biçimde senkron beklemek için
    # [System.WindowsRuntimeSystemExtensions].AsTask() + .Wait() yöntemi kullanılır
    # (eski polling yöntemi SetStateAsync'i tam beklemiyordu — komut yarıda kalıyordu).
    #
    # Çıktı satırları:
    #   ERISIM_RED:<durum>  → kullanıcı/policy radyo erişimini reddetti
    #   BULUNAMADI          → Bluetooth radyosu yok
    #   CIHAZ:<ad>          → bulunan radyo
    #   SONUC:<durum>       → SetStateAsync sonucu (Allowed = başarılı)
    #   DURUM:<state>       → işlem sonrası radyo durumu (On/Off — bilgi)
    #   HATA:<mesaj>        → istisna
    ps_script = f"""
$ErrorActionPreference = "Stop"
try {{
    [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
    [Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
    [Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    # IAsyncOperation<T> için genel AsTask metodunu yansımayla bul
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    }})[0]

    function Await($op, $resultType) {{
        $asTask = $asTaskGeneric.MakeGenericMethod($resultType)
        $task = $asTask.Invoke($null, @($op))
        $task.Wait(10000) | Out-Null
        return $task.Result
    }}

    # 1) Radyo erişimi iste (kullanıcı/policy reddedebilir)
    $erisim = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
    if ($erisim -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) {{
        Write-Output "ERISIM_RED:$erisim"
        exit
    }}

    # 2) Tüm radyoları al, Bluetooth olanı seç
    $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
    $bt = $radios | Where-Object {{ $_.Kind -eq [Windows.Devices.Radios.RadioKind]::Bluetooth }} | Select-Object -First 1
    if (-not $bt) {{ Write-Output "BULUNAMADI"; exit }}
    Write-Output "CIHAZ:$($bt.Name)"

    # 3) Durumu değiştir ve TAMAMLANMASINI bekle
    $sonuc = Await ($bt.SetStateAsync([Windows.Devices.Radios.RadioState]::{eylem})) ([Windows.Devices.Radios.RadioAccessStatus])
    Start-Sleep -Milliseconds 400
    Write-Output "SONUC:$sonuc"
    Write-Output "DURUM:$($bt.State)"
}} catch {{
    Write-Output "HATA:$($_.Exception.Message)"
}}
"""
    try:
        cikti = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
        print(f"[BT_RADIO] {eylem} → '{cikti}'")
        return cikti
    except Exception as e:
        print(f"[BT_RADIO] {eylem} → exception: {e}")
        return f"HATA:{e}"


def _bluetooth_pnp_calistir(eylem: str) -> str:
    # Bluetooth fiziksel adaptörünü (InstanceId USB\* veya PCI\*) PnP üzerinden kontrol eder.
    # Bağlı BT cihazları (BTHENUM\, BTH\, SWD\ vb.) dışlanır — yalnızca adaptör hedeflenir.
    # Teşhis: Intel(R) Wireless Bluetooth(R) → USB\VID_8087&PID_0033\5&274D72C6&0&14
    #
    # f-string kullanılır: {{}} → {} PowerShell'e gider (dosyanın geri kalanıyla tutarlı).
    # ESKİ raw string (r"""...""") yaklaşımı {{}} PowerShell'e literal olarak gönderiyordu
    # ve scriptblock syntax'ı bozuluyordu — hiç çalışmıyordu.
    ps_script = f"""
try {{
    $adaptorler = Get-PnpDevice | Where-Object {{
        ($_.FriendlyName -like '*Bluetooth*') -and
        ($_.InstanceId -like 'USB\\*' -or $_.InstanceId -like 'PCI\\*') -and
        ($_.FriendlyName -notlike '*Audio*') -and
        ($_.FriendlyName -notlike '*Sound*')
    }}
    if (-not $adaptorler) {{
        Write-Output "BULUNAMADI"
        exit
    }}
    foreach ($c in $adaptorler) {{
        Write-Output "CIHAZ:$($c.FriendlyName)"
        {eylem} -InstanceId $c.InstanceId -Confirm:$false -ErrorAction Stop
    }}
    Start-Sleep -Milliseconds 700
    $ilk     = $adaptorler | Select-Object -First 1
    $kontrol = Get-PnpDevice -InstanceId $ilk.InstanceId -ErrorAction SilentlyContinue
    if ($kontrol) {{
        Write-Output "DURUM:$($kontrol.Status)"
    }} else {{
        Write-Output "DURUM:BILINMIYOR"
    }}
}} catch {{
    Write-Output "HATA:$($_.Exception.Message)"
}}
"""
    try:
        sonuc = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        cikti = sonuc.stdout.strip()
        print(f"[BT_PNP] {eylem} → '{cikti}'")   # gerçek PowerShell çıktısı
        return cikti
    except Exception as e:
        hata = f"HATA:{e}"
        print(f"[BT_PNP] {eylem} → exception: {e}")
        return hata


def _bt_sonucu_isle(cikti: str, hedef_durum: str, basarili_mesaj: str) -> bool:
    # Radio API ve PnP çıktısını ortak işler. True → başarı, False → başarısız.
    # hedef_durum: "OFF" veya "DISABLED" (kapat için), "ON" veya "OK" (aç için)
    if "DURUM:" in cikti:
        durum = cikti.split("DURUM:", 1)[1].strip().upper()
        if durum in hedef_durum.split("|"):
            konus(basarili_mesaj)
            return True
        konus(f"Bluetooth komutu gönderildi ancak durum '{durum}' olarak gözüküyor.")
        return False
    if "BULUNAMADI" in cikti:
        return False   # Üst fonksiyon mesaj verir
    if "HATA:" in cikti:
        hata = cikti.split("HATA:", 1)[1].strip()
        print(f"[BLUETOOTH] Hata: {hata}")
        return False
    return False


def _bluetooth_ayarlari_ac():
    # Bluetooth ayar sayfasını açar — koddan değiştiremediğimizde dürüst son çare.
    try:
        os.startfile("ms-settings:bluetooth")
    except Exception:
        pass


def bluetooth_ac():
    # Bluetooth'u AÇAR. Eylem "On" — kapatma ile KARIŞTIRILMAZ.
    # 1. Yöntem: Windows.Devices.Radios API (SetStateAsync(On))
    # 2. Yöntem: Enable-PnpDevice (yedek)
    # Hiçbiri olmazsa DÜRÜSTÇE: ayar sayfasını aç, "açamadım" de — asla yalandan "açıldı" deme.
    cikti = _bluetooth_radio_api_calistir("On")

    # SetStateAsync 'Allowed' döndürdüyse komut kabul edildi → başarılı
    if "SONUC:Allowed" in cikti:
        konus("Bluetooth açıldı.")
        return
    if "BULUNAMADI" in cikti:
        konus("Bu cihazda Bluetooth radyosu bulunamadı.")
        return

    # Radio API erişim reddi/hata → PnP yedek (yalnızca radyo bulunduysa anlamlı)
    print("[BLUETOOTH] Radio API ile açılamadı, PnP deneniyor...")
    pnp = _bluetooth_pnp_calistir("Enable-PnpDevice")
    if _bt_sonucu_isle(pnp, "OK", "Bluetooth açıldı (PnP yöntemi)."):
        return

    # Hiçbiri olmadı → DÜRÜST
    print(f"[BLUETOOTH] Açma başarısız. Radio='{cikti}' PnP='{pnp}'")
    konus("Bluetooth'u koddan açamadım, Bluetooth ayarlarını açıyorum, oradan açabilirsin.")
    _bluetooth_ayarlari_ac()


def bluetooth_kapat():
    # Bluetooth'u KAPATIR. Eylem "Off" — açma ile KARIŞTIRILMAZ.
    # 1. Yöntem: Windows.Devices.Radios API (SetStateAsync(Off))
    # 2. Yöntem: Disable-PnpDevice (yedek — bu adaptörde "Generic failure" verebilir)
    # Hiçbiri olmazsa DÜRÜSTÇE: ayar sayfasını aç, "kapatamadım" de — asla yalandan "kapatıldı" deme.
    cikti = _bluetooth_radio_api_calistir("Off")

    if "SONUC:Allowed" in cikti:
        konus("Bluetooth kapatıldı.")
        return
    if "BULUNAMADI" in cikti:
        konus("Bu cihazda Bluetooth radyosu bulunamadı.")
        return

    # Radio API erişim reddi/hata → PnP yedek
    print("[BLUETOOTH] Radio API ile kapatılamadı, PnP deneniyor...")
    pnp = _bluetooth_pnp_calistir("Disable-PnpDevice")
    if _bt_sonucu_isle(pnp, "DISABLED", "Bluetooth kapatıldı (PnP yöntemi)."):
        return

    # Hiçbiri olmadı → DÜRÜST (PnP genelde "Generic failure" verir)
    print(f"[BLUETOOTH] Kapatma başarısız. Radio='{cikti}' PnP='{pnp}'")
    konus("Bluetooth'u koddan kapatamadım, Bluetooth ayarlarını açıyorum, oradan kapatabilirsin.")
    _bluetooth_ayarlari_ac()


# ── 5) GÜÇ / PERFORMANS MODU ─────────────────────────────────────────────────

def performans_modu():
    # Windows "Yüksek Performans" güç planına geçer (SCHEME_MIN).
    # ASUS Turbo ile eşdeğer Windows düzeyi kontrolü.
    try:
        subprocess.run(["powercfg", "/setactive", "SCHEME_MIN"], check=True, capture_output=True)
        konus("Yüksek performans moduna geçildi.")
    except Exception:
        konus("Performans moduna geçilemedi. Yönetici yetkisi gerekebilir.")


def denge_modu():
    # Windows "Dengeli" güç planına geçer (SCHEME_BALANCED).
    try:
        subprocess.run(["powercfg", "/setactive", "SCHEME_BALANCED"], check=True, capture_output=True)
        konus("Dengeli güç moduna geçildi.")
    except Exception:
        konus("Dengeli moda geçilemedi.")


def tasarruf_modu():
    # Windows "Güç Tasarrufu" güç planına geçer (SCHEME_MAX).
    try:
        subprocess.run(["powercfg", "/setactive", "SCHEME_MAX"], check=True, capture_output=True)
        konus("Güç tasarrufu moduna geçildi. Performans düşebilir.")
    except Exception:
        konus("Tasarruf moduna geçilemedi.")


# ── 6) EKRAN / GÖRÜNTÜ ───────────────────────────────────────────────────────

def ekran_kilitle():
    # Windows oturumunu kilitler (Ctrl+Alt+Del ekranına geçer).
    try:
        ctypes.windll.user32.LockWorkStation()
        konus("Ekran kilitlendi.")
    except Exception:
        konus("Ekranı kilitleyemedim.")


def ekrani_kapat():
    # Monitörü güç tasarrufu (kapalı) konumuna alır.
    # PostMessage HWND_BROADCAST ile SC_MONITORPOWER=2 (off) mesajı gönderir.
    try:
        HWND_BROADCAST  = 0xFFFF
        WM_SYSCOMMAND   = 0x0112
        SC_MONITORPOWER = 0xF170
        MONITOR_OFF     = 2
        ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_OFF)
        konus("Monitör kapatıldı.")
    except Exception:
        konus("Monitörü kapatamadım.")


def gece_modu():
    # Windows Gece Işığı (Night Light) ayarlar sayfasını açar.
    try:
        os.startfile("ms-settings:nightlight")
        konus("Gece ışığı ayarları açıldı.")
    except Exception:
        konus("Gece ışığı ayarlarına ulaşamadım.")


# ── 7) GÜÇ İŞLEMLERİ ─────────────────────────────────────────────────────────

def uyku_modu(mod: str = "sesli"):
    # Bilgisayarı uyku (sleep) moduna alır.
    # ÖNCE kullanıcıdan sesli/yazılı onay alır.
    konus("Bilgisayarı uyku moduna alayım mı?")
    yanit = komut_dinle() if mod == "sesli" else yaz().lower().strip()
    if not yanit or not any(k in yanit for k in ("evet", "tamam", "al", "ok", "git")):
        konus("İptal edildi.")
        return
    try:
        # Windows.Forms SetSuspendState('Sleep', forceCritical, disableWakeEvent) — gerçek uyku.
        # rundll32 SetSuspendState bazı sistemlerde hibernate (hazırda bekleme) yapabiliyor.
        # Windows.Forms yöntemi sleep ile hibernate'i net biçimde ayırt eder.
        # NOT: Sistem "hybrid sleep" aktifse; uyandırma hızlı olur ama bir anlık disk yazımı yapılır.
        #       Bu normaldir ve gerçek hibernate değildir (RAM içeriği korunur).
        ps_uyku = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
            "[System.Windows.Forms.Application]::SetSuspendState('Sleep', $false, $false)"
        )
        subprocess.Popen(["powershell", "-NonInteractive", "-Command", ps_uyku])
    except Exception:
        konus("Uyku moduna geçilemedi.")


def yeniden_baslat(mod: str = "sesli"):
    # Bilgisayarı 5 saniye sonra yeniden başlatır.
    # ÖNCE kullanıcıdan onay alır.
    konus("Bilgisayarı yeniden başlatayım mı? Beş saniye içinde başlayacak.")
    yanit = komut_dinle() if mod == "sesli" else yaz().lower().strip()
    if not yanit or not any(k in yanit for k in ("evet", "tamam", "başlat", "yap", "ok")):
        konus("İptal edildi.")
        return
    try:
        subprocess.run(["shutdown", "/r", "/t", "5"])
        konus("Beş saniye içinde yeniden başlıyor.")
    except Exception:
        konus("Yeniden başlatılamadı.")


# ── 8) DONANIM DURUMU ────────────────────────────────────────────────────────

def pil_durumu():
    # Pil yüzdesini ve şarj durumunu sesli bildirir (psutil).
    try:
        pil = psutil.sensors_battery()
        if pil is None:
            konus("Bu cihazda pil bilgisi bulunamadı.")
            return
        durum = "şarjda" if pil.power_plugged else "pille çalışıyor"
        konus(f"Pil yüzde {pil.percent:.0f}, {durum}.")
    except Exception:
        konus("Pil durumunu okuyamadım.")


def sistem_durumu():
    # CPU, RAM ve disk kullanım yüzdelerini tek cümlede özetler (psutil).
    try:
        cpu  = psutil.cpu_percent(interval=1)
        ram  = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        konus(
            f"İşlemci yüzde {cpu:.0f}, "
            f"bellek yüzde {ram.percent:.0f}, "
            f"disk yüzde {disk.percent:.0f} dolu."
        )
    except Exception:
        konus("Sistem durumunu okuyamadım.")


def cpu_sicakligi():
    # CPU sıcaklığını okumaya çalışır.
    # psutil.sensors_temperatures() Windows'ta genellikle None döndürür;
    # bu durumda WMI üzerinden ACPI termal bölgesini dener.
    try:
        sicakliklar = psutil.sensors_temperatures()
        if sicakliklar:
            for _, kayitlar in sicakliklar.items():
                if kayitlar:
                    konus(f"İşlemci sıcaklığı yaklaşık {kayitlar[0].current:.0f} derece.")
                    return
    except Exception:
        pass
    # WMI fallback — ACPI termal bölgesi (Kelvin → Celsius)
    try:
        import wmi as _wmi
        w = _wmi.WMI(namespace="root\\wmi")
        sicak = w.MSAcpi_ThermalZoneTemperature()[0]
        celsius = sicak.CurrentTemperature / 10.0 - 273.15
        konus(f"İşlemci sıcaklığı yaklaşık {celsius:.0f} derece.")
    except Exception:
        konus("Sıcaklık bilgisine ulaşamadım.")


# ── 9) UYGULAMA KAPAT ────────────────────────────────────────────────────────

def uygulama_kapat(metin: str):
    # Komut metnindeki uygulama adını _UYGULAMA_SOZLUGU'nda arar
    # ve taskkill ile o uygulamayı zorla kapatır.
    try:
        metin_k = metin.lower()
        bulunan = None
        for anahtar, exe in _UYGULAMA_SOZLUGU.items():
            if anahtar in metin_k:
                bulunan = exe
                break
        if not bulunan:
            konus("Hangi uygulamayı kapatmamı istediğini anlayamadım.")
            return
        sonuc = subprocess.run(
            ["taskkill", "/im", bulunan, "/f"],
            capture_output=True, text=True,
        )
        uygulama_adi = bulunan.split(".")[0]
        if sonuc.returncode == 0:
            konus(f"{uygulama_adi} kapatıldı.")
        else:
            konus(f"{uygulama_adi} zaten kapalı veya bulunamadı.")
    except Exception:
        konus("Uygulamayı kapatamadım.")


# ── 10) KLAVYE AYDINLATMASI (ASUS Aura — USB HID) ────────────────────────────
# Bu ROG makinede klavye ACPI ile DEĞİL, USB HID Aura protokolüyle kontrol edilir.
# aura_hid modülü G-Helper'ın (AsusHid.cs/Aura.cs) byte dizilerini birebir uygular.
# ÖNEMLİ: HID gönderimi teknik başarılı olsa bile ışığın fiziksel değişimi garanti
# değil; bu yüzden mesajlar "kesin yapıldı" demez, kullanıcının görmesini ister.

# Türkçe renk adı → (R, G, B) eşlemesi
_RENK_TABLOSU = {
    "kırmızı":  (255, 0, 0),
    "yeşil":    (0, 255, 0),
    "mavi":     (0, 0, 255),
    "beyaz":    (255, 255, 255),
    "mor":      (128, 0, 128),
    "turuncu":  (255, 60, 0),
    "sarı":     (255, 255, 0),
    "pembe":    (255, 20, 147),
    "camgöbeği": (0, 255, 255),
    "cyan":     (0, 255, 255),
}

# Türkçe/İngilizce efekt adı → (AuraMode, efekt_adı)
_EFEKT_TABLOSU = [
    (("renk döngüsü", "color cycle", "döngü"), aura_hid.MOD_COLORCYCLE, "renk döngüsü"),
    (("gökkuşağı", "rainbow", "gök kuşağı"),   aura_hid.MOD_RAINBOW,    "gökkuşağı"),
    (("nefes", "breathe", "breathing"),        aura_hid.MOD_BREATHE,    "nefes"),
    (("strobe", "yanıp sön", "flaş"),          aura_hid.MOD_STROBE,     "strobe"),
    (("sabit", "static", "düz"),               aura_hid.MOD_STATIC,     "sabit"),
]


def klavye_isigi_ayarla(metin: str):
    # Klavye parlaklığını USB HID Aura ile ayarlar — 4 DÜZEY:
    #   0 = kapalı
    #   1 = düşük (açık, ilk seviye)
    #   2 = orta
    #   3 = maksimum (en parlak)
    metin_k = metin.lower()

    # ÖNCELİK 1: Metinde açık tek haneli sayı (0-3) varsa onu kullan.
    #   "klavye ışığı 2", "klavye ışığını 3 yap" → o seviye.
    #   \b...\b kelime sınırı: "30"/"50" gibi çok haneli sayıları yanlışlıkla yakalamaz.
    _sayi = re.search(r"\b([0-3])\b", metin_k)

    if _sayi:
        seviye = int(_sayi.group(1))
    elif any(k in metin_k for k in ("kapat", "söndür", "kapalı")):
        seviye = 0
    elif any(k in metin_k for k in ("düşük", "az", "minimal", "kıs", "ilk")):
        seviye = 1
    elif any(k in metin_k for k in ("orta", "yarı")):
        seviye = 2
    elif any(k in metin_k for k in ("maksimum", "max", "yüksek", "tam", "full", "en parlak")):
        seviye = 3
    else:
        # "aç" veya belirsiz → maksimum (en parlak açık)
        seviye = 3

    _SEVIYE_ADLARI = {0: "kapalı", 1: "düşük", 2: "orta", 3: "maksimum"}
    seviye_adi = _SEVIYE_ADLARI[seviye]

    basarili = aura_hid.aura_parlaklik(seviye)
    print(f"[KLAVYE_ISIGI] istenen_seviye={seviye} hid_gönderim={basarili}")

    if not basarili:
        # HID cihazı bulunamadı / hidapi yok / yazma reddedildi → dürüst hata
        konus(
            "Klavye ışığını değiştiremedim. ASUS Aura cihazına erişemedim; "
            "hidapi kurulu ve G-Helper kapalı olmalı."
        )
        return

    # Gönderim teknik olarak başarılı — ama fiziksel sonucu kullanıcı doğrulamalı
    if seviye == 0:
        konus("Klavye ışığını kapatma komutunu gönderdim.")
    else:
        konus(f"Klavye ışığını {seviye_adi} seviyeye ayarlama komutunu gönderdim.")


def klavye_renk_ayarla(metin: str):
    # Klavye rengini sabit (Static) modda ayarlar. Metinde geçen renk adını bulur.
    metin_k = metin.lower()

    bulunan_renk = None
    renk_adi = None
    for ad, rgb in _RENK_TABLOSU.items():
        if ad in metin_k:
            bulunan_renk = rgb
            renk_adi = ad
            break

    if bulunan_renk is None:
        konus(
            "Hangi rengi yapmamı istediğini anlayamadım. "
            "Kırmızı, yeşil, mavi, beyaz, mor, turuncu, sarı veya pembe diyebilirsin."
        )
        return

    r, g, b = bulunan_renk
    basarili = aura_hid.aura_renk(aura_hid.MOD_STATIC, r, g, b)
    print(f"[KLAVYE_RENK] renk={renk_adi} rgb=({r},{g},{b}) hid_gönderim={basarili}")

    if not basarili:
        konus(
            "Klavye rengini değiştiremedim. ASUS Aura cihazına erişemedim; "
            "hidapi kurulu ve G-Helper kapalı olmalı."
        )
        return

    konus(f"Klavyeyi {renk_adi} yapma komutunu gönderdim.")


def klavye_efekt_ayarla(metin: str):
    # Klavye aydınlatma efektini ayarlar (gökkuşağı, nefes, renk döngüsü, strobe, sabit).
    metin_k = metin.lower()

    mod = None
    efekt_adi = None
    for anahtarlar, mod_kod, ad in _EFEKT_TABLOSU:
        if any(a in metin_k for a in anahtarlar):
            mod = mod_kod
            efekt_adi = ad
            break

    if mod is None:
        konus(
            "Hangi efekti istediğini anlayamadım. "
            "Gökkuşağı, nefes, renk döngüsü, strobe veya sabit diyebilirsin."
        )
        return

    # Efektlerde renk de istenebilir; metinde renk adı varsa onu kullan, yoksa beyaz.
    # (Gökkuşağı/renk döngüsü modlarında firmware rengi yok sayar — zararsız.)
    r, g, b = 255, 255, 255
    for ad, rgb in _RENK_TABLOSU.items():
        if ad in metin_k:
            r, g, b = rgb
            break

    basarili = aura_hid.aura_renk(mod, r, g, b, hiz=1)
    print(f"[KLAVYE_EFEKT] efekt={efekt_adi} mod={mod} hid_gönderim={basarili}")

    if not basarili:
        konus(
            "Klavye efektini değiştiremedim. ASUS Aura cihazına erişemedim; "
            "hidapi kurulu ve G-Helper kapalı olmalı."
        )
        return

    konus(f"Klavyeye {efekt_adi} efektini uygulama komutunu gönderdim.")


# ── 11) FAN MODU (ASUS) ──────────────────────────────────────────────────────

def fan_modu_ayarla(metin: str):
    # ASUS fan/termal profilini ATKACPI DeviceIoControl ile değiştirir.
    # G-Helper'ın kullandığı aynı yöntem: acpi_yaz(FAN_MODE, mod_kod).
    # Değerler (PerformanceMode / THROTTLE_THERMAL_POLICY):
    #   0=Dengeli, 1=Turbo, 2=Sessiz
    metin_k = metin.lower()
    if any(k in metin_k for k in ("sessiz", "silent", "sakin", "quiet")):
        mod_kod, mod_adi = 2, "Sessiz"
    elif any(k in metin_k for k in ("turbo", "maksimum", "max", "tam güç", "performans", "güçlü", "yüksek")):
        mod_kod, mod_adi = 1, "Turbo"
    else:
        mod_kod, mod_adi = 0, "Dengeli"

    # DEVS ile yaz (başarı = IOCTL geçti)
    basarili = acpi_yaz(FAN_MODE, mod_kod)

    # TEŞHİS: geri okuma SADECE bilgi amaçlı. Fan/performans modunun DSTS geri
    # okuması ASUS donanımında güvenilir DEĞİL (yazılan değeri yansıtmayabilir);
    # G-Helper bile bu modu yazıp geri okumaya güvenmez. Bu yüzden geri okuma
    # uyuşmazlığını BAŞARISIZLIK SAYMIYORUZ — yalnızca yazdırıyoruz.
    ham_oku = acpi_oku(FAN_MODE)
    print(
        f"[FAN] mod={mod_adi}({mod_kod}) yazma_ioctl={basarili} "
        f"geri_okuma_ham={ham_oku} çıkarılan_değer={acpi_deger(ham_oku)} "
        f"(geri okuma bilgi amaçlı, başarı ölçütü değil)"
    )

    if not basarili:
        # IOCTL'in kendisi başarısız → gerçek erişim/aygıt sorunu
        konus("Fan modunu değiştiremedim; donanım yazma komutunu reddetti.")
        return

    # Yazma çağrısı hata vermediyse komut donanıma ulaşmıştır → başarılı say.
    konus(f"Fan modu {mod_adi} olarak ayarlandı.")


# ── 12) GPU MODU (ASUS Optimus) ───────────────────────────────────────────────

def gpu_modu_ayarla(metin: str, mod: str = "sesli"):
    # ASUS GPU MUX modunu ATKACPI DeviceIoControl ile değiştirir.
    # G-Helper'ın kullandığı aynı yöntem: acpi_yaz(GPU_MUX, gpu_kod).
    # Değerler (GPUMuxROG / 0x00090016):
    #   0=Eco (iGPU), 1=Standart/Optimus, 2=Ultimate (dGPU)
    # DİKKAT: Bu değişiklik yeniden başlatma gerektirir.
    metin_k = metin.lower()
    if any(k in metin_k for k in ("eco", "tasarruf", "entegre", "igpu", "sadece entegre")):
        gpu_adi, gpu_kod = "Eco — sadece entegre GPU", 0
    elif any(k in metin_k for k in ("ultimate", "sadece ayrık", "dgpu", "tam güç", "dedicated")):
        gpu_adi, gpu_kod = "Ultimate — sadece ayrık GPU", 2
    else:
        gpu_adi, gpu_kod = "Standart/Optimus — otomatik geçiş", 1

    konus(
        f"GPU modunu {gpu_adi} olarak değiştirmek istiyorsun. "
        "Bu işlem için oturumu yeniden başlatman gerekecek. Devam edeyim mi?"
    )
    yanit = komut_dinle() if mod == "sesli" else yaz().lower().strip()
    if not yanit or not any(k in yanit for k in ("evet", "tamam", "devam", "yap", "ok")):
        konus("GPU modu değişikliği iptal edildi.")
        return

    # DEVS ile yaz
    if acpi_yaz(GPU_MUX, gpu_kod):
        konus(
            f"GPU modu {gpu_adi} olarak ayarlandı. "
            "Değişikliğin etkili olması için oturumu yeniden başlatman gerekiyor."
        )
    else:
        konus(
            "GPU modunu değiştiremedim. "
            "Programı yönetici olarak çalıştırmayı dene."
        )


# ── 13) TOUCHPAD ─────────────────────────────────────────────────────────────

def _touchpad_pnp(etkinlestir: bool):
    # PowerShell ile touchpad PnP cihazını etkinleştirir veya devre dışı bırakır.
    eylem = "Enable-PnpDevice" if etkinlestir else "Disable-PnpDevice"
    # Devre dışı bırakılmış cihazları da bulabilmek için -Status filtresi kullanılmaz
    filtre = '-Status "Error"' if etkinlestir else ""
    ps_script = f"""
try {{
    $cihazlar = Get-PnpDevice | Where-Object {{
        ($_.FriendlyName -like "*Touchpad*" -or
         $_.FriendlyName -like "*TouchPad*" -or
         $_.FriendlyName -like "*Precision*" -or
         $_.FriendlyName -like "*ELAN*" -or
         $_.FriendlyName -like "*Synaptics*")
    }}
    if ($cihazlar) {{
        foreach ($c in $cihazlar) {{
            {eylem} -InstanceId $c.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
        }}
        Write-Output "OK"
    }} else {{
        Write-Output "BULUNAMADI"
    }}
}} catch {{
    Write-Output "HATA:$($_.Exception.Message)"
}}
"""
    try:
        cikti = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return cikti
    except Exception:
        return "HATA"


def touchpad_kapat():
    # Touchpad PnP cihazını devre dışı bırakır. Yönetici yetkisi gerekebilir.
    cikti = _touchpad_pnp(etkinlestir=False)
    if "OK" in cikti:
        konus("Touchpad devre dışı bırakıldı.")
    elif "BULUNAMADI" in cikti:
        konus("Touchpad cihazı bulunamadı.")
    else:
        konus("Touchpad kapatmak için yönetici olarak çalıştırman gerekebilir.")


def touchpad_ac():
    # Touchpad PnP cihazını etkinleştirir. Yönetici yetkisi gerekebilir.
    cikti = _touchpad_pnp(etkinlestir=True)
    if "OK" in cikti:
        konus("Touchpad etkinleştirildi.")
    elif "BULUNAMADI" in cikti:
        konus("Devre dışı touchpad cihazı bulunamadı; zaten açık olabilir.")
    else:
        konus("Touchpad açmak için yönetici olarak çalıştırman gerekebilir.")


# ── 14) WINDOWS TUŞU KİLİDİ ──────────────────────────────────────────────────

def windows_tusu_kapat():
    # Klavye Scancode Map'i değiştirerek Sol ve Sağ Windows tuşunu devre dışı bırakır.
    # DEĞİŞİKLİK İÇİN YENİDEN BAŞLATMA GEREKİR.
    # Registry key: HKLM\SYSTEM\CurrentControlSet\Control\Keyboard Layout
    #   "Scancode Map" → REG_BINARY
    # Veri formatı: 8 byte header + (giriş sayısı * 4 byte) + 4 byte null
    # Her giriş: 2 byte hedef (0x0000 = devre dışı), 2 byte kaynak (E0 5B = Win Sol)
    try:
        scancode_map = bytes([
            0x00, 0x00, 0x00, 0x00,   # Sürüm
            0x00, 0x00, 0x00, 0x00,   # Bayraklar
            0x03, 0x00, 0x00, 0x00,   # Giriş sayısı: 2 devre dışı + 1 null = 3
            0x00, 0x00, 0x5B, 0xE0,   # Sol Windows tuşu (E0 5B) → null
            0x00, 0x00, 0x5C, 0xE0,   # Sağ Windows tuşu (E0 5C) → null
            0x00, 0x00, 0x00, 0x00,   # Null terminator
        ])
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Keyboard Layout",
            0, winreg.KEY_SET_VALUE,
        ) as anahtar:
            winreg.SetValueEx(anahtar, "Scancode Map", 0, winreg.REG_BINARY, scancode_map)
        konus("Windows tuşu devre dışı bırakıldı. Değişiklik için yeniden başlatman gerekiyor.")
    except PermissionError:
        konus("Windows tuşunu devre dışı bırakmak için yönetici yetkisi gerekiyor.")
    except Exception:
        konus("Windows tuşunu devre dışı bırakamadım.")


def windows_tusu_ac():
    # Scancode Map'i silerek Windows tuşlarını geri etkinleştirir.
    # DEĞİŞİKLİK İÇİN YENİDEN BAŞLATMA GEREKİR.
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Keyboard Layout",
            0, winreg.KEY_SET_VALUE,
        ) as anahtar:
            try:
                winreg.DeleteValue(anahtar, "Scancode Map")
            except FileNotFoundError:
                pass  # Zaten kayıt yok, Windows tuşu aktif demektir
        konus("Windows tuşu etkinleştirildi. Değişiklik için yeniden başlatman gerekiyor.")
    except PermissionError:
        konus("Windows tuşunu etkinleştirmek için yönetici yetkisi gerekiyor.")
    except Exception:
        konus("Windows tuşunu etkinleştiremedim.")


# ── 15) EKRAN MODU / TAZELEME HIZI ───────────────────────────────────────────

def ekran_modu_ayarla(metin: str):
    # Ekran tazeleme hızını değiştirmeye çalışır (ChangeDisplaySettingsW API).
    # Sayı varsa o Hz'e geçmeyi dener; olmayan bir mod istenirse hata vermez.
    # Başarısızsa veya sayı yoksa ekran ayarları sayfasını açar.
    sayi = re.search(r"\d+", metin)
    if sayi:
        hedef_hz = int(sayi.group())
        try:
            dm = _devmode_al()
            if dm:
                # Sadece tazeleme hızını değiştir, diğer ayarlara dokunma
                dm.dmFields           = 0x00400000   # DM_DISPLAYFREQUENCY bayrağı
                dm.dmDisplayFrequency = hedef_hz
                # CDS_TEST (0x02) ile önce desteklenip desteklenmediğini kontrol et
                test_sonuc = ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0x02)
                if test_sonuc == 0:   # DISP_CHANGE_SUCCESSFUL
                    # Test geçti → gerçekten uygula
                    ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)
                    konus(f"Ekran tazeleme hızı {hedef_hz} hertz olarak ayarlandı.")
                    return
                elif test_sonuc == 1:   # DISP_CHANGE_RESTART gerekli
                    ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)
                    konus(f"Tazeleme hızı {hedef_hz} hertz, yeniden başlatma gerekiyor.")
                    return
                else:
                    konus(
                        f"{hedef_hz} hertz bu ekranda desteklenmiyor. "
                        "Ekran ayarlarından desteklenen bir değer seçebilirsin."
                    )
                    os.startfile("ms-settings:display-advanced")
                    return
        except Exception:
            pass
    # Sayı yok veya değişiklik başarısız → ekran ayarlar sayfasını aç
    try:
        os.startfile("ms-settings:display-advanced")
        if sayi:
            konus(f"Ekran ayarları açıldı. {hedef_hz} hertz için oradan değiştirebilirsin.")
        else:
            konus("Ekran ve tazeleme hızı ayarları açıldı.")
    except Exception:
        konus("Ekran ayarlarına ulaşamadım.")


# ── 16) OTURUM KAPAT ─────────────────────────────────────────────────────────

def oturum_kapat():
    # Windows oturumunu kapatır (logoff — bilgisayar kapatılmaz, oturum sonlandırılır).
    # "shutdown /l" YALNIZCA mevcut kullanıcı oturumunu kapatır; PC çalışmaya devam eder.
    # Program çıkışı ("çıkış"/"kapat") ile KARIŞTIRILMAMALIDIR.
    try:
        subprocess.Popen(["shutdown", "/l"])
        # Oturum kapandığında bu konus() mesajı ulaşmayabilir ama deneyelim
        konus("Oturum kapatılıyor.")
    except Exception as e:
        print(f"[OTURUM] Hata: {e}")
        konus("Oturumu kapatamadım.")
