"""Panel rodowodu widoku „Klatki" - `LineageBar` i teksty wierszy rodowodu oraz kalibracji.

Pokazuje wejścia stosu albo mastery kalibracji zaznaczonej klatki, powód braku (`no_object`,
`offset_unknown`), flagi świeżości i bramki gestów (`_frame_gate_reason`, `_object_gate_reason`).
Warstwa widżetów; dane z read-modelu `queries`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from PySide6.QtWidgets import QDialogButtonBox      # okno wyboru kalibratora (`_WyborKalibratora`)

from horreum.gui import busy, i18n, queries
from horreum.gui.grid_model import _COLORS
from horreum.gui.kolko import kolko                # kółko myszy przestawia pole wyłącznie z fokusem (AR-349)
from horreum.gui.grid_panels import ElidedLabel


# Sufit listy panelu rodowodu: wejść stosu bywa kilkaset, więc lista MUSI mieć próg, za którym oddaje
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
    a w większości stosów archiwum (najwyższa ranga wejść = okno czasu) nią nie jest.

    Głupi widżet (NARROW, wzorzec `MacroBar`/`SelectionBar`): sam nie czyta i nie pisze do bazy —
    dostaje gotowy materiał przez `set_lineage` i emituje `judged(frame_ids, excluded)`; zapis
    (jedna klinga) robi `FramesView`.

    STOS BEZ WEJŚĆ TEŻ MA CO POKAZAĆ - i to jest sedno, nie przypadek brzegowy: spora część
    stosów archiwum nie ma rodowodu (liczniki ze stanu: memo stosów w Dostawie), a powód („okno
    opisuje jedną klatkę", „klatki są z innego teleskopu") mówi użytkownikowi, KTÓRĄ naprawę
    wykonać. Puste okno bez zdania byłoby gorsze niż brak panelu."""

    judged = Signal(list, bool)        # (frame_ids, excluded) — werdykt ręki, zapis u gospodarza
    offset_asked = Signal(int)         # (minuty) — wskazane odniesienie czasu, zapis u gospodarza
    # (frame_ids listy, frame_id dwukliku, tryb listy) - „pokaż te klatki w Zbiorach". Panel nie zna
    # gridu (NARROW): oddaje klatki, które pokazuje, a zbiór zawęża gospodarz. Tryb (`TRYB_*`) mówi,
    # CZYM są te klatki, bo od tego zależy zdanie na chipie zbioru (wejścia / propozycje / kalibratory).
    frames_requested = Signal(list, int, str)
    # Tryb propozycji: odrzucone wejścia stosu (wygaszone pod propozycjami) i ścieżki kandydatów
    # (nazwa pliku w wierszu) - podaje je `set_lineage` razem z nocami.
    _odrzucone = ()
    _sciezki_kandydatow = {}
    # Wejścia, które bierze gest „Odrzuć nowsze niż obraz" (AR-153): werdykt ręki na klatce zrobionej
    # po zintegrowaniu obrazu, jeszcze nieodrzucony (`rejectable` z `queries.stack_lineage_inputs`).
    _nowsze_ids = ()
    # Wszystkie wiersze listy z klatką nowszą niż obraz (`newer`, każde źródło i werdykt) - przy nich
    # „Potwierdź zaznaczone" ostrzega w podpowiedzi.
    _nowsze_wszystkie = frozenset()
    # OŚ KALIBRACJI - gesty ręki (E4-5), zapis u gospodarza. Każdy sygnał niesie klatkę nieba, o którą
    # pyta panel: para (panel, cel zapisu) powstaje razem w `set_calibration`, więc zmiana zaznaczenia
    # gridu w trakcie gestu nie przekieruje zapisu na inną klatkę.
    # (light, relacja, master, stan widziany: None = brak ogniwa | [master, asserted_by])
    calibrator_picked = Signal(int, str, int, object)
    calibrator_restored = Signal(int, str, int)      # (light, relacja, master wskazania ręki)
    calibration_count_asked = Signal(int)            # (light) - „Policz teraz”: etap Rodowód

    # Wiersz gestów osi kalibracji powstaje przy PIERWSZYM pokazaniu tej osi (`_wiersz_kalibracji`) -
    # panel stosu go nie potrzebuje. `_relacje` = materiał `explain_light` pokazywany na liście,
    # `_light_id` = klatka, o którą panel pyta; oba gasną przy wyjściu z osi (`_zgas_os_kalibracji`).
    _cal_row = None
    _relacje = ()
    _light_id = None

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
        self.combo_night = kolko(QComboBox())
        self.combo_night.currentIndexChanged.connect(self._on_night)
        nr.addWidget(self.combo_night, 1)
        lay.addWidget(self.night_row)
        # WSPÓLNY KATALOG WEJŚĆ RAZ, NAD LISTĄ - w wierszu zostaje sama nazwa pliku. Zmierzone na
        # kopii `pf4`: 161 ze 162 stosów z wejściami ma WSZYSTKIE wejścia w jednym katalogu, więc
        # `…\NGC4826\RC8_2600MC\L-Pro\` powtarzał się w każdym wierszu i zjadał miejsce nazwie.
        # Katalog opisuje TĘ listę, więc gaśnie przy każdym jej czyszczeniu (`modelReset`) - także
        # w osi kalibracji i w trybie propozycji, bez pamiętania o tym w każdej gałęzi z osobna.
        self.dir_row = QWidget()
        dr = QHBoxLayout(self.dir_row)
        dr.setContentsMargins(0, 0, 0, 0)
        _dir_lbl = QLabel(i18n.t("grid.lin.common_dir"))
        _dir_lbl.setProperty("role", "secondary")
        dr.addWidget(_dir_lbl)
        self.dir_path = SciezkaLabel()
        self.dir_path.setProperty("role", "secondary")
        dr.addWidget(self.dir_path, 1)
        self.dir_row.setVisible(False)
        lay.addWidget(self.dir_row)
        self.items = QListWidget()
        self.items.model().modelReset.connect(self._zgas_katalog)
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.setTextElideMode(Qt.ElideLeft)       # ścieżka: koniec (nazwa pliku) niesie sens
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items.setMaximumHeight(_LINEAGE_LIST_MAX_H)   # panel nie zjada gridu (wiz F3 #1)
        self.items.itemSelectionChanged.connect(self._sync_buttons)
        # DWUKLIK WIERSZA = TA KLATKA W ZBIORACH, w obu osiach jednym handlerem. Bez niego panel był
        # ślepym zaułkiem: pokazywał setki ścieżek wejść albo ścieżkę mastera, a żadna nie wiodła
        # do klatki, której dotyczyła. Tooltip listy nazywa gest - lista nie ma paska narzędzi,
        # a gest bez afordancji istnieje tylko dla tego, kto czytał kod (wzór listwy facetów).
        self.items.itemDoubleClicked.connect(self._on_double_click)
        self.items.setToolTip(i18n.t("grid.lin.show_tip"))
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
        # GEST AR-153 (decyzja Zdzinia `D-1016-1`: werdykty ręki na klatkach nowszych niż obraz to
        # pomyłka): odrzuca WYŁĄCZNIE takie wejścia, bez zaznaczania ich ręką na liście. Idzie tym
        # samym sygnałem co „Odrzuć zaznaczone", więc zapis, przeładowanie i „Cofnij werdykt" na pasku
        # robi gospodarz jedną drogą (`FramesView._on_lineage_judged`).
        self.btn_reject_newer = QPushButton(i18n.t("grid.lin.reject_newer"))
        self.btn_reject_newer.setToolTip(i18n.t("grid.lin.reject_newer_tip",
                                                undo=i18n.t("grid.lin.undo")))
        self.btn_reject_newer.clicked.connect(self._emit_newer)
        row.addWidget(self.btn_confirm)
        row.addWidget(self.btn_reject)
        row.addWidget(self.btn_reject_newer)
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
        self._raw_bez_odniesienia = 0   # druga wartość tamtego zwrotu - kandydaci bez zegara
        self._po_zintegrowaniu = 0      # trzecia - klatki zrobione po zintegrowaniu obrazu (AR-150)
        self._note_base = ""            # nota sprzed trybu propozycji (combo jej nie zjada)
        self._warn_base = ""            # ostrzeżenie sprzed trybu propozycji (noc dokłada swoje)
        self.set_lineage(None, [])

    def set_lineage(self, head, inputs, *, hint=None, candidates=(), raw_unreferenced=0,
                    after_integration=0, candidate_paths=None):
        """Wypełnij panel. `head` = wiersz `queries.stack_lineage_head` (albo `None`), `inputs` =
        wiersze `queries.stack_lineage_inputs`, `hint` = gotowe zdanie, gdy nie ma czego pokazać
        (złe zaznaczenie / rodowód nieliczony), `candidates` + `raw_unreferenced` +
        `after_integration` = trzy wartości zwrotu `stacks.propose_lineage_candidates`. Zero SQL
        i zero decyzji - sama prezentacja.

        PROPOZYCJE WCHODZĄ TYLKO W PUSTKĘ i to jest granica, nie optymalizacja: gdy stos MA wejścia,
        lista jest zapisem faktu, a doklejenie do niej ofert kazałoby odróżniać jedno od drugiego
        w tym samym oknie. Obraz z rodowodem niczego nie proponuje.

        `raw_unreferenced` PRZYCHODZI OSOBNO, BO NIESIE INNĄ RECEPTĘ NIŻ PUSTA LISTA: „kandydaci są,
        tylko nie znam zegara tego obrazu" prowadzi do gestu odniesienia, a „nie ma kandydatów" nie
        prowadzi nigdzie. Bez tej wartości panel mówił 6 obrazom kubełka, że archiwum jest puste,
        gdy stało w nim po 36 klatek (bramka pakietu 3a, 0808).

        `after_integration` IDZIE TĄ SAMĄ DROGĄ I Z TEGO SAMEGO POWODU (AR-150): klatki zrobione po
        zintegrowaniu obrazu propozycja pomija, a panel mówi ile - inaczej obraz, którego cały
        materiał powstał później, słyszałby, że archiwum nie ma ani jednej klatki."""
        self.items.clear()
        self.items.setMaximumHeight(_LINEAGE_LIST_MAX_H)   # oś kalibracji zaniża sufit do treści
        self._head = head
        # NOCE GASNĄ TU, A ZAPALAJĄ SIĘ WYŁĄCZNIE W `_set_candidates` - jedna droga w każdą stronę,
        # wzorem `_sync_visible` dla `night_row` (G2-3d). Bez tego `_nights` przeżywało wyjście
        # z trybu propozycji i licznik kandydatów mówiłby o POPRZEDNIM obrazie.
        self._nights = ()
        self._raw_bez_odniesienia = raw_unreferenced
        self._po_zintegrowaniu = after_integration
        self._nowsze_ids = [r["input_frame_id"] for r in inputs
                            if r.get("rejectable") and not r["excluded"]]
        self._nowsze_wszystkie = frozenset(r["input_frame_id"] for r in inputs if r.get("newer"))
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
        ostrz = " · ".join(x for x in (ostrz, _lineage_newer_warn(inputs)) if x)
        # OSTRZEŻENIE STAWIAMY OD RAZU, PRZED GAŁĘZIAMI — bo gałąź propozycji kończy się `return`
        # i pomijała ten zapis, więc panel nowego obrazu nosił ostrzeżenie POPRZEDNIEGO („⚠ obraz
        # zapisał inny teleskop niż jego klatki" o cudzym pliku). Zmierzone bramką pakietu 3a 0808;
        # etykieta była realnie widoczna, nie tylko wypełniona.
        self.warn.set_full_text(ostrz)          # `_lineage_flags` samo milczy przy pustej liście
        # LISTA POWSTAJE ZAWSZE, ZANIM ROZSTRZYGNIEMY O NAGŁÓWKU. Integracja z POWODEM może mieć
        # wiersze — `_reconcile` omija werdykty ręki, więc odrzucone kandydatury zostają, mając
        # `head["inputs"] == 0`. Gałąź powodu, która listy nie wypełniała, zabierała wtedy JEDYNĄ
        # drogę cofnięcia własnej decyzji (`stack_lineage_inputs` oddaje je właśnie po to).
        katalog = _wspolny_katalog([r["path"] for r in inputs])
        for r in inputs:
            it = QListWidgetItem(_lineage_item_text(r, katalog))
            it.setData(Qt.UserRole, r["input_frame_id"])
            if katalog is not None:
                it.setToolTip(r["path"] or "")      # pełna ścieżka pod kursorem, gdy wiersz ją skraca
            if r["excluded"]:
                it.setForeground(_COLORS["secondary_text"])
            elif r.get("newer"):
                it.setForeground(_COLORS["warn"])   # znacznik w tekście niesie to samo bez koloru
            self.items.addItem(it)
        if not head["inputs"] and powod:
            # NIE MA CZEGO POLICZYĆ ⇒ NIE LICZYMY. „Weszło 0 klatek · 0.0 h" o obrazie, który
            # przecież Z CZEGOŚ powstał, jest twierdzeniem, którego model nie ma — a to stan
            # CZĘSTY, nie brzegowy (memo stosów w Dostawie liczy go ze stanu). Głos oddaje powód, bo to on
            # mówi, KTÓRĄ naprawę wykonać; zero i „0.0 h" znikają.
            #
            # Warunek stoi na POWODZIE, nie na samym zerze: gdy człowiek odrzuci wszystkie
            # kandydatury, `inputs` też jest zerem — ale wtedy „weszło 0 klatek" jest PRAWDĄ
            # i jego własną decyzją, więc nagłówek ma ją pokazać.
            # ZDANIE POWODU MÓWI TYLKO TO, CO SPRAWDZONO (wizytacja natywna): `no_candidates` znaczy
            # „okno NAGŁÓWKA nic nie wybrało", a nie „archiwum nic nie ma" - pod spodem stoi noc
            # obrazu z dziesiątkami kandydatów. Przy materiale w propozycji powód mówi węziej.
            # Ta sama węższa mowa, gdy CAŁY pasujący materiał powstał po zintegrowaniu obrazu
            # (AR-150): „nie ma ani jednej pasującej klatki" nad notą „pominiętych 66 klatek
            # nowszych niż obraz" jest prawdą o oknie, ale czyta się jak sprzeczność - bliźniak
            # zdania, które nota wypiera w `_fill_night`. Liczba zostaje w nocie. RAW bez zegara
            # wyklucza ten wariant: o nim nie wiadomo, kiedy powstał.
            # Wariant „wszystkie powstały po obrazie" tylko bez własnych werdyktów na liście:
            # odrzucona klatka sprzed obrazu przeczyłaby słowu „wszystkie".
            if head["unresolved_reason"] == REASON_NO_CANDIDATES_TOKEN and not _lineage_stale(head):
                if any(n.frames for n in candidates):
                    powod = i18n.t("grid.lin.reason.no_candidates_window")
                elif after_integration and not raw_unreferenced and not inputs:
                    powod = i18n.t("grid.lin.reason.no_candidates_after_integration")
            self.head.setText(powod)
            self.note.set_full_text(info)
            # PUSTA PROPOZYCJA NAD WŁASNYMI WERDYKTAMI NIE OTWIERA TRYBU NOCY: „archiwum nie ma ani
            # jednej klatki" (pusta noc obrazu) byłoby fałszem - klatki są, tylko człowiek je odrzucił,
            # a propozycja osądzonych nie zwraca. Panel zostaje przy liście werdyktów (do cofnięcia)
            # i przy powodzie, który mówi receptę - tak stoi `telescope_mismatch` po werdyktach
            # (AR-171: zostaje w kubełku, receptą jest naprawa karty, nie lista). Bez werdyktów pusta
            # noc zostaje, jak dotąd: wtedy zdanie o pustym archiwum jest prawdą.
            if candidates and (any(n.frames for n in candidates) or raw_unreferenced or not inputs):
                self._odrzucone = [r for r in inputs if r["excluded"]]
                self._sciezki_kandydatow = dict(candidate_paths or {})
                self._set_candidates(candidates)
                return
            # POZA TRYBEM PROPOZYCJI LICZNIK ZOSTAJE (AR-154): stos, któremu propozycja nie ma nic
            # do dania poza klatkami nowszymi niż obraz, z kubełka wypada i nocy nie otwiera - ale
            # zdanie, DLACZEGO lista jest pusta, nie znika razem z trybem (to samo zdanie, co nota
            # nocy w `_fill_night`).
            # …I CO DALEJ (AR-171): nic - ani gest, ani przeliczenie rodowodu w Dostawie tego nie
            # zmieni, a podpowiedź stanu „brak" wysyłała właśnie tam. Zdanie stoi WYŁĄCZNIE przy
            # stanie „tylko klatki nowsze niż obraz": RAW-y czekające na zegar mają receptę (gest
            # odniesienia), a lista własnych werdyktów (`inputs` tu = same odrzucone, stan „wszystkie
            # odrzucone") ma drogę „Potwierdź" - nad nią „nie ma czego potwierdzić" byłoby fałszem.
            if after_integration:
                self.note.set_full_text(" · ".join(x for x in (info, i18n.t_plural(
                    "grid.lin.cand.after_integration", after_integration),
                    "" if raw_unreferenced or inputs else i18n.t("grid.lin.cand.only_newer"))
                    if x))
        elif head["used_rows"] is not None:
            # WERDYKT „N Z M" (podzbiór okna): nagłówek nie ma prawa mówić „weszły M" - weszło N,
            # tylko nie wiadomo które. Godziny skalowane do N (≈), bo wiersze listy to kandydaci okna.
            # Zdanie o podzbiorze idzie do OSTRZEŻENIA: to sprawa do decyzji, nie objaśnienie.
            m, n = head["window_rows"] or head["inputs"], head["used_rows"]
            godziny = (head["secs"] or 0) / 3600.0 * (n / head["inputs"] if head["inputs"] else 0)
            self.head.setText(i18n.t_plural("grid.lin.head_subset", m, used=n,
                                            hours=f"{godziny:.1f}"))
            self.warn.set_full_text(" · ".join(x for x in (
                ostrz, i18n.t_plural("grid.lin.flag.used_rows_warn", m, used=n)) if x))
            self.note.set_full_text(" · ".join(
                x for x in (powod, _lineage_basis_text(head, z_uzyciem=False), info) if x))
        else:
            godziny = (head["secs"] or 0) / 3600.0
            self.head.setText(i18n.t_plural("grid.lin.head", head["inputs"],
                                            hours=f"{godziny:.1f}"))
            self.note.set_full_text(" · ".join(x for x in (powod, _lineage_basis_text(head), info)
                                               if x))
        # Widoczność z LISTY, nie z licznika: stos z powodem, ale z odrzuconymi wierszami, ma je
        # pokazać (i dać się cofnąć), a stos bez ani jednego wiersza nie ma zajmować pionu na listę.
        self._sync_visible(bool(inputs))
        if katalog is not None:
            self.dir_path.set_full_text(katalog)
            self.dir_row.setVisible(True)

    def _set_candidates(self, nights):
        """Tryb PROPOZYCJI: noce z materiałem w combo, klatki wybranej nocy na liście.

        Otwiera się na NOCY MASTERA (pozycja 0 z rdzenia), także gdy ta noc jest pusta — bo pierwsze
        pytanie człowieka brzmi „czy program dobrze zrozumiał, o który wieczór pytam", a nie „daj mi
        cokolwiek". Przełączenie nocy NIE PYTA BAZY: rdzeń oddał wszystkie noce naraz, więc combo
        przerysowuje listę z pamięci."""
        self._zgas_os_kalibracji()            # propozycje to oś stosów - gesty kalibracji gasną
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
            it = QListWidgetItem(_candidate_item_text(r, self._sciezki_kandydatow.get(r["frame_id"])))
            it.setData(Qt.UserRole, r["frame_id"])
            self.items.addItem(it)
        # ODRZUCONE ZOSTAJĄ NA LIŚCIE, WYGASZONE (wizytacja natywna): propozycja osądzonych klatek nie
        # zwraca, więc odrzucony kandydat znikał z ekranu i jedyną drogą cofnięcia było „Cofnij"
        # na pasku. Pod propozycjami stoją własne werdykty - zaznaczenie i „Potwierdź" je odwraca.
        for r in self._odrzucone:
            it = QListWidgetItem(_lineage_item_text(r))
            it.setData(Qt.UserRole, r["input_frame_id"])
            it.setForeground(_COLORS["secondary_text"])
            self.items.addItem(it)
        widac_liste = self.items.count() > 0
        gdzie_indziej = sum(len(n.frames) for n in self._nights) - len(klatki)
        # TRZY RÓŻNE PUSTKI, TRZY RECEPTY - i to jest sedno naprawy z bramki 3a. „Nie ma nic"
        # i „są klatki, których nie umiem umieścić w czasie" prowadzą w zupełnie inne miejsca:
        # pierwsze donikąd, drugie wprost do gestu odniesienia (przycisk niżej sam się zapala).
        # Wspólne zdanie kłamało 6 obrazom kubełka, że archiwum jest puste, gdy stało w nim po 36.
        #
        # KLATKI PO ZINTEGROWANIU OBRAZU (AR-150) MÓWIĄ WŁASNYM ZDANIEM PRZY KAŻDEJ NOCY, bo
        # pominięcie dotyczy obrazu, nie wybranej nocy; zero = cisza. To zdanie wypiera też
        # „archiwum nie ma ani jednej klatki" - klatki SĄ, tylko powstały po obrazie.
        po_obrazie = (i18n.t_plural("grid.lin.cand.after_integration", self._po_zintegrowaniu)
                      if self._po_zintegrowaniu else "")
        if klatki:
            podpowiedz = ""
        elif gdzie_indziej:
            podpowiedz = i18n.t_plural("grid.lin.cand.empty_night", gdzie_indziej)
        elif self._raw_bez_odniesienia:
            podpowiedz = i18n.t_plural("grid.lin.cand.no_reference", self._raw_bez_odniesienia)
        elif po_obrazie:
            podpowiedz = ""
        else:
            podpowiedz = i18n.t("grid.lin.cand.empty_all", n=0)
        self.note.set_full_text(" · ".join(x for x in (self._note_base, podpowiedz, po_obrazie)
                                           if x))
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
        self.items.setVisible(widac_liste)
        self.action_row.setVisible(widac_liste)
        self.warn.setVisible(bool(self.warn.full_text()))
        self.note.setVisible(bool(self.note.full_text()))
        self._sync_buttons()
        self._sync_offset_visible()

    def set_calibration(self, relations, *, frame_name=None, light_frame_id=None,
                        select_relation=None):
        """DRUGA ODPOWIEDŹ TEGO SAMEGO PANELU (C3, Issue #6): czym skalibrowano zaznaczoną klatkę
        nieba. `relations` = wynik `lineage.explain_light` (po jednym wierszu na `dark`/`flat`),
        `frame_name` = nazwa pliku tej klatki (nagłówek), `light_frame_id` = cel gestów ręki,
        `select_relation` = relacja do zaznaczenia (po geście; bez niej - wiersz wymagający ręki).

        Panel jest kind-aware, a nie zdublowany, bo pytanie użytkownika jest JEDNO - „skąd ta
        klatka ma swój kształt" - i tylko odpowiedź zależy od rodzaju: gotowy obraz mówi, co
        w niego weszło, klatka nieba mówi, czym ją skalibrowano. Dwa osobne panele kazałyby
        zgadywać, który otworzyć, zanim wiadomo, co się zaznaczyło.

        RĘKA WSKAZUJE KALIBRATOR (decyzja Zdzinia, E4-5): dowolny master tej klasy i kamery, także
        spoza przepisu - bo przepis bywa ślepy (6004 lighty bez profilu darka) albo dobiera master
        sprzed trzech lat, a człowiek wie, którym naprawdę kalibrował. To NIE jest werdykt
        „potwierdź/odrzuć” osi stosów (`calibration` nie zna `excluded`), tylko wybór z listy,
        więc wiersz akcji stosu chowa się w całości, a gesty tej osi stoją we własnym wierszu
        (`_wiersz_kalibracji`): „Wskaż kalibrator…”, „Przywróć automat”, „Policz teraz”.

        TRZY STANY, TRZY POZIOMY (wizytacja 0802): powiązany - zwykły tekst; nieliczony - ⚠ i zwykły tekst, bo
        to robota na jedno kliknięcie, nie brak; luka - wygaszona, bo archiwum nie ma czego dać."""
        self.items.clear()
        self._head = None
        # OŚ KALIBRACJI TO WYJŚCIE Z TRYBU PROPOZYCJI (G2-3d) - wszystkie wartości gasną, bo opisują
        # materiał POPRZEDNIEGO obrazu. `set_lineage` zeruje je swoją drogą; ta metoda go nie woła.
        self._nights = ()
        self._raw_bez_odniesienia = 0
        self._po_zintegrowaniu = 0
        self._nowsze_ids = ()
        self._nowsze_wszystkie = frozenset()
        self._relacje = list(relations)
        self._light_id = light_frame_id
        for r in relations:
            it = QListWidgetItem(_calibration_item_text(r))
            it.setData(Qt.UserRole, r["master_frame_id"])
            if r["master_frame_id"] is None and not r["pending"]:
                it.setForeground(_COLORS["secondary_text"])
            self.items.addItem(it)
        self.head.setText(_calibration_head_text(relations, frame_name))
        # LISTA DO TREŚCI, nie do sufitu. Wejść stosu bywa 190, więc tam sufit 160 px chroni grid;
        # tutaj wierszy jest kilka (klasy przepisu), a ten sam sufit zostawiał ~100 px pustki -
        # dokładnie ten zarzut, który zdjął pustkę z panelu stosu (wiz #6), tylko z drugiej strony.
        # Pusta lista NIE zaniża sufitu do paska kilku pikseli: zero relacji jest dziś niemożliwe
        # (stała `_RELATIONS`), ale sufit liczony z nieistniejącego wiersza byłby pułapką czekającą.
        if self.items.count():
            wiersz = self.items.sizeHintForRow(0)
            self.items.setMaximumHeight(wiersz * self.items.count() + 2 * self.items.frameWidth())
        # NIELICZONE ≠ LUKA - pierwsze naprawia jedno kliknięcie („Policz teraz” obok), drugie
        # wymaga klatek, których w archiwum nie ma. Wspólne „brak” kazałoby szukać winy nie tam.
        czeka = any(r["pending"] for r in relations)
        self.warn.set_full_text(i18n.t("grid.lin.cal.pending") if czeka else "")
        self.note.set_full_text("")
        self.items.setVisible(True)
        self.action_row.setVisible(False)          # werdykt stosu nie ma tu celu zapisu
        self.warn.setVisible(bool(self.warn.full_text()))
        self.note.setVisible(False)
        self._wiersz_kalibracji().setVisible(bool(relations))
        self.btn_cal_count.setVisible(czeka)
        self.btn_cal_restore.setVisible(any(r["asserted_by"] == "user" for r in relations))
        # ZAZNACZENIE: relacja, której dotyczył gest (gospodarz po zapisie), a bez niej - jedyny
        # wiersz, który WYMAGA ręki (`_wymaga_reki`). Lista jest przebudowywana ze stanu, więc bez
        # tego każdy gest kończył się pustym zaznaczeniem, a następny zaczynał od kliknięcia w wiersz.
        relacje = [r["relation"] for r in relations]
        do_reki = [r["relation"] for r in relations if _wymaga_reki(r)]
        cel = (select_relation if select_relation in relacje
               else do_reki[0] if len(do_reki) == 1 else None)
        if cel is not None:
            self.items.item(relacje.index(cel)).setSelected(True)
        self._sync_buttons()
        # Odniesienie czasu jest faktem O OBRAZIE, a ta gałąź opisuje KLATKĘ NIEBA - przycisk
        # gaśnie razem z całym trybem stosu. `_head` jest tu `None`, więc gest i tak nie miałby
        # celu zapisu; jawne wołanie trzyma to w JEDNYM miejscu zamiast liczyć na kolejność pól.
        self._sync_offset_visible()

    def _wiersz_kalibracji(self):
        """Wiersz gestów osi kalibracji - budowany RAZ, przy pierwszym pokazaniu tej osi, i wstawiany
        pod wiersz akcji stosu. Osobny widżet, bo chowa się w całości razem z osią
        (`_zgas_os_kalibracji`), a osi stosów nie dotyczy żaden z jego przycisków."""
        if self._cal_row is not None:
            return self._cal_row
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        self.btn_cal_pick = QPushButton(i18n.t("grid.lin.cal.pick"))
        self.btn_cal_pick.clicked.connect(self._ask_calibrator)
        self.btn_cal_restore = QPushButton(i18n.t("grid.lin.cal.restore"))
        self.btn_cal_restore.clicked.connect(self._emit_restore)
        # „Policz teraz” STOI PRZY ⚠: stan nieliczony naprawia jedno kliknięcie, a do tej pory
        # kosztował cztery (Dostawa → Rodowód → Zbiory → ponowne zaznaczenie).
        self.btn_cal_count = QPushButton(i18n.t("grid.lin.cal.count"))
        self.btn_cal_count.setToolTip(i18n.t("grid.lin.cal.count_tip"))
        self.btn_cal_count.clicked.connect(self._emit_count)
        for b in (self.btn_cal_pick, self.btn_cal_restore, self.btn_cal_count):
            row.addWidget(b)
        row.addStretch(1)
        lay = self.layout()
        lay.insertWidget(lay.indexOf(self.action_row) + 1, w)
        self._cal_row = w
        return w

    def _zgas_os_kalibracji(self):
        """Wyjście z osi kalibracji (oś stosów, propozycje, podpowiedź): gesty tej osi znikają
        razem z materiałem, który opisywały - inaczej „Wskaż kalibrator…” wisiałby nad stosem."""
        self._relacje = ()
        self._light_id = None
        if self._cal_row is not None:
            self._cal_row.setVisible(False)

    def _wybrana_relacja(self):
        """Wiersz osi kalibracji, którego dotyczy gest - DOKŁADNIE jeden zaznaczony, inaczej `None`
        (dwa wiersze to dwie klasy, a gest wskazuje kalibrator jednej)."""
        zaznaczone = self.items.selectedItems()
        if len(zaznaczone) != 1 or not self._relacje:
            return None
        i = self.items.row(zaznaczone[0])
        return self._relacje[i] if 0 <= i < len(self._relacje) else None

    def _ask_calibrator(self):
        """„Wskaż kalibrator…”: lista kandydatów z rdzenia (`explain_light`, najpierw z przepisu,
        potem SPOZA PRZEPISU - oznaczone w każdym wierszu) i `calibrator_picked` ze stanem ogniwa,
        który człowiek widział (klinga odmówi, gdy baza zmieniła się w międzyczasie). Okno listy, nie
        rozwijane menu: kandydatów jednej kamery bywa 50 (zmierzone na kopii archiwum)."""
        r = self._wybrana_relacja()
        if r is None or not r.get("candidates") or self._light_id is None:
            return
        kandydaci = r["candidates"]
        dlg = _WyborKalibratora(
            self, [_calibrator_candidate_text(c, r["master_frame_id"]) for c in kandydaci],
            i18n.t("grid.lin.cal.pick_prompt", rel=calibration_class_name(r["relation"])),
            next((i for i, c in enumerate(kandydaci)
                  if c["master_frame_id"] == r["master_frame_id"]), 0))
        if dlg.exec() != QDialog.Accepted or dlg.wybrany() is None:
            return
        wybor = kandydaci[dlg.wybrany()]
        widziany = (None if r["master_frame_id"] is None
                    else [r["master_frame_id"], r["asserted_by"]])
        self.calibrator_picked.emit(self._light_id, r["relation"], wybor["master_frame_id"], widziany)

    def _emit_restore(self):
        r = self._wybrana_relacja()
        if r is not None and r["asserted_by"] == "user" and self._light_id is not None:
            self.calibrator_restored.emit(self._light_id, r["relation"], r["master_frame_id"])

    def _emit_count(self):
        if self._light_id is not None:
            self.calibration_count_asked.emit(self._light_id)

    def _sync_calibration_buttons(self):
        """Uczciwy disabled gestów osi kalibracji - każdy wygaszony przycisk mówi, czego brakuje
        (zaznaczenia wiersza, kandydatów, Twojej decyzji); etap w tle gasi wszystkie (`set_busy`)."""
        if self._cal_row is None:
            return
        r = self._wybrana_relacja()
        if r is None:
            pick_tip = restore_tip = "grid.lin.cal.tip_select"
        else:
            pick_tip = "grid.lin.cal.pick_tip" if r.get("candidates") else "grid.lin.cal.pick_tip_none"
            # „Przywróć automat” mówi, CO zostanie po zdjęciu: dobór z przepisu albo nic.
            restore_tip = ("grid.lin.cal.restore_tip_auto" if r["asserted_by"] != "user" else
                           "grid.lin.cal.restore_tip" if _ma_kandydata_z_przepisu(r) else
                           "grid.lin.cal.restore_tip_none")
        mozna_wskazac = pick_tip == "grid.lin.cal.pick_tip"
        mozna_zdjac = restore_tip in ("grid.lin.cal.restore_tip", "grid.lin.cal.restore_tip_none")
        self.btn_cal_pick.setEnabled(mozna_wskazac and not self._busy)
        self.btn_cal_restore.setEnabled(mozna_zdjac and not self._busy)
        self.btn_cal_count.setEnabled(not self._busy)
        # ETAP W TLE MÓWI SAM ZA SIEBIE: wygaszony przycisk z podpowiedzią „zaznacz wiersz” przy
        # zaznaczonym wierszu kłamałby o przyczynie.
        if self._busy:
            pick_tip = restore_tip = "grid.lin.cal.tip_busy"
        self.btn_cal_pick.setToolTip(i18n.t(pick_tip))
        self.btn_cal_restore.setToolTip(i18n.t(restore_tip))
        self.btn_cal_count.setToolTip(i18n.t("grid.lin.cal.tip_busy" if self._busy
                                             else "grid.lin.cal.count_tip"))

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
        zaznaczenie, oś kalibracji) ma je zdjąć bez pamiętania o tym z osobna. Tą samą drogą gasną
        gesty osi kalibracji - `_sync_visible` woła wyłącznie oś stosów."""
        self.night_row.setVisible(False)
        self._zgas_os_kalibracji()
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
        # ZAZNACZENIE Z KLATKĄ NOWSZĄ NIŻ OBRAZ (AR-153): potwierdzenie zostaje czynne - werdykt należy
        # do człowieka - ale podpowiedź mówi wprost, że zapisze wejście, które nie mogło się zdarzyć.
        nowsze = bool(self._nowsze_wszystkie & set(self.selected_frame_ids()))
        self.btn_confirm.setToolTip(i18n.t("grid.lin.confirm_tip_newer" if nowsze
                                           else "grid.lin.confirm_tip"))
        # „Odrzuć nowsze niż obraz" nie pyta o zaznaczenie - jego cel wyznacza fakt o wejściach.
        # Stoi tylko tam, gdzie ma co odrzucić. Tryb propozycji i oś kalibracji mają `_nowsze_ids`
        # puste z konstrukcji (propozycja zapala się wyłącznie przy zerze niewykluczonych wejść,
        # `set_calibration` zeruje zbiór), więc osobny warunek na tryb byłby martwą literą.
        self.btn_reject_newer.setVisible(bool(self._nowsze_ids))
        self.btn_reject_newer.setEnabled(not self._busy)
        self._sync_calibration_buttons()      # ta sama bramka (zaznaczenie + etap w tle) dla osi kalibracji

    def selected_frame_ids(self):
        return [it.data(Qt.UserRole) for it in self.items.selectedItems()]

    def select_frame_ids(self, frame_ids):
        """Przywróć zaznaczenie po przebudowie listy — po KLATKACH, nie po indeksach. Klatka, która
        z listy zniknęła, po prostu nie wraca (cicho): to stan, nie błąd."""
        chciane = set(frame_ids)
        for i in range(self.items.count()):
            it = self.items.item(i)
            it.setSelected(it.data(Qt.UserRole) in chciane)

    # WYBÓR CZŁOWIEKA W PANELU PRZEŻYWA PRZEBUDOWĘ (AR-172): noc trybu propozycji i relacja osi
    # kalibracji obok zaznaczonych wierszy - gospodarz bierze je przed przeładowaniem nie-nawigacyjnym
    # i oddaje po nim (`FramesView._stan_panelu`). Bez nich panel wracał na noc mastera i domyślną relację.
    def selected_night(self):
        """Noc wybrana w trybie propozycji (data z combo) albo `None` poza tym trybem."""
        return self.combo_night.currentData() if self._nights else None

    def select_night(self, night):
        """Przywróć noc trybu propozycji po przebudowie panelu - po DACIE nocy, nie po indeksie
        (pozycja 0 to zawsze noc mastera, `_set_candidates`). Nocy, której już nie ma, nie zgadujemy:
        panel zostaje na nocy mastera. Przełączenie idzie sygnałem combo - `_on_night` przerysowuje
        listę z pamięci, bez bazy."""
        i = self.combo_night.findData(night) if self._nights else -1
        if i >= 0:
            self.combo_night.setCurrentIndex(i)

    def selected_relation(self):
        """Relacja osi kalibracji z zaznaczonym wierszem (`dark`/`flat`) albo `None`."""
        r = self._wybrana_relacja()
        return None if r is None else r["relation"]

    def _emit(self, excluded):
        ids = self.selected_frame_ids()
        if ids:
            self.judged.emit(ids, excluded)

    def _emit_newer(self):
        """„Odrzuć nowsze niż obraz" (AR-153) → `judged(wejścia do odrzucenia, True)`. Pozostałe
        wejścia - także werdykty ręki sprzed zapisu stosu - zostają nietknięte."""
        if self._nowsze_ids and not self._busy:
            self.judged.emit(list(self._nowsze_ids), True)

    def _zgas_katalog(self):
        """Lista wyczyszczona → wspólny katalog poprzedniej listy schodzi z ekranu."""
        self.dir_path.set_full_text("")
        self.dir_row.setVisible(False)

    def _tryb_listy(self):
        """Czym są klatki na liście: kalibratory (oś kalibracji zeruje `_head`), propozycje (tryb
        nocy) albo wejścia stosu. Fakt panelu, nie domysł gospodarza z zaznaczenia gridu."""
        if self._head is None:
            return TRYB_KALIBRATORY
        return TRYB_PROPOZYCJE if self._nights else TRYB_WEJSCIA

    def _on_double_click(self, item):
        """Dwuklik wiersza → `frames_requested(klatki listy, klatka wiersza, tryb)`.

        ZBIÓREM JEST CAŁA LISTA, celem zaznaczenia - dwukliknięty wiersz. Pytanie brzmi „co weszło
        w ten obraz", więc w Zbiorach ma stanąć komplet (sort, kolumny, nagłówki), a nie samotna
        klatka; wiersz, w który człowiek kliknął, wraca zaznaczony. Wiersz bez klatki (luka osi
        kalibracji: `master_frame_id` NULL) nie ma dokąd prowadzić - gest milczy."""
        cel = item.data(Qt.UserRole)
        if cel is None:
            return
        ids = []
        for i in range(self.items.count()):
            fid = self.items.item(i).data(Qt.UserRole)
            if fid is not None and fid not in ids:
                ids.append(fid)
        self.frames_requested.emit(ids, cel, self._tryb_listy())

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
        bez śladu dla człowieka. Przy dwóch cyfrach `5,75` wraca do 345 co do minuty.

        PRZYCISKI Z KATALOGU (AR-278): statyczne `QInputDialog.getDouble` dawało „Cancel” w polskim
        oknie - repo nie wozi `QTranslator`, więc napisy przycisków ustawia się jak w planerze."""
        biezacy = None if self._head is None else self._head["utc_offset_min"]
        wstepna = biezacy if biezacy is not None else (self._offset_hint or 0)
        okno = QInputDialog(self)
        okno.setInputMode(QInputDialog.DoubleInput)
        # Pole liczby powstaje w oknie Qt (`setInputMode`), nie konstruktorem w tym pliku - reguła kółka (AR-349)
        # idzie na nie wprost, bo bramka AST (`test_gui_kolko_bramka`) widzi wyłącznie konstruktory.
        kolko(okno.findChild(QDoubleSpinBox))
        okno.setWindowTitle(i18n.t("grid.lin.offset_title"))
        okno.setLabelText(i18n.t("grid.lin.offset_prompt"))
        okno.setDoubleRange(-14.0, 14.0)
        okno.setDoubleDecimals(2)
        okno.setDoubleValue(wstepna / 60.0)
        okno.setOkButtonText(i18n.t("grid.lin.offset_ok"))
        okno.setCancelButtonText(i18n.t("grid.lin.offset_cancel"))
        if okno.exec() == QDialog.Accepted:
            self.offset_asked.emit(round(okno.doubleValue() * 60))

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


