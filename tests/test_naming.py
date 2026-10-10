"""Nazwa STOSU w archiwum (`naming.stack_name`) i tokeny nazwy pliku WBPP (`wbpp_stack_color`,
`wbpp_stack_variants`) - czyste funkcje, zero DB i dysku.

Pinowane co do znaku dwa realne przykłady planu przenosin 0802 (IC1795 mono, IC5068 kamera
kolorowa), kanał `R`, wariant `drizzle_1x` i kolizja nazwy (sufiks `WBPP_<data>` zamiast tokenu
`OBIEKT-<x>`, którego nazwa archiwum nie niesie)."""

import pytest

from horreum import naming

WBPP_IC1795_HA = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-H_mono_OBIEKT-IC1795.xisf"
WBPP_IC5068 = "masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_RGB.xisf"


def test_realny_przyklad_mono_co_do_znaku():
    kolor = naming.wbpp_stack_color(WBPP_IC1795_HA)
    assert kolor == "mono" and naming.wbpp_stack_variants(WBPP_IC1795_HA) == ()
    assert naming.stack_name("IC1795", "2025-12-16T17:27:54", "A140R_2600MM", "Ha", "600.000", kolor) == \
        "IC1795_2025-12-16_A140R_2600MM_Ha_600s_mono.xisf"


def test_realny_przyklad_kamera_kolorowa_rgb_co_do_znaku():
    kolor = naming.wbpp_stack_color(WBPP_IC5068)
    assert kolor == "RGB"
    assert naming.stack_name("IC5068", "2023-08-21T19:02:11.5", "76EDPH_2600MC", "NoFilter", 60.0, kolor) == \
        "IC5068_2023-08-21_76EDPH_2600MC_NoFilter_60s_RGB.xisf"


def test_kolizja_sufiks_wbpp_bez_tokenu_obiektu():
    """Druga integracja tego samego materiału: sufiks `WBPP_<YYYYMMDD>` na końcu, a `OBIEKT-IC1795`
    z nazwy WBPP do nazwy archiwum nie przechodzi (obiekt stoi już na początku)."""
    assert naming.stack_name("IC1795", "2025-12-16T17:27:54", "A140R_2600MM", "Ha", 600.0,
                             naming.wbpp_stack_color(WBPP_IC1795_HA), suffix="WBPP_20260124") == \
        "IC1795_2025-12-16_A140R_2600MM_Ha_600s_mono_WBPP_20260124.xisf"
    assert naming.stack_name("IC1795", "2025-12-16T17:27:54", "A140R_2600MM", "Ha", 600.0, "mono",
                             suffix="WBPP_20260124_2").endswith("_mono_WBPP_20260124_2.xisf")


@pytest.mark.parametrize("nazwa, kolor", [
    ("masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter__R.xisf", "R"),
    ("masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter__G.xisf", "G"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-1800.00s_FILTER-NoFilter__B.xisf", "B"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-R_mono.xisf", "mono"),     # filtr R na mono
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_combined_RGB.xisf", None),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter.xisf", None),
    ("masterLight_X_mono_RGB.xisf", None),
])
def test_kolor_z_nazwy_wbpp(nazwa, kolor):
    """Kanał rozstrzyga `resolve.channel` (litera po filtrze albo ekspozycji, nie goły token), kolor
    pełny - token `mono`/`RGB`; składanka ręki, brak tokenu i sprzeczność → `None`."""
    assert naming.wbpp_stack_color(nazwa) == kolor


def test_kanal_i_drizzle_w_nazwie():
    nazwa = "masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter__R.xisf"
    assert naming.stack_name("LMC", "2023-03-23T22:00:00", "105mm_A7R3", "NoFilter", 121.0,
                             naming.wbpp_stack_color(nazwa)) == "LMC_2023-03-23_105mm_A7R3_NoFilter_121s_R.xisf"
    drizzle = "masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter_RGB_drizzle_1x.xisf"
    assert naming.wbpp_stack_variants(drizzle) == ("drizzle_1x",)
    assert naming.stack_name("LMC", "2023-03-23T22:00:00", "105mm_A7R3", "NoFilter", 121.0,
                             naming.wbpp_stack_color(drizzle), variants=naming.wbpp_stack_variants(drizzle)) == \
        "LMC_2023-03-23_105mm_A7R3_NoFilter_121s_RGB_drizzle_1x.xisf"


def test_warianty_w_stalej_kolejnosci():
    """`autocrop` przed `drizzle_<n>x` niezależnie od kolejności w nazwie WBPP i w argumencie."""
    assert naming.wbpp_stack_variants("masterLight_X_mono_drizzle_2x_autocrop.xisf") == ("autocrop", "drizzle_2x")
    assert naming.stack_name("M31", "2024-09-01T21:00:00", "RC8_2600MM", "L", 300, "mono",
                             variants=("drizzle_2x", "autocrop"), suffix="WBPP_20240902") == \
        "M31_2024-09-01_RC8_2600MM_L_300s_mono_autocrop_drizzle_2x_WBPP_20240902.xisf"


@pytest.mark.parametrize("exptime, token", [("600.000", "600s"), (121.0, "121s"), (0.5, "0.5s"), (15, "15s")])
def test_ekspozycja_format_g(exptime, token):
    assert f"_{token}_mono.xisf" in naming.stack_name("X", "2024-01-01T00:00:00", "R", "Ha", exptime, "mono")


def test_segmenty_przez_sanitize():
    assert naming.stack_name("Heart & Soul", "2024-01-01T00:00:00", "A140R 2600MM", "L-Pro", 60, "RGB") == \
        "Heart_Soul_2024-01-01_A140R_2600MM_L-Pro_60s_RGB.xisf"


@pytest.mark.parametrize("zmiana, fragment", [
    ({"date_obs": None}, "DATE-OBS"),
    ({"date_obs": "2025-12-16"}, "DATE-OBS"),                  # data bez czasu - nie cicha północ
    ({"date_obs": "śmieć"}, "DATE-OBS"),
    ({"color": None}, "kolor"),
    ({"color": "combined_RGB"}, "kolor"),
    ({"exptime": None}, "ekspozycja"),
    ({"obj_seg": "  "}, "pusty segment"),
])
def test_odmowa_valueerror(zmiana, fragment):
    """Brak daty → plan mówi `header_mismatch`, brak koloru → `color_unknown`; reszta to EXPECT."""
    argumenty = {"obj_seg": "IC1795", "date_obs": "2025-12-16T17:27:54", "rig_seg": "A140R_2600MM",
                 "filter_seg": "Ha", "exptime": 600.0, "color": "mono", **zmiana}
    with pytest.raises(ValueError, match=fragment):
        naming.stack_name(argumenty.pop("obj_seg"), argumenty.pop("date_obs"), argumenty.pop("rig_seg"),
                          argumenty.pop("filter_seg"), argumenty.pop("exptime"), argumenty.pop("color"))


def test_odmowa_nieznany_wariant_i_pusty_sufiks():
    with pytest.raises(ValueError, match="wariant"):
        naming.stack_name("X", "2024-01-01T00:00:00", "R", "Ha", 60, "mono", variants=("starless",))
    with pytest.raises(ValueError, match="sufiks"):
        naming.stack_name("X", "2024-01-01T00:00:00", "R", "Ha", 60, "mono", suffix="__")
