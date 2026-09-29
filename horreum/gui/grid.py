"""Widok „Klatki" — grid nad EAV `cards` z filtrem i perspektywami (PLAN_gui_grid, KROK 3 scalenia).

READ-ONLY wobec danych (edycja/writeback = KROK 4). Doktryna §5: grid jest jedynym centrum, wszystko
inne to soczewki — ZERO modali w głównym przepływie. Warstwa widżetów (na whiteliście `test_gui_isolation`);
cała logika (silnik filtra, pivot, read-model) siedzi w Qt-wolnych `horreum.filter_engine`/`horreum.pivot`/
`horreum.gui.queries`. Model port `fitsmirror/gui/grid_model.py` (3 stany komórki + sort), bez edycji/stagingu.

Kolumny BAZOWE (warstwa interpretacji nad lustrem) + dynamiczne kolumny-keywordy z `cards`. Perspektywy =
nazwane {filtr+kolumny+grupowanie+sort} w **BAZIE** (`saved_query.spec_json`, migracja 0013) + presety
zaszyte w kodzie. **D-B ODWRÓCONE 2026-08-01 (GO Zdzinia, D-P-I-3), WDROŻONE w I-1:** nazwany widok jest
własnością ARCHIWUM, nie komputera — jedzie z bazą na laptop i przeżywa reinstalację. Rejestr zostaje
własnością BIURKA (progi, ostatnie katalogi); perspektywy zapisane w nim przed tą zmianą wciąga
JEDNORAZOWY, idempotentny import przy otwarciu widoku (`_import_settings_perspectives`) — wydanie
publiczne miało tę funkcję w `QSettings`, więc ciche porzucenie cudzych widoków byłoby regresją,
nie sprzątaniem. Grupowanie minimalne: nagłówki
grup po jednej kolumnie bazowej (D-D). `present` = kolumna statusu (zniknięte tłowane); Duplikaty = n_present>1.

F3 (PLAN_ux_redesign §4): pasek ZBIORU (`SelectionBar` — licznik + kryteria słowami + akcje) nad
`_PanelStack`, w którym klingi (`MacroBar`/`RenameBar`) są PANELAMI otwieranymi z akcji — widoczny
najwyżej JEDEN; przełączenie na cudzy panel czyści podgląd dotychczasowego właściciela (R#9).
"""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QItemSelection, QItemSelectionModel,
    QModelIndex, QObject, Qt, QSettings, QThread, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QDialog, QDialogButtonBox, QMenu, QMessageBox,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTableView, QToolButton,
    QVBoxLayout, QWidget,
)

from horreum import (db, filter_engine, lineage, macro as macro_mod, naming, pivot as pivot_mod,
                     repo, stacks, writeback)
from horreum.gui import busy, facet_model, i18n, portfolio, queries, rows, theme
from horreum.gui import pola as pola_mod   # `pola` bywa w tym pliku zmienną lokalną (pola zeznania)
from horreum.gui.facets import RAIL_MIN_W as _FIELDS_MIN_W, FacetRail
from horreum.gui import assign_dialog
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.projection_dialog import ProjectionDialog
from horreum.gui.rows import TwoPartDelegate
from horreum.gui.wb_worker import WritebackRunner, commit_do_cofniecia, zdanie_wyniku_zapisu
from horreum.resolve.headers import COPY_TESTIMONY_KEYWORDS

# Kolumny bazowe: (nagłówek, klucz). Klucze `_telescope`/`_object`/`_dt_delta` = pochodne. `_dt_delta`
# (Δh nagłówek−nazwa) liczone w `_derive` z `naming.header_dt`/`filename_dt` — `base_rows` zwraca już
# date_obs+path (zero zmian SQL). Kolumna renamu: grupowanie po Δh wykrawa homogeniczny wsad (§1).
# Para (klucz-etykiety, klucz-danych). Klucz-etykiety → i18n.t w BUDOWIE nagłówka (headerData), nie
# module-level (D-L1). Etykiety reużyte z katalogu app (col.path/frame.col.*/object.col.name) — SPOT.
BASE_COLS = [
    ("col.path", "path"), ("grid.col.kind", "kind"), ("frame.col.camera", "camera_model"),
    ("frame.col.telescope", "_telescope"), ("object.col.name", "_object"),
    ("frame.col.filter", "filter_canon"), ("grid.col.dt_delta", "_dt_delta"),
    # „Obrazy" (0021) - liczba obrazów KOPII; przy kilku kopiach wszystkie różne wartości („3 | 1",
    # `_dolacz_kopie`). Na końcu listy: kolumny szukane po kluczu nie przesuwają się, a tabela
    # przewija się w poziomie, więc podłoga okna (D-0801-1) zostaje, gdzie była.
    ("grid.col.images", "_images"),
]
_MISSING_TEXT = "—"

# TOOLTIP KOLUMNY „Obiekt" PER STAN (R-S3-4) — mapa, bo powodów jest cztery i każdy niesie inną
# RECEPTĘ, nie samą diagnozę: „nazwa z nagłówka" poprawia się w PLIKU, nagrobek — drugim gestem
# ręki, a kalibracji nie poprawia się wcale, bo obiektu nie ma z definicji. Jeden wspólny tooltip
# („to nie jest przypisany obiekt") mówiłby prawdę i nie dawał nikomu drogi dalej.
# Stan `canon` klucza NIE MA świadomie: nazwa mówi wtedy sama za siebie, a tooltip na każdej
# komórce kolumny byłby szumem pod kursorem. Parytet z katalogiem pilnuje bramka w `test_i18n`
# (klucz składany w locie jest dla kolektora literałów NIEWIDZIALNY — wzorzec `grid.lin.cal.gap.*`).
_OBJECT_STATE_TIPS = {
    "cleared": "grid.cell.object_cleared_tip",
    "kind": "grid.cell.object_kind_tip",
    "raw": "grid.cell.object_raw_tip",
    "hint": "grid.cell.object_hint_tip",
}


def _cleared_tip(row):
    """Zdanie nagrobka zależy od tego, CO STOI W KOMÓRCE (FC-1) — a to rozstrzyga pamięć z 0017.

    Trzy zdania, bo są trzy różne prawdy, a jedno wspólne kłamałoby w dwóch z nich:
    z pamięcią komórka pokazuje obiekt ZDJĘTY RĘKĄ (i wtedy warto dopowiedzieć, co niesie nagłówek
    pliku, bo to jest droga do naprawy trwałej); bez pamięci pokazuje nazwę Z NAGŁÓWKA, więc zdanie
    „to zdjęła ręka" byłoby o niej fałszem, a gest „Przywróć" nie ma czego odtworzyć i mówi o tym
    wprost („bez zapamiętanego obiektu: N", `queries.restore_targets`).

    Nagrobek bez pamięci nie jest hipotezą: baza-dawca sprzed migracji 0017 wwozi je legalnie
    (migracja 0017:29) — odmowa ich wpuszczenia byłaby utratą werdyktu ręki."""
    if not row.get("object_cleared_canon"):
        return i18n.t("grid.cell.object_cleared_nomem_tip")
    raw = row.get("object_raw")
    return (i18n.t("grid.cell.object_cleared_raw_tip", raw=raw) if raw
            else i18n.t("grid.cell.object_cleared_tip"))


def _object_tip(row, stan):
    """Zdanie stanu kolumny „Obiekt" — JEDEN wybór dla komórki i dla nagłówka grupy (FC-3).
    Belka bierze zdanie z wiersza wzorcowego kubełka, ale wolno jej to zrobić dopiero wtedy, gdy
    kubełek mówi jednym głosem - rozstrzyga `GridTableModel._group_tip_mode`, nie ta funkcja.

    Podpowiedź `hint` ma DWA zdania: w drzewie `STACKS` folder niesie nazwę i istnieje droga
    potwierdzenia ze ścieżki, w układzie WBPP nie - jedno wspólne zdanie byłoby o stosach
    z drzewa nieprawdą („nazwy nie niosą tożsamości")."""
    if stan == "hint" and queries.hint_from_stacks_tree(row.get("path")):
        return i18n.t("grid.cell.object_hint_stacks_tip")
    return _cleared_tip(row) if stan == "cleared" else i18n.t(_OBJECT_STATE_TIPS[stan])


def _group_tip(marker, stan):
    """Zdanie BELKI grupy — trzy tryby, bo kubełek nie zawsze mówi jednym głosem (bramka pakietu
    0815, zarzut zgodny u DWÓCH soczewek).

    Kubełek zbiera się po TEKŚCIE komórki, a tekst nagrobka jest ten sam niezależnie od tego, czy
    klatka niesie zeznanie nagłówka i czy baza pamięta zdjęty obiekt. Belka cytująca `bucket[0]`
    orzekała więc o całej grupie to, co jest prawdą o JEDNEJ klatce — a przy pierwszym masowym
    cofnięciu obejmującym klatki z nagłówkiem i bez (845 klatek nieba nie ma `object_raw`) zdanie
    zmieniałoby się jeszcze po kliknięciu w nagłówek kolumny, bo `bucket[0]` zależy od sortu.

    - `exact` — wszystkie wiersze mają te same fakty: belka mówi dokładnie to, co komórki pod nią;
    - `base`  — wszystkie pamiętają zdjęty obiekt, ale różnią się zeznaniem: zdanie BEZ klauzuli
      o nagłówku, bo klauzula z jednej klatki byłaby o pozostałych nieprawdą;
    - `None`  — kubełek miesza nagrobki z pamięcią i bez: belka MILCZY. Wariantu bazowego użyć tu
      nie wolno (twierdzi „baza pamięta"), a wariant bez pamięci mówi „nie ma czego przywracać" —
      obie wersje są fałszem o połowie wierszy. To ta sama reguła, którą stosuje `_group_state`."""
    tryb = marker.get("_group_tip")
    if tryb is None:
        return None
    if tryb == "base":
        return i18n.t("grid.cell.object_cleared_tip")
    return _object_tip(marker["_group_row"], stan)


# Pusty grid mówi DWIE różne rzeczy — filtr nic nie wpuścił vs. w bazie nie ma nic (wiz F5 #8:
# „zmień filtr lub perspektywę" na pustej bazie wysyła usera w ślepy zaułek zamiast po dostawę).
# Stałe trzymają KLUCZ (nie string) — rozwiązywane `i18n.t` w USE-site (D-L1; string zamroziłby PL).
# NIEPUSTA BAZA MÓWI Z PRZYCZYNY PUSTKI (FH-4, poprawka po firsthandzie): wariant wybiera decyzja
# recepty `_rodzaj_recepty_powrotu` pytana o klatki WIDOKU (`_CEL_WIDOK`) - ta sama metoda, z której
# pasek bierze receptę dla klatek GESTU, ale inne pytanie. Ogólne „zmień filtr lub perspektywę" przy
# facecie wskazywało gest, który niczego nie odsłania; pierwsza poprawka pytała o klatki gestu i w
# trimie, który MA klatki, wyrzucała z kolejki na „Przegląd" (firsthand: „Do przeglądu").
_EMPTY_FILTER = "grid.empty_filter"   # pustkę robi zbiór (facety/filtr) - gest: „× Wyczyść zbiór"
_EMPTY_PERSP = "grid.empty_persp"     # perspektywa bez ani jednej klatki - gest: „Przegląd"
_EMPTY_VIEW = "grid.empty_view"       # brak recepty (dziś nieosiągalny) - zdanie bez obietnicy gestu
_EMPTY_DB = "grid.empty_db"

# Kolory stanów gridu — z motywu (F6 §7, SPOT). Model czyta `_COLORS` NA ŻYWO w `data()`
# (Qt nie cache'uje BackgroundRole), więc `use_theme` przy przełączeniu + `viewport().update()`
# przemalowuje bez przebudowy modelu. Klucze: missing (foreground braku) / vanished_bg (present=0)
# / dup_bg (>1 obecna) / group_bg (nagłówek grupy) / touched_bg (dotknięty makrem) / skipped_bg
# / superseded_bg (treść pod ścieżką podmieniona — klatka jest historią, nie robotą).
_COLORS: dict[str, QColor] = {}


def use_theme(name):
    """Przeładuj kolory stanów gridu z motywu (Qt-wolny `theme.grid_colors`). Wołane przy imporcie
    oraz przez `app.apply_theme` przy przełączeniu skórki.

    `secondary_text` dokładamy z akcentów, bo wygaszony wiersz listy (odrzucone wejście rodowodu)
    to QListWidgetItem, a QSS ról nie dosięga do `setForeground` itemu — ta sama droga, którą
    `tasks.use_theme` gasi wiersze bez roboty."""
    _COLORS.update({k: QColor(v) for k, v in theme.grid_colors(name).items()})
    _COLORS["secondary_text"] = QColor(theme.accents(name)["secondary_text"])


use_theme(theme.DEFAULT)     # init przy imporcie (QColor bez QApplication — jak dawne stałe modułu)


def _vanished_tip(row):
    """Człon tooltipu kolumny ścieżki dla klatki ZNIKNIĘTEJ — z DATĄ, gdy baza ją zna.

    Wizytacja P5 #11: przy szukaniu backupu liczy się katalog i data. Katalog tooltip niósł od
    początku (pełna ścieżka), daty NIE niósł nikt — a `location.last_verified_at` na wierszu
    `present=0` jest dokładnie chwilą oznaczenia (patrz `queries.base_rows`). Kolumna zostaje przy
    nazwie pliku: doklejenie katalogu do DISPLAY zjadałaby elizja, a zmiana dotknęłaby wszystkich
    perspektyw, nie tylko „Zniknięte". Data do MINUT, bez „T" (wzorzec `app._fmt_event_ts`).
    Baza sprzed markera (`NULL`) → człon bez daty; brak faktu nie ma prawa udawać faktu."""
    ts = row.get("last_verified_at")
    if not ts:
        return i18n.t("grid.tip.vanished")
    return i18n.t("grid.tip.vanished_at", ts=str(ts)[:16].replace("T", " "))


def _former_tip(row):
    """Człon tooltipu ścieżki dla klatki, która ma ŻYWĄ kopię i zna też adres MARTWY - historia przeprowadzki.

    Wariant rozwojowy D-V-9 (decyzja Zdzinia 2026-08-14). Sama naprawa adresu ucisza kłamstwo, ale
    KASUJE Z EKRANU fakt, który baza zna: że ten obraz leżał wcześniej gdzie indziej. Klatka zna OBA
    adresy, więc stary przestaje być śmieciem do ukrycia i staje się odpowiedzią na pytanie zadawane
    w chwili wątpliwości - „przecież to leżało w starym drzewie, gdzie się podziało". Zmierzona
    populacja to 128 gotowych obrazów po uporządkowaniu drzewa stosów.

    Człon DOKLEJA SIĘ do werdyktu wiersza, nie konkuruje z nim: „×2 obecne lokalizacje" i „wcześniejszy
    adres" to dwa różne fakty o tej samej klatce. Wołający pilnuje jedynego warunku sensu - że POKAZANY
    adres jest żywy, bo inaczej „wcześniejszy" wskazywałby to, co user właśnie czyta w komórce.

    DWA STANY SPEŁNIAJĄ TEN WARUNEK I OBA DOSTAJĄ CZŁON ŚWIADOMIE (bramka pakietu, Z3/F5): klatka
    z kilkoma kopiami, z których część zniknęła, oraz klatka WYCOFANA, KTÓREJ PLIK WRÓCIŁ
    (`queries.retired_conflict_frame_ids` - stan modelowany, z własnym wierszem Porządków). W drugim
    przypadku tooltip mówi naraz „wycofana, a plik wrócił" i „wcześniejszy adres" - to dwa prawdziwe
    fakty o tej samej klatce, nie sprzeczność. Milczą natomiast stany BEZ żywej kopii (zniknięta,
    wycofana bez powrotu, zastąpiona): tam pokazany adres SAM jest tym martwym.

    TEN CZŁON I PERSPEKTYWA „Brakujące kopie" LICZĄ TEN SAM ZBIÓR (D-V-9d). Do tej zmiany
    `queries.missing_copy_frame_ids` wycinał klatkę wycofaną guardem `retired_at IS NULL`, a ten
    człon ją pokazywał - wiersz obiecywał „wszystkie naraz", a jednej nie oddawał. Rozstrzygnięcie
    idzie za FAKTEM: kopia zniknęła niezależnie od gestu ręki, więc predykat zdjął guard, a wiersz
    tłumaczy się własnym znacznikiem wycofania w komórce."""
    path = row.get("vanished_path")
    if not path:
        return ""
    n = row.get("n_vanished") or 0
    if n > 1:
        return i18n.t("grid.tip.former_paths", n=n, path=path)
    return i18n.t("grid.tip.former_path", path=path)


def _retired_tip(row):
    """Człon tooltipu ścieżki dla klatki WYCOFANEJ RĘKĄ — ZAWSZE z datą i ZAWSZE z drogą powrotu.

    Data jest tu treścią, nie ozdobą: to jedyny fakt o wycofaniu, którego po geście nie da się
    odtworzyć skądinąd (`retired_at` jest jego jedynym nośnikiem). Wzmianka o powrocie stoi
    w tooltipie, a nie tylko w menu, bo tooltip czyta się DOKŁADNIE w chwili wątpliwości
    („czemu ten wiersz jest inny") — a wtedy wiedza „to się cofa" jest najwięcej warta."""
    return i18n.t("grid.tip.retired", ts=str(row.get("retired_at"))[:16].replace("T", " "))


def _retired_back_tip(row):
    """Człon tooltipu ścieżki dla klatki WYCOFANEJ, KTÓREJ PLIK WRÓCIŁ (G2-7d) - bliźniak `_retired_tip`.

    Zdanie zwykłej wycofanej („pliku już nie szukamy") jest o tej klatce NIEPRAWDĄ: plik leży na
    dysku i to właśnie czyni ten stan robotą. Człon mówi więc trzy rzeczy: kiedy ręka wycofała
    (data - jak u bliźniaka, jedyny nośnik tego faktu), że przesłanka werdyktu upadła, i którędy
    ją zamknąć. Werdykt NIE gaśnie sam, bo wjazd materiału nie cofa gestu ręki („ręka
    nietykalna") - dlatego tooltip wskazuje gest, a nie obiecuje, że stan minie."""
    return i18n.t("grid.tip.retired_back", ts=str(row.get("retired_at"))[:16].replace("T", " "))


def _superseded_tip(row):
    """Człon tooltipu ścieżki dla klatki ZASTĄPIONEJ — ZAWSZE z adresem następczyni.

    Adres jest tu treścią, nie ozdobą: „zastąpiona" bez wskazania, DOKĄD poszła treść, jest
    zarzutem bez odpowiedzi — a to jedyne zdanie, po którym user widzi, że nic nie zginęło.
    Wzorzec `_vanished_tip`, z jedną różnicą: tam data bywa nieznana i człon się kurczy, tu
    `superseded_by` jest NOT NULL z definicji predykatu, więc wariantu bez adresu nie ma."""
    return i18n.t("grid.tip.superseded", id=row.get("superseded_by"))


def _set_role(w, role):
    """Zmiana roli koloru (`theme.ROLES` → QSS aplikacji) na ŻYWYM widżecie. Samo `setProperty` nic
    nie przemaluje: selektor `[role="…"]` jest ewaluowany przy POLISHU, więc widżet już pokazany
    trzyma stary kolor do końca życia. Dotyczy jedynej roli zmiennej w locie — kropki poczekalni."""
    w.setProperty("role", role)
    w.style().unpolish(w)
    w.style().polish(w)

# Operatory filtra: (klucz-etykiety, op). Etykieta → i18n.t w budowie combo; op to DANE (regex POMINIĘTY, D-F).
OPERATORS = [
    ("grid.op.eq", "eq"), ("grid.op.ne", "ne"), ("grid.op.gt", "gt"), ("grid.op.lt", "lt"),
    ("grid.op.ge", "ge"), ("grid.op.le", "le"), ("grid.op.contains", "contains"),
    ("grid.op.startswith", "startswith"), ("grid.op.exists", "exists"),
    ("grid.op.not_exists", "not_exists"),
]
_NO_VALUE = {"exists", "not_exists"}

# Szum strukturalny FITS: keywordy o najwyższym pokryciu, ale bez wartości analitycznej. Spychane na dół
# listy Pól i pomijane przy domyślnym doborze kolumn (P3-6) — NIE ukrywane (user może chcieć NAXIS jako kolumnę).
STRUCT_NOISE = {"SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND", "BZERO", "BSCALE", "END",
                "XBINNING", "YBINNING", "XPIXSZ", "YPIXSZ", "PCOUNT", "GCOUNT"}

# Presety perspektyw (zaszyte): (nazwa, {filter_tree, group_by}). Kolumny domyślne dobierane z pokrycia.
# PRESET_DUPS = stała współdzielona z TasksView (F5R#11 — klik w zadanie „Duplikaty" celuje w preset
# po nazwie; rename presetu bez stałej cicho degradowałby klik do „nieznana perspektywa").
PRESET_DUPS = "Duplikaty"
# PRESET_VANISHED — bliźniak PRESET_DUPS dla passa obecności (P5/#7): klik w zadanie „Zniknięte
# z dysku" celuje w preset PO NAZWIE, więc stała musi być współdzielona z TasksView.
PRESET_VANISHED = "Zniknięte"
# PRESET_LINEAGE — trzeci bliźniak (0808). Gest rodowodu mieszka w panelu „Rodowód" TEGO widoku
# i działa z zaznaczenia jednej klatki, więc wiersz Porządków „Obrazy bez rodowodu" nie ma dokąd
# prowadzić POZA Zbiorami: perspektywa jest tu jedyną drogą od liczby do listy. Stała współdzielona
# z TasksView po nazwie — jak u dwóch sąsiadów wyżej.
PRESET_LINEAGE = "Rodowód"
# PRESET_SUPERSEDED — czwarty bliźniak (0809, decyzja Zdzinia „z widocznym nagrobkiem"). Klatka
# zastąpiona wypadła ze WSZYSTKICH kubełków kolejki (nie jest robotą), więc bez własnej perspektywy
# byłaby wyłącznie w gridzie pełnym — czyli do znalezienia tylko przez przypadek. Stała współdzielona
# z TasksView po nazwie, jak trzej sąsiedzi wyżej.
PRESET_SUPERSEDED = "Zastąpione"
# PRESET_RETIRED — piąty bliźniak (D-OW-3/R2). Klatka WYCOFANA ręką wypada z kubełków roboczych
# dokładnie tak jak zastąpiona, więc bez własnej perspektywy nie byłoby ani jak jej znaleźć, ani
# — co ważniejsze — jak jej PRZYWRÓCIĆ: gest powrotu bierze cel z zaznaczenia, a zaznaczyć można
# tylko to, co widać. Perspektywa nie jest tu więc wygodą, tylko drugą połową odwracalności.
PRESET_RETIRED = "Wycofane"
# PRESET_MISSING_COPY - szósty bliźniak (D-V-9a). Klatka ŻYJE, ale jedna z jej kopii zniknęła:
# stan, którego do tej paczki NIE WIDZIAŁA żadna powierzchnia. „Zniknięte" go nie obejmują (żądają
# BRAKU żywej kopii), „Duplikaty" też nie (liczą wyłącznie obecne, więc widzą nadmiar, nie ubytek),
# a po naprawie D-V-9 fakt ten dało się zobaczyć WYŁĄCZNIE w tooltipie - jeden wiersz naraz, przy
# populacji 128. Stała współdzielona z TasksView po nazwie, jak pięciu sąsiadów wyżej.
PRESET_MISSING_COPY = "Brakujące kopie"
# PRESET_RETIRED_CONFLICT - siódmy bliźniak (G2-7d). Wiersz Porządków „Wycofane, a plik wrócił"
# jest ROBOTĄ i do tej zmiany prowadził do „Wycofanych", czyli do listy SZERSZEJ niż jego liczba:
# przy populacji 2 (wycofana z plikiem + wycofana bez pliku) ekran mówił „1" i pokazywał dwa
# wiersze, a „Przywróć" na tym drugim cofało werdykt ręki o klatce, której pliku naprawdę nie ma.
# Predykat istniał (`queries.retired_conflict_frame_ids`, ten sam, który liczy wiersz) - brakowało
# perspektywy, która go używa. Stała współdzielona z TasksView po nazwie, jak sześciu sąsiadów.
PRESET_RETIRED_CONFLICT = "Wycofane, a plik wrócił"
# PRESET_STACK_VERSIONS - ósmy bliźniak. Ten sam materiał zintegrowany kilka razy: inne piksele,
# więc „Duplikaty" tych plików nie widzą, a user chce je sprzątać. Perspektywa ustawia wersje obok
# siebie (grupowanie `_GRUPA_WERSJI`) z faktami do decyzji w kolumnie „Wersja"; Horreum niczego nie
# kasuje - gest „Zostaw tę wersję" kopiuje ścieżki pozostałych do schowka. Stała współdzielona
# z TasksView po nazwie, jak siedmiu sąsiadów.
PRESET_STACK_VERSIONS = "Wersje stosów"
# PRESET_COPY_CONFLICT - dziewiąty bliźniak (0021). Kopie JEDNEJ klatki (te same piksele pierwszego
# obrazu) mówią różnie: inny FILTER w nagłówku, inna liczba obrazów. „Duplikaty" widzą nadmiar kopii,
# nie widzą sprzeczności między nimi - a to od niej zależy, co oś klatki pokazuje. Podzbiór
# „Duplikatów" z konstrukcji (`queries.copy_conflict_frame_ids`). Stała współdzielona z TasksView po
# nazwie, jak ośmiu sąsiadów.
PRESET_COPY_CONFLICT = "Kopie niezgodne"
# PRESET_ORPHAN_TESTIMONY - dziesiąty bliźniak (AR-5). Zeznanie klatki pochodzi z kopii, której już
# nie ma, a obecne kopie mówią co innego. „Kopie niezgodne" tego nie widzą (porównują obecne kopie
# ze sobą, a te bywają zgodne), „Duplikaty" też nie. Lista pytań do człowieka
# (`queries.orphan_testimony_frame_ids`): ≥2 obecne kopie albo zeznanie napisane ręką - klatki
# o jednej kopii i zeznaniu spoza ręki naprawia Dostawa, więc tu ich nie ma. Stała współdzielona
# z TasksView po nazwie, jak dziewięciu sąsiadów.
PRESET_ORPHAN_TESTIMONY = "Zeznanie z nieobecnej kopii"
# PRESET_PATH_HEADER_CONFLICT - jedenasty bliźniak (E5-2). Obiekt klatki zatwierdził człowiek
# z folderu (`object_source='path'`), a karta `OBJECT` w pliku mówi co innego albo coś, czego
# drabina nie zna. „Do przeglądu" tego nie widzi (klatka MA obiekt), więc bez tej perspektywy
# rozjazd pliku z bazą nie miał żadnej powierzchni. Predykat
# `queries.path_header_conflict_frame_ids`. Stała współdzielona z TasksView po nazwie, jak
# dziesięciu sąsiadów.
PRESET_PATH_HEADER_CONFLICT = "Nagłówek inny niż folder"
# PRESET_TORN_WRITE - dwunasty bliźniak (0022, Q8). Kopia, której zapis nagłówka w miejscu przerwano
# albo nie przeszedł weryfikacji: nagłówek mógł zostać rozdarty, więc kopia jest izolowana od skanu.
# Predykat `queries.torn_write_frame_ids`. Stała współdzielona z TasksView po nazwie.
PRESET_TORN_WRITE = "Plik po przerwanym zapisie"
# PRESET_PENDING_FINISH - trzynasty bliźniak (warunek wsadu AR-17 (1)). Kopia, której zapis
# w miejscu przeszedł weryfikację, ale kontrola danych i re-sync bazy jeszcze się nie udały: plik
# ma nowy nagłówek, baza stary, a skan kopię pomija. Robotą jest DOKOŃCZENIE, nie odzysk - stąd
# osobna perspektywa obok przerwanego zapisu. Predykat `queries.pending_finish_frame_ids`. Stała
# współdzielona z TasksView po nazwie.
PRESET_PENDING_FINISH = "Zapis czeka na dokończenie"
# Klucz grupowania po GRUPIE WERSJI - pochodna wiersza (`_adnotuj_wersje`), nie kolumna bazowa:
# `BASE_COLS` zostaje bez zmian, więc podłoga okna się nie rusza. Pozycja listy „Grupuj wg" działa
# w każdej perspektywie (stosy spoza grup bliźniaków lądują w „(brak)"), a preset ją ustawia.
_GRUPA_WERSJI = "_wersja_grupa"
PRESETS = {
    "Przegląd": {"filter": None, "group_by": None},
    "Kalibracja": {"filter": {"op": "OR", "conditions": [
        {"keyword": "IMAGETYP", "operator": "contains", "value": "dark"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "flat"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "bias"},
    ]}, "group_by": "kind"},
    PRESET_DUPS: {"filter": None, "group_by": None, "only_dups": True},
    PRESET_VANISHED: {"filter": None, "group_by": None, "only_vanished": True},
    PRESET_LINEAGE: {"filter": None, "group_by": None, "only_lineage": True},
    PRESET_SUPERSEDED: {"filter": None, "group_by": None, "only_superseded": True},
    PRESET_RETIRED: {"filter": None, "group_by": None, "only_retired": True},
    PRESET_RETIRED_CONFLICT: {"filter": None, "group_by": None, "only_retired_conflict": True},
    PRESET_MISSING_COPY: {"filter": None, "group_by": None, "only_missing_copy": True},
    PRESET_STACK_VERSIONS: {"filter": None, "group_by": _GRUPA_WERSJI, "only_stack_versions": True},
    PRESET_COPY_CONFLICT: {"filter": None, "group_by": None, "only_copy_conflict": True},
    PRESET_ORPHAN_TESTIMONY: {"filter": None, "group_by": None, "only_orphan_testimony": True},
    PRESET_PATH_HEADER_CONFLICT: {"filter": None, "group_by": None,
                                  "only_path_header_conflict": True},
    PRESET_TORN_WRITE: {"filter": None, "group_by": None, "only_torn_write": True},
    PRESET_PENDING_FINISH: {"filter": None, "group_by": None, "only_pending_finish": True},
    "Do przeglądu": {"filter": None, "group_by": None, "only_review": True},
}
# Etykieta WYŚWIETLANIA presetu (tekst) osobno od TOŻSAMOŚCI (klucz PRESETS w `itemData` — używany przez
# `apply_perspective`/`_on_perspective`/`tasks.py`, odporny na tłumaczenie tekstu). Split D-L3.
_PRESET_LABELS = {
    "Przegląd": "perspective.review",
    "Kalibracja": "perspective.calibration",
    PRESET_DUPS: "perspective.dups",
    PRESET_VANISHED: "perspective.vanished",
    PRESET_LINEAGE: "perspective.lineage",
    PRESET_SUPERSEDED: "perspective.superseded",
    PRESET_RETIRED: "perspective.retired",
    PRESET_RETIRED_CONFLICT: "perspective.retired_conflict",
    PRESET_MISSING_COPY: "perspective.missing_copy",
    PRESET_STACK_VERSIONS: "perspective.stack_versions",
    PRESET_COPY_CONFLICT: "perspective.copy_conflict",
    PRESET_ORPHAN_TESTIMONY: "perspective.orphan_testimony",
    PRESET_PATH_HEADER_CONFLICT: "perspective.path_header_conflict",
    PRESET_TORN_WRITE: "perspective.torn_write",
    PRESET_PENDING_FINISH: "perspective.pending_finish",
    "Do przeglądu": "perspective.to_review",
}
# PERSPEKTYWA BEZ ZAWĘŻENIA - jedyny preset, który nie niesie ani filtra, ani flagi `only_*`
# (`PRESETS` wyżej), więc przejście na nią odsłania KAŻDY zbiór: `_on_perspective` przepisuje
# z niej także facety i filtr. Recepta powrotu po geście osi (FC-2) wskazuje ją imiennie, więc
# nazwa nie może być literałem w dwóch miejscach - a bramka pilnuje, że ten preset naprawdę
# jest czysty (`test_gui_grid`, `_PRESET_CZYSTY`).
_PRESET_CZYSTY = "Przegląd"
# PARA FLAGA → ZAPYTANIE MA JEDNO MIEJSCE (BP-4): `refresh()` buduje z tej tabeli listę trimów,
# a `_trim_aktywny()` odpowiada z niej recepcie powrotu. Wcześniej recepcie odpowiadał atrybut
# instancji stawiany RAZ w `refresh()`: poprawny wyłącznie przez kolejność wywołań, bez strażnika.
# Ta rodzina wykłada się dokładnie na kopiach enumeracji (`483df93`: siedem flag wpiętych w osiem
# miejsc i jedno pominięte), więc lekarstwem nie jest ósma kopia, tylko brak drugiej.
#
# OD G2-7d TO JEST JEDYNA ENUMERACJA RODZINY. BP-4 zdjął z ręcznej listy dwóch konsumentów
# z siedmiu, a pięciu (`__init__`, `_on_perspective`, `apply_object_facet`, serializacja spec-a,
# `_describe_criteria`) trzymało dalej własną kopię - i ósma flaga musiałaby trafić w dziewięć
# miejsc. Teraz każdy z nich iteruje tę tabelę, a trzy nazwy jednej flagi wynikają z JEDNEJ
# konwencji zamiast z trzech list: atrybut widoku `_only_X`, klucz spec-a `only_X` (bez
# podkreślnika - tak zapisują go bazy użytkowników, więc tej nazwy nie wolno zmieniać) i klucz
# paska kryteriów `grid.criteria.only_X`. Konwencję i komplet pinuje bramka
# `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`, łącznie z parytetem kluczy katalogu i18n.
#
# NAZWY ZAPYTAŃ, NIE OBIEKTY FUNKCJI: wiązanie późne zostawia drogę podmianie w teście
# (`monkeypatch.setattr(queries, …)`) i nie zamraża referencji z chwili importu. Koszt zerowy,
# a literał `dup_frame_ids` dalej jest greppowalny.
_TRIMY = (
    ("_only_dups", "dup_frame_ids"),
    ("_only_review", "review_frame_ids"),
    ("_only_vanished", "vanished_frame_ids"),
    ("_only_lineage", "lineage_pending_frame_ids"),
    ("_only_superseded", "superseded_frame_ids"),
    ("_only_retired", "retired_frame_ids"),
    ("_only_retired_conflict", "retired_conflict_frame_ids"),
    ("_only_missing_copy", "missing_copy_frame_ids"),
    ("_only_stack_versions", "stack_version_frame_ids"),
    ("_only_copy_conflict", "copy_conflict_frame_ids"),
    ("_only_orphan_testimony", "orphan_testimony_frame_ids"),
    ("_only_path_header_conflict", "path_header_conflict_frame_ids"),
    ("_only_torn_write", "torn_write_frame_ids"),
    ("_only_pending_finish", "pending_finish_frame_ids"),
)

# FLAGA, OD KTÓREJ ZALEŻY ZACHOWANIE WIDOKU, NIE TYLKO ZBIÓR: w perspektywie „Wersje stosów" model
# pokazuje kolumnę „Wersja", a tabela menu z gestem „Zostaw tę wersję". Nazwa atrybutu jako stała,
# nie literał `self._only_…` w źródle - bramka `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`
# pilnuje, żeby rodzina nie dostała drugiej, ręcznej enumeracji; to jest JEDNO odwołanie do jednej
# flagi, a jej obecność w `_TRIMY` pinuje test perspektywy.
_FLAGA_WERSJI = "_only_stack_versions"
# Te same zasady dla dwóch perspektyw izolacji zapisu w miejscu: w nich menu tabeli pokazuje drogi
# wyjścia z izolacji także nad pustym zaznaczeniem (wygaszone z powodem), a wejście w perspektywę
# podaje receptę gestu (`_RECEPTY_ZAPISU`). Klucz = flaga z `_TRIMY`.
_RECEPTY_ZAPISU = {
    "_only_torn_write": "grid.inplace.recipe_torn",
    "_only_pending_finish": "grid.inplace.recipe_pending",
}


def _klucz_spec(atrybut):
    """Klucz flagi w spec-u perspektywy (`_only_dups` → `only_dups`) - JEDNO miejsce konwencji."""
    return atrybut[1:]


def _klucz_kryterium(atrybut):
    """Klucz i18n flagi na pasku kryteriów (`_only_dups` → `grid.criteria.only_dups`)."""
    return "grid.criteria." + _klucz_spec(atrybut)


# Klucze spec-a, które TEN build umie zastosować. Flagi `only_*` dochodzą z `_TRIMY`, więc nowa
# perspektywa nie ma tu drugiego miejsca do dopisania.
_ZNANE_KLUCZE_SPECU = frozenset({"filter", "columns", "group_by", "facets"}
                                | {_klucz_spec(atrybut) for atrybut, _ in _TRIMY})


def _nieznane_warunki(spec):
    """Które ustawienia perspektywy `spec` ten build POMIJA - lista nazw, posortowana (D-V-9f).

    Perspektywa mieszka w BAZIE i jedzie z archiwum, więc bazę zapisaną NOWSZYM wydaniem otworzy
    kiedyś starsze. Spec czytamy przez `.get`, a nieznany klucz nie rzuca - więc flaga `only_*`,
    której ten build nie zna, znikała bez śladu i perspektywa pokazywała zbiór SZERSZY niż zapisany,
    pod własną nazwą. Migracja `0013_saved_query_spec.sql` nazywa tę pułapkę wprost. Starszych
    wydań już nie zmienimy; zabezpieczamy przyszłe, więc funkcja NIE zna żadnej konkretnej flagi -
    pyta wyłącznie o to, czego ten build nie umie.

    Liczy dwie rzeczy, bo mechanizm cichego pominięcia jest ten sam:
      * klucz najwyższego poziomu spoza `_ZNANE_KLUCZE_SPECU` - każdy, nie tylko `only_*`, bo
        nowsze wydanie może nazwać zawężenie inaczej, a starsze nie ma jak tego rozróżnić;
      * facet spoza `facet_model.FACETS` - `compose` iteruje wyłącznie znane facety, więc wybór
        w nieznanym też cicho poszerza zbiór.

    Wartość PUSTA (`False`, `None`, `[]`, `{}`) nie jest warunkiem: tak nowsze wydanie zapisuje flagę
    wyłączoną (`_save_perspective` zapisuje KAŻDĄ flagę, także fałszywą), a jej pominięcie nie
    zmienia zbioru. Zliczanie jej kazałoby ostrzegać przy każdej perspektywie z nowszej wersji."""
    nieznane = [k for k, v in spec.items() if k not in _ZNANE_KLUCZE_SPECU and v]
    facety = spec.get("facets")
    if isinstance(facety, dict):
        nieznane += [f"facets.{f}" for f, wybor in facety.items()
                     if f not in facet_model.FACETS and wybor
                     and ((wybor.get("in") or wybor.get("ex")) if isinstance(wybor, dict) else True)]
    return sorted(nieznane)


