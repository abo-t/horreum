"""Recepty paska trwają: recepty perspektyw składane ze stanu po każdym przeładowaniu (AR-298), recepta
optyki odlicza wpisy czekające w każdej szufladzie i dla każdej kopii (AR-297), recepta „Cofnij zapis
(commit N)” po zamknięciu okna kart z wykonawcą na osi obiektu (AR-296) i pole polecenia nośnika zdania.

Testy prowadzą prawdziwą drogę: `MainWindow` (gospodarz gasi receptę przy każdym raporcie, `_flash`),
prawdziwe przeładowanie, prawdziwy wątek zapisu i prawdziwe `exec()` okna kart. Czekanie na wątek - pętla
`processEvents` + `sleep` (`_czekaj`), nie `qWait`."""
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, macro, repo, scan, writeback
from horreum.gui import grid as grid_mod, grid_model, i18n, queries
from horreum.gui import tasks as tasks_mod
from horreum.gui.app import (NAV_DOM, NAV_PORZADKI, NAV_ZBIORY, STRONA_PORZADKI, MainWindow,
                             RepairHeaderDialog)
from horreum.gui.wb_worker import (EtykietaBledu, WritebackWorker, ZdanieZeSzczegolem, polecenie_zdania,
                                   szczegol_zdania, zlacz_zdania)

import test_gui_izolacja_zapisu as iz
import test_gui_rodowod_nowsze_zbiorczo as nz
from prawy_klik import menu_pola_otwarte, prawy_klik
from test_gui_app_object import NOW_PD, _nameless_tree, _select_review_tag
from test_gui_app_object import sciezka_karty  # noqa: F401  (oś obiektu z propozycją ścieżki i plikami)
from test_gui_optyka_teleskopu import widok_f  # noqa: F401  (FramesView nad RC8 f/8 x3 + f/200)
from test_gui_pasek_szczegol import _czekaj

NOW = "2026-10-21T12:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def bez_watkow(monkeypatch):
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _recepta_izolacji(klucz):
    return i18n.t(klucz, finish=i18n.t("grid.inplace.finish"), restore=i18n.t("grid.inplace.restore"),
                  release=i18n.t("grid.inplace.release"))


def _recepta_zgodnosci():
    return i18n.t("grid.sel.object_change_recipe", align=i18n.t("grid.sel.object_change_align"))


def _recepta_nowszych():
    return i18n.t("grid.lin.newer_recipe", reject=i18n.t("grid.lin.reject_newer"),
                  panel=i18n.t("grid.sel.lineage"), all=i18n.t("grid.lin.reject_newer_all"))


def _wszystkie_klatki(con):
    return {r[0] for r in con.execute("SELECT id FROM frame")}


# ============================================================ AR-298 - recepty perspektyw trwają


def _baza_izolacji(tmp_path, monkeypatch, commit):
    con, _ = iz._baza(tmp_path)
    commit(monkeypatch, con)
    con.close()
    return str(tmp_path / "h.db")


def _baza_nowszych(tmp_path, monkeypatch):
    path = str(tmp_path / "nowsze.db")
    c = db.open_db(path)
    nz._seed_dwa(c)
    c.close()
    return path


def _baza_zgodnosci(tmp_path, monkeypatch):
    path = str(tmp_path / "zgodnosc.db")
    c = db.open_db(path)
    for p in _nameless_tree(tmp_path):
        scan.ingest_record(c, scan.scan_file(str(p)), volume="V", now=NOW_PD, summary=scan.ScanSummary())
    c.close()
    monkeypatch.setattr(queries, "file_object_mismatch_frame_ids", _wszystkie_klatki)
    return path


_PERSPEKTYWY = {
    "pending_finish": (lambda t, m: _baza_izolacji(t, m, iz._commit_written), grid_mod.PRESET_PENDING_FINISH,
                       lambda: _recepta_izolacji("grid.inplace.recipe_pending")),
    "torn_write": (lambda t, m: _baza_izolacji(t, m, iz._commit_przerwany), grid_mod.PRESET_TORN_WRITE,
                   lambda: _recepta_izolacji("grid.inplace.recipe_torn")),
    "file_object_mismatch": (_baza_zgodnosci, grid_mod.PRESET_FILE_OBJECT_MISMATCH, _recepta_zgodnosci),
    "lineage_newer": (_baza_nowszych, grid_model.PRESET_LINEAGE_NEWER, _recepta_nowszych),
}


@pytest.mark.parametrize("nazwa", sorted(_PERSPEKTYWY))
def test_recepta_perspektywy_przezywa_przeladowanie(qapp, tmp_path, monkeypatch, bez_watkow, nazwa):
    """AR-298: wejście w perspektywę z receptą (droga Porządków), potem przeładowanie nie-nawigacyjne
    (wynik Pól, przebieg Dostawy) - raport wczytania gasi receptę na pasku gospodarza, a przyłożenie
    składa ją ze stanu z powrotem; wyjście na Dom i powrót do Zbiorów - recepta wraca. Na HEAD
    przeładowanie zostawiało pasek bez recepty (sonda fazy 1). Falsyfikator: `ponow_recepte` zna
    wyłącznie receptę optyki."""
    budowa, preset, tekst = _PERSPEKTYWY[nazwa]
    win = MainWindow(budowa(tmp_path, monkeypatch))
    try:
        win.resize(1400, 900)
        win.show()
        g = win.grid_view
        win._on_open_collection(preset)
        QApplication.processEvents()
        assert g._frame_ids, "perspektywa bez klatek - test nie mierzy recepty"
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == tekst()
        g.przeladuj_z_zaznaczeniem()
        QApplication.processEvents()
        assert win.recipe_label.isVisible(), "przeładowanie zgasiło receptę perspektywy"
        assert win.recipe_label.toolTip() == tekst()
        win._show_view(NAV_DOM)
        win._show_view(NAV_ZBIORY)
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == tekst()
    finally:
        win.close()


def _dziennik(v):
    log = []
    v.status_message.connect(lambda m: log.append(("S", str(m))))
    v.load_report.connect(lambda m: log.append(("L", str(m))))
    v.status_recipe.connect(lambda r: log.append(("R", r)))
    return log


def _recepta_po_ostatnim_raporcie(log):
    """Recepta, która stoi na pasku gospodarza po dzienniku: gospodarz gasi ją przy KAŻDYM raporcie."""
    ostatni = max((i for i, (k, _w) in enumerate(log) if k in ("S", "L")), default=-1)
    recepty = [w for k, w in log[ostatni + 1:] if k == "R"]
    return str(recepty[-1]) if recepty else ""


class _OknoUwag:
    def __init__(self, *, current, frame_count, parent=None):
        from horreum.gui.note_dialog import NoteIntent
        self.intent = NoteIntent("set", "chmury")

    def exec(self):
        return 1


def _perspektywa_zgodnosci_nad_f(widok, monkeypatch):
    v, con = widok
    monkeypatch.setattr(queries, "file_object_mismatch_frame_ids", _wszystkie_klatki)
    monkeypatch.setattr(grid_mod, "NoteDialog", _OknoUwag)
    v.apply_perspective(grid_mod.PRESET_FILE_OBJECT_MISMATCH)
    assert len(v._frame_ids) == 4
    f200 = next(fid for fid, fr in con.execute("SELECT frame_id, focratio_raw FROM header")
                if fr and float(fr) == 200.0)
    return v, con, f200


def test_raport_ogona_bez_recepty_przywraca_wylacznie_recepte_perspektywy(widok_f, monkeypatch):
    """AR-298 (ogon gestu): w perspektywie z klatkami gest uwag zostawia receptę „Cofnij uwagi”, potem
    zapis szuflady kończy się błędem (prawdziwy `_on_wb_failed` -> `_ogon_gestu` bez recepty). Zdanie błędu
    zgasiło receptę, którą złożyło przyłożenie - wraca recepta PERSPEKTYWY, a recepta wcześniejszego gestu
    nie (późniejszy gest ją unieważnił) - ani teraz, ani przy następnym przeładowaniu (wynik Pól, Dostawa),
    ani przy powrocie do Zbiorów (`ponow_recepte`). Falsyfikatory: ogon bez składania recepty (pasek
    pusty); ogon składa `ponow_recepte` (wraca „Cofnij uwagi”); ogon nie zeruje stanu recepty gestu
    (wraca przy następnym przyłożeniu)."""
    v, con, f200 = _perspektywa_zgodnosci_nad_f(widok_f, monkeypatch)
    v._przywroc_zaznaczenie([next(f for f in v._frame_ids if f != f200)])
    v._on_notes()
    assert v._recepta_gestu is not None, "gest uwag nie zostawił recepty - test nie mierzy unieważnienia"
    v._przywroc_zaznaczenie([f200])
    v._on_fix_optics()
    assert v._pending_count() == 1
    log = _dziennik(v)

    def _pada(*a, **k):
        raise OSError(64, "The specified network name is no longer available")
    monkeypatch.setattr(writeback, "commit", _pada)
    v._on_commit()
    QApplication.processEvents()
    assert any(k == "S" for k, _w in log), log
    assert len(v._frame_ids) == 4
    assert _recepta_po_ostatnim_raporcie(log) == _recepta_zgodnosci(), log
    for przeladuj in (v.przeladuj_z_zaznaczeniem, v.ponow_recepte, v.refresh):
        log.clear()
        przeladuj()
        QApplication.processEvents()
        assert all(str(w) in ("", _recepta_zgodnosci()) for k, w in log if k == "R"), (przeladuj, log)


