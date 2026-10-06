"""Drogi ręki w oknie (offscreen): wiersze Porządków osi sprzętu, stanowiska i faktu zatrzymanego
(AR-59, AR-41) oraz edycja jednej komórki keyworda do szuflady makra (AR-61).

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo, resolver, supersede, writeback
from horreum.gui import queries, rows, tasks as tasks_mod
from horreum.gui.app import _REVIEW_TAG, MainWindow, NAV_PORZADKI
from horreum.gui.grid import BASE_COLS, PRESET_SUPERSEDED

from fixture_s8 import NOW, build

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QStyleOptionViewItem


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    """Pokrycie pól Zbiorów inline - wzorzec `test_gui_mainwindow.py` (bez wątku tła w pomiarze)."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _s8(tmp_path):
    path = str(tmp_path / "s8.db")
    build(path, object_axis=True)
    return path


def _wiersz(win, key):
    lista = win.tasks_view.tasks
    for i in range(lista.count()):
        if lista.item(i).data(Qt.UserRole) == key:
            return lista.item(i)
    raise AssertionError(f"brak wiersza {key!r}")


# ---------------------------------------------------------------- AR-59: wiersze osi

def test_wiersze_osi_licza_klatki_od_wlascicieli_predykatow(qapp, tmp_path):
    """Liczby wierszy „Klatki bez zestawu" i „Klatki bez stanowiska" to liczby właścicieli
    predykatów - kubełka sprzętu kolejki przeglądu i wejścia gestu „Wskaż stanowisko…" - a lista
    pod klikiem sprzętu (lustro) liczy to samo. Wiersze są ROBOTĄ: pogrubione, nie szare, w plakietce.

    Falsyfikator: wróć wiersze do `_BEZ_ROBOTY` - pogrubienie i plakietka spadną."""
    win = MainWindow(_s8(tmp_path))
    try:
        st = resolver.review_state(win.con)
        bez_zestawu = st.no_config
        bez_stanowiska = len(queries.observatory_review_frames(win.con))
        assert bez_zestawu == len(queries.config_review_frames(win.con)) > 0
        assert bez_stanowiska > 0
        for key, n in (("config_review_frames", bez_zestawu),
                       ("observatory_review_frames", bez_stanowiska)):
            it = _wiersz(win, key)
            assert it.data(rows.SECONDARY) == f"{n}  ›"
            assert it.data(rows.STRONG) is True
            assert it.foreground().color() != tasks_mod._DIM["fg"]
        # plakietka: 4 dotychczasowe wiersze robocze fikstury + dwa nowe
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (6)"
        assert "Przypisz zestaw…" in _wiersz(win, "config_review_frames").toolTip()
        assert "Wskaż stanowisko…" in _wiersz(win, "observatory_review_frames").toolTip()
    finally:
        win.close()


def test_klik_w_wiersz_osi_prowadzi_do_gestu(qapp, tmp_path):
    """„Klatki bez zestawu" otwiera przegląd obiektów z ZAZNACZONYM kubełkiem sprzętu (lista klatek
    i gest gotowe), „Klatki bez stanowiska" - podstronę osi obserwatorium z gestem wskazania."""
    win = MainWindow(_s8(tmp_path))
    try:
        tv = win.tasks_view
        tv.tasks.itemClicked.emit(_wiersz(win, "config_review_frames"))
        assert tv.pages.currentIndex() == tasks_mod._PAGE_OBJECTS
        assert tv.object_view.review.currentItem().data(_REVIEW_TAG) == "config_review"
        tv._on_back()
        tv.tasks.itemClicked.emit(_wiersz(win, "observatory_review_frames"))
        assert tv.pages.currentIndex() == tasks_mod._PAGE_OBSERVATORY
    finally:
        win.close()


