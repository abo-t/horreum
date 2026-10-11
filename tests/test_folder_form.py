r"""Forma systemu plików kanonu (`catalog.folder_form`, D-1011-5 Q5), kategoria celu z rodzaju
obiektu (`paths.path_after_object_change`), token obiektu w nazwie pliku (`naming.compose_name`)
i równoważności `catalog_xref.json` dla gestu zmiany obiektu - decyzja D-1011-5. Czyste funkcje,
zero bazy."""
import json
import re
from importlib import resources

import pytest

from horreum import naming
from horreum.resolve.catalog import folder_form, xref, xref_aliases
from horreum.resolve.objects import load_own_objects, resolve_object
from horreum.resolve.paths import (CATEGORY_DIRS, KIND_CATEGORY, STACK_KIND,
                                   path_after_object_change)
from horreum.resolve.solar import _BODIES, _COMET_CANON, resolve_solar

R = "R:\\ASTRO_"
_ZAKAZANE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ═══════════════════════════════════════════════════════════════════ folder_form


@pytest.mark.parametrize("canon, forma", [
    ("C/2025 A6 (Lemmon)", "C2025A6_Lemmon"),
    ("C/2023 A3 (Tsuchinshan-ATLAS)", "C2023A3_Tsuchinshan-ATLAS"),
    ("21P/Giacobini-Zinner", "21P_Giacobini-Zinner"),
    ("C/2019 Y4", "C2019Y4"),                                  # desig bez nazwy (kometa spoza mapy)
    ("D/1993 F2 (Shoemaker-Levy 9)", "D1993F2_Shoemaker-Levy_9"),
])
def test_kometa_dostaje_oznaczenie_bez_ukosnika_i_nazwe(canon, forma):
    assert folder_form(canon) == forma


def test_komety_archiwum_daja_foldery_ktore_archiwum_juz_niesie():
    """Dwa z trzech folderów komet w archiwum (`C2025A6_Lemmon`, `21P_Giacobini-Zinner`) to już
    forma systemu plików; `C2023A3` jest krótszy - ten jeden rozjazd liczy wiersz Porządków."""
    formy = {c: folder_form(c) for c in _COMET_CANON.values()}
    assert formy == {"C/2025 A6 (Lemmon)": "C2025A6_Lemmon",
                     "C/2023 A3 (Tsuchinshan-ATLAS)": "C2023A3_Tsuchinshan-ATLAS",
                     "21P/Giacobini-Zinner": "21P_Giacobini-Zinner"}


def _kanony_assetow():
    """Kanony, które oś obiektu umie dziś postawić bez `/`: słownik obiektów własnych, regiony,
    cele planera, ciała Układu Słonecznego i przykłady każdej gramatyki katalogowej."""
    kanony = {r["c"] for r in load_own_objects()}
    for plik in ("targets_core.json", "targets_cirrus.json"):
        dane = json.loads(resources.files("horreum.data").joinpath(plik).read_text(encoding="utf-8"))
        kanony |= {r["c"] for r in dane["targets"]}
    regiony = json.loads(resources.files("horreum.resolve.data").joinpath("regions.json")
                         .read_text(encoding="utf-8"))
    kanony |= {r["canon"] for r in regiony["regions"]}
    kanony |= set(_BODIES.values())
    kanony |= {"NGC7000", "IC405", "Sh2-229", "M45", "C8", "LBN791", "CTB1", "B33", "Abell2151",
               "vdB30", "Ced214", "Cr464", "G012.2+00.3", "ESO056-115", "HCG092", "UGC7772"}
    return kanony


def test_kanon_bez_ukosnika_jest_swoja_forma_i_dopuszczalnym_folderem():
    """Odwrotność dla głębokiego nieba (69/69 folderów `LIGHTS` z klasy „zgodne” zostaje zgodnych
    - zmierzone na kopii archiwum): kanon bez `/` = folder, bez znaku zakazanego w Windows."""
    kanony = _kanony_assetow()
    assert len(kanony) > 100
    for c in kanony:
        assert "/" not in c
        assert folder_form(c) == c
        assert not _ZAKAZANE.search(folder_form(c)), c


@pytest.mark.parametrize("zly", ["", " M31", "M31 ", ".", "..", "a/b", "C/2025", "a:b", 'a"b',
                                 "C/2025 A6 (Le:mmon)", None, 7])
def test_folder_form_EXPECT_dla_kanonu_nie_do_postawienia(zly):
    with pytest.raises(ValueError):
        folder_form(zly)


@pytest.mark.parametrize("zly", ["CON", "con", "Nul", "PRN", "AUX", "COM1", "com9", "LPT1", "LPT9",
                                 "NUL.txt", "con.abc.def", "NGC7000.", "C/2025 A6 (Foo.)",
                                 "x" * 256, "C/2025 A6 (" + "y" * 250 + ")"])