def test_gest_bez_recepty_w_perspektywie_oddaje_miejsce_recepcie_perspektywy(widok_f, monkeypatch):
    """AR-298: „Cofnij uwagi”, gdy uwaga gestu została już zmieniona ręką, mówi „nie ma czego cofać” i
    zostawia pustą receptę gestu - pasek dostaje receptę perspektywy, nie pustkę do następnego
    przeładowania. Falsyfikator: `_ustaw_recepte_gestu` bez przejścia do recepty perspektywy."""
    v, con, f200 = _perspektywa_zgodnosci_nad_f(widok_f, monkeypatch)
    fid = next(f for f in v._frame_ids if f != f200)
    v._przywroc_zaznaczenie([fid])
    v._on_notes()
    repo.set_frame_note(con, frame_ids=[fid], body="inna", now=NOW)
    log = _dziennik(v)
    v._cofnij_uwagi()
    assert ("S", i18n.t("grid.notes.undo_nothing")) in log
    assert _recepta_po_ostatnim_raporcie(log) == _recepta_zgodnosci(), log


def test_dwie_flagi_receptowe_recepta_wg_priorytetu(widok_f, monkeypatch):
    """AR-298: spec perspektywy zapisuje każdą flagę osobno, a trimy się przecinają - przy dwóch flagach
    z receptą wygrywa ta, która dawniej padała ostatnia (zgodność pliku przed optyką). Falsyfikator:
    kolejność członów z optyką przed zgodnością."""
    v, con, f200 = _perspektywa_zgodnosci_nad_f(widok_f, monkeypatch)
    setattr(v, grid_model._FLAGA_OPTYKI, True)
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.refresh()
    assert v._frame_ids == [f200]                  # przecięcie obu trimów
    assert v._czlony_recepty_optyki(), "optyka bez recepty - kombinacja nie mierzy priorytetu"
    assert str(recepty[-1]) == _recepta_zgodnosci(), recepty


# ============================================================ AR-297 - odliczanie szuflady optyki


def _lokacje(con, fid):
    return [r[0] for r in con.execute("SELECT id FROM location WHERE frame_id = ? AND present = 1 "
                                      "ORDER BY id", (fid,))]


def _wpis(con, run_id, lid, keyword="FOCRATIO", status="pending"):
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword=keyword, idx=0, op="set",
                       old_value="200.0", new_value="8", new_type="float", new_comment=None,
                       expected_header_hash=None)
    if status != "pending":
        con.execute("UPDATE pending_changes SET status = ? WHERE run_id = ? AND location_id = ?",
                    (status, run_id, lid))
        con.commit()


def _druga_kopia(con, fid, tmp_path, present=1):
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", header_hash="h-kopia", now=NOW,
                            path=str(tmp_path / "kopia" / f"k{fid}_{present}.fits"))
    if not present:
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (lid,))
        con.commit()
    return lid


def test_klatki_w_szufladzie_kazda_obecna_kopia_kazdy_przebieg(widok_f, tmp_path):
    """AR-297 (read-model): klatka trafia, gdy KAŻDA obecna kopia ma czekający wpis tego keywordu z
    dowolnego przebiegu; wpis rozstrzygnięty, inny keyword i kopia nieobecna się nie liczą.
    Falsyfikatory: dowolna kopia zamiast każdej (`max`); bez warunku statusu."""
    _v, con = widok_f
    a, b, c, d = sorted(_wszystkie_klatki(con))
    _wpis(con, "STARA_SESJA", _lokacje(con, a)[0])                     # a: 1 kopia, czeka
    lb = _druga_kopia(con, b, tmp_path)                                 # b: 2 kopie, czeka jedna
    _wpis(con, "BIEZACA", _lokacje(con, b)[0])
    _wpis(con, "BIEZACA", _lokacje(con, c)[0], status="applied")       # c: rozstrzygnięty
    _wpis(con, "INNE_OKNO", _lokacje(con, d)[0], keyword="TELESCOP")   # d: inny keyword
    assert queries.klatki_w_szufladzie(con, [a, b, c, d], "FOCRATIO") == {a}
    _wpis(con, "STARA_SESJA", lb)                                       # b: czeka i druga kopia
    nieobecna = _druga_kopia(con, a, tmp_path, present=0)              # a: kopia nieobecna bez wpisu
    assert nieobecna
    assert queries.klatki_w_szufladzie(con, [a, b, c, d], "FOCRATIO") == {a, b}


def _recepty_optyki(v):
    recepty = []
    v.status_recipe.connect(recepty.append)
    return recepty


def test_recepta_optyki_odlicza_staging_starszego_przebiegu(widok_f):
    """AR-297: wpis FOCRATIO klatki f/200 czeka w przebiegu, którego ta szuflada nie prowadzi (poprzednia
    sesja, inne okno) - recepta nie każe wykonać gestu już czekającego. Na HEAD odliczanie szło wyłącznie
    z `self._run_id`. Falsyfikator: odczyt zawężony do bieżącego przebiegu."""
    v, con = widok_f
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    (f200,) = v._frame_ids
    assert v._run_id is None
    _wpis(con, "POPRZEDNIA_SESJA", _lokacje(con, f200)[0])
    recepty = _recepty_optyki(v)
    v.refresh()
    assert not any("200 → 8" in str(r) for r in recepty), recepty


def test_recepta_optyki_liczy_klatke_dopoki_kazda_kopia_nie_czeka(widok_f, tmp_path):
    """AR-297: klatka f/200 z dwiema obecnymi kopiami, wpis czeka dla jednej - druga kopia dalej ma
    niezgodną f/, recepta liczy klatkę; wpis dla drugiej - recepty f/ nie ma. Falsyfikator: klatka
    wypada, gdy czeka wpis dla dowolnej kopii."""
    v, con = widok_f
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    (f200,) = v._frame_ids
    druga = _druga_kopia(con, f200, tmp_path)
    _wpis(con, "R1", _lokacje(con, f200)[0])
    recepty = _recepty_optyki(v)
    v.refresh()
    assert recepty and "RC8 200 → 8 (1 kl.)" in str(recepty[-1]), recepty
    _wpis(con, "R2", druga)
    recepty.clear()
    v.refresh()
    assert not any("200 → 8" in str(r) for r in recepty), recepty


def test_recepta_optyki_jeden_odczyt_szuflady(widok_f, monkeypatch):
    """AR-297: zbiór klatek w szufladzie liczony RAZ na złożenie recepty, filtr w pamięci - nie zapytanie
    na każdą klatkę zbioru. Falsyfikator: odczyt w warunku comprehension (liczba wywołań = liczba klatek)."""
    v, con = widok_f
    monkeypatch.setattr(queries, "f_ratio_mismatch_frame_ids", _wszystkie_klatki)
    v.apply_perspective(grid_mod.PRESET_F_RATIO_MISMATCH)
    assert len(v._frame_ids) == 4
    prawdziwy, wywolania = queries.klatki_w_szufladzie, []
    monkeypatch.setattr(queries, "klatki_w_szufladzie",
                        lambda *a: (wywolania.append(a), prawdziwy(*a))[1])
    v.ponow_recepte()
    assert len(wywolania) == 1, wywolania


# ============================================================ AR-296 - cofnięcie zapisu kart z paska


def _okno_naprawy(tmp_path, n=2):
    """`MainWindow` nad bazą z `n` lightami bez OBJECT, na podstronie osi obiektu, kubełek „bez nazwy”."""
    path = tmp_path / "naprawa.db"
    con = db.open_db(str(path))
    nazwy = tuple(f"NGC7635_20230103_{chr(97 + i)}.fits" for i in range(n))
    pliki = _nameless_tree(tmp_path, names=nazwy)
    for p in pliki:
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD, summary=scan.ScanSummary())
    con.close()
    win = MainWindow(str(path))
    win.resize(1400, 900)
    win.show()
    win._show_view(NAV_PORZADKI)
    win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_OBJECTS)
    win.object_view.refresh()
    QApplication.processEvents()
    return win, path, pliki


def _naprawa_prawdziwym_exec(win):
    """„Napraw nagłówek…” przez PRAWDZIWE `exec()`: zegar klika „Zapisz karty”, czeka na koniec biegu okna
    i klika przycisk zamknięcia; bezpiecznik modalny zamyka okno sam (`reject`), gdy przycisku nie
    znajdzie albo okno stoi za długo. Zwraca numer commitu; po powrocie okno nie żyje."""
    ov = win.object_view
    _select_review_tag(ov, "nameless")
    stan = {"krok": 0, "commit": None}

    def _krok():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, RepairHeaderDialog):
            return
        if stan["krok"] == 0:
            stan["krok"] = 1
            QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        elif stan["krok"] == 1 and not dlg._runner.is_busy and dlg._commit_id is not None:
            stan["krok"], stan["commit"] = 2, dlg._commit_id
            QTest.mouseClick(dlg._close_btn, Qt.LeftButton)

    def _bezpiecznik():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    zegar, bezpiecznik = QTimer(), QTimer()
    zegar.timeout.connect(_krok)
    bezpiecznik.setSingleShot(True)
    bezpiecznik.timeout.connect(_bezpiecznik)
    zegar.start(20)
    bezpiecznik.start(60000)
    try:
        QTest.mouseClick(ov.repair_btn, Qt.LeftButton)
    finally:
        zegar.stop()
        bezpiecznik.stop()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert stan["krok"] == 2, f"okno kart nie przeszło zapisu i zamknięcia: {stan}"
    assert QApplication.activeModalWidget() is None
    assert not [d for d in win.findChildren(RepairHeaderDialog) if d.isVisible()]
    return stan["commit"]


