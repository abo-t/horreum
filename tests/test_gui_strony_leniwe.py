"""Strony leniwe okna głównego (AR-325, offscreen): Zbiory (grid + Znajdź), Dostawa (pipeline + raport „Co
przyszło”) i Planer powstają przy pierwszym wejściu albo pierwszym dostępie do atrybutu, Dom i Porządki w montażu.

Zmierzone natywnie przed zmianą na kopii pf4: `open_path` 617-767 ms jednego przestoju pętli zdarzeń (5/5 biegów);
dolna granica bez tych trzech stron 155-194 ms - o przestoju decydowała strona Zbiorów, której wątki tła startowały
w montażu. Kontrakt (K1): atrybut widoku strony leniwej buduje ją przy pierwszym dostępie; `zbuduj_strony()` buduje
wszystkie; kod gospodarza, który nie ma budować (powiadomienia stanu), czyta `_gotowy`. Wiązania: KOMENDY człowieka
budują adresata przed wykonaniem, POWIADOMIENIA dochodzą wyłącznie do stron zbudowanych, a zatrzaski stanu (bieg
Dostawy, zapis do plików z paska osi i ze Zbiorów) strona przykłada przy budowie. Każdy test nazywa falsyfikator.

Zmierzone natywnie po zmianie: pierwsze wejście w niezbudowane Zbiory 290-326 ms - strona Zbiorów dobudowuje się więc
w bezczynności zaraz po otwarciu bazy w pokazanym oknie (`MainWindow._zbiory_w_bezczynnosci`). Testy dróg „strona
niezbudowana” biegną bez dobudowy (autouse), testy dobudowy włączają ją jawnie (`_z_dobudowa`).

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import ast
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum.gui import app as app_mod, queries
from horreum.gui.app import (NAV_DOM, NAV_DOSTAWA, NAV_PLANER, NAV_PORZADKI, NAV_ZBIORY,
                             STRONA_DOM, STRONA_DOSTAWA, STRONA_PLANER, STRONA_PORZADKI, STRONA_ZBIORY,
                             MainWindow)

from fixture_s8 import build
from test_gui_grid_recepty import (_brama_dostawy, _etap_koniec, _etap_start, _klik_recepty,  # noqa: F401
                                   _naprawa_prawdziwym_exec, _okno_naprawy, brama)
from test_gui_pasek_szczegol import _czekaj

_LENIWE = {STRONA_ZBIORY: ("grid_view", "znajdz_view"), STRONA_DOSTAWA: ("pipeline_view", "przyjmij_view"),
           STRONA_PLANER: ("planner_view",)}


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_watkow(monkeypatch):
    """Tryb przewidywalny (bez wątków tła Zbiorów) - test, który mierzy wątki, przełącza go jawnie. Bez dobudowy
    Zbiorów w bezczynności: okno pokazane (`_okno`) zbudowałoby je w pierwszym `processEvents`, a testy komend,
    zatrzasków i porażki budowy mierzą drogę do strony NIEZBUDOWANEJ (klik albo komenda przed dobudową, okno
    niepokazane) - z dobudową kilka z nich nie miałoby czego mierzyć. Testy dobudowy włączają ją jawnie."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)


def _z_dobudowa(monkeypatch):
    """Dobudowa Zbiorów w bezczynności włączona - tryb produktu (autouse pliku ją wyłącza)."""
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", True)


def _pokazane_bez_obrotu(sciezka):
    """Okno z bazą pokazane i kotwice dobudowy stoją (liczniki montażu synchroniczne, kotwica malowania doręczona
    wprost), ale pętla zdarzeń nie obróciła się - zegar dobudowy czeka."""
    win = MainWindow(sciezka)
    win.resize(1500, 900)
    win.show()
    QCoreApplication.sendPostedEvents(win._po_malowaniu, app_mod._PoMalowaniu.TYP)
    assert win._dobudowa_zbiorow.isActive()
    return win


def _obroty(warunek, n=20):
    """Obroty pętli zdarzeń, aż `warunek()` (najwyżej `n`) - kotwica malowania, potem zegar dobudowy."""
    for _ in range(n):
        if warunek():
            return
        QApplication.processEvents()
    assert warunek()


def _licz_gridy(monkeypatch):
    """Połączenie każdego `FramesView` zbudowanego w teście (konstruktor, nie slot), w kolejności budowy."""
    from horreum.gui.grid import FramesView
    gridy = []
    prawdziwy = FramesView.__init__

    def _init(self, con, *a, **k):
        gridy.append(con)
        prawdziwy(self, con, *a, **k)
    monkeypatch.setattr(FramesView, "__init__", _init)
    return gridy


def _baza(tmp_path, nazwa="s8.db"):
    sciezka = str(tmp_path / nazwa)
    build(sciezka, object_axis=True)
    return sciezka


def _okno(sciezka):
    win = MainWindow(sciezka)
    win.resize(1500, 900)
    win.show()
    QApplication.processEvents()
    return win


def _zbudowane(win):
    """Strony leniwe zbudowane - ze słownika stron, nie z property (odczyt property buduje)."""
    return {s for s, nazwy in _LENIWE.items() if all(win._strony.get(n) is not None for n in nazwy)}


def _klik_nav(win, row):
    rect = win.nav.visualItemRect(win.nav.item(row))
    QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QApplication.processEvents()


def test_open_path_buduje_dom_i_porzadki_a_reszta_czeka(qapp, tmp_path):
    """Po `open_path` stoją Dom i Porządki, a na indeksach Zbiorów, Dostawy i Planera - zaślepki; stos ma pięć
    stron w kolejności `STRONA_*`. Falsyfikator: montaż buduje wszystkie strony (`_strony_leniwie` ignorowane)."""
    win = MainWindow(_baza(tmp_path))
    try:
        assert _zbudowane(win) == set()
        assert win.stack.count() == 5
        assert win.stack.widget(STRONA_DOM) is win.home_view
        assert win.stack.widget(STRONA_PORZADKI) is win.tasks_view
        for strona in _LENIWE:
            assert win.stack.widget(strona) is win._zaslepki[strona]
    finally:
        win.close()


