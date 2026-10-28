"""AR-358: jedna reguła szerokości z treści dla każdej kolumny modelu Zbiorów (`grid_model.szerokosci_z_tresci`) -
ścieżka, podgląd klingi, „Wersja” i pięć kolumn Znajdź - zamiast przejścia Qt po `data()` (8000 wywołań na kolumnę:
1000 wierszy × 8 ról). Zmierzone natywnie na kopii pf4 (mediany 10 biegów): ścieżka 50,9 → 28,3 ms, podgląd nazw
41,1 → 15,4 ms, 0 różnic piksela widocznego w 1760 operacjach układu (PL i EN) wobec drogi Qt.

Równoważność z Qt sprawdzamy od TEGO SAMEGO stanu: owijki dróg produktu (`kolumna_z_tresci` i `szerokosc_z_tresci`
w przestrzeni nazw `grid`, instancyjna `_szerokosci_znajdz`) liczą drogą produktu, potem oddają tabeli stan sprzed
niej i liczą drogą Qt sprzed zmiany (`max(sizeHintForColumn, sectionSizeHint)`, `resizeColumnToContents`) - migawka
WSZYSTKICH sekcji nagłówka, także ostatniej rozciąganej. Offscreen pogrubienie, kursywa i zwykły tekst mają tę samą
metrykę, więc czcionki ról dostają tu WIĘKSZY rozmiar (inaczej pominięcie `FontRole` przeszłoby niezauważone); miarę
tekstu wobec Qt (`QTextLayout`, nie `horizontalAdvance`; znak nowej linii) pilnuje test natywny w podprocesie.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import horreum
from horreum import db
from horreum.gui import grid as grid_mod, grid_model

from test_gui_pola_w_tle import _klik_przycisku, _odczekaj_debounce
from test_gui_zaznaczenie_przebudowy import _klik_naglowka, pliki  # noqa: F401
from test_gui_znajdz_szerokosci import (_baza_1500, _grupuj, _przeciagnij_sekcje, _szpieg_szerokosci,  # noqa: F401
                                        kursywa_wieksza)

NOW = "2026-10-28T12:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _rozciagana(h):
    """Ostatnia sekcja wizualna przy `stretchLastSection` - jej szerokość dociąga Qt w układzie odłożonym nagłówka, więc
    migawka w trakcie resetu łapie stan przed dociągnięciem. Porównujemy ją liczbą (`szerokosc_z_tresci`), a stan
    widoczny po układzie zmierzyła sonda natywna (0 różnic, także „Wersja” ostatnia w Znajdź)."""
    return h.logicalIndex(h.count() - 1) if h.stretchLastSection() and h.count() else None


def _sekcje(t):
    h = t.horizontalHeader()
    pomin = _rozciagana(h)
    return [None if c == pomin else h.sectionSize(c) for c in range(h.count())]


def _oddaj(t, szerokosci):
    h = t.horizontalHeader()
    for c, w in enumerate(szerokosci):
        if w is not None and not h.isSectionHidden(c):
            t.setColumnWidth(c, w)


def _qt(t, col):
    """Droga Qt sprzed AR-358: większa z podpowiedzi treści i nagłówka po układzie odłożonym."""
    t.executeDelayedItemsLayout()
    return max(t.sizeHintForColumn(col), t.horizontalHeader().sectionSizeHint(col))


@pytest.fixture
def droga_qt(monkeypatch):
    """Owijki dróg produktu w przestrzeni nazw `grid` (wołane wprost, żadna nie jest slotem). Zapis
    `(droga, kolumna, produkt, qt)`: `kolumna_z_tresci` - migawka wszystkich sekcji po drodze produktu i po drodze Qt
    od tego samego stanu; `szerokosc_z_tresci` - liczba produktu wobec liczby Qt, a przy `sufit=None` („Wersja”, potem
    `setColumnWidth`) dodatkowo migawka po `setColumnWidth(produkt)` wobec `resizeColumnToContents`."""
    zapis = []
    kolumna_prawdziwa, szerokosc_prawdziwa = grid_mod.kolumna_z_tresci, grid_mod.szerokosc_z_tresci

    def kolumna_z_tresci(table, col, *, sufit=grid_model._SUFIT_KOLUMNY_Z_TRESCI):
        przed = _sekcje(table)
        wynik = kolumna_prawdziwa(table, col, sufit=sufit)
        produkt = _sekcje(table)
        _oddaj(table, przed)
        table.setColumnWidth(col, min(_qt(table, col), sufit))
        zapis.append(("kolumna_z_tresci", col, produkt, _sekcje(table)))
        _oddaj(table, produkt)
        return wynik

    def szerokosc_z_tresci(table, col, *, sufit=grid_model._SUFIT_KOLUMNY_Z_TRESCI):
        wynik = szerokosc_prawdziwa(table, col, sufit=sufit)
        qt = _qt(table, col)
        zapis.append(("szerokosc_z_tresci", col, wynik, qt if sufit is None else min(qt, sufit)))
        if sufit is None:
            przed = _sekcje(table)
            table.setColumnWidth(col, wynik)
            produkt = _sekcje(table)
            _oddaj(table, przed)
            table.resizeColumnToContents(col)
            zapis.append(("wersja_stan", col, produkt, _sekcje(table)))
            _oddaj(table, przed)
        return wynik
    monkeypatch.setattr(grid_mod, "kolumna_z_tresci", kolumna_z_tresci)
    monkeypatch.setattr(grid_mod, "szerokosc_z_tresci", szerokosc_z_tresci)
    return zapis


@pytest.fixture
def pogrubienie_wieksze(monkeypatch):
    """Czcionka podglądu (pogrubiona) 1,6× większa - i Qt (przez `data`), i reguła modelu czytają tę samą metodę."""
    prawdziwa = grid_model.GridTableModel._preview_cell

    def _preview_cell(self, row, role):
        wynik = prawdziwa(self, row, role)
        if role == Qt.FontRole and isinstance(wynik, QFont):
            wynik.setPointSizeF(QApplication.font().pointSizeF() * 1.6)
        return wynik
    monkeypatch.setattr(grid_model.GridTableModel, "_preview_cell", _preview_cell)


@pytest.fixture
def wersja_dluga(monkeypatch):
    """Komórka „Wersja” szersza niż sufit kolumn z treści - fakty wersji bez stosów w bazie testu (atrapa treści)."""
    prawdziwa = grid_model.GridTableModel._version_cell

    def _version_cell(self, row, role):
        if role == Qt.DisplayRole:
            return "inna integracja · " + "W" * (40 + row.get("frame_id", 0) % 7)
        return prawdziwa(self, row, role)
    monkeypatch.setattr(grid_model.GridTableModel, "_version_cell", _version_cell)


@pytest.fixture
def widok1500(qapp, tmp_path):
    """Strona zbiorów nad bazą 1500 klatek (więcej niż precyzja Qt) - grid w kontenerze Znajdź, prezentacja klasyczna,
    bez wątków tła."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    sciezka = str(tmp_path / "w1500.db")
    _baza_1500(sciezka)
    con = db.connect(sciezka)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    s = ZnajdzView(v)
    s.resize(1500, 900)
    s.show()
    QApplication.processEvents()
    yield s, v
    v.zatrzymaj_pola()
    s.close()
    con.close()


