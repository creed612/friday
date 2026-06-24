# Bu dosya Friday'in Gmail entegrasyonunu içerir.
# Okunmamış mail okuma, filtreleme, gönderme ve yanıtlama işlevlerini kapsar.

import base64
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from googleapiclient.discovery import build

from google_kimlik import _giris_yap
from ses import konus, komut_dinle, yaz

# Önemsiz mail tespiti için gönderici adresi veya konu satırında aranan kelimeler
_ONEMSSIZ_KELIMELER = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "newsletter", "campaign", "marketing", "notification", "notifications",
    "automated", "automatic", "subscribe", "unsubscribe", "mailing",
    "promosyon", "indirim", "fırsat", "kampanya", "bülten",
    "info@", "support@", "hello@", "team@",
}

# Gmail API'nin otomatik kategori etiketi — bu etikete sahip mailler önemsizdir
_PROMOSYON_ETIKETI = "CATEGORY_PROMOTIONS"

# Tek seferlik servis nesnesi (singleton)
_servis = None


def _gmail_servisi():
    global _servis
    if _servis is None:
        _servis = build("gmail", "v1", credentials=_giris_yap())
    return _servis


def _onemssiz_mi(gonderen: str, konu: str, etiketler: list) -> bool:
    # Maili üç kritere göre filtreler:
    # 1. Gmail'in CATEGORY_PROMOTIONS etiketi varsa
    # 2. Gönderici adresi önemsiz kelime içeriyorsa
    # 3. Konu satırı önemsiz kelime içeriyorsa
    if _PROMOSYON_ETIKETI in etiketler:
        return True
    gonderen_k = gonderen.lower()
    konu_k     = konu.lower()
    return any(k in gonderen_k or k in konu_k for k in _ONEMSSIZ_KELIMELER)


def _baslik_degerini_al(basliklar: list, aranan: str) -> str:
    # E-posta başlık listesinden belirli bir alanın değerini döndürür.
    for b in basliklar:
        if b["name"].lower() == aranan.lower():
            return b["value"]
    return ""


def _metin_govdesi_al(mesaj: dict) -> str:
    # Mesajın text/plain gövdesini base64'ten çözüp döndürür.
    # Parçalı (multipart) mesajlarda text/plain parçasını bulur.
    def _parcalari_tara(payload):
        mime_turu = payload.get("mimeType", "")
        if mime_turu == "text/plain":
            veri = payload.get("body", {}).get("data", "")
            if veri:
                return base64.urlsafe_b64decode(veri).decode("utf-8", errors="ignore")
        for parca in payload.get("parts", []):
            sonuc = _parcalari_tara(parca)
            if sonuc:
                return sonuc
        return ""

    return _parcalari_tara(mesaj.get("payload", {}))


def okunmamis_mailleri_getir() -> dict:
    """
    Okunmamış mailleri çekip önemli ve önemsiz olarak ayırır.

    Dönüş:
        {
          "onemli":   [{"id", "thread_id", "gonderen", "gonderen_adres", "konu"}, ...],
          "onemssiz": [{"id", "thread_id", "gonderen", "konu"}, ...],
        }
    NOT: onemssiz (reklam) artık "id" de içerir → reklam okuma/silme mümkün.
    """
    sp = _gmail_servisi()

    # is:unread filtresiyle en fazla 20 mail çek (performans için sınır)
    liste = sp.users().messages().list(
        userId="me", q="is:unread", maxResults=20
    ).execute()

    mesajlar = liste.get("messages", [])
    onemli   = []
    onemssiz = []

    for m in mesajlar:
        detay = sp.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()

        basliklar = detay.get("payload", {}).get("headers", [])
        etiketler = detay.get("labelIds", [])
        gonderen  = _baslik_degerini_al(basliklar, "From")
        konu      = _baslik_degerini_al(basliklar, "Subject") or "(Konusuz)"

        # Gönderici adını ve adresini ayır: "Ad Soyad <adres@örnek.com>"
        eslesme   = re.match(r"^(.*?)\s*<(.+?)>$", gonderen)
        if eslesme:
            gonderen_adi = eslesme.group(1).strip().strip('"')
            gonderen_adres = eslesme.group(2).strip()
        else:
            gonderen_adi   = gonderen
            gonderen_adres = gonderen

        if _onemssiz_mi(gonderen_adres, konu, etiketler):
            onemssiz.append({
                "id":        m["id"],
                "thread_id": detay.get("threadId", ""),
                "gonderen":  gonderen_adi or gonderen_adres,
                "konu":      konu,
            })
        else:
            onemli.append({
                "id":          m["id"],
                "thread_id":   detay.get("threadId", ""),
                "gonderen":    gonderen_adi or gonderen_adres,
                "gonderen_adres": gonderen_adres,
                "konu":        konu,
            })

    return {"onemli": onemli, "onemssiz": onemssiz}


