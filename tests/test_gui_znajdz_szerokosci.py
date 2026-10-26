"""Szerokości kolumn Znajdź z treści (AR-346, offscreen): moduł bez Qt `horreum.gui.szerokosci` (reguła wierszy
Qt i reguła szerokości wspólna z planerem), pierwsze wejście w Znajdź kaflem Domu bez przejścia Qt po `data()`
i z TYMI SAMYMI szerokościami co pięć `resizeColumnToContents`, wejście przy zbiorze w drodze (zamówienie
szerokości na najbliższe przyłożenie zbioru, także nowszego zlecenia; gest ręki zdejmuje kolumnę; porażka
terminalna składu i wyjście ze Znajdź zamówienie gaszą).

Równoważność z Qt sprawdzamy, liczbą z prawdziwego Qt na tej samej tabeli, wychodząc z TEGO SAMEGO stanu: owijka
instancji `_szerokosci_znajdz` po prawdziwym rachunku oddaje tabeli szerokości sprzed niego i liczy je pięcioma
`resizeColumnToContents` (belka grupy odejmuje bieżące szerokości kolumn spanu - wynik zależy od stanu startu).
Zmierzone natywnie przed zmianą (kopia pf4, `QT_QPA_PLATFORM=windows`): pierwsze wejście 40 000 wywołań `data`
i klik 455-795 ms; prototyp tej reguły - te same szerokości 5/5 kolumn PL i EN, 5000/5000 komórek, 2364/2364
komórek kursywą, klik 175-236 ms. Offscreen kursywa i pogrubienie mają metrykę zwykłego tekstu (12 px na znak),
więc wiersze kursywą dostają tu czcionkę o WIĘKSZYM rozmiarze - inaczej pominięcie `FontRole` przeszłoby niezauważone.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QTableView

from horreum import db
from horreum.gui import grid as grid_mod, grid_model, grid_workers, szerokosci
from horreum.gui.app import MainWindow

from test_gui_isolation import PKG, _imports_pyside6
from test_gui_znajdz import _seed

NOW = "2026-10-26T12:00:00"
KLUCZE = grid_mod.FramesView._KOLUMNY_Z_TRESCI


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- moduł bez Qt

def test_modul_szerokosci_bez_qt():
    """Rachunek szerokości jest Qt-wolny (metrykę podaje wołający) - bramka `test_gui_isolation` pilnuje całego
    pakietu, ten wpis pilnuje modułu z imienia. Falsyfikator: import PySide6 w `szerokosci.py`."""
    sciezka = PKG / "gui" / "szerokosci.py"
    assert sciezka.is_file() and not _imports_pyside6(sciezka)


def test_wiersze_podpowiedzi_jak_qt():
    """Wiersze, z których Qt liczy podpowiedź szerokości (`QTableView::sizeHintForColumn`, Qt 6.9.2): kadr, potem
    na przemian w górę i w dół, do precyzji nagłówka. Mutanty: bez naprzemienności (tylko w dół); precyzja 0 bez
    wyjścia po kadrze; `dol` = -1 bez zamiany na ostatni wiersz (przypadek przewinięty bez kadru)."""
    w = szerokosci.wiersze_podpowiedzi
    assert w(0, -1, 1500, 1000) == list(range(1000))                     # niewidoczna albo krótsza niż kadr
    assert w(0, 37, 1500, 1000) == list(range(1000))                     # kadr od góry
    przewinieta = w(600, 640, 1500, 1000)
    assert przewinieta[:41] == list(range(600, 641))
    assert przewinieta[41:47] == [599, 641, 598, 642, 597, 643]
    assert sorted(przewinieta) == list(range(120, 1120))
    assert sorted(w(1400, 1440, 1500, 1000)) == list(range(500, 1500))   # koniec modelu - już tylko w górę
    niewidoczna = w(600, -1, 1500, 1000)
    assert niewidoczna[:900] == list(range(600, 1500)) and sorted(niewidoczna) == list(range(500, 1500))
    assert w(600, 640, 1500, 0) == list(range(600, 641))                 # precyzja 0 - sam kadr
    assert sorted(w(600, 640, 1500, -1)) == list(range(1500))           # precyzja -1 - wszystko
    assert w(0, -1, 0, 1000) == []
    assert w(0, -1, 5, 1000) == [0, 1, 2, 3, 4]


def test_wiersze_podpowiedzi_zgodne_z_zainstalowanym_qt(qapp):
    """To samo pytanie zadane PRAWDZIWEMU Qt: tabela 1500 wierszy wąskiego tekstu przewinięta do wiersza 600, jeden
    wiersz szeroki - `sizeHintForColumn` widzi go wtedy i tylko wtedy, gdy jest w `wiersze_podpowiedzi` (precyzja
    1000, 0, -1; tabela pokazana i schowana). Pilnuje reguły wobec Qt zainstalowanego w baterii, nie wobec lektury
    źródła - nowa wersja PySide6, która zmieni regułę, czerwieni ten test przed wydaniem."""
    model = QStandardItemModel(1500, 1)
    for r in range(1500):
        model.setItem(r, 0, QStandardItem("a"))
    t = QTableView()
    t.setModel(model)
    t.resize(300, 600)
    t.show()
    QApplication.processEvents()
    try:
        t.scrollTo(model.index(600, 0), QTableView.PositionAtTop)
        QApplication.processEvents()
        vh, h = t.verticalHeader(), t.horizontalHeader()
        waski = t.sizeHintForColumn(0)
        rozne = []
        for widoczna in (True, False):
            t.setVisible(widoczna)
            QApplication.processEvents()
            gora = max(0, vh.visualIndexAt(0))
            dol = vh.visualIndexAt(t.viewport().height()) if t.isVisible() else -1
            for precyzja in (1000, 0, -1):
                h.setResizeContentsPrecision(precyzja)
                zbior = set(szerokosci.wiersze_podpowiedzi(gora, dol, 1500, precyzja))
                for k in (0, 50, 109, 110, 119, 120, 500, 599, 600, 619, 620, 999, 1000, 1109, 1110, 1119, 1499):
                    model.item(k, 0).setText("W" * 40)
                    if (t.sizeHintForColumn(0) > waski) != (k in zbior):
                        rozne.append((widoczna, precyzja, k))
                    model.item(k, 0).setText("a")
        assert rozne == [], f"reguła wierszy rozjechana z Qt (widoczna, precyzja, wiersz): {rozne}"
    finally:
        t.close()


# ---------------------------------------------------------------- pierwsze wejście w Znajdź (MainWindow, kafel Domu)

_DLUGI_TELESKOP = "Teleskop " + "z bardzo długą nazwą własną " * 8
_DLUGA_KAMERA = "AAA kamera " + "o nazwie dłuższej niż suma kolumn " * 5
_FLAT = "FlatWizard - kalibracja z długim zeznaniem"


def _baza_1500(sciezka, n=1500):
    """1500 klatek (więcej niż precyzja Qt), porządek startowy widoku - ścieżka malejąco, więc klatka `i` stoi
    w wierszu `n - i`: obiekty M1..M9; filtr „Ha” (krótszy od nagłówka „Filtr” - podłoga nagłówka); dziesięć
    flatów z zeznaniem obiektu w nagłówku (stan `kind` - kursywa, najdłuższy tekst kolumny obiektu, wiersze
    10..19); pięć klatek kamery o nazwie dłuższej niż suma kolumn Znajdź (wiersze 0..4; belka „Grupuj wg:
    Kamera” z aktywnym spanem, pierwsza po sortowaniu belek); jedna klatka w wierszu 1449, za limitem Qt,
    z zestawem dłuższym niż każdy w wierszach Qt (Qt jej nie bierze)."""
    con = db.open_db(sciezka)
    con.executemany("INSERT INTO camera (id, model_canon, created_at) VALUES (?, ?, ?)",
                    [(1, "ASI2600MM", NOW), (2, _DLUGA_KAMERA, NOW)])
    con.executemany(
        "INSERT INTO telescope (id, telescop_canon, label, status, merged_into, created_at) VALUES (?,?,?,?,?,?)",
        [(1, "RC8", None, "proposed", None, NOW), (2, "LONG", _DLUGI_TELESKOP, "approved", None, NOW)])
    con.executemany("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES (?,?,?,?,?)",
                    [(1, 1, 1, "proposed", NOW), (2, 2, 1, "proposed", NOW), (3, 1, 2, "proposed", NOW)])
    con.executemany("INSERT INTO object (id, canon, catalog) VALUES (?, ?, ?)",
                    [(i, f"M{i}", "Messier") for i in range(1, 10)])
    klatki, naglowki, lokacje = [], [], []
    for i in range(1, n + 1):
        flat = n - 19 <= i <= n - 10
        config = 3 if i > n - 5 else 2 if i == 51 else 1
        kamera = 2 if config == 3 else 1
        obiekt = None if flat else (i % 9) + 1
        klatki.append((i, f"d{i}", "flat" if flat else "light", "fits", config, kamera, obiekt, "Ha", NOW))
        naglowki.append((i, "{}", _FLAT if flat else f"M{(i % 9) + 1}", f"2026-08-{(i % 20) + 1:02d}T22:00:00", 300.0))
        lokacje.append((i, "V", f"/a/f_{i:05d}.fits", 1))
    con.executemany("INSERT INTO frame (id, sha1_data, kind, filetype, config_id, camera_id, object_id, "
                    "filter_canon, first_seen_at) VALUES (?,?,?,?,?,?,?,?,?)", klatki)
    con.executemany("INSERT INTO header (frame_id, raw_json, object_raw, date_obs, exptime) VALUES (?,?,?,?,?)",
                    naglowki)
    con.executemany("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)", lokacje)
    con.commit()
    con.close()


@pytest.fixture
def okno(qapp, tmp_path, monkeypatch):
    """Okno z bazą 1500 klatek w trybie przewidywalnym (skład i pola bez wątków, bez dobudowy w bezczynności) -
    strona Zbiorów zbudowana przed pomiarem, Dom na ekranie."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)
    sciezka = str(tmp_path / "znajdz1500.db")
    _baza_1500(sciezka)
    win = MainWindow(sciezka)
    win.resize(1500, 900)
    win.show()
    QApplication.processEvents()
    assert win.grid_view.model.rowCount() == 1500     # odczyt property buduje stronę Zbiorów
    yield win
    win.close()


