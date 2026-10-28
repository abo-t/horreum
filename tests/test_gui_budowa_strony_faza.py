"""AR-351: budowa strony leniwej na żądanie (Zbiory, Dostawa, Planer) mówi, że trwa - faza „Przygotowuję stronę „…”…”
z kursorem oczekiwania i NAPISEM WIERSZA sidebara, którym człowiek wchodzi; dobudowa Zbiorów zegarem w bezczynności -
bez fazy i kursora; faza otwarcia bazy nie gaśnie w budowie zagnieżdżonej i gaśnie na każdym wyjściu `open_path`.

Zmierzone natywnie przed zmianą (kopia pf4, 10 biegów na tryb): klik w Zbiory przed dobudową - budowa 322,9 ms, 10/10
biegów z przestojem pętli > 300 ms, a etykieta fazy mówiła wtedy „Liczę Porządki…” i kursor był zwykły.

Stan w chwili budowy łapie szpieg w konstruktorze widoku strony (`FramesView`, `PipelineView`, `PlannerView` - żaden
nie jest slotem): kursor (`QApplication.overrideCursor`) i etykieta fazy okna. Gesty prawdziwe: klik wiersza sidebara,
kafel Domu, wybór „Wciągnij z WBPP…” z menu „Więcej…” Domu. Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os
import sqlite3
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum.gui import busy, i18n
from horreum.gui.app import (NAV_DOM, NAV_DOSTAWA, NAV_PLANER, NAV_ZBIORY, NAV_ZNAJDZ, STRONA_DOM, STRONA_DOSTAWA,
                             MainWindow)
from horreum.gui.wb_worker import zlacz_zdania

from test_gui_gospodarz import _okno_zniw, _rodowod_stosow, _wybierz_zniwa
from test_gui_strony_leniwe import (_baza, _klik_nav, _licz_gridy, _okno, _pokazane_bez_obrotu, _z_dobudowa,
                                    _zbudowane)


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_watkow(monkeypatch):
    """Tryb przewidywalny (bez wątków tła i bez dobudowy w bezczynności) - testy dobudowy włączają ją jawnie."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)


@pytest.fixture
def jezyk():
    """Język UI na czas testu - wraca do poprzedniego."""
    poprzedni = i18n._LANG
    yield i18n.set_lang
    i18n.set_lang(poprzedni)


def _kursor():
    k = QApplication.overrideCursor()
    return None if k is None else k.shape()


def _szpieg(monkeypatch, klasa):
    """Zapis `(kursor, etykieta fazy)` przy wejściu w konstruktor `klasa` - okno podaje test (`stan["okno"]`)."""
    stan = {"okno": None, "zapis": []}
    prawdziwy = klasa.__init__

    def _init(self, *a, **k):
        stan["zapis"].append((_kursor(), stan["okno"].phase_label.text()))
        prawdziwy(self, *a, **k)
    monkeypatch.setattr(klasa, "__init__", _init)
    return stan


def _zdanie(win, wiersz):
    return i18n.t("busy.page_building", page=win.nav.item(wiersz).text())


def _zdania_budowy(win):
    return {_zdanie(win, w) for w in (NAV_ZNAJDZ, NAV_ZBIORY, NAV_DOSTAWA, NAV_PLANER)}


@pytest.mark.parametrize("wiersz", [NAV_ZBIORY, NAV_ZNAJDZ])
def test_klik_przed_dobudowa_buduje_pod_faza_z_kursorem_i_napisem_wiersza(qapp, tmp_path, monkeypatch, wiersz):
    """Prawdziwy klik w wiersz strony Zbiorów, zanim zegar dobudowy ruszył: w chwili budowy kursor oczekiwania i zdanie
    z napisem KLIKNIĘTEGO wiersza („Znajdź” albo „Zbiory klasyczne” - jedna strona, dwa wiersze); po kliku kursor
    zdjęty, a zdanie budowy zeszło z paska. Falsyfikatory: budowa bez `busy.busy`; wiersz niepodany z
    `_on_nav_changed` (zdanie mówi wiersz startu strony)."""
    from horreum.gui.grid import FramesView
    _z_dobudowa(monkeypatch)
    stan = _szpieg(monkeypatch, FramesView)
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    stan["okno"] = win
    try:
        _klik_nav(win, wiersz)
        assert stan["zapis"] == [(Qt.WaitCursor, _zdanie(win, wiersz))]
        assert _kursor() is None
        assert win.phase_label.text() not in _zdania_budowy(win)
        assert win.nav.currentRow() == wiersz
    finally:
        win.close()


