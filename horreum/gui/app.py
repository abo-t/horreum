"""Warstwa widżetów GUI (PySide6 — PLAN_gui §5, PLAN_gui_pipeline §2). Cienka powłoka nad rdzeniem:

- **Read path** = `horreum.gui.queries` (czyste SELECT-y, Qt-free) — lista aktywnych, członkowie
  scaleni „pod" kanonem, audyt eventów.
- **Write path** = WYŁĄCZNIE funkcje usera z `horreum.repo` (jedna klinga → `event`, `actor=user:*`
  składany w repo). Te widżety NIE wykonują żadnego `con.execute` — meta-tripwir AST
  (`tests/test_repo_safety.py`) skanuje też ten plik; każdy literał DML albo SQL dynamiczny tutaj
  wysadziłby bramkę. Cała logika domenowa (FSM/guardy/zapytania) mieszka poza Qt i jest przetestowana
  bez Qt; tu zostaje sama glue Q↔baza (skill `test-isolation-optional-dependencies`).

Kanon GUI (wizytator): stan widoczny BEZ klikania (status/licznik klatek/członkowie w kolumnach i
panelu), UI NIE KŁAMIE (akcja niemożliwa = przycisk wyłączony, nie klik→błąd), cofnięcie zamiast
„czy na pewno?" (scalanie jest odwracalne — `Cofnij scalenie`).

ETAP 2 (PLAN_gui_pipeline): okno aplikacji to `MainWindow` (menu Plik: Otwórz/Nowa baza, nawigacja
między widokami w `QStackedWidget`). Oś teleskopu z etapu 1 to teraz OSADZALNY widok `TelescopeAxisView`;
`TelescopeAxisWindow` zostaje jako cienka powłoka-okno (zgodność wstecz: `python -m horreum.gui` i testy)."""
import os
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from horreum import db, repo
from horreum.gui import queries

# Kolumny listy głównej — indeksy nazwane (czytelne handlery zamiast magicznych liczb).
# Nagłówek = telescop_canon (tożsamość osi po przejściu fitsmirror); Etykieta = nazwa usera.
COL_ID, COL_CANON, COL_LABEL, COL_STATUS, COL_FRATIO, COL_FOCAL, COL_FRAMES = range(7)
HEADERS = ["ID", "Nagłówek", "Etykieta", "Status", "f/", "Ogniskowa", "Klatki"]


