"""Zaznaczenie przeżywa reset modelu BEZ NOWYCH DANYCH (AR-187) - testy sterujące realnym oknem Qt.

Sort klikiem w nagłówek, „Grupuj wg”, podgląd klingi i jego zdjęcie, przełączenie prezentacji
przebudowują te same wiersze, a reset zdejmował zaznaczenie po cichu: zero `selectionChanged`, licznik
paska dalej mówił „2 zaznaczone”, panel „Rodowód” pokazywał stos, którego nikt już nie zaznaczał
(sonda na HEAD: `[3, 10]` → `[]`). Zapis i cofnięcie szuflady przeładowują ten sam zbiór, a szły
drogą nawigacyjną. Kliki prawdziwe (`QTest.mouseClick` na widżecie), czekanie pętlą zdarzeń."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, pivot as pivot_mod
from horreum.gui import grid as grid_mod, i18n
from test_gui_pola_w_tle import (NOW, _baza_ze_stosem, _biezaca, _klik_komorki, _klik_listy_panelu,
                                 _klik_przycisku, _odczekaj_debounce, _wybierz_w_combo, _zaznaczone)


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _klik_naglowka(view, kolumna):
    """Prawdziwy klik myszą w środek sekcji nagłówka - droga `setSortingEnabled` → `model.sort`."""
    h = view.table.horizontalHeader()
    QApplication.processEvents()
    x = h.sectionViewportPosition(kolumna) + h.sectionSize(kolumna) // 2
    assert 0 <= x < h.viewport().width(), "sekcja poza kadrem nagłówka"
    QTest.mouseClick(h.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, h.height() // 2))
    QApplication.processEvents()


def _kolejnosc(view):
    return [r["frame_id"] for r in view.model._rows if "_group" not in r]


@pytest.fixture
def stos(qapp, tmp_path):
    """Widok bez wątków tła nad lightami 1-3 i stosem 10 (rodowód z lightów 1, 2). Zaznaczenie
    myszą: stos 10, Ctrl+klik light 3 w kolumnie 2 (bieżący wiersz nie jest pierwszym zaznaczonym,
    kolumna nie jest 0), panel „Rodowód” otwarty z wierszem 2 zaznaczonym na liście."""
    con = db.connect(_baza_ze_stosem(tmp_path))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view.resize(1400, 800)
    view.show()
    QApplication.processEvents()
    _klik_komorki(view, 10, 1)
    _klik_komorki(view, 3, 2, Qt.ControlModifier)
    _klik_przycisku(view.sel_bar.btn_lineage)
    _odczekaj_debounce()
    assert view._lineage_panel_open()
    _klik_listy_panelu(view.lineage_bar.items, 2)
    assert _zaznaczone(view) == [3, 10] and view.lineage_bar.selected_frame_ids() == [2]
    yield view
    view.close()
    con.close()


def test_sort_klikiem_w_naglowek_zaznaczenie_biezaca_licznik_i_panel_zostaja(stos):
    """Dwa kliki w „Ścieżkę” (rosnąco, malejąco) - kolejność wierszy realnie się zmienia, a zostają:
    zaznaczenie, bieżąca komórka po klatce i znaczeniu kolumny, licznik paska zgodny z zaznaczeniem
    i wiersz listy panelu. Falsyfikatory: bez połączenia `modelReset` → `_zaznaczenie_po_resecie`
    (zaznaczenie puste, licznik kłamie „2 zaznaczone”); bez `_date_timer.stop()` (panel przebudowany
    bez wiersza listy)."""
    view = stos
    przed, biezaca = _kolejnosc(view), _biezaca(view)
    sciezka = view.model.base_col("path")
    for _ in range(2):
        _klik_naglowka(view, sciezka)
        assert _kolejnosc(view) != przed, "sort nie zmienił kolejności - test nic by nie mierzył"
        przed = _kolejnosc(view)
        assert _zaznaczone(view) == [3, 10]
        assert _biezaca(view) == biezaca
        assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 2))
    _odczekaj_debounce()
    assert view.lineage_bar.selected_frame_ids() == [2]


@pytest.mark.parametrize("klucz", [k for _l, k in grid_mod.BASE_COLS if k != "path"] + [None])
def test_grupuj_wg_kazdy_klucz_i_powrot_bez_grupowania(stos, klucz):
    """Każda pozycja „Grupuj wg” przegrupowuje model sama, bez SQL (`set_group_by`), i każda - także
    powrót do „bez grupowania” - zostawia zaznaczenie i bieżącą komórkę; belki grup nie są klatkami,
    więc żaden zakres zaznaczenia ich nie obejmuje. „Wersja stosu” idzie przeładowaniem zbioru
    (AR-172, `test_gui_pola_w_tle`). Falsyfikator: migawka brana w `modelReset` zamiast
    `modelAboutToBeReset` (model już przebudowany - zaznaczenie puste)."""
    view = stos
    biezaca = _biezaca(view)
    if klucz is None:
        _wybierz_w_combo(view.combo_group, "kind")
        assert any("_group" in r for r in view.model._rows)
    _wybierz_w_combo(view.combo_group, klucz)
    assert view.model._group_by == klucz
    assert _zaznaczone(view) == [3, 10]
    assert _biezaca(view) == biezaca
    numery = set()
    for zakres in view.table.selectionModel().selection():
        numery.update(range(zakres.top(), zakres.bottom() + 1))
    assert not [i for i in numery if "_group" in view.model._rows[i]]
    _odczekaj_debounce()
    assert view.lineage_bar.selected_frame_ids() == [2]


def test_zmiana_zaznaczenia_tuz_przed_sortem_panel_odswieza_sie_z_wyborem(stos):
    """Debounce paneli czeka (Ctrl+klik lightu 2 tuż przed kliknięciem w nagłówek - panel jeszcze
    nie odbił nowego zaznaczenia), a reset przychodzi w tym oknie: panel odświeża się od razu dla
    zaznaczenia po resecie i z wyborem w panelu z migawki - wiersz listy zostaje. Falsyfikator:
    gałąź „czekał” bez `_refresh_lineage(**panel)` (debounce przebudowuje listę bez wiersza)."""
    view = stos
    _klik_komorki(view, 2, 2, Qt.ControlModifier)
    assert view._date_timer.isActive(), "debounce czeka - test mierzy tę gałąź"
    _klik_naglowka(view, view.model.base_col("path"))
    assert _zaznaczone(view) == [2, 3, 10]
    _odczekaj_debounce()
    assert view.lineage_bar.selected_frame_ids() == [2]


@pytest.mark.parametrize("gest", ["sort", "grupowanie"])
def test_pelne_zaznaczenie_wraca_po_sorcie_i_grupowaniu(stos, gest):
    """Ctrl+A (prawdziwy klawisz) i sort klikiem albo „Grupuj wg”: wraca CAŁE zaznaczenie, licznik
    paska je liczy, bieżąca komórka stoi na tej samej klatce, panel „Rodowód” zostaje przy jedynym
    obrazie zaznaczenia (stos 10) z wyborem na liście, a pasek nie mówi nic o zdjęciu - progu kosztu nie
    ma (AR-202: zdarzenie dostępności z zakresów, `_TabelaKlatek`). Falsyfikator: próg wierszy
    w `_zaznaczenie_po_resecie` (zaznaczenie puste po geście, panel bez stosu)."""
    view = stos
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    QApplication.processEvents()
    assert _zaznaczone(view) == [1, 2, 3, 10]
    _odczekaj_debounce()
    _klik_listy_panelu(view.lineage_bar.items, 2)
    assert view._lineage_frame_id == 10 and view.lineage_bar.selected_frame_ids() == [2]
    biezaca = _biezaca(view)
    zdania = []
    view.status_message.connect(zdania.append)
    if gest == "sort":
        _klik_naglowka(view, view.model.base_col("path"))
    else:
        _wybierz_w_combo(view.combo_group, "kind")
        assert any("_group" in r for r in view.model._rows)
    _odczekaj_debounce()
    assert _zaznaczone(view) == [1, 2, 3, 10]
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 4))
    assert _biezaca(view) == biezaca
    assert view._lineage_frame_id == 10 and view.lineage_bar.selected_frame_ids() == [2]
    assert zdania == []


def test_przeladowanie_nawigacyjne_dalej_zdejmuje_zaznaczenie(stos):
    """Granica reguły: nowy zbiór (klik facetu w listwie) to nawigacja - zaznaczenie znika, jak
    przed AR-187. Falsyfikator: `reset_tych_samych_wierszy()` zawsze `True` (reset `set_data`
    dostaje migawkę i zaznaczenie wraca)."""
    view = stos
    lw = view.facet_rail._lists["kind"]
    it = next(lw.item(i) for i in range(lw.count())
              if lw.item(i).data(Qt.UserRole) and lw.item(i).data(Qt.UserRole)[1] == "light")
    lw.scrollToItem(it)
    QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(it).center())
    QApplication.processEvents()
    assert sorted(view._frame_ids) == [1, 2, 3]
    assert _zaznaczone(view) == []


def test_reset_lokalny_a_nowe_dane_w_modelu():
    """Model mówi, czy trwający reset przebudowuje te same wiersze: tak przy sorcie, grupowaniu,
    podglądzie i prezentacji, nie przy `set_data` - i znów tak po nim. Falsyfikator: flaga
    `_nowe_wiersze` bez `finally` albo bez zdjęcia po `set_data`."""
    m = grid_mod.GridTableModel()
    widziane = []
    m.modelAboutToBeReset.connect(lambda: widziane.append(m.reset_tych_samych_wierszy()))
    base = [{"frame_id": i, "path": f"/a/{i}.fits", "kind": "light"} for i in (1, 2)]
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [])
    assert widziane == [False]
    m.sort(0, Qt.DescendingOrder)
    m.set_group_by("kind")
    m.set_preview({1: {"skipped": "x"}})
    m.set_preview({})
    m.set_base_columns(grid_mod.FIND_COLS, version_col=False)
    assert widziane == [False, True, True, True, True, True]


# ---------- kadr: pion po resecie lokalnym zostaje (Qt), bieżąca wraca bez skoku ----------

def _baza_dluga(tmp_path, n=300):
    """`n` lightów bez plików, ścieżki w kolejności innej niż `id`. Lista stoi rosnąco po „Ścieżce”
    (sort domyślny), więc klik w jej nagłówek odwraca kolejność - wiersz przy górze ląduje na końcu."""
    path = str(tmp_path / "dluga.db")
    con = db.open_db(path)
    con.executemany("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                    "VALUES (?, ?, 'light', 'fits', ?)", [(i, f"d{i}", NOW) for i in range(1, n + 1)])
    con.executemany("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    [(i, f"/a/{(i * 7919) % n:04d}_f{i}.fits") for i in range(1, n + 1)])
    con.commit()
    con.close()
    return path


@pytest.fixture
def dluga(qapp, tmp_path):
    con = db.connect(_baza_dluga(tmp_path))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view.resize(1400, 700)
    view.show()
    QApplication.processEvents()
    yield view
    view.close()
    con.close()


def _wywolania_flags_przy_ctrl_a(tmp_path, monkeypatch, n):
    """Ile razy Qt pyta `GridTableModel.flags` po prawdziwym Ctrl+A w tabeli `n` klatek (gest
    i pętla zdarzeń do ciszy) - i ile kolumn ma tabela."""
    licznik = {"n": 0}
    prawdziwe = grid_mod.GridTableModel.flags

    def _flags(self, index):
        licznik["n"] += 1
        return prawdziwe(self, index)
    monkeypatch.setattr(grid_mod.GridTableModel, "flags", _flags)
    katalog = tmp_path / f"n{n}"
    katalog.mkdir()
    con = db.connect(_baza_dluga(katalog, n))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        view.resize(1400, 700)
        view.show()
        _odczekaj_debounce()
        view.table.setFocus()
        licznik["n"] = 0
        QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
        _odczekaj_debounce()
        assert _zaznaczone(view) == list(range(1, n + 1))
        return licznik["n"], view.model.columnCount()
    finally:
        view.close()
        con.close()


def test_pelne_zaznaczenie_nie_pyta_o_kazda_komorke(qapp, tmp_path, monkeypatch):
    """Nagłówek poziomy ma WŁASNY model zaznaczenia: dzielony z tabelą pytał przy pełnym zaznaczeniu
    `flags()` o każdą komórkę przy każdym malowaniu nagłówka (kopia pf4: 255 909 wywołań, 2,7-3,5 s na
    Ctrl+A; po AR-202 natywnie 511 875 i 4-7 s - także z `setHighlightSections(False)`). Relacja, nie
    liczba: przybywa wierszy - liczba wywołań rośnie najwyżej o jedno na wiersz, nie o liczbę kolumn na
    wiersz. Falsyfikator: zdejmij własny model zaznaczenia nagłówka w `_build_ui` (wzrost = wiersze ×
    kolumny)."""
    male, kolumny = _wywolania_flags_przy_ctrl_a(tmp_path, monkeypatch, 100)
    duze, _ = _wywolania_flags_przy_ctrl_a(tmp_path, monkeypatch, 400)
    assert kolumny > 1
    assert duze - male <= 400 - 100, (male, duze, kolumny)


def _w_kadrze(view):
    rect = view.table.visualRect(view.table.currentIndex())
    return rect.isValid() and view.table.viewport().rect().intersects(rect)


def _klik_w_srodek_kadru(view, czesc=2):
    """Klik myszą w wiersz na wysokości 1/`czesc` kadru → jego klatka."""
    wiersz = view.table.rowAt(view.table.viewport().height() // czesc)
    fid = view.model._rows[wiersz]["frame_id"]
    _klik_komorki(view, fid, 1)
    return fid


def test_podglad_makra_i_wyczysc_zaznaczenie_zostaje_a_kadr_stoi(dluga):
    """„Podgląd” makra i „Wyczyść podgląd” myszą (klatki bez plików makro pomija z powodem - reset
    idzie drogą produktu): zaznaczenie i bieżąca komórka zostają, a pion paska przewijania stoi -
    przy podglądzie wiersze się nie ruszają, więc nie ma po co przewijać. Bieżący wiersz stoi przy
    górnej krawędzi kadru. Falsyfikator: środek kadru (`PositionAtCenter`) w
    `_zaznaczenie_po_resecie` - pion się zmienia."""
    view = dluga
    vb = view.table.verticalScrollBar()
    vb.setValue(vb.maximum() // 3)
    QApplication.processEvents()
    fid = _klik_w_srodek_kadru(view, czesc=8)
    biezaca, pion = _biezaca(view), vb.value()
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_prev)
    assert view.model._preview_active(), "podgląd stanął - reset przeszedł"
    _odczekaj_debounce()
    assert _zaznaczone(view) == [fid] and _biezaca(view) == biezaca and vb.value() == pion
    wyczysc = next(b for b in view.macro_bar.findChildren(type(view.macro_bar.btn_prev))
                   if b.text() == i18n.t("grid.action.clear_preview"))
    _klik_przycisku(wyczysc)
    assert not view.model._preview_active()
    _odczekaj_debounce()
    assert _zaznaczone(view) == [fid] and _biezaca(view) == biezaca and vb.value() == pion


def _wiersz(view, fid):
    return next(i for i, r in enumerate(view.model._rows) if r.get("frame_id") == fid)


def test_sort_pokazuje_biezaca_gdy_byla_w_kadrze(dluga):
    """Bieżąca komórka w kadrze przed sortem (wiersz przy górze listy) - sort malejący po „Ścieżce”
    (lista stoi rosnąco po niej) przenosi ją na koniec listy, a po sorcie stoi w kadrze (najmniejsze
    przewinięcie, które ją pokazuje). Falsyfikator: `kadr=None` zawsze - wiersz zostaje poza kadrem."""
    view = dluga
    vb = view.table.verticalScrollBar()
    vb.setValue(0)
    QApplication.processEvents()
    fid = _klik_w_srodek_kadru(view, czesc=4)
    ostatni_w_kadrze = view.table.rowAt(view.table.viewport().height() - 1)
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    assert _wiersz(view, fid) > ostatni_w_kadrze, "sort nie wywiózł wiersza poza dawny kadr"
    assert _zaznaczone(view) == [fid]
    assert _w_kadrze(view)


def test_sort_nie_przewija_do_biezacej_spoza_kadru(dluga):
    """Bieżąca komórka POZA kadrem przed sortem (człowiek przewinął w środek listy) - po sorcie pion
    zostaje, gdzie był, choć wiersz bieżący wyjechał na koniec listy: ani `scrollTo`, ani
    przewinięcie, które `setCurrentIndex` robi sam (`autoScroll`). Zaznaczenie i bieżąca wracają.
    Falsyfikatory: `EnsureVisible` także dla niewidocznej; `setCurrentIndex` bez wyłączenia
    `autoScroll` w `_przywroc_zaznaczenie`."""
    view = dluga
    vb = view.table.verticalScrollBar()
    vb.setValue(0)
    QApplication.processEvents()
    fid = _klik_w_srodek_kadru(view, czesc=4)
    biezaca = _biezaca(view)
    vb.setValue(vb.maximum() // 2)
    QApplication.processEvents()
    assert not _w_kadrze(view)
    pion = vb.value()
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    assert _wiersz(view, fid) > view.table.rowAt(view.table.viewport().height() - 1)
    assert _zaznaczone(view) == [fid] and _biezaca(view) == biezaca
    assert vb.value() == pion and not _w_kadrze(view)


def test_przelaczenie_prezentacji_zachowuje_biezaca_komorke_po_znaczeniu(stos):
    """Znajdź ↔ klasyczna przebudowuje kolumny bazowe na tych samych wierszach: zaznaczenie
    i bieżąca komórka (klatka + znaczenie kolumny „Filtr”, inny numer w każdej prezentacji) zostają -
    jedną drogą, bez drugiego, ręcznego odtworzenia w `set_presentation`. Falsyfikator: znaczenie
    kolumny w `_migawka_zaznaczenia` z `model._sort_id_for` (model opisuje już układ następny)."""
    view = stos
    _klik_komorki(view, 10, view.model.base_col("filter_canon"))
    _klik_komorki(view, 3, view.model.base_col("filter_canon"), Qt.ControlModifier)
    biezaca = _biezaca(view)
    assert biezaca == (3, ("base", "filter_canon"))
    view.set_presentation(grid_mod.PREZENTACJA_ZNAJDZ)
    assert _zaznaczone(view) == [3, 10] and _biezaca(view) == biezaca
    view.set_presentation(grid_mod.PREZENTACJA_KLASYCZNA)
    assert _zaznaczone(view) == [3, 10] and _biezaca(view) == biezaca


# ---------- zapis i cofnięcie szuflady: zbiór ten sam, zaznaczenie wraca ----------

@pytest.fixture
def pliki(qapp, tmp_path):
    """Trzy prawdziwe lighty FITS (różne piksele - trzy klatki) - zapis szuflady rusza dysk."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    con = db.open_db(str(tmp_path / "wb.db"))
    for i in (1, 2, 3):
        p = tmp_path / f"wb{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view._writeback_async = False
    view.resize(1400, 800)
    view.show()
    QApplication.processEvents()
    yield view, tmp_path
    view.close()
    con.close()