def test_pierwsze_wejscie_nie_pokazuje_zaslepki(qapp, tmp_path):
    """Pierwsze wejście w stronę leniwą (klik myszą w wiersz sidebara, potem strzałki) buduje ją PRZED pokazaniem -
    przy KAŻDEJ zmianie strony stosu bieżący widżet nie jest zaślepką; drugie wejście nie buduje drugi raz.
    Falsyfikator: budowa po `stack.setCurrentIndex` (emisja `currentChanged` z zaślepką na ekranie)."""
    win = _okno(_baza(tmp_path))
    zaslepki = set(map(id, win._zaslepki.values()))
    na_ekranie = []
    win.stack.currentChanged.connect(lambda _i: na_ekranie.append(id(win.stack.currentWidget())))
    try:
        for row in (NAV_DOSTAWA, NAV_ZBIORY, NAV_PLANER):
            _klik_nav(win, row)
        assert _zbudowane(win) == set(_LENIWE)
        grid = win._strony["grid_view"]
        win.nav.setFocus(Qt.OtherFocusReason)
        for klawisz in (Qt.Key_Up, Qt.Key_Up, Qt.Key_Down, Qt.Key_Down):
            QTest.keyClick(win.nav, klawisz)
            QApplication.processEvents()
        assert na_ekranie and not zaslepki.intersection(na_ekranie), "zaślepka stanęła na ekranie"
        assert win._strony["grid_view"] is grid, "drugie wejście zbudowało stronę od nowa"
    finally:
        win.close()


def test_dostep_do_atrybutu_buduje_strone_a_zbuduj_strony_jest_idempotentne(qapp, tmp_path):
    """Kontrakt K1: odczyt `win.grid_view` po `open_path` zwraca grid (strona zbudowana, zaślepka zdjęta), bez bazy -
    `None`; `zbuduj_strony()` buduje resztę i drugie wołanie nic nie zmienia. Falsyfikator: property bez budowy."""
    assert MainWindow().grid_view is None
    win = MainWindow(_baza(tmp_path))
    try:
        grid = win.grid_view
        assert grid is not None and _zbudowane(win) == {STRONA_ZBIORY}
        assert win.stack.widget(STRONA_ZBIORY) is win._strony["znajdz_view"]
        win.zbuduj_strony()
        widoki = dict(win._strony)
        win.zbuduj_strony()
        assert _zbudowane(win) == set(_LENIWE) and win._strony == widoki and win._zaslepki == {}
    finally:
        win.close()


# Metody gospodarza, którym WOLNO budować stronę leniwą odczytem jej atrybutu - KOMENDY człowieka i nawigacja.
_KOMENDY = {"show_find", "_on_nav_changed", "_on_nav_wejscie", "_on_open_collection", "_on_show_target_frames",
            "show_frames_in_collections", "_on_teczka_domu", "_on_wiecej_domu", "_on_przyjmij", "_on_open_harvest",
            "_resolve_after_repair", "_etap_po_gescie_rodowodu", "_on_przebieg_zmiany_obiektu", "_on_open_intake",
            "_on_wydaj_domu"}


def test_predykat_konsumentow_stron_leniwych():
    """Bramka AST: w `MainWindow` odczyt atrybutu widoku strony leniwej (`self.grid_view` …) stoi wyłącznie
    w metodzie-komendzie (`_KOMENDY`), a `getattr(self, "<widok>")` nigdzie - powiadomienie stanu z odczytem property
    po cichu zbudowałoby stronę (zysk otwarcia znika). Falsyfikator: nowa metoda gospodarza z `self.grid_view`."""
    zrodlo = open(app_mod.__file__, encoding="utf-8").read()
    klasa = next(n for n in ast.parse(zrodlo).body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    nazwy = {n for nazwy in _LENIWE.values() for n in nazwy}
    zle, getattry, komendy = [], [], set()
    for f in klasa.body:
        if not isinstance(f, ast.FunctionDef):
            continue
        for w in ast.walk(f):
            if (isinstance(w, ast.Attribute) and w.attr in nazwy and isinstance(w.value, ast.Name)
                    and w.value.id == "self"):
                (komendy.add(f.name) if f.name in _KOMENDY else zle.append(f"{f.name}:{w.lineno}"))
            if (isinstance(w, ast.Call) and getattr(w.func, "id", None) == "getattr" and len(w.args) >= 2
                    and isinstance(w.args[1], ast.Constant) and w.args[1].value in nazwy):
                getattry.append(f"{f.name}:{w.lineno}")
    assert not zle, f"odczyt strony leniwej poza komendą: {zle}"
    assert not getattry, getattry
    assert len(komendy) >= 12, komendy          # podłoga: predykat, który oślepł, nie przechodzi po cichu


@pytest.mark.parametrize("dobudowa", [False, True], ids=["bez_dobudowy", "z_dobudowa"])
def test_przebieg_dostawy_nie_buduje_niewidzianych_stron(qapp, tmp_path, monkeypatch, dobudowa):
    """Prawdziwy etap Dostawy przy niezbudowanym Planerze (i Zbiorach - bez dobudowy w bezczynności): koniec
    przebiegu (`running_changed(False)` → odświeżenie widoków, panel rodowodu) ich nie buduje i nie rzuca. Z dobudową
    Zbiory stoją już przed przebiegiem (bezczynność po otwarciu), przebieg zostawia ten sam grid, a Planer dalej czeka.
    Falsyfikator: `_odswiez_widoki_po_przebiegu` albo `_on_pipeline_running` przez property zamiast `_gotowy`."""
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", dobudowa)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        if dobudowa:
            _obroty(lambda: STRONA_ZBIORY in _zbudowane(win))
        przed = _zbudowane(win)
        assert przed == ({STRONA_ZBIORY} if dobudowa else set())
        grid = win._strony.get("grid_view")
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        _etap_koniec(win, puszczona)
        assert _zbudowane(win) == przed | {STRONA_DOSTAWA}
        assert win._strony.get("grid_view") is grid
    finally:
        puszczona.set()
        win.close()


def test_zniwa_i_przebieg_przy_niezbudowanych_zbiorach(qapp, tmp_path, monkeypatch):
    """Ogon żniw (`_zapisz_rodowod_po_przebiegu`, panel rodowodu po przebiegu) przy niezbudowanych Zbiorach -
    koniec przebiegu odświeża zbudowane widoki, Zbiorów nie buduje. Falsyfikator: `refresh_lineage_panel` przez
    property `grid_view`."""
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_DOSTAWA)
        widok = win._strony["pipeline_view"]
        win._zapisz_rodowod_po_przebiegu([], "")
        zapis = dict(widok.last_run, failed=None, cancelled=False, refused=None)
        widok.run_finished.emit(zapis)
        QApplication.processEvents()
        assert STRONA_ZBIORY not in _zbudowane(win)
    finally:
        win.close()


