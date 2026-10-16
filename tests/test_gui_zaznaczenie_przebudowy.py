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


def test_zaznaczenie_ponizej_progu_wraca_po_sorcie(stos, monkeypatch):
    """Próg odtworzenia liczy komórki (wiersze zaznaczenia × kolumny); zaznaczenie równe progowi
    wraca. Próg podmieniony na małą liczbę - test bez tysięcy wierszy. Falsyfikator: `>=` zamiast
    `>` w warunku progu."""
    view = stos
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 2 * view.model.columnCount())
    _klik_naglowka(view, view.model.base_col("path"))
    assert _zaznaczone(view) == [3, 10]
    assert view.count_label.text().endswith(i18n.t_plural("grid.selected", 2))


@pytest.mark.parametrize("gest", ["sort", "grupowanie"])
def test_zaznaczenie_ponad_progiem_schodzi_a_ekran_mowi_prawde(stos, monkeypatch, gest):
    """Zaznaczenie ponad progiem reset zdejmuje (odtworzenie kosztowałoby sekundy - pomiar przy
    `_PROG_ODTWORZENIA_KOMOREK`), a ekran mówi prawdę: licznik paska bez „zaznaczonych", panel
    „Rodowód" bez stosu, którego nikt już nie zaznacza, zdanie na pasku z liczbą klatek.
    Falsyfikatory: próg zdjęty (zaznaczenie wraca); bez zdania; bez `_update_count()` (licznik dalej
    „2 zaznaczone"); bez `_refresh_lineage()` (panel dalej pokazuje stos)."""
    view = stos
    zdania = []
    view.status_message.connect(zdania.append)
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 2 * view.model.columnCount() - 1)
    if gest == "sort":
        _klik_naglowka(view, view.model.base_col("path"))
    else:
        _wybierz_w_combo(view.combo_group, "kind")
    _odczekaj_debounce()
    assert _zaznaczone(view) == []
    assert view.count_label.text() == i18n.t_plural("grid.frames", 4)
    assert zdania[-1] == i18n.t_plural("grid.sel.restore_too_big", 2)
    assert view.lineage_bar.head.text() == i18n.t("grid.lin.hint.none")


@pytest.mark.parametrize("n, poczatek", [(1, "Zaznaczenie 1 klatki zdjęte"),
                                         (2, "Zaznaczenie 2 klatek zdjęte"),
                                         (5, "Zaznaczenie 5 klatek zdjęte"),
                                         (12, "Zaznaczenie 12 klatek zdjęte"),
                                         (22, "Zaznaczenie 22 klatek zdjęte")])