def _kullanici_yaniti_al(mod: str) -> str:
    # Moda göre kullanıcıdan metin alır.
    if mod == "sesli":
        return komut_dinle()
    return yaz().lower().strip()


# ── NİYET AYRIŞTIRMA ──────────────────────────────────────────────────────────
# KRİTİK TÜRKÇE SORUNU: olumsuz emir "-ma/-me" eki. "okuma" kelimesi "oku" İÇERİR,
# bu yüzden `"oku" in yanit` kontrolü "okuma"yı (OKUMA = read-NOT) yanlışlıkla
# "oku" sanıyordu. Çözüm: olumsuzları DAİMA olumlulardan ÖNCE kontrol et.

# Evet/hayır sorularında ("Okumamı ister misin?") OLUMSUZ/iptal sayılan ifadeler.
_OLUMSUZ_KELIMELER = (
    "okuma", "okumana gerek", "hayır", "hayir", "yok", "istemiyorum", "istemem",
    "gerek yok", "boşver", "boş ver", "olmaz", "vazgeç", "vazgec", "iptal", "dur",
)


def _olumsuz_mi(yanit: str) -> bool:
    # "Okumamı ister misin?" gibi sorulara verilen yanıt OLUMSUZ mu?
    # (Boş yanıt çağıran tarafça ayrıca ele alınır.)
    y = (yanit or "").lower().strip()
    return any(k in y for k in _OLUMSUZ_KELIMELER)


def _mail_eylem_belirle(yanit: str) -> str:
    # Mail başına sorulan "oku / geç / yanıt" sorusunun niyetini sınıflandırır.
    # Dönüş: "oku" | "yanit" | "gec" | "dur"
    # Kontrol SIRASI önemlidir: olumsuz ("okuma") olumludan ("oku") ÖNCE gelir.
    y = (yanit or "").lower().strip()
    if not y:
        return "gec"   # boş yanıt → güvenli varsayılan: sonrakine geç

    # 1) DURDUR — döngüyü temiz bitir. "kontrol" gibi yeni komut girişimleri de
    #    buraya düşsün ki kullanıcı üst seviyede komutu tazeleyebilsin.
    if any(k in y for k in ("dur", "bitir", "yeter", "iptal", "çık", "kapat",
                            "boşver", "boş ver", "vazgeç", "kontrol")):
        return "dur"

    # 2) YANIT
    if any(k in y for k in ("yanıt", "cevap", "yanit")):
        return "yanit"

    # 3) OLUMSUZ OKUMA — "okuma"/"içeriğini okuma" → bu maili OKUMA, geç.
    #    "oku" kontrolünden ÖNCE olmalı (okuma ⊃ oku).
    if "okuma" in y:
        return "gec"

    # 4) GEÇ / SONRAKİ / ATLA / hayır
    if any(k in y for k in ("geç", "sonraki", "atla", "diğer", "next", "hayır", "hayir", "yok")):
        return "gec"

    # 5) OKU / İÇERİK / olumlu
    if any(k in y for k in ("içerik", "oku", "evet", "olur", "tamam", "aç")):
        return "oku"

    # Anlaşılamadı → güvenli: geç
    return "gec"


