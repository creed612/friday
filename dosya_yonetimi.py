# Bu dosya Friday'in dosya arama ve açma işlemlerini içerir.
# dosya_ara_ve_ac() fonksiyonu burada tanımlıdır.
#
# YÖNTEM: Birincil arama Everything (voidtools) + es.exe ile yapılır — tüm diskleri
# anında indeksler, milisaniyede sonuç verir, Türkçe karakter güvenli.
# es.exe bulunamazsa/Everything kapalıysa eski os.walk yöntemine (yedek) düşülür.

import os
import subprocess
import tempfile

from config import ES_YOLU
from ses import konus, komut_dinle, yaz

# Kullanıcının ana klasörü (örn: C:\Users\KullaniciAdi)
ANA_KLASOR = os.path.expanduser("~")

# Önce taranacak hızlı klasörler — en sık kullanılan yerler
HIZLI_KLASORLER = [
    os.path.join(ANA_KLASOR, "Desktop"),
    os.path.join(ANA_KLASOR, "Documents"),
    os.path.join(ANA_KLASOR, "Downloads"),
    os.path.join(ANA_KLASOR, "Pictures"),
    os.path.join(ANA_KLASOR, "Videos"),
    os.path.join(ANA_KLASOR, "Music"),
]

# Tam disk taramasında atlanacak sistem klasörleri
# (gereksiz/izin sorunu çıkarabilecek dizinler)
ATLANACAK_KLASORLER = {
    "windows",
    "programdata",
    "$recycle.bin",
    "program files",
    "program files (x86)",
    "appdata",
}


def _klasorde_ara(kok_klasor, arama_terimi):
    # Verilen kök klasör ve alt klasörlerinde arama_terimi'ni içeren dosyaları döndürür.
    # PermissionError oluşursa o klasörü sessizce atlar.
    eslesmeler = []
    arama_kucuk = arama_terimi.lower()

    try:
        for klasor, alt_klasorler, dosyalar in os.walk(kok_klasor):
            for dosya in dosyalar:
                if arama_kucuk in dosya.lower():
                    eslesmeler.append(os.path.join(klasor, dosya))
    except PermissionError:
        pass   # İzin hatası — bu klasörü atla, aramayı sürdür

    return eslesmeler


def _disk_tara(arama_terimi):
    # C:\ diskinin tamamını tarar ama sistem klasörlerini atlar.
    eslesmeler = []
    arama_kucuk = arama_terimi.lower()

    for klasor, alt_klasorler, dosyalar in os.walk("C:\\", topdown=True):
        # topdown=True: alt_klasorler listesini değiştirerek ineceğimiz yerleri kısıtlayabiliriz
        # Sistem klasörlerini listeye almadan alt_klasorler'i filtrele (yerinde değiştir)
        alt_klasorler[:] = [
            d for d in alt_klasorler
            if d.lower() not in ATLANACAK_KLASORLER
        ]

        for dosya in dosyalar:
            if arama_kucuk in dosya.lower():
                eslesmeler.append(os.path.join(klasor, dosya))

    return eslesmeler


def _dosyayi_ac(dosya_yolu):
    # Dosyayı Windows'un varsayılan programıyla aç
    dosya_adi = os.path.basename(dosya_yolu)
    konus(f"{dosya_adi} dosyasını açıyorum.")
    os.startfile(dosya_yolu)


def _kullanicidan_numara_al(mod, liste_uzunlugu):
    # Kullanıcıdan hangi dosyayı açmak istediğini öğrenir.
    # Geçerli bir numara girilene kadar tekrar sorar (en fazla 3 deneme).
    for _ in range(3):
        if mod == "sesli":
            cevap = komut_dinle()
        else:
            cevap = yaz().lower()

        # Cevap içindeki ilk sayıyı bulmaya çalış
        for kelime in cevap.split():
            if kelime.isdigit():
                numara = int(kelime)
                if 1 <= numara <= liste_uzunlugu:
                    return numara
                else:
                    konus(f"Lütfen 1 ile {liste_uzunlugu} arasında bir numara söyle.")
                    break
        else:
            # Hiç rakam bulunamadı
            konus("Bir numara anlayamadım, tekrar söyler misin?")

    return None   # 3 denemede de geçerli numara gelmedi


