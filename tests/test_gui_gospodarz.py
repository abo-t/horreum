"""Gospodarz okna (`MainWindow`) jako jedyny właściciel reguł, które miały kopie albo wartość jednego nadawcy
(offscreen):

* „Wciągnij z WBPP…” - JEDNA reguła odmowy (`_powod_odmowy_zniw`) dla kliku i dla pozycji menu „Więcej…” Domu, czytana
  przy KAŻDYM otwarciu menu; budowa Dostawy po oknie żniw jako komenda (`_wejdz`) w obwódce, która mówi utratę rodowodu
  i wynik okna (AR-354);
* odcisk raportu Przyjmij po ostatnim pisarzu ogona końca biegu - log nie mówi „stan sprzed Twoich zmian” po zapisie
  gospodarza, każdą drogą końca, a błąd odcisku nie zostawia osi zajętej (AR-354, ogon biegu AR-373);
* zatrzask zapisu do plików dla odbiorców spoza mutexu - `any` źródeł, nie wartość nadawcy (AR-353);
* kolejka odłożonych recept osi: chwila spoza podań podaje wpis za zdjętą PODANĄ głową - aktywacja okna wyłącznie, gdy
  zdjęła z paska STOJĄCĄ gotowość, zamknięcie gestu w Osi teleskopu zawsze; recepta niesie tożsamość zamiaru, a
  wykonawca przy innej odmawia zdaniem (AR-355).

Gesty prawdziwe: klik przycisku „Więcej…” otwiera menu (PySide6 6.9: `popup` - klik wraca z menu na ekranie,
`aboutToShow` pada przed pokazaniem), klik pozycji ją wybiera; etapy Dostawy i zapisy do plików - prawdziwe, zatrzymane
bramą. Emisje sygnałów zapisu wprost zostają wyłącznie w teście agregacji dwóch źródeł (prawdziwe zapisy obu powierzchni
nie mogą biec naraz - mutex D-PD-3). Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os
import sqlite3
import sys
import threading
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from horreum import db, repo, stacks, writeback
from horreum.gui import home as home_mod
from horreum.gui import i18n, queries
from horreum.gui.app import (NAV_DOM, NAV_DOSTAWA, NAV_PORZADKI, NAV_ZBIORY, STRONA_DOM, STRONA_DOSTAWA,
                             STRONA_ZBIORY, MainWindow)
from horreum.gui.wb_worker import ZdanieZeSzczegolem, zlacz_zdania

from test_gui_grid_recepty import (_bajty, _brama_dostawy, _czekaj_na_cofniecie, _etap_koniec,  # noqa: F401
                                   _etap_start, _klik_recepty, _naprawa_prawdziwym_exec, _okno_naprawy, brama)
from test_gui_grid_szuflada import _aktywuj
from test_gui_optyka_teleskopu import (NOW, _baza as _baza_osi, _baza_z_dopisanymi, _cofnij_dopisanie_obok,
                                       _odloz_dopisanie, _pokazane, _wiersz_osi_teleskopu, _wycofany)
from test_gui_pasek_szczegol import _awaria_skanu, _czekaj
from test_gui_strony_leniwe import _baza, _klik_nav, _okno, _zbudowane


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_watkow(monkeypatch):
    """Tryb przewidywalny: bez wątków tła Zbiorów i bez dobudowy Zbiorów w bezczynności - testy mierzą drogi do stron
    niezbudowanych i zatrzaski zbudowanych bez strony, która powstałaby sama w pierwszym obrocie pętli."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)


# ---------------------------------------------------------------- gesty menu „Więcej…” Domu

def _odmowy_zniw():
    """Zdania odmowy złotej akcji w bieżącym języku - pozycja bez podpowiedzi pokazuje tekst akcji (Qt), nie pusty."""
    return {i18n.t("pipeline.refuse.delivery_running"), i18n.t("pipeline.refuse.writeback"),
            i18n.t("pipeline.refuse.no_db"), i18n.t("pipeline.refuse.source_probe")}


def _menu_wiecej(win):
    """Prawdziwe otwarcie menu „Więcej…” Domu klikiem przycisku - `(menu, pozycja „Wciągnij z WBPP…”)`; menu chowa
    wołający. Klik wraca z menu na ekranie (`popup`); BEZPIECZNIK na wypadek, gdyby przycisk otwierał menu pętlą
    `exec()` (klik wtedy nie wraca): zegar chowa po kilku sekundach badane menu (inny popup tylko wtedy, gdy menu nie
    jest widoczne, a klik i tak nie wrócił) i zapisuje to, a test kończy się asercją zamiast wisieć do limitu biegu."""
    btn = win.home_view.btn_wiecej
    menu = btn.menu()
    zawieszone = []

    def _bezpiecznik():
        popup = menu if menu.isVisible() else QApplication.activePopupWidget()
        if popup is not None:
            zawieszone.append(popup)
            popup.hide()
    bezpiecznik = QTimer()
    bezpiecznik.setSingleShot(True)
    bezpiecznik.timeout.connect(_bezpiecznik)
    bezpiecznik.start(5000)
    try:
        QTest.mouseClick(btn, Qt.LeftButton)
    finally:
        bezpiecznik.stop()
    assert not zawieszone, "klik „Więcej…” nie wrócił - menu w pętli `exec()`, zamknięte bezpiecznikiem"
    assert menu.isVisible(), "menu „Więcej…” się nie otworzyło"
    return menu, win.home_view.akcje_wiecej[home_mod.WIECEJ_ZNIWA]


def _stan_pozycji_zniw(win):
    """`(czynna, podpowiedź)` pozycji „Wciągnij z WBPP…” w chwili, w której człowiek ją widzi - po prawdziwym otwarciu
    menu; menu chowa się przed powrotem każdą drogą."""
    menu, akcja = _menu_wiecej(win)
    try:
        return akcja.isEnabled(), akcja.toolTip()
    finally:
        menu.hide()


def _wybierz_zniwa(win):
    """Prawdziwy wybór „Wciągnij z WBPP…”: otwarcie menu i klik pozycji. Pozycja wygaszona - klik nic nie robi, a menu
    chowa `finally`."""
    menu, akcja = _menu_wiecej(win)
    try:
        QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier, menu.actionGeometry(akcja).center())
    finally:
        menu.hide()


