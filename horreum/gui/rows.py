"""Delegat wiersza DWUCZŁONOWEGO `TwoPartDelegate` (P1 polish) — warstwa WIDŻETÓW (whitelist
`test_gui_isolation`). Jeden mechanizm zamyka trzy znaleziska wizytatora o tym samym kształcie:
liczba/adnotacja doklejona do tekstu wiersza przepycha go poza szerokość listy i zlewa się z nazwą.

- F7 #F1/#F2/#F4 (listwa facetów): godziny doklejone TEKSTEM za „(n)" rodziły poziomy scrollbar
  (najdłuższy wiersz — kometa Tsuchinshan-ATLAS) i miały wagę nazwy, więc kolumny godzin nie dało
  się skanować wzrokiem.
- wiz F5 #6 (lista zadań Porządków): `n` bez wyrównania, wiersze n=0 nie do odróżnienia.
- wiz F3 #4 (panel „Pola"): liczniki pokrycia ucięte przy 1200 px.

Kontrakt: `DisplayRole` = człon PIERWSZY (nazwa — rysowany od lewej, ELIDOWANY do wolnego miejsca),
rola `SECONDARY` = człon DRUGI (liczba/godziny — rysowany od prawej, NIGDY nie elidowany). Dzięki
temu nazwa oddaje szerokość liczbie, nie odwrotnie: licznik jest ostatnią rzeczą, którą widać.

`strong` (per LISTA, nie per wiersz) mówi, czym jest człon drugi:
- `strong=True` — LICZBA JEST TREŚCIĄ (Porządki: „ile do zrobienia") → pogrubiona, w kolorze wiersza,
  więc wyszarzenie itemu (`setForeground`) gasi oba człony razem.
- `strong=False` — ADNOTACJA (godziny portfela, pokrycie pól) → tekst drugorzędny z motywu (F6 §7).

Poziomy scrollbar listy-konsumenta wyłącza WOŁAJĄCY (`ScrollBarAlwaysOff`) — bez tego Qt dalej
rozciąga viewport pod `sizeHint` najdłuższej nazwy i elizja nigdy nie dochodzi do głosu.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from horreum.gui import theme

# Rola członu drugiego. `Qt.UserRole` jest ZAJĘTA u wszystkich konsumentów (facets: (facet,value,label);
# fields: keyword; tasks: klucz stanu) — dlatego +1, nie własna baza.
SECONDARY = Qt.UserRole + 1

_GAP = 12          # odstęp nazwa↔liczba; poniżej ~8 px człony się sklejają przy wąskiej listwie
_PAD = 6           # zapas przy prawej ramce; bez niego ink „›" dotyka krawędzi (wizytator P1 #3)

# Kolor tekstu drugorzędnego z motywu (F6 §7, SPOT). Czytany NA ŻYWO w `paint` (nie wypalany w item
# jak wykluczenia facetów), więc zmiana motywu = `use_theme` + zwykły repaint — bez `refresh_theme`.
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolor członu drugiego z motywu (Qt-wolny `theme.accents`)."""
    _COLORS["secondary"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)     # init przy imporcie (QColor bez QApplication — wzorzec grid/map_view)


class TwoPartDelegate(QStyledItemDelegate):
    """Nazwa (elidowana, od lewej) + liczba/adnotacja (od prawej). `strong` → patrz docstring modułu."""

    def __init__(self, parent=None, *, strong=False):
        super().__init__(parent)
        self._strong = strong

    def _own_color(self, index, selected):
        """Czy człon drugi ma iść KOLOREM WIERSZA zamiast szarością drugorzędną? Tak, gdy kolor
        wiersza NIEsie znaczenie (wizytator P1 #1/#5):
        - wiersz zaznaczony — szarość na tle `Highlight` spada do ~1.8:1 kontrastu i licznik znika
          dokładnie tam, gdzie user wskazuje (panel „Pola" ma selekcję);
        - item z JAWNYM `ForegroundRole` — czerwień ⊖ facetów („(+325 ukryte)" to TREŚĆ: ile wróci
          po zdjęciu wykluczenia) i wyszarzenie zadań z n=0 mają objąć oba człony, nie pół wiersza;
        - `strong` — liczba jest treścią z definicji (Porządki).
        """
        return self._strong or selected or index.data(Qt.ForegroundRole) is not None

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        secondary = index.data(SECONDARY)
        secondary = "" if secondary is None else str(secondary)
        primary = opt.text
        opt.text = ""                    # tło/zaznaczenie/hover maluje STYL; oba człony rysujemy sami
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        # `SE_ItemViewItemText` zwraca PEŁNY viewport — bez zapasu ink członu drugiego dotyka ramki
        # i „›" czyta się jako ucięty (wizytator P1 #3).
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget).adjusted(0, 0, -_PAD, 0)
        if rect.width() <= 0:
            return
        # `initStyleOption` przenosi ForegroundRole itemu do palety (QPalette.Text) — dzięki temu
        # czerwień ⊖ facetów i wyszarzenie wierszy n=0 przeżywają własne rysowanie tekstu.
        selected = bool(opt.state & QStyle.State_Selected)
        text_color = opt.palette.color(QPalette.HighlightedText if selected else QPalette.Text)
        painter.save()
        sec_w = 0
        if secondary:
            sec_font = QFont(opt.font)
            sec_font.setBold(self._strong)
            sec_w = QFontMetrics(sec_font).horizontalAdvance(secondary) + _GAP
            painter.setFont(sec_font)
            painter.setPen(text_color if self._own_color(index, selected) else _COLORS["secondary"])
            painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, secondary)
        painter.setFont(opt.font)
        painter.setPen(text_color)
        prim = rect.adjusted(0, 0, -sec_w, 0)
        elided = QFontMetrics(opt.font).elidedText(primary, Qt.ElideRight, max(0, prim.width()))
        painter.drawText(prim, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()
