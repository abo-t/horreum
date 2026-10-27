"""Powód odmowy rekoncyliacji zamiaru renamu ZOSTAJE w bazie (AR-323): `writeback.reconcile_renames` przy
wyniku 'blocked' zapisuje powód z kodem na wierszu zamiaru (`repo.note_rename_intent_refusal`) - szuflada czyta
go z bazy, nie ze zwrotu.

Co pilnujemy:
  * odmowa (inny `mtime`, wyjątek rozstrzygnięcia) - trójka powodu na wierszu, zamiar i status bez zmian;
  * ta sama odmowa drugi raz - zero zapisu;
  * rozstrzygnięcie zamiaru czyści powód (`settle_rename_intent`);
  * CAS kierunku: zamiar zamknięty i otwarty na nowo w przeciwnym kierunku między obserwacją a zapisem nie
    dostaje starej odmowy;
  * porażka zapisu powodu nie zmienia wyniku zamiaru, a dopisek ją mówi;
  * `item_reasons.KODY_ODMOWY_REKONCYLIACJI` (SPOT, AST po `writeback`) to dokładnie kody 'blocked'
    rekoncyliacji, rozłączne z każdym innym kodem powodu `writeback`/`repo` i znane katalogowi kodów.
Pliki prawdziwe (astropy) w `tmp_path`."""
from __future__ import annotations

import ast
import inspect
import os
import sqlite3

import pytest

from horreum import repo, writeback
from horreum.item_reasons import ITEM_REASON_CODES, KODY_ODMOWY_REKONCYLIACJI, PowodPozycji
from test_rename import NOW, _rozdarty


def _trojka(con):
    return tuple(con.execute("SELECT reason_code, in_flight, status FROM pending_renames").fetchone())


def test_odmowa_rekoncyliacji_zostaje_na_wierszu_zamiaru(tmp_path, monkeypatch):
    """Plik pod nową nazwą z innym `mtime`: wynik 'blocked', a wiersz zamiaru niesie kod
    `intent_mtime_differs` przy otwartym zamiarze `commit` i niezmienionym statusie; drugi bieg - zero zapisu;
    po przywróceniu `mtime` rekoncyliacja rozstrzyga zamiar i czyści powód."""
    con, _lid, _stara, nowa = _rozdarty(tmp_path, monkeypatch)
    status = _trojka(con)[2]
    st = os.stat(nowa)
    os.utime(nowa, (st.st_atime, st.st_mtime + 3600))
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and w.reason.code == "intent_mtime_differs", w
    assert _trojka(con) == ("intent_mtime_differs", "commit", status)
    zapisy = con.total_changes
    (w2,) = writeback.reconcile_renames(con, now=NOW)
    assert w2.status == "blocked" and con.total_changes == zapisy
    os.utime(nowa, (st.st_atime, st.st_mtime))
    (w3,) = writeback.reconcile_renames(con, now=NOW)
    assert w3.status == "reconciled", w3
    assert _trojka(con) == (None, None, "applied")
    con.close()


def test_wyjatek_rozstrzygniecia_zostaje_na_wierszu(tmp_path, monkeypatch):
    """Rozstrzygnięcie zamiaru rzuca - wynik 'blocked' z kodem `reconcile_failed`, ten sam kod na wierszu."""
    con, _lid, _stara, _nowa = _rozdarty(tmp_path, monkeypatch)

    def _pada(*a, **kw):
        raise OSError(5, "zerwany udział")
    monkeypatch.setattr(writeback, "_rozstrzygnij_zamiar", _pada)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and w.reason.code == "reconcile_failed", w
    assert _trojka(con)[:2] == ("reconcile_failed", "commit")
    con.close()