def _okno_zniw(monkeypatch, korzen, stosy):
    """Okno żniw podstawione w `sys.modules` (gospodarz importuje je leniwie): wciągnęło `stosy` (`(sha1, wejścia,
    kanon wydania)`), oddaje `korzen` do przyjęcia i mówi „Wciągnięto stosy”. Zwraca połączenia otwartych okien."""
    okna = []

    class _OknoZniw:
        def __init__(self, con, **_kw):
            okna.append(con)
            self.summary = "Wciągnięto stosy"
            self.harvested_root = str(korzen)
            self.harvested_stacks = list(stosy)

        def exec(self):
            return QDialog.Accepted
    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    return okna


def _pisarz_rodowodu(monkeypatch, zdarzenia):
    """Zapis rodowodu żniw (`stacks.record_harvest_inputs`) z REALNĄ mutacją przez połączenie okna (klinga osi obiektu
    z eventem): odcisk raportu Przyjmij to liczniki TEGO połączenia, a rdzeń zapisu rodowodu ma własne testy. Zdarzenie
    „zapis” trafia do wspólnej listy kolejności końca biegu."""
    def _zapis(con, *, master_sha1_data, input_frame_ids, now, actor="harvest"):
        przed = con.total_changes
        repo.upsert_object(con, canon=f"NGC{7980 + len(zdarzenia)}", catalog="NGC", kind="deep_sky", now=now)
        assert con.total_changes > przed, "pisarz bez zapisu - test nie mierzy odcisku"
        zdarzenia.append("zapis")
        return {"reason": None, "linked": 1, "upgraded": 0, "dropped": 0, "kept_user": 0}
    monkeypatch.setattr(stacks, "record_harvest_inputs", _zapis)


def _rodowod_stosow(monkeypatch, *, przerwany=False):
    """Etap „rodowód stosów” łańcucha „all” PRAWDZIWY, wstrzymany bramą (zwracaną; `set()` puszcza); `przerwany` - wynik
    oznaczony przerwaniem, jak anulowanie w czytaniu plików. Łańcuch woła `stacks.run_stack_lineage` przez atrybut
    modułu (`derive.DERIVED_STAGES`), więc brama stoi tam."""
    import dataclasses
    puszczona = threading.Event()
    prawdziwy = stacks.run_stack_lineage

    def _etap(con, **k):
        puszczona.wait(30)
        wynik = prawdziwy(con, **k)
        return dataclasses.replace(wynik, cancelled=True) if przerwany else wynik
    monkeypatch.setattr(stacks, "run_stack_lineage", _etap)
    return puszczona


# ---------------------------------------------------------------- AR-354: jedna reguła odmowy żniw

def test_menu_wiecej_przy_sondzie_zrodla_gasi_wciagnij_z_powodem_biegu(qapp, tmp_path, monkeypatch, ustawienia):
    """Dostawa zbudowana, w biegu sama sonda źródła po „Wskaż katalog…” (etap bez bazy: wątek widoku jest, a zatrzask
    biegu gospodarza nie). Otwarcie menu „Więcej…” na Domu pokazuje „Wciągnij z WBPP…” wygaszone z podpowiedzią biegu,
    klik w nią niczego nie otwiera; po końcu sondy ponowne otwarcie - czynna. Falsyfikatory: Dom z własną regułą
    (pozycja czynna w sondzie); menu bez pytania gospodarza przy otwarciu; reguła gospodarza wyłącznie z zatrzasków
    (gałąź zbudowanej Dostawy pominięta); wygaszenie bez podpowiedzi."""
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui.pipeline import PipelineWorker
    okna = _okno_zniw(monkeypatch, tmp_path, [])
    katalog = tmp_path / "zrodlo"
    katalog.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(katalog)))
    puszczona = threading.Event()
    prawdziwa_sonda = PipelineWorker._zrodlo

    def _sonda_za_brama(self, *a, **k):
        puszczona.wait(30)
        return prawdziwa_sonda(self, *a, **k)
    monkeypatch.setattr(PipelineWorker, "_zrodlo", _sonda_za_brama)
    win = _okno(_baza(tmp_path))
    try:
        czynna, podpowiedz = _stan_pozycji_zniw(win)
        assert czynna and podpowiedz not in _odmowy_zniw()
        _klik_nav(win, NAV_DOSTAWA)
        pv = win.pipeline_view
        QTest.mouseClick(pv.btn_pick, Qt.LeftButton)
        assert pv._thread is not None and not win._dostawa_w_biegu, "sonda źródła nie ruszyła - test nie mierzy reguły"
        _klik_nav(win, NAV_DOM)
        assert _stan_pozycji_zniw(win) == (False, i18n.t("pipeline.refuse.source_probe"))   # nie „postęp na stronie”
        _wybierz_zniwa(win)
        assert okna == []
        puszczona.set()
        _czekaj(lambda: pv._thread is None, "koniec sondy źródła")
        czynna, podpowiedz = _stan_pozycji_zniw(win)
        assert czynna and podpowiedz not in _odmowy_zniw()
    finally:
        puszczona.set()
        _czekaj(lambda: win._gotowy("pipeline_view") is None or win._gotowy("pipeline_view")._thread is None,
                "koniec sondy źródła")
        win.close()


def test_menu_wiecej_przy_zapisie_zbiorow_mowi_zapis_bez_budowy_dostawy(qapp, tmp_path, monkeypatch):
    """Zapis Zbiorów do plików w toku (uchwyt gridu zgłasza zajętość), Dostawa niezbudowana: otwarcie menu pokazuje
    pozycję wygaszoną z podpowiedzią zapisu, a reguła nie buduje Dostawy dla samego powodu (AR-335); koniec zapisu ją
    zapala. Falsyfikator: reguła przez property `pipeline_view` (budowa Dostawy przy otwarciu menu)."""
    win = _okno(_baza(tmp_path))
    try:
        grid = win.grid_view
        grid._wb.busy_changed.emit(True)
        try:
            assert _stan_pozycji_zniw(win) == (False, i18n.t("pipeline.refuse.writeback"))
            assert STRONA_DOSTAWA not in _zbudowane(win)
        finally:
            grid._wb.busy_changed.emit(False)
        czynna, podpowiedz = _stan_pozycji_zniw(win)
        assert czynna and podpowiedz not in _odmowy_zniw()
        assert STRONA_DOSTAWA not in _zbudowane(win)
    finally:
        win.close()


