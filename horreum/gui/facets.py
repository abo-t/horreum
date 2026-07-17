"""Listwa facetów `FacetRail` (F4, PLAN_ux_redesign §5) — warstwa WIDŻETÓW (whitelist
`test_gui_isolation`). GŁUPI widżet (NARROW, wzorzec `SelectionBar`): logika cyklu/składania mieszka
w Qt-wolnym `facet_model`; FramesView karmi `set_data(counts, state)` i słucha `facetsChanged(state)`.

Pięć grup (Obiekt z szukajką, Filtr, Rodzaj, Teleskop, Noc). Interakcja: klik wartości cykluje
none→in→ex→none. Sygnał cyklu = `itemClicked` — WYŁĄCZNIE gest usera (F4R#4: selection-based
`currentItemChanged` strzelałby przy przeładowaniu list w `set_data` → reentrancja
`facetsChanged→refresh→set_data→…`); defensywnie guard `_loading` (wzorzec `FieldsPanel`).
Listy BEZ zaznaczenia Qt (`NoSelection` — `itemClicked` działa niezależnie): stan niesie ✓/⊖,
drugie równoległe podświetlenie kłamałoby. Aktywne wybory ZAWSZE renderowane (pin na górze grupy,
n=0 gdy wartość poza sibling-setem) — niewidzialny aktywny filtr łamałby UI-NIE-KŁAMIE.
Szukajka filtruje TYLKO listę obiektów (prezentacja, nie zbiór)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from horreum.gui import facet_model, theme

# (facet, tytuł grupy, czy-długa-lista) — długie (Obiekt/Noc) dostają stretch, krótkie zwarty pas.
_GROUPS = [("object", "Obiekt", True), ("filter", "Filtr", False), ("kind", "Rodzaj", False),
           ("telescope", "Teleskop", False), ("night", "Noc", True)]

# Czerwień wykluczeń ⊖ — z motywu (F6 §7, SPOT). WYPALANA w item przy `set_data`, więc zmiana
# motywu wymaga `FacetRail.refresh_theme` (repaint sam nie odświeży wypalonego foregroundu).
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory facetów z motywu (Qt-wolny `theme.facet_colors`)."""
    _COLORS.update({k: QColor(v) for k, v in theme.facet_colors(name).items()})


use_theme(theme.DEFAULT)
_SHORT_MAX_H = 72                          # ~3 wiersze; krótka grupa nie zjada pionu długim (wiz F4 #1)
_LONG_MIN_H = 140                          # ~6 wierszy; Obiekt/Noc (47/173 wartości) wygrywają pion (wiz F4 #1)
_RAIL_MIN_W = 220                          # bez poziomego scrolla tnącego liczniki „(+n ukryte)" (wiz F4 #2)


