"""Widok Pipeline + worker `QThread` (PLAN_gui_pipeline §4/§6 — warstwa widżetów, ETAP 2). User
prowadzi pierwszy przebieg na własnych danych Z OKNA: wskaż katalog → skan (przyrostowy) → … bez CLI.

To JEDEN z plików warstwy widżetów, którym wolno importować PySide6 (test izolacji
`test_gui_isolation.py` — `pipeline.py` na whiteliście). Logika domenowa (skan, brama, normalizacja)
mieszka w rdzeniu Qt-wolnym (`horreum.scan`), throttle/snapshot w `horreum.gui.progress` (testowane
bez Qt). Tu zostaje sama glue: widżety, wątek, sygnały.

WSPÓŁBIEŻNOŚĆ (§4): worker otwiera WŁASNE połączenie `db.open_db` w SWOIM wątku (sqlite
`check_same_thread` — połączenie nie przechodzi między wątkami). Główny wątek NIGDY nie woła
`scan_tree` (UI się nie zamraża). Slot postępu dostaje DICT-migawkę liczników (nie żywy `ScanSummary`),
emisja przerzedzona (`progress.should_emit`). Anulowanie = `threading.Event` (stawiane w głównym
wątku przyciskiem, czytane w workerze — bezpieczne międzywątkowo)."""
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from horreum import db
from horreum.gui.progress import counts_snapshot, should_emit
from horreum.scan import scan_tree
from horreum.volumes import volume_serial


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class PipelineWorker(QObject):
    """Wykonawca etapu pipeline'u w wątku tła. Otwiera WŁASNE połączenie (per-wątek), woła funkcję
    rdzenia, emituje sygnały. NIE dotyka widżetów (slot w głównym wątku rusza UI).

    Sygnały: `progress(done,total,path,counts:dict)` (mid-skan, DICT-migawka), `stage_done(name,
    summary)` (po etapie — `summary` już niemutowany, więc obiekt wolno przekazać), `cancelled(name,
    summary)`, `failed(name, msg)` (wyjątek → komunikat, NIE crash)."""

    progress = Signal(int, int, str, dict)
    stage_done = Signal(str, object)
    cancelled = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, db_path, *, now_fn=_utc_now_iso):
        super().__init__()
        self._db_path = db_path
        self._now = now_fn
        self._cancel = threading.Event()
        self._stage = None
        self._params = {}

    def configure(self, stage, **params):
        self._stage = stage
        self._params = params

    def request_cancel(self):
        """Kooperatywne anulowanie — stawiane w GŁÓWNYM wątku, czytane w workerze (`Event` jest
        bezpieczny międzywątkowo; nie tykamy tu żadnego obiektu Qt)."""
        self._cancel.set()

    @Slot()
    def run(self):
        con = None
        try:
            con = db.open_db(self._db_path)
            if self._stage == "scan":
                self._run_scan(con)
            else:
                self.failed.emit(self._stage or "?", f"nieznany etap: {self._stage!r}")
        except Exception as exc:                       # błąd etapu → sygnał, NIE crash apki
            self.failed.emit(self._stage or "?", f"{type(exc).__name__}: {exc}")
        finally:
            if con is not None:
                con.close()

    def _run_scan(self, con):
        summary = scan_tree(
            con, self._params["root"],
            volume=self._params.get("volume", "?"),
            drive_letter=self._params.get("drive_letter"),
            tier=self._params.get("tier"),
            now=self._now(),
            progress=self._on_progress,
            should_cancel=self._cancel.is_set,
        )
        if summary.cancelled:
            self.cancelled.emit("scan", summary)
        else:
            self.stage_done.emit("scan", summary)

    def _on_progress(self, done, total, path, summary):
        # wołane SYNCHRONICZNIE w wątku workera przez scan_tree; przerzedź i wyślij MIGAWKĘ (dict),
        # nigdy żywego ScanSummary (worker mutuje go dalej w pętli → race po stronie slotu).
        if should_emit(done, total):
            self.progress.emit(done, total, path, counts_snapshot(summary))


_TIERS = [("—", None), ("cold", "cold"), ("scratch", "scratch")]


