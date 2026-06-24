# Bu dosya Friday'in hafıza ve kişiselleştirme sistemini içerir.
# Tüm veriler hafiza.json dosyasında okunabilir/düzenlenebilir JSON formatında saklanır.
#
# Şu an kural tabanlı çalışıyor; ileride LLM bağlamı olarak kullanılabilir.
# Bu yüzden veri yapısı temiz, genişletilebilir ve makine-okunabilir tutulmuştur.
#
# Bölümler:
#   1) Kişisel bilgiler  — bilgi_kaydet / bilgi_getir / kullanici_ozeti
#   2) Komut istatistikleri — komut_say / en_cok_kullanilan
#   3) Alışkanlık takibi  — aliskanlik_kaydet / aliskanlik_oner
#   4) Konuşma geçmişi   — konusma_ekle / son_konusmalar

import copy
import json
from datetime import datetime
from pathlib import Path
from threading import Lock


# Veri dosyasının yolu — hafiza.py ile aynı dizinde
_HAFIZA_DOSYASI = Path(__file__).parent / "hafiza.json"

# Eş zamanlı erişimi önleyen kilit (hatırlatıcı thread'i de dosyaya ulaşabilir)
_kilit = Lock()

# Geçmişte kaç konuşmanın saklanacağı (eski kayıtlar otomatik silinir)
_MAX_GECMIS = 100

# ── VARSAYILAN YAPI ────────────────────────────────────────────────────────────
# hafiza.json yoksa veya bozuksa bu yapı kullanılır.
# LLM bağlamı için de bu yapı doğrudan okunabilir.
_VARSAYILAN = {
    "kullanici": {
        "isim":     None,    # KULLANICININ adı (Doğukan gibi) — asistan adından AYRI
        "sehir":    None,    # Hava durumu için kayıtlı şehir (hava_durumu.py ile senkron)
        "tercihler": {}      # Özel tercihler: müzik_türü, dil, vs.
    },
    "asistan_adi":           "Friday",   # ASİSTANIN adı — kullanıcı adıyla ASLA karışmaz
    "komut_istatistikleri": {},   # {"hava_durumu": 42, "müzik": 30, ...}
    "aliskanliklar":         {},   # {"hava_durumu": {"sabah": 12, "öğle": 3, ...}, ...}
    "konusma_gecmisi":       [],   # Son 100 etkileşim, tarih/saat damgalı
}

# "isim" ve "sehir" doğrudan kullanici{} altında; diğerleri tercihler{} altında saklanır.
_BIRINCI_SINIF = {"isim", "sehir"}


# ── YARDIMCI: SAAT DİLİMİ ────────────────────────────────────────────────────

def _saat_dilimi() -> str:
    """Şu anki saate göre sabah/öğle/akşam/gece döndürür."""
    saat = datetime.now().hour
    if 5  <= saat < 12: return "sabah"
    if 12 <= saat < 17: return "öğle"
    if 17 <= saat < 22: return "akşam"
    return "gece"


# ── YARDIMCI: YÜKLEME / KAYDETME ──────────────────────────────────────────────

def _yukle() -> dict:
    """hafiza.json'u okur. Dosya yoksa veya bozuksa varsayılan yapıyı döner.

    Eksik anahtarları tamamlar — eski sürümden geçiş güvenli olur.
    NOT: Bu fonksiyon kilit içinden çağrılır; kendisi kilit almaz.
    """
    try:
        if _HAFIZA_DOSYASI.exists():
            with open(_HAFIZA_DOSYASI, "r", encoding="utf-8") as f:
                veri = json.load(f)
            # Eksik üst-düzey anahtarları varsayılanla tamamla
            for ana, val in _VARSAYILAN.items():
                if ana not in veri:
                    veri[ana] = copy.deepcopy(val)
                elif isinstance(val, dict):
                    for alt, alt_val in val.items():
                        if alt not in veri[ana]:
                            veri[ana][alt] = copy.deepcopy(alt_val)
            return veri
    except Exception:
        pass  # Bozuk JSON veya okuma hatası → sıfırdan başla
    return copy.deepcopy(_VARSAYILAN)


