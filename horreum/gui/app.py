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
import re
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QLocale, QSettings, QUrl, Signal
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from horreum import db, macro as macro_mod, repo, resolver
from horreum.gui import i18n, mapproj, queries, theme
from horreum.gui.map_view import SitesMapView
from horreum.resolve._text import norm_alnum
from horreum.resolve.catalog import catalog_canon, catalog_label, xref
from horreum.resolve.objects import resolve_object
from horreum.resolve.solar import resolve_solar

# Kolumny listy głównej — indeksy nazwane (czytelne handlery zamiast magicznych liczb).
# Nagłówek = telescop_canon (tożsamość osi po przejściu fitsmirror); Etykieta = nazwa usera.
COL_ID, COL_CANON, COL_LABEL, COL_STATUS, COL_FRATIO, COL_FOCAL, COL_FRAMES = range(7)
# Stałe nagłówków trzymają KLUCZE katalogu (nie stringi) — etykieta rozwiązuje się `_headers()` w czasie
# BUDOWY widżetu, po `i18n.set_lang` w `main` (D-L1: stałe module-level ewaluują się przed set_lang, więc
# string zamroziłby domyślny PL; klucz jest językowo-neutralny).
HEADERS = ["col.id", "axis.tel.col.canon", "axis.tel.col.label", "col.status",
           "axis.tel.col.fratio", "axis.tel.col.focal", "col.frames"]


def _headers(keys):
    """Nagłówki kolumn z katalogu w czasie budowy tabeli (klucze → etykiety bieżącego języka)."""
    return [i18n.t(k) for k in keys]


def _fmt(v):
    """Liczba do komórki: None → '' (teleskop bez wartości), float bez zbędnych zer (`5.6`, `784`)."""
    return "" if v is None else f"{v:g}"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


_NUM_ALIGN = Qt.AlignRight | Qt.AlignVCenter   # liczby prawo-wyrównane (skanowalność magnitud, wizytator T1/#2)

# Rola motywu (nasza nazwa) → QPalette.ColorRole (F6 §7 — składanie QColor w warstwie widżetów z
# Qt-wolnych hexów `theme.palette_spec`). `disabled_text` obsłużone osobno (grupa Disabled).
_PALETTE_ROLES = {
    "window": QPalette.Window, "window_text": QPalette.WindowText,
    "base": QPalette.Base, "alt_base": QPalette.AlternateBase, "text": QPalette.Text,
    "button": QPalette.Button, "button_text": QPalette.ButtonText, "bright_text": QPalette.BrightText,
    "highlight": QPalette.Highlight, "highlight_text": QPalette.HighlightedText,
    "tooltip_base": QPalette.ToolTipBase, "tooltip_text": QPalette.ToolTipText,
    "link": QPalette.Link, "placeholder": QPalette.PlaceholderText,
}


def _build_palette(name):
    """Złóż QPalette z motywu `name` (MUSI być znormalizowany). Disabled dla tekstu = `disabled_text`."""
    spec = theme.palette_spec(name)
    pal = QPalette()
    for key, role in _PALETTE_ROLES.items():
        pal.setColor(role, QColor(spec[key]))
    disabled = QColor(spec["disabled_text"])
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    return pal


def apply_theme(app, name):
    """Zastosuj motyw do CAŁEJ aplikacji: Fusion + QPalette (propaguje do otwartych okien) + QSS
    akcentów; podłącz kolory stanów gridu/facetów (SPOT). `name` znormalizowany (`theme.normalize`).
    Import grid/facets lazy — unika cyklu z warstwą Porządków (F5R2#1) i pozostaje spójny ze stylem
    importów widoków w `_mount_views`."""
    from horreum.gui import facets, grid, map_view, projection_dialog, rows, tasks
    app.setStyle("Fusion")
    app.setPalette(_build_palette(name))
    app.setStyleSheet(theme.qss(name))
    grid.use_theme(name)
    facets.use_theme(name)
    projection_dialog.use_theme(name)   # kolor nagłówka raportu (P-C) — QSS ról nie sięga QPlainTextEdit
    tasks.use_theme(name)               # szarość wierszy bez roboty (P-C) — QBrush, nie QSS
    map_view.use_theme(name)         # kolory mapy z motywu (F8) — init na starcie + przełączenie
    rows.use_theme(name)             # człon drugi wierszy (P1) — delegat czyta kolor NA ŻYWO w paint,
                                     # więc zwykły repaint wystarczy (bez `refresh_theme`)
    use_theme(name)                  # szarość pozycji kolejki przeglądu bez drogi dalej (wiz #11)


# Szarość pozycji kolejki przeglądu, które NIE prowadzą nigdzie (informacyjne albo z zerem).
# Wzorzec `tasks._DIM`: QBrush, nie QSS — QSS nie sięga pojedynczej pozycji `QListWidget`.
_DIM: dict[str, QColor] = {}


def use_theme(name):
    """Kolor wygaszenia Z MOTYWU (wzorzec `tasks.use_theme`) — nigdy literałem, bo sztywna szarość
    przeszła kiedyś w motywie jasnym z kontrastem 3,54:1, poniżej AA."""
    _DIM["fg"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)             # init przy imporcie (QColor bez QApplication — jak stałe modułu)


def _fmt_event_ts(ts):
    """Znacznik czasu audytu do minut: „2026-07-02T18:21:44.4+00:00" → „2026-07-02 18:21" (mikrosekundy
    i strefa to szum w liście historii — wizytator C2). Pusty/nietypowy → zwróć jak jest."""
    return ts[:16].replace("T", " ") if ts and "T" in ts else (ts or "")


def _copy_reason(raw):
    """Powód nieczytelności do komórki (Z6): zdejmij prefiks dziennika — lista sama nazywa się
    „Kopie nieczytelne", więc powtórzony wstęp tylko odsuwa to, po co user tu przyszedł
    („ParseError: …"). Fraza ma JEDNEGO właściciela — `repo.UNREADABLE_REASON_PREFIX`; event bez
    prefiksu (miękkie lądowanie W1) idzie w całości. Brak eventu dla tej kopii → myślnik: „nie
    wiem" jest faktem, pusta komórka wygląda na brak danych."""
    if not raw:
        return i18n.t("copy.no_reason")
    prefix = repo.UNREADABLE_REASON_PREFIX
    return raw[len(prefix):] if raw.startswith(prefix) else raw


