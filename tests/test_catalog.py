"""catalog_xref — asset ładuje się przez importlib.resources (jedzie w wheelu, bramka clone'a) +
rozpoznanie oznaczenia (`catalog_canon`), równoważność (`xref`) i etykieta (`catalog_label`)."""
import pytest

from horreum.resolve.catalog import (
    catalog_canon, catalog_label, load_catalog_xref, xref,
)


def test_catalog_xref_laduje_sie():
    x = load_catalog_xref()
    assert {"messier_to_ngc", "caldwell_to_ngc", "sh2_to_ic", "cross_to_ngc"} <= set(x)


def test_ngc_wins_forma():
    """Messier/Caldwell = alias-only -> rozwiązują się do klucza NGC/IC (polityka NGC-wins)."""
    x = load_catalog_xref()
    assert x["messier_to_ngc"]["M106"] == "NGC4258"
    assert x["caldwell_to_ngc"]["C23"] == "NGC891"
    assert x["sh2_to_ic"]["Sh2-190"] == "IC1805"


# --- catalog_canon: rozpoznanie + normalizacja zapisu (§3.5) ---

@pytest.mark.parametrize("raw, expected", [
    ("NGC 4736", "NGC4736"),       # spacja precz
    ("NGC4736", "NGC4736"),
    ("ngc 224", "NGC224"),         # case-insensitive
    ("NGC 0224", "NGC224"),        # zera wiodące precz
    ("Sh2 131", "Sh2-131"),        # Sharpless: spacja -> myślnik
    ("SH2-131", "Sh2-131"),
    ("M 81", "M81"),
    ("Messier 81", "M81"),
    ("IC1805", "IC1805"),
    ("C 23", "C23"),
    ("LDN 1174", "LDN1174"),
    ("vdB 142", "vdB142"),
])
def test_catalog_canon_rozpoznaje_i_normalizuje(raw, expected):
    assert catalog_canon(raw) == expected


@pytest.mark.parametrize("raw", ["Heart Nebula", "Bode's Galaxy", "FlatWizard", "Snapshot", "", None])
def test_catalog_canon_nie_oznaczenie_to_none(raw):
    """Nazwa potoczna / nie-obiekt NIE udaje kanonu (None) — koniec cichego śmieciowego kanonu."""
    assert catalog_canon(raw) is None


def test_catalog_canon_zapis_dwuczlonowy_tylko_podkreslnik():
    """Etap 6.x firsthand: 'NGC4631_PGC42637' → pierwszy człon 'NGC4631' (scala z 'NGC4631').
    Rozdzielnik to WYŁĄCZNIE '_'; oznaczenia ze spacją wewnętrzną = JEDEN człon, nietknięte —
    regresja na ostrzeżonych przypadkach. Prefiks nie-oznaczenie → None (bez over-matchu)."""
    assert catalog_canon("NGC4631_PGC42637") == "NGC4631"
    assert catalog_canon("Sh 2-184") == "Sh2-184"       # spacja ≠ rozdzielnik (NIE 'SH'+'2-184')
    assert catalog_canon("Caldwell 23") == "C23"         # j.w. — jeden człon ze spacją
    assert catalog_canon("Foo_Bar") is None              # prefiks nie-oznaczenie → None


# --- xref: równoważność międzykatalogowa (NGC-wins, DANYMI) ---

def test_xref_messier_caldwell_sh2_na_ngc_ic():
    assert xref("M106") == "NGC4258"        # Messier -> NGC
    assert xref("C23") == "NGC891"          # Caldwell -> NGC
    assert xref("Sh2-190") == "IC1805"      # Sharpless -> IC (realny bliźniak, danymi)


def test_xref_brak_wpisu_bez_zmiany():
    """Brak wpisu → kanon bez zmian: M45 (Plejady) nie ma NGC → zostaje M45; NGC bez xref też."""
    assert xref("M45") == "M45"
    assert xref("NGC4258") == "NGC4258"
    assert xref("Sh2-131") == "Sh2-131"     # Trąba Słonia — Sh2 zachowany (brak bliźniaka IC w danych)


# --- catalog_label: etykieta z formy kanonicznej ---

@pytest.mark.parametrize("canon, label", [
    ("NGC4258", "NGC"), ("IC1805", "IC"), ("Sh2-131", "Sh2"),
    ("M45", "Messier"), ("C23", "Caldwell"), ("LDN1174", "LDN"),
    ("vdB142", "vdB"), ("Ced214", "Ced"), ("Cr399", "Collinder"), ("B33", "Barnard"),
])
def test_catalog_label(canon, label):
    assert catalog_label(canon) == label
