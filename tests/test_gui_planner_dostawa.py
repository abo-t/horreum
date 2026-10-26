"""AR-334: Planer w biegu Dostawy nie liczy nocy na wpół zapisanej bazie - bieg to fakt widoku od konstruktora, każdy
powód rachunku w biegu tylko podbija generację, a koniec przebiegu liczy RAZ (`refresh` gospodarza po przebiegu).

Prawdziwy etap Dostawy w biegu (brama na „Rozwiąż”, wzór `test_gui_grid_recepty`), wejście w Planer klikiem w pasku
nawigacji, planer z prawdziwym wątkiem tła. Podsłuch liczy wywołania `targets.plan` (planer woła rdzeń przez moduł);
liczby to DELTY od chwili przed zdarzeniem, którego test dotyczy. Baza s8 nie zna stanowiska z GPS, więc każdy
rachunek kończy się pustym stanem „bez stanowiska” - licznik zapisuje wywołanie przed wyjątkiem rdzenia.
Czekanie wyłącznie na warunek (pętla zdarzeń + sen), nie na stałą liczbę obrotów. Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import targets
from horreum.gui import i18n
from horreum.gui.app import NAV_DOSTAWA, NAV_PLANER, MainWindow

from test_gui_grid_recepty import _brama_dostawy, _etap_koniec, _etap_start
from test_gui_pasek_szczegol import _czekaj, _czekaj_ms
from test_gui_strony_leniwe import _baza, _klik_nav, _okno


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_watkow_zbiorow(monkeypatch):
    """Bez wątków tła i dobudowy Zbiorów (wzór `test_gui_strony_leniwe._bez_watkow`) - mierzymy wątek planera."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)


def _licz_rachunki(monkeypatch, brama=None):
    """Lista wywołań `targets.plan`; z `brama` pierwszy rachunek czeka w wątku na `brama.set()`."""
    rachunki = []
    prawdziwy = targets.plan

    def _plan(con, **kw):
        rachunki.append(threading.current_thread().name)
        if brama is not None and len(rachunki) == 1:
            brama.wait(30)
        return prawdziwy(con, **kw)
    monkeypatch.setattr(targets, "plan", _plan)
    return rachunki


def _bez_watku(planer):
    return planer._worker is None and planer._thread is None


def _po_koncu(planer, rachunki, przed, opis):
    """Czekaj na pierwszy rachunek końca biegu i na ciszę: wątek sprzątnięty, a restart (drugi rachunek) miał czas
    wystartować - potem wątek znów sprzątnięty."""
    _czekaj(lambda: len(rachunki) > przed and _bez_watku(planer), opis)
    _czekaj_ms(200)
    _czekaj(lambda: _bez_watku(planer), f"{opis} - cisza")


def test_planer_zbudowany_w_biegu_liczy_raz_po_koncu(qapp, tmp_path, monkeypatch):
    """Pierwsze wejście w Planer w biegu Dostawy: planer wygaszony, bez wątku rachunku, nagłówek nocy mówi, że
    policzy po końcu Dostawy; po końcu przebiegu dokładnie jeden rachunek i zdanie znika. Falsyfikatory: konstruktor
    liczy przed zatrzaskiem (stan sprzed AR-334 - rachunek w biegu i drugi po końcu); `_zbuduj_planer` bez
    `w_biegu=`; `set_busy(False)` liczy obok `refresh` gospodarza (dwa rachunki po końcu)."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        przed = len(rachunki)
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        assert _bez_watku(planer), "rachunek nocy ruszył w biegu Dostawy"
        _czekaj_ms(200)
        assert len(rachunki) == przed and _bez_watku(planer)
        assert not planer.isEnabled()
        assert planer.night_label.text() == i18n.t("planner.after_intake")
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, przed, "rachunek po końcu biegu")
        assert len(rachunki) - przed == 1, rachunki
        assert planer.isEnabled() and planer.night_label.text() != i18n.t("planner.after_intake")
    finally:
        puszczona.set()
        win.close()


def test_planer_bez_stanowiska_wejscie_w_biegu_nie_liczy(qapp, tmp_path, monkeypatch):
    """Planer zbudowany przed biegiem na bazie bez stanowiska: wejście w niego w biegu (gospodarz woła `refresh`, dopóki
    trwa pusty stan „bez stanowiska”) nie liczy; koniec biegu liczy raz. Falsyfikator: `replan` bez bramki biegu."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: planer.bez_stanowiska and _bez_watku(planer), "planer bez stanowiska przed biegiem")
        po_budowie = len(rachunki)
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        _klik_nav(win, NAV_PLANER)
        assert _bez_watku(planer), "wejście w biegu uruchomiło rachunek"
        _czekaj_ms(200)
        assert len(rachunki) == po_budowie and _bez_watku(planer)
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, po_budowie, "rachunek po końcu biegu")
        assert len(rachunki) - po_budowie == 1, rachunki
    finally:
        puszczona.set()
        win.close()


def test_planer_restart_watku_w_biegu_czeka_na_koniec(qapp, tmp_path, monkeypatch):
    """Rachunek sprzed biegu w wątku, za nim generacja w kolejce (`refresh`), potem start biegu: koniec starego wątku
    w biegu NIE startuje drugiego rachunku (`_cleanup_thread`), koniec biegu liczy raz. Falsyfikator: restart
    w `_cleanup_thread` bez warunku biegu."""
    brama = threading.Event()
    rachunki = _licz_rachunki(monkeypatch, brama=brama)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: len(rachunki) == 1, "pierwszy rachunek w wątku")
        planer.refresh()
        assert planer._worker is not None and planer._pending_gen()
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        brama.set()
        _czekaj(lambda: _bez_watku(planer), "wątek sprzed biegu sprzątnięty")
        _czekaj_ms(200)
        assert len(rachunki) == 1 and _bez_watku(planer), rachunki
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, 1, "rachunek po końcu biegu")
        assert len(rachunki) == 2, rachunki
    finally:
        brama.set()
        puszczona.set()
        win.close()