def _klik_recepty(win):
    _czekaj(lambda: not win._recepta_wstrzymana, "blokada dwukliku recepty")
    assert win.recipe_label.isVisible() and win.recipe_label.isEnabled()
    QTest.mouseClick(win.recipe_label, Qt.LeftButton)


def _czekaj_na_cofniecie(win):
    ov = win.object_view
    _czekaj(lambda: not ov._zapis_kart_trwa, "koniec cofnięcia z paska")


def _bajty(pliki):
    return [p.read_bytes() for p in pliki]


@pytest.fixture
def brama(monkeypatch):
    """Brama w wątku workera zapisu po pierwszym pliku (wzór testu AR-280): `doszlo` - worker czeka,
    `zwolnij()` - idzie dalej. Bezpiecznik 30 s po stronie workera."""
    stan = types_ns(doszlo=threading.Event(), puszczona=threading.Event(), wlaczona=False)
    prawdziwy = WritebackWorker._emit_progress

    def _postep(self, done, total, p, status):
        prawdziwy(self, done, total, p, status)
        if stan.wlaczona and done == 1:
            stan.doszlo.set()
            stan.puszczona.wait(30)
    monkeypatch.setattr(WritebackWorker, "_emit_progress", _postep)
    yield stan
    stan.puszczona.set()


class types_ns:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_recepta_cofnij_zapis_po_zamknieciu_naprawy_cofa_commit(qapp, tmp_path, bez_watkow):
    """AR-296: „Napraw nagłówek…” zapisuje karty i zamyka się prawdziwym przyciskiem - pasek mówi wynik
    z poleceniem CLI, a obok stoi recepta „Cofnij zapis (commit N)” z wykonawcą. Klik cofa commit tym
    samym rdzeniem (bajty plików jak przed zapisem), zdanie mówi wynik, recepta schodzi (cofnięcie
    domknięte). Falsyfikator: brak recepty po zdaniu okna naprawy."""
    win, path, pliki = _okno_naprawy(tmp_path)
    przed = _bajty(pliki)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        assert _bajty(pliki) != przed
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert _bajty(pliki) == przed
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 2))
        assert not win.recipe_label.isVisible()
    finally:
        win.close()


def test_recepta_cofnij_zapis_po_zamknieciu_okna_sciezki(sciezka_karty):
    """AR-296: „Zatwierdź ze ścieżki…” przez PRAWDZIWE `exec()` - zegar klika „Zatwierdź wszystko”, czeka
    na koniec zapisu kart i klika „Zamknij”. Po zdaniu okna oś podaje receptę „Cofnij zapis (commit N)”,
    a jej wykonawca cofa karty (bajty pliku jak przed zapisem) i mówi notą tego okna. Falsyfikator: brak
    recepty po zdaniu okna ścieżki."""
    from PySide6.QtWidgets import QPushButton
    from horreum.gui.app import ConfirmPathObjectsDialog
    from test_gui_pasek_szczegol import _klik_okna_sciezki
    v, con, pliki, _fid = sciezka_karty
    przed = pliki["zapis"].read_bytes()
    recepty, zdania = [], []
    v.status_recipe.connect(recepty.append)
    v.wynik_cofniecia.connect(lambda msg, _recepta: zdania.append(msg))   # zdania biegu cofnięcia
    stan = {"krok": 0}

    def _krok():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, ConfirmPathObjectsDialog):
            return
        if stan["krok"] == 0:
            stan["krok"] = 1
            QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton)
        elif stan["krok"] == 1 and not dlg._runner.is_busy and dlg._commit_id is not None:
            stan["krok"], stan["commit"] = 2, dlg._commit_id
            zamknij = next(b for b in dlg.findChildren(QPushButton) if b.text() == i18n.t("path.close_btn"))
            QTest.mouseClick(zamknij, Qt.LeftButton)

    def _bezpiecznik():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    zegar, bezpiecznik = QTimer(), QTimer()
    zegar.timeout.connect(_krok)
    bezpiecznik.setSingleShot(True)
    bezpiecznik.timeout.connect(_bezpiecznik)
    zegar.start(20)
    bezpiecznik.start(60000)
    try:
        _klik_okna_sciezki(v)
    finally:
        zegar.stop()
        bezpiecznik.stop()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert stan["krok"] == 2, stan
    assert pliki["zapis"].read_bytes() != przed
    assert recepty and str(recepty[-1]) == i18n.t("wb.undo_recipe", id=stan["commit"]), recepty
    recepty[-1].czlony[0].wykonaj()
    _czekaj(lambda: not v._zapis_kart_trwa, "koniec cofnięcia z recepty")
    assert pliki["zapis"].read_bytes() == przed
    assert str(zdania[-1]).endswith(i18n.t("path.cards_restored_closed_note")), zdania[-1]


def test_kopiuj_polecenie_z_paska_po_naprawie(qapp, tmp_path, bez_watkow):
    """AR-309 (ostatnie ogniwo nośnika): po zamknięciu okna kart pole raportu gospodarza niesie samo
    polecenie cofnięcia - prawy klik -> „Kopiuj polecenie” daje je znak w znak. Falsyfikatory:
    `_wyswietl` bez pola polecenia; `_zdanie_okna_kart` gubi polecenie wariantu."""
    win, path, pliki = _okno_naprawy(tmp_path)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        polecenie = i18n.t("wb.undo_cli", db=queries.db_path_of(win.con), id=commit)
        assert polecenie_zdania(win._pelny_komunikat) == polecenie
        prawy_klik(win.report_label)
        pozycje = menu_pola_otwarte(win.report_label)
        pozycje[i18n.t("wb.copy_command")].trigger()
        win.report_label._menu.hide()
        assert QGuiApplication.clipboard().text() == polecenie
    finally:
        win.close()


def test_nosnik_zlacza_polecenia_a_zwykly_str_go_nie_ma(qapp):
    """AR-309: `zlacz_zdania` składa polecenia jak szczegóły (wiersz pod wierszem), zwykły `str` nie ma
    polecenia. Falsyfikator: złączenie gubi pole polecenia."""
    z = zlacz_zdania(" - ", (ZdanieZeSzczegolem("a", "s", "p1"), "b", ZdanieZeSzczegolem("c", "", "p2")))
    assert str(z) == "a - b - c" and szczegol_zdania(z) == "s"
    assert polecenie_zdania(z) == "p1\np2"
    assert polecenie_zdania("goły tekst") == ""


def test_recepta_cofnij_zapis_juz_cofniety_mowi_juz_cofniete(qapp, tmp_path, bez_watkow):
    """AR-296: commit cofnięty inną drogą (polecenie CLI ze zdania - `writeback.undo` na drugim
    połączeniu) przed kliknięciem recepty - rdzeń odpowiada „już cofnięte”, pasek to mówi, recepta schodzi,
    bajty bez zmian."""
    win, path, pliki = _okno_naprawy(tmp_path)
    przed = _bajty(pliki)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        con2 = db.connect(str(path))
        try:
            assert len(writeback.undo(con2, commit, now=NOW).restored) == 2
        finally:
            con2.close()
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert i18n.t_plural("wb.undo_already", 2) in str(win._pelny_komunikat)
        assert not win.recipe_label.isVisible()
        assert _bajty(pliki) == przed
    finally:
        win.close()


def test_recepta_cofnij_zapis_po_nowszym_zapisie_zostaje_z_powodem(qapp, tmp_path, bez_watkow):
    """AR-296: nowszy zapis tej samej kopii po commicie kart - rdzeń odmawia cofnięcia tego pliku (nie
    cofa cudzego zapisu), drugi plik wraca. Uchwyt zostaje: recepta wraca, zdanie mówi regułę ponowienia
    etykietą recepty, polecenie CLI jedzie polem polecenia. Falsyfikator: recepta nie wraca przy
    cofnięciu niedomkniętym."""
    win, path, pliki = _okno_naprawy(tmp_path)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        con2 = db.connect(str(path))
        try:
            fid = con2.execute("SELECT frame_id FROM location WHERE path = ?", (str(pliki[0]),)).fetchone()[0]
            pv, powod = macro.plan_manual_change(
                queries.writeback_frame_targets(con2, [fid]), "TELESCOP", "EQ6",
                cards_fn=lambda lid: queries.location_cards(con2, lid))
            assert pv is not None, powod
            repo.stage_pending_replacing(con2, run_id="NOWSZY", preview=pv)
            assert writeback.commit(con2, "NOWSZY", now=NOW, inplace=True).commit_id is not None
        finally:
            con2.close()
        po_nowszym = pliki[0].read_bytes()
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert pliki[0].read_bytes() == po_nowszym, "rdzeń cofnął cudzy, nowszy zapis"
        etykieta = i18n.t("wb.undo_recipe", id=commit)
        assert i18n.t("grid.wb.undo_retry", undo=etykieta) in str(win._pelny_komunikat)
        assert polecenie_zdania(win._pelny_komunikat) == i18n.t(
            "wb.undo_cli", db=queries.db_path_of(win.con), id=commit)
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == etykieta
    finally:
        win.close()