@pytest.fixture
def kursywa_wieksza(monkeypatch):
    """Atrapa czcionki komórki: `FontRole` z `_base_cell` (kursywa wierszy poza kanonem) ma 1,6× rozmiar - i Qt
    (przez `data`), i rachunek z treści czytają tę samą metodę, a offscreen różnicy kursywy nie widać."""
    prawdziwa = grid_model.GridTableModel._base_cell

    def _base_cell(self, row, key, role):
        wynik = prawdziwa(self, row, key, role)
        if role == Qt.FontRole and isinstance(wynik, QFont):
            wynik.setPointSizeF(QApplication.font().pointSizeF() * 1.6)
        return wynik
    monkeypatch.setattr(grid_model.GridTableModel, "_base_cell", _base_cell)


def _grupuj(v, klucz):
    indeks = v.combo_group.findData(klucz)
    assert indeks >= 0, klucz
    v.combo_group.setCurrentIndex(indeks)
    QApplication.processEvents()


def _szpieg_szerokosci(v):
    """Owijka INSTANCJI `_szerokosci_znajdz` (wołana wprost z `set_presentation` i `_zastosuj_zbior`, nie slot):
    po prawdziwym rachunku tabela wraca do szerokości sprzed niego i liczy je pięcioma `resizeColumnToContents`
    Qt od tego samego stanu, potem wraca do wyniku rachunku. Zapis per wywołanie: `(klucze, nasze, qt)`."""
    t, m = v.table, v.model
    prawdziwe = v._szerokosci_znajdz
    zapis = []

    def _szerokosci_znajdz(klucze=None):
        kl = KLUCZE if klucze is None else tuple(klucze)
        kolumny = {k: m.base_col(k) for k in kl}
        sledzone = list(kolumny.values()) + ([m.base_col("note")] if klucze is None else [])
        przed = {c: t.columnWidth(c) for c in sledzone}
        prawdziwe(klucze)
        po = {c: t.columnWidth(c) for c in sledzone}
        for c, w in przed.items():
            t.setColumnWidth(c, w)
        for c in kolumny.values():
            t.resizeColumnToContents(c)
        qt = {k: t.columnWidth(c) for k, c in kolumny.items()}
        for c, w in po.items():
            t.setColumnWidth(c, w)
        zapis.append((kl, {k: po[c] for k, c in kolumny.items()}, qt))
    v._szerokosci_znajdz = _szerokosci_znajdz
    return zapis