def _lineage_item_text(r, katalog=None):
    """Jeden wiersz listy wejść: czas · ekspozycja · ŹRÓDŁO PEWNOŚCI · ścieżka. Źródło stoi PRZED
    ścieżką, bo ścieżka jest elidowana od lewej i to ona ustępuje miejsca, nigdy werdykt.

    `katalog` = wspólny katalog całej listy (`_wspolny_katalog`), pokazany raz nad listą - wiersz
    niesie wtedy samą nazwę pliku."""
    czas = (r["date_obs"] or "")[:19].replace("T", " ")
    exp = f"{r['exptime']:.0f}s" if r["exptime"] is not None else "-"   # DASH, ORDERs §5.2
    zrodlo = i18n.t(f"grid.lin.src.{r['asserted_by']}")
    if r["excluded"]:
        zrodlo = i18n.t("grid.lin.src.excluded")
    # KLATKA NOWSZA NIŻ OBRAZ (AR-153) - fakt o wierszu, także odrzuconym (mówi, dlaczego odrzucono).
    # W tekście, nie tylko kolorem: kolor nie dociera do każdego oka. `.get`, bo wiersz bywa składany
    # poza read-modelem (testy, wiersze sprzed klucza).
    if r.get("newer"):
        zrodlo = f"{zrodlo} · {i18n.t('grid.lin.src.newer')}"
    sciezka = r["path"] or ""
    if katalog is not None and sciezka.startswith(katalog):
        sciezka = sciezka[len(katalog):]
    return f"{czas} · {exp} · [{zrodlo}] · {sciezka}"