# ---------------------------------------------------------------- KOMENDY budują adresata

def test_klik_przerwanej_zmiany_obiektu_buduje_zbiory_i_otwiera_okno(qapp, tmp_path, monkeypatch):
    """Klik w wiersz „Przerwane zmiany obiektu” Porządków (prawdziwy `mouseClick`) przy niezbudowanych Zbiorach -
    strona Zbiorów powstaje i dostaje komendę otwarcia okna przebiegu. Falsyfikator: komenda przez `_gotowy`
    (okno się nie otwiera) albo podpięcie do gridu sprzed budowy."""
    from horreum.gui.grid import FramesView
    otwarte = []
    monkeypatch.setattr(queries, "interrupted_object_change_runs", lambda con: ["przebieg-1"])
    monkeypatch.setattr(FramesView, "otworz_przebieg_zmiany_obiektu",
                        lambda self, run_id: otwarte.append((self, run_id)))
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_PORZADKI)
        win.tasks_view.refresh_counts()
        lista = win.tasks_view.tasks
        it = next(lista.item(i) for i in range(lista.count())
                  if lista.item(i).data(Qt.UserRole) == "object_change_interrupted")
        QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, lista.visualItemRect(it).center())
        QApplication.processEvents()
        assert otwarte == [(win._strony["grid_view"], "przebieg-1")]
    finally:
        win.close()


def test_klik_wiersza_faktow_kopii_buduje_dostawe_z_powodem(qapp, tmp_path):
    """Komenda „?” Porządków (`open_intake`) przy niezbudowanej Dostawie - strona powstaje, linia powodu stoi,
    Dostawa na ekranie. Falsyfikator: komenda przez `_gotowy`; pokazanie strony przed `show_reason`."""
    from test_gui_pipeline import _kopie_bez_faktow
    sciezka, _kat = _kopie_bez_faktow(tmp_path)
    win = _okno(sciezka)
    try:
        assert STRONA_DOSTAWA not in _zbudowane(win)
        powody = []
        win.stack.currentChanged.connect(
            lambda _i: powody.append(win._strony["pipeline_view"]._reason
                                     if "pipeline_view" in win._strony else "brak"))
        win.tasks_view.open_intake.emit()
        QApplication.processEvents()
        pipeline = win._strony["pipeline_view"]
        assert win.stack.currentIndex() == STRONA_DOSTAWA and pipeline.lbl_reason.isVisible()
        assert powody and powody[-1] == "copy_facts", "strona pokazana, zanim stanął powód"
    finally:
        win.close()


def test_kafel_wydaj_domu_buduje_zbiory_i_otwiera_wydanie(qapp, tmp_path, monkeypatch):
    """Klik kafla „Wydaj” Domu (prawdziwy `mouseClick`) przy niezbudowanych Zbiorach - strona powstaje i otwiera
    okno wydania obiektu; strona na ekranie zostaje Domem. Falsyfikator: komenda przez `_gotowy`."""
    from horreum.gui.grid import FramesView
    otwarte = []
    monkeypatch.setattr(FramesView, "_open_object_release", lambda self: otwarte.append(self))
    win = _okno(_baza(tmp_path))
    try:
        kafel = win.home_view.tile_wydaj
        assert kafel.isEnabled()
        QTest.mouseClick(kafel, Qt.LeftButton)
        QApplication.processEvents()
        assert otwarte == [win._strony["grid_view"]] and win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()


def test_naprawa_naglowka_uruchamia_etap_przy_niezbudowanej_dostawie(qapp, tmp_path, monkeypatch):
    """Takt 3 z okna „Napraw nagłówek…” (`object_view.run_stage_fn`) przy niezbudowanej Dostawie - strona powstaje,
    etap „Rozwiąż” rusza. Falsyfikator: `_resolve_after_repair` przez `_gotowy`."""
    from horreum.gui.pipeline import PipelineView
    etapy = []
    monkeypatch.setattr(PipelineView, "run_stage", lambda self, etap: etapy.append((self, etap)))
    win = _okno(_baza(tmp_path))
    try:
        assert win.object_view.run_stage_fn() is None
        assert etapy == [(win._strony["pipeline_view"], "resolve")]
    finally:
        win.close()


def test_trasy_przez_gospodarza_dochodza_do_strony_zbudowanej_pozniej(qapp, tmp_path, monkeypatch):
    """POWIADOMIENIE: gest „Przypisz obiekt…” z raportu Dostawy (`object_axis_changed`) przy niezbudowanych Zbiorach
    nie buduje ich i nie rzuca; po zbudowaniu Zbiorów ten sam sygnał przeładowuje grid z zaznaczeniem.
    Falsyfikator: bezpośrednie podpięcie w budowniczym Dostawy do `self.grid_view` (buduje Zbiory)."""
    from horreum.gui.grid import FramesView
    przeladowania = []
    prawdziwe = FramesView.przeladuj_z_zaznaczeniem
    monkeypatch.setattr(FramesView, "przeladuj_z_zaznaczeniem",
                        lambda self, *a, **k: (przeladowania.append(self), prawdziwe(self, *a, **k))[1])
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_DOSTAWA)
        przyjmij = win._strony["przyjmij_view"]
        przyjmij.object_axis_changed.emit()
        QApplication.processEvents()
        assert STRONA_ZBIORY not in _zbudowane(win) and przeladowania == []
        win._show_view(NAV_ZBIORY)
        przeladowania.clear()
        przyjmij.object_axis_changed.emit()
        QApplication.processEvents()
        assert przeladowania == [win._strony["grid_view"]]
    finally:
        win.close()


