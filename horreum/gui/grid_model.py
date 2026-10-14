"""Model tabeli widoku „Klatki" - kolumny, perspektywy, recepty i `GridTableModel`.

Warstwa widżetów (whitelista `test_gui_isolation`). Stałe kolumn i presetów, tooltipy stanów komórki,
recepty pasków, derywacje wiersza (`_derive`, `_dolacz_kopie`, wersje stosów), edytor komórki i model
Qt czytający kolory motywu na żywo (`_COLORS`, `use_theme`). Importuje go fasada `grid.py`, przez którą
reszta pakietu nadal sięga po te nazwy.
"""

from __future__ import annotations

import json
import math
import os
from typing import NamedTuple

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from horreum import naming, pivot as pivot_mod
from horreum.gui import facet_model, i18n, queries, rows, theme
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
    # „Rodowód" - stan rodowodu GOTOWEGO OBRAZU (`queries.LINEAGE_STATES`, `_adnotuj_rodowod`);
    # klatka innego rodzaju ma komórkę pustą (n.d.). Na końcu z tego samego powodu co „Obrazy".
    ("grid.col.lineage", "_rodowod"),
]
# PREZENTACJA ZNAJDŹ - ten sam model i ten sam zbiór, inny zestaw kolumn bazowych: to, po co człowiek
# przychodzi z pytaniem („co mam z tej nocy, w tym filtrze"), bez kolumn warsztatu (Δh, Obrazy,
# keywordy). Plik stoi OSTATNI, bo w tej prezentacji jest adresem, a nie przedmiotem pracy. Klucze
# `night`/`note` niesie `queries.base_rows` (kolumny dopisane na końcu SELECT-u), `_zestaw` liczy
# `_derive`. Kolumny keywordów zostają w modelu i chowa je widok - przełączenie prezentacji nie
# przeładowuje zbioru (`FramesView.set_presentation`).
FIND_COLS = [
    ("object.col.name", "_object"), ("find.col.night", "night"), ("frame.col.filter", "filter_canon"),
    ("find.col.exposure", "exptime"), ("find.col.rig", "_zestaw"), ("find.col.notes", "note"),
    ("find.col.file", "path"),
]
PREZENTACJA_ZNAJDZ = "znajdz"
PREZENTACJA_KLASYCZNA = "klasyczna"
# Szerokość kolumny „Uwagi" w px: uwaga ma do 300 znaków, a kolumna ma ją zapowiadać, nie zjadać
# okna - pełna treść idzie tooltipem komórki.
_SZEROKOSC_UWAG = 220
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
    if stan == "hint" and queries.hint_from_stacks_tree(row.get("path"), row.get("library_root")):
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
# PERSPEKTYWY, KTÓRYCH PUSTKA BYWA NIEWIEDZĄ: obie porównują zeznania kopii, a kopia bez zebranych
# faktów w porównaniu nie bierze udziału. Pusta perspektywa przy czekających kandydatach nie znaczy
# „sprawdzone, czysto" - pusty stan mówi wtedy zdaniem podpowiedzi Porządków (`tasks.copies_unread_tip`,
# jeden właściciel zdania) i prowadzi do Dostawy. Bliźniak `tasks._CZEKA_NA_FAKTY_KOPII` (te same
# dwa wiersze Porządków); klucz = flaga z `_TRIMY`.
_FLAGI_CZEKAJA_NA_FAKTY = ("_only_copy_conflict", "_only_orphan_testimony")

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
    # Rola `warn` z akcentów (bez nowego koloru): stan rodowodu „do potwierdzenia" w komórce gridu.
    _COLORS["warn"] = QColor(theme.accents(name)["warn"])


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
# i działa z zaznaczenia jednej klatki, więc wiersz Porządków „Rodowód do potwierdzenia" nie ma dokąd
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
# PRESET_WITHHELD_TESTIMONY - bliźniak AR-82. Plik kopii zapisany, a zeznanie klatki nie przyjęło
# jego nagłówka (głosem mówi inna obecna kopia) - zapis czeka na wskazanie kopii gestem „Ta kopia
# prowadzi”. Kopie bywają zgodne w polach „Kopii niezgodnych”, więc ten stan nie miał powierzchni.
# Predykat `queries.withheld_testimony_frame_ids`. Stała współdzielona z TasksView po nazwie.
PRESET_WITHHELD_TESTIMONY = "Zeznanie wstrzymane"
# PRESET_KEPT_COPIES - bliźniak AR-64. Rekoncyliacja przerwanej podmiany nie mogła dowieść stanu
# plików i zostawiła kopie obok ścieżki (wyparta, zwrotna, tymczasowa) - człowiek je porównuje
# i usuwa zbędne. Predykat `queries.kept_copy_frame_ids`. Stała współdzielona z TasksView po nazwie.
PRESET_KEPT_COPIES = "Kopie zostawione do oka"
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
# PRESET_FILE_OBJECT_MISMATCH - czternasty bliźniak (AR-17 krok 3). Klatka ma obiekt, a jej plik
# leży w folderze innego obiektu albo karta `OBJECT` mówi inną formą (E5-1: folderami zarządza
# Horreum). Robotą jest gest „Uzgodnij pliki…" (menu prawego kliku w tej perspektywie) - plik
# dogania obiekt, który klatka już ma. Predykat `queries.file_object_mismatch_frame_ids`, ten sam
# co liczba wiersza Porządków. Stała współdzielona z TasksView po nazwie.
PRESET_FILE_OBJECT_MISMATCH = "Plik nie zgadza się z obiektem"
# PRESET_F_RATIO_MISMATCH - piętnasty bliźniak (AR-129). Klatka (light, flat) z zestawem automatu,
# której `FOCRATIO` w pliku odbiega od f/ teleskopu (ręka, potem pliki) ponad tolerancję - na
# archiwum 26 XISF RC8 z f/200 i jeden FITS A140R z f/8. Robotą jest gest „Popraw f/ w plikach…"
# (menu prawego kliku w tej perspektywie) - na życzenie, przez szufladę zapisu z cofnięciem.
# Predykat `queries.f_ratio_mismatch_frame_ids`, ten sam co liczba wiersza Porządków.
PRESET_F_RATIO_MISMATCH = "f/ niezgodna z teleskopem"
# PRESET_XREF_RECONCILE - szesnasty bliźniak (AR-135). Para `catalog_xref` dopisana po fakcie
# (`M33 → NGC598`) zostawia klatki ręki przy obiekcie o kanonie-kluczu i równoważności ręki przy
# innym obiekcie niż cel. Robotą jest gest „Zmień obiekt…” na tych klatkach (cel podaje podpowiedź
# wiersza Porządków). Predykat `queries.xref_reconcile_frame_ids`, ten sam co liczba wiersza.
# Stała współdzielona z TasksView po nazwie.
PRESET_XREF_RECONCILE = "Nazwa katalogowa wskazuje inny obiekt"
# PRESET_READY_IMAGES - gotowe obrazy pogrupowane po stanie rodowodu. Bez flagi `only_*`: zbiór
# niesie ISTNIEJĄCY facet Rodzaj (`master_light`), więc listwa pokazuje go jako wybór, a facet
# „Rodowód" obok zawęża dalej jednym klikiem. Grupowanie po kolumnie „Rodowód" stawia stosy bez
# rodowodu pod własną belką - wcześniej nic ich w tabeli nie odróżniało.
PRESET_READY_IMAGES = "Gotowe obrazy"
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
    PRESET_READY_IMAGES: {"filter": None, "group_by": "_rodowod",
                          "facets": {"kind": {"in": [["master_light", "master_light"]]}}},
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
    PRESET_WITHHELD_TESTIMONY: {"filter": None, "group_by": None,
                                "only_withheld_testimony": True},
    PRESET_KEPT_COPIES: {"filter": None, "group_by": None, "only_kept_copies": True},
    PRESET_PATH_HEADER_CONFLICT: {"filter": None, "group_by": None,
                                  "only_path_header_conflict": True},
    PRESET_TORN_WRITE: {"filter": None, "group_by": None, "only_torn_write": True},
    PRESET_PENDING_FINISH: {"filter": None, "group_by": None, "only_pending_finish": True},
    PRESET_FILE_OBJECT_MISMATCH: {"filter": None, "group_by": None,
                                  "only_file_object_mismatch": True},
    PRESET_F_RATIO_MISMATCH: {"filter": None, "group_by": None, "only_f_ratio_mismatch": True},
    PRESET_XREF_RECONCILE: {"filter": None, "group_by": None, "only_xref_reconcile": True},
    "Do przeglądu": {"filter": None, "group_by": None, "only_review": True},
}
# Etykieta WYŚWIETLANIA presetu (tekst) osobno od TOŻSAMOŚCI (klucz PRESETS w `itemData` — używany przez
# `apply_perspective`/`_on_perspective`/`tasks.py`, odporny na tłumaczenie tekstu). Split D-L3.
_PRESET_LABELS = {
    "Przegląd": "perspective.review",
    "Kalibracja": "perspective.calibration",
    PRESET_READY_IMAGES: "perspective.ready_images",
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
    PRESET_WITHHELD_TESTIMONY: "perspective.withheld_testimony",
    PRESET_KEPT_COPIES: "perspective.kept_copies",
    PRESET_PATH_HEADER_CONFLICT: "perspective.path_header_conflict",
    PRESET_TORN_WRITE: "perspective.torn_write",
    PRESET_PENDING_FINISH: "perspective.pending_finish",
    PRESET_FILE_OBJECT_MISMATCH: "perspective.file_object_mismatch",
    PRESET_F_RATIO_MISMATCH: "perspective.f_ratio_mismatch",
    PRESET_XREF_RECONCILE: "perspective.xref_reconcile",
    "Do przeglądu": "perspective.to_review",
}
# PERSPEKTYWA BEZ ZAWĘŻENIA - jedyny preset, który nie niesie ani filtra, ani flagi `only_*`
# (`PRESETS` wyżej), więc przejście na nią odsłania KAŻDY zbiór: `_on_perspective` przepisuje
# z niej także facety i filtr. Recepta powrotu po geście osi (FC-2) wskazuje ją imiennie, więc
# nazwa nie może być literałem w dwóch miejscach - a bramka pilnuje, że ten preset naprawdę
# jest czysty (`test_gui_grid`, `_PRESET_CZYSTY`).
_PRESET_CZYSTY = "Przegląd"
# Rola pozycji listy perspektyw z etykietą BAZOWĄ (bez sufiksu „(zmieniona)", FH-12).
_ROLA_ETYKIETY = Qt.UserRole + 1
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
    ("_only_withheld_testimony", "withheld_testimony_frame_ids"),
    ("_only_kept_copies", "kept_copy_frame_ids"),
    ("_only_path_header_conflict", "path_header_conflict_frame_ids"),
    ("_only_torn_write", "torn_write_frame_ids"),
    ("_only_pending_finish", "pending_finish_frame_ids"),
    ("_only_file_object_mismatch", "file_object_mismatch_frame_ids"),
    ("_only_f_ratio_mismatch", "f_ratio_mismatch_frame_ids"),
    ("_only_xref_reconcile", "xref_reconcile_frame_ids"),
)

