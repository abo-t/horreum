"""Oś rodzaju klatki: normalize_kind (IMAGETYP → kanon kind, §1.4/§Etap 3).
Mapa = zeznanie firsthand + warianty „na zapas"; nierozpoznane → unknown (nie zgadujemy)."""
import pytest

from horreum.resolve.frames import normalize_kind


@pytest.mark.parametrize("imagetyp, kind", [
    # FITS firsthand (2600): LIGHT/Light/Light Frame → light; FLAT → flat
    ("LIGHT", "light"),
    ("Light", "light"),
    ("Light Frame", "light"),
    ("FLAT", "flat"),
    # XISF firsthand: LIGHT/FLAT (case-insensitive jak FITS) + Master Flat/Master Dark
    ("Master Flat", "master_flat"),
    ("Master Dark", "master_dark"),
    # „na zapas" (agnostyczność §5.8 — w archiwum 2600 nieobecne, mapa ma je gotowe)
    ("DARK", "dark"),
    ("Dark Frame", "dark"),
    ("BIAS", "bias"),
    ("Master Light", "master_light"),
    ("Integration", "master_light"),
])
def test_normalize_kind_warianty_firsthand(imagetyp, kind):
    assert normalize_kind(imagetyp) == kind


@pytest.mark.parametrize("imagetyp", [None, "", "   "])
def test_normalize_kind_brak_to_unknown(imagetyp):
    """Brak IMAGETYP (None/pusty/same białe znaki) → unknown (jawne, nie zgadywanie)."""
    assert normalize_kind(imagetyp) == "unknown"


@pytest.mark.parametrize("imagetyp", ["FlatWizard", "Snapshot", "Target", "foobar 123"])
def test_normalize_kind_nierozpoznane_to_unknown(imagetyp):
    """Niepuste, ale niezmapowane → unknown (sygnał do rozszerzenia mapy; warstwa zapisu doda
    event informacyjny — §Etap 4). NIE udajemy dopasowania."""
    assert normalize_kind(imagetyp) == "unknown"


@pytest.mark.parametrize("imagetyp, kind", [
    ("light_frame", "light"),          # underscore jako separator
    ("  Light   Frame  ", "light"),    # kolaps wielokrotnych spacji + strip
    ("MASTER  FLAT", "master_flat"),   # case + podwójna spacja
    ("master_dark", "master_dark"),
    ("flat frame", "flat"),            # generyczne zdjęcie „ frame"
    ("bias frame", "bias"),
])
def test_normalize_kind_kolaps_i_frame(imagetyp, kind):
    """Case-insensitive, kolaps białych znaków/`_`, zdjęcie końcowego „ frame" (Light Frame→light)."""
    assert normalize_kind(imagetyp) == kind


def test_normalize_kind_master_like_dla_query():
    """Wszystkie mastery zaczynają się od 'master_' (kryterium „WHERE kind LIKE 'master_%'", §1.4)."""
    for imagetyp in ("Master Flat", "Master Dark", "Master Light", "Integration"):
        assert normalize_kind(imagetyp).startswith("master_")


def test_normalize_kind_2600_zero_unknown():
    """Kryterium §5: realne IMAGETYP z FITS-2600 (LIGHT/Light/Light Frame/FLAT) — ZERO unknown."""
    realne_2600 = ["LIGHT", "Light", "Light Frame", "FLAT"]
    assert all(normalize_kind(v) != "unknown" for v in realne_2600)