def _kafel_znajdz(win):
    QTest.mouseClick(win.home_view.tile_znajdz, Qt.LeftButton)
    QApplication.processEvents()


@pytest.mark.parametrize("grupa", [None, "camera_model"])
def test_pierwsze_wejscie_w_Znajdz_z_Domu_bez_przejscia_Qt_po_komorkach(okno, monkeypatch, grupa):
    """Klik w kafel Znajdź Domu przy 1500 wierszach: model pytany mniej niż 3000 razy (Qt - pięć kolumn × 1000
    wierszy × 8 ról = 40 000; belka grupy - dwa pytania o podpis i czcionkę). Falsyfikatory: pięć
    `resizeColumnToContents` z powrotem; tekst komórki przez `data()` zamiast `_base_cell`."""
    v = okno.grid_view
    if grupa:
        _grupuj(v, grupa)
    licz = [0]
    prawdziwe = grid_model.GridTableModel.data

    def _data(self, *a, **k):
        licz[0] += 1
        return prawdziwe(self, *a, **k)
    monkeypatch.setattr(grid_model.GridTableModel, "data", _data)
    _kafel_znajdz(okno)
    assert v.prezentacja == grid_mod.PREZENTACJA_ZNAJDZ
    assert licz[0] < 3000, licz[0]