def mailleri_oku(mod: str):
    """
    Okunmamış önemli mailleri sesli olarak özetler ve her biri için
    kullanıcıya içerik okuma, geçme veya yanıt seçeneği sunar.
    """
    try:
        sonuc    = okunmamis_mailleri_getir()
        onemli   = sonuc["onemli"]
        onemssiz = sonuc["onemssiz"]

        if not onemli and not onemssiz:
            konus("Okunmamış mailin yok.")
            return

        if not onemli:
            konus(f"Önemli okunmamış mailin yok. {len(onemssiz)} reklam/bülten atlandı.")
            return

        # Özet: kimlerden mail geldiğini ve kaç reklamın atlandığını söyle
        gonderen_adlari = list({m["gonderen"] for m in onemli})
        if len(gonderen_adlari) == 1:
            ozet_gonderen = gonderen_adlari[0]
        elif len(gonderen_adlari) <= 3:
            ozet_gonderen = ", ".join(gonderen_adlari[:-1]) + " ve " + gonderen_adlari[-1]
        else:
            ozet_gonderen = f"{gonderen_adlari[0]}, {gonderen_adlari[1]} ve {len(gonderen_adlari)-2} kişi daha"

        reklam_notu = f" {len(onemssiz)} reklam mailini atladım." if onemssiz else ""
        konus(
            f"{ozet_gonderen} kişisinden toplam {len(onemli)} önemli mailin var."
            f"{reklam_notu} Okumamı ister misin?"
        )

        yanit = _kullanici_yaniti_al(mod)
        # Boş yanıt veya OLUMSUZ ("okuma", "hayır", "yok", "dur" …) → okumayı bırak.
        # NOT: "okuma" artık doğru biçimde OLUMSUZ sayılıyor (eskiden "oku" sanılıyordu).
        if not yanit or _olumsuz_mi(yanit):
            konus("Tamam, mailleri geçiyorum.")
            return

        # Her önemli maili sırayla işle
        for i, mail in enumerate(onemli, start=1):
            konus(f"{i}. mail. {mail['gonderen']}'den. Konu: {mail['konu']}.")
            konus("İçeriğini okuyayım mı, sonrakine geçeyim mi, yoksa yanıt mı vereyim?")

            secim = _kullanici_yaniti_al(mod)
            eylem = _mail_eylem_belirle(secim)

            if eylem == "dur":
                # Kullanıcı durmak istedi / yeni bir komut yazdı → döngüyü temiz bitir.
                konus("Tamam, mailleri bırakıyorum.")
                return

            if eylem == "oku":
                # Tam mesajı çekip gövdesini oku
                try:
                    sp      = _gmail_servisi()
                    detay   = sp.users().messages().get(userId="me", id=mail["id"], format="full").execute()
                    govde   = _metin_govdesi_al(detay)
                    if govde:
                        # İlk 500 karakteri oku — çok uzun metinler sesli okumada yorar
                        konus(govde[:500] + ("..." if len(govde) > 500 else ""))
                    else:
                        konus("Mail gövdesi okunamadı veya HTML formatında.")
                except Exception:
                    konus("Mailin içeriğini açamadım.")

            elif eylem == "yanit":
                konus("Yanıtınızı söyleyin veya yazın.")
                yanit_metni = _kullanici_yaniti_al(mod)
                if yanit_metni:
                    mail_yanitla(mail["id"], mail["thread_id"], mail["gonderen_adres"], mail["konu"], yanit_metni)
                else:
                    konus("Yanıt metni alınamadı, geçiyorum.")

            # eylem == "gec" → hiçbir şey yapma, bir sonraki maile geç

        # "okudum" yerine nötr ifade — kullanıcı bazılarını geçmiş olabilir.
        konus("Maillerini gözden geçirdik.")

    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Maillere şu an ulaşamıyorum.")


def mail_gonder(alici: str, konu: str, icerik: str):
    """
    Belirtilen alıcıya Gmail API üzerinden mail gönderir.
    alici : alıcının tam e-posta adresi
    """
    try:
        mesaj = MIMEText(icerik, "plain", "utf-8")
        mesaj["to"]      = alici
        mesaj["subject"] = konu
        ham_veri = base64.urlsafe_b64encode(mesaj.as_bytes()).decode()

        _gmail_servisi().users().messages().send(
            userId="me", body={"raw": ham_veri}
        ).execute()

        konus(f"Mail gönderildi: {alici}.")
    except Exception:
        konus("Mail gönderemedim. İnternet bağlantını veya izinleri kontrol et.")