def test_dobudowa_zegarem_bez_fazy_i_kursora(qapp, tmp_path, monkeypatch):
    """Dobudowa Zbiorów zegarem w bezczynności (człowiek na nią nie czeka): w chwili budowy bez kursora oczekiwania
    i bez zdania budowy. Falsyfikator: `faza=True` w `_dobuduj_zbiory`."""
    from horreum.gui.grid import FramesView
    _z_dobudowa(monkeypatch)
    stan = _szpieg(monkeypatch, FramesView)
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    stan["okno"] = win
    try:
        for _ in range(20):
            if win._gotowy("grid_view") is not None:
                break
            QApplication.processEvents()
        assert win._gotowy("grid_view") is not None, "zegar nie dobudował Zbiorów"
        assert len(stan["zapis"]) == 1
        kursor, etykieta = stan["zapis"][0]
        assert kursor is None and etykieta not in _zdania_budowy(win)
    finally:
        win.close()


_OCZEKIWANE = {("pl", NAV_DOSTAWA): "Przygotowuję stronę „Dostawa”…",
               ("pl", NAV_PLANER): "Przygotowuję stronę „Planer”…",
               ("en", NAV_DOSTAWA): "Preparing the “Intake” page…",
               ("en", NAV_PLANER): "Preparing the “Planner” page…"}


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("wiersz", [NAV_DOSTAWA, NAV_PLANER])
def test_dostawa_i_planer_buduja_sie_pod_faza_z_kursorem_i_nazwa(qapp, tmp_path, monkeypatch, jezyk, lang, wiersz):
    """Prawdziwy klik w wiersz Dostawy i Planera przed ich budową (PL i EN): w chwili budowy kursor oczekiwania i zdanie
    z nazwą strony - dosłownie, w mianowniku i w cudzysłowie języka; po kliku kursor zdjęty, zdanie zeszło.
    Falsyfikatory: faza tylko przy stronie Zbiorów; nazwa strony z innego klucza niż napis wiersza."""
    from horreum.gui.pipeline import PipelineView
    from horreum.gui.planner import PlannerView
    jezyk(lang)
    stan = _szpieg(monkeypatch, PipelineView if wiersz == NAV_DOSTAWA else PlannerView)
    win = _okno(_baza(tmp_path))
    stan["okno"] = win
    try:
        _klik_nav(win, wiersz)
        assert stan["zapis"] == [(Qt.WaitCursor, _OCZEKIWANE[(lang, wiersz)])]
        assert _kursor() is None
        assert win.phase_label.text() != _OCZEKIWANE[(lang, wiersz)]
    finally:
        win.close()


