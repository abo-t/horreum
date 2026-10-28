"""AR-362: powierzchnie okna na jednej regule klasy cofnięcia - recepta osi „Cofnij zapis (commit N)”
(`ObjectAxisView._zywy` przez `writeback.zakresy_cofniecia`, ta sama reguła co szuflada i okna kart) oraz jedno zdanie
szuflady przy faktach wykonawcy NIEZNANYCH (bez „Cofnij”, człon `wb.write_facts_unknown` z numerem commitu - także
przy zapisie przerwanym, jak okna kart). Rdzeń prawdziwy na FITS w `tmp_path`; atrapy wyłącznie awarii odczytu."""
import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import writeback
from horreum.gui import app, i18n, queries
from horreum.gui.wb_worker import CzescZapisu, zdanie_commitu_kart

from test_gui_grid_szuflada import (_baza_szuflady, _klik_w, _makro_przyciskiem, _przerwany_zapis, _widok_szuflady,
                                    _zamknij_widok)
from test_writeback_cofniecie_przebiegu import NOW, _jeden_zapis, _nakladka


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _zywy(con, commit_id, tozsamosc=None):
    """`ObjectAxisView._zywy` wpisu kart commitu `commit_id` (tożsamość zamiaru = przebieg commitu w tej bazie)."""
    wpis = SimpleNamespace(klucz=("karty", commit_id),
                           tozsamosc=tozsamosc or queries.przebieg_commitu(con, commit_id))
    return app.ObjectAxisView._zywy(SimpleNamespace(con=con), wpis)


def test_zywy_recepta_kart_z_reguly_klasy(tmp_path, monkeypatch):
    """Recepta „Cofnij zapis (commit N)” żyje, gdy zakres „Cofnij” commitu ma co zrobić - reguła szuflady i okien kart:
    podmiana potwierdzona - żyje; nakładka cofnięta (nowszy commit „już cofnięty” łańcuchem przebiegu) - martwa
    (dawniej żyła: dowód wprost bez łańcucha); sam zapis otwarty w miejscu (rozstrzyga odzysk, cofnięcie odmawia
    `undo_open_op`) - martwa; obca biblioteka pod tą samą ścieżką (inny przebieg commitu) - martwa. Falsyfikatory:
    predykat zakończenia per backup zamiast zakresu (`otwarty` żyje); reguła bez łańcucha (nakładka żyje)."""
    for kat in ("a", "n", "o"):
        (tmp_path / kat).mkdir()
    con = _jeden_zapis(tmp_path / "a", "atomowy", monkeypatch)[0]
    try:
        assert _zywy(con, 1)
        assert not _zywy(con, 1, tozsamosc="inny-przebieg")
    finally:
        con.close()
    con, _p = _nakladka(tmp_path / "n", "aa")
    try:
        assert writeback.undo(con, 2, now=NOW).complete and writeback.undo(con, 1, now=NOW).complete
        assert not _zywy(con, 2) and not _zywy(con, 1)
    finally:
        con.close()
    con = _jeden_zapis(tmp_path / "o", "przed_bajtem", monkeypatch)[0]
    try:
        assert writeback.przebieg_do_cofniecia(con, "R").otwarte == 1
        assert not _zywy(con, 1)
    finally:
        con.close()


def _pad_odczytu_zakresu(*_a, **_k):
    raise sqlite3.OperationalError("database is locked")


def test_fakty_nieznane_przy_zapisie_przerwanym_to_samo_zdanie_co_okna(qapp, tmp_path, monkeypatch):
    """Zapis przerwany „Anuluj” po pierwszym pliku, a odczyt zakresu w wykonawcy pada (fakty nieznane): szuflada mówi
    „przerwano, 2 do dokończenia” i - jak okna kart (`wb_worker.zdanie_commitu_kart`) - człon `wb.write_facts_unknown`
    z numerem commitu rdzenia; „Cofnij” nie stoi. Falsyfikator: człon wyłącznie w gałęzi „nic do cofnięcia”
    (zapis zamknięty), zdanie przerwanego zapisu milczy o faktach."""
    _path, con, pliki = _baza_szuflady(tmp_path, 3)
    v = _widok_szuflady(con)
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        monkeypatch.setattr(writeback, "_klasy_przebiegu", _pad_odczytu_zakresu)
        _przerwany_zapis(v, monkeypatch)
        assert v._pending_count() == 2 and v._undo_mode is None
        ogon = i18n.t("wb.write_facts_unknown") + i18n.t("grid.wb.commit_id", id=1)
        tekst = v.drawer.result.text()
        assert tekst.endswith(i18n.t("grid.wb.interrupted", n=2) + ogon), tekst
        # Okno kart przy tym samym wyniku i tych samych faktach (zapis przerwany po pierwszym pliku, commit 1).
        wynik = writeback.CommitResult("R", 1, [writeback.FileResult(1, str(pliki[0]), "applied", None)], [], [], [],
                                       cancelled=True)
        okno, cofnij = zdanie_commitu_kart(wynik, "grid.wb.applied", CzescZapisu(applied=(str(pliki[0]),)))
        assert okno.endswith(ogon) and cofnij is None, okno
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()


def test_podmiana_niepotwierdzona_rusza_plakietke_porzadkow(qapp, tmp_path, monkeypatch):
    """Zapis drogą atomową, której podmiany system nie potwierdził (`replace_unconfirmed` - plik `failed`,
    `CommitResult.commit_id` None, backup `pending_since`): fakty wykonawcy liczą plik TEJ operacji „do sprawdzenia”
    - operacja coś podmieniła, więc szuflada stawia „Cofnij” bez członu „zapisany wcześniej” i rusza plakietkę
    Porządków (karta mogła trafić do pliku). Falsyfikator: „ta operacja nic nie podmieniła” z samego `commit_id`
    (plakietka stoi)."""
    from horreum.gui.wb_worker import WritebackWorker

    def _atomowo(c, t, now, pr, sc):
        return writeback.commit(c, t, now=now, progress=pr, should_cancel=sc, inplace=False)

    def _bez_potwierdzenia(path, tmp, kopia):
        raise OSError(None, "awaria podmiany", None, 87)
    _path, con, _pliki = _baza_szuflady(tmp_path, 1)
    v = _widok_szuflady(con, inline=True)
    emisje = []
    v.stan_porzadkow_changed.connect(lambda: emisje.append(1))
    try:
        _makro_przyciskiem(v, "TELESCOP", "EQ6")
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _atomowo)
        monkeypatch.setattr(writeback, "_replace_file_w", _bez_potwierdzenia)
        _klik_w(v.drawer.btn_commit)
        assert con.execute("SELECT count(*) FROM header_backups WHERE pending_since IS NOT NULL").fetchone()[0] == 1
        assert v._undo_mode is not None, v.drawer.result.text()
        assert i18n.t_plural("grid.wb.written_before", 1) not in v.drawer.result.text(), v.drawer.result.text()
        assert emisje, "plakietka Porządków nie ruszyła"
    finally:
        monkeypatch.undo()
        _zamknij_widok(v)
        con.close()
