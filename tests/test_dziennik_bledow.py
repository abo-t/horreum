"""Dziennik błędów programu (`horreum.gui.dziennik_bledow`, AR-312) - Qt-wolny: treść wpisu, obrót po
progu, zapis wyłącznie pod katalogiem dziennika, porażki obrotu i dopisku, krótki wiersz powtórzenia.
Katalogi w `tmp_path` (prawdziwy `%LOCALAPPDATA%` nietknięty - `conftest._straznik_dziennika_usera`)."""
import os
import stat
import sys

import pytest

from horreum.gui import dziennik_bledow
from horreum.gui.dziennik_bledow import Dziennik

CZAS = "2026-10-22T12:00:00+02:00"


def _wpis(d, naglowek="ValueError: zła wartość @ horreum/scan.py:12", slad="Traceback (ostatni)\n  ramka\n"):
    return d.zapisz(czas=CZAS, wersja="0.19.0", watek="MainThread", naglowek=naglowek, slad=slad)


def _tresc(sciezka):
    with open(sciezka, encoding="utf-8") as fh:
        return fh.read()


def test_wpis_ma_czas_wersje_watek_miejsce_i_slad(tmp_path):
    """Wpis: wiersz z czasem, wersją, pid i wątkiem, wiersz `Typ: opis @ plik:N`, pełny ślad i pusty
    wiersz; drugi wpis dopisuje się pod pierwszym (UTF-8 - polskie litery z opisu zostają).
    Falsyfikator: tryb `w` - drugi wpis kasuje pierwszy."""
    katalog = tmp_path / "dane" / "Horreum"
    d = Dziennik(str(katalog))
    sciezka = _wpis(d)
    assert sciezka == str(katalog / "bledy.log") == dziennik_bledow.sciezka(str(katalog))
    _wpis(d, naglowek="KeyError: 'ź' @ horreum/repo.py:7", slad="Traceback 2\n")
    assert _tresc(sciezka) == (
        f"==== {CZAS} | Horreum 0.19.0 | pid {os.getpid()} | MainThread\n"
        "ValueError: zła wartość @ horreum/scan.py:12\nTraceback (ostatni)\n  ramka\n\n"
        f"==== {CZAS} | Horreum 0.19.0 | pid {os.getpid()} | MainThread\n"
        "KeyError: 'ź' @ horreum/repo.py:7\nTraceback 2\n\n")


def test_obrot_po_progu_trzyma_dwa_pliki_zapasowe(tmp_path, monkeypatch):
    """Wpis, który przekroczyłby próg, obraca pliki: `bledy.log` → `.1` → `.2`, najstarszy wypada;
    kolejność treści zachowana. Wpisy mieszczące się pod progiem idą do jednego pliku.
    Falsyfikator: bez obrotu (plik rośnie); obrót przy każdym wpisie."""
    pod_progiem = Dziennik(str(tmp_path / "Pod"))
    for i in range(3):
        _wpis(pod_progiem, naglowek=f"ValueError: pod progiem {i}")
    assert sorted(p.name for p in (tmp_path / "Pod").iterdir()) == ["bledy.log"]
    monkeypatch.setattr(dziennik_bledow, "PROG_BAJTOW", 300)
    d = Dziennik(str(tmp_path / "Horreum"))
    for i in range(4):
        _wpis(d, naglowek=f"ValueError: wpis {i}", slad="x" * 150)
    sciezka = tmp_path / "Horreum" / "bledy.log"
    pliki = sorted(p.name for p in (tmp_path / "Horreum").iterdir())
    assert pliki == ["bledy.log", "bledy.log.1", "bledy.log.2"], pliki
    assert "wpis 3" in _tresc(sciezka) and "wpis 2" not in _tresc(sciezka)
    assert "wpis 2" in _tresc(f"{sciezka}.1") and "wpis 1" in _tresc(f"{sciezka}.2")
    assert "wpis 0" not in "".join(_tresc(tmp_path / "Horreum" / p) for p in pliki)
    assert all(os.path.getsize(tmp_path / "Horreum" / p) <= 300 for p in pliki)


def _migawka(korzen):
    return {os.path.relpath(os.path.join(d, n), korzen): open(os.path.join(d, n), "rb").read()
            for d, _k, pliki in os.walk(korzen) for n in pliki}


def test_pisze_wylacznie_pod_katalogiem_dziennika(tmp_path, monkeypatch):
    """W biegu (z obrotem) zmienia się WYŁĄCZNIE katalog dziennika i tylko trzy nazwy z niego: plik
    rodzeństwa katalogu i plik w katalogu nadrzędnym zostają bajt w bajt. Bramka statyczna drzwi -
    `test_writeback_safety.py::test_drzwi_dziennika_mutuja_tylko_w_dozwolonych_funkcjach`.
    Falsyfikator: obrót do katalogu nadrzędnego."""
    monkeypatch.setattr(dziennik_bledow, "PROG_BAJTOW", 200)
    (tmp_path / "Inny").mkdir()
    (tmp_path / "Inny" / "bledy.log").write_bytes(b"cudzy")
    (tmp_path / "bledy.log.1").write_bytes(b"obok")
    przed = _migawka(tmp_path)
    d = Dziennik(str(tmp_path / "Horreum"))
    for i in range(5):
        _wpis(d, naglowek=f"ValueError: {i}", slad="y" * 120)
    po = _migawka(tmp_path)
    assert {k: v for k, v in po.items() if not k.startswith("Horreum" + os.sep)} == przed
    assert {k for k in po if k.startswith("Horreum" + os.sep)} == {
        os.path.join("Horreum", n) for n in ("bledy.log", "bledy.log.1", "bledy.log.2")}


