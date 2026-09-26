"""Delegat wiersza WIELOCZŁONOWEGO `TwoPartDelegate` (P1 polish) — warstwa WIDŻETÓW (whitelist
`test_gui_isolation`). Nazwa klasy została z czasów dwóch członów; trzeci doszedł w tym samym
mechanizmie, a przemianowanie ruszyłoby wszystkich wołających dla zera zmiany zachowania.
Jeden mechanizm zamyka znaleziska wizytatora o tym samym kształcie: liczba/adnotacja doklejona do
tekstu wiersza przepycha go poza szerokość listy i zlewa się z nazwą.

- F7 #F1/#F2/#F4 (listwa facetów): godziny doklejone TEKSTEM za „(n)" rodziły poziomy scrollbar
  (najdłuższy wiersz — kometa Tsuchinshan-ATLAS) i miały wagę nazwy, więc kolumny godzin nie dało
  się skanować wzrokiem.
- wiz F5 #6 (lista zadań Porządków): `n` bez wyrównania, wiersze n=0 nie do odróżnienia.
- wiz F3 #4 (panel „Pola"): liczniki pokrycia ucięte przy 1200 px.
- wiz P1 #4 (listwa facetów, RESZTKA po sklejeniu w jeden run): licznik jechał za szerokością
  ogona godzin → człon TRZECI, niżej.
- wiz P1 #6 (lista zadań): pogrubienie liczby było ustawieniem CAŁEJ listy → rola `STRONG`, niżej.
- W-5 (wizytacja 0810, kolejka przeglądu obiektu): wcięcie podwiersza było SPACJAMI w `DisplayRole`
  - jechało do schowka i do wersji EN, a przy elizji zjadało miejsce nazwie zamiast być nią wolne
  → rola `INDENT`, niżej.

Kontrakt: `DisplayRole` = człon PIERWSZY (nazwa — rysowany od lewej, ELIDOWANY do wolnego miejsca),
rola `SECONDARY` = człon DRUGI (liczba — rysowany od prawej, NIGDY nie elidowany), rola `TERTIARY`
= człon TRZECI (adnotacja — własna KOLUMNA przy prawej krawędzi, WRAZ z własnym separatorem:
„ · 12.3 h", nie „· 12.3 h"), rola `INDENT` = poziom wcięcia CZŁONU PIERWSZEGO (int, PIKSELE liczone
z metryki fontu - nigdy znak w tekście, W-5). Dzięki temu nazwa oddaje szerokość liczbie, nie
odwrotnie: licznik jest ostatnią rzeczą, którą widać. Separator należy do adnotacji, a nie do
delegata, bo to jedyny układ, w którym wiersz NAJSZERSZY rysuje się dokładnie tak jak przed
rozdzieleniem członów - wyrównanie kosztuje wtedy wyłącznie nieuniknioną cenę kolumny na wierszach
węższych (zmierzone, Segoe UI 9 pt: pas nazwy 132 px jak dotąd; dokładany `_GAP` zjadałby dodatkowe
9 px w KAŻDYM wierszu).

Człon TRZECI zamyka wiz P1 #4: gdy godziny szły w tym samym runie co „(n)", zmienna szerokość ogona
przesuwała licznik — „(301) · 60.4 h" kończyło „(n)" 108 px od prawej, a „(60) · 3.0 h" 96 px
(zmierzone na żywej pf4), więc kolumny liczb nie dało się skanować wzrokiem. Szerokość kolumny
ustala WOŁAJĄCY jednym `fit_tertiary(teksty_listy)` po przeładowaniu — mierzona z NAJSZERSZEJ treści
listy, nie z odgadniętej stałej, więc adnotacja nigdy nie przepełnia kolumny (ogon „(+n bez exptime)"
poszerza ją dla CAŁEJ listy, zamiast rozjeżdżać jeden wiersz). Bez `fit_tertiary` wiersz rysuje się
na własnej szerokości — niewyrównany, nigdy nachodzący.

`strong` mówi, czym jest człon drugi. Domyślna wartość jest PER LISTA, a rola `STRONG` nadpisuje ją
PER WIERSZ (wiz P1 #6: „0" na wierszu wyszarzonym było pogrubione mimo wyszarzenia — pogrubienie
krzyczy dokładnie tam, gdzie nie ma nic do zrobienia):
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

# Role członów. `Qt.UserRole` jest ZAJĘTA u wszystkich konsumentów (facets: (facet,value,label);
# fields: keyword; tasks: klucz stanu) — dlatego +1…+3, nie własna baza.
SECONDARY = Qt.UserRole + 1
TERTIARY = Qt.UserRole + 2     # adnotacja w KOLUMNIE (godziny portfela) — szerokość z `fit_tertiary`
STRONG = Qt.UserRole + 3       # nadpisuje `strong` listy dla TEGO wiersza (None → wartość listy)
# `+4`/`+5` NIE SĄ WOLNE mimo że MODUŁ ich nie używa: na listach, które i tak biorą ten delegat,
# siedzi tam CUDZA dana per-item - `facets._TIP_BASE` (+4, baza szukajki) i `app._REVIEW_PAYLOAD`/
# `_REVIEW_INFO` (+4/+5, dispatch kolejki przeglądu). `paint` czytałby ją jako poziom wcięcia, gdyby
# czwarta rola modułu wylądowała na którymkolwiek z tych numerów (W-5) - stąd +6, PIERWSZY numer
# wolny na przeglądzie WSZYSTKICH konsumentów delegata (`grep -rn "UserRole\|TwoPartDelegate"
# horreum/gui`, 2026-09-26: nikt nie sięga dalej niż +5). Powtórz ten grep, zanim dodasz kolejną
# rolę tutaj - pasmo modułu to zbiór {+1, +2, +3, +6}, nie przedział ciągły.
INDENT = Qt.UserRole + 6      # poziom wcięcia (int; 0/None = brak) - px liczy `_indent_px` z fontu

_GAP = 12          # odstęp nazwa↔liczba; poniżej ~8 px człony się sklejają przy wąskiej listwie
_PAD = 6           # zapas przy prawej ramce; bez niego ink „›" dotyka krawędzi (wizytator P1 #3)
_INDENT_UNIT_SPACES = 8    # PARYTET z dawnym tekstowym `app._WCIECIE` (W-5) - patrz `_indent_px`

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
        self._tertiary_w = 0            # szerokość kolumny adnotacji (0 = lista bez trzeciego członu)

    def _is_strong(self, index):
        """Czy człon drugi TEGO wiersza jest treścią? Rola `STRONG` bije domyślną wartość listy —
        wiersz bez roboty (Porządki, n=0) gasi pogrubienie razem z wyszarzeniem (wiz P1 #6)."""
        own = index.data(STRONG)
        return self._strong if own is None else bool(own)

    def _indent_px(self, index, font):
        """Px JEDNEGO poziomu wcięcia (rola `INDENT`; brak/0 → 0) w METRYCE fontu WIERSZA - skaluje
        się z DPI i rozmiarem czcionki zamiast być stałą (W-5). Jednostka to PARYTET z dawnym
        tekstowym wcięciem `app._WCIECIE` (8 spacji): ta sama miara na tym samym foncie daje tę samą
        szerokość, więc x startu nazwy nie rusza się względem stanu SPRZED zmiany (zmierzone przed/po
        w `tests/test_gui_app_object.py`)."""
        level = index.data(INDENT) or 0
        if not level:
            return 0
        return QFontMetrics(font).horizontalAdvance(" " * (_INDENT_UNIT_SPACES * int(level)))

    def primary_rect(self, rect, index, font):
        """Prostokąt CZŁONU PIERWSZEGO (nazwa) po odjęciu wcięcia - WYŁĄCZNIE lewa krawędź; prawą
        (miejsce zajęte przez człon drugi/trzeci) liczy `paint` osobno przez `tail`. Czysta funkcja
        geometrii (bez paintera/stylu), żeby test zmierzył x startu nazwy bez odpalania `paint` na
        realnym obrazie (W-5)."""
        return rect.adjusted(self._indent_px(index, font), 0, 0, 0)

    def fit_tertiary(self, texts):
        """Ustal szerokość KOLUMNY trzeciego członu na najszerszej adnotacji listy (wiz P1 #4).
        Woła konsument PO przeładowaniu itemów, raz na listę — dzięki temu liczby („(n)") mają stały
        prawy brzeg niezależnie od tego, ile cyfr ma ogon godzin. Mierzymy fontem WIDŻETU z `bold`
        listy: człon drugi i trzeci rysują się `sec_font`em, który wymusza `setBold(strong)` także na
        wierszach z własnym pogrubieniem (facety: aktywny wybór ✓) — pomiar jest więc dokładny, nie
        przybliżony. Pusta lista adnotacji → 0 (kolumna znika, układ wraca do dwuczłonowego)."""
        widget = self.parent()
        font = QFont(widget.font() if widget is not None else QFont())
        font.setBold(self._strong)
        fm = QFontMetrics(font)
        self._tertiary_w = max((fm.horizontalAdvance(t) for t in texts if t), default=0)
        return self._tertiary_w

    def _own_color(self, index, selected):
        """Czy człon drugi ma iść KOLOREM WIERSZA zamiast szarością drugorzędną? Tak, gdy kolor
        wiersza NIEsie znaczenie (wizytator P1 #1/#5):
        - wiersz zaznaczony — szarość na tle `Highlight` spada do ~1.8:1 kontrastu i licznik znika
          dokładnie tam, gdzie user wskazuje (panel „Pola" ma selekcję);
        - item z JAWNYM `ForegroundRole` — czerwień ⊖ facetów („(+325 ukryte)" to TREŚĆ: ile wróci
          po zdjęciu wykluczenia) i wyszarzenie zadań z n=0 mają objąć oba człony, nie pół wiersza;
        - `strong` — liczba jest treścią z definicji (Porządki).
        """
        return self._is_strong(index) or selected or index.data(Qt.ForegroundRole) is not None

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        secondary = index.data(SECONDARY)
        secondary = "" if secondary is None else str(secondary)
        tertiary = index.data(TERTIARY)
        tertiary = "" if tertiary is None else str(tertiary)
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
        # Człony prawe zjadają miejsce od prawej krawędzi: najpierw KOLUMNA adnotacji (trzeci),
        # potem liczba (drugi). `tail` = ile px już zajęte — nazwa dostaje resztę.
        tail = 0
        if secondary or tertiary:
            sec_font = QFont(opt.font)
            sec_font.setBold(self._is_strong(index))
            fm = QFontMetrics(sec_font)
            painter.setFont(sec_font)
            painter.setPen(text_color if self._own_color(index, selected) else _COLORS["secondary"])
            # Kolumna adnotacji: `fit_tertiary` (wołane przez konsumenta) daje wspólną szerokość dla
            # CAŁEJ listy — dopiero to ustawia liczby w kolumnę. Bez niego wiersz bierze własną
            # szerokość: niewyrównany, ale NIGDY nachodzący na liczbę.
            col = max(self._tertiary_w, fm.horizontalAdvance(tertiary)) if tertiary else self._tertiary_w
            if tertiary:
                painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, tertiary)
            tail = col                          # separator siedzi W adnotacji — patrz docstring modułu
            if secondary:
                painter.drawText(rect.adjusted(0, 0, -tail, 0), Qt.AlignRight | Qt.AlignVCenter, secondary)
                tail += fm.horizontalAdvance(secondary) + _GAP
        painter.setFont(opt.font)
        painter.setPen(text_color)
        prim = self.primary_rect(rect, index, opt.font).adjusted(0, 0, -tail, 0)
        elided = QFontMetrics(opt.font).elidedText(primary, Qt.ElideRight, max(0, prim.width()))
        painter.drawText(prim, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()
