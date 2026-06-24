# Bu dosya Friday'in Spotify kontrol özelliğini içerir.
# spotipy kütüphanesi aracılığıyla Spotify Web API'sine bağlanır.
# İlk çalıştırmada tarayıcı açılır, Spotify hesabıyla giriş yapılır;
# sonraki çalıştırmalarda .spotify_cache dosyasından token okunur.
#
# HATA YÖNETİMİ: Tüm fonksiyonlar SpotifyException yakalar. Program asla çökmez.

import re
import os
import time
import json
import random
import subprocess        # Spotify uygulamasını açmak için (cihaz yoksa)
import requests          # ağ (offline) hatalarını yakalamak için
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from rapidfuzz import fuzz

# İnternet yokken spotipy/requests bu hatayı fırlatır (NameResolutionError, timeout vb.).
# SpotifyException DEĞİLDİR → ayrıca yakalanmazsa programı ÇÖKERTİR (yaşanan hata).
_AG_HATASI = requests.exceptions.RequestException

from spotify_ayarlari import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from ses import konus

_CACHE_YOLU = ".spotify_cache"

# İzin kapsamı: çalma durumunu oku/değiştir, kütüphane ve playlist işlemleri
_SCOPE = (
    "user-modify-playback-state user-read-playback-state user-read-currently-playing "
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-private playlist-modify-public "
    "user-library-read user-library-modify "
    "user-top-read user-read-recently-played"
)

# Singleton: Spotify nesnesi bir kez oluşturulur, sonraki çağrılarda yeniden kullanılır
_sp = None


def _scope_yeterli(mevcut_scope: str) -> bool:
    # Önbellekteki token'ın scope'u, gerekli TÜM scope'ları kapsıyor mu?
    gerekli = set(_SCOPE.split())
    var = set((mevcut_scope or "").split())
    return gerekli.issubset(var)


def _onbellek_scope_kontrol():
    # GÜVENLİK AĞI: .spotify_cache'teki token tüm gerekli scope'ları kapsamıyorsa
    # (ileride yeni scope eklersek bu olabilir) dosyayı siler → SpotifyOAuth bir
    # sonraki sefer tam scope ile yeniden yetkilendirir (tarayıcı açılır).
    # NOT: Token zaten tüm scope'ları kapsıyorsa bu fonksiyon HİÇBİR ŞEY yapmaz
    #      (gereksiz yere yeniden giriş istemez).
    if not os.path.exists(_CACHE_YOLU):
        return
    try:
        with open(_CACHE_YOLU, "r", encoding="utf-8") as f:
            veri = json.load(f)
        if not _scope_yeterli(veri.get("scope", "")):
            print("[Spotify] Önbellek token'ı eksik scope içeriyor → "
                  ".spotify_cache siliniyor, bir sonraki komutta yeniden giriş gerekecek.")
            os.remove(_CACHE_YOLU)
    except Exception as e:
        print(f"[Spotify] Önbellek scope kontrolü hatası: {e}")


def _get_sp():
    # Spotify istemcisini döndürür; henüz oluşturulmadıysa oluşturur.
    # SpotifyOAuth token süresi dolduğunda (401) otomatik yeniler.
    global _sp
    if _sp is None:
        # Token oluşturmadan ÖNCE scope yeterliliğini denetle (eksikse cache'i sil).
        _onbellek_scope_kontrol()
        _sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=_SCOPE,
                cache_path=_CACHE_YOLU,
                open_browser=True,
            ),
            # Offline'da hızlı başarısız ol: 1 deneme + 8 sn zaman aşımı.
            # (Varsayılan 3 retry, internet yokken uzun uzun bekletiyordu.)
            retries=1,
            requests_timeout=8,
        )
    return _sp


# ── YARDIMCI FONKSİYONLAR ───────────────────────────────────────────────────