# ---------------------------------------------------------------- budowa failure-atomic

def test_wyjatek_w_budowie_zbiorow_zbiera_watek_i_pozwala_ponowic(qapp, tmp_path, monkeypatch):
    """Wyjątek w budowie strony Zbiorów PO starcie wątku składu zbioru (`FramesView.__init__`, tryb wątków tła):
    straż błędu dostaje wyjątek (podmieniony `sys.excepthook`), wątek gridu zebrany (`zatrzymaj_pola`), zaślepka
    zostaje na stosie, sidebar wraca na Dom, strona na ekranie się nie zmienia; po „zamknięciu okna błędu” drugi
    klik buduje Zbiory. Asercje bez odczytu property. Falsyfikatory: brak `zatrzymaj_pola` w obwódce porażki;
    wpis do słownika stron przed sukcesem; wiersz sidebara bez powrotu."""
    from horreum.gui.grid import FramesView
    from horreum.gui.flows import znajdz_view as znajdz_mod
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    zebrane, wyjatki = [], []
    prawdziwe_zbieranie = FramesView.zatrzymaj_pola

    def _zbierz(self):
        zebrane.append((self, self._zbior_thread is not None))
        return prawdziwe_zbieranie(self)
    monkeypatch.setattr(FramesView, "zatrzymaj_pola", _zbierz)

    class _Psuje(znajdz_mod.ZnajdzView):
        def __init__(self, *a, **k):
            raise RuntimeError("budowa strony Zbiorów padła")
    monkeypatch.setattr(app_mod, "ZnajdzView", _Psuje)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert len(wyjatki) == 1 and "budowa strony Zbiorów padła" in str(wyjatki[0])
        assert [mial for _g, mial in zebrane] == [True], "wątek składu gridu nie zebrany przed skasowaniem"
        assert zebrane[0][0]._zbior_thread is None
        assert "grid_view" not in win._strony and "znajdz_view" not in win._strony
        assert win.stack.widget(STRONA_ZBIORY) is win._zaslepki[STRONA_ZBIORY]
        assert win.stack.currentIndex() == STRONA_DOM and win.nav.currentRow() == NAV_DOM
        assert win._w_budowie == {}
        monkeypatch.setattr(app_mod, "ZnajdzView", znajdz_mod.ZnajdzView)   # „okno błędu zamknięte” - ponów
        _klik_nav(win, NAV_ZBIORY)
        assert STRONA_ZBIORY in _zbudowane(win) and win.stack.currentIndex() == STRONA_ZBIORY
        assert len(wyjatki) == 1
    finally:
        win.close()


def _porazka_raz(monkeypatch, strona):
    """Budowa strony `strona` pada RAZ (pierwsza próba), następna buduje normalnie - licznik prób w liście."""
    proby = []
    if strona == STRONA_ZBIORY:
        from horreum.gui.flows import znajdz_view as mod
        nazwa, cel = "ZnajdzView", app_mod
    else:
        from horreum.gui.flows import przyjmij as mod
        nazwa, cel = "PrzyjmijView", mod
    prawdziwa = getattr(mod, nazwa)

    class _RazPada(prawdziwa):
        def __init__(self, *a, **k):
            proby.append(1)
            if len(proby) == 1:
                raise RuntimeError("budowa strony padła raz")
            super().__init__(*a, **k)
    monkeypatch.setattr(cel, nazwa, _RazPada)
    return proby


@pytest.mark.parametrize("komenda", ["show_find", "show_classic", "przyjmij"])
def test_komenda_przy_porazce_budowy_strony_staje_po_jednym_oknie_bledu(qapp, tmp_path, monkeypatch, komenda):
    """Komenda gospodarza, która po nawigacji sięga po widok strony (Znajdź z Domu - `show_find`; perspektywa
    z Porządków - `show_classic`; kafel Przyjmij - `_on_przyjmij`), przy JEDNORAZOWEJ porażce budowy strony daje
    jedno zgłoszenie do straży i nic dalej: sidebar i stos zgodnie na Domu, zaślepka na miejscu, druga próba budowy
    nie zaszła w tym samym geście. Następna komenda buduje i wchodzi. Falsyfikator: komenda przełącza wiersz przed
    budową (porażka w `_on_nav_changed` nie przerywa komendy, następny krok buduje stronę drugi raz - sidebar
    „Znajdź”/„Zbiory” nad Domem albo strona zbudowana bez pokazania)."""
    from horreum.gui.grid import PRESET_DUPS
    from horreum.gui.pipeline import PipelineView
    strona = STRONA_DOSTAWA if komenda == "przyjmij" else STRONA_ZBIORY
    proby = _porazka_raz(monkeypatch, strona)
    monkeypatch.setattr(PipelineView, "receive", lambda self: "odmowa testu")   # bez okna wyboru katalogu
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    nadaj = {"show_find": win.home_view.znajdz.emit,
             "show_classic": lambda: win.tasks_view.open_collection.emit(PRESET_DUPS),
             "przyjmij": win.home_view.przyjmij.emit}[komenda]
    try:
        nadaj()
        QApplication.processEvents()
        assert len(wyjatki) == 1 and "budowa strony padła raz" in str(wyjatki[0]), wyjatki
        assert proby == [1], "druga budowa w tym samym geście"
        assert win.stack.currentIndex() == STRONA_DOM and win.nav.currentRow() == NAV_DOM
        assert win.stack.widget(strona) is win._zaslepki[strona]
        nadaj()
        QApplication.processEvents()
        assert len(wyjatki) == 1 and win.stack.currentIndex() == strona
    finally:
        win.close()


