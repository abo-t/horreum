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

import dataclasses
import os
import threading
from collections import Counter
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from horreum import db, harvest, projection
from horreum.gui import i18n, queries
from horreum.gui.projection_dialog import _elide_path

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
}

# Powód STOSU, którego zdanie różni się od zdania tego samego tokenu przy master flacie. Stos
# z wejściami spoza wydania ma receptę (skopiować ręką do `STACKS`, Dostawa go weźmie) i liczbę
# wejść; master flat spoza wydania nie ma ani jednego, ani drugiego. Klucze ⊆ `harvest.REASONS`.
_STACK_REASONS = {
    "outside_release": "harvest.reason.outside_release_stack",
}

# Rodzaj pozycji (`HarvestItem.kind`, ten sam, który nada skan kopii) → słowo kolumny „Rodzaj”.
# Rodzaj spoza mapy (master z nagłówkiem surowej klatki) renderuje się tokenem, jak status.
_HARVEST_KINDS = {
    "master_flat": "harvest.kind.master_flat",
    "master_light": "harvest.kind.master_light",
    "master_dark": "harvest.kind.master_dark",
    "unknown": "harvest.kind.unknown",
}

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
_SCREEN_SHARE = 0.9                      # okno rośnie pod treść tabeli najwyżej do tej części ekranu

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