def test_komenda_mowi_wiersz_wejscia_a_atrybut_wiersz_startu_strony(qapp, tmp_path, monkeypatch):
    """Kafel „Znajdź” Domu (komenda `_wejdz(NAV_ZNAJDZ)`) buduje Zbiory pod zdaniem „Znajdź”; kafel „Wydaj” Domu
    (komenda przez atrybut widoku, bez wiersza - okno wydania nad Domem, podstawione i zamknięte) - pod zdaniem
    wiersza prezentacji, w której strona startuje („Zbiory klasyczne”). Falsyfikator: wiersz niepodany z `_wejdz`."""
    from horreum.gui import grid as grid_mod
    from horreum.gui.grid import FramesView
    okna_wydania = []

    class _OknoWydania:
        def __init__(self, *a, **k):
            okna_wydania.append(_kursor())
            self.object_id = None

        def exec(self):
            return 0
    monkeypatch.setattr(grid_mod, "ObjectPickDialog", _OknoWydania)
    stan = _szpieg(monkeypatch, FramesView)
    win = _okno(_baza(tmp_path))
    stan["okno"] = win
    try:
        QTest.mouseClick(win.home_view.tile_znajdz, Qt.LeftButton)
        QApplication.processEvents()
        assert stan["zapis"] == [(Qt.WaitCursor, _zdanie(win, NAV_ZNAJDZ))]
    finally:
        win.close()
    stan = _szpieg(monkeypatch, FramesView)
    win = _okno(_baza(tmp_path, "s8b.db"))
    stan["okno"] = win
    try:
        QTest.mouseClick(win.home_view.tile_wydaj, Qt.LeftButton)
        QApplication.processEvents()
        assert stan["zapis"] == [(Qt.WaitCursor, _zdanie(win, NAV_ZBIORY))]
        assert okna_wydania == [None], "okno wydania nie stanęło po budowie (albo stanęło pod kursorem oczekiwania)"
        assert _kursor() is None and win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()


def test_budowa_w_fazie_otwarcia_nie_gasi_fazy_zewnetrznej(qapp, tmp_path, monkeypatch):
    """Montaż z `_strony_leniwie = False` (`zbuduj_strony` w fazie otwarcia bazy): każda z trzech budów pod zdaniem
    budowy i kursorem; zaraz po `zbuduj_strony` etykieta wraca do „Buduję widoki…”, kursor dalej oczekiwania (faza
    otwarcia trwa); po `open_path` etykieta pusta, kursor zdjęty. Falsyfikator: `_end_phase` po budowie bez warunku
    fazy zewnętrznej."""
    from horreum.gui.grid import FramesView
    from horreum.gui.pipeline import PipelineView
    from horreum.gui.planner import PlannerView
    monkeypatch.setattr(MainWindow, "_strony_leniwie", False)
    stany = [_szpieg(monkeypatch, k) for k in (FramesView, PipelineView, PlannerView)]
    po_budowie = []
    prawdziwe = MainWindow.zbuduj_strony

    def _zbuduj_strony(self):
        prawdziwe(self)
        po_budowie.append((self.phase_label.text(), _kursor()))
    monkeypatch.setattr(MainWindow, "zbuduj_strony", _zbuduj_strony)
    win = MainWindow()
    for s in stany:
        s["okno"] = win
    try:
        win.open_path(_baza(tmp_path))
        for s, wiersz in zip(stany, (NAV_ZBIORY, NAV_DOSTAWA, NAV_PLANER)):
            assert s["zapis"] == [(Qt.WaitCursor, _zdanie(win, wiersz))]
        assert po_budowie == [(i18n.t("busy.mount_views"), Qt.WaitCursor)]
        assert win.phase_label.text() == "" and _kursor() is None
    finally:
        win.close()


def test_porazka_montazu_gasi_faze_i_kursor(qapp, tmp_path, monkeypatch):
    """Montaż z `_strony_leniwie = False`, konstruktor gridu pada (błąd programu): `open_path` rzuca dalej, a etykieta
    fazy jest pusta i kursor zdjęty - dawniej „Buduję widoki…” zostawało na pasku. Falsyfikator: `_end_phase` w
    `_open_path` poza `finally`."""
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(MainWindow, "_strony_leniwie", False)

    def _pada(self, *a, **k):
        raise RuntimeError("konstruktor gridu padł w teście")
    monkeypatch.setattr(FramesView, "__init__", _pada)
    win = MainWindow()
    try:
        with pytest.raises(RuntimeError, match="konstruktor gridu"):
            win.open_path(_baza(tmp_path))
        assert win.phase_label.text() == "" and _kursor() is None
    finally:
        win.close()