def _wspolny_katalog(sciezki):
    """Katalog (z końcowym separatorem), w którym leżą WSZYSTKIE pokazane ścieżki, albo `None`.

    Tylko jeden katalog, nie najdłuższy wspólny przedrostek: stos z wejściami z dwóch nocy
    (1 ze 162 na kopii `pf4`) ma dwa katalogi i każdy wiersz musi powiedzieć, z którego jest -
    przedrostek wspólny ukryłby właśnie tę różnicę. Wiersz bez ścieżki (klatka bez obecnej kopii)
    nie rozstrzyga - nie ma czego skracać. Separator `\\` albo `/`, jak w ścieżkach archiwum."""
    katalogi = set()
    for p in sciezki:
        if p:
            i = max(p.rfind("\\"), p.rfind("/"))
            katalogi.add(p[:i + 1])
    if len(katalogi) != 1:
        return None
    (katalog,) = katalogi
    return katalog or None


class SciezkaLabel(ElidedLabel):
    """Etykieta ścieżki elidowana OD LEWEJ - koniec katalogu (obiekt, zestaw, filtr) niesie sens,
    a początek (`R:\\ASTRO_\\LIGHTS\\`) jest wspólny dla całego archiwum. Pełna ścieżka w tooltipie."""

    def _update_elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideLeft, max(0, self.width() - 4)))