def test_recepta_cofnij_zapis_odmawia_w_biegu_dostawy_i_przy_zapisie_zbiorow(qapp, tmp_path, bez_watkow):
    """AR-296: w biegu Dostawy i w biegu zapisu szuflady Zbiorów recepta odmawia zdaniem z numerem commitu
    (polecenie CLI w szczególe i w polu polecenia), pliki bez zmian; koniec blokady podaje receptę
    ponownie ze zdaniem. Blokady przełączane tu wprost na osi (zdanie odmowy i podanie po końcu blokady); drogę
    prawdziwego końca etapu Dostawy pinuje `test_recepta_odlozona_przez_etap_dostawy_stoi_po_odswiezeniu_widokow`,
    prawdziwego końca zapisu Zbiorów - `test_recepta_odlozona_wraca_po_prawdziwym_koncu_zapisu_zbiorow`.
    Falsyfikatory: brak strażnika `_busy`; brak strażnika zapisu Zbiorów."""
    win, path, pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        po = _bajty(pliki)
        polecenie = i18n.t("wb.undo_cli", db=queries.db_path_of(win.con), id=commit)
        for ustaw, klucz in ((ov.set_busy, "wb.undo_recipe_busy"),
                             (ov.set_writeback_busy, "wb.undo_recipe_foreign")):
            ustaw(True)
            _klik_recepty(win)
            assert win._pelny_komunikat == i18n.t(klucz, id=commit)
            assert polecenie_zdania(win._pelny_komunikat) == polecenie
            assert polecenie in szczegol_zdania(win._pelny_komunikat)
            assert not win._zegar_raportu.isActive()
            assert not ov._zapis_kart_trwa and _bajty(pliki) == po
            ustaw(False)
            assert win._pelny_komunikat == i18n.t("wb.undo_recipe_ready", id=commit)
            assert win.recipe_label.isVisible()
    finally:
        win.close()


def test_recepta_odlozona_wraca_po_prawdziwym_koncu_zapisu_zbiorow(qapp, tmp_path, bez_watkow, brama):
    """AR-296: klik recepty w biegu PRAWDZIWEGO zapisu szuflady Zbiorów (makro na klatkach tej bazy,
    „Zatwierdź”, brama w wątku zapisu) - odmowa; koniec zapisu (uchwyt gridu zwalnia mutex) podaje
    receptę ponownie ze zdaniem. Raporty Zbiorów zgasiły przycisk recepty Porządków, więc test wykonuje
    jej człon wprost (ten sam wykonawca, co klik). Falsyfikator: koniec blokady bez ponownego podania
    recepty."""
    win, path, pliki = _okno_naprawy(tmp_path)
    ov, g = win.object_view, win.grid_view
    try:
        commit = _naprawa_prawdziwym_exec(win)
        win._show_view(NAV_ZBIORY)
        g.refresh()
        g.macro_bar.asg_kw.setCurrentText("TELESCOP")
        g.macro_bar.asg_op.setCurrentIndex(0)
        g.macro_bar.asg_expr.setText("EQ6")
        g.macro_bar._emit_stage()
        assert g._pending_count() == 2, "makro bez stagingu - test nie mierzy blokady"
        brama.wlaczona = True
        QTest.mouseClick(g.drawer.btn_commit, Qt.LeftButton)
        _czekaj(brama.doszlo.is_set, "pierwszy plik zapisu szuflady")
        assert ov._foreign_wb is True
        win._show_view(NAV_PORZADKI)
        stan = win._recepta_porzadkow_stan
        assert stan is not None, "brak recepty cofnięcia - test nie mierzy odmowy"
        stan[0].czlony[0].wykonaj()
        assert win._pelny_komunikat == i18n.t("wb.undo_recipe_foreign", id=commit)
        assert not win.recipe_label.isVisible()
        brama.wlaczona = False
        brama.puszczona.set()
        _czekaj(lambda: not g._wb.is_busy, "koniec zapisu szuflady")
        for _ in range(10):
            QApplication.processEvents()
        assert ov._foreign_wb is False
        assert win.recipe_label.isVisible(), win._pelny_komunikat
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
        assert i18n.t("wb.undo_recipe_ready", id=commit) == str(win._recepta_porzadkow_stan[1])
    finally:
        brama.puszczona.set()
        win.close()


def test_zamkniecie_okna_w_biegu_cofniecia_z_paska_odmawia_i_anuluje(qapp, tmp_path, bez_watkow, brama):
    """AR-296: zamknięcie okna gospodarza w biegu cofnięcia z paska - okno zostaje, połączenie żyje,
    cofnięcie dostaje anulowanie po bieżącym pliku; wynik przerwany mówi, ile plików zostało, recepta
    wraca; drugie zamknięcie zamyka. Falsyfikator: straż zamknięcia bez uchwytu osi (abort wątku)."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    try:
        _naprawa_prawdziwym_exec(win)
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        assert win.close() is False
        assert win.isVisible() and win.con is not None
        assert win._pelny_komunikat == i18n.t("wb.close_refused")
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        assert win.recipe_label.isVisible()
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 1))
    finally:
        brama.puszczona.set()
        assert win.close() is True
        assert win.con is None


def test_przelaczenie_bazy_w_biegu_cofniecia_odmawia(qapp, tmp_path, bez_watkow, brama):
    """AR-296: przełączenie bazy w biegu cofnięcia z paska odmawia samym zdaniem (demontaż widoków
    skasowałby wątek w biegu) - BEZ anulowania: cofnięcie biegnie dalej i kończy wszystkie pliki, baza i oś
    zostają; po biegu przełączenie działa, a żaden callback nie trafia w nową oś. Falsyfikatory:
    `_open_path` bez straży zapisu (abort wątku albo ogon na zamkniętej bazie); odmowa z anulowaniem."""
    druga = str(tmp_path / "druga.db")
    db.open_db(druga).close()
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    try:
        _naprawa_prawdziwym_exec(win)
        ov = win.object_view
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        win._open_path(druga)
        assert win.db_path == str(path) and win.object_view is ov
        assert win._pelny_komunikat == i18n.t("wb.undo_switch_refused")
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 3))
        assert not win.recipe_label.isVisible()
        win._open_path(druga)
        assert win.db_path == druga and win.object_view is not ov
        nowa, zdania = win.object_view, []
        nowa.status_message.connect(zdania.append)
        for _ in range(20):
            QApplication.processEvents()
        assert zdania == []
    finally:
        brama.puszczona.set()
        win.close()


def test_callbacki_po_demontazu_osi_wracaja_bez_skutku(qapp, tmp_path, bez_watkow, brama):
    """AR-296: demontaż osi (`zatrzymaj_pola`) w biegu cofnięcia z paska - spóźniony postęp kolejnych
    plików i zakończenie nie zmieniają paska ani raportów odłożonych, a mutex zwalnia uchwyt
    (`busy_changed`). Falsyfikatory: wynik bez porównania generacji; postęp bez porównania generacji."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    try:
        _naprawa_prawdziwym_exec(win)
        ov = win.object_view
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        QApplication.processEvents()
        ov.zatrzymaj_pola()
        pasek, odlozone = win._pelny_komunikat, dict(win._odlozone_raporty)
        recepta = win.recipe_label.isVisible()
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        for _ in range(20):
            QApplication.processEvents()
        assert win._pelny_komunikat is pasek and dict(win._odlozone_raporty) == odlozone
        assert win.recipe_label.isVisible() == recepta
        assert win.grid_view._foreign_wb is False          # mutex zwolniony przez uchwyt
    finally:
        brama.puszczona.set()
        win.close()


def test_callback_porazki_po_demontazu_osi_wraca_bez_skutku(qapp, tmp_path, bez_watkow, monkeypatch):
    """AR-296: porażka cofnięcia z paska doręczona po demontażu osi nie zmienia paska."""
    win, path, pliki = _okno_naprawy(tmp_path)
    puszczona = threading.Event()
    try:
        _naprawa_prawdziwym_exec(win)
        ov = win.object_view

        def _pada(*a, **k):
            puszczona.wait(30)
            raise OSError(64, "The specified network name is no longer available")
        monkeypatch.setattr(writeback, "undo", _pada)
        _klik_recepty(win)
        QApplication.processEvents()
        ov.zatrzymaj_pola()
        pasek = win._pelny_komunikat
        puszczona.set()
        _czekaj_na_cofniecie(win)
        for _ in range(20):
            QApplication.processEvents()
        assert win._pelny_komunikat is pasek
    finally:
        puszczona.set()
        win.close()


def test_recepta_cofniecia_padla_mowi_powodem_i_wraca(qapp, tmp_path, bez_watkow, monkeypatch):
    """AR-296: wyjątek workera cofnięcia z paska - zdanie błędu ze szczegółem systemu, recepta wraca
    (nie wiadomo, czy pliki wróciły), mutex zwolniony."""
    win, path, pliki = _okno_naprawy(tmp_path)
    try:
        commit = _naprawa_prawdziwym_exec(win)

        def _pada(*a, **k):
            raise OSError(64, "The specified network name is no longer available")
        monkeypatch.setattr(writeback, "undo", _pada)
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert str(win._pelny_komunikat).startswith(i18n.t("grid.wb.error", msg="§").split("§")[0])
        assert win.recipe_label.isVisible()
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
        assert win.grid_view._foreign_wb is False
    finally:
        win.close()


