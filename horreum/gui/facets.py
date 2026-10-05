"""Listwa facetów `FacetRail` (F4, PLAN_ux_redesign §5) — warstwa WIDŻETÓW (whitelist
`test_gui_isolation`). GŁUPI widżet (NARROW, wzorzec `SelectionBar`): logika cyklu/składania mieszka
w Qt-wolnym `facet_model`; FramesView karmi `set_data(counts, state)` i słucha `facetsChanged(state)`.

Sześć grup (Obiekt z szukajką, Filtr, Kanał, Rodzaj, Teleskop, Noc). Interakcja: klik wartości cykluje
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
           ("channel", "facets.group.channel", False),
           ("kind", "facets.group.kind", False), ("telescope", "facets.group.telescope", False),
           ("night", "facets.group.night", True)]

# Czerwień wykluczeń ⊖ — z motywu (F6 §7, SPOT). WYPALANA w item przy `set_data`, więc zmiana
# motywu wymaga `FacetRail.refresh_theme` (repaint sam nie odświeży wypalonego foregroundu).
_COLORS: dict[str, QColor] = {}

# WŁASNY tooltip wiersza z chwili budowy (godziny portfela, F7) — zapamiętany, bo szukajka dokleja
# nad nim zdanie o trafionym aliasie (R-S3-9) i musi mieć do czego wrócić po skasowaniu frazy.
# Rola poza pasmem `rows` (+1…+3) i poza `UserRole` (tam siedzi trójka facet/value/label).
_TIP_BASE = Qt.UserRole + 4


def use_theme(name):
    """Przeładuj kolory facetów z motywu (Qt-wolny `theme.facet_colors`)."""
    _COLORS.update({k: QColor(v) for k, v in theme.facet_colors(name).items()})
    # Wiersz stanu pustego (R-S3-5) to TEKST DRUGORZĘDNY, więc bierze rolę, która już istnieje —
    # nie własny kolor w `facet_colors`. Nowa nazwa dla tego samego odcienia byłaby drugim
    # właścicielem faktu i rozjechałaby się przy pierwszej korekcie palety (SPOT).
    _COLORS["placeholder"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)
# Sufit grupy krótkiej liczony w WIERSZACH, nie w pikselach (W-6, wizytacja 0810): stała 72 px przy
# wierszu 16 px dawała 4,375 wiersza, więc Rodzaj pokazywał połówkę `master_dark` - ucięty wiersz
# czyta się jak ostatni, a nie jak zapowiedź dalszych. Piksele liczy `FacetRail._dopasuj_sufit`
# z REALNEGO wiersza, bo jego wysokość zależy od fontu i DPI: Segoe UI 9 pt na pulpicie 16 px,
# offscreen 12 px, offscreen z fontem ×1,6 19 px - żadna stała px nie mieści całych wierszy we
# wszystkich trzech.
_SHORT_ROWS = 4                            # krótka grupa nie zjada pionu długim (wiz F4 #1)
_KROTKIE = frozenset(facet for facet, _tytul, dluga in _GROUPS if not dluga)   # z `_GROUPS` (SPOT)
_LONG_MIN_H = 140                          # ~6 wierszy; Obiekt/Noc (47/173 wartości) wygrywają pion (wiz F4 #1)
# Próg czytelności LEWEJ KOLUMNY okna (wiz F4 #2) — publiczny, bo panel „Pola" w `grid.py` dzieli
# to samo minimum (wiz F3 #4); dwie liczby rozjechałyby się przy pierwszej korekcie (SPOT).
RAIL_MIN_W = 220


def _wiersze_z_wartoscia(lw):
    """Wiersze, które NIOSĄ wartość facetu i są na liście pokazane: bez wiersza stanu pustego (brak
    `UserRole`, R-S3-5) i bez schowanych szukajką. Wspólne sito obu połówek pilnowania kadru (W-7):
    czego nie widać, tego user nie widział, a do schowanego wiersza nie ma czego przewijać."""
    for i in range(lw.count()):
        it = lw.item(i)
        dane = it.data(Qt.UserRole)
        if dane is not None and not it.isHidden():
            yield it, dane


def _widac(lw, it):
    """Wiersz choćby CZĘŚCIOWO w kadrze listy - JEDNA definicja „widać go" dla obu stron
    przeładowania: przed nim (`_widziane` - co user mógł zobaczyć) i po nim (`_dopilnuj_kadru` -
    czy jest po co przewijać). Dwie definicje rozjechałyby się dokładnie na brzegu kadru, a tam
    rozstrzyga się, czy lista ucieka spod kursora.

    Tylko PION: lista przewija się wyłącznie w pionie, a szerokość `visualItemRect` to szerokość
    TREŚCI, nie kadru (zmierzone: 1686 px przy viewporcie 258 px dla długiej nazwy)."""
    r, kadr = lw.visualItemRect(it), lw.viewport().rect()
    return r.isValid() and r.bottom() >= kadr.top() and r.top() <= kadr.bottom()


def _widziane(lw):
    """Wartości wierszy, które WIDAĆ (`_widac`) - to, co user mógł zobaczyć (W-7/FH-5)."""
    return {dane[1] for it, dane in _wiersze_z_wartoscia(lw) if _widac(lw, it)}


class FacetRail(QWidget):
    """Emituje `facetsChanged(dict)` — NOWY stan po kliku (cykl `facet_model.cycle`)."""

    facetsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = facet_model.empty_state()
        self._loading = False
        self._lists = {}
        self._aliases = {}          # canon → {alias_norm}; dowozi `set_data` (S3)
        self._alias_forms = {}      # alias_norm → brzmienie do pokazania; dowozi `set_data` (AR-45)
        # (facet, wartość) ostatniego gestu W listwie - JEDNORAZOWY: gasi go najbliższe `set_data`,
        # także gdy niczego nie przewinął (wzorzec `FramesView._reveal_facet`; W-7, `_dopilnuj_kadru`).
        self._klik = None
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
                # Skasowanie frazy kosztowało Ctrl+A+Del — trzy klawisze na cofnięcie jednego
                # gestu (R-S3-5). Natywny „×" `QLineEdit` robi to jednym kliknięciem i pojawia się
                # sam dopiero, gdy jest co czyścić.
                self.search.setClearButtonEnabled(True)
                self.search.textChanged.connect(self._filter_objects)
                # Enter = weź PIERWSZE trafienie (R-S3-6). Bez tego fraza tylko chowała wiersze,
                # a wybór i tak wymagał sięgnięcia po mysz: „wpisz nazwę i pokaż mi to" kosztowało
                # 3 interakcje zamiast 2. Precedens w repo: `grid.py` — Enter w polu wartości
                # filtra znaczy „zastosuj".
                self.search.returnPressed.connect(self._on_search_enter)
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
            self._lists[facet] = lw
            outer.addWidget(lw, 1 if long_list else 0)
            if not long_list:
                # Sufit PO wpięciu w listwę: wiersz ma się zmierzyć fontem, który lista dziedziczy
                # od rodzica, a nie tym, który miała jako sierota.
                self._dopasuj_sufit(lw)

    # ---- API (FramesView) ----
    def state(self):
        return self._state

    def set_data(self, counts, state, extras=None, reveal=None, aliases=None, alias_forms=None):
        """Przeładuj listy. `counts`: dict facet → list[(value, label, n)] (sibling-set per facet);
        `state` = aktualny stan (właściciel: FramesView). `extras`: opc. dict facet → {value:
        (suffix, tooltip)} — anotacja godzin portfela (F7 §8), dziś tylko facet „object"; sufiks
        dokleja się do CZŁONU DRUGIEGO (`rows.SECONDARY` — prawa kolumna), nie do nazwy. Aktywne
        wybory nieobecne w counts → PIN na górze grupy z n=0 (wartość odcięta przez INNE facety/
        advanced). Pozycja scrolla KAŻDEJ listy przeżywa przeładowanie (firsthand F4: klik wartości
        w środku długiej listy nie może odrzucać widoku na górę — user klika tę samą wartość
        ponownie w cyklu ⊖).

        ODTWORZONY SCROLL NIE MA PRAWA ZGUBIĆ AKTYWNEGO WYBORU (W-7 + FH-5 - jeden defekt zmierzony
        dwa razy). Wiersz wyboru potrafi w przeładowaniu zmienić miejsce, a scroll zostaje stary:
        po geście osi `✓ NGC3623` zszedł do pinu (wiersz 0), scroll wrócił na 36 i wiersz stanął na
        y −576 (firsthand 0816); po kliku `Rodzaj = unknown` spoza kadru `✓ unknown` stało na y=80
        przy viewporcie 70 px (wizytacja 0810). Dlatego po odtworzeniu scrolla `_dopilnuj_kadru`
        przywraca na środek wybór, który user WIDZIAŁ przed przeładowaniem albo właśnie KLIKNĄŁ -
        ale wyłącznie taki, który wypadł z kadru CAŁY. Wiersz widoczny choćby częściowo zostaje,
        gdzie stoi: lista przewija się per WIERSZ (scroll 36 = wiersz 36, y −576 = 36 × 16 px), więc
        dociągnięcie wiersza uciętego na brzegu przesuwa listę o cały wiersz i drugi klik cyklu ⊖
        w to samo miejsce trafiałby w sąsiada.
        Reguła mieszka tu, a nie u wołającego, bo listwa nie musi wiedzieć, który gest ją
        przeładował: ta sama reguła obejmuje gest osi obiektu, gest żywotności klatki (oba kończą
        w `FramesView.refresh`) i klik w sąsiedniej grupie.

        `reveal` = `(facet, value)` ODWRACA tę regułę dla JEDNEJ listy: zbiór przyszedł Z ZEWNĄTRZ
        (most „Pokaż klatki celu" z planera), więc nie ma pozycji scrolla do uszanowania — jest
        wybór, którego user nie widzi. Zmierzone przed poprawką: `✓ NGC7000` stało na pozycji 36/48
        przy scrollu 0, czyli poza widokiem, a listwa wyglądała jak nietknięta. Odtworzenie scrolla
        jest słuszne dla kliku W listwie i szkodliwe dla wejścia z zewnątrz — stąd jawny parametr,
        nie zgadywanie po stanie.

        `aliases` = dict `canon → {alias_norm}` (S3): DRUGIE NAZWY obiektów, po których wolno szukać.
        Jeden kwarg, a nie import rdzenia do listwy — dopasowanie liczy Qt-wolny
        `facet_model.search_hit`, bo to logika (normalizacja + reguła), a listwa jest głupim
        widżetem. Mapa TRZYMA SIĘ przez przeładowania: szukajka filtruje przy każdym wpisanym znaku,
        a `set_data` woła się przy każdym `refresh` — gdyby `None` znaczyło „wyczyść", pierwszy
        refresh po wpisaniu litery gasiłby aliasy w środku pisania. `None` znaczy więc „bez zmian",
        pusty dict - „ta baza nie ma aliasów".

        `alias_forms` = dict `alias_norm → brzmienie` (AR-45): podpowiedź trafienia aliasem mówi
        brzmieniem, które user zna („Large Magellanic Cloud”), a nie kluczem (`LARGEMAGELLANICCLOUD`).
        Wołający podaje TĘ SAMĄ mapę, którą okno „Przypisz obiekt” pokazuje aliasy
        (`assign_dialog.formy_aliasow` nad `queries.alias_header_forms`); klucz bez brzmienia zostaje
        kluczem. Dopasowanie dalej idzie po kluczu - mapa służy wyłącznie do pokazania. `None` jak
        przy `aliases`: „bez zmian"."""
        self._loading = True
        scroll_pos = {facet: lw.verticalScrollBar().value() for facet, lw in self._lists.items()}
        # Co user WIDZIAŁ - liczone PRZED `clear()`, bo po nim wierszy już nie ma (W-7/FH-5).
        widziane = {facet: _widziane(lw) for facet, lw in self._lists.items()}
        klik, self._klik = self._klik, None        # jednorazowy: gaśnie tu, także gdy nic nie przewinie
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
                    it.setData(_TIP_BASE, tooltip or "")     # baza dla doklejki szukajki (R-S3-9)
                    if sel == "in":
                        f = QFont(); f.setBold(True); it.setFont(f)
                    elif sel == "ex":
                        it.setForeground(_COLORS["exclusion"])
                    lw.addItem(it)
                # Wspólna szerokość kolumny godzin PO wypełnieniu listy — dopiero to ustawia liczby
                # w jedną kolumnę. Grupa bez adnotacji (Filtr/Rodzaj/…) dostaje 0 = układ dwuczłonowy.
                lw.itemDelegate().fit_tertiary(hours)
                # STAN PUSTY DOTYCZY KAŻDEJ GRUPY, NIE TYLKO SZUKAJKI (R-S3-5): zawężenie do
                # jednego obiektu potrafi opróżnić Filtr, Teleskop i Noc naraz — zmierzone cztery
                # nieme prostokąty w jednym widoku. Grupa „object" dostanie zaraz potem własny
                # przebieg z frazą (`_filter_objects`), który tę decyzję nadpisze.
                self._set_empty_row(lw, pusto=lw.count() == 0, fraza="")
                if facet in _KROTKIE:
                    self._dopasuj_sufit(lw)        # W-6: z wiersza, który właśnie stanął na liście
            if aliases is not None:
                self._aliases = aliases
            if alias_forms is not None:
                self._alias_forms = alias_forms
            self._filter_objects(self.search.text())
            for facet, lw in self._lists.items():
                lw.doItemsLayout()                         # przelicz zakres scrolla PRZED restore
                lw.verticalScrollBar().setValue(scroll_pos[facet])   # setValue sam klampuje do zakresu
            self._reveal(reveal)
            for facet, lw in self._lists.items():
                if not (reveal and reveal[0] == facet):   # lista odsłonięta z zewnątrz ma już swój cel
                    self._dopilnuj_kadru(facet, lw, widziane[facet], klik)
        finally:
            self._loading = False

    def _reveal(self, reveal):
        """Przewiń listę do WSKAZANEJ wartości (wejście z zewnątrz — patrz `set_data`). Wartość
        nieobecna na liście = brak ruchu: pin aktywnego wyboru gwarantuje obecność, ale gdyby
        wołający podał wartość spoza facetu, cichy no-op jest lepszy niż skok w losowe miejsce.
        `PositionAtCenter`, nie `EnsureVisible` — wybór ma być WIDOCZNY, a nie doklejony do brzegu
        w miejscu, w którym oko go nie szuka.

        CZWARTE przejście po itemach w tym module i czwarty raz ta sama bramka (R-S3-5): wiersz
        stanu pustego nie niesie wartości facetu. Bez tego członu obietnica „cichy no-op" z akapitu
        wyżej byłaby `TypeError` — a to jest publiczny seam dla wejść Z ZEWNĄTRZ (most z planera),
        czyli dokładnie ta droga, na której wołający może podać wartość spoza listy."""
        if not reveal:
            return
        facet, value = reveal
        lw = self._lists.get(facet)
        if lw is None:
            return
        for i in range(lw.count()):
            it = lw.item(i)
            dane = it.data(Qt.UserRole)
            if dane is not None and dane[1] == value:
                lw.scrollToItem(it, QAbstractItemView.PositionAtCenter)
                return

    def _dopilnuj_kadru(self, facet, lw, widziane, klik):
        """Aktywny wybór, który user WIDZIAŁ przed przeładowaniem albo właśnie KLIKNĄŁ, a który po
        nim wypadł z kadru CAŁY, wraca na środek listy (W-7 + FH-5, reguła opisana w `set_data`).
        Wołane PO odtworzeniu scrolla i po zewnętrznym `_reveal` - listę odsłoniętą z zewnątrz
        wołający pomija, ona ma już cel.

        Dwa przypadki, w tej kolejności:

        * **kliknięta wartość** jest nadal aktywna i nie widać jej wcale → środek listy. Kliknięte
          liczy się jak widziane także spoza kadru: Enter szukajki bierze PIERWSZE trafienie, a ono
          bywa nad kadrem, gdy fraza schowała wiersze powyżej;
        * **wybory widziane przed przeładowaniem** - gdy nie widać ŻADNEGO, środek listy na
          pierwszym z nich (FH-5: wybór zszedł do pinu na wierszu 0, a scroll wrócił na 36).

        WIERSZ WIDOCZNY CHOĆBY CZĘŚCIOWO = ZERO RUCHU, także ucięty na brzegu kadru. Pierwsza
        wersja dociągała wybór do kadru „w całości" i łamała kontrakt `set_data`: lista przewija się
        per WIERSZ, więc dociągnięcie wiersza uciętego na brzegu przesuwało ją o cały wiersz i drugi
        klik cyklu ⊖ w to samo miejsce trafiał w sąsiada (zmierzone: scroll 10 → 14 po kliku w ucięty
        wiersz), a lista, w której nic się nie zmieniło, uciekała po kliku w INNEJ grupie tylko
        dlatego, że jej wybór stał na brzegu. Defekty, które ta reguła zamyka (y=80 przy viewporcie
        70 px, pin na wierszu 0 przy scrollu 36, trafienie Entera nad kadrem), to wiersze w CAŁOŚCI
        poza kadrem - węższe kryterium żadnego z nich nie gubi.

        Wybór, od którego user SAM odjechał scrollem, nie był widziany i nie jest kliknięty, więc
        zostaje poza kadrem: to decyzja usera, nie defekt. Własna droga, nie `self._reveal` - tamten
        jest publicznym seamem wejść z zewnątrz i jego kontrakt pinuje test mostu z planera.
        `PositionAtCenter` z tego samego powodu co tam: wybór ma stanąć tam, gdzie oko go szuka."""
        aktywne = [(dane[1], it) for it, dane in _wiersze_z_wartoscia(lw)
                   if facet_model.selection(self._state, dane[0], dane[1]) is not None]
        for value, it in aktywne:
            if (facet, value) == klik and not _widac(lw, it):
                lw.scrollToItem(it, QAbstractItemView.PositionAtCenter)
                return
        widziane_aktywne = [it for value, it in aktywne if value in widziane or (facet, value) == klik]
        if widziane_aktywne and not any(_widac(lw, it) for it in widziane_aktywne):
            lw.scrollToItem(widziane_aktywne[0], QAbstractItemView.PositionAtCenter)

    def _dopasuj_sufit(self, lw):
        """Sufit grupy krótkiej = `_SHORT_ROWS` PEŁNYCH wierszy + ramka z obu stron (W-6).

        Wysokość wiersza daje REALNY wiersz (`sizeHintForRow` - delegat i font listy), nie stała:
        wołane przy każdym przeładowaniu, więc sufit idzie za fontem i DPI, które mogą się zmienić
        między przeładowaniami. Viewport = wysokość − 2·ramka (zmierzone: sufit 72 → viewport 70
        przy ramce 1 px). Jedna wysokość starcza na całą listę, bo pogrubienie `✓` nie zmienia
        wysokości wiersza: `FontRole` rozwiązuje się względem fontu listy, a wiersz pogrubiony ma
        tyle co zwykły (zmierzone: offscreen 12/12 px, natywnie Segoe UI 9 pt 16/16 px - sufit 66).

        Lista pusta (konstruktor - wierszy jeszcze nie ma, a `sizeHintForRow` zwraca wtedy -1) mierzy
        wiersz-sondę: wstawiony i zdjęty w tym samym przebiegu, zanim cokolwiek się narysuje."""
        wiersz = lw.sizeHintForRow(0)
        if wiersz <= 0:
            lw.addItem(QListWidgetItem("Xg"))
            wiersz = lw.sizeHintForRow(0)
            lw.takeItem(0)
        lw.setMaximumHeight(_SHORT_ROWS * wiersz + 2 * lw.frameWidth())

    def refresh_theme(self):
        """Przemaluj wykluczenia po zmianie motywu. Kolor ⊖ jest WYPALONY w itemie przy `set_data`
        (nie czytany z modelu na żywo jak grid), więc podmiana `_COLORS` + repaint go nie odświeży —
        chodzimy po itemach i re-ustawiamy foreground wg bieżącego stanu (F6 recenzja #2).

        Wiersz stanu pustego (R-S3-5) ma WŁASNY kolor z motywu i nie niesie wartości facetu, więc
        przechodzi tą samą bramką co reszta jego obsługi — brakiem danych — i dostaje odświeżony
        odcień drugorzędny. Bez tego członu zmiana motywu wywracała CAŁE okno wyjątkiem, gdy tylko
        któraś grupa była pusta; złapała to dopiero pełna bateria (`test_menu_widok_przelacza_motyw`),
        bo testy listwy nie przełączają skórki."""
        default = QBrush()                          # foreground z palety (dla nie-⊖)
        for facet, lw in self._lists.items():
            for i in range(lw.count()):
                it = lw.item(i)
                dane = it.data(Qt.UserRole)
                if dane is None:
                    it.setForeground(_COLORS["placeholder"])
                    continue
                f, value, _label = dane
                ex = facet_model.selection(self._state, f, value) == "ex"
                it.setForeground(_COLORS["exclusion"] if ex else default)

    # ---- interakcja ----
    def _on_item_clicked(self, item):
        """Klik w WARTOŚĆ cykluje facet. Wiersz bez wartości (stan pusty, R-S3-5) jest bez skutku.

        `NoItemFlags` sprawia, że Qt sam nie wyśle tu placeholdera, ale SLOT wolno zawołać skądinąd
        — i wtedy rozpakowanie `None` wywalało widżet wyjątkiem. Ta sama lekcja, co przy wierszu
        informacyjnym kolejki: brak danych rozstrzyga dispatch, nie dobra wola wołającego.

        Gest zostawia JEDNORAZOWY ślad `_klik`: przeładowanie, które sam wywoła, stawia klikniętą
        wartość w kadrze, także gdy klik przyszedł spoza niego (W-7, `_dopilnuj_kadru`)."""
        if self._loading:
            return
        dane = item.data(Qt.UserRole) if item is not None else None
        if dane is None:
            return
        facet, value, label = dane
        self._klik = (facet, value)
        self._state = facet_model.cycle(self._state, facet, value, label)
        self.facetsChanged.emit(self._state)

    def _on_search_enter(self):
        """Enter w szukajce = cykl na PIERWSZYM widocznym trafieniu (R-S3-6).

        „Pierwsze widoczne", nie „pierwsze pasujące": user patrzy na przefiltrowaną listę i to jej
        górny wiersz jest tym, co Enter ma potwierdzić. Fraza bez trafień nie robi NIC — wiersz
        stanu pustego nie niesie wartości, więc nie ma czego cyklować (i tak samo milczy klik).

        Gest kończy w `_on_item_clicked`, czyli w tej samej normalizacji, co mysz — Enter jest
        skrótem do istniejącej ścieżki stanu, nie drugą ścieżką."""
        lw = self._lists["object"]
        for i in range(lw.count()):
            it = lw.item(i)
            if not it.isHidden() and it.data(Qt.UserRole) is not None:
                self._on_item_clicked(it)
                return

    def focus_search(self):
        """Kursor w szukajkę obiektów (Ctrl+F z widoku „Zbiory", R-S3-6). Zaznacza dotychczasową
        frazę, więc drugie Ctrl+F pozwala pisać od nowa bez kasowania — zachowanie, którego user
        oczekuje po każdym innym „znajdź"."""
        self.search.setFocus()
        self.search.selectAll()

    def _on_item_right_clicked(self, lw, pos):
        """Prawy klik na wartości = ⊖ wprost (P-C; dotąd 2 kliki przez `in`). Klik w PUSTE miejsce
        listy — i w wiersz stanu pustego (R-S3-5) — jest bez skutku: gest celuje we WARTOŚĆ."""
        if self._loading:
            return
        item = lw.itemAt(pos)
        if item is None or item.data(Qt.UserRole) is None:
            return
        facet, value, label = item.data(Qt.UserRole)
        self._klik = (facet, value)                  # ten sam ślad co lewy klik (W-7)
        self._state = facet_model.toggle_exclude(self._state, facet, value, label)
        self.facetsChanged.emit(self._state)

    def _filter_objects(self, text):
        """Szukajka obiektów: chowa niepasujące wiersze (prezentacja; aktywne wybory ZAWSZE widoczne).

        Dopasowanie liczy `facet_model.search_hit` — normalizacja igły i siana plus DRUGIE NAZWY
        obiektu (S3). Dawne `needle not in label.lower()` porównywało surowy tekst do surowej
        etykiety, więc `M 42` nie znajdowało `M42`, a „Large Magellanic Cloud" nie znajdowało nic:
        kanon `LMC` nie ma z tą frazą ani jednej wspólnej litery.

        WIERSZ TRAFIONY CUDZĄ NAZWĄ MÓWI TO W TOOLTIPIE (R-S3-9): wpisujesz „Large Magellanic
        Cloud", dostajesz `LMC` i bez tego zdania nie wiesz, dlaczego pasuje. Tooltip wraca do
        wspólnego („oba kliki"), gdy wiersz trafia własną nazwą — inaczej po skasowaniu frazy
        na liście zostałyby wyjaśnienia dopasowań, których już nie ma.

        STAN PUSTY MA WŁASNY WIERSZ (R-S3-5): fraza bez trafień zostawiała cztery nieme prostokąty
        po ~180 px i nic nie mówiło, czy to brak danych, czy zbyt wąska fraza."""
        lw = self._lists["object"]
        trafione = 0
        for i in range(lw.count()):
            it = lw.item(i)
            dane = it.data(Qt.UserRole)
            if dane is None:                     # wiersz-placeholder poprzedniego przebiegu
                continue
            facet, value, label = dane
            active = facet_model.selection(self._state, facet, value) is not None
            hit = facet_model.search_hit(text, label, self._aliases)
            it.setHidden(not active and hit is None)
            trafione += 0 if it.isHidden() else 1
            # Zdanie o aliasie DOKLEJA SIĘ nad własnym tooltipem wiersza, nie zamazuje go: godziny
            # portfela (F7) i wyjaśnienie trafienia to dwie różne informacje i obie są potrzebne
            # w tym samym momencie. Po skasowaniu frazy wiersz wraca do samej bazy — pusta baza
            # znaczy „dziedzicz tooltip listy", więc `setToolTip("")` jest tu wartością, nie brakiem.
            baza = it.data(_TIP_BASE) or ""
            if hit not in (None, facet_model.HIT_LABEL):
                zdanie = i18n.t("facets.tip.alias_hit", alias=self._alias_forms.get(hit, hit))
                it.setToolTip(f"{zdanie}\n{baza}" if baza else zdanie)
            else:
                it.setToolTip(baza)
        self._set_empty_row(lw, pusto=trafione == 0, fraza=text)

    def _set_empty_row(self, lw, *, pusto, fraza):
        """Wiersz-placeholder stanu pustego — pokazany, gdy fraza nie trafiła NICZEGO (R-S3-5).

        Bez niego lista zostawała niemym prostokątem ~180 px i nie mówiła, czy obiektów nie ma,
        czy fraza jest za wąska. Wiersz NIE jest klikalny (`NoItemFlags`) i nie niesie `UserRole`,
        więc `_on_item_clicked`/`_filter_objects` same go omijają — nie potrzebuje własnej gałęzi
        w dispatchu, tylko braku danych, których dispatch wymaga.

        Trzymamy JEDEN placeholder na listę i przestawiamy mu treść; kasowanie i wstawianie na
        nowo przy każdej literze frazy szarpałoby scrollem sąsiednich wierszy."""
        istniejacy = None
        for i in range(lw.count()):
            if lw.item(i).data(Qt.UserRole) is None:
                istniejacy = lw.item(i)
                break
        if not pusto:
            if istniejacy is not None:
                lw.takeItem(lw.row(istniejacy))
            return
        tekst = i18n.t("facets.empty_search", fraza=fraza) if fraza else i18n.t("facets.empty_group")
        if istniejacy is None:
            istniejacy = QListWidgetItem()
            istniejacy.setFlags(Qt.NoItemFlags)
            lw.addItem(istniejacy)
        istniejacy.setText(tekst)
        istniejacy.setForeground(_COLORS["placeholder"])
        istniejacy.setHidden(False)