def test_klik_po_zmianie_stanu_przeladowuje_kolejke_i_zapala_gest(qapp, tmp_path):
    """Montaż przy zerze klatek bez zestawu, potem stan bazy daje jedną: licznik jest świeży po
    `refresh_counts`, a klik musi przeładować kolejkę przeglądu, żeby znaleźć kubełek, zaznaczyć go
    i zapalić gest. Falsyfikator: zdejmij `object_view.refresh()` z `_zaznacz_kubelek`."""
    path = _s8(tmp_path)
    con = db.open_db(path)
    cel = con.execute("SELECT config_id FROM frame WHERE config_id IS NOT NULL LIMIT 1").fetchone()[0]
    puste = [r["frame_id"] for r in queries.config_review_frames(con)]
    for fid in puste:                                  # zero przy montażu
        con.execute("UPDATE frame SET config_id = ? WHERE id = ?", (cel, fid))
    con.commit()
    con.close()
    win = MainWindow(path)
    try:
        tv = win.tasks_view
        assert _wiersz(win, "config_review_frames").data(rows.SECONDARY) == "0  ›"
        win.con.execute("UPDATE frame SET config_id = NULL WHERE id = ?", (puste[0],))
        win.con.commit()
        tv.refresh_counts()
        it = _wiersz(win, "config_review_frames")
        assert it.data(rows.SECONDARY) == "1  ›"
        tv.tasks.itemClicked.emit(it)
        assert tv.object_view.review.currentItem().data(_REVIEW_TAG) == "config_review"
        assert tv.object_view.set_config_btn.isEnabled()
        assert tv.object_view.frames.rowCount() == 1
        # Drugi klik przy już zaznaczonym kubełku dalej drąży (lista ze stanu, nie z pamięci).
        tv._on_back()
        tv.object_view.frames.setRowCount(0)
        tv.tasks.itemClicked.emit(it)
        assert tv.object_view.frames.rowCount() == 1
    finally:
        win.close()


def test_wiersze_osi_na_pustej_bazie_milcza_szarym_zerem(qapp, tmp_path):
    """Zero to „nic do zrobienia": szare, bez pogrubienia, bez podpowiedzi o klatkach, których nie
    ma - i wciąż klikalne (podstrona jest drogą do osi)."""
    path = str(tmp_path / "pusta.db")
    db.open_db(path).close()
    win = MainWindow(path)
    try:
        for key in ("config_review_frames", "observatory_review_frames", "object_kept_frames"):
            it = _wiersz(win, key)
            assert it.data(rows.SECONDARY) == "0  ›"
            assert it.data(rows.STRONG) is False
            assert it.foreground().color() == tasks_mod._DIM["fg"]
            assert it.toolTip() == ""
            assert it.flags() & Qt.ItemIsEnabled
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki"
    finally:
        win.close()


# ---------------------------------------------------------------- AR-41: fakt zatrzymany

def test_fakt_zatrzymany_jest_widoczny_ale_nie_jest_robota(qapp, tmp_path):
    """Werdykt obiektu z ręki na klatce zastąpionej flatem: wiersz liczy 1, prowadzi do perspektywy
    „Zastąpione", a mimo liczby > 0 jest szary i poza plakietką - żaden gest go nie opróżni."""
    path = _s8(tmp_path)
    con = db.open_db(path)
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a = repo.upsert_frame(con, sha1_data="zat-a", kind="light", filetype="fits", camera_id=None,
                          now=NOW)[0]
    b = repo.upsert_frame(con, sha1_data="zat-b", kind="flat", filetype="fits", camera_id=None,
                          now=NOW)[0]
    repo.assign_object(con, frame_id=a, object_id=oid, object_source="user", now=NOW)
    lid = repo.add_location(con, frame_id=a, volume="V", path="/z/a.fits", now=NOW)[0]
    repo.rebind_location(con, location_id=lid, frame_after=b, now=NOW)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    con.close()
    win = MainWindow(path)
    try:
        assert supersede.kept_object_facts(win.con) == [(a, b)]
        it = _wiersz(win, "object_kept_frames")
        assert it.data(rows.SECONDARY) == "1  ›"
        assert it.data(rows.STRONG) is False
        assert it.foreground().color() == tasks_mod._DIM["fg"]
        assert "Zastąpione" in it.toolTip()
        perspektywy = []
        win.tasks_view.open_collection.connect(perspektywy.append)
        win.tasks_view._on_task_clicked(it)
        assert perspektywy == [PRESET_SUPERSEDED]
    finally:
        win.close()


# ---------------------------------------------------------------- AR-61: edycja komórki