class FacetRail(QWidget):
    """Emituje `facetsChanged(dict)` — NOWY stan po kliku (cykl `facet_model.cycle`)."""

    facetsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = facet_model.empty_state()
        self._loading = False
        self._lists = {}
        self.setMinimumWidth(_RAIL_MIN_W)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        for facet, title, long_list in _GROUPS:
            lbl = QLabel(title)
            f = QFont(); f.setBold(True); lbl.setFont(f)
            outer.addWidget(lbl)
            if facet == "object":
                self.search = QLineEdit()
                self.search.setPlaceholderText("szukaj obiektu…")
                self.search.textChanged.connect(self._filter_objects)
                outer.addWidget(self.search)
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.NoSelection)
            lw.itemClicked.connect(self._on_item_clicked)
            if long_list:
                lw.setMinimumHeight(_LONG_MIN_H)
            else:
                lw.setMaximumHeight(_SHORT_MAX_H)
            self._lists[facet] = lw
            outer.addWidget(lw, 1 if long_list else 0)

    # ---- API (FramesView) ----
    def state(self):
        return self._state

    def set_data(self, counts, state, extras=None):
        """Przeładuj listy. `counts`: dict facet → list[(value, label, n)] (sibling-set per facet);
        `state` = aktualny stan (właściciel: FramesView). `extras`: opc. dict facet → {value:
        (suffix, tooltip)} — anotacja godzin portfela (F7 §8), dziś tylko facet „object". Aktywne
        wybory nieobecne w counts → PIN na górze grupy z n=0 (wartość odcięta przez INNE facety/
        advanced). Pozycja scrolla KAŻDEJ listy przeżywa przeładowanie (firsthand F4: klik wartości
        w środku długiej listy nie może odrzucać widoku na górę — user klika tę samą wartość
        ponownie w cyklu ⊖)."""
        self._loading = True
        scroll_pos = {facet: lw.verticalScrollBar().value() for facet, lw in self._lists.items()}
        try:
            self._state = state or facet_model.empty_state()
            for facet, lw in self._lists.items():
                lw.clear()
                facet_extras = (extras or {}).get(facet) or {}
                entries = list((counts or {}).get(facet) or [])
                present = {v for v, _l, _n in entries}
                grp = self._state.get(facet) or {}
                pinned = [(v, l, 0) for v, l in (grp.get("in") or []) + (grp.get("ex") or [])
                          if v not in present]
                for value, label, n in pinned + entries:
                    sel = facet_model.selection(self._state, facet, value)
                    tooltip = None
                    if sel == "ex":
                        # „(n)" przy ⊖ znaczy „ile WRÓCI po zdjęciu" (sibling-set), nie wkład do
                        # zbioru (pokazanych jest 0) — render niesie tę semantykę (F4R2#1). Godzin
                        # NIE doklejamy: obiekt wykluczony nie wnosi ich do zbioru (F7 guard, DD-render).
                        text = f"⊖ {label} (+{n} ukryte)"
                    else:
                        text = f"{'✓ ' if sel == 'in' else ''}{label} ({n})"
                        sx = facet_extras.get(value)          # sufiks/tooltip godzin (F7) — poza ⊖
                        if sx:
                            text += sx[0]
                            tooltip = sx[1]
                    it = QListWidgetItem(text)
                    it.setData(Qt.UserRole, (facet, value, label))
                    if tooltip:
                        it.setToolTip(tooltip)
                    if sel == "in":
                        f = QFont(); f.setBold(True); it.setFont(f)
                    elif sel == "ex":
                        it.setForeground(_COLORS["exclusion"])
                    lw.addItem(it)
            self._filter_objects(self.search.text())
            for facet, lw in self._lists.items():
                lw.doItemsLayout()                         # przelicz zakres scrolla PRZED restore
                lw.verticalScrollBar().setValue(scroll_pos[facet])   # setValue sam klampuje do zakresu
        finally:
            self._loading = False

    def refresh_theme(self):
        """Przemaluj wykluczenia po zmianie motywu. Kolor ⊖ jest WYPALONY w itemie przy `set_data`
        (nie czytany z modelu na żywo jak grid), więc podmiana `_COLORS` + repaint go nie odświeży —
        chodzimy po itemach i re-ustawiamy foreground wg bieżącego stanu (F6 recenzja #2)."""
        default = QBrush()                          # foreground z palety (dla nie-⊖)
        for facet, lw in self._lists.items():
            for i in range(lw.count()):
                it = lw.item(i)
                f, value, _label = it.data(Qt.UserRole)
                ex = facet_model.selection(self._state, f, value) == "ex"
                it.setForeground(_COLORS["exclusion"] if ex else default)

    # ---- interakcja ----
    def _on_item_clicked(self, item):
        if self._loading:
            return
        facet, value, label = item.data(Qt.UserRole)
        self._state = facet_model.cycle(self._state, facet, value, label)
        self.facetsChanged.emit(self._state)

    def _filter_objects(self, text):
        """Szukajka obiektów: chowa niepasujące wiersze (prezentacja; aktywne wybory ZAWSZE widoczne)."""
        needle = (text or "").strip().lower()
        lw = self._lists["object"]
        for i in range(lw.count()):
            it = lw.item(i)
            facet, value, label = it.data(Qt.UserRole)
            active = facet_model.selection(self._state, facet, value) is not None
            it.setHidden(bool(needle) and not active and needle not in str(label).lower())