def test_kotwica_w_pompie_fazy_nie_buduje_drugi_raz(qapp, tmp_path, monkeypatch):
    """Pompa fazy (`busy.repaint` - `processEvents`) w budowie na żądanie doręcza kotwicę liczników montażu i obraca
    pętlę: zegar dobudowy nie rusza drugiej budowy tej samej strony - jeden grid, zero wyjątków. Falsyfikator: zegar
    dobudowy niezdjęty przed fazą."""
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    prawdziwa = busy.repaint

    def _pompa():
        prawdziwa()
        win._po_licznikach_montazu()
        QApplication.processEvents()
    monkeypatch.setattr(busy, "repaint", _pompa)
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert len(gridy) == 1 and wyjatki == [], (len(gridy), wyjatki)
    finally:
        monkeypatch.setattr(busy, "repaint", prawdziwa)
        win.close()


def test_porazka_budowy_zdejmuje_kursor_i_zdanie(qapp, tmp_path, monkeypatch):
    """Konstruktor gridu pada przy kliku w Zbiory: wyjątek idzie do straży (jedno zgłoszenie), kursor zdjęty, zdanie
    budowy zeszło, wiersz sidebara cofnięty na Dom. Falsyfikator: sprzątanie fazy poza `finally`."""
    from horreum.gui.grid import FramesView
    wyjatki, budowy = [], []

    def _pada(self, *a, **k):
        budowy.append((_kursor(), win.phase_label.text()))
        raise RuntimeError("konstruktor gridu padł w teście")
    monkeypatch.setattr(FramesView, "__init__", _pada)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert budowy == [(Qt.WaitCursor, _zdanie(win, NAV_ZBIORY))]
        assert len(wyjatki) == 1 and isinstance(wyjatki[0], RuntimeError), wyjatki
        assert _kursor() is None
        assert win.phase_label.text() not in _zdania_budowy(win)
        assert win.nav.currentRow() == NAV_DOM
    finally:
        win.close()


def test_budowa_w_serii_licznikow_montazu_oddaje_faze_tla(qapp, tmp_path, monkeypatch):
    """Liczniki Porządków montażu w wątku tła (brama rachunku zamknięta - faza tła „Liczę Porządki…” stoi): klik
    w Planer buduje go pod zdaniem Planera z kursorem, a po budowie etykieta wraca do fazy tła - robota jeszcze trwa.
    Falsyfikator: zerowanie etykiety zamiast `_end_phase()` po budowie."""
    from horreum.gui.planner import PlannerView
    from test_gui_mainwindow import _BEZPIECZNIK_LICZNIKOW_S, _brama_rachunku, _czekaj_na
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
    stan = _szpieg(monkeypatch, PlannerView)
    win = _okno(_baza(tmp_path))
    stan["okno"] = win
    try:
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        _czekaj_na(lambda: win.phase_label.text() == i18n.t("busy.counting_tasks"), "faza tła montażu")
        _klik_nav(win, NAV_PLANER)
        assert stan["zapis"] == [(Qt.WaitCursor, _zdanie(win, NAV_PLANER))]
        assert win.phase_label.text() == i18n.t("busy.counting_tasks") and _kursor() is None
    finally:
        brama.set()
        _czekaj_na(lambda: win.tasks_view._liczniki_thread is None, "koniec serii liczników")
        win.close()


