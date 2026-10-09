"""Warstwa widżetów GUI (PySide6 — PLAN_gui §5, PLAN_gui_pipeline §2). Cienka powłoka nad rdzeniem:

- **Read path** = `horreum.gui.queries` (czyste SELECT-y, Qt-free) — lista aktywnych, członkowie
  scaleni „pod" kanonem, audyt eventów.
- **Write path** = WYŁĄCZNIE funkcje usera z `horreum.repo` (jedna klinga → `event`, `actor=user:*`
  składany w repo). Te widżety NIE wykonują żadnego `con.execute` — meta-tripwir AST
  (`tests/test_repo_safety.py`) skanuje też ten plik; każdy literał DML albo SQL dynamiczny tutaj
  wysadziłby bramkę. Cała logika domenowa (FSM/guardy/zapytania) mieszka poza Qt i jest przetestowana
  bez Qt; tu zostaje sama glue Q↔baza (skill `test-isolation-optional-dependencies`).

Kanon GUI (wizytator): stan widoczny BEZ klikania (status/licznik klatek/członkowie w kolumnach i
panelu), UI NIE KŁAMIE (akcja niemożliwa = przycisk wyłączony, nie klik→błąd), cofnięcie zamiast
„czy na pewno?" (scalanie jest odwracalne — `Cofnij scalenie`).

ETAP 2 (PLAN_gui_pipeline): okno aplikacji to `MainWindow` (menu Plik: Otwórz/Nowa baza, nawigacja
między widokami w `QStackedWidget`). Oś teleskopu z etapu 1 to teraz OSADZALNY widok `TelescopeAxisView`;
`TelescopeAxisWindow` zostaje jako cienka powłoka-okno (zgodność wstecz: `python -m horreum.gui` i testy)."""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QLocale, QSettings, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from horreum import db, macro as macro_mod, repo, resolver
from horreum.resolver import forma_karty_object   # SPOT formy karty OBJECT (Qt-wolny)
from horreum.gui import busy, i18n, mapproj, portfolio, queries, rows, theme
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.wb_worker import zdanie_commitu_kart, zdanie_undo_kart
from horreum.gui.config_dialog import AssignConfigDialog
# Kontener strony zbiorów: stałe prezentacji są wartościami jego sygnału, a `_TRASY` (poziom modułu)
# ich potrzebuje; import ciągnie grid (~30 ms przy imporcie okna, zmierzone 2026-10-09).
from horreum.gui.flows.znajdz_view import PREZENTACJA_KLASYCZNA, PREZENTACJA_ZNAJDZ, ZnajdzView
from horreum.gui.observatory_dialog import AssignObservatoryDialog
from horreum.gui.map_view import SitesMapView
from horreum.gui.rows import TwoPartDelegate
from horreum.resolve._text import norm_alnum
from horreum.resolve.catalog import header_form
from horreum.resolve.paths import STACK_KIND, object_folder

# ROLE POZYCJI KOLEJKI PRZEGLĄDU — świadomie POZA pasmem `rows` (SECONDARY/TERTIARY/STRONG zajmują
# `UserRole+1…+3`). Kolejka trzymała payload pod `UserRole+1`, a powód pod `UserRole+2`, czyli
# DOKŁADNIE tam, skąd delegat czyta człon drugi i trzeci: podpięcie `TwoPartDelegate` bez tego
# przesunięcia wypisałoby `object_raw` w kolumnie liczby, a tooltip wiersza informacyjnego —
# w kolumnie adnotacji. Nazwane stałe, bo ta kolizja jest niewidoczna w miejscu użycia.
_REVIEW_TAG = Qt.UserRole                   # dispatch (`_selected_review`) — kontrakt sprzed zmiany
_REVIEW_PAYLOAD = Qt.UserRole + 4
_REVIEW_INFO = Qt.UserRole + 5

# Kolumny listy głównej — indeksy nazwane (czytelne handlery zamiast magicznych liczb).
# Nagłówek = telescop_canon (tożsamość osi po przejściu fitsmirror); Etykieta = nazwa usera.
COL_ID, COL_CANON, COL_LABEL, COL_STATUS, COL_FRATIO, COL_FOCAL, COL_FRAMES = range(7)
# ZAPAS PASKA STANU dla elizji raportu (FH-2). `QStatusBar` nie wystawia szerokości swojego pola
# komunikatu, więc odliczamy od szerokości paska to, czego nie zajmuje: własne marginesy układu
# i uchwyt zmiany rozmiaru w prawym rogu (`_PASEK_MARGINES`), odstęp przed każdym widżetem stałym
# (`_PASEK_ODSTEP`). Poniżej `_PASEK_MIN_KOMUNIKATU` nie tniemy w ogóle — na tak wąskim pasku
# elizja zostawiłaby sam wielokropek, czyli mniej niż ucięte zdanie.
#
# OBIE LICZBY ZMIERZONE, NIE OSZACOWANE (firsthand, 39 pomiarów na trzech skalowaniach): odstęp
# układu to dokładnie 6 px, a pole komunikatu kończy się na `pierwszy_stały.x() − 2` przy lewym
# marginesie 6, czyli zapas = `x − 8`. Wersja z 24 dawała `x − 6` i przebijała pole o stałe 2 px -
# ostatnia kolumna pikseli wielokropka bywała przez to ucięta. Falsyfikator: `zapas` policzony tą
# arytmetyką ma się równać `pierwszy_widoczny_stały.x() − 8`.
_PASEK_MARGINES = 26
_PASEK_ODSTEP = 6
_PASEK_MIN_KOMUNIKATU = 80
# SUFIT RECEPTY jako UDZIAŁ paska, nie liczba pikseli - bo rośnie ona z fontem i ze skalowaniem
# DPI, a chroni przed nią raport, który skaluje się tak samo. Dzisiejsza najdłuższa recepta PL
# (~94 znaki) mieści się z zapasem; sufit jest strażnikiem na przyszłe tłumaczenia i dłuższe
# etykiety menu, nie ograniczeniem stanu bieżącego.
_PASEK_UDZIAL_RECEPTY = 0.45
# SUFIT KOLEJKI PRZEGLĄDU W WIERSZACH, nie w pikselach (W-3) — bo wiersz maluje delegat i jego
# wysokość zależy od fontu i skalowania DPI. Lista dostawała 340 px ramki na 80 px treści (76 %
# pustki), stojąc nad tabelą „Biblioteka", której tego pionu brakowało. Sufit jest potrzebny, bo
# kolejka rośnie do ~45 pozycji: bez niego dopasowanie do treści zabrałoby bibliotekę w całości.
#
# LICZBA WZIĘTA Z POMIARU, NIE Z GŁOWY: wiersz ma 18 px (zmierzone na platformie natywnej), więc
# stara ramka 340 px pokazywała ich osiemnaście. Niższy sufit odbierałby pion dokładnie tam, gdzie
# roboty jest najwięcej - przy pełnej kolejce user widziałby MNIEJ niż przed naprawą (bramka
# pakietu, soczewka repo). Przy tej wartości krótka kolejka zwija się (5 pozycji: 340 → 94 px),
# a długa nie traci ani wiersza.
_KOLEJKA_SUFIT_WIERSZY = 18
# Tagi kolejki przeglądu, które niosą akcję RĘKI, i te z nich, które opisują klatki z NAGROBKIEM
# (S3/R-S2b-1). Jeden właściciel obu zbiorów, bo pytają o nie CZTERY miejsca — wygaszenie przycisku,
# tooltip, drążenie i zapis — a wyliczanka powtórzona cztery razy rozjedzie się przy pierwszym
# nowym kubełku: przycisk aktywny przy drążeniu, które go nie obsługuje, albo odwrotnie.
_CLEARED_TAGS = frozenset({"object_raw_cleared", "nameless_raw_cleared",
                           "nameless_cleared", "nameless_stacks_cleared"})
_ASSIGN_TAGS = frozenset({"object_raw", "nameless_raw",
                          "object_raw_cleared", "nameless_raw_cleared"})
# Kubełki, których drogą naprawy jest KARTA `OBJECT` W PLIKU — i ich połówki cofnięte (R-S3-1).
# Zbiór, nie wyliczanka w trzech `if`-ach: pytają o niego wygaszenie „Napraw nagłówek…", jego
# tooltip, tooltip sąsiada i wejście samej akcji, a rozszczepienie po `cleared` podwoiło każdą
# z tych list. Ta sama figura, co `_REPAIR_TIPS` niżej: kubełek dopisany jutro wchodzi JEDNYM
# słowem albo nie wchodzi wcale — nie połową powierzchni.
#
# Połówka cofnięta zostaje TUTAJ, a poza `_ASSIGN_TAGS`, bo droga naprawy nagrobka nie zależy od
# tego, kto zdjął nazwę, tylko od tego, czy plik ma jak o obiekcie zeznać: writeback wpisuje kartę
# i TYM SAMYM gasi nagrobek (`writeback.py:704-705`). Ręka jest drogą kubełka RAW, nie tego.
_CARD_TAGS = frozenset({"nameless", "nameless_stacks",
                        "nameless_cleared", "nameless_stacks_cleared"})
# POWÓD WYGASZENIA „Napraw nagłówek…" PER KUBEŁEK (R-S3-7) — mapa, nie drabina `if`-ów.
#
# Drabina rosła o jeden człon na każdy nowy kubełek i dwa razy z rzędu zapomniała o kolejnym:
# `object_raw` i `path_proposals` dostawały zdanie „zaznacz kubełek" o wierszu, który user
# WŁAŚNIE zaznaczył — czyli odpowiedź na pytanie, którego nie zadał. Mapa czyni ten dług
# STRUKTURALNYM: bramka przechodzi kolejkę i pyta, czy KAŻDY jej wiersz ma własne zdanie,
# więc kubełek dodany jutro przewróci test, zamiast po cichu dostać cudzą receptę.
#
# Klucz `None` = brak zaznaczenia. Kubełki naprawiane KARTĄ (`nameless`, `nameless_stacks`) mają
# przycisk AKTYWNY, więc ich wpis opisuje, co przycisk zrobi, a nie czego brakuje.
_REPAIR_TIPS = {
    "nameless": "repair.tip",
    "nameless_stacks": "repair.tip",
    # Połówki cofnięte (R-S3-1) mówią WPROST, że karta zdejmie nagrobek — inaczej user widzi
    # aktywny przycisk nad wierszem „cofnięte ręką" i nie wie, czy tamten werdykt przeżyje zapis.
    "nameless_cleared": "repair.tip_cleared",
    "nameless_stacks_cleared": "repair.tip_cleared",
    "nameless_raw": "repair.tip_raw",
    "nameless_raw_cleared": "repair.tip_raw",
    "object_raw": "repair.tip_named",
    "object_raw_cleared": "repair.tip_named",
    "path_proposals": "repair.tip_path",
    "unreadable": "repair.tip_unreadable",
    # R1: kubełek osi SPRZĘTU i jego DRUGA POŁOWA (klatki z zestawem od ręki). Sąsiadują w kolejce,
    # więc muszą mieć własne zdanie — inaczej wygaszony przycisk naprawy odesłałby usera do karty
    # `OBJECT`, która nie ma z nimi nic wspólnego.
    "config_review": "repair.tip_config",
    "config_by_hand": "repair.tip_config",
    None: "repair.tip_pick",
}
# Kubełki osi SPRZĘTU — dwie rozłączne populacje, jedna akcja („Przypisz zestaw…"), bo różni je
# to, SKĄD bierze się grupa, a nie to, co się z nią robi (lustro `_ASSIGN_TAGS` na osi obiektu).
_CONFIG_TAGS = frozenset({"config_review", "config_by_hand"})
# Stałe nagłówków trzymają KLUCZE katalogu (nie stringi) — etykieta rozwiązuje się `_headers()` w czasie
# BUDOWY widżetu, po `i18n.set_lang` w `main` (D-L1: stałe module-level ewaluują się przed set_lang, więc
# string zamroziłby domyślny PL; klucz jest językowo-neutralny).
HEADERS = ["col.id", "axis.tel.col.canon", "axis.tel.col.label", "col.status",
           "axis.tel.col.fratio", "axis.tel.col.focal", "col.frames"]


def _headers(keys):
    """Nagłówki kolumn z katalogu w czasie budowy tabeli (klucze → etykiety bieżącego języka)."""
    return [i18n.t(k) for k in keys]


def _fmt(v):
    """Liczba do komórki: None → '' (teleskop bez wartości), float bez zbędnych zer (`5.6`, `784`)."""
    return "" if v is None else f"{v:g}"


def _przeladuj_wiersze(table, n):
    """Ustaw tabelę na `n` wierszy PRZEZ ZRZUCENIE STARYCH — jedyna wolna droga przeładowania.

    `setRowCount(n)` na tabeli, która ma wiersze ORAZ zaznaczenie, każe modelowi zaznaczenia
    przeliczać zakresy przy KAŻDYM `setItem`, więc koszt jest kwadratowy. Zmierzone na 763
    wierszach kubełka RAW (firsthand 2026-08-04, kopia żywej `pf4`): **138 s** — Windows zdążył
    dopisać oknu „(brak odpowiedzi)", a jeden przebieg zjadł ~100 s CPU. Zrzucenie wierszy hurtem
    daje **0,26 s** (offscreen 57,7 → 0,10), czyli ~530×.

    `clearSelection()` jest PUŁAPKĄ, nie poprawką: kasowanie zaznaczenia z 763 wierszy samo jest
    kwadratem i mierzy **228 s**, czyli GORZEJ niż nic nie robić. Liczy się wyłącznie to, że stare
    wiersze znikają JEDNYM ruchem, zabierając zaznaczenie ze sobą.

    Właściciel reguły jest jeden (SPOT): każde przeładowanie tabeli w tym module idzie tędy —
    zbiory małe dziś nie płacą nic, a nie ma wtedy dwóch dróg, z których jedna czeka na dane."""
    table.setRowCount(0)
    table.setRowCount(n)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


_NUM_ALIGN = Qt.AlignRight | Qt.AlignVCenter   # liczby prawo-wyrównane (skanowalność magnitud, wizytator T1/#2)

# Rola motywu (nasza nazwa) → QPalette.ColorRole (F6 §7 — składanie QColor w warstwie widżetów z
# Qt-wolnych hexów `theme.palette_spec`). `disabled_text` obsłużone osobno (grupa Disabled).
_PALETTE_ROLES = {
    "window": QPalette.Window, "window_text": QPalette.WindowText,
    "base": QPalette.Base, "alt_base": QPalette.AlternateBase, "text": QPalette.Text,
    "button": QPalette.Button, "button_text": QPalette.ButtonText, "bright_text": QPalette.BrightText,
    "highlight": QPalette.Highlight, "highlight_text": QPalette.HighlightedText,
    "tooltip_base": QPalette.ToolTipBase, "tooltip_text": QPalette.ToolTipText,
    "link": QPalette.Link, "placeholder": QPalette.PlaceholderText,
}


def _build_palette(name):
    """Złóż QPalette z motywu `name` (MUSI być znormalizowany). Disabled dla tekstu = `disabled_text`."""
    spec = theme.palette_spec(name)
    pal = QPalette()
    for key, role in _PALETTE_ROLES.items():
        pal.setColor(role, QColor(spec[key]))
    disabled = QColor(spec["disabled_text"])
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    return pal


def apply_theme(app, name):
    """Zastosuj motyw do CAŁEJ aplikacji: Fusion + QPalette (propaguje do otwartych okien) + QSS
    akcentów; podłącz kolory stanów gridu/facetów (SPOT). `name` znormalizowany (`theme.normalize`).
    Import grid/facets lazy — unika cyklu z warstwą Porządków (F5R2#1) i pozostaje spójny ze stylem
    importów widoków w `_mount_views`."""
    from horreum.gui import facets, grid, map_view, projection_dialog, rows, tasks
    app.setStyle("Fusion")
    app.setPalette(_build_palette(name))
    app.setStyleSheet(theme.qss(name))
    grid.use_theme(name)
    facets.use_theme(name)
    projection_dialog.use_theme(name)   # kolor nagłówka raportu (P-C) — QSS ról nie sięga QPlainTextEdit
    tasks.use_theme(name)               # szarość wierszy bez roboty (P-C) — QBrush, nie QSS
    map_view.use_theme(name)         # kolory mapy z motywu (F8) — init na starcie + przełączenie
    rows.use_theme(name)             # człon drugi wierszy (P1) — delegat czyta kolor NA ŻYWO w paint,
                                     # więc zwykły repaint wystarczy (bez `refresh_theme`)
    use_theme(name)                  # szarość pozycji kolejki przeglądu bez drogi dalej (wiz #11)


# Szarość pozycji kolejki przeglądu, które NIE prowadzą nigdzie (informacyjne albo z zerem).
# Wzorzec `tasks._DIM`: QBrush, nie QSS — QSS nie sięga pojedynczej pozycji `QListWidget`.
_DIM: dict[str, QColor] = {}
# Kolor połówki kubełka z NAGROBKIEM (R-S3-3) — „to Twój werdykt, nie brak wiedzy". `warn`, nie
# `gold`: złoto jest akcentem MARKI i w motywie jasnym ma 2,7:1, więc do tekstu się nie nadaje
# (`theme.py` §akcenty); bursztyn ma 7,4:1 / 6,3:1 i jest tam wprost przeznaczony do tekstu.
_WERDYKT: dict[str, QColor] = {}
# Dwa SYGNAŁY werdyktu ręki, każdy o innym twierdzeniu - trzymane osobno, bo osobno się je stawia
# (firsthand 0810): znacznik `↺` mówi „to Twój werdykt" i należy się KAŻDEJ cofniętej pozycji, także
# takiej bez rodzica na ekranie; wcięcie mówi „jestem połówką wiersza NAD sobą" i wolno je postawić
# tylko wtedy, gdy ten wiersz naprawdę tam stoi.
#
# BP-2 (bramka pakietu, wizytacja 0810): glif miał tu WŁASNY literał `_ZNACZNIK` obok
# `queries.CLEARED_MARK` - dwóch właścicieli jednego faktu. Czytamy go teraz PRZEZ ATRYBUT modułu
# (`queries.CLEARED_MARK` - `queries` jest importowany jako moduł, nie `from queries import
# CLEARED_MARK`): import nazwy zamroziłby wartość przy starcie procesu, a podmiana w teście
# (`monkeypatch.setattr(queries, "CLEARED_MARK", …)`) nie miałaby wtedy czego zmienić.
#
# W-5 (wizytacja 0810): wcięcie przestało być spacjami w tekście (jechało do schowka i wersji EN,
# a przy elizji zjadało miejsce nazwie) - poziom niesie teraz rola `rows.INDENT` (int), którą delegat
# zamienia na px z metryki fontu przy malowaniu (`rows.TwoPartDelegate.primary_rect`).


def _etykieta_cofnieta(etykieta):
    """Etykieta cofniętej pozycji kolejki: znacznik + odstęp + tekst - JEDNO miejsce formatowania
    dla wszystkich CZTERECH wołających (BP-2): pętla `object_review` i trzy `*_cleared_line`.
    WCIĘCIE nie wchodzi do tego stringa (rola `rows.INDENT`, W-5) - sierota bez rodzica dostaje TEN
    SAM tekst co połówka w parze, różni je wyłącznie dana wcięcia, którą ustawia wołający."""
    return f"{queries.CLEARED_MARK}  {etykieta}"


def use_theme(name):
    """Kolory pozycji kolejki Z MOTYWU (wzorzec `tasks.use_theme`) — nigdy literałem, bo sztywna
    szarość przeszła kiedyś w motywie jasnym z kontrastem 3,54:1, poniżej AA."""
    _DIM["fg"] = QColor(theme.accents(name)["secondary_text"])
    _WERDYKT["fg"] = QColor(theme.accents(name)["warn"])


use_theme(theme.DEFAULT)             # init przy imporcie (QColor bez QApplication — jak stałe modułu)


def _fmt_event_ts(ts):
    """Znacznik czasu audytu do minut: „2026-07-02T18:21:44.4+00:00" → „2026-07-02 18:21" (mikrosekundy
    i strefa to szum w liście historii — wizytator C2). Pusty/nietypowy → zwróć jak jest."""
    return ts[:16].replace("T", " ") if ts and "T" in ts else (ts or "")


def _copy_reason(kind, reason):
    """Powód nieczytelności do komórki (Z6, P4-2) - JEDYNY właściciel formatowania tej komórki.

    RODZAJ STOI PRZED DIAGNOZĄ, bo to on mówi, gdzie szukać winy: „dysk/dostęp: …" (system nie
    oddał bajtów - plik może być zdrowy) albo „nagłówek nie przechodzi parsera: …" (plik do
    zgłoszenia). Samo „kopia nieczytelna" oskarżało plik i wysłało Zdzinia na dysk po zdrowy plik.
    Trzeci rodzaj, „baza danych: …", nie jest faktem o pliku: zawiódł zapis albo brama po naszej
    stronie, a bez etykiety sama diagnoza („OperationalError…") też kierowałaby winę na plik.
    Diagnoza przychodzi z kolumny bez prefiksu dziennika (lista i tak nazywa się „Kopie
    nieczytelne"). Brak rodzaju (rodzaj nieznany: wiersz sprzed 0019 albo wyjątek bez kodu systemu,
    którego nie dało się rozstrzygnąć) → sama diagnoza; brak diagnozy → myślnik: „nie wiem" jest
    faktem, pusta komórka wygląda na brak danych. Rodzaj bez diagnozy dostaje myślnik w miejscu
    opisu - rodzaj jest wtedy jedynym faktem, więc nie znika."""
    diagnoza = reason or i18n.t("copy.no_reason")
    if kind == "io":
        return i18n.t("copy.reason_io", reason=diagnoza)
    if kind == "parse":
        return i18n.t("copy.reason_parse", reason=diagnoza)
    if kind == "db":
        return i18n.t("copy.reason_db", reason=diagnoza)
    return diagnoza


def _fmt_obs_date(s):
    """Data klatki do sekund: „…T19:45:02.6075262" → „…T19:45:02" (7 cyfr ułamka to szum wizualny —
    wizytator O2); pełna wartość zostaje w tooltipie. Pusty → ''."""
    return s.split(".")[0] if s and "T" in s else (s or "")


