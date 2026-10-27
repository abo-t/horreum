"""AR-334: Planer w biegu Dostawy nie liczy nocy na wpół zapisanej bazie - bieg to fakt widoku od konstruktora, każdy
powód rachunku w biegu tylko podbija generację, a koniec przebiegu liczy RAZ (`refresh` gospodarza po przebiegu).

Prawdziwy etap Dostawy w biegu (brama na „Rozwiąż”, wzór `test_gui_grid_recepty`), wejście w Planer klikiem w pasku
nawigacji, planer z prawdziwym wątkiem tła. Podsłuch liczy wywołania `targets.plan` (planer woła rdzeń przez moduł);
liczby to DELTY od chwili przed zdarzeniem, którego test dotyczy. Baza s8 nie zna stanowiska z GPS, więc każdy
rachunek kończy się pustym stanem „bez stanowiska” - licznik zapisuje wywołanie przed wyjątkiem rdzenia.
Czekanie wyłącznie na warunek (pętla zdarzeń + sen), nie na stałą liczbę obrotów. Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import targets
from horreum.gui import i18n
from horreum.gui.app import NAV_DOSTAWA, NAV_PLANER, MainWindow

from test_gui_grid_recepty import _brama_dostawy, _etap_koniec, _etap_start
from test_gui_pasek_szczegol import _czekaj, _czekaj_ms
from test_gui_strony_leniwe import _baza, _klik_nav, _okno


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_watkow_zbiorow(monkeypatch):
    """Bez wątków tła i dobudowy Zbiorów (wzór `test_gui_strony_leniwe._bez_watkow`) - mierzymy wątek planera."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_zbiory_w_bezczynnosci", False)


def _licz_rachunki(monkeypatch, brama=None):
    """Lista wywołań `targets.plan`; z `brama` pierwszy rachunek czeka w wątku na `brama.set()`."""
    rachunki = []
    prawdziwy = targets.plan

    def _plan(con, **kw):
        rachunki.append(threading.current_thread().name)
        if brama is not None and len(rachunki) == 1:
            brama.wait(30)
        return prawdziwy(con, **kw)
    monkeypatch.setattr(targets, "plan", _plan)
    return rachunki


def _bez_watku(planer):
    return planer._worker is None and planer._thread is None


def _po_koncu(planer, rachunki, przed, opis):
    """Czekaj na pierwszy rachunek końca biegu i na ciszę: wątek sprzątnięty, a restart (drugi rachunek) miał czas
    wystartować - potem wątek znów sprzątnięty."""
    _czekaj(lambda: len(rachunki) > przed and _bez_watku(planer), opis)
    _czekaj_ms(200)
    _czekaj(lambda: _bez_watku(planer), f"{opis} - cisza")


def test_planer_zbudowany_w_biegu_liczy_raz_po_koncu(qapp, tmp_path, monkeypatch):
    """Pierwsze wejście w Planer w biegu Dostawy: bez wątku rachunku, zgaszone same gesty zapisu do bazy (AR-366), a w
    miejscu tabeli czynny pusty stan ze zdaniem, że policzy po końcu Dostawy; po końcu przebiegu dokładnie jeden rachunek
    i zdanie znika. Falsyfikatory: konstruktor liczy przed zatrzaskiem (stan sprzed AR-334 - rachunek w biegu i drugi po
    końcu); `_zbuduj_planer` bez `w_biegu=`; `set_busy(False)` liczy obok `refresh` gospodarza (dwa rachunki po końcu);
    bieg gasi cały widok; zdanie biegu nad pustą tabelą."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        przed = len(rachunki)
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        assert _bez_watku(planer), "rachunek nocy ruszył w biegu Dostawy"
        _czekaj_ms(200)
        assert len(rachunki) == przed and _bez_watku(planer)
        assert not planer.park_btn.isEnabled() and planer.order_combo.isEnabled()
        assert planer.table.isHidden() and not planer.empty_note.isHidden() and planer.empty_note.isEnabled()
        assert planer.empty_note.text() == i18n.t("planner.after_intake")
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, przed, "rachunek po końcu biegu")
        assert len(rachunki) - przed == 1, rachunki
        assert planer.park_btn.isEnabled() and planer.empty_note.text() != i18n.t("planner.after_intake")
    finally:
        puszczona.set()
        win.close()


def test_planer_bez_stanowiska_wejscie_w_biegu_nie_liczy(qapp, tmp_path, monkeypatch):
    """Planer zbudowany przed biegiem na bazie bez stanowiska: wejście w niego w biegu (gospodarz woła `refresh`, dopóki
    trwa pusty stan „bez stanowiska”) nie liczy; koniec biegu liczy raz. Falsyfikator: `replan` bez bramki biegu."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: planer.bez_stanowiska and _bez_watku(planer), "planer bez stanowiska przed biegiem")
        po_budowie = len(rachunki)
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        _klik_nav(win, NAV_PLANER)
        assert _bez_watku(planer), "wejście w biegu uruchomiło rachunek"
        _czekaj_ms(200)
        assert len(rachunki) == po_budowie and _bez_watku(planer)
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, po_budowie, "rachunek po końcu biegu")
        assert len(rachunki) - po_budowie == 1, rachunki
    finally:
        puszczona.set()
        win.close()