def mail_yanitla(mail_id: str, thread_id: str, alici: str, orijinal_konu: str, icerik: str):
    """
    Belirli bir mail zincirine (thread) yanıt gönderir.
    Konu "Re:" öneki alır; threadId korunarak zincir bütünlüğü sağlanır.
    """
    try:
        # Orijinal Message-Id başlığını al — In-Reply-To için gerekli
        sp    = _gmail_servisi()
        detay = sp.users().messages().get(userId="me", id=mail_id, format="metadata",
                                          metadataHeaders=["Message-Id"]).execute()
        orijinal_id = _baslik_degerini_al(
            detay.get("payload", {}).get("headers", []), "Message-Id"
        )

        konu = orijinal_konu if orijinal_konu.startswith("Re:") else f"Re: {orijinal_konu}"

        mesaj = MIMEText(icerik, "plain", "utf-8")
        mesaj["to"]         = alici
        mesaj["subject"]    = konu
        if orijinal_id:
            mesaj["In-Reply-To"] = orijinal_id
            mesaj["References"]  = orijinal_id

        ham_veri = base64.urlsafe_b64encode(mesaj.as_bytes()).decode()

        sp.users().messages().send(
            userId="me",
            body={"raw": ham_veri, "threadId": thread_id},
        ).execute()

        konus("Yanıt gönderildi.")
    except Exception:
        konus("Yanıt gönderemedim.")


# ══════════════════════════════════════════════════════════════════════════════
#  KAPSAMLI MAIL KOMUT TABLOSU
# ──────────────────────────────────────────────────────────────────────────────
# TÜM mail komutları TEK kapıdan: mail_komut_isle(metin, mod). komutlar.py yalnızca
# "mail/e-posta" geçen her komutu buraya yollar; niyet ayrımı BURADA yapılır.
#
# YENİ MAIL ÖZELLİĞİ EKLEMEK İÇİN: aşağıya bir niyet dalı + bir fonksiyon ekle.
# komutlar.py'ye DOKUNMANA GEREK YOK. Niyet SIRASI önemli: en spesifik en üstte.
#
# Mevcut niyetler:
#   gönder   : "mail at/gönder [kişi]"            → mail_gonder_etkilesimli
#   sil      : "(reklam) mailleri sil/çöpe at"    → mailleri_sil       (onay ister, çöpe taşır)
#   ara      : "maillerde [terim] ara/bul"        → mail_ara
#   say      : "kaç mailim var"                   → mail_say
#   reklam   : "reklam/spam mailleri oku/göster"  → reklam_maillerini_oku
#   (varsayılan) okunmamış ÖNEMLİ mailleri oku    → mailleri_oku
# ══════════════════════════════════════════════════════════════════════════════

