"""Fakty KOPII (0021) na powierzchniach GUI: wiersz Porządków „Kopie niezgodne ze sobą" (liczba,
plakietka, klik → Zbiory z tymi klatkami), kolumna „Obrazy" i podpowiedź „×N" w Zbiorach, etap
uzupełnienia w łańcuchu „Przyjmij nowe". Okno offscreen, pliki syntetyczne w `tmp_path`."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from horreum import db, repo, scan
from horreum.gui import grid as grid_mod, i18n, queries, rows, tasks as tasks_mod
from horreum.gui.pipeline import PipelineWorker

from test_copy_facts import NOW, _FLAT, _dwie_kopie, _fits, _xisf


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def archiwum(tmp_path):
    """Trzy klatki: niezgodne kopie (CLS ×3 obrazy / L-Pro ×1), jedna kopia XISF (2 obrazy) i FITS."""
    root, a, b = _dwie_kopie(tmp_path)
    solo = _xisf(root / "S" / "solo.xisf", _FLAT, payload=b"\x09" * 32,
                 images=({"id": "integration"}, {"id": "weightImage"}))
    f = _fits(root / "F" / "light.fits", "Ha")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = {k: con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]
           for k, p in (("kopie", a), ("solo", solo), ("fits", f))}
    yield con, fid, a, b
    con.close()


@pytest.fixture
def view(qapp, archiwum, monkeypatch):
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    con = archiwum[0]
    v = grid_mod.FramesView(con, now_fn=None)
    yield v
    v.close()


def _wiersz_modelu(view, frame_id):
    return next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == frame_id)


def _komorka(view, frame_id, klucz, rola=Qt.DisplayRole):
    kol = [k for _, k in grid_mod.BASE_COLS].index(klucz)
    return view.model.data(view.model.index(_wiersz_modelu(view, frame_id), kol), rola)


def test_kolumna_obrazy_pokazuje_wszystkie_rozne_wartosci_kopii(view, archiwum):
    """„3 | 1" dla klatki, której kopie niosą różną liczbę obrazów (w kolejności kopii), własna
    liczba dla jedynej kopii XISF, pusto dla FITS (liczba HDU nieznana bez dodatkowego I/O).
    Nagłówek kolumny i pozycja „Grupuj wg" mówią z katalogu, nie kluczem wewnętrznym."""
    _con, fid, _a, _b = archiwum
    assert _komorka(view, fid["kopie"], "_images") == "3 | 1"
    assert _komorka(view, fid["solo"], "_images") == "2"
    assert _komorka(view, fid["fits"], "_images") == ""
    kol = [k for _, k in grid_mod.BASE_COLS].index("_images")
    assert view.model.headerData(kol, Qt.Horizontal, Qt.DisplayRole) == i18n.t("grid.col.images")
    etykiety = [view.combo_group.itemText(i) for i in range(view.combo_group.count())]
    assert i18n.t("grid.col.images") in etykiety


def test_podpowiedz_xN_wymienia_kopie_obrazy_i_rozbiezne_pola(view, archiwum):
    """Pod „×2" każda obecna kopia: pełna ścieżka, liczba i role obrazów, pola, w których jej
    nagłówek mówi co innego - z JEJ wartością. Te same pola co wiersz Porządków (jeden właściciel
    reguły `queries.copy_divergence`)."""
    _con, fid, a, b = archiwum
    assert _komorka(view, fid["kopie"], "path").startswith("×2")
    tip = _komorka(view, fid["kopie"], "path", Qt.ToolTipRole)
    assert str(a) in tip and str(b) in tip
    assert "obrazy: 3 (MasterFlat, RejectionMapLow, RejectionMapHigh)" in tip
    assert "obrazy: 1 (integration)" in tip
    assert "FILTER=CLS" in tip and "FILTER=L-Pro" in tip
    assert tip.count("mówi inaczej:") == 2
    solo_tip = _komorka(view, fid["solo"], "path", Qt.ToolTipRole)
    assert "mówi inaczej" not in solo_tip                    # jedna kopia - nie ma z czym się różnić


def test_podpowiedz_mowi_o_kopii_bez_zebranego_zeznania(qapp, tmp_path, monkeypatch):
    """Kopia sprzed 0021 (fakty jeszcze niezebrane) nie milczy jak kopia zgodna - mówi, że zeznania
    nie ma i co je uzupełni. Rozjazdu wtedy nie ogłaszamy: „nie wiem" nie jest „inaczej"."""
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    root, a, b = _dwie_kopie(tmp_path)
    con = db.open_db(str(tmp_path / "h.db"))
    for p in (a, b):
        rec = scan.scan_file(str(p))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                                   filetype="xisf", camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path,
                          header_hash=rec.header_hash, now=NOW)
    v = grid_mod.FramesView(con, now_fn=None)
    try:
        tip = _komorka(v, fid, "path", Qt.ToolTipRole)
        assert tip.count("zeznanie nagłówka jeszcze niezebrane") == 2
        assert "mówi inaczej" not in tip
        assert _komorka(v, fid, "_images") == ""
    finally:
        v.close()
        con.close()


