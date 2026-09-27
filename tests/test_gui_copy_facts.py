"""Fakty KOPII (0021) na powierzchniach GUI: wiersz Porządków „Kopie niezgodne ze sobą" (liczba,
plakietka, klik → Zbiory z tymi klatkami), kolumna „Obrazy" i podpowiedź „×N" w Zbiorach, etap
uzupełnienia w łańcuchu „Przyjmij nowe", a od AR-5 także przejęcie zeznania ocalałej kopii w tym
łańcuchu i wiersz „Zeznanie z nieobecnej kopii". Okno offscreen, pliki syntetyczne w `tmp_path`."""
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
        assert "czeka 2" in brudno and "brak pliku" not in brudno
        # Kopia skasowana z dysku nie udaje „nieczytelnej" - linia mówi, co z nią zrobić.
        skasowane = v._format_result("copy_facts", scan.CopyFactsSummary(
            rows=550, read=548, written=548, missing=2, remaining=2))
        assert skasowane == ("Fakty kopii: uzupełniono 548 z 550 · brak pliku 2 - Dostawa → "
                             "„Oznacz zniknięte” · czeka 2")
        assert "nieczytelne" not in skasowane
    finally:
        v.close()


# ═════════════════════════ zeznanie z nieobecnej kopii (AR-5)


def _po_skasowaniu_zrodla(tmp_path, *, trzecia=False):
    """Baza plikowa: klatka, której `header` pochodzi z kopii L-Pro (skasowanej i nieobecnej),
    a obecna kopia mówi CLS (opcjonalnie druga obecna - OSC). Zwraca (ścieżka bazy, korzeń, fid)."""
    from test_orphan_testimony import _MASTER, _cls, _lpro, _zniknij
    root = tmp_path / "ARCH"
    a = _lpro(root)
    _cls(root)
    if trzecia:
        _xisf(root / "C_OSC" / "m.xisf", _MASTER + (("FILTER", "'OSC'"),), payload=b"\x05" * 32)
    path = str(tmp_path / "p.db")
    con = db.open_db(path)
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(a),)).fetchone()[0]
    _zniknij(con, a)
    con.close()
    return path, root, fid


def test_etap_Dostawy_przejmuje_zeznanie_przed_pochodnymi_i_potem_milczy(qapp, tmp_path):
    """„Przyjmij nowe": skan → fakty kopii → PRZEJĘCIE ZEZNANIA → group → resolve… W TYM SAMYM
    przebiegu `filter_canon` przechodzi na głos ocalałej kopii - przejęcie stoi przed etapami, które
    czytają `header`. Drugi przebieg nie ma kandydatów, więc etap milczy całkowicie."""
    from horreum.resolve.filters import normalize_filter
    path, root, fid = _po_skasowaniu_zrodla(tmp_path)

    def _przebieg():
        w = PipelineWorker(path, now_fn=lambda: NOW)
        w.configure("all", root=str(root), volume="?", drive_letter=None, tier=None)
        started, done = [], {}
        w.stage_started.connect(started.append)
        w.stage_done.connect(lambda n, r: done.__setitem__(n, r))
        w.run()
        return started, done

    started, done = _przebieg()
    assert started[:3] == ["scan", "adopt_testimony", "group"]
    assert started.index("adopt_testimony") < started.index("resolve")
    s = done["adopt_testimony"]
    assert (s.rows, s.adopted, s.remaining) == (1, 1, 0)
    con = db.open_db(path)
    assert con.execute("SELECT filter_raw FROM header WHERE frame_id = ?",
                       (fid,)).fetchone()[0] == "CLS"
    assert con.execute("SELECT filter_canon FROM frame WHERE id = ?",
                       (fid,)).fetchone()[0] == normalize_filter("CLS")
    con.close()
    started2, done2 = _przebieg()
    assert "adopt_testimony" not in started2 and "adopt_testimony" not in done2


def test_linia_raportu_przejecia_zeznania(qapp, tmp_path):
    """Raport mówi, ile przejęto z ilu; odmowy (inna klatka pod ścieżką, zmienione od skanu,
    nieczytelne) i to, co czeka, dopisuje tylko, gdy są (QUIET)."""
    from horreum.gui.pipeline import PipelineView
    path = str(tmp_path / "p.db")
    db.open_db(path).close()
    v = PipelineView(path, now_fn=lambda: NOW)
    try:
        czysto = v._format_result("adopt_testimony", scan.AdoptSummary(rows=2, read=2, adopted=2))
        assert czysto == "Zeznanie z nieobecnej kopii: przejęte od ocalałej kopii 2 z 2"
        brudno = v._format_result("adopt_testimony", scan.AdoptSummary(
            rows=4, read=3, adopted=1, identity=1, stale=1, failed=1, remaining=3))
        assert "plik to inna klatka 1" in brudno and "zmienione na dysku od skanu 1" in brudno
        assert "nieczytelne 1" in brudno and "czeka 3" in brudno
    finally:
        v.close()


