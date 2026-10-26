"""AR-349: każde pole wartości budowane w `horreum/gui` przechodzi przez `gui/kolko.kolko` - kółko myszy przestawia
je wyłącznie z fokusem.

Bramka AST (wzór `test_gui_role_rows.py`, bez importu Qt): konstruktor klasy pola, które kółko zmienia (`QComboBox`,
`QSpinBox`, `QDoubleSpinBox`, pola daty i czasu, suwaki - i każda klasa z `horreum/gui`, która z nich dziedziczy), jest
BEZPOŚREDNIM argumentem `kolko(...)`. Dawniej 34 miejsca budowy w 21 funkcjach miały politykę domyślną `WheelFocus`
i kółko nad polem bez kliknięcia przestawiało próg Planera albo park teleskopu. `QScrollBar` jest poza klasą - kółko
to jego funkcja. Pola tworzone wewnątrz okien Qt (`QInputDialog`) bramka nie widzi - te owija się wprost w kodzie."""
import ast
from pathlib import Path

import horreum

_GUI = Path(horreum.__file__).parent / "gui"
_POLA = frozenset({"QComboBox", "QFontComboBox", "QSpinBox", "QDoubleSpinBox", "QDateEdit", "QTimeEdit",
                   "QDateTimeEdit", "QAbstractSpinBox", "QSlider", "QDial"})


def _nazwa(wezel):
    if isinstance(wezel, ast.Name):
        return wezel.id
    if isinstance(wezel, ast.Attribute):
        return wezel.attr
    return None


def _klasy_pol(drzewa):
    """Klasy pól: bazowe Qt + domknięcie podklas zdefiniowanych w podanych modułach."""
    klasy = set(_POLA)
    while True:
        nowe = {w.name for d in drzewa for w in ast.walk(d)
                if isinstance(w, ast.ClassDef) and w.name not in klasy
                and any(_nazwa(b) in klasy for b in w.bases)}
        if not nowe:
            return klasy
        klasy |= nowe


def _konstruktory(drzewo, klasy):
    """`(linia, owinięty)` każdego wywołania konstruktora klasy pola; owinięty = bezpośredni argument `kolko(...)`."""
    owiniete = {id(a) for w in ast.walk(drzewo)
                if isinstance(w, ast.Call) and _nazwa(w.func) == "kolko" for a in w.args}
    return [(w.lineno, id(w) in owiniete) for w in ast.walk(drzewo)
            if isinstance(w, ast.Call) and _nazwa(w.func) in klasy]


def test_pola_wartosci_owiniete_w_kolko():
    """Poza `kolko(...)` żadnego konstruktora pola wartości w `horreum/gui`. Falsyfikator: zdjęcie owinięcia z jednego
    miejsca (np. progu Planera w `PlannerView._spin`)."""
    pliki = sorted(_GUI.rglob("*.py"))
    drzewa = {p: ast.parse(p.read_text(encoding="utf-8")) for p in pliki}
    klasy = _klasy_pol(drzewa.values())
    gole, owinietych = [], 0
    for plik, drzewo in drzewa.items():
        for linia, owiniety in _konstruktory(drzewo, klasy):
            if owiniety:
                owinietych += 1
            else:
                gole.append(f"{plik.relative_to(_GUI).as_posix()}:{linia}")
    assert not gole, f"pole wartości bez `kolko(...)` - kółko przestawi je bez fokusu: {gole}"
    # Podłoga liczności: predykat, który oślepł, nie przechodzi po cichu (34 miejsca budowy w dniu bramki).
    assert owinietych >= 34, owinietych


def test_predykat_kolka_widzi_formy():
    """Predykat na module syntetycznym: goły konstruktor, konstruktor przez moduł, podklasa z tego modułu i owinięcie
    nie wprost (`w = QComboBox(); kolko(w)`) to naruszenia; `kolko(QComboBox())` i odwołanie do klasy bez wywołania
    (`findChild(QDoubleSpinBox)`) - nie."""
    zrodlo = ("a = QComboBox()\n"
              "b = QtWidgets.QSpinBox()\n"
              "class Moje(QDoubleSpinBox):\n    pass\n"
              "c = Moje()\n"
              "w = QComboBox(); kolko(w)\n"
              "d = kolko(QComboBox())\n"
              "e = okno.findChild(QDoubleSpinBox)\n")
    drzewo = ast.parse(zrodlo)
    wynik = sorted(_konstruktory(drzewo, _klasy_pol([drzewo])))
    assert wynik == [(1, False), (2, False), (5, False), (6, False), (7, True)], wynik
