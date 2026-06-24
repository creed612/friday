# Bu dosya Friday'in hava durumu özelliğini içerir.
# Konum artık IP tabanlı değil; önce metinden şehir adı tespit edilir,
# bulunamazsa kaydedilmiş şehir kullanılır, o da yoksa kullanıcıdan sorulur.
# Koordinat tespiti için Open-Meteo'nun ücretsiz Geocoding API'si kullanılır.

import requests
from pathlib import Path

from ses import konus, komut_dinle, yaz


# Kayıtlı şehir bilgisinin tutulduğu dosya (programla aynı dizinde)
_SEHIR_KAYDI = Path(__file__).parent / "sehir_kaydi.txt"

# ── TÜRKİYE'NİN 81 İLİ (küçük harf, eşleştirme için) ───────────────────────
# Metinde bu isimlerden biri geçiyorsa o il kullanılır.
# NOT: "ağrı" Türkçede "acı/ağrı" anlamına da gelir; "ordu" "asker birliği"
# anlamına da gelir. Hava durumu bağlamında yanlış eşleşme pratikte nadirdir.
_ILLER = [
    "adana", "adıyaman", "afyonkarahisar", "ağrı", "aksaray", "amasya",
    "ankara", "antalya", "ardahan", "artvin", "aydın", "balıkesir",
    "bartın", "batman", "bayburt", "bilecik", "bingöl", "bitlis",
    "bolu", "burdur", "bursa", "çanakkale", "çankırı", "çorum",
    "denizli", "diyarbakır", "düzce", "edirne", "elazığ", "erzincan",
    "erzurum", "eskişehir", "gaziantep", "giresun", "gümüşhane",
    "hakkari", "hatay", "ıgdır", "isparta", "istanbul", "izmir",
    "kahramanmaraş", "karabük", "karaman", "kars", "kastamonu",
    "kayseri", "kilis", "kırıkkale", "kırklareli", "kırşehir",
    "kocaeli", "konya", "kütahya", "malatya", "manisa", "mardin",
    "mersin", "muğla", "muş", "nevşehir", "niğde", "ordu",
    "osmaniye", "rize", "sakarya", "samsun", "siirt", "sinop",
    "sivas", "şanlıurfa", "şırnak", "tekirdağ", "tokat", "trabzon",
    "tunceli", "uşak", "van", "yalova", "yozgat", "zonguldak",
]
# Sözlük en uzun eşleşmeyi garantilemek için uzunluğa göre sıralanmış.
# "kahramanmaraş" önce gelir, "maraş" ona takma ad olarak ayrıca kontrol edilir.
_ILLER_SIRASINDA = sorted(_ILLER, key=len, reverse=True)

# Kullanıcının söyleyebileceği takma adlar → geocoding'e gönderilecek resmi isim
_TAKMA_ADLAR = {
    "urfa":         "şanlıurfa",
    "antep":        "gaziantep",
    "afyon":        "afyonkarahisar",
    "maraş":        "kahramanmaraş",
    "k.maraş":      "kahramanmaraş",
    "izmit":        "kocaeli",
    "adapazarı":    "sakarya",
    "antakya":      "hatay",
    "iskenderun":   "hatay",
    "iğdır":        "ıgdır",   # yaygın yazım farklılığı
}


# ── ŞEHIR KAYIT / OKUMA ───────────────────────────────────────────────────────

def _sehir_kaydet(sehir: str):
    # Şehir adını hem sehir_kaydi.txt'ye hem hafiza.json'a yazar.
    # İki kaynağı senkron tutmak için her ikisine de yazılır.
    _sehir = sehir.strip().lower()
    _SEHIR_KAYDI.write_text(_sehir, encoding="utf-8")
    try:
        from hafiza import bilgi_kaydet
        bilgi_kaydet("sehir", _sehir)
    except Exception:
        pass  # hafiza.py yoksa sehir_kaydi.txt yeterli


