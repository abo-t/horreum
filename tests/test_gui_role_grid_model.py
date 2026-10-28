"""AR-357: role, wyrównania, flagi i stałe stylu modelu Zbiorów jako stałe modułu `horreum/gui/grid_model.py`.

Skrót trybu zgodności PySide6 (`Qt.DisplayRole`, `Qt.AlignRight`, `QStyle.PM_…`) kosztuje ~2 µs na dostęp wobec ~11 ns
stałej modułu, a `GridTableModel.data` i delegaty płacą go w każdej komórce kadru i w każdym wierszu rachunku
szerokości (natywnie na kopii pf4: malowanie kadru klasycznej 47,7 → 28,5 ms, `_szerokosci_znajdz` 82,2 → 30,4 ms).

Bramka AST: w metodach `GridTableModel`, `_ElizjaWSrodku`, `_DelegatBelki` i w funkcjach szerokości z treści zero
węzłów `Attribute` o korzeniu `Qt`, `QStyle`, `QStyleOptionViewItem`, `QTextOption` - poza wartościami domyślnymi
argumentów (liczone raz przy `def`) i metodami zimnymi z nazwy (sort - raz na gest). Stałe pinuje dokładny słownik
nazw, wartości i typów; typ zwrotu `flags()` i roli wyrównania - test na prawdziwym modelu.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from horreum import pivot as pivot_mod
from horreum.gui import grid_model

_KORZENIE = {"Qt", "QStyle", "QStyleOptionViewItem", "QTextOption"}
_KLASY = ("GridTableModel", "_ElizjaWSrodku", "_DelegatBelki")
_FUNKCJE = ("szerokosc_z_tresci", "kolumna_z_tresci", "szerokosci_z_tresci", "_szerokosc_tekstu")
# Metody zimne: raz na gest sortu, poza drogą komórki i malowania.
_ZIMNE = {"GridTableModel.sort", "GridTableModel.sort_order"}


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _korzen(wezel):
    while isinstance(wezel, ast.Attribute):
        wezel = wezel.value
    return wezel.id if isinstance(wezel, ast.Name) else None


def _skroty_qt(funkcja):
    """Najwyższe węzły łańcucha `Attribute` o korzeniu z `_KORZENIE` w funkcji (także w funkcjach zagnieżdżonych) -
    bez wartości domyślnych argumentów."""
    pomin = set()
    for d in [*funkcja.args.defaults, *(x for x in funkcja.args.kw_defaults if x is not None)]:
        pomin |= set(ast.walk(d))
    rodzic = {dziecko: w for w in ast.walk(funkcja) for dziecko in ast.iter_child_nodes(w)}
    return [w for w in ast.walk(funkcja) if isinstance(w, ast.Attribute) and _korzen(w) in _KORZENIE
            and w not in pomin and not isinstance(rodzic.get(w), ast.Attribute)]


def _drzewo_modulu():
    return ast.parse(Path(grid_model.__file__).read_text(encoding="utf-8"))


def test_metody_modelu_i_delegatow_bez_skrotow_qt():
    """Każda metoda trzech klas i każda funkcja szerokości z treści bez skrótu Qt. Podłoga: każda klasa i funkcja
    znaleziona, a metody zimne istnieją (wyjątek nie oślepnie po zmianie nazwy). Falsyfikator: `role == Qt.DisplayRole`
    w nowej metodzie modelu."""
    metody = {}
    for w in _drzewo_modulu().body:
        if isinstance(w, ast.ClassDef) and w.name in _KLASY:
            metody.update({f"{w.name}.{f.name}": f for f in w.body
                           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))})
        elif isinstance(w, ast.FunctionDef) and w.name in _FUNKCJE:
            metody[w.name] = w
    assert {n.split(".")[0] for n in metody if "." in n} == set(_KLASY)
    assert set(_FUNKCJE) <= set(metody), sorted(set(_FUNKCJE) - set(metody))
    assert _ZIMNE <= set(metody), sorted(_ZIMNE - set(metody))
    trafienia = {n: sorted({ast.unparse(x) for x in _skroty_qt(f)}) for n, f in metody.items() if n not in _ZIMNE}
    assert not {n: t for n, t in trafienia.items() if t}


def test_predykat_bramki_rol_na_zrodle_syntetycznym():
    """Predykat na źródle syntetycznym: skrót roli, pełna ścieżka enuma (jeden węzeł - najwyższy), `QStyle`,
    `QStyleOptionViewItem`, oba człony wyrównania i `QTextOption` - trafienia; wartości domyślne argumentów, stała
    modułu i `x.Qt.Y` - nie."""
    zrodlo = ("def f(role=Qt.DisplayRole, *, k=QStyle.PM_X):\n"
              "    a = Qt.DisplayRole\n"
              "    b = Qt.ItemDataRole.DisplayRole\n"
              "    c = QStyle.PM_FocusFrameHMargin\n"
              "    d = QStyleOptionViewItem.WrapText\n"
              "    e = int(Qt.AlignRight | Qt.AlignVCenter)\n"
              "    g = QTextOption.WrapMode.WordWrap\n"
              "    h = _ROLA_TEKSTU\n"
              "    i = x.Qt.Y\n"
              "    return a, b, c, d, e, g, h, i, role, k\n")
    funkcja = ast.parse(zrodlo).body[0]
    assert sorted((w.lineno, ast.unparse(w)) for w in _skroty_qt(funkcja)) == [
        (2, "Qt.DisplayRole"), (3, "Qt.ItemDataRole.DisplayRole"), (4, "QStyle.PM_FocusFrameHMargin"),
        (5, "QStyleOptionViewItem.WrapText"), (6, "Qt.AlignRight"), (6, "Qt.AlignVCenter"),
        (7, "QTextOption.WrapMode.WordWrap")]


# Dokładny słownik stałych modułu: nazwa → (wartość, typ). Role - liczby Qt (`Qt::ItemDataRole`), wyrównanie
# liczb `AlignRight | AlignVCenter` = 0x82 jako `int` (zwrot roli wyrównania), flagi i stałe stylu - enumy.
_STALE = {
    "_ROLA_TEKSTU": (0, int),
    "_ROLA_PODPOWIEDZI": (3, int),
    "_ROLA_KOLORU": (9, int),
    "_ROLA_CZCIONKI": (6, int),
    "_ROLA_WYROWNANIA": (7, int),
    "_ROLA_EDYCJI": (2, int),
    "_ROLA_TLA": (8, int),
    "_WYROWNANIE_LICZB": (0x82, int),
    "_FLAGA_EDYCJI": (Qt.ItemFlag.ItemIsEditable, Qt.ItemFlag),
    "_FLAGI_BELKI": (Qt.ItemFlag.ItemIsEnabled, Qt.ItemFlag),
    "_POZIOMO": (Qt.Orientation.Horizontal, Qt.Orientation),
    "_ELIZJA_W_SRODKU": (Qt.TextElideMode.ElideMiddle, Qt.TextElideMode),
    "_ELIZJA_Z_PRAWEJ": (Qt.TextElideMode.ElideRight, Qt.TextElideMode),
    "_BEZ_ZAWIJANIA": (~QStyleOptionViewItem.ViewItemFeature.WrapText, QStyleOptionViewItem.ViewItemFeature),
    "_PROSTOKAT_TEKSTU": (QStyle.SubElement.SE_ItemViewItemText, QStyle.SubElement),
    "_MARGINES_RAMKI": (QStyle.PixelMetric.PM_FocusFrameHMargin, QStyle.PixelMetric),
    "_ELEMENT_KOMORKI": (QStyle.ControlElement.CE_ItemViewItem, QStyle.ControlElement),
}


def test_stale_rol_dokladnie():
    """Stałe modułu wyznaczone PREDYKATEM (przypisanie na poziomie modułu, którego wartość czyta `Qt.`, `QStyle.`,
    `QStyleOptionViewItem.` albo `QTextOption.`) = dokładnie słownik wyżej: nazwa, wartość i typ. Falsyfikatory: stała
    usunięta, wartość z literówką roli, rola jako `ItemDataRole` zamiast `int`."""
    nazwy = set()
    for w in _drzewo_modulu().body:
        if isinstance(w, ast.Assign) and any(isinstance(x, ast.Attribute) and _korzen(x) in _KORZENIE
                                             for x in ast.walk(w.value)):
            nazwy |= {t.id for t in w.targets if isinstance(t, ast.Name)}
    stale = {n: (getattr(grid_model, n), type(getattr(grid_model, n))) for n in sorted(nazwy)}
    assert stale == _STALE


def test_flagi_modelu_sa_item_flag(qapp):
    """`flags()` zwraca `Qt.ItemFlag` (jak baza `QAbstractTableModel.flags`) dla belki grupy, komórki keyworda
    edytowalnej i komórki bazowej - z Pythona i przez `QModelIndex.flags` (C++); rola wyrównania kolumny liczb to
    `int`. Falsyfikator: flaga edycji jako `int`."""
    from horreum.gui.grid_model import BASE_COLS, GridTableModel
    wspolne = {"_telescope": "", "camera_model": None, "filter_canon": None, "filetype": "fits",
               "present": 1, "n_present": 1, "_images": "3"}
    base = [{"frame_id": 1, "path": "/a/f1.fits", "kind": "light", "_object": "M51", **wspolne},
            {"frame_id": 2, "path": "/a/f2.fits", "kind": "flat", "_object": "", **wspolne}]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 2], ["GAIN"], []), ["GAIN"], group_by="kind")
    m.set_editable(True)
    belka = next(i for i, r in enumerate(m._rows) if "_group" in r)
    wiersz = next(i for i, r in enumerate(m._rows) if r.get("frame_id") == 1)
    komorki = {"belka": m.index(belka, 0), "keyword edytowalny": m.index(wiersz, len(BASE_COLS)),
               "bazowa": m.index(wiersz, 0)}
    assert m.flags(komorki["keyword edytowalny"]) & Qt.ItemFlag.ItemIsEditable
    assert not m.flags(komorki["bazowa"]) & Qt.ItemFlag.ItemIsEditable
    assert m.flags(komorki["belka"]) == Qt.ItemFlag.ItemIsEnabled
    for nazwa, idx in komorki.items():
        assert type(m.flags(idx)) is Qt.ItemFlag, nazwa
        assert type(idx.flags()) is Qt.ItemFlag, nazwa
    obrazy = m.index(wiersz, [k for _, k in BASE_COLS].index("_images"))
    wyrownanie = m.data(obrazy, Qt.TextAlignmentRole)
    assert type(wyrownanie) is int
    assert wyrownanie == int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
