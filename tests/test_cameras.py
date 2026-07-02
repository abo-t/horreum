"""Oś KAMERA: normalize_camera (1:1 z Custosa, Duo→MD, idempotencja) + is_mono (§3.2)
+ camera_identity (wyłuskanie osi z nagłówka, §3.1/§3.6, agnostyczność §5.8,
Reguła B OSC→MC i rzut typu W3 — §Etap 2)."""
import pytest

from horreum.resolve.cameras import camera_identity, is_mono, normalize_camera


@pytest.mark.parametrize("instrume, expected", [
    ("ZWO ASI2600MM Pro", "ASI2600MM"),
    ("ZWO ASI2600MC Pro", "ASI2600MC"),
    ("ZWO ASI2600MM Duo", "ASI2600MD"),       # sensor MM, body Duo = osobna kamera (A1)
    ("ZWO ASI294MC Pro", "ASI294MC"),
    ("ASI2600MM", "ASI2600MM"),
    ("Sony A7RM3", "SONYA7RM3"),               # forma akwizycji FITS (dawca)
    ("Sony ILCE-7RM3A", "SONYA7RM3"),          # forma PixInsight XISF — TEN SAM korpus (fold PF-4)
    ("Sony ILCE-7RM3", "SONYA7RM3"),           # wariant bez sufiksu 'A'
])
def test_normalize_camera_warianty(instrume, expected):
    assert normalize_camera(instrume) == expected


def test_normalize_camera_puste():
    assert normalize_camera(None) is None
    assert normalize_camera("") is None


def test_normalize_camera_idempotentne():
    """normalize(normalize(x)) == normalize(x) — kanon nie traci tokenów przy ponownym przejściu
    (inwariant osi tożsamości; MD w alternacji łapie już-znormalizowaną formę Duo)."""
    for instrume in ("ZWO ASI2600MM Pro", "ZWO ASI2600MM Duo", "ZWO ASI2600MC Pro", "ASI294",
                     "Sony ILCE-7RM3A", "Sony A7RM3"):
        once = normalize_camera(instrume)
        assert normalize_camera(once) == once


def test_normalize_camera_asi294_bez_sufiksu_zostaje_surowy():
    """Separacja warstw: `normalize_camera` świadomie NIE dopisuje sufiksu (normalizer „głupi").
    Domknięcie OSC = Reguła B w `camera_identity`, gdy BAYERPAT potwierdzi kolor (§Etap 2/§5.8
    POPRAWIONE) — nie tutaj."""
    assert normalize_camera("ASI294") == "ASI294"


# --- is_mono (reguła jednokierunkowa, §3.2) ---

def test_is_mono_bayerpat_obecny_to_kolor():
    assert is_mono(bayerpat="RGGB", model_canon="ASI2600MC") == (0, "bayerpat")


def test_is_mono_mm_bez_bayerpat_to_mono():
    assert is_mono(bayerpat=None, model_canon="ASI2600MM") == (1, "model")


def test_is_mono_md_to_mono():
    assert is_mono(bayerpat=None, model_canon="ASI2600MD") == (1, "model")


def test_is_mono_mc_bez_bayerpat_to_kolor_z_modelu():
    assert is_mono(bayerpat=None, model_canon="ASI2600MC") == (0, "model")


def test_is_mono_dslr_raw_to_kolor():
    assert is_mono(bayerpat=None, model_canon=None, raw_format="raw_sony") == (0, "raw_format")


def test_is_mono_sony_fits_bez_modelu_to_review():
    """Sony zapisane jako FITS bez BAYERPAT, bez modelu ZWO, bez raw_format → review (NIE udaje
    mono) — krytyczny przypadek F10."""
    assert is_mono(bayerpat=None, model_canon=None, raw_format=None) == (None, "review")


# --- camera_identity: wyłuskanie osi KAMERA z nagłówka (§3.1/§3.6) ---

def test_camera_identity_mm_z_modelu():
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MM Pro", "XPIXSZ": 3.76})
    assert (ident.model_canon, ident.pixel_um) == ("ASI2600MM", 3.76)
    assert (ident.is_mono, ident.is_mono_source) == (1, "model")
    assert ident.raw_instrume == "ZWO ASI2600MM Pro"


