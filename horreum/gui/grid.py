"""Widok „Klatki" — grid nad EAV `cards` z filtrem i perspektywami (PLAN_gui_grid, KROK 3 scalenia).

READ-ONLY wobec danych (edycja/writeback = KROK 4). Doktryna §5: grid jest jedynym centrum, wszystko
inne to soczewki — ZERO modali w głównym przepływie. Warstwa widżetów (na whiteliście `test_gui_isolation`);
cała logika (silnik filtra, pivot, read-model) siedzi w Qt-wolnych `horreum.filter_engine`/`horreum.pivot`/
`horreum.gui.queries`. Model port `fitsmirror/gui/grid_model.py` (3 stany komórki + sort), bez edycji/stagingu.

Kolumny BAZOWE (warstwa interpretacji nad lustrem) + dynamiczne kolumny-keywordy z `cards`. Perspektywy =
nazwane {filtr+kolumny+grupowanie+sort} w `QSettings` + presety zaszyte (D-B). Grupowanie minimalne: nagłówki
grup po jednej kolumnie bazowej (D-D). `present` = kolumna statusu (zniknięte tłowane); Duplikaty = n_present>1.

F3 (PLAN_ux_redesign §4): pasek ZBIORU (`SelectionBar` — licznik + kryteria słowami + akcje) nad
`_PanelStack`, w którym klingi (`MacroBar`/`RenameBar`) są PANELAMI otwieranymi z akcji — widoczny
najwyżej JEDEN; przełączenie na cudzy panel czyści podgląd dotychczasowego właściciela (R#9).
"""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QObject, Qt, QSettings, QThread, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from horreum import db, filter_engine, macro as macro_mod, naming, pivot as pivot_mod, repo, writeback
from horreum.gui import queries
from horreum.gui.projection_dialog import ProjectionDialog

# Kolumny bazowe: (nagłówek, klucz). Klucze `_telescope`/`_object`/`_dt_delta` = pochodne. `_dt_delta`
# (Δh nagłówek−nazwa) liczone w `_derive` z `naming.header_dt`/`filename_dt` — `base_rows` zwraca już
# date_obs+path (zero zmian SQL). Kolumna renamu: grupowanie po Δh wykrawa homogeniczny wsad (§1).
BASE_COLS = [
    ("Ścieżka", "path"), ("Rodzaj", "kind"), ("Kamera", "camera_model"),
    ("Teleskop", "_telescope"), ("Obiekt", "_object"), ("Filtr", "filter_canon"),
    ("Δh (hdr−nazwa)", "_dt_delta"),
]
_MISSING_TEXT = "—"
_MISSING_COLOR = QColor(0x99, 0x99, 0x99)
_VANISHED_BG = QColor(0xFF, 0xE5, 0xE5)     # blady czerwony: wszystkie lokalizacje present=0
_DUP_BG = QColor(0xE5, 0xF0, 0xFF)          # blady niebieski: >1 obecna lokalizacja (Duplikaty)
_GROUP_BG = QColor(0xEE, 0xEE, 0xEE)        # tło nagłówka grupy
_TOUCHED_BG = QColor(0xE3, 0xF6, 0xE3)      # blady zielony: wiersz DOTKNIĘTY makrem (podgląd widoczny bez scrolla)
_SKIPPED_BG = QColor(0xF2, 0xF2, 0xF2)      # blady szary: wiersz POMINIĘTY przez makro (z powodem)

# Operatory filtra: etykieta → op (glif+słowo dla czytelności; regex POMINIĘTY, D-F).
OPERATORS = [
    ("= równe", "eq"), ("≠ różne", "ne"), ("> większe", "gt"), ("< mniejsze", "lt"),
    ("≥", "ge"), ("≤", "le"), ("zawiera", "contains"), ("zaczyna się", "startswith"),
    ("istnieje", "exists"), ("brak wartości", "not_exists"),
]
_NO_VALUE = {"exists", "not_exists"}

# Szum strukturalny FITS: keywordy o najwyższym pokryciu, ale bez wartości analitycznej. Spychane na dół
# listy Pól i pomijane przy domyślnym doborze kolumn (P3-6) — NIE ukrywane (user może chcieć NAXIS jako kolumnę).
STRUCT_NOISE = {"SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND", "BZERO", "BSCALE", "END",
                "XBINNING", "YBINNING", "XPIXSZ", "YPIXSZ", "PCOUNT", "GCOUNT"}

# Presety perspektyw (zaszyte): (nazwa, {filter_tree, group_by}). Kolumny domyślne dobierane z pokrycia.
PRESETS = {
    "Przegląd": {"filter": None, "group_by": None},
    "Kalibracja": {"filter": {"op": "OR", "conditions": [
        {"keyword": "IMAGETYP", "operator": "contains", "value": "dark"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "flat"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "bias"},
    ]}, "group_by": "kind"},
    "Duplikaty": {"filter": None, "group_by": None, "only_dups": True},
    "Do przeglądu": {"filter": None, "group_by": None, "only_review": True},
}


def _tel_label(row):
    return row["telescope_label"] or row["telescop_canon"] or ""


