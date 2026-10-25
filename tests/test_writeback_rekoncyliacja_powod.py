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


def _drzewo_writeback():
    """Funkcje i stałe-powody (`NAZWA = PowodPozycji(...)`) najwyższego poziomu modułu `writeback`."""
    drzewo = ast.parse(inspect.getsource(writeback))
    funkcje = {n.name: n for n in drzewo.body if isinstance(n, ast.FunctionDef)}
    stale = {n.targets[0].id: n.value.args[1].value for n in drzewo.body
             if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "PowodPozycji"}
    return funkcje, stale


def _kody_wyrazenia(w, funkcje, stale):
    """Kody powodu wyrażenia: `PowodPozycji(..., "kod")`, stała-powód modułu albo wołanie funkcji modułu
    (kody jej `return`); inne wyrażenie (powód liczony z wyjątku) → None."""
    if isinstance(w, ast.Call) and getattr(w.func, "id", None) == "PowodPozycji":
        return {w.args[1].value}
    if isinstance(w, ast.Name) and w.id in stale:
        return {stale[w.id]}
    if isinstance(w, ast.Call) and getattr(w.func, "id", None) in funkcje:
        kody = [_kody_wyrazenia(r.value, funkcje, stale) for r in ast.walk(funkcje[w.func.id])
                if isinstance(r, ast.Return) and r.value is not None]
        return None if not kody or None in kody else set().union(*kody)
    return None


def _kody_blocked_rekoncyliacji():
    """Kody każdego `FileResult(..., "blocked", <powód>)` funkcji rekoncyliacji; powód bez kodu w źródle
    (liczony z wyjątku) to błąd - zbiór musiałby zgadywać."""
    funkcje, stale = _drzewo_writeback()
    kody, nierozpoznane = set(), []
    for nazwa in _FUNKCJE_REKONCYLIACJI:
        for w in ast.walk(funkcje[nazwa]):
            if not (isinstance(w, ast.Call) and getattr(w.func, "id", None) == "FileResult"
                    and len(w.args) >= 4 and isinstance(w.args[2], ast.Constant)
                    and w.args[2].value == "blocked"):
                continue
            k = _kody_wyrazenia(w.args[3], funkcje, stale)
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
            if not (isinstance(w, ast.Call) and getattr(w.func, "id", None) == "PowodPozycji") or id(w) in pomin:
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
