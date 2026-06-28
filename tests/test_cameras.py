"""Oś KAMERA: normalize_camera (1:1 z Custosa, Duo→MD, idempotencja) + is_mono (§3.2)
+ camera_identity (wyłuskanie osi z nagłówka, §3.1/§3.6, agnostyczność §5.8)."""
import pytest

from horreum.resolve.cameras import camera_identity, is_mono, normalize_camera


@pytest.mark.parametrize("instrume, expected", [
    ("ZWO ASI2600MM Pro", "ASI2600MM"),
    ("ZWO ASI2600MC Pro", "ASI2600MC"),
    ("ZWO ASI2600MM Duo", "ASI2600MD"),       # sensor MM, body Duo = osobna kamera (A1)
    ("ZWO ASI294MC Pro", "ASI294MC"),
    ("ASI2600MM", "ASI2600MM"),
])
def test_normalize_camera_warianty(instrume, expected):
    assert normalize_camera(instrume) == expected


def test_normalize_camera_puste():
    assert normalize_camera(None) is None
    assert normalize_camera("") is None


def test_normalize_camera_idempotentne():
    """normalize(normalize(x)) == normalize(x) — kanon nie traci tokenów przy ponownym przejściu
    (inwariant osi tożsamości; MD w alternacji łapie już-znormalizowaną formę Duo)."""
    for instrume in ("ZWO ASI2600MM Pro", "ZWO ASI2600MM Duo", "ZWO ASI2600MC Pro", "ASI294"):
        once = normalize_camera(instrume)
        assert normalize_camera(once) == once


def test_asi294_bez_sufiksu_to_luka():
    """'ASI294' bez MM/MC nie dostaje sufiksu — trafi w fallback/review w module nie-2600 (F10).
    Tu sprawdzamy tylko, że normalize nie wymyśla sufiksu."""
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
    """BAYERPAT obecny → kolor z najmocniejszego źródła (priorytet nad modelem)."""
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MC Pro", "XPIXSZ": 3.76, "BAYERPAT": "RGGB"})
    assert (ident.is_mono, ident.is_mono_source) == (0, "bayerpat")


def test_camera_identity_asi294_bez_sufiksu_os_powstaje_mono_review():
    """Agnostyczność (§5.8): ASI294 bez sufiksu NIE wywala — oś powstaje (model+pixel), a is_mono
    wpada na review (brak BAYERPAT i brak modelu rozstrzygającego mono/kolor)."""
    ident = camera_identity({"INSTRUME": "ASI294", "XPIXSZ": 4.63})
    assert (ident.model_canon, ident.pixel_um) == ("ASI294", 4.63)
    assert (ident.is_mono, ident.is_mono_source) == (None, "review")


def test_camera_identity_sony_fits_os_powstaje_mono_review():
    """Sony-w-FITS z XPIXSZ: oś powstaje, ale mono nierozstrzygnięte → review (§5.8)."""
    ident = camera_identity({"INSTRUME": "ILCE-7M3", "XPIXSZ": 4.86})
    assert ident.pixel_um == 4.86
    assert (ident.is_mono, ident.is_mono_source) == (None, "review")


def test_camera_identity_brak_instrume_niederywowalne():
    """Brak INSTRUME → brak model_canon → None (review należy do warstwy frame, §4.2)."""
    assert camera_identity({"XPIXSZ": 3.76}) is None


def test_camera_identity_brak_xpixsz_niederywowalne():
    """Brak XPIXSZ → brak pixel_um (część klucza UNIQUE, NOT NULL) → None."""
    assert camera_identity({"INSTRUME": "ZWO ASI2600MM Pro"}) is None