def test_planer_restart_watku_w_biegu_czeka_na_koniec(qapp, tmp_path, monkeypatch):
    """Rachunek sprzed biegu w wątku, za nim generacja w kolejce (`refresh`), potem start biegu: koniec starego wątku
    w biegu NIE startuje drugiego rachunku (`_cleanup_thread`), koniec biegu liczy raz. Falsyfikator: restart
    w `_cleanup_thread` bez warunku biegu."""
    brama = threading.Event()
    rachunki = _licz_rachunki(monkeypatch, brama=brama)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: len(rachunki) == 1, "pierwszy rachunek w wątku")
        planer.refresh()
        assert planer._worker is not None and planer._pending_gen()
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        brama.set()
        _czekaj(lambda: _bez_watku(planer), "wątek sprzed biegu sprzątnięty")
        _czekaj_ms(200)
        assert len(rachunki) == 1 and _bez_watku(planer), rachunki
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, 1, "rachunek po końcu biegu")
        assert len(rachunki) == 2, rachunki
    finally:
        brama.set()
        puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-350: jeden właściciel końca biegu

@pytest.mark.parametrize("zbudowany", ["w_biegu", "przed_biegiem"])
def test_koniec_biegu_liczy_raz_takze_z_zegarem_w_pompie_fazy(qapp, tmp_path, monkeypatch, zbudowany):
    """AR-350: zegar (debounce, ponowienie `no_site`) albo koniec wątku sprzed biegu doręczony w pompie fazy odświeżenia
    trafia na zamkniętą bramę - po końcu biegu jest DOKŁADNIE jeden rachunek. Atrapa czasu: zegar 0 ms uzbrojony raz,
    tuż po otwarciu bramy (`set_busy(False)`); bez czekania na wątek w opakowaniu (`worker.finished -> thread.quit`
    idzie kolejką - zakleszczenie). Żniwa ze stosami (drugie odświeżenie po zapisie rodowodu) są poza tym kontraktem.
    Falsyfikator: `_on_pipeline_running` otwiera bramę przed fazą (`planner.set_busy(running)` także dla `False`)."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    try:
        if zbudowany == "przed_biegiem":
            _klik_nav(win, NAV_PLANER)
            _czekaj(lambda: win._strony["planner_view"].bez_stanowiska
                    and _bez_watku(win._strony["planner_view"]), "planer przed biegiem")
        win._show_view(NAV_DOSTAWA)
        _etap_start(win)
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        przed = len(rachunki)
        prawdziwe = planer.set_busy
        uzbrojony = []

        def _set_busy(running):
            prawdziwe(running)
            if not running and not uzbrojony:
                uzbrojony.append(1)
                planer._debounce.setInterval(0)
                planer._queue_replan()
        monkeypatch.setattr(planer, "set_busy", _set_busy)
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, przed, "rachunek po końcu biegu")
        assert uzbrojony and len(rachunki) - przed == 1, rachunki
    finally:
        puszczona.set()
        win.close()


def _etap_rodowodu(monkeypatch, koniec):
    """Etap „rodowód stosów” PRAWDZIWY, wstrzymany bramą, z wybranym końcem: sukces, błąd etapu albo wynik przerwany."""
    import dataclasses

    from horreum import derive
    puszczona = threading.Event()
    prawdziwy = derive.DERIVED["stack_lineage"]

    def _etap(con, now, cancel):
        puszczona.wait(30)
        if koniec == "blad":
            raise RuntimeError("etap padł")
        wynik = prawdziwy(con, now, cancel)
        return dataclasses.replace(wynik, cancelled=True) if koniec == "przerwany" else wynik
    monkeypatch.setitem(derive.DERIVED, "stack_lineage", _etap)
    return puszczona


@pytest.mark.parametrize("koniec", ["sukces", "blad", "przerwany", "odmowa"])
def test_kazdy_koniec_biegu_liczy_planer_raz_i_go_zwalnia(qapp, tmp_path, monkeypatch, koniec):
    """AR-350: każdy rodzaj końca przebiegu, który gospodarz kieruje do odświeżenia widoków (`running_changed(False)`
    z `_cleanup_thread` Dostawy) - sukces, błąd etapu, etap przerwany, odmowa startu (źródło nieosiągalne) - daje
    DOKŁADNIE jeden rachunek planera i zwolnione gesty zapisu. Rodzaj końca potwierdza zapis przebiegu Dostawy.
    Falsyfikator: rachunek albo zwolnienie bramy tylko po udanym przebiegu."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _etap_rodowodu(monkeypatch, koniec)
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: planer.bez_stanowiska and _bez_watku(planer), "planer przed biegiem")
        przed = len(rachunki)
        pv = win.pipeline_view
        if koniec == "odmowa":
            pv._root = str(tmp_path / "nie_ma")
            pv._on_scan()
        else:
            assert pv.run_stage("stack_lineage") is None
            _czekaj(lambda: not planer.park_btn.isEnabled(), "planer w biegu")
            puszczona.set()
        _czekaj(lambda: pv._thread is None and not win.object_view._busy, "koniec przebiegu")
        _po_koncu(planer, rachunki, przed, "rachunek po końcu biegu")
        assert len(rachunki) - przed == 1, rachunki
        assert planer.park_btn.isEnabled() and not planer._w_biegu
        zapis = pv.last_run
        assert {"sukces": not (zapis["failed"] or zapis["cancelled"] or zapis["refused"]),
                "blad": bool(zapis["failed"]), "przerwany": zapis["cancelled"] == "stack_lineage",
                "odmowa": bool(zapis["refused"])}[koniec], zapis
    finally:
        puszczona.set()
        win.close()