def test_recepta_porzadkow_wiazana_z_raportem_takze_odlozonym(qapp, tmp_path, bez_watkow, brama):
    """AR-296: recepta Porządków nie wchodzi do Zbiorów (dawniej zostawała tam, gdy grid nie miał własnej),
    wraca z Porządkami, póki stoi jej raport, a nowszy raport ją unieważnia. Wynik cofnięcia, który
    przyszedł, gdy człowiek był w Zbiorach (raport odłożony), wraca w Porządkach RAZEM z receptą
    ponowienia - wynik pada OD RAZU na pasku Zbiorów (bez odkładania), a recepta czeka na Porządki
    i nie gaśnie po jednej wizycie. Falsyfikatory: brak zdjęcia przy wejściu w Zbiory; brak ponowienia
    w Porządkach; wynik odłożony do Porządków; wynik związany z Porządkami (gaśnie po wyjściu)."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    ov = win.object_view
    try:
        _naprawa_prawdziwym_exec(win)
        win._show_view(NAV_ZBIORY)
        assert not win.recipe_label.isVisible()
        win._show_view(NAV_PORZADKI)
        assert win.recipe_label.isVisible()
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        win._show_view(NAV_ZBIORY)
        ov.refuse_close(lambda _t: None)            # anulowanie po bieżącym pliku - wynik częściowy
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 1))
        assert i18n.t("wb.undo_recipe_place") in str(win._pelny_komunikat)
        assert not win.recipe_label.isVisible()
        for _ in range(2):
            win._show_view(NAV_PORZADKI)
            assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 1))
            assert win.recipe_label.isVisible(), "recepta ponowienia nie wróciła z wynikiem"
            win._show_view(NAV_ZBIORY)
        win._show_view(NAV_PORZADKI)
        win._flash("inny raport")
        win._show_view(NAV_ZBIORY)
        win._show_view(NAV_PORZADKI)
        assert not win.recipe_label.isVisible()
    finally:
        brama.puszczona.set()
        win.close()


def test_odlozony_raport_osi_z_recepta_nie_gasnie_po_jednej_wizycie(qapp, tmp_path, bez_watkow):
    """AR-296: raport osi ze szczegółem i receptą przyszedł, gdy człowiek był w Zbiorach (odłożony do
    Porządków) - przy wejściu staje bez wiązania z miejscem, więc zdanie i recepta są także po
    Porządki -> Zbiory -> Porządki. Falsyfikator: odłożony raport stawiany z wiązaniem do Porządków."""
    from horreum.gui.grid_model import CzlonRecepty, Recepta
    win, path, pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    try:
        win._show_view(NAV_ZBIORY)
        zdanie = ZdanieZeSzczegolem("wynik osi", "szczegół")
        ov.status_message.emit(zdanie)
        ov.status_recipe.emit(Recepta([CzlonRecepty("Cofnij X", lambda: None)]))
        assert win._odlozone_raporty.get(STRONA_PORZADKI) is zdanie
        for _ in range(2):
            win._show_view(NAV_PORZADKI)
            assert win._pelny_komunikat is zdanie and win.recipe_label.isVisible()
            win._show_view(NAV_ZBIORY)
            assert win._pelny_komunikat is zdanie and not win.recipe_label.isVisible()
    finally:
        win.close()


def test_porazka_cofniecia_poza_porzadkami_wraca_z_recepta(qapp, tmp_path, bez_watkow, monkeypatch):
    """AR-296: start cofnięcia z paska, wyjście do Zbiorów, porażka workera - zdanie błędu pada od razu,
    a po powrocie do Porządków stoi z receptą ponowienia. Falsyfikator: porażka odłożona do Porządków
    bez wiązania recepty."""
    win, path, pliki = _okno_naprawy(tmp_path)
    puszczona = threading.Event()
    try:
        commit = _naprawa_prawdziwym_exec(win)

        def _pada(*a, **k):
            puszczona.wait(30)
            raise OSError(64, "The specified network name is no longer available")
        monkeypatch.setattr(writeback, "undo", _pada)
        _klik_recepty(win)
        win._show_view(NAV_ZBIORY)
        puszczona.set()
        _czekaj_na_cofniecie(win)
        bledu = i18n.t("grid.wb.error", msg="§").split("§")[0]
        assert str(win._pelny_komunikat).startswith(bledu)
        win._show_view(NAV_PORZADKI)
        assert str(win._pelny_komunikat).startswith(bledu)
        assert win.recipe_label.isVisible()
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
    finally:
        puszczona.set()
        win.close()


def test_wynik_cofniecia_widoczny_na_domu_po_odmowie_zamkniecia(qapp, tmp_path, bez_watkow, brama):
    """AR-296: klik recepty w Porządkach, przejście na Dom, zamknięcie okna w biegu - odmowa obiecuje, że
    zapis pokaże wynik: wynik przerwany stoi na pasku Domu (nie czeka w raportach odłożonych Porządków).
    Potem „Otwórz bazę…” w biegu drugiego cofnięcia - odmowa, a wynik po końcu biegu nie ginie.
    Falsyfikator: wynik idzie kanałem odkładanym do Porządków."""
    druga = str(tmp_path / "druga.db")
    db.open_db(druga).close()
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    try:
        _naprawa_prawdziwym_exec(win)
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        win._show_view(NAV_DOM)
        assert win.close() is False
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 1))
        assert STRONA_PORZADKI not in win._odlozone_raporty
        brama.doszlo.clear()
        brama.puszczona.clear()
        win._show_view(NAV_PORZADKI)
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik ponowienia")
        win._show_view(NAV_DOM)
        win._open_path(druga)
        assert win.db_path == str(path)
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        assert str(win._pelny_komunikat).startswith(i18n.t_plural("grid.wb.restored", 2)) or \
            i18n.t_plural("wb.undo_already", 1) in str(win._pelny_komunikat)
    finally:
        brama.puszczona.set()
        win.close()


def test_start_cofniecia_zdejmuje_recepte_i_drugi_klik_nie_rusza_drugiego_biegu(qapp, tmp_path, bez_watkow,
                                                                                monkeypatch):
    """AR-296: start cofnięcia z paska mówi „Cofam zapis (commit N)…” i zdejmuje przycisk recepty - w biegu
    nie stoi czynny przycisk, który nic nie robi; drugie wykonanie członu recepty w biegu nie rusza
    drugiego biegu (ten sam commit, jedno wywołanie rdzenia, bajty jak przed zapisem). Falsyfikatory:
    start bez zdania (przycisk czynny); brak strażnika biegu."""
    win, path, pliki = _okno_naprawy(tmp_path)
    przed = _bajty(pliki)
    puszczona, wywolania = threading.Event(), []
    prawdziwy = writeback.undo
    try:
        commit = _naprawa_prawdziwym_exec(win)

        def _czeka(con, cid, **kw):
            wywolania.append(cid)
            puszczona.wait(30)
            return prawdziwy(con, cid, **kw)
        monkeypatch.setattr(writeback, "undo", _czeka)
        recepta = win._recepta_porzadkow_stan[0]
        _klik_recepty(win)
        QApplication.processEvents()
        assert win._pelny_komunikat == i18n.t("wb.undo_recipe_started", id=commit)
        assert not win.recipe_label.isVisible()
        recepta.czlony[0].wykonaj()                 # drugi klik tego samego członu w biegu
        puszczona.set()
        _czekaj_na_cofniecie(win)
        for _ in range(10):
            QApplication.processEvents()
        assert wywolania == [commit]
        assert _bajty(pliki) == przed
    finally:
        puszczona.set()
        win.close()


def test_wynik_cofniecia_mowi_o_obiekcie_z_cofnietej_karty(qapp, tmp_path, bez_watkow):
    """AR-311 (wariant A): po zapisie kart przeszło „Rozwiąż” (obiekt z karty w bazie) - cofnięcie z paska
    zdejmuje kartę z plików I przywraca stan obiektu sprzed zapisu: klatki znów bez obiektu, a kolejka osi
    znów ma kubełek bezimiennych; zdanie wyniku mówi liczbę z rdzenia. Falsyfikator: zdanie bez członu
    obiektów (`zdanie_undo_kart`) albo klatki z obiektem z cofniętej karty."""
    from horreum import derive
    from horreum.gui.app import _REVIEW_TAG
    win, path, pliki = _okno_naprawy(tmp_path)
    try:
        _naprawa_prawdziwym_exec(win)
        con2 = db.connect(str(path))
        try:
            derive.DERIVED["resolve"](con2, NOW, lambda: False)
            assert con2.execute("SELECT count(*) FROM frame WHERE object_source = 'header'"
                                ).fetchone()[0] == 2
        finally:
            con2.close()
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert i18n.t_plural("wb.undo_objects_restored", 2) in str(win._pelny_komunikat)
        assert win.con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL"
                               ).fetchone()[0] == 0
        ov = win.object_view
        ov.refresh()
        assert "nameless" in {ov.review.item(i).data(_REVIEW_TAG) for i in range(ov.review.count())}
    finally:
        win.close()


def test_cofniecie_z_paska_gasi_powierzchnie_zapisu(qapp, tmp_path, bez_watkow, brama):
    """AR-296: w biegu cofnięcia z paska „Napraw nagłówek…” (aktywny przed klikiem), zapis Zbiorów i
    „Wciągnij z WBPP…” Domu gasną; po biegu przycisk osi wraca. Flaga biegu z sygnału uchwytu - uchwyt
    ogłasza start, zanim ustawi wątek. Falsyfikator: slot czyta `is_busy` uchwytu (przycisk aktywny)."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    ov = win.object_view
    try:
        _naprawa_prawdziwym_exec(win)
        con2 = db.connect(str(path))
        try:
            for p in _nameless_tree(tmp_path / "inne", names=("NGC7635_20230104_z.fits",), seed=7):
                scan.ingest_record(con2, scan.scan_file(str(p)), volume="V", now=NOW_PD,
                                   summary=scan.ScanSummary())
        finally:
            con2.close()
        ov._load_review()                            # kolejka bez raportu - recepta stoi
        _select_review_tag(ov, "nameless")
        assert ov.repair_btn.isEnabled(), "przycisk wygaszony przed biegiem - test nie mierzy mutexu"
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        QApplication.processEvents()
        assert not ov.repair_btn.isEnabled()
        assert win.grid_view._foreign_wb is True
        assert win._powod_odmowy_zniw() == i18n.t("pipeline.refuse.writeback")   # reguła „Wciągnij…” Domu (AR-354)
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        _select_review_tag(ov, "nameless")
        assert ov.repair_btn.isEnabled()
    finally:
        brama.puszczona.set()
        win.close()