def test_zamiar_otwarty_na_nowo_w_drugim_kierunku_nie_dostaje_starej_odmowy(tmp_path, monkeypatch):
    """Między obserwacją rekoncyliacji (zamiar `commit`) a zapisem powodu inny proces rozstrzyga zamiar,
    a wiersz dostaje nowy zamiar `undo`: odmowa sprzed zmiany nie trafia na nowy zamiar - wiersz zostaje
    z powodem próby renamu (rozdarcie), jaki miał."""
    con, _lid, _stara, _nowa = _rozdarty(tmp_path, monkeypatch)
    rid = con.execute("SELECT id FROM pending_renames").fetchone()[0]
    przed = _trojka(con)[0]

    def _w_miedzyczasie(c, r, *, now):
        repo.drop_rename_intent(c, rename_id=r["id"])
        repo.open_rename_intent(c, rename_id=r["id"], direction="undo")
        return writeback.FileResult(r["location_id"], r["old_path"], "blocked",
                                    PowodPozycji("dysk nie odpowiada (x) - zamiar zostaje",
                                                 "disk_silent", detail="x"))
    monkeypatch.setattr(writeback, "_rozstrzygnij_zamiar", _w_miedzyczasie)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked", w
    assert przed != "disk_silent" and _trojka(con)[:2] == (przed, "undo")
    assert repo.note_rename_intent_refusal(con, rename_id=rid, reason=w.reason,
                                           expect_in_flight="commit") is False
    assert _trojka(con)[0] == przed
    con.close()


