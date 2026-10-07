"""Gest „Ta kopia prowadzi" w Zbiorach (AR-4, AR-23): podmenu kopii w menu prawego kliku tabeli,
wątek tła gestu (uchwyt zapisu `_wb`, prawdziwy `QThread`) i ogon - odświeżony zbiór, zdanie
z drogą powrotu, plakietka Porządków i wiersz „Kopie niezgodne", którego robota gaśnie.

Przebieg prawdziwy: klik myszą w wiersz, zdarzenie menu kontekstowego na viewporcie tabeli,
wyzwolenie pozycji kopii w podmenu, wątek tła czyta nagłówek pliku. Pliki syntetyczne XISF
w `tmp_path` (scenariusz `test_orphan_testimony`), zero archiwum, zero żywej bazy."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, scan
from horreum.gui import grid as grid_mod, i18n, rows, tasks as tasks_mod

from test_copy_facts import NOW
from test_orphan_testimony import _cls, _header, _loc, _lpro

LATER = "2026-10-07T09:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def widok(qapp, tmp_path):
    """Zbiory nad bazą z klatką o dwóch niezgodnych kopiach (header z L-Pro) i jedną zwykłą klatką;
    wykonawca gestu w PRAWDZIWYM wątku tła (plik bazy na dysku)."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    _cls(root, payload=b"\x09" * 32, sub="SOLO")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    v = grid_mod.FramesView(con, now_fn=lambda: LATER)
    v.resize(1400, 800)
    v.show()
    assert v._writeback_async and v._db_path
    yield con, v, fid, a, b
    _po_gescie(v)
    v.close()
    con.close()


def _po_gescie(v, ms=10000):
    """Pętla zdarzeń kręci się, aż uchwyt zapisu zbierze wątek gestu (`busy_changed(False)` po
    `_cleanup`) - PySide6 nie ma `QTest.qWaitFor`. Czekanie `time.sleep`, nie `QTest.qWait`:
    `qWait` trzyma GIL przez cały swój interwał, więc wątek gestu dostawał okruchy czasu
    (zmierzone: 7,2 s zamiast 0,05 s inline). `True` = wątek zebrany w czasie."""
    for _ in range(ms // 10):
        QApplication.processEvents()
        if not v._wb.is_busy:
            return True
        time.sleep(0.01)
    return not v._wb.is_busy


def _wiersz(v, fid):
    return next(i for i, r in enumerate(v.model._rows)
                if isinstance(r, dict) and r.get("frame_id") == fid)


def _prawy_klik(v, row):
    """Klik lewym w wiersz (zaznaczenie), potem zdarzenie menu kontekstowego na viewporcie - ta
    sama droga, którą Qt idzie przy prawym kliku (`customContextMenuRequested`)."""
    rect = v.table.visualRect(v.model.index(row, 0))
    QTest.mouseClick(v.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    vp = v.table.viewport()
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, rect.center(),
                                                 vp.mapToGlobal(rect.center())))


def _pozycje_kopii(v):
    return [a for a in v._menu_kopii.actions() if not a.isSeparator()]


def test_gest_w_perspektywie_kopii_niezgodnych_przejmuje_i_mowi_droge_powrotu(widok):
    """Perspektywa „Kopie niezgodne": prawy klik na klatce → podmenu „Ta kopia prowadzi" z dwiema
    kopiami (L-Pro „mówi teraz"). Wybór CLS idzie wątkiem tła; po nim zbiór jest odświeżony
    (klatka dalej w perspektywie i w zaznaczeniu), `header` mówi CLS, pasek mówi drogę powrotu
    (kopia L-Pro), plakietka Porządków dostaje sygnał, a wiersz „Kopie niezgodne" liczy klatkę,
    ale jej nie pogrubia - decyzja ręki nie jest robotą."""
    con, v, fid, a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    assert v._frame_ids == [fid]
    msg, plakietka = [], []
    v.status_message.connect(msg.append)
    v.stan_porzadkow_changed.connect(lambda: plakietka.append(1))
    _prawy_klik(v, _wiersz(v, fid))
    assert v._menu_tabeli.isVisible()
    akcja = v._menu_kopii.menuAction()
    assert akcja.isVisible() and akcja.isEnabled()
    pozycje = _pozycje_kopii(v)
    assert [p.text() for p in pozycje] == [str(a) + i18n.t("grid.lead.speaks"), str(b)]
    assert "FILTER=CLS" in pozycje[1].toolTip()
    pozycje[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    assert _header(con, fid)["filter_raw"] == "CLS"
    assert v._frame_ids == [fid]
    assert [r["frame_id"] for r in v._selected_data_rows()] == [fid]
    zdanie = msg[-1]
    assert zdanie.startswith("Klatka mówi teraz głosem kopii B_CLS")
    assert "Powrót: „Ta kopia prowadzi” na kopii A_LPRO" in zdanie
    assert plakietka == [1]
    tv = tasks_mod.TasksView(con, now_fn=lambda: LATER)
    try:
        tv.refresh_counts()
        it = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                  if tv.tasks.item(i).data(Qt.UserRole) == "copy_conflict_frames")
        assert it.data(rows.SECONDARY).startswith(i18n.t("tasks.of_total", open=0, total=1))
        assert it.data(rows.STRONG) is False
        assert "kopię wiodącą wskazaną ręką" in it.toolTip()
    finally:
        tv.close()