def test_klik_znajdz_przy_porazce_budowy_nie_buduje_drugi_raz(qapp, tmp_path, monkeypatch):
    """Klik w wiersz Znajdź (prawdziwy `mouseClick`: wejście w `_on_nav_changed`, potem `itemClicked` →
    `_on_nav_wejscie`) przy jednorazowej porażce budowy Zbiorów: jedno zgłoszenie, sidebar wraca na Dom, a obsługa
    kliku nie sięga po widok strony (druga budowa). Falsyfikator: `_on_nav_wejscie` bez sprawdzenia, że wejście się
    udało."""
    proby = _porazka_raz(monkeypatch, STRONA_ZBIORY)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, app_mod.NAV_ZNAJDZ)
        assert len(wyjatki) == 1 and proby == [1], (wyjatki, proby)
        assert win.stack.currentIndex() == STRONA_DOM and win.nav.currentRow() == NAV_DOM
        assert "znajdz_view" not in win._strony
    finally:
        win.close()


# ---------------------------------------------------------------- zatrzaski stanu

def test_zbiory_i_planer_budowane_w_biegu_dostawy_maja_blokade(qapp, tmp_path, monkeypatch):
    """Prawdziwy etap Dostawy w biegu (brama): pierwsze wejście w Zbiory i Planer buduje je z blokadą biegu
    (grid - akcje zapisu wygaszone, planer - nieczynny); koniec przebiegu zwalnia obie.
    Falsyfikator: budowniczy bez zatrzasku `_dostawa_w_biegu`."""
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        win._show_view(NAV_ZBIORY)
        win._show_view(NAV_PLANER)
        grid, planer = win._strony["grid_view"], win._strony["planner_view"]
        assert grid._etap_w_biegu and not planer.isEnabled()
        _etap_koniec(win, puszczona)
        assert not grid._etap_w_biegu and planer.isEnabled()
    finally:
        puszczona.set()
        win.close()


def test_zbiory_i_dostawa_budowane_w_biegu_zapisu_z_paska_osi(qapp, tmp_path, brama):
    """Cofnięcie zapisu kart z paska osi w biegu (prawdziwy uchwyt, brama po pierwszym pliku): pierwsze wejście
    w Zbiory i Dostawę buduje je z mutexem zapisu (szuflada gridu i Dostawa wygaszone); koniec zapisu zwalnia
    obie. Falsyfikatory: zatrzask ustawiany po rozesłaniu; budowniczy bez zatrzasku zapisu osi."""
    win, _path, _pliki = _okno_naprawy(tmp_path)
    try:
        _naprawa_prawdziwym_exec(win)
        for strona in (STRONA_ZBIORY, STRONA_DOSTAWA):
            assert strona not in _zbudowane(win)
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        win._show_view(NAV_ZBIORY)
        win._show_view(NAV_DOSTAWA)
        grid, pipeline = win._strony["grid_view"], win._strony["pipeline_view"]
        assert grid._foreign_wb and pipeline._writeback_busy
        brama.puszczona.set()
        _czekaj(lambda: not win.object_view._zapis_kart_trwa, "koniec cofnięcia")
        assert not grid._foreign_wb and not pipeline._writeback_busy
    finally:
        brama.puszczona.set()
        win.close()


def test_dostawa_budowana_w_biegu_zapisu_zbiorow_a_koniec_osi_jej_nie_zwalnia(qapp, tmp_path):
    """Zatrzask zapisu ma DWA źródła (oś, grid): zapis szuflady Zbiorów w toku (uchwyt gridu zgłasza zajętość) -
    Dostawa zbudowana teraz jest wygaszona; samo zakończenie zapisu z paska osi jej nie zwalnia, zwalnia ją koniec
    zapisu Zbiorów. Falsyfikator: jeden wspólny zatrzask zapisu zamiast źródeł."""
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_ZBIORY)
        grid = win._strony["grid_view"]
        grid._wb.busy_changed.emit(True)                 # uchwyt gridu: zapis szuflady trwa
        win._na_zapis_osi(True)
        win._na_zapis_osi(False)                         # koniec zapisu z paska osi - grid dalej pisze
        win._show_view(NAV_DOSTAWA)
        pipeline = win._strony["pipeline_view"]
        assert pipeline._writeback_busy, "Dostawa zbudowana w zapisie Zbiorów stoi czynna"
        grid._wb.busy_changed.emit(False)
        assert not pipeline._writeback_busy
    finally:
        win.close()


def test_przelaczenie_bazy_z_mieszanka_stron(qapp, tmp_path, monkeypatch):
    """Baza A z ZBUDOWANYMI Zbiorami (wątki tła) i niezbudowanym Planerem → baza B: wątki gridu zebrane, nowe
    zaślepki na wszystkich trzech indeksach, słownik stron i zatrzaski wyzerowane; Planer B buduje się przy
    wejściu. Falsyfikator: `_clear_views` bez zerowania stron (property oddałoby grid bazy A)."""
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    zebrane = []
    prawdziwe = FramesView.zatrzymaj_pola
    monkeypatch.setattr(FramesView, "zatrzymaj_pola", lambda self: (zebrane.append(self), prawdziwe(self))[1])
    win = _okno(_baza(tmp_path, "a.db"))
    try:
        win._show_view(NAV_ZBIORY)
        grid_a = win._strony["grid_view"]
        win._show_view(NAV_DOM)
        win.open_path(_baza(tmp_path, "b.db"))
        assert grid_a in zebrane
        assert _zbudowane(win) == set() and set(win._zaslepki) == set(_LENIWE)
        assert win._dostawa_w_biegu is False and not any(win._zapis_w_biegu.values())
        win._show_view(NAV_ZBIORY)
        grid_b = win._strony["grid_view"]
        assert grid_b is not grid_a and grid_b.con is win.con, "Zbiory bazy B to nie grid na połączeniu B"
        win._show_view(NAV_PLANER)
        assert STRONA_PLANER in _zbudowane(win)
    finally:
        win.close()


# ---------------------------------------------------------------- dobudowa Zbiorów w bezczynności