class TelescopeAxisView(QWidget):
    """Osadzalny widok osi TELESKOP: lista kanonicznych teleskopów (lewa) + szczegół zaznaczonego
    (prawa: członkowie scaleni pod nim, audyt). Akcje usera (`label`/`approve`/`merge`/`unmerge`)
    idą przez `repo`. Komunikaty statusu emituje sygnałem `status_message` — pasek statusu należy do
    okna-gospodarza (`MainWindow`/`TelescopeAxisWindow`), nie do widoku.

    `con` = otwarte połączenie RW (NIE własność widoku — zamyka je okno/gospodarz). `now_fn` = źródło
    czasu akcji (ISO-8601); domyślnie zegar UTC, wstrzykiwalne dla testów."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._loading = False                # tłumi itemChanged podczas programowego wypełniania
        self._source_mergeable = False       # czy zaznaczony wiersz może być źródłem scalenia
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: tabela aktywnych + pasek akcji ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(i18n.t("axis.tel.active")))
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(_headers(HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Szerokości: kolumny do treści, Etykieta (nazwa usera) rośnie — spójne z osią OBSERWATORIUM;
        # `stretchLastSection` rozpychał „Klatki" i ucinał ją na wąsko (wizytator T2).
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_LABEL, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self._edit_triggers = self.table.editTriggers()   # przywracane po set_busy(False) (wizytator T3)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.table)

        actions = QHBoxLayout()
        self.btn_approve = QPushButton(i18n.t("axis.tel.approve"))
        self.btn_approve.clicked.connect(self._on_approve)
        actions.addWidget(self.btn_approve)
        actions.addStretch(1)
        actions.addWidget(QLabel(i18n.t("axis.tel.merge_into")))
        self.combo_target = QComboBox()
        self.combo_target.currentIndexChanged.connect(self._sync_merge_enabled)
        actions.addWidget(self.combo_target)
        self.btn_merge = QPushButton(i18n.t("action.merge"))
        self.btn_merge.clicked.connect(self._on_merge)
        actions.addWidget(self.btn_merge)
        lv.addLayout(actions)

        # --- prawa: szczegół zaznaczonego ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel(i18n.t("axis.tel.merged_under")))
        self.members = QListWidget()
        self.members.itemSelectionChanged.connect(self._sync_unmerge_enabled)
        rv.addWidget(self.members)
        self.btn_unmerge = QPushButton(i18n.t("action.unmerge"))
        self.btn_unmerge.clicked.connect(self._on_unmerge)
        rv.addWidget(self.btn_unmerge)
        rv.addWidget(QLabel(i18n.t("axis.history")))
        self.events = QListWidget()
        rv.addWidget(self.events)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter)

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self):
        """Przeładuj listę z read-modelu (źródło prawdy = baza; brak własnego cache, §5). Zachowuje
        zaznaczenie po `telescope_id`, a nie po numerze wiersza (po merge wiersze się przesuwają)."""
        prev = self._selected_telescope_id()
        self._loading = True
        try:
            rows = queries.active_telescopes(self.con)
            _przeladuj_wiersze(self.table, len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_cell(r, COL_ID, str(row["id"]), data=row["id"])
                self._set_cell(r, COL_CANON, row["telescop_canon"])
                self._set_cell(r, COL_LABEL, row["label"] or "", editable=True)
                self._set_cell(r, COL_STATUS, row["status"])
                self._set_cell(r, COL_FRATIO, _fmt(row["f_ratio_nominal"]), align=_NUM_ALIGN)
                self._set_cell(r, COL_FOCAL, _fmt(row["focal_nominal"]), align=_NUM_ALIGN)
                self._set_cell(r, COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
                if row["id"] == prev:
                    target_row = r
        finally:
            self._loading = False
        if target_row >= 0:
            self.table.selectRow(target_row)
        elif self.table.rowCount():
            self.table.selectRow(0)
        else:
            # pusty stan ma sensowny komunikat, nie gołe nagłówki (wizytator P3)
            self.status_message.emit(i18n.t("axis.tel.empty_status"))
        self._on_selection_changed()

    def _set_cell(self, r, c, text, *, editable=False, data=None, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # tylko etykieta jest edytowalna in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if align is not None:                 # liczby prawo-wyrównane (skanowalność, wizytator T1)
            item.setTextAlignment(align)
        if data is not None:                  # telescope_id na kolumnie ID (kotwica wiersza)
            item.setData(Qt.UserRole, data)
        self.table.setItem(r, c, item)

    def _selected_telescope_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_ID)
        return item.data(Qt.UserRole) if item else None

    def _selected_status(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_STATUS)
        return item.text() if item else None

    def _on_selection_changed(self):
        """Odśwież panel szczegółu (członkowie + audyt) i stany przycisków dla zaznaczonego wiersza.
        Stany przycisków są SZCZERE: akcja, która i tak dałaby `ValueError`/no-op, jest wyłączona —
        UI nie kłamie (approve scalonego/już-approved, merge źródła z członkami albo bez targetu)."""
        tid = self._selected_telescope_id()

        self.members.clear()
        members = queries.merged_under(self.con, tid) if tid is not None else []
        for m in members:
            it = QListWidgetItem(
                f'#{m["id"]}  {queries.telescope_label(m)}  ·  {m["status"]}')
            it.setData(Qt.UserRole, m["id"])
            self.members.addItem(it)

        self.events.clear()
        if tid is not None:
            for e in queries.axis_events(self.con, telescope_id=tid):
                self.events.addItem(f'{_fmt_event_ts(e["ts"])}  ·  {e["verb"]}  ·  {e["actor"]}')

        # Cel scalenia z PLACEHOLDEREM na wejściu (currentData=None): merge to świadoma deklaracja
        # „to ten sam teleskop" — nie wolno go wyzwolić jednym klikiem w przypadkowy pierwszy wiersz
        # (wizytator P2). `blockSignals` — przebudowa listy nie ma sypać `currentIndexChanged`.
        self.combo_target.blockSignals(True)
        self.combo_target.clear()
        self.combo_target.addItem(i18n.t("axis.pick_target"), None)
        for t in queries.active_telescopes(self.con):
            if t["id"] != tid:                # cel ≠ źródło → self-merge strukturalnie niemożliwy
                self.combo_target.addItem(
                    f'#{t["id"]}  {queries.telescope_label(t)}', t["id"])
        self.combo_target.setCurrentIndex(0)  # placeholder — użytkownik musi wybrać cel świadomie
        self.combo_target.blockSignals(False)

        self.btn_approve.setEnabled(tid is not None and self._selected_status() != "approved")
        # źródło mergowalne tylko gdy kanoniczne BEZ członków (inwariant głębokość ≤ 1, §3a) i JEST jakiś
        # realny cel (count>1: placeholder + ≥1 teleskop). Sam wybór celu rozstrzyga `_sync_merge_enabled`.
        self._source_mergeable = (tid is not None and not members and self.combo_target.count() > 1)
        self._sync_merge_enabled()
        self._sync_unmerge_enabled()

    def _sync_merge_enabled(self):
        """„Scal" aktywny dopiero gdy źródło jest mergowalne ORAZ wskazano REALNY cel (nie placeholder).
        Wołane przy zmianie zaznaczenia i przy zmianie celu w combo — UI nie kłamie i nie scala na ślepo."""
        self.btn_merge.setEnabled(self._source_mergeable and self.combo_target.currentData() is not None)

    def _sync_unmerge_enabled(self):
        self.btn_unmerge.setEnabled(bool(self.members.selectedItems()))

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU osi (szczery disabled — UI nie kłamie, że
        można pisać, gdy worker pisze do bazy w tle, §6). Po etapie gospodarz woła `set_busy(False)`,
        co przez `_on_selection_changed` przywraca SZCZERE stany przycisków dla zaznaczenia."""
        if busy:
            self.btn_approve.setEnabled(False)
            self.btn_merge.setEnabled(False)
            self.btn_unmerge.setEnabled(False)
            self.combo_target.setEnabled(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # zamknij in-line edyt etykiety (T3)
        else:
            self.table.setEditTriggers(self._edit_triggers)
            self.combo_target.setEnabled(True)
            self._on_selection_changed()

    # ---------------------------------------------------------------- akcje → repo (jedna klinga)

    def _flash(self, msg):
        self.status_message.emit(msg)

    def _on_item_changed(self, item):
        """Edycja in-line etykiety → `repo.label_telescope`. Pusty label → `ValueError` (kasowanie
        etykiety poza v1) złapany i pokazany, widok wraca do prawdy bazy (refresh)."""
        if self._loading or item.column() != COL_LABEL:
            return
        tid = self.table.item(item.row(), COL_ID).data(Qt.UserRole)
        try:
            changed = repo.label_telescope(
                self.con, telescope_id=tid, label=item.text(), now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.tel.label_rejected", e=e))
            self.refresh()
            return
        self._flash(i18n.t("axis.tel.label_saved") if changed else i18n.t("axis.tel.label_unchanged"))
        self.refresh()

    def _on_approve(self):
        tid = self._selected_telescope_id()
        if tid is None:
            return
        try:
            changed = repo.approve_telescope(self.con, telescope_id=tid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.tel.approve_failed", e=e))
            return
        self._flash(i18n.t("axis.tel.approved") if changed else i18n.t("axis.tel.already_approved"))
        self.refresh()

    def _on_merge(self):
        src = self._selected_telescope_id()
        tgt = self.combo_target.currentData()
        if src is None or tgt is None:        # brak źródła albo placeholder zamiast celu
            return
        try:
            changed = repo.merge_telescope(
                self.con, source_id=src, target_id=tgt, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.merge_failed", e=e))
            return
        self._flash(i18n.t("axis.merged", src=src, tgt=tgt) if changed
                    else i18n.t("axis.tel.already_merged"))
        self.refresh()

    def _on_unmerge(self):
        sel = self.members.selectedItems()
        if not sel:
            return
        mid = sel[0].data(Qt.UserRole)
        try:
            changed = repo.unmerge_telescope(self.con, telescope_id=mid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.unmerge_failed", e=e))
            return
        self._flash(i18n.t("axis.unmerged", mid=mid) if changed
                    else i18n.t("axis.tel.already_canonical"))
        self.refresh()


# ============================================================ oś OBIEKT (PLAN_gui_object + #8/P4)

# „Godziny" (FH-10) - naświetlenie lightów pod filtrami biblioteki (`queries.library_exposure`),
# rozbicie per filtr w tooltipie. Liczba klatek nie mówi, ile materiału jest: 40 subów po 30 s
# i 40 po 600 s to ta sama liczba w kolumnie „Klatki".
OBJ_COL_CANON, OBJ_COL_CATALOG, OBJ_COL_FRAMES, OBJ_COL_HOURS = range(4)
OBJ_HEADERS = ["object.col.name", "object.col.catalog", "col.frames", "object.col.hours"]
FRAME_COL_SHA, FRAME_COL_TEL, FRAME_COL_CAM, FRAME_COL_FILTER, FRAME_COL_DATE, FRAME_COL_PRESENT, \
    FRAME_COL_PATH = range(7)
FRAME_HEADERS = ["frame.col.sha", "frame.col.telescope", "frame.col.camera", "frame.col.filter",
                 "frame.col.date", "frame.col.present", "col.path"]
# Tryb „kopie" prawego panelu (Z6/P4 — drążenie kubełka `unreadable` do dokładnych location).
COPY_COL_PATH, COPY_COL_VOLUME, COPY_COL_PRESENT, COPY_COL_MARKED, COPY_COL_REASON = range(5)
COPY_HEADERS = ["col.path", "copy.col.volume", "copy.col.present", "copy.col.marked",
                "copy.col.reason"]
# Sufit szerokości „Ścieżki" w trybie „kopie" (P4-2): resztę panelu bierze „Powód", a pełną
# ścieżkę niesie tooltip - dlaczego tak, mówi `ObjectAxisView._show_copies`. Wartość z pomiaru
# na prawdziwym foncie (Segoe UI 9 pt, 2026-09-26): trzy krótkie kolumny zajmują 215 px, panel
# ma 581 px przy oknie 1310 i 472 px przy podłodze 1073. Sufit 320 zostawiał „Powodowi" 46 px
# w domyślnym oknie i przepychał go za prawą krawędź na podłodze; 200 daje mu 166 px i 57 px
# i nie łamie gwarancji „Powód bez przewijania na podłodze".
COPY_PATH_MAX_PX = 200


PATH_STACKS_PAYLOAD = "stacks"
"""Payload wiersza „…z tego ze ścieżki" spod kubełka GOTOWYCH STOSÓW (E3-1). Ten sam tag
`path_proposals` co pod RAW-em, bo akcja jest ta sama (okno potwierdzania, klinga ręki ze źródłem
`path`); payload mówi, KTÓRĄ populację wiersz liczy - drążenie i okno pokazują dokładnie ją."""


def path_proposals_for(con, payload):
    """Propozycje szczebla ścieżki populacji ZAZNACZONEGO wiersza kolejki (E3-1).

    Jeden filtr dla drążenia i okna: liczba przy wierszu, lista klatek w panelu i pozycje w oknie
    mają opisywać ten sam zbiór. Bez niego wiersz spod stosów otwierałby też RAW-y, a „z tego"
    przy nim kłamałoby o tym, co zatwierdza gest."""
    stosy = payload == PATH_STACKS_PAYLOAD
    return tuple(p for p in resolver.path_proposals(con) if p.stack_tree == stosy)


def plan_kart_sciezki(con, canon, frame_ids):
    """Plan karty `OBJECT` dla klatek zatwierdzanych ze ścieżki (O3 krok 1, decyzja usera
    2026-09-26: nagłówek i folder mają mówić to samo) → `(wartość, touched, skipped)`.

    ZERO ZAPISU: to jest ten sam silnik makr i te same bramki celu (`macro.resolve_target`: RAW
    read-only, brak obecnej kopii, wiele obecnych kopii, skompresowany master, degenerat, brak
    `header_hash`), którymi idzie „Napraw nagłówek…" - lista pominiętych nie jest drugą regułą.
    Operacja `add`: karta, która już JEST (także z inną wartością), nie zostanie nadpisana, tylko
    pominięta z powodem („karta juz istnieje") - rozjazd pliku z folderem rozstrzyga człowiek.

    Wartość = `header_form(canon)` (`NGC 7635`), SPOT formy nagłówka. Dwie bramki PRZED silnikiem
    pomijają całą pozycję z jednym powodem: wartość łamiąca reguły karty FITS (ten sam właściciel,
    `writeback.card_violation`, co przy zapisie) oraz wartość, której drabina resolvera NIE sprowadza
    z powrotem do `canon` - karta z taką nazwą przeniosłaby klatkę po re-syncu z potwierdzonego
    obiektu do innego albo do „nierozpoznanych" (np. kanon z aliasu folderu, którego nagłówek nie
    zna). `touched` = `PendingPreview` do `repo.stage_pending`; `skipped` = `[(frame_id, path,
    powód)]`."""
    from horreum import writeback        # lazy: astropy - jak w `_validate_object_value`
    forma = forma_karty_object(con, canon)
    value = forma if forma is not None else header_form(canon)
    naruszenie = writeback.card_violation("OBJECT", value, new_card=True)
    powod = None
    if naruszenie is not None:
        powod = i18n.t("path.card_skip.invalid", value=value, reason=naruszenie.reason)
    elif forma is None:
        powod = i18n.t("path.card_skip.no_roundtrip", value=value, canon=canon)
    if powod is not None:
        return value, [], [(fid, "", powod) for fid in frame_ids]
    md = macro_mod.MacroDef(assign=macro_mod.Assign(
        keyword="OBJECT", op="add", expr=repr(value), value_type="str"))
    run = macro_mod.run_macro(
        md, list(frame_ids),
        targets_fn=lambda ids: queries.writeback_frame_targets(con, ids),
        cards_fn=lambda fid: queries.frame_cards(con, fid))
    return value, list(run.touched), [(s.frame_id, s.path, s.reason) for s in run.skipped]


class ConfirmPathObjectsDialog(QDialog):
    """„Zatwierdź ze ścieżki…" — POWIERZCHNIA POTWIERDZANIA propozycji szczebla ścieżki (S2,
    D-OW-2/**B**). To jest cena wariantu B i bez niej segment nie istnieje: przebieg resolvera
    liczy kandydatów i NIE PISZE ani jednego wiersza osi obiektu, więc bez tego okna 707 klatek
    zostaje bezimiennych mimo działającego szczebla.

    JEDNOSTKĄ PRZEGLĄDU JEST NAZWA, NIE KLATKA: 707 klatek daje ≈35 pozycji. Lista per klatka
    byłaby listą, której nikt nie przeczyta — a przeczytać ją trzeba, bo 232 klatki trafiają
    w 21 kanonów, których w bazie NIE MA (`NGC6960` obok istniejących `NGC6992` i `Veil` to jeden
    obiekt nieba w trzech pozycjach facetu). Dlatego każda pozycja niesie ZNACZNIK „NOWA w bazie" —
    to właśnie te pozycje mają przejść przez oko.

    Domyślnie zaznaczone są WSZYSTKIE (akcja nazywa się „Zatwierdź wszystko"), odznaczenie jest
    wyjątkiem — 35 kliknięć na starcie zamieniłoby jeden gest w sesję klikania.

    ZAPIS IDZIE TĄ SAMĄ KLINGĄ, KTÓRĄ PISZE RĘKA (`repo.user_assign_object`), ze źródłem `path`
    i BEZ aliasu: jeden pisarz osi, nie dwóch — inaczej „Cofnij" z S2b widziałby jedną populację
    z dwóch. Alias z segmentu ścieżki nie powstaje, bo segment nie trafi żadnego przyszłego
    `object_raw` (D-OW-2 pkt 4); nazwy potoczne wpisu słownika zasieje najbliższy `Rozwiąż`.

    KARTA DO PLIKU (O3 krok 1, decyzja usera 2026-09-26): nagłówek i folder mają mówić to samo,
    więc ten sam klik dopisuje też kartę `OBJECT = header_form(kanon)` tam, gdzie plik na to
    pozwala. WZORZEC „Napraw nagłówek…" (`RepairHeaderDialog`) 1:1, bez nowej drogi zapisu: plan
    silnikiem makr (`plan_kart_sciezki`, bramki celu `macro.resolve_target`), staging
    `repo.stage_pending`, commit `WritebackRunner` z re-syncem zeznania w `writeback.commit`,
    jednorazowe „Cofnij" do zamknięcia okna i „Rozwiąż teraz" delegowane do Dostawy. Gest
    commituje sam, bo tak robi gest wzorcowy (staging bez commitu osierociłby `run_id`).
    KOLEJNOŚĆ: najpierw baza (klinga pyta o przesłankę „nagłówek milczy", więc karta zapisana
    przed nią zamieniłaby potwierdzenie w dryf), potem pliki - i tylko te klatki, które klinga
    REALNIE nazwała tym kanonem ze źródłem `path`. Klatki, których bramka nie przepuszcza (RAW,
    wiele kopii, karta już jest…), zostają przy samym potwierdzeniu z folderu - okno mówi PRZED
    kliknięciem ile i dlaczego. Po karcie i `Rozwiąż` źródło klatki przechodzi z `path` na nagłówek
    przy TYM SAMYM obiekcie (E5-1: przejście uprawnione, nie przepięcie)."""

    changed = Signal()          # zapis doszedł do skutku → gospodarz odświeża kolejkę i bibliotekę
    busy_changed = Signal(bool)  # okno pisze do plików → mutex drugiej powierzchni (D-PD-3)

    def __init__(self, con, *, proposals, now_fn, db_path=None, run_stage_fn=None, parent=None):
        super().__init__(parent)
        # Lazy jak w `RepairHeaderDialog`: `wb_worker` ciągnie `writeback` → astropy.
        from horreum.gui.wb_worker import WritebackRunner

        self.con = con
        self._now = now_fn
        self._run_stage = run_stage_fn
        self._run_id = None
        self._commit_id = None
        self._items = []        # [{proposal, check, value, n_cards}]
        self.assigned = 0
        self._domkniety = False   # gest zapisał bazę i karty - drugi klik nie ma czego robić
        self._runner = WritebackRunner(db_path if db_path is not None else queries.db_path_of(con),
                                       now_fn=now_fn, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)
        self.setWindowTitle(i18n.t("path.title"))
        self._build_ui(proposals)
        self._sync_action()

    def _build_ui(self, proposals):
        lay = QVBoxLayout(self)
        head = QLabel(i18n.t("path.head", names=len(proposals),
                             frames=sum(p.n_frames for p in proposals)))
        head.setWordWrap(True)
        lay.addWidget(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        gl = QVBoxLayout(inner)
        pominiete = {}          # powód -> liczba klatek (bez karty, tylko potwierdzenie w bazie)
        for p in proposals:
            value, touched, skipped = plan_kart_sciezki(self.con, p.canon, p.frame_ids)
            for _fid, _path, powod in skipped:
                pominiete[powod] = pominiete.get(powod, 0) + 1
            row = QHBoxLayout()
            check = QCheckBox(i18n.t("path.item", canon=p.canon, n=p.n_frames))
            check.setChecked(True)
            check.setToolTip(p.folder or "")
            check.toggled.connect(self._sync_action)
            row.addWidget(check, 2)
            # ZNACZNIK NOWEJ NAZWY jest OSOBNĄ etykietą, nie sufiksem tekstu pozycji: to jedyny
            # fakt, dla którego to okno w ogóle powstało, więc ma mieć własne miejsce i wagę.
            badge = QLabel(i18n.t("path.new_badge") if p.is_new else i18n.t("path.known_badge"))
            if p.is_new:
                _f = badge.font(); _f.setBold(True); badge.setFont(_f)
            row.addWidget(badge, 1)
            folder = QLabel(p.folder or "")
            folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(folder, 3)
            # Co pójdzie do PLIKU przy tej nazwie - dokładna wartość karty i ile klatek ją dostanie.
            karta = QLabel(i18n.t("path.card_item", value=repr(value), n=len(touched),
                                  total=p.n_frames) if touched
                           else i18n.t("path.card_item_none"))
            karta.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(karta, 3)
            gl.addLayout(row)
            self._items.append({"proposal": p, "check": check, "value": value,
                                "n_cards": len(touched)})
        gl.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area, 1)

        # ILE I DLACZEGO bez karty - przed kliknięciem, pogrupowane po powodzie: 700 RAW-ów to
        # jeden wiersz „plik RAW…: 700", nie 700 wierszy z tą samą treścią.
        self.cards_skipped = None
        if pominiete:
            lay.addWidget(QLabel(i18n.t("path.cards_skipped_head",
                                        n=sum(pominiete.values()))))
            self.cards_skipped = QListWidget()
            for powod, n in sorted(pominiete.items(), key=lambda kv: (-kv[1], kv[0])):
                self.cards_skipped.addItem(i18n.t("path.cards_skipped_item", reason=powod, n=n))
            self.cards_skipped.setMaximumHeight(90)
            lay.addWidget(self.cards_skipped)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)   # `commit_id` do skopiowania
        lay.addWidget(self.status)
        self.error = QLabel("")
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        actions = QHBoxLayout()
        self.confirm_btn = QPushButton(i18n.t("path.confirm_btn"))
        _f = self.confirm_btn.font(); _f.setBold(True); self.confirm_btn.setFont(_f)
        self.confirm_btn.clicked.connect(self._on_confirm)
        actions.addWidget(self.confirm_btn)
        self.undo_btn = QPushButton(i18n.t("path.undo_cards_btn"))
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)
        self.resolve_btn = QPushButton(i18n.t("repair.resolve_btn"))
        self.resolve_btn.setVisible(False)
        self.resolve_btn.clicked.connect(self._on_resolve)
        actions.addWidget(self.resolve_btn)
        actions.addStretch(1)
        close_btn = QPushButton(i18n.t("path.close_btn"))
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        lay.addLayout(actions)

    def _checked(self):
        return [it for it in self._items if it["check"].isChecked()]

    def _sync_action(self):
        """Licznik na przycisku mówi, ILE POZYCJI pójdzie do zapisu — szczery disabled przy zerze."""
        n = len(self._checked())
        self.confirm_btn.setText(i18n.t("path.confirm_btn_n", n=n) if n
                                 else i18n.t("path.confirm_btn"))
        self._sync_confirm()
        self.error.clear()

    def _sync_confirm(self):
        """Stan „Zatwierdź" BEZ czyszczenia błędu (wołają go też końce zapisu, a odmowa klingi
        z tego samego kliknięcia ma zostać widoczna). Po zapisie z kartami okno zostaje otwarte
        (Cofnij / Rozwiąż teraz), a drugie „Zatwierdź" nie ma czego zapisać, dopóki karty stoją
        w plikach - wraca po „Cofnij karty" i po commicie, który nie podmienił żadnego pliku."""
        n = len(self._checked())
        self.confirm_btn.setEnabled(n > 0 and not self._domkniety and not self._runner.is_busy)

    def _on_confirm(self):
        """Zapis zaznaczonych pozycji — JEDNA klinga na pozycję (transakcja per nazwa, bo obiekt
        i grupa klatek to jedna decyzja). Pozycja odznaczona NIE JEST zapisywana: „Zatwierdź
        wszystko" znaczy „wszystko, co zostawiłeś zaznaczone", nie „wszystko, co widzisz".

        Konflikt aliasu / dryf grupy wraca `ValueError` z klingi — okno zostaje otwarte z powodem,
        a pozycje zapisane wcześniej ZOSTAJĄ zapisane (każda ma własną transakcję).

        JEDEN GEST, N TRANSAKCJI, JEDNO ZDANIE (R-S2b-13): wyniki pozycji składa `ObjectGesture`
        (`+=`), nie ręczna suma dwóch liczb - ta gubiła rozbicie per fakt i zdanie mówiło
        „pominięte - zajęte między oknem a zapisem" także o darku, którego nikt nie zajął.
        Niezmiennik jak u trzech gestów Zbiorów: `assigned + skipped` == liczba klatek zaznaczonych
        pozycji, więc „z M" mówi o tym, co user zatwierdził, także gdy klinga padła w połowie."""
        from horreum.gui import grid       # lazy - wzorzec `apply_theme`/`_mount_views`
        wybrane = self._checked()
        if not wybrane:
            self.error.setText(i18n.t("path.err.nothing"))
            return
        gest = repo.ObjectGesture()
        przeszly = 0                 # pozycje, które klinga przyjęła (po `break` nie liczą się następne)
        # FAZA Z LICZNIKIEM (F-1): zapis idzie transakcja per NAZWA, więc „zapisuję" bez liczby
        # nie odróżniałoby przebiegu przez 34 pozycje od zawieszenia się na pierwszej. Licznik
        # bierze się z tej samej listy, którą user zaznaczył — nie z liczby propozycji w ogóle.
        with busy.busy(self.status.setText,
                       i18n.t("busy.saving_names", done=0, total=len(wybrane))) as faza:
            for i, it in enumerate(wybrane, 1):
                p = it["proposal"]
                try:
                    gest += repo.user_assign_object(
                        self.con, alias_norm=None, canon=p.canon, catalog=p.catalog, kind=p.kind,
                        frame_ids=list(p.frame_ids), now=self._now(), object_source="path")
                    przeszly += 1
                except ValueError as e:
                    self.error.setText(str(e))
                    # Pozycja, która padła, wycofała się w całości (`_immediate`), a pozycje po niej
                    # do klingi nie doszły - ich klatki liczą się jako ODMOWA KLINGI
                    # (`skipped_failed`), tak jak przy przywracaniu w Zbiorach. Inaczej nie
                    # liczyłyby się nigdzie i „z M" kłamałoby o tym, co user zatwierdził. Nie jako
                    # dryf: konflikt aliasu nie znaczy, że stan uciekł oknu.
                    gest += repo.ObjectGesture(
                        skipped_failed=sum(w["proposal"].n_frames for w in wybrane[i - 1:]))
                    break
                faza.say(i18n.t("busy.saving_names", done=i, total=len(wybrane)))
        self.assigned += gest.assigned
        self.status.setText(
            i18n.t_plural("path.done", przeszly, assigned=gest.assigned,
                          total=gest.assigned + gest.skipped) + grid.zdanie_pominiec(gest))
        self.changed.emit()
        # KARTY DO PLIKÓW NIE ZALEŻĄ OD `assigned` TEGO KLIKNIĘCIA (C2, bramka 0926): pętla idzie
        # po klatkach, które SĄ nazwane tym kanonem ze źródłem `path` - także gdy klinga padła na
        # innej pozycji albo gdy to jest POWTÓRKA po „Cofnij karty" / po commicie z samymi
        # `blocked`/`failed` (wtedy klinga liczy klatki jako dryf, bo obiekt już mają, a karty dalej
        # nie ma). Bez tego taka klatka zostawała nazwana z folderu bez karty i bez drogi do niej.
        run_id, staged = self._stage_karty(wybrane)
        if staged == 0:
            if gest.assigned and not self.error.text():
                self.accept()                                # zachowanie sprzed kart, 1:1
            return
        self._run_id = run_id
        self._domkniety = True
        self._begin_progress(staged)
        self._runner.start("commit", run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed)

    def _stage_karty(self, wybrane):
        """Staging kart dla zaznaczonych pozycji → `(run_id, liczba)`. Plan na ŚWIEŻO, wyłącznie
        dla klatek nazwanych TYM kanonem ze źródłem `path` (dryf, kalibracja, odmowa klingi
        i cudzy obiekt odpadają tu, nie w pisarzu). Zero wpisów → run sprzątnięty od razu."""
        run_id, staged = uuid.uuid4().hex, 0
        for it in wybrane:
            p = it["proposal"]
            nazwane = [r["frame_id"] for r in queries.base_rows(self.con, list(p.frame_ids))
                       if r["object_canon"] == p.canon and r["object_source"] == "path"]
            if not nazwane:
                continue
            _value, touched, _skipped = plan_kart_sciezki(self.con, p.canon, nazwane)
            for t in touched:
                repo.stage_pending(
                    self.con, run_id=run_id, location_id=t.location_id, keyword=t.keyword,
                    idx=t.idx, op=t.op, old_value=t.old_value, new_value=t.new_value,
                    new_type=t.new_type, new_comment=t.comment,
                    expected_header_hash=t.expected_header_hash)
            staged += len(touched)
        if staged == 0:
            repo.clear_pending_for_run(self.con, run_id)   # nic do plików → run nie zostaje otwarty
        return run_id, staged

    def _begin_progress(self, total):
        """Pasek na czas commitu i undo (wzorzec `RepairHeaderDialog._begin_progress`); `total=0`
        = pasek nieokreślony (undo nie zna liczby plików z góry). Akcje zapisu gasną."""
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.confirm_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.resolve_btn.setEnabled(False)

    def _end_progress(self):
        self.bar.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_confirm()

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)

    def _after_commit(self, op, res):
        """Po commicie kart (wątek główny): zdanie bazy + zdanie plików, „Cofnij karty" i „Rozwiąż
        teraz". `commit_id` widoczny - po zamknięciu okna to jedyny uchwyt do cofnięcia z ręki
        (ta sama umowa co w „Napraw nagłówek…"). Commit, który NIE podmienił żadnego pliku (same
        `blocked`/`failed` bez kopii), oddaje „Zatwierdź" - powtórka ma czym dopisać karty."""
        summary, cofnij = zdanie_commitu_kart(res, "path.cards_applied")
        if cofnij is not None:
            self._commit_id = cofnij
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
        self._domkniety = cofnij is not None
        if res.cancelled:
            self._porzuc_staging()               # reszta runu to sierota - nikt jej nie dokończy
        self._run_id = None                      # run domknięty commitem (R#5) - nie kasuj przy zamknięciu
        self.status.setText(self.status.text() + "\n" + summary)
        self._end_progress()
        self.changed.emit()

    def _on_failed(self, op, msg):
        """Wyjątek workera: staging tego runu jest sierotą (C1) - sprzątamy go od razu, nie przy
        zamknięciu okna. „Zatwierdź" wraca, bo nie wiemy, czy karty stoją w plikach."""
        self._porzuc_staging()
        self._domkniety = self._commit_id is not None
        self._end_progress()
        self.error.setText(i18n.t("grid.wb.error", msg=msg))
        self.changed.emit()

    def _porzuc_staging(self):
        if self._run_id is not None:
            repo.clear_pending_for_run(self.con, self._run_id)
            self._run_id = None

    def _on_undo(self):
        """Cofnięcie KART (bajty plików), nie potwierdzenia w bazie: klatki zostają nazwane
        z folderu (źródło `path`), a pliki wracają do stanu sprzed commitu - bez karty. Commit
        zużyty, więc „Zatwierdź" wraca: powtórka dopisze karty tym samym planem (C2)."""
        if self._commit_id is None or self._runner.is_busy:
            return
        self.error.clear()
        self._begin_progress(0)
        self._runner.start("undo", self._commit_id, on_progress=self._on_progress,
                           on_done=self._after_undo, on_failed=self._on_failed)

    def _after_undo(self, op, res):
        self.status.setText(self.status.text() + "\n" + zdanie_undo_kart(res)
                            + i18n.t("path.cards_restored_note"))
        self.undo_btn.setVisible(False)
        self.resolve_btn.setVisible(False)
        self._commit_id = None
        self._domkniety = False
        self._end_progress()
        self.changed.emit()

    def _on_resolve(self):
        """„Rozwiąż teraz" = istniejący etap Dostawy (jak w „Napraw nagłówek…"). Odmowa zostawia
        okno otwarte razem z „Cofnij"."""
        if self._run_stage is None:
            return self.error.setText(i18n.t("repair.err.no_host"))
        reason = self._run_stage()
        if reason:
            return self.error.setText(reason)
        self.accept()

    def set_pipeline_busy(self, busy):
        """Etap pipeline'u w biegu → akcje zapisu gasną (okno modalne, poza `set_busy` widoku)."""
        self.undo_btn.setEnabled(not busy)
        self.resolve_btn.setEnabled(not busy)
        if busy:
            self.confirm_btn.setEnabled(False)
        else:
            self._sync_confirm()

    def done(self, r):
        """KAŻDA droga zamknięcia (Zamknij, Esc, X, accept) przechodzi tędy. W biegu zapisu okno
        ZOSTAJE (`WritebackRunner.refuse_close`, C1) - wątek zapisu jest dzieckiem okna. Po biegu
        staging bez commitu jest sierotą (`run_id` zna tylko to okno) i znika."""
        if self._runner.refuse_close(self.error.setText):
            return
        self._porzuc_staging()
        super().done(r)


# ---------------------------------------------------------------- P-D: nazwa wraca do NAGŁÓWKA
# Klatka, której nagłówek MILCZY o obiekcie (czwarty przypadek obok uniwersalium/regionu/literówki),
# dostaje kartę `OBJECT` w PLIKU — propozycja ze ścieżki, zapis z ręki człowieka, oś wypełnia zwykły
# `Rozwiąż` (header-primary). Zapis do `frame.object_id` z ręki naprawiłby bazę i zostawił plik niemy:
# WBPP/PixInsight dalej nie wiedzą, czym jest klatka, a każda przyszła baza z tego drzewa wymagałaby
# powtórzenia decyzji (D-PD-1).

# ZEJŚCIE DWÓCH REGUŁ ŚCIEŻKI DO JEDNEJ (S2, D-OW-2 pkt 6b). Do S2 ten plik miał WŁASNĄ regułę
# ścieżki — literał `LIGHTS` zamiast markera rodzaju i `catalog_canon` zamiast drabiny nazwy — więc
# ekran i baza odpowiadały RÓŻNIE na to samo pytanie: przebieg nazywał `LMC` i `_SOLAR\Moon`,
# a dialog przy tych samych plikach milczał. Reguła ma teraz jednego właściciela
# (`resolver.path_proposal` → `resolve.paths` + `resolver.resolve_name`), a koszt zejścia zmierzono
# PRZED wdrożeniem na populacji P-D: 25 klatek bez karty, TRACI propozycję **0**.


def _validate_object_value(con, text):
    """Walidacja PRZED zapisem (D-PD-4) → `(wartość_do_pliku | None, powód_odmowy | None)`.

    Kolejność: `strip()` → drabina `resolver.resolve_name` → `forma_karty_object(kanon)` → bramki.
    Tekst, który drabina rozpoznaje jako obiekt (oznaczenie, nazwa zwyczajowa, słownik własny,
    alias nauczony), idzie do pliku w FORMIE NAGŁÓWKA kanonu Horreum - tą samą funkcją, którą liczy
    „Zatwierdź ze ścieżki…" (`plan_kart_sciezki`), nigdy surowy segment ścieżki (inaczej „podgląd
    == plik" rozjechałoby się o białe znaki). Tekst nierozpoznany zostaje, jaki jest, i odmawia go
    czwarta bramka niżej.
    ZASADA D-PD-9 ODWRÓCONA decyzjami usera 2026-09-26 (Q6, D2): dawniej do pliku szła forma PRZED
    `xref` („konwencja usera w JEGO plikach", folder `M82` → karta `M82`); dziś nagłówek niesie
    JEDNĄ formę na obiekt: folder `M82` → karta `NGC 3034`, „Bubble Nebula" → `NGC 7635` (nazwa
    zwyczajowa zostaje aliasem w bazie). Wyjątek: kanon, który z własnego zapisu nie wraca do siebie
    (znany tylko aliasem), zostawia tekst usera - ten się rozwiązuje, kanon by nie.

    Bramki odmowy (zero zapisu): pusto po `strip()`; REGUŁY KARTY FITS - znak spoza drukowalnego
    ASCII albo wartość dłuższa niż rekord. Te drugie pyta `writeback.card_violation`, czyli TEN
    SAM właściciel, który odmówi przy zapisie (SPOT): dialog mówi tylko wcześniej i własnym językiem
    (i18n), nie inną regułą. Bez tego taki kanon padłby dopiero w pisarzu jako 'blocked' po commicie
    zamiast odmowy przed nim. CZWARTA bramka - nazwa NIEROZPOZNAWALNA przez
    resolver — jest dodana ponad brief świadomie: cały wariant C stoi na tym, że po zapisie oś
    wypełni się sama, a nazwa, której przebieg nie zna, przeniosłaby klatkę tylko z kubełka
    „bez nazwy" do „nierozpoznane" — po nieodwracalnej mutacji pliku.

    Pytanie czwartej bramki zadaje `resolver.name_resolves` — CAŁA drabina nazwy (solar → katalog →
    alias), nie sam `resolve_object`; dlatego walidacja potrzebuje `con`. Bramka pytająca węższym
    predykatem niż przebieg odmawiałaby nazw, które przebieg rozwiązuje (`Moon`, `WR134`)."""
    raw = (text or "").strip()
    if not raw:
        return None, i18n.t("repair.err.empty")
    # Forma do pliku z TEJ SAMEJ drabiny, którą pójdzie przebieg (D2): tekst rozpoznany jako obiekt
    # - oznaczenie, nazwa zwyczajowa, słownik własny, alias nauczony - idzie jako `forma_karty_object`
    # kanonu (`Bubble Nebula` → `NGC 7635`, `M82` → `NGC 3034`); tekst nierozpoznany zostaje, jaki
    # jest, i odmawia go bramka niżej. Kanon, który z własnego zapisu nie wraca, zostawia tekst usera.
    try:
        ident = resolver.resolve_name(resolver.alias_lookup(con), raw)[0] if con else None
    except ValueError:
        ident = None
    value = (forma_karty_object(con, ident.canon) if ident is not None else None) or raw
    # Lazy jak `wb_worker` w dialogu: `writeback` ciągnie astropy, a dialog, który tu pyta, i tak
    # już go załadował. Dialog zapisuje kartę przez `add` - stąd `new_card=True`.
    from horreum import writeback
    naruszenie = writeback.card_violation("OBJECT", value, new_card=True)
    if naruszenie is not None:
        if naruszenie.kind == "length":
            return None, i18n.t("repair.err.too_long", n=naruszenie.length, max=naruszenie.limit)
        if naruszenie.kind == "chars":
            return None, i18n.t("repair.err.ascii", text=value)
        return None, naruszenie.reason          # nazwa: nieosiągalne dla stałej `OBJECT`
    if not resolver.name_resolves(con, value):
        return None, i18n.t("repair.err.unresolvable", text=raw)
    return value, None


class RepairHeaderDialog(QDialog):
    """„Napraw nagłówek…" — dopisanie karty `OBJECT` do PLIKÓW klatek bezimiennych (P-D, wariant C).

    Trzy takty (D-PD-6): **zapis karty → re-sync zeznania (automatyczny, w `writeback.commit`) →
    `Rozwiąż`**. Takty 1–2 dzieją się TU jednym kliknięciem („Zapisz karty"): staging i commit to
    JEDEN takt, bo sam staging osierociłby `run_id`, którego żadna inna powierzchnia nie zna.
    Takt 3 NIE uruchamia resolvera z dialogu — deleguje do `PipelineView.run_stage('resolve')`
    (wołanie inline zamroziłoby GUI na 15k klatek i ominęło bramkę `running_changed`).

    Mutacja pliku idzie WYŁĄCZNIE przez `writeback` (jedna klinga), staging WYŁĄCZNIE przez
    `repo.stage_pending`; ten dialog nie zna SQL. Bramki celu liczy `macro.resolve_target` — TA SAMA
    funkcja, która potem odsieje cel przy zapisie, więc lista pominiętych nie jest drugą regułą,
    tylko tym samym zdaniem powiedzianym wcześniej.

    Cofanie ma OKNO: „Cofnij" żyje od udanego zapisu do zamknięcia okna (i tylko przed taktem 3) —
    poza nim nie ma powierzchni cofania nagłówka, dlatego dialog pokazuje `commit_id`, a kotwicą
    ratunku zostaje kopia bajtowa."""

    changed = Signal()          # zapis/cofnięcie doszło do skutku → gospodarz odświeża kolejkę
    busy_changed = Signal(bool)  # ta powierzchnia pisze do plików → mutex drugiej (D-PD-3)

    def __init__(self, con, *, rows, db_path, now_fn, run_stage_fn=None, parent=None):
        super().__init__(parent)
        # Lazy: `wb_worker` ciągnie `writeback` → astropy; start apki nie ma za co płacić, dopóki
        # user nie otworzy tego okna (wzorzec lazy-importów widoków w `_mount_views`).
        from horreum.gui.wb_worker import WritebackRunner

        self.con = con
        self._now = now_fn
        self._run_stage = run_stage_fn
        self._run_id = None
        self._commit_id = None
        self._committed = False   # karty są w plikach → zapis milczy do cofnięcia
        self._runner = WritebackRunner(db_path, now_fn=now_fn, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)   # uchwyt zna OBA końce operacji
        self._groups = []       # [{folder, rows, check, edit, preview}]
        self._skipped = []      # [(path, powód)] — jawnie widoczne, nigdy ciche
        self.setWindowTitle(i18n.t("repair.title"))
        self._split_rows(rows)
        self._build_ui()
        self._sync_preview()

    # ---------------------------------------------------------------- podział wejścia
    def _split_rows(self, rows):
        """Wiersze read-modelu → grupy po FOLDERZE + lista pominiętych z powodem. Grupowanie
        SŁOWNIKIEM (kolejność pierwszego wystąpienia), bo porządek po pełnej ścieżce przeplata
        katalog z podkatalogiem. Folder bierzemy z celu writebacku, nie z `path` read-modelu —
        żeby grupa opisywała dokładnie ten plik, który zostanie zapisany.

        GOTOWY STOS GRUPUJE SIĘ PO FOLDERZE OBIEKTU, nie po rodzicu pliku (FC-4, ta sama wada co
        w kolumnie „Obiekt"): w układzie `STACKS\\<OBIEKT>\\<KONFIG>\\<FILTR>\\plik` rodzicem jest
        FILTR, więc etykiety grup brzmiały `NoFilter`/`Ha`, a jeden obiekt rozpadał się na tyle grup,
        ile ma filtrów. Folder obiektu daje `resolve.paths.object_folder(…, kind=STACK_KIND)`;
        poza drzewem `STACKS` (układ WBPP) i dla każdego lighta zostaje rodzic, znak w znak jak
        przedtem. Rodzaj wiersza wybiera też drzewo świadka propozycji (`path_proposal(…, kind=…)`),
        a reguła dwóch zgodnych świadków jest dla obu drzew ta sama."""
        ids = [r["frame_id"] for r in rows]
        targets = {}
        for t in queries.writeback_frame_targets(self.con, ids):
            targets.setdefault(int(t["frame_id"]), []).append(t)
        groups = {}
        rodzaj = {}             # frame_id -> kind (drzewo świadka), poza słownikiem wiersza grupy
        for r in rows:
            trows = targets.get(int(r["frame_id"]))
            if not trows:                       # klatka zniknęła z bazy między odczytem a otwarciem
                self._skipped.append((r["path"] or "", i18n.t("repair.skip.gone")))
                continue
            target, reason = macro_mod.resolve_target(trows)
            if target is None:
                self._skipped.append((r["path"] or "", reason or ""))
                continue
            rodzaj[r["frame_id"]] = r["kind"]
            folder = os.path.dirname(target["path"])
            if r["kind"] == STACK_KIND:
                folder = object_folder(target["path"], kind=STACK_KIND) or folder
            groups.setdefault(folder, []).append(
                dict(frame_id=r["frame_id"], path=target["path"]))
        for folder, items in groups.items():
            proposals = {resolver.path_proposal(self.con, it["path"], kind=rodzaj[it["frame_id"]])
                         for it in items}
            common = proposals.pop() if len(proposals) == 1 else None
            self._groups.append({"folder": folder, "rows": items, "proposal": common})

    # ---------------------------------------------------------------- budowa UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        n_frames = sum(len(g["rows"]) for g in self._groups)
        head = QLabel(i18n.t("repair.head", frames=n_frames, groups=len(self._groups)))
        head.setWordWrap(True)
        lay.addWidget(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        gl = QVBoxLayout(inner)
        for g in self._groups:
            row = QHBoxLayout()
            g["check"] = QCheckBox(i18n.t("repair.group", folder=os.path.basename(g["folder"]),
                                          n=len(g["rows"])))
            g["check"].setToolTip(g["folder"])
            # Grupa z parsowalną propozycją jest ZAZNACZONA: bez tego cztery grupy kosztują cztery
            # dodatkowe kliknięcia, a obietnica „≤ 4 interakcje" przestaje być prawdziwa.
            g["check"].setChecked(bool(g["proposal"]))
            row.addWidget(g["check"], 2)
            g["edit"] = QLineEdit(g["proposal"] or "")
            g["edit"].setPlaceholderText(i18n.t("repair.no_proposal"))
            g["edit"].textChanged.connect(self._sync_preview)
            g["check"].toggled.connect(self._sync_preview)
            row.addWidget(g["edit"], 1)
            g["preview"] = QLabel("")
            g["preview"].setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(g["preview"], 2)
            gl.addLayout(row)
        gl.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area, 1)

        if self._skipped:
            lay.addWidget(QLabel(i18n.t("repair.skipped_head", n=len(self._skipped))))
            lst = QListWidget()
            for path, reason in self._skipped:
                lst.addItem(f"{os.path.basename(path) or i18n.t('object.no_location')} — {reason}")
            lst.setMaximumHeight(90)
            lay.addWidget(lst)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)   # `commit_id` do skopiowania
        lay.addWidget(self.status)
        self.error = QLabel("")
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        actions = QHBoxLayout()
        self.save_btn = QPushButton(i18n.t("repair.save_btn"))
        _f = self.save_btn.font(); _f.setBold(True); self.save_btn.setFont(_f)   # złota akcja: WAGA, nie kolor (P-C)
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)
        self.undo_btn = QPushButton(i18n.t("grid.action.undo"))
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)
        self.resolve_btn = QPushButton(i18n.t("repair.resolve_btn"))
        self.resolve_btn.setVisible(False)
        self.resolve_btn.clicked.connect(self._on_resolve)
        actions.addWidget(self.resolve_btn)
        actions.addStretch(1)
        close_btn = QPushButton(i18n.t("repair.close_btn"))
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        lay.addLayout(actions)

    # ---------------------------------------------------------------- podgląd „co wpiszemy"
    def _sync_preview(self):
        """Podgląd DOKŁADNIE tego, co pójdzie do pliku (`OBJECT = 'NGC7635'`), plus szczery stan
        akcji. Grupa zaznaczona z niepoprawną wartością pokazuje powód przy sobie — user nie musi
        klikać, żeby dowiedzieć się, czemu zapis nie ruszy."""
        ready, first_err = 0, None
        for g in self._groups:
            if not g["check"].isChecked():
                g["preview"].setText("")
                continue
            value, err = _validate_object_value(self.con, g["edit"].text())
            if err:
                g["preview"].setText(i18n.t("repair.preview_none"))
                first_err = first_err or i18n.t(
                    "repair.err.group", folder=os.path.basename(g["folder"]), reason=err)
            else:
                g["preview"].setText(i18n.t("repair.preview", value=repr(value)))
                ready += len(g["rows"])
        self.error.setText(first_err or "")     # wejście się zmieniło → stary błąd nieaktualny
        # Po udanym commicie zapis MILCZY do czasu cofnięcia: karty są już w plikach, więc drugie
        # kliknięcie dałoby tylko listę „karta już istnieje" — szczery disabled zamiast pustego biegu.
        self.save_btn.setEnabled(ready > 0 and first_err is None and not self._committed
                                 and not self._runner.is_busy)
        # Licznik mówi, ile ZOSTAŁO do zapisania — nie ile BYŁO gotowe. Po commicie zostaje zero,
        # więc liczba znika razem z sensem drugiego kliknięcia; zamrożone „Zapisz karty (23)"
        # pod wygaszonym przyciskiem opisywało przeszłość (firsthand pilota P-D na `R:`).
        self.save_btn.setText(i18n.t("repair.save_btn_n", n=ready)
                              if ready and not self._committed else i18n.t("repair.save_btn"))

    def _fail(self, msg):
        self.error.setText(msg)

    # ---------------------------------------------------------------- takt 1+2: staging + commit
    def _on_save(self):
        """Staging i commit JEDNYM taktem. Walidacja WSZYSTKICH zaznaczonych grup PRZED
        jakimkolwiek zapisem — częściowy staging po odmowie zostawiłby otwarty run."""
        if self._runner.is_busy:
            return
        self.error.clear()
        plan = []
        for g in self._groups:
            if not g["check"].isChecked():
                continue
            value, err = _validate_object_value(self.con, g["edit"].text())
            if err:
                return self._fail(i18n.t("repair.err.group", folder=os.path.basename(g["folder"]),
                                         reason=err))
            plan.append((g, value))
        if not plan:
            return self._fail(i18n.t("repair.err.nothing"))

        run_id = uuid.uuid4().hex
        staged, skipped = 0, []
        for g, value in plan:
            # `repr(value)` — bo `expr` traktuje gołe `NGC7635` jak NAZWĘ ZMIENNEJ (przy kolizji
            # z keywordem wpisalibyśmy WARTOŚĆ TEJ KARTY), a sam cudzysłów nie wystarcza: kanon
            # z apostrofem wysadza kompilację i makro wpisałoby surową zawartość pola razem
            # z cudzysłowami. Python dobiera cudzysłów i escape sam.
            md = macro_mod.MacroDef(assign=macro_mod.Assign(
                keyword="OBJECT", op="add", expr=repr(value), value_type="str"))
            run = macro_mod.run_macro(
                md, [it["frame_id"] for it in g["rows"]],
                targets_fn=lambda ids: queries.writeback_frame_targets(self.con, ids),
                cards_fn=lambda fid: queries.frame_cards(self.con, fid),
                run_id=run_id)
            for p in run.touched:
                repo.stage_pending(
                    self.con, run_id=run_id, location_id=p.location_id, keyword=p.keyword,
                    idx=p.idx, op=p.op, old_value=p.old_value, new_value=p.new_value,
                    new_type=p.new_type, new_comment=p.comment,
                    expected_header_hash=p.expected_header_hash)
            staged += len(run.touched)
            skipped += [(s.path, s.reason) for s in run.skipped]
        if staged == 0:
            repo.clear_pending_for_run(self.con, run_id)     # nic do zapisu → run nie zostaje otwarty
            return self._fail(i18n.t("repair.err.all_skipped",
                                     reason=(skipped[0][1] if skipped else "")))

        self._run_id = run_id
        self._begin_progress(staged)
        self._runner.start("commit", run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed)

    def _begin_progress(self, total):
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.save_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.resolve_btn.setEnabled(False)

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"{done}/{total} · {os.path.basename(path)}")

    def _after_commit(self, op, res):
        """Post-processing commitu (wątek główny). Plik podmieniony → jednorazowe „Cofnij" + „Rozwiąż
        teraz"; `commit_id` WIDOCZNY, bo po zamknięciu okna to jedyny uchwyt do cofnięcia z ręki.
        Zdanie i regułę „kiedy wolno cofnąć" daje `zdanie_commitu_kart` - wspólne z oknem
        „Zatwierdź ze ścieżki…" (C4: także `failed` z kopią nagłówka ma „Cofnij")."""
        self.bar.setVisible(False)
        summary, cofnij = zdanie_commitu_kart(res, "grid.wb.applied")
        if cofnij is not None:
            self._commit_id = cofnij
            self._committed = True
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
        if res.cancelled or cofnij is None:
            self._porzuc_staging()               # reszta runu to sierota - nikt jej nie dokończy
        self._run_id = None                      # run domknięty commitem (R#5) - nie kasuj przy zamknięciu
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()
        self.status.setText(summary)
        self.changed.emit()

    def _on_failed(self, op, msg):
        """Wyjątek workera: staging runu jest sierotą (C1) - sprzątany od razu, nie przy zamknięciu."""
        self._porzuc_staging()
        self.bar.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()                     # PRZED `_fail`: podgląd czyści pole błędu
        self._fail(i18n.t("grid.wb.error", msg=msg))
        self.changed.emit()

    def _porzuc_staging(self):
        if self._run_id is not None:
            repo.clear_pending_for_run(self.con, self._run_id)
            self._run_id = None

    # ---------------------------------------------------------------- cofanie (OKNO do zamknięcia)
    def _on_undo(self):
        if self._commit_id is None or self._runner.is_busy:
            return
        self.error.clear()
        self._begin_progress(0)
        self._runner.start("undo", self._commit_id, on_progress=self._on_progress,
                           on_done=self._after_undo, on_failed=self._on_failed)

    def _after_undo(self, op, res):
        self.bar.setVisible(False)
        msg = zdanie_undo_kart(res)
        self.undo_btn.setVisible(False)          # commit ZUŻYTY - drugi undo nie ma czego cofać
        self.resolve_btn.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._commit_id = None
        self._committed = False                  # karty zdjęte → zapis znów ma sens
        self._sync_preview()
        self.status.setText(msg)
        self.changed.emit()

    # ---------------------------------------------------------------- takt 3: delegacja do pipeline'u
    def _on_resolve(self):
        """„Rozwiąż teraz" = ISTNIEJĄCY etap Dostawy, nie drugi resolver. Odmowa (etap już biegnie)
        ZOSTAWIA okno otwarte i NIE chowa „Cofnij": okno cofania musi przeżyć nieudaną delegację,
        inaczej UI potwierdzałoby sukces, którego nie było."""
        if self._run_stage is None:
            return self._fail(i18n.t("repair.err.no_host"))
        reason = self._run_stage()
        if reason:
            return self._fail(reason)
        self.accept()

    def set_pipeline_busy(self, busy):
        """Etap pipeline'u w biegu → akcje zapisu tego okna gasną. Modalne okno jest POZA zasięgiem
        `ObjectAxisView.set_busy` (tamto gasi widżety widoku), więc gospodarz przekazuje fakt tutaj."""
        self.undo_btn.setEnabled(not busy)
        self.resolve_btn.setEnabled(not busy)
        if busy:
            self.save_btn.setEnabled(False)
        else:
            self._sync_preview()

    def done(self, r):
        """KAŻDA droga zamknięcia (Zamknij, Esc, X, accept) przechodzi tędy. W biegu zapisu okno
        ZOSTAJE (`WritebackRunner.refuse_close`, C1 - ten sam kod co w „Zatwierdź ze ścieżki…"):
        wątek zapisu jest dzieckiem okna. Po biegu staging BEZ commitu jest sierotą (`run_id` zna
        tylko to okno), więc znika; po udanym commicie `_run_id` jest już None - wierszy 'applied'
        nie ruszamy."""
        if self._runner.refuse_close(self._fail):
            return
        self._porzuc_staging()
        super().done(r)