def test_folder_form_EXPECT_dla_segmentu_ktorego_Windows_nie_przyjmie(zly):
    """Nazwa urządzenia (także z rozszerzeniem), kropka na końcu (Windows ją zdejmuje - podgląd
    kłamałby o pisowni), segment ponad 255 znaków - walidowany WYNIK, także po przekształceniu
    komety."""
    with pytest.raises(ValueError):
        folder_form(zly)


@pytest.mark.parametrize("dobry", ["CONE", "COM10", "LPT10", "NULL", "AUXILIARY", "x" * 255,
                                   "Abell.1x"])
def test_folder_form_przyjmuje_nazwy_podobne_do_zakazanych(dobry):
    assert folder_form(dobry) == dobry


# ═══════════════════════════════════════════════════════════════════ kategoria z rodzaju obiektu


def test_kategorie_maja_jednego_wlasciciela():
    assert CATEGORY_DIRS == frozenset(KIND_CATEGORY.values()) == {"_COMETS", "_SOLAR"}


def test_deep_sky_spod_SOLAR_laduje_wprost_pod_markerem():
    assert path_after_object_change(rf"{R}\LIGHTS\_SOLAR\Saturn\A140R\x.fits", "NGC7000",
                                    object_kind="deep_sky") == rf"{R}\LIGHTS\NGC7000\A140R\x.fits"
    for rodzaj in ("region", "own"):
        assert path_after_object_change(rf"{R}\LIGHTS\_COMETS\12P\cam\x.fit", "Veil",
                                        object_kind=rodzaj) == rf"{R}\LIGHTS\Veil\cam\x.fit"


def test_kometa_z_korzenia_dostaje_COMETS_a_solar_SOLAR():
    assert path_after_object_change(rf"{R}\LIGHTS\NGC3034\RC6\OSC\x.fits", "C/2025 A6 (Lemmon)",
                                    object_kind="comet") == \
        rf"{R}\LIGHTS\_COMETS\C2025A6_Lemmon\RC6\OSC\x.fits"
    assert path_after_object_change("/mnt/a/LIGHTS/M31//cfg/x.fit", "Moon",
                                    object_kind="solar_system") == \
        "/mnt/a/LIGHTS/_SOLAR/Moon//cfg/x.fit"


def test_kategoria_tego_samego_rodzaju_zostaje_w_swojej_pisowni_a_inna_jest_wymieniana():
    assert path_after_object_change(rf"{R}\Lights\_solar\Saturn\cam\x.fit", "Moon",
                                    object_kind="solar_system") == rf"{R}\Lights\_solar\Moon\cam\x.fit"
    assert path_after_object_change(rf"{R}\LIGHTS\_SOLAR\Saturn\cam\x.fit", "21P/Giacobini-Zinner",
                                    object_kind="comet") == \
        rf"{R}\LIGHTS\_COMETS\21P_Giacobini-Zinner\cam\x.fit"


def test_drzewo_stosow_nie_dostaje_kategorii():
    assert path_after_object_change(rf"{R}\STACKS\IC405\cfg\Ha\s.xisf", "C/2025 A6 (Lemmon)",
                                    STACK_KIND, R, object_kind="comet") == \
        rf"{R}\STACKS\C2025A6_Lemmon\cfg\Ha\s.xisf"


# ═══════════════════════════════════════════════════════════════════ token obiektu w nazwie pliku


def _token(canon):
    nazwa, problem = naming.compose_name({"kind": "light", "object_canon": canon, "ext": ".fits"},
                                         None, template=("object",))
    assert problem is None
    return nazwa[:-len(".fits")]


def test_token_obiektu_komety_to_forma_folderu():
    assert _token("C/2025 A6 (Lemmon)") == "C2025A6_Lemmon"          # dawniej C_2025_A6_Lemmon
    assert _token("C/2023 A3 (Tsuchinshan-ATLAS)") == "C2023A3_Tsuchinshan-ATLAS"
    assert _token("21P/Giacobini-Zinner") == "21P_Giacobini-Zinner"


def test_token_obiektu_bez_ukosnika_bajt_w_bajt_jak_przed_zmiana():
    """Dla każdego kanonu bez `/` token = `_sanitize(kanon)` - także dla tekstu, którego `folder_form`
    by nie przyjął (rename klatki z takim kanonem nie wywraca się na EXPECT formy folderu)."""
    for c in sorted(_kanony_assetow()) + ["M 31", " LMC ", "a:b", "Heart & Soul"]:
        assert _token(c) == (naming._sanitize(c) or "_UNSET"), c


# ═══════════════════════════════════════════════════════════════════ równoważności xref


def test_xref_sh2_229_na_IC405_i_M44_na_NGC2632():
    assert xref("Sh2-229") == "IC405"
    assert xref("M44") == "NGC2632"
    assert "Sh2-229" in xref_aliases("IC405") and "M44" in xref_aliases("NGC2632")
    assert resolve_object("Sh2 229").canon == "IC405"
    assert resolve_object("M 44").canon == "NGC2632"
    assert resolve_object("Sh2-190").canon == "IC1805"                 # NGC-wins bez zmian
    assert resolve_solar("Sh2-229") is None