def test_dobudowa_buduje_zbiory_po_otwarciu_bez_wejscia(qapp, tmp_path, monkeypatch):
    """Strona Zbiorów powstaje w bezczynności po otwarciu bazy w POKAZANYM oknie, bez wejścia w nią: na ekranie dalej
    Dom, Dostawa i Planer czekają. Okno z bazą z konstruktora, jeszcze niepokazane, nie dobudowuje - zamawia dopiero
    pokazanie; baza otwarta w oknie już pokazanym (droga `main`) zamawia sama. Falsyfikatory: brak zamówienia po
    otwarciu; brak zamówienia przy pokazaniu; zamówienie bez warunku pokazanego okna."""
    _z_dobudowa(monkeypatch)
    win = MainWindow(_baza(tmp_path))
    try:
        for _ in range(5):
            QApplication.processEvents()
        assert _zbudowane(win) == set(), "dobudowa w oknie niepokazanym"
        win.resize(1500, 900)
        win.show()
        _obroty(lambda: _zbudowane(win) == {STRONA_ZBIORY})
        assert win.stack.currentIndex() == STRONA_DOM and win.nav.currentRow() == NAV_DOM
        win.open_path(_baza(tmp_path, "b.db"))
        assert _zbudowane(win) == set()
        _obroty(lambda: _zbudowane(win) == {STRONA_ZBIORY})
        assert win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()


