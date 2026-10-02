"""Widok Pipeline + worker QThread (`horreum.gui.pipeline`, PLAN_gui_pipeline §4/§7). Worker testowany
DWOJAKO: (1) synchronicznie — `run()` wołane wprost, sygnały łapane w listy (kontrakt: progress=dict-
migawka, stage_done/cancelled/failed); (2) integracyjnie w PRAWDZIWYM `QThread` z pętlą zdarzeń —
dowód, że główny wątek nie woła `scan_tree` (R1) i że `running_changed` przełącza się True→False.

`importorskip` na poziomie modułu — bez PySide6 plik się pomija (czyni §7.2 prawdziwym). FS = tmp_path
(logika); firsthand na realnych FITS/XISF = Etap 4."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from astropy.io import fits

from horreum import db
from horreum.gui import i18n
from horreum.gui.pipeline import PipelineView, PipelineWorker

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

NOW = "2026-06-29T15:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _fits(path, n):
    """Czytelny light-FITS o unikalnej treści (data=n → unikalny sha1)."""
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["XPIXSZ"] = 3.76
    hdu.header["IMAGETYP"] = "LIGHT"
    fits.HDUList([hdu]).writeto(str(path))
    return path


def _fresh_db(tmp_path, name="p.db"):
    path = str(tmp_path / name)
    db.open_db(path).close()                        # utwórz+zmigruj; worker otworzy własne połączenie
    return path


def _tree(tmp_path, n=2):
    t = tmp_path / "t"; t.mkdir()
    for i in range(n):
        _fits(t / f"l{i}.fits", i + 1)
    return str(t)


# --- worker: kontrakt sygnałów (synchronicznie) ---

def test_worker_scan_progress_dict_i_stage_done(qapp, tmp_path):
    """≥2 progress (done=1 i done=total), payload progresu to DICT (migawka, nie żywy ScanSummary),
    stage_done niesie ScanSummary z poprawnym frames_new."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("scan", root=_tree(tmp_path, 2), volume="VOL1", drive_letter=None, tier=None)
    prog, done = [], []
    w.progress.connect(lambda d, t, p, c: prog.append((d, t, c)))
    w.stage_done.connect(lambda n, s: done.append((n, s)))
    w.run()
    assert len(prog) >= 2 and all(isinstance(c, dict) for _, _, c in prog)   # snapshot dict
    assert prog[-1][:2] == (2, 2)                                            # domyka na total
    assert done and done[0][0] == "scan" and done[0][1].frames_new == 2