def test_zdanie_zdjetego_zaznaczenia_sie_odmienia(n, poczatek):
    assert i18n.t_plural("grid.sel.restore_too_big", n).startswith(poczatek)
    i18n.set_lang("en")
    assert i18n.t_plural("grid.sel.restore_too_big", n).startswith(
        f"Selection of {n} frame cleared" if n == 1 else f"Selection of {n} frames cleared")


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
    `flags()` o każdą komórkę (kopia pf4: 255 909 wywołań, 2,7-3,5 s na Ctrl+A i tyle samo przy
    odtworzeniu zaznaczenia po sorcie). Relacja, nie liczba: przybywa wierszy - liczba wywołań rośnie
    najwyżej o jedno na wiersz, nie o liczbę kolumn na wiersz. Falsyfikator: zdejmij własny model
    zaznaczenia nagłówka w `_build_ui` (wzrost = wiersze × kolumny)."""
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


# ---------- próg kosztu: cel gestu, układ po przebudowie, klatki zamiast wierszy, przyłożenie ----------

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


def test_podglad_nazw_ponad_progiem_nie_zmienia_celu_stagingu(nazwy, monkeypatch):
    """Dwie z trzech klatek zaznaczone, próg poniżej ich komórek: „Podgląd” nazw (reset podglądu)
    zostawia zaznaczenie - cel gestu - więc „Do stagingu” bierze te dwie, nie cały widok. Kliki
    prawdziwe. Falsyfikator: reset podglądu pod progiem (zaznaczenie znika, staging bierze 3)."""
    from horreum import writeback
    from horreum.gui import queries
    view, con = nazwy
    ids = _kolejnosc(view)
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    cel = sorted([ids[0], ids[2]])
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 2 * view.model.columnCount() - 1)
    _klik_przycisku(view.sel_bar.btn_rename)
    _klik_przycisku(view.rename_bar.btn_prev)
    assert view.model._preview_active()
    assert _zaznaczone(view) == cel
    _klik_przycisku(view.rename_bar.btn_stage)
    zakres = sorted(queries.frame_for_location(con, r["location_id"])
                    for r in writeback.renames_for_run(con, view._rename_run_id))
    assert zakres == cel


def test_prog_liczy_kolumny_ukladu_po_przebudowie(stos, monkeypatch):
    """Próg równy komórkom zaznaczenia w prezentacji Znajdź (mniej kolumn niż klasyczna): wejście
    w Znajdź odtwarza (decyduje układ PO przebudowie), powrót do klasycznej - więcej kolumn - zdejmuje
    ze zdaniem. Falsyfikator: kolumny z układu sprzed resetu (`_znaczenia_kolumn`)."""
    view = stos
    klasyczna = view.model.columnCount()
    view.set_presentation(grid_mod.PREZENTACJA_ZNAJDZ)
    znajdz = view.model.columnCount()
    view.set_presentation(grid_mod.PREZENTACJA_KLASYCZNA)
    assert znajdz < klasyczna and _zaznaczone(view) == [3, 10]
    zdania = []
    view.status_message.connect(zdania.append)
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 2 * znajdz)
    view.set_presentation(grid_mod.PREZENTACJA_ZNAJDZ)
    assert _zaznaczone(view) == [3, 10]
    view.set_presentation(grid_mod.PREZENTACJA_KLASYCZNA)
    assert _zaznaczone(view) == []
    assert zdania[-1] == i18n.t_plural("grid.sel.restore_too_big", 2)


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


def test_przeladowanie_po_kolumnach_ponad_progiem_zdejmuje_ze_zdaniem(stos, monkeypatch):
    """Przeładowanie nie-nawigacyjne (klik pola w „Polach”) ma ten sam próg, co reset lokalny:
    ponad nim zaznaczenie nie wraca, licznik bez „zaznaczonych”, panel bez stosu, zdanie po raporcie
    wczytania. Falsyfikator: `_zastosuj_zbior` bez progu (zaznaczenie wraca)."""
    from test_gui_pola_w_tle import _klik_pola
    view = stos
    zdania = []
    view.status_message.connect(zdania.append)
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 1)
    _klik_pola(view, "GAIN")
    _odczekaj_debounce()
    assert "GAIN" not in view.model._keywords
    assert _zaznaczone(view) == []
    assert view.count_label.text() == i18n.t_plural("grid.frames", 4)
    assert zdania[-1] == i18n.t_plural("grid.sel.restore_too_big", 2)
    assert view.lineage_bar.head.text() == i18n.t("grid.lin.hint.none")


def test_zapis_szuflady_ponad_progiem_zdanie_gestu_mowi_o_zdjeciu(pliki, monkeypatch):
    """Zapis szuflady przeładowuje zbiór ze znacznikiem nie-nawigacyjnym; ponad progiem zaznaczenie
    nie wraca, a ZDANIE GESTU (ostatnie na pasku) niesie człon o zdjęciu. Falsyfikator: ogon gestu
    bez członu `grid.sel.restore_too_big_tail`."""
    view, _tmp = pliki
    zdania = []
    view.status_message.connect(zdania.append)
    ids = _kolejnosc(view)
    _klik_komorki(view, ids[0], 1)
    _klik_komorki(view, ids[2], 1, Qt.ControlModifier)
    _klik_przycisku(view.sel_bar.btn_macro)
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_expr.setText("EQ6")
    _klik_przycisku(view.macro_bar.btn_stage)
    assert _zaznaczone(view) == sorted([ids[0], ids[2]]), "podgląd stagingu nie zdejmuje celu"
    monkeypatch.setattr(grid_mod, "_PROG_ODTWORZENIA_KOMOREK", 1)
    _klik_przycisku(view.drawer.btn_commit)
    _odczekaj_debounce()
    assert _zaznaczone(view) == []
    assert view.count_label.text() == i18n.t_plural("grid.frames", 3)
    assert zdania[-1].endswith(i18n.t_plural("grid.sel.restore_too_big_tail", 2))


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
