"""Czytnik przepisu ze ŚCIEŻKI mastera (C1, Issue #6) — czysta funkcja, zero DB/Qt/plików.

Kształty ścieżek wzięte z REALNYCH kombinacji archiwum (2026-07-22): `(100,21,10)`×23,
`(100,60,10)`×12, `(100,21,13)`×2, `(0,60,10)`×1 — łącznie 38/38 masterdarków.
"""
import os

from horreum.resolve.recipe import load_patterns, parse_master_path

MASTERDARK = os.path.join(
    r"R:\ASTRO_", "CALIBRATION", "masters", "darks", "ASI2600MM_100_21",
    "MASTERDARK_26MM_G100_O21_10_0300.000_EXPOSURE_300s.xisf")


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
    """Brak dopasowania = PUSTY dict, nigdy wartość domyślna (D-C-2: nastawy się nie wylicza)."""
    assert parse_master_path(r"X:\ARCHIWUM\LIGHTS\M31\A140R_2600MM\Ha\light_0001.fits") == {}
    assert parse_master_path(r"X:\ARCHIWUM\flats\RC8_2600MC\OSC\MASTERFLAT_OSC.xisf") == {}
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


# ─────────────────────────────── masterflat: tokeny NAZWY, nie fakty przepisu (AR-1)

FLAT_A = r"X:\ARCHIWUM\CALIBRATION\masters\flats\RC8_2600MC\OSC\MASTERFLAT_FLATGRP_202203240_FILTER_OSC_.xisf"
FLAT_B = r"X:\ARCHIWUM\CALIBRATION\masters\flats\RC8_2600MC\L-Pro\MASTERFLAT_FLATGRP_202209010_FILTER_LPRO_.xisf"


def test_masterflat_oddaje_grupe_i_filtr_z_nazwy():
    """Wzorzec `masterflat_flatgrp_filter` - grupa i filtr SUROWO z nazwy (tekst, bez kanonu),
    zero faktów przepisu: przepis flata jest cały w nagłówku."""
    facts = parse_master_path(FLAT_A)
    assert facts == {"recipe_class": "flat", "pattern": "masterflat_flatgrp_filter",
                     "flatgrp": "202203240", "filter_name": "OSC"}
    assert parse_master_path(FLAT_B)["filter_name"] == "LPRO"
    assert parse_master_path(FLAT_B.lower())["flatgrp"] == "202209010"
    # Filtr kończy się na `_`, kropce albo separatorze - nie wciąga rozszerzenia ani katalogu.
    assert parse_master_path(r"X:\a\MASTERFLAT_FLATGRP_202408240_FILTER_Ha.xisf")["filter_name"] == "Ha"


def test_masterflat_bez_ktoregos_tokenu_nie_pasuje():
    """Nazwa bez FLATGRP albo bez FILTER nie daje połowy faktów - wzorzec milczy w całości."""
    assert parse_master_path(r"X:\a\MASTERFLAT_FILTER_Ha_.xisf") == {}
    assert parse_master_path(r"X:\a\MASTERFLAT_FLATGRP_202408240_.xisf") == {}
    assert "flatgrp" not in parse_master_path(MASTERDARK)


def test_wzorzec_masterflatu_po_wzorcu_darka():
    """Pierwszy pasujący wygrywa - flat dołożony NA KONIEC listy (kontrakt `parse_master_path`)."""
    nazwy = [p[0] for p in load_patterns()]
    assert nazwy == ["masterdark_zwo_gain_offset_temp", "masterflat_flatgrp_filter"]
    assert load_patterns()[1][1] == "flat"


def test_kalibracja_nie_bierze_tokenow_masterflatu():
    """`calibration._from_path` przepuszcza ze ścieżki wyłącznie dark/bias i wyłącznie gain/offset/
    temperaturę - tokeny nazwy masterflatu nie wchodzą do przepisu żadnej klasy, a fakty darka
    zostają takie jak przed wzorcem flata."""
    from horreum import calibration

    for klasa in ("flat", "dark", "bias"):
        assert calibration._from_path(FLAT_A, klasa) == {}
        assert calibration._from_path(FLAT_B, klasa) == {}
    assert calibration._from_path(MASTERDARK, "dark") == {"gain": 100, "offset_adu": 21,
                                                          "set_temp_c": -10}
    assert calibration._from_path(MASTERDARK, "flat") == {}
