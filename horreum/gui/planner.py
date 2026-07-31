"""EKRAN PLANERA CELÓW (T5c) — „co dziś mam na niebie, w odpowiedniej wielkości i filtrach".

Czwarte miejsce nawigacji (D-0731-6): nie zakładka Porządków, bo badge liczy ROBOTY, a „ile do
zrobienia" w planerze zależy od suwaka `min_hours` — liczba w nawiasie kłamałaby przy każdej
zmianie progu. Nie grid, bo wiersz planera to CEL KATALOGU, który nie ma ani jednej klatki
(D-0731-1), a grid operuje na `frame_ids`.

WARSTWY: widżety tutaj, formatowanie w `planner_model` (Qt-wolne), rachunek w `targets`/`sky`
(rdzeń NIETKNIĘTY). Ten plik nie liczy nieba i nie formatuje komórek — montuje i steruje.

OFF-THREAD MIMO 0,35 S: rachunek nocy idzie na wątek tła z paskiem nieokreślonym, bo poprzeczką
jest brak zamrożenia okna, nie zmierzony czas (memory `horreum-gui-long-ops-progress`); przy
warstwie cirrus i wolniejszym dysku to samo 0,35 s bywa wielokrotnie dłuższe.

PRZERWANIE = UNIEWAŻNIENIE GENERACJĄ, świadomie BEZ haka `should_cancel` w rdzeniu: dokładanie
przerwania do `targets.plan` byłoby zmianą kontraktu T3 bez potrzeby. Kontrolki zostają AKTYWNE
w biegu — każda zmiana to nowa generacja, stary wynik ląduje w koszu.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from PySide6.QtCore import (QAbstractTableModel, QDate, QModelIndex, QObject, Qt, QThread, QTimer,
                            Signal, Slot)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit,
                               QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QSpinBox, QTableView, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from horreum import db, repo, targets
from horreum.gui import i18n, planner_model as pm, queries

# Debounce zmian parametrów: pojedyncze kliknięcie w strzałkę spinboxa nie ma prawa startować
# rachunku nocy, a przytrzymana strzałka wygenerowałaby ich kilkanaście.
_DEBOUNCE_MS = 300

# Kolumny listy: (klucz i18n, pole `ViewRow`). Jedenaście kolumn MUSI się elidować przy podłodze
# okna 1146 px — dlatego rozciąga się TYLKO pokrycie, reszta idzie do treści.
_COLUMNS = (("planner.col_canon", "canon"), ("planner.col_type", "type"),
            ("planner.col_size", "size"), ("planner.col_culmination", "culmination"),
            ("planner.col_window", "window"), ("planner.col_rig", "rig"),
            ("planner.col_coverage", "coverage"), ("planner.col_cost", "cost"),
            ("planner.col_recommend", "recommend"), ("planner.col_plan", "plan"),
            ("planner.col_note", "note"))
_STRETCH_COL = 6            # pokrycie — jedyna kolumna, która ma prawo zjeść nadmiar

_STATUSES = ("planned", "active", "done", "skip")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class PlanWorker(QObject):
    """Rachunek nocy poza wątkiem GUI (wzorzec `DryWorker` z `projection_dialog`). Otwiera WŁASNE
    połączenie po `db_path` — `con` głównego wątku nie przechodzi (sqlite `check_same_thread`).

    Wynik niesie GENERACJĘ startu: handler odrzuca stale, więc zmiana parametru w biegu nie kończy
    się starym planem na ekranie. `PlanResult` jest `frozen`, więc bezpiecznie przechodzi przez
    sygnał (precedens `stage_done` w `pipeline.py`)."""

    done = Signal(int, object)          # (generacja, targets.PlanResult)
    failed = Signal(int, str)           # (generacja, komunikat)
    finished = Signal()

    def __init__(self, db_path, params, gen, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con                 # tryb inline (testy / baza bez ścieżki) — bieg synchroniczny
        self._params = dict(params)
        self._gen = gen

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except ValueError as exc:
            # Baza bez stanowiska z GPS (`targets.plan`) — SZCZERY komunikat zamiast crashu:
            # planer bez pozycji obserwatora nie ma czego liczyć, a podstawienie „środka Polski"
            # byłoby kłamstwem.
            self.failed.emit(self._gen, str(exc))
        except Exception as exc:
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            return targets.plan(con, **self._params)
        finally:
            if own:
                con.close()


class PlannerTableModel(QAbstractTableModel):
    """Model read-only nad `planner_model.ViewRow` (wzorzec `GridTableModel`): karmiony GOTOWYMI
    komórkami, zero SQL i zero formatowania. Wiersz niewidoczny jest WYSZARZONY, nie ukryty —
    Księżyc i horyzont wyceniają, nie wycinają (D-0731-14)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._dim = QColor(128, 128, 128)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, r):
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return i18n.t(_COLUMNS[section][0])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return getattr(row, _COLUMNS[index.column()][1])
        if role == Qt.ForegroundRole and not row.visible:
            return self._dim
        if role == Qt.ToolTipRole and not row.visible:
            return i18n.t("planner.not_visible_tip")
        return None


