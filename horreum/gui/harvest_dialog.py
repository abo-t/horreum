"""Okno „Wciągnij mastery…” - żniwa masterów z wyjścia WBPP do biblioteki kalibracji archiwum.

Okno odpowiada na jedno pytanie: które pliki z katalogu wyjścia WBPP są masterami, które Horreum
umie przypiąć do swoich surowych flatów, dokąd pójdą i pod jaką nazwą. Odpowiedź liczy Qt-wolny
rdzeń `horreum.harvest` (plan bez mutacji, kopia przez klingę `projection.copy_master`); tu jest
glue widżetów wzorem okna wydania (`projection_dialog`): auto-DRY w wątku tła z licznikiem
generacji, apply w wątku tła z anulowaniem na granicy pliku, `off_thread=False` jako seam testowy.

DRY idzie w tle, bo plan czyta pliki: master to ~100 MB, a jego tożsamość (`sha1_data`,
`file_sha1`) liczy się z całych bajtów - kilka masterów na SMB to sekundy, w których okno nie
może stać. Sonda startuje WYŁĄCZNIE na zdarzeniach dyskretnych (otwarcie z pamięci, „Wskaż…”,
Enter albo wyjście z pola, „Zmień…” archiwum), nie na każdym klawiszu: `discover` chodzi
rekurencyjnie, a pole w połowie pisania („E:\\”) kazałoby mu przejść cały dysk. Sonda jest
anulowalna na granicy pliku (`should_cancel` rdzenia) - zamknięcie okna w jej trakcie czeka
najwyżej na jeden plik. Tekst pola różny od sondowanego wyszarza tabelę: podgląd mówi
o katalogu, którego w polu już nie ma.

Dwa przyciski, każdy z jedną rolą: „Wciągnij N” (domyślny, kopie) i „Zamknij i przyjmij do
archiwum” (widoczny od pierwszego wciągniętego mastera). Żaden nie zmienia znaczenia na
zdarzeniu z tła - przycisk, który pod kursorem zamienia się z kopii w zamknięcie okna, łapie
klik przeznaczony dla poprzedniej roli. Enter nigdy nie przyjmuje: w polu potwierdza ścieżkę,
w reszcie okna trafia w „Wciągnij”, który bez świeżego planu jest wygaszony.

Okno NIE uruchamia łańcucha Dostawy: bieg etapów ma jednego właściciela (`PipelineView`).
Wynik dla gospodarza to dwa atrybuty: `summary` (zdanie na pasek stanu) i `harvested_root`
(korzeń do przyjęcia). Ten drugi ustawia WYŁĄCZNIE gest „Zamknij i przyjmij do archiwum” i tylko
wtedy, gdy korzeń leży pod `<archiwum>\\CALIBRATION` - stąd archiwum zamrożone od pierwszej kopii:
dwa archiwa w jednym oknie dałyby korzeń, którego Dostawa nie powinna skanować. Zwykłe
„Zamknij” zostawia mastery na dysku i mówi w `summary`, kiedy baza je pozna.

Prawda o biegu przychodzi z POSTĘPU, nie z wyniku: katalogi wciągniętych kopii i liczniki
kłopotów zbiera `_on_apply_progress`, więc wyjątek rdzenia po kopiach (gałąź `failed`, bez
wyniku) dalej pokazuje, co leży w archiwum, i pozwala to przyjąć. Zeznanie `_ZNIWA_<ts>.json`,
którego nie udało się zapisać, to ostrzeżenie przy kopiach, które leżą - nie błąd kopii.

Powody przeglądu i statusy jadą LITERALNYMI mapami `_HARVEST_REASONS` / `_HARVEST_STATUS` (wzór
`pipeline._REVIEW_REASONS`): kolektor kluczy i18n widzi tylko literały, a parytet map z rdzeniem
(`harvest.REASONS`, `harvest.STATUSES`) i z katalogiem pilnuje test tego okna. Plik na whiteliście
`test_gui_isolation` (warstwa widżetów)."""

from __future__ import annotations

import dataclasses
import os
import threading
from collections import Counter

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
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