def _obj_label(row):
    return row["object_canon"] or row["object_raw"] or ""


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
    d["_telescope"] = _tel_label(row)
    d["_object"] = _obj_label(row)
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
        self._preview_label = "makro →"   # etykieta efemerycznej kolumny podglądu (klinga-zależna, R1 #4)

    def set_preview(self, preview, *, label="makro →"):
        """Podgląd klingi (doktryna §5: „grid = podgląd"): frame_id → zmiana (stara→nowa) albo
        pominięcie z powodem. Dokłada EFEMERYCZNĄ kolumnę (`label`, np. „makro →"/„nazwa →") na końcu;
        `{}`/None ją zdejmuje. `label` rozróżnia klingę (makro vs rename) w tym samym podglądzie (R1 #4)."""
        self.beginResetModel()
        self._preview = dict(preview or {})
        self._preview_label = label
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
                return BASE_COLS[section][0]
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
                return _GROUP_BG
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
                return "(pominięto)"
            if role == Qt.ForegroundRole:
                return _MISSING_COLOR
            if role == Qt.ToolTipRole:
                return f"pominięto: {pv['skipped']}"
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
                return _SKIPPED_BG if "skipped" in pv else _TOUCHED_BG
            if vanished:
                return _VANISHED_BG
            if dup:
                return _DUP_BG
            return None
        if key == "path":
            path = row.get("path") or ""
            if role == Qt.DisplayRole:
                name = os.path.basename(path) if path else "(brak lokalizacji)"
                # Prefiks „×N" PRZED nazwą (P2-2): sufiks ginął przy elizji długich ścieżek.
                return f"×{row['n_present']}  {name}" if dup else name
            if role == Qt.ToolTipRole:
                extra = "\n(zniknięta — wszystkie lokalizacje present=0)" if vanished else (
                    f"\n({row['n_present']} obecnych lokalizacji)" if dup else "")
                return (path or "(brak lokalizacji)") + extra
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
                return _MISSING_COLOR
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
        top.addWidget(QLabel("Łącz:")); top.addWidget(self.combo_op)
        btn_add = QPushButton("+ warunek"); btn_add.clicked.connect(self.add_row); top.addWidget(btn_add)
        self.chk_invert = QCheckBox("Odwróć: pokaż wszystko POZA filtrem")
        top.addWidget(self.chk_invert)
        btn_apply = QPushButton("Zastosuj"); btn_apply.clicked.connect(self._apply); top.addWidget(btn_apply)
        btn_clear = QPushButton("Wyczyść"); btn_clear.clicked.connect(self._clear); top.addWidget(btn_clear)
        top.addStretch(1)
        outer.addLayout(top)
        self._rows_box = QVBoxLayout(); outer.addLayout(self._rows_box)
        self.add_row()   # jeden pusty wiersz domyślnie — pierwszy filtr bez „+ warunek" (P3-4)

    def add_row(self):
        rw = QHBoxLayout()
        kw = QComboBox(); kw.setEditable(True); kw.addItems(self._keywords)
        op = QComboBox()
        for label, _ in OPERATORS:
            op.addItem(label)
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
    `columnsChanged(list[str])`. Integruje wybór kolumn i pokrycie w JEDNYM panelu (bez modalu Pokrycie)."""

    columnsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(QLabel("Pola (kolumny)"))
        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_changed)
        outer.addWidget(self.list)
        self._loading = False

    def load(self, facets, checked):
        """facets: wiersze (keyword, n). checked: set[str] zaznaczonych."""
        self._loading = True
        try:
            self.list.clear()
            for f in facets:
                kw, n = f["keyword"], f["n"]
                it = QListWidgetItem(f"{kw}   ({n})")
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
        comp.addWidget(QLabel("Oblicz:"))
        self.comp_name = QLineEdit(); self.comp_name.setPlaceholderText("nazwa (opc.)")
        self.comp_name.setFixedWidth(120)
        self.comp_expr = QLineEdit(); self.comp_expr.setPlaceholderText("wyrażenie, np. FOCALLEN / FOCRATIO")
        comp.addWidget(self.comp_name); comp.addWidget(QLabel("=")); comp.addWidget(self.comp_expr, 1)
        b.addLayout(comp)
        # Przypisz (keyword op wartość)
        asg = QHBoxLayout()
        asg.addWidget(QLabel("Przypisz:"))
        self.asg_kw = QComboBox(); self.asg_kw.setEditable(True); self.asg_kw.addItems(keywords)
        self.asg_kw.setFixedWidth(160)
        self.asg_op = QComboBox(); self.asg_op.addItems(["set", "add"])
        self.asg_expr = QLineEdit(); self.asg_expr.setPlaceholderText("wartość lub wyrażenie, np. round(new, 2)")
        asg.addWidget(self.asg_kw); asg.addWidget(self.asg_op); asg.addWidget(QLabel("=")); asg.addWidget(self.asg_expr, 1)
        b.addLayout(asg)
        # akcje
        act = QHBoxLayout()
        self.btn_prev = QPushButton("Podgląd"); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton("Do stagingu"); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton("Wyczyść podgląd"); btn_clear.clicked.connect(lambda: self.cleared.emit())
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
        pol.addWidget(QLabel("Źródło:"))
        self.src = QComboBox()
        self.src.addItem("DATE-OBS", "date_obs")          # D2: default DATE-OBS
        self.src.addItem("nazwa pliku", "filename")
        self.src.currentIndexChanged.connect(lambda *_: self.sourceChanged.emit())
        pol.addWidget(self.src)
        pol.addWidget(QLabel("Offset:"))
        self.offset = QSpinBox(); self.offset.setRange(-24, 24); self.offset.setValue(0)
        self.offset.setSuffix(" h")                       # BEZ założenia strefy (§2): 0 default
        pol.addWidget(self.offset)
        self.fallback = QCheckBox("Fallback na drugie źródło"); self.fallback.setChecked(True)  # D1
        pol.addWidget(self.fallback)
        pol.addStretch(1)
        self.target_lbl = QLabel("")                      # żywa etykieta celu (R1 #18)
        self.target_lbl.setStyleSheet("color: #666;")
        pol.addWidget(self.target_lbl)
        b.addLayout(pol)

        # (2) panel inspekcji daty (G1 — zarezerwowana powierzchnia; G4 — pełne timestampy)
        grid = QGridLayout(); grid.setContentsMargins(0, 2, 0, 2)
        self.lbl_primary = QLabel("—"); self.lbl_secondary = QLabel("—")
        self.lbl_delta = QLabel(""); self.lbl_flag = QLabel("")
        self.lbl_flag.setStyleSheet("color: #b00;")
        self.btn_align = QPushButton("Wyrównaj do drugiego źródła"); self.btn_align.setEnabled(False)
        self.btn_align.clicked.connect(self._align)
        grid.addWidget(self.lbl_primary, 0, 0); grid.addWidget(self.lbl_secondary, 0, 1)
        grid.addWidget(self.lbl_delta, 1, 0); grid.addWidget(self.lbl_flag, 1, 1)
        b.addLayout(grid)
        align_row = QHBoxLayout()                        # „Wyrównaj" = szerokość treści (pomocnik NIE
        align_row.addWidget(self.btn_align); align_row.addStretch(1)   # dominuje akcji głównych — wiz #5)
        b.addLayout(align_row)

        # (3) akcje (bliźniaczo do makra)
        act = QHBoxLayout()
        self.btn_prev = QPushButton("Podgląd"); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton("Do stagingu"); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton("Wyczyść podgląd"); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    # ---- stan / API ----
    def source(self):
        return self.src.currentData()

    def policy(self):
        return {"source": self.src.currentData(), "offset_hours": self.offset.value(),
                "fallback": self.fallback.isChecked()}

    def set_actions_enabled(self, on):
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_target_label(self, text):
        self.target_lbl.setText(text)

    def set_echo(self, primary, secondary, delta, flag, *, median=None, spread=None):
        """Wypełnij panel daty (FramesView liczy z zaznaczenia/widocznych). `median` (Δ w godzinach, float
        albo None) uzbraja „Wyrównaj": znak ZALEŻNY od źródła (R2 #2), wartość przez half-away (R2 #5),
        surowa mediana + rozrzut w tooltipie (R1 #16)."""
        self.lbl_primary.setText(primary); self.lbl_secondary.setText(secondary)
        self.lbl_delta.setText(delta); self.lbl_flag.setText(flag)
        self._median = median
        if median is None:
            self.btn_align.setEnabled(False)
            self.btn_align.setText("Wyrównaj do drugiego źródła")
            self.btn_align.setToolTip("")
            return
        self.btn_align.setEnabled(True)
        off = self._offset_from_median()
        other = "czasu z nazw" if self.source() == "date_obs" else "DATE-OBS"
        self.btn_align.setText(f"Wyrównaj do {other}: {off:+d} h")
        tip = f"surowa mediana Δ = {median!r} h"
        if spread is not None:
            tip += f" · rozrzut {spread:g} h"
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 4)))