def _hata_isle(hata, varsayilan: str = "Spotify ile bir sorun oluştu."):
    # Spotify hatalarını sınıflandırıp Türkçe mesaj verir.
    # ÖNCE ağ hatası: internet yoksa (NameResolutionError/timeout) bu bir
    # SpotifyException DEĞİLDİR; en başta yakala (yoksa http_status=None → varsayılan).
    if isinstance(hata, _AG_HATASI):
        print(f"[Spotify] Ağ hatası (offline): {hata}")
        konus("İnternet bağlantısı yok, Spotify'a şu an ulaşamıyorum.")
        return
    # 401: token süresi dolmuş (SpotifyOAuth normalde otomatik yeniler, nadiren düşülür)
    # 403: İKİ farklı durum olabilir — gerçek hatayı mesajdan ayırt et:
    #      (a) "Restriction violated" → ÇALMA KISITI (zaten çalıyor / Free hesap /
    #          cihaz kısıtı). Yetki sorunu DEĞİL.
    #      (b) diğer 403 → genelde yetki/scope; .spotify_cache silinip yeniden giriş gerekir.
    # 404: aktif cihaz yok veya kaynak bulunamadı
    kod = getattr(hata, "http_status", None)
    mesaj = (str(getattr(hata, "msg", "") or "") + " " + str(hata)).lower()
    # Teşhis için gerçek hata metnini konsola yaz (sesli okuma değil)
    print(f"[Spotify] Hata kodu={kod} mesaj={mesaj!r}")

    if kod == 401:
        konus("Spotify oturumunun süresi dolmuş. Friday'i yeniden başlatman gerekebilir.")
    elif kod == 403:
        if "restriction" in mesaj:
            konus(
                "Spotify bu komutu şu an uygulayamadı. "
                "Aktif bir cihazda çalma başlatılmış olmalı, ya da bu işlem hesabında kısıtlı."
            )
        else:
            konus(
                "Spotify yetkimi yenilemem gerekiyor. "
                "Friday'i kapat, .spotify_cache dosyasını sil ve yeniden başlatıp "
                "tarayıcıdan tüm izinleri onayla."
            )
    elif kod == 404:
        konus("Spotify aktif cihaz bulamadı. Spotify uygulamasını aç ve hazır hale getir.")
    else:
        konus(varsayilan)


def _spotify_uygulamasini_ac() -> bool:
    # Spotify masaüstü uygulamasını açar (cihaz bulunamadığında).
    # "spotify:" URI protokolü hem normal hem Microsoft Store sürümünde çalışır.
    # Başarısızsa bilinen kurulum yollarından Spotify.exe denenir.
    try:
        os.startfile("spotify:")   # protokol handler → Spotify uygulamasını başlatır
        return True
    except Exception:
        pass
    olasi_yollar = [
        os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
        r"C:\Program Files\WindowsApps\Spotify.exe",
    ]
    for yol in olasi_yollar:
        if yol and os.path.exists(yol):
            try:
                subprocess.Popen([yol])
                return True
            except Exception:
                pass
    return False


def _cihaz_bekle(sp, sure_saniye: int = 12) -> list:
    # Spotify açıldıktan sonra cihaz Spotify Connect'e kaydolana kadar bekler (poll).
    # En fazla sure_saniye boyunca her ~1.5 sn'de bir cihaz listesini kontrol eder.
    bitis = time.time() + sure_saniye
    while time.time() < bitis:
        time.sleep(1.5)
        try:
            cihazlar = sp.devices().get("devices", [])
            if cihazlar:
                return cihazlar
        except Exception:
            pass   # geçici hata → beklemeye devam et
    return []


def _aktif_cihaz_var_mi(sp, otomatik_ac: bool = True) -> bool:
    # Çalma yapılabilecek aktif bir Spotify cihazı olup olmadığını kontrol eder.
    #
    # Adımlar:
    #   1. sp.devices() ile cihaz listesini al
    #   2. Hiç cihaz yoksa → Spotify'ı KENDİ AÇ, cihaz kaydolana kadar bekle
    #   3. Aktif cihaz varsa → True döndür
    #   4. Cihaz var ama aktif değilse → ilk cihaza playback aktar, True döndür
    try:
        cihazlar = sp.devices().get("devices", [])

        # Hiç cihaz yok → Spotify kapalı olabilir; uygulamayı aç ve cihazı bekle.
        if not cihazlar and otomatik_ac:
            if _spotify_uygulamasini_ac():
                konus("Spotify kapalıydı, açıyorum, bir saniye.")
                cihazlar = _cihaz_bekle(sp, sure_saniye=12)

        if not cihazlar:
            konus(
                "Spotify'ı bir cihazda hazır hale getiremedim. "
                "Spotify uygulamasını açıp tekrar dener misin?"
            )
            return False

        # Zaten aktif olan cihaz varsa hızlıca dön
        if any(c["is_active"] for c in cihazlar):
            return True

        # Cihaz var ama aktif değil — odağı ilk cihaza taşı.
        # force_play=False: mevcut duraklı/çalıyor durumunu bozmaz.
        ilk_id = cihazlar[0]["id"]
        try:
            sp.transfer_playback(ilk_id, force_play=False)
            # Aktarım sonrası cihazın hazır olması için kısa bekleme (yeni açılan client)
            time.sleep(1.0)
        except SpotifyException:
            # Transfer başarısız olsa bile devam et; sonraki API çağrısı yine çalışabilir.
            pass
        return True

    except _AG_HATASI as e:
        # İnternet yok → kullanıcıya bildir, False döndür (çağıran sessizce çıkar, çökme yok).
        _hata_isle(e)
        return False
    except SpotifyException:
        return False