def test_worker_anulowanie_emituje_cancelled(qapp, tmp_path):
    """should_cancel po 1. progresie → cancelled (nie stage_done), summary.cancelled=True, < wszystkich."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("scan", root=_tree(tmp_path, 3), volume="VOL1", drive_letter=None, tier=None)
    cancelled, done = [], []
    w.cancelled.connect(lambda n, s: cancelled.append(s))
    w.stage_done.connect(lambda n, s: done.append(s))
    w.progress.connect(lambda d, t, p, c: w.request_cancel())   # anuluj po pierwszym progresie
    w.run()
    assert not done and cancelled                               # anulowano, nie dokończono
    assert cancelled[0].cancelled is True and cancelled[0].files < 3


def test_worker_blad_etapu_emituje_failed_nie_crash(qapp, tmp_path):
    """Nieznany etap → failed(name, msg), bez wyjątku w górę (apka nie pada)."""
    w = PipelineWorker(_fresh_db(tmp_path), now_fn=lambda: NOW)
    w.configure("bogus")
    failed = []
    w.failed.connect(lambda n, m: failed.append((n, m)))
    w.run()
    assert failed and failed[0][0] == "bogus"


# --- widok: skan w PRAWDZIWYM wątku (R1 — UI nie zamraża) ---

def test_view_skan_w_watku_running_i_summary(qapp, tmp_path):
    """Worker w QThread: główny wątek NIE woła scan_tree; po etapie panel ScanSummary wypełniony,
    a running_changed przeszło True→False (pętla kończy się na False = po sprzątnięciu wątku)."""
    db_path = _fresh_db(tmp_path)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 2)                    # serial policzy się ŚWIEŻO w _scan_params (F5)
    running = []
    loop = QEventLoop()
    view.running_changed.connect(running.append)
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(15000, loop.quit)                # bezpiecznik, gdyby coś zawisło
    view._on_scan()
    assert view._thread is not None                    # skan ruszył w wątku (nie synchronicznie)
    loop.exec()
    assert running and running[0] is True and running[-1] is False
    assert "[skan] pliki 2" in view.lbl_summary.text() and "nowe 2" in view.lbl_summary.text()
    assert view._thread is None                        # wątek sprzątnięty


# --- worker: etapy masowe group/resolve/delta + łańcuch „all" (synchronicznie) ---

def _scanned_db(tmp_path):
    """Baza z zeskanowanym małym drzewem (wejście dla group/resolve/delta)."""
    from horreum.scan import scan_tree
    db_path = _fresh_db(tmp_path)
    con = db.open_db(db_path)
    scan_tree(con, _tree(tmp_path, 2), volume="VOL1", now=NOW)
    con.close()
    return db_path


def test_worker_group_resolve_delta_emituja_stage_done(qapp, tmp_path):
    """Etapy masowe wołają funkcje rdzenia i niosą właściwy typ wyniku w stage_done."""
    from horreum.calibration import CalibrationSummary
    from horreum.grouper import GroupSummary
    from horreum.lineage import LineageSummary
    from horreum.resolver import DeltaReport, ResolveSummary
    db_path = _scanned_db(tmp_path)
    for stage, typ in [("group", GroupSummary), ("resolve", ResolveSummary),
                       ("calibrate", CalibrationSummary), ("lineage", LineageSummary),
                       ("delta", DeltaReport)]:
        w = PipelineWorker(db_path, now_fn=lambda: NOW)
        w.configure(stage)
        done, started = [], []
        w.stage_started.connect(lambda n: started.append(n))
        w.stage_done.connect(lambda n, r: done.append((n, r)))
        w.run()
        assert started == [stage]
        assert done and done[0][0] == stage and isinstance(done[0][1], typ)


def test_worker_all_lancuch_scan_group_resolve_delta_obecnosc(qapp, tmp_path):
    """„Przetwórz wszystko": jeden worker emituje stage_done dla scan→group→resolve→calibrate→
    lineage→delta→obecność w kolejności, a `finished` pada raz na końcu (sygnał do quit wątku).
    Kalibracja stoi PO resolverze (przepis flata bierze `frame.filter_canon`, który wypełnia dopiero
    resolver), rodowód PO kalibracji (dopasowuje do wyłonionych profili), oba PRZED deltą. Obecność
    zamyka sekwencję, bo raport dostawy ma mówić także o tym, co z drzewa ZNIKNĘŁO —
    zawsze w DRY (zapis = osobny gest).

    Tu wolumin jest zmyślony („VOL1"), więc pass poprawnie ABORCIUJE na guardzie serialu — sekwencja
    leci dalej, a nie wywala się: przesłanka nie do potwierdzenia to nie błąd etapu."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("all", root=_tree(tmp_path, 2), volume="VOL1", drive_letter=None, tier=None)
    order, fin, wyniki = [], [], {}
    w.stage_done.connect(lambda n, r: (order.append(n), wyniki.__setitem__(n, r)))
    w.finished.connect(lambda: fin.append(1))
    w.run()
    assert order == ["scan", "group", "resolve", "calibrate", "lineage", "delta", "presence"]
    assert wyniki["presence"].aborted is not None and wyniki["presence"].vanished == 0
    assert len(fin) == 1


def test_worker_all_bez_serialu_melduje_pominiecie_obecnosci(qapp, tmp_path):
    """Wolumin '?' (serial nieustalony) → pass NIE leci (bez trwałej kotwicy zakresu nie ma czego
    potwierdzać), ale etap MELDUJE pominięcie. Cisza czytałaby się jak „sprawdzone, nic nie znikło",
    a to jest „nie sprawdzone" — dokładnie ta różnica, dla której pass w ogóle powstał."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("all", root=_tree(tmp_path, 2), volume="?", drive_letter=None, tier=None)
    order, wyniki = [], {}
    w.stage_done.connect(lambda n, r: (order.append(n), wyniki.__setitem__(n, r)))
    w.run()
    assert order == ["scan", "group", "resolve", "calibrate", "lineage", "delta", "presence"]
    s = wyniki["presence"]
    assert "pominięty" in s.aborted and s.walked == 0 and s.vanished == 0


def test_worker_all_anulowanie_przerywa_lancuch(qapp, tmp_path):
    """Anulowanie skanu w „all" → cancelled(scan) i ŻADEN dalszy etap się nie wykonuje."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("all", root=_tree(tmp_path, 3), volume="VOL1", drive_letter=None, tier=None)
    done, cancelled = [], []
    w.stage_done.connect(lambda n, r: done.append(n))
    w.cancelled.connect(lambda n, r: cancelled.append(n))
    w.progress.connect(lambda d, t, p, c: w.request_cancel())
    w.run()
    assert cancelled == ["scan"] and "group" not in done    # łańcuch przerwany


# --- widok: bramkowanie przycisków + pełny „Przetwórz wszystko" w wątku ---

def test_gating_przyciskow_wymaga_bazy_i_katalogu(qapp, tmp_path):
    """all/scan wymagają bazy ORAZ katalogu; group/resolve/kalibracja/delta — samej bazy; „Przyjmij
    nowe" samej bazy (katalog przynosi własny, F5); anuluj wyłączony w spoczynku."""
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert not view.btn_all.isEnabled() and not view.btn_scan.isEnabled()   # brak katalogu
    assert view.btn_receive.isEnabled()                                     # F5: baza wystarcza
    assert view.btn_group.isEnabled() and view.btn_resolve.isEnabled() and view.btn_delta.isEnabled()
    assert view.btn_calibrate.isEnabled()                                   # oś przepisu: sama baza
    assert not view.btn_cancel.isEnabled()
    view._root = _tree(tmp_path, 1); view._sync_actions()
    assert view.btn_all.isEnabled() and view.btn_scan.isEnabled()           # katalog wskazany


def test_pasek_ukryty_w_spoczynku_blad_w_osobnym_wierszu(qapp, tmp_path):
    """Wizytator P2: w spoczynku pasek UKRYTY (nie kłamie „0%"); błąd etapu ląduje w OSOBNYM
    czerwonym wierszu (`lbl_error`), nie ginie w panelu summary."""
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert view.bar.isHidden()                           # idle: pasek schowany (intencja, nie zależy od show())
    assert view.lbl_error.isHidden()
    view._on_failed("scan", "PermissionError: brak dostępu")
    assert not view.lbl_error.isHidden() and "BŁĄD" in view.lbl_error.text()
    assert "scan" not in view.lbl_summary.text()         # błąd NIE zaśmieca panelu wyników


def test_linia_skanu_melduje_PRZEBIEG_NIEKOMPLETNY(qapp, tmp_path):
    """E4-6: zerwany share w połowie archiwum dawał linię raportu nie do odróżnienia od zdrowego
    doskanu, w którym nic nie przybyło — same niższe liczby. GUI jest JEDYNĄ powierzchnią użytkową
    (wydanie onefile nie ma CLI), więc naprawa żyjąca w konsoli nie naprawia nic dla człowieka,
    który patrzy na ekran. Para z falsyfikatorem: zdrowy przebieg milczy (QUIET)."""
    from horreum.scan import ScanSummary
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    zdrowy = ScanSummary(files=2, frames_new=2)
    assert "NIEKOMPLETNY" not in view._format_result("scan", zdrowy)
    niepelny = ScanSummary(files=2, frames_new=2, unreadable_dirs=[r"R:\ASTRO_\LIGHTS\CTB1"])
    assert "NIEKOMPLETNY" in view._format_result("scan", niepelny)


def test_view_przetworz_wszystko_w_watku(qapp, tmp_path):
    """Pełny łańcuch z okna w PRAWDZIWYM wątku: panel akumuluje 5 sekcji (skan/grupuj/rozwiąż/
    kalibracja/delta), running wraca do False po sprzątnięciu."""
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 2)                    # serial policzy się ŚWIEŻO w _scan_params (F5)
    running = []
    loop = QEventLoop()
    view.running_changed.connect(running.append)
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_all()
    loop.exec()
    txt = view.lbl_summary.text()
    assert "[skan]" in txt and "[grupuj]" in txt and "[rozwiąż]" in txt and "[delta]" in txt
    assert "[kalibracja]" in txt
    assert running[0] is True and running[-1] is False and view._thread is None


# --- F5 (Dostawa): świeży serial, „Przyjmij nowe", guard mieszania serialu ---