_SKRYPT_BLOKADY = '''
import contextlib, os, sys, time
sys.path.insert(0, sys.argv[1])
from horreum import db, writeback
znacznik, zwolnij = sys.argv[4], sys.argv[5]
prawdziwy = writeback._exclusive

@contextlib.contextmanager
def _z_bariera(path):
    with prawdziwy(path) as fh:
        with open(znacznik, "w", encoding="utf-8") as f:
            f.write(os.fspath(path))
        koniec = time.monotonic() + 60
        while not os.path.exists(zwolnij) and time.monotonic() < koniec:
            time.sleep(0.02)
        yield fh

writeback._exclusive = _z_bariera
con = db.connect(sys.argv[2])
res = writeback.undo(con, int(sys.argv[3]), now="2026-10-21T12:00:00")
print("restored", len(res.restored), "failed", len(res.failed), "blocked", len(res.blocked),
      "already", len(res.already))
'''


def test_dwaj_wykonawcy_cofniecia_jednego_pliku_w_dwoch_procesach(qapp, tmp_path, bez_watkow):
    """AR-296 (wyłączność): drugi proces cofa ten sam commit i trzyma blokadę pliku (`writeback._exclusive`)
    pierwszego pliku - recepta z paska w tym czasie nie zmienia tego pliku (rdzeń odmawia), drugi plik
    cofa; uchwyt zostaje (recepta wraca). Po zwolnieniu drugi proces kończy, ponowna recepta mówi „już
    cofnięte” i schodzi; bajty obu plików jak przed zapisem, bez plików tymczasowych. Falsyfikatory:
    blokada pliku dopuszczająca drugiego pisarza; recepta bez ponowienia."""
    win, path, pliki = _okno_naprawy(tmp_path)
    przed = _bajty(pliki)
    skrypt, znacznik, zwolnij = tmp_path / "blokada.py", tmp_path / "w_blokadzie", tmp_path / "zwolnij"
    skrypt.write_text(_SKRYPT_BLOKADY, encoding="utf-8")
    korzen = str(pathlib.Path(writeback.__file__).resolve().parents[1])
    proc = None
    try:
        commit = _naprawa_prawdziwym_exec(win)
        po_zapisie = _bajty(pliki)
        proc = subprocess.Popen([sys.executable, str(skrypt), korzen, str(path), str(commit),
                                 str(znacznik), str(zwolnij)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        _czekaj(lambda: znacznik.exists() and znacznik.read_text(encoding="utf-8")
                or proc.poll() is not None, "drugi proces w blokadzie", s=60)
        assert znacznik.exists(), proc.communicate()
        sciezka = os.path.normcase(os.path.abspath(znacznik.read_text(encoding="utf-8")))
        trzymany = next(i for i, p in enumerate(pliki) if os.path.normcase(os.path.abspath(p)) == sciezka)
        wolny = 1 - trzymany
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        # PRZED zwolnieniem bariery: plik nietrzymany cofnięty, trzymany nietknięty, zdanie paska mówi
        # jeden przywrócony i jeden, którego nie dało się cofnąć (powód w szczególe), uchwyt zostaje.
        assert pliki[wolny].read_bytes() == przed[wolny], "cofnięcie z paska padło w całości"
        assert pliki[trzymany].read_bytes() == po_zapisie[trzymany], "drugi pisarz w trzymanym pliku"
        zdanie = str(win._pelny_komunikat)
        assert zdanie.startswith(i18n.t_plural("grid.wb.restored", 1)), zdanie
        assert (i18n.t_plural("grid.wb.errors", 1) in zdanie
                or i18n.t_plural("grid.wb.blocked", 1) in zdanie), zdanie
        assert pliki[trzymany].name in zdanie, zdanie          # powód konfliktu nazywa trzymany plik
        assert win.recipe_label.isVisible(), "uchwyt zgasł przy pliku, który nie wrócił"
        zwolnij.write_text("", encoding="utf-8")
        wyjscie, bledy = proc.communicate(timeout=120)
        assert proc.returncode == 0, bledy
        # Drugi proces: trzymany plik przywrócił, nietrzymany zastał już cofnięty.
        assert wyjscie.split() == ["restored", "1", "failed", "0", "blocked", "1", "already", "1"], wyjscie
        assert _bajty(pliki) == przed
        # Końcowa próba osobnym etapem: recepta mówi „już cofnięte” i schodzi.
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert i18n.t_plural("wb.undo_already", 2) in str(win._pelny_komunikat)
        assert _bajty(pliki) == przed
        assert not win.recipe_label.isVisible()
        resztki = [p.name for p in pliki[0].parent.iterdir() if p not in pliki]
        assert resztki == [], resztki
    finally:
        zwolnij.write_text("", encoding="utf-8")
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        win.close()


# ============================================================ straż zapisu bez bazy i widoków


def test_straz_zapisu_bez_bazy_i_widokow(qapp, tmp_path, bez_watkow):
    """AR-296: straż przełączenia bazy pyta o widoki dopiero przy otwartej bazie - pierwsze `open_path`
    okna bez bazy, konstruktor z bazą i zamknięcie okna bez bazy idą bez wyjątku; przełączenie bez biegu
    działa. Falsyfikator: predykat bez strażnika braku bazy."""
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    for p in (a, b):
        db.open_db(p).close()
    pusty = MainWindow()
    assert pusty.close() is True
    win = MainWindow()
    try:
        win.open_path(a)
        assert win.db_path == a and win.con is not None
        win.open_path(b)
        assert win.db_path == b
    finally:
        win.close()
    win2 = MainWindow(a)
    try:
        assert win2.con is not None
    finally:
        win2.close()


def _main_okno(monkeypatch, argv):
    from horreum.gui import app as app_mod
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    przed = set(QApplication.topLevelWidgets())
    assert app_mod.main(argv) == 0
    okna = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w not in przed]
    assert len(okna) == 1, okna
    return okna[0]


@pytest.mark.zmienia_motyw
def test_main_z_argumentem_otwiera_baze_bez_widokow_przed(qapp, tmp_path, monkeypatch):
    """AR-296: `main` z bazą w argumencie - okno bez bazy, potem `open_path` (straż zapisu nie dotyka
    nieutworzonych widoków)."""
    a = str(tmp_path / "arg.db")
    db.open_db(a).close()
    win = _main_okno(monkeypatch, [a])
    try:
        assert win.db_path == a and win.con is not None
    finally:
        win.close()


@pytest.mark.zmienia_motyw
def test_main_z_ostatnia_baza_z_ustawien(qapp, tmp_path, monkeypatch):
    """AR-296: `main` bez argumentu - ostatnia baza z ustawień (izolowane `QSettings`), ta sama droga."""
    from PySide6.QtCore import QSettings
    a = str(tmp_path / "ostatnia.db")
    db.open_db(a).close()
    QSettings("Horreum", "Horreum").setValue("ostatnia_baza", a)
    win = _main_okno(monkeypatch, [])
    try:
        assert win.db_path == a and win.con is not None
    finally:
        win.close()


@pytest.mark.parametrize("gdzie", ["porzadki", "dom"])
def test_recepta_odlozona_przez_etap_dostawy_stoi_po_odswiezeniu_widokow(qapp, tmp_path, bez_watkow, monkeypatch,
                                                                         gdzie):
    """AR-296: klik recepty „Cofnij zapis (commit N)” w biegu PRAWDZIWEGO etapu Dostawy (rozwiązywanie z bramą)
    odmawia; koniec przebiegu podaje receptę ponownie DOPIERO po odświeżeniu widoków, więc raporty osi
    z odświeżenia („Brak teleskopów na osi…”) jej nie przykrywają - ani przy widocznych Porządkach, ani przy
    powrocie do nich z innego miejsca (raport osi odłożony do Porządków jest starszy od zdania recepty).
    Recepta przeżywa też koniec okna priorytetu raportu gestu. Falsyfikatory: `set_busy(False)` osi obiektu
    przed `_odswiez_widoki_po_przebiegu`; zdanie recepty bez zdjęcia odłożonego raportu Porządków."""
    from horreum import derive
    win, path, pliki = _okno_naprawy(tmp_path)
    ov = win.object_view
    puszczona = threading.Event()
    prawdziwy = derive.DERIVED["resolve"]

    def _czeka(con, now, cancel):
        puszczona.wait(30)
        return prawdziwy(con, now, cancel)
    monkeypatch.setitem(derive.DERIVED, "resolve", _czeka)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        po = _bajty(pliki)
        assert win.pipeline_view.run_stage("resolve") is None
        _czekaj(lambda: ov._busy, "etap w biegu")
        win._show_view(NAV_PORZADKI)
        stan = win._recepta_porzadkow_stan
        assert stan is not None, "brak recepty cofnięcia - test nie mierzy odmowy"
        stan[0].czlony[0].wykonaj()
        assert win._pelny_komunikat == i18n.t("wb.undo_recipe_busy", id=commit)
        if gdzie == "dom":
            win._show_view(NAV_DOM)
        puszczona.set()
        _czekaj(lambda: not ov._busy and win.pipeline_view._thread is None, "koniec przebiegu")
        for _ in range(20):
            QApplication.processEvents()
        if gdzie == "dom":
            win._show_view(NAV_PORZADKI)
        gotowe = i18n.t("wb.undo_recipe_ready", id=commit)
        assert str(win._pelny_komunikat) == gotowe, win._pelny_komunikat
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
        win._wypusc_raport_etapu()
        assert str(win._pelny_komunikat) == gotowe and win.recipe_label.isVisible()
        assert _bajty(pliki) == po, "odmowa ruszyła pliki"
    finally:
        puszczona.set()
        win.close()


# ============================================================ AR-318 - droga powrotu ze STANU; AR-310 - odłożenia osi


def _wiersz_zadania(win, klucz):
    lista = win.tasks_view.tasks
    return next(lista.item(i) for i in range(lista.count()) if lista.item(i).data(Qt.UserRole) == klucz)


def _liczba_wiersza(win, klucz):
    from horreum.gui import rows as rows_mod
    return _wiersz_zadania(win, klucz).data(rows_mod.SECONDARY)


def _klik_wiersza(win, klucz):
    """Prawdziwy klik myszą w wiersz listy zadań (widok listy Porządków)."""
    lista = win.tasks_view.tasks
    win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_LIST)
    QApplication.processEvents()
    wiersz = _wiersz_zadania(win, klucz)
    lista.scrollToItem(wiersz)
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, pos=lista.visualItemRect(wiersz).center())
    QApplication.processEvents()


