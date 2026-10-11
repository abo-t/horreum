"""Oś rodzaju klatki: normalize_kind (IMAGETYP → kanon kind, §1.4/§Etap 3).
Mapa = zeznanie firsthand + warianty „na zapas"; nierozpoznane → unknown (nie zgadujemy)."""
import pytest

from horreum.resolve.frames import (HISTORY_MASTER_KINDS, MASTER_IMAGETYP, kind_from_testimony,
                                    normalize_kind)
from horreum.resolve.stack import StackInput


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


# ============================================================ rodzaj z historii integracji (AR-96)

def _hist(*enabled, rows=None):
    """Krotka `parse_history`: `(rows, inputs, tool)`; wejście = `StackInput` z flagą `enabled`."""
    inputs = tuple(StackInput(path=f"D:/W/f{i}_c.xisf", enabled=e, has_drizzle=False)
                   for i, e in enumerate(enabled))
    return (len(inputs) if rows is None else rows), inputs, "process=ImageIntegration"


@pytest.mark.parametrize("imagetyp, history, kind", [
    ("FLAT", _hist(True, False), "master_flat"),       # stary zapis PixInsighta: master jako FLAT
    ("Flat Frame", _hist(True), "master_flat"),
    ("FLAT", _hist(False, False), "flat"),            # zero wejść włączonych - nie dowód mastera
    ("FLAT", (None, (), None), "flat"),               # plik bez historii integracji
    ("FLAT", None, "flat"),                           # FITS/RAW/nieczytelny XML - historii nie ma
    ("Master Flat", _hist(True), "master_flat"),
    ("LIGHT", _hist(True), "light"),                  # mapa zna wyłącznie flat
    ("DARK", _hist(True), "dark"),                    # dark bez populacji - bez reguły
    (None, _hist(True), "unknown"),                   # brak karty: klasy nie zgadujemy z historii
])
def test_kind_from_testimony_master_flat_z_historii(imagetyp, history, kind):
    assert kind_from_testimony(imagetyp, history) == kind


def test_master_imagetyp_wraca_do_rodzaju_mastera():
    """Forma karty pod naprawę nagłówka czytana przez skan daje ten sam rodzaj, co reguła z historii
    - po zapisie karta mówi to, co dziś mówi historia, i drugi plan naprawy jest pusty."""
    for sub, master in HISTORY_MASTER_KINDS.items():
        assert normalize_kind(MASTER_IMAGETYP[master]) == master
        assert kind_from_testimony(MASTER_IMAGETYP[master], None) == master