@pytest.mark.parametrize("stosy", [0, 1])
def test_porazka_budowy_dostawy_po_oknie_zniw_mowi_utrate_rodowodu_i_wynik(qapp, tmp_path, monkeypatch, stosy):
    """Wybór „Wciągnij z WBPP…” z menu Domu (prawdziwe otwarcie i klik), okno żniw skopiowało mastery, a budowa
    Dostawy pada błędem bazy: JEDNA próba budowy, jedno zgłoszenie do straży, pasek mówi utratę rodowodu dokładnego NA
    POCZĄTKU (gdy były stosy) i wynik okna; ogona biegu nie ma, sidebar i stos zostają na Domu. Falsyfikatory:
    przełączenie wiersza zamiast komendy (porażka połknięta w slocie, druga budowa przez property, pasek pusty);
    obwódka bez zdania utraty; obwódka połykająca wyjątek."""
    from horreum.gui.pipeline import PipelineView
    okna = _okno_zniw(monkeypatch, tmp_path, [("sha-stosu", (1,), None)] * stosy)
    proby, wyjatki = [], []

    def _pada(self, *a, **k):
        proby.append(1)
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(PipelineView, "__init__", _pada)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        assert STRONA_DOSTAWA not in _zbudowane(win)
        _wybierz_zniwa(win)
        QApplication.processEvents()
        assert okna == [win.con]
        assert proby == [1], "druga budowa Dostawy w tym samym geście"
        assert len(wyjatki) == 1 and isinstance(wyjatki[0], sqlite3.OperationalError), wyjatki
        zdania = ([i18n.t("status.harvest_lineage_lost", n=1)] if stosy else []) + ["Wciągnięto stosy"]
        assert str(win._pelny_komunikat) == str(zlacz_zdania(" - ", zdania))
        assert win._ogon_biegu is None
        assert win.stack.currentIndex() == STRONA_DOM and win.nav.currentRow() == NAV_DOM
        assert STRONA_DOSTAWA not in _zbudowane(win)
    finally:
        win.close()


def test_zniwa_z_domu_buduja_dostawe_raz_i_stawiaja_ogon_biegu(qapp, tmp_path, monkeypatch):
    """Szew z ogonem biegu na PRAWDZIWYM łańcuchu: wybór „Wciągnij z WBPP…” z menu Domu przy niezbudowanej Dostawie -
    strona powstaje RAZ (komenda), łańcuch rusza na korzeniu kopii, a ogon biegu stoi pod znacznikiem startu TEGO
    przebiegu (rodowód stosów za bramą); po końcu pisarz rodowodu pisze raz, ogon zdjęty. Falsyfikator: budowa
    przełączeniem wiersza i odczytem widoku (dwie budowy) albo zapis rodowodu bez ogona."""
    from horreum.gui.flows import przyjmij as przyjmij_mod
    korzen = tmp_path / "zniwa"
    korzen.mkdir()
    _okno_zniw(monkeypatch, korzen, [("sha-stosu", (1,), None)])
    zdarzenia = []
    _pisarz_rodowodu(monkeypatch, zdarzenia)
    puszczona = _rodowod_stosow(monkeypatch)
    budowy = []
    prawdziwa = przyjmij_mod.PrzyjmijView

    class _Liczona(prawdziwa):
        def __init__(self, *a, **k):
            budowy.append(1)
            super().__init__(*a, **k)
    monkeypatch.setattr(przyjmij_mod, "PrzyjmijView", _Liczona)
    win = _okno(_baza(tmp_path))
    try:
        assert STRONA_DOSTAWA not in _zbudowane(win)
        _wybierz_zniwa(win)
        pv = win._strony["pipeline_view"]
        since = pv.last_run["since"]
        assert budowy == [1] and since is not None and win._ogon_trwa(since)
        assert win.stack.currentIndex() == STRONA_DOSTAWA and win.nav.currentRow() == NAV_DOSTAWA
        puszczona.set()
        _czekaj(lambda: pv._thread is None and win._ogon_biegu is None, "koniec przebiegu i ogona")
        assert zdarzenia == ["zapis"] and budowy == [1]
    finally:
        puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-354: odcisk raportu Przyjmij po ogonie biegu

def _podsluch_konca(monkeypatch, win, zdarzenia):
    """Kolejność końca biegu: odcisk raportu Przyjmij po ogonie (`odcisk_po_ogonie`) i odświeżenie widoków gospodarza
    dopisują się do `zdarzenia` (obok „zapis” pisarza rodowodu); prawdziwe metody biegną dalej."""
    przyjmij = win._strony["przyjmij_view"]
    prawdziwy_odcisk = przyjmij.odcisk_po_ogonie
    monkeypatch.setattr(przyjmij, "odcisk_po_ogonie", lambda: (zdarzenia.append("odcisk"), prawdziwy_odcisk())[1])
    prawdziwe_odswiezenie = win._odswiez_widoki_po_przebiegu
    monkeypatch.setattr(win, "_odswiez_widoki_po_przebiegu",
                        lambda: (zdarzenia.append("odswiez"), prawdziwe_odswiezenie())[1])
    return przyjmij


@pytest.mark.parametrize("koniec", ["sukces", "blad", "przerwany", "odmowa", "bez_ogona"])
def test_odcisk_raportu_przyjmij_po_ostatnim_pisarzu_kazda_droga_konca(qapp, tmp_path, monkeypatch, koniec):
    """„Wciągnij z WBPP…” w Dostawie (prawdziwy klik, prawdziwy łańcuch) każdą drogą końca: przy ogonie biegu odcisk
    stanu raportu Przyjmij bierze się PO zapisie pisarza i PRZED jedynym odświeżeniem widoków, a jest równy stanowi
    połączenia okna po końcu (przebieg odmówiony - bez odcisku); bez ogona (żniwa bez stosów) - odcisk z końca
    przebiegu, jak dotąd, i jedno odświeżenie. Falsyfikatory: brak odcisku po ogonie (odcisk sprzed zapisu rodowodu);
    odcisk po odświeżeniu; odcisk przebiegu odmówionego."""
    korzen = tmp_path / "zniwa"
    if koniec != "odmowa":                        # odmowa = źródło nieosiągalne (sonda źródła w wątku tła)
        korzen.mkdir()
    if koniec == "blad":
        _awaria_skanu(monkeypatch)
    if koniec == "przerwany":
        _rodowod_stosow(monkeypatch, przerwany=True).set()
    _okno_zniw(monkeypatch, korzen, [] if koniec == "bez_ogona" else [("sha-stosu", (1,), None)])
    zdarzenia = []
    _pisarz_rodowodu(monkeypatch, zdarzenia)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_DOSTAWA)
        pv = win.pipeline_view
        przyjmij = _podsluch_konca(monkeypatch, win, zdarzenia)
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        _czekaj(lambda: pv._thread is None and not win.object_view._busy and win._ogon_biegu is None,
                "koniec przebiegu")
        zapis = pv.last_run
        assert {"sukces": not (zapis["failed"] or zapis["cancelled"] or zapis["refused"]),
                "blad": bool(zapis["failed"]), "przerwany": bool(zapis["cancelled"]),
                "odmowa": bool(zapis["refused"]),
                "bez_ogona": not (zapis["failed"] or zapis["cancelled"] or zapis["refused"])}[koniec], zapis
        assert zdarzenia == {"sukces": ["zapis", "odcisk", "odswiez"], "bez_ogona": ["odswiez"]}.get(
            koniec, ["odcisk", "odswiez"])
        if koniec == "odmowa":
            assert przyjmij._odcisk_przebiegu is None
        else:
            assert przyjmij._odcisk_przebiegu == queries.odcisk_bazy(win.con)
    finally:
        win.close()