@pytest.fixture
def wb_view(qapp, tmp_path):
    """FramesView nad bazą z JEDNYM realnym plikiem FITS - wzorzec `test_gui_grid.wb_view`."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    from horreum.gui.grid import FramesView
    p = tmp_path / "wb.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBSERVER"] = "Ja"
    hdu.writeto(str(p), overwrite=True)
    con = db.open_db(str(tmp_path / "wb.db"))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    yield v, con, p
    con.close()


def _kol(view, keyword):
    return len(BASE_COLS) + view.model._kw_off() + view.model._keywords.index(keyword)


def _komunikaty(view):
    out = []
    view.status_message.connect(out.append)
    return out


def test_komorka_keyworda_edytowalna_bazowa_nie(wb_view):
    """Edytowalna jest WYŁĄCZNIE komórka keyworda klatki, w którą makro może pisać. RAW i klatka bez
    jednej obecnej kopii - nie (bramki tanie, z faktów wiersza)."""
    view, con, p = wb_view
    m = view.model
    idx = m.index(0, _kol(view, "TELESCOP"))
    assert m.flags(idx) & Qt.ItemIsEditable
    assert not m.flags(m.index(0, 0)) & Qt.ItemIsEditable
    assert m.data(idx, Qt.EditRole) == "RC8"
    m._rows[0]["filetype"] = "raw"
    assert not m.flags(idx) & Qt.ItemIsEditable
    m._rows[0]["filetype"] = "fits"
    m._rows[0]["n_present"] = 2
    assert not m.flags(idx) & Qt.ItemIsEditable


def test_zajetosc_zdejmuje_edycje(wb_view):
    """Etap Dostawy i cudzy zapis plików gaszą wyzwalacze edycji i edytowalność komórek; koniec
    zajętości je przywraca. Edytor otwarty przed zajętością odbija bramka w `_on_cell_edit`."""
    view, con, p = wb_view
    idx = view.model.index(0, _kol(view, "TELESCOP"))
    view.set_busy(True)
    assert view.table.editTriggers() == QAbstractItemView.NoEditTriggers
    assert not view.model.flags(idx) & Qt.ItemIsEditable
    view.set_busy(False)
    assert view.table.editTriggers() == view._edit_triggers
    assert view.model.flags(idx) & Qt.ItemIsEditable
    view.set_writeback_busy(True)
    assert view.table.editTriggers() == QAbstractItemView.NoEditTriggers
    msg = _komunikaty(view)
    fid = view.model._rows[0]["frame_id"]
    view._on_cell_edit(fid, "TELESCOP", "EQ6", "")
    assert view._pending_count() == 0 and msg
    view.set_writeback_busy(False)
    assert view.model.flags(idx) & Qt.ItemIsEditable


def test_edycja_komorki_idzie_do_szuflady_makra_i_zastepuje_sie(wb_view):
    """Wpis w komórkę stage'uje się pod przebiegiem makra (`_run_id`), pokazuje w podglądzie
    „stara → nowa" i liczy w szufladzie. Druga edycja tej samej karty zastępuje pierwszą."""
    view, con, p = wb_view
    msg = _komunikaty(view)
    idx = view.model.index(0, _kol(view, "TELESCOP"))
    view.model.setData(idx, "EQ6")
    assert view._run_id is not None and view._pending_count() == 1 and view.drawer._n == 1
    pcol = view.model._preview_col()
    assert view.model.data(view.model.index(0, pcol), Qt.DisplayRole) == "RC8 → EQ6"
    assert "w szufladzie" in msg[-1]
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ8")
    wpisy = writeback.pending_for_run(con, view._run_id)
    assert [(w["keyword"], w["new_value"]) for w in wpisy] == [("TELESCOP", "EQ8")]
    assert "zastąpiła" in msg[-1]


def test_delegat_niesie_komentarz_a_zamkniecie_bez_zmiany_nic_nie_stageuje(wb_view):
    """Pole komentarza edytora ma znaczenie pola `MacroBar`; edytor zamknięty bez zmiany nie
    dokłada do szuflady `set` na tę samą wartość."""
    view, con, p = wb_view
    idx = view.model.index(0, _kol(view, "TELESCOP"))
    delegat = view.table.itemDelegate()
    ed = delegat.createEditor(view.table.viewport(), QStyleOptionViewItem(), idx)
    delegat.setEditorData(ed, idx)
    delegat.setModelData(ed, view.model, idx)                  # bez zmiany
    assert view._pending_count() == 0
    ed.wartosc.setText("EQ6")
    ed.komentarz.setText(" short ")
    delegat.setModelData(ed, view.model, idx)
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["new_value"], w["new_comment"]) == ("EQ6", "short")