class SelectionBar(QFrame):
    """Pasek ZBIORU (F3, PLAN_ux_redesign §4): licznik + kryteria słowami + akcje na zbiorze
    [Wydaj na stół…][Popraw nagłówki…][Uporządkuj nazwy plików…][★ Zapisz widok]. Przyciski paneli
    CHECKABLE — który panel otwarty widać bez klikania. Głupi widżet: FramesView łączy kliki i karmi
    etykiety (NARROW). Przyciski-panele ZAWSZE aktywne (gating checkable = pułapka
    disabled-but-checked-open, F3R#2); pusty zbiór gasi tylko „Wydaj na stół…"."""

    _PROJ_TIP = "Materializuj bieżącą perspektywę w drzewo linków/kopii (WBPP feed)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.count_label = QLabel("")
        f = QFont(); f.setBold(True); self.count_label.setFont(f)
        self.criteria_label = ElidedLabel()
        self.criteria_label.setStyleSheet("color: #666;")
        self.btn_proj = QPushButton("Wydaj na stół…")
        self.btn_proj.setToolTip(self._PROJ_TIP)
        self.btn_macro = QPushButton("Popraw nagłówki…"); self.btn_macro.setCheckable(True)
        self.btn_rename = QPushButton("Uporządkuj nazwy plików…"); self.btn_rename.setCheckable(True)
        self.btn_save = QPushButton("★ Zapisz widok")
        lay.addWidget(self.count_label); lay.addSpacing(8)
        lay.addWidget(self.criteria_label, 1)
        lay.addWidget(self.btn_proj); lay.addWidget(self.btn_macro)
        lay.addWidget(self.btn_rename); lay.addWidget(self.btn_save)

    def set_criteria(self, text):
        self.criteria_label.set_full_text(text)

    def set_have_frames(self, on):
        """Uczciwy disabled TYLKO realnej akcji na zbiorze (F3R#2): pusty zbiór gasi „Wydaj na stół…"
        (guard `_open_projection` zostaje drugą linią); „★ Zapisz widok" i panele zawsze żywe."""
        self.btn_proj.setEnabled(on)
        self.btn_proj.setToolTip(self._PROJ_TIP if on else "brak klatek w zbiorze")

    def set_active_panel(self, which):
        """Synchronizuj zaznaczenie przycisków-paneli ze stanem stacku (`None`/'macro'/'rename');
        blockSignals — to odbicie stanu, nie klik."""
        for btn, key in ((self.btn_macro, "macro"), (self.btn_rename, "rename")):
            btn.blockSignals(True)
            btn.setChecked(which == key)
            btn.blockSignals(False)