def _mevcut_calanik(sp) -> dict | None:
    # Şu an çalan parçanın bilgilerini döndürür.
    # Dönüş: {"isim", "sanatci", "uri", "id"} sözlüğü; çalma yoksa None.
    try:
        durum = sp.current_playback()
        if not durum or not durum.get("item"):
            return None
        parca = durum["item"]
        return {
            "isim":    parca["name"],
            "sanatci": parca["artists"][0]["name"],
            "uri":     parca["uri"],
            "id":      parca["id"],
        }
    except (SpotifyException, _AG_HATASI):
        # Ağ hatası dahil → None döndür (çağıran "bir şey çalmıyor" der, çökme yok)
        return None


def _begenilenleri_calistir(sp):
    # Kullanıcının beğendiği şarkıları (Liked Songs) karıştırarak çalar.
    #
    # ÖNEMLİ: "spotify:user:{id}:collection" context_uri'si ÇALIŞMIYOR — Spotify
    # Web API'si Liked Songs'u context olarak başlatmayı desteklemiyor (403/404).
    # DOĞRU yöntem: beğenilen şarkıların URI'lerini çekip uris=[...] ile çalmak.
    try:
        if not _aktif_cihaz_var_mi(sp):
            return

        # Beğenilen şarkıları çek (ilk 50 yeterli; çok daha fazlası gecikme yaratır)
        kayitli = sp.current_user_saved_tracks(limit=50)
        uriler = [
            it["track"]["uri"]
            for it in kayitli.get("items", [])
            if it.get("track") and it["track"].get("uri")
        ]

        if not uriler:
            konus("Beğendiğin şarkı bulamadım. Önce birkaç şarkı beğen, sonra tekrar dene.")
            return

        # Kendi tarafımızda karıştır (her seferinde farklı sıra) ve çal
        random.shuffle(uriler)
        sp.start_playback(uris=uriler)
        # Cihaz shuffle modunu da aç (sonraki geçişler de rastgele olsun) — başarısızsa önemsiz
        try:
            sp.shuffle(True)
        except SpotifyException:
            pass
        konus("Beğendiğin şarkılar karıştırılarak çalıyor.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Beğenilen şarkıları başlatamadım.")


# "bir şeyler çal" denince denenecek rastgele mood/popüler arama terimleri.
# Her seferinde farklı bir liste gelsin diye çeşitli; istediğin kadar ekleyebilirsin.
_RASTGELE_TERIMLER = [
    "türkçe pop", "pop hits", "top hits türkiye", "haftanın enleri", "chill",
    "rock classics", "yaz şarkıları", "party", "akustik", "rahatlatıcı",
    "enerjik", "lo-fi", "90lar türkçe", "yabancı pop", "en iyi şarkılar",
]


