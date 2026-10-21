"""Okno „Wciągnij wyniki WBPP” - żniwa masterów flat i stosów z wyjścia WBPP do bibliotek archiwum.

Okno odpowiada na jedno pytanie: które pliki z katalogu wyjścia WBPP Horreum umie przypiąć do
swoich klatek (master flat do surowych flatów, stos do lightów wydania), dokąd pójdą i pod jaką
nazwą. Odpowiedź liczy Qt-wolny rdzeń `horreum.harvest` (plan bez mutacji, kopia przez klingę
`projection.copy_master`); tu jest glue widżetów wzorem okna wydania (`projection_dialog`): auto-DRY
w wątku tła z licznikiem generacji, apply w wątku tła z anulowaniem na granicy pliku,
`off_thread=False` jako seam testowy.

LISTA WYDAŃ nad polem wyjścia, bo człowiek nie pamięta, gdzie WBPP oddał wyniki: wydanie obiektu
kładzie wyjście w `<karta>\\OBJECTS\\<obiekt>\\out`, a karty zna gospodarz (folder roboczy WBPP
i karty celu wydania). Stan wiersza (`harvest.releases`) liczy się z dysku, z TREŚCI zeznań żniw
biegów do archiwum okna (zeznanie biegu do innego archiwum nie świadczy - AR-105) i z rodowodu
stosów w bazie, nie z pamięci okna - w wątku tła z własnym licznikiem generacji, bo to spacer po
drzewach kart, także po SMB. Na starcie zaznacza się najnowsze wydanie z czymś do wciągnięcia, a wybór wiersza
to pole wyjścia i auto-DRY - do kopii zostaje jeden klik. Po każdym biegu lista liczy się
ponownie; wiersz bez niczego do wciągnięcia mówi, że folder wydania można skasować, i otwiera go -
okno niczego nie kasuje. Stos wciągnięty z wydania, którego rodowodu dokładnego baza jeszcze nie ma
(zwykłe „Zamknij”, a potem osobna Dostawa - AR-104), zatrzymuje to zdanie: zbiór jego wejść leży
tylko w zeznaniu żniw w tym folderze, więc lista odsłania „Zamknij i przyjmij” od otwarcia okna,
a wiersz mówi „rodowód do zapisania”. Wybór wiersza ani wynik listy nie przestawiają pola, które człowiek już
wskazał sam: pole jest prawdą, zaznaczenie listy idzie za nim.

STOSY idą do `<archiwum>\\STACKS`, nie pod `CALIBRATION`, więc korzeń przyjęcia przy stosie to korzeń
archiwum (sito `STACKS` łańcucha Dostawy), a nie wspólny rodzic kopii. Dokładny zbiór wejść stosu
(`frame_ids` planu) wraca do gospodarza w `harvested_stacks` razem z kanonem obiektu wydania
(AR-103: gospodarz porównuje go po łańcuchu z obiektem stosu) - rodowód zapisuje on po łańcuchu,
okno bazy nie tyka. Przyjąć można też kopie, które leżą w archiwum, a których baza nie zna (`exists`
z `known_to_db=False`: wciągnięte w innym oknie bez przyjęcia) - bieg bez nowej kopii też ma wtedy
co oddać Dostawie.

DRY idzie w tle, bo plan czyta pliki: master to ~100 MB, a jego tożsamość (`sha1_data`,
`file_sha1`) liczy się z całych bajtów - kilka masterów na SMB to sekundy, w których okno nie
może stać. Sonda startuje WYŁĄCZNIE na zdarzeniach dyskretnych (otwarcie z pamięci, „Wskaż…”,
Enter albo wyjście z pola, „Zmień…” archiwum), nie na każdym klawiszu: `discover` chodzi
rekurencyjnie, a pole w połowie pisania („E:\\”) kazałoby mu przejść cały dysk. Sonda jest
anulowalna na granicy pliku (`should_cancel` rdzenia) - zamknięcie okna w jej trakcie czeka
najwyżej na jeden plik. Tekst pola różny od sondowanego wyszarza tabelę: podgląd mówi
o katalogu, którego w polu już nie ma.

Dwa przyciski, każdy z jedną rolą: „Wciągnij N” (domyślny, kopie) i „Zamknij i przyjmij do
archiwum” (widoczny od pierwszej kopii do przyjęcia). Żaden nie zmienia znaczenia na
zdarzeniu z tła - przycisk, który pod kursorem zamienia się z kopii w zamknięcie okna, łapie
klik przeznaczony dla poprzedniej roli. Enter nigdy nie przyjmuje: w polu potwierdza ścieżkę,
w reszcie okna trafia w „Wciągnij”, który bez świeżego planu jest wygaszony.

Okno NIE uruchamia łańcucha Dostawy: bieg etapów ma jednego właściciela (`PipelineView`).
Wynik dla gospodarza to trzy atrybuty: `summary` (zdanie na pasek stanu), `harvested_root`
(korzeń do przyjęcia) i `harvested_stacks` (stosy ze zbiorem wejść: wciągnięte w tym oknie, zastane
bez wiedzy bazy i znane bazie bez rodowodu dokładnego). Dwa
ostatnie ustawia WYŁĄCZNIE gest „Zamknij i przyjmij do archiwum” i tylko wtedy, gdy kopie leżą
w bibliotekach archiwum okna (`CALIBRATION`, `STACKS`) - stąd archiwum zamrożone od pierwszej kopii
wciągniętej W TYM OKNIE (`_placed_dirs`): dwa archiwa w jednym oknie dałyby korzeń, którego Dostawa
nie powinna skanować. Kopie zastane w archiwum bez wiedzy bazy i stosy bez rodowodu dokładnego z listy
to fakty o BIEŻĄCYM archiwum, nie o tym oknie: „Zmień…” je zeruje, a sonda i lista liczą je dla
nowego - zajrzenie do innego archiwum nie zamyka drogi powrotu (AR-107). Zwykłe „Zamknij”
zostawia kopie na dysku i mówi w `summary`, kiedy baza je pozna, a przy stosach - że rodowód
dokładny zapisze wyłącznie „Zamknij i przyjmij” (Dostawa daje im rodowód okna czasu); instrukcja
przed ścieżką, bo pasek stanu ucina koniec zdania.

Prawda o biegu przychodzi z POSTĘPU, nie z wyniku: katalogi wciągniętych kopii i liczniki
kłopotów zbiera `_on_apply_progress`, więc wyjątek rdzenia po kopiach (gałąź `failed`, bez
wyniku) dalej pokazuje, co leży w archiwum, i pozwala to przyjąć. Zeznanie `_ZNIWA_<ts>.json`,
którego nie udało się zapisać, to ostrzeżenie przy kopiach, które leżą - nie błąd kopii.

Powody przeglądu, statusy i rodzaje jadą LITERALNYMI mapami `_HARVEST_REASONS` / `_STACK_REASONS` /
`_HARVEST_STATUS` / `_HARVEST_KINDS` (wzór `pipeline._REVIEW_REASONS`): kolektor kluczy i18n widzi
tylko literały, a parytet map z rdzeniem (`harvest.REASONS`, `harvest.STATUSES`) i z katalogiem
pilnuje test tego okna. Plik na whiteliście `test_gui_isolation` (warstwa widżetów)."""

from __future__ import annotations

import ast
import dataclasses
import os
import stat
import threading
from collections import Counter
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from horreum import db, harvest, projection
from horreum.gui import i18n, queries
from horreum.gui.grid_panels import ElidedLabel
from horreum.gui.projection_dialog import _COLORS, _elide_path
from horreum.gui.wb_worker import (EtykietaBledu, ZdanieZeSzczegolem,   # błąd systemu w języku UI
                                   tekst_powodu, wiersz_systemu)       # (AR-184), szczegół na pasek (AR-218)
from horreum.item_reasons import powod_okna, powod_systemu   # wyjątek workera jedną regułą okna (AR-264)

# Ile poziomów nad wyjściem WBPP szukać manifestu wydania: WBPP pisze `master/` (i `calibrated/`)
# wewnątrz katalogu roboczego, który wydanie obiektu kładzie pod `<karta>/OBJECTS/<obiekt>` -
# cztery poziomy łapią manifest także wtedy, gdy user wskaże podkatalog wyjścia.
_MANIFEST_LEVELS = 4

# Powód przeglądu → zdanie katalogu. Mapa, nie klucz składany w locie: kolektor `test_i18n` widzi
# tylko literały w `t(...)`, a parytet z `harvest.REASONS` (właścicielem listy jest rdzeń) pilnuje
# test tego okna.
_HARVEST_REASONS = {
    "no_raw_darks": "harvest.reason.no_raw_darks",
    "unreadable": "harvest.reason.unreadable",
    "no_history": "harvest.reason.no_history",
    "no_inputs": "harvest.reason.no_inputs",
    "inputs_unknown": "harvest.reason.inputs_unknown",
    "inputs_ambiguous": "harvest.reason.inputs_ambiguous",
    "mixed_profile": "harvest.reason.mixed_profile",
    "no_profile": "harvest.reason.no_profile",
    "no_night": "harvest.reason.no_night",
    "header_mismatch": "harvest.reason.header_mismatch",
    "outside_release": "harvest.reason.outside_release",
    "no_config": "harvest.reason.no_config",
    "name_taken": "harvest.reason.name_taken",
    "no_release": "harvest.reason.no_release",
    "no_light_seat": "harvest.reason.no_light_seat",
    "color_unknown": "harvest.reason.color_unknown",
    "foreign_calibration": "harvest.reason.foreign_calibration",
    "seat_unreadable": "harvest.reason.seat_unreadable",
}

# Powód STOSU, którego zdanie różni się od zdania tego samego tokenu przy master flacie. Stos
# z wejściami spoza wydania ma receptę (skopiować ręką do `STACKS`, Dostawa go weźmie) i liczbę
# wejść; master flat spoza wydania nie ma ani jednego, ani drugiego. Klucze ⊆ `harvest.REASONS`.
_STACK_REASONS = {
    "outside_release": "harvest.reason.outside_release_stack",
}

# Rodzaj pozycji (`HarvestItem.kind`, ten sam, który nada skan kopii) → słowo kolumny „Rodzaj”.
# Plik z nazwą mastera, którego nagłówek mówi o surowej klatce (`IMAGETYP=FLAT` bez historii
# integracji), dostaje rodzaj surowy - i słowo „surowy …”, nie token `flat`: wiersz idzie wtedy do
# przeglądu (`header_mismatch`), a kolumna ma powiedzieć, za co skan go weźmie. Zbiór rodzajów
# = `resolve.frames._KIND_MAP` + `unknown`; rodzaj spoza mapy renderuje się tokenem, jak status.
_HARVEST_KINDS = {
    "master_flat": "harvest.kind.master_flat",
    "master_light": "harvest.kind.master_light",
    "master_dark": "harvest.kind.master_dark",
    "light": "harvest.kind.light",
    "flat": "harvest.kind.flat",
    "dark": "harvest.kind.dark",
    "bias": "harvest.kind.bias",
    "unknown": "harvest.kind.unknown",
}

# `header_mismatch` stosu bez czytelnego `DATE-OBS`: rdzeń niesie w `detail` napis
# `DATE-OBS <repr wartości>` (`harvest._plan_stack`, krok nazwy). To nie jest niezgodność nagłówka
# z wejściami, tylko brak daty, której wymaga nazwa stosu - zdanie mówi to wprost, a wartość
# pokazuje bez `repr` („DATE-OBS None” nic człowiekowi nie mówi).
_DATE_OBS_DETAIL = "DATE-OBS "

# Status pozycji → rola koloru kolumny „Stan” (kolory z motywu: `projection_dialog._COLORS`,
# przeładowuje je `app.apply_theme`). Wciągnięty = ok; do przeglądu i przerwany = ostrzeżenie (plik
# czeka na człowieka); konflikt, błąd i bajty inne niż w podglądzie = błąd. „Do wciągnięcia” i „już
# w archiwum” bez roli - to stan zwykły, nie wynik ani kłopot.
_STATUS_ROLES = {"placed": "ok", "review": "warn", "cancelled": "warn",
                 "conflict": "error", "error": "error", "verify_bad": "error"}

# Status pozycji (plan i apply) → słowo w tabeli. Ta sama zasada literalności; parytet
# z `harvest.STATUSES`.
_HARVEST_STATUS = {
    "would-place": "harvest.status.would_place",
    "exists": "harvest.status.exists",
    "review": "harvest.status.review",
    "placed": "harvest.status.placed",
    "verify_bad": "harvest.status.verify_bad",
    "conflict": "harvest.status.conflict",
    "error": "harvest.status.error",
    "cancelled": "harvest.status.cancelled",
}

# Kłopoty biegu, które `summary` dokłada do zdania (zera milczą) - w kolejności zdania.
_TROUBLE_KEYS = (("conflict", "harvest.sum_conflict"), ("error", "harvest.sum_error"),
                 ("verify_bad", "harvest.verify_bad_tail"))

# Kolumny tabeli. Powód przed ścieżkami: to jedyna kolumna, która mówi, CO się nie zgadza, więc
# stoi przy pliku i stanie, a nie za dwiema ścieżkami - przy oknie węższym niż treść ścieżki
# przewijają się w bok, powód zostaje w kadrze (`_fit_columns`). Rodzaj (krótkie słowo) stoi przy
# pliku z tego samego powodu: za ścieżkami wypadałby z kadru.
COL_FILE, COL_KIND, COL_STATUS, COL_REASON, COL_NAME, COL_DIR, COL_RELEASE = range(7)
_HEADERS = ("harvest.col.file", "harvest.col.kind", "harvest.col.status", "harvest.col.reason",
            "harvest.col.name", "harvest.col.dir", "harvest.col.release")
_SCREEN_SHARE = 0.9                      # okno rośnie pod treść najwyżej do tej części ekranu (szerokość i wysokość)

# Lista wydań: kolumny i wysokość. Lista stoi NAD polem i nie może zjeść tabeli pozycji - widać
# najwyżej tyle wierszy, dalej przewija się sama.
REL_OBJECT, REL_CARD, REL_DATE, REL_STATE = range(4)
_REL_HEADERS = ("harvest.rel.col.object", "harvest.rel.col.card", "harvest.rel.col.date",
                "harvest.rel.col.state")
_REL_VISIBLE_ROWS = 4


# ---------------------------------------------------------------- pomocniki Qt-WOLNE (testowane wprost)

def clean_path(text):
    """Ścieżka z pola: bez białych znaków i bez cudzysłowów, które dokłada Eksplorator
    („Kopiuj jako ścieżkę” daje `"E:\\WBPP\\master"`) - z nimi ścieżka nie istnieje."""
    p = (text or "").strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
        p = p[1:-1].strip()
    return p


def norm_path(path):
    """Klucz porównania ścieżek na Windows: znormalizowana, bez wielkości liter (NTFS ich nie
    odróżnia)."""
    return os.path.normcase(os.path.normpath(path))