def test_serial_liczony_swiezo_w_watku_tla_na_starcie_skanu(qapp, tmp_path, monkeypatch):
    """R#7+R2-3: wartość do bramy `(volume,path,mtime)` ZAWSZE ze startu przebiegu - nigdy
    z montażu/pamięci (stale po przepięciu dysku w trakcie sesji). AR-31 (3): mierzy ją wątek
    tła (`_zrodlo`), więc parametry okna woluminu w ogóle nie niosą, a wynik pomiaru wraca do
    okna sygnałem `source_ready` i ląduje w lokacjach skanu."""
    import horreum.gui.pipeline as pl
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    tree = _tree(tmp_path, 1)
    assert "volume" not in view._scan_params(tree)     # okno nie mierzy serialu
    for serial, oczekiwany in (("FRESH", "FRESH"), (None, "?")):   # nieustalony → '?' (pełny skan)
        monkeypatch.setattr(pl, "volume_serial", lambda p, _s=serial: _s)
        db_path = _fresh_db(tmp_path, name=f"s{oczekiwany == '?'}.db")
        w = PipelineWorker(db_path, now_fn=lambda: NOW)
        w.configure("scan", **view._scan_params(tree))
        gotowe = []
        w.source_ready.connect(lambda r, v: gotowe.append((r, v)))
        w.run()
        assert gotowe == [(tree, oczekiwany)]
        con = db.open_db(db_path)
        assert {r[0] for r in con.execute("SELECT volume FROM location")} == {oczekiwany}
        con.close()


def test_receive_z_pamiecia_startuje_cala_sekwencje(qapp, tmp_path, monkeypatch, ustawienia):
    """„Przyjmij nowe" z zapamiętanym źródłem (D-UX-5): zero pytań, cała sekwencja „all"."""
    tree = _tree(tmp_path, 2)
    ustawienia.setValue("pipeline/last_source", tree)
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    running = []
    loop = QEventLoop()
    view.running_changed.connect(running.append)
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_receive()
    assert view._thread is not None                    # ruszyło bez pytania o katalog
    loop.exec()
    txt = view.lbl_summary.text()
    assert "[skan]" in txt and "[delta]" in txt        # cała sekwencja
    assert view._root == tree and ustawienia.value("pipeline/last_source") == tree


def test_receive_bez_pamieci_pyta_zapisuje_i_syncuje_memo(qapp, tmp_path, monkeypatch, ustawienia):
    """Pierwsza dostawa: pytanie o katalog, zapis pamięci, memo z JEDNEJ funkcji (F5R#10/R2#6)."""
    tree = _tree(tmp_path, 1)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: tree))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert "pierwsza dostawa" in view.lbl_source_memo.text()
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_receive()
    loop.exec()
    assert ustawienia.value("pipeline/last_source") == tree
    assert tree in view.lbl_source_memo.text()


def test_receive_anulowany_dialog_nie_startuje(qapp, tmp_path, monkeypatch, ustawienia):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._on_receive()
    assert view._thread is None                        # anuluj → nic nie rusza


def test_pick_dir_zapisuje_last_source(qapp, tmp_path, monkeypatch, ustawienia):
    """D-UX-5: jedna pamięć ostatniego katalogu — „Wskaż katalog…" też ją zapisuje."""
    tree = _tree(tmp_path, 1)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: tree))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._on_pick_dir()
    assert ustawienia.value("pipeline/last_source") == tree and tree in view.lbl_source_memo.text()


def test_serial_guard_wstrzymuje_skan_mieszany(qapp, tmp_path, monkeypatch):
    """F5R#3: serial '?' do bazy znającej realny wolumen = STOP przed pierwszym plikiem (skan '?' by
    PODWOIŁ lokacje każdej znanej klatki - brama nie trafi, UNIQUE(volume,path) wpuści drugą).
    AR-31 (3): serial mierzy wątek tła, więc i guard stoi tam - wstrzymanie wraca `start_refused`
    i okno pokazuje je tym samym wierszem błędu; baza bez nowej lokacji, raport bez linii skanu."""
    import horreum.gui.pipeline as pl
    from horreum import repo
    db_path = _fresh_db(tmp_path)
    con = db.open_db(db_path)
    fid, _ = repo.upsert_frame(con, sha1_data="sha-g", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.add_location(con, frame_id=fid, volume="VOL1", path="/x/g.fits", now=NOW)
    con.close()
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 1)
    monkeypatch.setattr(pl, "volume_serial", lambda p: None)
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(15000, loop.quit)
    view._on_scan()
    loop.exec()
    assert not view.lbl_error.isHidden() and "wolumen nieustalony" in view.lbl_error.text()
    assert "[skan]" not in view.lbl_summary.text()
    con = db.open_db(db_path)
    assert con.execute("SELECT COUNT(*) FROM location").fetchone()[0] == 1   # tylko VOL1
    con.close()


def test_serial_guard_przepuszcza_czysty_swiat(qapp, tmp_path, monkeypatch):
    """Czysty świat '?' (baza bez realnych wolumenów — np. nie-Windows) skanuje jak dziś."""
    import horreum.gui.pipeline as pl
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 1)
    monkeypatch.setattr(pl, "volume_serial", lambda p: None)
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(15000, loop.quit)
    view._on_scan()
    assert view._thread is not None
    loop.exec()
    assert "[skan] pliki 1" in view.lbl_summary.text()


# --- P5b: pass obecności w Dostawie (DRY → jawny zapis → droga do perspektywy) ---