def test_wiersz_porzadkow_liczy_i_prowadzi_do_listy_TYLKO_swoich_klatek(view, archiwum):
    """Wiersz jest AKCYJNY i JEST robotą (poza `_BEZ_ROBOTY`): pogrubiony, liczony do plakietki.
    Klik prowadzi do Zbiorów z perspektywą, która pokazuje dokładnie tyle klatek, ile mówi liczba,
    a pasek kryteriów nazywa zawężenie."""
    con, fid, _a, _b = archiwum
    assert "copy_conflict_frames" not in tasks_mod._BEZ_ROBOTY
    tv = tasks_mod.TasksView(con)
    tv.open_collection.connect(view.apply_perspective)
    try:
        tv.refresh_counts()
        wiersz = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                      if tv.tasks.item(i).data(Qt.UserRole) == "copy_conflict_frames")
        assert wiersz.text() == i18n.t("tasks.copy_conflict_frames")
        assert wiersz.data(rows.SECONDARY) == "1  ›" and wiersz.data(rows.STRONG) is True
        # Plakietka = liczba wierszy „TU JEST ROBOTA" (pogrubionych), a ten jest wśród nich.
        zywe = [tv.tasks.item(i).data(Qt.UserRole) for i in range(tv.tasks.count())
                if tv.tasks.item(i).data(rows.STRONG)]
        assert "copy_conflict_frames" in zywe and tv.refresh_counts() == len(zywe)
        tv._on_task_clicked(wiersz)
        assert view._frame_ids == [fid["kopie"]]
        assert len(view._frame_ids) == queries.tasks_state(con)["copy_conflict_frames"]
        assert i18n.t("grid.criteria.only_copy_conflict") in view.sel_bar.criteria_label.toolTip()
    finally:
        tv.close()


def test_etap_Dostawy_uzupelnia_kopie_sprzed_migracji_i_potem_milczy(qapp, tmp_path):
    """„Przyjmij nowe" = skan (brama przyrostowa POMIJA kopie sprzed 0021 - mtime bez zmian) → etap
    faktów kopii → reszta łańcucha. Bez tego etapu żywa baza nie dostałaby faktów nigdy (wydanie
    nie ma CLI). Drugi przebieg nie ma kandydatów, więc etap milczy całkowicie - ani „w toku", ani
    linii raportu."""
    root, a, b = _dwie_kopie(tmp_path)
    path = str(tmp_path / "p.db")
    con = db.open_db(path)
    for p in (a, b):                                        # wiersze „sprzed migracji": bez faktów
        rec = scan.scan_file(str(p))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="master_flat",
                                   filetype="xisf", camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="VOL1", path=rec.path, mtime=rec.mtime,
                          header_hash=rec.header_hash, now=NOW)
    con.close()

    def _przebieg():
        w = PipelineWorker(path, now_fn=lambda: NOW)
        w.configure("all", root=str(root), volume="VOL1", drive_letter=None, tier=None)
        started, done = [], {}
        w.stage_started.connect(started.append)
        w.stage_done.connect(lambda n, r: done.__setitem__(n, r))
        w.run()
        return started, done

    started, done = _przebieg()
    assert started[:3] == ["scan", "copy_facts", "group"]
    assert done["scan"].skipped == 2                        # skan kopii nie ruszył
    s = done["copy_facts"]
    assert (s.rows, s.written, s.remaining) == (2, 2, 0)
    con = db.open_db(path)
    assert queries.copy_conflict_frame_ids(con) == {fid}
    con.close()
    started2, done2 = _przebieg()
    assert "copy_facts" not in started2 and "copy_facts" not in done2


def test_linia_raportu_faktow_kopii(qapp, tmp_path):
    """Raport mówi, ile uzupełniono z ilu, a odmowy (zmienione na dysku, nieczytelne) i to, co czeka,
    dopisuje tylko, gdy są - zero odmów to krótka linia (QUIET)."""
    from horreum.gui.pipeline import PipelineView
    path = str(tmp_path / "p.db")
    db.open_db(path).close()
    v = PipelineView(path, now_fn=lambda: NOW)
    try:
        czysto = v._format_result("copy_facts", scan.CopyFactsSummary(rows=5, read=5, written=5))
        assert czysto == "Fakty kopii: uzupełniono 5 z 5"
        brudno = v._format_result("copy_facts", scan.CopyFactsSummary(
            rows=5, read=4, written=3, stale=1, failed=1, remaining=2))
        assert "zmienione na dysku od skanu 1" in brudno and "nieczytelne 1" in brudno
        assert "czeka 2" in brudno
    finally:
        v.close()