def test_kotwica_w_pompie_budowy_dostawy_nie_buduje_zbiorow_w_srodku(qapp, tmp_path, monkeypatch):
    """Bliźniak testu kotwicy dla Dostawy: zegar dobudowy uzbrojony, pompa fazy budowy Dostawy doręcza kotwicę
    liczników montażu i obraca pętlę - Zbiory NIE powstają w środku kliku (przed kursorem i zdaniem Dostawy); po budowie
    zegar wraca i dobudowa rusza. Falsyfikatory: zegar zdejmowany tylko przy budowie Zbiorów; warunek dobudowy patrzący
    tylko na budowę Zbiorów; zegar nieoddany po budowie innej strony."""
    _z_dobudowa(monkeypatch)
    gridy = _licz_gridy(monkeypatch)
    wyjatki, w_pompie = [], []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _pokazane_bez_obrotu(_baza(tmp_path))
    prawdziwa = busy.repaint

    def _pompa():
        prawdziwa()
        win._po_licznikach_montazu()
        QApplication.processEvents()
        if STRONA_DOSTAWA in win._w_budowie:    # pompa budowy Dostawy (grid ma własne fazy w swojej budowie)
            w_pompie.append(len(gridy))
    monkeypatch.setattr(busy, "repaint", _pompa)
    try:
        _klik_nav(win, NAV_DOSTAWA)
        monkeypatch.setattr(busy, "repaint", prawdziwa)
        assert w_pompie and set(w_pompie) == {0}, w_pompie
        for _ in range(20):
            if win._gotowy("grid_view") is not None:
                break
            QApplication.processEvents()
        assert win._gotowy("grid_view") is not None, "dobudowa nie ruszyła po budowie Dostawy"
        assert len(gridy) == 1 and wyjatki == [], (len(gridy), wyjatki)
    finally:
        monkeypatch.setattr(busy, "repaint", prawdziwa)
        win.close()