def _kaydet(veri: dict) -> None:
    """Veriyi hafiza.json'a yazar (UTF-8, okunabilir pretty-print).

    NOT: Bu fonksiyon kilit içinden çağrılır; kendisi kilit almaz.
    """
    with open(_HAFIZA_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2, default=str)


# ── KİŞİSEL BİLGİLER ──────────────────────────────────────────────────────────

def bilgi_kaydet(anahtar: str, deger) -> None:
    """Kullanıcı bilgisini hafiza.json'a kaydeder.

    "isim" ve "sehir" → kullanici{} altına doğrudan kaydedilir (birinci sınıf).
    Diğer anahtarlar  → kullanici.tercihler{} altına kaydedilir.

    Örnekler:
        bilgi_kaydet("isim", "Ahmet")
        bilgi_kaydet("sehir", "istanbul")
        bilgi_kaydet("müzik_türü", "rock")
    """
    try:
        with _kilit:
            veri = _yukle()
            if anahtar in _BIRINCI_SINIF:
                veri["kullanici"][anahtar] = deger
            else:
                veri["kullanici"].setdefault("tercihler", {})[anahtar] = deger
            _kaydet(veri)
    except Exception:
        pass  # Kayıt hatası sessizce geçilir — uygulama çökmez


def bilgi_getir(anahtar: str):
    """Kayıtlı kullanıcı bilgisini döndürür. Kayıt yoksa None."""
    try:
        with _kilit:
            veri = _yukle()
        if anahtar in _BIRINCI_SINIF:
            return veri["kullanici"].get(anahtar)
        return veri["kullanici"].get("tercihler", {}).get(anahtar)
    except Exception:
        return None


def asistan_adi_getir() -> str:
    """ASİSTANIN adını döndürür (varsayılan 'Friday'). Kullanıcı adından AYRIDIR."""
    try:
        with _kilit:
            veri = _yukle()
        return veri.get("asistan_adi") or "Friday"
    except Exception:
        return "Friday"


def asistan_adi_kaydet(ad: str) -> None:
    """ASİSTANIN adını kaydeder (top-level 'asistan_adi'). Kullanıcı adına DOKUNMAZ."""
    try:
        with _kilit:
            veri = _yukle()
            veri["asistan_adi"] = ad
            _kaydet(veri)
    except Exception:
        pass


def kullanici_ozeti() -> str:
    """Kayıtlı tüm kullanıcı bilgilerini tek cümle olarak özetler.

    LLM entegrasyonunda bu özet bağlam olarak sisteme verilebilir.
    """
    try:
        with _kilit:
            veri = _yukle()
        kul      = veri.get("kullanici", {})
        parcalar = []

        if kul.get("isim"):
            parcalar.append(f"adın {kul['isim']}")
        if kul.get("sehir"):
            parcalar.append(f"şehrin {kul['sehir'].title()}")
        for k, v in kul.get("tercihler", {}).items():
            # Anahtarlardaki alt çizgileri boşlukla göster — daha doğal Türkçe
            parcalar.append(f"{k.replace('_', ' ')}: {v}")

        if not parcalar:
            return "Henüz hakkında kayıtlı bir bilgim yok. 'Benim adım ...' diyerek tanıtabilirsin."
        return "Hakkında bildiklerim: " + ", ".join(parcalar) + "."
    except Exception:
        return "Bilgilerine şu an ulaşamıyorum."


# ── KOMUT İSTATİSTİKLERİ ──────────────────────────────────────────────────────

def komut_say(komut_adi: str) -> None:
    """Komut adının kullanım sayacını bir artırır.

    komutlar.py içindeki _izle() yardımcısı tarafından her başarılı
    komut işlendiğinde otomatik olarak çağrılır.
    """
    try:
        with _kilit:
            veri = _yukle()
            ist  = veri.setdefault("komut_istatistikleri", {})
            ist[komut_adi] = ist.get(komut_adi, 0) + 1
            _kaydet(veri)
    except Exception:
        pass


