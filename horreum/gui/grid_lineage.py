"""Panel rodowodu widoku „Klatki" - `LineageBar` i teksty wierszy rodowodu oraz kalibracji.

Pokazuje wejścia stosu albo mastery kalibracji zaznaczonej klatki, powód braku (`no_object`,
`offset_unknown`), flagi świeżości i bramki gestów (`_frame_gate_reason`, `_object_gate_reason`).
Warstwa widżetów; dane z read-modelu `queries`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from horreum.gui import busy, i18n, queries
from horreum.gui.grid_model import _COLORS
from horreum.gui.grid_panels import ElidedLabel


# Sufit listy panelu rodowodu: wejść stosu bywa 190, więc lista MUSI mieć próg, za którym oddaje
# pion gridowi. Oś kalibracji ma zawsze dwa wiersze i sufit sobie zaniża do treści (`set_calibration`),
# dlatego droga stosu przywraca tę wartość WPROST — panel przełącza się w obie strony.
_LINEAGE_LIST_MAX_H = 160


class LineageBar(QWidget):
    """Panel „Rodowód" (I-2d, P-I): CO WESZŁO W TEN OBRAZ — strona `_PanelStack` otwierana z paska
    zbioru, gdy zaznaczono DOKŁADNIE JEDEN gotowy stos (`kind='master_light'`).

    Panel jest jedynym miejscem, w którym widać RÓŻNICĘ MIĘDZY FAKTEM A KANDYDATEM. Wejście
    z `history` plik zeznał o sobie sam, wejście z `harvest` przyszło ze zbioru dokładnego żniw (nazwy
    w historii pliku ↔ lighty wydania); wejście z `window` zostało WYLICZONE z okna czasu i czeka
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
        # WYBÓR NOCY stoi NAD listą, bo rządzi jej treścią (decyzja Zdzinia 0808: „noc mastera
        # + wybór innej nocy"). Widoczny WYŁĄCZNIE w trybie propozycji — przy gotowym rodowodzie
        # nie ma czego wybierać, a pusty combo nad listą faktów sugerowałby, że są alternatywą.
        self.night_row = QWidget()
        nr = QHBoxLayout(self.night_row)
        nr.setContentsMargins(0, 0, 0, 0)
        nr.addWidget(QLabel(i18n.t("grid.lin.cand.night")))
        self.combo_night = QComboBox()
        self.combo_night.currentIndexChanged.connect(self._on_night)
        nr.addWidget(self.combo_night, 1)
        lay.addWidget(self.night_row)
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
        self._nights = ()               # propozycje z rdzenia (`stacks.propose_lineage_candidates`)
        self._raw_bez_odniesienia = 0   # druga wartość tamtego zwrotu — kandydaci bez zegara
        self._note_base = ""            # nota sprzed trybu propozycji (combo jej nie zjada)
        self._warn_base = ""            # ostrzeżenie sprzed trybu propozycji (noc dokłada swoje)
        self.set_lineage(None, [])

    def set_lineage(self, head, inputs, *, hint=None, candidates=(), raw_unreferenced=0):
        """Wypełnij panel. `head` = wiersz `queries.stack_lineage_head` (albo `None`), `inputs` =
        wiersze `queries.stack_lineage_inputs`, `hint` = gotowe zdanie, gdy nie ma czego pokazać
        (złe zaznaczenie / rodowód nieliczony), `candidates` + `raw_unreferenced` = obie wartości
        zwrotu `stacks.propose_lineage_candidates`. Zero SQL i zero decyzji — sama prezentacja.

        PROPOZYCJE WCHODZĄ TYLKO W PUSTKĘ i to jest granica, nie optymalizacja: gdy stos MA wejścia,
        lista jest zapisem faktu, a doklejenie do niej ofert kazałoby odróżniać jedno od drugiego
        w tym samym oknie. Obraz z rodowodem niczego nie proponuje.

        `raw_unreferenced` PRZYCHODZI OSOBNO, BO NIESIE INNĄ RECEPTĘ NIŻ PUSTA LISTA: „kandydaci są,
        tylko nie znam zegara tego obrazu" prowadzi do gestu odniesienia, a „nie ma kandydatów" nie
        prowadzi nigdzie. Bez tej wartości panel mówił 6 obrazom kubełka, że archiwum jest puste,
        gdy stało w nim po 36 klatek (bramka pakietu 3a, 0808)."""
        self.items.clear()
        self.items.setMaximumHeight(_LINEAGE_LIST_MAX_H)   # oś kalibracji zaniża sufit do treści
        self._head = head
        # NOCE GASNĄ TU, A ZAPALAJĄ SIĘ WYŁĄCZNIE W `_set_candidates` - jedna droga w każdą stronę,
        # wzorem `_sync_visible` dla `night_row` (G2-3d). Bez tego `_nights` przeżywało wyjście
        # z trybu propozycji i licznik kandydatów mówiłby o POPRZEDNIM obrazie.
        self._nights = ()
        self._raw_bez_odniesienia = raw_unreferenced
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
        # OSTRZEŻENIE STAWIAMY OD RAZU, PRZED GAŁĘZIAMI — bo gałąź propozycji kończy się `return`
        # i pomijała ten zapis, więc panel nowego obrazu nosił ostrzeżenie POPRZEDNIEGO („⚠ obraz
        # zapisał inny teleskop niż jego klatki" o cudzym pliku). Zmierzone bramką pakietu 3a 0808;
        # etykieta była realnie widoczna, nie tylko wypełniona.
        self.warn.set_full_text(ostrz)          # `_lineage_flags` samo milczy przy pustej liście
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
            if candidates:
                self._set_candidates(candidates)
                return
        else:
            godziny = (head["secs"] or 0) / 3600.0
            self.head.setText(i18n.t_plural("grid.lin.head", head["inputs"],
                                            hours=f"{godziny:.1f}"))
            self.note.set_full_text(" · ".join(x for x in (powod, info) if x))
        # Widoczność z LISTY, nie z licznika: stos z powodem, ale z odrzuconymi wierszami, ma je
        # pokazać (i dać się cofnąć), a stos bez ani jednego wiersza nie ma zajmować pionu na listę.
        self._sync_visible(bool(inputs))

    def _set_candidates(self, nights):
        """Tryb PROPOZYCJI: noce z materiałem w combo, klatki wybranej nocy na liście.

        Otwiera się na NOCY MASTERA (pozycja 0 z rdzenia), także gdy ta noc jest pusta — bo pierwsze
        pytanie człowieka brzmi „czy program dobrze zrozumiał, o który wieczór pytam", a nie „daj mi
        cokolwiek". Przełączenie nocy NIE PYTA BAZY: rdzeń oddał wszystkie noce naraz, więc combo
        przerysowuje listę z pamięci."""
        self._nights = tuple(nights)
        self._note_base = self.note.full_text()
        self._warn_base = self.warn.full_text()
        self.combo_night.blockSignals(True)
        self.combo_night.clear()
        for n in self._nights:
            klucz = "grid.lin.cand.night_master" if n.master_night else "grid.lin.cand.night_other"
            self.combo_night.addItem(i18n.t(klucz, night=n.night, n=len(n.frames)), n.night)
        self.combo_night.setCurrentIndex(0)
        self.combo_night.blockSignals(False)
        self._fill_night(0)

    def klatki_bez_odniesienia(self):
        """Ile klatek CZEKA NA ZEGAR tego obrazu - populacja, którą gest odniesienia odblokowuje.

        To jest liczba, na którą gest realnie działa: kandydat RAW bez wskazanego odniesienia nie
        wchodzi do okna, bo nie wiadomo, do której NOCY należy (`stacks.propose_lineage_candidates`,
        druga wartość zwrotu). Zero odróżnia „zegar nie miał czego odblokować" od „materiał czekał
        i właśnie ruszył" - a dokładnie tej różnicy brakowało, gdy stos meldował potem
        `no_candidates` bez wskazania przyczyny (G2-3d).

        ⚠ CZYTAJ PRZED `_refresh_lineage()`, nigdy po. Zapis offsetu czyni powód ZWIETRZAŁYM
        (`queries.lineage_reason_stale`: dla `offset_unknown` wietrzeje, gdy `utc_offset_min`
        przestaje być NULL), więc odświeżenie po zapisie NIE liczy już propozycji i każda liczba
        wzięta z panelu po nim jest strukturalnie zerem. Bramka pakietu złapała tu człon martwy
        w chwili narodzin - liczony po odświeżeniu mówił „0" nad stosem, pod którym stało 36 klatek."""
        return self._raw_bez_odniesienia

    def _on_night(self, idx):
        if idx >= 0:
            self._fill_night(idx)

    def _fill_night(self, idx):
        """Przerysuj listę propozycji dla wybranej nocy. PUSTA NOC ZOSTAJE NA EKRANIE z własnym
        zdaniem: „ta noc nie ma materiału, ale inne mają" to inna odpowiedź niż „nie ma nic",
        a różnicę widać wyłącznie wtedy, gdy pusty wybór wolno wybrać."""
        self.items.clear()
        klatki = self._nights[idx].frames if 0 <= idx < len(self._nights) else ()
        for r in klatki:
            it = QListWidgetItem(_candidate_item_text(r))
            it.setData(Qt.UserRole, r["frame_id"])
            self.items.addItem(it)
        gdzie_indziej = sum(len(n.frames) for n in self._nights) - len(klatki)
        # TRZY RÓŻNE PUSTKI, TRZY RECEPTY — i to jest sedno naprawy z bramki 3a. „Nie ma nic"
        # i „są klatki, których nie umiem umieścić w czasie" prowadzą w zupełnie inne miejsca:
        # pierwsze donikąd, drugie wprost do gestu odniesienia (przycisk niżej sam się zapala).
        # Wspólne zdanie kłamało 6 obrazom kubełka, że archiwum jest puste, gdy stało w nim po 36.
        if klatki:
            podpowiedz = ""
        elif gdzie_indziej:
            podpowiedz = i18n.t_plural("grid.lin.cand.empty_night", gdzie_indziej)
        elif self._raw_bez_odniesienia:
            podpowiedz = i18n.t_plural("grid.lin.cand.no_reference", self._raw_bez_odniesienia)
        else:
            podpowiedz = i18n.t("grid.lin.cand.empty_all", n=0)
        self.note.set_full_text(" · ".join(x for x in (self._note_base, podpowiedz) if x))
        # ROZJAZD TELESKOPU NOCY (B3a-2) - to samo zdanie, co przy gotowym rodowodzie, bo to ten
        # sam fakt z tej samej reguły (`stacks._telescope_rule`): klatki tej nocy zapisał inny
        # teleskop niż karta obrazu. Stoi przy NOCY, nie przy obrazie - przełączenie na inną noc
        # ma je zgasić, więc składamy je z bazy sprzed trybu propozycji przy każdym przerysowaniu.
        teleskop = i18n.t("grid.lin.flag.telescope")
        if not (0 <= idx < len(self._nights) and self._nights[idx].telescope_mismatch) \
                or teleskop in self._warn_base:
            teleskop = ""
        self.warn.set_full_text(" · ".join(x for x in (self._warn_base, teleskop) if x))
        self.night_row.setVisible(True)
        self.items.setVisible(bool(klatki))
        self.action_row.setVisible(bool(klatki))
        self.warn.setVisible(bool(self.warn.full_text()))
        self.note.setVisible(bool(self.note.full_text()))
        self._sync_buttons()
        self._sync_offset_visible()

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
        # OŚ KALIBRACJI TO WYJŚCIE Z TRYBU PROPOZYCJI (G2-3d) - obie wartości gasną, bo obie opisują
        # materiał POPRZEDNIEGO obrazu. `set_lineage` zeruje je swoją drogą; ta metoda go nie woła.
        self._nights = ()
        self._raw_bez_odniesienia = 0
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
        Chowamy oba i oddajemy pion gridowi; puste etykiety znikają razem z ich treścią.

        WYBÓR NOCY GAŚNIE TU, A ZAPALA SIĘ WYŁĄCZNIE W `_fill_night` — jedna droga w każdą stronę:
        combo należy do trybu propozycji, więc każde wyjście z niego (rodowód gotowy, inne
        zaznaczenie, oś kalibracji) ma je zdjąć bez pamiętania o tym z osobna."""
        self.night_row.setVisible(False)
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
        godzinami. Minuty w kolumnie zostają, żeby strefy niecałogodzinne nie wymagały migracji,
        gdy Zdzin tam pojedzie — pole jest szersze niż dzisiejsze okno i to jest świadome.

        DWIE CYFRY PO PRZECINKU, NIE JEDNA — i to nie jest kosmetyka (bramka pakietu, zarzut 2).
        Krok 0,1 h to 6 minut, więc strefy kwadransowe (Nepal `+5:45`, Chatham `+12:45`) nie dają
        się w tym oknie WYRAZIĆ. Gorsze od braku: przy ponownym otwarciu wartość 345 min pokazałaby
        się jako `5,8`, a samo OK zapisałoby **348** — ciche przepisanie poprawnego zapisu na błędny,
        bez śladu dla człowieka. Przy dwóch cyfrach `5,75` wraca do 345 co do minuty."""
        biezacy = None if self._head is None else self._head["utc_offset_min"]
        wstepna = biezacy if biezacy is not None else (self._offset_hint or 0)
        godziny, ok = QInputDialog.getDouble(
            self, i18n.t("grid.lin.offset_title"), i18n.t("grid.lin.offset_prompt"),
            wstepna / 60.0, -14.0, 14.0, 2)
        if ok:
            self.offset_asked.emit(round(godziny * 60))

    def _sync_offset_visible(self):
        """Przycisk odniesienia wchodzi TYLKO tam, gdzie ma co zmienić — a to znaczy: gdy powód
        brzmi `offset_unknown`, gdy PROPOZYCJA MA KANDYDATÓW BEZ ZEGARA, ALBO gdy odniesienie już
        wskazano (droga POWROTNA, żeby pomyłka ręki nie była wieczna — ta sama lekcja, co przy
        zestawie w R1).

        Nie pokazujemy go przy każdym stosie, bo dla 121 masterów FITS/ASI odniesienie nie jest
        pytaniem: ich czas i tak jest w jednym zegarze, a przycisk sugerowałby problem tam, gdzie
        go nie ma.

        CZŁON O KANDYDATACH JEST KONIECZNOŚCIĄ, NIE WYGODĄ (bramka pakietu 3a, 0808). Sam powód
        `offset_unknown` NIE WYSTARCZA, bo `_plan` kończy na `degenerate_window` PRZED wywołaniem
        `_in_window` (`stacks._plan`) — czyli stos o zdegenerowanym oknie, zbudowany z RAW-ów,
        tego powodu nie dostanie NIGDY. Bez tego członu jedyna recepta na 6 z 35 obrazów kubełka
        była strukturalnie nieklikalna, a panel twierdził przy tym, że archiwum jest puste."""
        head = self._head
        widoczny = head is not None and (head["unresolved_reason"] == REASON_OFFSET_TOKEN
                                         or self._raw_bez_odniesienia > 0
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


def _candidate_item_text(r):
    """Jeden wiersz PROPOZYCJI: czas · ekspozycja · filtr. Bez ścieżki i bez źródła pewności — obu
    tu nie ma z definicji: kandydat nie jest jeszcze wejściem, więc źródła nie ma czym wypełnić,
    a wiersz różnicuje CZAS (klatki jednej nocy leżą w jednym folderze i mają nazwy z akwizycji).
    Filtr zostaje, bo master bez własnego `FILTER` nie zawęża tej osi — wtedy jest jedyną
    informacją, która odróżnia kanały tej samej sesji."""
    czas = (r["date_obs"] or "")[:19].replace("T", " ")
    exp = f"{r['exptime']:.0f}s" if r["exptime"] is not None else "-"   # DASH, ORDERs §5.2
    return f"{czas} · {exp}" + (f" · {r['filter_canon']}" if r["filter_canon"] else "")


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

    Panel twierdził „obraz nie ma rozpoznanego obiektu" o wierszu, który w kolumnie obok pokazywał
    `IC443` — sprzeczność w jednym oknie, której user nie ma prawa rozstrzygać domysłem.

    PREDYKAT MA JEDNEGO WŁAŚCICIELA I NIE JEST NIM POWIERZCHNIA (SPOT, 0808): od kubełka rodowodu
    to samo pytanie zadaje perspektywa Zbiorów (`queries.lineage_pending_frame_ids` — zwietrzały
    stos czeka na PRZELICZENIE, nie na gest, więc do kubełka nie należy). Dwie kopie reguły
    rozjechałyby się przy pierwszym nowym powodzie, a rozjazd byłby niewidoczny: panel mówiłby
    jedno, lista wysyłałaby gdzie indziej. Zostaje tu sam alias, bo tekst powodu składa
    powierzchnia.

    NIE NAPRAWIAMY TU RODOWODU i to jest granica, nie brak: dobór wejść jedzie po CAŁYM archiwum
    stosów, więc jego przeliczenie należy do etapu w Dostawie. Panel ma powiedzieć PRAWDĘ o tym,
    co wie — a prawdą jest „ten zapis jest starszy niż twoje zmiany"."""
    return queries.lineage_reason_stale(head)


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
    # UWAGA OBOK WERDYKTU (G2-1d) STOI POZA GUARDEM LISTY: mówi o klatkach, których na liście nie ma
    # z definicji (RAW-y bez zegara nie weszły), więc przy zerze wejść jest tak samo prawdziwa.
    n_raw = _lineage_raw_note(head)
    if n_raw:
        ostrz.append(i18n.t_plural("grid.lin.flag.raw_unreferenced", n_raw))
    if head["twins"]:
        # NIE ostrzeżenie: ten sam zbiór wejść pod inną nazwą pliku to WARIANT tego samego obrazu
        # (`_ast`, `_drizzle_1x`, `_integration`), a nie kolizja. Zmierzone: 51 z 62 oflagowanych.
        info.append(i18n.t_plural("grid.lin.flag.twins", head["twins"]))
    if head["declared_rows"] is not None:
        info.append(i18n.t_plural("grid.lin.flag.declared", head["declared_rows"]))
    if head["excluded"]:
        info.append(i18n.t("grid.lin.flag.excluded", n=head["excluded"]))
    return " · ".join(ostrz), " · ".join(info)


def _lineage_raw_note(head):
    """Ile RAW-ów obrazu CZEKA NA ZEGAR wg uwagi przebiegu (`integration.raw_unreferenced`, G2-1d)
    - `0`, gdy uwagi nie ma albo ZWIETRZAŁA. Jeden właściciel dla flagi panelu i dla bramki gestu
    odniesienia (`FramesView._refresh_lineage`), żeby oba mówiły o tej samej liczbie.

    WIETRZEJE PO WSKAZANIU ZEGARA: liczba pochodzi z przebiegu sprzed gestu, a gest odpowiada
    dokładnie na jej pytanie - lustro członu `offset_unknown` w `queries.lineage_reason_stale`.
    Powtarzanie „nie umiem umieścić N klatek" nad obrazem z już wskazanym zegarem byłoby zdaniem
    starszym niż zmiana; bieżący stan pokaże najbliższy przebieg rodowodu."""
    if head["utc_offset_min"] is not None:
        return 0
    return head["raw_unreferenced"] or 0


def _frame_gate_reason(n, alive):
    """POWÓD wygaszenia kontrolki „Klatka ▾" jako klucz i18n — schodzi od najwęższego, jak
    `_object_gate_reason`.

    Rozróżnienie „nic nie zaznaczono" od „zaznaczyłeś klatki, których pliki żyją" jest tu całą
    treścią: drugi przypadek to OCHRONA, która zadziałała, i user ma prawo wiedzieć, że gest go
    nie zawiódł, tylko odmówił — inaczej wyszarzona kontrolka wygląda na usterkę."""
    if not n:
        return "grid.sel.frame_tip_empty"
    if alive:
        return "grid.sel.frame_tip_alive"
    return "grid.sel.frame_tip_none"


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