def _fmt(v):
    """Liczba do komórki: None → '' (teleskop bez wartości), float bez zbędnych zer (`5.6`, `784`)."""
    return "" if v is None else f"{v:g}"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class TelescopeAxisView(QWidget):
    """Osadzalny widok osi TELESKOP: lista kanonicznych teleskopów (lewa) + szczegół zaznaczonego
    (prawa: członkowie scaleni pod nim, audyt). Akcje usera (`label`/`approve`/`merge`/`unmerge`)
    idą przez `repo`. Komunikaty statusu emituje sygnałem `status_message` — pasek statusu należy do
    okna-gospodarza (`MainWindow`/`TelescopeAxisWindow`), nie do widoku.

    `con` = otwarte połączenie RW (NIE własność widoku — zamyka je okno/gospodarz). `now_fn` = źródło
    czasu akcji (ISO-8601); domyślnie zegar UTC, wstrzykiwalne dla testów."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._loading = False                # tłumi itemChanged podczas programowego wypełniania
        self._source_mergeable = False       # czy zaznaczony wiersz może być źródłem scalenia
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: tabela aktywnych + pasek akcji ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Aktywne teleskopy (kanoniczne)"))
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.table)

        actions = QHBoxLayout()
        self.btn_approve = QPushButton("Zatwierdź")
        self.btn_approve.clicked.connect(self._on_approve)
        actions.addWidget(self.btn_approve)
        actions.addStretch(1)
        actions.addWidget(QLabel("Scal zaznaczony w:"))
        self.combo_target = QComboBox()
        self.combo_target.currentIndexChanged.connect(self._sync_merge_enabled)
        actions.addWidget(self.combo_target)
        self.btn_merge = QPushButton("Scal")
        self.btn_merge.clicked.connect(self._on_merge)
        actions.addWidget(self.btn_merge)
        lv.addLayout(actions)

        # --- prawa: szczegół zaznaczonego ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Scalone pod tym teleskopem:"))
        self.members = QListWidget()
        self.members.itemSelectionChanged.connect(self._sync_unmerge_enabled)
        rv.addWidget(self.members)
        self.btn_unmerge = QPushButton("Cofnij scalenie")
        self.btn_unmerge.clicked.connect(self._on_unmerge)
        rv.addWidget(self.btn_unmerge)
        rv.addWidget(QLabel("Historia (audyt):"))
        self.events = QListWidget()
        rv.addWidget(self.events)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self):
        """Przeładuj listę z read-modelu (źródło prawdy = baza; brak własnego cache, §5). Zachowuje
        zaznaczenie po `telescope_id`, a nie po numerze wiersza (po merge wiersze się przesuwają)."""
        prev = self._selected_telescope_id()
        self._loading = True
        try:
            rows = queries.active_telescopes(self.con)
            self.table.setRowCount(len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_cell(r, COL_ID, str(row["id"]), data=row["id"])
                self._set_cell(r, COL_CANON, row["telescop_canon"])
                self._set_cell(r, COL_LABEL, row["label"] or "", editable=True)
                self._set_cell(r, COL_STATUS, row["status"])
                self._set_cell(r, COL_FRATIO, _fmt(row["f_ratio_nominal"]))
                self._set_cell(r, COL_FOCAL, _fmt(row["focal_nominal"]))
                self._set_cell(r, COL_FRAMES, str(row["frame_count"]))
                if row["id"] == prev:
                    target_row = r
        finally:
            self._loading = False
        if target_row >= 0:
            self.table.selectRow(target_row)
        elif self.table.rowCount():
            self.table.selectRow(0)
        else:
            # pusty stan ma sensowny komunikat, nie gołe nagłówki (wizytator P3)
            self.status_message.emit("Brak teleskopów na osi — uruchom grupowanie (horreum group).")
        self._on_selection_changed()

    def _set_cell(self, r, c, text, *, editable=False, data=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # tylko etykieta jest edytowalna in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if data is not None:                  # telescope_id na kolumnie ID (kotwica wiersza)
            item.setData(Qt.UserRole, data)
        self.table.setItem(r, c, item)

    def _selected_telescope_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_ID)
        return item.data(Qt.UserRole) if item else None

    def _selected_status(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_STATUS)
        return item.text() if item else None

    def _on_selection_changed(self):
        """Odśwież panel szczegółu (członkowie + audyt) i stany przycisków dla zaznaczonego wiersza.
        Stany przycisków są SZCZERE: akcja, która i tak dałaby `ValueError`/no-op, jest wyłączona —
        UI nie kłamie (approve scalonego/już-approved, merge źródła z członkami albo bez targetu)."""
        tid = self._selected_telescope_id()

        self.members.clear()
        members = queries.merged_under(self.con, tid) if tid is not None else []
        for m in members:
            it = QListWidgetItem(
                f'#{m["id"]}  {m["label"] or m["telescop_canon"]}  ·  {m["status"]}')
            it.setData(Qt.UserRole, m["id"])
            self.members.addItem(it)

        self.events.clear()
        if tid is not None:
            for e in queries.axis_events(self.con, telescope_id=tid):
                self.events.addItem(f'{e["ts"]}  ·  {e["verb"]}  ·  {e["actor"]}')

        # Cel scalenia z PLACEHOLDEREM na wejściu (currentData=None): merge to świadoma deklaracja
        # „to ten sam teleskop" — nie wolno go wyzwolić jednym klikiem w przypadkowy pierwszy wiersz
        # (wizytator P2). `blockSignals` — przebudowa listy nie ma sypać `currentIndexChanged`.
        self.combo_target.blockSignals(True)
        self.combo_target.clear()
        self.combo_target.addItem("— wybierz cel —", None)
        for t in queries.active_telescopes(self.con):
            if t["id"] != tid:                # cel ≠ źródło → self-merge strukturalnie niemożliwy
                self.combo_target.addItem(
                    f'#{t["id"]}  {t["label"] or t["telescop_canon"]}', t["id"])
        self.combo_target.setCurrentIndex(0)  # placeholder — użytkownik musi wybrać cel świadomie
        self.combo_target.blockSignals(False)

        self.btn_approve.setEnabled(tid is not None and self._selected_status() != "approved")
        # źródło mergowalne tylko gdy kanoniczne BEZ członków (inwariant głębokość ≤ 1, §3a) i JEST jakiś
        # realny cel (count>1: placeholder + ≥1 teleskop). Sam wybór celu rozstrzyga `_sync_merge_enabled`.
        self._source_mergeable = (tid is not None and not members and self.combo_target.count() > 1)
        self._sync_merge_enabled()
        self._sync_unmerge_enabled()

    def _sync_merge_enabled(self):
        """„Scal" aktywny dopiero gdy źródło jest mergowalne ORAZ wskazano REALNY cel (nie placeholder).
        Wołane przy zmianie zaznaczenia i przy zmianie celu w combo — UI nie kłamie i nie scala na ślepo."""
        self.btn_merge.setEnabled(self._source_mergeable and self.combo_target.currentData() is not None)

    def _sync_unmerge_enabled(self):
        self.btn_unmerge.setEnabled(bool(self.members.selectedItems()))

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU osi (szczery disabled — UI nie kłamie, że
        można pisać, gdy worker pisze do bazy w tle, §6). Po etapie gospodarz woła `set_busy(False)`,
        co przez `_on_selection_changed` przywraca SZCZERE stany przycisków dla zaznaczenia."""
        if busy:
            self.btn_approve.setEnabled(False)
            self.btn_merge.setEnabled(False)
            self.btn_unmerge.setEnabled(False)
            self.combo_target.setEnabled(False)
        else:
            self.combo_target.setEnabled(True)
            self._on_selection_changed()

    # ---------------------------------------------------------------- akcje → repo (jedna klinga)

    def _flash(self, msg):
        self.status_message.emit(msg)

    def _on_item_changed(self, item):
        """Edycja in-line etykiety → `repo.label_telescope`. Pusty label → `ValueError` (kasowanie
        etykiety poza v1) złapany i pokazany, widok wraca do prawdy bazy (refresh)."""
        if self._loading or item.column() != COL_LABEL:
            return
        tid = self.table.item(item.row(), COL_ID).data(Qt.UserRole)
        try:
            changed = repo.label_telescope(
                self.con, telescope_id=tid, label=item.text(), now=self._now())
        except ValueError as e:
            self._flash(f"Etykieta odrzucona: {e}")
            self.refresh()
            return
        self._flash("Etykieta zapisana." if changed else "Etykieta bez zmian.")
        self.refresh()

    def _on_approve(self):
        tid = self._selected_telescope_id()
        if tid is None:
            return
        try:
            changed = repo.approve_telescope(self.con, telescope_id=tid, now=self._now())
        except ValueError as e:
            self._flash(f"Nie zatwierdzono: {e}")
            return
        self._flash("Zatwierdzono." if changed else "Już zatwierdzony.")
        self.refresh()

    def _on_merge(self):
        src = self._selected_telescope_id()
        tgt = self.combo_target.currentData()
        if src is None or tgt is None:        # brak źródła albo placeholder zamiast celu
            return
        try:
            changed = repo.merge_telescope(
                self.con, source_id=src, target_id=tgt, now=self._now())
        except ValueError as e:
            self._flash(f"Nie scalono: {e}")
            return
        self._flash(f"Scalono #{src} → #{tgt}." if changed else "Już scalony.")
        self.refresh()

    def _on_unmerge(self):
        sel = self.members.selectedItems()
        if not sel:
            return
        mid = sel[0].data(Qt.UserRole)
        try:
            changed = repo.unmerge_telescope(self.con, telescope_id=mid, now=self._now())
        except ValueError as e:
            self._flash(f"Nie cofnięto: {e}")
            return
        self._flash(f"Cofnięto scalenie #{mid}." if changed else "Już kanoniczny.")
        self.refresh()