def test_zapis_szuflady_i_cofniecie_zaznaczenie_zostaje(pliki):
    """„Do stagingu” (podgląd ze stagingu), „Zapisz” i „Cofnij” w szufladzie myszą: plik zmieniony
    i przywrócony, a zaznaczenie dwóch klatek zostaje po każdym kroku. Falsyfikator: bez
    `_oznacz_przeladowanie_z_zaznaczeniem()` w `_after_commit` (albo w `_after_undo`) - przeładowanie
    po zapisie idzie drogą nawigacyjną i zaznaczenie znika."""
    from astropy.io import fits
    view, tmp = pliki
    ids = _kolejnosc(view)
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    cel = sorted([ids[0], ids[2]])
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)
    assert view._pending_count() == 3 and _zaznaczone(view) == cel
    _klik_przycisku(view.drawer.btn_commit)
    _odczekaj_debounce()
    assert {fits.getheader(str(tmp / f"wb{i}.fits"))["TELESCOP"] for i in (1, 2, 3)} == {"EQ6"}
    assert _zaznaczone(view) == cel
    _klik_przycisku(view._undo_btn)
    _odczekaj_debounce()
    assert {fits.getheader(str(tmp / f"wb{i}.fits"))["TELESCOP"] for i in (1, 2, 3)} == {"RC8"}
    assert _zaznaczone(view) == cel