def _sehir_oku() -> str | None:
    # Kaydedilmiş şehri döndürür.
    # Önce hafiza.json'a bakar (tek kaynak doğruluğu); yoksa sehir_kaydi.txt'ye düşer.
    try:
        from hafiza import bilgi_getir
        sehir = bilgi_getir("sehir")
        if sehir:
            return sehir
    except Exception:
        pass
    # Eski sürüm uyumluluğu — sehir_kaydi.txt hâlâ desteklenir
    if _SEHIR_KAYDI.exists():
        icerik = _SEHIR_KAYDI.read_text(encoding="utf-8").strip()
        return icerik if icerik else None
    return None


def _sehir_sil():
    # Kaydı hem sehir_kaydi.txt'den hem hafiza.json'dan sıfırlar.
    if _SEHIR_KAYDI.exists():
        _SEHIR_KAYDI.unlink()
    try:
        from hafiza import bilgi_kaydet
        bilgi_kaydet("sehir", None)
    except Exception:
        pass


# ── METİNDEN ŞEHİR ÇIKARMA ───────────────────────────────────────────────────

def _metinden_sehir_bul(metin: str) -> str | None:
    # Verilen metinde Türkiye illerinden birinin adı geçiyor mu kontrol eder.
    # Takma adlar (urfa, antep...) önce kontrol edilir; ardından resmi isimler.
    metin_k = metin.lower()

    # Takma adları kontrol et
    for takma, resmi in _TAKMA_ADLAR.items():
        if takma in metin_k:
            return resmi

    # 81 il listesini kontrol et (uzun isimler önce)
    for il in _ILLER_SIRASINDA:
        if il in metin_k:
            return il

    return None


# ── GEOCODING (ŞEHİR ADI → KOORDİNAT) ───────────────────────────────────────

def _koordinat_bul(sehir: str) -> tuple[float, float] | None:
    # Open-Meteo'nun ücretsiz Geocoding API'siyle şehir adını koordinata çevirir.
    # API anahtarı gerektirmez.
    url = "https://geocoding-api.open-meteo.com/v1/search"
    parametreler = {"name": sehir, "count": 1, "language": "tr"}
    cevap = requests.get(url, params=parametreler, timeout=5)
    veri = cevap.json()
    sonuclar = veri.get("results", [])
    if not sonuclar:
        return None
    return float(sonuclar[0]["latitude"]), float(sonuclar[0]["longitude"])


# ── HAVA VERİSİ ÇEKME ────────────────────────────────────────────────────────

def _koordinattan_hava_al(enlem: float, boylam: float) -> tuple[float, int]:
    # Open-Meteo forecast API'den ANLIK hava durumu çeker.
    #
    # MODERN "current" bloğu kullanılır (eski "current_weather=true" DEĞİL):
    #   - current=temperature_2m,weather_code → gerçek ANLIK 2m sıcaklığı (15 dk granüler)
    #   - timezone=auto → zaman damgası YEREL saatte (eski yöntem UTC veriyordu)
    # Bu, "yanlış/eski değer" sorununu giderir; hissedilen (apparent) DEĞİL,
    # gerçek hava sıcaklığı (temperature_2m) okunur.
    # Her sorguda taze veri çekilir (kod tarafında önbellek YOK).
    parametreler = {
        "latitude":  enlem,
        "longitude": boylam,
        "current":   "temperature_2m,weather_code",
        "timezone":  "auto",
    }
    cevap = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=parametreler,
        timeout=5,
    )
    veri  = cevap.json()
    anlik = veri["current"]
    # DEBUG: API'den dönen ham anlık veriyi yazdır (doğru alanı okuduğumuzu doğrula)
    print(f"[HAVA] ham current = {anlik}")
    return float(anlik["temperature_2m"]), int(anlik["weather_code"])


# ── WMO HAVA KODU YORUMLAMA ───────────────────────────────────────────────────

def hava_kodu_yorumla(kod: int) -> str:
    # WMO (Dünya Meteoroloji Örgütü) hava kodlarını Türkçe açıklamaya çevirir.
    if kod == 0:            return "açık"
    if 1 <= kod <= 3:       return "parçalı bulutlu"
    if kod in (45, 48):     return "sisli"
    if 51 <= kod <= 55:     return "çiseleyen yağmur"
    if 56 <= kod <= 57:     return "dondurucu çisenti"
    if 61 <= kod <= 65:     return "yağmurlu"
    if 66 <= kod <= 67:     return "dondurucu yağmur"
    if 71 <= kod <= 75:     return "karlı"
    if kod == 77:           return "kar taneli"
    if 80 <= kod <= 82:     return "sağanak yağışlı"
    if 85 <= kod <= 86:     return "kar sağanağı"
    if kod in (95, 96, 99): return "fırtınalı"
    return "değişken"