def _fmt_obs_date(s):
    """Data klatki do sekund: „…T19:45:02.6075262" → „…T19:45:02" (7 cyfr ułamka to szum wizualny —
    wizytator O2); pełna wartość zostaje w tooltipie. Pusty → ''."""
    return s.split(".")[0] if s and "T" in s else (s or "")


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
        lv.addWidget(QLabel(i18n.t("axis.tel.active")))
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(_headers(HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Szerokości: kolumny do treści, Etykieta (nazwa usera) rośnie — spójne z osią OBSERWATORIUM;
        # `stretchLastSection` rozpychał „Klatki" i ucinał ją na wąsko (wizytator T2).
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_LABEL, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self._edit_triggers = self.table.editTriggers()   # przywracane po set_busy(False) (wizytator T3)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.table)

        actions = QHBoxLayout()
        self.btn_approve = QPushButton(i18n.t("axis.tel.approve"))
        self.btn_approve.clicked.connect(self._on_approve)
        actions.addWidget(self.btn_approve)
        actions.addStretch(1)
        actions.addWidget(QLabel(i18n.t("axis.tel.merge_into")))
        self.combo_target = QComboBox()
        self.combo_target.currentIndexChanged.connect(self._sync_merge_enabled)
        actions.addWidget(self.combo_target)
        self.btn_merge = QPushButton(i18n.t("action.merge"))
        self.btn_merge.clicked.connect(self._on_merge)
        actions.addWidget(self.btn_merge)
        lv.addLayout(actions)

        # --- prawa: szczegół zaznaczonego ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel(i18n.t("axis.tel.merged_under")))
        self.members = QListWidget()
        self.members.itemSelectionChanged.connect(self._sync_unmerge_enabled)
        rv.addWidget(self.members)
        self.btn_unmerge = QPushButton(i18n.t("action.unmerge"))
        self.btn_unmerge.clicked.connect(self._on_unmerge)
        rv.addWidget(self.btn_unmerge)
        rv.addWidget(QLabel(i18n.t("axis.history")))
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
                self._set_cell(r, COL_FRATIO, _fmt(row["f_ratio_nominal"]), align=_NUM_ALIGN)
                self._set_cell(r, COL_FOCAL, _fmt(row["focal_nominal"]), align=_NUM_ALIGN)
                self._set_cell(r, COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
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
            self.status_message.emit(i18n.t("axis.tel.empty_status"))
        self._on_selection_changed()

    def _set_cell(self, r, c, text, *, editable=False, data=None, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # tylko etykieta jest edytowalna in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if align is not None:                 # liczby prawo-wyrównane (skanowalność, wizytator T1)
            item.setTextAlignment(align)
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
                f'#{m["id"]}  {queries.telescope_label(m)}  ·  {m["status"]}')
            it.setData(Qt.UserRole, m["id"])
            self.members.addItem(it)

        self.events.clear()
        if tid is not None:
            for e in queries.axis_events(self.con, telescope_id=tid):
                self.events.addItem(f'{_fmt_event_ts(e["ts"])}  ·  {e["verb"]}  ·  {e["actor"]}')

        # Cel scalenia z PLACEHOLDEREM na wejściu (currentData=None): merge to świadoma deklaracja
        # „to ten sam teleskop" — nie wolno go wyzwolić jednym klikiem w przypadkowy pierwszy wiersz
        # (wizytator P2). `blockSignals` — przebudowa listy nie ma sypać `currentIndexChanged`.
        self.combo_target.blockSignals(True)
        self.combo_target.clear()
        self.combo_target.addItem(i18n.t("axis.pick_target"), None)
        for t in queries.active_telescopes(self.con):
            if t["id"] != tid:                # cel ≠ źródło → self-merge strukturalnie niemożliwy
                self.combo_target.addItem(
                    f'#{t["id"]}  {queries.telescope_label(t)}', t["id"])
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
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # zamknij in-line edyt etykiety (T3)
        else:
            self.table.setEditTriggers(self._edit_triggers)
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
            self._flash(i18n.t("axis.tel.label_rejected", e=e))
            self.refresh()
            return
        self._flash(i18n.t("axis.tel.label_saved") if changed else i18n.t("axis.tel.label_unchanged"))
        self.refresh()

    def _on_approve(self):
        tid = self._selected_telescope_id()
        if tid is None:
            return
        try:
            changed = repo.approve_telescope(self.con, telescope_id=tid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.tel.approve_failed", e=e))
            return
        self._flash(i18n.t("axis.tel.approved") if changed else i18n.t("axis.tel.already_approved"))
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
            self._flash(i18n.t("axis.merge_failed", e=e))
            return
        self._flash(i18n.t("axis.merged", src=src, tgt=tgt) if changed
                    else i18n.t("axis.tel.already_merged"))
        self.refresh()

    def _on_unmerge(self):
        sel = self.members.selectedItems()
        if not sel:
            return
        mid = sel[0].data(Qt.UserRole)
        try:
            changed = repo.unmerge_telescope(self.con, telescope_id=mid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.unmerge_failed", e=e))
            return
        self._flash(i18n.t("axis.unmerged", mid=mid) if changed
                    else i18n.t("axis.tel.already_canonical"))
        self.refresh()


# ============================================================ oś OBIEKT (PLAN_gui_object + #8/P4)

OBJ_COL_CANON, OBJ_COL_CATALOG, OBJ_COL_FRAMES = range(3)
OBJ_HEADERS = ["object.col.name", "object.col.catalog", "col.frames"]
FRAME_COL_SHA, FRAME_COL_TEL, FRAME_COL_CAM, FRAME_COL_FILTER, FRAME_COL_DATE, FRAME_COL_PRESENT, \
    FRAME_COL_PATH = range(7)
FRAME_HEADERS = ["frame.col.sha", "frame.col.telescope", "frame.col.camera", "frame.col.filter",
                 "frame.col.date", "frame.col.present", "col.path"]
# Tryb „kopie" prawego panelu (Z6/P4 — drążenie kubełka `unreadable` do dokładnych location).
COPY_COL_PATH, COPY_COL_VOLUME, COPY_COL_PRESENT, COPY_COL_MARKED, COPY_COL_REASON = range(5)
COPY_HEADERS = ["col.path", "copy.col.volume", "copy.col.present", "copy.col.marked",
                "copy.col.reason"]


class AssignObjectDialog(QDialog):
    """Dialog ręcznego przypisania obiektu grupie review (#8, P4, D-P4-3): wybór ISTNIEJĄCEGO obiektu
    z biblioteki (combo `canon · catalog`) ALBO nowe oznaczenie katalogowe parsowane jak resolver
    (`catalog_canon` + `xref` — „IC 1795" → IC1795). Świadomie BEZ wolnego tekstu jako canon:
    `object.canon` nie ma deduplikacji semantycznej, a śmieciowego obiektu nic by nie posprzątało.

    Walidacja PRZED akceptacją: placeholder zamiast domyślnego realnego celu; akcja aktywna dopiero
    po jawnym wyborze albo parsowalnym oznaczeniu. Błąd konfliktu aliasu (`alias_target` — pre-check
    UX; ostateczny guard w `repo.user_assign_object`, TOCTOU) zostawia dialog otwarty. Nazwa
    rozwiązywalna katalogowo → nota o regule „katalog bije alias". Wynik walidacji ląduje w
    `self.selected` = `(canon, catalog, kind)` (`kind=None` dla obiektu istniejącego — repo go nie
    INSERTuje, więc pole nieużywane)."""

    def __init__(self, con, *, object_raw, alias_norm, frame_count, parent=None):
        super().__init__(parent)
        self.con = con
        self.alias_norm = alias_norm
        self.selected = None
        self.setWindowTitle(i18n.t("assign.title"))
        lay = QVBoxLayout(self)

        head = QLabel(i18n.t_plural("assign.group_head", frame_count, name=object_raw)
                      + "\n" + i18n.t("assign.alias_remembered"))
        head.setWordWrap(True)
        lay.addWidget(head)
        if resolve_solar(object_raw) or resolve_object(object_raw):
            note = QLabel(i18n.t("assign.catalog_note"))
            note.setWordWrap(True)
            lay.addWidget(note)

        lay.addWidget(QLabel(i18n.t("assign.existing_object")))
        self.combo = QComboBox()
        self.combo.addItem(i18n.t("assign.pick_object"), None)
        self._objects = queries.library_objects(con)          # bez filtra — pełna biblioteka
        for o in self._objects:
            self.combo.addItem(f"{o['canon']}  ·  {o['catalog'] or '—'}",
                               (o["id"], o["canon"], o["catalog"]))
        lay.addWidget(self.combo)

        lay.addWidget(QLabel(i18n.t("assign.new_designation")))
        self.designation = QLineEdit()
        self.designation.setPlaceholderText(i18n.t("assign.designation_placeholder"))
        lay.addWidget(self.designation)

        self.error = QLabel("")
        self.error.setProperty("role", "error")     # kolor z motywu (P-C) — sztywny #b00020 był ślepy na dark
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.accept_btn = buttons.button(QDialogButtonBox.Ok)
        self.accept_btn.setText(i18n.t_plural("assign.accept_btn", frame_count))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.combo.currentIndexChanged.connect(self._sync_accept_enabled)
        self.designation.textChanged.connect(self._sync_accept_enabled)
        self._sync_accept_enabled()

    def _fail(self, msg):
        self.error.setText(msg)

    def _sync_accept_enabled(self):
        """Akcja wymaga JAWNEGO celu; tekst oznaczenia walidujemy na żywo, żeby disabled miał powód."""
        text = self.designation.text().strip()
        valid_designation = bool(catalog_canon(text)) if text else False
        self.accept_btn.setEnabled(valid_designation if text else self.combo.currentData() is not None)
        self.error.clear()                                  # wejście się zmieniło → stary błąd nieaktualny
        if text and not valid_designation:
            self._fail(i18n.t("assign.unknown_designation", text=text))

    def _validate_and_accept(self):
        """Waliduj wybór; poprawny → `self.selected` + accept, błąd → nota i dialog zostaje."""
        text = self.designation.text().strip()
        if text:
            cc = catalog_canon(text)
            if not cc:
                return self._fail(i18n.t("assign.unknown_designation", text=text))
            canon, catalog, kind = xref(cc), catalog_label(xref(cc)), "deep_sky"
            object_id = next((o["id"] for o in self._objects if o["canon"] == canon), None)
        else:
            selected = self.combo.currentData()
            if selected is None:
                return self._fail(i18n.t("assign.pick_or_designate"))
            object_id, canon, catalog = selected
            kind = None                                   # obiekt istnieje — repo nie INSERTuje
        target = queries.alias_target(self.con, self.alias_norm)
        if target is not None and target != object_id:
            target_canon = next((o["canon"] for o in self._objects if o["id"] == target), target)
            return self._fail(i18n.t("assign.alias_conflict", target=target_canon))
        self.selected = (canon, catalog, kind)
        self.accept()


# ---------------------------------------------------------------- P-D: nazwa wraca do NAGŁÓWKA
# Klatka, której nagłówek MILCZY o obiekcie (czwarty przypadek obok uniwersalium/regionu/literówki),
# dostaje kartę `OBJECT` w PLIKU — propozycja ze ścieżki, zapis z ręki człowieka, oś wypełnia zwykły
# `Rozwiąż` (header-primary). Zapis do `frame.object_id` z ręki naprawiłby bazę i zostawił plik niemy:
# WBPP/PixInsight dalej nie wiedzą, czym jest klatka, a każda przyszła baza z tego drzewa wymagałaby
# powtórzenia decyzji (D-PD-1).

_OBJECT_CARD_MAX = 68     # rekord nagłówka FITS: powyżej astropy wchodzi w CONTINUE (nagłówek ASCII)


def _witness_folder(path):
    """Świadek 1 propozycji: segment PO `LIGHTS` (KOTWICA, nie stała głębokość — drzewo archiwum ma
    różne poziomy), przepuszczony przez `catalog_canon`. Brak kotwicy/nieparsowalny → None."""
    segs = [s for s in re.split(r"[\\/]+", path or "") if s]
    dirs = segs[:-1]                                  # ostatni segment to nazwa pliku
    for i, seg in enumerate(dirs):
        if seg.strip().upper() == "LIGHTS" and i + 1 < len(dirs):
            return catalog_canon(dirs[i + 1])
    return None


def _witness_filename(path):
    """Świadek 2: stem nazwy pliku cięty po `_`, PIERWSZY człon parsujący się katalogowo — nie
    prefiks. Prefiks jest martwy dla plików przemianowanych własnym rename v2: `DEFAULT_TEMPLATE`
    stawia na pierwszej pozycji `datetime`, więc oznaczenie ląduje w środku nazwy."""
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    for seg in stem.split("_"):
        cc = catalog_canon(seg)
        if cc:
            return cc
    return None


def _path_proposal(path):
    """Propozycja kanonu ze ścieżki = ZGODNE zeznanie DWÓCH świadków (folder + nazwa pliku), albo
    None. Ścieżka jest DOWODEM, nie prawdą: rozjazd zostawia pole puste i decyzję człowiekowi."""
    a, b = _witness_folder(path), _witness_filename(path)
    return a if a and a == b else None


def _validate_object_value(con, text):
    """Walidacja PRZED zapisem (D-PD-4) → `(wartość_do_pliku | None, powód_odmowy | None)`.

    Kolejność: `strip()` → `catalog_canon()` → bramki. Do pliku idzie forma PO `catalog_canon`
    (kolaps spacji + upper), nigdy surowy segment ścieżki — inaczej „podgląd == plik" rozjechałoby
    się o białe znaki. Forma jest PRZED `xref` (D-PD-9): zapis po `xref` przepisywałby konwencję
    użytkownika w JEGO plikach (folder `M82` → karta `NGC3034`).

    Bramki odmowy (zero zapisu): pusto po `strip()`; nie-ASCII (nagłówek FITS jest ASCII);
    dłuższe niż rekord. Bez nich taki kanon padłby dopiero w `writeto` i wrócił jako 'failed'
    („coś się zepsuło") zamiast czystej odmowy. CZWARTA bramka — nazwa NIEROZPOZNAWALNA przez
    resolver — jest dodana ponad brief świadomie: cały wariant C stoi na tym, że po zapisie oś
    wypełni się sama, a nazwa, której przebieg nie zna, przeniosłaby klatkę tylko z kubełka
    „bez nazwy" do „nierozpoznane" — po nieodwracalnej mutacji pliku.

    Pytanie czwartej bramki zadaje `resolver.name_resolves` — CAŁA drabina nazwy (solar → katalog →
    alias), nie sam `resolve_object`; dlatego walidacja potrzebuje `con`. Bramka pytająca węższym
    predykatem niż przebieg odmawiałaby nazw, które przebieg rozwiązuje (`Moon`, `WR134`)."""
    raw = (text or "").strip()
    if not raw:
        return None, i18n.t("repair.err.empty")
    value = catalog_canon(raw) or raw
    if not value.isascii():
        return None, i18n.t("repair.err.ascii", text=value)
    if len(value) > _OBJECT_CARD_MAX:
        return None, i18n.t("repair.err.too_long", n=len(value), max=_OBJECT_CARD_MAX)
    if not resolver.name_resolves(con, value):
        return None, i18n.t("repair.err.unresolvable", text=raw)
    return value, None


class RepairHeaderDialog(QDialog):
    """„Napraw nagłówek…" — dopisanie karty `OBJECT` do PLIKÓW klatek bezimiennych (P-D, wariant C).

    Trzy takty (D-PD-6): **zapis karty → re-sync zeznania (automatyczny, w `writeback.commit`) →
    `Rozwiąż`**. Takty 1–2 dzieją się TU jednym kliknięciem („Zapisz karty"): staging i commit to
    JEDEN takt, bo sam staging osierociłby `run_id`, którego żadna inna powierzchnia nie zna.
    Takt 3 NIE uruchamia resolvera z dialogu — deleguje do `PipelineView.run_stage('resolve')`
    (wołanie inline zamroziłoby GUI na 15k klatek i ominęło bramkę `running_changed`).

    Mutacja pliku idzie WYŁĄCZNIE przez `writeback` (jedna klinga), staging WYŁĄCZNIE przez
    `repo.stage_pending`; ten dialog nie zna SQL. Bramki celu liczy `macro.resolve_target` — TA SAMA
    funkcja, która potem odsieje cel przy zapisie, więc lista pominiętych nie jest drugą regułą,
    tylko tym samym zdaniem powiedzianym wcześniej.

    Cofanie ma OKNO: „Cofnij" żyje od udanego zapisu do zamknięcia okna (i tylko przed taktem 3) —
    poza nim nie ma powierzchni cofania nagłówka, dlatego dialog pokazuje `commit_id`, a kotwicą
    ratunku zostaje kopia bajtowa."""

    changed = Signal()          # zapis/cofnięcie doszło do skutku → gospodarz odświeża kolejkę
    busy_changed = Signal(bool)  # ta powierzchnia pisze do plików → mutex drugiej (D-PD-3)

    def __init__(self, con, *, rows, db_path, now_fn, run_stage_fn=None, parent=None):
        super().__init__(parent)
        # Lazy: `wb_worker` ciągnie `writeback` → astropy; start apki nie ma za co płacić, dopóki
        # user nie otworzy tego okna (wzorzec lazy-importów widoków w `_mount_views`).
        from horreum.gui.wb_worker import WritebackRunner

        self.con = con
        self._now = now_fn
        self._run_stage = run_stage_fn
        self._run_id = None
        self._commit_id = None
        self._committed = False   # karty są w plikach → zapis milczy do cofnięcia
        self._runner = WritebackRunner(db_path, now_fn=now_fn, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)   # uchwyt zna OBA końce operacji
        self._groups = []       # [{folder, rows, check, edit, preview}]
        self._skipped = []      # [(path, powód)] — jawnie widoczne, nigdy ciche
        self.setWindowTitle(i18n.t("repair.title"))
        self._split_rows(rows)
        self._build_ui()
        self._sync_preview()

    # ---------------------------------------------------------------- podział wejścia
    def _split_rows(self, rows):
        """Wiersze read-modelu → grupy po FOLDERZE + lista pominiętych z powodem. Grupowanie
        SŁOWNIKIEM (kolejność pierwszego wystąpienia), bo porządek po pełnej ścieżce przeplata
        katalog z podkatalogiem. Folder bierzemy z celu writebacku, nie z `path` read-modelu —
        żeby grupa opisywała dokładnie ten plik, który zostanie zapisany."""
        ids = [r["frame_id"] for r in rows]
        targets = {}
        for t in queries.writeback_frame_targets(self.con, ids):
            targets.setdefault(int(t["frame_id"]), []).append(t)
        groups = {}
        for r in rows:
            trows = targets.get(int(r["frame_id"]))
            if not trows:                       # klatka zniknęła z bazy między odczytem a otwarciem
                self._skipped.append((r["path"] or "", i18n.t("repair.skip.gone")))
                continue
            target, reason = macro_mod.resolve_target(trows)
            if target is None:
                self._skipped.append((r["path"] or "", reason or ""))
                continue
            groups.setdefault(os.path.dirname(target["path"]), []).append(
                dict(frame_id=r["frame_id"], path=target["path"]))
        for folder, items in groups.items():
            proposals = {_path_proposal(it["path"]) for it in items}
            common = proposals.pop() if len(proposals) == 1 else None
            self._groups.append({"folder": folder, "rows": items, "proposal": common})

    # ---------------------------------------------------------------- budowa UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        n_frames = sum(len(g["rows"]) for g in self._groups)
        head = QLabel(i18n.t("repair.head", frames=n_frames, groups=len(self._groups)))
        head.setWordWrap(True)
        lay.addWidget(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        gl = QVBoxLayout(inner)
        for g in self._groups:
            row = QHBoxLayout()
            g["check"] = QCheckBox(i18n.t("repair.group", folder=os.path.basename(g["folder"]),
                                          n=len(g["rows"])))
            g["check"].setToolTip(g["folder"])
            # Grupa z parsowalną propozycją jest ZAZNACZONA: bez tego cztery grupy kosztują cztery
            # dodatkowe kliknięcia, a obietnica „≤ 4 interakcje" przestaje być prawdziwa.
            g["check"].setChecked(bool(g["proposal"]))
            row.addWidget(g["check"], 2)
            g["edit"] = QLineEdit(g["proposal"] or "")
            g["edit"].setPlaceholderText(i18n.t("repair.no_proposal"))
            g["edit"].textChanged.connect(self._sync_preview)
            g["check"].toggled.connect(self._sync_preview)
            row.addWidget(g["edit"], 1)
            g["preview"] = QLabel("")
            g["preview"].setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(g["preview"], 2)
            gl.addLayout(row)
        gl.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area, 1)

        if self._skipped:
            lay.addWidget(QLabel(i18n.t("repair.skipped_head", n=len(self._skipped))))
            lst = QListWidget()
            for path, reason in self._skipped:
                lst.addItem(f"{os.path.basename(path) or i18n.t('object.no_location')} — {reason}")
            lst.setMaximumHeight(90)
            lay.addWidget(lst)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)   # `commit_id` do skopiowania
        lay.addWidget(self.status)
        self.error = QLabel("")
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        actions = QHBoxLayout()
        self.save_btn = QPushButton(i18n.t("repair.save_btn"))
        _f = self.save_btn.font(); _f.setBold(True); self.save_btn.setFont(_f)   # złota akcja: WAGA, nie kolor (P-C)
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)
        self.undo_btn = QPushButton(i18n.t("grid.action.undo"))
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)
        self.resolve_btn = QPushButton(i18n.t("repair.resolve_btn"))
        self.resolve_btn.setVisible(False)
        self.resolve_btn.clicked.connect(self._on_resolve)
        actions.addWidget(self.resolve_btn)
        actions.addStretch(1)
        close_btn = QPushButton(i18n.t("repair.close_btn"))
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        lay.addLayout(actions)

    # ---------------------------------------------------------------- podgląd „co wpiszemy"
    def _sync_preview(self):
        """Podgląd DOKŁADNIE tego, co pójdzie do pliku (`OBJECT = 'NGC7635'`), plus szczery stan
        akcji. Grupa zaznaczona z niepoprawną wartością pokazuje powód przy sobie — user nie musi
        klikać, żeby dowiedzieć się, czemu zapis nie ruszy."""
        ready, first_err = 0, None
        for g in self._groups:
            if not g["check"].isChecked():
                g["preview"].setText("")
                continue
            value, err = _validate_object_value(self.con, g["edit"].text())
            if err:
                g["preview"].setText(i18n.t("repair.preview_none"))
                first_err = first_err or i18n.t(
                    "repair.err.group", folder=os.path.basename(g["folder"]), reason=err)
            else:
                g["preview"].setText(i18n.t("repair.preview", value=repr(value)))
                ready += len(g["rows"])
        self.error.setText(first_err or "")     # wejście się zmieniło → stary błąd nieaktualny
        # Po udanym commicie zapis MILCZY do czasu cofnięcia: karty są już w plikach, więc drugie
        # kliknięcie dałoby tylko listę „karta już istnieje" — szczery disabled zamiast pustego biegu.
        self.save_btn.setEnabled(ready > 0 and first_err is None and not self._committed
                                 and not self._runner.is_busy)
        # Licznik mówi, ile ZOSTAŁO do zapisania — nie ile BYŁO gotowe. Po commicie zostaje zero,
        # więc liczba znika razem z sensem drugiego kliknięcia; zamrożone „Zapisz karty (23)"
        # pod wygaszonym przyciskiem opisywało przeszłość (firsthand pilota P-D na `R:`).
        self.save_btn.setText(i18n.t("repair.save_btn_n", n=ready)
                              if ready and not self._committed else i18n.t("repair.save_btn"))

    def _fail(self, msg):
        self.error.setText(msg)

    # ---------------------------------------------------------------- takt 1+2: staging + commit
    def _on_save(self):
        """Staging i commit JEDNYM taktem. Walidacja WSZYSTKICH zaznaczonych grup PRZED
        jakimkolwiek zapisem — częściowy staging po odmowie zostawiłby otwarty run."""
        if self._runner.is_busy:
            return
        self.error.clear()
        plan = []
        for g in self._groups:
            if not g["check"].isChecked():
                continue
            value, err = _validate_object_value(self.con, g["edit"].text())
            if err:
                return self._fail(i18n.t("repair.err.group", folder=os.path.basename(g["folder"]),
                                         reason=err))
            plan.append((g, value))
        if not plan:
            return self._fail(i18n.t("repair.err.nothing"))

        run_id = uuid.uuid4().hex
        staged, skipped = 0, []
        for g, value in plan:
            # `repr(value)` — bo `expr` traktuje gołe `NGC7635` jak NAZWĘ ZMIENNEJ (przy kolizji
            # z keywordem wpisalibyśmy WARTOŚĆ TEJ KARTY), a sam cudzysłów nie wystarcza: kanon
            # z apostrofem wysadza kompilację i makro wpisałoby surową zawartość pola razem
            # z cudzysłowami. Python dobiera cudzysłów i escape sam.
            md = macro_mod.MacroDef(assign=macro_mod.Assign(
                keyword="OBJECT", op="add", expr=repr(value), value_type="str"))
            run = macro_mod.run_macro(
                md, [it["frame_id"] for it in g["rows"]],
                targets_fn=lambda ids: queries.writeback_frame_targets(self.con, ids),
                cards_fn=lambda fid: queries.frame_cards(self.con, fid),
                run_id=run_id)
            for p in run.touched:
                repo.stage_pending(
                    self.con, run_id=run_id, location_id=p.location_id, keyword=p.keyword,
                    idx=p.idx, op=p.op, old_value=p.old_value, new_value=p.new_value,
                    new_type=p.new_type, new_comment=p.comment,
                    expected_header_hash=p.expected_header_hash)
            staged += len(run.touched)
            skipped += [(s.path, s.reason) for s in run.skipped]
        if staged == 0:
            repo.clear_pending_for_run(self.con, run_id)     # nic do zapisu → run nie zostaje otwarty
            return self._fail(i18n.t("repair.err.all_skipped",
                                     reason=(skipped[0][1] if skipped else "")))

        self._run_id = run_id
        self._begin_progress(staged)
        self._runner.start("commit", run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed)

    def _begin_progress(self, total):
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.save_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.resolve_btn.setEnabled(False)

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"{done}/{total} · {os.path.basename(path)}")

    def _after_commit(self, op, res):
        """Post-processing commitu (wątek główny). Udany zapis → jednorazowe „Cofnij" + „Rozwiąż
        teraz"; `commit_id` WIDOCZNY, bo po zamknięciu okna to jedyny uchwyt do cofnięcia z ręki."""
        self.bar.setVisible(False)
        parts = [i18n.t("grid.wb.applied", n=len(res.applied))]
        if res.blocked:
            parts.append(i18n.t("grid.wb.blocked", n=len(res.blocked)))
        if res.failed:
            parts.append(i18n.t("grid.wb.errors", n=len(res.failed)))
        if res.skipped:
            parts.append(i18n.t("grid.wb.skipped", n=len(res.skipped)))
        summary = " · ".join(parts)
        detail = next((fr.reason for fr in (res.blocked + res.failed) if fr.reason), None)
        if detail:
            summary += i18n.t("grid.wb.detail_sep", detail=detail)
        if res.applied and res.commit_id is not None:
            self._commit_id = res.commit_id
            self._committed = True
            summary += i18n.t("grid.wb.commit_id", id=res.commit_id)
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
            self._run_id = None                  # run domknięty commitem (R#5) — nie kasuj przy zamknięciu
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()
        self.status.setText(summary)
        self.changed.emit()

    def _on_failed(self, op, msg):
        self.bar.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()                     # PRZED `_fail`: podgląd czyści pole błędu
        self._fail(i18n.t("grid.wb.error", msg=msg))
        self.changed.emit()

    # ---------------------------------------------------------------- cofanie (OKNO do zamknięcia)
    def _on_undo(self):
        if self._commit_id is None or self._runner.is_busy:
            return
        self.error.clear()
        self._begin_progress(0)
        self._runner.start("undo", self._commit_id, on_progress=self._on_progress,
                           on_done=self._after_undo, on_failed=self._on_failed)

    def _after_undo(self, op, res):
        self.bar.setVisible(False)
        msg = i18n.t("grid.wb.restored", n=len(res.restored))
        if res.blocked:
            msg += " · " + i18n.t("grid.wb.blocked", n=len(res.blocked))
        self.status.setText(msg)
        self.undo_btn.setVisible(False)          # commit ZUŻYTY — drugi undo nie ma czego cofać
        self.resolve_btn.setVisible(False)
        self._commit_id = None
        self._committed = False                  # karty zdjęte → zapis znów ma sens
        self._sync_preview()
        self.status.setText(msg)
        self.changed.emit()

    # ---------------------------------------------------------------- takt 3: delegacja do pipeline'u
    def _on_resolve(self):
        """„Rozwiąż teraz" = ISTNIEJĄCY etap Dostawy, nie drugi resolver. Odmowa (etap już biegnie)
        ZOSTAWIA okno otwarte i NIE chowa „Cofnij": okno cofania musi przeżyć nieudaną delegację,
        inaczej UI potwierdzałoby sukces, którego nie było."""
        if self._run_stage is None:
            return self._fail(i18n.t("repair.err.no_host"))
        reason = self._run_stage()
        if reason:
            return self._fail(reason)
        self.accept()

    def set_pipeline_busy(self, busy):
        """Etap pipeline'u w biegu → akcje zapisu tego okna gasną. Modalne okno jest POZA zasięgiem
        `ObjectAxisView.set_busy` (tamto gasi widżety widoku), więc gospodarz przekazuje fakt tutaj."""
        self.undo_btn.setEnabled(not busy)
        self.resolve_btn.setEnabled(not busy)
        if busy:
            self.save_btn.setEnabled(False)
        else:
            self._sync_preview()

    def reject(self):
        """Zamknięcie okna: staging BEZ commitu jest sierotą (`run_id` zna tylko to okno), więc
        znika. Po udanym commicie `_run_id` jest już None — wierszy 'applied' nie ruszamy."""
        if self._run_id is not None:
            repo.clear_pending_for_run(self.con, self._run_id)
            self._run_id = None
        super().reject()


class ObjectAxisView(QWidget):
    """Osadzalny widok osi OBIEKT (PLAN_gui_object + #8/P4): biblioteka (obiekty → klatki, filtr
    po teleskopie/kamerze/filtrze) + kolejka przeglądu (obiekt-review / kopie nieczytelne /
    config-review / headerless) ze STANU. **Akcja zapisu:** „Przypisz obiekt…" na pozycji
    obiekt-review — dialog (`AssignObjectDialog`) → JEDNA klinga `repo.user_assign_object`
    (`actor=user:local`): alias zapamiętany na przyszłość + klatki grupy z `object_source='user'`
    (precedencja na całą drabinę resolvera). Drążenie „kopie nieczytelne" (Z6) → prawy panel
    w trybie „kopie" (dokładne location z markerem). Meta-test AST pilnuje, że widok nie tyka
    SQL zapisu — zapis idzie wyłącznie przez `repo`.

    Dispatch pozycji kolejki po STRING-TAGU (R#6): `Qt.UserRole` = tag (`"object_raw"` /
    `"unreadable"`), `Qt.UserRole+1` = payload (object_raw albo None) — tuple w jednej roli PySide6
    konwertuje na listę (QVariant) i porównanie z krotką-sentinelem po cichu zawodzi.

    `con` = otwarte połączenie (NIE własność widoku). `now_fn` = źródło czasu akcji zapisu
    (ISO-8601); domyślnie zegar UTC, wstrzykiwalne dla testów."""

    status_message = Signal(str)
    writeback_busy = Signal(bool)         # okno naprawy pisze do plików → mutex gridu (D-PD-3)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._busy = False                    # pipeline w biegu → akcja zapisu wygaszona
        self._foreign_wb = False              # DRUGA powierzchnia writebacku pisze (mutex, D-PD-3)
        self._copies_mode = False             # prawy panel w trybie „kopie" (Z6)
        self._loading = False                 # tłumi sygnały selekcji podczas programowego wypełniania
        self._repair_dlg = None               # otwarte okno naprawy nagłówka (modalne — poza set_busy)
        # Takt 3 (`Rozwiąż`) należy do Dostawy: gospodarz wstrzykuje wywołanie ISTNIEJĄCEJ,
        # bramkowanej drogi (`PipelineView.run_stage`). None = widok bez gospodarza (testy samego
        # widoku) → okno naprawy powie wprost, że taktu 3 nie ma stąd jak uruchomić.
        self.run_stage_fn = None
        self._build_ui()
        self._load_facets()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # --- pasek filtra ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("filter.telescope")))
        self.combo_tel = QComboBox()
        self.combo_tel.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_tel)
        bar.addWidget(QLabel(i18n.t("filter.filter")))
        self.combo_filter = QComboBox()
        self.combo_filter.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_filter)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: biblioteka obiektów + kolejka przeglądu pod nią ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(i18n.t("object.library")))
        self.objects = QTableWidget(0, len(OBJ_HEADERS))
        self.objects.setHorizontalHeaderLabels(_headers(OBJ_HEADERS))
        self.objects.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.objects.setSelectionMode(QAbstractItemView.SingleSelection)
        self.objects.setEditTriggers(QAbstractItemView.NoEditTriggers)   # read-only
        self.objects.verticalHeader().setVisible(False)
        self.objects.itemSelectionChanged.connect(self._on_object_selected)
        lv.addWidget(self.objects)
        # Nota pustego stanu W WIDOKU (wizytator P1 #2): pusty filtr nie może komunikować się tylko
        # ulotnym flashem na statusbarze — user patrzy na pustą bibliotekę i pełną kolejkę i nie wie,
        # czy to błąd. Nota jest odkrywalna w obszarze tabeli, chowana gdy są obiekty.
        self.lib_empty = QLabel(i18n.t("object.lib_empty"))
        self.lib_empty.setAlignment(Qt.AlignCenter)
        self.lib_empty.setWordWrap(True)
        self.lib_empty.setVisible(False)
        lv.addWidget(self.lib_empty)

        lv.addWidget(QLabel(i18n.t("object.review_queue")))
        self.review = QListWidget()
        self.review.itemSelectionChanged.connect(self._on_review_selected)
        lv.addWidget(self.review)
        # Akcja #8/P4: przypisz obiekt zaznaczonej pozycji review (aktywna TYLKO przy tagu
        # „object_raw" — obie listy wzajemnie czyszczą selekcję, przycisk śledzi obie).
        assign_row = QHBoxLayout()
        self.assign_btn = QPushButton(i18n.t("object.assign_btn"))
        self.assign_btn.setEnabled(False)
        self.assign_btn.clicked.connect(self._on_assign)
        assign_row.addWidget(self.assign_btn)
        # P-D: druga akcja tej samej kolejki — naprawa NAGŁÓWKA (plik), nie bazy. Aktywna wyłącznie
        # na pozycji `nameless`, więc obie akcje nigdy nie są klikalne naraz.
        self.repair_btn = QPushButton(i18n.t("repair.open_btn"))
        self.repair_btn.setEnabled(False)
        self.repair_btn.clicked.connect(self._on_repair)
        assign_row.addWidget(self.repair_btn)
        assign_row.addStretch(1)
        lv.addLayout(assign_row)

        # --- prawa: klatki zaznaczonego obiektu / pozycji review ---
        right = QWidget()
        rv = QVBoxLayout(right)
        self.frames_label = QLabel(i18n.t("col.frames"))
        rv.addWidget(self.frames_label)
        self.frames = QTableWidget(0, len(FRAME_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(FRAME_HEADERS))
        self.frames.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.frames.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # ZAWIJANIE WYŁĄCZONE, inaczej elizja kłamie (firsthand 2026-08-01, żywa pf4): przy
        # `wordWrap=True` (domyślne) delegat układa ścieżkę bez spacji jako jedną nierozrywalną
        # linię i tnie ją do „R:..." — ZANIM dojdzie do głosu szerokość sekcji. Zmierzone:
        # sekcja 281 px, `fontMetrics.elidedText` na tej szerokości daje 45 znaków
        # („R:\ASTRO_\CALIBRATION\masters\flats\A140R_260…"), a panel rysował 2 znaki.
        self.frames.setWordWrap(False)
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
            self.combo_tel.addItem(i18n.t("filter.all"), None)
            for t in queries.telescope_facets(self.con):
                self.combo_tel.addItem(queries.telescope_label(t), t["id"])
            self.combo_filter.clear()
            self.combo_filter.addItem(i18n.t("filter.all"), None)
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

    def refresh(self, *, select_canon=None, select_first=True):
        """Przeładuj bibliotekę i kolejkę z read-modelu (źródło prawdy = baza; brak cache). Zachowuje
        zaznaczenie obiektu po `object_id`; po zapisie `select_canon` wybiera jawny cel akcji.
        `select_first=False` zostawia jednoznaczny pusty wybór po operacji, która nic nie przypisała."""
        prev = self._selected_object_id() if select_canon is None else None
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
                self._set_obj_cell(r, OBJ_COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
                if row["canon"] == select_canon \
                        or (select_canon is None and row["id"] == prev):
                    target_row = r
            self._load_review()
        finally:
            self._loading = False
        if target_row < 0 and select_canon is not None and any(flt.values()):
            # Kolejka review jest globalna, biblioteka filtrowana: cel legalnego przypisania może być
            # poza bieżącym filtrem. Zdejmij filtry bez pośrednich refreshy i pokaż wynik akcji.
            self._loading = True
            try:
                self.combo_tel.setCurrentIndex(0)
                self.combo_filter.setCurrentIndex(0)
            finally:
                self._loading = False
            return self.refresh(select_canon=select_canon)
        empty = self.objects.rowCount() == 0
        self.lib_empty.setVisible(empty)               # nota odkrywalna w widoku (P1 #2)
        self.objects.setVisible(not empty)
        if target_row >= 0:
            self.objects.selectRow(target_row)
        elif not empty and select_first:
            self.objects.selectRow(0)
        elif not empty:
            self.objects.clearSelection()
            self.frames.setRowCount(0)
            self.frames_label.setText(i18n.t("col.frames"))
        else:
            self.frames.setRowCount(0)
            self.status_message.emit(i18n.t("object.empty_status"))
        self._restore_frames_mode()            # tryb „kopie" znika przy refresh (D-P4-5)
        self._sync_assign_enabled()
        self._on_object_selected()

    def _load_review(self):
        """Kolejka przeglądu ze STANU: obiekt-review (drążenie do klatek + akcja „Przypisz"),
        klatki bez nazwy w nagłówku (licznik — nie ma czego zgrupować, T5a), kopie nieczytelne
        (drążenie do kopii, Z6), liczniki config-review/headerless (informacyjne — bez drążenia,
        to inne osie/skan). Dispatch po string-tagu: `UserRole` = tag, `UserRole+1` = payload
        (R#6 — tuple w roli QVariant konwertuje na listę)."""
        q = queries.review_queue(self.con)
        self.review.clear()
        for r in q["object_review"]:
            self._add_review_item(i18n.t("object.review_item", name=r["object_raw"], n=r["n"]),
                                  tag="object_raw", payload=r["object_raw"])
        # Bezimienne (T5a): grid „Do przeglądu" je pokazuje, kolejka do dziś o nich milczała — bez
        # `object_raw` nie ma klucza grupowania, więc idą własnym licznikiem. Od P-D pozycja DRĄŻY
        # do klatek i niesie akcję „Napraw nagłówek…" (nazwa wraca do PLIKU, nie do bazy). Tag
        # nadawany WYŁĄCZNIE przy n>0: kubełek pusty ma zostać informacyjny, żeby zaznaczenie nie
        # otwierało okna bez treści.
        self._add_review_item(i18n.t("object.nameless_line", n=q["nameless_count"]),
                              tag="nameless" if q["nameless_count"] > 0 else None)
        # Bliźniak kubełka wyżej po drugiej stronie FORMATU (`resolver.NO_OBJECT_CARD_FILETYPES`):
        # RAW nie ma karty `OBJECT` z natury, więc „Napraw nagłówek…" go nie dotyczy, ale klatki
        # ZOSTAJĄ w perspektywie gridu „Do przeglądu" i partycja musi je policzyć. Wiersz jest
        # INFORMACYJNY (bez tagu → nieklikalny): akcją jest ręczne przypisanie, a to osobna
        # powierzchnia (#8/P4) — udawany tag otwierałby okno, które nie ma czego zapisać.
        # Pokazywany TYLKO gdy populacja istnieje: na archiwum bez lustrzanki to stałe „0".
        if q["nameless_raw_count"] > 0:
            self._add_review_item(i18n.t("object.nameless_raw_line", n=q["nameless_raw_count"]))
        # TRZECI kubełek tej samej partycji (I-2b/D-P-I-5): gotowy obraz po integracji, wciągnięty
        # drogą „Stosy". Do 2026-08-02 był INFORMACYJNY, bo pisarz XISF nie umiał dopisać karty
        # (D-X-12) — wiersz z akcją obiecywałby zapis, który kończy się 'blocked' na każdej pozycji.
        # P6d nauczyła pisarza wstawiać kartę, a D-0802-1 otworzyła ten tor, więc kubełek DRĄŻY
        # tak samo jak lightowy. Osobny od niego zostaje, bo to osobna populacja (i osobny licznik
        # partycji), nie dlatego, że droga naprawy jest inna — jest ta sama.
        if q["nameless_stacks_count"] > 0:
            self._add_review_item(
                i18n.t("object.nameless_stacks_line", n=q["nameless_stacks_count"]),
                tag="nameless_stacks")
        self._add_review_item(i18n.t("object.unreadable_line", n=q["unreadable_count"]),
                              tag="unreadable", dim_if_zero=q["unreadable_count"] == 0)
        # liczniki innych kanałów jako pozycja informacyjne (bez tagu → nieklikana); nota
        # „rozwiązywanie w przygotowaniu" ZAWĘŻONA do tych dwóch kanałów (R#9) — obiekt-review
        # i kopie mają już swoje akcje.
        self._add_review_item(i18n.t(
            "object.review_info",
            config=q["config_review_count"], headerless=q["headerless_count"]))

    def _add_review_item(self, text, *, tag=None, payload=None, dim_if_zero=False):
        """Jedna pozycja kolejki przeglądu — JEDEN producent wiersza dla wszystkich kubełków.

        WIZ #11: pięć wierszy miało identyczny krój i kolor, a klikalne były dwa — nic na ekranie
        nie mówiło, który z nich prowadzi dalej. Wiersz z drogą dostaje znacznik „›" (ten sam co
        na liście Porządków), wiersz bez drogi gaśnie i przestaje być zaznaczalny. Kubełek pusty
        gaśnie TEŻ, zostając klikalnym (wiz #17): „nic do zrobienia" ma być widać bez czytania
        liczby, a wejście do środka zostaje otwarte.

        Rozdzielenie stoi na TAGU, nie na osobnym parametrze — tag jest jedynym faktem, którego
        dispatch (`_selected_review`) realnie używa, więc druga flaga „czy klikalny" mogłaby się
        z nim rozjechać (SPOT)."""
        it = QListWidgetItem(f"{text}  ›" if tag else text)
        if tag:
            it.setData(Qt.UserRole, tag)
            it.setData(Qt.UserRole + 1, payload)
            if dim_if_zero:
                it.setForeground(_DIM["fg"])
        else:
            it.setFlags(Qt.ItemIsEnabled)      # informacyjny, nie do zaznaczenia
            it.setForeground(_DIM["fg"])
        self.review.addItem(it)

    def _set_obj_cell(self, r, c, text, *, data=None, align=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if align is not None:                 # liczba klatek prawo-wyrównana (skanowalność, wizytator O1)
            item.setTextAlignment(align)
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

    def _selected_review(self):
        """Zaznaczona pozycja kolejki jako para (tag, payload) albo (None, None). Tag z
        `Qt.UserRole`, payload z `Qt.UserRole+1` (string-tag dispatch, R#6)."""
        sel = self.review.selectedItems()
        if not sel:
            return None, None
        return sel[0].data(Qt.UserRole), sel[0].data(Qt.UserRole + 1)

    def _sync_assign_enabled(self):
        """Akcje kolejki aktywne WYŁĄCZNIE przy swojej pozycji i poza biegiem pipeline (szczery
        disabled — UI nie kłamie; R#10: obie listy wzajemnie czyszczą selekcję, więc przyciski
        śledzą tag, nie to, która lista „ostatnio kliknięta"). „Napraw nagłówek…" gaśnie dodatkowo,
        gdy DRUGA powierzchnia writebacku pisze do plików (mutex, D-PD-3)."""
        tag, _ = self._selected_review()
        self.assign_btn.setEnabled(tag == "object_raw" and not self._busy)
        # Dwa tagi, jedna akcja: kubełek lightów archiwum i kubełek gotowych stosów mają od
        # D-0802-1 tę samą drogę naprawy (karta `OBJECT` do PLIKU), więc przycisk obsługuje oba.
        self.repair_btn.setEnabled(tag in ("nameless", "nameless_stacks")
                                   and not self._busy and not self._foreign_wb)
        # WIZ #12: „Przypisz obiekt…" gasł BEZ SŁOWA obok aktywnego „Napraw nagłówek…", więc obie
        # drogi naprawy wyglądały jak jedna zepsuta. Wygaszony przycisk tłumaczy się sam — tooltip
        # nazywa drogę WŁAŚCIWĄ dla zaznaczonego kubełka, zamiast milczeć o istnieniu drugiej.
        self.assign_btn.setToolTip(i18n.t(
            "object.assign_tip" if tag == "object_raw" else
            "object.assign_tip_card" if tag in ("nameless", "nameless_stacks") else
            "object.assign_tip_pick"))

    def _on_object_selected(self):
        """Obiekt zaznaczony → klatki tego obiektu (z bieżącym filtrem). Czyści selekcję review (wzajemnie
        wykluczające źródła klatek: obiekt vs pozycja review) i wychodzi z trybu „kopie"."""
        if self._loading:
            return
        oid = self._selected_object_id()
        if oid is None:
            return
        if self.review.selectedItems():
            self.review.clearSelection()
        self._restore_frames_mode()
        self._sync_assign_enabled()
        flt = self._filters()
        rows = queries.object_frames(
            self.con, oid, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"])
        self.frames_label.setText(i18n.t("object.frames_of_object"))
        self._fill_frames(rows, present_col=True)

    def _on_review_selected(self):
        """Pozycja kolejki zaznaczona → dispatch po tagu: `object_raw` = nierozwiązane klatki tej
        nazwy (+ aktywacja „Przypisz obiekt…"); `unreadable` = tryb „kopie" prawego panelu (Z6);
        pozycja informacyjna (bez tagu) nie drąży."""
        if self._loading:
            return
        tag, payload = self._selected_review()
        self._sync_assign_enabled()
        if tag is None:                        # nic nie zaznaczone / pozycja informacyjna
            return
        self.objects.clearSelection()
        if tag == "object_raw":
            self._restore_frames_mode()
            rows = queries.object_review_frames(self.con, payload)
            self.frames_label.setText(i18n.t("object.frames_review", name=payload))
            self._fill_frames(rows, present_col=False)
        elif tag == "nameless":
            self._restore_frames_mode()
            rows = queries.nameless_frames(self.con)
            self.frames_label.setText(i18n.t("object.frames_nameless", n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag == "nameless_stacks":
            self._restore_frames_mode()
            rows = queries.nameless_stack_frames(self.con)
            self.frames_label.setText(i18n.t("object.frames_nameless_stacks", n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag == "unreadable":
            self._show_copies()

    # ------------------------------------------------ tryb „kopie" (Z6)

    def _show_copies(self):
        """Prawy panel w trybie „kopie": DOKŁADNE location z markerem `unreadable_since` (#13/Z6).
        Tryb znika przy `refresh()` i przy wyborze obiektu/pozycji review (powrót do klatek
        zaznaczenia — świadomie, udokumentowane w D-P4-5)."""
        rows = queries.unreadable_copies(self.con)
        self._copies_mode = True
        self.frames.setColumnCount(len(COPY_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(COPY_HEADERS))
        fh = self.frames.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Ścieżka bierze RESZTĘ i elidować się jej wolno (lustro trybu klatek — `FRAME_COL_PATH`
        # wyżej): przy `ResizeToContents` realna ścieżka archiwum (100 znaków) zjadała cały panel
        # i „Powód" — jedyna kolumna, dla której ten tryb powstał — stał za prawą krawędzią.
        # Firsthand 2026-08-01 na żywej pf4: jedyna nieczytelna kopia to master flat XISF,
        # a diagnozy („ParseError…") nie dało się przeczytać bez scrolla w poziomie.
        # Pełna ścieżka nie ginie: niesie ją tooltip komórki (niżej) i poziomy scroll.
        fh.setSectionResizeMode(COPY_COL_PATH, QHeaderView.Stretch)
        self.frames.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.frames.setRowCount(len(rows))
        for r, row in enumerate(rows):
            path = row["path"] or ""
            self._set_frame_cell(r, COPY_COL_PATH, path or i18n.t("object.no_path"),
                                 tooltip=path or None)
            self._set_frame_cell(r, COPY_COL_VOLUME, row["volume"])
            self._set_frame_cell(r, COPY_COL_PRESENT,
                                 i18n.t("common.yes") if row["present"] else i18n.t("common.no"))
            self._set_frame_cell(r, COPY_COL_MARKED, _fmt_event_ts(row["unreadable_since"]),
                                 tooltip=row["unreadable_since"])
            # Powód z dziennika (Z6): stan mówi KTÓRA kopia, ten człon — CZEGO nie da się
            # przeczytać. Tooltip niesie zapis dosłowny (z prefiksem), komórka — samą diagnozę.
            self._set_frame_cell(r, COPY_COL_REASON, _copy_reason(row["reason"]),
                                 tooltip=row["reason"] or None)
        self.frames_label.setText(i18n.t("object.unreadable_title", n=len(rows)))

    def _restore_frames_mode(self):
        """Powrót prawego panelu z trybu „kopie" do tabeli klatek (kolumny + nagłówki FRAME_*)."""
        if not self._copies_mode:
            return
        self._copies_mode = False
        self.frames.setColumnCount(len(FRAME_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(FRAME_HEADERS))
        fh = self.frames.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(FRAME_COL_PATH, QHeaderView.Stretch)

    # ------------------------------------------------ akcja zapisu (#8/P4)

    def _on_assign(self):
        """„Przypisz obiekt…": dialog wyboru obiektu → JEDNA klinga `repo.user_assign_object`
        (grupa = klatki pozycji review o tym `object_raw`; klucz aliasu = `norm_alnum(object_raw)` —
        ta sama funkcja, co resolver przy zapisie, SPOT). Raport „przypisano N z M" (R#8: dryf
        grupy = klatka zajęta między dialogiem a zapisem jest pomijana), potem refresh."""
        tag, object_raw = self._selected_review()
        if tag != "object_raw" or not object_raw:
            return
        alias_norm = norm_alnum(object_raw)
        if not alias_norm:                     # pusty klucz (D-P4-2/R#3) — dialog odrzuca grupę
            QMessageBox.warning(
                self, i18n.t("assign.title"),
                i18n.t("object.alias_no_alnum", name=object_raw))
            return
        rows = queries.object_review_frames(self.con, object_raw)
        frame_ids = [r["frame_id"] for r in rows]
        dlg = AssignObjectDialog(self.con, object_raw=object_raw, alias_norm=alias_norm,
                                 frame_count=len(frame_ids), parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        canon, catalog, kind = dlg.selected
        try:
            assigned, skipped = repo.user_assign_object(
                self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                frame_ids=frame_ids, now=self._now())
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("assign.title"), str(e))
            return
        msg = i18n.t("object.assigned_report", assigned=assigned, total=assigned + skipped, canon=canon)
        if skipped:
            msg += i18n.t("object.assigned_skipped", n=skipped)
        self.status_message.emit(msg)
        self.refresh(select_canon=canon if assigned else None, select_first=bool(assigned))

    # ------------------------------------------------ akcja zapisu do PLIKU (P-D)

    def _on_repair(self):
        """„Napraw nagłówek…": klatki bezimienne → dialog (grupy po folderze, propozycja ze ścieżki)
        → karta `OBJECT` w PLIKU. Zapis idzie klingą writebacku, nie do bazy — dlatego po nim
        odświeżamy kolejkę, a oś obiektu wypełnia dopiero takt 3 (`Rozwiąż`, delegowany gospodarzowi
        przez `run_stage_fn`; brak gospodarza = brak taktu 3, okno powie to wprost).

        Wejście bierzemy z ZAZNACZONEGO kubełka (D-0802-1): lighty archiwum i gotowe stosy mają tę
        samą drogę naprawy, ale to DWIE rozłączne populacje i dwa liczniki — otwarcie okna zawsze
        na lightach kłamałoby licznikiem, na którym user kliknął."""
        tag, _ = self._selected_review()
        rows = (queries.nameless_stack_frames(self.con) if tag == "nameless_stacks"
                else queries.nameless_frames(self.con))
        if not rows:
            self.status_message.emit(i18n.t("repair.nothing"))
            return
        dlg = RepairHeaderDialog(self.con, rows=rows, db_path=queries.db_path_of(self.con),
                                 now_fn=self._now, run_stage_fn=self.run_stage_fn, parent=self)
        dlg.changed.connect(self._on_repair_changed)
        dlg.busy_changed.connect(self.writeback_busy)   # mutex: gospodarz wygasi drugą powierzchnię
        self._repair_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._repair_dlg = None

    def _on_repair_changed(self):
        """Zapis/cofnięcie w oknie naprawy → kolejka mówi świeżą prawdę JUŻ po takcie 2 (dialog żyje
        w tym samym widoku). Oś obiektu i badge Porządków ruszą się dopiero po takcie 3 — to nie
        rozjazd, tylko dwa różne fakty: karta jest w pliku, obiektu jeszcze nie ma."""
        self._load_review()
        self._sync_assign_enabled()

    def _fill_frames(self, rows, *, present_col):
        """Wypełnij tabelę klatek. `present_col` — czy źródło niesie kolumnę `present` (biblioteka tak,
        review nie). `present=0` pokazujemy jako „nie" (R#7 — klatka WIDOCZNA mimo zniknięcia pliku).

        Źródło BEZ tej kolumny CHOWA ją w całości (wiz #10): pusta komórka pod nagłówkiem „Obecny"
        czyta się jak „nie ma", a w widoku obiektu obok ta sama kolumna mówi „tak". Nagłówek bez
        treści jest obietnicą bez pokrycia — znika razem z nią."""
        self.frames.setColumnHidden(FRAME_COL_PRESENT, not present_col)
        self.frames.setRowCount(len(rows))
        for r, row in enumerate(rows):
            keys = row.keys()
            self._set_frame_cell(r, FRAME_COL_SHA, (row["sha1_data"] or "")[:12])
            self._set_frame_cell(r, FRAME_COL_TEL, queries.telescope_label(row))
            self._set_frame_cell(r, FRAME_COL_CAM, row["camera_model"] or "")
            self._set_frame_cell(r, FRAME_COL_FILTER, row["filter_canon"] if "filter_canon" in keys else "")
            self._set_frame_cell(r, FRAME_COL_DATE, _fmt_obs_date(row["date_obs"]),
                                 tooltip=row["date_obs"] or None)
            if present_col and "present" in keys:
                self._set_frame_cell(r, FRAME_COL_PRESENT,
                                     i18n.t("common.yes") if row["present"] else i18n.t("common.no"))
            else:
                self._set_frame_cell(r, FRAME_COL_PRESENT, "")
            # Ścieżka: pokaż NAZWĘ PLIKU (elizja od prawej gubiłaby ją z pełnej ścieżki „R:\...");
            # pełna ścieżka w tooltipie (hover). Klatka bez lokalizacji (zniknięta) → jawny znacznik.
            path = row["path"] or ""
            self._set_frame_cell(r, FRAME_COL_PATH,
                                 os.path.basename(path) if path else i18n.t("object.no_location"),
                                 tooltip=path or None)

    def _set_frame_cell(self, r, c, text, *, tooltip=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if tooltip:
            item.setToolTip(tooltip)
        self.frames.setItem(r, c, item)

    def set_busy(self, busy):
        """Pipeline w biegu → wygaszenie akcji zapisu („Przypisz obiekt…" #8/P4, „Napraw nagłówek…"
        P-D) — szczery disabled. Read-modele odświeża gospodarz DOPIERO po `stage_finished`
        (WAL → zapisy workera widoczne), więc SELECT w trakcie zapisu tu nie zachodzi.

        OTWARTE okno naprawy jest MODALNE, więc poza zasięgiem tej metody (gasi widżety WIDOKU) —
        fakt przekazujemy mu wprost, inaczej „Zapisz karty" zostałby klikalny w trakcie biegu."""
        self._busy = busy
        self._sync_assign_enabled()
        if self._repair_dlg is not None:
            self._repair_dlg.set_pipeline_busy(busy)

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (grid) pisze do plików — „Napraw nagłówek…" gaśnie
        (mutex, D-PD-3: dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`)."""
        self._foreign_wb = busy
        self._sync_assign_enabled()


# ============================================================ oś OBSERWATORIUM (PLAN_os_obserwatorium §3)

# Kolumny listy stanowisk. Tożsamość osi jest GEOMETRYCZNA — brak stringa-nagłówka jak `telescop_canon`;
# to szerokość/długość identyfikują stanowisko dla oka usera (rozpoznaje swoje miejsca po współrzędnych). Nazwa
# to etykieta usera (edytowalna in-line → `label_observatory`). Bez kolumny Status (zawsze 'proposed'
# w v1 — brak approve) i bez Wysokości (atrybut D3, nie tożsamość — zejście na drugi plan).
OBS_COL_ID, OBS_COL_NAME, OBS_COL_LAT, OBS_COL_LON, OBS_COL_FRAMES = range(5)
OBS_HEADERS = ["col.id", "obs.col.name", "obs.col.lat", "obs.col.lon", "col.frames"]


def _fmt_coord(v):
    """Współrzędna do komórki/etykiety: STAŁA precyzja 4 miejsc (~11 m) — słupek lat/lon wyrównany
    (wizytator #2: `%g` dawał zmienną liczbę miejsc, np. `7.5` vs `128.4082` → poszarpany słupek;
    przy progu 4 km 11 m nie myli stanowisk). None → '' (defensywnie — lat/lon są NOT NULL)."""
    return "" if v is None else f"{v:.4f}"


def _obs_row_label(row):
    """Etykieta stanowiska do listy combo/członków: nazwa usera, a gdy brak (nienazwane — realny
    przypadek: cała oś świeżo `proposed`) — współrzędne z seeda, by pozycja NIE milczała."""
    return row["name"] or f'{_fmt_coord(row["lat"])}, {_fmt_coord(row["lon"])}'


class ObservatoryAxisView(QWidget):
    """Osadzalny widok osi OBSERWATORIUM (lista→scal→nazwij) — mirror `TelescopeAxisView` z JEDNĄ
    różnicą domenową: BEZ „Zatwierdź" (v1 nie ma approve; port osi = merge+unmerge+label). Lista
    kanonicznych stanowisk (lewa) + szczegół zaznaczonego (prawa: scalone pod nim, audyt). Akcje usera
    (`label`/`merge`/`unmerge`) idą przez `repo` (jedna klinga). Nazwa edytowalna in-line; tożsamość
    (szer./dług.) tylko do odczytu. Ten widok NIE wykonuje `con.execute` — meta-tripwir AST pilnuje.

    `con` = otwarte połączenie RW (NIE własność widoku). `now_fn` = źródło czasu (ISO-8601)."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._loading = False                # tłumi itemChanged podczas programowego wypełniania
        self._source_mergeable = False       # czy zaznaczony wiersz może być źródłem scalenia
        self._obs_coords = {}                # oid → (lat, lon) z ostatniego refresh (źródło GPS dla OSM)
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: tabela aktywnych stanowisk + pasek akcji ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(i18n.t("axis.obs.active")))
        self.table = QTableWidget(0, len(OBS_HEADERS))
        self.table.setHorizontalHeaderLabels(_headers(OBS_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Priorytet szerokości: Nazwa (etykieta usera) rośnie, reszta do treści (wizytator #3/#4 —
        # `stretchLastSection` rozpychał Klatki i ucinał je na wąsko, a Nazwa była ciasna).
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(OBS_COL_NAME, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self._edit_triggers = self.table.editTriggers()   # przywracane po set_busy(False) (wizytator T3)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.table)
        # Nota pustego stanu W WIDOKU (wizytator #1): `status_message` bywa nadpisany flashem gospodarza
        # (MainWindow), więc pusty stan musi być odkrywalny w obszarze tabeli — wzorzec 1:1 z
        # `ObjectAxisView.lib_empty`. Chowana, gdy są stanowiska.
        self.obs_empty = QLabel(i18n.t("axis.obs.empty_note"))
        self.obs_empty.setAlignment(Qt.AlignCenter)
        self.obs_empty.setWordWrap(True)
        self.obs_empty.setVisible(False)
        lv.addWidget(self.obs_empty)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(QLabel(i18n.t("axis.obs.merge_into")))
        self.combo_target = QComboBox()
        self.combo_target.currentIndexChanged.connect(self._sync_merge_enabled)
        actions.addWidget(self.combo_target)
        self.btn_merge = QPushButton(i18n.t("action.merge"))
        self.btn_merge.clicked.connect(self._on_merge)
        actions.addWidget(self.btn_merge)
        lv.addLayout(actions)

        # --- prawa: szczegół zaznaczonego ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel(i18n.t("axis.obs.merged_under")))
        self.members = QListWidget()
        self.members.itemSelectionChanged.connect(self._sync_unmerge_enabled)
        rv.addWidget(self.members)
        self.btn_unmerge = QPushButton(i18n.t("action.unmerge"))
        self.btn_unmerge.clicked.connect(self._on_unmerge)
        rv.addWidget(self.btn_unmerge)
        rv.addWidget(QLabel(i18n.t("axis.history")))
        self.events = QListWidget()
        rv.addWidget(self.events)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # --- mapa stanowisk (F8) na DOLE, pełnej szerokości: scatter geo chce szerokości, user
        # reguluje pionowy podział; przycisk OSM na zaznaczeniu (akcja tabeli, nie widżetu mapy). ---
        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(splitter)
        self.map_box = QWidget()                      # ref — ukrywany przy 0 stanowisk (wiz F8 #6)
        mv = QVBoxLayout(self.map_box)
        mv.setContentsMargins(0, 0, 0, 0)
        obar = QHBoxLayout()
        self.btn_osm = QPushButton(i18n.t("axis.obs.open_osm"))
        self.btn_osm.setEnabled(False)                # szczery disabled — bez zaznaczenia brak celu
        self.btn_osm.clicked.connect(self._on_open_osm)
        obar.addWidget(self.btn_osm)
        obar.addStretch(1)
        mv.addLayout(obar)
        self.map_view = SitesMapView()
        self.map_view.siteClicked.connect(self._on_map_click)   # klik w punkt → selekcja wiersza (#10)
        mv.addWidget(self.map_view, 1)
        vsplit.addWidget(self.map_box)
        # setStretchFactor sam nie wystarcza — sizeHint górnych tabel zjada przyrost i mapa siada na
        # minimum 160 px (wiz F8 #1); setSizes wymusza sensowny DOMYŚLNY podział (~55/45), user reguluje.
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([460, 380])
        outer.addWidget(vsplit, 1)

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self):
        """Przeładuj listę z read-modelu (źródło prawdy = baza; brak cache). Zachowuje zaznaczenie po
        `observatory_id` (po merge wiersze się przesuwają). Karmi mapę tymi SAMYMI wierszami (SPOT)
        i zapamiętuje współrzędne dla linku OSM (F8 F8 — read-model nie jest cache'owany inaczej)."""
        prev = self._selected_observatory_id()
        self._loading = True
        try:
            rows = queries.active_observatories(self.con)
            self._obs_coords = {row["id"]: (row["lat"], row["lon"]) for row in rows}
            self.table.setRowCount(len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_cell(r, OBS_COL_ID, str(row["id"]), data=row["id"])
                self._set_cell(r, OBS_COL_NAME, row["name"] or "", editable=True)
                self._set_cell(r, OBS_COL_LAT, _fmt_coord(row["lat"]), align=_NUM_ALIGN)
                self._set_cell(r, OBS_COL_LON, _fmt_coord(row["lon"]), align=_NUM_ALIGN)
                self._set_cell(r, OBS_COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
                if row["id"] == prev:
                    target_row = r
        finally:
            self._loading = False
        empty = self.table.rowCount() == 0
        self.obs_empty.setVisible(empty)              # nota odkrywalna w widoku (wizytator #1)
        self.table.setVisible(not empty)
        self.map_box.setVisible(not empty)            # 0 stanowisk → bez martwego pasa mapy (wiz F8 #6)
        self.map_view.set_sites(rows)                 # mapa dostaje TE SAME wiersze co tabela (F8)
        if target_row >= 0:
            self.table.selectRow(target_row)
        elif not empty:
            self.table.selectRow(0)
        else:
            self.status_message.emit(i18n.t("axis.obs.empty_status"))
        self._on_selection_changed()

    def _set_cell(self, r, c, text, *, editable=False, data=None, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # tylko nazwa jest edytowalna in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if align is not None:                 # liczby prawo-wyrównane (skanowalność magnitud, wizytator #2)
            item.setTextAlignment(align)
        if data is not None:                  # observatory_id na kolumnie ID (kotwica wiersza)
            item.setData(Qt.UserRole, data)
        self.table.setItem(r, c, item)

    def _on_map_click(self, oid):
        """Klik w punkt mapy (hit-test) → zaznacz odpowiedni wiersz tabeli (mapa→tabela; #10).
        Selekcja tabeli kaskaduje przez `itemSelectionChanged` → `_on_selection_changed`
        (wyróżnienie mapy + stan OSM) — mapa NIE orkiestruje, tabela zostaje właścicielem selekcji
        (SPOT). Nieznany oid (wiersz zniknął między refreshami) ignorowany."""
        for r in range(self.table.rowCount()):
            item = self.table.item(r, OBS_COL_ID)
            if item and item.data(Qt.UserRole) == oid:
                self.table.selectRow(r)
                return

    def _selected_observatory_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), OBS_COL_ID)
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self):
        """Odśwież panel szczegółu (członkowie + audyt) i stany przycisków dla zaznaczonego wiersza.
        Stany SZCZERE: merge bez realnego celu albo źródła z członkami jest wyłączony (UI nie kłamie)."""
        oid = self._selected_observatory_id()

        self.members.clear()
        members = queries.merged_under_observatory(self.con, oid) if oid is not None else []
        for m in members:
            it = QListWidgetItem(f'#{m["id"]}  {_obs_row_label(m)}')
            it.setData(Qt.UserRole, m["id"])
            self.members.addItem(it)

        self.events.clear()
        if oid is not None:
            for e in queries.observatory_axis_events(self.con, observatory_id=oid):
                self.events.addItem(f'{_fmt_event_ts(e["ts"])}  ·  {e["verb"]}  ·  {e["actor"]}')

        # Cel scalenia z PLACEHOLDEREM (currentData=None): merge to świadoma deklaracja „to samo
        # stanowisko" (np. dom↔praca, gdy user uzna). `blockSignals` — przebudowa nie sypie sygnałem.
        self.combo_target.blockSignals(True)
        self.combo_target.clear()
        self.combo_target.addItem(i18n.t("axis.pick_target"), None)
        for o in queries.active_observatories(self.con):
            if o["id"] != oid:                # cel ≠ źródło → self-merge strukturalnie niemożliwy
                self.combo_target.addItem(f'#{o["id"]}  {_obs_row_label(o)}', o["id"])
        self.combo_target.setCurrentIndex(0)
        self.combo_target.blockSignals(False)

        # źródło mergowalne tylko gdy kanoniczne BEZ członków (inwariant głębokość ≤ 1) i JEST realny cel.
        self._source_mergeable = (oid is not None and not members and self.combo_target.count() > 1)
        self._sync_merge_enabled()
        self._sync_unmerge_enabled()

        # mapa i OSM sprzężone z zaznaczeniem tabeli (F8): mapa wyróżnia punkt, OSM celuje w jego GPS.
        self.map_view.set_selected(oid)
        self.btn_osm.setEnabled(oid is not None)

    def _sync_merge_enabled(self):
        """„Scal" aktywny dopiero gdy źródło jest mergowalne ORAZ wskazano REALNY cel (nie placeholder)."""
        self.btn_merge.setEnabled(self._source_mergeable and self.combo_target.currentData() is not None)

    def _sync_unmerge_enabled(self):
        self.btn_unmerge.setEnabled(bool(self.members.selectedItems()))

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU osi (szczery disabled — worker pisze do bazy).
        Po etapie gospodarz woła `set_busy(False)` → `_on_selection_changed` przywraca szczere stany."""
        if busy:
            self.btn_merge.setEnabled(False)
            self.btn_unmerge.setEnabled(False)
            self.combo_target.setEnabled(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # zamknij in-line edyt nazwy (T3)
        else:
            self.table.setEditTriggers(self._edit_triggers)
            self.combo_target.setEnabled(True)
            self._on_selection_changed()

    # ---------------------------------------------------------------- akcje → repo (jedna klinga)

    def _flash(self, msg):
        self.status_message.emit(msg)

    def _on_open_osm(self):
        """Otwórz zaznaczone stanowisko w OpenStreetMap (przeglądarka usera — zoom/satelita/okolica poza
        apką, zero ciężaru w apce). Przycisk wyłączony bez zaznaczenia; handler i tak sprawdza (guard
        drugą linią). Źródło GPS = `_obs_coords` z ostatniego refresh (F8 F8)."""
        oid = self._selected_observatory_id()
        coord = self._obs_coords.get(oid) if oid is not None else None
        if coord is None:
            self._flash(i18n.t("axis.obs.select_for_map"))
            return
        QDesktopServices.openUrl(QUrl(mapproj.osm_url(coord[0], coord[1])))

    def _on_item_changed(self, item):
        """Edycja in-line nazwy → `repo.label_observatory`. Pusta nazwa → `ValueError` (kasowanie poza
        v1) złapany i pokazany; widok wraca do prawdy bazy (refresh)."""
        if self._loading or item.column() != OBS_COL_NAME:
            return
        oid = self.table.item(item.row(), OBS_COL_ID).data(Qt.UserRole)
        try:
            changed = repo.label_observatory(
                self.con, observatory_id=oid, name=item.text(), now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.obs.name_rejected", e=e))
            self.refresh()
            return
        self._flash(i18n.t("axis.obs.name_saved") if changed else i18n.t("axis.obs.name_unchanged"))
        self.refresh()

    def _on_merge(self):
        src = self._selected_observatory_id()
        tgt = self.combo_target.currentData()
        if src is None or tgt is None:        # brak źródła albo placeholder zamiast celu
            return
        try:
            changed = repo.merge_observatory(
                self.con, source_id=src, target_id=tgt, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.merge_failed", e=e))
            return
        self._flash(i18n.t("axis.merged", src=src, tgt=tgt) if changed
                    else i18n.t("axis.obs.already_merged"))
        self.refresh()

    def _on_unmerge(self):
        sel = self.members.selectedItems()
        if not sel:
            return
        mid = sel[0].data(Qt.UserRole)
        try:
            changed = repo.unmerge_observatory(self.con, observatory_id=mid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.unmerge_failed", e=e))
            return
        self._flash(i18n.t("axis.unmerged", mid=mid) if changed
                    else i18n.t("axis.obs.already_canonical"))
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
        self.setWindowTitle(i18n.t("window.telescope_axis"))
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


# Miejsca nawigacji (F5, PLAN_ux_redesign §6): indeksy pozycji sidebara == indeksy stron stacku.
# NAV_PLANER dołożony w T5 jako CZWARTE miejsce (D-0731-6) — świadomie BEZ badge'a: „ile do
# zrobienia" zależy u planera od suwaka `min_hours`, więc liczba w nawiasie kłamałaby przy każdej
# zmianie progu (badge Porządków liczy roboty, które są faktem bazy, nie funkcją parametru).
NAV_DOSTAWA, NAV_ZBIORY, NAV_PORZADKI, NAV_PLANER = range(4)


class MainWindow(QMainWindow):
    """Okno aplikacji (PLAN_gui_pipeline §2 + UX-redesign F5): menu Plik (Otwórz/Nowa baza) +
    nawigacja 3 MIEJSC w sidebarze (Dostawa / Zbiory / Porządki — `QListWidget` prowadzi
    `QStackedWidget`; osie teleskop/obserwatorium/obiekt to PODSTRONY Porządków w `TasksView`).
    WŁAŚCICIEL połączenia `con` — otwiera je z `db_path`, zamyka poprzednie przy przełączeniu bazy
    i bieżące przy zamknięciu okna (top-level apki, w odróżnieniu od osadzonych widoków).

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
        # Numer wersji W TYTULE, bo wydanie jedzie do użytkownika jako JEDEN plik `horreum-gui.exe`
        # (onefile — CLI `horreum --version` nie powstaje) i okno jest wtedy jedyną powierzchnią,
        # na której da się sprawdzić, co się ma. Numer czytany, nie pisany (`horreum/__init__.py`).
        from .. import __version__
        self.setWindowTitle(f"Horreum {__version__}")
        self.resize(1000, 620)
        self._build_menu()
        self._build_central()
        if db_path is not None:
            self._open_path(db_path)
        else:
            self._sync_db_state()

    # ---------------------------------------------------------------- budowa szkieletu

    def _build_menu(self):
        m = self.menuBar().addMenu(i18n.t("menu.file"))
        m.addAction(i18n.t("menu.open_db"), self._on_open_db)
        m.addAction(i18n.t("menu.new_db"), self._on_new_db)
        self._build_view_menu()

    def _build_view_menu(self):
        """Menu &Widok: motyw (ciemny/jasny) + język (PL/EN). Oba przez wykluczający QActionGroup;
        zaznaczenie ODBIJA bieżący stan z QSettings bez klikania (UI-NIE-KŁAMIE, F6 recenzja #6)."""
        view = self.menuBar().addMenu(i18n.t("menu.view"))
        self._build_theme_menu(view)
        view.addSeparator()
        self._build_lang_menu(view)

    def _build_theme_menu(self, view):
        """Sekcja motywu w &Widok — wykluczająca przez QActionGroup."""
        grp = QActionGroup(self)
        grp.setExclusive(True)
        current = theme.normalize(QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))
        self._theme_actions = {}
        for name, key in (("dark", "menu.theme.dark"), ("light", "menu.theme.light")):
            act = view.addAction(i18n.t(key))
            act.setCheckable(True)
            act.setChecked(name == current)
            act.triggered.connect(lambda _checked=False, n=name: self._on_theme(n))
            grp.addAction(act)
            self._theme_actions[name] = act

    def _build_lang_menu(self, view):
        """Sekcja języka w &Widok — bliźniak motywu (QActionGroup, klucz QSettings `ui/lang`).
        Endonimy z `i18n.available_langs()` NIE są tłumaczone. D-L1: zmiana zapisuje `ui/lang`
        i stosuje się przy STARCIE (nota w statusbarze), więc zaznaczenie odbija stan trwały,
        nie „za restart" — bieżąca sesja pozostaje w języku, w którym wystartowała."""
        grp = QActionGroup(self)
        grp.setExclusive(True)
        current = i18n.current_lang()   # ŻYWY język sesji (ustawiony w `main` z QSettings/locale)
        self._lang_actions = {}
        for code, endonym in i18n.available_langs():
            act = view.addAction(endonym)
            act.setCheckable(True)
            act.setChecked(code == current)
            act.triggered.connect(lambda _checked=False, c=code: self._on_lang(c))
            grp.addAction(act)
            self._lang_actions[code] = act

    def _on_lang(self, code):
        """Zapisz wybór języka (zadziała przy następnym starcie — D-L1 restart-required v1).
        NIE wołamy `i18n.set_lang` na żywo: `_LANG` mutowany w trakcie sesji rozdarłby raport
        liczony off-thread (R-i18n #6). Nota w statusbarze mówi userowi, że trzeba zrestartować."""
        QSettings("Horreum", "Horreum").setValue("ui/lang", code)
        self.statusBar().showMessage(i18n.t("lang.restart_note"), 8000)

    def _on_theme(self, name):
        """Przełącz motyw: zastosuj do aplikacji, POTEM utrwal (F6 recenzja #7 — nie zapisuj skórki,
        która się wywali w apply), i przemaluj otwarte widoki. Paleta globalna odświeża resztę sama;
        grid czyta kolory na żywo (viewport().update()), wykluczenia facetów wypalone → refresh_theme."""
        app = QApplication.instance()
        if app is None:
            return
        apply_theme(app, name)
        QSettings("Horreum", "Horreum").setValue("ui/theme", name)
        grid_view = getattr(self, "grid_view", None)
        if grid_view is not None:
            grid_view.table.viewport().update()
            grid_view.facet_rail.refresh_theme()
        obs = getattr(self, "observatory_view", None)   # mapa maluje QPainterem — paleta jej nie odświeży (F8)
        if obs is not None:
            obs.map_view.refresh_theme()
        planner = getattr(self, "planner_view", None)   # akcenty planera są per MOTYW (T5, wiz R2):
        if planner is not None:                        # wyszarzenie wiersza, ⚠ nota, „bez luk", chipy
            planner.use_theme(name)

    def _build_central(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        # Sidebar nawigacji (F5): lista pionowa 3 miejsc zamiast paska przycisków-zakładek.
        # Ukryty do montażu widoków (dom widoczności JAWNY: _clear_views chowa, _mount_views odsłania).
        self.nav = QListWidget()
        self.nav.setFixedWidth(160)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setVisible(False)
        outer.addWidget(self.nav)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        # Pusty stan ODKRYWALNY w centrum (wizytator F5 #3) — statusBar to za mało dla pierwszego
        # ekranu nowego usera; chowany, gdy jest baza (steruje _sync_db_state).
        self.empty_note = QLabel(i18n.t("main.no_db"))
        self.empty_note.setAlignment(Qt.AlignCenter)
        self.empty_note.setWordWrap(True)
        self.empty_note.setVisible(False)
        outer.addWidget(self.empty_note, 1)
        self.setCentralWidget(central)
        self.statusBar()

    def _show_view(self, idx):
        """Przełącz miejsce nawigacji (seam dla kodu i testów) — sidebar prowadzi stack."""
        self.nav.setCurrentRow(idx)

    def _on_nav_changed(self, row):
        if row < 0:                     # nav.clear() przy przemontowaniu emituje -1 (F5R#6)
            return
        self.stack.setCurrentIndex(row)
        if row == NAV_PORZADKI:         # wejście w Porządki = świeży stan liczników zadań
            self.tasks_view.refresh_counts()

    def _clear_views(self):
        self.nav.clear()
        self.nav.setVisible(False)
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    # ---------------------------------------------------------------- montaż widoków na bazie

    def _mount_views(self):
        """(Prze)montuj widoki na bieżącej bazie — 3 MIEJSCA (F5): Dostawa (pipeline), Zbiory (grid),
        Porządki (zadania + podstrony osi). Importy widżetów lazy (wzorzec etapów; dla `TasksView`
        OBOWIĄZKOWO — `tasks.py` importuje z `app.py` module-level, F5R2#1: import na górze domknąłby
        cykl). Pod-widoki osi z `TasksView` ALIASOWANE na oknie — kontrakt `axis_view`/
        `observatory_view`/`object_view` przeżywa przemontowanie bez zmian."""
        from horreum.gui.pipeline import PipelineView          # lazy: Qt-import tylko gdy montujemy
        from horreum.gui.grid import FramesView
        from horreum.gui.tasks import TasksView
        from horreum.gui.planner import PlannerView

        self._clear_views()
        pipeline = PipelineView(self.db_path, now_fn=self._now)
        pipeline.status_message.connect(self._flash)
        pipeline.stage_finished.connect(self._on_stage_finished)
        pipeline.running_changed.connect(self._on_pipeline_running)
        pipeline.open_collection.connect(self._on_open_collection)   # P5b: raport → perspektywa (3→1)
        self.pipeline_view = pipeline

        grid = FramesView(self.con, now_fn=self._now)
        grid.status_message.connect(self._flash)
        grid.writeback_busy.connect(self._on_writeback_busy)
        self.grid_view = grid

        tasks = TasksView(self.con, now_fn=self._now)
        self.tasks_view = tasks
        self.axis_view = tasks.axis_view
        self.observatory_view = tasks.observatory_view
        self.object_view = tasks.object_view
        # Takt 3 P-D: okno naprawy nagłówka nie ma własnego resolvera — dostaje ISTNIEJĄCĄ drogę
        # etapu wraz z przełączeniem widoku na Dostawę (precedens „3→1"). Wstrzykiwane TU, bo tylko
        # gospodarz zna obie powierzchnie.
        tasks.object_view.run_stage_fn = self._resolve_after_repair
        tasks.object_view.writeback_busy.connect(grid.set_writeback_busy)   # mutex w drugą stronę
        for v in (tasks.axis_view, tasks.observatory_view, tasks.object_view):
            v.status_message.connect(self._flash)
        tasks.open_collection.connect(self._on_open_collection)
        tasks.counts_changed.connect(self._on_tasks_counts)

        # Motyw PRZEKAZANY, nie czytany przez widok z rejestru (wiz T5 N4— jeden właściciel faktu).
        planner = PlannerView(self.con, db_path=self.db_path, now_fn=self._now,
                              theme_name=theme.normalize(
                                  QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT)))
        planner.status_message.connect(self._flash)
        planner.show_frames_for.connect(self._on_show_target_frames)   # T5e: most planer → grid
        self.planner_view = planner

        for label, widget in ((i18n.t("nav.dostawa"), pipeline), (i18n.t("nav.zbiory"), grid),
                              (i18n.t("nav.porzadki"), tasks), (i18n.t("nav.planer"), planner)):
            self.stack.addWidget(widget)
            self.nav.addItem(label)
        self.nav.setVisible(True)
        self._show_view(NAV_DOSTAWA)
        tasks.refresh_counts()    # badge żywy od MONTAŻU (F5R#1) — connect i pozycje nav już stoją

    def _on_stage_finished(self, name):
        """Etap pipeline'u zakończył zapis (worker, własne połączenie). Read-modele osi w głównym
        wątku odświeżamy DOPIERO TERAZ (nie w trakcie skanu — WAL → zapisy workera widoczne). Oś obiektu
        przeładowuje też facety (skan/resolver mogły dodać teleskopy/filtry/obiekty)."""
        self.axis_view.refresh()
        self.observatory_view.refresh()
        self.object_view._load_facets()
        self.object_view.refresh()
        self.grid_view._load_facets()
        self.grid_view.refresh()
        self.tasks_view.refresh_counts()    # liczniki zadań + badge ze świeżego stanu (F5)
        # Planer (T5): świeże klatki zmieniają POKRYCIE celów (godziny per kanał), więc plan nocy
        # policzony przed dostawą pokazywałby stare luki.
        self.planner_view.refresh()

    def _on_open_collection(self, name):
        """Zadanie z Porządków prowadzi do Zbiorów z ustawioną perspektywą (Duplikaty = flaga
        `only_dups` presetu, NIE drzewo filtra — R#14)."""
        self._show_view(NAV_ZBIORY)
        self.grid_view.apply_perspective(name)

    def _on_show_target_frames(self, canons):
        """Most planer → Zbiory (T5e, D-0731-7 WĄSKO): kanony celu → `object_id` → ISTNIEJĄCY facet
        Obiekt. Nieznany bazie kanon po prostu nie ma pary, a gdy nie ma ŻADNEJ — nie idziemy do
        gridu wcale: pusty facet pokazałby PEŁNĄ bazę i skłamał, że to klatki celu (przycisk jest
        wtedy nieaktywny, to bramka druga)."""
        pairs = [(r["id"], r["canon"]) for r in queries.object_ids_for_canons(self.con, canons)]
        if not pairs:
            self._flash(i18n.t("planner.no_object_for_target"))
            return
        self._show_view(NAV_ZBIORY)
        self.grid_view.apply_object_facet(pairs)

    def _on_tasks_counts(self, n):
        """Badge sidebara: „Porządki (N)" przy N>0; przy zerze GOŁE „Porządki" — „(0)" to szum (F5R#8)."""
        item = self.nav.item(NAV_PORZADKI)
        if item is not None:
            item.setText(i18n.t("nav.porzadki") if n == 0 else i18n.t("nav.porzadki_count", n=n))

    def _resolve_after_repair(self):
        """Takt 3 P-D wołany z okna „Napraw nagłówek…": ISTNIEJĄCY etap Dostawy. Zwraca POWÓD
        odmowy (okno je pokaże i zostanie otwarte) albo None — wtedy przełączamy widok na Dostawę,
        żeby postęp etapu był widoczny tam, gdzie zawsze. Przełączenie nie jest interakcją
        użytkownika, więc nie liczy się do budżetu kliknięć."""
        reason = self.pipeline_view.run_stage("resolve")
        if reason is None:
            self._show_view(NAV_DOSTAWA)
        return reason

    def _on_writeback_busy(self, busy):
        """Mutex DWÓCH powierzchni writebacku (D-PD-3). Grid pisze do plików → „Napraw nagłówek…"
        gaśnie; okno naprawy pisze → gaśnie Zatwierdź/Odrzuć/Cofnij gridu. Bez tego oba commity
        spotkałyby się na `BEGIN IMMEDIATE` (`busy_timeout` 5 s) i jeden wróciłby jako 'failed'."""
        self.object_view.set_writeback_busy(busy)

    def _on_pipeline_running(self, running):
        """W trakcie etapu wyłącz akcje zapisu osi (szczery disabled). Nawigacja zostaje aktywna —
        user może zerknąć na oś; blokujemy tylko ZAPIS (§6: aktywny tylko „Anuluj" skanu)."""
        self.axis_view.set_busy(running)
        self.observatory_view.set_busy(running)
        self.object_view.set_busy(running)     # „Przypisz obiekt…" (#8/P4) — zapis, gatowany jak inne
        self.grid_view.set_busy(running)     # grid ma akcje ZAPISU (staging/commit/undo) — gatuj (wizytator C1)
        self.planner_view.set_busy(running)  # planer czyta CAŁE archiwum — nie liczmy nocy na wpół zapisanej bazie

    # ---------------------------------------------------------------- menu Plik: Otwórz/Nowa baza

    def _on_open_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.open_db_title"), "", i18n.t("dialog.open_db_filter"))
        if path:
            self._open_path(path)

    def _on_new_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.new_db_title"), "", i18n.t("dialog.new_db_filter"))
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
        self._flash(i18n.t("main.db_loaded", path=path))

    def _sync_db_state(self):
        has = self.con is not None
        self.nav.setEnabled(has)
        self.stack.setVisible(has)
        self.empty_note.setVisible(not has)            # pusty stan w centrum (wizytator F5 #3)
        if not has:
            # bez timeoutu — to trwała podpowiedź pustego stanu, nie ulotny komunikat akcji
            self.statusBar().showMessage(i18n.t("main.no_db"))

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

    # Konsola Windows bywa cp1250 — komunikat ma polskie znaki; przełącz stdout na UTF-8 (best-effort,
    # jak `horreum.cli`), by `print` nie wywalił się na innym kodowaniu konsoli.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication([])

    # Trwałe ustawienia (Windows: rejestr) — przechowują ścieżkę ostatnio otwartej bazy i motyw.
    settings = QSettings("Horreum", "Horreum")

    # Motyw PRZED oknem (F6 §7): domyślnie ciemny; paleta/QSS/kolory stanów podłączone globalnie.
    apply_theme(app, theme.normalize(settings.value("ui/theme", theme.DEFAULT)))

    # Język PRZED oknem (#1, lustro motywu): jawny wybór z QSettings, inaczej auto z locale systemu
    # (gdy w available_langs), inaczej PL. Ustawiamy `_LANG` RAZ — stałe→klucze w widokach rozwiążą
    # etykiety z katalogu w czasie budowy (D-L1 restart-required v1; `_LANG` nie mutuje w sesji).
    saved_lang = settings.value("ui/lang", None)
    auto_lang = saved_lang if saved_lang is not None else QLocale().name()[:2]
    i18n.set_lang(auto_lang)

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