def _otomatik_calma(sp):
    # "bir şeyler çal" / "müzik çal" → Spotify'ın hazırladığı veya RASTGELE bir
    # playlist çalar (beğenilen şarkılar yerine taze/değişken içerik).
    # Birkaç yöntem sırayla denenir; Spotify bazı öneri uçlarını yeni uygulamalar
    # için kısıtladığından sağlam yedeklerle ilerlenir.
    if not _aktif_cihaz_var_mi(sp):
        return

    # YÖNTEM 1: Spotify'ın ÖNE ÇIKAN (editoryal) playlistleri — rastgele biri.
    try:
        veri = sp.featured_playlists(country="TR", limit=20)
        pls = [p for p in veri.get("playlists", {}).get("items", []) if p and p.get("uri")]
        if pls:
            secilen = random.choice(pls)
            sp.start_playback(context_uri=secilen["uri"])
            try:
                sp.shuffle(True)
            except SpotifyException:
                pass
            konus(f"{secilen['name']} çalıyor.")
            return
    except (SpotifyException, _AG_HATASI):
        pass   # bu uç kısıtlı/erişilemez olabilir → bir sonraki yöntemi dene

    # YÖNTEM 2: Rastgele bir mood/popüler terimle playlist ARA, çıkan listelerden birini çal.
    try:
        terim = random.choice(_RASTGELE_TERIMLER)
        print(f"[Spotify] Otomatik çalma araması: {terim!r}")
        veri = sp.search(q=terim, type="playlist", limit=10, market="TR")
        pls = [p for p in veri.get("playlists", {}).get("items", []) if p and p.get("uri")]
        if pls:
            secilen = random.choice(pls)
            sp.start_playback(context_uri=secilen["uri"])
            try:
                sp.shuffle(True)
            except SpotifyException:
                pass
            konus(f"{secilen['name']} çalıyor.")
            return
    except (SpotifyException, _AG_HATASI):
        pass

    # YÖNTEM 3 (son çare): beğenilen şarkıları karıştır.
    _begenilenleri_calistir(sp)


# ── ÇALMA YÖNETİMİ ─────────────────────────────────────────────────────────

# Çalma tetikleyici kelimeler (ilk kelime olarak gelir):
# Whisper bunları bazen farklı yazabilir (oynat→oant, çal→kal vb.)
_CALI_TETIKLEYICILER = ["çal", "kal", "oynat", "oyna", "oant", "oynayt", "başlat"]

# Genel müzik başlatma kalıpları — şarkı adı yok, sadece "müzik çal" gibi
_GENEL_MUZIK_KALIPLARI = [
    "müzik çal", "müzik başlat", "müzik oynat", "müzik aç",
    "biraz müzik", "bir şeyler çal", "müzik koy",
]


def calma_yonet(metin: str):
    # Komut metnini analiz edip doğru çalma eylemini seçer.
    #
    # Karar ağacı (sırayla):
    #   1. "devam et" varsa          → duraklatılmış şarkıyı sürdür
    #   2. Genel müzik kalıbı varsa  → beğenilen şarkıları karıştır ve çal
    #   3. Tetikleyici + içerik var  → sarki_calar(içerik)
    #   4. Sadece tetikleyici, içerik yok:
    #      - Duraklatılmış şarkı varsa → devam ettir
    #      - Yoksa                     → beğenilen şarkıları başlat
    sp = _get_sp()

    # 1. Devam et: duraklatılmış şarkıyı sürdür
    if "devam et" in metin:
        muzik_devam_et()
        return

    # 2. Genel müzik kalıpları: şarkı adı belirtilmemiş, sadece müzik isteği
    #    → Spotify'ın hazırladığı / rastgele bir playlist çal (beğenilenler değil).
    for kalip in _GENEL_MUZIK_KALIPLARI:
        if kalip in metin:
            _otomatik_calma(sp)
            return

    # 3. Tetikleyici kelimeden içerik çıkarmaya çalış.
    #    Format A: "çal [içerik]"           → tetikleyici başta
    #    Format B: "[içerik] çal"           → tetikleyici sonda
    #    Format C: "[içerik] çal [şeyler]"  → tetikleyici ortada, önündeki içerik
    icerik = None
    for tetik in _CALI_TETIKLEYICILER:
        # Format A: tetikleyici ilk kelime
        if metin.startswith(tetik + " "):
            icerik = metin[len(tetik):].strip()
            break
        # Format B/C: tetikleyici cümle içinde — solundaki metni al
        aralik = " " + tetik
        if metin.endswith(aralik) or (" " + tetik + " ") in metin:
            idx  = metin.rfind(aralik)
            once = metin[:idx].strip()
            if once and len(once) > 1:
                icerik = once
                break

    if icerik and len(icerik) > 1:
        sarki_calar(icerik)
        return

    # 4. İçerik bulunamadı — mevcut çalma durumuna bak
    try:
        durum = sp.current_playback()
        if durum and durum.get("is_playing") is False:
            # Duraklatılmış bir şarkı var → devam ettir
            muzik_devam_et()
        else:
            # Çalan bir şey yok → Spotify'ın hazırladığı/rastgele playlist çal
            _otomatik_calma(sp)
    except _AG_HATASI as e:
        # İnternet yok → çökmeden bildir (current_playback ağ hatası vermişti)
        _hata_isle(e)
    except SpotifyException:
        _otomatik_calma(sp)


