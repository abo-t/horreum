"""Oś KAMERA: normalize_camera (1:1 z Custosa, Duo→MD, idempotencja) + is_mono (§3.2)."""
import pytest

from horreum.resolve.cameras import is_mono, normalize_camera


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
