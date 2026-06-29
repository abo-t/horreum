"""Widok Pipeline + worker QThread (`horreum.gui.pipeline`, PLAN_gui_pipeline §4/§7). Worker testowany
DWOJAKO: (1) synchronicznie — `run()` wołane wprost, sygnały łapane w listy (kontrakt: progress=dict-
migawka, stage_done/cancelled/failed); (2) integracyjnie w PRAWDZIWYM `QThread` z pętlą zdarzeń —
dowód, że główny wątek nie woła `scan_tree` (R1) i że `running_changed` przełącza się True→False.

`importorskip` na poziomie modułu — bez PySide6 plik się pomija (czyni §7.2 prawdziwym). FS = tmp_path
(logika); firsthand na realnych FITS/XISF = Etap 4."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from astropy.io import fits

from horreum import db
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
    view._root = _tree(tmp_path, 2)
    view._serial = "VOL1"
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
    from horreum.grouper import GroupSummary
    from horreum.resolver import DeltaReport, ResolveSummary
    db_path = _scanned_db(tmp_path)
    for stage, typ in [("group", GroupSummary), ("resolve", ResolveSummary), ("delta", DeltaReport)]:
        w = PipelineWorker(db_path, now_fn=lambda: NOW)
        w.configure(stage)
        done, started = [], []
        w.stage_started.connect(lambda n: started.append(n))
        w.stage_done.connect(lambda n, r: done.append((n, r)))
        w.run()
        assert started == [stage]
        assert done and done[0][0] == stage and isinstance(done[0][1], typ)


def test_worker_all_lancuch_scan_group_resolve_delta(qapp, tmp_path):
    """„Przetwórz wszystko": jeden worker emituje stage_done dla scan→group→resolve→delta w kolejności,
    a `finished` pada raz na końcu (sygnał do quit wątku)."""
    db_path = _fresh_db(tmp_path)
    w = PipelineWorker(db_path, now_fn=lambda: NOW)
    w.configure("all", root=_tree(tmp_path, 2), volume="VOL1", drive_letter=None, tier=None)
    order, fin = [], []
    w.stage_done.connect(lambda n, r: order.append(n))
    w.finished.connect(lambda: fin.append(1))
    w.run()
    assert order == ["scan", "group", "resolve", "delta"]
    assert len(fin) == 1


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
    """all/scan wymagają bazy ORAZ katalogu; group/resolve/delta — samej bazy; anuluj wyłączony w spoczynku."""
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    assert not view.btn_all.isEnabled() and not view.btn_scan.isEnabled()   # brak katalogu
    assert view.btn_group.isEnabled() and view.btn_resolve.isEnabled() and view.btn_delta.isEnabled()
    assert not view.btn_cancel.isEnabled()
    view._root = _tree(tmp_path, 1); view._serial = "VOL1"; view._sync_actions()
    assert view.btn_all.isEnabled() and view.btn_scan.isEnabled()           # katalog wskazany


def test_view_przetworz_wszystko_w_watku(qapp, tmp_path):
    """Pełny łańcuch z okna w PRAWDZIWYM wątku: panel akumuluje 4 sekcje (skan/grupuj/rozwiąż/delta),
    running wraca do False po sprzątnięciu."""
    view = PipelineView(_fresh_db(tmp_path), now_fn=lambda: NOW)
    view._root = _tree(tmp_path, 2)
    view._serial = "VOL1"
    running = []
    loop = QEventLoop()
    view.running_changed.connect(running.append)
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(20000, loop.quit)
    view._on_all()
    loop.exec()
    txt = view.lbl_summary.text()
    assert "[skan]" in txt and "[grupuj]" in txt and "[rozwiąż]" in txt and "[delta]" in txt
    assert running[0] is True and running[-1] is False and view._thread is None
