"""Fasada `horreum.gui.grid` (WO-6) - każda nazwa, po którą pakiet, testy i skrypty sięgają przez `grid`,
nadal tam jest, a moduły `grid_*` nie importują fasady (kierunek zależności: moduły → fasada, nigdy wstecz).

Statycznie, AST-em. Nazwy czytane przez `grid` to: `from horreum.gui.grid import X` (także względne
`from .grid import X`), atrybuty `alias.X` w zasięgu, w którym `alias` jest związany importem modułu
(`from horreum.gui import grid [as g]`, `import horreum.gui.grid as g`), pełny łańcuch
`horreum.gui.grid.X` oraz ścieżka tekstowa `"horreum.gui.grid.X"` (monkeypatch). Zasięgi jak w Pythonie:
przypisanie w ciele klasy nie zasłania globala w metodzie, a `app.py` ze zmienną lokalną
`grid = FramesView(...)` nie wnosi atrybutów instancji jako nazw modułu. Moduły widoku odkrywane z dysku
(`gui/grid_*.py`), więc nowy moduł nie wypada spod żadnej z dwóch bramek."""
import ast
import importlib
from pathlib import Path

import pytest

import horreum

pytest.importorskip("PySide6")

ROOT = Path(horreum.__file__).parent.parent
GUI = ROOT / "horreum" / "gui"
MODUL = "horreum.gui.grid"
MODULY_WIDOKU = ("grid_lineage", "grid_model", "grid_panels", "grid_selection", "grid_workers")
_FUNKCJE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
            ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_ZASIEGI = _FUNKCJE + (ast.ClassDef,)


def _moduly_widoku():
    return tuple(sorted(p.stem for p in GUI.glob("grid_*.py")))


def _pliki():
    pomijane = {GUI / "grid.py"} | {GUI / f"{m}.py" for m in _moduly_widoku()}
    for katalog in ("horreum", "tests", "scripts"):
        for p in sorted((ROOT / katalog).rglob("*.py")):
            if p not in pomijane:
                yield p


def _cel(w, sciezka):
    """Moduł docelowy `ImportFrom` z rozwiązaną względnością (`sciezka` = ścieżka względna od ROOT)."""
    modul = w.module or ""
    if w.level:
        pakiet = ".".join(Path(sciezka).with_suffix("").parts[:-w.level])
        modul = pakiet + ("." + modul if modul else "")
    return modul


def _wlasne(wezel):
    """Węzły zasięgu bez wnętrza zagnieżdżonych zasięgów (te liczy się osobno)."""
    stos = list(ast.iter_child_nodes(wezel))
    while stos:
        w = stos.pop()
        yield w
        if not isinstance(w, _ZASIEGI):
            stos.extend(ast.iter_child_nodes(w))


def _aliasy_importu(wezel, sciezka):
    aliasy = set()
    for w in _wlasne(wezel):
        if isinstance(w, ast.ImportFrom) and _cel(w, sciezka) == "horreum.gui":
            aliasy |= {a.asname or a.name for a in w.names if a.name == "grid"}
        elif isinstance(w, ast.Import):
            aliasy |= {a.asname for a in w.names if a.name == MODUL and a.asname}
    return aliasy


