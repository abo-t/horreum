"""Dialog „Wydaj na stół" (F2 redesignu — PLAN_ux_redesign §3; KROK 6 scalenia — warstwa widżetów).

Przebudowa wokół 1-klik: CELE ZAPAMIĘTANE (QSettings `projection/targets`, karty-radio + „+ inny
cel…", ostatnio użyty = domyślny — wchłania wiz #8), AUTO-DRY OFF-THREAD (R#6: DRY sonduje FS celu —
cel SMB/odpięty może wisieć; wyzwalany WYŁĄCZNIE zdarzeniami dyskretnymi: otwarcie dialogu, klik
karty celu, zmiana układu/przełącznika kopii) i AUTO-DECYZJA hardlink/kopia po wolumenach (R#4+R2-1:
seriale lokacji, które plan FAKTYCZNIE wybierze — pierwsza obecna per frame, D-P5 — po odrzuceniu
frame'ów bez obecnej kopii; JAKIKOLWIEK inny wolumen / `'?'` → kopia CAŁOŚCI, bo `apply` ma jedną
globalną flagę `copy`). Słownictwo per tryb (wchłania wiz #5): „skopiowano/do skopiowania" vs
„zlinkowano/do zlinkowania"; przycisk nazywa skutek i liczbę („Utwórz 131 kopii"). Rozmiar przy
kopii (R#5): suma po TEJ SAMEJ lokacji, którą wybiera plan; `size_bytes IS NULL` → „(+n plików bez
rozmiaru)" zamiast kłamliwej sumy.

Ochrona przed stale-DRY (R2-2): licznik generacji — każde `_invalidate` inkrementuje; wynik DRY
niesie generację startu; handler przyjmuje WYŁĄCZNIE generację równą bieżącej (stale = odrzuć +
re-trigger). Sam wzorzec `_writeback_async` gridu tej ochrony NIE ma (writeback nie zmienia
parametrów w locie) — deklaracja off-thread bez licznika uzbroiłaby „Utwórz" pod starymi parametrami.

APPLY OFF-THREAD (P2/W1 — bramka pierwszego MASOWEGO wydania): `ApplyWorker` = bliźniak `DryWorker`
z paskiem determinowanym (procent + nota `done/total` i ETA — apply ZNA liczbę z planu, inaczej niż
sonda DRY) i „Przerwij wydawanie" łapiącym na granicy pliku. Na czas biegu parametry (cel/układ/
kopia/„Odśwież") są ZABLOKOWANE — `_invalidate` wyzerowałby `self._plan`, który worker właśnie
materializuje — a RAPORT jest przepisany: panel niósł tekst DRY („bez zmian na dysku") i przez cały
bieg kłamałby największą powierzchnią okna. Anulowanie (także zamknięcie okna w biegu) zostawia
CZĘŚCIOWE drzewo z manifestem (projekcja efemeryczna: undo = skasuj folder w Eksploratorze).

Cała logika plan/link/sonda/guard w Qt-wolnej klindze `horreum.projection` (NIETKNIĘTA — §0 briefu);
tu glue widżetów + czyste pomocniki decyzji (Qt-wolne funkcje modułowe, testowane wprost). Walidacja
segmentu `_WBPP`/`_Review` przy DODAWANIU celu (raz); guard w klindze zostaje drugą linią. Plik na
whiteliście `test_gui_isolation` (warstwa widżetów — import PySide6 uprawniony)."""

from __future__ import annotations

import json
import os
import threading
import time

from PySide6.QtCore import QObject, QSettings, QThread, Signal, Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from horreum import db, projection
from horreum.gui import i18n, queries
from horreum.volumes import volume_serial

_TREE_CAP = 30                        # ile folderów kategorii pokazać w raporcie dialogu


# ---------------------------------------------------------------- pomocniki Qt-WOLNE (testowane wprost)

def chosen_present(rows):
    """LUSTRO wyboru źródła `projection.plan` (D-P5): pierwsza OBECNA location per frame, w porządku
    zapytania (`ORDER BY frame_id, location_id`). Frame BEZ obecnej kopii (location_id NULL z LEFT
    JOIN) ODPADA — idzie do `skipped` planu i NIE uczestniczy w decyzji wolumenowej (R2-1: inaczej
    jedna zniknięta klatka fałszywie przełączałaby całość na kopię). `PlanItem` nie niesie volume,
    stąd powtórzona selekcja na `present_locations`, nie `plan.items` (brief §3)."""
    by_frame = {}
    for r in rows:
        if r["location_id"] is None:
            continue
        by_frame.setdefault(int(r["frame_id"]), r)
    return list(by_frame.values())