def test_camera_identity_mc_kolor_z_bayerpat():
    """BAYERPAT obecny → kolor z najmocniejszego źródła (priorytet nad modelem). Reguła B nie
    dotyka modelu z sufiksem (`^ASI\\d+$` nie łapie `ASI2600MC`) — idempotencja."""
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MC Pro", "XPIXSZ": 3.76, "BAYERPAT": "RGGB"})
    assert ident.model_canon == "ASI2600MC"
    assert (ident.is_mono, ident.is_mono_source) == (0, "bayerpat")


def test_camera_identity_asi294_z_bayerpat_regula_B_dopisuje_mc():
    """Reguła B (§Etap 2): ZWO bez sufiksu + kolor potwierdzony BAYERPAT → `ASI294`→`ASI294MC`.
    Firsthand: 445/445 ASI294 mają BAYERPAT (kolor, NIE review — §5.8 POPRAWIONE)."""
    ident = camera_identity({"INSTRUME": "ASI294", "XPIXSZ": 4.63, "BAYERPAT": "RGGB"})
    assert (ident.model_canon, ident.pixel_um) == ("ASI294MC", 4.63)
    assert (ident.is_mono, ident.is_mono_source) == (0, "bayerpat")


def test_camera_identity_asi294_bez_bayerpat_regula_B_nie_strzela():
    """Agnostyczność (§5.8): ASI294 BEZ BAYERPAT → Reguła B nie strzela (nie zgadujemy MM/MD).
    Oś powstaje (`ASI294`, pixel), is_mono=review — domknięcie tylko przy potwierdzonym kolorze."""
    ident = camera_identity({"INSTRUME": "ASI294", "XPIXSZ": 4.63})
    assert (ident.model_canon, ident.pixel_um) == ("ASI294", 4.63)
    assert (ident.is_mono, ident.is_mono_source) == (None, "review")


def test_camera_identity_sony_fits_z_bayerpat_kolor_placeholder():
    """Sony Mirrorless (konwersja DNG→FITS) z BAYERPAT → kolor; oś powstaje jako placeholder.
    Firsthand: 100/100 mają BAYERPAT (4.86 RGGB). Reguła B go NIE tyka (regex `^ASI\\d+$` ZWO-only);
    mapowanie na konkretne body ILCE = drugi przebieg (RAW)."""
    ident = camera_identity({"INSTRUME": "Sony Mirrorless Camera", "XPIXSZ": 4.86, "BAYERPAT": "RGGB"})
    assert ident.pixel_um == 4.86
    assert (ident.is_mono, ident.is_mono_source) == (0, "bayerpat")
    assert not ident.model_canon.endswith("MC")   # Reguła B nie dopisuje sufiksu nie-ZWO


def test_camera_identity_brak_instrume_niederywowalne():
    """Brak INSTRUME → brak model_canon → None (review należy do warstwy frame, §4.2)."""
    assert camera_identity({"XPIXSZ": 3.76}) is None


def test_camera_identity_brak_xpixsz_os_powstaje_pixel_none():
    """KONTRAKT ODWRÓCONY (PF-2, R1#3/R2#4): brak XPIXSZ NIE blokuje osi — tożsamość = model;
    pixel_um=None to nieznana WŁAŚCIWOŚĆ (uzupełni ją upsert_camera z innego zeznania).
    Rozwiązuje dziwactwo „Sony masterflat bez XPIXSZ"."""
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MM Pro"})
    assert ident is not None
    assert (ident.model_canon, ident.pixel_um) == ("ASI2600MM", None)
    assert (ident.is_mono, ident.is_mono_source) == (1, "model")


def test_camera_identity_xpixsz_string_z_xisf_rzutowany_na_float():
    """W3: XISF zwraca XPIXSZ jako string (`'3.76'`); pole gorące rzutowane na float → IDENTYCZNA
    oś co z FITS-float. Inaczej `UNIQUE(model_canon, pixel_um)` rozbiłby kamerę FITS-vs-XISF."""
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MC Pro", "XPIXSZ": "3.76", "BAYERPAT": "RGGB"})
    assert ident.pixel_um == 3.76
    assert isinstance(ident.pixel_um, float)


def test_camera_identity_xpixsz_pusty_string_pixel_none():
    """W3 brzeg: XPIXSZ pusty (`''`, jak w ubogich nagłówkach) → `_to_float`→None → oś POWSTAJE
    z pixel_um=None (kontrakt odwrócony PF-2), nie crash i nie blok."""
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MM Pro", "XPIXSZ": ""})
    assert ident is not None and ident.pixel_um is None
