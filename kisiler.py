# Bu dosya Friday'in Google Kişiler (People API) entegrasyonunu içerir.
# İsme göre kişi arar ve e-posta adresini döndürür.

from googleapiclient.discovery import build

from google_kimlik import _giris_yap

_servis = None


def _people_servisi():
    global _servis
    if _servis is None:
        _servis = build("people", "v1", credentials=_giris_yap())
    return _servis


def kisi_mail_bul(isim: str) -> str | None:
    """
    Google Kişiler'de isim ile arama yapar.

    isim   : aranacak kişi adı (tam veya kısmi)
    Dönüş  : bulunan ilk kişinin e-posta adresi, bulunamazsa None
    """
    try:
        sp = _people_servisi()

        # searchContacts: kişi adı, soyadı veya e-posta adresinde arar
        sonuc = sp.people().searchContacts(
            query=isim,
            readMask="names,emailAddresses",
        ).execute()

        kisiler = sonuc.get("results", [])
        if not kisiler:
            return None

        # İlk eşleşmenin birincil e-posta adresini al
        kisi    = kisiler[0].get("person", {})
        adresler = kisi.get("emailAddresses", [])
        if not adresler:
            return None

        return adresler[0].get("value")

    except Exception:
        return None
