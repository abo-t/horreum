"""Drogi wyjścia z izolacji zapisu w miejscu na powierzchniach GUI (warunki wsadu AR-17 (1)(2))
i recepty wierszy kopii bez zeznania (AR-28).

Kopia z operacją `inplace_op` w fazie izolującej jest pomijana przez skan. Rdzeń ma trzy drogi
wyjścia (`writeback.finish_inplace`, `writeback.recover_torn`, `repo.release_inplace_op`); tu
sprawdzamy, że GUI je pokazuje: wiersz Porządków „Zapis czeka na dokończenie" z własną
perspektywą, gesty w menu prawego kliku w Zbiorach (uczciwie wygaszone z powodem), zdanie wyniku
z powodem rdzenia i odświeżenie licznika tym samym sygnałem, co po innych gestach.

Operacje budowane PRAWDZIWĄ drogą pisarza na syntetycznym FITS w `tmp_path`: commit w miejscu,
którego re-sync pada (czkawka odczytu) → faza `written`; commit, którego `fsync` pada po zapisie
→ faza `unverified`. Okno offscreen, wykonawca zapisu inline (`_writeback_async = False`)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from astropy.io import fits
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from horreum import db, repo, scan, writeback
from horreum.gui import grid as grid_mod, i18n, queries, rows, tasks as tasks_mod
from horreum.gui.i18n_catalog import CATALOG

NOW = "2026-09-29T10:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _fits(path, *, seed=0):
    """FITS z kartą OBJECT (komentarz jak u NINA) i danymi zależnymi od `seed` (tożsamość klatki)."""
    hdu = fits.PrimaryHDU(data=(np.arange(64, dtype=np.int16).reshape(8, 8) + seed).astype(np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = ("NGC6992", "Name of the object of interest")
    hdu.writeto(path, overwrite=True)
    return path


def _baza(tmp_path, n=1, *, do_zapisu=None):
    """Baza z `n` plikami wciągniętymi skanem i wpisem stagingu `OBJECT` (run `R`) na kopiach
    o indeksach `do_zapisu` (domyślnie wszystkich)."""
    kat = tmp_path / "arch"
    kat.mkdir()
    con = db.open_db(str(tmp_path / "h.db"))
    pliki = []
    for i in range(n):
        p = _fits(kat / f"a{i}.fits", seed=i)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
        loc = con.execute("SELECT id, header_hash, frame_id FROM location WHERE path = ?",
                          (str(p),)).fetchone()
        if do_zapisu is None or i in do_zapisu:
            repo.stage_pending(con, run_id="R", location_id=loc["id"], keyword="OBJECT", idx=0,
                               op="set", old_value=None, new_value="NGC 6992", new_type="str",
                               new_comment=None, expected_header_hash=loc["header_hash"])
        pliki.append((p, loc["frame_id"]))
    return con, pliki


def _commit_written(monkeypatch, con):
    """Commit w miejscu, którego re-sync pada - operacje zostają `written` (plik z nowym nagłówkiem)."""
    with monkeypatch.context() as m:
        m.setattr(writeback.scan, "scan_file",
                  lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
        writeback.commit(con, "R", now=NOW, inplace=True)


def _commit_przerwany(monkeypatch, con):
    """Commit w miejscu, którego `fsync` pada PO zapisie - operacje zostają `unverified` (otwarte)."""
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        raise OSError(64, "The specified network name is no longer available")
    with monkeypatch.context() as m:
        m.setattr(writeback.os, "fsync", _fsync)
        writeback.commit(con, "R", now=NOW, inplace=True)


def _fazy(con):
    return [r["phase"] for r in con.execute("SELECT phase FROM inplace_op ORDER BY id")]


def _widok(con):
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    v.komunikaty, v.recepty, v.zajety, v.porzadki = [], [], [], []
    v.status_message.connect(v.komunikaty.append)
    v.status_recipe.connect(v.recepty.append)
    v.writeback_busy.connect(v.zajety.append)
    v.stan_porzadkow_changed.connect(lambda: v.porzadki.append(True))
    return v


def _zaznacz(view, frame_ids):
    from PySide6.QtCore import QItemSelectionModel
    sm = view.table.selectionModel()
    sm.clearSelection()
    for i, row in enumerate(view.model._rows):
        if isinstance(row, dict) and row.get("frame_id") in set(frame_ids):
            sm.select(view.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def _wiersz(tv, klucz):
    return next(tv.tasks.item(i) for i in range(tv.tasks.count())
                if tv.tasks.item(i).data(Qt.UserRole) == klucz)


def _menu(view):
    """Menu tabeli nad bieżącym zaznaczeniem (punkt poza wierszami - zaznaczenie zostaje)."""
    view._on_table_menu(QPoint(-50, -50))
    return view._menu_tabeli


# ═════════════════════════ AR-17 (1): wiersz „Zapis czeka na dokończenie"


def test_predykat_i_wiersz_zapisu_czekajacego_na_dokonczenie(qapp, tmp_path, monkeypatch):
    """Operacja `written` (re-sync padł) była dla GUI niewidoczna: `torn_write_frame_ids` widzi tylko
    fazy otwarte, a skan pomija izolowaną kopię. Teraz liczy ją osobny predykat i osobny wiersz, który
    JEST robotą (plakietka, pogrubienie), z podpowiedzią, gdzie szukać gestu.

    Falsyfikator: podmień fazy predykatu na `INPLACE_OPEN_PHASES` → pierwsza asercja widzi pusty
    zbiór; wyjmij wiersz z `_TASKS` → `_wiersz` nie znajdzie klucza."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    assert _fazy(con) == ["written"]
    assert queries.pending_finish_frame_ids(con) == {fid}
    assert queries.torn_write_frame_ids(con) == set(), "przerwany zapis to inny wiersz"
    assert queries.tasks_state(con)["pending_finish_frames"] == 1
    tv = tasks_mod.TasksView(con)
    try:
        przed = tv.refresh_counts()
        w = _wiersz(tv, "pending_finish_frames")
        assert w.text() == "Zapis czeka na dokończenie"
        assert w.data(rows.SECONDARY) == "1  ›" and w.data(rows.STRONG) is True
        assert f"„{i18n.t('grid.inplace.finish')}”" in w.toolTip(), w.toolTip()
        assert przed >= 1
        cele = []
        tv.open_collection.connect(cele.append)
        tv._on_task_clicked(w)
        assert cele == [grid_mod.PRESET_PENDING_FINISH]
    finally:
        tv.close()
    con.close()