def _klik_wiersza_porzadkow(win, klucz):
    """Prawdziwe wejście człowieka na podstronę Porządków: klik „Porządki” w sidebarze i klik wiersza listy o kluczu
    `klucz` (wiersz z kubełkiem sam otwiera podstronę i zaznacza kubełek - lista klatek i gest stoją od razu). Klik
    czeka, aż wiersz będzie czynny (rachunek liczników)."""
    _klik_nav(win, NAV_PORZADKI)
    lista = win.tasks_view.tasks

    def _wiersz():
        return next((lista.item(i) for i in range(lista.count()) if lista.item(i).data(Qt.UserRole) == klucz), None)
    _czekaj(lambda: _wiersz() is not None and bool(_wiersz().flags() & Qt.ItemIsEnabled), f"wiersz {klucz} czynny")
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, lista.visualItemRect(_wiersz()).center())
    QApplication.processEvents()


def _przypisz_obiekt_w_oknie(win, monkeypatch):
    """Prawdziwy gest człowieka „Przypisz obiekt…” w Porządkach: kubełek nierozpoznanej nazwy z nagłówka zaznaczony,
    klik przycisku; okno wyboru obiektu podstawione (M42 pod kluczem nazwy kubełka - jak wybór człowieka). Zapis idzie
    klingą osi (`repo.user_assign_object`); warunek wstępny - odcisk bazy okna się zmienił."""
    import horreum.gui.app as app_mod
    from horreum.resolve._text import norm_alnum

    class _OknoObiektu:
        def __init__(self, con, *, object_raw, **_kw):
            self.selected = ("M42", "Messier", None, norm_alnum(object_raw))

        def exec(self):
            return QDialog.Accepted
    monkeypatch.setattr(app_mod, "AssignObjectDialog", _OknoObiektu)
    _klik_wiersza_porzadkow(win, "unresolved_lights")
    ov = win.object_view
    assert ov._selected_review()[0] == "object_raw" and ov.assign_btn.isEnabled(), ov._selected_review()
    przed = queries.odcisk_bazy(win.con)
    QTest.mouseClick(ov.assign_btn, Qt.LeftButton)
    assert queries.odcisk_bazy(win.con) != przed, "gest bez zapisu - kontrola nie mierzy podpisu"


def test_log_przyjmij_po_zapisie_rodowodu_zniw_bez_podpisu_zmian(qapp, tmp_path, monkeypatch):
    """Żniwa ze stosem w Dostawie (prawdziwy łańcuch, log z liniami): rodowód zapisany przez połączenie okna PO końcu
    przebiegu nie jest zmianą człowieka - wejście w Dostawę z Domu zostawia log bez podpisu „stan sprzed Twoich zmian”.
    Kontrola: prawdziwy gest człowieka („Przypisz obiekt…” w Porządkach) i powrót do Dostawy - podpis stoi.
    Falsyfikator: odcisk raportu tylko z `run_finished` (sprzed zapisu rodowodu)."""
    korzen = tmp_path / "zniwa"
    korzen.mkdir()
    _okno_zniw(monkeypatch, korzen, [("sha-stosu", (1,), None)])
    zdarzenia = []
    _pisarz_rodowodu(monkeypatch, zdarzenia)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_DOSTAWA)
        pv = win.pipeline_view
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        _czekaj(lambda: pv._thread is None and win._ogon_biegu is None, "koniec przebiegu i ogona")
        assert zdarzenia == ["zapis"] and pv._summary_lines, "log bez linii - podpis nie miałby czego podpisać"
        _klik_nav(win, NAV_DOM)
        _klik_nav(win, NAV_DOSTAWA)
        assert pv.lbl_summary_head.isHidden(), "zapis rodowodu gospodarza podpisany jako zmiana człowieka"
        _przypisz_obiekt_w_oknie(win, monkeypatch)
        _klik_nav(win, NAV_DOSTAWA)
        assert not pv.lbl_summary_head.isHidden()
    finally:
        win.close()


def test_blad_odcisku_po_ogonie_zwalnia_os_i_idzie_do_strazy(qapp, tmp_path, monkeypatch):
    """Żniwa ze stosem w Dostawie (prawdziwy klik, prawdziwy łańcuch): ostatni pisarz ogona skończył, a odcisk stanu
    raportu Przyjmij pada błędem bazy. Błąd idzie do straży (jedno zgłoszenie), ogon zdjęty, a odświeżenie widoków
    i zwolnienie osi obiektu i tak biegną - oś nie zostaje zajęta po zakończonym przebiegu. Falsyfikator: odcisk poza
    `try` (wyjątek wychodzi przed odświeżeniem, oś zablokowana do końca sesji)."""
    korzen = tmp_path / "zniwa"
    korzen.mkdir()
    _okno_zniw(monkeypatch, korzen, [("sha-stosu", (1,), None)])
    zdarzenia, wyjatki = [], []
    _pisarz_rodowodu(monkeypatch, zdarzenia)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_DOSTAWA)
        pv = win.pipeline_view
        przyjmij = win._strony["przyjmij_view"]

        def _odcisk_pada():
            zdarzenia.append("odcisk")
            raise sqlite3.OperationalError("disk I/O error")
        monkeypatch.setattr(przyjmij, "odcisk_po_ogonie", _odcisk_pada)
        prawdziwe_odswiezenie = win._odswiez_widoki_po_przebiegu
        monkeypatch.setattr(win, "_odswiez_widoki_po_przebiegu",
                            lambda: (zdarzenia.append("odswiez"), prawdziwe_odswiezenie())[1])
        monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        _czekaj(lambda: pv._thread is None and win._ogon_biegu is None and bool(wyjatki),
                "koniec przebiegu i zgłoszenie błędu odcisku")
        QApplication.processEvents()
        assert len(wyjatki) == 1 and isinstance(wyjatki[0], sqlite3.OperationalError), wyjatki
        assert zdarzenia == ["zapis", "odcisk", "odswiez"]
        assert win._ogon_biegu is None and win.object_view._busy is False
    finally:
        win.close()


