"""Widok „Klatki" — grid nad EAV `cards` z filtrem i perspektywami (PLAN_gui_grid, KROK 3 scalenia).

READ-ONLY wobec danych (edycja/writeback = KROK 4). Doktryna §5: grid jest jedynym centrum, wszystko
inne to soczewki — ZERO modali w głównym przepływie. Warstwa widżetów (na whiteliście `test_gui_isolation`);
cała logika (silnik filtra, pivot, read-model) siedzi w Qt-wolnych `horreum.filter_engine`/`horreum.pivot`/
`horreum.gui.queries`. Model port `fitsmirror/gui/grid_model.py` (3 stany komórki + sort), bez edycji/stagingu.

Kolumny BAZOWE (warstwa interpretacji nad lustrem) + dynamiczne kolumny-keywordy z `cards`. Perspektywy =
nazwane {filtr+kolumny+grupowanie+sort} w **BAZIE** (`saved_query.spec_json`, migracja 0013) + presety
zaszyte w kodzie. **D-B ODWRÓCONE 2026-08-01 (GO Zdzinia, D-P-I-3), WDROŻONE w I-1:** nazwany widok jest
własnością ARCHIWUM, nie komputera — jedzie z bazą na laptop i przeżywa reinstalację. Rejestr zostaje
własnością BIURKA (progi, ostatnie katalogi); perspektywy zapisane w nim przed tą zmianą wciąga
JEDNORAZOWY, idempotentny import przy otwarciu widoku (`_import_settings_perspectives`) — wydanie
publiczne miało tę funkcję w `QSettings`, więc ciche porzucenie cudzych widoków byłoby regresją,
nie sprzątaniem. Grupowanie minimalne: nagłówki
grup po jednej kolumnie bazowej (D-D). `present` = kolumna statusu (zniknięte tłowane); Duplikaty = n_present>1.

F3 (PLAN_ux_redesign §4): pasek ZBIORU (`SelectionBar` — licznik + kryteria słowami + akcje) nad
`_PanelStack`, w którym klingi (`MacroBar`/`RenameBar`) są PANELAMI otwieranymi z akcji — widoczny
najwyżej JEDEN; przełączenie na cudzy panel czyści podgląd dotychczasowego właściciela (R#9).
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QModelIndex, QObject, Qt, QSettings, QThread, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QDialog, QMenu, QMessageBox,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTableView, QToolButton,
    QVBoxLayout, QWidget,
)

from horreum import (filter_engine, lineage, macro as macro_mod, naming, pivot as pivot_mod, repo,
                     stacks, writeback)
from horreum.gui import busy, facet_model, i18n, portfolio, queries, rows, theme
from horreum.gui.facets import RAIL_MIN_W as _FIELDS_MIN_W, FacetRail
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.projection_dialog import ProjectionDialog
from horreum.gui.rows import TwoPartDelegate
from horreum.gui.wb_worker import WritebackRunner

# Kolumny bazowe: (nagłówek, klucz). Klucze `_telescope`/`_object`/`_dt_delta` = pochodne. `_dt_delta`
# (Δh nagłówek−nazwa) liczone w `_derive` z `naming.header_dt`/`filename_dt` — `base_rows` zwraca już
# date_obs+path (zero zmian SQL). Kolumna renamu: grupowanie po Δh wykrawa homogeniczny wsad (§1).
# Para (klucz-etykiety, klucz-danych). Klucz-etykiety → i18n.t w BUDOWIE nagłówka (headerData), nie
# module-level (D-L1). Etykiety reużyte z katalogu app (col.path/frame.col.*/object.col.name) — SPOT.
BASE_COLS = [
    ("col.path", "path"), ("grid.col.kind", "kind"), ("frame.col.camera", "camera_model"),
    ("frame.col.telescope", "_telescope"), ("object.col.name", "_object"),
    ("frame.col.filter", "filter_canon"), ("grid.col.dt_delta", "_dt_delta"),
]
_MISSING_TEXT = "—"


# Pusty grid mówi DWIE różne rzeczy — filtr nic nie wpuścił vs. w bazie nie ma nic (wiz F5 #8:
# „zmień filtr lub perspektywę" na pustej bazie wysyła usera w ślepy zaułek zamiast po dostawę).
# Stałe trzymają KLUCZ (nie string) — rozwiązywane `i18n.t` w USE-site (D-L1; string zamroziłby PL).
_EMPTY_FILTER = "grid.empty_filter"
_EMPTY_DB = "grid.empty_db"

# Kolory stanów gridu — z motywu (F6 §7, SPOT). Model czyta `_COLORS` NA ŻYWO w `data()`
# (Qt nie cache'uje BackgroundRole), więc `use_theme` przy przełączeniu + `viewport().update()`
# przemalowuje bez przebudowy modelu. Klucze: missing (foreground braku) / vanished_bg (present=0)
# / dup_bg (>1 obecna) / group_bg (nagłówek grupy) / touched_bg (dotknięty makrem) / skipped_bg.
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory stanów gridu z motywu (Qt-wolny `theme.grid_colors`). Wołane przy imporcie
    oraz przez `app.apply_theme` przy przełączeniu skórki.

    `secondary_text` dokładamy z akcentów, bo wygaszony wiersz listy (odrzucone wejście rodowodu)
    to QListWidgetItem, a QSS ról nie dosięga do `setForeground` itemu — ta sama droga, którą
    `tasks.use_theme` gasi wiersze bez roboty."""
    _COLORS.update({k: QColor(v) for k, v in theme.grid_colors(name).items()})
    _COLORS["secondary_text"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)     # init przy imporcie (QColor bez QApplication — jak dawne stałe modułu)


def _vanished_tip(row):
    """Człon tooltipu kolumny ścieżki dla klatki ZNIKNIĘTEJ — z DATĄ, gdy baza ją zna.

    Wizytacja P5 #11: przy szukaniu backupu liczy się katalog i data. Katalog tooltip niósł od
    początku (pełna ścieżka), daty NIE niósł nikt — a `location.last_verified_at` na wierszu
    `present=0` jest dokładnie chwilą oznaczenia (patrz `queries.base_rows`). Kolumna zostaje przy
    nazwie pliku: doklejenie katalogu do DISPLAY zjadałaby elizja, a zmiana dotknęłaby wszystkich
    perspektyw, nie tylko „Zniknięte". Data do MINUT, bez „T" (wzorzec `app._fmt_event_ts`).
    Baza sprzed markera (`NULL`) → człon bez daty; brak faktu nie ma prawa udawać faktu."""
    ts = row.get("last_verified_at")
    if not ts:
        return i18n.t("grid.tip.vanished")
    return i18n.t("grid.tip.vanished_at", ts=str(ts)[:16].replace("T", " "))


def _set_role(w, role):
    """Zmiana roli koloru (`theme.ROLES` → QSS aplikacji) na ŻYWYM widżecie. Samo `setProperty` nic
    nie przemaluje: selektor `[role="…"]` jest ewaluowany przy POLISHU, więc widżet już pokazany
    trzyma stary kolor do końca życia. Dotyczy jedynej roli zmiennej w locie — kropki poczekalni."""
    w.setProperty("role", role)
    w.style().unpolish(w)
    w.style().polish(w)

# Operatory filtra: (klucz-etykiety, op). Etykieta → i18n.t w budowie combo; op to DANE (regex POMINIĘTY, D-F).
OPERATORS = [
    ("grid.op.eq", "eq"), ("grid.op.ne", "ne"), ("grid.op.gt", "gt"), ("grid.op.lt", "lt"),
    ("grid.op.ge", "ge"), ("grid.op.le", "le"), ("grid.op.contains", "contains"),
    ("grid.op.startswith", "startswith"), ("grid.op.exists", "exists"),
    ("grid.op.not_exists", "not_exists"),
]
_NO_VALUE = {"exists", "not_exists"}

# Szum strukturalny FITS: keywordy o najwyższym pokryciu, ale bez wartości analitycznej. Spychane na dół
# listy Pól i pomijane przy domyślnym doborze kolumn (P3-6) — NIE ukrywane (user może chcieć NAXIS jako kolumnę).
STRUCT_NOISE = {"SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND", "BZERO", "BSCALE", "END",
                "XBINNING", "YBINNING", "XPIXSZ", "YPIXSZ", "PCOUNT", "GCOUNT"}

# Presety perspektyw (zaszyte): (nazwa, {filter_tree, group_by}). Kolumny domyślne dobierane z pokrycia.
# PRESET_DUPS = stała współdzielona z TasksView (F5R#11 — klik w zadanie „Duplikaty" celuje w preset
# po nazwie; rename presetu bez stałej cicho degradowałby klik do „nieznana perspektywa").
PRESET_DUPS = "Duplikaty"
# PRESET_VANISHED — bliźniak PRESET_DUPS dla passa obecności (P5/#7): klik w zadanie „Zniknięte
# z dysku" celuje w preset PO NAZWIE, więc stała musi być współdzielona z TasksView.
PRESET_VANISHED = "Zniknięte"
PRESETS = {
    "Przegląd": {"filter": None, "group_by": None},
    "Kalibracja": {"filter": {"op": "OR", "conditions": [
        {"keyword": "IMAGETYP", "operator": "contains", "value": "dark"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "flat"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "bias"},
    ]}, "group_by": "kind"},
    PRESET_DUPS: {"filter": None, "group_by": None, "only_dups": True},
    PRESET_VANISHED: {"filter": None, "group_by": None, "only_vanished": True},
    "Do przeglądu": {"filter": None, "group_by": None, "only_review": True},
}
# Etykieta WYŚWIETLANIA presetu (tekst) osobno od TOŻSAMOŚCI (klucz PRESETS w `itemData` — używany przez
# `apply_perspective`/`_on_perspective`/`tasks.py`, odporny na tłumaczenie tekstu). Split D-L3.
_PRESET_LABELS = {
    "Przegląd": "perspective.review",
    "Kalibracja": "perspective.calibration",
    PRESET_DUPS: "perspective.dups",
    PRESET_VANISHED: "perspective.vanished",
    "Do przeglądu": "perspective.to_review",
}


def _obj_label(row):
    """Nazwa obiektu do kolumny — kanon, inaczej surowe zeznanie, inaczej PODPOWIEDŹ Z FOLDERU.

    Trzeci szczebel dołożył firsthand Zdzinia 0808 i jest wąski Z POMIARU, nie z ostrożności.
    Kubełek „bez nazwy, gotowe stosy" daje 18 wierszy, których NIE DA SIĘ ODRÓŻNIĆ na ekranie:
    nazwy plików generuje WBPP i wyglądają tak (`masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_
    FILTER-NoFilter__B.xisf`), że sześć stosów LMC i jeden IC443 czyta się identycznie. Tożsamość
    siedzi WYŁĄCZNIE w folderze — i tam jej nie widać, bo kolumna pokazuje ogon ścieżki. Recepta
    kubełka brzmi „nazwij ten obraz", a człowiek nie wie, KTÓRY nazywa.

    DLACZEGO TYLKO `master_light`: light z akwizycji niesie oznaczenie we WŁASNEJ nazwie i ma
    osobną drogę (szczebel ścieżki S2 PROPONUJE mu kanon). Stos jej nie ma — dlatego dług E3-1
    („świadek ścieżki nie sięga drzewa stosów") istnieje. To jego najtańsza połowa: pokazujemy
    to, co widać w ścieżce, i ANI KROKU DALEJ.

    PODPOWIEDŹ NIE UDAJE NAZWY — nawiasy kątowe odróżniają ją od kanonu, bo kolumna miesza wtedy
    dwa różne twierdzenia („tak się ten obiekt nazywa" i „tyle wiem ze ścieżki"), a wzięcie
    drugiego za pierwsze byłoby gorsze niż pusta komórka. Nic z tego nie trafia do bazy: to
    warstwa PREZENTACJI, gest osi obiektu dalej należy do człowieka."""
    nazwa = row.get("object_canon") or row.get("object_raw")
    if nazwa:
        return nazwa
    if row.get("kind") != "master_light":
        return ""
    folder = queries.stack_folder(row.get("path"))
    return f"⟨{folder}⟩" if folder else ""


