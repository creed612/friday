# aura_teshis.py — ASUS Aura HID teşhis aracı
#
# AMAÇ: "Aura cihazına erişemedim" hatasının GERÇEK sebebini bulmak.
# Üç olası durum: (1) hidapi kurulu değil, (2) cihaz bulunamadı,
# (3) bulundu ama feature report reddedildi.
#
# ÇALIŞTIR: YÖNETİCİ olarak, G-Helper KAPALI iken:
#   python aura_teshis.py
# Çıktının TAMAMINI kopyala-yapıştır.

print("=" * 70)
print(" ASUS AURA HID TEŞHİS")
print("=" * 70)

# ── 1) hidapi kurulu mu? ──────────────────────────────────────────────────────
try:
    import hid
    print("[1] hidapi: KURULU ✓")
except Exception as e:
    print(f"[1] hidapi: KURULU DEĞİL ✗  → hata: {e}")
    print("    ÇÖZÜM: pip install hidapi")
    print("    (Kurulu ama DLL hatası veriyorsa: pip install hidapi --force-reinstall)")
    raise SystemExit(0)

ASUS_VENDOR = 0x0B05
MAIN_AURA_PIDS = {
    0x1a30, 0x1854, 0x1869, 0x1866, 0x19b6, 0x1822, 0x1837, 0x184a, 0x183d,
    0x8502, 0x1807, 0x17e0, 0x1abe, 0x1b4c, 0x1b6e, 0x1b2c, 0x8854, 0x1ce7,
    0x1bf2,
}
REAR_LIGHT_PIDS = {0x18c6}
INPUT_ID = 0x5A

# ── 2) TÜM ASUS (0x0B05) HID cihazlarını listele ─────────────────────────────
print()
print("[2] Vendor 0x0B05 (ASUS) altındaki TÜM HID arayüzleri:")
print("-" * 70)
try:
    asus_cihazlar = list(hid.enumerate(ASUS_VENDOR, 0))
except Exception as e:
    print(f"    hid.enumerate hatası: {e}")
    asus_cihazlar = []

if not asus_cihazlar:
    print("    HİÇBİR 0x0B05 cihazı bulunamadı!")
    print("    → Klavye farklı bir vendor altında olabilir. Aşağıdaki [3]'e bak.")
else:
    for d in asus_cihazlar:
        pid = d.get("product_id")
        listede = "MAIN_AURA ✓" if pid in MAIN_AURA_PIDS else (
            "REAR_LIGHT" if pid in REAR_LIGHT_PIDS else "LİSTEDE YOK!")
        print(
            f"    PID={pid:#06x} [{listede}]  "
            f"arayüz={d.get('interface_number')}  "
            f"usage_page={d.get('usage_page'):#06x}  usage={d.get('usage'):#04x}"
        )
        print(f"        ürün='{d.get('product_string')}'  yol={d.get('path')}")

# ── 3) TÜM HID cihazlarını tara, ASUS/klavye olabilecekleri işaretle ─────────
print()
print("[3] Sistemdeki TÜM HID cihazları (klavye/ASUS ipuçları işaretli):")
print("-" * 70)
try:
    hepsi = list(hid.enumerate())
except Exception as e:
    hepsi = []
    print(f"    hid.enumerate() hatası: {e}")

for d in hepsi:
    vid = d.get("vendor_id")
    urun = (d.get("product_string") or "").lower()
    imalat = (d.get("manufacturer_string") or "").lower()
    ilginc = (vid == ASUS_VENDOR
              or "asus" in urun or "asus" in imalat
              or "aura" in urun
              or "keyboard" in urun or "klavye" in urun
              or "rog" in urun or "tuf" in urun)
    if ilginc:
        print(
            f"    VID={vid:#06x} PID={d.get('product_id'):#06x}  "
            f"usage_page={d.get('usage_page'):#06x} usage={d.get('usage'):#04x}  "
            f"arayüz={d.get('interface_number')}  ürün='{d.get('product_string')}'"
        )

# ── 4) MAIN_AURA_PIDS eşleşen cihazlara TEST parlaklık raporu gönder ─────────
print()
print("[4] Aday Aura cihazlarına TEST parlaklık raporu (seviye=3, 64 ve 65 byte):")
print("-" * 70)
adaylar = [d for d in asus_cihazlar if d.get("product_id") in MAIN_AURA_PIDS]
if not adaylar:
    print("    MAIN_AURA_PIDS eşleşen cihaz YOK → bu yüzden 'erişemedim' dedi.")
    print("    Yukarıdaki [2]/[3] listesinden klavyenin gerçek PID'sini bulalım.")
else:
    paket_base = [INPUT_ID, 0xBA, 0xC5, 0xC4, 3]
    for d in adaylar:
        pid = d.get("product_id")
        print(f"    → PID={pid:#06x} arayüz={d.get('interface_number')} açılıyor...")
        dev = hid.device()
        try:
            dev.open_path(d["path"])
        except Exception as e:
            print(f"        AÇILAMADI: {e}")
            continue
        for uzunluk in (64, 65):
            tampon = bytes(paket_base + [0] * (uzunluk - len(paket_base)))
            try:
                sonuc = dev.send_feature_report(tampon)
                print(f"        {uzunluk} byte → send_feature_report döndü: {sonuc}"
                      + ("  (BAŞARI?)" if sonuc is not None and sonuc >= 0 else "  (RED)"))
            except Exception as e:
                print(f"        {uzunluk} byte → HATA: {e}")
        try:
            dev.close()
        except Exception:
            pass

print()
print("=" * 70)
print(" TEŞHİS BİTTİ — çıktının TAMAMINI paylaş.")
print("=" * 70)
