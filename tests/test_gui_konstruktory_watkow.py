"""Bramka AST (AR-333): konstruktor klasy warstwy widżetów, który przechodnio startuje wątek tła, jest failure-atomic.

Wątek tła (`QThread`, `threading.Thread`) wystartowany w `__init__` żyje, zanim gospodarz dostanie obiekt - wyjątek
dalej w konstruktorze zostawia go poza każdym sprzątaniem (`QThread` skasowany w biegu to twardy abort aplikacji;
`FramesView` zostawiał też blokadę szuflady i drugi wątek). Reguła: instrukcja `__init__`, która (przechodnio
przez wywołania `self.metoda()` w obrębie klasy) startuje wątek, jest OSTATNIĄ instrukcją konstruktora (poza
gołymi przypisaniami stałej do atrybutu `self`) albo stoi w obwódce `try` / `except`, która woła
`self.zatrzymaj_pola()` i kończy się gołym `raise`. Instrukcja złożona (`if`, `with`, `for`) - ta sama reguła w
każdej jej gałęzi. Bramka czyta źródło, więc łapie też konstruktor, którego żaden test dziś nie buduje.

ŚLEPOTA (świadoma): bramka widzi wyłącznie start w ciele metody tej samej klasy i wywołania `self.metoda()`. Nie
widzi startu przez sygnał (zegar, `QTimer.singleShot`, połączenie, które odpala później), przez inny obiekt
(`self.pole.metoda()`, funkcja modułu, klasa bazowa) ani przez `getattr`. Klasa, która startuje wątek taką drogą,
przechodzi bramkę bez względu na kolejność - dla niej zostaje test dynamiczny (wzór `FramesView`:
`tests/test_gui_strony_leniwe.py`, porażka konstruktora po starcie wątków)."""
import ast
from pathlib import Path

import horreum

GUI = Path(horreum.__file__).parent / "gui"


def _wykonywane(wezel):
    """Węzły poddrzewa, które biegną razem z nim - bez ciał lambd i funkcji zagnieżdżonych (te biegną później,
    zwykle z sygnału: `clicked.connect(lambda: self.metoda())` w budowie widoku niczego nie startuje)."""
    stos = [wezel]
    while stos:
        n = stos.pop()
        yield n
        stos.extend(d for d in ast.iter_child_nodes(n)
                    if not isinstance(d, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)))


def _start_watku(wezel):
    """Czy w poddrzewie jest bezpośrednie utworzenie wątku: `QThread(…)` albo `threading.Thread(…)`."""
    for n in _wykonywane(wezel):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "QThread":
                return True
            if (isinstance(f, ast.Attribute) and f.attr == "Thread" and isinstance(f.value, ast.Name)
                    and f.value.id == "threading"):
                return True
    return False


def _wolane_metody(wezel):
    """Nazwy metod wołanych jako `self.nazwa(…)` w poddrzewie (poza lambdami i funkcjami zagnieżdżonymi)."""
    return {n.func.attr for n in _wykonywane(wezel)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"}


def _startujace(metody):
    """Metody klasy, które startują wątek wprost albo przechodnio przez `self.metoda()` (punkt stały)."""
    startujace = {nazwa for nazwa, f in metody.items() if _start_watku(f)}
    zmiana = True
    while zmiana:
        zmiana = False
        for nazwa, f in metody.items():
            if nazwa not in startujace and _wolane_metody(f) & startujace:
                startujace.add(nazwa)
                zmiana = True
    return startujace


def _instrukcja_startuje(instrukcja, startujace):
    return _start_watku(instrukcja) or bool(_wolane_metody(instrukcja) & startujace)


def _obwodka(instrukcja):
    """`try` z handlerem, który woła `self.zatrzymaj_pola()` i kończy się gołym `raise`."""
    if not isinstance(instrukcja, ast.Try):
        return False
    for h in instrukcja.handlers:
        if ("zatrzymaj_pola" in _wolane_metody(h) and h.body and isinstance(h.body[-1], ast.Raise)
                and h.body[-1].exc is None):
            return True
    return False


def _trywialna(instrukcja):
    """Gołe przypisanie stałej do atrybutu `self` - nie ma porażki, którą trzeba by zwijać."""
    return (isinstance(instrukcja, ast.Assign) and isinstance(instrukcja.value, ast.Constant)
            and all(isinstance(c, ast.Attribute) and isinstance(c.value, ast.Name) and c.value.id == "self"
                    for c in instrukcja.targets))


def _naruszenia(cialo, startujace):
    """Instrukcje, które biegną PO starcie wątku poza obwódką (numery linii)."""
    for i, instrukcja in enumerate(cialo):
        if not _instrukcja_startuje(instrukcja, startujace):
            continue
        po = [r.lineno for r in cialo[i + 1:] if not _trywialna(r)]
        if _obwodka(instrukcja):
            return po
        for galaz in ("body", "orelse"):
            if isinstance(instrukcja, (ast.If, ast.With, ast.For, ast.While)):
                po += _naruszenia(getattr(instrukcja, galaz, []), startujace)
        return po
    return []


def _konstruktory_z_watkiem():
    """`{(plik, klasa): (startuje, naruszenia, obwódka)}` dla klas, których `__init__` startuje wątek."""
    wynik = {}
    for plik in sorted(GUI.rglob("*.py")):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        for klasa in (n for n in ast.walk(drzewo) if isinstance(n, ast.ClassDef)):
            metody = {f.name: f for f in klasa.body if isinstance(f, ast.FunctionDef)}
            init = metody.get("__init__")
            if init is None:
                continue
            startujace = _startujace(metody)
            if not any(_instrukcja_startuje(i, startujace) for i in init.body):
                continue
            wynik[(plik.relative_to(GUI).as_posix(), klasa.name)] = (
                _naruszenia(init.body, startujace), any(_obwodka(i) for i in init.body))
    return wynik


def test_konstruktor_ze_startem_watku_jest_failure_atomic():
    """Każdy konstruktor, który startuje wątek tła, kończy się startem albo trzyma go w obwódce sprzątającej.
    Asercja pozytywna: bramka widzi znane dziś konstruktory z wątkiem (bez tego byłaby zielona na pustym zbiorze),
    a `FramesView` przechodzi wyłącznie dzięki obwódce. Falsyfikatory: obwódka zdjęta z `FramesView.__init__`;
    instrukcja dopisana za startem wątku w konstruktorze Domu."""
    znalezione = _konstruktory_z_watkiem()
    klasy = {k for _p, k in znalezione}
    assert {"FramesView", "HomeView", "PlannerView", "TasksView", "HarvestDialog", "ObjectChangeDialog"} <= klasy, (
        sorted(klasy))
    naruszenia = {klucz: po for klucz, (po, _o) in znalezione.items() if po}
    assert not naruszenia, f"konstruktor startuje wątek, a po starcie biegnie dalej bez obwódki (linie): {naruszenia}"
    assert znalezione[("grid.py", "FramesView")][1], "FramesView bez obwódki porażki konstruktora"