def test_wyjatek_odswiezenia_po_biegu_nie_zostawia_planera_w_biegu(qapp, tmp_path, monkeypatch):
    """AR-350: para `set_busy` + `refresh` Planera stoi PIERWSZA w fazie odświeżenia - wyjątek odświeżenia dalszego
    widoku (tu oś teleskopu) nie zostawia Planera z zamkniętą bramą do następnego przebiegu (wzór
    `test_gui_mainwindow.py::test_wyjatek_w_odswiezeniu_po_przebiegu_zwalnia_os_obiektu`). Falsyfikator: para na końcu
    fazy."""
    win = _okno(_baza(tmp_path))
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: planer.bez_stanowiska and _bez_watku(planer), "planer przed biegiem")
        win._on_pipeline_running(True)
        assert not planer.park_btn.isEnabled()

        def _pada():
            raise RuntimeError("odświeżenie padło")
        monkeypatch.setattr(win.axis_view, "refresh", _pada)
        with pytest.raises(RuntimeError, match="odświeżenie padło"):
            win._on_pipeline_running(False)
        assert planer.park_btn.isEnabled() and not planer._w_biegu
        _czekaj(lambda: _bez_watku(planer), "rachunek po końcu biegu")
    finally:
        win.close()


# ---------------------------------------------------------------- AR-366: w biegu gasną wyłącznie gesty zapisu do bazy

def _baza_planera(tmp_path, sieroty=()):
    """Baza planera ze stanowiskiem i zestawami (`test_gui_planner._seed`), opcjonalnie z osieroconą kuratelą."""
    from test_gui_planner import NOW, _seed
    sciezka = str(tmp_path / "planer.db")
    con = _seed(sciezka)
    for canon in sieroty:
        con.execute("INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
                    "VALUES (?, 'planned', NULL, NULL, ?, ?)", (canon, NOW, NOW))
    con.commit()
    con.close()
    return sciezka


def _planer_z_wynikiem(win):
    _klik_nav(win, NAV_PLANER)
    planer = win._strony["planner_view"]
    _czekaj(lambda: planer._result is not None and _bez_watku(planer) and not planer._pending_gen(),
            "plan nocy policzony")
    return planer


def _po_rachunku(planer, opis):
    _czekaj(lambda: _bez_watku(planer) and not planer._pending_gen(), opis)