def _przypisane(wezel):
    nazwy = set()
    if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        nazwy |= {a.arg for a in ast.walk(wezel.args) if isinstance(a, ast.arg)}
    for w in _wlasne(wezel):
        if isinstance(w, ast.Name) and isinstance(w.ctx, ast.Store):
            nazwy.add(w.id)
        elif isinstance(w, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nazwy.add(w.name)
    return nazwy


def _czytane(wezel, sciezka, aliasy_zewn, wynik, plik):
    """`aliasy_zewn` = aliasy widoczne z zasięgu otaczającego (dla metod: z modułu, nie z klasy)."""
    aliasy = (aliasy_zewn | _aliasy_importu(wezel, sciezka)) - _przypisane(wezel)
    dla_zagniezdzonych = aliasy_zewn if isinstance(wezel, ast.ClassDef) else aliasy
    for w in _wlasne(wezel):
        if isinstance(w, ast.Attribute):
            if isinstance(w.value, ast.Name) and w.value.id in aliasy:
                wynik.setdefault(w.attr, set()).add(plik)
            elif ast.unparse(w.value) == MODUL:                  # `import horreum.gui.grid` + łańcuch
                wynik.setdefault(w.attr, set()).add(plik)
        elif isinstance(w, ast.ImportFrom) and _cel(w, sciezka) == MODUL:
            for a in w.names:
                wynik.setdefault(a.name, set()).add(plik)
        elif isinstance(w, ast.Constant) and isinstance(w.value, str) and w.value.startswith(MODUL + "."):
            wynik.setdefault(w.value[len(MODUL) + 1:], set()).add(plik)   # monkeypatch po ścieżce
        if isinstance(w, _ZASIEGI):
            _czytane(w, sciezka, dla_zagniezdzonych, wynik, plik)


def _skanuj(zrodlo, sciezka, wynik=None):
    wynik = {} if wynik is None else wynik
    _czytane(ast.parse(zrodlo), sciezka, set(), wynik, Path(sciezka).name)
    return wynik


def _importy_fasady(zrodlo, sciezka):
    """Importy rozwiązujące się do fasady - w każdej formie (absolutny, względny, `import … as`)."""
    trafienia = []
    for w in ast.walk(ast.parse(zrodlo)):
        if isinstance(w, ast.ImportFrom):
            cel = _cel(w, sciezka)
            if cel == MODUL or (cel == "horreum.gui" and any(a.name == "grid" for a in w.names)):
                trafienia.append(ast.unparse(w))
        elif isinstance(w, ast.Import) and any(a.name == MODUL for a in w.names):
            trafienia.append(ast.unparse(w))
    return trafienia


def test_fasada_niesie_kazda_nazwe_czytana_przez_grid():
    grid = importlib.import_module(MODUL)
    czytane = {}
    for p in _pliki():
        _skanuj(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix(), czytane)
    assert "FramesView" in czytane and "PRESET_VANISHED" in czytane, "skaner nie widzi importerów"
    brak = {n: sorted(pliki) for n, pliki in czytane.items() if not hasattr(grid, n)}
    assert not brak, f"fasada `grid` zgubiła nazwy czytane z zewnątrz: {brak}"


def test_moduly_widoku_odkryte_z_dysku_i_bez_importu_fasady():
    assert _moduly_widoku() == MODULY_WIDOKU, (
        "zbiór `gui/grid_*.py` rozjechał się z listą modułów widoku - dopisz nowy moduł do "
        "`MODULY_WIDOKU`, do whitelisty Qt (`test_gui_isolation`) i do docstringu fasady")
    for nazwa in _moduly_widoku():
        sciezka = f"horreum/gui/{nazwa}.py"
        trafienia = _importy_fasady((ROOT / sciezka).read_text(encoding="utf-8"), sciezka)
        assert not trafienia, f"`{nazwa}` importuje fasadę `grid` - cykl; nazwa ma mieszkać niżej: {trafienia}"


@pytest.mark.parametrize("zrodlo", [
    "from . import grid\n",
    "from .grid import FramesView\n",
    "import horreum.gui.grid as grid\n",
    "from horreum.gui import grid\n",
    "from horreum.gui.grid import FramesView\n",
])
def test_bramka_cyklu_lapie_kazda_forme_importu(zrodlo):
    assert _importy_fasady(zrodlo, "horreum/gui/grid_nowy.py")


@pytest.mark.parametrize("zrodlo, sciezka", [
    ("from .grid import BRAK\n", "horreum/gui/inny.py"),
    ("from horreum.gui.grid import BRAK\n", "tests/test_x.py"),
    ("import horreum.gui.grid\nx = horreum.gui.grid.BRAK\n", "tests/test_x.py"),
    ("import horreum.gui.grid as g\nx = g.BRAK\n", "tests/test_x.py"),
    ("def f():\n    from horreum.gui import grid\n    return grid.BRAK\n", "horreum/gui/app.py"),
    ("from horreum.gui import grid as g\nclass C:\n    g = object()\n    def f(self):\n        return g.BRAK\n",
     "tests/test_x.py"),
    ("x = 'horreum.gui.grid.BRAK'\n", "tests/test_x.py"),
])
def test_skaner_widzi_nazwe_w_kazdej_formie(zrodlo, sciezka):
    assert "BRAK" in _skanuj(zrodlo, sciezka)


def test_skaner_nie_bierze_atrybutow_zmiennej_lokalnej():
    zrodlo = ("def montaz():\n    grid = FramesView()\n    grid.refresh()\n"
              "def motyw():\n    from horreum.gui import grid\n    grid.use_theme('x')\n")
    czytane = _skanuj(zrodlo, "horreum/gui/app.py")
    assert "use_theme" in czytane and "refresh" not in czytane
