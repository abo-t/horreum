"""Wspólny WYKONAWCA writebacku off-thread — worker + uchwyt startu/sprzątania dla KAŻDEJ
powierzchni, która commituje albo cofa zmiany plików (P-D/D-PD-3).

Do P-D mieszkał w `grid.py` i był prywatny dla „Zbiorów". Druga powierzchnia (dialog „Napraw
nagłówek…" osi obiektu) potrzebuje tego samego cyklu, a SKOPIOWANIE klasy powieliłoby naprawę
deadlocku AB-BA (GIL × `~QThread`, 2026-07-20), która raz już kosztowała sesję debugowania —
dlatego wędruje TU cały zestaw: worker, dyspozycja `_OPS`, fallback inline dla `:memory:`
i cleanup z `wait()`.

Warstwa widżetów (import Qt uprawniony), ale ŻADNEGO widżetu nie dotyka: postęp/koniec/błąd
wracają sygnałami, a wołający sam gasi przyciski i rysuje pasek — dlatego w `grid.py` zostaje
kilkulinijkowy launcher robiący WYŁĄCZNIE rzeczy widżetowe.

Uchwyt jest PER POWIERZCHNIA, nie singleton: wspólna instancja zlałaby `is_busy`, `cancel()`
i callbacki dwóch niezależnych operacji. Wzajemne wykluczenie DWÓCH powierzchni jest więc
osobnym faktem i mieszka w gospodarzu (`MainWindow`) — patrz `app.py`.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from horreum import db, writeback


class WritebackWorker(QObject):
    """Wykonawca commitu/undo writebacku w wątku tła — bliźniak `PipelineWorker` (pipeline.py §4).
    Otwiera WŁASNE połączenie w SWOIM wątku (`db.connect`; sqlite `check_same_thread` — połączenia
    nie dzielimy między wątkami) i woła Qt-wolny rdzeń `writeback.*` z callbackami `progress`/
    `should_cancel`. NIE dotyka widżetów. Rdzeń commituje per-plik → anulowanie (`Event`) albo wyjątek
    zostawia czysty stan applied/pending (utrwalony). Połączenie zamykane PRZED emisją `done`, żeby
    slot głównego wątku czytał tylko przez `self.con` (bez nakładania połączeń na tym samym pliku)."""

    progress = Signal(int, int, str, str)   # done, total, path, status — MID-commit (Qt-wolny callback rdzenia)
    done = Signal(str, object)              # op, result (CommitResult|UndoResult) — niemutowany po zwrocie rdzenia
    failed = Signal(str, str)               # op, msg — wyjątek → sygnał, NIE crash apki
    finished = Signal()                     # run() wrócił KAŻDĄ drogą → quit wątku

    # Cztery pętle-po-plikach dzielą sygnaturę (con, target_id, now=, progress=, should_cancel=).
    _OPS = {
        "commit":        lambda con, t, now, pr, sc: writeback.commit(con, t, now=now, progress=pr, should_cancel=sc),
        "commit_rename": lambda con, t, now, pr, sc: writeback.commit_renames(con, t, now=now, progress=pr, should_cancel=sc),
        "undo":          lambda con, t, now, pr, sc: writeback.undo(con, t, now=now, progress=pr, should_cancel=sc),
        "undo_rename":   lambda con, t, now, pr, sc: writeback.undo_renames(con, t, now=now, progress=pr, should_cancel=sc),
    }

    def __init__(self, db_path, op, target_id, *, now_fn):
        super().__init__()
        self._db_path = db_path
        self._op = op
        self._target_id = target_id
        self._now = now_fn
        self._cancel = threading.Event()

    def request_cancel(self):
        """Kooperatywne anulowanie — stawiane w GŁÓWNYM wątku, czytane w workerze (`Event` bezpieczny
        międzywątkowo; rdzeń sprawdza PRZED każdym plikiem, zostawiając zapisane 'applied')."""
        self._cancel.set()

    @Slot()
    def run(self):
        con = None
        result = None
        error = None
        try:
            con = db.connect(self._db_path)     # WŁASNE połączenie w TYM wątku (baza już zmigrowana)
            result = self._OPS[self._op](con, self._target_id, self._now(),
                                         self._emit_progress, self._cancel.is_set)
        except Exception as exc:                # błąd → sygnał, NIE crash
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if con is not None:
                con.close()                     # zamknij PRZED done — main czyta tylko przez self.con
        if error is not None:
            self.failed.emit(self._op, error)
        else:
            self.done.emit(self._op, result)
        self.finished.emit()                    # zawsze: zwolnij wątek

    def _emit_progress(self, done, total, path, status):
        # wołane SYNCHRONICZNIE w wątku workera przez rdzeń; ~7 plików/s (I/O NAS) → emisja per plik tania
        self.progress.emit(done, total, path, status)


class WritebackRunner(QObject):
    """Uchwyt cyklu życia jednej powierzchni: worker + wątek + sprzątanie. KLASA (nie mixin, nie goła
    funkcja): mixin kłóciłby się o MRO z `QDialog`/`QWidget` wołającego, a goła funkcja nie ma gdzie
    trzymać referencji — GC zabiłby `QThread` w locie.

    `async_ok=False` (testy) albo brak pliku bazy (`:memory:`) → `run()` INLINE, sygnały direct,
    czyli synchronicznie: ten sam rdzeń, bez QThread. To seam testowy — wołający wystawia go dalej
    jako własną właściwość, bo testy ustawiają go Z ZEWNĄTRZ na widoku.

    `busy_changed` jest JEDNYM właścicielem faktu „ta powierzchnia pisze" — stąd bierze go mutex
    dwóch powierzchni w gospodarzu. Gdyby wołający emitował go sam, musiałby trafić PIĘĆ ścieżek
    końca operacji (commit/undo × klinga + błąd) i pierwsza przeoczona zostawiłaby drugą
    powierzchnię wygaszoną na zawsze."""

    busy_changed = Signal(bool)   # True przy starcie, False gdy operacja skończona (OBIE drogi)

    def __init__(self, db_path, *, now_fn, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._now = now_fn
        self.async_ok = True
        self._thread = None
        self._worker = None

    @property
    def is_busy(self):
        """Czy operacja trwa. Guard „jeden writeback naraz" JEDNEJ powierzchni — dwie powierzchnie
        wyklucza gospodarz (uchwyt jest per-powierzchnia, D-PD-3)."""
        return self._thread is not None

    def start(self, op, target_id, *, on_progress, on_done, on_failed) -> bool:
        """Odpal `op` (commit/commit_rename/undo/undo_rename) na `target_id`. Zwraca False, gdy
        operacja już trwa (wołający nie ma wtedy prawa liczyć na callbacki). Sloty dostaje wołający
        — TEN moduł nie wie, co jest paskiem, a co przyciskiem."""
        if self._thread is not None:
            return False
        self._worker = WritebackWorker(self._db_path, op, target_id, now_fn=self._now)
        self._worker.progress.connect(on_progress)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_failed)
        self.busy_changed.emit(True)
        if self.async_ok and self._db_path:
            self._thread = QThread(self)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._thread.quit)
            self._thread.finished.connect(self._cleanup)
            self._thread.start()
        else:
            try:
                self._worker.run()              # inline: done/progress lecą direct = synchronicznie
            finally:
                self._worker = None
                self.busy_changed.emit(False)   # inline kończy się TU (nie ma wątku ani cleanupu)
        return True

    def cancel(self):
        """Kooperatywne anulowanie bieżącej operacji (rdzeń sprawdza PRZED następnym plikiem)."""
        if self._worker is not None:
            self._worker.request_cancel()

    def _cleanup(self):
        # wait() PRZED thread.deleteLater(): worker.deleteLater() doręcza się w teardown wątku
        # (Shiboken::Object::destroy → PyGILState_Ensure); bez wait() ~QThread mógłby czekać na
        # wątek TRZYMAJĄC GIL → AB-BA deadlock (native dump 2026-07-20, ten sam mechanizm co
        # projection_dialog._cleanup_dry_thread — komentarz tam). wait() zwalnia GIL → wątek
        # dokańcza destrukcję i umiera; ~QThread trafia na martwy handle.
        self._worker.deleteLater(); self._thread.wait(); self._thread.deleteLater()
        self._worker = None; self._thread = None
        self.busy_changed.emit(False)
