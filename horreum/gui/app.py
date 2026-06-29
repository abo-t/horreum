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
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from horreum import db, repo
from horreum.gui import queries

# Kolumny listy głównej — indeksy nazwane (czytelne handlery zamiast magicznych liczb).
COL_ID, COL_LABEL, COL_STATUS, COL_FRATIO, COL_FOCAL, COL_FRAMES = range(6)
HEADERS = ["ID", "Etykieta", "Status", "f/", "Ogniskowa", "Klatki"]


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
            self.status_message.emit("Brak teleskopów na osi — uruchom grouper (horreum group).")
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
            it = QListWidgetItem(f'#{m["id"]}  {m["label"] or "(bez etykiety)"}  ·  {m["status"]}')
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
                self.combo_target.addItem(f'#{t["id"]}  {t["label"] or "(bez etykiety)"}', t["id"])
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
    widokami w `QStackedWidget`. WŁAŚCICIEL połączenia `con` — zamyka poprzednie przy przełączeniu
    bazy i bieżące przy zamknięciu okna (top-level apki, w odróżnieniu od osadzonych widoków).

    ETAP 1: osadzony jest TYLKO widok osi teleskopu. Widok Pipeline (scan→group→resolve→delta)
    dochodzi w etapie 2 (`gui/pipeline.py`) przez `_mount_views`; pasek nawigacji pokazuje się
    automatycznie, gdy widoków jest ≥2."""

    def __init__(self, con=None, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._nav_buttons = []
        self.setWindowTitle("Horreum")
        self.resize(1000, 620)
        self._build_menu()
        self._build_central()
        if con is not None:
            self._mount_views()
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
        """(Prze)montuj widoki na bieżącym `con`. Wołane przy starcie z bazą i przy zmianie bazy."""
        self._clear_views()
        axis = TelescopeAxisView(self.con, now_fn=self._now)
        axis.status_message.connect(self._flash)
        self.axis_view = axis
        self._add_view("Oś teleskopu", axis)
        self._show_view(0)

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
        self._mount_views()
        self._sync_db_state()
        if old is not None:
            old.close()
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
    """Uruchom aplikację: `python -m horreum.gui [ścieżka.db]`. Z argumentem — otwiera bazę od razu;
    bez argumentu — okno startuje bez bazy (user otwiera/tworzy z menu Plik). Połączeniem zarządza
    `MainWindow` (zamyka je w `closeEvent`)."""
    import sys

    # Konsola Windows bywa cp1250 — komunikat ma polskie znaki; przełącz stdout na UTF-8 (best-effort,
    # jak `horreum.cli`), by `print` nie wywalił się na innym kodowaniu konsoli.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    argv = list(sys.argv[1:] if argv is None else argv)
    con = db.open_db(argv[0]) if argv else None
    app = QApplication.instance() or QApplication([])
    win = MainWindow(con)
    win.show()
    return app.exec()