def test_dobudowa_rusza_po_pierwszym_malowaniu_domu(qapp, tmp_path, monkeypatch):
    """Droga `main` (okno bez bazy pokazane i namalowane, potem `open_path`): pierwsze malowanie Domu otwartej bazy
    (zdarzenia `Paint` widżetów Domu) pada PRZED budową strony Zbiorów - dobudowa nie przesuwa pierwszej klatki bazy.
    Zmierzone natywnie z oknem na pulpicie: zegar 0 ms budował stronę przed malowaniem (Dom 628-1102 ms po
    `open_path`, bez dobudowy 25-33 ms). Falsyfikator: dobudowa bez kotwicy malowania (zegar od razu po otwarciu)."""
    from PySide6.QtCore import QEvent, QObject
    from horreum.gui.grid import FramesView
    _z_dobudowa(monkeypatch)
    zdarzenia = []
    prawdziwy = FramesView.__init__

    def _init(self, *a, **k):
        zdarzenia.append("budowa")
        prawdziwy(self, *a, **k)
    monkeypatch.setattr(FramesView, "__init__", _init)

    class _Malowanie(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Paint:
                zdarzenia.append("malowanie")
            return False
    filtr = _Malowanie()
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    try:
        for _ in range(3):
            QApplication.processEvents()
        win.open_path(_baza(tmp_path))
        for w in [win.home_view, *win.home_view.findChildren(QObject)]:
            if w.isWidgetType():
                w.installEventFilter(filtr)
        _obroty(lambda: "budowa" in zdarzenia)
        assert "malowanie" in zdarzenia and zdarzenia.index("malowanie") < zdarzenia.index("budowa"), zdarzenia[:5]
    finally:
        win.close()


def test_dobudowa_czeka_na_koniec_licznikow_montazu(qapp, tmp_path, monkeypatch):
    """Rachunek liczników Porządków montażu w tle (tryb wątków) zatrzymany bramą: Dom namalowany, a Zbiory się nie
    budują, dopóki seria liczników montażu się nie skończy; po końcu serii - dobudowa. Zmierzone A/B przeplatane na
    kopii pf4: dobudowa w trakcie serii odsuwała pierwszy wynik Porządków (2177-3835 ms wobec 1183-2362 ms).
    Falsyfikator: dobudowa bez kotwicy końca serii liczników montażu."""
    import threading
    from horreum.gui import tasks as tasks_mod
    _z_dobudowa(monkeypatch)
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    brama, glowny = threading.Event(), threading.get_ident()
    prawdziwy = tasks_mod._stan_licznikow

    def _stan(con):
        if threading.get_ident() != glowny:
            brama.wait(30)
        return prawdziwy(con)
    monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    try:
        QApplication.processEvents()
        win.open_path(_baza(tmp_path))
        _obroty(lambda: win._kotwica_malowania)
        for _ in range(10):
            QApplication.processEvents()
        assert STRONA_ZBIORY not in _zbudowane(win), "dobudowa w trakcie serii liczników montażu"
        brama.set()
        _czekaj(lambda: STRONA_ZBIORY in _zbudowane(win), "dobudowa po końcu serii liczników")
        assert win.stack.currentIndex() == STRONA_DOM
    finally:
        brama.set()
        win.close()


def test_klik_w_zbiory_przed_dobudowa_buduje_raz_bez_czekania(qapp, tmp_path, monkeypatch):
    """Klik w Zbiory, zanim zegar dobudowy ruszył (okno pokazane, pętla jeszcze się nie obróciła): strona powstaje na
    żądanie i od razu stoi na ekranie, bez czekania na zegar. Zegar schodzi, więc ani faza składu zbioru (pętla w
    `busy`), ani późniejsze obroty pętli nie budują jej drugi raz i nic nie rzuca. Falsyfikatory: budowa na żądanie
    bez zdjęcia zegara (zegar wchodzi w fazę składu - asercja reentrancji w haku); klik czekający na zegar."""
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    try:
        assert win._dobudowa_zbiorow.isActive() and _zbudowane(win) == set()
        rect = win.nav.visualItemRect(win.nav.item(NAV_ZBIORY))
        QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        assert wyjatki == [], wyjatki
        assert win._strony.get("znajdz_view") is not None, "klik czekał na zegar"
        assert win.stack.currentWidget() is win._strony["znajdz_view"]
        for _ in range(3):
            QApplication.processEvents()
        assert gridy == [win.con] and wyjatki == [], (gridy, wyjatki)
        assert not win._dobudowa_zbiorow.isActive()
    finally:
        win.close()


def test_zmiana_bazy_przed_dobudowa_nie_buduje_widoku_starej_bazy(qapp, tmp_path, monkeypatch):
    """Zmiana bazy, zanim zegar dobudowy bazy A ruszył: fazy otwarcia B kręcą pętlę (`busy.repaint`), ale zegar A
    schodzi na początku otwarcia - jedyny grid powstaje po otwarciu, na połączeniu B. Odmowa bazy (plik, który nie
    jest bazą) zostawia bazę C bieżącą i oddaje jej zegar. Falsyfikatory: zegar niezdjęty na początku otwarcia (grid
    na połączeniu A w fazie otwarcia B); odmowa bez powrotu zegara."""
    from PySide6.QtWidgets import QMessageBox
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    win = _pokazane_bez_obrotu(_baza(tmp_path, "a.db"))
    try:
        con_a = win.con
        assert win._dobudowa_zbiorow.isActive()
        win.open_path(_baza(tmp_path, "b.db"))
        assert gridy == [], "zegar bazy A zbudował Zbiory w fazie otwarcia B"
        _obroty(lambda: gridy)
        assert gridy == [win.con] and win.con is not con_a
        win.open_path(_baza(tmp_path, "c.db"))
        con_c = win.con
        nie_baza = tmp_path / "nie_baza.db"
        nie_baza.write_bytes(b"to nie jest baza SQLite " * 64)
        win.open_path(str(nie_baza))
        assert len(ostrzezenia) == 1 and win.con is con_c
        _obroty(lambda: len(gridy) > 1)
        assert gridy[1:] == [con_c] and STRONA_ZBIORY in _zbudowane(win)
    finally:
        win.close()


def test_demontaz_widokow_zdejmuje_zegar_dobudowy(qapp, tmp_path, monkeypatch):
    """Demontaż widoków (`_clear_views` - początek każdego montażu, wołany też wprost) zdejmuje zegar dobudowy: zegar
    mówi o stronie, której już nie ma. Falsyfikator: `_clear_views` bez zdjęcia zegara."""
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    try:
        assert win._dobudowa_zbiorow.isActive()
        win._clear_views()
        assert not win._dobudowa_zbiorow.isActive()
        QApplication.processEvents()
        assert gridy == []
    finally:
        win.close()


def test_zamkniecie_okna_przed_dobudowa_nie_buduje_niczego(qapp, tmp_path, monkeypatch):
    """Okno zamknięte, zanim zegar dobudowy ruszył: kolejne obroty pętli nie budują Zbiorów (połączenie już
    zamknięte) i nic nie rzuca - zaślepka zostaje. Falsyfikator: zamknięcie okna bez zdjęcia zegara."""
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    assert win._dobudowa_zbiorow.isActive()
    win.close()
    for _ in range(3):
        QApplication.processEvents()
    assert gridy == [] and wyjatki == [], (gridy, wyjatki)
    assert STRONA_ZBIORY in win._zaslepki and win.con is None


# ---------------------------------------------------------------- porażka konstruktora gridu (AR-333)

def _baza_z_przebiegiem(tmp_path):
    """Baza s8 z przebiegiem szuflady czekającym (`repo.stage_pending`) - budowa gridu bierze blokadę szuflady
    w `_podejmij_przebieg_poprzedni`, żeby podjąć przebieg."""
    from horreum import db, repo
    sciezka = _baza(tmp_path)
    con = db.connect(sciezka)
    lid, hh = con.execute("SELECT id, header_hash FROM location ORDER BY id LIMIT 1").fetchone()
    repo.stage_pending(con, run_id="R", location_id=lid, keyword="TELESCOP", idx=0, op="set", old_value="RC8",
                       new_value="EQ6", new_type="str", new_comment=None, expected_header_hash=hh)
    assert [p["run_id"] for p in queries.oczekujace_przebiegi_szuflady(con)] == ["R"]
    con.close()
    return sciezka


def _pada_w(monkeypatch, miejsce):
    """`FramesView.<miejsce>` rzuca (błąd programu w konstruktorze) i zapamiętuje pół-zbudowany widok.
    Zwraca `(pół-zbudowane widoki, prawdziwa metoda)`."""
    from horreum.gui.grid import FramesView
    polowy, prawdziwa = [], getattr(FramesView, miejsce)

    def _rzuca(self, *a, **k):
        polowy.append(self)
        raise RuntimeError("konstruktor gridu padł")
    monkeypatch.setattr(FramesView, miejsce, _rzuca)
    return polowy, prawdziwa


def _blokada_wolna(sciezka):
    from PySide6.QtCore import QLockFile
    swieza = QLockFile(sciezka + ".szuflada.lock")
    if not swieza.tryLock(0):
        return False
    swieza.unlock()
    return True


@pytest.mark.parametrize("miejsce", ["_przywroc_panel_rodowodu", "_odbuduj_perspektywy"])
def test_porazka_konstruktora_gridu_zbiera_watki_i_oddaje_blokade(qapp, tmp_path, monkeypatch, miejsce):
    """Błąd programu w `FramesView.__init__` PO starcie wątków tła - po wątku pól (`_odbuduj_perspektywy` w
    `_load_facets`) albo po obu wątkach i blokadzie szuflady (`_przywroc_panel_rodowodu`) - w trybie produktu,
    przy przebiegu szuflady czekającym, a wątki trzymane bramą w biegu. Klik w wiersz Znajdź: jedno zgłoszenie
    straży, pół-zbudowany widok ma oba wątki zebrane, a blokada szuflady jest wolna. Druga budowa w tym samym
    procesie (obiekt wyjątku żyje, jak w oknie błędu straży) podejmuje przebieg i nie mówi, że szufladę prowadzi
    inny proces Horreum. Falsyfikatory: konstruktor bez obwódki (wątki w biegu, blokada trzymana, zdanie
    o „innym procesie” z własnym PID-em); obwódka bez `zatrzymaj_pola`; obwódka połykająca wyjątek (zero
    zgłoszeń); obwódka zaczęta za `_load_facets` (wątek pól poza sprzątaniem)."""
    from horreum.gui import i18n
    from horreum.gui.grid import FramesView
    from test_gui_znajdz_szerokosci import _bramy_watkow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    sciezka = _baza_z_przebiegiem(tmp_path)
    bramy = _bramy_watkow(monkeypatch)
    polowy, prawdziwa = _pada_w(monkeypatch, miejsce)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(sciezka)
    try:
        _klik_nav(win, app_mod.NAV_ZNAJDZ)
        assert len(wyjatki) == 1 and "konstruktor gridu padł" in str(wyjatki[0]), wyjatki
        assert len(polowy) == 1
        assert polowy[0]._zbior_thread is None and polowy[0]._pola_thread is None, "wątek tła poza sprzątaniem"
        assert _blokada_wolna(sciezka), "blokada szuflady została przy pół-zbudowanym widoku"
        assert win.stack.currentIndex() == STRONA_DOM and "grid_view" not in win._strony
        monkeypatch.setattr(FramesView, miejsce, prawdziwa)       # „okno błędu zamknięte” - ponów
        bramy["zbior"].set()
        bramy["pola"].set()
        _klik_nav(win, app_mod.NAV_ZNAJDZ)
        drugi = win._strony["grid_view"]
        assert drugi._run_id == "R"
        assert drugi.drawer.label.text() == i18n.t_plural("grid.drawer.pending_prev", 1)
        assert drugi.drawer.result.text() != i18n.t("grid.drawer.foreign_owner", pid=os.getpid())
    finally:
        bramy["zbior"].set()
        bramy["pola"].set()
        win.close()


def test_porazka_konstruktora_gridu_z_rodzicem_odpina_widok(qapp, tmp_path, monkeypatch):
    """Widok budowany z rodzicem (publiczna droga konstruktora): porażka po starcie wątków zbiera je, oddaje
    blokadę szuflady i odpina widok od rodzica - rodzic nie trzyma pół-zbudowanego dziecka z połączeniami
    (obiekt Pythona żyje w śladzie wyjątku). Falsyfikator: obwódka bez odpięcia od rodzica."""
    from PySide6.QtWidgets import QWidget
    from horreum import db
    from horreum.gui.grid import FramesView
    from test_gui_znajdz_szerokosci import _bramy_watkow
    sciezka = _baza_z_przebiegiem(tmp_path)
    bramy = _bramy_watkow(monkeypatch)
    polowy, _prawdziwa = _pada_w(monkeypatch, "_przywroc_panel_rodowodu")
    con = db.connect(sciezka)
    rodzic = QWidget()
    try:
        with pytest.raises(RuntimeError, match="konstruktor gridu padł"):
            FramesView(con, parent=rodzic, pola_poza_watkiem=True)
        assert len(polowy) == 1
        assert rodzic.findChildren(FramesView) == [] and polowy[0].parent() is None
        assert polowy[0]._zbior_thread is None and polowy[0]._pola_thread is None
        assert _blokada_wolna(sciezka)
    finally:
        bramy["zbior"].set()
        bramy["pola"].set()
        rodzic.close()
        con.close()


# ---------------------------------------------------------------- „Wciągnij z WBPP…” bez budowy Dostawy (AR-335)

def _okna_zniw(monkeypatch):
    """Okno żniw podmienione modułem w `sys.modules` (droga gospodarza importuje je leniwie): lista połączeń okien
    utworzonych przez gospodarza; okno wraca bez wciągnięcia (`harvested_root=None`)."""
    import types
    okna = []

    class _OknoZniw:
        def __init__(self, con, **_kw):
            okna.append(con)
            self.summary, self.harvested_root, self.harvested_stacks = "", None, []

        def exec(self):
            return 0
    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    return okna


def test_wciagnij_z_domu_bez_wciagniecia_nie_buduje_dostawy(qapp, tmp_path, monkeypatch):
    """AR-335: „Więcej… → Wciągnij z WBPP…” z Domu otwiera okno żniw, a strona Dostawy nie powstaje - powód odmowy
    biegu przy niezbudowanej Dostawie mówią zatrzaski gospodarza. Falsyfikator: bramka z odczytu property
    `pipeline_view` (budowa całej Dostawy dla samego powodu)."""
    from horreum.gui import home as home_mod
    okna = _okna_zniw(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        assert STRONA_DOSTAWA not in _zbudowane(win)
        win.home_view.akcje_wiecej[home_mod.WIECEJ_ZNIWA].trigger()
        assert okna == [win.con]
        assert STRONA_DOSTAWA not in _zbudowane(win)
    finally:
        win.close()


def test_wciagnij_przy_zapisie_zbiorow_odmawia_bez_budowy_dostawy(qapp, tmp_path, monkeypatch):
    """AR-335: zapis Zbiorów do plików w toku (prawdziwy uchwyt `grid._wb`) - wejście gospodarza w „Wciągnij z WBPP…”
    (pozycja Domu jest wtedy wygaszona, więc wprost) odmawia zdaniem zapisu, okna nie otwiera i Dostawy nie buduje.
    Falsyfikator: gałąź bez zatrzasku zapisu gospodarza (okno otwiera się w czasie zapisu)."""
    from horreum.gui import home as home_mod, i18n
    okna = _okna_zniw(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        grid = win.grid_view
        grid._wb.busy_changed.emit(True)
        try:
            win._on_wiecej_domu(home_mod.WIECEJ_ZNIWA)
            assert okna == []
            assert str(win._pelny_komunikat) == i18n.t("pipeline.refuse.writeback")
            assert STRONA_DOSTAWA not in _zbudowane(win)
        finally:
            grid._wb.busy_changed.emit(False)
    finally:
        win.close()


def test_wciagnij_przy_sondzie_zrodla_zbudowanej_dostawy_odmawia_stanem_widoku(qapp, tmp_path, monkeypatch, ustawienia):
    """AR-335: Dostawa zbudowana, w biegu sama sonda źródła („Wskaż katalog…”, etap `probe` bez bazy) - wątek
    widoku jest, a `running_changed` nie pada, więc zatrzask biegu gospodarza stoi na fałszu. Odmowa biegu przychodzi
    ze stanu widoku (`PipelineView.powod_odmowy_biegu`), okno żniw się nie otwiera. Falsyfikator: gospodarz pyta
    własnych zatrzasków także przy zbudowanej Dostawie."""
    import threading
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui import home as home_mod, i18n
    from horreum.gui.pipeline import PipelineWorker
    okna = _okna_zniw(monkeypatch)
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
        pipeline = win.pipeline_view
        pipeline._on_pick_dir()
        assert pipeline._thread is not None and not win._dostawa_w_biegu
        win.home_view.akcje_wiecej[home_mod.WIECEJ_ZNIWA].trigger()
        assert okna == []
        assert str(win._pelny_komunikat) == i18n.t("pipeline.refuse.delivery_running")
    finally:
        puszczona.set()
        _czekaj(lambda: win._gotowy("pipeline_view")._thread is None, "koniec sondy źródła")
        win.close()