def _czekaj_na_etap(view, timeout_ms=20000):
    if not hasattr(view, "status_message_ostatni"):
        view.status_message_ostatni = ""
        view.status_message.connect(
            lambda m: setattr(view, "status_message_ostatni", m))
    """Odczekaj etap w wątku: pętla kończy się na running_changed(False) — czyli PO sprzątnięciu."""
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_obecnosc_dry_pokazuje_przycisk_a_zapis_droge_do_perspektywy(qapp, tmp_path):
    """P5b: DRY tylko RAPORTUJE i odsłania „Oznacz zniknięte"; dopiero jawny klik zapisuje, a wtedy
    przycisk zapisu znika (nie ma już czego oznaczać) i wchodzi droga 3→1 do perspektywy Zbiorów.

    Ta sekwencja jest sercem P5b: sekwencja dostawy NIGDY nie zdejmuje obecności sama."""
    from horreum.gui.grid import PRESET_VANISHED
    db_path = _fresh_db(tmp_path)
    root = _tree(tmp_path, 3)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = root
    view._on_scan()
    _czekaj_na_etap(view)
    os.remove(str(Path(root) / "l1.fits"))

    view._on_presence()                                   # DRY
    _czekaj_na_etap(view)
    # `isVisible()` na widoku, który nigdy nie dostał show(), jest ZAWSZE False — pytamy o intencję
    # widżetu (`isHidden`), tak jak reszta testów okna (wzorzec `empty_note`).
    assert not view.box_vanished.isHidden() and not view.btn_mark_vanished.isHidden()
    assert view.btn_show_vanished.isHidden()
    assert view.lbl_vanished.text().startswith("Zniknęła 1 kopia")   # odmiana, nie szablon
    con = db.open_db(db_path)
    assert con.execute("SELECT COUNT(*) FROM location WHERE present = 0").fetchone()[0] == 0
    con.close()

    perspektywy = []
    view.open_collection.connect(perspektywy.append)
    view._on_mark_vanished()                              # jawny zapis
    _czekaj_na_etap(view)
    assert view.lbl_vanished.text().startswith("Oznaczono 1 kopię")
    assert not view.btn_show_vanished.isHidden() and view.btn_mark_vanished.isHidden()
    con = db.open_db(db_path)
    assert con.execute("SELECT COUNT(*) FROM location WHERE present = 0").fetchone()[0] == 1
    con.close()
    view.btn_show_vanished.click()
    assert perspektywy == [PRESET_VANISHED]


def test_obecnosc_bez_zniknieć_nie_pokazuje_sekcji(qapp, tmp_path):
    """QUIET: gdy nic nie znikło, sekcja akcji zostaje UKRYTA, a fakt idzie jedną linią do panelu —
    pusty widżet „0 zniknięć" byłby stałym szumem w Dostawie."""
    db_path = _fresh_db(tmp_path)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 2)
    view._on_scan()
    _czekaj_na_etap(view)
    view._on_presence()
    _czekaj_na_etap(view)
    assert view.box_vanished.isHidden()
    assert not view.btn_mark_vanished.isEnabled()          # nie ma zamrożonych parametrów
    assert "nic nie znikło" in view.lbl_summary.text()


def test_anulowanie_obecnosci_melduje_zamiast_wywalac_slot(qapp, tmp_path, monkeypatch):
    """P1 (wizytator P5 #1): anulować da się KAŻDY przerywalny etap, nie tylko skan. `_on_cancelled`
    formatował twardo `[skan]` i czytał `summary.files`, którego `PresenceSummary` nie ma → slot padał
    AttributeError, panel zostawał PUSTY, pasek na 0%, a status „Anulowanie…" na wieki. Baza była
    bezpieczna — user nie miał jak się o tym dowiedzieć."""
    from horreum import presence as presence_mod
    db_path = _fresh_db(tmp_path)
    root = _tree(tmp_path, 3)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = root
    view._on_scan()
    _czekaj_na_etap(view)
    for n in ("l0.fits", "l1.fits"):        # JEDEN plik zostaje — inaczej hamulec „drzewo puste"
        os.remove(str(Path(root) / n))       # zatrzymałby pass przed pętlą potwierdzeń

    prawdziwe = presence_mod.path_gone

    def wolno(p):                                      # imitacja zerwanego SMB: anuluj w trakcie
        view._worker.request_cancel()
        return prawdziwe(p)

    monkeypatch.setattr(presence_mod, "path_gone", wolno)
    view._on_presence()
    _czekaj_na_etap(view)
    assert "[obecność] przerwane przez użytkownika" in view.lbl_summary.text()
    assert "przerwany" in view.status_message_ostatni
    assert view.box_vanished.isHidden()                # nic nie potwierdzono → nie ma czego oznaczać
    con = db.open_db(db_path)
    assert con.execute("SELECT COUNT(*) FROM location WHERE present = 0").fetchone()[0] == 0
    con.close()


# --- i18n: EN renderuje z katalogu (§4 rollout `pipeline`) ---

def test_en_render_pipeline_z_katalogu(qapp, tmp_path):
    """§5 (rollout pipeline): `set_lang('en')` PRZED budową → etykiety przycisków/paneli (stałe
    _TIERS/_STAGE_LABEL trzymają KLUCZE) ORAZ raport dostawy (`_format_*` sklejany z katalogu)
    renderują EN. Pełny łańcuch w PRAWDZIWYM wątku dowodzi obu warstw naraz. Autouse-fixture
    `_reset_i18n_lang` wraca na PL — bez skażenia baterii (raport off-thread czyta stały `_lang`)."""
    i18n.set_lang("en")
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    # build-time: stałe rozwiązane z katalogu, nie zamrożony PL
    assert view.btn_receive.text().startswith("Take new")
    assert view.btn_scan.text() == "Scan" and view.btn_all.text() == "Process all"
    assert view.combo_tier.itemText(1) == "cold (archive)"     # _TIERS[1] klucz → EN
    view._root = _tree(tmp_path, 2)
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_all()
    loop.exec()
    txt = view.lbl_summary.text()
    assert "[scan]" in txt and "[group]" in txt and "[delta]" in txt   # tagi raportu EN
    assert "files 2" in txt and "object" in txt                       # wkład tekstowy EN


def test_run_stage_fasada_zwraca_powod_odmowy(qapp, tmp_path):
    """D-PD-6: `run_stage` to PUBLICZNE wejście w etap masowy dla powierzchni spoza tego widoku
    (okno „Napraw nagłówek…" po zapisie kart). Zwraca POWÓD odmowy, nie goły `False`: jedna bramka
    łączy dwa różne stany („brak bazy" i „etap w biegu"), więc bool mógłby skłamać. Pięć slotów
    masowych deleguje TU — jeden dom bramki zamiast pięciu kopii."""
    view = PipelineView(None, now_fn=lambda: NOW)
    assert "baz" in view.run_stage("resolve")                 # bez bazy: powód, nie wystartowanie

    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    started = []
    view._start_stage = lambda stage, **kw: started.append((stage, kw))
    assert view.run_stage("resolve") is None and started == [("resolve", {})]

    # etap w biegu → odmowa z powodem; slot masowy dziedziczy tę samą bramkę (delegacja)
    view._thread = object()
    assert "biegu" in view.run_stage("resolve")
    view._on_group()
    assert started == [("resolve", {})]                       # nic nowego nie ruszyło
    view._thread = None
    view._on_group()
    assert started[-1] == ("group", {})


# --- droga „Stosy" (I-2b): własny korzeń, własna pamięć, poza sekwencją dostawy ---

