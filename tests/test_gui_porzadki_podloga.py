"""Podłoga okna nie zależy od liczby wierszy Porządków (AR-188).

Minimum okna liczy się z najwyższej strony stosu, a lista Porządków miała wysokość stałą na całą
treść - każdy nowy wiersz podnosił podłogę okna o wysokość wiersza. Teraz lista ma podłogę
w wierszach (`tasks._LISTA_ZADAN_MIN_WIERSZY`) i sufit = treść, a w układzie rośnie do treści,
gdy pion jest. Testy pinują RELACJE (N i N+10 wierszy - ta sama podłoga; wysokie okno - cała
treść bez suwaka; okno na podłodze - suwak), nie piksele: metryki offscreen nie są natywne."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QLayout, QListWidgetItem

from horreum.gui import rows
from horreum.gui.app import NAV_PORZADKI, MainWindow

from test_gui_mainwindow import _seeded_db


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _podlogi(win):
    """`(podłoga strony listy Porządków, podłoga okna)` - minimum z unieważnionych układów (okno
    bywa niepokazane: zdarzenie `LayoutRequest` aktywuje układ tylko widocznego widżetu)."""
    for lay in win.findChildren(QLayout):
        lay.invalidate()
    win.layout().invalidate()
    win.layout().activate()
    return (win.tasks_view.pages.widget(0).minimumSizeHint().height(),
            win.minimumSizeHint().height())


def _dopisz_wiersze(tv, n):
    for i in range(n):
        it = QListWidgetItem(f"dopisany wiersz {i}")
        it.setData(rows.SECONDARY, "0  ›")
        tv.tasks.addItem(it)
    tv._fit_task_list()


def _tresc(lista):
    m = lista.model()
    return (sum(lista.sizeHintForIndex(m.index(i, 0)).height() for i in range(lista.count()))
            + 2 * lista.frameWidth())


def _czekaj(warunek, limit_s=5.0):
    """Pętla zdarzeń, aż warunek zajdzie (jeden `processEvents` po geście mierzy fikcję)."""
    koniec = time.monotonic() + limit_s
    while not warunek():
        assert time.monotonic() < koniec, "układ nie doszedł do stanu"
        QCoreApplication.processEvents()
        time.sleep(0.01)


def test_podloga_okna_nie_zalezy_od_liczby_wierszy_Porzadkow(qapp, tmp_path):
    """+10 wierszy listy = ta sama podłoga strony listy i całego okna, a sufit listy rośnie z treścią
    (żaden wiersz nie jest schowany na stałe). Falsyfikator: `_fit_task_list` z
    `setFixedHeight(treść)` → obie podłogi rosną o 10 wierszy."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tv = win.tasks_view
        tv.refresh_counts()
        przed = _podlogi(win)
        _dopisz_wiersze(tv, 10)
        assert _podlogi(win) == przed
        assert tv.tasks.maximumHeight() == _tresc(tv.tasks)
        assert tv.tasks.minimumHeight() < tv.tasks.maximumHeight()
    finally:
        win.close()


def test_lista_Porzadkow_rosnie_do_tresci_gdy_jest_pion_a_przewija_na_podlodze(qapp, tmp_path):
    """Okno pokazane, Porządki na wierzchu: wysokie okno - lista ma całą treść, suwak bez zakresu;
    okno zwężone do podłogi - lista niższa niż treść (nie niższa niż podłoga), suwak z zakresem.
    Falsyfikator: lista bez stretchu w układzie strony → przy wysokim oknie lista stoi na podłodze
    z suwakiem."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.show()
        win._show_view(NAV_PORZADKI)
        tv, lista = win.tasks_view, win.tasks_view.tasks
        _dopisz_wiersze(tv, 20)
        win.resize(1400, 2400)
        _czekaj(lambda: lista.height() == lista.maximumHeight())
        assert lista.maximumHeight() == _tresc(lista)
        assert lista.verticalScrollBar().maximum() == 0
        win.resize(1400, win.minimumSizeHint().height())
        _czekaj(lambda: lista.height() < lista.maximumHeight())
        assert lista.height() >= lista.minimumHeight()
        _czekaj(lambda: lista.verticalScrollBar().maximum() > 0)
    finally:
        win.close()
