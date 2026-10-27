"""AR-388: cofnięcie commitu kart, którego backup rekoncyliacja z dyskiem rozstrzygnęła BEZ dowodu podmiany
(`header_backups.unreplaced_at`), mówi stan teraz - „plik nie niesie wersji z tego commitu” - a nie „już cofnięte”
ani historię podmiany. `unreplaced_at` stawia rekoncyliacja przy wersji sprzed zapisu (P = A) ORAZ przy trzeciej
wersji (zamiar `kept`, backup bez zamiaru z `replaced=None`) - zdanie ma być prawdą w każdym stanie, który daje kod
`undo_not_replaced`. Fakt rdzenia `UndoResult.not_replaced` (podzbiór `already`) czyta każda powierzchnia: okna kart,
szuflada i pasek (`wb_worker.zdanie_undo_kart`) oraz CLI `header-fix --undo`.

Stany sąsiednie: kopia wyparta K = A obok trzeciej wersji pod ścieżką - blokada `commit_cut_unproven` (lokacja do
oka), NIE plik bez wersji; cofnięcie własne domknięte - „już cofnięte”, NIE plik bez wersji.

Pliki prawdziwe (astropy) w `tmp_path`; śmierć procesu = wyjątek spoza `Exception` (fikstury `test_writeback_zamiar`)."""
from __future__ import annotations

import os

import pytest
from astropy.io import fits

from horreum import cli, writeback
from test_writeback import NOW
from test_writeback_cofniecie_przebiegu import _jeden_zapis
from test_writeback_podmiana import _Smierc, _backupy, _baza, _smierc_przed_podmiana, _zmien_cudzo
from test_writeback_zamiar import _smierc_w_commicie, _zamiary

ZDANIE_RDZENIA = "rekoncyliacja z dyskiem: plik nie niesie wersji z tego commitu - nie ma czego cofać"


def _bez_wersji(wynik):
    """Pliki wyniku z kodem pliku bez wersji z tego commitu."""
    return [fr for fr in wynik.already if getattr(fr.reason, "code", None) == writeback.CODE_BEZ_WERSJI_ZAPISU]


def _trzecia_wersja(p):
    """Zmiana NAGŁÓWKA poza programem - pod ścieżką ani wersja sprzed zapisu, ani wersja zapisu."""
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["TELESCOP"] = "OBCY"
    return p.read_bytes()


def test_podmiana_niepotwierdzona_plik_sprzed_zapisu(tmp_path, monkeypatch):
    """P = A (wyjątek przy samej podmianie): zamiar `not_replaced`, cofnięcie domknięte, plik w `not_replaced` ze
    zdaniem stanu teraz, bajty sprzed zapisu. Falsyfikator: konstrukcja wyniku bez `not_replaced`."""
    con, p, przed = _jeden_zapis(tmp_path, "niepotwierdzony", monkeypatch)
    wynik = writeback.undo_run(con, (1,), now=NOW)
    assert wynik.complete and wynik.not_replaced == wynik.already == _bez_wersji(wynik) != [], wynik
    assert str(wynik.not_replaced[0].reason) == ZDANIE_RDZENIA
    assert _zamiary(con)[0]["outcome"] == "not_replaced" and p.read_bytes() == przed
    con.close()