def _stack_xisf(path, n, imagetyp="Master Light"):
    """Minimalny monolityczny XISF z `IMAGETYP` i unikalną treścią (attachment) → własny sha1."""
    import struct
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
        '<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:%d:32">'
        '<FITSKeyword name="IMAGETYP" value="\'%s\'" comment=""/>'
        '<FITSKeyword name="INSTRUME" value="\'ZWO ASI2600MM Pro\'" comment=""/>'
        '<FITSKeyword name="XPIXSZ" value="3.76" comment=""/>'
        '</Image></xisf>'
    )
    body = xml % (0, imagetyp)
    raw = body.encode("utf-8")
    offset = 16 + len(raw)
    raw = (xml % (offset, imagetyp)).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(b"XISF0100")
        fh.write(struct.pack("<I", len(raw)))
        fh.write(b"\x00\x00\x00\x00")
        fh.write(raw)
        fh.write(bytes([n]) * 32)
    return path


def _stack_tree(tmp_path, n=2):
    t = tmp_path / "obrobka"
    t.mkdir()
    for i in range(n):
        _stack_xisf(t / f"masterLight_{i}.xisf", i + 1)
    return str(t)


def test_worker_stacks_emituje_stage_done(qapp, tmp_path):
    """Kontrakt sygnałów etapu „stosy" identyczny ze skanem: progres per plik + `stage_done`
    z podsumowaniem drogi (nie ze `ScanSummary` — droga ma własne pytania).

    Od I-2d droga DOMYKA ŁAŃCUCH (`group` → `resolve` → `stack_lineage`), więc etapów jest cztery:
    sam skan zostawiłby stosy bez osi i bez rodowodu, a „wciągnąłem" znaczyłoby mniej, niż user
    widzi na ekranie. Kolejność jest częścią kontraktu — rodowód stoi PO obu osiach, bo dobór okna
    stoi na obiekcie i teleskopie."""
    tree = _stack_tree(tmp_path)
    w = PipelineWorker(_fresh_db(tmp_path), now_fn=lambda: NOW)
    w.configure("stacks", root=tree, volume="VOL1")
    done, prog = [], []
    w.stage_done.connect(lambda name, s: done.append((name, s)))
    w.progress.connect(lambda d, t, p, c: prog.append((d, t, dict(c))))
    w.run()
    assert [n for n, _ in done] == ["stacks", "group", "resolve", "stack_lineage"]
    s = done[0][1]
    assert (s.candidates, s.ingested) == (2, 2)
    assert done[-1][1].stacks == 2                     # rodowód zobaczył OBA wciągnięte stosy
    assert prog and isinstance(prog[-1][2], dict)      # migawka DICT, nie żywy summary


def test_rodowod_stosow_liczy_sie_BEZ_skanu_i_BEZ_pytania_o_katalog(qapp, tmp_path, monkeypatch):
    """FIRSTHAND ZDZINIA 0808: „«Wciągnij stosy» jest bez sensu dla usera, skoro już wciągał raz".

    Rodowód stosów zależy od faktów, które człowiek nadaje MIĘDZY przebiegami (obiekt, zestaw,
    odniesienie czasu), więc po każdym geście trzeba go przeliczyć. Jedyną drogą było dotąd
    ponowne wciągnięcie CAŁEGO drzewa obróbki — z pytaniem o korzeń, który user już raz wskazał.
    Do tego przycisk o mylącej nazwie: „Rodowód" w rzędzie etapów liczy oś KALIBRACJI, więc cztery
    kliknięcia poszły w etap, który działał poprawnie i robił co innego (zmierzone na żywej bazie:
    4× `calibration.lineage_summary`, 0× `integration.lineage_summary`).

    Test pilnuje OBU połówek naprawy: etap liczy sam rodowód (`stack_lineage`, bez `stacks`)
    i NIE OTWIERA dialogu katalogu — to drugie jest sednem zarzutu, więc ma własną asercję."""
    from PySide6.QtWidgets import QFileDialog

    pytano = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: pytano.append(a) or "")
    w = PipelineWorker(_fresh_db(tmp_path), now_fn=lambda: NOW)
    w.configure("stack_lineage")
    done = []
    w.stage_done.connect(lambda name, s: done.append((name, s)))
    w.run()
    assert [n for n, _ in done] == ["stack_lineage"], "sam rodowód, bez skanu drzewa"

    view = PipelineView(_fresh_db(tmp_path))
    view._on_stack_lineage()
    assert pytano == [], "etap NIE ma prawa pytać o katalog — liczy z tego, co jest w bazie"
    view.close()


def test_dwa_rodowody_maja_ROZNE_nazwy(qapp):
    """Etykiety dwóch różnych osi nie mogą być tym samym słowem. Przed 0808 obie brzmiały
    „Rodowód" — jedna w rzędzie etapów (kalibracja), druga jako panel klatki (stosy) — i user
    kliknął czterokrotnie nie tę. Bramka pilnuje rozłączności, nie konkretnego brzmienia."""
    kal = i18n.t("pipeline.btn.lineage")
    stos = i18n.t("pipeline.btn.stack_lineage")
    assert kal != stos and kal and stos
    assert "kalibracj" in kal.lower(), "etap kalibracji ma się nazwać kalibracją"
    assert "stos" in stos.lower(), "etap stosów ma się nazwać stosami"


def test_stacks_pamieta_korzen_i_podpowiada_go(qapp, tmp_path, monkeypatch, ustawienia):
    """Korzeń drogi jest ZAPAMIĘTYWANY (`stacks/last_root`, QSettings per maszyna) i PODPOWIADANY
    przy kolejnym uruchomieniu — dialog dostaje go jako katalog startowy. Osobna pamięć od
    `pipeline/last_source`: to inny korzeń i inny gest, więc jedna pamięć kłamałaby na przemian
    o obu."""
    tree = _stack_tree(tmp_path)
    from PySide6.QtWidgets import QFileDialog
    widziane = []

    def _dlg(_parent, _title, start=""):
        widziane.append(start)
        return tree

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(_dlg))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert "jeszcze nie wskazano" in view.lbl_stacks_memo.text()
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_stacks()
    loop.exec()
    assert ustawienia.value("stacks/last_root") == tree
    assert tree in view.lbl_stacks_memo.text()
    assert widziane == [""]                            # pierwszy raz: brak podpowiedzi
    view._on_stacks()                                  # drugi raz: dialog startuje OD zapamiętanego
    assert widziane[-1] == tree
    assert not ustawienia.contains("pipeline/last_source")   # pamięci są ROZDZIELNE