# RODZAJ RECEPTY POWROTU - wynik JEDNEJ decyzji (`FramesView._rodzaj_recepty_powrotu`), którą czyta
# każda powierzchnia mówiąca „jak odsłonić to, czego nie widać" (FH-4). Rodzaj nazywa GEST, nie
# zdanie: brzmienia są własne (pasek mówi „odsłoni je …", pusty stan nie ma się do czego odnieść),
# a wybór ma jedno miejsce. Dwie kopie wyboru rozjechały się już raz dokładnie tak (FH-4: pasek
# wskazywał „× Wyczyść zbiór", pusty stan „zmień filtr").
_POWROT_PERSPEKTYWA = "perspektywa"   # przejście na `_PRESET_CZYSTY` - zdejmuje trim, facety i filtr
_POWROT_ZBIOR = "zbior"               # „× Wyczyść zbiór" - zdejmuje facety i filtr, perspektywa zostaje
# CEL PYTANIA O RECEPTĘ - jawny, bo „co odsłonić" to DWA pytania (FH-4, poprawka po firsthandzie).
# W trimie, który ma klatki, odpowiedzi są różne: klatki wypchnięte gestem wypadły z SAMEJ
# perspektywy (przypisany obiekt wyrzuca z „Do przeglądu"), a pustkę widoku robi tam zbiór.
_CEL_GEST = "gest"                    # klatki wypchnięte ostatnim gestem osi - recepta paska stanu
_CEL_WIDOK = "widok"                  # klatki bieżącego widoku - pusty stan


_KANONY_W_ZDANIU = 3
"""Ile nazw obiektów mieści się w zdaniu po geście, zanim reszta pójdzie jako `(+N)`.

Masowe cofnięcie potrafi objąć klatki kilku obiektów naraz (gest nie ma bramki jednorodności —
ma ją tylko NADANIE, bo tam brak jednego przedmiotu znaczy brak jednej nazwy do wpisania).
Wypisanie wszystkich zamieniłoby pasek stanu w listę; trzy pierwsze plus liczba mówią i CO
zdjęto, i ŻE było tego więcej."""


def _lista_kanonow(canons, maks=_KANONY_W_ZDANIU):
    """Kanony do zdania: do `maks` nazw po przecinku, reszta jako `(+N)`. Czysta funkcja.

    PORZĄDEK ROZSTRZYGA SIĘ TUTAJ, NIE U KLINGI (FC-7) - bo obcięcie do trzech jest własnością
    ZDANIA, a nie zapisu. Dwie klingi jednej pary gestów zbierały kanony w dwóch różnych
    porządkach: cofnięcie w kolejności KLATEK (`repo.clear_object_assignment`), przywrócenie
    alfabetycznie (`queries.restore_targets`, `ORDER BY o.canon`). Przy siedmiu obiektach oba
    zdania pokazywały więc ROZŁĄCZNE trójki tego samego zbioru - „NGC6960, NGC5194, NGC3623 (+4)"
    kontra „IC434, LMC, Moon (+4)" - i nie dawały się zestawić wzrokiem, choć mówiły o tym samym.

    Sortowanie tutaj domyka to dla WSZYSTKICH gestów naraz, także przyszłych: kolejność zbierania
    zostaje prywatną sprawą klingi, a zdanie ma jeden porządek. `sorted()` zgadza się z `ORDER BY`
    SQLite dla tych nazw (domyślna kolacja BINARY porównuje bajty UTF-8, czyli po code poincie)."""
    nazwy = sorted(canons)
    if len(nazwy) <= maks:
        return ", ".join(nazwy)
    return ", ".join(nazwy[:maks]) + i18n.t("grid.sel.object_canons_more", n=len(nazwy) - maks)


def zdanie_pominiec(gest, *, nothing_key="grid.sel.object_skip_nothing"):
    """Człony zdania po geście osi obiektu: rozbicie pominięć PER FAKT plus „w tym gotowe obrazy".
    Czysta funkcja; pusty łańcuch, gdy gest nie ma czego dopowiedzieć.

    JEDEN DOM PĘTLI DLA TRZECH POWIERZCHNI (R-S2b-13). O tym samym `repo.ObjectGesture` mówią gesty
    paska Zbiorów (`_po_gescie_osi`), zatwierdzanie propozycji ze ścieżki i nadanie z kolejki
    przeglądu (oba w `gui.app`). Dwie ostatnie miały własne ogony i spłaszczały pominięcia do
    „pominięte N - zajęte między oknem a zapisem", także o darku, którego nikt nie zajął, choć
    klinga oddaje rozbicie per fakt. Trzy siedziby jednej pętli to trzy okazje, żeby człon
    dołożony do `skipped_breakdown` pojawił się na jednym ekranie, a z dwóch pozostałych zniknął -
    dokładnie ta klasa, dla której rozbicie ma jednego właściciela w klasie gestu.

    Liczniki idą osobno, bo znaczą co innego: „kalibracja" to ochrona, która zadziałała, a „zmieniły
    się w międzyczasie" to ostrzeżenie, że stan uciekł. SKŁAD I KOLEJNOŚĆ członów bierzemy
    z `skipped_breakdown`, nie z literału tutaj: człon dołożony później wpadłby do sumy „z M"
    i zniknął z rozbicia, czyli dokładnie stamtąd, gdzie ma tłumaczyć.

    CZASOWNIK CZŁONU „nothing" NALEŻY DO GESTU, NIE DO CZŁONU (FC-6) - dlatego `nothing_key`:
    „nie było czego cofać" przy przywracaniu kłamałoby o kierunku zapisu. Pozostałe człony (rodzaj,
    źródło, pamięć, dryf, odmowa klingi) są neutralne wobec kierunku, więc zostają wspólne.

    Gotowe obrazy NIE stoją w pętli pominięć (D-OW-7): od chwili, gdy stos jest w zasięgu gestów,
    ta liczba mówi o tym, co gest ZROBIŁ, a nie czego nie tknął - „nazwano 30 · w tym gotowe
    obrazy: 2" znaczy „dwa z tych trzydziestu to obrazy po integracji". Człon zostaje osobny, bo to
    jedyny zapis osi, który sięga rodowodu - i należy do tego samego zdania na KAŻDEJ powierzchni."""
    czlony = [i18n.t(nothing_key if sufiks == "nothing" else f"grid.sel.object_skip_{sufiks}", n=n)
              for sufiks, n in gest.skipped_breakdown if n]
    if gest.stacks:
        czlony.append(i18n.t_plural("grid.sel.object_stacks", gest.stacks))
    return "".join(czlony)


def _zlacz_recepty(czlony):
    """Człony recepty w jedno zdanie własnego nośnika paska (FH-2). Czysta funkcja.

    KOLEJNOŚĆ CZŁONÓW JEST KOLEJNOŚCIĄ W CZASIE, nie ważnością: najpierw „odsłoni je …", potem
    „potem przywrócisz: …" - drugi gest bywa wykonalny dopiero po pierwszym, bo wypchnięcie celu
    z widoku gasi całą kontrolkę „Obiekt" (FC-9). Wołający dokłada człony w tym porządku i to on
    jest kontraktem; ta funkcja tylko odsiewa milczące i skleja.

    Separator ten sam, co w raporcie, bo oba zdania czyta się jednym ruchem oka wzdłuż paska -
    dwa różne rozdzielniki na jednej belce wyglądałyby jak dwa różne rejestry."""
    return " · ".join(x for x in czlony if x)


