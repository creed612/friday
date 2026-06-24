# Bu dosya Friday'in Google Drive entegrasyonunu içerir.
# Dosya adına göre arama yapar, sonuçları sesli listeler ve tarayıcıda açar.

import webbrowser

from googleapiclient.discovery import build

from google_kimlik import _giris_yap
from ses import konus, komut_dinle, yaz

_servis = None


def _drive_servisi():
    global _servis
    if _servis is None:
        _servis = build("drive", "v3", credentials=_giris_yap())
    return _servis


def drive_dosya_ara(arama_terimi: str, mod: str):
    """
    Drive'da dosya adı arama_terimi içeren dosyaları bulur ve listeler.
    Tek sonuç varsa otomatik açar; birden fazla varsa kullanıcıya seçim sunar.

    arama_terimi : aranacak dosya adı parçası
    mod          : "sesli" veya "yazili" — kullanıcı girdisi almak için
    """
    try:
        sp = _drive_servisi()

        # Çöp kutusundaki dosyaları hariç tut, adında arama yap
        # Tırnak içindeki apostrof çakışmasını önlemek için arama_terimi temizlenir
        guvenli_terim = arama_terimi.replace("'", "\\'")
        sorgu = f"name contains '{guvenli_terim}' and trashed = false"

        sonuc = sp.files().list(
            q=sorgu,
            fields="files(id, name, webViewLink, mimeType)",
            pageSize=10,
            orderBy="modifiedTime desc",   # en son değiştirilen önce gelsin
        ).execute()

        dosyalar = sonuc.get("files", [])

        if not dosyalar:
            konus(f"Drive'da '{arama_terimi}' adında bir dosya bulamadım.")
            return

        if len(dosyalar) == 1:
            konus(f"Bir dosya buldum: {dosyalar[0]['name']}. Açıyorum.")
            if dosyalar[0].get("webViewLink"):
                webbrowser.open(dosyalar[0]["webViewLink"])
            return

        # Birden fazla sonuç: listele ve seçim sor
        konus(f"{len(dosyalar)} dosya buldum:")
        for i, dosya in enumerate(dosyalar, start=1):
            konus(f"{i}. {dosya['name']}")

        konus("Hangisini açmamı istersin? Numara söyle veya 'iptal' de.")
        if mod == "sesli":
            yanit = komut_dinle()
        else:
            yanit = yaz().strip()

        if not yanit or "iptal" in yanit:
            konus("Tamam, iptal ettim.")
            return

        # Yanıttaki ilk sayıyı bul
        import re
        sayi_eslesme = re.search(r"\d+", yanit)
        if not sayi_eslesme:
            konus("Numara anlayamadım.")
            return

        secilen_idx = int(sayi_eslesme.group()) - 1
        if 0 <= secilen_idx < len(dosyalar):
            secilen = dosyalar[secilen_idx]
            konus(f"Açıyorum: {secilen['name']}.")
            if secilen.get("webViewLink"):
                webbrowser.open(secilen["webViewLink"])
        else:
            konus("Geçersiz numara.")

    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Drive'a şu an ulaşamıyorum.")