@pytest.mark.parametrize("grupa", [None, "_object"])
def test_pierwsze_wejscie_w_Znajdz_daje_szerokosci_resizeColumnToContents(okno, kursywa_wieksza, grupa):
    """Szerokości pięciu kolumn po kliku w kafel Znajdź = pięć `resizeColumnToContents` Qt od tego samego stanu
    tabeli. Dane rozróżniają: kursywa (wiersze flatów, najdłuższy tekst obiektu); wiersz za limitem Qt z
    najdłuższym zestawem (Qt go nie bierze); filtr krótszy od nagłówka (podłoga nagłówka); belki „Grupuj wg:
    Obiekt” (span pochłania podpis - równość przy belkach nieaktywnych; span aktywny - test niżej). Mutanty:
    `FontRole` pominięta, wszystkie wiersze zamiast wierszy Qt (bez grup); margines bez linii siatki, bez
    podłogi nagłówka (każdy parametr)."""
    v = okno.grid_view
    if grupa:
        _grupuj(v, grupa)
    zapis = _szpieg_szerokosci(v)
    _kafel_znajdz(okno)
    assert [kl for kl, _n, _q in zapis] == [KLUCZE], zapis
    _kl, nasze, qt = zapis[0]
    assert nasze == qt
    t, m = v.table, v.model
    assert nasze["filter_canon"] == t.horizontalHeader().sectionSizeHint(m.base_col("filter_canon"))
    if grupa is None:
        wiersz = next(r for r, row in enumerate(m._rows) if row.get("_zestaw", "").startswith(_DLUGI_TELESKOP))
        assert wiersz >= 1000, "zestaw spoza wierszy Qt musi stać za limitem"
        assert t.columnWidth(m.base_col("_zestaw")) < QFontMetricsF(t.font()).horizontalAdvance(
            m.data(m.index(wiersz, m.base_col("_zestaw")), Qt.DisplayRole)), "wiersz za limitem nie liczy się"