def test_porazka_zapisu_powodu_nie_zmienia_wyniku_zamiaru(tmp_path, monkeypatch):
    """Zapis powodu pada (baza zajęta) - wynik zamiaru dalej 'blocked' z powodem rozstrzygnięcia, a dopisek
    mówi błąd zapisu; wiersz z powodem sprzed rekoncyliacji."""
    con, _lid, _stara, nowa = _rozdarty(tmp_path, monkeypatch)
    przed = _trojka(con)[0]
    st = os.stat(nowa)
    os.utime(nowa, (st.st_atime, st.st_mtime + 3600))

    def _pada(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(repo, "note_rename_intent_refusal", _pada)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and "mtime" in w.reason and "database is locked" in w.reason, w
    assert _trojka(con)[:2] == (przed, "commit")
    con.close()


_FUNKCJE_REKONCYLIACJI = ("reconcile_renames", "_rozstrzygnij_zamiar")
# Źródła kodów odmowy rekoncyliacji - poza nimi żaden literał kodu `PowodPozycji` w `writeback`/`repo` nie może
# nieść kodu ze zbioru (szuflada wzięłaby powód próby renamu za odmowę rekoncyliacji).
_ZRODLA_ODMOWY = (*_FUNKCJE_REKONCYLIACJI, "_dysk_milczy")


def _nazwa_wolania(w):
    """Nazwa wołanej klasy/funkcji: `Nazwa(...)` i `x.Nazwa(...)` (atrybut DOWOLNEGO obiektu - nazwy `FileResult`
    i `PowodPozycji` są w repo jednoznaczne, a obca klasa o tej nazwie dałaby czerwień SPOT, nie ciszę); wyrażenie,
    które nie jest wołaniem → None."""
    if isinstance(w, ast.Call):
        if isinstance(w.func, ast.Name):
            return w.func.id
        if isinstance(w.func, ast.Attribute):
            return w.func.attr
    return None


def _argument(w, pozycja, slowo):
    """Argument wołania podany pozycyjnie albo słowem kluczowym (`FileResult` to dataclass); brak → None."""
    if len(w.args) > pozycja:
        return w.args[pozycja]
    return next((k.value for k in w.keywords if k.arg == slowo), None)


def _kod_powodu(w):
    """Kod wołania `PowodPozycji(tekst, "kod", ...)` - kod wyłącznie pozycyjnie (`/` w `__new__`). Kod spoza
    literału albo brak kodu = porażka z linią, nie `IndexError`/`AttributeError` bez miejsca."""
    kod = w.args[1] if len(w.args) > 1 else None
    assert isinstance(kod, ast.Constant) and isinstance(kod.value, str), \
        f"kod PowodPozycji nie jest literałem: linia {w.lineno}"
    return kod.value


def _drzewo_writeback(zrodlo=None):
    """Funkcje i stałe-powody (`NAZWA = PowodPozycji(...)`) najwyższego poziomu modułu `writeback` (albo
    źródła podanego wprost - test samych helperów)."""
    drzewo = ast.parse(inspect.getsource(writeback) if zrodlo is None else zrodlo)
    funkcje = {n.name: n for n in drzewo.body if isinstance(n, ast.FunctionDef)}
    stale = {n.targets[0].id: _kod_powodu(n.value) for n in drzewo.body
             if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and _nazwa_wolania(n.value) == "PowodPozycji"}
    return funkcje, stale


def _kody_wyrazenia(w, funkcje, stale):
    """Kody powodu wyrażenia: `PowodPozycji(..., "kod")`, stała-powód modułu albo wołanie funkcji modułu WYŁĄCZNIE
    po gołej nazwie (kody jej `return`); inne wyrażenie (powód liczony z wyjątku, metoda obiektu) → None."""
    if _nazwa_wolania(w) == "PowodPozycji":
        return {_kod_powodu(w)}
    if isinstance(w, ast.Name) and w.id in stale:
        return {stale[w.id]}
    # Funkcja modułu wyłącznie po gołej nazwie: `obj.metoda()` o nazwie funkcji modułu to inne wołanie.
    if isinstance(w, ast.Call) and isinstance(w.func, ast.Name) and w.func.id in funkcje:
        kody = [_kody_wyrazenia(r.value, funkcje, stale) for r in ast.walk(funkcje[w.func.id])
                if isinstance(r, ast.Return) and r.value is not None]
        return None if not kody or None in kody else set().union(*kody)
    return None


def _kody_blocked_rekoncyliacji(zrodlo=None):
    """Kody każdego `FileResult(..., "blocked", <powód>)` i `dataclasses.replace(<wynik>, status=..., ...)` funkcji
    rekoncyliacji (status i powód pozycyjnie albo słowem kluczowym, wołanie także przez moduł); powód bez kodu
    w źródle (liczony z wyjątku), brak powodu i status spoza literału to błąd z linią - zbiór musiałby zgadywać."""
    funkcje, stale = _drzewo_writeback(zrodlo)
    kody, nierozpoznane = set(), []
    for nazwa in _FUNKCJE_REKONCYLIACJI:
        for w in ast.walk(funkcje[nazwa]):
            wolanie = _nazwa_wolania(w)
            if wolanie == "replace":
                # `replace` bez `status` zostawia status wyniku, którego konstrukcję helper liczy osobno; ze `status`
                # to nowa odmowa - status i powód wyłącznie słowami kluczowymi (`replace(obj, /, **zmiany)`).
                if not any(k.arg == "status" for k in w.keywords):
                    continue
            elif wolanie != "FileResult":
                continue
            status = _argument(w, 2, "status")
            if not isinstance(status, ast.Constant):
                nierozpoznane.append(f"{nazwa}:{w.lineno}")
                continue
            if status.value != "blocked":
                continue
            powod = _argument(w, 3, "reason")
            k = None if powod is None else _kody_wyrazenia(powod, funkcje, stale)
            if k is None:
                nierozpoznane.append(f"{nazwa}:{w.lineno}")
            else:
                kody |= k
    assert not nierozpoznane, nierozpoznane
    return kody


def _kody_poza_zrodlami_odmowy():
    """Kody WSZYSTKICH wywołań `PowodPozycji` w całych modułach `writeback` i `repo` poza `_ZRODLA_ODMOWY`:
    pisarz renamu, prymityw `rename_file`, wyjątki repo z powodem (`powod_wyjatku`), stałe-powody modułu.
    Kod, który nie jest literałem, to błąd - rozłączności nie dałoby się wykazać."""
    kody, nieliteraly = set(), []
    for modul in (writeback, repo):
        drzewo = ast.parse(inspect.getsource(modul))
        pomin = {id(w) for n in drzewo.body if isinstance(n, ast.FunctionDef) and n.name in _ZRODLA_ODMOWY
                 for w in ast.walk(n)}
        for w in ast.walk(drzewo):
            if _nazwa_wolania(w) != "PowodPozycji" or id(w) in pomin:
                continue
            kod = w.args[1] if len(w.args) > 1 else None
            if isinstance(kod, ast.Constant) and isinstance(kod.value, str):
                kody.add(kod.value)
            else:
                nieliteraly.append(f"{modul.__name__}:{w.lineno}")
    assert not nieliteraly, nieliteraly
    return kody


def test_kody_odmowy_rekoncyliacji_to_dokladnie_kody_blocked_rekoncyliacji():
    """SPOT: zbiór z `item_reasons` == kody 'blocked' `reconcile_renames`/`_rozstrzygnij_zamiar` (z `_dysk_milczy`
    przez wołanie); brak kodu albo kod obcy (np. `torn_db_not` pisarza) - czerwone."""
    assert KODY_ODMOWY_REKONCYLIACJI == _kody_blocked_rekoncyliacji()


def test_kody_odmowy_rekoncyliacji_rozlaczne_z_reszta_powodow_i_znane():
    """Kod odmowy rekoncyliacji nie pojawia się w żadnym innym powodzie `writeback`/`repo` (szuflada rozróżnia
    odmowę rekoncyliacji od powodu próby renamu po kodzie, bo `status` wiersza z otwartym zamiarem tego nie
    robi), a każdy jest w `ITEM_REASON_CODES`."""
    reszta = _kody_poza_zrodlami_odmowy()
    assert {"torn_db_not", "returned_intent_left", "inplace_after_gate", "target_taken_db",
            "intent_dropped"} <= reszta, reszta
    assert not KODY_ODMOWY_REKONCYLIACJI & reszta, KODY_ODMOWY_REKONCYLIACJI & reszta
    assert KODY_ODMOWY_REKONCYLIACJI <= ITEM_REASON_CODES, KODY_ODMOWY_REKONCYLIACJI - ITEM_REASON_CODES


# Źródło próbne helperów AST: każda dozwolona postać `FileResult(..., "blocked", <powód>)` - powód pozycyjnie
# i słowem kluczowym, status słowem kluczowym, stała-powód modułu, wołanie przez moduł, kody przez funkcję.
_ZRODLO_PROBNE = '''
POWOD_STALY = PowodPozycji("tekst", "kod_staly")


def _dysk_milczy():
    return item_reasons.PowodPozycji("tekst", "kod_dysku")


def reconcile_renames():
    FileResult(1, "p", "blocked", PowodPozycji("tekst", "kod_pozycyjny"))
    FileResult(1, "p", "blocked", reason=PowodPozycji("tekst", "kod_slowem"))
    FileResult(1, "p", status="blocked", reason=POWOD_STALY)
    writeback.FileResult(1, "p", "blocked", _dysk_milczy())
    dataclasses.replace(wynik, status="blocked", reason=PowodPozycji("tekst", "kod_zamiany"))
    dataclasses.replace(wynik, reason="dopisek")
    FileResult(1, "p", "applied", None)


def _rozstrzygnij_zamiar():
    FileResult(1, "p", "reconciled", None)
'''


def test_helpery_ast_widza_slowa_kluczowe_wolanie_przez_modul_i_stale():
    """Helper zbioru kodów 'blocked' nie gubi postaci, którą dopuszcza dataclass `FileResult` (słowa kluczowe,
    trzy argumenty pozycyjne) ani wołania przez moduł - inaczej kod pominięty po cichu wypadłby ze zbioru
    szuflady, a test SPOT zostałby zielony (AR-342)."""
    assert _kody_blocked_rekoncyliacji(_ZRODLO_PROBNE) == {"kod_pozycyjny", "kod_slowem", "kod_staly", "kod_dysku",
                                                         "kod_zamiany"}


def test_helpery_ast_melduja_nierozpoznane_wolanie_z_linia():
    """Status spoza literału, 'blocked' bez powodu, powód liczony z wyjątku, kod `PowodPozycji` spoza literału
    i metoda obiektu o nazwie funkcji modułu = porażka helpera z miejscem (linia 3 źródła), nie pominięcie,
    cudze kody ani `AttributeError` bez linii (AR-342)."""
    for wiersz in ('FileResult(1, "p", status, None)',
                   'FileResult(1, "p", "blocked")',
                   'FileResult(1, "p", "blocked", reason=powod_wyjatku(e))',
                   'FileResult(1, "p", "blocked", PowodPozycji("tekst", kod))',
                   'FileResult(1, "p", "blocked", obj._rozstrzygnij_zamiar())',
                   'dataclasses.replace(wynik, status="blocked")',
                   'dataclasses.replace(wynik, status=status, reason=None)'):
        zrodlo = (f"def reconcile_renames():\n    pass\n    {wiersz}\n\n\n"
                  f"def _rozstrzygnij_zamiar():\n    return PowodPozycji(\"tekst\", \"kod_funkcji\")\n")
        with pytest.raises(AssertionError, match=r"reconcile_renames:3|linia 3"):
            _kody_blocked_rekoncyliacji(zrodlo)