class PipelineView(QWidget):
    """Widok Pipeline (ETAP 2 — sekcja SKANU; group/resolve/delta dochodzą w etapie 3). Pionowy flow:
    baza → źródło (katalog + tier + auto-wolumen) → skan z uczciwym % i anulowaniem → panel
    `ScanSummary`. Stan widoczny BEZ klikania; akcja kroku wyróżniona; UI nie kłamie (disabled gdy
    nie można).

    Sygnały do gospodarza (`MainWindow`): `status_message(str)` (pasek statusu), `stage_finished(str)`
    (etap zakończył zapis — gospodarz odświeża read-model osi; WAL → widoczne), `running_changed(bool)`
    (etap w toku — gospodarz wyłącza akcje zapisu osi: szczery disabled, §6)."""

    status_message = Signal(str)
    stage_finished = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, db_path, *, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._now = now_fn
        self._root = None
        self._serial = None
        self._thread = None
        self._worker = None
        self._build_ui()
        self._sync_actions()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        v = QVBoxLayout(self)

        # 1. Baza (wskaźnik; Otwórz/Nowa są w menu Plik okna)
        self.lbl_db = QLabel()
        self.lbl_db.setText(f"Baza: {self._db_path}" if self._db_path else "Baza: (brak)")
        v.addWidget(self.lbl_db)
        v.addWidget(self._hline())

        # 2. Źródło: katalog + tier + auto-wolumen
        src = QHBoxLayout()
        self.btn_pick = QPushButton("Wskaż katalog…")
        self.btn_pick.clicked.connect(self._on_pick_dir)
        src.addWidget(self.btn_pick)
        self.lbl_root = QLabel("(nie wskazano)")
        src.addWidget(self.lbl_root, 1)
        src.addWidget(QLabel("tier:"))
        self.combo_tier = QComboBox()
        for label, value in _TIERS:
            self.combo_tier.addItem(label, value)
        src.addWidget(self.combo_tier)
        v.addLayout(src)
        self.lbl_volume = QLabel("wolumen: —")
        v.addWidget(self.lbl_volume)
        v.addWidget(self._hline())

        # 3. Skan: akcja + pasek + liczniki + anuluj
        run = QHBoxLayout()
        self.btn_scan = QPushButton("Skanuj")
        self.btn_scan.clicked.connect(self._on_scan)
        run.addWidget(self.btn_scan)
        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.clicked.connect(self._on_cancel)
        run.addWidget(self.btn_cancel)
        run.addStretch(1)
        v.addLayout(run)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        v.addWidget(self.bar)
        self.lbl_counts = QLabel("")
        v.addWidget(self.lbl_counts)

        # 4. Panel podsumowania etapu
        self.lbl_summary = QLabel("")
        self.lbl_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_summary.setWordWrap(True)
        v.addWidget(self.lbl_summary)
        v.addStretch(1)

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ---------------------------------------------------------------- źródło

    def _on_pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Wskaż katalog do skanu")
        if not path:
            return
        self._root = path
        self.lbl_root.setText(path)
        serial = volume_serial(path)
        if serial is None:
            self.lbl_volume.setText("wolumen: ? (serial nieustalony → pełny skan, bez pomijania)")
        else:
            self.lbl_volume.setText(f"wolumen: {serial} (skan przyrostowy — znane pliki pomijane)")
        self._serial = serial
        self._sync_actions()

    # ---------------------------------------------------------------- skan (worker)

    def _on_scan(self):
        if self._root is None or self._db_path is None or self._thread is not None:
            return
        self.bar.setRange(0, 0)                          # nieokreślony do pierwszego progresu
        self.lbl_counts.setText("Skan w toku…")
        self.lbl_summary.setText("")
        self._start_stage(
            "scan",
            root=self._root,
            volume=self._serial if self._serial is not None else "?",
            drive_letter=(Path(self._root).drive or None),
            tier=self.combo_tier.currentData(),
        )

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.request_cancel()
            self.status_message.emit("Anulowanie… (po bieżącym pliku)")

    def _start_stage(self, stage, **params):
        self._worker = PipelineWorker(self._db_path, now_fn=self._now)
        self._worker.configure(stage, **params)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.stage_done.connect(self._on_stage_done)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_failed)
        # po zakończeniu etapu (każdą drogą) zatrzymaj pętlę wątku → finished → sprzątanie
        self._worker.stage_done.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._set_running(True)
        self._thread.start()

    def _cleanup_thread(self):
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_running(False)

    # ---------------------------------------------------------------- sloty (główny wątek)

    @Slot(int, int, str, dict)
    def _on_progress(self, done, total, path, counts):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        tail = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        review = counts["frame_review"] + counts["camera_review"]
        self.lbl_counts.setText(
            f"Pliki {done}/{total} · nowe {counts['frames_new']} · "
            f"pominięte {counts['skipped']} · review {review} · {tail}")

    @Slot(str, object)
    def _on_stage_done(self, name, summary):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.lbl_summary.setText(self._format_summary(summary))
        self.status_message.emit(f"Skan zakończony: {summary.files} plików.")
        self.stage_finished.emit(name)

    @Slot(str, object)
    def _on_cancelled(self, name, summary):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_summary.setText(
            f"Przerwano po {summary.files} plikach — baza spójna, ponowny skan dokończy.\n"
            + self._format_summary(summary))
        self.status_message.emit(f"Skan przerwany po {summary.files} plikach.")
        self.stage_finished.emit(name)                  # częściowy zapis też trzeba odświeżyć

    @Slot(str, str)
    def _on_failed(self, name, msg):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_counts.setText("")
        self.lbl_summary.setText(f"Błąd etapu „{name}”: {msg}")
        self.status_message.emit(f"Etap „{name}” nie powiódł się.")

    # ---------------------------------------------------------------- pomocnicze

    def _format_summary(self, s):
        return (
            f"Pliki: {s.files} · nowe frame'y: {s.frames_new} · istniejące: {s.frames_existing} · "
            f"pominięte (brama): {s.skipped}\n"
            f"nowe location: {s.locations_new} · nagłówki: {s.headers} · "
            f"frame.review: {s.frame_review} · camera.review: {s.camera_review} · "
            f"kind.unmapped: {s.kind_unmapped}")

    def _set_running(self, running):
        self.btn_scan.setEnabled(not running and self._can_scan())
        self.btn_pick.setEnabled(not running)
        self.combo_tier.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.running_changed.emit(running)

    def _can_scan(self):
        return self._db_path is not None and self._root is not None

    def _sync_actions(self):
        running = self._thread is not None
        self.btn_scan.setEnabled(not running and self._can_scan())
        self.btn_cancel.setEnabled(running)