def test_edycja_komorki_domknieta_klikiem_w_naglowek_zaznaczenie_zostaje(pliki):
    """Edytor komórki otwarty dwuklikiem, tekst wpisany, klik w nagłówek bez Enter: wpis idzie do
    szuflady (domknięcie z zapisem przed resetem), podgląd ze stagingu stoi, a zaznaczenie klatki
    zostaje mimo dwóch resetów (podgląd i sort). Falsyfikator: para sygnałów pomija reset
    `set_preview` (zaznaczenie puste po podglądzie stagingu)."""
    view, _tmp = pliki
    m = view.model
    kol = next(c for c in range(m.columnCount()) if m.headerData(c, Qt.Horizontal) == "TELESCOP")
    fid = _kolejnosc(view)[1]
    wiersz = next(i for i, r in enumerate(m._rows) if r.get("frame_id") == fid)
    rect = view.table.visualRect(m.index(wiersz, kol))
    QTest.mouseClick(view.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QTest.mouseDClick(view.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QApplication.processEvents()
    edytor = QApplication.focusWidget()
    assert edytor is not None and edytor is not view.table, "edytor komórki się nie otworzył"
    edytor.selectAll()
    QTest.keyClicks(edytor, "EQ6")
    _klik_naglowka(view, m.base_col("path"))
    _odczekaj_debounce()
    assert view._pending_count() == 1 and m._preview_active()
    assert _zaznaczone(view) == [fid]


# ---------- cel gestu, klatki zamiast wierszy, przyłożenie ----------

@pytest.fixture
def nazwy(qapp, tmp_path):
    """Trzy prawdziwe lighty FITS z `DATE-OBS` (nazwa z faktów ma z czego się złożyć) - pliki
    w `tmp_path`; zapis nazw nie rusza tu dysku (sam staging)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    con = db.open_db(str(tmp_path / "nazwy.db"))
    for i, dobs in enumerate(("2024-03-15T21:30:45", "2024-03-16T22:00:00", "2024-03-17T23:00:00")):
        p = tmp_path / f"raw{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, dtype=np.int16))
        hdu.header["IMAGETYP"] = "Light"
        hdu.header["OBJECT"] = "M42"
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["FILTER"] = "Ha"
        hdu.header["DATE-OBS"] = dobs
        hdu.header["EXPTIME"] = 300.0
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view._writeback_async = False
    view.resize(1400, 800)
    view.show()
    QApplication.processEvents()
    yield view, con
    view.close()
    con.close()


def test_podglad_nazw_przy_zaznaczeniu_czesci_nie_zmienia_celu_stagingu(nazwy):
    """Dwie z trzech klatek zaznaczone: „Podgląd” nazw (reset podglądu) zostawia zaznaczenie - cel
    gestu - więc „Do stagingu” bierze te dwie, nie cały widok. Kliki prawdziwe. Falsyfikator: reset
    podglądu bez odtworzenia zaznaczenia (zaznaczenie znika, staging bierze 3)."""
    from horreum import writeback
    from horreum.gui import queries
    view, con = nazwy
    ids = _kolejnosc(view)
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    cel = sorted([ids[0], ids[2]])
    _klik_przycisku(view.sel_bar.btn_rename)
    _klik_przycisku(view.rename_bar.btn_prev)
    assert view.model._preview_active()
    assert _zaznaczone(view) == cel
    _klik_przycisku(view.rename_bar.btn_stage)
    zakres = sorted(queries.frame_for_location(con, r["location_id"])
                    for r in writeback.renames_for_run(con, view._rename_run_id))
    assert zakres == cel


def test_dwa_wiersze_jednej_klatki_to_jeden_obraz(stos):
    """Stan, którego `queries.base_rows` dziś nie daje (wiersz na klatkę - kopia pf4: 16 998 wierszy
    na 16 998 klatek), wstawiony wprost do modelu: stos 10 w dwóch wierszach. Klik w jeden wiersz,
    sort - odtworzenie po `frame_id` stawia oba, a licznik i panel liczą KLATKI: „1 zaznaczona”,
    panel jednego stosu z jego wejściami. Falsyfikatory: panel liczący wiersze stosów („kilka
    obrazów”); licznik liczący wiersze („2 zaznaczone”)."""
    view = stos
    wiersze = [dict(r) for r in view.model._data_rows]
    wiersze.append(dict(next(r for r in wiersze if r["frame_id"] == 10)))
    view.model.set_data(wiersze, pivot_mod.build_pivot([r["frame_id"] for r in wiersze], [], []),
                        [])
    _klik_komorki(view, 10, 1)
    _odczekaj_debounce()
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    assert _zaznaczone(view) == [10, 10]
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 1))
    _klik_przycisku(view.sel_bar.btn_lineage)                  # zamknij i otwórz - panel czyta
    _klik_przycisku(view.sel_bar.btn_lineage)                  # zaznaczenie od nowa (oba wiersze)
    assert view._lineage_panel_open()
    assert view.lineage_bar.head.text() != i18n.t("grid.lin.hint.many")
    assert view._lineage_frame_id == 10 and view.lineage_bar.items.count() == 2


def test_przeladowanie_po_kolumnach_pelne_zaznaczenie_wraca(stos):
    """Nie-nawigacyjne przeładowanie tego samego zbioru (klik pola w „Polach”) przy zaznaczeniu
    całego widoku (Ctrl+A): wraca całe zaznaczenie i bieżąca komórka, licznik je liczy, pasek nie mówi
    o zdjęciu. Falsyfikator: `_zastosuj_zbior` bez odtworzenia migawki (zaznaczenie puste)."""
    from test_gui_pola_w_tle import _klik_pola
    view = stos
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    QApplication.processEvents()
    biezaca = _biezaca(view)
    zdania = []
    view.status_message.connect(zdania.append)
    _klik_pola(view, "GAIN")
    _odczekaj_debounce()
    assert "GAIN" not in view.model._keywords
    assert _zaznaczone(view) == [1, 2, 3, 10]
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 4))
    assert _biezaca(view) == biezaca
    assert zdania == []


def test_zapis_szuflady_pelne_zaznaczenie_wraca_zdanie_bez_czlonu(pliki):
    """Ctrl+A, staging makra i „Zapisz” myszą: przeładowanie po zapisie (nie-nawigacyjne, ten sam
    zbiór) oddaje zaznaczenie wszystkich klatek, a ostatnie zdanie paska to zdanie zapisu. Falsyfikator:
    bez `_oznacz_przeladowanie_z_zaznaczeniem()` w `_after_commit` (zaznaczenie puste)."""
    view, _tmp = pliki
    zdania = []
    view.status_message.connect(zdania.append)
    ids = _kolejnosc(view)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)
    assert _zaznaczone(view) == sorted(ids), "podgląd stagingu nie zdejmuje celu"
    _klik_przycisku(view.drawer.btn_commit)
    _odczekaj_debounce()
    assert _zaznaczone(view) == sorted(ids)
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 3))
    assert str(zdania[-1]).startswith(i18n.t("grid.wb.status", summary=""))


def test_wybor_czlowieka_w_trakcie_zapisu_w_tle_wygrywa(qapp, tmp_path, monkeypatch):
    """Zapis szuflady w WĄTKU TŁA wstrzymany bramą; w tym czasie człowiek klika myszą inną klatkę.
    Po końcu zapisu przeładowanie oddaje zaznaczenie z chwili PRZYŁOŻENIA - wybór człowieka, nie
    zaznaczenie z chwili „Zapisz”. Falsyfikator: migawka z chwili zlecenia (znacznik stawiany razem
    z migawką w `_after_commit`)."""
    import threading
    import time
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    from horreum.gui import wb_worker
    from test_gui_pola_w_tle import _czekaj
    con = db.open_db(str(tmp_path / "async.db"))
    for i in (1, 2, 3):
        p = tmp_path / f"a{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    brama, wszedl = threading.Event(), threading.Event()
    prawdziwy = wb_worker.WritebackWorker._OPS["commit"]

    def _commit(*a):
        wszedl.set()
        brama.wait(30)
        return prawdziwy(*a)
    monkeypatch.setitem(wb_worker.WritebackWorker._OPS, "commit", _commit)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        assert view._writeback_async, "zapis w wątku tła"
        view.resize(1400, 800)
        view.show()
        QApplication.processEvents()
        ids = _kolejnosc(view)
        _klik_komorki(view, ids[0], 1)
        _klik_przycisku(view.sel_bar.btn_macro)
        view.macro_bar.asg_kw.setCurrentText("TELESCOP")
        view.macro_bar.asg_expr.setText("EQ6")
        _klik_przycisku(view.macro_bar.btn_stage)
        _klik_przycisku(view.drawer.btn_commit)
        _czekaj(wszedl.is_set, "zapis w tle nie ruszył")
        assert view._wb.is_busy
        _klik_komorki(view, ids[2], 1)                      # wybór człowieka w trakcie zapisu
        assert _zaznaczone(view) == [ids[2]]
        brama.set()
        _czekaj(lambda: not view._wb.is_busy, "zapis w tle nie skończył")
        time.sleep(0.05)
        _odczekaj_debounce()
        assert view._pending_count() == 0
        assert _zaznaczone(view) == [ids[2]]
    finally:
        brama.set()
        _czekaj(lambda: not view._wb.is_busy, "zapis w tle nie skończył")
        view.close()
        con.close()


def test_wyjatek_w_set_data_zdejmuje_flage_nowych_danych(monkeypatch):
    """Wyjątek w środku `set_data` nie zostawia modelu w stanie „reset z nowymi danymi” - kolejny
    sort jest znów resetem tych samych wierszy. Falsyfikator: flaga bez `finally`."""
    m = grid_mod.GridTableModel()
    base = [{"frame_id": i, "path": f"/a/{i}.fits", "kind": "light"} for i in (1, 2)]
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [])

    def _pada():
        raise RuntimeError("awaria przebudowy")
    monkeypatch.setattr(m, "_rebuild", _pada)
    with pytest.raises(RuntimeError):
        m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [])
    assert m.reset_tych_samych_wierszy()


# ---------- AR-202: zdarzenia dostępności zaznaczenia z zakresów (`_TabelaKlatek`), zaznaczenie bez progu ----------
#
# Offscreen nie ma klienta UI Automation: `QAccessible.isActive()` jest False i `setActive(True)` go nie
# zmienia (zmierzone), więc testy podmieniają SAM kanał dostępności w module tabeli (`grid_model.QAccessible`:
# aktywny, `updateAccessibility` zapisuje zdarzenie). Gesty są prawdziwe; prawdziwego klienta UIA trzyma
# pomiar natywny przy zmianie (zdarzenia i stan komórek jak w `QTableView`).

def _kanal_dostepnosci(monkeypatch):
    """Podmiana kanału dostępności w `grid_model` - lista `(nazwa rodzaju, numer dziecka)` wysłanych
    zdarzeń, np. `("SelectionAdd", 17)`."""
    from PySide6.QtGui import QAccessible
    from horreum.gui import grid_model
    zdarzenia = []

    class _Kanal:
        Event = QAccessible.Event

        @staticmethod
        def isActive():
            return True

        @staticmethod
        def updateAccessibility(zdarzenie):
            zdarzenia.append((zdarzenie.type().name, zdarzenie.child()))
    monkeypatch.setattr(grid_model, "QAccessible", _Kanal)
    return zdarzenia


def _dziecko(view, wiersz, kolumna):
    """Numer dziecka komórki w interfejsie dostępności tabeli - jak `QTableViewPrivate::accessibleTable2Index`
    (nagłówki liczą się jako wiersz i kolumna, także ukryte)."""
    return (wiersz + 1) * (view.model.columnCount() + 1) + kolumna + 1


def _ctrl_a(view):
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    QApplication.processEvents()


def test_ctrl_a_zdarzenie_dostepnosci_z_zakresow(qapp, tmp_path, monkeypatch):
    """Prawdziwy Ctrl+A w tabeli 100 i 400 klatek przy aktywnej dostępności: JEDNO zdarzenie
    `SelectionAdd` dla pierwszej komórki (wiersz 0, kolumna 0), jak w `QTableView::selectionChanged`,
    a liczba wywołań `flags()` W SAMYM GEŚCIE nie rośnie z wierszami × kolumnami (natywnie, kopia pf4:
    256 902 wywołań i 2 s na Ctrl+A). Falsyfikatory: indeks z `selected.indexes()` (wzrost o wiersze ×
    kolumny); zwykły `QTableView` (zero zdarzeń); numer dziecka bez nagłówka pionowego."""
    zdarzenia = _kanal_dostepnosci(monkeypatch)
    licznik = {"n": 0}
    prawdziwe = grid_mod.GridTableModel.flags

    def _flags(self, index):
        licznik["n"] += 1
        return prawdziwe(self, index)
    monkeypatch.setattr(grid_mod.GridTableModel, "flags", _flags)
    w_gescie = {}
    for n in (100, 400):
        katalog = tmp_path / f"a{n}"
        katalog.mkdir()
        con = db.connect(_baza_dluga(katalog, n))
        view = grid_mod.FramesView(con, now_fn=lambda: NOW)
        try:
            view.resize(1400, 700)
            view.show()
            _odczekaj_debounce()
            view.table.setFocus()
            zdarzenia.clear()
            licznik["n"] = 0
            QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
            w_gescie[n] = licznik["n"]
            assert zdarzenia == [("SelectionAdd", _dziecko(view, 0, 0))]
            assert _zaznaczone(view) == list(range(1, n + 1))
        finally:
            view.close()
            con.close()
    assert w_gescie[400] - w_gescie[100] <= 400 - 100, w_gescie


def test_przejscie_zaznaczenia_na_inny_wiersz_dodaje_potem_usuwa(dluga, monkeypatch):
    """Klik w wiersz A, potem klik w wiersz B: jeden sygnał dodaje B i odejmuje A - zdarzenia
    `SelectionAdd` (B) PRZED `SelectionRemove` (A), oba w kolumnie 0, kolejność jak w
    `QTableView::selectionChanged`. Falsyfikatory: zamieniona kolejność; bez gałęzi `deselected`."""
    view = dluga
    zdarzenia = _kanal_dostepnosci(monkeypatch)
    a, b = _kolejnosc(view)[2], _kolejnosc(view)[5]
    _klik_komorki(view, a, 1)
    zdarzenia.clear()
    _klik_komorki(view, b, 1)
    assert zdarzenia == [("SelectionAdd", _dziecko(view, _wiersz(view, b), 0)),
                         ("SelectionRemove", _dziecko(view, _wiersz(view, a), 0))]


def test_klik_po_pelnym_zaznaczeniu_zdarzenie_usuniecia_jak_qt(dluga, monkeypatch):
    """Ctrl+A, potem klik w jeden wiersz: nic nie dochodzi, reszta odchodzi - jedno `SelectionRemove`
    dla komórki, którą Qt oddaje na pozycji 0 z `deselected.indexes()` (liczonej tu w teście na 300
    wierszach), zero `SelectionAdd`. Falsyfikator: bez gałęzi `deselected`."""
    view = dluga
    zdarzenia = _kanal_dostepnosci(monkeypatch)
    _ctrl_a(view)
    odjete = []
    view.table.selectionModel().selectionChanged.connect(lambda _s, d: odjete.extend(d.indexes()[:1]))
    zdarzenia.clear()
    fid = _klik_w_srodek_kadru(view, czesc=3)
    assert _zaznaczone(view) == [fid]
    pierwsza = odjete[-1]
    assert zdarzenia == [("SelectionRemove", _dziecko(view, pierwsza.row(), pierwsza.column()))]


def test_zdarzenie_dostepnosci_pomija_belke_grupy(dluga, monkeypatch):
    """„Grupuj wg: Rodzaj”, Ctrl+A - zakres Qt zaczyna się belką grupy (wiersz 0, niewybieralny),
    więc zdarzenie wskazuje pierwszy wiersz DANYCH, jak `indexes()` z sitem wybieralności.
    Falsyfikator: pierwszy indeks zakresu bez pytania o `flags()` (dziecko belki)."""
    view = dluga
    _wybierz_w_combo(view.combo_group, "kind")
    assert "_group" in view.model._rows[0] and "_group" not in view.model._rows[1]
    zdarzenia = _kanal_dostepnosci(monkeypatch)
    _ctrl_a(view)
    assert zdarzenia == [("SelectionAdd", _dziecko(view, 1, 0))]


def test_pierwszy_wybieralny_jak_indexes_qt(qapp):
    """`_pierwszy_wybieralny` oddaje to samo, co `QItemSelection.indexes()[0]` z Qt, na modelu z belkami
    grup: zakres całości (od belki), dwa zakresy z pierwszym złożonym z samej belki, zakres od wiersza
    danych w środku kolumn, puste zaznaczenie (`None` / pusta lista). Falsyfikator: sito bez `flags()`."""
    from PySide6.QtCore import QItemSelection
    from horreum.gui import grid_model
    m = grid_mod.GridTableModel()
    base = [{"frame_id": i, "path": f"/a/{i}.fits", "kind": k}
            for i, k in ((1, "dark"), (2, "light"), (3, "light"))]
    m.set_data(base, pivot_mod.build_pivot([1, 2, 3], [], []), [], group_by="kind")
    belki = [i for i, r in enumerate(m._rows) if "_group" in r]
    assert belki == [0, 2], m._rows
    ost = m.columnCount() - 1

    def _zaznaczenie(*zakresy):
        sel = QItemSelection()
        for (w1, k1), (w2, k2) in zakresy:
            sel.select(m.index(w1, k1), m.index(w2, k2))
        return sel
    for sel in (_zaznaczenie(((0, 0), (4, ost))),
                _zaznaczenie(((2, 0), (2, ost)), ((3, 0), (4, ost))),
                _zaznaczenie(((3, 2), (4, ost)))):
        qt = sel.indexes()[0]
        nasz = grid_model._pierwszy_wybieralny(sel)
        assert (nasz.row(), nasz.column()) == (qt.row(), qt.column())
    assert grid_model._pierwszy_wybieralny(QItemSelection()) is None


def test_selection_changed_przemalowuje_zaznaczony_wiersz(dluga):
    """Zaznaczenie przechodzi z jednego wiersza na drugi w modelu zaznaczenia - bez ruchu bieżącej
    komórki, bez fokusu, bez resetu i bez zmiany tekstu licznika („1 zaznaczona” przed i po), więc nic
    innego nie zleca malowania - a przemalowane zostają OBA wiersze: zdjęty i dołożony. Bazowe
    `QAbstractItemView.selectionChanged` zleca odświeżenie obszaru `deselected` i `selected`.
    Falsyfikator: `_TabelaKlatek.selectionChanged` bez wołania bazowego (zaznaczenie bez malowania)."""
    from PySide6.QtCore import QEvent, QItemSelectionModel, QObject
    view = dluga
    biezaca = view.table.currentIndex()
    pierwszy = view.table.rowAt(view.table.viewport().height() // 4)
    view.table.selectionModel().select(view.model.index(pierwszy, 0),
                                       QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    _odczekaj_debounce()

    class _Malowania(QObject):
        def __init__(self):
            super().__init__()
            self.obszary = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Paint:
                self.obszary.append(ev.region().boundingRect())
            return False
    filtr = _Malowania()
    view.table.viewport().installEventFilter(filtr)
    try:
        wiersz = view.table.rowAt(view.table.viewport().height() // 2)
        assert wiersz != pierwszy and biezaca.row() not in (pierwszy, wiersz)
        view.table.selectionModel().select(view.model.index(wiersz, 0),
                                           QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        _odczekaj_debounce()
        assert _zaznaczone(view) == [view.model._rows[wiersz]["frame_id"]]
        assert view.table.currentIndex() == biezaca, "bieżąca komórka się ruszyła - test nic by nie mierzył"
        for w in (pierwszy, wiersz):                          # zdjęty i dołożony
            komorka = view.table.visualRect(view.model.index(w, 0))
            assert any(o.intersects(komorka) for o in filtr.obszary), (w, filtr.obszary)
    finally:
        view.table.viewport().removeEventFilter(filtr)


def test_pelne_zaznaczenie_przezywa_podglad_i_jego_zdjecie(dluga):
    """Ctrl+A na 300 klatkach, „Podgląd” makra i „Wyczyść podgląd” myszą: całe zaznaczenie po obu
    resetach, licznik je liczy, zdanie zdjęcia bez członu. Falsyfikator: reset podglądu bez odtworzenia
    zaznaczenia (zaznaczenie puste)."""
    view = dluga
    zdania = []
    view.status_message.connect(zdania.append)
    _ctrl_a(view)
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_prev)
    assert view.model._preview_active()
    assert _zaznaczone(view) == list(range(1, 301))
    wyczysc = next(b for b in view.macro_bar.findChildren(type(view.macro_bar.btn_prev))
                   if b.text() == i18n.t("grid.action.clear_preview"))
    _klik_przycisku(wyczysc)
    assert not view.model._preview_active()
    assert _zaznaczone(view) == list(range(1, 301))
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 300))
    assert zdania[-1] == i18n.t("grid.macro.preview_cleared")


def test_shift_klik_po_sorcie_kotwiczy_na_biezacej_klatce(dluga):
    """Klik w klatkę (bieżąca, kotwica Shift), Ctrl+A, sort klikiem w „Ścieżkę”, Shift+klik w klatkę
    trzy wiersze wyżej od bieżącej w nowym porządku: zaznaczenie = wiersze od klikniętego do wiersza
    bieżącej klatki - kotwica przeżywa sort po tożsamości. Falsyfikator: `_przywroc_zaznaczenie` bez
    `setCurrentIndex` (kotwica znika, zakres liczy się od innego wiersza)."""
    view = dluga
    vb = view.table.verticalScrollBar()
    vb.setValue(0)
    QApplication.processEvents()
    fid = _klik_w_srodek_kadru(view, czesc=4)
    _ctrl_a(view)
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    assert len(_zaznaczone(view)) == 300
    wiersz = _wiersz(view, fid)
    assert view.table.currentIndex().row() == wiersz
    assert wiersz >= 3, "bieżąca po sorcie bez trzech wierszy nad sobą - test nic by nie mierzył"
    cel = view.model._rows[wiersz - 3]["frame_id"]
    _klik_komorki(view, cel, 1, Qt.ShiftModifier)
    oczekiwane = sorted(view.model._rows[i]["frame_id"] for i in range(wiersz - 3, wiersz + 1))
    assert _zaznaczone(view) == oczekiwane


def _prawy_klik(view, wiersz):
    """PRAWDZIWY prawy klik w wiersz (`tests/prawy_klik.py`: mysz przez uchwyt okna, wyzwalacz menu
    Windows `Release`) - nie syntetyczny `QContextMenuEvent`, który omijał nacisk myszy, a to w nacisku
    Qt przestawiał zaznaczenie przed menu (AR-263, wizytacja natywna)."""
    from prawy_klik import prawy_klik
    punkt = view.table.visualRect(view.model.index(wiersz, 1)).center()
    return prawy_klik(view.table.viewport(), punkt)


def test_prawy_klik_po_sorcie_cel_menu_z_odtworzonego_zaznaczenia(dluga):
    """Perspektywa z sekcją menu tabeli (flaga „Zastąpione” postawiona wprost - menu dochodzi do `popup`
    bez danych perspektywy, a reguła celu siedzi w `_on_table_menu`): Ctrl+A, sort klikiem, prawy klik
    w wiersz odtworzonego zaznaczenia - menu się pokazuje, zaznaczenie zostaje całe (cel gestu menu);
    potem klik w jeden wiersz i prawy klik POZA nim - zaznaczenie przechodzi na wiersz pod kursorem
    (konwencja platformy). Falsyfikator: odtworzenie bez zaznaczenia (prawy klik zaznacza jeden wiersz)."""
    view = dluga
    setattr(view, grid_mod._FLAGA_ZASTAPIONYCH, True)
    _ctrl_a(view)
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    try:
        _prawy_klik(view, view.table.rowAt(view.table.viewport().height() // 2))
        assert view._menu_tabeli.isVisible(), "menu nie doszło do popup - test nic by nie mierzył"
        assert len(_zaznaczone(view)) == 300
        view._menu_tabeli.hide()
        jeden = _klik_w_srodek_kadru(view, czesc=4)
        inny = view.table.rowAt(view.table.viewport().height() // 2)
        assert view.model._rows[inny]["frame_id"] != jeden
        _prawy_klik(view, inny)
        assert view._menu_tabeli.isVisible()
        assert _zaznaczone(view) == [view.model._rows[inny]["frame_id"]]
    finally:
        view._menu_tabeli.hide()


def test_tabela_klatek_zna_wersje_qt():
    """`_TabelaKlatek.selectionChanged` pomija w całości `QTableView::selectionChanged`, odtwarzając jej
    treść przeczytaną w źródle Qt z `_QT_TABELI_KLATEK`. Inna wersja Qt może tę metodę zmienić po cichu -
    test pęka, żeby ktoś ją przeczytał od nowa i dopisał wersję."""
    from PySide6.QtCore import qVersion
    from horreum.gui import grid_model
    assert qVersion() in grid_model._QT_TABELI_KLATEK, qVersion()


def test_inna_wersja_qt_wraca_do_metody_qt(dluga, monkeypatch):
    """Bezpiecznik w produkcie: przy wersji Qt spoza `_QT_TABELI_KLATEK` tabela woła
    `QTableView.selectionChanged` (wolniej, ale wiernie) - kanał dostępności tabeli nie dostaje nic od
    `_TabelaKlatek` (offscreen Qt sam nie wysyła, bo nie ma klienta), a zaznaczenie i malowanie działają.
    Falsyfikator: `selectionChanged` bez sprawdzenia wersji (zdarzenie z naszej drogi)."""
    from horreum.gui import grid_model
    view = dluga
    zdarzenia = _kanal_dostepnosci(monkeypatch)
    monkeypatch.setattr(grid_model, "qVersion", lambda: "6.10.0")
    _ctrl_a(view)
    assert _zaznaczone(view) == list(range(1, 301))
    assert zdarzenia == []


def test_inna_wersja_qt_obszar_zaznaczenia_bez_przyciecia(dluga, monkeypatch):
    """Bezpiecznik wersji obejmuje też `visualRegionForSelection` - bazowe `selectionChanged` woła ją
    wirtualnie, więc przy wersji spoza `_QT_TABELI_KLATEK` metoda Qt dostaje PEŁNE zaznaczenie. Zakres
    w całości pod kadrem: przy znanej wersji metoda Qt dostaje zaznaczenie przycięte do kadru (puste),
    przy innej - ten sam zakres w całości. Falsyfikator: przycięcie bez sprawdzenia wersji."""
    from PySide6.QtCore import QItemSelection, QItemSelectionRange
    from PySide6.QtWidgets import QTableView
    from horreum.gui import grid_model
    view = dluga
    tabela, model = view.table, view.table.model()
    dol = tabela.rowAt(tabela.viewport().height() - 1)
    assert 0 <= dol < model.rowCount() - 5
    dostala = []
    bazowa = QTableView.visualRegionForSelection
    monkeypatch.setattr(QTableView, "visualRegionForSelection",
                        lambda self, s: (dostala.append([(r.top(), r.bottom()) for r in
                                                         (s.at(i) for i in range(s.size()))]),
                                         bazowa(self, s))[1])
    sel = QItemSelection()
    sel.append(QItemSelectionRange(model.index(model.rowCount() - 3, 0),
                                   model.index(model.rowCount() - 1, model.columnCount() - 1)))
    tabela.visualRegionForSelection(sel)
    monkeypatch.setattr(grid_model, "qVersion", lambda: "6.10.0")
    tabela.visualRegionForSelection(sel)
    assert dostala == [[], [(model.rowCount() - 3, model.rowCount() - 1)]]


def _widok_dlugi(tmp_path, n):
    con = db.connect(_baza_dluga(tmp_path, n))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    view.resize(1400, 700)
    view.show()
    _odczekaj_debounce()
    return con, view


def test_obszar_przemalowania_przy_belkach_i_przesunietej_sekcji_nie_rosnie_z_wierszami(
        qapp, tmp_path, monkeypatch):
    """Podgląd makra i „Wyczyść podgląd” (sekcja nagłówka zostaje przesunięta), „Grupuj wg: Rodzaj”
    (belka - span), Ctrl+A: Qt liczy wtedy obszar zmiany zaznaczenia komórka po komórce (`visualRect`
    każdej, `rowCount` z każdego `index`) - natywnie na kopii pf4 512 887 wywołań i 9,4 s. Obszar
    przycięty do kadru (`_TabelaKlatek.visualRegionForSelection`): przyrost wywołań `rowCount` przy 400
    wierszach wobec 100 najwyżej wiersz na wiersz. Falsyfikator: bez przycięcia (wzrost = wiersze ×
    kolumny × 2)."""
    from PySide6.QtCore import QModelIndex
    licznik = {"n": 0}
    prawdziwe = grid_mod.GridTableModel.rowCount

    def _rowcount(self, parent=QModelIndex()):
        licznik["n"] += 1
        return prawdziwe(self, parent)
    monkeypatch.setattr(grid_mod.GridTableModel, "rowCount", _rowcount)
    w_gescie = {}
    for n in (100, 400):
        katalog = tmp_path / f"r{n}"
        katalog.mkdir()
        con, view = _widok_dlugi(katalog, n)
        try:
            _klik_przycisku(view.sel_bar.btn_macro)
            view.macro_bar.asg_kw.setCurrentText("TELESCOP")
            view.macro_bar.asg_expr.setText("EQ6")
            _klik_przycisku(view.macro_bar.btn_prev)
            _klik_przycisku(next(b for b in view.macro_bar.findChildren(type(view.macro_bar.btn_prev))
                                 if b.text() == i18n.t("grid.action.clear_preview")))
            _wybierz_w_combo(view.combo_group, "kind")
            assert view.table.horizontalHeader().sectionsMoved() and view.table.columnSpan(0, 0) > 1
            view.table.setFocus()
            _odczekaj_debounce()
            licznik["n"] = 0
            QTest.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
            _odczekaj_debounce()
            w_gescie[n] = licznik["n"]
            assert len(_zaznaczone(view)) == n
        finally:
            view.close()
            con.close()
    assert w_gescie[400] - w_gescie[100] <= 400 - 100, w_gescie


def test_odtworzenie_poszatkowanego_zaznaczenia_bez_przepisywania_zakresow(qapp, tmp_path, monkeypatch):
    """Co druga klatka zaznaczona (zakres na klatkę), sort klikiem: odtworzenie kładzie zakresy, które
    już obejmują wszystkie kolumny, bez `Rows` - Qt nie przepisuje każdego zakresu od nowa
    (`expandSelection`: `columnCount` i dwa `index` na zakres, scalanie każdego z poprzednimi). Relacja:
    przyrost wywołań `columnCount` w sorcie przy 200 zakresach wobec 50 - najwyżej trzy na zakres
    (zmierzone: dwa - tyle biorą dwa `index` przy budowie zakresu; z `Rows` pięć). Falsyfikator:
    `ClearAndSelect | Rows` w `_przywroc_zaznaczenie`."""
    from PySide6.QtCore import QModelIndex
    licznik = {"n": 0}
    prawdziwe = grid_mod.GridTableModel.columnCount

    def _columncount(self, parent=QModelIndex()):
        licznik["n"] += 1
        return prawdziwe(self, parent)
    monkeypatch.setattr(grid_mod.GridTableModel, "columnCount", _columncount)
    w_sorcie = {}
    for n in (100, 400):
        katalog = tmp_path / f"c{n}"
        katalog.mkdir()
        con, view = _widok_dlugi(katalog, n)
        try:
            view._przywroc_zaznaczenie(_kolejnosc(view)[::2])
            _odczekaj_debounce()
            licznik["n"] = 0
            _klik_naglowka(view, view.model.base_col("path"))
            w_sorcie[n] = licznik["n"]
            assert len(_zaznaczone(view)) == n // 2
        finally:
            view.close()
            con.close()
    assert w_sorcie[400] - w_sorcie[100] <= 3 * (200 - 50), w_sorcie


def test_zdjecie_podgladu_nazw_oddaje_staging_jednym_resetem(nazwy):
    """Staging makra, panel nazw (podgląd makra schodzi), „Podgląd” nazw, „Wyczyść podgląd” nazw:
    kolumna wraca do stagingu JEDNYM resetem modelu (dawniej zdjęcie i postawienie - dwa resety i dwa
    odtworzenia zaznaczenia), zaznaczenie dwóch klatek zostaje. Falsyfikator: `set_preview({})` przed
    `set_preview(stagingu)` w `_on_rename_clear`."""
    view, _con = nazwy
    ids = _kolejnosc(view)
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    cel = sorted([ids[0], ids[2]])
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)
    assert view._pending_count() > 0
    _klik_przycisku(view.sel_bar.btn_rename)
    _klik_przycisku(view.rename_bar.btn_prev)
    assert view._preview_owner == "rename"
    resety = []
    view.model.modelAboutToBeReset.connect(lambda: resety.append(1))
    _klik_przycisku(next(b for b in view.rename_bar.findChildren(type(view.rename_bar.btn_prev))
                         if b.text() == i18n.t("grid.action.clear_preview")))
    assert resety == [1]
    assert view._preview_owner == "macro" and view.model._preview == view._podglad_ze_stagingu()
    assert _zaznaczone(view) == cel


def _gest_resetu(view, gest):
    """Reset modelu z odtworzeniem zaznaczenia: sort klikiem, „Grupuj wg: Rodzaj”, podgląd makra
    (przyciskiem) albo nie-nawigacyjne przeładowanie tego samego zbioru."""
    if gest == "sort":
        _klik_naglowka(view, view.model.base_col("path"))
    elif gest == "grupowanie":
        _wybierz_w_combo(view.combo_group, "kind")
        assert "_group" in view.model._rows[0]
    elif gest == "podglad":
        _klik_przycisku(view.sel_bar.btn_macro)
        view.macro_bar.asg_kw.setCurrentText("TELESCOP")
        view.macro_bar.asg_expr.setText("EQ6")
        _klik_przycisku(view.macro_bar.btn_prev)
        assert view.model._preview_active()
    else:
        view.przeladuj_z_zaznaczeniem()
    _odczekaj_debounce()


@pytest.mark.parametrize("gest", ["sort", "grupowanie", "podglad", "przeladowanie"])
def test_shift_klik_po_odtworzeniu_zostawia_czesc_trwala(dluga, gest):
    """AR-249 (był ŚWIADOMYM DŁUGIEM - test pinował, że A wypada). Klik A, Ctrl+klik B, gest z resetem
    modelu, Shift+klik C trzy wiersze nad B. Qt trzyma A w części TRWAŁEJ zaznaczenia, a Shift+klik
    podmienia tylko część BIEŻĄCĄ (od kotwicy B) - bez resetu zostaje A i pas od C do B. Odtworzenie
    jednym `ClearAndSelect` kładło całość do części bieżącej i Shift zastępował całe zaznaczenie; migawka
    z częścią trwałą (`_czesc_trwala_zaznaczenia`) oddaje oba człony. Falsyfikator: odtworzenie bez
    `trwale` (jedno `select` całości) - A wypada."""
    view = dluga
    view.table.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    a, b = view.model._rows[1]["frame_id"], view.model._rows[12]["frame_id"]
    _klik_komorki(view, a, 1)
    _klik_komorki(view, b, 1, Qt.ControlModifier)
    assert _zaznaczone(view) == sorted([a, b])
    _gest_resetu(view, gest)
    assert _zaznaczone(view) == sorted([a, b])
    wiersz = _wiersz(view, b)
    assert view.table.currentIndex().row() == wiersz
    pas = [i for i in range(wiersz - 3, wiersz + 1) if "_group" not in view.model._rows[i]]
    assert len(pas) == 4 and _wiersz(view, a) not in pas, "A w pasie - test nic by nie mierzył"
    _klik_komorki(view, view.model._rows[pas[0]]["frame_id"], 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == sorted([a] + [view.model._rows[i]["frame_id"] for i in pas])


_STOS_DUZY = 1001          # gotowy obraz z rodowodem z lightów 1 i 2 w bazie `_baza_dluga`


def _dopisz_stos(path):
    """Gotowy obraz `_STOS_DUZY` (rodowód z lightów 1 i 2) w bazie lightów - panel Rodowód ma co pokazać."""
    con = db.connect(path)
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (?, 'm-duzy', 'master_light', 'xisf', ?)", (_STOS_DUZY, NOW))
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', '/a/S/stos.xisf', 1)",
                (_STOS_DUZY,))
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch) VALUES (77, ?, ?, 0, 0, 0)", (_STOS_DUZY, NOW))
    con.executemany("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by) "
                    "VALUES (77, ?, 'window')", [(1,), (2,)])
    con.commit()
    con.close()


def _panel_z_wyborem(view, wiersz_listy):
    """Panel Rodowód otwarty przyciskiem paska, wiersz listy kliknięty myszą - stan panelu do asercji."""
    _klik_przycisku(view.sel_bar.btn_lineage)
    _odczekaj_debounce()
    assert view._lineage_panel_open()
    _klik_listy_panelu(view.lineage_bar.items, wiersz_listy)
    return view._lineage_frame_id, view.lineage_bar.selected_frame_ids()


@pytest.mark.parametrize("gest", ["grupowanie", "przeladowanie"])
def test_500_klatek_wraca_po_grupowaniu_i_nienawigacyjnym_przeladowaniu(qapp, tmp_path, gest):
    """500 klatek × kolumny tabeli - ponad dawnym progiem 3 750 komórek - i stos z rodowodem: Ctrl+A,
    panel Rodowód z wierszem listy, potem „Grupuj wg: Rodzaj” albo nie-nawigacyjne przeładowanie tego
    samego zbioru (`przeladuj_z_zaznaczeniem` - droga wyniku Pól, Dostawy, kolumn ręką): wraca całe
    zaznaczenie, licznik je liczy, a panel zostaje przy stosie z tym samym wierszem listy (dawna luka
    testu, AR-250). Falsyfikatory: próg ~250 wierszy w `_zaznaczenie_po_resecie` albo
    w `_zastosuj_zbior`; `_refresh_lineage()` bez wyboru z migawki w `_zastosuj_zbior` (wiersz listy
    znika po przeładowaniu); bez `_date_timer.stop()` w `_zaznaczenie_po_resecie` (debounce
    przebudowuje panel bez wiersza po grupowaniu)."""
    path = _baza_dluga(tmp_path, 500)
    _dopisz_stos(path)
    con = db.connect(path)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        view.resize(1400, 700)
        view.show()
        _odczekaj_debounce()
        assert 500 * view.model.columnCount() > 3_750
        _ctrl_a(view)
        _odczekaj_debounce()
        panel = _panel_z_wyborem(view, 2)
        assert panel == (_STOS_DUZY, [2]), panel
        wszystkie = list(range(1, 501)) + [_STOS_DUZY]
        if gest == "grupowanie":
            _wybierz_w_combo(view.combo_group, "kind")
            assert "_group" in view.model._rows[0]
        else:
            view.przeladuj_z_zaznaczeniem()
        _odczekaj_debounce()
        assert _zaznaczone(view) == wszystkie
        assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 501))
        assert (view._lineage_frame_id, view.lineage_bar.selected_frame_ids()) == panel
    finally:
        view.close()
        con.close()


# ---------- AR-249: część trwała zaznaczenia przeżywa odtworzenie, jednym sygnałem ----------
#
# Qt trzyma zaznaczenie w części TRWAŁEJ i BIEŻĄCEJ (Shift podmienia tylko bieżącą). Kryterium: zbiór
# zaznaczonych wierszy po geście z resetem = zbiór bez resetu. Kotwica Shift po resecie (prywatne
# `currentSelectionStartIndex` Qt - reset ją unieważnia, kotwicą zostaje bieżąca komórka) to osobny
# mechanizm - „kotwica Shift po resecie, rejestr” - więc sekwencje niżej nie kończą resetu zakresem Shift.

def _reset_bez_zmiany_kolejnosci(view):
    """Dwa resety modelu bez przestawiania wierszy (postawienie i zdjęcie podglądu) - każdy z migawką
    i odtworzeniem zaznaczenia (`_zaznaczenie_przed_resetem`/`_po_resecie`)."""
    fid = view.model._rows[0]["frame_id"]
    view.model.set_preview({fid: {"skipped": "x"}})
    view.model.set_preview({})
    QApplication.processEvents()


def _sekwencja(view, kroki, reset):
    """Kroki gestów na wierszach `dluga` (stała kolejność - podgląd nie sortuje): ("klik", w),
    ("ctrl", w), ("shift", w), ("ctrl_a",); `reset` = reset przed OSTATNIM krokiem."""
    view.table.clearSelection()
    view.table.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    for i, krok in enumerate(kroki):
        if reset and i == len(kroki) - 1:
            _reset_bez_zmiany_kolejnosci(view)
        if krok[0] == "ctrl_a":
            _ctrl_a(view)
            continue
        mod = {"klik": Qt.NoModifier, "ctrl": Qt.ControlModifier, "shift": Qt.ShiftModifier}[krok[0]]
        _klik_komorki(view, view.model._rows[krok[1]]["frame_id"], 1, mod)
    return _zaznaczone(view)


@pytest.mark.parametrize("kroki", [
    [("klik", 1), ("ctrl", 12), ("shift", 9)],                      # Ctrl+klik utrwala A, Shift od B
    [("ctrl_a",), ("ctrl", 6), ("shift", 3)],                       # Ctrl+klik odznacza po Ctrl+A
    [("klik", 1), ("shift", 3), ("ctrl", 12), ("shift", 9)],        # zakres, potem Ctrl+klik
    [("klik", 6), ("ctrl_a",), ("shift", 3)],                       # Ctrl+A to część bieżąca - Shift ją podmienia
    [("klik", 1), ("ctrl", 12), ("ctrl", 12), ("shift", 15)],       # bieżąca na wierszu niezaznaczonym
], ids=["ctrl", "ctrl_a_odznacz", "zakres_ctrl", "ctrl_a", "biezaca_niezaznaczona"])
def test_odtworzenie_daje_ten_sam_zbior_co_brak_resetu(dluga, kroki):
    """Różnicowy: te same gesty bez resetu i z resetem przed ostatnim Shift+klikiem - ten sam zbiór
    zaznaczonych klatek. Sekwencja `ctrl_a` pilnuje drugiej strony: po Ctrl+A Shift podmienia całość
    także bez resetu (`selectAll` = `ClearAndSelect`), więc odtworzenie „wszystko trwałe” byłoby
    błędem. `biezaca_niezaznaczona`: drugi Ctrl+klik B odznacza B, a bieżąca komórka (kotwica Shift
    po resecie) zostaje na B - bez resetu Shift daje A i pas B..C, a bieżąca przeniesiona na pierwszy
    zaznaczony dawała pas A..C. Falsyfikatory: odtworzenie bez części trwałej (`ctrl`, `zakres_ctrl`,
    `ctrl_a_odznacz` czerwone); odtworzenie wszystkiego jako trwałe (`ctrl_a` czerwone); bieżąca
    szukana wyłącznie wśród zaznaczonych (`biezaca_niezaznaczona` czerwone)."""
    bez = _sekwencja(dluga, kroki, reset=False)
    z_resetem = _sekwencja(dluga, kroki, reset=True)
    assert z_resetem == bez, (sorted(set(bez) - set(z_resetem)), sorted(set(z_resetem) - set(bez)))


def test_migawka_zaznaczenia_nie_zmienia_zaznaczenia(dluga):
    """`_czesc_trwala_zaznaczenia` podmienia na chwilę część bieżącą (odczyt części trwałej publicznym
    API) - migawka wzięta POZA resetem zostawia zaznaczenie, a kolejny Shift+klik działa jak bez niej.
    Falsyfikator: odczyt bez przywrócenia części bieżącej (B znika z zaznaczenia)."""
    view = dluga
    a, b, c = (view.model._rows[w]["frame_id"] for w in (1, 12, 9))
    _klik_komorki(view, a, 1)
    _klik_komorki(view, b, 1, Qt.ControlModifier)
    migawka = view._migawka_zaznaczenia()
    assert sorted(migawka[0]) == sorted([a, b]) and migawka[4] == [a]
    assert _zaznaczone(view) == sorted([a, b])
    _klik_komorki(view, c, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == sorted({a} | {view.model._rows[w]["frame_id"] for w in range(9, 13)})


@pytest.mark.parametrize("przygotowanie", ["ctrl_a", "ctrl", "ctrl_a_odznacz"])
def test_odtworzenie_jednym_sygnalem_i_jednym_licznikiem(dluga, przygotowanie):
    """Odtworzenie po sorcie emituje `selectionChanged` RAZ i liczy pasek RAZ - także z częścią trwałą
    (dwa `select` pod zablokowanymi sygnałami + jedna emisja różnicy). Stan pośredni (sama część
    trwała) nie dochodzi do licznika, paneli ani zdarzenia dostępności. Falsyfikator: dwa `select`
    bez blokady sygnałów (dwie emisje, dwa `_update_count`)."""
    view = dluga
    if przygotowanie == "ctrl_a":
        _ctrl_a(view)
    elif przygotowanie == "ctrl":
        for w, mod in ((1, Qt.NoModifier), (5, Qt.ControlModifier), (9, Qt.ControlModifier)):
            _klik_komorki(view, view.model._rows[w]["frame_id"], 1, mod)
    else:
        _ctrl_a(view)
        _klik_komorki(view, view.model._rows[5]["frame_id"], 1, Qt.ControlModifier)
    _odczekaj_debounce()
    przed = _zaznaczone(view)
    emisje, liczniki = [], []
    view.table.selectionModel().selectionChanged.connect(lambda *_: emisje.append(1))
    prawdziwy = view._update_count
    view._update_count = lambda: (liczniki.append(1), prawdziwy())[1]
    _klik_naglowka(view, view.model.base_col("path"))
    assert _zaznaczone(view) == przed
    assert (len(emisje), len(liczniki)) == (1, 1)
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", len(przed)))


def test_naglowki_tabeli_bez_gestu_zaznaczenia(dluga):
    """Kryterium „zaznaczenie przez nagłówek” nie ma gestu w tej tabeli (N/A z dowodem): nagłówek
    poziomy przy `setSortingEnabled(True)` łączy wyłącznie sort (Qt `QTableView::setSortingEnabled` -
    połączenie `sectionPressed` → `selectColumn` istnieje tylko bez sortu), pionowy jest ukryty, a róg
    (`QTableCornerButton` → `selectAll`) chowa się, gdy którykolwiek nagłówek jest ukryty. Prawdziwy
    klik w sekcję nagłówka sortuje i zostawia zaznaczenie. Falsyfikator: pokazany nagłówek pionowy
    (róg widoczny - klik w niego zaznacza wszystko)."""
    from PySide6.QtWidgets import QAbstractButton
    view = dluga
    t = view.table
    assert t.isSortingEnabled() and t.verticalHeader().isHidden()
    rog = [b for b in t.findChildren(QAbstractButton) if b.parent() is t]
    assert rog and all(b.isHidden() for b in rog)
    a = view.model._rows[3]["frame_id"]
    _klik_komorki(view, a, 1)
    przed = _kolejnosc(view)
    _klik_naglowka(view, view.model.base_col("path"))
    assert _kolejnosc(view) != przed and _zaznaczone(view) == [a]


# ---------- AR-250: zapis szuflady przykłada podgląd razem ze zbiorem - jeden reset, jedno odtworzenie ----------

def _pliki_ze_stosem(tmp_path):
    """Trzy prawdziwe lighty FITS (TELESCOP, DATE-OBS - zapis makra i nazw ma z czego się złożyć) i gotowy
    obraz 10 z rodowodem z dwóch pierwszych (panel Rodowód ma co pokazać). Zwraca `(ścieżka bazy, id lightów)`."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    path = str(tmp_path / "szuflada.db")
    con = db.open_db(path)
    for i in (1, 2, 3):
        p = tmp_path / f"wb{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.header["OBJECT"] = "M42"
        hdu.header["FILTER"] = "Ha"
        hdu.header["EXPTIME"] = 300.0
        hdu.header["DATE-OBS"] = f"2024-03-{14 + i:02d}T21:30:45"
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    ids = [r[0] for r in con.execute("SELECT id FROM frame ORDER BY id")]
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (10, 'm10', 'master_light', 'xisf', ?)", (NOW,))
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (10, 'V', '/a/S/stos.xisf', 1)")
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch) VALUES (5, 10, ?, 0, 0, 0)", (NOW,))
    con.executemany("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by) "
                    "VALUES (5, ?, 'window')", [(ids[0],), (ids[1],)])
    con.commit()
    con.close()
    return path, ids


def _widok_szuflady(path, *, watek_zapisu=False, zbior_w_tle=False):
    con = db.connect(path)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=zbior_w_tle)
    view._writeback_async = watek_zapisu
    view.resize(1400, 800)
    view.show()
    if zbior_w_tle:
        from test_gui_pola_w_tle import _czekaj_na_pola
        _czekaj_na_pola(view)
    _odczekaj_debounce()
    return con, view