def _stan_bazy(con):
    """Wszystko, co gest zapisu Planera rusza w bazie: dziennik, kuratela, park."""
    return (con.execute("SELECT count(*) FROM event").fetchone()[0],
            [tuple(r) for r in con.execute("SELECT canon, status, priority, note FROM target_plan ORDER BY canon")],
            [tuple(r) for r in con.execute("SELECT id, in_park FROM telescope ORDER BY id")])


def _klik(widget):
    QTest.mouseClick(widget, Qt.LeftButton)
    QApplication.processEvents()


def test_w_biegu_gasna_tylko_gesty_zapisu_do_bazy(qapp, tmp_path, monkeypatch):
    """AR-366: w biegu Dostawy Planer zostaje czytelny i sterowalny - lista, „Porządek” i chipy działają, a gasną
    wyłącznie gesty zapisu do bazy: Zapisz/Zdejmij oznaczenie, „Park…”, trzy przyciski sierot. Prawdziwe kliknięcia,
    Enter w polu notatki i dwuklik w wierszu w biegu nie zmieniają bazy (dziennik, kuratela, park); wpisana notatka
    i wybrany status przeżywają bieg. Po końcu gesty wracają. Falsyfikatory: bieg gasi cały widok (`setEnabled`);
    `set_busy` przez `_sync_panel` (notatka znika); któryś gest zapisu czynny w biegu (zapis w bazie)."""
    from horreum.gui.planner import ParkDialog
    okna_parku = []
    monkeypatch.setattr(ParkDialog, "exec", lambda dlg: okna_parku.append(dlg) or 0)   # bez modalu w teście
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza_planera(tmp_path, sieroty=("LBN529", "NGC0000_NIEISTNIEJE")))
    try:
        planer = _planer_z_wynikiem(win)
        # Przed biegiem: zdjęcie sieroty (pamięć „Cofnij zdjęcie”), zapis oznaczenia celu - gesty czynne.
        planer.orphan_list.setCurrentRow(1)                      # NGC0000_NIEISTNIEJE (lista po kanonie)
        _klik(planer.orphan_clear_btn)
        _po_rachunku(planer, "rachunek po zdjęciu sieroty")
        rect = planer.table.visualRect(planer.model.index(0, 0))
        QTest.mouseClick(planer.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        cel = planer.selected_row().canon
        planer.panel_status.setCurrentIndex(planer.panel_status.findData("planned"))
        _klik(planer.save_btn)
        _po_rachunku(planer, "rachunek po zapisie oznaczenia")
        assert planer.selected_row().canon == cel and planer.clear_btn.isEnabled()
        planer.panel_status.setCurrentIndex(planer.panel_status.findData("active"))
        _klik(planer.panel_note)
        QTest.keyClicks(planer.panel_note, "w biegu")
        notatka = planer.panel_note.text()
        # Sierota zaznaczona PO ostatnim rachunku (zaznaczenie sekcji nie przeżywa przeliczenia): trzy gesty czynne.
        planer.orphan_list.setCurrentRow(0)                      # LBN529 - alias katalogowy C9: „Przenieś” czynne
        assert all(b.isEnabled() for b in (planer.orphan_clear_btn, planer.orphan_move_btn, planer.orphan_undo_btn))

        _etap_start(win)
        stan = _stan_bazy(win.con)
        gesty = (planer.save_btn, planer.clear_btn, planer.park_btn, planer.orphan_clear_btn,
                 planer.orphan_move_btn, planer.orphan_undo_btn)
        assert not any(b.isEnabled() for b in gesty)
        assert planer.table.isEnabled() and planer.order_combo.isEnabled() and planer.min_size.isEnabled()
        assert planer.panel_note.text() == notatka and planer.panel_status.currentData() == "active"
        assert planer.selected_row().canon == cel and planer._selected_orphan() is not None
        for b in gesty:
            _klik(b)
        QTest.keyClick(planer.panel_note, Qt.Key_Enter)
        QTest.keyClick(planer.panel_note, Qt.Key_Return)
        rect = planer.table.visualRect(planer.model.index(0, 0))
        QTest.mouseDClick(planer.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        QApplication.processEvents()
        chip = planer._chip_group.buttons()[1]
        _klik(chip)                                             # soczewka - przerysowanie bez rachunku i zapisu
        assert chip.isChecked() and planer._rig_chip == chip.text()
        assert _stan_bazy(win.con) == stan and okna_parku == []
        assert planer.panel_note.text() == notatka
        # AR-376: przerysowanie chipem zostawia cel i niezapisany status w CZYNNYM panelu - nie w wygaszonym bez celu.
        assert planer.selected_row().canon == cel and planer.panel.isEnabled()
        assert planer.panel_status.currentData() == "active"

        _etap_koniec(win, puszczona)
        _po_rachunku(planer, "rachunek po końcu biegu")
        assert planer.park_btn.isEnabled() and planer.orphan_undo_btn.isEnabled()
        assert planer.panel_note.text() == notatka
        assert planer.selected_row().canon == cel and planer.panel.isEnabled()
        assert planer.panel_status.currentData() == "active" and planer.save_btn.isEnabled()
    finally:
        puszczona.set()
        win.close()


def test_zmiana_progu_w_biegu_czeka_i_mowi_to_nad_lista(qapp, tmp_path, monkeypatch):
    """AR-366: próg zmieniony w biegu (prawdziwy klawisz w polu) tylko podbija generację - zero rachunków
    w biegu, lista sprzed zmiany zostaje, a pierwsza nota nad nią mówi, że plan policzy się po końcu Dostawy; koniec
    biegu liczy raz i nota znika. Falsyfikator: bez noty (lista przeczy tytułowi progów do końca biegu)."""
    rachunki = _licz_rachunki(monkeypatch)
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza_planera(tmp_path))
    zdanie = i18n.t("planner.after_intake")
    try:
        planer = _planer_z_wynikiem(win)
        wiersze = planer.model.rowCount()
        assert zdanie not in planer.notes_label.text()
        _etap_start(win)
        przed = len(rachunki)
        _klik(planer.min_size.lineEdit())
        QTest.keyClick(planer.min_size, Qt.Key_Up)
        _czekaj(lambda: planer.notes_label.text().splitlines()[:1] == [zdanie], "nota biegu nad listą")
        assert not planer.notes_label.isHidden() and planer.model.rowCount() == wiersze
        _czekaj_ms(200)
        assert len(rachunki) == przed, rachunki
        _etap_koniec(win, puszczona)
        _po_koncu(planer, rachunki, przed, "rachunek po końcu biegu")
        assert len(rachunki) - przed == 1, rachunki
        assert zdanie not in planer.notes_label.text()
    finally:
        puszczona.set()
        win.close()


def test_okno_parku_gasnie_gdy_bieg_rusza_przy_otwartym(qapp, tmp_path, monkeypatch):
    """AR-366: bieg Dostawy ruszający przy otwartym oknie „Park…” gasi okno (zapis `telescope.parked`), a koniec biegu
    je zwalnia - dawniej robił to wygaszony rodzic, dziś planer w biegu jest czynny. Prawdziwy klik „Park…”, prawdziwy
    etap; modal zastąpiony funkcją, która w nim startuje i kończy etap. Falsyfikator: okno parku bez gaszenia w biegu."""
    from horreum.gui.planner import ParkDialog
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza(tmp_path))
    stany = []

    def _exec(dlg):
        stany.append(dlg.isEnabled())
        _etap_start(win)
        stany.append(dlg.isEnabled())
        _etap_koniec(win, puszczona)
        stany.append(dlg.isEnabled())
        return 0
    monkeypatch.setattr(ParkDialog, "exec", _exec)
    try:
        _klik_nav(win, NAV_PLANER)
        planer = win._strony["planner_view"]
        _czekaj(lambda: _bez_watku(planer), "planer przed biegiem")
        _klik(planer.park_btn)
        assert stany == [True, False, True], stany
        assert planer._park_dlg is None
        _czekaj(lambda: _bez_watku(planer), "rachunek po końcu biegu")
    finally:
        puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-386: zgaszony gest zapisu mówi dlaczego

