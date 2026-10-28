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
import itertools
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QLocale, QSettings, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from horreum import db, macro as macro_mod, projection, repo, resolver, stacks
from horreum.resolver import forma_karty_object   # SPOT formy karty OBJECT (Qt-wolny)
from horreum.gui import busy, i18n, mapproj, portfolio, queries, rows, theme
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.kolko import kolko                # kółko myszy przestawia pole wyłącznie z fokusem (AR-349)
from horreum.gui.wb_worker import (EtykietaBledu, ZdanieZeSzczegolem, ogon_cofniecia,
                                   podpowiedz_kart, polecenie_zdania, szczegol_zdania, tekst_powodu,
                                   zdanie_commitu_kart, zlacz_zdania)
from horreum.gui.config_dialog import AssignConfigDialog, dopasuj_wysokosc
# Kontener strony zbiorów: stałe prezentacji są wartościami jego sygnału, a `_TRASY` (poziom modułu)
# ich potrzebuje; import ciągnie grid (~30 ms przy imporcie okna, zmierzone 2026-10-09).
from horreum.gui.flows.znajdz_view import PREZENTACJA_KLASYCZNA, PREZENTACJA_ZNAJDZ, ZnajdzView
from horreum.gui.observatory_dialog import AssignObservatoryDialog
from horreum.gui.map_view import SitesMapView
from horreum.gui import rows
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
_REVIEW_PAYLOAD = rows.ROLA_PRZEGLADU_PAYLOAD
_REVIEW_INFO = rows.ROLA_PRZEGLADU_INFO

# Kolumny listy głównej — indeksy nazwane (czytelne handlery zamiast magicznych liczb).
# Nagłówek = telescop_canon (tożsamość osi po przejściu fitsmirror); Etykieta = nazwa usera.
COL_ID, COL_CANON, COL_LABEL, COL_STATUS, COL_FRATIO, COL_FOCAL, COL_FRAMES = range(7)
# ZAPAS PASKA STANU dla elizji raportu (FH-2). Odliczamy od szerokości paska to, czego etykieta
# raportu nie dostanie: własne marginesy układu i uchwyt zmiany rozmiaru w prawym rogu
# (`_PASEK_MARGINES`), odstęp przed każdym widżetem, który stoi obok raportu (`_PASEK_ODSTEP`).
# Poniżej `_PASEK_MIN_KOMUNIKATU` nie tniemy w ogóle - na tak wąskim pasku elizja zostawiłaby sam
# wielokropek, czyli mniej niż ucięte zdanie.
#
# OBIE LICZBY ZMIERZONE, NIE OSZACOWANE (firsthand, 39 pomiarów na trzech skalowaniach): odstęp
# układu to dokładnie 6 px, a pole raportu kończy się na `następny_widżet.x() − 8`. Wersja z 24
# przebijała pole o stałe 2 px - ostatnia kolumna pikseli wielokropka bywała przez to ucięta.
# Po przejściu raportu na własną etykietę (AR-76: etykieta od x = 2, recepta zaraz za nią) pomiar
# powtórzony: 26 w stylu Fusion przy 900/1400/1913 px i każdym układzie recepty i fazy, 22 w stylu
# Windows - liczba Fusion zostaje, bo w Windows jest o 4 px ostrożniejsza, nie ciaśniejsza.
# Falsyfikator: `zapas` policzony tą arytmetyką ma się równać szerokości, którą układ paska daje
# etykiecie raportu przy tekście dłuższym niż pasek.
_PASEK_MARGINES = 26
_PASEK_ODSTEP = 6
_PASEK_MIN_KOMUNIKATU = 80
# SUFIT RECEPTY jako UDZIAŁ paska, nie liczba pikseli - bo rośnie ona z fontem i ze skalowaniem
# DPI, a chroni przed nią raport, który skaluje się tak samo. Dzisiejsza najdłuższa recepta PL
# (~94 znaki) mieści się z zapasem; sufit jest strażnikiem na przyszłe tłumaczenia i dłuższe
# etykiety menu, nie ograniczeniem stanu bieżącego.
_PASEK_UDZIAL_RECEPTY = 0.45
# OKNO PRIORYTETU RAPORTU GESTU (AR-97): przez tyle milisekund od raportu gestu (odmowa, wynik
# okna, raport z receptą) zdanie „<etap>: gotowe.” nie wypiera go z paska, tylko czeka. Zmierzone
# przed naprawą: odmowa kafla Przyjmij żyła 0,39 s, zdanie żniw 0,38 s - mniej niż trwa jedno
# przeczytanie. 5 s = domyślny czas życia raportu (`_flash(ms=5000)`): zdanie gestu dostaje
# cały czas, który pasek daje każdemu raportowi. Dłuższe okno nic by nie dało przy raporcie
# 5-sekundowym, a raport bez wygasania (`ms=0`) trzymałoby z dala od świeżego stanu etapu dłużej,
# niż ktoś czyta jedno zdanie.
_PRIORYTET_GESTU_MS = 5000
# Wartownik pominiętego `miejsce` w `MainWindow._flash` (AR-236): odróżnia „wołający nie podał
# miejsca” (raport ze szczegółem wiąże się z bieżącą stroną) od świadomego `None` (bez wiązania).
_BIEZACA_STRONA = object()
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
    "config_focal": "repair.tip_config",
    None: "repair.tip_pick",
}
# Kubełki osi SPRZĘTU - rozłączne populacje, jedna akcja („Przypisz zestaw…"), bo różni je to,
# SKĄD bierze się grupa, a nie to, co się z nią robi (lustro `_ASSIGN_TAGS` na osi obiektu).
# Trzeci (AR-128, D-1012-2 `Q8`): klatki z zestawem automatu, których ogniskowa w pliku odbiega od
# teleskopu - okno wybiera z teleskopów mieszczących się w tolerancji albo dopisuje nowy.
_CONFIG_TAGS = frozenset({"config_review", "config_by_hand", "config_focal"})
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


def apply_theme(app, name, *, styl=True):
    """Zastosuj motyw do CAŁEJ aplikacji: Fusion + QPalette (propaguje do otwartych okien) + QSS
    akcentów; podłącz kolory stanów gridu/facetów (SPOT). `name` znormalizowany (`theme.normalize`).
    Import grid/facets lazy — unika cyklu z warstwą Porządków (F5R2#1) i pozostaje spójny ze stylem
    importów widoków w `_mount_views`.

    `styl=False` (zmiana motywu w biegu, `MainWindow._on_theme`, AR-175): Fusion stoi od startu (`main`),
    a ponowne `setStyle` to zdarzenie stylu do każdego widżetu - zmierzone na kopii pf4 61-168 ms
    samego wywołania i 0,7-1,5 s ogona pętli z przeliczeniem szerokości tabel."""
    from horreum.gui import facets, grid, map_view, projection_dialog, rows, tasks
    if styl:
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

# RODZAJ KOLORU ELEMENTU (AR-175): kolor wypalony w elemencie listy albo tabeli (`setForeground`) nie
# idzie za motywem, więc element zapisuje przy budowie, CZYM jest jego kolor (rodzaj, nie wartość),
# a `odswiez_motyw` widoku przemalowuje z tej roli - bez ponownego odczytu bazy. Numer poza pasmem
# `rows` ({+1, +2, +3, +6}) i rolami kolejki przeglądu (+4, +5); `config_dialog` zajmuje +10/+11.
ROLA_RODZAJU_KOLORU = rows.ROLA_RODZAJU_KOLORU
# Wartość komórki optyki do edytora (liczba bez znacznika ręki) - rejestr ról w `rows`.
_ROLA_WARTOSCI_EDYTORA = rows.ROLA_WARTOSCI_EDYTORA
# Rodzaje elementów osi (kolejka przeglądu obiektów, komórki optyki osi teleskopu) → kolor z motywu.
_RODZAJ_SZARY, _RODZAJ_WERDYKT = "szary", "werdykt"


def _pedzel_rodzaju(rodzaj):
    """Kolor bieżącego motywu dla rodzaju elementu osi albo None (rodzaj bez koloru)."""
    return {_RODZAJ_SZARY: _DIM, _RODZAJ_WERDYKT: _WERDYKT}.get(rodzaj, {}).get("fg")


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


class _OptykaEdycja(QStyledItemDelegate):
    """Edytor komórek f/ i Ogniskowej Osi teleskopu (AR-128, bramka kodu N5): edytor startuje
    wartością bez znacznika ręki, a zatwierdzenie oddaje WPIS do `on_commit(telescope_id, kolumna,
    tekst)` zawsze - także wtedy, gdy tekst równa się temu, co komórka pokazuje. Model komórki nie jest
    zmieniany: po zapisie widok i tak przeładowuje się z bazy. Wpis idzie przez `QTimer.singleShot(0)`:
    przeładowanie tabeli w środku zamykania edytora usuwałoby komórkę, którą Qt jeszcze obsługuje.

    KOTWICA = TELESKOP I KOLUMNA Z CHWILI OTWARCIA EDYTORA (właściwości edytora z `createEditor`),
    nie numer wiersza ani indeks z chwili zatwierdzenia: między otwarciem edytora a wykonaniem wpisu
    tabela mogła się przeładować w innym porządku (klik nagłówka, `refresh` z innego widoku albo
    z końca etapu Dostawy), a indeks wskazałby wtedy sąsiada. `setModelData` czyta wyłącznie kotwicę."""

    def __init__(self, on_commit, parent=None):
        super().__init__(parent)
        self._on_commit = on_commit

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        editor.setProperty("telescope_id", index.siblingAtColumn(COL_ID).data(Qt.UserRole))
        editor.setProperty("kolumna", index.column())
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.data(_ROLA_WARTOSCI_EDYTORA) or "")

    def setModelData(self, editor, model, index):
        tid, kolumna, tekst = editor.property("telescope_id"), editor.property("kolumna"), editor.text()
        QTimer.singleShot(0, lambda: self._on_commit(tid, kolumna, tekst))


def zdanie_cofniecia_dopisania(wynik, telescope):
    """Zdanie wyniku „Cofnij dopisanie” (`repo.NewTelescopeUndo`, AR-133) - JEDNO dla recepty paska
    (oś obiektu) i gestu Osi teleskopu. Odmowa bez zapisu mówi powodem z tokenu klingi; cofnięcie
    mówi, ile klatek wróciło (zero - osobnym zdaniem, bez „cofnięto”, którego nie było), ile zostało
    i czy teleskop zszedł z osi."""
    def powod(token):
        return i18n.t(f"object.config_undo_add.refused.{token}")
    if wynik.refusal is not None and not (wynik.restored or wynik.kept):
        return i18n.t("object.config_undo_add.refused", telescope=telescope,
                      reason=powod(wynik.refusal))
    msg = (i18n.t_plural("object.config_undo_add.done", wynik.restored, telescope=telescope)
           if wynik.restored else i18n.t("object.config_undo_add.nothing", telescope=telescope))
    if wynik.kept:
        msg += i18n.t_plural("object.config_undo_add.kept", wynik.kept)
    return msg + (i18n.t("object.config_undo_add.retired", telescope=telescope) if wynik.retired
                  else i18n.t("object.config_undo_add.stays", telescope=telescope,
                              reason=powod(wynik.refusal)))


# ---- wspólne dwóch tabel osi (teleskop, obserwatorium): sort po kliku nagłówka, przerwana edycja

def _klucz_tekstu(v):
    """Klucz sortu komórki tekstowej osi: klucz naturalny biblioteki (`queries.natural_key`: bez
    wielkości liter, człony liczbowe jako liczby), surowy tekst jako człon następny dla porządku
    całkowitego. Pusty tekst = brak wartości (`None`)."""
    return (queries.natural_key(v), v) if v else None


def _posortuj_wiersze(rows, sort, klucz):
    """Wiersze tabeli osi w porządku kliku nagłówka `sort = (kolumna, Qt.SortOrder)`; `None` =
    porządek read-modelu. `klucz(row, kolumna)` daje wartość sortu albo `None` (komórka bez
    wartości). Komórki bez wartości zawsze na końcu, w obu kierunkach i w porządku read-modelu -
    ta sama reguła co MISSING w siatce (`grid_model._sort_key`). Sort stabilny: remis zostaje
    w porządku read-modelu."""
    if sort is None:
        return list(rows)
    col, order = sort
    obecne = [r for r in rows if klucz(r, col) is not None]
    puste = [r for r in rows if klucz(r, col) is None]
    return sorted(obecne, key=lambda r: klucz(r, col), reverse=order == Qt.DescendingOrder) + puste


def _wlacz_sort_naglowka(hdr, on_change):
    """Sort po kliku nagłówka tabeli osi: nagłówek sam przełącza kolumnę i kierunek (strzałka Qt),
    a widok układa wiersze PRZED wypełnieniem (`_posortuj_wiersze` w `refresh`). Start bez strzałki -
    porządek read-modelu, dopóki człowiek nie kliknie.

    `setSortingEnabled` zostaje wyłączone na stałe: sort modelu przestawiałby wiersze w trakcie
    `_set_cell` po numerze wiersza i zaraz po zatwierdzeniu edycji, a „puste na końcu w obu
    kierunkach” wymaga znajomości kierunku, której porównanie dwóch komórek nie ma."""
    hdr.setSectionsClickable(True)
    hdr.setSortIndicatorShown(True)
    hdr.setSortIndicator(-1, Qt.AscendingOrder)
    hdr.sortIndicatorChanged.connect(on_change)


def _zdanie_przerwanej_edycji(table):
    """Zdanie paska dla `refresh` tabeli osi, który zastał otwarty edytor komórki, albo `None`.

    Przebudowa wierszy (`_przeladuj_wiersze`) każe Qt zamknąć edytor BEZ zatwierdzenia, więc wpis
    człowieka przepada - bez tego zdania po cichu. Wpisu nie zatwierdzamy na siłę: zapisałby
    niedokończony tekst. Wołający pyta PRZED przebudową i pomija pytanie, gdy sam przeładowuje się
    z zatwierdzenia tej komórki (wtedy edytor jest jeszcze otwarty, ale wpis już zapisany)."""
    if table.state() == QAbstractItemView.EditingState:
        return i18n.t("axis.edit_interrupted")
    return None


# Kolumny tekstowe Osi teleskopu → pole wiersza `active_telescopes`. Pozostałe kolumny są liczbowe.
_TEL_SORT_TEKST = {COL_CANON: "telescop_canon", COL_LABEL: "label", COL_STATUS: "status"}


def _klucz_sortu_teleskopu(row, col):
    """Klucz sortu wiersza Osi teleskopu po kolumnie `col`; `None` = komórka bez wartości.

    Liczby jako liczby (ID, klatki, ogniskowa i f/ tak, jak je pokazuje komórka: ręka, potem pliki -
    `queries.telescope_focal`/`telescope_f_ratio`), więc „10” stoi za „9”. Tekst - `_klucz_tekstu`."""
    if col in _TEL_SORT_TEKST:
        return _klucz_tekstu(row[_TEL_SORT_TEKST[col]])
    if col == COL_FOCAL:
        return queries.telescope_focal(row)
    if col == COL_FRATIO:
        return queries.telescope_f_ratio(row)
    if col == COL_FRAMES:
        return row["frame_count"]
    assert col == COL_ID, col
    return row["id"]


class TelescopeAxisView(QWidget):
    """Osadzalny widok osi TELESKOP: lista kanonicznych teleskopów (lewa) + szczegół zaznaczonego
    (prawa: członkowie scaleni pod nim, zestawy, audyt). Akcje usera (`label`/`approve`/`merge`/
    `unmerge`, od AR-128 także f/ i ogniskowa ręką oraz „Przywróć z plików") idą przez `repo`.
    Komunikaty statusu emituje sygnałem `status_message` - pasek statusu należy do
    okna-gospodarza (`MainWindow`/`TelescopeAxisWindow`), nie do widoku.

    `con` = otwarte połączenie RW (NIE własność widoku — zamyka je okno/gospodarz). `now_fn` = źródło
    czasu akcji (ISO-8601); domyślnie zegar UTC, wstrzykiwalne dla testów."""

    status_message = Signal(str)
    # „Cofnij dopisanie” tej osi zamknął gest „Dopisz nowy…” teleskopu (id) - gospodarz zdejmuje jego wpis z kolejki
    # odłożonych recept osi obiektu (AR-321, `MainWindow._na_cofniete_dopisanie`).
    dopisanie_cofniete = Signal(int)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None, *, leniwie=False):
        """`leniwie=True` (podstrona Porządków przy montażu w trybie wątków tła, AR-175): bez odczytu
        bazy w konstruktorze - widok czyta ją przy pierwszym pokazaniu (`showEvent`). Domyślnie jak
        dotąd: okno osi i widok samodzielny czytają od razu."""
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._loading = False                # tłumi itemChanged podczas programowego wypełniania
        self._source_mergeable = False       # czy zaznaczony wiersz może być źródłem scalenia
        self._rows = {}                      # id → wiersz `active_telescopes` z ostatniego refresh
        self._pliki = {}                     # id → `FilesOptics` (wartość z plików) z ostatniego refresh
        self._busy = False                   # etap Dostawy pisze w tle - gesty optyki odmawiają (N8)
        self._dopisane = set()               # teleskopy z niecofniętym „Dopisz nowy…” (AR-133)
        self._sort = None                    # (kolumna, Qt.SortOrder) z kliku nagłówka; None = read-model
        self._z_zatwierdzenia = False        # refresh z zatwierdzenia komórki - edytor otwarty, wpis zapisany
        self._przeladowan = 0                # licznik `refresh` - pętla `_on_data_changed` staje po przeładowaniu
        # Odczyt odłożony do pokazania (`leniwie`, wzór `ObjectAxisView.odswiez_gdy_widoczny`); każde
        # `refresh` znacznik zdejmuje.
        self._nieaktualny = False
        self._build_ui()
        if leniwie:
            self._nieaktualny = True
        else:
            self.refresh()

    def showEvent(self, event):
        """Pokazanie przy postawionym znaczniku (`leniwie`) czyta bazę PO OBROCIE PĘTLI: wejście
        z wiersza Porządków (`TasksView.otworz_os_teleskopu`) przeładowuje oś samo, zanim przełączy
        stronę - znacznik schodzi i drugiego odczytu tego samego stanu nie ma."""
        super().showEvent(event)
        if self._nieaktualny:
            QTimer.singleShot(0, self, self._odswiez_jesli_nieaktualny)

    def _odswiez_jesli_nieaktualny(self):
        if self._nieaktualny and self.isVisible():
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
        _wlacz_sort_naglowka(hdr, self._on_sort_changed)
        self.table.verticalHeader().setVisible(False)
        self._edit_triggers = self.table.editTriggers()   # przywracane po set_busy(False) (wizytator T3)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        # ZAPIS TYLKO ZE ZMIANY TEKSTU (AR-326): `itemChanged` strzela przy KAŻDYM `setData` elementu - kolor,
        # podpowiedź, rola rodzaju - a w komórce optyki zapisuje werdykt ręki (`_on_optics_edited`). Sygnał
        # modelu niesie role (zmierzone, PySide6 6.9.2: `setForeground` [9], `setToolTip` [3], `setText` i edycja
        # [0, 2]), więc slot filtruje je u źródła; straż `_loading` zostaje drugą linią obrony.
        self.table.model().dataChanged.connect(self._on_data_changed)
        # Edytor optyki zatwierdza WPIS, nie zmianę tekstu komórki (wizytacja N5): `itemChanged` nie
        # strzela, gdy user wpisze to, co komórka już pokazuje (1600 z plików), a to jest właśnie
        # potwierdzenie ręką - teleskop w Horreum to wartość potwierdzona ręką (D-1012-2).
        self._optyka_delegat = _OptykaEdycja(self._on_optics_edited, self.table)
        for c in (COL_FOCAL, COL_FRATIO):
            self.table.setItemDelegateForColumn(c, self._optyka_delegat)
        lv.addWidget(self.table)

        actions = QHBoxLayout()
        self.btn_approve = QPushButton(i18n.t("axis.tel.approve"))
        self.btn_approve.clicked.connect(self._on_approve)
        actions.addWidget(self.btn_approve)
        # „Cofnij dopisanie” (AR-133) - TRWAŁA droga powrotu z „Dopisz nowy…”: recepta paska gaśnie
        # z każdym raportem i zmianą strony, a ten przycisk czyta ślad gestu z bazy (`telescope_add`),
        # więc przeżywa przełączenie ekranu i restart. Ta sama klinga i te same odmowy co recepta.
        self.btn_undo_add = QPushButton(i18n.t("axis.tel.undo_add"))
        self.btn_undo_add.setToolTip(i18n.t("axis.tel.undo_add_tip"))
        self.btn_undo_add.clicked.connect(self._on_undo_add)
        actions.addWidget(self.btn_undo_add)
        actions.addStretch(1)
        actions.addWidget(QLabel(i18n.t("axis.tel.merge_into")))
        self.combo_target = kolko(QComboBox())
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
        # OPTYKA (AR-128) - własny blok nad Zestawami (wizytacja N22): średnica WYLICZONA z ogniskowej
        # i f/ (pola średnicy nie ma - decyzja Zdzinia 2026-10-12) i „Przywróć z plików", który zdejmuje
        # rękę obu pól optyki zaznaczonego teleskopu. Przycisk aktywny wyłącznie, gdy jest co zdjąć
        # i nic nie biegnie w tle - szczery disabled, jak reszta paska (wizytator P2).
        rv.addWidget(QLabel(i18n.t("axis.tel.optics_header")))
        self.aperture = QLabel("")
        self.aperture.setWordWrap(True)
        rv.addWidget(self.aperture)
        self.btn_restore_optics = QPushButton(i18n.t("axis.tel.restore_optics"))
        self.btn_restore_optics.setToolTip(i18n.t("axis.tel.restore_optics_tip"))
        self.btn_restore_optics.clicked.connect(self._on_restore_optics)
        rv.addWidget(self.btn_restore_optics)
        # ZESTAWY (AR-128): co ten teleskop daje z każdą kamerą - piksel, skala bin 1/bin 2, kadr.
        # Liczby z planera (`sky.rigs`), więc panel i planer nie mają prawa mówić różnie.
        rv.addWidget(QLabel(i18n.t("axis.tel.rigs")))
        self.rigs = QListWidget()
        # Wiersz zestawu bywa dłuższy niż panel (firsthand na kopii `pf4`: poziomy pasek przewijania
        # pod trzema wierszami) - elizja z prawej, pełne zdanie w podpowiedzi wiersza.
        self.rigs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rigs.setTextElideMode(Qt.ElideRight)
        rv.addWidget(self.rigs)
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
        zaznaczenie po `telescope_id`, a nie po numerze wiersza (po merge i po sorcie wiersze się
        przesuwają). Porządek z kliku nagłówka (`self._sort`) przeżywa przeładowanie: wiersze są
        układane przed wypełnieniem, więc numer wiersza w pętli = wiersz na ekranie. Otwarty edytor
        komórki przebudowa zamyka bez zapisu - pasek mówi wtedy, że wpis trzeba powtórzyć."""
        self._przeladowan += 1
        prev = self._selected_telescope_id()
        przerwana = None if self._z_zatwierdzenia else _zdanie_przerwanej_edycji(self.table)
        self._nieaktualny = False            # odczyt odłożony przy montażu (`leniwie`, AR-175) - zrobiony
        self._loading = True
        try:
            rows = _posortuj_wiersze(queries.active_telescopes(self.con), self._sort,
                                     _klucz_sortu_teleskopu)
            self._rows = {row["id"]: row for row in rows}
            self._dopisane = queries.open_telescope_adds(self.con)
            # jedna derywacja „z plików" (AR-128) - ta sama, którą liczy Dostawa
            self._pliki = queries.optics_from_files(self.con)
            _przeladuj_wiersze(self.table, len(rows))
            target_row = -1
            for r, row in enumerate(rows):
                self._set_cell(r, COL_ID, str(row["id"]), data=row["id"])
                self._set_cell(r, COL_CANON, row["telescop_canon"])
                self._set_cell(r, COL_LABEL, row["label"] or "", editable=True)
                self._set_cell(r, COL_STATUS, row["status"])
                pliki = self._pliki.get(row["id"])
                self._set_optics_cell(r, COL_FRATIO, row["f_ratio_user"], row["f_ratio_nominal"],
                                      None if pliki is None else pliki.f_ratio,
                                      None if pliki is None else pliki.f_ratio_n)
                self._set_optics_cell(r, COL_FOCAL, row["focal_user"], row["focal_nominal"],
                                      None if pliki is None else pliki.focal,
                                      None if pliki is None else pliki.focal_n)
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
        if przerwana:
            self._flash(przerwana)

    def _on_sort_changed(self, col, order):
        """Klik nagłówka: zapamiętaj kolumnę i kierunek, ułóż listę od nowa (zaznaczenie zostaje)."""
        self._sort = (col, order)
        self.refresh()

    def _set_cell(self, r, c, text, *, editable=False, data=None, align=None):
        item = QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:                          # etykieta, f/ i ogniskowa (AR-128) - edycja in-line
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        if align is not None:                 # liczby prawo-wyrównane (skanowalność, wizytator T1)
            item.setTextAlignment(align)
        if data is not None:                  # telescope_id na kolumnie ID (kotwica wiersza)
            item.setData(Qt.UserRole, data)
        self.table.setItem(r, c, item)

    def _set_optics_cell(self, r, c, hand, column, files, files_n):
        """Komórka f/ albo Ogniskowej (AR-128): wartość = ręka, a bez niej kolumna automatu (reguła
        `queries.telescope_focal`/`telescope_f_ratio`), edytowalna dwuklikiem. Ręka niesie znacznik
        i kolor werdyktu (`_WERDYKT` - „to Twoje zdanie"), tooltip mówi zawsze, co mówią PLIKI
        (moda i liczba klatek, które ją niosą) - po wpisaniu ręką ta liczba nie znika.

        KOMÓRKA NIE PODPISUJE SIĘ „Z PLIKÓW", GDY TO NIEPRAWDA (bramka kodu N2/N5): kolumna automatu
        różna od dzisiejszej mody plików → szarość i zdanie „nieaktualne - Dostawa przeliczy";
        pliki milczą, a kolumna coś niesie → zdanie „pliki nie zeznają - wartość zapisana wcześniej"
        (RC8R: 1200 z chwili powołania teleskopu ręką)."""
        value = hand if hand is not None else column
        tekst = _fmt(value)
        self._set_cell(r, c, tekst, editable=True, align=_NUM_ALIGN)
        item = self.table.item(r, c)
        item.setData(_ROLA_WARTOSCI_EDYTORA, tekst)          # wartość do edytora (bez znacznika)
        z_plikow = (i18n.t("axis.tel.files_focal" if c == COL_FOCAL else "axis.tel.files_f_ratio",
                           v=_fmt(files), n=files_n)
                    if files is not None else i18n.t("axis.tel.files_none"))
        if hand is not None:
            item.setData(ROLA_RODZAJU_KOLORU, _RODZAJ_WERDYKT)   # `odswiez_motyw` (AR-175)
            item.setForeground(_WERDYKT["fg"])
            item.setText(f"{queries.CLEARED_MARK} {tekst}")
            item.setToolTip(i18n.t("axis.tel.optics_hand_tip", files=z_plikow))
        elif column is not None and files is None:
            item.setToolTip(i18n.t("axis.tel.optics_earlier_tip", files=z_plikow))
        elif column is not None and float(column) != float(files):
            item.setData(ROLA_RODZAJU_KOLORU, _RODZAJ_SZARY)
            item.setForeground(_DIM["fg"])
            item.setToolTip(i18n.t("axis.tel.optics_stale_tip", files=z_plikow))
        else:
            item.setToolTip(i18n.t("axis.tel.optics_files_tip", files=z_plikow))

    def odswiez_motyw(self):
        """Zmiana motywu (gospodarz, `MainWindow._on_theme`, AR-175): kolor werdyktu ręki i szarość
        „nieaktualne” w komórkach optyki z ROLI rodzaju zapisanej przy budowie. Dotąd `_on_theme` osi
        nie dotykał - bursztyn ciemnego motywu zostawał na białej bazie jasnego (~1,9:1) do najbliższego
        `refresh`. Bez odczytu bazy; komórki bez rodzaju mają kolor tekstu z palety.

        POD `_loading`, jak wypełnianie w `refresh`: przemalowanie nie jest zmianą tekstu, więc filtr ról
        `_on_data_changed` (AR-326) i tak go nie przepuszcza do zapisu werdyktu ręki; straż zostaje drugą linią
        obrony - każde przemalowanie pod tym samym strażnikiem co `refresh`."""
        self._loading = True
        try:
            for r in range(self.table.rowCount()):
                for c in (COL_FOCAL, COL_FRATIO):
                    item = self.table.item(r, c)
                    pedzel = None if item is None else _pedzel_rodzaju(item.data(ROLA_RODZAJU_KOLORU))
                    if pedzel is not None:
                        item.setForeground(pedzel)
        finally:
            self._loading = False

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

        self._fill_rigs(tid)
        reka = self._rows.get(tid) if tid is not None else None
        self.btn_restore_optics.setEnabled(
            not self._busy and reka is not None
            and (reka["focal_user"] is not None or reka["f_ratio_user"] is not None))
        self.btn_restore_optics.setToolTip(self._zdanie_przywrocenia(reka))
        self.btn_undo_add.setEnabled(not self._busy and tid in self._dopisane)
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
        co przez `_on_selection_changed` przywraca SZCZERE stany przycisków dla zaznaczenia.

        Stan trzyma flaga `_busy` (bramka kodu N8): zmiana zaznaczenia w trakcie etapu nie zapala
        „Przywróć z plików", a edytor optyki otwarty przed etapem odmawia zapisu z komunikatem."""
        self._busy = bool(busy)
        if busy:
            self.btn_approve.setEnabled(False)
            self.btn_merge.setEnabled(False)
            self.btn_unmerge.setEnabled(False)
            self.btn_restore_optics.setEnabled(False)
            self.btn_undo_add.setEnabled(False)
            self.combo_target.setEnabled(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # zamknij in-line edyt etykiety (T3)
        else:
            self.table.setEditTriggers(self._edit_triggers)
            self.combo_target.setEnabled(True)
            self._on_selection_changed()

    # ---------------------------------------------------------------- akcje → repo (jedna klinga)

    def _flash(self, msg):
        self.status_message.emit(msg)

    # Role, które znaczą „zmienił się tekst komórki” - tylko one docierają do zapisu (`_on_data_changed`).
    _ROLE_TEKSTU = frozenset((int(Qt.DisplayRole), int(Qt.EditRole)))

    def _on_data_changed(self, top_left, bottom_right, roles):
        """`dataChanged` modelu tabeli (AR-326): zmiana tekstu komórki (rola wyświetlania albo edycji; pusta
        lista ról = „wszystko się zmieniło”) idzie do `_on_item_changed`, zmiana koloru, podpowiedzi, fontu
        albo roli danych - nie. Bez tego filtra każde `setForeground`/`setToolTip` poza `_loading` w kolumnie
        optyki zapisywałoby werdykt ręki. Zapis komórki przeładowuje widok (`refresh` przebudowuje tabelę), więc
        reszta zakresu mówi już o innych wierszach - pętla staje po pierwszym przeładowaniu."""
        if roles and not self._ROLE_TEKSTU.intersection(int(r) for r in roles):
            return
        przeladowan = self._przeladowan
        for r in range(top_left.row(), bottom_right.row() + 1):
            for c in range(top_left.column(), bottom_right.column() + 1):
                item = self.table.item(r, c)
                if item is not None:
                    self._on_item_changed(item)
                    if self._przeladowan != przeladowan:
                        return

    def _on_item_changed(self, item):
        """Edycja in-line etykiety → `repo.label_telescope`. Pusty label → `ValueError` (kasowanie
        etykiety poza v1) złapany i pokazany, widok wraca do prawdy bazy (refresh). Przeładowanie
        z tej drogi zastaje edytor jeszcze otwarty, ale wpis jest już zapisany - `_z_zatwierdzenia`
        wycisza zdanie o przerwanej edycji."""
        if self._loading:
            return
        self._z_zatwierdzenia = True
        try:
            tid = self.table.item(item.row(), COL_ID).data(Qt.UserRole)
            if item.column() in (COL_FOCAL, COL_FRATIO):
                self._on_optics_edited(tid, item.column(), item.text())
                return
            if item.column() != COL_LABEL:
                return
            try:
                changed = repo.label_telescope(
                    self.con, telescope_id=tid, label=item.text(), now=self._now())
            except ValueError as e:
                self._flash(i18n.t("axis.tel.label_rejected", e=e))
                self.refresh()
                return
            self._flash(i18n.t("axis.tel.label_saved") if changed
                        else i18n.t("axis.tel.label_unchanged"))
            self.refresh()
        finally:
            self._z_zatwierdzenia = False

    def _on_optics_edited(self, tid, col, text):
        """Wpis w f/ albo Ogniskowej teleskopu `tid` (AR-128) → klinga ręki. Porównanie ze STANEM
        RĘKI, nie z tekstem komórki (bramka kodu N5): przy braku ręki każda poprawna liczba zapisuje
        rękę, także równa wartości z plików - to potwierdzenie. Pusty wpis = cofnięcie ręki tego
        pola; przy braku ręki nic do cofnięcia. Przecinek dziesiętny przyjmujemy (`5,6`). Wartość
        nieliczbowa albo spoza zakresu → komunikat z klingi i widok wraca do prawdy bazy. Każda droga
        mówi na pasku - stary komunikat nie zostaje. Pliki nietknięte - to zdanie o teleskopie w bazie.
        W trakcie etapu (`_busy`) odmowa z komunikatem (N8).

        Stan ręki czytany ze ŚWIEŻEGO read-modelu, nie z `_rows` ostatniego przeładowania: teleskop
        mógł zejść z osi (scalony, „Cofnij dopisanie”) między otwarciem edytora a wpisem - wtedy
        wpis przepada ze zdaniem odmowy, bez zapisu i bez wyjątku."""
        if self._busy:
            self._flash(i18n.t("axis.tel.optics_busy"))
            self.refresh()
            return
        wiersz = next((r for r in queries.active_telescopes(self.con) if r["id"] == tid), None)
        if wiersz is None:
            self._flash(i18n.t("axis.tel.optics_rejected", e=i18n.t("axis.tel.optics_gone", tid=tid)))
            self.refresh()
            return
        tekst = (text or "").replace(queries.CLEARED_MARK, "").strip().replace(",", ".")
        ogn = col == COL_FOCAL
        reka = wiersz["focal_user" if ogn else "f_ratio_user"]
        try:
            if not tekst:
                changed = reka is not None and (
                    repo.clear_telescope_focal if ogn else repo.clear_telescope_f_ratio)(
                    self.con, telescope_id=tid, now=self._now())
                msg = "axis.tel.optics_cleared"
            else:
                try:
                    wartosc = float(tekst)
                except ValueError:
                    raise ValueError(i18n.t("axis.tel.optics_not_number", text=tekst)) from None
                if ogn:
                    changed = repo.set_telescope_focal(self.con, telescope_id=tid, focal_mm=wartosc,
                                                       now=self._now())
                else:
                    changed = repo.set_telescope_f_ratio(self.con, telescope_id=tid, f_ratio=wartosc,
                                                         now=self._now())
                msg = "axis.tel.optics_saved"
        except ValueError as e:
            self._flash(i18n.t("axis.tel.optics_rejected", e=e))
            self.refresh()
            return
        self._flash(i18n.t(msg) if changed else i18n.t("axis.tel.optics_unchanged"))
        self.refresh()

    def _on_restore_optics(self):
        """„Przywróć z plików": zdejmij rękę OBU pól optyki zaznaczonego teleskopu JEDNĄ klingą
        (`repo.clear_telescope_optics` - jedna transakcja, dwa zdarzenia, N12). Widok wraca do prawdy
        bazy ZAWSZE (`finally`), także gdy klinga odmówiła. W trakcie etapu - odmowa (N8)."""
        tid = self._selected_telescope_id()
        if tid is None:
            return
        if self._busy:
            self._flash(i18n.t("axis.tel.optics_busy"))
            return
        try:
            a, b = repo.clear_telescope_optics(self.con, telescope_id=tid, now=self._now())
            self._flash(i18n.t("axis.tel.optics_cleared") if a or b
                        else i18n.t("axis.tel.optics_unchanged"))
        except ValueError as e:
            self._flash(i18n.t("axis.tel.optics_rejected", e=e))
        finally:
            self.refresh()

    def _on_undo_add(self):
        """„Cofnij dopisanie” zaznaczonego teleskopu (AR-133): `repo.undo_new_telescope` - ta sama
        klinga i to samo zdanie wyniku co recepta paska (`zdanie_cofniecia_dopisania`). Widok wraca
        do prawdy bazy zawsze - teleskop zdjęty nagrobkiem znika z listy. W trakcie etapu - odmowa
        z komunikatem, jak reszta zapisów osi (N8)."""
        tid = self._selected_telescope_id()
        if tid is None or tid not in self._dopisane:
            return
        if self._busy:
            self._flash(i18n.t("object.config_undo_add.busy"))
            return
        nazwa = queries.telescope_label(self._rows[tid])
        try:
            wynik = repo.undo_new_telescope(self.con, telescope_id=tid, now=self._now())
            self._flash(zdanie_cofniecia_dopisania(wynik, nazwa))
        finally:
            self.refresh()
        if tid not in self._dopisane:            # gest zamknięty (odmowa klingi zostawia go otwartym)
            self.dopisanie_cofniete.emit(tid)

    def _zdanie_przywrocenia(self, row):
        """Podpowiedź „Przywróć z plików" PRZED zapisem (wizytacja N5): co zostanie w polu po zdjęciu
        ręki - moda plików, a gdy pliki milczą, wartość zapisana wcześniej (RC8R: 1200 z chwili
        powołania) albo nic. Bez ręki - zdanie ogólne."""
        if row is None or (row["focal_user"] is None and row["f_ratio_user"] is None):
            return i18n.t("axis.tel.restore_optics_tip")
        pliki = self._pliki.get(row["id"])
        czesci = []
        for reka, kolumna, z_plikow, klucz in (
                (row["focal_user"], row["focal_nominal"], pliki and pliki.focal, "focal"),
                (row["f_ratio_user"], row["f_ratio_nominal"], pliki and pliki.f_ratio, "f_ratio")):
            if reka is None:
                continue
            if z_plikow is not None:
                czesci.append(i18n.t(f"axis.tel.restore_{klucz}_files", v=_fmt(z_plikow)))
            elif kolumna is not None:
                czesci.append(i18n.t(f"axis.tel.restore_{klucz}_earlier", v=_fmt(kolumna)))
            else:
                czesci.append(i18n.t(f"axis.tel.restore_{klucz}_none"))
        return i18n.t("axis.tel.restore_optics_tip") + "\n" + "\n".join(czesci)

    def _fill_rigs(self, tid):
        """Panel „Zestawy" zaznaczonego teleskopu (AR-128): średnica wyliczona ogniskowa / f/ (ręka,
        potem pliki) i wiersz na zestaw z planera (`sky.rigs` - ta sama ogniskowa, ten sam kadr)."""
        from horreum import sky                              # lazy: jak reszta odczytów planera
        self.rigs.clear()
        row = self._rows.get(tid) if tid is not None else None
        if row is None:
            self.aperture.setText("")
            return
        ogn, f = queries.telescope_focal(row), queries.telescope_f_ratio(row)
        self.aperture.setText(
            i18n.t("axis.tel.aperture", d=f"{ogn / f:.0f}", focal=_fmt(ogn), f=_fmt(f))
            if ogn and f else i18n.t("axis.tel.aperture_unknown"))
        for rig in sky.rigs(self.con, only=[row["telescop_canon"]]):
            if rig.scale_arcsec_px is None:
                tekst = i18n.t("axis.tel.rig_unknown", camera=rig.camera,
                               reason=i18n.t(f"axis.tel.rig_reason.{rig.reason}"))
            else:
                tekst = i18n.t("axis.tel.rig_line", camera=rig.camera, px=_fmt(rig.pixel_um),
                               s1=f"{rig.scale_arcsec_px:.2f}", s2=f"{2 * rig.scale_arcsec_px:.2f}",
                               fx=f"{rig.fov_x_arcmin:.1f}", fy=f"{rig.fov_y_arcmin:.1f}")
            it = QListWidgetItem(tekst)
            it.setToolTip(tekst)
            self.rigs.addItem(it)

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
    pominięta z powodem („karta już istnieje") - rozjazd pliku z folderem rozstrzyga człowiek.

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
        powod = i18n.t("path.card_skip.invalid", value=value, reason=tekst_powodu(naruszenie.reason))
    elif forma is None or canon in resolver.kanony_regionow():
        # Forma obiektu-regionu wraca wyłącznie klatce, którą region obejmuje (`resolver.karta_wraca`,
        # AR-177), a ta droga nie pyta per klatka - pomija kartę tym samym powodem co forma None.
        powod = i18n.t("path.card_skip.no_roundtrip", value=value, canon=canon)
    if powod is not None:
        return value, [], [(fid, "", powod) for fid in frame_ids]
    # FITS Z SUMĄ KONTROLNĄ (AR-163) odpada PRZED silnikiem: makro też ją odsiewa (AR-166), ale jego
    # pominięcie mówi zdaniem bez języka UI - tu powód rdzenia idzie przez `tekst_powodu`. Ta sama
    # bramka co w „Napraw nagłówek…” (`queries.fits_checksum_gate`) i ta sama kolejność: najpierw
    # bramki celu (`resolve_target`), potem suma.
    cele = {}
    for t in queries.writeback_frame_targets(con, list(frame_ids)):
        cele.setdefault(int(t["frame_id"]), []).append(t)
    z_suma = []
    for fid, wiersze in cele.items():
        cel, _ = macro_mod.resolve_target(wiersze)
        suma = queries.fits_checksum_gate(cel) if cel is not None else None
        if suma is not None:
            z_suma.append((fid, cel["path"], tekst_powodu(suma)))
    ids_z_suma = {fid for fid, _, _ in z_suma}
    md = macro_mod.MacroDef(assign=macro_mod.Assign(
        keyword="OBJECT", op="add", expr=repr(value), value_type="str"))
    run = macro_mod.run_macro(
        md, [fid for fid in frame_ids if int(fid) not in ids_z_suma],
        targets_fn=lambda ids: queries.writeback_frame_targets(con, ids),
        cards_fn=lambda fid: queries.frame_cards(con, fid))
    return value, list(run.touched), [(s.frame_id, s.path, s.reason) for s in run.skipped] + z_suma


def _wariant_paska_kart(zdanie_pola, zdanie_paska, db_path, commit_id):
    """`po_zamknieciu` okna piszącego karty (AR-283, AR-272): (zdanie pola, zdanie paska, szczegół
    paska, polecenie). Po zamknięciu okna uchwytami cofnięcia commitu są recepta paska „Cofnij zapis
    (commit N)” (AR-296) i CLI - zdanie paska niesie krótkie polecenie bez ścieżki bazy (pełna ścieżka
    przed numerem commitu ginęła w elizji), pełne polecenie stoi w szczególe pod kursorem i w polu
    polecenia nośnika („Kopiuj polecenie”, AR-309). Szczegół trzyma też zdanie na pasku do następnego
    raportu (`MainWindow._flash`, AR-236) - zdanie bez niego gasło po 5 s razem z numerem commitu."""
    polecenie = i18n.t("wb.undo_cli", db=db_path, id=commit_id)
    return (zdanie_pola, zdanie_paska, i18n.t("wb.undo_cli_tip", id=commit_id, cli=polecenie),
            polecenie)


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
    # Nota cofnięcia DOMKNIĘTEGO poza oknem (pasek po zamknięciu, recepta „Cofnij zapis”, AR-296):
    # klatki zostają nazwane z folderu, a „Zatwierdź” już nie istnieje.
    UWAGA_COFNIECIA = "path.cards_restored_closed_note"
    # Fakty operacji zapisu kart (`wb_worker.CzescZapisu`, AR-359) - przychodzą PRZED `_after_commit` (`_na_czesc`),
    # zużywa je `_after_commit`; None = wynik bez faktów (wywołanie wprost) - reguła `CommitResult.commit_id`.
    _czesc = None

    @property
    def commit_po_zamknieciu(self):
        """Commit kart, który po zamknięciu okna wolno cofnąć receptą paska (AR-296), albo None -
        po cofnięciu domkniętym w oknie i po zapisie, który niczego nie podmienił."""
        return self._commit_id

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
        self._db_path = db_path if db_path is not None else queries.db_path_of(con)
        # (zdanie pola `status`, jego wariant dla paska po zamknięciu okna, szczegół paska) - bez
        # przycisków okna, z poleceniem CLI cofnięcia (AR-236, AR-283, `_wariant_paska_kart`,
        # `ObjectAxisView._zdanie_okna_kart`); None = zdanie pola jest dobre i po zamknięciu
        self.po_zamknieciu = None
        self._runner = WritebackRunner(self._db_path, now_fn=now_fn, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)
        # Koniec biegu przelicza „Zatwierdź”: ogon zapisu/cofnięcia przychodzi, gdy
        # uchwyt jest jeszcze zajęty (wątek sprząta się po `done`), więc przycisk liczony w ogonie
        # zostawał wygaszony po udanym cofnięciu, choć zdanie mówi „„Zatwierdź” dopisze karty”.
        self._runner.busy_changed.connect(lambda zajety: zajety or self._sync_confirm())
        self.setWindowTitle(i18n.t("path.title"))
        self._build_ui(proposals)
        self._sync_action()

    def exec(self):
        """Modalny bieg i kasacja okna - wzorzec `object_change_dialog.ObjectChangeDialog.exec`:
        gospodarz czyta po `exec` `assigned` i zdanie stanu, a odroczona kasacja przychodzi
        w jego pętli zdarzeń, po slocie."""
        try:
            return super().exec()
        finally:
            self.deleteLater()

    def _build_ui(self, proposals):
        lay = QVBoxLayout(self)
        head = QLabel(i18n.t("path.head", count=i18n.t_plural(
            "path.head_count", len(proposals),
            frames=i18n.t_plural("grid.frames", sum(p.n_frames for p in proposals)))))
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
            check = QCheckBox(i18n.t("path.item", canon=p.canon,
                                     frames=i18n.t_plural("grid.frames", p.n_frames)))
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
                # Powód bramki celu i makra z kodem (AR-181) w języku UI; zdania katalogu bez zmian.
                self.cards_skipped.addItem(i18n.t("path.cards_skipped_item",
                                                  reason=tekst_powodu(powod), n=n))
            self.cards_skipped.setMaximumHeight(90)
            lay.addWidget(self.cards_skipped)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = EtykietaBledu("")     # zdanie wyniku + szczegół (protokół pola, AR-204)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)   # `commit_id` do skopiowania
        lay.addWidget(self.status)
        self.error = EtykietaBledu("")      # szczegół systemu awarii znika z następnym zdaniem (AR-185)
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
        # ENTER NIE PISZE DO PLIKÓW: `QDialog` robi przycisk z fokusem domyślnym (`autoDefault`), więc
        # Enter na zaznaczonym polu wyboru uruchamiał „Zatwierdź wszystko” (baza i karty w plikach).
        # Domyślny jest „Zamknij” - ten sam wzór co `RepairHeaderDialog._build_ui`.
        for btn in (self.confirm_btn, self.undo_btn, self.resolve_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        close_btn.setDefault(True)

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
        # Błąd POPRZEDNIEJ próby schodzi z pola przed nową - odmowa i awaria tej próby stawiają
        # własne zdanie; inaczej po udanym ponowieniu pasek dokleiłby starą awarię do sukcesu (AR-218).
        self.error.ustaw("")
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
                          of_total=i18n.t_plural("path.of_total", gest.assigned + gest.skipped))
            + grid.zdanie_pominiec(gest))
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
        # Karta W MIEJSCU (AR-117): droga atomowa przepisuje cały plik po SMB i zrywa dowiązania
        # `_WBPP`; plik, w którym karta się nie mieści, rdzeń zapisuje atomowo i mówi dlaczego. Ta sama
        # operacja co szuflada Zbiorów (`commit`, AR-258). Fakty zapisu (`on_partial`, AR-359) - „Cofnij” z zakresu
        # rdzenia, nie z samego `commit_id`.
        self._czesc = None
        self._runner.start("commit", run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed, on_partial=self._na_czesc)

    def _na_czesc(self, op, czesc):
        """Fakty operacji zapisu kart od wykonawcy (`WritebackWorker.czesciowy`, AR-359) - przed `_after_commit`
        tej samej operacji; metoda okna, więc z wątku tła przychodzi kolejką w wątku okna."""
        self._czesc = czesc

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
        """Koniec biegu zapisu. Zdanie odmowy zamknięcia w biegu („Zapis do plików trwa…”, AR-175)
        schodzi z pola: bieg się skończył, a czerwone zdanie stało dotąd obok wyniku. Odmowa klingi
        postawiona w tym polu kliknięciem przed biegiem zostaje - zdejmujemy wyłącznie to jedno zdanie."""
        self.bar.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        if self.error.text() == i18n.t("wb.close_refused"):
            self.error.clear()
        self._sync_confirm()

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)

    def _after_commit(self, op, res):
        """Po commicie kart (wątek główny): zdanie bazy + zdanie plików, „Cofnij karty" i „Rozwiąż
        teraz". `commit_id` widoczny - po zamknięciu okna to jedyny uchwyt do cofnięcia z ręki
        (ta sama umowa co w „Napraw nagłówek…"). Commit, który NIE podmienił żadnego pliku (same
        `blocked`/`failed` bez kopii), oddaje „Zatwierdź" - powtórka ma czym dopisać karty.
        Zapis w miejscu mówi o drodze zapisu tylko przy spadku na atomową (`zdanie_commitu_kart`).

        „COFNIJ” Z FAKTÓW WYKONAWCY (AR-359): zakres z klas rdzenia (`CzescZapisu.zakres`, ta sama reguła co szuflada) -
        sam przerwany zapis w miejscu „Cofnij” nie dostaje (rozstrzyga odzysk, zdanie mówi drogę), podmiana
        niepotwierdzona dostaje z członem „do sprawdzenia”. „Zatwierdź” milczy, dopóki zapis ruszył plik (także otwarty
        zapis - ponowny zapis trafiłby w izolację lokacji); oddaje go wyłącznie zapis, który nic nie ruszył."""
        czesc, self._czesc = self._czesc, None
        glowa = self.status.text()
        summary, cofnij = zdanie_commitu_kart(res, "path.cards_applied", czesc,
                                              przycisk=i18n.t("path.undo_cards_btn"))
        if cofnij is not None:
            self._commit_id = cofnij
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
        self._domkniety = (cofnij is not None or res.commit_id is not None
                           or (czesc is not None and czesc.zakres is not None))
        if res.cancelled:
            self._porzuc_staging()               # reszta runu to sierota - nikt jej nie dokończy
        self._run_id = None                      # run domknięty commitem (R#5) - nie kasuj przy zamknięciu
        # Spadek na drogę atomową zdanie mówi językiem człowieka; szczegół rdzenia - pod kursorem,
        # razem z pozostałymi powodami (okno nie ma listy pozycji) - protokół pola (AR-204).
        self.status.ustaw(glowa + "\n" + summary, podpowiedz_kart(res))
        if cofnij is not None:                   # pasek po zamknięciu: polecenie cofnięcia (AR-283)
            # Po zamknięciu przycisku okna nie ma - człony zdania nazywają polecenie CLI (wzór `_after_undo`).
            cli = i18n.t("wb.undo_cli_short", id=cofnij)
            pasek = zdanie_commitu_kart(res, "path.cards_applied", czesc, przycisk=cli)[0]
            self.po_zamknieciu = _wariant_paska_kart(
                self.status.text(), glowa + "\n" + pasek + i18n.t("wb.undo_short", cmd=cli),
                self._db_path, cofnij)
        self._end_progress()
        dopasuj_wysokosc(self)                   # zdanie bazy + zdanie plików (`config_dialog`)
        self.changed.emit()

    def _on_failed(self, op, msg, podpowiedz):
        """Wyjątek workera: staging tego runu jest sierotą (C1) - sprzątamy go od razu, nie przy
        zamknięciu okna. Szczegół systemu (`podpowiedz`, AR-185) - pod kursorem zdania; następne zdanie
        go zdejmuje. Fakty tej operacji (`_na_czesc`, AR-359) zużywa ta porażka - nie wiszą do następnego zapisu.

        WYJĄTEK ZAPISU PO PODMIANIE (AR-384; wyłącznie `op` `commit` - ten odbiorca łapie też porażkę
        cofnięcia): fakty wykonawcy znają pliki tej operacji → zdanie jak w szufladzie („N z M zapisane,
        potem błąd: … - „Cofnij karty” cofa zapisane (commit N)”, `zdanie_porazki_okna_kart`), „Cofnij karty”
        i „Rozwiąż teraz” z zakresu rdzenia, „Zatwierdź” milczy (karty stoją w plikach), wariant paska po
        zamknięciu i recepta gospodarza jak po sukcesie. Pole błędu nietknięte - odmowa klingi z tego
        kliknięcia zostaje. Wyjątek bez pliku tej operacji - „BŁĄD: …” w polu błędu, a „Zatwierdź” wraca,
        chyba że wcześniejszy commit czeka na „Cofnij”."""
        czesc, self._czesc = self._czesc, None
        self._porzuc_staging()
        from horreum.gui.wb_worker import czytelny_powod, zdanie_porazki_okna_kart   # zajętość słowami, bez `repr`
        porazka = (zdanie_porazki_okna_kart(czesc, czytelny_powod(msg), przycisk=i18n.t("path.undo_cards_btn"))
                   if op == "commit" else None)
        if porazka is None:
            self._domkniety = self._commit_id is not None
            self._end_progress()
            self.error.ustaw(i18n.t("grid.wb.error", msg=czytelny_powod(msg)), podpowiedz)
            self.changed.emit()
            return
        zdanie, cofnij = porazka
        if cofnij is not None:
            self._commit_id = cofnij
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
        self._domkniety = True                   # zapis ruszył pliki - ponowny trafiłby w kartę albo izolację
        self._end_progress()
        glowa = self.status.text()               # zdanie bazy tego kliknięcia (postęp kart pisze tylko pasek)
        okno = glowa + "\n" + zdanie
        self.status.ustaw(okno, podpowiedz)      # POLE zdania porażki - jedna linia (pole `error`: decyzja wyglądu)
        self.po_zamknieciu = None
        if cofnij is not None:                   # pasek po zamknięciu: polecenie CLI, wzór `_after_commit` (AR-283)
            cli = i18n.t("wb.undo_cli_short", id=cofnij)
            pasek = (glowa + "\n" + zdanie_porazki_okna_kart(czesc, czytelny_powod(msg), przycisk=cli)[0]
                     + i18n.t("wb.undo_short", cmd=cli))
            self.po_zamknieciu = _wariant_paska_kart(okno, pasek, self._db_path, cofnij)
        dopasuj_wysokosc(self)
        self.changed.emit()

    def _porzuc_staging(self):
        # Schodzą wyłącznie wpisy CZEKAJĄCE: rozstrzygnięte przerwanym zapisem (`failed` drogi atomowej -
        # na nich stoi potwierdzenie skanem, `applied`) zostają - reguła szuflady (`repo.clear_waiting_staging`).
        if self._run_id is not None:
            repo.clear_waiting_staging(self.con, run_id=self._run_id, klinga="karty")
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
        """Ogon cofnięcia kart: zdanie i regułę „czy Cofnij zostaje” daje `ogon_cofniecia` - wspólny
        z „Napraw nagłówek…” i szufladą Zbiorów (AR-160). Cofnięcie z błędem albo przerwane zostawia
        „Cofnij karty” przy TYM SAMYM commicie (ponowienie sprawdzi pozostałe pliki), a „Zatwierdź” milczy -
        część kart stoi w plikach. Nota „pliki są bez karty” mówi tylko o cofnięciu domkniętym.

        STATUS = WYNIK BIEŻĄCEGO GESTU, jak w „Napraw nagłówek…”: doklejanie każdego
        wyniku do poprzednich rosło do pięciu wierszy w oknie, które nie rośnie, i ucinało najnowszy
        wiersz z receptą przy rzędzie przycisków. Podpowiedź zapisu (spadek, powody) mówiła
        o zapisie, nie o cofnięciu - schodzi."""
        msg, ponow = ogon_cofniecia(res, i18n.t("path.undo_cards_btn"))
        # Pasek po zamknięciu okna (AR-236): bez przycisków okna - niedokończone cofnięcie ponawia
        # polecenie CLI tego commitu (krótkie w zdaniu, pełne w szczególe - AR-272), cofnięcie
        # domknięte mówi sam stan, bez obietnicy „Zatwierdź”.
        self.po_zamknieciu = (_wariant_paska_kart(
            msg, ogon_cofniecia(res, i18n.t("wb.undo_cli_short", id=self._commit_id))[0],
            self._db_path, self._commit_id) if ponow
            else (msg + i18n.t("path.cards_restored_note"),
                  msg + i18n.t(self.UWAGA_COFNIECIA), "", ""))
        if not ponow:
            msg += i18n.t("path.cards_restored_note")
            self.undo_btn.setVisible(False)
            self.resolve_btn.setVisible(False)
            self._commit_id = None
            self._domkniety = False
        # Szczegół cofnięcia: system (AR-168) i numery operacji z drogą wyjścia (AR-281).
        from horreum.gui.wb_worker import podpowiedz_cofniecia
        self.status.ustaw(msg, podpowiedz_cofniecia(res))
        self._end_progress()
        # Okno rośnie do zawiniętego zdania z receptą (AR-160, wspólny pomocnik `config_dialog`),
        # a cofnięcie to zapis - gospodarz odświeża kolejkę. Emisja stała dotąd w pomocniku
        # wysokości, więc zapis emitował dwa razy, a cofnięcie przy oknie niepokazanym - wcale.
        dopasuj_wysokosc(self)
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
    predykatem niż przebieg odmawiałaby nazw, które przebieg rozwiązuje (`Moon`, `WR134`).

    Sukces = wartość, którą drabina NAZWY rozpoznaje - dla każdej klatki tak samo. Nazwa
    obiektu-regionu (`Veil`) tu odmawia: region sprowadza klatkę ze współrzędnych, więc odpowiedź
    zależy od klatki i wyjątek regionu żyje wyłącznie w walidatorze grupy razem z bramką per klatka
    (`plan_kart_naprawy`, AR-180)."""
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
    odmowa = _odmowa_reguly_karty(value)
    if odmowa is not None:
        return None, odmowa
    if not resolver.name_resolves(con, value):
        return None, i18n.t("repair.err.unresolvable", text=raw)
    return value, None


def _odmowa_reguly_karty(value):
    """Powód odmowy reguł karty FITS dla karty `OBJECT` = `value` w języku UI albo None - jeden
    właściciel reguł (`writeback.card_violation`), dialog tylko mówi własnym językiem. Wspólne dla
    walidacji nazwy (`_validate_object_value`) i formy obiektu-regionu (`plan_kart_naprawy`)."""
    # Lazy jak `wb_worker` w dialogu: `writeback` ciągnie astropy, a dialog, który tu pyta, i tak
    # już go załadował. Dialog zapisuje kartę przez `add` - stąd `new_card=True`.
    from horreum import writeback
    naruszenie = writeback.card_violation("OBJECT", value, new_card=True)
    if naruszenie is None:
        return None
    if naruszenie.kind == "length":
        return i18n.t("repair.err.too_long", n=naruszenie.length, max=naruszenie.limit)
    if naruszenie.kind == "chars":
        return i18n.t("repair.err.ascii", text=value)
    # Nazwa karty: nieosiągalne dla stałej `OBJECT`, ale reguła ma kod - w języku UI (AR-181).
    return tekst_powodu(naruszenie.reason)


def plan_kart_naprawy(con, grupy, fakty, *, lookup=None):
    """Grupy okna „Napraw nagłówek…” → plan karty `OBJECT` per grupa, w kolejności `grupy` (AR-180):
    `(wartość | None, powód | None, frame_ids do zapisu, kanon regionu | None)` - wartość do pliku
    albo powód odmowy grupy, klatki, które kartę dostaną, i kanon obiektu-regionu (None - nazwa
    wraca drabiną nazw, karta dla każdej klatki grupy). `grupy` = `[(tekst, frame_ids)]` ZAZNACZONYCH
    grup, `fakty` = `resolver.fakty_karty_klatek` klatek okna. Zero zapisu.

    NAZWA (`_validate_object_value` - walidator nazwy bez zmian): karta dla każdej klatki grupy.
    OBIEKT-REGION: drabina nazw milczy, a tekst nazywa region (`resolver.kanon_regionu_karty`) -
    forma karty regionu (`forma_karty_object`) i bramka PER KLATKA tą samą drabiną, którą pójdzie
    przebieg (`resolver.karta_wraca`): kartę dostaje wyłącznie klatka, którą karta SAMA sprowadzi do
    regionu; reszta grupy zostaje bez karty (podgląd mówi ile), grupa bez żadnej takiej - powód.
    Węższa bramka kłamałaby o klatkach, które wrócą, szersza zapisałaby kartę, która klatki nie
    rozwiąże.

    KOLEJNOŚĆ PRZEBIEGU DLA WARIANTÓW STOSU (`run_resolver`: oryginał przed wariantem, wariant
    bierze obiekt oryginału z tego samego przebiegu): najpierw klatki bez relacji wariantu, potem
    warianty - wariant, którego oryginał dostaje kartę W TYM ZAPISIE, bierze obiekt, do którego ta
    karta oryginał sprowadzi (wraca szczeblem bliźniaka, choć sam leży poza regionem); wariant
    z oryginałem spoza zapisu - obiekt oryginału po przebiegu ze stanu bazy (`FaktyKarty.twin_canon`)."""
    lookup = lookup or resolver.alias_snapshot(con).get
    plany = []                                   # [wartość, powód, ids, region] per grupa
    przyszly = {}                                # frame_id → kanon klatki po zapisie i przebiegu
    for tekst, ids in grupy:
        value, err = _validate_object_value(con, tekst)
        if err is None:
            try:
                ident = resolver.resolve_name(lookup, value)[0]
            except ValueError:
                ident = None
            for fid in ids:
                if ident is not None:
                    przyszly[fid] = ident.canon
            plany.append([value, None, list(ids), None])
            continue
        raw = (tekst or "").strip()
        try:
            region = resolver.kanon_regionu_karty(con, raw, lookup=lookup) if con and raw else None
        except ValueError:
            region = None
        if region is None:
            plany.append([None, err, [], None])
            continue
        value = forma_karty_object(con, region) or header_form(region)
        odmowa = _odmowa_reguly_karty(value)
        plany.append([None, odmowa, [], None] if odmowa is not None else [value, None, [], region])

    def _wraca(fid, value, region, twin):
        f = fakty.get(fid)
        if f is None:                            # klatka zniknęła z bazy - karta jej nie sprowadzi
            return False
        return resolver.karta_wraca(lookup, value, region, f.ra_deg, f.dec_deg, twin_canon=twin)

    regionalne = [(plan, ids) for plan, (_t, ids) in zip(plany, grupy) if plan[3] is not None]
    for plan, ids in regionalne:                 # przejście 1: klatki bez relacji wariantu
        for fid in ids:
            f = fakty.get(fid)
            if (f is None or f.original_frame_id is None) and _wraca(fid, plan[0], plan[3], None):
                plan[2].append(fid)
                przyszly[fid] = plan[3]
    for plan, ids in regionalne:                 # przejście 2: warianty po oryginałach
        for fid in ids:
            f = fakty.get(fid)
            if f is None or f.original_frame_id is None:
                continue
            twin = przyszly.get(f.original_frame_id, f.twin_canon)
            if _wraca(fid, plan[0], plan[3], twin):
                plan[2].append(fid)
                przyszly[fid] = plan[3]
    wynik = []
    for (value, reason, zapis, region), (_t, ids) in zip(plany, grupy):
        if region is not None:
            w_zapisie = set(zapis)
            zapis = [fid for fid in ids if fid in w_zapisie]           # kolejność grupy
            if not zapis:
                reason = i18n.t_plural("repair.err.region_none", len(ids), value=repr(value),
                                       canon=region)
                value = None
        wynik.append((value, reason, tuple(zapis), region))
    return wynik


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
    # Nota cofnięcia domkniętego poza oknem (AR-296) - naprawa mówi sam stan, jak `_after_undo`.
    UWAGA_COFNIECIA = ""
    # Fakty operacji zapisu kart (`wb_worker.CzescZapisu`, AR-359) - jak w „Zatwierdź ze ścieżki…”.
    _czesc = None

    @property
    def commit_po_zamknieciu(self):
        """Commit kart do cofnięcia receptą paska po zamknięciu okna (AR-296) albo None."""
        return self._commit_id

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
        self._db_path = db_path
        self.po_zamknieciu = None   # wariant zdania `status` po zamknięciu okna (jak w „Zatwierdź ze ścieżki…”)
        self._runner = WritebackRunner(db_path, now_fn=now_fn, parent=self)
        self._runner.busy_changed.connect(self.busy_changed)   # uchwyt zna OBA końce operacji
        # Koniec biegu przelicza „Zapisz karty”: ogon cofnięcia przychodzi, gdy uchwyt
        # jest jeszcze zajęty (wątek sprząta się po `done`), więc przycisk zostawał wygaszony po
        # udanym cofnięciu. Błąd biegu (`_on_failed`) zostaje w polu błędu.
        self._runner.busy_changed.connect(
            lambda zajety: zajety or self._sync_preview(zachowaj_blad=True))
        self._groups = []       # [{folder, rows, check, edit, preview}]
        self._skipped = []      # [(path, powód)] — jawnie widoczne, nigdy ciche
        self._sumy = []         # [{label, n, reason, all}] - foldery z plikami z sumą (AR-163)
        self._fakty = {}        # frame_id → `resolver.FaktyKarty` - bramka karty regionu (AR-180)
        self.skipped_list = None   # lista pominiętych (None, gdy nic nie odpadło)
        self.setWindowTitle(i18n.t("repair.title"))
        self._split_rows(rows)
        self._build_ui()
        self._sync_preview()
        self.resize(self._rozmiar_startowy())

    def exec(self):
        """Modalny bieg i kasacja okna - wzorzec `object_change_dialog.ObjectChangeDialog.exec`
        (gospodarz nie czyta okna po `exec`; odroczona kasacja przychodzi po jego slocie)."""
        try:
            return super().exec()
        finally:
            self.deleteLater()

    def _rozmiar_startowy(self):
        """Rozmiar startowy OD TREŚCI (wizytacja: okno otwierało się 256×220 - wiersze grup za
        suwakiem, a po zapisie okno rozpychały przyciski „Cofnij”/„Rozwiąż teraz”). Szerokość:
        całe wiersze grup (podpowiedź treści listy + ramka i suwak pionowy) pod sufitem
        `_SCREEN_FRAC` dostępnego ekranu - dalej przewija lista, jak w oknach gestu ręki
        (`config_dialog.default_dialog_size`) - i nie mniej niż cały rząd przycisków ze schowanymi
        też (pojawiają się po zapisie, a ich rząd to minimum okna, którego sufit nie przebije);
        wysokość: wszystkie grupy bez suwaka, pod tym samym sufitem. Minimum okna bez zmian."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QGuiApplication
        from horreum.gui.config_dialog import _SCREEN_FRAC
        # Przed pierwszym pokazaniem układ wierszy trzyma podpowiedź sprzed `_sync_preview`
        # (zmierzone: 468 px przy wierszach 1026 px) - `activate` unieważnia układy rekurencyjnie.
        self.ensurePolished()
        self._area.widget().layout().activate()
        self.layout().activate()
        lay = self.layout()
        m = lay.contentsMargins()
        ramka = 2 * self._area.frameWidth()
        tresc = self._area.widget().sizeHint()
        przyciski = [self.save_btn, self.undo_btn, self.resolve_btn, self._close_btn]
        rzad = (sum(b.sizeHint().width() for b in przyciski)
                + self._actions.spacing() * len(przyciski))
        w = max(self.sizeHint().width(),
                tresc.width() + ramka + self._area.verticalScrollBar().sizeHint().width()
                + m.left() + m.right())
        # LISTA POMINIĘTYCH TEŻ JEST TREŚCIĄ (AR-175, wizytacja natywna): jej wpisy bywają szersze od grup
        # (zmierzone natywnie: najszerszy 673 px w widoku 541 px, poziomy suwak), a startowa szerokość
        # liczyła tylko grupy i przyciski. Pod tym samym sufitem `_SCREEN_FRAC`; suwak pionowy, gdy
        # lista nie mieści się w swoim sufitcie wysokości.
        lst = self.skipped_list
        if lst is not None:
            pion = (lst.verticalScrollBar().sizeHint().width()
                    if lst.sizeHintForRow(0) * lst.count() + 2 * lst.frameWidth() > lst.maximumHeight()
                    else 0)
            w = max(w, lst.sizeHintForColumn(0) + 2 * lst.frameWidth() + pion + m.left() + m.right())
        h = self.sizeHint().height() - self._area.sizeHint().height() + tresc.height() + ramka
        ekran = self.screen() or QGuiApplication.primaryScreen()
        if ekran is not None:
            dostepne = ekran.availableGeometry()
            if w > int(dostepne.width() * _SCREEN_FRAC):
                # Wiersze szersze niż sufit - poziomy suwak listy zabiera wiersz pionu.
                w = int(dostepne.width() * _SCREEN_FRAC)
                h += self._area.horizontalScrollBar().sizeHint().height()
            h = min(h, int(dostepne.height() * _SCREEN_FRAC))
        return QSize(max(w, rzad + m.left() + m.right()), max(h, self.sizeHint().height()))

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
        a reguła dwóch zgodnych świadków jest dla obu drzew ta sama.

        FITS Z SUMĄ KONTROLNĄ (AR-163) odpada TU, przed podglądem: pisarz go odmówi (`CHECKSUM`/
        `DATASUM`); makro też by go pominęło (AR-166), ale tu pominięcie liczy się per folder grupy -
        dawniej podgląd liczył taki plik do „Zapisz karty (N)”, a wynik mówił „2 zablokowane” bez
        folderu. Warunek ma
        jednego właściciela (`queries.fits_checksum_gate`, ten sam co bramka karty „Zmień obiekt…”),
        fakt `n_sum` niesie cel z `writeback_frame_targets`. Pominięcie liczy się PER FOLDER grupy
        (`self._sumy`): folder bez pliku do zapisu mówi „cały folder”, mieszany - ile odpadło."""
        ids = [r["frame_id"] for r in rows]
        targets = {}
        for t in queries.writeback_frame_targets(self.con, ids):
            targets.setdefault(int(t["frame_id"]), []).append(t)
        groups = {}
        sumy = {}               # folder -> {label, n, reason}: pliki z sumą kontrolną (AR-163)
        rodzaj = {}             # frame_id -> kind (drzewo świadka), poza słownikiem wiersza grupy
        korzen = resolver.library_root_from_db(self.con)   # kotwica drzewa stosów (E5-3)
        for r in rows:
            trows = targets.get(int(r["frame_id"]))
            if not trows:                       # klatka zniknęła z bazy między odczytem a otwarciem
                self._skipped.append((r["path"] or "", i18n.t("repair.skip.gone")))
                continue
            target, reason = macro_mod.resolve_target(trows)
            if target is None:
                self._skipped.append((r["path"] or "", reason or ""))
                continue
            folder = os.path.dirname(target["path"])
            if r["kind"] == STACK_KIND:
                folder = object_folder(target["path"], kind=STACK_KIND,
                                       library_root=korzen) or folder
            suma = queries.fits_checksum_gate(target)
            if suma is not None:
                wpis = sumy.setdefault(folder, {
                    "label": self._etykieta_grupy(folder, target["path"], r["kind"], korzen),
                    "n": 0, "reason": tekst_powodu(suma)})
                wpis["n"] += 1
                continue
            rodzaj[r["frame_id"]] = r["kind"]
            groups.setdefault(folder, []).append(
                dict(frame_id=r["frame_id"], path=target["path"]))
        self._sumy = [dict(w, all=folder not in groups) for folder, w in sumy.items()]
        for folder, items in groups.items():
            proposals = {resolver.path_proposal(self.con, it["path"], kind=rodzaj[it["frame_id"]])
                         for it in items}
            common = proposals.pop() if len(proposals) == 1 else None
            self._groups.append({"folder": folder, "rows": items, "proposal": common,
                                 "label": self._etykieta_grupy(folder, items[0]["path"],
                                                               rodzaj[items[0]["frame_id"]],
                                                               korzen)})
        # Fakty bramki karty regionu (AR-180): współrzędne i oryginał wariantu - raz na okno, bo
        # podgląd przelicza plan przy każdym klawiszu.
        self._fakty = resolver.fakty_karty_klatek(
            self.con, [it["frame_id"] for g in self._groups for it in g["rows"]])

    def _plan_zapisu(self):
        """Plan karty ZAZNACZONYCH grup → `{id(grupy): plan}` (`plan_kart_naprawy`) - JEDNA reguła
        dla podglądu i zapisu: zbiór klatek do zapisu zależy od wszystkich grup naraz (wariant
        stosu idzie za oryginałem z innej grupy okna)."""
        zaznaczone = [g for g in self._groups if g["check"].isChecked()]
        plany = plan_kart_naprawy(
            self.con, [(g["edit"].text(), [it["frame_id"] for it in g["rows"]]) for g in zaznaczone],
            self._fakty)
        return {id(g): p for g, p in zip(zaznaczone, plany)}

    @staticmethod
    def _etykieta_grupy(folder, path, kind, korzen):
        """Etykieta grupy OD FOLDERU OBIEKTU (`resolve.paths.object_folder`, jak grupa stosu):
        `NGC7635\\RC8_2600MC\\OSC`, nie sam rodzic pliku. Grupa lightów to folder pliku (zestaw,
        filtr), więc sam rodzic dawał etykiety `OSC`/`Ha` jednakowe dla każdego obiektu (zrzut
        natywny: cztery grupy „OSC”). Folder poza pozycją obiektu (układ WBPP) - nazwa folderu,
        jak dotąd; pełna ścieżka w podpowiedzi."""
        obiekt = object_folder(path, kind=kind, library_root=korzen)
        if obiekt and folder[:len(obiekt)].casefold() == obiekt.casefold():
            return os.path.relpath(folder, os.path.dirname(obiekt))
        return os.path.basename(folder)

    # ---------------------------------------------------------------- budowa UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        n_frames = sum(len(g["rows"]) for g in self._groups)
        head = QLabel(i18n.t_plural("repair.head", n_frames,          # odmiana obu liczb
                                    groups=i18n.t_plural("repair.head_groups", len(self._groups))))
        head.setWordWrap(True)
        lay.addWidget(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        self._area = area                    # rozmiar startowy od treści (`_rozmiar_startowy`)
        inner = QWidget()
        gl = QVBoxLayout(inner)
        for g in self._groups:
            row = QHBoxLayout()
            g["check"] = QCheckBox(i18n.t_plural("repair.group", len(g["rows"]),
                                                 folder=g["label"]))
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

        n_pominiete = len(self._skipped) + sum(s["n"] for s in self._sumy)
        if n_pominiete:
            lay.addWidget(QLabel(i18n.t("repair.skipped_head", n=n_pominiete)))
            lst = QListWidget()
            self.skipped_list = lst
            for s in self._sumy:                # sumy kontrolne per folder grupy (AR-163)
                if s["all"]:
                    lst.addItem(i18n.t_plural("repair.skip.checksum_all", s["n"],
                                              folder=s["label"], reason=s["reason"]))
                else:
                    lst.addItem(i18n.t_plural("repair.skip.checksum", s["n"],
                                              folder=s["label"], reason=s["reason"]))
            for path, reason in self._skipped:
                # Powód bramki celu z kodem (AR-181) w języku UI - kluczem katalogu, nie f-stringiem.
                lst.addItem(i18n.t("repair.skip.item",
                                   file=os.path.basename(path) or i18n.t("object.no_location"),
                                   reason=tekst_powodu(reason)))
            lst.setMaximumHeight(90)
            lay.addWidget(lst)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = EtykietaBledu("")     # zdanie wyniku + szczegół (protokół pola, AR-204)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)   # `commit_id` do skopiowania
        lay.addWidget(self.status)
        self.error = EtykietaBledu("")      # szczegół systemu awarii znika z następnym zdaniem (AR-185)
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
        self._actions, self._close_btn = actions, close_btn
        # ENTER NIE PISZE DO PLIKÓW: `QDialog` robi przycisk z fokusem domyślnym (`autoDefault`),
        # więc Enter w polu nazwy grupy uruchamiał „Zapisz karty (N)”.
        # Domyślny jest „Zamknij” - wzór `object_change_dialog.ObjectChangeDialog._build_ui`.
        for btn in (self.save_btn, self.undo_btn, self.resolve_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        close_btn.setDefault(True)

    # ---------------------------------------------------------------- podgląd „co wpiszemy"
    def _sync_preview(self, *, zachowaj_blad=False):
        """Podgląd DOKŁADNIE tego, co pójdzie do pliku (`OBJECT = 'NGC7635'`), plus szczery stan
        akcji. Grupa zaznaczona z niepoprawną wartością pokazuje powód przy sobie - user nie musi
        klikać, żeby dowiedzieć się, czemu zapis nie ruszy. Nazwa obiektu-regionu (AR-180) wraca
        tylko części grupy: podgląd mówi „k z n klatek”, podpowiedź - ile zostaje bez karty i czemu;
        przycisk liczy wyłącznie klatki, które kartę dostaną (`_plan_zapisu`, ta sama reguła co
        zapis). `zachowaj_blad` - przeliczenie po końcu biegu (wejście się nie zmieniło): błąd biegu
        zostaje, chyba że podgląd ma własny."""
        ready, first_err = 0, None
        plany = self._plan_zapisu()
        for g in self._groups:
            g["preview"].setToolTip("")
            if not g["check"].isChecked():
                g["preview"].setText("")
                continue
            value, err, ids, region = plany[id(g)]
            if err:
                g["preview"].setText(i18n.t("repair.preview_none"))
                first_err = first_err or i18n.t("repair.err.group", folder=g["label"], reason=err)
                continue
            n = len(g["rows"])
            if len(ids) < n:
                g["preview"].setText(i18n.t_plural("repair.preview_part", n, value=repr(value),
                                                   k=len(ids)))
                g["preview"].setToolTip(i18n.t_plural("repair.region_outside_tip", n - len(ids),
                                                      value=repr(value), canon=region))
            else:
                g["preview"].setText(i18n.t("repair.preview", value=repr(value)))
            ready += len(ids)
        if first_err is not None or not zachowaj_blad:
            self.error.setText(first_err or "")  # wejście się zmieniło → stary błąd nieaktualny
        # Po udanym commicie zapis MILCZY do czasu cofnięcia: karty są już w plikach, więc drugie
        # kliknięcie dałoby tylko listę „karta już istnieje" — szczery disabled zamiast pustego biegu.
        self.save_btn.setEnabled(ready > 0 and first_err is None and not self._committed
                                 and not self._runner.is_busy)
        # Licznik mówi, ile ZOSTAŁO do zapisania — nie ile BYŁO gotowe. Po commicie zostaje zero,
        # więc liczba znika razem z sensem drugiego kliknięcia; zamrożone „Zapisz karty (23)"
        # pod wygaszonym przyciskiem opisywało przeszłość (firsthand pilota P-D na `R:`).
        self.save_btn.setText(i18n.t("repair.save_btn_n", n=ready)
                              if ready and not self._committed else i18n.t("repair.save_btn"))

    def _fail(self, msg, szczegol=""):
        self.error.ustaw(msg, szczegol)          # zdanie + szczegół (protokół pola, AR-204)
        dopasuj_wysokosc(self)                   # błąd też zawija (AR-176)

    # ---------------------------------------------------------------- takt 1+2: staging + commit
    def _on_save(self):
        """Staging i commit JEDNYM taktem. Walidacja WSZYSTKICH zaznaczonych grup PRZED
        jakimkolwiek zapisem — częściowy staging po odmowie zostawiłby otwarty run."""
        if self._runner.is_busy:
            return
        self.error.clear()
        plan = []
        plany = self._plan_zapisu()              # ta sama reguła co podgląd (AR-180)
        for g in self._groups:
            if not g["check"].isChecked():
                continue
            value, err, ids, _region = plany[id(g)]
            if err:
                return self._fail(i18n.t("repair.err.group", folder=g["label"], reason=err))
            plan.append((g, value, list(ids)))
        if not plan:
            return self._fail(i18n.t("repair.err.nothing"))

        run_id = uuid.uuid4().hex
        staged, skipped = 0, []
        for g, value, do_zapisu in plan:
            # `repr(value)` — bo `expr` traktuje gołe `NGC7635` jak NAZWĘ ZMIENNEJ (przy kolizji
            # z keywordem wpisalibyśmy WARTOŚĆ TEJ KARTY), a sam cudzysłów nie wystarcza: kanon
            # z apostrofem wysadza kompilację i makro wpisałoby surową zawartość pola razem
            # z cudzysłowami. Python dobiera cudzysłów i escape sam.
            md = macro_mod.MacroDef(assign=macro_mod.Assign(
                keyword="OBJECT", op="add", expr=repr(value), value_type="str"))
            # Klatki z planu grupy: przy obiekcie-regionie tylko te, które karta sama sprowadzi.
            run = macro_mod.run_macro(
                md, do_zapisu,
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
            return self._fail(i18n.t("repair.err.all_skipped",   # powód makra w języku UI
                                     reason=tekst_powodu(skipped[0][1] if skipped else "")))

        self._run_id = run_id
        self._begin_progress(staged)
        # Karta W MIEJSCU (AR-117) - ten sam powód i ta sama operacja co w „Zatwierdź ze ścieżki…"; fakty zapisu
        # (`on_partial`, AR-359) - „Cofnij” z zakresu rdzenia.
        self._czesc = None
        self._runner.start("commit", run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed, on_partial=self._na_czesc)

    def _na_czesc(self, op, czesc):
        """Fakty operacji zapisu kart od wykonawcy (AR-359) - przed `_after_commit`; metoda okna (kolejka z wątku tła)."""
        self._czesc = czesc

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
        # Nazwa pliku to jedno długie słowo - skrócona do szerokości etykiety, inaczej rozpycha
        # okno (`object_change_dialog.tekst_postepu`).
        from horreum.gui.object_change_dialog import tekst_postepu
        self.status.setText(tekst_postepu(self.status, done, total, os.path.basename(path)))

    def _after_commit(self, op, res):
        """Post-processing commitu (wątek główny). Plik podmieniony → jednorazowe „Cofnij" + „Rozwiąż
        teraz"; `commit_id` WIDOCZNY, bo po zamknięciu okna to jedyny uchwyt do cofnięcia z ręki.
        Zdanie i regułę „kiedy wolno cofnąć" daje `zdanie_commitu_kart` - wspólne z oknem
        „Zatwierdź ze ścieżki…" (C4: także `failed` z kopią nagłówka ma „Cofnij"), z faktów wykonawcy (AR-359):
        przerwany zapis w miejscu bez „Cofnij” (droga odzysku w zdaniu), podmiana niepotwierdzona z „Cofnij” i członem
        „do sprawdzenia”; „Zapisz karty” milczy, dopóki zapis ruszył plik."""
        self.bar.setVisible(False)
        czesc, self._czesc = self._czesc, None
        summary, cofnij = zdanie_commitu_kart(res, "grid.wb.applied", czesc, przycisk=i18n.t("grid.action.undo"))
        if cofnij is not None:
            self._commit_id = cofnij
            self.undo_btn.setVisible(True)
            self.resolve_btn.setVisible(True)
        if cofnij is not None or res.commit_id is not None or (czesc is not None and czesc.zakres is not None):
            self._committed = True               # zapis ruszył plik - ponowny trafiłby w izolację albo w kartę
        if res.cancelled or cofnij is None:
            self._porzuc_staging()               # reszta runu to sierota - nikt jej nie dokończy
        self._run_id = None                      # run domknięty commitem (R#5) - nie kasuj przy zamknięciu
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()
        # Spadek na drogę atomową zdanie mówi językiem człowieka; szczegół rdzenia - pod kursorem,
        # razem z pozostałymi powodami (okno nie ma listy pozycji) - protokół pola (AR-204).
        self.status.ustaw(summary, podpowiedz_kart(res))
        if cofnij is not None:                   # pasek po zamknięciu: polecenie cofnięcia (AR-283)
            # Po zamknięciu przycisku okna nie ma - człony zdania nazywają polecenie CLI (wzór `_after_undo`).
            cli = i18n.t("wb.undo_cli_short", id=cofnij)
            pasek = zdanie_commitu_kart(res, "grid.wb.applied", czesc, przycisk=cli)[0]
            self.po_zamknieciu = _wariant_paska_kart(
                summary, pasek + i18n.t("wb.undo_short", cmd=cli), self._db_path, cofnij)
        # STATUS UCINAŁ SIĘ (AR-176, zmierzone natywnie): przy jednej grupie zdanie z trzema powodami
        # dostawało 44 px przy potrzebnych 64 - okno nie rosło. Wysokość PRZED emisją `changed`
        # (gospodarz odświeża po niej kolejkę).
        dopasuj_wysokosc(self)
        self.changed.emit()

    def _on_failed(self, op, msg, podpowiedz):
        """Wyjątek workera: staging runu jest sierotą (C1) - sprzątany od razu, nie przy zamknięciu.
        Szczegół systemu (`podpowiedz`, AR-185) - razem ze zdaniem (protokół pola AR-204); następne zdanie
        pola go zdejmuje. Fakty tej operacji (`_na_czesc`, AR-359) zużywa ta porażka.

        WYJĄTEK ZAPISU PO PODMIANIE (AR-384; wyłącznie `op` `commit` - ten odbiorca łapie też porażkę
        cofnięcia): zdanie jak w szufladzie z faktów wykonawcy (`zdanie_porazki_okna_kart`), „Cofnij”
        i „Rozwiąż teraz” z zakresu rdzenia, „Zapisz karty” milczy (`_committed` - karty stoją w plikach),
        wariant paska po zamknięciu i recepta gospodarza jak po sukcesie; zdanie zastępuje w `status`
        postęp ostatniego pliku. Wyjątek bez pliku tej operacji - „BŁĄD: …” w polu błędu (`_fail`)."""
        czesc, self._czesc = self._czesc, None
        self._porzuc_staging()
        from horreum.gui.wb_worker import czytelny_powod, zdanie_porazki_okna_kart   # zajętość słowami, bez `repr`
        porazka = (zdanie_porazki_okna_kart(czesc, czytelny_powod(msg), przycisk=i18n.t("grid.action.undo"))
                   if op == "commit" else None)
        if porazka is not None:
            zdanie, cofnij = porazka
            if cofnij is not None:
                self._commit_id = cofnij
                self.undo_btn.setVisible(True)
                self.resolve_btn.setVisible(True)
            self._committed = True               # PRZED `_sync_preview`: ten liczy „Zapisz karty”
        self.bar.setVisible(False)
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()                     # PRZED zdaniem: podgląd czyści pole błędu
        if porazka is None:
            self._fail(i18n.t("grid.wb.error", msg=czytelny_powod(msg)), podpowiedz)
            self.changed.emit()
            return
        self.status.ustaw(zdanie, podpowiedz)    # POLE zdania porażki - jedna linia (pole `error`: decyzja wyglądu)
        self.po_zamknieciu = None
        if cofnij is not None:                   # pasek po zamknięciu: polecenie CLI, wzór `_after_commit` (AR-283)
            cli = i18n.t("wb.undo_cli_short", id=cofnij)
            pasek = (zdanie_porazki_okna_kart(czesc, czytelny_powod(msg), przycisk=cli)[0]
                     + i18n.t("wb.undo_short", cmd=cli))
            self.po_zamknieciu = _wariant_paska_kart(zdanie, pasek, self._db_path, cofnij)
        dopasuj_wysokosc(self)
        self.changed.emit()

    def _porzuc_staging(self):
        # Schodzą wyłącznie wpisy CZEKAJĄCE: rozstrzygnięte przerwanym zapisem (`failed` drogi atomowej -
        # na nich stoi potwierdzenie skanem, `applied`) zostają - reguła szuflady (`repo.clear_waiting_staging`).
        if self._run_id is not None:
            repo.clear_waiting_staging(self.con, run_id=self._run_id, klinga="karty")
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
        """Ogon cofnięcia: zdanie z powodem i reguła „czy Cofnij zostaje” z `ogon_cofniecia` (AR-160,
        wspólne z „Zatwierdź ze ścieżki…” i szufladą Zbiorów). Błąd albo przerwanie zostawia
        „Cofnij” przy tym samym commicie, a zapis milczy - karty części plików wciąż stoją."""
        self.bar.setVisible(False)
        msg, ponow = ogon_cofniecia(res, i18n.t("grid.action.undo"))
        # Pasek po zamknięciu okna (AR-236): „Cofnij” już nie ma - niedokończone cofnięcie ponawia
        # polecenie CLI tego commitu (ten sam ogon, krótkie polecenie w miejscu etykiety przycisku,
        # pełne w szczególe - AR-272).
        self.po_zamknieciu = (_wariant_paska_kart(
            msg, ogon_cofniecia(res, i18n.t("wb.undo_cli_short", id=self._commit_id))[0],
            self._db_path, self._commit_id) if ponow else (msg, msg, "", ""))
        if not ponow:
            self.undo_btn.setVisible(False)      # commit ZUŻYTY - drugi undo nie ma czego cofać
            self.resolve_btn.setVisible(False)
            self._commit_id = None
            self._committed = False              # karty zdjęte → zapis znów ma sens
        self.undo_btn.setEnabled(True)
        self.resolve_btn.setEnabled(True)
        self._sync_preview()
        # Szczegół spadku mówił o zapisie - zostaje szczegół systemu cofnięcia (AR-168) i numery operacji
        # z drogą wyjścia (AR-281) albo nic.
        from horreum.gui.wb_worker import podpowiedz_cofniecia
        self.status.ustaw(msg, podpowiedz_cofniecia(res))
        dopasuj_wysokosc(self)                   # zdanie z receptą zawija (AR-176), przed `changed`
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


class _Odlozona:
    """Wpis kolejki odłożonych recept osi (AR-296, AR-310, AR-321) - DANE zamiaru, nie domknięcie: `klucz`
    (`("karty", commit)` / `("dopisanie", teleskop)`), `zapis_plikow` (czeka też na koniec zapisu do plików),
    `argumenty` (reszta zamiaru), `czeka` - bieg blokady, którego koniec wpis podaje: `(rodzaj, numer)`, rodzaj
    `"etap"` (bieg Dostawy) albo `"zapis"` (zapis do plików Zbiorów), numer z `_NUMERY_BLOKAD`, i `podany` - koniec
    blokady, otwarcie bazy albo zdjęcie podanej głowy przed nim (aktywacja okna, Oś teleskopu - AR-355,
    `ObjectAxisView.podaj_odlozone`) już go podały; potem podaje go wyłącznie wejście w Porządki i ogon gestu z recepty
    (`ObjectAxisView._podaj_odlozone`). `recepta` - obiekt recepty z ostatniego podania, a `przed` - zdanie, do którego
    dokleiło ono gotowość (wynik gestu, raport Porządków, `None`): wpis, któremu baza nic nie zostawiła, rozpoznaje po
    nich swoją receptę na pasku gospodarza (`ObjectAxisView.oczysc_martwe`, po tożsamości obiektu).

    `tozsamosc` (AR-336) - tożsamość ZAMIARU z bazy w chwili odłożenia: karty - `commits.run_id` commitu (uuid4 klingi,
    `queries.przebieg_commitu`), dopisanie - `(first_event_id, created_at)` otwartego śladu gestu (`queries.slad_dopisania`).
    Kolejka jest kluczowana ścieżką bazy, a plik podmieniony pod tą samą ścieżką inną biblioteką ma te same numery commitów
    i teleskopów - wpis żyje (`ObjectAxisView._zywy`) wyłącznie w bazie z tym samym zamiarem. ZAŁOŻENIE dla dopisania: obca
    biblioteka ma ten sam ślad tylko przy tym samym numerze teleskopu, tym samym numerze zdarzenia dziennika i tej samej
    mikrosekundzie zegara gestu - osiągalne tylko stałym zegarem (test); kopia TEJ SAMEJ biblioteki dzieli zamiar
    (poprawnie żyje)."""
    __slots__ = ("klucz", "zapis_plikow", "argumenty", "czeka", "tozsamosc", "podany", "recepta", "przed")

    def __init__(self, klucz, zapis_plikow, argumenty, czeka, tozsamosc):
        assert czeka[0] in ("etap", "zapis") and czeka[1] is not None, czeka
        self.klucz = klucz
        self.zapis_plikow = zapis_plikow
        self.argumenty = argumenty
        self.czeka = czeka
        self.tozsamosc = tozsamosc
        self.podany = False
        self.recepta = None
        self.przed = None


# Numery biegów blokad osi obiektu (`ObjectAxisView._blokady`) - wspólne dla procesu, więc wpis kolejki, który przeżył
# przemontowanie widoków (AR-321), nie trafi na bieg nowego widoku o tym samym numerze.
_NUMERY_BLOKAD = itertools.count(1)


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

    # Kubełki OSI OBIEKTU w kolejce przeglądu - klatki bez obiektu, które wiersz Porządków „Klatki bez
    # obiektu" liczy (nazwy z nagłówka, bez nazwy, RAW, stosy, propozycje ze ścieżki i ich połówki
    # cofnięte). Złożone z właścicieli dróg naprawy (ręka, karta), bez trzeciej wyliczanki.
    KUBELKI_OSI_OBIEKTU = _ASSIGN_TAGS | _CARD_TAGS | frozenset({"path_proposals"})

    # `str` albo `ZdanieZeSzczegolem` - zdanie okna „Zatwierdź ze ścieżki…” ze szczegółem po jego
    # zamknięciu (AR-218); `object`, bo `Signal(str)` gubi podklasę (jak `FramesView.status_message`).
    status_message = Signal(object)
    writeback_busy = Signal(bool)         # okno naprawy pisze do plików → mutex gridu (D-PD-3)
    # Gest „Przypisz zestaw…" zmienia oś TELESKOPU: liczbę klatek, wartość z plików, a „Dopisz
    # nowy…" dokłada wiersz (wizytacja N4) - gospodarz odświeża nią Oś teleskopu.
    telescope_axis_changed = Signal()
    # Recepta paska po geście osi (`grid_model.Recepta` z wykonawcą) - „Cofnij dopisanie” po „Dopisz
    # nowy…” (AR-133). Pada PO `status_message`, bo raport gasi receptę poprzedniego gestu.
    status_recipe = Signal(object)
    # Zdanie biegu cofnięcia zapisu kart z paska (AR-296) i recepta, która mu towarzyszy (`Recepta` albo
    # None) - JEDNĄ emisją: gospodarz stawia zdanie na pasku bez odkładania do Porządków i wiąże z nim
    # receptę (`MainWindow._wynik_cofniecia_osi`).
    wynik_cofniecia = Signal(object, object)
    # (recepta, przed) wpisu kolejki odłożeń, któremu baza nie zostawiła nic do wykonania (gest zamknięty inną drogą):
    # gospodarz zdejmuje tę receptę z paska i swojego stanu (`MainWindow._zdejmij_martwa_recepte`), AR-321.
    recepta_martwa = Signal(object, object)

    def __init__(self, con, now_fn=_utc_now_iso, parent=None, *, leniwie=False):
        """`leniwie=True` (podstrona Porządków przy montażu w trybie wątków tła, AR-175): bez odczytu
        kolejki i biblioteki w konstruktorze - znacznik `_nieaktualny` i odczyt przy pierwszym
        pokazaniu (`showEvent`, ta sama droga co `odswiez_gdy_widoczny`). Domyślnie jak dotąd: widok
        czyta bazę od razu."""
        super().__init__(parent)
        self.con = con
        self._now = now_fn
        self._busy = False                    # pipeline w biegu → akcja zapisu wygaszona
        self._foreign_wb = False              # DRUGA powierzchnia writebacku pisze (mutex, D-PD-3)
        # Bieżący bieg każdej blokady odkładającej recepty osi - `(rodzaj, numer)`, `None` poza biegiem (`_odloz`,
        # `_koniec_blokady`): koniec biegu podaje wyłącznie wpisy, które odłożył TEN bieg.
        self._blokady = {"etap": None, "zapis": None}
        self._copies_mode = False             # prawy panel w trybie „kopie" (Z6)
        self._loading = False                 # tłumi sygnały selekcji podczas programowego wypełniania
        # Otwarte okno piszące karty do plików: „Napraw nagłówek…" albo „Zatwierdź ze ścieżki…"
        # (modalne - poza zasięgiem `set_busy`, więc bieg pipeline'u przekazujemy mu wprost).
        self._repair_dlg = None
        self._naprawa_zmienila = False        # okno naprawy zgłosiło koniec biegu (`changed`, AR-236)
        self._sciezka_zmienila = False        # …i okno „Zatwierdź ze ścieżki…” (AR-283)
        # Cofnięcie commitu kart z paska po zamknięciu okna (AR-296): uchwyt zapisu tego widoku
        # (leniwy - `wb_worker` ciągnie astropy), generacja callbacków (podbija ją demontaż widoku,
        # `zatrzymaj_pola`) i flaga biegu z SYGNAŁU uchwytu - uchwyt ogłasza start, ZANIM ustawi
        # swój wątek, więc `is_busy` w slocie startu mówiłby jeszcze „wolny” (wzór `FramesView`).
        self._wb_kart = None
        self._gen_kart = 0
        self._bieg_kart = (-1, None, "", False)   # (generacja, commit, nota, dokończenie) biegu
        # JEDNO odłożenie recept osi (AR-296, AR-310): kolejka FIFO wpisów `_Odlozona` odmówionych w biegu
        # blokady; zdanie i receptę składa przy podaniu BIEŻĄCY widok (`_gotowosc`), pytając bazę, czy zamiar ma
        # jeszcze co wykonać. Wpis to DANE, nie domknięcie (AR-321): kolejka należy do gospodarza i tej bazy
        # (`uzyj_kolejki`) i przeżywa przemontowanie widoków, a recepta związana ze starym widokiem wykonałaby się
        # na zamkniętym połączeniu. Widok bez gospodarza ma własną listę. Wpis schodzi z kolejki przy starcie
        # swojego gestu (`zdejmij_odlozona`), przy zamknięciu gestu drogą trwałą w tym oknie (Oś teleskopu - przez
        # gospodarza) i po cichu przy podaniu, gdy baza mówi, że nie ma już czego cofać (wiersz Porządków, CLI).
        # Podany, a zgaszony bez kliku, wraca przy wejściu w Porządki - doklejony do odłożonego tam raportu.
        self._odlozone = []
        # Straż stojącej recepty (AR-321): gospodarz mówi, czy na pasku stoi recepta, którą ktoś czyta - podanie
        # z końca blokady jej nie nadpisuje. Widok bez gospodarza - nic nie stoi.
        self.recepta_stoi = lambda: False
        self._zapis_kart_trwa = False
        # Takt 3 (`Rozwiąż`) należy do Dostawy: gospodarz wstrzykuje wywołanie ISTNIEJĄCEJ,
        # bramkowanej drogi (`PipelineView.run_stage`). None = widok bez gospodarza (testy samego
        # widoku) → okno naprawy powie wprost, że taktu 3 nie ma stąd jak uruchomić.
        self.run_stage_fn = None
        # Stan bazy zmienił się poza tym widokiem, gdy go nie było widać (`odswiez_gdy_widoczny`):
        # przeładowanie czeka na pokazanie (`showEvent`), a każde `refresh` znacznik zdejmuje.
        self._nieaktualny = False
        self._build_ui()
        self._load_facets()
        if leniwie:
            self._nieaktualny = True
        else:
            self.refresh()

    def odswiez_gdy_widoczny(self):
        """Gest Zbiorów zmienił oś obiektu (`FramesView.object_axis_changed`): widoczny widok
        przeładowuje się od razu, niewidoczny dostaje znacznik i przeładowuje się przy pokazaniu.

        LENIWIE, BO TO BYŁ NAJWIĘKSZY PRZESTÓJ PO GEŚCIE (AR-84): po przeniesieniu składu zbioru
        i liczników Porządków w tło zostało tu ~0,4 s na wątku GUI po każdym geście osi obiektu
        (zmierzone na kopii pf4), a widoku w tym czasie nie widać - gest pada w Zbiorach.
        Punktem odświeżenia jest `showEvent`, nie wejście z listy Porządków: na podstronę prowadzi
        kilka dróg (wiersz zadania, kubełek z raportu Dostawy `_on_kubelek_porzadkow`, powrót przez
        sidebar na stronę, która już stała na tej podstronie), a pokazanie łapie każdą z nich -
        ekran nie pokaże stanu sprzed gestu żadną drogą."""
        if self.isVisible():
            self.refresh()
        else:
            self._nieaktualny = True

    def showEvent(self, event):
        """Pokazanie przy postawionym znaczniku przeładowuje widok PO OBROCIE PĘTLI: droga wejścia,
        która sama przeładowuje kolejkę (kubełek z wiersza Porządków albo z raportu Dostawy,
        `_zaznacz_kubelek`), robi to zaraz po przełączeniu strony i znacznik schodzi - bez
        drugiego przeładowania tego samego stanu."""
        super().showEvent(event)
        if self._nieaktualny:
            QTimer.singleShot(0, self, self._odswiez_jesli_nieaktualny)

    def _odswiez_jesli_nieaktualny(self):
        if self._nieaktualny and self.isVisible():
            self.refresh()

    def zaznacz_pierwszy_kubelek(self, tagi):
        """Wejście na podstronę z wiersza Porządków: zaznacz PIERWSZY niepusty kubełek kolejki o tagu
        z `tagi` - zaznaczenie drąży jego klatki i zapala gest (`_on_review_selected`). Bez tego
        podstrona zaznaczała pierwszy obiekt biblioteki (np. kometę z 4 klatkami), a do klatek z kolejki
        trzeba było kliknąć wiersz kolejki: trzy interakcje zamiast dwóch. Kubełek pusty nie ma tagu
        (wiersz informacyjny), więc pierwszy z tagiem jest pierwszym niepustym; brak takiego =
        nic się nie zaznacza (`False`).

        KOLEJKA PRZEŁADOWANA TYLKO PRZY ZNACZNIKU (`odswiez_gdy_widoczny`, AR-84): gest, który zmienił
        oś, postawił znacznik, więc kolejka bez niego mówi stanem bazy - wejście bez nowego gestu
        nie liczy jej drugi raz. Zaznaczenie zdejmowane przed ustawieniem, żeby drążenie poszło także
        przy kubełku już zaznaczonym."""
        if self._nieaktualny:
            self.refresh()
        for i in range(self.review.count()):
            if self.review.item(i).data(_REVIEW_TAG) in tagi:
                self.review.clearSelection()
                self.review.setCurrentRow(i)
                return True
        return False

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # --- pasek filtra ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("filter.telescope")))
        self.combo_tel = kolko(QComboBox())
        self.combo_tel.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.combo_tel)
        bar.addWidget(QLabel(i18n.t("filter.filter")))
        self.combo_filter = kolko(QComboBox())
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
        self._nieaktualny = False                     # stan z bazy - znacznik `odswiez_gdy_widoczny` schodzi
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
                count=i18n.t_plural(
                    "object.path_proposed_count", q["path_proposed_names"],
                    frames=i18n.t_plural("object.review_count", q["path_proposed_frames"])),
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
                count=i18n.t_plural(
                    "object.path_proposed_count", q["path_proposed_stack_names"],
                    frames=i18n.t_plural("object.review_count", q["path_proposed_stack_frames"])),
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
        # Zdanie z modułu bez Qt (AR-356): import modułu Dostawy tutaj ładował go przechodnio każdemu
        # wejściu w Porządki, omijając bramkę „Porządki bez modułu Dostawy” (`tests/test_dostawa_bramka.py`).
        from horreum.gui import dostawa_bramka     # lazy jak reszta importów modułów stron
        self._add_review_item(i18n.t("object.unreadable_line"),
                              count=i18n.t_plural("object.review_count", q["unreadable_count"]),
                              tag="unreadable" if q["unreadable_count"] > 0 else None,
                              info=i18n.t("object.unreadable_info_empty"),
                              tip=dostawa_bramka.unreadable_kinds_text(resolver.unreadable_kind_counts(self.con))
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
        # OGNISKOWA NIEZGODNA Z TELESKOPEM (AR-128, D-1012-2 `Q8`) - trzecia populacja osi sprzętu:
        # zestaw jest, ale z automatu, a ogniskowa w pliku odbiega od teleskopu ponad tolerancję.
        # Program nie zakłada teleskopu sam; wybór należy do ręki. Przy zerze wiersz zostaje jako
        # INFORMACYJNY ze zdaniem o sobie (wizytacja N20): klik z Porządków w „0" trafiał na podstronę
        # bez zaznaczenia i z podpowiedzią cudzego kubełka.
        self._add_review_item(
            i18n.t("object.config_focal_line"),
            count=i18n.t_plural("object.review_count", q["focal_mismatch_count"]),
            tag="config_focal" if q["focal_mismatch_count"] > 0 else None,
            info=i18n.t("object.config_focal_info_empty"))
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

        Bliźniak `tasks._fit_task_list`, ale z innym sednem: tam sufit = cała treść, a podłoga
        w wierszach (`tasks._LISTA_ZADAN_MIN_WIERSZY`) chroni podłogę okna przed wzrostem z każdym
        wierszem Porządków (AR-188); tu kolejka przeglądu rośnie do ~45 i pod nią stoi tabela
        „Biblioteka" - dopasowanie bez sufitu zabrałoby jej cały pion, czyli zamieniło jeden dług
        na drugi. Stąd `setMaximumHeight` (nie `setFixedHeight`) i suma po `_KOLEJKA_SUFIT_WIERSZY`
        wierszach: krótka kolejka nie zostawia pustki, długa dostaje pasek przewijania.

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
            it.setData(ROLA_RODZAJU_KOLORU, _RODZAJ_SZARY)
            powod = info or i18n.t("object.review_info_generic")
            it.setData(_REVIEW_INFO, powod)
            it.setToolTip(powod)
        if fg is not None:
            it.setForeground(fg)
            # Rodzaj koloru (AR-175) - `odswiez_motyw` przemalowuje z niego. Wołający podają dziś
            # wyłącznie kolor werdyktu; inny kolor zostaje wypalony, jak był.
            it.setData(ROLA_RODZAJU_KOLORU, _RODZAJ_WERDYKT if fg == _WERDYKT["fg"] else None)
        self.review.addItem(it)

    def odswiez_motyw(self):
        """Zmiana motywu (gospodarz, `MainWindow._on_theme`, AR-175): szarość wierszy bez drogi i kolor
        werdyktu ręki z ROLI rodzaju zapisanej przy budowie (`_add_review_item`) - bez `review_queue`,
        które `_on_theme` liczył dotąd tylko po to, żeby wypalić nowe kolory (0,35-0,46 s na kopii pf4).
        Lista jeszcze nie wczytana (odczyt odłożony do pokazania) nie ma czego przemalować."""
        for i in range(self.review.count()):
            it = self.review.item(i)
            pedzel = _pedzel_rodzaju(it.data(ROLA_RODZAJU_KOLORU))
            if pedzel is not None:
                it.setForeground(pedzel)

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
        # Cofnięcie z paska tego widoku (AR-296) pisze do plików jak okno - te same dwa przyciski gasną.
        zapis_plikow = self._foreign_wb or self._zapis_kart_trwa
        self.repair_btn.setEnabled(tag in _CARD_TAGS
                                   and not self._busy and not zapis_plikow)
        # Potwierdzanie propozycji pisze do BAZY i (od O3 kroku 1) kartę `OBJECT` do PLIKÓW - więc
        # mutex writebacku (`_foreign_wb`, D-PD-3) dotyczy go tak samo jak „Napraw nagłówek…".
        self.confirm_path_btn.setEnabled(tag == "path_proposals"
                                         and not self._busy and not zapis_plikow)
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
            else "object.set_config_tip_focal" if tag == "config_focal"
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
            "wb.undo_recipe_tip_busy" if self._zapis_kart_trwa and tag in _CARD_TAGS
            else "repair.tip_busy" if self._foreign_wb and tag in _CARD_TAGS
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
        elif tag in _CONFIG_TAGS:
            # Drążenie pokazuje KLATKI, a jednostkę gestu — folder × kamerę — pokazuje dopiero
            # okno (lustro `path_proposals` wyżej: tam jednostką jest nazwa). Read-model jest
            # LUSTREM licznika kubełka i test pinuje tę równość. Trzy tagi, bo trzy ROZŁĄCZNE
            # populacje (bez zestawu / z zestawem od ręki / ogniskowa niezgodna z teleskopem).
            self._restore_frames_mode()
            rows, klucz = {
                "config_by_hand": (queries.config_by_hand_frames, "object.frames_config_by_hand"),
                "config_focal": (queries.focal_mismatch_frames, "object.frames_config_focal"),
                "config_review": (queries.config_review_frames, "object.frames_config_review"),
            }[tag]
            rows = rows(self.con)
            self.frames_label.setText(i18n.t(klucz, n=len(rows)))
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
                           i18n.t_plural("busy.saving_frames", len(frame_ids))):
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
        self._sciezka_zmienila = False
        try:
            dlg.exec()
        finally:
            self._repair_dlg = None
        # PO KAŻDYM BIEGU W OKNIE, nie tylko przy nowych przypisaniach (AR-283): bieg zakończony odmową
        # klingi na pierwszej pozycji (`assigned` = 0) zostawiał pasek bez słowa, a powód odmowy znikał
        # z oknem. ODŚWIEŻENIE PRZED ZDANIEM: pusta biblioteka (filtr) mówi przy odświeżeniu
        # `object.empty_status`, który przykrywał wynik zapisu. Bez przypisań odświeżenie NIE stawia
        # pierwszego wiersza - zaznaczenie w bibliotece zostaje, bo nic się w niej nie zmieniło.
        if dlg.assigned or self._sciezka_zmienila:
            self.refresh(select_first=bool(dlg.assigned))
            self.status_message.emit(self._zdanie_okna_kart(dlg))
            self._podaj_recepte_cofniecia_kart(dlg)

    @staticmethod
    def _zdanie_okna_kart(dlg):
        """Raport paska po zamknięciu okna piszącego karty („Zatwierdź ze ścieżki…”, „Napraw
        nagłówek…”): zdania OBU pól okna RAZEM z ich szczegółami (AR-218) - wynik zapisu stoi
        w `status`, awaria zapisu kart w `error`; okno się zamknęło, więc plik, który padł, zostaje
        już tylko w podpowiedzi paska. Jedno złożenie dla obu okien (AR-236).

        BEZ PRZYCISKÓW OKNA: zdanie `status` po cofnięciu mówi „„Cofnij” ponowi…” albo „„Zatwierdź”
        dopisze…” - po zamknięciu takiego przycisku nie ma. Okno trzyma wtedy wariant dla paska
        (`po_zamknieciu`, `_wariant_paska_kart`: zdanie pola, wariant - krótkie polecenie CLI cofnięcia
        commitu po zapisie albo jego ponowienia, sam stan - i szczegół z pełnym poleceniem); wariant
        idzie tylko, gdy pole wciąż mówi to zdanie, z którym go złożono. Polecenie CLI jedzie też
        polem polecenia nośnika („Kopiuj polecenie”, AR-309)."""
        okno, pasek, szczegol, polecenie = dlg.po_zamknieciu or (None, None, "", "")
        status = ZdanieZeSzczegolem(dlg.status.text(), dlg.status.szczegol())
        if okno is not None and okno == dlg.status.text():
            status = ZdanieZeSzczegolem(pasek, "\n".join(
                x for x in (dlg.status.szczegol(), szczegol) if x), polecenie)
        return zlacz_zdania(" - ", (status,
                                    ZdanieZeSzczegolem(dlg.error.text(), dlg.error.szczegol())))

    def _on_confirm_path_changed(self):
        """Zapis w oknie potwierdzania → kolejka mówi świeżą prawdę JUŻ przy otwartym oknie
        (częściowy zapis przerwany odmową klingi nie zostawia ekranu z nieaktualnym licznikiem).
        Znacznik końca biegu czyta `_on_confirm_path` po zamknięciu okna (wynik na pasek, AR-283)."""
        self._sciezka_zmienila = True
        self._load_review()
        self._sync_assign_enabled()

    # ------------------------------------------------ cofnięcie zapisu kart z paska (AR-296)

    def _podaj_recepte_cofniecia_kart(self, dlg):
        """Po zdaniu okna kart: recepta „Cofnij zapis (commit N)”, gdy okno zostawiło commit do cofnięcia
        (`commit_po_zamknieciu`). Recepta PO raporcie - raport gasi receptę poprzedniego gestu."""
        if dlg.commit_po_zamknieciu is not None:
            self.status_recipe.emit(self._recepta_cofniecia_kart(dlg.commit_po_zamknieciu,
                                                                 dlg.UWAGA_COFNIECIA))

    @staticmethod
    def _etykieta_cofniecia_kart(commit_id, dokoncz):
        """Etykieta recepty cofnięcia commitu kart: „Dokończ cofnięcie (commit N)” z wiersza Porządków
        (AR-318), inaczej „Cofnij zapis (commit N)”. Dwa literały w gałęziach - kolektor kluczy katalogu
        zbiera tylko literały."""
        if dokoncz:
            return i18n.t("wb.undo_finish_recipe", id=commit_id)
        return i18n.t("wb.undo_recipe", id=commit_id)

    def _recepta_cofniecia_kart(self, commit_id, uwaga, *, dokoncz=False):
        """Recepta „Cofnij zapis (commit N)” (albo „Dokończ cofnięcie (commit N)” - `dokoncz`) - człon
        z wykonawcą (wzór `_recepta_cofniecia_dopisania`). Recepta NIESIE TOŻSAMOŚĆ ZAMIARU (AR-355): `commits.run_id`
        z chwili złożenia (`queries.przebieg_commitu`, jak wpis kolejki - AR-336), a wykonawca sprawdza ją przed
        startem (`_cofnij_zapis_kart`)."""
        from functools import partial
        from horreum.gui.grid_model import CzlonRecepty, Recepta
        return Recepta([CzlonRecepty(self._etykieta_cofniecia_kart(commit_id, dokoncz),
                                     partial(self._cofnij_zapis_kart, commit_id, uwaga,
                                             queries.przebieg_commitu(self.con, commit_id), dokoncz=dokoncz))])

    def podaj_dokonczenie_cofniecia(self, commit_id, n):
        """Wejście z wiersza Porządków „Niedokończone cofnięcia zapisu kart” (AR-318): zdanie z liczbą
        plików czekających, polecenie CLI w szczególe i w polu polecenia, recepta „Dokończ cofnięcie
        (commit N)” - ta sama droga wykonania co recepta paska (`_cofnij_zapis_kart`). Oś oznaczona
        nieaktualną najpierw się przeładowuje: raport odświeżenia przy pustej bibliotece
        (`object.empty_status`) zgasiłby receptę postawioną przed nim."""
        if self._nieaktualny:
            self.refresh()
        zdanie = i18n.t_plural("wb.undo_unfinished", n, id=commit_id,
                               finish=self._etykieta_cofniecia_kart(commit_id, True))
        self.wynik_cofniecia.emit(self._zdanie_polecenia_kart(zdanie, commit_id),
                                  self._recepta_cofniecia_kart(commit_id, "", dokoncz=True))

    def _obcy_wlasciciel_bazy(self):
        """PID innego procesu, który trzyma wyłączność szuflady tej bazy (`<baza>.szuflada.lock`,
        `FramesView._wez_szuflade`), albo `None`. Dokończenie cofnięcia podejmuje stan poprzedniej
        sesji, więc korzysta z tej samej wyłączności: SPRAWDZA ją, nie trzyma - udane `tryLock` zwalnia
        od razu, bo trzymanie przez bieg kazałoby własnej szufladzie Zbiorów mówić „inne okno”. Blokada
        tego procesu (własna szuflada) nie zatrzymuje - wewnątrz instancji chronią `_busy`/`_foreign_wb`
        i `_zapis_kart_trwa`."""
        from PySide6.QtCore import QLockFile          # lazy - jak `QLockFile` szuflady w `grid`
        sciezka = queries.db_path_of(self.con)
        if not sciezka:
            return None
        blokada = QLockFile(sciezka + ".szuflada.lock")
        blokada.setStaleLockTime(0)
        if blokada.tryLock(0):
            blokada.unlock()
            return None
        info = blokada.getLockInfo()
        pid = info[0] if info else None
        return pid if pid and pid != os.getpid() else None

    def _cofnij_zapis_kart(self, commit_id, uwaga, tozsamosc, *, dokoncz=False):
        """Klik „Cofnij zapis (commit N)” po zamknięciu okna kart (AR-296) - ten sam rdzeń, co „Cofnij”
        okna i `header-fix --undo` (`writeback.undo`), na wątku uchwytu zapisu tego widoku.

        NAJPIERW TOŻSAMOŚĆ ZAMIARU (AR-355): `tozsamosc` - `commits.run_id` z chwili złożenia recepty
        (`_recepta_cofniecia_kart`). Commit o tym numerze z INNYM przebiegiem zapisu w bazie pod połączeniem (albo
        brak commitu o tym numerze - `queries.przebieg_commitu` daje wtedy None) to nie zamiar recepty - zdanie
        odmowy i nic więcej: bez odłożenia, bez biegu, recepta schodzi z paska (kanał bez recepty). Wyłącznie
        tożsamość, nie żywotność zamiaru (`_zywy`): commit cofnięty inną drogą przy recepcie na
        pasku to droga osiągalna ręką, a zdanie mówi wtedy rdzeń (`ogon_cofniecia`).

        Odmowa przy biegu Dostawy i przy zapisie szuflady Zbiorów mówi zdaniem z numerem commitu (polecenie
        CLI w szczególe i w polu polecenia), a oś PAMIĘTA receptę i podaje ją ponownie, gdy blokada się
        skończy (`set_busy(False)`, `set_writeback_busy(False)` -> `_koniec_blokady`). Wyłączność BAJTÓW między
        instancjami trzyma rdzeń (blokada pliku `writeback._exclusive`, region == wynik commitu,
        operacja cofnięcia pod `BEGIN IMMEDIATE`) - drugi wykonawca dostaje wynik rdzenia, który pasek
        mówi `ogon_cofniecia`. Bieg pamięta GENERACJĘ z chwili startu (`_bieg_kart`): demontaż widoku
        (`zatrzymaj_pola`) unieważnia wszystkie trzy callbacki, także postęp, a zajętość zwalnia
        uchwyt (`busy_changed`).

        CALLBACKI TO METODY WIDOKU, NIE `functools.partial`: sygnał workera z wątku tła trafia do
        metody obiektu Qt kolejką, w jego wątku - a do gołego obiektu wywoływalnego Qt woła go
        wprost, w wątku workera (zmierzone: ogon czytał połączenie widoku z wątku tła -
        `sqlite3.ProgrammingError`). Dane biegu (commit, nota, generacja) stoją więc na widoku.

        ZDANIA BIEGU IDĄ KANAŁEM BEZ ODKŁADANIA (`wynik_cofniecia`): start, postęp, wynik i porażka padają
        na pasek tam, gdzie człowiek jest - odmowa zamknięcia okna i przełączenia bazy obiecuje „pokaże
        wynik”, a raport odłożony do Porządków ginąłby przy demontażu widoków. Start zdejmuje receptę
        z paska - przycisk, który nic by nie zrobił, nie stoi czynny w biegu.

        DOKOŃCZENIE Z WIERSZA PORZĄDKÓW (`dokoncz`, AR-318): przed biegiem sprawdzenie wyłączności bazy
        (`_obcy_wlasciciel_bazy`) - inny proces Horreum (okno albo wiersz poleceń) trzyma szufladę → zdanie
        z jego PID-em, recepta
        zostaje; etykieta recepty i zdania wyniku to „Dokończ cofnięcie (commit N)”."""
        if queries.przebieg_commitu(self.con, commit_id) != tozsamosc:
            self.wynik_cofniecia.emit(i18n.t("wb.undo_recipe_stale", id=commit_id), None)
            return
        if self._busy or self._foreign_wb:
            # Tożsamość zamiaru (AR-336) z TEJ bazy - sprawdzona wyżej, więc wpis niesie tę z recepty; po podmianie
            # pliku pod tą samą ścieżką commit o tym numerze jest cudzy (`_zywy`).
            self._odloz(("karty", commit_id), True, (uwaga, dokoncz), self._blokady["etap" if self._busy else "zapis"],
                        tozsamosc)
            self.wynik_cofniecia.emit(self._zdanie_polecenia_kart(i18n.t(
                "wb.undo_recipe_busy" if self._busy else "wb.undo_recipe_foreign", id=commit_id),
                commit_id), None)
            return
        if self._zapis_kart_trwa:
            return
        if dokoncz:
            obcy = self._obcy_wlasciciel_bazy()
            if obcy is not None:
                self.wynik_cofniecia.emit(self._zdanie_polecenia_kart(i18n.t(
                    "wb.undo_finish_foreign_owner", id=commit_id, pid=obcy), commit_id),
                    self._recepta_cofniecia_kart(commit_id, uwaga, dokoncz=True))
                return
        if self._wb_kart is None:
            from horreum.gui.wb_worker import WritebackRunner
            self._wb_kart = WritebackRunner(queries.db_path_of(self.con), now_fn=self._now, parent=self)
            self._wb_kart.busy_changed.connect(self._na_zajetosc_kart)
            self._wb_kart.busy_changed.connect(self.writeback_busy)   # mutex gridu, Dostawy, Domu
        self.zdejmij_odlozona(("karty", commit_id))
        self._bieg_kart = (self._gen_kart, commit_id, uwaga, dokoncz)
        self.wynik_cofniecia.emit(i18n.t("wb.undo_recipe_started", id=commit_id), None)
        self._wb_kart.start("undo", commit_id, on_progress=self._postep_cofniecia_kart,
                            on_done=self._po_cofnieciu_kart, on_failed=self._cofniecie_kart_padlo)

    def _zdanie_polecenia_kart(self, zdanie, commit_id, szczegol=""):
        """Zdanie paska o cofnięciu commitu kart z poleceniem CLI w szczególe i w polu polecenia
        (`ZdanieZeSzczegolem` - nie gaśnie zegarem, „Kopiuj polecenie”, AR-309)."""
        polecenie = i18n.t("wb.undo_cli", db=queries.db_path_of(self.con), id=commit_id)
        return ZdanieZeSzczegolem(zdanie, "\n".join(x for x in (szczegol, i18n.t(
            "wb.undo_cli_tip", id=commit_id, cli=polecenie)) if x), polecenie)

    def _gotowosc_kart(self, commit_id, uwaga, dokoncz):
        """Zdanie i recepta odłożonego cofnięcia zapisu kart przy podaniu (`_podaj_odlozone`)."""
        return (self._zdanie_polecenia_kart(i18n.t("wb.undo_recipe_ready", id=commit_id), commit_id),
                self._recepta_cofniecia_kart(commit_id, uwaga, dokoncz=dokoncz))

    def _zywy(self, wpis):
        """Czy zamiar wpisu ma jeszcze co wykonać - stan z BAZY, nie z pamięci osi (gest zamknięty inną drogą: wiersz
        Porządków, Oś teleskopu, drugie okno, CLI). Karty: choć jeden backup commitu bez trwałego dowodu zakończenia
        cofnięcia (reguła rdzenia `writeback._cofniecie_zakonczone`, bez odczytu plików). Dopisanie: gest
        „Dopisz nowy…” otwarty (ślad `telescope_add` bez `undone_at`).

        NAJPIERW TOŻSAMOŚĆ ZAMIARU (AR-336): baza pod ścieżką kolejki to ta sama biblioteka tylko wtedy, gdy zamiar wpisu
        (`_Odlozona.tozsamosc` z chwili odłożenia - `run_id` commitu, ślad gestu dopisania) jest w niej ten sam; plik
        podmieniony pod tą samą ścieżką inną biblioteką z żywym commitem albo gestem o tym numerze nie podaje cudzej
        recepty (klik cofnąłby commit cudzej biblioteki - zapis do jej plików). Założenie śladu dopisania - docstring
        `_Odlozona`."""
        rodzaj, cel = wpis.klucz
        if rodzaj == "karty":
            if wpis.tozsamosc is None or queries.przebieg_commitu(self.con, cel) != wpis.tozsamosc:
                return False
            from horreum import writeback      # lazy: rdzeń pisarza ciągnie astropy (`_cofnij_zapis_kart` też)
            return not all(writeback._cofniecie_zakonczone(self.con, cel, b)
                           for b in writeback.backups_for_commit(self.con, cel))
        assert rodzaj == "dopisanie", wpis.klucz
        return wpis.tozsamosc is not None and queries.slad_dopisania(self.con, cel) == wpis.tozsamosc

    def oczysc_martwe(self):
        """Wpisy kolejki, którym baza nie zostawiła nic do wykonania (`_zywy`), schodzą po cichu - KAŻDY, nie tylko
        głowa - a recepta, którą taki wpis już podał, idzie do gospodarza (`recepta_martwa`): zdejmuje ją z paska
        i ze swojego stanu, zanim cokolwiek ją przywróci albo poda następny wpis. Woła to każda chwila podania
        (`_podaj_odlozone`, przed strażą stojącej recepty), wejście w Porządki przed przywróceniem recepty
        i zamknięcie gestu drogą trwałą tego okna (`MainWindow._na_cofniete_dopisanie`).

        `True`, gdy zszedł wpis już PODANY (AR-355) - zamknięcie gestu w Osi teleskopu podaje wtedy następny niepodany
        wpis (`podaj_odlozone(tylko_niepodane=True)`); zdjęcie wyłącznie wpisów niepodanych - `False`: nic z kolejki nie
        stało na pasku, więc nic nie ustępuje. Aktywacja okna pyta węziej - czy zdjęta gotowość wciąż STAŁA na pasku
        (gospodarz, `MainWindow._zdjeta_gotowosc`): podany kiedyś wpis bywa już przykryty innym raportem."""
        zdjety_podany = False
        for w in list(self._odlozone):
            if not self._zywy(w):
                self.zdejmij_odlozona(w.klucz)
                zdjety_podany = zdjety_podany or w.podany
                if w.recepta is not None:
                    self.recepta_martwa.emit(w.recepta, w.przed)
        return zdjety_podany

    def _odloz(self, klucz, zapis_plikow, argumenty, czeka, tozsamosc):
        """Recepta osi odmówiona w biegu blokady `czeka` (`(rodzaj, numer)` z `_blokady`) wchodzi na KONIEC kolejki
        odłożeń (FIFO) jako wpis niepodany; druga odmowa tego samego zamiaru (klucz) zastępuje wpis i przesuwa go na
        koniec. `tozsamosc` - tożsamość zamiaru przeczytana z bazy przez wołającego w chwili odmowy (AR-336, `_zywy`)."""
        self.zdejmij_odlozona(klucz)
        self._odlozone.append(_Odlozona(klucz, zapis_plikow, argumenty, czeka, tozsamosc))

    def zdejmij_odlozona(self, klucz):
        """Wpis zamiaru `klucz` schodzi z kolejki odłożeń: start gestu z recepty (podany drugi raz nic by nie
        zrobił), zamknięcie gestu drogą trwałą w tym oknie (gospodarz - `MainWindow._na_cofniete_dopisanie`),
        podanie wpisu, któremu baza nie zostawiła nic do cofnięcia. W MIEJSCU: lista należy do gospodarza
        (`uzyj_kolejki`), nowa lista zerwałaby to powiązanie."""
        self._odlozone[:] = [w for w in self._odlozone if w.klucz != klucz]

    def uzyj_kolejki(self, kolejka):
        """Gospodarz podaje kolejkę odłożeń TEJ bazy (AR-321, `MainWindow._kolejki_osi`) - po powrocie do bazy
        ta sama lista wraca do osi nowego montażu. Lista zastępuje własną listę widoku."""
        self._odlozone = kolejka

    def _gotowosc(self, wpis):
        """Zdanie i recepta wpisu kolejki przy podaniu - składane przez BIEŻĄCY widok z danych wpisu (żywego -
        `oczysc_martwe` biegnie przed podaniem)."""
        klucz = wpis.klucz
        if klucz[0] == "karty":
            return self._gotowosc_kart(klucz[1], *wpis.argumenty)
        assert klucz[0] == "dopisanie", klucz
        return self._gotowosc_dopisania(klucz[1], *wpis.argumenty)

    def podaj_odlozone(self, *, doklej=None, tylko_niepodane=False):
        """Publiczne wejście gospodarza (AR-321) - `True`, gdy coś wyemitowano:

          * wejście w Porządki (`doklej` = raport odłożony do Porządków, który właśnie stanął na pasku): pierwszy
            wpis kolejki, także już podany, wraca z gotowością DOKLEJONĄ do tego raportu - recepta jest dostępna
            do startu swojego gestu, a raport, który na człowieka czekał, nie znika pod nią;
          * koniec otwarcia bazy (`tylko_niepodane`): wyłącznie wpis, którego żadna chwila jeszcze nie podała
            (powrót do bazy z odłożeniem sprzed przełączenia) - podany nie zastępuje drugi raz „Baza: … wczytana”;
          * zdjęcie podanej głowy (`doklej` + `tylko_niepodane`, AR-355): aktywacja okna, która zdjęła z paska STOJĄCĄ
            gotowość martwego wpisu (`doklej` = zdanie, które wtedy wróciło), i zamknięcie gestu w Osi teleskopu
            (`doklej` = wynik tego gestu) - następny wpis, którego nic jeszcze nie podało, dochodzi do tego zdania;
            podany nie wraca tu drugi raz (jego chwilą jest wejście w Porządki)."""
        return self._podaj_odlozone(doklej=doklej, wybor=(lambda w: not w.podany) if tylko_niepodane else None)

    def _koniec_blokady(self, blokada):
        """Koniec biegu blokady `blokada` (`(rodzaj, numer)`) podaje WYŁĄCZNIE wpisy, które odłożył ten bieg i których
        jeszcze nic nie podało - każdy raz (`_Odlozona.podany`); wpisy innego biegu i podane już raz zostają przy
        swoich chwilach (wejście w Porządki, ogon gestu), więc start i koniec zapisu Zbiorów albo koniec następnego
        etapu nie zastępują cudzych raportów tą samą gotowością. Wpis tego biegu wciąż trzymany drugą blokadą (etap
        w biegu, zapis do plików Zbiorów) czeka odtąd na koniec jej biegu."""
        for w in self._odlozone:
            if w.czeka == blokada and not w.podany:
                if self._busy:
                    w.czeka = self._blokady["etap"]
                elif w.zapis_plikow and self._foreign_wb:
                    w.czeka = self._blokady["zapis"]
        self._podaj_odlozone(wybor=lambda w: w.czeka == blokada and not w.podany)

    def _podaj_odlozone(self, *, po=None, doklej=None, wybor=None):
        """Koniec blokady (`_koniec_blokady`), koniec gestu z recepty (`po`) albo chwila gospodarza
        (`podaj_odlozone`): NAJPIERW wszystkie wpisy, którym baza nic nie zostawiła, schodzą z kolejki razem ze
        swoją receptą na pasku gospodarza (`oczysc_martwe`) - martwa głowa nie zasłania wpisu za nią, a martwa
        recepta nie trzyma straży. Potem PIERWSZY wpis kolejki (spośród `wybor`) bez blokady wraca ze zdaniem
        gotowości i receptą - jeden na wywołanie, bo pasek ma jeden przycisk recepty (człon drugi recepty znaczy
        „potem” w czasie) - i jest odtąd podany; wpis pamięta wyemitowaną receptę i zdanie, do którego ją dokleił.
        Kanał `wynik_cofniecia` zdejmuje starszy odłożony raport Porządków (`MainWindow._wynik_cofniecia_osi`). Wpis
        ZOSTAJE w kolejce do startu swojego gestu (AR-321).

        STRAŻ STOJĄCEJ RECEPTY (AR-321): bez `po` nic nie pada, gdy gospodarz mówi, że recepta stoi
        (`recepta_stoi`) - koniec zapisu Zbiorów po końcu etapu nadpisywał receptę podaną przed chwilą.

        `po` = zdanie wyniku gestu, który skończył się bez własnej recepty (cofnięcie domknięte, wynik
        cofnięcia dopisania): wynik i gotowość następnego wpisu idą JEDNĄ emisją - wynik nie znika pod
        nowym zdaniem; gest właśnie zużył stojącą receptę, więc straż go nie zatrzymuje. W tym podaniu wpis
        czekający na zapis do plików pomija własny bieg osi (`_zapis_kart_trwa`) - bieg właśnie się kończy,
        a klik i tak trafi po `busy_changed(False)`. `doklej` = raport, który już stoi na pasku - gotowość
        dochodzi do niego (wejście w Porządki). `True` - coś wyemitowano."""
        self.oczysc_martwe()
        if self._busy or (po is None and self.recepta_stoi()):
            return False
        for w in self._odlozone:
            if wybor is not None and not wybor(w):
                continue
            if w.zapis_plikow and (self._foreign_wb or (self._zapis_kart_trwa and po is None)):
                continue
            zdanie, recepta = self._gotowosc(w)
            przed = po if po is not None else doklej
            if przed:
                zdanie = zlacz_zdania(" - ", (przed, zdanie))
            w.podany, w.recepta, w.przed = True, recepta, przed or None
            self.wynik_cofniecia.emit(zdanie, recepta)
            return True
        return False

    def _na_zajetosc_kart(self, busy):
        self._zapis_kart_trwa = bool(busy)
        self._sync_assign_enabled()

    def _bieg_kart_zywy(self):
        """`(commit_id, uwaga, dokoncz)` biegu cofnięcia z paska, gdy jego generacja jest bieżąca,
        inaczej None."""
        gen, commit_id, uwaga, dokoncz = self._bieg_kart
        return (commit_id, uwaga, dokoncz) if gen == self._gen_kart else None

    def _postep_cofniecia_kart(self, done, total, path, status):
        bieg = self._bieg_kart_zywy()
        if bieg is None:
            return
        self.wynik_cofniecia.emit(i18n.t("wb.undo_recipe_progress", id=bieg[0], done=done,
                                         total=total), None)

    def _po_cofnieciu_kart(self, op, res):
        """Ogon cofnięcia z paska: zdanie i reguła „czy uchwyt zostaje” z `ogon_cofniecia` (rdzeń:
        `UndoResult.complete`, „już cofnięte” to stan docelowy). Niedomknięte - zdanie z poleceniem CLI
        w szczególe i w polu polecenia, recepta wraca; domknięte - stan bez recepty."""
        bieg = self._bieg_kart_zywy()
        if bieg is None:
            return
        commit_id, uwaga, dokoncz = bieg
        from horreum.gui.wb_worker import podpowiedz_cofniecia
        msg, ponow = ogon_cofniecia(res, self._etykieta_cofniecia_kart(commit_id, dokoncz))
        self._load_review()
        self._sync_assign_enabled()
        if ponow:
            # Wynik pada też poza Porządkami - zdanie mówi, gdzie stoi przycisk, który nazywa.
            self.wynik_cofniecia.emit(self._zdanie_polecenia_kart(
                msg + i18n.t("wb.undo_recipe_place"), commit_id, podpowiedz_cofniecia(res)),
                self._recepta_cofniecia_kart(commit_id, uwaga, dokoncz=dokoncz))
            return
        # Stan obiektu klatek z karty po „Rozwiąż” mówi zdanie z rdzenia (AR-311, `zdanie_undo_kart`).
        # Domknięte bez własnej recepty - następny odłożony wpis wraca razem z wynikiem (AR-310).
        wynik = ZdanieZeSzczegolem(msg + (i18n.t(uwaga) if uwaga else ""), podpowiedz_cofniecia(res))
        if not self._podaj_odlozone(po=wynik):
            self.wynik_cofniecia.emit(wynik, None)

    def _cofniecie_kart_padlo(self, op, zdanie, podpowiedz):
        """Wyjątek workera cofnięcia z paska: zdanie błędu ze szczegółem systemu, recepta wraca - nie
        wiemy, czy pliki wróciły."""
        bieg = self._bieg_kart_zywy()
        if bieg is None:
            return
        commit_id, uwaga, dokoncz = bieg
        from horreum.gui.wb_worker import czytelny_powod
        self.wynik_cofniecia.emit(ZdanieZeSzczegolem(
            i18n.t("grid.wb.error", msg=czytelny_powod(zdanie)), podpowiedz),
            self._recepta_cofniecia_kart(commit_id, uwaga, dokoncz=dokoncz))

    def refuse_close(self, say, *, przerwij=True):
        """Straż zamknięcia okna i przełączenia bazy gospodarza (AR-296): `True` = cofnięcie z paska
        trwa - zdanie i (przy `przerwij`) anulowanie po bieżącym pliku (`WritebackRunner.refuse_close`)."""
        return self._wb_kart is not None and self._wb_kart.refuse_close(say, przerwij=przerwij)

    def zatrzymaj_pola(self):
        """Widok znika (zamknięcie okna, przełączenie bazy - `MainWindow._zatrzymaj_watki_widokow`):
        callbacki cofnięcia z paska z chwili przed demontażem wracają bez skutku (generacja). Wątku
        NIE zbiera i nie czeka: gospodarz nie demontuje widoku w biegu zapisu (`refuse_close`), a
        sprzątanie wątku ma jednego właściciela - `QThread.finished` uchwytu. Idempotentne."""
        self._gen_kart += 1

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
        z ekranu: klatka wypada z kubełka, a automat jej nie tknie.

        TRZECIE WEJŚCIE (AR-128, D-1012-2 `Q8`): kubełek „ogniskowa niezgodna z teleskopem" otwiera
        okno w trybie ogniskowej - lista zawężona do teleskopów w tolerancji i „Dopisz nowy…". Zestaw
        z automatu NADPISUJE się (`overwrite=True`), bo ręka właśnie orzekła, że automat się mylił;
        nowy teleskop powstaje razem z przypisaniem jedną klingą."""
        tag, _ = self._selected_review()
        zmiana = tag == "config_by_hand"
        ogniskowa = tag == "config_focal"
        grupy = (queries.config_by_hand_groups(self.con) if zmiana
                 else queries.focal_mismatch_groups(self.con) if ogniskowa
                 else queries.config_review_groups(self.con))
        if not grupy:
            self.status_message.emit(i18n.t("cfg.err_nothing"))
            return
        dlg = AssignConfigDialog(self.con, groups=grupy, change=zmiana, focal=ogniskowa,
                                 parent=self)
        # ODMOWA KLINGI NIE GUBI WPISU (bramka kodu N16): przy „Dopisz nowy…" okno wraca otwarte
        # z polami, które user wypełnił, i z powodem odmowy; przy wyborze z listy - komunikat jak dawniej.
        while True:
            if dlg.exec() != QDialog.Accepted or dlg.selected is None:
                return
            telescope_id, telescope_label, frame_ids = dlg.selected
            nowy = getattr(dlg, "new_telescope", None)         # tylko tryb ogniskowej go ma
            try:
                with busy.busy(self.status_message.emit,
                               i18n.t_plural("busy.saving_frames", len(frame_ids))):
                    if nowy is not None:
                        telescope_id, g = repo.user_assign_config_new_telescope(
                            self.con, frame_ids=frame_ids, now=self._now(), **nowy)
                    else:
                        g = repo.user_assign_config(self.con, frame_ids=frame_ids,
                                                    telescope_id=telescope_id, now=self._now(),
                                                    overwrite=zmiana or ogniskowa)
                break
            except ValueError as e:            # dryf do nieistniejącej klatki/teleskopu, zła nazwa
                if nowy is None or not hasattr(dlg, "pokaz_odmowe"):
                    QMessageBox.warning(self, i18n.t("cfg.title"), str(e))
                    return
                dlg.pokaz_odmowe(str(e))
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
        self.telescope_axis_changed.emit()
        if nowy is not None and g.assigned:
            # „Dopisz nowy…” ma cofnięcie JEDNYM kliknięciem (AR-133, `Q8`): recepta niesie
            # teleskop, a klinga odtwarza stan sprzed gestu z jego trwałego śladu (`telescope_add`).
            # Na końcu - raport odświeżenia (pusta biblioteka) zgasiłby receptę wysłaną wcześniej.
            self.status_recipe.emit(self._recepta_cofniecia_dopisania(telescope_id,
                                                                       telescope_label))

    def _recepta_cofniecia_dopisania(self, telescope_id, telescope_label):
        """Recepta „Cofnij dopisanie „X”” - człon z wykonawcą (`grid_model.CzlonRecepty`). Recepta NIESIE TOŻSAMOŚĆ
        ZAMIARU (AR-355): ślad gestu z chwili złożenia (`queries.slad_dopisania`, jak wpis kolejki - AR-336)."""
        from horreum.gui.grid_model import CzlonRecepty, Recepta
        tozsamosc = queries.slad_dopisania(self.con, telescope_id)
        return Recepta([CzlonRecepty(
            i18n.t("object.config_undo_add", telescope=telescope_label),
            lambda: self._on_cofnij_dopisanie(telescope_id, telescope_label, tozsamosc))])

    def _on_cofnij_dopisanie(self, telescope_id, telescope_label, tozsamosc):
        """Klik „Cofnij dopisanie” (AR-133): `repo.undo_new_telescope` - klatki gestu wracają do
        zestawu sprzed gestu (CAS: klatka zmieniona po geście zostaje i jest policzona), teleskop
        bez klatek i bez ręki po geście schodzi nagrobkiem z osi. Odmowa bez zapisu (teleskop żyje
        już poza gestem: profil, scalenie, ręka po geście) mówi powodem z tokenu klingi.

        NAJPIERW TOŻSAMOŚĆ ZAMIARU (AR-355): `tozsamosc` - ślad gestu z chwili złożenia recepty. OTWARTY ślad tego
        teleskopu z inną tożsamością to gest dopisany od nowa (drugie okno, nagrobek: „Dopisz nowy…” tej samej nazwy
        wskrzesza TEN SAM teleskop z nowym śladem - `repo.user_assign_config_new_telescope`) albo inna biblioteka -
        zdanie odmowy z rodziny klingi (`refused.re_added`: nowe dopisanie cofa się na Osi teleskopu), bez odłożenia
        i bez zapisu. Brak otwartego śladu to gest zamknięty inną drogą (droga osiągalna ręką): klinga odmawia sama
        i mówi to swoim zdaniem.

        W TRAKCIE ETAPU DOSTAWY GEST JEST ODKŁADANY (AR-310): wpis `("dopisanie", teleskop)` wchodzi do
        tej samej kolejki odłożeń co cofnięcie zapisu kart (SPOT, `_odloz`), zdanie odmowy mówi, kiedy
        recepta wróci, a koniec etapu podaje ją kanałem `wynik_cofniecia` (`set_busy(False)` ->
        `_koniec_blokady`) - raporty odświeżenia po przebiegu już jej nie gaszą. Dopisanie czeka
        wyłącznie na etap: to zapis do BAZY, poza mutexem zapisu plików (jak „Przypisz zestaw…”).
        Wynik gestu przy niepustej kolejce idzie razem z gotowością następnego wpisu."""
        slad = queries.slad_dopisania(self.con, telescope_id)
        if slad is not None and slad != tozsamosc:
            self.wynik_cofniecia.emit(i18n.t("object.config_undo_add.refused", telescope=telescope_label,
                                             reason=i18n.t("object.config_undo_add.refused.re_added")), None)
            return
        if self._busy:
            self._odloz(("dopisanie", telescope_id), False, (telescope_label,), self._blokady["etap"],
                        tozsamosc)      # tożsamość zamiaru (AR-336), sprawdzona wyżej
            self.wynik_cofniecia.emit(i18n.t("object.config_undo_add.deferred",
                                             telescope=telescope_label), None)
            return
        self.zdejmij_odlozona(("dopisanie", telescope_id))
        wynik = repo.undo_new_telescope(self.con, telescope_id=telescope_id, now=self._now())
        zdanie = zdanie_cofniecia_dopisania(wynik, telescope_label)
        if not self._odlozone:
            self.status_message.emit(zdanie)
            self.refresh()
            self.telescope_axis_changed.emit()
            return
        self.refresh()
        self.telescope_axis_changed.emit()
        if not self._podaj_odlozone(po=zdanie):
            self.status_message.emit(zdanie)

    def _gotowosc_dopisania(self, telescope_id, telescope_label):
        """Zdanie i recepta odłożonego cofnięcia dopisania przy podaniu (`_podaj_odlozone`)."""
        return (i18n.t("object.config_undo_add.ready", telescope=telescope_label),
                self._recepta_cofniecia_dopisania(telescope_id, telescope_label))

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
        kontrakt „okno pokazuje dokładnie to, co licznik, na którym kliknąłeś".

        PO ZAMKNIĘCIU WYNIK IDZIE NA PASEK (AR-236), jak z „Zatwierdź ze ścieżki…”: zdania obu pól
        okna ze szczegółami (`_zdanie_okna_kart`) - inaczej plik, który padł przy zapisie kart,
        znikał razem z oknem. Tylko gdy w oknie skończył się bieg (zapis, cofnięcie albo jego błąd -
        sygnał `changed`); walidacja grup i „Zamknij” bez biegu nie mówią nic."""
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
        self._naprawa_zmienila = False
        try:
            dlg.exec()
        finally:
            self._repair_dlg = None
        if self._naprawa_zmienila:
            self.status_message.emit(self._zdanie_okna_kart(dlg))
            self._podaj_recepte_cofniecia_kart(dlg)

    def _on_repair_changed(self):
        """Zapis/cofnięcie w oknie naprawy → kolejka mówi świeżą prawdę JUŻ po takcie 2 (dialog żyje
        w tym samym widoku). Oś obiektu i badge Porządków ruszą się dopiero po takcie 3 — to nie
        rozjazd, tylko dwa różne fakty: karta jest w pliku, obiektu jeszcze nie ma. Znacznik końca
        biegu czyta `_on_repair` po zamknięciu okna (wynik na pasek, AR-236)."""
        self._naprawa_zmienila = True
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
        bieg = self._przelacz_blokade("etap", busy)
        self._busy = busy
        self._sync_assign_enabled()
        if self._repair_dlg is not None:
            self._repair_dlg.set_pipeline_busy(busy)
        if bieg is not None:
            self._koniec_blokady(bieg)       # recepty osi odłożone przez ten etap (AR-296, AR-310)

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (grid) pisze do plików — „Napraw nagłówek…" gaśnie
        (mutex, D-PD-3: dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`)."""
        bieg = self._przelacz_blokade("zapis", busy)
        self._foreign_wb = busy
        self._sync_assign_enabled()
        if bieg is not None:
            self._koniec_blokady(bieg)       # …i przez ten zapis w Zbiorach (AR-296)

    def _przelacz_blokade(self, rodzaj, w_biegu):
        """Start biegu blokady `rodzaj` nadaje mu numer (`_blokady`); koniec zdejmuje go i zwraca `(rodzaj, numer)`
        kończącego się biegu - inaczej (start, zgłoszenie bez zmiany stanu) `None`."""
        bieg = self._blokady[rodzaj]
        if w_biegu and bieg is None:
            self._blokady[rodzaj] = (rodzaj, next(_NUMERY_BLOKAD))
        elif not w_biegu and bieg is not None:
            self._blokady[rodzaj] = None
            return bieg
        return None


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


def _klucz_sortu_obserwatorium(row, col):
    """Klucz sortu wiersza osi OBSERWATORIUM po kolumnie `col`; `None` = komórka bez wartości.
    Nazwa - `_klucz_tekstu` (nienazwane na końcu); ID, szerokość, długość i klatki jako liczby
    (współrzędna ujemna przed dodatnią, brak współrzędnej na końcu)."""
    if col == OBS_COL_NAME:
        return _klucz_tekstu(row["name"])
    if col == OBS_COL_LAT:
        return row["lat"]
    if col == OBS_COL_LON:
        return row["lon"]
    if col == OBS_COL_FRAMES:
        return row["frame_count"]
    assert col == OBS_COL_ID, col
    return row["id"]


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
        self._sort = None                    # (kolumna, Qt.SortOrder) z kliku nagłówka; None = read-model
        self._z_zatwierdzenia = False        # refresh z zatwierdzenia nazwy - edytor otwarty, wpis zapisany
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
        _wlacz_sort_naglowka(hdr, self._on_sort_changed)
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
        self.combo_target = kolko(QComboBox())
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
        self.btn_hand_assign = QPushButton(i18n.t("obshand.btn_assign"))   # licznik dopisuje refresh
        self.btn_hand_assign.setToolTip(i18n.t("obshand.btn_assign_tip"))   # co liczy licznik
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
        i zapamiętuje współrzędne dla linku OSM (F8 F8 - read-model nie jest cache'owany inaczej).

        Porządek z kliku nagłówka (`self._sort`) przeżywa przeładowanie - tabela dostaje wiersze
        ułożone przed wypełnieniem, mapa ten sam zbiór w porządku read-modelu: kolejność rysowania
        rozstrzyga, który z nakładających się punktów leży na wierzchu i łapie klik, a ten nie może
        zależeć od sortu tabeli. Otwarty edytor nazwy przebudowa zamyka bez zapisu - pasek mówi wtedy,
        że wpis trzeba powtórzyć."""
        prev = self._selected_observatory_id()
        przerwana = None if self._z_zatwierdzenia else _zdanie_przerwanej_edycji(self.table)
        self._loading = True
        try:
            sites = queries.active_observatories(self.con)
            rows = _posortuj_wiersze(sites, self._sort, _klucz_sortu_obserwatorium)
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
        self.map_view.set_sites(sites)                # mapa dostaje TE SAME wiersze co tabela (F8)
        # AR-74: przycisk gestu niesie liczbę swojej roboty. TEN SAM predykat co wiersz Porządków
        # „Klatki bez stanowiska" i wejście okna (`queries.observatory_review_frames`, po AR-80 bez
        # darków i biasów) - jedna liczba = jedno wejście gestu, więc przycisk i wiersz nie mogą
        # mówić różnie.
        self.btn_hand_assign.setText(i18n.t(
            "obshand.btn_assign_n", n=len(queries.observatory_review_frames(self.con))))
        if target_row >= 0:
            self.table.selectRow(target_row)
        elif not empty:
            self.table.selectRow(0)
        else:
            self.status_message.emit(i18n.t("axis.obs.empty_status"))
        self._on_selection_changed()
        if przerwana:
            self._flash(przerwana)

    def _on_sort_changed(self, col, order):
        """Klik nagłówka: zapamiętaj kolumnę i kierunek, ułóż listę od nowa (zaznaczenie zostaje)."""
        self._sort = (col, order)
        self.refresh()

    def wejdz_po_wskazanie(self):
        """Wejście z wiersza Porządków „Klatki bez stanowiska" (AR-74) - lustro drogi osi zestawu
        (`TasksView._zaznacz_kubelek`): baza czytana od nowa, więc licznik przycisku równa się
        liczbie wiersza, z którego user przyszedł, a fokus staje na „Wskaż stanowisko…" - Enter/spacja
        otwiera okno bez szukania myszą. Gest roboty od dwóch równorzędnych przycisków obok odróżnia
        licznik na przycisku: obwódkę fokusu styl Fusion maluje dopiero po zmianie fokusu klawiaturą,
        więc po wejściu kliknięciem jej nie widać (wizytacja natywna). Przy biegu etapu przycisk jest
        wygaszony i fokusu nie bierze."""
        self.refresh()
        if self.btn_hand_assign.isEnabled():
            self.btn_hand_assign.setFocus(Qt.OtherFocusReason)

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
        v1) złapany i pokazany; widok wraca do prawdy bazy (refresh). Przeładowanie z tej drogi
        zastaje edytor jeszcze otwarty, ale wpis jest już zapisany - `_z_zatwierdzenia` wycisza
        zdanie o przerwanej edycji."""
        if self._loading or item.column() != OBS_COL_NAME:
            return
        self._z_zatwierdzenia = True
        try:
            oid = self.table.item(item.row(), OBS_COL_ID).data(Qt.UserRole)
            try:
                changed = repo.label_observatory(
                    self.con, observatory_id=oid, name=item.text(), now=self._now())
            except ValueError as e:
                self._flash(i18n.t("axis.obs.name_rejected", e=e))
                self.refresh()
                return
            self._flash(i18n.t("axis.obs.name_saved") if changed
                        else i18n.t("axis.obs.name_unchanged"))
            self.refresh()
        finally:
            self._z_zatwierdzenia = False

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
            with busy.busy(self._flash, i18n.t_plural("busy.saving_frames", len(wybor["frame_ids"]))):
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
# STRONY LENIWE (AR-325) i widoki, które każda z nich niesie - Dom i Porządki budują się w montażu (strona
# startu; plakietka i aliasy osi), te trzy przy pierwszym wejściu albo pierwszym dostępie do atrybutu.
class _PoMalowaniu(QObject):
    """Kotwica „po pierwszym malowaniu” dobudowy Zbiorów (AR-325): zdarzenie o NISKIM priorytecie zamówione na końcu
    otwarcia bazy Qt doręcza po `UpdateRequest` okna (malowanie, ten sam niski priorytet, wysłane wcześniej - w montażu),
    więc wywołanie zwrotne biegnie po pierwszym malowaniu Domu. Zegar 0 ms (priorytet zwykły) wyprzedzał malowanie:
    zmierzone natywnie z oknem na pulpicie - pierwsze malowanie Domu 628-1102 ms po `open_path` wobec 25-33 ms bez
    dobudowy. Odwołanie: `QCoreApplication.removePostedEvents` z typem `TYP`."""
    TYP = QEvent.Type(QEvent.registerEventType())

    def __init__(self, zwrot, parent):
        super().__init__(parent)
        self._zwrot = zwrot

    def zamow(self):
        QCoreApplication.postEvent(self, QEvent(self.TYP), Qt.LowEventPriority.value)

    def odwolaj(self):
        QCoreApplication.removePostedEvents(self, self.TYP)

    def event(self, ev):
        if ev.type() == self.TYP:
            self._zwrot()
            return True
        return super().event(ev)


_WIDOKI_STRONY = {STRONA_ZBIORY: ("grid_view", "znajdz_view"),
                  STRONA_DOSTAWA: ("pipeline_view", "przyjmij_view"),
                  STRONA_PLANER: ("planner_view",)}
_STRONA_WIDOKU = {nazwa: strona for strona, nazwy in _WIDOKI_STRONY.items() for nazwa in nazwy}


def _widok_strony(nazwa):
    """Atrybut widoku strony leniwej (AR-325, kontrakt K1): dostęp po montażu BUDUJE stronę, jeśli jeszcze jej
    nie ma (`MainWindow._zbuduj_strone`) - kod i testy, które mówią „po `open_path` widoki istnieją”, dostają
    widok. Bez bazy (przed montażem, po demontażu) - `None`. Kod gospodarza, który NIE ma budować (powiadomienia
    stanu: koniec przebiegu, motyw, mutex, straż zamknięcia), czyta `MainWindow._gotowy`."""
    def _get(self):
        widok = self._strony.get(nazwa)
        if widok is None and _STRONA_WIDOKU[nazwa] in self._zaslepki:
            self._zbuduj_strone(_STRONA_WIDOKU[nazwa])
            widok = self._strony.get(nazwa)
        return widok
    return property(_get, doc=f"Widok `{nazwa}` strony leniwej (AR-325) - buduje stronę przy pierwszym dostępie.")


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
    # Osie Porządków bez odczytu w montażu (AR-175) - OSOBNY przełącznik (AR-326): dawniej szły za
    # `_pola_poza_watkiem`, więc testy bez wątków tła nigdy nie widziały osi leniwych. Test, który czyta oś
    # zaraz po `open_path` bez wejścia w jej podstronę, wyłącza go jawnie.
    _osie_leniwie = True
    # Strony Zbiorów, Dostawy i Planera budowane przy pierwszym wejściu (AR-325) - zmierzone natywnie na kopii
    # pf4: `open_path` 617-767 ms jednego przestoju pętli (5/5 biegów), dolna granica bez tych trzech stron
    # 155-194 ms; o przestoju decydowała strona Zbiorów (jej wątki tła startowały w montażu i odbierały GIL
    # reszcie montażu). `False` - montaż buduje wszystko od razu (`zbuduj_strony`).
    _strony_leniwie = True
    # Strona Zbiorów DOBUDOWANA W BEZCZYNNOŚCI zaraz po otwarciu bazy w pokazanym oknie (AR-325, `_zamow_dobudowe`) -
    # zmierzone natywnie na kopii pf4: pierwsze wejście w niezbudowane Zbiory 290-326 ms (przestój ≥ 300 ms w 3 z 5
    # biegów; pierwszy `sizeHint` przycisku w budowie strony, ~272 ms w zimnym procesie, cProfile). Budowa rusza po
    # pierwszym malowaniu Domu i po serii liczników Porządków montażu (`_sprawdz_dobudowe`) - wcześniej przesuwała
    # jedno i drugie. `False` - Zbiory czekają na pierwsze wejście (testy dróg „strona niezbudowana”: komendy,
    # zatrzaski, porażka budowy).
    _zbiory_w_bezczynnosci = True
    # OGON BIEGU (AR-373): `(since, {pisarze})` przebiegu Dostawy, którego koniec zapisują jeszcze pisarze po
    # `run_finished` (dziś rodowód stosów ze żniw), albo None. Wtedy odświeżenie widoków robi ostatni pisarz, raz -
    # `running_changed(False)` go nie powtarza (`_on_pipeline_running`). Stan instancji; tu wartość startowa.
    _ogon_biegu = None
    # ZDJĘTA STOJĄCA GOTOWOŚĆ (AR-355): `(zdanie przywrócone albo None,)`, gdy `_zdejmij_martwa_recepte` zdjął z paska
    # gotowość martwego wpisu kolejki osi, która wciąż stała - aktywacja okna (`changeEvent`) podaje wtedy następny
    # niepodany wpis, doklejony do tego zdania; None - nic takiego nie zaszło. Jedna chwila: aktywacja zeruje ją przed
    # zdjęciem i po odczycie. Stan instancji; tu wartość startowa.
    _zdjeta_gotowosc = None

    grid_view = _widok_strony("grid_view")
    znajdz_view = _widok_strony("znajdz_view")
    pipeline_view = _widok_strony("pipeline_view")
    przyjmij_view = _widok_strony("przyjmij_view")
    planner_view = _widok_strony("planner_view")

    def __init__(self, db_path=None, now_fn=_utc_now_iso, on_db_changed=None, parent=None):
        super().__init__(parent)
        self.con = None
        self.db_path = None
        # STRONY LENIWE (AR-325): widoki Zbiorów, Dostawy i Planera (`grid_view`, `znajdz_view`, `pipeline_view`,
        # `przyjmij_view`, `planner_view`) mieszkają w słowniku i powstają przy pierwszym wejściu albo pierwszym
        # dostępie do atrybutu (property `_widok_strony`); kod gospodarza, który NIE ma budować, czyta `_gotowy`.
        # Przed montażem i po demontażu - `None` (menu Plik bywa wołane przed bazą, straż zapisu w biegu
        # `_odmowa_w_biegu_zapisu` pyta już przy pierwszym `open_path`).
        self._strony = {}
        self._zaslepki = {}             # `STRONA_*` → pusta zaślepka na stosie, dopóki strona nie powstała
        self._w_budowie = {}            # `STRONA_*` → widoki utworzone w trwającej budowie (zbieranie przy porażce)
        # ZATRZASKI STANU (AR-325): bieg Dostawy i zapis do plików (oś, grid) ustawiane PRZED rozesłaniem
        # do zbudowanych stron; strona budowana później przykłada je, zanim stanie się dostępna.
        self._dostawa_w_biegu = False
        self._zapis_w_biegu = {"os": False, "grid": False}
        self._nav_ostatni = NAV_DOM     # wiersz sidebara ostatniego udanego wejścia (powrót po porażce budowy)
        # Zegar dobudowy Zbiorów w bezczynności (`_zbiory_w_bezczynnosci`): jeden na okno, zatrzymywany przy budowie na
        # żądanie, na początku otwarcia bazy i przy zamknięciu okna - stoi PRZED pierwszym `_open_path` konstruktora.
        # Rusza dopiero po DWÓCH kotwicach montażu (`_sprawdz_dobudowe`): pierwsze malowanie Domu (`_PoMalowaniu`) i
        # koniec serii liczników Porządków montażu (`_on_liczenie_w_toku`) - obie zdejmuje demontaż (`_clear_views`).
        self._dobudowa_zbiorow = QTimer(self)
        self._dobudowa_zbiorow.setSingleShot(True)
        self._dobudowa_zbiorow.setInterval(0)
        self._dobudowa_zbiorow.timeout.connect(self._dobuduj_zbiory)
        self._po_malowaniu = _PoMalowaniu(self._na_malowanie_domu, self)
        self._kotwica_malowania = False
        self._kotwica_licznikow = False
        self.object_view = None
        # Recepta osi Porządków razem z raportem, z którym przyszła (`_recepta_porzadkow`, AR-296).
        self._recepta_porzadkow_stan = None
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
        # DWA KANAŁY FAZY OKNA (AR-175), jedna etykieta (`_pokaz_faze`): faza pierwszego planu (`_say_phase`
        # do `_end_phase`) i faza tła - rachunek liczników Porządków montażu w wątku tła, od startu serii
        # do jej końca (`_on_liczenie_w_toku`, seria `_seria_montazu` aktualnego `tasks_view`). Stan
        # stoi PRZED pierwszym `_open_path`: odmowa bazy (AR-69, AR-124) kończy się `_end_phase` bez montażu.
        self._faza_pierwsza = ""
        self._faza_tla = ""
        self._seria_montazu = None
        # TOKEN MONTAŻU (AR-326): numer bieżącego montażu widoków, niesiony w sygnałach `TasksView`
        # (`liczenie_w_toku`, `rachunek_padl`) - spóźniony sygnał widoku sprzed przełączenia bazy ma cudzy token.
        self._montaz = 0
        # Plakietka Porządków mówi „!” (AR-326) - stan gospodarza ustawiany w `_on_tasks_counts`, nie czytany z napisu.
        self._plakietka_padla = False
        # KOLEJKI ODŁOŻONYCH RECEPT OSI (AR-321) per baza tego okna: `queries.klucz_bazy(ścieżka)` → lista wpisów
        # (`ObjectAxisView._odloz`). Atrybut INSTANCJI - dwa okna w jednym procesie mają osobne kolejki; kolejka
        # żyje, dopóki okno (program) jest otwarte, i przeżywa przełączenie bazy - powrót do tej samej ścieżki
        # oddaje ją osi nowego montażu. Tożsamość bazy = napis ścieżki (`normcase(abspath)`), ta sama konwencja
        # co rejestr przeglądów i blokada szuflady: ta sama baza przez junction albo inny alias ścieżki to inna
        # kolejka (ograniczenie świadome - `realpath` zamieniłby literę dysku sieciowego na UNC). Plik podmieniony
        # pod tą samą ścieżką inną biblioteką dostaje tę samą kolejkę, a cudzej recepty nie podaje tożsamość zamiaru
        # wpisu (`_Odlozona.tozsamosc`, sprawdzana w `ObjectAxisView._zywy`).
        self._kolejki_osi = {}
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
        m.addAction(i18n.t("menu.work_root"), self._on_work_root)
        self._build_view_menu()
        # Pomoc (AR-312): wydanie okienkowe nie ma konsoli - dziennik błędów to jedyny ślad po oknie błędu.
        pomoc = self.menuBar().addMenu(i18n.t("menu.help"))
        pomoc.addAction(i18n.t("menu.open_error_log"), self._on_dziennik_bledow)

    def _on_dziennik_bledow(self):
        """„Pomoc → Otwórz dziennik błędów”: plik w programie systemu albo zdanie na pasku, dlaczego nie."""
        zdanie = otworz_dziennik_bledow()
        if zdanie is not None:
            self._flash(zdanie)

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
        apply_theme(app, name, styl=False)   # Fusion stoi od `main` (AR-175)
        QSettings("Horreum", "Horreum").setValue("ui/theme", name)
        grid_view = self._gotowy("grid_view")           # strona niezbudowana weźmie motyw przy budowie (AR-325)
        if grid_view is not None:
            grid_view.table.viewport().update()
            grid_view.facet_rail.refresh_theme()
        if self.home_view is not None:                 # złota ramka kafla to arkusz widżetu
            self.home_view.use_theme(name)
        obs = getattr(self, "observatory_view", None)   # mapa maluje QPainterem — paleta jej nie odświeży (F8)
        if obs is not None:
            obs.map_view.refresh_theme()
        planner = self._gotowy("planner_view")          # akcenty planera są per MOTYW (T5, wiz R2):
        if planner is not None:                        # wyszarzenie wiersza, ⚠ nota, „bez luk", chipy
            planner.use_theme(name)
        # KOLOR WYPALONY W ITEMIE NIE ŚLEDZI MOTYWU (wiz T2 N4). `_DIM["fg"]` odświeża się przy
        # `apply_theme`, ale wiersze zbudowane WCZEŚNIEJ trzymają starą wartość — po przełączeniu
        # na jasny szarość z motywu ciemnego spadała do 2,07:1. Listy budowane z `QListWidgetItem`
        # (nie przez delegata czytającego motyw w `paint`) przemalowują się z roli rodzaju koloru
        # zapisanej przy budowie (AR-175) - dotąd powstawały na nowo z bazy: kolejka osi obiektu
        # i CAŁY rachunek liczników Porządków na wątku GUI (1,8-3,0 s na kopii pf4 tylko po kolor).
        # Oś teleskopu wypala kolor werdyktu w komórkach optyki - dotąd zostawał z poprzedniego motywu.
        for widok in ("object_view", "tasks_view", "axis_view"):
            v = getattr(self, widok, None)
            if v is not None and isValid(v):
                v.odswiez_motyw()

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
        # Aktywacja niesie znacznik klawisza: fokus listy Porządków tylko z klawiatury (AR-377). Dwuklik myszą też
        # aktywuje wiersz - w chwili aktywacji z dwukliku przycisk myszy jest wciśnięty, przy Enterze nie.
        self.nav.itemActivated.connect(
            lambda item: self._on_nav_wejscie(item, klawisz=QApplication.mouseButtons() == Qt.NoButton))
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
        #
        # RAPORT MA WŁASNĄ ETYKIETĘ, A RECEPTA STOI ZARAZ ZA NIĄ (AR-76). Raport z `showMessage`
        # malował się w polu komunikatu, więc recepta mogła stać wyłącznie wśród widżetów stałych,
        # czyli przy prawej krawędzi: firsthand mierzył raport od x≈8, a receptę od x≈1290 - dwa
        # człony jednego zdania ~700 px od siebie. Zwykły widżet paska (`addWidget`) obok
        # `showMessage` nie wchodził w grę, bo każdy komunikat go zakrywa. Teraz oba człony są
        # zwykłymi widżetami w kolejności czytania, a pole komunikatu `QStatusBar` zostaje puste
        # (pisze do niego już tylko Qt, pustym `QStatusTipEvent` z menu). Etykieta ma minimum 1 px:
        # minimum równe tekstowi trzymałoby szerokość okna przy zwężaniu, zanim elizja się powtórzy.
        # POLE ZDANIA Z PROTOKOŁU OKIEN ZAPISU (AR-218, `EtykietaBledu`): raport ze szczegółem systemu
        # (`ZdanieZeSzczegolem`) dostaje glif wskaźnika, szczegół w podpowiedzi i menu „Kopiuj
        # zdanie / Kopiuj szczegół” - plik, który padł w zamkniętym oknie, zostaje pod kursorem.
        # Tekst zwykły (nazwa pliku `<a>.fits` nie jest HTML-em) daje samo pole (AR-235).
        self.report_label = EtykietaBledu("")
        self.report_label.setMinimumWidth(1)
        self.statusBar().addWidget(self.report_label)
        self.recipe_label = QToolButton()
        # Nazwa obiektu = selektor reguły WYGASZONEJ recepty w `theme.qss` (W4): wygaszona recepta
        # to zdanie do przeczytania, więc ma tekst `secondary_text` i ramkę przerywaną, a nie
        # domyślne `disabled_text` (1,63:1 w ciemnym motywie, firsthand na platformie natywnej).
        self.recipe_label.setObjectName(theme.RECEPTA_OBJECT_NAME)
        self.recipe_label.setAutoRaise(False)
        self.recipe_label.setFocusPolicy(Qt.NoFocus)
        self.recipe_label.clicked.connect(self._wykonaj_recepte)
        self.statusBar().addWidget(self.recipe_label)
        self.recipe_label.setVisible(False)     # po dodaniu - `addWidget` pokazuje widżet
        self._czlony_recepty = ()               # człony recepty na przycisku (FH-2e: klik robi pierwszy)
        self._obiekty_wydania = None            # (con, rozjazdy) - cel gestu „Przypisz obiekt wydania”
        self._zmiany_obiektu_wydania = None     # (con, [repo.ObjectOverride]) - materiał „Cofnij”
        self._recepta_wstrzymana = False        # blokada po wykonaniu członu - dwuklik to jeden gest (Z5)
        # FAZA JEST WIDŻETEM STAŁYM, raport i recepta zwykłymi - stałe stoją przy prawej krawędzi,
        # więc faza nie wejdzie MIĘDZY raport a receptę (wchodziła, gdy recepta też była stała,
        # a faza dodana przed nią: firsthand, zrzut `K_faza.png`). Recepta przykleja się do
        # raportu, a faza siada przy uchwycie zmiany rozmiaru.
        self.phase_label = QLabel("")
        self.phase_label.setProperty("role", "secondary")
        self.statusBar().addPermanentWidget(self.phase_label)
        self._pelny_komunikat = ""              # treść przed elizją (podpowiedź + ponowny pomiar)
        self._pelna_recepta = ""                # …i jej człon drugi, bo podpowiedź niesie OBA
        self._miejsce_komunikatu = None         # miejsce nawigacji, do którego raport należy (None = żadne)
        # Wygaśnięcie raportu - własny zegar, bo etykieta nie ma timeoutu `showMessage`.
        self._zegar_raportu = QTimer(self)
        self._zegar_raportu.setSingleShot(True)
        self._zegar_raportu.timeout.connect(self._wygas_raport)
        # Okno priorytetu raportu gestu (AR-97) i raport etapu, który w nim czeka (`_raport_etapu`).
        self._zegar_priorytetu = QTimer(self)
        self._zegar_priorytetu.setSingleShot(True)
        self._zegar_priorytetu.setInterval(_PRIORYTET_GESTU_MS)
        self._zegar_priorytetu.timeout.connect(self._wypusc_raport_etapu)
        self._raport_etapu_czeka = ""
        # Raporty widoków czekające na wejście w SWOJE miejsce nawigacji (`_raport_miejsca`):
        # `{miejsce: zdanie}` - wczytanie Zbiorów i oś stanowisk po przebiegu Dostawy (AR-43).
        self._odlozone_raporty = {}
        # Wygaśnięcie raportu (`_wygas_raport`) zeruje jego pełną treść i podpowiedź. RECEPTY NIE
        # GASI (FH-2e): recepta żyje tyle, co jej prawda - gasi ją cudzy raport (`_flash`), wyjście
        # ze Zbiorów i sam widok, gdy przestaje być prawdziwa - a nie zegar komunikatu.

    def _show_view(self, idx):
        """Przełącz WIERSZ sidebara (seam dla kodu i testów) - trasę do strony i prezentacji
        rozstrzyga `_on_nav_changed` z `_TRASY`."""
        self.nav.setCurrentRow(idx)

    def _wejdz(self, idx):
        """KOMENDA prowadząca na wiersz `idx` (AR-325): strona leniwa powstaje PRZED przełączeniem wiersza. Porażka
        budowy wychodzi z komendy wyjątkiem (jedno okno błędu programu) i zatrzymuje ją, zanim cokolwiek zmieni
        sidebar albo stos - dawniej porażka w `_on_nav_changed` nie przerywała komendy, a jej następny krok budował
        stronę drugi raz (drugie okno albo sidebar „Znajdź” nad Domem). Po udanej budowie przełączenie już nic nie
        buduje."""
        self._zbuduj_strone(_TRASY[idx][0])
        self._show_view(idx)

    def show_find(self, query=None):
        """Wejście do strony zbiorów w prezentacji Znajdź - jedyna droga z Domu i z menu. `query`
        (gdy podane) zastępuje bieżący zbiór wynikiem zapytania; bez niego zbiór zostaje, jaki był.
        Wiersz sidebara przełącza stronę i prezentację (`_on_nav_changed`), a kontener dostaje
        wywołanie jeszcze raz WPROST: wejście z Domu i z menu to zamiar szukania, więc fokus ma
        trafić w pole także wtedy, gdy przełączenie oddało go liście, która go trzymała. KOMENDA (`_wejdz`): po
        porażce budowy strony nic dalej."""
        self._wejdz(NAV_ZNAJDZ)
        self.znajdz_view.show_find(query)

    def show_classic(self):
        """Wejście do strony zbiorów w prezentacji klasycznej (dzisiejszy ekran Zbiorów) - KOMENDA (`_wejdz`):
        wołający idą dalej do gridu wyłącznie po udanym wejściu."""
        self._wejdz(NAV_ZBIORY)

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
        # Strona leniwa powstaje PRZED pokazaniem (AR-325) - zaślepka nigdy nie staje na ekranie. Porażka budowy
        # (błąd programu - mówi straż oknem) cofa wiersz sidebara do ostatniego udanego wejścia: strona się nie
        # zmieniła, a następne wejście buduje od nowa.
        try:
            self._zbuduj_strone(strona)
        except BaseException:
            self.nav.blockSignals(True)
            try:
                self.nav.setCurrentRow(self._nav_ostatni)
            finally:
                self.nav.blockSignals(False)
            raise
        self._nav_ostatni = row
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
            # Raport widoku nie przechodzi do cudzego miejsca - gaśnie tą samą drogą, co po czasie.
            # Gest obiektu wydania gaśnie RAZEM z nim także przy wejściu w Zbiory: inaczej przycisk
            # „Przypisz obiekt wydania” stałby tam bez swojego zdania, a recepta Zbiorów nie
            # zastąpiłaby go (`_recepta_gridu` chroni gest wydania).
            if self._gest_wydania_aktywny():
                self._ustaw_recepte("")
            self._wygas_raport()
        # Recepta gridu mówi o Zbiorach, więc poza nimi gaśnie z paska - a przy powrocie widok podaje
        # ją ze stanu, o ile wciąż jest prawdą (FH-2e). Drugi nadawca - gest obiektu wydania po żniwach
        # (`_pokaz_gest_obiektu_wydania`) - żyje w miejscu, w którym padł jego raport, i gaśnie z nim.
        # Dom dostaje ją osobno, ze strumienia (`_recepta_gridu`).
        # Recepta osi Porządków (AR-296, AR-133) mówi o Porządkach: schodzi także przy wejściu w Zbiory -
        # dawniej zostawała tam, gdy grid nie miał własnej recepty, a wynik jej wykonania szedł odłożony
        # do Porządków, czyli tam, gdzie człowieka nie było.
        if strona == STRONA_PORZADKI:
            # Przed przywróceniem recepty: wpis kolejki odłożeń, któremu baza nic nie zostawiła (gest zamknięty inną
            # drogą - CLI, drugie okno), schodzi razem ze swoją receptą (`_zdejmij_martwa_recepte`, AR-321).
            self.object_view.oczysc_martwe()
        stan = self._recepta_porzadkow_stan
        if strona != STRONA_ZBIORY or (stan is not None and self._czlony_recepty is stan[0].czlony):
            self._ustaw_recepte("")
        msg = self._odlozone_raporty.pop(strona, "")
        if msg:
            # Raport z chwili, gdy tego miejsca nie było widać - pada teraz, przy nim. Raport, z którym
            # związana jest recepta Porządków, staje bez wiązania: z receptą ponowienia nie gaśnie po
            # jednej wizycie (AR-296).
            self._flash(msg, miejsce=None if stan is not None and stan[1] is msg else strona)
        if strona == STRONA_ZBIORY:
            self.grid_view.ponow_recepte()
        if strona == STRONA_PORZADKI and stan is not None and stan[1] is self._pelny_komunikat:
            # Recepta wraca razem z raportem, z którym przyszła - także odłożonym: `_flash` wyżej
            # postawił na pasku TEN SAM obiekt raportu (AR-296).
            self._pokaz_recepte(stan[0])
        if strona == STRONA_PORZADKI:
            # Recepta osi odłożona przez blokadę, która nie mogła paść (stała inna recepta, zgasła bez kliku),
            # wraca przy wejściu tam, gdzie mieszka (AR-321) - o ile nic jej nie blokuje i nic nie stoi - doklejona
            # do raportu odłożonego do Porządków, który właśnie stanął: nie zastępuje go.
            self.object_view.podaj_odlozone(doklej=msg or None)
        if strona == STRONA_DOM:
            # Dom mówi o bazie w chwili wejścia. Przełączenie z listy (strzałki, klik) czeka na
            # postój - klik i Enter odczytują od razu w `_on_nav_wejscie`; z kodu (Dom, menu) od razu.
            if self.nav.hasFocus():
                self._dom_po_postoju.start()
            else:
                self._odswiez_dom()
        if strona == STRONA_PORZADKI:   # wejście w Porządki = świeży stan liczników zadań
            # Bez rachunku, gdy baza bez zmian (AR-84); przy zmianie w trybie wątków tła - rachunek w tle
            # z listą nieaktualną do wyniku (AR-337, rachunek wejścia w tle; tryb zna widok od montażu, AR-380).
            self.tasks_view.odswiez_przy_wejsciu()
        if strona == STRONA_DOSTAWA:
            # Raport „co przyszło” liczy się ze stanu, a nazwę mogła nadać ręka w Porządkach albo
            # w Zbiorach - wiersz „nie rozpoznałem” po powrocie kłamałby o niej (jedno zapytanie
            # zawężone do dostawy; bez raportu w tej sesji nic się nie liczy).
            self.przyjmij_view.odswiez_raport()
        if strona == STRONA_PLANER and self.planner_view.bez_stanowiska:
            # Stanowisko wskazuje się na innym ekranie (AR-48), więc pusty stan „bez stanowiska"
            # przelicza się przy każdym wejściu, dopóki jest prawdą - gest z pustego stanu obiecuje,
            # że plan policzy się po powrocie.
            self.planner_view.refresh()

    def _on_nav_wejscie(self, item, *, klawisz=False):
        """Klik albo Enter na wierszu: Znajdź oddaje fokus polu zapytania (`show_find` bez zapytania
        nie zmienia zbioru), Dom odczytuje się od razu, bez czekania na postój.

        Porządki - WYŁĄCZNIE z klawiatury (`klawisz=True`, aktywacja wiersza Enterem, AR-377): fokus tam, gdzie człowiek
        na Porządkach pracuje (`TasksView.fokus_z_klawiatury` - lista albo „← Porządki” podstrony), więc następny Enter
        działa bez Tab (pętla Popraw z klawiatury). Klik i dwuklik myszą fokusu nie przenoszą - lista z fokusem pokazuje
        natywną obwódkę bieżącego wiersza (zmierzone natywnie w obu motywach), a dla myszy byłby to nowy widoczny stan
        po każdym wejściu."""
        row = self.nav.row(item)
        if row == NAV_ZNAJDZ:
            # Wejście nieudane (porażka budowy strony - `_on_nav_changed` cofnął wiersz) - nic dalej: odczyt widoku
            # budowałby stronę drugi raz w tym samym geście.
            if self.nav.currentRow() == NAV_ZNAJDZ:
                self.znajdz_view.show_find()
        elif row == NAV_DOM:
            self._dom_po_postoju.stop()
            self._odswiez_dom()
        elif row == NAV_PORZADKI and klawisz and self.nav.currentRow() == NAV_PORZADKI:
            self.tasks_view.fokus_z_klawiatury()

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
        self._nav_ostatni = row

    def _zatrzymaj_watki_widokow(self):
        """Zbierz wątki tła widoków, ZANIM widoki znikną (przełączenie bazy, zamknięcie okna).
        `QThread` jest dzieckiem widoku, więc kasowany razem z nim w biegu zabiłby aplikację,
        a wynik doręczony później trafiłby w zamknięte połączenie. Po kluczu metody, nie po
        typie: widok bez wątku tła po prostu jej nie ma.

        Grid nie stoi wprost na stosie (siedzi w kontenerze strony zbiorów), więc jego wątki
        zbieramy jawnie - pytanie samych stron stosu zgubiłoby skład zbioru i pokrycie pól.
        Metody są idempotentne, więc kontener, który kiedyś zacznie delegować, nie szkodzi.

        Okna dialogowe też: zamknięte okno z wątkiem w biegu zostaje ukrytym dzieckiem okna głównego
        razem ze swoim `QThread` (lista wydań w oknie żniw chodzi po kartach SMB i nie ma punktu
        przerwania; bez wątku okno zwalnia się samo, `HarvestDialog._zwolnij_gdy_wolne`), więc
        wątek w biegu przy wyjściu z aplikacji zabiłby ją tak samo jak wątek widoku."""
        widoki = [self.stack.widget(i) for i in range(self.stack.count())]
        # Oś obiektu siedzi w stronie Porządków (`TasksView`) - jej generacja cofnięcia z paska
        # unieważnia spóźnione callbacki (AR-296), więc pytamy ją jawnie, jak grid. Warunkiem jest
        # ŻYWY widok, nie niepusty stos: montaż przerwany wyjątkiem (AR-302, start z bazą) zostawia
        # grid z wątkiem w biegu, zanim jakakolwiek strona trafi na stos.
        # Strona leniwa (AR-325): grid tylko zbudowany (`_gotowy` - zbieranie wątków nie buduje strony), a widoki
        # budowy w toku (zamknięcie w trakcie `_zbuduj_strone`) też.
        widoki.extend(v for v in (self._gotowy("grid_view"), self.object_view) if v is not None and isValid(v))
        for utworzone in self._w_budowie.values():
            widoki.extend(v for v in utworzone if isValid(v))
        widoki.extend(self.findChildren(QDialog))
        for w in widoki:
            zatrzymaj = getattr(w, "zatrzymaj_pola", None)
            if zatrzymaj is not None:
                zatrzymaj()

    def _clear_views(self):
        self._zatrzymaj_watki_widokow()
        # Faza tła mówi o liczeniu widoku, który znika (AR-175) - nowa baza stawia własną.
        self._faza_tla = ""
        self._seria_montazu = None
        self._pokaz_faze()
        self._odlozone_raporty.clear()       # raporty odłożone mówią o widokach, które właśnie znikają
        # Wykonawcy członów recepty wiszą na gridzie, który zaraz pójdzie do `deleteLater` - recepta
        # schodzi z paska tu, a nie dopiero przy pierwszym raporcie nowej bazy (Z9).
        self._ustaw_recepte("")
        self._recepta_strumienia = None
        self._recepta_porzadkow_stan = None  # wykonawca na osi, która zaraz zniknie (AR-296)
        self.home_view = None
        # Strony leniwe i zatrzaski stanu (AR-325) mówią o bazie, która znika: widoki stron zbudowanych schodzą
        # razem ze stosem (grid w kontenerze Znajdź, pipeline w kontenerze Dostawy), zaślepki też.
        self._strony.clear()
        self._zaslepki.clear()
        self._wstrzymaj_dobudowe()           # zegar i kotwice dobudowy mówią o stronie, której już nie ma
        self._kotwica_malowania = self._kotwica_licznikow = False
        self._plakietka_padla = False        # „Porządki (!)” mówi o rachunku widoku, który znika (AR-326)
        self._dostawa_w_biegu = False
        self._zapis_w_biegu = {"os": False, "grid": False}
        self._nav_ostatni = NAV_DOM
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
        `observatory_view`/`object_view` przeżywa przemontowanie bez zmian.

        STRONY LENIWE (AR-325): montaż buduje Dom (strona startu) i Porządki (plakietka, aliasy osi), a na
        indeksach Zbiorów, Dostawy i Planera stawia puste zaślepki - te strony buduje `_zbuduj_strone` przy
        pierwszym wejściu albo pierwszym dostępie do ich atrybutu. Wiązania z nimi idą przez gospodarza:
        KOMENDY człowieka (wiersz przerwanej zmiany obiektu, „?” Porządków, „Wydaj” Domu, takt 3 naprawy) budują
        adresata przed wykonaniem, POWIADOMIENIA stanu (mutex zapisu, koniec przebiegu, gest osi z raportu
        Dostawy) dochodzą wyłącznie do stron zbudowanych (`_gotowy`). Kolejność stron na stosie = `STRONA_*`."""
        from horreum.gui.tasks import TasksView                # lazy: Qt-import tylko gdy montujemy
        from horreum.gui.home import HomeView

        self._clear_views()
        motyw = theme.normalize(QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))

        # Osie Porządków bez odczytu w montażu (AR-175) - własny przełącznik `_osie_leniwie` (AR-326); token
        # montażu w konstruktorze rozróżnia sygnały tego widoku od spóźnionych sygnałów widoku sprzed zmiany bazy.
        self._montaz += 1
        tasks = TasksView(self.con, now_fn=self._now, leniwie=self._osie_leniwie, montaz=self._montaz,
                          w_tle=self._pola_poza_watkiem)        # tryb rachunku wejścia od montażu (AR-380)
        self.tasks_view = tasks
        self.axis_view = tasks.axis_view
        self.observatory_view = tasks.observatory_view
        self.object_view = tasks.object_view
        # Kolejka odłożonych recept osi należy do OKNA i tej bazy (AR-321): powrót do bazy oddaje ją nowej osi.
        # Oś pyta gospodarza, czy recepta stoi na pasku, zanim poda następny wpis (straż stojącej recepty).
        tasks.object_view.uzyj_kolejki(self._kolejki_osi.setdefault(queries.klucz_bazy(self.db_path), []))
        tasks.object_view.recepta_stoi = self._recepta_stoi
        # Takt 3 P-D: okno naprawy nagłówka nie ma własnego resolvera — dostaje ISTNIEJĄCĄ drogę
        # etapu wraz z przełączeniem widoku na Dostawę (precedens „3→1"). Wstrzykiwane TU, bo tylko
        # gospodarz zna obie powierzchnie.
        tasks.object_view.run_stage_fn = self._resolve_after_repair
        # Zapis do plików z paska osi (AR-296) - zatrzask stanu i mutex do zbudowanych stron (AR-325): grid gasi
        # szufladę, Dostawa i jej raport gasną. Wiązania gridu (gest Zbiorów → oś, plakietka) podpina budowniczy
        # strony Zbiorów (`_zbuduj_zbiory`), bo grid powstaje później.
        tasks.object_view.writeback_busy.connect(self._na_zapis_osi)
        # OSIE PORZĄDKÓW MÓWIĄ PRZY ODŚWIEŻENIU („Brak stanowisk na osi…”, „Brak obiektów dla tego
        # filtra…”), a odświeżają się też po przebiegu Dostawy - zdanie przykrywało wtedy status
        # etapu (AR-43), a odmowę kafla Przyjmij wypierało razem z czekającym „gotowe” (AR-97). Ta
        # sama droga, co raport wczytania Zbiorów: przy widocznych Porządkach pada od razu, poza nimi
        # czeka na wejście w nie.
        for v in (tasks.axis_view, tasks.object_view, tasks.observatory_view):
            v.status_message.connect(
                lambda msg: self._raport_miejsca(msg, STRONA_PORZADKI, wiaz=False))
        # „Cofnij dopisanie” po „Dopisz nowy…” (AR-133) - recepta gestu osi na pasek gospodarza.
        tasks.object_view.status_recipe.connect(self._recepta_porzadkow)
        tasks.open_collection.connect(self._on_open_collection)
        # Wiersz „Przerwane zmiany obiektu” (AR-121) otwiera okno przebiegu przez Zbiory - tam
        # mieszka mutex zapisu i odświeżenie zbioru oraz plakietki po zapisie albo cofnięciu. KOMENDA (AR-325):
        # gospodarz buduje Zbiory przed wykonaniem.
        tasks.open_object_change_run.connect(self._on_przebieg_zmiany_obiektu)
        # Wiersz „?" Porządków prowadzi tam, gdzie jest jego robota - do Dostawy (AR-28 (b)) - i
        # niesie powód: linia nad akcjami mówi, po co człowiek tu jest. Obie drogi do sygnału
        # (wiersz „?”, pusta perspektywa kopii) czekają na fakty kopii, więc powód jest jeden. KOMENDA (AR-325,
        # `_on_open_intake`): Dostawa budowana przed wykonaniem.
        tasks.open_intake.connect(self._on_open_intake)
        tasks.counts_changed.connect(self._on_tasks_counts)
        tasks.liczenie_w_toku.connect(self._on_liczenie_w_toku)   # faza tła (AR-175)
        tasks.rachunek_padl.connect(self._on_rachunek_padl)       # „Porządki (!)” (AR-326)

        # Dom: zamiary człowieka → istniejące drogi. Teczki w tle chodzą razem z wątkami tła
        # Zbiorów - test, który wyłącza tamte, dostaje też przewidywalny Dom.
        home = HomeView(self.con, now_fn=self._now, theme_name=motyw,
                        poza_watkiem=self._pola_poza_watkiem)
        home.przyjmij.connect(self._on_przyjmij)
        home.znajdz.connect(lambda: self.show_find())
        home.wydaj.connect(self._on_wydaj_domu)             # KOMENDA (AR-325): buduje Zbiory przed oknem wydania
        home.popraw.connect(lambda: self._show_view(NAV_PORZADKI))
        # „Wciągnij z WBPP…” w „Więcej…” Domu nie liczy reguły sam (AR-354): przy KAŻDYM otwarciu menu pyta gospodarza
        # (`_powod_odmowy_zniw` - ta sama reguła, co klik). Bieg Dostawy, sonda źródła i zapis do plików (także
        # cofnięcie zapisu kart z paska Porządków, AR-296) gaszą pozycję z jednego źródła.
        home.btn_wiecej.menu().aboutToShow.connect(lambda: home.ustaw_zniwa(self._powod_odmowy_zniw()))
        tasks.object_view.wynik_cofniecia.connect(self._wynik_cofniecia_osi)   # bez odkładania (AR-296)
        tasks.object_view.recepta_martwa.connect(self._zdejmij_martwa_recepte)  # recepta martwego wpisu (AR-321)
        # „Cofnij dopisanie” z Osi teleskopu - droga trwała zamyka gest; wpis kolejki odłożeń schodzi (AR-321).
        tasks.axis_view.dopisanie_cofniete.connect(self._na_cofniete_dopisanie)
        home.teczka.connect(self._on_teczka_domu)
        home.wiecej.connect(self._on_wiecej_domu)
        home.recepta_klik.connect(
            lambda: self._wykonaj_recepte(czlony=self._recepta_strumienia.czlony
                                          if self._recepta_strumienia else ()))
        self.home_view = home

        # Kolejność = `STRONA_*`; strony leniwe dostają zaślepkę (AR-325), budowa podmienia ją w miejscu.
        for strona, widget in ((STRONA_DOM, home), (STRONA_ZBIORY, None), (STRONA_DOSTAWA, None),
                               (STRONA_PORZADKI, tasks), (STRONA_PLANER, None)):
            if widget is None:
                widget = QWidget()
                self._zaslepki[strona] = widget
            assert self.stack.count() == strona, "strony stosu muszą stać w kolejności STRONA_*"
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
        # Badge żywy od MONTAŻU (F5R#1) - connect i pozycje nav już stoją. RACHUNEK W TLE (AR-175):
        # synchronicznie stał tu ~1,5 s z ~2,9-3,0 s całego otwarcia bazy na kopii pf4 (strażnik stosów,
        # mediana 3 biegów); w trybie bez wątków (seam testów) zostaje synchroniczny. Do wyniku plakietka
        # i kafel Domu mówią „liczę” („Porządki (…)”, „Popraw · …”) - gołe „Porządki” znaczy zero,
        # a wynik zdejmuje oba drogą `_on_tasks_counts`; pasek mówi fazę tła (`_on_liczenie_w_toku`).
        self._seria_montazu = None
        tasks.refresh_counts(w_tle=self._pola_poza_watkiem)
        if tasks.liczy_w_tle():
            self.nav.item(NAV_PORZADKI).setText(i18n.t("nav.porzadki_count", n="…"))
            home.ustaw_popraw(None)
        else:
            self._kotwica_licznikow = True   # rachunek montażu policzony synchronicznie - kotwica dobudowy stoi
            # Seria montażu „była” (numer 0 - widok numeruje serie od 1): późniejsza seria w tle (gest Zbiorów,
            # wejście w Porządki - AR-337) nie może udawać serii montażu - faza „Liczę…” na pasku i druga
            # kotwica dobudowy (`_on_liczenie_w_toku`) należą wyłącznie do montażu.
            self._seria_montazu = 0
        if not self._strony_leniwie:
            self.zbuduj_strony()

    # ---------------------------------------------------------------- strony leniwe (AR-325)

    def _gotowy(self, nazwa):
        """Widok strony leniwej, jeśli strona JUŻ powstała, inaczej `None` - BEZ budowania (AR-325). Dla
        powiadomień stanu: strona niezbudowana przeczyta świeży stan przy budowie, a zatrzaski
        (`_dostawa_w_biegu`, `_zapis_w_biegu`) przyłoży jej budowniczy."""
        return self._strony.get(nazwa)

    def zbuduj_strony(self):
        """Zbuduj wszystkie strony leniwe tej bazy (AR-325) - jawne wejście dla testu, który chce całego okna,
        i dla montażu z `_strony_leniwie = False`. Idempotentne: strona zbudowana zostaje."""
        for strona in _WIDOKI_STRONY:
            self._zbuduj_strone(strona)

    def _zamow_dobudowe(self):
        """Zamów dobudowę strony Zbiorów w bezczynności (`_zbiory_w_bezczynnosci`, AR-325) po otwarciu bazy w POKAZANYM
        oknie: koniec `_open_path` (start z `main` - okno stoi przed bazą) albo `showEvent` (baza otwarta
        w konstruktorze, okno pokazane później). Zamawia kotwicę malowania (`_PoMalowaniu`), o ile jej jeszcze nie
        ma; zegar rusza w `_sprawdz_dobudowe`. Okno niepokazane, bez bazy albo ze stroną już zbudowaną - nic."""
        if not self._dobudowa_mozliwa():
            return
        if self._kotwica_malowania:
            self._sprawdz_dobudowe()
        else:
            self._po_malowaniu.zamow()

    def _dobudowa_mozliwa(self):
        """Warunek stanu dobudowy: przełącznik, otwarta baza, pokazane okno, strona Zbiorów jeszcze niezbudowana i nie
        w budowie (zegar uzbrojony w fazie składu budowy na żądanie wszedłby w nią drugi raz)."""
        return (self._zbiory_w_bezczynnosci and self.con is not None and self.isVisible()
                and STRONA_ZBIORY in self._zaslepki and STRONA_ZBIORY not in self._w_budowie)

    def _na_malowanie_domu(self):
        """Kotwica malowania (`_PoMalowaniu`): Dom bazy, która właśnie się otworzyła, jest już namalowany."""
        self._kotwica_malowania = True
        self._sprawdz_dobudowe()

    def _po_licznikach_montazu(self):
        """Kotwica liczników: seria liczników Porządków montażu skończyła się (wynik albo porażka) albo liczyła się
        synchronicznie. Dobudowa w trakcie serii odbierała jej GIL - zmierzone A/B przeplatane na kopii pf4: pierwszy
        wynik Porządków 2177-3835 ms z dobudową wobec 1183-2362 ms bez niej."""
        self._kotwica_licznikow = True
        self._sprawdz_dobudowe()

    def _sprawdz_dobudowe(self):
        """Obie kotwice montażu stoją i stan pozwala - zegar dobudowy rusza (pierwszy wolny obrót pętli)."""
        if self._kotwica_malowania and self._kotwica_licznikow and self._dobudowa_mozliwa():
            self._dobudowa_zbiorow.start()

    def _wstrzymaj_dobudowe(self):
        """Zegar dobudowy i zamówiona kotwica malowania schodzą (otwarcie bazy, demontaż, zamknięcie okna)."""
        self._dobudowa_zbiorow.stop()
        self._po_malowaniu.odwolaj()

    def _dobuduj_zbiory(self):
        """Zegar dobudowy (`_zamow_dobudowe`). Strony zbudowanej w międzyczasie (klik w Zbiory, komenda) zegar nie
        dotyka - budowa na żądanie go zatrzymuje, a `_zbuduj_strone` strony zbudowanej nie buduje drugi raz. Porażka
        budowy to błąd programu (mówi straż oknem): zaślepka zostaje, następne wejście buduje od nowa, zegar nie
        ponawia."""
        self._zbuduj_strone(STRONA_ZBIORY)

    def _zbuduj_strone(self, strona):
        """Zbuduj stronę leniwą `strona` (`STRONA_*`) i podmień nią zaślepkę na stosie. Strona zbudowana,
        strona nieleniwa i okno bez bazy - nic.

        FAILURE-ATOMIC (AR-325): widoki strony powstają bez rodzica stosu i każdy trafia na listę budowy
        (`_w_budowie`) zaraz po utworzeniu. Wyjątek w budowie zbiera wątki tła każdego już utworzonego widoku
        (`zatrzymaj_pola` - `QThread` skasowany w biegu to twardy abort, `FramesView.zatrzymaj_pola`), kasuje je,
        zostawia zaślepkę i słownik stron bez wpisu i leci dalej (błąd programu - mówi straż oknem); następne
        wejście buduje od nowa. EXPECT: budowa tej samej strony w trakcie jej budowy to błąd programu."""
        zaslepka = self._zaslepki.get(strona)
        if zaslepka is None:
            return
        if strona == STRONA_ZBIORY:
            # Budowa na żądanie przed zegarem dobudowy zdejmuje zegar, ZANIM ruszy: skład zbioru bez wątków tła idzie
            # pod fazą (`busy.repaint` kręci pętlę), a zegar wszedłby w nią budową tej samej strony (asercja niżej).
            self._dobudowa_zbiorow.stop()
        assert strona not in self._w_budowie, f"strona {strona} budowana ponownie w trakcie budowy"
        utworzone = self._w_budowie[strona] = []
        budowniczy = {STRONA_ZBIORY: self._zbuduj_zbiory, STRONA_DOSTAWA: self._zbuduj_dostawe,
                      STRONA_PLANER: self._zbuduj_planer}[strona]
        try:
            widoki, kontener = budowniczy(utworzone)
        except BaseException:
            for w in reversed(utworzone):
                zatrzymaj = getattr(w, "zatrzymaj_pola", None)
                if zatrzymaj is not None and isValid(w):
                    zatrzymaj()
            for w in reversed(utworzone):
                if isValid(w):
                    w.setParent(None)
                    w.deleteLater()
            raise
        finally:
            del self._w_budowie[strona]
        # Krok świadomie BEZ obwódki: operacje na stosie i słowniku nie czytają danych i nie startują wątków,
        # więc nie mają porażki, którą trzeba by zwijać (wyjątek tu byłby błędem Qt, nie stanem bazy).
        self._strony.update(widoki)
        indeks = self.stack.indexOf(zaslepka)
        self.stack.insertWidget(indeks, kontener)
        self.stack.removeWidget(zaslepka)
        zaslepka.deleteLater()
        del self._zaslepki[strona]

    def _zbuduj_dostawe(self, utworzone):
        """Strona Dostawy: TEN SAM `PipelineView` w kontenerze z raportem „Co przyszło” (jak Znajdź nad
        gridem) - drugi widok Dostawy rozjechałby wątek etapów, mutex i przyciski. Zatrzaski przyłożone przed
        udostępnieniem strony: zapis do plików w toku gasi Dostawę i jej raport, zatrzask biegu (zgłoszony
        gospodarzowi, zanim strona powstała) gasi gest raportu."""
        from horreum.gui.pipeline import PipelineView               # lazy: Qt-import tylko gdy budujemy
        from horreum.gui.flows.przyjmij import PrzyjmijView
        pipeline = PipelineView(self.db_path, now_fn=self._now)
        utworzone.append(pipeline)
        pipeline.status_message.connect(self._flash_dostawy)
        pipeline.stage_status.connect(self._raport_etapu)   # „<etap>: gotowe.” ustępuje gestowi (AR-97)
        # `stage_finished` ŚWIADOMIE NIEPODPIĘTE: widoki odświeża koniec PRZEBIEGU
        # (`running_changed(False)`), nie koniec etapu - patrz `_odswiez_widoki_po_przebiegu`.
        pipeline.running_changed.connect(self._on_pipeline_running)
        pipeline.open_collection.connect(self._on_open_collection)   # P5b: raport → perspektywa (3→1)
        # „Wciągnij z WBPP…”: okno żniw potrzebuje połączenia z bazą, którego Dostawa nie trzyma.
        pipeline.open_harvest.connect(self._on_open_harvest)
        pipeline.set_work_root(self._work_wbpp())   # widok powstaje z każdą bazą, folder roboczy jest jeden
        przyjmij = PrzyjmijView(self.con, pipeline, now_fn=self._now)
        utworzone.append(przyjmij)
        przyjmij.status_message.connect(self._flash)
        przyjmij.open_tasks.connect(self._on_kubelek_porzadkow)
        # Gest „Przypisz obiekt…” z raportu dostawy - POWIADOMIENIE przez gospodarza (`_po_osi_z_raportu`):
        # Zbiory mogą jeszcze nie istnieć.
        przyjmij.object_axis_changed.connect(self._po_osi_z_raportu)
        if self._zatrzask_zapisu():
            pipeline.set_writeback_busy(True)
            przyjmij.set_writeback_busy(True)
        if self._dostawa_w_biegu:
            przyjmij.set_busy(True)
        return {"pipeline_view": pipeline, "przyjmij_view": przyjmij}, przyjmij

    def _zbuduj_zbiory(self, utworzone):
        """Strona zbiorów: grid w kontenerze z paskiem Znajdź - dwie prezentacje jednego stanu zbioru, nie dwa
        gridy (JEDEN-STAN-EKRANU). Grid startuje skład zbioru w wątku tła od `__init__` (AR-27) - to jego wątki
        w montażu odbierały GIL reszcie otwarcia bazy (AR-325). Zatrzaski: bieg Dostawy i zapis z paska osi."""
        from horreum.gui.grid import FramesView                      # lazy: Qt-import tylko gdy budujemy
        tasks, home = self.tasks_view, self.home_view
        grid = FramesView(self.con, now_fn=self._now, pola_poza_watkiem=self._pola_poza_watkiem)
        utworzone.append(grid)
        grid.status_message.connect(self._flash_grid)
        grid.load_report.connect(self._raport_wczytania_gridu)
        grid.ponow_raport_wczytania()        # zbiór startu jedzie z wątku tła od `__init__` (AR-27)
        grid.status_recipe.connect(self._recepta_gridu)   # recepta ma własny nośnik (FH-2)
        grid.writeback_busy.connect(self._on_writeback_busy)
        # Gesty panelu Rodowód (R2 oś stosu, E4-5 oś kalibracji) domykają się etapem Dostawy z NAZWĄ etapu -
        # bez tego user wędrował na inny ekran po przycisk stojący obok wyboru katalogu (firsthand 0808).
        grid.run_stage_fn = self._etap_po_gescie_rodowodu
        # Dwuklik w panelu rodowodu prowadzi do klatek w Zbiorach - nawigację zna gospodarz.
        grid.show_frames_fn = self.show_frames_in_collections
        # CZWARTA POWIERZCHNIA gestu osi obiektu (S2b, §4/14c-f): gest z paska Zbiorów zmienia kolejkę
        # przeglądu w oknie osi - a tamten widok nie ma skąd o tym wiedzieć. Gospodarz zna obie strony, więc
        # to on je łączy (grid nie importuje osi, oś nie importuje gridu). Leniwie (AR-84): niewidoczna oś
        # przeładuje się przy pokazaniu - gest pada w Zbiorach. Teczki Domu liczą godziny per obiekt.
        grid.object_axis_changed.connect(tasks.object_view.odswiez_gdy_widoczny)
        grid.object_axis_changed.connect(home.odswiez_teczki)
        grid.observatory_axis_changed.connect(tasks.observatory_view.refresh)   # przeniesione stanowisko
        # …i PIĄTA: badge sidebara, widoczny CAŁY CZAS - sygnał STANU PORZĄDKÓW z ogona każdego gestu gridu
        # (`object_axis_changed` milczał przy gestach żywotności klatki), liczony W TLE (AR-84: 557 ms
        # w ogonie gestu na kopii pf4), ten sam przełącznik co skład zbioru.
        grid.stan_porzadkow_changed.connect(
            lambda: self.tasks_view.refresh_counts(w_tle=self._pola_poza_watkiem))
        # Pusta perspektywa kopii w Zbiorach mówi zdaniem wiersza „?” i prowadzi tą samą drogą - sygnał na
        # sygnał, więc droga do Dostawy ma jedno podpięcie (komenda `_on_open_intake`).
        grid.open_intake.connect(tasks.open_intake)
        znajdz = ZnajdzView(grid)
        utworzone.append(znajdz)
        # Przełączenie prezentacji z wnętrza strony („Zbiory klasyczne" na pasku czasowników Znajdź) przesuwa
        # wiersz sidebara - inaczej sidebar mówiłby „Znajdź" nad ekranem klasycznym.
        znajdz.prezentacja_zmieniona.connect(self._on_prezentacja_zmieniona)
        if self._dostawa_w_biegu:
            grid.set_busy(True)
        if self._zapis_w_biegu["os"]:
            grid.set_writeback_busy(True)
        return {"grid_view": grid, "znajdz_view": znajdz}, znajdz

    def _zbuduj_planer(self, utworzone):
        """Strona Planera. Motyw PRZEKAZANY, nie czytany przez widok z rejestru (wiz T5 N4 - jeden właściciel
        faktu). Bieg Dostawy - parametr konstruktora (AR-325, AR-334): planer wygaszony od chwili budowy i bez rachunku
        nocy do końca przebiegu (liczy go `refresh` z `_odswiez_widoki_po_przebiegu`), a nie zatrzask po konstruktorze,
        który już policzył."""
        from horreum.gui.planner import PlannerView                  # lazy: Qt-import tylko gdy budujemy
        motyw = theme.normalize(QSettings("Horreum", "Horreum").value("ui/theme", theme.DEFAULT))
        planner = PlannerView(self.con, db_path=self.db_path, now_fn=self._now, theme_name=motyw,
                              w_biegu=self._dostawa_w_biegu)
        utworzone.append(planner)
        planner.status_message.connect(self._raport_planera)
        planner.open_sites.connect(self._on_open_sites)                # AR-48: pusty stan → stanowiska
        planner.show_frames_for.connect(self._on_show_target_frames)   # T5e: most planer → grid
        return {"planner_view": planner}, planner

    def _on_przebieg_zmiany_obiektu(self, run_id):
        """KOMENDA (AR-325): wiersz „Przerwane zmiany obiektu” Porządków otwiera okno przebiegu przez Zbiory -
        strona Zbiorów powstaje przed wykonaniem."""
        self.grid_view.otworz_przebieg_zmiany_obiektu(run_id)

    def _on_open_intake(self):
        """KOMENDA (AR-325, AR-327): wiersz „?” Porządków albo pusta perspektywa kopii w Zbiorach prowadzi do
        Dostawy z powodem - strona Dostawy powstaje przed wykonaniem, linia powodu staje PRZED pokazaniem
        strony, a klik to jawna komenda: fokus klawiatury trafia w gest powodu (`fokus=True`); zwykłe wejście
        w Dostawę (sidebar, strzałki) fokusu nie rusza."""
        from horreum.gui.pipeline import REASON_COPY_FACTS
        self.pipeline_view.show_reason(REASON_COPY_FACTS, fokus=True)
        self._show_view(NAV_DOSTAWA)

    def _on_wydaj_domu(self):
        """KOMENDA (AR-325): kafel „Wydaj” Domu otwiera okno wydania obiektu gridu - strona Zbiorów powstaje
        przed wykonaniem (okno stoi nad Domem, strona się nie zmienia)."""
        self.grid_view._open_object_release()

    def _po_osi_z_raportu(self):
        """POWIADOMIENIE (AR-325): gest „Przypisz obiekt…” z raportu dostawy zmienia tę samą oś, co gest
        Zbiorów - kolejka osi, plakietka Porządków (w tle, AR-84), teczki Domu i grid, jeśli jest (facet Obiekt
        liczy się w `_refresh`); gest z raportu nie nawiguje w Zbiorach - zaznaczenie zostaje (AR-172). Zbiory
        niezbudowane przeczytają świeży stan przy budowie."""
        self.tasks_view.object_view.odswiez_gdy_widoczny()
        self.tasks_view.refresh_counts(w_tle=self._pola_poza_watkiem)
        self.home_view.odswiez_teczki()
        grid = self._gotowy("grid_view")
        if grid is not None:
            grid.przeladuj_z_zaznaczeniem()

    def _na_cofniete_dopisanie(self, telescope_id):
        """„Cofnij dopisanie” Osi teleskopu zamknął gest „Dopisz nowy…” teleskopu `telescope_id` (AR-133) - wpis tego
        zamiaru schodzi z kolejki odłożonych recept osi obiektu tej bazy razem z receptą, którą już podał (AR-321,
        `ObjectAxisView.oczysc_martwe` - baza mówi, że gest zamknięty): podany drugi raz ogłaszałby „znów możliwe”
        gestu, którego już nie ma, i zasłaniał wpis za nim.

        Zdjęta głowa PODANA ustępuje następnemu niepodanemu wpisowi (AR-355): jego gotowość dochodzi do zdania
        wyniku gestu Osi teleskopu, które stoi na pasku (`doklej`) - dawniej wpis za zdjętą głową czekał na wejście
        w Porządki."""
        if self.object_view.oczysc_martwe():
            self.object_view.podaj_odlozone(doklej=self._pelny_komunikat or None, tylko_niepodane=True)

    def _zdejmij_martwa_recepte(self, recepta, przed):
        """Wpis kolejki odłożeń, któremu baza nic nie zostawiła, podał wcześniej `recepta` (AR-321,
        `ObjectAxisView.recepta_martwa`). Rozpoznanie po TOŻSAMOŚCI obiektu recepty, nie po tekście: stan recepty
        Porządków schodzi (wejście w Porządki jej nie przywróci), przycisk paska też, a raport z jej zdaniem
        gotowości, gdy wciąż stoi na pasku, ustępuje zdaniu, do którego go doklejono (`przed`), albo gaśnie.

        Zdjęcie STOJĄCEJ gotowości gospodarz pamięta razem z tym, co wróciło na pasek (`_zdjeta_gotowosc`, AR-355):
        tylko wtedy aktywacja okna ma czym podać następny wpis - gotowość przykryta innym raportem (raport Zbiorów ze
        szczegółem, zdanie postępu cofnięcia) już nie stoi, więc nic nie ustępuje i raport zostaje."""
        stan = self._recepta_porzadkow_stan
        if stan is None or stan[0] is not recepta:
            return
        self._recepta_porzadkow_stan = None
        if self._czlony_recepty is recepta.czlony:
            self._ustaw_recepte("")
        if stan[1] is self._pelny_komunikat:
            self._zdjeta_gotowosc = (przed or None,)
            if przed:
                self._flash(przed, miejsce=None)
            else:
                self._wygas_raport()

    def _na_zapis_osi(self, busy):
        """Zapis do plików z paska osi obiektu (cofnięcie commitu kart, AR-296): zatrzask stanu PRZED
        rozesłaniem (AR-325), potem mutex zbudowanych stron - szuflada Zbiorów dostaje stan TEGO źródła (druga strona
        mutexu, `FramesView.set_writeback_busy`: flaga o cudzej operacji), Dostawa i jej raport - zatrzask gospodarza
        (`_rozeslij_zatrzask_zapisu`). Dom pyta gospodarza przy otwarciu menu (`_powod_odmowy_zniw`)."""
        self._zapis_w_biegu["os"] = bool(busy)
        grid = self._gotowy("grid_view")
        if grid is not None:
            grid.set_writeback_busy(busy)
        self._rozeslij_zatrzask_zapisu()

    def _rozeslij_zatrzask_zapisu(self):
        """JEDNA PRAWDA ZAPISU DLA ODBIORCÓW SPOZA MUTEXU (AR-353): Dostawa i jej raport dostają zatrzask gospodarza
        - zapis do plików trwa, dopóki pisze KTÓRAKOLWIEK powierzchnia (`any` źródeł `_zapis_w_biegu`) - a nie wartość
        nadawcy, który właśnie się zgłosił: koniec zapisu z paska osi przy trwającym zapisie Zbiorów zapalałby etapy
        Dostawy obok pisarza. Ten sam zatrzask przykłada budowniczy (`_zbuduj_dostawe`); tu tylko strony zbudowane."""
        zapis = self._zatrzask_zapisu()
        for nazwa in ("pipeline_view", "przyjmij_view"):
            widok = self._gotowy(nazwa)
            if widok is not None:
                widok.set_writeback_busy(zapis)

    def _zatrzask_zapisu(self):
        """Zatrzask zapisu do plików gospodarza (AR-353) - `True`, dopóki pisze KTÓRAKOLWIEK powierzchnia
        (`_zapis_w_biegu`: pasek osi obiektu, szuflada Zbiorów). Jedno źródło dla rozsyłki do zbudowanych stron
        (`_rozeslij_zatrzask_zapisu`), budowniczego Dostawy (`_zbuduj_dostawe`) i reguły odmowy żniw przy
        niezbudowanej Dostawie (`_powod_odmowy_zniw`)."""
        return any(self._zapis_w_biegu.values())

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
                    # Planer (T5): świeże klatki zmieniają POKRYCIE celów (godziny per kanał), więc plan nocy
                    # policzony przed dostawą pokazywałby stare luki. JEDEN WŁAŚCICIEL KOŃCA BIEGU (AR-350): bramę
                    # rachunku otwiera dopiero ta para, kolejnymi instrukcjami - pompa fazy (wejście w `busy.busy`)
                    # idzie przed nią, więc zegar albo koniec wątku sprzed biegu doręczony w pompie trafia na bramę
                    # zamkniętą, a `refresh` liczy raz. Nowy bieg doręczony w pompie zostawia bramę zamkniętą.
                    # PIERWSZA pod fazą: wyjątek odświeżenia dalszego widoku nie zostawia Planera w biegu na zawsze.
                    planner = self._gotowy("planner_view")      # strona leniwa (AR-325) - wyłącznie zbudowana
                    if planner is not None:
                        planner.set_busy(self._dostawa_w_biegu)
                        planner.refresh()
                    self.axis_view.refresh()
                    self.observatory_view.refresh()
                    self.object_view._load_facets()
                    # Kolejka osi obiektu ~0,4 s na kopii pf4 - niewidoczna przeładuje się przy
                    # pokazaniu (AR-84), a człowiek stoi teraz w Dostawie.
                    self.object_view.odswiez_gdy_widoczny()
                    # Strony leniwe (AR-325) - wyłącznie zbudowane: niezbudowana przeczyta stan przy budowie.
                    grid = self._gotowy("grid_view")
                    if grid is not None:
                        grid._load_facets()
                        # Skład zbioru w wątku tła (AR-27: 1,4-1,5 s na żywej bazie stało tu w oknie);
                        # wraca od razu, tabela dostaje zbiór, gdy ten dojedzie. Zaznaczenie przeżywa
                        # przebieg: reset modelu je zabierał, a zbiór jest ten sam. Przeładowanie
                        # NIE-NAWIGACYJNE z generacją (AR-172): zmiana filtra przed końcem składu je
                        # unieważnia - zwykły ogon przechodził na nowsze zlecenie i oddawał stare zaznaczenie.
                        grid.przeladuj_z_zaznaczeniem()
                    # Liczniki zadań + badge ze świeżego stanu (F5) - w wątku tła (AR-84: 1,2-1,9 s
                    # stało tu w oknie na kopii pf4).
                    self.tasks_view.refresh_counts(w_tle=self._pola_poza_watkiem)
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

    def show_frames_in_collections(self, frame_ids, *, label, focus=None):
        """Most „pokaż te klatki w Zbiorach" - publiczne wejście dla każdej powierzchni, która zna
        `frame_id` (dziś: dwuklik w panelu rodowodu, obie osie). Strona zbiorów w BIEŻĄCEJ
        prezentacji, gdy już na niej stoimy (Znajdź zostaje Znajdź), inaczej klasyczna; zbiór
        ustawia publiczny seam gridu (`FramesView.show_frames`), z chipem i drogą powrotu."""
        if self._strona() != STRONA_ZBIORY:
            self.show_classic()
        self.grid_view.show_frames(frame_ids, label=label, focus=focus)

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
        if klucz == home_mod.WIECEJ_ZNIWA:
            self._on_open_harvest()                  # ta sama droga, co przycisk sekcji Stosy Dostawy
        elif klucz == home_mod.WIECEJ_PLANER:
            self._show_view(NAV_PLANER)
        elif klucz == home_mod.WIECEJ_STANOWISKA:
            self._on_open_sites()
        elif klucz == home_mod.WIECEJ_OS_TELESKOPU:
            # Ta sama droga, co wiersz „Teleskopy bez etykiety" Porządków: tabela od nowa i podstrona.
            self._show_view(NAV_PORZADKI)
            self.tasks_view.otworz_os_teleskopu()
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

    def _on_przyjmij(self):
        """Kafel Przyjmij na Domu = JEDNA interakcja do raportu: strona Dostawy i złota akcja na
        zapamiętanym źródle (pierwsza dostawa pyta o katalog - decyzja należy do człowieka).
        Odmowa (bieg w toku, zapis nagłówków, brak bazy) idzie na pasek, a strona z postępem biegu
        stoi wtedy przed oczami - drugi bieg nie rusza (`PipelineView.receive`). Menu „Więcej…”
        i wiersz „?" Porządków prowadzą na tę stronę dalej BEZ startu: to wejście po robotę
        trybu zaawansowanego, nie zamiar dostawy. KOMENDA (`_wejdz`): po porażce budowy strony nic dalej."""
        self._wejdz(NAV_DOSTAWA)
        reason = self.pipeline_view.receive()
        if reason is not None:
            self._flash(reason)
            self.przyjmij_view.pokaz_odmowe(reason)

    def _on_kubelek_porzadkow(self, tag):
        """Wiersz „bez nazwy” raportu dostawy → Porządki z TYM kubełkiem zaznaczonym na podstronie
        obiektów (drążenie pokazuje klatki, gest naprawy się zapala). Sama lista zadań kazałaby
        szukać kubełka drugi raz - przycisk raportu ma kończyć się na celu, nie przed nim. Pusty
        tag = podstrona bez wskazania (nazwy ponad sufit raportu: kolejka stoi przed oczami)."""
        from horreum.gui import tasks as tasks_mod      # lazy jak `TasksView` w `_mount_views`
        self._show_view(NAV_PORZADKI)
        self.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_OBJECTS)
        if tag:
            self.tasks_view._zaznacz_kubelek(tag)
        else:
            self.object_view.refresh()

    def _powod_odmowy_zniw(self):
        """JEDNA reguła odmowy „Wciągnij z WBPP…” gospodarza (AR-354) - powód (zdanie odmowy złotej akcji) albo `None`,
        gdy wolno. Pytają o nią klik (`_on_open_harvest`, bramka przed oknem) i pozycja menu „Więcej…” Domu przy KAŻDYM
        otwarciu menu (`aboutToShow`, `_mount_views`): Dom przykłada wynik i reguły nie liczy. Dawniej Dom trzymał
        własną kopię z zatrzasków biegu i zapisu, a sonda źródła („Wskaż katalog…”, etap bez bazy) nie zgłasza biegu
        gospodarzowi - pozycja stała czynna, a klik odmawiał.

        BEZ BUDOWY DOSTAWY DLA SAMEGO POWODU (AR-335): odczyt property `pipeline_view` budował całą stronę.
        Zbudowana Dostawa mówi własnym stanem (także etap bez bazy - `_thread` jest, a zatrzask biegu gospodarza
        nie); niezbudowana nie ma biegu z definicji, więc ta sama reguła (`dostawa_bramka.powod_odmowy_biegu`)
        dostaje zatrzaski gospodarza - te, które budowniczy przyłożyłby nowej Dostawie (`_zbuduj_dostawe`)."""
        pipeline = self._gotowy("pipeline_view")
        if pipeline is not None:
            return pipeline.powod_odmowy_biegu()
        from horreum.gui import dostawa_bramka     # lazy jak reszta importów drogi żniw
        return dostawa_bramka.powod_odmowy_biegu(baza=self.db_path is not None, bieg=self._dostawa_w_biegu,
                                                 zapis=self._zatrzask_zapisu())

    def _on_open_harvest(self):
        """„Wciągnij z WBPP…” → okno żniw nad połączeniem okna. Dwa wejścia, jedna droga: przycisk
        sekcji Stosy Dostawy (`PipelineView.open_harvest`) i pozycja „Więcej…” Domu (AR-109,
        `_on_wiecej_domu`). Przyjęcie („Zamknij i przyjmij”) przenosi na stronę Dostawy, jak kafel
        Przyjmij: tam biegnie łańcuch, który ono uruchamia, i staje raport „co przyszło” - z Domu
        człowiek patrzyłby na ekran, którego bieg nie dotyczy. Korzeń archiwum najpierw z bazy
        (`harvest.archive_root_from_db` - tam, gdzie leży biblioteka kalibracji), dopiero bez niego
        ostatnie źródło Dostawy: ono bywa podkatalogiem nocy, a wtedy mastery lądowałyby w drugiej,
        równoległej bibliotece. Po oknie: gdy coś wciągnięto - łańcuch Dostawy na wspólnym rodzicu
        kopii (`run_all_on`, bez zapisu źródła); bieg etapów ma jednego właściciela, więc okno go
        nie uruchamia samo. Zdanie wyniku i ewentualna odmowa łańcucha idą JEDNYM komunikatem -
        odmowa na osobnym raporcie zastąpiłaby na pasku wiadomość o położonych masterach. Importy
        leniwe (wzorzec `_mount_views`): okno ładuje się dopiero, gdy ktoś po nie sięgnie.

        Okno dostaje folder roboczy WBPP (stąd bierze wyniki wydań) i korzenie wszystkich kart
        wydań. Gdy wciągnęło stosy, a łańcuch ruszył, rodowód zapisujemy dopiero PO nim
        (`_zapisz_rodowod_po_przebiegu`): wiersz integracji stawia sam łańcuch.

        BRAMKA PRZED OKNEM (`_powod_odmowy_zniw` - ta sama reguła, którą pozycja „Więcej…” Domu czyta przy otwarciu
        menu): w biegu Dostawy albo przy zapisie nagłówków okno otwarte z Domu kończyło się odmową łańcucha PO
        „Zamknij i przyjmij”, a rodowód dokładny wciągniętych stosów zostawał tylko w folderze
        wydania. Odmowa pada na pasek, okno się nie otwiera. Strona Dostawy powstaje dopiero przy „Zamknij
        i przyjmij”.

        BUDOWA DOSTAWY PO OKNIE TO KOMENDA (`_wejdz`, AR-354): mastery już leżą w bibliotece, więc porażka budowy
        mówi na pasku utratę rodowodu dokładnego (instrukcja ratunku, NA POCZĄTKU - jak porażka biegu
        w `_zapisz_rodowod_po_przebiegu`) i wynik okna, a wyjątek idzie do straży - jedna budowa, jedno okno błędu.
        Dawniej przełączenie wiersza połykało porażkę w slocie, a odczyt widoku budował stronę drugi raz i wychodził
        przed zdaniem wyniku."""
        powod = self._powod_odmowy_zniw()
        if powod is not None:
            self._flash(powod)
            return
        from horreum import harvest
        from horreum.gui import projection_dialog
        from horreum.gui.harvest_dialog import HarvestDialog
        archiwum = (harvest.archive_root_from_db(self.con)
                    or QSettings("Horreum", "Horreum").value("pipeline/last_source", "") or "")
        dlg = HarvestDialog(self.con, now_fn=self._now, archive_root=archiwum,
                            work_root=self._work_wbpp(),
                            release_roots=projection_dialog.target_roots(), parent=self)
        dlg.exec()
        zdania = [dlg.summary] if dlg.summary else []
        if dlg.harvested_root:
            try:
                self._wejdz(NAV_DOSTAWA)                 # z Dostawy - bez budowy i bez zmiany (ten sam wiersz)
            except BaseException:
                if dlg.harvested_stacks:                 # zbiór dokładny leży dalej tylko w folderze wydania
                    zdania.insert(0, i18n.t("status.harvest_lineage_lost", n=len(dlg.harvested_stacks)))
                if zdania:
                    self._flash(zlacz_zdania(" - ", zdania))
                raise
            reason = self.pipeline_view.run_all_on(dlg.harvested_root)
            if reason is not None:
                zdania.append(reason)
                if dlg.harvested_stacks:                 # zbiór dokładny leży dalej tylko w folderze wydania
                    zdania.append(i18n.t("status.harvest_lineage_lost", n=len(dlg.harvested_stacks)))
            elif dlg.harvested_stacks:
                self._zapisz_rodowod_po_przebiegu(list(dlg.harvested_stacks), dlg.summary)
        if zdania:
            # Złączenie niesie szczegół błędu biegu z `summary` okna (AR-218) - `" - ".join` go gubił.
            self._flash(zlacz_zdania(" - ", zdania))

    def _zapisz_rodowod_po_przebiegu(self, stosy, podsumowanie=""):
        """Rodowód stosów wciągniętych w oknie żniw: JEDNORAZOWY nasłuch końca przebiegu, który
        właśnie ruszył. Łańcuch Dostawy daje stosowi wejścia z okna czasu (z klatkami odrzuconymi
        przez WBPP); żniwa znają zbiór dokładny, więc zapisują go po łańcuchu (`stacks.
        record_harvest_inputs`). Przed nim wiersza integracji jeszcze nie ma.

        PRZEBIEG ROZPOZNAJEMY PO ZNACZNIKU STARTU (`last_run["since"]`, ustawiany synchronicznie
        w `run_all_on`, więc jest znany w chwili powrotu): okno żniw mogło się otworzyć w fazie
        odświeżania po POPRZEDNIM biegu, zanim ten wyemitował `run_finished` - taki sygnał niesie
        cudzy znacznik i jest ignorowany bez rozłączania, nasłuch czeka na właściwy.

        Nasłuch rozłącza się przy pierwszym WŁAŚCIWYM wywołaniu, niezależnie od wyniku: następne
        przebiegi Dostawy nie mają wpływać na rodowód, a przebieg przerwany, odmówiony albo
        z błędem nie zapisuje niczego (stos zostaje z rodowodem okna, jak bez żniw) - i mówi to na
        pasku: zbiór dokładny leży wtedy tylko w zeznaniu w folderze wydania, a ponowne okno żniw
        odsłoni przyjęcie jeszcze raz (AR-104). Zmiana bazy w trakcie biegu też kasuje zapis - `con`
        jest już inne niż to, na którym żniwa się odbyły; tamto zdanie nie dotyczy bazy na ekranie.

        JEDNO ODŚWIEŻENIE PO ZAPISIE (AR-373): rodowód jest PISARZEM OGONA biegu (`_dopisz_do_ogona`), więc koniec
        przebiegu (`running_changed(False)`) nie odświeża widoków - drugi rachunek Planera czytał `integration_input`
        przed zapisem i szedł do kosza. Odświeża KAŻDE wyjście nasłuchu tego biegu (`_domknij_ogon` → TA SAMA droga co
        po każdym przebiegu, `_odswiez_i_zwolnij_po_biegu`): po zapisie w `finally` - wyjątek zapisu (inny niż
        `ValueError` per stos) leci dalej, ale nie zostawia widoków ze stanem sprzed zapisu, a Planera z zamkniętą
        bramą; przy przebiegu bez sukcesu PRZED zdaniem utraty rodowodu - raporty osi z odświeżenia go nie nadpiszą.
        Inna baza: `_open_path` zmontował widoki od nowa (`_mount_views` → `_clear_views`), więc nasłuch tylko zdejmuje
        swój ogon. Zdanie rodowodu DOKLEJA się do podsumowania okna żniw, nie zastępuje go.

        Po zapisie - obiekt stosu wobec obiektu wydania (AR-103, `_rozjazdy_obiektu_wydania`):
        rozjazd albo brak obiektu staje NA POCZĄTKU raportu z gestem „Przypisz obiekt wydania”
        na pasku; zgodność milczy."""
        widok, con = self._gotowy("pipeline_view"), self.con
        assert widok is not None, "zapis rodowodu po przebiegu bez strony Dostawy"   # przebieg ją zbudował
        start = widok.last_run["since"]
        self._dopisz_do_ogona(start, "rodowod")

        def po_przebiegu(zapis):
            if zapis["since"] != start:
                return
            widok.run_finished.disconnect(po_przebiegu)
            if con is not self.con:
                self._domknij_ogon(start, "rodowod", odswiez=False)
                return
            if zapis["failed"] or zapis["cancelled"] or zapis["refused"]:
                self._domknij_ogon(start, "rodowod")
                # Przebieg bez sukcesu: zdanie utraty rodowodu (instrukcja ratunku) NA POCZĄTKU - pasek
                # ucina koniec. Zastępuje raport Dostawy i podsumowanie żniw, więc niesie oba (AR-218):
                # wiersz awarii z jej szczegółem systemu z zapisu przebiegu (`failed`, `failed_tip` -
                # ten sam co w polu Dostawy, nie z paska, którego treść zależy od kolejności raportów)
                # albo powód odmowy, a za nimi podsumowanie okna żniw z jego szczegółem i członem
                # niezapisanego zeznania.
                przyczyna = (ZdanieZeSzczegolem(zapis["failed"], zapis["failed_tip"] or "")
                             if zapis["failed"] else zapis["refused"] or "")
                self._flash(zlacz_zdania(" - ", (i18n.t("status.harvest_lineage_lost", n=len(stosy)),
                                                 przyczyna, podsumowanie)))
                return
            try:
                zdanie = self._zdanie_rodowodu(con, stosy)
                rozjazdy = self._rozjazdy_obiektu_wydania(con, stosy)
            finally:
                self._domknij_ogon(start, "rodowod")
            if rozjazdy:
                self._pokaz_gest_obiektu_wydania(con, rozjazdy, podsumowanie, zdanie)
            elif zdanie:
                self._flash(zlacz_zdania(" - ", (podsumowanie, zdanie)))

        widok.run_finished.connect(po_przebiegu)

    def _ogon_trwa(self, since):
        """Czy koniec przebiegu `since` ma jeszcze pisarzy ogona (AR-373) - wtedy odświeżenie widoków robi ostatni
        z nich, nie `running_changed(False)`. `since=None` (przebieg bez startu) - nigdy."""
        return since is not None and self._ogon_biegu is not None and self._ogon_biegu[0] == since

    def _dopisz_do_ogona(self, since, pisarz):
        """Pisarz zapisu PO `run_finished` przebiegu `since` (AR-373). Woła go gospodarz synchronicznie po starcie
        przebiegu (`run_all_on`), zanim pętla zdarzeń doręczy jego koniec. Ogon innego przebiegu (porzucony
        przełączeniem bazy) ustępuje nowemu."""
        if not self._ogon_trwa(since):
            self._ogon_biegu = (since, set())
        self._ogon_biegu[1].add(pisarz)

    def _domknij_ogon(self, since, pisarz, *, odswiez=True):
        """Pisarz ogona skończył - KAŻDĄ drogą (AR-373). Ostatni zdejmuje ogon i robi JEDNO odświeżenie końca
        przebiegu (`_odswiez_i_zwolnij_po_biegu`); `odswiez=False` - widoki zmontowane od nowa (inna baza), nie ma
        czego odświeżać ani zwalniać.

        PRZED odświeżeniem raport Przyjmij bierze odcisk stanu od nowa (`PrzyjmijView.odcisk_po_ogonie`, AR-354): jego
        odcisk z `run_finished` powstał przed zapisem pisarzy ogona, więc następne przeliczenie raportu podpisywało log
        „stan sprzed Twoich zmian” po zapisie gospodarza. Odcisk = stan po OSTATNIM zapisie końca biegu. Odcisk czyta
        bazę, więc stoi w `try`: jego błąd idzie dalej do straży (EXPECT), a odświeżenie i zwolnienie osi pada
        w `finally` - ogon jest już zdjęty, więc nikt inny osi po tym przebiegu nie zwolni."""
        if not self._ogon_trwa(since):
            return
        self._ogon_biegu[1].discard(pisarz)
        if self._ogon_biegu[1]:
            return
        self._ogon_biegu = None
        if odswiez:
            przyjmij = self._gotowy("przyjmij_view")
            try:
                if przyjmij is not None:
                    przyjmij.odcisk_po_ogonie()
            finally:
                self._odswiez_i_zwolnij_po_biegu()

    def _odswiez_i_zwolnij_po_biegu(self):
        """KONIEC PRZEBIEGU = JEDNO odświeżenie wszystkich widoków i plakietki, potem panel rodowodu, a oś obiektu
        zwalnia się OSTATNIA (AR-296). Woła je `_on_pipeline_running(False)`, a przy ogonie biegu (AR-373) - ostatni
        pisarz ogona (`_domknij_ogon`).

        PANEL RODOWODU CZYTA STAN, KTÓRY ETAP WŁAŚNIE PRZEPISAŁ (bramka pakietu, zarzut 7). Bez tego takt 3 kończył
        się gorzej, niż zaczynał: gest uruchamiał przeliczenie, panel zostawał z zapisem sprzed niego i etykietą
        „nieaktualny”, a user nie miał jak jej zdjąć inaczej niż przeklikaniem zaznaczenia. Odświeżamy po KAŻDYM
        etapie, nie tylko po rodowodzie - `resolve` i `group` też ruszają fakty, na których stoi powód.

        Oś obiektu zwalnia się OSTATNIA (AR-296): koniec blokady podaje receptę cofnięcia zapisu kart odłożoną przez
        odmowę w biegu, a raporty osi z odświeżenia („Brak teleskopów na osi…”) padają wcześniej - zwolnienie przed
        odświeżeniem dawało zdanie „recepta wróciła” i receptę zgaszoną w tym samym obrocie. W `finally`: wyjątek
        odświeżenia nie zostawia osi zablokowanej. Koniec przebiegu doręczony W ŚRODKU odświeżenia (nowy krótki
        przebieg pod `processEvents` fazy) tylko zamawia kolejny obrót - oś zwalnia wywołanie zewnętrzne, po ostatnim
        obrocie. Bieg, który w pompie fazy RUSZYŁ i jeszcze trwa (`_dostawa_w_biegu`), trzyma oś zajętą - zwolni ją
        koniec TEGO biegu; dawniej oś wracała czynna przy pracującym pisarzu Dostawy."""
        try:
            self._odswiez_widoki_po_przebiegu()
            grid = self._gotowy("grid_view")     # niezbudowane Zbiory przeczytają panel przy budowie (AR-325)
            if grid is not None:
                grid.refresh_lineage_panel()
        finally:
            if not self._odswiezam_widoki and not self._dostawa_w_biegu:
                self.object_view.set_busy(False)

    def _zdanie_rodowodu(self, con, stosy):
        """Zapisuje rodowód stosów (`stacks.record_harvest_inputs`, per stos) i zwraca zdanie dla
        paska. Stos, któremu zapis odmówił (`ValueError`: wejście spoza lightów albo pusty zbiór;
        `no_integration`: łańcuch nie postawił mu integracji), liczony jest OSOBNYM członem -
        zdanie, które mówi tylko o udanych, ukryłoby stratę. Trzy człony, bo trzy różne stany:
        rodowód z historii; stos z rodowodem okna czasu (zapis odmówił, rodowód z łańcucha
        zostaje); stos BEZ rodowodu (łańcuch nie ujął go jako stosu, nie ma czego zapisać)."""
        z_historii = z_okna = bez_rodowodu = 0
        for sha1_data, wejscia, _kanon in stosy:
            try:
                wynik = stacks.record_harvest_inputs(
                    con, master_sha1_data=sha1_data, input_frame_ids=wejscia, now=self._now())
            except ValueError:
                z_okna += 1
                continue
            if wynik["reason"] is None:
                z_historii += 1
            else:
                bez_rodowodu += 1
        czlony = []
        if z_historii:
            czlony.append(i18n.t_plural("status.harvest_lineage", z_historii))
        if z_okna:
            czlony.append(i18n.t_plural("status.harvest_lineage_window", z_okna))
        if bez_rodowodu:
            czlony.append(i18n.t_plural("status.harvest_lineage_none", bez_rodowodu))
        return "; ".join(czlony)

    # ---- obiekt stosu wobec obiektu wydania (AR-103): zdanie + gest na pasku, cofnięcie ----

    def _rozjazdy_obiektu_wydania(self, con, stosy):
        """Stosy z żniw, których obiekt NIE zgadza się z obiektem wydania (`stacks.release_object_check`:
        `inny` albo `brak`) albo NIE DAJE SIĘ porównać, bo kanonu wydania ta baza nie zna
        (`wydanie_poza_baza` - zdanie bez gestu), w kolejności okna. Stos zgodny, bez kanonu wydania
        albo nieznany bazie nie daje zdania. Odczyt po łańcuchu: obiekt stosu daje mu dopiero
        Dostawa (nagłówek → resolver)."""
        rozjazdy = []
        for sha1_data, _wejscia, kanon in stosy:
            r = stacks.release_object_check(con, master_sha1_data=sha1_data, object_canon=kanon)
            if r is not None and r["verdict"] in ("inny", "brak", "wydanie_poza_baza"):
                rozjazdy.append(r)
        return rozjazdy

    @staticmethod
    def _zdanie_obiektu_wydania(rozjazdy):
        """Co się nie zgadza, po ludzku: osobny człon dla stosów z innym obiektem (para „stos: X,
        wydanie: Y” na każdą parę, bez powtórzeń) i dla stosów bez obiektu (kanony wydania). Kanony
        z bazy, nie z nagłówka - te same nazwy, które pokazują Zbiory."""
        inne = [r for r in rozjazdy if r["verdict"] == "inny"]
        puste = [r for r in rozjazdy if r["verdict"] == "brak"]
        czlony = []
        if inne:
            pary = list(dict.fromkeys(
                i18n.t("app.release_object.pair", stack=r["stack_canon"], release=r["release_canon"])
                for r in inne))
            czlony.append(i18n.t_plural("app.release_object.other", len(inne), pary="; ".join(pary)))
        if puste:
            kanony = ", ".join(dict.fromkeys(r["release_canon"] for r in puste))
            czlony.append(i18n.t_plural("app.release_object.none", len(puste), release=kanony))
        obce = [r for r in rozjazdy if r["verdict"] == "wydanie_poza_baza"]
        if obce:
            kanony = ", ".join(dict.fromkeys(r["release_canon"] for r in obce))
            czlony.append(i18n.t_plural("app.release_object.unknown", len(obce), release=kanony))
        return "; ".join(czlony)

    def _gest_wydania_aktywny(self):
        """Czy przycisk recepty niesie TERAZ gest obiektu wydania („Przypisz obiekt wydania” albo
        „Cofnij”) - właściciela recepty rozpoznajemy po wykonawcy jej pierwszego członu, bez
        osobnego stanu, który mógłby rozjechać się z paskiem."""
        czlony = self._czlony_recepty
        return bool(czlony) and czlony[0].wykonaj in (self._on_przypisz_obiekt_wydania,
                                                       self._on_cofnij_obiekt_wydania)

    def _pokaz_gest_obiektu_wydania(self, con, rozjazdy, podsumowanie="", zdanie_rodowodu=""):
        """Zdanie rozjazdu NA POCZĄTKU raportu (pasek ucina koniec, a to jest jedyny człon, który
        prosi o decyzję) i gest „Przypisz obiekt wydania” na przycisku recepty, przyklejonym do
        raportu. Raport bez wygasania i związany z bieżącym miejscem nawigacji: zdanie i gest żyją
        razem - gasi je cudzy raport gestu (`_flash` zdejmuje receptę) albo wyjście z tego miejsca;
        raport wczytania i recepta gridu go nie zdejmują (`_gest_wydania_aktywny`). Stosy, których
        nie da się porównać (`wydanie_poza_baza`), dostają samo zdanie - gest bez celu nie staje.
        Nigdy cicha podmiana: zapis robi wyłącznie klik."""
        from horreum.gui.grid_model import CzlonRecepty, Recepta
        tekst = zlacz_zdania(" - ", (self._zdanie_obiektu_wydania(rozjazdy), podsumowanie,
                                     zdanie_rodowodu))   # szczegół `podsumowanie` jedzie dalej (AR-218)
        cele = [r for r in rozjazdy if r["verdict"] in ("inny", "brak")]
        self._obiekty_wydania = (con, cele) if cele else None
        self._flash(tekst, ms=0 if cele else 5000, miejsce=self._strona())
        if cele:
            self._pokaz_recepte(Recepta([CzlonRecepty(i18n.t("app.release_object.assign"),
                                                      self._on_przypisz_obiekt_wydania)]))

    def _on_przypisz_obiekt_wydania(self):
        """Klik „Przypisz obiekt wydania”: per stos klinga jawnego nadpisania ręką
        (`repo.user_override_object`) ze stanem, który zdanie pokazało, jako oczekiwanym -
        stos zmieniony od żniw jest pomijany i nazwany (dryf), drugi klik niczego nie dopisuje.
        Po zapisie zdanie wyniku i recepta „Cofnij” (stan sprzed z klingi, nie z ekranu). Inna
        baza niż ta, na której żniwa się odbyły - gest milczy (stosy jej nie dotyczą)."""
        from horreum.gui.grid_model import CzlonRecepty, Recepta
        con, rozjazdy = self._obiekty_wydania or (None, [])
        self._obiekty_wydania = None
        if con is None or con is not self.con or not rozjazdy:
            return
        zmiany, kanony, juz, dryf = [], [], 0, 0
        for r in rozjazdy:
            wynik = repo.user_override_object(
                con, frame_id=r["frame_id"], canon=r["release_canon"],
                expected=(r["stack_object_id"], r["stack_source"], r["stack_cleared_id"]),
                reason="release_object", now=self._now(), changes_out=zmiany)
            if wynik == "assigned":
                kanony.append(r["release_canon"])
            elif wynik == "unchanged":
                juz += 1
            else:
                dryf += 1
        self._odswiez_po_obiekcie_wydania()
        czlony = []
        if zmiany:
            czlony.append(i18n.t_plural("app.release_object.assigned", len(zmiany),
                                        canons=", ".join(dict.fromkeys(kanony))))
        if juz:
            czlony.append(i18n.t_plural("app.release_object.already", juz))
        if dryf:
            czlony.append(i18n.t_plural("app.release_object.drift", dryf))
        self._zmiany_obiektu_wydania = (con, zmiany) if zmiany else None
        self._flash("; ".join(czlony), ms=0, miejsce=self._strona())
        if zmiany:
            self._pokaz_recepte(Recepta([CzlonRecepty(i18n.t("app.release_object.undo"),
                                                      self._on_cofnij_obiekt_wydania)]))

    def _on_cofnij_obiekt_wydania(self):
        """Klik „Cofnij” po geście: każdy stos wraca do stanu sprzed (`repo.restore_object_override`,
        CAS - stos zmieniony po geście zostaje i jest nazwany). Zdanie mówi, DO CZEGO stos wrócił
        (`change.before`): do poprzedniego obiektu, do braku obiektu albo do nagrobka ręki - „wrócił
        do poprzedniego obiektu” przy stosie, który obiektu nie miał, byłoby nieprawdą. Recepta
        gaśnie razem ze zdaniem wyniku: cofnięcia nie cofamy."""
        con, zmiany = self._zmiany_obiektu_wydania or (None, [])
        self._zmiany_obiektu_wydania = None
        if con is None or con is not self.con or not zmiany:
            return
        obiekt = pustka = nagrobek = dryf = 0
        for z in zmiany:
            if not repo.restore_object_override(con, change=z, now=self._now()):
                dryf += 1
            elif z.before[0] is not None:
                obiekt += 1
            elif z.before[1] == "user_cleared":
                nagrobek += 1
            else:
                pustka += 1
        self._odswiez_po_obiekcie_wydania()
        cofniete = []
        if obiekt:
            cofniete.append(i18n.t_plural("app.release_object.restored", obiekt))
        if pustka:
            cofniete.append(i18n.t_plural("app.release_object.restored_none", pustka))
        if nagrobek:
            cofniete.append(i18n.t_plural("app.release_object.restored_cleared", nagrobek))
        czlony = [i18n.t("app.release_object.undone", czlony=", ".join(cofniete))] if cofniete else []
        if dryf:
            czlony.append(i18n.t_plural("app.release_object.undo_drift", dryf))
        self._flash("; ".join(czlony), miejsce=self._strona())

    def _odswiez_po_obiekcie_wydania(self):
        """Gest zmienił oś obiektu stosów - te same powierzchnie, co po geście „Przypisz obiekt…”
        z raportu Dostawy (kolejka osi, plakietka Porządków, teczki Domu, grid) i panel rodowodu."""
        self.object_view.odswiez_gdy_widoczny()          # niewidoczna oś - przy pokazaniu (AR-84)
        self.tasks_view.refresh_counts(w_tle=self._pola_poza_watkiem)   # liczniki w tle (AR-84)
        if self.home_view is not None:
            self.home_view.odswiez_teczki()
        grid = self._gotowy("grid_view")                  # niezbudowane Zbiory - stan przy budowie (AR-325)
        if grid is not None:
            grid.przeladuj_z_zaznaczeniem()               # gest nie nawiguje w Zbiorach (AR-172)
            grid.refresh_lineage_panel()

    def _on_tasks_counts(self, n, powod=""):
        """Badge sidebara: „Porządki (N)" przy N>0; przy zerze GOŁE „Porządki" - „(0)" to szum (F5R#8).
        Ta sama liczba idzie na kafel „Popraw" Domu - jeden sygnał, dwa nośniki (SPOT). `"!"` (AR-326) - pierwszy
        rachunek padł: „Porządki (!)” z podpowiedzią `powod` (zdanie błędu z Porządków); gołe „Porządki”
        czytałoby się jak zero. Udany rachunek zdejmuje podpowiedź."""
        self._plakietka_padla = n == "!"
        item = self.nav.item(NAV_PORZADKI)
        if item is not None:
            item.setText(i18n.t("nav.porzadki") if n == 0 else i18n.t("nav.porzadki_count", n=n))
            item.setToolTip(powod if n == "!" else "")
        if self.home_view is not None:
            self.home_view.ustaw_popraw(n, powod)

    def _on_rachunek_padl(self, montaz, zdanie):
        """Pierwszy rachunek liczników Porządków padł (`TasksView.rachunek_padl`, AR-326) - plakietka i kafel
        mówią „!” ze zdaniem błędu w podpowiedzi. Sygnał widoku sprzed przełączenia bazy (cudzy token) - nic."""
        if montaz != self._montaz:
            return
        self._on_tasks_counts("!", zdanie)

    def _resolve_after_repair(self):
        """Takt 3 P-D wołany z okna „Napraw nagłówek…": ISTNIEJĄCY etap Dostawy. Zwraca POWÓD
        odmowy (okno je pokaże i zostanie otwarte) albo None — wtedy przełączamy widok na Dostawę,
        żeby postęp etapu był widoczny tam, gdzie zawsze. Przełączenie nie jest interakcją
        użytkownika, więc nie liczy się do budżetu kliknięć."""
        reason = self.pipeline_view.run_stage("resolve")
        if reason is None:
            self._show_view(NAV_DOSTAWA)
        return reason

    def _etap_po_gescie_rodowodu(self, stage):
        """Takt 3 dla gestów panelu Rodowód - lustro `_resolve_after_repair`, z etapem jako
        parametrem: `stack_lineage` po odniesieniu czasu stosu (R2), `lineage` po gestach osi
        kalibracji („Policz teraz”, „Przywróć automat”).

        Gest zmienia fakt, na którym stoi dobór, więc dopóki rodowód się nie przeliczy, ekran
        pokazuje stan sprzed gestu. Zdzin nazwał koszt wprost: „muszę teraz zmienić zakładkę na
        Dostawę i klikać button, który jest przy buttonie wyboru folderu — UX-owo to jest
        niezrozumiałe". I jest: akcja domykająca gest mieszkała na innym ekranie, w sekcji
        o wciąganiu plików z dysku.

        PRZEŁĄCZENIE WIDOKU ZALEŻY OD ETAPU. Rodowód stosów jest długi (czyta historię plików
        z archiwum), więc jego postęp ma być widoczny tam, gdzie zawsze - przełącza PROGRAM po
        jednym kliknięciu, a nie człowiek po trzech. Rodowód kalibracji trwa ułamek sekundy (0,38 s
        na kopii żywego archiwum, 14 338 lightów), a powrót z Dostawy czyścił zaznaczenie - to był
        cały koszt „Policz teraz” (4 interakcje zamiast 1, wizytacja 0802), więc ten etap biegnie
        bez zmiany ekranu, a panel odświeża się sam po końcu przebiegu."""
        reason = self.pipeline_view.run_stage(stage)
        if reason is None and stage == "stack_lineage":
            self._show_view(NAV_DOSTAWA)
        return reason

    def _on_writeback_busy(self, busy):
        """Mutex DWÓCH powierzchni writebacku (D-PD-3). Grid pisze do plików → „Napraw nagłówek…"
        gaśnie; okno naprawy pisze → gaśnie Zatwierdź/Odrzuć/Cofnij gridu. Bez tego oba commity
        spotkałyby się na `BEGIN IMMEDIATE` (`busy_timeout` 5 s) i jeden wróciłby jako 'failed'.
        Trzecia strona mutexu: Dostawa gaśnie przy zapisie Z KAŻDEJ z dwóch powierzchni - razem
        z gestem raportu „co przyszło” (zapis osi obiektu w trakcie zapisu kart do plików).

        Zatrzask stanu PRZED rozesłaniem (AR-325): Dostawa zbudowana w trakcie zapisu Zbiorów dostaje go od
        budowniczego; tu tylko strony zbudowane (`_gotowy`). Oś obiektu dostaje stan TEGO źródła (druga strona
        mutexu), Dostawa i jej raport - zatrzask gospodarza (`_rozeslij_zatrzask_zapisu`, AR-353); „Wciągnij z WBPP…”
        Domu czyta regułę gospodarza przy otwarciu menu (`_powod_odmowy_zniw`, AR-354)."""
        self._zapis_w_biegu["grid"] = bool(busy)
        self.object_view.set_writeback_busy(busy)
        self._rozeslij_zatrzask_zapisu()

    def _on_pipeline_running(self, running):
        """W trakcie etapu wyłącz akcje zapisu osi (szczery disabled). Nawigacja zostaje aktywna —
        user może zerknąć na oś; blokujemy tylko ZAPIS (§6: aktywny tylko „Anuluj" skanu).

        Zatrzask biegu PRZED rozesłaniem (AR-325): Zbiory i Planer zbudowane w trakcie biegu dostają go od
        budowniczego; tu tylko strony zbudowane (`_gotowy`). Dostawa biegnie, więc jej strona jest.

        Planer zamyka bramę tutaj, a otwiera ją WYŁĄCZNIE faza odświeżenia razem z rachunkiem (AR-350,
        `_odswiez_widoki_po_przebiegu`) - otwarcie tutaj zostawiało pompę fazy między bramą a `refresh`.

        OGON BIEGU (AR-373): gdy koniec tego przebiegu zapisują jeszcze pisarze po `run_finished` (rodowód żniw,
        `_zapisz_rodowod_po_przebiegu`), odświeżenie i zwolnienie osi robi ostatni z nich - tu tylko zatrzaski. Dawniej
        żniwa ze stosami odświeżały widoki dwa razy, a pierwszy rachunek Planera czytał bazę sprzed zapisu rodowodu.
        Przebieg rozpoznaje zapis WIDOKU Dostawy (`last_run["since"]` - migawka przed `running_changed(False)`),
        czytany wyłącznie ze strony zbudowanej (`_gotowy`, AR-325): bez niej droga jak bez ogona."""
        self._dostawa_w_biegu = bool(running)
        self.axis_view.set_busy(running)
        self.observatory_view.set_busy(running)
        if running:
            self.object_view.set_busy(True)     # „Przypisz obiekt…" (#8/P4) - zapis, gatowany jak inne
        grid, planner = self._gotowy("grid_view"), self._gotowy("planner_view")
        if grid is not None:
            grid.set_busy(running)     # grid ma akcje ZAPISU (staging/commit/undo) - gatuj (wizytator C1)
        if planner is not None and running:
            planner.set_busy(True)     # planer czyta CAŁE archiwum - nie liczmy nocy na wpół zapisanej bazie
        self.home_view.set_busy(running)     # „Wydaj do WBPP" Domu gaśnie jak „Wydaj obiekt…" gridu
        przyjmij = self._gotowy("przyjmij_view")
        if przyjmij is not None:
            przyjmij.set_busy(running)  # „Przypisz obiekt…” raportu dostawy - zapis osi
        if not running:
            # KONIEC PRZEBIEGU = JEDNO odświeżenie wszystkich widoków i plakietki (`_odswiez_i_zwolnij_po_biegu`). Bez
            # warunku „czy etap coś zapisał": przebieg przerwany albo zakończony błędem też mógł zapisać (etapy
            # łańcucha przed błędem, częściowy skan), a `running_changed(False)` przychodzi w każdej z tych dróg -
            # `_cleanup_thread` woła je po KAŻDYM końcu wątku. Przy ogonie biegu (AR-373) odświeża ostatni pisarz.
            dostawa = self._gotowy("pipeline_view")
            if dostawa is None or not self._ogon_trwa(dostawa.last_run["since"]):
                self._odswiez_i_zwolnij_po_biegu()

    # ---------------------------------------------------------------- menu Plik: Otwórz/Nowa baza

    def _katalog_okna_bazy(self):
        """Katalog startowy „Otwórz bazę…” i „Nowa baza…” (AR-378): katalog bieżącej bazy, katalog ostatniej bazy
        (`_KLUCZ_OSTATNIEJ_BAZY` - okno bez bazy po nieudanym otwarciu), Dokumenty, w końcu folder domowy - reguła
        `okna_wyboru.katalog_startowy`. Dawniej pusty start: pierwsze okno procesu otwierało katalog uruchomienia
        programu (onefile: obok pliku exe), każde następne - folder ostatniego dowolnego okna wyboru, np. drzewo
        archiwum po wskazaniu źródła Dostawy (Qt `lastVisitedDir`, zmierzone natywnie). Start to KATALOG - „Nowa
        baza…” nie podpowiada nazwy pliku."""
        from horreum.gui import okna_wyboru
        ostatnia = QSettings("Horreum", "Horreum").value(_KLUCZ_OSTATNIEJ_BAZY, None)
        return okna_wyboru.katalog_startowy(
            os.path.dirname(self.db_path) if self.db_path else None,
            os.path.dirname(ostatnia) if ostatnia else None,
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))

    def _on_open_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.open_db_title"), self._katalog_okna_bazy(), i18n.t("dialog.open_db_filter"))
        if path:
            self._open_path(path)

    def _on_new_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.new_db_title"), self._katalog_okna_bazy(), i18n.t("dialog.new_db_filter"))
        if path:
            self._open_path(path)

    def _work_wbpp(self):
        """Korzeń `_WBPP` folderu roboczego z ustawienia `work/root` albo `None`, gdy nikt go nie
        wskazał. Ustawienie trzyma katalog wybrany przez człowieka (`_on_work_root`); `_WBPP` składa
        z niego czysta `projection.work_wbpp_root` za każdym razem, więc jest jedno źródło tej
        ścieżki. Zero dysku."""
        root = QSettings("Horreum", "Horreum").value("work/root", "")
        return projection.work_wbpp_root(root) if root else None

    def _on_work_root(self):
        """Plik → „Folder roboczy WBPP…": wskazanie katalogu, z którego okno żniw bierze wyniki
        wydań. Zapisuje wybór (`work/root` - ten slot jest jedynym właścicielem ustawienia),
        dopisuje kartę celu wydania i podaje folder widokowi Dostawy.

        ZERO DYSKU W SLOCIE (jak „Przyjmij nowe" i „Wciągnij stosy…"): nic nie zakłada ani nie
        sprawdza. `_WBPP`,
        `OBJECTS\\<obiekt>` i `out` powstają przy pierwszym wydaniu obiektu, w klindze `apply`
        na wątku tła - katalog wskazany na odłączonym udziale nie zawiesi okna. Start okna (AR-378): zapamiętany
        folder, gdy jest albo jest jego rodzic, inaczej folder domowy - sprawdza wątek sondy z budżetem
        (`okna_wyboru.katalog_startowy`), nie ten slot."""
        from horreum.gui import okna_wyboru, projection_dialog
        ustawienia = QSettings("Horreum", "Horreum")
        start = str(ustawienia.value("work/root", "") or "")
        root = QFileDialog.getExistingDirectory(self, i18n.t("proj.work_card"), okna_wyboru.katalog_startowy(start))
        if not root:
            return
        ustawienia.setValue("work/root", root)
        wbpp = projection.work_wbpp_root(root)
        projection_dialog.remember_target(i18n.t("proj.work_card"), wbpp)
        pipeline = self._gotowy("pipeline_view")       # niezbudowana Dostawa weźmie folder przy budowie (AR-325)
        if pipeline is not None:
            pipeline.set_work_root(wbpp)
        self._flash(i18n.t("status.work_root_set", path=wbpp))

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
        w ogóle wstało".

        ODMOWA BAZY Z NOWSZEGO HORREUM (AR-69): `open_db` rzuca `db.SchemaTooNew`, zanim
        cokolwiek w bazie zmieni. Okno zostaje przy dotychczasowej bazie (przy starcie - bez
        bazy) i mówi to oknem komunikatu. Bez tego start z zapamiętaną nowszą bazą kończył się
        śladem stosu przed `app.exec()` przy KAŻDYM uruchomieniu. Ścieżka zostaje zapamiętana:
        po aktualizacji programu ta sama baza otworzy się sama.

        KAŻDY INNY BŁĄD OTWARCIA (AR-124) - plik, który nie jest bazą, obcięta kopia, baza sprzed
        przejścia fitsmirror, katalog zamiast pliku - kończy się tym samym: jedno okno „nie udało
        się otworzyć” z powodem, okno nie przełącza się na ten plik. Obwódka obejmuje WYŁĄCZNIE
        `open_db` (plik z zewnątrz, niczego jeszcze nie przejęliśmy); błąd montażu widoków to błąd
        programu i wybucha dalej. Okno komunikatu pada PO `busy`, bez kursora oczekiwania.
        Z `except` wychodzi samo zdanie: wyjątek w zmiennej lokalnej tworzy cykl z ramką i żyje do
        przebiegu GC razem z tym, co jego ramki trzymają.

        ZAPIS DO PLIKÓW W TOKU ODMAWIA PRZEŁĄCZENIA (AR-296): demontaż widoków skasowałby `QThread`
        uchwytu w biegu (twardy abort), a ogon zapisu trafiłby w zamknięte połączenie - ta sama straż
        co zamknięcie okna (`_odmowa_w_biegu_zapisu`), ale BEZ anulowania: samo zdanie na pasku, zapis
        biegnie dalej (zamiar „przerwij” wyraża tylko zamknięcie okna)."""
        if self._odmowa_w_biegu_zapisu(lambda _tekst: self._flash(i18n.t("wb.undo_switch_refused")),
                                       przerwij=False):
            return
        # Dobudowa Zbiorów (AR-325) czeka na koniec otwarcia: fazy otwarcia kręcą pętlę (`busy.repaint`), a zegar
        # zbudowałby w nich stronę bazy, która właśnie znika. Odmowa bazy - zegar wraca dla bazy, która zostaje.
        self._wstrzymaj_dobudowe()
        name = Path(path).name
        with busy.busy(self._say_phase, i18n.t("busy.open_db", name=name)) as faza:
            try:
                new_con = db.open_db(path)
            except db.SchemaTooNew as exc:           # nic nie przejęte - okno zostaje, jak było
                odmowa = i18n.t("main.db_too_new", name=name, found=exc.found,
                                supported=db.SCHEMA_VERSION)
            except Exception as exc:
                odmowa = i18n.t("main.db_open_failed", name=name,
                                reason=str(exc) or type(exc).__name__)
            else:
                odmowa = None
                old = self.con
                self.con = new_con
                self.db_path = path
                faza.say(i18n.t("busy.mount_views"))
                self._mount_views()
                self._sync_db_state()
                if old is not None:
                    old.close()
        if odmowa is not None:
            self._end_phase()
            self._zamow_dobudowe()
            QMessageBox.warning(self, i18n.t("dialog.open_db_title"), odmowa)
            return
        self._end_phase()
        if self._on_db_changed is not None:        # zapamiętaj ostatnią bazę (trwałe ustawienia)
            self._on_db_changed(path)
        self._flash(i18n.t("main.db_loaded", path=path), gest=False)   # stan okna, nie gest (AR-97)
        # Powrót do bazy z odłożoną receptą osi (AR-321): kolejka tej bazy przeżyła przełączenie - mówi od razu
        # wpisem, którego nic jeszcze nie podało (podany raz nie zastępuje drugi raz „Baza: … wczytana”).
        self.object_view.podaj_odlozone(tylko_niepodane=True)
        self._zamow_dobudowe()

    def _say_phase(self, text):
        """Ujście fazy dla operacji CAŁEGO OKNA (F-1) — własna etykieta paska statusu, a przy
        BRAKU zamontowanych widoków także środek okna.

        Dwa miejsca, bo faza ma dwa różne konteksty. Przy starcie `empty_note` jest JEDYNYM
        widocznym elementem: bez niego okno przez sekundy pokazywałoby „Brak bazy" — zdanie
        fałszywe, bo baza właśnie się wczytuje. Przy operacji na zamontowanych widokach środek
        jest zasłonięty stackiem, więc zostaje sama etykieta w pasku.

        Etykieta, nie `showMessage` — patrz komentarz przy `phase_label`: raport i faza nie mogą
        dzielić jednego miejsca, bo wtedy jedno kasuje drugie."""
        self._faza_pierwsza = text
        self._pokaz_faze()
        if not self.stack.isVisible():
            self.empty_note.setText(text)
            self.empty_note.setVisible(True)

    def _end_phase(self):
        """Koniec fazy okna: etykieta gaśnie, a środek wraca do zdania o STANIE (nie o robocie).
        Bez tego pasek zostawałby z opisem operacji, która już się skończyła - czyli kłamał.
        Faza TŁA, która wciąż trwa (AR-175), wraca wtedy na etykietę - robota jeszcze jest."""
        self._faza_pierwsza = ""
        self._pokaz_faze()
        self._sync_db_state()

    def _pokaz_faze(self):
        """JEDYNY pisarz etykiety fazy (AR-175): faza pierwszego planu, a bez niej faza tła; obie puste
        - etykieta gaśnie. Zmiana szerokości etykiety przelicza pasek (FH-2)."""
        self.phase_label.setText(self._faza_pierwsza or self._faza_tla)
        self._przelicz_pasek()

    def _on_liczenie_w_toku(self, montaz, seria, w_toku):
        """Seria biegów liczników Porządków w tle (`TasksView.liczenie_w_toku`, AR-175). Faza tła
        należy do PIERWSZEJ serii po montażu: późniejsze serie (gest Zbiorów, koniec Dostawy, wejście
        i powrót do Porządków przy zmienionej bazie - AR-337, rachunek wejścia w tle) mają plakietkę ze
        stanem poprzednim i własny znak (ogon gestu; faza przy tytule listy Porządków), a „Liczę…” na
        pasku po każdym z nich byłoby szumem. Montaż policzony synchronicznie zostawia `_seria_montazu = 0`
        (`_mount_views`) - żadna późniejsza seria nie zostaje wtedy przyjęta za serię montażu.
        Sygnał z cudzym tokenem montażu (widok w demontażu, AR-326 - dawniej `sender()`) i koniec cudzej
        serii są odrzucane - spóźnione `False` starej bazy nie gasi fazy nowej.

        Koniec serii bez żadnego przyłożonego rachunku zdejmuje też stan „liczę” z plakietki i kafla:
        porażkę mówi `rachunek_padl` („!”, `_on_rachunek_padl`); seria, która skończyła się bez wyniku i bez
        tego sygnału, też dostaje „!” - „(…)” obiecywałoby liczbę, która nie przyjdzie, a gołe „Porządki”
        mówiłoby zero."""
        tasks_view = getattr(self, "tasks_view", None)
        if tasks_view is None or montaz != self._montaz:
            return
        if w_toku:
            if self._seria_montazu is None:
                self._seria_montazu = seria
                self._faza_tla = i18n.t("busy.counting_tasks")
                self._pokaz_faze()
            return
        if seria != self._seria_montazu or not self._faza_tla:
            return
        self._faza_tla = ""
        self._pokaz_faze()
        if not tasks_view.ma_rachunek() and not self._plakietka_padla:
            self._on_tasks_counts("!", tasks_view.blad_licznikow.text())
        self._po_licznikach_montazu()        # kotwica dobudowy Zbiorów (AR-325)

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
            self._flash(i18n.t("main.no_db"), ms=0, gest=False)

    def _flash_grid(self, msg):
        """Wynik gestu gridu: związany ze Zbiorami, więc gaśnie przy zmianie miejsca nawigacji
        (AR-34). Wynik wyemitowany, gdy user jest gdzie indziej (gest panelu rodowodu przełącza
        widok na Dostawę), nie dostaje powiązania (jawne `None`) - nie ma z czym gasnąć, a zdanie ma
        paść; ze szczegółem (awaria zapisu) żyje wtedy do następnego raportu (AR-236, `_flash`)."""
        self._flash(msg, miejsce=STRONA_ZBIORY if self._strona() == STRONA_ZBIORY else None)

    def _flash_dostawy(self, msg):
        """Raport Dostawy (przerwanie i awaria etapu, odmowa, źródło nieosiągalne) - związany
        z Dostawą, gdy pada przy niej, jak wynik gestu gridu (`_flash_grid`, AR-34): po wyjściu
        z Dostawy zdanie i jego szczegół (AR-218) schodzą z paska, a awaria zostaje w polu błędu
        Dostawy i na stronie Przyjmij. Wizytacja natywna zastała „Etap „Rozwiązywanie” nie powiódł
        się.” nad Domem. Raport biegu w tle, gdy Dostawy nie widać, powiązania nie dostaje (jawne
        `None`) - nie ma z czym gasnąć; ze szczegółem żyje wtedy do następnego raportu (AR-236,
        `_flash`). Zdanie zwykłego końca etapu ma własny kanał (`_raport_etapu`)."""
        self._flash(msg, miejsce=STRONA_DOSTAWA if self._strona() == STRONA_DOSTAWA else None)

    def _raport_wczytania_gridu(self, msg):
        """Raport WCZYTANIA zbioru („Wczytuję klatki…", „Grid: N klatek…") - na pasek tylko wtedy,
        gdy Zbiory są widoczne; inaczej czeka na wejście w Zbiory (`_on_nav_changed`).

        Ten raport pada też poza Zbiorami: odświeżenie widoków po przebiegu Dostawy, start okna.
        Na pasku bez powiązania z miejscem przykrywał wtedy status etapu, po który user patrzy
        w Dostawie, mówiąc o ekranie, którego nie widać. Odłożony, a nie zgubiony: przy wejściu
        w Zbiory zdanie „Grid: N klatek…" jest prawdziwe i opisuje to, co właśnie pokazujemy.
        Nowszy raport zastępuje odłożony - liczy się ostatnie wczytanie.

        Aktywny gest obiektu wydania (AR-103, `_gest_wydania_aktywny`) też odkłada ten raport:
        wczytanie po przebiegu Dostawy przychodzi z wątku tła PO zdaniu rozjazdu, a `_flash`
        zdjąłby jego przycisk („Przypisz obiekt wydania” / „Cofnij”) - raport wczytania to nie gest
        człowieka, który ma prawo go zastąpić."""
        if self._gest_wydania_aktywny():
            self._odlozone_raporty[STRONA_ZBIORY] = msg
            return
        self._raport_miejsca(msg, STRONA_ZBIORY)

    def _raport_miejsca(self, msg, miejsce, *, wiaz=True):
        """Raport widoku, który mówi o JEDNYM miejscu nawigacji - na pasek, gdy to miejsce widać,
        a inaczej odłożony do wejścia w nie (`_on_nav_changed`). Jedna droga dla raportu wczytania
        Zbiorów i dla osi stanowisk (AR-43): oba padają też po przebiegu Dostawy i oba przykrywały
        wtedy status etapu, mówiąc o ekranie, którego nie widać.

        `wiaz` - czy raport pokazany OD RAZU ma gasnąć przy wyjściu z miejsca (AR-34). Oś stanowisk
        mówi tym samym kanałem także wyniki gestów, a te przeżywały zmianę widoku - zostają przy
        tym (`wiaz=False` = jawne `None` w `_flash`); wynik ze szczegółem - wynik okien „Zatwierdź
        ze ścieżki…” i „Napraw nagłówek…” po zamknięciu - żyje do następnego raportu (AR-236).
        Odłożony raport pada przy wejściu zawsze związany: mówi już wyłącznie o tym ekranie.
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

    def _flash(self, msg, ms=5000, miejsce=_BIEZACA_STRONA, *, gest=True):
        """Raport na pasek — Z ELIZJĄ (FH-2). KAŻDY raport gasi receptę poprzedniego gestu.

        `miejsce` wiąże raport z miejscem nawigacji: wejście gdzie indziej (`_on_nav_changed`)
        zdejmuje go z paska razem z receptą. Jawne `None` - raport bez wiązania: nie gaśnie przy
        przełączeniu widoku (ani raport „Grid: N klatek…", ani `ms=0`). Pominięte (`_BIEZACA_STRONA`)
        - raport bez szczegółu jak przy `None`, raport ze szczegółem związany z bieżącą stroną
        (AR-236, niżej).

        JEDYNE WEJŚCIE NA PASEK - i to jest wymóg, nie wygoda (bramka pakietu, zarzut zgodny
        u dwóch soczewek). Droga obok tej zostawiała receptę poprzedniego gestu nad zdemontowanymi
        widokami (komunikat „brak bazy" idzie BEZ timeoutu, więc wisiała bez końca) i nie
        odświeżała podpowiedzi, która niosła wtedy treść cudzego, wygasłego zdania. `ms=0` znaczy
        „bez wygasania”.

        Gaszenie stoi TUTAJ, a nie u wołającego, bo raport bez recepty przychodzi też stamtąd,
        gdzie o recepcie nikt nie słyszał (etapy Dostawy, odświeżenie gridu). Instrukcja powrotu
        wisząca przy cudzym zdaniu mówiłaby o geście, po którym nie ma już śladu na ekranie.

        `gest` (AR-97): raport otwiera okno priorytetu (`_PRIORYTET_GESTU_MS`), w którym zdanie
        etapu czeka (`_raport_etapu`). Domyślnie TAK - prawie każdy raport odpowiada na ruch
        człowieka (odmowa, wynik gestu, wynik okna); `False` mówią stan okna (baza wczytana, brak
        bazy) i sam raport etapu. Każdy raport zastępuje raport etapu czekający w oknie: ten jest
        starszy od zdania, które właśnie staje na pasku.

        SZCZEGÓŁ JEDZIE W ZDANIU (AR-218): `msg` bywa `ZdanieZeSzczegolem` (awaria zapisu Zbiorów,
        żniw, Dostawy, okna kart po zamknięciu) - podpowiedź paska niesie wtedy zdanie i szczegół,
        a pole raportu glif wskaźnika. Szczegół nie ma własnego pola: czyta się go z ŻYWEGO raportu
        (`szczegol_zdania(self._pelny_komunikat)`), więc znika razem z nim - następny raport,
        wygaśnięcie (`_wygas_raport`), także wyjście z miejsca, z którym raport jest związany.

        RAPORT ZE SZCZEGÓŁEM NIE GAŚNIE ZEGAREM (AR-236): w szczególe stoi plik, który padł, a 5 s
        to za mało, żeby go przeczytać albo skopiować („Kopiuj szczegół”) - okno, z którego raport
        przyszedł, bywa już zamknięte. Dlatego `ms=0` bez względu na to, co podał wołający, a raport
        bez miejsca od wołającego wiąże się z bieżącą stroną. Gaśnie dwiema drogami: wyjście
        z miejsca, z którym jest związany, i następny raport - także zdanie etapu Dostawy, które
        nadeszło w oknie priorytetu: staje po jego końcu (`_wypusc_raport_etapu`, AR-97 bez zmian).
        Jawne `None` od wołającego zostaje bez wiązania: wynik gestu osi (`_raport_miejsca` z
        `wiaz=False`, w tym wynik okien „Zatwierdź ze ścieżki…” i „Napraw nagłówek…”) i raport z tła
        spoza swojej strony (`_flash_grid`, `_flash_dostawy`) żyją wtedy do następnego raportu."""
        szczegol = szczegol_zdania(msg)
        if miejsce is _BIEZACA_STRONA:
            miejsce = self._strona() if szczegol else None
        if szczegol:
            ms = 0
        self._ustaw_recepte("")
        self._pelny_komunikat = msg
        self._miejsce_komunikatu = miejsce
        self._raport_etapu_czeka = ""
        self._wyswietl(msg)
        if ms:
            self._zegar_raportu.start(ms)
        else:
            self._zegar_raportu.stop()
        if gest:
            self._zegar_priorytetu.start()
        else:
            self._zegar_priorytetu.stop()

    def _raport_etapu(self, msg):
        """Zdanie etapu Dostawy („Grupowanie: gotowe.”) - na pasek od razu, chyba że trwa okno
        priorytetu raportu gestu (AR-97): wtedy czeka na jego koniec (`_wypusc_raport_etapu`).

        Zmierzone przed naprawą: odmowa kafla Przyjmij w biegu żyła na pasku 0,39 s, wynik okna
        żniw 0,38 s - każde „gotowe” etapu wypierało świeży raport gestu, zanim ktoś go przeczytał.
        Czeka, a nie idzie na `phase_label`: faza to opis roboty TRWAJĄCEJ i gaśnie z jej końcem
        (`_end_phase`), a „gotowe” mówi o skończonej. Czekający jest jeden - nowszy zastępuje
        starszy, bo liczy się ostatni stan przebiegu (pełną historię niesie panel Dostawy)."""
        if self._zegar_priorytetu.isActive():
            self._raport_etapu_czeka = msg
            return
        self._flash(msg, gest=False)

    def _wypusc_raport_etapu(self):
        """Koniec okna priorytetu: czekające zdanie etapu staje na pasku (zastępuje raport gestu,
        który dostał swoje okno). Bez czekającego - nic."""
        self._zegar_priorytetu.stop()
        msg, self._raport_etapu_czeka = self._raport_etapu_czeka, ""
        if msg:
            self._flash(msg, gest=False)

    def _pokaz_recepte(self, tekst):
        """Recepta ostatniego gestu na własny widżet — i PONOWNY pomiar elizji raportu (FH-2).

        Kolejność jest wymuszona: raport leci pierwszy (`_po_gescie_osi`), więc gdy przychodzi tu
        recepta, komunikat jest już przycięty do zapasu SPRZED jej pojawienia się. Widżet recepty
        zabiera szerokość obok raportu, więc bez tego ponowienia raport wystawałby pod nią - czyli
        sam rozdział członów wyprodukowałby to ucięcie, które miał zdjąć. Zdjęcie recepty oddaje
        miejsce raportowi i zdejmuje ją z podpowiedzi paska - podpowiedź z martwą receptą mówiłaby
        o geście, którego przycisku już nie ma."""
        self._ustaw_recepte(tekst)
        if self._pelny_komunikat:
            self._przelicz_pasek()
        else:
            self.statusBar().setToolTip(self._pelna_recepta)

    def _recepta_porzadkow(self, recepta):
        """Recepta gestu osi w Porządkach („Cofnij dopisanie”, AR-133) - na pasek, gdy Porządki
        widać. Przychodzi PO raporcie gestu, który zgasił receptę poprzedniego gestu, więc kolejność
        daje widok: najpierw zdanie, potem przycisk drogi powrotu.

        RECEPTA ŻYJE ZE SWOIM RAPORTEM (AR-296): zapamiętana razem z obiektem raportu, który ją
        poprzedził - żywym na pasku albo ODŁOŻONYM do wejścia w Porządki (`_raport_miejsca`), gdy wynik
        przyszedł, kiedy człowiek był gdzie indziej. Wejście w Porządki podaje ją ponownie, dopóki na
        pasku stoi ten sam raport (`_on_nav_changed`); nowszy raport ją unieważnia."""
        raport = (self._pelny_komunikat if self._strona() == STRONA_PORZADKI
                  else self._odlozone_raporty.get(STRONA_PORZADKI))
        self._recepta_porzadkow_stan = (recepta, raport) if recepta and raport else None
        if self._strona() == STRONA_PORZADKI:
            self._pokaz_recepte(recepta)

    def _wynik_cofniecia_osi(self, msg, recepta):
        """Zdanie biegu cofnięcia zapisu kart z paska osi (AR-296) - na pasek OD RAZU, bez wiązania
        z miejscem (jak wynik gridu spoza Zbiorów, `_flash_grid`): odmowa zamknięcia okna i przełączenia
        bazy obiecuje, że zapis „pokaże wynik”, a raport odłożony do Porządków nie padłby przed zamknięciem
        i ginąłby przy demontażu widoków. Recepta (ponowienie, powrót po blokadzie) wiąże się z TYM
        obiektem raportu i stoi na pasku przy Porządkach (`_on_nav_changed` poda ją przy wejściu). Raport
        osi odłożony do Porządków jest STARSZY od zdania z receptą (odświeżenie po przebiegu Dostawy) -
        zdanie go zastępuje, inaczej wejście w Porządki postawiłoby go na pasku i zgasiło receptę.
        Tym samym kanałem idą recepty osi odłożone przez blokadę - także „Cofnij dopisanie” (AR-310) -
        i dokończenie cofnięcia z wiersza Porządków (AR-318)."""
        if recepta:
            self._odlozone_raporty.pop(STRONA_PORZADKI, None)
        self._flash(msg, miejsce=None)
        self._recepta_porzadkow_stan = (recepta, msg) if recepta else None
        if recepta and self._strona() == STRONA_PORZADKI:
            self._pokaz_recepte(recepta)

    def _recepta_stoi(self):
        """Czy na pasku stoi recepta, którą ktoś czyta (AR-321, straż `ObjectAxisView._podaj_odlozone`): przycisk
        recepty widoczny (recepta gridu w Zbiorach, osi w Porządkach) ALBO recepta Porządków żywa razem ze swoim
        raportem - na pasku albo odłożonym do wejścia w Porządki (ta sama reguła co `_on_nav_changed`). Recepta,
        której raport ustąpił nowszemu, już nie stoi."""
        if self._czlony_recepty:
            return True
        stan = self._recepta_porzadkow_stan
        return stan is not None and (stan[1] is self._pelny_komunikat
                                     or stan[1] is self._odlozone_raporty.get(STRONA_PORZADKI))

    def _recepta_gridu(self, recepta):
        """Recepta z gridu - na pasek tylko przy widocznych Zbiorach (FH-2e). Grid składa ją ze
        stanu przy KAŻDYM przeładowaniu, także po przebiegu Dostawy, a recepta mówi o Zbiorach;
        przy wejściu w nie widok poda ją ponownie (`FramesView.ponow_recepte`).

        Dom dostaje KAŻDĄ receptę strumienia, niezależnie od widocznej strony: jego „Ostatnio" żyje
        wyłącznie tym strumieniem (pusta recepta zdejmuje ją z Domu), a nie raportami paska.

        Pasek NIE dostaje recepty gridu, gdy niesie gest obiektu wydania (`_gest_wydania_aktywny`):
        grid składa receptę przy każdym przeładowaniu (także po przebiegu Dostawy, w tle), a to nie
        gest człowieka - podmiana zabrałaby „Przypisz obiekt wydania” / „Cofnij” spod kursora."""
        self._recepta_strumienia = recepta if recepta else None
        if self.home_view is not None:
            self.home_view.pokaz_recepte(recepta)
        if self._strona() == STRONA_ZBIORY and not self._gest_wydania_aktywny():
            self._pokaz_recepte(recepta)

    def _wykonaj_recepte(self, *, czlony=None):
        """Klik w receptę = człon PIERWSZY (kolejność członów jest kolejnością w czasie, FH-2e).
        Człon bez wykonawcy ma przycisk wygaszony, więc tu nie dochodzi - warunek jest drugą linią
        obrony, bo sygnał bywa wołany wprost (testy, skróty).

        `czlony` podaje Dom: jego recepta przychodzi ze strumienia i żyje dłużej niż ta na pasku,
        którą gasi każdy cudzy raport. Bez argumentu - człony z paska. Keyword-only, bo `clicked`
        przycisku paska podałby tu `checked: bool`.

        PODWÓJNY KLIK TO JEDEN GEST MOTORYCZNY (Z5). Wykonanie członu zleca gest, który od razu
        zdejmuje swoją receptę z paska i Domu (`FramesView._zacznij_gest`), a receptę odwrotną
        składa ogon po przyłożeniu zbioru w tle (AR-84) - gdy ten zdąży przed drugim klikiem tego
        samego ruchu ręki, klik wykonałby odwrót odwrotu, masowo i bez potwierdzenia, a w trakcie
        składu odbiłby się od odmowy „Czytam klatki…". Po wykonaniu przycisk stoi więc
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
        """Wyrenderuj raport na jego etykietę - po elizji (`_zwezone`). Sam tekst: zegar wygaśnięcia
        stawia `_flash`, więc ponowny pomiar (`_przelicz_pasek`) nie przedłuża życia raportu. Pole
        pokazuje skrót, „Kopiuj zdanie” bierze pełne zdanie (`pelne`). PODPOWIEDŹ JEST JEDNA - paska
        (zdanie, recepta, szczegół; `_zwezone`): podpowiedź pola zasłaniałaby ją nad etykietą bez
        członu recepty, więc schodzi zaraz po `ustaw`.

        UKŁAD PASKA OD RAZU (AR-327): elizja liczy zapas z szerokości PASKA, a etykieta raportu dostaje swoją
        szerokość dopiero przy przeliczeniu układu - do tego czasu rysowałaby nowe zdanie w szerokości starego,
        ucięte bez wielokropka (zmierzone natywnie po `open_path`: 259 px etykiety przy 626 px „Baza: …”, do
        pierwszego obrotu pętli). `activate` przelicza układ paska teraz, przed malowaniem."""
        self.report_label.ustaw(self._zwezone(msg), szczegol_zdania(msg), pelne=msg,
                                polecenie=polecenie_zdania(msg))   # „Kopiuj polecenie” (AR-309)
        self.report_label.setToolTip("")
        uklad = self.statusBar().layout()
        if uklad is not None:
            uklad.activate()

    def _przelicz_pasek(self):
        """Przemierz elizję ŻYWEGO raportu - po każdej zmianie szerokości widżetów obok niego.

        Wołają to cztery powierzchnie, bo wszystkie zabierają albo oddają miejsce raportowi:
        recepta, wejście w fazę, jej koniec i zmiana szerokości okna. Bez tego broniła się przed
        własną szerokością tylko recepta, a faza („Odświeżam widoki po etapie…") wpychała żywy
        raport pod siebie - ten sam defekt, tyle że z drugiej strony paska (bramka pakietu,
        soczewka repo).

        Strażnik „nie nadpisujemy cudzego zdania” z czasów `showMessage` zszedł razem z nim:
        przeliczenie WSKRZESZAŁO wtedy raport, gdy pasek niósł komunikat postawiony z pominięciem
        `_flash`. Etykieta raportu ma jednego pisarza (`_wyswietl`), a wygasły raport zeruje
        `_pelny_komunikat` (`_wygas_raport`), więc nie ma czego wskrzesić."""
        if not self._pelny_komunikat:
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

    def _wygas_raport(self):
        """Raport gaśnie (jego zegar albo wyjście z miejsca, do którego należy): etykieta pustoszeje,
        pełna treść i podpowiedź gasną, podpowiedź zostaje z samą receptą. Okno priorytetu kończy
        się razem z raportem, którego broniło - czekające zdanie etapu staje od razu.

        RECEPTA NIE GAŚNIE TU (FH-2e). Dawniej żyła tyle, co jej raport, i to rodziło dwie klasy
        błędów naraz: dwuczłonowa recepta umierała po wykonaniu pierwszego członu (odświeżenie
        emituje własny raport), a pusty `QStatusTipEvent` z podświetlonej pozycji menu - okno
        przepisywało go na `showMessage("")`, nie do odróżnienia od timeoutu - gasił instrukcję
        w trakcie celowania w pozycję, którą nazywa. Recepta stoi na STANIE: gasi ją cudzy raport
        (`_flash`), wyjście ze Zbiorów i sam widok, gdy przestaje być prawdą. Pusty
        `QStatusTipEvent` trafia dziś w puste pole komunikatu `QStatusBar` i raportu nie dotyka."""
        self._zegar_raportu.stop()
        self._pelny_komunikat = ""
        self._miejsce_komunikatu = None
        self.report_label.setText("")
        self.statusBar().setToolTip(self._pelna_recepta)
        if self._zegar_priorytetu.isActive():
            self._wypusc_raport_etapu()

    def resizeEvent(self, event):
        # Zmiana szerokości okna zmienia zapas raportu - elizja liczona przy innej szerokości
        # cięłaby zdanie bez znaku albo za wcześnie (`_przelicz_pasek`).
        super().resizeEvent(event)
        self._przelicz_pasek()

    def _zwezone(self, msg):
        """Przytnij raport do REALNEGO zapasu paska, jawnym wielokropkiem, z pełną treścią w podpowiedzi.

        Pasek nie ma elizji: przy nadmiarze ucina w środku słowa i nie zostawia po tym żadnego
        znaku, więc zdanie kończące się na „…Przywróć c" wygląda na kompletne. Wielokropek
        zdejmuje to CICHE kłamstwo, a tooltip oddaje treść, której nie da się już zmieścić.

        MIERZYMY DO WIDŻETÓW OBOK RAPORTU, nie do szerokości paska: recepta (zaraz za raportem)
        i faza (widżet stały) zabierają mu miejsce, więc odliczają się od zapasu - bez tego sam
        rozdział z FH-2 kazałby zdaniu ucinać się WCZEŚNIEJ niż przed naprawą. Metryka z fontu
        etykiety raportu, bo to ona rysuje zdanie.

        PODPOWIEDŹ STOI ZAWSZE, NIE TYLKO PRZY CIĘCIU, i to jest odpowiedź na trzy dziury naraz
        (bramka pakietu, oba silniki): gałąź „za wąsko na elizję" oddawała pełny tekst Qt do
        cichego ucięcia i przy okazji KASOWAŁA podpowiedź; zwężenie okna w trakcie życia
        komunikatu tnie zdanie, które przy pomiarze się mieściło; a recepta nie ma jak pokazać
        własnej podpowiedzi, bo jest przezroczysta dla myszy. Jedna podpowiedź z całym zdaniem -
        raport plus recepta - zdejmuje wszystkie trzy bez ani jednej gałęzi.

        PRZED POKAZANIEM OKNA NIE TNIEMY: geometria jest wtedy zastępcza (domyślne 640 px), więc
        elizja liczona z niej okroiłaby zdanie, które w prawdziwym oknie mieści się w całości.

        Szczegół raportu (AR-218) stoi w podpowiedzi wierszem pod zdaniem (jak w polu zdania okien
        zapisu), a glif wskaźnika zabiera zdaniu swoje wcięcie - odliczone od zapasu."""
        bar = self.statusBar()
        szczegol = szczegol_zdania(msg)
        bar.setToolTip("\n".join(x for x in (" · ".join(x for x in (msg, self._pelna_recepta) if x),
                                             szczegol) if x))
        if not bar.isVisible():
            return msg
        stale = sum(w.sizeHint().width() + _PASEK_ODSTEP
                    for w in (self.phase_label, self.recipe_label) if w.isVisible())
        zapas = bar.width() - stale - _PASEK_MARGINES
        if szczegol:
            zapas -= self.report_label._szerokosc_wskaznika()
        fm = QFontMetrics(self.report_label.font())
        if zapas < _PASEK_MIN_KOMUNIKATU or fm.horizontalAdvance(msg) <= zapas:
            return msg
        return fm.elidedText(msg, Qt.ElideRight, zapas)

    def _odmowa_w_biegu_zapisu(self, say, *, przerwij=True):
        """Straż zamknięcia okna i przełączenia bazy: `True` = uchwyt zapisu do plików trwa (szuflada
        Zbiorów albo cofnięcie zapisu kart z paska osi obiektu, AR-296), a `say(tekst)` mówi, co się
        dzieje (`WritebackRunner.refuse_close`). `przerwij` - anulowanie po bieżącym pliku: przy
        zamknięciu okna intencja jest jasna; przełączenie bazy odmawia samym zdaniem, a zapis biegnie
        dalej. Bez bazy i przed montażem widoków (pierwsze `open_path`: argument startu, ostatnia
        baza) - `False` bez dotykania widoków, których jeszcze nie ma."""
        if self.con is None:
            return False
        grid = self._gotowy("grid_view")               # niezbudowane Zbiory nic nie piszą (AR-325)
        if grid is not None and grid._wb.refuse_close(say, przerwij=przerwij):
            return True
        osi = getattr(self, "object_view", None)
        return osi is not None and osi.refuse_close(say, przerwij=przerwij)

    def showEvent(self, event):
        """Okno z bazą otwartą przed pokazaniem (konstruktor z bazą) zamawia dobudowę Zbiorów (`_zamow_dobudowe`)."""
        super().showEvent(event)
        self._zamow_dobudowe()

    def changeEvent(self, event):
        """AKTYWACJA OKNA ZDEJMUJE MARTWE WPISY (AR-348): gest recepty osi zamknięty POZA tym oknem
        (CLI `header-fix --undo`, drugie okno, okno modalne tego okna) nie daje tu żadnego zdarzenia, więc martwa
        recepta stała na pasku do najbliższej chwili podania - a zdanie gotowości cofnięcia kart (`ZdanieZeSzczegolem`,
        `miejsce=None`, bez zegara - `_wynik_cofniecia_osi`, `_flash`) stoi na pasku KAŻDEJ strony. Powrót do okna
        (zmiana aktywacji na aktywne) czyści kolejkę odłożeń z wpisów, którym baza nic nie zostawiła
        (`ObjectAxisView.oczysc_martwe`, idempotentne - każda chwila podania i tak woła je najpierw); recepta i zdanie
        takiego wpisu schodzą z paska (`_zdejmij_martwa_recepte`).

        ...I PODAJE WPIS ZA ZDJĘTĄ GOTOWOŚCIĄ (AR-355): gdy zdjęcie zdjęło z paska gotowość, która wciąż na nim STAŁA
        (`_zdjeta_gotowosc` z `_zdejmij_martwa_recepte`), następny niepodany wpis kolejki wraca teraz ze swoją
        gotowością - doklejoną do zdania, które to zdjęcie przywróciło (`doklej`; nic nie wróciło - sama gotowość) -
        zamiast czekać na wejście w Porządki. Gotowość przykryta wcześniej innym raportem (raport Zbiorów ze szczegółem,
        zdanie postępu cofnięcia) nie stoi, więc nic nie ustępuje: gotowość doklejona do cudzego raportu stałaby potem
        na każdej stronie bez wiązania z miejscem. Zdjęcie wpisu nigdy niepodanego niczego nie podaje: taki wpis czeka
        na swoją chwilę (koniec blokady, wejście w Porządki), a aktywacja nie jest nią.

        TU, nie w `TasksView.event(WindowActivate)`: Qt podaje `WindowActivate` tylko widocznym dzieciom, a Porządki poza
        swoją stroną są ukryte - martwe zdanie na Domu zostałoby. Powrót z innej aplikacji to ta sama zmiana aktywacji
        (kontrakt Qt). Osłona: bez bazy nic; oś obiektu, której `_clear_views` nie zeruje, a którą przemontowanie właśnie
        kasuje (`deleteLater`), nie jest dotykana po skasowaniu (`isValid`). Zdarzenie idzie najpierw do Qt (`super()`)."""
        super().changeEvent(event)
        if (event.type() == QEvent.ActivationChange and self.isActiveWindow() and self.con is not None
                and self.object_view is not None and isValid(self.object_view)):
            self._zdjeta_gotowosc = None
            self.object_view.oczysc_martwe()
            zdjeta, self._zdjeta_gotowosc = self._zdjeta_gotowosc, None
            if zdjeta is not None:
                self.object_view.podaj_odlozone(doklej=zdjeta[0], tylko_niepodane=True)

    def closeEvent(self, event):
        # ZAPIS DO PLIKÓW W TOKU (szuflada Zbiorów) - okno ZOSTAJE, zamknięcie = żądanie anulowania po
        # bieżącym pliku (`WritebackRunner.refuse_close`, jak w oknach kart), drugie zamknięcie po biegu
        # zamyka (AR-280). Zmierzone: okno znikało w biegu, połączenie zamykało się pod wątkiem, który
        # pisał dalej, a ogon zapisu padał `ProgrammingError` na zamkniętej bazie. Bez otwartej bazy
        # widoku Zbiorów nie ma (`_mount_views`) - i nie ma czego pilnować. Poczekalnia bez zapisu w toku
        # NIE pyta: wraca w szufladzie przy następnym otwarciu tej bazy. Ta sama straż obejmuje
        # cofnięcie zapisu kart z paska Porządków (AR-296) - `_odmowa_w_biegu_zapisu`.
        if self._odmowa_w_biegu_zapisu(self._flash):
            event.ignore()
            return
        self._wstrzymaj_dobudowe()             # zamknięte okno niczego nie dobudowuje (AR-325)
        # Top-level apka jest właścicielem połączenia - zamyka je przy zamknięciu okna. Wątki tła
        # widoków PRZED połączeniem: wynik doręczony po zamknięciu nie ma prawa go dotknąć.
        self._zatrzymaj_watki_widokow()
        if self.con is not None:
            self.con.close()
            self.con = None
        super().closeEvent(event)


# ======================================== STRAŻ BŁĘDU PROGRAMU (AR-302) i TŁUMACZ Qt - rejon `main`
# Importy tu, nie w bloku modułu: obie rzeczy żyją wyłącznie dla `main` (start programu).
import logging  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
from typing import NamedTuple  # noqa: E402

from PySide6.QtCore import QEventLoop, QLibraryInfo, QObject, QStandardPaths, QTranslator, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QPlainTextEdit  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from horreum.gui import dziennik_bledow  # noqa: E402
from horreum.gui.wb_worker import tekst_powodu, wiersz_systemu  # noqa: E402
from horreum.item_reasons import PowodPozycji, powod_okna, powod_zapisu_dziennika  # noqa: E402

_LOG = logging.getLogger(__name__)


def katalog_dziennika_bledow():
    """Katalog dziennika błędów programu (AR-312): `<dane programów użytkownika>\\Horreum` z
    `GenericDataLocation` (Windows: `%LOCALAPPDATA%\\Horreum`) albo None, gdy system go nie podał.
    `GenericDataLocation`, nie `AppLocalDataLocation`: ta druga bez ustawionych nazw aplikacji bierze
    nazwę pliku wykonywalnego (`…\\python` z kodu, `…\\horreum-gui` z wydania - zmierzone 2026-10-22),
    a ta - ani od nazw, ani od katalogu bieżącego nie zależy; ścieżka z kodu i z wydania jest jedna."""
    baza = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not baza:
        return None
    return os.path.normpath(os.path.join(baza, "Horreum"))


def otworz_dziennik_bledow():
    """„Pomoc → Otwórz dziennik błędów” i przycisk okna błędu: plik w programie systemu albo zdanie, dlaczego
    nie (None = otwarty) - brak katalogu, brak pliku (program nie zgłosił jeszcze błędu), odmowa systemu."""
    katalog = katalog_dziennika_bledow()
    if katalog is None:
        return i18n.t("main.prog_error.log_no_dir")
    plik = dziennik_bledow.sciezka(katalog)
    if not os.path.isfile(plik):
        return i18n.t("main.prog_error.log_empty", path=plik)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(plik)):
        return i18n.t("main.prog_error.log_open_failed", path=plik)
    return None


class ZapisDziennika(NamedTuple):
    """Wynik dopisania zgłoszenia do dziennika: `sciezka` pliku po zapisie, `blad` - powód porażki
    (`powod_okna`); oba None - dziennika nie ma gdzie zapisać (system nie podał katalogu)."""
    sciezka: object = None
    blad: object = None


class Zgloszenie(NamedTuple):
    """To, co hak straży przekazuje do okna: powód (`powod_okna`, liczony raz w wątku haka) i zapis
    dziennika - okno i wpis mówią o tym samym obiekcie."""
    powod: object
    zapis: ZapisDziennika


class StrazBledowProgramu(QObject):
    """Wyjątek, którego nikt nie złapał (slot Qt, metoda wirtualna, wątek tła) → OKNO błędu programu
    z miejscem w kodzie (AR-302). Do AR-302 pakiet nie miał haka: PySide6 6.9.2 oddaje wyjątek ze
    slotu `sys.excepthook`, a domyślny hak drukuje go na `stderr`, którego wydanie okienkowe
    (`console=False`) nie ma - błąd przepadał bez śladu, okno stało dalej bez słowa (zmierzone).

    WĄTEK: hak bywa wołany w wątku tła (slot obiektu w `QThread` - zmierzone; `threading.excepthook`
    zawsze), a okno wolno budować wyłącznie w wątku GUI. Hak liczy powód TAM, gdzie go wołano (ślad
    pełny - `powod_okna` bierze z niego miejsce `@ horreum/…:N`), i emituje `zgloszony`; obiekt straży
    żyje w wątku GUI, więc z wątku tła sygnał idzie kolejką.

    OKNO NIEMODALNE, JEDNO NARAZ: `show`, nie `exec` - hak nie kręci zagnieżdżonej pętli, a wyjątek
    z `paintEvent` (seria: 3 wywołania w 50 ms, zmierzone) nie wchodzi ponownie w okno. Kolejne
    zgłoszenia przy stojącym oknie podbijają jego licznik; zgłoszenie po zamknięciu okna otwiera NOWE
    okno z własnym licznikiem - nic nie ginie po cichu.

    BEZ REKURSJI I BEZ CISZY: budowa okna stoi pod przejściową blokadą reentrancji - zgłoszenie, które
    przyjdzie w jej trakcie, i każde zgłoszenie po tym, jak własne okno raz padło, idzie do okna
    zastępczego (`QMessageBox`); poprzedni hak dostaje zgłoszenie dopiero, gdy padnie i ono. Trwałe
    wyłączenie straży odpadło: w wydaniu bez konsoli poprzedni hak nie ma dokąd pisać, więc drugi,
    niezależny błąd przepadał. Każde zgłoszenie idzie też do poprzedniego haka, gdy jest `sys.stderr`
    (konsola deweloperska zachowuje ślad). `BaseException` spoza `Exception` (przerwanie z klawiatury,
    wyjście) - wyłącznie poprzedni hak. Wyjątek synchroniczny startu - `pokaz_przed_wyjsciem`.

    DZIENNIK (AR-312): każde zgłoszenie (okno własne, zastępcze, błąd startu) hak dopisuje do pliku
    dziennika błędów (`dziennik_bledow`) W WĄTKU HAKA, przed emisją - wpis zostaje także wtedy, gdy pętla
    okna już nie ruszy. Okno mówi, gdzie zapisano (i ma „Otwórz dziennik”), a porażka zapisu nie zdejmuje
    okna i nie jest ciszą: okno mówi, że dziennika nie zapisano, ze szczegółem. Zapis nigdy nie rzuca
    z haka (`_do_dziennika`) - reguła „bez rekursji” obejmuje i jego."""

    zgloszony = Signal(object)          # `Zgloszenie` (powód + zapis dziennika) - `object`: kod klasy i parametry

    def __init__(self, katalog_dziennika=None):
        super().__init__()
        self._dziennik = None if katalog_dziennika is None else dziennik_bledow.Dziennik(katalog_dziennika)
        self._wersja = None             # `horreum.__version__` - liczona leniwie przy pierwszym zgłoszeniu
        self._poprzedni = sys.excepthook
        self._poprzedni_watku = threading.excepthook
        self._w_budowie = False         # blokada reentrancji na czas budowy i pokazania okna
        self._okno_zepsute = False      # własne okno padło - zgłoszenia idą do okna zastępczego
        self._start = False             # błąd startu: program się zakończy (`pokaz_przed_wyjsciem`)
        self.okno = None                # ostatnie okno (QDialog) - testy czytają je wprost
        self._lbl_kolejne = None
        self._kolejne = 0
        self.zastepcze = []             # okna zastępcze (`QMessageBox`) - trzymane, testy czytają je wprost
        self.zgloszony.connect(self._pokaz)

    def zainstaluj(self):
        sys.excepthook = self._hak
        threading.excepthook = self._hak_watku

    def zdejmij(self):
        """Poprzednie haki z powrotem (koniec `main`; testy wołają `main` kilka razy w jednej sesji)."""
        sys.excepthook = self._poprzedni
        threading.excepthook = self._poprzedni_watku

    @staticmethod
    def _bez_aplikacji():
        """Stan straży przed `QApplication` (`main`, AR-324): `QDialog`/`QMessageBox` i `QEventLoop` bez aplikacji
        widżetów to twarde przerwanie procesu - nie dziennik, nie okno."""
        return not isinstance(QApplication.instance(), QApplication)

    def pokaz_przed_wyjsciem(self, exc):
        """Wyjątek SYNCHRONICZNY startu (budowa okna głównego, otwarcie bazy startowej) - wychodzi z `main`
        ramkami, a interpreter wołałby hak dopiero po `finally`, który straż już zdjął: w wydaniu bez konsoli
        program zamykał się bez słowa. Tu zgłoszenie idzie przy żywej straży, a pętla zdarzeń kręci się, aż
        człowiek zamknie okno błędu (albo okno zastępcze). Wołający kończy program kodem błędu. Błąd PRZED
        `QApplication` (albo samej `QApplication`, AR-324): wpis w dzienniku i `stderr`, bez okna i bez pętli."""
        self._start = True
        self._hak(type(exc), exc, exc.__traceback__)
        if self._bez_aplikacji():
            return
        petla = QEventLoop()

        def _sprawdz():
            widoczne = [o for o in (self.okno, *self.zastepcze) if o is not None and isValid(o) and o.isVisible()]
            if not widoczne:
                petla.quit()
        takt = QTimer()
        takt.timeout.connect(_sprawdz)
        takt.start(50)
        petla.exec()
        takt.stop()

    def _zglos(self, wartosc, tb, watek):
        try:
            powod = powod_okna(wartosc)
        except Exception:               # klasyfikacja padła - surowy tekst, ale ślad zostaje
            powod = f"{type(wartosc).__name__}: {self._tekst(wartosc)}"
        zapis = self._do_dziennika(wartosc, tb, watek, powod)
        try:
            self.zgloszony.emit(Zgloszenie(powod, zapis))
        except Exception:
            self._poprzedni(*sys.exc_info())

    @staticmethod
    def _tekst(wartosc):
        try:
            return str(wartosc)
        except Exception:               # zepsuty `__str__` wywraca zwykle i klasyfikację - sama klasa
            return "?"

    def _do_dziennika(self, wartosc, tb, watek, powod):
        """Wpis zgłoszenia w dzienniku (`ZapisDziennika`) - nigdy nie rzuca: porażka wraca powodem do okna.
        Nagłówek wpisu: błąd programu - `Typ: opis @ plik:N` (`detail` powodu okna); inna klasa (system,
        baza) - `Typ: opis`, miejsce stoi w śladzie."""
        if self._dziennik is None:
            return ZapisDziennika()
        try:
            detail = (dict(powod.params).get("detail")
                      if isinstance(powod, PowodPozycji) and powod.code == "prog_error" else None)
            if not (isinstance(detail, str) and detail):
                detail = f"{type(wartosc).__name__}: {self._tekst(wartosc)}"
            if self._wersja is None:
                import horreum
                self._wersja = horreum.__version__
            return ZapisDziennika(sciezka=self._dziennik.zapisz(
                czas=datetime.now().astimezone().isoformat(timespec="seconds"), wersja=self._wersja,
                watek=watek, naglowek=detail,
                slad="".join(traceback.format_exception(type(wartosc), wartosc, tb))))
        except Exception as exc:
            try:
                return ZapisDziennika(blad=powod_zapisu_dziennika(exc))   # klasa także spoza tabeli (AR-324)
            except Exception:
                return ZapisDziennika(blad=f"{type(exc).__name__}: {self._tekst(exc)}")

    def _hak(self, typ, wartosc, tb):
        if sys.stderr is not None or not isinstance(wartosc, Exception):
            self._poprzedni(typ, wartosc, tb)
        if isinstance(wartosc, Exception):
            self._zglos(wartosc, tb, threading.current_thread().name)

    def _hak_watku(self, args):
        wartosc = args.exc_value
        if sys.stderr is not None or not isinstance(wartosc, Exception):
            self._poprzedni_watku(args)
        if isinstance(wartosc, Exception):
            self._zglos(wartosc, args.exc_traceback, getattr(args.thread, "name", "?"))

    @Slot(object)
    def _pokaz(self, zgloszenie):
        """Zgłoszenie → okno. Zgłoszenie W TRAKCIE budowy okna (pokazanie maluje, malowanie może rzucić
        i wrócić tu hakiem) i każde zgłoszenie po tym, jak własne okno raz padło, idzie do okna
        zastępczego - nic nie jest wyłączane na stałe: kolejny błąd zawsze ma widoczny ślad. Dopiero
        porażka okna zastępczego oddaje zgłoszenie poprzedniemu hakowi. Kolejne zgłoszenie przy stojącym
        oknie odświeża też linię dziennika - porażka późniejszego zapisu nie jest ciszą. Bez `QApplication`
        (straż stoi przed nią, AR-324) okna nie ma jak zbudować - zgłoszenie zostaje w dzienniku i `stderr`."""
        powod, zapis = zgloszenie
        if self._bez_aplikacji():
            return
        if self._w_budowie or self._okno_zepsute:
            self._pokaz_zastepczo(powod, zapis)
            return
        # Okno ma za rodzica okno aktywne w chwili błędu - zamknięty dialog-rodzic kasuje je razem
        # z sobą, więc obiekt Pythona bywa pusty (`isValid`); takie okno jest po prostu zamknięte.
        self._w_budowie = True
        try:
            zywe = self.okno is not None and isValid(self.okno)
            if zywe and self.okno.isVisible():
                self._kolejne += 1
                self._lbl_kolejne.setText(i18n.t_plural("main.prog_error.more", self._kolejne))
                self._lbl_kolejne.setVisible(True)
                self._ustaw_dziennik(self.okno, zapis)
                return
            if zywe:
                self.okno.deleteLater()
            self._kolejne = 0
            self.okno = None
            self.okno = self._zbuduj_okno(powod, zapis)
            self.okno.show()
            self.okno.raise_()
        except Exception:
            self._okno_zepsute = True
            if sys.stderr is not None:
                self._poprzedni(*sys.exc_info())
            self._pokaz_zastepczo(powod, zapis)
        finally:
            self._w_budowie = False

    @staticmethod
    def _linia_dziennika(zapis):
        """(zdanie, szczegół) linii dziennika w oknie: zapisano (ze ścieżką) / nie zapisano (powód
        i szczegół systemu) / nie ma gdzie zapisać."""
        if zapis.sciezka is not None:
            return i18n.t("main.prog_error.log_saved", path=zapis.sciezka), ""
        if zapis.blad is not None:
            szczegol = wiersz_systemu(zapis.blad) if isinstance(zapis.blad, PowodPozycji) else ""
            return i18n.t("main.prog_error.log_failed", msg=tekst_powodu(zapis.blad)), szczegol
        return i18n.t("main.prog_error.log_no_dir"), ""

    def _ustaw_dziennik(self, okno, zapis):
        """Linia dziennika i przycisk „Otwórz dziennik” okna własnego (przycisk tylko po zapisie)."""
        zdanie, szczegol = self._linia_dziennika(zapis)
        okno.lbl_dziennik.ustaw(zdanie, szczegol)
        okno.btn_dziennik.setVisible(zapis.sciezka is not None)

    def _zdanie(self, powod):
        """Zdanie okna (własnego i zastępczego): błąd programu słowem katalogu, klasa bazy/systemu swoim.
        Błąd startu (`pokaz_przed_wyjsciem`) mówi, że program nie wystartował - okno główne jest schowane,
        a „Zamknij” kończy program; zdanie „okno działa dalej” byłoby nieprawdą."""
        klucz = "main.prog_error.text_start" if self._start else "main.prog_error.text"
        if isinstance(powod, PowodPozycji) and powod.code == "prog_error":
            return i18n.t(klucz, msg=i18n.t("main.prog_error.what"))
        return i18n.t(klucz, msg=tekst_powodu(powod))

    def _pokaz_zastepczo(self, powod, zapis):
        """Okno zastępcze: zwykły `QMessageBox` (instancja, przycisk z katalogu) ze zdaniem błędu programu,
        linią dziennika i szczegółem z miejscem w kodzie (na końcu) - bez pól i menu własnego okna. Przy
        stojącym oknie zastępczym kolejne zgłoszenie podbija jego licznik (jak w oknie własnym) i odświeża
        linię dziennika, zamiast otwierać następne - seria z `paintEvent` po zamknięciu okna odsłaniającego
        widżet zalewałaby ekran oknami."""
        try:
            zywe = [o for o in self.zastepcze if isValid(o) and o.isVisible()]
            if zywe:
                okno = zywe[-1]
                okno.kolejne += 1
                okno.setInformativeText(i18n.t_plural("main.prog_error.more", okno.kolejne))
                okno.setText(self._tekst_zastepczy(okno.zdanie, zapis, okno.szczegol))
                return
            szczegol = wiersz_systemu(powod) if isinstance(powod, PowodPozycji) else ""
            zdanie = self._zdanie(powod)
            okno = QMessageBox(QMessageBox.Critical, i18n.t("main.prog_error.title"),
                               self._tekst_zastepczy(zdanie, zapis, szczegol))
            okno.addButton(i18n.t("main.prog_error.close"), QMessageBox.AcceptRole)
            okno.setModal(False)
            okno.kolejne = 0
            okno.zdanie, okno.szczegol = zdanie, szczegol
            self.zastepcze = [okno]
            okno.show()
        except Exception:
            self._poprzedni(*sys.exc_info())

    def _tekst_zastepczy(self, zdanie, zapis, szczegol):
        """Tekst okna zastępczego: zdanie, linia dziennika (z jej szczegółem), szczegół błędu na końcu."""
        return "\n\n".join(c for c in (zdanie, *self._linia_dziennika(zapis), szczegol) if c)

    def _zbuduj_okno(self, powod, zapis):
        """Okno: zdanie (pole zdania ze szczegółem pod kursorem i w menu), szczegół WIDOCZNY w polu
        tylko-do-odczytu (okno ma na niego miejsce), linia dziennika błędów (gdzie zapisano albo dlaczego
        nie) z „Otwórz dziennik”, licznik kolejnych błędów, przyciski z katalogu."""
        zdanie = self._zdanie(powod)
        szczegol = wiersz_systemu(powod)
        okno = QDialog(QApplication.activeWindow())
        okno.setModal(False)
        okno.setWindowTitle(i18n.t("main.prog_error.title"))
        lay = QVBoxLayout(okno)
        pole = EtykietaBledu()
        pole.setWordWrap(True)
        pole.ustaw(zdanie, szczegol)
        lay.addWidget(pole)
        okno.pole = pole
        okno.szczegol = QPlainTextEdit(szczegol)
        okno.szczegol.setReadOnly(True)
        okno.szczegol.setVisible(bool(szczegol))
        lay.addWidget(okno.szczegol)
        okno.lbl_dziennik = EtykietaBledu()
        okno.lbl_dziennik.setWordWrap(True)
        lay.addWidget(okno.lbl_dziennik)
        self._lbl_kolejne = QLabel("")
        self._lbl_kolejne.setVisible(False)
        okno.lbl_kolejne = self._lbl_kolejne
        lay.addWidget(self._lbl_kolejne)
        rzad = QHBoxLayout()
        rzad.addStretch(1)
        okno.btn_dziennik = QPushButton(i18n.t("main.prog_error.open_log"))

        def _otworz_dziennik():
            zdanie_otwarcia = otworz_dziennik_bledow()
            if zdanie_otwarcia is not None:     # plik zniknął albo system odmówił - zdanie w oknie
                okno.lbl_dziennik.ustaw(zdanie_otwarcia, "")
        okno.btn_dziennik.clicked.connect(_otworz_dziennik)
        rzad.addWidget(okno.btn_dziennik)
        self._ustaw_dziennik(okno, zapis)
        okno.btn_kopiuj = QPushButton(i18n.t("main.prog_error.copy"))
        okno.btn_kopiuj.setEnabled(bool(szczegol))
        okno.btn_kopiuj.clicked.connect(lambda: QGuiApplication.clipboard().setText(szczegol))
        rzad.addWidget(okno.btn_kopiuj)
        okno.btn_zamknij = QPushButton(i18n.t("main.prog_error.close"))
        okno.btn_zamknij.setDefault(True)
        okno.btn_zamknij.clicked.connect(okno.close)
        rzad.addWidget(okno.btn_zamknij)
        lay.addLayout(rzad)
        return okno


def zainstaluj_tlumacza_qt(app, jezyk):
    """Tłumacz Qt `qtbase_<język UI>` (teksty samego Qt: menu kontekstowe pól - „Cofnij”, „Wklej” -
    i przyciski standardowe okien spoza katalogu) albo None. Idzie za językiem UI PROGRAMU, nie systemu:
    UI EN na polskim Windows zostaje angielskie (`en` - bez tłumacza, Qt mówi po angielsku sam).
    Brak pliku `.qm` (wydanie bez tłumaczeń) to nie powód, żeby program nie wstał (kod u klienta):
    ostrzeżenie w logu i dalej po angielsku. Zdejmuje go `main` w tym samym `finally`, co haki straży."""
    if jezyk == "en":
        return None
    tlumacz = QTranslator(app)
    katalog = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not tlumacz.load(f"qtbase_{jezyk}", katalog):
        _LOG.warning("tłumacz Qt: brak qtbase_%s w %s - teksty Qt zostają po angielsku", jezyk, katalog)
        tlumacz.deleteLater()
        return None
    app.installTranslator(tlumacz)
    return tlumacz


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

    # Straż błędu programu PIERWSZA (AR-302, AR-324): przed `QApplication`, `QSettings`, motywem, językiem
    # i tłumaczem - błąd któregokolwiek z nich trafia do dziennika i kończy program kodem błędu. Dwa stany
    # JEDNEJ straży (jeden zestaw haków - bez podwójnego wpisu): bez aplikacji dziennik i `stderr`, bez okna
    # (`QDialog` bez `QApplication` to twarde przerwanie); po niej - okno błędu. Katalog dziennika z
    # `QStandardPaths` jest ten sam przed aplikacją i po niej (zmierzone: = `%LOCALAPPDATA%`). Straż
    # i tłumacza zdejmuje `finally`: testy wołają `main` kilka razy na jednej `QApplication`, a hak
    # i tłumacz to stan procesu.
    straz = StrazBledowProgramu(katalog_dziennika_bledow())     # dziennik błędów (AR-312)
    straz.zainstaluj()
    app = tlumacz = None
    try:
        # Przechwycenie obejmuje WYŁĄCZNIE start synchroniczny, nie `app.exec()`: wyjątek z pętli
        # zdarzeń (w testach - z podmienionego `exec`) wychodzi z `main` od razu, zamiast czekać, aż ktoś
        # zamknie okno błędu. Okno główne, które zdążyło stanąć, chowa się na czas okna błędu (w połowie
        # zamontowane przyjmowałoby gesty, a powrót z `main` nie przechodzi przez jego `closeEvent`),
        # a po nim zamyka się zwykłą drogą.
        okna = []
        try:
            app = QApplication.instance() or QApplication([])

            # Trwałe ustawienia (Windows: rejestr) - przechowują ścieżkę ostatnio otwartej bazy i motyw.
            settings = QSettings("Horreum", "Horreum")

            # Motyw PRZED oknem (F6 §7): domyślnie ciemny; paleta/QSS/kolory stanów podłączone globalnie.
            apply_theme(app, theme.normalize(settings.value("ui/theme", theme.DEFAULT)))

            # Język PRZED oknem (#1, lustro motywu): jawny wybór z QSettings, inaczej auto z locale systemu
            # (gdy w available_langs), inaczej PL. Ustawiamy `_LANG` RAZ - stałe→klucze w widokach rozwiążą
            # etykiety z katalogu w czasie budowy (D-L1 restart-required v1; `_LANG` nie mutuje w sesji).
            saved_lang = settings.value("ui/lang", None)
            auto_lang = saved_lang if saved_lang is not None else QLocale().name()[:2]
            i18n.set_lang(auto_lang)

            # Teksty samego Qt (menu pól, przyciski standardowe) w języku UI programu.
            tlumacz = zainstaluj_tlumacza_qt(app, i18n.current_lang())
            _start_okna(argv, settings, okna)
        except Exception as exc:
            for w in okna:
                w.hide()
            straz.pokaz_przed_wyjsciem(exc)
            for w in okna:
                w.close()
            return 1
        return app.exec()
    finally:
        straz.zdejmij()
        if tlumacz is not None:
            app.removeTranslator(tlumacz)
            tlumacz.deleteLater()


# Klucz ustawień ostatnio otwartej bazy: pisze go `_start_okna` (start z ostatnią bazą), czyta też katalog startowy
# okien bazy (`MainWindow._katalog_okna_bazy`, AR-378) - jedno miejsce nazwy.
_KLUCZ_OSTATNIEJ_BAZY = "ostatnia_baza"


def _start_okna(argv, settings, okna):
    """Start synchroniczny `main` (pod strażą i tłumaczem): baza startowa i okno - dopisane do `okna`, zanim
    cokolwiek może rzucić po jego pokazaniu. Pętlę zdarzeń kręci `main`."""
    if argv:
        start = argv[0]
    else:
        start = settings.value(_KLUCZ_OSTATNIEJ_BAZY, None)
        # Ostatnia baza mogła zostać przeniesiona/usunięta — wtedy startujemy bez bazy (nie wybuchamy).
        if start and not Path(start).exists():
            start = None

    def zapamietaj_baze(path):
        settings.setValue(_KLUCZ_OSTATNIEJ_BAZY, path)

    # OKNO STAJE PRZED CZYTANIEM BAZY (F-1). Do tej zmiany `MainWindow(start)` otwierał bazę
    # i montował cztery widoki W KONSTRUKTORZE, a `show()` szedł dopiero po nim — zmierzone
    # 4 649 ms na żywej `pf4`, przez które na ekranie nie było NICZEGO (a w wydaniu onefile
    # dochodzi do tego rozpakowanie bootloadera). Użytkownik pytał wtedy nie „czy trwa", tylko
    # „czy ono w ogóle wstało" — i nie miał gdzie przeczytać odpowiedzi.
    # Kolejność jest tu CAŁĄ naprawą: okno bez bazy → faza na środku → dopiero odczyt.
    win = MainWindow(on_db_changed=zapamietaj_baze)
    okna.append(win)
    win.show()
    if start:
        # Faza PRZED pierwszym przemalowaniem: bez tego okno błysnęłoby zdaniem „Brak bazy",
        # które za moment i tak przestaje być prawdą.
        win._say_phase(i18n.t("busy.open_db", name=Path(start).name))
        busy.repaint()
        win.open_path(start)
