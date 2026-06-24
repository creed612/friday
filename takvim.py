# Bu dosya Friday'in Google Takvim entegrasyonunu içerir.
# İlk çalıştırmada tarayıcıda Google girişi açılır ve token.json oluşturulur.
# Sonraki çalıştırmalarda token.json okunur, tekrar giriş gerekmez.

import datetime
import re

from googleapiclient.discovery import build
from dateparser.search import search_dates

from google_kimlik import _giris_yap
from ses import konus, komut_dinle, yaz

# Türkiye sabit UTC+3 (yaz saati yok) → API zaman damgalarında bu ofseti kullanırız.
_TR_OFSET = "+03:00"
_TR_ZAMAN_DILIMI = "Europe/Istanbul"

# Türkçe ay adları (1-12 → ad); tarih seslendirmede kullanılır.
_AYLAR = [
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

# dateparser ayarları — Türkçe, gelecek tarih tercihli (hatırlatıcı ile aynı).
_DP_AYAR = {"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False}

_AY_RE = r"(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)"


def _tarih_metni_normalle(metin: str) -> str:
    # dateparser Türkçe LOCATIVE ekini ("ağustosta", "15te") ve "saat 15" (dakikasız
    # → yıl sanıyor) kalıbını ANLAYAMIYOR. search_dates'e vermeden ÖNCE normalleştir:
    #   "30 ağustosta"   → "30 ağustos"
    #   "saat 15te"/"15 te"/"15'te" → "15:00"
    #   "saat 15:30"     → "15:30"
    m = metin.lower()
    # 1) Ay adından locative ekini at (ağustosta → ağustos, ağustos'ta → ağustos).
    #    ['’]? : Whisper bazen "ağustos'ta" diye apostrof koyuyor — onu da yakala.
    m = re.sub(_AY_RE + r"['’]?(ta|te|da|de)\b", r"\1", m)
    # 2) Saatten sonra locative ek: "15te"/"15'te"/"15 te" → "15:00" (saat kuralından ÖNCE)
    m = re.sub(r"\b(\d{1,2})\s*['’]?\s*(te|ta|de|da)\b", r"\1:00", m)
    # 3) "saat 15" → "15:00", "saat 15:30" → "15:30" ("saat" kelimesini kaldır)
    def _saat_sub(mo):
        h, dk = mo.group(1), mo.group(2)
        return f"{h}:{dk}" if dk else f"{h}:00"
    m = re.sub(r"saat\s+(\d{1,2})(?::?(\d{2}))?", _saat_sub, m)
    return m


# Singleton: Google Calendar API istemcisi bir kez oluşturulur, sonra yeniden kullanılır.
# gmail_yonetimi.py'deki _servis ile aynı pattern — her çağrıda build() ~50ms tasarruf.
_servis = None


def _servis_al():
    """Calendar servisini döner; ilk çağrıda oluşturur, sonrakilerde önbellekten verir."""
    global _servis
    if _servis is None:
        kimlik = _giris_yap()
        _servis = build("calendar", "v3", credentials=kimlik)
    return _servis


def gunluk_etkinlikleri_getir():
    # Bugünün takvim etkinliklerini Google Calendar API'den çeker.
    # Dönüş: [{"baslik": str, "saat": str}, ...] listesi
    #         Etkinlik yoksa boş liste döner.

    servis = _servis_al()

    # Bugünün başlangıç ve bitiş zamanlarını UTC formatında oluştur
    bugun = datetime.date.today()
    baslangic = datetime.datetime(bugun.year, bugun.month, bugun.day, 0, 0, 0)
    bitis = datetime.datetime(bugun.year, bugun.month, bugun.day, 23, 59, 59)

    # RFC 3339 formatı Google API'nin beklediği format (timezone bilgisi ekli)
    baslangic_str = baslangic.isoformat() + "Z"   # "Z" = UTC
    bitis_str = bitis.isoformat() + "Z"

    # API isteği: birincil takvimden bugünün etkinliklerini saat sırasına göre al
    sonuc = servis.events().list(
        calendarId="primary",
        timeMin=baslangic_str,
        timeMax=bitis_str,
        singleEvents=True,        # Tekrarlanan etkinlikleri ayrı ayrı göster
        orderBy="startTime",      # Saat sırasına göre sırala
    ).execute()

    etkinlikler = sonuc.get("items", [])
    liste = []

    for etkinlik in etkinlikler:
        baslik = etkinlik.get("summary", "İsimsiz Etkinlik")

        # Etkinliğin başlangıç saatini al
        # "dateTime" varsa saatli randevu, sadece "date" varsa tüm gün etkinliği
        baslangic_bilgi = etkinlik["start"]
        if "dateTime" in baslangic_bilgi:
            # "2024-06-17T14:00:00+03:00" formatından sadece saat:dakika al
            saat_str = baslangic_bilgi["dateTime"][11:16]
        else:
            # Tüm gün etkinliği — saat yok
            saat_str = "tüm gün"

        liste.append({"baslik": baslik, "saat": saat_str})

    return liste


def takvimi_soyle(mod):
    # Bugünün etkinliklerini çekip Friday'in sesli/yazılı olarak söylemesini sağlar.
    # Hata durumunda kullanıcıyı bilgilendirir.
    try:
        etkinlikler = gunluk_etkinlikleri_getir()

        if not etkinlikler:
            konus("Bugün takviminde herhangi bir etkinlik yok.")
            return

        # Etkinlik sayısını belirt ve hepsini sırayla oku
        adet = len(etkinlikler)
        cumle = f"Bugün takviminde {adet} etkinliğin var: "

        parcalar = []
        for e in etkinlikler:
            if e["saat"] == "tüm gün":
                parcalar.append(f"tüm gün {e['baslik']}")
            else:
                parcalar.append(f"saat {e['saat']}'de {e['baslik']}")

        # Virgülle birleştir, son parçadan önce "ve" koy — daha doğal bir söylem
        if len(parcalar) == 1:
            cumle += parcalar[0] + "."
        else:
            cumle += ", ".join(parcalar[:-1]) + " ve " + parcalar[-1] + "."

        konus(cumle)

    except FileNotFoundError:
        # credentials.json bulunamazsa
        konus("Google Takvim bağlantısı için kimlik dosyası bulunamadı.")
    except Exception:
        # Ağ hatası, API hatası veya başka bir sorun
        konus("Takvim bilgisine şu an ulaşamıyorum.")


# ══════════════════════════════════════════════════════════════════════════════
#  ETKİNLİK EKLEME + BELİRLİ TARİH SORGULAMA
# ══════════════════════════════════════════════════════════════════════════════

def _tarih_turkce(tarih: datetime.date) -> str:
    # Tarihi doğal Türkçe ifadeye çevirir: "Bugün" / "Yarın" / "30 Ağustos".
    bugun = datetime.date.today()
    if tarih == bugun:
        return "Bugün"
    if tarih == bugun + datetime.timedelta(days=1):
        return "Yarın"
    return f"{tarih.day} {_AYLAR[tarih.month]}"


def _saat_belirtilmis_mi(metin: str, tarih_ifadesi: str) -> bool:
    # Metinde gerçek bir SAAT geçiyor mu? (dateparser saat yoksa şu anki saatle
    # doldurduğu için parse edilen saate güvenemeyiz; metne bakarız.)
    iz = (metin + " " + (tarih_ifadesi or "")).lower()
    if re.search(r"\d{1,2}[:.]\d{2}", iz):          # 15:30, 9.45
        return True
    if "saat" in iz:                                 # "saat 15"
        return True
    if any(k in iz for k in ("öğlen", "öğle", "akşam", "sabah", "gece", "buçuk", "öğleden")):
        return True
    # "15'te", "15 te", "9'da" → sayı + yönelme eki (saat ima eder)
    if re.search(r"\b\d{1,2}\s*['’]?\s*(te|ta|de|da)\b", iz):
        return True
    return False


def _baslik_ayikla(metin: str, tarih_ifadeleri: list) -> str:
    # Etkinlik başlığını çıkarır: tarih ifadelerini ve komut kelimelerini temizler.
    # "takvime 30 ağustosta doktor randevusu ekle" → "doktor randevusu"
    baslik = metin
    for ifade in tarih_ifadeleri:
        if ifade:
            baslik = baslik.replace(ifade, " ")
    # Saat kalıntılarını at ("15:00" gibi — tarih ifadesinde yakalanmamış olabilir)
    baslik = re.sub(r"\b\d{1,2}:\d{2}\b", " ", baslik)
    # Komut/dolgu kelimelerini at (UZUN ifadeler önce — "takvime ekle" gibi)
    for kelime in ("takvimime", "takvime", "takvimde", "takvim",
                   "etkinlik olarak", "etkinlik", "oluştur", "ekler misin",
                   "ekleyebilir misin", "ekle", "kaydet", "koy", "olarak",
                   "diye", "adında", "adıyla", "saat"):
        baslik = re.sub(rf"\b{re.escape(kelime)}\b", " ", baslik, flags=re.IGNORECASE)
    baslik = " ".join(baslik.split()).strip(" ,.-'\"")
    # Normalleştirme küçük harfe çevirdiği için ilk harfi büyüt (takvim başlığı görünümü)
    if baslik:
        baslik = baslik[0].upper() + baslik[1:]
    return baslik


def etkinlik_ekle(metin: str, mod: str):
    # Metinden tarih/saat ve başlık çıkarıp Google Takvim'e etkinlik ekler.
    # Saat varsa 1 saatlik randevu; yoksa tüm gün etkinliği.
    try:
        # Normalleştir: "30 ağustosta"/"saat 15te" → dateparser'ın anladığı biçim.
        norm = _tarih_metni_normalle(metin)
        sonuclar = search_dates(norm, languages=["tr"], settings=_DP_AYAR)
        if not sonuclar:
            konus("Etkinliğin tarihini anlayamadım. "
                  "Örneğin 'takvime yarın saat 15 te toplantı ekle' diyebilirsin.")
            return

        tarih_ifadesi, zaman = sonuclar[0]
        if zaman is None:
            konus("Tarihi anlayamadım, tekrar dener misin?")
            return

        # Saat tespiti ORİJİNAL metinden ("saat", "te" ipuçları orada).
        saatli = _saat_belirtilmis_mi(metin, tarih_ifadesi)
        # Başlık NORMALLEŞTİRİLMİŞ metinden ayıklanır (tarih ifadeleri orada eşleşir).
        baslik = _baslik_ayikla(norm, [s[0] for s in sonuclar])
        if not baslik:
            baslik = "Etkinlik"

        servis = _servis_al()

        if saatli:
            # Saatli randevu: 1 saat sürer. Türkiye ofsetiyle (+03:00) yaz.
            bas = zaman.replace(second=0, microsecond=0)
            bit = bas + datetime.timedelta(hours=1)
            govde = {
                "summary": baslik,
                "start": {"dateTime": bas.strftime("%Y-%m-%dT%H:%M:%S") + _TR_OFSET,
                          "timeZone": _TR_ZAMAN_DILIMI},
                "end":   {"dateTime": bit.strftime("%Y-%m-%dT%H:%M:%S") + _TR_OFSET,
                          "timeZone": _TR_ZAMAN_DILIMI},
            }
            zaman_str = f"{_tarih_turkce(bas.date())} saat {bas.strftime('%H:%M')}"
        else:
            # Tüm gün etkinliği: start.date / end.date (end HARİÇ → ertesi gün).
            gun = zaman.date()
            govde = {
                "summary": baslik,
                "start": {"date": gun.isoformat()},
                "end":   {"date": (gun + datetime.timedelta(days=1)).isoformat()},
            }
            zaman_str = f"{_tarih_turkce(gun)} (tüm gün)"

        olusan = servis.events().insert(calendarId="primary", body=govde).execute()

        # DOĞRULAMA: insert dönüşünde id varsa etkinlik gerçekten oluşmuştur.
        if olusan and olusan.get("id"):
            konus(f"{baslik} etkinliğini {zaman_str} olarak takvime ekledim.")
        else:
            konus("Etkinliği eklemeyi denedim ama oluştuğunu doğrulayamadım.")

    except FileNotFoundError:
        konus("Google Takvim kimlik dosyası bulunamadı.")
    except Exception as e:
        print(f"[TAKVIM] etkinlik_ekle hatası: {e}")
        konus("Etkinliği takvime ekleyemedim. Takvim yazma iznini onayladığından emin ol.")


def belirli_tarih_etkinlikleri(metin: str, mod: str):
    # Metinde belirtilen TARİHİN etkinliklerini listeler; tarih yoksa bugünü kullanır.
    # (Eski hata: hangi tarih sorulursa sorulsun "bugün etkinlik yok" diyordu.)
    try:
        sonuclar = search_dates(_tarih_metni_normalle(metin), languages=["tr"], settings=_DP_AYAR)
        if sonuclar and sonuclar[0][1] is not None:
            hedef = sonuclar[0][1].date()
        else:
            hedef = datetime.date.today()

        # O günün başı-sonu, Türkiye ofsetiyle (doğru gün sınırları)
        bas = f"{hedef.isoformat()}T00:00:00{_TR_OFSET}"
        bit = f"{hedef.isoformat()}T23:59:59{_TR_OFSET}"

        servis = _servis_al()
        sonuc = servis.events().list(
            calendarId="primary",
            timeMin=bas, timeMax=bit,
            singleEvents=True, orderBy="startTime",
        ).execute()
        etkinlikler = sonuc.get("items", [])

        tarih_str = _tarih_turkce(hedef)

        if not etkinlikler:
            # DOĞRU tarihi söyle — artık "bugün" demiyor
            konus(f"{tarih_str} takviminde etkinlik yok.")
            return

        parcalar = []
        for e in etkinlikler:
            baslik = e.get("summary", "İsimsiz Etkinlik")
            bas_bilgi = e["start"]
            if "dateTime" in bas_bilgi:
                saat = bas_bilgi["dateTime"][11:16]
                parcalar.append(f"saat {saat}'de {baslik}")
            else:
                parcalar.append(f"tüm gün {baslik}")

        if len(parcalar) == 1:
            icerik = parcalar[0]
        else:
            icerik = ", ".join(parcalar[:-1]) + " ve " + parcalar[-1]

        konus(f"{tarih_str} takviminde {len(etkinlikler)} etkinliğin var: {icerik}.")

    except FileNotFoundError:
        konus("Google Takvim kimlik dosyası bulunamadı.")
    except Exception as e:
        print(f"[TAKVIM] belirli_tarih_etkinlikleri hatası: {e}")
        konus("Takvim bilgisine şu an ulaşamıyorum.")