# FLAGA, OD KTÓREJ ZALEŻY ZACHOWANIE WIDOKU, NIE TYLKO ZBIÓR: w perspektywie „Wersje stosów" model
# pokazuje kolumnę „Wersja", a tabela menu z gestem „Zostaw tę wersję". Nazwa atrybutu jako stała,
# nie literał `self._only_…` w źródle - bramka `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`
# pilnuje, żeby rodzina nie dostała drugiej, ręcznej enumeracji; to jest JEDNO odwołanie do jednej
# flagi, a jej obecność w `_TRIMY` pinuje test perspektywy.
_FLAGA_WERSJI = "_only_stack_versions"
# Perspektywa „Zastąpione" dokłada do menu tabeli gest przeniesienia faktów ręki (AR-41) - ta sama
# figura co wyżej: jedno odwołanie do jednej flagi rodziny, pod stałą.
_FLAGA_ZASTAPIONYCH = "_only_superseded"
# Perspektywa „Plik nie zgadza się z obiektem" dokłada do menu tabeli gest „Uzgodnij pliki…"
# (AR-17 krok 3) i przy wejściu podaje jego receptę - ta sama figura: jedna flaga, pod stałą.
_FLAGA_ZGODNOSCI_PLIKU = "_only_file_object_mismatch"
# Perspektywa „f/ niezgodna z teleskopem" dokłada do menu tabeli gest „Popraw f/ w plikach…"
# (AR-129) - ta sama figura: jedna flaga, pod stałą.
_FLAGA_OPTYKI = "_only_f_ratio_mismatch"
# Te same zasady dla dwóch perspektyw izolacji zapisu w miejscu: w nich menu tabeli pokazuje drogi
# wyjścia z izolacji także nad pustym zaznaczeniem (wygaszone z powodem), a wejście w perspektywę
# podaje receptę gestu (`_RECEPTY_ZAPISU`). Klucz = flaga z `_TRIMY`.
_RECEPTY_ZAPISU = {
    "_only_torn_write": "grid.inplace.recipe_torn",
    "_only_pending_finish": "grid.inplace.recipe_pending",
}
# PERSPEKTYWY, W KTÓRYCH KOLUMNA „OBRAZY" MA TREŚĆ - i tylko w nich stoi domyślnie. Fakty kopii
# zbiera się z założenia dla XISF i klatek wielokopiowych (`scan.copy_facts_candidates`), więc na
# kopii żywego archiwum kolumna była pusta w 16 901 z 16 901 wierszy „Przeglądu": stała tam jako
# obietnica bez pokrycia. W tych trzech perspektywach wiersze są kandydatami do zebrania faktów
# (XISF albo klatka wielokopiowa), więc pusta komórka kandydata znaczy „jeszcze nie wiem" i mówi
# to znakiem „?" (`_images_cell`).
# Wybór ręki w „Polach" bije domyślną (`FramesView._obrazy_reka`). Klucz = flaga z `_TRIMY`.
_FLAGI_OBRAZOW = ("_only_dups", "_only_copy_conflict", _FLAGA_WERSJI)
# Perspektywy, w których każda klatka czeka na wskazanie kopii wiodącej (AR-4, AR-23, AR-82): menu
# tabeli pokazuje w nich podmenu „Ta kopia prowadzi" zawsze - przy złym zaznaczeniu wygaszone
# z powodem. Klucz = flaga z `_TRIMY`.
_FLAGI_KOPII_WIODACEJ = ("_only_copy_conflict", "_only_orphan_testimony",
                         "_only_withheld_testimony")
# Perspektywy, w których komórka ścieżki niesie prefiks „×N" albo ścieżkę jako przedmiot decyzji
# (duplikaty, ich podzbiór niezgodnych, wersje stosów, dwie perspektywy izolacji zapisu): tam
# kolumna bierze szerokość z treści z sufitem i elizją w środku (`kolumna_z_tresci`). Gdzie indziej
# zostaje szerokość, którą ustawiła ręka - pamięci szerokości per perspektywa tu nie ma.
# Perspektywy izolacji dochodzą z `_RECEPTY_ZAPISU`, nie z drugiej listy: klatka w izolacji bywa
# klatką wielokopiową, więc komórka niesie „×2" i domyślne 100 px zostawiało z niej sam prefiks.
_FLAGI_SCIEZKI_Z_TRESCI = ("_only_dups", "_only_copy_conflict", _FLAGA_WERSJI, *_RECEPTY_ZAPISU)
# Sufit szerokości kolumny dopasowanej do treści, w px: ścieżka „×2  2026-01-21_…_0001.xisf" mieści
# się z zapasem, a jedna długa nazwa nie wypycha keywordów poza okno 1400 px.
_SUFIT_KOLUMNY_Z_TRESCI = 420


def _klucz_spec(atrybut):
    """Klucz flagi w spec-u perspektywy (`_only_dups` → `only_dups`) - JEDNO miejsce konwencji."""
    return atrybut[1:]


def _klucz_kryterium(atrybut):
    """Klucz i18n flagi na pasku kryteriów (`_only_dups` → `grid.criteria.only_dups`)."""
    return "grid.criteria." + _klucz_spec(atrybut)


# WYGLĄD WIDOKU W SPEC-U PERSPEKTYWY (AR-36) - jeden klucz `view` ze słownikiem, nie klucze obok
# warunków: wygląd nie zmienia ZBIORU, więc `_nieznane_warunki` pomija go w całości, także pola,
# których ten build jeszcze nie zna. W środku: widoczność kolumny „Obrazy" (`True`/`False`, brak =
# za perspektywą) i szerokość kolumny ścieżki w px (brak = liczona przez widok). Starsze wydania
# czytają spec przez `.get` i pomijają nieznany klucz bez wyjątku (zmierzone na `v0.10.0`:
# `_on_perspective` czyta wyłącznie swoje klucze, `queries.perspectives` nieznanych nie rusza).
_SPEC_WIDOK = "view"
_SPEC_OBRAZY = "images"
_SPEC_SZEROKOSC_SCIEZKI = "path_width"
# Klucze spec-a, które TEN build umie zastosować. Flagi `only_*` dochodzą z `_TRIMY`, więc nowa
# perspektywa nie ma tu drugiego miejsca do dopisania.
_ZNANE_KLUCZE_SPECU = frozenset({"filter", "columns", "group_by", "facets", _SPEC_WIDOK}
                                | {_klucz_spec(atrybut) for atrybut, _ in _TRIMY})


def _zawezenie_facetowe(drzewo):
    """Czy drzewo filtra to SAMO zawężenie facetowe - liść facetu albo grupa AND/OR takich liści
    (warunek zestawu z Znajdź). Warunek keyworda, negacja albo pusta grupa - nie. Czysta funkcja."""
    if not isinstance(drzewo, dict):
        return False
    if "facet" in drzewo:
        return True
    dzieci = drzewo.get("conditions") or []
    return (str(drzewo.get("op", "")).upper() in ("AND", "OR") and bool(dzieci)
            and all(_zawezenie_facetowe(d) for d in dzieci))


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
    zostaje prywatną sprawą klingi, a zdanie ma jeden porządek. Porządek jest NATURALNY
    (`queries.natural_key`), ten sam co w bibliotece obiektów i w listach facetów: porządek znaków
    stawiał „NGC700" przed „NGC7000" i „Caldwell 12" przed „Caldwell 3", czyli zdanie po geście
    czytało się inaczej niż lista, z której user te obiekty wybierał. Surowa nazwa jako człon
    następny daje porządek całkowity (klucz naturalny jest ślepy na wielkość liter)."""
    nazwy = sorted(canons, key=lambda c: (queries.natural_key(c), c))
    if len(nazwy) <= maks:
        return ", ".join(nazwy)
    return ", ".join(nazwy[:maks]) + i18n.t("grid.sel.object_canons_more", n=len(nazwy) - maks)


def zdanie_pominiec(gest, *, nothing_key="grid.sel.object_skip_nothing",
                    prefix="grid.sel.object_skip_", odmiana=False):
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
    jedyny zapis osi, który sięga rodowodu - i należy do tego samego zdania na KAŻDEJ powierzchni.

    OŚ SPRZĘTU MÓWI TĄ SAMĄ GRAMATYKĄ (R-S2b-15): `repo.ConfigGesture` ma własne
    `skipped_breakdown`, a wołający podaje `prefix` swoich kluczy. Jej człony są FRAZAMI odmienianymi
    przez liczbę (`odmiana=True` → `t_plural`: „1 klatka bez kamery", „5 klatek bez kamery"), bo
    to klatki, a nie licznik po dwukropku. Zera nie są drukowane na żadnej osi. Gest bez gotowych
    obrazów (`stacks`) nie niesie tego pola - gest zestawu ich nie liczy, o rodowodzie mówi
    osobny człon wołającego."""
    def czlon(sufiks, n):
        klucz = nothing_key if sufiks == "nothing" else f"{prefix}{sufiks}"
        return i18n.t_plural(klucz, n) if odmiana else i18n.t(klucz, n=n)

    czlony = [czlon(sufiks, n) for sufiks, n in gest.skipped_breakdown if n]
    if getattr(gest, "stacks", 0):
        czlony.append(i18n.t_plural("grid.sel.object_stacks", gest.stacks))
    return "".join(czlony)


class CzlonRecepty(NamedTuple):
    """Jeden człon recepty paska: TEKST i WYKONAWCA (FH-2e).

    `wykonaj` to wywołanie bez argumentów, które robi DOKŁADNIE to, co tekst nazywa, albo `None`,
    gdy gest jest jeszcze niewykonalny (wariant „potem" - celuje w klatki, których nie ma na
    ekranie). `None` nie znaczy „tylko informacja do ukrycia": przycisk recepty ma wtedy zostać
    WYGASZONY, nie zniknąć, bo zdanie dalej mówi prawdę o drugim kroku."""
    tekst: str
    wykonaj: object = None


class Recepta(str):
    """Recepta paska jako ZDANIE i LISTA CZŁONÓW naraz (FH-8, FH-2e). Czysta wartość.

    Zdanie (`str`) jest dla każdego, kto czyta receptę jak tekst - podpowiedź paska, testy, log.
    Człony są dla nośnika: elizja przy braku miejsca zdejmuje CAŁY człon pierwszy, a nie ogon
    zdania - cięcie od prawej zjadało nazwę pozycji menu, czyli jedyną część, której user szuka
    wzrokiem. Wykonawcę bierze nośnik z członu PIERWSZEGO, bo kolejność członów jest kolejnością
    w czasie.

    KOLEJNOŚĆ CZŁONÓW JEST KOLEJNOŚCIĄ W CZASIE, nie ważnością: najpierw „odsłoni je …", potem
    „potem przywrócisz: …" - drugi gest bywa wykonalny dopiero po pierwszym, bo wypchnięcie celu
    z widoku gasi całą kontrolkę „Obiekt" (FC-9). Wołający dokłada człony w tym porządku i to on
    jest kontraktem; konstruktor tylko odsiewa milczące i skleja.

    Separator ten sam, co w raporcie, bo oba zdania czyta się jednym ruchem oka wzdłuż paska -
    dwa różne rozdzielniki na jednej belce wyglądałyby jak dwa różne rejestry.

    `ts` - TOŻSAMOŚĆ GESTU, którego drogę powrotu recepta niesie (AR-94): znacznik `event.ts`
    jego zdarzeń w dzienniku albo `None`, gdy nadawca go nie zna. Dom opisuje „Ostatnio” zdarzeniem
    o tym znaczniku, a nie ostatnim gestem w ogóle - gest wykonany później w innym miejscu nie
    podszywa się pod gest, który cofa przycisk recepty."""
    SEPARATOR = " · "

    def __new__(cls, czlony=(), ts=None):
        czlony = tuple(c if isinstance(c, CzlonRecepty) else CzlonRecepty(c) for c in czlony)
        czlony = tuple(c for c in czlony if c.tekst)
        self = super().__new__(cls, cls.SEPARATOR.join(c.tekst for c in czlony))
        self.czlony = czlony
        self.ts = ts
        return self