def test_wiersz_porzadkow_zeznanie_z_nieobecnej_kopii(qapp, tmp_path, monkeypatch):
    """Wiersz AKCYJNY i ROBOTA (poza `_BEZ_ROBOTY`): liczy klatki o ≥2 obecnych kopiach, których
    `header` mówi głosem nieobecnej - tu kopię wiodącą wskazuje człowiek. Klik prowadzi do Zbiorów
    z perspektywą pokazującą dokładnie te klatki; pasek kryteriów nazywa zawężenie."""
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    path, _root, fid = _po_skasowaniu_zrodla(tmp_path, trzecia=True)
    con = db.open_db(path)
    view = grid_mod.FramesView(con, now_fn=None)
    tv = tasks_mod.TasksView(con)
    tv.open_collection.connect(view.apply_perspective)
    try:
        assert "orphan_testimony_frames" not in tasks_mod._BEZ_ROBOTY
        tv.refresh_counts()
        wiersz = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                      if tv.tasks.item(i).data(Qt.UserRole) == "orphan_testimony_frames")
        assert wiersz.text() == i18n.t("tasks.orphan_testimony_frames")
        assert wiersz.data(rows.SECONDARY) == "1  ›" and wiersz.data(rows.STRONG) is True
        tv._on_task_clicked(wiersz)
        assert view._frame_ids == [fid]
        assert len(view._frame_ids) == queries.tasks_state(con)["orphan_testimony_frames"]
        assert i18n.t("grid.criteria.only_orphan_testimony") in view.sel_bar.criteria_label.toolTip()
    finally:
        tv.close()
        view.close()
        con.close()


def test_gest_oznacz_znikniete_puszcza_przejecie_i_pochodne(qapp, tmp_path, monkeypatch):
    """„Oznacz zniknięte" (presence-apply) to chwila, w której klatka zaczyna mówić głosem
    nieobecnego pliku - więc w tym samym wątku tła idą przejęcie zeznania i pochodne (group →
    resolve → calibrate → lineage). Bez tego stan trwał niewidoczny do następnej dostawy."""
    from horreum import presence
    from horreum.resolve.filters import normalize_filter
    from test_orphan_testimony import _cls, _lpro
    monkeypatch.setattr(presence, "volume_serial", lambda p: "VOL1")
    root = tmp_path / "ARCH"
    a = _lpro(root)
    _cls(root)
    path = str(tmp_path / "p.db")
    con = db.open_db(path)
    scan.scan_tree(con, root, volume="VOL1", now=NOW)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(a),)).fetchone()[0]
    con.close()
    os.remove(a)
    w = PipelineWorker(path, now_fn=lambda: NOW)
    w.configure("presence-apply", root=str(root), volume="VOL1", drive_letter=None, tier=None)
    started, done = [], {}
    w.stage_started.connect(started.append)
    w.stage_done.connect(lambda n, r: done.__setitem__(n, r))
    w.run()
    assert started == ["presence", "adopt_testimony", "group", "resolve", "calibrate", "lineage"]
    assert done["presence"].vanished == 1 and done["adopt_testimony"].adopted == 1
    con = db.open_db(path)
    assert con.execute("SELECT filter_canon FROM frame WHERE id = ?",
                       (fid,)).fetchone()[0] == normalize_filter("CLS")
    con.close()
    w2 = PipelineWorker(path, now_fn=lambda: NOW)                # nic nowego: sam pass, bez ogona
    w2.configure("presence-apply", root=str(root), volume="VOL1", drive_letter=None, tier=None)
    started2 = []
    w2.stage_started.connect(started2.append)
    w2.run()
    assert started2 == ["presence"]


def _bez_faktow(con, *paths):
    from test_orphan_testimony import _bez_faktow as _zdejmij
    _zdejmij(con, *paths)


def test_gest_oznacz_znikniete_uzupelnia_fakty_ocalalej_przed_przejeciem(qapp, tmp_path,
                                                                        monkeypatch):
    """Ocalała kopia sprzed 0021 (bez faktów): ogon „Oznacz zniknięte" najpierw dociąga jej fakty,
    dopiero potem pyta o przejęcie - lustro „Przyjmij nowe". Bez faktów predykat zeznania milczy
    („nie wiem"), więc samo przejęcie nie miałoby kandydata, a klatka mówiłaby dalej głosem
    skasowanego pliku."""
    from horreum import presence
    from test_orphan_testimony import _cls, _lpro
    monkeypatch.setattr(presence, "volume_serial", lambda p: "VOL1")
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    path = str(tmp_path / "p.db")
    con = db.open_db(path)
    scan.scan_tree(con, root, volume="VOL1", now=NOW)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(a),)).fetchone()[0]
    _bez_faktow(con, a, b)
    con.close()
    os.remove(a)
    w = PipelineWorker(path, now_fn=lambda: NOW)
    w.configure("presence-apply", root=str(root), volume="VOL1", drive_letter=None, tier=None)
    started, done = [], {}
    w.stage_started.connect(started.append)
    w.stage_done.connect(lambda n, r: done.__setitem__(n, r))
    w.run()
    assert started[:3] == ["presence", "copy_facts", "adopt_testimony"]
    assert done["copy_facts"].written == 1 and done["adopt_testimony"].adopted == 1
    con = db.open_db(path)
    assert con.execute("SELECT filter_raw FROM header WHERE frame_id = ?",
                       (fid,)).fetchone()[0] == "CLS"
    con.close()