def _otworz_edytor(qapp, view, keyword):
    """Edytor otwarty PRZEZ WIDOK (`edit`), w pokazanym i aktywnym oknie - fokus jest prawdziwy."""
    from PySide6.QtWidgets import QLineEdit
    inny = QLineEdit(view)                     # widżet spoza edytora, do którego odejdzie fokus
    inny.show()                                # dziecko dodane do pokazanego rodzica jest ukryte
    view.resize(1200, 600)
    view.show()
    view.activateWindow()
    QApplication.processEvents()
    idx = view.model.index(0, _kol(view, keyword))
    view.table.setCurrentIndex(idx)
    view.table.edit(idx)                       # publiczny slot `edit` (void) - wynik czytamy niżej
    QApplication.processEvents()
    ed = view.table.indexWidget(idx)
    assert ed is not None, "widok nie otworzył edytora"
    assert ed.wartosc.hasFocus()
    return idx, ed, inny


def test_fokus_poza_edytorem_zatwierdza_wpis(qapp, wb_view):
    """Wpis bez Enter, potem klik gdzie indziej (fokus poza edytor) - zmiana jest w szufladzie, więc
    „Zatwierdź" nie zgubi jej. Falsyfikator: zdejmij filtr pól w `_EdycjaKomorki.createEditor`."""
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    inny.setFocus()
    QApplication.processEvents()
    assert view._pending_count() == 1
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")
    assert view.table.indexWidget(idx) is None, "edytor zamknięty"