class _PanelStack(QStackedWidget):
    """Stack paneli kling (F3): sizeHint = BIEŻĄCA strona — goły QStackedWidget bierze max ze stron,
    więc otwarte makro wisiałoby w pasie wysokości renamu [skill: pyside6-desktop-layout-gotchas]."""

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
        self.label = QLabel("Poczekalnia zmian — pusta")   # słownik F3 (§4)
        self.result = QLabel(""); self.result.setStyleSheet("color: #666;")
        # Postęp writebacku renderuje się TU (nie w modalu): pasek + „Anuluj" wchodzą w miejsce
        # Zatwierdź/Odrzuć na czas commitu/undo (off-thread — GUI nie zamarza; rdzeń commituje per-plik).
        self.bar = QProgressBar(); self.bar.setVisible(False); self.bar.setMaximumWidth(220); self.bar.setTextVisible(False)
        self.btn_cancel = QPushButton("Anuluj"); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(lambda: self.cancel.emit())
        self.btn_commit = QPushButton("Zatwierdź"); self.btn_commit.clicked.connect(lambda: self.commit.emit())
        self.btn_reject = QPushButton("Odrzuć"); self.btn_reject.clicked.connect(lambda: self.reject.emit())
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
            self.dot.setText("●"); self.dot.setStyleSheet("color: #d08000;")   # U+25CF: jest w Segoe UI, paruje z „○" (wiz F3 #2)
            # `label` rozróżnia klingę też przy n>0: „N zmian nazw oczekuje" vs domyślne „N zmian
            # oczekuje" (mikro-zmiana §0; call-sites makra bez label → domyślny tekst, R1 #8).
            self.label.setText(label or f"{n} zmian oczekuje")
            if result is None:
                self.result.setText("")      # nowy staging: skasuj STALE wynik commitu/odrzucenia (wiz #7)
        else:
            self.dot.setText("○"); self.dot.setStyleSheet("color: #999;")
            # `label` nadpisuje domyślny tekst pustego stanu: po commicie „Zatwierdzono…" zamiast
            # pustostanu poczekalni (sprzeczność z wynikiem obok — wizytator D2).
            self.label.setText(label or "Poczekalnia zmian — pusta")
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