_WARTOWNIK = "podpowiedź sprzed zdarzenia"


def _podpowiedz(przycisk):
    """Podpowiedź drogą zdarzenia, jak pod kursorem: wartownik w etykiecie podpowiedzi, potem `QHelpEvent(ToolTip)`
    na przycisku. Przycisk bez podpowiedzi ignoruje zdarzenie i etykieta zostaje przy wartowniku - nie przy podpowiedzi
    poprzednio sprawdzanego przycisku."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip
    p = QPoint(przycisk.width() // 2, przycisk.height() // 2)
    QToolTip.showText(przycisk.mapToGlobal(p), _WARTOWNIK, None)
    QApplication.sendEvent(przycisk, QHelpEvent(QEvent.ToolTip, p, przycisk.mapToGlobal(p)))
    return QToolTip.text()


def test_w_biegu_zgaszone_gesty_zapisu_mowia_dlaczego(qapp, tmp_path, monkeypatch):
    """AR-386: w biegu Dostawy każdy z sześciu zgaszonych gestów zapisu (Zapisz/Zdejmij oznaczenie, „Park…”, trzy
    gesty sierot) mówi pod kursorem JEDEN powód - zapiszesz po końcu Dostawy; „Przenieś” nie obiecuje wtedy gestu,
    a „Cofnij zdjęcie” nie opisuje funkcji. Po końcu biegu wracają własne podpowiedzi. Prawdziwy etap, podpowiedź drogą
    zdarzenia. Falsyfikatory: gest bez powodu w biegu; powód zostaje po biegu; podpowiedź cofnięcia nie wraca."""
    from PySide6.QtWidgets import QToolTip
    puszczona = _brama_dostawy(monkeypatch)
    win = _okno(_baza_planera(tmp_path, sieroty=("LBN529", "NGC0000_NIEISTNIEJE")))
    try:
        planer = _planer_z_wynikiem(win)
        planer.orphan_list.setCurrentRow(1)                      # NGC0000_NIEISTNIEJE - pamięć „Cofnij zdjęcie”
        _klik(planer.orphan_clear_btn)
        _po_rachunku(planer, "rachunek po zdjęciu sieroty")
        rect = planer.table.visualRect(planer.model.index(0, 0))
        QTest.mouseClick(planer.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        planer.panel_status.setCurrentIndex(planer.panel_status.findData("planned"))
        _klik(planer.save_btn)
        _po_rachunku(planer, "rachunek po zapisie oznaczenia")
        planer.orphan_list.setCurrentRow(0)                      # LBN529 - alias katalogowy C9: „Przenieś” czynne
        gesty = {"zapisz": planer.save_btn, "zdejmij": planer.clear_btn, "park": planer.park_btn,
                 "sierota_zdejmij": planer.orphan_clear_btn, "sierota_przenies": planer.orphan_move_btn,
                 "sierota_cofnij": planer.orphan_undo_btn}
        wlasne = {**dict.fromkeys(("zapisz", "zdejmij", "park", "sierota_zdejmij"), _WARTOWNIK),
                  "sierota_przenies": i18n.t("planner.orphan_move_tip", where="C9"),
                  "sierota_cofnij": i18n.t("planner.orphan_undo_tip")}
        assert all(b.isEnabled() for b in gesty.values())
        assert {n: _podpowiedz(b) for n, b in gesty.items()} == wlasne

        _etap_start(win)
        assert not any(b.isEnabled() for b in gesty.values())
        assert {n: _podpowiedz(b) for n, b in gesty.items()} == \
            dict.fromkeys(gesty, i18n.t("planner.busy_write_tip"))

        _etap_koniec(win, puszczona)
        _po_rachunku(planer, "rachunek po końcu biegu")
        planer.orphan_list.setCurrentRow(0)                      # zaznaczenie sekcji nie przeżywa przeliczenia
        assert all(b.isEnabled() for b in gesty.values())
        assert {n: _podpowiedz(b) for n, b in gesty.items()} == wlasne
    finally:
        QToolTip.hideText()
        puszczona.set()
        win.close()


# ---------------------------------------------------------------- AR-373: po żniwach ze stosami jedno odświeżenie

def _zniwa_bez_okna(monkeypatch, korzen):
    """Okno żniw podstawione w `sys.modules` (wzór `test_gui_przyjmij._zniwa_ze_stosami`): wciągnęło jeden stos bez
    wydania i oddaje `korzen` do przyjęcia - łańcuch Dostawy biegnie PRAWDZIWYM `run_all_on`. Zapis rodowodu
    (`stacks.record_harvest_inputs`) atrapą; zwraca rejestr zapisanych stosów."""
    import sys
    import types

    from PySide6.QtWidgets import QDialog

    from horreum import stacks

    class _OknoZniw:
        def __init__(self, *_a, **_k):
            self.summary = "Wciągnięto stosy"
            self.harvested_root = str(korzen)
            self.harvested_stacks = [("sha-stosu", (1,), None)]

        def exec(self):
            return QDialog.Accepted
    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    zapisy = []

    def _zapis(con, *, master_sha1_data, input_frame_ids, now, actor="harvest"):
        zapisy.append(master_sha1_data)
        return {"reason": None, "linked": 1, "upgraded": 0, "dropped": 0, "kept_user": 0}
    monkeypatch.setattr(stacks, "record_harvest_inputs", _zapis)
    return zapisy


def _zniwa_w_oknie(tmp_path, monkeypatch, koniec):
    """Okno z Planerem zbudowanym przed biegiem, podsłuch `set_busy` Planera i osi obiektu oraz odświeżeń końca
    przebiegu. Podsłuch odświeżenia FLASHUJE raport przed prawdziwym odświeżeniem - zdanie, które ma stać na pasku po
    końcu żniw, musi paść PO odświeżeniu. Zwraca `(okno, planer, zajętość, odświeżenia, zapisy rodowodu)`."""
    korzen = tmp_path / "zniwa"
    if koniec != "odmowa":                        # odmowa = źródło nieosiągalne (sonda źródła w wątku tła)
        korzen.mkdir()
    if koniec == "blad":
        from test_gui_pasek_szczegol import _awaria_skanu
        _awaria_skanu(monkeypatch)
    zapisy = _zniwa_bez_okna(monkeypatch, korzen)
    win = _okno(_baza(tmp_path))
    _klik_nav(win, NAV_PLANER)
    planer = win._strony["planner_view"]
    _czekaj(lambda: planer.bez_stanowiska and _bez_watku(planer), "planer przed biegiem")
    zajetosc, odswiezenia = [], []
    for nazwa, widok in (("planer", planer), ("obiekt", win.object_view)):
        prawdziwe = widok.set_busy
        monkeypatch.setattr(widok, "set_busy",
                            lambda b, _n=nazwa, _p=prawdziwe: (zajetosc.append((_n, b)), _p(b)))
    prawdziwe_odswiezenie = win._odswiez_widoki_po_przebiegu

    def _odswiez():
        odswiezenia.append(1)
        win._flash("raport odświeżenia")
        prawdziwe_odswiezenie()
    monkeypatch.setattr(win, "_odswiez_widoki_po_przebiegu", _odswiez)
    win._show_view(NAV_DOSTAWA)
    return win, planer, zajetosc, odswiezenia, zapisy


def _ostatni(zajetosc, wpis):
    return max(i for i, w in enumerate(zajetosc) if w == wpis)


@pytest.mark.parametrize("koniec", ["sukces", "odmowa", "blad"])
def test_zniwa_ze_stosami_odswiezaja_widoki_raz(qapp, tmp_path, monkeypatch, koniec):
    """AR-373: „Wciągnij z WBPP…” ze stosami - koniec łańcucha Dostawy odświeża widoki RAZ, po zapisie rodowodu:
    jeden rachunek Planera (dawniej dwa, pierwszy czytał bazę sprzed zapisu), oś obiektu zwolniona po odświeżeniu
    (AR-296 - dawniej przed drugim). Przebieg odmówiony albo z błędem odświeża też raz, a zdanie utraty rodowodu stoi
    po raportach odświeżenia. Prawdziwy klik, prawdziwe `run_all_on`. Falsyfikatory: odświeżenie także przy
    `running_changed(False)`; gałąź porażki bez odświeżenia (Planer z zamkniętą bramą); zwolnienie osi przed
    odświeżeniem; zdanie utraty przed odświeżeniem."""
    rachunki = _licz_rachunki(monkeypatch)
    win, planer, zajetosc, odswiezenia, zapisy = _zniwa_w_oknie(tmp_path, monkeypatch, koniec)
    try:
        pv = win.pipeline_view
        przed = len(rachunki)
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        _czekaj(lambda: pv._thread is None and not win.object_view._busy, "koniec przebiegu")
        _po_koncu(planer, rachunki, przed, "rachunek po końcu żniw")
        assert len(rachunki) - przed == 1, rachunki
        assert odswiezenia == [1]
        assert _ostatni(zajetosc, ("obiekt", False)) > _ostatni(zajetosc, ("planer", False)), zajetosc
        assert not planer._w_biegu and not win.object_view._busy and win._ogon_biegu is None
        zapis = pv.last_run
        if koniec == "sukces":
            assert zapisy == ["sha-stosu"] and not (zapis["failed"] or zapis["refused"])
            assert str(win._pelny_komunikat).startswith("Wciągnięto stosy - ")
        else:
            assert zapisy == [] and bool(zapis["refused" if koniec == "odmowa" else "failed"])
            assert str(win._pelny_komunikat).startswith(i18n.t("status.harvest_lineage_lost", n=1))
    finally:
        win.close()


def test_zniwa_na_innej_bazie_zdejmuja_ogon_bez_odswiezenia(qapp, tmp_path, monkeypatch):
    """AR-373: koniec przebiegu żniw, gdy okno ma już inne połączenie - widoki nowej bazy zmontował od nowa
    `_open_path` (`_mount_views` → `_clear_views`), więc nasłuch rodowodu zdejmuje tylko swój ogon: zero odświeżeń,
    zero zapisu. Przebieg bez wątku (`run_all_on` stawia znacznik startu, jak `_start_stage`), koniec - `run_finished`
    z tym znacznikiem. Falsyfikator: gałąź innej bazy domyka ogon z odświeżeniem."""
    from horreum.gui.pipeline import PipelineView
    zapisy = _zniwa_bez_okna(monkeypatch, tmp_path)
    monkeypatch.setattr(PipelineView, "run_all_on",
                        lambda self, root: self.last_run.update(stage="all", since="2026-10-27T12:00:00+00:00"))
    win = _okno(_baza(tmp_path))
    prawdziwe = win.con
    try:
        odswiezenia = []
        monkeypatch.setattr(win, "_odswiez_widoki_po_przebiegu", lambda: odswiezenia.append(1))
        win._show_view(NAV_DOSTAWA)
        pv = win.pipeline_view
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        assert win._ogon_trwa("2026-10-27T12:00:00+00:00")
        win.con = object()                                       # inna baza otwarta w trakcie biegu
        pv.run_finished.emit({**pv._pusty_zapis_przebiegu(), "stage": "all", "since": "2026-10-27T12:00:00+00:00"})
        assert odswiezenia == [] and zapisy == [] and win._ogon_biegu is None
    finally:
        win.con = prawdziwe
        win.close()


def test_bieg_ruszajacy_w_pompie_odswiezenia_trzyma_os_obiektu(qapp, tmp_path, monkeypatch):
    """AR-296 na końcu biegu: bieg, który RUSZYŁ w pompie fazy odświeżenia po poprzednim i jeszcze trwa, trzyma oś
    obiektu zajętą - gesty zapisu osi nie wracają czynne przy pracującym pisarzu Dostawy; zwalnia ją koniec TEGO biegu.
    Start drugiego biegu doręczony w środku odświeżenia (jak przez `processEvents` fazy), bez jego końca w tej samej
    pompie. Falsyfikator: zwolnienie osi po odświeżeniu bez warunku biegu."""
    win = _okno(_baza(tmp_path))
    try:
        prawdziwe = win.axis_view.refresh
        obroty = []

        def _refresh(*a, **k):
            obroty.append(1)
            if len(obroty) == 1:
                win._on_pipeline_running(True)          # drugi bieg rusza w pompie fazy i trwa
            prawdziwe(*a, **k)
        monkeypatch.setattr(win.axis_view, "refresh", _refresh)
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)                 # koniec pierwszego biegu
        assert win._dostawa_w_biegu and win.object_view._busy
        win._on_pipeline_running(False)                 # koniec drugiego
        assert not win.object_view._busy and len(obroty) == 2
    finally:
        win.close()


def test_ogon_biegu_odswieza_po_ostatnim_pisarzu(qapp, tmp_path, monkeypatch):
    """AR-373 (rozwojowo): ogon biegu to ZBIÓR pisarzy po `since` - przy drugim pisarzu koniec zapisu rodowodu nie
    odświeża jeszcze widoków i nie zwalnia osi; robi to raz ostatni pisarz. Falsyfikator: domknięcie odświeża bez
    sprawdzenia, czy ogon jest pusty."""
    rachunki = _licz_rachunki(monkeypatch)
    win, planer, zajetosc, odswiezenia, zapisy = _zniwa_w_oknie(tmp_path, monkeypatch, "sukces")
    try:
        pv = win.pipeline_view
        przed = len(rachunki)
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        since = pv.last_run["since"]
        win._dopisz_do_ogona(since, "inny pisarz")
        _czekaj(lambda: pv._thread is None and zapisy == ["sha-stosu"], "zapis rodowodu po przebiegu")
        _czekaj_ms(200)
        assert odswiezenia == [] and len(rachunki) == przed
        assert planer._w_biegu and win.object_view._busy and win._ogon_trwa(since)
        win._domknij_ogon(since, "inny pisarz")
        _po_koncu(planer, rachunki, przed, "rachunek po ostatnim pisarzu")
        assert odswiezenia == [1] and len(rachunki) - przed == 1
        assert not planer._w_biegu and not win.object_view._busy and win._ogon_biegu is None
    finally:
        win.close()
