"""Dziennik błędów programu na powierzchni okna (AR-312): „Pomoc → Otwórz dziennik błędów” i katalog
dziennika z danych programu użytkownika. Okno offscreen; katalog danych programu podmienia
`conftest._izoluj_dane_programu`, otwarcie pliku - atrapa `QDesktopServices.openUrl` (żaden test nie
otwiera Notatnika na pulpicie)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMenu

from horreum.gui import app as app_mod
from horreum.gui import dziennik_bledow, i18n
from horreum.gui.app import MainWindow


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _akcja_pomocy(win):
    """Akcja „Otwórz dziennik błędów” z menu Pomoc - po etykietach z katalogu."""
    menu = next(m for m in win.menuBar().findChildren(QMenu) if m.title() == i18n.t("menu.help"))
    return next(a for a in menu.actions() if a.text() == i18n.t("menu.open_error_log"))


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_menu_pomoc_otwiera_dziennik(qapp, monkeypatch, lang):
    """„Pomoc → Otwórz dziennik błędów” (bez bazy - menu działa przed otwarciem bazy): plik jest - otwiera go
    program systemu; pliku nie ma (program nie zgłosił błędu) - pasek mówi to ze ścieżką; system odmówił -
    pasek mówi, że nie udało się otworzyć. Falsyfikator: menu otwiera katalog, nie plik; cisza bez pliku."""
    i18n.set_lang(lang)
    otwarte, wynik_otwarcia = [], [True]
    monkeypatch.setattr(app_mod.QDesktopServices, "openUrl",
                        staticmethod(lambda url: otwarte.append(url.toLocalFile()) or wynik_otwarcia[0]))
    plik = dziennik_bledow.sciezka(app_mod.katalog_dziennika_bledow())
    win = MainWindow()
    try:
        _akcja_pomocy(win).trigger()
        assert otwarte == [] and win._pelny_komunikat == i18n.t("main.prog_error.log_empty", path=plik)
        dziennik_bledow.Dziennik(os.path.dirname(plik)).zapisz(
            czas="2026-10-22T12:00:00+02:00", wersja="0", watek="MainThread", naglowek="ValueError: x", slad="")
        _akcja_pomocy(win).trigger()
        assert [os.path.normcase(os.path.normpath(p)) for p in otwarte] == [os.path.normcase(plik)], otwarte
        wynik_otwarcia[0] = False
        _akcja_pomocy(win).trigger()
        assert win._pelny_komunikat == i18n.t("main.prog_error.log_open_failed", path=plik)
    finally:
        win.close()
    assert win.menuBar().findChildren(QMenu)[-1].title() == i18n.t("menu.help")


def test_katalog_dziennika_z_danych_programu(monkeypatch):
    """Katalog dziennika = `GenericDataLocation` + `Horreum` (ta sama ścieżka z kodu i z wydania - nie zależy
    od nazwy pliku wykonywalnego ani od katalogu bieżącego); system bez katalogu danych - None, a menu mówi,
    że dziennika nie ma gdzie zapisać. Falsyfikator: `AppLocalDataLocation`."""
    pytania = []

    def _atrapa(typ):
        pytania.append(typ)
        return "X:/Dane"
    monkeypatch.setattr(QStandardPaths, "writableLocation", staticmethod(_atrapa))
    assert app_mod.katalog_dziennika_bledow() == os.path.normpath("X:/Dane/Horreum")
    assert pytania == [QStandardPaths.StandardLocation.GenericDataLocation]
    monkeypatch.setattr(QStandardPaths, "writableLocation", staticmethod(lambda _typ: ""))
    assert app_mod.katalog_dziennika_bledow() is None
    assert app_mod.otworz_dziennik_bledow() == i18n.t("main.prog_error.log_no_dir")
