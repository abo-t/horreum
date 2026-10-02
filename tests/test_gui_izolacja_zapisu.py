"""Drogi wyjścia z izolacji zapisu w miejscu na powierzchniach GUI (warunki wsadu AR-17 (1)(2))
i recepty wierszy kopii bez zeznania (AR-28).

Kopia z operacją `inplace_op` w fazie izolującej jest pomijana przez skan. Rdzeń ma trzy drogi
wyjścia (`writeback.finish_inplace`, `writeback.recover_torn`, `writeback.release_isolation`); tu
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
from PySide6.QtWidgets import QApplication, QDialog, QLabel

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
    Plik nietknięty, faza `released`, licznik 0. Gest idzie uchwytem zapisu gridu jak dwa pozostałe
    (rdzeń czeka na blokadę pliku), więc emituje `writeback_busy` True → False - mutex z Dostawą.

    Falsyfikator: zdejmij `_sync_ok` z okna → asercja o wygaszeniu pada; wołaj
    `release_inplace_op` z pustym powodem → asercja o treści zdarzenia pada; wołaj rdzeń w slocie
    wprost, z pominięciem `_start_gestu_zapisu` → asercja o `zajety` pada."""
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
        assert view.zajety == [True, False], "zwolnienie idzie uchwytem zapisu (blokada pliku)"
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
    stoją tylko, gdy są, a przerwanie mówi, że reszta nietknięta. Sukces bez powodu nie dokleja
    niczego; sukces Z powodem rdzenia (droga powrotu, zwolnienie pliku, którego nie ma) - tak,
    osobnym członem po powodzie odmowy.

    Falsyfikator: zdejmij drugi człon (`w.status == sukces and w.reason`) → ostatnia asercja pada."""
    from types import SimpleNamespace as NS
    wyniki = [NS(status="applied", path="C:\\a\\x.fits", reason=None),
              NS(status="blocked", path="/b/y.fits", reason="inny plik"),
              NS(status="failed", path="z.fits", reason="re-sync padł")]
    zdanie = grid_mod._zdanie_gestu_zapisu("finish_inplace", NS(results=wyniki, cancelled=True))
    assert zdanie == ("Dokończono 1 zapis · zablokowany 1 · nieudany 1 · przerwano, reszta "
                      "nietknięta - y.fits: inny plik")
    assert grid_mod._zdanie_gestu_zapisu(
        "recover_torn", NS(results=[NS(status="restored", path="a", reason=None)] * 2,
                           cancelled=False)) == "Przywrócono nagłówek w 2 plikach"
    assert grid_mod._zdanie_gestu_zapisu(
        "release_inplace", NS(results=[NS(status="released", path="C:\\a\\x.fits", reason="bez"),
                                       NS(status="blocked", path="y.fits", reason="zajęty")],
                              cancelled=False)) == \
        "Zwolniono do skanu 1 plik · zablokowany 1 - y.fits: zajęty - x.fits: bez"


def test_zdanie_commitu_stawia_powod_bledu_przed_blokada():
    """Bliźniak rozdarcia renamu po stronie commitu (`commit_renames` → szuflada): wsad z blokadą
    i błędem pokazywał powód PIERWSZEJ blokady, więc „plik PRZENIESIONY…, baza NIE przepięta"
    chował się za „cel już istnieje". Błąd bywa rozjazdem do naprawy, blokada zostawia plik
    nietknięty - powód błędu idzie pierwszy.

    Falsyfikator: przywróć `res.blocked + res.failed` w `zdanie_wyniku_zapisu` → asercja pada."""
    from types import SimpleNamespace as NS
    from horreum.gui.wb_worker import zdanie_wyniku_zapisu
    res = NS(applied=[NS(reason=None)],
             blocked=[NS(reason="cel już istnieje na dysku (anty-clobber)")],
             failed=[NS(reason="plik PRZENIESIONY na x.fits, ale baza NIE przepięta")],
             skipped=[])
    zdanie = zdanie_wyniku_zapisu(res, "grid.wb.renamed")
    assert zdanie.endswith("plik PRZENIESIONY na x.fits, ale baza NIE przepięta"), zdanie
    assert "1 zablokowanych" in zdanie and "1 błędów" in zdanie, zdanie


def test_przywroc_droga_powrotu_mowi_ze_plik_zmienil_sie_poza_naglowkiem(qapp, tmp_path,
                                                                           monkeypatch):
    """Zapis `written`, a dane poza nagłówkiem zmienione na dysku: „Przywróć nagłówek sprzed zapisu"
    idzie drogą powrotu - stary nagłówek w miejscu, plik zwolniony do pełnego skanu. Rdzeń oddaje
    'restored' Z POWODEM („plik zmienił się poza nagłówkiem… przeskanuj plik"). Dawniej zdanie
    brało powód tylko z odmów i błędów, więc człowiek czytał samo „Przywrócono nagłówek w 1 pliku".

    Falsyfikator: zdejmij człon sukcesu z `_zdanie_gestu_zapisu` → asercja o „przeskanuj" pada."""
    con, [(p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    dane = bytearray(p.read_bytes())
    dane[-1] ^= 0xFF                                    # bajt danych, daleko za nagłówkiem
    p.write_bytes(bytes(dane))
    view = _widok(con)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        view._on_restore_header()
        assert _fazy(con) == ["recovered"]
        zdanie = view.komunikaty[-1]
        assert zdanie.startswith("Przywrócono nagłówek w 1 pliku - a0.fits: "), zdanie
        assert "poza nagłówkiem" in zdanie and "przeskanuj" in zdanie, zdanie
        assert "przeskanuj" in view.drawer.result.text()
    finally:
        view.close()
    con.close()


def test_dlugie_zdanie_wyniku_nie_podnosi_minimum_okna(qapp, tmp_path, monkeypatch):
    """Zdanie wyniku w szufladzie (368 znaków, firsthand: porażka „Dokończ zapis") podnosiło
    minimum szerokości widoku - a za nim okna - do długości zdania (2613 px na ekranie 2560).
    Teraz zdanie jest elidowane w malowaniu, pełne w `text()` i w podpowiedzi, a minimum szerokości
    widoku z długim zdaniem równa się minimum bez niego. Bliźniak w tej samej etykiecie: nazwa
    pliku w postępie (`update_progress`) - też nie rusza minimum.

    Falsyfikator: `self.result = QLabel("")` w `StagingDrawer` → minimum rośnie z długością zdania."""
    con, _ = _baza(tmp_path)
    view = _widok(con)
    view.resize(1400, 800)
    view.show()                                         # ukryty widok nie liczy minimum z dzieci
    try:
        view.drawer.set_result("")
        QApplication.processEvents()
        przed = view.minimumSizeHint().width()
        przed_szuflada = view.drawer.minimumSizeHint().width()
        dlugie = "Dokończono 0 zapisów · nieudany 1 - " + "NGC281_20211110_LIGHT.fit: " + "x" * 330
        zwykla = QLabel(dlugie)                         # kontrola: offscreen mierzy tekst szerzej
        assert zwykla.minimumSizeHint().width() > przed, "sonda nie umiałaby się zaczerwienić"
        view.drawer.set_result(dlugie)
        QApplication.processEvents()
        assert view.minimumSizeHint().width() == przed
        assert view.drawer.minimumSizeHint().width() == przed_szuflada
        assert view.drawer.result.text() == dlugie and view.drawer.result.toolTip() == dlugie
        view.drawer.update_progress(1, 2, "C:\\" + "d" * 300 + ".fits")
        QApplication.processEvents()
        assert view.minimumSizeHint().width() == przed
    finally:
        view.close()
    con.close()


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
    """Gospodarz podpina `open_intake` pod przełączenie widoku - droga człowieka od wiersza do ekranu -
    i podaje Dostawie powód wejścia: linia nad akcjami mówi, po co człowiek tu jest."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PORZADKI, MainWindow
    from horreum.gui.pipeline import REASON_COPY_FACTS
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    _kopie_bez_faktow(tmp_path).close()
    win = MainWindow(str(tmp_path / "k.db"))
    try:
        win._show_view(NAV_PORZADKI)
        win.tasks_view._on_task_clicked(_wiersz(win.tasks_view, "orphan_testimony_frames"))
        assert win.stack.currentIndex() == NAV_DOSTAWA
        assert win.pipeline_view._reason == REASON_COPY_FACTS
        assert win.pipeline_view.lbl_reason.text()
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


_WARUNEK_PRZYCISKU = {"pl": "gdy sprawdzenie potwierdzi zniknięcie",
                      "en": "when the check confirms the file is gone"}


def test_recepta_mowi_ze_oznacz_znikniete_jest_warunkowe(qapp, tmp_path, ustawienia):
    """Hamulec passa obecności (drzewo puste, za dużo kandydatów) nie liczy potwierdzeń, więc
    „Oznacz zniknięte" się wtedy nie pojawia - a recepta obiecywała go bezwarunkowo. Teraz każda
    forma obu recept w obu językach mówi, że przycisk pojawia się po POTWIERDZONYM zniknięciu,
    a sprawdzenie pod hamulcem („drzewo puste") rzeczywiście przycisku nie pokazuje.

    Falsyfikator: usuń warunek z którejkolwiek formy `grid.tip.copy_unread` /
    `tasks.copies_unread_tip` → pierwsza pętla pada."""
    for klucz in ("grid.tip.copy_unread", "tasks.copies_unread_tip"):
        for jezyk in ("pl", "en"):
            formy = CATALOG[klucz][jezyk]
            for tekst in (formy.values() if isinstance(formy, dict) else [formy]):
                assert _WARUNEK_PRZYCISKU[jezyk] in tekst[tekst.index("{mark}"):], (klucz, jezyk)

    from horreum.gui.pipeline import PipelineView
    from horreum.volumes import volume_serial
    kat = tmp_path / "t"
    kat.mkdir()
    plik = _fits(kat / "l0.fits")
    db_path = str(tmp_path / "p.db")
    con = db.open_db(db_path)
    scan.scan_tree(con, str(kat), volume=volume_serial(str(kat)) or "?", now=NOW)
    con.close()
    os.remove(str(plik))                                # jedyny plik drzewa - hamulec „drzewo puste"
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        view._set_root(str(kat))
        view._on_presence()
        _czekaj_na_etap(view)
        assert "drzewo puste" in view.lbl_summary.text(), view.lbl_summary.text()
        assert view.box_vanished.isHidden() or view.btn_mark_vanished.isHidden()
    finally:
        view.close()


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


def test_niedostepne_zrodlo_sprawdza_watek_tla_i_daje_droge_do_katalogu(qapp, tmp_path,
                                                                          monkeypatch, ustawienia):
    """Ostatnie źródło to odłączony udział (tu: katalog, którego nie ma). Dawniej slot okna robił
    `is_dir` na tej ścieżce - na zawieszonym SMB okno stało do timeoutu sieci - a potem bez słowa
    otwierał dialog katalogu. Teraz slot NIE dotyka dysku (ani `is_dir`, ani serialu woluminu):
    korzeń idzie do wątku tła, który wraca jawnym stanem „źródło niedostępne: <ścieżka> - wskaż
    katalog" z przyciskiem „Wskaż katalog…" pod wynikiem; dopiero ten przycisk pyta o katalog.
    Surowego „FileNotFoundError" na czerwono nie ma, a niedostępna ścieżka nie zostaje wskazanym
    katalogiem.

    Falsyfikator: przywróć w `_on_presence` `Path(source).is_dir()` na ostatnim źródle → lista
    dotknięć dysku w wątku okna nie jest pusta."""
    import threading
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui import pipeline as pipeline_mod
    brak = str(tmp_path / "odlaczony_udzial" / "ASTRO_")
    zdrowy = tmp_path / "zdrowy"
    zdrowy.mkdir()
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    ustawienia.setValue("pipeline/last_source", brak)

    w_oknie = []                                        # (co, ścieżka) wołane w wątku okna

    def _szpieg(nazwa, prawdziwa):
        def _f(sciezka, *a, **kw):
            if (threading.current_thread() is threading.main_thread()
                    and "odlaczony_udzial" in str(sciezka)):
                w_oknie.append((nazwa, str(sciezka)))
            return prawdziwa(sciezka, *a, **kw)
        return _f
    monkeypatch.setattr(os.path, "isdir", _szpieg("isdir", os.path.isdir))
    monkeypatch.setattr(Path, "is_dir", _szpieg("Path.is_dir", Path.is_dir))
    monkeypatch.setattr(pipeline_mod, "volume_serial",
                        _szpieg("volume_serial", pipeline_mod.volume_serial))
    dialogi = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: dialogi.append(1) or str(zdrowy)))

    view = pipeline_mod.PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert brak in view.btn_presence.toolTip()
        view._on_presence()
        assert w_oknie == [] and dialogi == [], (w_oknie, dialogi)
        assert view._thread is not None, "etap ruszył na ostatnim źródle"
        _czekaj_na_etap(view)
        zdanie = i18n.t("pipeline.source.unreachable_pick", root=brak)
        assert not view.box_vanished.isHidden() and view.lbl_vanished.text() == zdanie
        assert not view.btn_pick_source.isHidden() and view.btn_pick_source.isEnabled()
        assert view.btn_mark_vanished.isHidden() and view.lbl_error.isHidden()
        assert i18n.t("pipeline.source.unreachable", root=brak) in view.lbl_summary.text()
        assert view._root is None and dialogi == []
        assert w_oknie == [], w_oknie

        view.btn_pick_source.click()                    # droga dalej - dopiero TERAZ pytanie
        assert dialogi == [1] and view._thread is not None
        _czekaj_na_etap(view)
        assert view._root == str(zdrowy)
        # AR-30 (3): katalog wskazany do sprawdzenia nie przestawia źródła „Przyjmij nowe” -
        # niedostępne źródło dostawy zgłosi własna droga złotej akcji, z własnym pytaniem.
        assert ustawienia.value("pipeline/last_source") == brak
        assert view.btn_pick_source.isHidden()
    finally:
        view.close()


@pytest.mark.parametrize("wejscie", ["przyjmij_nowe", "skanuj"])
def test_sekwencja_skanu_na_niedostepnym_zrodle_nie_dotyka_dysku_w_oknie(
        qapp, tmp_path, monkeypatch, ustawienia, wejscie):
    """AR-31 (3), bliźniak „Sprawdź obecność": złota akcja „Przyjmij nowe" robiła `is_dir` na
    zapamiętanym źródle, a ona i „Skanuj"/„Przetwórz wszystko" mierzyły serial woluminu
    (`_set_root`, `_scan_params`) w slocie okna - na odłączonym udziale SMB okno stało do timeoutu
    sieci. Teraz slot nie dotyka dysku: sondę i serial robi wątek tła, a niedostępne źródło wraca
    jawnym stanem „Źródło niedostępne: <ścieżka> - wskaż katalog" z przyciskiem, linią „[skan] NIE
    WYKONANO" i bez zmiany wskazanego katalogu. Przycisk pyta o katalog i powtarza TEN etap.

    Falsyfikator: przywróć w `_on_receive` `Path(source).is_dir()` albo w `_scan_params`
    `volume_serial` → lista dotknięć dysku w wątku okna nie jest pusta."""
    import threading
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui import pipeline as pipeline_mod
    brak = str(tmp_path / "odlaczony_udzial" / "ASTRO_")
    zdrowy = tmp_path / "zdrowy"
    zdrowy.mkdir()
    _fits(zdrowy / "l0.fits")
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()

    w_oknie = []                                        # (co, ścieżka) wołane w wątku okna

    def _szpieg(nazwa, prawdziwa):
        def _f(sciezka, *a, **kw):
            if (threading.current_thread() is threading.main_thread()
                    and str(tmp_path) in str(sciezka)):
                w_oknie.append((nazwa, str(sciezka)))
            return prawdziwa(sciezka, *a, **kw)
        return _f
    monkeypatch.setattr(os.path, "isdir", _szpieg("isdir", os.path.isdir))
    monkeypatch.setattr(Path, "is_dir", _szpieg("Path.is_dir", Path.is_dir))
    monkeypatch.setattr(pipeline_mod, "volume_serial",
                        _szpieg("volume_serial", pipeline_mod.volume_serial))
    dialogi = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: dialogi.append(1) or str(zdrowy)))

    view = pipeline_mod.PipelineView(db_path, now_fn=lambda: NOW)
    try:
        if wejscie == "przyjmij_nowe":
            ustawienia.setValue("pipeline/last_source", brak)
            view._on_receive()
        else:
            view._root = brak                           # wskazany wcześniej, udział odpadł potem
            view._sync_actions()
            view._on_scan()
        assert w_oknie == [] and dialogi == [], (w_oknie, dialogi)
        assert view._thread is not None, "etap ruszył bez pytania o katalog"
        _czekaj_na_etap(view)
        zdanie = i18n.t("pipeline.source.unreachable_pick", root=brak)
        assert not view.box_vanished.isHidden() and view.lbl_vanished.text() == zdanie
        assert not view.btn_pick_source.isHidden() and view.btn_pick_source.isEnabled()
        assert view.btn_mark_vanished.isHidden() and view.lbl_error.isHidden()
        linia = i18n.t("pipeline.fmt.scan_not_done",
                       reason=i18n.t("pipeline.source.unreachable", root=brak))
        assert view.lbl_summary.text() == linia, view.lbl_summary.text()
        assert view._root == (None if wejscie == "przyjmij_nowe" else brak)
        assert w_oknie == [] and dialogi == [], w_oknie

        view.btn_pick_source.click()                    # droga dalej - dopiero TERAZ pytanie
        assert dialogi == [1] and view._thread is not None
        assert w_oknie == [], w_oknie
        _czekaj_na_etap(view)
        assert view._root == str(zdrowy) and str(zdrowy) in view.lbl_root.text()
        assert ustawienia.value("pipeline/last_source") == str(zdrowy)
        assert "[skan] pliki 1" in view.lbl_summary.text(), view.lbl_summary.text()
        assert ("[delta]" in view.lbl_summary.text()) == (wejscie == "przyjmij_nowe")
        assert view.btn_pick_source.isHidden()
    finally:
        view.close()


def test_podpowiedz_sprawdz_obecnosc_mowi_ze_oznacz_znikniete_jest_warunkowe(qapp, tmp_path,
                                                                             ustawienia):
    """AR-31 (4), bliźniak poprawionej recepty kopii bez zeznania: trzy podpowiedzi „Sprawdź
    obecność" obiecywały „Oznacz zniknięte… pojawi się pod wynikiem" bezwarunkowo, a przycisk
    pojawia się tylko po POTWIERDZONYM zniknięciu (hamulec passa potwierdzeń nie liczy, „nic nie
    znikło" nie ma czego oznaczać). Teraz każda z trzech podpowiedzi w obu językach niesie
    warunek po nazwie przycisku, a podpowiedź na ekranie mówi go w każdym z trzech stanów.

    Falsyfikator: usuń warunek z którejkolwiek `pipeline.tip.presence*` → pierwsza pętla pada."""
    warunek = {"pl": "gdy sprawdzenie potwierdzi zniknięcie",
               "en": "when the check confirms a copy is gone"}
    klucze = ("pipeline.tip.presence", "pipeline.tip.presence_last", "pipeline.tip.presence_ask")
    for klucz in klucze:
        for jezyk in ("pl", "en"):
            tekst = CATALOG[klucz][jezyk]
            assert warunek[jezyk] in tekst[tekst.index("{mark}"):], (klucz, jezyk)

    from horreum.gui.pipeline import PipelineView
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert warunek["pl"] in view.btn_presence.toolTip()               # pytanie o katalog
        ustawienia.setValue("pipeline/last_source", str(tmp_path))
        view._sync_source_memo()
        assert str(tmp_path) in view.btn_presence.toolTip()                # ostatnie źródło
        assert warunek["pl"] in view.btn_presence.toolTip()
        view._show_root(str(tmp_path), None)
        assert warunek["pl"] in view.btn_presence.toolTip()               # wskazany katalog
    finally:
        view.close()


def test_recepta_recznego_zwolnienia_wskazuje_gest_okna_i_release_isolation():
    """AR-31 (5): zdanie odmowy „nierozstrzygalne…" (`writeback._RECZNA`) kierowało do
    `repo.release_inplace_op(N)` - klingi bazy bez blokady pliku, której człowiek nie ma jak wywołać.
    Drogą usera jest gest „Zwolnij plik do skanu…" w menu prawego kliku w Zbiorach, a w kodzie
    `writeback.release_isolation` (zwolnienie pod blokadą pliku z CAS fazy). Nazwa gestu musi być
    tą z katalogu - zmiana etykiety bez zdania rozjechałaby receptę z menu.

    Falsyfikator: przywróć w `_RECZNA` `repo.release_inplace_op` → pierwsza asercja pada."""
    assert "release_inplace_op" not in writeback._RECZNA
    assert "writeback.release_isolation" in writeback._RECZNA
    assert f"„{CATALOG['grid.inplace.release']['pl']}”" in writeback._RECZNA
    assert "w Zbiorach" in writeback._RECZNA and "prawego kliku" in writeback._RECZNA


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


# ═════════════════════════ AR-30: ogony GUI izolacji zapisu w miejscu


def test_AR30_1_powod_rdzenia_mowi_gestem_okna_i_wywolaniem(tmp_path, monkeypatch):
    """AR-30 (1): powody porażki nazywały same FUNKCJE (`recover_torn(N)`, `finish_inplace(N)`),
    a menu nazywa te drogi gestami. Powód mówi teraz w dwóch formach naraz - „gest” (`wywołanie`) -
    a nazwy gestów w rdzeniu są tymi z katalogu GUI (rdzeń nie importuje GUI, więc pilnuje test).

    Falsyfikator: przywróć w `_powod_izolacji` samo `recover_torn(N)` → asercja o geście pada;
    zmień etykietę gestu w katalogu bez rdzenia → pierwsza pętla pada."""
    for stala, klucz in ((writeback._GEST_DOKONCZ, "grid.inplace.finish"),
                         (writeback._GEST_PRZYWROC, "grid.inplace.restore"),
                         (writeback._GEST_ZWOLNIJ, "grid.inplace.release")):
        assert stala == CATALOG[klucz]["pl"], klucz
    otwarta = writeback._powod_izolacji({"id": 7, "kind": "commit", "phase": "unverified"})
    assert f"„{writeback._GEST_PRZYWROC}” (`recover_torn(7)`)" in otwarta, otwarta
    czeka = writeback._powod_izolacji({"id": 8, "kind": "commit", "phase": "written"})
    assert f"„{writeback._GEST_DOKONCZ}” (`finish_inplace(8)`)" in czeka, czeka
    assert f"„{writeback._GEST_PRZYWROC}” (`recover_torn(8)`)" in czeka, czeka

    con, _ = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    op_id = con.execute("SELECT id FROM inplace_op").fetchone()[0]
    odmowa = writeback.recover_torn(con, op_id, now=NOW)       # zapis poprawny - powrót odmawia
    assert odmowa.status == "blocked"
    assert f"„{writeback._GEST_DOKONCZ}” (`finish_inplace({op_id})`)" in odmowa.reason, odmowa
    con.close()


def test_AR30_2_podpowiedzi_dokonczenia_mowia_o_powrocie_i_zwolnieniu(qapp, tmp_path, monkeypatch):
    """AR-30 (2): podpowiedź „Dokończ zapis” (menu) i wiersza „Zapis czeka na dokończenie”
    (Porządki) mówiły tylko „Dokończ”, choć przy nieudanej kontroli danych drogą jest powrót,
    a przy pliku skasowanym - zwolnienie. Obie nazywają teraz oba gesty.

    Falsyfikator: zdejmij `finish_tip_else` z `_sync_menu_zapisu` → druga asercja pada."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    tv = tasks_mod.TasksView(con)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        menu = _menu(view)
        try:
            tip = view.act_finish_write.toolTip()
            assert tip.startswith("Dokończy 1 zapis"), tip
            for gest in ("grid.inplace.restore", "grid.inplace.release"):
                assert f"„{i18n.t(gest)}”" in tip, tip
            assert view._sep_zwolnienia.isVisible(), "„Zwolnij…” za własną kreską"
        finally:
            menu.hide()
        tv.refresh_counts()
        wiersz = _wiersz(tv, "pending_finish_frames").toolTip()
        for gest in ("grid.inplace.finish", "grid.inplace.restore", "grid.inplace.release"):
            assert f"„{i18n.t(gest)}”" in wiersz, wiersz
    finally:
        tv.close()
        view.close()
    con.close()


def test_AR30_3_katalog_do_sprawdzenia_nie_zostaje_zrodlem_dostawy(qapp, tmp_path, monkeypatch,
                                                                    ustawienia):
    """AR-30 (3): „Wskaż katalog…” obecności zapisywał wskazany katalog jako źródło „Przyjmij nowe” -
    sprawdzenie korzenia archiwum przestawiało złotą akcję na całe archiwum. Podpowiedź przy
    ostatnim źródle mówi teraz zakres (tylko kopie pod tym katalogiem) i drogę do korzenia.

    Falsyfikator: przywróć `_remember_source` w `_on_presence_pick` → asercja o pamięci pada."""
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui.pipeline import PipelineView
    dostawa = tmp_path / "dostawa"
    korzen = tmp_path / "archiwum"
    dostawa.mkdir()
    korzen.mkdir()
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    ustawienia.setValue("pipeline/last_source", str(dostawa))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(korzen)))
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        tip = view.btn_presence.toolTip()
        assert str(dostawa) in tip and f"„{i18n.t('pipeline.btn.presence_in')}”" in tip, tip
        view._on_presence_pick()
        _czekaj_na_etap(view)
        assert view._root == str(korzen)
        assert ustawienia.value("pipeline/last_source") == str(dostawa)
    finally:
        view.close()


def test_sprawdz_obecnosc_W_nie_zapamietuje_zrodla_i_nie_dotyka_dysku_w_oknie(
        qapp, tmp_path, monkeypatch, ustawienia):
    """Podpowiedź „Sprawdź obecność" kazała po korzeń archiwum sięgać „Wskaż katalog…", który
    ZAPAMIĘTUJE źródło „Przyjmij nowe" - złota akcja wciągałaby potem całe archiwum, czyli
    dokładnie ta szkoda, przed którą chroni `_on_presence_pick`. Jest teraz osobne wejście
    „Sprawdź obecność w…" obok „Sprawdź obecność": pyta o katalog, sprawdza go, a źródła dostawy
    nie rusza. Podpowiedź wskazuje to wejście, a sondę katalogu (is_dir, serial) robi wątek tła.

    Falsyfikator: podepnij przycisk pod `_on_pick_dir` albo przywróć `_remember_source`
    w `_on_presence_pick` → `pipeline/last_source` zmienia się na korzeń; przywróć `_set_root`
    w `_on_presence_pick` → lista dotknięć dysku w wątku okna nie jest pusta."""
    import threading
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui import pipeline as pipeline_mod
    dostawa = tmp_path / "dostawa"
    korzen = tmp_path / "archiwum"
    dostawa.mkdir()
    korzen.mkdir()
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    ustawienia.setValue("pipeline/last_source", str(dostawa))
    w_oknie = []

    def _szpieg(nazwa, prawdziwa):
        def _f(sciezka, *a, **kw):
            if (threading.current_thread() is threading.main_thread()
                    and "archiwum" in str(sciezka)):
                w_oknie.append((nazwa, str(sciezka)))
            return prawdziwa(sciezka, *a, **kw)
        return _f
    monkeypatch.setattr(os.path, "isdir", _szpieg("isdir", os.path.isdir))
    monkeypatch.setattr(Path, "is_dir", _szpieg("Path.is_dir", Path.is_dir))
    monkeypatch.setattr(pipeline_mod, "volume_serial",
                        _szpieg("volume_serial", pipeline_mod.volume_serial))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(korzen)))
    view = pipeline_mod.PipelineView(db_path, now_fn=lambda: NOW)
    try:
        przycisk = view.btn_presence_in
        assert przycisk.text() == i18n.t("pipeline.btn.presence_in") and przycisk.isEnabled()
        assert i18n.t("pipeline.receive") in przycisk.toolTip()
        assert f"„{przycisk.text()}”" in view.btn_presence.toolTip(), "podpowiedź wskazuje wejście"
        przycisk.click()
        assert view._thread is not None, "etap ruszył"
        assert w_oknie == [], w_oknie
        _czekaj_na_etap(view)
        assert view._root == str(korzen), "korzeń wskazany dopiero po sondzie wątku tła"
        assert ustawienia.value("pipeline/last_source") == str(dostawa), "źródło dostawy nietknięte"
        assert w_oknie == [], w_oknie
    finally:
        view.close()


def test_AR30_4_klatka_z_kilkoma_kopiami_w_izolacji_nazywa_pliki(qapp, tmp_path, monkeypatch):
    """AR-30 (4): cel gestu kluczowany klatką, wykonanie per kopia - przy dwóch kopiach jednej klatki
    w izolacji gest rusza obie, a ekran nie mówił których. Populacja dziś 0 (zapis w miejscu odmawia
    przy ≥2 obecnych kopiach), więc stan podstawiony w read-modelu - test pinuje zdanie, nie rdzeń.

    Falsyfikator: zdejmij `_zdanie_kopii_wielokrotnych` z podpowiedzi → asercja o plikach pada."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    ops = [{"op_id": 1, "location_id": 1, "frame_id": fid, "phase": "written", "kind": "commit",
            "path": r"R:\A\a0.fits"},
           {"op_id": 2, "location_id": 2, "frame_id": fid, "phase": "written", "kind": "commit",
            "path": r"S:\B\a0_kopia.fits"}]
    monkeypatch.setattr(view, "_operacje_gestu", lambda: ops)
    try:
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        menu = _menu(view)
        try:
            for act in (view.act_finish_write, view.act_restore_header, view.act_release_file):
                assert "a0.fits, a0_kopia.fits" in act.toolTip(), act.toolTip()
        finally:
            menu.hide()
        assert grid_mod._zdanie_kopii_wielokrotnych(grid_mod._kopie_wielokrotne(ops[:1])) == ""
    finally:
        view.close()
    con.close()


def test_dopisek_kopii_wielokrotnych_nie_mowi_o_JEDNEJ_klatce_przy_plikach_z_kilku():
    """Lista `{files}` zbiera kopie WSZYSTKICH zaznaczonych klatek wielokopiowych, a dopisek mówił
    „Klatka ma kilka kopii…" - jedna klatka przy plikach z dwóch. Zdanie jest teraz neutralne
    wobec liczby klatek w obu językach, a liczba plików idzie liczebnikiem.

    Falsyfikator: przywróć „Klatka ma kilka kopii" w `grid.inplace.many_copies` → asercja pada."""
    ops = [{"op_id": i, "frame_id": fid, "path": rf"R:\A\{nazwa}"}
           for i, (fid, nazwa) in enumerate([(1, "a.fits"), (1, "a_kopia.fits"),
                                              (2, "b.fits"), (2, "b_kopia.fits")])]
    zdanie = grid_mod._zdanie_kopii_wielokrotnych(grid_mod._kopie_wielokrotne(ops))
    assert "4 pliki: a.fits, a_kopia.fits, b.fits, b_kopia.fits" in zdanie, zdanie
    for forma in CATALOG["grid.inplace.many_copies"]["pl"].values():
        assert not forma.lstrip().startswith("Klatka ma"), forma
    for forma in CATALOG["grid.inplace.many_copies"]["en"].values():
        assert not forma.lstrip().startswith("A frame has"), forma


@pytest.mark.parametrize("preset", [grid_mod.PRESET_PENDING_FINISH, grid_mod.PRESET_TORN_WRITE])
def test_sciezka_w_perspektywach_izolacji_z_trescia_i_elizja_w_srodku(qapp, tmp_path, monkeypatch,
                                                                      preset):
    """Perspektywy izolacji pokazywały w kolumnie ścieżki „×2 …" - prefiks klatki wielokopiowej
    przy domyślnej szerokości i elizji z prawej, czyli bez nazwy pliku. Należą teraz do perspektyw,
    w których ścieżka bierze szerokość z treści i elizję w środku - ten sam mechanizm co Duplikaty.

    Falsyfikator: zdejmij `_RECEPTY_ZAPISU` z `_FLAGI_SCIEZKI_Z_TRESCI` → delegat kolumny jest
    domyślny i asercja pada."""
    con, _pliki = _baza(tmp_path)
    if preset == grid_mod.PRESET_PENDING_FINISH:
        _commit_written(monkeypatch, con)
    else:
        _commit_przerwany(monkeypatch, con)
    view = _widok(con)
    try:
        view.apply_perspective(preset)
        kol = view.model.base_col("path")
        assert isinstance(view.table.itemDelegateForColumn(kol), grid_mod._ElizjaWSrodku)
        assert view.table.columnWidth(kol) <= grid_mod._SUFIT_KOLUMNY_Z_TRESCI
        view.apply_perspective("Przegląd")
        assert not isinstance(view.table.itemDelegateForColumn(kol), grid_mod._ElizjaWSrodku)
    finally:
        view.close()
    con.close()


def test_AR30_5_wynik_gestu_nie_stoi_obok_postepu_i_nie_przezywa_perspektywy(qapp, tmp_path,
                                                                             monkeypatch):
    """AR-30 (5): szuflada pokazywała wynik poprzedniego gestu obok postępu następnego i niosła go
    do innej perspektywy. Teraz start postępu czyści pole, a zmiana perspektywy oddaje tekst sprzed
    gestu - o ile szuflada wciąż pokazuje wynik gestu.

    Falsyfikator: zdejmij `result.setText("")` z `begin_progress` → pierwsza asercja pada; zdejmij
    `_zdejmij_wynik_gestu_zapisu` z `_on_perspective` → ostatnia asercja pada."""
    con, [(_p, fid)] = _baza(tmp_path)
    _commit_written(monkeypatch, con)
    view = _widok(con)
    try:
        view.drawer.set_result("stary wynik")
        view.drawer.begin_progress(0)
        assert view.drawer.result.text() == ""
        view.drawer.end_progress()
        view.drawer.set_result("Zatwierdzono 1")
        view.apply_perspective(grid_mod.PRESET_PENDING_FINISH)
        _zaznacz(view, [fid])
        view._on_finish_write()
        assert view.drawer.result.text().startswith("Dokończono 1 zapis")
        view.apply_perspective("Przegląd")
        assert view.drawer.result.text() == "Zatwierdzono 1"
    finally:
        view.close()
    con.close()


def test_szuflada_po_Przywroc_naglowek_oddaje_PRAWDZIWE_zdanie_commitu(qapp, tmp_path,
                                                                       monkeypatch):
    """Podejrzenie z recenzji: po geście „Przywróć nagłówek sprzed zapisu" zmiana perspektywy
    oddaje szufladzie „Zatwierdzono…" przy „Cofnij" - czy to zdanie nie mówi o zapisie, który gest
    właśnie cofnął? Nie mówi: commit szuflady idzie drogą ATOMOWĄ (`wb_worker` woła
    `writeback.commit` bez `inplace`), więc nie ma operacji `inplace_op`, a operacja izolowana
    pochodzi z INNEGO zapisu (zapis w miejscu poza gridem). Gest cofa tamten zapis do stanu po
    commicie szuflady - zmiana commitu zostaje w pliku, a „Cofnij" dalej ją cofa.

    Falsyfikator: gdyby gest cofał zmianę commitu szuflady, nagłówek po geście miałby wartość
    sprzed commitu i pierwsza asercja o pliku padłaby."""
    con, [(p, fid)] = _baza(tmp_path)
    view = _widok(con)
    try:
        view._run_id = "R"
        view.refresh()
        view._on_commit()                                     # commit szuflady - droga atomowa
        assert _fazy(con) == [], "commit szuflady nie zostawia operacji w miejscu"
        zdanie_commitu = view.drawer.result.text()
        assert view._undo_mode == "macro" and not view._undo_btn.isHidden()
        assert fits.getheader(str(p))["OBJECT"] == "NGC 6992"
        # Drugi zapis tej kopii W MIEJSCU, poza gridem, przerwany po zapisie (faza otwarta).
        loc = con.execute("SELECT id, header_hash FROM location WHERE frame_id = ?",
                          (fid,)).fetchone()
        repo.stage_pending(con, run_id="R2", location_id=loc["id"], keyword="OBJECT", idx=0,
                           op="set", old_value="NGC 6992", new_value="NGC 6995", new_type="str",
                           new_comment=None, expected_header_hash=loc["header_hash"])
        prawdziwy = os.fsync

        def _fsync(fd):
            prawdziwy(fd)
            raise OSError(64, "The specified network name is no longer available")
        with monkeypatch.context() as m:
            m.setattr(writeback.os, "fsync", _fsync)
            writeback.commit(con, "R2", now=NOW, inplace=True)
        assert _fazy(con) == ["unverified"]
        assert fits.getheader(str(p))["OBJECT"] == "NGC 6995"

        view.apply_perspective(grid_mod.PRESET_TORN_WRITE)
        _zaznacz(view, [fid])
        view._on_restore_header()
        assert view.drawer.result.text().startswith("Przywrócono"), view.drawer.result.text()
        assert fits.getheader(str(p))["OBJECT"] == "NGC 6992", "zmiana commitu szuflady została"
        view.apply_perspective("Przegląd")
        assert view.drawer.result.text() == zdanie_commitu    # zdanie wraca - i jest prawdziwe
        assert not view._undo_btn.isHidden()
        view._dispatch_undo()                                 # „Cofnij" dalej cofa ten commit
        assert fits.getheader(str(p))["OBJECT"] == "NGC6992", view.drawer.result.text()
    finally:
        view.close()
    con.close()