def test_perspektywa_zapisu_czekajacego_pokazuje_klatke_i_recepte(qapp, tmp_path, monkeypatch):
    """Klik w wiersz prowadzi do perspektywy z tymi samymi klatkami, co liczba, a wejście w nią
    podaje receptę gestu (gest mieszka w menu prawego kliku, którego nie widać).

    Falsyfikator: zdejmij emisję recepty w `_on_perspective` → ostatnia asercja pada."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        assert view._frame_ids == [fid]
        assert i18n.t("grid.criteria.only_pending_finish") in view.sel_bar.criteria_label.toolTip()
        assert view.recepty and i18n.t("grid.inplace.finish") in view.recepty[-1], view.recepty
    finally:
        view.close()
    con.close()


# ═════════════════════════ AR-17 (2): gesty w menu tabeli


def test_dokoncz_zapis_zmienia_faze_odswieza_licznik_i_dziedziczy_mutex(qapp, tmp_path, monkeypatch):
    """„Dokończ zapis" na klatce z operacją `written`: faza `synced`, kopia wraca do skanu, klatka
    wychodzi z perspektywy (to jest skutek gestu), zdanie na pasku, sygnał stanu Porządków →
    licznik 0. Gest idzie uchwytem zapisu gridu, więc emituje `writeback_busy` True → False - ten
    sam fakt, który gospodarz przekazuje Dostawie (mutex „writeback → Dostawa").

    Falsyfikator: wołaj `writeback.finish_inplace` w slocie wprost, z pominięciem `_start_writeback`
    → asercja o `zajety` pada; zdejmij `stan_porzadkow_changed` z ogona → licznik zostaje 1."""
    con, [(p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    tv = tasks_mod.TasksView(con)
    view.stan_porzadkow_changed.connect(tv.refresh_counts)
    try:
        tv.refresh_counts()
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        menu = _menu(view)
        try:
            assert view.act_finish_write.isVisible() and view.act_finish_write.isEnabled()
            assert view.act_finish_write.toolTip().startswith("Dokończy 1 zapis")
            assert view.act_restore_header.isEnabled() and view.act_release_file.isEnabled()
            assert not view.act_keep_version.isVisible(), "gest wersji tylko w swojej perspektywie"
        finally:
            menu.hide()
        view._on_finish_write()
        assert _fazy(con) == ["synced"] and not scan._isolated(con, str(p))
        assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["applied"]
        assert view.zajety == [True, False]
        assert view.porzadki, "gest ma ruszyć plakietkę Porządków"
        assert _wiersz(tv, "pending_finish_frames").data(rows.SECONDARY) == "0  ›"
        assert view._frame_ids == [], "udany gest wypycha klatkę z perspektywy"
        assert view.komunikaty[-1].startswith("Dokończono 1 zapis"), view.komunikaty[-1]
    finally:
        tv.close()
        view.close()
    con.close()


def test_przywroc_naglowek_po_przerwanym_zapisie(qapp, tmp_path, monkeypatch):
    """Operacja otwarta (`unverified`): „Przywróć nagłówek sprzed zapisu" wraca stary region
    w miejscu - plik bajt w bajt jak przed commitem, faza `recovered`, wiersz „Plik po przerwanym
    zapisie" gaśnie. „Dokończ" jest przy niej wygaszony z powodem, który wskazuje właściwy gest.

    Falsyfikator: zapal „Dokończ" przy każdej fazie izolującej → asercja o `isEnabled` pada."""
    con, [(p, fid)] = _baza(tmp_path)
    przed = p.read_bytes()
    _commit_przerwany(monkeypatch, con)
    assert _fazy(con) == ["unverified"] and queries.torn_write_frame_ids(con) == {fid}
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_TORN_WRITE)
        assert view.recepty and i18n.t("grid.inplace.restore") in view.recepty[-1]
        _zaznacz(view, [fid])
        menu = _menu(view)
        try:
            assert not view.act_finish_write.isEnabled()
            assert view.act_finish_write.toolTip() == i18n.t(
                "grid.inplace.finish_open_only", restore=i18n.t("grid.inplace.restore"))
            assert view.act_restore_header.isEnabled()
        finally:
            menu.hide()
        view._on_finish_write()                        # bramka slotu - druga linia za wygaszeniem
        assert _fazy(con) == ["unverified"] and view.zajety == []
        view._on_restore_header()
        assert _fazy(con) == ["recovered"] and p.read_bytes() == przed
        assert queries.torn_write_frame_ids(con) == set() and not scan._isolated(con, str(p))
        assert view.komunikaty[-1].startswith("Przywrócono nagłówek w 1 pliku"), view.komunikaty
    finally:
        view.close()
    con.close()


