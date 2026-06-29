"""Widok Pipeline + worker `QThread` (PLAN_gui_pipeline §4/§6 — warstwa widżetów). User prowadzi
CAŁY pierwszy przebieg na własnych danych Z OKNA: wskaż katalog → skan (przyrostowy) → grupuj →
rozwiąż → delta — bez CLI. „Przetwórz wszystko" robi cały łańcuch jednym kliknięciem.

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
from horreum.grouper import run_grouper
from horreum.resolver import delta_report, run_resolver
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
    stage_started = Signal(str)            # przed każdym (pod)etapem — UI pokazuje „… w toku"
    stage_done = Signal(str, object)       # po (pod)etapie — summary/report
    cancelled = Signal(str, object)
    failed = Signal(str, str)
    finished = Signal()                    # run() zakończył (KAŻDĄ drogą) — sygnał do quit() wątku

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
                self._scan(con)
            elif self._stage == "group":
                self._bulk(con, "group")
            elif self._stage == "resolve":
                self._bulk(con, "resolve")
            elif self._stage == "delta":
                self._bulk(con, "delta")
            elif self._stage == "all":
                self._run_all(con)
            else:
                self.failed.emit(self._stage or "?", f"nieznany etap: {self._stage!r}")
        except Exception as exc:                       # błąd etapu → sygnał, NIE crash apki
            self.failed.emit(self._stage or "?", f"{type(exc).__name__}: {exc}")
        finally:
            if con is not None:
                con.close()
            self.finished.emit()                       # zawsze: zwolnij wątek (quit pętli zdarzeń)

    def _scan(self, con):
        """Skan z progresem/anulowaniem. Zwraca summary; emituje cancelled/stage_done. `False` =
        anulowano (wołający przerywa łańcuch „all")."""
        self.stage_started.emit("scan")
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
            return False
        self.stage_done.emit("scan", summary)
        return True

    def _bulk(self, con, name):
        """Etap masowy (group/resolve/delta) — bezobsługowy, sekundy–minuty, bez progresu per-wiersz.
        delta jest READ-ONLY (zero DML). Emituje stage_started → stage_done."""
        self.stage_started.emit(name)
        if name == "group":
            result = run_grouper(con, self._now())
        elif name == "resolve":
            result = run_resolver(con, self._now())
        else:                                          # delta — read-only
            result = delta_report(con)
        self.stage_done.emit(name, result)

    def _run_all(self, con):
        """„Przetwórz wszystko": scan→group→resolve→delta w jednym wątku. Anulowanie skanu PRZERYWA
        łańcuch (group/resolve/delta się nie wykonują — baza spójna, re-skan dokończy)."""
        if not self._scan(con):
            return
        self._bulk(con, "group")
        self._bulk(con, "resolve")
        self._bulk(con, "delta")

    def _on_progress(self, done, total, path, summary):
        # wołane SYNCHRONICZNIE w wątku workera przez scan_tree; przerzedź i wyślij MIGAWKĘ (dict),
        # nigdy żywego ScanSummary (worker mutuje go dalej w pętli → race po stronie slotu).
        if should_emit(done, total):
            self.progress.emit(done, total, path, counts_snapshot(summary))


# Etykiety widoczne dla użytkownika po polsku; wartości danych ("cold"/"scratch") to identyfikatory
# poziomu zapisywane do bazy (rdzeń `scan_tree`) — ZOSTAJĄ niezmienione.
_TIERS = [("—", None), ("zimny (archiwum)", "cold"), ("roboczy", "scratch")]
_STAGE_LABEL = {"scan": "Skan", "group": "Grupowanie", "resolve": "Rozwiązywanie", "delta": "Delta"}


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
        self._cancellable = False
        self._summary_lines = []
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

        # 2. Źródło: katalog + poziom + auto-wolumen
        src = QHBoxLayout()
        self.btn_pick = QPushButton("Wskaż katalog…")
        self.btn_pick.clicked.connect(self._on_pick_dir)
        src.addWidget(self.btn_pick)
        self.lbl_root = QLabel("(nie wskazano)")
        src.addWidget(self.lbl_root, 1)
        src.addWidget(QLabel("poziom:"))
        self.combo_tier = QComboBox()
        for label, value in _TIERS:
            self.combo_tier.addItem(label, value)
        src.addWidget(self.combo_tier)
        v.addLayout(src)
        self.lbl_volume = QLabel("wolumen: —")
        v.addWidget(self.lbl_volume)
        v.addWidget(self._hline())

        # 3. „Przetwórz wszystko" — DOMYŚLNA ścieżka (skan→grupuj→rozwiąż→delta jednym kliknięciem).
        # Akcja główna ma wagę WIZUALNĄ (bold + wyższy) — wizytator P2: nie może wyglądać jak reszta.
        self.btn_all = QPushButton("Przetwórz wszystko  (skan → grupuj → rozwiąż → delta)")
        _f = self.btn_all.font()
        _f.setBold(True)
        self.btn_all.setFont(_f)
        self.btn_all.setMinimumHeight(34)
        self.btn_all.clicked.connect(self._on_all)
        v.addWidget(self.btn_all)

        # 4. Etapy pojedyncze (tryb zaawansowany) + anulowanie (tylko skan/all jest przerywalny)
        stages = QHBoxLayout()
        self.btn_scan = QPushButton("Skanuj")
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_group = QPushButton("Grupuj")
        self.btn_group.clicked.connect(self._on_group)
        self.btn_resolve = QPushButton("Rozwiąż")
        self.btn_resolve.clicked.connect(self._on_resolve)
        self.btn_delta = QPushButton("Pokaż deltę")
        self.btn_delta.clicked.connect(self._on_delta)
        self.btn_cancel = QPushButton("Anuluj")
        self.btn_cancel.clicked.connect(self._on_cancel)
        for b in (self.btn_scan, self.btn_group, self.btn_resolve, self.btn_delta, self.btn_cancel):
            stages.addWidget(b)
        stages.addStretch(1)
        v.addLayout(stages)

        # 5. Pasek + liczniki (wspólne: skan = uczciwy %; etapy masowe = busy spinner). Pasek UKRYTY
        # w spoczynku — wizytator P2: „0%" w idle kłamie, że coś ruszyło. Pojawia się w _begin_run.
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        self.lbl_counts = QLabel("")
        v.addWidget(self.lbl_counts)

        # 6. Błąd etapu — OSOBNY wiersz, kolor semantyczny (wizytator P2: błąd nie może ginąć wśród
        # czarnych wierszy panelu). Ukryty dopóki nie padnie failed.
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #b00020;")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        v.addWidget(self.lbl_error)

        # 7. Panel podsumowania — akumuluje wiersz per (pod)etap (handoff delty do import-legacy)
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

    # ---------------------------------------------------------------- akcje (worker)

    def _scan_params(self):
        return dict(
            root=self._root,
            volume=self._serial if self._serial is not None else "?",
            drive_letter=(Path(self._root).drive or None),
            tier=self.combo_tier.currentData(),
        )

    def _begin_run(self):
        """Wyzeruj panel/pasek przed nowym przebiegiem (summary akumuluje per etap, więc czyścimy)."""
        self._summary_lines = []
        self.lbl_summary.setText("")
        self.lbl_error.setVisible(False)
        self.lbl_error.setText("")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.lbl_counts.setText("")

    def _on_all(self):
        if not self._can_scan() or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("all", **self._scan_params())

    def _on_scan(self):
        if not self._can_scan() or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("scan", **self._scan_params())

    def _on_group(self):
        if self._db_path is None or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("group")

    def _on_resolve(self):
        if self._db_path is None or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("resolve")

    def _on_delta(self):
        if self._db_path is None or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("delta")

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
        self._worker.stage_started.connect(self._on_stage_started)
        self._worker.stage_done.connect(self._on_stage_done)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_failed)
        # quit DOPIERO gdy run() w całości wróci (`finished`) — przy „all" leci wiele stage_done,
        # więc NIE wolno kończyć wątku na pierwszym z nich.
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._set_running(True, cancellable=stage in ("scan", "all"))
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
        do_przegladu = counts["frame_review"] + counts["camera_review"]
        self.lbl_counts.setText(
            f"Pliki {done}/{total} · nowe {counts['frames_new']} · "
            f"pominięte {counts['skipped']} · przegląd {do_przegladu} · {tail}")

    @Slot(str)
    def _on_stage_started(self, name):
        # skan: pasek nieokreślony do 1. progresu; etap masowy: busy spinner (bez progresu per-wiersz)
        self.bar.setRange(0, 0)
        self.lbl_counts.setText(f"{_STAGE_LABEL.get(name, name)} w toku…")

    @Slot(str, object)
    def _on_stage_done(self, name, result):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.lbl_counts.setText("")
        self._append_summary(self._format_result(name, result))
        self.status_message.emit(f"{_STAGE_LABEL.get(name, name)}: gotowe.")
        self.stage_finished.emit(name)                  # gospodarz odświeża oś (WAL)

    @Slot(str, object)
    def _on_cancelled(self, name, summary):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_counts.setText("")
        self._append_summary(
            f"[skan] przerwano po {summary.files} plikach — baza spójna, ponowny skan dokończy.")
        self._append_summary(self._format_result("scan", summary))
        self.status_message.emit(f"Skan przerwany po {summary.files} plikach.")
        self.stage_finished.emit(name)                  # częściowy zapis też trzeba odświeżyć

    @Slot(str, str)
    def _on_failed(self, name, msg):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_counts.setText("")
        self.lbl_error.setText(f"BŁĄD — etap „{_STAGE_LABEL.get(name, name)}”: {msg}")
        self.lbl_error.setVisible(True)                 # czerwony, osobny wiersz — nie ginie w panelu
        self.status_message.emit(f"Etap „{name}” nie powiódł się.")

    # ---------------------------------------------------------------- formatowanie / stan przycisków

    def _append_summary(self, line):
        self._summary_lines.append(line)
        self.lbl_summary.setText("\n".join(self._summary_lines))

    def _format_result(self, name, r):
        if name == "scan":
            return self._format_scan(r)
        if name == "group":
            return self._format_group(r)
        if name == "resolve":
            return self._format_resolve(r)
        if name == "delta":
            return self._format_delta(r)
        return str(r)

    def _format_scan(self, s):
        return (
            f"[skan] pliki {s.files} · nowe {s.frames_new} · istniejące {s.frames_existing} · "
            f"pominięte {s.skipped} · wykluczone katalogi {s.dirs_excluded} · "
            f"lokalizacje {s.locations_new} · nagłówki {s.headers} · "
            f"przegląd f/{s.frame_review} k/{s.camera_review} rodzaj/{s.kind_unmapped}")

    def _format_group(self, s):
        return (
            f"[grupuj] nagłówki {s.headers} · f/ ok/odzysk/przegląd "
            f"{s.focratio_ok}/{s.focratio_recovered}/{s.focratio_review} · teleskopy {s.telescopes_proposed} "
            f"(podejrzane {s.telescopes_suspect}) · konfiguracje {s.configs_proposed}/{s.configs_assigned} · "
            f"konfig. do przeglądu {s.config_review}")

    def _format_resolve(self, s):
        return (
            f"[rozwiąż] klatki {s.frames} · klatki light {s.light_frames} · obiekty nowe {s.objects_new} · "
            f"przypisane {s.objects_assigned} · przegląd {s.objects_review} "
            f"(różnych {s.objects_unresolved_distinct}) · filtry {s.filters_set}")

    def _format_delta(self, r):
        total = r.object_resolved + r.object_unresolved
        top = ", ".join(f"{raw}×{n}" for raw, n in r.object_delta[:8]) or "—"
        reviews = ", ".join(f"{v}:{n}" for v, n in sorted(r.review_counts.items())) or "—"
        return (
            f"[delta] obiekt {r.object_resolved}/{total} ({r.object_pct:.1f}%) · filtry {r.filters_canon}\n"
            f"   nierozpoznane: {top}\n   do przeglądu: {reviews}")

    def _refresh_buttons(self, running, cancellable):
        idle = not running
        has_db = self._db_path is not None
        self.btn_pick.setEnabled(idle)
        self.combo_tier.setEnabled(idle)
        self.btn_all.setEnabled(idle and self._can_scan())
        self.btn_scan.setEnabled(idle and self._can_scan())
        self.btn_group.setEnabled(idle and has_db)
        self.btn_resolve.setEnabled(idle and has_db)
        self.btn_delta.setEnabled(idle and has_db)
        self.btn_cancel.setEnabled(running and cancellable)

    def _set_running(self, running, *, cancellable=False):
        self._cancellable = cancellable if running else False
        self._refresh_buttons(running, self._cancellable)
        self.running_changed.emit(running)

    def _can_scan(self):
        return self._db_path is not None and self._root is not None

    def _sync_actions(self):
        self._refresh_buttons(self._thread is not None, self._cancellable)