def sarki_calar(sarki_adi: str):
    # Verilen şarkı adını arar, ilk sonucu albüm bağlamında çalar.
    # Albüm bağlamı başarısız olursa (single, kısıtlı içerik) tek şarkı olarak çalar.
    sp = _get_sp()
    try:
        if not _aktif_cihaz_var_mi(sp):
            return

        # "track:" alan filtresi: yalnızca şarkı başlıklarında arar.
        # Genel q=... araması albüm adı ve sanatçı biyografisini de tarar → yanlış sonuç riski.
        sorgu = f"track:{sarki_adi}"
        print(f"[Spotify] Aranıyor: {sorgu!r}")

        # market="TR": Türkiye'de çalınabilir sonuçları öne çıkarır → yanlış/çalınamaz
        # parça riskini azaltır (despacito → alakasız şarkı sorununun çözümü).
        sonuclar = sp.search(q=sorgu, type="track", limit=5, market="TR")
        parcalar  = sonuclar.get("tracks", {}).get("items", [])

        # İlk 3 sonucu debug için göster — yanlış şarkı sorununu teşhis etmek için
        for i, p in enumerate(parcalar[:3]):
            print(f"[Spotify] #{i+1}: {p['name']} — {p['artists'][0]['name']}")

        if not parcalar:
            konus(f"{sarki_adi} adında bir şarkı bulamadım.")
            return

        secilen   = parcalar[0]
        isim      = secilen["name"]
        sanatci   = secilen["artists"][0]["name"]
        sarki_uri = secilen["uri"]
        album_uri = secilen["album"]["uri"]

        # Albüm bağlamında çal: şarkı bitince albümden devam eder, kuyruk boş kalmaz.
        # Başarısız olursa (single, erişim kısıtı) tek şarkı olarak çal (fallback).
        try:
            sp.start_playback(context_uri=album_uri, offset={"uri": sarki_uri})
        except SpotifyException:
            sp.start_playback(uris=[sarki_uri])

        konus(f"Çalıyor: {isim}, {sanatci}.")

    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, f"{sarki_adi} adlı şarkıyı çalarken bir sorun oluştu.")


# ── KONTROL KOMUTLARI ────────────────────────────────────────────────────────

def muzik_duraklat():
    # Çalan müziği duraklatır.
    sp = _get_sp()
    try:
        sp.pause_playback()
        konus("Duraklatıldı.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Duraklatamadım.")


def muzik_devam_et():
    # Duraklatılmış müziği devam ettirir.
    sp = _get_sp()
    try:
        sp.start_playback()
        konus("Devam ediyor.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Devam ettiremedim.")


def sonraki_sarki():
    # Sıradaki parçaya geçer.
    sp = _get_sp()
    try:
        sp.next_track()
        konus("Sonraki şarkı.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Sonraki şarkıya geçemedim.")


def onceki_sarki():
    # Bir önceki parçaya döner.
    sp = _get_sp()
    try:
        sp.previous_track()
        konus("Önceki şarkı.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Önceki şarkıya dönemedim.")


def simdi_calan():
    # Şu an Spotify'da çalan parçayı sesli olarak bildirir.
    sp = _get_sp()
    bilgi = _mevcut_calanik(sp)
    if bilgi:
        konus(f"Şu an çalıyor: {bilgi['isim']}, {bilgi['sanatci']}.")
    else:
        konus("Şu an bir şey çalmıyor.")