def test_porazka_budowy_sprzata_pod_kursorem_i_zdaniem(qapp, tmp_path, monkeypatch):
    """Grid powstał, a kontener strony pada: zbieranie wątków gridu (`zatrzymaj_pola` - blokujące) biegnie jeszcze pod
    kursorem oczekiwania i zdaniem budowy; po porażce oba zeszły razem. Falsyfikator: faza obejmuje wyłącznie budowę,
    nie sprzątanie po niej."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    from horreum.gui.grid import FramesView
    wyjatki, sprzatanie = [], []
    prawdziwe = FramesView.zatrzymaj_pola

    def _zatrzymaj(self):
        sprzatanie.append((_kursor(), win.phase_label.text()))
        prawdziwe(self)

    def _pada(self, *a, **k):
        raise RuntimeError("kontener strony padł w teście")
    monkeypatch.setattr(FramesView, "zatrzymaj_pola", _zatrzymaj)
    monkeypatch.setattr(ZnajdzView, "__init__", _pada)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_ZBIORY)
        assert len(wyjatki) == 1 and isinstance(wyjatki[0], RuntimeError), wyjatki
        assert sprzatanie[:1] == [(Qt.WaitCursor, _zdanie(win, NAV_ZBIORY))], sprzatanie
        assert _kursor() is None and win.phase_label.text() not in _zdania_budowy(win)
    finally:
        win.close()


# ---------------------------------------------------------------- szew z oknem żniw (komenda `_wejdz(NAV_DOSTAWA)`)

def test_wyjatek_wejscia_w_faze_nie_zostawia_budowy_w_toku(qapp, tmp_path, monkeypatch):
    """Wejście w fazę budowy Dostawy pada (`busy.busy` przed budowniczym - `_say_phase`, `repaint`): wyjątek idzie do
    straży, wpis budowy schodzi, a następne wejście buduje stronę bez asercji „budowana ponownie”. Falsyfikator:
    zdjęcie wpisu budowy w `finally` wewnątrz ciała fazy (wyjątek wejścia go omija, dobudowa i budowa stoją)."""
    import contextlib
    prawdziwa, pady, wyjatki = busy.busy, [], []
    win = _okno(_baza(tmp_path))

    @contextlib.contextmanager
    def _pada_raz(say, tekst):
        if not pady and tekst == _zdanie(win, NAV_DOSTAWA):     # wyłącznie wejście w fazę budowy Dostawy, raz
            pady.append(tekst)
            raise RuntimeError("wejście w fazę padło w teście")
        with prawdziwa(say, tekst):
            yield
    monkeypatch.setattr(busy, "busy", _pada_raz)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    try:
        _klik_nav(win, NAV_DOSTAWA)
        assert len(pady) == 1 and len(wyjatki) == 1 and isinstance(wyjatki[0], RuntimeError), (pady, wyjatki)
        assert STRONA_DOSTAWA not in win._w_budowie and _kursor() is None
        assert STRONA_DOSTAWA in win._zaslepki, "strona po porażce wejścia nie wróciła do zaślepki"
        _klik_nav(win, NAV_DOM)
        _klik_nav(win, NAV_DOSTAWA)
        assert len(wyjatki) == 1, wyjatki
        assert STRONA_DOSTAWA not in win._zaslepki and win.nav.currentRow() == NAV_DOSTAWA
    finally:
        win.close()


def test_zniwa_buduja_dostawe_pod_faza_i_zostawiaja_raport(qapp, tmp_path, monkeypatch):
    """Wybór „Wciągnij z WBPP…” z menu Domu, okno żniw wciągnęło stos: Dostawa buduje się RAZ pod zdaniem „Dostawa”
    z kursorem; po komendzie wiersz `NAV_DOSTAWA`, kursor zdjęty, etykieta fazy bez zdania budowy, a raport żniw stoi
    na pasku raportu (faza i raport to dwa widżety). Pin szwu komendy żniw z fazą budowy."""
    from horreum.gui.pipeline import PipelineView
    korzen = tmp_path / "zniwa"
    korzen.mkdir()
    _okno_zniw(monkeypatch, korzen, [("sha-stosu", (1,), None)])
    puszczona = _rodowod_stosow(monkeypatch)
    stan = _szpieg(monkeypatch, PipelineView)
    win = _okno(_baza(tmp_path))
    stan["okno"] = win
    try:
        _wybierz_zniwa(win)
        assert stan["zapis"] == [(Qt.WaitCursor, _zdanie(win, NAV_DOSTAWA))]
        assert win.nav.currentRow() == NAV_DOSTAWA and win.stack.currentIndex() == STRONA_DOSTAWA
        assert _kursor() is None
        assert win.phase_label.text() not in _zdania_budowy(win)
        assert str(win._pelny_komunikat) == "Wciągnięto stosy"
    finally:
        puszczona.set()
        pv = win._gotowy("pipeline_view")
        for _ in range(3000):
            if pv is None or pv._thread is None:
                break
            QApplication.processEvents()
        win.close()


def test_porazka_budowy_dostawy_po_zniwach_zostawia_wiersz_i_raport(qapp, tmp_path, monkeypatch):
    """Budowa Dostawy po oknie żniw pada błędem bazy: w chwili budowy zdanie „Dostawa” z kursorem; po komendzie kursor
    zdjęty, etykieta fazy pusta OBOK raportu z utratą rodowodu i wynikiem okna, wiersz i strona zostają na Domu.
    Falsyfikator: sprzątanie fazy poza `finally`."""
    from horreum.gui.pipeline import PipelineView
    _okno_zniw(monkeypatch, tmp_path, [("sha-stosu", (1,), None)])
    budowy, wyjatki = [], []

    def _pada(self, *a, **k):
        budowy.append((_kursor(), win.phase_label.text()))
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(PipelineView, "__init__", _pada)
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    win = _okno(_baza(tmp_path))
    try:
        _wybierz_zniwa(win)
        QApplication.processEvents()
        assert budowy == [(Qt.WaitCursor, _zdanie(win, NAV_DOSTAWA))]
        assert len(wyjatki) == 1 and isinstance(wyjatki[0], sqlite3.OperationalError), wyjatki
        assert _kursor() is None and win.phase_label.text() == ""
        assert str(win._pelny_komunikat) == str(zlacz_zdania(" - ", [i18n.t("status.harvest_lineage_lost", n=1),
                                                                     "Wciągnięto stosy"]))
        assert win.nav.currentRow() == NAV_DOM and win.stack.currentIndex() == STRONA_DOM
        assert STRONA_DOSTAWA not in _zbudowane(win)
    finally:
        win.close()
