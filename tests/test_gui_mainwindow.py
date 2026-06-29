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


def _seeded_db(tmp_path, name="s8.db"):
    path = str(tmp_path / name)
    con = db.open_db(path)
    seed(con)
    con.close()                                            # MainWindow otwiera własne połączenie
    return path


def test_otwarte_na_bazie_montuje_oba_widoki(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert win.stack.count() == 2                      # etap 2: Pipeline + oś teleskopu
        assert isinstance(win.axis_view, TelescopeAxisView)
        assert win.axis_view.table.rowCount() == 4         # read-model odbity w osadzonym widoku
        assert all(not b.isHidden() for b in win._nav_buttons)   # 2 widoki → nawigacja odsłonięta
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
    win = MainWindow(_seeded_db(tmp_path, "a.db"))
    con_a = win.con
    try:
        assert win.axis_view.table.rowCount() == 4
        win._open_path(str(tmp_path / "b.db"))             # nowa, pusta baza
        assert win.con is not con_a                        # przejęta nowa baza
        assert win.db_path.endswith("b.db")                # ścieżka aktualna (worker jej potrzebuje)
        assert win.axis_view.table.rowCount() == 0         # pusta → 0 teleskopów
        with pytest.raises(Exception):                     # stare połączenie zamknięte
            con_a.execute("SELECT 1")
    finally:
        win.close()


def test_closeevent_zamyka_polaczenie(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    con = win.con
    win.close()
    assert win.con is None
    with pytest.raises(Exception):
        con.execute("SELECT 1")


def test_zapamietuje_ostatnia_baze_przez_callback(qapp, tmp_path):
    """Każdy wybór bazy woła wstrzyknięte `on_db_changed(path)` — to nim `main` zapisuje ostatnią
    bazę do trwałych ustawień. Start z bazą zapamiętuje ją; późniejsze „Otwórz" nadpisuje."""
    zapamietane = []
    win = MainWindow(_seeded_db(tmp_path, "a.db"), on_db_changed=zapamietane.append)
    try:
        assert zapamietane[-1].endswith("a.db")            # start z bazą → zapamiętana
        win._open_path(str(tmp_path / "b.db"))             # zmiana bazy → nadpisanie
        assert zapamietane[-1].endswith("b.db")
    finally:
        win.close()


def test_etap_pipeline_wylacza_akcje_osi_R5(qapp, tmp_path):
    """R5: w trakcie etapu pipeline'u (running_changed True) akcje ZAPISU osi są wyłączone (szczery
    disabled — worker pisze do bazy w tle). Po etapie (False) szczere stany wracają (proposed →
    approve znów aktywny)."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win.axis_view.table.selectRow(0)                   # zaznacz proposed → approve normalnie aktywny
        win._on_pipeline_running(True)
        assert not win.axis_view.btn_approve.isEnabled()
        assert not win.axis_view.btn_merge.isEnabled()
        assert not win.axis_view.btn_unmerge.isEnabled()
        win._on_pipeline_running(False)
        assert win.axis_view.btn_approve.isEnabled()       # szczery stan przywrócony (proposed)
    finally:
        win.close()