# Kolumny tabeli. Powód TRZECI: to jedyna kolumna, która mówi, CO się nie zgadza, więc stoi przy
# pliku i stanie, a nie za dwiema ścieżkami - przy oknie węższym niż treść ścieżki przewijają się
# w bok, powód zostaje w kadrze (`_fit_columns`).
COL_FILE, COL_STATUS, COL_REASON, COL_NAME, COL_DIR, COL_RELEASE = range(6)
_HEADERS = ("harvest.col.file", "harvest.col.status", "harvest.col.reason", "harvest.col.name",
            "harvest.col.dir", "harvest.col.release")
_SCREEN_SHARE = 0.9                      # okno rośnie pod treść tabeli najwyżej do tej części ekranu


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


def reason_text(item):
    """Kolumna „Powód” (Qt-wolne). `reason` to TOKEN rdzenia (`harvest.REASONS`) - zdanie z mapy
    z `reason_n` (ile wejść, profili, nazw); `detail` to dane od rdzenia: CO się nie zgadza
    (nagłówek kontra profil), pierwsze nazwy nietrafionych wejść, wyjątek czytnika. Ekran pokazuje
    oba, bo sama kategoria nie mówi, co poprawić. Po apply token jest pusty, a `detail` niesie
    tekst klingi kopii (konflikt, błąd I/O). Pozycja `exists` bez obecnej kopii mówi to wprost -
    pusta kolumna katalogu wyglądałaby jak błąd. Token spoza mapy renderuje się sam, nie pustką."""
    detail = (item.detail or "").strip()
    if item.reason:
        key = _HARVEST_REASONS.get(item.reason)
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


# ---------------------------------------------------------------- dialog

