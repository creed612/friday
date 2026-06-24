# Bu dosya Friday'in hızlı not alma özelliğini içerir.
# Notlar proje klasöründeki "notlarim.txt" dosyasına tarih/saat damgasıyla kaydedilir.

import os
import re
from datetime import datetime
from ses import konus, komut_dinle, yaz

# Not dosyasının tam yolu — notlar.py nerede olursa olsun her zaman doğru dizini gösterir
_NOTLAR_DOSYASI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notlarim.txt")

# Silme onayında OLUMSUZ sayılan ifadeler (gmail_yonetimi ile aynı mantık)
_OLUMSUZ_KELIMELER = ("hayır", "hayir", "yok", "istemiyorum", "vazgeç", "iptal",
                       "dur", "boşver", "boş ver", "olmaz", "silme")


def not_ekle(metin):
    # Metni "[GG.AA.YYYY SS:DD] metin" formatında notlarim.txt dosyasına ekler.
    # Dosya yoksa otomatik oluşturulur.
    tarih_saat = datetime.now().strftime("%d.%m.%Y %H:%M")
    satir = f"[{tarih_saat}] {metin}\n"

    with open(_NOTLAR_DOSYASI, "a", encoding="utf-8") as dosya:
        dosya.write(satir)

    konus("Not kaydedildi.")


def notlari_oku():
    # notlarim.txt dosyasını okur ve tüm notları sırayla sesli okur.
    # Dosya yoksa veya boşsa "Hiç notun yok" der.
    if not os.path.exists(_NOTLAR_DOSYASI):
        konus("Hiç notun yok.")
        return

    with open(_NOTLAR_DOSYASI, "r", encoding="utf-8") as dosya:
        notlar = [satir.strip() for satir in dosya if satir.strip()]

    if not notlar:
        konus("Hiç notun yok.")
        return

    konus(f"Toplam {len(notlar)} notun var.")
    for not_satiri in notlar:
        konus(not_satiri)


# ══════════════════════════════════════════════════════════════════════════════
#  KAPSAMLI NOT KOMUT TABLOSU
# ──────────────────────────────────────────────────────────────────────────────
# TÜM not komutları tek kapıdan: notlar_komut_isle(metin, mod). Yeni bir not
# özelliği eklemek için BURAYA bir niyet dalı + fonksiyon eklemek yeterli
# (komutlar.py'ye dokunmaya gerek yok). Niyet SIRASI önemli: EKLE en başta
# (içeriğinde "sil" geçse bile "not al ..." bir EKLEME komutudur).
#
# Niyetler: ekle | sil (hepsi/son/ilk/numara) | say | (varsayılan) oku
# ══════════════════════════════════════════════════════════════════════════════

def _notlari_yukle() -> list:
    # Notları satır listesi olarak döndürür (boş satırlar atılır).
    if not os.path.exists(_NOTLAR_DOSYASI):
        return []
    with open(_NOTLAR_DOSYASI, "r", encoding="utf-8") as dosya:
        return [s.strip() for s in dosya if s.strip()]


def _notlari_yaz(liste: list) -> None:
    # Not listesini dosyaya geri yazar (silme işlemlerinden sonra).
    with open(_NOTLAR_DOSYASI, "w", encoding="utf-8") as dosya:
        for s in liste:
            dosya.write(s + "\n")


def _not_icerigi(satir: str) -> str:
    # "[GG.AA.YYYY SS:DD] içerik" → "içerik" (zaman damgasını ayıkla, sesli okuma için).
    return re.sub(r"^\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}\]\s*", "", satir) or satir


def not_say() -> None:
    # Kayıtlı not sayısını söyler.
    adet = len(_notlari_yukle())
    konus("Hiç notun yok." if adet == 0 else f"Toplam {adet} notun var.")


def not_sil(metin: str, mod: str) -> None:
    # Not siler. Kapsam metinden belirlenir:
    #   "son notu sil"      → en son notu
    #   "ilk notu sil"      → ilk notu
    #   "3. notu sil"       → numarayla (regex ile sayı)
    #   "notları sil"/"hepsini sil" → TÜMÜ (önce ONAY ister)
    notlar = _notlari_yukle()
    if not notlar:
        konus("Silinecek not yok.")
        return

    m = metin.lower()
    sayi = re.search(r"\d+", m)

    # SON
    if "son" in m or "sonuncu" in m:
        silinen = notlar.pop()
        _notlari_yaz(notlar)
        konus(f"Son notun silindi: {_not_icerigi(silinen)}")
        return

    # İLK (sayı yoksa)
    if "ilk" in m and not sayi:
        notlar.pop(0)
        _notlari_yaz(notlar)
        konus("İlk notun silindi.")
        return

    # NUMARA ile
    if sayi:
        idx = int(sayi.group())
        if 1 <= idx <= len(notlar):
            silinen = notlar.pop(idx - 1)
            _notlari_yaz(notlar)
            konus(f"{idx}. notun silindi: {_not_icerigi(silinen)}")
        else:
            konus(f"{idx} numaralı not yok; toplam {len(notlar)} notun var.")
        return

    # TÜMÜ — yıkıcı, ONAY iste
    konus(f"{len(notlar)} notun var. Hepsini silmemi onaylıyor musun?")
    yanit = (komut_dinle() if mod == "sesli" else yaz()).lower().strip()
    if (yanit and not any(k in yanit for k in _OLUMSUZ_KELIMELER)
            and any(k in yanit for k in ("evet", "sil", "olur", "tamam", "onayla"))):
        _notlari_yaz([])
        konus("Tüm notların silindi.")
    else:
        konus("İptal ettim, notların duruyor.")


def notlar_komut_isle(metin: str, mod: str) -> bool:
    """Tüm not komutlarını niyetine göre yönlendirir. Dönüş: True (ele alındı)."""
    m = (metin or "").lower().strip()

    # 1) EKLE — "not al/ekle/düş [içerik]" (EN BAŞTA: içerikte 'sil' geçse bile EKLEME'dir)
    for tetik in ("not al ", "not ekle ", "not düş ", "not olarak ekle ", "notuma ekle "):
        if m.startswith(tetik):
            # İçeriği ORİJİNAL metinden al (büyük/küçük harf korunur)
            icerik = metin[len(tetik):].strip()
            if icerik:
                not_ekle(icerik)
            else:
                konus("Ne not almamı istersin? Lütfen bir şeyler söyle.")
            return True

    # 2) SİL — "notları/notu/son/ilk/3. ... sil/temizle/kaldır"
    if any(k in m for k in ("sil", "temizle", "kaldır", "çöpe")):
        not_sil(m, mod)
        return True

    # 3) SAY — "kaç notum var", "not sayısı"
    if "kaç not" in m or "not sayısı" in m:
        not_say()
        return True

    # 4) VARSAYILAN — notları oku/listele
    notlari_oku()
    return True