def volume_decision(chosen, target_serial):
    """Auto hardlink/kopia (R#4): True = KOPIA. WSZYSTKIE wybrane lokacje na wolumenie celu →
    hardlink; JAKIKOLWIEK inny / `'?'` (placeholder skanu = wolumen nieznany) / nieustalony serial
    celu (None) → kopia CAŁOŚCI (konserwatywnie — `apply` ma jedną globalną flagę `copy`).
    `location.volume` jest NOT NULL w schemacie, więc „None-serial" źródła nie istnieje."""
    if target_serial is None:
        return True
    vols = {r["volume"] for r in chosen}
    return bool(vols - {target_serial}) or "?" in vols


def size_summary(chosen):
    """Suma rozmiaru kopii po WYBRANYCH lokacjach (TYCH SAMYCH, które wybiera plan — R#5; nie po
    wszystkich obecnych: frame w >1 kopii zawyżyłby sumę o duplikaty). `size_bytes IS NULL` liczony
    OSOBNO — „(+n plików bez rozmiaru)" zamiast kłamliwej sumy. Zwraca (total_bytes, n_bez_rozmiaru)."""
    total = 0
    missing = 0
    for r in chosen:
        sb = r["size_bytes"]
        if sb is None:
            missing += 1
        else:
            total += int(sb)
    return total, missing


