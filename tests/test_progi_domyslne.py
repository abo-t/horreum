"""AR-371: wartości domyślne pięciu progów planera mają JEDNO źródło w rdzeniu (`targets.DEFAULT_THRESHOLDS`) - czytają
je `targets.plan`, `targets.feasible`, GUI (`planner._THRESHOLDS`) i CLI (bez flagi próg nie jest podawany). Dawniej te
same liczby stały w czterech miejscach, a dopisek „(domyślnie 6′)” w tytule paska progów ogłaszałby kopię GUI.

Bez Qt: bramka czyta źródła modułów przez AST (`gui/planner.py` bez importu), CLI biegnie na bazie w pliku."""
import ast
import inspect
from pathlib import Path

import pytest

import horreum
from horreum import cli, db, targets

_PKG = Path(horreum.__file__).parent
_PROGI = ("min_size", "min_dark", "max_mag", "min_alt", "min_hours")
_FLAGI = {"--min-size", "--min-dark", "--max-mag", "--min-alt", "--min-hours"}


def test_wartosci_domyslne_progow_w_rdzeniu():
    """Pin decyzji (D-0731-10): 6′ rozmiaru, 15′ ciemnej, 13 mag, 30° wysokości, 1 h na kanał. Stała tylko do odczytu -
    domyślne argumentów wiążą się przy imporcie, więc zmieniony w locie słownik rozjechałby się z nimi.
    Falsyfikator: zwykły `dict` zamiast `MappingProxyType` (przypisanie przechodzi)."""
    assert dict(targets.DEFAULT_THRESHOLDS) == {"min_size": 6.0, "min_dark": 15.0, "max_mag": 13.0,
                                                "min_alt": 30.0, "min_hours": 1.0}
    with pytest.raises(TypeError):
        targets.DEFAULT_THRESHOLDS["min_size"] = 8.0
    for nazwa, funkcja in (("plan", targets.plan), ("feasible", targets.feasible)):
        parametry = inspect.signature(funkcja).parameters
        for prog in _PROGI:
            if prog in parametry:
                assert parametry[prog].default == targets.DEFAULT_THRESHOLDS[prog], (nazwa, prog)


def _odczyt_stalej(wezel, *, przez_modul):
    """Czy wyrażenie to `DEFAULT_THRESHOLDS["<próg>"]` (w `targets`) albo `targets.DEFAULT_THRESHOLDS["<próg>"]`."""
    if not (isinstance(wezel, ast.Subscript) and isinstance(wezel.slice, ast.Constant)):
        return None
    v = wezel.value
    if przez_modul:
        trafia = (isinstance(v, ast.Attribute) and v.attr == "DEFAULT_THRESHOLDS"
                  and isinstance(v.value, ast.Name) and v.value.id == "targets")
    else:
        trafia = isinstance(v, ast.Name) and v.id == "DEFAULT_THRESHOLDS"
    return wezel.slice.value if trafia else None


def _drzewo(nazwa):
    return ast.parse((_PKG / nazwa).read_text(encoding="utf-8"))


def test_rdzen_cli_i_planer_czytaja_jedno_zrodlo_progow():
    """Bramka AST (predykat, nie wyliczanka): domyślne pięciu progów w `targets.plan` i `targets.feasible` to odczyty
    `DEFAULT_THRESHOLDS`, drugi element krotki `planner._THRESHOLDS` to `targets.DEFAULT_THRESHOLDS[…]` tego samego
    progu, a pięć flag progów CLI ma `default=None`. Podłogi liczności: predykat, który oślepł, nie przechodzi po cichu.
    Falsyfikatory: literał `6.0` w sygnaturze `plan`, w `_THRESHOLDS` albo w parserze CLI."""
    funkcje = {w.name: w for w in ast.walk(_drzewo("targets.py")) if isinstance(w, ast.FunctionDef)}
    for nazwa, ile in (("plan", 5), ("feasible", 3)):
        f = funkcje[nazwa]
        domyslne = {a.arg: d for a, d in zip(f.args.kwonlyargs, f.args.kw_defaults) if a.arg in _PROGI}
        assert len(domyslne) == ile, (nazwa, sorted(domyslne))
        zle = {p: ast.unparse(d) for p, d in domyslne.items() if _odczyt_stalej(d, przez_modul=False) != p}
        assert not zle, f"targets.{nazwa}: wartość domyślna progu spoza `DEFAULT_THRESHOLDS`: {zle}"

    progi_gui = next(w.value for w in ast.walk(_drzewo("gui/planner.py"))
                     if isinstance(w, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_THRESHOLDS"
                                                          for t in w.targets))
    pary = {k.value: v.elts[1] for k, v in zip(progi_gui.keys, progi_gui.values)}
    assert set(pary) == set(_PROGI), sorted(pary)
    zle = {p: ast.unparse(d) for p, d in pary.items() if _odczyt_stalej(d, przez_modul=True) != p}
    assert not zle, f"planner._THRESHOLDS: wartość domyślna spoza `targets.DEFAULT_THRESHOLDS`: {zle}"

    flagi = {}
    for w in ast.walk(_drzewo("cli.py")):
        if (isinstance(w, ast.Call) and isinstance(w.func, ast.Attribute) and w.func.attr == "add_argument"
                and w.args and isinstance(w.args[0], ast.Constant) and w.args[0].value in _FLAGI):
            domyslna = next((k.value for k in w.keywords if k.arg == "default"), None)
            flagi[w.args[0].value] = domyslna
    assert set(flagi) == _FLAGI, sorted(flagi)
    zle = {f: ast.unparse(d) if d is not None else "brak" for f, d in flagi.items()
           if not (isinstance(d, ast.Constant) and d.value is None)}
    assert not zle, f"CLI: flaga progu z własną wartością domyślną: {zle}"


def _baza_ze_stanowiskiem(tmp_path):
    sciezka = str(tmp_path / "plan.db")
    con = db.open_db(sciezka)
    con.execute("INSERT INTO observatory(name, lat, lon, status, created_at) "
                "VALUES ('Stanowisko', 53.389, 14.4424, 'proposed', '2026-07-31T12:00:00+00:00')")
    con.commit()
    con.close()
    return sciezka


def test_cli_plan_bez_flag_progow_nie_nazywa_progow(tmp_path, monkeypatch, capsys):
    """`horreum plan` bez flag progów nie podaje rdzeniowi żadnego z pięciu - liczą domyślne rdzenia; flaga podaje swój
    próg. Prawdziwy rdzeń za podsłuchem. Falsyfikator: `default=6.0` w parserze (CLI znów ma własną kopię)."""
    sciezka = _baza_ze_stanowiskiem(tmp_path)
    wolania = []
    prawdziwy = targets.plan

    def _plan(con, **kw):
        wolania.append(kw)
        return prawdziwy(con, **kw)
    monkeypatch.setattr(targets, "plan", _plan)
    assert cli.main(["plan", sciezka, "--night", "2026-08-15", "--json"]) == 0
    assert cli.main(["plan", sciezka, "--night", "2026-08-15", "--json", "--min-size", "8"]) == 0
    capsys.readouterr()
    assert not set(_PROGI) & set(wolania[0]), wolania[0]
    assert {k: wolania[1][k] for k in _PROGI if k in wolania[1]} == {"min_size": 8.0}