def test_przywroc_przy_poprawnym_zapisie_odmawia_i_mowi_powod_rdzenia(qapp, tmp_path, monkeypatch):
    """Zapis `written` z udaną kontrolą danych (re-sync padł tylko na czkawce): powrót go NIE cofa -
    rdzeń odmawia z drogą do dokończenia. Powód rdzenia jedzie na pasek dosłownie, z nazwą pliku;
    zdanie bez niego zostawiałoby „zablokowany 1" bez odpowiedzi „czemu". Powód porównujemy
    z odpowiedzią rdzenia na to samo pytanie (odmowa niczego nie zmienia, więc drugie wywołanie
    mówi to samo) - test nie pinuje brzmienia rdzenia, tylko to, że GUI go nie gubi.

    Falsyfikator: zdejmij człon `grid.inplace.detail` z `_zdanie_gestu_zapisu` → asercja o powodzie
    pada."""
    con, [(p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    po_zapisie = p.read_bytes()
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        menu = _menu(view)
        try:
            assert i18n.t("grid.inplace.finish") in view.act_restore_header.toolTip(), \
                "podpowiedź powrotu mówi z góry, że poprawny zapis się dokańcza"
        finally:
            menu.hide()
        view._on_restore_header()
        assert _fazy(con) == ["written"] and p.read_bytes() == po_zapisie
        zdanie = view.komunikaty[-1]
        op_id = con.execute("SELECT id FROM inplace_op").fetchone()[0]
        rdzen = writeback.recover_torn(con, op_id, now=NOW)
        assert rdzen.status == "blocked" and rdzen.reason
        assert "zablokowany 1" in zdanie and f"a0.fits: {rdzen.reason}" in zdanie, zdanie
    finally:
        view.close()
    con.close()


def test_zwolnij_wymaga_powodu_i_zostawia_go_w_dzienniku(qapp, tmp_path, monkeypatch):
    """„Zwolnij plik do skanu…": okno bez powodu ma wygaszony przycisk (to rozstrzygnięcie człowieka),
    Enter nie przechodzi obok bramki, a powód trafia do zdarzenia `location.writeback_released`.
    Plik nietknięty, faza `released`, licznik 0.

    Falsyfikator: zdejmij `_sync_ok` z okna → asercja o wygaszeniu pada; wołaj
    `release_inplace_op` z pustym powodem → asercja o treści zdarzenia pada."""
    dlg = grid_mod.ReleaseDialog(2)
    try:
        assert not dlg.btn_ok.isEnabled() and dlg.btn_ok.toolTip()
        dlg.edit.setText("   ")
        assert not dlg.btn_ok.isEnabled(), "same spacje to nie powód"
        dlg.accept()
        assert dlg.result() != QDialog.Accepted, "accept bez powodu nie przechodzi"
        dlg.edit.setText("przywrócony z pełnej kopii")
        assert dlg.btn_ok.isEnabled() and not dlg.btn_ok.toolTip()
    finally:
        dlg.close()

    con, [(p, fid)] = _baza(tmp_path)
    _commit_przerwany(monkeypatch, con)
    przed = p.read_bytes()

    def _exec(self):
        self.edit.setText("  sprawdzony hashem z kopią  ")
        return QDialog.Accepted
    monkeypatch.setattr(grid_mod.ReleaseDialog, "exec", _exec)
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_TORN_WRITE)
        _zaznacz(view, [fid])
        view._on_release_file()
        assert _fazy(con) == ["released"] and p.read_bytes() == przed
        ev = con.execute("SELECT reason FROM event WHERE verb = 'location.writeback_released'"
                         ).fetchone()
        assert ev["reason"] == "sprawdzony hashem z kopią"
        assert queries.tasks_state(con)["torn_write_frames"] == 0 and view.porzadki
        assert view.komunikaty[-1].startswith("Zwolniono do skanu 1 plik"), view.komunikaty
        assert view.zajety == [], "zwolnienie jest samą bazą - bez wątku zapisu"
    finally:
        view.close()
    con.close()


def test_menu_poza_perspektywa_tylko_nad_klatka_izolowana(qapp, tmp_path, monkeypatch):
    """Poza perspektywami zapisu prawy klik na zwykłej klatce zostaje niczym (i nie przestawia
    zaznaczenia), a na klatce z kopią izolowaną pokazuje gesty - w „Przeglądzie" też da się dokończyć
    zapis. W perspektywie zapisu przy pustym zaznaczeniu gesty są WIDOCZNE i wygaszone z powodem.

    Falsyfikator: zdejmij pytanie o izolację z `_on_table_menu` → menu nie pokaże się nad klatką
    izolowaną w „Przeglądzie" albo pokaże się nad zwykłą."""
    con, [(_p0, izolowana), (_p1, zwykla)] = _baza(tmp_path, n=2, do_zapisu={0})
    _commit_written(monkeypatch, con)
    view = _widok(con)
    view.resize(1200, 700)
    view.show()
    QApplication.processEvents()
    try:
        view.apply_perspective("Przegląd")

        def _punkt(fid):
            r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == fid)
            return view.table.visualRect(view.model.index(r, 0)).center()

        _zaznacz(view, [])
        view._on_table_menu(_punkt(zwykla))
        assert not view._menu_tabeli.isVisible()
        assert view._selected_data_rows() == [], "prawy klik bez menu nie zaznacza"
        view._on_table_menu(_punkt(izolowana))
        try:
            assert view._menu_tabeli.isVisible()
            assert [r["frame_id"] for r in view._selected_data_rows()] == [izolowana]
            assert view.act_finish_write.isEnabled()
        finally:
            view._menu_tabeli.hide()

        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [])
        menu = _menu(view)
        try:
            for act in (view.act_finish_write, view.act_restore_header, view.act_release_file):
                assert act.isVisible() and not act.isEnabled()
                assert act.toolTip() == i18n.t("grid.inplace.none")
        finally:
            menu.hide()
    finally:
        view.close()
    con.close()


