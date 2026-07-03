"""Widok „Klatki" — grid nad EAV `cards` z filtrem i perspektywami (PLAN_gui_grid, KROK 3 scalenia).

READ-ONLY wobec danych (edycja/writeback = KROK 4). Doktryna §5: grid jest jedynym centrum, wszystko
inne to soczewki — ZERO modali w głównym przepływie. Warstwa widżetów (na whiteliście `test_gui_isolation`);
cała logika (silnik filtra, pivot, read-model) siedzi w Qt-wolnych `horreum.filter_engine`/`horreum.pivot`/
`horreum.gui.queries`. Model port `fitsmirror/gui/grid_model.py` (3 stany komórki + sort), bez edycji/stagingu.

Kolumny BAZOWE (warstwa interpretacji nad lustrem) + dynamiczne kolumny-keywordy z `cards`. Perspektywy =
nazwane {filtr+kolumny+grupowanie+sort} w `QSettings` + presety zaszyte (D-B). Grupowanie minimalne: nagłówki
grup po jednej kolumnie bazowej (D-D). `present` = kolumna statusu (zniknięte tłowane); Duplikaty = n_present>1.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QTableView, QVBoxLayout, QWidget,
)

from horreum import filter_engine, macro as macro_mod, pivot as pivot_mod, repo, writeback
from horreum.gui import queries

# Kolumny bazowe: (nagłówek, klucz). Klucze `_telescope`/`_object` = pochodne (fallback etykiety).
BASE_COLS = [
    ("Ścieżka", "path"), ("Rodzaj", "kind"), ("Kamera", "camera_model"),
    ("Teleskop", "_telescope"), ("Obiekt", "_object"), ("Filtr", "filter_canon"),
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


def _derive(row):
    """sqlite3.Row → dict z polami pochodnymi (_telescope/_object) do kolumn bazowych."""
    d = {k: row[k] for k in row.keys()}
    d["_telescope"] = _tel_label(row)
    d["_object"] = _obj_label(row)
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
        self._preview = {}       # frame_id → {'keyword','old','new'} | {'skipped': reason} (podgląd makra, KROK 4)

    def set_preview(self, preview):
        """Podgląd makra (doktryna §5: „grid = podgląd makra"): frame_id → zmiana (stara→nowa) albo
        pominięcie z powodem. Dokłada EFEMERYCZNĄ kolumnę „makro →" na końcu; `{}`/None ją zdejmuje."""
        self.beginResetModel()
        self._preview = dict(preview or {})
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
                return "makro →"
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
            v = row.get(self._col_key(col))
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
        return "(brak)" if v in (None, "") else str(v)

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
    """Minimalny builder drzewa filtra: wiersze [keyword][operator][wartość][×] + selektor AND/OR.
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

    def _remove(self, entry):
        entry["holder"].setParent(None)
        self._rows.remove(entry)

    def _clear(self):
        for e in list(self._rows):
            self._remove(e)
        self.add_row()   # zostaw pusty wiersz gotowy do następnego filtra
        self.filterApplied.emit(None)

    def set_tree(self, tree):
        """Odtwarza wiersze panelu z drzewa JEDNOPOZIOMOWEGO — synchronizuje panel z filtrem perspektywy
        (P3-3: bez tego preset ustawia filtr, a panel jest pusty → kolejny „Zastosuj" po cichu go nadpisuje).
        Głębsze zagnieżdżenie (grupa w grupie) niereprezentowalne w płaskim panelu → pusty wiersz. NIE emituje
        `filterApplied` (wołający już odświeża)."""
        for e in list(self._rows):
            self._remove(e)
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
            return None
        return {"op": self.combo_op.currentText(), "conditions": conds}

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
    """Zwijany pasek makra (doktryna §5: „makro = zwijany pasek obok filtra") — sekcje Oblicz/Przypisz.
    Emituje `preview(dict)` (policz i pokaż w gridzie, BEZ zapisu), `stage(dict)` (do szuflady),
    `cleared()`. Makro operuje na tym, co widać w gridzie (frame_ids wołającego)."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.toggle = QPushButton("▸ Makro (edycja nagłówków)")
        self.toggle.setCheckable(True)
        self.toggle.clicked.connect(self._on_toggle)
        head.addWidget(self.toggle); head.addStretch(1)
        outer.addLayout(head)

        self.body = QWidget(); self.body.setVisible(False)
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

    def _on_toggle(self, checked):
        self.body.setVisible(checked)
        self.toggle.setText(("▾ " if checked else "▸ ") + "Makro (edycja nagłówków)")

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


class StagingDrawer(QFrame):
    """Stała szuflada dolna stagingu (doktryna §5: „N zmian oczekuje · Przejrzyj · Zatwierdź · Odrzuć").
    Postęp i wynik commitu renderują się TU (nie w łańcuchu modali). Emituje `commit()`/`reject()`."""

    commit = Signal()
    reject = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.dot = QLabel("○")
        self.label = QLabel("Brak zmian oczekujących")
        self.result = QLabel(""); self.result.setStyleSheet("color: #666;")
        self.btn_commit = QPushButton("Zatwierdź"); self.btn_commit.clicked.connect(lambda: self.commit.emit())
        self.btn_reject = QPushButton("Odrzuć"); self.btn_reject.clicked.connect(lambda: self.reject.emit())
        lay.addWidget(self.dot); lay.addWidget(self.label); lay.addSpacing(8)
        lay.addWidget(self.result, 1); lay.addWidget(self.btn_commit); lay.addWidget(self.btn_reject)
        self.set_count(0)

    def set_count(self, n, *, result=None):
        self._n = n
        if n > 0:
            self.dot.setText("⬤"); self.dot.setStyleSheet("color: #d08000;")
            self.label.setText(f"{n} zmian oczekuje")
        else:
            self.dot.setText("○"); self.dot.setStyleSheet("color: #999;")
            self.label.setText("Brak zmian oczekujących")
        self.btn_commit.setEnabled(n > 0)
        self.btn_reject.setEnabled(n > 0)
        # Nowy staging (n>0) chowa ewentualny stary „Cofnij"; commit/reject znów widoczne (#5).
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
    """Widok „Klatki": panel Pól | (perspektywa + filtr + makro + grupowanie + grid) + szuflada stagingu.
    Kontrakt montażu `MainWindow`: `__init__(con, now_fn, parent)`, sygnał `status_message`, `refresh()`.
    KROK 4: makro (druga klinga) — filtr→oblicz→przypisz na widocznych klatkach, staging, commit/undo."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=None, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._filter_tree = None
        self._only_dups = False
        self._only_review = False
        self._frame_ids = []      # frame_id widoczne w gridzie (cel makra) — aktualizowane w refresh()
        self._run_id = None       # JEDEN run_id sesji makra (R#5 lifecycle: stage→commit/reject zwalnia)
        self._build_ui()
        self._load_facets()
        self.refresh()
        self._refresh_drawer()

    # ---- budowa ----
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Perspektywa:"))
        self.combo_persp = QComboBox()
        self.combo_persp.currentIndexChanged.connect(self._on_perspective)
        bar.addWidget(self.combo_persp)
        btn_save = QPushButton("Zapisz jako…"); btn_save.clicked.connect(self._save_perspective)
        bar.addWidget(btn_save)
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
        self.count_label = QLabel("")
        bar.addWidget(self.count_label)
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

        self.macro_bar = MacroBar([])
        self.macro_bar.preview.connect(self._on_macro_preview)
        self.macro_bar.stage.connect(self._on_macro_stage)
        self.macro_bar.cleared.connect(self._on_macro_clear)
        rv.addWidget(self.macro_bar)

        self.model = GridTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
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
        rv.addWidget(self.empty)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)   # stretch: grid dominuje okno (doktryna §5), pasek nie zjada połowy (P2-1)

        self.drawer = StagingDrawer()  # stała szuflada dolna stagingu (doktryna §5)
        self.drawer.commit.connect(self._on_commit)
        self.drawer.reject.connect(self._on_reject)
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
        self.filter_panel._keywords = self._all_keywords
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
        self.count_label.setText(f"{n} klatek")
        self.empty.setVisible(n == 0)
        self.table.setVisible(n > 0)
        self.macro_bar.set_actions_enabled(bool(base_ids))   # szczery disabled makra na pustym gridzie (#4)
        self.status_message.emit(f"Grid: {n} klatek, {len(keywords)} kolumn-keywordów")

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
        self.status_message.emit("Podgląd makra wyczyszczony")

    def _pending_count(self):
        if self._run_id is None:
            return 0
        return sum(1 for r in writeback.pending_for_run(self.con, self._run_id)
                   if r["status"] == "pending")

    def _refresh_drawer(self):
        self.drawer.set_count(self._pending_count())

    def _on_commit(self):
        if self._run_id is None:
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = writeback.commit(self.con, self._run_id, now=self._now())
        finally:
            QGuiApplication.restoreOverrideCursor()
        parts = [f"{len(res.applied)} zapisanych"]
        if res.blocked:
            parts.append(f"{len(res.blocked)} zablokowanych")
        if res.failed:
            parts.append(f"{len(res.failed)} błędów")
        if res.skipped:
            parts.append(f"{len(res.skipped)} pominiętych")
        summary = " · ".join(parts)
        if res.commit_id is not None and res.applied:
            summary += f"  (commit {res.commit_id})"
            self._last_commit_id = res.commit_id
            self._install_undo(res.commit_id, summary)
        else:
            self.drawer.set_count(self._pending_count(), result=summary)
        self._run_id = None                              # R#5: run domknięty commitem
        self.model.set_preview({})
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe wartości
        self._refresh_drawer()
        self.status_message.emit(f"Writeback: {summary}")

    def _install_undo(self, commit_id, summary):
        """Po udanym commicie szuflada oferuje jednorazowe „Cofnij" (undo całego commitu). Przycisk
        tworzony i podłączany RAZ (stabilny handler czyta `self._undo_commit_id`) — bez churnu
        connect/disconnect (który sypał RuntimeWarning)."""
        self.drawer.set_count(0, result=summary)
        self.drawer.set_commit_actions_visible(False)   # jedyna sensowna akcja teraz to Cofnij (#5)
        self._undo_commit_id = commit_id
        if not hasattr(self, "_undo_btn"):
            self._undo_btn = QPushButton("Cofnij")
            self._undo_btn.clicked.connect(lambda: self._on_undo(self._undo_commit_id))
            self.drawer.layout().addWidget(self._undo_btn)
        self._undo_btn.setVisible(True)

    def _on_undo(self, commit_id):
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = writeback.undo(self.con, commit_id, now=self._now())
        finally:
            QGuiApplication.restoreOverrideCursor()
        msg = f"{len(res.restored)} przywróconych"
        if res.blocked:
            msg += f" · {len(res.blocked)} zablokowanych"
        self._undo_btn.setVisible(False)
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self.status_message.emit(f"Undo: {msg}")

    def _on_reject(self):
        if self._run_id is None:
            return
        n = self._pending_count()
        repo.clear_pending_for_run(self.con, self._run_id)
        self._run_id = None
        self.model.set_preview({})
        self.drawer.set_count(0, result=f"Odrzucono {n} zmian")   # trwałe sprzężenie w szufladzie (#3)
        self.status_message.emit(f"Odrzucono {n} zmian")