def test_stacks_anulowany_dialog_nie_startuje(qapp, tmp_path, monkeypatch, ustawienia):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._on_stacks()
    assert view._thread is None


def test_stacks_poza_sekwencja_przyjmij_nowe(qapp, tmp_path):
    """D-P-I-1: droga „Stosy" jest OSOBNA — „Przetwórz wszystko" jej NIE woła. Gdyby wpadła do
    łańcucha dostawy, codzienny skan sięgałby do drzewa obróbki bez pytania, a to jest inny
    zakres i inna odwracalność."""
    tree = _tree(tmp_path, 1)
    w = PipelineWorker(_fresh_db(tmp_path), now_fn=lambda: NOW)
    w.configure("all", root=tree, volume="VOL1")
    etapy = []
    w.stage_done.connect(lambda name, s: etapy.append(name))
    w.run()
    assert "stacks" not in etapy


def test_stacks_przycisk_wymaga_samej_bazy(qapp, tmp_path):
    """Stosy przynoszą WŁASNY korzeń (dialog), więc — jak „Przyjmij nowe" — nie zależą od katalogu
    trybu zaawansowanego. Bez bazy przycisk jest szczerze wygaszony."""
    view = PipelineView(None, now_fn=lambda: NOW)
    assert view.btn_stacks.isEnabled() is False
    view2 = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert view2.btn_stacks.isEnabled() is True        # mimo braku wskazanego katalogu
    assert view2.btn_scan.isEnabled() is False         # …a skan wymaga katalogu


def _szpieg_dysku(monkeypatch, fragment):
    """Lista dotknięć dysku W WĄTKU OKNA na ścieżkach zawierających `fragment` (wzorzec testów
    AR-31 (3) w `test_gui_izolacja_zapisu.py`): `isdir`, `exists`, `stat`, `Path.is_dir`, serial
    woluminu i kanonizacja korzenia. Wątek tła dotyka dysku legalnie - nie jest liczony."""
    import threading
    import horreum.gui.pipeline as pl
    from horreum import scan
    w_oknie = []

    def _szpieg(nazwa, prawdziwa):
        def _f(sciezka, *a, **kw):
            if (threading.current_thread() is threading.main_thread()
                    and fragment in str(sciezka)):
                w_oknie.append((nazwa, str(sciezka)))
            return prawdziwa(sciezka, *a, **kw)
        return _f
    monkeypatch.setattr(os.path, "isdir", _szpieg("isdir", os.path.isdir))
    monkeypatch.setattr(os.path, "exists", _szpieg("exists", os.path.exists))
    monkeypatch.setattr(os, "stat", _szpieg("stat", os.stat))
    monkeypatch.setattr(Path, "is_dir", _szpieg("Path.is_dir", Path.is_dir))
    monkeypatch.setattr(pl, "volume_serial", _szpieg("volume_serial", pl.volume_serial))
    monkeypatch.setattr(scan, "canonize_root", _szpieg("canonize_root", scan.canonize_root))
    return w_oknie


# --- droga „Stosy": serial i guard w wątku tła (AR-31 (3)) ---

def test_stosy_nie_dotykaja_dysku_w_oknie_i_nie_zmieniaja_zrodla(qapp, tmp_path, monkeypatch,
                                                                   ustawienia):
    """AR-31 (3), bliźniak „Przyjmij nowe": `_on_stacks` mierzył `volume_serial` korzenia stosów
    w slocie okna zaraz po dialogu - na odłączonym udziale SMB okno stało do timeoutu sieci. Teraz
    slot podaje sam napis ścieżki, a serial i guard mieszania robi wątek tła. Korzeń stosów NIE
    zostaje wskazanym katalogiem trybu zaawansowanego (to drzewo obróbki, nie źródło archiwum).

    Falsyfikator: przywróć w `_on_stacks` `volume_serial(root)` → lista dotknięć nie jest pusta;
    zdejmij `wskaz=False` w `_stacks` → `_root` dostaje korzeń stosów."""
    from PySide6.QtWidgets import QFileDialog
    tree = _stack_tree(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: tree))
    w_oknie = _szpieg_dysku(monkeypatch, "obrobka")
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    try:
        view._on_stacks()
        assert w_oknie == [], w_oknie
        assert view._thread is not None
        _czekaj_na_etap(view)
        assert "[stosy] wciągnięte 2 z 2" in view.lbl_summary.text(), view.lbl_summary.text()
        assert view._root is None and view.lbl_root.text() == i18n.t("pipeline.root_none")
        assert ustawienia.value("stacks/last_root") == tree
        assert w_oknie == [], w_oknie
    finally:
        view.close()


def test_stosy_na_niedostepnym_korzeniu_wracaja_stanem_i_pytaja_znow_o_korzen(
        qapp, tmp_path, monkeypatch, ustawienia):
    """Korzeń stosów, którego wątek tła nie widzi jako katalogu: własna linia „[stosy] NIE
    WYKONANO", zdanie „Źródło niedostępne - wskaż katalog" z przyciskiem, a przycisk pyta znów
    o korzeń STOSÓW (dialog z `stacks/last_root`), nie o źródło archiwum."""
    from PySide6.QtWidgets import QFileDialog
    brak = str(tmp_path / "odlaczony" / "obrobka")
    tree = _stack_tree(tmp_path)
    odpowiedzi = [brak, tree]
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: odpowiedzi.pop(0)))
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    try:
        view._on_stacks()
        _czekaj_na_etap(view)
        linia = i18n.t("pipeline.fmt.stacks_not_done",
                       reason=i18n.t("pipeline.source.unreachable", root=brak))
        assert view.lbl_summary.text() == linia, view.lbl_summary.text()
        assert not view.btn_pick_source.isHidden() and view.btn_pick_source.isEnabled()
        view.btn_pick_source.click()
        assert odpowiedzi == [] and view._thread is not None
        _czekaj_na_etap(view)
        assert "[stosy] wciągnięte 2 z 2" in view.lbl_summary.text(), view.lbl_summary.text()
        assert ustawienia.value("stacks/last_root") == tree
        assert not ustawienia.contains("pipeline/last_source")
    finally:
        view.close()