def _podsluch_resetow(view, monkeypatch):
    """Licznik resetów modelu (`modelAboutToBeReset`) i odtworzeń zaznaczenia (`_przywroc_zaznaczenie`
    z niepustym celem - cel gestu `()` ogona zapisu się nie liczy)."""
    resety, odtworzenia = [], []
    view.model.modelAboutToBeReset.connect(lambda: resety.append(1))
    prawdziwe = grid_mod.FramesView._przywroc_zaznaczenie

    def _licz(self, frame_ids, **kw):
        if frame_ids:
            odtworzenia.append(1)
        return prawdziwe(self, frame_ids, **kw)
    monkeypatch.setattr(grid_mod.FramesView, "_przywroc_zaznaczenie", _licz)
    return resety, odtworzenia


def _makro_do_stagingu(view):
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("TELESCOP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText("EQ6")
    bar._emit_stage()


@pytest.mark.parametrize("klinga", ["makro", "nazwy"])
def test_zapis_szuflady_jeden_reset_jedno_odtworzenie_panel_zostaje(qapp, tmp_path, monkeypatch, klinga):
    """Ctrl+A (trzy lighty i stos), panel Rodowód przy stosie z wierszem listy, staging makra albo nazw,
    „Zatwierdź” myszą w szufladzie: przeładowanie po zapisie to JEDEN reset modelu i JEDNO odtworzenie
    zaznaczenia (podgląd schodzi w resecie `set_data`), zaznaczenie i panel z wyborem zostają, podglądu
    nie ma. Falsyfikator: ogon `set_preview` w `_zbior_ogony` zamiast podglądu przy przyłożeniu (dwa resety,
    dwa odtworzenia)."""
    from test_gui_pasek_szczegol import _POL
    path, ids = _pliki_ze_stosem(tmp_path)
    con, view = _widok_szuflady(path)
    try:
        _ctrl_a(view)
        _odczekaj_debounce()
        panel = _panel_z_wyborem(view, ids[1])
        assert panel == (10, [ids[1]]), panel
        if klinga == "makro":
            _makro_do_stagingu(view)
        else:
            view._on_rename_stage(_POL)
        assert view.model._preview_active()
        wszystkie = _zaznaczone(view)
        resety, odtworzenia = _podsluch_resetow(view, monkeypatch)
        _klik_przycisku(view.drawer.btn_commit)
        _odczekaj_debounce()
        assert (len(resety), len(odtworzenia)) == (1, 1)
        assert not view.model._preview_active()
        assert _zaznaczone(view) == wszystkie
        assert (view._lineage_frame_id, view.lineage_bar.selected_frame_ids()) == panel
    finally:
        view.close()
        con.close()


def test_zapis_przerwany_jeden_reset_podglad_pozostalych_panel_zostaje(qapp, tmp_path, monkeypatch):
    """Zapis w PRAWDZIWYM wątku, „Anuluj” po pierwszym pliku: ogon przerwanego zapisu stawia podgląd
    samych oczekujących wpisów TYM SAMYM resetem, co przyłożenie zbioru - jeden reset, jedno odtworzenie;
    panel Rodowód z wyborem zostaje. Falsyfikator: podgląd pozostałych ogonem po przyłożeniu (dwa resety)."""
    from horreum.gui import queries
    from test_gui_pasek_szczegol import _anuluj_w_biegu, _brama_po_pierwszym_pliku
    path, ids = _pliki_ze_stosem(tmp_path)
    con, view = _widok_szuflady(path, watek_zapisu=True)
    try:
        _ctrl_a(view)
        _odczekaj_debounce()
        panel = _panel_z_wyborem(view, ids[1])
        _makro_do_stagingu(view)
        stary = view.model._preview
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        resety, odtworzenia = _podsluch_resetow(view, monkeypatch)
        QTest.mouseClick(view.drawer.btn_commit, Qt.LeftButton)
        _anuluj_w_biegu(view, brama, doszlo, stary)
        _odczekaj_debounce()
        oczekujace = {w["frame_id"] for w in queries.pending_cards_for_run(con, view._run_id)}
        assert oczekujace and set(view.model._preview) == oczekujace
        assert (len(resety), len(odtworzenia)) == (1, 1)
        assert (view._lineage_frame_id, view.lineage_bar.selected_frame_ids()) == panel
    finally:
        from test_gui_pola_w_tle import _czekaj
        _czekaj(lambda: not view._wb.is_busy, "wątek zapisu przed zamknięciem")
        view.close()
        con.close()


@pytest.mark.parametrize("podglad", ["aktywny", "zdjety"])
def test_odrzucenie_w_trakcie_przeladowania_wygrywa_z_podgladem_po_zapisie(qapp, tmp_path, monkeypatch, podglad):
    """Kolizja z pisarzem `set_preview`: zapis przerwany „Anuluj”, przeładowanie po nim składa się w tle
    (brama na `_sklad_zbioru` w wątku), a człowiek w tym czasie klika „Odrzuć” w szufladzie - staging
    znika, kolumna podglądu też. Przyłożenie NIE stawia podglądu oczekujących (już odrzuconych): nowsza
    intencja wygrywa (`_odloz_podglad_do_przylozenia` - licznik wołań pisarzy podglądu modelu). Dawny ogon
    `set_preview(pozostale)` przywracał po cichu podgląd odrzuconego stagingu. `zdjety`: panel Rodowód
    zdjął podgląd makra przed „Zatwierdź”, więc „Odrzuć” woła `set_preview({})` na pustym podglądzie - bez
    podmiany obiektu. Falsyfikatory: przyłożenie bez sprawdzenia nowszej intencji (oba warianty - podgląd
    dwóch wpisów po odrzuceniu); intencja z tożsamości obiektu podglądu (`zdjety`)."""
    import threading
    from horreum.gui import grid_workers
    from test_gui_pasek_szczegol import _brama_po_pierwszym_pliku
    from test_gui_pola_w_tle import _czekaj
    path, _ids = _pliki_ze_stosem(tmp_path)
    con, view = _widok_szuflady(path, watek_zapisu=True, zbior_w_tle=True)
    sklad = threading.Event()
    try:
        view.table.clearSelection()
        _klik_komorki(view, _ids[0], 1)
        for fid in _ids[1:]:
            _klik_komorki(view, fid, 1, Qt.ControlModifier)
        _makro_do_stagingu(view)
        assert view._pending_count() == 3 and view.model._preview_active()
        if podglad == "zdjety":
            _klik_przycisku(view.sel_bar.btn_lineage)
            assert view._lineage_panel_open() and not view.model._preview_active()
            assert view._pending_count() == 3 and view.drawer.btn_commit.isVisible()
        brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
        prawdziwy = grid_workers._sklad_zbioru

        def _sklad(*a, **k):
            if threading.current_thread() is not threading.main_thread():
                sklad.wait(30)
            return prawdziwy(*a, **k)
        monkeypatch.setattr(grid_workers, "_sklad_zbioru", _sklad)
        QTest.mouseClick(view.drawer.btn_commit, Qt.LeftButton)
        _czekaj(lambda: doszlo.is_set() and view.drawer.btn_cancel.isVisible(), "pierwszy plik")
        QTest.mouseClick(view.drawer.btn_cancel, Qt.LeftButton)
        brama.set()
        _czekaj(lambda: not view._wb.is_busy and view._zbior_w_drodze(), "przeładowanie po zapisie w drodze")
        assert view._pending_count() == 2
        assert view.drawer.btn_reject.isVisible() and view.drawer.btn_reject.isEnabled()
        QTest.mouseClick(view.drawer.btn_reject, Qt.LeftButton)
        assert view._pending_count() == 0
        sklad.set()
        _czekaj(lambda: not view._zbior_w_drodze(), "przyłożenie zbioru")
        _odczekaj_debounce()
        assert not view.model._preview_active(), view.model._preview
    finally:
        sklad.set()
        _czekaj(lambda: not view._wb.is_busy and not view._zbior_w_drodze(), "wątki przed zamknięciem")
        view.zatrzymaj_pola()
        view.close()
        con.close()


def test_licznik_wolan_podgladu_rosnie_przy_kazdym_pisarzu():
    """Kotwica reguły „nowsza intencja” (`GridTableModel._wersja_podgladu`) rośnie przy KAŻDYM pisarzu
    podglądu: `set_preview` ze zmianą i bez niej (zdjęcie pustego - bez resetu, obiekt podglądu ten sam)
    oraz `set_data(preview=…)`; `set_data` bez podglądu i reset bez podglądu (sort) jej nie ruszają.
    Falsyfikatory: licznik NIEpodbity po wczesnym powrocie `set_preview` (pierwsza asercja po zdjęciu pustego);
    `set_data(preview=…)` bez podbicia."""
    m = grid_mod.GridTableModel()
    base = [{"frame_id": i, "path": f"/a/{i}.fits", "kind": "light"} for i in (1, 2)]
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [])
    w = [m._wersja_podgladu]
    pusty = m._preview
    m.set_preview({})                                   # nic do zdjęcia - bez resetu, ten sam obiekt
    assert m._preview is pusty
    w.append(m._wersja_podgladu)
    m.set_preview({1: {"skipped": "x"}})
    w.append(m._wersja_podgladu)
    m.sort(0, Qt.DescendingOrder)
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [])
    w.append(m._wersja_podgladu)
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [], preview={})
    w.append(m._wersja_podgladu)
    assert [b - a for a, b in zip(w, w[1:])] == [1, 1, 0, 1]