def test_gesty_czekaja_na_etap_i_na_inny_zapis(qapp, tmp_path, monkeypatch):
    """W trakcie etapu Dostawy i cudzego zapisu do plików gesty są wygaszone z powodem, a slot
    odmawia zdaniem, bez startu wątku i bez zmiany fazy.

    Falsyfikator: usuń `_powod_zajetosci` z `_start_gestu_zapisu` → faza zmienia się na `synced`."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        for wlacz, wylacz, klucz in ((view.set_busy, view.set_busy, "grid.inplace.busy_stage"),
                                     (view.set_writeback_busy, view.set_writeback_busy,
                                      "grid.inplace.busy_write")):
            wlacz(True)
            _zaznacz(view, [fid])
            menu = _menu(view)
            try:
                assert not view.act_finish_write.isEnabled()
                assert view.act_finish_write.toolTip() == i18n.t(klucz)
            finally:
                menu.hide()
            view._on_finish_write()
            assert _fazy(con) == ["written"] and view.komunikaty[-1] == i18n.t(klucz)
            wylacz(False)
    finally:
        view.close()
    con.close()


def test_zdanie_wyniku_liczy_statusy_i_przerwanie():
    """Czysta funkcja zdania: człon główny liczy sukcesy statusem właściwym gestowi, człony odmów
    stoją tylko, gdy są, a przerwanie mówi, że reszta nietknięta."""
    from types import SimpleNamespace as NS
    wyniki = [NS(status="applied", path="C:\\a\\x.fits", reason=None),
              NS(status="blocked", path="/b/y.fits", reason="inny plik"),
              NS(status="failed", path="z.fits", reason="re-sync padł")]
    zdanie = grid_mod._zdanie_gestu_zapisu("finish_inplace", NS(results=wyniki, cancelled=True))
    assert zdanie == ("Dokończono 1 zapis · zablokowany 1 · nieudany 1 · przerwano, reszta "
                      "nietknięta - y.fits: inny plik")
    assert grid_mod._zdanie_gestu_zapisu(
        "recover_torn", NS(results=[NS(status="restored", path="a", reason="ok")] * 2,
                           cancelled=False)) == "Przywrócono nagłówek w 2 plikach"


# ═════════════════════════ AR-28: recepty wierszy kopii bez zeznania


def _kopie_bez_faktow(tmp_path):
    """Jedna klatka, dwie kopie FITS wciągnięte bez faktów kopii (jak sprzed 0021) - zero wierszy
    porównujących zeznania znaczy wtedy „nie wiem" („?")."""
    kat = tmp_path / "kopie"
    kat.mkdir()
    con = db.open_db(str(tmp_path / "k.db"))
    for nazwa in ("a.fits", "b.fits"):
        rec = scan.scan_file(str(_fits(kat / nazwa)))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path,
                          header_hash=rec.header_hash, now=NOW)
    return con


def test_klik_w_wiersz_niewiadomy_prowadzi_do_Dostawy(qapp, tmp_path):
    """AR-28 (b): w stanie „?" lista pod klikiem była pusta (predykat „nie wie"), a szewron zapraszał.
    Klik prowadzi teraz tam, gdzie jest robota - do Dostawy - a podpowiedź to mówi. Po zebraniu
    faktów wiersz wraca do zwykłej perspektywy.

    Falsyfikator: zdejmij gałąź `_niewiadome` z `_on_task_clicked` → `open_collection` dostaje
    perspektywę, `open_intake` milczy."""
    con = _kopie_bez_faktow(tmp_path)
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        w = _wiersz(tv, "copy_conflict_frames")
        assert w.data(rows.SECONDARY).startswith("? · ")
        assert f"{i18n.t('nav.dostawa')}." in w.toolTip().splitlines()[-1]
        dostawa, perspektywy = [], []
        tv.open_intake.connect(lambda: dostawa.append(True))
        tv.open_collection.connect(perspektywy.append)
        tv._on_task_clicked(w)
        assert dostawa == [True] and perspektywy == []
        scan.backfill_copy_facts(con, now=NOW)
        tv.refresh_counts()
        tv._on_task_clicked(_wiersz(tv, "copy_conflict_frames"))
        assert perspektywy == [grid_mod.PRESET_COPY_CONFLICT] and dostawa == [True]
    finally:
        tv.close()
    con.close()


def test_klik_w_wiersz_niewiadomy_przelacza_okno_na_Dostawe(qapp, tmp_path, monkeypatch):
    """Gospodarz podpina `open_intake` pod przełączenie widoku - droga człowieka od wiersza do ekranu."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PORZADKI, MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    _kopie_bez_faktow(tmp_path).close()
    win = MainWindow(str(tmp_path / "k.db"))
    try:
        win._show_view(NAV_PORZADKI)
        win.tasks_view._on_task_clicked(_wiersz(win.tasks_view, "orphan_testimony_frames"))
        assert win.stack.currentIndex() == NAV_DOSTAWA
    finally:
        win.close()