def mail_komut_isle(metin: str, mod: str) -> bool:
    """Mail ile ilgili tüm komutları niyetine göre doğru fonksiyona yönlendirir.

    Dönüş: True (komut ele alındı). komutlar.py bu fonksiyonu çağırıp return False yapar.
    """
    m = (metin or "").lower().strip()

    # 1) GÖNDER — "mail at/gönder [kişi]" (en spesifik: tetikleyici + alıcı)
    for tetik in ("mail at ", "mail gönder ", "e-posta at ", "e-posta gönder ",
                  "eposta at ", "eposta gönder ", "mail yaz "):
        if tetik in m:
            alici = m.split(tetik, 1)[1].strip()
            mail_gonder_etkilesimli(alici, mod)
            return True

    # 2) SİL / ÇÖPE AT — "(reklam) mailleri sil/temizle/çöpe at"
    #    "hepsini/tüm" → tüm okunmamışlar; aksi halde sadece reklam (güvenli varsayılan).
    if any(k in m for k in ("sil", "çöpe at", "çöpe taşı", "temizle")):
        kapsam = "hepsi" if any(k in m for k in ("hepsi", "tüm", "bütün", "tamamı")) else "reklam"
        mailleri_sil(mod, kapsam)
        return True

    # 3) ARA — arama fiili ("ara"/"bul") Türkçe'de hem SONDA ("maillerde fatura ara")
    #    hem ÖNDE ("mail ara fatura") olabilir. Fiili kelime olarak ara, dolgu
    #    kelimelerini (mail/maillerde/ara/bul…) çıkar, kalanı arama terimi yap.
    _toks = m.replace("?", "").split()
    if "ara" in _toks or "bul" in _toks or "arat" in _toks or "arar" in _toks:
        _ARA_DOLGU = {
            "mailde", "maillerde", "maillerimde", "maillerimi", "maillerim",
            "mailleri", "maili", "mail", "e-posta", "eposta", "epostalarda",
            "ara", "arat", "arar", "bul", "içinde", "arasında", "de", "da", "bir",
        }
        terim = " ".join(t for t in _toks if t not in _ARA_DOLGU).strip()
        mail_ara(terim, mod)   # terim boşsa mail_ara "ne aramamı istersin" der
        return True

    # 4) SAY — "kaç mailim var", "mail sayısı"
    if ("kaç mail" in m or "kaç tane mail" in m or "mail sayısı" in m
            or "kaç e-posta" in m or "kaç epostam" in m):
        mail_say(mod)
        return True

    # 5) REKLAM/SPAM OKU-ÖZET — "reklam mailleri oku/göster/özetle/neler/hangi"
    if (any(k in m for k in ("reklam", "spam", "gereksiz", "önemsiz", "bülten"))
            and any(k in m for k in ("oku", "göster", "özet", "listele", "bahset",
                                     "neler", "hangi", "nedir", "var"))):
        reklam_maillerini_oku(mod)
        return True

    # 6) VARSAYILAN — okunmamış ÖNEMLİ mailleri oku (klasik akış)
    mailleri_oku(mod)
    return True


def mail_gonder_etkilesimli(alici_isim: str, mod: str):
    # Kişi adından adres bulur, konu+içerik sorar, mail_gonder ile yollar.
    # kisi_mail_bul gecikmeli import edilir (döngüsel bağımlılık riskini önler).
    if not alici_isim:
        konus("Kime mail atmamı istersin?")
        return
    try:
        from kisiler import kisi_mail_bul
    except Exception:
        konus("Kişi rehberine ulaşamadım.")
        return
    adres = kisi_mail_bul(alici_isim)
    if not adres:
        konus(f"{alici_isim} adında birinin mail adresini bulamadım.")
        return
    konus("Konu nedir?")
    konu = komut_dinle() if mod == "sesli" else yaz().strip()
    if not konu:
        konus("Konu alınamadı, iptal ettim.")
        return
    konus("Mail içeriğini söyle veya yaz.")
    icerik = komut_dinle() if mod == "sesli" else yaz().strip()
    if not icerik:
        konus("İçerik alınamadı, iptal ettim.")
        return
    mail_gonder(adres, konu, icerik)


def _mailleri_cope_tasi(id_listesi: list) -> int:
    # Mailleri Gmail ÇÖP kutusuna taşır (KALICI SİLMEZ — 30 gün geri alınabilir).
    # Kaç tanesinin taşındığını döndürür.
    sp = _gmail_servisi()
    adet = 0
    for mid in id_listesi:
        try:
            sp.users().messages().trash(userId="me", id=mid).execute()
            adet += 1
        except Exception:
            pass   # tek bir mail başarısız olsa da diğerlerine devam et
    return adet