def test_belka_z_aktywnym_spanem_daje_szerokosc_resizeColumnToContents(qapp, tmp_path):
    """„Grupuj wg: Kamera”, podpis belki szerszy niż suma pozostałych kolumn spanu (strona 900 px - ostatnia
    kolumna rozciąga się do kadru): SPAN AKTYWNY, kolumna obiektu szersza od każdej komórki i równa pięciu
    `resizeColumnToContents` od tego samego stanu. Mutanty: belka jak zwykła komórka (bez odjęcia spanu - za
    szeroko); belka pominięta (za wąsko)."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    sciezka = str(tmp_path / "span.db")
    _baza_1500(sciezka)
    con = db.connect(sciezka)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    s = ZnajdzView(v)
    s.resize(900, 700)
    s.show()
    QApplication.processEvents()
    try:
        _grupuj(v, "camera_model")
        zapis = _szpieg_szerokosci(v)
        s.show_find()
        _kl, nasze, qt = zapis[0]
        assert nasze == qt
        t, m = v.table, v.model
        belka = next(r for r, row in enumerate(m._rows) if row.get("_group") == _DLUGA_KAMERA)
        assert belka < 1000
        margines = 2 * (t.style().pixelMetric(QStyle.PM_FocusFrameHMargin, None, t) + 1) + 1
        komorki = max(QFontMetricsF(t.font()).horizontalAdvance(row["_object"])
                      for row in m._rows[:1000] if "_group" not in row)
        assert nasze["_object"] > komorki + margines, "span nie zdecydował - test nie mierzy reguły belki"
    finally:
        v.zatrzymaj_pola()
        s.close()
        con.close()


# ---------------------------------------------------------------- wejście przy zbiorze w drodze

def _bramy_watkow(monkeypatch):
    """Skład zbioru i pokrycie pól w wątkach tła wstrzymane bramami (`stan["zbior"]`, `stan["pola"]` - zdarzenia
    do zwolnienia; przerwanie działa, więc widok zatrzymany nie wisi). `stan["pada"]` - tyle kolejnych składów
    pada błędem po zwolnieniu bramy. Wołający zwalnia obie bramy w sprzątaniu."""
    stan = {"zbior": threading.Event(), "pola": threading.Event(), "pada": 0}
    prawdziwy = grid_mod._sklad_zbioru

    def _sklad(con_, migawka, przerwij=lambda: None):
        while not stan["zbior"].is_set():
            przerwij()
            time.sleep(0.005)
        if stan["pada"]:
            stan["pada"] -= 1
            raise RuntimeError("skład zbioru padł w teście")
        return prawdziwy(con_, migawka, przerwij)
    for modul in (grid_mod, grid_workers):     # wątek GUI (fasada) i robotnik tła
        monkeypatch.setattr(modul, "_sklad_zbioru", _sklad)
    prawdziwe_pola = grid_workers.PolaWorker._policz

    def _policz(self, con_):
        while not stan["pola"].is_set():
            if self._cancel.is_set():
                raise RuntimeError("przerwano")
            time.sleep(0.005)
        return prawdziwe_pola(self, con_)
    monkeypatch.setattr(grid_workers.PolaWorker, "_policz", _policz)
    return stan


@pytest.fixture
def bramy(monkeypatch):
    stan = _bramy_watkow(monkeypatch)
    yield stan
    stan["zbior"].set()
    stan["pola"].set()


def _czekaj(warunek, limit_s=15.0):
    koniec = time.monotonic() + limit_s
    while not warunek():
        assert time.monotonic() < koniec, "warunek nie zaszedł w limicie"
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def w_drodze(qapp, tmp_path, bramy):
    """`ZnajdzView` nad gridem z wątkami tła (tryb produktu) - pierwszy zbiór i pola wstrzymane, Znajdź wchodzi
    przy pustym modelu i zbiorze w drodze."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    con = db.open_db(str(tmp_path / "wdrodze.db"))
    _seed(con)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    s = ZnajdzView(v)
    s.resize(1400, 800)
    s.show()
    QApplication.processEvents()
    yield s, v, bramy
    bramy["zbior"].set()
    bramy["pola"].set()
    v.zatrzymaj_pola()
    s.close()
    con.close()


