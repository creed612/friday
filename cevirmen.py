# Bu dosya Friday'in çevirmen özelliğini içerir.
# deep-translator kütüphanesi aracılığıyla Google Translate motorunu kullanır.
# API anahtarı gerekmez; internet bağlantısı yeterlidir.

from deep_translator import GoogleTranslator
from ses import konus

# Türkçe dil isimlerini Google Translate dil kodlarına eşleyen sözlük
_DIL_KODLARI = {
    "ingilizce": "en",
    "almanca":   "de",
    "fransızca": "fr",
    "ispanyolca": "es",
    "italyanca": "it",
    "rusça":     "ru",
    "arapça":    "ar",
    "japonca":   "ja",
}


def metni_cevir(komut_metni):
    # Komut metninden hedef dili ve çevrilecek metni ayırır, çeviriyi yapar.
    # Örnek: "merhaba nasılsın çevir ingilizceye" → hedef="en", metin="merhaba nasılsın"

    # Hangi dil geçiyor? Sözlükte ilk eşleşeni al; bulunamazsa İngilizce varsayılan
    hedef_dil_adi = None
    hedef_kod = "en"
    for dil_adi, kod in _DIL_KODLARI.items():
        if dil_adi in komut_metni:
            hedef_dil_adi = dil_adi
            hedef_kod = kod
            break

    # Tetikleyici kelimeleri çıkararak çevrilecek metni elde et
    temiz = komut_metni
    temiz = temiz.replace("çevir", "")
    temiz = temiz.replace("çevirir misin", "")
    temiz = temiz.replace("çevirmenin", "")
    if hedef_dil_adi:
        # "ingilizceye", "ingilizce" vb. biçimlerini temizle
        for sonek in ("ye", "ya", "e", "a", "de", "da", ""):
            temiz = temiz.replace(hedef_dil_adi + sonek, "")
    temiz = temiz.strip(" ,.-?!")

    if not temiz:
        konus("Ne çevirmemi istersin? Lütfen bir metin söyle.")
        return

    try:
        ceviri = GoogleTranslator(source="tr", target=hedef_kod).translate(temiz)
        dil_etiketi = hedef_dil_adi.capitalize() if hedef_dil_adi else "İngilizce"
        konus(f"{dil_etiketi} çevirisi: {ceviri}")
    except Exception:
        konus("Çeviri yapamadım, internet bağlantını kontrol et.")
