"""EKRAN PLANERA CELÓW (T5c) — „co dziś mam na niebie, w odpowiedniej wielkości i filtrach".

Czwarte miejsce nawigacji (D-0731-6): nie zakładka Porządków, bo badge liczy ROBOTY, a „ile do
zrobienia" w planerze zależy od suwaka `min_hours` — liczba w nawiasie kłamałaby przy każdej
zmianie progu. Nie grid, bo wiersz planera to CEL KATALOGU, który nie ma ani jednej klatki
(D-0731-1), a grid operuje na `frame_ids`.

WARSTWY: widżety tutaj, formatowanie w `planner_model` (Qt-wolne), rachunek w `targets`/`sky`
(rdzeń NIETKNIĘTY). Ten plik nie liczy nieba i nie formatuje komórek — montuje i steruje.

OFF-THREAD MIMO 0,35 S: rachunek nocy idzie na wątek tła z paskiem nieokreślonym, bo poprzeczką
jest brak zamrożenia okna, nie zmierzony czas (memory `horreum-gui-long-ops-progress`); przy
warstwie cirrus i wolniejszym dysku to samo 0,35 s bywa wielokrotnie dłuższe.

PRZERWANIE = UNIEWAŻNIENIE GENERACJĄ, świadomie BEZ haka `should_cancel` w rdzeniu: dokładanie
przerwania do `targets.plan` byłoby zmianą kontraktu T3 bez potrzeby. Kontrolki zostają AKTYWNE
w biegu — każda zmiana to nowa generacja, stary wynik ląduje w koszu.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from PySide6.QtCore import (QAbstractTableModel, QDate, QModelIndex, QObject, QSettings, Qt,
                            QThread, QTimer, Signal, Slot)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit,
                               QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QSpinBox, QTableView,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from horreum import db, repo, targets
from horreum.gui import i18n, planner_model as pm, queries, theme

# Debounce zmian parametrów: pojedyncze kliknięcie w strzałkę spinboxa nie ma prawa startować
# rachunku nocy, a przytrzymana strzałka wygenerowałaby ich kilkanaście.
_DEBOUNCE_MS = 300

# Spinbox na „1,00" nie potrzebuje pół ekranu (wiz T5 #12) — kolumna kontrolek ma być kolumną.
_SPIN_W = 96

# Kolumny listy: (klucz i18n, pole `ViewRow`). Kolumny idą do TREŚCI (`ResizeToContents`), a nadmiar
# zjada ostatnia — Notatka (wiz T5 #4). Elizji NIE MA i obiecywać jej nie wolno: `ResizeToContents`
# z definicji nie schodzi poniżej treści, więc `ElideRight` niżej broni tylko komórek przyciętych
# ręcznie przez usera. Wcześniejszy zapis mówił o „elizji 11 kolumn przy 1146 px" i o stałej
# `_STRETCH_COL = 6` (pokrycie), której NIC nie czytało — oba były nieprawdą, patrz `_MIN_W`.
_COLUMNS = (("planner.col_canon", "canon"), ("planner.col_type", "type"),
            ("planner.col_size", "size"), ("planner.col_culmination", "culmination"),
            ("planner.col_window", "window"), ("planner.col_rig", "rig"),
            ("planner.col_coverage", "coverage"), ("planner.col_cost", "cost"),
            ("planner.col_recommend", "recommend"), ("planner.col_plan", "plan"),
            ("planner.col_note", "note"))

# Indeks kolumny „Pokrycie" liczony Z `_COLUMNS`, nie wpisany liczbą: przestawienie kolumn nie ma
# prawa przenieść tooltipu ze ścieżkami stosów (I-2e) na cudzą komórkę.
_COL_COVERAGE = next(i for i, (key, _f) in enumerate(_COLUMNS) if key == "planner.col_coverage")

# PODŁOGA EKRANU — decyzja Zdzinia 2026-08-01 (D-0801-1): kolumny NIE ustępują, ustępuje okno.
# Zmierzone realnym fontem (Segoe UI 9 pt, żywa pf4, 429 wierszy, planer na wierzchu w oknie):
# jedenaście kolumn zajmuje 981 px treści, ramka + pionowy scrollbar biorą 36 px, sidebar nawigacji
# 184 px. Przy oknie 1073 (dawna podłoga, dyktowana przez Zbiory) tabela scrollowała się w poziomie
# o 375 px, przy 1146 o 55. 1126 px ekranu = 1310 px okna daje 109 px zapasu na dłuższe treści
# (warstwa cirrus, katalog EN) i mieści się na 1366×768 przy skalowaniu 100%.
# ⚠ ZNANY KOSZT, zaakceptowany świadomie: przy skalowaniu 125% laptop 1366 raportuje 1093 px
# logicznych — okno wtedy się NIE MIEŚCI, a prawa krawędź ucieka poza ekran. Falsyfikator tej
# decyzji: pierwszy firsthand na maszynie ze skalowaniem.
_MIN_W = 1126

_STATUSES = ("planned", "active", "done", "skip")

# Progi wyszukiwania: (atrybut, klucz i18n, domyślna, min, max, krok) — JEDEN właściciel wartości
# domyślnych (D-0731-10). Zapamiętywane w `QSettings` per maszyna — to zostaje, ale UWAGA na wzorzec:
# porównanie „jak perspektywy gridu" jest NIEAKTUALNE od 2026-08-01 (D-P-I-3 odwróciło D-B, perspektywy
# idą do BAZY). Próg wyszukiwania jest własnością BIURKA, nie archiwum, więc dzieli los rejestru
# świadomie, a nie przez analogię: „w bieżącym wyszukiwaniu" mówiło o tym, że progi nie idą do assetu — a nie o tym, że mają
# ginąć przy każdym uruchomieniu. „Przywróć domyślne" jest obok, więc powrót do 6′/15′/13 mag
# kosztuje jeden klik i stan zawsze widnieje w tytule zwiniętego paska.
_THRESHOLDS = {"min_size": ("planner.min_size", 6.0, 0.0, 600.0, 1.0),
               "min_dark": ("planner.min_dark", 15.0, 0.0, 600.0, 1.0),
               "max_mag": ("planner.max_mag", 13.0, 0.0, 25.0, 0.5),
               "min_alt": ("planner.min_alt", 30.0, 0.0, 89.0, 5.0),
               "min_hours": ("planner.min_hours", 1.0, 0.0, 100.0, 0.5)}
_MAX_COST_DEFAULT = 3.0
_SETTINGS_PREFIX = "planner/"

# Sufit wysokości sekcji sierot kurateli (R-S0-7) — ok. trzy wiersze. Sekcja jest wtrętem między
# planem nocy a panelem wiersza i przy dłuższej liście ma się scrollować, a nie rosnąć: ekran
# planera nie ma zapasu w pionie (D-0801-1).
_ORPHAN_LIST_H = 88

# Wartownik pozycji „nie wypowiedziałeś się" w combo parku: `QComboBox.itemData(None)` jest
# nierozróżnialne od pustych danych, a trójstan `in_park` musi przejść przez UI bez zlania stanów.
_PARK_UNSAID = "unsaid"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class PlanWorker(QObject):
    """Rachunek nocy poza wątkiem GUI (wzorzec `DryWorker` z `projection_dialog`). Otwiera WŁASNE
    połączenie po `db_path` — `con` głównego wątku nie przechodzi (sqlite `check_same_thread`).

    Wynik niesie GENERACJĘ startu: handler odrzuca stale, więc zmiana parametru w biegu nie kończy
    się starym planem na ekranie. `PlanResult` jest `frozen`, więc bezpiecznie przechodzi przez
    sygnał (precedens `stage_done` w `pipeline.py`)."""

    done = Signal(int, object)          # (generacja, targets.PlanResult)
    failed = Signal(int, str)           # (generacja, komunikat)
    finished = Signal()

    def __init__(self, db_path, params, gen, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con                 # tryb inline (testy / baza bez ścieżki) — bieg synchroniczny
        self._params = dict(params)
        self._gen = gen

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except ValueError as exc:
            # Baza bez stanowiska z GPS (`targets.plan`) — SZCZERY komunikat zamiast crashu:
            # planer bez pozycji obserwatora nie ma czego liczyć, a podstawienie „środka Polski"
            # byłoby kłamstwem.
            self.failed.emit(self._gen, str(exc))
        except Exception as exc:
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            return targets.plan(con, **self._params)
        finally:
            if own:
                con.close()


class PlannerTableModel(QAbstractTableModel):
    """Model read-only nad `planner_model.ViewRow` (wzorzec `GridTableModel`): karmiony GOTOWYMI
    komórkami, zero SQL i zero formatowania. Wiersz niewidoczny jest WYSZARZONY, nie ukryty —
    Księżyc i horyzont wyceniają, nie wycinają (D-0731-14)."""

    # Kolumny liczbowe wyrównane w PRAWO — kolumna jest do PORÓWNYWANIA między wierszami,
    # a słupek liczb wyrównany do lewej nie da się skanować (wiz T5 #5, wzorzec `grid`/`app`).
    _NUM_COLS = frozenset({2, 3, 4, 7})     # rozmiar, kulminacja, okno, koszt

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        # Kolor USTAWIA `use_theme` (widok woła je przy budowie) — druga inicjalizacja z
        # `theme.DEFAULT` była drugim właścicielem faktu i nadpisywała się w locie (wiz T5 N3).
        self._dim = QColor(theme.accents(theme.DEFAULT)["secondary_text"])

    def use_theme(self, name):
        """Szarość wiersza niewidocznego z MOTYWU, nie ze sztywnego `128,128,128` (wiz T5 #16):
        na jasnym motywie stała dawała ~3,9:1 kontrastu. Woła `app` przy przełączeniu skórki."""
        self._dim = QColor(theme.accents(name)["secondary_text"])
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, len(_COLUMNS) - 1))

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, r):
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return i18n.t(_COLUMNS[section][0])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return getattr(row, _COLUMNS[index.column()][1])
        if role == Qt.TextAlignmentRole and index.column() in self._NUM_COLS:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and not row.visible:
            return self._dim
        if role == Qt.ToolTipRole:
            # Pokrycie ma WŁASNY tooltip (I-2e — gdzie leżą gotowe obrazy) i wygrywa na swojej
            # kolumnie: „ten cel dziś nie wschodzi" powtarza się w dziesięciu innych komórkach
            # tego samego wiersza, a ścieżka do obrazu jest tylko tutaj.
            if index.column() == _COL_COVERAGE and row.coverage_tip:
                return row.coverage_tip
            if not row.visible:
                return i18n.t("planner.not_visible_tip")
        return None


class ParkDialog(QDialog):
    """„Park…" — jawna własność użytkownika: CZYM dziś fotografuje (D-0731-12). Park NIE jest
    derywowalny z danych (`max(date_obs)` wskazałby sprzęt ostatnio używany, a nie posiadany),
    więc jedyną drogą jest zdanie człowieka.

    Przegląd z `queries.park_overview` (ten sam literał co CLI `horreum park`). Przełącznik ma
    TRZY stany, bo tyle ma `telescope.in_park`: „w parku" (1) · „historyczny" (0) · „nie
    wypowiedziałeś się" (NULL). Trzeci był wcześniej tylko ETYKIETĄ stanu wyjściowego i znikał
    z listy po pierwszym wyborze — czyli UI oferowało drogę w jedną stronę: raz wypowiedziane
    zdanie zostawało na zawsze, a jedyną drogą powrotu było `repo` z konsoli. „Odrzuciłem"
    i „wycofuję zdanie" znaczą co innego (park przejrzany vs baza świeża) i to `in_park` niesie,
    więc powierzchnia musi umieć oba.

    Zapis idzie przez `repo.set_telescope_park` na GŁÓWNYM wątku — jak każda akcja osi."""

    COL_CANON, COL_LIGHTS, COL_LAST, COL_PARK = range(4)

    def __init__(self, con, now_fn, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self.changed = 0
        self.setWindowTitle(i18n.t("planner.park_title"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(i18n.t("planner.park_hint")))
        rows = queries.park_overview(con)
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels([i18n.t("planner.park_col_telescope"),
                                              i18n.t("planner.park_col_lights"),
                                              i18n.t("planner.park_col_last"),
                                              i18n.t("planner.park_col_state")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._combos = {}
        for r, row in enumerate(rows):
            self._fill(r, row)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Stretch na DACIE, nie na combo (wizytacja P-C #10): rozciągnięte combo miało ~450 px na
        # napis „w parku", a numery wierszy Qt niosły informację zerową (grid chowa je tak samo).
        hh.setSectionResizeMode(self.COL_LAST, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        # Tekst przycisku z katalogu, nie z Qt: repo nie wozi `QTranslator`, więc standardowy
        # „Close" wychodziłby po angielsku w polskim oknie (wiz T5 #11, wzorzec `app.py:456`).
        # „Zamknij", nie „OK": dialog zapisuje NATYCHMIAST, nie ma czego zatwierdzać.
        box.button(QDialogButtonBox.Close).setText(i18n.t("planner.park_close"))
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        lay.addWidget(box)

    def _fill(self, r, row):
        # Nazwa USERA przez `queries.telescope_label` (P-C; jedyny właściciel reguły label→kanon,
        # P-B). Dotąd kolumna pokazywała surowy `telescop_canon`, czyli napis Z NAGŁÓWKA — user
        # oglądał tu cudze słowo o własnym sprzęcie. Kanon zostaje TOŻSAMOŚCIĄ zestawu (`sky.park`,
        # token CLI), więc gdy nazwa go przesłania, idzie w tooltip — inaczej nie dałoby się
        # połączyć wiersza dialogu z wierszem `horreum park`.
        item = QTableWidgetItem(queries.telescope_label(row))
        if row["label"]:
            item.setToolTip(i18n.t("planner.park_canon_tip", canon=row["telescop_canon"]))
        self.table.setItem(r, self.COL_CANON, item)
        lights = QTableWidgetItem(str(row["lights"]))
        lights.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)     # słupek liczb (wiz T5 #5)
        self.table.setItem(r, self.COL_LIGHTS, lights)
        # Data do MINUT, bez „T" — surowe ISO to szum (wzorzec `app._fmt_event_ts`, wiz T5 #18).
        last = (row["last_seen"] or "")[:16].replace("T", " ") or "—"
        self.table.setItem(r, self.COL_LAST, QTableWidgetItem(last))
        combo = QComboBox()
        combo.addItem(i18n.t("planner.park_in"), 1)
        combo.addItem(i18n.t("planner.park_historic"), 0)
        # Trzeci stan ZAWSZE na liście — jest wyborem, nie etykietą (patrz docstring klasy).
        # `findData(None)` w Qt zwraca −1 (None znaczy „brak dopasowania"), więc indeksu pozycji
        # NULL nie szukamy po danych, tylko go znamy: jest ostatni.
        combo.addItem(i18n.t("planner.park_unsaid"), _PARK_UNSAID)
        combo.setCurrentIndex({1: 0, 0: 1}.get(row["in_park"], 2))
        combo.activated.connect(lambda _i, tid=row["id"], c=combo: self._on_pick(tid, c))
        self.table.setCellWidget(r, self.COL_PARK, combo)
        self._combos[row["id"]] = combo

    def _on_pick(self, telescope_id, combo):
        """Wybór z listy → `in_park`. Wartownik `_PARK_UNSAID` zamieniamy na `None` dopiero tutaj:
        w `itemData` `None` byłby nieodróżnialny od „brak danych pozycji"."""
        value = combo.currentData()
        if repo.set_telescope_park(self.con, telescope_id=telescope_id,
                                   in_park=None if value == _PARK_UNSAID else value,
                                   now=self._now()):
            self.changed += 1


class PlannerView(QWidget):
    """Ekran planera: nagłówek nocy + panel sterowania + lista celów.

    DWA UCHWYTY DO BAZY, jawnie w konstruktorze: `db_path` dla workera (własne połączenie w wątku)
    oraz `con` dla zapisów kuratelii na GŁÓWNYM wątku (T5d). Bez `db_path` (testy, `:memory:`)
    rachunek idzie inline na `con` — synchronicznie, bez wątku."""

    status_message = Signal(str)
    show_frames_for = Signal(object)     # T5e: kanony archiwum celu → most do gridu

    def __init__(self, con, db_path=None, now_fn=_utc_now_iso, parent=None, off_thread=True,
                 theme_name=None):
        super().__init__(parent)
        self.con = con
        self._db_path = db_path
        self._now = now_fn
        self._off_thread = off_thread
        self._gen = 0
        self._shown_gen = 0              # generacja, której wynik (albo błąd) stoi na ekranie
        self._worker = None
        self._thread = None
        self._result = None
        self._keep_canon = None          # cel, na który zaznaczenie ma wrócić po re-planie
        # PAMIĘĆ ZDJĘTEJ SIEROTY (R-S0-7) — `(kanon, status, priorytet, nota)` albo None. Żyje
        # w SESJI, nie w bazie: to droga powrotu z pomyłki sprzed sekundy, a nie druga historia
        # obok dziennika (`event(target_plan.cleared)` niesie cały wiersz sprzed kasacji).
        self._orphan_undo = None
        self._rig_chip = None            # None = soczewka „najlepsze dopasowanie" (D-0731-13)
        self._order = pm.ORDER_CORE      # porządek listy — prezentacja, klucz rdzenia nietknięty
        self._settings = QSettings("Horreum", "Horreum")
        self._loading = True             # blokada re-planu na czas budowy kontrolek
        # Podłoga ekranu (D-0801-1) — okno idzie za nią, bo Qt propaguje minimum dziecka w górę.
        self.setMinimumWidth(_MIN_W)
        self._build()
        # Motyw ŻYWY, nie `DEFAULT` (wiz T5 R2): `main` woła `apply_theme` PRZED budową okna,
        # więc widok musi sam przeczytać wybór użytkownika, inaczej jasny start dostaje akcenty
        # ciemne (kontrast 2,0–2,4:1).
        # Motyw od TEGO, KTO GO ZASTOSOWAŁ (wiz T5 N4): `MainWindow` zna nazwę, którą podał
        # `apply_theme`. Rejestr jest fallbackiem dla wywołań bez okna (testy, podgląd).
        self.use_theme(theme_name if theme_name is not None
                       else QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))
        self._loading = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.replan)
        self.replan()

    # ---------------------------------------------------------------- budowa

    def _build(self):
        outer = QVBoxLayout(self)
        self.night_label = QLabel("")
        self.night_label.setWordWrap(True)
        nf = self.night_label.font()          # kotwica nagłówka WAGĄ, nie tylko kolorem (wiz T5 R6)
        nf.setBold(True)
        nf.setPointSizeF(nf.pointSizeF() * 1.15)
        self.night_label.setFont(nf)
        self.counts_label = QLabel("")
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        head = QHBoxLayout()
        head.addWidget(self.night_label, 1)      # STRETCH na kotwicy, nie na pustce (wiz T5 N1):
        #                                         bez niego `wordWrap` oddawał szerokość do minimum
        #                                         i noc zawijała się na 3 linie obok pół ekranu pustki
        # „Szukaj" NA ZEWNĄTRZ zwijanego panelu (wiz T5 #3): to inny TRYB (pomija progi), więc musi
        # przeżyć zwinięcie progów — schowany razem z nimi znikał jedyną drogą do celu spoza progów.
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(i18n.t("planner.find_hint"))
        # MINIMUM, nie tylko maksimum (wiz T5 R3): po przeprowadzce do nagłówka pole ściskało się
        # do 74 px przy placeholderze wymagającym 127 — wejście do trybu, który zwijanie progów
        # miało uratować, było najmniejszą kontrolką ekranu. Krzyżyk = wyjście z trybu jednym klikiem.
        self.find_edit.setMinimumWidth(200)
        self.find_edit.setMaximumWidth(320)
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self.replan)
        # N2: krzyżyk „✕" ma WYCHODZIĆ z trybu szukania, nie tylko czyścić pole — po `clear()`
        # ekran nadal mówił „Tryb szukania: 1 trafienie" nad listą z jednym wierszem z 429.
        # Debounce (300 ms) jest już w `_queue_replan`, więc przy okazji dostajemy żywe szukanie.
        self.find_edit.textChanged.connect(self._queue_replan)
        head.addWidget(QLabel(i18n.t("planner.find_label")))
        head.addWidget(self.find_edit)
        find_btn = QPushButton(i18n.t("planner.find"))
        find_btn.clicked.connect(self.replan)
        head.addWidget(find_btn)
        self.park_btn = QPushButton(i18n.t("planner.park_btn"))
        self.park_btn.clicked.connect(self._on_park)
        head.addWidget(self.park_btn)
        outer.addLayout(head)
        self.counts_label.setProperty("role", "secondary")   # hierarchia nagłówka (wiz T5 #13)
        outer.addWidget(self.counts_label)
        self.warn_label = QLabel("")            # noty `warn` — waga z modelu NIE ginie; kolor z `use_theme`
        self.warn_label.setWordWrap(True)
        outer.addWidget(self.warn_label)
        self.notes_label.setProperty("role", "secondary")
        outer.addWidget(self.notes_label)
        outer.addWidget(self._build_controls())
        self.chips_row = QHBoxLayout()
        outer.addLayout(self.chips_row)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)                 # nieokreślony — nie znamy postępu rachunku nocy
        # Miejsce REZERWOWANE także po ukryciu (wiz T5 #14): pasek wchodził w układ przy każdym
        # przeliczeniu (0,6 s po zmianie progu) i spychał listę o ~20 px — lista skakała pod kursorem.
        sp = self.busy.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.busy.setSizePolicy(sp)
        self.busy.setVisible(False)
        outer.addWidget(self.busy)
        self.table = QTableView()
        self.model = PlannerTableModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Nadmiar szerokości idzie do NOTATKI, nie do pokrycia (wiz T5 #4): pokrycie miało 437 px
        # przy najdłuższej treści 223 px (392/429 wierszy niesie samo „bez klatek"), a notatka —
        # jedyne pole o nieograniczonej długości — dostawała 57 px.
        hh.setStretchLastSection(True)
        hh.setSectionsClickable(False)   # sort nie istnieje (porządek należy do rdzenia) — martwa
        #                                  afordancja przy 429 wierszach kłamie (wiz T5 #15)
        self.table.setTextElideMode(Qt.ElideRight)     # 11 kolumn ma elidować, nie podnosić minimum okna
        self.table.doubleClicked.connect(self._on_row_double_clicked)   # wiz T5 #19
        outer.addWidget(self.table, 1)
        self.empty_note = QLabel(i18n.t("planner.empty"))
        self.empty_note.setAlignment(Qt.AlignCenter)
        self.empty_note.setWordWrap(True)
        self.empty_note.setVisible(False)
        outer.addWidget(self.empty_note, 1)
        outer.addWidget(self._build_orphan_box())
        outer.addWidget(self._build_row_panel())
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._sync_panel()

    def _build_row_panel(self):
        """Panel zaznaczonego celu — JEDYNE miejsce zapisu ekranu (kuratela). Kanon bierzemy
        z `row.target.canon`, czyli z assetu (`targets.load_targets`), NIGDY z wpisanego tekstu:
        „Eastern Veil" wskazuje naraz NGC6992 i NGC6995, więc zapis po nazwie potocznej trafiłby
        w losowy rekord. Pole „Szukaj" filtruje widok i niczego nie zapisuje — reguła jest więc
        spełniona KONSTRUKCYJNIE, nie regulaminowo."""
        self.panel = QGroupBox(i18n.t("planner.panel"))
        lay = QHBoxLayout(self.panel)
        self.no_gaps_label = QLabel("")     # „✓ bez luk" = INFORMACJA, nigdy zapis (D-T4-d),
        #                                     przy KANONIE, bo to opis celu, nie akcja (wiz T5 #17)
        lay.addWidget(self.no_gaps_label)
        self.panel_status = QComboBox()
        # PIERWSZA pozycja = „(bez oznaczenia)" z `data=None` (wiz T5 #1, P1): bez niej combo
        # trzymało status POPRZEDNIEGO celu, więc jeden klik w „Zapisz" wpisywał do bazy status,
        # którego user nie wybrał — a kolumna „Plan" pokazywała w tej samej chwili „—".
        self.panel_status.addItem(i18n.t("planner.status_none"), None)
        for s in _STATUSES:
            self.panel_status.addItem(i18n.t(f"planner.status_{s}"), s)
        self.panel_status.currentIndexChanged.connect(self._sync_save_enabled)
        lay.addWidget(QLabel(i18n.t("planner.status")))
        lay.addWidget(self.panel_status)
        self.panel_priority = QSpinBox()
        self.panel_priority.setRange(0, 99)
        self.panel_priority.setSpecialValueText(i18n.t("planner.priority_none"))   # 0 → NULL
        lay.addWidget(QLabel(i18n.t("planner.priority")))
        lay.addWidget(self.panel_priority)
        self.panel_note = QLineEdit()
        self.panel_note.setPlaceholderText(i18n.t("planner.note_hint"))
        lay.addWidget(self.panel_note, 1)
        # Hierarchia akcji (wiz T5 #9): zapis jest AKCJĄ GŁÓWNĄ (bold, domyślny), zdjęcie płaskie,
        # a „Pokaż klatki" stoi PO ODSTĘPIE — to skok na inny ekran, nie zapis.
        # ŚWIADOMIE bez skrótu „Zaplanuj" (D-0731-15, Zdzin 2026-08-01): drugi przycisk zapisu
        # wpisywałby status, którego user nie wskazał wprost — combo jest jedyną drogą.
        self.save_btn = QPushButton(i18n.t("planner.save_mark"))
        self.save_btn.setDefault(True)
        f = self.save_btn.font()
        f.setBold(True)
        self.save_btn.setFont(f)
        self.save_btn.clicked.connect(self._on_save_mark)
        lay.addWidget(self.save_btn)
        self.clear_btn = QPushButton(i18n.t("planner.clear_mark"))
        self.clear_btn.setFlat(True)
        self.clear_btn.clicked.connect(self._on_clear_mark)
        lay.addWidget(self.clear_btn)
        lay.addSpacing(24)
        self.frames_btn = QPushButton(i18n.t("planner.show_frames"))
        self.frames_btn.clicked.connect(self._on_show_frames)
        lay.addWidget(self.frames_btn)
        return self.panel

    def _sync_save_enabled(self):
        """„Zapisz oznaczenie" żyje TYLKO przy wybranym statusie — przy „(bez oznaczenia)" nie ma
        czego zapisać, a szczery disabled mówi to bez komunikatu (wiz T5 #1)."""
        self.save_btn.setEnabled(self.panel_status.currentData() is not None)

    # ---------------------------------------------------------------- sierota kurateli (R-S0-7)

    def _build_orphan_box(self):
        """Sekcja „oznaczenia bez celu w katalogu" — jedyna powierzchnia tej populacji (R-S0-7).

        DO S0 OZNACZENIE OSIEROCONE BYŁO NIEWIDOCZNE **I** NIEUSUWALNE: `targets.plan` dokleja
        kuratelę przez `marks.get(t.canon)`, więc wiersz `target_plan` na kanonie, którego asset
        nie zna, nie ma jak stać się `TargetRow`; a `_on_clear_mark` kasuje wyłącznie z ZAZNACZONEGO
        wiersza listy. Jedyną drogą była konsola (`horreum target <db> <kanon> --clear`).

        UKRYTA PRZY ZERZE, świadomie: podłoga tego ekranu (D-0801-1) nie ma zapasu w pionie, a stan
        pojawia się raz na przebudowę assetu. Sekcja kosztuje zero pikseli, dopóki nie ma o czym
        mówić — i to jest cała różnica wobec noty w nagłówku, której tu NIE MA (byłaby drugą
        siedzibą tej samej liczby).

        TRZY AKCJE, BO STANY SĄ DWA I OBA MUSZĄ MIEĆ DROGĘ POWROTU:

        * **Przenieś** — żywy wyłącznie dla `moved`, czyli gdy kanon oznaczenia jest dziś ALIASEM
          KATALOGOWYM innego rekordu. Bez tej pozycji sekcja namawiałaby do skasowania kuratelii
          celu, który stoi w katalogu obok, pod nową nazwą (SIN-DOWNGRADE).
        * **Zdejmij** — kasacja wiersza; jedyna akcja dla `unknown`.
        * **Cofnij zdjęcie** — DROGA POWROTU, bez której ta paczka wnosiłaby dokładnie ten dług,
          który domyka. Dla sieroty odtworzenie inną drogą jest NIEMOŻLIWE: i GUI, i CLI walidują
          kanon wobec assetu (`resolve_plan_canon`), a tej nazwy w asecie nie ma. Pozycja jest
          WIDOCZNA ZAWSZE, wygaszona gdy nie ma czego cofać — wzorzec `act_restore` z paska Zbiorów
          (o odwracalności trzeba wiedzieć PRZED pomyłką, nie po niej)."""
        box = QGroupBox(i18n.t("planner.orphans", n=0))
        box.setVisible(False)
        lay = QVBoxLayout(box)
        hint = QLabel(i18n.t("planner.orphans_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.orphan_list = QListWidget()
        # Sufit wysokości, reszta scrollem: sekcja jest wtrętem między listą a panelem i nie ma
        # prawa zjeść ekranu, który należy do planu nocy. Liczba, nie `sizeHintForRow` — na PUSTEJ
        # liście ten rachunek zwraca -1, więc karmiłby `setMaximumHeight` liczbą ujemną.
        self.orphan_list.setMaximumHeight(_ORPHAN_LIST_H)
        self.orphan_list.itemSelectionChanged.connect(self._sync_orphan_buttons)
        lay.addWidget(self.orphan_list)
        row = QHBoxLayout()
        self.orphan_move_btn = QPushButton(i18n.t("planner.orphan_move"))
        self.orphan_move_btn.clicked.connect(self._on_orphan_move)
        row.addWidget(self.orphan_move_btn)
        self.orphan_clear_btn = QPushButton(i18n.t("planner.orphan_clear"))
        self.orphan_clear_btn.clicked.connect(self._on_orphan_clear)
        row.addWidget(self.orphan_clear_btn)
        self.orphan_undo_btn = QPushButton(i18n.t("planner.orphan_undo"))
        self.orphan_undo_btn.setFlat(True)
        self.orphan_undo_btn.setToolTip(i18n.t("planner.orphan_undo_tip"))
        self.orphan_undo_btn.clicked.connect(self._on_orphan_undo)
        row.addWidget(self.orphan_undo_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._orphan_box = box
        # Stan przycisków USTAWIAMY WPROST na starcie, nie licząc na sygnał zaznaczenia: pusta lista
        # nie emituje `itemSelectionChanged`, więc trzy przyciski stałyby aktywne nad niczym (ta sama
        # pułapka, którą `_sync_save_enabled` łapie przy `setCurrentIndex(0)`, wiz T5 R1).
        self._sync_orphan_buttons()
        return box

    def _render_orphans(self, result):
        """Przepisz sekcję z `PlanResult`. Zaznaczenie NIE przeżywa przeliczenia świadomie: lista
        jest krótka, a po każdej akcji jej skład się zmienia — trzymanie kursora na pozycji, której
        już nie ma, byłoby obietnicą bez pokrycia."""
        marks = dict(getattr(result, "orphan_marks", {}) or {}) if result is not None else {}
        self.orphan_list.clear()
        for canon in sorted(marks):
            stan, row, gdzie = marks[canon]
            opis = (i18n.t("planner.orphan_moved_to", where=gdzie)
                    if stan == targets.ORPHAN_MOVED else i18n.t("planner.orphan_unknown"))
            it = QListWidgetItem(i18n.t(
                "planner.orphan_row", canon=canon, status=row["status"],
                note=row["note"] or "", where=opis))
            it.setData(Qt.UserRole, (canon, stan, gdzie,
                                     row["status"], row["priority"], row["note"]))
            self.orphan_list.addItem(it)
        self._orphan_box.setTitle(i18n.t("planner.orphans", n=len(marks)))
        # Sekcja żyje, dopóki JEST populacja ALBO jest co cofnąć — inaczej „Cofnij zdjęcie"
        # znikałoby razem z ostatnią sierotą, czyli dokładnie w chwili, w której bywa potrzebne.
        self._orphan_box.setVisible(bool(marks) or self._orphan_undo is not None)
        self._sync_orphan_buttons()

    def _selected_orphan(self):
        """Dane zaznaczonej sieroty albo None. WŁASNE źródło celu, nie `_selected_canon()`: tamta
        metoda czyta zaznaczenie TABELI planu, a sierota w tabeli nie stoi z definicji — wspólna
        metoda wpisywałaby gest na cudzy cel (klasa wiz T5 #1)."""
        items = self.orphan_list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _sync_orphan_buttons(self):
        dane = self._selected_orphan()
        self.orphan_clear_btn.setEnabled(dane is not None)
        self.orphan_move_btn.setEnabled(dane is not None and dane[1] == targets.ORPHAN_MOVED)
        self.orphan_move_btn.setToolTip(
            i18n.t("planner.orphan_move_tip", where=dane[2]) if dane and dane[2]
            else i18n.t("planner.orphan_move_tip_none"))
        self.orphan_undo_btn.setEnabled(self._orphan_undo is not None)

    def _on_orphan_clear(self):
        dane = self._selected_orphan()
        if dane is None:
            return
        canon, _stan, _gdzie, status, priority, note = dane
        if repo.clear_target_plan(self.con, canon=canon, now=self._now()):
            # PAMIĘĆ ZDJĘCIA zapisana PO udanej kasacji, nie przed: gdyby wiersz zniknął w międzyczasie
            # inną drogą (konsola równolegle), „Cofnij" odtwarzałby oznaczenie, którego nikt nie zdejmował.
            self._orphan_undo = (canon, status, priority, note)
            self.status_message.emit(i18n.t("planner.orphan_cleared", canon=canon))
            self.replan()

    def _on_orphan_move(self):
        """Przeniesienie kuratelii na rekord, który przejął kanon — JEDNA decyzja człowieka, dwa
        zapisy klingi. Status, priorytet i nota przechodzą w komplecie: przenosimy CUDZĄ decyzję,
        a nie zakładamy nowej."""
        dane = self._selected_orphan()
        if dane is None or dane[1] != targets.ORPHAN_MOVED:
            return
        canon, _stan, gdzie, status, priority, note = dane
        # ⛔ CEL DOCELOWY MOŻE JUŻ MIEĆ WŁASNĄ, ŚWIEŻSZĄ KURATELĘ — i to nie jest przypadek
        # brzegowy, tylko GŁÓWNY scenariusz tego stanu: przebudowa assetu przenosi nazwę, człowiek
        # oznacza cel od nowa pod nazwą BIEŻĄCĄ, a stara sierota zostaje. `set_target_plan` pisze
        # po kanonie, więc bez tego guarda „Przenieś" nadpisałoby jego świeższą decyzję STARSZYM
        # wierszem — bezgłośnie i bez drogi powrotu w GUI. Paczka domykająca grupę „gest bez drogi
        # powrotu" nie ma prawa wnieść gestu, który NISZCZY cudzy zapis (bramka pakietu, Fable Z2).
        if targets.plan_marks(self.con).get(gdzie) is not None:
            self.status_message.emit(i18n.t("planner.orphan_move_taken", where=gdzie))
            return
        repo.set_target_plan(self.con, canon=gdzie, status=status, priority=priority,
                             note=note, now=self._now())
        repo.clear_target_plan(self.con, canon=canon, now=self._now())
        self._orphan_undo = None       # oznaczenie nie zginęło — nie ma czego cofać
        self.status_message.emit(i18n.t("planner.orphan_moved", canon=canon, where=gdzie))
        self._replan_keeping(gdzie)

    def _on_orphan_undo(self):
        if self._orphan_undo is None:
            return
        canon, status, priority, note = self._orphan_undo
        repo.set_target_plan(self.con, canon=canon, status=status, priority=priority,
                             note=note, now=self._now())
        self._orphan_undo = None
        self.status_message.emit(i18n.t("planner.orphan_undone", canon=canon))
        self.replan()

    def _build_controls(self):
        """Progi w ZWIJANYM pasku. Zwijamy PRZYCISKIEM ze strzałką, nie `checkable QGroupBox`
        (wiz T5 #3 P1): odznaczony checkbox przy DZIAŁAJĄCYCH progach czyta się w Qt jak „ta grupa
        jest wyłączona" — a progi wtedy nadal tną listę. Tytuł niesie STAN, więc zwinięty pasek
        mówi, czym filtrujesz, zamiast tylko chować kontrolki."""
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        self.controls_toggle = QToolButton()
        self.controls_toggle.setCheckable(True)
        self.controls_toggle.setChecked(True)
        self.controls_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.controls_toggle.setArrowType(Qt.DownArrow)
        self.controls_toggle.setAutoRaise(True)
        self.controls_toggle.toggled.connect(self._on_controls_toggled)
        outer.addWidget(self.controls_toggle, 0, Qt.AlignLeft)
        body = QWidget()
        self._controls_body = body
        outer.addWidget(body)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.night_edit = QDateEdit()
        self.night_edit.setCalendarPopup(True)
        self.night_edit.setSpecialValueText(i18n.t("planner.night_auto"))
        # Minimum = wartość specjalna „noc bieżąca": DOPÓKI user nie tknie pola, noc wybiera rdzeń
        # (`targets.default_night` liczy dobę z DŁUGOŚCI stanowiska, nie ze strefy maszyny) —
        # podstawianie tu `QDate.currentDate()` byłoby DRUGIM właścicielem faktu „która to noc".
        self.night_edit.setMinimumDate(QDate(1970, 1, 1))
        self.night_edit.setDate(QDate(1970, 1, 1))
        self.night_edit.dateChanged.connect(self._queue_replan)
        form.addRow(i18n.t("planner.night"), self.night_edit)

        self.cirrus = QCheckBox(i18n.t("planner.layer_cirrus"))   # D-0731-9: domyślnie OFF
        self.cirrus.toggled.connect(self._queue_replan)
        form.addRow("", self.cirrus)

        self.status_combo = QComboBox()
        self.status_combo.addItem(i18n.t("planner.status_any"), None)
        for s in _STATUSES:
            self.status_combo.addItem(i18n.t(f"planner.status_{s}"), s)
        self.status_combo.currentIndexChanged.connect(self._queue_replan)
        form.addRow(i18n.t("planner.status"), self.status_combo)
        lay.addLayout(form)

        # Progi: wartości PAMIĘTANE między sesjami (`QSettings`, per maszyna — klasa D-B).
        # D-0731-10 zabrania pieczenia progów w ASSECIE, nie zapamiętywania ich w profilu maszyny;
        # zerowanie ich przy każdym starcie kazało powtarzać te same cztery ruchy każdego wieczoru.
        thresholds = QFormLayout()
        right = QFormLayout()
        self._spins = {}
        self.min_size = self._spin(thresholds, "min_size")
        self.min_dark = self._spin(thresholds, "min_dark")
        self.max_mag = self._spin(thresholds, "max_mag")
        self.min_alt = self._spin(thresholds, "min_alt")
        lay.addLayout(thresholds)
        self.min_hours = self._spin(right, "min_hours")

        cost_row = QHBoxLayout()
        # Checkbox Z ETYKIETĄ (wiz T5 #12): nagi kwadracik nie mówi, co włącza.
        self.max_cost_on = QCheckBox(i18n.t("planner.max_cost_on"))   # D-0731-14: domyślnie WYŁĄCZONY
        self.max_cost_on.setChecked(self._read_setting("max_cost_on", 0.0) == 1.0)
        self.max_cost_on.toggled.connect(self._on_max_cost_toggled)
        self.max_cost = QDoubleSpinBox()
        self.max_cost.setRange(1.0, 100.0)
        self.max_cost.setSingleStep(0.5)
        self.max_cost.setValue(self._read_setting("max_cost", _MAX_COST_DEFAULT))
        self.max_cost.setEnabled(self.max_cost_on.isChecked())
        self.max_cost.setMaximumWidth(_SPIN_W)
        self.max_cost.valueChanged.connect(self._queue_replan)
        self.max_cost.valueChanged.connect(lambda _v: self._save_thresholds())
        cost_row.addWidget(self.max_cost_on)
        cost_row.addWidget(self.max_cost)
        cost_row.addStretch(1)
        right.addRow(i18n.t("planner.max_cost"), cost_row)
        # Powrót do 6′/15′/13 mag jednym klikiem — bez niego zapamiętane progi byłyby drogą
        # w jedną stronę, a user nie ma skąd znać wartości domyślnych (są w kodzie, nie na ekranie).
        self.reset_btn = QPushButton(i18n.t("planner.reset_thresholds"))
        self.reset_btn.setToolTip(i18n.t("planner.reset_thresholds_tip"))
        self.reset_btn.clicked.connect(self._on_reset_thresholds)
        right.addRow("", self.reset_btn)
        lay.addLayout(right)
        lay.addStretch(1)
        self._sync_controls_title()
        return box

    def _read_setting(self, name, default):
        """Próg z `QSettings` → float. Wpis nieczytelny (ręczna edycja rejestru, wpis z innej wersji)
        spada na domyślną: ekran ma wystartować, a nie wysypać się na cudzym stringu. Zakres pilnuje
        sam spinbox (`setValue` klampuje), więc wartość spoza widełek nie przejdzie dalej."""
        try:
            return float(self._settings.value(_SETTINGS_PREFIX + name, default))
        except (TypeError, ValueError):
            return default

    def _save_thresholds(self):
        """Zapisz progi (bez debounce'u — `QSettings` to zapis lokalny, a stan ma przeżyć zamknięcie
        okna także wtedy, gdy user zmienił próg i od razu wyszedł)."""
        if self._loading:
            return
        for name, w in self._spins.items():
            self._settings.setValue(_SETTINGS_PREFIX + name, w.value())
        self._settings.setValue(_SETTINGS_PREFIX + "max_cost", self.max_cost.value())
        self._settings.setValue(_SETTINGS_PREFIX + "max_cost_on",
                                1.0 if self.max_cost_on.isChecked() else 0.0)

    def _on_reset_thresholds(self):
        """Wszystkie progi na domyślne + JEDEN re-plan. `_loading` tłumi sygnały pośrednie, więc
        pięć `setValue` nie startuje pięciu rachunków nocy (debounce by je scalił, ale liczenie
        na przypadek nie jest kontraktem)."""
        self._loading = True
        try:
            for name, (_key, default, _lo, _hi, _step) in _THRESHOLDS.items():
                self._spins[name].setValue(default)
            self.max_cost_on.setChecked(False)
            self.max_cost.setValue(_MAX_COST_DEFAULT)
        finally:
            self._loading = False
        self.max_cost.setEnabled(False)
        self._save_thresholds()
        self._sync_controls_title()
        self.replan()

    def _spin(self, form, name):
        """Spinbox progu `name` — widełki, krok i wartość domyślna z `_THRESHOLDS` (SPOT), bieżąca
        wartość z `QSettings`. Rejestruje się w `_spins`, więc zapis i reset nie mają własnej listy."""
        key, default, lo, hi, step = _THRESHOLDS[name]
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setValue(self._read_setting(name, default))
        self._spins[name] = w
        w.setMaximumWidth(_SPIN_W)          # spinbox na „1,00" nie ma prawa jechać przez pół ekranu
        w.valueChanged.connect(self._queue_replan)
        w.valueChanged.connect(lambda _v: self._sync_controls_title())
        w.valueChanged.connect(lambda _v: self._save_thresholds())
        form.addRow(i18n.t(key), w)
        return w

    def _on_max_cost_toggled(self, on):
        self.max_cost.setEnabled(on)
        self._save_thresholds()
        self._queue_replan()

    def _on_controls_toggled(self, shown):
        self._controls_body.setVisible(shown)
        self.controls_toggle.setArrowType(Qt.DownArrow if shown else Qt.RightArrow)
        self._sync_controls_title()

    def _sync_controls_title(self):
        """Tytuł paska niesie STAN progów — zwinięty musi mówić, czym tniesz listę, inaczej user
        widzi krótką listę i nie wie dlaczego (wiz T5 #3)."""
        self.controls_toggle.setText(i18n.t(
            "planner.controls_state", size=f"{self.min_size.value():.0f}",
            dark=f"{self.min_dark.value():.0f}", mag=f"{self.max_mag.value():.1f}",
            alt=f"{self.min_alt.value():.0f}", hours=f"{self.min_hours.value():.1f}"))

    # ---------------------------------------------------------------- chipy zestawu (soczewka)

    def use_theme(self, name):
        """Akcenty CAŁEGO ekranu z ŻYWEGO motywu (wiz T5 R2). Wcześniej wszystkie nowe kolory
        wisiały na `theme.DEFAULT` (ciemnym), a `main` woła `apply_theme` PRZED budową okna —
        start w motywie jasnym malował planera akcentami ciemnymi. Zmierzone skutki: wyszarzenie
        wiersza 2,38:1 na białym (sztywne `128` sprzed poprawki dawało 3,95 — „naprawa" pogorszyła
        dokładnie ten motyw, który miała ratować), ⚠ nota 1,99:1, „bez luk" 2,21:1."""
        self._theme = theme.normalize(name)
        a = theme.accents(self._theme)
        p = theme.palette_spec(self._theme)
        # `bright_text`, nie `gold` (wiz T5 N5): złoto to akcent spichlerza i w jasnym motywie ma
        # 2,72:1 — jedyny sygnał „coś jest nie tak" nie dochodził do progu czytelności (AA 4,5).
        self.warn_label.setStyleSheet(f"color: {p['bright_text']};")
        self.no_gaps_label.setStyleSheet(f"color: {a['ok_green']};")
        self._chip_qss = (
            "QToolButton:checked { background: %s; color: %s; font-weight: bold; "
            "border: 1px solid %s; border-radius: 3px; padding: 2px 8px; }"
            "QToolButton { padding: 2px 8px; }" % (p["highlight"], p["highlight_text"], a["gold"]))
        group = getattr(self, "_chip_group", None)
        for b in (group.buttons() if group is not None else ()):
            b.setStyleSheet(self._chip_qss)
        self.model.use_theme(self._theme)

    def _rebuild_chips(self, result):
        """Chipy zestawów w porządku po lightach + „najlepsze dopasowanie" jako pozycja pierwsza.
        Chip jest SOCZEWKĄ (nic nie znika — `planner_model`), więc przełączenie NIE re-planuje:
        przelicza tylko komórki z tego samego `PlanResult`."""
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        # Etykieta mówi WPROST, że to soczewka, a nie filtr (wiz T5 #2 P1): sam pasek nazw
        # teleskopów czytał się jak zawężanie listy, choć zmienia dwie KOLUMNY, nie zbiór.
        self.chips_row.addWidget(QLabel(i18n.t("planner.chips_label")))
        # Zaznaczony chip na kolorze zaznaczenia ŻYWEGO motywu (`use_theme`): zmierzone 64 vs 81
        # na tle 43 (różnica 17/255, i to zaznaczony był CIEMNIEJSZY) nie odróżniało soczewki.
        names = (None,) + pm.rig_choices(result)
        if self._rig_chip not in names:          # zestaw zniknął (inny park) → wracamy do best-fit
            self._rig_chip = None
        for name in names:
            b = QToolButton()
            b.setCheckable(True)
            b.setText(i18n.t("planner.chip_best") if name is None else name)
            b.setChecked(name == self._rig_chip)
            b.setStyleSheet(self._chip_qss)
            b.setToolTip(i18n.t("planner.chip_tip"))
            b.clicked.connect(lambda _c=False, n=name: self._on_chip(n))
            self._chip_group.addButton(b)
            self.chips_row.addWidget(b)
        self.chips_row.addStretch(1)
        # Porządek listy PRZY chipach, bo to ta sama myśl: chip mówi CZYIMI oczami patrzysz,
        # porządek — czy lista ma iść za tym spojrzeniem. Do T5 chip zmieniał radę, ale nie
        # kolejność, więc „patrzę oczami RC8" zostawiało na górze cele wybrane dla A140R.
        self.chips_row.addWidget(QLabel(i18n.t("planner.order_label")))
        self.order_combo = QComboBox()
        self.order_combo.addItem(i18n.t("planner.order_core"), pm.ORDER_CORE)
        self.order_combo.addItem(i18n.t("planner.order_lens"), pm.ORDER_LENS)
        self.order_combo.setCurrentIndex(0 if self._order == pm.ORDER_CORE else 1)
        self.order_combo.setToolTip(i18n.t("planner.order_tip"))
        self.order_combo.currentIndexChanged.connect(self._on_order)
        self.chips_row.addWidget(self.order_combo)

    def _on_chip(self, name):
        self._rig_chip = name
        self._render_rows()

    def _on_order(self, _index):
        """Zmiana porządku = PRZERYSOWANIE, nie nowy rachunek nocy (jak chip): ten sam `PlanResult`,
        inne ułożenie gotowych wierszy."""
        self._order = self.order_combo.currentData()
        self._render_rows()

    # ---------------------------------------------------------------- rachunek

    def _params(self):
        """Parametry rachunku z kontrolek. `night=None` dopóki user nie tknął daty — wtedy noc
        wybiera rdzeń. Tekst w „Szukaj" włącza tryb `find`, który POMIJA progi (pytasz o konkretny
        obiekt — masz dostać jego okno, nawet gdy nigdy nie wschodzi); mówi o tym nota nad listą."""
        qd = self.night_edit.date()
        night = None if qd == self.night_edit.minimumDate() else date(qd.year(), qd.month(), qd.day())
        find = self.find_edit.text().strip() or None
        return {"night": night, "limit": None, "find": find,
                "layers": targets.ALL_LAYERS if self.cirrus.isChecked() else targets.DEFAULT_LAYERS,
                "status": self.status_combo.currentData(),
                "min_size": self.min_size.value(), "min_dark": self.min_dark.value(),
                "max_mag": self.max_mag.value(), "min_alt": self.min_alt.value(),
                "min_hours": self.min_hours.value(),
                "max_cost": self.max_cost.value() if self.max_cost_on.isChecked() else None}

    def _queue_replan(self, *_a):
        if not self._loading:
            self._debounce.start()

    def replan(self):
        """Policz plan pod BIEŻĄCE parametry. Nowa generacja unieważnia wynik w locie — jeden
        worker naraz, stary wynik ląduje w koszu (kontrolki zostają aktywne)."""
        self._debounce.stop()
        # Zaznaczenie przeżywa KAŻDE przeliczenie, nie tylko zapis (wiz T5 #10): zmiana progu
        # gasiła panel, a wpisana notatka przepadała bez śladu.
        if self._keep_canon is None:
            self._keep_canon = self._selected_canon()
        self._gen += 1
        if self._worker is not None:
            return                       # wynik w biegu i tak przyjdzie ze STARĄ generacją → odrzucony
        self._start(self._gen)

    def _start(self, gen):
        self.busy.setVisible(True)
        worker = PlanWorker(self._db_path, self._params(), gen,
                            con=None if self._db_path else self.con)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        if self._off_thread and self._db_path:
            self._thread = QThread(self)
            worker.moveToThread(self._thread)
            self._thread.started.connect(worker.run)
            worker.finished.connect(self._thread.quit)
            self._thread.finished.connect(self._cleanup_thread)
            self._thread.start()
        else:
            try:
                worker.run()             # inline: done/failed lecą direct = synchronicznie
            finally:
                self._worker = None
                self.busy.setVisible(False)

    def _cleanup_thread(self):
        # ŚWIĘTA KOLEJNOŚĆ (deadlock AB-BA GIL × ~QThread, natywny dump 2026-07-20 → `08992c4`):
        # worker.deleteLater() doręcza się w TEARDOWN wątku (Shiboken::Object::destroy →
        # PyGILState_Ensure). Bez wait() poniższy thread.deleteLater() mógłby doręczyć się na main
        # ZANIM wątek umrze: ~QThread czekałby na wątek TRZYMAJĄC GIL, a wątek na GIL. wait()
        # zwalnia GIL, więc wątek dokańcza destrukcję workera i umiera.
        self._worker.deleteLater()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.busy.setVisible(False)
        if self._pending_gen():
            self._start(self._gen)       # parametry zmieniły się w biegu → licz jeszcze raz

    def _pending_gen(self):
        """Czy na ekranie stoi coś starszego niż bieżące parametry. Liczymy WYŁĄCZNIE generacjami —
        „wynik pusty" i „wynik nieudany" to prawidłowe stany ekranu, a nie powód do kolejnego biegu
        (warunek na `self._result is None` zapętliłby ekran przy bazie bez stanowiska GPS)."""
        return self._shown_gen != self._gen

    @Slot(int, object)
    def _on_done(self, gen, result):
        if gen != self._gen:
            return                       # stale — świeży bieg wystartuje w cleanupie
        self._result = result
        self._shown_gen = gen
        self._rebuild_chips(result)
        self._render_header(result)
        self._render_orphans(result)
        self._render_rows()

    @Slot(int, str)
    def _on_failed(self, gen, message):
        if gen != self._gen:
            return
        self._result = None
        self._shown_gen = gen
        self.model.set_rows(())
        self.night_label.setText(message)
        self.counts_label.setText("")
        self.warn_label.setText("")
        self.notes_label.setText("")
        # Sekcja sierot znika razem z wynikiem: przy nieudanym rachunku (baza bez stanowiska GPS)
        # nie wiemy NIC o kurateli, a stara lista udawałaby świeży pomiar.
        self._render_orphans(None)
        self.empty_note.setVisible(False)
        self.table.setVisible(True)
        self.status_message.emit(message)

    # ---------------------------------------------------------------- render

    def _render_header(self, result):
        """Nagłówek W TRZECH WAGACH (wiz T5 #6/#13): kotwica nocy, lejek jako tekst drugorzędny,
        a noty ROZDZIELONE po wadze — `warn` (park nieustawiony, sprzęt bez zestawu, lighty bez
        filtra na mono) dostaje ostrzegawczy akcent, `info` idzie do drugorzędnych. Waga jest
        liczona w `planner_model.header_notes` i do tej pory widok ją WYRZUCAŁ."""
        find = self.find_edit.text().strip()
        self.night_label.setText(pm.night_text(result))
        # W trybie `find` lejek („1560 → 1 po progach") kłamał: progi są pominięte (wiz T5 #7).
        self.counts_label.setText(
            i18n.t_plural("planner.counts_find", len(result.rows), needle=find) if find
            else pm.counts_text(result))
        warns, infos = [], []
        for level, text in pm.header_notes(result):
            (warns if level == "warn" else infos).append(text)
        if find:
            infos.insert(0, i18n.t("planner.find_note"))
        self.warn_label.setText("\n".join(f"⚠ {t}" for t in warns))
        self.warn_label.setVisible(bool(warns))
        self.notes_label.setText("\n".join(infos))
        self.notes_label.setVisible(bool(infos))

    def _render_rows(self):
        if self._result is None:
            return
        rows = pm.view_rows(self._result, self._rig_chip, order=self._order)
        # Niezapisana notatka nie ma prawa zniknąć przy przeliczeniu (wiz T5 #10): trzymamy ją
        # razem z kanonem i oddajemy, gdy zaznaczenie wróci na TEN SAM cel.
        typed = (self._keep_canon, self.panel_note.text()) if self.panel_note.isModified() else None
        self.model.set_rows(rows)
        empty = not rows
        self.empty_note.setText(i18n.t("planner.empty_find", needle=self.find_edit.text().strip())
                                if self.find_edit.text().strip() else i18n.t("planner.empty"))
        self.empty_note.setVisible(empty)
        self.table.setVisible(not empty)
        # Zaznaczenie wraca na TEN SAM cel, o ile został na liście: `skip` go z niej zdejmuje
        # i wtedy pusty panel jest UCZCIWĄ odpowiedzią („skreśliłeś go", nie „zgubiłem").
        keep = self._keep_canon
        if keep is not None:
            for r, v in enumerate(rows):
                if v.canon == keep:
                    self.table.selectRow(r)
                    break
            self._keep_canon = None
        self._sync_panel()
        if typed is not None and typed[0] == keep and self._selected_canon() == keep:
            self.panel_note.setText(typed[1])
            self.panel_note.setModified(True)

    # ---------------------------------------------------------------- panel wiersza (ZAPIS)

    def _on_row_selected(self, *_a):
        self._sync_panel()

    def _on_row_double_clicked(self, _index):
        """Podwójny klik w wiersz = „Pokaż klatki celu" (wiz T5 #19) — najbardziej naturalne
        miejsce na tę akcję; bez pokrycia jest no-opem, bo przycisk też jest wtedy nieaktywny."""
        self._on_show_frames()

    def _sync_panel(self):
        """Panel odbija ZAZNACZONY wiersz. Brak zaznaczenia = szczery disabled (UI nie kłamie);
        „Pokaż klatki celu" gaśnie osobno, gdy cel nie ma pokrycia — pusty filtr pokazałby
        w gridzie pełną bazę."""
        row = self.selected_row()
        self.panel.setEnabled(row is not None)
        if row is None:
            self.panel.setTitle(i18n.t("planner.panel"))
            self.panel_note.setText("")
            self.no_gaps_label.setText("")
            self.panel_status.setCurrentIndex(0)
            self._sync_save_enabled()      # patrz niżej — `setCurrentIndex(0)` na zerze MILCZY
            return
        src = row.source
        # Kanon w TYTULE panelu (wiz T5 #8): etykieta w rzędzie kontrolek była ściskana przez
        # rozciągane pole notatki i ucinała się do „G(", a panel z trzema przyciskami zapisu
        # musi mówić, KTÓREGO celu dotyczy.
        self.panel.setTitle(i18n.t("planner.panel_of", canon=row.canon))
        # BEZWARUNKOWO — także przy `None` (wtedy „(bez oznaczenia)"): inaczej combo trzyma
        # status poprzedniego celu i „Zapisz" wpisuje cudze zdanie (wiz T5 #1, P1).
        self.panel_status.setCurrentIndex(max(0, self.panel_status.findData(src.plan_status)))
        # Stan przycisku ustawiamy WPROST, nie licząc na sygnał (wiz T5 R1, P1): `setCurrentIndex(0)`
        # na indeksie już zerowym NIE emituje `currentIndexChanged`, więc „Zapisz" zostawał
        # aktywny (bold + pierścień domyślnego) od startu aplikacji do pierwszej zmiany statusu —
        # najczęstszy pierwszy klik sesji trafiał w martwy przycisk i nie dostawał nawet komunikatu.
        self._sync_save_enabled()
        self.panel_priority.setValue(src.priority or 0)
        self.panel_note.setText(src.note or "")
        self.frames_btn.setEnabled(pm.can_show_frames(src))
        self.clear_btn.setEnabled(src.plan_status is not None)
        # Podpowiedź, nie automat (D-T4-d): status jest zdaniem CZŁOWIEKA, a luka zależy od suwaka
        # `min_hours` — automatyczne `done` czyniłoby trwały status funkcją parametru runtime.
        self.no_gaps_label.setText("" if src.coverage.gaps else i18n.t("planner.no_gaps"))

    def _selected_canon(self):
        row = self.selected_row()
        return None if row is None else row.source.target.canon

    def _on_save_mark(self):
        canon = self._selected_canon()
        status = self.panel_status.currentData()
        if canon is None or status is None:
            # Druga bramka OBOK szczerego disabled: przycisk to prezentacja, a zapis nie ma prawa
            # ruszyć bez wybranego statusu (wiz T5 #1 — nigdy więcej cudzego zdania w bazie).
            return
        priority = self.panel_priority.value() or None      # 0 = „bez priorytetu" → NULL
        changed = repo.set_target_plan(
            self.con, canon=canon, status=status,
            priority=priority, note=self.panel_note.text().strip() or None, now=self._now())
        self.status_message.emit(i18n.t("planner.mark_saved" if changed else "planner.mark_same",
                                        canon=canon))
        if changed:
            self._replan_keeping(canon)

    def _on_clear_mark(self):
        canon = self._selected_canon()
        if canon is None:
            return
        changed = repo.clear_target_plan(self.con, canon=canon, now=self._now())
        self.status_message.emit(i18n.t("planner.mark_cleared" if changed else "planner.mark_same",
                                        canon=canon))
        if changed:
            self._replan_keeping(canon)

    def _replan_keeping(self, canon):
        """Po udanym zapisie licz plan od nowa (status zmienia listę — `skip` z niej znika)
        i wróć zaznaczeniem na ten sam cel, o ile został."""
        self._keep_canon = canon
        self.replan()

    def _on_park(self):
        """Dialog parku. Po zmianie oznaczeń plan liczy się od nowa — park ZMIENIA zestawy, więc
        stary wynik opisywałby inny sprzęt (a po scaleniu osi park bywa stęchły — `5dfe28b`)."""
        dlg = ParkDialog(self.con, self._now, parent=self)
        dlg.exec()
        if dlg.changed:
            self.status_message.emit(i18n.t("planner.park_changed", n=dlg.changed))
            self.replan()

    def _on_show_frames(self):
        """Most do gridu (D-0731-7, WĄSKO): emituj KANONY ARCHIWUM celu — jeden cel bywa
        w archiwum pod kilkoma nazwami naraz (`IC410` ORAZ `LBN807`), więc most oddaje sumę.
        Okno zamienia je na `object_id` i ustawia ISTNIEJĄCY facet Obiekt; planer nie składa
        drzewa filtra (druga ścieżka składania złamałaby SPOT `facet_model.compose`)."""
        row = self.selected_row()
        if row is None or not pm.can_show_frames(row.source):
            return
        self.show_frames_for.emit(tuple(row.source.coverage.archive_canons))

    # ---------------------------------------------------------------- cykl życia

    def selected_row(self):
        """`planner_model.ViewRow` zaznaczonego wiersza albo None (seam dla panelu i testów)."""
        sel = self.table.selectionModel()
        rows = sel.selectedRows() if sel else []
        return self.model.row_at(rows[0].row()) if rows else None

    def refresh(self):
        """Świeże klatki (pipeline) zmieniają pokrycie — przelicz nocy od nowa."""
        self.replan()

    def set_busy(self, running):
        """W biegu pipeline'u ekran nie liczy planu na wpół zapisanej bazie (spójnie z osiami)."""
        self.setEnabled(not running)

    def closeEvent(self, event):
        """Zamknięcie w biegu = unieważnienie generacją; wątek dokańcza i sprząta się sam."""
        self._gen += 1
        super().closeEvent(event)