def test_stosy_guard_mieszania_serialu_w_watku_tla(qapp, tmp_path, monkeypatch, ustawienia):
    """F5R#3 dla drogi „Stosy": serial '?' do bazy znającej realny wolumen = STOP przed pierwszym
    plikiem. Guard przeszedł z okna do wątku tła razem z pomiarem serialu - wstrzymanie wraca
    `start_refused` tym samym wierszem błędu, baza bez nowej lokacji."""
    import horreum.gui.pipeline as pl
    from horreum import repo
    from PySide6.QtWidgets import QFileDialog
    db_path = _fresh_db(tmp_path)
    con = db.open_db(db_path)
    fid, _ = repo.upsert_frame(con, sha1_data="sha-g", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.add_location(con, frame_id=fid, volume="VOL1", path="/x/g.fits", now=NOW)
    con.close()
    tree = _stack_tree(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: tree))
    monkeypatch.setattr(pl, "volume_serial", lambda p: None)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        view._on_stacks()
        assert view._thread is not None                 # okno nie rozstrzyga - wątek tła
        _czekaj_na_etap(view)
        assert not view.lbl_error.isHidden() and "wolumen nieustalony" in view.lbl_error.text()
        assert "[stosy]" not in view.lbl_summary.text()
        con = db.open_db(db_path)
        assert con.execute("SELECT COUNT(*) FROM location").fetchone()[0] == 1
        con.close()
    finally:
        view.close()


# --- gest „Zbierz fakty kopii (N)": dwa etapy łańcucha bez skanu ---

def _kopie_bez_faktow(tmp_path):
    """Jedna klatka, dwie kopie FITS wciągnięte BEZ faktów kopii (jak sprzed 0021) - obie są
    kandydatami `scan.copy_facts_candidates`. Zwraca (ścieżka bazy, katalog kopii)."""
    from horreum import repo, scan
    kat = tmp_path / "kopie"
    kat.mkdir()
    db_path = _fresh_db(tmp_path)
    con = db.open_db(db_path)
    for nazwa in ("a.fits", "b.fits"):
        rec = scan.scan_file(str(_fits(kat / nazwa, 7)))
        fid, _ = repo.upsert_frame(con, sha1_data=rec.sha1_data, kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=rec.path,
                          header_hash=rec.header_hash, now=NOW)
    con.close()
    return db_path, str(kat)