def test_zatrzymanie_widoku_gasi_podglad_odlozony_do_przylozenia(qapp, tmp_path, monkeypatch):
    """Zapis szuflady odkłada podgląd do przyłożenia zbioru, przeładowanie po nim składa się w tle (brama
    na `_sklad_zbioru` w wątku), a widok znika (`zatrzymaj_pola`) - odłożony podgląd schodzi razem z ogonami
    zleceń (`_zatrzymaj_zbior`). Pierwsze przyłożenie po powrocie widoku (przeładowanie synchroniczne)
    zostawia podgląd modelu bez zmian: `set_data` dostaje `preview=None`, nie podgląd sprzed zatrzymania.
    Falsyfikator: `_zatrzymaj_zbior` bez zdjęcia odłożonego podglądu (przyłożenie po powrocie z `{}`)."""
    import threading
    from horreum.gui import grid_workers
    from test_gui_pola_w_tle import _czekaj
    path, ids = _pliki_ze_stosem(tmp_path)
    con, view = _widok_szuflady(path, zbior_w_tle=True)
    sklad = threading.Event()
    try:
        _klik_komorki(view, ids[0], 1)
        _makro_do_stagingu(view)
        assert view.model._preview_active()
        prawdziwy = grid_workers._sklad_zbioru

        def _sklad(*a, **k):
            if threading.current_thread() is not threading.main_thread():
                sklad.wait(30)
            return prawdziwy(*a, **k)
        monkeypatch.setattr(grid_workers, "_sklad_zbioru", _sklad)
        _klik_przycisku(view.drawer.btn_commit)
        assert view._zbior_w_drodze() and view._podglad_przy_przylozeniu is not None
        sklad.set()
        view.zatrzymaj_pola()
        assert view._podglad_przy_przylozeniu is None
        podglady = []
        prawdziwe = view.model.set_data
        monkeypatch.setattr(view.model, "set_data",
                            lambda *a, **k: (podglady.append(k.get("preview")), prawdziwe(*a, **k))[1])
        view.refresh()
        assert podglady == [None]
    finally:
        sklad.set()
        _czekaj(lambda: not view._wb.is_busy, "wątek zapisu przed zamknięciem")
        view.zatrzymaj_pola()
        view.close()
        con.close()