def test_recepta_kopii_bez_zeznania_ma_wykonalny_dwukrok(qapp):
    """AR-28 (a): druga droga recepty prowadzi przez „Sprawdź obecność" (działa bez wskazanego
    katalogu) do „Oznacz zniknięte" (pojawia się pod wynikiem). Nazwy z katalogu w KAŻDEJ formie
    obu języków - forma bez `{check}` zgubiłaby pierwszy krok dla jednej liczby."""
    for klucz in ("grid.tip.copy_unread", "tasks.copies_unread_tip"):
        for jezyk in ("pl", "en"):
            formy = CATALOG[klucz][jezyk]
            for tekst in (formy.values() if isinstance(formy, dict) else [formy]):
                assert "{check}" in tekst and "{mark}" in tekst, (klucz, jezyk)
                assert tekst.index("{check}") < tekst.index("{mark}"), (klucz, jezyk)
    tip = i18n.t("grid.tip.copy_unread", place=i18n.t("nav.dostawa"),
                 check=i18n.t("pipeline.btn.presence"), mark=i18n.t("pipeline.btn.mark_vanished"))
    assert "Dostawa → „Sprawdź obecność” → „Oznacz zniknięte”" in tip, tip


def _czekaj_na_etap(view, timeout_ms=20000):
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_sprawdz_obecnosc_w_swiezej_sesji_bierze_ostatnie_zrodlo(qapp, tmp_path, ustawienia):
    """AR-28 (a), wariant „Sprawdź obecność działa na ostatnim źródle": w świeżej sesji (katalog
    niewskazany) przycisk był wygaszony, a recepta wskazywała „Oznacz zniknięte", którego na
    ekranie nie ma. Teraz przycisk żyje przy samej bazie, podpowiedź nazywa źródło, a po DRY
    „Oznacz zniknięte" stoi pod wynikiem - cel recepty jest widoczny po jej pierwszym kroku.

    Falsyfikator: przywróć `idle and self._can_scan()` dla `btn_presence` → pierwsza asercja pada;
    zdejmij gałąź ostatniego źródła z `_on_presence` → etap nie rusza (`_thread is None`)."""
    from horreum.gui.pipeline import PipelineView
    kat = tmp_path / "t"
    kat.mkdir()
    for i in range(2):
        _fits(kat / f"l{i}.fits", seed=i + 1)
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    pierwsza = PipelineView(db_path, now_fn=lambda: NOW)
    pierwsza._set_root(str(kat))
    pierwsza._on_scan()
    _czekaj_na_etap(pierwsza)
    pierwsza.close()
    os.remove(str(kat / "l1.fits"))
    ustawienia.setValue("pipeline/last_source", str(kat))

    swieza = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert swieza._root is None and swieza.btn_presence.isEnabled()
        assert str(kat) in swieza.btn_presence.toolTip()
        swieza.btn_presence.click()
        assert swieza._thread is not None, "etap ruszył bez pytania o katalog"
        _czekaj_na_etap(swieza)
        assert swieza._root == str(kat)
        assert not swieza.box_vanished.isHidden() and not swieza.btn_mark_vanished.isHidden()
        assert swieza.btn_mark_vanished.isEnabled()
    finally:
        swieza.close()