def _ogon_sciezki(path):
    """Nazwa pliku ze ścieżki Windows albo POSIX - do zdania na pasku, gdzie pełna ścieżka zjadłaby
    powód, po który człowiek patrzy."""
    return str(path or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


# Status wyniku, który znaczy „gest zrobił swoje", per operacja rdzenia - klucz zdania głównego
# i status sukcesu. `finish_inplace` oddaje 'applied', `recover_torn` - 'restored'.
_GESTY_ZAPISU = {
    "finish_inplace": ("grid.inplace.finished", "applied"),
    "recover_torn": ("grid.inplace.restored", "restored"),
}


def _zdanie_gestu_zapisu(op, res):
    """Zdanie wyniku gestu plikowego izolacji: „Dokończono N zapisów · zablokowane M · błędy K -
    plik: powód" (+ przerwanie). Czysta funkcja.

    POWÓD RDZENIA JEDZIE DOSŁOWNIE - jest po polsku i niesie drogę dalej (np. „kontrola danych
    operacji 7 przechodzi - zapis jest poprawny, powrót go nie cofa; dokończ…"); zdanie bez niego
    zostawiałoby człowieka przy „zablokowane 1" bez odpowiedzi „czemu". Pokazujemy PIERWSZY powód
    z nazwą pliku - reszta ma tę samą drogę albo własny wiersz w Porządkach, a pasek jest jeden.
    `res` = wynik pętli wykonawcy (`results` = `writeback.FileResult` per operacja, `cancelled`)."""
    klucz, sukces = _GESTY_ZAPISU[op]
    wyniki = list(res.results)
    msg = i18n.t_plural(klucz, sum(1 for w in wyniki if w.status == sukces))
    zablokowane = [w for w in wyniki if w.status == "blocked"]
    bledy = [w for w in wyniki if w.status not in (sukces, "blocked")]
    if zablokowane:
        msg += i18n.t_plural("grid.inplace.blocked", len(zablokowane))
    if bledy:
        msg += i18n.t_plural("grid.inplace.failed", len(bledy))
    if res.cancelled:
        msg += i18n.t("grid.inplace.cancelled")
    powod = next((w for w in zablokowane + bledy if w.reason), None)
    if powod is not None:
        msg += i18n.t("grid.inplace.detail", file=_ogon_sciezki(powod.path), detail=powod.reason)
    return msg


def _half_away(x):
    """Zaokrąglij do int metodą half-away-from-zero (NIE goły `round()`, który jest half-to-even —
    R2 #5). Używane do przełożenia float-mediany Δ na całkowity offset spinu."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x)) if x else 0


def _dt_delta_hours(date_obs, path):
    """Δ = DATE-OBS − czas z nazwy pliku, w godzinach (float) albo None. Guard `path is None`
    (LEFT JOIN location — `basename(None)` = TypeError, R1 #11). Brak któregoś źródła → None."""
    if path is None:
        return None
    h = naming.header_dt(date_obs)
    fn = naming.filename_dt(os.path.basename(path))
    if h is None or fn is None:
        return None
    return (h - fn).total_seconds() / 3600.0


def _derive(row):
    """sqlite3.Row → dict z polami pochodnymi (_telescope/_object/_dt_delta) do kolumn bazowych."""
    d = {k: row[k] for k in row.keys()}
    d["_telescope"] = queries.telescope_label(row)
    # Ze SŁOWNIKA, nie z surowego wiersza: `object_cell` pyta o `kind`/`path`/`object_source`,
    # a te wchodzą nie z każdego zapytania gridu — `sqlite3.Row` na brakującym kluczu rzuca,
    # `dict.get` oddaje None. Ta sama obrona, co przy `_dt_delta_hours` linijkę niżej.
    #
    # PARA ROZPAKOWANA NA DWA KLUCZE, a `_object` ZOSTAJE STRINGIEM — i to nie jest kosmetyka:
    # tę samą wartość czytają trzej konsumenci (komórka, klucz sortu i wartość grupowania), a dwaj
    # ostatni porównują i sklejają napisy. Krotka w `_object` narysowałaby w komórce `('LMC',
    # 'canon')` i kazała sortowi porównywać pary.
    d["_object"], d["_object_state"] = queries.object_cell(d)
    d["_dt_delta"] = _dt_delta_hours(d.get("date_obs"), d.get("path"))
    # Liczba obrazów POKAZANEJ kopii (0021) jako tekst komórki - klatkę z kilkoma kopiami nadpisuje
    # `_dolacz_kopie` wartościami wszystkich kopii. `.get`, bo nie każde zapytanie gridu ją niesie.
    n = d.get("image_count")
    d["_images"] = "" if n is None else str(n)
    return d


def _dolacz_kopie(base, kopie):
    """Dołóż wierszom gridu fakty ICH OBECNYCH KOPII (0021) - czysta funkcja nad gotowymi danymi
    (`queries.present_copy_facts`), zero SQL; mutuje dicty `base` w miejscu, jak `_derive` buduje je
    dla modelu.

    Dwa klucze, dwóch czytelników:
      * `_copies` - lista kopii (dict wiersza + `_rozne`, pola rozjazdu z `queries.copy_divergence`)
        dla podpowiedzi „×N"; JEDEN właściciel reguły rozjazdu z wierszem Porządków, więc opis pod
        kursorem i liczba na liście mówią o tych samych polach;
      * `_images` - WSZYSTKIE różne liczby obrazów w kolejności kopii („3 | 1"); kopia bez zebranych
        faktów (NULL) nie wnosi wartości, bo „nie wiem" nie jest liczbą. Jedna wspólna wartość zostaje
        jedną liczbą - rozjazd ma być widoczny, zgodność ma nie hałasować.
    Wiersz bez kilku kopii zostaje nietknięty (liczbę jego jedynej kopii ustawił `_derive`)."""
    per_klatka = {}
    for r in kopie:
        per_klatka.setdefault(r["frame_id"], []).append(r)
    for row in base:
        rows = per_klatka.get(row.get("frame_id"))
        if not rows:
            continue
        rozne = queries.copy_divergence(rows)
        row["_copies"] = [{**{k: r[k] for k in r.keys()}, "_rozne": rozne.get(r["location_id"], ())}
                          for r in rows]
        liczby = []
        for r in rows:
            if r["image_count"] is not None and r["image_count"] not in liczby:
                liczby.append(r["image_count"])
        row["_images"] = " | ".join(str(n) for n in liczby)


# Kolumna `location` → keyword nagłówka (0021) - do zdania „FILTER=CLS" w podpowiedzi kopii.
_KOPIA_KEYWORD_KOLUMNA = {kw: kol for kol, kw in COPY_TESTIMONY_KEYWORDS}


def _wartosc_zeznania(v):
    """Wartość pola zeznania kopii do podpowiedzi: brak → „∅" (jak podgląd klingi), liczba
    zmiennoprzecinkowa bez ogona zer (`1.34`, `300`), reszta tekstem."""
    if v is None:
        return "∅"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _dup_tip(row):
    """Człon podpowiedzi ścieżki dla klatki z KILKOMA obecnymi kopiami: liczba kopii, a pod nią każda
    kopia - pełna ścieżka, liczba i role obrazów, pola, w których jej zeznanie odbiega od pozostałych
    (z jej własną wartością). Do 0021 podpowiedź mówiła samo „N obecnych lokalizacji", a baza nie
    wiedziała, czym kopie się różnią - teraz wie, więc mówi.

    Role pokazujemy, gdy którakolwiek jest znana; pojedynczy obraz bez `imageType` i bez `id` (248
    plików archiwum) dostaje samą liczbę - lista „(?)" nie niesie informacji. Kopia bez zebranego
    zeznania mówi to wprost, zamiast milczeć jak kopia zgodna."""
    tip = i18n.t("grid.tip.dup_locs", n=row["n_present"])
    for c in row.get("_copies") or ():
        tip += i18n.t("grid.tip.copy_path", path=c["path"])
        if c["image_count"] is not None:
            tip += i18n.t("grid.tip.copy_images", n=c["image_count"])
            role = json.loads(c["image_roles"]) if c["image_roles"] else []
            if any(r is not None for r in role):
                tip += f" ({', '.join('?' if r is None else str(r) for r in role)})"
        if c["hdr_hash"] is None:
            tip += i18n.t("grid.tip.copy_unread", place=i18n.t("nav.dostawa"),
                          check=i18n.t("pipeline.btn.presence"),
                          mark=i18n.t("pipeline.btn.mark_vanished"))
        elif c["_rozne"]:
            pola = [i18n.t("grid.tip.copy_field_images") if e == queries.COPY_IMAGES
                    else f"{e}={_wartosc_zeznania(c[_KOPIA_KEYWORD_KOLUMNA[e]])}"
                    for e in c["_rozne"]]
            tip += i18n.t("grid.tip.copy_diff", fields=", ".join(pola))
    return tip


def _chwila(iso):
    """Znacznik ISO do zdania na ekranie - do MINUT, bez „T" (wzorzec `_vanished_tip`); `None` → None."""
    return str(iso)[:16].replace("T", " ") if iso else None


def _okno(iso):
    """Brzeg okna stosu do zdania - CO DO SEKUNDY, bo tak stoi w kluczu grupy wersji
    (`queries._grupy_wersji`): zapis do minut potrafiłby pokazać dwie grupy o oknach różnych
    o sekundy pod jednakowym opisem. Jeden format dla belki i dla tooltipu komórki."""
    return str(iso)[:19].replace("T", " ") if iso else "?"


def _etykieta_grupy_wersji(grupa):
    """Nagłówek grupy bliźniaków: obiekt · filtr · ekspozycja · okno - czyli dokładnie klucz, który
    czyni stosy tym samym materiałem (kamery w nim nie ma: okno co do sekundy już ją przypina)."""
    exp = grupa["exptime"]
    return i18n.t("grid.version.group",
                  object=grupa["object_canon"] or i18n.t("grid.version.no_object"),
                  filter=grupa["filter_canon"] or i18n.t("portfolio.no_filter"),
                  exp=f"{exp:g}" if exp is not None else "?",
                  start=_okno(grupa["window_start"]), end=_okno(grupa["window_end"]))


def _adnotuj_wersje(base, grupy):
    """Dołóż wierszom gridu fakty grupy wersji: `_wersja_grupa` (etykieta belki, klucz grupowania
    `_GRUPA_WERSJI`) i `_wersja` (fakty członka dla kolumny „Wersja"). Wiersz spoza grup zostaje
    bez kluczy - grupuje się wtedy do „(brak)", a komórka milczy. Czysta funkcja nad gotowymi
    danymi (`queries.stack_version_groups`), zero SQL; mutuje dicty `base` w miejscu, jak `_derive`
    buduje je dla modelu."""
    fakty = {}
    for g in grupy:
        etykieta = _etykieta_grupy_wersji(g)
        for m in g["members"]:
            fakty[m["frame_id"]] = (etykieta, {**m, "group_kind": g["kind"],
                                               "window_start": g["window_start"],
                                               "window_end": g["window_end"]})
    for row in base:
        f = fakty.get(row.get("frame_id"))
        if f is not None:
            row["_wersja_grupa"], row["_wersja"] = f


class GridTableModel(QAbstractTableModel):
    """Model read-only: kolumny bazowe + dynamiczne kolumny-keywordy. 3 stany komórki keyworda; sort
    numeryczny (po `PivotCell.num`) / tekstowy, MISSING na końcu; grupowanie = nagłówki grup w płaskiej
    liście. Karmiony gotowymi danymi (`set_data`) — zero SQL/plików."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []          # dict-y klatek (z 'cells') PRZEPLATANE markerami grup {'_group':..,'_count':..}
        self._data_rows = []     # same klatki (bez markerów) — źródło do sortu/grupowania
        self._keywords = []
        self._group_by = None
        self._sort_col = 0
        self._sort_desc = False
        self._numeric_kw = set() # keywordy z choć jedną komórką liczbową → MISSING „—" też prawo (P3-7)
        self._preview = {}       # frame_id → {'keyword','old','new'} | {'skipped': reason} (podgląd makra/renamu)
        self._preview_label = i18n.t("grid.preview.macro")   # etykieta efemerycznej kolumny (klinga-zależna, R1 #4)
        self._version_col_on = False   # kolumna „Wersja" - wyłącznie w perspektywie „Wersje stosów"

    def set_preview(self, preview, *, label=None):
        """Podgląd klingi (doktryna §5: „grid = podgląd"): frame_id → zmiana (stara→nowa) albo
        pominięcie z powodem. Dokłada EFEMERYCZNĄ kolumnę (`label`, np. „makro →"/„nazwa →") na końcu;
        `{}`/None ją zdejmuje. `label` rozróżnia klingę (makro vs rename) w tym samym podglądzie (R1 #4);
        `None` → domyślna „makro →" z katalogu (rozwiązywana w wywołaniu, nie w sygnaturze — D-L1)."""
        self.beginResetModel()
        self._preview = dict(preview or {})
        self._preview_label = label if label is not None else i18n.t("grid.preview.macro")
        self.endResetModel()

    def _preview_active(self):
        return bool(self._preview)

    def set_data(self, base_rows, pivot, keywords, group_by=None, version_col=False):
        """base_rows: list[dict] (z `_derive`); pivot: horreum.pivot.Pivot; keywords: list[str].

        `version_col` dokłada kolumnę „Wersja" (fakty `_wersja` z `_adnotuj_wersje`) zaraz po
        kolumnach bazowych (`_version_col`). Kolumna jest własnością perspektywy „Wersje stosów",
        nie wiersza: te same stosy w „Przeglądzie" niosą fakty (grupowanie „Wersja stosu" działa
        wszędzie), ale kolumna pojawia się tylko tam, gdzie wybór wersji jest robotą ekranu."""
        self._version_col_on = bool(version_col)
        cells = {r.frame_id: r.cells for r in pivot.rows}
        for d in base_rows:
            d["cells"] = cells.get(d["frame_id"], {})
        self._data_rows = list(base_rows)
        self._keywords = list(keywords)
        # Kolumna-keyword jest NUMERYCZNA, gdy ma choć jedną komórkę liczbową — wtedy MISSING „—"
        # wyrównujemy w prawo, by nie wisiał po lewej pod słupkiem liczb (wizytator P3-7).
        self._numeric_kw = set()
        for kw in self._keywords:
            for d in self._data_rows:
                c = d["cells"].get(kw, pivot_mod.MISSING)
                if c is not pivot_mod.MISSING and c.num is not None:
                    self._numeric_kw.add(kw)
                    break
        self._group_by = group_by
        self._rebuild()

    # ---- kształt ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return (len(BASE_COLS) + len(self._keywords) + (1 if self._version_col_on else 0)
                + (1 if self._preview_active() else 0))

    def _version_col(self):
        """Indeks kolumny „Wersja" albo None, gdy perspektywa jej nie chce.

        ZARAZ PO KOLUMNACH BAZOWYCH, PRZED KEYWORDAMI - zmierzone zrzutem offscreen na kopii żywej
        bazy: postawiona za sześcioma domyślnymi keywordami lądowała poza prawą krawędzią okna
        1400 px, czyli fakty, po które ta perspektywa istnieje, wymagały przewijania w bok."""
        return len(BASE_COLS) if self._version_col_on else None

    def _kw_off(self):
        """Przesunięcie kolumn-keywordów o kolumnę „Wersja" (0 poza jej perspektywą)."""
        return 1 if self._version_col_on else 0

    def _preview_col(self):
        """Indeks efemerycznej kolumny podglądu makra (ostatnia) albo None, gdy podgląd nieaktywny."""
        if not self._preview_active():
            return None
        return len(BASE_COLS) + self._kw_off() + len(self._keywords)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section == self._preview_col():
                return self._preview_label
            if section == self._version_col():
                return i18n.t("grid.col.version")
            if section < len(BASE_COLS):
                return i18n.t(BASE_COLS[section][0])
            return self._keywords[section - len(BASE_COLS) - self._kw_off()]
        return section + 1

    def _col_key(self, col):
        return BASE_COLS[col][1] if col < len(BASE_COLS) else None

    def _kw_for_col(self, col):
        return None if col < len(BASE_COLS) else self._keywords[col - len(BASE_COLS) - self._kw_off()]

    # ---- komórki ----
    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and isinstance(self._rows[index.row()], dict) and "_group" in self._rows[index.row()]:
            return Qt.ItemIsEnabled  # nagłówek grupy: nieselektowalny
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if "_group" in row:  # marker grupy
            # NAGŁÓWEK ZNA STAN, KTÓRY ZNA KOMÓRKA (FC-3). Bez tego „Grupuj wg: Obiekt" malowało
            # `▸ DARK (14)` białym pogrubieniem — dokładnie tak, jak `▸ CTB1 (901)` — choć komórki
            # pod belką były kursywą i szare: jeden ekran mówił o tych samych klatkach dwie różne
            # rzeczy, a naprawa polityki kolumny (R-S3-4) objęła komórkę i ominęła belkę.
            # Pogrubienie ZOSTAJE (belka jest belką); kursywa i szarość mówią „to nie jest
            # przypisany obiekt". Zmierzone na żywym archiwum: 79 grup, największa 2344 klatki.
            stan = row.get("_group_state")
            if role == Qt.DisplayRole and col == 0:
                return f"▸ {row['_group']}  ({row['_count']})"
            if role == Qt.BackgroundRole:
                return _COLORS["group_bg"]
            if role == Qt.FontRole and col == 0:
                f = QFont(); f.setBold(True); f.setItalic(stan is not None); return f
            if stan is None or col != 0:
                return None
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.ToolTipRole:
                return _group_tip(row, stan)
            return None

        if col == self._preview_col():
            return self._preview_cell(row, role)
        if col == self._version_col():
            return self._version_cell(row, role)
        if col < len(BASE_COLS):
            return self._base_cell(row, self._col_key(col), role)
        return self._kw_cell(row, self._kw_for_col(col), role)

    def _version_cell(self, row, role):
        """Komórka „Wersja": rodzaj członka · chwila integracji · liczba wejść - fakty, po których
        człowiek wybiera wersję do zostawienia. Tooltip niesie ŚWIADKA (dlaczego ten rodzaj) i okno.

        Brak faktu MILCZY zamiast udawać: stosy sprzed modułu XISF 1.1.2 nie mają sygnatury, więc
        nie mają daty integracji - człon po prostu nie staje (data pliku nie jest datą integracji:
        zapis nagłówka przez Horreum ją przestawia). Rodzaj jest zawsze, bo zawsze jest werdyktem
        read-modelu, także „nieustalone"."""
        f = row.get("_wersja")
        if not f:
            return None
        if role == Qt.DisplayRole:
            czlony = [i18n.t(f"grid.version.kind.{f['kind']}")]
            if f.get("timestamp"):
                czlony.append(_chwila(f["timestamp"]))
            if f.get("declared_rows") is not None:
                czlony.append(i18n.t_plural("grid.version.inputs", f["declared_rows"]))
            return " · ".join(czlony)
        if role == Qt.ToolTipRole:
            swiadek = f.get("witness")
            return (i18n.t(f"grid.version.why.{swiadek}" if swiadek else "grid.version.why.none")
                    + i18n.t("grid.version.window", start=_okno(f.get("window_start")),
                             end=_okno(f.get("window_end"))))
        if role == Qt.ForegroundRole and f["kind"] != queries.WERSJA_INNA:
            return _COLORS["missing"]      # bez dowodu wersji - wyciszone, jak brak karty
        return None

    def _preview_cell(self, row, role):
        """Komórka podglądu makra: dotknięty frame → „stara → nowa" (tooltip pełny); pominięty →
        „(pominięto)" z powodem w tooltipie; nietknięty → pusto (doktryna §5)."""
        pv = self._preview.get(row.get("frame_id"))
        if pv is None:
            return None
        if "skipped" in pv:
            if role == Qt.DisplayRole:
                return i18n.t("grid.preview.skipped")
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.ToolTipRole:
                return i18n.t("grid.preview.skipped_tip", reason=pv['skipped'])
            return None
        if role == Qt.DisplayRole:
            if pv.get("op") == "rename":
                return str(pv["new"])          # tylko NOWA nazwa (stara jest w kol. „Ścieżka"; wiz #1)
            old = "∅" if pv.get("old") is None else str(pv["old"])
            return f"{old} → {pv['new']}"
        if role == Qt.ToolTipRole:
            return f"{pv['keyword']}: {pv.get('old')!r} → {pv['new']!r} ({pv['op']})"
        if role == Qt.FontRole:
            f = QFont(); f.setBold(True); return f
        return None

    def _base_cell(self, row, key, role):
        # ZASTĄPIONA bije ZNIKNIĘTĄ, bo to nie są dwa odcienie jednego stanu: klatka bez ani jednej
        # kopii wygląda tak samo w obu, ale w pierwszym przypadku jest robota (znajdź plik), a w
        # drugim nie ma żadnej — treść przejęła następczyni. Kolejność `if`-ów JEST tą regułą.
        #
        # WYCOFANA (D-OW-3/R2) wchodzi POMIĘDZY, i ta sama reguła to dyktuje: „nie ma tu roboty"
        # bije „jest robota", a spośród dwóch stanów bez roboty pierwszeństwo ma ten, który mówi,
        # DOKĄD poszła treść. Pełna hierarchia: zastąpiona > wycofana > zniknięta > duplikat.
        # Bez tego wiersz w perspektywie „Wycofane" byłby pomalowany i opisany jako ZNIKNIĘTY,
        # czyli ekran wołałby o robotę, którą człowiek przed chwilą zamknął.
        #
        # WYCOFANA, A PLIK WRÓCIŁ (G2-7d) to odmiana wycofanej, ale z INNYM zdaniem, nie z innym
        # tłem: tło mówi „werdykt ręki", a to dalej prawda. Różnią się tym, co wiersz ma
        # powiedzieć człowiekowi - „pliku już nie szukamy" jest o tej klatce NIEPRAWDĄ, bo plik
        # leży na dysku. Bez własnego zdania dwa wiersze „Wycofanych" wyglądały identycznie,
        # a „Przywróć" na niewłaściwym cofało werdykt o klatce, której pliku naprawdę nie ma.
        # Predykat to lustro `queries.retired_conflict_frame_ids` na polach, które `base_rows`
        # i tak niesie (`n_present` = liczba OBECNYCH kopii).
        superseded = row.get("superseded_by") is not None
        retired = not superseded and row.get("retired_at") is not None
        retired_back = retired and (row.get("n_present") or 0) > 0
        vanished = (not superseded and not retired and row.get("present") == 0
                    and (row.get("n_present") or 0) == 0)
        dup = (row.get("n_present") or 0) > 1
        if role == Qt.BackgroundRole:
            # Podgląd makra WYGRYWA tło (bieżący fokus): dotknięty/pominięty wiersz widoczny w
            # kolumnach bazowych NIEZALEŻNIE od scrolla poziomego (wizytator #1/#2 — „widać zanim zapiszesz").
            pv = self._preview.get(row.get("frame_id")) if self._preview else None
            if pv is not None:
                return _COLORS["skipped_bg"] if "skipped" in pv else _COLORS["touched_bg"]
            if superseded:
                return _COLORS["superseded_bg"]
            if retired:
                return _COLORS["retired_bg"]
            if vanished:
                return _COLORS["vanished_bg"]
            if dup:
                return _COLORS["dup_bg"]
            return None
        if key == "path":
            path = row.get("path") or ""
            if role == Qt.DisplayRole:
                name = os.path.basename(path) if path else i18n.t("object.no_location")
                # Klatka zastąpiona MÓWI TO WPROST W KOMÓRCE, nie tylko tłem i tooltipem: tło niesie
                # kolor (a użytkownik bywa daltonistą albo ma inny motyw), tooltip wymaga najechania,
                # a ten wiersz ma się tłumaczyć sam — inaczej wygląda jak plik, który zginął.
                if superseded:
                    return i18n.t("grid.cell.superseded", id=row.get("superseded_by"))
                # Wycofana MÓWI TO W KOMÓRCE z tego samego powodu, co zastąpiona: tło niesie kolor
                # (a user bywa daltonistą albo ma inny motyw), tooltip wymaga najechania — a ten
                # wiersz ma się tłumaczyć sam, inaczej wygląda jak plik, którego ktoś jeszcze szuka.
                if retired_back:
                    return i18n.t("grid.cell.retired_back", name=name)
                if retired:
                    return i18n.t("grid.cell.retired", name=name)
                # Prefiks „×N" PRZED nazwą (P2-2): sufiks ginął przy elizji długich ścieżek.
                return f"×{row['n_present']}  {name}" if dup else name
            if role == Qt.ToolTipRole:
                extra = _superseded_tip(row) if superseded else (
                    _retired_back_tip(row) if retired_back else
                    _retired_tip(row) if retired else (
                    _vanished_tip(row) if vanished else (
                        _dup_tip(row) if dup else "")))
                # Historia przeprowadzki DOKLEJA SIĘ do werdyktu (patrz `_former_tip`), a warunek
                # `present == 1` jest warunkiem SENSU zdania, nie ostrożnością: pokazany adres musi
                # być żywy, żeby „wcześniejszy" znaczyło coś innego niż on sam.
                if row.get("present") == 1:
                    extra += _former_tip(row)
                return (path or i18n.t("object.no_location")) + extra
            return None
        if key == "_dt_delta":
            # JEDEN typ: zawsze float godzin (R2 #3). Pełne godziny renderują się „-2", ułamek „-1.97"
            # (`:g`); ŻADNYCH stringów-znaczników (mieszany typ rozbrajałby sort numeryczny R1 #6). Flaga
            # niepełnogodzinności mieszka WYŁĄCZNIE w panelu daty RenameBar, nie w komórce.
            v = row.get("_dt_delta")
            if role == Qt.DisplayRole:
                return "" if v is None else f"{v:g}"           # None → pusta komórka (R1 #7)
            if role == Qt.TextAlignmentRole and v is not None:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if role == Qt.ToolTipRole and v is not None:
                return f"DATE-OBS − czas z nazwy = {v!r} h"     # surowy float (kontrola kwantyzacji)
            return None
        if key == "_object":
            # KOLUMNA MÓWI, CZYM JEST TO, CO POKAZUJE (R-S3-4). Do tej paczki jeden napis niósł
            # DWA różne twierdzenia — „ten obiekt tak się nazywa" i „tyle mówi nagłówek pliku" —
            # więc po geście „Cofnij przypisanie" wiersz dalej pokazywał `NGC7023`, a facet Obiekt
            # na tym samym ekranie był już pusty. Stan liczy JEDEN właściciel (`queries.object_cell`),
            # tutaj zostaje samo malowanie: zeznanie dostaje ten sam zestaw ról, którym grid maluje
            # brak karty keyworda (kursywa + `missing`), bo „to nie jest przypisany obiekt" jest
            # brakiem, a nie ostrzeżeniem. Kanon zostaje nietknięty.
            stan = row.get("_object_state", "canon")
            if role == Qt.DisplayRole:
                return row.get("_object") or ""
            if stan == "canon":
                return None
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.FontRole:
                f = QFont(); f.setItalic(True); return f
            if role == Qt.ToolTipRole:
                return _object_tip(row, stan)
            return None
        if role == Qt.DisplayRole:
            v = row.get(key)
            return "" if v is None else str(v)
        return None

    def _kw_cell(self, row, kw, role):
        cell = row["cells"].get(kw, pivot_mod.MISSING)
        if cell is pivot_mod.MISSING:
            if role == Qt.DisplayRole:
                return _MISSING_TEXT
            if role == Qt.ForegroundRole:
                return _COLORS["missing"]
            if role == Qt.FontRole:
                f = QFont(); f.setItalic(True); return f
            if role == Qt.TextAlignmentRole and kw in self._numeric_kw:
                return int(Qt.AlignRight | Qt.AlignVCenter)   # „—" pod słupkiem liczb (wizytator P3-7)
            if role == Qt.ToolTipRole:
                return "brak karty"
            return None
        if role == Qt.DisplayRole:
            return "" if cell.raw is None else str(cell.raw)
        if role == Qt.TextAlignmentRole and cell.num is not None:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    # ---- sort + grupowanie ----
    def set_group_by(self, group_by):
        self._group_by = group_by
        self._rebuild()

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort_col = column
        self._sort_desc = order == Qt.DescendingOrder
        self._rebuild()

    def _sort_key(self, row):
        col = self._sort_col
        if col == self._version_col():
            # Po CHWILI INTEGRACJI (ISO sortuje się chronologicznie), potem po liczbie wejść;
            # wiersz bez faktów - na koniec, jak MISSING (kierunek sortu go nie przenosi).
            f = row.get("_wersja")
            if not f:
                return (2, "")
            return (0, f.get("timestamp") or "", f.get("declared_rows") or 0)
        if col >= len(BASE_COLS) + self._kw_off() + len(self._keywords):   # podgląd makra / indeks
            return (0, "")                                   # spoza bieżących kolumn → sort neutralny
        kw = self._kw_for_col(col)
        if kw is None:
            key = self._col_key(col)
            if key == "_dt_delta":                            # gałąź numeryczna (R1 #6), None na koniec
                v = row.get("_dt_delta")
                return (2, 0.0) if v is None else (0, float(v))
            v = row.get(key)
            return (0, "" if v is None else str(v).lower())
        cell = row["cells"].get(kw, pivot_mod.MISSING)
        if cell is pivot_mod.MISSING:
            return (2, "")  # MISSING zawsze na końcu (niezależnie od kierunku)
        if cell.num is not None:
            return (0, cell.num)
        return (1, "" if cell.raw is None else str(cell.raw).lower())

    def _group_state(self, bucket):
        """Stan belki grupy = stan JEJ WIERSZY, i tylko gdy mówią jednym głosem (FC-3).

        Grupowanie po czymkolwiek innym niż kolumna „Obiekt" stanu nie ma — belka „▸ fits (900)"
        nie jest o obiekcie i wyciszenie jej byłoby zdaniem o niczym.

        Niejednorodny kubełek dostaje `None` zamiast stanu WIĘKSZOŚCI: belka mówiłaby wtedy o stanie,
        którego część jej wierszy nie ma. Klucz grupy to TEKST komórki, a znaczniki z FC-8 (`↺`,
        `⟨…⟩`, `?`) rozdzielają stany niekanoniczne między sobą — ale NIE rozdzielają `canon` od
        `kind`, bo żaden z tych dwóch znacznika nie niesie (bramka pakietu 0815, zarzut 4). Wystarczy
        flat, któremu kamera wpisała w `OBJECT` dokładnie tę nazwę, którą oś zna jako kanon lightów,
        i jeden kubełek zbierze oba stany. Belka jest wtedy neutralna, a komórki pod nią i tak mówią
        każda za siebie."""
        if self._group_by != "_object":
            return None
        stany = {r.get("_object_state", "canon") for r in bucket}
        stan = stany.pop() if len(stany) == 1 else None
        return stan if stan in _OBJECT_STATE_TIPS else None

    def _group_tip_mode(self, bucket, stan):
        """Czy belka MOŻE zacytować wiersz wzorcowy — `exact` / `base` / `None` (opis: `_group_tip`).

        Od danych WIERSZA zależą `cleared` (pamięć nagrobka + zeznanie nagłówka) i `hint` (układ
        ścieżki: drzewo `STACKS` albo WBPP); pozostałe stany mają zdanie stałe per stan, więc
        wiersz wzorcowy jest dla nich obojętny."""
        if stan is None:
            return None
        if stan == "hint":
            # Zdanie podpowiedzi zależy od UKŁADU ścieżki (`_object_tip`): kubełek mieszający drzewo
            # `STACKS` z układem WBPP pod jednym tekstem komórki nie ma jednego zdania - belka milczy.
            drzewa = {queries.hint_from_stacks_tree(r.get("path")) for r in bucket}
            return "exact" if len(drzewa) == 1 else None
        if stan != "cleared":
            return "exact"
        fakty = {(bool(r.get("object_cleared_canon")), bool(r.get("object_raw"))) for r in bucket}
        if len(fakty) == 1:
            return "exact"
        return "base" if all(pamiec for pamiec, _ in fakty) else None

    def _group_value(self, row):
        if self._group_by in (None, ""):
            return None
        v = row.get(self._group_by)
        if v in (None, ""):
            return "(brak)"
        if self._group_by == "_dt_delta":
            return f"{v:g}"                                    # etykieta grupy spójna z komórką („-2")
        return str(v)

    def _rebuild(self):
        self.beginResetModel()
        # MISSING-na-końcu: rozdziel klucz sortu (0/1 present, 2 missing) — reverse tylko w obrębie present.
        rows = sorted(self._data_rows, key=self._sort_key,
                      reverse=self._sort_desc)
        # reverse psuje „MISSING na końcu" — przenieś markery MISSING zawsze na koniec:
        if self._sort_desc:
            present = [r for r in rows if self._sort_key(r)[0] != 2]
            missing = [r for r in self._data_rows if self._sort_key(r)[0] == 2]
            rows = present + missing
        if self._group_by in (None, ""):
            self._rows = list(rows)
        else:
            if self._group_by == "_dt_delta":                 # porządek nagłówków grup NUMERYCZNY (R2 #4):
                rows = sorted(rows, key=lambda r: (           # inaczej „-1", „-12", „-2"; None-grupa na koniec
                    r.get("_dt_delta") is None, r.get("_dt_delta") or 0.0))
            else:
                rows = sorted(rows, key=lambda r: (self._group_value(r) or "").lower())
            self._rows = []
            cur = object()
            bucket = []
            def flush():
                if bucket:
                    stan = self._group_state(bucket)
                    self._rows.append({"_group": cur, "_count": len(bucket),
                                       "_group_state": stan, "_group_row": bucket[0],
                                       "_group_tip": self._group_tip_mode(bucket, stan)})
                    self._rows.extend(bucket)
            for r in rows:
                g = self._group_value(r)
                if g != cur:
                    flush(); cur = g; bucket = []
                bucket.append(r)
            flush()
        self.endResetModel()


class FilterPanel(QWidget):
    """Minimalny builder drzewa filtra: wiersze [keyword][operator][wartość][×] + selektor AND/OR
    + checkbox „Odwróć" (F1 redesignu: owija drzewo w NOT — `uniwersum − wynik`).
    Emituje `filterApplied(dict|None)` — GUI v1 buduje jednopoziomową grupę (rdzeń wspiera głębiej)."""

    filterApplied = Signal(object)

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        self._rows = []
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.combo_op = QComboBox(); self.combo_op.addItems(["AND", "OR"])
        top.addWidget(QLabel(i18n.t("grid.filter.join"))); top.addWidget(self.combo_op)
        btn_add = QPushButton(i18n.t("grid.filter.add_cond")); btn_add.clicked.connect(self.add_row); top.addWidget(btn_add)
        self.chk_invert = QCheckBox(i18n.t("grid.filter.invert"))
        top.addWidget(self.chk_invert)
        btn_apply = QPushButton(i18n.t("grid.filter.apply")); btn_apply.clicked.connect(self._apply); top.addWidget(btn_apply)
        btn_clear = QPushButton(i18n.t("grid.filter.clear")); btn_clear.clicked.connect(self._clear); top.addWidget(btn_clear)
        top.addStretch(1)
        outer.addLayout(top)
        self._rows_box = QVBoxLayout(); outer.addLayout(self._rows_box)
        self.add_row()   # jeden pusty wiersz domyślnie — pierwszy filtr bez „+ warunek" (P3-4)

    def add_row(self):
        rw = QHBoxLayout()
        kw = QComboBox(); kw.setEditable(True); kw.addItems(self._keywords)
        op = QComboBox()
        for label, _ in OPERATORS:
            op.addItem(i18n.t(label))
        val = QLineEdit()
        val.returnPressed.connect(self._apply)   # Enter w polu wartości = Zastosuj (P3-4)
        rm = QPushButton("×"); rm.setFixedWidth(28)
        rw.addWidget(kw, 2); rw.addWidget(op, 1); rw.addWidget(val, 2); rw.addWidget(rm)
        holder = QWidget(); holder.setLayout(rw)
        self._rows_box.addWidget(holder)
        entry = {"kw": kw, "op": op, "val": val, "holder": holder}
        rm.clicked.connect(lambda: self._remove(entry))
        self._rows.append(entry)

    def set_keywords(self, keywords):
        """Odśwież listę keywordów we WSZYSTKICH combo, także w wierszach już zbudowanych — inaczej wiersz
        domyślny (dodany w `__init__`, zanim `_load_facets` pozna keywordy) zostaje z pustą listą i klik nie
        rozwija pola do wyboru. Editable → zachowaj wpisany tekst. Bliźniacze do `MacroBar.set_keywords`."""
        self._keywords = list(keywords)
        for e in self._rows:
            combo = e["kw"]
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear(); combo.addItems(self._keywords); combo.setCurrentText(cur)
            combo.blockSignals(False)

    def _remove(self, entry):
        entry["holder"].setParent(None)
        self._rows.remove(entry)

    def _clear(self):
        for e in list(self._rows):
            self._remove(e)
        self.chk_invert.setChecked(False)   # „Wyczyść" = pełny reset, także negacji
        self.add_row()   # zostaw pusty wiersz gotowy do następnego filtra
        self.filterApplied.emit(None)

    def set_tree(self, tree):
        """Odtwarza wiersze panelu z drzewa JEDNOPOZIOMOWEGO — synchronizuje panel z filtrem perspektywy
        (P3-3: bez tego preset ustawia filtr, a panel jest pusty → kolejny „Zastosuj" po cichu go nadpisuje).
        Korzeń NOT (F1, R#1 BLOKUJĄCE): zaznacz „Odwróć" i odtwórz DZIECKO płaską logiką — bez tego
        perspektywa z NOT wczytuje się w pusty panel i pierwszy „Zastosuj" po cichu kasuje negację.
        Głębsze zagnieżdżenie (grupa w grupie) niereprezentowalne w płaskim panelu → pusty wiersz. NIE emituje
        `filterApplied` (wołający już odświeża)."""
        for e in list(self._rows):
            self._remove(e)
        invert = (isinstance(tree, dict) and "operator" not in tree
                  and str(tree.get("op", "")).upper() == "NOT")
        self.chk_invert.setChecked(invert)
        if invert:
            children = tree.get("conditions", [])
            tree = children[0] if len(children) == 1 else None   # ≠1 dziecko: defensywnie pusty panel
        if tree is None:
            self.add_row()
            return
        if "operator" in tree:                     # pojedynczy warunek
            op_group, conds = "AND", [tree]
        else:
            op_group = str(tree.get("op", "AND")).upper()
            conds = tree.get("conditions", [])
        self.combo_op.setCurrentText(op_group if op_group in ("AND", "OR") else "AND")
        if not conds or not all("operator" in c for c in conds):
            self.add_row()                         # niereprezentowalne → nie udawaj, że oddajemy filtr
            return
        for c in conds:
            self.add_row()
            e = self._rows[-1]
            e["kw"].setCurrentText(c["keyword"])
            for i, (_, opc) in enumerate(OPERATORS):
                if opc == c["operator"]:
                    e["op"].setCurrentIndex(i)
                    break
            if "value" in c:
                e["val"].setText(str(c["value"]))

    def build_tree(self):
        conds = []
        for e in self._rows:
            kw = e["kw"].currentText().strip()
            if not kw:
                continue
            op = OPERATORS[e["op"].currentIndex()][1]
            if op in _NO_VALUE:
                conds.append({"keyword": kw, "operator": op})
                continue
            val = e["val"].text()
            if val.strip() == "":
                continue   # wiersz niedokończony (edytowalne combo auto-wybiera keyword) — NIE wstrzykuj `eq ''`
            conds.append({"keyword": kw, "operator": op, "value": val})
        if not conds:
            return None   # pusty panel = uniwersum, BEZ owijania w NOT (checkbox bez warunków nie kłamie ∅-em)
        tree = {"op": self.combo_op.currentText(), "conditions": conds}
        if self.chk_invert.isChecked():
            return {"op": "NOT", "conditions": [tree]}
        return tree

    def _apply(self):
        self.filterApplied.emit(self.build_tree())


class FieldsPanel(QWidget):
    """Panel Pól: checkbox kolumny-keyworda + pokrycie inline (ile klatek ma daną kartę). Emituje
    `columnsChanged(list[str])`. Integruje wybór kolumn i pokrycie w JEDNYM panelu (bez modalu Pokrycie).

    Pokrycie idzie w PRAWĄ kolumnę (`rows.TwoPartDelegate`): przy 1200 px splitter 1:4 skąpi lewej
    stronie i liczniki doklejone do keyworda były ucięte (wiz F3 #4). Minimum szerokości jak listwa
    facetów — obie części lewej kolumny mają ten sam próg czytelności."""

    columnsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(i18n.t("grid.fields.title"))
        outer.addWidget(self.title)
        self.list = QListWidget()
        self.list.setItemDelegate(TwoPartDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemChanged.connect(self._on_changed)
        outer.addWidget(self.list)
        self.setMinimumWidth(_FIELDS_MIN_W)
        self._loading = False

    def load(self, facets, checked):
        """facets: wiersze (keyword, n). checked: set[str] zaznaczonych."""
        self._loading = True
        try:
            self.list.clear()
            for f in facets:
                kw, n = f["keyword"], f["n"]
                it = QListWidgetItem(kw)
                it.setData(rows.SECONDARY, f"({n})")     # pokrycie w prawej kolumnie (wiz F3 #4)
                it.setData(Qt.UserRole, kw)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if kw in checked else Qt.Unchecked)
                self.list.addItem(it)
        finally:
            self._loading = False

    def set_stan(self, stan):
        """Stan pokrycia w TYTULE panelu: None = aktualne, "liczy" = liczone w tle, "blad" = nie
        policzone. Lista pod tytułem zostaje z poprzedniego wyniku - czyszczenie jej na czas
        liczenia pokazywałoby pustkę, która wygląda jak archiwum bez pól."""
        if stan == "liczy":
            self.title.setText(i18n.t("grid.fields.title_counting"))
        elif stan == "blad":
            self.title.setText(i18n.t("grid.fields.title_failed"))
        else:
            self.title.setText(i18n.t("grid.fields.title"))

    def checked_keywords(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _on_changed(self, _item):
        if not self._loading:
            self.columnsChanged.emit(self.checked_keywords())


class MacroBar(QWidget):
    """Panel makra (F3: strona `_PanelStack`, otwierana z paska zbioru „Popraw nagłówki…") — sekcje
    Oblicz/Przypisz. Emituje `preview(dict)` (policz i pokaż w gridzie, BEZ zapisu), `stage(dict)`
    (do szuflady), `cleared()`. Makro operuje na tym, co widać w gridzie (frame_ids wołającego)."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)
        # Oblicz (opcjonalny krok pośredni: nazwa = wyrażenie)
        comp = QHBoxLayout()
        comp.addWidget(QLabel(i18n.t("grid.macro.compute")))
        self.comp_name = QLineEdit(); self.comp_name.setPlaceholderText(i18n.t("grid.macro.name_ph"))
        self.comp_name.setFixedWidth(120)
        self.comp_expr = QLineEdit(); self.comp_expr.setPlaceholderText(i18n.t("grid.macro.expr_ph"))
        comp.addWidget(self.comp_name); comp.addWidget(QLabel("=")); comp.addWidget(self.comp_expr, 1)
        b.addLayout(comp)
        # Przypisz (keyword op wartość)
        asg = QHBoxLayout()
        asg.addWidget(QLabel(i18n.t("grid.macro.assign")))
        self.asg_kw = QComboBox(); self.asg_kw.setEditable(True); self.asg_kw.addItems(keywords)
        self.asg_kw.setFixedWidth(160)
        self.asg_op = QComboBox(); self.asg_op.addItems(["set", "add"])
        self.asg_expr = QLineEdit(); self.asg_expr.setPlaceholderText(i18n.t("grid.macro.assign_ph"))
        asg.addWidget(self.asg_kw); asg.addWidget(self.asg_op); asg.addWidget(QLabel("=")); asg.addWidget(self.asg_expr, 1)
        b.addLayout(asg)
        # akcje
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    def set_actions_enabled(self, on):
        """Wyłącz Podgląd/Do stagingu, gdy nie ma widocznych klatek (szczery disabled zamiast cichego
        no-op — wizytator #4). `Wyczyść podgląd` zostaje aktywny (zdejmuje ewentualny stary podgląd)."""
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_keywords(self, keywords):
        self._keywords = keywords
        cur = self.asg_kw.currentText()
        self.asg_kw.blockSignals(True)
        self.asg_kw.clear(); self.asg_kw.addItems(keywords); self.asg_kw.setCurrentText(cur)
        self.asg_kw.blockSignals(False)

    def macro_def(self):
        """Zbierz definicję makra z pól (None, gdy brak keyworda/wartości przypisania)."""
        kw = self.asg_kw.currentText().strip()
        expr = self.asg_expr.text().strip()
        if not kw or not expr:
            return None
        md = {"assign": {"keyword": kw, "op": self.asg_op.currentText(), "expr": expr}}
        cname, cexpr = self.comp_name.text().strip(), self.comp_expr.text().strip()
        if cname and cexpr:
            md["computes"] = [{"name": cname, "expr": cexpr}]
        return md

    def _emit_preview(self):
        md = self.macro_def()
        if md is not None:
            self.preview.emit(md)

    def _emit_stage(self):
        md = self.macro_def()
        if md is not None:
            self.stage.emit(md)


class _TokenRow(QWidget):
    """Jeden rząd edytora wzoru: typ tokenu + argument (folder→poziom, orig→regex) + ↑↓⊖. `spec()`
    zwraca goły string (token bez argumentu) LUB dict `{"t":…}` (parametryczny) — forma DANE `naming`."""

    changed = Signal()
    removeRequested = Signal(object)
    moveRequested = Signal(object, int)                # (self, -1 w górę / +1 w dół)

    # (klucz-etykiety, tid). Etykieta → i18n.t w budowie combo; tid to DANE `naming`.
    _TOKENS = (("grid.token.datetime", "datetime"), ("grid.token.object", "object"),
               ("grid.token.kind", "kind"), ("grid.token.filter", "filter"),
               ("grid.token.exp", "exp"), ("grid.token.disc", "disc"),
               ("grid.token.folder", "folder"), ("grid.token.orig", "orig"))

    def __init__(self, spec="kind", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(); self.combo.setFixedWidth(170)     # stała kolumna typu (wiz #2 — bez ragged)
        for lbl, tid in self._TOKENS:
            self.combo.addItem(i18n.t(lbl), tid)
        lay.addWidget(self.combo)
        self.level = QSpinBox(); self.level.setRange(1, 8); self.level.setPrefix(i18n.t("grid.token.level_prefix"))
        lay.addWidget(self.level)
        self.regex = QLineEdit(); self.regex.setPlaceholderText(i18n.t("grid.token.regex_ph"))
        self.regex.setMinimumWidth(160)
        lay.addWidget(self.regex)
        lay.addStretch(1)                                           # wypełniacz → przyciski zawsze przy prawej
        btn_up = QPushButton("↑"); btn_dn = QPushButton("↓"); btn_rm = QPushButton("⊖")
        for b in (btn_up, btn_dn, btn_rm):
            b.setFixedWidth(28); lay.addWidget(b)
        btn_up.clicked.connect(lambda: self.moveRequested.emit(self, -1))
        btn_dn.clicked.connect(lambda: self.moveRequested.emit(self, +1))
        btn_rm.clicked.connect(lambda: self.removeRequested.emit(self))
        self.combo.currentIndexChanged.connect(self._sync_args)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.level.valueChanged.connect(lambda *_: self.changed.emit())
        self.regex.textChanged.connect(lambda *_: self.changed.emit())
        self.set_spec(spec)

    def _sync_args(self):
        tok = self.combo.currentData()
        self.level.setVisible(tok == "folder")
        self.regex.setVisible(tok == "orig")

    def set_spec(self, spec):
        tok = spec.get("t") if isinstance(spec, dict) else spec
        args = spec if isinstance(spec, dict) else {}
        i = self.combo.findData(tok)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        if tok == "folder":
            self.level.setValue(int(args.get("n", 1)))
        elif tok == "orig":
            self.regex.setText(str(args.get("re", "")))
        self._sync_args()

    def spec(self):
        tok = self.combo.currentData()
        if tok == "folder":
            return {"t": "folder", "n": self.level.value()}
        if tok == "orig":
            return {"t": "orig", "re": self.regex.text()}
        return tok


class _TemplateEditor(QWidget):
    """Edytor wzoru nazwy (§5): lista `_TokenRow` + [+ Token][Przywróć domyślny]. `template()` = lista
    specyfikacji (DANE dla `naming.run_rename`). Domyślny preset = `DEFAULT_TEMPLATE` (Z `disc` — D-I4
    bezpieczny domyśl; czyste nazwy = user RĘCZNIE usuwa rząd `disc`, kolizja → warning+skip)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(i18n.t("grid.tmpl.title")); lbl.setProperty("role", "secondary")
        head.addWidget(lbl); head.addStretch(1)
        btn_add = QPushButton(i18n.t("grid.tmpl.add_token")); btn_def = QPushButton(i18n.t("grid.tmpl.restore"))
        head.addWidget(btn_add); head.addWidget(btn_def)
        outer.addLayout(head)
        self._empty_hint = QLabel(i18n.t("grid.tmpl.empty_hint")); self._empty_hint.hide()
        self._empty_hint.setProperty("role", "secondary")
        outer.addWidget(self._empty_hint)
        self._host = QWidget()
        self._rows_lay = QVBoxLayout(self._host); self._rows_lay.setContentsMargins(0, 0, 0, 0)
        # Sufit wysokości + scroll (wiz #1): rozbudowany wzór NIE zjada gridu — nadwyżka scrolluje.
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True); self._scroll.setWidget(self._host)
        self._scroll.setFrameShape(QFrame.NoFrame); self._scroll.setMaximumHeight(200)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)
        btn_add.clicked.connect(lambda: (self._add_row("kind"), self.changed.emit()))
        btn_def.clicked.connect(lambda: self._restore_default())
        self.set_template(naming.DEFAULT_TEMPLATE)

    def _rows(self):
        return [self._rows_lay.itemAt(i).widget() for i in range(self._rows_lay.count())]

    def _refresh_empty(self):
        self._empty_hint.setVisible(len(self._rows()) == 0)

    def _add_row(self, spec):
        row = _TokenRow(spec)
        row.removeRequested.connect(self._remove)
        row.moveRequested.connect(self._move)
        row.changed.connect(self.changed)
        self._rows_lay.addWidget(row)
        self._refresh_empty()
        return row

    def _remove(self, row):
        self._rows_lay.removeWidget(row); row.deleteLater()
        self._refresh_empty(); self.changed.emit()

    def _move(self, row, direction):
        i = self._rows_lay.indexOf(row); j = i + direction
        if 0 <= j < self._rows_lay.count():
            self._rows_lay.removeWidget(row); self._rows_lay.insertWidget(j, row); self.changed.emit()

    def _restore_default(self):
        self.set_template(naming.DEFAULT_TEMPLATE); self.changed.emit()

    def set_template(self, specs):
        while self._rows_lay.count():
            w = self._rows_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for spec in specs:
            self._add_row(spec)
        self._refresh_empty()

    def template(self):
        return [row.spec() for row in self._rows()]


class RenameBar(QWidget):
    """Panel „Nazwy z faktów" (F3: strona `_PanelStack`, otwierana z paska zbioru „Uporządkuj nazwy
    plików…"; BLIŹNIAK strukturalny `MacroBar`). Trzy strefy: (1) polityka wsadu — Źródło/Offset/
    Fallback + żywa etykieta celu; (2) panel inspekcji daty (G1, G4 — pełne timestampy + Δ + align do
    drugiego źródła); (3) akcje. Emituje `preview(policy)`/`stage(policy)`/`cleared()`/`sourceChanged()`.
    `policy` = {source, offset_hours, fallback} — jeden silnik `naming.run_rename`. Panel daty KARMIONY
    z zewnątrz (`set_echo`) — FramesView zna zaznaczenie i wie, czy panel jest otwarty."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()
    sourceChanged = Signal()     # zmiana źródła → przelicz etykietę/znak align (R2 #2)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._median = None       # ostatnia mediana Δ wsadu (do przycisku „Wyrównaj")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)

        # (1) polityka wsadu
        pol = QHBoxLayout()
        pol.addWidget(QLabel(i18n.t("grid.rename.source")))
        self.src = QComboBox()
        self.src.addItem("DATE-OBS", "date_obs")          # D2: default DATE-OBS (kw FITS — bez tłumaczenia)
        self.src.addItem(i18n.t("grid.rename.src_filename"), "filename")
        self.src.currentIndexChanged.connect(lambda *_: self.sourceChanged.emit())
        pol.addWidget(self.src)
        pol.addWidget(QLabel(i18n.t("grid.rename.offset")))
        self.offset = QSpinBox(); self.offset.setRange(-24, 24); self.offset.setValue(0)
        self.offset.setSuffix(" h")                       # BEZ założenia strefy (§2): 0 default
        pol.addWidget(self.offset)
        self.fallback = QCheckBox(i18n.t("grid.rename.fallback")); self.fallback.setChecked(True)  # D1
        pol.addWidget(self.fallback)
        pol.addStretch(1)
        self.target_lbl = QLabel("")                      # żywa etykieta celu (R1 #18)
        self.target_lbl.setProperty("role", "secondary")  # tekst drugorzędny z motywu (F6 §7)
        pol.addWidget(self.target_lbl)
        b.addLayout(pol)

        # (2) panel inspekcji daty (G1 — zarezerwowana powierzchnia; G4 — pełne timestampy)
        grid = QGridLayout(); grid.setContentsMargins(0, 2, 0, 2)
        self.lbl_primary = QLabel("—"); self.lbl_secondary = QLabel("—")
        self.lbl_delta = QLabel(""); self.lbl_flag = QLabel("")
        self.lbl_flag.setProperty("role", "error")       # kolor z motywu (P-C), nie sztywne #b00
        self.btn_align = QPushButton(i18n.t("grid.rename.align")); self.btn_align.setEnabled(False)
        self.btn_align.clicked.connect(self._align)
        grid.addWidget(self.lbl_primary, 0, 0); grid.addWidget(self.lbl_secondary, 0, 1)
        grid.addWidget(self.lbl_delta, 1, 0); grid.addWidget(self.lbl_flag, 1, 1)
        b.addLayout(grid)
        align_row = QHBoxLayout()                        # „Wyrównaj" = szerokość treści (pomocnik NIE
        align_row.addWidget(self.btn_align); align_row.addStretch(1)   # dominuje akcji głównych — wiz #5)
        b.addLayout(align_row)

        # (3) edytor wzoru nazwy (v2 §5 — folder/orig/per-token; DANE dla `run_rename`)
        b.addSpacing(10)                                 # oddech od panelu daty (wiz #4)
        self.template_editor = _TemplateEditor()
        b.addWidget(self.template_editor)

        # (4) akcje (bliźniaczo do makra)
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    # ---- stan / API ----
    def source(self):
        return self.src.currentData()

    def policy(self):
        return {"source": self.src.currentData(), "offset_hours": self.offset.value(),
                "fallback": self.fallback.isChecked(), "template": self.template_editor.template()}

    def set_actions_enabled(self, on):
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_target_label(self, text):
        self.target_lbl.setText(text)

    def set_echo(self, primary, secondary, delta, flag, *, flag_role="warn", median=None, spread=None):
        """Wypełnij panel daty (FramesView liczy z zaznaczenia/widocznych). `median` (Δ w godzinach, float
        albo None) uzbraja „Wyrównaj": znak ZALEŻNY od źródła (R2 #2), wartość przez half-away (R2 #5),
        surowa mediana + rozrzut w tooltipie (R1 #16).

        `flag_role` NAZYWA WAGĘ komunikatu (wizytacja P-C #7): „Δ niepełnogodzinna!" to ostrzeżenie
        (`warn`), „brak źródła czasu" to stan informacyjny (`secondary`). Do P-C oba nosiły tę samą
        czerwień co „Etap padł" Dostawy — akcent semantyczny, który krzyczy o wszystkim, nie mówi
        o niczym. Czerwień zostaje wyłącznie dla awarii."""
        self.lbl_primary.setText(primary); self.lbl_secondary.setText(secondary)
        self.lbl_delta.setText(delta); self.lbl_flag.setText(flag)
        _set_role(self.lbl_flag, flag_role)
        self._median = median
        if median is None:
            self.btn_align.setEnabled(False)
            self.btn_align.setText(i18n.t("grid.rename.align"))
            self.btn_align.setToolTip("")
            return
        self.btn_align.setEnabled(True)
        off = self._offset_from_median()
        other = i18n.t("grid.rename.other_fname") if self.source() == "date_obs" else "DATE-OBS"
        self.btn_align.setText(i18n.t("grid.rename.align_to", other=other, off=f"{off:+d}"))
        tip = i18n.t("grid.rename.align_tip", median=repr(median))
        if spread is not None:
            tip += i18n.t("grid.rename.align_tip_spread", spread=f"{spread:g}")
        self.btn_align.setToolTip(tip)

    def _offset_from_median(self):
        """Offset całkowity z mediany Δ (=hdr−nazwa). source=date_obs → −Δ (przesuń nagłówek do nazwy);
        source=filename → +Δ (przesuń nazwę do nagłówka). `resolve_dt` = base+offset (R2 #2)."""
        signed = -self._median if self.source() == "date_obs" else self._median
        return _half_away(signed)

    def _align(self):
        if self._median is not None:
            self.offset.setValue(self._offset_from_median())

    def _emit_preview(self):
        self.preview.emit(self.policy())

    def _emit_stage(self):
        self.stage.emit(self.policy())


class ElidedLabel(QLabel):
    """QLabel z elizją w prawo: pełny tekst przez `set_full_text` (ląduje też w tooltipie), render
    przycinany do bieżącej szerokości — długi opis kryteriów nie rozpycha okna (F3, §4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def set_full_text(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._update_elide()

    def full_text(self):
        """Tekst PRZED elizją — wołający pyta o treść, nie o to, co się akurat zmieściło
        (`text()` zwraca wersję przyciętą i „czy jest co pokazać" odpowiedziałby na niej fałszem
        przy wąskim panelu)."""
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 4)))


# Sufit listy panelu rodowodu: wejść stosu bywa 190, więc lista MUSI mieć próg, za którym oddaje
# pion gridowi. Oś kalibracji ma zawsze dwa wiersze i sufit sobie zaniża do treści (`set_calibration`),
# dlatego droga stosu przywraca tę wartość WPROST — panel przełącza się w obie strony.
_LINEAGE_LIST_MAX_H = 160


class LineageBar(QWidget):
    """Panel „Rodowód" (I-2d, P-I): CO WESZŁO W TEN OBRAZ — strona `_PanelStack` otwierana z paska
    zbioru, gdy zaznaczono DOKŁADNIE JEDEN gotowy stos (`kind='master_light'`).

    Panel jest jedynym miejscem, w którym widać RÓŻNICĘ MIĘDZY FAKTEM A KANDYDATEM. Wejście
    z `history` plik zeznał o sobie sam; wejście z `window` zostało WYLICZONE z okna czasu i czeka
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
        info.append(i18n.t("grid.lin.flag.declared", n=head["declared_rows"]))
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


class SelectionBar(QFrame):
    """Pasek ZBIORU (F3, PLAN_ux_redesign §4): licznik + kryteria słowami + akcje na zbiorze
    [Wydaj na stół…][Popraw nagłówki…][Uporządkuj nazwy plików…][★ Zapisz widok]. Przyciski paneli
    CHECKABLE — który panel otwarty widać bez klikania. Głupi widżet: FramesView łączy kliki i karmi
    etykiety (NARROW). Przyciski-panele ZAWSZE aktywne (gating checkable = pułapka
    disabled-but-checked-open, F3R#2); pusty zbiór gasi tylko „Wydaj na stół…"."""

    _PROJ_TIP = "grid.sel.proj_tip"   # KLUCZ (rozwiązywany i18n.t w use-site — nie zamrożony PL)

    # Skrót „ostatnio użyte" (R-S2b-12) niesie KOMPLET pól klingi, nie sam kanon: `user_assign_object`
    # INSERTuje obiekt, gdy kanon nowy, więc `catalog`/`kind` muszą dojechać razem z nazwą.
    objectRecentPicked = Signal(str, object, object)
    _RECENT_MAX = 5                   # sufit listy skrótu (dług mówi „3-5"); tyle samo pyta read-model

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.count_label = QLabel("")
        f = QFont(); f.setBold(True); self.count_label.setFont(f)
        self.criteria_label = ElidedLabel()
        self.criteria_label.setProperty("role", "secondary")   # kryteria zbioru czytelne na dark (F6 §7)
        self.btn_proj = QPushButton(i18n.t("grid.sel.project"))
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP))
        # ZŁOTA AKCJA Zbiorów (wiz F3 #3, dług zamknięty w P-C): jedna akcja na miejsce niesie wagę
        # wizualną — wzorzec „Przyjmij nowe" (`pipeline._build_ui`). Waga = BOLD, nie kolor: złoto
        # motywu ma w jasnej skórce 2,7:1 i jako tekst nie dochodzi do progu czytelności (wiz T5 N5).
        # Bez podnoszenia wysokości — pasek zbioru trzyma pięć przycisków w jednym rzędzie.
        _f = self.btn_proj.font(); _f.setBold(True); self.btn_proj.setFont(_f)
        # „× Wyczyść zbiór" (wiz F4 #3): jednoklikowe zdjęcie facetów + filtra — bez niego jedyną
        # drogą było od-cyklowanie każdej wartości (preset „Przegląd" = no-op, gdy już wybrany).
        self.btn_clear = QPushButton(i18n.t("grid.sel.clear_set"))
        self.btn_clear.setToolTip(i18n.t("grid.sel.clear_tip"))
        self.btn_macro = QPushButton(i18n.t("grid.sel.fix_headers")); self.btn_macro.setCheckable(True)
        self.btn_rename = QPushButton(i18n.t("grid.sel.tidy_names")); self.btn_rename.setCheckable(True)
        # Panel rodowodu (I-2d) — trzeci panel stacku. ZAWSZE aktywny, jak pozostałe przyciski-panele
        # (F3R#2: gating checkable = pułapka disabled-but-checked-open); niewłaściwe zaznaczenie
        # tłumaczy sam panel zdaniem, a nie wygaszony przycisk, który nie mówi DLACZEGO.
        self.btn_lineage = QPushButton(i18n.t("grid.sel.lineage")); self.btn_lineage.setCheckable(True)
        self.btn_lineage.setToolTip(i18n.t("grid.sel.lineage_tip"))
        # OŚ OBIEKTU NA ZAZNACZENIU (S2b, D-OW-6) — JEDNA kontrolka z menu, nie dwa przyciski:
        # pasek trzyma już sześć, a siódmy i ósmy przewróciłyby go do drugiego rzędu. Obie pozycje
        # są tą samą sprawą („co to za obiekt"), więc menu jest tu grupowaniem, nie chowaniem.
        self.btn_object = QToolButton()
        # JEDEN CHEVRON, NIE DWA (R-S2b-11): tekst niósł własne „▾", a `InstantPopup` dokłada do
        # tego natywny wskaźnik menu — kontrolka zapowiadała rozwinięcie dwa razy. Strzałkę rysuje
        # styl, więc to ona zostaje: zna platformę i motyw, a literał w stringu nie.
        self.btn_object.setText(i18n.t("grid.sel.object"))
        self.btn_object.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_object)
        self.act_name = menu.addAction(i18n.t("grid.sel.object_name"))
        self.act_clear = menu.addAction(i18n.t("grid.sel.object_clear"))
        # DROGA POWROTU STOI OBOK GESTU, KTÓRY JEJ WYMAGA (R-S2b-3). Pozycja jest WIDOCZNA ZAWSZE,
        # nie tylko gdy ma co robić — inaczej user dowiadywałby się o odwracalności dopiero PO
        # pomyłce, czyli w jedynym momencie, w którym wiedza „to się da cofnąć" jest już spóźniona.
        # Populacja nagrobków jest z natury rzadka, więc ta pozycja bywa wygaszona przez większość
        # czasu; powód niesie tooltip KONTROLKI (menu w tym repo nie pokazuje tooltipów pozycji).
        self.act_restore = menu.addAction(i18n.t("grid.sel.object_restore"))
        # Pula skrótu „ostatnio użyte" (R-S2b-12) — tworzona RAZ; treść i widoczność ustawia
        # `set_recent_objects`. Powód takiego kształtu, a nie dokładania akcji: patrz jej docstring.
        self._recent_sep = menu.addSeparator()
        self._recent_sep.setVisible(False)
        self._recent_acts = [menu.addAction("") for _ in range(self._RECENT_MAX)]
        for act in self._recent_acts:
            act.setVisible(False)
            act.triggered.connect(lambda _checked=False, a=act: self.objectRecentPicked.emit(*a.data()))
        self.btn_object.setMenu(menu)
        # OŚ ŻYWOTNOŚCI KLATKI (D-OW-3/R2) — druga kontrolka z menu, tym samym argumentem co
        # „Obiekt ▾" (D-OW-6): obie pozycje to jedna sprawa („czy ta klatka jest jeszcze robotą"),
        # a dwa osobne przyciski rozsypałyby pasek. ⛔ Do menu obiektu tego NIE wkładamy: tamto
        # menu ma własny słownik powodów (`_object_gate_reason` → klucze `grid.sel.object_tip_*`),
        # więc wspólna kontrolka kazałaby jednemu tooltipowi tłumaczyć dwie różne osie.
        self.btn_frame = QToolButton()
        self.btn_frame.setText(i18n.t("grid.sel.frame"))
        self.btn_frame.setPopupMode(QToolButton.InstantPopup)
        fmenu = QMenu(self.btn_frame)
        self.act_retire = fmenu.addAction(i18n.t("grid.sel.frame_retire"))
        # DROGA POWROTU STOI OBOK GESTU, KTÓRY JEJ WYMAGA — ta sama reguła, co przy `act_restore`
        # osi obiektu: pozycja widoczna ZAWSZE, także wygaszona, bo o odwracalności trzeba wiedzieć
        # PRZED pomyłką. Tu waży to podwójnie: wycofanie zdejmuje klatkę z oczu, więc bez tej
        # pozycji user nie miałby skąd wiedzieć, że gest w ogóle się cofa.
        self.act_frame_restore = fmenu.addAction(i18n.t("grid.sel.frame_restore"))
        self.btn_frame.setMenu(fmenu)
        self.btn_save = QPushButton(i18n.t("grid.sel.save_view"))
        # RÓWNA WYSOKOŚĆ W RZĘDZIE (R-S2b-11): `QToolButton` liczy `sizeHint` inaczej niż
        # `QPushButton` i wychodził o 1 px niższy od sześciu sąsiadów — jedyny widżet innej klasy
        # w rzędzie wyglądał jak wpadka układu. Wysokość bierzemy z SĄSIADA, nie z liczby: stała
        # rozjechałaby się przy pierwszej zmianie motywu albo skali DPI.
        self.btn_object.setFixedHeight(self.btn_save.sizeHint().height())
        self.btn_frame.setFixedHeight(self.btn_save.sizeHint().height())
        lay.addWidget(self.count_label); lay.addSpacing(8)
        lay.addWidget(self.criteria_label, 1)
        # Złota akcja WYJĘTA z klastra pomocniczych (wizytacja P-C #6): sam bold przegrywał wzrokowo
        # z glifem ★ sąsiada, bo wszystkie pięć stało w jednym ciągu. Odstęp, nie ramka — QSS
        # `border` na QPushButton w Fusion zastępuje CAŁE malowanie ramki i spłaszcza przycisk.
        lay.addWidget(self.btn_clear)
        lay.addSpacing(12); lay.addWidget(self.btn_proj); lay.addSpacing(12)
        lay.addWidget(self.btn_macro)
        lay.addWidget(self.btn_rename); lay.addWidget(self.btn_lineage)
        lay.addWidget(self.btn_object); lay.addWidget(self.btn_frame)
        lay.addWidget(self.btn_save)

    def set_criteria(self, text):
        self.criteria_label.set_full_text(text)

    def set_object_actions(self, *, namable, clearable, stacks=0, restorable=0, reason=None):
        # `stacks` = ILE GEST RUSZY, nie ile ich jest w zaznaczeniu — parametr karmi wyłącznie
        # zdanie o skutku, więc wołający podaje `stacks_touchable` (bramka pakietu 0810, zarzut 1).
        """Uczciwy disabled obu pozycji osi obiektu (S2b, §4/14c-a). Cel gestu to WYŁĄCZNIE
        zaznaczenie, więc przy pustym gaśnie wszystko — fallback „to, co widoczne" jest dla ZAPISU
        osi ZAKAZANY (800 widocznych klatek i jedno chybione kliknięcie to ta sama sekunda).
        Kontrolka zbiorcza zostaje żywa, dopóki cokolwiek da się zrobić: menu, które tłumaczy
        wygaszoną pozycję, mówi WIĘCEJ niż wygaszony przycisk bez powodu.

        `reason` (klucz i18n z `_object_gate_reason`) niesie POWÓD wygaszenia — bez niego szara
        kontrolka odbierała jedyną powierzchnię, która mogła cokolwiek wytłumaczyć (R-S2b-8).
        Przy AKTYWNEJ kontrolce tooltip mówi, ile klatek gest realnie ruszy: to ta sama liczba,
        którą pokaże okno, więc user poznaje ją PRZED kliknięciem, a nie po."""
        self.act_name.setEnabled(bool(namable))
        self.act_clear.setEnabled(bool(clearable))
        self.act_restore.setEnabled(bool(restorable))
        # `restorable` W WARUNKU JAWNIE, choć dziś jest nadmiarowy: każdy nagrobek jest też
        # `namable` (`object_id IS NULL` ⇒ do nazwania), więc kontrolka i tak by żyła. Zależność
        # jest jednak NIEJAWNA i pęknie przy pierwszej zmianie `WEAK_OBJECT_SOURCES` — wtedy
        # kontrolka gasłaby nad żywą pozycją menu, czyli odbierała jedyną drogę do gestu.
        aktywna = bool(namable or clearable or restorable)
        self.btn_object.setEnabled(aktywna)
        if not aktywna:
            self.btn_object.setToolTip(i18n.t(reason or "grid.sel.object_tip_empty"))
            return
        # CZŁON O GOTOWYCH OBRAZACH PRZED GESTEM, nie po nim (R-S3-8). Powód `object_tip_stacks`
        # broni wyłącznie zaznaczenia z SAMYCH stosów — tam gasi kontrolkę. Przy zaznaczeniu
        # MIESZANYM nikt ich nie liczył, więc o tym, że gest ruszył gotowe obrazy (każdy złożony
        # z setek klatek), user dowiadywał się dopiero ze zdania po zapisie. Ten sam klucz, co
        # tamto zdanie — jedna fraza, jeden właściciel. Milczy przy zerze: „w tym gotowe obrazy: 0"
        # mówiłoby o czymś, czego w zaznaczeniu nie ma.
        # ...i liczy WYŁĄCZNIE stosy, które gest ruszy. Zmierzone: 181 ze 193 stosów archiwum ma
        # nazwę ze źródła mocnego, więc człon liczony „ile stosów jest w zaznaczeniu" kłamałby
        # w 94% przypadków — w tooltipie, który powstał po to, żeby powiedzieć prawdę PRZED gestem.
        tip = i18n.t("grid.sel.object_tip_ready", namable=namable, clearable=clearable)
        # TRZECIA DROGA MA BYĆ W TYM SAMYM ZDANIU, co dwie pierwsze — inaczej powtórzyłaby klasę
        # R-S3-8: tooltip zapowiadałby dwie liczby, a menu oferowało trzy akcje. Milczy przy zerze,
        # bo „do przywrócenia: 0" mówiłoby o czymś, czego w zaznaczeniu nie ma.
        if restorable:
            tip += i18n.t("grid.sel.object_tip_restorable", n=restorable)
        if stacks:
            tip += i18n.t_plural("grid.sel.object_stacks", stacks)
        self.btn_object.setToolTip(tip)

    def set_frame_actions(self, *, retirable, restorable, reason=None):
        """Uczciwy disabled osi żywotności klatki (D-OW-3/R2) — wzorzec `set_object_actions`.

        Powód wygaszenia liczy `_frame_gate_reason` i niesie go tooltip KONTROLKI: menu w tym repo
        nie pokazuje tooltipów pozycji, a szara kontrolka bez powodu odbiera jedyną powierzchnię,
        która mogła cokolwiek wytłumaczyć (dług R-S2b-8, zamknięty na sąsiedniej osi).

        Liczby biorą się z WIERSZY, które i tak są na ekranie (`base_rows` niesie `retired_at`,
        `present`, `n_present`, `superseded_by`) — bez nowego zapytania w gorącej pętli zaznaczenia.
        To jest PREZENTACJA, nie prawda: prawdę rozstrzyga klinga wewnątrz transakcji, bo między
        zaznaczeniem a zapisem plik może wrócić na dysk."""
        self.act_retire.setEnabled(bool(retirable))
        self.act_frame_restore.setEnabled(bool(restorable))
        aktywna = bool(retirable or restorable)
        self.btn_frame.setEnabled(aktywna)
        self.btn_frame.setToolTip(
            i18n.t("grid.sel.frame_tip_ready", retirable=retirable, restorable=restorable)
            if aktywna else i18n.t(reason or "grid.sel.frame_tip_empty"))

    def set_recent_objects(self, obiekty):
        """Skrót „ostatnio użyte" na dole menu obiektu (R-S2b-12) — 5 interakcji spada do 2.

        Najczęstszy gest brzmi „te klatki to ZNOWU NGC6960" i kosztował: Obiekt ▾ · Przypisz… ·
        rozwiń combo · wybierz · Przypisz. Skrót nie jest drugą ścieżką zapisu — kończy w tej samej
        klindze i z tym samym kluczem aliasu (`assign_dialog.alias_key`), pomija wyłącznie WYBÓR.

        Treść odświeża się przy każdym pokazaniu menu: lista jest pochodną dziennika i zmienia się
        po każdym geście, więc zbudowana raz kłamałaby dokładnie tam, gdzie ma pomagać.
        Wygaszone razem z „Przypisz obiekt…" — skrót nie może omijać bramki, którą ta pozycja stoi.

        PULA STAŁA, NIE TWORZENIE-I-USUWANIE — i to jest poprawka po awarii, nie mikrooptymalizacja.
        Pierwsza wersja dokładała `QAction` na każde otwarcie menu; bramka pakietu słusznie wytknęła
        rosnące sieroty (`removeAction` zdejmuje z menu, ale nie zwalnia), a zaproponowane lekarstwo
        — `deleteLater()` — **wywaliło Qt access violation** w losowym późniejszym teście kręcącym
        pętlą zdarzeń: usunięcie jest ODROCZONE, a menu bywa do tego czasu zebrane przez Pythona.
        Zmierzone: pełna bateria kończyła się `Fatal Python error: Aborted`, bez `deleteLater` jest
        czysta. Pula tworzona RAZ w konstruktorze nie ma ani sierot, ani odroczonych usunięć —
        pozycje nadmiarowe po prostu znikają (`setVisible(False)`).

        `_RECENT_MAX` jest sufitem listy: read-model i tak pyta o tyle samo, a menu z dwudziestoma
        pozycjami przestałoby być skrótem."""
        obiekty = list(obiekty)[:self._RECENT_MAX]
        self._recent_sep.setVisible(bool(obiekty))
        for act, o in zip(self._recent_acts, obiekty + [None] * self._RECENT_MAX):
            if o is None:
                act.setVisible(False)
                continue
            act.setText(i18n.t("grid.sel.object_recent", canon=o["canon"]))
            act.setData((o["canon"], o["catalog"], o["kind"]))
            act.setEnabled(self.act_name.isEnabled())
            act.setVisible(True)

    def set_clearable(self, on):
        """Uczciwy disabled „× Wyczyść zbiór": aktywny TYLKO gdy jest co zdjąć (facety/filtr)."""
        self.btn_clear.setEnabled(on)

    def set_have_frames(self, on):
        """Uczciwy disabled TYLKO realnej akcji na zbiorze (F3R#2): pusty zbiór gasi „Wydaj na stół…"
        (guard `_open_projection` zostaje drugą linią); „★ Zapisz widok" i panele zawsze żywe."""
        self.btn_proj.setEnabled(on)
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP) if on else i18n.t("grid.sel.proj_tip_empty"))

    def set_active_panel(self, which):
        """Synchronizuj zaznaczenie przycisków-paneli ze stanem stacku (`None`/'macro'/'rename');
        blockSignals — to odbicie stanu, nie klik."""
        for btn, key in ((self.btn_macro, "macro"), (self.btn_rename, "rename"),
                         (self.btn_lineage, "lineage")):
            btn.blockSignals(True)
            btn.setChecked(which == key)
            btn.blockSignals(False)


class _PanelStack(QStackedWidget):
    """Stack paneli kling (F3): sizeHint = BIEŻĄCA strona — goły QStackedWidget bierze max ze stron,
    więc otwarte makro wisiałoby w pasie wysokości renamu [skill: pyside6-desktop-layout-gotchas].

    SAM sizeHint NIE WYSTARCZYŁ i to jest lekcja zmierzona, nie teoria (firsthand 2026-08-02).
    Nadpisane podpowiedzi czyta layout RODZICA, ale wewnętrzny `QStackedLayout` osobno wymusza na
    tym widżecie minimum równe NAJWYŻSZEJ stronie — więc stack i tak nie schodził poniżej 240 px
    (wysokość renamu), a niska strona wisiała w nim WYŚRODKOWANA. Zmierzone na realnym oknie:
    panel rodowodu zajmował 68 px treści, a odbierał tabeli 246 px — 92 px martwego pasa nad
    i 92 pod. Panel makra tracił 6 px, bo jego strona jest bliska maksimum i pasa nie widać.

    Dlatego sufit jest USTAWIANY WPROST z bieżącej strony — przy przełączeniu strony i przy każdej
    zmianie jej treści (`LayoutRequest`), bo panele rosną i maleją w biegu (ostrzeżenie w rodowodzie,
    rzędy tokenów w renamie)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ŹRÓDŁO PUSTKI: `QLayout` z domyślnym `SetDefaultConstraint` wpisuje widżetowi TWARDE
        # `minimumSize` równe maksimum ze stron — i to ono, nie podpowiedzi, trzymało stack na
        # wysokości renamu. Zdejmujemy wymuszanie i czyścimy minimum wpisane przed tą zmianą;
        # od tej pory o wysokości decydują nadpisane niżej podpowiedzi BIEŻĄCEJ strony.
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumHeight(0)
        self.currentChanged.connect(lambda _i: self._sync_ceiling())

    def event(self, e):
        # DWA KROKI SĄ KONIECZNE, każdy leczy co innego (zmierzone osobno):
        # zdjęcie wymuszenia pozwala stackowi ZEJŚĆ do wysokości bieżącej strony, a sufit sprawia,
        # że layout rodzica nie rezerwuje slotu na najwyższą stronę i nie centruje w nim niskiej.
        # Sufit liczymy przy `LayoutRequest`, bo panele rosną i maleją BEZ przełączania strony
        # (ostrzeżenie w rodowodzie, rzędy tokenów w renamie) — i dopiero po zdjęciu wymuszenia
        # podpowiedź strony jest w tym momencie już prawdziwa. Sam sufit obcinał treść o krok.
        if e.type() == QEvent.LayoutRequest:
            self._sync_ceiling()
        return super().event(e)

    def _sync_ceiling(self):
        """Sufit = wysokość BIEŻĄCEJ strony, z JEDNĄ synchroniczną przeliczką rodzica.

        Bez niej sufit był o krok w tyle i OBCINAŁ treść (zmierzone: strona żądała 68 px, stack
        stał na 56, lista traciła 12 px z 40) — `setMaximumHeight` w trakcie `LayoutRequest` trafia
        w przebieg, który rodzic już policzył. Guard równości zamyka pętlę: przeliczka rodzica
        wraca tu `LayoutRequest`-em, ale przy niezmienionym suficie nie robi nic."""
        w = self.currentWidget()
        if w is None:
            return
        h = w.sizeHint().height()
        if self.maximumHeight() != h:
            self.setMaximumHeight(h)
            rodzic = self.parentWidget()
            if rodzic is not None and rodzic.layout() is not None:
                rodzic.layout().activate()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()



class StagingDrawer(QFrame):
    """Stała szuflada dolna stagingu (doktryna §5: „N zmian oczekuje · Przejrzyj · Zatwierdź · Odrzuć").
    Postęp i wynik commitu renderują się TU (nie w łańcuchu modali). Emituje `commit()`/`reject()`."""

    commit = Signal()
    reject = Signal()
    cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.dot = QLabel("○")
        self.label = QLabel(i18n.t("grid.drawer.empty"))   # słownik F3 (§4)
        self.result = QLabel(""); self.result.setProperty("role", "secondary")   # F6 §7
        # Postęp writebacku renderuje się TU (nie w modalu): pasek + „Anuluj" wchodzą w miejsce
        # Zatwierdź/Odrzuć na czas commitu/undo (off-thread — GUI nie zamarza; rdzeń commituje per-plik).
        self.bar = QProgressBar(); self.bar.setVisible(False); self.bar.setMaximumWidth(220); self.bar.setTextVisible(False)
        self.btn_cancel = QPushButton(i18n.t("grid.action.cancel")); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(lambda: self.cancel.emit())
        self.btn_commit = QPushButton(i18n.t("grid.action.commit")); self.btn_commit.clicked.connect(lambda: self.commit.emit())
        self.btn_reject = QPushButton(i18n.t("grid.action.reject")); self.btn_reject.clicked.connect(lambda: self.reject.emit())
        # Klaster licznik+wynik po LEWEJ (dot·label·result), rozpychacz, akcje po prawej — inaczej
        # `result` ze stretch=1 rozrzucał licznik i przyciski na całą szerokość (wizytator D1).
        lay.addWidget(self.dot); lay.addWidget(self.label); lay.addSpacing(8)
        lay.addWidget(self.result); lay.addStretch(1)
        lay.addWidget(self.bar); lay.addWidget(self.btn_cancel)
        lay.addWidget(self.btn_commit); lay.addWidget(self.btn_reject)
        self.set_count(0)

    def begin_progress(self, total):
        """Wejście w tryb postępu (start commitu/undo): pasek + „Anuluj" widoczne, Zatwierdź/Odrzuć
        schowane (nie klikać w biegu). `total=0` → pasek nieokreślony do pierwszego progresu."""
        self.bar.setRange(0, total if total > 0 else 0); self.bar.setValue(0); self.bar.setVisible(True)
        self.btn_cancel.setVisible(True); self.btn_cancel.setEnabled(True)
        self.btn_commit.setVisible(False); self.btn_reject.setVisible(False)

    def update_progress(self, done, total, path):
        """Slot postępu (główny wątek): pasek done/total + nazwa bieżącego pliku w `result`."""
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        tail = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        self.result.setText(f"{done}/{total} · {tail}")

    def end_progress(self):
        """Wyjście z trybu postępu: schowaj pasek + „Anuluj". Widoczność Zatwierdź/Odrzuć/Cofnij ustawia
        wołający (set_count / set_commit_actions_visible) w post-processingu commitu."""
        self.bar.setVisible(False); self.btn_cancel.setVisible(False)
        self.btn_commit.setVisible(True); self.btn_reject.setVisible(True)

    def set_count(self, n, *, result=None, label=None):
        self._n = n
        if n > 0:
            self.dot.setText("●"); _set_role(self.dot, "warn")   # U+25CF: jest w Segoe UI, paruje z „○" (wiz F3 #2)
            # `label` rozróżnia klingę też przy n>0: „N zmian nazw oczekuje" vs domyślne „N zmian
            # oczekuje" (mikro-zmiana §0; call-sites makra bez label → domyślny tekst, R1 #8).
            self.label.setText(label or i18n.t("grid.drawer.pending", n=n))
            if result is None:
                self.result.setText("")      # nowy staging: skasuj STALE wynik commitu/odrzucenia (wiz #7)
        else:
            self.dot.setText("○"); _set_role(self.dot, "secondary")
            # `label` nadpisuje domyślny tekst pustego stanu: po commicie „Zatwierdzono…" zamiast
            # pustostanu poczekalni (sprzeczność z wynikiem obok — wizytator D2).
            self.label.setText(label or i18n.t("grid.drawer.empty"))
        self.btn_commit.setEnabled(n > 0)
        self.btn_reject.setEnabled(n > 0)
        # Nowy staging (n>0) → Zatwierdź/Odrzuć znowu widoczne. NIE chowa tu „Cofnij" (osobny przycisk
        # FramesView) — to robi `_dismiss_undo` przy starcie stagingu (recenzent #1/#4, wiz #3).
        if n > 0:
            self.set_commit_actions_visible(True)
        if result is not None:
            self.result.setText(result)

    def set_commit_actions_visible(self, on):
        """Pokaż/ukryj Zatwierdź+Odrzuć. Po commicie chowamy je, bo jedyną sensowną akcją jest
        „Cofnij" (wizytator #5 — nie mieszać żywego Cofnij z wyszarzonym Zatwierdź/Odrzuć)."""
        self.btn_commit.setVisible(on)
        self.btn_reject.setVisible(on)

    def set_result(self, text):
        """Sam wynik operacji plikowej spoza stagingu (gesty izolacji zapisu w miejscu): postęp szedł
        przez tę szufladę, więc wynik zastępuje w niej ostatnią linię postępu. Licznika i etykiety
        poczekalni NIE rusza - gest nie zmienia stagingu, a „Zatwierdzono…" przy żywym „Cofnij"
        musi przeżyć."""
        self.result.setText(text)


class ReleaseDialog(QDialog):
    """Okno gestu „Zwolnij plik do skanu…" (`repo.release_inplace_op`): skutek słowami, liczba kopii
    i POWÓD wpisany przez człowieka. Zwolnienie nie zmienia pliku i niczego nie sprawdza - to jego
    rozstrzygnięcie, że plik jest w porządku, więc bez powodu „Zwolnij" jest wygaszone, a powód
    trafia do zdarzenia `location.writeback_released`. Enter nie przejdzie obok bramki: przycisk
    domyślny jest wygaszony, a `accept` sprawdza powód drugi raz (EXPECT)."""

    def __init__(self, n, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("grid.inplace.release"))
        lay = QVBoxLayout(self)
        opis = QLabel(i18n.t_plural("grid.inplace.release_ask", n))
        opis.setWordWrap(True)
        lay.addWidget(opis)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(i18n.t("grid.inplace.release_placeholder"))
        lay.addWidget(self.edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = self.buttons.button(QDialogButtonBox.Ok)
        self.btn_ok.setText(i18n.t("grid.inplace.release_ok"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.edit.textChanged.connect(self._sync_ok)
        self._sync_ok()

    def reason(self):
        """Powód bez białych znaków na brzegach - taki idzie do dziennika."""
        return self.edit.text().strip()

    def _sync_ok(self):
        on = bool(self.reason())
        self.btn_ok.setEnabled(on)
        self.btn_ok.setToolTip("" if on else i18n.t("grid.inplace.release_need_reason"))

    def accept(self):
        if not self.reason():
            return
        super().accept()


class PolaWorker(QObject):
    """Pokrycie panelu „Pola" liczone POZA wątkiem GUI (rdzeń: Qt-wolny `pola`, koszty tam).

    Bliźniak `PlanWorker`: `db_path` → WŁASNE połączenie otwarte w SWOIM wątku (sqlite
    `check_same_thread`), odcisk i pokrycie w jednej transakcji czytającej; `con` (tryb inline,
    testy i `:memory:`) → ten sam rdzeń na połączeniu wołającego, bez transakcji, bo bez wątku.
    `poprzedni_odcisk` równy bieżącemu = karty bez zmian: `keyword_facets` NIE jest wołane,
    a `done` niesie `None` zamiast pól (listwa zostaje, jaka była).

    ANULOWANIE MUSI UMIEĆ PRZERWAĆ SAMO ZAPYTANIE: pokrycie to jedno zapytanie trwające sekundy,
    więc flaga sprawdzana „przed następnym krokiem" kazałaby zamknięciu okna czekać do jego końca.
    `Connection.interrupt` jest w sqlite3 wprost przeznaczone do wołania z INNEGO wątku; zamek
    pilnuje, żeby nie trafiło w połączenie właśnie zamykane."""

    done = Signal(int, object, object)   # generacja, odcisk, pola (lista słowników) albo None
    failed = Signal(int, str)            # generacja, komunikat
    finished = Signal()                  # run() wrócił KAŻDĄ drogą → quit wątku

    def __init__(self, gen, poprzedni_odcisk, *, db_path=None, con=None):
        super().__init__()
        self._gen = gen
        self._poprzedni = poprzedni_odcisk
        self._db_path = db_path
        self._con_zewn = con
        self._con = None
        self._zamek = threading.Lock()
        self._cancel = threading.Event()

    def request_cancel(self):
        """Wołane z wątku GUI: flaga + przerwanie zapytania w locie (patrz docstring klasy)."""
        self._cancel.set()
        with self._zamek:
            if self._con is not None:
                self._con.interrupt()

    @Slot()
    def run(self):
        odcisk = pola = error = None
        try:
            if self._con_zewn is not None:
                odcisk, pola = self._policz(self._con_zewn)
            else:
                with self._zamek:
                    self._con = db.connect(self._db_path)
                try:
                    # Migawka WAL na oba zapytania: odcisk opisuje dokładnie dane pokrycia.
                    self._con.execute("BEGIN")
                    odcisk, pola = self._policz(self._con)
                finally:
                    with self._zamek:
                        self._con.close()          # PRZED emisją - główny wątek czyta przez swoje
                        self._con = None
        except Exception as exc:                   # błąd (także przerwanie) → sygnał, NIE crash
            error = f"{type(exc).__name__}: {exc}"
        if error is not None:
            self.failed.emit(self._gen, error)
        else:
            self.done.emit(self._gen, odcisk, pola)
        self.finished.emit()

    def _policz(self, con):
        odcisk = pola_mod.odcisk_kart(con)
        if odcisk == self._poprzedni:
            return odcisk, None                    # karty bez zmian - liczyć nie ma czego
        if self._cancel.is_set():
            raise RuntimeError("przerwano")
        return odcisk, pola_mod.pokrycie(con)


class FramesView(QWidget):
    """Widok „Klatki": panel Pól | (perspektywa + filtr + PASEK ZBIORU + panele kling + grid)
    + poczekalnia zmian (szuflada stagingu). Kontrakt montażu `MainWindow`: `__init__(con, now_fn,
    parent)`, sygnał `status_message`, `refresh()`. KROK 4: makro (druga klinga) — filtr→oblicz→
    przypisz na widocznych klatkach, staging, commit/undo. F3: klingi jako panele `_PanelStack`
    otwierane z `SelectionBar` (najwyżej jeden widoczny; R#9 w `_toggle_panel`)."""

    status_message = Signal(str)
    # Gest osi obiektu z paska Zbiorów zmienia stan, który pokazuje INNE okno (kolejka przeglądu
    # osi obiektu). Sygnał, nie wołanie: grid nie zna gospodarza i nie ma go poznawać (NARROW).
    object_axis_changed = Signal()
    # STAN LICZONY PRZEZ PORZĄDKI SIĘ ZMIENIŁ - jeden sygnał z końca drogi KAŻDEGO gestu gridu,
    # który rusza populację `queries.tasks_state`; gospodarz podpina go RAZ pod `refresh_counts`
    # (plakietka nawigacji). Osobno od `object_axis_changed`, bo ten mówi o INNEJ powierzchni
    # (kolejka przeglądu osi obiektu) i nie odpala przy gestach osi żywotności klatki - a właśnie
    # przez to plakietka zostawała przy liczbie sprzed „Przywróć"/„Wycofaj" do wejścia w Porządki.
    # Dopinanie odświeżenia przy każdym geście osobno to figura, która w tym repo rozjeżdżała się
    # już kilka razy („etykieta kłamie"); właściciel emisji jest jeden - ogon gestu. Emitują:
    # `_po_gescie_osi`, `_po_gescie_klatki`, gesty panelu rodowodu i ogony writebacku (makro:
    # `_after_commit`/`_after_undo`, rename: `_after_commit_rename`/`_after_undo_rename`, błąd:
    # `_on_wb_failed`), wyłącznie gdy gest coś zapisał (ogon błędu - zawsze, bo nie wie, ile zdążył
    # zapisać). Rename jest tu dla JEDNEJ reguły, nie dlatego, że dziś wiadomo, który wiersz czyta
    # `location.path`: „każdy ogon zapisu emituje" nie wymaga pamiętania, który wiersz Porządków
    # czyta które pole, a kosztuje jedno `tasks_state` po geście.
    stan_porzadkow_changed = Signal()
    # Mutex DWÓCH powierzchni writebacku (D-PD-3): gospodarz przekazuje ten fakt drugiej powierzchni
    # (dialog „Napraw nagłówek…"). Dwa równoległe commity spotkałyby się na `BEGIN IMMEDIATE`
    # z `busy_timeout` 5 s i jeden wróciłby jako 'failed' — bez powodu widocznego dla usera.
    writeback_busy = Signal(bool)
    # RECEPTA MA WŁASNY KANAŁ (FH-2), bo dostała własny nośnik na pasku. Zdanie po geście przestało
    # się mieścić w `showMessage` - zmierzone 252 znaki = 1336 px przy 1459 px dostępnych (przy
    # skalowaniu 125 % już 1695/1672), a `QStatusBar` tnie BEZ wielokropka, w środku słowa, i ucina
    # człon OSTATNI, czyli receptę. Rozdział jest tu koniecznością, nie estetyką - lustro
    # `phase_label`: raport („co się stało") i recepta („co możesz teraz zrobić") konkurowały
    # o jedno pole, więc ginęła ta druga, choć to po nią user sięga.
    #
    # RAPORT ZOSTAJE NA `status_message` I TO JEST CELOWE: wydzielenie CAŁEGO zdania na nowy sygnał
    # przepięłoby kanał, którym mówią wszystkie inne gesty widoku, a raport gestu osi niczym się od
    # nich nie różni. Osobny kanał należy się temu członowi, który ma osobny nośnik - i tylko jemu.
    # Recepta leci ZARAZ PO raporcie (nigdy przed), więc pusta gasi cudzą z poprzedniego gestu.
    status_recipe = Signal(str)

    def __init__(self, con, now_fn=None, parent=None, *, pola_poza_watkiem=False):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)   # worker writebacku otwiera WŁASNE połączenie (per-wątek)
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._filter_tree = None
        # F4: stan listwy facetów (serializowany w perspektywie OSOBNO od `_filter_tree` — nota R2)
        # + drzewo EFEKTYWNE compose(facety, advanced), ustawiane w refresh() (źródło paska kryteriów,
        # F4R#8). Oba PRZED pierwszym refresh() (F4R2#7).
        self._facet_state = facet_model.empty_state()
        self._effective_tree = None
        self._zeruj_flagi()         # flagi perspektyw `_only_*` - skład z `_TRIMY`, jedna enumeracja
        self._cel_gestu = []        # klatki wypchnięte z widoku przez ostatni gest - wracają do
                                    # zaznaczenia przy najbliższym przeładowaniu zbioru (FC-2)
        self._reveal_facet = None   # (facet, wartość) do odsłonięcia w listwie — patrz `apply_object_facet`
        self._frame_ids = []      # frame_id widoczne w gridzie (cel makra) — aktualizowane w refresh()
        self._run_id = None       # JEDEN run_id sesji makra (R#5 lifecycle: stage→commit/reject zwalnia)
        self._n_total = 0         # liczba widocznych klatek (baza licznika; zaznaczenie dokładane, G2)
        # Stan renamu — CZTERY zmienne (R1 #1 + R2 #1): run aktywnego stagingu, flaga „skommitowany"
        # (re-stage po commicie MINTUJE nowy run, nie kasuje wierszy 'applied'=undo), OSOBNY cel „Cofnij"
        # (przechwycony przy commicie — bez niego mint przekierowałby żywy Cofnij na pusty run = złudzenie),
        # tryb dispatchu współdzielonego „Cofnij" ({None,macro,rename}).
        self._rename_run_id = None
        self._rename_run_committed = False
        self._undo_rename_run_id = None
        self._undo_mode = None
        self._preview_owner = None   # {None,'macro','rename'} — podgląd współdzielony (R1 #19)
        # Writeback OFF-THREAD (commit/undo nie zamrażają GUI): cykl worker+wątek trzyma WSPÓLNY
        # uchwyt (`wb_worker.WritebackRunner`, P-D/D-PD-3 — ten sam kod wykonuje dialog „Napraw
        # nagłówek…"), tu zostaje tylko to, co widżetowe. Uchwyt POWSTAJE W `__init__`, bo seam
        # `_writeback_async` bywa ustawiany z zewnątrz PRZED pierwszą operacją (testy).
        # `_wb_target_id` zostaje W WIDOKU: czyta go `_after_commit_rename` PO zakończeniu operacji,
        # a uchwyt jest per-powierzchnia — wspólny ślad celu nadpisywałyby sobie dwa okna.
        self._wb = WritebackRunner(self._db_path, now_fn=self._now, parent=self)
        self._wb.busy_changed.connect(self.writeback_busy)   # re-emisja: uchwyt zna oba końce operacji
        self._wb_target_id = None
        self._foreign_wb = False   # DRUGA powierzchnia pisze (mutex; ustawia gospodarz)
        self._etap_w_biegu = False  # etap Dostawy pisze do bazy (`set_busy`) - gesty izolacji czekają
        self._cel_gestu_zapisu = []  # klatki ostatniego gestu izolacji - zaznaczenie po jego końcu
        # POKRYCIE PÓL POZA WĄTKIEM GUI (`PolaWorker`). Zapytanie trwa na żywym archiwum 5,6-5,9 s,
        # a szło przy otwarciu bazy i po KAŻDYM przebiegu Dostawy - okno stało wtedy jednym blokiem
        # dłuższym niż próg „Nie odpowiada". `pola_poza_watkiem=False` (domyślne) = ten sam rdzeń
        # inline: widok zbudowany wprost (testy, `:memory:`) dostaje pola synchronicznie, jak dotąd;
        # gospodarz (`MainWindow`) włącza wątek. Kolumny zaczynają PUSTE - domyślne wybiera pierwszy
        # wynik (`_zastosuj_pola`), bo bez pokrycia nie wiadomo, które keywordy są najczęstsze.
        self._pola_async = pola_poza_watkiem
        self._columns = []
        self._pola = None           # ostatnie ZASTOSOWANE pokrycie (lista {"keyword", "n"})
        self._pola_odcisk = None    # odcisk kart, z którego ono pochodzi (`pola.odcisk_kart`)
        self._pola_gen = 0          # generacja prośby - wynik starszej ląduje w koszu
        self._pola_worker = None
        self._pola_thread = None
        self._pola_ponow = False    # prośba w trakcie biegu → jeszcze jeden bieg po nim
        self._pola_stop = False     # widok zamykany - żadnego nowego biegu
        self._zbudowany = False     # koniec `__init__`: od tej chwili zmiana kolumn przeładowuje zbiór
        self._build_ui()
        # PRZED pierwszym zbudowaniem listy perspektyw: rejestr sprzed I-1 dowozi swoje widoki do
        # bazy, więc combo od razu pokazuje komplet, a nie „gdzie się podziały moje perspektywy".
        self._import_settings_perspectives()
        self._load_facets()
        self.refresh()
        self._refresh_drawer()
        self._zbudowany = True

    # ---- budowa ----
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Górny pasek CHUDY (F3): tylko soczewki widoku (perspektywa + grupowanie); akcje na ZBIORZE
        # mieszkają w SelectionBar niżej.
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("grid.top.perspective")))
        self.combo_persp = QComboBox()
        self.combo_persp.currentIndexChanged.connect(self._on_perspective)
        bar.addWidget(self.combo_persp)
        bar.addSpacing(16)
        bar.addWidget(QLabel(i18n.t("grid.top.group_by")))
        self.combo_group = QComboBox()
        self.combo_group.addItem(i18n.t("grid.top.no_group"), None)
        for label, key in BASE_COLS:
            if key not in ("path",):
                # `BASE_COLS` niesie KLUCZE i18n, nie napisy (rozwiązuje je `headerData`) — bez `t()`
                # listwa pokazywała `object.col.name` zamiast „Obiekt". Znalezione sondą FC-3 na
                # żywym archiwum: SZEŚĆ z siedmiu pozycji renderowało klucz wewnętrzny.
                self.combo_group.addItem(i18n.t(label), key)
        # Grupowanie po GRUPIE WERSJI (perspektywa „Wersje stosów") - pochodna wiersza, nie kolumna.
        self.combo_group.addItem(i18n.t("grid.top.group_version"), _GRUPA_WERSJI)
        self.combo_group.currentIndexChanged.connect(self._on_group)
        bar.addWidget(self.combo_group)
        bar.addStretch(1)
        outer.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        # F4: lewa kolumna = pionowy splitter FacetRail (góra, dominuje) / Pola (dół) — wybór kolumn
        # to inna troska niż zawężanie zbioru (COHESION), oba zostają widoczne.
        self.facet_rail = FacetRail()
        self.facet_rail.facetsChanged.connect(self._on_facet_change)
        # Ctrl+F → szukajka obiektów (R-S3-6). `QKeySequence.Find`, nie literał: sekwencję „znajdź"
        # zna platforma i to ona ma o niej decydować. Kontekst WIDGET-Z-DZIEĆMI, nie okno — Ctrl+F
        # wciśnięty w Porządkach albo w planerze nie ma prawa przerzucać kursora do listwy Zbiorów.
        self._sc_find = QShortcut(QKeySequence.Find, self)
        self._sc_find.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_find.activated.connect(self.facet_rail.focus_search)
        self.fields = FieldsPanel()
        self.fields.columnsChanged.connect(self._on_columns)
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.facet_rail)
        left.addWidget(self.fields)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)
        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.filter_panel = FilterPanel([])
        self.filter_panel.filterApplied.connect(self._on_filter)
        rv.addWidget(self.filter_panel)

        # Pasek zbioru (F3): licznik + kryteria słowami + akcje; klingi jako panele w stacku niżej.
        self.sel_bar = SelectionBar()
        self.count_label = self.sel_bar.count_label      # TEN SAM QLabel (F3R#5) — `_update_count` bez zmian
        self.sel_bar.btn_proj.clicked.connect(self._open_projection)
        self.sel_bar.btn_clear.clicked.connect(self._on_clear_selection)
        self.sel_bar.btn_save.clicked.connect(self._save_perspective)
        self.sel_bar.btn_macro.clicked.connect(lambda: self._toggle_panel("macro"))
        self.sel_bar.btn_rename.clicked.connect(lambda: self._toggle_panel("rename"))
        self.sel_bar.btn_lineage.clicked.connect(lambda: self._toggle_panel("lineage"))
        self.sel_bar.act_name.triggered.connect(self._on_object_name)
        self.sel_bar.act_clear.triggered.connect(self._on_object_clear)
        self.sel_bar.act_restore.triggered.connect(self._on_object_restore)
        self.sel_bar.act_retire.triggered.connect(self._on_frame_retire)
        self.sel_bar.act_frame_restore.triggered.connect(self._on_frame_restore)
        # Skrót „ostatnio użyte" (R-S2b-12): lista jest pochodną dziennika, więc odświeża się
        # PRZY OTWARCIU menu, nie raz na budowie widoku — inaczej pokazywałaby stan sprzed gestów.
        self.sel_bar.btn_object.menu().aboutToShow.connect(self._sync_recent_objects)
        self.sel_bar.objectRecentPicked.connect(self._on_object_recent)
        rv.addWidget(self.sel_bar)

        self.macro_bar = MacroBar([])
        self.macro_bar.preview.connect(self._on_macro_preview)
        self.macro_bar.stage.connect(self._on_macro_stage)
        self.macro_bar.cleared.connect(self._on_macro_clear)

        self.rename_bar = RenameBar()                    # bliźniaczy panel obok makra (G3)
        self.rename_bar.preview.connect(self._on_rename_preview)
        self.rename_bar.stage.connect(self._on_rename_stage)
        self.rename_bar.cleared.connect(self._on_rename_clear)
        self.rename_bar.sourceChanged.connect(self._refresh_date_echo)

        self.lineage_bar = LineageBar()                   # trzeci panel stacku (I-2d)
        self.lineage_bar.judged.connect(self._on_lineage_judged)
        self.lineage_bar.offset_asked.connect(self._on_lineage_offset)
        self._lineage_frame_id = None       # cel gestu odniesienia (klatka stosu w panelu)
        # TAKT 3 gestu osi stosu — wstrzykuje gospodarz (`MainWindow`), bo tylko on zna Dostawę.
        # None = widok bez gospodarza (testy samego gridu): gest zapisuje, a zdanie mówi, gdzie
        # przeliczyć — dokładnie jak przed tą zmianą, więc brak wstrzyknięcia niczego nie psuje.
        self.run_stage_fn = None

        self.panel_stack = _PanelStack()                 # najwyżej JEDEN panel widoczny (F3)
        self.panel_stack.addWidget(self.macro_bar)
        self.panel_stack.addWidget(self.rename_bar)
        self.panel_stack.addWidget(self.lineage_bar)
        self.panel_stack.setVisible(False)               # żaden panel nie otwarty na starcie
        # PANEL BIERZE TYLE, ILE POTRZEBUJE — NADMIAR NALEŻY DO TABELI (wiz T2 N1). Domyślna
        # polityka `QStackedWidget` jest pionowo Expanding, więc stack pochłaniał leftover i stał
        # 309 px WYSOKI także wtedy, gdy niósł jedno zdanie (`sizeHint` 36 px): panel zjadał połowę
        # okna, a tabela pokazywała 10 wierszy ze 128. Samo skrócenie treści panelu tego nie ruszyło
        # — bo o wysokości decydowała polityka, nie treść.
        self.panel_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        rv.addWidget(self.panel_stack)

        self.model = GridTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        # Debounce panelu daty: `selectionChanged` może sypać setki eventów przy zaznaczeniu wsadu
        # → przelicz echo raz, po 150 ms ciszy (R1 #15).
        self._date_timer = QTimer(self); self._date_timer.setSingleShot(True); self._date_timer.setInterval(150)
        self._date_timer.timeout.connect(self._refresh_date_echo)
        # Panel rodowodu wisi na TYM SAMYM debouncie (I-2d): oba czytają zaznaczenie, oba tylko przy
        # własnym otwartym panelu, więc drugi timer byłby drugim właścicielem tego samego zdarzenia.
        self._date_timer.timeout.connect(self._refresh_lineage)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._on_selection_changed())
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)   # zebra: skanowalność długich list (P3-5)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        # MENU KONTEKSTOWE TABELI - dom gestu „Zostaw tę wersję" (perspektywa „Wersje stosów").
        # Nie pasek zbioru: `sel_bar` trzyma już osiem przycisków, a podłoga okna jest mierzona
        # - dziewiąty poszerzałby ją w KAŻDEJ perspektywie dla gestu, który ma sens w jednej.
        # Nie menu „Klatka": tamto jest osią żywotności z własnym słownikiem powodów wygaszenia,
        # a wspólna kontrolka kazałaby jednemu tooltipowi tłumaczyć dwie osie (argument D-OW-6).
        # Gest działa na JEDNYM wierszu („tę wersję"), więc prawy klik na wierszu jest jego
        # naturalnym miejscem. Menu powstaje RAZ (wzorzec puli `set_recent_objects`: tworzenie
        # i kasowanie menu per klik zostawiało sieroty albo odroczone usunięcia), a stan akcji
        # ustawia `_sync_menu_wersji` tuż przed pokazaniem.
        # DRUGI DOM W TYM SAMYM MENU: drogi wyjścia z izolacji zapisu w miejscu (warunek wsadu
        # AR-17 (2)) - „Dokończ zapis", „Przywróć nagłówek sprzed zapisu", „Zwolnij plik do
        # skanu…". Ten sam argument co wyżej: gesty dotyczą KOPII kilku klatek w dwóch
        # perspektywach, a dziewiąta kontrolka paska zbioru poszerzałaby podłogę okna w każdej.
        # Nie menu „Klatka": izolacja jest stanem pliku, nie żywotności klatki (D-OW-6). Sekcja
        # zapisu pokazuje się w perspektywach „Plik po przerwanym zapisie" / „Zapis czeka na
        # dokończenie" i nad każdą klatką z kopią izolowaną; poza tym prawy klik zostaje tym, czym
        # był (niczym). Jedno menu, nie dwa: stos z kopią izolowaną w „Wersjach stosów" ma
        # dostać obie sekcje naraz.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_menu)
        self._menu_tabeli = QMenu(self.table)
        self._menu_tabeli.setToolTipsVisible(True)   # powód wygaszenia niesie tooltip POZYCJI
        self.act_keep_version = self._menu_tabeli.addAction(i18n.t("grid.version.keep"))
        self.act_keep_version.triggered.connect(self._on_keep_version)
        self._sep_zapisu = self._menu_tabeli.addSeparator()
        self.act_finish_write = self._menu_tabeli.addAction(i18n.t("grid.inplace.finish"))
        self.act_finish_write.triggered.connect(self._on_finish_write)
        self.act_restore_header = self._menu_tabeli.addAction(i18n.t("grid.inplace.restore"))
        self.act_restore_header.triggered.connect(self._on_restore_header)
        self.act_release_file = self._menu_tabeli.addAction(i18n.t("grid.inplace.release"))
        self.act_release_file.triggered.connect(self._on_release_file)
        rv.addWidget(self.table, 1)   # stretch: nadmiar pionu należy do TABELI, nie do panelu (N1)

        # PUSTY STAN = ZDANIE + GEST (FH-4). `self.empty` zostaje etykietą z tekstem (kontrakt testów
        # i sond: `empty.text()`, `empty.isVisible()`), a przycisk stoi obok niej w jednym pojemniku,
        # który przejmuje stretch - oba jadą razem na środek pustej przestrzeni. Przycisk WYKONUJE
        # receptę, którą pusty stan podaje (`wykonaj_recepte_powrotu` z celem `_CEL_WIDOK`), zamiast
        # ją tylko opisywać. Lambda, nie sam slot: `clicked` niesie `checked: bool`, a cel jest
        # keyword-only właśnie po to, żeby ten bool nie wpadł w jego miejsce.
        self.empty_box = QWidget()
        eb = QVBoxLayout(self.empty_box); eb.setContentsMargins(0, 0, 0, 0)
        eb.addStretch(1)
        self.empty = QLabel(i18n.t(_EMPTY_FILTER))
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True); self.empty.setVisible(False)
        eb.addWidget(self.empty)
        self.empty_btn = QPushButton()
        self.empty_btn.clicked.connect(lambda: self.wykonaj_recepte_powrotu(cel=_CEL_WIDOK))
        self.empty_btn.setVisible(False)
        eb.addWidget(self.empty_btn, 0, Qt.AlignHCenter)
        eb.addStretch(1)
        self.empty_box.setVisible(False)
        rv.addWidget(self.empty_box, 1)   # stretch: pusty stan zbiera leftover - SelectionBar/panel nie balonieją (wiz F3 #1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)   # stretch: grid dominuje okno (doktryna §5), pasek nie zjada połowy (P2-1)

        self.drawer = StagingDrawer()  # stała szuflada dolna stagingu (doktryna §5)
        self.drawer.commit.connect(self._on_commit)
        self.drawer.reject.connect(self._on_reject)
        self.drawer.cancel.connect(self._on_wb_cancel)
        outer.addWidget(self.drawer)

    # ---- facety / perspektywy ----
    def _load_facets(self):
        """Przeładuj to, co widok wie o SCHEMACIE archiwum: pokrycie pól (zamówione - patrz
        `_zamow_pola`) i listę perspektyw (synchronicznie, bo to kilka wierszy `saved_query`).
        Woła gospodarz po przebiegu Dostawy i sam widok przy budowie."""
        self._zamow_pola()
        self._odbuduj_perspektywy()

    # ---- pokrycie pól (panel „Pola", keywordy filtra i makra) ----
    def _zamow_pola(self):
        """Poproś o pokrycie pól. W trybie wątku wraca od razu; wynik przychodzi do `_on_pola_done`.
        Prośba w trakcie biegu nie odpala drugiego wątku: bieżący wynik jest już starszy niż prośba
        (generacja), więc trafia do kosza, a po jego końcu rusza jeden bieg więcej (`_sprzataj_pola`)."""
        if self._pola_stop:
            return
        self._pola_gen += 1
        if self._pola_worker is not None:
            self._pola_ponow = True
            return
        self._start_pola()

    def _start_pola(self):
        worker = PolaWorker(self._pola_gen, self._pola_odcisk,
                            db_path=self._db_path if self._pola_async else None,
                            con=None if self._pola_async and self._db_path else self.con)
        worker.done.connect(self._on_pola_done)
        worker.failed.connect(self._on_pola_failed)
        self._pola_worker = worker
        if self._pola_async and self._db_path:
            # Listwa w trakcie liczenia mówi „liczę", a pokazuje stan POPRZEDNI - pusta lista
            # udawałaby archiwum bez ani jednego pola.
            self.fields.set_stan("liczy")
            self._pola_thread = QThread(self)
            worker.moveToThread(self._pola_thread)
            self._pola_thread.started.connect(worker.run)
            worker.finished.connect(self._pola_thread.quit)
            self._pola_thread.finished.connect(self._sprzataj_pola)
            self._pola_thread.start()
        else:
            try:
                worker.run()               # inline: done/failed lecą direct = synchronicznie
            finally:
                self._pola_worker = None

    def _sprzataj_pola(self):
        """Koniec wątku pokrycia. ŚWIĘTA KOLEJNOŚĆ jak w `planner._cleanup_thread` (deadlock AB-BA
        GIL × ~QThread): worker.deleteLater → wait → thread.deleteLater. Wątek już zebrany przez
        `zatrzymaj_pola` nie ma tu czego sprzątać - wtedy wracamy od razu."""
        if self._pola_thread is None:
            return
        self._pola_worker.deleteLater()
        self._pola_thread.wait()
        self._pola_thread.deleteLater()
        self._pola_worker = None
        self._pola_thread = None
        if self._pola_ponow and not self._pola_stop:
            self._pola_ponow = False
            self._start_pola()

    def zatrzymaj_pola(self):
        """Widok znika (zamknięcie okna, przełączenie bazy): przerwij liczenie i ZBIERZ wątek, zanim
        rodzic go skasuje - `QThread` niszczony w biegu to twardy abort aplikacji. Wynik, który
        zdążył wyjść z wątku, trafia do kosza generacją, więc nie dotknie widoku ani zamkniętego
        połączenia. Przerwanie powtarzamy co 100 ms: `interrupt` trafiony w chwilę między dwoma
        zapytaniami workera nie działa, a kolejne łapie już zapytanie w locie. Idempotentne."""
        self._pola_stop = True
        self._pola_ponow = False
        self._pola_gen += 1
        if self._pola_thread is None:
            return
        self._pola_worker.request_cancel()
        self._pola_thread.quit()           # pętla wątku kończy się zaraz po `run()` (quit z góry)
        self._pola_worker.deleteLater()
        while not self._pola_thread.wait(100):
            self._pola_worker.request_cancel()
        self._pola_thread.deleteLater()
        self._pola_worker = None
        self._pola_thread = None

    @Slot(int, object, object)
    def _on_pola_done(self, gen, odcisk, pola):
        if gen != self._pola_gen:
            return                         # starszy niż ostatnia prośba - świeży bieg już zamówiony
        self._pola_odcisk = odcisk
        self.fields.set_stan(None)
        if pola is not None:               # None = karty bez zmian, listwa zostaje, jaka jest
            self._zastosuj_pola(pola)

    @Slot(int, str)
    def _on_pola_failed(self, gen, msg):
        if gen != self._pola_gen:
            return
        # Odcisk zostaje przy ostatnim ZASTOSOWANYM wyniku, więc kolejna prośba policzy od nowa.
        # Listwa trzyma stan poprzedni i mówi, że go nie odświeżyła.
        self.fields.set_stan("blad")
        self.status_message.emit(i18n.t("grid.fields.failed_status", msg=msg))

    def _zastosuj_pola(self, facets):
        """Pokrycie → panel Pól, keywordy filtra i makra. Zaznaczenia usera PRZEŻYWAJĄ przeliczenie:
        kolumny domyślne (6 najczęstszych keywordów spoza szumu strukturalnego) wybieramy tylko przy
        PIERWSZYM wyniku, potem odpadają jedynie kolumny, których keywordu nie ma już w żadnej karcie
        (bez tego zostałaby kolumna bez pola do jej odznaczenia)."""
        pierwszy = self._pola is None
        self._pola = facets
        self._all_keywords = [f["keyword"] for f in facets]
        if pierwszy and not self._columns:     # puste kolumny PÓŹNIEJ to wybór człowieka, nie brak
            kolumny = [f["keyword"] for f in facets if f["keyword"] not in STRUCT_NOISE][:6]
        else:
            znane = set(self._all_keywords)
            kolumny = [c for c in self._columns if c in znane]
        zmiana = kolumny != self._columns
        self._columns = kolumny
        self._wypelnij_pola()
        self.filter_panel.set_keywords(self._all_keywords)
        self.macro_bar.set_keywords(self._all_keywords)
        if zmiana and self._zbudowany:
            self.refresh()                 # model tabeli niesie kolumny - bez tego zostałyby stare

    def _wypelnij_pola(self):
        """Lista Pól z OSTATNIEGO pokrycia i bieżących kolumn. Szum strukturalny na DÓŁ (stabilnie
        w obrębie grup - pokrycie zachowane), P3-6. Bez pokrycia (pierwszy wynik jeszcze w drodze)
        nie ma czego pokazać - zaznaczenia odda `_zastosuj_pola`, czytając `_columns`."""
        if self._pola is None:
            return
        ordered = sorted(self._pola, key=lambda f: f["keyword"] in STRUCT_NOISE)
        self.fields.load(ordered, set(self._columns))

    def _odbuduj_perspektywy(self):
        # perspektywy: presety (kod) + zapisane w BAZIE (I-1)
        # POZYCJA PRZEŻYWA ODBUDOWĘ LISTY (bliźniak BP-5 w `_load_facets`): `clear()` zostawiał indeks
        # 0, a gospodarz woła tę metodę z `refresh()` po każdym przebiegu Dostawy - combo mówiło wtedy
        # „Przegląd" nad zbiorem z trimem. Wracamy na tę samą pozycję PO DANYCH i bez sygnału, bo stan
        # się nie zmienił. Pozycji, której już nie ma, tu nie zgadujemy: rozstrzyga właściciel
        # etykiety na końcu `_refresh`.
        biezaca = self.combo_persp.currentData()
        self.combo_persp.blockSignals(True)
        self.combo_persp.clear()
        for name in PRESETS:
            self.combo_persp.addItem(i18n.t(_PRESET_LABELS[name]), ("preset", name))
        for name, spec in self._saved_perspectives():
            # Wiersz, którego nie umiemy zastosować (`spec is None` — stary `sql_text` z 0013),
            # ZOSTAJE NA LIŚCIE i mówi to wprost. Ukrycie go byłoby zniknięciem cudzej pracy bez
            # słowa; wybór kończy się statusem, nie pustym filtrem.
            label = f"★ {name}" if spec is not None else f"★ {name} ⚠"
            self.combo_persp.addItem(label, ("saved", name))
        for i in range(self.combo_persp.count()):
            if self.combo_persp.itemData(i) == biezaca:
                self.combo_persp.setCurrentIndex(i)
                break
        self.combo_persp.blockSignals(False)

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _saved_perspectives(self):
        """Perspektywy z BAZY — `[(nazwa, spec|None), …]`. Rejestru już nie czytamy: to, co w nim
        było, wciągnął jednorazowy import przy budowie widoku."""
        return queries.perspectives(self.con)

    def _import_settings_perspectives(self):
        """JEDNORAZOWY, IDEMPOTENTNY import perspektyw z rejestru użytkownika do bazy (I-1).

        Wydanie publiczne zapisywało je w `QSettings` (D-B), więc przeniesienie kanonu do bazy bez
        tego kroku skasowałoby użytkownikom nazwane widoki — regresja, nie sprzątanie (FORWARD).
        Rejestru NIE czyścimy: koszt jest zerowy, a zostawiona kopia ratuje kogoś, kto wróci na
        starsze wydanie. Powtórzenie importu jest darmowe, bo `repo.save_perspective` przy
        identycznej treści nie pisze i nie emituje eventu — dlatego nie ma tu flagi „już zrobione",
        która i tak nie przeżyłaby przesiadki na drugą maszynę.

        Nazwa ISTNIEJĄCA W BAZIE wygrywa z rejestrową: baza jest teraz kanonem, a import ma
        dowieźć to, czego w niej nie ma, nie cofać czyjegoś zapisu do stanu sprzed przesiadki."""
        raw = self._settings().value("grid/perspectives", "{}")
        try:
            store = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(store, dict) or not store:
            return
        znane = {name for name, _spec in queries.perspectives(self.con)}
        for name, spec in store.items():
            if name not in znane and isinstance(spec, dict):
                repo.save_perspective(self.con, name=name, spec=spec, now=self._now())

    def _on_perspective(self):
        data = self.combo_persp.currentData()
        if not data:
            return
        kind, name = data
        spec = self._spec_pozycji(data)
        if spec is None:
            # Perspektywa jest, ale nie umiemy jej zastosować (stary `sql_text` z migracji 0013).
            # MÓWIMY to wprost: zastosowanie pustego spec-a zdjęłoby filtr i wyglądałoby na
            # „perspektywa pokazuje wszystko", czyli cichy fałsz zamiast pytania.
            if kind == "saved":
                self.status_message.emit(i18n.t("grid.persp.unreadable", name=name))
            return
        for atrybut, _ in _TRIMY:
            setattr(self, atrybut, bool(spec.get(_klucz_spec(atrybut))))
        self._filter_tree = spec.get("filter")
        # F4R#2: stan facetów resetowany dla KAŻDEJ perspektywy (preset ORAZ zapisana) — perspektywa
        # definiuje CAŁY zbiór; stara zapisana bez klucza "facets" MUSI zerować stan, inaczej facety
        # poprzedniego wyboru wyciekają w nowy zbiór. Rail przeładuje refresh() (set_data).
        self._facet_state = spec.get("facets") or facet_model.empty_state()
        self.filter_panel.set_tree(self._filter_tree)   # panel odbija filtr perspektywy (P3-3);
        # set_tree dostaje TYLKO advanced — facety NIGDY nie idą w płaski panel (nota R2, P3-3 wyżej)
        gb = spec.get("group_by")
        idx = self.combo_group.findData(gb)
        self.combo_group.blockSignals(True)
        self.combo_group.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_group.blockSignals(False)
        if "columns" in spec:
            # Zaznaczenia z OSTATNIEGO pokrycia, nie z nowego zapytania: przełączenie perspektywy
            # liczyło tu pokrycie całego archiwum na wątku GUI (sekundy na żywej bazie), choć
            # zmienia wyłącznie to, które pola są zaznaczone.
            self._columns = list(spec["columns"])
            self._wypelnij_pola()
        self.refresh()
        # Perspektywa izolacji zapisu podaje gest, który ją opróżnia: gesty mieszkają w menu
        # prawego kliku (nie na pasku zbioru), a menu nie widać, dopóki się go nie otworzy.
        # Recepta PO `refresh()`, bo raport odświeżenia gasi receptę poprzedniego gestu.
        recepta = next((k for a, k in _RECEPTY_ZAPISU.items() if getattr(self, a)), None)
        if recepta is not None and self._frame_ids:
            self.status_recipe.emit(i18n.t(
                recepta, finish=i18n.t("grid.inplace.finish"),
                restore=i18n.t("grid.inplace.restore"), release=i18n.t("grid.inplace.release")))

    def apply_object_facet(self, pairs):
        """Ustaw zbiór na WSKAZANE obiekty — publiczny seam dla wejść spoza widoku (T5e: „Pokaż
        klatki celu" z planera, D-0731-7). `pairs` = `[(object_id, canon), …]`; wiele par, bo jeden
        cel katalogu bywa w archiwum pod kilkoma nazwami (`IC410` ORAZ `LBN807`) i most ma pokazać
        SUMĘ klatek.

        Reużywa ISTNIEJĄCY facet Obiekt (liść `rel_object` + `facet_model.compose`) zamiast składać
        drzewo filtra po swojemu — druga ścieżka składania złamałaby SPOT i rozjechałaby się
        z cyklem facetów przy pierwszej zmianie. Perspektywa wraca do pełnej (zbiór definiuje
        wejście, nie poprzedni widok), advanced-filtr znika — jak przy każdej perspektywie.

        ETYKIETA IDZIE ZA ZBIOREM (bliźniak BP-5, potwierdzony testem): flagi i filtr były tu zerowane
        od początku, ale lista perspektyw zostawała, więc z „Duplikatów" most pokazywał klatki celu
        pod etykietą „Duplikaty". Rozstrzyga właściciel etykiety na końcu `_refresh`, jak po każdym
        przeładowaniu; facet mostu dopasowania nie blokuje, bo jest zawężeniem W RAMACH perspektywy
        (`_stan_zgodny_z`).

        ZAZNACZENIE MUSI BYĆ WIDOCZNE: listwa domyślnie odtwarza pozycję scrolla (słusznie dla kliku
        W listwie), więc wejście z zewnątrz zostawiało `✓` poza viewportem — zmierzone: pozycja 36
        z 48 przy scrollu 0. Stąd JEDNORAZOWY `_reveal_facet`, konsumowany przez najbliższe
        przeładowanie listwy."""
        self._zeruj_flagi()
        self._filter_tree = None
        self.filter_panel.set_tree(None)
        self._facet_state = {"object": {"in": [[oid, canon] for oid, canon in pairs]}} \
            if pairs else facet_model.empty_state()
        self._reveal_facet = ("object", pairs[0][0]) if pairs else None
        self.refresh()

    def apply_perspective(self, name):
        """Ustaw perspektywę PO NAZWIE — publiczny seam dla wejść spoza widoku (F5: klik w zadanie
        „Duplikaty" w Porządkach; R#14 — duplikatów NIE wyraża drzewo filtra, jedyna droga to
        mechanizm perspektyw). Presety iterowane pierwsze w combo, więc kolizja nazwy z zapisaną
        rozstrzyga się na preset. Pozycja już bieżąca → `_on_perspective()` wprost (klik w zadanie =
        ZAWSZE czysta perspektywa, nie no-op nad facetami usera). Nieznana nazwa → status."""
        for i in range(self.combo_persp.count()):
            data = self.combo_persp.itemData(i)
            if data and data[1] == name:
                if i == self.combo_persp.currentIndex():
                    self._on_perspective()
                else:
                    self.combo_persp.setCurrentIndex(i)   # currentIndexChanged → _on_perspective
                return
        self.status_message.emit(i18n.t("grid.persp.unknown", name=name))

    def _load_saved(self, name):
        return dict(self._saved_perspectives()).get(name)

    def _spec_pozycji(self, data):
        """Definicja pozycji listy perspektyw - `data` = `(rodzaj, nazwa)` z `itemData`. Preset czyta
        się z kodu, zapisana z BAZY; `None` = pozycja, której nie umiemy zastosować (stary `sql_text`).
        Jedno miejsce, bo pytają o to dwaj: przełączenie perspektywy i właściciel jej etykiety."""
        kind, name = data
        return PRESETS.get(name) if kind == "preset" else self._load_saved(name)

    def _stan_zgodny_z(self, spec):
        """Czy ZBIÓR widoku jest tym, który definiuje perspektywa `spec` (BP-5).

        Definicję zbioru niosą trzy rzeczy: flagi `only_*`, filtr zaawansowany i facety. Grupowanie
        i kolumny zmieniają WYGLĄD zbioru, nie jego skład, więc nie są porównywane.

        Flagi i filtr zgadzają się DOKŁADNIE. Facety perspektywy muszą w stanie STAĆ, ale stan może
        mieć ich więcej: facet dołożony ponad definicję (klik w listwie, most planera) jest zawężeniem
        W RAMACH perspektywy, nie jej zmianą. Ta jedna reguła rozstrzyga obu wołających bez rozróżniania
        ich: preset (bez facetów) pasuje do stanu z facetem mostu, a zapisana perspektywa z facetem
        przestaje pasować, gdy „× Wyczyść zbiór" ten facet zdjął.

        Flagi biorą skład z `_TRIMY` (BP-4), a spec niesie je bez podkreślnika (`only_dups` ↔
        `_only_dups`) - konwencja pinowana bramką `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`."""
        flagi_spec = {atrybut for atrybut, _ in _TRIMY if spec.get(_klucz_spec(atrybut))}
        flagi_stanu = {atrybut for atrybut, _ in _TRIMY if getattr(self, atrybut)}
        if flagi_spec != flagi_stanu or spec.get("filter") != self._filter_tree:
            return False
        return all(self._facet_state.get(facet) == wybor
                   for facet, wybor in (spec.get("facets") or {}).items())

    def _etykieta_perspektywy_za_stanem(self):
        """JEDEN WŁAŚCICIEL ETYKIETY STANU (BP-5): gdy zbiór przestał być tym, który definiuje bieżąca
        pozycja listy perspektyw, lista przeskakuje na PRESET, którego definicja się ze stanem zgadza.

        WOŁAJĄCY JEST JEDEN: `_refresh`, na końcu KAŻDEGO przeładowania - etykieta jest pochodną
        stanu (BP-5 domknięty w `_refresh`). Trzy jawne wywołania przy gestach („× Wyczyść zbiór",
        zmiana filtra z panelu, most planera) przegapiły czwartą drogę: klik w listwie facetów
        zostawiał „★ Lighty" nad dopełnieniem jej definicji. Gesty zdejmujące część definicji bez
        przełączania perspektywy flag nie tykają, więc z trimem trafiamy w preset Z TĄ FLAGĄ
        („Duplikaty" zostają „Duplikatami"), a bez trimu w `_PRESET_CZYSTY`. Dosłowne „zawsze
        Przegląd" kłamałoby od drugiej strony: duplikaty pod etykietą perspektywy bez zawężenia.

        Przeładowanie po `_on_perspective` kończy się wczesnym powrotem - stan jest wtedy z definicji
        tej pozycji. `_save_perspective` nie przeładowuje (stan == właśnie zapisany, pozycję wybiera
        sam). Pozycja „★ X ⚠" (spec `None`) nie ma definicji do porównania, więc najbliższe
        przeładowanie oddaje etykietę presetowi zgodnemu ze stanem.

        BEZ SYGNAŁU: stan jest już właściwy, a `_on_perspective` przepisałby grupowanie z presetu
        (i kolumny, gdy spec je niesie) i przeładował zbiór drugi raz. Kandydatami są wyłącznie
        presety - nazwa zapisana przez człowieka nie jest nasza do zgadywania. Brak dopasowania
        (dwie flagi naraz, możliwe tylko w specyfikacji spoza GUI - `_save_perspective` bierze flagi
        ze stanu, a preset niesie najwyżej jedną) zostawia etykietę: lepiej nieprecyzyjna nazwa niż
        wymyślona."""
        data = self.combo_persp.currentData()
        if data:
            spec = self._spec_pozycji(data)
            if spec is not None and self._stan_zgodny_z(spec):
                return
        for i in range(self.combo_persp.count()):
            kandydat = self.combo_persp.itemData(i)
            if kandydat and kandydat[0] == "preset" and self._stan_zgodny_z(PRESETS[kandydat[1]]):
                self.combo_persp.blockSignals(True)
                self.combo_persp.setCurrentIndex(i)
                self.combo_persp.blockSignals(False)
                return

    def _warunki_nowszej_wersji_do_przeniesienia(self, name):
        """Klucze spec-a, których ten build nie zna, a które zapis pod nazwą `name` ma PRZENIEŚĆ
        (D-V-9f, druga połowa) - do scalenia z nowym spec-iem, zwykle puste.

        Spec składany jest ze STANU widoku, a stan zna tylko to, co ten build umie. Bez tego członu
        ponowny zapis perspektywy przyjechanej z nowszej wersji kasował po cichu jej warunek:
        pierwsza połowa D-V-9f ostrzegała na pasku, a zapis i tak go gubił - i to w bazie, czyli
        także dla nowszego wydania, które ten warunek umiało zastosować.

        REGUŁA: przenosimy wtedy i tylko wtedy, gdy zapis NADPISUJE TĘ PERSPEKTYWĘ, KTÓRĄ WIDOK
        POKAZUJE - pozycja listy to `("saved", name)`, a zbiór widoku jest wciąż jej zbiorem
        (`_stan_zgodny_z`, ta sama reguła, którą właściciel etykiety decyduje, czy widok jest jeszcze
        tą perspektywą). Tylko wtedy wiemy, że człowiek zapisuje „to samo, może z poprawką", a nie
        coś innego pod starą nazwą. Zapis pod NOWĄ nazwą niesie wyłącznie to, co widok zna: ten
        build nie umie zastosować obcego warunku, więc nowa perspektywa odziedziczyłaby zawężenie,
        którego nikt tu nie widział ani nie wybrał. Tak samo nadpisanie INNEJ nazwy albo zapis
        z widoku, który przestał być tą perspektywą (np. po „× Wyczyść zbiór") - człowiek zastępuje
        wtedy zbiór świadomie, a doklejenie cudzego warunku zrobiłoby z niego trzeci, niczyj.

        Zwraca PARĘ `(klucze, facety)`, bo warunki nowszej wersji mieszkają w dwóch miejscach
        spec-a, a mechanizm ich cichego pominięcia jest ten sam (`_nieznane_warunki`):
          * klucze NAJWYŻSZEGO poziomu spoza `_ZNANE_KLUCZE_SPECU` - wszystkie, także puste
            (to zapis nowszego wydania, nie nasz do przycinania);
          * facety spoza `facet_model.FACETS`. Te leżą już w `self._facet_state`, bo
            `_on_perspective` przepisuje facety spec-a w całości - i właśnie dlatego wołający
            ODFILTROWUJE je ze stanu, a wraca je wyłącznie ta funkcja. Bez tego zapis pod nową
            nazwą przemycałby obcy facet ze stanu, łamiąc regułę wyżej.
        Format spec-a się nie zmienia: obie połowy wracają pod swoje dotychczasowe miejsca."""
        if self.combo_persp.currentData() != ("saved", name):
            return {}, {}
        spec = self._load_saved(name)
        if spec is None or not self._stan_zgodny_z(spec):
            return {}, {}
        facety = spec.get("facets") if isinstance(spec.get("facets"), dict) else {}
        return ({k: v for k, v in spec.items() if k not in _ZNANE_KLUCZE_SPECU},
                {f: g for f, g in facety.items() if f not in facet_model.FACETS})

    def _save_perspective(self):
        name, ok = QInputDialog.getText(self, i18n.t("grid.persp.save_title"), i18n.t("grid.persp.save_prompt"))
        if not ok or not name.strip():
            return
        name = name.strip()
        klucze_obce, facety_obce = self._warunki_nowszej_wersji_do_przeniesienia(name)
        spec = {
            "filter": self._filter_tree, "columns": self._columns,
            "group_by": self.combo_group.currentData(),
            # KAŻDA flaga, także fałszywa: jawne `False` mówi starszemu wydaniu „tu nic nie ma",
            # więc `_nieznane_warunki` po tamtej stronie go nie liczy (pusta wartość to nie warunek).
            **{_klucz_spec(atrybut): getattr(self, atrybut) for atrybut, _ in _TRIMY},
            # OSOBNO od "filter" (nota R2) - set_tree nigdy ich nie widzi. Ze stanu bierzemy tylko
            # facety, które ten build zna; obce wracają wyłącznie regułą przeniesienia (D-V-9f).
            "facets": {**{f: g for f, g in self._facet_state.items() if f in facet_model.FACETS},
                       **facety_obce},
            **klucze_obce,
        }
        # Zapis idzie do BAZY (I-1) — perspektywa jedzie z archiwum, nie z tą maszyną. Czasownik
        # z klingi rozstrzyga KOMUNIKAT: nazwa przyjechana z drugiej maszyny z inną treścią zostaje
        # NADPISANA, a „zapisano" bez słowa o tym mówiłoby o czymś, co się nie stało (F9).
        _id, verb = repo.save_perspective(self.con, name=name, spec=spec, now=self._now())
        # Sama lista perspektyw: zapis nie rusza kart, a pełne `_load_facets` liczyło tu dawniej
        # pokrycie całego archiwum i przy okazji zerowało kolumny do domyślnych - zaraz po tym,
        # jak człowiek zapisał je w perspektywie.
        self._odbuduj_perspektywy()
        # F4R2#6 (pre-existing, ścieżka tykana przez F4): rebuild combo pod blockSignals zostawiał
        # indeks 0 („Przegląd") przy żywym stanie świeżo zapisanej perspektywy — etykieta kłamała.
        # Re-select zapisanej, nadal bez emisji (_on_perspective nie ma czego przeładowywać:
        # stan == właśnie zapisany).
        self.combo_persp.blockSignals(True)
        for i in range(self.combo_persp.count()):
            if self.combo_persp.itemData(i) == ("saved", name):
                self.combo_persp.setCurrentIndex(i)
                break
        self.combo_persp.blockSignals(False)
        self.status_message.emit(i18n.t(
            "grid.persp.overwritten" if verb == "perspective.overwritten" else "grid.persp.saved",
            name=name))

    def _open_projection(self):
        """Otwórz dialog projekcji dla WIDOCZNEJ perspektywy (`self._frame_ids` — po filtrach dups/review,
        to co user widzi; doktryna §5). Modal TYLKO na potwierdzenie eksportu; cała mutacja plików w
        Qt-wolnej klindze `projection` przez dialog. Pusty grid → szczery status, bez pustego dialogu."""
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.proj.no_frames"))
            return
        dlg = ProjectionDialog(self.con, self._frame_ids, now_fn=self._now,
                               perspektywa=self.combo_persp.currentText(), parent=self)
        dlg.exec()
        # Wydanie zostawia ślad W APLIKACJI (wiz P-C #4): przed tym jedynym zapisem był
        # `_PROJEKCJA.json` w celu, więc po zamknięciu dialogu okno nie wiedziało nic o tym,
        # co przed chwilą wyjechało na stół. Zdanie składa dialog (tam liczby są świeże).
        if dlg.summary:
            self.status_message.emit(dlg.summary)

    # ---- oś OBIEKTU na zaznaczeniu (S2b, D-OW-6) ----

    def _object_gesture_ids(self):
        """Cel OBU gestów: WYŁĄCZNIE zaznaczenie (§4/14c-a). Fallback „to, co widoczne" jest dla
        zapisu osi ZAKAZANY — przy 800 widocznych klatkach chybione kliknięcie i zamierzony gest
        wyglądają identycznie. Pusty ⇒ status i zero zapisu; to druga linia obrony za wygaszeniem,
        bo bramka woła SLOT, nie przycisk (klik w wyszarzony przycisk przeszedłby trywialnie)."""
        ids = [r["frame_id"] for r in self._selected_data_rows()]
        if not ids:
            self.status_message.emit(i18n.t("grid.sel.object_empty"))
        return ids

    def _po_gescie_osi(self, klucz, gest, *, odwracalny=False,
                       canons_key="grid.sel.object_canons",
                       nothing_key="grid.sel.object_skip_nothing", **kw):
        """Wspólny ogon WSZYSTKICH gestów osi: zdanie z ROZBICIEM per fakt + odświeżenie CZTERECH
        powierzchni + ZACHOWANIE ZAZNACZENIA.

        Liczniki idą osobno, bo znaczą co innego: „kalibracja" to ochrona, która zadziałała,
        a „zmieniły się w międzyczasie" to ostrzeżenie, że stan uciekł. Jedno „pominięto N" kazałoby
        człowiekowi zgadywać, którą z tych dwóch rzeczy właśnie zobaczył.

        ZAZNACZENIE PRZEŻYWA GEST (R-S2b-3, człon pierwszy). `refresh()` przebudowuje model
        (`beginResetModel`), więc zaznaczenie 120 klatek szło do zera — a razem z nim JEDYNY tani
        cel gestu naprawczego. Zmierzone przez wizytację: odtworzenie stanu sprzed pomyłki
        kosztowało 6-8 interakcji plus pamięć człowieka o tym, co tam stało."""
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        recepty = []                    # człony „co teraz zrobić" — własny nośnik paska (FH-2)
        msg = i18n.t(klucz, assigned=gest.assigned, total=gest.assigned + gest.skipped, **kw)
        # Rozbicie pominięć i gotowe obrazy składa JEDEN dom (`zdanie_pominiec`), wspólny z dwiema
        # powierzchniami osi w `gui.app` - `nothing_key` idzie za gestem (FC-6), jak `canons_key`.
        msg += zdanie_pominiec(gest, nothing_key=nothing_key)
        # KANONY OSOBNYM CZŁONEM, nie placeholderem w zdaniu bazowym (R-S2b-3, człon drugi).
        # Zdanie bazowe ma dwóch wołających o RÓŻNYCH kwargach, więc `{canons}` w nim byłoby
        # `KeyError`-em u tego, który go nie poda — a bramka i18n pyta o komplet PL/EN i istnienie
        # klucza, nie o parytet placeholderów z wołającym. Osobny człon milczy przy zerze;
        # placeholder zostawiłby wiszący dwukropek nad pustką. Nadanie go nie dokłada: tam kanon
        # jest w zdaniu bazowym, bo user sam go przed chwilą wybrał.
        if gest.canons and "canon" not in kw:
            msg += i18n.t(canons_key, canons=_lista_kanonow(gest.canons))
        poza = 0
        if gest.assigned:
            # CZTERY POWIERZCHNIE: wiersze gridu, facety (Obiekt zmienił zawartość), licznik/pasek
            # oraz kolejka przeglądu w oknie osi — ta ostatnia przez sygnał, bo nie jest nasza.
            self.refresh()
            wrocilo = self._przywroc_zaznaczenie(zaznaczone)
            self.object_axis_changed.emit()
            self.stan_porzadkow_changed.emit()     # plakietka Porządków (patrz definicja sygnału)
            # CEL GESTU BYWA WYPCHNIĘTY Z WIDOKU PRZEZ SAM GEST (FC-2) - i to nie jest przypadek
            # brzegowy: przy facecie `Obiekt=NGC3623` cofnięcie zostawia widok 43 → 0 klatek
            # (zmierzone na kopii żywej bazy), bo `facet_objects` JOIN-uje po `f.object_id`,
            # a nagrobek z niego wypada. Ta sama figura od drugiej strony jest przy przywracaniu
            # TYPOWA: klatka z obiektem nie należy już do perspektywy „Do przeglądu".
            # Liczba jest POMIAREM (ile z zaznaczonych wróciło na przebudowany model), nie
            # domysłem z liczników klingi - a recepta schodzi od stanu zawężenia, żeby nie
            # obiecywać kliknięcia, które akurat tego zbioru nie odsłoni.
            poza = len(zaznaczone) - wrocilo
            fakt, recepta_widoku = self._czlon_poza_widokiem(poza, zaznaczone)
            msg += fakt
            recepty.append(recepta_widoku)
        # RECEPTA ODWRACALNOŚCI SKŁADA SIĘ TUTAJ, NIE U WOŁAJĄCEGO (bramka pakietu, zarzut
        # blokujący) - bo jej treść zależy od tego, czy cel został na ekranie, a to wie dopiero
        # ten kod. Gdy klatki wyszły z widoku, zaznaczenie po `refresh()` jest puste, więc
        # `_sync_object_actions` gasi całą kontrolkę „Obiekt": zdanie „przywrócisz: Obiekt → …"
        # wskazywałoby wtedy napis wyszarzony w tej samej chwili. Wariant „potem" ustawia oba
        # gesty w kolejności, w której da się je WYKONAĆ.
        if odwracalny and gest.assigned:
            recepty.append(
                i18n.t("grid.sel.object_clear_undo_after" if poza else "grid.sel.object_clear_undo",
                       menu=i18n.t("grid.sel.object"), action=i18n.t("grid.sel.object_restore")))
        # ZDANIE IDZIE PO ODŚWIEŻENIU, nie przed (adjudykacja recenzji S2b). `refresh()` kończy się
        # własnym `status_message` („Grid: N klatek…"), a odbiornikiem jest jeden `showMessage`
        # paska stanu — emisja przed odświeżeniem ginęła w tym samym obrocie pętli. Skutek był
        # dokładnie odwrotny do zamierzonego: rozbicie per fakt user widział WYŁĄCZNIE wtedy, gdy
        # gest niczego nie zapisał (bo wtedy `refresh()` nie leci), a po udanym zapisie — nigdy.
        # KAŻDY FAKT GESTU JEDZIE W TYM JEDNYM ZDANIU, nie drugą emisją. Ta sama pułapka, co wyżej,
        # tylko od drugiej strony: dwa `emit` w jednym obrocie pętli trafiają w jeden `showMessage`,
        # więc drugie wymazuje pierwsze (bramka pakietu 0810). Dlatego nagrobek bez pamięci jest
        # członem rozbicia (FC-6), a nie osobnym zdaniem doklejanym przez wołającego.
        self.status_message.emit(msg)
        self.status_recipe.emit(_zlacz_recepty(recepty))

    def _czlon_poza_widokiem(self, poza, cel=None):
        """Człon „poza widokiem: N" ORAZ jego recepta - WSPÓLNY DLA OBU OSI zaznaczenia (FC-2).

        Obie osie mają ten sam problem i to nie jest analogia: na osi obiektu gest wypycha cel przy
        aktywnym facecie „Obiekt", a na osi żywotności klatki wypchnięcie jest wręcz REGUŁĄ, bo
        wycofanie zdejmuje klatkę z kubełków roboczych. Dwie kopie tej frazy rozjechałyby się przy
        pierwszej poprawce, a trzecia oś dołożyłaby trzecią (bramka pakietu, soczewka repo).

        ZWRACA PARĘ `(fakt, recepta)`, bo te dwa człony jadą na pasek OSOBNYMI kanałami (FH-2):
        „poza widokiem: N" jest POMIAREM i należy do raportu, a „odsłoni je …" jest INSTRUKCJĄ
        i dostaje własny widżet, którego długość raportu już nie zdmuchnie.

        Para pustych łańcuchów przy zerze, żeby wołający nie musiał pytać - milczenie jest tu
        poprawną odpowiedzią: zdanie o zerze klatek poza widokiem mówiłoby o czymś, co się nie
        stało."""
        if not poza:
            return "", ""
        # …i zapamiętaj CEL, żeby recepta odsłaniająca oddała go w zaznaczeniu (`refresh`).
        # Bez tego odsłonięcie jest tylko połową drogi: zbiór wraca, a klatki gestu toną w nim
        # bez śladu - zmierzone firsthandem na 43 klatkach w widoku 16 901 wierszy.
        self._cel_gestu = list(cel or [])
        fakt = i18n.t("grid.sel.out_of_view", n=poza)
        recepta = self._recepta_powrotu_do_widoku()
        if recepta is None:
            return fakt, ""
        klucz, kwargi = recepta
        return fakt, i18n.t(klucz, **kwargi)

    def _rodzaj_recepty_powrotu(self, *, cel):
        """Którym JEDNYM gestem odsłonić to, czego nie widać - ze STANU zawężenia, liczone w chwili
        pytania, nie zapamiętane w `refresh()` (FC-2, BP-4). Zwraca RODZAJ recepty (`_POWROT_*`)
        albo `None`, gdy nie ma czego doradzić.

        JEDYNY WŁAŚCICIEL WYBORU GESTU, Z JAWNYM CELEM, bo „co odsłonić" to dwa pytania (FH-4,
        poprawka po firsthandzie). `_CEL_GEST` pyta o klatki wypchnięte gestem osi (recepta paska),
        `_CEL_WIDOK` o klatki bieżącego widoku (pusty stan). Każda powierzchnia mapuje rodzaj na
        WŁASNE brzmienie, ale żadna nie wybiera gestu sama - do FH-4 pusty stan miał własny, ogólny
        tekst i po geście przy facecie przeczył zdaniu, które pasek podał pięć sekund wcześniej.

        RECEPTA MUSI BYĆ WYKONALNA, i to jest tu jedyne kryterium. „× Wyczyść zbiór" zdejmuje
        facety i filtr, ale flag perspektywy NIE tyka (`_on_clear_selection` - są własnością
        perspektywy), więc przy aktywnym trimie odsłania WYŁĄCZNIE klatki tej perspektywy. Repo
        dostało już tę klasę raz, przy komunikacie o konflikcie („zawęź do dwóch", gdy zawężenie
        nic nie zmieniało). Stąd różne odpowiedzi przy trimie:
        - cel „gest": pierwszeństwo ma PERSPEKTYWA, bo klatka, której gest zmienił stan, wypadła
          z SAMEJ perspektywy (przypisany obiekt wyrzuca z „Do przeglądu") - odsłoni ją tylko inna;
        - cel „widok": gdy perspektywa MA klatki, a zbiór je zasłania, recepta to „× Wyczyść
          zbiór" i perspektywa zostaje. Pierwsza wersja FH-4 pytała tu o klatki gestu i wyrzucała
          z kolejki (firsthand: „Do przeglądu" z 8 czekającymi klatkami prowadziło na „Przegląd"
          z 16 901). Gdy populacja trimu jest pusta, zbioru czyścić nie ma po co.

        GDY WYGRYWA PERSPEKTYWA, JEDEN GEST ODSŁANIA WSZYSTKO: przełączenie zeruje TAKŻE facety
        i filtr (`_on_perspective`), a „Przegląd" nie niesie ani trimu, ani filtra; wariant „zdejmij
        oba" kazałby zrobić dwa gesty tam, gdzie wystarcza jeden (bramka pakietu, zarzut
        o nadmiarową receptę). Bez trimu wygrywa gest WĘŻSZY: przycisk zbioru.

        `cel` JEST KEYWORD-ONLY z tego samego powodu co w `_on_object_name`: wykonawca wisi na
        `clicked`, które niesie `checked: bool`. Cel spoza dwóch znanych to błąd wołającego (EXPECT),
        nie trzecia, cicha gałąź."""
        if cel not in (_CEL_GEST, _CEL_WIDOK):
            raise ValueError(f"nieznany cel recepty powrotu: {cel!r}")
        trim, zbior = self._trim_aktywny(), self._zbior_zawezony()
        if cel == _CEL_WIDOK and trim and zbior and self._populacja_trimu():
            return _POWROT_ZBIOR
        if trim:
            return _POWROT_PERSPEKTYWA
        if zbior:
            return _POWROT_ZBIOR
        return None

    def _populacja_trimu(self):
        """Klatki, które perspektywa wpuszcza BEZ zawężenia zbioru - przecięcie aktywnych trimów,
        składane z `_TRIMY` (BP-4: skład rodziny ma jedno miejsce) i liczone w chwili pytania.
        `set.intersection` oddaje NOWY set, więc zbiory zapytań nie są przycinane w miejscu.

        Pytanie ma sens wyłącznie przy aktywnym trimie - bez niego populacją jest całe uniwersum,
        a tego ta metoda nie liczy. Wołanie bez trimu to błąd wołającego (EXPECT)."""
        trimy = [getattr(queries, nazwa)(self.con) for atrybut, nazwa in _TRIMY
                 if getattr(self, atrybut)]
        if not trimy:
            raise ValueError("populacja trimu bez aktywnego trimu")
        return set.intersection(*trimy)

    def _recepta_powrotu_do_widoku(self):
        """Brzmienie recepty na PASKU STANU - `(klucz, kwargi)` albo `None`, gdy nie ma czego doradzić.
        Pasek mówi o klatkach wypchniętych gestem („odsłoni je …"), więc pyta decyzję o `_CEL_GEST`;
        pusty stan pyta tę samą metodę o `_CEL_WIDOK` i w trimie, który ma klatki, dostaje inną,
        też prawdziwą odpowiedź (FH-4, poprawka po firsthandzie). Brzmienie paska się przez to nie
        zmieniło. Recepta cytuje etykietę gestu z katalogu (nazwa presetu, napis przycisku zbioru),
        żeby zmiana napisu przenosiła się tu sama."""
        rodzaj = self._rodzaj_recepty_powrotu(cel=_CEL_GEST)
        if rodzaj == _POWROT_PERSPEKTYWA:
            return "grid.sel.out_of_view_persp", {"perspective": i18n.t(_PRESET_LABELS[_PRESET_CZYSTY])}
        if rodzaj == _POWROT_ZBIOR:
            return "grid.sel.out_of_view_set", {"action": i18n.t("grid.sel.clear_set")}
        return None

    def wykonaj_recepte_powrotu(self, *, cel):
        """WYKONAJ receptę powrotu dla podanego CELU - gest, który `_rodzaj_recepty_powrotu` wybiera
        w chwili kliknięcia, nie zapamiętany z chwili podania recepty (stan mógł się zmienić).

        JEDEN WYKONAWCA, CEL PODAJE WOŁAJĄCY (FH-4, poprawka po firsthandzie): przycisk pustego
        stanu pyta o `_CEL_WIDOK`, a przycisk recepty paska stanu zapyta o `_CEL_GEST`
        (TODO-DŁUG(FH-2e) w `app.py`) - tam zostaje już tylko podpięcie, bez kopii wyboru. `cel`
        jest keyword-only, więc `checked: bool` z `clicked` nie wpadnie w jego miejsce. Mechanizmy
        są dwa i różne: lista perspektyw (przez `apply_perspective`, więc pozycja listy idzie za
        stanem) i przycisk zbioru.

        Klatki ostatniego gestu osi wracają po wykonaniu SAME: oba gesty kończą się `refresh()`,
        który odkłada `_cel_gestu` w zaznaczeniu (FC-2) - bez tego odsłonięty zbiór topiłby je."""
        rodzaj = self._rodzaj_recepty_powrotu(cel=cel)
        if rodzaj == _POWROT_PERSPEKTYWA:
            self.apply_perspective(_PRESET_CZYSTY)
        elif rodzaj == _POWROT_ZBIOR:
            self._on_clear_selection()

    def _ustaw_pusty_stan(self, baza_ma_klatki):
        """Zdanie i gest PUSTEGO GRIDU (FH-4) - wołane z `_refresh`, gdy zbiór jest pusty.

        Pusta baza nie ma czego odsłaniać: zdanie kieruje po dostawę, przycisku nie ma (wiz F5 #8).
        Niepusta baza bierze wariant z PRZYCZYNY pustki - z decyzji recepty pytanej o `_CEL_WIDOK`
        (FH-4, poprawka po firsthandzie): zbiór zasłania klatki perspektywy → zdanie o zbiorze
        i „× Wyczyść zbiór" (perspektywa zostaje); perspektywa nie ma ani jednej klatki → zdanie
        o perspektywie i przejście na „Przegląd". Pasek pyta tę samą metodę o klatki GESTU, więc
        w trimie, który ma klatki, obie powierzchnie mówią co innego - i obie prawdę. Przycisk nosi
        nazwę gestu: przy zbiorze dosłownie napis przycisku paska zbioru, żeby gest miał jedną nazwę
        na całym ekranie. Brak recepty przy niepustej bazie jest dziś nieosiągalny (bez zawężenia
        widać wszystkie klatki), więc zostaje zdanie bez przycisku: przycisk bez gestu obiecywałby
        coś, czego nie ma.

        NIE woła `_czlon_poza_widokiem`: tamten zapamiętuje klatki gestu (`_cel_gestu`), a pusty
        stan powstaje także bez gestu - wybór brzmienia nie ma prawa ruszać stanu zaznaczenia."""
        if not baza_ma_klatki:
            zdanie, gest = _EMPTY_DB, ""
        else:
            rodzaj = self._rodzaj_recepty_powrotu(cel=_CEL_WIDOK)
            if rodzaj == _POWROT_PERSPEKTYWA:
                zdanie = _EMPTY_PERSP
                gest = i18n.t("grid.empty_persp_action", perspective=i18n.t(_PRESET_LABELS[_PRESET_CZYSTY]))
            elif rodzaj == _POWROT_ZBIOR:
                zdanie, gest = _EMPTY_FILTER, i18n.t("grid.sel.clear_set")
            else:
                zdanie, gest = _EMPTY_VIEW, ""
        self.empty.setText(i18n.t(zdanie))
        self.empty_btn.setText(gest)
        self.empty_btn.setVisible(bool(gest))

    def _przywroc_zaznaczenie(self, frame_ids):
        """Odłóż zaznaczenie po `frame_id` na PRZEBUDOWANYM modelu (R-S2b-3, człon pierwszy).

        PO `frame_id`, NIE PO NUMERZE WIERSZA — i to nie jest ostrożność: gest osi zmienia klucz
        sortu tej kolumny (`_object` bierze się z kanonu), a filtr perspektywy potrafi klatkę ze
        zbioru wyrzucić. Numer wiersza po `refresh()` wskazuje więc zupełnie inną klatkę.

        JEDNO WYWOŁANIE `select()`, NIGDY PĘTLA. Każde wywołanie emituje `selectionChanged`, a ten
        ciągnie `_update_count` → read-model osi (zmierzone 31 ms przy 16 648 klatkach). Pętla po
        zakresach wracałaby dokładnie do kwadratu, który zdjęło P-K (2 071 ms → 2 ms).

        ZAKRESY ŁAMIĄ SIĘ NA MARKERACH GRUP i to jest zmierzone falsyfikatorem, nie założone:
        `select()` na zakresie obejmującym wiersz NIESELEKTOWALNY wciąga go do `sm.selection()`
        (`selectedRows()` go odsiewa, ZAKRESY nie), a `_selected_data_rows` czyta właśnie zakresy.
        Bez łamania po geście podświetlałby się nagłówek grupy — wiersz, którego gest nie tknął.

        KADR IDZIE ZA ZAZNACZENIEM. Po `endResetModel` widok wraca na górę, więc zaznaczenie
        odłożone poprawnie byłoby NIEWIDOCZNE: user patrzy na pierwszy wiersz, a jego 120 klatek
        siedzi w połowie szesnastu tysięcy. `NoUpdate` przy `setCurrentIndex`, bo bieżąca komórka
        jest tu kotwicą dla Shift, a nie drugim, konkurencyjnym zaznaczeniem.

        Klatka, która po geście wypadła ze zbioru (perspektywa „Do przeglądu" pyta o `object_id
        IS NULL`, więc PRZYWRÓCONA klatka do niej nie należy), po prostu nie wraca — to uczciwe,
        bo jej na ekranie nie ma. Dla gestu przywracania jest to przypadek TYPOWY, nie brzegowy,
        i dlatego zdanie po geście musi być pełne: bywa jedynym potwierdzeniem.

        ZWRACA, ILE WIERSZY REALNIE ODŁOŻONO - bo dopiero różnica wobec celu mówi, ile klatek gest
        wypchnął z widoku (FC-2). Liczba jest tu darmowa (lista i tak powstaje), a policzona
        u wołającego wymagałaby drugiego przebiegu po modelu."""
        sm = self.table.selectionModel()
        if sm is None or not frame_ids:
            return 0
        chciane = set(frame_ids)
        numery = [i for i, row in enumerate(self.model._rows)
                  if isinstance(row, dict) and row.get("frame_id") in chciane
                  and "_group" not in row]
        if not numery:
            return 0
        ostatnia = self.model.columnCount() - 1
        sel = QItemSelection()
        start = prev = numery[0]
        for i in numery[1:] + [None]:
            if i != prev + 1:                       # koniec ciągu — także gdy przerwał go marker
                sel.select(self.model.index(start, 0), self.model.index(prev, ostatnia))
                start = i
            prev = i
        sm.select(sel, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        pierwszy = self.model.index(numery[0], 0)
        sm.setCurrentIndex(pierwszy, QItemSelectionModel.NoUpdate)
        self.table.scrollTo(pierwszy, QAbstractItemView.PositionAtCenter)
        return len(numery)

    def _on_object_name(self, *, preselect_canon=None):
        """„Przypisz obiekt…" ze Zbiorów: nadpisuje WYŁĄCZNIE źródła słabe, przy zamrożonym stanie
        okna. (Do R-S2b-11 pozycja nazywała się „Nazwij zaznaczenie…" — jeden z czterech czasowników
        na tę samą robotę.)

        `preselect_canon` niesie WYBÓR, KTÓRY JUŻ PADŁ w skrócie „ostatnio użyte" — okno otwiera
        się wtedy nie po to, żeby zapytać o nazwę, tylko żeby pokazać dysklozurę. Domyślne `None`
        zostawia drogę pozycji menu nietkniętą (tam wyboru jeszcze nie było).

        PARAMETR JEST KEYWORD-ONLY I TO NIE JEST GUST: ta metoda wisi na `QAction.triggered`,
        które emituje `checked: bool`, więc parametr pozycyjny łapałby `False` jako nazwę obiektu
        — cicho, bo pętla po bibliotece po prostu by go nie znalazła. Gwiazdka zamienia tę klasę
        pomyłki w błąd wywołania (EXPECT), a testem pinujemy, że sam sygnał wchodzi bez argumentu."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        stan = queries.selection_object_state(self.con, ids)
        if stan["conflict"]:
            # Dwa różne obiekty wśród klatek podlegających nadpisaniu ⇒ gest nie ma JEDNEGO
            # przedmiotu. Odmowa BEZ zapisu — częściowe wykonanie byłoby gorsze niż żadne, bo
            # user zobaczyłby „nazwano 30 z 80" i nie wiedział, które 30.
            # Liczba z READ-MODELU, nie literał: „2" było zaszyte, więc zaznaczenie z siedmioma
            # obiektami kazało zawęzić do dwóch, a po zawężeniu odmawiało tak samo — komunikat
            # o fałszywej liczbie jest receptą, której nie da się wykonać.
            self.status_message.emit(i18n.t("grid.sel.object_conflict", n=stan["conflict_n"]))
            return
        # LICZBA W OKNIE = ile gest realnie ruszy (`namable`), a nie ile zaznaczono: przycisk mówił
        # „Przypisz 8 klatek" i zapisywał 4, a przy realnym archiwum (większość lightów ma źródło
        # mocne) rozjazd jest regułą, nie wyjątkiem. Kontekst zaznaczenia idzie dalej, bo to okno
        # pyta wtedy o NADPISANIE cudzej nazwy i musi to powiedzieć zamiast zdania o kubełku RAW.
        # Zaznaczenie też bywa nagrobkiem — „Nazwij" jedzie `overwrite_weak=True`, więc gasi
        # werdykt tak samo, jak zapis z kubełka cofniętych. Liczba z read-modelu (`by_source`),
        # nie z osobnego zapytania: ten sam dict już wygasza kontrolkę.
        dlg = AssignObjectDialog(self.con, object_raw=None, frame_count=stan["namable"],
                                 selection=stan,
                                 cleared_n=stan["by_source"].get("user_cleared", 0),
                                 preselect_canon=preselect_canon, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        canon, catalog, kind, alias_norm = dlg.selected
        try:
            gest = repo.user_assign_object(
                self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                frame_ids=ids, now=self._now(), overwrite_weak=True,
                expected_object_id=stan["expected_object_id"])
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("grid.sel.object_name"), str(e))
            return
        self._po_gescie_osi("grid.sel.object_named", gest, canon=canon)

    def _sync_recent_objects(self):
        """Zasil skrót „ostatnio użyte" przed pokazaniem menu (R-S2b-12)."""
        self.sel_bar.set_recent_objects(queries.recent_hand_objects(self.con))

    def _on_object_recent(self, canon, catalog, kind):
        """Skrót „ostatnio użyte": ten sam zapis co „Przypisz obiekt…", z pominiętym WYBOREM.

        Wszystkie guardy zostają i to jest cała różnica między skrótem a obejściem: pusty cel,
        konflikt dwóch obiektów w zaznaczeniu, zamrożony `expected_object_id` i klucz aliasu liczony
        JEDNYM właścicielem (`assign_dialog.alias_key`). Pomijamy okno, nie bramki — inaczej skrót
        byłby drugą, słabszą ścieżką zapisu tej samej osi.

        `object_raw=None`, bo cel bierze się z ZAZNACZENIA, a nie z grupy o wspólnym zeznaniu —
        dokładnie jak w `_on_object_name`, którego to jest skrót.

        SKRÓT ODDAJE STER OKNU, GDY MA COŚ ZGASIĆ (bramka pakietu, zarzut 4). Bramki techniczne
        skrót miał komplet, ale gubił jedyną DYSKLOZURĘ: okno mówi, ile nagrobków ręki zgaśnie
        (`assign.cleared_warning`) i ile cudzych nazw nadpisze (`assign.selection_overwrite`).
        Kontrakt `AssignObjectDialog` stawia to zdanie na DRODZE KLIKNIĘCIA, nie w tooltipie —
        więc dwa kliknięcia nie mogą po cichu skasować werdyktu człowieka. Gdy nie ma czego gasić
        (zwykły przypadek: świeże klatki), skrót pisze wprost i zostaje przy obiecanych 2 gestach."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        stan = queries.selection_object_state(self.con, ids)
        if stan["conflict"]:
            self.status_message.emit(i18n.t("grid.sel.object_conflict", n=stan["conflict_n"]))
            return
        if stan["overwrite"] or stan["by_source"].get("user_cleared"):
            # …z WYBOREM, KTÓRY JUŻ PADŁ (firsthand 0810, znalezisko 3): okno pyta o zgodę na
            # zgaszenie werdyktu, a nie o nazwę — więc wybrany kanon jedzie z nim jako preselekcja.
            # Bez tego skrót kosztował 5 interakcji zamiast obiecanych 2, i to dokładnie tam, gdzie
            # naprawa z kolejki jest regułą (nagrobek albo źródło `path`). Dysklozura zostaje.
            return self._on_object_name(preselect_canon=canon)
        try:
            gest = repo.user_assign_object(
                self.con, alias_norm=assign_dialog.alias_key(None, canon), canon=canon,
                catalog=catalog, kind=kind, frame_ids=ids, now=self._now(), overwrite_weak=True,
                expected_object_id=stan["expected_object_id"])
        except ValueError as e:                # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("grid.sel.object_name"), str(e))
            return
        self._po_gescie_osi("grid.sel.object_named", gest, canon=canon)

    def _on_object_clear(self):
        """„Cofnij przypisanie": zdejmuje wyłącznie to, co postawiła ręka albo ścieżka.

        ZDANIE NIESIE DROGĘ POWROTU (FC-9). Odwracalność tego gestu jest w aplikacji od R-S2b-3,
        ale widać ją wyłącznie w tooltipie kontrolki („do przywrócenia: 46") i w pozycji menu za
        kliknięciem - czyli nigdzie w chwili, w której się przydaje. Człon idzie TYLKO po udanym
        zapisie: przy zerze mówiłby, jak cofnąć coś, co się nie stało. Etykiety cytujemy z KLUCZY
        i18n, nie literałem - recepta wskazująca napis, którego na ekranie nie ma, jest gorsza
        niż jej brak (klasa pilnowana bramką „surowego klucza").

        SAMĄ RECEPTĘ SKŁADA `_po_gescie_osi`, a ten gest tylko deklaruje, że jest odwracalny -
        bo jej treść zależy od tego, czy cel gestu został na ekranie (tam jest ten pomiar)."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        gest = repo.clear_object_assignment(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_osi("grid.sel.object_cleared", gest, odwracalny=True)

    def _on_object_restore(self):
        """„Przywróć cofnięte przypisanie" — DROGA POWROTU z masowego cofnięcia (R-S2b-3).

        Dług nazywał trzy człony i to jest ten trzeci: po pomyłkowym geście na 120 klatkach
        odtworzenie stanu sprzed niej kosztowało 6-8 interakcji PLUS pamięć człowieka o tym, co
        tam stało. Od 0017 pamięta to baza, więc naprawa kosztuje JEDEN gest — i składa się
        z członem pierwszym: zaznaczenie po cofnięciu ZOSTAJE, więc cel jest już wskazany.

        CEL = ZAZNACZENIE, jak obie sąsiednie pozycje menu. Wariant „cofnij OSTATNIĄ partię"
        (z dziennika) odpadł nie z powodu ceny: menu „Obiekt ▾" ma JEDNĄ regułę celu („ta akcja
        pisze wyłącznie po zaznaczeniu") i pozycja z własną regułą pisałaby po klatkach, których
        na ekranie nie widać. Cel z zaznaczenia jest przy tym OGÓLNIEJSZY — sięga też nagrobka
        sprzed tygodnia, nie tylko tego z ostatniej minuty.

        PISZE JEDNA KLINGA OSI (`repo.user_assign_object`, D-OW-2/B), transakcja per GRUPA, bo
        klinga przyjmuje jeden kanon na wywołanie, a masowe cofnięcie obejmuje bywa kilka obiektów.
        Wzorzec: `ConfirmPathObjectsDialog._on_confirm` (pętla klingi per nazwa, faza zajętości).

        `expected_source='user_cleared'` to GUARD DRYFU WEWNĄTRZ TRANSAKCJI: klatka, która między
        odczytem a zapisem przestała być nagrobkiem, liczy się jako pominięta, a nie zostaje
        przemalowana. Bez niego jedyną obroną byłby filtr w read-modelu, czyli POZA transakcją —
        obrona słabsza niż u obu sąsiadów (`expected_object_id` jest tu martwy z definicji, bo
        nagrobek ma `object_id IS NULL`).

        `alias_norm=None`: alias zapisało pierwotne nadanie, a przywrócenie niczego nie nazywa.
        `object_source='user'` (domyślne): przywrócenie JEST wskazaniem palcem — drugim świadomym
        gestem tej samej ręki.

        TRZY GESTY JEDNEJ OSI, JEDNA GRAMATYKA (FC-6, R-S2b-13): `assigned + skipped == len(ids)`.
        Sąsiednie gesty dostają całe zaznaczenie i odsiewają je licznikami klingi, a ten podawał
        klindze wyłącznie grupy - więc „z M" liczyło same nagrobki z pamięcią (firsthand: „30 z 30"
        przy 120 zaznaczonych), a reszta zaznaczenia nie liczyła się nigdzie. Gest startuje więc od
        rozbicia z read-modelu i mówi ZAWSZE przez `_po_gescie_osi`, także przy zerze grup: osobne
        zdanie „nie ma czego przywrócić" było drugą gramatyką tej samej osi, podczas gdy sąsiad
        w tej samej sytuacji mówi „Cofnięto … 0 z N · nie było czego cofać: N"."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        grupy, pominiete = queries.restore_targets(self.con, ids)
        gest = repo.ObjectGesture(**pominiete)
        if grupy:                            # faza „0 z 0" zapowiadałaby robotę, której nie ma
            with busy.busy(self.status_message.emit,
                           i18n.t("busy.restoring", done=0, total=len(grupy))) as faza:
                for i, g in enumerate(grupy):
                    try:
                        gest += repo.user_assign_object(
                            self.con, alias_norm=None, canon=g["canon"], catalog=g["catalog"],
                            kind=g["kind"], frame_ids=g["frame_ids"], now=self._now(),
                            overwrite_weak=True, expected_source="user_cleared",
                            expected_cleared_id=g["object_id"])
                    except ValueError as e:  # dryf do nieistniejącej klatki / konflikt aliasu
                        QMessageBox.warning(self, i18n.t("grid.sel.object_restore"), str(e))
                        # Grupa, która padła, wycofała się w całości (`_immediate`), a grupy po
                        # niej do klingi nie doszły - ich klatki liczą się jako ODMOWA KLINGI
                        # (`skipped_failed`), bo inaczej nie liczyłyby się nigdzie i „z M" znów
                        # kłamałoby o zaznaczeniu. Nie jako dryf: konflikt aliasu nie znaczy, że
                        # stan się zmienił, a „zmieniły się w międzyczasie" mówiłoby właśnie to.
                        gest += repo.ObjectGesture(
                            skipped_failed=sum(len(r["frame_ids"]) for r in grupy[i:]))
                        break
                    faza.say(i18n.t("busy.restoring", done=i + 1, total=len(grupy)))
        self._po_gescie_osi(
            "grid.sel.object_restored", gest,
            canons_key="grid.sel.object_canons_restored",
            nothing_key="grid.sel.object_restore_skip_nothing")

    # ---- panele kling (F3, PLAN_ux_redesign §4) ----
    def _toggle_panel(self, which):
        """Panel klingi z paska zbioru: najwyżej JEDEN widoczny. Zamknięcie zostawia podgląd
        (kolumna podglądu w gridzie to wartość sama w sobie; staging żyje w poczekalni niezależnie).
        Otwarcie/przełączenie na panel X przy podglądzie CUDZEGO właściciela czyści go WPROST
        handlerem `cleared` (R#9 — bez emitowania sygnału cudzego widżetu). SEKWENCJA otwarcia =
        kontrakt (F3R#4): strona stacku → pokaż → echo daty (guard echa musi już widzieć rename)."""
        target = {"macro": self.macro_bar, "rename": self.rename_bar,
                  "lineage": self.lineage_bar}[which]
        # „otwarty" = JAWNIE pokazany (isHidden odwrócone), NIE isVisible() — to drugie jest False,
        # gdy przodek niepokazany (offscreen testy przed show()), i kłamałoby o stanie stacku.
        if not self.panel_stack.isHidden() and self.panel_stack.currentWidget() is target:
            self.panel_stack.setVisible(False)           # zamknięcie: podgląd ZOSTAJE
            self.sel_bar.set_active_panel(None)
            return
        if (self._preview_owner and self._preview_owner != which
                and self.model._preview_active()):
            if self._preview_owner == "macro":
                self._on_macro_clear()
            else:
                self._on_rename_clear()
        self.panel_stack.setCurrentWidget(target)
        self.panel_stack.setVisible(True)
        self.sel_bar.set_active_panel(which)
        if which == "rename":
            self._refresh_date_echo()                    # PO pokazaniu strony (F3R#4)
        elif which == "lineage":
            self._refresh_lineage()                      # jw. — panel czyta zaznaczenie po pokazaniu

    def _rename_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.rename_bar)

    def changeEvent(self, e):
        """Zmiana skórki PRZEBUDOWUJE panel rodowodu — wygaszenie wiersza jest w nim WYPALONE
        w itemie (`setForeground`), a nie czytane w `paint` jak w delegacie gridu, więc samo
        odmalowanie zostawiłoby kolor ze starego motywu. Lekcja jest w repo spisana od dawna
        (`app.py` przebudowuje z tego powodu inne listy) — panel rodowodu był drugim jej złamaniem,
        raz w osi stosów, raz w dołożonej osi kalibracji."""
        super().changeEvent(e)
        if e.type() == QEvent.PaletteChange:
            self._refresh_lineage()          # warunkowe: przy zamkniętym panelu nie czyta bazy

    # ---- panel RODOWODU (I-2d) ----
    def _lineage_panel_open(self):
        return (not self.panel_stack.isHidden()
                and self.panel_stack.currentWidget() is self.lineage_bar)

    def _refresh_lineage(self, *, select_frame_ids=None):
        """Wypełnij panel rodowodu z zaznaczenia. Warunek: DOKŁADNIE JEDNA zaznaczona klatka
        `master_light` — rodowód jest faktem o JEDNYM obrazie, a „rodowód zbioru" nie znaczy nic.
        Każdy inny stan dostaje ZDANIE, nie pustkę: user ma wiedzieć, czego brakuje do odpowiedzi
        (wzorzec „uczciwy disabled", tylko że tłumaczy się panel, nie przycisk).

        `select_frame_ids` przywraca zaznaczenie PO odświeżeniu (werdykt ręki) — po klatkach,
        nie po indeksach, bo kolejność wierszy należy do zapytania, a nie do panelu.

        Świadomie WARUNKOWE (jak `_refresh_date_echo`): przy zamkniętym panelu nie czytamy bazy."""
        if not self._lineage_panel_open():
            return
        wiersze = self._selected_data_rows()
        stosy = [r for r in wiersze if r.get("kind") == "master_light"]
        if len(stosy) != 1:
            # OŚ KALIBRACJI (C3, Issue #6) — druga odpowiedź tego samego panelu. Warunek jest
            # DOPEŁNIENIEM osi stosów, nie jej konkurentem: pytamy dopiero, gdy w zaznaczeniu nie
            # ma gotowego obrazu, więc droga stosu zachowuje się dokładnie jak przedtem.
            lighty = [r for r in wiersze if r.get("kind") == "light"]
            # DOKŁADNIE JEDEN ZAZNACZONY WIERSZ, nie „jeden light wśród kilku klatek" (CAPTAIN):
            # nagłówek panelu nie nazywa klatki, więc przy zaznaczeniu light+dark+bias użytkownik
            # nie miałby jak sprawdzić, o której z nich mówi ekran.
            if len(wiersze) == 1 and lighty:
                relacje = lineage.explain_light(self.con, lighty[0]["frame_id"])
                if relacje:
                    self.lineage_bar.set_calibration(relacje)
                    return
            # TRZY RÓŻNE POMYŁKI, TRZY ZDANIA. Jeden komunikat na wszystkie mówił o klatce
            # KALIBRACYJNEJ także wtedy, gdy zaznaczono dwie klatki nieba — czyli zdanie fałszywe
            # o tym, co użytkownik ma przed oczami (ta sama klasa co „kryterium sklejające fakty").
            klucz = ("grid.lin.hint.none" if not wiersze else
                     "grid.lin.hint.many" if len(stosy) > 1 or len(lighty) > 1 else
                     "grid.lin.hint.one_only" if len(wiersze) > 1 else
                     "grid.lin.hint.not_stack")
            self.lineage_bar.set_lineage(None, [], hint=i18n.t(klucz))
            return
        fid = stosy[0]["frame_id"]
        head = queries.stack_lineage_head(self.con, fid)
        if head is None:
            self.lineage_bar.set_lineage(None, [], hint=i18n.t("grid.lin.hint.not_computed"))
            return
        # PROPOZYCJA MATERIAŁU liczona TYLKO tam, gdzie jest pytaniem: obraz z rodowodem ma fakt,
        # a obraz z powodem ZWIETRZAŁYM czeka na przeliczenie etapem, nie na rękę. Poza tymi dwoma
        # stanami zapytanie chodziłoby po całym materiale obiektu przy każdym zaznaczeniu, nie
        # mając komu oddać wyniku.
        kandydaci, raw_bez_zegara = (), 0
        if head["unresolved_reason"] and not head["inputs"] \
                and not queries.lineage_reason_stale(head):
            kandydaci, raw_bez_zegara = stacks.propose_lineage_candidates(self.con, fid)
        # TRZECI ŚWIADEK ZEGARA (G2-1d): uwaga przebiegu o RAW-ach bez zegara przy obrazie, którego
        # werdykt mówi co innego - także przy GOTOWYM rodowodzie z puli mieszanej, gdzie propozycji
        # nie liczymy wcale. Bez tego członu flaga mówiłaby „nie umiem umieścić N klatek", a gest,
        # który je umieszcza, zostałby schowany (bramka niżej i `_sync_offset_visible`).
        raw_bez_zegara = raw_bez_zegara or _lineage_raw_note(head)
        # PROPOZYCJA ODNIESIENIA LICZONA TYLKO TAM, GDZIE JEST PYTANIEM (R2): dla 121 masterów
        # FITS/ASI zegar nie jest problemem, a zapytanie chodzi po całym materiale obiektu, więc
        # liczenie go przy każdym zaznaczeniu byłoby kosztem bez odbiorcy.
        #
        # DRUGI WYZWALACZ DOSZEDŁ Z BRAMKI 3a i stoi PO policzeniu kandydatów, bo dopiero one
        # mówią, że pytanie o zegar w ogóle padło. Powód `offset_unknown` sam nie wystarcza:
        # stos o zdegenerowanym oknie go nie dostanie (`stacks._plan` kończy wcześniej), a to
        # właśnie takie stosy stoją w kubełku z materiałem RAW nie do umieszczenia w czasie.
        self.lineage_bar.set_offset_hint(
            stacks.propose_offset_minutes(self.con, fid)
            if head["unresolved_reason"] == REASON_OFFSET_TOKEN or raw_bez_zegara else None)
        self.lineage_bar.set_lineage(head, queries.stack_lineage_inputs(self.con, fid),
                                     candidates=kandydaci, raw_unreferenced=raw_bez_zegara)
        self._lineage_frame_id = fid
        if select_frame_ids:
            self.lineage_bar.select_frame_ids(select_frame_ids)

    def refresh_lineage_panel(self):
        """Przerysuj panel rodowodu ze STANU — publiczne wejście dla gospodarza (NARROW).

        Wołane po zakończeniu KAŻDEGO etapu Dostawy, bo etap przepisuje `unresolved_reason`,
        a panel trzyma jego poprzednią wartość. Bez tego takt 3 zostawiał na ekranie zdanie
        „zapis nieaktualny" dokładnie po tym, jak sam ten zapis odświeżył (bramka pakietu, zarzut 7).

        Cicho, gdy panel nie jest otwarty albo nic nie zaznaczono — `_refresh_lineage` sam
        rozstrzyga, czy ma co pokazać."""
        self._refresh_lineage()

    def _on_lineage_offset(self, minutes):
        """Wskazane odniesienie czasu → jedna klinga (`repo.set_integration_offset`), potem
        odświeżenie panelu ze STANU — lustro `_on_lineage_judged`.

        RODOWODU TU NIE PRZELICZAMY i to jest granica, nie brak: dobór wejść jedzie po CAŁYM
        archiwum stosów (`run_stack_lineage`), więc jest robotą etapu w Dostawie, nie skutkiem
        ubocznym kliknięcia w panelu. Zamiast tego zdanie mówi WPROST, gdzie to policzyć — ta sama
        umowa, co przy geście zestawu w R1."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        # ILE KLATEK CZEKAŁO NA TEN ZEGAR (G2-3d) - CZYTANE PRZED ZAPISEM, nie po. Zakres offsetu
        # jest bramką na NONSENS, nie na pomyłkę: wskazanie o dobę obok przechodzi walidację,
        # a jedynym śladem był potem powód `no_candidates` bez słowa o przyczynie. Człon stoi
        # ZAWSZE, także przy zerze - to właśnie zero mówi „ten zegar nie miał czego odblokować".
        #
        # ⚠ KOLEJNOŚĆ JEST TU CAŁYM MECHANIZMEM (bramka pakietu, zarzut blokujący). Zapis czyni
        # powód ZWIETRZAŁYM (`queries.lineage_reason_stale`), więc `_refresh_lineage()` po nim nie
        # liczy już propozycji: liczba wzięta stamtąd byłaby strukturalnym zerem, czyli członem
        # martwym w chwili narodzin - i to nad stosem, pod którym stoi 36 klatek.
        czekalo = i18n.t("grid.lin.offset_waiting",
                         n=self.lineage_bar.klatki_bez_odniesienia())
        repo.set_integration_offset(self.con, master_frame_id=self._lineage_frame_id,
                                    utc_offset_min=minutes, now=self._now())
        self._refresh_lineage()
        # Zapis czyni powód `offset_unknown` zwietrzałym, a ten liczy się do plakietki Porządków
        # (`stacks_lineage_pending`) - odświeżenie nie może czekać na etap, który przy odmowie
        # albo bez `run_stage_fn` w ogóle nie ruszy.
        self.stan_porzadkow_changed.emit()
        godziny = f"{minutes / 60.0:+.1f}"
        # TAKT 3: gest sam się domyka. Bez tego user musiał przejść na inny ekran i znaleźć tam
        # przycisk stojący obok wyboru katalogu — akcja domykająca gest mieszkała w sekcji
        # o wciąganiu plików z dysku. Odmowa (etap już biegnie / brak bazy) NIE jest błędem gestu:
        # zapis się udał, więc mówimy prawdę o obu połówkach i zostawiamy zdanie z receptą.
        if self.run_stage_fn is None:
            self.status_message.emit(i18n.t("grid.lin.offset_saved", hours=godziny) + czekalo)
            return
        powod = self.run_stage_fn()
        self.status_message.emit(
            (i18n.t("grid.lin.offset_saved_counting", hours=godziny) if powod is None
             else i18n.t("grid.lin.offset_saved_busy", hours=godziny, reason=powod)) + czekalo)

    def _on_lineage_judged(self, frame_ids, excluded):
        """Werdykt ręki → jedna klinga (`repo.judge_integration_input`), potem odświeżenie panelu
        ze STANU. Zapis jest natychmiastowy i BEZ poczekalni: to decyzja o RELACJI w bazie, nie
        mutacja pliku — staging chroni bajty na dysku, a tu żaden bajt nie jest ruszany."""
        iid = self.lineage_bar.integration_id()
        if iid is None:
            return
        n = 0
        for fid in frame_ids:
            n += repo.judge_integration_input(
                self.con, integration_id=iid, input_frame_id=fid,
                excluded=excluded, now=self._now())
        # ZAZNACZENIE PRZEŻYWA WERDYKT: lista jest przebudowywana ze stanu, więc bez tego człowiek
        # tracił wiersze zaraz po decyzji i cofnięcie własnego „odrzuć" kosztowało odszukanie ich
        # od nowa (wiz #8). Zwracamy te same klatki, nie te same indeksy — kolejność wierszy
        # należy do zapytania.
        self._refresh_lineage(select_frame_ids=frame_ids)
        if n:
            # Potwierdzone wejście czyni powód stosu zwietrzałym, a ten liczy się do plakietki.
            self.stan_porzadkow_changed.emit()
        # Klinga jest idempotentna, więc powtórzony ten sam werdykt daje 0 — a „Potwierdzono 0"
        # brzmi jak porażka zapisu, którym nie jest (QUIET: brak zmiany mówi o braku zmiany).
        klucz = ("grid.lin.judged_none" if not n else
                 "grid.lin.judged_excluded" if excluded else "grid.lin.judged_confirmed")
        self.status_message.emit(i18n.t(klucz, n=n))

    def _describe_criteria(self):
        """Opis zbioru słowami do paska: drzewo EFEKTYWNE (facety + advanced — F4R#8, samo
        `_filter_tree` nie widzi facetów) + flagi perspektyw spoza silnika (`only_dups`/`only_review`
        - grid.py PRESETS; drzewo ich nie koduje, F4R2#7), łączone „ · ".

        OSTATNI CZŁON MÓWI, CZEGO TEN BUILD NIE ZASTOSOWAŁ (D-V-9f): perspektywa zapisana nowszym
        wydaniem może nieść warunek, którego tu nie znamy, a wtedy zbiór jest szerszy niż zapisany.
        Pytamy pozycję, która JEST na liście - dlatego `_refresh` woła ten opis PO właścicielu
        etykiety: gdy zbiór przestał być tą perspektywą, ostrzeżenie o niej też przestaje dotyczyć."""
        parts = [filter_engine.describe(self._effective_tree)]
        parts += [i18n.t(_klucz_kryterium(atrybut)) for atrybut, _ in _TRIMY
                  if getattr(self, atrybut)]
        data = self.combo_persp.currentData()
        spec = self._spec_pozycji(data) if data and data[0] == "saved" else None
        pominiete = _nieznane_warunki(spec) if spec is not None else []
        if pominiete:
            parts.append(i18n.t_plural("grid.criteria.unknown_keys", len(pominiete),
                                       keys=", ".join(pominiete)))
        return " · ".join(parts)

    def _zeruj_flagi(self):
        """Zdejmij WSZYSTKIE flagi perspektyw - skład z `_TRIMY`, jak każda inna enumeracja rodziny."""
        for atrybut, _ in _TRIMY:
            setattr(self, atrybut, False)

    def _zbior_zawezony(self):
        """Czy zbiór trzyma coś, co ZDEJMUJE „× Wyczyść zbiór" - facety albo filtr zaawansowany.

        JEDEN WŁAŚCICIEL TEGO PREDYKATU: karmi i uczciwy disabled przycisku, i receptę powrotu po
        geście osi (FC-2). Dwie kopie rozjechałyby się dokładnie tak, jak rozjechała się rodzina
        `only_*` - a tu cena rozjazdu jest wyższa niż wygaszony przycisk: zdanie po geście
        wskazywałoby gest, który zawężenia nie zdejmuje. Flagi perspektywy są POZA tym predykatem
        świadomie, bo ten przycisk ich nie tyka (`_on_clear_selection`)."""
        return bool(self._facet_state) or self._filter_tree is not None

    def _trim_aktywny(self):
        """Czy trim perspektywy przycina zbiór - LICZONE W MIEJSCU UŻYCIA, nie zapamiętane (BP-4).

        Bliźniak `_zbior_zawezony` i tak samo jedyny właściciel swojego predykatu. Do tej zmiany
        odpowiadał atrybut `_trim_active` stawiany raz w `refresh()`: klasa „recepta czyta stan
        nieaktualny" była pusta wyłącznie dlatego, że KAŻDA ścieżka zmieniająca zbiór kończy się
        `refresh()` - czyli przez kolejność wywołań, bez żadnego strażnika. Pierwszy czytelnik
        spoza tej kolejności dostałby stan sprzed gestu, a recepta wskazałaby gest, który niczego
        nie odsłania.

        Zero SQL i zero kosztu: czytamy same flagi, a nie zbiory, które one wybierają."""
        return any(getattr(self, atrybut) for atrybut, _ in _TRIMY)

    # ---- reakcje ----
    def _on_filter(self, tree):
        """Jedyny odbiorca `filterApplied` panelu - „Zastosuj", Enter w polu wartości i „Wyczyść"
        panelu (także pośrednio przez `_on_clear_selection`). `set_tree` sygnału nie emituje, więc
        przełączenie perspektywy tędy nie przechodzi.

        ETYKIETA IDZIE ZA ZBIOREM (BP-5, bliźniak przez panel filtra): panelowe „Wyczyść" omija
        `_on_clear_selection`, a „Kalibracja" zostawała nad pełnym zbiorem. Rozstrzyga właściciel na
        końcu `_refresh`, jak po każdym przeładowaniu. Filtr ZMIENIONY etykiety nie rusza (żaden
        preset go nie definiuje, a właściciel nie zgaduje); przeskok następuje dopiero, gdy stan
        znów jest definicją presetu - w praktyce po zdjęciu filtra."""
        self._filter_tree = tree
        self.refresh()

    def _on_columns(self, cols):
        self._columns = cols
        self.refresh()

    def _on_group(self):
        # Grupa wersji jest pochodną liczoną w `_refresh` tylko wtedy, gdy ktoś o nią pyta
        # (`_potrzebne_wersje`) - wybór tej pozycji musi więc przeładować zbiór, inaczej każdy
        # wiersz wylądowałby w „(brak)". Pozostałe klucze model przegrupowuje sam, bez SQL.
        if self.combo_group.currentData() == _GRUPA_WERSJI:
            self.refresh()
            return
        self.model.set_group_by(self.combo_group.currentData())

    # ---- odczyt → widok ----
    def _memo_leaf_fns(self):
        """Memoizowane akcesory silnika na czas JEDNEGO refreshu (F4R2#4): sibling-sety facetów
        re-używają tych samych liści, więc cache `(kind,kw,p1,p2)→set` zwija 5N wywołań liści do N.
        Jedna migawka DB per refresh — cache umiera z wyjściem z refresh() (źródło prawdy = baza)."""
        leaf_cache = {}
        universe_cache = []

        def leaf_fn(k, kw, p1, p2):
            key = (k, kw, p1, p2)
            if key not in leaf_cache:
                leaf_cache[key] = queries.leaf_frame_ids(self.con, k, kw, p1, p2)
            return leaf_cache[key]

        def universe_fn():
            if not universe_cache:
                universe_cache.append(queries.all_frame_ids(self.con))
            return universe_cache[0]

        return leaf_fn, universe_fn

    def refresh(self):
        """Silnik filtra → zbiór frame_id → base_rows + pivot → model. Źródło prawdy = baza (bez
        cache między refreshami). F4: drzewo EFEKTYWNE = compose(stan facetów, drzewo panelu);
        trimy dups/review SETAMI literałowymi PRZED base_rows — JEDNA derywacja trimu dla zbioru
        głównego i sibling-setów listwy (SPOT, F4R2#2); liczniki listwy per sibling-set (F4R#1).

        POD NAZWANĄ FAZĄ (F-1): zmierzone **1 000 ms** na 16 648 klatkach, a wołane przy KAŻDEJ
        zmianie facetu, perspektywy i filtra — czyli w reakcji na kliknięcie, po którym user czeka
        i patrzy w nieruchomy ekran."""
        with busy.busy(self.status_message.emit, i18n.t("busy.read_frames")):
            self._refresh()

    def _refresh(self):
        """Wykonawcza połowa `refresh` (fazę zakłada wołający — JEDEN jej właściciel)."""
        leaf_fn, universe_fn = self._memo_leaf_fns()
        self._effective_tree = facet_model.compose(self._facet_state, self._filter_tree)
        frame_ids = filter_engine.run(self._effective_tree, leaf_fn=leaf_fn, universe_fn=universe_fn)
        # JEDNA derywacja trimu dla zbioru głównego I dla sibling-setów listwy (SPOT, F4R2#2) —
        # lista powstaje RAZ i idzie w obie strony. Dwie kopie tej enumeracji rozjechały się
        # dokładnie tak, jak zapowiada historia rodziny `only_*`: listwa dostawała `dup_ids`
        # i `review_ids`, a pięciu młodszych braci nie widziała w ogóle, więc w perspektywie
        # z trimem liczniki facetów i godziny portfela liczyły się na zbiorze BEZ przycięcia.
        # Skład rodziny czytamy z `_TRIMY` (BP-4), więc dołożenie ósmej flagi jest wpisem w tabelę,
        # a nie ósmym miejscem do zapamiętania.
        trims = [getattr(queries, nazwa)(self.con) for atrybut, nazwa in _TRIMY
                 if getattr(self, atrybut)]
        # NOWY set, NIGDY `&=`: przy pustym filtrze `filter_engine.run` zwraca uniwersum WPROST
        # (`filter_engine.py:171`), a to jest ZAPAMIĘTANY obiekt memoizacji (`_memo_leaf_fns`).
        # `&=` przycinało go W MIEJSCU, więc kolejne `universe_fn()` widziało już przycięty zbiór —
        # perspektywa z trimem potrafiła pokazać „Baza pusta" na pełnej bazie (wizytator P5 #2).
        for trim in trims:
            frame_ids = frame_ids & trim
        base = [_derive(r) for r in queries.base_rows(self.con, list(frame_ids))]
        if self._potrzebne_wersje():
            _adnotuj_wersje(base, queries.stack_version_groups(self.con))
        # Fakty KOPII (0021) - pytamy wyłącznie o klatki z kilkoma obecnymi kopiami: kolumna
        # „Obrazy" i podpowiedź „×N" potrzebują wtedy każdej kopii, a reszta archiwum ma jedną
        # i jej liczbę niesie już `base_rows`. Wąskie zapytanie zamiast podzapytania na 16 tys. wierszy.
        _dolacz_kopie(base, queries.present_copy_facts(
            self.con, [b["frame_id"] for b in base if (b.get("n_present") or 0) > 1]))
        base_ids = [b["frame_id"] for b in base]
        self._frame_ids = base_ids     # cel makra = to, co WIDAĆ (po filtrach dups/review), doktryna §5
        keywords = list(self._columns)
        rows = queries.cards_pivot(self.con, base_ids, keywords) if (base_ids and keywords) else []
        pv = pivot_mod.build_pivot(base_ids, keywords, rows)
        self.model.set_data(base, pv, keywords, group_by=self.combo_group.currentData(),
                            version_col=self._perspektywa_wersji())
        if self.model._version_col() is not None:
            # Domyślne 100 px elidowało „inna integracja · 2026-02-21 12:43 · 33 wejścia", czyli
            # właśnie te fakty, po które perspektywa istnieje. Koszt znikomy: perspektywa ma na
            # kopii żywego archiwum 40 stosów (2026-09-26).
            self.table.resizeColumnToContents(self.model._version_col())
        # CEL OSTATNIEGO GESTU WRACA RAZEM ZE ZBIOREM (FC-2, firsthand). Recepta powrotu odsłania
        # zbiór, ale sama nie ODNAJDUJE w nim celu: zmierzone na żywym archiwum - po wykonaniu
        # recepty widok miał 16 901 wierszy, zaznaczenie 0 i wygaszoną kontrolkę, więc 43 klatki
        # gestu były nie do wyłuskania. Recepta prowadziła w ślepy zaułek dokładnie tam, gdzie
        # miała pomóc. Cel odkłada się więc sam przy najbliższym przeładowaniu zbioru.
        # JEDNORAZOWO, wzorem `_reveal_facet`: stan konsumuje PIERWSZY refresh po geście, także
        # gdy niczego nie odłożył. Bez wygaszania zaznaczenie wracałoby przy dowolnym późniejszym
        # odświeżeniu (zmiana kolumn, sortu) - czyli tam, gdzie user o nie nie prosił, a granica
        # „zaznaczenie przeżywa GEST, nie każdy refresh" jest w tym repo pinowana od R-S2b-3.
        if self._cel_gestu:
            cel, self._cel_gestu = self._cel_gestu, []
            self._przywroc_zaznaczenie(cel)
        n = len(base)
        self._n_total = n
        self._update_count()
        if n == 0:
            # Rozróżnienie „filtr nic nie wpuścił" vs „w bazie NIC nie ma" (wiz F5 #8). Uniwersum
            # bierzemy z memoizowanego `universe_fn` TEGO refreshu — na niepustym gridzie zapytania
            # nie ma w ogóle, a gdy filtr już go dotknął, jest z cache'u. Wariant niepustej bazy
            # wybiera decyzja recepty powrotu (FH-4) - patrz `_ustaw_pusty_stan`.
            self._ustaw_pusty_stan(bool(universe_fn()))
        self.empty_box.setVisible(n == 0)    # pojemnik i etykieta RAZEM: `empty.isVisible()` zostaje
        self.empty.setVisible(n == 0)        # kontraktem, a etykieta nie wisi widoczna w ukrytym pudle
        self.table.setVisible(n > 0)
        self.macro_bar.set_actions_enabled(bool(base_ids))   # szczery disabled makra na pustym gridzie (#4)
        self.rename_bar.set_actions_enabled(bool(base_ids))  # bliźniaczo dla renamu
        self.sel_bar.set_have_frames(bool(base_ids))         # pusty zbiór gasi „Wydaj na stół…" (F3R#2)
        self.sel_bar.set_clearable(self._zbior_zawezony())
        self._reload_facet_rail(leaf_fn, universe_fn, trims, base_ids)   # listwa (F4)
        self._sync_staging_mutex()                           # staging jednej klingi wyłącza „Do stagingu" drugiej
        self._refresh_date_echo()                            # panel daty odbija świeże widoczne (echo warunkowe)
        self._refresh_lineage()                              # …i panel rodowodu, tak samo warunkowo
        self.status_message.emit(
            i18n.t("grid.status.loaded", frames=i18n.t_plural('grid.frames', n), cols=len(keywords)))
        # ETYKIETA PERSPEKTYWY JEST POCHODNĄ STANU (BP-5 domknięty tutaj): każda droga, która zmienia
        # zbiór, kończy się tym przeładowaniem, więc właściciel etykiety ma JEDNO miejsce wołania,
        # a nie po jednym przy każdym geście - tamte trzy przegapiły klik w listwie facetów.
        self._etykieta_perspektywy_za_stanem()
        # Kryteria zbioru SŁOWAMI (F3) - PO etykiecie, bo ostatni człon opisu pyta pozycję listy
        # perspektyw o warunki, których ten build nie zna (D-V-9f); przed rozstrzygnięciem
        # etykiety pytałby pozycję, która za chwilę przestanie być bieżąca.
        self.sel_bar.set_criteria(self._describe_criteria())

    def _reload_facet_rail(self, leaf_fn, universe_fn, trims, current_ids):
        """Liczniki listwy facetów per SIBLING-SET (F4R#1): zbiór facetu F = compose bez CAŁEJ własnej
        grupy F (in+ex) — liczniki na pełnym zbiorze samo-zawężałyby facet i OR-wewnątrz byłby
        nieosiągalny. Facet BEZ aktywnego wyboru → sibling == zbiór bieżący (już policzony;
        D-UX-3(a)). Trim perspektywy = przecięcie z gotowymi setami (F4R2#2, bez base_rows).

        `trims` przychodzi z `_refresh` GOTOWĄ LISTĄ, a nie jako dwa nazwane sety: enumeracja
        rodziny `only_*` ma tu jednego właściciela, więc dołożenie siódmej perspektywy nie może
        po cichu ominąć liczników listwy (to jest ta sama klasa rozjazdu, którą rodzina
        przechodziła już dwa razy)."""
        counts, extras = {}, {}
        for facet in facet_model.FACETS:
            if facet not in self._facet_state:
                ids = current_ids
            else:
                tree = facet_model.compose(facet_model.sibling_state(self._facet_state, facet),
                                           self._filter_tree)
                sib = filter_engine.run(tree, leaf_fn=leaf_fn, universe_fn=universe_fn)
                # NOWY set, NIGDY `&=` — z tego samego powodu, co w `_refresh`: sibling-set powstaje
                # z drzewa BEZ własnej grupy facetu, więc przy jednym aktywnym facecie i pustym
                # filtrze `compose` daje `None`, a `run` oddaje MEMOIZOWANE uniwersum. `&=` przycinało
                # je w miejscu, czyli kolejny facet tej samej pętli liczył licznik na zbiorze
                # przyciętym przez poprzednika.
                for trim in trims:
                    sib = sib & trim
                ids = list(sib)
            counts[facet] = self._facet_counts(facet, ids)
            if facet == "object":
                # Portfel (F7 §8): godziny lightów per obiekt na TYM SAMYM `ids` co `facet_objects`
                # (parytet n↔godziny; inne aktywne facety zawężają godziny). Formatowanie = `portfolio`.
                summ = portfolio.summarize(queries.object_exposure(self.con, ids))
                extras["object"] = {oid: (portfolio.object_suffix(e), portfolio.object_tooltip(e))
                                    for oid, e in summ.items()}
        # `_reveal_facet` jest JEDNORAZOWY: gasimy go tu, nie u wołającego — inaczej każdy kolejny
        # refresh (klik w listwie, zmiana perspektywy) skakałby do celu sprzed pół godziny.
        reveal, self._reveal_facet = self._reveal_facet, None
        # DRUGIE NAZWY do szukajki (S3): mapa `canon → {alias_norm}` z CAŁEJ biblioteki, nie ze
        # zbioru — szukajka chowa wiersze listy, więc filtrowanie mapy po `ids` nic by nie
        # oszczędziło, a rozjechałoby dwa wejścia tego samego pytania. Bez niej „Large Magellanic
        # Cloud" nie znajduje niczego: kanon `LMC` nie ma z tą frazą wspólnej litery.
        self.facet_rail.set_data(counts, self._facet_state, extras, reveal=reveal,
                                 aliases=queries.object_alias_index(self.con))

    def _facet_counts(self, facet, ids):
        """Kubełki jednego facetu → list[(value, label, n)] (kontrakt `FacetRail.set_data`).
        Etykieta teleskopu = label→canon fallback z JEDNEGO właściciela (`queries.telescope_label`);
        filtr/rodzaj/noc są swoją własną etykietą."""
        if facet == "object":
            return [(r["id"], r["canon"], r["n"]) for r in queries.facet_objects(self.con, ids)]
        if facet == "filter":
            return [(r["filter_canon"], r["filter_canon"], r["n"])
                    for r in queries.facet_filters(self.con, ids)]
        if facet == "kind":
            return [(r["kind"], r["kind"], r["n"]) for r in queries.facet_kinds(self.con, ids)]
        if facet == "telescope":
            return [(r["id"], queries.telescope_label(r), r["n"])
                    for r in queries.facet_telescopes(self.con, ids)]
        return [(r["night"], r["night"], r["n"]) for r in queries.facet_nights(self.con, ids)]

    def _on_facet_change(self, state):
        """Klik w listwie (cykl none→in→ex→none policzony w `facet_model.cycle`) → nowy stan →
        przeskładanie zbioru. Stan JEST własnością FramesView (widżet emituje wynik)."""
        self._facet_state = state
        self.refresh()

    def _on_clear_selection(self):
        """„× Wyczyść zbiór" (wiz F4 #3): zdejmij facety + filtr advanced JEDNYM klikiem. Flagi
        perspektywy (`only_dups`/`only_review`) zostają — są własnością perspektywy, nie filtra.
        `_clear` panelu emituje `filterApplied(None)` → `_on_filter` → jeden refresh.

        ETYKIETA PERSPEKTYWY IDZIE ZA ZBIOREM (BP-5): preset „Kalibracja" zawęża filtrem, więc ten
        gest zdejmuje całą jego definicję, a zapisana perspektywa traci swoje facety. Rozstrzyga
        właściciel etykiety na końcu `_refresh`, do którego ten gest dochodzi przez `_on_filter`;
        kontrakt wobec flag zostaje bez zmian, bo od niego zależy wykonalność recepty powrotu
        (`_rodzaj_recepty_powrotu`)."""
        self._facet_state = facet_model.empty_state()
        self.filter_panel._clear()

    def _on_selection_changed(self):
        self._update_count()
        self._date_timer.start()                             # debounced echo daty (R1 #15)

    def _update_count(self):
        """Licznik = widoczne klatki + (gdy jest) zaznaczenie: „N klatek · M zaznaczonych" (wizytator G2 —
        akcja na zaznaczeniu musi potwierdzać cel). Nagłówki grup są nieselektowalne → nie liczą się.
        Odświeża też żywą etykietę celu renamu (R1 #18): zaznaczenie-first, inaczej widoczne.
        Odmiana przez `plural` [#11]: ścieżka Duplikatów robi z n=1 przypadek TYPOWY, a „1 klatek"
        na pasku zbioru czytało się jak błąd (wiz K7 / wiz F5 #7).

        JEDEN PRZEBIEG ZAZNACZENIA NA ZDARZENIE (R-S2b-7). Do S3 ta metoda chodziła po zaznaczeniu
        DWA razy — raz po licznik (`selectedRows()`), raz po id-y (`_selected_data_rows`) — a każdy
        przebieg kosztował **1,06 s** przy pełnym zaznaczeniu 16 648 klatek. Licznik bierze się więc
        z tej samej listy wierszy, z której biorą się id-y."""
        rows = self._selected_data_rows()
        sel = len(rows)
        txt = i18n.t_plural("grid.frames", self._n_total) + (
            f"  ·  {i18n.t_plural('grid.selected', sel)}" if sel else "")
        self.count_label.setText(txt)
        self._sync_object_actions(rows)
        if hasattr(self, "rename_bar"):
            self.rename_bar.set_target_label(
                f"Cel: {i18n.t_plural('grid.selected', sel)}" if sel
                else f"Cel: {i18n.t_plural('grid.visible', self._n_total)}")

    def _sync_object_actions(self, rows=None):
        """Uczciwy disabled osi obiektu — liczony z ZAZNACZENIA, nie z widocznych (§4/14c-a).

        BEZ DEBOUNCE'U, i to jest wynik POMIARU, nie zaniechanie (R-S2b-7). Znalezisko mówiło
        „read-model w gorącej pętli" i szacowało koszt na `json.dumps` 15 890 id + `json_each`
        na wątku GUI. Zmierzone przy pełnym zaznaczeniu 16 648 klatek: `selection_object_state`
        = **31 ms**, czyli 1,5% kosztu `_update_count`; całe 2 040 ms brał `selectedRows()`,
        wołany dwa razy — i to jego zdjęcie (zakresy zamiast `QModelIndex`) załatwiło pętlę,
        z 2 071 ms na **2 ms**. Debounce dołożony NA WIERZCH tej naprawy kupowałby 31 ms na
        zdarzenie, a płacił niezmiennikiem „po zmianie zaznaczenia pasek mówi prawdę": stan
        pozycji menu zależałby od timera, więc każda bramka uczciwości disabled musiałaby pompować
        pętlę zdarzeń. Zła cena za 1,5%.

        `rows` przekazuje wołający, gdy już je ma — jeden przebieg zaznaczenia na zdarzenie.
        Read-model pytamy tylko wtedy, gdy jest o co pytać: przy pustym zaznaczeniu odpowiedź jest
        znana bez SQL-a."""
        if rows is None:
            rows = self._selected_data_rows()
        ids = [r["frame_id"] for r in rows]
        stan = queries.selection_object_state(self.con, ids) if ids else None
        self.sel_bar.set_object_actions(
            namable=stan["namable"] if stan else 0,
            clearable=stan["clearable"] if stan else 0,
            stacks=stan["stacks_touchable"] if stan else 0,
            restorable=stan["restorable"] if stan else 0,
            reason=_object_gate_reason(stan))
        # OŚ ŻYWOTNOŚCI liczy się z TYCH SAMYCH wierszy, bez drugiego zapytania: `base_rows` niesie
        # komplet (`retired_at`, `superseded_by`, `present`, `n_present`). Predykat jest lustrem
        # guardów klingi (`repo._retire_verdict`) — a rozstrzyga i tak klinga, w transakcji.
        retirable = sum(1 for r in rows
                        if r.get("retired_at") is None and r.get("superseded_by") is None
                        and r.get("present") == 0 and (r.get("n_present") or 0) == 0)
        restorable = sum(1 for r in rows if r.get("retired_at") is not None)
        alive = sum(1 for r in rows if (r.get("n_present") or 0) > 0)
        self.sel_bar.set_frame_actions(retirable=retirable, restorable=restorable,
                                       reason=_frame_gate_reason(len(rows), alive))

    # ---- oś ŻYWOTNOŚCI klatki (D-OW-3/R2) ----

    def _on_frame_retire(self):
        """„Wycofaj klatkę…": zamyka sprawę klatki, której pliku już nie ma na dysku.

        POTWIERDZENIE, w odróżnieniu od sąsiadów z osi obiektu, i to z jednego powodu: skutek tego
        gestu jest NIEWIDOCZNY NATYCHMIAST — klatka wypada z kubełków i z bieżącej perspektywy,
        więc ekran po geście nie pokazuje tego, co się właśnie stało. Okno podaje liczbę, którą
        gest realnie ruszy (tę samą, co tooltip kontrolki), zanim cokolwiek zostanie zapisane.

        Cel = ZAZNACZENIE, jak wszystkie gesty pasków w tym widoku. Klatki żywe, zastąpione
        i już wycofane odsiewa KLINGA (`repo._retire_verdict`), nie ten slot: filtr w read-modelu
        stałby POZA transakcją, więc plik, który wrócił między oknem a zapisem, przeszedłby."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        if QMessageBox.question(
                self, i18n.t("grid.sel.frame_retire"),
                i18n.t("grid.sel.frame_retire_ask", n=len(ids))) != QMessageBox.Yes:
            return
        gest = repo.retire_frames(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_klatki("grid.sel.frame_retired", gest)

    def _on_frame_restore(self):
        """„Przywróć klatkę" — DROGA POWROTU z wycofania. Bez potwierdzenia, bo gest jest
        NIEDESTRUKCYJNY i odwraca cudzy skutek: pytanie o zgodę na naprawę pomyłki byłoby
        kolejną przeszkodą dokładnie tam, gdzie człowiek już raz się pomylił."""
        ids = self._object_gesture_ids()
        if not ids:
            return
        gest = repo.restore_frames(self.con, frame_ids=ids, now=self._now())
        self._po_gescie_klatki("grid.sel.frame_restored", gest)

    def _po_gescie_klatki(self, klucz, gest):
        """Ogon gestów osi żywotności: zdanie z ROZBICIEM per powód + odświeżenie + zaznaczenie.

        Rozbicie idzie z `RetireGesture.skipped_breakdown` (JEDEN właściciel składu), nie z literału
        tutaj — ta sama lekcja, którą repo dostało już na osi obiektu: człon dołożony później
        wpadał do sumy „z M" i znikał z rozbicia, czyli z jedynego miejsca, gdzie tłumaczył.

        CZŁON „POZA WIDOKIEM" TA SAMA FUNKCJA, CO NA OSI OBIEKTU (FC-2, bramka pakietu): tutaj
        wypchnięcie celu jest wręcz REGUŁĄ, bo wycofanie zdejmuje klatkę z kubełków roboczych -
        a zdanie, które „bywa jedynym śladem", milczało o tym, gdzie te klatki się podziały."""
        zaznaczone = [r["frame_id"] for r in self._selected_data_rows()]
        msg = i18n.t(klucz, done=gest.done, total=gest.done + gest.skipped)
        for sufiks, n in gest.skipped_breakdown:
            if n:
                msg += i18n.t(f"grid.sel.frame_skip_{sufiks}", n=n)
        recepta = ""
        if gest.done:
            self.refresh()
            fakt, recepta = self._czlon_poza_widokiem(
                len(zaznaczone) - self._przywroc_zaznaczenie(zaznaczone), zaznaczone)
            msg += fakt
            # Wycofanie i przywrócenie ruszają cztery liczniki Porządków naraz (wycofane,
            # „a plik wrócił", zniknięte, brakujące kopie) - plakietka ma to wiedzieć bez wejścia
            # w Porządki. Przed zdaniem: `refresh_counts` nie mówi na pasek stanu.
            self.stan_porzadkow_changed.emit()
        # ZDANIE PO ODŚWIEŻENIU I TYLKO JEDNO — repo dostało tę klasę już DWA RAZY na sąsiedniej
        # osi: `refresh()` kończy własnym `status_message`, a odbiornikiem obu jest jeden
        # `showMessage`, więc emisja przed odświeżeniem ginie w tym samym obrocie pętli zdarzeń.
        # Waży to tu podwójnie: po udanym wycofaniu klatka ZNIKA z perspektywy, więc to zdanie
        # bywa jedynym śladem, że gest się odbył.
        self.status_message.emit(msg)
        self.status_recipe.emit(recepta)

    # ---- WERSJE STOSÓW (perspektywa „Wersje stosów") ----

    def _perspektywa_wersji(self):
        """Czy widok stoi w perspektywie „Wersje stosów" - flaga z `_TRIMY` pod stałą `_FLAGA_WERSJI`."""
        return bool(getattr(self, _FLAGA_WERSJI))

    def _potrzebne_wersje(self):
        """Czy przeładowanie ma policzyć grupy wersji - tylko gdy ktoś o nie pyta: perspektywa
        (kolumna „Wersja") albo grupowanie „Wersja stosu". Poza tym `_refresh` nie płaci za read-model
        (zmierzone 17 ms na 193 stosach żywego archiwum, przy każdym kliknięciu w listwie)."""
        return self._perspektywa_wersji() or self.combo_group.currentData() == _GRUPA_WERSJI

    def _on_table_menu(self, pos):
        """Prawy klik na tabeli: menu z sekcją „Zostaw tę wersję" (perspektywa „Wersje stosów")
        i sekcją dróg wyjścia z izolacji zapisu w miejscu (perspektywy zapisu albo klatka z kopią
        izolowaną). Żadna sekcja nie pasuje → menu się nie pokazuje i zaznaczenie zostaje.

        Wiersz pod kursorem, którego nie ma w zaznaczeniu, staje się zaznaczeniem - konwencja
        platformy, a zarazem jedyny sposób, żeby „tę" wskazywało to, na co człowiek kliknął.
        Kliknięcie W zaznaczenie zostawia je, jak jest: przy kilku zaznaczonych gest wersji odmówi
        z powodem w tooltipie pozycji, zamiast po cichu wybrać jeden z nich, a gesty zapisu
        obejmą wszystkie zaznaczone kopie izolowane (liczba stoi w tooltipie).

        Poza perspektywami menu pyta o izolację klatek, na które wskazuje klik (zaznaczenie albo
        wiersz pod kursorem), ZANIM cokolwiek zaznaczy - prawy klik na zwykłej klatce ma zostać
        niczym, a nie przestawiać zaznaczenia."""
        idx = self.table.indexAt(pos)
        sm = self.table.selectionModel()
        pod_kursorem = (self.model._rows[idx.row()] if idx.isValid() else None)
        poza_zaznaczeniem = (idx.isValid() and sm is not None
                             and not sm.isRowSelected(idx.row(), QModelIndex()))
        wersje = self._perspektywa_wersji()
        zapis = self._perspektywa_zapisu()
        if not wersje and not zapis:
            if poza_zaznaczeniem:
                cel = ([pod_kursorem["frame_id"]] if isinstance(pod_kursorem, dict)
                       and "_group" not in pod_kursorem else [])
            else:
                cel = [r["frame_id"] for r in self._selected_data_rows()]
            zapis = bool(queries.isolated_inplace_ops(self.con, cel))
            if not zapis:
                return
        if poza_zaznaczeniem:
            self.table.selectRow(idx.row())
        self.act_keep_version.setVisible(wersje)
        self._sep_zapisu.setVisible(wersje and zapis)
        for act in (self.act_finish_write, self.act_restore_header, self.act_release_file):
            act.setVisible(zapis)
        if wersje:
            self._sync_menu_wersji()
        if zapis:
            self._sync_menu_zapisu()
        # `popup`, nie `exec`: menu nie trzyma własnej pętli zdarzeń, a wybór i tak dochodzi
        # sygnałem `triggered`. Blokujący `exec` zawiesza każdy przebieg bez człowieka przy myszy.
        self._menu_tabeli.popup(self.table.viewport().mapToGlobal(pos))

    def _sync_menu_wersji(self):
        """Uczciwy disabled gestu „Zostaw tę wersję" - z planu liczonego w chwili pokazania menu.

        Pozycja żyje wyłącznie wtedy, gdy jest co skopiować: dokładnie jeden zaznaczony stos, który
        ma w grupie co najmniej jedną wersję z dowodem odrębności względem siebie. Tooltip mówi, ile
        ścieżek pójdzie do schowka - tę samą liczbę, którą potwierdzi pasek po geście - albo
        dlaczego nie ma czego kopiować."""
        wiersze = self._selected_data_rows()
        plan = (queries.keep_version_plan(self.con, wiersze[0]["frame_id"])
                if len(wiersze) == 1 else None)
        if len(wiersze) != 1:
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(i18n.t("grid.version.select_one"))
        elif not plan or not plan["paths"]:
            self.act_keep_version.setEnabled(False)
            self.act_keep_version.setToolTip(i18n.t("grid.version.nothing"))
        else:
            self.act_keep_version.setEnabled(True)
            self.act_keep_version.setToolTip(
                i18n.t_plural("grid.version.keep_tip", len(plan["paths"])))

    def _on_keep_version(self):
        """„Zostaw tę wersję": ścieżki obecnych kopii POZOSTAŁYCH wersji grupy idą do schowka,
        a pasek mówi, ile ich skopiowano. BEZ ZAPISU - Horreum niczego nie kasuje ani nie przenosi:
        usuwa człowiek, poza programem, a skan po usunięciu zdejmie grupę z tej listy (predykat
        wymaga obecnej kopii). Dlatego gest nie woła `stan_porzadkow_changed`: stan bazy się nie
        zmienił.

        Plan liczony OD NOWA w chwili gestu, nie wzięty z menu - między pokazaniem a kliknięciem
        mógł przejść skan. Do schowka trafiają wyłącznie stosy z DOWODEM odrębności względem
        zostawianego (`queries.keep_version_plan`); pochodne tej wersji i członkowie bez dowodu
        zostają, a zdanie liczy tych drugich, żeby cisza schowka o nich nie udawała, że ich nie ma.
        Separator `\\n` - Qt zamienia go w schowku Windows na CRLF."""
        wiersze = self._selected_data_rows()
        if len(wiersze) != 1:
            self.status_message.emit(i18n.t("grid.version.select_one"))
            return
        plan = queries.keep_version_plan(self.con, wiersze[0]["frame_id"])
        if not plan or not plan["paths"]:
            self.status_message.emit(i18n.t("grid.version.nothing"))
            return
        QGuiApplication.clipboard().setText("\n".join(plan["paths"]))
        msg = (i18n.t_plural("grid.version.copied", len(plan["paths"]))
               + i18n.t_plural("grid.version.copied_stacks", plan["stacks"]))
        if plan["unknown"]:
            msg += i18n.t("grid.version.skipped_unknown", n=plan["unknown"])
        self.status_message.emit(msg + i18n.t("grid.version.no_delete"))

    # ---- IZOLACJA ZAPISU W MIEJSCU: drogi wyjścia z GUI (warunek wsadu AR-17 (1)(2)) ----
    # Kopia z operacją zapisu w fazie izolującej (`repo.INPLACE_ISOLATING_PHASES`) jest pomijana
    # przez skan i przez każdą inną mutację pliku. Rdzeń ma trzy drogi wyjścia; tu dostają gesty:
    # „Dokończ zapis" (`writeback.finish_inplace`), „Przywróć nagłówek sprzed zapisu"
    # (`writeback.recover_torn`) i „Zwolnij plik do skanu…" (`repo.release_inplace_op`). Dwie
    # pierwsze czytają i piszą plik, więc idą wątkiem tła przez TEN SAM uchwyt co commit makra
    # (`self._wb`) - a z nim dziedziczą mutex „writeback → Dostawa" i „jeden zapis naraz"
    # (`busy_changed` → gospodarz). Trzecia jest samą bazą i idzie od razu.

    def _perspektywa_zapisu(self):
        """Czy widok stoi w jednej z dwóch perspektyw izolacji zapisu (flagi z `_TRIMY`)."""
        return any(getattr(self, atrybut) for atrybut in _RECEPTY_ZAPISU)

    def _operacje_gestu(self):
        """Operacje izolujące kopie ZAZNACZONYCH klatek - liczone od nowa (menu i gest pytają w swojej
        chwili; między nimi mógł przejść inny zapis). Cel to wyłącznie zaznaczenie, jak na osiach."""
        return queries.isolated_inplace_ops(
            self.con, [r["frame_id"] for r in self._selected_data_rows()])

    def _powod_zajetosci(self):
        """Klucz powodu, dla którego gest izolacji nie może ruszyć teraz, albo `None`. Etap Dostawy
        pisze do bazy w tle, a zapis z tego widoku albo z okna naprawy trzyma pliki - odzysk czy
        dokończenie w środku byłyby drugim pisarzem obok nich."""
        if self._etap_w_biegu:
            return "grid.inplace.busy_stage"
        if self._wb.is_busy or self._foreign_wb:
            return "grid.inplace.busy_write"
        return None

    def _sync_menu_zapisu(self):
        """Uczciwy disabled trzech gestów izolacji - ze stanu liczonego w chwili pokazania menu.

        Każda pozycja mówi w tooltipie, ile kopii ruszy, albo DLACZEGO nie ruszy żadnej: zajętość
        (etap, inny zapis), brak kopii izolowanej w zaznaczeniu, faza, w której gest nie ma sensu
        („Dokończ" wyłącznie przy zapisie, który czeka na dokończenie - przerwany zapis nie ma czego
        dokańczać). „Przywróć" i „Zwolnij" żyją przy każdej fazie izolującej: przy zapisie
        czekającym na dokończenie powrót rozstrzyga rdzeń kontrolą danych i odmawia z powodem, gdy
        zapis jest poprawny - tooltip mówi o tym z góry."""
        ops = self._operacje_gestu()
        akcje = (self.act_finish_write, self.act_restore_header, self.act_release_file)
        powod = self._powod_zajetosci() or (None if ops else "grid.inplace.none")
        if powod is not None:
            for act in akcje:
                act.setEnabled(False)
                act.setToolTip(i18n.t(powod))
            return
        do_dokonczenia = [o for o in ops if o["phase"] in queries.INPLACE_PENDING_FINISH_PHASES]
        self.act_finish_write.setEnabled(bool(do_dokonczenia))
        self.act_finish_write.setToolTip(
            i18n.t_plural("grid.inplace.finish_tip", len(do_dokonczenia)) if do_dokonczenia
            else i18n.t("grid.inplace.finish_open_only", restore=i18n.t("grid.inplace.restore")))
        tip = i18n.t_plural("grid.inplace.restore_tip", len(ops))
        if do_dokonczenia:
            tip += i18n.t("grid.inplace.restore_tip_written", finish=i18n.t("grid.inplace.finish"))
        self.act_restore_header.setEnabled(True)
        self.act_restore_header.setToolTip(tip)
        self.act_release_file.setEnabled(True)
        self.act_release_file.setToolTip(i18n.t_plural("grid.inplace.release_tip", len(ops)))

    def _on_finish_write(self):
        """„Dokończ zapis": kontrola danych i re-sync operacji `written` zaznaczonych kopii."""
        ops = [o for o in self._operacje_gestu()
               if o["phase"] in queries.INPLACE_PENDING_FINISH_PHASES]
        self._start_gestu_zapisu("finish_inplace", ops, pusty=i18n.t(
            "grid.inplace.finish_open_only", restore=i18n.t("grid.inplace.restore")))

    def _on_restore_header(self):
        """„Przywróć nagłówek sprzed zapisu": odzysk operacji otwartej albo droga powrotu z fazy
        czekającej na dokończenie - rozstrzyga rdzeń pod blokadą pliku (`writeback.recover_torn`)."""
        self._start_gestu_zapisu("recover_torn", self._operacje_gestu(),
                                 pusty=i18n.t("grid.inplace.none"))

    def _start_gestu_zapisu(self, op, ops, *, pusty):
        """Wspólny start dwóch gestów plikowych: bramka zajętości i pustego celu (druga linia za
        wygaszeniem - bramka woła slot, nie pozycję menu), potem wątek tła `self._wb`. Cel klatek
        zapamiętany TU, nie w ogonie: w trakcie biegu człowiek może zmienić zaznaczenie."""
        powod = self._powod_zajetosci()
        if powod is not None:
            self.status_message.emit(i18n.t(powod))
            return
        if not ops:
            self.status_message.emit(pusty)
            return
        self._cel_gestu_zapisu = sorted({o["frame_id"] for o in ops})
        self._start_writeback(op, [o["op_id"] for o in ops], self._after_gestu_zapisu)

    @Slot(str, object)
    def _after_gestu_zapisu(self, op, res):
        """Ogon gestu plikowego na wątku głównym: szuflada wraca ze stanu postępu (bez zdejmowania
        „Cofnij" poprzedniego commitu), zdanie wyniku idzie do szuflady i na pasek."""
        self.drawer.end_progress()
        if self._undo_mode is not None:
            self.drawer.set_commit_actions_visible(False)
        self._po_gescie_zapisu(_zdanie_gestu_zapisu(op, res), self._cel_gestu_zapisu)

    def _on_release_file(self):
        """„Zwolnij plik do skanu…": jawne zwolnienie izolacji RĘKĄ (`repo.release_inplace_op`).

        To jest rozstrzygnięcie człowieka, że plik jest w porządku (np. przywrócony z pełnej
        kopii), więc okno żąda powodu - bez niego przycisk jest wygaszony - a powód idzie do
        zdarzenia `location.writeback_released`. Plik nietknięty; samą bazą, więc bez wątku tła.
        Operacja, która przestała izolować między menu a gestem (inny proces ją domknął), jest
        liczona osobno z powodem klingi - reszta idzie dalej."""
        powod = self._powod_zajetosci()
        if powod is not None:
            self.status_message.emit(i18n.t(powod))
            return
        ops = self._operacje_gestu()
        if not ops:
            self.status_message.emit(i18n.t("grid.inplace.none"))
            return
        dlg = ReleaseDialog(len(ops), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        uzasadnienie = dlg.reason()
        zwolnione, odmowy = 0, []
        for o in ops:
            try:
                repo.release_inplace_op(self.con, op_id=o["op_id"], now=self._now(),
                                        reason=uzasadnienie)
                zwolnione += 1
            except ValueError as exc:
                odmowy.append((o["path"], str(exc)))
        msg = i18n.t_plural("grid.inplace.released", zwolnione)
        if odmowy:
            msg += i18n.t_plural("grid.inplace.refused", len(odmowy))
            msg += i18n.t("grid.inplace.detail", file=_ogon_sciezki(odmowy[0][0]),
                          detail=odmowy[0][1])
        self._po_gescie_zapisu(msg, sorted({o["frame_id"] for o in ops}))

    def _po_gescie_zapisu(self, msg, cel):
        """Wspólny ogon trzech gestów izolacji: odświeżenie zbioru z celem w zaznaczeniu, człon
        „poza widokiem" (w perspektywach zapisu udany gest WYPYCHA klatkę - to jest jego skutek),
        szuflada, plakietka Porządków i JEDNO zdanie po odświeżeniu (`refresh()` kończy własnym
        zdaniem, które zjadłoby wcześniejsze - lekcja `_po_gescie_osi`). Plakietka zawsze: gest
        rozstrzyga rdzeń, a porażka w połowie też mogła zmienić fazę."""
        self.refresh()
        fakt, recepta = self._czlon_poza_widokiem(
            len(cel) - self._przywroc_zaznaczenie(cel), cel)
        self._refresh_drawer()
        self.drawer.set_result(msg)
        self.stan_porzadkow_changed.emit()
        self.status_message.emit(msg + fakt)
        self.status_recipe.emit(recepta)

    # ---- panel inspekcji daty (G1/G4 — RenameBar) ----
    def _selected_data_rows(self):
        """Wiersze-klatki (bez markerów grup) dla zaznaczenia. Puste zaznaczenie → [].

        Z ZAKRESÓW zaznaczenia, nie z `selectedRows()` (R-S2b-7). `QItemSelectionRange.indexes()`
        woła `model.flags()` dla KAŻDEJ komórki zakresu i buduje `QModelIndex` per wiersz —
        zmierzone **1,06 s** na 16 648 zaznaczonych klatkach, czyli ta sama klasa kosztu, którą
        `b5d1b5c` zdjęło z przeładowania tabeli. Zakresy niosą samą geometrię (O(zakresów)),
        a jedyne, czego ta metoda potrzebuje, to NUMERY wierszy.

        Filtr `"_group" not in row` zostaje jedynym sitem i to on odtwarza kontrakt starej wersji:
        `indexes()` odsiewał nagłówki grup przez `ItemIsSelectable`, zakres ich nie odsieje, bo nie
        pyta modelu o flagi. Zakresy potrafią się nakładać (kontrakt Qt), więc numery deduplikujemy
        — inaczej klatka wpadłaby do zapisu dwa razy.

        KOLEJNOŚĆ ZMIENIA SIĘ ŚWIADOMIE: `selectedRows()` oddawał wiersze w kolejności KLIKANIA,
        ta droga — w kolejności w tabeli. Sprawdzone na parytecie (zbiór identyczny w każdym
        przypadku, także przy zakresach nakładających się i przy grupowaniu) oraz u wszystkich
        pięciu wołających: każdy bierze zbiór albo długość, żaden nie stoi na kolejności kliknięć.
        Porządek wierszowy jest przy tym DETERMINISTYCZNY, a tamten zależał od tego, jak user
        klikał."""
        sm = self.table.selectionModel()
        if sm is None:
            return []
        numery = set()
        for zakres in sm.selection():
            numery.update(range(zakres.top(), zakres.bottom() + 1))
        out = []
        for i in sorted(numery):
            row = self.model._rows[i]
            if isinstance(row, dict) and "_group" not in row:
                out.append(row)
        return out

    def _refresh_date_echo(self):
        """Odśwież panel daty RenameBar z zaznaczenia (albo widocznych, gdy puste). G1 ŚWIADOMIE
        WARUNKOWE (R1 #17): przy ZAMKNIĘTYM panelu echo zaznaczenia niesie już licznik G2 — pełne
        echo daty wymaga otwartego panelu renamu (przepływ renamu i tak dzieje się przy otwartym;
        `_toggle_panel` woła echo PO pokazaniu strony — F3R#4)."""
        if not self._rename_panel_open():
            return
        scope = self._selected_data_rows() or self.model._data_rows
        if len(scope) == 1:
            r = scope[0]
            h = naming.header_dt(r.get("date_obs"))
            fn = naming.filename_dt(os.path.basename(r["path"])) if r.get("path") else None
            primary = (i18n.t("grid.echo.dateobs", ts=f"{h:%Y-%m-%d %H:%M:%S}") if h
                       else i18n.t("grid.echo.dateobs_none"))
            secondary = (i18n.t("grid.echo.fname_time", ts=f"{fn:%Y-%m-%d %H:%M:%S}") if fn
                         else i18n.t("grid.echo.fname_none"))
            d = r.get("_dt_delta")
            if d is None:
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta_none"),
                                         i18n.t("grid.echo.no_time_src"), flag_role="secondary")
            else:
                flag = i18n.t("grid.echo.delta_subhour") if abs(d - round(d)) > 1e-9 else ""
                self.rename_bar.set_echo(primary, secondary, i18n.t("grid.echo.delta", d=f"{d:g}"), flag)
            return
        # wsad (>1): mediana Δ + rozrzut (1 interakcja/wsad, §5b briefu-matki) + align
        deltas = [r["_dt_delta"] for r in scope if r.get("_dt_delta") is not None]
        primary = i18n.t("grid.echo.batch", n=len(scope), both=len(deltas))
        if deltas:
            med = statistics.median(deltas)
            spread = max(deltas) - min(deltas)
            self.rename_bar.set_echo(primary,
                                     i18n.t("grid.echo.batch_stats", med=f"{med:g}", spread=f"{spread:g}"),
                                     "", "", median=med, spread=spread)
        else:
            self.rename_bar.set_echo(primary, i18n.t("grid.echo.no_time_batch"), "", "")

    def set_busy(self, busy):
        """Podczas etapu pipeline'u wyłącz akcje ZAPISU grida (makro/rename/staging/commit/undo) — worker
        pisze do bazy w tle (wizytator C1). Po etapie przywróć SZCZERE stany (paski wg widocznych klatek,
        commit/odrzuć wg liczby oczekujących AKTYWNEJ klingi); nie tykamy etykiet/widoczności szuflady (D2).
        Gesty izolacji zapisu w miejscu nie mają stałej kontrolki - stan menu liczy się przy jego
        pokazaniu, więc zapamiętujemy sam fakt biegu (`_powod_zajetosci`)."""
        self._etap_w_biegu = bool(busy)
        if busy:
            self.macro_bar.set_actions_enabled(False)
            self.rename_bar.set_actions_enabled(False)
            self.sel_bar.btn_proj.setEnabled(False)      # „Wydaj" gaśnie w biegu etapu (F3R#7)
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            # Panel „Rodowód" to CZWARTA powierzchnia zapisu (I-2d) i pisze do tego samego stołu,
            # który worker właśnie przelicza — bez tej linii werdykt ręki wchodził w środek etapu.
            self.lineage_bar.set_busy(True)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            self.macro_bar.set_actions_enabled(bool(self._frame_ids))
            self.rename_bar.set_actions_enabled(bool(self._frame_ids))
            self.sel_bar.set_have_frames(bool(self._frame_ids))
            n = self._active_pending_count()             # mode-aware (R1 #2): makro LUB rename
            self.drawer.btn_commit.setEnabled(n > 0)
            self.drawer.btn_reject.setEnabled(n > 0)
            self.lineage_bar.set_busy(False)             # panel wraca do stanu z zaznaczenia
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._sync_staging_mutex()

    def set_writeback_busy(self, busy):
        """DRUGA powierzchnia writebacku (dialog „Napraw nagłówek…") pisze do plików — wygaś
        Zatwierdź/Odrzuć/Cofnij (D-PD-3). To NIE to samo co `set_busy`: tam pisze pipeline do BAZY
        i gasną wszystkie akcje zapisu; tu chodzi o jeden zasób — mutację plików pod jedną
        transakcją. Własny bieg gridu tej ścieżki nie używa (jego akcje są wtedy schowane paskiem
        postępu), więc flaga mówi wyłącznie o CUDZEJ operacji."""
        self._foreign_wb = busy
        if busy:
            self.drawer.btn_commit.setEnabled(False)
            self.drawer.btn_reject.setEnabled(False)
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(False)
        else:
            if hasattr(self, "_undo_btn"):
                self._undo_btn.setEnabled(True)
            self._refresh_drawer()                       # szczere stany wg oczekujących AKTYWNEJ klingi

    # ---- makro / staging (KROK 4, druga klinga) ----
    def _targets_fn(self, frame_ids):
        return queries.writeback_frame_targets(self.con, frame_ids)

    def _cards_fn(self, frame_id):
        return queries.frame_cards(self.con, frame_id)

    def _run(self, md, run_id=None):
        """Uruchom makro nad widocznymi frame_ids (czysty silnik + wstrzyknięte akcesory). Błąd
        DEFINICJI makra (skladnia/węzeł) → komunikat, None."""
        try:
            return macro_mod.run_macro(md, self._frame_ids, targets_fn=self._targets_fn,
                                       cards_fn=self._cards_fn, run_id=run_id)
        except (macro_mod.expr.ExprError, ValueError) as exc:
            # Błąd DEFINICJI makra → sprzężenie w szufladzie + status (bez modalu — doktryna §5, #3).
            self.drawer.set_count(self._pending_count(), result=i18n.t("grid.macro.error", exc=exc))
            self.status_message.emit(i18n.t("grid.macro.error", exc=exc))
            return None

    def _show_preview(self, run):
        """Wrzuć podgląd makra do modelu (stara→nowa / pominięto) i zwróć (touched, skipped).
        Grid kluczuje FRAME, a touched niesie location_id → mapuj przez `location.frame_id`."""
        self._note_preview_takeover("macro")
        preview = {}
        for pv in run.touched:
            fid = self._frame_for_location(pv.location_id)
            if fid is not None:
                preview[fid] = {"keyword": pv.keyword, "old": pv.old_value, "new": pv.new_value,
                                "op": pv.op}
        for sk in run.skipped:
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview)
        return len(run.touched), len(run.skipped)

    def _frame_for_location(self, location_id):
        return queries.frame_for_location(self.con, location_id)

    def _on_macro_preview(self, md):
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames_count"))
            return
        run = self._run(md)
        if run is None:
            return
        t, s = self._show_preview(run)
        self.status_message.emit(i18n.t("grid.macro.preview_result", t=t, s=s))

    def _on_macro_stage(self, md):
        if not self._frame_ids:
            self.status_message.emit(i18n.t("grid.macro.no_frames"))
            return
        if self._rename_pending_count() > 0:             # mutex symetryczny: staging renamu w toku
            self.status_message.emit(i18n.t("grid.macro.staging_busy"))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        if self._run_id is None:
            self._run_id = uuid.uuid4().hex
        repo.clear_pending_for_run(self.con, self._run_id)   # idempotentny re-stage (R#5)
        run = self._run(md, run_id=self._run_id)
        if run is None:
            return
        for p in run.touched:
            repo.stage_pending(
                self.con, run_id=self._run_id, location_id=p.location_id, keyword=p.keyword,
                idx=p.idx, op=p.op, old_value=p.old_value, new_value=p.new_value,
                new_type=p.new_type, new_comment=p.comment,
                expected_header_hash=p.expected_header_hash)
        self._show_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.macro.staged", t=len(run.touched), s=len(run.skipped)))

    def _on_macro_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit(i18n.t("grid.macro.preview_cleared"))

    def _pending_count(self):
        if self._run_id is None:
            return 0
        return sum(1 for r in writeback.pending_for_run(self.con, self._run_id)
                   if r["status"] == "pending")

    def _rename_pending_count(self):
        if self._rename_run_id is None:
            return 0
        return sum(1 for r in writeback.renames_for_run(self.con, self._rename_run_id)
                   if r["status"] == "pending")

    def _active_pending_count(self):
        """Oczekujące AKTYWNEJ klingi. Staging jest MUTEX — najwyżej jedna niepusta, więc `or` wybiera ją."""
        return self._pending_count() or self._rename_pending_count()

    def _sync_staging_mutex(self):
        """Staging na WYŁĄCZNOŚĆ: „Do stagingu" jednej klingi disabled+tooltip, gdy druga ma pending
        (R2 #8 — stan widoczny BEZ klikania). AUTORYTATYWNY nad `btn_stage`: gdy druga klinga zwolni
        staging, re-enable wg widocznych klatek (inaczej przycisk zostałby wyszarzony). Wołane po każdej
        zmianie stagingu i w refresh() (po `set_actions_enabled`)."""
        macro_n, rename_n = self._pending_count(), self._rename_pending_count()
        has_frames = bool(self._frame_ids)
        if macro_n > 0:
            self.rename_bar.btn_stage.setEnabled(False)
            self.rename_bar.btn_stage.setToolTip(f"staging makra w toku ({macro_n} zmian)")
        else:
            self.rename_bar.btn_stage.setEnabled(has_frames)
            self.rename_bar.btn_stage.setToolTip("")
        if rename_n > 0:
            self.macro_bar.btn_stage.setEnabled(False)
            self.macro_bar.btn_stage.setToolTip(i18n.t("grid.rename.staging_busy_tip", n=rename_n))
        else:
            self.macro_bar.btn_stage.setEnabled(has_frames)
            self.macro_bar.btn_stage.setToolTip("")

    def _refresh_drawer(self):
        """Szuflada MODE-AWARE (R1 #2): pokazuje AKTYWNĄ klingę (staging mutex → najwyżej jedna niepusta).
        Rename → „N zmian nazw oczekuje" (mikro-zmiana §0); makro → domyślny. Gdy pending=0 ale „Cofnij"
        widoczny (świeży commit), NIE nadpisuj etykiety „Zatwierdzono/Przemianowano" pustostanem (D2/#2)."""
        rn = self._rename_pending_count()
        macro_n = self._pending_count()
        if rn > 0:
            self.drawer.set_count(rn, label=i18n.t("grid.drawer.pending_rename", n=rn))
        elif macro_n > 0:
            self.drawer.set_count(macro_n)
        elif self._undo_mode is None:         # brak pending i brak świeżego „Cofnij" → pustostan
            self.drawer.set_count(0)          # (sygnał stanu, NIE isVisible() — zawodne bez show())
        # else: undo oferowany (`_undo_mode` ustawiony) → zachowaj etykietę „Zatwierdzono/Przemianowano"
        self._sync_staging_mutex()

    # ---- writeback off-thread (commit/undo w wątku tła; postęp + „Anuluj" w szufladzie) ----
    @property
    def _writeback_async(self):
        """Seam testowy „inline zamiast QThread" — ustawiany Z ZEWNĄTRZ na WIDOKU (cztery testy),
        a mieszkający na uchwycie. Property z getterem i SETTEREM, żeby oba zapisy trafiały w to
        samo miejsce po wydzieleniu wykonawcy (D-PD-3)."""
        return self._wb.async_ok

    @_writeback_async.setter
    def _writeback_async(self, value):
        self._wb.async_ok = value

    def _start_writeback(self, op, target_id, after_slot):
        """Odpal `op` (commit/commit_rename/undo/undo_rename) na wątku tła; postęp → szuflada, `done`
        → `after_slot` (post-processing na wątku GŁÓWNYM). Cykl wątku trzyma uchwyt `self._wb`;
        TUTAJ zostają wyłącznie rzeczy widżetowe (pasek szuflady, wygaszenie „Do stagingu")."""
        if self._wb.is_busy or self._foreign_wb:         # jeden writeback naraz (akcje i tak schowane)
            return
        self._wb_target_id = target_id
        self.drawer.begin_progress(0)
        self.macro_bar.btn_stage.setEnabled(False)       # bez nowego stagingu w biegu
        self.rename_bar.btn_stage.setEnabled(False)
        self._wb.start(op, target_id, on_progress=self._on_wb_progress, on_done=after_slot,
                       on_failed=self._on_wb_failed)

    @Slot(int, int, str, str)
    def _on_wb_progress(self, done, total, path, status):
        self.drawer.update_progress(done, total, path)

    @Slot(str, str)
    def _on_wb_failed(self, op, msg):
        self.drawer.end_progress()
        self.drawer.set_count(self._active_pending_count(), result=i18n.t("grid.wb.error", msg=msg))
        self.refresh()
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.wb.failed", op=op, msg=msg))
        # Wyjątek w ŚRODKU operacji nie mówi, ile plików zdążyło się zmienić (każdy plik to osobny
        # zapis), a przerwany zapis w miejscu sam jest wierszem Porządków (kopia izolowana) - więc
        # plakietka liczy się ze stanu także tu, bez zgadywania, czy coś się zapisało.
        self.stan_porzadkow_changed.emit()

    def _on_wb_cancel(self):
        if self._wb.is_busy:
            self._wb.cancel()                            # rdzeń sprawdza PRZED następnym plikiem
            self.drawer.btn_cancel.setEnabled(False)
            self.status_message.emit(i18n.t("grid.wb.cancelling"))

    def _commit_summary(self, res, noun_key):
        """Podsumowanie CommitResult: „N {noun} · M zablokowanych · …" + pierwszy powód (wiz #4).
        `noun_key` = klucz frazy głównej (`grid.wb.applied`/`grid.wb.renamed`) — DANE, nie string PL."""
        return zdanie_wyniku_zapisu(res, noun_key)       # jedno zdanie dla trzech powierzchni (Z11)

    def _on_commit(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_commit_rename()
            return
        if self._run_id is None:
            return
        self._start_writeback("commit", self._run_id, self._after_commit)

    def _after_commit(self, op, res):
        """Post-processing commitu makra (wątek główny). Anulowano → część 'pending' została w runie:
        run zostaje otwarty do dokończenia, bez „Cofnij" (zapisane siedzą w commits — undo po CLI)."""
        self.drawer.end_progress()
        summary = self._commit_summary(res, "grid.wb.applied")
        remaining = self._pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, result=summary)
        elif commit_do_cofniecia(res) is not None:       # także `failed` z kopią nagłówka (Z11)
            summary += i18n.t("grid.wb.commit_id", id=res.commit_id)
            self._last_commit_id = res.commit_id
            self._install_undo(res.commit_id, summary, applied=len(res.applied))
            self._run_id = None                          # R#5: run domknięty commitem
        else:                                            # wszystko blocked/failed/skipped
            self.drawer.set_count(0, result=summary)
            self._run_id = None
        self.model.set_preview({})
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe wartości
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.wb.status", summary=summary))
        # Karta w pliku to zeznanie klatki (`header`, `cards`), a z niego liczą się wiersze Porządków
        # („Nagłówek inny niż folder", kopie niezgodne…) - więc commit, który COKOLWIEK podmienił,
        # rusza plakietkę. Warunek to reguła „Cofnij" (plik zmieniony, także `failed` z kopią
        # nagłówka) albo niepuste `applied` przy przerwaniu anulowaniem.
        if res.applied or commit_do_cofniecia(res) is not None:
            self.stan_porzadkow_changed.emit()

    def _install_undo(self, commit_id, summary, applied):
        """Po udanym commicie makra szuflada oferuje jednorazowe „Cofnij" (undo całego commitu). Etykieta
        „Zatwierdzono…" zamiast pustostanu, by nie przeczyła wynikowi obok (wizytator D2)."""
        self.drawer.set_count(0, result=summary,
                              label=i18n.t("grid.wb.committed_label", n=applied, id=commit_id))
        self.drawer.set_commit_actions_visible(False)   # jedyna sensowna akcja teraz to Cofnij (#5)
        self._undo_commit_id = commit_id
        self._undo_mode = "macro"                        # dispatch współdzielonego „Cofnij" (R1 #3)
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _ensure_undo_button(self):
        """Współdzielony przycisk „Cofnij" (tworzony RAZ, stabilny handler → dispatch po `_undo_mode`;
        bez churnu connect/disconnect, który sypał RuntimeWarning — wzorzec makra)."""
        if not hasattr(self, "_undo_btn"):
            self._undo_btn = QPushButton(i18n.t("grid.action.undo"))
            self._undo_btn.clicked.connect(self._dispatch_undo)
            self.drawer.layout().addWidget(self._undo_btn)

    def _dismiss_undo(self):
        """Nowa operacja stagingu UNIEWAŻNIA „Cofnij" poprzedniego commitu (transient undo wygasa — inny
        run w toku). Chowa przycisk + zeruje `_undo_mode`, żeby leftover „Cofnij" nie dispatchował undo
        starej klingi na wierzch świeżego stagingu = osierocenie pending + zakleszczenie mutexa bez
        widocznego powodu (recenzent #1, wizytator #3). Wołane na starcie stagingu obu kling."""
        if hasattr(self, "_undo_btn"):
            self._undo_btn.setVisible(False)
        self._undo_mode = None

    def _dispatch_undo(self):
        """Współdzielony „Cofnij" woła undo AKTYWNEJ klingi wg `_undo_mode` (R1 #3, init None)."""
        if self._undo_mode == "rename":
            self._on_undo_rename(self._undo_rename_run_id)
        else:
            self._on_undo(self._undo_commit_id)

    def _on_undo(self, commit_id):
        self._start_writeback("undo", commit_id, self._after_undo)

    def _after_undo(self, op, res):
        msg = i18n.t("grid.wb.restored", n=len(res.restored))
        if res.blocked:
            msg += " · " + i18n.t("grid.wb.blocked", n=len(res.blocked))
        self.drawer.end_progress()
        self._undo_btn.setVisible(False)
        self._undo_mode = None
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self._refresh_drawer()                           # honest: odbij pending drugiej klingi (wiz #3b)
        self.status_message.emit(i18n.t("grid.wb.undo_status", msg=msg))
        # Lustro commitu: zeznanie wróciło (patrz `_after_commit`). `failed` też rusza plakietkę -
        # cofnięcie w miejscu kończy się nim przy kopii izolowanej, a wtedy zmienia się wiersz
        # „Plik po przerwanym zapisie". Licz ze stanu, jak `_on_wb_failed`, zamiast zgadywać.
        if res.restored or res.failed:
            self.stan_porzadkow_changed.emit()

    def _on_reject(self):
        if self._rename_pending_count() > 0:             # szuflada aktywnej klingi (staging mutex)
            self._on_reject_rename()
            return
        if self._run_id is None:
            return
        n = self._pending_count()
        repo.clear_pending_for_run(self.con, self._run_id)
        self._run_id = None
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t("grid.wb.rejected", n=n))   # trwałe sprzężenie w szufladzie (#3)
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t("grid.wb.rejected", n=n))

    # ---- rename „Nazwy z faktów" (druga klinga plików: os.rename) ----
    def _note_preview_takeover(self, new_owner):
        """Podgląd współdzielony (jeden `_preview`, R1 #19): przejęcie przez drugą klingę zdejmuje
        pierwszy — komunikat w statusie, żeby zniknięcie nie było ciche. Wołane PRZED `set_preview`."""
        if (self._preview_owner and self._preview_owner != new_owner
                and self.model._preview_active()):
            other = (i18n.t("grid.preview.owner_macro") if self._preview_owner == "macro"
                     else i18n.t("grid.preview.owner_rename"))
            self.status_message.emit(i18n.t("grid.preview.takeover", other=other))
        self._preview_owner = new_owner

    def _rename_target_ids(self):
        """Cel wsadu renamu (D-I1): zaznaczenie jeśli niepuste, inaczej wszystkie widoczne. Zwraca
        (frame_ids, ZAMROŻONY opis celu) — opis idzie do statusu po akcji (R2 #10, cel ruchomy)."""
        rows = self._selected_data_rows()
        if rows:
            return [r["frame_id"] for r in rows], f"{len(rows)} zaznaczonych"
        return list(self._frame_ids), f"{self._n_total} widocznych"

    def _run_rename(self, ids, policy, run_id=None):
        return naming.run_rename(
            ids, targets_fn=lambda i: queries.rename_frame_targets(self.con, i),
            source=policy["source"], offset_hours=policy["offset_hours"],
            template=policy.get("template") or naming.DEFAULT_TEMPLATE,
            fallback=policy["fallback"], run_id=run_id)

    def _show_rename_preview(self, run):
        """Podgląd renamu do modelu (nazwa stara→nowa / pominięto). `RenamePreview` niesie `frame_id`
        WPROST (bez mapowania location→frame jak makro). Etykieta kolumny „nazwa →" (R1 #4)."""
        self._note_preview_takeover("rename")
        preview = {}
        for pv in run.touched:
            preview[pv.frame_id] = {"keyword": "nazwa pliku", "op": "rename",
                                    "old": os.path.basename(pv.old_path),
                                    "new": os.path.basename(pv.new_path)}
        for sk in run.skipped:
            preview[sk.frame_id] = {"skipped": sk.reason}
        self.model.set_preview(preview, label=i18n.t("grid.preview.name"))
        return len(run.touched), len(run.skipped)

    def _on_rename_preview(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_count"))
            return
        try:
            run = self._run_rename(ids, policy)
        except ValueError as e:                          # zły regex orig we wzorze (INFORMUJ)
            self.status_message.emit(i18n.t("grid.rename.error", e=e))
            return
        t, s = self._show_rename_preview(run)
        self.status_message.emit(i18n.t("grid.rename.preview_result", t=t, s=s, target=target))

    def _on_rename_stage(self, policy):
        ids, target = self._rename_target_ids()
        if not ids:
            self.status_message.emit(i18n.t("grid.rename.no_frames"))
            return
        if self._pending_count() > 0:                    # mutex: staging makra w toku
            self.status_message.emit(i18n.t("grid.rename.staging_busy"))
            return
        self._dismiss_undo()                             # nowy staging unieważnia leftover „Cofnij" (wiz #3)
        # Pętla życia run_id (R1 #1 + R2 #1): run niecommitowany → clear (bezpieczne, same 'pending');
        # run skommitowany → MINTUJ NOWY (clear skasowałby wiersze 'applied' = rekordy undo).
        try:
            naming.validate_template(policy.get("template") or naming.DEFAULT_TEMPLATE)  # zły regex → stop przed mintem
        except ValueError as e:
            self.status_message.emit(i18n.t("grid.rename.error", e=e))
            return
        if self._rename_run_id is None or self._rename_run_committed:
            self._rename_run_id = uuid.uuid4().hex
            self._rename_run_committed = False
        else:
            repo.clear_renames_for_run(self.con, self._rename_run_id)
        run = self._run_rename(ids, policy, run_id=self._rename_run_id)
        for p in run.touched:
            repo.stage_rename(self.con, run_id=self._rename_run_id, location_id=p.location_id,
                              old_path=p.old_path, new_path=p.new_path, expected_mtime=p.mtime)
        self._show_rename_preview(run)
        self._refresh_drawer()
        self.status_message.emit(i18n.t(
            "grid.rename.staged", t=len(run.touched), s=len(run.skipped), target=target))

    def _on_rename_clear(self):
        self.model.set_preview({})
        self._preview_owner = None
        self.status_message.emit(i18n.t("grid.rename.preview_cleared"))

    def _on_commit_rename(self):
        run_id = self._rename_run_id
        if run_id is None:
            return
        self._start_writeback("commit_rename", run_id, self._after_commit_rename)

    def _after_commit_rename(self, op, res):
        """Post-processing commitu renamu (wątek główny). Anulowano → reszta nazw została 'pending':
        run zostaje otwarty do dokończenia, bez „Cofnij"."""
        self.drawer.end_progress()
        run_id = self._wb_target_id
        summary = self._commit_summary(res, "grid.wb.renamed")
        remaining = self._rename_pending_count()
        if remaining > 0:                                # przerwane anulowaniem
            summary += i18n.t("grid.wb.interrupted", n=remaining)
            self.drawer.set_count(remaining, label=i18n.t("grid.drawer.pending_rename", n=remaining),
                                  result=summary)
        elif res.applied:                                # Cofnij TYLKO gdy coś zrobione (R2 #6)
            summary += i18n.t("grid.wb.run_id", id=run_id)   # run_id w wyniku: undo po restarcie przez CLI (R2 #7)
            self._undo_rename_run_id = run_id            # PRZECHWYĆ cel Cofnij przed re-stage (R2 #1)
            self._rename_run_committed = True
            self._install_rename_undo(run_id, summary, applied=len(res.applied))
        else:                                            # wszystko blocked/failed → run zwolniony
            self._rename_run_id = None
            self._rename_run_committed = False
            self.drawer.set_count(0, result=summary)
        self.model.set_preview({})
        self._preview_owner = None
        self.refresh()                                   # baza odświeżona — grid pokazuje nowe ścieżki
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.rename.status_summary", summary=summary))
        if res.applied:                                  # ogon zapisu → plakietka (definicja sygnału)
            self.stan_porzadkow_changed.emit()

    def _install_rename_undo(self, run_id, summary, applied):
        """Po udanym rename szuflada oferuje „Cofnij" (undo_renames przebiegu). Lustro `_install_undo`
        makra, tryb `rename` (dispatch współdzielonego przycisku). Etykieta CZYSTA (bez 32-hex szumu);
        pełny run_id zostaje w `result`=summary jako kotwica CLI-undo po restarcie (R2 #7, wiz #6)."""
        self.drawer.set_count(0, result=summary, label=i18n.t("grid.rename.renamed_label", n=applied))
        self.drawer.set_commit_actions_visible(False)
        self._undo_mode = "rename"
        self._ensure_undo_button()
        self._undo_btn.setVisible(True)

    def _on_undo_rename(self, run_id):
        self._start_writeback("undo_rename", run_id, self._after_undo_rename)

    def _after_undo_rename(self, op, res):
        msg = i18n.t("grid.wb.restored", n=len(res.restored))
        if res.blocked:
            msg += " · " + i18n.t("grid.wb.blocked", n=len(res.blocked))
        self.drawer.end_progress()
        self._undo_rename_run_id = None
        self._undo_mode = None
        self._rename_run_id = None
        self._rename_run_committed = False
        self._undo_btn.setVisible(False)
        self.drawer.set_commit_actions_visible(True)     # przywróć akcje po cofnięciu (#5)
        self.drawer.set_count(0, result=msg)
        self.refresh()
        self._refresh_drawer()
        self.status_message.emit(i18n.t("grid.rename.undo_status", msg=msg))
        if res.restored:                                 # lustro commitu renamu
            self.stan_porzadkow_changed.emit()

    def _on_reject_rename(self):
        if self._rename_run_id is None:
            return
        n = self._rename_pending_count()
        repo.clear_renames_for_run(self.con, self._rename_run_id)
        self._rename_run_id = None
        self._rename_run_committed = False
        self.model.set_preview({})
        self._preview_owner = None
        self.drawer.set_count(0, result=i18n.t("grid.rename.rejected", n=n))
        self._sync_staging_mutex()
        self.status_message.emit(i18n.t("grid.rename.rejected", n=n))