def _zlacz_recepty(czlony, ts=None):
    """Człony recepty (`CzlonRecepty` albo goły tekst bez wykonawcy) w `Recepta` (FH-2, FH-8),
    z tożsamością gestu (`ts`, AR-94)."""
    return Recepta(czlony, ts)


class _Odwrot(NamedTuple):
    """Droga powrotu gestu osi zaznaczenia - z czego składa się jej człon recepty (FC-9, FH-2e).

    Dwa klucze, bo człon ma dwa warianty: gest od razu wykonalny i wariant „potem", gdy cel
    gestu najpierw trzeba odsłonić. `menu`/`akcja` to KLUCZE etykiet kontrolki i pozycji menu,
    cytowane z katalogu - recepta wskazująca napis, którego na ekranie nie ma, jest gorsza niż jej
    brak. `slot` to metoda widoku, którą wisi ta pozycja menu: wykonawca recepty woła ją, nie kopię.
    `zostalo` to metoda widoku, która mówi, ILE klatek celu da się dziś odwrócić - recepta żyje,
    dopóki to jest prawdą (odwracalność jest faktem o STANIE, nie o czasie komunikatu)."""
    klucz: str
    klucz_potem: str
    menu: str
    akcja: str
    slot: str
    zostalo: str


# Trzy drogi powrotu osi zaznaczenia, każda z WŁASNĄ parą kluczy zdania. Cofnięcie przypisania
# i wycofanie klatki brzmią dziś tak samo („przywrócisz: …”, etykiety jadą parametrem), ale klucz
# wspólny kłamałby o osi: zmiana zdania osi obiektu zmieniałaby receptę osi klatki (AR-71).
# Przywrócenie przypisania ma własną parę także w brzmieniu: jego odwrotem jest COFNIĘCIE
# („cofniesz: …"), a „przywrócisz" byłoby nieprawdą o kierunku (FH-9).
_ODWROT_COFNIECIA = _Odwrot("grid.sel.object_clear_undo", "grid.sel.object_clear_undo_after",
                            "grid.sel.object", "grid.sel.object_restore",
                            "_on_object_restore", "_ile_do_przywrocenia")
_ODWROT_PRZYWROCENIA = _Odwrot("grid.sel.object_restore_undo", "grid.sel.object_restore_undo_after",
                               "grid.sel.object", "grid.sel.object_clear",
                               "_on_object_clear", "_ile_do_cofniecia")
# Odmowa wykonania recepty przy zajętości (Z4) - powód z `_powod_zajetosci` (klucze gestów
# izolacji) na zdanie RECEPTY: tamte obiecują, że gest „ruszy po zakończeniu", a recepta sama
# nie ruszy - trzeba ją kliknąć jeszcze raz. Ten sam słownik odmawia pozycjom menu osi, które
# recepta nazywa (AR-70, `FramesView._odmowa_zajetosci`) - to te same sloty.
_RECEPTA_ZAJETA = {"grid.inplace.busy_stage": "grid.recipe.busy_stage",
                   "grid.inplace.busy_write": "grid.recipe.busy_write"}

_ODWROT_WYCOFANIA = _Odwrot("grid.sel.frame_retire_undo", "grid.sel.frame_retire_undo_after",
                            "grid.sel.frame", "grid.sel.frame_restore",
                            "_on_frame_restore", "_ile_wycofanych")
# Droga powrotu gestu UWAG nie jest pozycją menu: odwrotem jest przywrócenie stanu sprzed gestu,
# a ten zna wyłącznie migawka widoku (`FramesView._migawka_uwag`) - recepta jest jedynym wejściem.
# Zdanie członu mówi więc samą czynność; `menu`/`akcja` wskazują nazwę gestu, nie napis menu.
_ODWROT_UWAG = _Odwrot("grid.notes.undo", "grid.notes.undo_after",
                       "grid.notes.action", "grid.notes.action",
                       "_cofnij_uwagi", "_ile_uwag_do_cofniecia")
# Droga powrotu WERDYKTU RĘKI w panelu rodowodu (D-1011-4): odwrotem nie jest werdykt przeciwny,
# tylko stan SPRZED gestu (`repo.restore_integration_judgment`), znany wyłącznie migawce widoku
# (`FramesView._migawka_werdyktu`) - recepta jest jedynym wejściem, jak przy uwagach. Cel recepty
# to klatka STOSU (wiersz gridu), bo wejścia stosu w gridzie zwykle nie stoją.
_ODWROT_WERDYKTU = _Odwrot("grid.lin.undo", "grid.lin.undo_after",
                           "grid.sel.lineage", "grid.sel.lineage",
                           "_cofnij_werdykt", "_ile_werdyktow_do_cofniecia")
# Odmowa gestu uwag przy zajętości - zdania gestów izolacji obiecują, że gest „ruszy po
# zakończeniu", a okno uwag samo nie ruszy.
_UWAGI_ZAJETE = {"grid.inplace.busy_stage": "grid.notes.busy_stage",
                 "grid.inplace.busy_write": "grid.notes.busy_write"}