def find_manifest(wbpp_dir, levels=_MANIFEST_LEVELS):
    """Manifest wydania (`_PROJEKCJA.json`) w `wbpp_dir` albo do `levels` poziomów wyżej →
    `(korzeń, treść)`; brak → `(None, None)`. Pierwszy znaleziony wygrywa - najbliższe wydanie
    jest tym, w którego drzewie WBPP pracowało. `read_manifest` jest tolerancyjny (brak pliku
    i uszkodzony JSON to „nie wiem”), więc sonda nigdy tu nie pada."""
    d = os.path.abspath(wbpp_dir)
    for _ in range(levels + 1):
        payload = projection.read_manifest(d)
        if payload is not None:
            return d, payload
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
    sam, nie pustką."""
    detail = (item.detail or "").strip()
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


def release_counts(row, fresh=None):
    """`(niewciągnięte, wciągnięte, do przeglądu)` wiersza listy: ze świeżego planu (`plan_counts`),
    gdy podgląd przeliczył `out` tego wiersza, inaczej z listy (`harvest.ReleaseRow`)."""
    return fresh if fresh is not None else (row.pending, row.done, row.review)


def release_state_text(row, fresh=None):
    """Stan wiersza listy wydań: liczby (zera milczą), a bez żadnej - „czeka na WBPP”. Niewciągnięte
    z listy to „do sprawdzenia”: lista zna zeznania żniw, nie plan - kandydat bez rozstrzygającego
    zeznania może być równie dobrze przeglądem; „do wciągnięcia” mówi dopiero świeży plan (`fresh`).
    Wydanie nowsze od wyników (`awaiting_wbpp`) zaczyna od „czeka na WBPP”, a wciągnięte z poprzednich
    wyników są „poprzednio wciągnięte” - nie są wynikami OSTATNIEGO wydania. Stosy bez rodowodu
    dokładnego w bazie (`row.lineage`, z listy - plan bazy o nie nie pyta) to „rodowód do zapisania”."""
    pending, done, review = release_counts(row, fresh)
    parts = [i18n.t("harvest.rel.waiting")] if row.awaiting_wbpp else []
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
    return " · ".join(parts) if parts else i18n.t("harvest.rel.waiting")


def is_harvested(row, fresh=None):
    """Folder wydania przestał być Horreum potrzebny: nic do wciągnięcia ani do przeglądu (pliki
    przeglądu leżą tylko tam), coś wciągnięto, wyniki są wynikami OSTATNIEGO wydania, a każdy stos
    z tego folderu ma w bazie rodowód dokładny (inaczej zbiór jego wejść leży tylko w zeznaniu żniw)."""
    pending, done, review = release_counts(row, fresh)
    return pending == 0 and review == 0 and done > 0 and not row.awaiting_wbpp and not row.lineage


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
    failed = Signal(int, str)         # (generacja, komunikat)
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
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(self._gen, payload)
        finally:
            self.finished.emit()

    def _compute(self):
        if not os.path.isdir(self._wbpp_dir):
            return {"wbpp_dir": self._wbpp_dir, "missing": True}
        manifest_root, manifest = find_manifest(self._wbpp_dir)
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
    failed = Signal(str)                    # wyjątek → sygnał, nie crash okna
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
            self.failed.emit(f"{type(exc).__name__}: {exc}")
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
    failed = Signal(int, str)         # (generacja, komunikat)
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
            try:
                rows = harvest.releases(self._roots, archive_root=self._archive_root or None, con=con)
            finally:
                if own:
                    con.close()
        except Exception as exc:                     # lista pada szczerze, nie cichą śmiercią wątku
            self.failed.emit(self._gen, f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(self._gen, rows)
        finally:
            self.finished.emit()


# ---------------------------------------------------------------- dialog

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
        self._trouble = Counter()        # konflikty, błędy, niezgodne bajty - wszystkie biegi okna
        self._ran = False                # okno puściło choć jeden bieg apply
        self._last_counts = Counter()    # statusy ostatniego biegu (zdanie „nic nie wciągnięto”)
        self._last_cancelled = 0         # nietknięte w ostatnim, przerwanym biegu
        self._last_error = None          # wyjątek rdzenia ostatniego biegu
        self._close_after_apply = None   # kod zamknięcia zgłoszonego w biegu apply
        self._closing = False
        self._notice_state = ("", None)  # ostatni komunikat stanu - wraca, gdy pole przestaje odbiegać
        self.summary = None              # zdanie na pasek stanu gospodarza (None = nic się nie stało)
        self.harvested_root = None       # korzeń do przyjęcia - ustawia go WYŁĄCZNIE „Zamknij i przyjmij”
        self.harvested_stacks = []       # [(sha1_data, frame_ids, kanon wydania)] - razem z `harvested_root`
        self._shown_out = None           # wyjście WBPP pozycji w tabeli - kolumna pliku liczy się względem niego
        self._table_viewport = None      # viewport tabeli po budowie (filtr zdarzeń zmiany rozmiaru)
        self._first_pick_checked = False  # pierwsze użycie: wybór katalogu raz po pokazaniu (`showEvent`)
        self._rel_gen = 0                # licznik generacji listy wydań - lista starszego zamówienia odpada
        self._rel_thread = None
        self._rel_worker = None
        self._rel_pending = False        # zamówienie przyszło w biegu listy → świeża lista po sprzątnięciu
        self._rel_started = False        # pierwsza lista przyszła (wybór startowy zrobiony albo oddany polu)
        self._releases = []              # wiersze listy wydań w kolejności tabeli
        self.setWindowTitle(i18n.t("harvest.title"))
        self.setModal(True)
        self.resize(980, 600)
        self._build_ui()
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
        hint = QLabel(i18n.t("harvest.hint"))
        hint.setProperty("role", "secondary")
        hint.setWordWrap(True)
        v.addWidget(hint)

        # Lista wydań z kart. Zdanie nad nią: brak kart, liczenie, pusta lista, błąd listy. Z kartami
        # miejsce listy stoi od startu (zdanie o wysokości wiersza, pusta tabela, zarezerwowany wiersz
        # „wciągnięte”): lista, która dochodzi z tła, nie spycha pola i przycisków pod kursorem - klik
        # w „Wskaż…” trafiałby w wiersz listy.
        reserve = bool(self._rel_roots)
        self.rel_notice = QLabel("")
        self.rel_notice.setWordWrap(True)
        self.rel_notice.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.rel_notice.setMinimumHeight(self.rel_notice.fontMetrics().lineSpacing())
        self.rel_notice.setVisible(False)
        v.addWidget(self.rel_notice)
        self.rel_table = QTableWidget(0, len(_REL_HEADERS))
        self.rel_table.setHorizontalHeaderLabels([i18n.t(k) for k in _REL_HEADERS])
        self.rel_table.verticalHeader().setVisible(False)
        self.rel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rel_table.setWordWrap(False)
        rh = self.rel_table.horizontalHeader()
        rh.setSectionResizeMode(QHeaderView.ResizeToContents)
        rh.setStretchLastSection(True)
        self.rel_table.setMaximumHeight(
            rh.sizeHint().height() + _REL_VISIBLE_ROWS * self.rel_table.verticalHeader().defaultSectionSize()
            + 2 * self.rel_table.frameWidth())
        self.rel_table.itemSelectionChanged.connect(self._on_release_selected)
        self.rel_table.setVisible(reserve)
        v.addWidget(self.rel_table)
        # Wiersz zaznaczonego wydania bez niczego do wciągnięcia: zdanie (folder można skasować albo
        # najpierw przegląd) i „Otwórz” - bez kasowania.
        row_d = QHBoxLayout()
        self.rel_done_note = QLabel(i18n.t("harvest.rel.done_note"))
        self.rel_done_note.setProperty("role", "secondary")
        self.rel_done_note.setWordWrap(True)
        row_d.addWidget(self.rel_done_note, 1)
        self.btn_open_release = QPushButton(i18n.t("harvest.rel.btn_open"))
        self.btn_open_release.setAutoDefault(False)
        self.btn_open_release.clicked.connect(self._on_open_release)
        row_d.addWidget(self.btn_open_release)
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
        self.archive_warn = QLabel("")               # archiwum okna ≠ archiwum bazy (`_show_archive`)
        self.archive_warn.setProperty("role", "warn")
        self.archive_warn.setWordWrap(True)
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
        v.addWidget(self.head_label)
        # Stan okna jednym zdaniem: sonda w biegu, brak wyjścia, pusty katalog, błąd, bieg apply.
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        self.notice.setTextInteractionFlags(Qt.TextSelectableByMouse)   # ścieżkę z komunikatu da się skopiować
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
        v.addWidget(self.table, 1)

        act = QHBoxLayout()
        self.busy = QProgressBar()       # DRY = nieokreślony (`_set_probing`), apply = `done/total`
        self.busy.setRange(0, 0)
        self.busy.setMinimumWidth(220)
        self.busy.setTextVisible(False)
        self.busy.setVisible(False)
        act.addWidget(self.busy)
        self.progress_note = QLabel("")
        self.progress_note.setProperty("role", "secondary")
        act.addWidget(self.progress_note)
        act.addStretch(1)
        self.btn_apply = QPushButton(i18n.t_plural("harvest.btn_apply", 0))
        self.btn_apply.setEnabled(False)             # uzbraja WYŁĄCZNIE świeża sonda z czymś do wciągnięcia
        self.btn_apply.setDefault(True)
        _fa = self.btn_apply.font(); _fa.setBold(True); self.btn_apply.setFont(_fa)
        self.btn_apply.setMinimumHeight(34)
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
        self.archive_warn.setText(i18n.t("harvest.archive_differs", db=self._db_archive)
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
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """Pierwsze użycie (brak `harvest/last_output`) BEZ kart: od razu okno wyboru katalogu
        wyjścia, jak kafel Przyjmij przy pierwszej dostawie - puste pole i zdanie „Wskaż…” to jedna
        interakcja więcej do tego samego miejsca. Z kartami wyborem jest lista wydań, więc okno
        wyboru nie wyskakuje nad nią. Raz na okno, po pokazaniu (kolejka zdarzeń), żeby wybór
        stał nad oknem żniw, a nie przed nim; anulowanie zostawia okno z pustym polem."""
        super().showEvent(event)
        if not self._first_pick_checked:
            self._first_pick_checked = True
            if not self._rel_roots and not str(self._settings().value("harvest/last_output", "") or ""):
                QTimer.singleShot(0, self._on_pick_output)

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

    def _grow_to_table(self):
        """Szerokość okna pod treść tabeli: suma kolumn (powód w pełnej treści) + ramy, najwyżej
        90% dostępnej szerokości ekranu. Okno tylko ROŚNIE - nie zabiera szerokości, którą user mu
        dał - i nie schodzi poniżej szerokości startowej."""
        if self.table.rowCount() == 0:
            return
        hh = self.table.horizontalHeader()
        total = sum(max(self.table.sizeHintForColumn(c), hh.sectionSizeHint(c))
                    for c in range(len(_HEADERS)))
        m = self.layout().contentsMargins()
        overhead = (m.left() + m.right() + 2 * self.table.frameWidth()
                    + self.table.verticalScrollBar().sizeHint().width())
        screen = self.screen()
        cap = int(screen.availableGeometry().width() * _SCREEN_SHARE) if screen is not None else total + overhead
        target = min(total + overhead, cap)
        if target > self.width():
            self.resize(target, self.height())
        self._fit_columns()

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
        """Nowe parametry unieważniają podgląd: generacja ++, plan, tabela i słowo skutku znikają."""
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
        # przyjęcie nie zostaje nigdy - bez domyślnego Enter w oknie nic nie robi.
        accept_heavy = receivable and n == 0 and not running
        self.btn_apply.setDefault(not accept_heavy)
        for btn, heavy in ((self.btn_apply, not accept_heavy), (self.btn_accept, accept_heavy)):
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
            self._show_notice(i18n.t("harvest.missing_dir", path=wbpp_dir), "error")
            return
        # Pamięć pola = ostatnie wyjście, które ISTNIAŁO: literówka nie wraca przy następnym otwarciu.
        self._settings().setValue("harvest/last_output", wbpp_dir)
        plan = payload["plan"]
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
        # zeznania wisiałby inaczej jako „do sprawdzenia” na zawsze); inne wiersze stoją.
        self._fresh[norm_path(wbpp_dir)] = plan_counts(plan.items)
        self._render_release_states()
        self._fill(plan.items)
        if not plan.items:
            self.head_label.setText("")
            self._show_notice(i18n.t("harvest.empty", path=wbpp_dir))
        else:
            c = status_counts(plan.items)
            self.head_label.setText(i18n.t("harvest.head_dry", place=c.get("would-place", 0),
                                           exists=c.get("exists", 0), review=c.get("review", 0)))
            # Zdanie o wydaniu tylko wtedy, gdy rdzeń przyjął manifest jako świadka (układ wydania
            # obiektu) - manifest perspektywy gridu leżący wyżej nie jest wydaniem tych flatów.
            # Ścieżka = gdzie plik manifestu LEŻY, nie korzeń zapisany w nim w dniu wydania.
            found = payload.get("manifest_root")
            self._show_notice(i18n.t("harvest.manifest_note", path=found or plan.manifest_root)
                              if plan.manifest_root else "")
        self._sync_stale()

    @Slot(int, str)
    def _on_dry_failed(self, gen, msg):
        self._set_probing(False)
        if self._closing:
            return
        if gen != self._gen:
            self._dry_pending = True
            return
        self._plan = None
        self._sync_buttons()
        self._show_notice(i18n.t("harvest.dry_failed", msg=msg), "error")

    def _show_notice(self, text, role=None, *, remember=True):
        """Komunikat stanu. `remember=False` - zdanie chwilowe (pole odbiega od podglądu), po którym
        wraca poprzedni komunikat."""
        if remember:
            self._notice_state = (text, role)
        self.notice.setText(text)
        self.notice.setProperty("role", role or "")
        self.notice.style().unpolish(self.notice)    # rola zmienia kolor z motywu dopiero po repolish
        self.notice.style().polish(self.notice)

    def _fill(self, items):
        """Tabela pozycji (plan albo wynik apply - te same pola, inne statusy). Plik WZGLĘDEM
        wyjścia WBPP, katalog WZGLĘDEM archiwum (`rel_text`); pełne ścieżki i pełny powód pod
        kursorem. Po wypełnieniu okno rośnie pod treść, a powód wraca w kadr (`_grow_to_table`)."""
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            folder = dir_of(it)
            reason = reason_text(it)
            cells = {COL_FILE: (rel_text(it.src, self._shown_out), it.src),
                     COL_KIND: (kind_text(it.kind), None),
                     COL_STATUS: (status_text(it.status), None),
                     COL_REASON: (reason, reason),
                     COL_NAME: (name_text(it), None),
                     COL_DIR: (rel_text(folder, self._archive_root), folder),
                     COL_RELEASE: (release_text(it), None)}
            for col, (text, tip) in cells.items():
                cell = QTableWidgetItem(text)
                if tip:
                    cell.setToolTip(tip)
                self.table.setItem(i, col, cell)
        self._grow_to_table()

    # ---- lista wydań ----
    def _show_rel_notice(self, text, role=None):
        """Zdanie nad listą wydań (brak kart, liczenie, pusta lista, błąd). Z kartami wiersz zdania
        zostaje także pusty - miejsce listy jest zarezerwowane; bez kart pusty tekst go chowa."""
        self.rel_notice.setText(text)
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

    @Slot(int, str)
    def _on_releases_failed(self, gen, msg):
        if self._closing:
            return
        if gen != self._rel_gen:
            self._rel_pending = True
            return
        self._show_rel_notice(i18n.t("harvest.rel.failed", msg=msg), "error")
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
                         REL_DATE: (release_date_text(row.ts), row.ts),
                         REL_STATE: ("", row.out_dir)}
                for col, (text, tip) in cells.items():
                    cell = QTableWidgetItem(str(text))
                    if tip:
                        cell.setToolTip(str(tip))
                    self.rel_table.setItem(i, col, cell)
        finally:
            self.rel_table.blockSignals(blocked)
        self._render_release_states()
        self._show_rel_notice("" if rows else i18n.t("harvest.rel.none"))
        path = self._requested[0] if self._requested is not None else clean_path(self.edit_output.text())
        self._select_release_for(path)

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
        """`plan_counts` ostatniego podglądu `out` tego wiersza albo None (wiersz mówi listą)."""
        return self._fresh.get(norm_path(row.out_dir))

    def _render_release_states(self):
        """Komórka stanu każdego wiersza - z listy albo ze świeżego planu jego `out` (`_fresh`) -
        i zdanie pod listą dla zaznaczonego wiersza."""
        for i, row in enumerate(self._releases):
            item = self.rel_table.item(i, REL_STATE)
            if item is not None:
                item.setText(release_state_text(row, self._fresh_of(row)))
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
        """Tryb biegu: pasek `done/total`, „Przerwij” w miejscu „Wciągnij”, parametry zamrożone -
        zmiana pola wyzerowałaby plan, który worker właśnie kopiuje. Komunikat mówi, że dysk się
        zmienia, bo podgląd nad tabelą przestał być podglądem."""
        self._apply_seen = (0, total)
        self.busy.setRange(0, total)
        self.busy.setValue(0)
        self.busy.setFormat("%p%")
        self.busy.setTextVisible(True)
        self.busy.setVisible(True)
        self.progress_note.setText(f"0/{total}")
        self._show_notice(i18n.t("harvest.applying"))
        self.btn_apply.setVisible(False)
        self.btn_apply.setEnabled(False)             # WPROST, nie tylko ukryciem (domyślny łapie Enter)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._set_params_enabled(False)

    def _apply_end(self):
        self.busy.setVisible(False)
        self.busy.setTextVisible(False)
        self.busy.setFormat("")
        self.busy.setRange(0, 0)
        self.progress_note.setText("")
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
            self.progress_note.setText(i18n.t("harvest.cancelling"))

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
            self.progress_note.setText(f"{done_n}/{total} · {os.path.basename(dst)}")
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
            self._show_notice(i18n.t("harvest.manifest_error", err=res.manifest_error), "warn")
        else:
            self._show_notice("")
        self._set_summary(c, cancelled_n=c.get("cancelled", 0) if res.cancelled else 0)
        self._outcome = i18n.t("harvest.btn_cancelled" if res.cancelled else
                               "harvest.btn_done" if c.get("placed") else "harvest.btn_nothing")
        self._sync_buttons()
        self._trigger_releases()                     # zeznanie biegu zmieniło stan wydania na liście

    @Slot(str)
    def _on_apply_failed(self, msg):
        """Wyjątek rdzenia w biegu. Tabela, liczby i `summary` biorą prawdę z postępu: pozycja,
        która przeszła przez klingę, ma jej status; reszta planu nie została tknięta (`cancelled`).
        Kopie, które leżą, dalej można przyjąć."""
        done_n, total = self._apply_seen
        self._apply_end()
        items = [dataclasses.replace(it, status=self._run_status.get(it.dst, "cancelled"))
                 if it.status == "would-place" else it for it in (self._plan.items if self._plan else [])]
        self._plan = None
        self._fill(items)
        c = status_counts(items)
        self._show_head_done(c, cancelled=bool(c.get("cancelled")))
        made = i18n.t("harvest.made_before_error", done=done_n, total=total) if done_n else ""
        self._show_notice(i18n.t("harvest.apply_error", msg=msg, made=made), "error")
        self._set_summary(c, cancelled_n=0, error=msg)
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

    def _set_summary(self, c, *, cancelled_n, error=None):
        """Fakty ostatniego biegu do zdania paska (statusy, nietknięte przy przerwaniu, wyjątek
        rdzenia); samo zdanie składa `_refresh_summary` ze wszystkich faktów okna."""
        self._ran = True
        self._last_counts = Counter(c)
        self._last_cancelled = cancelled_n
        self._last_error = error
        self._refresh_summary()

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
        bez „konflikty: 1” kłamie o komplecie."""
        tail = ""
        if self._last_error and (self._placed_n or self._unknown):
            tail += " · " + i18n.t("harvest.status_error", msg=self._last_error)
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
        self.summary = None if fact is None else fact + self._summary_tail()

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
        rodzicem gospodarza; zanim gospodarz zniknie, czeka na wątek `zatrzymaj_pola`."""
        if self._apply_worker is not None:
            self._close_after_apply = r
            self._apply_worker.request_cancel()
            self.btn_cancel.setEnabled(False)
            self.btn_close.setEnabled(False)
            self._sync_buttons()
            self.progress_note.setText(i18n.t("harvest.closing"))
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
            self.summary = self._close_summary()
        super().done(r)

    def zatrzymaj_pola(self):
        """Okno znika razem z gospodarzem (zamknięcie aplikacji, przełączenie bazy -
        `MainWindow._zatrzymaj_watki_widokow` woła tę metodę po nazwie): ZBIERZ każdy wątek tła okna,
        zanim rodzic go skasuje - `QThread` niszczony w biegu to twardy abort. Zamknięte okno zostaje
        ukrytym dzieckiem okna głównego, a `done` na listę wydań nie czeka (rdzeń bez punktu
        przerwania, karta bywa uśpionym SMB) - więc czekanie żyje tu, poza gestem człowieka.
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