def is_under(path, root):
    """`path` leży w `root` albo jest nim (porównanie `norm_path`); różne wolumeny → False."""
    p, r = norm_path(path), norm_path(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False


def find_manifest(wbpp_dir, levels=_MANIFEST_LEVELS, *, errors_out=None):
    """Manifest wydania (`_PROJEKCJA.json`) w `wbpp_dir` albo do `levels` poziomów wyżej →
    `(korzeń, treść)`; brak → `(None, None)`. Pierwszy znaleziony wygrywa - najbliższe wydanie
    jest tym, w którego drzewie WBPP pracowało. Wyjątku nie ma (`read_manifest` jest tolerancyjny).

    `errors_out` (lista, AR-234): manifest, który LEŻY, a nie da się go przeczytać (błąd systemu
    klasą albo plik uszkodzony) - `(ścieżka manifestu, powód)` i KONIEC szukania z `(korzeń, None)`:
    to manifest najbliższego wydania, a manifest wyżej należałby do innego drzewa. Bez listy szukanie
    idzie wyżej jak dotąd, a plan bez świadka mówił stosom „brak manifestu wydania”."""
    d = os.path.abspath(wbpp_dir)
    for _ in range(levels + 1):
        bledy = []
        payload = projection.read_manifest(d, errors_out=bledy)
        if payload is not None:
            return d, payload
        if bledy and errors_out is not None:
            errors_out.extend(bledy)
            return d, None
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None, None


def status_counts(items):
    """Liczność statusów pozycji (plan albo wynik apply) - jedno źródło dla nagłówka i przycisku."""
    return Counter(it.status for it in items)


def status_text(status):
    """Słowo statusu z katalogu. Status spoza mapy renderuje się tokenem, nie pustką - nowy status
    rdzenia ma być widoczny w tabeli, zanim ktoś dopisze mu zdanie."""
    key = _HARVEST_STATUS.get(status)
    return i18n.t(key) if key else status


def kind_text(kind):
    """Słowo kolumny „Rodzaj” (master flat, stos). Rodzaj spoza mapy renderuje się tokenem."""
    key = _HARVEST_KINDS.get(kind)
    return i18n.t(key) if key else (kind or "")


def reason_text(item):
    """Kolumna „Powód” (Qt-wolne). `reason` to TOKEN rdzenia (`harvest.REASONS`) - zdanie z mapy
    z `reason_n` (ile wejść, profili, nazw); `detail` to dane od rdzenia: CO się nie zgadza
    (nagłówek kontra profil), pierwsze nazwy nietrafionych wejść, wyjątek czytnika, ścieżka
    biblioteki `STACKS` albo cudzego mastera. Ekran pokazuje oba, bo sama kategoria nie mówi, co
    poprawić - receptę niesie zdanie z katalogu, nie `detail` (dane rdzenia nie znają języka ekranu).
    Stos bierze zdanie z `_STACK_REASONS`, gdy jego token ma tam własne. Po apply token jest pusty,
    a `detail` niesie tekst klingi kopii (konflikt, błąd I/O). Pozycja `exists` bez obecnej kopii
    mówi to wprost - pusta kolumna katalogu wyglądałaby jak błąd. Token spoza mapy renderuje się
    sam, nie pustką. `header_mismatch` z `DATE-OBS` w `detail` mówi o dacie nazwy stosu
    (`date_obs_text`), nie o niezgodności z wejściami. `detail` z błędem systemu klasą
    (`PowodPozycji` `os_*`: kopia, czytnik, AR-184) mówi w języku UI przez `tekst_powodu`, a surowy
    tekst systemu stoi w podpowiedzi komórki (`_fill`). Dane bez kodu idą przez `czytelny_powod`:
    ścieżka w zapisie `repr` traci podwojone ukośniki (`'X:\\\\a'` → `'X:\\a'`), plik zajęty
    (WinError 32/33) mówi słowami okna z nazwą pliku; reszta przechodzi znak w znak."""
    detail = (tekst_powodu(item.detail) or "").strip()
    if item.reason == "header_mismatch" and detail.startswith(_DATE_OBS_DETAIL):
        return date_obs_text(detail[len(_DATE_OBS_DETAIL):])
    if item.reason:
        key = ((_STACK_REASONS.get(item.reason) if item.kind == "master_light" else None)
               or _HARVEST_REASONS.get(item.reason))
        text = i18n.t(key, n=item.reason_n or 0) if key else item.reason
        return f"{text}: {detail}" if detail else text
    if detail:
        return detail
    if item.status == "exists" and not item.exists_path:
        return i18n.t("harvest.exists_no_copy")
    return ""


def date_obs_text(wartosc):
    """Zdanie powodu stosu bez czytelnego `DATE-OBS` z wartości, którą rdzeń wpisał `repr`-em
    (`None` albo napis w cudzysłowie): brak karty - jedno zdanie, karta bez godziny albo śmieć -
    drugie, z wartością bez cudzysłowów. Napis spoza `repr` pokazuje się taki, jaki przyszedł."""
    try:
        wartosc = ast.literal_eval(wartosc)
    except (ValueError, SyntaxError):
        pass
    if wartosc is None:
        return i18n.t("harvest.reason.date_obs_missing")
    return i18n.t("harvest.reason.date_obs_unreadable", value=wartosc)


def status_role(status):
    """Rola koloru kolumny „Stan” (`_STATUS_ROLES`) albo None - status bez znaczenia kłopotu."""
    return _STATUS_ROLES.get(status)


def name_text(item):
    """Kolumna „Nazwa docelowa”: nazwa planu, a dla `exists` - nazwa pliku, który już leży.
    Pozycja z wejściami z kilku nocy mówi o nocach OBOK nazwy: nazwa niesie najwcześniejszą,
    a WBPP grupuje flaty po filtrze, więc druga noc to fakt do zobaczenia, nie odmowa."""
    name = item.name or (os.path.basename(item.exists_path) if item.exists_path else "")
    nights = list(item.nights or ())
    if name and len(nights) > 1:
        name += i18n.t("harvest.nights", nights=", ".join(nights))
    return name


def dir_of(item):
    """Katalog docelowy pozycji: siedziba planu albo katalog kopii, która już leży; brak → ''."""
    path = item.dst or item.exists_path
    return os.path.dirname(path) if path else ""


def release_text(item):
    """Kolumna „Wydanie”: `(obiekt, zestaw)` z manifestu-świadka; „poza wydaniem Horreum” WYŁĄCZNIE
    dla pozycji, które plan ocenił do końca i które idą (albo poszły) do archiwum bez świadka.
    Pozycja odrzucona wcześniej (dark, nieczytelna, nieznane wejścia) albo już w archiwum nie
    przeszła przez manifest - zdanie o wydaniu byłoby o niej nieprawdą, więc komórka milczy.
    Nazwy obiektu i zestawu to wartości domenowe - bez tłumaczenia."""
    if item.release:
        return " / ".join(str(x) for x in item.release)
    if item.status in ("would-place", "placed"):
        return i18n.t("harvest.outside_release")
    return ""


def rel_text(path, root):
    """Ścieżka do tabeli: WZGLĘDEM `root`, gdy w nim leży, inaczej pełna. Archiwum i wyjście WBPP
    stoją w wierszach nad tabelą, więc w komórce zostaje to, co odróżnia wiersze - podkatalog
    wyjścia przy czterech plikach o tej samej nazwie, ogon `CALIBRATION\\…` przy celu. Ścieżka
    ucięta środkiem gubiła właśnie tę część. Cel spoza `root` (kopia w archiwum, które pamięta
    baza) pokazuje się cały - skrót udawałby, że leży w archiwum okna."""
    if not path:
        return ""
    if root and is_under(path, root):
        rel = os.path.relpath(path, root)
        return path if rel == os.curdir else rel
    return path


def common_root(dirs):
    """Wspólny rodzic katalogów, do których coś wciągnięto - korzeń skanu po żniwach; brak
    katalogów albo różne wolumeny (`commonpath` nie łączy `R:` z `E:`) → None."""
    dirs = sorted({d for d in dirs if d})
    if not dirs:
        return None
    try:
        return os.path.commonpath(dirs)
    except ValueError:
        return None


def plan_counts(items):
    """`(do wciągnięcia, już w archiwum, do przeglądu)` świeżego planu - liczby wiersza listy, którego
    `out` właśnie przeliczył podgląd."""
    c = status_counts(items)
    return c.get("would-place", 0), c.get("exists", 0), c.get("review", 0)


@dataclasses.dataclass(frozen=True)
class SondaNiepelna:
    """Wpis „świeżego” stanu wiersza po podglądzie `out`, który nie przeczytał wyjścia całego
    (`unreadable` = katalogi nieprzeczytane) albo padł (`unreadable == 0`), AR-222. BLOKADA
    bezwzględna: stan wiersza mówi o niej, nie o liczbach, a `is_harvested` jest fałszywe - ani liczby
    tego podglądu (nie obejmują nieprzeczytanego), ani liczby listy sprzed niego (stare) nie mogą
    odsłonić zdania „folder możesz skasować”. Zdejmuje ją dopiero pełny podgląd tego `out`."""
    unreadable: int = 0


def release_counts(row, fresh=None):
    """`(niewciągnięte, wciągnięte, do przeglądu)` wiersza listy: ze świeżego planu (`plan_counts`),
    gdy podgląd przeliczył `out` tego wiersza, inaczej z listy (`harvest.ReleaseRow`). Pod blokadą
    (`SondaNiepelna`) - liczby listy wyłącznie dla zdań, które WSTRZYMUJĄ kasowanie (przegląd,
    rodowód); stan wiersza i `is_harvested` blokują same."""
    if fresh is None or isinstance(fresh, SondaNiepelna):
        return row.pending, row.done, row.review
    return fresh


def manifest_error_text(powod, path):
    """Zdanie o manifeście wydania, który LEŻY, a nie da się go przeczytać (AR-234) - Qt-wolne,
    jedno dla podglądu wyjścia (`HarvestDryWorker`) i podpowiedzi wiersza listy: plik uszkodzony
    (`proj_manifest_damaged`) mówi pole, które padło, i radę; błąd systemu - klasę w języku UI
    (surowy tekst systemu idzie do szczegółu, `wiersz_systemu`)."""
    if getattr(powod, "code", None) == "proj_manifest_damaged":
        return i18n.t("harvest.manifest_damaged", path=path, detail=dict(powod.params).get("detail"))
    return i18n.t("harvest.manifest_unreadable", path=path, msg=tekst_powodu(powod))


def release_manifest_state(row):
    """Człon stanu wiersza o manifeście wydania (AR-234) - „manifest uszkodzony (JSON)” albo
    „manifest nieczytelny: <klasa>” - albo `""`, gdy manifest przeczytano."""
    powod = row.manifest_error
    if powod is None:
        return ""
    if getattr(powod, "code", None) == "proj_manifest_damaged":
        return i18n.t("harvest.rel.manifest_damaged", detail=dict(powod.params).get("detail"))
    return i18n.t("harvest.rel.manifest_unreadable", msg=tekst_powodu(powod))


def release_state_tip(row):
    """Podpowiedź komórki stanu: wyjście WBPP wiersza, a przy manifeście nie do przeczytania - zdanie
    o nim (`manifest_error_text`) i szczegół systemu (AR-234)."""
    if row.manifest_error is None:
        return row.out_dir
    sciezka = os.path.join(row.object_root, projection.MANIFEST_NAME)
    return "\n".join(w for w in (manifest_error_text(row.manifest_error, sciezka),
                                 wiersz_systemu(row.manifest_error), row.out_dir) if w)


def release_date_cell(row):
    """`(tekst, podpowiedź)` komórki daty: data z manifestu (`release_date_text`), a data, którą
    naprawa manifestu wzięła z drzewa (`ts_source` - czas założenia folderu zestawu, AR-240) - ze
    znakiem przybliżenia i podpowiedzią, że to data pierwszego wydania zestawu."""
    tekst = release_date_text(row.ts)
    if tekst and row.ts_source == projection.TS_SOURCE_TREE:
        return i18n.t("harvest.rel.date_tree", date=tekst), i18n.t("harvest.rel.date_tree_tip", ts=row.ts)
    return tekst, row.ts


def release_state_text(row, fresh=None):
    """Stan wiersza listy wydań: liczby (zera milczą), a bez żadnej - „czeka na WBPP”. Niewciągnięte
    z listy to „do sprawdzenia”: lista zna zeznania żniw, nie plan - kandydat bez rozstrzygającego
    zeznania może być równie dobrze przeglądem; „do wciągnięcia” mówi dopiero świeży plan (`fresh`).
    Wydanie nowsze od wyników (`awaiting_wbpp`) zaczyna od „czeka na WBPP”, a wciągnięte z poprzednich
    wyników są „poprzednio wciągnięte” - nie są wynikami OSTATNIEGO wydania. Stosy bez rodowodu
    dokładnego w bazie (`row.lineage`, z listy - plan bazy o nie nie pyta) to „rodowód do zapisania”,
    a ścieżki, których lista nie przeczytała (`row.unreadable`, AR-222) - „nieprzeczytane”. Pod blokadą
    podglądu (`SondaNiepelna`) stan mówi wyłącznie o niej - żadnej liczby, więc i żadnego „wciągnięte”.
    Manifest wydania nie do przeczytania (`row.manifest_error`, AR-234) stoi PIERWSZY w każdym stanie."""
    manifest = [release_manifest_state(row)] if row.manifest_error is not None else []
    if isinstance(fresh, SondaNiepelna):
        return " · ".join(manifest + [i18n.t("harvest.rel.unread", n=fresh.unreadable) if fresh.unreadable
                                      else i18n.t("harvest.rel.probe_failed")])
    pending, done, review = release_counts(row, fresh)
    parts = manifest + ([i18n.t("harvest.rel.waiting")] if row.awaiting_wbpp else [])
    if pending:
        parts.append(i18n.t("harvest.rel.pending", n=pending) if fresh is not None
                     else i18n.t("harvest.rel.unchecked", n=pending))
    if done:
        parts.append(i18n.t("harvest.rel.done_before", n=done) if row.awaiting_wbpp
                     else i18n.t("harvest.rel.done", n=done))
    if review:
        parts.append(i18n.t("harvest.rel.review", n=review))
    if row.lineage:
        parts.append(i18n.t("harvest.rel.lineage", n=len(row.lineage)))
    if row.unreadable:
        parts.append(i18n.t("harvest.rel.unread", n=len(row.unreadable)))
    return " · ".join(parts) if parts else i18n.t("harvest.rel.waiting")


def unread_note(dirs, out):
    """`(zdanie, szczegół)` planu NIEPEŁNEGO (AR-222) z `HarvestPlan.unreadable_dirs` - katalogi
    względem wyjścia (`rel_text`), szczegół = wiersze systemu (`wiersz_systemu`, ścieżka w surowym
    tekście); bez katalogów nieprzeczytanych `("", "")`."""
    if not dirs:
        return "", ""
    zdanie = i18n.t_plural("harvest.unread_dirs", len(dirs),
                           paths=", ".join(rel_text(sciezka, out) for sciezka, _powod in dirs))
    return zdanie, "\n".join(w for w in (wiersz_systemu(powod) for _s, powod in dirs) if w)


def is_harvested(row, fresh=None):
    """Folder wydania przestał być Horreum potrzebny: nic do wciągnięcia ani do przeglądu (pliki
    przeglądu leżą tylko tam), coś wciągnięto, wyniki są wynikami OSTATNIEGO wydania, każdy stos
    z tego folderu ma w bazie rodowód dokładny (inaczej zbiór jego wejść leży tylko w zeznaniu żniw),
    a lista przeczytała cały folder - w katalogu nieprzeczytanym (AR-222) mogą leżeć pliki, których
    archiwum nie ma. Ostatni podgląd tego `out` niepełny albo nieudany (`SondaNiepelna`) - nigdy.
    Manifest wydania nie do przeczytania (`manifest_error`, AR-234) - nigdy: plan bez świadka nie
    rozpozna stosów tego wydania, a „ostatnie wydanie” nie ma daty."""
    if isinstance(fresh, SondaNiepelna):
        return False
    pending, done, review = release_counts(row, fresh)
    return (pending == 0 and review == 0 and done > 0 and not row.awaiting_wbpp and not row.lineage
            and not row.unreadable and row.manifest_error is None)


def needs_lineage(row, fresh=None):
    """Nic do wciągnięcia ani do przeglądu, ale stosy czekają na rodowód dokładny - folder potrzebny
    do „Zamknij i przyjmij” (AR-104)."""
    pending, _done, review = release_counts(row, fresh)
    return pending == 0 and review == 0 and bool(row.lineage)


def needs_review(row, fresh=None):
    """Nic do wciągnięcia, ale są pozycje do przeglądu - folderu nie wolno jeszcze kasować."""
    pending, _done, review = release_counts(row, fresh)
    return pending == 0 and review > 0


def preselect_index(rows):
    """Wiersz zaznaczany na starcie: najnowsze wydanie z kandydatami bez rozstrzygnięcia (rdzeń oddaje
    listę od najnowszego), a bez takiego - najnowsze ze stosami czekającymi na rodowód dokładny
    (przycisk przyjęcia stoi wtedy z ich powodu, więc zdanie pod listą ma mówić o nich), albo None.
    Wydanie czekające na WBPP bez takich kandydatów nie jest robotą."""
    return next((i for i, r in enumerate(rows) if r.pending > 0),
                next((i for i, r in enumerate(rows) if r.lineage), None))


def release_date_text(ts):
    """Data wydania z `ts` manifestu: czas LOKALNY `YYYY-MM-DD HH:MM` (manifest pisze UTC, człowiek
    pamięta swój wieczór); nieczytelny znacznik pokazuje się surowy, brak - pusto."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return str(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def release_roots_of(work_root, release_roots):
    """Korzenie kart do listy wydań: folder roboczy pierwszy, potem karty celu; ta sama karta pod
    dwiema pisowniami (`/` i `\\`, wielkość liter) liczy się raz - pierwsza pisownia zostaje."""
    out, seen = [], set()
    for root in ([work_root] if work_root else []) + list(release_roots or ()):
        root = str(root or "").strip()
        if not root:
            continue
        key = norm_path(os.path.abspath(root))
        if key not in seen:
            seen.add(key)
            out.append(os.path.normpath(root))
    return tuple(out)


# ---------------------------------------------------------------- worker DRY (wątek tła)

class HarvestDryWorker(QObject):
    """Plan żniw poza wątkiem GUI. Otwiera WŁASNE połączenie po `db_path` (połączenie SQLite nie
    przechodzi między wątkami); tryb inline (testy, `:memory:`) dostaje żywe `con` wołającego.
    Manifest-świadek szuka tutaj, nie w dialogu: to też odczyt dysku. Wynik niesie GENERACJĘ
    startu - dialog odrzuca wynik sondy, której parametry przestały obowiązywać.

    `request_cancel` (flaga `threading.Event`, stawiana w wątku głównym) idzie do rdzenia jako
    `should_cancel`: `discover`/`plan` przerywają na granicy pliku wyjątkiem `HarvestCancelled`,
    a przerwana sonda NIE emituje wyniku - nikt na niego nie czeka.

    Czytnik mastera bierze z modułu rdzenia W CHWILI biegu (`harvest.read_master`), nie z wartości
    domyślnej `plan` - testy podstawiają czytnik bez czytania XISF, a produkcja czyta pliki."""

    done = Signal(int, object)        # (generacja, payload)
    # (generacja, powód) - `object`: `Signal(str)` zgubiłby kod błędu systemu klasą (AR-184)
    failed = Signal(int, object)
    finished = Signal()

    def __init__(self, db_path, wbpp_dir, archive_root, gen, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._wbpp_dir = wbpp_dir
        self._archive_root = archive_root
        self._gen = gen
        self._cancel = threading.Event()

    def request_cancel(self):
        self._cancel.set()

    @Slot()
    def run(self):
        try:
            payload = self._compute()
        except harvest.HarvestCancelled:
            pass                                     # porzucona sonda - wynik nikomu niepotrzebny
        except Exception as exc:                     # sonda pada szczerze, nie cichą śmiercią wątku
            self.failed.emit(self._gen, powod_okna(exc))
        else:
            self.done.emit(self._gen, payload)
        finally:
            self.finished.emit()

    def _compute(self):
        # `os.stat`, nie `os.path.isdir` (AR-199): `isdir` połyka każdy błąd jako False, więc zerwany
        # udział (WinError 53, 67, 64…) mówił „Katalog nie istnieje”. Brak (2/3: folder, rodzic, dysk)
        # i plik zamiast folderu zostają brakiem; każdy inny błąd systemu - także bez klasy (123: nazwa
        # niepoprawna) - idzie wyjątkiem do `run`, które oddaje go `failed` klasą przez właściciela.
        try:
            jest = stat.S_ISDIR(os.stat(self._wbpp_dir).st_mode)
        except OSError as exc:
            powod = powod_systemu(exc)
            if powod is None or powod.code != "os_missing":
                raise
            jest = False
        if not jest:
            return {"wbpp_dir": self._wbpp_dir, "missing": True}
        # Manifest najbliższego wydania, którego nie da się przeczytać (AR-234): sonda mówi to
        # zdaniem z klasą, zamiast planu bez świadka, w którym stosy dostałyby „brak manifestu”.
        bledy = []
        manifest_root, manifest = find_manifest(self._wbpp_dir, errors_out=bledy)
        if bledy:
            return {"wbpp_dir": self._wbpp_dir, "missing": False, "manifest_error": bledy[0]}
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            plan = harvest.plan(con, self._wbpp_dir, archive_root=self._archive_root,
                                manifest=manifest, read=harvest.read_master,
                                should_cancel=self._cancel.is_set)
        finally:
            if own:
                con.close()
        return {"wbpp_dir": self._wbpp_dir, "missing": False, "plan": plan,
                "manifest_root": manifest_root}


# ---------------------------------------------------------------- worker apply (wątek tła)

class HarvestApplyWorker(QObject):
    """Kopie masterów poza wątkiem GUI (`harvest.apply` → klinga `projection.copy_master`). Bazy
    nie tyka: plan jest policzony, apply czyta i pisze wyłącznie pliki. `progress` po każdym pliku;
    anulowanie przez `threading.Event` (flaga stawiana w wątku głównym, czytana tu) łapie na
    granicy pliku - kopia w połowie zostaje `.part`-em, którego skan nie bierze za mastera."""

    progress = Signal(int, int, str, str)   # done, total, dst, status
    done = Signal(object)                   # HarvestResult (może nieść cancelled=True)
    failed = Signal(object)                 # powód wyjątku → sygnał, nie crash okna (kod: AR-184)
    finished = Signal()

    def __init__(self, plan, now):
        super().__init__()
        self._plan = plan
        self._now = now
        self._cancel = threading.Event()

    def request_cancel(self):
        self._cancel.set()

    @Slot()
    def run(self):
        try:
            res = harvest.apply(self._plan, now=self._now, progress=self._emit_progress,
                                should_cancel=self._cancel.is_set)
        except Exception as exc:
            self.failed.emit(powod_okna(exc))
        else:
            self.done.emit(res)
        finally:
            self.finished.emit()

    def _emit_progress(self, done, total, dst, status):
        self.progress.emit(done, total, dst, status)


# ---------------------------------------------------------------- worker listy wydań (wątek tła)

class HarvestReleasesWorker(QObject):
    """Lista wydań z kart poza wątkiem GUI (`harvest.releases`: spacer po `OBJECTS` każdej karty,
    `discover` w każdym `out`, odczyt zeznań żniw i - dla stosów z zeznań - rodowodu w bazie). Bazę
    czyta WŁASNYM połączeniem po `db_path` (połączenie SQLite nie przechodzi między wątkami); tryb
    inline (testy, `:memory:`) dostaje żywe `con` wołającego. `archive_root` = archiwum okna: świadczą
    tylko zeznania biegów do niego (AR-105). Wynik
    niesie GENERACJĘ startu - dialog odrzuca listę policzoną przed nowszym zamówieniem. Rdzeń nie
    ma punktu przerwania, więc worker nie ma `request_cancel`: porzucona lista po prostu dobiega
    końca i nikt jej nie odbiera. Funkcję bierze z modułu rdzenia W CHWILI biegu (seam testowy)."""

    done = Signal(int, object)        # (generacja, [ReleaseRow])
    # (generacja, `((karta, powód), …)` - powód None = folderu nie ma, inaczej nie da się go przeczytać,
    # `harvest.missing_roots` i `releases(errors_out=)`, AR-222) - przed `done` tej generacji
    missing = Signal(int, object)
    failed = Signal(int, object)      # (generacja, powód) - `object` niesie kod (AR-184)
    finished = Signal()

    def __init__(self, roots, gen, *, archive_root=None, db_path=None, con=None):
        super().__init__()
        self._roots = tuple(roots)
        self._gen = gen
        self._archive_root = archive_root
        self._db_path = db_path
        self._con = con

    @Slot()
    def run(self):
        try:
            own = bool(self._db_path)
            con = db.connect(self._db_path) if own else self._con
            nieczytelne = []                         # karty z `OBJECTS` nie do przeczytania (AR-222)
            try:
                rows = harvest.releases(self._roots, archive_root=self._archive_root or None, con=con,
                                        errors_out=nieczytelne)
            finally:
                if own:
                    con.close()
            brak = harvest.missing_roots(self._roots)
            # Karta, której folderu nie widać, mówi raz - zdaniem z `missing_roots`.
            widziane = {karta for karta, _powod in brak}
            brak += tuple(p for p in nieczytelne if p[0] not in widziane)
        except Exception as exc:                     # lista pada szczerze, nie cichą śmiercią wątku
            self.failed.emit(self._gen, powod_okna(exc))
        else:
            self.missing.emit(self._gen, brak)
            self.done.emit(self._gen, rows)
        finally:
            self.finished.emit()


# ---------------------------------------------------------------- dialog

def _szerokosc_od_okna(label):
    """Zdanie stanu nie dyktuje szerokości okna (AR-140). Zawijanie Qt nie łamie wiersza po `\\`,
    więc ścieżka w zdaniu była jednym słowem, a minimum etykiety - jej pełną szerokością: zdanie
    podglądu z `<wydanie>\\OBJECTS\\<obiekt>` dłuższe od okna poszerzało je samo, okno już nie
    wracało, wskazówka u góry traciła wiersz, a pole z „Wskaż…” i „Zmień…” podjeżdżało pod kursorem
    o ten wiersz. Etykieta bierze szerokość, którą daje jej okno, a ścieżkę dłuższą od okna pole
    zdania łamie po `\\` w kolejnych wierszach (`EtykietaBledu`, AR-221 - miejsca łamania tylko
    w malowaniu). Etykieta jest zaznaczalna (kopia z menu kontekstowego i Ctrl+C - zdanie bez znaków
    łamania), a pełny tekst pod kursorem stawia pole zdania (`EtykietaBledu.ustaw`, AR-204 - zdanie
    ze szczegółem systemu, ten sam protokół co pola okien zapisu i szuflada)."""
    sp = label.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Ignored)
    label.setSizePolicy(sp)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)


class _ZdanieZRezerwa(QLabel):
    """Zdanie, które pod kursorem zmienia się na jedno z kilku zdań katalogu (`klucze`), rezerwuje
    wysokość NAJWYŻSZEGO z nich przy bieżącej szerokości (AR-225): `heightForWidth` = max po zdaniach,
    tekst u góry etykiety - krótsze zdanie zostawia wolne miejsce pod sobą, nie nad. Układ liczy
    wysokość i minimum wiersza przez `heightForWidth` (`_fit_height`, `_podloga_wysokosci` też), więc
    rezerwa idzie za szerokością okna bez własnych haków.

    Dlaczego: wiersz zaznaczonego wydania rezerwował wysokość zdania z konstrukcji („folder możesz
    skasować”), a lista z tła pokazywała inne - krótsze „najpierw rozstrzygnij” podnosiło pole,
    „Wskaż…” i „Zmień…” pod kursorem (natywnie font ×1,6, PL i EN: -18 px; offscreen ×1,6 EN: -14 px),
    dłuższe zdanie o rodowodzie przy wąskim oknie spychało je w dół (natywnie ×1 PL: 32 px wobec 24 px
    rezerwy). Koszt: wiersz od otwarcia ma wysokość najdłuższego zdania (natywnie ×1 PL 24 → 32 px).

    Miarą jest ukryta etykieta-dziecko z zawijaniem, po jednej na zdanie - ta sama droga liczenia co
    etykiety; tekst miary zmienia się tylko, gdy zdanie klucza w języku chwili liczenia jest inne (bez
    zdarzeń zmiany tekstu przy każdym przeliczeniu układu). Font etykiety idzie do miar przy każdym
    liczeniu: przy arkuszu stylu aplikacji `setFont` rodzica nie schodzi do dzieci. Zdania w języku
    chwili liczenia (`i18n.t`); okno żniw jest modalne i budowane przy każdym otwarciu, więc język
    się w jego życiu nie zmienia."""

    def __init__(self, klucze):
        self._klucze = tuple(klucze)
        super().__init__(i18n.t(self._klucze[0]))
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._miary = []
        for _klucz in self._klucze:
            miara = QLabel(self)
            miara.setWordWrap(True)
            miara.hide()
            self._miary.append(miara)

    def heightForWidth(self, w):
        wysokosc = super().heightForWidth(w)
        for klucz, miara in zip(self._klucze, self._miary):
            miara.setFont(self.font())
            zdanie = i18n.t(klucz)
            if miara.text() != zdanie:
                miara.setText(zdanie)
            wysokosc = max(wysokosc, miara.heightForWidth(w))
        return wysokosc


class HarvestDialog(QDialog):
    """Żniwa wyników WBPP: lista wydań z kart (`work_root` = folder roboczy WBPP, `release_roots` =
    karty celu wydania; obie od gospodarza), pole wyjścia WBPP z pamięci (`harvest/last_output`),
    wiersz archiwum (`archive_root` od wołającego - domyślne archiwum podaje gospodarz), auto-DRY,
    tabela pozycji planu, „Wciągnij N” i „Zamknij i przyjmij do archiwum”. `now_fn` = zegar
    (znacznik zeznania `_ZNIWA_<ts>.json`); `off_thread=False` = wszystkie workery inline (seam
    testowy, sygnały direct = synchronicznie)."""

    def __init__(self, con, *, now_fn, archive_root, work_root=None, release_roots=(),
                 off_thread=True, parent=None):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)
        self._now = now_fn
        root = str(archive_root or "").strip()
        self._archive_root = os.path.normpath(root) if root else ""
        work = str(work_root or "").strip()
        self._work_root = os.path.normpath(work) if work else ""
        self._rel_roots = release_roots_of(self._work_root, release_roots)
        # Archiwum, które zna baza - JEDNO zapytanie przy otwarciu (tanie SQL, inline). Inne
        # archiwum w oknie to częsty błąd ręki (kopia archiwum w scratchu, stara karta): okno mówi
        # to przy wierszu „Archiwum”, zanim cokolwiek zostanie skopiowane.
        self._db_archive = harvest.archive_root_from_db(con)
        self._off_thread = off_thread
        self._gen = 0                    # licznik generacji DRY - wynik starszej sondy odpada
        self._dry_thread = None
        self._dry_worker = None
        self._dry_pending = False        # wynik stale przyszedł za żywym workerem → świeża sonda po sprzątnięciu
        self._requested = None           # (wyjście, archiwum) ostatniej zleconej sondy
        self._probed = None              # wyjście, którego podgląd stoi w tabeli (None = tabela pusta)
        self._plan = None                # plan ZAAKCEPTOWANEJ (bieżąca generacja) sondy
        self._outcome = None             # słowo skutku ostatniego biegu na przycisku „Wciągnij”
        self._apply_thread = None
        self._apply_worker = None
        self._apply_seen = (0, 0)        # ostatni postęp - zdanie błędu mówi, ile przetworzono
        self._run_status = {}            # dst → status z postępu BIEŻĄCEGO biegu
        self._run_items = {}             # dst → pozycja planu BIEŻĄCEGO biegu (stos niesie wejścia)
        self._placed_dirs = set()        # katalogi z ≥1 wciągniętą kopią, ze wszystkich biegów okna
        self._placed_keys = set()        # `norm_path` celów wciągniętych kopii - wszystkie biegi okna
        self._placed_n = 0               # ile plików wciągnęły wszystkie biegi okna (z postępu)
        self._placed_stacks = {}         # sha1_data → (frame_ids, kanon wydania) stosów wciągniętych w tym oknie
        # Cztery fakty o BIEŻĄCYM archiwum okna - zeruje je zmiana archiwum (`_set_archive`, AR-107).
        self._unknown = {}               # `norm_path` → ścieżka kopii w archiwum, której baza nie zna
        self._unknown_stacks = {}        # sha1_data → (frame_ids, kanon) stosów w archiwum bez wiedzy bazy
        self._lineage = {}               # `norm_path` → kopia stosu pod STACKS bez rodowodu dokładnego (lista)
        self._lineage_stacks = {}        # sha1_data → (frame_ids, kanon) tych stosów (z zeznania żniw, AR-104)
        self._fresh = {}                 # `norm_path(out)` → `plan_counts` ostatniego podglądu tego wyjścia
        # `norm_path(out)` → `SondaNiepelna`: ostatni podgląd tego wyjścia nie przeczytał go całego albo
        # padł (AR-222) - blokada „wciągnięte” do pełnego podglądu tego `out`; zmiana archiwum jej nie zdejmuje
        self._sonda_niepelna = {}
        self._trouble = Counter()        # konflikty, błędy, niezgodne bajty - wszystkie biegi okna
        self._ran = False                # okno puściło choć jeden bieg apply
        self._last_counts = Counter()    # statusy ostatniego biegu (zdanie „nic nie wciągnięto”)
        self._last_cancelled = 0         # nietknięte w ostatnim, przerwanym biegu
        self._last_error = None          # wyjątek rdzenia ostatniego biegu
        self._last_manifest = None       # niezapisane zeznanie ostatniego biegu (zdanie)
        self._szczegoly_biegu = ""       # szczegół systemu obu - podpowiedź zdania paska (AR-218)
        self._close_after_apply = None   # kod zamknięcia zgłoszonego w biegu apply
        self._closing = False
        self._zwolnione = False          # `deleteLater` po zamknięciu już zlecone (`_zwolnij_gdy_wolne`)
        self._notice_state = ("", None, "")  # ostatni komunikat stanu (tekst, rola, podpowiedź) - wraca, gdy pole przestaje odbiegać
        self.summary = None              # zdanie na pasek stanu gospodarza (None = nic się nie stało)
        self.harvested_root = None       # korzeń do przyjęcia - ustawia go WYŁĄCZNIE „Zamknij i przyjmij”
        self.harvested_stacks = []       # [(sha1_data, frame_ids, kanon wydania)] - razem z `harvested_root`
        self._shown_out = None           # wyjście WBPP pozycji w tabeli - kolumna pliku liczy się względem niego
        self._table_viewport = None      # viewport tabeli po budowie (filtr zdarzeń zmiany rozmiaru)
        self._rel_viewport = None        # viewport listy wydań po budowie (szerokość kolumny „Karta”)
        self._first_pick_checked = False  # pierwsze użycie: wybór katalogu raz po pokazaniu (`showEvent`)
        self._rozmieszczone = False      # okno ma już własne miejsce na ekranie (po pierwszym `QDialog.showEvent`, `_ekran`)
        self._podstawy_zdan = {}         # etykieta zdania nad polem → minimum wysokości sprzed zapadki (`_zwolnij_zapadke`)
        self._rel_gen = 0                # licznik generacji listy wydań - lista starszego zamówienia odpada
        self._rel_thread = None
        self._rel_worker = None
        self._rel_pending = False        # zamówienie przyszło w biegu listy → świeża lista po sprzątnięciu
        self._rel_started = False        # pierwsza lista przyszła (wybór startowy zrobiony albo oddany polu)
        self._releases = []              # wiersze listy wydań w kolejności tabeli
        self._rel_missing = ()           # `(karta, powód)` kart bez folderu albo nieczytelnych (AR-147, AR-222)
        self.setWindowTitle(i18n.t("harvest.title"))
        self.setModal(True)
        self.resize(980, 600)
        self._build_ui()
        self._sync_buttons()             # waga przycisków od pierwszej klatki - ze stanu, nie z budowy
        self._show_archive()
        self.edit_output.setText(str(self._settings().value("harvest/last_output", "") or ""))
        if self._rel_roots:
            # Karty są: auto-DRY rusza dopiero z pierwszą listą (najnowsze wydanie z robotą albo
            # pamięć pola) - inaczej sonda pamięci czytałaby mastery, które lista zaraz unieważni.
            self._show_rel_notice(i18n.t("harvest.rel.probing"))
            self._trigger_releases()
        else:
            self._show_rel_notice(i18n.t("harvest.rel.no_sources"))
            self._on_output_edited()     # otwarcie z pamięci = zdarzenie dyskretne → auto-DRY

    # ---- budowa ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        self.hint_label = QLabel(i18n.t("harvest.hint"))
        self.hint_label.setProperty("role", "secondary")
        self.hint_label.setWordWrap(True)
        v.addWidget(self.hint_label)

        # Lista wydań z kart. Zdanie nad nią: brak kart, liczenie, pusta lista, błąd listy. Z kartami
        # miejsce listy stoi od startu (widoczne zdanie, także puste, pusta tabela, zarezerwowany wiersz
        # „wciągnięte”): lista, która dochodzi z tła, nie spycha pola i przycisków pod kursorem - klik
        # w „Wskaż…” trafiałby w wiersz listy. Puste zdanie trzyma wysokość wiersza samo (etykieta
        # zaznaczalna liczy ją z dokumentu, zmierzone: z minimum 0 układ identyczny) - minimum niżej to
        # tylko podłoga wysokości, liczona fontem z konstrukcji.
        reserve = bool(self._rel_roots)
        self.rel_notice = EtykietaBledu("")          # zdanie + szczegół systemu (AR-204)
        self.rel_notice.setWordWrap(True)
        self.rel_notice.setMinimumHeight(self.rel_notice.fontMetrics().lineSpacing())   # podłoga wysokości
        _szerokosc_od_okna(self.rel_notice)          # błąd listy niesie ścieżkę karty
        self.rel_notice.setVisible(False)
        v.addWidget(self.rel_notice)
        self.rel_table = QTableWidget(0, len(_REL_HEADERS))
        self.rel_table.setHorizontalHeaderLabels([i18n.t(k) for k in _REL_HEADERS])
        self.rel_table.verticalHeader().setVisible(False)
        self.rel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rel_table.setWordWrap(False)
        # Karta bywa długą ścieżką (folder roboczy pod profilem użytkownika, karta na udziale): liczona
        # za treścią rozpychała tabelę w bok i ucinała komórkę „Stan” - jedyną, która mówi, co z wydaniem
        # zrobić. Karta jest więc elidowana ŚRODKIEM (dysk i `_WBPP` na końcu zostają, pełna ścieżka pod
        # kursorem), a jej szerokość liczy `_fit_rel_columns` z reszty po obiekcie, dacie i stanie.
        self.rel_table.setTextElideMode(Qt.ElideMiddle)
        rh = self.rel_table.horizontalHeader()
        rh.setSectionResizeMode(QHeaderView.ResizeToContents)
        rh.setSectionResizeMode(REL_CARD, QHeaderView.Interactive)
        rh.setStretchLastSection(True)
        # Wysokość STAŁA (AR-201), nie tylko sufit: lista stoi NAD polem, a układ ściskał ją pod przyrost
        # zdań spod pola (okno ściśnięte ręką: 56 → 48 px natywnie) - pole, „Wskaż…” i „Zmień…”
        # podjeżdżały o tyle pod kursorem. Brakującą wysokość daje teraz okno (`_podloga_wysokosci`).
        self.rel_table.setFixedHeight(
            rh.sizeHint().height() + _REL_VISIBLE_ROWS * self.rel_table.verticalHeader().defaultSectionSize()
            + 2 * self.rel_table.frameWidth())
        self.rel_table.itemSelectionChanged.connect(self._on_release_selected)
        self.rel_table.setVisible(reserve)
        v.addWidget(self.rel_table)
        # Wiersz zaznaczonego wydania bez niczego do wciągnięcia: zdanie (folder można skasować albo
        # najpierw przegląd albo rodowód) i „Otwórz” - bez kasowania. Zarezerwowany wiersz trzyma
        # wysokość NAJWYŻSZEGO z trzech zdań (`_ZdanieZRezerwa`, AR-225) - zdanie, które lista z tła
        # pokaże, nie przesuwa pola pod nim.
        row_d = QHBoxLayout()
        self.rel_done_note = _ZdanieZRezerwa(("harvest.rel.done_note", "harvest.rel.review_note",
                                              "harvest.rel.lineage_note"))
        self.rel_done_note.setProperty("role", "secondary")
        row_d.addWidget(self.rel_done_note, 1)
        self.btn_open_release = QPushButton(i18n.t("harvest.rel.btn_open"))
        self.btn_open_release.setAutoDefault(False)
        self.btn_open_release.clicked.connect(self._on_open_release)
        row_d.addWidget(self.btn_open_release, 0, Qt.AlignTop)     # przy zdaniu, nie w środku wyższego wiersza
        v.addLayout(row_d)
        for w in (self.rel_done_note, self.btn_open_release):
            if reserve:
                sp = w.sizePolicy()
                sp.setRetainSizeWhenHidden(True)
                w.setSizePolicy(sp)
            w.setVisible(False)

        row_o = QHBoxLayout()
        row_o.addWidget(QLabel(i18n.t("harvest.output_label")))
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText(i18n.t("harvest.output_placeholder"))
        self.edit_output.setClearButtonEnabled(True)
        self.edit_output.editingFinished.connect(self._on_output_edited)
        self.edit_output.textChanged.connect(self._sync_stale)
        self.edit_output.installEventFilter(self)    # Enter = potwierdź ścieżkę, nie „Wciągnij” (`eventFilter`)
        row_o.addWidget(self.edit_output, 1)
        self.btn_pick = QPushButton(i18n.t("harvest.btn_pick"))
        self.btn_pick.setAutoDefault(False)
        self.btn_pick.clicked.connect(self._on_pick_output)
        row_o.addWidget(self.btn_pick)
        v.addLayout(row_o)

        row_a = QHBoxLayout()
        self.archive_label = QLabel("")
        row_a.addWidget(self.archive_label, 1)
        self.btn_archive = QPushButton(i18n.t("harvest.btn_archive"))
        self.btn_archive.setAutoDefault(False)
        self.btn_archive.clicked.connect(self._on_pick_archive)
        row_a.addWidget(self.btn_archive)
        v.addLayout(row_a)
        row_w = QHBoxLayout()
        self.archive_warn = EtykietaBledu("")        # archiwum okna ≠ archiwum bazy (`_show_archive`)
        self.archive_warn.setProperty("role", "warn")
        self.archive_warn.setWordWrap(True)
        _szerokosc_od_okna(self.archive_warn)        # ostrzeżenie niesie ścieżki obu archiwów
        self.archive_warn.setVisible(False)
        row_w.addWidget(self.archive_warn, 1)
        # Powrót jednym klikiem (AR-107): ostrzeżenie mówi, że pliki trafią gdzie indziej, więc droga
        # do archiwum bazy stoi obok niego, a nie za oknem wyboru katalogu. Blokada jak „Zmień…”.
        self.btn_archive_back = QPushButton(i18n.t("harvest.btn_archive_back"))
        self.btn_archive_back.setAutoDefault(False)
        self.btn_archive_back.clicked.connect(self._on_archive_back)
        self.btn_archive_back.setVisible(False)
        row_w.addWidget(self.btn_archive_back, 0, Qt.AlignTop)
        v.addLayout(row_w)

        self.head_label = QLabel("")
        _fh = self.head_label.font(); _fh.setBold(True); self.head_label.setFont(_fh)
        # Zdanie liczb (z dopiskami kłopotów i przerwania) zawija się na „ · ” jak nagłówek okna wydania,
        # zamiast dyktować minimum szerokości okna (AR-201: najdłuższe 1287 px przy foncie ×1,6). Zawijanie,
        # nie elizja - elizja zjadłaby końcowe „konflikty”, „błędy” i „przerwano”.
        self.head_label.setWordWrap(True)
        v.addWidget(self.head_label)
        # Stan okna jednym zdaniem: sonda w biegu, brak wyjścia, pusty katalog, błąd, bieg apply.
        self.notice = EtykietaBledu("")              # zdanie + szczegół systemu (AR-204)
        self.notice.setWordWrap(True)
        _szerokosc_od_okna(self.notice)              # podgląd z tła niesie ścieżkę wydania (zaznaczalna)
        v.addWidget(self.notice)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels([i18n.t(k) for k in _HEADERS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Szerokości liczy `_fit_columns` (przy każdym wypełnieniu i zmianie rozmiaru), nie tryb
        # nagłówka: `Stretch` daje powodowi wyłącznie resztkę po pozostałych kolumnach, a przy
        # dwóch długich ścieżkach resztką jest minimum sekcji - powód znikał za prawą krawędzią.
        # Bez zawijania: długi powód elidowany na końcu, pełna treść pod kursorem.
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        self._table_viewport = self.table.viewport()
        self._table_viewport.installEventFilter(self)    # zmiana szerokości okna → `_fit_columns`
        # Filtr listy wydań dopiero tu, gdy pole wyjścia już stoi (`eventFilter` pyta o nie najpierw).
        self._rel_viewport = self.rel_table.viewport()
        self._rel_viewport.installEventFilter(self)      # zmiana szerokości okna → `_fit_rel_columns`
        v.addWidget(self.table, 1)

        act = QHBoxLayout()
        # Pasek BEZ napisu: licznik biegu mówi notatka obok („3/12 · plik”) - procent na pasku
        # powtarzał tę samą liczbę drugim zapisem („0%” obok „0/1”).
        self.busy = QProgressBar()       # DRY = nieokreślony (`_set_probing`), apply = `done/total`
        self.busy.setRange(0, 0)
        self.busy.setMinimumWidth(220)
        self.busy.setTextVisible(False)
        self.busy.setVisible(False)
        act.addWidget(self.busy)
        # Notatka elidowana od prawej, pełna treść pod kursorem: nazwa stosu WBPP ma do ~100 znaków
        # (zmierzone na kopii archiwum: 97), a etykieta za treścią rozpychała okno w bok. Licznik stoi
        # na początku, więc elizja go nie zjada. Notatka bierze wolne miejsce wiersza (w miejscu
        # dawnego rozpychacza), przyciski zostają przy prawej krawędzi.
        self.progress_note = ElidedLabel()
        self.progress_note.setProperty("role", "secondary")
        act.addWidget(self.progress_note, 1)
        self.btn_apply = QPushButton(i18n.t_plural("harvest.btn_apply", 0))
        self.btn_apply.setEnabled(False)             # uzbraja WYŁĄCZNIE świeża sonda z czymś do wciągnięcia
        # Waga (bold, wysokość, Enter) - wyłącznie `_sync_buttons`, ze stanu okna (AR-262).
        self.btn_apply.clicked.connect(self._on_apply)
        act.addWidget(self.btn_apply)
        self.btn_cancel = QPushButton(i18n.t("harvest.btn_cancel_apply"))
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setVisible(False)            # wchodzi W MIEJSCE „Wciągnij” na czas biegu
        self.btn_cancel.clicked.connect(self._on_cancel_apply)
        act.addWidget(self.btn_cancel)
        # Przyjęcie NIE jest domyślne ani autodomyślne: Enter (w polu, w tabeli) nigdy nie zamyka
        # okna z uruchomieniem łańcucha Dostawy.
        self.btn_accept = QPushButton(i18n.t("harvest.btn_accept"))
        self.btn_accept.setAutoDefault(False)
        self.btn_accept.setVisible(False)
        self.btn_accept.clicked.connect(self._on_accept)
        act.addWidget(self.btn_accept)
        self.btn_close = QPushButton(i18n.t("harvest.btn_close"))
        self.btn_close.setAutoDefault(False)
        self.btn_close.clicked.connect(self.reject)
        act.addWidget(self.btn_close)
        v.addLayout(act)

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _show_archive(self):
        """Wiersz archiwum i ostrzeżenie pod nim: archiwum okna inne niż archiwum bazy (porównanie
        bez wielkości liter, po normalizacji). Baza bez archiwum (`None`) - nie ma z czym
        porównać, więc okno milczy."""
        if self._archive_root:
            self.archive_label.setText(i18n.t("harvest.archive_label",
                                              root=_elide_path(self._archive_root)))
            self.archive_label.setToolTip(self._archive_root)
        else:
            self.archive_label.setText(i18n.t("harvest.archive_unset"))
            self.archive_label.setToolTip("")
        differs = self._archive_differs()
        self.archive_warn.ustaw(i18n.t("harvest.archive_differs", db=self._db_archive)
                                if differs else "")
        self.archive_warn.setVisible(differs)
        self.btn_archive_back.setVisible(differs)

    def _archive_differs(self):
        """Archiwum okna inne niż archiwum, które zna baza (bez archiwum bazy - nie ma z czym porównać)."""
        return bool(self._archive_root and self._db_archive
                    and norm_path(self._archive_root) != norm_path(self._db_archive))

    def eventFilter(self, obj, event):
        """Enter w polu wyjścia potwierdza ścieżkę (świeża sonda) i ZOSTAJE w polu. Bez tego
        klawisz szedłby dalej do domyślnego „Wciągnij” - nowa ścieżka z Enterem ruszyłaby kopię
        według planu, którego user jeszcze nie widział (inline nawet według świeżego)."""
        if (obj is self.edit_output and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            self._on_output_edited(force=True)
            return True
        if obj is self._table_viewport and event.type() == QEvent.Resize:
            self._fit_columns()
        if obj is self._rel_viewport and event.type() == QEvent.Resize:
            self._fit_rel_columns()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """Pierwsze użycie (brak `harvest/last_output`) BEZ kart: od razu okno wyboru katalogu
        wyjścia, jak kafel Przyjmij przy pierwszej dostawie - puste pole i zdanie „Wskaż…” to jedna
        interakcja więcej do tego samego miejsca. Z kartami wyborem jest lista wydań, więc okno
        wyboru nie wyskakuje nad nią. Raz na okno, po pokazaniu (kolejka zdarzeń), żeby wybór
        stał nad oknem żniw, a nie przed nim; anulowanie zostawia okno z pustym polem.
        Pierwsze pokazanie dopasowuje też wysokość (`_fit_height`) - przed `QDialog.showEvent`,
        które ustawia pozycję okna pod jego rozmiar - a po nim stawia podłogę wysokości
        (`_podloga_wysokosci`), bez czekania na pierwszy `LayoutRequest`."""
        first = not self._first_pick_checked
        if first:
            self._first_pick_checked = True
            self._fit_height()
        super().showEvent(event)
        if first:
            self._rozmieszczone = True               # od teraz ekran = ten, na którym okno stoi (`_ekran`)
            self._podloga_wysokosci()
        if first and not self._rel_roots and not str(self._settings().value("harvest/last_output", "") or ""):
            QTimer.singleShot(0, self._on_pick_output)

    def _fit_height(self):
        """Wysokość okna pod treść (AR-191): `heightForWidth` układu przy szerokości, którą okno już
        ma, najwyżej `_SCREEN_SHARE` wysokości ekranu; okno tylko rośnie ponad startowe 600 px. Stałe
        600 px nie zna fontu: przy foncie ×1,6 treść chce 694-760 px (offscreen), okno startowało
        ściśnięte z tabelą pozycji na minimum, a wiersz, który zdanie podglądu z tła dokłada pod
        polem, schodził wtedy z listy wydań NAD nim - pole, „Wskaż…” i „Zmień…” podjeżdżały o
        13-19 px. W wysokości treści tabela pozycji stoi na swoim sizeHint i to jej zapas bierze
        przyrost zdania."""
        want = self.layout().totalHeightForWidth(self.width())
        sufit = self._sufit_wysokosci()
        if sufit is not None:
            want = min(want, sufit)
        if want > self.height():
            self.resize(self.width(), want)

    def _sufit_wysokosci(self):
        """`_SCREEN_SHARE` dostępnej wysokości ekranu okna albo None (okno bez ekranu)."""
        screen = self._ekran()
        return int(screen.availableGeometry().height() * _SCREEN_SHARE) if screen is not None else None

    def _podloga_wysokosci(self):
        """Minimum wysokości okna = minimum treści przy BIEŻĄCEJ szerokości (`totalMinimumHeightForWidth`,
        AR-201), najwyżej `_sufit_wysokosci` - okno nie wymusza wysokości większej niż ekran, pod którą
        dolny rząd przycisków wyszedłby poza niego. Qt liczy minimum okna bez zawijania zdań: okno
        ściśnięte ręką do minimum przed dojściem listy stało niżej od treści, a wiersz, który zdanie
        podglądu z tła dokłada pod polem, układ zabierał liście wydań NAD nim - pole, „Wskaż…”
        i „Zmień…” podjeżdżały pod kursorem (natywnie -8 px przy foncie ×1, -26 px przy ×1,6). Z podłogą
        okno rośnie od dołu: w oknie ściśniętym dolny rząd zjeżdża o przyrost zdania - przycisk, który
        w tej chwili dopiero się uzbraja, nie pole, w które człowiek właśnie celuje. Okno postawione
        przy dolnej krawędzi ekranu podnosi się o tyle, ile wystaje (`_rama_w_obszarze_ekranu`) - dolny
        rząd przycisków nie schodzi pod ekran. Niepokazane okno (testy inline) nie dostaje podłogi -
        wysokość stawia mu pierwsze pokazanie. Guard równości zamyka pętlę `LayoutRequest` (wzorzec
        `grid_selection`)."""
        if not self.isVisible():
            return
        want = self.layout().totalMinimumHeightForWidth(self.width())
        sufit = self._sufit_wysokosci()
        if sufit is not None:
            want = min(want, sufit)
        if want != self.minimumHeight():
            wysokosc = self.height()
            self.setMinimumHeight(want)
            if self.height() > wysokosc:
                self._rama_w_obszarze_ekranu()

    def _rama_w_obszarze_ekranu(self):
        """Okno, które urosło od dołu z podłogi wysokości, podnosi się o tyle, ile jego ramka wystaje pod
        dolną krawędź obszaru roboczego swojego ekranu (`_ekran`), nie wyżej niż jego górna krawędź.
        Zmaksymalizowanego nie rusza - jego geometrię trzyma system."""
        screen = self._ekran()
        if screen is None or self.isMaximized():
            return
        obszar = screen.availableGeometry()
        nadmiar = self.frameGeometry().bottom() - obszar.bottom()
        if nadmiar > 0:
            self.move(self.x(), max(obszar.top(), self.y() - nadmiar))

    def event(self, e):
        # Treść zmienia wysokość przy każdym zdaniu z tła - podłoga idzie za nią (`_podloga_wysokosci`);
        # zdanie, które zniknęło, oddaje zapadkę (`_zwolnij_zapadke`), zanim podłoga się przeliczy.
        wynik = super().event(e)
        if e.type() == QEvent.LayoutRequest:
            self._zwolnij_zapadke(tylko_puste=True)
            self._podloga_wysokosci()
        return wynik

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._podloga_wysokosci()                 # węższe okno łamie zdania na więcej wierszy

    def _ekran(self):
        """Ekran okna. Przed pierwszym rozmieszczeniem - ten, na którym okno STANIE: rodzica
        (`QDialog.showEvent` centruje okno na nim), a bez rodzica - własny; `self.screen()` niepokazanego
        okna z rodzicem na drugim monitorze to ekran główny, więc sufit startowy liczyłby się z innego
        ekranu. Po rozmieszczeniu - ten, na którym okno STOI (`self.screen()`): okno przeniesione ręką na
        inny monitor niż rodzic rośnie w lewo do krawędzi SWOJEGO ekranu (AR-201), a nie ekranu rodzica."""
        return self.screen() if self._rozmieszczone else (self.parentWidget() or self).screen()

    # ---- szerokości (powód w kadrze, ścieżki odróżnialne) ----
    def _fit_columns(self):
        """Szerokości kolumn: wszystkie poza powodem za treścią; powód dostaje resztę viewportu
        (rozciąga się, gdy jest miejsce), a gdy reszty brakuje - swoją treść, przycięte tak, by
        razem z kolumnami przed nim mieścił się w kadrze. Kolumny ścieżek na prawo wtedy przewijają
        się w bok, powód nie (zrzut wizytatora: suma 1827 px przy viewporcie 956 px chowała go za
        krawędzią)."""
        if self._table_viewport is None:
            return
        hh = self.table.horizontalHeader()
        for c in range(len(_HEADERS)):
            if c != COL_REASON:
                self.table.resizeColumnToContents(c)
        vw = self.table.viewport().width()
        others = sum(self.table.columnWidth(c) for c in range(len(_HEADERS)) if c != COL_REASON)
        left = sum(self.table.columnWidth(c) for c in range(COL_REASON))
        want = max(self.table.sizeHintForColumn(COL_REASON), hh.sectionSizeHint(COL_REASON))
        width = max(vw - others, min(want, vw - left), hh.minimumSectionSize())
        if self.table.columnWidth(COL_REASON) != width:
            hh.resizeSection(COL_REASON, width)

    def _fit_rel_columns(self):
        """Szerokość kolumny „Karta” listy wydań: jej treść, gdy wiersz mieści się w kadrze, a gdy
        nie - reszta viewportu po obiekcie, dacie i stanie liczonych w pełnej treści (nie mniej niż
        minimum sekcji; elizja środkiem robi resztę). Stan stoi ostatni i rozciąga się na resztę, więc
        zostaje cały zawsze, gdy w kadrze mieści się karta o minimalnej szerokości. Rozciągana sekcja
        ostatnia nie schodzi poniżej domyślnej szerokości sekcji (zmierzone natywnie: 100 px przy treści
        95) - liczona samą treścią dawała sumę o 5 px szerszą od kadru i pasek przewijania w bok."""
        if self._rel_viewport is None:
            return
        rh = self.rel_table.horizontalHeader()
        tresc = {c: max(self.rel_table.sizeHintForColumn(c), rh.sectionSizeHint(c))
                 for c in range(len(_REL_HEADERS))}
        tresc[REL_STATE] = max(tresc[REL_STATE], rh.defaultSectionSize())
        inne = sum(w for c, w in tresc.items() if c != REL_CARD)
        width = max(min(tresc[REL_CARD], self.rel_table.viewport().width() - inne),
                    rh.minimumSectionSize())
        if self.rel_table.columnWidth(REL_CARD) != width:
            rh.resizeSection(REL_CARD, width)

    def _grow_to_table(self):
        """Szerokość okna pod treść tabeli: suma kolumn (powód w pełnej treści) + ramy, najwyżej
        90% dostępnej szerokości ekranu. Okno tylko ROŚNIE - nie zabiera szerokości, którą user mu
        dał - i nie schodzi poniżej szerokości startowej.

        Pokazane okno rośnie W LEWO (AR-201): wzrost przychodzi z tła (podgląd, wynik biegu), a każdy
        przycisk wierszy nad tabelą i pod nią („Wskaż…”, „Zmień…”, „Wciągnij”, „Zamknij”) stoi przy
        prawej krawędzi - okno rosnące w prawo przenosiło je spod kursora o +100 px (font ×1) i +675 px
        (×1,6), natywnie. Lewa krawędź ekranu okna (`_ekran`) zatrzymuje wzrost w lewo, resztę bierze
        prawa strona; okno już za lewą krawędzią nie skacze w prawo, okno zmaksymalizowane się nie
        rusza. Przed wzrostem zdania nad polem dostają zapadkę wysokości (`_zapadka_zdan_nad_polem`)."""
        if self.table.rowCount() == 0:
            return
        hh = self.table.horizontalHeader()
        total = sum(max(self.table.sizeHintForColumn(c), hh.sectionSizeHint(c))
                    for c in range(len(_HEADERS)))
        m = self.layout().contentsMargins()
        overhead = (m.left() + m.right() + 2 * self.table.frameWidth()
                    + self.table.verticalScrollBar().sizeHint().width())
        screen = self._ekran()
        cap = int(screen.availableGeometry().width() * _SCREEN_SHARE) if screen is not None else total + overhead
        target = min(total + overhead, cap)
        if target > self.width() and not self.isMaximized():
            self._zapadka_zdan_nad_polem()
            g = self.geometry()
            if self.isVisible() and screen is not None:
                # Lewa krawędź obszaru klienta: krawędź ekranu + ramka okna (geometria bez ramki).
                lewo = screen.availableGeometry().left() + (g.x() - self.frameGeometry().x())
                x = min(g.x(), max(lewo, g.x() - (target - g.width())))
                self.setGeometry(x, g.y(), target, g.height())
            else:
                self.resize(target, self.height())
        self._fit_columns()

    def _zapadka_zdan_nad_polem(self):
        """Zdania nad polem (wskazówka, zdanie listy wydań, zarezerwowane zdanie wiersza wydania) nie
        maleją, gdy okno poszerza się pod tabelę z tła (AR-201): szersze okno łamie je na mniej
        wierszy, a wysokość, którą oddawały, podnosiła pole, „Wskaż…” i „Zmień…” pod kursorem -
        natywnie przy foncie ×1,6 o 44 px (980 → 1655 px: wskazówka 78 → 52, zdanie wiersza 52 → 34).
        Minimum każdego = jego bieżąca wysokość, tekst u góry etykiety (wolne miejsce pod nim, nie nad);
        zwężenie okna ręką dalej je podnosi - minimum to podłoga. Zapadka trzyma tylko do zmiany stanu
        (`_zwolnij_zapadke`). Niepokazane okno nie ma jeszcze wysokości z układu (`height()` niepołożonej
        etykiety to domyślne 30 px) - wtedy nic; tak samo etykieta ukryta bez zarezerwowanego miejsca."""
        if not self.isVisible():
            return
        for lab in (self.hint_label, self.rel_notice, self.rel_done_note):
            if lab.isVisibleTo(self) or lab.sizePolicy().retainSizeWhenHidden():
                self._podstawy_zdan.setdefault(lab, lab.minimumHeight())
                lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                lab.setMinimumHeight(max(lab.minimumHeight(), lab.height()))

    def _zwolnij_zapadke(self, *, tylko_puste=False):
        """Minimum zdań nad polem wraca do wartości sprzed zapadki (`_podstawy_zdan`): na początku
        NOWEGO podglądu (`_invalidate` - nowe wyjście, wiersz listy, zmiana archiwum) i - z
        `tylko_puste` - dla zdania, które zniknęło (`LayoutRequest`). Bez tego zapadka trzymała
        największą wysokość z życia okna: puste zdanie listy po zniknięciu ostrzeżenia dalej zajmowało
        jego wiersze, a cykle zwężenie → wynik z tła zatrzaskiwały minimum coraz wyżej. Pole może wtedy
        podjechać - to zmiana stanu (gest człowieka albo koniec zdania), nie przyrost z tła."""
        for lab, podstawa in self._podstawy_zdan.items():
            if (not tylko_puste or not lab.text()) and lab.minimumHeight() != podstawa:
                lab.setMinimumHeight(podstawa)

    # ---- parametry ----
    def _pick_start(self):
        """Katalog startowy „Wskaż…”: `<folder roboczy>\\OBJECTS`, gdy istnieje - tam leżą wyjścia
        wszystkich wydań; inaczej ostatnie wyjście z pola, a bez niego archiwum. Jedno `isdir` tuż
        przed oknem wyboru, które i tak czyta ten katalog w wątku GUI - nic nie zakłada."""
        if self._work_root:
            objects = os.path.join(self._work_root, projection.OBJECT_NAMESPACE)
            if os.path.isdir(objects):
                return objects
        return clean_path(self.edit_output.text()) or self._archive_root

    def _on_pick_output(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("harvest.dlg.pick_output"), self._pick_start())
        if path:
            self._set_output(path)

    def _set_output(self, path):
        """Ustaw pole wyjścia i sonduj - także tę samą ścieżkę co przed chwilą: wskazanie to jawna
        prośba o podgląd (seam testowy - bez `QFileDialog`)."""
        self.edit_output.setText(os.path.normpath(path))
        self._on_output_edited(force=True)

    def _on_pick_archive(self):
        """„Zmień…” archiwum. Okno wyboru kręci WŁASNĄ pętlę zdarzeń, a w niej może dobiec podgląd
        z kopiami zastanymi w archiwum (AR-100) - te archiwum już nie zamrażają (AR-107), więc
        wynik z pętli niczego tu nie blokuje. Blokadę niesie wyłącznie kopia wciągnięta w tym oknie,
        a bieg, który ją kładzie, trzyma „Zmień…” wygaszone do swojego końca i nie rusza przy
        otwartym (modalnym) oknie wyboru - strażnikiem obejścia jest asercja `_set_archive`."""
        path = QFileDialog.getExistingDirectory(self, i18n.t("harvest.dlg.pick_archive"),
                                                self._archive_root)
        if path:
            self._set_archive(path)

    def _on_archive_back(self):
        """„Wróć do archiwum bazy” przy ostrzeżeniu o innym archiwum (AR-107) - ta sama zmiana
        archiwum co „Zmień…”, z celem z bazy zamiast z okna wyboru."""
        self._set_archive(self._db_archive)

    def _set_archive(self, path):
        """Zmiana archiwum TYLKO dla tego okna: źródło Dostawy (`pipeline/last_source`) należy do
        strony Dostawy, a okno żniw nie przestawia jej po cichu następnej dostawy. Po pierwszej
        kopii wciągniętej w tym oknie archiwum jest zamrożone (`_sync_buttons`) - EXPECT, gdy ktoś
        obejdzie wygaszony przycisk. Seam testowy.

        Kopie zastane bez wiedzy bazy i stosy bez rodowodu dokładnego to fakty o archiwum, które
        okno właśnie opuszcza (AR-107): zerowane tu, liczy je od nowa sonda (`_on_dry_done`) i lista
        (`_take_lineage`) wobec nowego archiwum. Bez tego wróciłyby do korzenia przyjęcia spoza
        bibliotek archiwum okna (odmowa `_receivable_root`) albo trzymały przycisk przyjęcia."""
        assert not self._placed_dirs, "archiwum zamrożone od pierwszej kopii wciągniętej w tym oknie"
        self._archive_root = os.path.normpath(path)
        self._unknown.clear()
        self._unknown_stacks.clear()
        self._lineage.clear()
        self._lineage_stacks.clear()
        self._refresh_summary()
        self._sync_buttons()                         # przyjęcie gaśnie, zanim sonda i lista powiedzą swoje
        self._show_archive()
        self._fresh.clear()                          # podglądy wierszy liczone wobec poprzedniego archiwum
        self._trigger_releases()                     # stan listy zależy od archiwum (AR-105)
        self._on_output_edited()

    def _on_output_edited(self, *, force=False):
        """Zdarzenie dyskretne pola (otwarcie, Enter, wyjście z pola, „Wskaż…”, zmiana archiwum).
        Cudzysłowy z wklejonej ścieżki znikają tu, zanim cokolwiek ją sonduje. Bez `force` te same
        parametry co ostatnia zlecona sonda → nic: wyjście z pola klikiem w „Wciągnij” emituje
        `editingFinished`, a unieważnienie w tym momencie zgasiłoby przycisk pod kursorem
        i wyzerowało plan, który klik właśnie wydaje; po biegu zmazałoby tabelę wyniku. `force`
        (Enter, „Wskaż…”) to jawna prośba o świeży podgląd tej samej ścieżki."""
        if self._apply_worker is not None:
            return                                   # parametry zamrożone w biegu (pole i tak wygaszone)
        path = clean_path(self.edit_output.text())
        if path != self.edit_output.text():
            self.edit_output.setText(path)
        key = (path, self._archive_root)
        if key == self._requested and not force:
            return
        self._requested = key
        self._select_release_for(path)               # zaznaczenie listy idzie za polem, nie odwrotnie
        self._invalidate()
        self._trigger_dry()

    def _invalidate(self):
        """Nowe parametry unieważniają podgląd: generacja ++, plan, tabela i słowo skutku znikają,
        a zdania nad polem oddają zapadkę wysokości z poprzedniego podglądu (`_zwolnij_zapadke`)."""
        self._zwolnij_zapadke()
        self._gen += 1
        self._plan = None
        self._probed = None
        self._outcome = None
        self.table.setRowCount(0)
        self.table.setEnabled(True)
        self.head_label.setText("")
        self._sync_buttons()

    def _is_stale(self):
        """Tekst pola odbiega od wyjścia, którego podgląd stoi w tabeli."""
        return self._probed is not None and clean_path(self.edit_output.text()) != self._probed

    def _sync_stale(self, *_):
        """Pole odbiega od podglądu → tabela wyszarzona i zdanie, dla czego jest podgląd (Enter
        liczy nowy); pole wraca do podglądu → poprzedni komunikat wraca."""
        stale = self._is_stale()
        self.table.setEnabled(not stale)
        if stale:
            self._show_notice(i18n.t("harvest.stale", path=self._probed), remember=False)
        else:
            self._show_notice(*self._notice_state, remember=False)
        self._sync_buttons()

    def _sync_buttons(self):
        """Stan obu przycisków z faktów okna - jedyne miejsce, które je ustawia (poza wejściem
        i wyjściem z biegu). „Wciągnij N”: świeży plan bieżących parametrów z czymś do wciągnięcia,
        pole zgodne z podglądem, nic w biegu; po biegu nazywa jego skutek. „Zamknij i przyjmij”:
        od pierwszej rzeczy do przyjęcia (`_receivable_dirs` - kopia wciągnięta albo zastana w archiwum
        bez wiedzy bazy, stos bez rodowodu dokładnego z listy). Archiwum zamrożone WYŁĄCZNIE od
        pierwszej kopii wciągniętej w tym oknie (`_placed_dirs`, AR-107) - rzeczy zastane w archiwum
        to fakty o nim, które „Zmień…” liczy od nowa."""
        running = self._apply_worker is not None
        n = status_counts(self._plan.items).get("would-place", 0) if self._plan is not None else 0
        if self._plan is None and self._outcome is not None:
            self.btn_apply.setText(self._outcome)
        else:
            self.btn_apply.setText(i18n.t_plural("harvest.btn_apply", n))
        self.btn_apply.setEnabled(n > 0 and not running and not self._is_stale()
                                  and self._close_after_apply is None)
        receivable = bool(self._receivable_dirs())
        self.btn_accept.setVisible(receivable)
        self.btn_accept.setEnabled(receivable and self._close_after_apply is None)
        # Waga idzie za JEDYNĄ robotą okna: bez niczego do wciągnięcia, a z czymś do przyjęcia, gruby
        # i wysoki jest przycisk przyjęcia, nie wygaszony „Wciągnij 0 plików”. Domyślnym (Enter)
        # przyjęcie nie zostaje nigdy - bez domyślnego Enter w oknie nic nie robi. „Wciągnij” waży
        # WYŁĄCZNIE aktywny (AR-262, jak `ProjectionDialog._waga_akcji`): wygaszony gruby i domyślny
        # wskazywał martwy przycisk, gdy okno nie ma żadnej roboty.
        accept_heavy = receivable and n == 0 and not running
        apply_heavy = self.btn_apply.isEnabled() and not accept_heavy
        self.btn_apply.setDefault(apply_heavy)
        for btn, heavy in ((self.btn_apply, apply_heavy), (self.btn_accept, accept_heavy)):
            font = btn.font()
            font.setBold(heavy)
            btn.setFont(font)
            btn.setMinimumHeight(34 if heavy else 0)
        locked = bool(self._placed_dirs)
        for btn in (self.btn_archive, self.btn_archive_back):
            btn.setEnabled(not locked and not running)
            btn.setToolTip(i18n.t("harvest.archive_locked") if locked else "")

    # ---- sonda (auto-DRY) ----
    def _set_probing(self, on):
        """Pasek „pracuję” sondy - jedno miejsce, wołane też z wczesnych powrotów i przy wyniku
        nieaktualnej generacji (inaczej pasek wisiałby po sondzie, której nikt nie odebrał). Bieg
        apply ma własny pasek determinowany - tu go nie ruszamy."""
        if self._apply_worker is not None:
            return
        self.busy.setRange(0, 0)
        self.busy.setVisible(on)

    def _trigger_dry(self):
        """Sonda pod BIEŻĄCE parametry. Jeden worker naraz: sonda w biegu należy do starszej
        generacji (każde wołanie z pola idzie po `_invalidate`), więc dostaje anulowanie - nie
        czyta dalej plików, których wyniku nikt nie przyjmie - a świeża rusza po sprzątnięciu
        (`_dry_pending`). Wczesny powrót (puste pole, ścieżka względna, brak archiwum) gasi pasek
        i niczego nie zleca."""
        if self._closing or self._apply_worker is not None:
            return
        if self._dry_worker is not None:
            self._dry_worker.request_cancel()
        output = clean_path(self.edit_output.text())
        if not output:
            self._set_probing(False)
            self._show_notice(i18n.t("harvest.no_output"))
            return
        if not os.path.isabs(output):
            self._set_probing(False)
            self._show_notice(i18n.t("harvest.not_absolute", path=output), "error")
            return
        if not self._archive_root:
            self._set_probing(False)
            self._show_notice(i18n.t("harvest.no_archive"))
            return
        if self._dry_worker is not None:
            self._dry_pending = True                 # anulowany wyżej; świeża sonda po sprzątnięciu
            return
        self._dry_pending = False
        self._show_notice(i18n.t("harvest.probing"))
        self._set_probing(True)
        worker = HarvestDryWorker(self._db_path, output, self._archive_root, self._gen,
                                  con=None if self._db_path else self.con)
        worker.done.connect(self._on_dry_done)
        worker.failed.connect(self._on_dry_failed)
        self._dry_worker = worker
        if self._off_thread and self._db_path:
            self._dry_thread = QThread(self)
            worker.moveToThread(self._dry_thread)
            self._dry_thread.started.connect(worker.run)
            worker.finished.connect(self._dry_thread.quit)
            self._dry_thread.finished.connect(self._cleanup_dry_thread)
            self._dry_thread.start()
        else:
            try:
                worker.run()                         # inline: done/failed lecą direct = synchronicznie
            finally:
                self._dry_worker = None
            if self._dry_pending:
                self._trigger_dry()

    @Slot()
    def _cleanup_dry_thread(self):
        # KOLEJNOŚĆ jak w `projection_dialog._cleanup_dry_thread`: wait() przed thread.deleteLater(),
        # bo ~QThread doręczony na main przed śmiercią wątku czekałby na niego TRZYMAJĄC GIL, a wątek
        # (destrukcja wrappera workera) czekałby na GIL - AB-BA na stałe; wait() GIL zwalnia.
        if self._dry_thread is None:
            return                                   # wątek zebrał już `zatrzymaj_pola`; sygnał z kolejki
        self._dry_worker.deleteLater()
        self._dry_thread.wait()
        self._dry_thread.deleteLater()
        self._dry_worker = None
        self._dry_thread = None
        if self._dry_pending:
            self._trigger_dry()
        self._zwolnij_gdy_wolne()                    # sonda dłuższa niż limit zamknięcia trzymała okno

    @Slot(int, object)
    def _on_dry_done(self, gen, payload):
        self._set_probing(False)
        if self._closing:
            return
        if gen != self._gen:
            self._dry_pending = True                 # stale: odrzuć, świeża sonda po sprzątnięciu
            return
        wbpp_dir = payload["wbpp_dir"]
        if payload["missing"]:
            # Wyjście WYDANIA z listy bez folderu `out` to stan „czeka na WBPP” (wiersz listy mówi to
            # samo), nie awaria - notka rolą drugorzędną (AR-262). Ścieżka spoza listy: błąd jak dotąd.
            if norm_path(wbpp_dir) in {norm_path(r.out_dir) for r in self._releases}:
                self._show_notice(i18n.t("harvest.out_waiting", path=wbpp_dir), "secondary")
            else:
                self._show_notice(i18n.t("harvest.missing_dir", path=wbpp_dir), "error")
            return
        if payload.get("manifest_error") is not None:
            # Manifest najbliższego wydania leży, a nie da się go przeczytać (AR-234): sonda padła -
            # plan bez świadka mówiłby stosom „brak manifestu wydania” o pliku, który jest.
            sciezka, powod = payload["manifest_error"]
            self._on_dry_failed(gen, powod, zdanie=manifest_error_text(powod, sciezka))
            return
        plan = payload["plan"]
        nieprzeczytane = plan.unreadable_dirs
        if nieprzeczytane and norm_path(nieprzeczytane[0][0]) == norm_path(wbpp_dir):
            # Samego wyjścia nie da się przeczytać (`stat` przeszedł, listing nie: odmowa 5, zerwanie
            # udziału - AR-222): to sonda, która padła, nie pusty katalog - jak błąd `stat` (AR-199).
            self._on_dry_failed(gen, nieprzeczytane[0][1])
            return
        # Pamięć pola = ostatnie wyjście, które ISTNIAŁO: literówka nie wraca przy następnym otwarciu.
        self._settings().setValue("harvest/last_output", wbpp_dir)
        self._plan = plan
        self._probed = wbpp_dir
        self._shown_out = wbpp_dir                   # wynik biegu z tego planu liczy pliki względem tego samego wyjścia
        # Kopie, które leżą w archiwum, a baza ich nie zna (wciągnięte w innym oknie bez przyjęcia):
        # fakt o archiwum, nie o tym wyjściu - zostaje do zmiany archiwum (`_set_archive`, AR-107).
        unknown = {norm_path(it.exists_path): it.exists_path for it in plan.items
                   if it.status == "exists" and not it.known_to_db and it.exists_path}
        if unknown.keys() - self._unknown.keys():
            self._unknown.update(unknown)
            self._refresh_summary()
        # Stos z tej grupy niesie zbiór wejść z planu - przyjęty teraz dostaje rodowód dokładny,
        # choć położyło go inne okno.
        self._unknown_stacks.update((it.sha1_data, (tuple(it.frame_ids), it.release_canon))
                                    for it in plan.items
                                    if it.status == "exists" and not it.known_to_db
                                    and it.kind == "master_light" and it.sha1_data and it.frame_ids)
        # Wiersz listy z tym `out` liczy się teraz ze świeżego planu, nie z zeznań (wynik bez
        # zeznania wisiałby inaczej jako „do sprawdzenia” na zawsze); inne wiersze stoją. Plan
        # NIEPEŁNY (AR-222) wiersza nie liczy, a stawia BLOKADĘ (`SondaNiepelna`): jego zera nie
        # obejmują katalogów nieprzeczytanych, a liczby listy sprzed podglądu są stare - jedne i drugie
        # odsłoniłyby „folder możesz skasować”. Zdejmuje ją dopiero pełny podgląd tego `out`.
        if nieprzeczytane:
            self._fresh.pop(norm_path(wbpp_dir), None)
            self._sonda_niepelna[norm_path(wbpp_dir)] = SondaNiepelna(len(nieprzeczytane))
        else:
            self._sonda_niepelna.pop(norm_path(wbpp_dir), None)
            self._fresh[norm_path(wbpp_dir)] = plan_counts(plan.items)
        self._render_release_states()
        self._fill(plan.items)
        niepelny, szczegol = unread_note(nieprzeczytane, wbpp_dir)
        if not plan.items:
            self.head_label.setText("")
            if niepelny:                             # pusto w części przeczytanej - nie „brak masterów”
                self._show_notice(niepelny, "warn", szczegol)
            else:
                self._show_notice(i18n.t("harvest.empty", path=wbpp_dir))
        else:
            c = status_counts(plan.items)
            self.head_label.setText(i18n.t("harvest.head_dry", place=c.get("would-place", 0),
                                           exists=c.get("exists", 0), review=c.get("review", 0)))
            # Zdanie o wydaniu tylko wtedy, gdy rdzeń przyjął manifest jako świadka (układ wydania
            # obiektu) - manifest perspektywy gridu leżący wyżej nie jest wydaniem tych flatów.
            # Ścieżka = gdzie plik manifestu LEŻY, nie korzeń zapisany w nim w dniu wydania.
            found = payload.get("manifest_root")
            wydanie = (i18n.t("harvest.manifest_note", path=found or plan.manifest_root)
                       if plan.manifest_root else "")
            if niepelny:                             # najpierw plan niepełny, potem wydanie
                self._show_notice(" ".join(z for z in (niepelny, wydanie) if z), "warn", szczegol)
            else:
                self._show_notice(wydanie)
        self._sync_stale()

    @Slot(int, object)
    def _on_dry_failed(self, gen, msg, zdanie=None):
        """Sonda padła: błąd systemu klasą w języku UI, surowy tekst systemu pod kursorem (AR-184).
        Wiersz listy z tym wyjściem dostaje blokadę „podgląd nieudany” (AR-222): ani poprzedni podgląd,
        ani liczby listy nie mówią „wciągnięte”, dopóki pełny podgląd tego `out` się nie uda. Wyjście
        zna worker sondy (żyje do sprzątnięcia wątku, także przy wywołaniu z `_on_dry_done`).
        `zdanie` - gotowe zdanie zamiast „Nie można: …” (manifest wydania nie do przeczytania, AR-234)."""
        self._set_probing(False)
        if self._closing:
            return
        if gen != self._gen:
            self._dry_pending = True
            return
        wyjscie = getattr(self._dry_worker, "_wbpp_dir", None)
        if wyjscie:
            self._fresh.pop(norm_path(wyjscie), None)
            self._sonda_niepelna[norm_path(wyjscie)] = SondaNiepelna()
            self._render_release_states()
        self._plan = None
        self._sync_buttons()
        self._show_notice(zdanie or i18n.t("harvest.dry_failed", msg=tekst_powodu(msg)), "error",
                          wiersz_systemu(msg))

    def _show_notice(self, text, role=None, tip="", *, remember=True):
        """Komunikat stanu. `remember=False` - zdanie chwilowe (pole odbiega od podglądu), po którym
        wraca poprzedni komunikat. `tip` - szczegół systemu w podpowiedzi (`EtykietaBledu.ustaw`)."""
        if remember:
            self._notice_state = (text, role, tip)
        self.notice.ustaw(text, tip)
        self.notice.setProperty("role", role or "")
        self.notice.style().unpolish(self.notice)    # rola zmienia kolor z motywu dopiero po repolish
        self.notice.style().polish(self.notice)

    def _fill(self, items):
        """Tabela pozycji (plan albo wynik apply - te same pola, inne statusy). Plik WZGLĘDEM
        wyjścia WBPP, katalog WZGLĘDEM archiwum (`rel_text`); pełne ścieżki i pełny powód pod
        kursorem. Słowo stanu w kolorze swojej roli (`status_role`) - kolor bierze się z motywu przy
        każdym wypełnieniu, okno jest modalne i krótkotrwałe. Po wypełnieniu okno rośnie pod treść,
        a powód wraca w kadr (`_grow_to_table`)."""
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            folder = dir_of(it)
            reason = reason_text(it)
            # Pełny powód pod kursorem, a przy błędzie systemu klasą - wiersz surowego tekstu systemu
            # (AR-184): zdanie komórki mówi klasę w języku UI, ścieżka i komunikat systemu - tu.
            podpowiedz = "\n".join(p for p in (reason, wiersz_systemu(it.detail)) if p)
            cells = {COL_FILE: (rel_text(it.src, self._shown_out), it.src),
                     COL_KIND: (kind_text(it.kind), None),
                     COL_STATUS: (status_text(it.status), None),
                     COL_REASON: (reason, podpowiedz),
                     COL_NAME: (name_text(it), None),
                     COL_DIR: (rel_text(folder, self._archive_root), folder),
                     COL_RELEASE: (release_text(it), None)}
            role = status_role(it.status)
            for col, (text, tip) in cells.items():
                cell = QTableWidgetItem(text)
                if tip:
                    cell.setToolTip(tip)
                if col == COL_STATUS and role is not None:
                    cell.setForeground(_COLORS[role])
                self.table.setItem(i, col, cell)
        self._grow_to_table()

    # ---- lista wydań ----
    def _show_rel_notice(self, text, role=None, tip=""):
        """Zdanie nad listą wydań (brak kart, liczenie, pusta lista, błąd). Z kartami wiersz zdania
        zostaje także pusty - miejsce listy jest zarezerwowane; bez kart pusty tekst go chowa.
        `tip` - szczegół systemu w podpowiedzi (`EtykietaBledu.ustaw`)."""
        self.rel_notice.ustaw(text, tip)
        self.rel_notice.setProperty("role", role or "")
        self.rel_notice.style().unpolish(self.rel_notice)
        self.rel_notice.style().polish(self.rel_notice)
        self.rel_notice.setVisible(bool(text) or bool(self._rel_roots))

    def _trigger_releases(self):
        """Lista wydań z kart pod BIEŻĄCE zamówienie (start okna, koniec biegu apply). Jeden worker
        naraz: zamówienie w trakcie listy podnosi generację - wynik w biegu odpadnie - a świeża
        lista rusza po sprzątnięciu (`_rel_pending`). Bez kart nie ma czego liczyć, a po zamknięciu
        zgłoszonym w biegu apply - nie ma komu jej pokazać."""
        if self._closing or self._close_after_apply is not None or not self._rel_roots:
            return
        self._rel_gen += 1
        if self._rel_worker is not None:
            self._rel_pending = True
            return
        self._rel_pending = False
        if not self._releases:
            self._show_rel_notice(i18n.t("harvest.rel.probing"))
        worker = HarvestReleasesWorker(self._rel_roots, self._rel_gen, archive_root=self._archive_root,
                                       db_path=self._db_path, con=None if self._db_path else self.con)
        worker.missing.connect(self._on_releases_missing)
        worker.done.connect(self._on_releases_done)
        worker.failed.connect(self._on_releases_failed)
        self._rel_worker = worker
        if self._off_thread:
            self._rel_thread = QThread(self)
            worker.moveToThread(self._rel_thread)
            self._rel_thread.started.connect(worker.run)
            worker.finished.connect(self._rel_thread.quit)
            self._rel_thread.finished.connect(self._cleanup_rel_thread)
            self._rel_thread.start()
        else:
            try:
                worker.run()                         # inline: done/failed lecą direct = synchronicznie
            finally:
                self._rel_worker = None
            if self._rel_pending:
                self._trigger_releases()

    @Slot()
    def _cleanup_rel_thread(self):
        # wait() przed thread.deleteLater() - ten sam deadlock GIL × ~QThread co w `_cleanup_dry_thread`;
        # wątek już skończył (`finished`), więc wait() wraca od razu.
        if self._rel_thread is None:
            return                                   # wątek zebrał już `zatrzymaj_pola`; sygnał z kolejki
        self._rel_worker.deleteLater()
        self._rel_thread.wait()
        self._rel_thread.deleteLater()
        self._rel_worker = None
        self._rel_thread = None
        if self._rel_pending and not self._closing:
            self._trigger_releases()
        self._zwolnij_gdy_wolne()                    # lista dobiegła po zamknięciu - okno może zniknąć

    @Slot(int, object)
    def _on_releases_missing(self, gen, roots):
        """Karty bez folderu z listy bieżącej generacji - zdanie nad listą czyta je w `_fill_releases`
        (sygnał przychodzi przed `done` tej samej generacji); lista starszego zamówienia odpada."""
        if not self._closing and gen == self._rel_gen:
            self._rel_missing = tuple(roots)

    @Slot(int, object)
    def _on_releases_done(self, gen, rows):
        """Lista bieżącej generacji: tabela, zaznaczenie za polem, a przy PIERWSZEJ liście - wybór
        startowy. Wybór startowy zaznacza najnowsze wydanie z kandydatami i sonduje jego `out`, ale
        tylko wtedy, gdy człowiek niczego jeszcze nie wskazał (`_requested`), nie pisze właśnie w polu
        (`isModified`) i nic nie biegnie - lista, która przyszła później, nie przestawia pola, które
        ktoś już wybrał albo w które pisze."""
        if self._closing:
            return
        if gen != self._rel_gen:
            self._rel_pending = True                 # stale: odrzuć, świeża lista po sprzątnięciu
            return
        self._fill_releases(rows)
        self._take_lineage(rows)
        if self._rel_started:
            return
        self._rel_started = True
        if self._field_taken():
            return
        i = preselect_index(rows)
        if i is not None:
            self._set_output(rows[i].out_dir)        # zaznaczenie idzie za polem (`_on_output_edited`)
        else:
            self._on_output_edited()                 # nic do wciągnięcia - podgląd pamięci pola

    @Slot(int, object)
    def _on_releases_failed(self, gen, msg):
        if self._closing:
            return
        if gen != self._rel_gen:
            self._rel_pending = True
            return
        self._rel_missing = ()                       # braki kart należą do listy, która się udała
        # Błąd systemu klasą w języku UI, surowy tekst systemu pod kursorem (AR-184).
        self._show_rel_notice(i18n.t("harvest.rel.failed", msg=tekst_powodu(msg)), "error",
                              wiersz_systemu(msg))
        if not self._rel_started:
            self._rel_started = True
            if not self._field_taken():
                self._on_output_edited()             # bez listy okno dalej działa na polu

    def _field_taken(self):
        """Pole należy do człowieka: wskazał wyjście (`_requested`), pisze w polu (`isModified` -
        `setText` z kodu flagę zdejmuje) albo biegnie apply. Wtedy pierwsza lista nie robi wyboru."""
        return (self._requested is not None or self.edit_output.isModified()
                or self._apply_worker is not None)

    def _fill_releases(self, rows):
        """Tabela listy wydań: obiekt · karta · data · stan; pełne ścieżki pod kursorem. Wypełnienie
        bez sygnału wyboru - przebudowa tabeli nie jest wyborem człowieka."""
        self._releases = list(rows)
        blocked = self.rel_table.blockSignals(True)
        try:
            self.rel_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                cells = {REL_OBJECT: (row.object_canon or os.path.basename(row.object_root), row.object_root),
                         REL_CARD: (row.root, row.root),
                         REL_DATE: release_date_cell(row),
                         REL_STATE: ("", release_state_tip(row))}
                for col, (text, tip) in cells.items():
                    cell = QTableWidgetItem(str(text))
                    if tip:
                        cell.setToolTip(str(tip))
                    self.rel_table.setItem(i, col, cell)
        finally:
            self.rel_table.blockSignals(blocked)
        self._render_release_states()
        self._show_rel_notice(*self._zdanie_listy(rows))
        path = self._requested[0] if self._requested is not None else clean_path(self.edit_output.text())
        self._select_release_for(path)

    def _zdanie_listy(self, rows):
        """`(zdanie, rola, szczegół)` nad listą wydań: karta bez folderu na dysku mówi o SOBIE w roli
        ostrzeżenia (AR-147) - także obok listy z innych kart, bo jej wydań lista nie policzyła - a zdanie
        o pustych kartach zostaje dla kart, które istnieją i nie mają wydań. Karta, której folderu albo
        `OBJECTS` nie da się przeczytać (zerwany udział, odmowa - AR-222), mówi klasą błędu w języku UI,
        a surowy tekst systemu stoi w szczególe; obok braku - drugim zdaniem. Pusty tekst = lista mówi
        sama."""
        brak = [karta for karta, powod in self._rel_missing if powod is None]
        nieczytelne = [(karta, powod) for karta, powod in self._rel_missing if powod is not None]
        zdania = []
        if len(brak) == 1:
            zdania.append(i18n.t("harvest.rel.missing_one", path=brak[0]))
        elif brak:
            zdania.append(i18n.t_plural("harvest.rel.missing_many", len(brak), paths=", ".join(brak)))
        if len(nieczytelne) == 1:
            karta, powod = nieczytelne[0]
            zdania.append(i18n.t("harvest.rel.unreachable_one", path=karta, msg=tekst_powodu(powod)))
        elif nieczytelne:
            zdania.append(i18n.t_plural("harvest.rel.unreachable_many", len(nieczytelne),
                                        paths=", ".join(karta for karta, _powod in nieczytelne)))
        if zdania:
            szczegol = "\n".join(w for w in (wiersz_systemu(p) for _k, p in nieczytelne) if w)
            return " ".join(zdania), "warn", szczegol
        return ("" if rows else i18n.t("harvest.rel.none")), None, ""

    def _take_lineage(self, rows):
        """Stosy z listy, których rodowodu dokładnego baza nie ma (AR-104: zwykłe „Zamknij”, potem
        osobna Dostawa - zbiór wejść leży tylko w zeznaniu żniw w folderze wydania). Fakt o archiwum
        okna, nie o wybranym wierszu - zostaje do zmiany archiwum jak kopie nieznane bazie: odsłania
        „Zamknij i przyjmij”, a przyjęcie oddaje te stosy gospodarzowi; archiwum nie blokuje (AR-107)."""
        nowe = {norm_path(path): path for row in rows for _sha1, _ids, path, _kanon in row.lineage}
        self._lineage_stacks.update((sha1, (tuple(ids), kanon))
                                    for row in rows for sha1, ids, _path, kanon in row.lineage)
        if nowe.keys() - self._lineage.keys():
            self._lineage.update(nowe)
            self._refresh_summary()
        self._sync_buttons()

    def _fresh_of(self, row):
        """`plan_counts` ostatniego podglądu `out` tego wiersza, `SondaNiepelna` (podgląd niepełny albo
        nieudany - blokada przed każdą liczbą, AR-222) albo None (wiersz mówi listą)."""
        klucz = norm_path(row.out_dir)
        return self._sonda_niepelna.get(klucz) or self._fresh.get(klucz)

    def _render_release_states(self):
        """Komórka stanu każdego wiersza - z listy albo ze świeżego planu jego `out` (`_fresh`) -
        i zdanie pod listą dla zaznaczonego wiersza."""
        for i, row in enumerate(self._releases):
            item = self.rel_table.item(i, REL_STATE)
            if item is not None:
                item.setText(release_state_text(row, self._fresh_of(row)))
        self._fit_rel_columns()                      # stan zmienił treść - karta oddaje mu miejsce
        self._sync_release_note()

    def _select_release_for(self, path):
        """Zaznacz wiersz, którego `out` to `path` (bez wielkości liter, po normalizacji), albo żaden -
        bez sygnału wyboru: zaznaczenie idzie za polem i nie sonduje drugi raz."""
        key = norm_path(path) if path else None
        idx = next((i for i, r in enumerate(self._releases) if key and norm_path(r.out_dir) == key), None)
        blocked = self.rel_table.blockSignals(True)
        try:
            if idx is None:
                self.rel_table.clearSelection()
            else:
                self.rel_table.selectRow(idx)
        finally:
            self.rel_table.blockSignals(blocked)
        self._sync_release_note()

    def _selected_release(self):
        rows = self.rel_table.selectionModel().selectedRows()
        if not rows:
            return None
        i = rows[0].row()
        return self._releases[i] if 0 <= i < len(self._releases) else None

    def _on_release_selected(self):
        """Wybór wiersza przez człowieka = pole `<wydanie>\\out` i auto-DRY. W biegu apply lista jest
        wygaszona; gdyby sygnał i tak przyszedł, pole jest zamrożone (`_on_output_edited`)."""
        self._sync_release_note()
        row = self._selected_release()
        if row is None or self._apply_worker is not None:
            return
        self._set_output(row.out_dir)

    def _sync_release_note(self):
        """Zdanie pod listą i „Otwórz” przy zaznaczonym wierszu bez niczego do wciągnięcia (liczby
        ze świeżego planu, gdy jest): „folder możesz skasować” wyłącznie przy `is_harvested`, przy
        pozycjach do przeglądu - „najpierw rozstrzygnij” (ich pliki leżą tylko tam), przy stosach bez
        rodowodu dokładnego - „Zamknij i przyjmij”, folder zostaje (bez „Otwórz”: nie ma po co do niego
        wchodzić); inaczej nic. Okno bez archiwum o kasowaniu milczy: lista liczy rodowód stosów wobec
        `STACKS` archiwum, więc bez niego puste `lineage` znaczy „nie wiem”, nie „baza ma zbiór”. Okno
        na archiwum innym niż archiwum bazy też milczy: kopie leżą tam, gdzie Dostawa bazy ich nie
        zobaczy, a jedynym źródłem do archiwum bazy jest dalej ten folder. Zdania, które wstrzymują
        kasowanie, mają rolę `warn`; zgoda na kasowanie - `secondary`."""
        row = self._selected_release()
        fresh = self._fresh_of(row) if row is not None else None
        open_on, role = True, "warn"
        if (row is not None and self._archive_root and not self._archive_differs()
                and is_harvested(row, fresh)):
            self.rel_done_note.setText(i18n.t("harvest.rel.done_note"))
            role = "secondary"
        elif row is not None and needs_review(row, fresh):
            self.rel_done_note.setText(i18n.t("harvest.rel.review_note"))
        elif row is not None and needs_lineage(row, fresh):
            self.rel_done_note.setText(i18n.t("harvest.rel.lineage_note"))
            open_on = False
        else:
            row = None
        if self.rel_done_note.property("role") != role:
            self.rel_done_note.setProperty("role", role)
            self.rel_done_note.style().unpolish(self.rel_done_note)   # kolor roli z motywu po repolish
            self.rel_done_note.style().polish(self.rel_done_note)
        on = row is not None
        self.rel_done_note.setVisible(on)
        self.btn_open_release.setVisible(on and open_on)
        self.btn_open_release.setToolTip(row.object_root if on and open_on else "")

    def _on_open_release(self):
        """Folder zaznaczonego wydania w Eksploratorze - człowiek kasuje go sam, okno nie kasuje."""
        row = self._selected_release()
        if row is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(row.object_root))

    # ---- apply ----
    def _on_apply(self):
        """„Wciągnij N” - kopie w wątku tła według planu, który stoi w tabeli."""
        if (self._plan is None or self._apply_worker is not None or self._dry_worker is not None
                or self._is_stale() or self._close_after_apply is not None):
            return
        total = status_counts(self._plan.items).get("would-place", 0)
        if total == 0:
            return
        self._run_status = {}
        self._run_items = {it.dst: it for it in self._plan.items if it.status == "would-place"}
        # Bieg zmienia dysk i zostawia zeznanie: wiersz tego wyjścia mówi odtąd lista, nie plan sprzed biegu.
        self._fresh.pop(norm_path(self._plan.wbpp_dir or ""), None)
        self._apply_begin(total)
        worker = HarvestApplyWorker(self._plan, self._now())
        worker.progress.connect(self._on_apply_progress)
        worker.done.connect(self._on_apply_done)
        worker.failed.connect(self._on_apply_failed)
        self._apply_worker = worker
        if self._off_thread:
            self._apply_thread = QThread(self)
            worker.moveToThread(self._apply_thread)
            self._apply_thread.started.connect(worker.run)
            worker.finished.connect(self._apply_thread.quit)
            self._apply_thread.finished.connect(self._cleanup_apply_thread)
            self._apply_thread.start()
        else:
            try:
                worker.run()                         # inline: sloty lecą direct = synchronicznie
            finally:
                self._apply_worker = None
            self._sync_buttons()
            self._close_if_requested()

    @Slot()
    def _cleanup_apply_thread(self):
        # wait() przed thread.deleteLater() - ten sam deadlock GIL × ~QThread co w `_cleanup_dry_thread`.
        if self._apply_thread is None:
            return                                   # wątek zebrał już `zatrzymaj_pola`; sygnał z kolejki
        self._apply_worker.deleteLater()
        self._apply_thread.wait()
        self._apply_thread.deleteLater()
        self._apply_worker = None
        self._apply_thread = None
        self._sync_buttons()
        self._close_if_requested()

    def _apply_begin(self, total):
        """Tryb biegu: pasek `done/total` (bez napisu - licznik niesie notatka), „Przerwij” w miejscu
        „Wciągnij”, parametry zamrożone - zmiana pola wyzerowałaby plan, który worker właśnie kopiuje.
        Komunikat mówi, że dysk się zmienia, bo podgląd nad tabelą przestał być podglądem."""
        self._apply_seen = (0, total)
        self.busy.setRange(0, total)
        self.busy.setValue(0)
        self.busy.setVisible(True)
        self.progress_note.set_full_text(f"0/{total}")
        self._show_notice(i18n.t("harvest.applying"))
        self.btn_apply.setVisible(False)
        self.btn_apply.setEnabled(False)             # WPROST, nie tylko ukryciem (domyślny łapie Enter)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._set_params_enabled(False)

    def _apply_end(self):
        self.busy.setVisible(False)
        self.busy.setRange(0, 0)
        self.progress_note.set_full_text("")
        self.btn_cancel.setVisible(False)
        self.btn_apply.setVisible(True)
        self._set_params_enabled(True)

    def _set_params_enabled(self, on):
        """Parametry sondy w biegu apply: pole, „Wskaż…”, „Zmień…” i lista wydań (wybór wiersza
        przestawia pole). „Otwórz” zostaje - otwiera folder i niczego nie zmienia."""
        self.edit_output.setEnabled(on)
        self.btn_pick.setEnabled(on)
        self.rel_table.setEnabled(on)
        self.btn_archive.setEnabled(on and not self._placed_dirs)
        self.btn_archive_back.setEnabled(on and not self._placed_dirs)

    def _on_cancel_apply(self):
        if self._apply_worker is not None:
            self._apply_worker.request_cancel()      # rdzeń sprawdza PRZED następnym plikiem
            self.btn_cancel.setEnabled(False)
            self.progress_note.set_full_text(i18n.t("harvest.cancelling"))

    @Slot(int, int, str, str)
    def _on_apply_progress(self, done_n, total, dst, status):
        """Postęp per plik - i JEDYNE źródło faktów biegu: katalog każdej opublikowanej kopii
        i licznik kłopotów wpadają tu, zanim rdzeń odda wynik, więc wyjątek po kopiach nie gubi
        tego, co już leży w archiwum. Przyjęcie dostępne od pierwszej kopii. Wciągnięty stos zapisuje
        tu swój zbiór wejść (pozycja planu biegu) - rodowód dostanie go po przyjęciu."""
        if self.busy.maximum() != total:
            self.busy.setRange(0, total)
        self.busy.setValue(done_n)
        self._apply_seen = (done_n, total)
        self._run_status[dst] = status
        if status == "placed":
            self._placed_dirs.add(os.path.dirname(dst))
            self._placed_keys.add(norm_path(dst))
            self._placed_n += 1
            it = self._run_items.get(dst)
            if it is not None and it.kind == "master_light" and it.sha1_data:
                self._placed_stacks[it.sha1_data] = (tuple(it.frame_ids), it.release_canon)
        elif status in ("conflict", "error", "verify_bad"):
            self._trouble[status] += 1
        if self._close_after_apply is None:
            self.progress_note.set_full_text(f"{done_n}/{total} · {os.path.basename(dst)}")
        self._sync_buttons()

    @Slot(object)
    def _on_apply_done(self, res):
        """Bieg skończony (pełny albo przerwany): tabela pokazuje statusy apply, nagłówek liczby
        skutku. Zeznanie, którego nie zapisano (`manifest_error`), to ostrzeżenie przy kopiach,
        które leżą - nie błąd kopii."""
        self._apply_end()
        self._placed_dirs.update(res.placed_dirs)    # to samo, co zebrał postęp - zbiór, więc bez podwojeń
        self._plan = None                            # dysk się zmienił - kolejny bieg wymaga świeżej sondy (Enter, „Wskaż…”)
        self._fill(res.items)                        # wynik biegu dla `_probed` - pole odbiegające dalej go wyszarza
        c = status_counts(res.items)
        self._show_head_done(c, cancelled=res.cancelled)
        if res.manifest_error:
            # Błąd systemu klasą w języku UI, surowy tekst systemu pod kursorem (AR-184).
            self._show_notice(self._zdanie_zeznania(res.manifest_error, c),
                              "warn", wiersz_systemu(res.manifest_error))
        else:
            self._show_notice("")
        self._set_summary(c, cancelled_n=c.get("cancelled", 0) if res.cancelled else 0,
                          manifest_error=res.manifest_error)
        self._outcome = i18n.t("harvest.btn_cancelled" if res.cancelled else
                               "harvest.btn_done" if c.get("placed") else "harvest.btn_nothing")
        self._sync_buttons()
        self._trigger_releases()                     # zeznanie biegu zmieniło stan wydania na liście

    @Slot(object)
    def _on_apply_failed(self, powod):
        """Wyjątek rdzenia w biegu. Tabela, liczby i `summary` biorą prawdę z postępu: pozycja,
        która przeszła przez klingę, ma jej status; reszta planu nie została tknięta (`cancelled`).
        Kopie, które leżą, dalej można przyjąć. Błąd systemu klasą mówi w języku UI w notce
        i w zdaniu paska (`_set_summary`), surowy tekst systemu - pod kursorem notki (AR-184) i zdania
        paska (AR-218)."""
        msg = tekst_powodu(powod)
        done_n, total = self._apply_seen
        self._apply_end()
        items = [dataclasses.replace(it, status=self._run_status.get(it.dst, "cancelled"))
                 if it.status == "would-place" else it for it in (self._plan.items if self._plan else [])]
        self._plan = None
        self._fill(items)
        c = status_counts(items)
        self._show_head_done(c, cancelled=bool(c.get("cancelled")))
        made = i18n.t("harvest.made_before_error", done=done_n, total=total) if done_n else ""
        self._show_notice(i18n.t("harvest.apply_error", msg=msg, made=made), "error",
                          wiersz_systemu(powod))
        self._set_summary(c, cancelled_n=0, error=powod)
        self._outcome = i18n.t("harvest.btn_error")
        self._sync_buttons()
        self._trigger_releases()                     # kopie sprzed błędu też zmieniają stan wydania

    def _show_head_done(self, c, *, cancelled):
        head = i18n.t("harvest.head_done", placed=c.get("placed", 0), exists=c.get("exists", 0),
                      review=c.get("review", 0), conflict=c.get("conflict", 0),
                      errors=c.get("error", 0))
        if c.get("verify_bad"):
            head += i18n.t("harvest.verify_bad_tail", n=c["verify_bad"])
        if cancelled:
            head += i18n.t("harvest.cancelled_tail", n=c.get("cancelled", 0))
        self.head_label.setText(head)

    def _set_summary(self, c, *, cancelled_n, error=None, manifest_error=None):
        """Fakty ostatniego biegu do zdania paska (statusy, nietknięte przy przerwaniu, wyjątek
        rdzenia, niezapisane zeznanie biegu); samo zdanie składa `_refresh_summary` ze wszystkich
        faktów okna. `error` i `manifest_error` to powody rdzenia: zdanie w języku UI idzie do zdania
        paska, surowy tekst systemu (`wiersz_systemu`) do jego podpowiedzi (AR-218) - pasek stanu
        to jedyny ślad po zamknięciu okna, a notka z plikiem, który padł, zamyka się z nim."""
        self._ran = True
        self._last_counts = Counter(c)
        self._last_cancelled = cancelled_n
        self._last_error = tekst_powodu(error) if error else None
        self._last_manifest = self._zdanie_zeznania(manifest_error, c) if manifest_error else None
        self._szczegoly_biegu = "\n".join(wiersz_systemu(p) for p in (error, manifest_error)
                                          if p and wiersz_systemu(p))
        self._refresh_summary()

    def _zdanie_zeznania(self, powod, c):
        """Zdanie niezapisanego zeznania biegu (notka i zdanie paska): „Kopie leżą w archiwum, ale…”
        wyłącznie wtedy, gdy kopie leżą - wciągnięte w oknie (`_placed_n`) albo zastane w archiwum
        w tym biegu (`exists` w statusach `c`). Zeznanie pisze się zawsze, także przy biegu
        przerwanym przed pierwszą kopią i przy samych błędach kopii - wtedy samo „zeznania nie
        zapisano”."""
        klucz = ("harvest.manifest_error" if self._placed_n or c.get("exists")
                 else "harvest.manifest_error_none")
        return i18n.t(klucz, err=tekst_powodu(powod))

    def _summary_fact(self, *, with_root):
        """Zdanie główne paska: ile wciągnięto, a bez kopii - ile kopii w archiwum nie zna baza,
        a bez obu - błąd albo „nic nie wciągnięto”; None = w oknie nic się nie stało. `with_root`
        - ścieżka w zdaniu (wynik okna, przyjęcie); bez niej - zdanie zwykłego „Zamknij”, w którym
        ścieżka stoi za instrukcją (`_close_summary`)."""
        dirs = self._copy_dirs() or {os.path.dirname(p) for p in self._lineage.values()}
        root = common_root(dirs) or ", ".join(sorted(dirs))
        if self._placed_n:
            if with_root:
                return i18n.t_plural("harvest.status_placed", self._placed_n, root=root)
            return i18n.t_plural("harvest.close_placed", self._placed_n)
        if self._unknown:
            if with_root:
                return i18n.t_plural("harvest.status_unknown", len(self._unknown), root=root)
            return i18n.t_plural("harvest.close_unknown", len(self._unknown))
        if self._lineage:
            if with_root:
                return i18n.t("harvest.status_lineage", n=len(self._lineage), root=root)
            return i18n.t("harvest.close_lineage", n=len(self._lineage))
        if self._last_error:                         # nic nie leży - błąd jest całą wiadomością
            return i18n.t("harvest.status_error", msg=self._last_error)
        if self._ran:
            return i18n.t("harvest.status_nothing", exists=self._last_counts.get("exists", 0),
                          review=self._last_counts.get("review", 0))
        return None

    def _summary_tail(self):
        """Dopiski zdania paska ze WSZYSTKICH biegów okna: błąd przy kopiach, które leżą, niezerowe
        konflikty, błędy i niezgodne bajty (zera milczą), kopie nieznane bazie obok wciągniętych,
        nietknięte przy przerwaniu. Pasek stanu to jedyny ślad po zamknięciu okna, a „wciągnięto 3”
        bez „konflikty: 1” kłamie o komplecie.

        Błąd biegu stoi w zdaniu ZAWSZE: w zdaniu głównym, gdy nic nie leży, a inaczej tutaj - także
        przy samych stosach do rodowodu (`_lineage`), przy których zdanie główne mówiło stosy, a błąd
        znikał z paska. Niezapisane zeznanie biegu (`manifest_error`) - tak samo: notka okna mówiła
        o nim, pasek milczał (AR-218)."""
        tail = ""
        if self._last_error and (self._placed_n or self._unknown or self._lineage):
            tail += " · " + i18n.t("harvest.status_error", msg=self._last_error)
        if self._last_manifest:
            tail += " · " + self._last_manifest
        for status, key in _TROUBLE_KEYS:
            if self._trouble[status]:
                tail += i18n.t(key, n=self._trouble[status])
        extra = len(self._unknown.keys() - self._placed_keys) if self._placed_n else 0
        if extra:
            tail += i18n.t("harvest.sum_unknown", n=extra)
        if self._last_cancelled:
            tail += i18n.t("harvest.cancelled_tail", n=self._last_cancelled)
        return tail

    def _refresh_summary(self):
        """`summary` = zdanie główne ze ścieżką + dopiski. Drugi bieg z zerem po pierwszym
        z wciągnięciem mówiłby inaczej „nic nie wciągnięto” nad korzeniem, który gospodarz przyjmuje."""
        fact = self._summary_fact(with_root=True)
        self.summary = None if fact is None else self._zdanie_paska(fact + self._summary_tail())

    def _zdanie_paska(self, tekst):
        """Zdanie paska ze szczegółem systemu błędu i niezapisanego zeznania ostatniego biegu
        (`ZdanieZeSzczegolem`, AR-218) - oba człony zdanie mówi zawsze (`_summary_fact`,
        `_summary_tail`), więc szczegół zawsze ma swoje zdanie. Bez szczegółu - zwykły tekst."""
        return ZdanieZeSzczegolem(tekst, self._szczegoly_biegu) if self._szczegoly_biegu else tekst

    def _close_summary(self):
        """Zdanie zwykłego „Zamknij” przy kopiach do przyjęcia: fakt, dopiski, INSTRUKCJA, a ścieżka
        na końcu - pasek stanu ucina koniec zdania, a instrukcja bez ścieżki dalej mówi, co zrobić.
        Przy stosach instrukcja mówi najpierw, że rodowód dokładny zapisze WYŁĄCZNIE „Zamknij
        i przyjmij” (Dostawa daje stosowi rodowód okna czasu - AR-104); zdanie o następnej dostawie
        dotyczy tylko kopii, których baza nie zna."""
        text = self._summary_fact(with_root=False)
        dirs = self._copy_dirs()
        stosy = {**self._lineage_stacks, **self._unknown_stacks, **self._placed_stacks}
        if dirs and stosy:                           # zdanie samych stosów (`close_lineage`) niesie ją samo
            text += i18n.t("harvest.close_lineage_tail", n=len(stosy))
        text += self._summary_tail()
        if dirs:
            text += self._later_tail(dirs, common_root(dirs) or ", ".join(sorted(dirs)))
        return text

    # ---- przyjęcie i zamknięcie ----
    def _copy_dirs(self):
        """Katalogi kopii, których baza nie zna: wciągnięte w tym oknie ∪ zastane w archiwum
        (`exists` z `known_to_db=False`)."""
        return self._placed_dirs | {os.path.dirname(p) for p in self._unknown.values()}

    def _receivable_dirs(self):
        """Katalogi do przyjęcia: kopie, których baza nie zna (`_copy_dirs`) ∪ katalogi stosów bez
        rodowodu dokładnego z listy (`_lineage`, AR-104). Ten zbiór niesie widoczność „Zamknij
        i przyjmij”, korzeń, `done()` i zdanie paska; blokadę archiwum - tylko `_placed_dirs` (AR-107)."""
        return self._copy_dirs() | {os.path.dirname(p) for p in self._lineage.values()}

    def _receivable_root(self):
        """Korzeń do przyjęcia albo zdanie odmowy. EXPECT na korzeniu, który pójdzie do skanu
        Dostawy, wobec bibliotek archiwum OKNA (korzeń przed segmentem `CALIBRATION`, jak w planie):
        wszystkie katalogi pod `<archiwum>\\CALIBRATION` → ich wspólny rodzic (skan tylko tego, co
        wciągnięto); choć jeden pod `<archiwum>\\STACKS`, reszta w bibliotekach → korzeń archiwum (sito
        `STACKS` łańcucha bierze stos dopiero ze skanu korzenia); katalog poza obiema bibliotekami
        (dwa wolumeny, archiwum zmienione obejściem blokady) → odmowa: Dostawa skanowałaby coś,
        czego żniwa nie pisały."""
        dirs = self._receivable_dirs()
        try:
            lib = harvest.library_root(self._archive_root) if self._archive_root else ""
        except ValueError:
            lib = ""
        cal = os.path.join(lib, projection.CALIBRATION_SEGMENT) if lib else ""
        stk = os.path.join(lib, harvest.STACKS_SEGMENT) if lib else ""
        outside = sorted(d for d in dirs if not (cal and (is_under(d, cal) or is_under(d, stk))))
        if not dirs or outside:
            return None, i18n.t("harvest.accept_refused", root=", ".join(outside or sorted(dirs)) or "?",
                                cal=cal or "?", stacks=stk or "?")
        if all(is_under(d, cal) for d in dirs):
            return common_root(dirs), None
        return lib, None

    def _on_accept(self):
        """„Zamknij i przyjmij do archiwum”: korzeń dla gospodarza (strażnik `_receivable_root`)
        i zamknięcie. W biegu - zamknięcie po bieżącym pliku (`done`), a korzeń i stosy liczą się
        jeszcze raz przy zamknięciu, bo bieżący plik mógł dołożyć katalog albo stos."""
        root, why = self._receivable_root()
        if why is not None:
            self.harvested_root = None
            self.harvested_stacks = []
            self._show_notice(why, "error")
            return
        self.harvested_root = root
        self.accept()

    def _close_if_requested(self):
        """Zamknięcie zgłoszone w biegu apply wykonuje się, gdy bieg naprawdę wrócił."""
        if self._close_after_apply is not None and self._apply_worker is None:
            r, self._close_after_apply = self._close_after_apply, None
            self.done(r)

    def done(self, r):
        """Zamknięcie (Zamknij/Esc/X/„Zamknij i przyjmij”) nie zostawia żywego wątku pod kasowanym
        rodzicem.

        APPLY W BIEGU: zamknięcie = ŻĄDANIE ANULOWANIA, okno zostaje do końca bieżącego pliku
        (wzorzec `ProjectionDialog.done`). Czekanie w wątku głównym byłoby zakładem o czas kopii
        mastera przez SMB, a okno w tym czasie martwe; zamiast tego przyciski gasną, zdanie mówi
        „Zamykam po bieżącym pliku…”, a zamknięcie wykonuje `_close_if_requested` po sprzątnięciu
        wątku - z wynikiem biegu już w `summary`.

        SONDA: anulowanie na granicy pliku (`should_cancel` rdzenia) + `wait` - czeka najwyżej na
        odczyt jednego mastera; limit 10 s jak w oknie wydania chroni przed zawieszonym SMB.
        Świeża sonda po zamknięciu już nie startuje (`_closing`).

        LISTA WYDAŃ: rdzeń nie ma punktu przerwania, więc czekanie byłoby zakładem o czas spaceru
        po kartach (SMB) w wątku głównym. Generacja w górę (wynik nie dotknie zamkniętego okna),
        `quit()` kończy wątek zaraz po liście, a zbiera go `_cleanup_rel_thread`. Okno żyje dalej pod
        rodzicem gospodarza; zanim gospodarz zniknie, czeka na wątek `zatrzymaj_pola`.

        Zamknięte okno bez żywego wątku kasuje się samo (`_zwolnij_gdy_wolne`) - z wątkiem w biegu
        robi to sprzątanie ostatniego wątku."""
        if self._apply_worker is not None:
            self._close_after_apply = r
            self._apply_worker.request_cancel()
            self.btn_cancel.setEnabled(False)
            self.btn_close.setEnabled(False)
            self._sync_buttons()
            self.progress_note.set_full_text(i18n.t("harvest.closing"))
            return
        self._closing = True
        if self._dry_worker is not None:
            self._dry_worker.request_cancel()
        if self._dry_thread is not None:
            self._dry_thread.quit()
            self._dry_thread.wait(10_000)
        self._rel_gen += 1
        if self._rel_thread is not None:
            self._rel_thread.quit()
        if r == QDialog.Accepted and self.harvested_root is not None:
            self.harvested_root, _why = self._receivable_root()
        accepted = r == QDialog.Accepted and self.harvested_root is not None
        # Stosy do rodowodu: wciągnięte w tym oknie, zastane w archiwum bez wiedzy bazy (przyjmowane
        # teraz, położone wcześniej) i znane bazie bez rodowodu dokładnego (lista, AR-104) - jeden
        # wpis na `sha1_data`, z kanonem obiektu wydania (porównanie obiektu stosu po łańcuchu, AR-103).
        stosy = {**self._lineage_stacks, **self._unknown_stacks, **self._placed_stacks}
        self.harvested_stacks = ([(sha1, ids, kanon) for sha1, (ids, kanon) in stosy.items()]
                                 if accepted else [])
        if not accepted and self._receivable_dirs():
            self.summary = self._zdanie_paska(self._close_summary())
        super().done(r)
        self._zwolnij_gdy_wolne()

    def _zwolnij_gdy_wolne(self):
        """Zamknięte okno bez żywego wątku tła kasuje się samo (`deleteLater`). Bez tego każde
        zamknięte okno żniw zostawało ukrytym dzieckiem okna głównego do końca sesji - z tabelami,
        planem i listą wydań w pamięci. Usunięcie jest ODROCZONE: gospodarz czyta `summary`
        i `harvested_*` zaraz po `exec()`, a atrybuty Pythona przeżywają obiekt Qt i tak (zmierzone
        2026-10-13: PySide6 6.9.2, atrybut wrappera czytelny po `shiboken6.delete`). Wątek w biegu
        (lista wydań bez punktu przerwania, sonda dłuższa niż limit zamknięcia) trzyma okno przy
        życiu - `QThread` dziecka kasowany w biegu to twardy abort - więc wołają to też `_cleanup_*`
        po ostatnim wątku; do tego czasu wątek zbiera gospodarz przez `zatrzymaj_pola`. Raz na okno."""
        if (self._closing and not self._zwolnione and self._dry_thread is None
                and self._rel_thread is None and self._apply_thread is None):
            self._zwolnione = True
            self.deleteLater()

    def zatrzymaj_pola(self):
        """Okno znika razem z gospodarzem (zamknięcie aplikacji, przełączenie bazy -
        `MainWindow._zatrzymaj_watki_widokow` woła tę metodę po nazwie): ZBIERZ każdy wątek tła okna,
        zanim rodzic go skasuje - `QThread` niszczony w biegu to twardy abort. Zamknięte okno z wątkiem
        w biegu zostaje ukrytym dzieckiem okna głównego, a `done` na listę wydań nie czeka (rdzeń bez
        punktu przerwania, karta bywa uśpionym SMB) - więc czekanie żyje tu, poza gestem człowieka.
        Kolejność jak w `_cleanup_*` (quit z góry → worker.deleteLater → wait → thread.deleteLater);
        anulowanie powtarzane co 100 ms tam, gdzie worker je ma. Generacje w górę: wynik, który
        zdążył wyjść z wątku, nie dotknie okna. Idempotentne."""
        self._closing = True
        self._gen += 1
        self._rel_gen += 1
        self._zbierz(self._rel_thread, self._rel_worker)
        self._rel_thread = self._rel_worker = None
        self._zbierz(self._dry_thread, self._dry_worker)
        self._dry_thread = self._dry_worker = None
        self._zbierz(self._apply_thread, self._apply_worker)
        self._apply_thread = self._apply_worker = None

    @staticmethod
    def _zbierz(thread, worker):
        """Zakończ i zbierz jeden wątek tła (bez limitu czasu - to jest właśnie chwila, w której okno
        musi go przeżyć); brak wątku - nic."""
        if thread is None:
            return
        cancel = getattr(worker, "request_cancel", None)
        if cancel is not None:
            cancel()
        thread.quit()
        worker.deleteLater()
        while not thread.wait(100):
            if cancel is not None:
                cancel()
        thread.deleteLater()

    def _later_tail(self, dirs, root):
        """Kiedy baza pozna kopie, których nikt nie przyjął: przy następnej dostawie TYLKO wtedy,
        gdy wszystkie leżą pod źródłem Dostawy (`pipeline/last_source`); inaczej Dostawa ich nie
        zobaczy i zdanie mówi, którędy do nich dojść. Ścieżka za instrukcją."""
        source = str(self._settings().value("pipeline/last_source", "") or "").strip()
        if source and all(is_under(d, source) for d in dirs):
            return i18n.t("harvest.status_later", root=root)
        return i18n.t("harvest.status_outside", root=root)
