# Bu dosya Friday'in hatırlatıcı özelliğini içerir.
# Hatırlatıcılar bellekte bir listede tutulur; program kapanınca silinir.

import time
import threading
from datetime import datetime
from dateparser.search import search_dates

from ses import konus

# Aktif hatırlatıcıların listesi — her eleman {"zaman": datetime, "mesaj": str}
_hatirlaticilar = []

# Listeye aynı anda iki iş parçacığından erişilmesini önleyen kilit
_liste_kilidi = threading.Lock()


def hatirlatici_kur(komut_metni):
    # Gelen metinden zaman ifadesini ve hatırlatma mesajını ayırır.
    # Örnek: "20 dakika sonra su iç" → zaman=şimdi+20dk, mesaj="su iç"
    # dateparser'ın PREFER_DATES_FROM='future' ayarı geçmiş saatleri yarına taşır.
    sonuclar = search_dates(
        komut_metni,
        languages=["tr"],
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
    )

    if not sonuclar:
        konus("Zamanı anlayamadım, tekrar dener misin?")
        return

    # search_dates → [(eşleşen_metin, datetime), ...]; ilk eşleşmeyi kullan
    zaman_ifadesi, zaman = sonuclar[0]

    if zaman is None:
        konus("Zamanı anlayamadım, tekrar dener misin?")
        return

    # Zaman ifadesini ve tetikleyici "hatırlat" kelimesini çıkararak mesajı elde et
    mesaj = (
        komut_metni
        .replace(zaman_ifadesi, "")
        .replace("hatırlat", "")
        .replace("hatirlatici", "")
        .strip(" ,.-")
    )
    if not mesaj:
        mesaj = "Hatırlatma zamanı geldi."

    with _liste_kilidi:
        _hatirlaticilar.append({"zaman": zaman, "mesaj": mesaj})

    konus(f"Tamam, {zaman.strftime('%H:%M')} için hatırlatıcı kuruldu.")


def _kontrol_dongusu():
    # Arka planda her 10 saniyede bir çalışır; zamanı gelmiş hatırlatıcıları seslendirir.
    while True:
        simdi = datetime.now()
        tetiklenenler = []

        with _liste_kilidi:
            kalan = []
            for h in _hatirlaticilar:
                if simdi >= h["zaman"]:
                    tetiklenenler.append(h)
                else:
                    kalan.append(h)
            # Listeyi yerinde güncelle (referans aynı kalır)
            _hatirlaticilar[:] = kalan

        for h in tetiklenenler:
            konus(f"Hatırlatma: {h['mesaj']}")

        time.sleep(10)


def hatirlaticilari_kontrol_et():
    # Daemon thread olarak başlatılır; program kapanınca otomatik durur.
    thread = threading.Thread(target=_kontrol_dongusu, daemon=True, name="HatirlaticiThread")
    thread.start()