@pytest.mark.skipif(sys.platform != "win32", reason="blokada pliku otwartego przez inny uchwyt - Windows")
def test_obrot_pliku_otwartego_nie_zatrzymuje_dopisku(tmp_path, monkeypatch):
    """Druga instancja programu trzyma plik (`WinError 32` przy obrocie): wpis i tak idzie, z wierszem
    o nieudanym obrocie. Falsyfikator: porażka obrotu wychodzi wyjątkiem."""
    monkeypatch.setattr(dziennik_bledow, "PROG_BAJTOW", 200)
    d = Dziennik(str(tmp_path / "Horreum"))
    sciezka = _wpis(d, naglowek="ValueError: pierwszy", slad="z" * 150)
    with open(sciezka, "rb"):
        _wpis(d, naglowek="ValueError: drugi", slad="z" * 150)
    tresc = _tresc(sciezka)
    assert "(obrót dziennika nie powiódł się: PermissionError: " in tresc, tresc
    assert "ValueError: pierwszy" in tresc and "ValueError: drugi" in tresc
    assert not os.path.exists(f"{sciezka}.1")


def test_powtorzenie_idzie_krotkim_wierszem(tmp_path):
    """Zgłoszenie identyczne z poprzednim pełnym wpisem (nagłówek i ślad) - krótki wiersz z licznikiem;
    inne pomiędzy przerywa serię (następne identyczne znów pełnym wpisem).
    Falsyfikator: powtórzenie pełnym wpisem."""
    d = Dziennik(str(tmp_path / "Horreum"))
    for _ in range(3):
        _wpis(d)
    _wpis(d, naglowek="ValueError: inny")
    sciezka = _wpis(d)
    glowa = f"==== {CZAS} | Horreum 0.19.0 | pid {os.getpid()} | MainThread"
    wiersze = _tresc(sciezka).splitlines()
    assert wiersze[5:7] == [f"{glowa} | powtórzenie 1: ValueError: zła wartość @ horreum/scan.py:12",
                            f"{glowa} | powtórzenie 2: ValueError: zła wartość @ horreum/scan.py:12"]
    assert _tresc(sciezka).count("Traceback (ostatni)") == 3        # pierwszy, „inny” i po nim znów pełny
    assert _tresc(sciezka).count("| powtórzenie ") == 2


def test_nieudany_dopisek_nie_przesuwa_numeru_powtorzenia(tmp_path):
    """Powtórzenie, którego dopisek padł, nie zostawia śladu w liczniku: następne udane identyczne
    zgłoszenie to „powtórzenie 1” (w pliku nie ma dziury „1” przed „2”), a po nieudanym PEŁNYM wpisie
    nowego błędu następne jego zgłoszenie idzie pełnym wpisem. Falsyfikator: licznik podbity przed
    dopiskiem → „powtórzenie 2”."""
    d = Dziennik(str(tmp_path / "Horreum"))
    sciezka = _wpis(d)
    os.chmod(sciezka, stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            _wpis(d)
        with pytest.raises(PermissionError):
            _wpis(d, naglowek="ValueError: nowy")
    finally:
        os.chmod(sciezka, stat.S_IREAD | stat.S_IWRITE)
    _wpis(d)
    _wpis(d, naglowek="ValueError: nowy")
    wiersze = _tresc(sciezka).splitlines()
    assert wiersze[5].endswith(" | powtórzenie 1: ValueError: zła wartość @ horreum/scan.py:12"), wiersze
    assert wiersze[6].endswith(" | MainThread") and wiersze[7] == "ValueError: nowy", wiersze


def test_katalog_wzgledny_to_blad_programu():
    """Katalog względny trafiłby do katalogu bieżącego (w wydaniu - czegokolwiek): EXPECT, nie stan."""
    with pytest.raises(ValueError):
        Dziennik("Horreum")


def test_porazka_dopisku_rzuca(tmp_path):
    """Plik dziennika tylko do odczytu (`PermissionError`) - wyjątek do wołającego (straż mówi o nim
    w oknie); plik w miejscu katalogu (`FileExistsError` z założenia katalogu) - też.
    Falsyfikator: połknięty wyjątek - straż powiedziałaby „zapisano”."""
    d = Dziennik(str(tmp_path / "Horreum"))
    sciezka = _wpis(d)
    os.chmod(sciezka, stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            _wpis(d, naglowek="ValueError: drugi")
    finally:
        os.chmod(sciezka, stat.S_IREAD | stat.S_IWRITE)
    (tmp_path / "Plik").write_bytes(b"")
    with pytest.raises(OSError):
        _wpis(Dziennik(str(tmp_path / "Plik")))