# ============================================================ oś OBIEKT (PLAN_gui_object — READ-ONLY)

OBJ_COL_CANON, OBJ_COL_CATALOG, OBJ_COL_FRAMES = range(3)
OBJ_HEADERS = ["Obiekt", "Katalog", "Klatki"]
FRAME_COL_SHA, FRAME_COL_TEL, FRAME_COL_CAM, FRAME_COL_FILTER, FRAME_COL_DATE, FRAME_COL_PRESENT, \
    FRAME_COL_PATH = range(7)
FRAME_HEADERS = ["sha1 danych", "Teleskop", "Kamera", "Filtr", "Data", "Obecny", "Ścieżka"]


def _tel_facet_label(row):
    """Etykieta teleskopu do comba filtra: nazwa usera, a gdy brak (proposed) — `telescop_canon`
    (nazwa z nagłówka — po przejściu fitsmirror zawsze obecna i user-czytelna)."""
    return row["label"] or row["telescop_canon"]


def _tel_cell(row):
    """Etykieta teleskopu w tabeli klatek (wizytator P1 #1): nazwa usera, a gdy brak (teleskop
    jeszcze nienazwany — realny przypadek: cała oś `proposed`) — `telescop_canon` z nagłówka, by
    kolumna NIE milczała. Klatka bez teleskopu (config NULL) → '' (brak osi, nie brak danych)."""
    return row["telescope_label"] or row["telescop_canon"] or ""


