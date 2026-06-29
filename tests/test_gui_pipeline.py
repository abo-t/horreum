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
    assert "Pliki: 2" in view.lbl_summary.text() and "nowe frame'y: 2" in view.lbl_summary.text()
    assert view._thread is None                        # wątek sprzątnięty