def test_sprawdz_obecnosc_bez_zrodla_pyta_o_katalog(qapp, tmp_path, monkeypatch, ustawienia):
    """Bez wskazanego katalogu i bez ostatniego źródła przycisk pyta o katalog (jak „Przyjmij nowe"),
    a anulowane pytanie nie rusza niczego."""
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui.pipeline import PipelineView
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert view.btn_presence.isEnabled()
        assert view.btn_presence.toolTip() == i18n.t(
            "pipeline.tip.presence_ask", mark=i18n.t("pipeline.btn.mark_vanished"))
        view._on_presence()
        assert view._thread is None and view._root is None
    finally:
        view.close()


def test_zapis_naglowkow_mowi_czemu_Dostawa_jest_wygaszona(qapp, tmp_path):
    """AR-28 (c): w trakcie zapisu nagłówków cała Dostawa gaśnie; teraz mówi dlaczego - zdaniem pod
    złotą akcją i podpowiedzią samej akcji, tym samym kluczem, którym odmawia `run_stage`.

    Falsyfikator: zdejmij `lbl_writeback_busy.setVisible` z `_refresh_buttons` → asercja pada."""
    from horreum.gui.pipeline import PipelineView
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        powod = i18n.t("pipeline.refuse.writeback")
        assert view.lbl_writeback_busy.isHidden()
        view.set_writeback_busy(True)
        assert not view.btn_receive.isEnabled()
        assert not view.lbl_writeback_busy.isHidden() and view.lbl_writeback_busy.text() == powod
        assert view.btn_receive.toolTip() == powod and view.run_stage("resolve") == powod
        view.set_writeback_busy(False)
        assert view.lbl_writeback_busy.isHidden() and view.btn_receive.toolTip() == ""
    finally:
        view.close()