def _half_away(x):
    """Zaokrąglij do int metodą half-away-from-zero (NIE goły `round()`, który jest half-to-even —
    R2 #5). Używane do przełożenia float-mediany Δ na całkowity offset spinu."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x)) if x else 0


def _dt_delta_hours(date_obs, path):
    """Δ = DATE-OBS − czas z nazwy pliku, w godzinach (float) albo None. Guard `path is None`
    (LEFT JOIN location — `basename(None)` = TypeError, R1 #11). Brak któregoś źródła → None."""
    if path is None:
        return None
    h = naming.header_dt(date_obs)
    fn = naming.filename_dt(os.path.basename(path))
    if h is None or fn is None:
        return None
    return (h - fn).total_seconds() / 3600.0


def _derive(row):
    """sqlite3.Row → dict z polami pochodnymi (_telescope/_object/_dt_delta) do kolumn bazowych."""
    d = {k: row[k] for k in row.keys()}
    d["_telescope"] = queries.telescope_label(row)
    # Ze SŁOWNIKA, nie z surowego wiersza: `_obj_label` pyta o `kind`/`path`, a te wchodzą nie
    # z każdego zapytania gridu — `sqlite3.Row` na brakującym kluczu rzuca, `dict.get` oddaje None.
    # Ta sama obrona, co przy `_dt_delta_hours` linijkę niżej.
    d["_object"] = _obj_label(d)
    d["_dt_delta"] = _dt_delta_hours(d.get("date_obs"), d.get("path"))
    return d


class GridTableModel(QAbstractTableModel):
    """Model read-only: kolumny bazowe + dynamiczne kolumny-keywordy. 3 stany komórki keyworda; sort
    numeryczny (po `PivotCell.num`) / tekstowy, MISSING na końcu; grupowanie = nagłówki grup w płaskiej
    liście. Karmiony gotowymi danymi (`set_data`) — zero SQL/plików."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []          # dict-y klatek (z 'cells') PRZEPLATANE markerami grup {'_group':..,'_count':..}
        self._data_rows = []     # same klatki (bez markerów) — źródło do sortu/grupowania
        self._keywords = []
        self._group_by = None
        self._sort_col = 0
        self._sort_desc = False
        self._numeric_kw = set() # keywordy z choć jedną komórką liczbową → MISSING „—" też prawo (P3-7)
        self._preview = {}       # frame_id → {'keyword','old','new'} | {'skipped': reason} (podgląd makra/renamu)
        self._preview_label = i18n.t("grid.preview.macro")   # etykieta efemerycznej kolumny (klinga-zależna, R1 #4)

    def set_preview(self, preview, *, label=None):
        """Podgląd klingi (doktryna §5: „grid = podgląd"): frame_id → zmiana (stara→nowa) albo
        pominięcie z powodem. Dokłada EFEMERYCZNĄ kolumnę (`label`, np. „makro →"/„nazwa →") na końcu;
        `{}`/None ją zdejmuje. `label` rozróżnia klingę (makro vs rename) w tym samym podglądzie (R1 #4);
        `None` → domyślna „makro →" z katalogu (rozwiązywana w wywołaniu, nie w sygnaturze — D-L1)."""
        self.beginResetModel()
        self._preview = dict(preview or {})
        self._preview_label = label if label is not None else i18n.t("grid.preview.macro")
        self.endResetModel()

    def _preview_active(self):
        return bool(self._preview)

    def set_data(self, base_rows, pivot, keywords, group_by=None):
        """base_rows: list[dict] (z `_derive`); pivot: horreum.pivot.Pivot; keywords: list[str]."""
        cells = {r.frame_id: r.cells for r in pivot.rows}
        for d in base_rows:
            d["cells"] = cells.get(d["frame_id"], {})
        self._data_rows = list(base_rows)
        self._keywords = list(keywords)
        # Kolumna-keyword jest NUMERYCZNA, gdy ma choć jedną komórkę liczbową — wtedy MISSING „—"
        # wyrównujemy w prawo, by nie wisiał po lewej pod słupkiem liczb (wizytator P3-7).
        self._numeric_kw = set()
        for kw in self._keywords:
            for d in self._data_rows:
                c = d["cells"].get(kw, pivot_mod.MISSING)
                if c is not pivot_mod.MISSING and c.num is not None:
                    self._numeric_kw.add(kw)
                    break
        self._group_by = group_by
        self._rebuild()

    # ---- kształt ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(BASE_COLS) + len(self._keywords) + (1 if self._preview_active() else 0)

    def _preview_col(self):
        """Indeks efemerycznej kolumny podglądu makra (ostatnia) albo None, gdy podgląd nieaktywny."""
        return len(BASE_COLS) + len(self._keywords) if self._preview_active() else None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section == self._preview_col():
                return self._preview_label
            if section < len(BASE_COLS):
                return i18n.t(BASE_COLS[section][0])
            return self._keywords[section - len(BASE_COLS)]
        return section + 1

    def _col_key(self, col):
        return BASE_COLS[col][1] if col < len(BASE_COLS) else None

    def _kw_for_col(self, col):
        return None if col < len(BASE_COLS) else self._keywords[col - len(BASE_COLS)]

    # ---- komórki ----
    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and isinstance(self._rows[index.row()], dict) and "_group" in self._rows[index.row()]:
            return Qt.ItemIsEnabled  # nagłówek grupy: nieselektowalny
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if "_group" in row:  # marker grupy
            if role == Qt.DisplayRole and col == 0:
                return f"▸ {row['_group']}  ({row['_count']})"
            if role == Qt.BackgroundRole:
                return _COLORS["group_bg"]
            if role == Qt.FontRole and col == 0:
                f = QFont(); f.setBold(True); return f
            return None

        if col == self._preview_col():
            return self._preview_cell(row, role)
        if col < len(BASE_COLS):
            return self._base_cell(row, self._col_key(col), role)
        return self._kw_cell(row, self._kw_for_col(col), role)

    def _preview_cell(self, row, role):
        """Komórka podglądu makra: dotknięty frame → „stara → nowa" (tooltip pełny); pominięty →
        „(pominięto)" z powodem w tooltipie; nietknięty → pusto (doktryna §5)."""
        pv = self._preview.get(row.get("frame_id"))
        if pv is None:
            return None
        if "skipped" in pv:
            if role == Qt.DisplayRole:
                return i18n.t("grid.preview.skipped")
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.ToolTipRole:
                return i18n.t("grid.preview.skipped_tip", reason=pv['skipped'])
            return None
        if role == Qt.DisplayRole:
            if pv.get("op") == "rename":
                return str(pv["new"])          # tylko NOWA nazwa (stara jest w kol. „Ścieżka"; wiz #1)
            old = "∅" if pv.get("old") is None else str(pv["old"])
            return f"{old} → {pv['new']}"
        if role == Qt.ToolTipRole:
            return f"{pv['keyword']}: {pv.get('old')!r} → {pv['new']!r} ({pv['op']})"
        if role == Qt.FontRole:
            f = QFont(); f.setBold(True); return f
        return None

    def _base_cell(self, row, key, role):
        vanished = row.get("present") == 0 and (row.get("n_present") or 0) == 0
        dup = (row.get("n_present") or 0) > 1
        if role == Qt.BackgroundRole:
            # Podgląd makra WYGRYWA tło (bieżący fokus): dotknięty/pominięty wiersz widoczny w
            # kolumnach bazowych NIEZALEŻNIE od scrolla poziomego (wizytator #1/#2 — „widać zanim zapiszesz").
            pv = self._preview.get(row.get("frame_id")) if self._preview else None
            if pv is not None:
                return _COLORS["skipped_bg"] if "skipped" in pv else _COLORS["touched_bg"]
            if vanished:
                return _COLORS["vanished_bg"]
            if dup:
                return _COLORS["dup_bg"]
            return None
        if key == "path":
            path = row.get("path") or ""
            if role == Qt.DisplayRole:
                name = os.path.basename(path) if path else i18n.t("object.no_location")
                # Prefiks „×N" PRZED nazwą (P2-2): sufiks ginął przy elizji długich ścieżek.
                return f"×{row['n_present']}  {name}" if dup else name
            if role == Qt.ToolTipRole:
                extra = _vanished_tip(row) if vanished else (
                    i18n.t("grid.tip.dup_locs", n=row['n_present']) if dup else "")
                return (path or i18n.t("object.no_location")) + extra
            return None
        if key == "_dt_delta":
            # JEDEN typ: zawsze float godzin (R2 #3). Pełne godziny renderują się „-2", ułamek „-1.97"
            # (`:g`); ŻADNYCH stringów-znaczników (mieszany typ rozbrajałby sort numeryczny R1 #6). Flaga
            # niepełnogodzinności mieszka WYŁĄCZNIE w panelu daty RenameBar, nie w komórce.
            v = row.get("_dt_delta")
            if role == Qt.DisplayRole:
                return "" if v is None else f"{v:g}"           # None → pusta komórka (R1 #7)
            if role == Qt.TextAlignmentRole and v is not None:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if role == Qt.ToolTipRole and v is not None:
                return f"DATE-OBS − czas z nazwy = {v!r} h"     # surowy float (kontrola kwantyzacji)
            return None
        if role == Qt.DisplayRole:
            v = row.get(key)
            return "" if v is None else str(v)
        return None

    def _kw_cell(self, row, kw, role):
        cell = row["cells"].get(kw, pivot_mod.MISSING)
        if cell is pivot_mod.MISSING:
            if role == Qt.DisplayRole:
                return _MISSING_TEXT
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.FontRole:
                f = QFont(); f.setItalic(True); return f
            if role == Qt.TextAlignmentRole and kw in self._numeric_kw:
                return int(Qt.AlignRight | Qt.AlignVCenter)   # „—" pod słupkiem liczb (wizytator P3-7)
            if role == Qt.ToolTipRole:
                return "brak karty"
            return None
        if role == Qt.DisplayRole:
            return "" if cell.raw is None else str(cell.raw)
        if role == Qt.TextAlignmentRole and cell.num is not None:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    # ---- sort + grupowanie ----
    def set_group_by(self, group_by):
        self._group_by = group_by
        self._rebuild()

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort_col = column
        self._sort_desc = order == Qt.DescendingOrder
        self._rebuild()

    def _sort_key(self, row):
        col = self._sort_col
        if col >= len(BASE_COLS) + len(self._keywords):   # kolumna podglądu makra → sort neutralny
            return (0, "")
        kw = self._kw_for_col(col)
        if kw is None:
            key = self._col_key(col)
            if key == "_dt_delta":                            # gałąź numeryczna (R1 #6), None na koniec
                v = row.get("_dt_delta")
                return (2, 0.0) if v is None else (0, float(v))
            v = row.get(key)
            return (0, "" if v is None else str(v).lower())
        cell = row["cells"].get(kw, pivot_mod.MISSING)
        if cell is pivot_mod.MISSING:
            return (2, "")  # MISSING zawsze na końcu (niezależnie od kierunku)
        if cell.num is not None:
            return (0, cell.num)
        return (1, "" if cell.raw is None else str(cell.raw).lower())

    def _group_value(self, row):
        if self._group_by in (None, ""):
            return None
        v = row.get(self._group_by)
        if v in (None, ""):
            return "(brak)"
        if self._group_by == "_dt_delta":
            return f"{v:g}"                                    # etykieta grupy spójna z komórką („-2")
        return str(v)

    def _rebuild(self):
        self.beginResetModel()
        # MISSING-na-końcu: rozdziel klucz sortu (0/1 present, 2 missing) — reverse tylko w obrębie present.
        rows = sorted(self._data_rows, key=self._sort_key,
                      reverse=self._sort_desc)
        # reverse psuje „MISSING na końcu" — przenieś markery MISSING zawsze na koniec:
        if self._sort_desc:
            present = [r for r in rows if self._sort_key(r)[0] != 2]
            missing = [r for r in self._data_rows if self._sort_key(r)[0] == 2]
            rows = present + missing
        if self._group_by in (None, ""):
            self._rows = list(rows)
        else:
            if self._group_by == "_dt_delta":                 # porządek nagłówków grup NUMERYCZNY (R2 #4):
                rows = sorted(rows, key=lambda r: (           # inaczej „-1", „-12", „-2"; None-grupa na koniec
                    r.get("_dt_delta") is None, r.get("_dt_delta") or 0.0))
            else:
                rows = sorted(rows, key=lambda r: (self._group_value(r) or "").lower())
            self._rows = []
            cur = object()
            bucket = []
            def flush():
                if bucket:
                    self._rows.append({"_group": cur, "_count": len(bucket)})
                    self._rows.extend(bucket)
            for r in rows:
                g = self._group_value(r)
                if g != cur:
                    flush(); cur = g; bucket = []
                bucket.append(r)
            flush()
        self.endResetModel()


class FilterPanel(QWidget):
    """Minimalny builder drzewa filtra: wiersze [keyword][operator][wartość][×] + selektor AND/OR
    + checkbox „Odwróć" (F1 redesignu: owija drzewo w NOT — `uniwersum − wynik`).
    Emituje `filterApplied(dict|None)` — GUI v1 buduje jednopoziomową grupę (rdzeń wspiera głębiej)."""

    filterApplied = Signal(object)

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        self._rows = []
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.combo_op = QComboBox(); self.combo_op.addItems(["AND", "OR"])
        top.addWidget(QLabel(i18n.t("grid.filter.join"))); top.addWidget(self.combo_op)
        btn_add = QPushButton(i18n.t("grid.filter.add_cond")); btn_add.clicked.connect(self.add_row); top.addWidget(btn_add)
        self.chk_invert = QCheckBox(i18n.t("grid.filter.invert"))
        top.addWidget(self.chk_invert)
        btn_apply = QPushButton(i18n.t("grid.filter.apply")); btn_apply.clicked.connect(self._apply); top.addWidget(btn_apply)
        btn_clear = QPushButton(i18n.t("grid.filter.clear")); btn_clear.clicked.connect(self._clear); top.addWidget(btn_clear)
        top.addStretch(1)
        outer.addLayout(top)
        self._rows_box = QVBoxLayout(); outer.addLayout(self._rows_box)
        self.add_row()   # jeden pusty wiersz domyślnie — pierwszy filtr bez „+ warunek" (P3-4)

    def add_row(self):
        rw = QHBoxLayout()
        kw = QComboBox(); kw.setEditable(True); kw.addItems(self._keywords)
        op = QComboBox()
        for label, _ in OPERATORS:
            op.addItem(i18n.t(label))
        val = QLineEdit()
        val.returnPressed.connect(self._apply)   # Enter w polu wartości = Zastosuj (P3-4)
        rm = QPushButton("×"); rm.setFixedWidth(28)
        rw.addWidget(kw, 2); rw.addWidget(op, 1); rw.addWidget(val, 2); rw.addWidget(rm)
        holder = QWidget(); holder.setLayout(rw)
        self._rows_box.addWidget(holder)
        entry = {"kw": kw, "op": op, "val": val, "holder": holder}
        rm.clicked.connect(lambda: self._remove(entry))
        self._rows.append(entry)

    def set_keywords(self, keywords):
        """Odśwież listę keywordów we WSZYSTKICH combo, także w wierszach już zbudowanych — inaczej wiersz
        domyślny (dodany w `__init__`, zanim `_load_facets` pozna keywordy) zostaje z pustą listą i klik nie
        rozwija pola do wyboru. Editable → zachowaj wpisany tekst. Bliźniacze do `MacroBar.set_keywords`."""
        self._keywords = list(keywords)
        for e in self._rows:
            combo = e["kw"]
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear(); combo.addItems(self._keywords); combo.setCurrentText(cur)
            combo.blockSignals(False)

    def _remove(self, entry):
        entry["holder"].setParent(None)
        self._rows.remove(entry)

    def _clear(self):
        for e in list(self._rows):
            self._remove(e)
        self.chk_invert.setChecked(False)   # „Wyczyść" = pełny reset, także negacji
        self.add_row()   # zostaw pusty wiersz gotowy do następnego filtra
        self.filterApplied.emit(None)

    def set_tree(self, tree):
        """Odtwarza wiersze panelu z drzewa JEDNOPOZIOMOWEGO — synchronizuje panel z filtrem perspektywy
        (P3-3: bez tego preset ustawia filtr, a panel jest pusty → kolejny „Zastosuj" po cichu go nadpisuje).
        Korzeń NOT (F1, R#1 BLOKUJĄCE): zaznacz „Odwróć" i odtwórz DZIECKO płaską logiką — bez tego
        perspektywa z NOT wczytuje się w pusty panel i pierwszy „Zastosuj" po cichu kasuje negację.
        Głębsze zagnieżdżenie (grupa w grupie) niereprezentowalne w płaskim panelu → pusty wiersz. NIE emituje
        `filterApplied` (wołający już odświeża)."""
        for e in list(self._rows):
            self._remove(e)
        invert = (isinstance(tree, dict) and "operator" not in tree
                  and str(tree.get("op", "")).upper() == "NOT")
        self.chk_invert.setChecked(invert)
        if invert:
            children = tree.get("conditions", [])
            tree = children[0] if len(children) == 1 else None   # ≠1 dziecko: defensywnie pusty panel
        if tree is None:
            self.add_row()
            return
        if "operator" in tree:                     # pojedynczy warunek
            op_group, conds = "AND", [tree]
        else:
            op_group = str(tree.get("op", "AND")).upper()
            conds = tree.get("conditions", [])
        self.combo_op.setCurrentText(op_group if op_group in ("AND", "OR") else "AND")
        if not conds or not all("operator" in c for c in conds):
            self.add_row()                         # niereprezentowalne → nie udawaj, że oddajemy filtr
            return
        for c in conds:
            self.add_row()
            e = self._rows[-1]
            e["kw"].setCurrentText(c["keyword"])
            for i, (_, opc) in enumerate(OPERATORS):
                if opc == c["operator"]:
                    e["op"].setCurrentIndex(i)
                    break
            if "value" in c:
                e["val"].setText(str(c["value"]))

    def build_tree(self):
        conds = []
        for e in self._rows:
            kw = e["kw"].currentText().strip()
            if not kw:
                continue
            op = OPERATORS[e["op"].currentIndex()][1]
            if op in _NO_VALUE:
                conds.append({"keyword": kw, "operator": op})
                continue
            val = e["val"].text()
            if val.strip() == "":
                continue   # wiersz niedokończony (edytowalne combo auto-wybiera keyword) — NIE wstrzykuj `eq ''`
            conds.append({"keyword": kw, "operator": op, "value": val})
        if not conds:
            return None   # pusty panel = uniwersum, BEZ owijania w NOT (checkbox bez warunków nie kłamie ∅-em)
        tree = {"op": self.combo_op.currentText(), "conditions": conds}
        if self.chk_invert.isChecked():
            return {"op": "NOT", "conditions": [tree]}
        return tree

    def _apply(self):
        self.filterApplied.emit(self.build_tree())


class FieldsPanel(QWidget):
    """Panel Pól: checkbox kolumny-keyworda + pokrycie inline (ile klatek ma daną kartę). Emituje
    `columnsChanged(list[str])`. Integruje wybór kolumn i pokrycie w JEDNYM panelu (bez modalu Pokrycie).

    Pokrycie idzie w PRAWĄ kolumnę (`rows.TwoPartDelegate`): przy 1200 px splitter 1:4 skąpi lewej
    stronie i liczniki doklejone do keyworda były ucięte (wiz F3 #4). Minimum szerokości jak listwa
    facetów — obie części lewej kolumny mają ten sam próg czytelności."""

    columnsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(QLabel(i18n.t("grid.fields.title")))
        self.list = QListWidget()
        self.list.setItemDelegate(TwoPartDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemChanged.connect(self._on_changed)
        outer.addWidget(self.list)
        self.setMinimumWidth(_FIELDS_MIN_W)
        self._loading = False

    def load(self, facets, checked):
        """facets: wiersze (keyword, n). checked: set[str] zaznaczonych."""
        self._loading = True
        try:
            self.list.clear()
            for f in facets:
                kw, n = f["keyword"], f["n"]
                it = QListWidgetItem(kw)
                it.setData(rows.SECONDARY, f"({n})")     # pokrycie w prawej kolumnie (wiz F3 #4)
                it.setData(Qt.UserRole, kw)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if kw in checked else Qt.Unchecked)
                self.list.addItem(it)
        finally:
            self._loading = False

    def checked_keywords(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _on_changed(self, _item):
        if not self._loading:
            self.columnsChanged.emit(self.checked_keywords())


class MacroBar(QWidget):
    """Panel makra (F3: strona `_PanelStack`, otwierana z paska zbioru „Popraw nagłówki…") — sekcje
    Oblicz/Przypisz. Emituje `preview(dict)` (policz i pokaż w gridzie, BEZ zapisu), `stage(dict)`
    (do szuflady), `cleared()`. Makro operuje na tym, co widać w gridzie (frame_ids wołającego)."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)
        # Oblicz (opcjonalny krok pośredni: nazwa = wyrażenie)
        comp = QHBoxLayout()
        comp.addWidget(QLabel(i18n.t("grid.macro.compute")))
        self.comp_name = QLineEdit(); self.comp_name.setPlaceholderText(i18n.t("grid.macro.name_ph"))
        self.comp_name.setFixedWidth(120)
        self.comp_expr = QLineEdit(); self.comp_expr.setPlaceholderText(i18n.t("grid.macro.expr_ph"))
        comp.addWidget(self.comp_name); comp.addWidget(QLabel("=")); comp.addWidget(self.comp_expr, 1)
        b.addLayout(comp)
        # Przypisz (keyword op wartość)
        asg = QHBoxLayout()
        asg.addWidget(QLabel(i18n.t("grid.macro.assign")))
        self.asg_kw = QComboBox(); self.asg_kw.setEditable(True); self.asg_kw.addItems(keywords)
        self.asg_kw.setFixedWidth(160)
        self.asg_op = QComboBox(); self.asg_op.addItems(["set", "add"])
        self.asg_expr = QLineEdit(); self.asg_expr.setPlaceholderText(i18n.t("grid.macro.assign_ph"))
        asg.addWidget(self.asg_kw); asg.addWidget(self.asg_op); asg.addWidget(QLabel("=")); asg.addWidget(self.asg_expr, 1)
        b.addLayout(asg)
        # akcje
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    def set_actions_enabled(self, on):
        """Wyłącz Podgląd/Do stagingu, gdy nie ma widocznych klatek (szczery disabled zamiast cichego
        no-op — wizytator #4). `Wyczyść podgląd` zostaje aktywny (zdejmuje ewentualny stary podgląd)."""
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_keywords(self, keywords):
        self._keywords = keywords
        cur = self.asg_kw.currentText()
        self.asg_kw.blockSignals(True)
        self.asg_kw.clear(); self.asg_kw.addItems(keywords); self.asg_kw.setCurrentText(cur)
        self.asg_kw.blockSignals(False)

    def macro_def(self):
        """Zbierz definicję makra z pól (None, gdy brak keyworda/wartości przypisania)."""
        kw = self.asg_kw.currentText().strip()
        expr = self.asg_expr.text().strip()
        if not kw or not expr:
            return None
        md = {"assign": {"keyword": kw, "op": self.asg_op.currentText(), "expr": expr}}
        cname, cexpr = self.comp_name.text().strip(), self.comp_expr.text().strip()
        if cname and cexpr:
            md["computes"] = [{"name": cname, "expr": cexpr}]
        return md

    def _emit_preview(self):
        md = self.macro_def()
        if md is not None:
            self.preview.emit(md)

    def _emit_stage(self):
        md = self.macro_def()
        if md is not None:
            self.stage.emit(md)


class _TokenRow(QWidget):
    """Jeden rząd edytora wzoru: typ tokenu + argument (folder→poziom, orig→regex) + ↑↓⊖. `spec()`
    zwraca goły string (token bez argumentu) LUB dict `{"t":…}` (parametryczny) — forma DANE `naming`."""

    changed = Signal()
    removeRequested = Signal(object)
    moveRequested = Signal(object, int)                # (self, -1 w górę / +1 w dół)

    # (klucz-etykiety, tid). Etykieta → i18n.t w budowie combo; tid to DANE `naming`.
    _TOKENS = (("grid.token.datetime", "datetime"), ("grid.token.object", "object"),
               ("grid.token.kind", "kind"), ("grid.token.filter", "filter"),
               ("grid.token.exp", "exp"), ("grid.token.disc", "disc"),
               ("grid.token.folder", "folder"), ("grid.token.orig", "orig"))

    def __init__(self, spec="kind", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(); self.combo.setFixedWidth(170)     # stała kolumna typu (wiz #2 — bez ragged)
        for lbl, tid in self._TOKENS:
            self.combo.addItem(i18n.t(lbl), tid)
        lay.addWidget(self.combo)
        self.level = QSpinBox(); self.level.setRange(1, 8); self.level.setPrefix(i18n.t("grid.token.level_prefix"))
        lay.addWidget(self.level)
        self.regex = QLineEdit(); self.regex.setPlaceholderText(i18n.t("grid.token.regex_ph"))
        self.regex.setMinimumWidth(160)
        lay.addWidget(self.regex)
        lay.addStretch(1)                                           # wypełniacz → przyciski zawsze przy prawej
        btn_up = QPushButton("↑"); btn_dn = QPushButton("↓"); btn_rm = QPushButton("⊖")
        for b in (btn_up, btn_dn, btn_rm):
            b.setFixedWidth(28); lay.addWidget(b)
        btn_up.clicked.connect(lambda: self.moveRequested.emit(self, -1))
        btn_dn.clicked.connect(lambda: self.moveRequested.emit(self, +1))
        btn_rm.clicked.connect(lambda: self.removeRequested.emit(self))
        self.combo.currentIndexChanged.connect(self._sync_args)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.level.valueChanged.connect(lambda *_: self.changed.emit())
        self.regex.textChanged.connect(lambda *_: self.changed.emit())
        self.set_spec(spec)

    def _sync_args(self):
        tok = self.combo.currentData()
        self.level.setVisible(tok == "folder")
        self.regex.setVisible(tok == "orig")

    def set_spec(self, spec):
        tok = spec.get("t") if isinstance(spec, dict) else spec
        args = spec if isinstance(spec, dict) else {}
        i = self.combo.findData(tok)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        if tok == "folder":
            self.level.setValue(int(args.get("n", 1)))
        elif tok == "orig":
            self.regex.setText(str(args.get("re", "")))
        self._sync_args()

    def spec(self):
        tok = self.combo.currentData()
        if tok == "folder":
            return {"t": "folder", "n": self.level.value()}
        if tok == "orig":
            return {"t": "orig", "re": self.regex.text()}
        return tok


class _TemplateEditor(QWidget):
    """Edytor wzoru nazwy (§5): lista `_TokenRow` + [+ Token][Przywróć domyślny]. `template()` = lista
    specyfikacji (DANE dla `naming.run_rename`). Domyślny preset = `DEFAULT_TEMPLATE` (Z `disc` — D-I4
    bezpieczny domyśl; czyste nazwy = user RĘCZNIE usuwa rząd `disc`, kolizja → warning+skip)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(i18n.t("grid.tmpl.title")); lbl.setProperty("role", "secondary")
        head.addWidget(lbl); head.addStretch(1)
        btn_add = QPushButton(i18n.t("grid.tmpl.add_token")); btn_def = QPushButton(i18n.t("grid.tmpl.restore"))
        head.addWidget(btn_add); head.addWidget(btn_def)
        outer.addLayout(head)
        self._empty_hint = QLabel(i18n.t("grid.tmpl.empty_hint")); self._empty_hint.hide()
        self._empty_hint.setProperty("role", "secondary")
        outer.addWidget(self._empty_hint)
        self._host = QWidget()
        self._rows_lay = QVBoxLayout(self._host); self._rows_lay.setContentsMargins(0, 0, 0, 0)
        # Sufit wysokości + scroll (wiz #1): rozbudowany wzór NIE zjada gridu — nadwyżka scrolluje.
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True); self._scroll.setWidget(self._host)
        self._scroll.setFrameShape(QFrame.NoFrame); self._scroll.setMaximumHeight(200)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)
        btn_add.clicked.connect(lambda: (self._add_row("kind"), self.changed.emit()))
        btn_def.clicked.connect(lambda: self._restore_default())
        self.set_template(naming.DEFAULT_TEMPLATE)

    def _rows(self):
        return [self._rows_lay.itemAt(i).widget() for i in range(self._rows_lay.count())]

    def _refresh_empty(self):
        self._empty_hint.setVisible(len(self._rows()) == 0)

    def _add_row(self, spec):
        row = _TokenRow(spec)
        row.removeRequested.connect(self._remove)
        row.moveRequested.connect(self._move)
        row.changed.connect(self.changed)
        self._rows_lay.addWidget(row)
        self._refresh_empty()
        return row

    def _remove(self, row):
        self._rows_lay.removeWidget(row); row.deleteLater()
        self._refresh_empty(); self.changed.emit()

    def _move(self, row, direction):
        i = self._rows_lay.indexOf(row); j = i + direction
        if 0 <= j < self._rows_lay.count():
            self._rows_lay.removeWidget(row); self._rows_lay.insertWidget(j, row); self.changed.emit()

    def _restore_default(self):
        self.set_template(naming.DEFAULT_TEMPLATE); self.changed.emit()

    def set_template(self, specs):
        while self._rows_lay.count():
            w = self._rows_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for spec in specs:
            self._add_row(spec)
        self._refresh_empty()

    def template(self):
        return [row.spec() for row in self._rows()]


class RenameBar(QWidget):
    """Panel „Nazwy z faktów" (F3: strona `_PanelStack`, otwierana z paska zbioru „Uporządkuj nazwy
    plików…"; BLIŹNIAK strukturalny `MacroBar`). Trzy strefy: (1) polityka wsadu — Źródło/Offset/
    Fallback + żywa etykieta celu; (2) panel inspekcji daty (G1, G4 — pełne timestampy + Δ + align do
    drugiego źródła); (3) akcje. Emituje `preview(policy)`/`stage(policy)`/`cleared()`/`sourceChanged()`.
    `policy` = {source, offset_hours, fallback} — jeden silnik `naming.run_rename`. Panel daty KARMIONY
    z zewnątrz (`set_echo`) — FramesView zna zaznaczenie i wie, czy panel jest otwarty."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()
    sourceChanged = Signal()     # zmiana źródła → przelicz etykietę/znak align (R2 #2)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._median = None       # ostatnia mediana Δ wsadu (do przycisku „Wyrównaj")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)

        # (1) polityka wsadu
        pol = QHBoxLayout()
        pol.addWidget(QLabel(i18n.t("grid.rename.source")))
        self.src = QComboBox()
        self.src.addItem("DATE-OBS", "date_obs")          # D2: default DATE-OBS (kw FITS — bez tłumaczenia)
        self.src.addItem(i18n.t("grid.rename.src_filename"), "filename")
        self.src.currentIndexChanged.connect(lambda *_: self.sourceChanged.emit())
        pol.addWidget(self.src)
        pol.addWidget(QLabel(i18n.t("grid.rename.offset")))
        self.offset = QSpinBox(); self.offset.setRange(-24, 24); self.offset.setValue(0)
        self.offset.setSuffix(" h")                       # BEZ założenia strefy (§2): 0 default
        pol.addWidget(self.offset)
        self.fallback = QCheckBox(i18n.t("grid.rename.fallback")); self.fallback.setChecked(True)  # D1
        pol.addWidget(self.fallback)
        pol.addStretch(1)
        self.target_lbl = QLabel("")                      # żywa etykieta celu (R1 #18)
        self.target_lbl.setProperty("role", "secondary")  # tekst drugorzędny z motywu (F6 §7)
        pol.addWidget(self.target_lbl)
        b.addLayout(pol)

        # (2) panel inspekcji daty (G1 — zarezerwowana powierzchnia; G4 — pełne timestampy)
        grid = QGridLayout(); grid.setContentsMargins(0, 2, 0, 2)
        self.lbl_primary = QLabel("—"); self.lbl_secondary = QLabel("—")
        self.lbl_delta = QLabel(""); self.lbl_flag = QLabel("")
        self.lbl_flag.setProperty("role", "error")       # kolor z motywu (P-C), nie sztywne #b00
        self.btn_align = QPushButton(i18n.t("grid.rename.align")); self.btn_align.setEnabled(False)
        self.btn_align.clicked.connect(self._align)
        grid.addWidget(self.lbl_primary, 0, 0); grid.addWidget(self.lbl_secondary, 0, 1)
        grid.addWidget(self.lbl_delta, 1, 0); grid.addWidget(self.lbl_flag, 1, 1)
        b.addLayout(grid)
        align_row = QHBoxLayout()                        # „Wyrównaj" = szerokość treści (pomocnik NIE
        align_row.addWidget(self.btn_align); align_row.addStretch(1)   # dominuje akcji głównych — wiz #5)
        b.addLayout(align_row)

        # (3) edytor wzoru nazwy (v2 §5 — folder/orig/per-token; DANE dla `run_rename`)
        b.addSpacing(10)                                 # oddech od panelu daty (wiz #4)
        self.template_editor = _TemplateEditor()
        b.addWidget(self.template_editor)

        # (4) akcje (bliźniaczo do makra)
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    # ---- stan / API ----
    def source(self):
        return self.src.currentData()

    def policy(self):
        return {"source": self.src.currentData(), "offset_hours": self.offset.value(),
                "fallback": self.fallback.isChecked(), "template": self.template_editor.template()}

    def set_actions_enabled(self, on):
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_target_label(self, text):
        self.target_lbl.setText(text)

    def set_echo(self, primary, secondary, delta, flag, *, flag_role="warn", median=None, spread=None):
        """Wypełnij panel daty (FramesView liczy z zaznaczenia/widocznych). `median` (Δ w godzinach, float
        albo None) uzbraja „Wyrównaj": znak ZALEŻNY od źródła (R2 #2), wartość przez half-away (R2 #5),
        surowa mediana + rozrzut w tooltipie (R1 #16).

        `flag_role` NAZYWA WAGĘ komunikatu (wizytacja P-C #7): „Δ niepełnogodzinna!" to ostrzeżenie
        (`warn`), „brak źródła czasu" to stan informacyjny (`secondary`). Do P-C oba nosiły tę samą
        czerwień co „Etap padł" Dostawy — akcent semantyczny, który krzyczy o wszystkim, nie mówi
        o niczym. Czerwień zostaje wyłącznie dla awarii."""
        self.lbl_primary.setText(primary); self.lbl_secondary.setText(secondary)
        self.lbl_delta.setText(delta); self.lbl_flag.setText(flag)
        _set_role(self.lbl_flag, flag_role)
        self._median = median
        if median is None:
            self.btn_align.setEnabled(False)
            self.btn_align.setText(i18n.t("grid.rename.align"))
            self.btn_align.setToolTip("")
            return
        self.btn_align.setEnabled(True)
        off = self._offset_from_median()
        other = i18n.t("grid.rename.other_fname") if self.source() == "date_obs" else "DATE-OBS"
        self.btn_align.setText(i18n.t("grid.rename.align_to", other=other, off=f"{off:+d}"))
        tip = i18n.t("grid.rename.align_tip", median=repr(median))
        if spread is not None:
            tip += i18n.t("grid.rename.align_tip_spread", spread=f"{spread:g}")
        self.btn_align.setToolTip(tip)

    def _offset_from_median(self):
        """Offset całkowity z mediany Δ (=hdr−nazwa). source=date_obs → −Δ (przesuń nagłówek do nazwy);
        source=filename → +Δ (przesuń nazwę do nagłówka). `resolve_dt` = base+offset (R2 #2)."""
        signed = -self._median if self.source() == "date_obs" else self._median
        return _half_away(signed)

    def _align(self):
        if self._median is not None:
            self.offset.setValue(self._offset_from_median())

    def _emit_preview(self):
        self.preview.emit(self.policy())

    def _emit_stage(self):
        self.stage.emit(self.policy())


class ElidedLabel(QLabel):
    """QLabel z elizją w prawo: pełny tekst przez `set_full_text` (ląduje też w tooltipie), render
    przycinany do bieżącej szerokości — długi opis kryteriów nie rozpycha okna (F3, §4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def set_full_text(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._update_elide()

    def full_text(self):
        """Tekst PRZED elizją — wołający pyta o treść, nie o to, co się akurat zmieściło
        (`text()` zwraca wersję przyciętą i „czy jest co pokazać" odpowiedziałby na niej fałszem
        przy wąskim panelu)."""
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 4)))


# Sufit listy panelu rodowodu: wejść stosu bywa 190, więc lista MUSI mieć próg, za którym oddaje
# pion gridowi. Oś kalibracji ma zawsze dwa wiersze i sufit sobie zaniża do treści (`set_calibration`),
# dlatego droga stosu przywraca tę wartość WPROST — panel przełącza się w obie strony.
_LINEAGE_LIST_MAX_H = 160


class LineageBar(QWidget):
    """Panel „Rodowód" (I-2d, P-I): CO WESZŁO W TEN OBRAZ — strona `_PanelStack` otwierana z paska
    zbioru, gdy zaznaczono DOKŁADNIE JEDEN gotowy stos (`kind='master_light'`).

    Panel jest jedynym miejscem, w którym widać RÓŻNICĘ MIĘDZY FAKTEM A KANDYDATEM. Wejście
    z `history` plik zeznał o sobie sam; wejście z `window` zostało WYLICZONE z okna czasu i czeka
    na potwierdzenie. Bez tej różnicy w oczach użytkownika rodowód wyglądałby jak wiedza pewna,
    a w 75 na 81 przypadków nią nie jest.

    Głupi widżet (NARROW, wzorzec `MacroBar`/`SelectionBar`): sam nie czyta i nie pisze do bazy —
    dostaje gotowy materiał przez `set_lineage` i emituje `judged(frame_ids, excluded)`; zapis
    (jedna klinga) robi `FramesView`.

    STOS BEZ WEJŚĆ TEŻ MA CO POKAZAĆ — i to jest sedno, nie przypadek brzegowy: 47 ze 128 stosów
    archiwum nie dostało rodowodu, a powód („okno opisuje jedną klatkę", „klatki są z innego
    teleskopu") mówi użytkownikowi, KTÓRĄ naprawę wykonać. Puste okno bez zdania byłoby gorsze
    niż brak panelu."""

    judged = Signal(list, bool)        # (frame_ids, excluded) — werdykt ręki, zapis u gospodarza
    offset_asked = Signal(int)         # (minuty) — wskazane odniesienie czasu, zapis u gospodarza

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)               # domyślny odstęp rozpychał panel o 55 px pustki (wiz #6)
        self.head = QLabel("")
        _f = self.head.font(); _f.setBold(True); self.head.setFont(_f)
        self.head.setWordWrap(True)     # powód bywa zdaniem, a nie liczbą — nie elidujemy go
        # DWIE ETYKIETY, BO TO DWIE STAWKI: ostrzeżenie żąda decyzji, informacja tylko tłumaczy.
        # Wspólna szara nota malowała „⚠ karta do naprawy" tym samym kolorem co „to druga wersja
        # obrazu" i użytkownik nie miał po czym ich odróżnić (wiz #4).
        self.warn = ElidedLabel()
        self.warn.setProperty("role", "warn")
        self.note = ElidedLabel()
        self.note.setProperty("role", "secondary")
        lay.addWidget(self.head)
        lay.addWidget(self.warn)
        lay.addWidget(self.note)
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.setTextElideMode(Qt.ElideLeft)       # ścieżka: koniec (nazwa pliku) niesie sens
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items.setMaximumHeight(_LINEAGE_LIST_MAX_H)   # panel nie zjada gridu (wiz F3 #1)
        self.items.itemSelectionChanged.connect(self._sync_buttons)
        lay.addWidget(self.items)
        # Wiersz akcji w WIDŻECIE, nie w gołym layoucie — pusta lista chowa go w całości (wiz #6),
        # a layoutu nie da się ukryć jednym wywołaniem.
        self.action_row = QWidget()
        row = QHBoxLayout(self.action_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.btn_confirm = QPushButton(i18n.t("grid.lin.confirm"))
        self.btn_confirm.setToolTip(i18n.t("grid.lin.confirm_tip"))
        self.btn_confirm.clicked.connect(lambda: self._emit(False))
        self.btn_reject = QPushButton(i18n.t("grid.lin.reject"))
        self.btn_reject.setToolTip(i18n.t("grid.lin.reject_tip"))
        self.btn_reject.clicked.connect(lambda: self._emit(True))
        row.addWidget(self.btn_confirm)
        row.addWidget(self.btn_reject)
        row.addStretch(1)
        lay.addWidget(self.action_row)
        # GEST ODNIESIENIA STOI POZA `action_row` I TO JEST ROZSTRZYGNIĘCIE, NIE UKŁAD: tamten
        # wiersz chowa się razem z listą (`_sync_visible`), a ten przycisk potrzebny jest DOKŁADNIE
        # wtedy, gdy listy nie ma — stos z materiałem RAW i nieznanym zegarem ma zero wejść. Wspólny
        # rodzic znaczyłby, że jedyna recepta na `offset_unknown` znika razem z problemem.
        self.btn_offset = QPushButton(i18n.t("grid.lin.offset"))
        self.btn_offset.clicked.connect(self._ask_offset)
        lay.addWidget(self.btn_offset)
        lay.addStretch(1)               # pustkę zbiera dół panelu, nie odstępy między wierszami
        self._busy = False
        self._offset_hint = None        # propozycja z rdzenia (`stacks.propose_offset_minutes`)
        self.set_lineage(None, [])

    def set_lineage(self, head, inputs, *, hint=None):
        """Wypełnij panel. `head` = wiersz `queries.stack_lineage_head` (albo `None`), `inputs` =
        wiersze `queries.stack_lineage_inputs`, `hint` = gotowe zdanie, gdy nie ma czego pokazać
        (złe zaznaczenie / rodowód nieliczony). Zero SQL i zero decyzji — sama prezentacja."""
        self.items.clear()
        self.items.setMaximumHeight(_LINEAGE_LIST_MAX_H)   # oś kalibracji zaniża sufit do treści
        self._head = head
        if head is None:
            # Brak materiału ZAWSZE mówi zdaniem — także w stanie startowym, zanim ktokolwiek
            # cokolwiek zaznaczył. Pusty panel bez wyjaśnienia czyta się jak awaria.
            self.head.setText(hint if hint is not None else i18n.t("grid.lin.hint.none"))
            self.warn.set_full_text("")
            self.note.set_full_text("")
            self._sync_visible(False)
            return
        powod = _lineage_reason_text(head)
        ostrz, info = _lineage_flags(head)
        # LISTA POWSTAJE ZAWSZE, ZANIM ROZSTRZYGNIEMY O NAGŁÓWKU. Integracja z POWODEM może mieć
        # wiersze — `_reconcile` omija werdykty ręki, więc odrzucone kandydatury zostają, mając
        # `head["inputs"] == 0`. Gałąź powodu, która listy nie wypełniała, zabierała wtedy JEDYNĄ
        # drogę cofnięcia własnej decyzji (`stack_lineage_inputs` oddaje je właśnie po to).
        for r in inputs:
            it = QListWidgetItem(_lineage_item_text(r))
            it.setData(Qt.UserRole, r["input_frame_id"])
            if r["excluded"]:
                it.setForeground(_COLORS["secondary_text"])
            self.items.addItem(it)
        if not head["inputs"] and powod:
            # NIE MA CZEGO POLICZYĆ ⇒ NIE LICZYMY. „Weszło 0 klatek · 0.0 h" o obrazie, który
            # przecież Z CZEGOŚ powstał, jest twierdzeniem, którego model nie ma — a to stan
            # NAJCZĘSTSZY, nie brzegowy: 47 ze 128 stosów archiwum. Głos oddaje powód, bo to on
            # mówi, KTÓRĄ naprawę wykonać; zero i „0.0 h" znikają.
            #
            # Warunek stoi na POWODZIE, nie na samym zerze: gdy człowiek odrzuci wszystkie
            # kandydatury, `inputs` też jest zerem — ale wtedy „weszło 0 klatek" jest PRAWDĄ
            # i jego własną decyzją, więc nagłówek ma ją pokazać.
            self.head.setText(powod)
            self.note.set_full_text(info)
        else:
            godziny = (head["secs"] or 0) / 3600.0
            self.head.setText(i18n.t_plural("grid.lin.head", head["inputs"],
                                            hours=f"{godziny:.1f}"))
            self.note.set_full_text(" · ".join(x for x in (powod, info) if x))
        self.warn.set_full_text(ostrz)          # `_lineage_flags` samo milczy przy pustej liście
        # Widoczność z LISTY, nie z licznika: stos z powodem, ale z odrzuconymi wierszami, ma je
        # pokazać (i dać się cofnąć), a stos bez ani jednego wiersza nie ma zajmować pionu na listę.
        self._sync_visible(bool(inputs))

    def set_calibration(self, relations):
        """DRUGA ODPOWIEDŹ TEGO SAMEGO PANELU (C3, Issue #6): czym skalibrowano zaznaczoną klatkę
        nieba. `relations` = wynik `lineage.explain_light` (po jednym wierszu na `dark`/`flat`).

        Panel jest kind-aware, a nie zdublowany, bo pytanie użytkownika jest JEDNO — „skąd ta
        klatka ma swój kształt" — i tylko odpowiedź zależy od rodzaju: gotowy obraz mówi, co
        w niego weszło, klatka nieba mówi, czym ją skalibrowano. Dwa osobne panele kazałyby
        zgadywać, który otworzyć, zanim wiadomo, co się zaznaczyło.

        WERDYKTU RĘKI TU NIE MA i to nie jest przeoczenie: `calibration` nie zna kolumny
        `excluded` — dobór mastera jest funkcją przepisu i czasu, więc ręka zmienia go naprawiając
        FAKT (nastawę, kartę), nie przegłosowując wynik. Wiersz akcji chowa się w całości."""
        self.items.clear()
        self._head = None
        powiazane = [r for r in relations if r["master_frame_id"] is not None]
        for r in relations:
            it = QListWidgetItem(_calibration_item_text(r))
            it.setData(Qt.UserRole, r["master_frame_id"])
            if r["master_frame_id"] is None:
                it.setForeground(_COLORS["secondary_text"])
            self.items.addItem(it)
        self.head.setText(i18n.t("grid.lin.cal.head", n=len(powiazane), total=len(relations)))
        # LISTA DO TREŚCI, nie do sufitu. Wejść stosu bywa 190, więc tam sufit 160 px chroni grid;
        # tutaj wierszy jest kilka (klasy przepisu), a ten sam sufit zostawiał ~100 px pustki —
        # dokładnie ten zarzut, który zdjął pustkę z panelu stosu (wiz #6), tylko z drugiej strony.
        # Pusta lista NIE zaniża sufitu do paska kilku pikseli: zero relacji jest dziś niemożliwe
        # (stała `_RELATIONS`), ale sufit liczony z nieistniejącego wiersza byłby pułapką czekającą.
        if self.items.count():
            wiersz = self.items.sizeHintForRow(0)
            self.items.setMaximumHeight(wiersz * self.items.count() + 2 * self.items.frameWidth())
        # NIELICZONE ≠ LUKA — pierwsze naprawia jedno kliknięcie w Dostawie, drugie wymaga klatek,
        # których w archiwum nie ma. Wspólne „brak" kazałoby szukać winy tam, gdzie jej nie ma.
        czeka = [r for r in relations if r["pending"]]
        self.warn.set_full_text(i18n.t("grid.lin.cal.pending") if czeka else "")
        self.note.set_full_text("")
        self.items.setVisible(True)
        self.action_row.setVisible(False)          # w tej osi nie ma czego potwierdzać ani odrzucać
        self.warn.setVisible(bool(self.warn.full_text()))
        self.note.setVisible(False)
        self._sync_buttons()
        # Odniesienie czasu jest faktem O OBRAZIE, a ta gałąź opisuje KLATKĘ NIEBA — przycisk
        # gaśnie razem z całym trybem stosu. `_head` jest tu `None`, więc gest i tak nie miałby
        # celu zapisu; jawne wołanie trzyma to w JEDNYM miejscu zamiast liczyć na kolejność pól.
        self._sync_offset_visible()

    def integration_id(self):
        """Integracja, której dotyczy panel (albo `None`) — gospodarz pyta o cel zapisu TU, zamiast
        sięgać do pola widżetu (NARROW: panel wystawia fakt, nie swoje wnętrze).

        Tryb kalibracji zeruje `_head`, więc werdykt ręki nie ma tam celu zapisu — i dobrze:
        `judged` nie ma prawa trafić w tabelę, która werdyktów nie zna."""
        return None if self._head is None else self._head["integration_id"]

    def set_busy(self, busy):
        """Etap pipeline'u pisze do bazy w tle — werdykt ręki musi wtedy zamilknąć. To DRUGA
        powierzchnia zapisu tego samego stołu (`integration_input`), więc obowiązuje ją ta sama
        bramka co makro/rename/staging; bez niej klik w „Odrzuć" trafiał w wiersz, który worker
        właśnie przeliczał."""
        self._busy = busy
        self._sync_buttons()
        self._sync_offset_visible()      # ten sam stół, ta sama bramka — gest odniesienia też milknie

    def _sync_visible(self, ma_liste):
        """Panel bez listy nie ma prawa zajmować miejsca na listę: pusty `QListWidget` (130 px)
        i dwa wygaszone przyciski mówiły „tu coś będzie" tam, gdzie nic nie będzie (wiz #6).
        Chowamy oba i oddajemy pion gridowi; puste etykiety znikają razem z ich treścią."""
        self.items.setVisible(ma_liste)
        self.action_row.setVisible(ma_liste)
        self.warn.setVisible(bool(self.warn.full_text()))
        self.note.setVisible(bool(self.note.full_text()))
        self._sync_buttons()
        self._sync_offset_visible()

    def _sync_buttons(self):
        """Uczciwy disabled: werdykt dotyczy ZAZNACZONYCH wierszy listy, więc bez zaznaczenia nie ma
        na czym go wydać (wzorzec `set_have_frames` — gasimy realną akcję, nie panel)."""
        ile = len(self.items.selectedItems())
        for b in (self.btn_confirm, self.btn_reject):
            b.setEnabled(ile > 0 and not self._busy)

    def selected_frame_ids(self):
        return [it.data(Qt.UserRole) for it in self.items.selectedItems()]

    def select_frame_ids(self, frame_ids):
        """Przywróć zaznaczenie po przebudowie listy — po KLATKACH, nie po indeksach. Klatka, która
        z listy zniknęła, po prostu nie wraca (cicho): to stan, nie błąd."""
        chciane = set(frame_ids)
        for i in range(self.items.count()):
            it = self.items.item(i)
            it.setSelected(it.data(Qt.UserRole) in chciane)

    def _emit(self, excluded):
        ids = self.selected_frame_ids()
        if ids:
            self.judged.emit(ids, excluded)

    def set_offset_hint(self, minutes):
        """Propozycja odniesienia z rdzenia (`stacks.propose_offset_minutes`) — `None` = brak.
        Panel jej NIE liczy (głupi widżet): dostaje ją gotową i tylko pokazuje jako wartość
        wstępną okna. Zapis i tak wymaga potwierdzenia — propozycja skraca gest, nie zastępuje go."""
        self._offset_hint = minutes

    def _ask_offset(self):
        """Zapytaj o odniesienie czasu tego obrazu i wyemituj `offset_asked` (zapis u gospodarza).

        JEDNOSTKĄ OKNA SĄ GODZINY, choć baza trzyma MINUTY — bo tak brzmi pytanie do człowieka
        („o ile zegar aparatu wyprzedzał UTC"), a wszystkie zmierzone offsety archiwum są pełnymi
        godzinami. Minuty w kolumnie zostają, żeby strefy półgodzinne (Indie, część Australii)
        nie wymagały migracji, gdy Zdzin tam pojedzie — pole jest szersze niż dzisiejsze okno
        i to jest świadome."""
        biezacy = None if self._head is None else self._head["utc_offset_min"]
        wstepna = biezacy if biezacy is not None else (self._offset_hint or 0)
        godziny, ok = QInputDialog.getDouble(
            self, i18n.t("grid.lin.offset_title"), i18n.t("grid.lin.offset_prompt"),
            wstepna / 60.0, -14.0, 14.0, 1)
        if ok:
            self.offset_asked.emit(round(godziny * 60))

    def _sync_offset_visible(self):
        """Przycisk odniesienia wchodzi TYLKO tam, gdzie ma co zmienić — a to znaczy: gdy powód
        brzmi `offset_unknown` ALBO odniesienie już wskazano (droga POWROTNA, żeby pomyłka ręki
        nie była wieczna — ta sama lekcja, co przy zestawie w R1).

        Nie pokazujemy go przy każdym stosie, bo dla 121 masterów FITS/ASI odniesienie nie jest
        pytaniem: ich czas i tak jest w jednym zegarze, a przycisk sugerowałby problem tam, gdzie
        go nie ma."""
        head = self._head
        widoczny = head is not None and (head["unresolved_reason"] == REASON_OFFSET_TOKEN
                                         or head["utc_offset_min"] is not None)
        self.btn_offset.setVisible(widoczny)
        self.btn_offset.setEnabled(widoczny and not self._busy)
        if widoczny:
            biezacy = head["utc_offset_min"]
            self.btn_offset.setText(
                i18n.t("grid.lin.offset") if biezacy is None
                else i18n.t("grid.lin.offset_set", hours=f"{biezacy / 60.0:+.1f}"))


def _lineage_item_text(r):
    """Jeden wiersz listy wejść: czas · ekspozycja · ŹRÓDŁO PEWNOŚCI · ścieżka. Źródło stoi PRZED
    ścieżką, bo ścieżka jest elidowana od lewej i to ona ustępuje miejsca, nigdy werdykt."""
    czas = (r["date_obs"] or "")[:19].replace("T", " ")
    exp = f"{r['exptime']:.0f}s" if r["exptime"] is not None else "—"
    zrodlo = i18n.t(f"grid.lin.src.{r['asserted_by']}")
    if r["excluded"]:
        zrodlo = i18n.t("grid.lin.src.excluded")
    return f"{czas} · {exp} · [{zrodlo}] · {r['path'] or ''}"


def _znany(klucz, zapasowo):
    """Etykieta z katalogu ALBO surowa wartość, gdy katalog jej nie zna. `i18n.t` na nieznanym kluczu
    zwraca sam klucz („grid.lin.cal.rel.bias" na ekranie), a baza dopuszcza wartości spoza stałych
    kodu (`0009`: `bias`, wpisy ręki/WBPP). Lepiej pokazać surowe `bias` niż ścieżkę klucza."""
    return i18n.t(klucz) if klucz in i18n.CATALOG else zapasowo


def _calibration_item_text(r):
    """Jeden wiersz osi kalibracji: KLASA · [źródło pewności] · ścieżka mastera. Klasa stoi pierwsza,
    bo to ona jest pytaniem („czym odjęto ciemność, czym wyrównano pole"); ścieżka jest elidowana
    od lewej, więc ustępuje ona, nigdy werdykt — dokładnie jak w wierszu wejść stosu.

    Klasa spoza stałej (`bias`, wpis ręki) dostaje SWOJĄ nazwę zamiast surowego klucza — katalog
    zna dwie, a baza dopuszcza więcej (`0009`)."""
    klasa = _znany(f"grid.lin.cal.rel.{r['relation']}", r["relation"])
    if r["master_frame_id"] is not None:
        zrodlo = _znany(f"grid.lin.cal.src.{r['asserted_by']}", r["asserted_by"] or "")
        # ZNIKNIĘTY MASTER MUSI SIĘ PRZYZNAĆ. `calibrators_for` bierze ścieżkę tylko z kopii
        # OBECNEJ, więc po zniknięciu pliku wiersz kończył się kropką i pustką — a nagłówek dalej
        # liczył go do „skalibrowana". Powiązanie jest prawdziwe (tożsamość to `sha1_data`),
        # nieprawdziwa jest dostępność — i to ona ma być na ekranie.
        gdzie = r["master_path"] or i18n.t("grid.lin.cal.vanished", id=r["master_frame_id"])
        # DYSTANS OBOK ŹRÓDŁA — liczba, nie werdykt. Progu „za daleko" świadomie nie stawiamy:
        # ile dni to za dużo, zależy od klasy i od sprzętu, a zgadnięty próg malowałby na czerwono
        # dobór, który bywa jedynym możliwym. Użytkownik dostaje miarę i ocenia sam.
        if r.get("days_apart") is not None:
            zrodlo = f"{zrodlo} · {i18n.t('grid.lin.cal.delta', n=r['days_apart'])}"
        return f"{klasa} · [{zrodlo}] · {gdzie}"
    # BRAK MA POWÓD ALBO GO NIE MA — i to są dwa różne zdania. Token `gap` niesie powód archiwum;
    # `pending` znaczy, że master JEST, tylko nikt jeszcze nie policzył powiązania.
    if r["pending"]:
        return f"{klasa} · {i18n.t('grid.lin.cal.state.pending')}"
    powod = i18n.t(f"grid.lin.cal.gap.{r['gap']}")
    return f"{klasa} · {powod}"


# Tokeny powodów, o których panel wie WIĘCEJ niż samą prozę — LUSTRO stałych rdzenia
# (`stacks.REASON_NO_OBJECT`, `stacks.REASON_OFFSET_UNKNOWN`), trzymane tu jako literały, bo
# warstwa widżetów nie importuje rdzenia poza `queries` (test izolacji §4). Równość obu zapisów
# pinuje bramka w `tests/test_gui_grid.py`, żeby rozjazd nie przeszedł cicho.
REASON_NO_OBJECT_TOKEN = "no_object"
REASON_OFFSET_TOKEN = "offset_unknown"


def _lineage_reason_text(head):
    """Prozę powodu składa POWIERZCHNIA, rdzeń niesie token (`unresolved_reason`) — ta sama granica
    co przy `wbpp-feed`/`ProjectionAbort`; inaczej polski komunikat rdzenia wyciekłby do wersji EN."""
    powod = head["unresolved_reason"]
    if not powod:
        return ""
    if _lineage_stale(head):
        return i18n.t("grid.lin.reason.stale")
    return i18n.t(f"grid.lin.reason.{powod}")


def _lineage_stale(head):
    """Czy zapisany powód ZWIETRZAŁ wobec bieżącego stanu (firsthand 0808).

    `unresolved_reason` jest zapisem z chwili OSTATNIEGO przebiegu rodowodu, a fakty, na których
    stoi, zmienia GEST CZŁOWIEKA między przebiegami. Panel twierdził więc „obraz nie ma
    rozpoznanego obiektu" o wierszu, który w kolumnie obok pokazywał `IC443` — sprzeczność w jednym
    oknie, której user nie ma prawa rozstrzygać domysłem.

    Wykrywamy ją wprost i WĄSKO: pytamy tylko o te powody, których przesłankę widać w tym samym
    read-modelu. Powód ogólny („nie wiem, czy to jeszcze aktualne") wymagałby porównania czasu
    przebiegu ze znacznikiem zmiany faktów — a takiego znacznika dziś nie ma i dorabianie go pod
    komunikat byłoby budową mechanizmu pod zdanie.

    NIE NAPRAWIAMY TU RODOWODU i to jest granica, nie brak: dobór wejść jedzie po CAŁYM archiwum
    stosów, więc jego przeliczenie należy do etapu w Dostawie. Panel ma powiedzieć PRAWDĘ o tym,
    co wie — a prawdą jest „ten zapis jest starszy niż twoje zmiany"."""
    powod = head["unresolved_reason"]
    if powod == REASON_NO_OBJECT_TOKEN:
        return head["object_now"] is not None
    if powod == REASON_OFFSET_TOKEN:
        return head["utc_offset_min"] is not None
    return False


def _lineage_flags(head):
    """Flagi panelu rozdzielone WEDŁUG STAWKI → `(ostrzeżenia, informacje)`.

    Ostrzeżenie żąda decyzji („ten sub policzono dwa razy", „karta teleskopu do naprawy"),
    informacja tylko tłumaczy obraz („to druga wersja", „plik deklaruje N"). Wspólny szary ciąg
    zrównywał jedno z drugim — powierzchnia maluje je teraz różnymi rolami (wiz #4).

    OSTRZEŻENIE MILCZY, GDY LISTA JEST PUSTA. „⚠ część TYCH klatek wchodzi też w inny obraz" przy
    zerze wejść mówi o czymś, czego na ekranie nie ma — a to stan 42 z 47 stosów bez rodowodu.
    Gaśnie WYŁĄCZNIE ostrzeżenie: informacje („odrzuconych: N", „plik deklaruje N") są przy zerze
    JEDYNYM wyjaśnieniem tego zera, więc wspólny guard zabierał je dokładnie tam, gdzie są potrzebne
    — przy stosie, z którego człowiek własnoręcznie odrzucił wszystkie kandydatury.

    Współdzielenie bierzemy z `shared` (realne: ten sam wiersz wejścia w integracji o INNYM
    odcisku), nie z `ambiguous` (nakładanie się okien planu). Poprzedni `elif` gasił ostrzeżenie
    obecnością bliźniaka — zmierzone: 17 ze 128 integracji ma JEDNO I DRUGIE, więc uspokojenie
    zjadało wtedy sygnał, który miał znaczenie. Rozdzielone predykaty nie muszą się wykluczać."""
    ostrz, info = [], []
    if head["inputs"]:
        if head["shared"]:
            ostrz.append(i18n.t("grid.lin.flag.ambiguous"))
        if head["telescope_mismatch"]:
            ostrz.append(i18n.t("grid.lin.flag.telescope"))
    if head["twins"]:
        # NIE ostrzeżenie: ten sam zbiór wejść pod inną nazwą pliku to WARIANT tego samego obrazu
        # (`_ast`, `_drizzle_1x`, `_integration`), a nie kolizja. Zmierzone: 51 z 62 oflagowanych.
        info.append(i18n.t_plural("grid.lin.flag.twins", head["twins"]))
    if head["declared_rows"] is not None:
        info.append(i18n.t("grid.lin.flag.declared", n=head["declared_rows"]))
    if head["excluded"]:
        info.append(i18n.t("grid.lin.flag.excluded", n=head["excluded"]))
    return " · ".join(ostrz), " · ".join(info)


def _object_gate_reason(stan):
    """POWÓD wygaszenia kontrolki „Obiekt ▾" jako klucz i18n; `None` = jest co robić (R-S2b-8).

    Wygaszony przycisk tłumaczy się SAM — to doktryna repo, złamana akurat w tym miejscu: przy
    zaznaczeniu samych klatek z nagłówka (w realnym archiwum ~95% lightów) kontrolka była szara,
    menu nieotwieralne i NIC nie mówiło dlaczego, choć trzej gatujący sąsiedzi (`btn_proj`,
    `btn_clear`, `btn_lineage`) tooltipy mają.

    Powód liczy się z READ-MODELU, nie z domysłu, i schodzi od najwęższego: brak zaznaczenia →
    brak klatek nieba → sam gotowy obraz (droga naprawy jest inna: karta `OBJECT` w pliku) →
    nazwa z nagłówka (poprawia się w PLIKU, nie w bazie). Kolejność ma znaczenie: zaznaczenie
    mieszane trafia w pierwszy powód, który je opisuje prawdziwie."""
    if stan is None or not stan["n"]:
        return "grid.sel.object_tip_empty"
    if not stan["lights"]:
        return "grid.sel.object_tip_no_lights"
    if stan["lights"] == stan["stacks"]:
        return "grid.sel.object_tip_stacks"
    return "grid.sel.object_tip_header"


class SelectionBar(QFrame):
    """Pasek ZBIORU (F3, PLAN_ux_redesign §4): licznik + kryteria słowami + akcje na zbiorze
    [Wydaj na stół…][Popraw nagłówki…][Uporządkuj nazwy plików…][★ Zapisz widok]. Przyciski paneli
    CHECKABLE — który panel otwarty widać bez klikania. Głupi widżet: FramesView łączy kliki i karmi
    etykiety (NARROW). Przyciski-panele ZAWSZE aktywne (gating checkable = pułapka
    disabled-but-checked-open, F3R#2); pusty zbiór gasi tylko „Wydaj na stół…"."""

    _PROJ_TIP = "grid.sel.proj_tip"   # KLUCZ (rozwiązywany i18n.t w use-site — nie zamrożony PL)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.count_label = QLabel("")
        f = QFont(); f.setBold(True); self.count_label.setFont(f)
        self.criteria_label = ElidedLabel()
        self.criteria_label.setProperty("role", "secondary")   # kryteria zbioru czytelne na dark (F6 §7)
        self.btn_proj = QPushButton(i18n.t("grid.sel.project"))
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP))
        # ZŁOTA AKCJA Zbiorów (wiz F3 #3, dług zamknięty w P-C): jedna akcja na miejsce niesie wagę
        # wizualną — wzorzec „Przyjmij nowe" (`pipeline._build_ui`). Waga = BOLD, nie kolor: złoto
        # motywu ma w jasnej skórce 2,7:1 i jako tekst nie dochodzi do progu czytelności (wiz T5 N5).
        # Bez podnoszenia wysokości — pasek zbioru trzyma pięć przycisków w jednym rzędzie.
        _f = self.btn_proj.font(); _f.setBold(True); self.btn_proj.setFont(_f)
        # „× Wyczyść zbiór" (wiz F4 #3): jednoklikowe zdjęcie facetów + filtra — bez niego jedyną
        # drogą było od-cyklowanie każdej wartości (preset „Przegląd" = no-op, gdy już wybrany).
        self.btn_clear = QPushButton(i18n.t("grid.sel.clear_set"))
        self.btn_clear.setToolTip(i18n.t("grid.sel.clear_tip"))
        self.btn_macro = QPushButton(i18n.t("grid.sel.fix_headers")); self.btn_macro.setCheckable(True)
        self.btn_rename = QPushButton(i18n.t("grid.sel.tidy_names")); self.btn_rename.setCheckable(True)
        # Panel rodowodu (I-2d) — trzeci panel stacku. ZAWSZE aktywny, jak pozostałe przyciski-panele
        # (F3R#2: gating checkable = pułapka disabled-but-checked-open); niewłaściwe zaznaczenie
        # tłumaczy sam panel zdaniem, a nie wygaszony przycisk, który nie mówi DLACZEGO.
        self.btn_lineage = QPushButton(i18n.t("grid.sel.lineage")); self.btn_lineage.setCheckable(True)
        self.btn_lineage.setToolTip(i18n.t("grid.sel.lineage_tip"))
        # OŚ OBIEKTU NA ZAZNACZENIU (S2b, D-OW-6) — JEDNA kontrolka z menu, nie dwa przyciski:
        # pasek trzyma już sześć, a siódmy i ósmy przewróciłyby go do drugiego rzędu. Obie pozycje
        # są tą samą sprawą („co to za obiekt"), więc menu jest tu grupowaniem, nie chowaniem.
        self.btn_object = QToolButton()
        self.btn_object.setText(i18n.t("grid.sel.object"))
        self.btn_object.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_object)
        self.act_name = menu.addAction(i18n.t("grid.sel.object_name"))
        self.act_clear = menu.addAction(i18n.t("grid.sel.object_clear"))
        self.btn_object.setMenu(menu)
        self.btn_save = QPushButton(i18n.t("grid.sel.save_view"))
        lay.addWidget(self.count_label); lay.addSpacing(8)
        lay.addWidget(self.criteria_label, 1)
        # Złota akcja WYJĘTA z klastra pomocniczych (wizytacja P-C #6): sam bold przegrywał wzrokowo
        # z glifem ★ sąsiada, bo wszystkie pięć stało w jednym ciągu. Odstęp, nie ramka — QSS
        # `border` na QPushButton w Fusion zastępuje CAŁE malowanie ramki i spłaszcza przycisk.
        lay.addWidget(self.btn_clear)
        lay.addSpacing(12); lay.addWidget(self.btn_proj); lay.addSpacing(12)
        lay.addWidget(self.btn_macro)
        lay.addWidget(self.btn_rename); lay.addWidget(self.btn_lineage)
        lay.addWidget(self.btn_object); lay.addWidget(self.btn_save)

    def set_criteria(self, text):
        self.criteria_label.set_full_text(text)

    def set_object_actions(self, *, namable, clearable, reason=None):
        """Uczciwy disabled obu pozycji osi obiektu (S2b, §4/14c-a). Cel gestu to WYŁĄCZNIE
        zaznaczenie, więc przy pustym gaśnie wszystko — fallback „to, co widoczne" jest dla ZAPISU
        osi ZAKAZANY (800 widocznych klatek i jedno chybione kliknięcie to ta sama sekunda).
        Kontrolka zbiorcza zostaje żywa, dopóki cokolwiek da się zrobić: menu, które tłumaczy
        wygaszoną pozycję, mówi WIĘCEJ niż wygaszony przycisk bez powodu.

        `reason` (klucz i18n z `_object_gate_reason`) niesie POWÓD wygaszenia — bez niego szara
        kontrolka odbierała jedyną powierzchnię, która mogła cokolwiek wytłumaczyć (R-S2b-8).
        Przy AKTYWNEJ kontrolce tooltip mówi, ile klatek gest realnie ruszy: to ta sama liczba,
        którą pokaże okno, więc user poznaje ją PRZED kliknięciem, a nie po."""
        self.act_name.setEnabled(bool(namable))
        self.act_clear.setEnabled(bool(clearable))
        aktywna = bool(namable or clearable)
        self.btn_object.setEnabled(aktywna)
        self.btn_object.setToolTip(
            i18n.t("grid.sel.object_tip_ready", namable=namable, clearable=clearable) if aktywna
            else i18n.t(reason or "grid.sel.object_tip_empty"))

    def set_clearable(self, on):
        """Uczciwy disabled „× Wyczyść zbiór": aktywny TYLKO gdy jest co zdjąć (facety/filtr)."""
        self.btn_clear.setEnabled(on)

    def set_have_frames(self, on):
        """Uczciwy disabled TYLKO realnej akcji na zbiorze (F3R#2): pusty zbiór gasi „Wydaj na stół…"
        (guard `_open_projection` zostaje drugą linią); „★ Zapisz widok" i panele zawsze żywe."""
        self.btn_proj.setEnabled(on)
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP) if on else i18n.t("grid.sel.proj_tip_empty"))

    def set_active_panel(self, which):
        """Synchronizuj zaznaczenie przycisków-paneli ze stanem stacku (`None`/'macro'/'rename');
        blockSignals — to odbicie stanu, nie klik."""
        for btn, key in ((self.btn_macro, "macro"), (self.btn_rename, "rename"),
                         (self.btn_lineage, "lineage")):
            btn.blockSignals(True)
            btn.setChecked(which == key)
            btn.blockSignals(False)


class _PanelStack(QStackedWidget):
    """Stack paneli kling (F3): sizeHint = BIEŻĄCA strona — goły QStackedWidget bierze max ze stron,
    więc otwarte makro wisiałoby w pasie wysokości renamu [skill: pyside6-desktop-layout-gotchas].

    SAM sizeHint NIE WYSTARCZYŁ i to jest lekcja zmierzona, nie teoria (firsthand 2026-08-02).
    Nadpisane podpowiedzi czyta layout RODZICA, ale wewnętrzny `QStackedLayout` osobno wymusza na
    tym widżecie minimum równe NAJWYŻSZEJ stronie — więc stack i tak nie schodził poniżej 240 px
    (wysokość renamu), a niska strona wisiała w nim WYŚRODKOWANA. Zmierzone na realnym oknie:
    panel rodowodu zajmował 68 px treści, a odbierał tabeli 246 px — 92 px martwego pasa nad
    i 92 pod. Panel makra tracił 6 px, bo jego strona jest bliska maksimum i pasa nie widać.

    Dlatego sufit jest USTAWIANY WPROST z bieżącej strony — przy przełączeniu strony i przy każdej
    zmianie jej treści (`LayoutRequest`), bo panele rosną i maleją w biegu (ostrzeżenie w rodowodzie,
    rzędy tokenów w renamie)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ŹRÓDŁO PUSTKI: `QLayout` z domyślnym `SetDefaultConstraint` wpisuje widżetowi TWARDE
        # `minimumSize` równe maksimum ze stron — i to ono, nie podpowiedzi, trzymało stack na
        # wysokości renamu. Zdejmujemy wymuszanie i czyścimy minimum wpisane przed tą zmianą;
        # od tej pory o wysokości decydują nadpisane niżej podpowiedzi BIEŻĄCEJ strony.
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumHeight(0)
        self.currentChanged.connect(lambda _i: self._sync_ceiling())

    def event(self, e):
        # DWA KROKI SĄ KONIECZNE, każdy leczy co innego (zmierzone osobno):
        # zdjęcie wymuszenia pozwala stackowi ZEJŚĆ do wysokości bieżącej strony, a sufit sprawia,
        # że layout rodzica nie rezerwuje slotu na najwyższą stronę i nie centruje w nim niskiej.
        # Sufit liczymy przy `LayoutRequest`, bo panele rosną i maleją BEZ przełączania strony
        # (ostrzeżenie w rodowodzie, rzędy tokenów w renamie) — i dopiero po zdjęciu wymuszenia
        # podpowiedź strony jest w tym momencie już prawdziwa. Sam sufit obcinał treść o krok.
        if e.type() == QEvent.LayoutRequest:
            self._sync_ceiling()
        return super().event(e)

    def _sync_ceiling(self):
        """Sufit = wysokość BIEŻĄCEJ strony, z JEDNĄ synchroniczną przeliczką rodzica.

        Bez niej sufit był o krok w tyle i OBCINAŁ treść (zmierzone: strona żądała 68 px, stack
        stał na 56, lista traciła 12 px z 40) — `setMaximumHeight` w trakcie `LayoutRequest` trafia
        w przebieg, który rodzic już policzył. Guard równości zamyka pętlę: przeliczka rodzica
        wraca tu `LayoutRequest`-em, ale przy niezmienionym suficie nie robi nic."""
        w = self.currentWidget()
        if w is None:
            return
        h = w.sizeHint().height()
        if self.maximumHeight() != h:
            self.setMaximumHeight(h)
            rodzic = self.parentWidget()
            if rodzic is not None and rodzic.layout() is not None:
                rodzic.layout().activate()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()



class StagingDrawer(QFrame):
    """Stała szuflada dolna stagingu (doktryna §5: „N zmian oczekuje · Przejrzyj · Zatwierdź · Odrzuć").
    Postęp i wynik commitu renderują się TU (nie w łańcuchu modali). Emituje `commit()`/`reject()`."""

    commit = Signal()
    reject = Signal()
    cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.dot = QLabel("○")
        self.label = QLabel(i18n.t("grid.drawer.empty"))   # słownik F3 (§4)
        self.result = QLabel(""); self.result.setProperty("role", "secondary")   # F6 §7
        # Postęp writebacku renderuje się TU (nie w modalu): pasek + „Anuluj" wchodzą w miejsce
        # Zatwierdź/Odrzuć na czas commitu/undo (off-thread — GUI nie zamarza; rdzeń commituje per-plik).
        self.bar = QProgressBar(); self.bar.setVisible(False); self.bar.setMaximumWidth(220); self.bar.setTextVisible(False)
        self.btn_cancel = QPushButton(i18n.t("grid.action.cancel")); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(lambda: self.cancel.emit())
        self.btn_commit = QPushButton(i18n.t("grid.action.commit")); self.btn_commit.clicked.connect(lambda: self.commit.emit())
        self.btn_reject = QPushButton(i18n.t("grid.action.reject")); self.btn_reject.clicked.connect(lambda: self.reject.emit())
        # Klaster licznik+wynik po LEWEJ (dot·label·result), rozpychacz, akcje po prawej — inaczej
        # `result` ze stretch=1 rozrzucał licznik i przyciski na całą szerokość (wizytator D1).
        lay.addWidget(self.dot); lay.addWidget(self.label); lay.addSpacing(8)
        lay.addWidget(self.result); lay.addStretch(1)
        lay.addWidget(self.bar); lay.addWidget(self.btn_cancel)
        lay.addWidget(self.btn_commit); lay.addWidget(self.btn_reject)
        self.set_count(0)

    def begin_progress(self, total):
        """Wejście w tryb postępu (start commitu/undo): pasek + „Anuluj" widoczne, Zatwierdź/Odrzuć
        schowane (nie klikać w biegu). `total=0` → pasek nieokreślony do pierwszego progresu."""
        self.bar.setRange(0, total if total > 0 else 0); self.bar.setValue(0); self.bar.setVisible(True)
        self.btn_cancel.setVisible(True); self.btn_cancel.setEnabled(True)
        self.btn_commit.setVisible(False); self.btn_reject.setVisible(False)

    def update_progress(self, done, total, path):
        """Slot postępu (główny wątek): pasek done/total + nazwa bieżącego pliku w `result`."""
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        tail = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        self.result.setText(f"{done}/{total} · {tail}")

    def end_progress(self):
        """Wyjście z trybu postępu: schowaj pasek + „Anuluj". Widoczność Zatwierdź/Odrzuć/Cofnij ustawia
        wołający (set_count / set_commit_actions_visible) w post-processingu commitu."""
        self.bar.setVisible(False); self.btn_cancel.setVisible(False)
        self.btn_commit.setVisible(True); self.btn_reject.setVisible(True)

    def set_count(self, n, *, result=None, label=None):
        self._n = n
        if n > 0:
            self.dot.setText("●"); _set_role(self.dot, "warn")   # U+25CF: jest w Segoe UI, paruje z „○" (wiz F3 #2)
            # `label` rozróżnia klingę też przy n>0: „N zmian nazw oczekuje" vs domyślne „N zmian
            # oczekuje" (mikro-zmiana §0; call-sites makra bez label → domyślny tekst, R1 #8).
            self.label.setText(label or i18n.t("grid.drawer.pending", n=n))
            if result is None:
                self.result.setText("")      # nowy staging: skasuj STALE wynik commitu/odrzucenia (wiz #7)
        else:
            self.dot.setText("○"); _set_role(self.dot, "secondary")
            # `label` nadpisuje domyślny tekst pustego stanu: po commicie „Zatwierdzono…" zamiast
            # pustostanu poczekalni (sprzeczność z wynikiem obok — wizytator D2).
            self.label.setText(label or i18n.t("grid.drawer.empty"))
        self.btn_commit.setEnabled(n > 0)
        self.btn_reject.setEnabled(n > 0)
        # Nowy staging (n>0) → Zatwierdź/Odrzuć znowu widoczne. NIE chowa tu „Cofnij" (osobny przycisk
        # FramesView) — to robi `_dismiss_undo` przy starcie stagingu (recenzent #1/#4, wiz #3).
        if n > 0:
            self.set_commit_actions_visible(True)
        if result is not None:
            self.result.setText(result)

    def set_commit_actions_visible(self, on):
        """Pokaż/ukryj Zatwierdź+Odrzuć. Po commicie chowamy je, bo jedyną sensowną akcją jest
        „Cofnij" (wizytator #5 — nie mieszać żywego Cofnij z wyszarzonym Zatwierdź/Odrzuć)."""
        self.btn_commit.setVisible(on)
        self.btn_reject.setVisible(on)


class FramesView(QWidget):
    """Widok „Klatki": panel Pól | (perspektywa + filtr + PASEK ZBIORU + panele kling + grid)
    + poczekalnia zmian (szuflada stagingu). Kontrakt montażu `MainWindow`: `__init__(con, now_fn,
    parent)`, sygnał `status_message`, `refresh()`. KROK 4: makro (druga klinga) — filtr→oblicz→
    przypisz na widocznych klatkach, staging, commit/undo. F3: klingi jako panele `_PanelStack`
    otwierane z `SelectionBar` (najwyżej jeden widoczny; R#9 w `_toggle_panel`)."""

    status_message = Signal(str)
    # Gest osi obiektu z paska Zbiorów zmienia stan, który pokazuje INNE okno (kolejka przeglądu
    # osi obiektu). Sygnał, nie wołanie: grid nie zna gospodarza i nie ma go poznawać (NARROW).
    object_axis_changed = Signal()
    # Mutex DWÓCH powierzchni writebacku (D-PD-3): gospodarz przekazuje ten fakt drugiej powierzchni
    # (dialog „Napraw nagłówek…"). Dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`
    # z `busy_timeout` 5 s i jeden wróciłby jako 'failed' — bez powodu widocznego dla usera.
    writeback_busy = Signal(bool)

    def __init__(self, con, now_fn=None, parent=None):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)   # worker writebacku otwiera WŁASNE połączenie (per-wątek)
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._filter_tree = None
        # F4: stan listwy facetów (serializowany w perspektywie OSOBNO od `_filter_tree` — nota R2)
        # + drzewo EFEKTYWNE compose(facety, advanced), ustawiane w refresh() (źródło paska kryteriów,
        # F4R#8). Oba PRZED pierwszym refresh() (F4R2#7).
        self._facet_state = facet_model.empty_state()
        self._effective_tree = None
        self._only_dups = False
        self._only_review = False
        self._only_vanished = False
        self._reveal_facet = None   # (facet, wartość) do odsłonięcia w listwie — patrz `apply_object_facet`
        self._frame_ids = []      # frame_id widoczne w gridzie (cel makra) — aktualizowane w refresh()
        self._run_id = None       # JEDEN run_id sesji makra (R#5 lifecycle: stage→commit/reject zwalnia)
        self._n_total = 0         # liczba widocznych klatek (baza licznika; zaznaczenie dokładane, G2)
        # Stan renamu — CZTERY zmienne (R1 #1 + R2 #1): run aktywnego stagingu, flaga „skommitowany"
        # (re-stage po commicie MINTUJE nowy run, nie kasuje wierszy 'applied'=undo), OSOBNY cel „Cofnij"
        # (przechwycony przy commicie — bez niego mint przekierowałby żywy Cofnij na pusty run = złudzenie),
        # tryb dispatchu współdzielonego „Cofnij" ({None,macro,rename}).
        self._rename_run_id = None
        self._rename_run_committed = False
        self._undo_rename_run_id = None
        self._undo_mode = None
        self._preview_owner = None   # {None,'macro','rename'} — podgląd współdzielony (R1 #19)
        # Writeback OFF-THREAD (commit/undo nie zamrażają GUI): cykl worker+wątek trzyma WSPÓLNY
        # uchwyt (`wb_worker.WritebackRunner`, P-D/D-PD-3 — ten sam kod wykonuje dialog „Napraw
        # nagłówek…"), tu zostaje tylko to, co widżetowe. Uchwyt POWSTAJE W `__init__`, bo seam
        # `_writeback_async` bywa ustawiany z zewnątrz PRZED pierwszą operacją (testy).
        # `_wb_target_id` zostaje W WIDOKU: czyta go `_after_commit_rename` PO zakończeniu operacji,
        # a uchwyt jest per-powierzchnia — wspólny ślad celu nadpisywałyby sobie dwa okna.
        self._wb = WritebackRunner(self._db_path, now_fn=self._now, parent=self)
        self._wb.busy_changed.connect(self.writeback_busy)   # re-emisja: uchwyt zna oba końce operacji
        self._wb_target_id = None
        self._foreign_wb = False   # DRUGA powierzchnia pisze (mutex; ustawia gospodarz)
        self._build_ui()
        # PRZED pierwszym zbudowaniem listy perspektyw: rejestr sprzed I-1 dowozi swoje widoki do
        # bazy, więc combo od razu pokazuje komplet, a nie „gdzie się podziały moje perspektywy".
        self._import_settings_perspectives()
        self._load_facets()
        self.refresh()
        self._refresh_drawer()

    # ---- budowa ----
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Górny pasek CHUDY (F3): tylko soczewki widoku (perspektywa + grupowanie); akcje na ZBIORZE
        # mieszkają w SelectionBar niżej.
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("grid.top.perspective")))
        self.combo_persp = QComboBox()
        self.combo_persp.currentIndexChanged.connect(self._on_perspective)
        bar.addWidget(self.combo_persp)
        bar.addSpacing(16)
        bar.addWidget(QLabel(i18n.t("grid.top.group_by")))
        self.combo_group = QComboBox()
        self.combo_group.addItem(i18n.t("grid.top.no_group"), None)
        for label, key in BASE_COLS:
            if key not in ("path",):
                self.combo_group.addItem(label, key)
        self.combo_group.currentIndexChanged.connect(self._on_group)
        bar.addWidget(self.combo_group)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        # F4: lewa kolumna = pionowy splitter FacetRail (góra, dominuje) / Pola (dół) — wybór kolumn
        # to inna troska niż zawężanie zbioru (COHESION), oba zostają widoczne.
        self.facet_rail = FacetRail()
        self.facet_rail.facetsChanged.connect(self._on_facet_change)
        self.fields = FieldsPanel()
        self.fields.columnsChanged.connect(self._on_columns)
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.facet_rail)
        left.addWidget(self.fields)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)
        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.filter_panel = FilterPanel([])
        self.filter_panel.filterApplied.connect(self._on_filter)
        rv.addWidget(self.filter_panel)

        # Pasek zbioru (F3): licznik + kryteria słowami + akcje; klingi jako panele w stacku niżej.
        self.sel_bar = SelectionBar()
        self.count_label = self.sel_bar.count_label      # TEN SAM QLabel (F3R#5) — `_update_count` bez zmian
        self.sel_bar.btn_proj.clicked.connect(self._open_projection)
        self.sel_bar.btn_clear.clicked.connect(self._on_clear_selection)
        self.sel_bar.btn_save.clicked.connect(self._save_perspective)
        self.sel_bar.btn_macro.clicked.connect(lambda: self._toggle_panel("macro"))
        self.sel_bar.btn_rename.clicked.connect(lambda: self._toggle_panel("rename"))
        self.sel_bar.btn_lineage.clicked.connect(lambda: self._toggle_panel("lineage"))
        self.sel_bar.act_name.triggered.connect(self._on_object_name)
        self.sel_bar.act_clear.triggered.connect(self._on_object_clear)
        rv.addWidget(self.sel_bar)

        self.macro_bar = MacroBar([])
        self.macro_bar.preview.connect(self._on_macro_preview)
        self.macro_bar.stage.connect(self._on_macro_stage)
        self.macro_bar.cleared.connect(self._on_macro_clear)

        self.rename_bar = RenameBar()                    # bliźniaczy panel obok makra (G3)
        self.rename_bar.preview.connect(self._on_rename_preview)
        self.rename_bar.stage.connect(self._on_rename_stage)
        self.rename_bar.cleared.connect(self._on_rename_clear)
        self.rename_bar.sourceChanged.connect(self._refresh_date_echo)

        self.lineage_bar = LineageBar()                   # trzeci panel stacku (I-2d)
        self.lineage_bar.judged.connect(self._on_lineage_judged)
        self.lineage_bar.offset_asked.connect(self._on_lineage_offset)
        self._lineage_frame_id = None       # cel gestu odniesienia (klatka stosu w panelu)
        # TAKT 3 gestu osi stosu — wstrzykuje gospodarz (`MainWindow`), bo tylko on zna Dostawę.
        # None = widok bez gospodarza (testy samego gridu): gest zapisuje, a zdanie mówi, gdzie
        # przeliczyć — dokładnie jak przed tą zmianą, więc brak wstrzyknięcia niczego nie psuje.
        self.run_stage_fn = None

        self.panel_stack = _PanelStack()                 # najwyżej JEDEN panel widoczny (F3)
        self.panel_stack.addWidget(self.macro_bar)
        self.panel_stack.addWidget(self.rename_bar)
        self.panel_stack.addWidget(self.lineage_bar)
        self.panel_stack.setVisible(False)               # żaden panel nie otwarty na starcie
        # PANEL BIERZE TYLE, ILE POTRZEBUJE — NADMIAR NALEŻY DO TABELI (wiz T2 N1). Domyślna
        # polityka `QStackedWidget` jest pionowo Expanding, więc stack pochłaniał leftover i stał
        # 309 px WYSOKI także wtedy, gdy niósł jedno zdanie (`sizeHint` 36 px): panel zjadał połowę
        # okna, a tabela pokazywała 10 wierszy ze 128. Samo skrócenie treści panelu tego nie ruszyło
        # — bo o wysokości decydowała polityka, nie treść.
        self.panel_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        rv.addWidget(self.panel_stack)

        self.model = GridTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        # Debounce panelu daty: `selectionChanged` może sypać setki eventów przy zaznaczeniu wsadu
        # → przelicz echo raz, po 150 ms ciszy (R1 #15).
        self._date_timer = QTimer(self); self._date_timer.setSingleShot(True); self._date_timer.setInterval(150)
        self._date_timer.timeout.connect(self._refresh_date_echo)
        # Panel rodowodu wisi na TYM SAMYM debouncie (I-2d): oba czytają zaznaczenie, oba tylko przy
        # własnym otwartym panelu, więc drugi timer byłby drugim właścicielem tego samego zdarzenia.
        self._date_timer.timeout.connect(self._refresh_lineage)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection_changed())
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)   # zebra: skanowalność długich list (P3-5)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        rv.addWidget(self.table, 1)   # stretch: nadmiar pionu należy do TABELI, nie do panelu (N1)

        self.empty = QLabel(i18n.t(_EMPTY_FILTER))
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True); self.empty.setVisible(False)
        rv.addWidget(self.empty, 1)   # stretch: pusty stan zbiera leftover — SelectionBar/panel nie balonieją (wiz F3 #1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)   # stretch: grid dominuje okno (doktryna §5), pasek nie zjada połowy (P2-1)

        self.drawer = StagingDrawer()  # stała szuflada dolna stagingu (doktryna §5)
        self.drawer.commit.connect(self._on_commit)
        self.drawer.reject.connect(self._on_reject)
        self.drawer.cancel.connect(self._on_wb_cancel)
        outer.addWidget(self.drawer)

    # ---- facety / perspektywy ----
    def _load_facets(self):
        facets = list(queries.keyword_facets(self.con))
        # Domyślne kolumny: 6 najczęstszych keywordów (po pokryciu), z pominięciem szumu strukturalnego.
        default = [f["keyword"] for f in facets if f["keyword"] not in STRUCT_NOISE][:6]
        self._all_keywords = [f["keyword"] for f in facets]
        # Lista Pól: szum strukturalny na DÓŁ (stabilnie w obrębie grup — pokrycie zachowane), P3-6.
        ordered = sorted(facets, key=lambda f: f["keyword"] in STRUCT_NOISE)
        self.fields.load(ordered, set(default))
        self._columns = default
        self.filter_panel.set_keywords(self._all_keywords)
        self.macro_bar.set_keywords(self._all_keywords)
        # perspektywy: presety (kod) + zapisane w BAZIE (I-1)
        self.combo_persp.blockSignals(True)
        self.combo_persp.clear()
        for name in PRESETS:
            self.combo_persp.addItem(i18n.t(_PRESET_LABELS[name]), ("preset", name))
        for name, spec in self._saved_perspectives():
            # Wiersz, którego nie umiemy zastosować (`spec is None` — stary `sql_text` z 0013),
            # ZOSTAJE NA LIŚCIE i mówi to wprost. Ukrycie go byłoby zniknięciem cudzej pracy bez
            # słowa; wybór kończy się statusem, nie pustym filtrem.
            label = f"★ {name}" if spec is not None else f"★ {name} ⚠"
            self.combo_persp.addItem(label, ("saved", name))
        self.combo_persp.blockSignals(False)

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _saved_perspectives(self):
        """Perspektywy z BAZY — `[(nazwa, spec|None), …]`. Rejestru już nie czytamy: to, co w nim
        było, wciągnął jednorazowy import przy budowie widoku."""
        return queries.perspectives(self.con)

    def _import_settings_perspectives(self):
        """JEDNORAZOWY, IDEMPOTENTNY import perspektyw z rejestru użytkownika do bazy (I-1).

        Wydanie publiczne zapisywało je w `QSettings` (D-B), więc przeniesienie kanonu do bazy bez
        tego kroku skasowałoby użytkownikom nazwane widoki — regresja, nie sprzątanie (FORWARD).
        Rejestru NIE czyścimy: koszt jest zerowy, a zostawiona kopia ratuje kogoś, kto wróci na
        starsze wydanie. Powtórzenie importu jest darmowe, bo `repo.save_perspective` przy
        identycznej treści nie pisze i nie emituje eventu — dlatego nie ma tu flagi „już zrobione",
        która i tak nie przeżyłaby przesiadki na drugą maszynę.

        Nazwa ISTNIEJĄCA W BAZIE wygrywa z rejestrową: baza jest teraz kanonem, a import ma
        dowieźć to, czego w niej nie ma, nie cofać czyjegoś zapisu do stanu sprzed przesiadki."""
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            store = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(store, dict) or not store:
            return
        znane = {name for name, _spec in queries.perspectives(self.con)}
        for name, spec in store.items():
            if name not in znane and isinstance(spec, dict):
                repo.save_perspective(self.con, name=name, spec=spec, now=self._now())

    def _on_perspective(self):
        data = self.combo_persp.currentData()
        if not data:
            return
        kind, name = data
        spec = PRESETS.get(name) if kind == "preset" else self._load_saved(name)
        if spec is None:
            # Perspektywa jest, ale nie umiemy jej zastosować (stary `sql_text` z migracji 0013).
            # MÓWIMY to wprost: zastosowanie pustego spec-a zdjęłoby filtr i wyglądałoby na
            # „perspektywa pokazuje wszystko", czyli cichy fałsz zamiast pytania.
            if kind == "saved":
                self.status_message.emit(i18n.t("grid.persp.unreadable", name=name))
            return
        self._only_dups = bool(spec.get("only_dups"))
        self._only_review = bool(spec.get("only_review"))
        self._only_vanished = bool(spec.get("only_vanished"))
        self._filter_tree = spec.get("filter")
        # F4R#2: stan facetów resetowany dla KAŻDEJ perspektywy (preset ORAZ zapisana) — perspektywa
        # definiuje CAŁY zbiór; stara zapisana bez klucza "facets" MUSI zerować stan, inaczej facety
        # poprzedniego wyboru wyciekają w nowy zbiór. Rail przeładuje refresh() (set_data).
        self._facet_state = spec.get("facets") or facet_model.empty_state()
        self.filter_panel.set_tree(self._filter_tree)   # panel odbija filtr perspektywy (P3-3);
        # set_tree dostaje TYLKO advanced — facety NIGDY nie idą w płaski panel (nota R2, P3-3 wyżej)
        gb = spec.get("group_by")
        idx = self.combo_group.findData(gb)
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_group.blockSignals(False)
        if "columns" in spec:
            self._columns = list(spec["columns"])
            self.fields.load(queries.keyword_facets(self.con), set(self._columns))
        self.refresh()

    def apply_object_facet(self, pairs):
        """Ustaw zbiór na WSKAZANE obiekty — publiczny seam dla wejść spoza widoku (T5e: „Pokaż
        klatki celu" z planera, D-0731-7). `pairs` = `[(object_id, canon), …]`; wiele par, bo jeden
        cel katalogu bywa w archiwum pod kilkoma nazwami (`IC410` ORAZ `LBN807`) i most ma pokazać
        SUMĘ klatek.

        Reużywa ISTNIEJĄCY facet Obiekt (liść `rel_object` + `facet_model.compose`) zamiast składać
        drzewo filtra po swojemu — druga ścieżka składania złamałaby SPOT i rozjechałaby się
        z cyklem facetów przy pierwszej zmianie. Perspektywa wraca do „Wszystkie" (zbiór definiuje
        wejście, nie poprzedni widok), advanced-filtr znika — jak przy każdej perspektywie.

        ZAZNACZENIE MUSI BYĆ WIDOCZNE: listwa domyślnie odtwarza pozycję scrolla (słusznie dla kliku
        W listwie), więc wejście z zewnątrz zostawiało `✓` poza viewportem — zmierzone: pozycja 36
        z 48 przy scrollu 0. Stąd JEDNORAZOWY `_reveal_facet`, konsumowany przez najbliższe
        przeładowanie listwy."""
        self._only_dups = self._only_review = self._only_vanished = False
        self._filter_tree = None
        self.filter_panel.set_tree(None)
        self._facet_state = {"object": {"in": [[oid, canon] for oid, canon in pairs]}} \
            if pairs else facet_model.empty_state()
        self._reveal_facet = ("object", pairs[0][0]) if pairs else None
        self.refresh()

    def apply_perspective(self, name):
        """Ustaw perspektywę PO NAZWIE — publiczny seam dla wejść spoza widoku (F5: klik w zadanie
        „Duplikaty" w Porządkach; R#14 — duplikatów NIE wyraża drzewo filtra, jedyna droga to
        mechanizm perspektyw). Presety iterowane pierwsze w combo, więc kolizja nazwy z zapisaną
        rozstrzyga się na preset. Pozycja już bieżąca → `_on_perspective()` wprost (klik w zadanie =
        ZAWSZE czysta perspektywa, nie no-op nad facetami usera). Nieznana nazwa → status."""
        for i in range(self.combo_persp.count()):
            data = self.combo_persp.itemData(i)
            if data and data[1] == name:
                if i == self.combo_persp.currentIndex():
                    self._on_perspective()
                else:
                    self.combo_persp.setCurrentIndex(i)   # currentIndexChanged → _on_perspective
                return
        self.status_message.emit(i18n.t("grid.persp.unknown", name=name))

    def _load_saved(self, name):
        return dict(self._saved_perspectives()).get(name)

    def _save_perspective(self):
        name, ok = QInputDialog.getText(self, i18n.t("grid.persp.save_title"), i18n.t("grid.persp.save_prompt"))
        if not ok or not name.strip():
            return
        name = name.strip()
        spec = {
            "filter": self._filter_tree, "columns": self._columns,
            "group_by": self.combo_group.currentData(),
            "only_dups": self._only_dups, "only_review": self._only_review,
            "only_vanished": self._only_vanished,
            "facets": self._facet_state,   # OSOBNO od "filter" (nota R2) — set_tree nigdy ich nie widzi
        }
        # Zapis idzie do BAZY (I-1) — perspektywa jedzie z archiwum, nie z tą maszyną. Czasownik
        # z klingi rozstrzyga KOMUNIKAT: nazwa przyjechana z drugiej maszyny z inną treścią zostaje
        # NADPISANA, a „zapisano" bez słowa o tym mówiłoby o czymś, co się nie stało (F9).
        _id, verb = repo.save_perspective(self.con, name=name, spec=spec, now=self._now())
        self._load_facets()
        # F4R2#6 (pre-existing, ścieżka tykana przez F4): rebuild combo pod blockSignals zostawiał
        # indeks 0 („Przegląd") przy żywym stanie świeżo zapisanej perspektywy — etykieta kłamała.
        # Re-select zapisanej, nadal bez emisji (_on_perspective nie ma czego przeładowywać:
        # stan == właśnie zapisany).
        self.combo_persp.blockSignals(True)
        for i in range(self.combo_persp.count()):
            if self.combo_persp.itemData(i) == ("saved", name):
                self.combo_persp.setCurrentIndex(i)
                break
        self.combo_persp.blockSignals(False)
        self.status_message.emit(i18n.t(
            "grid.persp.overwritten" if verb == "perspective.overwritten" else "grid.persp.saved",
            name=name))

    def _open_projection(self):
        """Otwórz dialog projekcji dla WIDOCZNEJ perspektywy (`self._frame_ids` — po filtrach dups/review,
        to co user widzi; doktryna §5). Modal TYLKO na potwierdzenie eksportu; cała mutacja plików w
        Qt-wolnej klindze `projection` przez dialog. Pusty grid → szczery status, bez pustego dialogu."""
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.proj.no_frames"))
            return
        dlg = ProjectionDialog(self.con, self._frame_ids, now_fn=self._now,
                               perspektywa=self.combo_persp.currentText(), parent=self)
        dlg.exec()
        # Wydanie zostawia ślad W APLIKACJI (wiz P-C #4): przed tym jedynym zapisem był
        # `_PROJEKCJA.json` w celu, więc po zamknięciu dialogu okno nie wiedziało nic o tym,
        # co przed chwilą wyjechało na stół. Zdanie składa dialog (tam liczby są świeże).
        if dlg.summary:
            self.status_message.emit(dlg.summary)

    # ---- oś OBIEKTU na zaznaczeniu (S2b, D-OW-6) ----

    def _object_gesture_ids(self):
        """Cel OBU gestów: WYŁĄCZNIE zaznaczenie (§4/14c-a). Fallback „to, co widoczne" jest dla
        zapisu osi ZAKAZANY — przy 800 widocznych klatkach chybione kliknięcie i zamierzony gest
        wyglądają identycznie. Pusty ⇒ status i zero zapisu; to druga linia obrony za wygaszeniem,
        bo bramka woła SLOT, nie przycisk (klik w wyszarzony przycisk przeszedłby trywialnie)."""
        ids = [r["frame_id"] for r in self._selected_data_rows()]
        if not ids:
            self.status_message.emit(i18n.t("grid.sel.object_empty"))
        return ids

    def _po_gescie_osi(self, klucz, gest, **kw):
        """Wspólny ogon obu gestów: zdanie z ROZBICIEM per fakt + odświeżenie CZTERECH powierzchni.

        Liczniki idą osobno, bo znaczą co innego: „kalibracja" to ochrona, która zadziałała,
        a „zmieniły się w międzyczasie" to ostrzeżenie, że stan uciekł. Jedno „pominięto N" kazałoby
        człowiekowi zgadywać, którą z tych dwóch rzeczy właśnie zobaczył."""
        msg = i18n.t(klucz, assigned=gest.assigned, total=gest.assigned + gest.skipped, **kw)
        # Skład i kolejność członów ma JEDNEGO właściciela (`ObjectGesture.skipped_breakdown`),
        # a nie literał tutaj: czwarty człon dołożony w S3 („nie było czego cofać") wpadłby
        # do sumy „z M" i zniknął z rozbicia, czyli dokładnie stamtąd, gdzie miał tłumaczyć.
        for sufiks, n in gest.skipped_breakdown:
            if n:
                msg += i18n.t(f"grid.sel.object_skip_{sufiks}", n=n)
        # Gotowe obrazy NIE stoją w pętli pominięć (D-OW-7): od chwili, gdy stos jest w zasięgu obu
        # gestów, ta liczba mówi o tym, co gest ZROBIŁ, a nie czego nie tknął. Zdanie „nazwano 30
        # · gotowe obrazy: 2" znaczy „dwa z tych trzydziestu to obrazy po integracji" — a nie „dwa
        # zostawiłem". Człon zostaje osobny, bo to jedyny zapis osi, który sięga rodowodu.
        if gest.stacks:
            msg += i18n.t("grid.sel.object_stacks", n=gest.stacks)
        if gest.assigned:
            # CZTERY POWIERZCHNIE: wiersze gridu, facety (Obiekt zmienił zawartość), licznik/pasek
            # oraz kolejka przeglądu w oknie osi — ta ostatnia przez sygnał, bo nie jest nasza.
            self.refresh()
            self.object_axis_changed.emit()
        # ZDANIE IDZIE PO ODŚWIEŻENIU, nie przed (adjudykacja recenzji S2b). `refresh()` kończy się
        # własnym `status_message` („Grid: N klatek…"), a odbiornikiem jest jeden `showMessage`
        # paska stanu — emisja przed odświeżeniem ginęła w tym samym obrocie pętli. Skutek był
        # dokładnie odwrotny do zamierzonego: rozbicie per fakt user widział WYŁĄCZNIE wtedy, gdy
        # gest niczego nie zapisał (bo wtedy `refresh()` nie leci), a po udanym zapisie — nigdy.
        self.status_message.emit(msg)

    def _on_object_name(self):
        """„Nazwij zaznaczenie…": nadpisuje WYŁĄCZNIE źródła słabe, przy zamrożonym stanie okna."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        stan = queries.selection_object_state(self.con, ids)
        if stan["conflict"]:
            # Dwa różne obiekty wśród klatek podlegających nadpisaniu ⇒ gest nie ma JEDNEGO
            # przedmiotu. Odmowa BEZ zapisu — częściowe wykonanie byłoby gorsze niż żadne, bo
            # user zobaczyłby „nazwano 30 z 80" i nie wiedział, które 30.
            # Liczba z READ-MODELU, nie literał: „2" było zaszyte, więc zaznaczenie z siedmioma
            # obiektami kazało zawęzić do dwóch, a po zawężeniu odmawiało tak samo — komunikat
            # o fałszywej liczbie jest receptą, której nie da się wykonać.
            self.status_message.emit(i18n.t("grid.sel.object_conflict", n=stan["conflict_n"]))
            return
        # LICZBA W OKNIE = ile gest realnie ruszy (`namable`), a nie ile zaznaczono: przycisk mówił
        # „Przypisz 8 klatek" i zapisywał 4, a przy realnym archiwum (większość lightów ma źródło
        # mocne) rozjazd jest regułą, nie wyjątkiem. Kontekst zaznaczenia idzie dalej, bo to okno
        # pyta wtedy o NADPISANIE cudzej nazwy i musi to powiedzieć zamiast zdania o kubełku RAW.
        # Zaznaczenie też bywa nagrobkiem — „Nazwij" jedzie `overwrite_weak=True`, więc gasi
        # werdykt tak samo, jak zapis z kubełka cofniętych. Liczba z read-modelu (`by_source`),
        # nie z osobnego zapytania: ten sam dict już wygasza kontrolkę.
        dlg = AssignObjectDialog(self.con, object_raw=None, frame_count=stan["namable"],
                                 selection=stan,
                                 cleared_n=stan["by_source"].get("user_cleared", 0), parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        canon, catalog, kind, alias_norm = dlg.selected
        try:
            gest = repo.user_assign_object(
                self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                frame_ids=ids, now=self._now(), overwrite_weak=True,
                expected_object_id=stan["expected_object_id"])
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("grid.sel.object_name"), str(e))
            return
        self._po_gescie_osi("grid.sel.object_named", gest, canon=canon)

    def _on_object_clear(self):
        """„Cofnij przypisanie": zdejmuje wyłącznie to, co postawiła ręka albo ścieżka."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        gest = repo.clear_object_assignment(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_osi("grid.sel.object_cleared", gest)

    # ---- panele kling (F3, PLAN_ux_redesign §4) ----
    def _toggle_panel(self, which):
        """Panel klingi z paska zbioru: najwyżej JEDEN widoczny. Zamknięcie zostawia podgląd
        (kolumna podglądu w gridzie to wartość sama w sobie; staging żyje w poczekalni niezależnie).
        Otwarcie/przełączenie na panel X przy podglądzie CUDZEGO właściciela czyści go WPROST
        handlerem `cleared` (R#9 — bez emitowania sygnału cudzego widżetu). SEKWENCJA otwarcia =
        kontrakt (F3R#4): strona stacku → pokaż → echo daty (guard echa musi już widzieć rename)."""
        target = {"macro": self.macro_bar, "rename": self.rename_bar,
                  "lineage": self.lineage_bar}[which]
        # „otwarty" = JAWNIE pokazany (isHidden odwrócone), NIE isVisible() — to drugie jest False,
        # gdy przodek niepokazany (offscreen testy przed show()), i kłamałoby o stanie stacku.
        if not self.panel_stack.isHidden() and self.panel_stack.currentWidget() is target:
            self.panel_stack.setVisible(False)           # zamknięcie: podgląd ZOSTAJE
            self.sel_bar.set_active_panel(None)
            return
        if (self._preview_owner and self._preview_owner != which
                and self.model._preview_active()):
            if self._preview_owner == "macro":
                self._on_macro_clear()
            else:
                self._on_rename_clear()
        self.panel_stack.setCurrentWidget(target)
        self.panel_stack.setVisible(True)
        self.sel_bar.set_active_panel(which)
        if which == "rename":
            self._refresh_date_echo()                    # PO pokazaniu strony (F3R#4)
        elif which == "lineage":
            self._refresh_lineage()                      # jw. — panel czyta zaznaczenie po pokazaniu

    def _rename_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.rename_bar)

    def changeEvent(self, e):
        """Zmiana skórki PRZEBUDOWUJE panel rodowodu — wygaszenie wiersza jest w nim WYPALONE
        w itemie (`setForeground`), a nie czytane w `paint` jak w delegacie gridu, więc samo
        odmalowanie zostawiłoby kolor ze starego motywu. Lekcja jest w repo spisana od dawna
        (`app.py` przebudowuje z tego powodu inne listy) — panel rodowodu był drugim jej złamaniem,
        raz w osi stosów, raz w dołożonej osi kalibracji."""
        super().changeEvent(e)
        if e.type() == QEvent.PaletteChange:
            self._refresh_lineage()          # warunkowe: przy zamkniętym panelu nie czyta bazy

    # ---- panel RODOWODU (I-2d) ----
    def _lineage_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.lineage_bar)

    def _refresh_lineage(self, *, select_frame_ids=None):
        """Wypełnij panel rodowodu z zaznaczenia. Warunek: DOKŁADNIE JEDNA zaznaczona klatka
        `master_light` — rodowód jest faktem o JEDNYM obrazie, a „rodowód zbioru" nie znaczy nic.
        Każdy inny stan dostaje ZDANIE, nie pustkę: user ma wiedzieć, czego brakuje do odpowiedzi
        (wzorzec „uczciwy disabled", tylko że tłumaczy się panel, nie przycisk).

        `select_frame_ids` przywraca zaznaczenie PO odświeżeniu (werdykt ręki) — po klatkach,
        nie po indeksach, bo kolejność wierszy należy do zapytania, a nie do panelu.

        Świadomie WARUNKOWE (jak `_refresh_date_echo`): przy zamkniętym panelu nie czytamy bazy."""
        if not self._lineage_panel_open():
            return
        wiersze = self._selected_data_rows()
        stosy = [r for r in wiersze if r.get("kind") == "master_light"]
        if len(stosy) != 1:
            # OŚ KALIBRACJI (C3, Issue #6) — druga odpowiedź tego samego panelu. Warunek jest
            # DOPEŁNIENIEM osi stosów, nie jej konkurentem: pytamy dopiero, gdy w zaznaczeniu nie
            # ma gotowego obrazu, więc droga stosu zachowuje się dokładnie jak przedtem.
            lighty = [r for r in wiersze if r.get("kind") == "light"]
            # DOKŁADNIE JEDEN ZAZNACZONY WIERSZ, nie „jeden light wśród kilku klatek" (CAPTAIN):
            # nagłówek panelu nie nazywa klatki, więc przy zaznaczeniu light+dark+bias użytkownik
            # nie miałby jak sprawdzić, o której z nich mówi ekran.
            if len(wiersze) == 1 and lighty:
                relacje = lineage.explain_light(self.con, lighty[0]["frame_id"])
                if relacje:
                    self.lineage_bar.set_calibration(relacje)
                    return
            # TRZY RÓŻNE POMYŁKI, TRZY ZDANIA. Jeden komunikat na wszystkie mówił o klatce
            # KALIBRACYJNEJ także wtedy, gdy zaznaczono dwie klatki nieba — czyli zdanie fałszywe
            # o tym, co użytkownik ma przed oczami (ta sama klasa co „kryterium sklejające fakty").
            klucz = ("grid.lin.hint.none" if not wiersze else
                     "grid.lin.hint.many" if len(stosy) > 1 or len(lighty) > 1 else
                     "grid.lin.hint.one_only" if len(wiersze) > 1 else
                     "grid.lin.hint.not_stack")
            self.lineage_bar.set_lineage(None, [], hint=i18n.t(klucz))
            return
        fid = stosy[0]["frame_id"]
        head = queries.stack_lineage_head(self.con, fid)
        if head is None:
            self.lineage_bar.set_lineage(None, [], hint=i18n.t("grid.lin.hint.not_computed"))
            return
        # PROPOZYCJA ODNIESIENIA LICZONA TYLKO TAM, GDZIE JEST PYTANIEM (R2): dla 121 masterów
        # FITS/ASI zegar nie jest problemem, a zapytanie chodzi po całym materiale obiektu, więc
        # liczenie go przy każdym zaznaczeniu byłoby kosztem bez odbiorcy.
        self.lineage_bar.set_offset_hint(
            stacks.propose_offset_minutes(self.con, fid)
            if head["unresolved_reason"] == "offset_unknown" else None)
        self.lineage_bar.set_lineage(head, queries.stack_lineage_inputs(self.con, fid))
        self._lineage_frame_id = fid
        if select_frame_ids:
            self.lineage_bar.select_frame_ids(select_frame_ids)

    def _on_lineage_offset(self, minutes):
        """Wskazane odniesienie czasu → jedna klinga (`repo.set_integration_offset`), potem
        odświeżenie panelu ze STANU — lustro `_on_lineage_judged`.

        RODOWODU TU NIE PRZELICZAMY i to jest granica, nie brak: dobór wejść jedzie po CAŁYM
        archiwum stosów (`run_stack_lineage`), więc jest robotą etapu w Dostawie, nie skutkiem
        ubocznym kliknięcia w panelu. Zamiast tego zdanie mówi WPROST, gdzie to policzyć — ta sama
        umowa, co przy geście zestawu w R1."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        repo.set_integration_offset(self.con, master_frame_id=self._lineage_frame_id,
                                    utc_offset_min=minutes, now=self._now())
        self._refresh_lineage()
        godziny = f"{minutes / 60.0:+.1f}"
        # TAKT 3: gest sam się domyka. Bez tego user musiał przejść na inny ekran i znaleźć tam
        # przycisk stojący obok wyboru katalogu — akcja domykająca gest mieszkała w sekcji
        # o wciąganiu plików z dysku. Odmowa (etap już biegnie / brak bazy) NIE jest błędem gestu:
        # zapis się udał, więc mówimy prawdę o obu połówkach i zostawiamy zdanie z receptą.
        if self.run_stage_fn is None:
            self.status_message.emit(i18n.t("grid.lin.offset_saved", hours=godziny))
            return
        powod = self.run_stage_fn()
        self.status_message.emit(
            i18n.t("grid.lin.offset_saved_counting", hours=godziny) if powod is None
            else i18n.t("grid.lin.offset_saved_busy", hours=godziny, reason=powod))

    def _on_lineage_judged(self, frame_ids, excluded):
        """Werdykt ręki → jedna klinga (`repo.judge_integration_input`), potem odświeżenie panelu
        ze STANU. Zapis jest natychmiastowy i BEZ poczekalni: to decyzja o RELACJI w bazie, nie
        mutacja pliku — staging chroni bajty na dysku, a tu żaden bajt nie jest ruszany."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        n = 0
        for fid in frame_ids:
            n += repo.judge_integration_input(
                self.con, integration_id=iid, input_frame_id=fid,
                excluded=excluded, now=self._now())
        # ZAZNACZENIE PRZEŻYWA WERDYKT: lista jest przebudowywana ze stanu, więc bez tego człowiek
        # tracił wiersze zaraz po decyzji i cofnięcie własnego „odrzuć" kosztowało odszukanie ich
        # od nowa (wiz #8). Zwracamy te same klatki, nie te same indeksy — kolejność wierszy
        # należy do zapytania.
        self._refresh_lineage(select_frame_ids=frame_ids)
        # Klinga jest idempotentna, więc powtórzony ten sam werdykt daje 0 — a „Potwierdzono 0"
        # brzmi jak porażka zapisu, którym nie jest (QUIET: brak zmiany mówi o braku zmiany).
        klucz = ("grid.lin.judged_none" if not n else
                 "grid.lin.judged_excluded" if excluded else "grid.lin.judged_confirmed")
        self.status_message.emit(i18n.t(klucz, n=n))

    def _describe_criteria(self):
        """Opis zbioru słowami do paska: drzewo EFEKTYWNE (facety + advanced — F4R#8, samo
        `_filter_tree` nie widzi facetów) + flagi perspektyw spoza silnika (`only_dups`/`only_review`
        — grid.py PRESETS; drzewo ich nie koduje, F4R2#7), łączone „ · "."""
        parts = [filter_engine.describe(self._effective_tree)]
        if self._only_dups:
            parts.append(i18n.t("grid.criteria.only_dups"))
        if self._only_review:
            parts.append(i18n.t("grid.criteria.only_review"))
        if self._only_vanished:
            parts.append(i18n.t("grid.criteria.only_vanished"))
        return " · ".join(parts)

    # ---- reakcje ----
    def _on_filter(self, tree):
        self._filter_tree = tree
        self.refresh()

    def _on_columns(self, cols):
        self._columns = cols
        self.refresh()

    def _on_group(self):
        self.model.set_group_by(self.combo_group.currentData())

    # ---- odczyt → widok ----
    def _memo_leaf_fns(self):
        """Memoizowane akcesory silnika na czas JEDNEGO refreshu (F4R2#4): sibling-sety facetów
        re-używają tych samych liści, więc cache `(kind,kw,p1,p2)→set` zwija 5N wywołań liści do N.
        Jedna migawka DB per refresh — cache umiera z wyjściem z refresh() (źródło prawdy = baza)."""
        leaf_cache = {}
        universe_cache = []

        def leaf_fn(k, kw, p1, p2):
            key = (k, kw, p1, p2)
            if key not in leaf_cache:
                leaf_cache[key] = queries.leaf_frame_ids(self.con, k, kw, p1, p2)
            return leaf_cache[key]

        def universe_fn():
            if not universe_cache:
                universe_cache.append(queries.all_frame_ids(self.con))
            return universe_cache[0]

        return leaf_fn, universe_fn

    def refresh(self):
        """Silnik filtra → zbiór frame_id → base_rows + pivot → model. Źródło prawdy = baza (bez
        cache między refreshami). F4: drzewo EFEKTYWNE = compose(stan facetów, drzewo panelu);
        trimy dups/review SETAMI literałowymi PRZED base_rows — JEDNA derywacja trimu dla zbioru
        głównego i sibling-setów listwy (SPOT, F4R2#2); liczniki listwy per sibling-set (F4R#1).

        POD NAZWANĄ FAZĄ (F-1): zmierzone **1 000 ms** na 16 648 klatkach, a wołane przy KAŻDEJ
        zmianie facetu, perspektywy i filtra — czyli w reakcji na kliknięcie, po którym user czeka
        i patrzy w nieruchomy ekran."""
        with busy.busy(self.status_message.emit, i18n.t("busy.read_frames")):
            self._refresh()

    def _refresh(self):
        """Wykonawcza połowa `refresh` (fazę zakłada wołający — JEDEN jej właściciel)."""
        leaf_fn, universe_fn = self._memo_leaf_fns()
        self._effective_tree = facet_model.compose(self._facet_state, self._filter_tree)
        frame_ids = filter_engine.run(self._effective_tree, leaf_fn=leaf_fn, universe_fn=universe_fn)
        dup_ids = queries.dup_frame_ids(self.con) if self._only_dups else None
        review_ids = queries.review_frame_ids(self.con) if self._only_review else None
        gone_ids = queries.vanished_frame_ids(self.con) if self._only_vanished else None
        # NOWY set, NIGDY `&=`: przy pustym filtrze `filter_engine.run` zwraca uniwersum WPROST
        # (`filter_engine.py:171`), a to jest ZAPAMIĘTANY obiekt memoizacji (`_memo_leaf_fns`).
        # `&=` przycinało go W MIEJSCU, więc kolejne `universe_fn()` widziało już przycięty zbiór —
        # perspektywa z trimem potrafiła pokazać „Baza pusta" na pełnej bazie (wizytator P5 #2).
        for trim in (dup_ids, review_ids, gone_ids):
            if trim is not None:
                frame_ids = frame_ids & trim
        base = [_derive(r) for r in queries.base_rows(self.con, list(frame_ids))]
        base_ids = [b["frame_id"] for b in base]
        self._frame_ids = base_ids     # cel makra = to, co WIDAĆ (po filtrach dups/review), doktryna §5
        keywords = list(self._columns)
        rows = queries.cards_pivot(self.con, base_ids, keywords) if (base_ids and keywords) else []
        pv = pivot_mod.build_pivot(base_ids, keywords, rows)
        self.model.set_data(base, pv, keywords, group_by=self.combo_group.currentData())
        n = len(base)
        self._n_total = n
        self._update_count()
        if n == 0:
            # Rozróżnienie „filtr nic nie wpuścił" vs „w bazie NIC nie ma" (wiz F5 #8). Uniwersum
            # bierzemy z memoizowanego `universe_fn` TEGO refreshu — na niepustym gridzie zapytania
            # nie ma w ogóle, a gdy filtr już go dotknął, jest z cache'u.
            self.empty.setText(i18n.t(_EMPTY_FILTER) if universe_fn() else i18n.t(_EMPTY_DB))
        self.empty.setVisible(n == 0)
        self.table.setVisible(n > 0)
        self.macro_bar.set_actions_enabled(bool(base_ids))   # szczery disabled makra na pustym gridzie (#4)
        self.rename_bar.set_actions_enabled(bool(base_ids))  # bliźniaczo dla renamu
        self.sel_bar.set_have_frames(bool(base_ids))         # pusty zbiór gasi „Wydaj na stół…" (F3R#2)
        self.sel_bar.set_criteria(self._describe_criteria()) # kryteria zbioru SŁOWAMI (F3)
        self.sel_bar.set_clearable(bool(self._facet_state) or self._filter_tree is not None)
        self._reload_facet_rail(leaf_fn, universe_fn, dup_ids, review_ids, base_ids)   # listwa (F4)
        self._sync_staging_mutex()                           # staging jednej klingi wyłącza „Do stagingu" drugiej
        self._refresh_date_echo()                            # panel daty odbija świeże widoczne (echo warunkowe)
        self._refresh_lineage()                              # …i panel rodowodu, tak samo warunkowo
        self.status_message.emit(
            i18n.t("grid.status.loaded", frames=i18n.t_plural('grid.frames', n), cols=len(keywords)))

    def _reload_facet_rail(self, leaf_fn, universe_fn, dup_ids, review_ids, current_ids):
        """Liczniki listwy facetów per SIBLING-SET (F4R#1): zbiór facetu F = compose bez CAŁEJ własnej
        grupy F (in+ex) — liczniki na pełnym zbiorze samo-zawężałyby facet i OR-wewnątrz byłby
        nieosiągalny. Facet BEZ aktywnego wyboru → sibling == zbiór bieżący (już policzony;
        D-UX-3(a)). Trimy dups/review = przecięcie z gotowymi setami (F4R2#2, bez base_rows)."""
        counts, extras = {}, {}
        for facet in facet_model.FACETS:
            if facet not in self._facet_state:
                ids = current_ids
            else:
                tree = facet_model.compose(facet_model.sibling_state(self._facet_state, facet),
                                           self._filter_tree)
                sib = filter_engine.run(tree, leaf_fn=leaf_fn, universe_fn=universe_fn)
                if dup_ids is not None:
                    sib &= dup_ids
                if review_ids is not None:
                    sib &= review_ids
                ids = list(sib)
            counts[facet] = self._facet_counts(facet, ids)
            if facet == "object":
                # Portfel (F7 §8): godziny lightów per obiekt na TYM SAMYM `ids` co `facet_objects`
                # (parytet n↔godziny; inne aktywne facety zawężają godziny). Formatowanie = `portfolio`.
                summ = portfolio.summarize(queries.object_exposure(self.con, ids))
                extras["object"] = {oid: (portfolio.object_suffix(e), portfolio.object_tooltip(e))
                                    for oid, e in summ.items()}
        # `_reveal_facet` jest JEDNORAZOWY: gasimy go tu, nie u wołającego — inaczej każdy kolejny
        # refresh (klik w listwie, zmiana perspektywy) skakałby do celu sprzed pół godziny.
        reveal, self._reveal_facet = self._reveal_facet, None
        # DRUGIE NAZWY do szukajki (S3): mapa `canon → {alias_norm}` z CAŁEJ biblioteki, nie ze
        # zbioru — szukajka chowa wiersze listy, więc filtrowanie mapy po `ids` nic by nie
        # oszczędziło, a rozjechałoby dwa wejścia tego samego pytania. Bez niej „Large Magellanic
        # Cloud" nie znajduje niczego: kanon `LMC` nie ma z tą frazą wspólnej litery.
        self.facet_rail.set_data(counts, self._facet_state, extras, reveal=reveal,
                                 aliases=queries.object_alias_index(self.con))

    def _facet_counts(self, facet, ids):
        """Kubełki jednego facetu → list[(value, label, n)] (kontrakt `FacetRail.set_data`).
        Etykieta teleskopu = label→canon fallback z JEDNEGO właściciela (`queries.telescope_label`);
        filtr/rodzaj/noc są swoją własną etykietą."""
        if facet == "object":
            return [(r["id"], r["canon"], r["n"]) for r in queries.facet_objects(self.con, ids)]
        if facet == "filter":
            return [(r["filter_canon"], r["filter_canon"], r["n"])
                    for r in queries.facet_filters(self.con, ids)]
        if facet == "kind":
            return [(r["kind"], r["kind"], r["n"]) for r in queries.facet_kinds(self.con, ids)]
        if facet == "telescope":
            return [(r["id"], queries.telescope_label(r), r["n"])
                    for r in queries.facet_telescopes(self.con, ids)]
        return [(r["night"], r["night"], r["n"]) for r in queries.facet_nights(self.con, ids)]

    def _on_facet_change(self, state):
        """Klik w listwie (cykl none→in→ex→none policzony w `facet_model.cycle`) → nowy stan →
        przeskładanie zbioru. Stan JEST własnością FramesView (widżet emituje wynik)."""
        self._facet_state = state
        self.refresh()

    def _on_clear_selection(self):
        """„× Wyczyść zbiór" (wiz F4 #3): zdejmij facety + filtr advanced JEDNYM klikiem. Flagi
        perspektywy (`only_dups`/`only_review`) zostają — są własnością perspektywy, nie filtra.
        `_clear` panelu emituje `filterApplied(None)` → `_on_filter` → jeden refresh."""
        self._facet_state = facet_model.empty_state()
        self.filter_panel._clear()

    def _on_selection_changed(self):
        self._update_count()
        self._date_timer.start()                             # debounced echo daty (R1 #15)

    def _update_count(self):
        """Licznik = widoczne klatki + (gdy jest) zaznaczenie: „N klatek · M zaznaczonych" (wizytator G2 —
        akcja na zaznaczeniu musi potwierdzać cel). Nagłówki grup są nieselektowalne → nie liczą się.
        Odświeża też żywą etykietę celu renamu (R1 #18): zaznaczenie-first, inaczej widoczne.
        Odmiana przez `plural` [#11]: ścieżka Duplikatów robi z n=1 przypadek TYPOWY, a „1 klatek"
        na pasku zbioru czytało się jak błąd (wiz K7 / wiz F5 #7).

        JEDEN PRZEBIEG ZAZNACZENIA NA ZDARZENIE (R-S2b-7). Do S3 ta metoda chodziła po zaznaczeniu
        DWA razy — raz po licznik (`selectedRows()`), raz po id-y (`_selected_data_rows`) — a każdy
        przebieg kosztował **1,06 s** przy pełnym zaznaczeniu 16 648 klatek. Licznik bierze się więc
        z tej samej listy wierszy, z której biorą się id-y."""
        rows = self._selected_data_rows()
        sel = len(rows)
        txt = i18n.t_plural("grid.frames", self._n_total) + (
            f"  ·  {i18n.t_plural('grid.selected', sel)}" if sel else "")
        self.count_label.setText(txt)
        self._sync_object_actions(rows)
        if hasattr(self, "rename_bar"):
            self.rename_bar.set_target_label(
                f"Cel: {i18n.t_plural('grid.selected', sel)}" if sel
                else f"Cel: {i18n.t_plural('grid.visible', self._n_total)}")

    def _sync_object_actions(self, rows=None):
        """Uczciwy disabled osi obiektu — liczony z ZAZNACZENIA, nie z widocznych (§4/14c-a).

        BEZ DEBOUNCE'U, i to jest wynik POMIARU, nie zaniechanie (R-S2b-7). Znalezisko mówiło
        „read-model w gorącej pętli" i szacowało koszt na `json.dumps` 15 890 id + `json_each`
        na wątku GUI. Zmierzone przy pełnym zaznaczeniu 16 648 klatek: `selection_object_state`
        = **31 ms**, czyli 1,5% kosztu `_update_count`; całe 2 040 ms brał `selectedRows()`,
        wołany dwa razy — i to jego zdjęcie (zakresy zamiast `QModelIndex`) załatwiło pętlę,
        z 2 071 ms na **2 ms**. Debounce dołożony NA WIERZCH tej naprawy kupowałby 31 ms na
        zdarzenie, a płacił niezmiennikiem „po zmianie zaznaczenia pasek mówi prawdę": stan
        pozycji menu zależałby od timera, więc każda bramka uczciwości disabled musiałaby pompować
        pętlę zdarzeń. Zła cena za 1,5%.

        `rows` przekazuje wołający, gdy już je ma — jeden przebieg zaznaczenia na zdarzenie.
        Read-model pytamy tylko wtedy, gdy jest o co pytać: przy pustym zaznaczeniu odpowiedź jest
        znana bez SQL-a."""
        if rows is None:
            rows = self._selected_data_rows()
        ids = [r["frame_id"] for r in rows]
        stan = queries.selection_object_state(self.con, ids) if ids else None
        self.sel_bar.set_object_actions(
            namable=stan["namable"] if stan else 0,
            clearable=stan["clearable"] if stan else 0,
            reason=_object_gate_reason(stan))

    # ---- panel inspekcji daty (G1/G4 — RenameBar) ----
    def _selected_data_rows(self):
        """Wiersze-klatki (bez markerów grup) dla zaznaczenia. Puste zaznaczenie → [].

        Z ZAKRESÓW zaznaczenia, nie z `selectedRows()` (R-S2b-7). `QItemSelectionRange.indexes()`
        woła `model.flags()` dla KAŻDEJ komórki zakresu i buduje `QModelIndex` per wiersz —
        zmierzone **1,06 s** na 16 648 zaznaczonych klatkach, czyli ta sama klasa kosztu, którą
        `b5d1b5c` zdjęło z przeładowania tabeli. Zakresy niosą samą geometrię (O(zakresów)),
        a jedyne, czego ta metoda potrzebuje, to NUMERY wierszy.

        Filtr `"_group" not in row` zostaje jedynym sitem i to on odtwarza kontrakt starej wersji:
        `indexes()` odsiewał nagłówki grup przez `ItemIsSelectable`, zakres ich nie odsieje, bo nie
        pyta modelu o flagi. Zakresy potrafią się nakładać (kontrakt Qt), więc numery deduplikujemy
        — inaczej klatka wpadłaby do zapisu dwa razy.

        KOLEJNOŚĆ ZMIENIA SIĘ ŚWIADOMIE: `selectedRows()` oddawał wiersze w kolejności KLIKANIA,
        ta droga — w kolejności w tabeli. Sprawdzone na parytecie (zbiór identyczny w każdym
        przypadku, także przy zakresach nakładających się i przy grupowaniu) oraz u wszystkich
        pięciu wołających: każdy bierze zbiór albo długość, żaden nie stoi na kolejności kliknięć.
        Porządek wierszowy jest przy tym DETERMINISTYCZNY, a tamten zależał od tego, jak user
        klikał."""
        sm = self.table.selectionModel()
        if sm is None:
            return []
        numery = set()
        for zakres in sm.selection():
            numery.update(range(zakres.top(), zakres.bottom() + 1))
        out = []
        for i in sorted(numery):
            row = self.model._rows[i]
            if isinstance(row, dict) and "_group" not in row:
                out.append(row)
        return out

    def _refresh_date_echo(self):
        """Odśwież panel daty RenameBar z zaznaczenia (albo widocznych, gdy puste). G1 ŚWIADOMIE
        WARUNKOWE (R1 #17): przy ZAMKNIĘTYM panelu echo zaznaczenia niesie już licznik G2 — pełne
        echo daty wymaga otwartego panelu renamu (przepływ renamu i tak dzieje się przy otwartym;
        `_toggle_panel` woła echo PO pokazaniu strony — F3R#4)."""
        if not self._rename_panel_open():
            return
        scope = self._selected_data_rows() or self.model._data_rows
        if len(scope) == 1:
            r = scope[0]
            h = naming.header_dt(r.get("date_obs"))
            fn = naming.filename_dt(os.path.basename(r["path"])) if r.get("path") else None
            primary = (i18n.t("grid.echo.dateobs", ts=f"{h:%Y-%m-%d %H:%M:%S}") if h
                       else i18n.t("grid.echo.dateobs_none"))
            secondary = (i18n.t("grid.echo.fname_time", ts=f"{fn:%Y-%m-%d %H:%M:%S}") if fn
                         else i18n.t("grid.echo.fname_none"))
            d = r.get("_dt_delta")
            if d is None:
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta_none"),
                                         i18n.t("grid.echo.no_time_src"), flag_role="secondary")
            else:
                flag = i18n.t("grid.echo.delta_subhour") if abs(d - round(d)) > 1e-9 else ""
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta", d=f"{d:g}"), flag)
            return
        # wsad (>1): mediana Δ + rozrzut (1 interakcja/wsad, §5b briefu-matki) + align
        deltas = [r["_dt_delta"] for r in scope if r.get("_dt_delta") is not None]
        primary = i18n.t("grid.echo.batch", n=len(scope), both=len(deltas))
        if deltas:
            med = statistics.median(deltas)
            spread = max(deltas) - min(deltas)
            self.rename_bar.set_echo(primary,
                                     i18n.t("grid.echo.batch_stats", med=f"{med:g}", spread=f"{spread:g}"),
                                     "", "", median=med, spread=spread)
        else:
            self.rename_bar.set_echo(primary, i18n.t("grid.echo.no_time_batch"), "", "")

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU grida (makro/rename/staging/commit/undo) — worker
        pisze do bazy w tle (wizytator C1). Po etapie przywróć SZCZERE stany (paski wg widocznych klatek,
        commit/odrzuć wg liczby oczekujących AKTYWNEJ klingi); nie tykamy etykiet/widoczności szuflady (D2)."""
        if busy:
            self.macro_bar.set_actions_enabled(False)
            self.rename_bar.set_actions_enabled(False)
            self.sel_bar.btn_proj.setEnabled(False)      # „Wydaj" gaśnie w biegu etapu (F3R#7)
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            # Panel „Rodowód" to CZWARTA powierzchnia zapisu (I-2d) i pisze do tego samego stołu,
            # który worker właśnie przelicza — bez tej linii werdykt ręki wchodził w środek etapu.
            self.lineage_bar.set_busy(True)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            self.macro_bar.set_actions_enabled(bool(self._frame_ids))
            self.rename_bar.set_actions_enabled(bool(self._frame_ids))
            self.sel_bar.set_have_frames(bool(self._frame_ids))
            n = self._active_pending_count()             # mode-aware (R1 #2): makro LUB rename
            self.drawer.btn_commit.setEnabled(n > 0)
            self.drawer.btn_reject.setEnabled(n > 0)
            self.lineage_bar.set_busy(False)             # panel wraca do stanu z zaznaczenia
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._sync_staging_mutex()

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (dialog „Napraw nagłówek…") pisze do plików — wygaś
        Zatwierdź/Odrzuć/Cofnij (D-PD-3). To NIE to samo co `set_busy`: tam pisze pipeline do BAZY
        i gasną wszystkie akcje zapisu; tu chodzi o jeden zasób — mutację plików pod jedną
        transakcją. Własny bieg gridu tej ścieżki nie używa (jego akcje są wtedy schowane paskiem
        postępu), więc flaga mówi wyłącznie o CUDZEJ operacji."""
        self._foreign_wb = busy
        if busy:
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._refresh_drawer()                       # szczere stany wg oczekujących AKTYWNEJ klingi

    # ---- makro / staging (KROK 4, druga klinga) ----
    def _targets_fn(self, frame_ids):
        return queries.writeback_frame_targets(self.con, frame_ids)

    def _cards_fn(self, frame_id):
        return queries.frame_cards(self.con, frame_id)

    def _run(self, md, run_id=None):
        """Uruchom makro nad widocznymi frame_ids (czysty silnik + wstrzyknięte akcesory). Błąd
        DEFINICJI makra (skladnia/węzeł) → komunikat, None."""
        try:
            return macro_mod.run_macro(md, self._frame_ids, targets_fn=self._targets_fn,
                                       cards_fn=self._cards_fn, run_id=run_id)
        except (macro_mod.expr.ExprError, ValueError) as exc:
            # Błąd DEFINICJI makra → sprzężenie w szufladzie + status (bez modalu — doktryna §5, #3).
            self.drawer.set_count(self._pending_count(), result=i18n.t("grid.macro.error", exc=exc))
            self.status_message.emit(i18n.t("grid.macro.error", exc=exc))
            return None

    def _show_preview(self, run):
        """Wrzuć podgląd makra do modelu (stara→nowa / pominięto) i zwróć (touched, skipped).
        Grid kluczuje FRAME, a touched niesie location_id → mapuj przez `location.frame_id`."""
        self._note_preview_takeover("macro")
        preview = {}
        for pv in run.touched:
            fid = self._frame_for_location(pv.location_id)
            if fid is not None:
                preview[fid] = {"keyword": pv.keyword, "old": pv.old_value, "new": pv.new_value,
                                "op": pv.op}
        for sk in run.skipped:
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview)
        return len(run.touched), len(run.skipped)

    def _frame_for_location(self, location_id):
        return queries.frame_for_location(self.con, location_id)

    def _on_macro_preview(self, md):
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames_count"))
            return
        run = self._run(md)
        if run is None:
            return
        t, s = self._show_preview(run)
        self.status_message.emit(i18n.t("grid.macro.preview_result", t=t, s=s))

    def _on_macro_stage(self, md):
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames"))
            return
        if self._rename_pending_count() > 0:             # mutex symetryczny: staging renamu w toku
            self.status_message.emit(i18n.t("grid.macro.staging_busy"))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        if self._run_id is None:
            self._run_id = uuid.uuid4().hex
        repo.clear_pending_for_run(self.con, self._run_id)   # idempotentny re-stage (R#5)
        run = self._run(md, run_id=self._run_id)
        if run is None:
            return
        for p in run.touched:
            repo.stage_pending(
                self.con, run_id=self._run_id, location_id=p.location_id, keyword=p.keyword,
                idx=p.idx, op=p.op, old_value=p.old_value, new_value=p.new_value,
                new_type=p.new_type, new_comment=p.comment,
                expected_header_hash=p.expected_header_hash)
        self._show_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.macro.staged", t=len(run.touched), s=len(run.skipped)))

    def _on_macro_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit(i18n.t("grid.macro.preview_cleared"))

    @staticmethod
    def _first_reason(res):
        """Reprezentatywny powód blokady/błędu do summary — user na ścianie blocked pyta „czemu?",
        nie chce samego licznika (wizytator #4). Pierwszy niepusty `reason` z blocked/failed."""
        return next((fr.reason for fr in (res.blocked + res.failed) if fr.reason), None)

    def _pending_count(self):
        if self._run_id is None:
            return 0
        return sum(1 for r in writeback.pending_for_run(self.con, self._run_id)
                   if r["status"] == "pending")

    def _rename_pending_count(self):
        if self._rename_run_id is None:
            return 0
        return sum(1 for r in writeback.renames_for_run(self.con, self._rename_run_id)
                   if r["status"] == "pending")

    def _active_pending_count(self):
        """Oczekujące AKTYWNEJ klingi. Staging jest MUTEX — najwyżej jedna niepusta, więc `or` wybiera ją."""
        return self._pending_count() or self._rename_pending_count()

    def _sync_staging_mutex(self):
        """Staging na WYŁĄCZNOŚĆ: „Do stagingu" jednej klingi disabled+tooltip, gdy druga ma pending
        (R2 #8 — stan widoczny BEZ klikania). AUTORYTATYWNY nad `btn_stage`: gdy druga klinga zwolni
        staging, re-enable wg widocznych klatek (inaczej przycisk zostałby wyszarzony). Wołane po każdej
        zmianie stagingu i w refresh() (po `set_actions_enabled`)."""
        macro_n, rename_n = self._pending_count(), self._rename_pending_count()
        has_frames = bool(self._frame_ids)
        if macro_n > 0:
            self.rename_bar.btn_stage.setEnabled(False)
            self.rename_bar.btn_stage.setToolTip(f"staging makra w toku ({macro_n} zmian)")
        else:
            self.rename_bar.btn_stage.setEnabled(has_frames)
            self.rename_bar.btn_stage.setToolTip("")
        if rename_n > 0:
            self.macro_bar.btn_stage.setEnabled(False)
            self.macro_bar.btn_stage.setToolTip(i18n.t("grid.rename.staging_busy_tip", n=rename_n))
        else:
            self.macro_bar.btn_stage.setEnabled(has_frames)
            self.macro_bar.btn_stage.setToolTip("")

    def _refresh_drawer(self):
        """Szuflada MODE-AWARE (R1 #2): pokazuje AKTYWNĄ klingę (staging mutex → najwyżej jedna niepusta).
        Rename → „N zmian nazw oczekuje" (mikro-zmiana §0); makro → domyślny. Gdy pending=0 ale „Cofnij"
        widoczny (świeży commit), NIE nadpisuj etykiety „Zatwierdzono/Przemianowano" pustostanem (D2/#2)."""
        rn = self._rename_pending_count()
        macro_n = self._pending_count()
        if rn > 0:
            self.drawer.set_count(rn, label=i18n.t("grid.drawer.pending_rename", n=rn))
        elif macro_n > 0:
            self.drawer.set_count(macro_n)
        elif self._undo_mode is None:         # brak pending i brak świeżego „Cofnij" → pustostan
            self.drawer.set_count(0)          # (sygnał stanu, NIE isVisible() — zawodne bez show())
        # else: undo oferowany (`_undo_mode` ustawiony) → zachowaj etykietę „Zatwierdzono/Przemianowano"
        self._sync_staging_mutex()

    # ---- writeback off-thread (commit/undo w wątku tła; postęp + „Anuluj" w szufladzie) ----
    @property
    def _writeback_async(self):
        """Seam testowy „inline zamiast QThread" — ustawiany Z ZEWNĄTRZ na WIDOKU (cztery testy),
        a mieszkający na uchwycie. Property z getterem i SETTEREM, żeby oba zapisy trafiały w to
        samo miejsce po wydzieleniu wykonawcy (D-PD-3)."""
        return self._wb.async_ok

    @_writeback_async.setter
    def _writeback_async(self, value):
        self._wb.async_ok = value

    def _start_writeback(self, op, target_id, after_slot):
        """Odpal `op` (commit/commit_rename/undo/undo_rename) na wątku tła; postęp → szuflada, `done`
        → `after_slot` (post-processing na wątku GŁÓWNYM). Cykl wątku trzyma uchwyt `self._wb`;
        TUTAJ zostają wyłącznie rzeczy widżetowe (pasek szuflady, wygaszenie „Do stagingu")."""
        if self._wb.is_busy or self._foreign_wb:         # jeden writeback naraz (akcje i tak schowane)
            return
        self._wb_target_id = target_id
        self.drawer.begin_progress(0)
        self.macro_bar.btn_stage.setEnabled(False)       # bez nowego stagingu w biegu
        self.rename_bar.btn_stage.setEnabled(False)
        self._wb.start(op, target_id, on_progress=self._on_wb_progress, on_done=after_slot,
                       on_failed=self._on_wb_failed)

    @Slot(int, int, str, str)
    def _on_wb_progress(self, done, total, path, status):
        self.drawer.update_progress(done, total, path)

    @Slot(str, str)
    def _on_wb_failed(self, op, msg):
        self.drawer.end_progress()
        self.drawer.set_count(self._active_pending_count(), result=i18n.t("grid.wb.error", msg=msg))
        self.refresh()
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.wb.failed", op=op, msg=msg))

    def _on_wb_cancel(self):
        if self._wb.is_busy:
            self._wb.cancel()                            # rdzeń sprawdza PRZED następnym plikiem
            self.drawer.btn_cancel.setEnabled(False)
            self.status_message.emit(i18n.t("grid.wb.cancelling"))

    def _commit_summary(self, res, noun_key):
        """Podsumowanie CommitResult: „N {noun} · M zablokowanych · …" + pierwszy powód (wiz #4).
        `noun_key` = klucz frazy głównej (`grid.wb.applied`/`grid.wb.renamed`) — DANE, nie string PL."""
        parts = [i18n.t(noun_key, n=len(res.applied))]
        if res.blocked:
            parts.append(i18n.t("grid.wb.blocked", n=len(res.blocked)))
        if res.failed:
            parts.append(i18n.t("grid.wb.errors", n=len(res.failed)))
        if res.skipped:
            parts.append(i18n.t("grid.wb.skipped", n=len(res.skipped)))
        summary = " · ".join(parts)
        detail = self._first_reason(res)                 # powód, nie tylko liczba (wiz #4)
        if detail:
            summary += i18n.t("grid.wb.detail_sep", detail=detail)
        return summary

    def _on_commit(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_commit_rename()
            return
        if self._run_id is None:
            return
        self._start_writeback("commit", self._run_id, self._after_commit)

    def _after_commit(self, op, res):
        """Post-processing commitu makra (wątek główny). Anulowano → część 'pending' została w runie:
        run zostaje otwarty do dokończenia, bez „Cofnij" (zapisane siedzą w commits — undo po CLI)."""
        self.drawer.end_progress()
        summary = self._commit_summary(res, "grid.wb.applied")
        remaining = self._pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, result=summary)
        elif res.commit_id is not None and res.applied:
            summary += i18n.t("grid.wb.commit_id", id=res.commit_id)
            self._last_commit_id = res.commit_id
            self._install_undo(res.commit_id, summary, applied=len(res.applied))
            self._run_id = None                          # R#5: run domknięty commitem
        else:                                            # wszystko blocked/failed/skipped
            self.drawer.set_count(0, result=summary)
            self._run_id = None
        self.model.set_preview({})
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe wartości
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.wb.status", summary=summary))

    def _install_undo(self, commit_id, summary, applied):
        """Po udanym commicie makra szuflada oferuje jednorazowe „Cofnij" (undo całego commitu). Etykieta
        „Zatwierdzono…" zamiast pustostanu, by nie przeczyła wynikowi obok (wizytator D2)."""
        self.drawer.set_count(0, result=summary,
                              label=i18n.t("grid.wb.committed_label", n=applied, id=commit_id))
        self.drawer.set_commit_actions_visible(False)   # jedyna sensowna akcja teraz to Cofnij (#5)
        self._undo_commit_id = commit_id
        self._undo_mode = "macro"                        # dispatch współdzielonego „Cofnij" (R1 #3)
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _ensure_undo_button(self):
        """Współdzielony przycisk „Cofnij" (tworzony RAZ, stabilny handler → dispatch po `_undo_mode`;
        bez churnu connect/disconnect, który sypał RuntimeWarning — wzorzec makra)."""
        if not hasattr(self, "_undo_btn"):
            self._undo_btn = QPushButton(i18n.t("grid.action.undo"))
            self._undo_btn.clicked.connect(self._dispatch_undo)
            self.drawer.layout().addWidget(self._undo_btn)

    def _dismiss_undo(self):
        """Nowa operacja stagingu UNIEWAŻNIA „Cofnij" poprzedniego commitu (transient undo wygasa — inny
        run w toku). Chowa przycisk + zeruje `_undo_mode`, żeby leftover „Cofnij" nie dispatchował undo
        starej klingi na wierzch świeżego stagingu = osierocenie pending + zakleszczenie mutexa bez
        widocznego powodu (recenzent #1, wizytator #3). Wołane na starcie stagingu obu kling."""
        if hasattr(self, "_undo_btn"):
            self._undo_btn.setVisible(False)
        self._undo_mode = None

    def _dispatch_undo(self):
        """Współdzielony „Cofnij" woła undo AKTYWNEJ klingi wg `_undo_mode` (R1 #3, init None)."""
        if self._undo_mode == "rename":
            self._on_undo_rename(self._undo_rename_run_id)
        else:
            self._on_undo(self._undo_commit_id)

    def _on_undo(self, commit_id):
        self._start_writeback("undo", commit_id, self._after_undo)

    def _after_undo(self, op, res):
        msg = i18n.t("grid.wb.restored", n=len(res.restored))
        if res.blocked:
            msg += " · " + i18n.t("grid.wb.blocked", n=len(res.blocked))
        self.drawer.end_progress()
        self._undo_btn.setVisible(False)
        self._undo_mode = None
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self._refresh_drawer()                           # honest: odbij pending drugiej klingi (wiz #3b)
        self.status_message.emit(i18n.t("grid.wb.undo_status", msg=msg))

    def _on_reject(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_reject_rename()
            return
        if self._run_id is None:
            return
        n = self._pending_count()
        repo.clear_pending_for_run(self.con, self._run_id)
        self._run_id = None
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t("grid.wb.rejected", n=n))   # trwałe sprzężenie w szufladzie (#3)
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t("grid.wb.rejected", n=n))

    # ---- rename „Nazwy z faktów" (druga klinga plików: os.rename) ----
    def _note_preview_takeover(self, new_owner):
        """Podgląd współdzielony (jeden `_preview`, R1 #19): przejęcie przez drugą klingę zdejmuje
        pierwszy — komunikat w statusie, żeby zniknięcie nie było ciche. Wołane PRZED `set_preview`."""
        if (self._preview_owner and self._preview_owner != new_owner
                and self.model._preview_active()):
            other = (i18n.t("grid.preview.owner_macro") if self._preview_owner == "macro"
                     else i18n.t("grid.preview.owner_rename"))
            self.status_message.emit(i18n.t("grid.preview.takeover", other=other))
        self._preview_owner = new_owner

    def _rename_target_ids(self):
        """Cel wsadu renamu (D-I1): zaznaczenie jeśli niepuste, inaczej wszystkie widoczne. Zwraca
        (frame_ids, ZAMROŻONY opis celu) — opis idzie do statusu po akcji (R2 #10, cel ruchomy)."""
        rows = self._selected_data_rows()
        if rows:
            return [r["frame_id"] for r in rows], f"{len(rows)} zaznaczonych"
        return list(self._frame_ids), f"{self._n_total} widocznych"

    def _run_rename(self, ids, policy, run_id=None):
        return naming.run_rename(
            ids, targets_fn=lambda i: queries.rename_frame_targets(self.con, i),
            source=policy["source"], offset_hours=policy["offset_hours"],
            template=policy.get("template") or naming.DEFAULT_TEMPLATE,
            fallback=policy["fallback"], run_id=run_id)

    def _show_rename_preview(self, run):
        """Podgląd renamu do modelu (nazwa stara→nowa / pominięto). `RenamePreview` niesie `frame_id`
        WPROST (bez mapowania location→frame jak makro). Etykieta kolumny „nazwa →" (R1 #4)."""
        self._note_preview_takeover("rename")
        preview = {}
        for pv in run.touched:
            preview[pv.frame_id] = {"keyword": "nazwa pliku", "op": "rename",
                                    "old": os.path.basename(pv.old_path),
                                    "new": os.path.basename(pv.new_path)}
        for sk in run.skipped:
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview, label=i18n.t("grid.preview.name"))
        return len(run.touched), len(run.skipped)

    def _on_rename_preview(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_count"))
            return
        try:
            run = self._run_rename(ids, policy)
        except ValueError as e:                          # zły regex orig we wzorze (INFORMUJ)
            self.status_message.emit(i18n.t("grid.rename.error", e=e))
            return
        t, s = self._show_rename_preview(run)
        self.status_message.emit(i18n.t("grid.rename.preview_result", t=t, s=s, target=target))

    def _on_rename_stage(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_frames"))
            return
        if self._pending_count() > 0:                    # mutex: staging makra w toku
            self.status_message.emit(i18n.t("grid.rename.staging_busy"))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        # Pętla życia run_id (R1 #1 + R2 #1): run niecommitowany → clear (bezpieczne, same 'pending');
        # run skommitowany → MINTUJ NOWY (clear skasowałby wiersze 'applied' = rekordy undo).
        try:
            naming.validate_template(policy.get("template") or naming.DEFAULT_TEMPLATE)  # zły regex → stop przed mintem
        except ValueError as e:
            self.status_message.emit(i18n.t("grid.rename.error", e=e))
            return
        if self._rename_run_id is None or self._rename_run_committed:
            self._rename_run_id = uuid.uuid4().hex
            self._rename_run_committed = False
        else:
            repo.clear_renames_for_run(self.con, self._rename_run_id)
        run = self._run_rename(ids, policy, run_id=self._rename_run_id)
        for p in run.touched:
            repo.stage_rename(self.con, run_id=self._rename_run_id, location_id=p.location_id,
                              old_path=p.old_path, new_path=p.new_path, expected_mtime=p.mtime)
        self._show_rename_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t(
            "grid.rename.staged", t=len(run.touched), s=len(run.skipped), target=target))

    def _on_rename_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit(i18n.t("grid.rename.preview_cleared"))

    def _on_commit_rename(self):
        run_id = self._rename_run_id
        if run_id is None:
            return
        self._start_writeback("commit_rename", run_id, self._after_commit_rename)

    def _after_commit_rename(self, op, res):
        """Post-processing commitu renamu (wątek główny). Anulowano → reszta nazw została 'pending':
        run zostaje otwarty do dokończenia, bez „Cofnij"."""
        self.drawer.end_progress()
        run_id = self._wb_target_id
        summary = self._commit_summary(res, "grid.wb.renamed")
        remaining = self._rename_pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, label=i18n.t("grid.drawer.pending_rename", n=remaining),
                                  result=summary)
        elif res.applied:                                # Cofnij TYLKO gdy coś zrobione (R2 #6)
            summary += i18n.t("grid.wb.run_id", id=run_id)   # run_id w wyniku: undo po restarcie przez CLI (R2 #7)
            self._undo_rename_run_id = run_id            # PRZECHWYĆ cel Cofnij przed re-stage (R2 #1)
            self._rename_run_committed = True
            self._install_rename_undo(run_id, summary, applied=len(res.applied))
        else:                                            # wszystko blocked/failed → run zwolniony
            self._rename_run_id = None
            self._rename_run_committed = False
            self.drawer.set_count(0, result=summary)
        self.model.set_preview({})
        self._preview_owner = None
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe ścieżki
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.rename.status_summary", summary=summary))

    def _install_rename_undo(self, run_id, summary, applied):
        """Po udanym rename szuflada oferuje „Cofnij" (undo_renames przebiegu). Lustro `_install_undo`
        makra, tryb `rename` (dispatch współdzielonego przycisku). Etykieta CZYSTA (bez 32-hex szumu);
        pełny run_id zostaje w `result`=summary jako kotwica CLI-undo po restarcie (R2 #7, wiz #6)."""
        self.drawer.set_count(0, result=summary, label=i18n.t("grid.rename.renamed_label", n=applied))
        self.drawer.set_commit_actions_visible(False)
        self._undo_mode = "rename"
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _on_undo_rename(self, run_id):
        self._start_writeback("undo_rename", run_id, self._after_undo_rename)

    def _after_undo_rename(self, op, res):
        msg = i18n.t("grid.wb.restored", n=len(res.restored))
        if res.blocked:
            msg += " · " + i18n.t("grid.wb.blocked", n=len(res.blocked))
        self.drawer.end_progress()
        self._undo_rename_run_id = None
        self._undo_mode = None
        self._rename_run_id = None
        self._rename_run_committed = False
        self._undo_btn.setVisible(False)
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.rename.undo_status", msg=msg))

    def _on_reject_rename(self):
        if self._rename_run_id is None:
            return
        n = self._rename_pending_count()
        repo.clear_renames_for_run(self.con, self._rename_run_id)
        self._rename_run_id = None
        self._rename_run_committed = False
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t("grid.rename.rejected", n=n))
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t("grid.rename.rejected", n=n))