def _kadr(v, kadr):
    t = v.table
    if kadr == "srodek":
        sb = t.verticalScrollBar()
        sb.setValue(sb.maximum() // 2)
    else:
        t.scrollToTop()
    QApplication.processEvents()


def _podglad_nazw(v):
    _klik_przycisku(v.sel_bar.btn_rename)
    QTest.keyClick(v.table, Qt.Key_A, Qt.ControlModifier)
    _klik_przycisku(v.rename_bar.btn_prev)
    assert v.model._preview_active(), "podgląd nazw nie stanął - test nie mierzy kolumny podglądu"


def _rowne(zapis):
    assert zapis, "żadna droga szerokości z treści nie pobiegła - test nie mierzy reguły"
    rozne = []
    for d, c, p, q in zapis:
        if isinstance(p, list):
            rozne += [(d, c, i, a, b) for i, (a, b) in enumerate(zip(p, q)) if a != b]
        elif p != q:
            rozne.append((d, c, p, q))
    assert not rozne, rozne


def test_sort_przy_podgladzie_nazw_bez_przejscia_qt_po_kolumnie_podgladu(widok1500, monkeypatch):
    """1500 wierszy, podgląd nazw stawiany prawdziwym klikiem „Podgląd”, potem prawdziwy klik w sekcję nagłówka
    (sort - reset modelu przy stojącym podglądzie): do powrotu kliku model pytany o kolumnę podglądu mniej niż 100
    razy przy każdym z dwóch gestów (droga Qt - 8000). Falsyfikator: reguła modelu zdjęta z `szerokosc_z_tresci`."""
    _s, v = widok1500
    m = v.model
    _klik_przycisku(v.sel_bar.btn_rename)
    QTest.keyClick(v.table, Qt.Key_A, Qt.ControlModifier)
    licz = [0]
    prawdziwe = grid_model.GridTableModel.data

    def _data(self, index, role=Qt.DisplayRole):
        if index.isValid() and index.column() == self._preview_col():
            licz[0] += 1
        return prawdziwe(self, index, role)
    monkeypatch.setattr(grid_model.GridTableModel, "data", _data)
    QTest.mouseClick(v.rename_bar.btn_prev, Qt.LeftButton)
    klik_podgladu = licz[0]
    QApplication.processEvents()
    assert m._preview_active() and m._preview_col() is not None
    h = v.table.horizontalHeader()
    kolumna = m.base_col("kind")
    x = h.sectionViewportPosition(kolumna) + h.sectionSize(kolumna) // 2
    licz[0] = 0
    QTest.mouseClick(h.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, h.height() // 2))
    klik_naglowka = licz[0]
    QApplication.processEvents()
    assert m.sort_column() == kolumna, "klik w nagłówek nie posortował - test nie mierzy resetu przy podglądzie"
    assert klik_podgladu < 100 and klik_naglowka < 100, (klik_podgladu, klik_naglowka)


@pytest.mark.parametrize("kadr", ["gora", "srodek"])
@pytest.mark.parametrize("grupa", [None, "_object"])
def test_szerokosci_podgladu_nazw_jak_droga_qt(widok1500, droga_qt, pogrubienie_wieksze, kursywa_wieksza, grupa,
                                               kadr):
    """Podgląd nazw (pogrubiony) i sort przy nim: każda szerokość kolumny podglądu i ścieżki = droga Qt od tego samego
    stanu, każda sekcja nagłówka. Falsyfikatory: czcionka `FontRole` pominięta w regule modelu; układ odłożony zdjęty
    z `szerokosc_z_tresci`."""
    _s, v = widok1500
    if grupa:
        _grupuj(v, grupa)
    _kadr(v, kadr)
    _podglad_nazw(v)
    _klik_naglowka(v, v.model.base_col("kind"))
    assert any(d == "kolumna_z_tresci" and c == v.model._preview_col() for d, c, _p, _q in droga_qt)
    _rowne(droga_qt)


@pytest.mark.parametrize("kadr", ["gora", "srodek"])
@pytest.mark.parametrize("grupa", [None, "_object", "camera_model"])
def test_szerokosci_znajdz_i_wersji_jak_droga_qt(widok1500, droga_qt, kursywa_wieksza, wersja_dluga, grupa, kadr):
    """Znajdź (pięć kolumn z treści) i „Kolumny ▾ → Wersja” - „Wersja” stoi wtedy OSTATNIA i rozciąga się do kadru,
    a jej treść jest szersza niż sufit: pięć kolumn = pięć `resizeColumnToContents`, „Wersja” bez sufitu = droga Qt,
    a stan końcowy po `setColumnWidth` = stan po `resizeColumnToContents` (każda sekcja). Falsyfikatory: sufit
    na „Wersji”; reguła spanu belki zdjęta (grupa „Kamera” - span aktywny)."""
    s, v = widok1500
    if grupa:
        _grupuj(v, grupa)
    _kadr(v, kadr)
    znajdz = _szpieg_szerokosci(v)
    s.show_find()
    QApplication.processEvents()
    v._on_version_col(True)
    QApplication.processEvents()
    assert v.model._version_col() is not None
    assert znajdz and all(nasze == qt for _kl, nasze, qt in znajdz), znajdz
    wersja = [(d, p, q) for d, c, p, q in droga_qt if c == v.model._version_col() and d == "szerokosc_z_tresci"]
    assert wersja and all(p > grid_model._SUFIT_KOLUMNY_Z_TRESCI for _d, p, _q in wersja), wersja
    _rowne(droga_qt)


def test_sufit_kolumny_z_tresci_dla_modelu_gridu(widok1500, wersja_dluga):
    """Kolumna modelu gridu szersza niż sufit: `szerokosc_z_tresci` = sufit, `sufit=None` - droga Qt bez sufitu.
    Falsyfikator: `min` z sufitem zdjęty albo przyłożony przy `sufit=None`."""
    s, v = widok1500
    s.show_find()
    v._on_version_col(True)
    QApplication.processEvents()
    t, kol = v.table, v.model._version_col()
    qt = _qt(t, kol)
    assert qt > grid_model._SUFIT_KOLUMNY_Z_TRESCI
    assert grid_model.szerokosc_z_tresci(t, kol) == grid_model._SUFIT_KOLUMNY_Z_TRESCI
    assert grid_model.szerokosc_z_tresci(t, kol, sufit=None) == qt


def test_ten_sam_tekst_w_dwoch_czcionkach_jednej_kolumny(qapp, kursywa_wieksza):
    """Jedna kolumna, ten sam tekst w dwóch czcionkach: zwykła (kanon obiektu) i większa kursywa (zeznanie nagłówka),
    na przemian od pierwszego wiersza, który Qt bierze - reguła modelu = droga Qt. Falsyfikator: pamięć szerokości
    w wywołaniu z kluczem bez czcionki (kursywa dostaje szerokość zwykłej, zmierzonej pierwszą)."""
    from PySide6.QtWidgets import QTableView
    from horreum import pivot as pivot_mod
    wiersze = [{"frame_id": i + 1, "path": f"X:/L/a{i}.fits", "kind": "light", "present": 1, "n_present": 1,
                "_object": "NGC 7000 Pelikan"} for i in range(10)]
    m = grid_model.GridTableModel()
    m.set_base_columns(grid_model.FIND_COLS, version_col=False)
    m.set_data(wiersze, pivot_mod.build_pivot([w["frame_id"] for w in wiersze], [], []), [])
    for r, row in enumerate(m._rows):
        row["_object_state"] = "canon" if r % 2 == 0 else "raw"
    t = QTableView()
    t.setModel(m)
    kol = m.base_col("_object")
    zwykla, kursywa = m.data(m.index(0, kol), Qt.FontRole), m.data(m.index(1, kol), Qt.FontRole)
    assert zwykla is None and kursywa is not None and kursywa.pointSizeF() > QApplication.font().pointSizeF()
    assert grid_model.szerokosci_z_tresci(t, [kol]) == [_qt(t, kol)]


def _baza_kopii(sciezka, n=1500, dlugie=300):
    """`n` klatek, każda z dwiema obecnymi kopiami (perspektywa „Duplikaty”); porządek startowy - ścieżka malejąco,
    więc `dlugie` klatek o dłuższej nazwie („z_…”) stoi w pierwszych wierszach. Reguła Qt bierze 1000 wierszy od kadru:
    u góry widzi dłuższe nazwy, przewinięta na dół - już nie."""
    con = db.open_db(sciezka)
    klatki, naglowki, lokacje = [], [], []
    for i in range(1, n + 1):
        nazwa = f"z_dluga_{i:05d}.fits" if i <= dlugie else f"f_{i:05d}.fits"
        klatki.append((i, f"d{i}", "light", "fits", NOW))
        naglowki.append((i, "{}"))
        lokacje += [(i, "V", f"/a/{nazwa}", 1), (i, "W", f"/a/{nazwa}", 1)]
    con.executemany("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)", klatki)
    con.executemany("INSERT INTO header (frame_id, raw_json) VALUES (?,?)", naglowki)
    con.executemany("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)", lokacje)
    con.commit()
    con.close()


def test_zapis_perspektywy_nie_zapisuje_szerokosci_programowej_po_przewinieciu(qapp, tmp_path, droga_qt):
    """Duplikaty (szerokość ścieżki z treści, AR-36): auto-szerokość u góry, przewinięcie na dół (reguła Qt bierze inne
    1000 wierszy i dałaby węższą kolumnę), zapis perspektywy - BEZ szerokości ścieżki (to szerokość programu, nie ręki);
    przeciągnięcie uchwytu o 1 px - szerokość zapisana. Falsyfikatory: zapis porównujący z rachunkiem w bieżącym kadrze;
    pamięć szerokości zastosowanej nieustawiana w `_uloz_kolumny`."""
    sciezka = str(tmp_path / "kopie.db")
    _baza_kopii(sciezka)
    con = db.connect(sciezka)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    v.resize(1400, 800)
    v.show()
    QApplication.processEvents()
    try:
        v.apply_perspective(grid_mod.PRESET_DUPS)
        QApplication.processEvents()
        t, m = v.table, v.model
        assert m.rowCount() == 1500
        kol = m.base_col("path")
        u_gory = t.columnWidth(kol)
        assert u_gory == min(_qt(t, kol), grid_model._SUFIT_KOLUMNY_Z_TRESCI)
        t.scrollToBottom()
        QApplication.processEvents()
        assert _qt(t, kol) < u_gory, "kadr nie zmienia reguły Qt - test nie mierzy przewinięcia"
        assert grid_model._SPEC_SZEROKOSC_SCIEZKI not in v._wyglad_do_zapisu()
        _przeciagnij_sekcje(v, "path", 1)
        assert t.columnWidth(kol) == u_gory + 1, "gest ręki nie zmienił szerokości o 1 px"
        assert v._wyglad_do_zapisu()[grid_model._SPEC_SZEROKOSC_SCIEZKI] == u_gory + 1
        _rowne(droga_qt)
    finally:
        v.zatrzymaj_pola()
        v.close()
        con.close()


@pytest.fixture
def kopie_znajdz(qapp, tmp_path):
    """Strona zbiorów (grid w kontenerze Znajdź) nad bazą 60 klatek z dwiema kopiami, perspektywa „Duplikaty”."""
    from horreum.gui.flows.znajdz_view import ZnajdzView
    sciezka = str(tmp_path / "kopie60.db")
    _baza_kopii(sciezka, n=60, dlugie=10)
    con = db.connect(sciezka)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    s = ZnajdzView(v)
    s.resize(1400, 800)
    s.show()
    QApplication.processEvents()
    v.apply_perspective(grid_mod.PRESET_DUPS)
    QApplication.processEvents()
    yield s, v
    v.zatrzymaj_pola()
    s.close()
    con.close()


def test_znajdz_sciezka_ostatnia_po_sorcie_bez_zapisu_szerokosci(kopie_znajdz):
    """Znajdź z perspektywą „Duplikaty”: „Plik” stoi OSTATNI i rozciąga się do kadru; po sorcie (prawdziwy klik
    nagłówka) zapis perspektywy nie niesie szerokości ścieżki - rozciągnięta nie jest wyborem ręki. Falsyfikator: zapis
    porównujący szerokość ostatniej sekcji z szerokością zastosowaną."""
    s, v = kopie_znajdz
    s.show_find()
    QApplication.processEvents()
    kol = v.model.base_col("path")
    assert v._ostatnia_widoczna_sekcja() == kol and v._sciezka_z_tresci is not None
    _klik_naglowka(v, v.model.base_col("_object"))
    assert v.table.columnWidth(kol) != v._sciezka_z_tresci, "ścieżka nie rozciągnięta - test nie mierzy reguły"
    assert grid_model._SPEC_SZEROKOSC_SCIEZKI not in v._wyglad_do_zapisu()


def test_podglad_za_sciezka_ostatnia_oddaje_jej_szerokosc_z_tresci(kopie_znajdz):
    """Znajdź z „Duplikatami”: podgląd klingi staje za „Plikiem” (reset modelu bez nowego zbioru) - ścieżka przestaje
    być ostatnia, a migawka sprzed resetu jej nie niosła (była rozciągana). Ścieżka dostaje szerokość zastosowaną
    z treści, nie domyślną, i zapis jej nie niesie. Falsyfikator: oddanie szerokości po znaczeniu bez ścieżki z treści
    (ścieżka 100 px, zapis bierze to za wybór ręki)."""
    s, v = kopie_znajdz
    s.show_find()
    QApplication.processEvents()
    m, kol = v.model, v.model.base_col("path")
    assert v._ostatnia_widoczna_sekcja() == kol
    zastosowana = v._sciezka_z_tresci
    fid = next(r["frame_id"] for r in m._rows if "_group" not in r)
    m.set_preview({fid: {"op": "rename", "old": "a.fits", "new": "b.fits"}}, label="podgląd")
    QApplication.processEvents()
    assert v._ostatnia_widoczna_sekcja() != kol, "ścieżka dalej ostatnia - test nie mierzy oddania"
    assert zastosowana != v.table.horizontalHeader().defaultSectionSize()
    assert v.table.columnWidth(kol) == zastosowana
    assert grid_model._SPEC_SZEROKOSC_SCIEZKI not in v._wyglad_do_zapisu()


def test_klasyczna_sort_bez_zapisu_a_reka_zapisuje(kopie_znajdz):
    """Klasyczna z „Duplikatami” (ścieżka nie ostatnia): sort prawdziwym klikiem nagłówka - zapis bez szerokości
    ścieżki; przeciągnięcie uchwytu ścieżki o 1 px - szerokość zapisana. Falsyfikator: oddanie po sorcie innej
    szerokości niż zastosowana."""
    s, v = kopie_znajdz
    s.show_classic()
    QApplication.processEvents()
    kol = v.model.base_col("path")
    assert v._ostatnia_widoczna_sekcja() != kol
    _klik_naglowka(v, v.model.base_col("kind"))
    assert grid_model._SPEC_SZEROKOSC_SCIEZKI not in v._wyglad_do_zapisu()
    szer = v.table.columnWidth(kol)
    _przeciagnij_sekcje(v, "path", 1)
    assert v._wyglad_do_zapisu()[grid_model._SPEC_SZEROKOSC_SCIEZKI] == szer + 1


def test_klasyczna_gest_reki_na_sciezce_przezywa_sort(kopie_znajdz):
    """Klasyczna z „Duplikatami”: gest ręki na ścieżce (uchwyt o 15 px), potem sort prawdziwym klikiem nagłówka - reset
    modelu bez nowego zbioru oddaje ścieżce szerokość z migawki, czyli tę z gestu, a zapis perspektywy ją niesie.
    Falsyfikator: reset nadpisujący migawkę pamięcią szerokości zastosowanej przez program (gest ginie przy sorcie)."""
    s, v = kopie_znajdz
    s.show_classic()
    QApplication.processEvents()
    t, kol = v.table, v.model.base_col("path")
    assert v._ostatnia_widoczna_sekcja() != kol and v._sciezka_z_tresci is not None
    reka = t.columnWidth(kol) + 15
    _przeciagnij_sekcje(v, "path", 15)
    assert t.columnWidth(kol) == reka != v._sciezka_z_tresci, "gest ręki nie zmienił szerokości ścieżki"
    _klik_naglowka(v, v.model.base_col("kind"))
    assert t.columnWidth(kol) == reka
    assert v._wyglad_do_zapisu()[grid_model._SPEC_SZEROKOSC_SCIEZKI] == reka


def test_znajdz_sciezka_ostatnia_przy_przepelnieniu_zapisuje_gest(kopie_znajdz):
    """Znajdź z „Duplikatami”: „Plik” stoi ostatni, ale nagłówek jest przepełniony w poziomie (inna kolumna szersza niż
    kadr) - `stretchLastSection` nie ma czego dociągać, więc ostatnia sekcja niesie własną szerokość, a gest ręki na
    niej (uchwyt o 7 px) zapis perspektywy niesie. Falsyfikator: każda ostatnia widoczna sekcja liczona jak
    rozciągnięta."""
    s, v = kopie_znajdz
    s.show_find()
    QApplication.processEvents()
    t, kol = v.table, v.model.base_col("path")
    h = t.horizontalHeader()
    assert v._ostatnia_widoczna_sekcja() == kol
    t.setColumnWidth(v.model.base_col("_object"), h.viewport().width() + 400)
    QApplication.processEvents()
    assert h.length() > h.viewport().width(), "nagłówek nie przepełniony - test nie mierzy reguły"
    t.horizontalScrollBar().setValue(t.horizontalScrollBar().maximum())
    QApplication.processEvents()
    przed = t.columnWidth(kol)
    _przeciagnij_sekcje(v, "path", 7)
    assert t.columnWidth(kol) == przed + 7, "gest ręki nie zmienił szerokości ostatniej sekcji"
    assert v._wyglad_do_zapisu()[grid_model._SPEC_SZEROKOSC_SCIEZKI] == przed + 7


def test_po_zapisie_szuflady_szerokosci_i_cofnij(pliki, droga_qt, pogrubienie_wieksze, monkeypatch):
    """Prawdziwy zapis szuflady (karty z podglądem ze stagingu przy „Grupuj wg: Obiekt”, zapis do plików inline):
    szerokość kolumny podglądu przy stagingu = droga Qt, a ogon zapisu (`_after_commit` - przeładowanie z belkami przez
    rozdział komórki modelu) kończy się raportem i „Cofnij”, bez wyjątku ze slotu; każda szerokość z treści policzona
    po drodze = droga Qt. Pin szwu reguły szerokości z ogonem zapisu."""
    view, _tmp = pliki
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    zdania = []
    view.status_message.connect(zdania.append)
    _grupuj(view, "_object")
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)
    assert view._pending_count() > 0 and view.model._preview_active()
    assert any(d == "kolumna_z_tresci" and c == view.model._preview_col() for d, c, _p, _q in droga_qt)
    zdania.clear()
    _klik_przycisku(view.drawer.btn_commit)
    _odczekaj_debounce()
    QApplication.processEvents()
    assert wyjatki == []
    assert zdania, "raport po zapisie nie padł"
    assert view._undo_btn.isVisible() and view._undo_btn.isEnabled()
    assert any("_group" in r for r in view.model._rows), "przeładowanie po zapisie zgubiło grupowanie"
    _rowne(droga_qt)


# ---------------------------------------------------------------- natywnie: miara tekstu wobec Qt

_SKRYPT_NATYWNY = r'''
import json, math, os, sys
korzen, tmp = sys.argv[1], sys.argv[2]
sys.path.insert(0, korzen)
import faulthandler
faulthandler.dump_traceback_later(90, exit=True)
from PySide6.QtCore import QSettings
_ini = QSettings.__init__
QSettings.__init__ = lambda self, *a, **k: _ini(self, os.path.join(tmp, "ustawienia.ini"), QSettings.Format.IniFormat)
from PySide6.QtGui import QFontMetricsF, QTextLayout
from PySide6.QtWidgets import QApplication, QStyle, QTableView
app = QApplication([])
import horreum
from horreum import pivot as pivot_mod
from horreum.gui import grid_model as gm
NAZWY = ([f"Obiekt{k}_2023-08-{10 + k % 20:02d}_76EDPH_2600MC_NoFilter_"
          f"{60 * (1 + k % 9)}s_RGB_autocrop_WBPP{k % 4}.xisf" for k in range(40)]
         + [f"NGC{1000 + k}_2024-07-04_RC8_2600MM_Ha_300s_mono_WBPP_FLATGRP{k % 9}_{'x' * (k % 30)}.xisf"
            for k in range(40)])
WIELOWIERSZOWE = ["krótka\nbardzo długa druga linia tekstu", "Linia jeden\nLinia dwa dłuższa niż pierwsza",
                  "NGC 7000\nPelikan · Ha 3 nm", "x" * 30 + "\n" + "y" * 10, "RC8 · ASI2600MM\n2024-03-15 i dalej"]
wiersze = []
for i in range(len(NAZWY)):
    wiersze.append({"frame_id": i + 1, "path": f"X:/L/a{i}.fits", "kind": "light", "present": 1, "n_present": 1,
                    "_object": NAZWY[i], "_object_state": "canon", "night": f"2024-07-{1 + i % 28:02d}",
                    "filter_canon": "Ha" if i % 2 else "OIII", "exptime": 300.0 + i, "note": "",
                    "_zestaw": WIELOWIERSZOWE[i % len(WIELOWIERSZOWE)]})
m = gm.GridTableModel()
m.set_base_columns(gm.FIND_COLS, version_col=False)
m.set_data(wiersze, pivot_mod.build_pivot([w["frame_id"] for w in wiersze], [], []), [])
t = QTableView()
t.setModel(m)
klucze = ("_object", "night", "filter_canon", "exptime", "_zestaw")
kolumny = [m.base_col(k) for k in klucze]
nasze = gm.szerokosci_z_tresci(t, kolumny)
qt = [max(t.sizeHintForColumn(c), t.horizontalHeader().sectionSizeHint(c)) for c in kolumny]
czcionka = t.font()
margines = (2 * (t.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, t) + 1)
            + (1 if t.showGrid() else 0))

def bez_zamiany(tekst):
    uklad = QTextLayout(tekst, czcionka)
    uklad.setTextOption(gm._OPCJA_LINII)
    uklad.beginLayout()
    s = 0.0
    while True:
        ln = uklad.createLine()
        if not ln.isValid():
            break
        ln.setLineWidth(gm._LINIA_BEZ_KONCA)
        s = max(s, ln.naturalTextWidth())
    uklad.endLayout()
    return math.ceil(s)

fm = QFontMetricsF(czcionka)
adv_obiektu = max(math.ceil(fm.horizontalAdvance(x)) for x in NAZWY) + margines
bez_zamiany_zestawu = max(bez_zamiany(x) for x in WIELOWIERSZOWE) + margines
print("JSON " + json.dumps({"horreum": horreum.__file__, "nasze": nasze, "qt": qt, "adv_obiektu": adv_obiektu,
                            "bez_zamiany_zestawu": bez_zamiany_zestawu}), flush=True)
os._exit(0)
'''


@pytest.mark.skipif(sys.platform != "win32", reason="miara tekstu natywnej platformy Windows")
def test_miara_tekstu_jak_qt_natywnie(tmp_path):
    """Podproces na platformie natywnej (`QT_QPA_PLATFORM=windows`, bez okna - tabela niepokazana): model gridu
    z pięcioma kolumnami Znajdź, długie nazwy obiektów i teksty wielowierszowe w kolumnie zestawu - reguła modelu =
    `max(sizeHintForColumn, sectionSizeHint)` każdej kolumny. Świadkowie niepustości z tego samego biegu: najszersza
    nazwa miarą `horizontalAdvance` i najszerszy tekst wielowierszowy bez zamiany znaku nowej linii dają inną liczbę
    niż Qt - test rozróżnia obie miary. Falsyfikatory: miara `horizontalAdvance`; zamiana znaku nowej linii zdjęta."""
    korzen = Path(horreum.__file__).resolve().parents[1]
    skrypt = tmp_path / "miara.py"
    skrypt.write_text(_SKRYPT_NATYWNY, encoding="utf-8", newline="\n")
    p = subprocess.run([sys.executable, "-X", "faulthandler", str(skrypt), str(korzen), str(tmp_path)],
                       env=dict(os.environ, QT_QPA_PLATFORM="windows"), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    linia = next((x for x in reversed(p.stdout.splitlines()) if x.startswith("JSON ")), None)
    assert linia, p.stdout[-2000:] + p.stderr[-2000:]
    wynik = json.loads(linia[5:])
    assert Path(wynik["horreum"]).resolve().parents[1] == korzen
    assert wynik["nasze"] == wynik["qt"], wynik
    assert wynik["adv_obiektu"] != wynik["qt"][0], wynik
    assert wynik["bez_zamiany_zestawu"] != wynik["qt"][4], wynik
