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


def _komorka_sciezki(v, fid):
    kol = [k for _, k in grid_mod.BASE_COLS].index("path")
    return v.model.data(v.model.index(_wiersz(v, fid), kol), Qt.ToolTipRole)


@pytest.fixture
def zgodne(qapp, tmp_path):
    """Klatka o dwóch kopiach ZGODNYCH z zeznaniem w ośmiu polach, różnych liczbą obrazów - przypadek
    z wizytacji: obie kopie „mówią", więc dopisek „mówi teraz" nie wskazywał żadnej."""
    from test_copy_facts import _xisf
    from test_orphan_testimony import _MASTER
    root = tmp_path / "ARCH"
    c1 = _cls(root, sub="C1")
    c2 = _xisf(root / "C2" / "m.xisf",
               _MASTER + (("FILTER", "'CLS'"), ("OBJECT", "'NGC 6888'"), ("EXPTIME", "0.205")),
               images=({"id": "integration"}, {"imageType": "Rejection"}), payload=b"\x05" * 32)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, c1)["frame_id"]
    assert _loc(con, c2)["frame_id"] == fid
    v = grid_mod.FramesView(con, now_fn=lambda: LATER)
    v.resize(1400, 800)
    v.show()
    yield con, v, fid, c1, c2
    _po_gescie(v)
    v.close()
    con.close()


def test_wybor_reki_widac_w_menu_i_w_podpowiedzi_sciezki(zgodne):
    """Z11: przy dwóch kopiach zgodnych z zeznaniem obie dostają „zgodna z zeznaniem" (nie „mówi
    teraz"), a po geście kopia wskazana ręką jest w podmenu zaznaczona i nosi znacznik - także przy
    następnym otwarciu menu i w podpowiedzi komórki „Ścieżka". Wiersz Porządków liczy klatkę jako
    decyzję ręki, nie robotę.

    Falsyfikator: zdejmij `reka` z `lead_copy_choices` → żadna pozycja nie jest zaznaczona,
    a podpowiedź ścieżki nie ma znacznika."""
    con, v, fid, c1, c2 = zgodne
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    assert v._frame_ids == [fid]
    zgodna, reka = i18n.t("grid.lead.agrees"), i18n.t("grid.lead.hand")
    _prawy_klik(v, _wiersz(v, fid))
    pozycje = _pozycje_kopii(v)
    assert [p.text() for p in pozycje] == [str(c1) + zgodna, str(c2) + zgodna]
    assert not any(p.isChecked() for p in pozycje)
    assert i18n.t("grid.tip.copy_hand") not in _komorka_sciezki(v, fid)
    msg = []
    v.status_message.connect(msg.append)
    pozycje[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    assert msg[-1].startswith("Kopia C2")                    # werdykt `confirmed`: wybór zapisany
    _prawy_klik(v, _wiersz(v, fid))
    pozycje = _pozycje_kopii(v)
    assert [p.text() for p in pozycje] == [str(c1) + zgodna, str(c2) + reka + zgodna]
    assert [p.isChecked() for p in pozycje] == [False, True]
    assert pozycje[1].toolTip().startswith(
        i18n.t("grid.lead.hand_tip", lead=i18n.t("grid.lead.menu")))
    v._menu_tabeli.hide()
    tip = _komorka_sciezki(v, fid)
    assert str(c2) + i18n.t("grid.tip.copy_hand") in tip
    assert str(c1) + i18n.t("grid.tip.copy_hand") not in tip
    tv = tasks_mod.TasksView(con, now_fn=lambda: LATER)
    try:
        tv.refresh_counts()
        it = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                  if tv.tasks.item(i).data(Qt.UserRole) == "copy_conflict_frames")
        assert it.data(rows.SECONDARY) == i18n.t("tasks.of_total", open=0, total=1) + "  ›"
        assert it.data(rows.STRONG) is False
    finally:
        tv.close()