# ---------- AR-263: prawy przycisk nie rusza zaznaczenia - jedna reguła, menu decyduje ----------
#
# Prawdziwy prawy klik przez uchwyt okna przy OBU wyzwalaczach menu: `Release` (Windows - pomocnik
# `tests/prawy_klik.py`) i `Press` (offscreen; pomocnik przypina Release, więc tu własna droga - także
# dla modyfikatorów i dwukliku, z przypięciem wyzwalacza z pomocnika).

from test_gui_lead_copy import widok  # noqa: E402,F401 - fikstura „Kopie niezgodne” (gest kopii wiodącej)
from test_gui_stack_versions import wcon  # noqa: E402,F401 - fikstura bazy „Wersje stosów”

# Wyzwalacze NAZWĄ, nie `Qt.ContextMenuTrigger.*`: enum jest od Qt 6.8, a parametry liczą się przy kolekcji -
# na starszym PySide6 (pakiet `>=6.5`) wywróciłyby moduł, zanim strażnik `przypiecie_wyzwalacza` pominie test.
_WYZWALACZE = ["Press", "Release"]


def _prawy_klik_tabeli(view, punkt, wyzwalacz, mod=Qt.NoModifier, *, dwuklik=False):
    """Prawdziwy prawy klik (`dwuklik` - dwuklik) z modyfikatorami `mod` w `punkt` viewportu tabeli przy
    wyzwalaczu menu `wyzwalacz`; zwraca aktywne menu albo None (czekanie pętlą - gest bez menu to też
    wynik). Zwykły klik przy `Release` idzie pomocnikiem `tests/prawy_klik.py`, reszta tu - z tym samym
    przypięciem wyzwalacza (`przypiecie_wyzwalacza`: Qt < 6.8 - pominięcie z powodem, nowszy bez API -
    błąd testu)."""
    import time
    from prawy_klik import prawy_klik, przypiecie_wyzwalacza
    vp = view.table.viewport()
    hints = przypiecie_wyzwalacza()          # PRZED pierwszym `Qt.ContextMenuTrigger` (API Qt >= 6.8)
    wyzwalacz = getattr(Qt.ContextMenuTrigger, wyzwalacz)
    if wyzwalacz == Qt.ContextMenuTrigger.Release and mod == Qt.NoModifier and not dwuklik:
        return prawy_klik(vp, punkt)
    assert QApplication.activePopupWidget() is None, "przed gestem otwarte menu"
    poprzedni = hints.contextMenuTrigger()
    hints.setContextMenuTrigger(wyzwalacz)
    try:
        uchwyt = vp.window().windowHandle()
        gest = QTest.mouseDClick if dwuklik else QTest.mouseClick
        gest(uchwyt, Qt.RightButton, mod, uchwyt.mapFromGlobal(vp.mapToGlobal(punkt)))
        koniec = time.monotonic() + 0.3
        while QApplication.activePopupWidget() is None and time.monotonic() < koniec:
            QApplication.processEvents()
            time.sleep(0.005)
    finally:
        hints.setContextMenuTrigger(poprzedni)
    return QApplication.activePopupWidget()