def yuruyus_onerisi(sicaklik: float, hava_kodu: int) -> str:
    # Sıcaklık ve hava koduna göre yürüyüş önerisi üretir.
    olumsuz = set(range(51, 68)) | set(range(71, 78)) | set(range(80, 87)) | {95, 96, 99}
    if hava_kodu not in olumsuz and 10 <= sicaklik <= 28:
        return "Yürüyüş için hava çok uygun."
    if hava_kodu in olumsuz:
        return "Hava yürüyüş için pek uygun değil."
    if sicaklik < 10:
        return "Hava oldukça soğuk, yürüyüş için pek uygun değil."
    return "Hava oldukça sıcak, yürüyüş için dikkatli olunmalı."


# ── ANA FONKSİYONLAR ─────────────────────────────────────────────────────────

def sehir_sifirla(mod: str):
    # "şehir değiştir" / "konumu değiştir" komutunda çağrılır.
    # Mevcut kaydı siler ve kullanıcıdan yeni şehri ister.
    _sehir_sil()
    konus("Konumunu sıfırladım. Yeni şehrini söyle.")
    yanit = komut_dinle() if mod == "sesli" else yaz().lower().strip()
    if not yanit:
        konus("Şehir alınamadı. Bir dahaki hava durumu sorgusunda tekrar sorarım.")
        return
    # Yanıttan şehir adını çıkar; bulamazsa ham yanıtı şehir olarak kullan
    sehir = _metinden_sehir_bul(yanit) or yanit.strip()
    _sehir_kaydet(sehir)
    konus(f"Konumun {sehir.title()} olarak kaydedildi.")


def hava_durumu_soyle(metin: str, mod: str):
    # 1. Adım: gelen metinden şehir adı çıkar (ör. "istanbul hava nasıl")
    # 2. Adım: metinde şehir yoksa kaydedilmiş şehri kullan
    # 3. Adım: hiçbir kaynak yoksa kullanıcıdan sor ve kaydet
    # 4. Adım: Open-Meteo Geocoding ile koordinat bul, hava verisini çek
    try:
        # ADIM 1: Metinden şehir tespiti
        sehir = _metinden_sehir_bul(metin)
        if sehir:
            # Kullanıcı şehir adı belirttiyse kaydet — bir sonraki varsayılan olsun
            _sehir_kaydet(sehir)

        # ADIM 2: Kaydedilmiş şehir
        if not sehir:
            sehir = _sehir_oku()

        # ADIM 3: Hiç kaynak yok → kullanıcıdan sor
        if not sehir:
            konus("Hangi şehirdesin?")
            yanit = komut_dinle() if mod == "sesli" else yaz().lower().strip()
            if not yanit:
                konus("Şehir alınamadı.")
                return
            sehir = _metinden_sehir_bul(yanit) or yanit.strip()
            _sehir_kaydet(sehir)

        # ADIM 4: Koordinat bul ve hava verisini çek
        koordinatlar = _koordinat_bul(sehir)
        if not koordinatlar:
            konus(f"{sehir.title()} için konum bilgisi bulunamadı. Şehir adını kontrol eder misin?")
            return

        enlem, boylam = koordinatlar
        sicaklik, hava_kodu = _koordinattan_hava_al(enlem, boylam)
        aciklama = hava_kodu_yorumla(hava_kodu)
        oneri    = yuruyus_onerisi(sicaklik, hava_kodu)

        mesaj = f"{sehir.title()} için hava durumu: {round(sicaklik)} derece, {aciklama}. {oneri}"
        konus(mesaj)

    except requests.exceptions.ConnectionError:
        konus("İnternet bağlantısı yok, hava durumuna ulaşamıyorum.")
    except Exception:
        konus("Hava durumu bilgisine şu an ulaşamıyorum.")
