# Bu dosya GLOBAL / eğlenceli özel günlerin statik listesini içerir.
# Türkiye'ye özel resmi günler DEĞİL; dünya çapında bilinen/eğlenceli günler.
# Anahtar formatı "AY-GÜN" (ör. "03-14" = 14 Mart). Friday bunları sabah raporunda
# ve "bugün ne günü / 14 mart ne günü" sorularında kullanır.

import datetime
import re

from dateparser.search import search_dates
from ses import konus

_AY_RE = r"(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)"


def _tarih_metni_normalle(metin: str) -> str:
    # dateparser Türkçe locative ekini anlamıyor ("14 martta" → bulamaz).
    # Ay adından "ta/te/da/de" ekini at. (takvim.py'deki ile aynı mantığın özeti;
    # özel gün sorgusunda saat gerekmediği için sadece ay-eki yeterli.)
    return re.sub(_AY_RE + r"(ta|te|da|de)\b", r"\1", metin.lower())

# ── SABİT TARİHLİ ÖZEL GÜNLER ("AA-GG" → ad) ──────────────────────────────────
_OZEL_GUNLER = {
    "01-01": "Yılbaşı",
    "01-04": "Dünya Braille Günü",
    "02-04": "Dünya Kanser Günü",
    "02-11": "Bilimde Kadınlar ve Kızlar Günü",
    "02-14": "Sevgililer Günü",
    "02-20": "Dünya Sosyal Adalet Günü",
    "03-03": "Dünya Yaban Hayatı Günü",
    "03-08": "Dünya Kadınlar Günü",
    "03-14": "Pi Günü",                         # 3.14
    "03-17": "Aziz Patrick Günü",
    "03-20": "Dünya Mutluluk Günü",
    "03-21": "Dünya Şiir Günü",
    "03-22": "Dünya Su Günü",
    "04-01": "Şaka Günü (1 Nisan)",
    "04-07": "Dünya Sağlık Günü",
    "04-22": "Dünya Günü",
    "04-23": "Dünya Kitap Günü",                # ayrıca TR: 23 Nisan
    "05-04": "Star Wars Günü (May the 4th)",
    "05-12": "Dünya Hemşireler Günü",
    "05-25": "Havlu Günü (Towel Day)",
    "06-05": "Dünya Çevre Günü",
    "06-21": "Dünya Müzik Günü",
    "07-17": "Dünya Emoji Günü",
    "08-08": "Dünya Kediler Günü",
    "08-19": "Dünya Fotoğrafçılık Günü",
    "09-08": "Dünya Okuryazarlık Günü",
    "09-19": "Korsan Gibi Konuş Günü",
    "09-21": "Dünya Barış Günü",
    "09-30": "Dünya Çeviri Günü",
    "10-01": "Dünya Kahve Günü",
    "10-04": "Dünya Hayvanları Koruma Günü",
    "10-05": "Dünya Öğretmenler Günü",
    "10-31": "Cadılar Bayramı (Halloween)",
    "11-11": "Bekarlar Günü (Singles' Day)",
    "11-13": "Dünya Nezaket Günü",
    "11-19": "Dünya Tuvalet Günü",
    "12-10": "Dünya İnsan Hakları Günü",
    "12-25": "Noel",
    "12-31": "Yılbaşı Arifesi",
}

# dateparser ayarları — Türkçe (takvim.py ile aynı mantık).
_DP_AYAR = {"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False}

_AYLAR = [
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def ozel_gun_kontrol(tarih: datetime.date = None) -> str | None:
    # Verilen tarihte özel gün varsa adını döndürür, yoksa None.
    # tarih verilmezse bugünü kullanır.
    if tarih is None:
        tarih = datetime.date.today()

    anahtar = tarih.strftime("%m-%d")
    if anahtar in _OZEL_GUNLER:
        return _OZEL_GUNLER[anahtar]

    # HESAPLANAN GÜN: Programcılar Günü = yılın 256. günü (256 = 2^8, hoş bir detay).
    if tarih.timetuple().tm_yday == 256:
        return "Programcılar Günü"

    return None


def _tarih_turkce(tarih: datetime.date) -> str:
    bugun = datetime.date.today()
    if tarih == bugun:
        return "Bugün"
    if tarih == bugun + datetime.timedelta(days=1):
        return "Yarın"
    return f"{tarih.day} {_AYLAR[tarih.month]}"


def ozel_gun_soyle(metin: str, mod: str):
    # "bugün özel bir gün mü", "14 mart ne günü", "bugün ne günü" sorularına yanıt.
    # Metinde tarih varsa onu, yoksa bugünü kontrol eder.
    try:
        sonuclar = search_dates(_tarih_metni_normalle(metin), languages=["tr"], settings=_DP_AYAR)
        if sonuclar and sonuclar[0][1] is not None:
            hedef = sonuclar[0][1].date()
        else:
            hedef = datetime.date.today()

        ad = ozel_gun_kontrol(hedef)
        tarih_str = _tarih_turkce(hedef)

        if ad:
            konus(f"{tarih_str} {ad}.")
        else:
            konus(f"{tarih_str} için özel bir gün kaydım yok.")
    except Exception as e:
        print(f"[OZEL_GUN] Hata: {e}")
        konus("Özel gün bilgisine şu an bakamadım.")
