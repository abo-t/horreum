"""Oś OBIEKT — `resolve_object` (PLAN §3.5/§Etap 6): oznaczenie katalogowe + xref + nazwy potoczne;
nierozpoznane → None (warstwa wyżej decyduje o delcie — TYLKO light/master_light)."""
import pytest

from horreum.resolve.objects import resolve_object


def test_oznaczenie_katalogowe_source_header():
    """Czyste oznaczenie z nagłówka (kanon bez xref) → source='header'; zapis znormalizowany."""
    o = resolve_object("NGC 4258")
    assert (o.canon, o.catalog, o.kind, o.source) == ("NGC4258", "NGC", "deep_sky", "header")
    assert o.alias_norm == "NGC4258"


def test_messier_mapowany_przez_xref():
    """M106 → NGC4258 (NGC-wins) → source='catalog_xref'; alias_norm zachowuje formę surową (M106)."""
    o = resolve_object("M106")
    assert (o.canon, o.catalog, o.source) == ("NGC4258", "NGC", "catalog_xref")
    assert o.alias_norm == "M106"


def test_messier_bez_ngc_zostaje_messierem():
    """M45 (Plejady) nie ma NGC → kanon M45, source='header' (xref bez zmiany)."""
    o = resolve_object("M 45")
    assert (o.canon, o.catalog, o.source) == ("M45", "Messier", "header")


@pytest.mark.parametrize("raw, canon, catalog", [
    ("Rosette Nebula", "NGC2237", "NGC"),       # nazwa potoczna + zdjęty deskryptor
    ("Pelican", "IC5070", "IC"),
    ("Elephant's Trunk", "Sh2-131", "Sh2"),     # firsthand: realny light (apostrof zniesiony)
    ("North America Nebula", "NGC7000", "NGC"),
    ("Cigar Galaxy", "NGC3034", "NGC"),         # Etap 6.x: → M82 → (xref) NGC3034 (scala z „M 82")
    ("Flaming Star Nebula", "IC405", "IC"),     # Etap 6.x: folder Sh2-229, brak rodzeństwa katalog.
    ("Bubble Nebula", "NGC7635", "NGC"),        # Etap 6.x: scala z „NGC 7635"
])
def test_nazwy_potoczne_source_common_name(raw, canon, catalog):
    o = resolve_object(raw)
    assert (o.canon, o.catalog, o.source, o.kind) == (canon, catalog, "common_name", "deep_sky")


def test_nazwa_potoczna_przez_messier_xref():
    """Bode's Galaxy → (common) M81 → (xref) NGC3031: łańcuch potoczna→Messier→NGC."""
    o = resolve_object("Bode's Galaxy")
    assert (o.canon, o.source) == ("NGC3031", "common_name")


@pytest.mark.parametrize("raw", ["FlatWizard", "Snapshot", "Mur", "Lemmon", "Target", "", None])
def test_nierozpoznane_to_none(raw):
    """Nie-obiekt / sentinel narzędzia / solar-comet (Lemmon) / pusty → None. Bez zgadywania —
    spadają do delty (lub poprawnego NULL kalibracji) w warstwie resolvera."""
    assert resolve_object(raw) is None