class ParkDialog(QDialog):
    """„Park…" — jawna własność użytkownika: CZYM dziś fotografuje (D-0731-12). Park NIE jest
    derywowalny z danych (`max(date_obs)` wskazałby sprzęt ostatnio używany, a nie posiadany),
    więc jedyną drogą jest zdanie człowieka.

    Przegląd z `queries.park_overview` (ten sam literał co CLI `horreum park`). Przełącznik ma
    DWA stany — „w parku" / „historyczny"; cofnięcia do NULL („wycofuję zdanie") świadomie NIE
    eksponujemy: klinga je umie i testuje, ale dziś nikt nie potrzebuje odróżnić „odrzuciłem"
    od „nie wypowiedziałem się" (dług T4 nazwany, nie ukryty).

    Zapis idzie przez `repo.set_telescope_park` na GŁÓWNYM wątku — jak każda akcja osi."""

    COL_CANON, COL_LIGHTS, COL_LAST, COL_PARK = range(4)

    def __init__(self, con, now_fn, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self.changed = 0
        self.setWindowTitle(i18n.t("planner.park_title"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(i18n.t("planner.park_hint")))
        rows = queries.park_overview(con)
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels([i18n.t("planner.park_col_telescope"),
                                              i18n.t("planner.park_col_lights"),
                                              i18n.t("planner.park_col_last"),
                                              i18n.t("planner.park_col_state")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._combos = {}
        for r, row in enumerate(rows):
            self._fill(r, row)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        lay.addWidget(self.table)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        lay.addWidget(box)

    def _fill(self, r, row):
        self.table.setItem(r, self.COL_CANON, QTableWidgetItem(row["canon"]))
        self.table.setItem(r, self.COL_LIGHTS, QTableWidgetItem(str(row["lights"])))
        self.table.setItem(r, self.COL_LAST, QTableWidgetItem((row["last_seen"] or "—")[:19]))
        combo = QComboBox()
        combo.addItem(i18n.t("planner.park_in"), 1)
        combo.addItem(i18n.t("planner.park_historic"), 0)
        if row["in_park"] is None:
            # Trzeci stan („nic nie powiedziałem") pokazujemy JAKO POZYCJĘ, żeby lista nie
            # udawała, że user już się wypowiedział — ale wybrać go z powrotem nie można.
            combo.addItem(i18n.t("planner.park_unsaid"), None)
            combo.setCurrentIndex(2)
        else:
            combo.setCurrentIndex(0 if row["in_park"] == 1 else 1)
        combo.activated.connect(lambda _i, tid=row["id"], c=combo: self._on_pick(tid, c))
        self.table.setCellWidget(r, self.COL_PARK, combo)
        self._combos[row["id"]] = combo

    def _on_pick(self, telescope_id, combo):
        value = combo.currentData()
        if value is None:
            return                       # pozycja „nie wypowiedziałeś się" jest tylko etykietą stanu
        if repo.set_telescope_park(self.con, telescope_id=telescope_id, in_park=value,
                                   now=self._now()):
            self.changed += 1
        idx = combo.findData(None)       # zdanie padło → etykieta stanu wyjściowego znika z listy
        if idx >= 0:
            combo.removeItem(idx)


class PlannerView(QWidget):
    """Ekran planera: nagłówek nocy + panel sterowania + lista celów.

    DWA UCHWYTY DO BAZY, jawnie w konstruktorze: `db_path` dla workera (własne połączenie w wątku)
    oraz `con` dla zapisów kuratelii na GŁÓWNYM wątku (T5d). Bez `db_path` (testy, `:memory:`)
    rachunek idzie inline na `con` — synchronicznie, bez wątku."""

    status_message = Signal(str)
    show_frames_for = Signal(object)     # T5e: kanony archiwum celu → most do gridu

    def __init__(self, con, db_path=None, now_fn=_utc_now_iso, parent=None, off_thread=True):
        super().__init__(parent)
        self.con = con
        self._db_path = db_path
        self._now = now_fn
        self._off_thread = off_thread
        self._gen = 0
        self._shown_gen = 0              # generacja, której wynik (albo błąd) stoi na ekranie
        self._worker = None
        self._thread = None
        self._result = None
        self._keep_canon = None          # cel, na który zaznaczenie ma wrócić po re-planie
        self._rig_chip = None            # None = soczewka „najlepsze dopasowanie" (D-0731-13)
        self._loading = True             # blokada re-planu na czas budowy kontrolek
        self._build()
        self._loading = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.replan)
        self.replan()

    # ---------------------------------------------------------------- budowa

    def _build(self):
        outer = QVBoxLayout(self)
        self.night_label = QLabel("")
        self.night_label.setWordWrap(True)
        self.counts_label = QLabel("")
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        head = QHBoxLayout()
        head.addWidget(self.night_label, 1)
        self.park_btn = QPushButton(i18n.t("planner.park_btn"))
        self.park_btn.clicked.connect(self._on_park)
        head.addWidget(self.park_btn)
        outer.addLayout(head)
        outer.addWidget(self.counts_label)
        outer.addWidget(self.notes_label)
        outer.addWidget(self._build_controls())
        self.chips_row = QHBoxLayout()
        outer.addLayout(self.chips_row)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)                 # nieokreślony — nie znamy postępu rachunku nocy
        self.busy.setVisible(False)
        outer.addWidget(self.busy)
        self.table = QTableView()
        self.model = PlannerTableModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_STRETCH_COL, QHeaderView.Stretch)
        hh.setStretchLastSection(False)
        self.table.setTextElideMode(Qt.ElideRight)     # 11 kolumn ma elidować, nie podnosić minimum okna
        outer.addWidget(self.table, 1)
        self.empty_note = QLabel(i18n.t("planner.empty"))
        self.empty_note.setAlignment(Qt.AlignCenter)
        self.empty_note.setWordWrap(True)
        self.empty_note.setVisible(False)
        outer.addWidget(self.empty_note, 1)
        outer.addWidget(self._build_row_panel())
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._sync_panel()

    def _build_row_panel(self):
        """Panel zaznaczonego celu — JEDYNE miejsce zapisu ekranu (kuratela). Kanon bierzemy
        z `row.target.canon`, czyli z assetu (`targets.load_targets`), NIGDY z wpisanego tekstu:
        „Eastern Veil" wskazuje naraz NGC6992 i NGC6995, więc zapis po nazwie potocznej trafiłby
        w losowy rekord. Pole „Szukaj" filtruje widok i niczego nie zapisuje — reguła jest więc
        spełniona KONSTRUKCYJNIE, nie regulaminowo."""
        self.panel = QGroupBox(i18n.t("planner.panel"))
        lay = QHBoxLayout(self.panel)
        self.panel_canon = QLabel("—")
        lay.addWidget(self.panel_canon)
        self.panel_status = QComboBox()
        for s in _STATUSES:
            self.panel_status.addItem(i18n.t(f"planner.status_{s}"), s)
        lay.addWidget(QLabel(i18n.t("planner.status")))
        lay.addWidget(self.panel_status)
        self.panel_priority = QSpinBox()
        self.panel_priority.setRange(0, 99)
        self.panel_priority.setSpecialValueText(i18n.t("planner.priority_none"))   # 0 → NULL
        lay.addWidget(QLabel(i18n.t("planner.priority")))
        lay.addWidget(self.panel_priority)
        self.panel_note = QLineEdit()
        self.panel_note.setPlaceholderText(i18n.t("planner.note_hint"))
        lay.addWidget(self.panel_note, 1)
        self.save_btn = QPushButton(i18n.t("planner.save_mark"))
        self.save_btn.clicked.connect(self._on_save_mark)
        lay.addWidget(self.save_btn)
        self.clear_btn = QPushButton(i18n.t("planner.clear_mark"))
        self.clear_btn.clicked.connect(self._on_clear_mark)
        lay.addWidget(self.clear_btn)
        self.frames_btn = QPushButton(i18n.t("planner.show_frames"))
        self.frames_btn.clicked.connect(self._on_show_frames)
        lay.addWidget(self.frames_btn)
        self.no_gaps_label = QLabel("")     # „✓ bez luk" = INFORMACJA, nigdy zapis (D-T4-d)
        lay.addWidget(self.no_gaps_label)
        return self.panel

    def _build_controls(self):
        box = QGroupBox(i18n.t("planner.controls"))
        lay = QHBoxLayout(box)
        form = QFormLayout()
        self.night_edit = QDateEdit()
        self.night_edit.setCalendarPopup(True)
        self.night_edit.setSpecialValueText(i18n.t("planner.night_auto"))
        # Minimum = wartość specjalna „noc bieżąca": DOPÓKI user nie tknie pola, noc wybiera rdzeń
        # (`targets.default_night` liczy dobę z DŁUGOŚCI stanowiska, nie ze strefy maszyny) —
        # podstawianie tu `QDate.currentDate()` byłoby DRUGIM właścicielem faktu „która to noc".
        self.night_edit.setMinimumDate(QDate(1970, 1, 1))
        self.night_edit.setDate(QDate(1970, 1, 1))
        self.night_edit.dateChanged.connect(self._queue_replan)
        form.addRow(i18n.t("planner.night"), self.night_edit)

        self.cirrus = QCheckBox(i18n.t("planner.layer_cirrus"))   # D-0731-9: domyślnie OFF
        self.cirrus.toggled.connect(self._queue_replan)
        form.addRow("", self.cirrus)

        self.status_combo = QComboBox()
        self.status_combo.addItem(i18n.t("planner.status_any"), None)
        for s in _STATUSES:
            self.status_combo.addItem(i18n.t(f"planner.status_{s}"), s)
        self.status_combo.currentIndexChanged.connect(self._queue_replan)
        form.addRow(i18n.t("planner.status"), self.status_combo)
        lay.addLayout(form)

        # Progi: RUNTIME, świadomie bez QSettings (D-0731-10 — „w BIEŻĄCYM wyszukiwaniu").
        thresholds = QFormLayout()
        self.min_size = self._spin(thresholds, "planner.min_size", 6.0, 0.0, 600.0, 1.0)
        self.min_dark = self._spin(thresholds, "planner.min_dark", 15.0, 0.0, 600.0, 1.0)
        self.max_mag = self._spin(thresholds, "planner.max_mag", 13.0, 0.0, 25.0, 0.5)
        self.min_alt = self._spin(thresholds, "planner.min_alt", 30.0, 0.0, 89.0, 5.0)
        lay.addLayout(thresholds)

        right = QFormLayout()
        self.min_hours = self._spin(right, "planner.min_hours", 1.0, 0.0, 100.0, 0.5)
        cost_row = QHBoxLayout()
        self.max_cost_on = QCheckBox()            # D-0731-14: próg kosztu domyślnie WYŁĄCZONY
        self.max_cost_on.toggled.connect(self._on_max_cost_toggled)
        self.max_cost = QDoubleSpinBox()
        self.max_cost.setRange(1.0, 100.0)
        self.max_cost.setSingleStep(0.5)
        self.max_cost.setValue(3.0)
        self.max_cost.setEnabled(False)
        self.max_cost.valueChanged.connect(self._queue_replan)
        cost_row.addWidget(self.max_cost_on)
        cost_row.addWidget(self.max_cost)
        right.addRow(i18n.t("planner.max_cost"), cost_row)

        find_row = QHBoxLayout()
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(i18n.t("planner.find_hint"))
        self.find_edit.returnPressed.connect(self.replan)
        btn = QPushButton(i18n.t("planner.find"))
        btn.clicked.connect(self.replan)
        find_row.addWidget(self.find_edit, 1)
        find_row.addWidget(btn)
        right.addRow(i18n.t("planner.find_label"), find_row)
        lay.addLayout(right)
        return box

    def _spin(self, form, key, value, lo, hi, step):
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setValue(value)
        w.valueChanged.connect(self._queue_replan)
        form.addRow(i18n.t(key), w)
        return w

    def _on_max_cost_toggled(self, on):
        self.max_cost.setEnabled(on)
        self._queue_replan()

    # ---------------------------------------------------------------- chipy zestawu (soczewka)

    def _rebuild_chips(self, result):
        """Chipy zestawów w porządku po lightach + „najlepsze dopasowanie" jako pozycja pierwsza.
        Chip jest SOCZEWKĄ (nic nie znika — `planner_model`), więc przełączenie NIE re-planuje:
        przelicza tylko komórki z tego samego `PlanResult`."""
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        names = (None,) + pm.rig_choices(result)
        if self._rig_chip not in names:          # zestaw zniknął (inny park) → wracamy do best-fit
            self._rig_chip = None
        for name in names:
            b = QToolButton()
            b.setCheckable(True)
            b.setText(i18n.t("planner.chip_best") if name is None else name)
            b.setChecked(name == self._rig_chip)
            b.clicked.connect(lambda _c=False, n=name: self._on_chip(n))
            self._chip_group.addButton(b)
            self.chips_row.addWidget(b)
        self.chips_row.addStretch(1)

    def _on_chip(self, name):
        self._rig_chip = name
        self._render_rows()

    # ---------------------------------------------------------------- rachunek

    def _params(self):
        """Parametry rachunku z kontrolek. `night=None` dopóki user nie tknął daty — wtedy noc
        wybiera rdzeń. Tekst w „Szukaj" włącza tryb `find`, który POMIJA progi (pytasz o konkretny
        obiekt — masz dostać jego okno, nawet gdy nigdy nie wschodzi); mówi o tym nota nad listą."""
        qd = self.night_edit.date()
        night = None if qd == self.night_edit.minimumDate() else date(qd.year(), qd.month(), qd.day())
        find = self.find_edit.text().strip() or None
        return {"night": night, "limit": None, "find": find,
                "layers": targets.ALL_LAYERS if self.cirrus.isChecked() else targets.DEFAULT_LAYERS,
                "status": self.status_combo.currentData(),
                "min_size": self.min_size.value(), "min_dark": self.min_dark.value(),
                "max_mag": self.max_mag.value(), "min_alt": self.min_alt.value(),
                "min_hours": self.min_hours.value(),
                "max_cost": self.max_cost.value() if self.max_cost_on.isChecked() else None}

    def _queue_replan(self, *_a):
        if not self._loading:
            self._debounce.start()

    def replan(self):
        """Policz plan pod BIEŻĄCE parametry. Nowa generacja unieważnia wynik w locie — jeden
        worker naraz, stary wynik ląduje w koszu (kontrolki zostają aktywne)."""
        self._debounce.stop()
        self._gen += 1
        if self._worker is not None:
            return                       # wynik w biegu i tak przyjdzie ze STARĄ generacją → odrzucony
        self._start(self._gen)

    def _start(self, gen):
        self.busy.setVisible(True)
        worker = PlanWorker(self._db_path, self._params(), gen,
                            con=None if self._db_path else self.con)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        if self._off_thread and self._db_path:
            self._thread = QThread(self)
            worker.moveToThread(self._thread)
            self._thread.started.connect(worker.run)
            worker.finished.connect(self._thread.quit)
            self._thread.finished.connect(self._cleanup_thread)
            self._thread.start()
        else:
            try:
                worker.run()             # inline: done/failed lecą direct = synchronicznie
            finally:
                self._worker = None
                self.busy.setVisible(False)

    def _cleanup_thread(self):
        # ŚWIĘTA KOLEJNOŚĆ (deadlock AB-BA GIL × ~QThread, natywny dump 2026-07-20 → `08992c4`):
        # worker.deleteLater() doręcza się w TEARDOWN wątku (Shiboken::Object::destroy →
        # PyGILState_Ensure). Bez wait() poniższy thread.deleteLater() mógłby doręczyć się na main
        # ZANIM wątek umrze: ~QThread czekałby na wątek TRZYMAJĄC GIL, a wątek na GIL. wait()
        # zwalnia GIL, więc wątek dokańcza destrukcję workera i umiera.
        self._worker.deleteLater()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.busy.setVisible(False)
        if self._pending_gen():
            self._start(self._gen)       # parametry zmieniły się w biegu → licz jeszcze raz

    def _pending_gen(self):
        """Czy na ekranie stoi coś starszego niż bieżące parametry. Liczymy WYŁĄCZNIE generacjami —
        „wynik pusty" i „wynik nieudany" to prawidłowe stany ekranu, a nie powód do kolejnego biegu
        (warunek na `self._result is None` zapętliłby ekran przy bazie bez stanowiska GPS)."""
        return self._shown_gen != self._gen

    @Slot(int, object)
    def _on_done(self, gen, result):
        if gen != self._gen:
            return                       # stale — świeży bieg wystartuje w cleanupie
        self._result = result
        self._shown_gen = gen
        self._rebuild_chips(result)
        self._render_header(result)
        self._render_rows()

    @Slot(int, str)
    def _on_failed(self, gen, message):
        if gen != self._gen:
            return
        self._result = None
        self._shown_gen = gen
        self.model.set_rows(())
        self.night_label.setText(message)
        self.counts_label.setText("")
        self.notes_label.setText("")
        self.empty_note.setVisible(False)
        self.table.setVisible(True)
        self.status_message.emit(message)

    # ---------------------------------------------------------------- render

    def _render_header(self, result):
        self.night_label.setText(pm.night_text(result))
        self.counts_label.setText(pm.counts_text(result))
        notes = [t for _lvl, t in pm.header_notes(result)]
        if self.find_edit.text().strip():
            notes.insert(0, i18n.t("planner.find_note"))
        self.notes_label.setText("\n".join(notes))
        self.notes_label.setVisible(bool(notes))

    def _render_rows(self):
        if self._result is None:
            return
        rows = pm.view_rows(self._result, self._rig_chip)
        self.model.set_rows(rows)
        empty = not rows
        self.empty_note.setVisible(empty)
        self.table.setVisible(not empty)
        # Zaznaczenie po zapisie wraca na TEN SAM cel, o ile został na liście: `skip` go z niej
        # zdejmuje i wtedy pusty panel jest UCZCIWĄ odpowiedzią („skreśliłeś go", nie „zgubiłem").
        if self._keep_canon is not None:
            for r, v in enumerate(rows):
                if v.canon == self._keep_canon:
                    self.table.selectRow(r)
                    break
            self._keep_canon = None
        self._sync_panel()

    # ---------------------------------------------------------------- panel wiersza (ZAPIS)

    def _on_row_selected(self, *_a):
        self._sync_panel()

    def _sync_panel(self):
        """Panel odbija ZAZNACZONY wiersz. Brak zaznaczenia = szczery disabled (UI nie kłamie);
        „Pokaż klatki celu" gaśnie osobno, gdy cel nie ma pokrycia — pusty filtr pokazałby
        w gridzie pełną bazę."""
        row = self.selected_row()
        self.panel.setEnabled(row is not None)
        if row is None:
            self.panel_canon.setText("—")
            self.panel_note.setText("")
            self.no_gaps_label.setText("")
            return
        src = row.source
        self.panel_canon.setText(row.canon)
        if src.plan_status is not None:
            self.panel_status.setCurrentIndex(self.panel_status.findData(src.plan_status))
        self.panel_priority.setValue(src.priority or 0)
        self.panel_note.setText(src.note or "")
        self.frames_btn.setEnabled(pm.can_show_frames(src))
        self.clear_btn.setEnabled(src.plan_status is not None)
        # Podpowiedź, nie automat (D-T4-d): status jest zdaniem CZŁOWIEKA, a luka zależy od suwaka
        # `min_hours` — automatyczne `done` czyniłoby trwały status funkcją parametru runtime.
        self.no_gaps_label.setText("" if src.coverage.gaps else i18n.t("planner.no_gaps"))

    def _selected_canon(self):
        row = self.selected_row()
        return None if row is None else row.source.target.canon

    def _on_save_mark(self):
        canon = self._selected_canon()
        if canon is None:
            return
        priority = self.panel_priority.value() or None      # 0 = „bez priorytetu" → NULL
        changed = repo.set_target_plan(
            self.con, canon=canon, status=self.panel_status.currentData(),
            priority=priority, note=self.panel_note.text().strip() or None, now=self._now())
        self.status_message.emit(i18n.t("planner.mark_saved" if changed else "planner.mark_same",
                                        canon=canon))
        if changed:
            self._replan_keeping(canon)

    def _on_clear_mark(self):
        canon = self._selected_canon()
        if canon is None:
            return
        changed = repo.clear_target_plan(self.con, canon=canon, now=self._now())
        self.status_message.emit(i18n.t("planner.mark_cleared" if changed else "planner.mark_same",
                                        canon=canon))
        if changed:
            self._replan_keeping(canon)

    def _replan_keeping(self, canon):
        """Po udanym zapisie licz plan od nowa (status zmienia listę — `skip` z niej znika)
        i wróć zaznaczeniem na ten sam cel, o ile został."""
        self._keep_canon = canon
        self.replan()

    def _on_park(self):
        """Dialog parku. Po zmianie oznaczeń plan liczy się od nowa — park ZMIENIA zestawy, więc
        stary wynik opisywałby inny sprzęt (a po scaleniu osi park bywa stęchły — `5dfe28b`)."""
        dlg = ParkDialog(self.con, self._now, parent=self)
        dlg.exec()
        if dlg.changed:
            self.status_message.emit(i18n.t("planner.park_changed", n=dlg.changed))
            self.replan()

    def _on_show_frames(self):
        """Most do gridu (D-0731-7, WĄSKO): emituj KANONY ARCHIWUM celu — jeden cel bywa
        w archiwum pod kilkoma nazwami naraz (`IC410` ORAZ `LBN807`), więc most oddaje sumę.
        Okno zamienia je na `object_id` i ustawia ISTNIEJĄCY facet Obiekt; planer nie składa
        drzewa filtra (druga ścieżka składania złamałaby SPOT `facet_model.compose`)."""
        row = self.selected_row()
        if row is None or not pm.can_show_frames(row.source):
            return
        self.show_frames_for.emit(tuple(row.source.coverage.archive_canons))

    # ---------------------------------------------------------------- cykl życia

    def selected_row(self):
        """`planner_model.ViewRow` zaznaczonego wiersza albo None (seam dla panelu i testów)."""
        sel = self.table.selectionModel()
        rows = sel.selectedRows() if sel else []
        return self.model.row_at(rows[0].row()) if rows else None

    def refresh(self):
        """Świeże klatki (pipeline) zmieniają pokrycie — przelicz nocy od nowa."""
        self.replan()

    def set_busy(self, running):
        """W biegu pipeline'u ekran nie liczy planu na wpół zapisanej bazie (spójnie z osiami)."""
        self.setEnabled(not running)

    def closeEvent(self, event):
        """Zamknięcie w biegu = unieważnienie generacją; wątek dokańcza i sprząta się sam."""
        self._gen += 1
        super().closeEvent(event)
