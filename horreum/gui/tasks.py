"""Widok PORZĄDKI — `TasksView` (F5, PLAN_ux_redesign §6): lista zadań ze STANU bazy + podstrony
osi (teleskop/obserwatorium/przegląd obiektów) montowane w wewnętrznym stacku. Trzecie miejsce
nawigacji `MainWindow` (Dostawa / Zbiory / Porządki).

Glue Qt↔read-model: liczniki liczy `queries.tasks_state` (bieżący STAN tabel, nigdy `count(event)`
— memory horreum-review-queue-from-state); ten plik NIE wykonuje żadnego SQL (meta-test AST
`test_repo_safety.py` skanuje i ten plik). Warstwa widżetów — na whiteliście `test_gui_isolation`.

KIERUNEK IMPORTÓW (F5R2#1): ten moduł importuje widoki osi z `horreum.gui.app` MODULE-LEVEL;
`app.py` importuje `TasksView` WYŁĄCZNIE lazy w `_mount_views` (wzorzec pipeline/grid) — import
na górze `app.py` domknąłby cykl → ImportError na starcie aplikacji.

Kontrakt montażu: `TasksView(con, now_fn, parent)`; pod-widoki osi wystawione jako `.axis_view`/
`.observatory_view`/`.object_view` (MainWindow ALIASUJE je na sobie — kontrakt `_on_stage_finished`/
`_on_pipeline_running` przeżywa przemontowanie bez zmian). `now_fn` FORWARDOWANE do pod-widoków
(F5R#2 — otrzymany argument, nie własny default: akcje osi w podstronach piszą wstrzykniętym
zegarem, asercja tożsamości `_now` w testach stabilna).

Świadomy cykl odświeżania: licznik NIE odświeża się na żywo w trakcie pracy w podstronie —
`refresh_counts()` woła gospodarz przy montażu / po etapie pipeline'u / na wejściu w Porządki,
a sam widok przy powrocie „← Porządki" (user mógł nazwać teleskopy w podstronie)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from horreum.gui import queries, rows
from horreum.gui.app import (
    ObjectAxisView, ObservatoryAxisView, TelescopeAxisView, _utc_now_iso,
)
from horreum.gui.grid import PRESET_DUPS, PRESET_VANISHED
from horreum.gui.rows import TwoPartDelegate

# Definicja listy zadań: (klucz stanu z `tasks_state`, etykieta, akcja). Akcja: numer podstrony
# wewnętrznego stacku (int), nazwa perspektywy Zbiorów (str — sygnał `open_collection`) albo None
# (pozycja INFORMACYJNA — bez powierzchni akcji: XISF to własność formatu, nie robota do zrobienia).
# Wiersze AKCYJNE (akcja ≠ None) z n>0 liczą się do badge'a sidebara — informacja nie jest zadaniem
# (stała obecność XISF w badge = wieczny szum). „Zniknięte" AWANSOWAŁY z informacji na akcję wraz
# z passem obecności (P5/#7): dopóki nie było przebiegu wykrywającego, liczba była martwa i nie było
# jej gdzie rozwinąć — teraz prowadzi do perspektywy z listą klatek bez ani jednej obecnej kopii.
_PAGE_LIST, _PAGE_TELESCOPE, _PAGE_OBSERVATORY, _PAGE_OBJECTS = range(4)
# Szarość wierszy BEZ roboty: pozycje informacyjne (zawsze) i akcyjne z n=0 (wiz F5 #6 — „nic do
# zrobienia" ma być widać bez czytania liczby). Akcyjne z n=0 zostają KLIKALNE: podstrona osi to
# jedyna droga do niej po przemontowaniu nawigacji.
_DIM = QColor(0x88, 0x88, 0x88)
# Szerokość listy zadań. Prawe wyrównanie liczb SKANUJE się w wąskim pasie i ROZJEŻDŻA na szerokim:
# przy oknie 1200 px etykieta lądowała na x≈185, a liczba na x≈1180 — ~900 px pustki między nimi
# (wizytator P1 #2, dług delegata przeniesionego z listwy 220 px na pełną szerokość okna).
# Liczba z POMIARU TREŚCI, nie z oka: najdłuższa etykieta („XISF (nagłówki tylko do odczytu)") = 172 px
# + najszerszy człon drugi („381  ›") = 35 px + `_GAP`/`_PAD` ≈ 230 px. 400 px daje oddech bez
# rozjeżdżania; przy 520 px wzrok znów gubi drogę etykieta→liczba (wizytator P1 tura 2).
_LIST_MAX_W = 400
_TASKS = [
    ("unresolved_lights", "Klatki bez obiektu", _PAGE_OBJECTS),
    ("telescopes_unlabeled", "Teleskopy bez etykiety", _PAGE_TELESCOPE),
    ("observatories_unnamed", "Stanowiska bez nazwy", _PAGE_OBSERVATORY),
    ("dup_frames", "Duplikaty (>1 kopia)", PRESET_DUPS),
    ("xisf_frames", "XISF (nagłówki tylko do odczytu)", None),
    ("vanished_frames", "Zniknięte z dysku", PRESET_VANISHED),
]


class TasksView(QWidget):
    """Miejsce PORZĄDKI: strona 0 = lista zadań ze stanu, strony 1–3 = podstrony osi (te same widoki
    co dawne zakładki, opakowane w pasek „← Porządki"). Klik w zadanie prowadzi do powierzchni:
    podstrona osi albo Zbiory z ustawioną perspektywą (sygnał `open_collection` — duplikatów NIE
    wyraża drzewo filtra, to flaga `only_dups` presetu, R#14). Wiersze akcyjne klikalne ZAWSZE
    (także n=0 — podstrona to jedyna droga do osi po przemontowaniu nawigacji)."""

    open_collection = Signal(str)   # nazwa perspektywy Zbiorów (gospodarz przełącza widok)
    counts_changed = Signal(int)    # badge sidebara: liczba pozycji AKCYJNYCH z n>0

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        # pod-widoki osi z FORWARDOWANYM now_fn (F5R#2) — wystawione dla aliasów MainWindow
        self.axis_view = TelescopeAxisView(con, now_fn=now_fn)
        self.observatory_view = ObservatoryAxisView(con, now_fn=now_fn)
        self.object_view = ObjectAxisView(con, now_fn=now_fn)
        self._build_ui()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        # strona 0: lista zadań
        list_page = QWidget()
        lv = QVBoxLayout(list_page)
        lv.addWidget(QLabel("Porządki — zadania ze stanu bazy"))
        self.tasks = QListWidget()
        # NoSelection: highlight selekcji Qt byłby drugim „zaznaczeniem" obok treści (wzorzec F4R2#3);
        # klik = WYŁĄCZNIE gest usera przez itemClicked (F4R#4 — nigdy selection-based).
        self.tasks.setSelectionMode(QListWidget.NoSelection)
        # Liczba = TREŚĆ zadania → prawa kolumna, pogrubiona, w kolorze wiersza (`strong=True`),
        # więc wyszarzenie wiersza gasi etykietę i liczbę razem (wiz F5 #6).
        self.tasks.setItemDelegate(TwoPartDelegate(self.tasks, strong=True))
        self.tasks.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # elizja zamiast scrolla
        self.tasks.setMaximumWidth(_LIST_MAX_W)
        self.tasks.itemClicked.connect(self._on_task_clicked)
        for key, label, action in _TASKS:
            it = QListWidgetItem(label)
            if action is None:
                # informacyjna (wzorzec app.py — pozycje info): wyszarzona, żeby afordancja nie
                # kłamała w obie strony (wizytator F5 #2 — „wygląda jednakowo, działa różnie")
                it.setFlags(Qt.ItemIsEnabled)
                it.setForeground(_DIM)
            else:
                it.setData(Qt.UserRole, key)           # akcyjna — handler mapuje klucz → akcja
            self.tasks.addItem(it)
        lv.addWidget(self.tasks)
        self.pages.addWidget(list_page)                # _PAGE_LIST

        # strony 1–3: podstrony osi (kolejność MUSI zgadzać się ze stałymi _PAGE_*)
        self.pages.addWidget(self._wrap("Oś teleskopu", self.axis_view))          # _PAGE_TELESCOPE
        self.pages.addWidget(self._wrap("Oś obserwatorium", self.observatory_view))   # _PAGE_OBSERVATORY
        self.pages.addWidget(self._wrap("Przegląd obiektów", self.object_view))   # _PAGE_OBJECTS

    def _wrap(self, title, view):
        """Podstrona osi: pasek powrotu + tytuł + widok. Powrót odświeża listę (stan mógł się
        zmienić — user nazwał teleskopy/scalił stanowiska w podstronie)."""
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        back = QPushButton("← Porządki")
        back.clicked.connect(self._on_back)
        bar.addWidget(back)
        lbl = QLabel(title)
        _f = lbl.font()
        _f.setBold(True)                # tytuł podstrony wybija się nad tekst treści (wizytator #9)
        lbl.setFont(_f)
        bar.addWidget(lbl)
        bar.addStretch(1)
        pv.addLayout(bar)
        pv.addWidget(view, 1)
        return page

    # ---------------------------------------------------------------- odczyt → widok

    def refresh_counts(self):
        """Przeładuj liczniki zadań ze stanu (`queries.tasks_state`) i wyemituj badge
        (`counts_changed` = liczba pozycji akcyjnych z n>0). Woła gospodarz (montaż / po etapie /
        wejście w Porządki) i powrót z podstrony."""
        state = queries.tasks_state(self.con)
        badge = 0
        for row, (key, label, action) in enumerate(_TASKS):
            n = state[key]
            it = self.tasks.item(row)
            # akcyjne z chevronem „›" — wiersz ZAPRASZA klik; informacyjne bez (wizytator F5 #2).
            # Liczba idzie w CZŁON DRUGI (prawa kolumna, `rows.SECONDARY`), nie w tekst etykiety —
            # inaczej liczby nie ustawiają się w kolumnę i nie da się ich skanować (wiz F5 #6).
            it.setText(label)
            it.setData(rows.SECONDARY, f"{n}  ›" if action is not None else str(n))
            if action is not None:
                it.setForeground(QBrush() if n > 0 else _DIM)   # n=0 → wyszarzone, wciąż klikalne
            if action is not None and n > 0:
                badge += 1
        self.counts_changed.emit(badge)
        return badge

    # ---------------------------------------------------------------- akcje

    def _on_task_clicked(self, item):
        key = item.data(Qt.UserRole)
        if key is None:                                # pozycja informacyjna — nie prowadzi nigdzie
            return
        action = next(a for k, _, a in _TASKS if k == key)
        if isinstance(action, int):
            self.pages.setCurrentIndex(action)         # podstrona osi
        else:
            self.open_collection.emit(action)          # Zbiory z perspektywą (np. Duplikaty)

    def _on_back(self):
        self.pages.setCurrentIndex(_PAGE_LIST)
        self.refresh_counts()                          # stan mógł się zmienić w podstronie