class ObjectAxisView(QWidget):
    """Osadzalny widok osi OBIEKT (PLAN_gui_object + #8/P4): biblioteka (obiekty → klatki, filtr
    po teleskopie/kamerze/filtrze) + kolejka przeglądu (obiekt-review / kopie nieczytelne /
    config-review / headerless) ze STANU. **Akcja zapisu:** „Przypisz obiekt…" na pozycji
    obiekt-review — dialog (`AssignObjectDialog`) → JEDNA klinga `repo.user_assign_object`
    (`actor=user:local`): alias zapamiętany na przyszłość + klatki grupy z `object_source='user'`
    (precedencja na całą drabinę resolvera). Drążenie „kopie nieczytelne" (Z6) → prawy panel
    w trybie „kopie" (dokładne location z markerem). Meta-test AST pilnuje, że widok nie tyka
    SQL zapisu — zapis idzie wyłącznie przez `repo`.

    Dispatch pozycji kolejki po STRING-TAGU (R#6): `Qt.UserRole` = tag (`"object_raw"` /
    `"unreadable"`), `Qt.UserRole+1` = payload (object_raw albo None) — tuple w jednej roli PySide6
    konwertuje na listę (QVariant) i porównanie z krotką-sentinelem po cichu zawodzi.

    `con` = otwarte połączenie (NIE własność widoku). `now_fn` = źródło czasu akcji zapisu
    (ISO-8601); domyślnie zegar UTC, wstrzykiwalne dla testów."""

    status_message = Signal(str)
    writeback_busy = Signal(bool)         # okno naprawy pisze do plików → mutex gridu (D-PD-3)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._busy = False                    # pipeline w biegu → akcja zapisu wygaszona
        self._foreign_wb = False              # DRUGA powierzchnia writebacku pisze (mutex, D-PD-3)
        self._copies_mode = False             # prawy panel w trybie „kopie" (Z6)
        self._loading = False                 # tłumi sygnały selekcji podczas programowego wypełniania
        # Otwarte okno piszące karty do plików: „Napraw nagłówek…" albo „Zatwierdź ze ścieżki…"
        # (modalne - poza zasięgiem `set_busy`, więc bieg pipeline'u przekazujemy mu wprost).
        self._repair_dlg = None
        # Takt 3 (`Rozwiąż`) należy do Dostawy: gospodarz wstrzykuje wywołanie ISTNIEJĄCEJ,
        # bramkowanej drogi (`PipelineView.run_stage`). None = widok bez gospodarza (testy samego
        # widoku) → okno naprawy powie wprost, że taktu 3 nie ma stąd jak uruchomić.
        self.run_stage_fn = None
        self._build_ui()
        self._load_facets()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # --- pasek filtra ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("filter.telescope")))
        self.combo_tel = QComboBox()
        self.combo_tel.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_tel)
        bar.addWidget(QLabel(i18n.t("filter.filter")))
        self.combo_filter = QComboBox()
        self.combo_filter.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_filter)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: biblioteka obiektów + kolejka przeglądu pod nią ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(i18n.t("object.library")))
        self.objects = QTableWidget(0, len(OBJ_HEADERS))
        self.objects.setHorizontalHeaderLabels(_headers(OBJ_HEADERS))
        self.objects.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.objects.setSelectionMode(QAbstractItemView.SingleSelection)
        self.objects.setEditTriggers(QAbstractItemView.NoEditTriggers)   # read-only
        self.objects.verticalHeader().setVisible(False)
        self.objects.itemSelectionChanged.connect(self._on_object_selected)
        # NADMIAR PIONU NALEŻY DO BIBLIOTEKI (W-3): kolejka pod nią bierze tyle, ile ma treści
        # (`_dopasuj_kolejke`), więc bez tego współczynnika zwolniony pion zostałby pustką
        # rozłożoną po obu kontrolkach zamiast trafić do tabeli, która wierszy ma setki.
        lv.addWidget(self.objects, 1)
        # Nota pustego stanu W WIDOKU (wizytator P1 #2): pusty filtr nie może komunikować się tylko
        # ulotnym flashem na statusbarze — user patrzy na pustą bibliotekę i pełną kolejkę i nie wie,
        # czy to błąd. Nota jest odkrywalna w obszarze tabeli, chowana gdy są obiekty.
        self.lib_empty = QLabel(i18n.t("object.lib_empty"))
        self.lib_empty.setAlignment(Qt.AlignCenter)
        self.lib_empty.setWordWrap(True)
        self.lib_empty.setVisible(False)
        lv.addWidget(self.lib_empty)

        lv.addWidget(QLabel(i18n.t("object.review_queue")))
        self.review = QListWidget()
        # WIERSZ WIELOCZŁONOWY (R-S3-3): nazwa od lewej (elidowana), liczba i adnotacja przy prawej
        # krawędzi. Do tej zmiany kolejka doklejała oba człony do tekstu, więc przy wąskim oknie
        # lista jechała poziomym scrollem i pierwsze ginęło to, co niesie ZNACZENIE („cofnięte
        # ręką"). `ScrollBarAlwaysOff` jest częścią kontraktu delegata, nie kosmetyką: bez niego
        # Qt rozciąga viewport pod `sizeHint` najdłuższej nazwy i elizja nigdy nie dochodzi do głosu.
        self.review.setItemDelegate(TwoPartDelegate(self.review))
        self.review.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.review.itemSelectionChanged.connect(self._on_review_selected)
        # DRUGI sygnał, bo wiersz informacyjny nie jest zaznaczalny i pierwszego nie wyzwala (F-2).
        self.review.itemClicked.connect(self._on_review_clicked)
        # TRZECI: dwuklik = akcja pozycji bez wędrówki do rzędu przycisków (R-S3-6). Gest, którego
        # nie było, choć lista go sugeruje samym drążeniem; naprawa kubełka cofniętych spada z 6
        # interakcji na 5.
        self.review.itemDoubleClicked.connect(self._on_review_double_clicked)
        lv.addWidget(self.review)
        # Akcja #8/P4: przypisz obiekt zaznaczonej pozycji review (aktywna TYLKO przy tagu
        # „object_raw" — obie listy wzajemnie czyszczą selekcję, przycisk śledzi obie).
        assign_row = QHBoxLayout()
        self.assign_btn = QPushButton(i18n.t("object.assign_btn"))
        self.assign_btn.setEnabled(False)
        self.assign_btn.clicked.connect(self._on_assign)
        assign_row.addWidget(self.assign_btn)
        # P-D: druga akcja tej samej kolejki — naprawa NAGŁÓWKA (plik), nie bazy. Aktywna wyłącznie
        # na pozycji `nameless`, więc obie akcje nigdy nie są klikalne naraz.
        self.repair_btn = QPushButton(i18n.t("repair.open_btn"))
        self.repair_btn.setEnabled(False)
        self.repair_btn.clicked.connect(self._on_repair)
        assign_row.addWidget(self.repair_btn)
        # TRZECIA akcja tej samej kolejki (S2, D-OW-2/B): potwierdzenie propozycji ze ŚCIEŻKI.
        # Osobna od „Przypisz obiekt…", bo tam człowiek WSKAZUJE obiekt, a tu POTWIERDZA cudzą
        # propozycję hurtem — i osobna od „Napraw nagłówek…", bo tamta pisze do PLIKÓW, ta do bazy.
        self.confirm_path_btn = QPushButton(i18n.t("object.confirm_path_btn"))
        self.confirm_path_btn.setEnabled(False)
        self.confirm_path_btn.clicked.connect(self._on_confirm_path)
        assign_row.addWidget(self.confirm_path_btn)
        # CZWARTA akcja — i pierwsza w tym rzędzie, która nie dotyczy osi OBIEKTU (R1). Kubełek
        # sprzętu mieszka w tej kolejce od początku, ale do R1 był wierszem informacyjnym z notą
        # „rozwiązywanie w przygotowaniu": mechanizmu nie było, więc powierzchni też nie. Ekran
        # zapowiadał userowi tę drogę wprost, a niedokończona obietnica na ekranie jest droższa
        # niż dług w kolejce — dlatego akcja stoi tu, obok tej noty, którą właśnie zdejmuje.
        self.set_config_btn = QPushButton(i18n.t("object.set_config_btn"))
        self.set_config_btn.setEnabled(False)
        self.set_config_btn.clicked.connect(self._on_set_config)
        assign_row.addWidget(self.set_config_btn)
        assign_row.addStretch(1)
        lv.addLayout(assign_row)

        # --- prawa: klatki zaznaczonego obiektu / pozycji review ---
        right = QWidget()
        rv = QVBoxLayout(right)
        self.frames_label = QLabel(i18n.t("col.frames"))
        rv.addWidget(self.frames_label)
        self.frames = QTableWidget(0, len(FRAME_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(FRAME_HEADERS))
        self.frames.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.frames.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # ZAWIJANIE WYŁĄCZONE, inaczej elizja kłamie (firsthand 2026-08-01, żywa pf4): przy
        # `wordWrap=True` (domyślne) delegat układa ścieżkę bez spacji jako jedną nierozrywalną
        # linię i tnie ją do „R:..." — ZANIM dojdzie do głosu szerokość sekcji. Zmierzone:
        # sekcja 281 px, `fontMetrics.elidedText` na tej szerokości daje 45 znaków
        # („R:\ASTRO_\CALIBRATION\masters\flats\A140R_260…"), a panel rysował 2 znaki.
        self.frames.setWordWrap(False)
        # Panel jest od S4 CELEM akcji zapisu, więc przycisk musi śledzić jego zaznaczenie tak samo
        # jak tag kolejki — inaczej odznaczenie wszystkiego zostawiałoby aktywny przycisk bez celu.
        self.frames.itemSelectionChanged.connect(self._sync_assign_enabled)
        # Kolumny wąskie (sha/tel/kam/filtr/data/obecny) do treści, Ścieżka bierze resztę — inaczej
        # stałe 100px zjadają panel i na Ścieżkę zostaje ~130px (widać tylko „R:...", ginie nazwa pliku).
        fh = self.frames.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(FRAME_COL_PATH, QHeaderView.Stretch)
        self.frames.verticalHeader().setVisible(False)
        self._elizja_sciezki_klatek()
        rv.addWidget(self.frames)

        splitter.addWidget(left)
        splitter.addWidget(right)
        # NADMIAR POZIOMU NALEŻY DO PRAWEGO PANELU. Przy podziale 2:3 lewa strona brała z nadmiaru
        # tyle samo co szerokość własnej treści, a biblioteka ma trzy wąskie kolumny - zostawał po
        # niej pusty pas, a panel kopii obok ucinał „Powód" (wizytacja przy 1400 px). Lewa strona
        # stoi na swojej podpowiedzi rozmiaru (rząd czterech akcji kolejki), prawa bierze resztę;
        # uchwyt splittera dalej przesuwa granicę ręką.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # …a w bibliotece szerokość, która zostaje, bierze NAZWA obiektu: kolumna, którą
        # elidowało („21P/Giacobini-…"), zamiast pustego pasa za ostatnią kolumną.
        oh = self.objects.horizontalHeader()
        oh.setSectionResizeMode(QHeaderView.ResizeToContents)
        oh.setSectionResizeMode(OBJ_COL_CANON, QHeaderView.Stretch)
        outer.addWidget(splitter, 1)   # stretch: splitter zjada pionowy nadmiar, pasek filtra nie puchnie w pustkę

    # ---------------------------------------------------------------- facety filtra

    def _load_facets(self):
        """Wypełnij comba filtra realnie istniejącymi osiami (kanoniczne teleskopy + filtry). Placeholder
        „(wszystkie)" niesie `data=None` → brak filtra (wzór `(? IS NULL OR …)` w read-modelu)."""
        self._loading = True
        try:
            self.combo_tel.clear()
            self.combo_tel.addItem(i18n.t("filter.all"), None)
            for t in queries.telescope_facets(self.con):
                self.combo_tel.addItem(queries.telescope_label(t), t["id"])
            self.combo_filter.clear()
            self.combo_filter.addItem(i18n.t("filter.all"), None)
            for f in queries.filter_facets(self.con):
                self.combo_filter.addItem(f["filter_canon"], f["filter_canon"])
        finally:
            self._loading = False

    def _filters(self):
        return {"telescope_id": self.combo_tel.currentData(),
                "filter_canon": self.combo_filter.currentData()}

    def _on_filter_changed(self):
        if not self._loading:
            self.refresh()

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self, *, select_canon=None, select_first=True):
        """Przeładuj bibliotekę i kolejkę z read-modelu (źródło prawdy = baza; brak cache). Zachowuje
        zaznaczenie obiektu po `object_id`; po zapisie `select_canon` wybiera jawny cel akcji.
        `select_first=False` zostawia jednoznaczny pusty wybór po operacji, która nic nie przypisała."""
        prev = self._selected_object_id() if select_canon is None else None
        flt = self._filters()
        self._loading = True
        try:
            # BEZ FAZY ZAJĘTOŚCI — ŚWIADOMIE, i to jest pomiar, nie przeoczenie (F-1): cały
            # `refresh()` tego widoku mierzy **164 ms** na 16 648 klatkach (z czego `review_queue`
            # 146 ms), czyli poniżej progu, przy którym człowiek pyta „czy się zawiesiło". Faza
            # mignęłaby na 0,16 s i byłaby szumem, a nie informacją — a że ten widok kończy akcje
            # WŁASNYMI raportami („Przypisano 2 z 2 klatek → M42"), migający opis roboty
            # wypychałby ze statusu dokładnie to zdanie, po które user czekał.
            rows = queries.library_objects(
                self.con, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"])
            godziny = portfolio.summarize(queries.library_exposure(
                self.con, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"]))
            _przeladuj_wiersze(self.objects, len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_obj_cell(r, OBJ_COL_CANON, row["canon"], data=row["id"])
                self._set_obj_cell(r, OBJ_COL_CATALOG, row["catalog"] or "")
                self._set_obj_cell(r, OBJ_COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
                # Obiekt z samymi masterlightami nie ma godzin subów - komórka milczy zamiast
                # udawać „0.0 h". Lighty bez EXPTIME mówią o sobie W KOMÓRCE tym samym sufiksem co
                # listwa gridu (`portfolio.object_suffix`, bez separatora listwy): „0.0 h" bez
                # ogona czytałoby się jak „brak materiału", choć klatki są, tylko bez czasu.
                wpis = godziny.get(row["id"])
                self._set_obj_cell(
                    r, OBJ_COL_HOURS,
                    portfolio.object_suffix(wpis).removeprefix(" · ") if wpis else "",
                    align=_NUM_ALIGN, tip=portfolio.object_tooltip(wpis) if wpis else None)
                if row["canon"] == select_canon \
                        or (select_canon is None and row["id"] == prev):
                    target_row = r
            self._load_review()
        finally:
            self._loading = False
        if target_row < 0 and select_canon is not None and any(flt.values()):
            # Kolejka review jest globalna, biblioteka filtrowana: cel legalnego przypisania może być
            # poza bieżącym filtrem. Zdejmij filtry bez pośrednich refreshy i pokaż wynik akcji.
            self._loading = True
            try:
                self.combo_tel.setCurrentIndex(0)
                self.combo_filter.setCurrentIndex(0)
            finally:
                self._loading = False
            return self.refresh(select_canon=select_canon)
        empty = self.objects.rowCount() == 0
        self.lib_empty.setVisible(empty)               # nota odkrywalna w widoku (P1 #2)
        self.objects.setVisible(not empty)
        if target_row >= 0:
            self.objects.selectRow(target_row)
        elif not empty and select_first:
            self.objects.selectRow(0)
        elif not empty:
            self.objects.clearSelection()
            self.frames.setRowCount(0)
            self.frames_label.setText(i18n.t("col.frames"))
        else:
            self.frames.setRowCount(0)
            self.status_message.emit(i18n.t("object.empty_status"))
        self._restore_frames_mode()            # tryb „kopie" znika przy refresh (D-P4-5)
        self._sync_assign_enabled()
        self._on_object_selected()

    def _load_review(self):
        """Kolejka przeglądu ze STANU: obiekt-review (drążenie do klatek + akcja „Przypisz"),
        klatki bez nazwy w nagłówku (licznik — nie ma czego zgrupować, T5a), kopie nieczytelne
        (drążenie do kopii, Z6), liczniki config-review/headerless (informacyjne — bez drążenia,
        to inne osie/skan). Dispatch po string-tagu: `UserRole` = tag, `UserRole+1` = payload
        (R#6 — tuple w roli QVariant konwertuje na listę)."""
        q = queries.review_queue(self.con)
        self.review.clear()
        rodzic = None                    # nazwa OSTATNIEJ nietkniętej połówki — jedyny legalny rodzic wcięcia
        for r in q["object_review"]:
            # CZŁON „cofnięte ręką" (S3/R-S2b-1) niesie TAG, nie payload: dispatch tego widoku stoi
            # na string-tagu właśnie po to, żeby nie wozić krotki w roli QVariant (wraca jako lista,
            # R#6). Para (`object_raw`, cleared) rozkłada się więc na tag + payload, a nie na tuple.
            #
            # POŁÓWKA COFNIĘTA JEST PODWIERSZEM SWOJEJ NAZWY (R-S3-2/R-S3-3), nie osobną pozycją:
            # zapytanie stawia ją zaraz pod połówką nietkniętą, a wcięcie i znacznik `↺` na
            # POCZĄTKU mówią to samo oku — zanim cokolwiek się utnie. Kolor `warn`, nie `gold`:
            # złoto jest akcentem marki i w jasnym motywie ma 2,7:1, więc do tekstu się nie nadaje
            # (`theme.py` §akcenty). Adnotacja słowna zostaje, ale schodzi do członu trzeciego.
            cofniete = bool(r["cleared"])
            # WCIĘCIE TWIERDZI PRZYNALEŻNOŚĆ, więc wolno je postawić WYŁĄCZNIE pod własnym
            # rodzicem (firsthand 0810, znalezisko 1 — blokada odbioru). Zapytanie grupuje po
            # `(object_raw, cleared)`, więc nazwa, której cofnięto WSZYSTKIE klatki, oddaje
            # JEDEN wiersz `cleared=1` — a bezwarunkowe wcięcie podwieszało go pod obcą nazwę
            # stojącą wyżej. Zmierzone na 45 pozycjach: prawdziwe pary DWIE, reszta sierot.
            # Szkoda jest ta sama, przed którą broniło R-S3-2 („user załatwia rodzica i zostawia
            # podwiersz"), tylko wprowadzona z drugiej strony. Sierota traci WYŁĄCZNIE wcięcie —
            # znacznik, kolor i adnotacja zostają, bo werdykt ręki jest faktem niezależnym od
            # sąsiedztwa. Warunek jest lokalny: sort trzyma nietkniętą połówkę BEZPOŚREDNIO nad
            # cofniętą (klucz `review_queue`: suma, nazwa naturalnie, nazwa, `cleared` - od W-4
            # w Pythonie, nie w `ORDER BY`), więc rodzicem może być tylko wiersz poprzedni.
            #
            # WCIĘCIE JEST DANĄ, NIE TEKSTEM (W-5): poziom idzie rolą `rows.INDENT`, którą delegat
            # zamienia na px z metryki fontu przy malowaniu - `DisplayRole` obu połówek niesie TĘ
            # SAMĄ etykietę (`_etykieta_cofnieta`) i różni je wyłącznie ta rola.
            podwiersz = cofniete and rodzic == r["object_raw"]
            rodzic = None if cofniete else r["object_raw"]
            etykieta = r["object_raw"]
            if cofniete:
                etykieta = _etykieta_cofnieta(etykieta)
            self._add_review_item(
                etykieta,
                count=i18n.t_plural("object.review_count", r["n"]),
                mark=i18n.t("object.review_cleared_mark") if cofniete else None,
                fg=_WERDYKT["fg"] if cofniete else None,
                tag="object_raw_cleared" if cofniete else "object_raw",
                payload=r["object_raw"],
                indent=1 if podwiersz else 0)
        # Bezimienne (T5a): grid „Do przeglądu" je pokazuje, kolejka do dziś o nich milczała — bez
        # `object_raw` nie ma klucza grupowania, więc idą własnym licznikiem. Od P-D pozycja DRĄŻY
        # do klatek i niesie akcję „Napraw nagłówek…" (nazwa wraca do PLIKU, nie do bazy). Tag
        # nadawany WYŁĄCZNIE przy n>0: kubełek pusty ma zostać informacyjny, żeby zaznaczenie nie
        # otwierało okna bez treści.
        self._add_review_item(i18n.t("object.nameless_line"),
                              count=i18n.t_plural("object.review_count", q["nameless_count"]),
                              tag="nameless" if q["nameless_count"] > 0 else None,
                              info=i18n.t("object.nameless_info_empty"))
        # Druga połowa tego kubełka (R-S3-1) — lustro wiersza RAW-owego niżej, z tego samego powodu
        # i w tej samej formie. Klatka trafia tu, gdy nazwę zdjąłeś ręką, a nagłówek o obiekcie
        # MILCZY (nazwa przyszła z regionu/ścieżki/xref, nie z karty). QUIET — wiersza nie ma,
        # dopóki nic nie cofnięto; na archiwum bez ani jednego nagrobka ekran wygląda jak przedtem.
        # ZNACZNIK NALEŻY SIĘ WSZYSTKIM TRZEM BLIŹNIACZYM PAROM, nie tylko pętli wyżej (firsthand
        # 0810, znalezisko 2). Etykieta połówki cofniętej jest DOSŁOWNIE tym samym zdaniem, co
        # etykieta połówki nietkniętej (`nameless` ≡ `nameless_cleared` i tak samo dla RAW-a
        # i stosów) — więc bez `↺` na początku dwa sąsiednie wiersze różnią się wyłącznie kolorem
        # i adnotacją stojącą w trzeciej kolumnie, czyli tam, gdzie wzrok trafia ostatni. Wcięcia
        # te wiersze NIE dostają i to jest różnica wobec pętli `object_review`: są bliźniakami
        # w partycji, a nie połówkami jednej nazwy.
        if q["nameless_cleared_count"] > 0:
            self._add_review_item(
                _etykieta_cofnieta(i18n.t("object.nameless_cleared_line")),
                count=i18n.t_plural("object.review_count", q["nameless_cleared_count"]), mark=i18n.t("object.review_cleared_mark"),
                fg=_WERDYKT["fg"], tag="nameless_cleared")
        # Bliźniak kubełka wyżej po drugiej stronie FORMATU (`resolver.NO_OBJECT_CARD_FILETYPES`):
        # RAW nie ma karty `OBJECT` z natury, więc „Napraw nagłówek…" go nie dotyczy — drogą
        # naprawy jest RĘKA. Do S4 wiersz był INFORMACYJNY i to była luka, nie decyzja: akcja
        # „Przypisz obiekt…" zapalała się wyłącznie przy tagu `object_raw`, którego ta populacja
        # NIE MA z definicji formatu, więc jedyna droga naprawy nie miała powierzchni.
        # Pokazywany TYLKO gdy populacja istnieje: na archiwum bez lustrzanki to stałe „0".
        if q["nameless_raw_count"] > 0:
            self._add_review_item(i18n.t("object.nameless_raw_line"),
                                  count=i18n.t_plural("object.review_count", q["nameless_raw_count"]),
                                  mark=i18n.t("object.mark_by_hand"), tag="nameless_raw")
        # Druga połowa tego samego kubełka — klatki, którym nazwę ZDJĄŁEŚ. Osobny wiersz, nie
        # dopisek: do rozszczepienia wracały nieodróżnialne od nietkniętych, a „Przypisz obiekt…"
        # cicho ich nie tykało. QUIET — wiersza nie ma, dopóki nic nie cofnięto.
        if q["nameless_raw_cleared_count"] > 0:
            self._add_review_item(
                _etykieta_cofnieta(i18n.t("object.nameless_raw_cleared_line")),
                count=i18n.t_plural("object.review_count", q["nameless_raw_cleared_count"]), mark=i18n.t("object.review_cleared_mark"),
                fg=_WERDYKT["fg"], tag="nameless_raw_cleared")
        # PODZBIÓR kubełka wyżej, nie szósty kubełek (S2, D-OW-2/B): tym klatkom ŚCIEŻKA proponuje
        # kanon, a zapis czeka na gest człowieka. Wiersz stoi ZARAZ POD RAW-em, bo opisuje jego
        # drogę wyjścia — i świadomie NIE wchodzi do partycji, która już je policzyła.
        # Klikalny tylko przy niepustej populacji: pusta lista propozycji nie ma czego pokazać.
        if q["path_proposed_frames"] is None:
            # Słownik obiektów własnych ma błąd — kubełek NIE UDAJE zera (to dwie różne prawdy):
            # wiersz mówi, że propozycji nie policzono, i nie prowadzi nigdzie, bo nie ma dokąd.
            self._add_review_item(i18n.t("object.path_proposed_broken"),
                                  info=i18n.t("object.path_proposed_broken_info"))
        elif q["path_proposed_frames"] > 0:
            self._add_review_item(
                i18n.t("object.path_proposed_line"),
                count=i18n.t("object.path_proposed_count", names=q["path_proposed_names"],
                             frames=q["path_proposed_frames"]),
                mark=i18n.t("object.mark_to_confirm"), tag="path_proposals")
        # TRZECI kubełek tej samej partycji (I-2b/D-P-I-5): gotowy obraz po integracji, wciągnięty
        # drogą „Stosy". Do 2026-08-02 był INFORMACYJNY, bo pisarz XISF nie umiał dopisać karty
        # (D-X-12) — wiersz z akcją obiecywałby zapis, który kończy się 'blocked' na każdej pozycji.
        # P6d nauczyła pisarza wstawiać kartę, a D-0802-1 otworzyła ten tor, więc kubełek DRĄŻY
        # tak samo jak lightowy. Osobny od niego zostaje, bo to osobna populacja (i osobny licznik
        # partycji), nie dlatego, że droga naprawy jest inna — jest ta sama.
        if q["nameless_stacks_count"] > 0:
            self._add_review_item(
                i18n.t("object.nameless_stacks_line"),
                count=i18n.t_plural("object.review_count", q["nameless_stacks_count"]),
                mark=i18n.t("object.mark_by_card"), tag="nameless_stacks")
        # Czwarta i ostatnia połówka (R-S3-1). Ten wiersz nie jest teoretyczny: D-OW-7 wpuściło
        # gest osi obiektu na GOTOWY OBRAZ, więc cofnięcie na stosie jest jednym kliknięciem —
        # a bez własnego wiersza stos z werdyktem ręki wracał nad kubełek wyżej nieodróżnialny
        # od stosu, o którym nikt nigdy nie decydował.
        if q["nameless_stacks_cleared_count"] > 0:
            self._add_review_item(
                _etykieta_cofnieta(i18n.t("object.nameless_stacks_cleared_line")),
                count=i18n.t_plural("object.review_count", q["nameless_stacks_cleared_count"]), mark=i18n.t("object.review_cleared_mark"),
                fg=_WERDYKT["fg"], tag="nameless_stacks_cleared")
        # PODZBIÓR kubełka stosów (E3-1) - lustro wiersza propozycji spod RAW-a: stos z drzewa
        # `STACKS`, którego nagłówek milczy, dostaje nazwę z folderu na POTWIERDZENIE. `None`
        # (słownik z błędem) nie ma tu własnego wiersza: zgłasza go już wiersz spod RAW-a.
        if q["path_proposed_stack_frames"]:
            self._add_review_item(
                i18n.t("object.path_proposed_line"),
                count=i18n.t("object.path_proposed_count", names=q["path_proposed_stack_names"],
                             frames=q["path_proposed_stack_frames"]),
                mark=i18n.t("object.mark_to_confirm"), tag="path_proposals",
                payload=PATH_STACKS_PAYLOAD)
        # JEDNOSTKA TEGO WIERSZA TO KLATKA, mimo że kubełek nazywa się od KOPII (firsthand 0810,
        # znalezisko 4 — lekarstwo poprawione po sprawdzeniu rdzenia). `resolver.review_state`
        # liczy tu `count(DISTINCT f.id)`, czyli klatki z ≥1 kopią oznaczoną nieczytelną, i robi
        # to świadomie („spójność z resztą liczników"). Odmiana idzie więc TYM SAMYM kluczem, co
        # każdy sąsiedni kubełek; własny klucz „N kopii" kłamałby o tym, co policzono.
        # ROZBICIE PO RODZAJU (P4-2) idzie do podpowiedzi wiersza, liczone PO KOPIACH: kubełek
        # z samą liczbą nie mówił, czy szukać winy w dysku, czy w pliku. Pusty kubełek go nie
        # dostaje - zero nie ma czego rozbijać, a jego zdanie niesie `info`.
        from horreum.gui.pipeline import unreadable_kinds_text   # lazy: jak montaż Dostawy
        self._add_review_item(i18n.t("object.unreadable_line"),
                              count=i18n.t_plural("object.review_count", q["unreadable_count"]),
                              tag="unreadable" if q["unreadable_count"] > 0 else None,
                              info=i18n.t("object.unreadable_info_empty"),
                              tip=unreadable_kinds_text(resolver.unreadable_kind_counts(self.con))
                              if q["unreadable_count"] > 0 else None)
        # OŚ SPRZĘTU WYCHODZI Z WIERSZA INFORMACYJNEGO (R1) — do tej zmiany była połową licznika
        # z notą „rozwiązywanie w przygotowaniu". Nota mówiła prawdę i dlatego musiała zniknąć
        # razem z drogą: gest istnieje, więc wiersz DRĄŻY i niesie akcję. Reguła pustego kubełka
        # ta sama, co u sąsiadów: zero nie ma dokąd prowadzić, więc zostaje informacyjne.
        self._add_review_item(i18n.t("object.config_review_line"),
                              count=i18n.t_plural("object.review_count", q["config_review_count"]),
                              tag="config_review" if q["config_review_count"] > 0 else None,
                              info=i18n.t("object.config_review_info_empty"))
        # DRUGA POŁOWA TEGO KUBEŁKA — klatki, którym zestaw NADAŁA RĘKA (bramka pakietu 3a,
        # zarzut 1). To nie kosmetyka wiersza, tylko jedyna droga powrotna: po geście klatka
        # wypada z kubełka (`config_id` już nie jest NULL), a automat jej nie tknie (guard
        # lepkości) — bez tego wiersza pierwsza pomyłka ręki byłaby WIECZNA. Ta sama figura,
        # co „cofnięte ręką" na osi obiektu: populacja rozłączna, własny licznik, ta sama akcja.
        # QUIET — wiersza nie ma, dopóki nikt niczego nie wskazał.
        if q["config_by_hand_count"] > 0:
            self._add_review_item(
                i18n.t("object.config_by_hand_line"),
                count=i18n.t_plural("object.review_count", q["config_by_hand_count"]), tag="config_by_hand")
        # licznik POZOSTAŁEGO kanału jako pozycja informacyjna (bez tagu → nieklikana); nota
        # „rozwiązywanie w przygotowaniu" ZAWĘŻONA do klatek bez nagłówka — obiekt-review, kopie
        # i (od R1) oś sprzętu mają już swoje akcje.
        self._add_review_item(
            i18n.t("object.review_info"),
            count=i18n.t_plural("object.review_count", q["headerless_count"]),
            info=i18n.t("object.review_info_why"))
        # Wspólna szerokość kolumny adnotacji PO wypełnieniu listy (kontrakt `rows.fit_tertiary`) —
        # dopiero to ustawia „cofnięte ręką" w jedną kolumnę zamiast pozwalać każdemu wierszowi
        # rysować się na własnej szerokości. Lista bez ani jednego nagrobka dostaje 0 = układ
        # dwuczłonowy, czyli dokładnie to, co było przed R-S3-3.
        self.review.itemDelegate().fit_tertiary(
            [self.review.item(i).data(rows.TERTIARY) for i in range(self.review.count())])
        self._dopasuj_kolejke()

    def _dopasuj_kolejke(self):
        """Zetnij wysokość kolejki przeglądu DO TREŚCI, z sufitem w wierszach (W-3).

        Wzorzec `tasks._fit_task_list`, z jedną różnicą, która jest tu sednem: tam lista ma pięć
        pozycji i sufit byłby zbędny, a kolejka przeglądu rośnie do ~45 — dopasowanie bez sufitu
        zabrałoby cały pion tabeli „Biblioteka", czyli zamieniło jeden dług na drugi. Stąd
        `setMaximumHeight` (nie `setFixedHeight`) i suma po `_KOLEJKA_SUFIT_WIERSZY` wierszach:
        krótka kolejka nie zostawia pustki, długa dostaje pasek przewijania.

        WYSOKOŚĆ SUMUJEMY PRZEZ DELEGATA, nie mnożymy jednej podpowiedzi — wiersze `TwoPartDelegate`
        nie muszą być równe, a `sizeHintForRow(0)` kłamało już raz w bliźniaczej liście (WIZ #14).
        Metryki fontu są prawdziwe dopiero po `show()`, więc wołane jest to z `_load_review`, czyli
        przy każdym napełnieniu listy, a nie raz w budowie."""
        n = self.review.count()
        if not n:
            # Strukturalnie nieosiągalne (wiersz informacyjny `review_info` wchodzi bezwarunkowo),
            # więc lista bez treści zwija się do ramki zamiast rezerwować pion na nic.
            self.review.setMaximumHeight(2 * self.review.frameWidth())
            return
        model = self.review.model()
        # Pytamy delegata TYLKO o wiersze pod sufitem: przy pełnej kolejce reszta i tak nie wpływa
        # na wynik, a `refresh()` osi leci po KAŻDYM geście gridu (`object_axis_changed`).
        self.review.setMaximumHeight(
            sum(self.review.sizeHintForIndex(model.index(i, 0)).height()
                for i in range(min(n, _KOLEJKA_SUFIT_WIERSZY)))
            + 2 * self.review.frameWidth())

    def _add_review_item(self, text, *, tag=None, payload=None, info=None,
                         count=None, mark=None, fg=None, indent=0, tip=None):
        """Jedna pozycja kolejki przeglądu — JEDEN producent wiersza dla wszystkich kubełków.

        WIERSZ JEST TRÓJCZŁONOWY (R-S3-3): `text` = nazwa (człon pierwszy, elidowany), `count` =
        liczba klatek (człon drugi, przy prawej krawędzi, razem ze znacznikiem drogi „›"), `mark` =
        adnotacja typu „cofnięte ręką" (człon trzeci, własna kolumna). `fg` maluje CAŁY wiersz —
        używa go połówka z nagrobkiem, bo kolor jest tam TREŚCIĄ (werdykt człowieka), a nie ozdobą.
        Kubełki bez własnej liczby podają sam `text` i zachowują się dokładnie jak przedtem.

        `indent` (W-5, int poziom) niesie rolę `rows.INDENT` - WYŁĄCZNIE dla podwiersza pod własnym
        rodzicem (pętla `object_review`, `_load_review`). `0`/domyślny NIE ustawia roli wcale, więc
        wszystkie pozostałe kubełki zachowują się bez zmian. `text` nigdy nie niesie wcięcia
        spacjami - to był dług W-5 (jechało do schowka i do wersji EN, a przy elizji zjadało miejsce
        nazwie).

        WIZ #11: pięć wierszy miało identyczny krój i kolor, a klikalne były dwa — nic na ekranie
        nie mówiło, który z nich prowadzi dalej. Wiersz z drogą dostaje znacznik „›" (ten sam co
        na liście Porządków), wiersz bez drogi gaśnie i przestaje być zaznaczalny.

        KUBEŁEK PUSTY NIE MA DOKĄD PROWADZIĆ, więc jest informacyjny — jedna reguła dla wszystkich
        (wiz T2 N6: dwa puste kubełki zachowywały się dwojako, a drążenie w pusty otwierało tabelę
        z zerem wierszy i bez zdania). Wyszarzenie SELEKTOWALNEGO wiersza było przy okazji
        defektem kontrastu (T2 N3): jawny `ForegroundRole` bije `HighlightedText`, więc zaznaczona
        szarość na podświetleniu spadała do 1,84:1 — ta sama lekcja, którą `rows.TwoPartDelegate`
        ma już zapisaną w `_own_color`. Brak drogi ⇒ brak zaznaczenia ⇒ problem nie powstaje.

        Rozdzielenie stoi na TAGU, nie na osobnym parametrze — tag jest jedynym faktem, którego
        dispatch (`_selected_review`) realnie używa, więc druga flaga „czy klikalny" mogłaby się
        z nim rozjechać (SPOT).

        WIERSZ INFORMACYJNY TŁUMACZY SIĘ SAM (F-2, firsthand Zdzinia 0804). Do tej zmiany klik
        w niego nie dawał ŻADNEJ odpowiedzi — i to dosłownie: wiersz nie jest zaznaczalny, więc
        `itemSelectionChanged` w ogóle nie leci i nie ma nawet podświetlenia. Dla użytkownika jest
        to nieodróżnialne od zawieszenia, a trzy z pięciu wierszy kolejki tak mają. Dostaje więc
        `info`: tooltip pod kursorem ORAZ zdanie w pasku statusu po kliknięciu — mówiące, CZEGO
        ten wiersz jest opisem i dlaczego nie prowadzi dalej. Domyślne `info` jest świadome:
        wiersz bez własnego wytłumaczenia i tak ma odpowiedzieć cokolwiek, bo cisza jest tu
        gorsza od zdania ogólnego.

        `tip` (P4-2) to podpowiedź wiersza Z DROGĄ - osobno od `info`, bo `info` opisuje wiersz,
        który NIE prowadzi dalej (i trafia też do paska statusu), a `tip` dopowiada szczegół
        wierszowi, który prowadzi (rozbicie kopii nieczytelnych po rodzaju awarii). Wiersz bez
        drogi `tip` ignoruje: tam podpowiedzią jest `info` i dwa zdania by się przykrywały."""
        it = QListWidgetItem(text)
        # ZNACZNIK DROGI I LICZBA IDĄ W CZŁON DRUGI (R-S3-3, wzorzec `tasks.py`): „›" doklejone do
        # tekstu jechało za długością nazwy, więc w liście o zmiennych nazwach nie było kolumny,
        # którą dałoby się skanować wzrokiem. Człon drugi rysuje się od prawej i NIE jest elidowany.
        czlon2 = " ".join(filter(None, (count, "›" if tag else "")))
        it.setData(rows.SECONDARY, czlon2)
        if mark:                               # adnotacja („cofnięte ręką") — własna kolumna z separatorem
            it.setData(rows.TERTIARY, f"  ·  {mark}")
        if indent:                              # poziom wcięcia (W-5) - 0/domyślny nie stawia roli wcale
            it.setData(rows.INDENT, indent)
        if tag:
            it.setData(_REVIEW_TAG, tag)
            it.setData(_REVIEW_PAYLOAD, payload)
            if tip:
                it.setToolTip(tip)
        else:
            it.setFlags(Qt.ItemIsEnabled)      # informacyjny, nie do zaznaczenia
            it.setForeground(_DIM["fg"])
            powod = info or i18n.t("object.review_info_generic")
            it.setData(_REVIEW_INFO, powod)
            it.setToolTip(powod)
        if fg is not None:
            it.setForeground(fg)
        self.review.addItem(it)

    def _on_review_clicked(self, item):
        """Klik w wiersz kolejki. Wiersz Z DROGĄ obsługuje `_on_review_selected` (przez zaznaczenie);
        tu zostaje WYŁĄCZNIE wiersz informacyjny — jedyny, który sam z siebie nie odpowiada niczym
        (F-2). `itemClicked` leci także dla wierszy niezaznaczalnych, bo są `ItemIsEnabled`."""
        if item is not None and item.data(_REVIEW_TAG) is None:
            self.status_message.emit(item.data(_REVIEW_INFO)
                                     or i18n.t("object.review_info_generic"))

    def _on_review_double_clicked(self, item):
        """Dwuklik w pozycję kolejki = jej AKCJA (R-S3-6). Skrót gestu, nie druga ścieżka zapisu.

        Akcję wybiera stan przycisków, a nie własna mapa tag→akcja: `_sync_assign_enabled` jest
        JEDYNYM właścicielem tego przypisania (cztery rozłączne zbiory tagów), więc druga
        wyliczanka rozjechałaby się z nim przy pierwszym nowym kubełku (SPOT). Skutek uboczny jest
        pożądany: dwuklik nie zrobi nigdy niczego, czego nie da się zrobić przyciskiem — w tym
        podczas biegu pipeline'u, kiedy wszystkie cztery są wygaszone.

        Wiersz informacyjny nie jest zaznaczalny, więc `itemDoubleClicked` na nim nie zmieni
        zaznaczenia — przyciski patrzą wtedy na POPRZEDNIĄ pozycję. Stąd jawny warunek na tagu:
        bez niego dwuklik w wiersz bez drogi odpalałby akcję sąsiada."""
        if item is None or item.data(_REVIEW_TAG) is None:
            return
        for btn in (self.assign_btn, self.repair_btn, self.confirm_path_btn, self.set_config_btn):
            if btn.isEnabled():
                btn.click()
                return

    def _set_obj_cell(self, r, c, text, *, data=None, align=None, tip=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if align is not None:                 # liczba klatek prawo-wyrównana (skanowalność, wizytator O1)
            item.setTextAlignment(align)
        if data is not None:
            item.setData(Qt.UserRole, data)
        if tip:
            item.setToolTip(tip)
        self.objects.setItem(r, c, item)

    def _selected_object_id(self):
        sm = self.objects.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows:
            return None
        item = self.objects.item(rows[0].row(), OBJ_COL_CANON)
        return item.data(Qt.UserRole) if item else None

    def _selected_review(self):
        """Zaznaczona pozycja kolejki jako para (tag, payload) albo (None, None). Role nazwane
        (`_REVIEW_TAG`/`_REVIEW_PAYLOAD`) — payload NIE mieszka już pod `UserRole+1`, bo tę rolę
        zajmuje człon drugi delegata (R-S3-3; string-tag dispatch bez zmian, R#6)."""
        sel = self.review.selectedItems()
        if not sel:
            return None, None
        return sel[0].data(_REVIEW_TAG), sel[0].data(_REVIEW_PAYLOAD)

    def _sync_assign_enabled(self):
        """Akcje kolejki aktywne WYŁĄCZNIE przy swojej pozycji i poza biegiem pipeline (szczery
        disabled — UI nie kłamie; R#10: obie listy wzajemnie czyszczą selekcję, więc przyciski
        śledzą tag, nie to, która lista „ostatnio kliknięta"). „Napraw nagłówek…" gaśnie dodatkowo,
        gdy DRUGA powierzchnia writebacku pisze do plików (mutex, D-PD-3)."""
        tag, _ = self._selected_review()
        # Dwa tagi, jedna akcja (S4): grupa Z zeznaniem i kubełek RAW różnią się tym, SKĄD bierze
        # się grupa, nie tym, co się z nią robi — obie nazywa ręka, obie zapisuje ta sama klinga.
        # Trzeci warunek to CEL: od S4 pisze się zaznaczenie panelu, więc puste zaznaczenie znaczy
        # „nie ma czego zapisać" i przycisk ma to powiedzieć wygaszeniem, a nie ciszą po kliknięciu.
        self.assign_btn.setEnabled(tag in _ASSIGN_TAGS and not self._busy
                                   and bool(self._selected_frame_ids()))
        # Jedna akcja dla całej rodziny kubełków naprawianych KARTĄ: lighty archiwum i gotowe stosy
        # mają od D-0802-1 tę samą drogę (karta `OBJECT` do PLIKU), a od R-S3-1 każdy z nich ma
        # jeszcze połówkę cofniętą — dla niej ta droga jest TĄ SAMĄ drogą, bo writeback gasi
        # nagrobek. Zbiór zamiast wyliczanki: przy rozszczepieniu wyliczanka zapala przycisk nad
        # jedną połówką i gasi nad drugą, choć obie prowadzą do tego samego okna.
        self.repair_btn.setEnabled(tag in _CARD_TAGS
                                   and not self._busy and not self._foreign_wb)
        # Potwierdzanie propozycji pisze do BAZY i (od O3 kroku 1) kartę `OBJECT` do PLIKÓW - więc
        # mutex writebacku (`_foreign_wb`, D-PD-3) dotyczy go tak samo jak „Napraw nagłówek…".
        self.confirm_path_btn.setEnabled(tag == "path_proposals"
                                         and not self._busy and not self._foreign_wb)
        # Wygaszony przycisk tłumaczy się SAM (ta sama lekcja co WIZ #12 pięć linii wyżej): przy
        # swoim kubełku mówi, CO zrobi; poza nim — czego brakuje, żeby dało się go kliknąć.
        self.confirm_path_btn.setToolTip(i18n.t(
            "object.confirm_path_tip" if tag == "path_proposals"
            else "object.confirm_path_tip_pick"))
        # Oś SPRZĘTU (R1) — jak potwierdzanie propozycji: pisze do BAZY, więc mutex writebacku
        # jej nie dotyczy; bramką jest sam bieg pipeline'u. Wygaszony przycisk tłumaczy się sam.
        self.set_config_btn.setEnabled(tag in _CONFIG_TAGS and not self._busy)
        self.set_config_btn.setToolTip(i18n.t(
            "object.set_config_tip_change" if tag == "config_by_hand"
            else "object.set_config_tip" if tag == "config_review"
            else "object.set_config_tip_pick"))
        # WIZ #12: „Przypisz obiekt…" gasł BEZ SŁOWA obok aktywnego „Napraw nagłówek…", więc obie
        # drogi naprawy wyglądały jak jedna zepsuta. Wygaszony przycisk tłumaczy się sam — tooltip
        # nazywa drogę WŁAŚCIWĄ dla zaznaczonego kubełka, zamiast milczeć o istnieniu drugiej.
        #
        # KARTA PYTA PIERWSZA (R-S3-1): połówka cofnięta kubełka kartowego jest jednocześnie
        # `_CLEARED_TAGS` i `_CARD_TAGS`, a rozstrzyga o niej DROGA NAPRAWY, nie to, kto zdjął
        # nazwę. Przy starej kolejności („cofnięte" na górze) wygaszony przycisk mówiłby nad tym
        # wierszem „ręka nadpisze Twój werdykt" — obietnicę akcji, której ten kubełek nie ma.
        self.assign_btn.setToolTip(i18n.t(
            "object.assign_tip_card" if tag in _CARD_TAGS else
            "object.assign_tip_cleared" if tag in _CLEARED_TAGS else
            "object.assign_tip" if tag == "object_raw" else
            "object.assign_tip_raw" if tag == "nameless_raw" else
            "object.assign_tip_pick"))
        # TRZECI przycisk tego rzędu milczał — jako JEDYNY (R-S3-7). Miał `enabled=False` i PUSTY
        # tooltip dla każdego wiersza, choć obaj sąsiedzi tłumaczą się od S2/S4. Skutek: kubełek,
        # który naprawia się kartą w PLIKU, wyglądał identycznie jak ten, który naprawia się ręką
        # w bazie — a różnica jest fundamentalna, bo jedna droga tyka archiwum, druga nie.
        # Osobny człon dla mutexu writebacku: „nie da się" i „nie teraz" to dwa różne zdania.
        # Mutex writebacku BIJE powód kubełka: „nie da się" i „nie teraz" to dwa różne zdania,
        # a użytkownik czekający na cudzy zapis potrzebuje tego drugiego.
        self.repair_btn.setToolTip(i18n.t(
            "repair.tip_busy" if self._foreign_wb and tag in _CARD_TAGS
            else _REPAIR_TIPS.get(tag, "repair.tip_pick")))

    def _on_object_selected(self):
        """Obiekt zaznaczony → klatki tego obiektu (z bieżącym filtrem). Czyści selekcję review (wzajemnie
        wykluczające źródła klatek: obiekt vs pozycja review) i wychodzi z trybu „kopie"."""
        if self._loading:
            return
        oid = self._selected_object_id()
        if oid is None:
            return
        if self.review.selectedItems():
            self.review.clearSelection()
        self._restore_frames_mode()
        self._sync_assign_enabled()
        flt = self._filters()
        rows = queries.object_frames(
            self.con, oid, telescope_id=flt["telescope_id"], filter_canon=flt["filter_canon"])
        self.frames_label.setText(i18n.t("object.frames_of_object"))
        self._fill_frames(rows, present_col=True)

    def _on_review_selected(self):
        """Pozycja kolejki zaznaczona → dispatch po tagu: `object_raw` = nierozwiązane klatki tej
        nazwy (+ aktywacja „Przypisz obiekt…"); `nameless_raw` = klatki w formacie bez karty
        `OBJECT` (S4 — ta sama akcja, grupa bez zeznania); `unreadable` = tryb „kopie" prawego
        panelu (Z6); pozycja informacyjna (bez tagu) nie drąży.

        BEZ FAZY ZAJĘTOŚCI, na pomiarze (F-1): drążenie kubełków mierzy **76–103 ms** na 16 648
        klatkach po naprawie `b5d1b5c` — do niej te same ścieżki brały dziesiątki sekund i faza
        byłaby tu konieczna, ale defekt kwadratowy zdjęto i został gest, który człowiek odbiera
        jako natychmiastowy."""
        if self._loading:
            return
        tag, payload = self._selected_review()
        self._sync_assign_enabled()
        if tag is None:                        # nic nie zaznaczone / pozycja informacyjna
            return
        self.objects.clearSelection()
        self._drill_review(tag, payload)

    def _drill_review(self, tag, payload):
        """Drążenie zaznaczonej pozycji kolejki do prawego panelu — wykonawcza połowa
        `_on_review_selected` (dispatch po tagu oddzielony od bramek wejścia)."""
        if tag in ("object_raw", "object_raw_cleared"):
            cofniete = tag in _CLEARED_TAGS
            self._restore_frames_mode()
            # Drążenie PO PARZE, nie po samym stringu: bez członu `cleared` wróciłaby UNIA obu
            # pozycji i zapis sięgnąłby klatek spoza klikniętego wiersza.
            rows = queries.object_review_frames(self.con, payload, cleared=cofniete)
            self.frames_label.setText(i18n.t(
                "object.frames_review_cleared" if cofniete else "object.frames_review",
                name=payload))
            self._fill_frames(rows, present_col=False)
            self._select_all_frames()
        elif tag in ("nameless", "nameless_cleared"):
            cofniete = tag in _CLEARED_TAGS
            self._restore_frames_mode()
            rows = queries.nameless_frames(self.con, cleared=cofniete)
            self.frames_label.setText(i18n.t(
                "object.frames_nameless_cleared" if cofniete
                else "object.frames_nameless", n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag in ("nameless_raw", "nameless_raw_cleared"):
            cofniete = tag in _CLEARED_TAGS
            self._restore_frames_mode()
            rows = queries.nameless_raw_frames(self.con, cleared=cofniete)
            self.frames_label.setText(i18n.t(
                "object.frames_nameless_raw_cleared" if cofniete
                else "object.frames_nameless_raw", n=len(rows)))
            self._fill_frames(rows, present_col=False)
            self._select_all_frames()
        elif tag in ("nameless_stacks", "nameless_stacks_cleared"):
            cofniete = tag in _CLEARED_TAGS
            self._restore_frames_mode()
            rows = queries.nameless_stack_frames(self.con, cleared=cofniete)
            self.frames_label.setText(i18n.t(
                "object.frames_nameless_stacks_cleared" if cofniete
                else "object.frames_nameless_stacks", n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag == "path_proposals":
            # Drążenie pokazuje KLATKI (żeby wiersz nie był ślepym zaułkiem), a jednostkę przeglądu
            # — NAZWĘ — pokazuje dopiero okno potwierdzania. Id-y bierzemy od JEDNEGO właściciela
            # predykatu; read-model tylko je dekoruje kolumnami panelu.
            self._restore_frames_mode()
            ids = [fid for p in path_proposals_for(self.con, payload) for fid in p.frame_ids]
            rows = queries.path_proposal_frames(self.con, ids)
            self.frames_label.setText(i18n.t("object.frames_path_proposed", n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag in ("config_review", "config_by_hand"):
            # Drążenie pokazuje KLATKI, a jednostkę gestu — folder × kamerę — pokazuje dopiero
            # okno (lustro `path_proposals` wyżej: tam jednostką jest nazwa). Read-model jest
            # LUSTREM licznika kubełka i test pinuje tę równość. Dwa tagi, bo dwie ROZŁĄCZNE
            # populacje (bez zestawu / z zestawem od ręki) — i to jest cały sens drugiego wiersza.
            self._restore_frames_mode()
            reka = tag == "config_by_hand"
            rows = (queries.config_by_hand_frames(self.con) if reka
                    else queries.config_review_frames(self.con))
            self.frames_label.setText(i18n.t(
                "object.frames_config_by_hand" if reka else "object.frames_config_review",
                n=len(rows)))
            self._fill_frames(rows, present_col=False)
        elif tag == "unreadable":
            self._show_copies()

    # ------------------------------------------------ tryb „kopie" (Z6)

    def _show_copies(self):
        """Prawy panel w trybie „kopie": DOKŁADNE location z markerem `unreadable_since` (#13/Z6).
        Tryb znika przy `refresh()` i przy wyborze obiektu/pozycji review (powrót do klatek
        zaznaczenia - świadomie, udokumentowane w D-P4-5).

        RESZTĘ PANELU BIERZE „POWÓD", bo to dla tej kolumny tryb istnieje; „Ścieżka" dostaje szerokość
        treści z sufitem `COPY_PATH_MAX_PX`, a pełną wartość niesie tooltip komórki. Dwa pomiary
        na pf4 pokazały dwie strony tego samego błędu. Firsthand 2026-08-01 mierzył 100-znakową
        ŚCIEŻKĘ przy `ResizeToContents`: wypychała diagnozę za prawą krawędź, więc `Stretch` poszedł
        na ścieżkę. Firsthand 2026-09-26 (kopia pf4, skale 100/125/150 %) zmierzył 150-znakowy POWÓD
        (`PermissionError` z `open()` niósł pełną ścieżkę archiwum): „Powód" wyszedł na 963 px
        w panelu 571 px, a „Ścieżka" ze `Stretch` spadła do 86 px (`R:\\ASTRO_\\LI...`). `Stretch`
        na kolumnie pomocniczej oddaje ją na łaskę najdłuższej treści sąsiada - ma iść za kolumną,
        dla której tryb istnieje, a sufit chroni ścieżkę przed zjedzeniem panelu. Powtórkę ścieżki
        w powodzie zdjęto przy tym u źródła (`scan.unreadable_reason_of`)."""
        rows = queries.unreadable_copies(self.con)
        self._copies_mode = True
        self.frames.setColumnCount(len(COPY_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(COPY_HEADERS))
        fh = self.frames.horizontalHeader()
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Sufit działa na cały nagłówek, ale poza ścieżką żadna kolumna treści go nie sięga,
        # a sekcji `Stretch` Qt nim nie przycina (sonda offscreen 2026-09-26). Zdejmuje go
        # `_restore_frames_mode` - tryb klatek ma własny układ.
        fh.setMaximumSectionSize(COPY_PATH_MAX_PX)
        fh.setSectionResizeMode(COPY_COL_REASON, QHeaderView.Stretch)
        self.frames.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        _przeladuj_wiersze(self.frames, len(rows))
        for r, row in enumerate(rows):
            path = row["path"] or ""
            # W KOMÓRCE NAZWA PLIKU, pełna ścieżka w podpowiedzi - forma ścieżki z Duplikatów.
            # Kopie nieczytelne dzielą długi prefiks (`R:\ASTRO_\STACKS\…`), więc pełna ścieżka
            # w sufit 200 px zostawiała z elizją w środku dwa końce, a człon rozróżniający kopie
            # wypadał właśnie ze środka (wizytacja na kopii pf4: pięć wierszy „R:\ASTRO_\STAC…").
            self._set_frame_cell(r, COPY_COL_PATH,
                                 queries.path_tail(path, dirs=0) if path
                                 else i18n.t("object.no_path"),
                                 tooltip=path or None)
            self._set_frame_cell(r, COPY_COL_VOLUME, row["volume"])
            self._set_frame_cell(r, COPY_COL_PRESENT,
                                 i18n.t("common.yes") if row["present"] else i18n.t("common.no"))
            self._set_frame_cell(r, COPY_COL_MARKED, _fmt_event_ts(row["unreadable_since"]),
                                 tooltip=row["unreadable_since"])
            # Powód ze STANU kopii (Z6, P4-2): marker mówi KTÓRA kopia, ten człon - CZEGO nie da
            # się przeczytać i GDZIE szukać winy (rodzaj przed diagnozą). Tooltip niesie diagnozę
            # dosłownie, bez etykiety rodzaju - to ją kopiuje się do zgłoszenia.
            self._set_frame_cell(r, COPY_COL_REASON, _copy_reason(row["kind"], row["reason"]),
                                 tooltip=row["reason"] or None)
        # Elizja W ŚRODKU i szerokość z treści - ten sam mechanizm co ścieżka w Duplikatach
        # (FH-14): domyślna elizja z prawej zostawiała „R:\ASTRO_\LI…" bez nazwy pliku.
        from horreum.gui import grid       # lazy - wzorzec `_on_confirm`
        grid.kolumna_z_tresci(self.frames, COPY_COL_PATH, sufit=COPY_PATH_MAX_PX)
        self.frames_label.setText(i18n.t("object.unreadable_title", n=len(rows)))

    def _restore_frames_mode(self):
        """Powrót prawego panelu z trybu „kopie" do tabeli klatek (kolumny + nagłówki FRAME_*)."""
        if not self._copies_mode:
            return
        self._copies_mode = False
        self.frames.setItemDelegateForColumn(COPY_COL_PATH, None)   # w trybie klatek kolumna 0 to sha
        self.frames.setColumnCount(len(FRAME_HEADERS))
        self.frames.setHorizontalHeaderLabels(_headers(FRAME_HEADERS))
        fh = self.frames.horizontalHeader()
        fh.setMaximumSectionSize(-1)          # sufit trybu „kopie" zdjęty (-1 = domyślny Qt)
        fh.setSectionResizeMode(QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(FRAME_COL_PATH, QHeaderView.Stretch)
        self._elizja_sciezki_klatek()

    def _elizja_sciezki_klatek(self):
        """Ścieżka trybu klatek elidowana W ŚRODKU - ten sam delegat co ścieżka trybu „kopie"
        i Duplikatów (`grid.elizja_w_srodku`). Szerokość zostaje przy `Stretch`; zmienia się
        wyłącznie miejsce cięcia: elizja z prawej zostawiała z ogona ścieżki katalog i zjadała
        nazwę pliku (wizytacja: „21P_Giacobini-Zinner\\NOC…" w czterech wierszach naraz)."""
        from horreum.gui import grid       # lazy - wzorzec `_on_confirm`
        grid.elizja_w_srodku(self.frames, FRAME_COL_PATH)

    # ------------------------------------------------ akcja zapisu (#8/P4)

    def _on_assign(self):
        """„Przypisz obiekt…": dialog wyboru obiektu → JEDNA klinga `repo.user_assign_object`.
        Raport „przypisano N z M" z rozbiciem pominięć PER FAKT (R#8: dryf grupy = klatka zajęta
        między dialogiem a zapisem jest pomijana; R-S2b-13: dryf to tylko jeden z członów), potem
        refresh.

        DWA WEJŚCIA, JEDNA DROGA ZAPISU (S4): `object_raw` = grupa nierozpoznanej nazwy z nagłówka;
        `nameless_raw` = kubełek klatek w formacie bez karty `OBJECT`. Grupa idzie dalej jako LISTA
        `frame_ids`, nie jako tag — kto ją wyznacza, jest sprawą tego dispatchu, a nie zapisu.

        CELEM JEST ZAZNACZENIE PANELU (`_selected_frame_ids`), nie wynik drążenia: drążenie zaznacza
        wszystko, więc gest „cały kubełek" kosztuje tyle samo kliknięć co przedtem, ale zaznaczenie
        można PRZYCIĄĆ — a kubełek RAW nie jest grupą semantyczną i jeden kanon dla całej reszty
        archiwum byłby zapisem, który do S2b nie miał drogi odwrotu (dziś ma ją w Zbiorach, ale gest
        nadal ma trafiać w to, co user zaznaczył, a nie w całą resztę archiwum).

        KLUCZ ALIASU LICZY DIALOG (trzy przypadki — kontrakt w `AssignObjectDialog`), bo zna wybraną
        nazwę; tu zostaje wyłącznie bramka pustego klucza dla grupy Z ZEZNANIEM, bo to własność
        GRUPY, znana przed otwarciem okna (D-P4-2/R#3: alias `""` łapałby każdą niealfanumeryczną
        nazwę). Kubełek RAW tej bramki nie potrzebuje: on zeznania nie ma i klucz bierze się skądinąd."""
        tag, object_raw = self._selected_review()
        if tag in ("object_raw", "object_raw_cleared"):
            if not object_raw:
                return
            if not norm_alnum(object_raw):     # pusty klucz (D-P4-2/R#3) — grupa odrzucona
                QMessageBox.warning(
                    self, i18n.t("assign.title"),
                    i18n.t("object.alias_no_alnum", name=object_raw))
                return
        elif tag in ("nameless_raw", "nameless_raw_cleared"):
            object_raw = None
        else:
            return
        # NAGROBEK GASI DRUGI GEST CZŁOWIEKA — i to jest jedyne miejsce, w którym ta akcja różni
        # się między połówkami kubełka. Bez `overwrite_weak` klinga chroni werdykt ręki przed
        # przypadkowym wskrzeszeniem (`source_skip`), więc przycisk zapisywał 0 z N i mówił
        # „pominięto" bez powodu: kubełek miał akcję, akcja go nie tykała.
        cofniete = tag in _CLEARED_TAGS
        frame_ids = self._selected_frame_ids()
        if not frame_ids:
            # Przycisk jest wygaszony przy pustym zaznaczeniu, ale SLOT wolno zawołać skądinąd —
            # cisza po kliknięciu byłaby gorsza od odmowy, bo nie da się odróżnić od zapisu.
            self.status_message.emit(i18n.t("object.assign_nothing"))
            return
        # Kubełek cofniętych zaznacza WYŁĄCZNIE nagrobki (drążenie jedzie `cleared=True`), więc
        # liczba jest długością zaznaczenia — nie trzeba drugiego SELECT-a na ten sam fakt.
        dlg = AssignObjectDialog(self.con, object_raw=object_raw,
                                 frame_count=len(frame_ids),
                                 cleared_n=len(frame_ids) if cofniete else 0, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        canon, catalog, kind, alias_norm = dlg.selected
        try:
            with busy.busy(self.status_message.emit,
                           i18n.t("busy.saving_frames", n=len(frame_ids))):
                g = repo.user_assign_object(
                    self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                    frame_ids=frame_ids, now=self._now(), overwrite_weak=cofniete)
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("assign.title"), str(e))
            return
        # TEN SAM FAKT MUSI BRZMIEĆ TAK SAMO NA OBU POWIERZCHNIACH (wizytacja S3, R-S2b-13). Zapis
        # z kolejki najpierw wyrzucał `g.stacks`, które Zbiory mówiły („w tym gotowe obrazy: N"),
        # a potem spłaszczał pominięcia do „pominięte - zajęte między dialogiem a zapisem", choć
        # klinga oddaje rozbicie per fakt - i to kolejka jest naturalną drogą, którą stos trafia
        # pod ten gest. Człony składa więc ten sam dom, co zdanie Zbiorów.
        from horreum.gui import grid       # lazy - wzorzec `apply_theme`/`_mount_views`
        self.status_message.emit(
            i18n.t_plural("object.assigned_report", g.assigned + g.skipped, assigned=g.assigned,
                          canon=canon) + grid.zdanie_pominiec(g))
        self.refresh(select_canon=canon if g.assigned else None, select_first=bool(g.assigned))

    # ------------------------------------------------ akcja potwierdzania propozycji (S2)

    def _on_confirm_path(self):
        """„Zatwierdź ze ścieżki…": propozycje szczebla ścieżki → okno przeglądu → klinga
        `repo.user_assign_object` ze źródłem `path`.

        Propozycje liczymy TU, w chwili otwarcia — nie z licznika kolejki: między odświeżeniem
        a kliknięciem mógł przebiec `Rozwiąż` z workera i lista byłaby o niego starsza. Klinga
        pomija klatki, które w międzyczasie dostały obiekt (dryf), więc podwójne liczenie kosztuje
        jeden SELECT, a jego brak kosztowałby zapis pod nieaktualną listą."""
        # Populacja ZAZNACZONEGO wiersza (E3-1): RAW-y spod RAW-a, stosy spod stosów.
        _, payload = self._selected_review()
        propozycje = path_proposals_for(self.con, payload)   # 16 ms zmierzone - bez fazy (F-1)
        if not propozycje:
            self.status_message.emit(i18n.t("path.err.nothing"))
            return
        dlg = ConfirmPathObjectsDialog(self.con, proposals=propozycje, now_fn=self._now,
                                       db_path=queries.db_path_of(self.con),
                                       run_stage_fn=self.run_stage_fn, parent=self)
        # Zapis CZĘŚCIOWY przerwany odmową klingi zostawia okno otwarte, a kolejkę pod spodem
        # nieaktualną — sygnał odświeża ją natychmiast (lustro `_on_repair_changed`).
        dlg.changed.connect(self._on_confirm_path_changed)
        # Od O3 kroku 1 okno pisze też karty do PLIKÓW - ten sam mutex i ta sama bramka biegu
        # pipeline'u, co okno „Napraw nagłówek…" (`_repair_dlg` = otwarte okno piszące do plików).
        dlg.busy_changed.connect(self.writeback_busy)
        self._repair_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._repair_dlg = None
        if dlg.assigned:
            self.status_message.emit(dlg.status.text())
            self.refresh(select_first=True)

    def _on_confirm_path_changed(self):
        """Zapis w oknie potwierdzania → kolejka mówi świeżą prawdę JUŻ przy otwartym oknie
        (częściowy zapis przerwany odmową klingi nie zostawia ekranu z nieaktualnym licznikiem)."""
        self._load_review()
        self._sync_assign_enabled()

    # ------------------------------------------------ akcja osi SPRZĘTU (R1)

    def _on_set_config(self):
        """„Przypisz zestaw…": grupy folder × kamera → okno wskazania TELESKOPU → jedna klinga
        `repo.user_assign_config`.

        Grupy liczymy TU, w chwili otwarcia — nie z licznika kolejki: między odświeżeniem
        a kliknięciem mógł przebiec `Przetwórz wszystko` z workera i lista byłaby o niego starsza
        (lustro `_on_confirm_path`). Klinga i tak pomija klatki, które w międzyczasie dostały
        zestaw, więc podwójne liczenie kosztuje jeden SELECT, a jego brak kosztowałby zapis pod
        nieaktualną listą.

        CEL BIERZEMY Z OKNA, nie z zaznaczenia panelu — i tym ta akcja różni się od „Przypisz
        obiekt…". Jednostką gestu jest FOLDER × KAMERA (D-DR-3), a panel klatek nie ma jak jej
        pokazać: zaznaczenie 5 z 100 klatek folderu dałoby zestaw połowie serii zrobionej tym
        samym sprzętem — stan, którego nikt nie chciał i którego nic w kolejce nie pokazuje.

        DWA WEJŚCIA, JEDNA DROGA ZAPISU (bramka pakietu 3a, zarzut 1): kubełek „bez zestawu"
        NADAJE, a jego druga połowa („zestaw wskazany ręką") ZMIENIA — ta sama klinga, różnica
        w jednym parametrze. Bez drugiego wejścia pierwsza pomyłka ręki była nieodwracalna
        z ekranu: klatka wypada z kubełka, a automat jej nie tknie."""
        tag, _ = self._selected_review()
        zmiana = tag == "config_by_hand"
        grupy = (queries.config_by_hand_groups(self.con) if zmiana
                 else queries.config_review_groups(self.con))
        if not grupy:
            self.status_message.emit(i18n.t("cfg.err_nothing"))
            return
        dlg = AssignConfigDialog(self.con, groups=grupy, change=zmiana, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        telescope_id, telescope_label, frame_ids = dlg.selected
        try:
            with busy.busy(self.status_message.emit,
                           i18n.t("busy.saving_frames", n=len(frame_ids))):
                g = repo.user_assign_config(self.con, frame_ids=frame_ids,
                                            telescope_id=telescope_id, now=self._now(),
                                            overwrite=zmiana)
        except ValueError as e:                # dryf do nieistniejącej klatki/teleskopu
            QMessageBox.warning(self, i18n.t("cfg.title"), str(e))
            return
        from horreum.gui import grid       # lazy - wzorzec `_on_confirm`
        # Suma i rozbicie pominięć mają JEDNEGO właściciela - `ConfigGesture` (R-S2b-15); zdanie
        # składa ten sam dom, co na osi obiektu, z prefiksem kluczy osi sprzętu i bez zer.
        # Zero przypisań nie jest „przypisaniem 0 z N" - zdanie mówi, że nic się nie zmieniło,
        # a powód niesie rozbicie pominięć zaraz za nim.
        msg = (i18n.t_plural("object.config_assigned_report", g.assigned + g.skipped,
                             telescope=telescope_label, assigned=g.assigned) if g.assigned
               else i18n.t("object.config_assigned_none", telescope=telescope_label))
        msg += grid.zdanie_pominiec(g, prefix="grid.sel.config_skip_", odmiana=True)
        if g.assigned:
            # Dobór rodowodu stosów czyta teleskop KANDYDATA (`stacks._in_window`), więc zestaw
            # nadany ręką może przesunąć rodowód gotowego obrazu — ale dopiero, gdy te klatki są
            # czyimś materiałem. Mówimy GDZIE to przeliczyć, zamiast liczyć za usera przy okazji
            # innego gestu (takt należy do Dostawy, jak takt 3 przy naprawie nagłówka).
            msg += i18n.t("object.config_next_step")
        self.status_message.emit(msg)
        self.refresh()

    # ------------------------------------------------ akcja zapisu do PLIKU (P-D)

    def _on_repair(self):
        """„Napraw nagłówek…": klatki bezimienne → dialog (grupy po folderze, propozycja ze ścieżki)
        → karta `OBJECT` w PLIKU. Zapis idzie klingą writebacku, nie do bazy — dlatego po nim
        odświeżamy kolejkę, a oś obiektu wypełnia dopiero takt 3 (`Rozwiąż`, delegowany gospodarzowi
        przez `run_stage_fn`; brak gospodarza = brak taktu 3, okno powie to wprost).

        Wejście bierzemy z ZAZNACZONEGO kubełka (D-0802-1): lighty archiwum i gotowe stosy mają tę
        samą drogę naprawy, ale to DWIE rozłączne populacje i dwa liczniki — otwarcie okna zawsze
        na lightach kłamałoby licznikiem, na którym user kliknął.

        OD R-S3-1 KUBEŁKI SĄ CZTERY, bo każda z tych populacji ma połówkę cofniętą ręką — i to jest
        DRUGA oś tego samego wyboru, nie kosmetyka wiersza. Bez członu `cleared` kliknięcie
        w „cofnięte ręką" otwierało okno z populacją NIETKNIĘTĄ: listą rozłączną z tą, którą user
        widział pod spodem, i to zapisem do PLIKÓW. Wybór po parze (populacja, źródło) trzyma
        kontrakt „okno pokazuje dokładnie to, co licznik, na którym kliknąłeś"."""
        tag, _ = self._selected_review()
        cofniete = tag in _CLEARED_TAGS
        czytaj = (queries.nameless_stack_frames
                  if tag in ("nameless_stacks", "nameless_stacks_cleared")
                  else queries.nameless_frames)
        rows = czytaj(self.con, cleared=cofniete)
        if not rows:
            self.status_message.emit(i18n.t("repair.nothing"))
            return
        dlg = RepairHeaderDialog(self.con, rows=rows, db_path=queries.db_path_of(self.con),
                                 now_fn=self._now, run_stage_fn=self.run_stage_fn, parent=self)
        dlg.changed.connect(self._on_repair_changed)
        dlg.busy_changed.connect(self.writeback_busy)   # mutex: gospodarz wygasi drugą powierzchnię
        self._repair_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._repair_dlg = None

    def _on_repair_changed(self):
        """Zapis/cofnięcie w oknie naprawy → kolejka mówi świeżą prawdę JUŻ po takcie 2 (dialog żyje
        w tym samym widoku). Oś obiektu i badge Porządków ruszą się dopiero po takcie 3 — to nie
        rozjazd, tylko dwa różne fakty: karta jest w pliku, obiektu jeszcze nie ma."""
        self._load_review()
        self._sync_assign_enabled()

    def _fill_frames(self, rows, *, present_col):
        """Wypełnij tabelę klatek. `present_col` — czy źródło niesie kolumnę `present` (biblioteka tak,
        review nie). `present=0` pokazujemy jako „nie" (R#7 — klatka WIDOCZNA mimo zniknięcia pliku).

        Źródło BEZ tej kolumny CHOWA ją w całości (wiz #10): pusta komórka pod nagłówkiem „Obecny"
        czyta się jak „nie ma", a w widoku obiektu obok ta sama kolumna mówi „tak". Nagłówek bez
        treści jest obietnicą bez pokrycia — znika razem z nią."""
        self.frames.setColumnHidden(FRAME_COL_PRESENT, not present_col)
        _przeladuj_wiersze(self.frames, len(rows))
        for r, row in enumerate(rows):
            keys = row.keys()
            # `frame_id` w roli danych PIERWSZEJ kolumny: od S4 panel jest CELEM akcji zapisu
            # („Przypisz obiekt…" pisze zaznaczenie, nie całą listę), więc wiersz musi umieć
            # powiedzieć, którą klatkę pokazuje. Źródło bez tej kolumny (biblioteka) zostawia None.
            self._set_frame_cell(r, FRAME_COL_SHA, (row["sha1_data"] or "")[:12],
                                 data=row["frame_id"] if "frame_id" in keys else None)
            self._set_frame_cell(r, FRAME_COL_TEL, queries.telescope_label(row))
            self._set_frame_cell(r, FRAME_COL_CAM, row["camera_model"] or "")
            self._set_frame_cell(r, FRAME_COL_FILTER, row["filter_canon"] if "filter_canon" in keys else "")
            self._set_frame_cell(r, FRAME_COL_DATE, _fmt_obs_date(row["date_obs"]),
                                 tooltip=row["date_obs"] or None)
            if present_col and "present" in keys:
                self._set_frame_cell(r, FRAME_COL_PRESENT,
                                     i18n.t("common.yes") if row["present"] else i18n.t("common.no"))
            else:
                self._set_frame_cell(r, FRAME_COL_PRESENT, "")
            # Ścieżka: pokaż NAZWĘ PLIKU (elizja od prawej gubiłaby ją z pełnej ścieżki „R:\...");
            # pełna ścieżka w tooltipie (hover). Klatka bez lokalizacji (zniknięta) → jawny znacznik.
            #
            # OGON ŚCIEŻKI, NIE SAMA NAZWA — bo nazwa pliku nie jest w tych kubełkach rozróżnikiem
            # (firsthand 0808, DWA zgłoszenia): `masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_….xisf`
            # u stosów i `astro_dsc4198.dng` u RAW-ów nie mówią nic, tożsamość niesie KATALOG.
            # ZMIERZONE na 703 RAW-ach: sam rodzic ma 3 różne wartości, dwa ostatnie katalogi — 34,
            # czyli dokładnie tyle, ile nazw czyta z nich świadek ścieżki. Reguła jest JEDNA dla
            # wszystkich kubełków: pierwsza wersja ciął ją po `master_light` z uzasadnieniem, które
            # pomiar obalił. Tooltip z pełną ścieżką zostaje, ale sam NIE WYSTARCZA: pokazuje jeden
            # wiersz naraz, a wybór spośród bliźniaków jest PORÓWNANIEM.
            path = row["path"] or ""
            self._set_frame_cell(r, FRAME_COL_PATH,
                                 queries.path_tail(path) if path else i18n.t("object.no_location"),
                                 tooltip=path or None)

    def _set_frame_cell(self, r, c, text, *, tooltip=None, data=None):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if tooltip:
            item.setToolTip(tooltip)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self.frames.setItem(r, c, item)

    def _select_all_frames(self):
        """Drążenie kubełka Z AKCJĄ zaznacza CAŁĄ grupę: domyślny cel zostaje ten sam co przed S4
        (jeden gest na cały kubełek), a zaznaczenie na ekranie od początku mówi prawdę o zakresie
        zapisu. Kubełki bez akcji zapisu tego nie robią — podświetlenie obiecywałoby czynność."""
        self.frames.selectAll()

    def _selected_frame_ids(self):
        """Klatki ZAZNACZONE w panelu — cel akcji zapisu osi (S4, adjudykacja recenzji diffu).

        Fallback na „wszystko widoczne" jest tu ZAKAZANY i to nie jest ostrożność na wyrost: kubełek
        RAW nie jest grupą semantyczną, tylko resztą („czego nie umieliśmy nazwać") — na żywej bazie
        763 klatki z kilkudziesięciu folderów. Zapis całej listy jednym kliknięciem nadawałby im
        JEDEN kanon ze źródłem `user`, które pomija całą drabinę przy każdym kolejnym `Rozwiąż`,
        jest sticky dla szczebla ścieżki i którego dzisiejsza aplikacja nie umie cofnąć.

        Cały kubełek pozostaje jednym gestem: drążenie zaznacza wszystko (`_on_review_selected`),
        więc domyślny cel jest ten sam co przed zmianą — dochodzi wyłącznie możliwość PRZYCIĘCIA
        grupy i to, że zaznaczenie na ekranie mówi prawdę o tym, co pójdzie do zapisu."""
        sm = self.frames.selectionModel()
        rows = sm.selectedRows() if sm else []
        ids = [self.frames.item(idx.row(), FRAME_COL_SHA) for idx in rows]
        return [i.data(Qt.UserRole) for i in ids if i is not None and i.data(Qt.UserRole) is not None]

    def set_busy(self, busy):
        """Pipeline w biegu → wygaszenie akcji zapisu („Przypisz obiekt…" #8/P4, „Napraw nagłówek…"
        P-D) - szczery disabled. Read-modele odświeża gospodarz DOPIERO po końcu przebiegu
        (`running_changed(False)`; WAL → zapisy workera widoczne), więc SELECT w trakcie zapisu tu nie zachodzi.

        OTWARTE okno naprawy jest MODALNE, więc poza zasięgiem tej metody (gasi widżety WIDOKU) —
        fakt przekazujemy mu wprost, inaczej „Zapisz karty" zostałby klikalny w trakcie biegu."""
        self._busy = busy
        self._sync_assign_enabled()
        if self._repair_dlg is not None:
            self._repair_dlg.set_pipeline_busy(busy)

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (grid) pisze do plików — „Napraw nagłówek…" gaśnie
        (mutex, D-PD-3: dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`)."""
        self._foreign_wb = busy
        self._sync_assign_enabled()


# ============================================================ oś OBSERWATORIUM (PLAN_os_obserwatorium §3)

# Kolumny listy stanowisk. Tożsamość osi jest GEOMETRYCZNA — brak stringa-nagłówka jak `telescop_canon`;
# to szerokość/długość identyfikują stanowisko dla oka usera (rozpoznaje swoje miejsca po współrzędnych). Nazwa
# to etykieta usera (edytowalna in-line → `label_observatory`). Bez kolumny Status (zawsze 'proposed'
# w v1 — brak approve) i bez Wysokości (atrybut D3, nie tożsamość — zejście na drugi plan).
OBS_COL_ID, OBS_COL_NAME, OBS_COL_LAT, OBS_COL_LON, OBS_COL_FRAMES = range(5)
OBS_HEADERS = ["col.id", "obs.col.name", "obs.col.lat", "obs.col.lon", "col.frames"]


def _fmt_coord(v):
    """Współrzędna do komórki/etykiety: STAŁA precyzja 4 miejsc (~11 m) — słupek lat/lon wyrównany
    (wizytator #2: `%g` dawał zmienną liczbę miejsc, np. `7.5` vs `128.4082` → poszarpany słupek;
    przy progu 4 km 11 m nie myli stanowisk). None → '' (defensywnie — lat/lon są NOT NULL)."""
    return "" if v is None else f"{v:.4f}"


def _obs_row_label(row):
    """Etykieta stanowiska do listy combo/członków: nazwa usera, a gdy brak (nienazwane — realny
    przypadek: cała oś świeżo `proposed`) — współrzędne z seeda, by pozycja NIE milczała."""
    return row["name"] or f'{_fmt_coord(row["lat"])}, {_fmt_coord(row["lon"])}'


class ObservatoryAxisView(QWidget):
    """Osadzalny widok osi OBSERWATORIUM (lista→scal→nazwij) — mirror `TelescopeAxisView` z JEDNĄ
    różnicą domenową: BEZ „Zatwierdź" (v1 nie ma approve; port osi = merge+unmerge+label). Lista
    kanonicznych stanowisk (lewa) + szczegół zaznaczonego (prawa: scalone pod nim, audyt). Akcje usera
    (`label`/`merge`/`unmerge`) idą przez `repo` (jedna klinga). Nazwa edytowalna in-line; tożsamość
    (szer./dług.) tylko do odczytu. Ten widok NIE wykonuje `con.execute` — meta-tripwir AST pilnuje.

    `con` = otwarte połączenie RW (NIE własność widoku). `now_fn` = źródło czasu (ISO-8601)."""

    status_message = Signal(str)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._loading = False                # tłumi itemChanged podczas programowego wypełniania
        self._source_mergeable = False       # czy zaznaczony wiersz może być źródłem scalenia
        self._obs_coords = {}                # oid → (lat, lon) z ostatniego refresh (źródło GPS dla OSM)
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)

        # --- lewa: tabela aktywnych stanowisk + pasek akcji ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(i18n.t("axis.obs.active")))
        self.table = QTableWidget(0, len(OBS_HEADERS))
        self.table.setHorizontalHeaderLabels(_headers(OBS_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Priorytet szerokości: Nazwa (etykieta usera) rośnie, reszta do treści (wizytator #3/#4 —
        # `stretchLastSection` rozpychał Klatki i ucinał je na wąsko, a Nazwa była ciasna).
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(OBS_COL_NAME, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self._edit_triggers = self.table.editTriggers()   # przywracane po set_busy(False) (wizytator T3)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.table)
        # Nota pustego stanu W WIDOKU (wizytator #1): `status_message` bywa nadpisany flashem gospodarza
        # (MainWindow), więc pusty stan musi być odkrywalny w obszarze tabeli — wzorzec 1:1 z
        # `ObjectAxisView.lib_empty`. Chowana, gdy są stanowiska.
        self.obs_empty = QLabel(i18n.t("axis.obs.empty_note"))
        self.obs_empty.setAlignment(Qt.AlignCenter)
        self.obs_empty.setWordWrap(True)
        self.obs_empty.setVisible(False)
        lv.addWidget(self.obs_empty)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(QLabel(i18n.t("axis.obs.merge_into")))
        self.combo_target = QComboBox()
        self.combo_target.currentIndexChanged.connect(self._sync_merge_enabled)
        actions.addWidget(self.combo_target)
        self.btn_merge = QPushButton(i18n.t("action.merge"))
        self.btn_merge.clicked.connect(self._on_merge)
        actions.addWidget(self.btn_merge)
        lv.addLayout(actions)

        # STANOWISKO Z RĘKI (0027) - wejście TU, w widoku osi, a nie z Porządków ani z menu klatki:
        # gest wybiera albo tworzy STANOWISKO, a lista stanowisk i mapa stoją obok, więc user
        # widzi, w co trafia. Grupy klatek okno liczy samo (folder), bez zaznaczenia w Zbiorach.
        # Przyciski aktywne zawsze (poza biegiem etapu) - pusty kubełek mówi komunikatem.
        hand = QHBoxLayout()
        self.btn_hand_assign = QPushButton(i18n.t("obshand.btn_assign"))
        self.btn_hand_change = QPushButton(i18n.t("obshand.btn_change"))
        self.btn_hand_clear = QPushButton(i18n.t("obshand.btn_clear"))
        for przycisk, tryb in ((self.btn_hand_assign, "assign"), (self.btn_hand_change, "change"),
                               (self.btn_hand_clear, "clear")):
            przycisk.clicked.connect(lambda _c=False, t=tryb: self._on_hand_site(t))
            hand.addWidget(przycisk)
        hand.addStretch(1)
        lv.addLayout(hand)

        # --- prawa: szczegół zaznaczonego ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel(i18n.t("axis.obs.merged_under")))
        self.members = QListWidget()
        self.members.itemSelectionChanged.connect(self._sync_unmerge_enabled)
        rv.addWidget(self.members)
        self.btn_unmerge = QPushButton(i18n.t("action.unmerge"))
        self.btn_unmerge.clicked.connect(self._on_unmerge)
        rv.addWidget(self.btn_unmerge)
        rv.addWidget(QLabel(i18n.t("axis.history")))
        self.events = QListWidget()
        rv.addWidget(self.events)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # --- mapa stanowisk (F8) na DOLE, pełnej szerokości: scatter geo chce szerokości, user
        # reguluje pionowy podział; przycisk OSM na zaznaczeniu (akcja tabeli, nie widżetu mapy). ---
        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(splitter)
        self.map_box = QWidget()                      # ref — ukrywany przy 0 stanowisk (wiz F8 #6)
        mv = QVBoxLayout(self.map_box)
        mv.setContentsMargins(0, 0, 0, 0)
        obar = QHBoxLayout()
        self.btn_osm = QPushButton(i18n.t("axis.obs.open_osm"))
        self.btn_osm.setEnabled(False)                # szczery disabled — bez zaznaczenia brak celu
        self.btn_osm.clicked.connect(self._on_open_osm)
        obar.addWidget(self.btn_osm)
        obar.addStretch(1)
        mv.addLayout(obar)
        self.map_view = SitesMapView()
        self.map_view.siteClicked.connect(self._on_map_click)   # klik w punkt → selekcja wiersza (#10)
        mv.addWidget(self.map_view, 1)
        vsplit.addWidget(self.map_box)
        # setStretchFactor sam nie wystarcza — sizeHint górnych tabel zjada przyrost i mapa siada na
        # minimum 160 px (wiz F8 #1); setSizes wymusza sensowny DOMYŚLNY podział (~55/45), user reguluje.
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([460, 380])
        outer.addWidget(vsplit, 1)

    # ---------------------------------------------------------------- odczyt → widok

    def refresh(self):
        """Przeładuj listę z read-modelu (źródło prawdy = baza; brak cache). Zachowuje zaznaczenie po
        `observatory_id` (po merge wiersze się przesuwają). Karmi mapę tymi SAMYMI wierszami (SPOT)
        i zapamiętuje współrzędne dla linku OSM (F8 F8 — read-model nie jest cache'owany inaczej)."""
        prev = self._selected_observatory_id()
        self._loading = True
        try:
            rows = queries.active_observatories(self.con)
            self._obs_coords = {row["id"]: (row["lat"], row["lon"]) for row in rows}
            _przeladuj_wiersze(self.table, len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_cell(r, OBS_COL_ID, str(row["id"]), data=row["id"])
                self._set_cell(r, OBS_COL_NAME, row["name"] or "", editable=True)
                self._set_cell(r, OBS_COL_LAT, _fmt_coord(row["lat"]), align=_NUM_ALIGN)
                self._set_cell(r, OBS_COL_LON, _fmt_coord(row["lon"]), align=_NUM_ALIGN)
                self._set_cell(r, OBS_COL_FRAMES, str(row["frame_count"]), align=_NUM_ALIGN)
                if row["id"] == prev:
                    target_row = r
        finally:
            self._loading = False
        empty = self.table.rowCount() == 0
        self.obs_empty.setVisible(empty)              # nota odkrywalna w widoku (wizytator #1)
        self.table.setVisible(not empty)
        self.map_box.setVisible(not empty)            # 0 stanowisk → bez martwego pasa mapy (wiz F8 #6)
        self.map_view.set_sites(rows)                 # mapa dostaje TE SAME wiersze co tabela (F8)
        if target_row >= 0:
            self.table.selectRow(target_row)
        elif not empty:
            self.table.selectRow(0)
        else:
            self.status_message.emit(i18n.t("axis.obs.empty_status"))
        self._on_selection_changed()

    def _set_cell(self, r, c, text, *, editable=False, data=None, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # tylko nazwa jest edytowalna in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if align is not None:                 # liczby prawo-wyrównane (skanowalność magnitud, wizytator #2)
            item.setTextAlignment(align)
        if data is not None:                  # observatory_id na kolumnie ID (kotwica wiersza)
            item.setData(Qt.UserRole, data)
        self.table.setItem(r, c, item)

    def _on_map_click(self, oid):
        """Klik w punkt mapy (hit-test) → zaznacz odpowiedni wiersz tabeli (mapa→tabela; #10).
        Selekcja tabeli kaskaduje przez `itemSelectionChanged` → `_on_selection_changed`
        (wyróżnienie mapy + stan OSM) — mapa NIE orkiestruje, tabela zostaje właścicielem selekcji
        (SPOT). Nieznany oid (wiersz zniknął między refreshami) ignorowany."""
        self._select_observatory(oid)

    def _select_observatory(self, oid):
        """Zaznacz wiersz stanowiska `oid` (kanon). Kaskada jak przy kliku w mapę: tabela →
        `_on_selection_changed` → wyróżnienie mapy i OSM. Nieznany oid - bez skutku."""
        for r in range(self.table.rowCount()):
            item = self.table.item(r, OBS_COL_ID)
            if item and item.data(Qt.UserRole) == oid:
                self.table.selectRow(r)
                return

    def _selected_observatory_id(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), OBS_COL_ID)
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self):
        """Odśwież panel szczegółu (członkowie + audyt) i stany przycisków dla zaznaczonego wiersza.
        Stany SZCZERE: merge bez realnego celu albo źródła z członkami jest wyłączony (UI nie kłamie)."""
        oid = self._selected_observatory_id()

        self.members.clear()
        members = queries.merged_under_observatory(self.con, oid) if oid is not None else []
        for m in members:
            it = QListWidgetItem(f'#{m["id"]}  {_obs_row_label(m)}')
            it.setData(Qt.UserRole, m["id"])
            self.members.addItem(it)

        self.events.clear()
        if oid is not None:
            for e in queries.observatory_axis_events(self.con, observatory_id=oid):
                self.events.addItem(f'{_fmt_event_ts(e["ts"])}  ·  {e["verb"]}  ·  {e["actor"]}')

        # Cel scalenia z PLACEHOLDEREM (currentData=None): merge to świadoma deklaracja „to samo
        # stanowisko" (np. dom↔praca, gdy user uzna). `blockSignals` — przebudowa nie sypie sygnałem.
        self.combo_target.blockSignals(True)
        self.combo_target.clear()
        self.combo_target.addItem(i18n.t("axis.pick_target"), None)
        for o in queries.active_observatories(self.con):
            if o["id"] != oid:                # cel ≠ źródło → self-merge strukturalnie niemożliwy
                self.combo_target.addItem(f'#{o["id"]}  {_obs_row_label(o)}', o["id"])
        self.combo_target.setCurrentIndex(0)
        self.combo_target.blockSignals(False)

        # źródło mergowalne tylko gdy kanoniczne BEZ członków (inwariant głębokość ≤ 1) i JEST realny cel.
        self._source_mergeable = (oid is not None and not members and self.combo_target.count() > 1)
        self._sync_merge_enabled()
        self._sync_unmerge_enabled()

        # mapa i OSM sprzężone z zaznaczeniem tabeli (F8): mapa wyróżnia punkt, OSM celuje w jego GPS.
        self.map_view.set_selected(oid)
        self.btn_osm.setEnabled(oid is not None)

    def _sync_merge_enabled(self):
        """„Scal" aktywny dopiero gdy źródło jest mergowalne ORAZ wskazano REALNY cel (nie placeholder)."""
        self.btn_merge.setEnabled(self._source_mergeable and self.combo_target.currentData() is not None)

    def _sync_unmerge_enabled(self):
        self.btn_unmerge.setEnabled(bool(self.members.selectedItems()))

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU osi (szczery disabled — worker pisze do bazy).
        Po etapie gospodarz woła `set_busy(False)` → `_on_selection_changed` przywraca szczere stany."""
        for przycisk in (self.btn_hand_assign, self.btn_hand_change, self.btn_hand_clear):
            przycisk.setEnabled(not busy)             # gest ręki pisze do bazy - jak scalenie
        if busy:
            self.btn_merge.setEnabled(False)
            self.btn_unmerge.setEnabled(False)
            self.combo_target.setEnabled(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # zamknij in-line edyt nazwy (T3)
        else:
            self.table.setEditTriggers(self._edit_triggers)
            self.combo_target.setEnabled(True)
            self._on_selection_changed()

    # ---------------------------------------------------------------- akcje → repo (jedna klinga)

    def _flash(self, msg):
        self.status_message.emit(msg)

    def _on_open_osm(self):
        """Otwórz zaznaczone stanowisko w OpenStreetMap (przeglądarka usera — zoom/satelita/okolica poza
        apką, zero ciężaru w apce). Przycisk wyłączony bez zaznaczenia; handler i tak sprawdza (guard
        drugą linią). Źródło GPS = `_obs_coords` z ostatniego refresh (F8 F8)."""
        oid = self._selected_observatory_id()
        coord = self._obs_coords.get(oid) if oid is not None else None
        if coord is None:
            self._flash(i18n.t("axis.obs.select_for_map"))
            return
        QDesktopServices.openUrl(QUrl(mapproj.osm_url(coord[0], coord[1])))

    def _on_item_changed(self, item):
        """Edycja in-line nazwy → `repo.label_observatory`. Pusta nazwa → `ValueError` (kasowanie poza
        v1) złapany i pokazany; widok wraca do prawdy bazy (refresh)."""
        if self._loading or item.column() != OBS_COL_NAME:
            return
        oid = self.table.item(item.row(), OBS_COL_ID).data(Qt.UserRole)
        try:
            changed = repo.label_observatory(
                self.con, observatory_id=oid, name=item.text(), now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.obs.name_rejected", e=e))
            self.refresh()
            return
        self._flash(i18n.t("axis.obs.name_saved") if changed else i18n.t("axis.obs.name_unchanged"))
        self.refresh()

    def _on_merge(self):
        src = self._selected_observatory_id()
        tgt = self.combo_target.currentData()
        if src is None or tgt is None:        # brak źródła albo placeholder zamiast celu
            return
        try:
            changed = repo.merge_observatory(
                self.con, source_id=src, target_id=tgt, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.merge_failed", e=e))
            return
        self._flash(i18n.t("axis.merged", src=src, tgt=tgt) if changed
                    else i18n.t("axis.obs.already_merged"))
        self.refresh()

    def _on_unmerge(self):
        sel = self.members.selectedItems()
        if not sel:
            return
        mid = sel[0].data(Qt.UserRole)
        try:
            changed = repo.unmerge_observatory(self.con, observatory_id=mid, now=self._now())
        except ValueError as e:
            self._flash(i18n.t("axis.unmerge_failed", e=e))
            return
        self._flash(i18n.t("axis.unmerged", mid=mid) if changed
                    else i18n.t("axis.obs.already_canonical"))
        self.refresh()

    def _on_hand_site(self, mode):
        """„Wskaż / Zmień / Cofnij stanowisko…" → okno grup folderów → jedna klinga (0027).

        Grupy liczymy TU, w chwili otwarcia (lustro `_on_set_config`): między odświeżeniem
        a kliknięciem mógł przebiec `Rozwiąż`. Klinga i tak liczy odmowy przy zapisie (zajęta,
        bez zmiany), więc lista nieaktualna kosztuje komunikat, a nie zły zapis.

        RECEPTA ODWROTU W KOMUNIKACIE: po nadaniu zdanie mówi, gdzie leży cofnięcie - ten widok,
        „Cofnij wskazanie…" - bo klatka po geście wypada z kubełka „bez stanowiska" i bez tej
        podpowiedzi user nie wie, którędy wrócić."""
        grupy = (queries.observatory_review_groups(self.con) if mode == "assign"
                 else queries.observatory_by_hand_groups(self.con))
        if not grupy:
            self._flash(i18n.t("obshand.nothing" if mode == "assign" else "obshand.nothing_hand"))
            return
        dlg = AssignObservatoryDialog(self.con, groups=grupy, mode=mode, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        wybor = dlg.selected
        try:
            with busy.busy(self._flash, i18n.t("busy.saving_frames", n=len(wybor["frame_ids"]))):
                if mode == "clear":
                    g = repo.clear_observatory_assignment(
                        self.con, frame_ids=wybor["frame_ids"], now=self._now())
                else:
                    g = repo.user_assign_observatory(
                        self.con, frame_ids=wybor["frame_ids"], now=self._now(),
                        observatory_id=wybor["observatory_id"], lat=wybor["lat"],
                        lon=wybor["lon"], name=wybor["name"], elev=wybor["elev"],
                        overwrite=mode == "change")
        except ValueError as e:                # dryf do nieistniejącej klatki/stanowiska
            QMessageBox.warning(self, i18n.t("obshand.title"), str(e))
            return
        self.refresh()
        if mode != "clear" and g.observatory_id is not None:   # cel gestu zaznaczony: tabela,
            cid, _ = queries.observatory_site_label(self.con, g.observatory_id)   # szczegół i mapa
            self._select_observatory(cid)                      # pokazują, gdzie trafiły klatki
        self._flash(zdanie_stanowiska(self.con, mode, g))


def _etykieta_stanowiska(con, observatory_id, *, z_numerem=False):
    """Stanowisko w zdaniu gestu: nazwa KANONU albo `#id`; `z_numerem` = `#id nazwa` (zdanie o pustym
    stanowisku musi wskazać wiersz na liście osi, a nazwa bywa pusta)."""
    cid, nazwa = queries.observatory_site_label(con, observatory_id)
    if z_numerem:
        return i18n.t("obshand.site_label", id=cid, name=nazwa or "").strip()
    return nazwa or f"#{cid}"


def zdanie_stanowiska(con, mode, g):
    """Zdanie po geście stanowiska z ręki - wzorzec `grid.zdanie_pominiec`: odmiana przez liczbę,
    człony WYŁĄCZNIE przy liczbie > 0, kropka na końcu całego zdania.

    CEL NAZYWA FAKTYCZNE STANOWISKO, nie wpisane współrzędne: punkt w promieniu `THRESH_KM` trafia
    w istniejące stanowisko, więc „Stanowisko -30.25, 170.70" mówiłoby o miejscu, którego na liście
    nie ma. Po cofnięciu stanowisko z ręki ZOSTAJE (planer go potrzebuje) - zdanie mówi, że zostało
    puste, żeby wiersz z zerem klatek nie wyglądał na błąd."""
    if mode == "clear":
        msg = i18n.t_plural("obshand.cleared_report", g.cleared + g.not_hand + g.nothing,
                            cleared=g.cleared)
        if g.not_hand:
            msg += i18n.t_plural("obshand.clear_not_hand", g.not_hand)
        if g.nothing:
            msg += i18n.t_plural("obshand.clear_nothing", g.nothing)
        if g.cleared_gps:
            msg += i18n.t_plural("obshand.clear_gps", g.cleared_gps)
        if g.cleared - g.cleared_gps:
            msg += i18n.t_plural("obshand.clear_no_site", g.cleared - g.cleared_gps)
        for oid in g.cleared_from:
            if not queries.observatory_live_frames(con, oid):
                msg += i18n.t("obshand.site_empty",
                              site=_etykieta_stanowiska(con, oid, z_numerem=True))
        return msg + "."
    msg = i18n.t_plural("obshand.assigned_report", g.assigned + g.occupied + g.unchanged,
                        site=_etykieta_stanowiska(con, g.observatory_id), assigned=g.assigned)
    if g.created:
        msg += i18n.t("obshand.created")
    if g.occupied:
        msg += i18n.t_plural("obshand.skip_occupied", g.occupied)
    if g.unchanged:
        msg += i18n.t_plural("obshand.skip_unchanged", g.unchanged)
    if g.name_kept:
        msg += i18n.t("obshand.name_kept", name=g.name_kept)
    if g.elev_set is not None:
        msg += i18n.t("obshand.elev_set", elev=f"{g.elev_set:g}")
    if g.elev_kept is not None:
        msg += i18n.t("obshand.elev_kept", elev=f"{g.elev_kept:g}")
    if g.assigned:
        msg += i18n.t("obshand.undo_hint")
    return msg + "."


class TelescopeAxisWindow(QMainWindow):
    """Powłoka-okno osi teleskopu (zgodność wstecz — etap 1). Treść = osadzony `TelescopeAxisView`;
    okno dokłada tylko tytuł i pasek statusu (podpięty pod sygnał widoku). NIE jest właścicielem
    `con` (zamyka je wołający — `main`/fixture). Sygnatura `__init__` niezmieniona z etapu 1, by
    `test_gui_app.py` (import `COL_ID/COL_LABEL/TelescopeAxisWindow`, wywołanie `now_fn=`) był zielony.

    Dostęp do widżetów/handlerów (`table`, `btn_approve`, `_on_merge`, `refresh`, …) jest delegowany
    do osadzonego widoku przez `__getattr__` — testy etapu 1 sterują oknem jak dawniej, bez zmian."""

    def __init__(self, con, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("window.telescope_axis"))
        self.resize(960, 560)
        self.view = TelescopeAxisView(con, now_fn=now_fn)
        self.view.status_message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.setCentralWidget(self.view)
        self.statusBar()

    def __getattr__(self, name):
        # Delegacja do osadzonego widoku TYLKO dla atrybutów nieznanych oknu (QMainWindow ma własne
        # `close`/`show`/…). `__dict__` zamiast `getattr(self, ...)` — bez ryzyka rekurencji, gdy
        # `view` jeszcze nie istnieje (w trakcie __init__ przed przypisaniem).
        view = self.__dict__.get("view")
        if view is not None:
            return getattr(view, name)
        raise AttributeError(name)


# Wiersze sidebara: Dom i Znajdź na górze, pod nieklikalnym nagłówkiem „Więcej" dawne cztery
# miejsca (F5, PLAN_ux_redesign §6). NAV_PLANER świadomie BEZ badge'a (D-0731-6): „ile do zrobienia"
# zależy u planera od suwaka `min_hours`, więc liczba w nawiasie kłamałaby przy każdej zmianie progu
# (badge Porządków liczy roboty, które są faktem bazy, nie funkcją parametru).
NAV_DOM, NAV_ZNAJDZ, NAV_WIECEJ, NAV_DOSTAWA, NAV_ZBIORY, NAV_PORZADKI, NAV_PLANER = range(7)
# Strony stosu. WIERSZ NIE JEST JUŻ STRONĄ 1:1: Znajdź i Zbiory klasyczne to JEDNA strona (ten sam
# `FramesView` w kontenerze `ZnajdzView`) w dwóch prezentacjach - drugi grid rozjechałby stan zbioru,
# staging i mutex (JEDEN-STAN-EKRANU). Raporty widoków wiążą się ze STRONĄ, nie z wierszem: przejście
# Znajdź → Zbiory klasyczne nie zmienia tego, co widać pod paskiem.
STRONA_DOM, STRONA_ZBIORY, STRONA_DOSTAWA, STRONA_PORZADKI, STRONA_PLANER = range(5)
# JEDYNE miejsce mapowania wiersz → (strona, prezentacja strony zbiorów). Nagłówka „Więcej" tu nie
# ma: nie jest celem, a `_on_nav_changed` ignoruje wiersz bez trasy. Prezentacje to wartości
# sygnału `ZnajdzView.prezentacja_zmieniona` (stałe z kontenera strony), więc odwrotna mapa
# (przełączenie z wnętrza strony przesuwa wiersz) bierze się z tej samej tabeli.
_TRASY = {
    NAV_DOM: (STRONA_DOM, None),
    NAV_ZNAJDZ: (STRONA_ZBIORY, PREZENTACJA_ZNAJDZ),
    NAV_DOSTAWA: (STRONA_DOSTAWA, None),
    NAV_ZBIORY: (STRONA_ZBIORY, PREZENTACJA_KLASYCZNA),
    NAV_PORZADKI: (STRONA_PORZADKI, None),
    NAV_PLANER: (STRONA_PLANER, None),
}
_WIERSZ_PREZENTACJI = {prez: row for row, (_strona, prez) in _TRASY.items() if prez is not None}
# Postój na wierszu Dom przed jego odczytem przy przeglądaniu sidebara strzałkami - dłuższy niż
# odstęp autopowtórzenia klawisza, krótszy niż chwila, po której człowiek czyta ekran.
_DOM_POSTOJ_MS = 150


class MainWindow(QMainWindow):
    """Okno aplikacji (PLAN_gui_pipeline §2 + UX-redesign F5): menu Plik (Otwórz/Nowa baza) +
    sidebar (Dom · Znajdź · „Więcej": Dostawa / Zbiory klasyczne / Porządki / Planer - `QListWidget`
    prowadzi `QStackedWidget` przez `_TRASY`; osie teleskop/obserwatorium/obiekt to PODSTRONY
    Porządków w `TasksView`). Start z otwartą bazą = Dom; wejścia do strony zbiorów z Domu i z menu
    to wyłącznie `show_find`/`show_classic`.
    WŁAŚCICIEL połączenia `con` — otwiera je z `db_path`, zamyka poprzednie przy przełączeniu bazy
    i bieżące przy zamknięciu okna (top-level apki, w odróżnieniu od osadzonych widoków).

    Trzyma `db_path` (nie tylko `con`): worker pipeline'u potrzebuje ŚCIEŻKI, by otworzyć WŁASNE
    połączenie w swoim wątku (sqlite `check_same_thread` — `con` głównego wątku nie przechodzi).
    Po etapie pipeline'u odświeża read-model osi (WAL → zapisy workera widoczne) i przywraca
    szczere stany akcji osi (`set_busy`)."""

    # Pokrycie pól Zbiorów liczone w wątku tła (`FramesView(pola_poza_watkiem=…)`). Atrybut KLASY,
    # bo widoki montuje sam `__init__` okna - seam testowy musi stać, zanim okno powstanie.
    # Ten sam przełącznik oddaje w tło skład zbioru gridu (`ZbiorWorker`, AR-27) - oba wątki tła
    # Zbiorów chodzą razem, więc test, który chce widoku przewidywalnego, wyłącza oba jednym ruchem.
    _pola_poza_watkiem = True

    def __init__(self, db_path=None, now_fn=_utc_now_iso, on_db_changed=None, parent=None):
        super().__init__(parent)
        self.con = None
        self.db_path = None
        self._now = now_fn
        # Wstrzykiwane wywołanie zwrotne „zmieniono bazę" (wzór jak `now_fn`): `main` podpina tu zapis
        # ostatniej ścieżki do trwałych ustawień; testy go nie podają → brak skutków ubocznych.
        self._on_db_changed = on_db_changed
        # Straż ponownego wejścia w odświeżenie widoków po przebiegu Dostawy (patrz
        # `_odswiez_widoki_po_przebiegu`): druga prośba w trakcie nie zagnieżdża się, tylko zamawia
        # jeden obrót więcej po skończeniu bieżącego.
        self._odswiezam_widoki = False
        self._odswiez_jeszcze_raz = False
        # Dom istnieje tylko przy zamontowanej bazie; `None` po demontażu, bo blokada recepty
        # (`_odblokuj_recepte`, zegar) może przyjść już po nim.
        self.home_view = None
        # Ostatnia recepta ze strumienia Zbiorów - Dom pokazuje ją i wykonuje niezależnie od paska,
        # z którego gasi ją każdy cudzy raport (FH-2e); życie wyznacza wyłącznie strumień.
        self._recepta_strumienia = None
        # Numer wersji W TYTULE, bo wydanie jedzie do użytkownika jako JEDEN plik `horreum-gui.exe`
        # (onefile — CLI `horreum --version` nie powstaje) i okno jest wtedy jedyną powierzchnią,
        # na której da się sprawdzić, co się ma. Numer czytany, nie pisany (`horreum/__init__.py`).
        from .. import __version__
        self.setWindowTitle(f"Horreum {__version__}")
        self.resize(1000, 620)
        self._build_menu()
        self._build_central()
        if db_path is not None:
            self._open_path(db_path)
        else:
            self._sync_db_state()

    # ---------------------------------------------------------------- budowa szkieletu

    def _build_menu(self):
        m = self.menuBar().addMenu(i18n.t("menu.file"))
        m.addAction(i18n.t("menu.open_db"), self._on_open_db)
        m.addAction(i18n.t("menu.new_db"), self._on_new_db)
        self._build_view_menu()

    def _build_view_menu(self):
        """Menu &Widok: motyw (ciemny/jasny) + język (PL/EN). Oba przez wykluczający QActionGroup;
        zaznaczenie ODBIJA bieżący stan z QSettings bez klikania (UI-NIE-KŁAMIE, F6 recenzja #6)."""
        view = self.menuBar().addMenu(i18n.t("menu.view"))
        self._build_theme_menu(view)
        view.addSeparator()
        self._build_lang_menu(view)

    def _build_theme_menu(self, view):
        """Sekcja motywu w &Widok — wykluczająca przez QActionGroup."""
        grp = QActionGroup(self)
        grp.setExclusive(True)
        current = theme.normalize(QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))
        self._theme_actions = {}
        for name, key in (("dark", "menu.theme.dark"), ("light", "menu.theme.light")):
            act = view.addAction(i18n.t(key))
            act.setCheckable(True)
            act.setChecked(name == current)
            act.triggered.connect(lambda _checked=False, n=name: self._on_theme(n))
            grp.addAction(act)
            self._theme_actions[name] = act

    def _build_lang_menu(self, view):
        """Sekcja języka w &Widok — bliźniak motywu (QActionGroup, klucz QSettings `ui/lang`).
        Endonimy z `i18n.available_langs()` NIE są tłumaczone. D-L1: zmiana zapisuje `ui/lang`
        i stosuje się przy STARCIE (nota w statusbarze), więc zaznaczenie odbija stan trwały,
        nie „za restart" — bieżąca sesja pozostaje w języku, w którym wystartowała."""
        grp = QActionGroup(self)
        grp.setExclusive(True)
        current = i18n.current_lang()   # ŻYWY język sesji (ustawiony w `main` z QSettings/locale)
        self._lang_actions = {}
        for code, endonym in i18n.available_langs():
            act = view.addAction(endonym)
            act.setCheckable(True)
            act.setChecked(code == current)
            act.triggered.connect(lambda _checked=False, c=code: self._on_lang(c))
            grp.addAction(act)
            self._lang_actions[code] = act

    def _on_lang(self, code):
        """Zapisz wybór języka (zadziała przy następnym starcie — D-L1 restart-required v1).
        NIE wołamy `i18n.set_lang` na żywo: `_LANG` mutowany w trakcie sesji rozdarłby raport
        liczony off-thread (R-i18n #6). Nota w statusbarze mówi userowi, że trzeba zrestartować."""
        QSettings("Horreum", "Horreum").setValue("ui/lang", code)
        self._flash(i18n.t("lang.restart_note"), ms=8000)   # jedno wejście na pasek (FH-2)

    def _on_theme(self, name):
        """Przełącz motyw: zastosuj do aplikacji, POTEM utrwal (F6 recenzja #7 — nie zapisuj skórki,
        która się wywali w apply), i przemaluj otwarte widoki. Paleta globalna odświeża resztę sama;
        grid czyta kolory na żywo (viewport().update()), wykluczenia facetów wypalone → refresh_theme."""
        app = QApplication.instance()
        if app is None:
            return
        apply_theme(app, name)
        QSettings("Horreum", "Horreum").setValue("ui/theme", name)
        grid_view = getattr(self, "grid_view", None)
        if grid_view is not None:
            grid_view.table.viewport().update()
            grid_view.facet_rail.refresh_theme()
        if self.home_view is not None:                 # złota ramka kafla to arkusz widżetu
            self.home_view.use_theme(name)
        obs = getattr(self, "observatory_view", None)   # mapa maluje QPainterem — paleta jej nie odświeży (F8)
        if obs is not None:
            obs.map_view.refresh_theme()
        planner = getattr(self, "planner_view", None)   # akcenty planera są per MOTYW (T5, wiz R2):
        if planner is not None:                        # wyszarzenie wiersza, ⚠ nota, „bez luk", chipy
            planner.use_theme(name)
        # KOLOR WYPALONY W ITEMIE NIE ŚLEDZI MOTYWU (wiz T2 N4). `_DIM["fg"]` odświeża się przy
        # `apply_theme`, ale wiersze zbudowane WCZEŚNIEJ trzymają starą wartość — po przełączeniu
        # na jasny szarość z motywu ciemnego spadała do 2,07:1. Listy budowane z `QListWidgetItem`
        # (nie przez delegata czytającego motyw w `paint`) muszą więc powstać na nowo.
        objects = getattr(self, "object_view", None)
        if objects is not None:
            objects._load_review()
        tasks_view = getattr(self, "tasks_view", None)
        if tasks_view is not None:
            tasks_view.refresh_counts()

    def _build_central(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        # Sidebar nawigacji (F5): lista pionowa miejsc zamiast paska przycisków-zakładek.
        # Ukryty do montażu widoków (dom widoczności JAWNY: _clear_views chowa, _mount_views odsłania).
        self.nav = QListWidget()
        self.nav.setFixedWidth(160)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        # Klik albo Enter na wierszu = „idę tam pracować" (fokus wchodzi na stronę), same strzałki
        # = przeglądanie sidebara (fokus zostaje w liście) - patrz `_on_nav_changed`.
        self.nav.itemClicked.connect(self._on_nav_wejscie)
        self.nav.itemActivated.connect(self._on_nav_wejscie)
        # Odczyt Domu (~0,1 s na żywej bazie, teczki osobno w tle) dopiero po POSTOJU na wierszu:
        # strzałki w sidebarze mijają Dom w drodze do Znajdź i nie mają za każdym razem czekać.
        # Kolejny ruch restartuje zegar, a po nim odczyt idzie tylko, gdy Dom wciąż jest na ekranie.
        self._dom_po_postoju = QTimer(self)
        self._dom_po_postoju.setSingleShot(True)
        self._dom_po_postoju.setInterval(_DOM_POSTOJ_MS)
        self._dom_po_postoju.timeout.connect(self._odswiez_dom_po_postoju)
        self.nav.setVisible(False)
        outer.addWidget(self.nav)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        # Pusty stan ODKRYWALNY w centrum (wizytator F5 #3) — statusBar to za mało dla pierwszego
        # ekranu nowego usera; chowany, gdy jest baza (steruje _sync_db_state).
        self.empty_note = QLabel(i18n.t("main.no_db"))
        self.empty_note.setAlignment(Qt.AlignCenter)
        self.empty_note.setWordWrap(True)
        self.empty_note.setVisible(False)
        outer.addWidget(self.empty_note, 1)
        self.setCentralWidget(central)
        # WŁASNY KANAŁ FAZY (F-1) — widżet STAŁY paska statusu, nie `showMessage`. Rozdział jest
        # tu koniecznością, nie estetyką: `showMessage` ma jedno miejsce, więc opis roboty
        # („Odświeżam widoki po etapie…") wypychałby z niego raport, który właśnie padł („Etap
        # Rozwiąż zakończony") — a raport jest tym, po co user czekał. Pusty w spoczynku, więc
        # w bezczynności nie zabiera ani piksela.
        # WŁASNY KANAŁ RECEPTY (FH-2) — ta sama konieczność, co przy fazie niżej, tylko od strony
        # DŁUGOŚCI: zdanie po geście osi urosło do 252 znaków = 1336 px przy 1459 px dostępnych
        # (przy skalowaniu 125 % 1695/1672, przy 150 % 1947/1814), a `QStatusBar` tnie BEZ
        # wielokropka i w środku słowa. Ucinany był człon OSTATNI, czyli instrukcja powrotu —
        # jedyna część zdania, po którą user faktycznie sięga.
        #
        # RECEPTA WYKONUJE POWRÓT, NIE TYLKO GO OPISUJE (FH-2e). Klik robi człon PIERWSZY recepty
        # (kolejność członów jest kolejnością w czasie): odsłonięcie celu albo pozycję menu, którą
        # zdanie nazywa - ten sam slot, co w menu, bez kopii. Wariant „potem" (gest jeszcze
        # niewykonalny) zostawia przycisk WYGASZONY, nie znika: zdanie dalej mówi prawdę.
        #
        # `autoRaise` WYŁĄCZONE RAZEM ZE ZDJĘCIEM PRZEZROCZYSTOŚCI DLA MYSZY - obie połowy naraz.
        # Płaski rysunek był uczciwy, dopóki kontrolka nic nie robiła; teraz klik działa, więc ma
        # wyglądać na przycisk (firsthand mierzył ramkę 31,31,31 z gradientem 79-81 - właśnie tę
        # afordancję).
        #
        # BEZ `role=secondary`: selektor motywu to wyłącznie `QLabel[role=…]` (`theme.py`), więc na
        # `QToolButton` własność jest MARTWA - i dobrze, bo gdyby działała, recepta zeszłaby do
        # 3,67:1, poniżej progu 4,5:1 (zmierzone). Własność zdjęta, żeby pierwszy „naprawiacz" jej
        # nie ożywił.
        self.recipe_label = QToolButton()
        # Nazwa obiektu = selektor reguły WYGASZONEJ recepty w `theme.qss` (W4): wygaszona recepta
        # to zdanie do przeczytania, więc ma tekst `secondary_text` i ramkę przerywaną, a nie
        # domyślne `disabled_text` (1,63:1 w ciemnym motywie, firsthand na platformie natywnej).
        self.recipe_label.setObjectName(theme.RECEPTA_OBJECT_NAME)
        self.recipe_label.setAutoRaise(False)
        self.recipe_label.setFocusPolicy(Qt.NoFocus)
        self.recipe_label.clicked.connect(self._wykonaj_recepte)
        self.statusBar().addPermanentWidget(self.recipe_label)
        self.recipe_label.setVisible(False)     # po dodaniu — `addPermanentWidget` pokazuje widżet
        self._czlony_recepty = ()               # człony recepty na przycisku (FH-2e: klik robi pierwszy)
        self._recepta_wstrzymana = False        # blokada po wykonaniu członu - dwuklik to jeden gest (Z5)
        # FAZA DOPIERO PO RECEPCIE - kolejność dodawania jest kolejnością OD LEWEJ, więc faza dodana
        # pierwsza wchodziła MIĘDZY raport a receptę i rozdzielała dwa człony jednego zdania
        # komunikatem trzeciej sprawy (firsthand, zrzut `K_faza.png`). Recepta przykleja się teraz
        # do raportu, a faza siada przy uchwycie zmiany rozmiaru.
        self.phase_label = QLabel("")
        self.phase_label.setProperty("role", "secondary")
        self.statusBar().addPermanentWidget(self.phase_label)
        self._pelny_komunikat = ""              # treść przed elizją (podpowiedź + ponowny pomiar)
        self._pelna_recepta = ""                # …i jej człon drugi, bo podpowiedź niesie OBA
        self._ms_komunikatu = 5000              # timeout żywego raportu (0 = bez wygasania)
        self._ostatnio_pokazany = ""            # tekst POSTAWIONY przez nas - strażnik cudzych zdań
        self._miejsce_komunikatu = None         # miejsce nawigacji, do którego raport należy (None = żadne)
        # Raporty widoków czekające na wejście w SWOJE miejsce nawigacji (`_raport_miejsca`):
        # `{miejsce: zdanie}` - wczytanie Zbiorów i oś stanowisk po przebiegu Dostawy (AR-43).
        self._odlozone_raporty = {}
        # Wygaśnięcie raportu zeruje jego pełną treść i podpowiedź. RECEPTY NIE GASI (FH-2e):
        # recepta żyje tyle, co jej prawda - gasi ją cudzy raport (`_flash`), wyjście ze Zbiorów
        # i sam widok, gdy przestaje być prawdziwa - a nie zegar komunikatu.
        self.statusBar().messageChanged.connect(self._on_status_changed)

    def _show_view(self, idx):
        """Przełącz WIERSZ sidebara (seam dla kodu i testów) - trasę do strony i prezentacji
        rozstrzyga `_on_nav_changed` z `_TRASY`."""
        self.nav.setCurrentRow(idx)

    def show_find(self, query=None):
        """Wejście do strony zbiorów w prezentacji Znajdź - jedyna droga z Domu i z menu. `query`
        (gdy podane) zastępuje bieżący zbiór wynikiem zapytania; bez niego zbiór zostaje, jaki był.
        Wiersz sidebara przełącza stronę i prezentację (`_on_nav_changed`), a kontener dostaje
        wywołanie jeszcze raz WPROST: wejście z Domu i z menu to zamiar szukania, więc fokus ma
        trafić w pole także wtedy, gdy przełączenie oddało go liście, która go trzymała."""
        self._show_view(NAV_ZNAJDZ)
        self.znajdz_view.show_find(query)

    def show_classic(self):
        """Wejście do strony zbiorów w prezentacji klasycznej (dzisiejszy ekran Zbiorów)."""
        self._show_view(NAV_ZBIORY)

    def _strona(self):
        """Bieżąca strona stosu (`STRONA_*`) - miejsce, z którym wiążą się raporty i recepta."""
        return self.stack.currentIndex()

    def _on_nav_changed(self, row):
        if row < 0:                     # nav.clear() przy przemontowaniu emituje -1 (F5R#6)
            return
        trasa = _TRASY.get(row)
        if trasa is None:               # nagłówek „Więcej" - ręka go nie wybierze, kod nie powinien
            return
        strona, prezentacja = trasa
        self.stack.setCurrentIndex(strona)
        if prezentacja == PREZENTACJA_ZNAJDZ:
            # `show_find` kładzie fokus w polu zapytania - dobrze, gdy człowiek przyszedł szukać, ale
            # strzałki w sidebarze zatrzymywałyby się na Znajdź na zawsze (następna strzałka trafia
            # w pole). Fokus wraca więc do listy, jeśli tam był; wejście „na serio" (klik, Enter)
            # oddaje go polu w `_on_nav_wejscie`, a Dom i menu wchodzą przez `show_find`.
            z_listy = self.nav.hasFocus()
            self.znajdz_view.show_find()
            if z_listy:
                self.nav.setFocus(Qt.OtherFocusReason)
        elif prezentacja == PREZENTACJA_KLASYCZNA:
            self.znajdz_view.show_classic()
        if self._miejsce_komunikatu is not None and self._miejsce_komunikatu != strona:
            # Raport widoku nie przechodzi do cudzego miejsca; `clearMessage` gasi też receptę
            # (`_on_status_changed`), a tu zerujemy to, co tamta droga zostawia przy cichym pasku.
            self._miejsce_komunikatu = None
            self._pelny_komunikat = ""
            self.statusBar().clearMessage()
        # Recepta mówi o Zbiorach (jedynym nadawcą jest grid), więc poza nimi gaśnie z paska -
        # a przy powrocie widok podaje ją ze stanu, o ile wciąż jest prawdą (FH-2e). Dom niesie
        # ją osobno, ze strumienia (`_recepta_gridu`).
        if strona != STRONA_ZBIORY:
            self._ustaw_recepte("")
        msg = self._odlozone_raporty.pop(strona, "")
        if msg:
            # Raport z chwili, gdy tego miejsca nie było widać - pada teraz, przy nim.
            self._flash(msg, miejsce=strona)
        if strona == STRONA_ZBIORY:
            self.grid_view.ponow_recepte()
        if strona == STRONA_DOM:
            # Dom mówi o bazie w chwili wejścia. Przełączenie z listy (strzałki, klik) czeka na
            # postój - klik i Enter odczytują od razu w `_on_nav_wejscie`; z kodu (Dom, menu) od razu.
            if self.nav.hasFocus():
                self._dom_po_postoju.start()
            else:
                self._odswiez_dom()
        if strona == STRONA_PORZADKI:   # wejście w Porządki = świeży stan liczników zadań
            self.tasks_view.refresh_counts()
        if strona == STRONA_PLANER and self.planner_view.bez_stanowiska:
            # Stanowisko wskazuje się na innym ekranie (AR-48), więc pusty stan „bez stanowiska"
            # przelicza się przy każdym wejściu, dopóki jest prawdą - gest z pustego stanu obiecuje,
            # że plan policzy się po powrocie.
            self.planner_view.refresh()

    def _on_nav_wejscie(self, item):
        """Klik albo Enter na wierszu: Znajdź oddaje fokus polu zapytania (`show_find` bez zapytania
        nie zmienia zbioru), Dom odczytuje się od razu, bez czekania na postój."""
        row = self.nav.row(item)
        if row == NAV_ZNAJDZ:
            self.znajdz_view.show_find()
        elif row == NAV_DOM:
            self._dom_po_postoju.stop()
            self._odswiez_dom()

    def _odswiez_dom(self):
        """Wejście na Dom: „Co mam" i dziennik od razu, teczki zamówione w tle. Teczki przy KAŻDYM
        wejściu, bo nadanie obiektu w Porządkach przenosi klatki między teczkami, a oś obiektu
        Porządków nie ma sygnału zmiany - wejście jest jedyną chwilą, w której wiadomo, że Dom
        trzeba pokazać prawdziwy. Stare karty stoją do wyniku (zdanie „Liczę gotowość…" nad nimi)."""
        self.home_view.odswiez()
        self.home_view.odswiez_teczki()

    def _odswiez_dom_po_postoju(self):
        """Koniec postoju na wierszu Dom - odczyt tylko, gdy Dom wciąż jest na ekranie (strzałki mogły
        go minąć) i wciąż istnieje (zmiana bazy w trakcie postoju)."""
        if self.home_view is not None and self._strona() == STRONA_DOM:
            self._odswiez_dom()

    def _on_prezentacja_zmieniona(self, prezentacja):
        """Prezentację przełączono Z WNĘTRZA strony zbiorów (przycisk „Zbiory klasyczne" paska
        Znajdź) albo z `show_*` - sidebar ma pokazać właściwy wiersz. Sygnały listy zablokowane:
        strona się nie zmienia, a `_on_nav_changed` zawołałby `show_*` drugi raz (pętla).
        Idempotentne - wiersz już właściwy zostaje."""
        row = _WIERSZ_PREZENTACJI.get(prezentacja)
        if row is None or self.nav.currentRow() == row:
            return
        self.nav.blockSignals(True)
        try:
            self.nav.setCurrentRow(row)
        finally:
            self.nav.blockSignals(False)

    def _zatrzymaj_watki_widokow(self):
        """Zbierz wątki tła widoków, ZANIM widoki znikną (przełączenie bazy, zamknięcie okna).
        `QThread` jest dzieckiem widoku, więc kasowany razem z nim w biegu zabiłby aplikację,
        a wynik doręczony później trafiłby w zamknięte połączenie. Po kluczu metody, nie po
        typie: widok bez wątku tła po prostu jej nie ma.

        Grid nie stoi wprost na stosie (siedzi w kontenerze strony zbiorów), więc jego wątki
        zbieramy jawnie - pytanie samych stron stosu zgubiłoby skład zbioru i pokrycie pól.
        Metody są idempotentne, więc kontener, który kiedyś zacznie delegować, nie szkodzi."""
        widoki = [self.stack.widget(i) for i in range(self.stack.count())]
        if self.stack.count():
            widoki.append(self.grid_view)
        for w in widoki:
            zatrzymaj = getattr(w, "zatrzymaj_pola", None)
            if zatrzymaj is not None:
                zatrzymaj()

    def _clear_views(self):
        self._zatrzymaj_watki_widokow()
        self._odlozone_raporty.clear()       # raporty odłożone mówią o widokach, które właśnie znikają
        # Wykonawcy członów recepty wiszą na gridzie, który zaraz pójdzie do `deleteLater` - recepta
        # schodzi z paska tu, a nie dopiero przy pierwszym raporcie nowej bazy (Z9).
        self._ustaw_recepte("")
        self._recepta_strumienia = None
        self.home_view = None
        self.nav.clear()
        self.nav.setVisible(False)
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    # ---------------------------------------------------------------- montaż widoków na bazie

    def _mount_views(self):
        """(Prze)montuj widoki na bieżącej bazie - strony `STRONA_*`: Dom, zbiory (grid w kontenerze
        Znajdź), Dostawa (pipeline), Porządki (zadania + podstrony osi), Planer; wiersze sidebara wg
        `_TRASY`. Importy widżetów lazy (wzorzec etapów; dla `TasksView`
        OBOWIĄZKOWO - `tasks.py` importuje z `app.py` module-level, F5R2#1: import na górze domknąłby
        cykl). Pod-widoki osi z `TasksView` ALIASOWANE na oknie - kontrakt `axis_view`/
        `observatory_view`/`object_view` przeżywa przemontowanie bez zmian."""
        from horreum.gui.pipeline import (                     # lazy: Qt-import tylko gdy montujemy
            REASON_COPY_FACTS, PipelineView)
        from horreum.gui.grid import FramesView
        from horreum.gui.tasks import TasksView
        from horreum.gui.planner import PlannerView
        from horreum.gui.home import HomeView

        self._clear_views()
        motyw = theme.normalize(QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))
        pipeline = PipelineView(self.db_path, now_fn=self._now)
        pipeline.status_message.connect(self._flash)
        # `stage_finished` ŚWIADOMIE NIEPODPIĘTE: widoki odświeża koniec PRZEBIEGU
        # (`running_changed(False)`), nie koniec etapu - patrz `_odswiez_widoki_po_przebiegu`.
        pipeline.running_changed.connect(self._on_pipeline_running)
        pipeline.open_collection.connect(self._on_open_collection)   # P5b: raport → perspektywa (3→1)
        self.pipeline_view = pipeline

        grid = FramesView(self.con, now_fn=self._now, pola_poza_watkiem=self._pola_poza_watkiem)
        grid.status_message.connect(self._flash_grid)
        grid.load_report.connect(self._raport_wczytania_gridu)
        grid.ponow_raport_wczytania()        # zbiór startu jedzie z wątku tła od `__init__` (AR-27)
        grid.status_recipe.connect(self._recepta_gridu)   # recepta ma własny nośnik (FH-2)
        grid.writeback_busy.connect(self._on_writeback_busy)
        self.grid_view = grid

        tasks = TasksView(self.con, now_fn=self._now)
        self.tasks_view = tasks
        self.axis_view = tasks.axis_view
        self.observatory_view = tasks.observatory_view
        self.object_view = tasks.object_view
        # Takt 3 P-D: okno naprawy nagłówka nie ma własnego resolvera — dostaje ISTNIEJĄCĄ drogę
        # etapu wraz z przełączeniem widoku na Dostawę (precedens „3→1"). Wstrzykiwane TU, bo tylko
        # gospodarz zna obie powierzchnie.
        tasks.object_view.run_stage_fn = self._resolve_after_repair
        # …i to samo dla gestu osi STOSU (R2): panel Rodowód zmienia fakt, na którym stoi dobór
        # wejść, więc musi umieć domknąć własny gest. Bez tej linii user wędrował na inny ekran po
        # przycisk stojący obok wyboru katalogu (firsthand 0808).
        grid.run_stage_fn = self._stack_lineage_after_gesture
        tasks.object_view.writeback_busy.connect(grid.set_writeback_busy)   # mutex w drugą stronę
        tasks.object_view.writeback_busy.connect(pipeline.set_writeback_busy)   # i Dostawa gaśnie
        # CZWARTA POWIERZCHNIA gestu osi obiektu (S2b, §4/14c-f): gest z paska Zbiorów zmienia
        # kolejkę przeglądu w oknie osi — a tamten widok nie ma skąd o tym wiedzieć. Gospodarz zna
        # obie strony, więc to on je łączy (grid nie importuje osi, oś nie importuje gridu).
        grid.object_axis_changed.connect(tasks.object_view.refresh)
        grid.observatory_axis_changed.connect(tasks.observatory_view.refresh)   # przeniesione stanowisko
        # …i PIĄTA: badge sidebara, widoczny CAŁY CZAS. Liczy `review_frame_ids`, czyli dokładnie
        # populację, którą oba gesty zmieniają — bez tej linii licznik zadań pokazywał stan sprzed
        # gestu aż do wejścia w Porządki, więc „stan widoczny bez klikania" przestawał być prawdą
        # zaraz po akcji, która go zmieniła (adjudykacja recenzji S2b).
        # Podpięte pod sygnał STANU PORZĄDKÓW, nie pod `object_axis_changed`: ten drugi milczał
        # przy gestach osi żywotności klatki („Przywróć"/„Wycofaj"), więc plakietka zostawała przy
        # starej liczbie. Jeden sygnał z ogona każdego gestu gridu, jedno podpięcie tutaj - bez
        # drugiego podpięcia pod `object_axis_changed`, które odświeżałoby plakietkę dwa razy.
        grid.stan_porzadkow_changed.connect(tasks.refresh_counts)
        for v in (tasks.axis_view, tasks.object_view):
            v.status_message.connect(self._flash)
        # OŚ STANOWISK MÓWI PRZY KAŻDYM ODŚWIEŻENIU, gdy jest pusta („Brak stanowisk na osi…"),
        # a odświeża się też po przebiegu Dostawy - zdanie przykrywało wtedy status etapu, po
        # który user patrzy (AR-43). Ta sama droga, co raport wczytania Zbiorów: przy widocznych
        # Porządkach pada od razu, poza nimi czeka na wejście w nie.
        tasks.observatory_view.status_message.connect(
            lambda msg: self._raport_miejsca(msg, STRONA_PORZADKI, wiaz=False))
        tasks.open_collection.connect(self._on_open_collection)
        # Wiersz „?" Porządków prowadzi tam, gdzie jest jego robota - do Dostawy (AR-28 (b)) - i
        # niesie powód: linia nad akcjami mówi, po co człowiek tu jest. Obie drogi do sygnału
        # (wiersz „?”, pusta perspektywa kopii) czekają na fakty kopii, więc powód jest jeden.
        tasks.open_intake.connect(lambda: (pipeline.show_reason(REASON_COPY_FACTS),
                                           self._show_view(NAV_DOSTAWA)))
        # Pusta perspektywa kopii w Zbiorach mówi zdaniem tego wiersza i prowadzi tą samą drogą -
        # sygnał na sygnał, więc droga do Dostawy ma jedno podpięcie.
        grid.open_intake.connect(tasks.open_intake)
        tasks.counts_changed.connect(self._on_tasks_counts)

        # Motyw PRZEKAZANY, nie czytany przez widok z rejestru (wiz T5 N4— jeden właściciel faktu).
        planner = PlannerView(self.con, db_path=self.db_path, now_fn=self._now, theme_name=motyw)
        planner.status_message.connect(self._raport_planera)
        planner.open_sites.connect(self._on_open_sites)                # AR-48: pusty stan → stanowiska
        planner.show_frames_for.connect(self._on_show_target_frames)   # T5e: most planer → grid
        self.planner_view = planner

        # Strona zbiorów: TEN SAM grid w kontenerze z paskiem Znajdź - dwie prezentacje jednego
        # stanu zbioru, nie dwa gridy (JEDEN-STAN-EKRANU).
        znajdz = ZnajdzView(grid)
        # Przełączenie prezentacji z wnętrza strony („Zbiory klasyczne" na pasku czasowników
        # Znajdź) przesuwa wiersz sidebara - inaczej sidebar mówiłby „Znajdź" nad ekranem klasycznym.
        znajdz.prezentacja_zmieniona.connect(self._on_prezentacja_zmieniona)
        self.znajdz_view = znajdz

        # Dom: zamiary człowieka → istniejące drogi. Teczki w tle chodzą razem z wątkami tła
        # Zbiorów - test, który wyłącza tamte, dostaje też przewidywalny Dom.
        home = HomeView(self.con, now_fn=self._now, theme_name=motyw,
                        poza_watkiem=self._pola_poza_watkiem)
        home.przyjmij.connect(lambda: self._show_view(NAV_DOSTAWA))
        home.znajdz.connect(lambda: self.show_find())
        home.wydaj.connect(grid._open_object_release)
        home.popraw.connect(lambda: self._show_view(NAV_PORZADKI))
        home.teczka.connect(self._on_teczka_domu)
        home.wiecej.connect(self._on_wiecej_domu)
        home.recepta_klik.connect(
            lambda: self._wykonaj_recepte(czlony=self._recepta_strumienia.czlony
                                          if self._recepta_strumienia else ()))
        # Teczki liczą godziny per obiekt - gest osi obiektu przenosi klatki między teczkami.
        grid.object_axis_changed.connect(home.odswiez_teczki)
        self.home_view = home

        for widget in (home, znajdz, pipeline, tasks, planner):      # kolejność = `STRONA_*`
            self.stack.addWidget(widget)
        # Wiersze i wiersz startu przy ZABLOKOWANYCH sygnałach listy: Dom właśnie policzył się
        # w konstruktorze, a `_on_nav_changed` zamówiłby drugi odczyt i drugi rachunek teczek
        # (~0,5 s w tle na żywej bazie) przy każdym starcie i zmianie bazy.
        self.nav.blockSignals(True)
        try:
            for row, label in ((NAV_DOM, i18n.t("nav.dom")), (NAV_ZNAJDZ, i18n.t("nav.znajdz")),
                               (NAV_WIECEJ, i18n.t("nav.wiecej")),
                               (NAV_DOSTAWA, i18n.t("nav.dostawa")),
                               (NAV_ZBIORY, i18n.t("nav.zbiory")),
                               (NAV_PORZADKI, i18n.t("nav.porzadki")),
                               (NAV_PLANER, i18n.t("nav.planer"))):
                assert self.nav.count() == row, "wiersze sidebara muszą stać w kolejności NAV_*"
                item = QListWidgetItem(label)
                if row == NAV_WIECEJ:
                    # Nagłówek sekcji: bez flag nie da się go wybrać ani myszą, ani strzałkami
                    # (klawiatura go przeskakuje), a wyszarzenie mówi, że to podpis, nie miejsce.
                    item.setFlags(Qt.NoItemFlags)
                self.nav.addItem(item)
            self.nav.setCurrentRow(NAV_DOM)
        finally:
            self.nav.blockSignals(False)
        self.stack.setCurrentIndex(STRONA_DOM)
        self.nav.setVisible(True)
        tasks.refresh_counts()    # badge żywy od MONTAŻU (F5R#1) - connect i pozycje nav już stoją

    def _odswiez_widoki_po_przebiegu(self):
        """Przebieg Dostawy się skończył (worker, własne połączenie) - read-modele w głównym wątku
        odświeżamy DOPIERO TERAZ (WAL → zapisy workera widoczne). Oś obiektu i grid przeładowują też
        facety (skan/resolver mogły dodać teleskopy/filtry/obiekty/keywordy). Pokrycie pól gridu
        (najdroższe z nich) tylko ZAMAWIAMY: liczy się w wątku tła i wyłącznie wtedy, gdy zmieniły
        się karty (`FramesView._zamow_pola`), więc ten obrót na nie nie czeka.

        RAZ NA PRZEBIEG, NIE RAZ NA ETAP. Do tej zmiany każdy `stage_finished` przeładowywał tu
        wszystkie widoki. Zmierzone na kopii żywej bazy (16 901 klatek, ~1 mln wierszy `cards`):
        11,7 s na etap, z czego 8,4 s to `_load_facets` gridu (samo zapytanie `keyword_facets`
        5,4-6,6 s), a „Przyjmij nowe" ma do dziewięciu etapów - okno stało łącznie ~88 s na
        przebieg. Raport każdego etapu pokazuje sam widok Dostawy, a akcje zapisu pozostałych widoków
        są w trakcie przebiegu i tak wygaszone (`set_busy`), więc ich odświeżenie w połowie łańcucha
        nie dawało userowi nic poza nieruchomym oknem.

        STRAŻ PONOWNEGO WEJŚCIA. Faza (`busy`) woła `processEvents`, a to doręcza sygnały zebrane
        w kolejce - przy odświeżeniu per etap doręczało W ŚRODKU odświeżenia koniec KOLEJNEGO etapu
        z wątku tła, więc odświeżenia zagnieżdżały się i kończyły w odwróconej kolejności. Po końcu
        przebiegu wątku tła już nie ma, ale strażnik zostaje: prośba, która przyjdzie w trakcie,
        nie zagnieżdża się, tylko zamawia jeden pełny obrót więcej PO bieżącym - czyli ostatnie
        słowo zawsze ma odczyt nowszy niż ostatni zapis.

        POD NAZWANĄ FAZĄ (F-1): przeładowania lecą DOKŁADNIE w chwili, w której pasek Dostawy
        właśnie zgasł - bez fazy user widzi „zakończono" i zaraz potem nieruchome okno."""
        if self._odswiezam_widoki:
            self._odswiez_jeszcze_raz = True
            return
        self._odswiezam_widoki = True
        try:
            while True:
                self._odswiez_jeszcze_raz = False
                with busy.busy(self._say_phase, i18n.t("busy.refresh_views")):
                    self.axis_view.refresh()
                    self.observatory_view.refresh()
                    self.object_view._load_facets()
                    self.object_view.refresh()
                    self.grid_view._load_facets()
                    # Skład zbioru w wątku tła (AR-27: 1,4-1,5 s na żywej bazie stało tu w oknie);
                    # wraca od razu, tabela dostaje zbiór, gdy ten dojedzie.
                    self.grid_view.refresh(w_tle=True)
                    self.tasks_view.refresh_counts()    # liczniki zadań + badge ze świeżego stanu (F5)
                    # Planer (T5): świeże klatki zmieniają POKRYCIE celów (godziny per kanał), więc
                    # plan nocy policzony przed dostawą pokazywałby stare luki.
                    self.planner_view.refresh()
                    # Dom: sumy i dziennik od razu, teczki tylko zamawiamy (wątek tła).
                    self._odswiez_dom()
                if not self._odswiez_jeszcze_raz:
                    break
        finally:
            self._odswiezam_widoki = False
            # Faza gaśnie KAŻDĄ drogą - wyjątek w odświeżeniu zostawiałby na pasku opis roboty,
            # która już się skończyła (pasek kłamałby „Odświeżam widoki…" do następnej fazy).
            self._end_phase()

    def _on_open_collection(self, name):
        """Zadanie z Porządków prowadzi do Zbiorów z ustawioną perspektywą (Duplikaty = flaga
        `only_dups` presetu, NIE drzewo filtra - R#14). Prezentacja klasyczna: perspektywa jest
        kontrolką tamtej prezentacji."""
        self.show_classic()
        self.grid_view.apply_perspective(name)

    def _on_show_target_frames(self, canons):
        """Most planer → Zbiory (T5e, D-0731-7 WĄSKO): kanony celu → `object_id` → ISTNIEJĄCY facet
        Obiekt. Nieznany bazie kanon po prostu nie ma pary, a gdy nie ma ŻADNEJ — nie idziemy do
        gridu wcale: pusty facet pokazałby PEŁNĄ bazę i skłamał, że to klatki celu (przycisk jest
        wtedy nieaktywny, to bramka druga)."""
        pairs = [(r["id"], r["canon"]) for r in queries.object_ids_for_canons(self.con, canons)]
        if not pairs:
            self._flash(i18n.t("planner.no_object_for_target"))
            return
        self.show_classic()
        self.grid_view.apply_object_facet(pairs)

    def _on_open_sites(self):
        """Pusty stan planera „bez stanowiska" (AR-48) → oś obserwatorium w Porządkach, gdzie stoi
        „Wskaż stanowisko…". Gospodarz zna oba ekrany; planer nie importuje Porządków."""
        self._show_view(NAV_PORZADKI)
        self.tasks_view.otworz_stanowiska()

    def _on_teczka_domu(self, object_id, canon):
        """Karta teczki na Domu → Znajdź z facetem tego obiektu. Ten sam publiczny seam gridu, co
        most planera (`apply_object_facet`): zbiór definiuje wejście, nie poprzedni widok."""
        self.show_find()
        self.grid_view.apply_object_facet([(object_id, canon)])

    def _on_wiecej_domu(self, klucz):
        """Pozycja menu „Więcej…" Domu → istniejąca droga. Narzędzia paska zbioru (nazwy plików,
        makra) otwieramy KLIKIEM ich przycisku, tylko gdy panel jest zamknięty: przycisk jest
        przełącznikiem, więc drugi klik schowałby to, po co człowiek przyszedł."""
        from horreum.gui import home as home_mod     # lazy jak `HomeView` w `_mount_views`
        if klucz == home_mod.WIECEJ_PLANER:
            self._show_view(NAV_PLANER)
        elif klucz == home_mod.WIECEJ_STANOWISKA:
            self._on_open_sites()
        elif klucz in (home_mod.WIECEJ_NAZWY, home_mod.WIECEJ_MAKRA):
            self.show_classic()
            bar = self.grid_view.sel_bar
            btn = bar.btn_rename if klucz == home_mod.WIECEJ_NAZWY else bar.btn_macro
            if not btn.isChecked():
                btn.click()
        elif klucz == home_mod.WIECEJ_PERSPEKTYWY:
            self.show_classic()
            self.grid_view.combo_persp.setFocus(Qt.OtherFocusReason)
        elif klucz == home_mod.WIECEJ_DOSTAWA:
            self._show_view(NAV_DOSTAWA)
        elif klucz == home_mod.WIECEJ_KLASYCZNE:
            self.show_classic()
        else:
            raise ValueError(f"nieznana pozycja menu Więcej: {klucz!r}")

    def _on_tasks_counts(self, n):
        """Badge sidebara: „Porządki (N)" przy N>0; przy zerze GOŁE „Porządki" - „(0)" to szum (F5R#8).
        Ta sama liczba idzie na kafel „Popraw" Domu - jeden sygnał, dwa nośniki (SPOT)."""
        item = self.nav.item(NAV_PORZADKI)
        if item is not None:
            item.setText(i18n.t("nav.porzadki") if n == 0 else i18n.t("nav.porzadki_count", n=n))
        if self.home_view is not None:
            self.home_view.ustaw_popraw(n)

    def _resolve_after_repair(self):
        """Takt 3 P-D wołany z okna „Napraw nagłówek…": ISTNIEJĄCY etap Dostawy. Zwraca POWÓD
        odmowy (okno je pokaże i zostanie otwarte) albo None — wtedy przełączamy widok na Dostawę,
        żeby postęp etapu był widoczny tam, gdzie zawsze. Przełączenie nie jest interakcją
        użytkownika, więc nie liczy się do budżetu kliknięć."""
        reason = self.pipeline_view.run_stage("resolve")
        if reason is None:
            self._show_view(NAV_DOSTAWA)
        return reason

    def _stack_lineage_after_gesture(self):
        """Takt 3 dla gestów osi STOSU (odniesienie czasu R2) — lustro `_resolve_after_repair`.

        Gest zmienia fakt, na którym stoi dobór wejść, więc dopóki rodowód się nie przeliczy, ekran
        pokazuje stan sprzed gestu. Zdzin nazwał koszt wprost: „muszę teraz zmienić zakładkę na
        Dostawę i klikać button, który jest przy buttonie wyboru folderu — UX-owo to jest
        niezrozumiałe". I jest: akcja domykająca gest mieszkała na innym ekranie, w sekcji
        o wciąganiu plików z dysku.

        Przełączenie widoku ZOSTAJE (jak przy naprawie nagłówka): etap jest długi i jego postęp ma
        być widoczny tam, gdzie zawsze. Różnica wobec stanu sprzed tej zmiany jest w tym, że
        przełącza PROGRAM po jednym kliknięciu, a nie człowiek po trzech."""
        reason = self.pipeline_view.run_stage("stack_lineage")
        if reason is None:
            self._show_view(NAV_DOSTAWA)
        return reason

    def _on_writeback_busy(self, busy):
        """Mutex DWÓCH powierzchni writebacku (D-PD-3). Grid pisze do plików → „Napraw nagłówek…"
        gaśnie; okno naprawy pisze → gaśnie Zatwierdź/Odrzuć/Cofnij gridu. Bez tego oba commity
        spotkałyby się na `BEGIN IMMEDIATE` (`busy_timeout` 5 s) i jeden wróciłby jako 'failed'.
        Trzecia strona mutexu: Dostawa gaśnie przy zapisie Z KAŻDEJ z dwóch powierzchni."""
        self.object_view.set_writeback_busy(busy)
        self.pipeline_view.set_writeback_busy(busy)

    def _on_pipeline_running(self, running):
        """W trakcie etapu wyłącz akcje zapisu osi (szczery disabled). Nawigacja zostaje aktywna —
        user może zerknąć na oś; blokujemy tylko ZAPIS (§6: aktywny tylko „Anuluj" skanu)."""
        self.axis_view.set_busy(running)
        self.observatory_view.set_busy(running)
        self.object_view.set_busy(running)     # „Przypisz obiekt…" (#8/P4) — zapis, gatowany jak inne
        self.grid_view.set_busy(running)     # grid ma akcje ZAPISU (staging/commit/undo) — gatuj (wizytator C1)
        self.planner_view.set_busy(running)  # planer czyta CAŁE archiwum — nie liczmy nocy na wpół zapisanej bazie
        self.home_view.set_busy(running)     # „Wydaj do WBPP" Domu gaśnie jak „Wydaj obiekt…" gridu
        if not running:
            # KONIEC PRZEBIEGU = JEDNO odświeżenie wszystkich widoków i plakietki. Bez warunku
            # „czy etap coś zapisał": przebieg przerwany albo zakończony błędem też mógł zapisać
            # (etapy łańcucha przed błędem, częściowy skan), a `running_changed(False)` przychodzi
            # w każdej z tych dróg - `_cleanup_thread` woła je po KAŻDYM końcu wątku.
            self._odswiez_widoki_po_przebiegu()
            # PANEL RODOWODU CZYTA STAN, KTÓRY ETAP WŁAŚNIE PRZEPISAŁ (bramka pakietu, zarzut 7).
            # Bez tego takt 3 kończył się gorzej, niż zaczynał: gest uruchamiał przeliczenie, panel
            # zostawał z zapisem sprzed niego i etykietą „nieaktualny", a user nie miał jak jej zdjąć
            # inaczej niż przeklikaniem zaznaczenia. Odświeżamy po KAŻDYM etapie, nie tylko po
            # rodowodzie — `resolve` i `group` też ruszają fakty, na których stoi powód.
            self.grid_view.refresh_lineage_panel()

    # ---------------------------------------------------------------- menu Plik: Otwórz/Nowa baza

    def _on_open_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.open_db_title"), "", i18n.t("dialog.open_db_filter"))
        if path:
            self._open_path(path)

    def _on_new_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.new_db_title"), "", i18n.t("dialog.new_db_filter"))
        if path:
            self._open_path(path)

    def open_path(self, path):
        """PUBLICZNE wejście w bazę — jedyna droga dla `main`, które otwiera bazę PO pokazaniu okna
        (F-1). Nazwa bez podkreślenia, bo to nie jest już wyłącznie wewnętrzna sprawa okna."""
        self._open_path(path)

    def _open_path(self, path):
        """Otwórz+zmigruj bazę, przejmij ją na własność, przemontuj widoki. Stare połączenie (nasza
        własność) zamykamy — read-model nowej bazy musi widzieć właściwy plik.

        DWIE NAZWANE FAZY (F-1), bo to najdłuższa operacja aplikacji — zmierzone 4 649 ms na żywej
        `pf4` (16 648 klatek): otwarcie i migracja bazy, potem montaż czterech widoków. Faza idzie
        na ŚRODEK okna, nie na pasek statusu: przy starcie w oknie nie ma jeszcze nic innego,
        a pasek statusu na dole jest ostatnim miejscem, w które user patrzy, gdy pyta „czy to
        w ogóle wstało"."""
        with busy.busy(self._say_phase, i18n.t("busy.open_db", name=Path(path).name)) as faza:
            new_con = db.open_db(path)
            old = self.con
            self.con = new_con
            self.db_path = path
            faza.say(i18n.t("busy.mount_views"))
            self._mount_views()
            self._sync_db_state()
            if old is not None:
                old.close()
        self._end_phase()
        if self._on_db_changed is not None:        # zapamiętaj ostatnią bazę (trwałe ustawienia)
            self._on_db_changed(path)
        self._flash(i18n.t("main.db_loaded", path=path))

    def _say_phase(self, text):
        """Ujście fazy dla operacji CAŁEGO OKNA (F-1) — własna etykieta paska statusu, a przy
        BRAKU zamontowanych widoków także środek okna.

        Dwa miejsca, bo faza ma dwa różne konteksty. Przy starcie `empty_note` jest JEDYNYM
        widocznym elementem: bez niego okno przez sekundy pokazywałoby „Brak bazy" — zdanie
        fałszywe, bo baza właśnie się wczytuje. Przy operacji na zamontowanych widokach środek
        jest zasłonięty stackiem, więc zostaje sama etykieta w pasku.

        Etykieta, nie `showMessage` — patrz komentarz przy `phase_label`: raport i faza nie mogą
        dzielić jednego miejsca, bo wtedy jedno kasuje drugie."""
        self.phase_label.setText(text)
        self._przelicz_pasek()          # faza zabiera szerokość żywemu raportowi (FH-2)
        if not self.stack.isVisible():
            self.empty_note.setText(text)
            self.empty_note.setVisible(True)

    def _end_phase(self):
        """Koniec fazy okna: etykieta gaśnie, a środek wraca do zdania o STANIE (nie o robocie).
        Bez tego pasek zostawałby z opisem operacji, która już się skończyła — czyli kłamał."""
        self.phase_label.setText("")
        self._przelicz_pasek()          # …i oddaje ją z powrotem (FH-2)
        self._sync_db_state()

    def _sync_db_state(self):
        has = self.con is not None
        self.nav.setEnabled(has)
        self.stack.setVisible(has)
        self.empty_note.setVisible(not has)            # pusty stan w centrum (wizytator F5 #3)
        # Tekst pustego stanu WRACA po fazie (F-1): `_say_phase` wpisał tu opis roboty, a gdyby
        # został, kolejne otwarcie bazy z menu zaczynałoby się od zdania o poprzednim otwarciu.
        self.empty_note.setText(i18n.t("main.no_db"))
        if not has:
            # bez timeoutu — to trwała podpowiedź pustego stanu, nie ulotny komunikat akcji.
            # Przez `_flash`, nie gołym `showMessage`: bez tego recepta poprzedniej bazy wisiała
            # tu BEZ KOŃCA nad zdemontowanymi widokami, wskazując menu, którego już nie ma.
            self._flash(i18n.t("main.no_db"), ms=0)

    def _flash_grid(self, msg):
        """Wynik gestu gridu: związany ze Zbiorami, więc gaśnie przy zmianie miejsca nawigacji
        (AR-34). Wynik wyemitowany, gdy user jest gdzie indziej (gest panelu rodowodu przełącza
        widok na Dostawę), nie dostaje powiązania - nie ma z czym gasnąć, a zdanie ma paść."""
        self._flash(msg, miejsce=STRONA_ZBIORY if self._strona() == STRONA_ZBIORY else None)

    def _raport_wczytania_gridu(self, msg):
        """Raport WCZYTANIA zbioru („Wczytuję klatki…", „Grid: N klatek…") - na pasek tylko wtedy,
        gdy Zbiory są widoczne; inaczej czeka na wejście w Zbiory (`_on_nav_changed`).

        Ten raport pada też poza Zbiorami: odświeżenie widoków po przebiegu Dostawy, start okna.
        Na pasku bez powiązania z miejscem przykrywał wtedy status etapu, po który user patrzy
        w Dostawie, mówiąc o ekranie, którego nie widać. Odłożony, a nie zgubiony: przy wejściu
        w Zbiory zdanie „Grid: N klatek…" jest prawdziwe i opisuje to, co właśnie pokazujemy.
        Nowszy raport zastępuje odłożony - liczy się ostatnie wczytanie."""
        self._raport_miejsca(msg, STRONA_ZBIORY)

    def _raport_miejsca(self, msg, miejsce, *, wiaz=True):
        """Raport widoku, który mówi o JEDNYM miejscu nawigacji - na pasek, gdy to miejsce widać,
        a inaczej odłożony do wejścia w nie (`_on_nav_changed`). Jedna droga dla raportu wczytania
        Zbiorów i dla osi stanowisk (AR-43): oba padają też po przebiegu Dostawy i oba przykrywały
        wtedy status etapu, mówiąc o ekranie, którego nie widać.

        `wiaz` - czy raport pokazany OD RAZU ma gasnąć przy wyjściu z miejsca (AR-34). Oś stanowisk
        mówi tym samym kanałem także wyniki gestów, a te przeżywały zmianę widoku - zostają przy
        tym. Odłożony raport pada przy wejściu zawsze związany: mówi już wyłącznie o tym ekranie.
        Nowszy raport zastępuje odłożony - liczy się ostatnie słowo widoku."""
        if self._strona() == miejsce:
            self._odlozone_raporty.pop(miejsce, None)
            self._flash(msg, miejsce=miejsce if wiaz else None)
        else:
            self._odlozone_raporty[miejsce] = msg

    def _raport_planera(self, msg):
        """Komunikat planera - na pasek WYŁĄCZNIE przy widocznym planerze (AR-48).

        Planer liczy noc w wątku tła także wtedy, gdy go nie widać (montaż, przebieg Dostawy),
        a jego zdanie o braku stanowiska stało nad ekranem Dostawy, którego nie dotyczy. Nie
        odkładamy go: przy wejściu na planer ten sam stan mówi PUSTY STAN ekranu (zdanie i gest
        „Ustaw stanowisko…"), więc odłożony raport powtarzałby go drugi raz."""
        if self._strona() == STRONA_PLANER:
            self._flash(msg, miejsce=STRONA_PLANER)

    def _flash(self, msg, ms=5000, miejsce=None):
        """Raport na pasek — Z ELIZJĄ (FH-2). KAŻDY raport gasi receptę poprzedniego gestu.

        `miejsce` wiąże raport z miejscem nawigacji: wejście gdzie indziej (`_on_nav_changed`)
        zdejmuje go z paska razem z receptą. Bez niego komunikat nie gaśnie przy przełączeniu
        widoku (ani raport „Grid: N klatek…", ani `ms=0`).

        JEDYNE WEJŚCIE NA PASEK - i to jest wymóg, nie wygoda (bramka pakietu, zarzut zgodny
        u dwóch soczewek). Gołe `showMessage` obok tej drogi zostawiało receptę poprzedniego gestu
        nad zdemontowanymi widokami (komunikat „brak bazy" idzie BEZ timeoutu, więc wisiała bez
        końca) i nie odświeżało podpowiedzi, która niosła wtedy treść cudzego, wygasłego zdania.
        `ms=0` znaczy „bez timeoutu" - kontrakt `QStatusBar.showMessage`.

        Gaszenie stoi TUTAJ, a nie u wołającego, bo raport bez recepty przychodzi też stamtąd,
        gdzie o recepcie nikt nie słyszał (etapy Dostawy, odświeżenie gridu). Instrukcja powrotu
        wisząca przy cudzym zdaniu mówiłaby o geście, po którym nie ma już śladu na ekranie."""
        self._ustaw_recepte("")
        self._pelny_komunikat = msg
        self._ms_komunikatu = ms
        self._miejsce_komunikatu = miejsce
        self._wyswietl(msg)

    def _pokaz_recepte(self, tekst):
        """Recepta ostatniego gestu na własny widżet — i PONOWNY pomiar elizji raportu (FH-2).

        Kolejność jest wymuszona: raport leci pierwszy (`_po_gescie_osi`), więc gdy przychodzi tu
        recepta, komunikat jest już przycięty do zapasu SPRZED jej pojawienia się. Widżet recepty
        zabiera szerokość (`addPermanentWidget`), więc bez tego ponowienia raport wystawałby pod
        nią - czyli sam rozdział członów wyprodukowałby to ucięcie, które miał zdjąć."""
        self._ustaw_recepte(tekst)
        if tekst and self._pelny_komunikat:
            self._przelicz_pasek()

    def _recepta_gridu(self, recepta):
        """Recepta z gridu - na pasek tylko przy widocznych Zbiorach (FH-2e). Grid składa ją ze
        stanu przy KAŻDYM przeładowaniu, także po przebiegu Dostawy, a recepta mówi o Zbiorach;
        przy wejściu w nie widok poda ją ponownie (`FramesView.ponow_recepte`).

        Dom dostaje KAŻDĄ receptę strumienia, niezależnie od widocznej strony: jego „Ostatnio" żyje
        wyłącznie tym strumieniem (pusta recepta zdejmuje ją z Domu), a nie raportami paska."""
        self._recepta_strumienia = recepta if recepta else None
        if self.home_view is not None:
            self.home_view.pokaz_recepte(recepta)
        if self._strona() == STRONA_ZBIORY:
            self._pokaz_recepte(recepta)

    def _wykonaj_recepte(self, *, czlony=None):
        """Klik w receptę = człon PIERWSZY (kolejność członów jest kolejnością w czasie, FH-2e).
        Człon bez wykonawcy ma przycisk wygaszony, więc tu nie dochodzi - warunek jest drugą linią
        obrony, bo sygnał bywa wołany wprost (testy, skróty).

        `czlony` podaje Dom: jego recepta przychodzi ze strumienia i żyje dłużej niż ta na pasku,
        którą gasi każdy cudzy raport. Bez argumentu - człony z paska. Keyword-only, bo `clicked`
        przycisku paska podałby tu `checked: bool`.

        PODWÓJNY KLIK TO JEDEN GEST MOTORYCZNY (Z5). Wykonanie członu składa receptę odwrotną
        synchronicznie (odświeżenie → `ponow_recepte`), więc drugi klik tego samego ruchu ręki
        wykonałby odwrót odwrotu - masowo i bez potwierdzenia. Po wykonaniu przycisk stoi więc
        wygaszony przez systemowy odstęp podwójnego kliku (`doubleClickInterval`), a nie do
        następnego obrotu pętli: drugi klik dwukliku przychodzi z systemu do ~500 ms później,
        więc blokada na jeden obrót niczego by nie złapała. Blokada jest JEDNA dla paska i Domu -
        to ta sama recepta, a dwuklik na którymkolwiek nośniku to wciąż jeden gest."""
        czlony = self._czlony_recepty if czlony is None else czlony
        if self._recepta_wstrzymana or not czlony:
            return
        wykonaj = czlony[0].wykonaj
        if wykonaj is None:
            return
        self._recepta_wstrzymana = True
        try:
            wykonaj()
        finally:
            self._wlacz_recepte(False)
            if self.home_view is not None:
                self.home_view.wstrzymaj_recepte(True)
            QTimer.singleShot(QApplication.doubleClickInterval(), self, self._odblokuj_recepte)

    def _wlacz_recepte(self, wlaczona):
        """Stan przycisku recepty - JEDNO miejsce dla włączenia i kursora (W4). Wygaszenie pokazuje
        ramka przerywana z `theme.qss` i kursor strzałki; tekst zostaje czytelny (`secondary_text`),
        bo wariant „potem" jest zdaniem do przeczytania. Włączona recepta ma kursor ręki - klik coś
        robi."""
        self.recipe_label.setEnabled(wlaczona)
        self.recipe_label.setCursor(Qt.PointingHandCursor if wlaczona else Qt.ArrowCursor)

    def _odblokuj_recepte(self):
        """Koniec blokady po wykonaniu członu (Z5): przycisk wraca do stanu BIEŻĄCEJ recepty."""
        self._recepta_wstrzymana = False
        self._wlacz_recepte(bool(self._czlony_recepty)
                            and self._czlony_recepty[0].wykonaj is not None)
        if self.home_view is not None:             # `None` po demontażu w trakcie blokady
            self.home_view.wstrzymaj_recepte(False)

    def _wyswietl(self, msg):
        """Wyrenderuj raport na pasek i ZAPAMIĘTAJ, co dokładnie tam postawiliśmy."""
        self._ostatnio_pokazany = self._zwezone(msg)
        self.statusBar().showMessage(self._ostatnio_pokazany, self._ms_komunikatu)

    def _przelicz_pasek(self):
        """Przemierz elizję ŻYWEGO raportu - po każdej zmianie szerokości widżetów stałych.

        Wołają to trzy powierzchnie, bo wszystkie trzy zabierają miejsce komunikatowi: recepta,
        wejście w fazę i jej koniec. Bez tego broniła się przed własną szerokością tylko recepta,
        a faza („Odświeżam widoki po etapie…") wpychała żywy raport pod siebie - ten sam defekt,
        tyle że z drugiej strony paska (bramka pakietu, soczewka repo).

        ⚠ NIE NADPISUJEMY CUDZEGO ZDANIA. Ten warunek jest tu po tym, jak przeliczenie WSKRZESIŁO
        raport sprzed chwili: pasek niósł już komunikat postawiony z pominięciem `_flash`, a faza
        wepchnęła na jego miejsce nasz zapamiętany tekst. Porównanie z tym, co sami postawiliśmy,
        rozstrzyga to bez zgadywania - i jest odporne na kolejnego pisarza spoza tej drogi."""
        if not self._pelny_komunikat:
            return
        if self.statusBar().currentMessage() != self._ostatnio_pokazany:
            return
        self._wyswietl(self._pelny_komunikat)

    def _ustaw_recepte(self, recepta):
        """Wpisz receptę na jej przycisk, PRZYCIĘTĄ do swojego sufitu (pusta = przycisk znika).

        `recepta` to `grid.Recepta` (zdanie + człony z wykonawcami) - kontrakt `status_recipe`;
        pusta (także `""`) zdejmuje przycisk.

        SUFIT SZEROKOŚCI JEST STRAŻNIKIEM, NIE OZDOBĄ (bramka pakietu, soczewka architektury):
        bez niego recepta jest bezpieczna wyłącznie przez dzisiejszą zawartość katalogu i18n -
        dłuższa etykieta menu w przyszłym tłumaczeniu zjadłaby pole raportu bez żadnego sygnału.
        Pełna treść nie ginie: niesie ją podpowiedź paska (`_zwezone`) i podpowiedź przycisku.

        KONTRAKT: NAPIS NA PRZYCISKU OPISUJE TO, CO ZROBI KLIK (Z6). Klik robi człon pierwszy,
        bo kolejność członów jest kolejnością w czasie - a w realnych receptach człon drugi nigdy
        nie jest wykonalny obok pierwszego (wariant „potem" istnieje właśnie dlatego, że cel trzeba
        najpierw odsłonić). Wersja FH-8, która przy braku miejsca zdejmowała człon PIERWSZY,
        pokazywała więc instrukcję, której klik nie wykonywał. Teraz przy braku miejsca zostaje
        człon pierwszy z „ · …" na znak, że jest dalszy ciąg, a dalsze człony idą do podpowiedzi;
        gdy nie mieści się nawet on, tniemy go od prawej. Nazwa pozycji menu z członu drugiego
        wraca na przycisk sama, gdy po kliknięciu recepta złoży się ze stanu jako jednoczłonowa."""
        bar, przycisk = self.statusBar(), self.recipe_label
        if not recepta:
            self._pelna_recepta, self._czlony_recepty = "", ()
            przycisk.setVisible(False)
            przycisk.setText("")
            przycisk.setToolTip("")
            return
        self._pelna_recepta = str(recepta)
        self._czlony_recepty = recepta.czlony
        przycisk.setVisible(True)
        przycisk.setToolTip(str(recepta))
        self._wlacz_recepte(recepta.czlony[0].wykonaj is not None and not self._recepta_wstrzymana)
        # NADDATEK WIDŻETU MIERZONY, NIE ZGADYWANY: `QToolButton` dokłada do tekstu własne obramowanie
        # i marginesy, więc elizja liczona wprost do sufitu przebijała go o te kilkadziesiąt pikseli
        # (zmierzone: 944 px przy sufcie 914). Stawiamy pełny tekst, odczytujemy różnicę między
        # podpowiedzią rozmiaru a szerokością samego tekstu i dopiero wtedy tniemy - dzięki temu
        # próg trzyma się także po zmianie motywu, fontu i skalowania DPI.
        fm = QFontMetrics(bar.font())
        napis = str(recepta)
        przycisk.setText(napis)
        naddatek = przycisk.sizeHint().width() - fm.horizontalAdvance(napis)
        sufit = max(int(bar.width() * _PASEK_UDZIAL_RECEPTY) - naddatek, 0)
        if fm.horizontalAdvance(napis) > sufit and len(recepta.czlony) > 1:
            napis = recepta.czlony[0].tekst + recepta.SEPARATOR + "…"
        przycisk.setText(fm.elidedText(napis, Qt.ElideRight, sufit))

    def _on_status_changed(self, msg):
        """Wygasł komunikat ⇒ gaśnie jego pełna treść i podpowiedź; podpowiedź zostaje z samą receptą.

        RECEPTA NIE GAŚNIE TU (FH-2e). Dawniej żyła tyle, co jej raport, i to rodziło dwie klasy
        błędów naraz: dwuczłonowa recepta umierała po wykonaniu pierwszego członu (odświeżenie
        emituje własny raport), a pusty `QStatusTipEvent` z podświetlonej pozycji menu - okno
        przepisuje go na `showMessage("")`, nie do odróżnienia od timeoutu - gasił instrukcję
        w trakcie celowania w pozycję, którą nazywa. Recepta stoi teraz na STANIE: gasi ją cudzy
        raport (`_flash`), wyjście ze Zbiorów i sam widok, gdy przestaje być prawdą."""
        if msg:
            return
        self._pelny_komunikat = ""
        self.statusBar().setToolTip(self._pelna_recepta)

    def _zwezone(self, msg):
        """Przytnij raport do REALNEGO zapasu paska, jawnym wielokropkiem, z pełną treścią w podpowiedzi.

        `QStatusBar` nie ma elizji: przy nadmiarze ucina w środku słowa i nie zostawia po tym
        żadnego znaku, więc zdanie kończące się na „…Przywróć c" wygląda na kompletne. Wielokropek
        zdejmuje to CICHE kłamstwo, a tooltip oddaje treść, której nie da się już zmieścić.

        MIERZYMY DO WIDŻETÓW STAŁYCH, nie do szerokości paska: `addPermanentWidget` zabiera miejsce
        komunikatowi, więc faza i recepta odliczają się od zapasu — bez tego sam rozdział z FH-2
        kazałby zdaniu ucinać się WCZEŚNIEJ niż przed naprawą.

        PODPOWIEDŹ STOI ZAWSZE, NIE TYLKO PRZY CIĘCIU, i to jest odpowiedź na trzy dziury naraz
        (bramka pakietu, oba silniki): gałąź „za wąsko na elizję" oddawała pełny tekst Qt do
        cichego ucięcia i przy okazji KASOWAŁA podpowiedź; zwężenie okna w trakcie życia
        komunikatu tnie zdanie, które przy pomiarze się mieściło; a recepta nie ma jak pokazać
        własnej podpowiedzi, bo jest przezroczysta dla myszy. Jedna podpowiedź z całym zdaniem -
        raport plus recepta - zdejmuje wszystkie trzy bez ani jednej gałęzi.

        PRZED POKAZANIEM OKNA NIE TNIEMY: geometria jest wtedy zastępcza (domyślne 640 px), więc
        elizja liczona z niej okroiłaby zdanie, które w prawdziwym oknie mieści się w całości."""
        bar = self.statusBar()
        bar.setToolTip(" · ".join(x for x in (msg, self._pelna_recepta) if x))
        if not bar.isVisible():
            return msg
        stale = sum(w.sizeHint().width() + _PASEK_ODSTEP
                    for w in (self.phase_label, self.recipe_label) if w.isVisible())
        zapas = bar.width() - stale - _PASEK_MARGINES
        fm = QFontMetrics(bar.font())
        if zapas < _PASEK_MIN_KOMUNIKATU or fm.horizontalAdvance(msg) <= zapas:
            return msg
        return fm.elidedText(msg, Qt.ElideRight, zapas)

    def closeEvent(self, event):
        # Top-level apka jest właścicielem połączenia - zamyka je przy zamknięciu okna. Wątki tła
        # widoków PRZED połączeniem: wynik doręczony po zamknięciu nie ma prawa go dotknąć.
        self._zatrzymaj_watki_widokow()
        if self.con is not None:
            self.con.close()
            self.con = None
        super().closeEvent(event)


def main(argv=None):
    """Uruchom aplikację: `python -m horreum.gui [ścieżka.bazy]`. Z argumentem — otwiera wskazaną bazę
    od razu; bez argumentu — odtwarza OSTATNIO używaną bazę (zapamiętaną w trwałych ustawieniach), a
    gdy jej brak lub plik zniknął — okno startuje bez bazy (użytkownik wskazuje/tworzy z menu Plik).
    Każdy wybór bazy (z argumentu, menu „Otwórz", „Nowa") jest zapamiętywany jako ostatnia baza.
    Połączeniem zarządza `MainWindow` (zamyka je w `closeEvent`)."""
    import sys
    from pathlib import Path

    # Konsola Windows bywa cp1250 — komunikat ma polskie znaki; przełącz stdout na UTF-8 (best-effort,
    # jak `horreum.cli`), by `print` nie wywalił się na innym kodowaniu konsoli.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication([])

    # Trwałe ustawienia (Windows: rejestr) — przechowują ścieżkę ostatnio otwartej bazy i motyw.
    settings = QSettings("Horreum", "Horreum")

    # Motyw PRZED oknem (F6 §7): domyślnie ciemny; paleta/QSS/kolory stanów podłączone globalnie.
    apply_theme(app, theme.normalize(settings.value("ui/theme", theme.DEFAULT)))

    # Język PRZED oknem (#1, lustro motywu): jawny wybór z QSettings, inaczej auto z locale systemu
    # (gdy w available_langs), inaczej PL. Ustawiamy `_LANG` RAZ — stałe→klucze w widokach rozwiążą
    # etykiety z katalogu w czasie budowy (D-L1 restart-required v1; `_LANG` nie mutuje w sesji).
    saved_lang = settings.value("ui/lang", None)
    auto_lang = saved_lang if saved_lang is not None else QLocale().name()[:2]
    i18n.set_lang(auto_lang)

    if argv:
        start = argv[0]
    else:
        start = settings.value("ostatnia_baza", None)
        # Ostatnia baza mogła zostać przeniesiona/usunięta — wtedy startujemy bez bazy (nie wybuchamy).
        if start and not Path(start).exists():
            start = None

    def zapamietaj_baze(path):
        settings.setValue("ostatnia_baza", path)

    # OKNO STAJE PRZED CZYTANIEM BAZY (F-1). Do tej zmiany `MainWindow(start)` otwierał bazę
    # i montował cztery widoki W KONSTRUKTORZE, a `show()` szedł dopiero po nim — zmierzone
    # 4 649 ms na żywej `pf4`, przez które na ekranie nie było NICZEGO (a w wydaniu onefile
    # dochodzi do tego rozpakowanie bootloadera). Użytkownik pytał wtedy nie „czy trwa", tylko
    # „czy ono w ogóle wstało" — i nie miał gdzie przeczytać odpowiedzi.
    # Kolejność jest tu CAŁĄ naprawą: okno bez bazy → faza na środku → dopiero odczyt.
    win = MainWindow(on_db_changed=zapamietaj_baze)
    win.show()
    if start:
        # Faza PRZED pierwszym przemalowaniem: bez tego okno błysnęłoby zdaniem „Brak bazy",
        # które za moment i tak przestaje być prawdą.
        win._say_phase(i18n.t("busy.open_db", name=Path(start).name))
        busy.repaint()
        win.open_path(start)
    return app.exec()