def test_jedna_zgodna_kopia_mowi_teraz_i_nosi_znacznik_reki(widok):
    """Gdy z zeznaniem zgadza się jedna kopia, dopisek zostaje „mówi teraz"; po geście na CLS ta
    kopia mówi i jest wskazana ręką (zaznaczona), L-Pro nie ma żadnego dopisku."""
    con, v, fid, a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    _prawy_klik(v, _wiersz(v, fid))
    _pozycje_kopii(v)[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    _prawy_klik(v, _wiersz(v, fid))
    pozycje = _pozycje_kopii(v)
    assert [p.text() for p in pozycje] == [
        str(a), str(b) + i18n.t("grid.lead.hand") + i18n.t("grid.lead.speaks")]
    assert [p.isChecked() for p in pozycje] == [False, True]
    v._menu_tabeli.hide()


def _kopie_bez_faktow(con):
    """Inna klatka z dwiema obecnymi kopiami bez zebranych faktów (stan „sprzed 0021") - kandydaci
    licznika „nie wiem" (`scan.copy_facts_candidates(..., porownywalne=True)`), bez plików."""
    from horreum import repo
    fid, _ = repo.upsert_frame(con, sha1_data="sha-bez-faktow", kind="master_flat",
                               filetype="xisf", camera_id=None, now=NOW)
    for nazwa in ("X1", "X2"):
        repo.add_location(con, frame_id=fid, volume="?", path=f"/brak/{nazwa}/m.xisf",
                          header_hash=f"h-{nazwa}", now=NOW)
    assert len(scan.copy_facts_candidates(con, porownywalne=True)) == 2


def _wiersz_porzadkow(tv, klucz):
    return next(tv.tasks.item(i) for i in range(tv.tasks.count())
                if tv.tasks.item(i).data(Qt.UserRole) == klucz)


def test_wiersz_kopii_niezgodnych_po_decyzji_reki_przy_kopiach_bez_zeznania(widok):
    """Z12: decyzja ręki (robota 0 z 1) i kopie bez zeznania (dolna granica „+") składają się
    w jednej liczbie - „0 z 1+ · 2 kopie bez zeznania" - a podpowiedź mówi po kolei: gdzie gest,
    że klatka ma decyzję ręki, i co z kopiami bez zeznania. Wiersz zostaje przygaszony.

    Falsyfikator: przywróć gałąź „N+" przed „z" w `refresh_counts` → liczba mówi „1+ · …",
    a podpowiedź nie ma ani zdania o geście, ani o decyzji ręki."""
    con, v, fid, _a, _b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    _prawy_klik(v, _wiersz(v, fid))
    _pozycje_kopii(v)[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    _kopie_bez_faktow(con)
    tv = tasks_mod.TasksView(con, now_fn=lambda: LATER)
    try:
        tv.refresh_counts()
        it = _wiersz_porzadkow(tv, "copy_conflict_frames")
        assert it.data(rows.SECONDARY) == "0 z 1+ · 2 kopie bez zeznania  ›"
        assert it.data(rows.STRONG) is False
        assert it.foreground().color() == tasks_mod._DIM["fg"]
        tip = it.toolTip()
        gest = i18n.t("tasks.copy_conflict_tip", lead=i18n.t("grid.lead.menu"))
        reka = i18n.t_plural("tasks.copy_conflict_led_tip", 1)
        kopie = grid_mod.zdanie_kopii_bez_zeznania(
            scan.copy_facts_candidates(con, porownywalne=True), dest=i18n.t("nav.zbiory"))
        assert tip == f"{gest}{reka}\n{kopie}", tip
    finally:
        tv.close()


def test_wiersz_zeznania_z_nieobecnej_kopii_przy_kopiach_bez_zeznania(qapp, tmp_path):
    """Z12, drugi wiersz: „Zeznanie z nieobecnej kopii" przy kopiach bez zeznania mówi dolną granicę
    („1+ · …"), a podpowiedź niesie zdanie o geście PRZED zdaniem o kopiach bez zeznania - dawniej
    gałąź „częściowe" stała przed gałęzią gestu i zdanie o geście nie pokazywało się nigdy."""
    from test_orphan_testimony import _zniknij
    root = tmp_path / "ARCH"
    a, _b = _lpro(root), _cls(root)
    con = db.open_db(str(tmp_path / "h.db"))
    tv = None
    try:
        scan.scan_tree(con, root, volume="?", now=NOW)
        _zniknij(con, a)
        _kopie_bez_faktow(con)
        tv = tasks_mod.TasksView(con, now_fn=lambda: LATER)
        tv.refresh_counts()
        it = _wiersz_porzadkow(tv, "orphan_testimony_frames")
        assert it.data(rows.SECONDARY) == "1+ · 2 kopie bez zeznania  ›"
        assert it.data(rows.STRONG) is True
        gest = i18n.t("tasks.orphan_testimony_tip", lead=i18n.t("grid.lead.menu"))
        kopie = grid_mod.zdanie_kopii_bez_zeznania(
            scan.copy_facts_candidates(con, porownywalne=True), dest=i18n.t("nav.zbiory"))
        assert it.toolTip() == f"{gest}\n{kopie}"
    finally:
        if tv is not None:
            tv.close()
        con.close()


def test_zdanie_odmowy_mowi_ze_nic_nie_zapisano():
    """Czysta funkcja zdania: odmowa niesie ścieżkę kopii (katalog i nazwa) i powód odczytu."""
    from horreum.lead_copy import LeadCopyResult
    res = LeadCopyResult("failed", 1, r"R:\X\B_CLS\m.xisf", reason="OSError: [WinError 64] x")
    zdanie = grid_mod._zdanie_kopii_wiodacej(res)
    assert zdanie == ("Nie udało się przeczytać kopii B_CLS\\m.xisf: OSError: [WinError 64] x "
                      "- nic nie zapisano.")
    bez_powrotu = grid_mod._zdanie_kopii_wiodacej(LeadCopyResult("adopted", 1, "/a/C/m.xisf"))
    assert bez_powrotu.endswith(i18n.t("grid.lead.no_back"))