def _do_listy_i_liczniki(win, klucz, liczba):
    win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_LIST)
    win.tasks_view.refresh_counts()
    _czekaj(lambda: _liczba_wiersza(win, klucz) == liczba,
            f"wiersz {klucz} = {liczba!r}, jest {_liczba_wiersza(win, klucz)!r}")


def _cofnij_czesc(path, commit, n_plikow=1):
    """Cofnięcie przerwane po `n_plikow` plikach drugim połączeniem (poprzednia sesja, awaria)."""
    pytania = []
    con = db.connect(str(path))
    try:
        writeback.undo(con, commit, now=NOW,
                       should_cancel=lambda: (pytania.append(1), len(pytania) > n_plikow)[1])
    finally:
        con.close()


def _brama_dostawy(monkeypatch):
    """Etap „Rozwiąż” PRAWDZIWY, wstrzymany bramą do `puszczona.set()` (wzór testu wyżej)."""
    from horreum import derive
    puszczona = threading.Event()
    prawdziwy = derive.DERIVED["resolve"]

    def _czeka(con, now, cancel):
        puszczona.wait(30)
        return prawdziwy(con, now, cancel)
    monkeypatch.setitem(derive.DERIVED, "resolve", _czeka)
    return puszczona


def _etap_start(win):
    assert win.pipeline_view.run_stage("resolve") is None
    _czekaj(lambda: win.object_view._busy, "etap w biegu")


def _etap_koniec(win, puszczona):
    puszczona.set()
    _czekaj(lambda: not win.object_view._busy and win.pipeline_view._thread is None, "koniec przebiegu")
    for _ in range(20):
        QApplication.processEvents()


def _okno(path):
    win = MainWindow(str(path))
    win.resize(1400, 900)
    win.show()
    win._show_view(NAV_PORZADKI)
    QApplication.processEvents()
    return win


def test_zamkniecie_w_biegu_cofniecia_mowi_pliki_nietkniete_a_wiersz_dokancza_po_restarcie(
        qapp, tmp_path, bez_watkow, brama):
    """AR-318: zamknięcie okna w biegu cofnięcia z paska (prawdziwy uchwyt, anulowanie po pliku 1 z 3) -
    zdanie mówi fakt rdzenia: 2 pliki nietknięte zostają w stanie po zapisie, a „Cofnij zapis (commit N)”
    dokończy; drugie zamknięcie zamyka program. Nowe okno na tej bazie: wiersz „Niedokończone cofnięcia
    zapisu kart” = 1, prawdziwy klik w wiersz stawia receptę „Dokończ cofnięcie (commit N)” z liczbą plików,
    klik recepty dokańcza (bajty jak przed zapisem), „← Porządki” - wiersz 0. Falsyfikatory: ogon bez gałęzi
    nietkniętych (zdanie „wymaga sprawdzenia”); wiersz bez recepty po kliku."""
    from PySide6.QtWidgets import QPushButton
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    # Granica śladu cofnięcia (`writeback._granica_sladu`) to chwila migracji tej bazy z dokładnością do
    # sekundy, a commit z TEJ SAMEJ sekundy rdzeń liczy ostrożnie („wymaga sprawdzenia”, AR-320). Baza testu
    # zmigrowana wcześniej - zdanie nietkniętych nie zależy od tego, czy test zmieścił się w jednej sekundzie.
    con = db.connect(str(path))
    con.execute("UPDATE migration_log SET applied_at = '2000-01-01T00:00:00Z' WHERE version = 47")
    con.commit()
    con.close()
    przed = _bajty(pliki)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        brama.wlaczona = True
        _klik_recepty(win)
        _czekaj(brama.doszlo.is_set, "pierwszy plik cofnięcia")
        assert win.close() is False
        brama.puszczona.set()
        _czekaj_na_cofniecie(win)
        tekst = str(win._pelny_komunikat)
        assert (i18n.t_plural("wb.undo_cancelled_untouched", 2)
                + i18n.t("wb.undo_cancelled_finish", undo=i18n.t("wb.undo_recipe", id=commit))) in tekst, tekst
        assert i18n.t_plural("wb.undo_cancelled_check", 2, undo=i18n.t("wb.undo_recipe", id=commit)) not in tekst
    finally:
        brama.puszczona.set()
        assert win.close() is True
    brama.wlaczona = False
    win = _okno(path)
    try:
        _do_listy_i_liczniki(win, "undo_unfinished", "1  ›")
        _klik_wiersza(win, "undo_unfinished")
        assert win.tasks_view.pages.currentIndex() == tasks_mod._PAGE_OBJECTS
        dokoncz = i18n.t("wb.undo_finish_recipe", id=commit)
        assert str(win._pelny_komunikat) == i18n.t_plural("wb.undo_unfinished", 2, id=commit, finish=dokoncz)
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == dokoncz
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert _bajty(pliki) == przed
        powrot = next(b for b in win.tasks_view.pages.currentWidget().findChildren(QPushButton)
                      if b.text() == i18n.t("tasks.back"))
        QTest.mouseClick(powrot, Qt.LeftButton)
        _czekaj(lambda: _liczba_wiersza(win, "undo_unfinished") == "0  ›", "wiersz gaśnie")
    finally:
        win.close()


