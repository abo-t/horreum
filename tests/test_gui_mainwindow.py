"""Okno aplikacji `MainWindow` (PLAN_gui_pipeline §2, etap 1) — szkielet powłoki: menu Plik
(Otwórz/Nowa baza), osadzony widok osi teleskopu w `QStackedWidget`, własność połączenia (zamyka
swoje `con` przy zmianie bazy i przy zamknięciu okna). Pasek nawigacji ukryty dopóki jest 1 widok
(Pipeline dochodzi w etapie 2). Sterujemy oknem bez pytest-qt (offscreen, QApplication ręcznie).

`importorskip` na poziomie modułu — bez PySide6 plik się pomija (czyni §7.2 prawdziwym)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db
from horreum.gui.app import MainWindow, TelescopeAxisView

from fixture_s8 import seed

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_otwarte_na_bazie_montuje_os_teleskopu(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "s8.db"))
    seed(con)
    win = MainWindow(con)
    try:
        assert win.stack.count() == 1                      # etap 1: tylko oś teleskopu
        assert isinstance(win.axis_view, TelescopeAxisView)
        assert win.axis_view.table.rowCount() == 4         # read-model odbity w osadzonym widoku
        # 1 widok → pasek nawigacji ukryty (samotny przycisk to szum)
        assert all(not b.isVisible() for b in win._nav_buttons)
    finally:
        win.close()                                        # closeEvent zamyka con (własność okna)


def test_brak_bazy_startuje_pusto_z_podpowiedzia(qapp):
    win = MainWindow(None)
    try:
        assert win.stack.count() == 0                      # bez bazy brak widoków
        assert "brak baz" in win.statusBar().currentMessage().lower()
    finally:
        win.close()


def test_zmiana_bazy_przemontowuje_i_zamyka_stara(qapp, tmp_path):
    con_a = db.open_db(str(tmp_path / "a.db"))
    seed(con_a)
    win = MainWindow(con_a)
    try:
        assert win.axis_view.table.rowCount() == 4
        win._open_path(str(tmp_path / "b.db"))             # nowa, pusta baza
        assert win.con is not con_a                        # przejęta nowa baza
        assert win.axis_view.table.rowCount() == 0         # pusta → 0 teleskopów
        with pytest.raises(Exception):                     # stare połączenie zamknięte
            con_a.execute("SELECT 1")
    finally:
        win.close()


def test_closeevent_zamyka_polaczenie(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "s8.db"))
    seed(con)
    win = MainWindow(con)
    win.close()
    assert win.con is None
    with pytest.raises(Exception):
        con.execute("SELECT 1")