def test_droga_Stosy_uzupelnia_fakty_i_przejmuje_zeznanie_pod_swoim_korzeniem(qapp, tmp_path,
                                                                             monkeypatch):
    """„Wciągnij stosy…" to jedyna droga, która dotyka drzewa obróbki - „Przyjmij nowe" chodzi po
    archiwum, a oba etapy są zawężone do korzenia. Kopie stosów sprzed 0021 dostają więc fakty
    i przejęcie zeznania TU, po skanie stosów i przed `group`; kopia spoza korzenia stosów zostaje
    nietknięta. Skan stosów podmieniony (brama przyrostowa i tak pominęłaby kopie bez zmian)."""
    from horreum.gui import pipeline as pipeline_mod
    from test_orphan_testimony import _cls, _lpro
    stosy = tmp_path / "STACKS"
    a, b = _lpro(stosy), _cls(stosy)
    obca = _xisf(tmp_path / "ARCH" / "inna.xisf", _FLAT, payload=b"\x0a" * 32)
    path = str(tmp_path / "p.db")
    con = db.open_db(path)
    scan.scan_tree(con, stosy, volume="?", now=NOW)
    scan.scan_tree(con, tmp_path / "ARCH", volume="?", now=NOW)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(a),)).fetchone()[0]
    _bez_faktow(con, a, b, obca)
    from test_orphan_testimony import _zniknij
    _zniknij(con, a)
    con.close()
    monkeypatch.setattr(pipeline_mod, "scan_stacks", lambda *a, **k: scan.StackScanSummary())
    w = PipelineWorker(path, now_fn=lambda: NOW)
    w.configure("stacks", root=str(stosy), volume="?", drive_letter=None, tier=None)
    started, done = [], {}
    w.stage_started.connect(started.append)
    w.stage_done.connect(lambda n, r: done.__setitem__(n, r))
    w.run()
    assert started == ["stacks", "copy_facts", "adopt_testimony", "group", "resolve",
                       "stack_lineage"]
    assert (done["copy_facts"].rows, done["copy_facts"].written) == (1, 1)
    assert done["adopt_testimony"].adopted == 1
    con = db.open_db(path)
    assert con.execute("SELECT filter_raw FROM header WHERE frame_id = ?",
                       (fid,)).fetchone()[0] == "CLS"
    assert con.execute("SELECT hdr_hash FROM location WHERE path = ?",
                       (str(obca),)).fetchone()[0] is None
    con.close()


def test_wiersz_porzadkow_nie_chowa_klatki_ktora_naprawi_dopiero_Dostawa(qapp, tmp_path):
    """Jedna ocalała kopia i zeznanie spoza ręki - to robota etapu, ale etap chodzi wyłącznie pod
    korzeniem Dostawy (albo stosów). Ocalała poza nim czekałaby niewidoczna do dostawy, której
    nikt nie zrobi, więc wiersz Porządków liczy także te klatki (liczba = lista w Zbiorach)."""
    path, _root, fid = _po_skasowaniu_zrodla(tmp_path)
    con = db.open_db(path)
    try:
        assert [f for f, _k in scan.adopt_candidates(con)] == [fid]
        assert queries.orphan_testimony_frame_ids(con) == {fid}
        assert queries.tasks_state(con)["orphan_testimony_frames"] == 1
    finally:
        con.close()


def test_linia_raportu_liczy_wyscig_osobno(qapp, tmp_path):
    """Werdykt „stan zmienił się w trakcie" nie udaje „zmienione na dysku od skanu" - to fakt
    o bazie, nie o pliku."""
    from horreum.gui.pipeline import PipelineView
    path = str(tmp_path / "p.db")
    db.open_db(path).close()
    v = PipelineView(path, now_fn=lambda: NOW)
    try:
        linia = v._format_result("adopt_testimony", scan.AdoptSummary(rows=1, read=1, raced=1))
        assert "stan zmienił się w trakcie 1" in linia and "zmienione na dysku" not in linia
    finally:
        v.close()