def _srodek(view, wiersz, kolumna=1):
    return view.table.visualRect(view.model.index(wiersz, kolumna)).center()


def _zamknij_menu(menu):
    if menu is not None:
        menu.hide()
        QApplication.processEvents()


def _stan(view):
    return _zaznaczone(view), view.table.currentIndex().row()


@pytest.mark.parametrize("cel", ["poza", "w_zaznaczenie", "pusty_obszar", "belka"])
@pytest.mark.parametrize("wyzwalacz", _WYZWALACZE, ids=["press", "release"])
def test_prawy_klik_bez_menu_nic_nie_zmienia(qapp, tmp_path, wyzwalacz, cel):
    """Zwykły widok (menu nie powstaje): prawy klik POZA zaznaczeniem, W zaznaczenie, w pusty obszar pod
    wierszami i na belce grupy - zaznaczenie z Ctrl+kliku i bieżąca komórka bez zmian. Dawniej Qt
    przestawiał je w nacisku: poza - zaznaczenie = kliknięty wiersz, pusty obszar i belka - czyszczenie
    (zmierzone prawdziwym klikiem, wizytacja natywna). Falsyfikator: `_TabelaKlatek` bez nadpisanego
    nacisku i puszczenia prawym."""
    con, view = _widok_dlugi(tmp_path, 5 if cel == "pusty_obszar" else 300)
    try:
        if cel == "belka":
            _wybierz_w_combo(view.combo_group, "kind")
            assert "_group" in view.model._rows[0]
        dane = [i for i, r in enumerate(view.model._rows) if "_group" not in r]
        _klik_komorki(view, view.model._rows[dane[0]]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[dane[2]]["frame_id"], 1, Qt.ControlModifier)
        przed = _stan(view)
        if cel == "poza":
            punkt = _srodek(view, dane[3])
        elif cel == "w_zaznaczenie":
            punkt = _srodek(view, dane[0])
        elif cel == "pusty_obszar":
            punkt = QPoint(60, view.table.visualRect(view.model.index(dane[-1], 1)).bottom() + 40)
            assert view.table.indexAt(punkt).isValid() is False
        else:
            punkt = _srodek(view, 0, 0)
        menu = _prawy_klik_tabeli(view, punkt, wyzwalacz)
        _zamknij_menu(menu)
        assert menu is None
        assert _stan(view) == przed
    finally:
        view.close()
        con.close()


@pytest.mark.parametrize("cel", ["poza", "w_zaznaczenie", "belka"])
@pytest.mark.parametrize("wyzwalacz", _WYZWALACZE, ids=["press", "release"])
def test_prawy_klik_z_menu_zaznacza_wylacznie_klatke_spoza(qapp, tmp_path, wyzwalacz, cel):
    """Perspektywa z sekcją menu (flaga „Zastąpione” wprost): menu powstaje; KLATKA spoza zaznaczenia
    staje się zaznaczeniem i bieżącą (konwencja platformy), klik W zaznaczenie i na belce grupy (nie
    klatka) zostawia zaznaczenie i bieżącą. Falsyfikator: belka liczona jako wiersz spoza zaznaczenia
    (zaznaczenie zdjęte, `selectRow` na belce)."""
    con, view = _widok_dlugi(tmp_path, 300)
    try:
        setattr(view, grid_mod._FLAGA_ZASTAPIONYCH, True)
        if cel == "belka":
            _wybierz_w_combo(view.combo_group, "kind")
        dane = [i for i, r in enumerate(view.model._rows) if "_group" not in r]
        _klik_komorki(view, view.model._rows[dane[0]]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[dane[2]]["frame_id"], 1, Qt.ControlModifier)
        przed = _stan(view)
        wiersz = {"poza": dane[3], "w_zaznaczenie": dane[0], "belka": 0}[cel]
        menu = _prawy_klik_tabeli(view, _srodek(view, wiersz, 0 if cel == "belka" else 1), wyzwalacz)
        try:
            assert menu is view._menu_tabeli
            if cel == "poza":
                assert _stan(view) == ([view.model._rows[wiersz]["frame_id"]], wiersz)
            else:
                assert _stan(view) == przed
        finally:
            _zamknij_menu(menu)
    finally:
        view.close()
        con.close()


# Osobny wiersz na przypadek: przy wyzwalaczu `Press` prawy nacisk w TYM SAMYM punkcie okna co menu
# poprzedniego testu nie doręcza menu tabeli (zmierzone offscreen: `ContextMenu` dochodzi do okna, nie do
# viewportu; w innym punkcie albo w świeżym procesie - dochodzi) - artefakt wejścia testowego, nie gest.
@pytest.mark.parametrize("wyzwalacz, mod, wiersz", [
    ("Press", Qt.ControlModifier, 6), ("Press", Qt.ShiftModifier, 7),
    ("Release", Qt.ControlModifier, 8), ("Release", Qt.ShiftModifier, 9),
], ids=["press-ctrl", "press-shift", "release-ctrl", "release-shift"])
def test_prawy_klik_z_menu_z_modyfikatorem_zaznacza_wylacznie_klatke_spoza(qapp, tmp_path, wyzwalacz, mod, wiersz):
    """Ctrl+prawy i Shift+prawy na klatce spoza zaznaczenia (menu powstaje): klatka staje się JEDYNYM
    zaznaczeniem i bieżącą - modyfikator jej nie dokłada (Ctrl) ani nie robi zakresu od kotwicy (Shift).
    Falsyfikator: `selectRow` - liczy polecenie z modyfikatorów klawiatury w chwili wołania (Ctrl: trzy
    zaznaczone klatki, Shift: pas od kotwicy)."""
    con, view = _widok_dlugi(tmp_path, 300)
    try:
        setattr(view, grid_mod._FLAGA_ZASTAPIONYCH, True)
        _klik_komorki(view, view.model._rows[1]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[3]["frame_id"], 1, Qt.ControlModifier)
        menu = _prawy_klik_tabeli(view, _srodek(view, wiersz), wyzwalacz, mod)
        try:
            assert menu is view._menu_tabeli
            assert _stan(view) == ([view.model._rows[wiersz]["frame_id"]], wiersz)
        finally:
            _zamknij_menu(menu)
    finally:
        view.close()
        con.close()


@pytest.mark.parametrize("klawisz", ["Menu", "Shift+F10"])
def test_menu_z_klawiatury_dla_zaznaczenia_bez_zmiany(qapp, tmp_path, klawisz):
    """Klawisz Menu i Shift+F10 doręczają tabeli (widżetowi z fokusem) to samo zdarzenie -
    `QContextMenuEvent` z przyczyną `Keyboard`, w punkcie bieżącej komórki. `QTest.keyClick` go nie
    wytwarza (zmierzone offscreen i natywnie: 0 zdarzeń menu), natywnie klawisz Menu systemu (`VK_APPS`)
    dał je z przyczyną klawiatura - test doręcza to zdarzenie wprost. Bieżąca komórka POZA zaznaczeniem
    (Ctrl+↓): menu dotyczy zaznaczenia, zaznaczenie i bieżąca bez zmian. Falsyfikator: reguła „klatka
    pod kursorem” także dla klawiatury (zaznaczenie = wiersz bieżącej komórki)."""
    from PySide6.QtGui import QContextMenuEvent
    con, view = _widok_dlugi(tmp_path, 300)
    try:
        setattr(view, grid_mod._FLAGA_ZASTAPIONYCH, True)
        _klik_komorki(view, view.model._rows[1]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[4]["frame_id"], 1, Qt.ControlModifier)
        view.table.setFocus()
        QTest.keyClick(view.table, Qt.Key_Down, Qt.ControlModifier)
        QApplication.processEvents()
        przed = _stan(view)
        assert przed[1] == 5 and not view.table.selectionModel().isRowSelected(5)
        t = view.table
        punkt = t.viewport().mapTo(t, t.visualRect(t.currentIndex()).center())
        QApplication.sendEvent(t, QContextMenuEvent(QContextMenuEvent.Keyboard, punkt, t.mapToGlobal(punkt)))
        QApplication.processEvents()
        menu = QApplication.activePopupWidget()
        try:
            assert menu is view._menu_tabeli
            assert _stan(view) == przed
        finally:
            _zamknij_menu(menu)
    finally:
        view.close()
        con.close()


def test_inna_wersja_qt_prawy_klik_wraca_do_metody_qt(qapp, tmp_path, monkeypatch):
    """Bezpiecznik wersji obejmuje też zdarzenia myszy `_TabelaKlatek`: przy wersji Qt spoza
    `_QT_TABELI_KLATEK` prawy przycisk idzie metodą Qt - prawy klik poza zaznaczeniem przestawia je
    (zachowanie Qt). Falsyfikator: nadpisanie nacisku bez sprawdzenia wersji."""
    from horreum.gui import grid_model
    con, view = _widok_dlugi(tmp_path, 300)
    try:
        _klik_komorki(view, view.model._rows[1]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[3]["frame_id"], 1, Qt.ControlModifier)
        monkeypatch.setattr(grid_model, "qVersion", lambda: "6.10.0")
        _zamknij_menu(_prawy_klik_tabeli(view, _srodek(view, 6), "Release"))
        assert _zaznaczone(view) == [view.model._rows[6]["frame_id"]]
    finally:
        view.close()
        con.close()


@pytest.mark.parametrize("wyzwalacz, dwuklik, wiersz", [
    ("Press", False, 4), ("Press", True, 5),
    ("Release", False, 7), ("Release", True, 8),
], ids=["press-klik", "press-dwuklik", "release-klik", "release-dwuklik"])
def test_prawy_klik_na_komorce_ostatniego_lewego_kliku_bez_gestu_qt(qapp, tmp_path, wyzwalacz, dwuklik, wiersz):
    """Prawy klik i prawy dwuklik W KOMÓRKĘ ostatniego lewego kliku (zwykły widok - menu nie powstaje).
    Nacisk prawym nie dochodzi do Qt, więc `pressedIndex` widoku zostaje z lewego kliku: puszczenie
    prawym oddane metodzie Qt liczy się jako klik tej komórki (`QAbstractItemView::mouseReleaseEvent` -
    `activated` na platformie z aktywacją pojedynczym klikiem, tu styl z `SH_ItemView_ActivateItemOnSingleClick`),
    a dwuklik prawym - jako dwuklik (`doubleClicked`). Żaden sygnał gestu tabeli nie pada, zaznaczenie,
    bieżąca i stan widoku bez zmian. Falsyfikatory: puszczenie prawym przez metodę Qt (`activated`),
    dwuklik prawym przez metodę Qt (`doubleClicked`)."""
    from PySide6.QtWidgets import QAbstractItemView, QProxyStyle, QStyle

    class _AktywacjaKlikiem(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, returnData=None):
            if hint == QStyle.SH_ItemView_ActivateItemOnSingleClick:
                return 1
            return super().styleHint(hint, option, widget, returnData)

    con, view = _widok_dlugi(tmp_path, 300)
    try:
        t = view.table
        styl = _AktywacjaKlikiem()
        styl.setParent(t)                    # żyje tyle, co tabela (`setStyle` nie przejmuje własności)
        t.setStyle(styl)
        _klik_komorki(view, view.model._rows[1]["frame_id"], 1)
        _klik_komorki(view, view.model._rows[wiersz]["frame_id"], 1, Qt.ControlModifier)
        przed = _stan(view)
        sygnaly = []
        for nazwa in ("pressed", "clicked", "doubleClicked", "activated"):
            getattr(t, nazwa).connect(lambda idx, n=nazwa: sygnaly.append((n, idx.row())))
        menu = _prawy_klik_tabeli(view, _srodek(view, wiersz), wyzwalacz, dwuklik=dwuklik)
        _zamknij_menu(menu)
        assert menu is None
        assert sygnaly == []
        assert _stan(view) == przed and t.state() == QAbstractItemView.NoState
    finally:
        view.close()
        con.close()


def _klik_pozycji_menu(menu, akcja):
    """Prawdziwy klik pozycji menu wyskakującego (otwarte - inaczej pozycji nie ma gdzie kliknąć).

    Punkt kliku to środek WIDOCZNEJ części pozycji (AR-307): menu szersze niż ekran Qt przycina do
    ekranu, a pozycja z pełną ścieżką pliku bywa szersza od okna - środek całej pozycji wypadał wtedy
    poza oknem i klik nie trafiał w nic (zależnie od długości ścieżki katalogu testu)."""
    assert menu.isVisible() and akcja.isVisible() and akcja.isEnabled(), akcja.text()
    widoczna = menu.actionGeometry(akcja).intersected(menu.rect())
    assert not widoczna.isEmpty(), f"pozycja poza kadrem menu: {akcja.text()}"
    QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier, widoczna.center())
    QApplication.processEvents()


@pytest.mark.parametrize("wyzwalacz", _WYZWALACZE, ids=["press", "release"])
def test_prawy_klik_zostaw_te_wersje_cel_z_klatki_pod_kursorem(qapp, wcon, wyzwalacz):
    """„Zostaw tę wersję” naprawdę: zaznaczona wersja 102, prawy klik na wersji 101 (poza zaznaczeniem) -
    101 staje się zaznaczeniem i bieżącą, klik pozycji menu kopiuje do schowka ścieżki POZOSTAŁEJ wersji
    (102 - jej ścieżka) i nie rusza zaznaczenia ani bieżącej. Falsyfikator: cel gestu z zaznaczenia sprzed
    prawego kliku (schowek mówiłby ścieżkami 101)."""
    from test_gui_pola_w_tle import _czekaj
    view = grid_mod.FramesView(wcon, now_fn=lambda: NOW)
    view._writeback_async = False
    try:
        view.resize(1400, 800)
        view.show()
        view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
        _odczekaj_debounce()
        QApplication.clipboard().setText("nietknięte")
        _klik_komorki(view, 102, 1)
        menu = _prawy_klik_tabeli(view, _srodek(view, _wiersz(view, 101)), wyzwalacz)
        try:
            assert menu is view._menu_tabeli
            assert _stan(view) == ([101], _wiersz(view, 101))
            _klik_pozycji_menu(menu, view.act_keep_version)
        finally:
            _zamknij_menu(QApplication.activePopupWidget())
        _czekaj(lambda: QApplication.clipboard().text() != "nietknięte", "schowek po geście")
        assert QApplication.clipboard().text().split("\n") == ["/st/IC1795/Ha/stara.xisf", "/kopia/stara.xisf"]
        assert _stan(view) == ([101], _wiersz(view, 101))
    finally:
        view.close()


