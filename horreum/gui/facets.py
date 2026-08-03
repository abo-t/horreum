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
Szukajka filtruje TYLKO listę obiektów (prezentacja, nie zbiór).

Wiersz jest TRÓJCZŁONOWY (`rows.TwoPartDelegate`, P1): nazwa od lewej (elidowana), licznik i godziny
portfela od prawej jako tekst drugorzędny — każde we WŁASNEJ kolumnie. Wcześniej godziny szły TEKSTEM
za „(n)" — najdłuższy wiersz przepychał listwę przez 220 px w poziomy scrollbar i „1.5 h" bywało
ucięte (wiz F7 #F1), kolumna godzin była nieskanowalna (#F2) i miała wagę nazwy (#F4). Po sklejeniu
ich w jeden run członu drugiego został ostatni rozjazd: liczba jechała za zmienną szerokością godzin
(wiz P1 #4) — dlatego godziny mają dziś rolę `rows.TERTIARY` i wspólną szerokość z `fit_tertiary`."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from horreum.gui import facet_model, i18n, rows, theme
from horreum.gui.rows import TwoPartDelegate

# (facet, KLUCZ tytułu grupy, czy-długa-lista) — długie (Obiekt/Noc) dostają stretch, krótkie zwarty
# pas. Tytuł = klucz i18n rozwiązywany w budowie (nie zamrażać PL przy imporcie).
_GROUPS = [("object", "facets.group.object", True), ("filter", "facets.group.filter", False),
           ("kind", "facets.group.kind", False), ("telescope", "facets.group.telescope", False),
           ("night", "facets.group.night", True)]

# Czerwień wykluczeń ⊖ — z motywu (F6 §7, SPOT). WYPALANA w item przy `set_data`, więc zmiana
# motywu wymaga `FacetRail.refresh_theme` (repaint sam nie odświeży wypalonego foregroundu).
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory facetów z motywu (Qt-wolny `theme.facet_colors`)."""
    _COLORS.update({k: QColor(v) for k, v in theme.facet_colors(name).items()})


use_theme(theme.DEFAULT)
_SHORT_MAX_H = 72                          # ~3 wiersze; krótka grupa nie zjada pionu długim (wiz F4 #1)
_LONG_MIN_H = 140                          # ~6 wierszy; Obiekt/Noc (47/173 wartości) wygrywają pion (wiz F4 #1)
# Próg czytelności LEWEJ KOLUMNY okna (wiz F4 #2) — publiczny, bo panel „Pola" w `grid.py` dzieli
# to samo minimum (wiz F3 #4); dwie liczby rozjechałyby się przy pierwszej korekcie (SPOT).
RAIL_MIN_W = 220


class FacetRail(QWidget):
    """Emituje `facetsChanged(dict)` — NOWY stan po kliku (cykl `facet_model.cycle`)."""

    facetsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = facet_model.empty_state()
        self._loading = False
        self._lists = {}
        self._aliases = {}          # canon → {alias_norm}; dowozi `set_data` (S3)
        self.setMinimumWidth(RAIL_MIN_W)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        for facet, title, long_list in _GROUPS:
            lbl = QLabel(i18n.t(title))
            f = QFont(); f.setBold(True); lbl.setFont(f)
            outer.addWidget(lbl)
            if facet == "object":
                self.search = QLineEdit()
                self.search.setPlaceholderText(i18n.t("facets.search_object"))
                self.search.textChanged.connect(self._filter_objects)
                outer.addWidget(self.search)
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.NoSelection)
            # Człon drugi (licznik/godziny) do prawej kolumny; nazwa elidowana. Scrollbar poziomy OFF,
            # inaczej Qt rozciąga viewport pod `sizeHint` najdłuższej nazwy i elizja nie dochodzi
            # do głosu (wiz F7 #F1 — kometa Tsuchinshan-ATLAS tnie „1.5 h").
            lw.setItemDelegate(TwoPartDelegate(lw))
            lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lw.itemClicked.connect(self._on_item_clicked)
            # Prawy klik = ⊖ WPROST (bez menu — gest, nie polecenie). Skrót cyklu, nie druga
            # ścieżka stanu: kończy w `facet_model.toggle_exclude`, więc lewy i prawy klik dzielą
            # jedną normalizację. `CustomContextMenu` przechwytuje też klawisz menu kontekstowego.
            lw.setContextMenuPolicy(Qt.CustomContextMenu)
            lw.customContextMenuRequested.connect(
                lambda pos, w=lw: self._on_item_right_clicked(w, pos))
            # Gest bez menu jest NIEWIDOCZNY (wizytacja P-C #2: skrót 2→1 istniał wyłącznie dla
            # tego, kto czytał commit). Tooltip listy nazywa OBA kliki — jedyna afordancja, jaką
            # ma listwa bez paska narzędzi.
            lw.setToolTip(i18n.t("facets.tip.clicks"))
            if long_list:
                lw.setMinimumHeight(_LONG_MIN_H)
            else:
                lw.setMaximumHeight(_SHORT_MAX_H)
            self._lists[facet] = lw
            outer.addWidget(lw, 1 if long_list else 0)

    # ---- API (FramesView) ----
    def state(self):
        return self._state

    def set_data(self, counts, state, extras=None, reveal=None, aliases=None):
        """Przeładuj listy. `counts`: dict facet → list[(value, label, n)] (sibling-set per facet);
        `state` = aktualny stan (właściciel: FramesView). `extras`: opc. dict facet → {value:
        (suffix, tooltip)} — anotacja godzin portfela (F7 §8), dziś tylko facet „object"; sufiks
        dokleja się do CZŁONU DRUGIEGO (`rows.SECONDARY` — prawa kolumna), nie do nazwy. Aktywne
        wybory nieobecne w counts → PIN na górze grupy z n=0 (wartość odcięta przez INNE facety/
        advanced). Pozycja scrolla KAŻDEJ listy przeżywa przeładowanie (firsthand F4: klik wartości
        w środku długiej listy nie może odrzucać widoku na górę — user klika tę samą wartość
        ponownie w cyklu ⊖).

        `reveal` = `(facet, value)` ODWRACA tę regułę dla JEDNEJ listy: zbiór przyszedł Z ZEWNĄTRZ
        (most „Pokaż klatki celu" z planera), więc nie ma pozycji scrolla do uszanowania — jest
        wybór, którego user nie widzi. Zmierzone przed poprawką: `✓ NGC7000` stało na pozycji 36/48
        przy scrollu 0, czyli poza widokiem, a listwa wyglądała jak nietknięta. Odtworzenie scrolla
        jest słuszne dla kliku W listwie i szkodliwe dla wejścia z zewnątrz — stąd jawny parametr,
        nie zgadywanie po stanie.

        `aliases` = dict `canon → {alias_norm}` (S3): DRUGIE NAZWY obiektów, po których wolno szukać.
        Jeden kwarg, a nie import rdzenia do listwy — dopasowanie liczy Qt-wolny
        `facet_model.matches_search`, bo to logika (normalizacja + reguła), a listwa jest głupim
        widżetem. Mapa TRZYMA SIĘ przez przeładowania: szukajka filtruje przy każdym wpisanym znaku,
        a `set_data` woła się przy każdym `refresh` — gdyby `None` znaczyło „wyczyść", pierwszy
        refresh po wpisaniu litery gasiłby aliasy w środku pisania. `None` znaczy więc „bez zmian",
        pusty dict — „ta baza nie ma aliasów"."""
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
                hours = []                                    # adnotacje listy → szerokość kolumny
                for value, label, n in pinned + entries:
                    sel = facet_model.selection(self._state, facet, value)
                    tooltip, third = None, ""
                    if sel == "ex":
                        # „(n)" przy ⊖ znaczy „ile WRÓCI po zdjęciu" (sibling-set), nie wkład do
                        # zbioru (pokazanych jest 0) — render niesie tę semantykę (F4R2#1). Godzin
                        # NIE doklejamy: obiekt wykluczony nie wnosi ich do zbioru (F7 guard, DD-render).
                        text, second = f"⊖ {label}", i18n.t("facets.hidden", n=n)
                    else:
                        text, second = f"{'✓ ' if sel == 'in' else ''}{label}", f"({n})"
                        sx = facet_extras.get(value)          # sufiks/tooltip godzin (F7) — poza ⊖
                        if sx:
                            # Godziny idą w CZŁON TRZECI (własna kolumna), nie doklejone do „(n)" —
                            # inaczej ich zmienna szerokość przesuwa licznik i kolumny liczb nie da
                            # się skanować (wiz P1 #4). Sufiks idzie WPROST, z własnym separatorem
                            # („ · 1.0 h") — kontrakt `rows.TERTIARY`; dzięki temu wiersz najszerszy
                            # rysuje się piksel w piksel jak przed rozdzieleniem członów.
                            third = sx[0]                     # „ · 1.0 h" — formatowanie: `portfolio`
                            tooltip = sx[1]
                    it = QListWidgetItem(text)
                    it.setData(Qt.UserRole, (facet, value, label))
                    it.setData(rows.SECONDARY, second)        # prawa kolumna (delegat, P1)
                    if third:
                        it.setData(rows.TERTIARY, third)
                        hours.append(third)
                    if tooltip:
                        it.setToolTip(tooltip)
                    if sel == "in":
                        f = QFont(); f.setBold(True); it.setFont(f)
                    elif sel == "ex":
                        it.setForeground(_COLORS["exclusion"])
                    lw.addItem(it)
                # Wspólna szerokość kolumny godzin PO wypełnieniu listy — dopiero to ustawia liczby
                # w jedną kolumnę. Grupa bez adnotacji (Filtr/Rodzaj/…) dostaje 0 = układ dwuczłonowy.
                lw.itemDelegate().fit_tertiary(hours)
            if aliases is not None:
                self._aliases = aliases
            self._filter_objects(self.search.text())
            for facet, lw in self._lists.items():
                lw.doItemsLayout()                         # przelicz zakres scrolla PRZED restore
                lw.verticalScrollBar().setValue(scroll_pos[facet])   # setValue sam klampuje do zakresu
            self._reveal(reveal)
        finally:
            self._loading = False

    def _reveal(self, reveal):
        """Przewiń listę do WSKAZANEJ wartości (wejście z zewnątrz — patrz `set_data`). Wartość
        nieobecna na liście = brak ruchu: pin aktywnego wyboru gwarantuje obecność, ale gdyby
        wołający podał wartość spoza facetu, cichy no-op jest lepszy niż skok w losowe miejsce.
        `PositionAtCenter`, nie `EnsureVisible` — wybór ma być WIDOCZNY, a nie doklejony do brzegu
        w miejscu, w którym oko go nie szuka."""
        if not reveal:
            return
        facet, value = reveal
        lw = self._lists.get(facet)
        if lw is None:
            return
        for i in range(lw.count()):
            it = lw.item(i)
            if it.data(Qt.UserRole)[1] == value:
                lw.scrollToItem(it, QAbstractItemView.PositionAtCenter)
                return

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

    def _on_item_right_clicked(self, lw, pos):
        """Prawy klik na wartości = ⊖ wprost (P-C; dotąd 2 kliki przez `in`). Klik w PUSTE miejsce
        listy jest bez skutku — gest celuje we wartość, nie w listę."""
        if self._loading:
            return
        item = lw.itemAt(pos)
        if item is None:
            return
        facet, value, label = item.data(Qt.UserRole)
        self._state = facet_model.toggle_exclude(self._state, facet, value, label)
        self.facetsChanged.emit(self._state)

    def _filter_objects(self, text):
        """Szukajka obiektów: chowa niepasujące wiersze (prezentacja; aktywne wybory ZAWSZE widoczne).

        Dopasowanie liczy `facet_model.matches_search` — normalizacja igły i siana plus DRUGIE NAZWY
        obiektu (S3). Dawne `needle not in label.lower()` porównywało surowy tekst do surowej
        etykiety, więc `M 42` nie znajdowało `M42`, a „Large Magellanic Cloud" nie znajdowało nic:
        kanon `LMC` nie ma z tą frazą ani jednej wspólnej litery."""
        lw = self._lists["object"]
        for i in range(lw.count()):
            it = lw.item(i)
            facet, value, label = it.data(Qt.UserRole)
            active = facet_model.selection(self._state, facet, value) is not None
            it.setHidden(not active and not facet_model.matches_search(text, label, self._aliases))