def _wejscie_w_drodze(s, v):
    s.show_find()
    QApplication.processEvents()
    assert v.model.rowCount() == 0 and v.zbior_w_drodze(), "Znajdź miało wejść przy zbiorze w drodze"
    assert v._szerokosci_zamowione is not None


def _do_przylozenia(v):
    _czekaj(lambda: not v.zbior_w_drodze() and v.model.rowCount() > 0)


def _przeciagnij_sekcje(v, klucz, o_px):
    """Gest ręki: prawdziwe przeciągnięcie uchwytu sekcji nagłówka (prawa krawędź kolumny) o `o_px`."""
    h = v.table.horizontalHeader()
    c = v.model.base_col(klucz)
    x = h.sectionViewportPosition(c) + h.sectionSize(c) - 1
    y = h.height() // 2
    QTest.mousePress(h.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseMove(h.viewport(), QPoint(x + o_px // 2, y))
    QTest.mouseMove(h.viewport(), QPoint(x + o_px, y))
    QTest.mouseRelease(h.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x + o_px, y))
    QApplication.processEvents()


def test_wejscie_przy_zbiorze_w_drodze_liczy_szerokosci_przy_przylozeniu(w_drodze):
    """Wejście w Znajdź przy pustym modelu (zbiór startu w drodze) liczy z podpowiedzi nagłówka, a przyłożenie TEGO
    zbioru liczy pięć kolumn jeszcze raz - te same liczby co `resizeColumnToContents` od tego samego stanu; noc
    szersza niż jej nagłówek. Falsyfikator: bez liczenia przy przyłożeniu (noc zostaje przy podpowiedzi nagłówka -
    natywnie na pf4 49 px przy treści 69)."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    naglowek_nocy = v.table.columnWidth(v.model.base_col("night"))
    zapis = _szpieg_szerokosci(v)
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert [kl for kl, _n, _q in zapis] == [KLUCZE], zapis
    _kl, nasze, qt = zapis[0]
    assert nasze == qt
    assert nasze["night"] > naglowek_nocy
    assert v._szerokosci_zamowione is None


def test_gest_reki_w_oknie_w_drodze_zdejmuje_kolumne_z_zamowienia(w_drodze):
    """Przeciągnięcie uchwytu „Noc” w oknie „w drodze”: szerokość z ręki przeżywa reset po znaczeniu kolumny
    i przyłożenie jej nie nadpisuje; cztery pozostałe kolumny liczą się przy przyłożeniu. Potem ręka przeżywa także
    zwykłe przeładowanie. Falsyfikatory: zamówienie bez zdejmowania kolumny gestem; liczenie przy każdym
    przyłożeniu. (Strażnik resetu pilnuje test niżej - tu przyłożenie nie zmienia liczby kolumn, więc oddanie
    szerokości po znaczeniu nie rusza sekcji.)"""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    przed = v.table.columnWidth(v.model.base_col("night"))
    _przeciagnij_sekcje(v, "night", 160)
    reka = v.table.columnWidth(v.model.base_col("night"))
    assert reka > przed + 100, "gest ręki nie zmienił szerokości - test nie mierzy ręki"
    zapis = _szpieg_szerokosci(v)
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert v.table.columnWidth(v.model.base_col("night")) == reka
    assert [kl for kl, _n, _q in zapis] == [tuple(k for k in KLUCZE if k != "night")], zapis
    assert zapis[0][1] == zapis[0][2]
    bramy["pola"].set()
    _czekaj(lambda: v._pola_thread is None and not v.zbior_w_drodze())
    v.refresh()
    assert v.table.columnWidth(v.model.base_col("night")) == reka
    assert len(zapis) == 1


def test_przylozenie_z_nowa_kolumna_podgladu_liczy_szerokosci_mimo_oddania_po_znaczeniu(qapp, tmp_path, bramy):
    """Przebieg szuflady czekający przy otwarciu bazy (podjęty w konstruktorze) wnosi kolumnę podglądu przy
    pierwszym przyłożeniu zbioru - reset zmienia liczbę kolumn, a `_uloz_belki_i_wersje` oddaje szerokości po
    znaczeniu. Zamówienie zostaje i pięć kolumn liczy się jak `resizeColumnToContents`. (`QHeaderView::reset`
    zachowuje sekcje - qheaderview.cpp:1863-1866 - więc pięciu kolumnom Znajdź, które nie zmieniają pozycji, oddanie
    ustawia tę samą szerokość bez `sectionResized`; strażnik resetu chroni zamówienie na wypadek innej drogi.)
    Falsyfikator: brak liczenia przy przyłożeniu (zamówienie zgubione przy zmianie układu kolumn)."""
    from horreum import repo
    from horreum.gui.flows.znajdz_view import ZnajdzView
    con = db.open_db(str(tmp_path / "podglad.db"))
    _seed(con)
    lid = con.execute("SELECT id FROM location ORDER BY id LIMIT 1").fetchone()[0]
    repo.stage_pending(con, run_id="R", location_id=lid, keyword="TELESCOP", idx=0, op="set", old_value="RC8",
                       new_value="EQ6", new_type="str", new_comment=None, expected_header_hash=None)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    s = ZnajdzView(v)
    s.resize(1400, 800)
    s.show()
    QApplication.processEvents()
    try:
        assert v._run_id == "R", "przebieg szuflady niepodjęty - test nie mierzy kolumny podglądu"
        _wejscie_w_drodze(s, v)
        kolumny = v.model.columnCount()
        zapis = _szpieg_szerokosci(v)
        bramy["zbior"].set()
        _do_przylozenia(v)
        assert v.model._preview_col() is not None and v.model.columnCount() > kolumny
        assert [kl for kl, _n, _q in zapis] == [KLUCZE], zapis
        assert zapis[0][1] == zapis[0][2]
    finally:
        bramy["zbior"].set()
        bramy["pola"].set()
        v.zatrzymaj_pola()
        s.close()
        con.close()


def test_zastapione_zlecenie_przejmuje_zamowienie(w_drodze):
    """Wynik pól przychodzi PRZED zbiorem startu i przeładowuje zbiór (nowe kolumny, nowa generacja): zamówienie
    przechodzi na nowsze zlecenie - przyłożenie nowszego zbioru liczy pięć kolumn raz, jak `resizeColumnToContents`,
    i zamówienie zdejmuje. Falsyfikator: zamówienie gaśnie przy zastąpieniu (kolumny zostają przy podpowiedziach
    nagłówka z wejścia)."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    gen = v._zbior_gen
    zapis = _szpieg_szerokosci(v)
    bramy["pola"].set()
    _czekaj(lambda: v._zbior_gen > gen)
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert [kl for kl, _n, _q in zapis] == [KLUCZE], zapis
    assert zapis[0][1] == zapis[0][2] and v._szerokosci_zamowione is None


def test_zapytanie_w_oknie_w_drodze_przejmuje_zamowienie_a_reka_zdejmuje_kolumne(w_drodze):
    """Znajdź z Domu zaraz po otwarciu bazy: zbiór startu w drodze, człowiek wpisuje zapytanie i Enter, zanim zbiór
    dojedzie (nowe zlecenie, nowa generacja - zamówienie przechodzi na nie), a POTEM przeciąga uchwyt „Zestaw”.
    Przyłożenie zbioru zapytania liczy cztery kolumny jak `resizeColumnToContents`, a zestaw zostaje przy szerokości
    z ręki. Falsyfikatory: zamówienie gaśnie przy zastąpieniu (kolumny ucięte do nagłówka); gest ręki po przejęciu
    nie zdejmuje kolumny (zestaw nadpisany)."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    gen = v._zbior_gen
    zapis = _szpieg_szerokosci(v)
    QTest.keyClicks(s.pole, "m42")
    QTest.keyClick(s.pole, Qt.Key_Return)
    QApplication.processEvents()
    assert v._zbior_gen > gen and v.zbior_w_drodze(), "zapytanie miało zastąpić zbiór w drodze"
    _przeciagnij_sekcje(v, "_zestaw", 160)
    reka = v.table.columnWidth(v.model.base_col("_zestaw"))
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert sorted(v._frame_ids) == [1, 2], "przyłożony zbiór to nie zbiór zapytania"
    assert [kl for kl, _n, _q in zapis] == [tuple(k for k in KLUCZE if k != "_zestaw")], zapis
    assert zapis[0][1] == zapis[0][2]
    assert v.table.columnWidth(v.model.base_col("_zestaw")) == reka


def test_jedna_porazka_skladu_i_udane_ponowienie_licza_szerokosci_raz(w_drodze):
    """Skład zbioru startu pada RAZ (porażka nieterminalna - ponowienie w tle tej samej generacji) i ponowienie się
    udaje: zamówienie czeka na ponowiony zbiór, a jego przyłożenie liczy pięć kolumn raz, jak `resizeColumnToContents`.
    Falsyfikator: zamówienie gaszone już przy pierwszej porażce (przed `_ponow_zbior`) - noc zostaje przy
    podpowiedzi nagłówka."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    zapis = _szpieg_szerokosci(v)
    bramy["pada"] = 1
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert bramy["pada"] == 0, "skład nie padł - test nie mierzy ponowienia"
    assert [kl for kl, _n, _q in zapis] == [KLUCZE], zapis
    assert zapis[0][1] == zapis[0][2] and v._szerokosci_zamowione is None


def test_porazka_skladu_gasi_zamowienie(w_drodze):
    """Skład zbioru startu pada dwa razy (ponowienie w tle i zdanie porażki - zbiór, na który zamówienie czekało,
    nie przychodzi): zamówienie gaśnie i następne przeładowanie, dużo później, szerokości nie liczy. Falsyfikator:
    porażka terminalna bez zdjęcia zamówienia."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    zapis = _szpieg_szerokosci(v)
    bramy["pada"] = 2
    bramy["zbior"].set()
    _czekaj(lambda: not v.zbior_w_drodze() and bramy["pada"] == 0 and v._zbior_thread is None)
    assert v.model.rowCount() == 0
    v.refresh()
    assert v.model.rowCount() > 0 and zapis == [] and v._szerokosci_zamowione is None


def test_pusty_zbior_w_drodze_konsumuje_zamowienie(qapp, tmp_path, bramy):
    """Baza bez klatek: zbiór startu przychodzi pusty - przyłożenie liczy szerokości (podpowiedzi nagłówka, jak
    Qt) i zdejmuje zamówienie; następne przeładowanie już nie liczy. Falsyfikator: zamówienie zostawione po
    pustym przyłożeniu (liczy przy następnym zbiorze)."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    con = db.open_db(str(tmp_path / "pusta.db"))
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    s = ZnajdzView(v)
    try:
        s.show_find()
        assert v.zbior_w_drodze() and v._szerokosci_zamowione is not None
        zapis = _szpieg_szerokosci(v)
        bramy["zbior"].set()
        bramy["pola"].set()
        _czekaj(lambda: not v.zbior_w_drodze() and v._pola_thread is None)
        assert [kl for kl, _n, _q in zapis] == [KLUCZE] and zapis[0][1] == zapis[0][2]
        assert v._szerokosci_zamowione is None
        v.refresh()
        assert len(zapis) == 1
    finally:
        v.zatrzymaj_pola()
        s.close()
        con.close()


def test_wyjscie_do_klasycznej_przed_przylozeniem_gasi_zamowienie(w_drodze, monkeypatch):
    """Wejście w Znajdź w drodze, potem „Zbiory klasyczne” przed przyłożeniem: zamówienie schodzi przy wyjściu
    i przyłożenie w prezentacji klasycznej niczego nie liczy (bez błędu programu). Falsyfikator: zamówienie
    przeżywa wyjście - przyłożenie pyta o kolumnę „Noc”, której klasyczna nie ma (wyjątek ze slotu)."""
    s, v, bramy = w_drodze
    _wejscie_w_drodze(s, v)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    s.show_classic()
    assert v._szerokosci_zamowione is None
    bramy["zbior"].set()
    _do_przylozenia(v)
    assert wyjatki == [] and v.prezentacja == grid_mod.PREZENTACJA_KLASYCZNA