def test_kopia_i_tymczasowy_usuniete_trzecia_wersja_pod_sciezka(tmp_path, monkeypatch):
    """Podmiana zaszła (P = N, K = A), proces zginął, potem z zewnątrz zniknęła kopia wyparta, a pod ścieżką stanęła
    trzecia wersja (C): zamiar `kept` bez plików obok - kod `undo_not_replaced`. Dawne zdanie „commit nie podmienił
    (na dysku nagłówek sprzed commitu)” było tu fałszem; zdanie stanu teraz jest prawdą. Plik C nietknięty."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_w_commicie(con, monkeypatch)
    (z,) = _zamiary(con)
    os.remove(z["displaced_path"])
    assert not os.path.exists(z["prepared_path"])
    c = _trzecia_wersja(p)
    wynik = writeback.undo(con, 1, now=NOW)
    assert wynik.complete and wynik.not_replaced == wynik.already != [], wynik
    assert str(wynik.not_replaced[0].reason) == ZDANIE_RDZENIA
    assert _zamiary(con)[0]["outcome"] == "kept" and p.read_bytes() == c
    con.close()


def test_kopia_sprzed_zapisu_obok_trzeciej_wersji_to_blokada(tmp_path, monkeypatch):
    """Stan sąsiedni: K = A zostaje obok, pod ścieżką C - rekoncyliacja blokuje lokację do oka (`commit_cut_unproven`),
    cofnięcie NIE mówi „bez wersji” ani „już cofnięte” i zostaje niedomknięte; K i C nietknięte."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_w_commicie(con, monkeypatch)
    (z,) = _zamiary(con)
    a_bajty = open(z["displaced_path"], "rb").read()
    c = _zmien_cudzo(str(p), "w_miejscu", b"\x66")
    wynik = writeback.undo(con, 1, now=NOW)
    (fr,) = wynik.blocked
    assert fr.reason.code == "commit_cut_unproven", fr
    assert not wynik.already and not wynik.not_replaced and not wynik.complete, wynik
    assert open(z["displaced_path"], "rb").read() == a_bajty and p.read_bytes() == c
    con.close()


def test_backup_bez_zamiaru_z_trzecia_wersja(tmp_path, monkeypatch):
    """Backup bez zamiaru podmiany (zapis sprzed 0038 - wiersz zamiaru zdjęty) i trzecia wersja nagłówka:
    rekoncyliacja dawną regułą - `replaced=None`, `unreplaced_at` - kod `undo_not_replaced` ze zdaniem stanu teraz,
    plik nietknięty."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_przed_podmiana(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    with con:
        con.execute("DELETE FROM replace_intent")
    c = _trzecia_wersja(p)
    wynik = writeback.undo(con, 1, now=NOW)
    assert wynik.complete and wynik.not_replaced == wynik.already != [], wynik
    assert str(wynik.not_replaced[0].reason) == ZDANIE_RDZENIA
    (b,) = _backupy(con)
    assert b["pending_since"] is None and b["unreplaced_at"] is not None and p.read_bytes() == c
    con.close()


def test_cofniecie_juz_domkniete_to_nie_plik_bez_wersji(tmp_path):
    """Stan sąsiedni: drugie cofnięcie domkniętego cofnięcia atomowego - „już cofnięte” wynikiem własnym
    (`undo_already_own`), `not_replaced` puste. Falsyfikator: `not_replaced` = całe `already`."""
    con, p, lid = _baza(tmp_path, "fits")
    res = writeback.commit(con, "R", now=NOW)
    assert writeback.undo(con, res.commit_id, now=NOW).complete
    wynik = writeback.undo(con, res.commit_id, now=NOW)
    assert wynik.complete and [fr.reason.code for fr in wynik.already] == ["undo_already_own"], wynik
    assert wynik.not_replaced == []
    con.close()


@pytest.mark.parametrize("stan", ["sprzed_zapisu", "trzecia_wersja"])
def test_cli_undo_mowi_bez_wersji_z_commitu(tmp_path, capsys, monkeypatch, stan):
    """`header-fix --undo` na tym samym fakcie: wiersz „bez wersji z commitu 1”, bez „juz cofniete”, kod 0 (cofnięcie
    domknięte), ASCII pod cp1250 - dla pliku sprzed zapisu i dla trzeciej wersji. Falsyfikator: wiersz „juz cofniete”
    z całego `already`."""
    if stan == "sprzed_zapisu":
        con, p, _przed = _jeden_zapis(tmp_path, "niepotwierdzony", monkeypatch)
        dbp = str(tmp_path / "p.db")
    else:
        con, p, _lid = _baza(tmp_path, "fits")
        _smierc_w_commicie(con, monkeypatch)
        os.remove(_zamiary(con)[0]["displaced_path"])
        _trzecia_wersja(p)
        dbp = str(tmp_path / "h.db")
    con.close()
    kod = cli.main(["header-fix", dbp, "--undo", "1"])
    out = capsys.readouterr().out
    assert kod == 0, out
    assert ("\n  bez wersji z commitu 1 - plik nie niesie wersji z tego commitu (rekoncyliacja z dyskiem), "
            "nie ma czego cofac") in out, out
    assert "juz cofniete" not in out and "zablokowane 0" in out, out
    out.encode("cp1250")
