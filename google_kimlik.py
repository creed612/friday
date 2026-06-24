# Bu dosya tüm Google API servisleri için merkezi kimlik doğrulamasını sağlar.
# İlk çalıştırmada tarayıcıda Google girişi açılır ve token.json oluşturulur.
# Sonraki çalıştırmalarda token.json'dan okunur; süresi dolmuşsa sessizce yenilenir.
# Tüm servisler (Takvim, Gmail, Kişiler, Drive) bu tek token'ı paylaşır.

import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Tüm servislerin birleşik izin kapsamı.
# Token bir kez oluşturulunca tüm bu servislere erişim sağlanır.
SCOPES = [
    # calendar.events: takvim etkinliklerini OKUMA + YAZMA (ekleme/silme) kapsar.
    # (Eski salt-okunur calendar.readonly de bırakıldı; events onu da içerir.)
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Kimlik dosyaları proje kök klasöründe aranır
_PROJE_KLASORU     = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_DOSYASI = os.path.join(_PROJE_KLASORU, "credentials.json")
TOKEN_DOSYASI       = os.path.join(_PROJE_KLASORU, "token.json")


def _giris_yap() -> Credentials:
    """
    Geçerli Google API kimlik bilgisini döndürür.

    Sırasıyla şunu dener:
    1. token.json varsa yükle ve tüm scope'larla doğrula.
    2. Token süresi dolmuş ama yenilenebilirse sessizce yenile.
    3. Hiç token yoksa tarayıcıda OAuth akışı başlat.

    Yeni veya yenilenmiş token her durumda token.json'a yazılır.
    """
    kimlik = None

    if os.path.exists(TOKEN_DOSYASI):
        kimlik = Credentials.from_authorized_user_file(TOKEN_DOSYASI, SCOPES)

    if not kimlik or not kimlik.valid:
        if kimlik and kimlik.expired and kimlik.refresh_token:
            # Mevcut token'ı sessizce yenile (kullanıcı etkileşimi gerekmez)
            kimlik.refresh(Request())
        else:
            # İlk giriş: tarayıcı açılır, kullanıcı izin verir
            akis = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_DOSYASI, SCOPES
            )
            # port=0 → sistem boş bir port seçer, 8080/8888 çakışmalarını önler
            kimlik = akis.run_local_server(port=0)

        with open(TOKEN_DOSYASI, "w", encoding="utf-8") as dosya:
            dosya.write(kimlik.to_json())

    return kimlik