# ---------------------------------------------------------------- AR-353: zatrzask zapisu dla odbiorców spoza mutexu

@pytest.mark.parametrize("kolejnosc", ["grid_os", "os_grid"])
def test_dostawa_zbudowana_gasnie_do_konca_ostatniego_zapisu(qapp, tmp_path, kolejnosc):
    """Agregacja dwóch źródeł zapisu do plików (sygnały uchwytów wprost - prawdziwe zapisy obu powierzchni nie biegną
    naraz): Dostawa i jej raport zbudowane PRZED zapisem gasną do końca OSTATNIEGO zapisu, a reguła żniw mówi zapis;
    każda strona mutexu dostaje wyłącznie cudze źródło. Falsyfikatory: rozsyłka gołej wartości nadawcy (koniec jednego
    zapisu zapala Dostawę przy drugim); zatrzask gospodarza także do szuflady Zbiorów (szuflada gasi własny zapis)."""
    win = _okno(_baza(tmp_path))
    try:
        grid, ov = win.grid_view, win.object_view
        pv, przyjmij = win.pipeline_view, win.przyjmij_view
        zrodla = {"grid": grid._wb.busy_changed, "os": ov.writeback_busy}
        pierwszy, drugi = ("grid", "os") if kolejnosc == "grid_os" else ("os", "grid")
        zrodla[pierwszy].emit(True)
        zrodla[drugi].emit(True)
        zrodla[drugi].emit(False)                        # koniec drugiego zapisu - pierwszy dalej pisze
        assert pv._writeback_busy and not pv.btn_receive.isEnabled() and not pv.lbl_writeback_busy.isHidden()
        assert przyjmij._writeback_busy
        assert win._powod_odmowy_zniw() == i18n.t("pipeline.refuse.writeback")
        assert bool(grid._foreign_wb) == (pierwszy == "os") and bool(ov._foreign_wb) == (pierwszy == "grid")
        zrodla[pierwszy].emit(False)
        assert not pv._writeback_busy and pv.btn_receive.isEnabled() and not przyjmij._writeback_busy
        assert win._powod_odmowy_zniw() is None and not grid._foreign_wb and not ov._foreign_wb
    finally:
        win.close()


@pytest.mark.parametrize("zrodlo", ["os", "grid"])
def test_prawdziwy_zapis_do_plikow_gasi_dostawe_raport_i_menu_domu(qapp, tmp_path, brama, zrodlo):
    """Prawdziwy zapis do plików zatrzymany bramą po pierwszym pliku - cofnięcie zapisu kart z paska Porządków (klik
    recepty) albo zapis szuflady Zbiorów („Zatwierdź”): Dostawa zbudowana przed zapisem i jej raport gasną, a pozycja
    „Wciągnij z WBPP…” w otwartym menu Domu mówi zapis; po końcu zapisu wszystko wraca. Falsyfikator: gospodarz bez
    rozsyłki zatrzasku do zbudowanej Dostawy (okablowanie gest → uchwyt → gospodarz → odbiorcy)."""
    win, _path, _pliki = _okno_naprawy(tmp_path)
    try:
        pv, przyjmij = win.pipeline_view, win.przyjmij_view          # Dostawa zbudowana PRZED zapisem
        if zrodlo == "os":
            _naprawa_prawdziwym_exec(win)
            brama.wlaczona = True
            _klik_recepty(win)
        else:
            g = win.grid_view
            win._show_view(NAV_ZBIORY)
            g.refresh()
            g.macro_bar.asg_kw.setCurrentText("TELESCOP")
            g.macro_bar.asg_op.setCurrentIndex(0)
            g.macro_bar.asg_expr.setText("EQ6")
            g.macro_bar._emit_stage()
            assert g._pending_count() == 2, "makro bez stagingu - test nie mierzy zapisu"
            brama.wlaczona = True
            QTest.mouseClick(g.drawer.btn_commit, Qt.LeftButton)
        _czekaj(brama.doszlo.is_set, "pierwszy plik zapisu")
        QApplication.processEvents()
        assert pv._writeback_busy and not pv.btn_receive.isEnabled() and przyjmij._writeback_busy
        _klik_nav(win, NAV_DOM)
        assert _stan_pozycji_zniw(win) == (False, i18n.t("pipeline.refuse.writeback"))
        brama.wlaczona = False
        brama.puszczona.set()
        _czekaj(lambda: not any(win._zapis_w_biegu.values()), "koniec zapisu do plików")
        assert not pv._writeback_busy and pv.btn_receive.isEnabled() and not przyjmij._writeback_busy
        czynna, podpowiedz = _stan_pozycji_zniw(win)
        assert czynna and podpowiedz not in _odmowy_zniw()
    finally:
        brama.puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-355: wpis za zdjętą głową kolejki

def _baza_z_trzema_dopisanymi(tmp_path):
    """Baza osi (`test_gui_optyka_teleskopu._baza`) z TRZEMA gestami „Dopisz nowy…” - dwa na obcych klatkach RC8 800 mm,
    trzeci na klatce RC8 1600 mm (ten sam teleskop źródłowy). Ścieżka i lista `(teleskop, etykieta)`; połączenie
    zamknięte - okno otwiera własne."""
    con, obce, rc8 = _baza_osi(tmp_path)
    rc8_klatka = con.execute("SELECT id FROM frame WHERE sha1_data = 'RC80'").fetchone()[0]
    dopisane = []
    for i, fid in enumerate((*obce, rc8_klatka)):
        etykieta = f"RC8 0.{i + 5}x"
        tid, _g = repo.user_assign_config_new_telescope(con, frame_ids=[fid], name=etykieta, focal_mm=800.0 + i,
                                                         in_park=1, source_telescope_id=rc8, now=NOW)
        assert queries.slad_dopisania(con, tid) is not None, "gest bez śladu - test nie mierzy kolejki"
        dopisane.append((tid, etykieta))
    con.close()
    return str(tmp_path / "o.db"), dopisane