@pytest.mark.parametrize("wyzwalacz", _WYZWALACZE, ids=["press", "release"])
def test_prawy_klik_ta_kopia_prowadzi_cel_z_klatki_pod_kursorem(qapp, widok, wyzwalacz):
    """„Ta kopia prowadzi” naprawdę (podmenu kopii, wątek tła gestu): perspektywa „Kopie niezgodne” bez
    zaznaczenia, prawy klik na klatce - ona staje się zaznaczeniem, klik w podmenu, klik kopii CLS -
    nagłówek klatki mówi CLS, zaznaczenie i bieżąca na tej klatce po odświeżeniu zbioru. Falsyfikator:
    menu z pustym zaznaczeniem (podmenu kopii bez celu)."""
    from test_gui_lead_copy import _header, _po_gescie
    from test_gui_pola_w_tle import _czekaj
    con, v, fid, _a, _b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    _odczekaj_debounce()
    assert v._frame_ids == [fid] and _zaznaczone(v) == []
    menu = _prawy_klik_tabeli(v, _srodek(v, _wiersz(v, fid)), wyzwalacz)
    try:
        assert menu is v._menu_tabeli
        assert _stan(v) == ([fid], _wiersz(v, fid))
        _klik_pozycji_menu(menu, v._menu_kopii.menuAction())
        _czekaj(v._menu_kopii.isVisible, "podmenu kopii")
        pozycje = [a for a in v._menu_kopii.actions() if not a.isSeparator()]
        _klik_pozycji_menu(v._menu_kopii, pozycje[1])
    finally:
        _zamknij_menu(QApplication.activePopupWidget())
        v._menu_tabeli.hide()
    assert _po_gescie(v)
    _odczekaj_debounce()
    assert _header(con, fid)["filter_raw"] == "CLS"
    assert _stan(v) == ([fid], _wiersz(v, fid))


# ============================================================ kotwica zakresu Shift po resecie modelu (AR-266)


def _shift_strzalka_w_dol(view, n=3):
    view.table.setFocus()
    for _ in range(n):
        QTest.keyClick(view.table, Qt.Key_Down, Qt.ShiftModifier)
        QApplication.processEvents()


def _zakres_od(view, od, do):
    """frame_id wierszy klatek między wierszem `od` a wierszem `do` (włącznie) w BIEŻĄCYM porządku."""
    ra, rd = _wiersz(view, od), _wiersz(view, do)
    return sorted(r["frame_id"] for r in view.model._rows[min(ra, rd):max(ra, rd) + 1] if "_group" not in r)


def _klatka_za(view, b, a, krok=3):
    """Klatka `krok` wierszy klatek za B, w kierunku od A (zakres od A i od B różnią się wtedy)."""
    kier = 1 if _wiersz(view, a) <= _wiersz(view, b) else -1
    w, n = _wiersz(view, b), 0
    while n < krok:
        w += kier
        if "_group" not in view.model._rows[w]:
            n += 1
    return view.model._rows[w]["frame_id"]


def _klik_i_zakres(view, wejscie):
    """Klik A, potem Shift+klik B (albo Shift+↓ × 3) - zakres z kotwicą na A. Zwraca (A, B)."""
    view.table.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    a = view.model._rows[5]["frame_id"]
    _klik_komorki(view, a, 1)
    if wejscie == "mysz":
        b = view.model._rows[8]["frame_id"]
        _klik_komorki(view, b, 1, Qt.ShiftModifier)
    else:
        _shift_strzalka_w_dol(view)
        b = view.model._rows[view.table.currentIndex().row()]["frame_id"]
    assert _zaznaczone(view) == _zakres_od(view, a, b) and len(_zaznaczone(view)) == 4
    return a, b


@pytest.mark.parametrize("wejscie", ["mysz", "klawiatura"])
@pytest.mark.parametrize("gest", ["sort", "grupowanie", "podglad", "przeladowanie"])
def test_shift_po_resecie_liczy_zakres_od_kotwicy(dluga, gest, wejscie):
    """AR-266: klik A, Shift+klik B (albo Shift+↓), gest z resetem modelu, Shift+klik D - zakres od A w nowym
    porządku, jak bez resetu (7 klatek), nie od B (4). Qt trzyma kotwicę prywatnie, reset ją unieważnia,
    a odtworzenie bieżącej komórki stawiało ją na B. Człowiek puszcza Shift przed gestem (QTest trzyma
    modyfikator w stanie aplikacji, więc test puszcza go jawnie). Falsyfikatory: migawka bez kotwicy,
    tryb „trzymaj” = metoda Qt (krok bieżącej przestawia kotwicę na B)."""
    view = dluga
    a, b = _klik_i_zakres(view, wejscie)
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    przed = _zaznaczone(view)
    _gest_resetu(view, gest)
    assert _zaznaczone(view) == przed
    d = _klatka_za(view, b, a)
    _klik_komorki(view, d, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, a, d), (len(_zaznaczone(view)), len(_zakres_od(view, a, d)))
    assert _zakres_od(view, a, d) != _zakres_od(view, b, d), "od A = od B - test nic by nie mierzył"


def test_shift_wcisniety_w_chwili_resetu_dalej_od_kotwicy(dluga):
    """AR-266: Shift trzymany w chwili przeładowania (stan modyfikatorów aplikacji z Shift) - Qt nie ustawia
    wtedy kotwicy przy zmianie bieżącej, więc odtworzenie wymusza ją krokiem „ustaw”. Falsyfikator: tryb
    „ustaw” = metoda Qt (kotwica nieważna, Qt bierze bieżącą B)."""
    from PySide6.QtGui import QGuiApplication
    view = dluga
    a, b = _klik_i_zakres(view, "mysz")
    assert QGuiApplication.keyboardModifiers() & Qt.ShiftModifier, "Shift puszczony - test nic by nie mierzył"
    view.przeladuj_z_zaznaczeniem()
    _odczekaj_debounce()
    d = _klatka_za(view, b, a)
    _klik_komorki(view, d, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, a, d)


def test_lustro_kotwicy_idzie_za_regula_qt(dluga):
    """Lustro kotwicy (`_TabelaKlatek.kotwica`) bez resetu: klik - kotwica na klikniętej, Shift+klik - zostaje,
    Ctrl+klik w BIEŻĄCĄ komórkę - na niej (Qt przestawia kotwicę w naciśnięciu, a `currentChanged` nie
    przychodzi, bo bieżąca się nie zmienia), Ctrl+klik - na klikniętej, ↓ bez Shift - na nowej bieżącej,
    Shift+↓ - zostaje. Falsyfikator: lustro bez `mousePressEvent` (po Ctrl+kliku w bieżącą zostaje na A)."""
    view = dluga
    view.table.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    rows = view.model._rows

    def kotwica():
        return rows[view.table.kotwica().row()]["frame_id"]
    a, b, c, d = (rows[w]["frame_id"] for w in (2, 6, 10, 12))
    _klik_komorki(view, a, 1)
    assert kotwica() == a
    _klik_komorki(view, b, 1, Qt.ShiftModifier)
    assert kotwica() == a and _zaznaczone(view) == _zakres_od(view, a, b)
    _klik_komorki(view, b, 1, Qt.ControlModifier)
    assert kotwica() == b
    _klik_komorki(view, c, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, a, c), "Qt liczy zakres od B"
    _klik_komorki(view, d, 1, Qt.ControlModifier)
    assert kotwica() == d
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key_Down, Qt.NoModifier)
    QApplication.processEvents()
    nowa = rows[view.table.currentIndex().row()]["frame_id"]
    assert kotwica() == nowa
    _shift_strzalka_w_dol(view, 2)
    assert kotwica() == nowa and _zaznaczone(view) == _zakres_od(
        view, nowa, rows[view.table.currentIndex().row()]["frame_id"])


def test_inna_wersja_qt_kotwica_jak_qt(dluga, monkeypatch):
    """Bezpiecznik wersji (`_QT_TABELI_KLATEK`) obejmuje lustro, `selectionCommand` i `postaw_biezaca`: przy
    innej wersji Qt tabela zachowuje się jak Qt (po sorcie zakres od bieżącej B), bez wyjątku. Bezpieczniki
    stoją warstwami (każdy z trzech sam wyłącza krok kotwicy), więc falsyfikatorem jest zdjęcie wszystkich
    trzech naraz - zakres od A."""
    from horreum.gui import grid_model
    view = dluga
    monkeypatch.setattr(grid_model, "qVersion", lambda: "6.10.0")
    a, b = _klik_i_zakres(view, "mysz")
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    _gest_resetu(view, "sort")
    d = _klatka_za(view, b, a)
    _klik_komorki(view, d, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, b, d)


def test_kotwica_spoza_zbioru_zostawia_biezaca(dluga):
    """Kotwica, której klatki po przeładowaniu nie ma w zbiorze (prawdziwe przeładowanie nie-nawigacyjne
    po zniknięciu klatki A z bazy): zaznaczenie wraca bez A, bieżąca wraca na B i jest kotwicą - Shift+klik
    liczy zakres od B, bez wyjątku. Falsyfikator: kotwica spoza zbioru stawiana na pierwszym wierszu."""
    view = dluga
    a, b = _klik_i_zakres(view, "mysz")
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    with view.con:
        view.con.execute("DELETE FROM location WHERE frame_id = ?", (a,))
        view.con.execute("DELETE FROM frame WHERE id = ?", (a,))
    view.przeladuj_z_zaznaczeniem()
    _odczekaj_debounce()
    assert a not in view._frame_ids and b in _zaznaczone(view)
    assert view.model._rows[view.table.currentIndex().row()]["frame_id"] == b
    assert view.model._rows[view.table.kotwica().row()]["frame_id"] == b
    d = view.model._rows[_wiersz(view, b) + 3]["frame_id"]
    _klik_komorki(view, d, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, b, d)


# ============================================================ kotwica Shift+strzałki przy nieważnej kotwicy (AR-305)


def _shift_strzalki_bez_biezacej(view):
    """Puste zaznaczenie i bez bieżącej, sort klikiem (reset modelu - nic do odtworzenia), Shift+↓ dwa razy.
    Qt: pierwszy ruch zostawia kotwicę nieważną (bieżącej sprzed ruchu nie było), drugi bierze za kotwicę
    bieżącą sprzed ruchu - klatkę pierwszego ruchu. Zwraca jej `frame_id`."""
    view.table.verticalScrollBar().setValue(0)
    view.table.selectionModel().clear()
    QApplication.processEvents()
    _gest_resetu(view, "sort")
    assert not view.table.currentIndex().isValid() and not view.table.kotwica().isValid()
    _shift_strzalka_w_dol(view, 1)
    a = view.model._rows[view.table.currentIndex().row()]["frame_id"]
    _shift_strzalka_w_dol(view, 1)
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    return a


def test_shift_strzalka_przy_niewaznej_kotwicy_jak_qt(dluga):
    """AR-305: po resecie bez bieżącej Shift+↓ ×2 - lustro kotwicy stoi tam, gdzie kotwica Qt (klatka pierwszego
    ruchu, `qabstractitemview.cpp` 6.9.2 `:2453-2454`), Shift+klik D liczy zakres od niej, a po kolejnym sorcie
    Shift+klik E dalej od tej samej klatki. Dawniej lustro zostawało nieważne i Shift+klik stawiał je na bieżącej
    - po resecie zakres od klatki o wiersz dalej niż Qt. Falsyfikator: `_TabelaKlatek` bez `keyPressEvent`."""
    view = dluga
    a = _shift_strzalki_bez_biezacej(view)
    assert view.model._rows[view.table.kotwica().row()]["frame_id"] == a
    d = view.model._rows[_wiersz(view, a) + 6]["frame_id"]
    _klik_komorki(view, d, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, a, d)
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    _gest_resetu(view, "sort")
    e = _klatka_za(view, d, a)
    _klik_komorki(view, e, 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == _zakres_od(view, a, e), (len(_zaznaczone(view)), len(_zakres_od(view, a, e)))


def test_shift_strzalka_przy_waznej_kotwicy_lustro_nietkniete(dluga):
    """Shift+↓ przy WAŻNEJ kotwicy (klik A) nie przestawia lustra - Qt też nie (kotwica zostaje na A).
    Falsyfikator: lustro w `keyPressEvent` bez warunku nieważnej kotwicy (kotwica na bieżącej sprzed ruchu)."""
    view = dluga
    view.table.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    a = view.model._rows[4]["frame_id"]
    _klik_komorki(view, a, 1)
    _shift_strzalka_w_dol(view, 3)
    QTest.keyRelease(view.table, Qt.Key_Shift, Qt.NoModifier)
    assert view.model._rows[view.table.kotwica().row()]["frame_id"] == a


def test_inna_wersja_qt_klawiatura_jak_qt(dluga, monkeypatch):
    """Bezpiecznik wersji (`_QT_TABELI_KLATEK`) obejmuje `keyPressEvent`: przy innej wersji Qt klawiatura idzie
    metodą Qt bez lustra - kotwica lustra po Shift+↓ ×2 zostaje nieważna, bez wyjątku. Falsyfikator:
    `keyPressEvent` bez bezpiecznika (lustro ustawione przy obcej wersji)."""
    from horreum.gui import grid_model
    view = dluga
    monkeypatch.setattr(grid_model, "qVersion", lambda: "6.10.0")
    _shift_strzalki_bez_biezacej(view)
    assert not view.table.kotwica().isValid()