def _candidate_item_text(r, sciezka=None):
    """Jeden wiersz PROPOZYCJI: czas · ekspozycja · filtr · nazwa pliku. Bez źródła pewności -
    kandydat nie jest jeszcze wejściem, więc źródła nie ma czym wypełnić. Filtr zostaje, bo master
    bez własnego `FILTER` nie zawęża tej osi - wtedy jest jedyną informacją, która odróżnia kanały
    tej samej sesji. Nazwa pliku (bez katalogu: klatki jednej nocy leżą w jednym folderze) daje
    człowiekowi to, po czym zna swoje klatki - sam czas tego nie dawał (wizytacja natywna)."""
    czas = (r["date_obs"] or "")[:19].replace("T", " ")
    exp = f"{r['exptime']:.0f}s" if r["exptime"] is not None else "-"   # DASH, ORDERs §5.2
    nazwa = str(sciezka or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return (f"{czas} · {exp}" + (f" · {r['filter_canon']}" if r["filter_canon"] else "")
            + (f" · {nazwa}" if nazwa else ""))


def _znany(klucz, zapasowo):
    """Etykieta z katalogu ALBO surowa wartość, gdy katalog jej nie zna. `i18n.t` na nieznanym kluczu
    zwraca sam klucz („grid.lin.cal.rel.bias" na ekranie), a baza dopuszcza wartości spoza stałych
    kodu (`0009`: `bias`, wpisy ręki/WBPP). Lepiej pokazać surowe `bias` niż ścieżkę klucza."""
    return i18n.t(klucz) if klucz in i18n.CATALOG else zapasowo


class _WyborKalibratora(QDialog):
    """Okno „Wskaż kalibrator”: lista kandydatów (wiersze z `_calibrator_candidate_text`), DWUKLIK
    zatwierdza wybór, przyciski mówią językiem programu (i18n, nie „Cancel” w polskim oknie),
    a wysokość mieści kilkanaście wierszy z ~50 - `QInputDialog` nie dawał żadnej z tych trzech
    rzeczy (wizytacja fali 4). Wynik: indeks wybranego wiersza (`wybrany`)."""

    def __init__(self, parent, etykiety, prompt, start):
        super().__init__(parent)
        self.setObjectName("calibrator_picker")
        self.setWindowTitle(i18n.t("grid.lin.cal.pick_title"))
        lay = QVBoxLayout(self)
        opis = QLabel(prompt)
        opis.setWordWrap(True)
        lay.addWidget(opis)
        self.lista = QListWidget()
        self.lista.addItems(etykiety)
        self.lista.setCurrentRow(start)
        self.lista.itemDoubleClicked.connect(lambda _it: self.accept())
        lay.addWidget(self.lista, 1)
        przyciski = QDialogButtonBox()
        ok = przyciski.addButton(i18n.t("grid.lin.cal.pick_ok"), QDialogButtonBox.AcceptRole)
        przyciski.addButton(i18n.t("grid.lin.cal.pick_cancel"), QDialogButtonBox.RejectRole)
        ok.setDefault(True)
        przyciski.accepted.connect(self.accept)
        przyciski.rejected.connect(self.reject)
        lay.addWidget(przyciski)
        self.resize(760, 560)
        self.setMinimumSize(560, 420)

    def wybrany(self):
        i = self.lista.currentRow()
        return i if i >= 0 else None


def calibration_class_name(relation):
    """Nazwa klasy kalibratora dla człowieka („ciemność (dark)”) - jedno źródło dla wiersza listy,
    nagłówka panelu i komunikatów gestu u gospodarza."""
    return _znany(f"grid.lin.cal.rel.{relation}", relation)


def _nazwa_pliku(sciezka):
    """Ostatni człon ścieżki, oba separatory - archiwum to `R:\\...`, testy i kopie bywają `/...`."""
    return (sciezka or "").replace("\\", "/").rsplit("/", 1)[-1]


def _calibration_head_text(relations, frame_name):
    """Nagłówek osi kalibracji: NAZWA KLATKI i stan KAŻDEJ klasy osobno - „ciemność: jest
    · pole: nie policzono”. Dawne „Skalibrowana: N z 2 klas” zrównywało „nie ma” z „nie policzono”,
    a „klas” było żargonem; bez nazwy klatki ekran nie mówił, o której klatce odpowiada."""
    stany = []
    for r in relations:
        stan = ("linked_inactive" if r["master_frame_id"] is not None
                and r.get("master_active") is False else
                "linked_mismatch" if r["master_frame_id"] is not None
                and _niezgodnosc_biezacego(r) else
                "linked" if r["master_frame_id"] is not None else
                "pending" if r["pending"] else "gap")
        stany.append(i18n.t("grid.lin.cal.head.class", rel=calibration_class_name(r["relation"]),
                            state=i18n.t(f"grid.lin.cal.head.{stan}")))
    klasy = " · ".join(stany)
    return i18n.t("grid.lin.cal.head", name=frame_name, classes=klasy) if frame_name else klasy


def _wymaga_reki(r):
    """Czy wiersz osi kalibracji CZEKA NA GEST: kalibrator jest, ale nieaktywny (wycofany, zastąpiony,
    bez pliku) albo kalibratora nie ma, a są kandydaci do wskazania. Nieliczony nie czeka na rękę,
    tylko na „Policz teraz”. Właściciel predykatu domyślnego zaznaczenia (`set_calibration`)."""
    if r["master_frame_id"] is not None:
        return r.get("master_active") is False
    return not r["pending"] and bool(r.get("candidates"))


def _ma_kandydata_z_przepisu(r):
    """Czy po zdjęciu wskazania ręki przebieg ma z czego odtworzyć automat - jest kandydat
    z przepisu lightu. Bez niego „Przywróć automat” zostawia klatkę bez kalibratora i ma to
    powiedzieć, zanim człowiek kliknie."""
    return any(c["in_recipe"] for c in r.get("candidates") or ())


def _poza_przepisem(r):
    """Czy POWIĄZANY master leży poza przepisem lightu - tylko ręka może go tam postawić (E4-5).
    Świadkiem jest lista kandydatów z rdzenia: master z przepisu stoi na niej z `in_recipe`."""
    return r["master_frame_id"] is not None and not any(
        c["master_frame_id"] == r["master_frame_id"] and c["in_recipe"]
        for c in r.get("candidates") or ())


def _calibrator_candidate_text(c, biezacy_id):
    """Wiersz listy wyboru kalibratora: [z przepisu | SPOZA PRZEPISU] · Δ dni · plik (#id).
    Oznaczenie stoi PIERWSZE w każdym wierszu - lista jest długa, a granica przepisu ma być widoczna
    w każdym jej miejscu, nie tylko na początku grupy. Numer klatki czyni wiersze rozróżnialnymi,
    gdy dwa mastery noszą tę samą nazwę pliku w różnych katalogach."""
    znak = i18n.t("grid.lin.cal.cand.recipe" if c["in_recipe"] else "grid.lin.cal.cand.off")
    # SPOZA PRZEPISU NAZYWA NIEZGODNOŚĆ w samym znaczniku („· filtr OIII ≠ Ha”): flat innego filtra
    # stał na liście bez wyróżnienia obok zgodnych (wizytacja fali 4), a wybór bez tej wiedzy jest
    # zgadywaniem. Zgodny spoza przepisu (inna noc profilu? inny teleskop?) mówi samą różnicą.
    if not c["in_recipe"]:
        roznica = _niezgodnosc_text(c.get("mismatch", []))
        if roznica:
            znak = f"{znak} · {roznica}"
    dni = (i18n.t("grid.lin.cal.delta", n=c["days_apart"]) if c["days_apart"] is not None
           else i18n.t("grid.lin.cal.cand.no_time"))
    plik = (_nazwa_pliku(c["master_path"]) if c["master_path"]
            else i18n.t("grid.lin.cal.vanished", id=c["master_frame_id"]))
    tekst = f"[{znak}] · {dni} · {plik} (#{c['master_frame_id']})"
    if c["master_frame_id"] == biezacy_id:
        tekst += f" · {i18n.t('grid.lin.cal.cand.current')}"
    return tekst


def _wartosc_faktu(fakt, wartosc):
    """Wartość członu `profile_key` po ludzku: ekspozycja bez zer po przecinku, brak filtra słowem."""
    if fakt == "filt" and wartosc == "~":
        return i18n.t("grid.lin.cal.mis.no_filter")
    if fakt == "exp":
        try:
            return f"{float(wartosc):g}"
        except ValueError:
            return wartosc
    return wartosc


def _niezgodnosc_text(mismatch):
    """Niezgodność nastawy kandydata wobec lightu (`lineage._niezgodnosc`) → zdanie dla człowieka,
    „filtr OIII ≠ Ha, binning 2 ≠ 1”; `None` (master bez profilu) → „nastawa nieznana”; `[]` → ""."""
    if mismatch is None:
        return i18n.t("grid.lin.cal.mis.unknown")
    return ", ".join(
        i18n.t(f"grid.lin.cal.mis.{m['fact']}", master=_wartosc_faktu(m["fact"], m["master"]),
               light=_wartosc_faktu(m["fact"], m["light"]))
        for m in mismatch)


def _niezgodnosc_biezacego(r):
    """Niezgodność nastawy POWIĄZANEGO mastera wobec lightu - z listy kandydatów (rdzeń liczy ją
    raz, dla każdego aktywnego mastera kamery). Master spoza listy (nieaktywny) - `[]`: o nim
    mówi już ostrzeżenie nieaktywności."""
    for c in r.get("candidates") or ():
        if c["master_frame_id"] == r["master_frame_id"]:
            return c.get("mismatch") or []
    return []


def _calibration_item_text(r):
    """Jeden wiersz osi kalibracji: KLASA · [źródło pewności] · ścieżka mastera. Klasa stoi pierwsza,
    bo to ona jest pytaniem („czym odjęto ciemność, czym wyrównano pole"); ścieżka jest elidowana
    od lewej, więc ustępuje ona, nigdy werdykt - dokładnie jak w wierszu wejść stosu.

    Klasa spoza stałej (`bias`, wpis ręki) dostaje SWOJĄ nazwę zamiast surowego klucza - katalog
    zna dwie, a baza dopuszcza więcej (`0009`). Wskazanie ręki spoza przepisu mówi to w źródle
    pewności („Twoja decyzja · spoza przepisu”) - to jedyne miejsce, gdzie widać, że automat by
    tego mastera nie wybrał."""
    klasa = calibration_class_name(r["relation"])
    if r["master_frame_id"] is not None:
        zrodlo = _znany(f"grid.lin.cal.src.{r['asserted_by']}", r["asserted_by"] or "")
        if r["asserted_by"] == "user" and _poza_przepisem(r):
            zrodlo = f"{zrodlo} · {i18n.t('grid.lin.cal.off_recipe')}"
        # ZNIKNIĘTY MASTER MUSI SIĘ PRZYZNAĆ. `calibrators_for` bierze ścieżkę tylko z kopii
        # OBECNEJ, więc po zniknięciu pliku wiersz kończył się kropką i pustką - a nagłówek dalej
        # liczył go do „skalibrowana". Powiązanie jest prawdziwe (tożsamość to `sha1_data`),
        # nieprawdziwa jest dostępność - i to ona ma być na ekranie.
        gdzie = r["master_path"] or i18n.t("grid.lin.cal.vanished", id=r["master_frame_id"])
        # DYSTANS OBOK ŹRÓDŁA - liczba, nie werdykt. Progu „za daleko" świadomie nie stawiamy:
        # ile dni to za dużo, zależy od klasy i od sprzętu, a zgadnięty próg malowałby na czerwono
        # dobór, który bywa jedynym możliwym. Użytkownik dostaje miarę i ocenia sam.
        if r.get("days_apart") is not None:
            zrodlo = f"{zrodlo} · {i18n.t('grid.lin.cal.delta', n=r['days_apart'])}"
        # NIEAKTYWNY KALIBRATOR (wycofany, zastąpiony, bez pliku) stoi PRZED źródłem: wskazanie ręki
        # przeżywa przebieg, więc bez tego ostrzeżenia „Twoja decyzja” wisiałaby na masterze,
        # którego nie da się już użyć, a jedyną drogą jest wskazać inny.
        if r.get("master_active") is False:
            return f"{klasa} · {i18n.t('grid.lin.cal.inactive')} · [{zrodlo}] · {gdzie}"
        # INNA NASTAWA (wizytacja fali 4): ręka wolno wskazała flat OIII dla lightu Ha, ale panel
        # nie ma prawa mówić o nim zwykłym „jest” - ostrzeżenie nazywa różnicę przed źródłem.
        roznica = _niezgodnosc_biezacego(r)
        if roznica:
            ostrz = i18n.t("grid.lin.cal.mismatch", what=_niezgodnosc_text(roznica))
            return f"{klasa} · {ostrz} · [{zrodlo}] · {gdzie}"
        return f"{klasa} · [{zrodlo}] · {gdzie}"
    # BRAK MA POWÓD ALBO GO NIE MA - i to są dwa różne zdania. Token `gap` niesie powód archiwum;
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
REASON_NO_CANDIDATES_TOKEN = "no_candidates"   # lustro `stacks.REASON_NO_CANDIDATES`

# Tryby listy panelu w sygnale `frames_requested` - gospodarz składa z nich zdanie chipu zbioru.
TRYB_WEJSCIA = "inputs"
TRYB_PROPOZYCJE = "candidates"
TRYB_KALIBRATORY = "calibration"
# Zdanie chipu zbioru per tryb listy. Klucze jawne, nie składane w locie - kolektor literałów
# bramki i18n widzi wyłącznie literały (wzorzec `_OBJECT_STATE_TIPS`).
_KLUCZE_POKAZ = {
    TRYB_WEJSCIA: "grid.lin.show.inputs",
    TRYB_PROPOZYCJE: "grid.lin.show.candidates",
    TRYB_KALIBRATORY: "grid.lin.show.calibration",
}


def _lineage_basis_text(head, *, z_uzyciem=True):
    """NA CZYM stoi rodowód stosu (0034, AR-108) - zdanie obok liczby wejść: podstawa rangi
    `history` (`grid.lin.basis.{token}`, tokeny `stacks.LINEAGE_BASES`), „część klatek poza oknem
    nagłówka” (zbiór z nazw szerszy od okna) i werdykt „plik użył N z M klatek okna” (wiersze okna
    są kandydatami - ile z nich weszło, plik mówi, których - nie). M = `window_rows` z read-modelu:
    wiersze okna plus odrzucone werdyktem, czyli kandydaci okna, które przebieg zapisał - wejście
    dopięte ręką (`user`) M nie zawyża. Token bierze rdzeń, prozę powierzchnia - ta sama granica co
    `_lineage_reason_text`.

    `z_uzyciem=False` - bez członu „plik użył N z M": przy werdykcie podzbioru mówi go nagłówek
    i ostrzeżenie panelu (`set_lineage`), a trzecie powtórzenie w nocie byłoby szumem."""
    czesci = []
    if head["lineage_basis"]:
        czesci.append(i18n.t(f"grid.lin.basis.{head['lineage_basis']}"))
    if head["outside_window"]:
        czesci.append(i18n.t("grid.lin.flag.outside_window"))
    if z_uzyciem and head["used_rows"] is not None:
        czesci.append(i18n.t_plural("grid.lin.flag.used_rows", head["window_rows"],
                                    used=head["used_rows"]))
    return " · ".join(czesci)


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


def _lineage_newer_warn(inputs):
    """Ostrzeżenie o wejściach zrobionych po zintegrowaniu obrazu (AR-153) - DWA ZDANIA, BO DWIE
    RECEPTY (fakt i gest to dwa pojęcia). Werdykt ręki na takiej klatce to pomyłka
    (`D-1016-1`) - zdanie z liczbą i gestem „Odrzuć nowsze niż obraz" niżej. Takie wejście z pliku,
    okna albo wydania znaczy, że zegar w nagłówku kłamie - zdanie bez gestu, bo werdykt ręki nie
    naprawi zegara (populacja na kopii pf4: 0). Wiersze odrzucone milczą: ich sprawa jest zamknięta.
    `inputs` = wiersze `queries.stack_lineage_inputs` (klucze `newer`, `rejectable`)."""
    zywe = [r for r in inputs if r.get("newer") and not r["excluded"]]
    reka = sum(1 for r in zywe if r.get("rejectable"))
    czesci = [i18n.t_plural("grid.lin.flag.newer", reka)] if reka else []
    if any(not r.get("rejectable") for r in zywe):
        czesci.append(i18n.t("grid.lin.flag.newer_clock"))
    return " · ".join(czesci)


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