def format_bytes(n):
    """Rozmiar czytelnie: 999 B → 1.2 MB → 3.4 GB (dziesiętnie po jednostkach 1024)."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def eta_text(done_n, total, elapsed_s, warmup=5):
    """Pozostały czas z zaobserwowanego tempa — „ · pozostało ~14 min" albo PUSTY łańcuch (Qt-wolne).
    Kopia bajtów przez SMB idzie godzinami: sam licznik „12345/15890" nie mówi, czy zostało 5 minut
    czy 3 godziny (wiz #5). Pierwsze `warmup` plików pomijane — tempo z 1–2 próbek potrafi kłamać
    o rząd wielkości, a cofająca się prognoza jest gorsza niż jej brak."""
    if done_n < warmup or done_n >= total or elapsed_s <= 0:
        return ""
    remaining = (total - done_n) * (elapsed_s / done_n)
    if remaining < 90:
        return i18n.t("proj.eta_s", n=int(remaining))
    if remaining < 5400:
        return i18n.t("proj.eta_min", n=int(round(remaining / 60)))
    return i18n.t("proj.eta_h", h=remaining / 3600)


def _elide_path(path, cap=64):
    """Elizja długiej ścieżki celu ŚRODKIEM (wiz K3: pełna ścieżka na karcie dyktowała minimum
    szerokości dialogu). Pełna wersja idzie w tooltip karty."""
    if len(path) <= cap:
        return path
    half = (cap - 1) // 2
    return path[:half] + "…" + path[-half:]


# ---------------------------------------------------------------- worker auto-DRY (wątek tła)

class DryWorker(QObject):
    """Auto-DRY poza wątkiem GUI (R#6). Otwiera WŁASNE połączenie po `db_path` (con nie przechodzi
    między wątkami — check_same_thread); tryb inline (testy / `:memory:`) dostaje żywe `con`
    wołającego i działa synchronicznie. Wynik niesie GENERACJĘ startu (R2-2) — handler dialogu
    odrzuca stale. `request_cancel` łapie na granicy pliku (kontrakt `should_cancel` klingi)."""

    done = Signal(int, object)        # (generacja, payload: plan/res/decyzja/rozmiar)
    failed = Signal(int, str)         # (generacja, komunikat)
    finished = Signal()

    def __init__(self, db_path, frame_ids, layout, root, force_copy, now, gen, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._frame_ids = list(frame_ids)
        self._layout = layout
        self._root = root
        self._force_copy = force_copy
        self._now = now
        self._gen = gen
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except ValueError as exc:                    # guard korzenia klingi (druga linia po walidacji celu)
            self.failed.emit(self._gen, str(exc))
        except Exception as exc:                     # OSError sondy FS itp. — szczerze, nie cicha śmierć wątku
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            plan = projection.plan(con, self._frame_ids, self._layout)
            rows = queries.present_locations(con, self._frame_ids)
        finally:
            if own:
                con.close()
        chosen = chosen_present(rows)
        target_serial = volume_serial(self._root)
        auto_copy = volume_decision(chosen, target_serial)
        eff_copy = bool(self._force_copy) or auto_copy
        res = projection.apply(plan, self._root, do_apply=False, copy=eff_copy, now=self._now,
                               should_cancel=lambda: self._cancel)
        total, missing = size_summary(chosen)
        return {"plan": plan, "res": res, "auto_copy": auto_copy, "copy": eff_copy,
                "target_serial": target_serial, "size_total": total, "size_missing": missing}


# ---------------------------------------------------------------- worker apply (wątek tła)

class ApplyWorker(QObject):
    """REALNE wydanie (linki/kopie) poza wątkiem GUI — bliźniak `DryWorker` (P2/W1). DB nie tyka:
    plan jest już policzony, `projection.apply` czyta WYŁĄCZNIE filesystem — stąd, inaczej niż
    `WritebackWorker` gridu, żadnego własnego połączenia. `progress` per plik (rdzeń woła Qt-wolny
    callback synchronicznie w TYM wątku); `request_cancel` przez `threading.Event` (jak
    `WritebackWorker` — flaga stawiana w wątku głównym, czytana tu) łapie na GRANICY PLIKU.
    `ProjectionAbort` (sonda pierwszego linku) idzie OSOBNYM sygnałem z wynikiem częściowym — to
    werdykt o wolumenie, nie awaria."""

    progress = Signal(int, int, str, str)   # done, total, dst, status — MID-apply
    done = Signal(object)                   # ApplyResult (może nieść cancelled=True)
    aborted = Signal(str, object)           # komunikat, CZĘŚCIOWY ApplyResult (sonda hardlinka)
    failed = Signal(str)                    # wyjątek → sygnał, NIE crash apki
    finished = Signal()                     # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, plan, root, copy, now, manifest):
        super().__init__()
        self._plan = plan
        self._root = root
        self._copy = copy
        self._now = now
        self._manifest = manifest
        self._cancel = threading.Event()

    def request_cancel(self):
        self._cancel.set()

    @Slot()
    def run(self):
        try:
            res = projection.apply(self._plan, self._root, do_apply=True, copy=self._copy,
                                   now=self._now, manifest=self._manifest,
                                   progress=self._emit_progress, should_cancel=self._cancel.is_set)
        except projection.ProjectionAbort as exc:
            self.aborted.emit(str(exc), exc.result)
        except ValueError as exc:                    # guard korzenia klingi (druga linia)
            self.failed.emit(str(exc))
        except Exception as exc:                     # OSError itp. — szczerze, nie cicha śmierć wątku
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(res)
        finally:
            self.finished.emit()

    def _emit_progress(self, done, total, dst, status):
        self.progress.emit(done, total, dst, status)


# ---------------------------------------------------------------- dialog

class ProjectionDialog(QDialog):
    """Wydanie perspektywy na stół: karty celów z pamięci + auto-DRY + „Utwórz N kopii/linków".
    `frame_ids` = klatki gridu (cel); `now_fn` = zegar (ts manifestu); `perspektywa` = etykieta do
    manifestu `_PROJEKCJA.json`; `off_thread=False` = OBA workery (DRY i apply) inline (seam
    testowy, wzorzec `_writeback_async` gridu — sygnały direct = synchronicznie)."""

    def __init__(self, con, frame_ids, *, now_fn, perspektywa="perspektywa", off_thread=True,
                 parent=None):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)
        self._frame_ids = list(frame_ids)
        self._now = now_fn
        self._perspektywa = perspektywa
        self._off_thread = off_thread
        self._gen = 0                    # licznik generacji DRY (R2-2)
        self._dry_thread = None
        self._dry_worker = None
        self._dry_pending = False        # stale przyszło, worker jeszcze żył → re-trigger po sprzątnięciu
        self._plan = None                # plan z ZAAKCEPTOWANEGO (bieżąca generacja) DRY
        self._dry = None                 # payload zaakceptowanego DRY (copy/rozmiar/serial)
        self._cards = []                 # [{name, path, radio, note}]
        # Apply OFF-THREAD (P2/W1): worker+wątek per-wydanie; korzeń NIE jest kopiowany do pola —
        # karty są zamrożone w biegu, więc `_current_root()` pozostaje prawdą do końca wydania.
        self._apply_thread = None
        self._apply_worker = None
        self.setWindowTitle(i18n.t("proj.title"))
        self.setModal(True)
        self.resize(640, 520)
        self._build_ui()
        self._reload_targets()           # zaznaczenie domyślnego celu ODPALA auto-DRY (otwarcie dialogu)

    # ---- budowa ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.addWidget(QLabel(i18n.t("proj.frames_in_perspective", n=len(self._frame_ids))))

        v.addWidget(QLabel(i18n.t("proj.target_label")))
        self._targets_box = QVBoxLayout()
        v.addLayout(self._targets_box)
        self._btn_group = QButtonGroup(self)         # karty w osobnych wierszach → jawna ekskluzywność
        row_add = QHBoxLayout()
        self.btn_add = QPushButton(i18n.t("proj.add_target"))   # atrybut: blokowany na czas apply (W1)
        btn_add = self.btn_add
        btn_add.setAutoDefault(False)
        btn_add.clicked.connect(self._on_add_target)
        row_add.addWidget(btn_add)
        row_add.addStretch(1)
        v.addLayout(row_add)

        hint = QLabel(i18n.t("proj.segment_hint"))
        hint.setProperty("role", "secondary")        # trwała reguła celu (dyskoverowalna przed błędem, #2); tekst drugorzędny z motywu (F6 §7)
        v.addWidget(hint)

        row_l = QHBoxLayout()
        row_l.addWidget(QLabel(i18n.t("proj.layout_label")))
        self.combo_layout = QComboBox()
        self.combo_layout.addItem(i18n.t("proj.layout_by_object"), "po-obiektach")
        self.combo_layout.addItem(i18n.t("proj.layout_wbpp"), "wbpp-feed")
        self.combo_layout.currentIndexChanged.connect(self._on_param_changed)
        row_l.addWidget(self.combo_layout)
        row_l.addStretch(1)
        v.addLayout(row_l)

        self.chk_copy = QCheckBox(i18n.t("proj.force_copy"))
        self.chk_copy.toggled.connect(self._on_param_changed)
        v.addWidget(self.chk_copy)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))   # monospace: słupki liczb (#7)
        self.report.setPlaceholderText(i18n.t("proj.placeholder"))
        v.addWidget(self.report, 1)

        act = QHBoxLayout()
        # JEDEN pasek dwóch biegów (SPOT): DRY = nieokreślony (sonda nie zna liczby z góry, wiz W2),
        # apply = determinowany `done/total` z planu. Przełącza `_apply_begin`/`_apply_end`.
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        # Szerokość USTALONA raz: `setMaximumWidth` nie poszerza (sizeHint słupka to ~83 px, więc limit
        # 220 px był NO-OP i tekst „12345 / 15890" rozjeżdżał się na krawędzi wypełnienia — wiz #3);
        # ustawianie jej dopiero na czas biegu przesuwałoby notę o ~137 px przy każdym wejściu/wyjściu.
        self.busy.setMinimumWidth(220)
        self.busy.setTextVisible(False)
        self.busy.setVisible(False)
        act.addWidget(self.busy)
        self.progress_note = QLabel("")              # „12/131 · plik.fits" — postęp NAZWANY, nie sam słupek
        self.progress_note.setProperty("role", "secondary")
        act.addWidget(self.progress_note)
        self.btn_dry = QPushButton(i18n.t("proj.btn_refresh"))
        self.btn_dry.setAutoDefault(False)           # ręczny re-DRY (np. po zmianie na dysku poza apką)
        self.btn_dry.setEnabled(False)               # bez celu nie ma czego sondować (wiz K5)
        self.btn_dry.clicked.connect(self._on_manual_dry)
        self.btn_apply = QPushButton(i18n.t("proj.btn_create"))
        self.btn_apply.setEnabled(False)             # uzbraja WYŁĄCZNIE zakończony świeży DRY
        self.btn_apply.setDefault(True)              # złota akcja wydania (F2: 1-klik)
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_cancel = QPushButton(i18n.t("proj.btn_cancel_apply"))   # NAZYWA skutek — „Anuluj" obok „Zamknij" czytało się jak bliźniak (wiz #9)
        # wchodzi W MIEJSCE „Utwórz" na czas biegu (wzorzec szuflady gridu)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._on_cancel_apply)
        btn_close = QPushButton(i18n.t("proj.btn_close"))
        btn_close.setAutoDefault(False)
        btn_close.clicked.connect(self.reject)
        act.addStretch(1)
        act.addWidget(self.btn_dry)
        act.addWidget(self.btn_apply)
        act.addWidget(self.btn_cancel)
        act.addWidget(btn_close)
        v.addLayout(act)

    # ---- cele (QSettings) ----
    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _load_target_list(self):
        raw = self._settings().value("projection/targets", "[]")
        try:
            targets = json.loads(raw)
        except (ValueError, TypeError):
            targets = []
        return [t for t in targets if isinstance(t, dict) and t.get("path")]

    def _save_target(self, name, path):
        targets = [t for t in self._load_target_list() if t["path"] != path]   # ten sam cel → nadpisz nazwę
        targets.append({"name": name, "path": path})
        self._settings().setValue("projection/targets", json.dumps(targets, ensure_ascii=False))

    def _reload_targets(self, select_path=None):
        """Przebuduj karty-radio z QSettings; zaznacz `select_path` albo ostatnio użyty cel. Zaznaczenie
        (o ile jest) ODPALA auto-DRY — to zdarzenie dyskretne „otwarcie dialogu / nowy cel"."""
        for c in self._cards:
            self._btn_group.removeButton(c["radio"])
            c["holder"].setParent(None)
        self._cards = []
        targets = self._load_target_list()
        last = self._settings().value("projection/last_target", "")
        pick = select_path if select_path else (last if any(t["path"] == last for t in targets) else None)
        if pick is None and targets:
            pick = targets[-1]["path"]               # brak pamięci → ostatnio dodany
        for t in targets:
            row = QHBoxLayout()
            radio = QRadioButton(f"{t['name']}  —  {_elide_path(t['path'])}")
            radio.setToolTip(t["path"])              # pełna ścieżka pod kursorem (wiz K3)
            self._btn_group.addButton(radio)
            note = QLabel("")
            note.setProperty("role", "secondary")   # tekst drugorzędny z motywu (F6 §7)
            row.addWidget(radio)
            row.addWidget(note)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self._targets_box.addWidget(holder)
            radio.toggled.connect(self._on_target_toggled)
            self._cards.append({"name": t["name"], "path": t["path"], "radio": radio,
                                "note": note, "holder": holder})
        self.btn_dry.setEnabled(False)               # uzbroi je dopiero zaznaczony cel (wiz K5)
        if pick is not None:
            for c in self._cards:
                if c["path"] == pick:
                    c["radio"].setChecked(True)      # → toggled → _invalidate + auto-DRY
                    break

    def _current_root(self):
        for c in self._cards:
            if c["radio"].isChecked():
                return c["path"]
        return None

    def _on_add_target(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("proj.dlg.pick_target"))
        if not path:
            return
        name, ok = QInputDialog.getText(self, i18n.t("proj.dlg.name_title"),
                                        i18n.t("proj.dlg.name_label"),
                                        text=os.path.basename(path) or path)
        if not ok or not name.strip():
            return
        self._add_target_path(path, name.strip())

    def _add_target_path(self, path, name):
        """Dodanie celu z WALIDACJĄ segmentu wykluczonego (raz, przy dodawaniu — brief §3; guard
        w klindze zostaje drugą linią). Zwraca True gdy dodano (seam testowy — bez QFileDialog)."""
        try:
            projection._assert_excluded_segment(path)
        except ValueError as exc:
            self.report.setPlainText(i18n.t("proj.add_failed", e=exc))
            return False
        self._save_target(name, path)
        self._reload_targets(select_path=path)       # nowa karta zaznaczona → auto-DRY
        return True

    # ---- stan / auto-DRY ----
    def _invalidate(self):
        """Zmiana parametru (cel/układ/kopia) unieważnia DRY: generacja ++ (R2-2), „Utwórz" gaśnie —
        uzbroi je wyłącznie ZAKOŃCZONY świeży DRY pod dokładnie bieżące parametry."""
        self._gen += 1
        self._plan = None
        self._dry = None
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText(i18n.t("proj.btn_create"))

    def _on_target_toggled(self, checked):
        if not checked:
            return                                   # reaguj raz, na kartę ZAZNACZANĄ
        self._settings().setValue("projection/last_target", self._current_root() or "")
        self._invalidate()
        self._trigger_dry()

    def _on_param_changed(self, *_):
        self._invalidate()
        self._trigger_dry()

    def _on_manual_dry(self):
        self._invalidate()                           # ręczny re-DRY = świeża generacja (stale w biegu odpadnie)
        self._trigger_dry()

    def _trigger_dry(self):
        """Start auto-DRY pod BIEŻĄCE parametry. Jeden worker naraz — gdy DRY w biegu, jego wynik
        przyjdzie ze STARĄ generacją, zostanie odrzucony i re-triggernie świeży (R2-2)."""
        root = self._current_root()
        if not root:
            self.report.setPlainText(i18n.t("proj.pick_or_add"))
            return
        if self._dry_worker is not None or self._apply_worker is not None:
            return                                   # w biegu apply DRY nie startuje (plan jest materializowany)
        self._dry_pending = False                    # flagę gasi UDANY start — odbity re-trigger nie przepada
        self.report.setPlainText(i18n.t("proj.probing"))
        self.busy.setVisible(True)                   # bieg widoczny, nie tylko tekstem (wiz W2)
        self.btn_dry.setEnabled(False)               # jeden DRY naraz — „Odśwież" gaśnie na czas biegu
        worker = DryWorker(self._db_path, self._frame_ids, self.combo_layout.currentData(),
                           root, self.chk_copy.isChecked(), self._now(), self._gen,
                           con=None if self._db_path else self.con)
        worker.done.connect(self._on_dry_done)
        worker.failed.connect(self._on_dry_failed)
        self._dry_worker = worker
        if self._off_thread and self._db_path:
            self._dry_thread = QThread(self)
            worker.moveToThread(self._dry_thread)
            self._dry_thread.started.connect(worker.run)
            worker.finished.connect(self._dry_thread.quit)
            self._dry_thread.finished.connect(self._cleanup_dry_thread)
            self._dry_thread.start()
        else:
            try:
                worker.run()                         # inline: done/failed lecą direct = synchronicznie
            finally:
                self._dry_worker = None
            if self._dry_pending:
                self._trigger_dry()

    def _cleanup_dry_thread(self):
        # KOLEJNOŚĆ (deadlock GIL × ~QThread, native dump 2026-07-20): worker.deleteLater() doręcza
        # się w TEARDOWN wątku (Shiboken::Object::destroy → PyGILState_Ensure). Bez wait() poniższy
        # thread.deleteLater() mógłby doręczyć się na main, zanim wątek umrze: ~QThread czekałby na
        # wątek TRZYMAJĄC GIL (destrukcja wrappera), a wątek na GIL — AB-BA na stałe. wait() zwalnia
        # GIL, więc wątek dokańcza destrukcję workera i umiera; ~QThread trafia na martwy handle.
        self._dry_worker.deleteLater()
        self._dry_thread.wait()
        self._dry_thread.deleteLater()
        self._dry_worker = None
        self._dry_thread = None
        if self._dry_pending:                        # stale odrzucone w locie → świeży DRY pod bieżące parametry
            self._trigger_dry()                      # flagę gasi DOPIERO udany start (apply w biegu odbija _trigger_dry)

    @Slot(int, object)
    def _on_dry_done(self, gen, payload):
        if gen != self._gen:                         # stale (R2-2): odrzuć + re-trigger
            self._dry_pending = True
            return
        self.busy.setVisible(False)                  # świeży wynik przyjęty — bieg skończony (W2)
        self.btn_dry.setEnabled(True)
        self._plan = payload["plan"]
        self._dry = payload
        self.report.setPlainText(self._format(payload["res"], payload["plan"], dry=True,
                                              payload=payload))
        n = payload["res"].counts.get("would-link", 0)
        key = "proj.create_copies" if payload["copy"] else "proj.create_links"
        self.btn_apply.setText(i18n.t_plural(key, n))
        self.btn_apply.setEnabled(n > 0)             # zero do utworzenia → szczery disabled
        self._update_card_note(payload)

    @Slot(int, str)
    def _on_dry_failed(self, gen, msg):
        if gen != self._gen:
            self._dry_pending = True
            return
        self.busy.setVisible(False)
        self.btn_dry.setEnabled(True)
        self._plan = None
        self._dry = None
        self.btn_apply.setEnabled(False)
        self.report.setPlainText(i18n.t("proj.dry_failed", msg=msg))

    def _update_card_note(self, payload):
        """Szczera nota trybu na ZAZNACZONEJ karcie celu (brief §3): skąd decyzja hardlink/kopia."""
        if self.chk_copy.isChecked():
            note = i18n.t("proj.note_forced_copy")
        elif payload["auto_copy"]:
            note = i18n.t("proj.note_other_vol")
        else:
            note = i18n.t("proj.note_same_vol")
        for c in self._cards:
            c["note"].setText(note if c["radio"].isChecked() else "")

    # ---- akcje: apply OFF-THREAD (P2/W1) ----
    def _on_apply(self):
        """Wydaj plan na dysk w wątku tła (bramka pierwszego MASOWEGO wydania z GUI): pasek
        `done/total` + „Anuluj" na granicy pliku. Parametry blokowane na czas biegu — inaczej klik
        w kartę/układ zawołałby `_invalidate` i wyzerował `self._plan`, który worker właśnie
        materializuje."""
        root = self._current_root()
        if self._plan is None or self._dry is None or not root or self._apply_worker is not None:
            return
        self._apply_begin(len(self._plan.items), root)
        worker = ApplyWorker(self._plan, root, self._dry["copy"], self._now(),
                             {"perspektywa": self._perspektywa, "n_frames": len(self._frame_ids)})
        worker.progress.connect(self._on_apply_progress)
        worker.done.connect(self._on_apply_done)
        worker.aborted.connect(self._on_apply_aborted)
        worker.failed.connect(self._on_apply_failed)
        self._apply_worker = worker
        if self._off_thread:
            self._apply_thread = QThread(self)
            worker.moveToThread(self._apply_thread)
            self._apply_thread.started.connect(worker.run)
            worker.finished.connect(self._apply_thread.quit)
            self._apply_thread.finished.connect(self._cleanup_apply_thread)
            self._apply_thread.start()
        else:
            try:
                worker.run()                         # inline: sloty lecą direct = synchronicznie
            finally:
                self._apply_worker = None

    def _cleanup_apply_thread(self):
        # wait() przed thread.deleteLater() — ten sam deadlock GIL × ~QThread co w _cleanup_dry_thread
        # (komentarz tam); wait() zwalnia GIL, więc teardown wątku dokończy destrukcję workera.
        self._apply_worker.deleteLater()
        self._apply_thread.wait()
        self._apply_thread.deleteLater()
        self._apply_worker = None
        self._apply_thread = None

    def _apply_begin(self, total, root):
        """Wejście w tryb wydania: pasek determinowany (PROCENT — liczby niesie nota, żeby licznik nie
        stał w oknie dwa razy), „Anuluj" w miejscu „Utwórz", parametry zamrożone, RAPORT PRZEPISANY.

        Przepisanie raportu jest obowiązkowe: panel niósł tekst DRY („bez zmian na dysku, do
        zlinkowania: N") i przez CAŁY bieg twierdziłby to samo, mutując dysk — największa powierzchnia
        okna kłamałaby najgłośniej (wiz P1 #1). Przy okazji jest to jedyne miejsce, gdzie w biegu widać
        DOKĄD lecą pliki (karty celu są wygaszone, wiz #8)."""
        self._apply_started = time.monotonic()       # baza ETA (zegar wydania ≠ `now_fn` manifestu)
        self._apply_seen = (0, total)                # ostatni postęp — raport błędu mówi, ile już powstało
        self.busy.setRange(0, total if total > 0 else 0)
        self.busy.setValue(0)
        self.busy.setFormat("%p%")
        self.busy.setTextVisible(True)
        self.busy.setVisible(True)
        self.progress_note.setText(f"0/{total}")
        self.report.setPlainText(i18n.t("proj.applying", root=root))
        self.btn_apply.setVisible(False)
        self.btn_apply.setEnabled(False)             # WPROST, nie tylko przez ukrycie (default-button łapie Enter)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._set_params_enabled(False)

    def _apply_end(self):
        """Wyjście z trybu wydania (sukces / abort / błąd / anulowanie): pasek wraca do postaci
        DRY-owej, parametry odmrożone."""
        self.busy.setVisible(False)
        self.busy.setTextVisible(False)
        self.busy.setFormat("")
        self.busy.setRange(0, 0)                     # z powrotem nieokreślony (tryb DRY)
        self.progress_note.setText("")
        self.btn_cancel.setVisible(False)
        self.btn_apply.setVisible(True)
        self._set_params_enabled(True)

    def _set_params_enabled(self, on):
        """Zamrożenie/odmrożenie parametrów DRY na czas apply (ochrona `self._plan` w biegu). Cały
        WIERSZ karty (`holder`), nie samo radio — inaczej nota trybu („ten sam wolumen → hardlink")
        zostaje w pełnej jasności i zamrożenie czyta się plamiasto (wiz #7)."""
        self.combo_layout.setEnabled(on)
        self.chk_copy.setEnabled(on)
        self.btn_add.setEnabled(on)
        self.btn_dry.setEnabled(on and self._current_root() is not None)
        for c in self._cards:
            c["holder"].setEnabled(on)

    def _on_cancel_apply(self):
        if self._apply_worker is not None:
            self._apply_worker.request_cancel()      # rdzeń sprawdza PRZED następnym plikiem
            self.btn_cancel.setEnabled(False)
            self.progress_note.setText(i18n.t("proj.cancelling"))

    @Slot(int, int, str, str)
    def _on_apply_progress(self, done_n, total, dst, status):
        if self.busy.maximum() != total:
            self.busy.setRange(0, total)
        self.busy.setValue(done_n)
        self._apply_seen = (done_n, total)
        tail = dst.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        eta = eta_text(done_n, total, time.monotonic() - self._apply_started)
        self.progress_note.setText(f"{done_n}/{total}{eta} · {tail}")

    @Slot(object)
    def _on_apply_done(self, res):
        """Wydanie skończone (pełne albo anulowane): raport z rdzenia, „Utwórz" gaśnie — dysk się
        zmienił, więc kolejne wydanie wymaga ŚWIEŻEGO DRY („Odśwież podgląd")."""
        self._apply_end()
        # Cel był ZAMROŻONY na czas biegu, więc `_current_root()` to dokładnie ten, na który wydano.
        self._settings().setValue("projection/last_target", self._current_root())   # ostatnio UŻYTY = domyślny
        self.report.setPlainText(self._format(res, self._plan, dry=False, partial=res.cancelled))
        self.btn_apply.setEnabled(False)
        # nie głosi akcji, która zaszła (wiz K2)
        self.btn_apply.setText(i18n.t("proj.btn_cancelled") if res.cancelled
                               else i18n.t("proj.btn_created_ok"))

    @Slot(str, object)
    def _on_apply_aborted(self, msg, partial):
        """Sonda pierwszego linku padła (SMB oddał kopię zamiast hardlinka) — werdykt o wolumenie."""
        self._apply_end()
        self.report.setPlainText(
            i18n.t("proj.abort_prefix", msg=msg)
            + self._format(partial, self._plan, dry=False, partial=True))
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText(i18n.t("proj.btn_not_created"))  # NIE obiecuje akcji, której raport zabrania (wiz #4)

    @Slot(str)
    def _on_apply_failed(self, msg):
        # Ile już powstało PRZED błędem — bez tego user widzi samą awarię i nie wie, że w celu leży
        # częściowe drzewo (ścieżka anulowania to mówi, ścieżka błędu milczała — wiz #2).
        done_n, total = self._apply_seen
        self._apply_end()
        made = i18n.t("proj.made_before_error", done=done_n, total=total) if done_n else ""
        self.report.setPlainText(i18n.t("proj.apply_error", msg=msg, made=made))
        self.btn_apply.setEnabled(False)             # dysk mógł się zmienić częściowo — DRY musi przeliczyć
        self.btn_apply.setText(i18n.t("proj.btn_error"))

    def _format(self, res, plan, *, dry, partial=False, payload=None):
        c = res.counts
        word_todo = i18n.t("proj.word_copy_todo" if res.copy else "proj.word_link_todo")
        word_done = i18n.t("proj.word_copy_done" if res.copy else "proj.word_link_done")
        mode = i18n.t("proj.mode_copies" if res.copy else "proj.mode_links")
        lines = []
        if dry:
            lines.append(i18n.t("proj.dry_head", layout=res.layout, mode=mode))
            lines.append(i18n.t("proj.dry_counts", todo=word_todo, would=c.get("would-link", 0),
                                exists=c.get("exists", 0), conflict=c.get("conflict", 0),
                                skipped=c.get("skipped", 0)))
            if payload is not None and res.copy:
                size_line = i18n.t("proj.dry_size", size=format_bytes(payload["size_total"]))
                if payload["size_missing"]:
                    m = payload["size_missing"]
                    size_line += f"  {i18n.t_plural('proj.files_no_size', m)}"
                lines.append(size_line)
        else:
            # abort → nie „Utworzono" (wizytator #6); anulowanie nazywa się WPROST (W1) — user ma
            # wiedzieć, że reszta planu jest nietknięta, a nie że wydanie zawiodło.
            head = i18n.t("proj.head_cancelled") if res.cancelled else (
                i18n.t("proj.head_partial") if partial else i18n.t("proj.head_created"))
            lines.append(i18n.t("proj.done_head", head=head, layout=res.layout, mode=mode))
            lines.append(i18n.t("proj.done_counts", done=word_done, linked=c.get("linked", 0),
                                exists=c.get("exists", 0), conflict=c.get("conflict", 0),
                                vbad=c.get("verify_bad", 0), errors=c.get("error", 0),
                                skipped=c.get("skipped", 0)))
            if res.cancelled:
                # Ile planu ZOSTAŁO: drzewo kategorii niżej rysuje się z PEŁNEGO planu, więc bez tej
                # linii raport po anulowaniu wygląda na kompletny. PO liczbach tego, co się stało —
                # pierwsza liczba pod nagłówkiem ma mówić o skutku, nie o jego braku (wiz #11).
                touched = sum(c.get(k, 0) for k in ("linked", "exists", "conflict", "error", "verify_bad"))
                lines.append(i18n.t("proj.untouched", n=max(len(plan.items) - touched, 0)))
        if plan.multi_present:
            lines.append(i18n.t("proj.multi_present", n=plan.multi_present))
        folders: dict = {}
        for it in plan.items:
            key = "/".join(it.segments)
            folders[key] = folders.get(key, 0) + 1
        nf = len(folders)
        # „drzewo PLANU": po anulowaniu/abortcie sekcja niżej dalej opisuje pełen plan, nie stan
        # dysku — bez tego słowa czyta się jak listing celu (wiz #6).
        lines.append(i18n.t("proj.plan_tree", tree=i18n.t_plural("proj.plan_tree_folders", nf)))
        for key, n in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0]))[:_TREE_CAP]:
            lines.append(f"    {key}: {n}")
        if len(folders) > _TREE_CAP:
            lines.append(i18n.t("proj.more_folders", n=len(folders) - _TREE_CAP))
        return "\n".join(lines)

    # ---- sprzątanie wątków przy zamknięciu ----
    def done(self, r):
        """Zamknięcie dialogu (Zamknij/Esc/X) nie może zostawić żywego QThread pod kasowanym rodzicem
        („QThread: Destroyed while thread is still running" = twardy abort apki).

        WYDANIE W BIEGU: zamknięcie = ŻĄDANIE ANULOWANIA, okno ZOSTAJE. Czekanie z timeoutem byłoby
        zakładem o czas jednego pliku — kopia 200 MB przez SMB przekracza każdy sensowny limit, a po
        jego wygaśnięciu wątek-sierota dalej tworzyłby pliki pod skasowanym rodzicem. Okno zostaje
        też po to, by raport „Przerwano" (ile powstało, ile nietkniętych) miał dokąd trafić — bez
        niego user zostaje z częściowym drzewem i zerową wiedzą. Drugie Esc, już po biegu, zamyka.

        SONDA DRY: krótka i NICZEGO nie tworzy → cancel + wait, jak dotąd."""
        if self._apply_worker is not None:
            self._on_cancel_apply()
            return
        if self._dry_worker is not None:
            self._dry_worker.request_cancel()
        if self._dry_thread is not None:
            self._dry_thread.quit()
            self._dry_thread.wait(10_000)
        super().done(r)