def mailleri_sil(mod: str, kapsam: str = "reklam"):
    # Okunmamış mailleri çöpe taşır. ÖNCE ONAY ister (yıkıcı işlem).
    # kapsam="reklam" → sadece reklam/bülten; "hepsi" → tüm okunmamışlar.
    # Çöpe taşır (kalıcı silmez); kullanıcı isterse Gmail çöpünden geri alır.
    try:
        sonuc = okunmamis_mailleri_getir()
        if kapsam == "hepsi":
            hedef  = sonuc["onemli"] + sonuc["onemssiz"]
            etiket = "okunmamış"
        else:
            hedef  = sonuc["onemssiz"]
            etiket = "reklam"

        if not hedef:
            konus(f"Silinecek {etiket} mail yok.")
            return

        konus(f"{len(hedef)} {etiket} maili çöpe taşıyayım mı? Gmail çöpünden geri alınabilir.")
        yanit = _kullanici_yaniti_al(mod)
        # Açık onay şart: olumsuz veya boşsa SİLME (yıkıcı işlemde güvenli taraf).
        if not yanit or _olumsuz_mi(yanit) or not any(
                k in yanit for k in ("evet", "sil", "olur", "tamam", "onayla", "at")):
            konus("İptal ettim, hiçbir mail silinmedi.")
            return

        adet = _mailleri_cope_tasi([mail["id"] for mail in hedef])
        konus(f"{adet} mail çöpe taşındı.")

    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Mailleri silerken bir sorun oluştu.")


def reklam_maillerini_oku(mod: str):
    # Reklam/bülten (önemsiz) maillerin gönderen+konusunu özetler, silmeyi önerir.
    try:
        reklam = okunmamis_mailleri_getir()["onemssiz"]
        if not reklam:
            konus("Reklam veya bülten türü okunmamış mailin yok.")
            return

        konus(f"{len(reklam)} reklam veya bülten mailin var. İlk birkaçı:")
        for i, mail in enumerate(reklam[:5], start=1):
            konus(f"{i}. {mail['gonderen']}, konu: {mail['konu']}.")
        if len(reklam) > 5:
            konus(f"Ve {len(reklam) - 5} tane daha.")

        konus("Bunları çöpe taşımamı ister misin?")
        yanit = _kullanici_yaniti_al(mod)
        if yanit and not _olumsuz_mi(yanit) and any(
                k in yanit for k in ("evet", "sil", "olur", "tamam", "at", "taşı")):
            adet = _mailleri_cope_tasi([mail["id"] for mail in reklam])
            konus(f"{adet} reklam maili çöpe taşındı.")
        else:
            konus("Tamam, dokunmuyorum.")

    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Maillere şu an ulaşamıyorum.")


def mail_ara(terim: str, mod: str):
    # Gmail araması yapar (q=terim) ve ilk birkaç sonucun gönderen/konusunu okur.
    terim = (terim or "").strip()
    if not terim:
        konus("Maillerde ne aramamı istersin?")
        return
    try:
        sp    = _gmail_servisi()
        liste = sp.users().messages().list(userId="me", q=terim, maxResults=10).execute()
        mesajlar = liste.get("messages", [])
        if not mesajlar:
            konus(f"{terim} ile ilgili bir mail bulamadım.")
            return

        konus(f"{terim} için {len(mesajlar)} mail buldum. İlk birkaçı:")
        for i, m in enumerate(mesajlar[:5], start=1):
            detay = sp.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject"],
            ).execute()
            basliklar = detay.get("payload", {}).get("headers", [])
            gonderen  = _baslik_degerini_al(basliklar, "From")
            konu      = _baslik_degerini_al(basliklar, "Subject") or "(Konusuz)"
            eslesme   = re.match(r"^(.*?)\s*<(.+?)>$", gonderen)
            gon_adi   = eslesme.group(1).strip().strip('"') if eslesme else gonderen
            konus(f"{i}. {gon_adi}, konu: {konu}.")

    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Mail araması yapamadım.")


def mail_say(mod: str):
    # Okunmamış mail sayısını söyler.
    try:
        sp    = _gmail_servisi()
        liste = sp.users().messages().list(userId="me", q="is:unread", maxResults=100).execute()
        adet  = liste.get("resultSizeEstimate", len(liste.get("messages", [])))
        if adet == 0:
            konus("Okunmamış mailin yok.")
        else:
            konus(f"Toplam {adet} okunmamış mailin var.")
    except FileNotFoundError:
        konus("Google kimlik dosyası bulunamadı.")
    except Exception:
        konus("Mail sayısına ulaşamadım.")
