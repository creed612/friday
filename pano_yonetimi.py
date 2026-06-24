# Bu dosya Friday'in "pano hilesi" özelliğini içerir.
# Kullanıcı bir metni seçip Ctrl+C ile kopyalar; Friday panodaki metni
# OKUR, ÖZETLER veya ÇEVİRİR. Ekran okuma/OCR'a gerek kalmadan web sitesi
# ve belge okuma için basit ve sağlam bir yöntemdir.
#
# HATA YÖNETİMİ: Tüm fonksiyonlar try/except ile korunur; pano boşsa veya
# metin değilse (resim kopyalanmışsa) nazikçe uyarılır, program çökmez.

import re

import pyperclip

from ses import konus, komut_dinle, yaz
from cevirmen import _DIL_KODLARI   # Türkçe dil adı → Google Translate kodu


# Uzun metin eşikleri (karakter cinsinden)
_UZUN_OKUMA_ESIGI = 2000     # bundan uzunsa: oku mu / özetle mi diye sor
_LLM_BAGLAM_ESIGI = 6000     # bundan uzunsa: parçalara böl (map-reduce özet)


def _pano_metni_al() -> str:
    # Panodaki metni döndürür. Resim/boş/metin-dışı durumlarda "" döner.
    try:
        metin = pyperclip.paste()
        # pyperclip metin döndürür; resim kopyalanmışsa genelde "" gelir
        return metin.strip() if isinstance(metin, str) else ""
    except Exception as e:
        print(f"[PANO] Pano okunamadı: {e}")
        return ""


def _kullanici_yaniti_al(mod: str) -> str:
    # Moda göre kullanıcıdan yanıt alır (gmail_yonetimi ile aynı desen).
    if mod == "sesli":
        return komut_dinle()
    return yaz().lower().strip()


# ── A) PANOYU OKU ─────────────────────────────────────────────────────────────

def pano_oku(mod: str):
    # Panodaki metni seslendirir. Çok uzunsa önce oku/özetle diye sorar.
    metin = _pano_metni_al()
    if not metin:
        konus("Panoda metin yok. Önce bir şeyler kopyala, sonra tekrar dene.")
        return

    # Çok uzun metin → kullanıcıya sor (tamamını okumak yorucu olur)
    if len(metin) > _UZUN_OKUMA_ESIGI:
        kelime_sayisi = len(metin.split())
        konus(
            f"Panoda uzun bir metin var, yaklaşık {kelime_sayisi} kelime. "
            "Tamamını okuyayım mı, yoksa özetleyeyim mi?"
        )
        yanit = _kullanici_yaniti_al(mod)
        if yanit and any(k in yanit for k in ("özet", "özetle", "kısa", "summary")):
            pano_ozetle(mod)
            return
        # "oku"/"tamamını"/belirsiz → tamamını oku (aşağı düşer)

    konus(metin)


# ── B) PANOYU ÖZETLE ──────────────────────────────────────────────────────────

_OZET_SISTEM = (
    "Aşağıdaki metni Türkçe olarak kısa ve net özetle. "
    "Sadece özeti ver, başka bir şey yazma."
)


def _metni_parcala(metin: str, parca_boyu: int) -> list:
    # Uzun metni, kelime sınırlarını koruyarak ~parca_boyu karakterlik parçalara böler.
    kelimeler = metin.split()
    parcalar, mevcut = [], ""
    for kelime in kelimeler:
        if len(mevcut) + len(kelime) + 1 > parca_boyu:
            if mevcut:
                parcalar.append(mevcut)
            mevcut = kelime
        else:
            mevcut = f"{mevcut} {kelime}".strip()
    if mevcut:
        parcalar.append(mevcut)
    return parcalar


def pano_ozetle(mod: str):
    # Panodaki metni LLM (qwen3:8b) ile özetler ve seslendirir.
    # Çok uzun metinlerde (bağlam 4096) map-reduce: her parçayı özetle,
    # sonra özetleri birleştirip tek bir nihai özet üret.
    metin = _pano_metni_al()
    if not metin:
        konus("Panoda metin yok. Önce özetlemek istediğin metni kopyala.")
        return

    # LLM gecikmeli import — döngüsel bağımlılık ve açılış yükü riski yok
    try:
        from beyin import beyin_metin_uret
    except Exception:
        konus("Özetleme için beynim şu an kapalı.")
        return

    try:
        konus("Panodaki metni özetliyorum, bir saniye.")

        if len(metin) <= _LLM_BAGLAM_ESIGI:
            # Tek seferde özetle
            ozet = beyin_metin_uret(_OZET_SISTEM, metin)
        else:
            # MAP-REDUCE: parçalara böl, her parçayı özetle, sonra özetleri özetle
            parcalar = _metni_parcala(metin, _LLM_BAGLAM_ESIGI - 1000)
            print(f"[PANO] Uzun metin {len(parcalar)} parçaya bölündü (map-reduce özet).")
            ara_ozetler = []
            for i, parca in enumerate(parcalar, start=1):
                _o = beyin_metin_uret(_OZET_SISTEM, parca)
                if _o:
                    ara_ozetler.append(_o)
                print(f"[PANO] Parça {i}/{len(parcalar)} özetlendi.")
            if not ara_ozetler:
                ozet = None
            else:
                # REDUCE: ara özetleri birleştirip nihai özet üret
                birlesik = "\n".join(ara_ozetler)
                ozet = beyin_metin_uret(
                    "Aşağıda bir metnin parça parça özetleri var. Bunları birleştirip "
                    "tek, tutarlı ve kısa bir Türkçe özet yaz. Sadece özeti ver.",
                    birlesik,
                )

        if ozet:
            konus(ozet)
            if mod == "yazili":
                print(f"\n[ÖZET]\n{ozet}\n")
        else:
            # beyin_metin_uret None → Ollama kapalı veya hata
            konus("Özetleme için beynim şu an kapalı veya yanıt veremedi.")
    except Exception as e:
        print(f"[PANO] Özetleme hatası: {e}")
        konus("Metni özetleyemedim.")


# ── C) PANOYU ÇEVİR ───────────────────────────────────────────────────────────

def _hedef_dil_ayikla(komut_metni: str):
    # Komut metninden hedef dili çıkarır. Bulamazsa ("ingilizce", "en") varsayılan.
    # Örn: "panodakini almancaya çevir" → ("almanca", "de")
    for dil_adi, kod in _DIL_KODLARI.items():
        if dil_adi in komut_metni:
            return dil_adi, kod
    return "ingilizce", "en"


def pano_cevir(mod: str, komut_metni: str = ""):
    # Panodaki metni hedef dile çevirir (deep-translator, mevcut çeviri altyapısı).
    # Kaynak dil "auto": pano metni İngilizce/başka dilde olabilir → otomatik algıla.
    metin = _pano_metni_al()
    if not metin:
        konus("Panoda metin yok. Önce çevirmek istediğin metni kopyala.")
        return

    hedef_dil_adi, hedef_kod = _hedef_dil_ayikla(komut_metni)

    try:
        from deep_translator import GoogleTranslator
        # source="auto": pano metninin dili önceden bilinmiyor (web/belge olabilir)
        ceviri = GoogleTranslator(source="auto", target=hedef_kod).translate(metin)
        konus(f"{hedef_dil_adi.capitalize()} çevirisi: {ceviri}")
        if mod == "yazili":
            print(f"\n[ÇEVİRİ - {hedef_dil_adi}]\n{ceviri}\n")
    except Exception as e:
        print(f"[PANO] Çeviri hatası: {e}")
        konus("Panodaki metni çeviremedim, internet bağlantını kontrol et.")