def _ogon_sciezki(path):
    """Nazwa pliku ze ścieżki Windows albo POSIX - do zdania na pasku, gdzie pełna ścieżka zjadłaby
    powód, po który człowiek patrzy."""
    return str(path or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


# Status wyniku, który znaczy „gest zrobił swoje", per operacja rdzenia - klucz zdania głównego
# i status sukcesu. `finish_inplace` oddaje 'applied', `recover_torn` - 'restored',
# `release_isolation` - 'released'.
_GESTY_ZAPISU = {
    "finish_inplace": ("grid.inplace.finished", "applied"),
    "recover_torn": ("grid.inplace.restored", "restored"),
    "release_inplace": ("grid.inplace.released", "released"),
}


def _zdanie_gestu_zapisu(op, res):
    """Zdanie wyniku gestu plikowego izolacji: „Dokończono N zapisów · zablokowane M · błędy K -
    plik: powód" (+ przerwanie). Czysta funkcja.

    POWÓD RDZENIA JEDZIE DOSŁOWNIE - jest po polsku i niesie drogę dalej (np. „kontrola danych
    operacji 7 przechodzi - zapis jest poprawny, powrót go nie cofa; dokończ…"); zdanie bez niego
    zostawiałoby człowieka przy „zablokowane 1" bez odpowiedzi „czemu". Pokazujemy PIERWSZY powód
    z nazwą pliku - reszta ma tę samą drogę albo własny wiersz w Porządkach, a pasek jest jeden.

    SUKCES Z POWODEM TEŻ MÓWI (osobnym, drugim członem): rdzeń podaje powód przy sukcesie tylko
    wtedy, gdy człowiek musi coś wiedzieć - przywrócenie drogą powrotu („plik zmienił się poza
    nagłówkiem… przeskanuj plik") albo zwolnienie pliku, którego nie dało się otworzyć. Samo
    „Przywrócono nagłówek w 1 pliku" chowało, że plik ma zmiany poza nagłówkiem i czeka na skan.
    `res` = wynik pętli wykonawcy (`results` = `writeback.FileResult` per operacja, `cancelled`)."""
    klucz, sukces = _GESTY_ZAPISU[op]
    wyniki = list(res.results)
    msg = i18n.t_plural(klucz, sum(1 for w in wyniki if w.status == sukces))
    # AR-82: dokończenie domknęło fazę, plik jest zapisany, a zeznanie klatki nie przyjęło zapisu -
    # osobny człon, nie „błąd” (`grid.wb.withheld`, ta sama fraza co wynik commitu).
    wstrzymane = [w for w in wyniki if w.status == "withheld"]
    zablokowane = [w for w in wyniki if w.status == "blocked"]
    bledy = [w for w in wyniki if w.status not in (sukces, "blocked", "withheld")]
    if wstrzymane:
        msg += " · " + i18n.t_plural("grid.wb.withheld", len(wstrzymane))
    if zablokowane:
        msg += i18n.t_plural("grid.inplace.blocked", len(zablokowane))
    if bledy:
        msg += i18n.t_plural("grid.inplace.failed", len(bledy))
    if res.cancelled:
        msg += i18n.t("grid.inplace.cancelled")
    for powod in (next((w for w in zablokowane + bledy + wstrzymane if w.reason), None),
                  next((w for w in wyniki if w.status == sukces and w.reason), None)):
        if powod is not None:
            msg += i18n.t("grid.inplace.detail", file=_ogon_sciezki(powod.path),
                          detail=powod.reason)
    return msg


def _kopia_krotko(path):
    """Katalog i nazwa pliku kopii (`B_CLS\\m.xisf`) - do zdania na pasku. Sama nazwa nie wystarcza:
    kopie jednej klatki zwykle mają tę samą nazwę w różnych katalogach, a cała ścieżka zjadłaby
    pasek, na którym stoi też droga powrotu."""
    p = str(path or "")
    i = max(p.rfind("\\"), p.rfind("/"))
    j = max(p.rfind("\\", 0, i), p.rfind("/", 0, i)) if i > 0 else -1
    return p[j + 1:]


# Werdykt gestu „Ta kopia prowadzi" (`lead_copy.LeadCopyResult.verdict`) → klucz zdania.
_ZDANIA_KOPII_WIODACEJ = {
    "adopted": "grid.lead.adopted", "confirmed": "grid.lead.confirmed",
    "unchanged": "grid.lead.unchanged",
    "absent": "grid.lead.absent", "isolated": "grid.lead.isolated", "failed": "grid.lead.failed",
    "identity": "grid.lead.identity", "stale": "grid.lead.stale", "raced": "grid.lead.raced",
}


def _zdanie_kopii_wiodacej(res):
    """Zdanie po geście „Ta kopia prowadzi" - czysta funkcja. Przejęcie mówi DROGĘ POWROTU: kopię,
    która mówiła przed gestem, wskazuje się tym samym gestem (`res.back`). Gdy żadna obecna kopia
    nie mówiła (zeznanie z kopii, której już nie ma), powrotu gestem nie ma i zdanie to mówi -
    poprzednie zeznanie zostaje wyłącznie w dzienniku. Odmowa mówi, że nic nie zapisano, i czemu."""
    msg = i18n.t(_ZDANIA_KOPII_WIODACEJ[res.verdict], copy=_kopia_krotko(res.path),
                 reason=res.reason or "")
    if res.verdict in ("adopted", "confirmed"):
        msg += (i18n.t("grid.lead.back", lead=i18n.t("grid.lead.menu"),
                       copy=_kopia_krotko(res.back[0])) if res.back
                else i18n.t("grid.lead.no_back"))
    return msg


def _kopie_wielokrotne(ops):
    """Operacje izolujące klatek, które mają W CELU więcej niż jedną kopię izolowaną (AR-30 (4)).
    Cel gestu jest kluczowany klatką (zaznaczenie wierszy), a wykonanie idzie per operacja - przy
    dwóch kopiach jednej klatki gest rusza obie. Populacja dziś 0 (zapis w miejscu odmawia przy
    ≥2 obecnych kopiach), więc to zdanie jest tripwirem: ekran ma powiedzieć KTÓRE pliki."""
    na_klatke = {}
    for o in ops:
        na_klatke.setdefault(o["frame_id"], []).append(o)
    return [o for grupa in na_klatke.values() if len(grupa) > 1 for o in grupa]


def _zdanie_kopii_wielokrotnych(wiele):
    """Dopisek podpowiedzi gestu izolacji: ile plików i które, gdy klatka ma kilka kopii w izolacji."""
    if not wiele:
        return ""
    return i18n.t_plural("grid.inplace.many_copies", len(wiele),
                         files=", ".join(_ogon_sciezki(o["path"]) for o in wiele))


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
    d["_images_n"] = n          # klucz SORTU kolumny „Obrazy" - liczba, nie tekst („10" < „2")
    # Zestaw „teleskop · kamera" dla prezentacji Znajdź - z pól, które wiersz i tak niesie; brak
    # jednej połowy nie kasuje drugiej (klatka bez configu ma kamerę, a nie ma teleskopu).
    d["_zestaw"] = " · ".join(p for p in (d["_telescope"], d.get("camera_model")) if p)
    return d


def _dolacz_kopie(base, kopie, reka=None):
    """Dołóż wierszom gridu fakty ICH OBECNYCH KOPII (0021) - czysta funkcja nad gotowymi danymi
    (`queries.present_copy_facts`), zero SQL; mutuje dicty `base` w miejscu, jak `_derive` buduje je
    dla modelu. `reka` - `{frame_id: location_id}` ważnych kotwic ręki (`repo.hand_lead_locations`).

    Dwa klucze, dwóch czytelników:
      * `_copies` - lista kopii (dict wiersza + `_rozne`, pola rozjazdu z `queries.copy_divergence`,
        + `_reka`, kopia wskazana gestem „Ta kopia prowadzi") dla podpowiedzi „×N"; JEDEN właściciel
        reguły rozjazdu z wierszem Porządków, więc opis pod kursorem i liczba na liście mówią
        o tych samych polach;
      * `_images` - WSZYSTKIE różne liczby obrazów w kolejności kopii („3 | 1"); kopia bez zebranych
        faktów (NULL) nie wnosi wartości, bo „nie wiem" nie jest liczbą. Jedna wspólna wartość zostaje
        jedną liczbą - rozjazd ma być widoczny, zgodność ma nie hałasować;
      * `_images_n` - NAJWIĘKSZA z tych liczb (klucz sortu kolumny): klatka, której któraś kopia
        niesie więcej obrazów, staje tam, gdzie ta kopia. Brak każdej liczby → None.
    Wiersz bez kilku kopii zostaje nietknięty (liczbę jego jedynej kopii ustawił `_derive`)."""
    per_klatka = {}
    for r in kopie:
        per_klatka.setdefault(r["frame_id"], []).append(r)
    for row in base:
        rows = per_klatka.get(row.get("frame_id"))
        if not rows:
            continue
        rozne = queries.copy_divergence(rows)
        kotwica = (reka or {}).get(row.get("frame_id"))
        row["_copies"] = [{**{k: r[k] for k in r.keys()}, "_rozne": rozne.get(r["location_id"], ()),
                           "_reka": r["location_id"] == kotwica}
                          for r in rows]
        liczby = []
        for r in rows:
            if r["image_count"] is not None and r["image_count"] not in liczby:
                liczby.append(r["image_count"])
        row["_images"] = " | ".join(str(n) for n in liczby)
        row["_images_n"] = max(liczby) if liczby else None


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


def _obrazy_kopii(kopia):
    """Liczba i role obrazów kopii do podpowiedzi: „3 (MasterFlat, RejectionMapLow, …)"; sama liczba,
    gdy żadna rola nie jest znana (pojedynczy obraz bez `imageType` i bez `id` - 248 plików
    archiwum - lista „(?)" nie niesie informacji); „∅" bez zebranej liczby. Jeden format dla
    „×N" i dla członu „mówi inaczej"."""
    if kopia["image_count"] is None:
        return _wartosc_zeznania(None)
    tekst = str(kopia["image_count"])
    role = json.loads(kopia["image_roles"]) if kopia["image_roles"] else []
    if any(r is not None for r in role):
        tekst += f" ({', '.join('?' if r is None else str(r) for r in role)})"
    return tekst


def _pole_rozjazdu(etykieta, kopia):
    """Jedno pole z `queries.copy_divergence` jako człon zdania „mówi inaczej: …" - wspólne dla
    podpowiedzi „×N" i podmenu „Ta kopia prowadzi". `kopia` - wiersz `present_copy_facts` (dict).
    Obrazy - liczba i role TEJ kopii (`_obrazy_kopii`), nie sama nazwa pola: „obrazy" bez wartości
    nie mówiło, czym kopie się różnią (odbiór 2026-10-10); pola NAZWY i ŚCIEŻKI (AR-1) - etykieta
    z katalogu i wartość tej kopii (`queries.copy_name_facts`); keyword nagłówka - „FILTER=CLS"."""
    if etykieta == queries.COPY_IMAGES:
        return f"{i18n.t('grid.tip.copy_field_images')}={_obrazy_kopii(kopia)}"
    if etykieta in queries.COPY_NAME_FIELDS:
        wartosc = queries.copy_name_facts(kopia["path"])[etykieta]
        if etykieta == queries.COPY_FLATGRP:
            nazwa = i18n.t("grid.tip.copy_field_flatgrp")
        elif etykieta == queries.COPY_NAME_FILTER:
            nazwa = i18n.t("grid.tip.copy_field_name_filter")
        else:
            nazwa = i18n.t("grid.tip.copy_field_filter_dir")
        return f"{nazwa}={_wartosc_zeznania(wartosc)}"
    return f"{etykieta}={_wartosc_zeznania(kopia[_KOPIA_KEYWORD_KOLUMNA[etykieta]])}"


def _dup_tip(row):
    """Człon podpowiedzi ścieżki dla klatki z KILKOMA obecnymi kopiami: liczba kopii, a pod nią każda
    kopia - pełna ścieżka, liczba i role obrazów, pola, w których jej zeznanie odbiega od pozostałych
    (z jej własną wartością). Do 0021 podpowiedź mówiła samo „N obecnych lokalizacji", a baza nie
    wiedziała, czym kopie się różnią - teraz wie, więc mówi.

    Liczba i role obrazów w jednym formacie z członem „mówi inaczej" (`_obrazy_kopii`). Kopia bez
    zebranego zeznania mówi to wprost, zamiast milczeć jak kopia zgodna."""
    tip = i18n.t("grid.tip.dup_locs", n=row["n_present"])
    for c in row.get("_copies") or ():
        tip += i18n.t("grid.tip.copy_path", path=c["path"])
        if c.get("_reka"):
            tip += i18n.t("grid.tip.copy_hand")
        if c["image_count"] is not None:
            tip += i18n.t("grid.tip.copy_images", n=_obrazy_kopii(c))
        if queries.copy_facts_state(c["hdr_hash"], c["hdr_rule"]) != queries.FAKTY_BIEZACE:
            tip += i18n.t("grid.tip.copy_unread", place=i18n.t("nav.dostawa"),
                          check=i18n.t("pipeline.btn.presence"),
                          mark=i18n.t("pipeline.btn.mark_vanished"))
        # Kopia bez zebranego zeznania nie ma pól nagłówka w `_rozne`, ale pola nazwy i ścieżki
        # (AR-1) mieć może - baza zna je zawsze.
        if c["_rozne"]:
            pola = [_pole_rozjazdu(e, c) for e in c["_rozne"]]
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


def _etykieta_grupy_wersji(grupa, *, zestaw=False):
    """Nagłówek grupy bliźniaków: obiekt · filtr · ekspozycja · okno - opis materiału, który człowiek
    rozpoznaje. Klucz grupy ma jeszcze kamerę i teleskop (`queries._grupy_wersji`), ale ich miejsce
    na belce zajmują tylko wtedy, gdy są ROZRÓŻNIKIEM (`zestaw=True`): dwa zestawy z kamerą tego
    samego modelu tej samej nocy dają dwie grupy o identycznym opisie, a belki muszą się różnić
    tekstem, nie tylko pozycją na liście."""
    exp = grupa["exptime"]
    opis = i18n.t("grid.version.group",
                  object=grupa["object_canon"] or i18n.t("grid.version.no_object"),
                  filter=grupa["filter_canon"] or i18n.t("portfolio.no_filter"),
                  exp=f"{exp:g}" if exp is not None else "?",
                  start=_okno(grupa["window_start"]), end=_okno(grupa["window_end"]))
    if zestaw:
        opis += i18n.t("grid.version.group_rig", telescope=grupa["telescope"] or "?",
                       camera=grupa["camera"] or "?")
    return opis


def _adnotuj_wersje(base, grupy):
    """Dołóż wierszom gridu fakty grupy wersji: `_wersja_grupa` (stabilny identyfikator grupy
    z read-modelu - klucz grupowania `_GRUPA_WERSJI`), `_wersja_etykieta` (podpis belki) i `_wersja`
    (fakty członka dla kolumny „Wersja"). Grupowanie po IDENTYFIKATORZE, nie po podpisie: dwie
    grupy o tym samym opisie zlałyby się pod jedną belką w jedną „grupę" stosów z dwóch zestawów.
    Podpis dostaje rozróżnik zestawu tylko przy kolizji opisów (`_etykieta_grupy_wersji`).
    Wiersz spoza grup zostaje bez kluczy - grupuje się wtedy do „(brak)", a komórka milczy. Czysta
    funkcja nad gotowymi danymi (`queries.stack_version_groups`), zero SQL; mutuje dicty `base`
    w miejscu, jak `_derive` buduje je dla modelu."""
    opisy = {}
    for g in grupy:
        opis = _etykieta_grupy_wersji(g)
        opisy[opis] = opisy.get(opis, 0) + 1
    fakty = {}
    for g in grupy:
        etykieta = _etykieta_grupy_wersji(g, zestaw=opisy[_etykieta_grupy_wersji(g)] > 1)
        for m in g["members"]:
            fakty[m["frame_id"]] = (g["group_id"], etykieta,
                                    {**m, "group_kind": g["kind"],
                                     "kept": g.get("kept", False), "kept_at": g.get("kept_at"),
                                     "centers": g.get("centers", 0),
                                     "window_start": g["window_start"],
                                     "window_end": g["window_end"]})
    for row in base:
        f = fakty.get(row.get("frame_id"))
        if f is not None:
            row["_wersja_grupa"], row["_wersja_etykieta"], row["_wersja"] = f


# Stan rodowodu gotowego obrazu → (etykieta, podpowiedź). Klucze JAWNE per token (kolektor literałów
# bramki i18n widzi wyłącznie literały) - komplet z `queries.LINEAGE_STATES` pinuje test.
_STANY_RODOWODU = {
    "pending": "grid.lineage.state.pending",
    "exact": "grid.lineage.state.exact",
    "history": "grid.lineage.state.history",
    "mixed": "grid.lineage.state.mixed",
    "window": "grid.lineage.state.window",
    "rejected": "grid.lineage.state.rejected",
    "none": "grid.lineage.state.none",
    "uncounted": "grid.lineage.state.uncounted",
}
_TIPY_RODOWODU = {
    "exact": "grid.lineage.tip.exact",
    "history": "grid.lineage.tip.history",
    "mixed": "grid.lineage.tip.mixed",
    "window": "grid.lineage.tip.window",
    "pending": "grid.lineage.tip.pending",
    "rejected": "grid.lineage.tip.rejected",
    "none": "grid.lineage.tip.none",
    "uncounted": "grid.lineage.tip.uncounted",
}
# Stany, które są BRAKIEM rodowodu - komórka maluje je rolą braku (szarość + kursywa), jak brak
# karty keyworda: „nie wiadomo, z czego powstał" nie jest ostrzeżeniem, tylko pustym miejscem.
_RODOWOD_BRAK = frozenset({"rejected", "none", "uncounted"})


def _adnotuj_rodowod(base, stany):
    """Dołóż wierszom gridu `_rodowod` = token stanu (`queries.stack_lineage_states`) albo `None`
    dla klatki, która nie jest gotowym obrazem. Czysta funkcja nad gotowym słownikiem, zero SQL;
    mutuje dicty `base` w miejscu, jak `_adnotuj_wersje`."""
    for row in base:
        row["_rodowod"] = stany.get(row.get("frame_id"))


class _ElizjaWSrodku(QStyledItemDelegate):
    """Delegat JEDNEJ kolumny z elizją w środku: tekst traci środek, a zachowuje oba końce -
    prefiks „×N" i ogon nazwy pliku z rozszerzeniem. `QTableView.setTextElideMode` działa na całą
    tabelę, więc elizja kolumny żyje w delegacie (`setItemDelegateForColumn`).

    JEDNA LINIA, BEZ ZAWIJANIA (AR-116). Tabela ma domyślnie `wordWrap`, więc styl dostawał opcję
    z `WrapText` i nazwę ze spacjami („×2  NGC6992 …") łamał na dwie linie w wąskiej kolumnie,
    zamiast ją skrócić. Zawijanie zdejmujemy w opcji, a tekst do malowania skraca
    `QFontMetrics.elidedText` do szerokości prostokąta tekstu (`tekst_w_linii`) - w malowaniu, nie
    w `initStyleOption`, bo z tej opcji liczy się też podpowiedź szerokości kolumny z treści."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideMiddle
        option.features &= ~QStyleOptionViewItem.WrapText

    @staticmethod
    def tekst_w_linii(option):
        """Tekst opcji skrócony w środku do szerokości, którą styl da mu w komórce: prostokąt
        tekstu (`SE_ItemViewItemText`) minus margines, który styl odejmuje sam przy rysowaniu
        (`PM_FocusFrameHMargin` + 1 z każdej strony). Mieści się w całości - zostaje bez zmian."""
        styl = option.widget.style() if option.widget is not None else QApplication.style()
        prostokat = styl.subElementRect(QStyle.SE_ItemViewItemText, option, option.widget)
        margines = styl.pixelMetric(QStyle.PM_FocusFrameHMargin, None, option.widget) + 1
        return option.fontMetrics.elidedText(option.text, Qt.ElideMiddle,
                                             max(0, prostokat.width() - 2 * margines))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = self.tekst_w_linii(opt)
        styl = opt.widget.style() if opt.widget is not None else QApplication.style()
        styl.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)


class _EdycjaKomorki(QStyledItemDelegate):
    """Delegat edycji komórki keyworda (AR-61): pole WARTOŚCI i pole KOMENTARZA o znaczeniu pola
    komentarza w `MacroBar` (pusty - karta zachowuje zastany; wpisany - zapis razem z nim, AR-47).

    Edytor szerszy niż komórka: dwa pola w kolumnie keyworda ~100 px nie dałyby się czytać, a komentarz
    jest jedyną drogą z GUI dla karty FITS, której zastany komentarz nie mieści się przy nowej wartości.
    Zamknięcie bez zmiany (fokus poza edytor, ta sama wartość, pusty komentarz) NIE stage'uje nic -
    inaczej każde przypadkowe otwarcie edytora dokładałoby do szuflady `set` na tę samą wartość.

    EDYTOR JEST KONTENEREM, A FOKUS MAJĄ JEGO POLA - więc filtr zdarzeń bazowego delegata (stawiany
    przez widok na kontenerze) nie widzi `FocusOut` pól i wyjście z edytora kliknięciem gdzie indziej
    (np. „Zatwierdź" szuflady) gubiło wpis: commit szedł bez niego, a odświeżenie zabijało edytor.
    Dlatego delegat filtruje OBA POLA sam (`eventFilter`): opuszczenie CAŁEGO edytora (fokus poza
    kontener i jego dzieci, bez otwartego popupu) zatwierdza; przejście wartość↔komentarz (Tab)
    edycji nie kończy; Enter w każdym polu zatwierdza, Esc anuluje. Ta sama reguła co
    `QAbstractItemDelegate.eventFilter` dla edytora jednopolowego, przeniesiona na pola kontenera.

    CEL EDYCJI JEST STABILNY, NIE INDEKSOWY: `(frame_id, keyword)` ustalone przy otwarciu (`cel`).
    Reset modelu (odświeżenie po wyniku pól z wątku, sort, podgląd) unieważnia `QModelIndex`, a widok
    i tak niszczy wtedy edytor - więc widok domyka AKTYWNY edytor (`domknij`) przed każdym resetem
    i zanim sam zniknie (zamknięcie okna, przełączenie bazy), a zapis idzie po celu. Bez tego wpis
    ginął po cichu razem z edytorem."""

    _MIN_W = 320

    def __init__(self, parent=None):
        super().__init__(parent)
        self.aktywny = None          # otwarty edytor (kontener) - jeden naraz, jak w widoku

    def createEditor(self, parent, option, index):
        ed = QWidget(parent)
        ed.setAutoFillBackground(True)
        lay = QHBoxLayout(ed)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        ed.wartosc = QLineEdit(ed)
        ed.wartosc.setPlaceholderText(i18n.t("grid.cell.value_ph"))
        ed.komentarz = QLineEdit(ed)
        ed.komentarz.setPlaceholderText(i18n.t("grid.macro.comment_ph"))
        ed.komentarz.setToolTip(i18n.t("grid.macro.comment_tip"))
        lay.addWidget(ed.wartosc, 3)
        lay.addWidget(ed.komentarz, 2)
        ed.setFocusProxy(ed.wartosc)
        ed.zamkniety = False
        ed.zatwierdzony = False
        ed.model = index.model()
        ed.cel = ed.model.cel_edycji(index)
        for pole in (ed.wartosc, ed.komentarz):
            pole.kontener = ed
            pole.installEventFilter(self)
        self.aktywny = ed
        return ed

    def destroyEditor(self, editor, index):
        if self.aktywny is editor:
            self.aktywny = None
        super().destroyEditor(editor, index)

    def domknij(self):
        """Zatwierdź AKTYWNY edytor po jego stabilnym celu, bez pytania widoku o indeks - wołane przed
        resetem modelu i przed zniknięciem widoku. Edytor bez zmiany nie stage'uje nic (ta sama
        reguła co zamknięcie fokusem). Zwraca True, gdy był otwarty edytor."""
        ed = self.aktywny
        if ed is None or ed.zamkniety:
            return False
        ed.zamkniety = True
        self.aktywny = None
        self._zatwierdz(ed)
        return True

    def _zatwierdz(self, ed):
        """Jedno zatwierdzenie wpisu edytora - po celu `(frame_id, keyword)`, raz na edytor."""
        if ed.zatwierdzony:
            return
        wartosc, komentarz = ed.wartosc.text(), ed.komentarz.text().strip()
        if wartosc == getattr(ed, "pierwotna", None) and not komentarz:
            return                       # nic nie zmieniono - zamknięcie edytora to nie zmiana
        ed.zatwierdzony = True
        ed.model.cell_edit_requested.emit(ed.cel[0], ed.cel[1], wartosc, komentarz)

    def _zakoncz(self, ed, *, zatwierdz):
        """Jedno zamknięcie edytora: `commitData` (gdy zatwierdzamy) i `closeEditor` dla KONTENERA -
        widok zna kontener, nie pola. Flaga chroni przed drugim zamknięciem, gdy niszczony edytor
        oddaje fokus i jego pole dostaje jeszcze `FocusOut`."""
        from PySide6.QtWidgets import QAbstractItemDelegate
        if ed.zamkniety:
            return
        ed.zamkniety = True
        if self.aktywny is ed:
            self.aktywny = None
        if zatwierdz:
            self.commitData.emit(ed)
            self.closeEditor.emit(ed, QAbstractItemDelegate.NoHint)
        else:
            self.closeEditor.emit(ed, QAbstractItemDelegate.RevertModelCache)

    def eventFilter(self, obj, ev):
        ed = getattr(obj, "kontener", None)
        if ed is None:
            return super().eventFilter(obj, ev)
        tab = ev.type() in (QEvent.KeyPress, QEvent.ShortcutOverride) and ev.key() in (
            Qt.Key_Tab, Qt.Key_Backtab)
        if tab and ev.type() == QEvent.ShortcutOverride:
            ev.accept()                      # Tab ma dojść do pola jako KeyPress, nie do skrótu
            return True
        if tab:
            # Tab/Backtab KRĄŻY MIĘDZY POLAMI EDYTORA. Bez tego `QLineEdit` oddaje Tab rodzicom aż do
            # `QAbstractItemView.focusNextPrevChild`, który zatwierdza komórkę i przechodzi dalej -
            # komentarz wpisany po Tab przepadał. Zatwierdza wyłącznie Enter albo opuszczenie edytora.
            (ed.komentarz if obj is ed.wartosc else ed.wartosc).setFocus(Qt.TabFocusReason)
            return True
        if ev.type() == QEvent.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._zakoncz(ed, zatwierdz=True)
                return True
            if ev.key() == Qt.Key_Escape:
                self._zakoncz(ed, zatwierdz=False)
                return True
        elif ev.type() == QEvent.FocusOut:
            from PySide6.QtWidgets import QApplication
            if QApplication.activePopupWidget() is not None:
                return False                 # menu kontekstowe pola - edycja trwa
            w = QApplication.focusWidget()
            while w is not None:
                if w is ed:
                    return False             # Tab wartość↔komentarz - edycja trwa
                w = w.parentWidget()
            self._zakoncz(ed, zatwierdz=True)
        return False

    def setEditorData(self, editor, index):
        tekst = index.data(Qt.EditRole) or ""
        editor.pierwotna = tekst
        editor.wartosc.setText(tekst)
        editor.wartosc.selectAll()

    def setModelData(self, editor, model, index):
        self._zatwierdz(editor)          # po celu z otwarcia, nie po `index` (reset go unieważnia)

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        editor.setGeometry(r.x(), r.y(), max(r.width(), self._MIN_W), r.height())


def elizja_w_srodku(table, col):
    """Kolumna `col` tabeli `table` elidowana W ŚRODKU - bez ruszania jej szerokości. Połowa
    `kolumna_z_tresci` dla kolumn, których szerokość ustala kto inny (sekcja `Stretch` w panelu
    Przeglądu obiektów): elizja z prawej zjadała tam ogon ścieżki, czyli nazwę pliku.

    Idempotentna: delegat powstaje raz na tabelę (dziecko tabeli, bezstanowy, więc służy każdej
    kolumnie) i jest używany ponownie, więc wołanie przy każdym przeładowaniu niczego nie mnoży.
    Zdjęcie elizji robi wołający (`setItemDelegateForColumn(col, None)`)."""
    delegat = table.findChild(_ElizjaWSrodku)
    if delegat is None:
        delegat = _ElizjaWSrodku(table)
    if table.itemDelegateForColumn(col) is not delegat:
        table.setItemDelegateForColumn(col, delegat)


def kolumna_z_tresci(table, col, *, sufit=_SUFIT_KOLUMNY_Z_TRESCI):
    """Kolumna `col` tabeli `table` szeroka z treści, nie szersza niż `sufit` px, z elizją
    w środku - JEDEN mechanizm dla każdej kolumny, której treść jest przedmiotem decyzji (ścieżka
    w „Duplikatach" i „Wersjach stosów"). Domyślne 100 px zostawiało z „×2  M31_…_0001.xisf" sam
    prefiks, a elizja z prawej zjadała właśnie nazwę pliku.

    Idempotentna jak `elizja_w_srodku`. Zdjęcie elizji poza perspektywą robi wołający
    (`setItemDelegateForColumn(col, None)`) - ta funkcja mówi tylko, jak kolumnę ustawić."""
    elizja_w_srodku(table, col)
    table.setColumnWidth(col, szerokosc_z_tresci(table, col, sufit=sufit))


def szerokosc_z_tresci(table, col, *, sufit=_SUFIT_KOLUMNY_Z_TRESCI):
    """Szerokość, jaką `kolumna_z_tresci` nadaje kolumnie `col` - bez jej ustawiania. Ta sama
    reguła co `QTableView.resizeColumnToContents` (większa z podpowiedzi treści i nagłówka),
    przycięta sufitem. Jedno miejsce, bo pyta o nią też zapis perspektywy: szerokość równa tej
    nie jest wyborem ręki (AR-36)."""
    table.executeDelayedItemsLayout()
    szer = max(table.sizeHintForColumn(col), table.horizontalHeader().sectionSizeHint(col))
    return min(szer, sufit)


# KOLUMNA EXPTIME - JEDNA PRECYZJA NA KOLUMNĘ (AR-115). Karta niesie liczbę w zapisie programu, który
# ją wpisał (NINA „600.0”, WBPP w stosie „600.00” albo „600.000”, aparat 1/160 s jako „0.00625”, flat
# z automatu ekspozycji „4.03329572835443”), więc surowy zapis stawiał „1800.00”, „600.000” i „15.000”
# jeden pod drugim. Reguła z rozkładu na kopii archiwum (pf4, 2026-10-13: 16 888 klatek z EXPTIME,
# 278 różnych wartości): wartość całkowita 13 743 klatki (81 %), jedno miejsce 647, dwa 2 315, trzy
# 41, więcej 142 (flaty z automatu, migawka 1/30 i 1/13 s). Przy dwóch miejscach zlewa się 23 z 278
# różnych wartości (1/160, 1/125, 1/100 i 1/80 s → „0.01”), przy trzech - żadna. Kolumna bierze więc
# NAJMNIEJ miejsc, które pokazują dokładnie każdą jej wartość, i nie więcej niż trzy: lighty z całymi
# sekundami mówią „600”, kolumna z flatami „0.080” i „600.000”. Wartość uciętą do trzech miejsc
# komórka podaje w podpowiedzi pełnym zapisem karty; pole edycji startuje od zapisu karty.
_EXPTIME = "EXPTIME"
_EXPTIME_MAKS_MIEJSC = 3


def _dokladnie(v, miejsca):
    return abs(round(v, miejsca) - v) < 1e-9


def miejsca_ekspozycji(wartosci):
    """Miejsca po przecinku kolumny EXPTIME dla jej wartości liczbowych - reguła w komentarzu
    wyżej; pusta kolumna - 0."""
    miejsca = 0
    for v in wartosci:
        while miejsca < _EXPTIME_MAKS_MIEJSC and not _dokladnie(v, miejsca):
            miejsca += 1
        if miejsca == _EXPTIME_MAKS_MIEJSC:
            break
    return miejsca


class GridTableModel(QAbstractTableModel):
    """Model danych read-only: kolumny bazowe + dynamiczne kolumny-keywordy. 3 stany komórki keyworda;
    sort numeryczny (po `PivotCell.num`) / tekstowy, MISSING na końcu; grupowanie = nagłówki grup
    w płaskiej liście. Karmiony gotowymi danymi (`set_data`) - zero SQL/plików.

    EDYCJA KOMÓRKI KEYWORDA (AR-61) NIE ZMIENIA MODELU: `setData` zamienia wpis człowieka na sygnał
    `cell_edit_requested(frame_id, keyword, wartość, komentarz)`, a widok przepuszcza go przez te same
    bramki co makro i stage'uje do szuflady. Wartość w komórce zmienia dopiero commit i przeładowanie;
    do tego czasu zmianę pokazuje podgląd klingi (kolumna „makro →"), jak przy makrze."""

    cell_edit_requested = Signal(int, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Edycja komórek włączona poza zajętością (etap Dostawy, zapis plików) - przełącza widok
        # (`FramesView._sync_edycji`); model sam o zajętości nie wie.
        self._edytowalne = True
        self._rows = []          # dict-y klatek (z 'cells') PRZEPLATANE markerami grup {'_group':..,'_count':..}
        self._data_rows = []     # same klatki (bez markerów) — źródło do sortu/grupowania
        self._keywords = []
        self._group_by = None
        # SORT PAMIĘTANY PO ZNACZENIU, NIE PO NUMERZE KOLUMNY: ("base", klucz) / ("kw", keyword) /
        # ("version",) albo None (sort neutralny). Numer przestawał znaczyć to samo, gdy perspektywa
        # dokładała kolumnę „Wersja" przed keywordami - sort po pierwszym keywordzie zamieniał się
        # wtedy po cichu w sort po „Wersji". Numer bieżącego układu oddaje `sort_column`.
        self._sort_id = ("base", BASE_COLS[0][1])
        self._sort_desc = False
        self._obrazy_pytajnik = False   # perspektywa kopii: brak liczby obrazów = „?" (`_images_cell`)
        self._numeric_kw = set() # keywordy z większością wartości liczbowych → cała kolumna w prawo (AR-77)
        self._miejsca_exptime = 0  # jedna precyzja kolumny EXPTIME (`miejsca_ekspozycji`, AR-115)
        self._miejsca_czasu = 0    # ta sama reguła dla kolumny „Czas” widoku Znajdź (`row["exptime"]`)
        self._preview = {}      # frame_id → {'keyword','old','new'} | {'skipped': reason} (podgląd makra/renamu)
        self._preview_label = i18n.t("grid.preview.macro")   # etykieta efemerycznej kolumny (klinga-zależna, R1 #4)
        self._version_col_on = False   # kolumna „Wersja" - perspektywa „Wersje stosów" albo wybór w Znajdź
        # Kolumny bazowe BIEŻĄCEJ prezentacji: `BASE_COLS` (klasyczna) albo `FIND_COLS` (Znajdź).
        # Numery liczone od nich - keywordy, „Wersja" i podgląd idą za nimi w obu prezentacjach.
        self._base = BASE_COLS

    def set_base_columns(self, cols, *, version_col):
        """Przełącz zestaw kolumn bazowych (prezentacja) na TYCH SAMYCH wierszach - bez nowych
        danych: przebudowa układu, jak przy sorcie. `version_col` jak w `set_data`, bo o kolumnie
        „Wersja" w Znajdź decyduje wybór w „Kolumny ▾", a w klasycznej perspektywa."""
        self._base = cols
        self._version_col_on = bool(version_col)
        self._rebuild()

    def n_bazowych(self):
        """Liczba kolumn bazowych bieżącej prezentacji - pierwszy numer kolumny za nimi."""
        return len(self._base)

    def set_preview(self, preview, *, label=None):
        """Podgląd klingi (doktryna §5: „grid = podgląd"): frame_id → zmiana (stara→nowa) albo
        pominięcie z powodem. Dokłada EFEMERYCZNĄ kolumnę (`label`, np. „makro →"/„nazwa →")
        LOGICZNIE na końcu; `{}`/None ją zdejmuje. `label` rozróżnia klingę (makro vs rename)
        w tym samym podglądzie (R1 #4); `None` → domyślna „makro →" z katalogu (rozwiązywana
        w wywołaniu, nie w sygnaturze - D-L1).

        WIZUALNIE kolumna stoi zaraz za „Ścieżką" - przesunięciem nagłówka w widoku
        (`FramesView._uloz_belki_i_wersje`), nie nowym indeksem, więc numery keywordów, sort
        i szerokości się nie przesuwają. Podgląd stał ostatni także wizualnie (rename: indeks 14
        z 15, x=1300 przy viewporcie 1076 px; makro i edycja komórki: ~130 px na końcu), więc
        tego, co miał pokazać, nie było widać bez przewijania - ani obok starej wartości."""
        self.beginResetModel()
        self._preview = dict(preview or {})
        self._preview_label = label if label is not None else i18n.t("grid.preview.macro")
        self.endResetModel()

    def _preview_active(self):
        return bool(self._preview)

    def set_data(self, base_rows, pivot, keywords, group_by=None, version_col=False,
                 images_unknown=False):
        """base_rows: list[dict] (z `_derive`); pivot: horreum.pivot.Pivot; keywords: list[str].

        `version_col` dokłada kolumnę „Wersja" (fakty `_wersja` z `_adnotuj_wersje`) zaraz po
        kolumnach bazowych (`_version_col`). Kolumna jest własnością perspektywy „Wersje stosów",
        nie wiersza: te same stosy w „Przeglądzie" niosą fakty (grupowanie „Wersja stosu" działa
        wszędzie), ale kolumna pojawia się tylko tam, gdzie wybór wersji jest robotą ekranu.

        `images_unknown` - perspektywa, w której brak liczby obrazów jest robotą, nie stanem
        archiwum (`_FLAGI_OBRAZOW`): komórka kandydata do zebrania faktów mówi wtedy „?"."""
        self._version_col_on = bool(version_col)
        self._obrazy_pytajnik = bool(images_unknown)
        cells = {r.frame_id: r.cells for r in pivot.rows}
        for d in base_rows:
            d["cells"] = cells.get(d["frame_id"], {})
        self._data_rows = list(base_rows)
        self._keywords = list(keywords)
        # Kolumna-keyword jest NUMERYCZNA, gdy WIĘKSZOŚĆ jej wartości to liczby (AR-77), i wtedy
        # CAŁA stoi do prawej - wartości i kreska braku MISSING (wizytator P3-7), inaczej do lewej.
        # Dawniej wystarczała jedna komórka liczbowa, a wartość szła za typem własnej karty: GAIN
        # „4000" zapisany tekstem stał po lewej, a kreska braku w tej samej kolumnie po prawej
        # (firsthand W11). Remis to nie większość - kolumna zostaje tekstowa. Pętla kończy się,
        # gdy wynik jest już przesądzony (połowa wierszy po jednej stronie).
        self._numeric_kw = set()
        polowa = len(self._data_rows) / 2
        for kw in self._keywords:
            liczby = teksty = 0
            for d in self._data_rows:
                c = d["cells"].get(kw, pivot_mod.MISSING)
                if c is pivot_mod.MISSING or c.raw is None:
                    continue
                if c.num is not None:
                    liczby += 1
                else:
                    teksty += 1
                if liczby > polowa or teksty >= polowa:
                    break
            if liczby > teksty:
                self._numeric_kw.add(kw)
        self._miejsca_exptime = miejsca_ekspozycji(
            c.num for d in self._data_rows
            if (c := d["cells"].get(_EXPTIME, pivot_mod.MISSING)) is not pivot_mod.MISSING
            and c.num is not None) if _EXPTIME in self._keywords else 0
        self._miejsca_czasu = miejsca_ekspozycji(
            float(d["exptime"]) for d in self._data_rows if d.get("exptime") is not None)
        self._group_by = group_by
        self._rebuild()

    # ---- kształt ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return (len(self._base) + len(self._keywords) + (1 if self._version_col_on else 0)
                + (1 if self._preview_active() else 0))

    def _version_col(self):
        """Indeks kolumny „Wersja" albo None, gdy perspektywa jej nie chce.

        ZARAZ PO KOLUMNACH BAZOWYCH, PRZED KEYWORDAMI - zmierzone zrzutem offscreen na kopii żywej
        bazy: postawiona za sześcioma domyślnymi keywordami lądowała poza prawą krawędzią okna
        1400 px, czyli fakty, po które ta perspektywa istnieje, wymagały przewijania w bok."""
        return len(self._base) if self._version_col_on else None

    def _kw_off(self):
        """Przesunięcie kolumn-keywordów o kolumnę „Wersja" (0 poza jej perspektywą)."""
        return 1 if self._version_col_on else 0

    def _preview_col(self):
        """Indeks efemerycznej kolumny podglądu (ostatnia) albo None, gdy podgląd nieaktywny.
        Indeks LOGICZNY - wizualnie podgląd stoi zaraz za „Ścieżką" (`set_preview`)."""
        if not self._preview_active():
            return None
        return len(self._base) + self._kw_off() + len(self._keywords)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section == self._preview_col():
                return self._preview_label
            if section == self._version_col():
                return i18n.t("grid.col.version")
            if section < len(self._base):
                return i18n.t(self._base[section][0])
            return self._keywords[section - len(self._base) - self._kw_off()]
        return section + 1

    def _col_key(self, col):
        return self._base[col][1] if col < len(self._base) else None

    def _kw_for_col(self, col):
        return None if col < len(self._base) else self._keywords[col - len(self._base) - self._kw_off()]

    def _sort_id_for(self, col):
        """Znaczenie kolumny `col` BIEŻĄCEGO układu jako identyfikator sortu (`_sort_id`) albo None
        dla kolumny bez sortu (podgląd klingi, indeks spoza układu)."""
        if col is None or col < 0 or col >= self.columnCount() or col == self._preview_col():
            return None
        if col == self._version_col():
            return ("version",)
        kw = self._kw_for_col(col)
        return ("base", self._col_key(col)) if kw is None else ("kw", kw)

    def sort_column(self):
        """Numer kolumny, po której model sortuje, w BIEŻĄCYM układzie - albo -1, gdy tej kolumny
        w układzie nie ma (keyword odznaczony w „Polach", „Wersja" poza swoją perspektywą). Widok
        stawia według niego wskaźnik sortu nagłówka po każdym przeładowaniu."""
        return next((c for c in range(self.columnCount()) if self._sort_id_for(c) == self._sort_id), -1)

    def sort_order(self):
        return Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder

    def base_col(self, key):
        """Numer kolumny bazowej o kluczu danych `key` w bieżącym układzie. Klucz spoza kolumn
        bazowych bieżącej prezentacji to błąd wołającego (EXPECT) - pyta o niego `has_base_col`."""
        col = next((c for c in range(self.columnCount())
                    if self._sort_id_for(c) == ("base", key)), None)
        if col is None:
            raise ValueError(f"nieznana kolumna bazowa: {key!r}")
        return col

    def has_base_col(self, key):
        """Czy bieżąca prezentacja ma kolumnę bazową `key` („Obrazy" ma tylko klasyczna)."""
        return any(k == key for _, k in self._base)

    # ---- komórki ----
    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and isinstance(self._rows[index.row()], dict) and "_group" in self._rows[index.row()]:
            return Qt.ItemIsEnabled  # nagłówek grupy: nieselektowalny
        if index.isValid() and self._komorka_edytowalna(index):
            return base | Qt.ItemIsEditable
        return base

    def _komorka_edytowalna(self, index):
        """Czy komórkę wolno otworzyć do edycji (AR-61) - TANIE bramki z faktów wiersza, bo `flags`
        woła się dla każdej komórki zakresu (R-S2b-7: koszt zaznaczenia mierzony w wywołaniach).

        Tylko kolumna KEYWORDA (te same keywordy, które dostaje pasek makra) i tylko klatka, w którą
        makro też może pisać, sądząc po tym, co wiersz już niesie: nie RAW (pisarz odmawia) i dokładnie
        jedna obecna kopia (D-W1). Reszta bramek celu (kompresja, degenerat, brak `header_hash`) i reguły
        karty idą przy zatwierdzeniu edycji przez `macro.plan_manual_change` - z powodem na pasku."""
        if not self._edytowalne:
            return False
        col = index.column()
        if (col < len(self._base) or col == self._preview_col() or col == self._version_col()
                or col >= self.columnCount()):
            return False
        row = self._rows[index.row()]
        return row.get("filetype") != "raw" and (row.get("n_present") or 0) == 1

    def set_editable(self, on):
        """Włącz albo wyłącz edycję komórek (zajętość widoku). Bez resetu: `flags` czyta flagę przy
        następnym zapytaniu widoku, a otwarty edytor i tak odbije bramka zajętości w widoku."""
        self._edytowalne = bool(on)

    def setData(self, index, value, role=Qt.EditRole):
        """Wpis człowieka w komórkę keyworda → `cell_edit_requested` (bez komentarza). Model się nie
        zmienia, więc zwraca False - widok pokaże zmianę podglądem po stage'u."""
        if role != Qt.EditRole:
            return False
        self.request_cell_edit(index, value, "")
        return False

    def request_cell_edit(self, index, value, comment):
        """Wyjście gołego `setData` (bez delegata): ten sam warunek edytowalności co `flags` - indeks
        spoza niego nie emituje nic (EXPECT na wołającym). Delegat nie idzie tędy: zapisuje po celu
        ustalonym przy otwarciu (`cel_edycji`), bo jego indeks bywa już nieważny po resecie."""
        if not index.isValid() or not self._komorka_edytowalna(index):
            return
        frame_id, keyword = self.cel_edycji(index)
        self.cell_edit_requested.emit(frame_id, keyword, "" if value is None else str(value),
                                      comment or "")

    def cel_edycji(self, index):
        """Stabilny cel edycji komórki: `(frame_id, keyword)` - przeżywa reset modelu."""
        return int(self._rows[index.row()]["frame_id"]), self._kw_for_col(index.column())

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
        if col < len(self._base):
            return self._base_cell(row, self._col_key(col), role)
        return self._kw_cell(row, self._kw_for_col(col), role)

    def _version_cell(self, row, role):
        """Komórka „Wersja": rodzaj członka · skrót świadka · chwila integracji · liczba wejść -
        fakty, po których człowiek wybiera wersję do zostawienia. Tooltip niesie pełne zdanie
        świadka (dlaczego ten rodzaj) i okno.

        SKRÓT ŚWIADKA STOI W KOMÓRCE, nie tylko w tooltipie: dwie wersje stosu bez sygnatury
        i historii wyglądały na ekranie identycznie („inna integracja"), a jedyny powód werdyktu
        - inne pomiary szumu i PSF - wymagał najechania na każdą komórkę po kolei.

        Brak faktu MILCZY zamiast udawać: stos bez sygnatury integracji (sprzed modułu XISF 1.1.2)
        dostaje datę z `XISF:CreationTime` (AR-10, chwila zapisu pliku zaraz po integracji - źródło
        mówi tooltip), a bez obu człon po prostu nie staje (data pliku w systemie plików nie jest
        datą integracji: zapis nagłówka przez Horreum ją przestawia). Rodzaj jest zawsze, bo zawsze
        jest werdyktem read-modelu, także „nieustalone".

        Werdykt „zostawiam wszystkie" (0026) stoi PIERWSZYM członem - kolumna bywa ucięta przy
        wąskim oknie, a to on mówi, że w tej grupie nie ma już roboty; komórka jest wtedy wyciszona.
        Etykieta środka kadru („środek A", `queries._srodki_grupy`) to fakt do rozróżnienia stosów
        z dwóch przebiegów kamery kolorowej, które poza nią różni tylko nazwa - nie świadek wersji.
        Liczba obrazów (AR-10) to fakt kopii z kolumny „Obrazy" (`_images`, ta sama wartość): XISF
        mówi „3 obrazy", FITS „obrazy: -" - czytnik FITS obrazów nie liczy (0021), a pusta komórka
        wyglądała jak brak danych."""
        f = row.get("_wersja")
        if not f:
            return None
        if role == Qt.DisplayRole:
            czlony = [i18n.t("grid.version.kept")] if f.get("kept") else []
            czlony.append(i18n.t(f"grid.version.kind.{f['kind']}"))
            if f.get("witness"):
                czlony.append(i18n.t(f"grid.version.short.{f['witness']}"))
            if f.get("center"):
                czlony.append(i18n.t("grid.version.center", label=f["center"]))
            if f.get("timestamp"):
                czlony.append(_chwila(f["timestamp"]))
            if f.get("declared_rows") is not None:
                czlony.append(i18n.t_plural("grid.version.inputs", f["declared_rows"]))
            if row.get("_images_n") is not None:
                czlony.append(i18n.t_plural("grid.version.images", row["_images_n"],
                                            count=row.get("_images") or row["_images_n"]))
            elif row.get("filetype") == "fits":
                czlony.append(i18n.t("grid.version.images_fits"))
            return " · ".join(czlony)
        if role == Qt.ToolTipRole:
            swiadek = f.get("witness")
            tip = (i18n.t(f"grid.version.why.{swiadek}" if swiadek else "grid.version.why.none")
                   + i18n.t("grid.version.window", start=_okno(f.get("window_start")),
                            end=_okno(f.get("window_end"))))
            if f.get("timestamp_source"):
                tip += i18n.t(f"grid.version.when.{f['timestamp_source']}")
            if f.get("center"):
                ra, dec = f["center_radec"]
                tip += i18n.t_plural("grid.version.center_tip", f.get("centers") or 0,
                                     label=f["center"], ra=f"{ra:.4f}", dec=f"{dec:+.4f}")
            if row.get("_images_n") is None and row.get("filetype") == "fits":
                tip += i18n.t("grid.version.images_fits_tip")
            if f.get("kept"):
                tip += i18n.t("grid.version.kept_tip", at=_chwila(f.get("kept_at")) or "?",
                              reopen=i18n.t("grid.version.reopen"))
            return tip
        if role == Qt.ForegroundRole and (f["kind"] != queries.WERSJA_INNA or f.get("kept")):
            return _COLORS["missing"]      # bez dowodu wersji albo po werdykcie - wyciszone
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
        if "cards" in pv:
            # Wpis ze stagingu przebiegu (AR-61): wszystkie karty klatki, które zapisze commit. Jedna
            # karta wygląda jak podgląd makra; kilka - każda z nazwą keyworda, żeby nie zgadywać.
            # Komentarz, który zapis wniesie, jest częścią zmiany: przy samej zmianie komentarza
            # (wartość bez zmian) komórka mówi „komentarz → …" zamiast „RC8 → RC8", a przy zmianie
            # wartości komentarz stoi w podpowiedzi.
            karty = pv["cards"]

            def _zmiana(k):
                if k.get("comment") is not None and k["old"] == k["new"]:
                    return i18n.t("grid.preview.comment_only", comment=k["comment"])
                return f"{'∅' if k['old'] is None else k['old']} → {k['new']}"

            def _tip(k):
                tip = f"{k['keyword']}: {k['old']!r} → {k['new']!r} ({k['op']})"
                if k.get("comment") is not None:
                    tip += i18n.t("grid.preview.comment_tip", comment=k["comment"])
                return tip
            if role == Qt.DisplayRole:
                if len(karty) == 1:
                    return _zmiana(karty[0])
                return " · ".join(f"{k['keyword']}: {_zmiana(k)}" for k in karty)
            if role == Qt.ToolTipRole:
                return "\n".join(_tip(k) for k in karty)
            if role == Qt.FontRole:
                f = QFont(); f.setBold(True); return f
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
                # Wchłonięty szkielet (AR-42, flaga `absorbed` z `base_rows`) to nie podmiana treści:
                # plik wyzdrowiał. Osobne zdanie, to samo ogniwo do następczyni.
                if superseded and row.get("absorbed"):
                    return i18n.t("grid.cell.absorbed", id=row.get("superseded_by"))
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
                extra = i18n.t("grid.tip.absorbed", id=row.get("superseded_by")) if (
                    superseded and row.get("absorbed")) else _superseded_tip(row) if superseded else (
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
        if key == "_images":
            return self._images_cell(row, role)
        if key == "_rodowod":
            # Stan rodowodu gotowego obrazu; n.d. (inny rodzaj) = pusta komórka bez podpowiedzi.
            stan = row.get("_rodowod")
            if stan is None:
                return "" if role == Qt.DisplayRole else None
            if role == Qt.DisplayRole:
                return i18n.t(_STANY_RODOWODU[stan])
            if role == Qt.ToolTipRole:
                return i18n.t(_TIPY_RODOWODU[stan])
            # Role z motywu: „do potwierdzenia" to robota (warn), „z okna czasu" - kandydat, którego
            # nikt nie potwierdził (secondary); brak rodowodu - rola braku, jak brak karty.
            if stan == "pending" and role == Qt.ForegroundRole:
                return _COLORS["warn"]
            if stan == "window" and role == Qt.ForegroundRole:
                return _COLORS["secondary_text"]
            if stan in _RODOWOD_BRAK:
                if role == Qt.ForegroundRole:
                    return _COLORS["missing"]
                if role == Qt.FontRole:
                    f = QFont(); f.setItalic(True); return f
            return None
        if key == "exptime":
            # Czas ekspozycji Znajdź: jedna precyzja na kolumnę (`miejsca_ekspozycji`, jak EXPTIME) -
            # „300 s" przy samych pełnych sekundach, do prawej jak każda kolumna liczb; sort liczbowy
            # w `_sort_key`.
            v = row.get("exptime")
            if role == Qt.DisplayRole:
                return "" if v is None else i18n.t("find.cell.exposure",
                                                   s=f"{float(v):.{self._miejsca_czasu}f}")
            if role == Qt.TextAlignmentRole and v is not None:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None
        if key == "note":
            # Uwaga ścięta szerokością kolumny, pełna w tooltipie - kolumna zapowiada, nie czyta.
            v = row.get("note")
            if role == Qt.DisplayRole:
                return v or ""
            if role == Qt.ToolTipRole and v:
                return v
            return None
        if role == Qt.DisplayRole:
            v = row.get(key)
            return "" if v is None else str(v)
        return None

    def _images_cell(self, row, role):
        """Komórka „Obrazy": liczba (albo „3 | 1" przy kopiach różnych) wyrównana do prawej, jak
        każda kolumna liczb.

        BRAK LICZBY MÓWI „?" TYLKO TAM, GDZIE JEST ROBOTĄ (`_obrazy_pytajnik`, perspektywy
        `_FLAGI_OBRAZOW`), i tylko przy kopii, którą uzupełnienie faktów w ogóle czyta - flaga
        `copy_facts_class` z read-modelu (`queries.base_rows`), liczona TYM SAMYM literałem co etap
        Dostawy (`queries.copy_facts_class`, AR-35): XISF albo klatka z więcej niż jedną lokacją ogółem.
        Pojedynczy FITS faktów z założenia nie dostaje, więc „?" z receptą byłby przy nim obietnicą
        bez pokrycia - zostaje pusty. Poza tymi perspektywami pusta komórka zostaje pusta: tam
        „nie wiem" jest stanem archiwum, nie robotą."""
        tekst = row.get("_images") or ""
        if tekst:
            if role == Qt.DisplayRole:
                return tekst
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None
        if not (self._obrazy_pytajnik and row.get("copy_facts_class")):
            return "" if role == Qt.DisplayRole else None
        if role == Qt.DisplayRole:
            return "?"
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            return _COLORS["missing"]
        if role == Qt.ToolTipRole:
            return i18n.t("grid.tip.images_unknown") + i18n.t(
                "grid.tip.copy_unread", place=i18n.t("nav.dostawa"),
                check=i18n.t("pipeline.btn.presence"), mark=i18n.t("pipeline.btn.mark_vanished"))
        return None

    def _kw_cell(self, row, kw, role):
        cell = row["cells"].get(kw, pivot_mod.MISSING)
        if role == Qt.EditRole:
            # Edytor startuje od wartości karty, a przy braku karty od pustego pola - znak „—"
            # w polu edycji zostałby zapisany jako wartość nowej karty.
            return "" if cell is pivot_mod.MISSING or cell.raw is None else str(cell.raw)
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
        if kw == _EXPTIME and cell.num is not None:
            # Jedna precyzja kolumny zamiast zapisu karty (AR-115, reguła przy `miejsca_ekspozycji`).
            if role == Qt.DisplayRole:
                return f"{cell.num:.{self._miejsca_exptime}f}"
            if role == Qt.ToolTipRole and not _dokladnie(cell.num, self._miejsca_exptime):
                return str(cell.raw)
        if role == Qt.DisplayRole:
            return "" if cell.raw is None else str(cell.raw)
        if role == Qt.TextAlignmentRole and kw in self._numeric_kw:
            return int(Qt.AlignRight | Qt.AlignVCenter)   # wyrównanie kolumny, nie karty (AR-77)
        return None

    # ---- sort + grupowanie ----
    def set_group_by(self, group_by):
        self._group_by = group_by
        self._rebuild()

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort_id = self._sort_id_for(column)      # znaczenie kolumny, nie jej numer
        self._sort_desc = order == Qt.DescendingOrder
        self._rebuild()

    def _sort_key(self, row):
        sid = self._sort_id
        # Kolumny sortu nie ma w bieżącym układzie (keyword odznaczony, „Wersja" poza swoją
        # perspektywą) → sort neutralny; wróci sam, gdy kolumna wróci (`_sort_id` pamięta znaczenie).
        if (sid is None or (sid[0] == "kw" and sid[1] not in self._keywords)
                or (sid[0] == "version" and self._version_col() is None)
                or (sid[0] == "base" and not self.has_base_col(sid[1]))):   # np. Δh w Znajdź
            return (0, "")
        if sid[0] == "version":
            # Po CHWILI INTEGRACJI (ISO sortuje się chronologicznie), potem po liczbie wejść;
            # wiersz bez faktów - na koniec, jak MISSING (kierunek sortu go nie przenosi).
            # BRAK CZŁONU TEŻ NA KOŃCU, w obu kierunkach (wzór `_dt_delta`): pusty napis i zero
            # stawiały stos bez sygnatury PRZED znanymi datami. Znacznik braku zależy od kierunku,
            # bo `_rebuild` odwraca cały klucz - po odwróceniu ma wylądować za znanymi wartościami.
            f = row.get("_wersja")
            if not f:
                return (2, "")
            brak = -1 if self._sort_desc else 1
            ts, n = f.get("timestamp"), f.get("declared_rows")
            return (0, 0 if ts else brak, ts or "", 0 if n is not None else brak, n or 0)
        if sid[0] == "base":
            key = sid[1]
            if key == "_dt_delta":                            # gałąź numeryczna (R1 #6), None na koniec
                v = row.get("_dt_delta")
                return (2, 0.0) if v is None else (0, float(v))
            if key == "_images":
                # LICZBA, NIE TEKST: „10" stało przed „2", a pusta komórka na górze. Klatka z kilkoma
                # kopiami sortuje się po największej liczbie (`_images_n`); brak - na koniec w obu
                # kierunkach, jak MISSING (wzór `_dt_delta`).
                v = row.get("_images_n")
                return (2, 0) if v is None else (0, v)
            if key == "_rodowod":
                # Po PEWNOŚCI (kolejność `_STANY_RODOWODU` = `queries.LINEAGE_STATES`), nie po
                # alfabecie etykiety; n.d. na koniec w obu kierunkach, jak MISSING.
                v = row.get("_rodowod")
                return (2, 0) if v is None else (0, list(_STANY_RODOWODU).index(v))
            if key == "exptime":                             # liczba, brak na koniec (wzór `_images`)
                v = row.get("exptime")
                return (2, 0.0) if v is None else (0, float(v))
            v = row.get(key)
            return (0, "" if v is None else str(v).lower())
        cell = row["cells"].get(sid[1], pivot_mod.MISSING)
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
            drzewa = {queries.hint_from_stacks_tree(r.get("path"), r.get("library_root"))
                      for r in bucket}
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
        if self._group_by == "_rodowod" and v is None:
            # Klatka, która nie jest gotowym obrazem: „nie dotyczy", NIE „(brak)" - obok stoi stan
            # „brak" rodowodu i dwa kubełki o jednym słowie znaczyłyby dwie różne rzeczy.
            return i18n.t("grid.lineage.state.nd")
        if v in (None, ""):
            return "(brak)"
        if self._group_by == "_dt_delta":
            return f"{v:g}"                                    # etykieta grupy spójna z komórką („-2")
        if self._group_by == "_rodowod":
            return i18n.t(_STANY_RODOWODU[v])                  # belka mówi słowem komórki, nie tokenem
        return str(v)

    def _group_label(self, row):
        """Podpis belki kubełka, do którego należy `row`. Zwykle to sama wartość grupowania; grupa
        wersji ma podpis OSOBNO od klucza (`_adnotuj_wersje`): kubełek wyznacza stabilny
        identyfikator, a człowiek czyta opis materiału - dwie grupy o jednym opisie zostają dwiema
        belkami."""
        if self._group_by == _GRUPA_WERSJI and row.get("_wersja_etykieta"):
            return row["_wersja_etykieta"]
        return self._group_value(row)

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
            elif self._group_by == "_rodowod":               # belki po PEWNOŚCI, n.d. na końcu
                kolejnosc = list(_STANY_RODOWODU)
                rows = sorted(rows, key=lambda r: (
                    kolejnosc.index(r["_rodowod"]) if r.get("_rodowod") else len(kolejnosc)))
            elif self._group_by == _GRUPA_WERSJI:            # porządek belek po PODPISIE, kubełek
                rows = sorted(rows, key=lambda r: (           # po IDENTYFIKATORZE grupy
                    self._group_label(r).lower(), self._group_value(r)))
            else:
                rows = sorted(rows, key=lambda r: (self._group_value(r) or "").lower())
            self._rows = []
            cur = object()
            bucket = []
            def flush():
                if bucket:
                    stan = self._group_state(bucket)
                    self._rows.append({"_group": self._group_label(bucket[0]), "_count": len(bucket),
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