def test_aktywacja_podaje_wpis_za_zdjeta_podana_glowa_kolejki(qapp, tmp_path, monkeypatch):
    """Dwa „Cofnij dopisanie” odłożone w PRAWDZIWYM etapie Dostawy; koniec etapu podaje pierwszy (A), A zamknięty
    drugim połączeniem (jak drugie okno), powrót do okna - pasek mówi gotowość B z jego receptą, a w kolejce zostaje
    sam B. Falsyfikator: aktywacja, która zdejmuje martwą głowę i nie podaje wpisu za nią (B czeka na Porządki)."""
    a, [(tid_a, et_a), (tid_b, et_b)] = _baza_z_dopisanymi(tmp_path, ile=2)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        _odloz_dopisanie(win, tid_a, et_a)
        _odloz_dopisanie(win, tid_b, et_b)
        _etap_koniec(win, puszczona)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=et_a)
        _cofnij_dopisanie_obok(a, tid_a)
        _aktywuj(win)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=et_b)
        stan = win._recepta_porzadkow_stan
        assert stan is not None and stan[0].czlony[0].tekst == i18n.t("object.config_undo_add", telescope=et_b)
        assert [w.klucz for w in win._kolejki_osi[queries.klucz_bazy(a)]] == [("dopisanie", tid_b)]
    finally:
        puszczona.set()
        win.close()


def test_aktywacja_po_zdjeciu_wpisu_niepodanego_niczego_nie_podaje(qapp, tmp_path, monkeypatch):
    """Trzy wpisy odłożone w prawdziwym etapie; koniec etapu podaje pierwszy (A), cudzy raport gasi jego receptę bez
    kliku; drugi (X, NIGDY niepodany) zamknięty drugim połączeniem. Powrót do okna zdejmuje X po cichu i niczego nie
    podaje - cudzy raport stoi, trzeci wpis czeka na swoją chwilę (wejście w Porządki). Falsyfikator: podanie po
    zdjęciu dowolnego wpisu (aktywacja staje się chwilą podania)."""
    a, [(tid_a, et_a), (tid_x, et_x), (tid_b, et_b)] = _baza_z_trzema_dopisanymi(tmp_path)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        for tid, et in ((tid_a, et_a), (tid_x, et_x), (tid_b, et_b)):
            _odloz_dopisanie(win, tid, et)
        _etap_koniec(win, puszczona)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=et_a)
        win._flash("cudzy raport", ms=0)                 # bez wygasania - asercja niżej czyta pasek
        _cofnij_dopisanie_obok(a, tid_x)
        _aktywuj(win)
        assert str(win._pelny_komunikat) == "cudzy raport"
        assert {w.klucz[1]: w.podany for w in win._kolejki_osi[queries.klucz_bazy(a)]} == {tid_a: True, tid_b: False}
    finally:
        puszczona.set()
        win.close()


def test_aktywacja_przy_gotowosci_przykrytej_raportem_niczego_nie_podaje(qapp, tmp_path, monkeypatch):
    """Dwa wpisy odłożone w prawdziwym etapie, koniec etapu podaje pierwszy (A); raport Zbiorów ze szczegółem (związany
    ze stroną Zbiorów) przykrywa gotowość A, a A zamknięty drugim połączeniem. Powrót do okna zdejmuje A po cichu:
    raport stoi bez zmian, drugi wpis czeka niepodany na swoją chwilę. Falsyfikator: aktywacja podająca następny wpis
    po samym zdjęciu wpisu kiedyś podanego (gotowość doklejona do cudzego raportu stałaby potem na każdej stronie)."""
    a, [(tid_a, et_a), (tid_b, et_b)] = _baza_z_dopisanymi(tmp_path, ile=2)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        _odloz_dopisanie(win, tid_a, et_a)
        _odloz_dopisanie(win, tid_b, et_b)
        _etap_koniec(win, puszczona)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.ready", telescope=et_a)
        raport = ZdanieZeSzczegolem("Zapis Zbiorów przerwany", "X:\\L\\a.fits: odmowa dostępu")
        win._flash(raport, miejsce=STRONA_ZBIORY)
        _cofnij_dopisanie_obok(a, tid_a)
        _aktywuj(win)
        assert win._pelny_komunikat is raport, str(win._pelny_komunikat)
        assert {w.klucz[1]: w.podany for w in win._kolejki_osi[queries.klucz_bazy(a)]} == {tid_b: False}
    finally:
        puszczona.set()
        win.close()


def test_aktywacja_po_zdjeciu_gotowosci_doklejonej_wraca_zdanie_i_podaje_nastepny(qapp, tmp_path, monkeypatch):
    """Trzy wpisy odłożone w prawdziwym etapie; koniec etapu podaje pierwszy (A), człowiek cofa A przyciskiem Osi
    teleskopu - pasek mówi wynik gestu z doklejoną gotowością drugiego (B). B zamknięty drugim połączeniem; powrót do
    okna przywraca wynik gestu A i dokleja do niego gotowość trzeciego wpisu (C) z jego receptą. Falsyfikator: aktywacja
    podająca następny wpis bez zdania, które zdjęcie przywróciło (wynik gestu człowieka znika pod gotowością)."""
    a, [(tid_a, et_a), (tid_b, et_b), (tid_c, et_c)] = _baza_z_trzema_dopisanymi(tmp_path)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        for tid, et in ((tid_a, et_a), (tid_b, et_b), (tid_c, et_c)):
            _odloz_dopisanie(win, tid, et)
        _etap_koniec(win, puszczona)
        _klik_nav(win, NAV_PORZADKI)
        av = _wiersz_osi_teleskopu(win, tid_a)
        QTest.mouseClick(av.btn_undo_add, Qt.LeftButton)
        assert _wycofany(win, tid_a)
        ogon_b = " - " + i18n.t("object.config_undo_add.ready", telescope=et_b)
        pasek = str(win._pelny_komunikat)
        assert pasek.endswith(ogon_b) and et_a in pasek.removesuffix(ogon_b), pasek
        wynik_a = pasek.removesuffix(ogon_b)
        _cofnij_dopisanie_obok(a, tid_b)
        _aktywuj(win)
        assert str(win._pelny_komunikat) == str(zlacz_zdania(
            " - ", (wynik_a, i18n.t("object.config_undo_add.ready", telescope=et_c))))
        stan = win._recepta_porzadkow_stan
        assert stan is not None and stan[0].czlony[0].tekst == i18n.t("object.config_undo_add", telescope=et_c)
    finally:
        puszczona.set()
        win.close()