def test_dokonczenie_z_wiersza_w_biegu_dostawy_odmawia_i_wraca(qapp, tmp_path, bez_watkow, monkeypatch):
    """AR-318 + AR-310: recepta „Dokończ cofnięcie” z wiersza Porządków wykonana w biegu PRAWDZIWEGO etapu
    Dostawy odmawia zdaniem (pliki bez zmian), a po końcu etapu wraca z TĄ SAMĄ etykietą i dokańcza.
    Falsyfikator: odłożenie odbudowuje receptę z etykietą „Cofnij zapis (commit N)”."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    przed = _bajty(pliki)
    puszczona = _brama_dostawy(monkeypatch)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        _cofnij_czesc(path, commit)
        po = _bajty(pliki)
        _do_listy_i_liczniki(win, "undo_unfinished", "1  ›")
        _klik_wiersza(win, "undo_unfinished")
        _etap_start(win)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_busy", id=commit)
        assert _bajty(pliki) == po, "odmowa ruszyła pliki"
        _etap_koniec(win, puszczona)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_ready", id=commit)
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_finish_recipe", id=commit)
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert _bajty(pliki) == przed
    finally:
        puszczona.set()
        win.close()


_TRZYMAJ_BLOKADE = r'''
import os, sys, time
from PySide6.QtCore import QLockFile
blokada = QLockFile(sys.argv[1])
blokada.setStaleLockTime(0)
assert blokada.tryLock(10000)
with open(sys.argv[2], "w") as fh:
    fh.write(str(os.getpid()))
koniec = time.monotonic() + 60
while not os.path.exists(sys.argv[3]) and time.monotonic() < koniec:
    time.sleep(0.02)
blokada.unlock()
'''


def test_dokonczenie_odmawia_gdy_baze_trzyma_inne_okno(qapp, tmp_path, bez_watkow):
    """AR-318: dokończenie podejmuje stan poprzedniej sesji, więc korzysta z wyłączności szuflady bazy -
    drugi PROCES trzyma `<baza>.szuflada.lock`: recepta odmawia zdaniem z jego PID-em, pliki bez zmian,
    recepta zostaje; koniec tamtego procesu - klik dokańcza. Falsyfikator: dokończenie bez sprawdzenia
    blokady (pliki cofnięte mimo obcego właściciela)."""
    win, path, pliki = _okno_naprawy(tmp_path, n=3)
    przed = _bajty(pliki)
    skrypt, gotowe, zwolnij = tmp_path / "trzymaj.py", tmp_path / "gotowe", tmp_path / "zwolnij"
    skrypt.write_text(_TRZYMAJ_BLOKADE, encoding="utf-8")
    proces = None
    try:
        commit = _naprawa_prawdziwym_exec(win)
        _cofnij_czesc(path, commit)
        po = _bajty(pliki)
        proces = subprocess.Popen([sys.executable, str(skrypt), str(path) + ".szuflada.lock",
                                   str(gotowe), str(zwolnij)])
        _czekaj(lambda: gotowe.exists() and gotowe.read_text(encoding="utf-8"), "blokada drugiego procesu")
        pid = int(gotowe.read_text(encoding="utf-8"))      # interpreter, nie wyrzutnia `venv`
        _do_listy_i_liczniki(win, "undo_unfinished", "1  ›")
        _klik_wiersza(win, "undo_unfinished")
        _klik_recepty(win)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_finish_foreign_owner", id=commit,
                                                   pid=pid), win._pelny_komunikat
        assert _bajty(pliki) == po
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_finish_recipe", id=commit)
        zwolnij.write_text("", encoding="utf-8")
        proces.wait(timeout=30)
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert _bajty(pliki) == przed
    finally:
        zwolnij.write_text("", encoding="utf-8")
        if proces is not None:
            try:
                proces.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proces.kill()
        win.close()


def _okno_naprawy_z_kamera(tmp_path, n=2):
    """`_okno_naprawy` z klatkami, które mają kamerę (`INSTRUME`) i zestaw po grouperze - na nich
    „Dopisz nowy…” (`repo.user_assign_config_new_telescope`) przypisuje teleskop."""
    from astropy.io import fits
    from horreum import grouper
    path = tmp_path / "naprawa.db"
    con = db.open_db(str(path))
    pliki = _nameless_tree(tmp_path, names=tuple(f"NGC7635_20230103_{chr(97 + i)}.fits" for i in range(n)))
    for p in pliki:
        fits.setval(str(p), "INSTRUME", value="ZWO ASI2600MC Pro")
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD, summary=scan.ScanSummary())
    grouper.run_grouper(con, NOW_PD)
    con.close()
    win = _okno(path)
    win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_OBJECTS)
    win.object_view.refresh()
    QApplication.processEvents()
    return win, path, pliki


def test_dwie_recepty_osi_odlozone_naraz_podane_po_kolei(qapp, tmp_path, bez_watkow, monkeypatch):
    """AR-310: recepta cofnięcia zapisu kart i recepta „Cofnij dopisanie” odmówione w tym samym etapie
    Dostawy (prawdziwy etap) - kolejka FIFO: po końcu etapu wraca STARSZA (karty); jej klik cofa zapis, a
    wynik i gotowość drugiej idą jednym zdaniem z receptą dopisania; jej klik zdejmuje teleskop.
    Falsyfikatory: jedno miejsce odłożenia (nowsza wypiera starszą - po etapie stoi dopisanie); brak
    przekazania po końcu gestu (druga recepta nie wraca)."""
    win, path, pliki = _okno_naprawy_z_kamera(tmp_path)
    przed = _bajty(pliki)
    ov = win.object_view
    puszczona = _brama_dostawy(monkeypatch)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        karty = win._recepta_porzadkow_stan[0]
        fids = [r[0] for r in win.con.execute("SELECT id FROM frame ORDER BY id")]
        tid, _g = repo.user_assign_config_new_telescope(win.con, frame_ids=fids, name="RC8 0.5x",
                                                         focal_mm=800.0, now=NOW)
        dopisanie = ov._recepta_cofniecia_dopisania(tid, "RC8 0.5x")
        _etap_start(win)
        karty.czlony[0].wykonaj()
        dopisanie.czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.deferred", telescope="RC8 0.5x")
        _etap_koniec(win, puszczona)
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_ready", id=commit)
        assert win.recipe_label.toolTip() == i18n.t("wb.undo_recipe", id=commit)
        _klik_recepty(win)
        _czekaj_na_cofniecie(win)
        assert _bajty(pliki) == przed
        tekst = str(win._pelny_komunikat)
        assert tekst.endswith(" - " + i18n.t("object.config_undo_add.ready", telescope="RC8 0.5x")), tekst
        assert tekst.startswith(i18n.t_plural("grid.wb.restored", 2)), tekst
        assert win.recipe_label.toolTip() == i18n.t("object.config_undo_add", telescope="RC8 0.5x")
        _klik_recepty(win)
        assert win.con.execute("SELECT retired_at FROM telescope WHERE id = ?", (tid,)).fetchone()[0]
    finally:
        puszczona.set()
        win.close()


@pytest.mark.parametrize("gdzie", ["porzadki", "dom"])
def test_cofnij_dopisanie_odlozone_przez_etap_dostawy_wraca_po_odswiezeniu(qapp, tmp_path, bez_watkow,
                                                                          monkeypatch, gdzie):
    """AR-310: recepta „Cofnij dopisanie” stoi na pasku Porządków; wykonana w biegu PRAWDZIWEGO etapu Dostawy
    odmawia zdaniem odroczenia (teleskop żyje); koniec przebiegu podaje ją ponownie DOPIERO po odświeżeniu
    widoków - przy widocznych Porządkach i po powrocie do nich z Domu zdanie gotowości i recepta stoją, także
    po końcu okna priorytetu raportu etapu; prawdziwy klik zdejmuje teleskop. Falsyfikatory: odmowa
    z natychmiastową receptą (raport odświeżenia ją gasi); podanie przed odświeżeniem widoków."""
    win, path, pliki = _okno_naprawy_z_kamera(tmp_path)
    ov = win.object_view
    puszczona = _brama_dostawy(monkeypatch)
    try:
        fids = [r[0] for r in win.con.execute("SELECT id FROM frame ORDER BY id")]
        tid, _g = repo.user_assign_config_new_telescope(win.con, frame_ids=fids, name="RC8 0.5x",
                                                         focal_mm=800.0, now=NOW)
        ov.status_message.emit("dopisano")
        ov.status_recipe.emit(ov._recepta_cofniecia_dopisania(tid, "RC8 0.5x"))
        etykieta = i18n.t("object.config_undo_add", telescope="RC8 0.5x")
        assert win.recipe_label.toolTip() == etykieta
        _etap_start(win)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert str(win._pelny_komunikat) == i18n.t("object.config_undo_add.deferred", telescope="RC8 0.5x")
        assert win.con.execute("SELECT retired_at FROM telescope WHERE id = ?", (tid,)).fetchone()[0] is None
        if gdzie == "dom":
            win._show_view(NAV_DOM)
        _etap_koniec(win, puszczona)
        if gdzie == "dom":
            win._show_view(NAV_PORZADKI)
        gotowe = i18n.t("object.config_undo_add.ready", telescope="RC8 0.5x")
        assert str(win._pelny_komunikat) == gotowe, win._pelny_komunikat
        assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == etykieta
        win._wypusc_raport_etapu()
        assert str(win._pelny_komunikat) == gotowe and win.recipe_label.isVisible()
        _klik_recepty(win)
        assert win.con.execute("SELECT retired_at FROM telescope WHERE id = ?", (tid,)).fetchone()[0]
    finally:
        puszczona.set()
        win.close()


def test_odlozona_recepta_nie_przechodzi_na_inna_baze_i_wraca_z_powrotem(qapp, tmp_path, bez_watkow,
                                                                          monkeypatch):
    """AR-310, AR-321: odłożenie należy do okna i TEJ bazy - zdanie mówi „także po powrocie do tej bazy, dopóki
    program jest otwarty”. Przełączenie bazy w biegu etapu: po końcu etapu na pasku nowej bazy nie ma zdania
    gotowości starego wpisu ani recepty, wyjątku na zamkniętym połączeniu też nie ma; powrót do pierwszej bazy
    podaje zdanie gotowości. Falsyfikatory: kolejka wspólna dla baz (stara recepta na pasku nowej bazy);
    kolejka w widoku (powrót bez recepty)."""
    druga = tmp_path / "druga.db"
    db.open_db(str(druga)).close()
    win, path, pliki = _okno_naprawy(tmp_path)
    puszczona = _brama_dostawy(monkeypatch)
    try:
        commit = _naprawa_prawdziwym_exec(win)
        _etap_start(win)
        win._recepta_porzadkow_stan[0].czlony[0].wykonaj()
        assert "także po powrocie do tej bazy, dopóki program jest otwarty" in i18n.CATALOG[
            "wb.undo_recipe_busy"]["pl"]
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_busy", id=commit)
        win._open_path(str(druga))
        assert win.db_path == str(druga)
        puszczona.set()
        _czekaj(lambda: win.pipeline_view._thread is None, "koniec przebiegu starej bazy")
        for _ in range(20):
            QApplication.processEvents()
        assert str(win._pelny_komunikat) != i18n.t("wb.undo_recipe_ready", id=commit)
        assert win._recepta_porzadkow_stan is None and not win.recipe_label.isVisible()
        win._open_path(str(path))
        assert str(win._pelny_komunikat) == i18n.t("wb.undo_recipe_ready", id=commit)
        assert win._recepta_porzadkow_stan is not None
    finally:
        puszczona.set()
        win.close()


def test_os_obiektu_leniwie_czyta_baze_przy_pierwszym_pokazaniu(qapp, tmp_path):
    """Kontrakt montażu w tle (AR-175): `ObjectAxisView(..., leniwie=True)` nie czyta kolejki w konstruktorze
    (znacznik `_nieaktualny`), a czyta ją przy pierwszym pokazaniu; domyślnie (widok samodzielny, okna
    osi, testy) czyta od razu. Falsyfikatory: domyślne `leniwie=True` (pusta kolejka samodzielnego widoku);
    leniwie bez znacznika (pokazanie nie czyta)."""
    from horreum.gui.app import ObjectAxisView
    con = db.open_db(str(tmp_path / "l.db"))
    for p in _nameless_tree(tmp_path):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD, summary=scan.ScanSummary())
    od_razu = ObjectAxisView(con)
    assert od_razu.review.count() > 0 and not od_razu._nieaktualny
    leniwy = ObjectAxisView(con, leniwie=True)
    assert leniwy.review.count() == 0 and leniwy._nieaktualny
    leniwy.show()
    _czekaj(lambda: leniwy.review.count() == od_razu.review.count(), "odczyt przy pokazaniu")
    assert not leniwy._nieaktualny
    leniwy.close()
    od_razu.close()
    con.close()