# ── EVERYTHING (es.exe) TABANLI ARAMA ────────────────────────────────────────

# Sistem/geçici/çöp yolları — kullanıcının gerçek dosyaları öncelikli olsun diye elenir.
_ISTENMEYEN_PARCALAR = (
    "\\windows\\", "\\appdata\\", "\\$recycle.bin\\", "\\program files",
    "\\programdata\\", "\\temp\\", "\\tmp\\", "\\cache",
    "\\node_modules\\", "\\.git\\", "\\site-packages\\", "\\winsxs\\",
)


def _es_var_mi() -> bool:
    # es.exe yolu geçerli mi? (config.ES_YOLU)
    return bool(ES_YOLU) and os.path.isfile(ES_YOLU)


def _everything_ara(arama_terimi: str, limit: int = 50):
    # es.exe ile arar. Dönüş: (ok, sonuc_listesi)
    #   ok=False → es.exe/Everything çalışmıyor (returncode!=0 veya exception)
    # Türkçe güvenli yöntem: -export-txt + -utf8-bom ile geçici dosyaya yaz,
    # utf-8-sig ile oku (stdout kodlaması Türkçe Windows'ta güvenilmez).
    # -sort date-modified-descending: en son değişen (kullanıcının güncel) dosyalar
    #   önce gelsin — eski sistem dosyaları listenin sonuna düşer, gerçek dosyalar öne çıkar.
    # limit=50: sistem dosyaları kullanıcı dosyalarını sınırın dışına itmesin diye
    #   bolca sonuç çekilir; sonra _sonuclari_suz çöpü eler, kullanıcıya ilk 5 gösterilir.
    tmp = os.path.join(tempfile.gettempdir(), "_friday_es.txt")
    try:
        r = subprocess.run(
            [ES_YOLU, "-n", str(limit),
             "-sort", "date-modified-descending",
             "-export-txt", tmp, "-utf8-bom", arama_terimi],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            # Everything kapalıysa es.exe hata kodu döndürür
            hata = (r.stderr or b"").decode("utf-8", "ignore") \
                 + (r.stdout or b"").decode("utf-8", "ignore")
            print(f"[DOSYA] es.exe hata (kod {r.returncode}): {hata.strip()[:200]}")
            return False, []
        sonuclar = []
        if os.path.exists(tmp):
            with open(tmp, encoding="utf-8-sig") as f:
                sonuclar = [s.strip() for s in f if s.strip()]
        return True, sonuclar
    except Exception as e:
        print(f"[DOSYA] Everything arama hatası: {e}")
        return False, []
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _sonuclari_suz(sonuclar: list) -> list:
    # Sistem/çöp yollarını eler, kullanıcının gerçek dosyalarını önceliklendirir.
    # Öncelik sırası:
    #   1) Sistem-dışı + gerçek DOSYA  (en iyi — kullanıcının dosyaları)
    #   2) Sistem-dışı (klasör de olsa)
    #   3) Hiçbiri yoksa BOŞ → "bulamadım". WinSxS/Program Files/AppData gibi
    #      sistem dosya/klasörlerini ASLA açmayız (çöp yedeği KASITLI kaldırıldı).
    temiz = [y for y in sonuclar if not any(p in y.lower() for p in _ISTENMEYEN_PARCALAR)]

    temiz_dosya = [y for y in temiz if os.path.isfile(y)]
    if temiz_dosya:
        return temiz_dosya
    return temiz


def dosya_ara_ve_ac(arama_terimi, mod):
    # BİRİNCİL: Everything (es.exe) ile tüm disklerde anında arama.
    # es.exe yoksa eski os.walk yöntemine (yedek) düşer.
    arama_terimi = (arama_terimi or "").strip()
    if not arama_terimi:
        konus("Ne aramamı istersin?")
        return

    # es.exe yoksa → eski yöntem
    if not _es_var_mi():
        print("[DOSYA] es.exe bulunamadı (config.ES_YOLU), eski tarama yöntemi kullanılıyor.")
        _eski_dosya_ara_ve_ac(arama_terimi, mod)
        return

    konus(f"{arama_terimi} için arama yapıyorum.")

    ok, ham = _everything_ara(arama_terimi)
    if not ok:
        konus(
            "Dosya arama servisi Everything çalışmıyor gibi görünüyor. "
            "Lütfen Everything programının açık olduğundan emin ol."
        )
        return

    eslesmeler = _sonuclari_suz(ham)

    # 0 sonuç → wildcard ile genişlet (*terim* → kısmi eşleşme), yine yoksa bildir
    if not eslesmeler:
        ok2, ham2 = _everything_ara(f"*{arama_terimi}*")
        if ok2:
            eslesmeler = _sonuclari_suz(ham2)

    if not eslesmeler:
        konus(f"{arama_terimi} isminde bir dosya bulamadım.")
        return

    # Tek sonuç → direkt aç
    if len(eslesmeler) == 1:
        _dosyayi_ac(eslesmeler[0])
        return

    # Birden fazla → ilk 5'ini numaralandır, seçtir (dosya türü farkı önemli değil:
    # .docx/.pdf hepsi listelenir, kullanıcı seçer).
    goster = eslesmeler[:5]
    liste_sozlu = ""
    for i, yol in enumerate(goster, start=1):
        liste_sozlu += f"{i}, {os.path.basename(yol)}, "

    konus(
        f"{len(eslesmeler)} dosya buldum. İlk {len(goster)} tanesi: {liste_sozlu}"
        "Hangisini açmamı istersin, numarasını söyle."
    )

    secim = _kullanicidan_numara_al(mod, len(goster))
    if secim is not None:
        _dosyayi_ac(goster[secim - 1])
    else:
        konus("Geçerli bir numara alamadım, dosyayı açmıyorum.")


def _eski_dosya_ara_ve_ac(arama_terimi, mod):
    # YEDEK YÖNTEM (eski): os.walk ile tarama. Yalnızca es.exe bulunamazsa kullanılır.
    # Önce hızlı klasörleri, bulamazsa tüm C: diskini tarar (yavaş, tek disk).

    konus(f"{arama_terimi} için arama yapıyorum.")

    # --- ADIM 1: Hızlı klasörleri tara ---
    eslesmeler = []
    for klasor in HIZLI_KLASORLER:
        if os.path.exists(klasor):   # Klasör yoksa atla (örn: Music klasörü olmayabilir)
            eslesmeler.extend(_klasorde_ara(klasor, arama_terimi))

    # --- ADIM 2: Hızlı klasörlerde bulunamadıysa tüm diski tara ---
    if not eslesmeler:
        konus("Bu klasörlerde bulamadım, tüm diski taramaya başlıyorum, biraz zaman alabilir.")
        eslesmeler = _disk_tara(arama_terimi)

    # --- ADIM 3: Sonuçlara göre davran ---

    if not eslesmeler:
        # Hiçbir yerde bulunamadı
        konus("Bu isimde bir dosya bulamadım.")
        return

    if len(eslesmeler) == 1:
        # Tek eşleşme — direkt aç
        _dosyayi_ac(eslesmeler[0])
        return

    # Birden fazla eşleşme — kullanıcıya listele ve seçtir
    # Sesli okuma için dosya adlarını numaralandırıp birleştiriyoruz
    liste_sozlu = ""
    for i, yol in enumerate(eslesmeler, start=1):
        liste_sozlu += f"{i}, {os.path.basename(yol)}, "

    konus(
        f"{len(eslesmeler)} tane dosya buldum: {liste_sozlu}"
        "Hangisini açmamı istersin, numarasını söyle."
    )

    secim = _kullanicidan_numara_al(mod, len(eslesmeler))

    if secim is not None:
        _dosyayi_ac(eslesmeler[secim - 1])   # Liste 0 tabanlı, kullanıcı 1 tabanlı giriyor
    else:
        konus("Geçerli bir numara alamadım, dosyayı açmıyorum.")
