"""Fasada `horreum.gui.grid` (WO-6) - każda nazwa, po którą pakiet, testy i skrypty sięgają przez `grid`,
nadal tam jest, a moduły `grid_*` nie importują fasady (kierunek zależności: moduły → fasada, nigdy wstecz).

Statycznie, AST-em: zbiór nazw czytanych przez `grid` liczony z importów `from horreum.gui.grid import X`
i z atrybutów `alias.X` w zasięgu, w którym `alias` jest związany importem modułu (`app.py` trzyma też
zmienną lokalną `grid = FramesView(...)` - jej atrybuty to nie nazwy modułu). Bez PySide6 plik się pomija,
bo sprawdzenie obecności nazw importuje fasadę."""
import ast
import importlib
from pathlib import Path

import pytest

import horreum

pytest.importorskip("PySide6")

ROOT = Path(horreum.__file__).parent.parent
MODUL = "horreum.gui.grid"
MODULY_WIDOKU = ("grid_model", "grid_panels", "grid_lineage", "grid_selection", "grid_workers")
_ZASIEGI = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _pliki():
    for katalog in ("horreum", "tests", "scripts"):
        for p in sorted((ROOT / katalog).rglob("*.py")):
            if p.name.startswith("grid") and p.parent.name == "gui":
                continue
            yield p


def _wlasne(wezel):
    """Węzły zasięgu bez zagnieżdżonych funkcji (te mają własny zasięg)."""
    stos = list(ast.iter_child_nodes(wezel))
    while stos:
        w = stos.pop()
        yield w
        if not isinstance(w, _ZASIEGI):
            stos.extend(ast.iter_child_nodes(w))


def _aliasy_importu(wezel, plik):
    aliasy = set()
    for w in _wlasne(wezel):
        if isinstance(w, ast.ImportFrom):
            modul = w.module or ""
            if w.level:
                pakiet = ".".join(plik.relative_to(ROOT).with_suffix("").parts[:-w.level])
                modul = pakiet + ("." + modul if modul else "")
            if modul == "horreum.gui":
                aliasy |= {a.asname or a.name for a in w.names if a.name == "grid"}
        elif isinstance(w, ast.Import):
            aliasy |= {a.asname for a in w.names if a.name == MODUL and a.asname}
    return aliasy


def _przypisane(wezel):
    nazwy = set()
    if isinstance(wezel, _ZASIEGI):
        nazwy |= {a.arg for a in ast.walk(wezel.args) if isinstance(a, ast.arg)}
    for w in _wlasne(wezel):
        if isinstance(w, ast.Name) and isinstance(w.ctx, ast.Store):
            nazwy.add(w.id)
    return nazwy


def _czytane(wezel, plik, aliasy, wynik):
    aliasy = (aliasy | _aliasy_importu(wezel, plik)) - _przypisane(wezel)
    for w in _wlasne(wezel):
        if isinstance(w, ast.Attribute) and isinstance(w.value, ast.Name) and w.value.id in aliasy:
            wynik.setdefault(w.attr, set()).add(plik.name)
        elif isinstance(w, ast.ImportFrom) and w.module == MODUL:
            for a in w.names:
                wynik.setdefault(a.name, set()).add(plik.name)
        elif isinstance(w, ast.Constant) and isinstance(w.value, str) and w.value.startswith(MODUL + "."):
            wynik.setdefault(w.value[len(MODUL) + 1:], set()).add(plik.name)   # monkeypatch po ścieżce
        if isinstance(w, _ZASIEGI):
            _czytane(w, plik, aliasy, wynik)


def _nazwy_czytane_przez_fasade():
    wynik = {}
    for p in _pliki():
        _czytane(ast.parse(p.read_text(encoding="utf-8")), p, set(), wynik)
    return wynik


def test_fasada_niesie_kazda_nazwe_czytana_przez_grid():
    grid = importlib.import_module(MODUL)
    czytane = _nazwy_czytane_przez_fasade()
    assert "FramesView" in czytane and "PRESET_VANISHED" in czytane, "skaner nie widzi importerów"
    brak = {n: sorted(pliki) for n, pliki in czytane.items() if not hasattr(grid, n)}
    assert not brak, f"fasada `grid` zgubiła nazwy czytane z zewnątrz: {brak}"


def test_moduly_widoku_nie_importuja_fasady():
    for nazwa in MODULY_WIDOKU:
        drzewo = ast.parse((ROOT / "horreum" / "gui" / f"{nazwa}.py").read_text(encoding="utf-8"))
        for w in ast.walk(drzewo):
            if isinstance(w, ast.ImportFrom):
                assert w.module != MODUL and not (
                    w.module == "horreum.gui" and any(a.name == "grid" for a in w.names)), (
                    f"`{nazwa}` importuje fasadę `grid` - cykl; nazwa ma mieszkać w module niżej")