def test_zamkniecie_glowy_w_osi_teleskopu_podaje_wpis_za_nia(qapp, tmp_path, monkeypatch):
    """Dwa wpisy odłożone w prawdziwym etapie, A podany; człowiek cofa A przyciskiem Osi teleskopu (droga trwała tego
    okna) - pasek mówi wynik gestu, a za nim gotowość B z receptą B. Falsyfikator: zamknięcie gestu w oknie, które
    zdejmuje głowę i nie podaje wpisu za nią (B czeka na ponowne wejście w Porządki)."""
    a, [(tid_a, et_a), (tid_b, et_b)] = _baza_z_dopisanymi(tmp_path, ile=2)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        _odloz_dopisanie(win, tid_a, et_a)
        _odloz_dopisanie(win, tid_b, et_b)
        _etap_koniec(win, puszczona)
        _klik_nav(win, NAV_PORZADKI)
        av = _wiersz_osi_teleskopu(win, tid_a)
        assert av.btn_undo_add.isEnabled()
        QTest.mouseClick(av.btn_undo_add, Qt.LeftButton)
        assert _wycofany(win, tid_a)
        gotowosc_b = i18n.t("object.config_undo_add.ready", telescope=et_b)
        pasek = str(win._pelny_komunikat)
        assert pasek.endswith(" - " + gotowosc_b) and pasek != " - " + gotowosc_b, pasek   # wynik gestu A przed B
        assert et_a in pasek.removesuffix(" - " + gotowosc_b), pasek
        stan = win._recepta_porzadkow_stan
        assert stan is not None and stan[0].czlony[0].tekst == i18n.t("object.config_undo_add", telescope=et_b)
    finally:
        puszczona.set()
        win.close()


def test_zamkniecie_wpisu_niepodanego_w_osi_teleskopu_niczego_nie_podaje(qapp, tmp_path, monkeypatch):
    """Trzy wpisy odłożone w prawdziwym etapie, koniec etapu podaje pierwszy (A); człowiek cofa przyciskiem Osi
    teleskopu drugi wpis (X, nigdy niepodany). X schodzi z kolejki po cichu, pasek mówi sam wynik gestu, a trzeci wpis
    czeka niepodany na swoją chwilę. Falsyfikator: zamknięcie gestu w Osi teleskopu podające następny wpis po zdjęciu
    wpisu nigdy niepodanego (wynik `oczysc_martwe` „zdjęło cokolwiek”)."""
    a, [(tid_a, et_a), (tid_x, et_x), (tid_b, et_b)] = _baza_z_trzema_dopisanymi(tmp_path)
    puszczona = _brama_dostawy(monkeypatch)
    win = _pokazane(a, monkeypatch)
    try:
        _etap_start(win)
        for tid, et in ((tid_a, et_a), (tid_x, et_x), (tid_b, et_b)):
            _odloz_dopisanie(win, tid, et)
        _etap_koniec(win, puszczona)
        _klik_nav(win, NAV_PORZADKI)
        av = _wiersz_osi_teleskopu(win, tid_x)
        QTest.mouseClick(av.btn_undo_add, Qt.LeftButton)
        assert _wycofany(win, tid_x)
        pasek = str(win._pelny_komunikat)
        assert et_x in pasek and i18n.t("object.config_undo_add.ready", telescope=et_b) not in pasek, pasek
        assert {w.klucz[1]: w.podany for w in win._kolejki_osi[queries.klucz_bazy(a)]} == {tid_a: True, tid_b: False}
    finally:
        puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-355: tożsamość zamiaru w recepcie

def test_klik_recepty_kart_z_innym_przebiegiem_commitu_odmawia_bez_zapisu(qapp, tmp_path):
    """Recepta „Cofnij zapis (commit N)” po zamknięciu okna naprawy niesie przebieg zapisu commitu; w bazie pod oknem
    commit N dostaje inny przebieg (drugie połączenie - zamiar innej biblioteki). Klik recepty: zdanie odmowy, recepta
    schodzi z paska, uchwyt zapisu nie powstaje, pliki bajt w bajt. Zmiana przebiegu wprost w bazie, bo drogi gestem
    nie ma: produkt wiersz `commits` tylko wstawia (przebieg zapisu to uuid4 klingi), więc commit N z innym przebiegiem
    pod tą samą ścieżką daje wyłącznie inna biblioteka - to, co tu podstawia drugie połączenie. Falsyfikator: wykonawca
    bez sprawdzenia tożsamości (cofnięcie cudzego commitu - zapis do plików)."""
    win, path, pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        przed = _bajty(pliki)
        con2 = sqlite3.connect(str(path))
        try:
            with con2:
                con2.execute("UPDATE commits SET run_id = 'przebieg-innej-biblioteki' WHERE id = ?", (commit,))
        finally:
            con2.close()
        _klik_recepty(win)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_stale", id=commit)
        assert ov._wb_kart is None and not ov._zapis_kart_trwa
        assert _bajty(pliki) == przed
        assert win._recepta_porzadkow_stan is None and not win.recipe_label.isVisible()
    finally:
        win.close()


def _baza_kubelka_ogniskowej(tmp_path):
    """Baza osi (`test_gui_optyka_teleskopu._baza`) BEZ gestu: kubełek ogniskowej z dwiema obcymi klatkami RC8 800 mm
    czeka na „Dopisz nowy…”. Ścieżka, klatki kubełka i teleskop źródłowy; połączenie zamknięte - okno otwiera własne."""
    con, obce, rc8 = _baza_osi(tmp_path)
    con.close()
    return str(tmp_path / "o.db"), obce, rc8


