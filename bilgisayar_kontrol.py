# Bu dosya bilgisayar üzerindeki kontrol işlemlerini içerir.
# Uygulama açma ve bilgisayarı kapatma fonksiyonları burada tanımlıdır.

import webbrowser   # Varsayılan tarayıcıyı açmak için
import subprocess   # Windows uygulamalarını (notepad, calc) başlatmak için
import os           # shutdown komutunu çalıştırmak için

from ses import konus, komut_dinle, yaz


def tarayici_ac():
    konus("Tarayıcıyı açıyorum.")
    webbrowser.open("https://www.google.com")   # Boş sekme yerine Google açılır


def not_defteri_ac():
    konus("Not defterini açıyorum.")
    subprocess.Popen("notepad.exe")   # Popen: programı arka planda başlatır, beklemez


def hesap_makinesi_ac():
    konus("Hesap makinesini açıyorum.")
    subprocess.Popen("calc.exe")


def bilgisayari_kapat(mod):
    # Önce kullanıcıdan onay al; yanlışlıkla kapanmayı önlemek için
    konus("Bilgisayarı gerçekten kapatmamı istiyor musun? Emin isen evet de.")

    # Onay cevabını moda göre al: sesli modda mikrofon, yazılı modda klavye
    if mod == "sesli":
        onay = komut_dinle()   # 5 saniyelik timeout ile sesli cevap bekle
    else:
        onay = yaz().lower()   # Klavyeden cevap al

    if "evet" in onay:
        konus("Bilgisayar kapatılıyor.")
        # /s: kapat  /t 5: 5 saniye sonra (son anda iptal için komut: "shutdown /a")
        os.system("shutdown /s /t 5")
        return True   # Ana döngüyü sonlandır sinyali

    # "evet" gelmedi ya da timeout — kapatma iptal
    konus("Tamam, kapatmıyorum.")
    return False