class FramesView(QWidget):
    """Widok „Klatki": panel Pól | (perspektywa + filtr + PASEK ZBIORU + panele kling + grid)
    + poczekalnia zmian (szuflada stagingu). Kontrakt montażu `MainWindow`: `__init__(con, now_fn,
    parent)`, sygnał `status_message`, `refresh()`. KROK 4: makro (druga klinga) — filtr→oblicz→
    przypisz na widocznych klatkach, staging, commit/undo. F3: klingi jako panele `_PanelStack`
    otwierane z `SelectionBar` (najwyżej jeden widoczny; R#9 w `_toggle_panel`)."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=None, parent=None):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)   # worker writebacku otwiera WŁASNE połączenie (per-wątek)
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._filter_tree = None
        self._only_dups = False
        self._only_review = False
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
        # Writeback OFF-THREAD (commit/undo nie zamrażają GUI): worker+wątek per-operacja, ślad celu
        # (run_id/commit_id) dla slotu post-processingu. `_writeback_async=False` (testy) → run() inline,
        # sygnały direct = synchronicznie, ten sam rdzeń bez QThread.
        self._wb_thread = None
        self._wb_worker = None
        self._wb_target_id = None
        self._writeback_async = True
        self._build_ui()
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
        bar.addWidget(QLabel("Perspektywa:"))
        self.combo_persp = QComboBox()
        self.combo_persp.currentIndexChanged.connect(self._on_perspective)
        bar.addWidget(self.combo_persp)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Grupuj wg:"))
        self.combo_group = QComboBox()
        self.combo_group.addItem("(bez grupowania)", None)
        for label, key in BASE_COLS:
            if key not in ("path",):
                self.combo_group.addItem(label, key)
        self.combo_group.currentIndexChanged.connect(self._on_group)
        bar.addWidget(self.combo_group)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        self.fields = FieldsPanel()
        self.fields.columnsChanged.connect(self._on_columns)
        splitter.addWidget(self.fields)

        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.filter_panel = FilterPanel([])
        self.filter_panel.filterApplied.connect(self._on_filter)
        rv.addWidget(self.filter_panel)

        # Pasek zbioru (F3): licznik + kryteria słowami + akcje; klingi jako panele w stacku niżej.
        self.sel_bar = SelectionBar()
        self.count_label = self.sel_bar.count_label      # TEN SAM QLabel (F3R#5) — `_update_count` bez zmian
        self.sel_bar.btn_proj.clicked.connect(self._open_projection)
        self.sel_bar.btn_save.clicked.connect(self._save_perspective)
        self.sel_bar.btn_macro.clicked.connect(lambda: self._toggle_panel("macro"))
        self.sel_bar.btn_rename.clicked.connect(lambda: self._toggle_panel("rename"))
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

        self.panel_stack = _PanelStack()                 # najwyżej JEDEN panel widoczny (F3)
        self.panel_stack.addWidget(self.macro_bar)
        self.panel_stack.addWidget(self.rename_bar)
        self.panel_stack.setVisible(False)               # żaden panel nie otwarty na starcie
        rv.addWidget(self.panel_stack)

        self.model = GridTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        # Debounce panelu daty: `selectionChanged` może sypać setki eventów przy zaznaczeniu wsadu
        # → przelicz echo raz, po 150 ms ciszy (R1 #15).
        self._date_timer = QTimer(self); self._date_timer.setSingleShot(True); self._date_timer.setInterval(150)
        self._date_timer.timeout.connect(self._refresh_date_echo)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection_changed())
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)   # zebra: skanowalność długich list (P3-5)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        rv.addWidget(self.table)

        self.empty = QLabel("Brak klatek dla tego filtra — zmień filtr lub perspektywę.")
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
        # perspektywy: presety + zapisane w QSettings
        self.combo_persp.blockSignals(True)
        self.combo_persp.clear()
        for name in PRESETS:
            self.combo_persp.addItem(name, ("preset", name))
        for name in self._saved_perspectives():
            self.combo_persp.addItem(f"★ {name}", ("saved", name))
        self.combo_persp.blockSignals(False)

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _saved_perspectives(self):
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            return list(json.loads(raw).keys())
        except (ValueError, TypeError):
            return []

    def _on_perspective(self):
        data = self.combo_persp.currentData()
        if not data:
            return
        kind, name = data
        spec = PRESETS.get(name) if kind == "preset" else self._load_saved(name)
        if spec is None:
            return
        self._only_dups = bool(spec.get("only_dups"))
        self._only_review = bool(spec.get("only_review"))
        self._filter_tree = spec.get("filter")
        self.filter_panel.set_tree(self._filter_tree)   # panel odbija filtr perspektywy (P3-3)
        gb = spec.get("group_by")
        idx = self.combo_group.findData(gb)
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_group.blockSignals(False)
        if "columns" in spec:
            self._columns = list(spec["columns"])
            self.fields.load(queries.keyword_facets(self.con), set(self._columns))
        self.refresh()

    def _load_saved(self, name):
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            return json.loads(raw).get(name)
        except (ValueError, TypeError):
            return None

    def _save_perspective(self):
        name, ok = QInputDialog.getText(self, "Zapisz perspektywę", "Nazwa:")
        if not ok or not name.strip():
            return
        name = name.strip()
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            store = json.loads(raw)
        except (ValueError, TypeError):
            store = {}
        store[name] = {
            "filter": self._filter_tree, "columns": self._columns,
            "group_by": self.combo_group.currentData(),
            "only_dups": self._only_dups, "only_review": self._only_review,
        }
        self._settings().setValue("grid/perspectives", json.dumps(store))
        self._load_facets()
        self.status_message.emit(f"Zapisano perspektywę „{name}”")

    def _open_projection(self):
        """Otwórz dialog projekcji dla WIDOCZNEJ perspektywy (`self._frame_ids` — po filtrach dups/review,
        to co user widzi; doktryna §5). Modal TYLKO na potwierdzenie eksportu; cała mutacja plików w
        Qt-wolnej klindze `projection` przez dialog. Pusty grid → szczery status, bez pustego dialogu."""
        if not self._frame_ids:
            self.status_message.emit("Projekcja: brak widocznych klatek")
            return
        dlg = ProjectionDialog(self.con, self._frame_ids, now_fn=self._now,
                               perspektywa=self.combo_persp.currentText(), parent=self)
        dlg.exec()

    # ---- panele kling (F3, PLAN_ux_redesign §4) ----
    def _toggle_panel(self, which):
        """Panel klingi z paska zbioru: najwyżej JEDEN widoczny. Zamknięcie zostawia podgląd
        (kolumna podglądu w gridzie to wartość sama w sobie; staging żyje w poczekalni niezależnie).
        Otwarcie/przełączenie na panel X przy podglądzie CUDZEGO właściciela czyści go WPROST
        handlerem `cleared` (R#9 — bez emitowania sygnału cudzego widżetu). SEKWENCJA otwarcia =
        kontrakt (F3R#4): strona stacku → pokaż → echo daty (guard echa musi już widzieć rename)."""
        target = self.macro_bar if which == "macro" else self.rename_bar
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

    def _rename_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.rename_bar)

    def _describe_criteria(self):
        """Opis zbioru słowami do paska: drzewo filtra (`filter_engine.describe`) + flagi perspektyw
        spoza silnika (`only_dups`/`only_review` — grid.py PRESETS), łączone „ · "."""
        parts = [filter_engine.describe(self._filter_tree)]
        if self._only_dups:
            parts.append("tylko duplikaty")
        if self._only_review:
            parts.append("tylko do przeglądu")
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
    def refresh(self):
        """Silnik filtra → zbiór frame_id → base_rows + pivot → model. Źródło prawdy = baza (bez cache)."""
        frame_ids = filter_engine.run(
            self._filter_tree,
            leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(self.con, k, kw, p1, p2),
            universe_fn=lambda: queries.all_frame_ids(self.con),
        )
        base = [_derive(r) for r in queries.base_rows(self.con, list(frame_ids))]
        if self._only_dups:
            base = [b for b in base if (b.get("n_present") or 0) > 1]
        if self._only_review:
            base = [b for b in base
                    if b.get("object_canon") is None and b.get("kind") in ("light", "master_light")]
        base_ids = [b["frame_id"] for b in base]
        self._frame_ids = base_ids     # cel makra = to, co WIDAĆ (po filtrach dups/review), doktryna §5
        keywords = list(self._columns)
        rows = queries.cards_pivot(self.con, base_ids, keywords) if (base_ids and keywords) else []
        pv = pivot_mod.build_pivot(base_ids, keywords, rows)
        self.model.set_data(base, pv, keywords, group_by=self.combo_group.currentData())
        n = len(base)
        self._n_total = n
        self._update_count()
        self.empty.setVisible(n == 0)
        self.table.setVisible(n > 0)
        self.macro_bar.set_actions_enabled(bool(base_ids))   # szczery disabled makra na pustym gridzie (#4)
        self.rename_bar.set_actions_enabled(bool(base_ids))  # bliźniaczo dla renamu
        self.sel_bar.set_have_frames(bool(base_ids))         # pusty zbiór gasi „Wydaj na stół…" (F3R#2)
        self.sel_bar.set_criteria(self._describe_criteria()) # kryteria zbioru SŁOWAMI (F3)
        self._sync_staging_mutex()                           # staging jednej klingi wyłącza „Do stagingu" drugiej
        self._refresh_date_echo()                            # panel daty odbija świeże widoczne (echo warunkowe)
        self.status_message.emit(f"Grid: {n} klatek, {len(keywords)} kolumn-keywordów")

    def _on_selection_changed(self):
        self._update_count()
        self._date_timer.start()                             # debounced echo daty (R1 #15)

    def _update_count(self):
        """Licznik = widoczne klatki + (gdy jest) zaznaczenie: „N klatek · M zaznaczonych" (wizytator G2 —
        akcja na zaznaczeniu musi potwierdzać cel). Nagłówki grup są nieselektowalne → nie liczą się.
        Odświeża też żywą etykietę celu renamu (R1 #18): zaznaczenie-first, inaczej widoczne."""
        sm = self.table.selectionModel()
        sel = len(sm.selectedRows()) if sm else 0
        txt = f"{self._n_total} klatek" + (f"  ·  {sel} zaznaczonych" if sel else "")
        self.count_label.setText(txt)
        if hasattr(self, "rename_bar"):
            self.rename_bar.set_target_label(
                f"Cel: {sel} zaznaczonych" if sel else f"Cel: {self._n_total} widocznych")

    # ---- panel inspekcji daty (G1/G4 — RenameBar) ----
    def _selected_data_rows(self):
        """Wiersze-klatki (bez markerów grup) dla zaznaczenia. Puste zaznaczenie → []."""
        sm = self.table.selectionModel()
        if sm is None:
            return []
        out = []
        for idx in sm.selectedRows():
            row = self.model._rows[idx.row()]
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
            primary = f"DATE-OBS: {h:%Y-%m-%d %H:%M:%S}" if h else "DATE-OBS: (brak)"
            secondary = f"czas z nazwy: {fn:%Y-%m-%d %H:%M:%S}" if fn else "czas z nazwy: (brak)"
            d = r.get("_dt_delta")
            if d is None:
                self.rename_bar.set_echo(primary, secondary, "Δ = —", "brak źródła czasu")
            else:
                flag = "Δ niepełnogodzinna!" if abs(d - round(d)) > 1e-9 else ""
                self.rename_bar.set_echo(primary, secondary, f"Δ (hdr−nazwa) = {d:g} h", flag)
            return
        # wsad (>1): mediana Δ + rozrzut (1 interakcja/wsad, §5b briefu-matki) + align
        deltas = [r["_dt_delta"] for r in scope if r.get("_dt_delta") is not None]
        primary = f"Wsad: {len(scope)} klatek ({len(deltas)} z obu źródeł)"
        if deltas:
            med = statistics.median(deltas)
            spread = max(deltas) - min(deltas)
            self.rename_bar.set_echo(primary, f"mediana Δ = {med:g} h · rozrzut {spread:g} h",
                                     "", "", median=med, spread=spread)
        else:
            self.rename_bar.set_echo(primary, "brak źródła czasu w wsadzie", "", "")

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
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            self.macro_bar.set_actions_enabled(bool(self._frame_ids))
            self.rename_bar.set_actions_enabled(bool(self._frame_ids))
            self.sel_bar.set_have_frames(bool(self._frame_ids))
            n = self._active_pending_count()             # mode-aware (R1 #2): makro LUB rename
            self.drawer.btn_commit.setEnabled(n > 0)
            self.drawer.btn_reject.setEnabled(n > 0)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._sync_staging_mutex()

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
            self.drawer.set_count(self._pending_count(), result=f"Błąd makra: {exc}")
            self.status_message.emit(f"Błąd makra: {exc}")
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
            self.status_message.emit("Makro: brak widocznych klatek do policzenia")
            return
        run = self._run(md)
        if run is None:
            return
        t, s = self._show_preview(run)
        self.status_message.emit(f"Podgląd makra: {t} do zapisu, {s} pominięto")

    def _on_macro_stage(self, md):
        if not self._frame_ids:
            self.status_message.emit("Makro: brak widocznych klatek")
            return
        if self._rename_pending_count() > 0:             # mutex symetryczny: staging renamu w toku
            self.status_message.emit("Makro: najpierw zatwierdź/odrzuć staging nazw")
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
        self.status_message.emit(f"Do stagingu: {len(run.touched)} zmian, {len(run.skipped)} pominięto")

    def _on_macro_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit("Podgląd makra wyczyszczony")

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
            self.macro_bar.btn_stage.setToolTip(f"staging nazw w toku ({rename_n} zmian)")
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
            self.drawer.set_count(rn, label=f"{rn} zmian nazw oczekuje")
        elif macro_n > 0:
            self.drawer.set_count(macro_n)
        elif self._undo_mode is None:         # brak pending i brak świeżego „Cofnij" → pustostan
            self.drawer.set_count(0)          # (sygnał stanu, NIE isVisible() — zawodne bez show())
        # else: undo oferowany (`_undo_mode` ustawiony) → zachowaj etykietę „Zatwierdzono/Przemianowano"
        self._sync_staging_mutex()

    # ---- writeback off-thread (commit/undo w wątku tła; postęp + „Anuluj" w szufladzie) ----
    def _start_writeback(self, op, target_id, after_slot):
        """Odpal `op` (commit/commit_rename/undo/undo_rename) na wątku tła; postęp → szuflada, `done`
        → `after_slot` (post-processing na wątku GŁÓWNYM). `_writeback_async=False` lub brak pliku
        (`:memory:`) → run() inline (sygnały direct = synchronicznie), ten sam rdzeń bez QThread."""
        if self._wb_thread is not None:                  # jeden writeback naraz (akcje i tak schowane)
            return
        self._wb_target_id = target_id
        self.drawer.begin_progress(0)
        self.macro_bar.btn_stage.setEnabled(False)       # bez nowego stagingu w biegu
        self.rename_bar.btn_stage.setEnabled(False)
        self._wb_worker = WritebackWorker(self._db_path, op, target_id, now_fn=self._now)
        self._wb_worker.progress.connect(self._on_wb_progress)
        self._wb_worker.done.connect(after_slot)
        self._wb_worker.failed.connect(self._on_wb_failed)
        if self._writeback_async and self._db_path:
            self._wb_thread = QThread(self)
            self._wb_worker.moveToThread(self._wb_thread)
            self._wb_thread.started.connect(self._wb_worker.run)
            self._wb_worker.finished.connect(self._wb_thread.quit)
            self._wb_thread.finished.connect(self._cleanup_wb_thread)
            self._wb_thread.start()
        else:
            try:
                self._wb_worker.run()                    # inline: done/progress lecą direct = synchronicznie
            finally:
                self._wb_worker = None

    def _cleanup_wb_thread(self):
        self._wb_worker.deleteLater(); self._wb_thread.deleteLater()
        self._wb_worker = None; self._wb_thread = None

    @Slot(int, int, str, str)
    def _on_wb_progress(self, done, total, path, status):
        self.drawer.update_progress(done, total, path)

    @Slot(str, str)
    def _on_wb_failed(self, op, msg):
        self.drawer.end_progress()
        self.drawer.set_count(self._active_pending_count(), result=f"BŁĄD: {msg}")
        self.refresh()
        self._refresh_drawer()
        self.status_message.emit(f"Writeback „{op}” nie powiódł się: {msg}")

    def _on_wb_cancel(self):
        if self._wb_worker is not None:
            self._wb_worker.request_cancel()             # rdzeń sprawdza PRZED następnym plikiem
            self.drawer.btn_cancel.setEnabled(False)
            self.status_message.emit("Anulowanie… (po bieżącym pliku)")

    def _commit_summary(self, res, noun):
        """Podsumowanie CommitResult: „N {noun} · M zablokowanych · …" + pierwszy powód (wiz #4)."""
        parts = [f"{len(res.applied)} {noun}"]
        if res.blocked:
            parts.append(f"{len(res.blocked)} zablokowanych")
        if res.failed:
            parts.append(f"{len(res.failed)} błędów")
        if res.skipped:
            parts.append(f"{len(res.skipped)} pominiętych")
        summary = " · ".join(parts)
        detail = self._first_reason(res)                 # powód, nie tylko liczba (wiz #4)
        if detail:
            summary += f" — {detail}"
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
        summary = self._commit_summary(res, "zapisanych")
        remaining = self._pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += f" — przerwano, {remaining} do dokończenia"
            self.drawer.set_count(remaining, result=summary)
        elif res.commit_id is not None and res.applied:
            summary += f"  (commit {res.commit_id})"
            self._last_commit_id = res.commit_id
            self._install_undo(res.commit_id, summary, applied=len(res.applied))
            self._run_id = None                          # R#5: run domknięty commitem
        else:                                            # wszystko blocked/failed/skipped
            self.drawer.set_count(0, result=summary)
            self._run_id = None
        self.model.set_preview({})
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe wartości
        self._refresh_drawer()
        self.status_message.emit(f"Writeback: {summary}")

    def _install_undo(self, commit_id, summary, applied):
        """Po udanym commicie makra szuflada oferuje jednorazowe „Cofnij" (undo całego commitu). Etykieta
        „Zatwierdzono…" zamiast pustostanu, by nie przeczyła wynikowi obok (wizytator D2)."""
        self.drawer.set_count(0, result=summary, label=f"Zatwierdzono: {applied} (commit {commit_id})")
        self.drawer.set_commit_actions_visible(False)   # jedyna sensowna akcja teraz to Cofnij (#5)
        self._undo_commit_id = commit_id
        self._undo_mode = "macro"                        # dispatch współdzielonego „Cofnij" (R1 #3)
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _ensure_undo_button(self):
        """Współdzielony przycisk „Cofnij" (tworzony RAZ, stabilny handler → dispatch po `_undo_mode`;
        bez churnu connect/disconnect, który sypał RuntimeWarning — wzorzec makra)."""
        if not hasattr(self, "_undo_btn"):
            self._undo_btn = QPushButton("Cofnij")
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
        msg = f"{len(res.restored)} przywróconych"
        if res.blocked:
            msg += f" · {len(res.blocked)} zablokowanych"
        self.drawer.end_progress()
        self._undo_btn.setVisible(False)
        self._undo_mode = None
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self._refresh_drawer()                           # honest: odbij pending drugiej klingi (wiz #3b)
        self.status_message.emit(f"Undo: {msg}")

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
        self.drawer.set_count(0, result=f"Odrzucono {n} zmian")   # trwałe sprzężenie w szufladzie (#3)
        self._sync_staging_mutex()
        self.status_message.emit(f"Odrzucono {n} zmian")

    # ---- rename „Nazwy z faktów" (druga klinga plików: os.rename) ----
    def _note_preview_takeover(self, new_owner):
        """Podgląd współdzielony (jeden `_preview`, R1 #19): przejęcie przez drugą klingę zdejmuje
        pierwszy — komunikat w statusie, żeby zniknięcie nie było ciche. Wołane PRZED `set_preview`."""
        if (self._preview_owner and self._preview_owner != new_owner
                and self.model._preview_active()):
            other = "makra" if self._preview_owner == "macro" else "nazw"
            self.status_message.emit(f"Zdjęto podgląd {other} (druga klinga)")
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
        self.model.set_preview(preview, label="nazwa →")
        return len(run.touched), len(run.skipped)

    def _on_rename_preview(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit("Rename: brak klatek do policzenia")
            return
        run = self._run_rename(ids, policy)
        t, s = self._show_rename_preview(run)
        self.status_message.emit(f"Podgląd nazw: {t} do zmiany, {s} pominięto (cel: {target})")

    def _on_rename_stage(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit("Rename: brak klatek")
            return
        if self._pending_count() > 0:                    # mutex: staging makra w toku
            self.status_message.emit("Rename: najpierw zatwierdź/odrzuć staging makra")
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        # Pętla życia run_id (R1 #1 + R2 #1): run niecommitowany → clear (bezpieczne, same 'pending');
        # run skommitowany → MINTUJ NOWY (clear skasowałby wiersze 'applied' = rekordy undo).
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
        self.status_message.emit(
            f"Do stagingu nazw: {len(run.touched)} zmian, {len(run.skipped)} pominięto (cel: {target})")

    def _on_rename_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit("Podgląd nazw wyczyszczony")

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
        summary = self._commit_summary(res, "przemianowanych")
        remaining = self._rename_pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += f" — przerwano, {remaining} do dokończenia"
            self.drawer.set_count(remaining, label=f"{remaining} zmian nazw oczekuje", result=summary)
        elif res.applied:                                # Cofnij TYLKO gdy coś zrobione (R2 #6)
            summary += f"  (run {run_id})"               # run_id w wyniku: undo po restarcie przez CLI (R2 #7)
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
        self.status_message.emit(f"Rename: {summary}")

    def _install_rename_undo(self, run_id, summary, applied):
        """Po udanym rename szuflada oferuje „Cofnij" (undo_renames przebiegu). Lustro `_install_undo`
        makra, tryb `rename` (dispatch współdzielonego przycisku). Etykieta CZYSTA (bez 32-hex szumu);
        pełny run_id zostaje w `result`=summary jako kotwica CLI-undo po restarcie (R2 #7, wiz #6)."""
        self.drawer.set_count(0, result=summary, label=f"Przemianowano: {applied}")
        self.drawer.set_commit_actions_visible(False)
        self._undo_mode = "rename"
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _on_undo_rename(self, run_id):
        self._start_writeback("undo_rename", run_id, self._after_undo_rename)

    def _after_undo_rename(self, op, res):
        msg = f"{len(res.restored)} przywróconych"
        if res.blocked:
            msg += f" · {len(res.blocked)} zablokowanych"
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
        self.status_message.emit(f"Undo nazw: {msg}")

    def _on_reject_rename(self):
        if self._rename_run_id is None:
            return
        n = self._rename_pending_count()
        repo.clear_renames_for_run(self.con, self._rename_run_id)
        self._rename_run_id = None
        self._rename_run_committed = False
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=f"Odrzucono {n} zmian nazw")
        self._sync_staging_mutex()
        self.status_message.emit(f"Odrzucono {n} zmian nazw")
