"""AR-326: rejestr ról elementów w `horreum/gui/rows.py` - jedno miejsce numerów `Qt.UserRole + n` w pakiecie.

Bramka AST: wyrażenie `<...>.UserRole + <stała>` (także `Qt.ItemDataRole.UserRole + n`) stoi wyłącznie w `rows.py`;
każdy inny moduł bierze stałą z rejestru. Dawniej numery żyły w sześciu modułach i dwie role z różnych modułów
lądowały na tym samym numerze tej samej listy (W-5) - zgadywanie wolnego numeru zastępuje jeden przegląd rejestru.
"""
import ast
from pathlib import Path

import horreum

_KORZEN = Path(horreum.__file__).parent


def _przesuniecia_rol(drzewo):
    """Węzły `BinOp` z `UserRole` po jednej stronie dodawania i stałą liczbową po drugiej."""
    def _user_role(w):
        return isinstance(w, ast.Attribute) and w.attr == "UserRole"
    for w in ast.walk(drzewo):
        if (isinstance(w, ast.BinOp) and isinstance(w.op, ast.Add)
                and ((_user_role(w.left) and isinstance(w.right, ast.Constant))
                     or (_user_role(w.right) and isinstance(w.left, ast.Constant)))):
            yield w


def test_numery_rol_wylacznie_w_rejestrze_rows():
    """Poza `gui/rows.py` żadnego `UserRole + n`. Falsyfikator: stała roli z powrotem w module konsumenta."""
    poza = []
    w_rejestrze = 0
    for plik in sorted(_KORZEN.rglob("*.py")):
        wezly = list(_przesuniecia_rol(ast.parse(plik.read_text(encoding="utf-8"))))
        if plik.relative_to(_KORZEN).as_posix() == "gui/rows.py":
            w_rejestrze = len(wezly)
        else:
            poza += [f"{plik.relative_to(_KORZEN).as_posix()}:{w.lineno}" for w in wezly]
    assert not poza, f"numer roli poza rejestrem `rows.py`: {poza}"
    # Podłoga liczności: predykat, który oślepł, nie przechodzi po cichu (rejestr ma dziś 14 ról).
    assert w_rejestrze >= 14, w_rejestrze


def test_predykat_rol_widzi_obie_pisownie():
    """Predykat bramki na module syntetycznym: `Qt.UserRole + 3`, `Qt.ItemDataRole.UserRole + 2` i `5 + Qt.UserRole`
    to przesunięcia; `Qt.UserRole` samo, `x + 1` i `Qt.UserRole - 1` - nie."""
    zrodlo = ("A = Qt.UserRole + 3\nB = Qt.ItemDataRole.UserRole + 2\nC = 5 + Qt.UserRole\n"
              "D = Qt.UserRole\nE = x + 1\nF = Qt.UserRole - 1\n")
    linie = sorted(w.lineno for w in _przesuniecia_rol(ast.parse(zrodlo)))
    assert linie == [1, 2, 3]


def test_role_rejestru_unikalne_na_wspolnych_listach():
    """Role wiersza czytane przez `TwoPartDelegate` (pasmo {+1, +2, +3, +6}) nie pokrywają się z rolami danych
    list, które biorą ten delegat (facety, kolejka przeglądu osi obiektu) ani z rodzajem koloru."""
    from horreum.gui import rows
    pasmo = {rows.SECONDARY, rows.TERTIARY, rows.STRONG, rows.INDENT}
    assert len(pasmo) == 4
    for rola in (rows.ROLA_PODPOWIEDZI_FACETU, rows.ROLA_PRZEGLADU_PAYLOAD, rows.ROLA_PRZEGLADU_INFO,
                 rows.ROLA_RODZAJU_KOLORU):
        assert rola not in pasmo, rola
    assert len({rows.ROLA_PRZEGLADU_PAYLOAD, rows.ROLA_PRZEGLADU_INFO, rows.ROLA_RODZAJU_KOLORU}) == 3
    assert len({rows.ROLA_KAMERY_GRUPY, rows.ROLA_FOLDERU_GRUPY, rows.ROLA_GRUPY}) == 3