def ses_ayarla(komut_metni: str):
    # Ses seviyesini ayarlar (0–100 sınırı korunur).
    # Sayı varsa → o değere; yoksa anahtar kelimeye göre ±20 uygular.
    sp = _get_sp()
    try:
        sayi_eslesme = re.search(r"\d+", komut_metni)
        if sayi_eslesme:
            # Kullanıcı doğrudan sayı söyledi (ör. "sesi 60 yap")
            hedef = max(0, min(100, int(sayi_eslesme.group())))
        else:
            # Mevcut ses seviyesini al; alınamazsa 50 varsay
            durum  = sp.current_playback()
            mevcut = (
                durum["device"]["volume_percent"]
                if durum and durum.get("device") else 50
            )
            if any(k in komut_metni for k in ("aç", "yükselt", "artır")):
                hedef = min(100, mevcut + 20)
            else:
                # "kıs", "azalt", "düşür" veya bilinmeyen → azalt
                hedef = max(0, mevcut - 20)

        sp.volume(hedef)
        konus(f"Ses seviyesi yüzde {hedef}.")

    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Ses seviyesini ayarlayamadım.")


def karistir_ac_kapa():
    # Karıştırma (shuffle) modunu tersine çevirir: açık↔kapalı.
    sp = _get_sp()
    try:
        durum = sp.current_playback()
        if not durum:
            konus("Şu an aktif bir çalma yok.")
            return
        yeni = not durum.get("shuffle_state", False)
        sp.shuffle(yeni)
        konus("Karıştırma açıldı." if yeni else "Karıştırma kapandı.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Karıştırma modunu değiştiremedim.")


def tekrar_modu_degistir():
    # Tekrar modunu döngüsel değiştirir: kapalı → şarkı tekrar → kapalı.
    # "context" (albüm/playlist döngüsü) aktifse de kapalıya alır.
    sp = _get_sp()
    try:
        durum = sp.current_playback()
        if not durum:
            konus("Şu an aktif bir çalma yok.")
            return
        mevcut = durum.get("repeat_state", "off")
        yeni   = "track" if mevcut == "off" else "off"
        sp.repeat(yeni)
        mesajlar = {
            "off":   "Tekrar modu kapatıldı.",
            "track": "Bu şarkı tekrarlanıyor.",
        }
        konus(mesajlar[yeni])
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Tekrar modunu değiştiremedim.")


def sarki_begen():
    # Şu an çalan şarkıyı kullanıcının kütüphanesine (Liked Songs) ekler.
    sp = _get_sp()
    bilgi = _mevcut_calanik(sp)
    if not bilgi:
        konus("Şu an bir şey çalmıyor, beğenecek şarkı yok.")
        return
    try:
        sp.current_user_saved_tracks_add([bilgi["id"]])
        konus(f"{bilgi['isim']} kütüphanene eklendi.")
    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Şarkıyı beğenemedim.")


# ── PLAYLIST YARDIMCILARI ────────────────────────────────────────────────────

# Playlist komutlarındaki dolgu/tetikleyici kelimeler — adı ayıklarken atılır.
# TAM KELİME olarak çıkarılır (substring değil) ki "Çalışma" gibi adlar bozulmasın.
_PLAYLIST_DOLGU = {
    "playlist", "playlisti", "playlisti", "playlistimi", "playlistini",
    "playlist'i", "playlist'imi", "playlist'ini",
    "liste", "listemi", "listesini", "listeyi", "listesi", "çalma",
    "çal", "oynat", "başlat", "aç", "bir", "bana", "lütfen", "tane", "şu", "bu",
}

# "çalma listesi" gibi iki kelimelik ifadeler önce tek seferde temizlenir.
_PLAYLIST_COKLU_DOLGU = ("çalma listemi", "çalma listesini", "çalma listesi", "bir tane")


def _playlist_adi_ayikla(metin: str) -> str:
    # Komut metninden playlist adını çıkarır. Örnekler:
    #   "playlist çal sakin"        → "sakin"
    #   "sakin playlist çal"        → "sakin"
    #   "sakin bir playlist çal"    → "sakin"
    #   "sakin çalma listemi aç"    → "sakin"
    #   "sakin akşamlar playlistini çal" → "sakin akşamlar"
    m = metin.lower()
    for ifade in _PLAYLIST_COKLU_DOLGU:
        m = m.replace(ifade, " ")
    # Tek kelimelik dolguları TAM KELİME olarak at (substring değil)
    kelimeler = [k for k in m.split() if k not in _PLAYLIST_DOLGU]
    return " ".join(kelimeler).strip()