def test_droga_powrotu_tym_samym_gestem(widok):
    """Ta sama ścieżka drugi raz, na kopii L-Pro - zeznanie wraca, a droga powrotu wskazuje CLS."""
    con, v, fid, a, _b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    msg = []
    v.status_message.connect(msg.append)
    for indeks in (1, 0):
        _prawy_klik(v, _wiersz(v, fid))
        _pozycje_kopii(v)[indeks].trigger()
        v._menu_tabeli.hide()
        assert _po_gescie(v)
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    assert "Powrót: „Ta kopia prowadzi” na kopii B_CLS" in msg[-1]


def test_poza_perspektywa_gest_tylko_nad_klatka_ktora_czeka(widok):
    """„Przegląd": prawy klik na klatce z niezgodnymi kopiami otwiera menu z podmenu kopii; prawy
    klik na zwykłej klatce zostaje niczym (menu się nie pokazuje)."""
    con, v, fid, _a, _b = widok
    solo = next(f for f in v._frame_ids if f != fid)
    _prawy_klik(v, _wiersz(v, solo))
    assert not v._menu_tabeli.isVisible()
    _prawy_klik(v, _wiersz(v, fid))
    assert v._menu_tabeli.isVisible() and v._menu_kopii.menuAction().isVisible()
    assert len(_pozycje_kopii(v)) == 2
    v._menu_tabeli.hide()


def test_zajetosc_gasi_podmenu_a_slot_odmawia(widok):
    """Etap Dostawy w biegu: podmenu wygaszone z powodem zajętości, a slot (druga linia) odmawia
    zdaniem i niczego nie zapisuje. Poza perspektywą kopii zaznaczenie kilku klatek nie ma jednej
    klatki do gestu - prawy klik zostaje niczym."""
    con, v, fid, _a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    v.set_busy(True)
    _prawy_klik(v, _wiersz(v, fid))
    akcja = v._menu_kopii.menuAction()
    assert not akcja.isEnabled() and akcja.toolTip() == i18n.t("grid.inplace.busy_stage")
    v._menu_tabeli.hide()
    msg = []
    v.status_message.connect(msg.append)
    v._on_lead_copy(_loc(con, b)["id"])
    assert msg == [i18n.t("grid.inplace.busy_stage")] and not v._wb.is_busy
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    v.set_busy(False)
    v.apply_perspective("Przegląd")
    v.table.selectAll()
    vp = v.table.viewport()
    srodek = v.table.visualRect(v.model.index(_wiersz(v, fid), 0)).center()
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, srodek,
                                                 vp.mapToGlobal(srodek)))
    # Zaznaczenie kilku klatek poza perspektywą kopii: gest nie ma jednej klatki - menu milczy.
    assert not v._menu_tabeli.isVisible()


def test_puste_zaznaczenie_w_perspektywie_kopii(widok):
    """W perspektywie kopii podmenu stoi zawsze, a przy zaznaczeniu innym niż jedna klatka jest
    wygaszone z prośbą o jedną - prawy klik pod ostatnim wierszem, przy pustym zaznaczeniu."""
    con, v, fid, _a, _b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    v.table.clearSelection()
    vp = v.table.viewport()
    pod = QPoint(10, v.table.visualRect(v.model.index(_wiersz(v, fid), 0)).bottom() + 40)
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, pod, vp.mapToGlobal(pod)))
    assert v._menu_tabeli.isVisible()
    akcja = v._menu_kopii.menuAction()
    assert akcja.isVisible() and not akcja.isEnabled()
    assert akcja.toolTip() == i18n.t("grid.lead.select_one")
    v._menu_tabeli.hide()


def test_zdanie_odmowy_mowi_ze_nic_nie_zapisano():
    """Czysta funkcja zdania: odmowa niesie ścieżkę kopii (katalog i nazwa) i powód odczytu."""
    from horreum.lead_copy import LeadCopyResult
    res = LeadCopyResult("failed", 1, r"R:\X\B_CLS\m.xisf", reason="OSError: [WinError 64] x")
    zdanie = grid_mod._zdanie_kopii_wiodacej(res)
    assert zdanie == ("Nie udało się przeczytać kopii B_CLS\\m.xisf: OSError: [WinError 64] x "
                      "- nic nie zapisano.")
    bez_powrotu = grid_mod._zdanie_kopii_wiodacej(LeadCopyResult("adopted", 1, "/a/C/m.xisf"))
    assert bez_powrotu.endswith(i18n.t("grid.lead.no_back"))
