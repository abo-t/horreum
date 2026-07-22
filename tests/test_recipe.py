"""Czytnik przepisu ze ŚCIEŻKI mastera (C1, Issue #6) — czysta funkcja, zero DB/Qt/plików.

Kształty ścieżek wzięte z REALNYCH kombinacji archiwum (2026-07-22): `(100,21,10)`×23,
`(100,60,10)`×12, `(100,21,13)`×2, `(0,60,10)`×1 — łącznie 38/38 masterdarków.
"""
import os

from horreum.resolve.recipe import load_patterns, parse_master_path

MASTERDARK = os.path.join(
    r"R:\ASTRO_", "CALIBRATION", "masters", "darks", "ASI2600MM_100_21",
    "MASTERDARK_26MM_G100_O21_10_0300.000_EXPOSURE_300s.xisf")
MASTERFLAT = os.path.join(
    r"R:\ASTRO_", "CALIBRATION", "masters", "flats", "76EDPH_2600MM", "Ha",
    "MASTERFLAT_FLATGRP_202304220_FILTER_Ha_.xisf")


def test_masterdark_oddaje_komplet_faktow():
    """Realny kształt → gain/offset/temperatura/czas + ślad wzorca i klasa przepisu."""
    facts = parse_master_path(MASTERDARK)
    assert facts["recipe_class"] == "dark"
    assert facts["gain"] == 100
    assert facts["offset_adu"] == 21
    assert facts["set_temp_c"] == -10
    assert facts["exptime_path"] == 300.0
    assert facts["pattern"] == "masterdark_zwo_gain_offset_temp"


def test_znak_temperatury_z_assetu_nie_z_nazwy():
    """Człon `_13_` niesie MODUŁ nastawy; minus dokłada reguła `temp_sign` z assetu (chłodzenie).
    Potwierdzenie: nastawy `SET-TEMP` lightów to -10,0 i -13,0, nigdy dodatnie 10/13."""
    p = MASTERDARK.replace("_O21_10_", "_O21_13_")
    assert parse_master_path(p)["set_temp_c"] == -13


def test_gain_zero_to_wartosc_nie_brak():
    """`G000` = gain 0 (realna kombinacja `(0,60,10)`), nie „brak faktu" — ta sama pułapka,
    którą `extract_header` pilnuje dla nagłówka (`GAIN=0` to wartość)."""
    p = MASTERDARK.replace("_G100_O21_", "_G0_O60_")
    facts = parse_master_path(p)
    assert facts["gain"] == 0
    assert facts["offset_adu"] == 60


def test_typy_zgodne_z_derywacja_naglowka():
    """Rzuty idą przez `_coerce` (jak `extract_header`): gain/offset/temp to `int`, czas to `float`
    — inaczej `g=100` ze ścieżki i `g=100.0` z nagłówka dałyby DWA przepisy jednej nastawy."""
    facts = parse_master_path(MASTERDARK)
    assert isinstance(facts["gain"], int) and not isinstance(facts["gain"], bool)
    assert isinstance(facts["offset_adu"], int)
    assert isinstance(facts["set_temp_c"], int)
    assert isinstance(facts["exptime_path"], float)


def test_sciezka_spoza_wzorca_to_zero_faktow():
    """Brak dopasowania = PUSTY dict, nigdy wartość domyślna (D-C-2: nastawy się nie wylicza).
    Masterflat CELOWO nie pasuje — jego przepis jest cały w nagłówku (73/73), więc ścieżka
    nie ma tam czego dokładać (zmierzone: 0/76 masterflatów łapie ten wzorzec)."""
    assert parse_master_path(MASTERFLAT) == {}
    assert parse_master_path(r"R:\ASTRO_\LIGHTS\M31\A140R_2600MM\Ha\light_0001.fits") == {}
    assert parse_master_path("") == {}
    assert parse_master_path(None) == {}


def test_wzorce_pochodza_z_assetu():
    """Konwencja nazewnicza jednego archiwum żyje w `master_paths.json` (jak `regions.json`),
    nie w kodzie — inny użytkownik dokłada wzorzec bez tykania Pythona."""
    pats = load_patterns()
    assert pats and pats[0][0] == "masterdark_zwo_gain_offset_temp"
    assert pats[0][1] == "dark"
    assert pats[0][3] == -1                      # temp_sign: negative → mnożnik -1


def test_wielkosc_liter_sciezki_bez_znaczenia():
    """Windows nie rozróżnia wielkości liter w ścieżkach — wzorzec też nie może."""
    assert parse_master_path(MASTERDARK.lower())["gain"] == 100
