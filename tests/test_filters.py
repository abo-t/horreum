"""Oś FILTR — `normalize_filter` (PLAN §3.5/§Etap 6): wariant → kanon; pusty/brak/slot → None (W2,
bez review); nieznany niepusty → verbatim."""
import pytest

from horreum.resolve.filters import normalize_filter


@pytest.mark.parametrize("raw, canon", [
    ("H", "Ha"), ("Ha", "Ha"), ("HA", "Ha"), ("H-alpha", "Ha"), ("Ha3nm", "Ha"),
    ("O", "OIII"), ("OIII", "OIII"), ("O3", "OIII"),
    ("S", "SII"), ("SII", "SII"), ("S2", "SII"),
    ("L", "L"), ("Lum", "L"), ("R", "R"), ("G", "G"), ("B", "B"),
    ("L-Pro", "L-Pro"), ("LPro", "L-Pro"), ("LPRO", "L-Pro"),   # broadband (osobna przestrzeń)
    ("L-eXtreme", "L-eXtreme"), ("L-EX", "L-eXtreme"),
    ("LeXt", "L-eXtreme"), ("LEXT", "L-eXtreme"),               # Etap 6.x firsthand (norma obu=LEXT)
])
def test_normalize_filter_kanon(raw, canon):
    assert normalize_filter(raw) == canon


@pytest.mark.parametrize("raw", [None, "", "NoFilter", "None", "Clear", "EMPTY", "3", "7"])
def test_brak_filtra_lub_slot_to_none(raw):
    """Brak/pusty/none-token (świadomy brak, W2) lub slot numeryczny bez mapy → None (nie review)."""
    assert normalize_filter(raw) is None


def test_nieznany_niepusty_zachowany_verbatim():
    """Nieznany token niepusty → verbatim (zeznanie; mapa rośnie po firsthand, nie zgadujemy)."""
    assert normalize_filter("Tri-band ZWO") == "Tri-band ZWO"