class HarvestDialog(QDialog):
    """Żniwa masterów: pole wyjścia WBPP z pamięci (`harvest/last_output`), wiersz archiwum
    (`archive_root` od wołającego - domyślne archiwum podaje gospodarz), auto-DRY, tabela pozycji
    planu, „Wciągnij N” i „Zamknij i przyjmij do archiwum”. `now_fn` = zegar (znacznik zeznania
    `_ZNIWA_<ts>.json`); `off_thread=False` = oba workery inline (seam testowy, sygnały direct =
    synchronicznie)."""

    def __init__(self, con, *, now_fn, archive_root, off_thread=True, parent=None):
        super().__init__(parent)
        self.con = con
        self._db_path = queries.db_path_of(con)
        self._now = now_fn
        root = str(archive_root or "").strip()
        self._archive_root = os.path.normpath(root) if root else ""
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
        self._placed_dirs = set()        # katalogi z ≥1 wciągniętym masterem, ze wszystkich biegów okna
        self._placed_n = 0               # ile masterów wciągnęły wszystkie biegi okna (z postępu)
        self._trouble = Counter()        # konflikty, błędy, niezgodne bajty - wszystkie biegi okna
        self._summary_fact = None        # zdanie o biegach; `done` dokłada do niego los przyjęcia
        self._close_after_apply = None   # kod zamknięcia zgłoszonego w biegu apply
        self._closing = False
        self._notice_state = ("", None)  # ostatni komunikat stanu - wraca, gdy pole przestaje odbiegać
        self.summary = None              # zdanie na pasek stanu gospodarza (None = nic się nie stało)
        self.harvested_root = None       # korzeń do przyjęcia - ustawia go WYŁĄCZNIE „Zamknij i przyjmij”
        self._shown_out = None           # wyjście WBPP pozycji w tabeli - kolumna pliku liczy się względem niego
        self._table_viewport = None      # viewport tabeli po budowie (filtr zdarzeń zmiany rozmiaru)
        self._first_pick_checked = False  # pierwsze użycie: wybór katalogu raz po pokazaniu (`showEvent`)
        self.setWindowTitle(i18n.t("harvest.title"))
        self.setModal(True)
        self.resize(980, 540)
        self._build_ui()
        self._show_archive()
        self.edit_output.setText(str(self._settings().value("harvest/last_output", "") or ""))
        self._on_output_edited()         # otwarcie z pamięci = zdarzenie dyskretne → auto-DRY

    # ---- budowa ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        hint = QLabel(i18n.t("harvest.hint"))
        hint.setProperty("role", "secondary")
        hint.setWordWrap(True)
        v.addWidget(hint)

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
        self.archive_warn = QLabel("")               # archiwum okna ≠ archiwum bazy (`_show_archive`)
        self.archive_warn.setProperty("role", "warn")
        self.archive_warn.setWordWrap(True)
        self.archive_warn.setVisible(False)
        v.addWidget(self.archive_warn)

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
        differs = bool(self._archive_root and self._db_archive
                       and norm_path(self._archive_root) != norm_path(self._db_archive))
        self.archive_warn.setText(i18n.t("harvest.archive_differs", db=self._db_archive)
                                  if differs else "")
        self.archive_warn.setVisible(differs)

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
        """Pierwsze użycie (brak `harvest/last_output`): od razu okno wyboru katalogu wyjścia, jak
        kafel Przyjmij przy pierwszej dostawie - puste pole i zdanie „Wskaż…” to jedna interakcja
        więcej do tego samego miejsca. Raz na okno, po pokazaniu (kolejka zdarzeń), żeby wybór
        stał nad oknem żniw, a nie przed nim; anulowanie zostawia okno z pustym polem."""
        super().showEvent(event)
        if not self._first_pick_checked:
            self._first_pick_checked = True
            if not str(self._settings().value("harvest/last_output", "") or ""):
                QTimer.singleShot(0, self._on_pick_output)

    # ---- szerokości (powód w kadrze, ścieżki odróżnialne) ----
    def _fit_columns(self):
        """Szerokości kolumn: wszystkie poza powodem za treścią; powód dostaje resztę viewportu
        (rozciąga się, gdy jest miejsce), a gdy reszty brakuje - swoją treść, przycięte tak, by
        razem z plikiem i stanem mieścił się w kadrze. Kolumny ścieżek na prawo wtedy przewijają
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
        left = self.table.columnWidth(COL_FILE) + self.table.columnWidth(COL_STATUS)
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
    def _on_pick_output(self):
        start = clean_path(self.edit_output.text()) or self._archive_root
        path = QFileDialog.getExistingDirectory(self, i18n.t("harvest.dlg.pick_output"), start)
        if path:
            self._set_output(path)

    def _set_output(self, path):
        """Ustaw pole wyjścia i sonduj - także tę samą ścieżkę co przed chwilą: wskazanie to jawna
        prośba o podgląd (seam testowy - bez `QFileDialog`)."""
        self.edit_output.setText(os.path.normpath(path))
        self._on_output_edited(force=True)

    def _on_pick_archive(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("harvest.dlg.pick_archive"),
                                                self._archive_root)
        if path:
            self._set_archive(path)

    def _set_archive(self, path):
        """Zmiana archiwum TYLKO dla tego okna: źródło Dostawy (`pipeline/last_source`) należy do
        strony Dostawy, a okno żniw nie przestawia jej po cichu następnej dostawy. Po pierwszej
        kopii archiwum jest zamrożone (`_sync_buttons`) - EXPECT, gdy ktoś obejdzie wygaszony
        przycisk. Seam testowy."""
        assert not self._placed_dirs, "archiwum zamrożone od pierwszego wciągniętego mastera"
        self._archive_root = os.path.normpath(path)
        self._show_archive()
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
        od pierwszego wciągniętego mastera. Archiwum zamrożone od tej samej chwili."""
        running = self._apply_worker is not None
        n = status_counts(self._plan.items).get("would-place", 0) if self._plan is not None else 0
        if self._plan is None and self._outcome is not None:
            self.btn_apply.setText(self._outcome)
        else:
            self.btn_apply.setText(i18n.t_plural("harvest.btn_apply", n))
        self.btn_apply.setEnabled(n > 0 and not running and not self._is_stale()
                                  and self._close_after_apply is None)
        placed = bool(self._placed_dirs)
        self.btn_accept.setVisible(placed)
        self.btn_accept.setEnabled(placed and self._close_after_apply is None)
        self.btn_archive.setEnabled(not placed and not running)
        self.btn_archive.setToolTip(i18n.t("harvest.archive_locked") if placed else "")

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
        self.edit_output.setEnabled(on)
        self.btn_pick.setEnabled(on)
        self.btn_archive.setEnabled(on and not self._placed_dirs)

    def _on_cancel_apply(self):
        if self._apply_worker is not None:
            self._apply_worker.request_cancel()      # rdzeń sprawdza PRZED następnym plikiem
            self.btn_cancel.setEnabled(False)
            self.progress_note.setText(i18n.t("harvest.cancelling"))

    @Slot(int, int, str, str)
    def _on_apply_progress(self, done_n, total, dst, status):
        """Postęp per plik - i JEDYNE źródło faktów biegu: katalog każdej opublikowanej kopii
        i licznik kłopotów wpadają tu, zanim rdzeń odda wynik, więc wyjątek po kopiach nie gubi
        tego, co już leży w archiwum. Przyjęcie dostępne od pierwszej kopii."""
        if self.busy.maximum() != total:
            self.busy.setRange(0, total)
        self.busy.setValue(done_n)
        self._apply_seen = (done_n, total)
        self._run_status[dst] = status
        if status == "placed":
            self._placed_dirs.add(os.path.dirname(dst))
            self._placed_n += 1
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
        """Zdanie paska stanu ze WSZYSTKICH biegów okna: drugi bieg z zerem po pierwszym
        z wciągnięciem mówiłby „nic nie wciągnięto” nad korzeniem, który gospodarz przyjmuje.
        Niezerowe konflikty, błędy i niezgodne bajty dochodzą do zdania (zera milczą) - pasek
        stanu to jedyny ślad po zamknięciu okna, a „wciągnięto 3” bez „konflikty: 1” kłamie
        o komplecie."""
        root = common_root(self._placed_dirs)
        if self._placed_n and root:
            fact = i18n.t_plural("harvest.status_placed", self._placed_n, root=root)
            if error:
                fact += " · " + i18n.t("harvest.status_error", msg=error)
        elif error:                                  # nic nie leży - błąd jest całą wiadomością
            fact = i18n.t("harvest.status_error", msg=error)
        else:
            fact = i18n.t("harvest.status_nothing", exists=c.get("exists", 0),
                          review=c.get("review", 0))
        for status, key in _TROUBLE_KEYS:
            if self._trouble[status]:
                fact += i18n.t(key, n=self._trouble[status])
        if cancelled_n:
            fact += i18n.t("harvest.cancelled_tail", n=cancelled_n)
        self._summary_fact = fact
        self.summary = fact

    # ---- przyjęcie i zamknięcie ----
    def _receivable_root(self):
        """Korzeń do przyjęcia albo zdanie odmowy. EXPECT na korzeniu, który pójdzie do skanu
        Dostawy: wspólny rodzic kopii MUSI leżeć pod `<archiwum>\\CALIBRATION` - inny korzeń
        (dwa wolumeny, archiwum zmienione obejściem blokady) kazałby Dostawie skanować coś, czego
        żniwa nie pisały."""
        root = common_root(self._placed_dirs)
        cal = os.path.join(self._archive_root, projection.CALIBRATION_SEGMENT) if self._archive_root else ""
        if root is None or not cal or not is_under(root, cal):
            return None, i18n.t("harvest.accept_refused", root=root or ", ".join(sorted(self._placed_dirs)),
                                cal=cal or "?")
        return root, None

    def _on_accept(self):
        """„Zamknij i przyjmij do archiwum”: korzeń dla gospodarza (strażnik `_receivable_root`)
        i zamknięcie. W biegu - zamknięcie po bieżącym pliku (`done`), a korzeń liczy się
        jeszcze raz przy zamknięciu, bo bieżący plik mógł dołożyć katalog."""
        root, why = self._receivable_root()
        if why is not None:
            self.harvested_root = None
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
        Świeża sonda po zamknięciu już nie startuje (`_closing`)."""
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
        if r == QDialog.Accepted and self.harvested_root is not None:
            self.harvested_root, _why = self._receivable_root()
        if self._summary_fact and self.harvested_root is None and self._placed_dirs:
            self.summary = self._summary_fact + self._later_tail()
        super().done(r)

    def _later_tail(self):
        """Kiedy baza pozna mastery, których nikt nie przyjął: przy następnej dostawie TYLKO wtedy,
        gdy wszystkie kopie leżą pod źródłem Dostawy (`pipeline/last_source`); inaczej Dostawa ich
        nie zobaczy i zdanie mówi, którędy do nich dojść."""
        source = str(self._settings().value("pipeline/last_source", "") or "").strip()
        if source and all(is_under(d, source) for d in self._placed_dirs):
            return i18n.t("harvest.status_later")
        return i18n.t("harvest.status_outside")