def test_tab_do_komentarza_nie_konczy_edycji_a_enter_konczy(qapp, wb_view):
    """Przejście wartość → komentarz to dalej ta sama edycja; Enter w komentarzu zatwierdza obie
    wartości naraz."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    ed.komentarz.setFocus()
    QApplication.processEvents()
    assert view._pending_count() == 0 and view.table.indexWidget(idx) is ed
    ed.komentarz.setText("short")
    QApplication.sendEvent(ed.komentarz, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    QApplication.processEvents()
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["new_value"], w["new_comment"]) == ("EQ6", "short")


def test_prawdziwy_klawisz_tab_przechodzi_do_komentarza_i_nie_zamyka_edytora(qapp, wb_view):
    """Firsthand natywny (W1): po F2 i wpisaniu wartości PRAWDZIWY Tab zamykał edytor
    (`QAbstractItemView.focusNextPrevChild` zatwierdzał komórkę), a komentarz wpisany potem przepadał.
    Klawisz, nie `setFocus`: Tab krąży między polami, Backtab wraca, zatwierdza dopiero Enter.
    Falsyfikator: zdejmij obsługę `Key_Tab` z `_EdycjaKomorki.eventFilter`."""
    from PySide6.QtTest import QTest
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.selectAll()
    QTest.keyClicks(ed.wartosc, "EQ6")
    QTest.keyClick(ed.wartosc, Qt.Key_Tab)
    QApplication.processEvents()
    assert view.table.indexWidget(idx) is ed and not ed.zamkniety, "Tab zamknął edytor"
    assert ed.komentarz.hasFocus()
    QTest.keyClick(ed.komentarz, Qt.Key_Backtab, Qt.ShiftModifier)
    QApplication.processEvents()
    assert ed.wartosc.hasFocus() and view.table.indexWidget(idx) is ed
    QTest.keyClick(ed.wartosc, Qt.Key_Tab)
    QTest.keyClicks(ed.komentarz, "short")
    QTest.keyClick(ed.komentarz, Qt.Key_Tab)          # z komentarza cyklicznie do wartości
    QApplication.processEvents()
    assert ed.wartosc.hasFocus() and view._pending_count() == 0
    QTest.keyClick(ed.wartosc, Qt.Key_Return)
    QApplication.processEvents()
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["new_value"], w["new_comment"]) == ("EQ6", "short")


def test_esc_anuluje_edycje(qapp, wb_view):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    QApplication.sendEvent(ed.wartosc, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    QApplication.processEvents()
    assert view._pending_count() == 0 and view.table.indexWidget(idx) is None


def test_podglad_pokazuje_wszystkie_karty_klatki_a_commit_je_zapisuje(wb_view):
    """Dwie edycje różnych keywordów tej samej klatki: podgląd wynika ze stagingu i pokazuje obie,
    commit zapisuje obie. Falsyfikator: wróć do jednego wpisu `dotad[frame_id]` - podgląd zgubi
    pierwszą kartę."""
    from astropy.io import fits
    view, con, p = wb_view
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ6")
    view.model.setData(view.model.index(0, _kol(view, "OBSERVER")), "Zdzich")
    pcol = view.model._preview_col()
    tekst = view.model.data(view.model.index(0, pcol), Qt.DisplayRole)
    assert "TELESCOP: RC8 → EQ6" in tekst and "OBSERVER: Ja → Zdzich" in tekst
    view._on_commit()
    hdr = fits.getheader(str(p))
    assert (hdr["TELESCOP"], hdr["OBSERVER"]) == ("EQ6", "Zdzich")


def test_podglad_mowi_o_zmianie_samego_komentarza(qapp, wb_view):
    """Wartość bez zmian, nowy komentarz: commit zmieni komentarz FITS, więc podgląd mówi to wprost
    („komentarz → …"), nie „RC8 → RC8"; przy zmianie wartości komentarz stoi w podpowiedzi.
    Falsyfikator: zdejmij `comment` z wpisu `_podglad_ze_stagingu`."""
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.komentarz.setText("nowy opis")
    inny.setFocus()
    QApplication.processEvents()
    pcol = view.model._preview_col()
    assert view.model.data(view.model.index(0, pcol), Qt.DisplayRole) == "komentarz → nowy opis"
    view.model.setData(view.model.index(0, _kol(view, "OBSERVER")), "Zdzich")
    idx, ed, inny = _otworz_edytor(qapp, view, "IMAGETYP")
    ed.wartosc.setText("Light Frame")
    ed.komentarz.setText("typ")
    inny.setFocus()
    QApplication.processEvents()
    tip = view.model.data(view.model.index(0, view.model._preview_col()), Qt.ToolTipRole)
    assert "IMAGETYP: 'Light' → 'Light Frame' (set) · komentarz → 'typ'" in tip


def test_podglad_stagingu_jednym_zapytaniem_bez_mapowania_per_wpis(wb_view, monkeypatch):
    """Podgląd po edycji bierze klatkę każdego wpisu z JEDNEGO zapytania
    (`queries.pending_cards_for_run`), nie z `_frame_for_location` na wpis - seria edycji nie
    kosztuje kwadratowo. Falsyfikator: wróć do pętli z `_frame_for_location`."""
    view, con, p = wb_view
    monkeypatch.setattr(view, "_frame_for_location",
                        lambda lid: pytest.fail("mapowanie lokacji per wpis"))
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ6")
    view.model.setData(view.model.index(0, _kol(view, "OBSERVER")), "Zdzich")
    tekst = view.model.data(view.model.index(0, view.model._preview_col()), Qt.DisplayRole)
    assert "TELESCOP: RC8 → EQ6" in tekst and "OBSERVER: Ja → Zdzich" in tekst
    wiersze = queries.pending_cards_for_run(con, view._run_id)
    assert [(w["frame_id"], w["keyword"]) for w in wiersze] == [
        (view.model._rows[0]["frame_id"], "TELESCOP"), (view.model._rows[0]["frame_id"], "OBSERVER")]


def test_reset_modelu_w_trakcie_edycji_nie_gubi_wpisu(qapp, wb_view):
    """Odświeżenie gridu (np. wynik pól z wątku tła) w trakcie pisania: reset niszczy edytor
    i unieważnia indeks - wpis ma trafić do szuflady po stabilnym celu, a podgląd dojść po resecie.
    Falsyfikator: odłącz `modelAboutToBeReset` od `_domknij_edycje`."""
    view, con, p = wb_view
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    view.refresh()
    QApplication.processEvents()
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")
    pcol = view.model._preview_col()
    assert pcol is not None
    assert view.model.data(view.model.index(0, pcol), Qt.DisplayRole) == "RC8 → EQ6"


def test_reset_w_zajetosci_odmawia_z_powodem(qapp, wb_view):
    """Reset modelu w trakcie edycji, gdy zapis plików trwa: staging niemożliwy - odmowa z powodem
    na pasku, nie cisza."""
    view, con, p = wb_view
    msg = _komunikaty(view)
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    view._foreign_wb = True
    view.refresh()
    assert view._pending_count() == 0
    assert any("zapis" in m.lower() or "write" in m.lower() for m in msg), msg


def _baza_z_fitsem(tmp_path, nazwa):
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    p = tmp_path / f"{nazwa}.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(str(p), overwrite=True)
    path = str(tmp_path / f"{nazwa}.db")
    con = db.open_db(path)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    con.close()
    return path


def _oczekujace(path):
    con = db.open_db(path)
    try:
        return [(r[0], r[1]) for r in con.execute(
            "SELECT keyword, new_value FROM pending_changes WHERE status = 'pending'")]
    finally:
        con.close()


def _okno_z_edycja(qapp, path):
    from horreum.gui.app import NAV_ZBIORY
    win = MainWindow(path)
    win.resize(1400, 900)
    win.show()
    win._show_view(NAV_ZBIORY)
    view = win.grid_view
    view._writeback_async = False
    idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
    ed.wartosc.setText("EQ6")
    return win, view


def test_zamkniecie_okna_w_trakcie_edycji_stageuje_przed_zamknieciem_polaczenia(qapp, tmp_path):
    """Zamknięcie okna z otwartym edytorem: wpis trafia do stagingu, ZANIM okno zamknie połączenie
    (tak samo jak niezatwierdzona szuflada - staging zostaje w bazie). Falsyfikator: zdejmij
    `_domknij_edycje("bez")` z `zatrzymaj_pola`."""
    path = _baza_z_fitsem(tmp_path, "zamkniecie")
    win, view = _okno_z_edycja(qapp, path)
    win.close()
    assert win.con is None
    assert _oczekujace(path) == [("TELESCOP", "EQ6")]


def test_przelaczenie_bazy_w_trakcie_edycji_stageuje_w_starej_bazie(qapp, tmp_path):
    path = _baza_z_fitsem(tmp_path, "stara")
    druga = _baza_z_fitsem(tmp_path, "nowa")
    win, view = _okno_z_edycja(qapp, path)
    try:
        win._open_path(druga)
        assert _oczekujace(path) == [("TELESCOP", "EQ6")]
        assert _oczekujace(druga) == []
    finally:
        win.close()


def test_zmiana_miejsca_nawigacji_w_trakcie_edycji_stageuje(qapp, tmp_path):
    path = _baza_z_fitsem(tmp_path, "nawigacja")
    win, view = _okno_z_edycja(qapp, path)
    try:
        win._show_view(NAV_PORZADKI)
        QApplication.processEvents()
        assert view._pending_count() == 1
    finally:
        win.close()


def test_odmowa_mowi_powod_i_nie_zapisuje(wb_view):
    """Wartość łamiąca reguły karty (znak spoza ASCII) - powód na pasku, szuflada pusta."""
    view, con, p = wb_view
    msg = _komunikaty(view)
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "Żuraw")
    assert view._pending_count() == 0
    assert msg[-1].startswith("Komórka TELESCOP - bez zmiany:")


def test_makro_nie_zjada_edycji_komorki(wb_view):
    """Ponowny staging makra czyści cały przebieg - przy edycji komórki w szufladzie odmawia
    z powodem zamiast zjeść ją po cichu. Falsyfikator: zdejmij bramkę z `_on_macro_stage`."""
    view, con, p = wb_view
    msg = _komunikaty(view)
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ6")
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("IMAGETYP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText("Flat")
    bar._emit_stage()
    assert "edycja komórki" in msg[-1]
    (w,) = writeback.pending_for_run(con, view._run_id)
    assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")


def test_commit_edycji_zapisuje_plik_a_cel_cofniecia_lapie_commit(wb_view):
    """Pułapka dwóch mutacji przez jedną szufladę: cel „Cofnij" łapany w chwili COMMITU. Commit
    pierwszej edycji, druga edycja (zdejmuje stare „Cofnij"), commit drugiej - „Cofnij" celuje
    w DRUGI commit i przywraca wartość sprzed niego, nie sprzed pierwszego."""
    from astropy.io import fits
    view, con, p = wb_view
    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ6")
    view._on_commit()
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"
    pierwszy = view._undo_commit_id
    assert pierwszy == view._last_commit_id and view._undo_mode == "macro"

    view.model.setData(view.model.index(0, _kol(view, "TELESCOP")), "EQ8")
    assert view._undo_mode is None                             # stare „Cofnij" unieważnione
    view._on_commit()
    assert fits.getheader(str(p))["TELESCOP"] == "EQ8"
    assert view._undo_commit_id == view._last_commit_id != pierwszy
    view._dispatch_undo()
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"
