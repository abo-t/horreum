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
    """Menu kontekstowe na wierszu (`QContextMenuEvent` na viewporcie - droga prawego kliku Qt)."""
    from PySide6.QtGui import QContextMenuEvent
    vp = view.table.viewport()
    punkt = view.table.visualRect(view.model.index(wiersz, 1)).center()
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, punkt, vp.mapToGlobal(punkt)))
    QApplication.processEvents()


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


def test_shift_klik_po_odtworzeniu_zastepuje_cale_zaznaczenie(dluga):
    """ŚWIADOMY DŁUG - test pinuje DZISIEJSZE zachowanie, nie regułę docelową. Klik A, Ctrl+klik B, sort
    klikiem, Shift+klik C trzy wiersze nad B. Przed sortem Qt trzyma A w części TRWAŁEJ zaznaczenia,
    a Shift+klik podmienia tylko część BIEŻĄCĄ (od kotwicy B); odtworzenie po sorcie kładzie całe
    zaznaczenie jednym `select()` w część bieżącą, więc Shift+klik zastępuje je w całości - zostaje pas od
    C do B, A wypada. Wariant docelowy: migawka zachowuje podział na część trwałą i bieżącą."""
    view = dluga
    vb = view.table.verticalScrollBar()
    vb.setValue(0)
    QApplication.processEvents()
    a = view.model._rows[view.table.rowAt(view.table.viewport().height() // 8)]["frame_id"]
    b = view.model._rows[view.table.rowAt(view.table.viewport().height() // 4)]["frame_id"]
    _klik_komorki(view, a, 1)
    _klik_komorki(view, b, 1, Qt.ControlModifier)
    assert _zaznaczone(view) == sorted([a, b])
    _klik_naglowka(view, view.model.base_col("path"))
    _odczekaj_debounce()
    assert _zaznaczone(view) == sorted([a, b])
    wiersz = _wiersz(view, b)
    assert view.table.currentIndex().row() == wiersz and wiersz >= 3
    pas = list(range(wiersz - 3, wiersz + 1))
    assert _wiersz(view, a) not in pas, "A w pasie - test nic by nie mierzył"
    _klik_komorki(view, view.model._rows[wiersz - 3]["frame_id"], 1, Qt.ShiftModifier)
    assert _zaznaczone(view) == sorted(view.model._rows[i]["frame_id"] for i in pas)
    assert a not in _zaznaczone(view)


@pytest.mark.parametrize("gest", ["grupowanie", "przeladowanie"])
def test_500_klatek_wraca_po_grupowaniu_i_nienawigacyjnym_przeladowaniu(qapp, tmp_path, gest):
    """500 klatek × kolumny tabeli - ponad dawnym progiem 3 750 komórek: Ctrl+A, potem „Grupuj wg:
    Rodzaj” albo nie-nawigacyjne przeładowanie tego samego zbioru (`przeladuj_z_zaznaczeniem` - droga
    wyniku Pól, Dostawy, kolumn ręką): wraca całe zaznaczenie i licznik je liczy. Falsyfikator: próg
    ~250 wierszy w `_zaznaczenie_po_resecie` albo w `_zastosuj_zbior`."""
    con, view = _widok_dlugi(tmp_path, 500)
    try:
        assert 500 * view.model.columnCount() > 3_750
        _ctrl_a(view)
        if gest == "grupowanie":
            _wybierz_w_combo(view.combo_group, "kind")
            assert "_group" in view.model._rows[0]
        else:
            view.przeladuj_z_zaznaczeniem()
        _odczekaj_debounce()
        assert _zaznaczone(view) == list(range(1, 501))
        assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 500))
    finally:
        view.close()
        con.close()