class ObjectAxisView(QWidget):
    """Osadzalny widok osi OBIEKT (PLAN_gui_object, wariant A — READ-ONLY): biblioteka (obiekty →
    klatki, filtr po teleskopie/kamerze/filtrze) + kolejka przeglądu (obiekt-review / config-review /
    headerless) ze STANU. **Zero akcji zapisu** — rozwiązywanie review świadomie odłożone (import-legacy);
    UI to jawnie deklaruje („podgląd"), żeby nie kłamać obietnicą akcji. Meta-test AST pilnuje, że ten
    widok nie tyka SQL zapisu (sama glue Qt↔read-model).

    `con` = otwarte połączenie (NIE własność widoku). `now_fn` nieużywane (brak zapisu) — przyjmowane
    dla spójności sygnatury z `TelescopeAxisView` (montaż w `MainWindow`)."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._loading = False                 # tłumi sygnały selekcji podczas programowego wypełniania
        self._build_ui()
        self._load_facets()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # --- pasek filtra + jawna nota „podgląd" (UI nie kłamie obietnicą akcji) ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Teleskop:"))
        self.combo_tel = QComboBox()
        self.combo_tel.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_tel)
        bar.addWidget(QLabel("Filtr:"))
        self.combo_filter = QComboBox()
        self.combo_filter.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_filter)
        bar.addStretch(1)
        bar.addWidget(QLabel("Podgląd — rozwiązywanie review w przygotowaniu"))
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: biblioteka obiektów + kolejka przeglądu pod nią ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Biblioteka (obiekty)"))
        self.objects = QTableWidget(0, len(OBJ_HEADERS))
        self.objects.setHorizontalHeaderLabels(OBJ_HEADERS)
        self.objects.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.objects.setSelectionMode(QAbstractItemView.SingleSelection)
        self.objects.setEditTriggers(QAbstractItemView.NoEditTriggers)   # read-only
        self.objects.verticalHeader().setVisible(False)
        self.objects.itemSelectionChanged.connect(self._on_object_selected)
        lv.addWidget(self.objects)
        # Nota pustego stanu W WIDOKU (wizytator P1 #2): pusty filtr nie może komunikować się tylko
        # ulotnym flashem na statusbarze — user patrzy na pustą bibliotekę i pełną kolejkę i nie wie,
        # czy to błąd. Nota jest odkrywalna w obszarze tabeli, chowana gdy są obiekty.
        self.lib_empty = QLabel("Brak obiektów dla tego filtra — zmień filtr lub rozwiąż (resolve).")
        self.lib_empty.setAlignment(Qt.AlignCenter)
        self.lib_empty.setWordWrap(True)
        self.lib_empty.setVisible(False)
        lv.addWidget(self.lib_empty)

        lv.addWidget(QLabel("Kolejka przeglądu"))
        self.review = QListWidget()
        self.review.itemSelectionChanged.connect(self._on_review_selected)
        lv.addWidget(self.review)

        # --- prawa: klatki zaznaczonego obiektu / pozycji review ---
        right = QWidget()
        rv = QVBoxLayout(right)
        self.frames_label = QLabel("Klatki")
        rv.addWidget(self.frames_label)
        self.frames = QTableWidget(0, len(FRAME_HEADERS))
        self.frames.setHorizontalHeaderLabels(FRAME_HEADERS)
        self.frames.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.frames.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Kolumny wąskie (sha/tel/kam/filtr/data/obecny) do treści, Ścieżka bierze resztę — inaczej
        # stałe 100px zjadają panel i na Ścieżkę zostaje ~130px (widać tylko „R:...", ginie nazwa pliku).
        fh = self.frames.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(FRAME_COL_PATH, QHeaderView.Stretch)
        self.frames.verticalHeader().setVisible(False)
        rv.addWidget(self.frames)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)   # stretch: splitter zjada pionowy nadmiar, pasek filtra nie puchnie w pustkę

    # ---------------------------------------------------------------- facety filtra

    def _load_facets(self):
        """Wypełnij comba filtra realnie istniejącymi osiami (kanoniczne teleskopy + filtry). Placeholder
        „(wszystkie)" niesie `data=None` → brak filtra (wzór `(? IS NULL OR …)` w read-modelu)."""
        self._loading = True
        try:
            self.combo_tel.clear()
            self.combo_tel.addItem("(wszystkie)", None)
            for t in queries.telescope_facets(self.con):
                self.combo_tel.addItem(_tel_facet_label(t), t["id"])
            self.combo_filter.clear()
            self.combo_filter.addItem("(wszystkie)", None)
            for f in queries.filter_facets(self.con):
                self.combo_filter.addItem(f["filter_canon"], f["filter_canon"])
        finally:
            self._loading = False

    def _filters(self):
        return {"telescope_id": self.combo_tel.currentData(),
                "filter_canon": self.combo_filter.currentData()}

    def _on_filter_changed(self):
        if not self._loading:
            self.refresh()

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self):
        """Przeładuj bibliotekę i kolejkę z read-modelu (źródło prawdy = baza; brak cache). Zachowuje
        zaznaczenie obiektu po `object_id` (po zmianie filtra wiersze się przesuwają)."""
        prev = self._selected_object_id()
        flt = self._filters()
        self._loading = True
        try:
            rows = queries.library_objects(
                self.con, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"])
            self.objects.setRowCount(len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_obj_cell(r, OBJ_COL_CANON, row["canon"], data=row["id"])
                self._set_obj_cell(r, OBJ_COL_CATALOG, row["catalog"] or "")
                self._set_obj_cell(r, OBJ_COL_FRAMES, str(row["frame_count"]))
                if row["id"] == prev:
                    target_row = r
            self._load_review()
        finally:
            self._loading = False
        empty = self.objects.rowCount() == 0
        self.lib_empty.setVisible(empty)               # nota odkrywalna w widoku (P1 #2)
        self.objects.setVisible(not empty)
        if target_row >= 0:
            self.objects.selectRow(target_row)
        elif not empty:
            self.objects.selectRow(0)
        else:
            self.frames.setRowCount(0)
            self.status_message.emit(
                "Brak obiektów dla tego filtra — zeskanuj i rozwiąż (horreum resolve) lub zmień filtr.")
        self._on_object_selected()

    def _load_review(self):
        """Kolejka przeglądu ze STANU: obiekt-review (drążenie do klatek), liczniki config-review /
        headerless (informacyjne — bez drążenia, to inne osie/skan)."""
        q = queries.review_queue(self.con)
        self.review.clear()
        for r in q["object_review"]:
            it = QListWidgetItem(f'{r["object_raw"]}  ·  {r["n"]} klatek')
            it.setData(Qt.UserRole, r["object_raw"])
            self.review.addItem(it)
        # liczniki innych kanałów jako pozycje informacyjne (bez UserRole → nieklikane do klatek)
        info = QListWidgetItem(
            f'— config-review: {q["config_review_count"]}  ·  bez nagłówka: {q["headerless_count"]}')
        info.setFlags(Qt.ItemIsEnabled)        # nie do zaznaczenia (informacyjne)
        self.review.addItem(info)

    def _set_obj_cell(self, r, c, text, *, data=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self.objects.setItem(r, c, item)

    def _selected_object_id(self):
        sm = self.objects.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows:
            return None
        item = self.objects.item(rows[0].row(), OBJ_COL_CANON)
        return item.data(Qt.UserRole) if item else None

    def _on_object_selected(self):
        """Obiekt zaznaczony → klatki tego obiektu (z bieżącym filtrem). Czyści selekcję review (wzajemnie
        wykluczające źródła klatek: obiekt vs pozycja review)."""
        if self._loading:
            return
        oid = self._selected_object_id()
        if oid is None:
            return
        if self.review.selectedItems():
            self.review.clearSelection()
        flt = self._filters()
        rows = queries.object_frames(
            self.con, oid, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"])
        self.frames_label.setText("Klatki obiektu")
        self._fill_frames(rows, present_col=True)

    def _on_review_selected(self):
        """Pozycja obiekt-review zaznaczona → jej nierozwiązane klatki (drążenie review). Pozycje
        informacyjne (config/headerless) nie mają `UserRole` → ignorowane."""
        if self._loading:
            return
        sel = self.review.selectedItems()
        if not sel:
            return
        object_raw = sel[0].data(Qt.UserRole)
        if object_raw is None:                 # pozycja informacyjna (liczniki) — nie drąży
            return
        self.objects.clearSelection()
        rows = queries.object_review_frames(self.con, object_raw)
        self.frames_label.setText(f"Klatki do przeglądu: {object_raw}")
        self._fill_frames(rows, present_col=False)

    def _fill_frames(self, rows, *, present_col):
        """Wypełnij tabelę klatek. `present_col` — czy źródło niesie kolumnę `present` (biblioteka tak,
        review nie). `present=0` pokazujemy jako „nie" (R#7 — klatka WIDOCZNA mimo zniknięcia pliku)."""
        self.frames.setRowCount(len(rows))
        for r, row in enumerate(rows):
            keys = row.keys()
            self._set_frame_cell(r, FRAME_COL_SHA, (row["sha1_data"] or "")[:12])
            self._set_frame_cell(r, FRAME_COL_TEL, _tel_cell(row))
            self._set_frame_cell(r, FRAME_COL_CAM, row["camera_model"] or "")
            self._set_frame_cell(r, FRAME_COL_FILTER, row["filter_canon"] if "filter_canon" in keys else "")
            self._set_frame_cell(r, FRAME_COL_DATE, row["date_obs"] or "")
            if present_col and "present" in keys:
                self._set_frame_cell(r, FRAME_COL_PRESENT, "tak" if row["present"] else "nie")
            else:
                self._set_frame_cell(r, FRAME_COL_PRESENT, "")
            # Ścieżka: pokaż NAZWĘ PLIKU (elizja od prawej gubiłaby ją z pełnej ścieżki „R:\...");
            # pełna ścieżka w tooltipie (hover). Klatka bez lokalizacji (zniknięta) → jawny znacznik.
            path = row["path"] or ""
            self._set_frame_cell(r, FRAME_COL_PATH, os.path.basename(path) if path else "(brak lokalizacji)",
                                 tooltip=path or None)

    def _set_frame_cell(self, r, c, text, *, tooltip=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if tooltip:
            item.setToolTip(tooltip)
        self.frames.setItem(r, c, item)

    def set_busy(self, busy):
        """Spójność z gospodarzem: widok read-only nie ma akcji zapisu do wygaszenia. Realne ryzyko to
        SELECT w trakcie zapisu workera — gospodarz odświeża DOPIERO po `stage_finished` (NIE woła tu
        refresh w trakcie). Metoda istnieje dla jednolitego kontraktu montażu; no-op poza spójnością."""
        # celowo no-op: brak przycisków zapisu; odświeżanie sterowane przez gospodarza po stage_finished.


class TelescopeAxisWindow(QMainWindow):
    """Powłoka-okno osi teleskopu (zgodność wstecz — etap 1). Treść = osadzony `TelescopeAxisView`;
    okno dokłada tylko tytuł i pasek statusu (podpięty pod sygnał widoku). NIE jest właścicielem
    `con` (zamyka je wołający — `main`/fixture). Sygnatura `__init__` niezmieniona z etapu 1, by
    `test_gui_app.py` (import `COL_ID/COL_LABEL/TelescopeAxisWindow`, wywołanie `now_fn=`) był zielony.

    Dostęp do widżetów/handlerów (`table`, `btn_approve`, `_on_merge`, `refresh`, …) jest delegowany
    do osadzonego widoku przez `__getattr__` — testy etapu 1 sterują oknem jak dawniej, bez zmian."""

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Horreum — oś teleskopu")
        self.resize(960, 560)
        self.view = TelescopeAxisView(con, now_fn=now_fn)
        self.view.status_message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.setCentralWidget(self.view)
        self.statusBar()

    def __getattr__(self, name):
        # Delegacja do osadzonego widoku TYLKO dla atrybutów nieznanych oknu (QMainWindow ma własne
        # `close`/`show`/…). `__dict__` zamiast `getattr(self, ...)` — bez ryzyka rekurencji, gdy
        # `view` jeszcze nie istnieje (w trakcie __init__ przed przypisaniem).
        view = self.__dict__.get("view")
        if view is not None:
            return getattr(view, name)
        raise AttributeError(name)


class MainWindow(QMainWindow):
    """Okno aplikacji (PLAN_gui_pipeline §2): menu Plik (Otwórz/Nowa baza) + nawigacja między
    widokami w `QStackedWidget` (Pipeline ↔ Oś teleskopu). WŁAŚCICIEL połączenia `con` — otwiera je
    z `db_path`, zamyka poprzednie przy przełączeniu bazy i bieżące przy zamknięciu okna (top-level
    apki, w odróżnieniu od osadzonych widoków).

    Trzyma `db_path` (nie tylko `con`): worker pipeline'u potrzebuje ŚCIEŻKI, by otworzyć WŁASNE
    połączenie w swoim wątku (sqlite `check_same_thread` — `con` głównego wątku nie przechodzi).
    Po etapie pipeline'u odświeża read-model osi (WAL → zapisy workera widoczne) i przywraca
    szczere stany akcji osi (`set_busy`)."""

    def __init__(self, db_path=None, now_fn=_utc_now_iso, on_db_changed=None, parent=None):
        super().__init__(parent)
        self.con = None
        self.db_path = None
        self._now = now_fn
        # Wstrzykiwane wywołanie zwrotne „zmieniono bazę" (wzór jak `now_fn`): `main` podpina tu zapis
        # ostatniej ścieżki do trwałych ustawień; testy go nie podają → brak skutków ubocznych.
        self._on_db_changed = on_db_changed
        self._nav_buttons = []
        self.setWindowTitle("Horreum")
        self.resize(1000, 620)
        self._build_menu()
        self._build_central()
        if db_path is not None:
            self._open_path(db_path)
        else:
            self._sync_db_state()

    # ---------------------------------------------------------------- budowa szkieletu

    def _build_menu(self):
        m = self.menuBar().addMenu("&Plik")
        m.addAction("Otwórz bazę…", self._on_open_db)
        m.addAction("Nowa baza…", self._on_new_db)

    def _build_central(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        self._nav_bar = QHBoxLayout()
        self._nav_bar.addStretch(1)                 # przyciski wstawiane PRZED tym rozpychaczem
        outer.addLayout(self._nav_bar)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.setCentralWidget(central)
        self.statusBar()

    def _add_view(self, label, widget):
        """Zarejestruj widok w stacku + przycisk nawigacji. Pasek nawigacji widoczny od ≥2 widoków
        (samotny przycisk byłby szumem)."""
        idx = self.stack.addWidget(widget)
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self._show_view(idx))
        self._nav_bar.insertWidget(len(self._nav_buttons), btn)
        self._nav_buttons.append(btn)
        self._sync_nav_visibility()

    def _show_view(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self._nav_buttons):
            b.setChecked(i == idx)

    def _sync_nav_visibility(self):
        many = len(self._nav_buttons) >= 2
        for b in self._nav_buttons:
            b.setVisible(many)

    def _clear_views(self):
        for b in self._nav_buttons:
            self._nav_bar.removeWidget(b)
            b.deleteLater()
        self._nav_buttons.clear()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    # ---------------------------------------------------------------- montaż widoków na bazie

    def _mount_views(self):
        """(Prze)montuj widoki na bieżącej bazie. Wołane przy starcie z bazą i przy zmianie bazy.
        Pipeline pierwszy (wejście usera: pierwszy przebieg); oś teleskopu jako drugi widok."""
        from horreum.gui.pipeline import PipelineView          # lazy: Qt-import tylko gdy montujemy

        self._clear_views()
        pipeline = PipelineView(self.db_path, now_fn=self._now)
        pipeline.status_message.connect(self._flash)
        pipeline.stage_finished.connect(self._on_stage_finished)
        pipeline.running_changed.connect(self._on_pipeline_running)
        self.pipeline_view = pipeline
        self._add_view("Przetwarzanie", pipeline)

        axis = TelescopeAxisView(self.con, now_fn=self._now)
        axis.status_message.connect(self._flash)
        self.axis_view = axis
        self._add_view("Oś teleskopu", axis)

        obj = ObjectAxisView(self.con, now_fn=self._now)
        obj.status_message.connect(self._flash)
        self.object_view = obj
        self._add_view("Oś obiektu", obj)

        from horreum.gui.grid import FramesView              # lazy: Qt-import tylko gdy montujemy
        grid = FramesView(self.con, now_fn=self._now)
        grid.status_message.connect(self._flash)
        self.grid_view = grid
        self._add_view("Klatki", grid)
        self._show_view(0)

    def _on_stage_finished(self, name):
        """Etap pipeline'u zakończył zapis (worker, własne połączenie). Read-modele osi w głównym
        wątku odświeżamy DOPIERO TERAZ (nie w trakcie skanu — WAL → zapisy workera widoczne). Oś obiektu
        przeładowuje też facety (skan/resolver mogły dodać teleskopy/filtry/obiekty)."""
        self.axis_view.refresh()
        self.object_view._load_facets()
        self.object_view.refresh()
        self.grid_view._load_facets()
        self.grid_view.refresh()

    def _on_pipeline_running(self, running):
        """W trakcie etapu wyłącz akcje zapisu osi (szczery disabled). Nawigacja zostaje aktywna —
        user może zerknąć na oś; blokujemy tylko ZAPIS (§6: aktywny tylko „Anuluj" skanu)."""
        self.axis_view.set_busy(running)

    # ---------------------------------------------------------------- menu Plik: Otwórz/Nowa baza

    def _on_open_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Otwórz bazę Horreum", "", "Bazy SQLite (*.db *.sqlite);;Wszystkie pliki (*)")
        if path:
            self._open_path(path)

    def _on_new_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Nowa baza Horreum", "", "Bazy SQLite (*.db)")
        if path:
            self._open_path(path)

    def _open_path(self, path):
        """Otwórz+zmigruj bazę, przejmij ją na własność, przemontuj widoki. Stare połączenie (nasza
        własność) zamykamy — read-model nowej bazy musi widzieć właściwy plik."""
        new_con = db.open_db(path)
        old = self.con
        self.con = new_con
        self.db_path = path
        self._mount_views()
        self._sync_db_state()
        if old is not None:
            old.close()
        if self._on_db_changed is not None:        # zapamiętaj ostatnią bazę (trwałe ustawienia)
            self._on_db_changed(path)
        self._flash(f"Baza: {path}")

    def _sync_db_state(self):
        has = self.con is not None
        for b in self._nav_buttons:
            b.setEnabled(has)
        if not has:
            # bez timeoutu — to trwała podpowiedź pustego stanu, nie ulotny komunikat akcji
            self.statusBar().showMessage("Brak bazy — otwórz lub utwórz bazę (menu Plik).")

    def _flash(self, msg):
        self.statusBar().showMessage(msg, 5000)

    def closeEvent(self, event):
        # Top-level apka jest właścicielem połączenia — zamyka je przy zamknięciu okna.
        if self.con is not None:
            self.con.close()
            self.con = None
        super().closeEvent(event)


def main(argv=None):
    """Uruchom aplikację: `python -m horreum.gui [ścieżka.bazy]`. Z argumentem — otwiera wskazaną bazę
    od razu; bez argumentu — odtwarza OSTATNIO używaną bazę (zapamiętaną w trwałych ustawieniach), a
    gdy jej brak lub plik zniknął — okno startuje bez bazy (użytkownik wskazuje/tworzy z menu Plik).
    Każdy wybór bazy (z argumentu, menu „Otwórz", „Nowa") jest zapamiętywany jako ostatnia baza.
    Połączeniem zarządza `MainWindow` (zamyka je w `closeEvent`)."""
    import sys
    from pathlib import Path

    from PySide6.QtCore import QSettings

    # Konsola Windows bywa cp1250 — komunikat ma polskie znaki; przełącz stdout na UTF-8 (best-effort,
    # jak `horreum.cli`), by `print` nie wywalił się na innym kodowaniu konsoli.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication([])

    # Trwałe ustawienia (Windows: rejestr) — przechowują ścieżkę ostatnio otwartej bazy.
    settings = QSettings("Horreum", "Horreum")

    if argv:
        start = argv[0]
    else:
        start = settings.value("ostatnia_baza", None)
        # Ostatnia baza mogła zostać przeniesiona/usunięta — wtedy startujemy bez bazy (nie wybuchamy).
        if start and not Path(start).exists():
            start = None

    def zapamietaj_baze(path):
        settings.setValue("ostatnia_baza", path)

    win = MainWindow(start, on_db_changed=zapamietaj_baze)
    win.show()
    return app.exec()