def en_cok_kullanilan(n: int = 5) -> list:
    """En çok kullanılan n komutu (komut_adi, sayi) çiftleri olarak döndürür.

    Örnek çıktı: [("hava_durumu", 42), ("müzik_cal", 30), ("takvim", 12)]
    """
    try:
        with _kilit:
            veri = _yukle()
        ist = veri.get("komut_istatistikleri", {})
        return sorted(ist.items(), key=lambda x: x[1], reverse=True)[:n]
    except Exception:
        return []


# ── ALIŞKANLIK TAKİBİ ─────────────────────────────────────────────────────────

def aliskanlik_kaydet(komut: str) -> None:
    """Komutun hangi saat diliminde kullanıldığını alışkanlık verisine ekler.

    Örün: Her sabah hava durumu soruluyorsa:
        aliskanliklar["hava_durumu"]["sabah"] → 12 (kez)

    aliskanlik_oner() bu birikmiş veriyi proaktif öneri için kullanır.
    """
    try:
        dilim = _saat_dilimi()
        with _kilit:
            veri = _yukle()
            al   = veri.setdefault("aliskanliklar", {})
            if komut not in al:
                # Yeni komut için dört saat dilimini sıfırla başlat
                al[komut] = {"sabah": 0, "öğle": 0, "akşam": 0, "gece": 0}
            al[komut][dilim] = al[komut].get(dilim, 0) + 1
            _kaydet(veri)
    except Exception:
        pass


def aliskanlik_oner() -> tuple | None:
    """Şu anki saat diliminde en sık kullanılan komutu önerir.

    En az 3 kullanım varsa (komut_adi, sayi, dilim) tuple'ı döner.
    Yoksa None döner — main.py'de açılışta proaktif öneri için kullanılır.

    Örn: sabah 5 kez hava durumu sorulmuşsa
         → ("hava_durumu", 5, "sabah") döner.
    """
    try:
        dilim = _saat_dilimi()
        with _kilit:
            veri = _yukle()
        al = veri.get("aliskanliklar", {})
        if not al:
            return None
        # Bu saat diliminde en yüksek sayıya sahip komutu bul
        en_cok = max(al.items(), key=lambda x: x[1].get(dilim, 0))
        sayi   = en_cok[1].get(dilim, 0)
        if sayi >= 3:
            return (en_cok[0], sayi, dilim)
    except Exception:
        pass
    return None


# ── KONUŞMA GEÇMİŞİ ───────────────────────────────────────────────────────────

def konusma_ekle(kullanici_metni: str, friday_cevabi: str = "") -> None:
    """Her etkileşimi tarih/saat damgasıyla konuşma geçmişine ekler.

    Son _MAX_GECMIS (100) kayıt tutulur; eski kayıtlar otomatik silinir.
    friday_cevabi genellikle işlenen komutun adıdır (örn. "hava_durumu").
    LLM entegrasyonunda bu geçmiş bağlam olarak modele verilebilir.
    """
    try:
        with _kilit:
            veri   = _yukle()
            gecmis = veri.setdefault("konusma_gecmisi", [])
            gecmis.append({
                "tarih":     datetime.now().isoformat(timespec="seconds"),
                "kullanici": kullanici_metni[:200],    # çok uzun metinleri kırp
                "friday":    friday_cevabi[:100],
            })
            # Dosya şişmesin: sadece son 100 kayıt
            if len(gecmis) > _MAX_GECMIS:
                veri["konusma_gecmisi"] = gecmis[-_MAX_GECMIS:]
            _kaydet(veri)
    except Exception:
        pass


def son_konusmalar(n: int = 5) -> list:
    """Son n konuşmayı döndürür. Liste eskiden yeniye sıralıdır.

    Her öğe: {"tarih": "2024-06-18T08:30:15", "kullanici": "...", "friday": "..."}
    """
    try:
        with _kilit:
            veri = _yukle()
        gecmis = veri.get("konusma_gecmisi", [])
        return gecmis[-n:]
    except Exception:
        return []