def _tum_playlistler(sp) -> list:
    # Kullanıcının TÜM playlist'lerini sayfalayarak toplar (50/istek sınırı aşılır).
    tum = []
    sonuc = sp.current_user_playlists(limit=50)
    while sonuc:
        tum.extend(sonuc["items"])
        sonuc = sp.next(sonuc) if sonuc.get("next") else None
    return tum


def _playlist_bul(tum_listeler: list, aranan: str):
    # Playlist adını esnek eşleştirir: önce büyük/küçük harf duyarsız ALT DİZE,
    # bulunamazsa rapidfuzz ile bulanık eşleşme (eşik 70). Eşleşme yoksa None.
    aranan = aranan.lower().strip()
    if not aranan:
        return None

    # 1. Tam alt dize: "sakin" → "Sakin Akşamlar"
    for pl in tum_listeler:
        if pl and aranan in pl["name"].lower():
            return pl

    # 2. Bulanık eşleşme: yazım/ek farklarını tolere eder
    en_iyi, en_skor = None, 0
    for pl in tum_listeler:
        if not pl:
            continue
        skor = fuzz.partial_ratio(aranan, pl["name"].lower())
        if skor > en_skor:
            en_iyi, en_skor = pl, skor
    return en_iyi if en_skor >= 70 else None


def playlist_cal(playlist_adi: str):
    # Adı verilen playlist'i bulur ve çalar. Ad; dolgu kelimeleri temizlenip
    # (sakin bir playlist çal → sakin) esnek + bulanık eşleştirmeyle aranır.
    sp = _get_sp()

    # Tetikleyici/dolgu kelimeleri ayıkla (komutlar.py ham metni de gönderebilir)
    temiz_ad = _playlist_adi_ayikla(playlist_adi)
    if not temiz_ad:
        konus("Hangi playlist'i çalmamı istersin?")
        return

    try:
        if not _aktif_cihaz_var_mi(sp):
            return

        tum_listeler = _tum_playlistler(sp)
        eslesen = _playlist_bul(tum_listeler, temiz_ad)

        if not eslesen:
            # Boş "bulamadım" yerine YARDIMCI ol: mevcut birkaç playlist adını söyle
            if tum_listeler:
                ornekler = ", ".join(pl["name"] for pl in tum_listeler[:4] if pl)
                konus(
                    f"{temiz_ad} adında bir playlist bulamadım. "
                    f"Şunlar var: {ornekler}. Hangisini çalayım?"
                )
            else:
                konus("Hiç playlist'in yok gibi görünüyor.")
            return

        # Playlist bağlamında çal: tüm şarkılar sıraya girer
        sp.start_playback(context_uri=eslesen["uri"])
        konus(f"{eslesen['name']} çalıyor.")

    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Playlist'i çalamadım.")


def playliste_ekle(playlist_adi: str):
    # Şu an çalan şarkıyı belirtilen playlist'e ekler.
    sp = _get_sp()
    bilgi = _mevcut_calanik(sp)
    if not bilgi:
        konus("Şu an bir şey çalmıyor, ekleyecek şarkı yok.")
        return
    try:
        # Kullanıcının tüm playlist'lerini topla, esnek + bulanık eşleştir
        temiz_ad = _playlist_adi_ayikla(playlist_adi)
        tum_listeler = _tum_playlistler(sp)
        eslesen = _playlist_bul(tum_listeler, temiz_ad)

        if not eslesen:
            if tum_listeler:
                ornekler = ", ".join(pl["name"] for pl in tum_listeler[:4] if pl)
                konus(
                    f"{temiz_ad} adında bir playlist bulamadım. "
                    f"Şunlar var: {ornekler}. Hangisine ekleyeyim?"
                )
            else:
                konus("Hiç playlist'in yok gibi görünüyor.")
            return

        # Şarkı URI'sini playlist'e ekle (playlist_add_items: yeni spotipy metodu)
        sp.playlist_add_items(eslesen["id"], [bilgi["uri"]])
        konus(f"{bilgi['isim']}, {eslesen['name']} playlistine eklendi.")

    except (SpotifyException, _AG_HATASI) as e:
        _hata_isle(e, "Playlist'e ekleyemedim.")