def _bez_faktow(db_path):
    con = db.open_db(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM location WHERE hdr_hash IS NULL").fetchone()[0]
    finally:
        con.close()


def test_gest_fakty_kopii_widoczny_tylko_gdy_jest_co_zbierac(qapp, tmp_path):
    """Przycisk „Zbierz fakty kopii (N)" stoi obok złotej akcji WYŁĄCZNIE przy N > 0, z liczbą
    z tego samego predykatu co wiersz „?" w Porządkach (bez korzenia). Po przebiegu znika.

    Falsyfikator: zdejmij `setVisible(n > 0)` z `_sync_copy_facts` → pierwsza asercja pada."""
    pusta = PipelineView(_fresh_db(tmp_path, name="pusta.db"), now_fn=lambda: NOW)
    bez_bazy = PipelineView(None, now_fn=lambda: NOW)
    try:
        assert pusta.btn_copy_facts.isHidden() and not pusta.btn_copy_facts.isEnabled()
        assert bez_bazy.btn_copy_facts.isHidden()
    finally:
        pusta.close()
        bez_bazy.close()
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert not view.btn_copy_facts.isHidden() and view.btn_copy_facts.isEnabled()
        assert view.btn_copy_facts.text() == i18n.t("pipeline.btn.copy_facts", n=2)
        assert view.btn_copy_facts.toolTip() == i18n.t_plural("pipeline.tip.copy_facts", 2)
        view.btn_copy_facts.click()
        _czekaj_na_etap(view)
        assert _bez_faktow(db_path) == 0, (view.lbl_summary.text(), view.lbl_error.text())
        assert view.btn_copy_facts.isHidden() and not view.btn_copy_facts.isEnabled()
    finally:
        view.close()


def test_gest_fakty_kopii_woła_dokladnie_fakty_i_przejecie_bez_skanu(qapp, tmp_path, monkeypatch):
    """Gest idzie drogą ogona „Oznacz zniknięte" (`_adopt_and_derive`): `_copy_facts` →
    `_adopt_testimony`, te same funkcje rdzenia, bez zawężenia do korzenia (licznik i wiersz „?"
    liczą bez korzenia). Ani skanu, ani passa obecności, ani sondy źródła; bez przejęcia
    zeznania także bez etapów masowych (pochodne tylko po realnym przejęciu - osobny test).

    Falsyfikator: dołóż w `_adopt_and_derive` `self._scan(con)` → wołania zawierają skan."""
    from horreum import scan
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    wolane = []
    for nazwa in ("_adopt_and_derive", "_copy_facts", "_adopt_testimony", "_scan", "_stacks",
                  "_bulk", "_presence", "_zrodlo"):
        prawdziwa = getattr(PipelineWorker, nazwa)

        def _f(self, *a, _n=nazwa, _p=prawdziwa, **kw):
            wolane.append(_n)
            return _p(self, *a, **kw)
        monkeypatch.setattr(PipelineWorker, nazwa, _f)
    korzenie = []
    prawdziwy_backfill = scan.backfill_copy_facts
    monkeypatch.setattr(scan, "backfill_copy_facts",
                        lambda con, **kw: korzenie.append(kw.get("root")) or
                        prawdziwy_backfill(con, **kw))
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("copy_facts")
    started, done, failed = [], [], []
    w.stage_started.connect(started.append)
    w.stage_done.connect(lambda name, s: done.append((name, s)))
    w.failed.connect(lambda n, m: failed.append((n, m)))
    w.run()
    assert failed == []
    assert wolane == ["_adopt_and_derive", "_copy_facts", "_adopt_testimony"], wolane
    assert korzenie == [None]
    assert started == ["copy_facts"] and [n for n, _ in done] == ["copy_facts"]
    assert (done[0][1].rows, done[0][1].written) == (2, 2)
    assert _bez_faktow(db_path) == 0


@pytest.mark.parametrize("przejecie, pochodne", [
    (dict(adopted=1), ["group", "resolve", "calibrate", "lineage"]),
    (dict(adopted=0), []),
    (dict(adopted=1, cancelled=True), []),
    (None, []),
])
def test_gest_fakty_kopii_pochodne_wylacznie_po_realnym_przejeciu(qapp, tmp_path, monkeypatch,
                                                                   przejecie, pochodne):
    """Przejęcie zeznania zmienia `header`, z którego liczą się pochodne - więc po REALNYM
    przejęciu gest puszcza `group` → `resolve` → `calibrate` → `lineage` (kolejność Dostawy),
    a bez niego (zero przejętych, anulowanie, brak kandydatów) nie rusza żadnego etapu masowego.
    Delty i obecności nie ma w żadnym wariancie - to nie dostawa.

    Falsyfikator: zdejmij `not a.adopted` ze straży `_adopt_and_derive` → wariant zero przejętych
    liczy całe archiwum."""
    from horreum import scan
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    masowe = []
    monkeypatch.setattr(PipelineWorker, "_bulk", lambda self, con, name: masowe.append(name))
    monkeypatch.setattr(
        PipelineWorker, "_adopt_testimony",
        lambda self, con: None if przejecie is None else scan.AdoptSummary(rows=1, **przejecie))
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("copy_facts")
    w.run()
    assert masowe == pochodne


def test_gest_fakty_kopii_anulowanie_przerywa_przed_przejeciem(qapp, tmp_path, monkeypatch):
    """Anulowanie tak jak w łańcuchu: `cancelled('copy_facts')`, a przejęcie zeznania i pochodne
    nie ruszają. W oknie gest jest przerywalny (przycisk „Anuluj" aktywny w trakcie)."""
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    adopt, masowe = [], []
    prawdziwa = PipelineWorker._adopt_testimony
    monkeypatch.setattr(PipelineWorker, "_adopt_testimony",
                        lambda self, con: adopt.append(1) or prawdziwa(self, con))
    prawdziwy_bulk = PipelineWorker._bulk
    monkeypatch.setattr(PipelineWorker, "_bulk",
                        lambda self, con, name: masowe.append(name) or
                        prawdziwy_bulk(self, con, name))
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("copy_facts")
    cancelled, done = [], []
    w.cancelled.connect(lambda name, s: cancelled.append((name, s)))
    w.stage_done.connect(lambda name, s: done.append(name))
    w.request_cancel()
    w.run()
    assert [n for n, _ in cancelled] == ["copy_facts"] and cancelled[0][1].cancelled
    assert done == [] and adopt == [] and masowe == []
    assert _bez_faktow(db_path) == 2                     # nic nie zapisane

    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        view._on_copy_facts()
        assert view._thread is not None and view.btn_cancel.isEnabled()
        _czekaj_na_etap(view)
    finally:
        view.close()


def test_gest_fakty_kopii_wykluczony_z_zapisem_naglowkow(qapp, tmp_path):
    """Straż wzajemnego wykluczenia z zapisem nagłówków (jak `run_stage`): przy zapisie w toku
    przycisk wygaszony, a slot zawołany wprost nie rusza etapu. W drugą stronę gest idzie przez
    `running_changed(True)` - ten sam sygnał, którym gospodarz gasi zapis w gridzie.

    Falsyfikator: zdejmij `self._writeback_busy` ze straży `_on_copy_facts` → etap rusza."""
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        bieg = []
        view.running_changed.connect(bieg.append)
        view.set_writeback_busy(True)
        assert not view.btn_copy_facts.isHidden() and not view.btn_copy_facts.isEnabled()
        view._on_copy_facts()
        assert view._thread is None and bieg == [] and _bez_faktow(db_path) == 2
        view.set_writeback_busy(False)
        assert view.btn_copy_facts.isEnabled()
        view._on_copy_facts()
        assert bieg == [True]
        assert not view.btn_receive.isEnabled() and not view.btn_copy_facts.isEnabled()
        _czekaj_na_etap(view)
        assert bieg == [True, False] and _bez_faktow(db_path) == 0
    finally:
        view.close()


def test_gest_fakty_kopii_nie_dotyka_dysku_w_oknie(qapp, tmp_path, monkeypatch):
    """AR-31 (3): ani licznik N (budowa widoku, odświeżenie), ani slot gestu nie dotykają dysku
    w wątku okna - N to sam SELECT bez korzenia (bez `canonize_root`), a pliki kopii czyta wątek
    tła. Na odłączonym udziale okno nie może stać do timeoutu sieci przez przycisk z liczbą.

    Falsyfikator: licz N przez `copy_facts_candidates(con, ostatnie_zrodlo)` → `canonize_root`
    w oknie; czytaj kopie w slocie → `stat` w oknie."""
    db_path, kat = _kopie_bez_faktow(tmp_path)
    w_oknie = _szpieg_dysku(monkeypatch, kat)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        view.show_reason("copy_facts")
        view._on_copy_facts()
        assert w_oknie == [], w_oknie
        _czekaj_na_etap(view)
        assert _bez_faktow(db_path) == 0, "wątek tła przeczytał kopie"
        assert w_oknie == [], w_oknie
    finally:
        view.close()


def test_powod_wejscia_z_Porzadkow_linia_nad_akcjami(qapp, tmp_path):
    """Klik w wiersz „?" w Porządkach przenosi do Dostawy; `show_reason` mówi linią nad akcjami,
    po co człowiek tu jest i który gest to załatwia. Linia gaśnie, gdy robota zrobiona (N = 0)
    albo przy zwykłym wejściu (`None`). Nieznany powód to błąd programisty (EXPECT)."""
    from horreum.gui.pipeline import REASON_COPY_FACTS
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    try:
        assert view.lbl_reason.isHidden()
        view.show_reason(REASON_COPY_FACTS)
        gest = i18n.t("pipeline.btn.copy_facts", n=2)
        assert not view.lbl_reason.isHidden()
        assert view.lbl_reason.text() == i18n.t_plural("pipeline.why.copy_facts", 2, gest=gest)
        assert view.lbl_reason.text().startswith("Zebrać fakty kopii: 2 kopie czekają")
        view.show_reason(None)
        assert view.lbl_reason.isHidden()
        with pytest.raises(AssertionError):
            view.show_reason("cokolwiek")
        view.show_reason(REASON_COPY_FACTS)
        view._on_copy_facts()
        _czekaj_na_etap(view)
        assert view.lbl_reason.isHidden() and view._reason is None
    finally:
        view.close()


def test_etykieta_zlotej_akcji_wymienia_fakty_kopii(qapp):
    """Łańcuch w etykiecie „Przyjmij nowe" wymienia etap faktów kopii (nazwą etapu z katalogu,
    w obu językach) - przed zmianą jedyną wskazówką, że złota akcja zbiera fakty, był kod."""
    for jezyk in ("pl", "en"):
        i18n.set_lang(jezyk)
        try:
            assert (i18n.t("pipeline.stage.copy_facts").lower()
                    in i18n.t("pipeline.receive").lower()), jezyk
        finally:
            i18n.set_lang("pl")