def _dopisz_nowy_w_oknie(win, monkeypatch, etykieta, rc8):
    """Prawdziwy gest „Dopisz nowy…” w Porządkach: kubełek ogniskowej zaznaczony, klik „Przypisz zestaw…”; okno
    modalne podstawione (oddaje nowy teleskop `etykieta` i klatki kubełka - jak wypełnione przez człowieka). Klinga
    zakłada teleskop, a recepta „Cofnij dopisanie” staje na pasku gospodarza. Zwraca teleskop."""
    import horreum.gui.app as app_mod

    class _OknoZestawu:
        def __init__(self, con, *, groups, change=False, focal=False, parent=None):
            assert focal and not change, "gest nie z kubełka ogniskowej"
            self.new_telescope = {"name": etykieta, "focal_mm": 800.0, "f_ratio": None, "in_park": 1,
                                  "source_telescope_id": rc8}
            self.selected = (None, etykieta, [fid for g in groups for fid in g["frame_ids"]])

        def exec(self):
            return QDialog.Accepted
    monkeypatch.setattr(app_mod, "AssignConfigDialog", _OknoZestawu)
    _klik_wiersza_porzadkow(win, "focal_mismatch_frames")
    ov = win.object_view
    assert ov._selected_review()[0] == "config_focal" and ov.set_config_btn.isEnabled(), ov._selected_review()
    QTest.mouseClick(ov.set_config_btn, Qt.LeftButton)
    stan = win._recepta_porzadkow_stan
    assert stan is not None and stan[0].czlony[0].tekst == i18n.t("object.config_undo_add", telescope=etykieta)
    assert win.recipe_label.isVisible(), "recepta gestu nie stoi na pasku"
    return win.con.execute("SELECT id FROM telescope WHERE telescop_canon = ?", (etykieta,)).fetchone()[0]


def _cofnij_dopisanie_teraz(sciezka, tid, now):
    """„Cofnij dopisanie” drugim połączeniem (drugie okno) zegarem chwili po geście okna; cofnięcie musi wejść."""
    con = db.open_db(sciezka)
    try:
        assert repo.undo_new_telescope(con, telescope_id=tid, now=now).restored, "cofnięcie obok nie weszło"
    finally:
        con.close()


def test_klik_recepty_dopisania_po_dopisaniu_od_nowa_odmawia_bez_zapisu(qapp, tmp_path, monkeypatch):
    """Recepta „Cofnij dopisanie” z prawdziwego gestu „Dopisz nowy…” niesie ślad gestu. Drugie okno (drugie
    połączenie) cofa to dopisanie i dopisuje teleskop tej samej nazwy od nowa - nagrobek wskrzesza TEN SAM teleskop
    z nowym śladem. Klik recepty: zdanie odmowy z rodziny klingi (dopisano od nowa - nowe cofniesz w Osi teleskopu),
    nowe dopisanie i jego ślad zostają, recepta schodzi. Falsyfikator: wykonawca bez sprawdzenia tożsamości (recepta
    cofa nowe dopisanie, którego nie dotyczy)."""
    a, obce, rc8 = _baza_kubelka_ogniskowej(tmp_path)
    win = _pokazane(a, monkeypatch)
    et = "RC8 0.5x"
    try:
        tid = _dopisz_nowy_w_oknie(win, monkeypatch, et, rc8)
        _cofnij_dopisanie_teraz(a, tid, win._now())
        con2 = db.open_db(a)
        try:
            tid2, _g = repo.user_assign_config_new_telescope(con2, frame_ids=obce, name=et, focal_mm=800.0, in_park=1,
                                                             source_telescope_id=rc8, now=win._now())
        finally:
            con2.close()
        assert tid2 == tid, "dopisanie od nowa założyło inny teleskop - test nie mierzy wskrzeszenia"
        nowy_slad = queries.slad_dopisania(win.con, tid)
        assert nowy_slad is not None
        _klik_recepty(win)
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.refused", telescope=et,
                                                    reason=i18n.t("object.config_undo_add.refused.re_added"))
        assert not _wycofany(win, tid) and queries.slad_dopisania(win.con, tid) == nowy_slad
        assert win._recepta_porzadkow_stan is None and not win.recipe_label.isVisible()
    finally:
        win.close()


@pytest.mark.parametrize("gest", ["karty", "dopisanie"])
def test_klik_recepty_po_zamknieciu_gestu_poza_oknem_mowi_rdzen(qapp, tmp_path, monkeypatch, gest):
    """Recepta stoi na pasku, a jej gest zamknięto poza oknem (commit cofnięty rdzeniem na drugim połączeniu - jak
    `header-fix --undo`; dopisanie z prawdziwego gestu „Dopisz nowy…” cofnięte drugim połączeniem). Tożsamość zamiaru
    się nie zmieniła, więc klik idzie do rdzenia i pierwsze zdanie wyniku to jego zdanie (karty - pasek; dopisanie -
    kanał widoku osi) - nie odmowa recepty. Falsyfikatory: straż przez żywotność zamiaru (`_zywy`) zamiast tożsamości;
    dopisanie bez otwartego śladu uznane za cudze."""
    if gest == "karty":
        win, path, _pliki = _okno_naprawy(tmp_path)
        ov = win.object_view
        try:
            commit = _naprawa_prawdziwym_exec(win)
            con2 = db.open_db(str(path))
            try:
                assert writeback.undo(con2, commit, now=NOW).complete
            finally:
                con2.close()
            _klik_recepty(win)
            assert ov._wb_kart is not None, "klik nie doszedł do rdzenia"
            _czekaj_na_cofniecie(win)
            assert str(win._pelny_komunikat) != i18n.t("wb.undo_recipe_stale", id=commit)
        finally:
            win.close()
        return
    a, _obce, rc8 = _baza_kubelka_ogniskowej(tmp_path)
    et = "RC8 0.5x"
    wolania = []
    prawdziwe = repo.undo_new_telescope
    monkeypatch.setattr(repo, "undo_new_telescope", lambda con, **k: (wolania.append(k["telescope_id"]),
                                                                       prawdziwe(con, **k))[1])
    win = _pokazane(a, monkeypatch)
    try:
        tid = _dopisz_nowy_w_oknie(win, monkeypatch, et, rc8)
        _cofnij_dopisanie_teraz(a, tid, win._now())
        wolania.clear()                                  # drugie połączenie też woła rdzeń
        ov = win.object_view
        zdania = []
        ov.status_message.connect(lambda z: zdania.append(str(z)))
        ov.wynik_cofniecia.connect(lambda z, _r: zdania.append(str(z)))
        _klik_recepty(win)
        assert wolania == [tid], "klik nie doszedł do rdzenia"
        # Kanał widoku osi, nie pasek: scena osi nie ma obiektów, a odświeżenie po geście mówi wtedy pustą bibliotekę
        # (`object.empty_status`) - zdanie wyniku pada przed nim.
        powod = i18n.t("object.config_undo_add.refused.re_added")
        assert zdania[0] == i18n.t("object.config_undo_add.refused", telescope=et,
                                   reason=i18n.t("object.config_undo_add.refused.undone")), zdania
        assert not any(powod in z for z in zdania), zdania
    finally:
        win.close()
